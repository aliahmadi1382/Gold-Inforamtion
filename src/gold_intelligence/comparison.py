"""Descriptive monthly comparison, with different definitions kept visible."""

import calendar
import statistics
from collections import defaultdict
from datetime import UTC, date

from .models import aware
from .storage import record_id
from .world_bank import DATASET, SERIES


def latest_periods(records):
    grouped = defaultdict(list)
    for r in records:
        grouped[r.provenance.observed_at].append(r)
    result = []
    for versions in grouped.values():

        def rank(r):
            return r.provenance.available_at, r.provenance.retrieved_at

        best = max(map(rank, versions))
        winners = [r for r in versions if rank(r) == best]
        values = {r.close if r.kind == "price_close" else r.value for r in winners}
        if len(values) > 1:
            raise ValueError("conflicting revisions in monthly comparison")
        result.append(min(winners, key=record_id))
    return sorted(result, key=lambda r: r.provenance.observed_at)


def compare_monthly(store, as_of) -> dict:
    as_of = aware(as_of).astimezone(UTC)
    alpha = [
        r
        for r in store.read("price_close", as_of)
        if r.provenance.source_id == "alpha_vantage_gold" and r.provenance.observed_at <= as_of
    ]
    monthly = [
        r
        for r in store.read("observation", as_of)
        if r.provenance.source_id == "world_bank_pink_sheet"
        and r.series_id == SERIES
        and r.provenance.observed_at <= as_of
    ]
    for r in alpha:
        p = r.provenance
        if (
            p.synthetic
            or p.dataset != "gold_silver_history_daily_v1"
            or r.instrument != "XAUUSD"
            or r.venue != "ALPHA_VANTAGE_REFERENCE"
            or r.timeframe != "1d"
            or r.price_type != "provider_reference"
            or p.currency != "USD"
            or p.unit != "currency_per_troy_ounce"
        ):
            raise ValueError("unexpected daily stream in monthly comparison")
    for r in monthly:
        p = r.provenance
        method = (
            "spot_daily_average"
            if p.observed_at.date() >= date(2025, 6, 1)
            else ("london_afternoon_fixing_average")
        )
        if (
            p.synthetic
            or p.dataset != DATASET
            or p.currency != "USD"
            or p.unit != "currency_per_troy_ounce"
            or r.layer != "price"
            or r.vintage_date is not None
            or r.value is None
            or r.value <= 0
            or p.observed_at.day != 1
            or r.dimensions
            != {
                "instrument": "GOLD",
                "frequency": "1mo",
                "aggregation": "monthly_average",
                "methodology": method,
            }
        ):
            raise ValueError("unexpected monthly reference stream")
    alpha, monthly = latest_periods(alpha), latest_periods(monthly)
    first_weekend = next((r.session_date for r in alpha if r.session_date.weekday() >= 5), None)
    grouped = defaultdict(list)
    for r in alpha:
        grouped[r.session_date.strftime("%Y-%m")].append(r)
    rows, excluded = [], []
    for reference in monthly:
        first = reference.provenance.observed_at.date()
        month = first.strftime("%Y-%m")
        closes = grouped.get(month, [])
        if not closes:
            continue
        last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
        if alpha[0].session_date > first or alpha[-1].session_date < last or last >= as_of.date():
            excluded.append(month)
            continue
        weekdays = [r.close for r in closes if r.session_date.weekday() < 5]
        if not weekdays:
            raise ValueError("overlapping month has no weekday observations")
        all_mean = statistics.mean(r.close for r in closes)
        weekday_mean = statistics.mean(weekdays)
        weekday_slots = sum(
            date(first.year, first.month, day).weekday() < 5 for day in range(1, last.day + 1)
        )
        rows.append(
            {
                "month": month,
                "world_bank_methodology": reference.dimensions["methodology"],
                "alpha_calendar_regime": (
                    "no_weekend_labels_observed"
                    if first_weekend is None
                    else (
                        "before_first_weekend_label"
                        if month < first_weekend.strftime("%Y-%m")
                        else "weekend_label_era"
                    )
                ),  # Observed boundary, not a provider methodology claim.
                "alpha_observations": len(closes),
                "alpha_weekend_labels": len(closes) - len(weekdays),
                "weekday_slots_without_labels": weekday_slots - len(weekdays),
                "alpha_all_labels_mean": all_mean,
                "alpha_weekdays_mean": weekday_mean,
                "world_bank_mean": reference.value,
                "relative_difference_all": all_mean / reference.value - 1,
                "relative_difference_weekdays": weekday_mean / reference.value - 1,
                "world_bank_record_id": record_id(reference),
                "alpha_record_ids": [record_id(r) for r in closes],
            }
        )

    def summary(values):
        return {
            "months": len(values),
            "median_absolute_relative_difference": statistics.median(
                abs(r["relative_difference_all"]) for r in values
            )
            if values
            else None,
            "max_absolute_relative_difference": max(
                abs(r["relative_difference_all"]) for r in values
            )
            if values
            else None,
        }

    return {
        "schema_version": "1.0.0",
        "as_of": as_of.isoformat(),
        "status": "descriptive_only" if rows else "no_overlap",
        "first_weekend_label": first_weekend.isoformat() if first_weekend else None,
        "summary": summary(rows),
        "by_world_bank_methodology": {
            method: summary([r for r in rows if r["world_bank_methodology"] == method])
            for method in sorted({r["world_bank_methodology"] for r in rows})
        },
        "by_alpha_calendar_regime": {
            regime: summary([r for r in rows if r["alpha_calendar_regime"] == regime])
            for regime in sorted({r["alpha_calendar_regime"] for r in rows})
        },
        "excluded_boundary_months": excluded,
        "months": rows,
        "limitations": [
            "Different monthly definitions; upstream supplier independence is not established.",
            "Weekday-only means are sensitivity checks, not corrected daily prices.",
            "Missing weekday slots include holidays; no exchange calendar is inferred.",
            "Interior gaps remain visible in counts; no interpolation is performed.",
            "Agreement does not verify the daily unit, session time, weekends or execution price.",
        ],
    }
