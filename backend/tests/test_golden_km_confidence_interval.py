"""
Milestone 3 — golden fixture: KM pointwise confidence intervals.

Validates the pilot-grade 95% CI (exponential Greenwood formula with a
log-log transformation — lifelines' default) two ways that are independent
of lifelines:

  1. An inline hand computation of the exponential-Greenwood log-log bounds
     from the defining formula, on a tiny hand-checkable dataset.
  2. Frozen literal constants (offline-computed) for the same points.

Formula (exponential Greenwood, log-log transform), at an event time t with
survival estimate S(t):
    v            = ln S(t)
    cumulative_sq(t) = sum over event times t_i <= t of d_i / (n_i (n_i - d_i))
    c            = z * sqrt(cumulative_sq(t)) / v          (z = 1.959964 for 95%)
    lower, upper = exp(-exp(ln(-v) +/- c))
The +/- assignment to lower/upper flips because v < 0; the two produced
values are asserted as a set-independent {lower, upper} pair.

Dataset: durations [2, 3, 4, 5, 7, 9], events [1, 1, 0, 1, 1, 0]
(the row at t=4 and t=9 are censored). Survival: 5/6, 4/6, 4/6, 4/9, 2/9, 2/9.
"""
import math

import pandas as pd
import pytest

from app.tasks.analysis import _run_kaplan_meier

Z_95 = 1.959963984540054
TOL = 1e-6

DF = pd.DataFrame({"dur": [2, 3, 4, 5, 7, 9], "evt": [1, 1, 0, 1, 1, 0]})
RESULT = _run_kaplan_meier(DF, {"time_column": "dur", "event_column": "evt", "has_censoring": True})
OVERALL = RESULT["overall"]

# Frozen golden constants (offline-computed exponential-Greenwood log-log):
GOLDEN_CI_AT_T2 = (0.273123, 0.974712)
GOLDEN_CI_AT_T3 = (0.194617, 0.904434)


def _hand_loglog_ci(surv: float, cumulative_sq: float) -> tuple[float, float]:
    v = math.log(surv)
    a = math.exp(-math.exp(math.log(-v) + Z_95 * math.sqrt(cumulative_sq) / v))
    b = math.exp(-math.exp(math.log(-v) - Z_95 * math.sqrt(cumulative_sq) / v))
    return (min(a, b), max(a, b))


def _ci_at(time: float) -> tuple[float, float]:
    i = OVERALL["timeline"].index(time)
    lo, hi = OVERALL["ci_lower"][i], OVERALL["ci_upper"][i]
    return (min(lo, hi), max(lo, hi))


def test_ci_arrays_align_with_timeline():
    n = len(OVERALL["timeline"])
    assert len(OVERALL["ci_lower"]) == n
    assert len(OVERALL["ci_upper"]) == n


def test_ci_at_t2_matches_hand_derived_exponential_greenwood():
    # cumulative_sq at t=2: d/(n(n-d)) = 1/(6*5)
    expected = _hand_loglog_ci(5 / 6, 1 / (6 * 5))
    got = _ci_at(2.0)
    assert got[0] == pytest.approx(expected[0], abs=TOL)
    assert got[1] == pytest.approx(expected[1], abs=TOL)


def test_ci_at_t3_matches_hand_derived_exponential_greenwood():
    # cumulative_sq at t=3: 1/(6*5) + 1/(5*4)
    cumsq = 1 / (6 * 5) + 1 / (5 * 4)
    expected = _hand_loglog_ci(4 / 6, cumsq)
    got = _ci_at(3.0)
    assert got[0] == pytest.approx(expected[0], abs=TOL)
    assert got[1] == pytest.approx(expected[1], abs=TOL)


def test_ci_matches_frozen_golden_constants():
    assert _ci_at(2.0) == pytest.approx(GOLDEN_CI_AT_T2, abs=TOL)
    assert _ci_at(3.0) == pytest.approx(GOLDEN_CI_AT_T3, abs=TOL)


def test_ci_reported_method_and_level():
    repro = RESULT["reproducibility"]
    assert repro["ci_method"] == "exponential_greenwood_log_log"
    assert repro["ci_level"] == 0.95
