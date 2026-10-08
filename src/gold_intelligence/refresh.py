"""One manual, checkpointed refresh; each acquisition keeps its own evidence manifest."""

import hashlib
import os
import re
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator

from . import __version__
from .acquisition import AcquisitionRun, acquire, write_manifest
from .alpha_vantage import DATASET as GOLD_DATASET
from .alpha_vantage import ingest_alpha_gold
from .cftc import DATASET as COT_DATASET
from .cftc import FIRST_DATE, MARKET, ingest_cftc_gold
from .ingestion import fetch_bytes
from .macro import fetch_reviewed_series
from .models import Contract, Hash, Timestamp
from .research_report import (
    ReportSettings,
    build_research_report,
    verify_research_bundle,
    write_research_report,
)
from .storage import canonical
from .world_bank import DATASET as WB_DATASET
from .world_bank import ingest_monthly_gold

FRED_START = date(1776, 7, 4)
AUTO_KEYS = ("alpha_vantage_gold", "world_bank_pink_sheet", "cftc_disaggregated")
MANUAL_INPUTS = ("bls_release_evidence", "bls_release_values", "fred_exact_vintages")


class RefreshPolicy(Contract):
    fred_overlap_days: int = Field(default=120, ge=1, le=3650)
    cot_overlap_days: int = Field(default=90, ge=14, le=3650)
    full_history: bool = False


class RefreshStep(Contract):
    key: str = Field(
        pattern=r"^(alpha_vantage_gold|world_bank_pink_sheet|cftc_disaggregated|fred:[A-Z0-9_]+)$"
    )
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    start: date | None = None
    end: date | None = None
    status: Literal["pending", "running", "succeeded", "failed", "interrupted"] = "pending"
    acquisition_status: Literal["not_started", "unavailable", "running", "succeeded", "failed"] = (
        "not_started"
    )
    inserted_records: int | None = Field(default=None, ge=0)
    referenced_records: int | None = Field(default=None, ge=0)
    failure_type: str | None = None
    failure_reason: str | None = Field(
        default=None,
        pattern=r"^(HTTP_[45][0-9]{2}|MISSING_CREDENTIALS|CONNECTION_FAILED|VALIDATION_FAILED|STORAGE_ERROR|INTERRUPTED|UNEXPECTED_ERROR)$",
    )

    @model_validator(mode="after")
    def consistent(self):
        if (self.start is None) != (self.end is None) or (
            self.start is not None and self.start > self.end
        ):
            raise ValueError("invalid refresh interval")
        if (self.status in {"failed", "interrupted"}) != (self.failure_type is not None):
            raise ValueError("refresh failure type disagrees with step state")
        if (self.failure_type is None) != (self.failure_reason is None):
            raise ValueError("failed refresh step requires a safe reason code")
        if self.status == "succeeded" and self.acquisition_status != "succeeded":
            raise ValueError("refresh success requires a completed acquisition trace")
        if self.acquisition_status in {"succeeded", "failed"}:
            if self.inserted_records is None or self.referenced_records is None:
                raise ValueError("completed acquisition requires counts")
            if self.inserted_records > self.referenced_records:
                raise ValueError("inserted records exceed referenced records")
        elif self.inserted_records is not None or self.referenced_records is not None:
            raise ValueError("unconfirmed acquisition cannot claim record counts")
        return self


class EvidenceFreshness(Contract):
    key: str
    status: Literal["current", "stale", "missing", "missing_value", "unchecked"]
    reference_at: Timestamp | None
    age_days: float | None = Field(ge=0)
    limit_days: float | None = Field(gt=0)


