"""
Milestone 1 — externally sourced golden fixture: linear regression.

Source (primary citation):
    Anscombe, F. J. (1973). "Graphs in Statistical Analysis." American
    Statistician, 27(1), 17-21.

Dataset I of Anscombe's quartet — four datasets constructed to share
(almost) identical summary statistics and the same least-squares
regression line, despite very different underlying distributions. Data
values transcribed from the Wikipedia "Anscombe's quartet" article
(accessed 2026-07), which reproduces Anscombe's original Dataset I table
and states the shared regression line as y = 3.00 + 0.500x, R^2 = 0.67
(values there are rounded to 2-3 significant figures).

Golden constants below are computed offline via the closed-form OLS
formulas (not scipy, not statsmodels, not this repo's _run_regression) —
sum-of-products / sum-of-squares — and frozen here as literal constants,
not derived at test runtime. They agree with the rounded published summary
(0.500091 rounds to 0.500; 3.000091 rounds to 3.00; 0.6665 rounds to 0.67).
"""
import pandas as pd
import pytest

from app.tasks.analysis import _run_regression

X = [10.0, 8.0, 13.0, 9.0, 11.0, 14.0, 6.0, 4.0, 12.0, 7.0, 5.0]
Y = [8.04, 6.95, 7.58, 8.81, 8.33, 9.96, 7.24, 4.26, 10.84, 4.82, 5.68]

DF = pd.DataFrame({"x": X, "y": Y})

# Frozen golden constants (computed offline via closed-form OLS, not test-derived):
GOLDEN_SLOPE = 0.5000909090909091
GOLDEN_INTERCEPT = 3.0000909090909085
GOLDEN_R_SQUARED = 0.666542459508775

TOLERANCE = 1e-9

RESULT = _run_regression(DF, {"target_column": "y", "feature_columns": ["x"]})


def test_slope_matches_anscombe_dataset_i():
    assert RESULT["slope"] == pytest.approx(GOLDEN_SLOPE, abs=TOLERANCE)


def test_intercept_matches_anscombe_dataset_i():
    assert RESULT["intercept"] == pytest.approx(GOLDEN_INTERCEPT, abs=TOLERANCE)


def test_r_squared_matches_anscombe_dataset_i():
    assert RESULT["r_squared"] == pytest.approx(GOLDEN_R_SQUARED, abs=TOLERANCE)


def test_rounded_values_match_published_summary():
    # Independent low-precision check against the rounded values as stated
    # in the published/secondary source directly (y = 3.00 + 0.500x, R^2 = 0.67).
    assert round(RESULT["slope"], 3) == 0.500
    assert round(RESULT["intercept"], 2) == 3.00
    assert round(RESULT["r_squared"], 2) == 0.67


def test_meta_reports_no_dropped_rows():
    assert RESULT["_meta"] == {"total_rows": 11, "used_rows": 11, "dropped_rows": 0}
