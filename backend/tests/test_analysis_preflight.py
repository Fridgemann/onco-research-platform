"""
Milestone 4, Slice 3 — real preflight for the non-KM analyses.

The property that matters: preflight and the executed run share the same
`prepare_*` helpers, so reported counts equal final counts by construction —
the guarantee M3 established for Kaplan-Meier, extended to the rest.

Descriptive is reported PER COLUMN because that is how it is computed; a
single joint used/excluded pair would misrepresent it. Linear and logistic
keep joint-row counts because every selected column must be usable on the
same row.

Logistic additionally reports its two usable outcome classes so the
researcher can choose which one the model predicts. That choice is never
made silently: numeric 1 is only ever *suggested*, and preflight stays
not-ready until an explicit selection arrives.

All fixtures are synthetic.
"""
import numpy as np
import pandas as pd
import pytest

from app.services.analysis_prep import AnalysisValidationError, preflight_analysis
from app.tasks import analysis as task_analysis


# ── Descriptive: per-column, never joint ────────────────────────────────────

def test_descriptive_preflight_reports_per_column_counts():
    df = pd.DataFrame({
        "Age": [58, 71, 48, 34],
        "Value": ["100", "C", None, "400"],
    })
    pf = preflight_analysis(df, "descriptive_stats", {"columns": ["Age", "Value"]})

    assert pf["ready"] is True
    assert "counts" not in pf                      # joint counts would mislead here
    assert pf["counts_by_column"]["Age"]["used_rows"] == 4
    assert pf["counts_by_column"]["Value"] == {
        "used_rows": 2, "excluded_rows": 2, "missing_rows": 1, "non_numeric_rows": 1,
    }


def test_descriptive_preflight_not_ready_when_a_column_has_no_usable_values():
    df = pd.DataFrame({"Age": [1, 2], "Dead": ["C", "ND"]})
    pf = preflight_analysis(df, "descriptive_stats", {"columns": ["Age", "Dead"]})
    assert pf["ready"] is False
    assert "column_has_no_usable_values" in pf["blockers"]
    assert pf["counts_by_column"]["Dead"]["used_rows"] == 0


def test_descriptive_preflight_counts_match_the_run():
    df = pd.DataFrame({"Age": [58, 71, 48, 34], "Value": ["100", "C", None, "400"]})
    params = {"columns": ["Age", "Value"]}
    pf = preflight_analysis(df, "descriptive_stats", params)
    run = task_analysis._run_descriptive_stats(df, params)

    for col in ("Age", "Value"):
        assert run[col]["count"] == pf["counts_by_column"][col]["used_rows"]
        assert run[col]["missing"] == pf["counts_by_column"][col]["missing_rows"]
        assert run[col]["non_numeric"] == pf["counts_by_column"][col]["non_numeric_rows"]


# ── Linear: joint rows ──────────────────────────────────────────────────────

def test_regression_preflight_counts_match_the_run():
    df = pd.DataFrame({
        "x": ["1", "2", "3", None, "5", "6"],
        "y": ["10", "20", "C", "40", "50", "60"],
    })
    params = {"target_column": "y", "feature_columns": ["x"]}
    pf = preflight_analysis(df, "regression", params)
    run = task_analysis._run_regression(df, params)

    assert pf["ready"] is True
    assert pf["counts"]["used_rows"] == run["n"] == 4
    assert pf["counts"]["excluded_rows"] == 2
    assert "counts_by_column" not in pf
    # per-column processing detail is still available for the UI
    roles = {c["name"]: c["role"] for c in pf["columns"]}
    assert roles == {"y": "target", "x": "feature"}


def test_regression_preflight_blocks_when_no_usable_rows():
    df = pd.DataFrame({"x": ["C", "ND", None], "y": ["1", "2", "3"]})
    pf = preflight_analysis(df, "regression", {"target_column": "y", "feature_columns": ["x"]})
    assert pf["ready"] is False
    assert "no_usable_rows" in pf["blockers"]


