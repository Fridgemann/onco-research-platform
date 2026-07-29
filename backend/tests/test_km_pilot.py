"""
Milestone 3 — pilot-grade KM behavioral tests: at-risk table, median
"not reached", tied times, all-censored group, single vs multiple groups,
reproducibility metadata, and JSON-safety of the full result.
"""
import json

import lifelines
import pandas as pd
import pytest

from app.tasks.analysis import _run_kaplan_meier
from tests.conftest import km_overall, km_curve, km_labels


def _km(df, **params):
    base = {"time_column": "dur", "event_column": "evt", "has_censoring": True}
    base.update(params)
    return _run_kaplan_meier(df, base)


def test_at_risk_table_matches_hand_derived_counts():
    # durations 2,3,4(cens),5,7,9(cens); events 1,1,0,1,1,0
    df = pd.DataFrame({"dur": [2, 3, 4, 5, 7, 9], "evt": [1, 1, 0, 1, 1, 0]})
    rt = km_overall(_km(df))["risk_table"]
    assert rt["time"] == [0.0, 2.0, 3.0, 4.0, 5.0, 7.0, 9.0]
    # at risk immediately before each time
    assert rt["at_risk"] == [6, 6, 5, 4, 3, 2, 1]
    assert rt["events"] == [0, 1, 1, 0, 1, 1, 0]
    assert rt["censored"] == [0, 0, 0, 1, 0, 0, 1]


def test_median_not_reached_is_null():
    # All censored -> survival never drops to 0.5 -> median "not reached".
    df = pd.DataFrame({"dur": [5, 8, 10], "evt": [0, 0, 0]})
    result = _km(df)
    assert km_overall(result)["median_survival"] is None
    # and the whole result is still valid JSON (no Infinity / NaN).
    json.dumps(result)


def test_all_censored_group_produces_no_events():
    df = pd.DataFrame({"dur": [5, 8, 10], "evt": [0, 0, 0]})
    o = km_overall(_km(df))
    assert o["n_events"] == 0
    assert o["n_censored"] == 3


def test_tied_event_times_handled():
    # ties at t=2 and t=3
    df = pd.DataFrame({"dur": [2, 2, 3, 3, 5], "evt": [1, 1, 1, 0, 1]})
    o = km_overall(_km(df))
    # timeline collapses tied times to single points
    assert o["timeline"] == [0.0, 2.0, 3.0, 5.0]
    # at t=2, two events out of 5 at risk -> S = 3/5 = 0.6
    i2 = o["timeline"].index(2.0)
    assert o["survival_probability"][i2] == pytest.approx(0.6)
    # risk table records 2 events at t=2
    rt = o["risk_table"]
    assert rt["events"][rt["time"].index(2.0)] == 2


def test_single_group_has_no_comparison():
    df = pd.DataFrame({"dur": [2, 3, 4, 5], "evt": [1, 1, 0, 1]})
    result = _km(df)
    assert [g["label"] for g in result["groups"]] == ["overall"]
    assert result["comparison"] is None


def test_multiple_groups_have_logrank_comparison():
    df = pd.DataFrame({
        "dur": [2, 3, 5, 4, 7, 9],
        "evt": [1, 1, 1, 0, 1, 0],
        "grp": ["A", "A", "A", "B", "B", "B"],
    })
    result = _km(df, group_column="grp")
    assert km_labels(result) == {("A", "string"), ("B", "string")}
    assert result["comparison"]["test"] == "logrank"
    assert result["comparison"]["degrees_of_freedom"] == 1
    # each group carries its own curve, CI, counts, and risk table
    for g in ("A", "B"):
        payload = km_curve(result, g)
        assert len(payload["ci_lower"]) == len(payload["timeline"])
        assert "risk_table" in payload
        assert payload["n"] == payload["n_events"] + payload["n_censored"]


