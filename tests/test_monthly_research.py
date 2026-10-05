import calendar
import json
import math
import runpy
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from gold_intelligence.cli import main
from gold_intelligence.ingestion import provenance
from gold_intelligence.models import Observation
from gold_intelligence.monthly_research import (
    DRIVERS,
    REGIMES,
    SERIES,
    SPECS,
    MonthlyChange,
    MonthlyResearchPlan,
    coefficients,
    load_research_plan,
    method,
    monthly_research,
    ranks,
    render_monthly_persian,
    rolling_associations,
    shift_month,
    summarize,
)
from gold_intelligence.storage import record_id
from gold_intelligence.world_bank import DATASET

CUTOFF = datetime(2026, 10, 1, tzinfo=UTC)


@pytest.fixture
def make_observation(store, registry):
    raw = store.put_raw(b"Invented monthly research fixtures, not vendor observations")

    def make(series, day, value=100, retrieved=CUTOFF, **changes):
        unit, currency, _, _ = SPECS[series]
        gold = series == SERIES
        p = provenance(
            registry.get("world_bank_pink_sheet" if gold else "fred"),
            raw,
            day.isoformat(),
            datetime.combine(day, datetime.min.time(), UTC),
            retrieved,
            DATASET if gold else series,
            unit,
            currency,
            day.isoformat(),
        )
        fields = dict(
            provenance=p,
            layer="price" if gold else "macro",
            series_id=series,
            value=value,
            dimensions={
                "instrument": "GOLD",
                "frequency": "1mo",
                "aggregation": "monthly_average",
                "methodology": method(day),
            }
            if gold
            else {},
        )
        fields.update(changes)
        return Observation(**fields)

    return make


def seed(store, make, start=date(2024, 1, 1), count=4):
    records = []
    for index in range(count):
        month = shift_month(start, index)
        for series in SPECS:
            if SPECS[series][2] == "monthly":
                records.append(make(series, month, 100 * 1.1**index))
            else:
                for day in range(1, calendar.monthrange(month.year, month.month)[1] + 1):
                    when = month.replace(day=day)
                    if when.weekday() < 5:
                        records.append(make(series, when, 100 + index + day / 100))
    store.put(records)
    return records


def plan(**kwargs):
    return MonthlyResearchPlan(start_month=date(2024, 2, 1), **kwargs)


def level(report, series, month):
    return next(r for r in report.levels if r.series_id == series and r.month == month)


def test_known_correlations_ties_and_constant_series():
    assert coefficients([1, 2, 3], [1, 3, 2]) == pytest.approx((0.5, 0.5))
    assert coefficients([1, 1, 2], [1, 2, 3])[1] == pytest.approx(math.sqrt(3) / 2)
    assert ranks([9, 1, 1, 5]) == [4, 1.5, 1.5, 3]
    assert coefficients([1, 1, 1], [1, 2, 3]) == (None, None)
    assert coefficients([], []) == (None, None)


def test_price_cpi_changes_and_rate_units(store, make_observation):
    seed(store, make_observation)
    report = monthly_research(store, plan(), CUTOFF)
    feb = report.changes[0]
    assert feb.values[SERIES] == pytest.approx(10)
    assert feb.values["CPIAUCSL"] == pytest.approx(10)
    # Independent arithmetic on February/January weekday day numbers.
    monthly_means = []
    for month in (1, 2):
        days = [
            d
            for d in range(1, calendar.monthrange(2024, month)[1] + 1)
            if date(2024, month, d).weekday() < 5
        ]
        monthly_means.append(100 + month - 1 + sum(days) / len(days) / 100)
    assert feb.values["DFII10"] == pytest.approx(monthly_means[1] - monthly_means[0])
    assert feb.values["DTWEXBGS"] == pytest.approx(100 * (monthly_means[1] / monthly_means[0] - 1))
    assert report.daily_backtest_ready is False


def test_latest_null_not_backfilled_and_breaks_both_adjacent_changes(store, make_observation):
    records = seed(store, make_observation)
    old = next(
        r for r in records if r.series_id == "CPIAUCSL" and r.provenance.observed_at.month == 2
    )
    null = make_observation("CPIAUCSL", date(2024, 2, 1), None, CUTOFF + timedelta(hours=1))
    store.put([null])
    earlier = monthly_research(store, plan(), CUTOFF)
    later = monthly_research(store, plan(), CUTOFF + timedelta(hours=1))
    assert level(earlier, "CPIAUCSL", date(2024, 2, 1)).record_ids == (record_id(old),)
    assert level(later, "CPIAUCSL", date(2024, 2, 1)).record_ids == (record_id(null),)
    assert [r.exclusions["CPIAUCSL"] for r in later.changes[:2]] == [
        "current_missing",
        "previous_missing",
    ]
    assert later.changes[2].values["CPIAUCSL"] is not None
    assert earlier.fingerprint != later.fingerprint


