"""
Milestone 2 — analysis-specific data preparation: linear regression.

Linear regression treats the target AND every feature as numeric roles.
This file covers the data-preparation behavior only (coercion, joint row
alignment, per-column processing report) — the underlying OLS math is
unchanged and is validated separately by the Milestone 1 fixtures.
"""
import pandas as pd
import pytest

from app.tasks.analysis import AnalysisValidationError, _run_regression


def test_target_and_features_are_normalized_and_reported():
    # target has an English-grouped thousands value; feature has one too.
    df = pd.DataFrame({
        "x": ["1", "2", "1,000", "4", "5"],
        "y": ["10", "2,000", "30", "40", "50"],
    })
    result = _run_regression(df, {"target_column": "y", "feature_columns": ["x"]})

    assert result["processing"]["y"]["role"] == "target"
    assert result["processing"]["y"]["normalized"] == 1
    assert result["processing"]["y"]["normalized_rule"] == "english_thousands_grouping"
    assert result["processing"]["x"]["role"] == "feature"
    assert result["processing"]["x"]["normalized"] == 1
    # all 5 rows usable after normalization
    assert result["_meta"] == {"total_rows": 5, "used_rows": 5, "dropped_rows": 0}
    assert result["n"] == 5


def test_rows_are_jointly_aligned_across_target_and_feature():
    # target non-numeric at index 2; feature missing at index 3 — different
    # rows, so both are excluded and the survivors stay row-aligned.
    df = pd.DataFrame({
        "x": ["1", "2", "3", None, "5", "6"],
        "y": ["10", "20", "C", "40", "50", "60"],
    })
    result = _run_regression(df, {"target_column": "y", "feature_columns": ["x"]})

    assert result["_meta"] == {"total_rows": 6, "used_rows": 4, "dropped_rows": 2}
    assert result["n"] == 4
    assert result["processing"]["y"]["non_numeric"] == 1
    assert result["processing"]["y"]["top_non_numeric_codes"] == {"C": 1}
    assert result["processing"]["x"]["missing"] == 1


def test_overlapping_exclusions_counted_once_in_meta():
    # Both target and feature are invalid at the SAME row (index 2): target
    # non-numeric, feature missing. The joint mask drops that row once, so
    # used_rows reflects the union of exclusions, not the sum.
    df = pd.DataFrame({
        "x": ["1", "2", None, "4", "5"],
        "y": ["10", "20", "C", "40", "50"],
    })
    result = _run_regression(df, {"target_column": "y", "feature_columns": ["x"]})

    # per-column counts still report each column's own exclusion...
    assert result["processing"]["y"]["non_numeric"] == 1
    assert result["processing"]["x"]["missing"] == 1
    # ...but the joint _meta counts the shared row only once.
    assert result["_meta"] == {"total_rows": 5, "used_rows": 4, "dropped_rows": 1}


def test_multiple_features_jointly_aligned():
    df = pd.DataFrame({
        "x1": ["1", "2", "3", "4", None, "6"],   # missing at idx 4
        "x2": ["1", "1", "C", "2", "3", "3"],     # non-numeric at idx 2
        "y":  ["8", "10", "15", "17", "22", "25"],
    })
    result = _run_regression(df, {"target_column": "y", "feature_columns": ["x1", "x2"]})

    assert result["type"] == "multiple_linear"
    # idx 2 and idx 4 dropped -> 4 usable rows
    assert result["_meta"] == {"total_rows": 6, "used_rows": 4, "dropped_rows": 2}
    assert result["processing"]["x1"]["missing"] == 1
    assert result["processing"]["x2"]["non_numeric"] == 1


def test_no_usable_rows_raises_validation_error():
    df = pd.DataFrame({"x": ["C", "ND", None], "y": ["1", "2", "3"]})
    with pytest.raises(AnalysisValidationError, match="No rows have usable numeric values"):
        _run_regression(df, {"target_column": "y", "feature_columns": ["x"]})
