"""
Milestone 1 — independent baseline validation: logistic regression.

This is the hardest of the four fixtures because logistic regression's MLE
has no closed form (unlike linear regression's OLS) and — critically —
_run_logistic_regression's production code uses sklearn.LogisticRegression
with its DEFAULT L2 regularization (C=1.0), not an unregularized fit. An
independent reference computed without that same regularization would not
match, and that mismatch would not indicate a bug: it would just mean the
two models are solving different optimization problems. That gap is real
and large — checked empirically on this exact fixture, an UNREGULARIZED
Newton-Raphson MLE gives coefficient (-7.159, 1.302) while sklearn's
regularized default gives (-4.983, 0.906), a ~30% difference. A tolerance
loose enough to paper over that would validate nothing.

So the independent reference implemented here is a hand-written Newton-
Raphson (iteratively reweighted least squares) solver for L2-PENALIZED
logistic regression, matching sklearn's exact regularization convention
(penalty on coefficients only, not the intercept, strength 1/C). This is
a genuinely separate implementation from sklearn's solver (no sklearn
calls in computing the expected values), and — because it optimizes the
same penalized objective sklearn does — it converges to the same point
sklearn's default solver should, unlike an unregularized reference would.

Formulas:
  Newton-Raphson update for penalized logistic regression:
    p_i     = sigmoid(X_i . beta)
    W       = diag(p_i * (1 - p_i))
    gradient = X^T (y - p) - [0, beta_coef / C]   (no penalty on intercept)
    hessian  = -X^T W X - [[0, 0], [0, 1/C]]
    beta_new = beta - hessian^-1 . gradient
  Iterated to convergence (step size < 1e-12).

Accuracy and AUC are validated separately and more simply: given the
model's own fitted probabilities, accuracy is (predicted == actual).mean()
at a 0.5 threshold, and AUC is the Mann-Whitney U statistic (fraction of
all (positive, negative) score pairs correctly ordered) — both computed
by hand here, independent of sklearn.metrics.

Tolerance: coefficients use 0.01 absolute — looser than the other three
fixtures' 1e-9, because sklearn's default 'lbfgs' solver converges to its
own tol=1e-4 stopping criterion rather than machine precision, so a small
residual gap (~0.002-0.003 observed) versus a fully-converged Newton-
Raphson solve is expected, not a bug. Accuracy/AUC use 1e-9 since they're
computed directly from the model's own output, not a separate optimizer.
"""
import numpy as np
import pandas as pd
import pytest

from app.tasks.analysis import _run_logistic_regression

COEF_TOLERANCE = 0.01
METRIC_TOLERANCE = 1e-9

# ── Fixture: small, non-perfectly-separable binary classification dataset ──
#
# x = 1..10, y has overlap at x=5/6 (y=1 then y=0) so the classes are NOT
# perfectly separable — avoiding the perfect-separation convergence failure
# that unregularized logistic MLE is prone to (flagged during pilot planning).
DF = pd.DataFrame({
    "x": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    "y": [0, 0, 0, 0, 1, 0, 1, 1, 1, 1],
})


def _l2_penalized_newton_raphson_mle(x: np.ndarray, y: np.ndarray, C: float = 1.0) -> np.ndarray:
    """Independent reference solver — not sklearn, not statsmodels."""
    X = np.column_stack([np.ones(len(x)), x])
    beta = np.zeros(2)
    for _ in range(200):
        p = 1 / (1 + np.exp(-(X @ beta)))
        W = np.diag(p * (1 - p))
        gradient = X.T @ (y - p) - np.array([0.0, beta[1] / C])
        hessian = -X.T @ W @ X - np.array([[0.0, 0.0], [0.0, 1.0 / C]])
        step = np.linalg.solve(hessian, gradient)
        beta = beta - step
        if np.max(np.abs(step)) < 1e-12:
            break
    return beta


def test_logistic_coefficients_match_independent_l2_penalized_mle_solver():
    result = _run_logistic_regression(DF, {"target_column": "y", "feature_columns": ["x"]})

    x = DF["x"].to_numpy(dtype=float)
    y = DF["y"].to_numpy(dtype=float)
    expected_intercept, expected_coef = _l2_penalized_newton_raphson_mle(x, y, C=1.0)

    assert result["type"] == "logistic"
    assert result["intercept"] == pytest.approx(expected_intercept, abs=COEF_TOLERANCE)
    assert result["coefficients"]["x"] == pytest.approx(expected_coef, abs=COEF_TOLERANCE)


def test_logistic_accuracy_and_auc_match_hand_computed_metrics():
    result = _run_logistic_regression(DF, {"target_column": "y", "feature_columns": ["x"]})

    x = DF["x"].to_numpy(dtype=float)
    y = DF["y"].to_numpy(dtype=int)
    intercept = result["intercept"]
    coef = result["coefficients"]["x"]

    # Predictions from the model's OWN fitted coefficients — this checks
    # accuracy_score/roc_auc_score's arithmetic, not the optimizer.
    p = 1 / (1 + np.exp(-(intercept + coef * x)))
    predicted = (p >= 0.5).astype(int)

    expected_accuracy = float((predicted == y).mean())

    pos_scores = p[y == 1]
    neg_scores = p[y == 0]
    concordant = sum(
        1.0 if ps > ns else (0.5 if ps == ns else 0.0)
        for ps in pos_scores for ns in neg_scores
    )
    expected_auc = concordant / (len(pos_scores) * len(neg_scores))

    assert result["accuracy"] == pytest.approx(expected_accuracy, abs=METRIC_TOLERANCE)
    assert result["auc"] == pytest.approx(expected_auc, abs=METRIC_TOLERANCE)


def test_logistic_regression_meta_reports_no_dropped_rows():
    result = _run_logistic_regression(DF, {"target_column": "y", "feature_columns": ["x"]})
    assert result["_meta"] == {"total_rows": 10, "used_rows": 10, "dropped_rows": 0}


def test_reference_solver_matches_sklearn_unregularized_as_a_sanity_check():
    # Confirms the hand-written Newton-Raphson solver itself is correct by
    # checking it against sklearn's own unregularized mode (a very large C
    # approximates no penalty) — a solver sanity check, not the production
    # code path (which always uses the regularized default).
    from sklearn.linear_model import LogisticRegression

    x = DF["x"].to_numpy(dtype=float)
    y = DF["y"].to_numpy(dtype=float)

    unregularized = _l2_penalized_newton_raphson_mle(x, y, C=1e8)
    sk_unregularized = LogisticRegression(max_iter=1000, penalty=None)
    sk_unregularized.fit(x.reshape(-1, 1), y)

    assert unregularized[0] == pytest.approx(sk_unregularized.intercept_[0], abs=0.01)
    assert unregularized[1] == pytest.approx(sk_unregularized.coef_[0][0], abs=0.01)
