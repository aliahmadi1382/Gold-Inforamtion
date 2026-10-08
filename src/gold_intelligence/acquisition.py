"""Local acquisition manifests. Credentials and exception payloads are never serialized."""

import hashlib
import os
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator

from . import __version__
from .models import Contract, Hash, NonEmpty, Timestamp
from .storage import Store
from .transport_evidence import TransportEvidence, capture_transport

SAFE_PARAMETERS = {
    "input_filename",
    "source",
    "instrument",
    "venue",
    "dataset",
    "timeframe",
    "price_type",
    "currency",
    "unit",
    "volume_unit",
    "contract_expiry",
    "timezone",
    "verified_availability",
    "retrieved_at",
    "market_code",
    "futures_only_confirmed",
    "series",
    "start",
    "end",
    "vintage",
    "reviewed",
}


class AcquisitionRun(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    operation: Literal[
        "import-prices",
        "import-cftc",
        "import-records",
        "fetch-fred",
        "fetch-alpha-gold",
        "fetch-fred-reviewed",
        "fetch-worldbank-gold",
        "fetch-philly-cpi",
        "fetch-cftc-gold",
        "import-release-evidence",
        "import-release-values",
    ]
    application_version: NonEmpty
    started_at: Timestamp
    finished_at: Timestamp | None = None
    status: Literal["running", "succeeded", "failed"]
    parameters: dict[str, str | bool | None]
    raw_sha256: tuple[Hash, ...] = ()
    record_ids: tuple[Hash, ...] = ()
    inserted_records: int = Field(default=0, ge=0)
    failure_type: str | None = None

    @model_validator(mode="after")
    def consistent(self):
        if set(self.parameters) - SAFE_PARAMETERS:
            raise ValueError("unsupported manifest parameter; credentials must stay in environment")
        if (self.status == "running") != (self.finished_at is None):
            raise ValueError("terminal runs require a finish timestamp")
        if self.finished_at and self.finished_at < self.started_at:
            raise ValueError("run finish cannot precede start")
        if (self.status == "failed") != (self.failure_type is not None):
            raise ValueError("only failed runs carry a failure type")
        if self.inserted_records > len(self.record_ids):
            raise ValueError("inserted count exceeds traced records")
        return self


def write_manifest(path: Path, run: Contract) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Replace within the same directory so readers never see partially written JSON.
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
        ) as stream:
            temp_path = Path(stream.name)
            stream.write(run.model_dump_json(indent=2) + "\n")
        os.replace(temp_path, path)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


def acquire(
    store: Store,
    operation: str,
    parameters: dict,
    execute: Callable[[], int],
    *,
    run_id: str | None = None,
) -> dict:
    with store.writer_lock():
        return _acquire_locked(store, operation, parameters, execute, run_id=run_id)


def _acquire_locked(store, operation, parameters, execute, *, run_id=None):
    run = AcquisitionRun(
        run_id=run_id if run_id is not None else uuid4().hex,
        operation=operation,
        application_version=__version__,
        started_at=datetime.now(UTC),
        status="running",
        parameters=parameters,
    )
    path = store.root / "runs" / f"{run.run_id}.json"
    # Reserve outside the JSON namespace: readers must not see an empty manifest,
    # and concurrent callers must never overwrite a caller-supplied run ID.
    path.parent.mkdir(parents=True, exist_ok=True)
    reservation = path.with_suffix(".reserve")
    with reservation.open("x", encoding="utf-8"):
        pass
    try:
        if path.exists():
            raise FileExistsError("acquisition run ID already exists")
        write_manifest(path, run)
    finally:
        reservation.unlink()
    failure = None
    with store.capture_ingestion() as evidence, capture_transport() as attempts:
        try:
            inserted = execute()
            if inserted != evidence.inserted_records:
                raise ValueError("adapter inserted count differs from transactional trace")
        except BaseException as exc:
            failure = exc
        final = AcquisitionRun.model_validate(
            {
                **run.model_dump(),
                "status": "failed" if failure else "succeeded",
                "finished_at": datetime.now(UTC),
                "raw_sha256": sorted(evidence.raw_sha256),
                "record_ids": sorted(evidence.record_ids),
                "inserted_records": evidence.inserted_records,
                "failure_type": type(failure).__name__ if failure else None,
            }
        )
        write_manifest(path, final)
        transport = TransportEvidence(
            run_id=final.run_id,
            acquisition_manifest_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            attempts=tuple(attempts),
        )
        write_manifest(store.root / "transport" / f"{final.run_id}.json", transport)
    if failure:
        raise failure
    return {"inserted": final.inserted_records, "run_id": final.run_id, "manifest": str(path)}


def list_runs(root: Path) -> list[dict]:
    runs = []
    for path in sorted((root / "runs").glob("*.json")):
        run = AcquisitionRun.model_validate_json(path.read_bytes())
        if path.stem != run.run_id:
            raise ValueError("manifest filename does not match its run ID")
        runs.append(
            {
                "run_id": run.run_id,
                "operation": run.operation,
                "status": run.status,
                "started_at": run.started_at.isoformat(),
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "inserted_records": run.inserted_records,
                "referenced_records": len(run.record_ids),
                "raw_blobs": len(run.raw_sha256),
                "failure_type": run.failure_type,
            }
        )
    return sorted(runs, key=lambda run: (run["started_at"], run["run_id"]))