def test_reproducibility_block_is_complete_and_dynamic():
    df = pd.DataFrame({"dur": [2, 3, 4, 5], "evt": [1, 1, 0, 1]})
    repro = _km(df)["reproducibility"]
    assert repro["library"] == "lifelines"
    assert repro["library_version"] == lifelines.__version__  # dynamic, not hardcoded
    assert repro["ci_method"] == "exponential_greenwood_log_log"
    assert repro["ci_level"] == 0.95
    assert repro["at_risk_convention"] == "immediately_before"
    assert repro["parameters"]["time_column"] == "dur"


def test_assumptions_present_and_mention_censoring_and_non_causal():
    df = pd.DataFrame({"dur": [2, 3, 4, 5], "evt": [1, 1, 0, 1]})
    text = " ".join(_km(df)["assumptions"]).lower()
    assert "censor" in text
    assert "causal" in text


def test_counts_block_present_in_result():
    df = pd.DataFrame({"dur": [2, 3, 4, 5], "evt": [1, 1, 0, 1]})
    counts = _km(df)["counts"]
    assert counts["total_rows"] == counts["used_rows"] + counts["excluded_rows"]
    assert counts["used_rows"] == counts["events"] + counts["censored"]


# ── Collision-safe groups list (Milestone 3 corrections) ────────────────────

def test_reserved_group_labels_do_not_collide_with_metadata():
    # Group labels that match reserved result keys must not overwrite metadata.
    df = pd.DataFrame({
        "dur": [2, 3, 5, 4, 7, 9],
        "evt": [1, 1, 1, 0, 1, 0],
        "grp": ["counts", "counts", "comparison", "comparison", "processing", "processing"],
    })
    result = _km(df, group_column="grp")
    # metadata keys remain their proper types, not curve dicts
    assert isinstance(result["counts"], dict) and "used_rows" in result["counts"]
    assert isinstance(result["comparison"], dict) and "available" in result["comparison"]
    assert isinstance(result["processing"], dict)
    assert km_labels(result) == {("counts", "string"), ("comparison", "string"), ("processing", "string")}


def test_numeric_and_string_group_labels_do_not_collide():
    # A numeric 1 and a string "1" are distinct groups, not merged.
    df = pd.DataFrame({
        "dur": [2, 3, 5, 4, 7, 9],
        "evt": [1, 1, 1, 0, 1, 0],
        "grp": [1, 1, 1, "1", "1", "1"],
    })
    result = _km(df, group_column="grp")
    # collision-safe: distinct typed labels, not merged into one "1"
    assert km_labels(result) == {(1.0, "number"), ("1", "string")}
    assert len(result["groups"]) == 2
    # a mixed-type group array the log-rank library can't handle degrades
    # gracefully rather than crashing the run
    assert result["comparison"]["available"] in (True, False)


def test_full_result_is_strict_json_safe():
    # No NaN / Infinity anywhere (allow_nan=False would raise otherwise).
    df = pd.DataFrame({
        "dur": [2, 3, 5, 4, 7, 9],
        "evt": [1, 1, 1, 0, 1, 0],
        "grp": ["A", "A", "A", "B", "B", "B"],
    })
    result = _km(df, group_column="grp")
    json.dumps(result, allow_nan=False)


def test_logrank_unavailable_when_no_observed_events():
    # Two groups but zero events overall -> no spurious chi-square=0 / p=1.
    df = pd.DataFrame({
        "dur": [2, 3, 4, 5],
        "evt": [0, 0, 0, 0],
        "grp": ["A", "A", "B", "B"],
    })
    result = _km(df, group_column="grp")
    assert result["comparison"] == {"available": False, "reason": "no_observed_events"}


def test_censor_marks_returned_with_coordinates():
    df = pd.DataFrame({"dur": [2, 3, 4, 5, 7, 9], "evt": [1, 1, 0, 1, 1, 0]})
    marks = km_overall(_km(df))["censor_marks"]
    times = [m["time"] for m in marks]
    assert times == [4.0, 9.0]  # the two censored times
    for m in marks:
        assert 0.0 <= m["survival_probability"] <= 1.0
        assert m["count"] == 1
