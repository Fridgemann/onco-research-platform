"""
Milestone 4, Slice 1 — shared preparation/profiling service.

Two things are proved here:

1. The prep/profiling helpers live in a neutral service that both the Celery
   worker and the API routes import, and the task module's names are the SAME
   objects — so there is exactly one implementation, not a copy that can drift.

2. The newly extracted prepare_* helpers report the same row accounting the
   corresponding _run_* function actually uses. This is the property the
   non-KM preflight endpoints will depend on (Slice 3): preflight counts equal
   final counts by construction, the guarantee M3 established for KM.

The prepare_* helpers are deliberately NON-raising for data states (they
report `blockers` / `empty_columns`), mirroring the M3 split between
_km_classify_and_count (reports) and _km_prepare (rejects). Request-shape
errors (unknown column, too many features) still raise.
"""
import numpy as np
import pandas as pd
import pytest

from app.services import analysis_prep
from app.tasks import analysis as task_analysis
from app.services.analysis_prep import (
    AnalysisValidationError,
    prepare_descriptive,
    prepare_logistic,
    prepare_regression,
)


# ── 1. One implementation, shared ───────────────────────────────────────────

SHARED_NAMES = [
    "AnalysisValidationError",
    "_check_columns",
    "_dropna_stats",
    "_coerce_numeric",
    "_numeric_processing_report",
    "_categorical_processing_report",
    "_binary_code_counts",
    "_cell_status_key",
    "_assert_json_safe",
    "_km_prepare",
    "_km_preflight",
    "_km_classify_and_count",
]


@pytest.mark.parametrize("name", SHARED_NAMES)
def test_service_exposes_shared_helper(name):
    assert hasattr(analysis_prep, name), f"{name} should live in the shared service"


@pytest.mark.parametrize("name", SHARED_NAMES)
def test_task_module_reexports_the_same_object(name):
    # Identity, not equality: a copied implementation would pass an equality
    # check but could drift from what the worker actually runs.
    assert getattr(task_analysis, name) is getattr(analysis_prep, name)


# ── 2. prepare_* row accounting matches the run functions ───────────────────

def test_prepare_descriptive_counts_are_per_column():
    # Descriptive computes each column on its own usable rows — a single joint
    # used/excluded pair would misrepresent it.
    df = pd.DataFrame({
        "Age": [58, 71, 48, 34],
        "Value": ["100", "C", None, "400"],
    })
    prep = prepare_descriptive(df, {"columns": ["Age", "Value"]})

    assert prep["counts_by_column"]["Age"] == {
        "used_rows": 4, "excluded_rows": 0, "missing_rows": 0, "non_numeric_rows": 0,
    }
    assert prep["counts_by_column"]["Value"] == {
        "used_rows": 2, "excluded_rows": 2, "missing_rows": 1, "non_numeric_rows": 1,
    }
    assert prep["empty_columns"] == []


def test_prepare_descriptive_reports_empty_column_without_raising():
    df = pd.DataFrame({"Value": ["C", "ND", None]})
    prep = prepare_descriptive(df, {"columns": ["Value"]})
    assert prep["empty_columns"] == ["Value"]
    assert prep["counts_by_column"]["Value"]["used_rows"] == 0


def test_prepare_descriptive_matches_run_output():
    df = pd.DataFrame({
        "Age": [58, 71, 48, 34],
        "Value": ["100", "C", None, "400"],
    })
    params = {"columns": ["Age", "Value"]}
    prep = prepare_descriptive(df, params)
    run = task_analysis._run_descriptive_stats(df, params)

    for col in ("Age", "Value"):
        assert run[col]["count"] == prep["counts_by_column"][col]["used_rows"]
        assert run[col]["missing"] == prep["counts_by_column"][col]["missing_rows"]
        assert run[col]["non_numeric"] == prep["counts_by_column"][col]["non_numeric_rows"]
    assert run["_meta"] == prep["meta"]