# ── Logistic: classes, and an outcome that is chosen rather than assumed ────

LOGISTIC_DF = pd.DataFrame({
    "x": [1, 2, 3, 4, 5, 6, 7, 8],
    "y": [0, 0, 0, 0, 1, 1, 1, 1],
})
LOGISTIC_PARAMS = {"target_column": "y", "feature_columns": ["x"]}


def test_logistic_preflight_reports_both_usable_classes_with_counts():
    pf = preflight_analysis(LOGISTIC_DF, "logistic_regression", LOGISTIC_PARAMS)
    classes = {(c["value"], c["value_type"]): c["count"] for c in pf["target_classes"]}
    assert classes == {(0.0, "number"): 4, (1.0, "number"): 4}


def test_logistic_preflight_suggests_but_does_not_confirm_the_outcome():
    pf = preflight_analysis(LOGISTIC_DF, "logistic_regression", LOGISTIC_PARAMS)
    assert pf["suggested_positive_class"] == {"value": 1.0, "value_type": "number"}
    # a suggestion is not a decision — preflight stays not-ready
    assert pf["ready"] is False
    assert "positive_class_unconfirmed" in pf["blockers"]


def test_logistic_preflight_ready_once_the_outcome_is_confirmed():
    params = {**LOGISTIC_PARAMS, "positive_class": {"value": 1, "value_type": "number"}}
    pf = preflight_analysis(LOGISTIC_DF, "logistic_regression", params)
    assert pf["ready"] is True
    assert pf["blockers"] == []


def test_logistic_preflight_rejects_an_outcome_outside_the_usable_classes():
    params = {**LOGISTIC_PARAMS, "positive_class": {"value": 7, "value_type": "number"}}
    with pytest.raises(AnalysisValidationError, match="not one of"):
        preflight_analysis(LOGISTIC_DF, "logistic_regression", params)


def test_logistic_preflight_no_suggestion_for_non_standard_labels():
    df = pd.DataFrame({"x": [1, 2, 3, 4], "y": ["alive", "dead", "alive", "dead"]})
    pf = preflight_analysis(df, "logistic_regression", {"target_column": "y", "feature_columns": ["x"]})
    assert pf["suggested_positive_class"] is None
    assert "positive_class_unconfirmed" in pf["blockers"]


def test_logistic_preflight_blocks_non_binary_target():
    df = pd.DataFrame({"x": [1, 2, 3, 4], "y": ["a", "b", "c", "a"]})
    pf = preflight_analysis(df, "logistic_regression", {"target_column": "y", "feature_columns": ["x"]})
    assert pf["ready"] is False
    assert "target_not_binary" in pf["blockers"]


def test_logistic_preflight_counts_match_the_run():
    params = {**LOGISTIC_PARAMS, "positive_class": {"value": 1, "value_type": "number"}}
    pf = preflight_analysis(LOGISTIC_DF, "logistic_regression", params)
    run = task_analysis._run_logistic_regression(LOGISTIC_DF, params)
    assert pf["counts"]["used_rows"] == run["n"]


# ── Confirmed outcome actually orients the model ────────────────────────────

def test_confirmed_outcome_orients_coefficients():
    """Flipping which outcome is modelled flips the coefficient direction.

    x rises with class 1, so predicting 1 gives a positive coefficient and
    predicting 0 gives a negative one. If the selection were ignored the two
    would be identical.
    """
    predict_one = task_analysis._run_logistic_regression(
        LOGISTIC_DF, {**LOGISTIC_PARAMS, "positive_class": {"value": 1, "value_type": "number"}}
    )
    predict_zero = task_analysis._run_logistic_regression(
        LOGISTIC_DF, {**LOGISTIC_PARAMS, "positive_class": {"value": 0, "value_type": "number"}}
    )

    assert predict_one["coefficients"]["x"] > 0
    assert predict_zero["coefficients"]["x"] < 0
    assert predict_one["positive_class"] == {"value": 1.0, "value_type": "number"}
    assert predict_zero["positive_class"] == {"value": 0.0, "value_type": "number"}
    assert predict_one["positive_class_confirmed"] is True


