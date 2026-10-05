"""Reproducible monthly relationships; current revisions, no execution-price claims."""

import calendar
import hashlib
import statistics
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, model_validator

from . import __version__
from .comparison import latest_periods
from .models import Contract, Hash, Timestamp, aware
from .storage import canonical, record_id
from .world_bank import DATASET, SERIES

BREAK = date(2025, 6, 1)
SPECS = {
    SERIES: ("currency_per_troy_ounce", "USD", "monthly", "percent_change"),
    "DTWEXBGS": ("index_jan2006_100", None, "weekday", "percent_change"),
    "DFII10": ("percent", None, "weekday", "percentage_point_change"),
    "DGS10": ("percent", None, "weekday", "percentage_point_change"),
    "CPIAUCSL": ("index_1982_1984_100_sa", None, "monthly", "percent_change"),
}
DRIVERS = tuple(s for s in SPECS if s != SERIES)
NAMES = {
    SERIES: "تغییر میانگین قیمت طلا، درصد",
    "DTWEXBGS": "تغییر میانگین شاخص گستردهٔ دلار، درصد",
    "DFII10": "تغییر میانگین بازده واقعی ۱۰ساله، واحد درصد",
    "DGS10": "تغییر میانگین بازده اسمی ۱۰ساله، واحد درصد",
    "CPIAUCSL": "تورم ماهانهٔ CPI تعدیل‌شده، درصد",
}
REGIMES = ("london_afternoon_fixing_average", "spot_daily_average")
STATUS_FA = {
    "estimated": "توصیفی",
    "too_short": "کمتر از حداقل نمونه",
    "no_overlap": "بدون هم‌پوشانی",
    "constant": "سری ثابت؛ تعریف‌نشده",
}


def shift_month(month: date, offset: int) -> date:
    year, zero_month = divmod(month.year * 12 + month.month - 1 + offset, 12)
    return date(year, zero_month + 1, 1)


def month_range(start: date, end: date) -> list[date]:
    result = []
    while start <= end:
        result.append(start)
        start = shift_month(start, 1)
    return result


def method(month: date) -> str:
    return REGIMES[int(month >= BREAK)]


class MonthlyResearchPlan(Contract):
    start_month: date = date(2006, 2, 1)
    minimum_valid_weekday_fraction: float = Field(default=0.8, gt=0, le=1)
    minimum_pairs: int = Field(default=36, ge=3)
    rolling_months: int = Field(default=60, ge=3)

    @model_validator(mode="after")
    def valid_window(self):
        if self.start_month.day != 1 or self.start_month < date(2006, 2, 1):
            raise ValueError("study starts on a month boundary, no earlier than 2006-02")
        if self.rolling_months < self.minimum_pairs:
            raise ValueError("rolling window must meet the configured minimum sample")
        return self


def load_research_plan(path: Path) -> MonthlyResearchPlan:
    return MonthlyResearchPlan.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


class MonthlyLevel(Contract):
    series_id: str
    month: date
    unit: str
    method: str | None = None
    status: Literal["available", "missing", "insufficient_daily_coverage"]
    value: float | None
    expected_labels: int
    valid_values: int
    missing_labels: tuple[date, ...]
    null_labels: tuple[date, ...]
    record_ids: tuple[Hash, ...]


class MonthlyChange(Contract):
    month: date
    method: str
    values: dict[str, float | None]
    exclusions: dict[str, str]


class Association(Contract):
    series_id: str
    population: Literal["pairwise", "common"]
    method: str
    months: tuple[date, ...]
    n: int
    status: Literal["estimated", "too_short", "no_overlap", "constant"]
    pearson: float | None
    spearman: float | None


class RollingAssociation(Contract):
    series_id: str
    method: str
    first_month: date
    last_month: date
    n: int
    pearson: float | None
    spearman: float | None


