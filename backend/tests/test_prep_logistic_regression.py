"""
Milestone 2 — analysis-specific data preparation: logistic regression.

Logistic regression treats the feature columns as numeric roles (coerced +
normalized) and the target as a categorical role: its original class labels
are preserved exactly, never sent through numeric coercion, and exactly two
usable classes must remain after joint filtering. The underlying sklearn
fit (including its default L2 regularization) is unchanged — see the
Milestone 1 fixtures for the numerical validation.
"""
import pandas as pd
import pytest

from app.tasks.analysis import AnalysisValidationError, _run_logistic_regression


def test_string_class_labels_preserved_while_features_normalized():
    df = pd.DataFrame({
        "hours": ["1", "2", "3", "1,000", "5", "6", "7", "8"],  # normalized at idx 3
        "result": ["fail", "fail", "fail", "pass", "pass", "fail", "pass", "pass"],
    })
    result = _run_logistic_regression(df, {"target_column": "result", "feature_columns": ["hours"]})

    # original string labels preserved, not coerced to numbers
    assert result["classes"] == ["fail", "pass"]
    # target is categorical: reported as such, with no non-numeric framing
    assert result["processing"]["result"]["role"] == "target"
    assert "non_numeric" not in result["processing"]["result"]
    # feature is numeric: normalization reported
    assert result["processing"]["hours"]["role"] == "feature"
    assert result["processing"]["hours"]["normalized"] == 1


def test_rows_dropped_jointly_and_exactly_two_classes_remain():
    # feature missing at idx 1, target missing at idx 5 — different rows.
    df = pd.DataFrame({
        "x": ["1", None, "3", "4", "5", "6"],
        "y": ["a", "a", "b", "a", "b", None],
    })
    result = _run_logistic_regression(df, {"target_column": "y", "feature_columns": ["x"]})

    assert result["_meta"] == {"total_rows": 6, "used_rows": 4, "dropped_rows": 2}
    assert result["n"] == 4
    assert sorted(result["classes"]) == ["a", "b"]
    assert result["processing"]["x"]["missing"] == 1
    assert result["processing"]["y"]["missing"] == 1


def test_three_original_classes_reduced_to_two_by_filtering_is_accepted():
    # 'c' appears only on a row whose feature is unusable, so after joint
    # filtering exactly two classes ('a','b') remain — this is valid.
    df = pd.DataFrame({
        "x": ["1", "2", "C", "4", "5"],   # non-numeric at idx 2
        "y": ["a", "b", "c", "a", "b"],   # 'c' only at idx 2
    })
    result = _run_logistic_regression(df, {"target_column": "y", "feature_columns": ["x"]})

    assert sorted(result["classes"]) == ["a", "b"]
    assert result["_meta"]["used_rows"] == 4


def test_one_remaining_class_raises_validation_error():
    df = pd.DataFrame({"x": ["1", "2", "3"], "y": ["pass", "pass", "pass"]})
    with pytest.raises(AnalysisValidationError, match="exactly two outcome classes"):
        _run_logistic_regression(df, {"target_column": "y", "feature_columns": ["x"]})


def test_more_than_two_remaining_classes_raises_validation_error():
    df = pd.DataFrame({"x": ["1", "2", "3", "4"], "y": ["a", "b", "c", "a"]})
    with pytest.raises(AnalysisValidationError, match="exactly two outcome classes"):
        _run_logistic_regression(df, {"target_column": "y", "feature_columns": ["x"]})


def test_no_usable_rows_raises_validation_error():
    df = pd.DataFrame({"x": ["C", "ND", None], "y": ["a", "b", "a"]})
    with pytest.raises(AnalysisValidationError, match="No rows have usable values"):
        _run_logistic_regression(df, {"target_column": "y", "feature_columns": ["x"]})


def test_class_count_error_message_contains_no_cell_values():
    # Safety: the validation message must not leak dataset cell contents.
    df = pd.DataFrame({"x": ["1", "2", "3"], "y": ["secret_label", "secret_label", "secret_label"]})
    with pytest.raises(AnalysisValidationError) as exc_info:
        _run_logistic_regression(df, {"target_column": "y", "feature_columns": ["x"]})
    assert "secret_label" not in str(exc_info.value)
