"""Compose existing research engines at one cutoff and one SQLite read snapshot."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator

from . import __version__
from .brief import ISSUES, NAMES, STATUSES, UNITS, cell
from .macro import MacroContext, MacroPlan, macro_context
from .models import Contract, Hash, Timestamp, aware
from .monthly_research import (
    NAMES as MONTHLY_NAMES,
)
from .monthly_research import (
    REGIMES,
    STATUS_FA,
    MonthlyResearch,
    MonthlyResearchPlan,
    monthly_research,
    render_monthly_persian,
)
from .quality import QualityPolicy, QualityReport, assess
from .release_calendar import CalendarContext, calendar_context
from .release_values import ReleaseValueReport, release_value_report, render_release_values
from .revision_ledger import RevisionLedger, RevisionPlan, render_revision_ledger, revision_ledger
from .storage import canonical

PARTS = ("quality", "macro", "calendar", "monthly", "releases", "revisions")
LABELS = {
    "quality": "کنترل کیفیت",
    "price": "پوشش قیمت روزانه",
    "macro": "شاخص‌های کلان",
    "calendar": "تقویم انتشار",
    "monthly": "روابط ماهانه",
    "releases": "اتصال مقدار و سند",
    "revisions": "دفتر اصلاحیه‌ها",
}
STATES = {
    "available": "در دسترس در دامنهٔ تعریف‌شده",
    "limited": "دارای محدودیت",
    "missing": "فاقد شواهد کافی",
}
FILES = {
    "research-report.json",
    "research-report.fa.md",
    "details/quality.json",
    "details/macro.json",
    "details/calendar.json",
    "details/monthly-research.json",
    "details/monthly-research.fa.md",
    "details/release-values.json",
    "details/release-values.fa.md",
    "details/revision-ledger.json",
    "details/revision-ledger.fa.md",
}


class ReportSettings(Contract):
    macro_plan: MacroPlan
    quality_policy: QualityPolicy
    monthly_plan: MonthlyResearchPlan
    revision_plan: RevisionPlan
    calendar_horizon_days: int = Field(default=90, ge=1, le=366)
    calendar_max_evidence_age_hours: float = Field(default=168, gt=0, le=8760)


class ReportSection(Contract):
    key: Literal["quality", "price", "macro", "calendar", "monthly", "releases", "revisions"]
    status: Literal["available", "limited", "missing"]
    evidence_pointer: str


def price_streams(quality):
    return tuple(
        s
        for s in quality.streams
        if s.identity.get("kind") in {"price_close", "price_bar"}
        and s.identity.get("instrument") == "XAUUSD"
        and s.identity.get("timeframe") == "1d"
    )


def section_states(quality, macro, calendar, monthly, releases, revisions):
    prices = price_streams(quality)
    price_ids = {s.stream_id for s in prices}
    price_issues = any(i.stream_id in price_ids for i in quality.issues)
    common = [a for a in monthly.associations if a.population == "common"]
    states = [
        (
            "quality",
            "missing"
            if quality.eligible_records == 0
            else "available"
            if quality.status == "pass"
            else "limited",
            "/quality",
        ),
        (
            "price",
            "missing" if not prices else "limited" if price_issues else "available",
            "/quality/streams",
        ),
        (
            "macro",
            "available"
            if macro.status == "available"
            else "limited"
            if any(e.record_id for e in macro.entries)
            else "missing",
            "/macro",
        ),
        (
            "calendar",
            "available"
            if calendar.status == "scheduled_events"
            else "limited"
            if calendar.status == "stale_evidence"
            else "missing",
            "/calendar",
        ),
        (
            "monthly",
            "available"
            if common and all(a.status == "estimated" for a in common)
            else "limited"
            if any(a.status == "estimated" for a in common)
            else "missing",
            "/monthly",
        ),
        (
            "releases",
            "available"
            if releases.status == "compared"
            else "limited"
            if releases.documents
            else "missing",
            "/releases",
        ),
        (
            "revisions",
            "available"
            if revisions.status == "complete"
            else "limited"
            if revisions.captures
            else "missing",
            "/revisions",
        ),
    ]
    return tuple(ReportSection(key=k, status=s, evidence_pointer=p) for k, s, p in states)


def overall_status(sections, quality):
    if quality.status == "fail" or any(s.status == "missing" for s in sections):
        return "partial"
    return "with_limits" if any(s.status == "limited" for s in sections) else "compiled"


def semantic_payload(value):
    """Build clocks are volatile; evidence capture/retrieval clocks remain bound."""
    if isinstance(value, dict):
        return {k: semantic_payload(v) for k, v in value.items() if k != "generated_at"}
    if isinstance(value, list):
        return [semantic_payload(v) for v in value]
    return value


def fingerprint(payload):
    payload = {k: v for k, v in payload.items() if k != "fingerprint"}
    return hashlib.sha256(canonical(semantic_payload(payload)).encode()).hexdigest()


class ResearchReport(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    software_version: str
    generated_at: Timestamp
    as_of: Timestamp
    fingerprint: Hash
    registry_sha256: Hash
    settings: ReportSettings
    status: Literal["compiled", "with_limits", "partial"]
    sections: tuple[ReportSection, ...]
    quality: QualityReport
    macro: MacroContext
    calendar: CalendarContext
    monthly: MonthlyResearch
    releases: ReleaseValueReport
    revisions: RevisionLedger
    data_basis: Literal["stored_data_single_snapshot"] = "stored_data_single_snapshot"
    daily_backtest_ready: Literal[False] = False
    intraday_replay_ready: Literal[False] = False
    first_release_verified: Literal[False] = False

    @model_validator(mode="after")
    def consistent_bundle(self):
        parts = {name: getattr(self, name) for name in PARTS}
        if any(part.as_of != self.as_of for part in parts.values()):
            raise ValueError("report components must share exactly one cutoff")
        if any(
            getattr(part, "software_version", self.software_version) != self.software_version
            for part in parts.values()
        ):
            raise ValueError("report component software versions differ")
        if (
            self.macro.mode != "system"
            or self.macro.vintage is not None
            or self.quality.replay_mode != "system"
        ):
            raise ValueError("unified report requires current revisions in system replay mode")
        expected_policy = hashlib.sha256(
            canonical(self.settings.quality_policy.model_dump(mode="json")).encode()
        ).hexdigest()
        if self.quality.policy_sha256 != expected_policy:
            raise ValueError("quality policy differs from the report settings")
        if (
            self.monthly.plan != self.settings.monthly_plan
            or self.revisions.plan != self.settings.revision_plan
            or self.calendar.horizon_days != self.settings.calendar_horizon_days
            or self.calendar.max_evidence_age_hours != self.settings.calendar_max_evidence_age_hours
        ):
            raise ValueError("component plan differs from report settings")
        if tuple(e.series_id for e in self.macro.entries) != tuple(
            s.series_id for s in self.settings.macro_plan.series
        ):
            raise ValueError("macro scope differs from report settings")
        if self.sections != section_states(**parts) or self.status != overall_status(
            self.sections, self.quality
        ):
            raise ValueError("section summaries differ from component evidence")
        if self.fingerprint != fingerprint(self.model_dump(mode="json")):
            raise ValueError("unified report fingerprint mismatch")
        return self


def build_research_report(store, registry, settings, as_of):
    as_of = aware(as_of).astimezone(UTC)
    if store.db.in_transaction:
        raise ValueError("start the report outside an existing database transaction")
    store.db.execute("BEGIN")
    try:
        quality = assess(store, registry, as_of, settings.quality_policy)
        # Coverage gaps are publishable diagnostics. Integrity and mixed-data failures are not.
        fatal = {i.code for i in quality.issues if i.severity == "error"} - {
            "NO_ELIGIBLE_DATA",
            "REQUIRED_STREAM_MISSING",
        }
        if fatal:
            raise ValueError(
                "research report blocked by data integrity: " + ", ".join(sorted(fatal))
            )
        parts = dict(
            quality=quality,
            macro=macro_context(store, settings.macro_plan, as_of),
            calendar=calendar_context(
                store,
                as_of,
                settings.calendar_horizon_days,
                settings.calendar_max_evidence_age_hours,
            ),
            monthly=monthly_research(store, settings.monthly_plan, as_of),
            releases=release_value_report(store, registry, as_of),
            revisions=revision_ledger(store, registry, settings.revision_plan, as_of),
        )
        sections = section_states(**parts)
        payload = dict(
            schema_version="1.0.0",
            software_version=__version__,
            generated_at=datetime.now(UTC).isoformat(),
            as_of=as_of.isoformat(),
            registry_sha256=hashlib.sha256(
                canonical(registry.model_dump(mode="json")).encode()
            ).hexdigest(),
            settings=settings.model_dump(mode="json"),
            status=overall_status(sections, quality),
            sections=[s.model_dump(mode="json") for s in sections],
            **{k: v.model_dump(mode="json") for k, v in parts.items()},
            data_basis="stored_data_single_snapshot",
            daily_backtest_ready=False,
            intraday_replay_ready=False,
            first_release_verified=False,
        )
        # Pydantic JSON uses Z for UTC; bind that same canonical timestamp form.
        payload["generated_at"] = (
            datetime.fromisoformat(payload["generated_at"]).isoformat().replace("+00:00", "Z")
        )
        payload["as_of"] = as_of.isoformat().replace("+00:00", "Z")
        return ResearchReport.model_validate({**payload, "fingerprint": fingerprint(payload)})
    finally:
        store.db.rollback()


def number(value, places=3):
    return "—" if value is None else f"{value:,.{places}f}".rstrip("0").rstrip(".")


def render_research_report(report):
    label = {
        "compiled": "بخش‌ها در دامنهٔ خود در دسترس‌اند",
        "with_limits": "گزارش دارای محدودیت است",
        "partial": "بخشی از شواهد یا پوشش مورد نیاز موجود نیست",
    }[report.status]
    macro_count = sum(e.status == "available" for e in report.macro.entries)
    common = [a for a in report.monthly.associations if a.population == "common"]
    estimated = sum(a.status == "estimated" for a in common)
    revisions = report.revisions
    lines = [
        "# گزارش یکپارچهٔ پژوهش طلا",
        "",
        f"**{label}.** این گزارش از داده‌های ذخیره‌شده با زمان برش "
        f"`{report.as_of.isoformat()}` ساخته شده است؛ اجرای آن دریافت تازه از منبع نیست.",
        "",
        f"{macro_count} شاخص از {len(report.macro.entries)} شاخص کلان در محدودهٔ سن مجاز است. "
        f"برای {estimated} مورد از {len(common)} مقایسهٔ ماهانه با نمونهٔ مشترک، "
        "ضریب قابل گزارش داریم. "
        f"دفتر اصلاحیه‌ها {revisions.compared_pairs} جفت از {revisions.expected_pairs} جفت "
        "برنامه‌ریزی‌شده را پوشش می‌دهد. این شمارش‌ها تعریف‌های جدا دارند و امتیاز معاملاتی نیستند.",
        "",
        "## وضعیت هر بخش",
        "",
        "| بخش | وضعیت |",
        "| --- | --- |",
    ]
    lines += [f"| {LABELS[s.key]} | {STATES[s.status]} |" for s in report.sections]
    lines += [
        "",
        "## پوشش قیمت روزانه",
        "",
        "هر ردیف یک جریان مستقل منبع/محل قیمت است. قیمت پایانی دارای برچسب تاریخ، "
        "کندل OHLC یا زمان بسته‌شدن تأییدشده نیست. جریان‌ها با هم جمع یا ادغام نمی‌شوند.",
        "",
        "| منبع و مجموعه | محل قیمت | نوع | تاریخ‌های یکتا | "
        "نخستین تاریخ | آخرین تاریخ | تاریخ آخر هفته |",
        "| --- | --- | --- | ---: | --- | --- | ---: |",
    ]
    prices = price_streams(report.quality)
    for s in prices:
        kind = "فقط قیمت پایانی" if s.identity["kind"] == "price_close" else "کندل OHLC"
        lines.append(
            f"| {cell(s.identity['source_id'])} / {cell(s.identity['dataset'])} | "
            f"{cell(s.identity['venue'])} | {kind} | {s.unique_observations} | "
            f"{s.first_observed_at.date()} | {s.last_observed_at.date()} | "
            f"{s.weekend_date_labels} |"
        )
    if not prices:
        lines.append("| جریان روزانهٔ XAUUSD موجود نیست | — | — | — | — | — | — |")
    lines += [
        "",
        "جزئیات جریان‌ها و هشدارهایشان: [گزارش کیفیت](details/quality.json).",
        "",
        "## شاخص‌های کلان",
        "",
        "این‌ها آخرین نسخهٔ مجاز در زمان برش‌اند. دورهٔ مرجع، تاریخ انتشار نیست. "
        "CPI این جدول سطح شاخص است؛ مقدار مفقود با عدد قدیمی‌تر پر نمی‌شود.",
        "",
        "| شاخص | مقدار | واحد | دورهٔ مرجع | وضعیت |",
        "| --- | ---: | --- | --- | --- |",
    ]
    for e in report.macro.entries:
        period = e.reference_at.date() if e.reference_at else "—"
        lines.append(
            f"| [{cell(NAMES.get(e.series_id, e.series_id))}]"
            f"(https://fred.stlouisfed.org/series/{e.series_id}) | {number(e.value, 4)} | "
            f"{cell(UNITS.get(e.unit, e.unit))} | {period} | "
            f"{STATUSES[e.status]} |"
        )
    lines += [
        "",
        "شناسهٔ رکورد، زمان دریافت و حد تازگی هر شاخص: [شواهد کلان](details/macro.json).",
        "",
        "## تقویم اعلام‌شدهٔ پیش رو",
        "",
        f"افق بررسی {report.calendar.horizon_days} روز است و فقط CPI و اشتغال را پوشش می‌دهد. "
        "ساعت اعلام‌شده، زمان اندازه‌گیری‌شدهٔ تحویل نیست؛ تغییر بعدی بدون شاهد تازه معلوم نمی‌شود.",
        "",
        "| رویداد و دوره | نیویورک | UTC | تهران | وضعیت شاهد |",
        "| --- | --- | --- | --- | --- |",
    ]
    for e in report.calendar.upcoming:
        times = [
            t.strftime("%Y-%m-%d %H:%M %z")
            for t in (e.new_york_time, e.announced_at.astimezone(UTC), e.tehran_time)
        ]
        state = "نیازمند بررسی دوباره" if e.stale_evidence else "در محدودهٔ سن مجاز"
        lines.append(
            f"| [{e.series_id} / {e.reference_period}]({e.source_url}) | "
            f"{' | '.join(times)} | {state} |"
        )
    if not report.calendar.upcoming:
        lines.append(
            "| در این افق شاهد واجد شرایط نداریم؛ به معنی نبود رویداد نیست | — | — | — | — |"
        )
    lines += [
        "",
        "سن و زمان ثبت هر شاهد: [شواهد تقویم](details/calendar.json).",
        "",
        "## روابط توصیفی ماهانه",
        "",
        "مقایسهٔ اصلی از نمونهٔ مشترک استفاده می‌کند: فقط ماه‌هایی که تغییر هر پنج سری "
        "موجود است. ضریب، جهت همراهی را توصیف می‌کند و علت یا پیش‌بینی نیست. "
        "طلا تغییر میانگین ماهانهٔ بانک جهانی است، نه بازده معامله در پایان ماه. "
        "دو روش قیمت جدا می‌مانند؛ تغییر ژوئن ۲۰۲۵ به دلیل مرز روش کنار گذاشته شده است.",
        "",
    ]
    for regime in REGIMES:
        title = (
            "تثبیت عصر لندن؛ تا مهٔ ۲۰۲۵"
            if regime == REGIMES[0]
            else "میانگین نقدی؛ پس از مرز ژوئن ۲۰۲۵"
        )
        lines += [
            f"### {title}",
            "",
            "| متغیر | بازهٔ ماه‌های نمونه | تعداد | پیرسون | اسپیرمن | وضعیت |",
            "| --- | --- | ---: | ---: | ---: | --- |",
        ]
        for a in common:
            if a.method == regime:
                period = f"{a.months[0]:%Y-%m} تا {a.months[-1]:%Y-%m}" if a.months else "—"
                lines.append(
                    f"| {MONTHLY_NAMES[a.series_id]} | {period} | {a.n} | {number(a.pearson)} | "
                    f"{number(a.spearman)} | {STATUS_FA[a.status]} |"
                )
        lines.append("")
    lines += [
        "",
        f"کمتر از {report.monthly.plan.minimum_pairs} ماه ضریب نمایش داده نمی‌شود؛ "
        "این حد، سیاست گزارش است. بازهٔ ابتدا/انتها تضمین پیوستگی نیست. "
        "نمونهٔ دوتایی، پنجره‌های متحرک و ماه‌های حذف‌شده: "
        "[گزارش کامل روابط](details/monthly-research.fa.md).",
        "",
        "## اتصال مقدار به سند و نسخه",
        "",
    ]
    values = [v for d in report.releases.documents for v in d.values]
    historical = sum(v.release_date_vintage.status == "matches_display" for v in values)
    current_diff = sum(v.current_revision.status == "differs_display" for v in values)
    lines += [
        f"از {len(report.releases.documents)} سند، {len(values)} ردیف مقدار بررسی شده است؛ "
        f"{historical} ردیف با vintage تاریخی در دقت نمایش سازگار است و {current_diff} ردیف "
        "با نسخهٔ جاری اختلاف نمایشی دارد. یک ماه ممکن است در چند سند تکرار شود؛ "
        "این شمارش، تعداد ماه‌های مستقل نیست. اختلاف نسخهٔ جاری با سند، غافلگیری بازار نیست.",
        "",
        "دامنهٔ این بخش همهٔ سندهای واجد شرایط ذخیره‌شده است؛ دامنهٔ دفتر زیر از برنامهٔ ثابت می‌آید. "
        "[جزئیات اتصال سند و FRED](details/release-values.fa.md).",
        "",
        "## دفتر اصلاحیه‌ها",
        "",
        f"پنجرهٔ ثابت {revisions.plan.start_period} تا {revisions.plan.end_period}: "
        f"{revisions.vintage_matched_pairs} جفت از {revisions.expected_pairs} جفت هم سندهای "
        "قابل مقایسه دارد و هم با هر دو vintage تاریخی سازگار است. "
        f"{revisions.changed_display_pairs} جفت اختلاف در دقت نمایش دارد. "
        "برابری عددهای یک‌اعشاری، نبود اصلاح زیر دقت نمایش یا اصلاح سال‌های بعد را ثابت نمی‌کند.",
        "",
        "جزئیات هر ماه، اسناد مفقود/مبهم و ثبت‌های مجدد همان سند: "
        "[دفتر اصلاحیه‌ها](details/revision-ledger.fa.md).",
        "",
        "## محدودیت‌های مؤثر و اقدام بعدی",
        "",
    ]
    issue_names = {
        **ISSUES,
        "NO_ELIGIBLE_DATA": "هیچ دادهٔ واجد شرایطی در زمان برش موجود نیست.",
        "REQUIRED_STREAM_MISSING": "یکی از جریان‌های الزامی سیاست کیفیت موجود نیست.",
        "DAILY_GAP_REVIEW": (
            "فاصله‌هایی در تاریخ‌های روزانه وجود دارد که نیازمند بررسی تقویم منبع است."
        ),
    }
    for code in sorted({i.code for i in report.quality.issues}):
        lines.append(f"- {cell(issue_names.get(code, code))}")
    if any(e.stale_evidence for e in report.calendar.upcoming):
        lines.append(
            "- شواهد تقویم از حد سن مجاز گذشته‌اند؛ تاریخ‌ها باید با منبع دوباره بررسی شوند."
        )
    if not report.calendar.upcoming:
        lines.append("- برای افق انتخاب‌شده، تقویم بررسی‌شدهٔ کافی نداریم.")
    if estimated < len(common):
        lines.append(
            "- در بخشی از نمونه‌های ماهانه ضریب قابل گزارش نیست؛ نتیجه با صفر جایگزین نشده است."
        )
    if revisions.status != "complete":
        lines.append(
            "- تکمیل دفتر اصلاحیه نیازمند رفع جایگاه‌های مفقود، مبهم یا تطبیق‌های ناسازگار است."
        )
    lines += [
        "- پیش از پژوهش بازده روزانه، تعریف واحد، ساعت مرجع و قیمت‌های آخر هفته باید روشن شود.",
        "- اولین انتشار و ساعت واقعی تحویل هنوز تأیید نشده‌اند؛ "
        "بک‌تست روزانه و بازپخش درون‌روزی آماده نیستند.",
        "",
        "## شواهد و بازتولید",
        "",
        "همهٔ بخش‌ها در یک خواندن سازگار از پایگاه ساخته شده‌اند؛ زمان برش مشترک، "
        "دورهٔ مرجع یا تازگی یکسان ایجاد نمی‌کند. گزارش‌های قدیمی از دیسک با هم ترکیب نشده‌اند. "
        "حساب‌ها از همان موتورهای مستقل پروژه می‌آیند؛ عدد یا تفسیر مدل زبانی افزوده نشده است.",
        "",
        f"نسخهٔ نرم‌افزار: {report.software_version}؛ "
        f"زمان ساخت: `{report.generated_at.isoformat()}`.",
        f"شناسهٔ بازتولید: `{report.fingerprint}`.",
        "",
        "[JSON یکپارچه و شناسهٔ همهٔ ورودی‌ها](research-report.json) · "
        "[فهرست فایل‌ها و هش‌ها](manifest.json)",
        "",
        "این بسته محلی است. هر اجرا در پوشهٔ جدا ذخیره می‌شود "
        "تا خروجی یا یادداشت اجرای قبلی بازنویسی نشود.",
        "",
    ]
    return "\n".join(lines)


class ReportFile(Contract):
    path: str = Field(pattern=r"^(?:details/)?[a-z][a-z0-9-]*(?:\.fa)?\.(?:json|md)$")
    sha256: Hash
    bytes: int = Field(ge=0)


class ReportManifest(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    software_version: str
    as_of: Timestamp
    report_fingerprint: Hash
    files: tuple[ReportFile, ...]

    @model_validator(mode="after")
    def complete_file_set(self):
        if {f.path for f in self.files} != FILES or len(self.files) != len(FILES):
            raise ValueError("report manifest must contain the complete unique file set")
        return self


def write_research_report(report, output_dir):
    # Validate again in case a nested dictionary was edited after model creation.
    report = ResearchReport.model_validate(report.model_dump(mode="json"))
    outputs = {
        "research-report.json": report.model_dump_json(indent=2) + "\n",
        "research-report.fa.md": render_research_report(report),
    }
    for key, name in (
        ("quality", "quality"),
        ("macro", "macro"),
        ("calendar", "calendar"),
        ("monthly", "monthly-research"),
        ("releases", "release-values"),
        ("revisions", "revision-ledger"),
    ):
        outputs[f"details/{name}.json"] = getattr(report, key).model_dump_json(indent=2) + "\n"
    outputs.update(
        {
            "details/monthly-research.fa.md": render_monthly_persian(report.monthly),
            "details/release-values.fa.md": render_release_values(report.releases),
            "details/revision-ledger.fa.md": render_revision_ledger(report.revisions),
        }
    )
    manifest = ReportManifest(
        software_version=report.software_version,
        as_of=report.as_of,
        report_fingerprint=report.fingerprint,
        files=tuple(
            ReportFile(path=k, sha256=hashlib.sha256(v.encode()).hexdigest(), bytes=len(v.encode()))
            for k, v in sorted(outputs.items())
        ),
    )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = uuid4().hex
    staging = output_dir / f".incomplete-{suffix}"
    destination = (
        output_dir / f"research-{report.generated_at.astimezone(UTC):%Y%m%dT%H%M%S%fZ}-{suffix[:8]}"
    )
    staging.mkdir()
    (staging / "details").mkdir()
    for name, content in outputs.items():
        (staging / name).write_bytes(content.encode("utf-8"))
    (staging / "manifest.json").write_bytes(
        (manifest.model_dump_json(indent=2) + "\n").encode("utf-8")
    )
    verify_research_bundle(staging)
    staging.rename(destination)
    return destination


def load_verified_report(directory):
    """Return the same bytes and models that passed verification, without rereading."""
    directory = Path(directory).resolve()
    manifest = ReportManifest.model_validate_json((directory / "manifest.json").read_bytes())
    contents = {}
    for item in manifest.files:
        path = (directory / item.path).resolve()
        if not path.is_relative_to(directory):
            raise ValueError("report artifact escaped its bundle directory")
        content = path.read_bytes()
        if len(content) != item.bytes or hashlib.sha256(content).hexdigest() != item.sha256:
            raise ValueError("report artifact hash mismatch")
        contents[item.path] = content
    report = ResearchReport.model_validate_json(contents["research-report.json"])
    if (
        report.as_of != manifest.as_of
        or report.software_version != manifest.software_version
        or report.fingerprint != manifest.report_fingerprint
    ):
        raise ValueError("manifest differs from the research report")
    for key, name in (
        ("quality", "quality"),
        ("macro", "macro"),
        ("calendar", "calendar"),
        ("monthly", "monthly-research"),
        ("releases", "release-values"),
        ("revisions", "revision-ledger"),
    ):
        if json.loads(contents[f"details/{name}.json"]) != getattr(report, key).model_dump(
            mode="json"
        ):
            raise ValueError("report detail differs from its embedded component")
    return report, manifest, contents["research-report.json"]


def verify_research_bundle(directory):
    report, manifest, _ = load_verified_report(directory)
    return {
        "status": "verified",
        "files": len(manifest.files),
        "fingerprint": report.fingerprint,
        "as_of": report.as_of.isoformat(),
    }