def test_prepare_regression_counts_match_run():
    df = pd.DataFrame({
        "x": ["1", "2", "3", None, "5", "6"],   # missing at idx 3
        "y": ["10", "20", "C", "40", "50", "60"],  # non-numeric at idx 2
    })
    params = {"target_column": "y", "feature_columns": ["x"]}
    prep = prepare_regression(df, params)
    run = task_analysis._run_regression(df, params)

    assert prep["counts"]["total_rows"] == 6
    assert prep["counts"]["used_rows"] == 4
    assert prep["counts"]["excluded_rows"] == 2
    # per-reason counts are row-level and may overlap; excluded counts once
    assert prep["counts"]["exclusions"]["missing"] == 1
    assert prep["counts"]["exclusions"]["non_numeric"] == 1
    assert run["n"] == prep["counts"]["used_rows"]
    assert run["_meta"] == prep["meta"]
    assert prep["blockers"] == []


def test_prepare_regression_reports_no_usable_rows_without_raising():
    df = pd.DataFrame({"x": ["C", "ND", None], "y": ["1", "2", "3"]})
    prep = prepare_regression(df, {"target_column": "y", "feature_columns": ["x"]})
    assert "no_usable_rows" in prep["blockers"]
    assert prep["counts"]["used_rows"] == 0
    # the run function still rejects it
    with pytest.raises(AnalysisValidationError):
        task_analysis._run_regression(df, {"target_column": "y", "feature_columns": ["x"]})


def test_prepare_logistic_counts_and_classes_match_run():
    df = pd.DataFrame({
        "x": ["1", None, "3", "4", "5", "6"],   # missing at idx 1
        "y": ["a", "a", "b", "a", "b", None],   # missing at idx 5
    })
    params = {"target_column": "y", "feature_columns": ["x"]}
    prep = prepare_logistic(df, params)
    run = task_analysis._run_logistic_regression(df, params)

    assert prep["counts"]["used_rows"] == 4
    assert prep["counts"]["excluded_rows"] == 2
    assert run["n"] == prep["counts"]["used_rows"]
    assert run["_meta"] == prep["meta"]

    # exactly the two usable classes, typed, with counts
    classes = {(c["value"], c["value_type"]): c["count"] for c in prep["classes"]}
    assert classes == {("a", "string"): 2, ("b", "string"): 2}
    assert prep["blockers"] == []


def test_prepare_logistic_flags_non_binary_target_without_raising():
    df = pd.DataFrame({"x": ["1", "2", "3", "4"], "y": ["a", "b", "c", "a"]})
    prep = prepare_logistic(df, {"target_column": "y", "feature_columns": ["x"]})
    assert "target_not_binary" in prep["blockers"]
    assert len(prep["classes"]) == 3
    # the run function still rejects it
    with pytest.raises(AnalysisValidationError, match="exactly two outcome classes"):
        task_analysis._run_logistic_regression(df, {"target_column": "y", "feature_columns": ["x"]})


def test_prepare_logistic_suggests_numeric_one_but_does_not_confirm():
    df = pd.DataFrame({"x": [1, 2, 3, 4], "y": [0, 1, 0, 1]})
    prep = prepare_logistic(df, {"target_column": "y", "feature_columns": ["x"]})
    # a hint only — nothing is auto-applied
    assert prep["suggested_positive_class"] == {"value": 1.0, "value_type": "number"}
    assert "positive_class" not in prep


def test_prepare_logistic_no_suggestion_for_non_standard_classes():
    df = pd.DataFrame({"x": [1, 2, 3, 4], "y": ["alive", "dead", "alive", "dead"]})
    prep = prepare_logistic(df, {"target_column": "y", "feature_columns": ["x"]})
    assert prep["suggested_positive_class"] is None


# ── 3. Request-shape errors still raise ─────────────────────────────────────

def test_unknown_column_still_raises():
    df = pd.DataFrame({"x": [1, 2], "y": [1, 2]})
    with pytest.raises(AnalysisValidationError, match="not found"):
        prepare_regression(df, {"target_column": "nope", "feature_columns": ["x"]})


def test_too_many_features_still_raises():
    df = pd.DataFrame({"y": [1, 2], **{f"f{i}": [1, 2] for i in range(60)}})
    with pytest.raises(AnalysisValidationError, match="Too many feature columns"):
        prepare_regression(df, {"target_column": "y", "feature_columns": [f"f{i}" for i in range(60)]})
