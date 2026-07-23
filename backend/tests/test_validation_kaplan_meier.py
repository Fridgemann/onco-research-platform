"""
Milestone 1 — independent baseline validation: Kaplan-Meier.

IMPORTANT NOTE ON SOURCE: the milestone spec suggested validating against a
published example such as the 6-MP leukemia remission dataset (Freireich et
al. 1963), widely reprinted in survival-analysis textbooks. That dataset was
deliberately NOT used here — reciting its exact per-patient time/censoring
table from memory risks transcription errors, and a validation fixture with
a wrong "ground truth" is worse than no fixture at all. If you have access to
the exact published table (a textbook copy, or the `drug6mp` dataset from
R's KMsurv package), it should be added as a second fixture alongside this
one; this file does not depend on it.

What IS used here: small datasets where the Kaplan-Meier product-limit
estimate is derived by hand from the defining formula, so the "independent
reference" is the formula itself, not lifelines' implementation of it. This
exercises the actual production code path (_run_kaplan_meier: DataFrame
plumbing, event/censoring handling, group splitting, median calculation),
not just lifelines directly.

Formula (Kaplan-Meier product-limit estimator):
    S(t) = product over all event times t_i <= t of (1 - d_i / n_i)
    where n_i = number still at risk just before t_i,
          d_i = number of events (not censorings) at t_i.
Censored observations reduce the risk set for subsequent times but do not
themselves change S(t).

Median survival = smallest t at which S(t) <= 0.5 (lifelines' convention,
matched here for consistency with the production code).

Tolerance: 1e-9 absolute. All expected values here are small exact
fractions (5/6, 2/3, 4/9, 2/9, 1/2, 1/3) computed independently by hand;
any deviation beyond floating-point noise indicates a real discrepancy.
"""
import pandas as pd
import pytest

from app.tasks.analysis import _run_kaplan_meier

TOLERANCE = 1e-9


# ── Fixture 1: single group, hand-derived ───────────────────────────────────
#
# 6 patients. Durations: 2, 3, 4, 5, 7, 9. Event indicator: 1 = event
# (relapse/death), 0 = censored. Patient at t=4 and t=9 are censored.
#
# Hand derivation:
#   t=2: at risk n=6, events d=1 -> S = 1 * (1 - 1/6)         = 5/6      = 0.833333...
#   t=3: at risk n=5, events d=1 -> S = 5/6 * (1 - 1/5)       = 4/6      = 0.666667...
#   t=4: censored, no event -> S unchanged                     = 2/3      = 0.666667...
#   t=5: at risk n=3, events d=1 -> S = 2/3 * (1 - 1/3)       = 4/9      = 0.444444...
#   t=7: at risk n=2, events d=1 -> S = 4/9 * (1 - 1/2)       = 2/9      = 0.222222...
#   t=9: censored, no event -> S unchanged                      = 2/9      = 0.222222...
# Median: smallest t with S(t) <= 0.5 -> t=5 (S(3)=0.667 > 0.5, S(5)=0.444 <= 0.5)
DF_OVERALL = pd.DataFrame({
    "duration": [2, 3, 4, 5, 7, 9],
    "event": [1, 1, 0, 1, 1, 0],
})

EXPECTED_OVERALL_TIMELINE = [0.0, 2.0, 3.0, 4.0, 5.0, 7.0, 9.0]
EXPECTED_OVERALL_SURVIVAL = [1.0, 5 / 6, 4 / 6, 4 / 6, 4 / 9, 2 / 9, 2 / 9]
EXPECTED_OVERALL_MEDIAN = 5.0


def test_overall_km_curve_matches_hand_derived_product_limit_formula():
    result = _run_kaplan_meier(DF_OVERALL, {"time_column": "duration", "event_column": "event"})
    overall = result["overall"]

    assert overall["timeline"] == pytest.approx(EXPECTED_OVERALL_TIMELINE, abs=TOLERANCE)
    assert overall["survival_probability"] == pytest.approx(EXPECTED_OVERALL_SURVIVAL, abs=TOLERANCE)
    assert overall["median_survival"] == pytest.approx(EXPECTED_OVERALL_MEDIAN, abs=TOLERANCE)


def test_overall_km_meta_reports_no_dropped_rows():
    result = _run_kaplan_meier(DF_OVERALL, {"time_column": "duration", "event_column": "event"})
    assert result["_meta"] == {"total_rows": 6, "used_rows": 6, "dropped_rows": 0}


# ── Fixture 2: two groups, hand-derived ─────────────────────────────────────
#
# Group A (all events, no censoring): durations 2, 3, 5, all events.
#   t=2: n=3, d=1 -> S = 2/3 = 0.666667
#   t=3: n=2, d=1 -> S = 2/3 * 1/2 = 1/3 = 0.333333
#   t=5: n=1, d=1 -> S = 1/3 * 0 = 0.0
#   Median: smallest t with S(t) <= 0.5 -> t=3 (S(2)=0.667 > 0.5, S(3)=0.333 <= 0.5)
#
# Group B (one event, two censored): durations 4 (censored), 7 (event), 9 (censored).
#   t=4: censored -> S unchanged = 1.0
#   t=7: n=2, d=1 -> S = 1.0 * 1/2 = 0.5
#   t=9: censored -> S unchanged = 0.5
#   Median: smallest t with S(t) <= 0.5 -> t=7 (S(7)=0.5 <= 0.5)
DF_GROUPED = pd.DataFrame({
    "duration": [2, 3, 5, 4, 7, 9],
    "event": [1, 1, 1, 0, 1, 0],
    "arm": ["A", "A", "A", "B", "B", "B"],
})

EXPECTED_GROUP_A_TIMELINE = [0.0, 2.0, 3.0, 5.0]
EXPECTED_GROUP_A_SURVIVAL = [1.0, 2 / 3, 1 / 3, 0.0]
EXPECTED_GROUP_A_MEDIAN = 3.0

EXPECTED_GROUP_B_TIMELINE = [0.0, 4.0, 7.0, 9.0]
EXPECTED_GROUP_B_SURVIVAL = [1.0, 1.0, 0.5, 0.5]
EXPECTED_GROUP_B_MEDIAN = 7.0


def test_grouped_km_curves_match_hand_derived_product_limit_formula():
    result = _run_kaplan_meier(
        DF_GROUPED,
        {"time_column": "duration", "event_column": "event", "group_column": "arm"},
    )

    group_a = result["A"]
    assert group_a["timeline"] == pytest.approx(EXPECTED_GROUP_A_TIMELINE, abs=TOLERANCE)
    assert group_a["survival_probability"] == pytest.approx(EXPECTED_GROUP_A_SURVIVAL, abs=TOLERANCE)
    assert group_a["median_survival"] == pytest.approx(EXPECTED_GROUP_A_MEDIAN, abs=TOLERANCE)

    group_b = result["B"]
    assert group_b["timeline"] == pytest.approx(EXPECTED_GROUP_B_TIMELINE, abs=TOLERANCE)
    assert group_b["survival_probability"] == pytest.approx(EXPECTED_GROUP_B_SURVIVAL, abs=TOLERANCE)
    assert group_b["median_survival"] == pytest.approx(EXPECTED_GROUP_B_MEDIAN, abs=TOLERANCE)
