"""Reviewed official timing evidence, separate from economic values and actual releases."""

import hashlib
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, HttpUrl, model_validator

from .ingestion import provenance
from .models import CalendarRelease, Contract, Hash, NonEmpty, Timestamp, aware
from .storage import record_id

NY = ZoneInfo("America/New_York")
TEHRAN = ZoneInfo("Asia/Tehran")
DATASETS = {"schedule": "bls_reviewed_schedule_v1", "archive_header": "bls_reviewed_header_v1"}
SERIES = {"CPIAUCSL": "cpi", "UNRATE": "empsit"}


class TimingEntry(Contract):
    series_id: Literal["CPIAUCSL", "UNRATE"]
    reference_period: str = Field(pattern=r"^\d{4}-\d{2}$")
    announced_at: Timestamp
    evidence_note: NonEmpty = Field(max_length=1500)

    @model_validator(mode="after")
    def period_and_clock(self):
        reference = date.fromisoformat(self.reference_period + "-01")
        ny = self.announced_at.astimezone(NY)
        if self.announced_at.utcoffset() != ny.utcoffset() or self.announced_at.replace(
            tzinfo=None
        ) != ny.replace(tzinfo=None):
            raise ValueError("announced_at must use the actual New York offset for that date")
        if ny.date() < reference:
            raise ValueError("release cannot precede its reference period")
        return self


