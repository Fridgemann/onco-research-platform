import io
import json
import logging
import math
import re
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.security import decrypt_bytes
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.dataset import Dataset
from app.models.user import User  # noqa: F401 — needed for FK resolution
from app.models.workspace import Workspace, WorkspaceMember  # noqa: F401 — needed for FK resolution
from app.services.storage import _sync_download

import lifelines
from lifelines import KaplanMeierFitter
from lifelines.statistics import multivariate_logrank_test

logger = logging.getLogger(__name__)

# Celery workers are sync — use psycopg2 instead of asyncpg
_sync_url = settings.DATABASE_URL.replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)
_sync_engine = create_engine(_sync_url, pool_pre_ping=True)
SyncSession = sessionmaker(bind=_sync_engine)


def _set_job(session, job_id: str, **kwargs) -> None:
    result = session.execute(
        update(AnalysisJob)
        .where(AnalysisJob.id == job_id)
        .values(**kwargs)
        .execution_options(synchronize_session=False)
    )
    session.commit()
    if result.rowcount == 0:
        logger.error("_set_job: 0 rows updated for job_id=%s kwargs=%s", job_id, list(kwargs))


class AnalysisValidationError(ValueError):
    """A safe, developer-authored validation message meant to reach the user.

    Never raise this with dataset-derived values embedded (e.g. cell contents) —
    only column names, counts, and limits. A plain ValueError (including one
    raised by pandas/sklearn/lifelines, which may embed raw dataset content)
    is treated as unsafe and goes through the sanitized catch-all path in
    run_analysis_task instead of being logged/stored verbatim.
    """


def _check_columns(df: pd.DataFrame, *col_lists: list[str]) -> None:
    all_cols = [c for cols in col_lists for c in cols]
    missing = [c for c in all_cols if c not in df.columns]
    if missing:
        raise AnalysisValidationError(
            f"Column(s) not found: {missing}. "
            "Check the available columns listed in the analysis form."
        )


def _dropna_stats(df: pd.DataFrame, df_clean: pd.DataFrame) -> dict:
    total = len(df)
    used = len(df_clean)
    return {"total_rows": total, "used_rows": used, "dropped_rows": total - used}


_TOP_CODES_LIMIT = 5
_CODE_STRING_MAX_LEN = 32
_NORMALIZED_EXAMPLES_LIMIT = 3

# English-style grouped thousands only: 1-3 leading digits, then one or more
# ",ddd" groups of exactly 3 digits, optional decimal tail. Deliberately
# strict — "1,23" (wrong group size) and "1.234,56" (European decimal comma)
# do not match and are left as non-numeric/coded rather than guessed at.
#
# This assumes English number formatting (comma thousands separator, dot
# decimal point). It will misread European-formatted numbers (e.g. "1.234,56"
# meaning 1234.56) as non-numeric codes rather than parsing them — that's a
# locale question, not something this helper decides. Locale selection can be
# added later if a dataset needs it.
_ENGLISH_GROUPED_NUMBER_RE = re.compile(r"^[+-]?\d{1,3}(,\d{3})+(\.\d+)?$")


