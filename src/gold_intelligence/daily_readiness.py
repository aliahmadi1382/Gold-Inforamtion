"""Report-bound daily research requirements; diagnostic checks cannot grant readiness."""

import hashlib
from typing import Literal

from pydantic import Field, model_validator

from .models import Contract, Hash, NonEmpty, Timestamp
from .research_report import parse_research_report


class DailyRequirement(Contract):
    id: Literal["price_unit", "session_clock", "calendar", "first_release", "temporal_validation"]
    title: NonEmpty
    status: Literal["needs_evidence", "not_assessed"]
    facts: dict
    pointers: tuple[str, ...] = Field(min_length=1)
    required_evidence: NonEmpty
    limitation: NonEmpty


class DailyReadiness(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    report_fingerprint: Hash
    input_sha256: Hash
    as_of: Timestamp
    status: Literal["blocked"] = "blocked"
    daily_backtest_ready: Literal[False] = False
    requirements: tuple[DailyRequirement, ...]

    @model_validator(mode="after")
    def complete_requirements(self):
        if tuple(r.id for r in self.requirements) != (
            "price_unit",
            "session_clock",
            "calendar",
            "first_release",
            "temporal_validation",
        ):
            raise ValueError("daily readiness requires each diagnostic once in order")
        return self

    scope: Literal["saved_report_diagnostics_not_methodology_certification"] = (
        "saved_report_diagnostics_not_methodology_certification"
    )


def build_daily_readiness(content: bytes):
    report = parse_research_report(content)
    quality = report.quality
    prices = [
        (i, s)
        for i, s in enumerate(quality.streams)
        if s.identity.get("kind") in {"price_close", "price_bar"}
        and s.identity.get("timeframe") == "1d"
    ]
    ids = {stream.stream_id for _, stream in prices}
    codes = {issue.code for issue in quality.issues if issue.stream_id in ids}
    price_pointers = tuple(f"/quality/streams/{i}" for i, _ in prices) or ("/quality/streams",)
    facts = {
        "streams": [
            dict(
                stream_id=s.stream_id,
                identity=s.identity,
                unique_observations=s.unique_observations,
                date_only_prices=s.date_only_prices,
                weekend_date_labels=s.weekend_date_labels,
                daily_gap_count=s.daily_gap_count,
            )
            for _, s in prices
        ]
    }
    checks = []
    for identifier, title, code, requirement, limit in (
        (
            "price_unit",
            "واحد و تعریف قیمت",
            "UNIT_INFERRED",
            "مدرک روش منبع دربارهٔ ارز، واحد اونس تروا، ابزار و ثبات تعریف در تاریخچه.",
            "نام ابزار و نبود هشدار، تأیید روش قیمت نیست؛ جریان‌ها مستقل می‌مانند.",
        ),
        (
            "session_clock",
            "ساعت مرجع و زمان دسترسی",
            "DATE_ONLY_PRICE",
            "ساعت مرجع، منطقهٔ زمانی، تعریف بسته‌شدن و شاهد زمان دسترسی هر مشاهده.",
            "نیمه‌شب UTC برچسب تاریخ است؛ زمان بسته‌شدن یا دسترسی تاریخی از آن ساخته نمی‌شود.",
        ),
        (
            "calendar",
            "تقویم و قیمت‌های آخر هفته",
            "WEEKEND_DATE_LABELS",
            "تقویم منبع و روش تعطیلات/آخر هفته، همراه سیاست مستند فاصله‌ها و تغییر روش.",
            "شمار برچسب آخر هفته یا فاصلهٔ تقویمی، شمار جلسهٔ معاملاتی یا دادهٔ مفقود نیست.",
        ),
    ):
        checks.append(
            DailyRequirement(
                id=identifier,
                title=title,
                status="needs_evidence" if code in codes else "not_assessed",
                facts={**facts, "warning_present": code in codes},
                pointers=price_pointers,
                required_evidence=requirement,
                limitation=limit,
            )
        )
    checks.append(
        DailyRequirement(
            id="first_release",
            title="اولین انتشار و زمان واقعی تحویل",
            status="needs_evidence",
            facts={
                "first_release_verified": report.first_release_verified,
                "release_documents": len(report.releases.documents),
            },
            pointers=("/first_release_verified", "/releases/documents", "/calendar"),
            required_evidence=(
                "آرشیو مقدار اولین انتشار و زمان دسترسی واقعی؛ نسخه‌های اصلاحی و زمان دریافت جدا."
            ),
            limitation=(
                "ساعت اعلام‌شده و vintage هم‌تاریخ، اولین مقدار یا ساعت تحویل را اثبات نمی‌کنند."
            ),
        )
    )
    checks.append(
        DailyRequirement(
            id="temporal_validation",
            title="آزمون زمانی پژوهش روزانه",
            status="not_assessed",
            facts={"daily_backtest_ready": report.daily_backtest_ready},
            pointers=("/daily_backtest_ready",),
            required_evidence=(
                "پس از رفع شروط داده: هدف/افق، نمونهٔ کافی، جداسازی زمانی و آزمون خارج از نمونه."
            ),
            limitation="گزارش ماهانه و تازه‌بودن دریافت جای آزمون پژوهش روزانه را نمی‌گیرند.",
        )
    )
    return DailyReadiness(
        report_fingerprint=report.fingerprint,
        input_sha256=hashlib.sha256(content).hexdigest(),
        as_of=report.as_of,
        requirements=tuple(checks),
    )
