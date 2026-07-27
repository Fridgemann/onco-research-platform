"""
Milestone 1 — externally sourced golden fixture: logistic regression.

Secondary reference:
    Wikipedia, "Logistic regression" article, "Example" section (hours
    studied vs. exam pass/fail). https://en.wikipedia.org/wiki/Logistic_regression
    Accessed 2026-07-20. The article's worked example fits an unregularized
    maximum-likelihood logistic regression to 20 students' study hours and
    pass/fail outcomes, reporting intercept (beta_0) approximately -4.1 and
    slope (beta_1) approximately 1.5 (values stated in the article to 1
    decimal place).

IMPORTANT METHODOLOGY NOTE: the production code (_run_logistic_regression)
fits sklearn.LogisticRegression with its DEFAULT L2 regularization
(C=1.0), not an unregularized MLE. Verified offline on this exact dataset:
an unregularized fit reproduces the cited Wikipedia values closely
(-4.078 vs -4.1, 1.505 vs 1.5), but sklearn's regularized default gives
substantially different coefficients (-3.14, 1.15) — a real ~23%
difference, not a rounding discrepancy. So this file makes two separate,
clearly-labeled comparisons instead of one, and they validate different
things against different references:

  1. An "unregularized MLE" constant, computed offline with the same
     hand-written L2-penalized Newton-Raphson solver used in
     test_validation_logistic_regression.py (with the penalty strength
     set negligibly small, C=1e8, so it approximates no penalty at all).
     This is compared against the published -4.1 / 1.5 citation, and is
     what validates that this fixture's transcribed data and methodology
     genuinely reproduce an externally published result.

  2. A "production" constant, computed offline with that same solver but
     using C=1.0 (sklearn's actual default), compared against
     _run_logistic_regression's real output. This validates the actual
     production code path — but NOT against externally published
     production-equivalent coefficients, because no such citation exists
     (the cited source is unregularized; production is regularized).
     Its reference is the independent hand-written penalized solver only,
     same as the internal (non-golden) fixture already covers — the
     external citation here lends confidence to the data and the
     unregularized half of the methodology, not to the regularized
     coefficients themselves.

Data transcribed from the article's table (hours studied, pass=1/fail=0):
"""
import pandas as pd
import pytest

from app.tasks.analysis import _run_logistic_regression

HOURS = [0.50, 0.75, 1.00, 1.25, 1.50, 1.75, 1.75, 2.00, 2.25, 2.50,
         2.75, 3.00, 3.25, 3.50, 4.00, 4.25, 4.50, 4.75, 5.00, 5.50]
PASSED = [0, 0, 0, 0, 0, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 1, 1, 1, 1, 1]

DF = pd.DataFrame({"hours": HOURS, "pass": PASSED})

# Published citation (Wikipedia, rounded to 1 decimal place):
PUBLISHED_INTERCEPT = -4.1
PUBLISHED_COEF = 1.5
PUBLISHED_TOLERANCE = 0.05  # accounts for the citation's 1-decimal rounding

# Frozen golden constants, computed offline (not derived at test runtime):
#
# Unregularized MLE (Newton-Raphson, C=1e8 ~ no penalty) — confirms this
# transcription reproduces the citation.
OFFLINE_UNREGULARIZED_INTERCEPT = -4.07771342
OFFLINE_UNREGULARIZED_COEF = 1.50464542

# L2-penalized MLE at sklearn's actual default (C=1.0) — the real
# production-matching reference.
OFFLINE_PRODUCTION_INTERCEPT = -3.13952493
OFFLINE_PRODUCTION_COEF = 1.1486039
PRODUCTION_TOLERANCE = 0.01  # same rationale as test_validation_logistic_regression.py:
                             # sklearn's default solver converges to its own
                             # tol=1e-4, not machine precision, vs. a fully
                             # converged Newton-Raphson solve.

# Classification metrics, computed offline from the production model's own
# fitted probabilities (accuracy_score/roc_auc_score arithmetic, not the
# optimizer) at a 0.5 threshold:
OFFLINE_ACCURACY = 0.8
OFFLINE_AUC = 0.895

RESULT = _run_logistic_regression(DF, {"target_column": "pass", "feature_columns": ["hours"]})


def test_offline_unregularized_fit_reproduces_published_citation():
    assert OFFLINE_UNREGULARIZED_INTERCEPT == pytest.approx(PUBLISHED_INTERCEPT, abs=PUBLISHED_TOLERANCE)
    assert OFFLINE_UNREGULARIZED_COEF == pytest.approx(PUBLISHED_COEF, abs=PUBLISHED_TOLERANCE)


def test_production_coefficients_match_offline_l2_penalized_reference():
    assert RESULT["intercept"] == pytest.approx(OFFLINE_PRODUCTION_INTERCEPT, abs=PRODUCTION_TOLERANCE)
    assert RESULT["coefficients"]["hours"] == pytest.approx(OFFLINE_PRODUCTION_COEF, abs=PRODUCTION_TOLERANCE)


def test_production_accuracy_and_auc_match_offline_computation():
    assert RESULT["accuracy"] == pytest.approx(OFFLINE_ACCURACY, abs=1e-9)
    assert RESULT["auc"] == pytest.approx(OFFLINE_AUC, abs=1e-9)


def test_meta_reports_no_dropped_rows():
    assert RESULT["_meta"] == {"total_rows": 20, "used_rows": 20, "dropped_rows": 0}
