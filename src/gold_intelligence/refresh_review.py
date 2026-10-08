"""Auditable post-refresh review, rebuilt from copied inputs without a database."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator

from . import __version__
from .brief import cell
from .models import Contract, Hash, Timestamp
from .refresh import RefreshRun
from .report_comparison import ReportComparison, compare_snapshots
from .research_report import LABELS, load_verified_report, parse_research_report
from .storage import canonical

BaselineState = Literal["selected", "missing", "failed"]
CHANGE_KINDS = ("numeric", "result", "missingness", "view", "evidence", "age")


def digest(content):
    return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True)
class Baseline:
    status: BaselineState
    content: bytes | None = None
    failure_type: str | None = None


def select_baseline(output_dir, explicit=None, store_root=None):
    """Select once before acquisition. Never fall back after a corrupt candidate."""
    try:
        if explicit is not None:
            report, _, content = load_verified_report(explicit)
        else:
            if output_dir is None:
                return Baseline("missing")
            candidates = []
            for path in Path(output_dir).glob("refresh-*/refresh-run.json"):
                run = RefreshRun.model_validate_json(path.read_bytes())
                if (
                    store_root is not None
                    and Path(run.store_root).resolve() != Path(store_root).resolve()
                ):
                    continue
                if run.status in {"succeeded", "partial"} and run.report.status == "succeeded":
                    bundle = (path.parent / run.report.bundle).resolve()
                    if not bundle.is_relative_to(path.parent.resolve()):
                        raise ValueError("baseline bundle escaped its refresh directory")
                    candidates.append((run.report.as_of, bundle, run.report.fingerprint))
            if not candidates:
                return Baseline("missing")
            candidates.sort(key=lambda item: (item[0], str(item[1])))
            newest = [item for item in candidates if item[0] == candidates[-1][0]]
            if len(newest) != 1:
                raise ValueError("ambiguous latest baseline")
            _, bundle, expected = newest[0]
            report, _, content = load_verified_report(bundle)
            if report.fingerprint != expected or report.as_of != newest[0][0]:
                raise ValueError("baseline differs from its refresh trace")
        if report.as_of > datetime.now(UTC):
            raise ValueError("future baseline")
        return Baseline("selected", content)
    except Exception as exc:
        return Baseline("failed", failure_type=type(exc).__name__)


def change_kind(field):
    if not field.before_present or not field.after_present:
        return "view"
    if field.category != "result":
        return field.category
    if field.before is None or field.after is None:
        return "missingness"
    if type(field.before) in {int, float} and type(field.after) in {int, float}:
        return "numeric"
    return "result"


class ReviewPriority(Contract):
    priority: Literal[1, 2, 3]
    code: str
    subject: str
    message: str
    input_path: Literal["inputs/refresh-run.json", "inputs/after.json", "review.json"]
    pointer: str = Field(pattern=r"^/")


def review_fingerprint(payload):
    data = {k: v for k, v in payload.items() if k not in {"fingerprint", "generated_at"}}
    if data.get("comparison") is not None:
        data["comparison"] = {k: v for k, v in data["comparison"].items() if k != "generated_at"}
    return digest(canonical(data).encode())


class RefreshReview(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    application_version: str
    generated_at: Timestamp
    fingerprint: Hash
    refresh_run_id: str
    refresh_sha256: Hash
    after_sha256: Hash | None
    before_sha256: Hash | None
    baseline_status: BaselineState
    baseline_failure_type: str | None
    status: Literal[
        "compared", "no_baseline", "baseline_failed", "comparison_failed", "report_failed"
    ]
    failure_type: str | None
    comparison: ReportComparison | None
    field_counts: dict[str, int]
    priorities: tuple[ReviewPriority, ...]
    daily_backtest_ready: Literal[False] = False
    causal_attribution: Literal[False] = False

    @model_validator(mode="after")
    def consistent(self):
        if set(self.field_counts) != set(CHANGE_KINDS) or any(
            value < 0 for value in self.field_counts.values()
        ):
            raise ValueError("invalid change counts")
        if (self.baseline_status == "selected") != (self.before_sha256 is not None):
            raise ValueError("baseline state disagrees with copied evidence")
        if (self.baseline_status == "failed") != (self.baseline_failure_type is not None):
            raise ValueError("baseline failure must be explicit")
        if (self.status == "compared") != (self.comparison is not None):
            raise ValueError("comparison state disagrees with output")
        if (self.status in {"comparison_failed", "report_failed"}) != (
            self.failure_type is not None
        ):
            raise ValueError("review failure must be explicit")
        if self.comparison:
            if self.comparison.before.report_sha256 != self.before_sha256 or (
                self.comparison.after.report_sha256 != self.after_sha256
            ):
                raise ValueError("comparison differs from copied inputs")
            expected = dict.fromkeys(CHANGE_KINDS, 0)
            for row in self.comparison.changes:
                for field in row.fields:
                    expected[change_kind(field)] += 1
            if self.field_counts != expected:
                raise ValueError("change counts differ from comparison")
        elif any(self.field_counts.values()):
            raise ValueError("uncompared review cannot claim changes")
        if self.fingerprint != review_fingerprint(self.model_dump(mode="json")):
            raise ValueError("review fingerprint mismatch")
        return self


def build_review(run_bytes, after_bytes, baseline, generated_at=None, version=__version__):
    run = RefreshRun.model_validate_json(run_bytes)
    if run.status == "running":
        raise ValueError("cannot review an unfinished refresh")
    report = parse_research_report(after_bytes) if after_bytes is not None else None
    if (run.report.status == "succeeded") != (report is not None):
        raise ValueError("current report disagrees with refresh state")
    if report and (
        report.fingerprint != run.report.fingerprint or report.as_of != run.report.as_of
    ):
        raise ValueError("current report differs from refresh trace")
    comparison, failure = None, None
    clock = generated_at or datetime.now(UTC)
    if not report:
        status, failure = "report_failed", run.report.failure_type or "ReportUnavailable"
    elif baseline.status == "missing":
        status = "no_baseline"
    elif baseline.status == "failed":
        status = "baseline_failed"
    else:
        try:
            before = parse_research_report(baseline.content)
            if before.as_of > run.started_at:
                raise ValueError("baseline cutoff must precede refresh start")
            comparison = compare_snapshots(
                baseline.content,
                after_bytes,
                "inputs/before.json",
                "inputs/after.json",
                version,
                clock,
            )
            status = "compared"
        except Exception as exc:
            status, failure = "comparison_failed", type(exc).__name__
    priorities = []

    def add(priority, code, subject, message, path, pointer):
        priorities.append(
            ReviewPriority(
                priority=priority,
                code=code,
                subject=subject,
                message=message,
                input_path=path,
                pointer=pointer,
            )
        )

    if not report:
        add(
            1,
            "REPORT_UNAVAILABLE",
            "report",
            "گزارش جاری ساخته یا بررسی نشده است.",
            "inputs/refresh-run.json",
            "/report",
        )
    for index, step in enumerate(run.steps):
        if step.status != "succeeded":
            add(
                1,
                "ACQUISITION_FAILED",
                step.key,
                f"دریافت موفق نیست: {step.status} / {step.failure_reason or 'NOT_COMPLETED'}؛ "
                "دادهٔ قبلی در گزارش، دریافت تازه محسوب نمی‌شود.",
                "inputs/refresh-run.json",
                f"/steps/{index}",
            )
    for index, fresh in enumerate(run.report.freshness):
        if fresh.status != "current":
            add(
                1,
                "FRESHNESS_REVIEW",
                fresh.key,
                f"وضعیت سن یا مقدار: {fresh.status}.",
                "inputs/refresh-run.json",
                f"/report/freshness/{index}",
            )
    if baseline.status != "selected":
        add(
            2,
            "BASELINE_MISSING" if baseline.status == "missing" else "BASELINE_FAILED",
            "baseline",
            "مبنای مقایسه موجود نیست یا بررسی آن شکست خورده؛ تغییرات نامعلوم‌اند.",
            "review.json",
            "/baseline_status",
        )
    if status == "comparison_failed":
        add(
            1,
            "COMPARISON_FAILED",
            "comparison",
            "مقایسه شکست خورده؛ ثبات داده ادعا نمی‌شود.",
            "review.json",
            "/status",
        )
    if report:
        for index, section in enumerate(report.sections):
            if section.status != "available":
                add(
                    2,
                    "SECTION_LIMIT",
                    section.key,
                    f"{LABELS[section.key]}: {section.status}؛ جزئیات محدودیت بررسی شود.",
                    "inputs/after.json",
                    f"/sections/{index}",
                )
        if run.report.calendar_status != "scheduled_events":
            add(
                1,
                "CALENDAR_REVIEW",
                "calendar",
                "پوشش یا شاهد تقویم جاری نیازمند بررسی است.",
                "inputs/after.json",
                "/calendar",
            )
    counts = dict.fromkeys(CHANGE_KINDS, 0)
    if comparison:
        if comparison.context_changes:
            add(
                2,
                "CONTEXT_CHANGED",
                "context",
                "زمان برش، نسخه یا تنظیمات تغییر کرده؛ اختلاف خروجی لزوماً اقتصادی نیست.",
                "review.json",
                "/comparison/context_changes",
            )
        for index, section in enumerate(comparison.sections):
            if section.comparison_basis != "both_present":
                add(
                    2,
                    "SCHEMA_INCOMPARABLE",
                    section.key,
                    "این بخش در قالب یکی از ورودی‌ها نیست؛ با دادهٔ مفقود یا صفر یکی نیست.",
                    "review.json",
                    f"/comparison/sections/{index}",
                )
        for row in comparison.changes:
            for field in row.fields:
                counts[change_kind(field)] += 1
        definition_changes = [
            index
            for index, row in enumerate(comparison.changes)
            if any(
                field.path.rsplit("/", 1)[-1]
                in {"unit", "method", "source_id", "dataset", "frequency", "currency"}
                for field in row.fields
            )
        ]
        if definition_changes:
            add(
                2,
                "DEFINITION_REVIEW",
                "definitions",
                "تغییر منبع، واحد یا روش و ورود/خروج هویت‌ها باید بررسی شود؛ "
                "اختلاف عدد میان تعریف‌های متفاوت محاسبه نمی‌شود.",
                "review.json",
                "/comparison/changes",
            )
        for key, label in (
            ("numeric", "عدد"),
            ("missingness", "مقدار مفقود"),
            ("view", "حضور در نما"),
        ):
            if counts[key]:
                add(
                    2,
                    "CHANGES_TO_REVIEW",
                    key,
                    f"{counts[key]} فیلد با تغییر {label}؛ مسیرها در جزئیات مقایسه ثبت شده‌اند.",
                    "review.json",
                    "/comparison/changes",
                )
    add(
        3,
        "MANUAL_INPUTS",
        "manual",
        "شواهد BLS و vintageهای دقیق با این گردش خودکار به‌روز نمی‌شوند.",
        "inputs/refresh-run.json",
        "/manual_inputs",
    )
    data = dict(
        schema_version="1.0.0",
        application_version=version,
        generated_at=clock.isoformat(),
        refresh_run_id=run.run_id,
        refresh_sha256=digest(run_bytes),
        after_sha256=digest(after_bytes) if after_bytes is not None else None,
        before_sha256=digest(baseline.content) if baseline.content is not None else None,
        baseline_status=baseline.status,
        baseline_failure_type=baseline.failure_type,
        status=status,
        failure_type=failure,
        comparison=comparison.model_dump(mode="json") if comparison else None,
        field_counts=counts,
        priorities=[
            p.model_dump(mode="json") for p in sorted(priorities, key=lambda p: p.priority)
        ],
        daily_backtest_ready=False,
        causal_attribution=False,
    )
    return RefreshReview.model_validate({**data, "fingerprint": review_fingerprint(data)})


def render_review(review):
    lines = [
        "# چه چیزی تغییر کرده و چه چیزی نیازمند بررسی است؟",
        "",
        f"وضعیت خلاصه: `{review.status}`؛ اجرای دریافت: `{review.refresh_run_id}`.",
        "اولویت‌ها قواعد بررسی داده‌اند؛ سیگنال معامله یا احتمال سود نیستند.",
        "",
    ]
    if review.comparison:
        comparison = review.comparison
        lines.extend(
            [
                f"برش مبنا: `{comparison.before.as_of.isoformat()}`؛ "
                f"برش جاری: `{comparison.after.as_of.isoformat()}`.",
                f"نتیجهٔ مقایسه: `{comparison.status}`.",
                "",
            ]
        )
        lines.extend(
            [
                "## وضعیت بخش‌ها",
                "",
                "| بخش | وضعیت مبنا | وضعیت جاری | ورود / خروج / تغییر | مبنای مقایسه |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for section in comparison.sections:
            lines.append(
                f"| {LABELS[section.key]} | {section.before_status} | {section.after_status} | "
                f"{section.added} / {section.removed} / {section.modified} | "
                f"{section.comparison_basis} |"
            )
        lines.append("")
        if comparison.context_changes:
            lines.extend(
                [
                    "## زمینهٔ محاسبه",
                    "",
                    "زمینه جدا از عددهای گزارش مقایسه می‌شود. مسیرهای تغییرکرده:",
                    "",
                    *[f"- `{field.path}`" for field in comparison.context_changes],
                    "",
                ]
            )
        labels = dict(
            numeric="عدد",
            result="نتیجه یا وضعیت",
            missingness="مقدار تهی",
            view="ورود یا خروج از نما",
            evidence="شاهد",
            age="سن",
        )
        lines.extend(["| نوع تغییر فیلد | تعداد |", "| --- | --- |"])
        lines.extend(f"| {labels[key]} | {review.field_counts[key]} |" for key in CHANGE_KINDS)
        lines.extend(
            [
                "",
                "این تعدادها مربوط به فیلدهای گزارش‌اند؛ تعداد رخداد اقتصادی مستقل نیستند.",
                "ثبات پوشش قیمت، برابری همهٔ قیمت‌های پایگاه را اثبات نمی‌کند.",
                "",
            ]
        )
        numeric = [
            (i, row, field)
            for i, row in enumerate(comparison.changes)
            for field in row.fields
            if change_kind(field) in {"numeric", "missingness"}
        ]
        if numeric:
            lines.extend(
                [
                    "## نمونهٔ تغییر عدد و مقدار مفقود",
                    "",
                    "| بخش / ردیف | فیلد | قبل | بعد | شاهد |",
                    "| --- | --- | --- | --- | --- |",
                ]
            )
            for index, row, field in numeric[:15]:
                lines.append(
                    f"| {cell(LABELS[row.section] + ' / ' + row.label)} | {cell(field.path)} | "
                    f"{cell(json.dumps(field.before, ensure_ascii=False))} | "
                    f"{cell(json.dumps(field.after, ensure_ascii=False))} | "
                    f"[جزئیات](review.json) `/comparison/changes/{index}` |"
                )
            lines.extend(
                [
                    "",
                    f"نمایش حداکثر ۱۵ مورد از {len(numeric)} فیلد؛ "
                    "تمام تغییرات، مسیر دو طرف و شناسه‌های شاهد در JSON موجود است.",
                    "",
                ]
            )
    else:
        lines.extend(["تغییرات مقایسه نشده‌اند؛ نبود مقایسه به معنی نبود تغییر نیست.", ""])
    lines.extend(
        ["## اولویت بررسی", "", "| اولویت | موضوع | مورد | شاهد |", "| --- | --- | --- | --- |"]
    )
    for item in review.priorities:
        lines.append(
            f"| {item.priority} | {cell(item.subject)} | {cell(item.message)} | "
            f"[ورودی]({item.input_path}) `{item.pointer}` |"
        )
    lines.extend(
        [
            "",
            "۱: خطای عملیاتی، تازگی یا مقایسه؛ ۲: محدودیت و تغییر نیازمند تفسیر؛ "
            "۳: یادآوری روش. اختلاف‌ها علت اقتصادی یا آمادگی بک‌تست را ثابت نمی‌کنند.",
            "",
        ]
    )
    return "\n".join(lines)


class ReviewFile(Contract):
    path: Literal[
        "review.json",
        "review.fa.md",
        "inputs/refresh-run.json",
        "inputs/before.json",
        "inputs/after.json",
    ]
    sha256: Hash
    bytes: int = Field(ge=0)


class ReviewManifest(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    fingerprint: Hash
    files: tuple[ReviewFile, ...]

    @model_validator(mode="after")
    def unique(self):
        names = [item.path for item in self.files]
        if len(set(names)) != len(names) or not {
            "review.json",
            "review.fa.md",
            "inputs/refresh-run.json",
        }.issubset(names):
            raise ValueError("incomplete or duplicate review files")
        return self


def write_refresh_review(directory, baseline):
    directory = Path(directory)
    run_bytes = (directory / "refresh-run.json").read_bytes()
    run = RefreshRun.model_validate_json(run_bytes)
    after = None
    if run.report.status == "succeeded":
        bundle = (directory / run.report.bundle).resolve()
        if not bundle.is_relative_to(directory.resolve()):
            raise ValueError("current bundle escaped refresh directory")
        _, _, after = load_verified_report(bundle)
    review = build_review(run_bytes, after, baseline)
    outputs = {
        "review.json": (review.model_dump_json(indent=2) + "\n").encode(),
        "review.fa.md": render_review(review).encode(),
        "inputs/refresh-run.json": run_bytes,
    }
    if after is not None:
        outputs["inputs/after.json"] = after
    if baseline.content is not None:
        outputs["inputs/before.json"] = baseline.content
    manifest = ReviewManifest(
        fingerprint=review.fingerprint,
        files=tuple(
            ReviewFile(path=name, sha256=digest(content), bytes=len(content))
            for name, content in sorted(outputs.items())
        ),
    )
    parent = directory / "reviews"
    parent.mkdir(exist_ok=True)
    suffix = uuid4().hex
    staging = parent / f".incomplete-{suffix}"
    staging.mkdir()
    (staging / "inputs").mkdir()
    for name, content in outputs.items():
        (staging / name).write_bytes(content)
    (staging / "manifest.json").write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    verify_review(staging)
    destination = parent / f"review-{review.generated_at:%Y%m%dT%H%M%S%fZ}-{suffix[:8]}"
    staging.rename(destination)
    return review, destination


def verify_review(directory):
    directory = Path(directory).resolve()
    manifest = ReviewManifest.model_validate_json((directory / "manifest.json").read_bytes())
    contents = {}
    for item in manifest.files:
        path = (directory / item.path).resolve()
        if not path.is_relative_to(directory):
            raise ValueError("review artifact escaped bundle directory")
        content = path.read_bytes()
        if len(content) != item.bytes or digest(content) != item.sha256:
            raise ValueError("review artifact hash mismatch")
        contents[item.path] = content
    saved = RefreshReview.model_validate_json(contents["review.json"])
    expected_files = {"review.json", "review.fa.md", "inputs/refresh-run.json"}
    if saved.after_sha256 is not None:
        expected_files.add("inputs/after.json")
    if saved.before_sha256 is not None:
        expected_files.add("inputs/before.json")
    if set(contents) != expected_files:
        raise ValueError("review file set differs from input state")
    baseline = Baseline(
        saved.baseline_status, contents.get("inputs/before.json"), saved.baseline_failure_type
    )
    expected = build_review(
        contents["inputs/refresh-run.json"],
        contents.get("inputs/after.json"),
        baseline,
        saved.generated_at,
        saved.application_version,
    )
    if saved != expected or saved.fingerprint != manifest.fingerprint:
        raise ValueError("review differs from recomputed inputs")
    if contents["review.fa.md"] != render_review(expected).encode():
        raise ValueError("review prose differs from recomputed inputs")
    return {
        "status": "verified",
        "review_status": saved.status,
        "files": len(contents),
        "fingerprint": saved.fingerprint,
    }
