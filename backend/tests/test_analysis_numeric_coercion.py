"""
Unit tests for _coerce_numeric (app/tasks/analysis.py).

Covers the English-style thousands-grouping parser: which values it accepts
as "just formatting" and safely converts, and which it correctly refuses to
guess at because they're ambiguous or potentially meaningful.
"""
import pandas as pd
import pytest

from app.tasks.analysis import (
    _CODE_STRING_MAX_LEN,
    AnalysisValidationError,
    _coerce_numeric,
    _run_descriptive_stats,
)


# ── Accepted: plain numbers pandas already parses fine ──────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("12.5", 12.5),
    ("-3.75", -3.75),
    ("0", 0.0),
    ("42", 42.0),
])
def test_plain_numbers_parse_without_grouping_logic(raw, expected):
    result = _coerce_numeric(pd.Series([raw]))
    assert result["values"].iloc[0] == expected
    assert result["non_numeric_rows"] == 0


# ── Accepted: English-style grouped thousands ────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("1,234", 1234.0),
    ("1,234.56", 1234.56),
    ("1,234,567.89", 1234567.89),
    ("-1,234", -1234.0),
    ("+1,234", 1234.0),
    (" 1,234 ", 1234.0),  # surrounding whitespace trimmed
])
def test_english_grouped_thousands_are_parsed(raw, expected):
    result = _coerce_numeric(pd.Series([raw]))
    assert result["non_numeric_rows"] == 0
    assert result["values"].iloc[0] == pytest.approx(expected)


# ── Rejected: ambiguous or meaningful values, never guessed at ─────────────

@pytest.mark.parametrize("raw", [
    "12,5",        # European decimal comma (12.5) — ambiguous with grouping
    "1.234,56",    # European thousands+decimal (1234.56) — wrong locale
    "1,23",        # malformed grouping (group not exactly 3 digits)
    "C",           # confidentiality / censor code
    "ND",          # not-detected assay flag
    "<5",          # below-detection-limit marker
    "12 mg/L",     # embedded unit
    "unknown",     # explicit unknown marker
])
def test_ambiguous_or_coded_values_are_not_guessed(raw):
    result = _coerce_numeric(pd.Series([raw]))
    assert result["non_numeric_rows"] == 1
    assert result["values"].empty


def test_missing_values_are_not_counted_as_non_numeric():
    result = _coerce_numeric(pd.Series(["1,234", None, "C"]))
    assert result["missing_rows"] == 1
    assert result["non_numeric_rows"] == 1
    assert list(result["values"]) == [1234.0]


def test_top_non_numeric_codes_reports_counts():
    series = pd.Series(["C"] * 3 + ["ND"] * 2 + ["1,234"])
    result = _coerce_numeric(series)
    assert result["top_non_numeric_codes"] == {"C": 3, "ND": 2}


# ── Normalized-value reporting ──────────────────────────────────────────────

def test_normalized_rows_counted_and_rule_reported():
    result = _coerce_numeric(pd.Series(["1,148", "1,422", "42", "C"]))
    assert result["normalized_rows"] == 2
    assert result["normalized_rule"] == "english_thousands_grouping"


def test_no_normalization_reports_zero_and_no_rule():
    result = _coerce_numeric(pd.Series(["42", "C"]))
    assert result["normalized_rows"] == 0
    assert result["normalized_rule"] is None
    assert result["normalized_examples"] == []


def test_normalized_examples_are_capped_and_distinct():
    # "1,148" appears 5 times — must not fill all 3 example slots by itself.
    series = pd.Series(["1,148"] * 5 + ["1,422", "1,122", "1,999"])
    result = _coerce_numeric(series)
    assert result["normalized_rows"] == 8
    raws = [ex["raw"] for ex in result["normalized_examples"]]
    assert len(raws) == 3
    assert len(set(raws)) == 3  # all distinct, no repeats


def test_normalized_example_values_are_raw_to_parsed_pairs():
    result = _coerce_numeric(pd.Series(["1,148"]))
    assert result["normalized_examples"] == [{"raw": "1,148", "parsed": 1148.0}]


def test_normalized_examples_dedupe_before_truncation_not_after():
    # Two distinct long values sharing the same first N chars must NOT be
    # treated as duplicates just because their truncated display forms match.
    long_a = "1," + "234," * 20 + "567"
    long_b = "1," + "234," * 20 + "999"
    assert long_a[:_CODE_STRING_MAX_LEN] == long_b[:_CODE_STRING_MAX_LEN]  # same prefix
    result = _coerce_numeric(pd.Series([long_a, long_b]))
    assert result["normalized_rows"] == 2
    assert len(result["normalized_examples"]) == 2


def test_normalized_example_raw_value_is_truncated_for_display():
    long_value = "1," + "234," * 20 + "567"
    assert len(long_value) > _CODE_STRING_MAX_LEN
    result = _coerce_numeric(pd.Series([long_value]))
    example = result["normalized_examples"][0]
    assert len(example["raw"]) == _CODE_STRING_MAX_LEN
    assert example["raw"].endswith("...")
    assert example["parsed"] == float(long_value.replace(",", ""))


# ── Integration: _run_descriptive_stats end to end ──────────────────────────

def test_descriptive_stats_treats_grouped_thousands_as_numeric():
    df = pd.DataFrame({"Value": ["1,148", "1,422", "1,122", "C"]})
    result = _run_descriptive_stats(df, {"columns": ["Value"]})
    assert result["Value"]["count"] == 3
    assert result["Value"]["non_numeric"] == 1
    assert result["Value"]["top_non_numeric_codes"] == {"C": 1}
    assert result["Value"]["normalized"] == 3
    assert result["Value"]["normalized_rule"] == "english_thousands_grouping"
    assert result["Value"]["normalized_examples"] == [
        {"raw": "1,148", "parsed": 1148.0},
        {"raw": "1,422", "parsed": 1422.0},
        {"raw": "1,122", "parsed": 1122.0},
    ]


def test_descriptive_stats_fails_cleanly_with_no_usable_values():
    df = pd.DataFrame({"Value": ["C", "ND", None]})
    with pytest.raises(AnalysisValidationError, match="no usable numeric values"):
        _run_descriptive_stats(df, {"columns": ["Value"]})
