"""
Shared analysis preparation and profiling.

This module is deliberately neutral — it imports nothing from Celery, the
task module, or the API layer — so the worker and the HTTP routes run the
*same* preparation code rather than two implementations that can drift.

The split follows the convention established for Kaplan-Meier in Milestone 3:

  * `prepare_*` / `_km_classify_and_count` are **non-raising** for fixable
    data states. They report `blockers` (and `empty_columns` for descriptive)
    so a preflight endpoint can explain the problem instead of erroring.
  * Request-shape problems — an unknown column, too many features, a
    malformed mapping — still raise `AnalysisValidationError` immediately.
  * The run path (`_km_prepare`, and the `_run_*` functions in
    `app.tasks.analysis`) rejects anything not ready, so the backend stays
    authoritative even if a client skips preflight.

No dataset-derived cell value may appear in a raised message, a log, or an
audit record; typed values are returned in payloads only, for the
authenticated member who already has access to the data.
"""
import json
import math
import re

import numpy as np
import pandas as pd

from app.core.config import settings


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


def _assert_json_safe(result: dict) -> None:
    """Reject any NaN/Infinity before the result can be persisted.

    Strict serialization is the guarantee that a non-finite statistic never
    reaches the database or the frontend; the caller raises through the
    sanitized task error path if this fails.
    """
    json.dumps(result, allow_nan=False)


_MAX_FEATURE_COLS = 50

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


# ── Descriptive / regression / logistic preparation ─────────────────────────
#
# Lifted out of the corresponding _run_* functions so the preflight endpoints
# and the Celery run share one implementation. Non-raising for data states.


def prepare_descriptive(df: pd.DataFrame, params: dict) -> dict:
    """Per-column preparation for descriptive statistics.

    Descriptive stats compute each column on its OWN usable rows, so counts
    are reported per column — a single joint used/excluded pair would
    misrepresent what the analysis actually does. The joint mask is still
    returned because `_meta` reports cohort-level row accounting.
    """
    columns = params.get("columns") or df.select_dtypes(include=[np.number]).columns.tolist()
    _check_columns(df, columns)

    total = len(df)
    per_column: dict[str, dict] = {}
    counts_by_column: dict[str, dict] = {}
    empty_columns: list[str] = []
    joint_valid = pd.Series(True, index=df.index)

    for col in columns:
        coerced = _coerce_numeric(df[col])
        values = coerced["values"]
        used = int(values.count())

        per_column[col] = {"coerced": coerced, "values": values}
        counts_by_column[col] = {
            "used_rows": used,
            "excluded_rows": total - used,
            "missing_rows": coerced["missing_rows"],
            "non_numeric_rows": coerced["non_numeric_rows"],
        }
        if values.empty:
            empty_columns.append(col)
        joint_valid &= coerced["is_valid"]

    blockers = ["column_has_no_usable_values"] if empty_columns else []

    return {
        "columns": columns,
        "per_column": per_column,
        "counts_by_column": counts_by_column,
        "empty_columns": empty_columns,
        "joint_valid": joint_valid,
        "meta": _dropna_stats(df, df[joint_valid]),
        "blockers": blockers,
        "ready": not blockers,
    }


def _joint_numeric_counts(df: pd.DataFrame, joint_valid: pd.Series,
                          any_missing: pd.Series, any_non_numeric: pd.Series) -> dict:
    """Row accounting for analyses that require every column on the same row.

    Per-reason counts are row-level and may overlap (one row can be both
    missing in one column and non-numeric in another); `excluded_rows`
    counts each excluded row exactly once.
    """
    total = len(df)
    used = int(joint_valid.sum())
    return {
        "total_rows": total,
        "used_rows": used,
        "excluded_rows": total - used,
        "exclusions": {
            "missing": int(any_missing.sum()),
            "non_numeric": int(any_non_numeric.sum()),
        },
    }


