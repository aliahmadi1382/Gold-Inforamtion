"""Bind reviewed archive values to their document and compare exact-date FRED vintages.

Archive embargo headers are retained as evidence, never promoted to measured delivery
times. Both archive extracts and FRED observations keep retrieval-time availability.
"""

import hashlib
import json
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, model_validator

from . import __version__
from .brief import cell
from .comparison import latest_periods
from .ingestion import provenance
from .models import Contract, Hash, NonEmpty, Observation, Timestamp, aware
from .monthly_research import shift_month
from .registry import validate_record_source
from .release_calendar import NY, TEHRAN, ReleaseEvidence, TimingEntry
from .storage import canonical, record_id

DATASET = "bls_reviewed_release_values_v1"
Metric = Literal["cpi_all_items_sa_mom", "unemployment_rate_sa"]
METRICS = {
    "cpi_all_items_sa_mom": {
        "series": "BLS_CPI_U_SA_MOM",
        "fred": "CPIAUCSL",
        "unit": "percent_change_mom_sa",
        "fred_unit": "index_1982_1984_100_sa",
        "label": "تورم ماهانهٔ CPI-U تعدیل‌شده",
    },
    "unemployment_rate_sa": {
        "series": "BLS_UNRATE_SA",
        "fred": "UNRATE",
        "unit": "percent_sa",
        "fred_unit": "percent_sa",
        "label": "نرخ بیکاری کل، تعدیل‌شده",
    },
}


class PublishedValue(Contract):
    reference_period: str = Field(pattern=r"^\d{4}-\d{2}$")
    value: float
    unit: Literal["percent_change_mom_sa", "percent_sa"]
    decimal_places: Literal[1] = 1
    locator: NonEmpty = Field(max_length=500)
    review_note: NonEmpty = Field(max_length=1500)