def test_run_rejects_an_outcome_outside_the_usable_classes():
    # Backend authority: a direct API call cannot smuggle in a bogus outcome.
    params = {**LOGISTIC_PARAMS, "positive_class": {"value": 99, "value_type": "number"}}
    with pytest.raises(AnalysisValidationError, match="not one of"):
        task_analysis._run_logistic_regression(LOGISTIC_DF, params)


def test_unconfirmed_outcome_falls_back_and_is_marked_unconfirmed():
    # Optional at the task layer so the M1 validated statistics stay unchanged
    # for legacy/direct calls. The HTTP submission route requires a selection;
    # this fallback is not a supported path for new work.
    run = task_analysis._run_logistic_regression(LOGISTIC_DF, LOGISTIC_PARAMS)
    assert run["positive_class_confirmed"] is False
    assert run["positive_class"] is not None


def test_mixed_typed_classes_do_not_crash_a_confirmed_run():
    # numeric 1 and string "1" are deliberately distinct classes. np.unique
    # sorts the original labels and raises TypeError on mixed types, so the
    # legacy `classes` list must come from the already-typed prep classes.
    df = pd.DataFrame({"x": [1, 2, 3, 4, 5, 6], "y": [1, 1, 1, "1", "1", "1"]})
    run = task_analysis._run_logistic_regression(
        df,
        {"target_column": "y", "feature_columns": ["x"],
         "positive_class": {"value": "1", "value_type": "string"}},
    )
    assert run["positive_class"] == {"value": "1", "value_type": "string"}
    assert len(run["classes"]) == 2
    typed = {(c["value_type"], c["value"]) for c in run["target_classes"]}
    assert typed == {("number", 1.0), ("string", "1")}


def test_class_labels_must_reference_usable_classes():
    params = {
        **LOGISTIC_PARAMS,
        "positive_class": {"value": 1, "value_type": "number"},
        "class_labels": [{"value": 7, "value_type": "number", "label": "nope"}],
    }
    with pytest.raises(AnalysisValidationError, match="label"):
        task_analysis._run_logistic_regression(LOGISTIC_DF, params)


def test_valid_class_labels_are_echoed():
    params = {
        **LOGISTIC_PARAMS,
        "positive_class": {"value": 1, "value_type": "number"},
        "class_labels": [
            {"value": 0, "value_type": "number", "label": "no recurrence"},
            {"value": 1, "value_type": "number", "label": "recurrence"},
        ],
    }
    run = task_analysis._run_logistic_regression(LOGISTIC_DF, params)
    labels = {c["label"] for c in run["class_labels"]}
    assert labels == {"no recurrence", "recurrence"}


def test_string_labels_can_be_chosen_as_the_outcome():
    df = pd.DataFrame({"x": [1, 2, 3, 4, 5, 6], "y": ["alive", "alive", "alive", "dead", "dead", "dead"]})
    params = {"target_column": "y", "feature_columns": ["x"],
              "positive_class": {"value": "dead", "value_type": "string"}}
    run = task_analysis._run_logistic_regression(df, params)
    assert run["positive_class"] == {"value": "dead", "value_type": "string"}
    assert run["coefficients"]["x"] > 0     # x rises with "dead"


# ── Dispatch ────────────────────────────────────────────────────────────────

def test_kaplan_meier_is_directed_to_its_own_endpoint():
    df = pd.DataFrame({"dur": [1, 2], "evt": [1, 0]})
    with pytest.raises(AnalysisValidationError, match="Kaplan"):
        preflight_analysis(df, "kaplan_meier", {"time_column": "dur", "event_column": "evt"})