def prepare_regression(df: pd.DataFrame, params: dict) -> dict:
    """Joint-row preparation for linear regression (target + all features numeric)."""
    target_col = params["target_column"]
    feature_cols = params["feature_columns"]
    if len(feature_cols) > _MAX_FEATURE_COLS:
        raise AnalysisValidationError(
            f"Too many feature columns ({len(feature_cols)}); maximum is {_MAX_FEATURE_COLS}."
        )

    _check_columns(df, [target_col], feature_cols)

    coerced: dict[str, dict] = {}
    processing: dict[str, dict] = {}
    joint_valid = pd.Series(True, index=df.index)
    any_missing = pd.Series(False, index=df.index)
    any_non_numeric = pd.Series(False, index=df.index)

    for col, role in [(target_col, "target")] + [(f, "feature") for f in feature_cols]:
        c = _coerce_numeric(df[col])
        coerced[col] = c
        processing[col] = _numeric_processing_report(role, c)
        joint_valid &= c["is_valid"]

        is_missing = df[col].isna()
        any_missing |= is_missing
        any_non_numeric |= (~c["is_valid"] & ~is_missing)

    counts = _joint_numeric_counts(df, joint_valid, any_missing, any_non_numeric)
    blockers = [] if counts["used_rows"] else ["no_usable_rows"]

    return {
        "target_col": target_col,
        "feature_cols": feature_cols,
        "coerced": coerced,
        "processing": processing,
        "joint_valid": joint_valid,
        "meta": _dropna_stats(df, df[joint_valid]),
        "counts": counts,
        "blockers": blockers,
        "ready": not blockers,
    }


def _typed_class_counts(series: pd.Series) -> list[dict]:
    """Distinct target classes as typed, JSON-safe entries with row counts.

    Uses the same type-preserving key as the KM status mapping, so numeric 1
    never collapses into string "1". Ordered deterministically.
    """
    counts_by_key: dict[tuple, int] = {}
    for cell in series:
        if pd.isna(cell):
            continue
        key = _cell_status_key(cell)
        if key is None:
            key = ("__unsupported__",)
        counts_by_key[key] = counts_by_key.get(key, 0) + 1

    entries = []
    for key, count in counts_by_key.items():
        if key == ("__unsupported__",):
            entries.append({"value": None, "value_type": "unsupported", "count": count})
        else:
            entries.append({"value": key[1], "value_type": key[0], "count": count})
    entries.sort(key=lambda e: (e["value_type"], str(e["value"])))
    return entries


def _suggest_positive_class(classes: list[dict]) -> dict | None:
    """Suggest numeric 1 for standard 0/1 data — a hint only.

    Never auto-applied: the doctor confirms which outcome is being modelled
    before the analysis runs. Returns None for any non-standard coding, so
    the UI cannot quietly default to an arbitrary class.
    """
    keys = {(c["value_type"], c["value"]) for c in classes}
    if keys == {("number", 0.0), ("number", 1.0)}:
        return {"value": 1.0, "value_type": "number"}
    return None


def prepare_logistic(df: pd.DataFrame, params: dict) -> dict:
    """Joint-row preparation for logistic regression.

    Features are numeric roles; the target is categorical and keeps its
    original labels. Reports the usable classes so the caller can ask the
    doctor which outcome to model rather than choosing one silently.
    """
    target_col = params["target_column"]
    feature_cols = params["feature_columns"]
    if len(feature_cols) > _MAX_FEATURE_COLS:
        raise AnalysisValidationError(
            f"Too many feature columns ({len(feature_cols)}); maximum is {_MAX_FEATURE_COLS}."
        )

    _check_columns(df, [target_col], feature_cols)

    processing: dict[str, dict] = {}
    joint_valid = pd.Series(True, index=df.index)

    target_valid, processing[target_col] = _categorical_processing_report(df[target_col], "target")
    joint_valid &= target_valid

    any_missing = df[target_col].isna()
    any_non_numeric = pd.Series(False, index=df.index)

    coerced: dict[str, dict] = {}
    for col in feature_cols:
        c = _coerce_numeric(df[col])
        coerced[col] = c
        processing[col] = _numeric_processing_report("feature", c)
        joint_valid &= c["is_valid"]

        is_missing = df[col].isna()
        any_missing |= is_missing
        any_non_numeric |= (~c["is_valid"] & ~is_missing)

    counts = _joint_numeric_counts(df, joint_valid, any_missing, any_non_numeric)
    classes = _typed_class_counts(df[target_col][joint_valid])

    blockers: list[str] = []
    if counts["used_rows"] == 0:
        blockers.append("no_usable_rows")
    elif len(classes) != 2:
        blockers.append("target_not_binary")

    return {
        "target_col": target_col,
        "feature_cols": feature_cols,
        "coerced": coerced,
        "processing": processing,
        "joint_valid": joint_valid,
        "meta": _dropna_stats(df, df[joint_valid]),
        "counts": counts,
        "classes": classes,
        "suggested_positive_class": _suggest_positive_class(classes),
        "blockers": blockers,
        "ready": not blockers,
    }