def test_vintage_and_future_retrieval_excluded_even_if_verified_release(store, make_observation):
    current = make_observation("CPIAUCSL", date(2024, 1, 1))
    future = make_observation("CPIAUCSL", date(2024, 1, 1), 1000, CUTOFF + timedelta(days=1))
    future = future.model_copy(
        update={
            "provenance": future.provenance.model_copy(
                update={"availability_basis": "verified_release", "available_at": CUTOFF}
            )
        }
    )
    vintage = make_observation("CPIAUCSL", date(2024, 1, 1), 999, vintage_date=date(2024, 2, 1))
    store.put([current, future, vintage])
    report = monthly_research(store, plan(), CUTOFF)
    assert level(report, "CPIAUCSL", date(2024, 1, 1)).value == 100


def test_equal_rank_conflicting_revisions_fail(store, make_observation):
    store.put([make_observation("CPIAUCSL", date(2024, 1, 1), n) for n in (100, 101)])
    with pytest.raises(ValueError, match="conflicting revisions"):
        monthly_research(store, plan(), CUTOFF)


def test_missing_weekday_rejects_month_but_null_holiday_can_pass(store, make_observation):
    records = seed(store, make_observation)
    missing = next(
        r
        for r in records
        if r.series_id == "DTWEXBGS" and r.provenance.observed_at.date() == date(2024, 2, 29)
    )
    store.db.execute("DELETE FROM records WHERE id = ?", (record_id(missing),))
    store.db.commit()
    store.put([make_observation("DFII10", date(2024, 2, 19), None, CUTOFF + timedelta(hours=1))])
    report = monthly_research(store, plan(), CUTOFF + timedelta(hours=1))
    dollar = level(report, "DTWEXBGS", date(2024, 2, 1))
    assert dollar.value is None and dollar.status == "insufficient_daily_coverage"
    assert dollar.missing_labels == (date(2024, 2, 29),)
    rate = level(report, "DFII10", date(2024, 2, 1))
    assert rate.value is not None and rate.null_labels == (date(2024, 2, 19),)
    assert report.changes[1].exclusions["DTWEXBGS"] == "previous_insufficient_daily_coverage"


def test_too_many_null_weekdays_rejects_average(store, make_observation):
    records = seed(store, make_observation, count=2)
    february = [
        r for r in records if r.series_id == "DGS10" and r.provenance.observed_at.month == 2
    ]
    store.put(
        [
            make_observation(
                "DGS10", r.provenance.observed_at.date(), None, CUTOFF + timedelta(hours=1)
            )
            for r in february[:5]
        ]
    )
    report = monthly_research(store, plan(), CUTOFF + timedelta(hours=1))
    assert level(report, "DGS10", date(2024, 2, 1)).status == "insufficient_daily_coverage"


def test_month_completion_and_utc_labels(store, make_observation):
    r = make_observation(SERIES, date(2026, 9, 1), retrieved=datetime(2026, 9, 1, tzinfo=UTC))
    r = r.model_copy(
        update={
            "provenance": r.provenance.model_copy(
                update={
                    "observed_at": r.provenance.observed_at.astimezone(
                        timezone(timedelta(hours=-1))
                    )
                }
            )
        }
    )
    store.put([r])
    p = MonthlyResearchPlan(start_month=date(2026, 9, 1))
    unfinished = monthly_research(store, p, CUTOFF - timedelta(seconds=1))
    finished = monthly_research(store, p, CUTOFF)
    assert not unfinished.changes
    assert level(finished, SERIES, date(2026, 9, 1)).value == 100


def test_methodology_break_is_excluded_not_chained(store, make_observation):
    seed(store, make_observation, start=date(2025, 4, 1), count=4)
    report = monthly_research(store, MonthlyResearchPlan(start_month=date(2025, 5, 1)), CUTOFF)
    assert report.changes[0].values[SERIES] == pytest.approx(10)
    assert report.changes[1].exclusions[SERIES] == "methodology_break"
    assert report.changes[1].values[SERIES] is None
    assert report.changes[2].values[SERIES] == pytest.approx(10)
    assert all(a.pearson is None for a in report.associations)


@pytest.mark.parametrize("mutation", ["unit", "dimensions", "synthetic", "date", "zero", "weekend"])
def test_invalid_stream_fails(store, make_observation, mutation):
    r = make_observation("DTWEXBGS", date(2024, 1, 2))
    if mutation == "unit":
        r = r.model_copy(update={"provenance": r.provenance.model_copy(update={"unit": "wrong"})})
    elif mutation == "dimensions":
        r = r.model_copy(update={"dimensions": {"venue": "other"}})
    elif mutation == "synthetic":
        r = r.model_copy(
            update={
                "provenance": r.provenance.model_copy(
                    update={"synthetic": True, "availability_basis": "synthetic"}
                )
            }
        )
    elif mutation == "zero":
        r = r.model_copy(update={"value": 0})
    else:
        offset = timedelta(hours=1) if mutation == "date" else timedelta(days=4)
        r = r.model_copy(
            update={
                "provenance": r.provenance.model_copy(
                    update={"observed_at": r.provenance.observed_at + offset}
                )
            }
        )
    store.put([r])
    with pytest.raises(ValueError):
        monthly_research(store, plan(), CUTOFF)