def test_unknown_job_type_rejected():
    df = pd.DataFrame({"a": [1, 2]})
    with pytest.raises(AnalysisValidationError):
        preflight_analysis(df, "not_a_real_analysis", {})


# ── class_labels: preflight and run must agree ──────────────────────────────

_CONFIRMED = {"value": 1, "value_type": "number"}

BAD_LABEL_PARAMS = {
    **LOGISTIC_PARAMS,
    "positive_class": _CONFIRMED,
    "class_labels": [{"value": 7, "value_type": "number", "label": "nope"}],
}


def test_preflight_and_run_agree_on_invalid_labels():
    # Regression: preflight used to report ready=true and the run then raised,
    # which is exactly the disagreement this endpoint exists to prevent. Both
    # must reject, and with the same message, since they share one helper.
    preflight_error = run_error = None
    try:
        preflight_analysis(LOGISTIC_DF, "logistic_regression", BAD_LABEL_PARAMS)
    except AnalysisValidationError as exc:
        preflight_error = str(exc)
    try:
        task_analysis._run_logistic_regression(LOGISTIC_DF, BAD_LABEL_PARAMS)
    except AnalysisValidationError as exc:
        run_error = str(exc)

    assert preflight_error is not None
    assert preflight_error == run_error


def test_preflight_and_run_agree_on_valid_labels():
    params = {
        **LOGISTIC_PARAMS,
        "positive_class": _CONFIRMED,
        "class_labels": [
            {"value": 0, "value_type": "number", "label": "no recurrence"},
            {"value": 1, "value_type": "number", "label": "recurrence"},
        ],
    }
    pf = preflight_analysis(LOGISTIC_DF, "logistic_regression", params)
    run = task_analysis._run_logistic_regression(LOGISTIC_DF, params)

    assert pf["ready"] is True
    assert {c["label"] for c in run["class_labels"]} == {"no recurrence", "recurrence"}


@pytest.mark.parametrize("invalid_value", [{}, "", 0, "labels", 5])
def test_non_list_class_labels_are_rejected_not_ignored(invalid_value):
    # `or []` used to treat {}, "" and 0 as "nothing supplied"; the truthy
    # non-list shapes must be rejected for the same reason.
    params = {**LOGISTIC_PARAMS, "positive_class": _CONFIRMED, "class_labels": invalid_value}
    with pytest.raises(AnalysisValidationError, match="list of typed entries"):
        task_analysis._run_logistic_regression(LOGISTIC_DF, params)
    with pytest.raises(AnalysisValidationError, match="list of typed entries"):
        preflight_analysis(LOGISTIC_DF, "logistic_regression", params)


@pytest.mark.parametrize("labels,expected", [
    # duplicate entry for the same outcome
    ([{"value": 1, "value_type": "number", "label": "a"},
      {"value": 1, "value_type": "number", "label": "b"}], "Duplicate"),
    # blank / whitespace-only text
    ([{"value": 1, "value_type": "number", "label": "   "}], "non-empty"),
    ([{"value": 1, "value_type": "number", "label": ""}], "non-empty"),
    # over the length cap
    ([{"value": 1, "value_type": "number", "label": "x" * 65}], "maximum length"),
])
def test_label_rules_are_enforced_by_both_paths(labels, expected):
    params = {**LOGISTIC_PARAMS, "positive_class": _CONFIRMED, "class_labels": labels}
    with pytest.raises(AnalysisValidationError, match=expected):
        task_analysis._run_logistic_regression(LOGISTIC_DF, params)
    with pytest.raises(AnalysisValidationError, match=expected):
        preflight_analysis(LOGISTIC_DF, "logistic_regression", params)


def test_absent_or_null_class_labels_mean_no_labels():
    for extra in ({}, {"class_labels": None}):
        params = {**LOGISTIC_PARAMS, "positive_class": _CONFIRMED, **extra}
        run = task_analysis._run_logistic_regression(LOGISTIC_DF, params)
        assert run["class_labels"] == []
