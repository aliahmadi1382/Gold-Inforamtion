"""Bounded HTTP attempt evidence without URLs, headers, bodies or exception messages."""

import hashlib
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .models import Contract, Hash, Timestamp


class HttpAttempt(Contract):
    started_at: Timestamp
    attempt: int = Field(ge=1, le=3)
    outcome: Literal["success", "http_error", "connection_error", "response_too_large"]
    status_code: int | None = Field(default=None, ge=100, le=599)

    @model_validator(mode="after")
    def consistent(self):
        if self.outcome == "http_error" and (self.status_code is None or self.status_code < 400):
            raise ValueError("HTTP failures require an error status")
        if self.outcome != "http_error" and self.status_code is not None:
            raise ValueError("only HTTP failures carry a captured status")
        return self


class TransportEvidence(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    acquisition_manifest_sha256: Hash
    scope: Literal["instrumented_fetch_bytes"] = "instrumented_fetch_bytes"
    quota_status: Literal["not_measured"] = "not_measured"
    attempts: tuple[HttpAttempt, ...]


_attempts = ContextVar("http_attempt_evidence", default=None)


@contextmanager
def capture_transport():
    attempts = []
    token = _attempts.set(attempts)
    try:
        yield attempts
    finally:
        _attempts.reset(token)


def record_attempt(started_at, attempt, outcome, status_code=None):
    target = _attempts.get()
    if target is not None:
        target.append(
            HttpAttempt(
                started_at=started_at, attempt=attempt, outcome=outcome, status_code=status_code
            )
        )


def started_now():
    return datetime.now(UTC)


def load_transport(root, run_id):
    root = Path(root)
    path = root / "transport" / f"{run_id}.json"
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("linked transport evidence is unsupported")
    evidence = TransportEvidence.model_validate_json(path.read_bytes())
    from .acquisition import AcquisitionRun

    run_bytes = (root / "runs" / f"{run_id}.json").read_bytes()
    run = AcquisitionRun.model_validate_json(run_bytes)
    if (
        evidence.run_id != run_id
        or evidence.acquisition_manifest_sha256 != hashlib.sha256(run_bytes).hexdigest()
    ):
        raise ValueError("transport evidence differs from acquisition manifest")
    times = [attempt.started_at for attempt in evidence.attempts]
    if (
        run.finished_at is None
        or times != sorted(times)
        or any(not run.started_at <= stamp <= run.finished_at for stamp in times)
    ):
        raise ValueError("transport attempt timestamps differ from acquisition interval")
    return evidence