def _coerce_numeric(series: pd.Series) -> dict:
    """Coerce a column to numeric without assuming non-numeric values are junk.

    Values that fail conversion (e.g. 'ND', 'BLQ', '<5', assay flags) are kept
    separate from true missing values so callers can report both distinctly
    instead of silently dropping or misinterpreting them.

    Only one narrow, unambiguous formatting convention is auto-corrected:
    English-style thousands-grouped numbers (e.g. "1,234.56"). Everything
    else that fails plain numeric parsing — units, comparison operators,
    ambiguous locale formats, coded values — is reported, never guessed.
    """
    is_missing = series.isna()
    numeric = pd.to_numeric(series, errors="coerce")

    normalized_count = 0
    normalized_examples: list[dict] = []

    needs_retry = numeric.isna() & ~is_missing
    if needs_retry.any():
        candidates = series[needs_retry].astype(str).str.strip()
        looks_grouped = candidates.str.match(_ENGLISH_GROUPED_NUMBER_RE)
        if looks_grouped.any():
            grouped_candidates = candidates[looks_grouped]
            stripped = grouped_candidates.str.replace(",", "", regex=False)
            parsed = pd.to_numeric(stripped, errors="coerce")
            valid_parsed = parsed[~parsed.isna()]
            numeric.loc[valid_parsed.index] = valid_parsed.values

            normalized_count = int(len(valid_parsed))

            # Up to N examples, deduped by the *complete* raw value so a
            # frequently repeated value (e.g. "1,148" appearing 12 times)
            # doesn't fill the whole example list with copies of itself, and
            # two distinct long numbers sharing a prefix aren't conflated.
            # Display truncation happens separately, after dedup.
            raw_for_valid = grouped_candidates.loc[valid_parsed.index]
            seen: dict[str, float] = {}
            for raw_val, parsed_val in zip(raw_for_valid, valid_parsed):
                if raw_val not in seen:
                    seen[raw_val] = float(parsed_val)
                    if len(seen) >= _NORMALIZED_EXAMPLES_LIMIT:
                        break
            normalized_examples = [
                {
                    "raw": raw if len(raw) <= _CODE_STRING_MAX_LEN else raw[:_CODE_STRING_MAX_LEN - 3] + "...",
                    "parsed": parsed_val,
                }
                for raw, parsed_val in seen.items()
            ]

    is_valid = ~numeric.isna()
    is_bad_code = ~is_valid & ~is_missing

    codes = (
        series[is_bad_code]
        .astype(str)
        .str.slice(0, _CODE_STRING_MAX_LEN)
        .value_counts()
        .head(_TOP_CODES_LIMIT)
    )

    return {
        "values": numeric[is_valid],
        # Full-index coerced series (normalization applied, NaN where the
        # value was missing or non-numeric). Callers slice this on a JOINT
        # validity mask so multiple columns stay row-aligned — never on this
        # column's own is_valid mask alone.
        "coerced": numeric,
        "is_valid": is_valid,
        "missing_rows": int(is_missing.sum()),
        "non_numeric_rows": int(is_bad_code.sum()),
        "top_non_numeric_codes": {str(k): int(v) for k, v in codes.items()},
        "normalized_rows": normalized_count,
        "normalized_rule": "english_thousands_grouping" if normalized_count else None,
        "normalized_examples": normalized_examples,
    }


def _numeric_processing_report(role: str, coerced: dict) -> dict:
    """Per-column processing summary for a numeric-role column.

    Shared shape across every analysis (Milestone 2): role, missing count,
    and the non-numeric / normalization detail that only applies to numeric
    roles. Categorical roles use _categorical_processing_report instead and
    never carry non_numeric fields.
    """
    return {
        "role": role,
        "missing": coerced["missing_rows"],
        "non_numeric": coerced["non_numeric_rows"],
        "top_non_numeric_codes": coerced["top_non_numeric_codes"],
        "normalized": coerced["normalized_rows"],
        "normalized_rule": coerced["normalized_rule"],
        "normalized_examples": coerced["normalized_examples"],
    }


def _categorical_processing_report(series: pd.Series, role: str) -> tuple[pd.Series, dict]:
    """Validity mask + processing summary for a categorical-role column.

    Original labels are preserved untouched — only genuinely missing values
    (NaN) are invalid. Valid non-numeric text (class labels, group names) is
    NEVER reported as "non-numeric"; that field is omitted entirely here.
    Returns (full_index_is_valid_mask, report).
    """
    is_valid = series.notna()
    report = {"role": role, "missing": int((~is_valid).sum())}
    return is_valid, report


_BINARY_CODES = {0.0, 1.0}


def _binary_code_counts(values: pd.Series) -> dict | None:
    """If the usable values are exactly {0, 1} — both present, nothing else —
    return count/percent for each code.

    Exact equality, not subset: a column with only 0s (or only 1s) is a
    constant column, not a demonstrated binary code, and is left as a plain
    numeric column rather than presented as if it were binary-coded.

    Never guesses what 0/1 *mean* (yes/no, male/female, etc.) — that's for
    the researcher's own dataset documentation, not something this platform
    infers from a column name or value pattern.
    """
    unique_vals = set(values.unique())
    if unique_vals != _BINARY_CODES:
        return None

    total = int(values.count())
    count_0 = int((values == 0.0).sum())
    count_1 = int((values == 1.0).sum())
    return {
        "coded_0": {"count": count_0, "percent": (count_0 / total * 100) if total else 0.0},
        "coded_1": {"count": count_1, "percent": (count_1 / total * 100) if total else 0.0},
    }


