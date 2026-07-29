"""
Milestone 3 — golden fixture: KM group comparison (log-rank).

Uses the classic Freireich et al. 1963 6-MP vs. placebo leukemia remission
trial (same dataset as test_golden_kaplan_meier.py). The two-sample log-rank
(Mantel-Cox) statistic for this dataset is a widely reproduced result:
chi-square ~= 16.79 on 1 degree of freedom (see e.g. Klein & Moeschberger,
"Survival Analysis", and most survival-analysis texts reproducing Gehan's
analysis of these data).

The frozen chi-square below is offline-computed and matches that published
~16.79 to two decimals; degrees of freedom = (#groups - 1) = 1.
"""
import pandas as pd
import pytest

from app.tasks.analysis import _run_kaplan_meier

CONTROL_TIMES = [1, 1, 2, 2, 3, 4, 4, 5, 5, 8, 8, 8, 8, 11, 11, 12, 12, 15, 17, 22, 23]
CONTROL_EVENTS = [1] * 21
_TREATMENT_RAW = [
    (6, 1), (6, 1), (6, 1), (6, 0), (7, 1), (9, 0), (10, 1), (10, 0), (11, 0),
    (13, 1), (16, 1), (17, 0), (19, 0), (20, 0), (22, 1), (23, 1),
    (25, 0), (32, 0), (32, 0), (34, 0), (35, 0),
]

DF = pd.DataFrame({
    "dur": CONTROL_TIMES + [t for t, _ in _TREATMENT_RAW],
    "evt": CONTROL_EVENTS + [e for _, e in _TREATMENT_RAW],
    "arm": ["control"] * 21 + ["treatment"] * 21,
})

RESULT = _run_kaplan_meier(
    DF, {"time_column": "dur", "event_column": "evt", "group_column": "arm", "has_censoring": True}
)

GOLDEN_LOGRANK_CHI_SQUARE = 16.79  # published ~16.79 (2 dp)
GOLDEN_DOF = 1


def test_logrank_chi_square_matches_published_value():
    comp = RESULT["comparison"]
    assert comp["available"] is True
    assert comp["test"] == "logrank"
    assert comp["chi_square"] == pytest.approx(GOLDEN_LOGRANK_CHI_SQUARE, abs=0.01)


def test_logrank_degrees_of_freedom_is_groups_minus_one():
    assert RESULT["comparison"]["degrees_of_freedom"] == GOLDEN_DOF


def test_logrank_p_value_is_significant():
    # p is far below 0.001 for these data; assert the order of magnitude only.
    assert RESULT["comparison"]["p_value"] < 0.001
