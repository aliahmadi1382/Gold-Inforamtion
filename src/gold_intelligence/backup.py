"""Verified core-store snapshots and isolated restore; never copy credentials."""

import hashlib
import shutil
import sqlite3
import time
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator

from . import __version__
from .acquisition import AcquisitionRun, write_manifest
from .models import Contract, Hash, Timestamp
from .storage import canonical, decode_record
from .store_lock import store_lock


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def backup_fingerprint(data):
    return hashlib.sha256(
        canonical({k: v for k, v in data.items() if k != "fingerprint"}).encode()
    ).hexdigest()


class BackupFile(Contract):
    path: str = Field(pattern=r"^(market\.sqlite3|raw/[a-f0-9]{64}|runs/[a-f0-9]{32}\.json)$")
    sha256: Hash
    bytes: int = Field(ge=0)


class BackupManifest(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    application_version: str
    created_at: Timestamp
    source_root: str
    fingerprint: Hash
    files: tuple[BackupFile, ...]
    records: int = Field(ge=0)
    raw_blobs: int = Field(ge=0)
    acquisition_runs: int = Field(ge=0)
    run_states: dict[Literal["running", "succeeded", "failed"], int]
    scope: Literal["core_store_without_credentials_or_external_reports"] = (
        "core_store_without_credentials_or_external_reports"
    )

    @model_validator(mode="after")
    def consistent(self):
        paths = [item.path for item in self.files]
        if len(paths) != len(set(paths)) or paths.count("market.sqlite3") != 1:
            raise ValueError("backup requires one database and unique files")
        if self.raw_blobs != sum(path.startswith("raw/") for path in paths) or (
            self.acquisition_runs != sum(path.startswith("runs/") for path in paths)
        ):
            raise ValueError("backup inventory count mismatch")
        if set(self.run_states) != {"running", "succeeded", "failed"} or (
            any(value < 0 for value in self.run_states.values())
            or sum(self.run_states.values()) != self.acquisition_runs
        ):
            raise ValueError("invalid acquisition state counts")
        for item in self.files:
            if item.path.startswith("raw/") and item.path.split("/")[1] != item.sha256:
                raise ValueError("raw filename must equal content hash")
        if self.fingerprint != backup_fingerprint(self.model_dump(mode="json")):
            raise ValueError("backup fingerprint mismatch")
        return self


class RestoreReceipt(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    application_version: str
    restored_at: Timestamp
    backup_fingerprint: Hash
    store_root: str
    status: Literal["restored_and_verified"] = "restored_and_verified"
    records: int = Field(ge=0)
    raw_blobs: int = Field(ge=0)
    acquisition_runs: int = Field(ge=0)


def core_files(root):
    root = Path(root).resolve()
    database = root / "market.sqlite3"
    if not database.is_file() or database.is_symlink():
        raise ValueError("missing database or linked database file")
    paths = [database]
    for name in ("raw", "runs"):
        directory = root / name
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            raise ValueError("core directories must not be linked or non-directories")
        if name == "raw" and not directory.is_dir():
            raise ValueError("raw directory is required")
        for path in sorted(directory.iterdir()) if directory.exists() else ():
            if path.is_symlink() or not path.is_file():
                raise ValueError("core evidence must be regular files")
            # Atomic manifest leftovers are not finalized acquisition documents.
            if name == "runs" and path.suffix != ".json":
                continue
            relative = path.relative_to(root).as_posix()
            BackupFile(path=relative, sha256="0" * 64, bytes=0)
            paths.append(path)
    return paths


def audit_core(root):
    root = Path(root).resolve()
    paths = core_files(root)
    raw = {path.name for path in paths if path.parent.name == "raw"}
    for path in paths:
        if path.parent.name == "raw" and file_hash(path) != path.name:
            raise ValueError("raw evidence hash mismatch")
    with closing(sqlite3.connect((root / "market.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("SQLite integrity check failed")
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if tables != {"records"}:
            raise ValueError("unexpected store tables")
        schema = db.execute("PRAGMA table_info(records)").fetchall()
        if [row[1] for row in schema] != ["id", "kind", "payload"] or schema[0][5] != 1:
            raise ValueError("unexpected records schema")
        identifiers = set()
        for identifier, kind, payload in db.execute("SELECT id, kind, payload FROM records"):
            item = decode_record(identifier, kind, payload)
            if item.provenance.raw_sha256 not in raw:
                raise ValueError("record has missing raw lineage")
            identifiers.add(identifier)
    states = Counter({"running": 0, "succeeded": 0, "failed": 0})
    for path in paths:
        if path.parent.name == "runs":
            run = AcquisitionRun.model_validate_json(path.read_bytes())
            if path.stem != run.run_id:
                raise ValueError("acquisition filename disagrees with run ID")
            if set(run.raw_sha256) - raw or set(run.record_ids) - identifiers:
                raise ValueError("acquisition trace has missing evidence")
            states[run.status] += 1
    return {
        "records": len(identifiers),
        "raw_blobs": len(raw),
        "acquisition_runs": sum(states.values()),
        "run_states": dict(states),
    }


def render_backup(manifest):
    return "\n".join(
        [
            "# پشتیبان بررسی‌شدهٔ داده‌های اصلی",
            "",
            f"زمان UTC: `{manifest.created_at.isoformat()}`.",
            f"نسخهٔ نرم‌افزار: `{manifest.application_version}`.",
            f"نسخه‌های رکورد: {manifest.records}؛ خام: {manifest.raw_blobs}؛ "
            f"اسناد دریافت: {manifest.acquisition_runs}.",
            f"دریافت‌های ناتمام: {manifest.run_states['running']}؛ "
            f"ناموفق: {manifest.run_states['failed']}.",
            "وضعیت تاریخی دریافت‌ها حفظ شده است؛ پشتیبان آن‌ها را موفق اعلام نمی‌کند.",
            "",
            f"Fingerprint: `{manifest.fingerprint}`.",
            "بسته شامل پایگاه، تمام raw و اسناد JSON دریافت است. کلید، گزارش‌های خارج "
            "از store، کد و تنظیمات در این بسته نیستند و جدا نگهداری می‌شوند.",
            "این نسخه روی دیسک محلی است؛ نسخهٔ مستقل در برابر خرابی همان دیسک نیست.",
            "بررسی هش و بازیابی، صحت اقتصادی داده یا سودآوری را ثابت نمی‌کند.",
            "",
        ]
    )


def verify_payload(root, manifest):
    paths = {path.relative_to(root).as_posix(): path for path in core_files(root)}
    if set(paths) != {item.path for item in manifest.files}:
        raise ValueError("backup inventory differs from manifest")
    for item in manifest.files:
        path = paths[item.path]
        if path.stat().st_size != item.bytes or file_hash(path) != item.sha256:
            raise ValueError("backup file hash or size mismatch")
    result = audit_core(root)
    if any(result[name] != getattr(manifest, name) for name in result):
        raise ValueError("backup counts disagree with restored evidence")
    return result


def verify_backup(directory):
    root = Path(directory).resolve()
    for name in ("backup-manifest.json", "backup.fa.md"):
        if (root / name).is_symlink():
            raise ValueError("backup metadata must not be linked")
    manifest = BackupManifest.model_validate_json((root / "backup-manifest.json").read_bytes())
    result = verify_payload(root, manifest)
    if (root / "backup.fa.md").read_bytes() != render_backup(manifest).encode():
        raise ValueError("backup summary differs from manifest")
    return {
        "status": "verified",
        "fingerprint": manifest.fingerprint,
        "files": len(manifest.files),
        **result,
    }


def snapshot_database(source_path, destination):
    # The online-backup API includes committed WAL pages; copying the main file alone does not.
    deadline = time.monotonic() + 30

    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            raise TimeoutError("SQLite backup exceeded its bounded wait")

    with closing(sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True, timeout=5)) as source:
        with closing(sqlite3.connect(destination)) as target:
            source.backup(target, pages=256, progress=progress, sleep=0.1)
            target.execute("PRAGMA journal_mode=DELETE")


def backup_store(source_root, output_dir):
    source = Path(source_root).resolve()
    output = Path(output_dir).resolve()
    if output.is_relative_to(source):
        raise ValueError("backup output must be outside the source store")
    with store_lock(source):
        # Validate before creating any backup directory; a typo must not create an empty store.
        audit_core(source)
        original = core_files(source)
        evidence = {
            path.relative_to(source).as_posix(): file_hash(path)
            for path in original
            if path.name != "market.sqlite3"
        }
        output.mkdir(parents=True, exist_ok=True)
        suffix = uuid4().hex
        staging = output / f".incomplete-backup-{suffix}"
        staging.mkdir()
        (staging / "raw").mkdir()
        (staging / "runs").mkdir()
        snapshot_database(source / "market.sqlite3", staging / "market.sqlite3")
        for path in original:
            if path.name != "market.sqlite3":
                shutil.copyfile(path, staging / path.relative_to(source))
        # Detect outside-the-lock filesystem changes instead of certifying a mixed copy.
        current = {
            path.relative_to(source).as_posix(): file_hash(path)
            for path in core_files(source)
            if path.name != "market.sqlite3"
        }
        if current != evidence:
            raise ValueError("source evidence changed during backup")
        result = audit_core(staging)
        files = tuple(
            BackupFile(
                path=path.relative_to(staging).as_posix(),
                sha256=file_hash(path),
                bytes=path.stat().st_size,
            )
            for path in core_files(staging)
        )
        data = dict(
            schema_version="1.0.0",
            application_version=__version__,
            created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            source_root=str(source),
            files=[item.model_dump(mode="json") for item in files],
            **result,
            scope="core_store_without_credentials_or_external_reports",
        )
        manifest = BackupManifest.model_validate({**data, "fingerprint": backup_fingerprint(data)})
        write_manifest(staging / "backup-manifest.json", manifest)
        (staging / "backup.fa.md").write_bytes(render_backup(manifest).encode())
        verify_backup(staging)
        destination = output / f"backup-{manifest.created_at:%Y%m%dT%H%M%S%fZ}-{suffix}"
        staging.rename(destination)
        return manifest, destination


def restore_store(backup_dir, destination):
    backup = Path(backup_dir).resolve()
    target = Path(destination).absolute()
    if target.exists() or target.is_symlink():
        raise FileExistsError("restore destination must be new")
    if target.resolve().is_relative_to(backup) or backup.is_relative_to(target.resolve()):
        raise ValueError("restore destination must be separate from backup")
    checked = verify_backup(backup)
    manifest_bytes = (backup / "backup-manifest.json").read_bytes()
    manifest = BackupManifest.model_validate_json(manifest_bytes)
    if manifest.fingerprint != checked["fingerprint"]:
        raise ValueError("backup manifest changed after verification")
    if target.resolve().is_relative_to(Path(manifest.source_root).resolve()):
        raise ValueError("restore destination must be outside the original source store")
    # Reserve a new container atomically. The store is published inside it only after verification.
    target.mkdir(parents=True, exist_ok=False)
    staging = target / ".incomplete-store"
    staging.mkdir()
    (staging / "raw").mkdir()
    (staging / "runs").mkdir()
    for item in manifest.files:
        source = backup / item.path
        if source.is_symlink() or not source.resolve().is_relative_to(backup):
            raise ValueError("backup evidence changed or escaped its directory")
        shutil.copyfile(source, staging / item.path)
    if (backup / "backup-manifest.json").read_bytes() != manifest_bytes:
        raise ValueError("backup manifest changed during restore")
    verify_payload(staging.resolve(), manifest)
    published = target / "store"
    staging.rename(published)
    receipt = RestoreReceipt(
        application_version=__version__,
        restored_at=datetime.now(UTC),
        backup_fingerprint=manifest.fingerprint,
        store_root=str(published.resolve()),
        records=manifest.records,
        raw_blobs=manifest.raw_blobs,
        acquisition_runs=manifest.acquisition_runs,
    )
    write_manifest(target / "restore-receipt.json", receipt)
    return receipt