def _run_descriptive_stats(df: pd.DataFrame, params: dict) -> dict:
    columns = params.get("columns") or df.select_dtypes(include=[np.number]).columns.tolist()
    _check_columns(df, columns)

    result: dict = {}
    joint_valid = pd.Series(True, index=df.index)

    for col in columns:
        coerced = _coerce_numeric(df[col])
        values = coerced["values"]
        if values.empty:
            raise AnalysisValidationError(f"Column '{col}' has no usable numeric values.")

        binary_counts = _binary_code_counts(values)

        result[col] = {
            "count": int(values.count()),
            "mean": float(values.mean()),
            "std": float(values.std()),
            "min": float(values.min()),
            "p25": float(values.quantile(0.25)),
            "median": float(values.median()),
            "p75": float(values.quantile(0.75)),
            "max": float(values.max()),
            "missing": coerced["missing_rows"],
            "non_numeric": coerced["non_numeric_rows"],
            "top_non_numeric_codes": coerced["top_non_numeric_codes"],
            "normalized": coerced["normalized_rows"],
            "normalized_rule": coerced["normalized_rule"],
            "normalized_examples": coerced["normalized_examples"],
            "is_binary": binary_counts is not None,
            "binary_counts": binary_counts,
        }
        joint_valid &= coerced["is_valid"]

    result["_meta"] = _dropna_stats(df, df[joint_valid])
    return result


_MAX_FEATURE_COLS = 50


def _run_regression(df: pd.DataFrame, params: dict) -> dict:
    from scipy.stats import linregress

    target_col = params["target_column"]
    feature_cols = params["feature_columns"]
    if len(feature_cols) > _MAX_FEATURE_COLS:
        raise AnalysisValidationError(f"Too many feature columns ({len(feature_cols)}); maximum is {_MAX_FEATURE_COLS}.")

    _check_columns(df, [target_col], feature_cols)

    # Linear regression: target AND every feature are numeric roles. Coerce
    # each, then align on a single joint validity mask so every column keeps
    # the same original rows — never filter columns independently.
    coerced: dict[str, dict] = {}
    processing: dict[str, dict] = {}
    joint_valid = pd.Series(True, index=df.index)
    for col, role in [(target_col, "target")] + [(f, "feature") for f in feature_cols]:
        c = _coerce_numeric(df[col])
        coerced[col] = c
        processing[col] = _numeric_processing_report(role, c)
        joint_valid &= c["is_valid"]

    meta = _dropna_stats(df, df[joint_valid])
    if not bool(joint_valid.any()):
        raise AnalysisValidationError(
            "No rows have usable numeric values across the target and all feature columns."
        )

    y = coerced[target_col]["coerced"][joint_valid].to_numpy()

    if len(feature_cols) == 1:
        x = coerced[feature_cols[0]]["coerced"][joint_valid].to_numpy()
        slope, intercept, r_value, p_value, std_err = linregress(x, y)
        return {
            "type": "linear",
            "feature": feature_cols[0],
            "slope": float(slope),
            "intercept": float(intercept),
            "r_squared": float(r_value**2),
            "p_value": float(p_value),
            "std_err": float(std_err),
            "n": len(y),
            "processing": processing,
            "_meta": meta,
        }

    feature_matrix = np.column_stack(
        [coerced[f]["coerced"][joint_valid].to_numpy() for f in feature_cols]
    )
    X = np.column_stack([np.ones(len(y)), feature_matrix])
    coeffs = np.linalg.lstsq(X, y, rcond=None)[0]
    y_pred = X @ coeffs
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    return {
        "type": "multiple_linear",
        "features": feature_cols,
        "intercept": float(coeffs[0]),
        "coefficients": {f: float(c) for f, c in zip(feature_cols, coeffs[1:])},
        "r_squared": float(1 - ss_res / ss_tot),
        "n": len(y),
        "processing": processing,
        "_meta": meta,
    }


_KM_ABSOLUTE_MAX_GROUPS = settings.KM_ABSOLUTE_MAX_GROUPS
_KM_MAX_UNIQUE_TIMES = settings.KM_MAX_UNIQUE_TIMES

# ── Kaplan-Meier event/censoring mapping ────────────────────────────────────
#
# The censoring status of each row is resolved through an explicit, typed
# mapping — never inferred from the duration, and never by treating "not an
# event" as censored. Values are matched by a normalized (value_type, value)
# key rather than raw Python equality, because Python's `True == 1` and
# `False == 0` would otherwise conflate booleans with the numbers 0/1.

_KM_SUPPORTED_VALUE_TYPES = {"boolean", "number", "string"}
_KM_MAPPING_ROLES = {"event", "censored", "exclude"}

# Only these exact keys auto-map; strings "1"/"0" deliberately never do.
_KM_AUTO_MAP = {
    ("boolean", True): "event",
    ("boolean", False): "censored",
    ("number", 1.0): "event",
    ("number", 0.0): "censored",
}


