from types import SimpleNamespace

import pytest
from test_monthly_stability import change, parent

from gold_intelligence.monthly_research import REGIMES, rolling_associations, summarize
from gold_intelligence.monthly_robustness import monthly_robustness


def report(changes, minimum=3, rolling=3):
    result = parent(changes, minimum)
    plan = SimpleNamespace(minimum_pairs=minimum, rolling_months=rolling)
    result.monthly.plan = plan
    result.monthly.associations = summarize(changes, plan)
    result.monthly.rolling = rolling_associations(changes, plan)
    return result


def test_all_single_month_removals_preserve_common_population_and_method():
    rows = [change(2010, m, m) for m in range(1, 6)]
    rows += [change(2025, m, m, regime=REGIMES[1]) for m in range(7, 10)]
    result = monthly_robustness(report(rows))
    eligible = result["influence"][0]
    assert eligible["n"] == 5 and len(eligible["removals"]) == 5
    assert all(r["n"] == 4 and r["pearson"] == pytest.approx(-1) for r in eligible["removals"])
    assert eligible["pearson_min"] == pytest.approx(-1)
    assert eligible["largest_absolute_change"] == pytest.approx(0)
    assert result["influence"][4]["status"] == "too_short"
    assert result["influence"][4]["removals"] == []
    assert not result["forecasting_test"] and not result["daily_backtest_ready"]
    assert result["monthly_fingerprint"] == "b" * 64


def test_pairwise_extra_months_are_explicit_not_silently_shared():
    rows = [change(2010, m, m, missing=m == 2) for m in range(1, 6)]
    result = monthly_robustness(report(rows))
    row = next(
        r
        for r in result["sample_comparisons"]
        if r["series_id"] == "DFII10" and r["method"] == REGIMES[0]
    )
    assert row["pairwise_n"] == 5 and row["common_n"] == 4
    assert row["additional_pairwise_months"] == ["2010-02-01"]
    assert all(len(r["removals"]) == 4 for r in result["influence"][:4])


def test_rolling_gaps_and_method_boundary_are_null_not_connected():
    rows = [change(2025, m, m, regime=REGIMES[m >= 6], missing=m == 3) for m in range(1, 9)]
    result = monthly_robustness(report(rows))
    driver = [r for r in result["rolling"] if r["series_id"] == "DFII10"]
    assert driver[0]["pearson"] is None and driver[0]["missing_months"] == ["2025-03-01"]
    crossing = next(r for r in driver if r["last_month"] == "2025-06-01")
    assert crossing["pearson"] is None and "methodology_break" in crossing["reasons"]
    assert driver[-1]["pearson"] == pytest.approx(-1)


def test_removal_can_make_a_series_constant_without_zero_imputation():
    rows = [change(2010, m, 1 if m < 4 else 2) for m in range(1, 5)]
    row = monthly_robustness(report(rows))["influence"][0]
    assert row["undefined_removals"] == 1
    assert row["removals"][-1]["pearson"] is None
    assert row["pearson_min"] == pytest.approx(-1)
    assert monthly_robustness(report([]))["rolling"] == []
