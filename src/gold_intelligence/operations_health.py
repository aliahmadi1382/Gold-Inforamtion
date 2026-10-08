"""Offline operational evidence; never infer provider quota or historical runtime."""

import hashlib
import platform
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from . import __version__
from .acquisition import AcquisitionRun, write_manifest
from .models import Contract, Hash, Timestamp
from .refresh import RefreshRun
from .store_lock import store_lock


class HealthRun(Contract):
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    manifest_sha256: Hash
    operation: str
    identity_sha256: Hash
    started_at: Timestamp
    finished_at: Timestamp | None
    status: Literal["running", "succeeded", "failed"]
    inserted_records: int = Field(ge=0)
    # Old manifests contain exception class names only: do not copy arbitrary text.
    failure_category: Literal["none", "interrupted", "storage", "validation", "unknown"]
    failure_reason: str | None = None
    retry_action: Literal[
        "none",
        "inspect_unfinished",
        "check_quota_before_manual_retry",
        "manual_retry_after_transport_budget",
        "repair_before_retry",
        "inspect_before_retry",
    ]
    consecutive_failures: int = Field(ge=0)
    is_latest: bool
    quota_status: Literal["not_measured"] = "not_measured"
    historical_runtime: Literal["not_recorded"] = "not_recorded"


class OperationsHealth(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    application_version: str
    generated_at: Timestamp
    python_version: str
    python_implementation: str
    status: Literal["no_history", "attention", "clear"]
    runs: tuple[HealthRun, ...]
    refresh_sha256: Hash | None = None
    refresh_status: str | None = None
    refresh_store_relation: Literal["not_supplied", "same_path", "relocated_explicitly"]
    request_attempt_limit: Literal[3] = 3
    automatic_workflow_retries: Literal[0] = 0
    market_freshness_assessed: Literal[False] = False


def retry_action(status, reason):
    if status == "running":
        return "inspect_unfinished"
    if status == "succeeded":
        return "none"
    if reason == "HTTP_429":
        return "check_quota_before_manual_retry"
    if reason in {"CONNECTION_FAILED", "HTTP_500", "HTTP_502", "HTTP_503", "HTTP_504"}:
        return "manual_retry_after_transport_budget"
    if reason in {
        "HTTP_400",
        "HTTP_401",
        "HTTP_403",
        "HTTP_404",
        "MISSING_CREDENTIALS",
        "VALIDATION_FAILED",
        "STORAGE_ERROR",
    }:
        return "repair_before_retry"
    return "inspect_before_retry"


def build_operations_health(root, refresh_manifest=None, *, allow_relocated_refresh=False):
    root = Path(root).resolve()
    if not (root / "market.sqlite3").is_file():
        raise ValueError("existing store database is required")
    refresh = None
    refresh_digest = None
    relation = "not_supplied"
    with store_lock(root):
        traces = []
        for path in sorted((root / "runs").glob("*.json")):
            if path.is_symlink():
                raise ValueError("acquisition manifest must not be linked")
            content = path.read_bytes()
            run = AcquisitionRun.model_validate_json(content)
            if path.stem != run.run_id:
                raise ValueError("manifest filename does not match run ID")
            traces.append((run, hashlib.sha256(content).hexdigest()))
        by_id = {run.run_id: run for run, _ in traces}
        reasons = {}
        if refresh_manifest is not None:
            content = Path(refresh_manifest).read_bytes()
            refresh = RefreshRun.model_validate_json(content)
            if Path(refresh.store_root).resolve() != root:
                if not allow_relocated_refresh:
                    raise ValueError(
                        "refresh belongs to a different store; relocation must be explicit"
                    )
                relation = "relocated_explicitly"
            else:
                relation = "same_path"
            refresh_digest = hashlib.sha256(content).hexdigest()
            for step in refresh.steps:
                trace = by_id.get(step.run_id)
                if step.acquisition_status in {"succeeded", "failed", "running"}:
                    if trace is None or trace.status != step.acquisition_status:
                        raise ValueError("refresh acquisition state disagrees with stored trace")
                    if step.inserted_records is not None and (
                        step.inserted_records != trace.inserted_records
                        or step.referenced_records != len(trace.record_ids)
                    ):
                        raise ValueError("refresh counts disagree with stored trace")
                if trace is not None:
                    expected_operation = {
                        "alpha_vantage_gold": "fetch-alpha-gold",
                        "world_bank_pink_sheet": "fetch-worldbank-gold",
                        "cftc_disaggregated": "fetch-cftc-gold",
                    }.get(step.key, "fetch-fred-reviewed")
                    expected_source = "fred" if step.key.startswith("fred:") else step.key
                    if (
                        trace.operation != expected_operation
                        or trace.parameters.get("source") != expected_source
                    ):
                        raise ValueError("refresh operation/source disagrees with stored trace")
                    if (
                        step.key.startswith("fred:")
                        and trace.parameters.get("series") != step.key.split(":", 1)[1]
                    ):
                        raise ValueError("refresh series disagrees with stored trace")
                    reasons[trace.run_id] = step.failure_reason
        # Changing overlap windows does not create a new source/series health identity.
        identity_keys = {
            "source",
            "instrument",
            "venue",
            "dataset",
            "timeframe",
            "price_type",
            "market_code",
            "series",
            "vintage",
            "reviewed",
        }
        groups = {}
        for run, digest in traces:
            identity = (
                run.operation,
                tuple(
                    sorted(
                        (key, value)
                        for key, value in run.parameters.items()
                        if key in identity_keys
                    )
                ),
            )
            groups.setdefault(identity, []).append((run, digest))
        rows = []
        for identity, group in groups.items():
            group.sort(key=lambda pair: (pair[0].started_at, pair[0].run_id))
            streak = 0
            for index, (run, digest) in enumerate(group):
                streak = streak + 1 if run.status == "failed" else 0
                category = (
                    "none"
                    if run.status != "failed"
                    else {
                        "KeyboardInterrupt": "interrupted",
                        "SystemExit": "interrupted",
                        "OSError": "storage",
                    }.get(run.failure_type, "unknown")
                )
                reason = reasons.get(run.run_id)
                rows.append(
                    HealthRun(
                        run_id=run.run_id,
                        manifest_sha256=digest,
                        operation=run.operation,
                        identity_sha256=hashlib.sha256(repr(identity).encode()).hexdigest(),
                        started_at=run.started_at,
                        finished_at=run.finished_at,
                        status=run.status,
                        inserted_records=run.inserted_records,
                        failure_category=category,
                        failure_reason=reason,
                        retry_action=retry_action(run.status, reason),
                        consecutive_failures=streak,
                        is_latest=index == len(group) - 1,
                    )
                )
    rows.sort(key=lambda row: (row.started_at, row.run_id))
    attention = any(
        row.status == "running" or (row.is_latest and row.status == "failed") for row in rows
    )
    if refresh is not None and refresh.status != "succeeded":
        attention = True
    return OperationsHealth(
        application_version=__version__,
        generated_at=datetime.now(UTC),
        python_version=platform.python_version(),
        python_implementation=platform.python_implementation(),
        status="no_history"
        if not rows and refresh is None
        else "attention"
        if attention
        else "clear",
        runs=tuple(rows),
        refresh_sha256=refresh_digest,
        refresh_status=refresh.status if refresh else None,
        refresh_store_relation=relation,
    )


def write_operations_health(report, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    write_manifest(destination / "operations-health.json", report)
    lines = [
        "# سلامت عملیات",
        "",
        f"وضعیت: `{report.status}`",
        f"Python گزارش: `{report.python_version}`؛ محیط اجراهای قدیمی ثبت نشده است.",
        "سهمیهٔ منابع اندازه‌گیری نشده؛ سلامت عملیات به معنی تازگی بازار نیست.",
        "حداکثر سه تلاش برای هر درخواست؛ تلاش مجدد کل گردش خودکار نیست.",
        "",
        "| شناسهٔ اجرا | عملیات | وضعیت | آخرین | شکست متوالی | خطای امن | اقدام |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in report.runs:
        lines.append(
            f"| `{row.run_id}` | {row.operation} | {row.status} | {row.is_latest} | "
            f"{row.consecutive_failures} | {row.failure_reason or row.failure_category} | "
            f"{row.retry_action} |"
        )
    (destination / "operations-health.fa.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"status": report.status, "directory": str(destination), "runs": len(report.runs)}