def _normalize_mapping_key(value, value_type: str) -> tuple:
    """Normalize a mapping entry's declared value into a match key.

    Raises AnalysisValidationError (no raw value echoed) for unsupported
    types, type/value mismatches, or non-finite numbers.
    """
    if value_type == "boolean":
        if not isinstance(value, bool):
            raise AnalysisValidationError("A boolean event-mapping entry must be true or false.")
        return ("boolean", bool(value))
    if value_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AnalysisValidationError("A numeric event-mapping entry must be a number.")
        if not math.isfinite(value):
            raise AnalysisValidationError("A numeric event-mapping entry must be a finite number.")
        return ("number", float(value))
    if value_type == "string":
        if not isinstance(value, str):
            raise AnalysisValidationError("A string event-mapping entry must be text.")
        return ("string", value)
    raise AnalysisValidationError("Unsupported value_type in event mapping.")


def _cell_status_key(cell) -> tuple | None:
    """Normalize a raw status cell into a match key, or None if unusable.

    Booleans are checked before numbers on purpose: isinstance(True, int) is
    True in Python, so a bool must resolve to ("boolean", ...) and never to
    ("number", 1.0). Non-finite numbers and unsupported types return None.
    """
    if isinstance(cell, (bool, np.bool_)):
        return ("boolean", bool(cell))
    if isinstance(cell, (int, float, np.integer, np.floating)):
        f = float(cell)
        return ("number", f) if math.isfinite(f) else None
    if isinstance(cell, str):
        return ("string", cell)
    return None


def _build_event_mapping(event_mapping: list) -> dict:
    """Turn a list of {value, value_type, role} entries into a key->role dict.

    Rejects duplicate or conflicting keys and invalid roles/types. No raw
    values appear in any error message.
    """
    resolved: dict[tuple, str] = {}
    for entry in event_mapping:
        role = entry.get("role")
        if role not in _KM_MAPPING_ROLES:
            raise AnalysisValidationError("Each event-mapping role must be Event, Censored, or Exclude.")
        key = _normalize_mapping_key(entry.get("value"), entry.get("value_type"))
        if key in resolved:
            raise AnalysisValidationError("Duplicate or conflicting event-mapping entries for a status value.")
        resolved[key] = role
    return resolved


def _classify_km_status(series: pd.Series, mapping: dict) -> tuple[pd.Series, int]:
    """Classify every status cell into event / censored / excluded / unmapped / missing.

    Explicit mapping wins over auto-mapping. Returns a full-index role Series
    plus the count of DISTINCT unmapped values (for a value-free error).
    """
    roles = pd.Series("missing", index=series.index, dtype=object)
    unmapped_keys: set = set()
    for idx, cell in series.items():
        if pd.isna(cell):
            continue
        key = _cell_status_key(cell)
        role = mapping.get(key) if key is not None else None
        if role is None and key is not None:
            role = _KM_AUTO_MAP.get(key)
        if role is None:
            roles.at[idx] = "unmapped"
            unmapped_keys.add(key if key is not None else ("__unsupported__",))
        elif role == "exclude":
            roles.at[idx] = "excluded"
        else:
            roles.at[idx] = role  # "event" or "censored"
    return roles, len(unmapped_keys)


def _median_or_none(kmf: "KaplanMeierFitter") -> float | None:
    """Median survival, or None when the curve never reaches 0.5 ("not reached")."""
    m = kmf.median_survival_time_
    return float(m) if np.isfinite(m) else None


def _assert_json_safe(result: dict) -> None:
    """Reject any NaN/Infinity before the result can be persisted.

    Strict serialization is the guarantee that a non-finite statistic never
    reaches the database or the frontend; the caller raises through the
    sanitized task error path if this fails.
    """
    json.dumps(result, allow_nan=False)


# Pilot-grade KM statistical conventions surfaced in every result.
_KM_CI_METHOD = "exponential_greenwood_log_log"
_KM_CI_LEVEL = 0.95
_KM_AT_RISK_CONVENTION = "immediately_before"  # lifelines event_table at_risk
_KM_ASSUMPTIONS = [
    "Censoring is assumed non-informative (independent of the event process).",
    "Observations are assumed independent.",
    "All subjects are assumed to share a consistently defined time origin and a "
    "single, consistently defined event.",
    "Estimates are descriptive of this cohort, not causal.",
    "A censored observation means the subject was event-free up to that time; "
    "their status afterward is unknown.",
    "Competing events (other outcomes that prevent the event of interest) are "
    "treated as ordinary censoring, which can bias the estimate.",
    "Confidence intervals are pointwise 95% intervals (Greenwood variance with a "
    "log-log transformation), not simultaneous confidence bands.",
    "The log-rank test assesses whether survival curves differ; it does not "
    "quantify the size or direction of any difference, and can miss or mislead "
    "when curves cross or hazards are non-proportional.",
    "Survival beyond the largest observed time is undefined.",
]


