"""Local Persian research-status brief; deterministic prose, no trading recommendation."""

from datetime import UTC, datetime
from typing import Literal

from .macro import MacroContext, macro_context
from .models import Contract, Timestamp
from .quality import QualityReport, assess
from .release_calendar import CalendarContext, calendar_context

NAMES = {
    "DFF": "نرخ مؤثر وجوه فدرال",
    "DGS10": "بازده اسمی خزانهٔ ۱۰ساله",
    "DFII10": "بازده واقعی خزانهٔ ۱۰ساله",
    "T10YIE": "تورم سربه‌سر ۱۰ساله",
    "DTWEXBGS": "شاخص گستردهٔ دلار، نه DXY",
    "CPIAUCSL": "سطح شاخص CPI تعدیل‌شده",
    "UNRATE": "نرخ بیکاری تعدیل‌شده",
}
STATUSES = {
    "available": "در دسترس",
    "missing": "فاقد دادهٔ مجاز",
    "missing_value": "مقدار مفقود",
    "stale": "دورهٔ مرجع قدیمی",
}
UNITS = {
    "percent": "درصد",
    "percent_sa": "درصد، تعدیل فصلی",
    "index_jan2006_100": "شاخص؛ ژانویهٔ ۲۰۰۶ = ۱۰۰",
    "index_1982_1984_100_sa": "شاخص؛ ۱۹۸۲–۱۹۸۴ = ۱۰۰، تعدیل فصلی",
}
ISSUES = {
    "DATE_ONLY_PRICE": "قیمت روزانه برچسب تاریخ دارد؛ ساعت جلسه معلوم نیست.",
    "UNIT_INFERRED": "واحد قیمت Alpha Vantage از نام ابزار استنباط شده است.",
    "WEEKEND_DATE_LABELS": "قیمت‌های آخر هفته حفظ شده‌اند؛ روش تولیدشان هنوز روشن نیست.",
    "MISSING_VALUES": "بخشی از مقادیر منبع مفقود است؛ با عدد جایگزین نشده است.",
    "RELEASE_TIME_UNKNOWN": "برای بخشی از داده‌ها فقط زمان دریافت مشخص است.",
    "STALE_REFERENCE": (
        "برخی جریان\u200cها دورهٔ مرجع قدیمی دارند؛ نسخهٔ تاریخی یا روش "
        "پایان\u200cیافته هم ممکن است در این گروه باشد."
    ),
}


