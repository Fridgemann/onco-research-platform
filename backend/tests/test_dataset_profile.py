"""
Milestone 4, Slice 2 — dataset profiling (unit level).

The inspect endpoint returns real cell values, so the profiler has two jobs
that matter equally: describe the data usefully, and never overstate what it
actually looked at. A profile computed from a capped subset must say so —
sampled counts presented as global would quietly mislead a clinician about
their own cohort.

All fixtures here are synthetic.
"""
import json

import pandas as pd
import pytest

from app.services.analysis_prep import AnalysisValidationError, profile_dataset
from app.schemas.dataset import (
    INSPECT_MAX_COLUMN_NAME_LEN,
    INSPECT_MAX_COLUMNS,
    INSPECT_MAX_DISTINCT,
    INSPECT_MAX_SAMPLE_ROWS,
    INSPECT_MAX_STRING_LEN,
)


def _col(profile: dict, name: str) -> dict:
    return next(c for c in profile["columns"] if c["name"] == name)


# ── Profile scope: sampled counts are never presented as global ─────────────

def test_full_scope_reports_total_rows():
    df = pd.DataFrame({"Age": [58, 71, 48]})
    p = profile_dataset(df, truncated=False)
    assert p["profile"] == {
        "profiled_rows": 3, "profile_scope": "full", "total_rows": 3,
    }


def test_partial_scope_reports_unknown_total_rather_than_guessing():
    df = pd.DataFrame({"Age": list(range(100))})
    p = profile_dataset(df, truncated=True)
    assert p["profile"]["profile_scope"] == "partial"
    assert p["profile"]["profiled_rows"] == 100
    # unknown, not estimated
    assert p["profile"]["total_rows"] is None


def test_partial_scope_column_counts_are_scoped_to_profiled_rows():
    # 60 rows profiled out of an unknown larger file; 10 missing among them.
    df = pd.DataFrame({"Value": [None] * 10 + list(range(50))})
    p = profile_dataset(df, truncated=True)
    col = _col(p, "Value")
    assert p["profile"]["profiled_rows"] == 60
    assert col["missing"] == 10
    assert col["missing_percent"] == pytest.approx(100 * 10 / 60)


# ── Display types (hints only, never authoritative) ─────────────────────────

def test_display_type_numeric():
    df = pd.DataFrame({"Age": [58, 71, 48, 34]})
    assert _col(profile_dataset(df, truncated=False), "Age")["display_type"] == "numeric"


def test_display_type_binary_requires_both_codes():
    df = pd.DataFrame({"Flag": [0, 1, 1, 0]})
    assert _col(profile_dataset(df, truncated=False), "Flag")["display_type"] == "binary"


def test_constant_zero_column_is_not_binary():
    df = pd.DataFrame({"Flag": [0, 0, 0]})
    assert _col(profile_dataset(df, truncated=False), "Flag")["display_type"] != "binary"


def test_display_type_categorical_for_text():
    df = pd.DataFrame({"Arm": ["A", "B", "A"]})
    assert _col(profile_dataset(df, truncated=False), "Arm")["display_type"] == "categorical"


def test_all_missing_column_is_reported_as_empty_not_guessed():
    df = pd.DataFrame({"Blank": [None, None, None]})
    col = _col(profile_dataset(df, truncated=False), "Blank")
    assert col["display_type"] == "empty"
    assert col["missing"] == 3


# ── Caps ────────────────────────────────────────────────────────────────────

def test_sample_rows_capped():
    df = pd.DataFrame({"Age": list(range(500))})
    p = profile_dataset(df, truncated=False)
    assert len(p["sample_rows"]) == INSPECT_MAX_SAMPLE_ROWS


def test_wide_dataset_truncates_columns_explicitly():
    wide = {f"c{i}": [1, 2] for i in range(INSPECT_MAX_COLUMNS + 25)}
    p = profile_dataset(pd.DataFrame(wide), truncated=False)

    assert p["column_count"] == INSPECT_MAX_COLUMNS + 25   # true width of the file
    assert p["columns_returned"] == INSPECT_MAX_COLUMNS    # what is described below
    assert p["columns_truncated"] is True
    assert len(p["columns"]) == INSPECT_MAX_COLUMNS
    # sample rows must not smuggle in the columns we said we dropped
    assert all(len(row) <= INSPECT_MAX_COLUMNS for row in p["sample_rows"])