class ReleaseValueEvidence(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    source_url: HttpUrl
    captured_at: Timestamp
    capture_method: Literal["reviewed_web_extract"] = "reviewed_web_extract"
    metric: Metric
    release_id: str = Field(pattern=r"^USDL-\d{2}-\d{4}$")
    headline_period: str = Field(pattern=r"^\d{4}-\d{2}$")
    announced_at: Timestamp
    timing_basis: Literal["archive_embargo_header"] = "archive_embargo_header"
    timezone_evidence: NonEmpty
    document_status: Literal["archive_as_captured", "reissued"]
    reissued_on: date | None = None
    revision_note: NonEmpty
    caveats: tuple[NonEmpty, ...] = ()
    values: tuple[PublishedValue, ...] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def identity_and_units(self):
        spec = METRICS[self.metric]
        # Reuse the reviewed archive URL, New York/DST and reference-clock rules.
        ReleaseEvidence(
            source_url=self.source_url,
            captured_at=self.captured_at,
            timing_basis="archive_header",
            timezone_evidence=self.timezone_evidence,
            entries=(
                TimingEntry(
                    series_id=spec["fred"],
                    reference_period=self.headline_period,
                    announced_at=self.announced_at,
                    evidence_note="Value-document clock validation",
                ),
            ),
        )
        headline = date.fromisoformat(self.headline_period + "-01")
        if self.announced_at.date() < shift_month(headline, 1):
            raise ValueError("monthly release must follow the completed headline period")
        if self.release_id.split("-")[1] != self.announced_at.strftime("%y"):
            raise ValueError("release identifier year differs from the header")
        if (self.document_status == "reissued") != (self.reissued_on is not None):
            raise ValueError("reissued documents require an explicit reissue date")
        if self.reissued_on and not (
            self.announced_at.date() <= self.reissued_on <= self.captured_at.astimezone(NY).date()
        ):
            raise ValueError("reissue date lies outside the header/capture interval")
        seen = set()
        for entry in self.values:
            period = date.fromisoformat(entry.reference_period + "-01")
            if period not in {headline, shift_month(headline, -1)}:
                raise ValueError("only headline and immediately preceding periods are supported")
            if period in seen:
                raise ValueError("duplicate period in release value evidence")
            seen.add(period)
            if entry.unit != spec["unit"]:
                raise ValueError(
                    "metric and unit differ; CPI level/MoM/YoY are not interchangeable"
                )
            decimal = Decimal(str(entry.value))
            try:
                rounded = decimal.quantize(Decimal("0.1"))
            except InvalidOperation:
                raise ValueError("published value exceeds supported precision") from None
            if decimal != rounded:
                raise ValueError("published value must preserve the reviewed one-decimal precision")
            if (self.metric == "unemployment_rate_sa" and not 0 <= entry.value <= 100) or (
                self.metric == "cpi_all_items_sa_mom" and entry.value <= -100
            ):
                raise ValueError("published value outside the metric domain")
        if headline not in seen:
            raise ValueError("headline period value is required")
        return self


def normalize_values(evidence, source, digest, retrieved):
    retrieved = aware(retrieved).astimezone(UTC)
    if source.source_id != "bls" or "macro" not in source.layers:
        raise ValueError("release values require the BLS macro source")
    if evidence.captured_at > retrieved:
        raise ValueError("archive capture cannot follow ingestion")
    spec = METRICS[evidence.metric]
    records = []
    for index, entry in enumerate(evidence.values):
        p = provenance(
            source,
            digest,
            f"values:{index}",
            datetime.fromisoformat(entry.reference_period + "-01T00:00:00+00:00"),
            retrieved,
            DATASET,
            entry.unit,
            None,
            evidence.announced_at.isoformat(),
            timezone="America/New_York",
            transformations=(
                "reviewed_release_value_v1",
                "operator_attested",
                "archive_as_captured",
            ),
        )
        p = type(p).model_validate({**p.model_dump(), "source_url": evidence.source_url})
        records.append(
            Observation(
                provenance=p,
                layer="macro",
                series_id=spec["series"],
                value=entry.value,
                dimensions={
                    "metric": evidence.metric,
                    "release_id": evidence.release_id,
                    "headline_period": evidence.headline_period,
                    "announced_at": evidence.announced_at.isoformat(),
                    "captured_at": evidence.captured_at.isoformat(),
                    "document_status": evidence.document_status,
                    "reissued_on": str(evidence.reissued_on) if evidence.reissued_on else "unknown",
                    "period_role": "headline"
                    if entry.reference_period == evidence.headline_period
                    else "previous_in_document",
                },
            )
        )
    return records


def import_release_values(store, path, source, *, reviewed=False, retrieved_at=None):
    if not reviewed:
        raise ValueError("review the official archive and attest with --reviewed")
    content = Path(path).read_bytes()
    if len(content) > 1_000_000:
        raise ValueError("release-value evidence exceeds 1 MB")
    evidence = ReleaseValueEvidence.model_validate_json(content)
    return store.put(
        normalize_values(
            evidence, source, store.put_raw(content), retrieved_at or datetime.now(UTC)
        )
    )


def read_blob(store, digest, cache):
    if digest not in cache:
        content = (store.root / "raw" / digest).read_bytes()
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("release comparison raw hash mismatch")
        cache[digest] = content
    return cache[digest]


def document_versions(store, registry, records, cache):
    """Validate every eligible complete capture before selecting document versions."""
    bundles, grouped = {}, defaultdict(list)
    records = [
        r for r in records if r.provenance.source_id == "bls" and r.provenance.dataset == DATASET
    ]
    ids = {record_id(r) for r in records}
    for r in records:
        p = r.provenance
        validate_record_source(r, registry)
        key = p.raw_sha256, p.retrieved_at
        if key not in bundles:
            evidence = ReleaseValueEvidence.model_validate_json(
                read_blob(store, p.raw_sha256, cache)
            )
            expected = normalize_values(evidence, registry.get("bls"), p.raw_sha256, p.retrieved_at)
            expected_ids = {record_id(row) for row in expected}
            if not expected_ids <= ids:
                raise ValueError("release document is incomplete or differs from reviewed evidence")
            bundles[key] = evidence, expected
            grouped[str(evidence.source_url)].append((evidence, expected))
        if record_id(r) not in {record_id(row) for row in bundles[key][1]}:
            raise ValueError("release value differs from reviewed evidence")
    return grouped


def selected_documents(store, registry, records, cache):
    """Select entire latest captured documents; dropped rows must not reappear."""
    grouped = document_versions(store, registry, records, cache)
    selected = []
    for versions in grouped.values():
        latest_capture = max(e.captured_at for e, _ in versions)
        winners = [(e, rs) for e, rs in versions if e.captured_at == latest_capture]
        if len({canonical(e.model_dump(mode="json")) for e, _ in winners}) > 1:
            raise ValueError("conflicting same-capture release documents")
        selected.append(min(winners, key=lambda pair: tuple(record_id(r) for r in pair[1])))
    return sorted(selected, key=lambda pair: (pair[0].announced_at, pair[0].metric))


class ValueComparison(Contract):
    status: Literal[
        "matches_display", "differs_display", "rounding_boundary", "missing_period", "missing_value"
    ]
    value: float | None = None
    difference_from_document: float | None = None
    record_ids: tuple[Hash, ...] = ()
    vintage_date: date | None
    transformation: Literal["native_unemployment_rate", "100*(current_CPI/prior_CPI-1)"]


class ReleaseValueLink(Contract):
    reference_period: str
    period_role: Literal["headline", "previous_in_document"]
    document_value: float
    unit: str
    locator: str
    document_record_id: Hash
    release_date_vintage: ValueComparison
    current_revision: ValueComparison


class ReleaseDocument(Contract):
    source_url: HttpUrl
    release_id: str
    metric: Metric
    headline_period: str
    announced_at: Timestamp
    tehran_time: Timestamp
    captured_at: Timestamp
    document_status: Literal["archive_as_captured", "reissued"]
    reissued_on: date | None
    revision_note: str
    caveats: tuple[str, ...]
    values: tuple[ReleaseValueLink, ...]
    first_release_verified: Literal[False] = False


class ReleaseValueReport(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    generated_at: Timestamp
    as_of: Timestamp
    software_version: str
    fingerprint: Hash
    status: Literal["compared", "incomplete", "no_evidence"]
    documents: tuple[ReleaseDocument, ...]
    intraday_replay_ready: Literal[False] = False
    limitations: tuple[str, ...] = (
        "Official archive values are manually reviewed extracts, not original HTML bytes.",
        "An archive may have been reissued; the capture date identifies the inspected version.",
        "An embargo header and a date-only FRED vintage do not prove intraday delivery time.",
        "Same-day FRED consistency is not independent confirmation or proof of first release.",
        "CPI MoM uses two index levels from the same vintage and compares at display precision.",
        "Current-revision differences are not release surprises; no consensus input is present.",
        "Historical availability is not backdated; replay remains retrieval bounded.",
    )


def validate_fred_raw(store, record, vintage, cache):
    p = record.provenance
    payload = json.loads(read_blob(store, p.raw_sha256, cache))
    parts = p.raw_record_id.split(":")
    if len(parts) != 2 or parts[0] != "observations" or not parts[1].isdigit():
        raise ValueError("invalid FRED evidence pointer")
    rows = payload.get("observations", [])
    index = int(parts[1])
    if index >= len(rows):
        raise ValueError("FRED evidence pointer out of range")
    row = rows[index]
    if vintage and any(
        payload.get(k) != vintage.isoformat() for k in ("realtime_start", "realtime_end")
    ):
        raise ValueError("FRED response does not establish the requested vintage date")
    value = None if row["value"] == "." else float(row["value"])
    if (
        record.value != value
        or p.observed_at != datetime.fromisoformat(row["date"] + "T00:00:00+00:00")
        or record.dimensions != {k: row[k] for k in ("realtime_start", "realtime_end")}
        or payload.get("units") != "lin"
    ):
        raise ValueError("FRED record differs from its native-unit raw observation")


def compare_value(store, registry, records, evidence, entry, vintage, cache):
    spec = METRICS[evidence.metric]
    period = date.fromisoformat(entry.reference_period + "-01")
    periods = [period]
    cpi = evidence.metric == "cpi_all_items_sa_mom"
    if cpi:
        periods.insert(0, shift_month(period, -1))
    candidates = []
    for r in records:
        p = r.provenance
        if p.source_id != "fred" or r.series_id != spec["fred"] or r.vintage_date != vintage:
            continue
        if p.observed_at.astimezone(UTC).date() not in periods:
            continue
        validate_record_source(r, registry)
        if (
            p.synthetic
            or r.layer != "macro"
            or p.dataset != spec["fred"]
            or p.unit != spec["fred_unit"]
            or p.currency is not None
            or str(p.source_url) != f"https://fred.stlouisfed.org/series/{spec['fred']}"
        ):
            raise ValueError("incompatible FRED comparison stream")
        candidates.append(r)
    selected = latest_periods(candidates)
    for r in selected:
        validate_fred_raw(store, r, vintage, cache)
    common = dict(
        vintage_date=vintage,
        record_ids=tuple(record_id(r) for r in selected),
        transformation="100*(current_CPI/prior_CPI-1)" if cpi else "native_unemployment_rate",
    )
    if len(selected) != len(periods):
        return ValueComparison(status="missing_period", **common)
    if any(r.value is None for r in selected):
        return ValueComparison(status="missing_value", **common)
    values = [Decimal(str(r.value)) for r in selected]
    if (cpi and any(v <= 0 for v in values)) or (not cpi and not 0 <= values[0] <= 100):
        raise ValueError("invalid FRED index/rate value")
    value = 100 * (values[1] / values[0] - 1) if cpi else values[0]
    difference = value - Decimal(str(entry.value))
    distance = abs(difference)
    half_unit = Decimal("0.05")
    status = (
        "rounding_boundary"
        if abs(distance - half_unit) <= Decimal("1e-10")
        else ("matches_display" if distance < half_unit else "differs_display")
    )
    return ValueComparison(
        status=status, value=float(value), difference_from_document=float(difference), **common
    )


def release_value_report(store, registry, as_of):
    as_of = aware(as_of).astimezone(UTC)
    records = [r for r in store.read("observation", as_of) if r.provenance.observed_at <= as_of]
    cache, documents, evidence_ids = {}, [], []
    for evidence, normalized in selected_documents(store, registry, records, cache):
        links = []
        for entry, record in zip(evidence.values, normalized, strict=True):
            vintage = compare_value(
                store, registry, records, evidence, entry, evidence.announced_at.date(), cache
            )
            current = compare_value(store, registry, records, evidence, entry, None, cache)
            evidence_ids += [record_id(record), *vintage.record_ids, *current.record_ids]
            links.append(
                ReleaseValueLink(
                    reference_period=entry.reference_period,
                    period_role="headline"
                    if entry.reference_period == evidence.headline_period
                    else "previous_in_document",
                    document_value=entry.value,
                    unit=entry.unit,
                    locator=entry.locator,
                    document_record_id=record_id(record),
                    release_date_vintage=vintage,
                    current_revision=current,
                )
            )
        documents.append(
            ReleaseDocument(
                source_url=evidence.source_url,
                release_id=evidence.release_id,
                metric=evidence.metric,
                headline_period=evidence.headline_period,
                announced_at=evidence.announced_at,
                tehran_time=evidence.announced_at.astimezone(TEHRAN),
                captured_at=evidence.captured_at,
                document_status=evidence.document_status,
                reissued_on=evidence.reissued_on,
                revision_note=evidence.revision_note,
                caveats=evidence.caveats,
                values=tuple(links),
            )
        )
    identity = {
        "version": __version__,
        "as_of": as_of.isoformat(),
        "record_ids": sorted(set(evidence_ids)),
    }
    incomplete = any(
        v.release_date_vintage.status != "matches_display" or v.current_revision.value is None
        for d in documents
        for v in d.values
    )
    return ReleaseValueReport(
        generated_at=datetime.now(UTC),
        as_of=as_of,
        software_version=__version__,
        fingerprint=hashlib.sha256(canonical(identity).encode()).hexdigest(),
        status="no_evidence" if not documents else ("incomplete" if incomplete else "compared"),
        documents=tuple(documents),
    )


def render_release_values(report):
    statuses = {
        "matches_display": "سازگار با دقت نمایش",
        "differs_display": "اختلاف در دقت نمایش",
        "rounding_boundary": "مرز گردکردن؛ نامعین",
        "missing_period": "نسخه/دوره موجود نیست",
        "missing_value": "مقدار مفقود",
    }

    def number(v):
        return "—" if v is None else f"{v:.4f}".rstrip("0").rstrip(".")

    lines = [
        "# اتصال مقدار اقتصادی به سند انتشار و نسخهٔ تاریخی",
        "",
        f"زمان برش: `{report.as_of.isoformat()}`؛ نسخه: {report.software_version}.",
        f"شناسهٔ بازتولید: `{report.fingerprint}`.",
        "",
        "این گزارش اعداد آرشیو رسمی را به سند مشخص و نسخهٔ روزانهٔ FRED وصل می‌کند. "
        "ساعت جدول، ساعت سرصفحهٔ سند است؛ زمان واقعی تحویل یا اولین دسترسی تأیید نشده است. "
        "داده‌ها همچنان زمان دسترسی برابر دریافت محلی دارند.",
        "",
        "CPI این گزارش درصد تغییر ماهانهٔ شاخص تعدیل‌شده است؛ سطح شاخص و تورم سالانه "
        "معیارهای دیگری هستند. نرخ بیکاری به درصد ثبت شده است. «قبلی در سند» مقدار "
        "ماه پیش در همین سند است و ممکن است با سند انتشار ماه قبل فرق کند.",
        "",
    ]
    if not report.documents:
        lines += ["برای این زمان برش سند واجد شرایطی موجود نیست.", ""]
    for d in report.documents:
        lines += [
            f"## {METRICS[d.metric]['label']}؛ {d.headline_period}",
            "",
            f"سند [{cell(d.release_id)}]({d.source_url})؛ ثبت شاهد: `{d.captured_at.isoformat()}`.",
            f"زمان سرصفحه در نیویورک: `{d.announced_at.isoformat()}`؛ "
            f"UTC: `{d.announced_at.astimezone(UTC).isoformat()}`؛ "
            f"تهران: `{d.tehran_time.isoformat()}`.",
            "",
            "وضعیت سند: "
            + (
                f"بازانتشار در {d.reissued_on}."
                if d.reissued_on
                else "آرشیو در زمان مشاهده؛ نسخهٔ اول تأیید نشده."
            ),
            cell(d.revision_note),
            "",
            "| دوره | نقش در سند | مقدار سند | نسخهٔ FRED در تاریخ سرصفحه | "
            "تطبیق تاریخی | نسخهٔ جاری | اختلاف جاری با سند |",
            "| --- | --- | ---: | ---: | --- | ---: | ---: |",
        ]
        for v in d.values:
            role = "دورهٔ اصلی" if v.period_role == "headline" else "قبلی در همین سند"
            lines.append(
                f"| {v.reference_period} | {role} | {v.document_value:.1f} | "
                f"{number(v.release_date_vintage.value)} | "
                f"{statuses[v.release_date_vintage.status]} | "
                f"{number(v.current_revision.value)} | "
                f"{number(v.current_revision.difference_from_document)} |"
            )
        lines += [
            "",
            "اختلاف‌ها به واحد درصد هستند؛ مقدارهای نمایشی جدول تا چهار رقم اعشار گرد شده‌اند.",
            "",
        ]
        for v in d.values:
            lines += [
                f"- شاهد {v.reference_period}: {cell(v.locator)}؛ رکورد `{v.document_record_id}`."
            ]
        lines += [f"- {cell(note)}" for note in d.caveats]
        lines.append("")
    lines += [
        "## روش خواندن و حدود نتیجه",
        "",
        "برای CPI، هر دو شاخص ماه جاری و قبل از یک تاریخ vintage گرفته می‌شوند. "
        "فرمول ۱۰۰ × (شاخص جاری ÷ شاخص قبلی − ۱) است. سازگاری به معنی اختلاف کمتر از "
        "۰٫۰۵ واحد درصد با عدد یک‌اعشاری سند است؛ مرز دقیق جدا علامت می‌خورد. "
        "شاخص‌های ورودی نیز گرد شده‌اند، بنابراین این تطبیق اثبات برابری اعداد منتشرنشده نیست.",
        "",
        "FRED و آرشیو در اینجا ریشهٔ آماری مشترک BLS دارند؛ توافق آن‌ها تأیید منبع مستقل نیست. "
        "تاریخ vintage دقت روز دارد و تطبیق عدد، ساعت اولین انتشار را اثبات نمی‌کند. "
        "بازانتشار و اصلاحات فصلی ممکن است نسخهٔ جاری را تغییر دهند.",
        "",
        "اختلاف نسخهٔ جاری با سند «غافلگیری خبر» نیست؛ برای غافلگیری به انتظار بازارِ "
        "ثبت‌شده پیش از انتشار نیاز است. در این مرحله انتظار بازار یا واکنش قابل معاملهٔ "
        "طلا محاسبه نشده است.",
        "",
        "JSON همراه، نسخهٔ هر سند، واحد، نتیجهٔ تطبیق، شناسهٔ تمام والدهای FRED و شاهد خام "
        "را نگه می‌دارد. این گزارش برای بررسی اتصال سند و نسخه است؛ بازپخش درون‌روزی آماده نیست.",
        "",
    ]
    return "\n".join(lines)