def _group_label_and_type(value) -> tuple:
    """Return a JSON-safe (label, value_type) for a group value, preserving type.

    Keeps numeric 1 distinct from string "1" so the collision-safe groups list
    never conflates them.
    """
    key = _cell_status_key(value)
    if key is None:
        return (str(value), "string")
    return (key[1], key[0])


def _km_curve_payload(durations: pd.Series, event_observed: pd.Series) -> dict:
    """Fit one KM curve and return curve, pointwise CI, median, counts, at-risk table.

    at_risk is the number at risk immediately before each time point
    (lifelines event_table convention), documented via _KM_AT_RISK_CONVENTION.
    """
    kmf = KaplanMeierFitter()
    # alpha passed explicitly (95% CI) rather than relying on the library default.
    kmf.fit(durations=durations, event_observed=event_observed, alpha=1 - _KM_CI_LEVEL)
    ci = kmf.confidence_interval_  # exponential Greenwood + log-log (lifelines default)
    et = kmf.event_table
    events = pd.Series(event_observed).astype(bool)

    # Explicit censor coordinates so the frontend can place tick marks without
    # reconstructing any statistic: survival value at each time where >=1
    # censoring occurred (excluding the synthetic t=0 row).
    censor_marks = []
    for t, row in et.iterrows():
        if t > 0 and int(row["censored"]) > 0:
            censor_marks.append({
                "time": float(t),
                "survival_probability": float(kmf.predict(t)),
                "count": int(row["censored"]),
            })

    return {
        "timeline": kmf.survival_function_.index.tolist(),
        "survival_probability": kmf.survival_function_["KM_estimate"].tolist(),
        "ci_lower": ci.iloc[:, 0].tolist(),
        "ci_upper": ci.iloc[:, 1].tolist(),
        "median_survival": _median_or_none(kmf),
        "n": int(len(durations)),
        "n_events": int(events.sum()),
        "n_censored": int((~events).sum()),
        "risk_table": {
            "time": et.index.tolist(),
            "at_risk": et["at_risk"].tolist(),
            "events": et["observed"].tolist(),
            "censored": et["censored"].tolist(),
        },
        "censor_marks": censor_marks,
    }


def _km_reproducibility(params: dict) -> dict:
    """Reproducibility metadata: parameters, library/version, CI method/level."""
    return {
        "parameters": {
            "time_column": params.get("time_column"),
            "event_column": params.get("event_column"),
            "group_column": params.get("group_column"),
            "has_censoring": params.get("has_censoring", True),
            "event_mapping": params.get("event_mapping") or [],
            "all_events_confirmed": bool(params.get("all_events_confirmed", False)),
            "max_groups": params.get("max_groups"),
        },
        "library": "lifelines",
        "library_version": lifelines.__version__,
        "ci_method": _KM_CI_METHOD,
        "ci_level": _KM_CI_LEVEL,
        "at_risk_convention": _KM_AT_RISK_CONVENTION,
    }


_KM_MAX_STATUS_VALUES = 50      # a censoring indicator shouldn't have many distinct values
_KM_MAX_MAPPING_ENTRIES = 200


def _status_value_payload(key: tuple, count: int, mapping: dict) -> dict:
    """Build a UI-facing status-value entry preserving the original type.

    Returned to the authenticated dataset member only (never logged/audited).
    """
    if key == ("__unsupported__",):
        value, value_type = None, "unsupported"
    else:
        value_type, value = key[0], key[1]
    if key in mapping:
        role = mapping[key]  # "event" | "censored" | "exclude"
    else:
        auto = _KM_AUTO_MAP.get(key)
        role = f"auto_{auto}" if auto else "unmapped"
    return {"value": value, "value_type": value_type, "count": count, "role": role}


