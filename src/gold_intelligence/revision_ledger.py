"""Adjacent-document comparisons and separate same-document capture history.

The ledger measures differences in inspected archives. It never certifies first
release values, intraday availability, consensus surprises or original HTML.
"""

import hashlib
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, model_validator

from . import __version__
from .brief import cell
from .models import Contract, Hash, NonEmpty, Timestamp, aware
from .monthly_research import shift_month
from .release_values import (
    METRICS,
    Metric,
    ReleaseValueEvidence,
    ValueComparison,
    compare_value,
    document_versions,
)
from .storage import canonical, record_id


class RevisionPlan(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    declared_at: Timestamp
    start_period: str = Field(pattern=r"^\d{4}-\d{2}$")
    end_period: str = Field(pattern=r"^\d{4}-\d{2}$")
    metrics: tuple[Metric, ...] = Field(min_length=1, max_length=2)
    selection_reason: NonEmpty
    method: Literal["adjacent_document_display"] = "adjacent_document_display"

    @model_validator(mode="after")
    def scope(self):
        start = date.fromisoformat(self.start_period + "-01")
        end = date.fromisoformat(self.end_period + "-01")
        months = (end.year - start.year) * 12 + end.month - start.month + 1
        if not 1 <= months <= 120:
            raise ValueError("revision window must contain 1 to 120 months")
        if len(set(self.metrics)) != len(self.metrics):
            raise ValueError("revision metrics must be unique")
        # Reserve the following headline month required by the final comparison.
        shift_month(end, 1)
        return self


def load_revision_plan(path):
    return RevisionPlan.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


class DocumentCapture(Contract):
    capture_id: Hash
    raw_sha256: Hash
    retrieved_at: Timestamp
    record_ids: tuple[Hash, ...]
    evidence: ReleaseValueEvidence


class DocumentSlot(Contract):
    metric: Metric
    headline_period: str
    status: Literal["present", "missing", "ambiguous"]
    candidate_capture_ids: tuple[Hash, ...]


class ValueAnchor(Contract):
    capture_id: Hash
    record_id: Hash
    reference_period: str
    value: float
    unit: str
    decimal_places: Literal[1] = 1
    locator: str


class RevisionPair(Contract):
    metric: Metric
    reference_period: str
    next_headline_period: str
    status: Literal[
        "unchanged_display",
        "changed_display",
        "missing_document",
        "ambiguous_document",
        "missing_previous_value",
        "invalid_document_order",
    ]
    before: ValueAnchor | None
    after: ValueAnchor | None
    difference_pp: float | None = None
    before_vintage: ValueComparison | None
    after_vintage: ValueComparison | None
    vintage_difference_pp: float | None = None


class CaptureChange(Contract):
    metric: Metric
    reference_period: str
    before_capture_id: Hash
    after_capture_id: Hash
    status: Literal["unchanged_display", "changed_display", "added", "removed"]
    before: ValueAnchor | None
    after: ValueAnchor | None
    difference_pp: float | None = None


class RevisionLedger(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    software_version: str
    generated_at: Timestamp
    as_of: Timestamp
    fingerprint: Hash
    plan: RevisionPlan
    status: Literal["complete", "incomplete", "no_evidence"]
    expected_pairs: int
    compared_pairs: int
    vintage_matched_pairs: int
    changed_display_pairs: int
    document_slots: tuple[DocumentSlot, ...]
    captures: tuple[DocumentCapture, ...]
    pairs: tuple[RevisionPair, ...]
    capture_changes: tuple[CaptureChange, ...]
    first_release_verified: Literal[False] = False
    intraday_replay_ready: Literal[False] = False
    limitations: tuple[str, ...] = (
        "Equality is only at the one-decimal display precision and only for adjacent documents.",
        "Archive captures may be reissued; their header clocks do not date observed revisions.",
        "Same-document recapture differences are separate from cross-document differences.",
        "Missing and ambiguous document slots remain in the declared coverage denominator.",
        "FRED vintages are day-resolution and share the underlying BLS statistical source.",
        "Availability remains retrieval bounded; no historical availability is inferred.",
        "The plan declaration is operator supplied, not independently certified preregistration.",
        "Differences are not market surprises and do not estimate tradable gold responses.",
    )


def periods(plan):
    start = date.fromisoformat(plan.start_period + "-01")
    end = date.fromisoformat(plan.end_period + "-01")
    count = (end.year - start.year) * 12 + end.month - start.month + 1
    return [shift_month(start, n).strftime("%Y-%m") for n in range(count + 1)]


def anchor(capture, period):
    if capture is not None:
        for entry, rid in zip(capture.evidence.values, capture.record_ids, strict=True):
            if entry.reference_period == period:
                return ValueAnchor(
                    capture_id=capture.capture_id,
                    record_id=rid,
                    reference_period=period,
                    value=entry.value,
                    unit=entry.unit,
                    locator=entry.locator,
                )
    return None


def difference(before, after):
    if before is None or after is None or before.value is None or after.value is None:
        return None
    return float(Decimal(str(after.value)) - Decimal(str(before.value)))


def revision_ledger(store, registry, plan, as_of):
    as_of = aware(as_of).astimezone(UTC)
    records = [r for r in store.read("observation", as_of) if r.provenance.observed_at <= as_of]
    cache, captures, latest, changes = {}, [], defaultdict(list), []
    headlines = periods(plan)
    for versions in document_versions(store, registry, records, cache).values():
        # Do not permit one URL to silently change the metric, period or release identity.
        identities = {
            (e.metric, e.headline_period, e.release_id, e.announced_at) for e, _ in versions
        }
        if len(identities) != 1:
            raise ValueError("same archive URL has conflicting release identities")
        first = versions[0][0]
        if first.metric not in plan.metrics or first.headline_period not in headlines:
            continue
        by_time = defaultdict(list)
        for evidence, rows in versions:
            by_time[evidence.captured_at].append((evidence, rows))
        history = []
        for when in sorted(by_time):
            candidates = by_time[when]
            if len({canonical(e.model_dump(mode="json")) for e, _ in candidates}) != 1:
                raise ValueError("conflicting same-capture release documents")
            evidence, rows = min(candidates, key=lambda pair: tuple(record_id(r) for r in pair[1]))
            ids = tuple(record_id(r) for r in rows)
            capture = DocumentCapture(
                capture_id=ids[0],
                raw_sha256=rows[0].provenance.raw_sha256,
                retrieved_at=rows[0].provenance.retrieved_at,
                record_ids=ids,
                evidence=evidence,
            )
            history.append(capture)
            captures.append(capture)
        latest[(first.metric, first.headline_period)].append(history[-1])
        for old, new in zip(history, history[1:], strict=False):
            for period in headlines[:-1]:
                before, after = anchor(old, period), anchor(new, period)
                if before is None and after is None:
                    continue
                delta = difference(before, after)
                changes.append(
                    CaptureChange(
                        metric=first.metric,
                        reference_period=period,
                        before_capture_id=old.capture_id,
                        after_capture_id=new.capture_id,
                        status="added"
                        if before is None
                        else "removed"
                        if after is None
                        else "unchanged_display"
                        if delta == 0
                        else "changed_display",
                        before=before,
                        after=after,
                        difference_pp=delta,
                    )
                )
    slots, pairs, parent_ids = [], [], set()
    for metric in sorted(plan.metrics):
        for headline in headlines:
            candidates = latest[(metric, headline)]
            slots.append(
                DocumentSlot(
                    metric=metric,
                    headline_period=headline,
                    status="missing"
                    if not candidates
                    else "present"
                    if len(candidates) == 1
                    else "ambiguous",
                    candidate_capture_ids=tuple(sorted(c.capture_id for c in candidates)),
                )
            )
        for period, following in zip(headlines, headlines[1:], strict=False):
            old, new = latest[(metric, period)], latest[(metric, following)]
            baseline = old[0] if len(old) == 1 else None
            successor = new[0] if len(new) == 1 else None
            before, after = anchor(baseline, period), anchor(successor, period)
            delta = difference(before, after)
            if len(old) > 1 or len(new) > 1:
                status = "ambiguous_document"
            elif baseline is None or successor is None:
                status = "missing_document"
            elif after is None:
                status = "missing_previous_value"
            elif baseline.evidence.announced_at >= successor.evidence.announced_at:
                status = "invalid_document_order"
            else:
                status = "unchanged_display" if delta == 0 else "changed_display"
            vintages = []
            for capture, value in ((baseline, before), (successor, after)):
                comparison = None
                if value is not None:
                    entry = next(e for e in capture.evidence.values if e.reference_period == period)
                    comparison = compare_value(
                        store,
                        registry,
                        records,
                        capture.evidence,
                        entry,
                        capture.evidence.announced_at.date(),
                        cache,
                    )
                    parent_ids.update(comparison.record_ids)
                vintages.append(comparison)
            pairs.append(
                RevisionPair(
                    metric=metric,
                    reference_period=period,
                    next_headline_period=following,
                    status=status,
                    before=before,
                    after=after,
                    difference_pp=delta if status.endswith("_display") else None,
                    before_vintage=vintages[0],
                    after_vintage=vintages[1],
                    vintage_difference_pp=difference(*vintages)
                    if status.endswith("_display")
                    else None,
                )
            )
    captures.sort(key=lambda c: (str(c.evidence.source_url), c.evidence.captured_at))
    capture_times = {c.capture_id: c.evidence.captured_at for c in captures}
    changes.sort(
        key=lambda c: (
            c.metric,
            c.reference_period,
            capture_times[c.before_capture_id],
            capture_times[c.after_capture_id],
            c.before_capture_id,
            c.after_capture_id,
        )
    )
    compared = sum(p.status.endswith("_display") for p in pairs)
    matched = sum(
        p.status.endswith("_display")
        and all(
            v is not None and v.status == "matches_display"
            for v in (p.before_vintage, p.after_vintage)
        )
        for p in pairs
    )
    identity = dict(
        version=__version__,
        plan=plan.model_dump(mode="json"),
        as_of=as_of.isoformat(),
        record_ids=sorted(parent_ids | {rid for c in captures for rid in c.record_ids}),
    )
    return RevisionLedger(
        software_version=__version__,
        generated_at=datetime.now(UTC),
        as_of=as_of,
        plan=plan,
        fingerprint=hashlib.sha256(canonical(identity).encode()).hexdigest(),
        status="no_evidence"
        if not captures
        else "complete"
        if matched == len(pairs)
        else "incomplete",
        expected_pairs=len(pairs),
        compared_pairs=compared,
        vintage_matched_pairs=matched,
        changed_display_pairs=sum(p.status == "changed_display" for p in pairs),
        document_slots=tuple(slots),
        captures=tuple(captures),
        pairs=tuple(pairs),
        capture_changes=tuple(changes),
    )


def render_revision_ledger(report):
    labels = {
        "unchanged_display": "برابر در دقت نمایش",
        "changed_display": "اختلاف در دقت نمایش",
        "missing_document": "سند مفقود",
        "ambiguous_document": "سند مبهم",
        "missing_previous_value": "عدد دورهٔ قبل مفقود",
        "invalid_document_order": "ترتیب سند نامعتبر",
        "added": "اضافه‌شده",
        "removed": "حذف‌شده",
    }

    def number(value):
        return "—" if value is None else f"{value:.6f}".rstrip("0").rstrip(".")

    def vintage(value):
        if value is None:
            return "—"
        status = {
            "matches_display": "سازگار",
            "differs_display": "ناسازگار با دقت نمایش",
            "rounding_boundary": "مرز گردکردن",
            "missing_period": "نسخه/دوره مفقود",
            "missing_value": "مقدار مفقود",
        }[value.status]
        return f"{value.vintage_date}: {number(value.value)} ({status})"

    lines = [
        "# دفتر اصلاحیه‌ها و پوشش اسناد",
        "",
        f"بازهٔ دوره‌های اقتصادی: {report.plan.start_period} تا {report.plan.end_period}؛ "
        f"برش داده: `{report.as_of.isoformat()}`؛ نسخه: {report.software_version}.",
        f"شناسهٔ بازتولید: `{report.fingerprint}`.",
        f"زمان ثبت برنامه: `{report.plan.declared_at.isoformat()}`؛ "
        "این زمان خوداظهاری محلی است و پیش‌ثبت مستقل محسوب نمی‌شود.",
        "",
        f"از {report.expected_pairs} مقایسهٔ مورد انتظار، {report.compared_pairs} جفت سند "
        f"قابل مقایسه است و {report.vintage_matched_pairs} جفت با هر دو نسخهٔ تاریخی سازگار است. "
        f"تعداد اختلاف در ارقام نمایشی: {report.changed_display_pairs}. وضعیت: `{report.status}`.",
        "",
        "برای هر ماه، عدد همان دوره در سند اصلی آن ماه با عدد همان دوره در سند ماه بعد "
        "مقایسه می‌شود. مخرج پوشش از برنامهٔ ثابت می‌آید؛ سند مفقود از جدول حذف نمی‌شود. "
        "«برابر» فقط به دقت یک رقم اعشار اشاره دارد و نبود همهٔ اصلاحات بعدی را ثابت نمی‌کند.",
        "",
    ]
    for metric in sorted(report.plan.metrics):
        lines += [
            f"## {METRICS[metric]['label']}",
            "",
            "| دوره | سند همان ماه | در سند ماه بعد | اختلاف (واحد درصد) | نتیجه |",
            "| --- | ---: | ---: | ---: | --- |",
        ]
        for pair in report.pairs:
            if pair.metric == metric:
                before = number(pair.before.value if pair.before else None)
                after = number(pair.after.value if pair.after else None)
                lines.append(
                    f"| {pair.reference_period} | {before} | {after} | "
                    f"{number(pair.difference_pp)} | "
                    f"{labels[pair.status]} |"
                )
        lines += [
            "",
            "| دوره | FRED در تاریخ سند همان ماه | FRED در تاریخ سند بعد | اختلاف نسخه‌ها |",
            "| --- | --- | --- | ---: |",
        ]
        for pair in report.pairs:
            if pair.metric == metric:
                lines.append(
                    f"| {pair.reference_period} | {vintage(pair.before_vintage)} | "
                    f"{vintage(pair.after_vintage)} | {number(pair.vintage_difference_pp)} |"
                )
        lines.append("")
    lines += ["## پوشش مورد انتظار", "", "| شاخص | دورهٔ اصلی سند | وضعیت |", "| --- | --- | --- |"]
    for slot in report.document_slots:
        status = {"present": "موجود", "missing": "مفقود", "ambiguous": "مبهم"}[slot.status]
        lines.append(f"| {METRICS[slot.metric]['label']} | {slot.headline_period} | {status} |")
    lines += [
        "",
        "## تاریخچهٔ ثبت یک سند",
        "",
        "این بخش تغییر بین دو ثبت محلی از یک نشانی سند را جدا نگه می‌دارد. "
        "این تغییر می‌تواند از ویرایش آرشیو یا اصلاح برداشت دستی باشد؛ علت نیازمند بررسی است.",
        "",
    ]
    if not report.capture_changes:
        lines += [
            "برای اسناد این بازه، جفت ثبت محلی متفاوتی موجود نیست؛ "
            "دربارهٔ تغییرات بین ثبت‌ها نتیجه‌ای نداریم.",
            "",
        ]
    for change in report.capture_changes:
        lines.append(
            f"- {METRICS[change.metric]['label']}، {change.reference_period}: "
            f"{labels[change.status]}؛ اختلاف {number(change.difference_pp)}؛ "
            f"`{change.before_capture_id}` → `{change.after_capture_id}`."
        )
    lines += ["", "## شواهد قابل پیگیری", ""]
    for capture in report.captures:
        e = capture.evidence
        lines += [
            f"- [{cell(e.release_id)}]({e.source_url})؛ دورهٔ اصلی {e.headline_period}؛ "
            f"سرصفحه `{e.announced_at.isoformat()}`؛ ثبت `{e.captured_at.isoformat()}`؛ "
            f"وضعیت `{e.document_status}`؛ شناسهٔ ثبت `{capture.capture_id}`.",
            f"  یادداشت نسخه: {cell(e.revision_note)}",
        ]
    lines += [
        "",
        "## حدود تفسیر",
        "",
        "آرشیوهای بازانتشارشده ممکن است با نسخهٔ روز اول فرق داشته باشند. ساعت سرصفحه "
        "زمان دقیق اصلاح یا تحویل نیست. نسخهٔ تاریخی FRED فقط دقت روز دارد و از همان "
        "آمار BLS می‌آید؛ تأیید مستقل محسوب نمی‌شود. مقدارهای CPI از دو سطح شاخصِ "
        "همان vintage محاسبه شده‌اند. اختلاف نسخه‌ها، غافلگیری نسبت به انتظار بازار نیست.",
        "",
        "تاریخ دسترسی به عقب منتقل نشده است. کامل‌بودن این گزارش فقط به پنجره و "
        "معیار مقایسهٔ تعریف‌شده مربوط است؛ نسخهٔ اول و بازپخش درون‌روزی تأیید نشده‌اند. "
        "JSON همراه، برنامه، همهٔ ثبت‌ها، جای سلول‌ها، شناسهٔ خام و والدهای FRED را نگه می‌دارد.",
        "",
    ]
    return "\n".join(lines)