class ReleaseEvidence(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    source_url: HttpUrl
    captured_at: Timestamp
    capture_method: Literal["reviewed_web_extract"] = "reviewed_web_extract"
    timing_basis: Literal["schedule", "archive_header"]
    source_timezone: Literal["America/New_York"] = "America/New_York"
    timezone_evidence: NonEmpty
    caveats: tuple[NonEmpty, ...] = ()
    entries: tuple[TimingEntry, ...] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def source_and_identity(self):
        url = self.source_url
        if (
            url.scheme != "https"
            or url.host != "www.bls.gov"
            or url.query
            or url.fragment
            or url.username
            or url.password
            or url.port != 443
        ):
            raise ValueError("timing evidence must cite an ordinary official BLS HTTPS URL")
        seen = set()
        for entry in self.entries:
            family = SERIES[entry.series_id]
            if self.timing_basis == "schedule":
                allowed = f"/schedule/news_release/{family}.htm"
            else:
                allowed = (
                    f"/news.release/archives/{family}_{entry.announced_at.strftime('%m%d%Y')}.htm"
                )
                if entry.announced_at > self.captured_at:
                    raise ValueError("archived header cannot announce a future release")
            if url.path != allowed:
                raise ValueError("BLS URL does not match the series or archived release date")
            key = entry.series_id, entry.reference_period
            if key in seen:
                raise ValueError("duplicate reference period in timing evidence")
            seen.add(key)
        return self


def normalize_evidence(evidence, source, digest, retrieved):
    retrieved = aware(retrieved).astimezone(UTC)
    if source.source_id != "bls" or "calendar" not in source.layers:
        raise ValueError("timing evidence requires the BLS calendar source")
    if evidence.captured_at > retrieved:
        raise ValueError("evidence capture cannot follow local ingestion")
    records = []
    for index, entry in enumerate(evidence.entries):
        reference = datetime.fromisoformat(entry.reference_period + "-01T00:00:00+00:00")
        p = provenance(
            source,
            digest,
            f"entries:{index}",
            reference,
            retrieved,
            DATASETS[evidence.timing_basis],
            "release_event",
            None,
            entry.announced_at.isoformat(),
            timezone="America/New_York",
            transformations=(
                "reviewed_web_extract_v1",
                "operator_attested",
                "announced_time_only",
                "reference_month_start_label_utc",
            ),
        )
        p = type(p).model_validate({**p.model_dump(), "source_url": evidence.source_url})
        records.append(
            CalendarRelease(
                provenance=p,
                event_id=f"bls:{entry.series_id}:{entry.reference_period}",
                series_id=entry.series_id,
                reference_period=entry.reference_period,
                scheduled_at=entry.announced_at.astimezone(UTC),
                # Even an archived embargo header is not a measured delivery timestamp.
                actual_release_at=None,
                actual=None,
                previous=None,
                consensus=None,
            )
        )
    return records


def import_evidence(store, path, source, *, reviewed=False, retrieved_at=None):
    if not reviewed:
        raise ValueError("review the official page and attest with --reviewed")
    content = Path(path).read_bytes()
    if len(content) > 1_000_000:
        raise ValueError("timing evidence exceeds 1 MB")
    evidence = ReleaseEvidence.model_validate_json(content)
    digest = store.put_raw(content)
    records = normalize_evidence(evidence, source, digest, retrieved_at or datetime.now(UTC))
    return store.put(records)


class CalendarItem(Contract):
    series_id: NonEmpty
    reference_period: NonEmpty
    announced_at: Timestamp
    new_york_time: Timestamp
    tehran_time: Timestamp
    timing_basis: Literal["schedule", "archive_header"]
    evidence_captured_at: Timestamp
    evidence_age_hours: float
    stale_evidence: bool
    record_id: Hash
    source_url: HttpUrl
    caveats: tuple[str, ...]


class CalendarContext(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    as_of: Timestamp
    horizon_days: int
    max_evidence_age_hours: float
    eligible_events: int
    upcoming: tuple[CalendarItem, ...]
    status: Literal["scheduled_events", "no_upcoming_evidence", "stale_evidence"]
    limitations: tuple[str, ...] = (
        "Stored schedule snapshot; updates and cancellations require another source review.",
        "Announced/embargo times do not establish actual delivery or first-release values.",
        "No economic value or FRED availability timestamp is changed by calendar evidence.",
    )


def calendar_context(store, as_of, horizon_days=90, max_age_hours=168):
    as_of = aware(as_of).astimezone(UTC)
    if not 1 <= horizon_days <= 366 or not 0 < max_age_hours <= 8760:
        raise ValueError("invalid calendar horizon or evidence age limit")
    grouped, raw = defaultdict(list), {}
    for r in store.read("calendar_release", as_of):
        p = r.provenance
        if p.source_id != "bls" or p.dataset not in DATASETS.values():
            continue
        if p.synthetic or p.unit != "release_event" or p.currency is not None:
            raise ValueError("incompatible calendar stream")
        if p.raw_sha256 not in raw:
            content = (store.root / "raw" / p.raw_sha256).read_bytes()
            if hashlib.sha256(content).hexdigest() != p.raw_sha256:
                raise ValueError("calendar raw evidence hash mismatch")
            raw[p.raw_sha256] = ReleaseEvidence.model_validate_json(content)
        evidence = raw[p.raw_sha256]
        # Reconcile the timing fields to the reviewed extraction, including the source URL.
        field, index = p.raw_record_id.split(":")
        if field != "entries" or not index.isdigit() or int(index) >= len(evidence.entries):
            raise ValueError("invalid calendar evidence pointer")
        entry = evidence.entries[int(index)]
        if (
            r.actual is not None
            or r.actual_release_at is not None
            or r.previous is not None
            or r.consensus is not None
            or r.consensus_as_of is not None
            or r.series_id != entry.series_id
            or r.reference_period != entry.reference_period
            or r.scheduled_at != entry.announced_at
            or str(p.source_url) != str(evidence.source_url)
            or p.dataset != DATASETS[evidence.timing_basis]
            or p.observed_at != datetime.fromisoformat(r.reference_period + "-01T00:00:00+00:00")
            or p.original_timestamp != entry.announced_at.isoformat()
            or p.original_timezone != "America/New_York"
            or p.availability_basis != "retrieval_time"
            or evidence.captured_at > p.retrieved_at
            or r.event_id != f"bls:{r.series_id}:{r.reference_period}"
        ):
            raise ValueError("calendar record differs from reviewed evidence")
        grouped[(r.series_id, r.reference_period)].append((r, evidence))
    upcoming = []
    for versions in grouped.values():
        # Capture time prevents importing an older extract later from undoing a newer schedule.
        best = max(e.captured_at for _, e in versions)
        winners = [pair for pair in versions if pair[1].captured_at == best]
        if len({r.scheduled_at for r, _ in winners}) > 1:
            raise ValueError("conflicting latest calendar versions")
        r, evidence = min(winners, key=lambda pair: record_id(pair[0]))
        if not as_of < r.scheduled_at <= as_of + timedelta(days=horizon_days):
            continue
        age = (as_of - evidence.captured_at).total_seconds() / 3600
        upcoming.append(
            CalendarItem(
                series_id=r.series_id,
                reference_period=r.reference_period,
                announced_at=r.scheduled_at,
                new_york_time=r.scheduled_at.astimezone(NY),
                tehran_time=r.scheduled_at.astimezone(TEHRAN),
                timing_basis=evidence.timing_basis,
                evidence_captured_at=evidence.captured_at,
                evidence_age_hours=age,
                stale_evidence=age > max_age_hours,
                record_id=record_id(r),
                source_url=evidence.source_url,
                caveats=evidence.caveats,
            )
        )
    return CalendarContext(
        as_of=as_of,
        horizon_days=horizon_days,
        max_evidence_age_hours=max_age_hours,
        eligible_events=len(grouped),
        upcoming=tuple(sorted(upcoming, key=lambda x: x.announced_at)),
        status="no_upcoming_evidence"
        if not upcoming
        else ("stale_evidence" if any(x.stale_evidence for x in upcoming) else "scheduled_events"),
    )