def _km_classify_and_count(df: pd.DataFrame, params: dict) -> dict:
    """Resolve KM data preparation WITHOUT raising on fixable data-content states.

    Single source of truth for both the run path (_km_prepare, which raises
    when not ready) and the preflight endpoint (_km_preflight, which reports).
    Genuine request-shape errors (unknown column, malformed/oversized mapping,
    too many distinct status values) still raise AnalysisValidationError.
    Fixable data states (unmapped values, missing all-events confirmation,
    missing status column, no usable rows) are returned as `blockers` with
    `ready=False`. No raw cell values appear in any raised message.
    """
    time_col = params["time_column"]
    group_col = params.get("group_column")
    has_censoring = params.get("has_censoring", True)
    event_col = params.get("event_column")
    event_mapping = params.get("event_mapping") or []
    all_events_confirmed = bool(params.get("all_events_confirmed", False))

    if len(event_mapping) > _KM_MAX_MAPPING_ENTRIES:
        raise AnalysisValidationError("Too many event-mapping entries.")

    needed = [time_col] + ([group_col] if group_col else [])
    if has_censoring and event_col:
        needed.append(event_col)
    _check_columns(df, needed)

    processing: dict[str, dict] = {}
    joint = pd.Series(True, index=df.index)
    blockers: list[str] = []

    dur = _coerce_numeric(df[time_col])
    processing[time_col] = _numeric_processing_report("duration", dur)
    joint &= dur["is_valid"]

    missing_group = 0
    if group_col:
        group_valid, processing[group_col] = _categorical_processing_report(df[group_col], "group")
        joint &= group_valid
        missing_group = int((~group_valid).sum())

    missing_status = 0
    explicitly_excluded = 0
    status_values: list[dict] = []
    event_observed_full = None

    if has_censoring:
        if not event_col:
            blockers.append("no_status_column")
        else:
            mapping = _build_event_mapping(event_mapping)  # raises on bad entries
            roles, n_unmapped = _classify_km_status(df[event_col], mapping)

            # Distinct-value payload for the mapping UI (typed, capped).
            counts_by_key: dict[tuple, int] = {}
            for cell in df[event_col]:
                if pd.isna(cell):
                    continue
                k = _cell_status_key(cell)
                k = k if k is not None else ("__unsupported__",)
                counts_by_key[k] = counts_by_key.get(k, 0) + 1
            if len(counts_by_key) > _KM_MAX_STATUS_VALUES:
                raise AnalysisValidationError(
                    "Status column has too many distinct values to be a censoring "
                    f"indicator (max {_KM_MAX_STATUS_VALUES})."
                )
            status_values = [
                _status_value_payload(k, c, mapping) for k, c in counts_by_key.items()
            ]

            missing_status = int((roles == "missing").sum())
            explicitly_excluded = int((roles == "excluded").sum())
            status_valid = roles.isin(["event", "censored"])
            joint &= status_valid
            event_observed_full = (roles == "event")
            processing[event_col] = {"role": "event", "missing": missing_status}
            if n_unmapped > 0:
                blockers.append("unmapped_values")
    else:
        if not all_events_confirmed:
            blockers.append("needs_all_events_confirmation")
        # Projection: every usable row is an observed event.
        event_observed_full = pd.Series(True, index=df.index)

    total = len(df)
    used = int(joint.sum())
    if used == 0:
        blockers.append("no_usable_rows")

    if event_observed_full is not None:
        event_observed = event_observed_full[joint].astype(bool)
        events = int(event_observed.sum())
        censored = used - events
    else:
        event_observed = None
        events = censored = 0

    n_unmapped_total = sum(1 for v in status_values if v["role"] == "unmapped")

    counts = {
        "total_rows": total,
        "used_rows": used,
        "excluded_rows": total - used,
        "events": events,
        "censored": censored,
        "censoring_percentage": (censored / used * 100.0) if used else 0.0,
        # Per-reason counts may overlap (a row can be invalid for several
        # reasons); excluded_rows above counts each excluded row only once.
        "exclusions": {
            "missing_duration": int(dur["missing_rows"]),
            "invalid_duration": int(dur["non_numeric_rows"]),
            "missing_status": missing_status,
            "missing_group": missing_group,
            "explicitly_excluded": explicitly_excluded,
        },
        "unmapped_values": n_unmapped_total,
    }

    return {
        "durations": dur["coerced"][joint],
        "event_observed": event_observed,
        "groups": df[group_col][joint] if group_col else None,
        "processing": processing,
        "meta": _dropna_stats(df, df[joint]),
        "counts": counts,
        "status_values": status_values,
        "joint_valid": joint,
        "blockers": blockers,
        "ready": not blockers,
    }


_KM_BLOCKER_MESSAGES = {
    "no_status_column": "A status column is required when the dataset contains censored observations.",
    "unmapped_values": "Some status values are unmapped. Map each remaining value to Event, Censored, or Exclude.",
    "needs_all_events_confirmation": (
        "Enable censoring and provide a status column, or explicitly confirm that "
        "every included row is an observed event."
    ),
    "no_usable_rows": "No rows have usable values across the selected columns.",
}


def _km_prepare(df: pd.DataFrame, params: dict) -> dict:
    """Run-path KM prep: classify, then REJECT if not ready (backend authority).

    The Celery task and any direct API submit always go through this, so a
    frontend that skips preflight cannot bypass validation.
    """
    resolved = _km_classify_and_count(df, params)
    if not resolved["ready"]:
        first = resolved["blockers"][0]
        raise AnalysisValidationError(_KM_BLOCKER_MESSAGES.get(first, "Invalid Kaplan-Meier configuration."))
    return resolved


