from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from gold_intelligence.monthly_research import REGIMES, SPECS, MonthlyChange, MonthlyResearchPlan
from gold_intelligence.monthly_stability import monthly_stability
from gold_intelligence.world_bank import SERIES


def parent(changes, minimum=3):
    return SimpleNamespace(
        fingerprint="a" * 64,
        as_of=datetime(2026, 10, 8, tzinfo=UTC),
        monthly=SimpleNamespace(
            changes=changes,
            fingerprint="b" * 64,
            plan=MonthlyResearchPlan(minimum_pairs=minimum, rolling_months=max(60, minimum)),
        ),
    )


def change(year, month, value, regime=REGIMES[0], missing=False):
    values = {s: -value for s in SPECS}
    values[SERIES] = value
    if missing:
        values["DGS10"] = None
    return MonthlyChange(month=date(year, month, 1), method=regime, values=values, exclusions={})


def test_fixed_windows_do_not_pool_opposite_relationships():
    changes = [change(2010, m, m) for m in range(1, 4)]
    positive = [
        change(2015, m, m).model_copy(update={"values": {s: m for s in SPECS}}) for m in range(1, 4)
    ]
    result = monthly_stability(parent(changes + positive))
    rows = [r for r in result["rows"] if r["series_id"] == "DFII10"]
    assert rows[0]["pearson"] == pytest.approx(-1)
    assert rows[1]["pearson"] == pytest.approx(1)
    assert set(rows[0]["months"]).isdisjoint(rows[1]["months"])
    assert not result["forecasting_test"]
    assert result["report_fingerprint"] == "a" * 64


def test_missing_common_month_and_short_new_method_are_not_estimated():
    changes = [change(2025, m, m, missing=m == 2) for m in range(1, 4)]
    changes += [change(2025, m, m, regime=REGIMES[1]) for m in range(7, 9)]
    rows = monthly_stability(parent(changes))["rows"]
    assert len(rows) == 8
    assert all(r["n"] == 2 and r["pearson"] is None for r in rows)
    assert {r["method"] for r in rows} == set(REGIMES)
    assert rows[0]["excluded_months"] == 1


def test_constant_and_empty_samples_have_no_coefficient():
    rows = monthly_stability(parent([change(2010, m, 1) for m in range(1, 4)]))["rows"]
    assert all(r["status"] == "constant" and r["spearman"] is None for r in rows)
    assert monthly_stability(parent([]))["rows"] == []
