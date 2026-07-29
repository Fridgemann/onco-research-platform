"""
Milestone 3 (Turn A) — KM censoring/event mapping and preflight counts.

Covers _km_prepare and the event-mapping resolution it uses: typed value
matching (no True==1 conflation), automatic 0/1/boolean mapping, explicit
textual/multi-label mappings, exclusion, unmapped rejection, the all-events
confirmation branch, count identities, and preflight==final equivalence.
"""
import numpy as np
import pandas as pd
import pytest

from app.tasks.analysis import (
    AnalysisValidationError,
    _cell_status_key,
    _km_prepare,
    _run_kaplan_meier,
)


# ── Type-safe key normalization (the True==1 bug) ───────────────────────────

def test_boolean_cell_key_is_not_conflated_with_number_one():
    assert _cell_status_key(True) == ("boolean", True)
    assert _cell_status_key(False) == ("boolean", False)
    assert _cell_status_key(1) == ("number", 1.0)
    assert _cell_status_key(0) == ("number", 0.0)
    # numpy scalars behave the same
    assert _cell_status_key(np.bool_(True)) == ("boolean", True)
    assert _cell_status_key(np.int64(1)) == ("number", 1.0)


def test_string_one_zero_are_strings_not_numbers():
    assert _cell_status_key("1") == ("string", "1")
    assert _cell_status_key("0") == ("string", "0")


# ── Automatic mapping (standard 0/1 and boolean) ────────────────────────────

def test_standard_0_1_auto_maps_without_explicit_mapping():
    df = pd.DataFrame({"dur": [2, 3, 4, 5], "evt": [1, 1, 0, 1]})
    prep = _km_prepare(df, {"time_column": "dur", "event_column": "evt", "has_censoring": True})
    assert prep["counts"]["events"] == 3
    assert prep["counts"]["censored"] == 1


def test_boolean_status_auto_maps():
    df = pd.DataFrame({"dur": [2, 3, 4, 5], "evt": [True, True, False, True]})
    prep = _km_prepare(df, {"time_column": "dur", "event_column": "evt", "has_censoring": True})
    assert prep["counts"]["events"] == 3
    assert prep["counts"]["censored"] == 1


# ── Explicit text / multiple censor labels / exclusion ──────────────────────

def test_text_mappings_resolved():
    df = pd.DataFrame({"dur": [2, 3, 4, 5], "evt": ["relapse", "relapse", "alive", "relapse"]})
    prep = _km_prepare(df, {
        "time_column": "dur", "event_column": "evt", "has_censoring": True,
        "event_mapping": [
            {"value": "relapse", "value_type": "string", "role": "event"},
            {"value": "alive", "value_type": "string", "role": "censored"},
        ],
    })
    assert prep["counts"]["events"] == 3
    assert prep["counts"]["censored"] == 1


def test_multiple_censor_labels_all_map_to_censored():
    df = pd.DataFrame({
        "dur": [2, 3, 4, 5, 6],
        "evt": ["dead", "lost_to_followup", "withdrew", "dead", "alive"],
    })
    prep = _km_prepare(df, {
        "time_column": "dur", "event_column": "evt", "has_censoring": True,
        "event_mapping": [
            {"value": "dead", "value_type": "string", "role": "event"},
            {"value": "lost_to_followup", "value_type": "string", "role": "censored"},
            {"value": "withdrew", "value_type": "string", "role": "censored"},
            {"value": "alive", "value_type": "string", "role": "censored"},
        ],
    })
    assert prep["counts"]["events"] == 2
    assert prep["counts"]["censored"] == 3