def _km_preflight(df: pd.DataFrame, params: dict) -> dict:
    """Preflight report: same counts as the run, without raising on fixable states."""
    resolved = _km_classify_and_count(df, params)
    return {
        "ready": resolved["ready"],
        "blockers": resolved["blockers"],
        "counts": resolved["counts"],
        "status_values": resolved["status_values"],
    }


def _run_kaplan_meier(df: pd.DataFrame, params: dict) -> dict:
    prep = _km_prepare(df, params)
    durations = prep["durations"]
    event_observed = prep["event_observed"]
    groups = prep["groups"]
    processing = prep["processing"]
    meta = prep["meta"]
    group_col = params.get("group_column")

    unique_times = durations.nunique()
    if unique_times > _KM_MAX_UNIQUE_TIMES:
        raise AnalysisValidationError(
            f"Time column has {unique_times} unique values (max {_KM_MAX_UNIQUE_TIMES}). "
            "Round timestamps to whole days or months to reduce resolution."
        )

    common = {
        "processing": processing,
        "_meta": meta,
        "counts": prep["counts"],
        "reproducibility": _km_reproducibility(params),
        "assumptions": _KM_ASSUMPTIONS,
    }

    # Curves live in a `groups` LIST (not top-level keys), so a group label
    # like "counts" or "comparison", or a numeric 1 vs string "1", can never
    # collide with metadata keys or each other.
    if not group_col:
        result = {
            "grouped": False,
            "groups": [{
                "label": "overall",
                "value_type": "overall",
                "curve": _km_curve_payload(durations, event_observed),
            }],
            "comparison": None,
            **common,
        }
        _assert_json_safe(result)
        return result

    requested_max = int(params.get("max_groups", _KM_ABSOLUTE_MAX_GROUPS))
    effective_max = min(requested_max, _KM_ABSOLUTE_MAX_GROUPS)

    unique_groups = groups.unique()
    if len(unique_groups) > effective_max:
        raise AnalysisValidationError(
            f"Group column has {len(unique_groups)} unique values, "
            f"exceeds your limit of {requested_max} "
            f"(server maximum: {_KM_ABSOLUTE_MAX_GROUPS}). "
            "Use a categorical column with fewer distinct values."
        )

    groups_out = []
    for group in unique_groups:
        group_mask = groups == group
        label, value_type = _group_label_and_type(group)
        groups_out.append({
            "label": label,
            "value_type": value_type,
            "curve": _km_curve_payload(durations[group_mask], event_observed[group_mask]),
        })

    result = {"grouped": True, "groups": groups_out, "comparison": _km_comparison(durations, groups, event_observed, len(unique_groups)), **common}
    _assert_json_safe(result)
    return result


def _km_comparison(durations: pd.Series, groups: pd.Series, event_observed: pd.Series, n_groups: int) -> dict:
    """Multivariate (Mantel-Cox) log-rank comparison, or a reason it is unavailable.

    Never returns a spurious chi-square=0 / p=1 for degenerate inputs.
    """
    if n_groups < 2:
        return {"available": False, "reason": "insufficient_groups"}
    if int(pd.Series(event_observed).astype(bool).sum()) == 0:
        return {"available": False, "reason": "no_observed_events"}
    try:
        lr = multivariate_logrank_test(durations, groups, event_observed)
    except Exception:
        # Defensive: never let a comparison failure crash the whole KM run
        # (e.g. degenerate/pathological group arrays the library can't handle).
        return {"available": False, "reason": "undefined"}
    if not (np.isfinite(lr.test_statistic) and np.isfinite(lr.p_value)):
        return {"available": False, "reason": "undefined"}
    return {
        "available": True,
        "test": "logrank",
        "chi_square": float(lr.test_statistic),
        "degrees_of_freedom": int(lr.degrees_of_freedom),
        "p_value": float(lr.p_value),
    }




