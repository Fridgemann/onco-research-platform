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

# Preparation and profiling live in a neutral service so the worker and the
# API routes share one implementation (Milestone 4, Slice 1). Re-exported here
# because this module is the historical import site for these names.
from app.services.analysis_prep import (  # noqa: F401
    AnalysisValidationError,
    _assert_json_safe,
    _binary_code_counts,
    _build_event_mapping,
    _categorical_processing_report,
    _cell_status_key,
    _check_columns,
    _classify_km_status,
    _CODE_STRING_MAX_LEN,
    _coerce_numeric,
    _dropna_stats,
    _km_classify_and_count,
    _km_prepare,
    _km_preflight,
    _KM_ABSOLUTE_MAX_GROUPS,
    _KM_AUTO_MAP,
    _KM_BLOCKER_MESSAGES,
    _KM_MAX_UNIQUE_TIMES,
    _MAX_FEATURE_COLS,
    _normalize_mapping_key,
    _numeric_processing_report,
    _status_value_payload,
    preflight_analysis,
    prepare_descriptive,
    prepare_logistic,
    prepare_regression,
    profile_dataset,
    resolve_class_labels,
    resolve_positive_class,
)

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


def _run_descriptive_stats(df: pd.DataFrame, params: dict) -> dict:
    # Preparation is shared with the preflight endpoint so reported counts and
    # executed counts cannot diverge.
    prep = prepare_descriptive(df, params)
    if prep["empty_columns"]:
        raise AnalysisValidationError(
            f"Column '{prep['empty_columns'][0]}' has no usable numeric values."
        )

    result: dict = {}

    for col in prep["columns"]:
        coerced = prep["per_column"][col]["coerced"]
        values = prep["per_column"][col]["values"]

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

    result["_meta"] = prep["meta"]
    return result


def _run_regression(df: pd.DataFrame, params: dict) -> dict:
    from scipy.stats import linregress

    # Preparation is shared with the preflight endpoint so reported counts and
    # executed counts cannot diverge.
    prep = prepare_regression(df, params)
    target_col = prep["target_col"]
    feature_cols = prep["feature_cols"]
    coerced = prep["coerced"]
    processing = prep["processing"]
    joint_valid = prep["joint_valid"]
    meta = prep["meta"]

    if "no_usable_rows" in prep["blockers"]:
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


def _median_or_none(kmf: "KaplanMeierFitter") -> float | None:
    """Median survival, or None when the curve never reaches 0.5 ("not reached")."""
    m = kmf.median_survival_time_
    return float(m) if np.isfinite(m) else None


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

    # Preparation is shared with the preflight endpoint so reported counts and
    # executed counts cannot diverge.
    prep = prepare_logistic(df, params)
    target_col = prep["target_col"]
    feature_cols = prep["feature_cols"]
    coerced = prep["coerced"]
    processing = prep["processing"]
    joint_valid = prep["joint_valid"]
    meta = prep["meta"]

    if "no_usable_rows" in prep["blockers"]:
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
    n_classes = len(prep["classes"])
    if n_classes != 2:
        raise AnalysisValidationError(
            f"Logistic regression requires exactly two outcome classes after "
            f"excluding unusable rows; found {n_classes}."
        )

    # Which outcome the model predicts is the researcher's decision. When one
    # is confirmed, the target is mapped to 0/1 with 1 = that outcome BEFORE
    # fitting, so probabilities, coefficient directions and AUC all describe
    # it — rather than sign-flipping afterwards and risking disagreement
    # between the figures. Revalidated here, so a direct API submit that
    # skipped preflight cannot select an outcome the data does not contain.
    confirmed = resolve_positive_class(params, prep["classes"])

    if confirmed is not None:
        fit_y = np.array([1 if _cell_status_key(v) == confirmed else 0 for v in y])
        positive_class = {"value": confirmed[1], "value_type": confirmed[0]}
    else:
        # No selection: keep sklearn's own ordering, exactly as before, and
        # record that nothing was confirmed.
        fit_y = y
        positive_class = None

    model = LogisticRegression(max_iter=1000)
    model.fit(X, fit_y)

    y_pred = model.predict(X)
    accuracy = float(accuracy_score(fit_y, y_pred))

    auc = None
    try:
        if len(model.classes_) == 2:
            auc = float(roc_auc_score(fit_y, model.predict_proba(X)[:, 1]))
    except Exception:
        pass

    if positive_class is None and len(model.classes_) == 2:
        # Disclose the class sklearn treated as positive, so the direction of
        # every figure is stated even when nothing was explicitly chosen.
        fallback = _cell_status_key(model.classes_[1])
        if fallback is not None:
            positive_class = {"value": fallback[1], "value_type": fallback[0]}

    return {
        "type": "logistic",
        "target": target_col,
        "features": feature_cols,
        "intercept": float(model.intercept_[0]),
        "coefficients": {f: float(c) for f, c in zip(feature_cols, model.coef_[0])},
        "accuracy": accuracy,
        "auc": auc,
        "n": len(y),
        # The original outcome labels, independent of how the fit was oriented.
        # For a confirmed run these come from the already-typed prep classes:
        # the model was fitted on a 0/1 mapping so its own classes_ would say
        # 0/1, and np.unique would raise TypeError on deliberately distinct
        # mixed types (numeric 1 vs string "1"). The unconfirmed compatibility
        # path keeps model.classes_ exactly as before.
        "classes": (
            [c["value"] for c in prep["classes"]]
            if confirmed is not None
            else model.classes_.tolist()
        ),
        "target_classes": prep["classes"],
        "positive_class": positive_class,
        "positive_class_confirmed": confirmed is not None,
        "class_labels": resolve_class_labels(params, prep["classes"]),
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
