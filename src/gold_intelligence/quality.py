"""Point-in-time coverage and data-readiness checks, without filling or deleting data."""

import hashlib
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import Field

from .models import Contract, Hash, NonEmpty, Record, Timestamp, aware
from .registry import Registry, validate_record_source
from .storage import Store, canonical, decode_record, record_id

Positive = Annotated[float, Field(gt=0)]


class RequiredStream(Contract):
    kind: Literal[
        "price_bar", "price_close", "observation", "positioning", "news_event", "calendar_release"
    ]
    source_id: NonEmpty | None = None
    dataset: NonEmpty | None = None
    instrument: NonEmpty | None = None
    series_id: NonEmpty | None = None
    timeframe: NonEmpty | None = None
    min_observations: int = Field(default=1, ge=1)


class QualityPolicy(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    max_age_hours: dict[str, Positive] = Field(default_factory=dict)
    daily_gap_warning_hours: Positive = 96
    missing_fraction_warning_above: float = Field(default=0, ge=0, le=1)
    required_streams: tuple[RequiredStream, ...] = ()


class QualityIssue(Contract):
    severity: Literal["warning", "error"]
    code: NonEmpty
    message: NonEmpty
    stream_id: Hash | None = None
    record_ids: tuple[str, ...] = ()


class StreamInventory(Contract):
    stream_id: Hash
    identity: dict
    record_versions: int = Field(ge=1)
    unique_observations: int = Field(ge=1)
    extra_versions: int = Field(ge=0)
    first_observed_at: Timestamp
    last_observed_at: Timestamp
    last_available_at: Timestamp
    age_hours: float
    freshness_limit_hours: float | None
    missing_values: int = Field(ge=0)
    missing_fraction: float = Field(ge=0, le=1)
    retrieval_time_only_versions: int = Field(ge=0)
    daily_gap_count: int = Field(ge=0)
    largest_gap_hours: float | None
    date_only_prices: int = Field(default=0, ge=0)
    weekend_date_labels: int = Field(default=0, ge=0)


class QualityReport(Contract):
    schema_version: Literal["1.1.0"] = "1.1.0"
    as_of: Timestamp
    replay_mode: Literal["system", "source"]
    status: Literal["pass", "warning", "fail"]
    data_mode: Literal["empty", "synthetic", "real", "mixed"]
    policy_sha256: Hash
    total_records: int
    valid_records: int
    eligible_records: int
    excluded_by_time: int
    streams: tuple[StreamInventory, ...]
    issues: tuple[QualityIssue, ...]
    interpretation: str = (
        "Operational checks only. No guarantee of source accuracy, market completeness, "
        "historical release correctness or trading fitness."
    )


def load_policy(path: Path) -> QualityPolicy:
    return QualityPolicy.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def stream_identity(record: Record) -> dict:
    p = record.provenance
    identity = dict(
        kind=record.kind,
        source_id=p.source_id,
        dataset=p.dataset,
        unit=p.unit,
        currency=p.currency,
        synthetic=p.synthetic,
    )
    if record.kind == "price_bar":
        identity.update(
            instrument=record.instrument,
            venue=record.venue,
            timeframe=record.timeframe,
            price_type=record.price_type,
            contract_expiry=str(record.contract_expiry) if record.contract_expiry else None,
            volume_unit=record.volume_unit,
        )
    elif record.kind == "price_close":
        identity.update(
            instrument=record.instrument,
            venue=record.venue,
            timeframe=record.timeframe,
            price_type=record.price_type,
            timestamp_precision=record.timestamp_precision,
            session_timezone=record.session_timezone,
            unit_basis=record.unit_basis,
        )
    elif record.kind == "observation":
        identity.update(
            layer=record.layer,
            series_id=record.series_id,
            vintage_date=str(record.vintage_date) if record.vintage_date else None,
            dimensions={
                k: v
                for k, v in record.dimensions.items()
                if k not in {"realtime_start", "realtime_end"}
            },
        )
    elif record.kind == "positioning":
        identity.update(
            market_code=record.market_code, report_type=record.report_type, category=record.category
        )
    elif record.kind == "news_event":
        identity.update(event_id=record.event_id)
    else:
        identity.update(
            event_id=record.event_id,
            series_id=record.series_id,
            reference_period=record.reference_period,
        )
    return identity


def assess(
    store: Store,
    registry: Registry,
    as_of: datetime,
    policy: QualityPolicy,
    mode: str = "system",
    allow_synthetic: bool = False,
) -> QualityReport:
    aware(as_of)
    if mode not in {"system", "source"}:
        raise ValueError("unknown replay mode")
    issues = []

    def issue(code, message, *, severity="error", stream_id=None, ids=()):
        issues.append(
            QualityIssue(
                severity=severity,
                code=code,
                message=message,
                stream_id=stream_id,
                record_ids=tuple(ids),
            )
        )

    groups = defaultdict(list)
    raw_checks = {}
    total = valid = eligible = excluded = 0
    flags = set()
    for identifier, kind, payload in store.entries():
        total += 1
        try:
            record = decode_record(identifier, kind, payload)
        except ValueError:
            issue(
                "INVALID_RECORD",
                "Stored contract, kind or content hash is invalid.",
                ids=(identifier,),
            )
            continue
        valid += 1
        p = record.provenance
        try:
            validate_record_source(record, registry)
        except ValueError:
            issue(
                "SOURCE_MISMATCH",
                "Source metadata or rights do not match the registry.",
                ids=(identifier,),
            )
        if p.raw_sha256 not in raw_checks:
            path = store.root / "raw" / p.raw_sha256
            raw_checks[p.raw_sha256] = (
                "RAW_MISSING"
                if not path.is_file()
                else "RAW_CORRUPT"
                if hashlib.sha256(path.read_bytes()).hexdigest() != p.raw_sha256
                else None
            )
            if raw_checks[p.raw_sha256]:
                issue(
                    raw_checks[p.raw_sha256],
                    "Referenced raw bytes are missing or corrupt.",
                    ids=(identifier,),
                )
        if p.available_at > as_of or (mode == "system" and p.retrieved_at > as_of):
            excluded += 1
            continue
        eligible += 1
        flags.add(p.synthetic)
        if p.observed_at > as_of and kind not in {"calendar_release", "news_event"}:
            issue(
                "FUTURE_OBSERVATION",
                "Eligible measurement has a future reference timestamp.",
                ids=(identifier,),
            )
        groups[canonical(stream_identity(record))].append(record)

    if not eligible:
        issue("NO_ELIGIBLE_DATA", "No valid records are available at the requested cutoff.")
    if flags == {True, False}:
        issue("MIXED_DATA_MODE", "Use separate stores for synthetic examples and real data.")
    elif flags == {True} and not allow_synthetic:
        issue("SYNTHETIC_INPUT", "Synthetic data cannot satisfy real-data readiness checks.")

    streams = []
    for identity_json, records in sorted(groups.items()):
        identity = stream_identity(records[0])
        sid = hashlib.sha256(identity_json.encode()).hexdigest()
        versions = defaultdict(list)
        for record in records:
            # News/calendar versions refer to the same event even if its scheduled time moves.
            slot = (
                "event"
                if record.kind in {"news_event", "calendar_release"}
                else (record.provenance.observed_at.astimezone(UTC).isoformat())
            )
            versions[slot].append(record)
        resolved = []
        for candidates in versions.values():

            def rank(r):
                return r.provenance.available_at, r.provenance.retrieved_at

            best = max(rank(record) for record in candidates)
            latest = [record for record in candidates if rank(record) == best]
            if len(latest) > 1:
                issue(
                    "AMBIGUOUS_REVISION",
                    "Multiple versions share the latest availability times.",
                    stream_id=sid,
                    ids=sorted(record_id(r) for r in latest),
                )
            resolved.append(min(latest, key=record_id))
        resolved.sort(key=lambda record: record.provenance.observed_at)
        first, last = resolved[0].provenance, resolved[-1].provenance
        age = (as_of - last.observed_at).total_seconds() / 3600
        age_key = f"series:{identity.get('series_id', '')}"
        limit = policy.max_age_hours.get(age_key, policy.max_age_hours.get(identity["kind"]))
        if limit is not None and age > limit:
            issue(
                "STALE_REFERENCE",
                "Latest reference timestamp exceeds the policy age limit.",
                severity="warning",
                stream_id=sid,
            )
        missing = sum(record.kind == "observation" and record.value is None for record in resolved)
        missing_fraction = missing / len(resolved)
        if missing_fraction > policy.missing_fraction_warning_above:
            issue(
                "MISSING_VALUES",
                "Selected observation versions contain null values.",
                severity="warning",
                stream_id=sid,
            )
        retrieval_only = sum(r.provenance.availability_basis == "retrieval_time" for r in records)
        if retrieval_only:
            issue(
                "RELEASE_TIME_UNKNOWN",
                "Availability is conservative retrieval time; "
                "historical release-time analysis needs separate evidence.",
                severity="warning",
                stream_id=sid,
            )
        gaps = []
        if identity.get("timeframe") == "1d":
            gaps = [
                (b.provenance.observed_at - a.provenance.observed_at).total_seconds() / 3600
                for a, b in zip(resolved, resolved[1:], strict=False)
            ]
        large_gaps = sum(gap > policy.daily_gap_warning_hours for gap in gaps)
        date_only_prices = sum(r.kind == "price_close" for r in resolved)
        weekend_labels = sum(
            r.kind == "price_close" and r.session_date.weekday() >= 5 for r in resolved
        )
        if date_only_prices:
            issue(
                "DATE_ONLY_PRICE",
                "Provider dates are period labels, not verified session-close instants; "
                "OHLC features and intraday alignment are unavailable.",
                severity="warning",
                stream_id=sid,
            )
        if identity.get("unit_basis") == "instrument_convention":
            issue(
                "UNIT_INFERRED",
                "Price unit follows the instrument convention; "
                "the response does not explicitly certify the unit.",
                severity="warning",
                stream_id=sid,
            )
        if weekend_labels:
            issue(
                "WEEKEND_DATE_LABELS",
                "Provider weekend dates are retained; confirm calendar and pricing methodology "
                "before treating every row as a trading session.",
                severity="warning",
                stream_id=sid,
            )
        if large_gaps:
            issue(
                "DAILY_GAP_REVIEW",
                "Large calendar-time gaps need a provider/session review; "
                "this is not a verified missing trading-session count.",
                severity="warning",
                stream_id=sid,
            )
        streams.append(
            StreamInventory(
                stream_id=sid,
                identity=identity,
                record_versions=len(records),
                unique_observations=len(resolved),
                extra_versions=len(records) - len(resolved),
                first_observed_at=first.observed_at,
                last_observed_at=last.observed_at,
                last_available_at=max(r.provenance.available_at for r in records),
                age_hours=age,
                freshness_limit_hours=limit,
                missing_values=missing,
                missing_fraction=missing_fraction,
                retrieval_time_only_versions=retrieval_only,
                daily_gap_count=large_gaps,
                largest_gap_hours=max(gaps) if gaps else None,
                date_only_prices=date_only_prices,
                weekend_date_labels=weekend_labels,
            )
        )
    for expected in policy.required_streams:
        filters = expected.model_dump(exclude_none=True, exclude={"min_observations"})
        matches = [
            stream
            for stream in streams
            if all(stream.identity.get(k) == v for k, v in filters.items())
        ]
        if not any(stream.unique_observations >= expected.min_observations for stream in matches):
            issue(
                "REQUIRED_STREAM_MISSING",
                "No single matching stream meets the required "
                f"observation count: {canonical(filters)}.",
            )
    status = (
        "fail" if any(i.severity == "error" for i in issues) else ("warning" if issues else "pass")
    )
    data_mode = (
        "mixed"
        if len(flags) == 2
        else "synthetic"
        if flags == {True}
        else ("real" if flags == {False} else "empty")
    )
    return QualityReport(
        as_of=as_of,
        replay_mode=mode,
        status=status,
        data_mode=data_mode,
        policy_sha256=hashlib.sha256(
            canonical(policy.model_dump(mode="json")).encode()
        ).hexdigest(),
        total_records=total,
        valid_records=valid,
        eligible_records=eligible,
        excluded_by_time=excluded,
        streams=tuple(streams),
        issues=tuple(issues),
    )
