"""Optional, separately versioned evidence; never changes research fingerprints."""

import hashlib
import platform
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from . import __version__
from .models import Contract, Hash, Timestamp


class RuntimeEvidence(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    scope: Literal["bundle_writer"] = "bundle_writer"
    captured_at: Timestamp
    application_version: str
    python_version: str
    python_implementation: str
    operating_system: str
    machine: str
    dependencies: dict[str, str]
    report_sha256: Hash
    report_fingerprint: Hash


class RuntimeManifest(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    runtime_sha256: Hash
    runtime_bytes: int = Field(ge=0)


class ComputationEvidence(RuntimeEvidence):
    scope: Literal["local_report_computation"] = "local_report_computation"
    started_at: Timestamp
    finished_at: Timestamp

    @model_validator(mode="after")
    def ordered_clock(self):
        if not self.started_at <= self.finished_at <= self.captured_at:
            raise ValueError("computation clock is not ordered")
        return self


def computation_start():
    return dict(
        started_at=datetime.now(UTC),
        application_version=__version__,
        python_version=platform.python_version(),
        python_implementation=platform.python_implementation(),
        operating_system=platform.system(),
        machine=platform.machine(),
        dependencies={
            name: version(name)
            for name in ("pydantic", "openpyxl", "defusedxml", "PyYAML", "tzdata")
        },
    )


def write_computation(directory, report, trace):
    if trace is None:
        return
    if trace["report_fingerprint"] != report.fingerprint:
        raise ValueError("computation trace belongs to a different report")
    directory = Path(directory)
    evidence = ComputationEvidence(
        **trace,
        captured_at=datetime.now(UTC),
        report_sha256=hashlib.sha256((directory / "research-report.json").read_bytes()).hexdigest(),
    )
    content = (evidence.model_dump_json(indent=2) + "\n").encode()
    (directory / "computation.json").write_bytes(content)
    manifest = RuntimeManifest(
        runtime_sha256=hashlib.sha256(content).hexdigest(), runtime_bytes=len(content)
    )
    (directory / "computation-manifest.json").write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )


def load_computation(directory, report, report_bytes):
    directory = Path(directory).resolve()
    paths = [directory / "computation.json", directory / "computation-manifest.json"]
    if not any(p.exists() or p.is_symlink() for p in paths):
        return None
    if any(p.is_symlink() or not p.is_file() for p in paths):
        raise ValueError("incomplete or unsafe computation evidence")
    content = paths[0].read_bytes()
    manifest = RuntimeManifest.model_validate_json(paths[1].read_bytes())
    if (
        len(content) != manifest.runtime_bytes
        or hashlib.sha256(content).hexdigest() != manifest.runtime_sha256
    ):
        raise ValueError("computation artifact hash mismatch")
    evidence = ComputationEvidence.model_validate_json(content)
    if not evidence.started_at <= report.generated_at <= evidence.finished_at:
        raise ValueError("report generation is outside its computation clock")
    if (
        evidence.report_sha256 != hashlib.sha256(report_bytes).hexdigest()
        or evidence.report_fingerprint != report.fingerprint
    ):
        raise ValueError("computation evidence belongs to a different report")
    return evidence


def write_runtime(directory, report):
    directory = Path(directory)
    evidence = RuntimeEvidence(
        captured_at=datetime.now(UTC),
        application_version=__version__,
        python_version=platform.python_version(),
        python_implementation=platform.python_implementation(),
        operating_system=platform.system(),
        machine=platform.machine(),
        dependencies={
            name: version(name)
            for name in ("pydantic", "openpyxl", "defusedxml", "PyYAML", "tzdata")
        },
        report_sha256=hashlib.sha256((directory / "research-report.json").read_bytes()).hexdigest(),
        report_fingerprint=report.fingerprint,
    )
    content = (evidence.model_dump_json(indent=2) + "\n").encode()
    (directory / "runtime.json").write_bytes(content)
    manifest = RuntimeManifest(
        runtime_sha256=hashlib.sha256(content).hexdigest(), runtime_bytes=len(content)
    )
    (directory / "runtime-manifest.json").write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )


def load_runtime(directory, report, report_bytes):
    directory = Path(directory).resolve()
    paths = [directory / "runtime.json", directory / "runtime-manifest.json"]
    if not any(p.exists() or p.is_symlink() for p in paths):
        return None
    if any(p.is_symlink() or not p.is_file() for p in paths):
        raise ValueError("incomplete or unsafe runtime evidence")
    manifest = RuntimeManifest.model_validate_json(paths[1].read_bytes())
    content = paths[0].read_bytes()
    if (
        len(content) != manifest.runtime_bytes
        or hashlib.sha256(content).hexdigest() != manifest.runtime_sha256
    ):
        raise ValueError("runtime artifact hash mismatch")
    evidence = RuntimeEvidence.model_validate_json(content)
    if (
        evidence.report_sha256 != hashlib.sha256(report_bytes).hexdigest()
        or evidence.report_fingerprint != report.fingerprint
    ):
        raise ValueError("runtime evidence belongs to a different report")
    return evidence