def test_excluded_values_leave_analysis_and_are_counted():
    df = pd.DataFrame({
        "dur": [2, 3, 4, 5],
        "evt": ["event", "censored", "unknown", "event"],
    })
    prep = _km_prepare(df, {
        "time_column": "dur", "event_column": "evt", "has_censoring": True,
        "event_mapping": [
            {"value": "event", "value_type": "string", "role": "event"},
            {"value": "censored", "value_type": "string", "role": "censored"},
            {"value": "unknown", "value_type": "string", "role": "exclude"},
        ],
    })
    assert prep["counts"]["used_rows"] == 3
    assert prep["counts"]["events"] == 2
    assert prep["counts"]["censored"] == 1
    assert prep["counts"]["exclusions"]["explicitly_excluded"] == 1


def test_explicit_mapping_overrides_auto():
    # Numeric 1 auto-maps to event, but an explicit entry can re-map it.
    df = pd.DataFrame({"dur": [2, 3, 4, 5], "evt": [1, 1, 0, 0]})
    prep = _km_prepare(df, {
        "time_column": "dur", "event_column": "evt", "has_censoring": True,
        "event_mapping": [
            {"value": 1, "value_type": "number", "role": "censored"},
            {"value": 0, "value_type": "number", "role": "event"},
        ],
    })
    assert prep["counts"]["events"] == 2   # the two 0s
    assert prep["counts"]["censored"] == 2  # the two 1s


# ── Unmapped rejection (value-free message) ─────────────────────────────────

def test_unmapped_values_rejected_with_count_only():
    df = pd.DataFrame({"dur": [2, 3, 4, 5], "evt": ["a", "b", "a", "c"]})
    with pytest.raises(AnalysisValidationError) as exc:
        _km_prepare(df, {"time_column": "dur", "event_column": "evt", "has_censoring": True})
    msg = str(exc.value)
    assert "3 distinct status value" in msg  # a, b, c
    for raw in ("a", "b", "c"):
        assert f'"{raw}"' not in msg  # never echo raw values


def test_duplicate_mapping_entries_rejected():
    df = pd.DataFrame({"dur": [2, 3], "evt": ["x", "y"]})
    with pytest.raises(AnalysisValidationError, match="Duplicate or conflicting"):
        _km_prepare(df, {
            "time_column": "dur", "event_column": "evt", "has_censoring": True,
            "event_mapping": [
                {"value": "x", "value_type": "string", "role": "event"},
                {"value": "x", "value_type": "string", "role": "censored"},
                {"value": "y", "value_type": "string", "role": "censored"},
            ],
        })


def test_non_finite_number_mapping_rejected():
    df = pd.DataFrame({"dur": [2, 3], "evt": [1, 0]})
    with pytest.raises(AnalysisValidationError, match="finite"):
        _km_prepare(df, {
            "time_column": "dur", "event_column": "evt", "has_censoring": True,
            "event_mapping": [{"value": float("inf"), "value_type": "number", "role": "event"}],
        })


# ── Missing status is excluded, never silently censored ─────────────────────

def test_missing_status_is_excluded_not_censored():
    df = pd.DataFrame({"dur": [2, 3, 4, 5], "evt": [1, None, 0, 1]})
    prep = _km_prepare(df, {"time_column": "dur", "event_column": "evt", "has_censoring": True})
    assert prep["counts"]["used_rows"] == 3
    assert prep["counts"]["exclusions"]["missing_status"] == 1
    # the missing row is NOT counted as censored
    assert prep["counts"]["events"] == 2
    assert prep["counts"]["censored"] == 1


# ── All-events (no censoring) branch ────────────────────────────────────────

def test_all_events_requires_explicit_confirmation():
    df = pd.DataFrame({"dur": [2, 3, 4]})
    with pytest.raises(AnalysisValidationError, match="confirm"):
        _km_prepare(df, {"time_column": "dur", "has_censoring": False})


def test_all_events_confirmed_treats_every_row_as_event():
    df = pd.DataFrame({"dur": [2, 3, 4, 5]})
    prep = _km_prepare(df, {
        "time_column": "dur", "has_censoring": False, "all_events_confirmed": True,
    })
    assert prep["counts"]["events"] == 4
    assert prep["counts"]["censored"] == 0
    assert prep["counts"]["censoring_percentage"] == 0.0