class ResearchBrief(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    generated_at: Timestamp
    as_of: Timestamp
    quality: QualityReport
    macro: MacroContext
    calendar: CalendarContext
    daily_backtest_ready: Literal[False] = False
    scope: str = "Descriptive data status and reviewed timing evidence; not a trading signal."


def build_brief(store, registry, plan, policy, as_of, horizon_days=90):
    quality = assess(store, registry, as_of, policy)
    return ResearchBrief(
        generated_at=datetime.now(UTC),
        as_of=as_of,
        quality=quality,
        macro=macro_context(store, plan, as_of),
        calendar=calendar_context(store, as_of, horizon_days),
    )


def cell(value):
    return (
        str(value).replace("|", "\\|").replace("\n", " ").replace("<", "&lt;").replace(">", "&gt;")
    )


def render_persian(brief: ResearchBrief) -> str:
    state = {"pass": "قبولِ کنترل‌های داده", "warning": "هشدار", "fail": "خطا"}[brief.quality.status]
    lines = [
        "# گزارش وضعیت داده و تقویم پژوهش طلا",
        "",
        f"زمان برش اطلاعات: `{brief.as_of.isoformat()}`؛ "
        f"زمان ساخت: `{brief.generated_at.isoformat()}`.",
        "",
        f"**وضعیت کنترل کیفیت: {state}. آمادگی بک‌تست روزانه: تأیید نشده.**",
        "",
        (
            "این گزارش تصویر داده\u200cهای در دسترس است. عدد شاخص، زمان اعلام\u200cشدهٔ "
            "انتشار و قیمت طلا تعریف\u200cهای جدا دارند. گزارشی از خریدوفروش یا "
            "پیش\u200cبینی بازده تولید نمی\u200cشود."
        ),
        "",
        "## شاخص‌های کلان",
        "",
        (
            "انتخاب هر عدد بر اساس زمان دسترسی و دریافت انجام شده است. تاریخ "
            "مرجع، زمان انتشار نیست. وضعیت «در دسترس» فقط به قواعد انتخاب و سن "
            "دوره مربوط است."
        ),
        "",
        "| شاخص | مقدار | واحد | دورهٔ مرجع | وضعیت |",
        "| --- | ---: | --- | --- | --- |",
    ]
    for e in brief.macro.entries:
        value = "—" if e.value is None else f"{e.value:,.4f}".rstrip("0").rstrip(".")
        period = e.reference_at.date().isoformat() if e.reference_at else "—"
        lines.append(
            f"| {cell(NAMES.get(e.series_id, e.series_id))} ({e.series_id}) | {value} | "
            f"{cell(UNITS.get(e.unit, e.unit))} | {period} | {STATUSES[e.status]} |"
        )
    lines += [
        "",
        (
            "CPI در این جدول سطح شاخص است؛ نرخ تورم ماهانه یا سالانه محاسبه "
            "نشده است. آخرین مقدار مفقود با مشاهدهٔ قدیمی\u200cتر جایگزین نمی\u200cشود."
        ),
        "",
        "## زمان‌های اعلام‌شدهٔ پیش رو",
        "",
        "پوشش این جدول فقط CPI و گزارش اشتغال است. ورودی، یادداشت بازبینی صفحهٔ رسمی است؛ "
        "HTML اصلی در این محیط دریافت نشده است.",
        (
            "این جدول نسخهٔ بررسی\u200cشدهٔ تقویم است؛ تأخیر، لغو یا تغییر بعدی بدون"
            " بررسی تازهٔ منبع مشخص نمی\u200cشود. زمان تهران با منطقهٔ زمانی واقعی "
            "محاسبه شده است."
        ),
        "",
        "| رویداد و دوره | نیویورک | UTC | تهران | سن شاهد، ساعت | وضعیت شاهد |",
    ]
    lines.append("| --- | --- | --- | --- | ---: | --- |")
    if not brief.calendar.upcoming:
        lines.append("| در این بازه شاهد واجد شرایط ذخیره نشده است | — | — | — | — | نامعلوم |")
    for e in brief.calendar.upcoming:
        link = f"[{e.series_id} / {e.reference_period}]({e.source_url})"
        times = [
            d.strftime("%Y-%m-%d %H:%M %z")
            for d in (e.new_york_time, e.announced_at.astimezone(UTC), e.tehran_time)
        ]
        freshness = "نیازمند بررسی دوباره" if e.stale_evidence else "در محدودهٔ سن مجاز"
        lines.append(f"| {link} | {' | '.join(times)} | {e.evidence_age_hours:.1f} | {freshness} |")
    lines += [
        "",
        (
            "عبور ساعت تقویم به معنی دریافت مقدار واقعی نیست. سرصفحهٔ انتشار "
            "قدیمی هم اجازه نمی\u200cدهد مقادیر اصلاح\u200cشدهٔ امروز را به آن ساعت نسبت "
            "بدهیم."
        ),
        "",
        "## محدودیت‌های مؤثر",
        "",
    ]
    codes = sorted({issue.code for issue in brief.quality.issues})
    lines += [f"- {cell(ISSUES.get(code, code))}" for code in codes]
    if not codes:
        lines.append(
            "- در کنترل‌های اجراشده موردی گزارش نشده است؛ این نتیجه تأیید روش قیمت یا سودآوری نیست."
        )
    lines += [
        "",
        "## کارهای مستقل از پاسخ Alpha Vantage",
        "",
        "- نگهداری نسخه‌های تقویم و بررسی تغییر تاریخ‌ها و ساعت‌ها.",
        "- تکمیل شواهد انتشار و اتصال دقیق هر مقدار به نسخهٔ منتشرشدهٔ خودش.",
        (
            "- پژوهش توصیفی داده\u200cهای ماهانه با تعریف و نسخهٔ مشخص، بدون ادعای "
            "دسترسی تاریخی یا قابلیت معامله."
        ),
        "",
        "## بخش وابسته به پاسخ منبع قیمت",
        "",
        (
            "محاسبات بازده و بک\u200cتست روزانهٔ Alpha Vantage به روشن\u200cشدن واحد، "
            "ساعت مرجع و روش قیمت\u200cهای آخر هفته وابسته\u200cاند. این محدودیت مانع "
            "پیشرفت تقویم، کیفیت و گزارش داده\u200cهای کلان نیست."
        ),
        "",
        "## شناسه‌های شواهد",
        "",
        (
            "مقادیر و زمان\u200cها از رکوردهای زیر آمده\u200cاند. گزارش JSON همراه، سیاست"
            " کیفیت، هش\u200cها و جزئیات کامل را نگه می\u200cدارد."
        ),
        "",
    ]
    lines += [f"- `{e.series_id}`: `{e.record_id}`" for e in brief.macro.entries if e.record_id]
    lines += [
        f"- تقویم `{e.series_id}/{e.reference_period}`: `{e.record_id}`"
        for e in brief.calendar.upcoming
    ]
    return "\n".join(lines) + "\n"
