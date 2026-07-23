"""
Milestone 1 — externally sourced golden fixture: Kaplan-Meier.

Source (primary citation):
    Freireich EJ, Gehan E, Frei E 3rd, et al. "The effect of 6-mercaptopurine
    on the duration of steroid-induced remissions in acute leukemia: A model
    for evaluation of other potentially useful therapy." Blood. 1963;
    21(6):699-716.

This is the classic 6-MP vs. placebo leukemia remission trial: 21 children
per arm, remission time in weeks, right-censored. It is one of the most
widely reprinted datasets in survival analysis (e.g. R's KMsurv::drug6mp,
bpcp::leuk2) and its Kaplan-Meier curve and median survival times are
published in multiple independent secondary sources that agree with each
other, which is what makes it usable here as a genuine external reference
rather than a single memorized recollection.

Per-patient data transcribed from a secondary reproduction of the dataset
(https://survive-python.readthedocs.io/examples/Leukemia_Remission_Time_Dataset.html,
accessed 2026-07; data matches the structure described in Freireich et al.
1963 — 21 control patients all relapsing, 21 treatment patients with 9
events and 12 censored):

  Control (placebo), all 21 relapse (no censoring), weeks:
    1, 1, 2, 2, 3, 4, 4, 5, 5, 8, 8, 8, 8, 11, 11, 12, 12, 15, 17, 22, 23

  Treatment (6-MP), 9 events + 12 censored (marked +), weeks:
    6, 6, 6, 6+, 7, 9+, 10, 10+, 11+, 13, 16, 17+, 19+, 20+, 22, 23,
    25+, 32+, 32+, 34+, 35+

Golden constants below (median survival, and survival probability at 5/10/
15/20 weeks for each arm) are the published values from that same secondary
source, computed offline and frozen here as literal constants — this test
does not derive them from any formula or from _run_kaplan_meier's own
output. Checkpoint tolerance is 0.001 (published values are given to 3
decimal places; observed discrepancy against the production code's exact
fractions was <= 0.0005 in all four checkpoints per arm when this fixture
was verified).
"""
import pandas as pd
import pytest

from app.tasks.analysis import _run_kaplan_meier

CONTROL_TIMES = [1, 1, 2, 2, 3, 4, 4, 5, 5, 8, 8, 8, 8, 11, 11, 12, 12, 15, 17, 22, 23]
CONTROL_EVENTS = [1] * 21  # all relapse, no censoring

# (duration, event) pairs; event=1 relapse, event=0 censored
_TREATMENT_RAW = [
    (6, 1), (6, 1), (6, 1), (6, 0), (7, 1), (9, 0), (10, 1), (10, 0), (11, 0),
    (13, 1), (16, 1), (17, 0), (19, 0), (20, 0), (22, 1), (23, 1),
    (25, 0), (32, 0), (32, 0), (34, 0), (35, 0),
]
TREATMENT_TIMES = [t for t, _ in _TREATMENT_RAW]
TREATMENT_EVENTS = [e for _, e in _TREATMENT_RAW]

DF = pd.DataFrame({
    "duration": CONTROL_TIMES + TREATMENT_TIMES,
    "event": CONTROL_EVENTS + TREATMENT_EVENTS,
    "arm": ["control"] * 21 + ["treatment"] * 21,
})

# Frozen golden constants (offline-computed / published, not test-derived):
GOLDEN_MEDIAN_CONTROL = 8.0
GOLDEN_MEDIAN_TREATMENT = 23.0

# checkpoint week -> survival probability, per arm
GOLDEN_CONTROL_CHECKPOINTS = {5: 0.571, 10: 0.381, 15: 0.143, 20: 0.095}
GOLDEN_TREATMENT_CHECKPOINTS = {5: 1.000, 10: 0.753, 15: 0.690, 20: 0.627}

CHECKPOINT_TOLERANCE = 0.001


def _survival_at(timeline: list, survival: list, week: int) -> float:
    """Step-function lookup: value at the last timeline point <= week."""
    value = survival[0]
    for t, s in zip(timeline, survival):
        if t <= week:
            value = s
        else:
            break
    return value


RESULT = _run_kaplan_meier(
    DF, {"time_column": "duration", "event_column": "event", "group_column": "arm"}
)


def test_control_median_matches_published_value():
    assert RESULT["control"]["median_survival"] == pytest.approx(GOLDEN_MEDIAN_CONTROL, abs=1e-9)


def test_treatment_median_matches_published_value():
    assert RESULT["treatment"]["median_survival"] == pytest.approx(GOLDEN_MEDIAN_TREATMENT, abs=1e-9)


def test_control_checkpoints_match_published_survival_curve():
    timeline = RESULT["control"]["timeline"]
    survival = RESULT["control"]["survival_probability"]
    for week, expected in GOLDEN_CONTROL_CHECKPOINTS.items():
        actual = _survival_at(timeline, survival, week)
        assert actual == pytest.approx(expected, abs=CHECKPOINT_TOLERANCE), f"week {week}"


def test_treatment_checkpoints_match_published_survival_curve():
    timeline = RESULT["treatment"]["timeline"]
    survival = RESULT["treatment"]["survival_probability"]
    for week, expected in GOLDEN_TREATMENT_CHECKPOINTS.items():
        actual = _survival_at(timeline, survival, week)
        assert actual == pytest.approx(expected, abs=CHECKPOINT_TOLERANCE), f"week {week}"


def test_meta_reports_full_cohort_no_missing_rows():
    assert RESULT["_meta"] == {"total_rows": 42, "used_rows": 42, "dropped_rows": 0}