def _run_logistic_regression(df: pd.DataFrame, params: dict) -> dict:
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score, accuracy_score

    target_col = params["target_column"]
    feature_cols = params["feature_columns"]
    if len(feature_cols) > _MAX_FEATURE_COLS:
        raise AnalysisValidationError(f"Too many feature columns ({len(feature_cols)}); maximum is {_MAX_FEATURE_COLS}.")

    _check_columns(df, [target_col], feature_cols)

    # Features are numeric roles (coerce + normalize); the target is a
    # categorical role — its original class labels are preserved exactly and
    # never sent through numeric coercion. All columns align on one joint mask.
    processing: dict[str, dict] = {}
    joint_valid = pd.Series(True, index=df.index)

    target_valid, processing[target_col] = _categorical_processing_report(df[target_col], "target")
    joint_valid &= target_valid

    coerced: dict[str, dict] = {}
    for col in feature_cols:
        c = _coerce_numeric(df[col])
        coerced[col] = c
        processing[col] = _numeric_processing_report("feature", c)
        joint_valid &= c["is_valid"]

    meta = _dropna_stats(df, df[joint_valid])
    if not bool(joint_valid.any()):
        raise AnalysisValidationError(
            "No rows have usable values across the target and all feature columns."
        )

    y = df[target_col][joint_valid].to_numpy()
    X = np.column_stack(
        [coerced[f]["coerced"][joint_valid].to_numpy() for f in feature_cols]
    )

    # Binary classification only — require exactly two classes remaining after
    # joint filtering. Fewer than two means the outcome has no contrast to
    # model; more than two is unsupported (the result shape assumes binary).
    n_classes = pd.Series(y).nunique()
    if n_classes != 2:
        raise AnalysisValidationError(
            f"Logistic regression requires exactly two outcome classes after "
            f"excluding unusable rows; found {n_classes}."
        )

    model = LogisticRegression(max_iter=1000)
    model.fit(X, y)

    y_pred = model.predict(X)
    accuracy = float(accuracy_score(y, y_pred))

    auc = None
    try:
        if len(model.classes_) == 2:
            auc = float(roc_auc_score(y, model.predict_proba(X)[:, 1]))
    except Exception:
        pass

    return {
        "type": "logistic",
        "target": target_col,
        "features": feature_cols,
        "intercept": float(model.intercept_[0]),
        "coefficients": {f: float(c) for f, c in zip(feature_cols, model.coef_[0])},
        "accuracy": accuracy,
        "auc": auc,
        "n": len(y),
        "classes": model.classes_.tolist(),
        "processing": processing,
        "_meta": meta,
    }


@celery_app.task(bind=True, name="run_analysis")
def run_analysis_task(self, job_id: str):
    with SyncSession() as session:
        job = session.get(AnalysisJob, job_id)
        if not job:
            logger.error("Job %s not found in DB", job_id)
            return

        logger.info("Job %s found: type=%s dataset=%s", job_id, job.job_type, job.dataset_id)
        dataset_id = job.dataset_id
        job_type = job.job_type
        parameters = job.parameters

        _set_job(session, job_id,
                 status=JobStatus.RUNNING,
                 started_at=datetime.now(timezone.utc))

        try:
            dataset = session.get(Dataset, dataset_id)
            raw = _sync_download(dataset.object_key)
            df = pd.read_csv(io.StringIO(decrypt_bytes(raw).decode("utf-8")), index_col=False)
            df = df.loc[:, ~df.columns.str.match(r"^Unnamed: \d+$")]
            params = json.loads(parameters or "{}")

            dispatch = {
                "kaplan_meier": _run_kaplan_meier,
                "regression": _run_regression,
                "descriptive_stats": _run_descriptive_stats,
                "logistic_regression": _run_logistic_regression,
            }
            result = dispatch[job_type](df, params)

            # Strict serialization: a NaN/Infinity anywhere in the result
            # raises here and routes to the sanitized failure path rather than
            # persisting a non-finite statistic.
            _set_job(session, job_id,
                     status=JobStatus.COMPLETED,
                     result=json.dumps(result, allow_nan=False),
                     completed_at=datetime.now(timezone.utc))
            logger.info("Job %s completed successfully", job_id)

        except AnalysisValidationError as exc:
            # Developer-authored message (column names/counts/limits only,
            # never dataset cell values) — safe to log and store verbatim.
            logger.warning("Job %s validation error: %s", job_id, exc)
            _set_job(session, job_id,
                     status=JobStatus.FAILED,
                     error_message=str(exc)[:512],
                     completed_at=datetime.now(timezone.utc))
        except Exception as exc:
            # Any other exception — including plain ValueError, which pandas/
            # sklearn/lifelines can raise with dataset-derived values embedded
            # in the message (e.g. an object-column .mean() call concatenating
            # a whole string column into the error text). Never log str(exc)
            # or use exc_info here, and never let the original exception
            # object propagate: logger.exception's traceback rendering, and
            # Celery's own task-failure logging, would both print it in full
            # regardless of how our own log message is formatted.
            logger.error(
                "Job %s failed: job_type=%s exception_class=%s",
                job_id, job_type, type(exc).__name__,
            )
            _set_job(session, job_id,
                     status=JobStatus.FAILED,
                     error_message="Analysis failed. Check that column names exist and contain numeric data.",
                     completed_at=datetime.now(timezone.utc))
            raise RuntimeError(
                "Analysis job failed; dataset-derived exception text suppressed"
            ) from None