class MonthlyResearch(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    generated_at: Timestamp
    as_of: Timestamp
    software_version: str
    plan: MonthlyResearchPlan
    fingerprint: Hash
    status: Literal["descriptive_only", "insufficient_data"]
    daily_backtest_ready: Literal[False] = False
    levels: tuple[MonthlyLevel, ...]
    changes: tuple[MonthlyChange, ...]
    associations: tuple[Association, ...]
    rolling: tuple[RollingAssociation, ...]
    definitions: dict[str, str]
    sources: dict[str, str]
    limitations: tuple[str, ...] = (
        "Latest versions known at the cutoff; not an original-release historical replay.",
        "Gold uses monthly average prices, not executable close-to-close returns.",
        "Contemporaneous association is neither causation nor a forecasting test.",
        "June 2025 gold change crosses a methodology break and is excluded.",
        "Daily coverage uses weekday labels, not a verified trading/holiday calendar.",
        "No imputation; missing months invalidate adjacent changes and rolling windows.",
        "The minimum sample is a reporting policy, not a statistical power guarantee.",
        "Overlapping rolling windows are dependent; no p-values or confidence claims.",
        "No lag search, fitted strategy, transaction costs or out-of-sample evaluation.",
    )


def select_inputs(store, as_of, start, end):
    """Validate compatible streams and raw hashes before collapsing current revisions."""
    grouped = defaultdict(list)
    raw_hashes = set()
    for r in store.read("observation", as_of, "system"):
        p = r.provenance
        if r.series_id not in SPECS or r.vintage_date is not None:
            continue
        expected_source = "world_bank_pink_sheet" if r.series_id == SERIES else "fred"
        if p.source_id != expected_source:
            continue
        day = p.observed_at.astimezone(UTC).date()
        if not start <= day < shift_month(end, 1) or p.observed_at > as_of:
            continue
        unit, currency, frequency, _ = SPECS[r.series_id]
        if (
            p.synthetic
            or p.unit != unit
            or p.currency != currency
            or p.observed_at != datetime.combine(day, datetime.min.time(), UTC)
            or p.dataset != (DATASET if r.series_id == SERIES else r.series_id)
            or r.layer != ("price" if r.series_id == SERIES else "macro")
            or (frequency == "monthly" and day.day != 1)
            or (frequency == "weekday" and day.weekday() >= 5)
        ):
            raise ValueError(f"incompatible monthly study stream: {r.series_id}")
        if r.series_id == SERIES:
            if r.dimensions != {
                "instrument": "GOLD",
                "frequency": "1mo",
                "aggregation": "monthly_average",
                "methodology": method(day),
            }:
                raise ValueError("unexpected World Bank methodology")
        elif set(r.dimensions) - {"realtime_start", "realtime_end"}:
            raise ValueError("unexpected FRED dimensions")
        if SPECS[r.series_id][3] == "percent_change" and r.value is not None and r.value <= 0:
            raise ValueError("nonpositive price/index level")
        grouped[r.series_id].append(r)
        raw_hashes.add(p.raw_sha256)
    for digest in raw_hashes:
        blob = store.root / "raw" / digest
        if not blob.exists() or hashlib.sha256(blob.read_bytes()).hexdigest() != digest:
            raise ValueError("monthly study raw evidence failed integrity check")
    return {series: latest_periods(grouped[series]) for series in SPECS}


def aggregate_month(series, month, records, plan):
    unit, _, frequency, _ = SPECS[series]
    if frequency == "weekday":
        expected = [
            month.replace(day=d)
            for d in range(1, calendar.monthrange(month.year, month.month)[1] + 1)
            if month.replace(day=d).weekday() < 5
        ]
    else:
        expected = [month]
    labels = {r.provenance.observed_at.astimezone(UTC).date() for r in records}
    missing = tuple(d for d in expected if d not in labels)
    nulls = tuple(
        r.provenance.observed_at.astimezone(UTC).date() for r in records if r.value is None
    )
    values = [r.value for r in records if r.value is not None]
    status = "missing"
    if values:
        enough = not missing and len(values) / len(expected) >= plan.minimum_valid_weekday_fraction
        status = "available" if enough else "insufficient_daily_coverage"
    return MonthlyLevel(
        series_id=series,
        month=month,
        unit=unit,
        method=method(month) if series == SERIES else None,
        status=status,
        value=statistics.fmean(values) if status == "available" else None,
        expected_labels=len(expected),
        valid_values=len(values),
        missing_labels=missing,
        null_labels=nulls,
        record_ids=tuple(record_id(r) for r in records),
    )


def changes_from_levels(levels, months):
    lookup = {(v.series_id, v.month): v for v in levels}
    changes = []
    for month in months:
        values, exclusions = {}, {}
        for series, (_, _, _, transform) in SPECS.items():
            current = lookup[series, month]
            previous = lookup[series, shift_month(month, -1)]
            reason = None
            if series == SERIES and current.method != previous.method:
                reason = "methodology_break"
            elif current.value is None:
                reason = "current_" + current.status
            elif previous.value is None:
                reason = "previous_" + previous.status
            values[series] = None
            if reason:
                exclusions[series] = reason
            else:
                values[series] = (
                    100 * (current.value / previous.value - 1)
                    if transform == "percent_change"
                    else current.value - previous.value
                )
        changes.append(
            MonthlyChange(month=month, method=method(month), values=values, exclusions=exclusions)
        )
    return changes


def ranks(values):
    """Average ranks for ties, without breaking ties by input order."""
    positions = defaultdict(list)
    for index, value in enumerate(sorted(values), 1):
        positions[value].append(index)
    averages = {value: statistics.fmean(indices) for value, indices in positions.items()}
    return [averages[value] for value in values]


def coefficients(x, y):
    if len(x) < 2 or len(set(x)) == 1 or len(set(y)) == 1:
        return None, None
    return statistics.correlation(x, y), statistics.correlation(ranks(x), ranks(y))


def summarize(changes, plan):
    results = []
    for regime in REGIMES:
        for population in ("pairwise", "common"):
            for series in DRIVERS:
                needed = SPECS if population == "common" else (SERIES, series)
                rows = [
                    r
                    for r in changes
                    if r.method == regime and all(r.values[s] is not None for s in needed)
                ]
                n = len(rows)
                status = "no_overlap" if not n else "too_short"
                pearson = spearman = None
                if n >= plan.minimum_pairs:
                    pearson, spearman = coefficients(
                        [r.values[SERIES] for r in rows], [r.values[series] for r in rows]
                    )
                    status = "estimated" if pearson is not None else "constant"
                results.append(
                    Association(
                        series_id=series,
                        population=population,
                        method=regime,
                        months=tuple(r.month for r in rows),
                        n=n,
                        status=status,
                        pearson=pearson,
                        spearman=spearman,
                    )
                )
    return results


def rolling_associations(changes, plan):
    result = []
    size = plan.rolling_months
    for end in range(size, len(changes) + 1):
        rows = changes[end - size : end]
        if (
            len({r.method for r in rows}) != 1
            or rows[-1].month != shift_month(rows[0].month, size - 1)
            or any(r.values[s] is None for r in rows for s in SPECS)
        ):
            continue
        for series in DRIVERS:
            pearson, spearman = coefficients(
                [r.values[SERIES] for r in rows], [r.values[series] for r in rows]
            )
            result.append(
                RollingAssociation(
                    series_id=series,
                    method=rows[0].method,
                    first_month=rows[0].month,
                    last_month=rows[-1].month,
                    n=size,
                    pearson=pearson,
                    spearman=spearman,
                )
            )
    return result


def monthly_research(store, plan, as_of):
    as_of = aware(as_of).astimezone(UTC)
    end = shift_month(as_of.date().replace(day=1), -1)
    start = shift_month(plan.start_month, -1)
    inputs = select_inputs(store, as_of, start, end)
    levels = []
    for series, records in inputs.items():
        grouped = defaultdict(list)
        for r in records:
            grouped[r.provenance.observed_at.astimezone(UTC).date().replace(day=1)].append(r)
        for month in month_range(start, end):
            levels.append(aggregate_month(series, month, grouped[month], plan))
    changes = changes_from_levels(levels, month_range(plan.start_month, end))
    associations = summarize(changes, plan)
    identity = {
        "software_version": __version__,
        "plan": plan.model_dump(mode="json"),
        "as_of": as_of.isoformat(),
        "input_ids": sorted(record_id(r) for rows in inputs.values() for r in rows),
    }
    return MonthlyResearch(
        generated_at=datetime.now(UTC),
        as_of=as_of,
        software_version=__version__,
        plan=plan,
        fingerprint=hashlib.sha256(canonical(identity).encode()).hexdigest(),
        status="descriptive_only"
        if any(a.status == "estimated" for a in associations)
        else "insufficient_data",
        levels=tuple(levels),
        changes=tuple(changes),
        associations=tuple(associations),
        rolling=tuple(rolling_associations(changes, plan)),
        definitions={s: NAMES[s] for s in SPECS},
        sources={
            SERIES: "https://www.worldbank.org/en/research/commodity-markets",
            **{s: f"https://fred.stlouisfed.org/series/{s}" for s in DRIVERS},
        },
    )


def format_number(value):
    return "—" if value is None else f"{value:.3f}"


def render_monthly_persian(report: MonthlyResearch) -> str:
    readiness = (
        "قابل استفاده در دامنهٔ پژوهش توصیفی با محدودیت‌های بالا"
        if report.status == "descriptive_only"
        else "داده برای گزارش ضریب همبستگی کافی نیست"
    )
    lines = [
        "# پژوهش توصیفی روابط ماهانهٔ طلا",
        "",
        f"زمان برش: `{report.as_of.isoformat()}`؛ نسخهٔ نرم‌افزار: {report.software_version}.",
        f"شناسهٔ بازتولید: `{report.fingerprint}`.",
        "",
        "**این محاسبه با نسخه‌های شناخته‌شده در زمان برش انجام شده است؛ "
        "دسترسی تاریخی به این نسخه‌ها، علیت، پیش‌بینی یا سودآوری را ثابت نمی‌کند.**",
        "",
        "## تعریف مقایسه",
        "",
        "طلا: درصد تغییر میانگین ماهانهٔ بانک جهانی؛ این عدد بازده خریدوفروش در پایان ماه نیست. "
        "دلار: درصد تغییر میانگین DTWEXBGS؛ این شاخص DXY نیست. "
        "نرخ‌ها: اختلاف میانگین دو ماه به واحد درصد. "
        "CPI: درصد تغییر شاخص تعدیل‌شده نسبت به ماه قبل؛ نه تورم سالانه و نه غافلگیری انتشار.",
        "",
        f"شروع تغییرها: {report.plan.start_month:%Y-%m}؛ ماه قبل فقط پایهٔ محاسبه است. "
        "فقط ماه‌های تقویمی پایان‌یافته وارد می‌شوند. هر سری روزانه باید تمام برچسب‌های "
        f"دوشنبه تا جمعه و دست‌کم {report.plan.minimum_valid_weekday_fraction:.0%} مقدار "
        "غیرمفقود داشته باشد. این قاعده، تأیید تقویم معاملاتی یا علت مفقودی نیست. "
        "ماه ناقص و ماه پس از آن در تغییر همان سری حذف می‌شوند؛ هیچ پرکردنی انجام نمی‌شود.",
        "",
        "ژوئن ۲۰۲۵ به دلیل تغییر تعریف قیمت طلا از محاسبهٔ تغییر حذف شده است. "
        "دو روش قیمت با هم ادغام نمی‌شوند.",
        "",
    ]
    for regime in REGIMES:
        title = (
            "تا مهٔ ۲۰۲۵؛ تثبیت عصر لندن" if regime == REGIMES[0] else "از ژوئیهٔ ۲۰۲۵؛ میانگین نقدی"
        )
        lines += [
            f"## {title}",
            "",
            "نمونهٔ مشترک شامل ماه‌هایی است که تغییر هر پنج سری موجود است. "
            "نمونهٔ دوتایی فقط طلا و متغیر همان سطر را لازم دارد. "
            f"زیر {report.plan.minimum_pairs} ماه ضریب نمایش داده نمی‌شود؛ "
            "این حد، سیاست گزارش است و تضمین کفایت آماری نیست.",
            "",
            "| متغیر | نمونه | ماه‌ها | تعداد | پیرسون | اسپیرمن | وضعیت |",
            "| --- | --- | --- | ---: | ---: | ---: | --- |",
        ]
        for a in report.associations:
            if a.method != regime:
                continue
            period = f"{a.months[0]:%Y-%m} تا {a.months[-1]:%Y-%m}" if a.months else "—"
            label = "مشترک" if a.population == "common" else "دوتایی"
            lines.append(
                f"| {NAMES[a.series_id]} | {label} | {period} | {a.n} | "
                f"{format_number(a.pearson)} | {format_number(a.spearman)} | "
                f"{STATUS_FA[a.status]} |"
            )
        lines += [
            "",
            "بازهٔ ابتدا و انتها به معنی پیوستگی همهٔ ماه‌ها نیست؛ فهرست دقیق در JSON است.",
            "",
        ]
    lines += [
        f"## حساسیت زمانی؛ پنجرهٔ {report.plan.rolling_months} ماهه",
        "",
        "فقط پنجره‌های پیوسته با نمونهٔ مشترک کامل و یک روش قیمت محاسبه می‌شوند. "
        "حداقل و حداکثر زیر، دامنهٔ ضرایب پنجره‌هاست؛ فاصلهٔ اطمینان نیست. "
        "پنجره‌ها هم‌پوشانی دارند و شواهد مستقل شمرده نمی‌شوند.",
        "",
        "| متغیر | تعداد پنجره | کمینهٔ پیرسون | بیشینهٔ پیرسون | آخرین پنجره | آخرین پیرسون |",
        "| --- | ---: | ---: | ---: | --- | ---: |",
    ]
    for series in DRIVERS:
        rows = [r for r in report.rolling if r.series_id == series and r.pearson is not None]
        period = f"{rows[-1].first_month:%Y-%m} تا {rows[-1].last_month:%Y-%m}" if rows else "—"
        values = [r.pearson for r in rows]
        lines.append(
            f"| {NAMES[series]} | {len(rows)} | "
            f"{format_number(min(values) if values else None)} | "
            f"{format_number(max(values) if values else None)} | {period} | "
            f"{format_number(values[-1] if values else None)} |"
        )
    lines += [
        "",
        "## حذف‌ها و پوشش",
        "",
        "| سری | ماه سطح قابل استفاده | ماه سطح حذف‌شده | تغییر حذف‌شده | آخرین سطح قابل استفاده |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for series in SPECS:
        levels = [r for r in report.levels if r.series_id == series]
        usable = [r for r in levels if r.value is not None]
        excluded = sum(r.values[series] is None for r in report.changes)
        last = f"{usable[-1].month:%Y-%m}" if usable else "—"
        lines.append(
            f"| {series} | {len(usable)} | {len(levels) - len(usable)} | {excluded} | {last} |"
        )
    reason_names = {
        "methodology_break": "تغییر روش قیمت",
        "current_missing": "مقدار ماه جاری مفقود",
        "previous_missing": "مقدار ماه قبل مفقود",
        "current_insufficient_daily_coverage": "پوشش روزانهٔ ماه جاری ناکافی",
        "previous_insufficient_daily_coverage": "پوشش روزانهٔ ماه قبل ناکافی",
    }
    rejected = [r for r in report.changes if r.exclusions]
    if rejected:
        lines += [
            "",
            "جدول زیر ماه‌های دارای حذف را نشان می‌دهد؛ علت مفقودی منبع از خود عدد حدس زده نمی‌شود.",
            "",
            "| ماه | تغییرهای حذف‌شده و علت |",
            "| --- | --- |",
        ]
        for row in rejected:
            reasons = "؛ ".join(f"{s}: {reason_names[why]}" for s, why in row.exclusions.items())
            lines.append(f"| {row.month:%Y-%m} | {reasons} |")
    lines += [
        "",
        "## خواندن نتیجه و حدود آن",
        "",
        "علامت ضریب، جهت همراهی در همین نمونه را نشان می‌دهد؛ بزرگی آن سهم علت یا احتمال "
        "سود نیست. پیرسون رابطهٔ خطی و اسپیرمن همراهی رتبه‌ها را می‌سنجد. "
        "تفاوت این دو یا تغییر ضریب در پنجره‌ها نیازمند بررسی است، نه انتخاب ضریب مطلوب. "
        "خودهمبستگی و هم‌پوشانی پنجره‌ها دلیل کافی است که از این جدول ادعای معناداری "
        "یا فاصلهٔ اطمینان ساده نسازیم. رابطهٔ همان ماه برای تصمیم ابتدای ماه در دسترس نیست.",
        "",
        f"وضعیت بررسی: {readiness}. "
        "بک‌تست روزانه و مطالعهٔ واکنش انتشار همچنان به روش قیمت و نسخه/زمان واقعی انتشار وابسته‌اند.",
        "",
        "## منابع و بازتولید",
        "",
    ]
    lines += [f"- [{series}]({url})" for series, url in report.sources.items()]
    lines += [
        "",
        "فایل JSON همراه شامل تنظیمات، تمام ماه‌های ردشده با علت، برچسب‌های مفقود، "
        "شناسهٔ رکوردهای ورودی، فهرست دقیق نمونه‌ها و ضرایب تمام پنجره‌هاست. "
        "شناسه‌ها به پایگاه محلی و از آنجا به شاهد خام دارای SHA-256 متصل‌اند. "
        "این خروجی مشتق‌شده در پوشهٔ local نگهداری می‌شود.",
        "",
    ]
    return "\n".join(lines)
