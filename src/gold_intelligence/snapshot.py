import math
from datetime import datetime
from typing import Literal

from pydantic import Field

from .analysis import price_series, technical_features
from .models import Contract, Timestamp, aware
from .storage import Store, record_id


class MarketSnapshot(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    as_of: Timestamp
    replay_mode: Literal["system", "source"]
    instrument: str
    timeframe: str
    synthetic: bool
    price_status: Literal["fresh", "stale"]
    technical: dict
    context: dict
    warnings: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    feature_version: Literal["technical_v1"] = "technical_v1"
    analysis_scope: Literal["research_only"] = "research_only"
    decision: Literal["NO_TRADE"] = "NO_TRADE"
    decision_reason: str = "No validated trading strategy or execution adapter is installed."
    parameters: dict = Field(default_factory=dict)


def snapshot(
    store: Store,
    as_of: datetime,
    instrument: str = "XAUUSD",
    timeframe: str = "1d",
    mode: str = "system",
    source_id: str | None = None,
    dataset: str | None = None,
    venue: str | None = None,
    stale_after_hours: float = 96,
) -> MarketSnapshot:
    aware(as_of)
    if not math.isfinite(stale_after_hours) or stale_after_hours <= 0:
        raise ValueError("staleness threshold must be positive")
    bars = [
        b
        for b in store.read("price_bar", as_of, mode)
        if b.instrument == instrument
        and b.timeframe == timeframe
        and b.provenance.observed_at <= as_of
        and (not source_id or b.provenance.source_id == source_id)
        and (not dataset or b.provenance.dataset == dataset)
        and (not venue or b.venue == venue)
    ]
    bars = price_series(bars)
    last = bars[-1]
    synthetic = last.provenance.synthetic
    age = (as_of - last.provenance.observed_at).total_seconds() / 3600
    warnings = []
    if synthetic:
        warnings.append("SYNTHETIC DEMONSTRATION: not actual market observations.")
    if age > stale_after_hours:
        warnings.append("Latest price exceeds the configured freshness threshold.")
    if len(bars) < 50:
        warnings.append("Insufficient warm-up for SMA50 trend classification.")
    if mode == "source":
        warnings.append("Source replay ignores local retrieval time; audit release evidence first.")
    recent = bars[-50:]
    if timeframe == "1d" and any(
        (b.provenance.observed_at - a.provenance.observed_at).days > 4
        for a, b in zip(recent, recent[1:], strict=False)
    ):
        warnings.append(
            "Daily series contains gaps over four calendar days; review market calendar."
        )
    context = {
        layer: {"status": "missing", "observations": []}
        for layer in (
            "macro",
            "central_banks",
            "etf",
            "physical",
            "options",
            "positioning",
            "news",
            "calendar",
        )
    }
    evidence = [record_id(b) for b in bars]  # Swing features can depend on the full history.
    latest = {}
    for item in store.read("observation", as_of, mode):
        p = item.provenance
        if p.synthetic != synthetic or p.observed_at > as_of or item.layer not in context:
            continue
        key = (
            item.layer,
            item.series_id,
            p.source_id,
            p.dataset,
            p.unit,
            p.currency,
            item.vintage_date,
            tuple(
                sorted(
                    (k, v)
                    for k, v in item.dimensions.items()
                    if k not in {"realtime_start", "realtime_end"}
                )
            ),
        )
        rank = (p.observed_at, p.available_at, p.retrieved_at, record_id(item))
        if key not in latest or rank > latest[key][0]:
            latest[key] = (rank, item)
    for key in sorted(latest, key=str):
        item = latest[key][1]
        p = item.provenance
        context[item.layer]["status"] = "available_uninterpreted"
        context[item.layer]["observations"].append(
            {
                "series_id": item.series_id,
                "value": item.value,
                "unit": p.unit,
                "currency": p.currency,
                "source_id": p.source_id,
                "dimensions": item.dimensions,
                "vintage_date": item.vintage_date.isoformat() if item.vintage_date else None,
                "observed_at": p.observed_at.isoformat(),
                "available_at": p.available_at.isoformat(),
                "age_days": (as_of - p.observed_at).total_seconds() / 86400,
                "missing_value": item.value is None,
                "evidence_id": record_id(item),
            }
        )
        evidence.append(record_id(item))
    positions = {}
    for item in store.read("positioning", as_of, mode):
        p = item.provenance
        if p.synthetic != synthetic or p.observed_at > as_of:
            continue
        key = (item.market_code, item.report_type, item.category, p.source_id)
        rank = (p.observed_at, p.available_at, p.retrieved_at, record_id(item))
        if key not in positions or rank > positions[key][0]:
            positions[key] = (rank, item)
    for key in sorted(positions):
        item = positions[key][1]
        context["positioning"]["status"] = "available_uninterpreted"
        context["positioning"]["observations"].append(
            {
                "market_code": item.market_code,
                "category": item.category,
                "net": item.net,
                "report_type": item.report_type,
                "open_interest": item.open_interest,
                "age_days": (as_of - item.provenance.observed_at).total_seconds() / 86400,
                "evidence_id": record_id(item),
            }
        )
        evidence.append(record_id(item))
    for kind, layer in (("news_event", "news"), ("calendar_release", "calendar")):
        events = {}
        for item in store.read(kind, as_of, mode):
            if item.provenance.synthetic != synthetic:
                continue
            key = (item.event_id, item.provenance.source_id)
            rank = (item.provenance.available_at, item.provenance.retrieved_at, record_id(item))
            if key not in events or rank > events[key][0]:
                events[key] = (rank, item)
        for key in sorted(events):
            item = events[key][1]
            context[layer]["status"] = "available_uninterpreted"
            context[layer]["observations"].append(
                {"record": item.model_dump(mode="json"), "evidence_id": record_id(item)}
            )
            evidence.append(record_id(item))
    warnings.append(
        "Context ages are reported; no universal macro freshness or causal bias is inferred."
    )
    return MarketSnapshot(
        as_of=as_of,
        replay_mode=mode,
        instrument=instrument,
        timeframe=timeframe,
        synthetic=synthetic,
        price_status="stale" if age > stale_after_hours else "fresh",
        technical=technical_features(bars),
        context=context,
        warnings=tuple(warnings),
        evidence_ids=tuple(sorted(set(evidence))),
        parameters={
            "stale_after_hours": stale_after_hours,
            "source_id": last.provenance.source_id,
            "dataset": last.provenance.dataset,
            "venue": last.venue,
            "currency": last.provenance.currency,
            "unit": last.provenance.unit,
        },
    )
