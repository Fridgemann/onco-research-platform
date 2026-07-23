"""
Unit tests for binary-coded column detection in descriptive statistics
(app/tasks/analysis.py: _binary_code_counts, wired into _run_descriptive_stats).

A column is "binary" here purely in the sense that its usable numeric values
are exactly {0, 1} — never a claim about what those codes mean (yes/no,
male/female, etc.). Meaning comes from the researcher's own dataset
documentation, not from this platform.
"""
import pandas as pd
import pytest

from app.tasks.analysis import _binary_code_counts, _run_descriptive_stats


# ── _binary_code_counts: unit-level ─────────────────────────────────────────

def test_normal_0_1_data_is_detected_as_binary():
    result = _binary_code_counts(pd.Series([0.0, 1.0, 0.0, 1.0, 1.0]))
    assert result == {
        "coded_0": {"count": 2, "percent": 40.0},
        "coded_1": {"count": 3, "percent": 60.0},
    }


def test_string_0_1_values_are_detected_as_binary_after_coercion():
    # _coerce_numeric already turns "0"/"1" strings into floats — this
    # confirms _binary_code_counts works on that coerced output directly.
    coerced = pd.to_numeric(pd.Series(["0", "1", "1", "0"]))
    result = _binary_code_counts(coerced)
    assert result == {
        "coded_0": {"count": 2, "percent": 50.0},
        "coded_1": {"count": 2, "percent": 50.0},
    }


def test_non_binary_low_cardinality_column_is_not_classified_as_binary():
    # Only two distinct values, but not {0, 1} — must not be misdetected.
    result = _binary_code_counts(pd.Series([1.0, 2.0, 1.0, 2.0]))
    assert result is None


def test_three_valued_column_is_not_binary():
    result = _binary_code_counts(pd.Series([0.0, 1.0, 2.0, 0.0]))
    assert result is None


def test_all_zero_column_is_not_binary():
    # Exact equality, not subset: a constant column isn't a demonstrated
    # binary code just because 0 happens to be one of the two allowed values.
    result = _binary_code_counts(pd.Series([0.0, 0.0, 0.0, 0.0]))
    assert result is None


def test_all_one_column_is_not_binary():
    result = _binary_code_counts(pd.Series([1.0, 1.0, 1.0]))
    assert result is None


def test_all_zero_column_is_not_binary_through_descriptive_stats():
    df = pd.DataFrame({"Flag": [0, 0, 0, 0, 0]})
    result = _run_descriptive_stats(df, {"columns": ["Flag"]})
    assert result["Flag"]["is_binary"] is False
    assert result["Flag"]["binary_counts"] is None


# ── Integration through _run_descriptive_stats: missing/coded exclusion ────

def test_missing_and_non_numeric_values_excluded_from_binary_denominator():
    df = pd.DataFrame({"Flag": ["0", "1", None, "C", "1"]})
    result = _run_descriptive_stats(df, {"columns": ["Flag"]})
    col = result["Flag"]

    assert col["missing"] == 1
    assert col["non_numeric"] == 1
    assert col["is_binary"] is True
    # usable values: 0, 1, 1 -> total 3
    assert col["binary_counts"]["coded_0"] == {"count": 1, "percent": pytest.approx(33.333, abs=0.01)}
    assert col["binary_counts"]["coded_1"] == {"count": 2, "percent": pytest.approx(66.667, abs=0.01)}


def test_existing_statistics_still_present_on_binary_column():
    # Backward compatibility: adding is_binary/binary_counts must not remove
    # the existing mean/std/etc. fields.
    df = pd.DataFrame({"Flag": [0, 1, 0, 1]})
    result = _run_descriptive_stats(df, {"columns": ["Flag"]})
    col = result["Flag"]
    for key in ("count", "mean", "std", "min", "p25", "median", "p75", "max"):
        assert key in col


def test_non_binary_column_has_is_binary_false_and_no_counts():
    df = pd.DataFrame({"Score": [1, 2, 3, 4, 5]})
    result = _run_descriptive_stats(df, {"columns": ["Score"]})
    col = result["Score"]
    assert col["is_binary"] is False
    assert col["binary_counts"] is None


# ── Realistic columns: Age, Gender, mixed financial Value ──────────────────

def test_age_like_continuous_column_is_not_binary():
    df = pd.DataFrame({"Age": [58, 71, 48, 34, 62, 27, 80, 40, 58, 77]})
    result = _run_descriptive_stats(df, {"columns": ["Age"]})
    assert result["Age"]["is_binary"] is False
    assert result["Age"]["binary_counts"] is None


def test_gender_like_0_1_column_is_binary_with_correct_counts():
    df = pd.DataFrame({"Gender": [1, 0, 1, 1, 0, 1, 0, 0, 1, 0]})
    result = _run_descriptive_stats(df, {"columns": ["Gender"]})
    col = result["Gender"]
    assert col["is_binary"] is True
    assert col["binary_counts"] == {
        "coded_0": {"count": 5, "percent": 50.0},
        "coded_1": {"count": 5, "percent": 50.0},
    }


def test_mixed_financial_value_column_is_not_binary():
    # Many distinct numeric values plus confidentiality codes — the exact
    # scenario that originally motivated the non-numeric coercion work.
    df = pd.DataFrame({"Value": ["123", "456", "789", "1,148", "C", "C"]})
    result = _run_descriptive_stats(df, {"columns": ["Value"]})
    col = result["Value"]
    assert col["is_binary"] is False
    assert col["binary_counts"] is None
    assert col["non_numeric"] == 2
    assert col["normalized"] == 1


# ── Binary-card data-quality fields (count/missing/non_numeric alongside
#    binary_counts) — the frontend card renders these together, so a binary
#    result must carry accurate data-quality context, not just the split. ──

def test_binary_column_result_includes_usable_count_alongside_binary_counts():
    df = pd.DataFrame({"Flag": [0, 1, 0, 1, 1]})
    result = _run_descriptive_stats(df, {"columns": ["Flag"]})
    col = result["Flag"]
    assert col["is_binary"] is True
    assert col["count"] == 5
    assert col["missing"] == 0
    assert col["non_numeric"] == 0
    assert col["binary_counts"]["coded_0"]["count"] + col["binary_counts"]["coded_1"]["count"] == col["count"]


def test_binary_column_result_reports_missing_and_non_numeric_with_binary_counts():
    df = pd.DataFrame({"Flag": ["0", "1", None, "ND", "1", "0"]})
    result = _run_descriptive_stats(df, {"columns": ["Flag"]})
    col = result["Flag"]
    assert col["is_binary"] is True
    assert col["count"] == 4
    assert col["missing"] == 1
    assert col["non_numeric"] == 1
    assert col["binary_counts"] == {
        "coded_0": {"count": 2, "percent": 50.0},
        "coded_1": {"count": 2, "percent": 50.0},
    }
