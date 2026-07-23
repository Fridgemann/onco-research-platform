"""
Milestone 1 — independent baseline validation: linear regression.

Rather than reciting a remembered textbook dataset's published coefficients
(the same transcription-error risk flagged in the KM validation file), this
uses a small hand-constructed dataset with clean values, and derives the
expected slope/intercept/r_squared/std_err from the closed-form ordinary
least squares formulas directly — no linregress, no statsmodels, no sklearn
involved in computing the expected values.

Formulas (simple linear regression, y = intercept + slope * x):
    mean_x, mean_y = arithmetic means
    Sxy = sum((x_i - mean_x) * (y_i - mean_y))
    Sxx = sum((x_i - mean_x) ** 2)
    Syy = sum((y_i - mean_y) ** 2)
    slope     = Sxy / Sxx
    intercept = mean_y - slope * mean_x
    r_squared = Sxy**2 / (Sxx * Syy)
    SSE       = Syy - slope * Sxy                  (residual sum of squares)
    std_err   = sqrt( (SSE / (n - 2)) / Sxx )       (standard error of slope)
    t_stat    = slope / std_err
    p_value   = 2 * P(T > |t_stat|), T ~ Student's t with (n - 2) df

p_value's expected value uses scipy.stats.t.sf purely as a distribution
lookup (equivalent to reading a t-table in a textbook appendix) applied to
an independently hand-derived t-statistic — it does not call linregress or
any other regression routine, so it does not validate the analysis code
against itself.

Tolerance: 1e-9 absolute — same reasoning as the descriptive stats fixture
(same double-precision arithmetic, independent implementation path).
"""
import math

import pandas as pd
import pytest
from scipy.stats import t as t_dist

from app.tasks.analysis import _run_regression

TOLERANCE = 1e-9

# ── Fixture: small hand-constructed dataset ─────────────────────────────────
#
# x = [1, 2, 3, 4, 5], y = [2, 4, 5, 4, 5]
#
# mean_x = 3, mean_y = 4
# Sxy = (1-3)(2-4) + (2-3)(4-4) + (3-3)(5-4) + (4-3)(4-4) + (5-3)(5-4)
#     = 4 + 0 + 0 + 0 + 2 = 6
# Sxx = 4 + 1 + 0 + 1 + 4 = 10
# Syy = 4 + 0 + 1 + 0 + 1 = 6
#
# slope     = 6 / 10 = 0.6
# intercept = 4 - 0.6*3 = 2.2
# r_squared = 6^2 / (10*6) = 36/60 = 0.6
# SSE       = 6 - 0.6*6 = 2.4
# std_err   = sqrt((2.4/3) / 10) = sqrt(0.08) = 0.2828427124746...
# t_stat    = 0.6 / 0.2828427124746 = 2.1213203435596...
DF = pd.DataFrame({"x": [1, 2, 3, 4, 5], "y": [2, 4, 5, 4, 5]})

EXPECTED_SLOPE = 0.6
EXPECTED_INTERCEPT = 2.2
EXPECTED_R_SQUARED = 0.6
EXPECTED_STD_ERR = math.sqrt((2.4 / 3) / 10)
EXPECTED_T_STAT = EXPECTED_SLOPE / EXPECTED_STD_ERR
EXPECTED_P_VALUE = 2 * t_dist.sf(abs(EXPECTED_T_STAT), df=3)


def test_linear_regression_matches_hand_derived_ols_formulas():
    result = _run_regression(DF, {"target_column": "y", "feature_columns": ["x"]})

    assert result["type"] == "linear"
    assert result["slope"] == pytest.approx(EXPECTED_SLOPE, abs=TOLERANCE)
    assert result["intercept"] == pytest.approx(EXPECTED_INTERCEPT, abs=TOLERANCE)
    assert result["r_squared"] == pytest.approx(EXPECTED_R_SQUARED, abs=TOLERANCE)
    assert result["std_err"] == pytest.approx(EXPECTED_STD_ERR, abs=TOLERANCE)
    assert result["p_value"] == pytest.approx(EXPECTED_P_VALUE, abs=TOLERANCE)
    assert result["n"] == 5


def test_linear_regression_meta_reports_no_dropped_rows():
    result = _run_regression(DF, {"target_column": "y", "feature_columns": ["x"]})
    assert result["_meta"] == {"total_rows": 5, "used_rows": 5, "dropped_rows": 0}


def test_reference_t_statistic_derivation_is_actually_independent():
    # Sanity check on the validation methodology: confirm the hand-derived
    # SSE/std_err/t_stat chain via the textbook formula directly, rather
    # than trusting the module-level constants above at face value.
    x = [1, 2, 3, 4, 5]
    y = [2, 4, 5, 4, 5]
    n = len(x)
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    sxy = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    sxx = sum((xi - mean_x) ** 2 for xi in x)
    syy = sum((yi - mean_y) ** 2 for yi in y)

    slope = sxy / sxx
    sse = syy - slope * sxy
    std_err = math.sqrt((sse / (n - 2)) / sxx)

    assert slope == pytest.approx(EXPECTED_SLOPE, abs=TOLERANCE)
    assert std_err == pytest.approx(EXPECTED_STD_ERR, abs=TOLERANCE)
