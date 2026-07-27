import io
import json
import logging
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

from lifelines import KaplanMeierFitter

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


def _run_kaplan_meier(df: pd.DataFrame, params: dict) -> dict:
    time_col = params["time_column"]
    event_col = params["event_column"]
    group_col = params.get("group_column")

    selected = [time_col, event_col] + ([group_col] if group_col else [])
    _check_columns(df, selected)

    event_value = params.get("event_value")  # e.g. 2 for R convention (1=censored, 2=dead)
    df_clean = df[selected].dropna()
    meta = _dropna_stats(df, df_clean)

    unique_times = df_clean[time_col].nunique()
    if unique_times > _KM_MAX_UNIQUE_TIMES:
        raise AnalysisValidationError(
            f"Time column has {unique_times} unique values (max {_KM_MAX_UNIQUE_TIMES}). "
            "Round timestamps to whole days or months to reduce resolution."
        )

    event_observed = (df_clean[event_col] == event_value) if event_value is not None else df_clean[event_col]

    if not group_col:
        kmf = KaplanMeierFitter()
        kmf.fit(durations=df_clean[time_col], event_observed=event_observed)
        return {
            "overall": {
                "timeline": kmf.survival_function_.index.tolist(),
                "survival_probability": kmf.survival_function_["KM_estimate"].tolist(),
                "median_survival": float(kmf.median_survival_time_)
            },
            "_meta": meta,
        }

    requested_max = int(params.get("max_groups", _KM_ABSOLUTE_MAX_GROUPS))
    effective_max = min(requested_max, _KM_ABSOLUTE_MAX_GROUPS)

    unique_groups = df_clean[group_col].unique()
    if len(unique_groups) > effective_max:
        raise AnalysisValidationError(
            f"Group column has {len(unique_groups)} unique values, "
            f"exceeds your limit of {requested_max} "
            f"(server maximum: {_KM_ABSOLUTE_MAX_GROUPS}). "
            "Use a categorical column with fewer distinct values."
        )

    result: dict = {"_meta": meta}
    for group in unique_groups:
        subset = df_clean[df_clean[group_col] == group]
        sub_events = (subset[event_col] == event_value) if event_value is not None else subset[event_col]
        kmf = KaplanMeierFitter()
        kmf.fit(durations=subset[time_col], event_observed=sub_events)
        result[str(group)] = {
            "timeline": kmf.survival_function_.index.tolist(),
            "survival_probability": kmf.survival_function_["KM_estimate"].tolist(),
            "median_survival": float(kmf.median_survival_time_)
        }
    return result




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

            _set_job(session, job_id,
                     status=JobStatus.COMPLETED,
                     result=json.dumps(result),
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