def test_corrupt_raw_fails(store, make_observation):
    r = make_observation(SERIES, date(2024, 1, 1))
    store.put([r])
    (store.root / "raw" / r.provenance.raw_sha256).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="raw evidence"):
        monthly_research(store, plan(), CUTOFF)


def test_negative_real_yields_are_valid(store, make_observation):
    for day in range(1, 32):
        when = date(2024, 1, day)
        if when.weekday() < 5:
            store.put([make_observation("DFII10", when, -1)])
    report = monthly_research(store, plan(), CUTOFF)
    assert level(report, "DFII10", date(2024, 1, 1)).value == -1


@pytest.mark.parametrize("tamper", [None, "level", "correlation", "coverage"])
def test_independent_reconciliation(store, make_observation, tmp_path, tamper):
    seed(store, make_observation, count=5)
    report = monthly_research(store, plan(minimum_pairs=3, rolling_months=3), CUTOFF)
    payload = report.model_dump(mode="json")
    if tamper == "level":
        payload["levels"][0]["value"] += 1
    elif tamper == "correlation":
        payload["associations"][0]["pearson"] = 0.123
    elif tamper == "coverage":
        payload["levels"][0]["valid_values"] += 1
    path = tmp_path / "report.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    validate = runpy.run_path("scripts/inspect_monthly_research.py")["validate"]
    if tamper:
        with pytest.raises(ValueError):
            validate(store.root, path)
    else:
        assert validate(store.root, path)["status"] == "reconciled"


def changes(count=5):
    return [
        MonthlyChange(
            month=shift_month(date(2024, 1, 1), i),
            method=REGIMES[0],
            values={s: i + (i % 2) / 10 for s in SPECS},
            exclusions={},
        )
        for i in range(count)
    ]


def test_pairwise_common_samples_and_minimum_are_explicit():
    rows = changes()
    rows[0].values["CPIAUCSL"] = None
    results = summarize(rows, plan(minimum_pairs=5))
    pairwise = next(
        a
        for a in results
        if a.series_id == "DFII10" and a.population == "pairwise" and a.method == REGIMES[0]
    )
    common = next(
        a
        for a in results
        if a.series_id == "DFII10" and a.population == "common" and a.method == REGIMES[0]
    )
    assert pairwise.n == 5 and pairwise.pearson == pytest.approx(1)
    assert common.n == 4 and common.status == "too_short" and common.pearson is None
    assert (
        len({a.months for a in results if a.population == "common" and a.method == REGIMES[0]}) == 1
    )


def test_rolling_never_bridges_gaps_or_method_breaks():
    p = plan(minimum_pairs=3, rolling_months=3)
    rows = changes(5)
    assert len(rolling_associations(rows, p)) == 3 * len(DRIVERS)
    rows[2].values["CPIAUCSL"] = None
    assert rolling_associations(rows, p) == []
    rows = changes(5)
    assert rolling_associations([rows[0], rows[2], rows[4]], p) == []
    rows[2] = rows[2].model_copy(update={"method": REGIMES[1]})
    assert rolling_associations(rows, p) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"start_month": "2005-01-01"},
        {"start_month": "2024-02-02"},
        {"minimum_valid_weekday_fraction": 1.1},
        {"minimum_pairs": 61},
        {"rolling_months": 2},
    ],
)
def test_invalid_plans(changes):
    with pytest.raises(ValueError):
        MonthlyResearchPlan(**changes)


def test_fingerprint_reproducible_and_empty_cli_exits_three(store, tmp_path, capsys):
    p = load_research_plan(Path("config/monthly_research.yaml"))
    a = monthly_research(store, p, CUTOFF)
    b = monthly_research(store, p, CUTOFF)
    assert a.fingerprint == b.fingerprint
    assert a.status == "insufficient_data"
    output = tmp_path / "reports"
    assert (
        main(
            [
                "--store",
                str(store.root),
                "monthly-research",
                "--as-of",
                CUTOFF.isoformat(),
                "--output-dir",
                str(output),
            ]
        )
        == 3
    )
    assert json.loads(capsys.readouterr().out)["estimated_associations"] == 0
    payload = json.loads((output / "monthly-research.json").read_text(encoding="utf-8"))
    assert payload["fingerprint"] == a.fingerprint
    assert (output / "monthly-research.fa.md").read_text(
        encoding="utf-8"
    ) == render_monthly_persian(a)
