import io
import json
import logging
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sqlalchemy import create_engine
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
_sync_engine = create_engine(_sync_url)
SyncSession = sessionmaker(bind=_sync_engine)


def _set_job(session, job: AnalysisJob, **kwargs) -> None:
    for k, v in kwargs.items():
        setattr(job, k, v)
    session.commit()


def _run_descriptive_stats(df: pd.DataFrame, params: dict) -> dict:
    columns = params.get("columns") or df.select_dtypes(include=[np.number]).columns.tolist()
    result = {}
    for col in columns:
        if col not in df.columns:
            continue
        series = df[col].dropna()
        result[col] = {
            "count": int(series.count()),
            "mean": float(series.mean()),
            "std": float(series.std()),
            "min": float(series.min()),
            "p25": float(series.quantile(0.25)),
            "median": float(series.median()),
            "p75": float(series.quantile(0.75)),
            "max": float(series.max()),
            "missing": int(df[col].isna().sum()),
        }
    return result


_MAX_FEATURE_COLS = 50


def _run_regression(df: pd.DataFrame, params: dict) -> dict:
    from scipy.stats import linregress

    target_col = params["target_column"]
    feature_cols = params["feature_columns"]
    if len(feature_cols) > _MAX_FEATURE_COLS:
        raise ValueError(f"Too many feature columns ({len(feature_cols)}); maximum is {_MAX_FEATURE_COLS}.")

    df_clean = df[[target_col] + feature_cols].dropna()
    y = df_clean[target_col].values

    if len(feature_cols) == 1:
        slope, intercept, r_value, p_value, std_err = linregress(
            df_clean[feature_cols[0]].values, y
        )
        return {
            "type": "linear",
            "feature": feature_cols[0],
            "slope": float(slope),
            "intercept": float(intercept),
            "r_squared": float(r_value**2),
            "p_value": float(p_value),
            "std_err": float(std_err),
            "n": len(y),
        }

    X = np.column_stack([np.ones(len(df_clean)), df_clean[feature_cols].values])
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
    }


_KM_ABSOLUTE_MAX_GROUPS = int(os.getenv("KM_ABSOLUTE_MAX_GROUPS", "100"))
_KM_MAX_UNIQUE_TIMES = int(os.getenv("KM_MAX_UNIQUE_TIMES", "2000"))


def _run_kaplan_meier(df: pd.DataFrame, params: dict) -> dict:
    time_col = params["time_column"]
    event_col = params["event_column"]
    group_col = params.get("group_column")

    event_value = params.get("event_value")  # e.g. 2 for R convention (1=censored, 2=dead)
    df_clean = df[[time_col, event_col, group_col] if group_col else [time_col, event_col]].dropna()

    unique_times = df_clean[time_col].nunique()
    if unique_times > _KM_MAX_UNIQUE_TIMES:
        raise ValueError(
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
            }
        }

    requested_max = int(params.get("max_groups", _KM_ABSOLUTE_MAX_GROUPS))
    effective_max = min(requested_max, _KM_ABSOLUTE_MAX_GROUPS)

    unique_groups = df_clean[group_col].unique()
    if len(unique_groups) > effective_max:
        raise ValueError(
            f"Group column has {len(unique_groups)} unique values, "
            f"exceeds your limit of {requested_max} "
            f"(server maximum: {_KM_ABSOLUTE_MAX_GROUPS}). "
            "Use a categorical column with fewer distinct values."
        )

    result = {}
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
        raise ValueError(f"Too many feature columns ({len(feature_cols)}); maximum is {_MAX_FEATURE_COLS}.")
    df_clean = df[[target_col] + feature_cols].dropna()

    y = df_clean[target_col].values
    X = df_clean[feature_cols].values

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
    }


@celery_app.task(bind=True, name="run_analysis")
def run_analysis_task(self, job_id: str):
    with SyncSession() as session:
        job = session.get(AnalysisJob, job_id)
        if not job:
            logger.error("Job %s not found", job_id)
            return

        _set_job(session, job,
                 status=JobStatus.RUNNING,
                 started_at=datetime.now(timezone.utc))

        try:
            dataset = session.get(Dataset, job.dataset_id)
            raw = _sync_download(dataset.object_key)
            df = pd.read_csv(io.StringIO(decrypt_bytes(raw).decode("utf-8")))
            params = json.loads(job.parameters or "{}")

            dispatch = {
                "kaplan_meier": _run_kaplan_meier,
                "regression": _run_regression,
                "descriptive_stats": _run_descriptive_stats,
                "logistic_regression": _run_logistic_regression,
            }
            result = dispatch[job.job_type](df, params)

            _set_job(session, job,
                     status=JobStatus.COMPLETED,
                     result=json.dumps(result),
                     completed_at=datetime.now(timezone.utc))

        except ValueError as exc:
            # ValueError comes from our own validation guards — safe to surface
            logger.warning("Job %s validation error: %s", job_id, exc)
            _set_job(session, job,
                     status=JobStatus.FAILED,
                     error_message=str(exc)[:512],
                     completed_at=datetime.now(timezone.utc))
        except Exception as exc:
            logger.exception("Job %s failed: %s", job_id, exc)
            _set_job(session, job,
                     status=JobStatus.FAILED,
                     error_message="Analysis failed. Check that column names exist and contain numeric data.",
                     completed_at=datetime.now(timezone.utc))
            raise
