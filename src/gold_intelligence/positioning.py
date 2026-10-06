"""As-known COT context with whole-capture reconciliation and explicit weekly gaps."""

import hashlib
import math
import os
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator

from . import __version__
from .cftc import API, DATASET, GROUPS, MARKET, CotCapture, capture_records, raw_json
from .models import Contract, Hash, Timestamp, aware
from .registry import validate_record_source
from .storage import canonical, record_id

NAMES = {
    "producer_merchant_processor_user": "تولیدکننده / بازرگان / پردازشگر / مصرف‌کننده",
    "swap_dealer": "معامله‌گران سوآپ",
    "managed_money": "مدیران سرمایه",
    "other_reportable": "سایر گزارش‌دهندگان",
    "nonreportable": "موقعیت‌های غیرگزارش‌شونده",
}


class CategoryPosition(Contract):
    category: Literal[
        "producer_merchant_processor_user",
        "swap_dealer",
        "managed_money",
        "other_reportable",
        "nonreportable",
    ]
    long: int = Field(ge=0)
    short: int = Field(ge=0)
    spreading: int | None = Field(ge=0)
    net: int
    net_percent_open_interest: float | None
    net_change_7d: int | None
    record_id: Hash


class WeeklyPosition(Contract):
    observed_date: date
    known_at: Timestamp
    capture_sha256: Hash
    open_interest: int = Field(ge=0)
    delta_status: Literal["first_observation", "seven_day_pair", "irregular_interval"]
    previous_observed_date: date | None
    open_interest_change_7d: int | None
    categories: tuple[CategoryPosition, ...]


