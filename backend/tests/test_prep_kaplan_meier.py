"""
Milestone 2 — analysis-specific data preparation: Kaplan-Meier.

KM has three roles with different handling:
  - duration: numeric role (coerced + normalized)
  - event:    categorical role with special encoding validation
  - group:    categorical role, preserved exactly (never coerced, even when
              the labels look numeric such as 0/1/2)

The product-limit math is unchanged and validated by the Milestone 1
fixtures; this file covers data preparation only.
"""
import pandas as pd
import pytest

from app.tasks.analysis import AnalysisValidationError, _run_kaplan_meier


def test_grouped_number_duration_is_normalized():
    df = pd.DataFrame({
        "dur": ["2", "3", "1,000", "5", "7", "9"],  # normalized at idx 2
        "evt": [1, 1, 0, 1, 1, 0],
    })
    result = _run_kaplan_meier(df, {"time_column": "dur", "event_column": "evt"})
    assert result["processing"]["dur"]["role"] == "duration"
    assert result["processing"]["dur"]["normalized"] == 1
    assert result["processing"]["dur"]["normalized_rule"] == "english_thousands_grouping"


def test_numeric_looking_group_labels_are_preserved_not_coerced():
    # Group coded 0/1 must stay categorical — the result keys are the group
    # labels, and the group column is never numerically coerced.
    df = pd.DataFrame({
        "dur": [2, 3, 5, 4, 7, 9],
        "evt": [1, 1, 1, 0, 1, 0],
        "grp": [0, 1, 0, 1, 0, 1],
    })
    result = _run_kaplan_meier(
        df, {"time_column": "dur", "event_column": "evt", "group_column": "grp"}
    )
    group_keys = {k for k in result if k not in ("processing", "_meta")}
    assert group_keys == {"0", "1"}
    assert result["processing"]["grp"]["role"] == "group"
    # group is categorical: no non-numeric framing
    assert "non_numeric" not in result["processing"]["grp"]


def test_string_group_labels_are_preserved():
    df = pd.DataFrame({
        "dur": [2, 3, 5, 4, 7, 9],
        "evt": [1, 1, 1, 0, 1, 0],
        "grp": ["A", "A", "A", "B", "B", "B"],
    })
    result = _run_kaplan_meier(
        df, {"time_column": "dur", "event_column": "evt", "group_column": "grp"}
    )
    group_keys = {k for k in result if k not in ("processing", "_meta")}
    assert group_keys == {"A", "B"}


def test_boolean_events_accepted_without_event_value():
    df = pd.DataFrame({"dur": [2, 3, 4, 5], "evt": [True, True, False, True]})
    result = _run_kaplan_meier(df, {"time_column": "dur", "event_column": "evt"})
    assert result["overall"]["median_survival"] == pytest.approx(3.0)


def test_zero_one_events_accepted_without_event_value():
    df = pd.DataFrame({"dur": [2, 3, 4, 5], "evt": [1, 1, 0, 1]})
    result = _run_kaplan_meier(df, {"time_column": "dur", "event_column": "evt"})
    assert result["overall"]["median_survival"] == pytest.approx(3.0)


def test_explicit_textual_event_value_supported():
    df = pd.DataFrame({
        "dur": [2, 3, 4, 5],
        "evt": ["relapse", "relapse", "censored", "relapse"],
    })
    result = _run_kaplan_meier(
        df, {"time_column": "dur", "event_column": "evt", "event_value": "relapse"}
    )
    assert result["overall"]["median_survival"] == pytest.approx(3.0)


def test_ambiguous_event_encoding_rejected_without_event_value():
    # Values other than 0/1/boolean (here a "2") are ambiguous when no
    # event_value is given — reject rather than guess.
    df = pd.DataFrame({"dur": [2, 3, 4, 5], "evt": [1, 2, 1, 2]})
    with pytest.raises(AnalysisValidationError, match="boolean or coded 0/1"):
        _run_kaplan_meier(df, {"time_column": "dur", "event_column": "evt"})


def test_string_event_encoding_rejected_without_event_value():
    df = pd.DataFrame({"dur": [2, 3, 4, 5], "evt": ["yes", "no", "yes", "no"]})
    with pytest.raises(AnalysisValidationError, match="boolean or coded 0/1"):
        _run_kaplan_meier(df, {"time_column": "dur", "event_column": "evt"})


def test_overlapping_exclusions_counted_once_in_meta():
    # duration non-numeric at idx 2; that same row would also be dropped for
    # any other reason — the joint mask counts it once.
    df = pd.DataFrame({
        "dur": ["2", "3", "C", "5", "7"],  # non-numeric at idx 2
        "evt": [1, 1, 1, None, 1],          # missing at idx 3
    })
    result = _run_kaplan_meier(df, {"time_column": "dur", "event_column": "evt"})
    # idx 2 (duration) and idx 3 (event) are different rows -> 2 dropped
    assert result["_meta"] == {"total_rows": 5, "used_rows": 3, "dropped_rows": 2}
    assert result["processing"]["dur"]["non_numeric"] == 1
    assert result["processing"]["evt"]["missing"] == 1


def test_duration_and_event_dropped_on_same_row_counted_once():
    df = pd.DataFrame({
        "dur": ["2", "3", "C", "5"],  # non-numeric at idx 2
        "evt": [1, 1, None, 1],        # missing at idx 2 (SAME row)
    })
    result = _run_kaplan_meier(df, {"time_column": "dur", "event_column": "evt"})
    # only idx 2 dropped, counted once despite two reasons
    assert result["_meta"] == {"total_rows": 4, "used_rows": 3, "dropped_rows": 1}


def test_no_usable_rows_raises_validation_error():
    df = pd.DataFrame({"dur": ["C", "ND", None], "evt": [1, 1, 0]})
    with pytest.raises(AnalysisValidationError, match="No rows have usable values"):
        _run_kaplan_meier(df, {"time_column": "dur", "event_column": "evt"})