def test_narrow_dataset_is_not_marked_truncated():
    p = profile_dataset(pd.DataFrame({"a": [1], "b": [2]}), truncated=False)
    assert p["columns_truncated"] is False
    assert p["column_count"] == p["columns_returned"] == 2


def test_distinct_values_capped_and_count_null_when_over_cap():
    df = pd.DataFrame({"Many": [f"v{i}" for i in range(INSPECT_MAX_DISTINCT + 5)]})
    col = _col(profile_dataset(df, truncated=False), "Many")
    assert col["distinct_count"] is None      # unknown-above-cap, not a wrong number
    assert col["distinct_values"] is None


def test_distinct_values_returned_when_within_cap():
    df = pd.DataFrame({"Arm": ["A", "B", "A", "B"]})
    col = _col(profile_dataset(df, truncated=False), "Arm")
    assert col["distinct_count"] == 2
    assert {v["value"] for v in col["distinct_values"]} == {"A", "B"}
    assert all(v["value_type"] == "string" for v in col["distinct_values"])


def test_long_strings_truncated_in_samples_and_distinct_values():
    long = "x" * (INSPECT_MAX_STRING_LEN + 50)
    df = pd.DataFrame({"Note": [long, long]})
    p = profile_dataset(df, truncated=False)
    assert len(p["sample_rows"][0]["Note"]) <= INSPECT_MAX_STRING_LEN
    col = _col(p, "Note")
    assert all(len(v["value"]) <= INSPECT_MAX_STRING_LEN for v in col["distinct_values"])


# ── Typed, JSON-safe cell values ────────────────────────────────────────────

def test_sample_cells_preserve_type_and_are_json_safe():
    df = pd.DataFrame({
        "i": [58], "f": [16.5], "s": ["A"], "b": [True], "missing": [None],
    })
    p = profile_dataset(df, truncated=False)
    row = p["sample_rows"][0]
    assert row["i"] == 58 and isinstance(row["i"], int)
    assert row["f"] == pytest.approx(16.5)
    assert row["s"] == "A"
    assert row["b"] is True
    assert row["missing"] is None
    # strict serialization: no NaN/Infinity may reach the client
    json.dumps(p, allow_nan=False)


def test_overlong_column_name_is_rejected_without_echoing_it():
    # Bounding the column COUNT does not bound the response: each name is
    # repeated as a JSON key in every sample row, so one huge header would
    # amplify the payload. Names are identifiers, so reject rather than
    # truncate — and never echo the name itself.
    huge = "h" * (INSPECT_MAX_COLUMN_NAME_LEN + 1)
    df = pd.DataFrame({huge: [1, 2], "ok": [3, 4]})
    with pytest.raises(AnalysisValidationError) as exc:
        profile_dataset(df, truncated=False)
    msg = str(exc.value)
    assert str(INSPECT_MAX_COLUMN_NAME_LEN) in msg
    assert huge not in msg          # count only, never the identifier


def test_column_name_at_the_limit_is_accepted():
    ok_name = "h" * INSPECT_MAX_COLUMN_NAME_LEN
    p = profile_dataset(pd.DataFrame({ok_name: [1, 2]}), truncated=False)
    assert p["columns"][0]["name"] == ok_name


def test_integers_stay_integers_beside_a_float_column():
    # Regression: iterrows() builds one Series per row, so an all-numeric row
    # is upcast to a single float dtype and 58 would be reported as 58.0.
    # A row with no string/bool column is exactly the case that hides it.
    df = pd.DataFrame({"age": [58, 71], "bmi": [16.5, 22.25]})
    row = profile_dataset(df, truncated=False)["sample_rows"][0]
    assert row["age"] == 58
    assert isinstance(row["age"], int) and not isinstance(row["age"], bool)
    assert row["bmi"] == pytest.approx(16.5)
    assert isinstance(row["bmi"], float)


def test_numeric_one_and_string_one_stay_distinct():
    df = pd.DataFrame({"mixed": [1, "1", 1, "1"]})
    col = _col(profile_dataset(df, truncated=False), "mixed")
    typed = {(v["value_type"], v["value"]) for v in col["distinct_values"]}
    assert ("number", 1.0) in typed
    assert ("string", "1") in typed


def test_non_finite_numbers_do_not_break_json_safety():
    df = pd.DataFrame({"x": [1.0, float("inf"), float("nan")]})
    p = profile_dataset(df, truncated=False)
    json.dumps(p, allow_nan=False)
