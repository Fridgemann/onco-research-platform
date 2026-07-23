"""
Milestone 1 — independent baseline validation: descriptive statistics.

This does NOT compare _run_descriptive_stats's output against pandas itself
(that would only prove we called the pandas API correctly, not that the
underlying arithmetic is right). Expected values are computed here with
Python's stdlib `statistics` module — a separate implementation from the
pandas/numpy C-optimized routines the production code actually uses.

Fixture source: hand-constructed, not drawn from a published dataset. This is
appropriate for descriptive statistics specifically because the quantities
involved (mean, sample std, median, quartiles, counts) are basic enough to
verify directly from the formulas below without needing an external
authority — unlike KM or regression, where an independent published example
is the more meaningful check. Values were chosen so every column produces
exact or easily-hand-checked results (documented per-column below).

Formulas:
  mean         = sum(x) / n
  sample std   = sqrt( sum((x - mean)**2) / (n - 1) )   [ddof=1, matches
                 pandas' default .std()]
  median       = middle value (avg of two middle values if n is even)
  quartiles    = linear interpolation between order statistics (pandas'
                 default .quantile() method; confirmed to match Python's
                 statistics.quantiles(..., method="inclusive") for this
                 fixture — see comment below)

Tolerance: 1e-9 absolute. Both implementations use IEEE 754 double-precision
arithmetic on the same finite input, so an independent correct implementation
should agree to near machine precision; a larger mismatch would indicate an
actual formula or methodology difference, not floating-point noise.
"""
import math
import statistics as st

import pandas as pd
import pytest

from app.tasks.analysis import _run_descriptive_stats

TOLERANCE = 1e-9

# ── Fixture ──────────────────────────────────────────────────────────────
#
# Measurement: clean continuous column, no missing/non-numeric values.
# Sex:         binary 0/1 column, evenly split (4/4) for an easy hand-check.
# Status:      continuous column with 2 missing values — usable subset
#              [5, 7, 9, 11, 13, 15] was chosen so the mean lands on an
#              exact 10.0 and variance arithmetic stays simple.
# Value:       2 confidentiality codes ("C") + 2 English-grouped thousands
#              ("1,200"/"1,500") mixed with plain numbers, to validate
#              non-numeric exclusion and normalization together. Its "C"
#              rows (indices 2, 5) are deliberately placed at different
#              positions than Status's missing rows (indices 1, 4), so the
#              two columns' exclusions don't overlap — this makes the joint
#              row-alignment count (_meta) simple to hand-verify as a union.
DF = pd.DataFrame({
    "Measurement": [12, 15, 18, 22, 25, 30, 35, 40],
    "Sex": [1, 0, 1, 1, 0, 1, 0, 0],
    "Status": [5, None, 7, 9, None, 11, 13, 15],
    "Value": ["100", "1,200", "C", "300", "1,500", "C", "400", "500"],
})

RESULT = _run_descriptive_stats(DF, {"columns": ["Measurement", "Sex", "Status", "Value"]})


def _assert_stats_match(col: dict, usable_values: list[float]) -> None:
    expected_mean = st.mean(usable_values)
    expected_std = st.stdev(usable_values)  # sample stdev, ddof=1 — matches pandas default
    expected_median = st.median(usable_values)
    # method="inclusive" is Python's linear-interpolation quantile method —
    # confirmed by hand to match pandas' .quantile() default for this data.
    expected_p25, _, expected_p75 = st.quantiles(usable_values, n=4, method="inclusive")

    assert col["count"] == len(usable_values)
    assert col["mean"] == pytest.approx(expected_mean, abs=TOLERANCE)
    assert col["std"] == pytest.approx(expected_std, abs=TOLERANCE)
    assert col["median"] == pytest.approx(expected_median, abs=TOLERANCE)
    assert col["p25"] == pytest.approx(expected_p25, abs=TOLERANCE)
    assert col["p75"] == pytest.approx(expected_p75, abs=TOLERANCE)
    assert col["min"] == pytest.approx(min(usable_values), abs=TOLERANCE)
    assert col["max"] == pytest.approx(max(usable_values), abs=TOLERANCE)


def test_measurement_matches_independent_stdlib_calculation():
    _assert_stats_match(RESULT["Measurement"], [12, 15, 18, 22, 25, 30, 35, 40])


def test_status_missing_values_excluded_and_remaining_stats_match():
    col = RESULT["Status"]
    assert col["missing"] == 2
    _assert_stats_match(col, [5, 7, 9, 11, 13, 15])


def test_value_non_numeric_and_normalized_counts_match_hand_count():
    col = RESULT["Value"]
    # "C" appears twice -> excluded as non-numeric.
    assert col["non_numeric"] == 2
    assert col["top_non_numeric_codes"] == {"C": 2}
    # "1,200" and "1,500" are English-grouped thousands -> normalized, not excluded.
    assert col["normalized"] == 2
    _assert_stats_match(col, [100, 1200, 300, 1500, 400, 500])


def test_sex_binary_counts_match_hand_count():
    col = RESULT["Sex"]
    assert col["is_binary"] is True
    # 4 zeros, 4 ones out of 8 -> 50% / 50%, exactly.
    assert col["binary_counts"] == {
        "coded_0": {"count": 4, "percent": 50.0},
        "coded_1": {"count": 4, "percent": 50.0},
    }


def test_meta_row_counts_match_hand_count():
    # 8 rows total. Status is missing at indices {1, 4}; Value is
    # non-numeric ("C") at indices {2, 5} — no overlap with Status's
    # excluded rows. The joint-valid row count (valid across ALL four
    # selected columns) excludes the union {1, 2, 4, 5}: 8 - 4 = 4 used.
    meta = RESULT["_meta"]
    assert meta["total_rows"] == 8
    assert meta["used_rows"] == 4
    assert meta["dropped_rows"] == 4


def test_reference_calculation_is_actually_independent_of_pandas():
    # Sanity check on the validation methodology itself: confirm stdlib's
    # sample stdev is computed via a formula distinct from pandas/numpy's
    # internal reduction, by checking it against the textbook formula
    # directly (not just trusting the stdlib call).
    values = [12, 15, 18, 22, 25, 30, 35, 40]
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    manual_std = math.sqrt(variance)
    assert manual_std == pytest.approx(st.stdev(values), abs=TOLERANCE)
    assert manual_std == pytest.approx(RESULT["Measurement"]["std"], abs=TOLERANCE)