class RefreshReport(Contract):
    status: Literal["pending", "running", "succeeded", "failed", "skipped"] = "pending"
    as_of: Timestamp | None = None
    bundle: str | None = None
    fingerprint: Hash | None = None
    research_status: Literal["compiled", "with_limits", "partial"] | None = None
    freshness: tuple[EvidenceFreshness, ...] = ()
    calendar_status: str | None = None
    failure_type: str | None = None

    @model_validator(mode="after")
    def consistent(self):
        if (self.status == "failed") != (self.failure_type is not None):
            raise ValueError("report failure type disagrees with state")
        if self.status in {"running", "succeeded", "failed"} and self.as_of is None:
            raise ValueError("attempted report requires cutoff")
        if self.status == "succeeded":
            if not self.bundle or not self.fingerprint or not self.research_status:
                raise ValueError("report success requires verified output")
        elif self.bundle or self.fingerprint or self.research_status or self.freshness:
            raise ValueError("unfinished report cannot claim verified output")
        return self


def completed_status(steps, report):
    if report.status != "succeeded":
        return "failed"
    if (
        any(s.status != "succeeded" for s in steps)
        or report.research_status == "partial"
        or any(f.status != "current" for f in report.freshness)
        or report.calendar_status != "scheduled_events"
    ):
        return "partial"
    return "succeeded"


