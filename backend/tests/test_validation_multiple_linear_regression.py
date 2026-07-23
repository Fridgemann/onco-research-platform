"""
Milestone 1 — independent validation of the multiple-linear-regression path.

_run_regression has two code paths: a single-feature path using
scipy.stats.linregress (already validated in test_validation_linear_regression.py
and test_golden_linear_regression.py), and a SEPARATE multi-feature path
using np.linalg.lstsq, which neither of those fixtures exercises. This
fixture covers that second path.

Independent reference: the normal-equations solution
    beta = (X^T X)^-1 X^T y
computed offline via two methods distinct from np.linalg.lstsq — plain
Gaussian solve (np.linalg.solve on the normal equations) and Cramer's rule
(explicit determinant ratios) — which agreed with each other and with
lstsq to float precision when checked. Expected values below are frozen
literal constants from that offline computation, not derived at test
runtime and not copied from _run_regression's own output.

Data: x1 = [1,2,3,4,5,6], x2 = [1,1,2,2,3,3], y = [8,10,15,17,22,25].
y is NOT an exact linear combination of x1/x2 (deliberately, so the fit
has genuine residual error and R^2 != 1.0, actually exercising least
squares rather than an exact/consistent linear system).
"""
import pandas as pd
import pytest

from app.tasks.analysis import _run_regression

X1 = [1, 2, 3, 4, 5, 6]
X2 = [1, 1, 2, 2, 3, 3]
Y = [8, 10, 15, 17, 22, 25]

DF = pd.DataFrame({"x1": X1, "x2": X2, "y": Y})

# Frozen golden constants (computed offline via normal-equations solve and
# cross-checked via Cramer's rule; not derived at test runtime):
GOLDEN_INTERCEPT = 2.8333333333333317
GOLDEN_COEF_X1 = 2.3333333333333344
GOLDEN_COEF_X2 = 2.5833333333333326
GOLDEN_R_SQUARED = 0.9980959634424981

TOLERANCE = 1e-9

RESULT = _run_regression(DF, {"target_column": "y", "feature_columns": ["x1", "x2"]})


def test_uses_multiple_linear_path_not_single_feature_path():
    assert RESULT["type"] == "multiple_linear"


def test_intercept_matches_normal_equations_reference():
    assert RESULT["intercept"] == pytest.approx(GOLDEN_INTERCEPT, abs=TOLERANCE)


def test_coefficients_match_normal_equations_reference():
    assert RESULT["coefficients"]["x1"] == pytest.approx(GOLDEN_COEF_X1, abs=TOLERANCE)
    assert RESULT["coefficients"]["x2"] == pytest.approx(GOLDEN_COEF_X2, abs=TOLERANCE)


def test_r_squared_matches_normal_equations_reference():
    assert RESULT["r_squared"] == pytest.approx(GOLDEN_R_SQUARED, abs=TOLERANCE)
    # Sanity check on the fixture itself: confirm it's a genuine imperfect
    # fit, not an exact linear system (which would trivially satisfy any
    # correct solver and not exercise least-squares behavior).
    assert RESULT["r_squared"] < 1.0


def test_meta_reports_no_dropped_rows():
    assert RESULT["_meta"] == {"total_rows": 6, "used_rows": 6, "dropped_rows": 0}