class PositioningContext(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    generated_at: Timestamp
    as_of: Timestamp
    software_version: str
    source_id: Literal["cftc_disaggregated"] = "cftc_disaggregated"
    source_url: Literal["https://publicreporting.cftc.gov/resource/72hh-3qpy.json"] = API
    dataset: Literal["cftc_disaggregated_futures_only_gold_v1"] = DATASET
    market_code: Literal["088691"] = MARKET
    report_type: Literal["disaggregated_futures_only"] = "disaggregated_futures_only"
    unit: Literal["contracts_of_100_troy_ounces"] = "contracts_of_100_troy_ounces"
    max_age_days: int = Field(ge=1, le=365)
    status: Literal["descriptive_only", "stale", "no_data"]
    latest_observation_age_days: int | None
    eligible_captures: int = Field(ge=0)
    eligible_record_versions: int = Field(ge=0)
    superseded_record_versions: int = Field(ge=0)
    source_registry_sha256: Hash
    fingerprint: Hash
    weeks: tuple[WeeklyPosition, ...]
    irregular_intervals: tuple[tuple[date, date], ...]
    non_tuesday_labels: tuple[date, ...]
    historical_release_ready: Literal[False] = False
    daily_backtest_ready: Literal[False] = False
    limitations: tuple[str, ...] = (
        "COMEX gold futures across maturities; not spot XAU/USD or futures-and-options combined.",
        "Dates label positions; UTC midnight is a storage convention, not an observation instant.",
        "Availability is retrieval-bound; Tuesday/Friday convention does not prove release time.",
        "Current downloaded history; early backfill uses retrospective group classifications.",
        "Classifications can change; net changes are not cash flows, trader counts or signals.",
        "Spreading is not separately reported for producers or nonreportables; null is not zero.",
        "Only exact seven-day pairs receive deltas; other intervals require review.",
        "Freshness uses date age and a configured threshold, not an official release SLA.",
        "Revision markers/counts detect visible API changes; no provider snapshot token.",
    )

    @model_validator(mode="after")
    def consistent_context(self):
        # Saved bundles can verify arithmetic without access to the raw store.
        # Reordering is harmless: date and category are the semantic identities.
        weeks = sorted(self.weeks, key=lambda w: w.observed_date)
        if len({w.observed_date for w in weeks}) != len(weeks):
            raise ValueError("duplicate positioning observation date")
        identifiers = [g.record_id for w in weeks for g in w.categories]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("duplicate positioning record evidence")
        if self.superseded_record_versions != self.eligible_record_versions - len(identifiers):
            raise ValueError("positioning version counts disagree")
        if bool(weeks) != bool(self.eligible_captures) or (
            not weeks and self.eligible_record_versions
        ):
            raise ValueError("positioning capture counts disagree")
        if (
            self.eligible_record_versions % 5
            or self.eligible_captures > self.eligible_record_versions // 5
        ):
            raise ValueError("positioning captures must contain complete five-group dates")
        if len({w.capture_sha256 for w in weeks}) > self.eligible_captures:
            raise ValueError("selected positioning captures exceed eligible captures")
        previous = None
        irregular = []
        for week in weeks:
            if (
                week.observed_date > week.known_at.astimezone(UTC).date()
                or week.known_at > self.as_of
            ):
                raise ValueError("positioning evidence exceeds its cutoff or predates observation")
            groups = {g.category: g for g in week.categories}
            if set(groups) != set(GROUPS) or len(week.categories) != len(GROUPS):
                raise ValueError("positioning requires all five unique categories")
            exact = previous is not None and (week.observed_date - previous.observed_date).days == 7
            if previous and not exact:
                irregular.append((previous.observed_date, week.observed_date))
            status = (
                "seven_day_pair"
                if exact
                else ("irregular_interval" if previous else "first_observation")
            )
            if (
                week.delta_status != status
                or week.previous_observed_date != (previous.observed_date if previous else None)
                or week.open_interest_change_7d
                != (week.open_interest - previous.open_interest if exact else None)
            ):
                raise ValueError("positioning interval or OI delta disagrees with history")
            prior = {g.category: g for g in previous.categories} if previous else {}
            oi = week.open_interest
            for name, group in groups.items():
                if (group.spreading is None) != (GROUPS[name][2] is None):
                    raise ValueError(
                        "positioning spreading must preserve separately reported status"
                    )
                if (
                    group.net != group.long - group.short
                    or max(group.long, group.short, group.spreading or 0) > oi
                ):
                    raise ValueError("positioning net or position bounds disagree")
                share = group.net_percent_open_interest
                if (oi == 0 and share is not None) or (
                    oi != 0
                    and (
                        share is None
                        or not math.isclose(share, 100 * group.net / oi, abs_tol=1e-10)
                    )
                ):
                    raise ValueError("positioning net/OI share disagrees")
                if group.net_change_7d != (group.net - prior[name].net if exact else None):
                    raise ValueError("positioning net delta disagrees")
            if any(
                sum(getattr(g, side) + (g.spreading or 0) for g in groups.values()) != oi
                for side in ("long", "short")
            ):
                raise ValueError("positioning groups do not reconcile to open interest")
            previous = week
        if (
            tuple(irregular) != self.irregular_intervals
            or tuple(w.observed_date for w in weeks if w.observed_date.weekday() != 1)
            != self.non_tuesday_labels
        ):
            raise ValueError("positioning calendar profile disagrees")
        age = (self.as_of.astimezone(UTC).date() - weeks[-1].observed_date).days if weeks else None
        status = (
            "no_data"
            if age is None
            else ("stale" if age > self.max_age_days else "descriptive_only")
        )
        if self.latest_observation_age_days != age or self.status != status:
            raise ValueError("positioning freshness summary disagrees")
        return self


def positioning_context(store, registry, as_of, max_age_days=14):
    as_of = aware(as_of).astimezone(UTC)
    if type(max_age_days) is not int or not 1 <= max_age_days <= 365:
        raise ValueError("positioning max age must be an integer from 1 to 365 days")
    source = registry.get("cftc_disaggregated")
    captures = defaultdict(list)
    for record in store.read("positioning", as_of, "system"):
        if record.provenance.source_id == source.source_id:
            validate_record_source(record, registry)
            captures[record.provenance.raw_sha256].append(record)
    candidates = defaultdict(list)
    for digest, actual in sorted(captures.items()):
        capture = CotCapture.model_validate_json(raw_json(store, digest))
        if capture.retrieved_at > as_of:
            raise ValueError("normalized CFTC availability precedes its raw capture")
        expected = capture_records(store, source, capture, digest)
        if {record_id(r) for r in actual} != {record_id(r) for r in expected}:
            raise ValueError("CFTC capture has missing, altered or incompatible normalized records")
        by_day = defaultdict(list)
        for record in expected:
            by_day[record.provenance.observed_at.date()].append(record)
        for day, records in by_day.items():
            candidates[day].append((capture.retrieved_at, digest, records))
    weeks = []
    irregular = []
    previous = None
    selected_ids = []
    for day, versions in sorted(candidates.items()):
        latest_time = max(v[0] for v in versions)
        latest = [v for v in versions if v[0] == latest_time]
        if len(latest) != 1:
            raise ValueError("conflicting CFTC captures at the same retrieval time")
        known, digest, records = latest[0]
        by_category = {r.category: r for r in records}
        oi = records[0].open_interest
        exact_week = previous is not None and day - previous.observed_date == timedelta(days=7)
        previous_groups = {g.category: g for g in previous.categories} if previous else {}
        if previous is not None and not exact_week:
            irregular.append((previous.observed_date, day))
        categories = tuple(
            CategoryPosition(
                category=category,
                long=r.long,
                short=r.short,
                spreading=r.spreading,
                net=r.net,
                net_percent_open_interest=100 * r.net / oi if oi else None,
                net_change_7d=r.net - previous_groups[category].net if exact_week else None,
                record_id=record_id(r),
            )
            for category in GROUPS
            for r in (by_category[category],)
        )
        selected_ids.extend(g.record_id for g in categories)
        previous = WeeklyPosition(
            observed_date=day,
            known_at=known,
            capture_sha256=digest,
            open_interest=oi,
            delta_status="seven_day_pair"
            if exact_week
            else ("irregular_interval" if previous else "first_observation"),
            previous_observed_date=previous.observed_date if previous else None,
            open_interest_change_7d=oi - previous.open_interest if exact_week else None,
            categories=categories,
        )
        weeks.append(previous)
    age = (as_of.date() - weeks[-1].observed_date).days if weeks else None
    registry_hash = hashlib.sha256(canonical(source.model_dump(mode="json")).encode()).hexdigest()
    eligible = sum(len(records) for records in captures.values())
    identity = {
        "as_of": as_of.isoformat(),
        "max_age_days": max_age_days,
        "software_version": __version__,
        "source_registry_sha256": registry_hash,
        "selected_ids": sorted(selected_ids),
        "eligible_captures": sorted(captures),
    }
    return PositioningContext(
        generated_at=datetime.now(UTC),
        as_of=as_of,
        software_version=__version__,
        max_age_days=max_age_days,
        status="no_data"
        if age is None
        else ("stale" if age > max_age_days else "descriptive_only"),
        latest_observation_age_days=age,
        eligible_captures=len(captures),
        eligible_record_versions=eligible,
        superseded_record_versions=eligible - len(selected_ids),
        source_registry_sha256=registry_hash,
        fingerprint=hashlib.sha256(canonical(identity).encode()).hexdigest(),
        weeks=tuple(weeks),
        irregular_intervals=tuple(irregular),
        non_tuesday_labels=tuple(w.observed_date for w in weeks if w.observed_date.weekday() != 1),
    )


def render_positioning(report):
    state = {"no_data": "بدون دادهٔ مجاز", "stale": "دادهٔ قدیمی", "descriptive_only": "توصیفی"}
    lines = [
        "# موقعیت معامله‌گران طلای COMEX — گزارش COT",
        "",
        f"زمان برش: `{report.as_of.isoformat()}`؛ وضعیت: **{state[report.status]}**.",
        "",
        "دامنه: گزارش تفکیکی، فقط آتی، تمام سررسیدها؛ هر قرارداد ۱۰۰ اونس تروا.",
        "قیمت نقدی XAU/USD، جریان پول یا توصیهٔ معامله از این جدول استخراج نمی‌شود.",
        "",
        f"تاریخ‌های مشاهده: {len(report.weeks):,}؛ ثبت‌های دریافت: {report.eligible_captures}؛ "
        f"نسخه‌های کنارگذاشته‌شده: {report.superseded_record_versions:,}.",
        f"فاصله‌های غیرهفت‌روزه: {len(report.irregular_intervals)}؛ "
        f"برچسب‌های غیرسه‌شنبه: {len(report.non_tuesday_labels)}. این موارد نیازمند بررسی‌اند.",
        "",
    ]
    if report.weeks:
        latest = max(report.weeks, key=lambda w: w.observed_date)
        first = min(w.observed_date for w in report.weeks)
        lines.extend(
            [
                f"پوشش مشاهده: {first} تا {latest.observed_date}.",
                f"آخرین مشاهده: **{latest.observed_date}**؛ سن مشاهده: "
                f"{report.latest_observation_age_days} روز؛ "
                f"آستانهٔ داخلی: {report.max_age_days} روز.",
                f"زمان دریافت این نسخه: `{latest.known_at.isoformat()}`؛ "
                "زمان انتشار تاریخی نامعلوم.",
                f"قراردادهای باز (OI): **{latest.open_interest:,}**؛ "
                f"وضعیت مقایسهٔ هفت‌روزه: `{latest.delta_status}`.",
                "",
                "| گروه | خرید | فروش | اسپرد | خالص | خالص / OI، درصد | تغییر خالص هفت‌روزه |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for group in sorted(latest.categories, key=lambda g: list(NAMES).index(g.category)):
            spread = "تفکیک نشده" if group.spreading is None else f"{group.spreading:,}"
            share = (
                "تعریف‌نشده"
                if group.net_percent_open_interest is None
                else (f"{group.net_percent_open_interest:.2f}")
            )
            delta = "محاسبه نشده" if group.net_change_7d is None else f"{group.net_change_7d:+,}"
            lines.append(
                f"| {NAMES[group.category]} | {group.long:,} | {group.short:,} | {spread} | "
                f"{group.net:+,} | {share} | {delta} |"
            )
    lines.extend(
        [
            "",
            "## روش خواندن و محدودیت",
            "",
            "خالص برابر خرید منهای فروش است. اسپرد در جمع هر دو سمت منظور می‌شود؛ "
            "جمع هر سمت، با موقعیت‌های غیرگزارش‌شونده، باید برابر OI باشد.",
            "",
            "دریافت امروز، آگاهی تاریخی ایجاد نمی‌کند. نسخه‌های موجود در زمان برش انتخاب می‌شوند؛ "
            "دسته‌بندی معامله‌گران ممکن است تغییر کند؛ "
            "تاریخچهٔ اولیه با دسته‌بندی بعدی ساخته شده است.",
            "",
            "تغییر هفت‌روزه فقط برای دو تاریخ دقیقاً هفت روز فاصله‌دار محاسبه می‌شود. "
            "تاریخ‌های دیگر پر نمی‌شوند. تغییر گروه می‌تواند حاصل تغییر طبقه‌بندی نیز باشد.",
            "",
            "JSON همراه، تمام هفته‌ها، فاصله‌ها، شناسهٔ رکوردها و هش زنجیرهٔ شواهد خام را دارد. "
            "هش، تمامیت بایت‌های ذخیره‌شده را بررسی می‌کند؛ اصالت اقتصادی داده را اثبات نمی‌کند.",
            "",
            f"اثر انگشت: `{report.fingerprint}`",
            "",
            f"[دادهٔ رسمی CFTC]({API}) · "
            "[تعریف گروه‌ها و تاریخچه](https://www.cftc.gov/MarketReports/CommitmentsofTraders/DisaggregatedExplanatoryNotes/index.htm)",
            "",
        ]
    )
    return "\n".join(lines)


def write_positioning(report, output_dir):
    """Publish a new local directory only after both artifacts are written."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    name = f"positioning-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid4().hex[:8]}"
    stage = output_dir / f".{name}.tmp"
    target = output_dir / name
    stage.mkdir()
    try:
        (stage / "positioning.json").write_text(
            report.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        (stage / "positioning.fa.md").write_text(render_positioning(report), encoding="utf-8")
        os.replace(stage, target)
    finally:
        if stage.exists():
            for path in stage.iterdir():
                path.unlink()
            stage.rmdir()
    return target