def test_has_censoring_true_requires_status_column():
    df = pd.DataFrame({"dur": [2, 3, 4]})
    with pytest.raises(AnalysisValidationError, match="status column is required"):
        _km_prepare(df, {"time_column": "dur", "has_censoring": True})


# ── Count identities and reason accounting ──────────────────────────────────

def test_count_identities_hold():
    df = pd.DataFrame({
        "dur": ["2", "C", "4", "5", "6"],     # invalid duration at idx 1
        "evt": [1, 1, None, "drop", 0],        # missing at 2, excluded at 3
        "grp": ["A", "A", "A", "A", "A"],
    })
    prep = _km_prepare(df, {
        "time_column": "dur", "event_column": "evt", "group_column": "grp",
        "has_censoring": True,
        "event_mapping": [{"value": "drop", "value_type": "string", "role": "exclude"}],
    })
    c = prep["counts"]
    assert c["total_rows"] == c["used_rows"] + c["excluded_rows"]
    assert c["used_rows"] == c["events"] + c["censored"]
    assert c["exclusions"]["invalid_duration"] == 1
    assert c["exclusions"]["missing_status"] == 1
    assert c["exclusions"]["explicitly_excluded"] == 1


def test_overlapping_exclusions_counted_once_in_excluded_rows():
    # idx 1: duration invalid AND status missing (same row) -> excluded once.
    df = pd.DataFrame({"dur": ["2", "C", "4"], "evt": [1, None, 0]})
    prep = _km_prepare(df, {"time_column": "dur", "event_column": "evt", "has_censoring": True})
    c = prep["counts"]
    assert c["excluded_rows"] == 1
    # per-reason counts may overlap: both fire for the same row
    assert c["exclusions"]["invalid_duration"] == 1
    assert c["exclusions"]["missing_status"] == 1


# ── Preflight (_km_prepare) counts == final KM run counts ────────────────────

def test_preflight_counts_match_final_analysis_counts():
    df = pd.DataFrame({
        "dur": [2, 3, 4, 5, 6, 7],
        "evt": ["e", "c", "e", "x", "e", "c"],
        "grp": ["A", "A", "B", "B", "B", "A"],
    })
    params = {
        "time_column": "dur", "event_column": "evt", "group_column": "grp",
        "has_censoring": True,
        "event_mapping": [
            {"value": "e", "value_type": "string", "role": "event"},
            {"value": "c", "value_type": "string", "role": "censored"},
            {"value": "x", "value_type": "string", "role": "exclude"},
        ],
    }
    prep = _km_prepare(df, params)
    run = _run_kaplan_meier(df, params)

    # sum the per-group counts from the final run and compare to preflight
    group_keys = run["group_labels"]
    total_events = sum(run[g]["n_events"] for g in group_keys)
    total_censored = sum(run[g]["n_censored"] for g in group_keys)
    total_n = sum(run[g]["n"] for g in group_keys)

    assert total_n == prep["counts"]["used_rows"]
    assert total_events == prep["counts"]["events"]
    assert total_censored == prep["counts"]["censored"]


def test_type_preservation_numeric_one_not_string_one():
    # A numeric status column of 1/0 must be matched by numeric auto-mapping,
    # and a string mapping of "1" must NOT match it.
    df = pd.DataFrame({"dur": [2, 3, 4], "evt": [1, 0, 1]})
    prep = _km_prepare(df, {
        "time_column": "dur", "event_column": "evt", "has_censoring": True,
        # a string "1" entry should be irrelevant to numeric cells
        "event_mapping": [{"value": "1", "value_type": "string", "role": "censored"}],
    })
    # numeric 1s auto-map to event, unaffected by the string "1" entry
    assert prep["counts"]["events"] == 2
    assert prep["counts"]["censored"] == 1
