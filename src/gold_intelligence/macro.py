"""Reviewed FRED backfills and conservative point-in-time macro context."""

import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode

import yaml
from pydantic import Field, model_validator

from .acquisition import acquire
from .ingestion import fetch_bytes, ingest_fred
from .models import Contract, Hash, NonEmpty, Timestamp, aware
from .registry import Source
from .storage import Store, record_id


class CoreSeries(Contract):
    series_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    unit: NonEmpty
    currency: str | None = None
    frequency: Literal["D", "W", "M", "Q"]
    provider_units: NonEmpty
    seasonal_adjustment: Literal["SA", "NSA", "SAAR"]
    max_age_days: float = Field(gt=0)


class MacroPlan(Contract):
    series: tuple[CoreSeries, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_series(self):
        if len({s.series_id for s in self.series}) != len(self.series):
            raise ValueError("macro plan must have unique series IDs")
        return self


def load_plan(path: Path) -> MacroPlan:
    return MacroPlan.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def fetch_reviewed_series(store, source, spec, start, end, vintage, fetch):
    key = os.environ.get("FRED_API_KEY")
    if not key:
        raise ValueError("set FRED_API_KEY before fetching")
    params = {"series_id": spec.series_id, "api_key": key, "file_type": "json"}
    content = fetch("https://api.stlouisfed.org/fred/series?" + urlencode(params))
    store.put_raw(content)  # Traced by this series' acquisition manifest, including failures.
    try:
        rows = json.loads(content)["seriess"]
        expected = {
            "id": spec.series_id,
            "units": spec.provider_units,
            "frequency_short": spec.frequency,
            "seasonal_adjustment_short": spec.seasonal_adjustment,
        }
        if len(rows) != 1 or any(rows[0][k] != v for k, v in expected.items()):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise ValueError("FRED metadata differs from the reviewed plan") from None
    return ingest_fred(
        store, source, spec.series_id, start, end, spec.unit, spec.currency, vintage, fetch
    )


def fetch_core(
    store: Store,
    source: Source,
    plan: MacroPlan,
    start: date,
    end: date,
    vintage: date | None = None,
    fetch=fetch_bytes,
) -> dict:
    """Each series is atomic; successful series survive another series' failure."""
    if source.source_id != "fred" or not date(1776, 7, 4) <= start <= end:
        raise ValueError("invalid FRED source or observation interval")
    if end > datetime.now(UTC).date() or (vintage and vintage > datetime.now(UTC).date()):
        raise ValueError("future acquisition end or vintage")
    plan_bytes = plan.model_dump_json().encode()
    results = []
    for spec in plan.series:

        def execute(spec=spec):
            store.put_raw(plan_bytes)
            return fetch_reviewed_series(store, source, spec, start, end, vintage, fetch)

        try:
            result = acquire(
                store,
                "fetch-fred-reviewed",
                {
                    "source": "fred",
                    "series": spec.series_id,
                    "unit": spec.unit,
                    "currency": spec.currency,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "vintage": vintage.isoformat() if vintage else None,
                },
                execute,
            )
            results.append({"series": spec.series_id, "status": "succeeded", **result})
        except (ValueError, OSError, KeyError, TypeError) as exc:
            # Provider bodies/URLs may contain credentials; expose only the exception type.
            results.append(
                {"series": spec.series_id, "status": "failed", "failure_type": type(exc).__name__}
            )
    failures = sum(r["status"] == "failed" for r in results)
    return {
        "status": "succeeded"
        if not failures
        else ("failed" if failures == len(results) else "partial"),
        "series": results,
        "inserted": sum(r.get("inserted", 0) for r in results),
    }


class MacroEntry(Contract):
    series_id: NonEmpty
    unit: NonEmpty
    frequency: NonEmpty
    status: Literal["available", "missing", "missing_value", "stale"]
    value: float | None = None
    reference_at: Timestamp | None = None
    available_at: Timestamp | None = None
    retrieved_at: Timestamp | None = None
    availability_basis: str | None = None
    reference_age_days: float | None = None
    max_age_days: float
    record_id: Hash | None = None


class MacroContext(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    as_of: Timestamp
    mode: Literal["system", "source"]
    vintage: date | None
    status: Literal["available", "incomplete"]
    entries: tuple[MacroEntry, ...]
    note: str = (
        "Reference dates are period labels, not release times. Historical vintages retain "
        "retrieval-time availability unless a release timestamp is independently verified. "
        "Latest nulls remain missing; no backward fill or trading signal is produced."
    )


def macro_context(store, plan, as_of, mode="system", vintage=None) -> MacroContext:
    as_of = aware(as_of).astimezone(UTC)
    if vintage and vintage > as_of.date():
        raise ValueError("vintage cannot follow the context cutoff")
    records = store.read("observation", as_of, mode)
    entries = []
    for spec in plan.series:
        candidates = []
        for r in records:
            p = r.provenance
            if (
                p.source_id != "fred"
                or r.series_id != spec.series_id
                or r.vintage_date != vintage
                or p.observed_at > as_of
            ):
                continue
            if (
                r.layer != "macro"
                or p.synthetic
                or p.dataset != spec.series_id
                or p.unit != spec.unit
                or p.currency != spec.currency
                or set(r.dimensions) - {"realtime_start", "realtime_end"}
            ):
                raise ValueError(f"incompatible stream for {spec.series_id}")
            candidates.append(r)
        fields = dict(
            series_id=spec.series_id,
            unit=spec.unit,
            frequency=spec.frequency,
            max_age_days=spec.max_age_days,
        )
        if not candidates:
            entries.append(MacroEntry(**fields, status="missing"))
            continue

        def rank(r):
            p = r.provenance
            return p.observed_at, p.available_at, p.retrieved_at

        best = max(map(rank, candidates))
        winners = [r for r in candidates if rank(r) == best]
        if len({r.value for r in winners}) > 1:
            raise ValueError(f"conflicting latest revisions for {spec.series_id}")
        r = min(winners, key=record_id)
        p = r.provenance
        age = (as_of - p.observed_at).total_seconds() / 86400
        status = (
            "missing_value"
            if r.value is None
            else ("stale" if age > spec.max_age_days else "available")
        )
        entries.append(
            MacroEntry(
                **fields,
                status=status,
                value=r.value,
                reference_at=p.observed_at,
                available_at=p.available_at,
                retrieved_at=p.retrieved_at,
                availability_basis=p.availability_basis,
                reference_age_days=age,
                record_id=record_id(r),
            )
        )
    return MacroContext(
        as_of=as_of,
        mode=mode,
        vintage=vintage,
        entries=tuple(entries),
        status="available" if all(e.status == "available" for e in entries) else "incomplete",
    )