class RefreshRun(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    application_version: str
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    store_root: str
    started_at: Timestamp
    finished_at: Timestamp | None = None
    status: Literal["running", "succeeded", "partial", "failed", "interrupted"] = "running"
    policy: RefreshPolicy
    report_settings: ReportSettings
    registry_sha256: Hash
    steps: tuple[RefreshStep, ...]
    report: RefreshReport = Field(default_factory=RefreshReport)
    manual_inputs: tuple[
        Literal["bls_release_evidence", "bls_release_values", "fred_exact_vintages"], ...
    ] = MANUAL_INPUTS
    daily_backtest_ready: Literal[False] = False

    @model_validator(mode="after")
    def consistent(self):
        expected = {
            *AUTO_KEYS,
            *(f"fred:{s.series_id}" for s in self.report_settings.macro_plan.series),
        }
        if {s.key for s in self.steps} != expected or len(self.steps) != len(expected):
            raise ValueError("refresh must account for every requested source/series exactly once")
        if len({s.run_id for s in self.steps}) != len(self.steps):
            raise ValueError("duplicate acquisition run IDs")
        if self.manual_inputs != MANUAL_INPUTS:
            raise ValueError("manual evidence must remain explicitly outside refresh")
        if (self.status == "running") != (self.finished_at is None):
            raise ValueError("terminal refresh requires a finish timestamp")
        if self.finished_at and self.finished_at < self.started_at:
            raise ValueError("refresh finish precedes start")
        if self.report.as_of and (
            self.report.as_of < self.started_at
            or (self.finished_at and self.report.as_of > self.finished_at)
        ):
            raise ValueError("report cutoff outside refresh interval")
        if self.status in {"succeeded", "partial", "failed"}:
            if any(s.status not in {"succeeded", "failed"} for s in self.steps):
                raise ValueError("completed refresh has unfinished acquisitions")
            if self.report.status not in {"succeeded", "failed"}:
                raise ValueError("completed refresh must attempt its report")
            if self.status != completed_status(self.steps, self.report):
                raise ValueError("refresh summary disagrees with outcomes")
        if self.report.status == "succeeded":
            if {f.key for f in self.report.freshness} != expected or len(
                self.report.freshness
            ) != len(expected):
                raise ValueError("report must expose freshness for every automatic input")
        return self


@contextmanager
def refresh_lock(root):
    """OS-owned lock: concurrent refreshes fail; process termination releases the lock."""
    with (root / "refresh.lock").open("a+b") as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError("another refresh owns this store's refresh lock") from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def overlap_start(latest, end, days, first, full_history):
    if full_history or latest is None:
        return first
    # An old local store must also cover the entire gap since its last observation.
    return max(first, min(end, latest) - timedelta(days=days))


def fred_overlap_start(latest, end, days, frequency, full_history):
    start = overlap_start(latest, end, days, FRED_START, full_history)
    if start == FRED_START:
        return start
    # Period labels can precede a mid-period request boundary. Request whole periods;
    # keep the existing adapter's strict out-of-range check instead of discarding rows.
    if frequency == "M":
        start = start.replace(day=1)
    elif frequency == "Q":
        start = start.replace(month=1 + 3 * ((start.month - 1) // 3), day=1)
    elif frequency == "W" and latest is not None:
        start -= timedelta(days=(start.weekday() - latest.weekday()) % 7)
    return max(FRED_START, start)


def plan_steps(store, settings, policy, started):
    end = started.date()
    if end < FIRST_DATE:
        raise ValueError("refresh date precedes supported COT history")
    observations = store.read("observation", started)
    positions = store.read("positioning", started)
    steps = [RefreshStep(key=k, run_id=uuid4().hex) for k in AUTO_KEYS[:2]]
    for spec in settings.macro_plan.series:
        dates = [
            r.provenance.observed_at.date()
            for r in observations
            if r.provenance.source_id == "fred"
            and r.provenance.dataset == spec.series_id
            and r.series_id == spec.series_id
            and r.layer == "macro"
            and r.provenance.unit == spec.unit
            and r.provenance.currency == spec.currency
            and not r.provenance.synthetic
            and r.vintage_date is None
            and not (set(r.dimensions) - {"realtime_start", "realtime_end"})
        ]
        steps.append(
            RefreshStep(
                key=f"fred:{spec.series_id}",
                run_id=uuid4().hex,
                start=fred_overlap_start(
                    max(dates, default=None),
                    end,
                    policy.fred_overlap_days,
                    spec.frequency,
                    policy.full_history,
                ),
                end=end,
            )
        )
    dates = [
        r.provenance.observed_at.date()
        for r in positions
        if r.provenance.source_id == "cftc_disaggregated"
        and r.provenance.dataset == COT_DATASET
        and r.market_code == MARKET
        and not r.provenance.synthetic
    ]
    steps.append(
        RefreshStep(
            key="cftc_disaggregated",
            run_id=uuid4().hex,
            start=overlap_start(
                max(dates, default=None),
                end,
                policy.cot_overlap_days,
                FIRST_DATE,
                policy.full_history,
            ),
            end=end,
        )
    )
    return tuple(steps)


def execute_step(store, registry, settings, step):
    key = step.key
    if key == "alpha_vantage_gold":
        operation, parameters = (
            "fetch-alpha-gold",
            dict(source=key, instrument="XAUUSD", timeframe="1d"),
        )

        def execute():
            return ingest_alpha_gold(store, registry.get(key))
    elif key == "world_bank_pink_sheet":
        operation, parameters = (
            "fetch-worldbank-gold",
            dict(source=key, instrument="GOLD", timeframe="1mo"),
        )

        def execute():
            return ingest_monthly_gold(store, registry.get(key))
    elif key == "cftc_disaggregated":
        operation = "fetch-cftc-gold"
        parameters = dict(source=key, market_code=MARKET, start=str(step.start), end=str(step.end))

        def execute():
            return ingest_cftc_gold(store, registry.get(key), step.start, step.end)
    else:
        spec = next(s for s in settings.macro_plan.series if key == f"fred:{s.series_id}")
        operation = "fetch-fred-reviewed"
        parameters = dict(
            source="fred",
            series=spec.series_id,
            unit=spec.unit,
            currency=spec.currency,
            start=str(step.start),
            end=str(step.end),
            vintage=None,
        )

        def execute():
            store.put_raw(settings.macro_plan.model_dump_json().encode())
            return fetch_reviewed_series(
                store, registry.get("fred"), spec, step.start, step.end, None, fetch_bytes
            )

    return acquire(store, operation, parameters, execute, run_id=step.run_id)


def safe_failure_reason(failure):
    if failure is None:
        return None
    if not isinstance(failure, Exception):
        return "INTERRUPTED"
    # Only recognize the transport's own exact sanitized messages, never serialize
    # arbitrary exception text or provider bodies, even when they contain key URLs.
    message = str(failure)
    match = re.fullmatch(r"provider request failed with HTTP ([45][0-9]{2})", message)
    if match:
        return "HTTP_" + match[1]
    if message == "provider connection failed after bounded retries":
        return "CONNECTION_FAILED"
    if message in {
        "set FRED_API_KEY before fetching",
        "set FRED_API_KEY in the environment before fetching",
        "set ALPHAVANTAGE_API_KEY before fetching",
    }:
        return "MISSING_CREDENTIALS"
    if isinstance(failure, OSError):
        return "STORAGE_ERROR"
    return "VALIDATION_FAILED" if isinstance(failure, ValueError) else "UNEXPECTED_ERROR"


def step_outcome(store, step, failure=None):
    # A missing/unfinished trace is a failure, even if the adapter returned normally.
    try:
        trace = AcquisitionRun.model_validate_json(
            (store.root / "runs" / f"{step.run_id}.json").read_bytes()
        )
        if trace.run_id != step.run_id:
            raise ValueError("acquisition trace identity differs")
        trace_state = trace.status
    except (ValueError, OSError):
        trace, trace_state = None, "unavailable"
    if failure is None and trace_state != "succeeded":
        failure = RuntimeError()
    state = (
        "succeeded"
        if failure is None
        else "failed"
        if isinstance(failure, Exception)
        else "interrupted"
    )
    return RefreshStep.model_validate(
        {
            **step.model_dump(),
            "status": state,
            "acquisition_status": trace_state,
            "failure_type": type(failure).__name__ if failure is not None else None,
            "failure_reason": safe_failure_reason(failure),
            "inserted_records": trace.inserted_records
            if trace_state in {"succeeded", "failed"}
            else None,
            "referenced_records": len(trace.record_ids)
            if trace_state in {"succeeded", "failed"}
            else None,
        }
    )


def report_freshness(report):
    rows = []
    for key, kind, dataset in (
        ("alpha_vantage_gold", "price_close", GOLD_DATASET),
        ("world_bank_pink_sheet", "observation", WB_DATASET),
    ):
        streams = [
            s
            for s in report.quality.streams
            if s.identity.get("source_id") == key
            and s.identity.get("kind") == kind
            and s.identity.get("dataset") == dataset
            and not s.identity.get("synthetic")
        ]
        # WB intentionally has two methodological eras. Their compatible period
        # coverage can supply a latest date; the report retains both original streams.
        wb_compatible = key == "world_bank_pink_sheet" and all(
            s.identity.get("unit") == "currency_per_troy_ounce"
            and s.identity.get("currency") == "USD"
            and s.identity.get("series_id") == "WB_GOLD_MONTHLY"
            and s.identity.get("layer") == "price"
            and s.identity.get("vintage_date") is None
            and s.identity.get("dimensions")
            in (
                {
                    "aggregation": "monthly_average",
                    "frequency": "1mo",
                    "instrument": "GOLD",
                    "methodology": method,
                }
                for method in ("london_afternoon_fixing_average", "spot_daily_average")
            )
            for s in streams
        )
        stream = (
            max(streams, key=lambda s: s.last_observed_at)
            if streams and wb_compatible
            else streams[0]
            if len(streams) == 1 and key != "world_bank_pink_sheet"
            else None
        )
        limit = (
            stream.freshness_limit_hours / 24 if stream and stream.freshness_limit_hours else None
        )
        age = stream.age_hours / 24 if stream else None
        state = (
            "missing"
            if not streams
            else "unchecked"
            if stream is None or limit is None
            else "stale"
            if age > limit
            else "current"
        )
        rows.append(
            EvidenceFreshness(
                key=key,
                status=state,
                reference_at=stream.last_observed_at if stream else None,
                age_days=age,
                limit_days=limit,
            )
        )
    for entry in report.macro.entries:
        rows.append(
            EvidenceFreshness(
                key=f"fred:{entry.series_id}",
                status="current" if entry.status == "available" else entry.status,
                reference_at=entry.reference_at,
                age_days=entry.reference_age_days,
                limit_days=entry.max_age_days,
            )
        )
    cot = report.positioning
    latest = max((w.observed_date for w in cot.weeks), default=None)
    rows.append(
        EvidenceFreshness(
            key="cftc_disaggregated",
            status="missing"
            if cot.status == "no_data"
            else "stale"
            if cot.status == "stale"
            else "current",
            reference_at=datetime.combine(latest, datetime.min.time(), UTC) if latest else None,
            age_days=cot.latest_observation_age_days,
            limit_days=cot.max_age_days,
        )
    )
    return tuple(rows)


FA = {
    "running": "در حال اجرا",
    "pending": "هنوز شروع نشده",
    "succeeded": "موفق",
    "failed": "ناموفق",
    "interrupted": "متوقف‌شده",
    "partial": "ناقص / نیازمند بررسی",
    "current": "در محدودهٔ سن مجاز",
    "stale": "قدیمی",
    "missing": "داده موجود نیست",
    "missing_value": "مقدار آخر مفقود است",
    "unchecked": "تازگی تأیید نشده",
    "skipped": "اجرا نشده",
}


def render_refresh(run):
    lines = [
        "# نتیجهٔ به‌روزرسانی و گزارش",
        "",
        f"وضعیت کل: **{FA[run.status]}**؛ شناسه: `{run.run_id}`.",
        f"شروع: `{run.started_at.isoformat()}`؛ "
        f"پایان: `{run.finished_at.isoformat() if run.finished_at else '—'}`.",
        "",
        "موفقیت دریافت با تازه‌بودن دورهٔ داده متفاوت است. اگر دریافت شکست بخورد، "
        "گزارش ممکن است از دادهٔ قبلی پایگاه استفاده کند؛ جدول زیر آن شکست را حفظ می‌کند.",
        "",
        "| منبع / سری | نتیجهٔ دریافت | بازهٔ درخواستی | رکورد درج‌شده | "
        "وضعیت سند دریافت | شناسهٔ دریافت / نوع خطا |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for step in run.steps:
        bounds = f"{step.start} تا {step.end}" if step.start else "کل تاریخچهٔ ارائه‌شده"
        count = step.inserted_records if step.inserted_records is not None else "—"
        lines.append(
            f"| {step.key} | {FA[step.status]} | {bounds} | {count} | "
            f"{step.acquisition_status} | `{step.run_id}` / {step.failure_reason or '—'} |"
        )
    lines += [
        "",
        "سند هر دریافت در `STORE/runs/<شناسه>.json` قرار دارد. "
        "درج نسخهٔ تازه به معنی تغییر عدد نیست؛ دریافت مجددِ همان عدد هم شاهد تازه می‌سازد.",
        "",
        f"ساخت گزارش: **{FA[run.report.status]}**.",
    ]
    if run.report.status == "succeeded":
        lines += [
            f"[گزارش پژوهش فارسی]({run.report.bundle}/research-report.fa.md)؛ "
            f"وضعیت محتوای گزارش: `{run.report.research_status}`.",
            f"زمان برش مشترک: `{run.report.as_of.isoformat()}`؛ "
            f"هش معنایی: `{run.report.fingerprint}`.",
            "",
            "| ورودی گزارش | وضعیت تازگی | آخرین تاریخ / دورهٔ مرجع | "
            "سن (روز) | آستانهٔ داخلی (روز) |",
            "| --- | --- | --- | --- | --- |",
        ]
        for row in run.report.freshness:
            age = f"{row.age_days:.2f}" if row.age_days is not None else "—"
            limit = f"{row.limit_days:g}" if row.limit_days is not None else "—"
            reference = str(row.reference_at.date()) if row.reference_at else "—"
            lines.append(f"| {row.key} | {FA[row.status]} | {reference} | {age} | {limit} |")
        lines += [
            "",
            "سن داده از تاریخ مشاهده/دوره محاسبه شده؛ آستانه‌ها سیاست داخلی‌اند "
            "و تقویم رسمی انتشار نیستند. عدد مفقود با عدد قبلی پر نشده است.",
            f"وضعیت شواهد تقویم: `{run.report.calendar_status}`؛ "
            "سن هر شاهد در گزارش پژوهش آمده است.",
        ]
    elif run.report.failure_type:
        lines += [
            f"نوع خطای ساخت گزارش: `{run.report.failure_type}`. "
            "خروجی قبلی جایگزین این اجرا نشده است."
        ]
    lines += [
        "",
        "## ورودی‌هایی که این دستور به‌روز نمی‌کند",
        "",
        "اسناد و تقویم بررسی‌شدهٔ BLS، مقدارهای رونویسی‌شدهٔ انتشار، "
        "و نسخه‌های FRED با تاریخ تاریخی مشخص، خودکار دریافت نمی‌شوند. "
        "شواهد قبلی با سن و محدودیت خودشان استفاده می‌شوند؛ "
        "برای شواهد تازه باید مسیر بازبینی و ورود مربوط اجرا شود.",
        "",
        f"هم‌پوشانی FRED: {run.policy.fred_overlap_days} روز؛ "
        f"COT: {run.policy.cot_overlap_days} روز؛ بازخوانی کامل: `{run.policy.full_history}`.",
        "پنجرهٔ هم‌پوشان اصلاحیه‌های بیرون از آن را کشف نمی‌کند. "
        "موفقیت این اجرا تأیید دقت منبع، ساعت انتشار تاریخی یا آمادگی بک‌تست روزانه نیست.",
        "",
    ]
    return "\n".join(lines)


def refresh_and_report(store, registry, settings, policy, output_dir):
    # Validate before network I/O, including model_copy() callers that bypass validation.
    settings = ReportSettings.model_validate(settings.model_dump())
    policy = RefreshPolicy.model_validate(policy.model_dump())
    for key in (*AUTO_KEYS, "fred"):
        registry.get(key)
    with refresh_lock(store.root), store.writer_lock():
        started = datetime.now(UTC)
        run = RefreshRun(
            application_version=__version__,
            run_id=uuid4().hex,
            store_root=str(store.root.resolve()),
            started_at=started,
            policy=policy,
            report_settings=settings,
            registry_sha256=hashlib.sha256(
                canonical(registry.model_dump(mode="json")).encode()
            ).hexdigest(),
            steps=plan_steps(store, settings, policy, started),
        )
        directory = output_dir / f"refresh-{started.strftime('%Y%m%dT%H%M%S%fZ')}-{run.run_id}"
        directory.mkdir(parents=True)

        def checkpoint(**changes):
            nonlocal run
            run = RefreshRun.model_validate({**run.model_dump(), **changes})
            write_manifest(directory / "refresh-run.json", run)

        def replace_step(index, step):
            steps = list(run.steps)
            steps[index] = step
            checkpoint(steps=steps)

        checkpoint()
        try:
            for index, step in enumerate(run.steps):
                replace_step(
                    index,
                    step.model_copy(
                        update={"status": "running", "acquisition_status": "unavailable"}
                    ),
                )
                try:
                    execute_step(store, registry, settings, step)
                except BaseException as exc:
                    replace_step(index, step_outcome(store, step, exc))
                    if not isinstance(exc, Exception):
                        raise
                else:
                    replace_step(index, step_outcome(store, step))
            cutoff = datetime.now(UTC)
            checkpoint(report=RefreshReport(status="running", as_of=cutoff))
            try:
                report = build_research_report(store, registry, settings, cutoff)
                bundle = write_research_report(report, directory / "reports")
                verify_research_bundle(bundle)
                result = RefreshReport(
                    status="succeeded",
                    as_of=cutoff,
                    bundle=bundle.relative_to(directory).as_posix(),
                    fingerprint=report.fingerprint,
                    research_status=report.status,
                    freshness=report_freshness(report),
                    calendar_status=report.calendar.status,
                )
            except Exception as exc:
                result = RefreshReport(
                    status="failed", as_of=cutoff, failure_type=type(exc).__name__
                )
            checkpoint(
                report=result,
                status=completed_status(run.steps, result),
                finished_at=datetime.now(UTC),
            )
        except BaseException:
            # A checkpoint/disk failure may itself prevent this best-effort final write.
            pending = run.report.status in {"pending", "running"}
            checkpoint(
                status="interrupted",
                finished_at=datetime.now(UTC),
                report=RefreshReport(status="skipped") if pending else run.report,
            )
            (directory / "refresh.fa.md").write_text(render_refresh(run), encoding="utf-8")
            raise
        (directory / "refresh.fa.md").write_text(render_refresh(run), encoding="utf-8")
        return run, directory
