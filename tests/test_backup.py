"""Offline recovery tests preserve invented data and exercise actual SQLite/WAL behavior."""

import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import validate

from gold_intelligence import backup, cli
from gold_intelligence.acquisition import AcquisitionRun, acquire, write_manifest
from gold_intelligence.backup import (
    BackupFile,
    backup_fingerprint,
    backup_store,
    file_hash,
    restore_store,
    verify_backup,
)
from gold_intelligence.storage import Store
from gold_intelligence.store_lock import store_lock


@pytest.fixture
def populated(store, make_bar):
    rows = [make_bar(index=index, close=100 + index) for index in range(3)]
    acquire(store, "import-records", {"source": "synthetic_demo"}, lambda: store.put(rows))
    store.put_raw(b"unreferenced failed-response evidence")
    (store.root / "credentials.env").write_text("private-sentinel", encoding="utf-8")
    (store.root / "notes.json").write_text("external-report-sentinel", encoding="utf-8")
    return store


@pytest.fixture
def saved(populated, tmp_path):
    return backup_store(populated.root, tmp_path / "backups")


def test_backup_restore_preserves_records_raw_and_runs_but_excludes_keys(
    saved, populated, tmp_path
):
    manifest, directory = saved
    assert manifest.records == 3 and manifest.raw_blobs == 2 and manifest.acquisition_runs == 1
    assert verify_backup(directory)["status"] == "verified"
    assert not (directory / "credentials.env").exists() and not (directory / "notes.json").exists()
    validate(
        manifest.model_dump(mode="json"),
        json.loads(Path("schemas/backup_manifest_v2.schema.json").read_bytes()),
    )
    receipt = restore_store(directory, tmp_path / "restore")
    validate(
        receipt.model_dump(mode="json"),
        json.loads(Path("schemas/restore_receipt_v2.schema.json").read_bytes()),
    )
    with Store(Path(receipt.store_root)) as restored:
        assert list(restored.entries()) == list(populated.entries())
        assert restored.audit() == {"records": 3, "raw_lineage": "verified"}
        assert (
            (restored.root / "raw")
            .joinpath(next(path.name for path in (populated.root / "raw").iterdir()))
            .exists()
        )
    for item in manifest.files:
        assert file_hash(Path(receipt.store_root) / item.path) == item.sha256


def test_online_backup_includes_committed_wal_pages(populated, make_bar, tmp_path):
    assert populated.db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    populated.put([make_bar(index=5)])
    wal = populated.root / "market.sqlite3-wal"
    assert wal.exists() and wal.stat().st_size > 0
    manifest, directory = backup_store(populated.root, tmp_path / "backup")
    assert manifest.records == 4
    assert not (directory / "market.sqlite3-wal").exists()
    assert not (directory / "market.sqlite3-shm").exists()
    assert verify_backup(directory)["records"] == 4


def test_missing_source_does_not_create_empty_store_or_backup(tmp_path):
    source = tmp_path / "typo"
    output = tmp_path / "backup"
    with pytest.raises(ValueError):
        backup_store(source, output)
    assert not source.exists() and not output.exists()


def test_empty_store_can_be_backed_up_and_restored(store, tmp_path):
    manifest, directory = backup_store(store.root, tmp_path / "backup")
    assert manifest.records == manifest.raw_blobs == manifest.acquisition_runs == 0
    assert restore_store(directory, tmp_path / "restore").records == 0


def test_active_writer_blocks_backup_and_does_not_publish(populated, tmp_path):
    with populated.writer_lock():
        with pytest.raises(ValueError, match="another writer"):
            backup_store(populated.root, tmp_path / "backup")
    assert not (tmp_path / "backup").exists()


def test_backup_lock_blocks_raw_normalized_and_acquisition_writes(populated, make_bar):
    row = make_bar(index=5)
    previous = set((populated.root / "runs").iterdir())
    with store_lock(populated.root):
        for action in (
            lambda: populated.put_raw(b"new raw"),
            lambda: populated.put([row]),
            lambda: acquire(populated, "import-records", {}, lambda: populated.put([row])),
        ):
            with pytest.raises(ValueError, match="another writer"):
                action()
    assert set((populated.root / "runs").iterdir()) == previous
    assert populated.db.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 3


def test_acquisition_holds_lock_before_manifest_until_terminal_state(populated, make_bar, tmp_path):
    row = make_bar(index=6)

    def execute():
        with pytest.raises(ValueError, match="another writer"):
            backup_store(populated.root, tmp_path / "backup")
        return populated.put([row])

    acquire(populated, "import-records", {}, execute)
    assert not (tmp_path / "backup").exists()
    assert backup_store(populated.root, tmp_path / "backup")[0].records == 4


def test_lock_recovers_after_exception(populated, tmp_path):
    with pytest.raises(RuntimeError), populated.writer_lock():
        raise RuntimeError("interrupted")
    assert backup_store(populated.root, tmp_path / "backup")[0].records == 3


def test_process_termination_releases_shared_lock(populated, tmp_path):
    code = (
        "import sys; from pathlib import Path; "
        "from gold_intelligence.store_lock import store_lock; "
        "ctx=store_lock(Path(sys.argv[1])); ctx.__enter__(); print('locked',flush=True); "
        "sys.stdin.readline()"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(populated.root)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "locked"
        with pytest.raises(ValueError, match="another writer"):
            backup_store(populated.root, tmp_path / "backup")
    finally:
        process.terminate()
        process.communicate(timeout=10)
    assert backup_store(populated.root, tmp_path / "backup")[0].records == 3


def test_failed_and_abandoned_runs_keep_original_status(populated, tmp_path):
    def fail():
        raise ValueError("private exception")

    with pytest.raises(ValueError):
        acquire(populated, "import-records", {}, fail)
    run = AcquisitionRun(
        run_id="a" * 32,
        operation="import-records",
        application_version="0.1.0",
        started_at=datetime.now(UTC),
        status="running",
        parameters={},
    )
    write_manifest(populated.root / "runs" / f"{run.run_id}.json", run)
    manifest, directory = backup_store(populated.root, tmp_path / "backup")
    assert manifest.run_states == {"running": 1, "failed": 1, "succeeded": 1}
    assert "private exception" not in (directory / "backup-manifest.json").read_text()
    assert verify_backup(directory)["run_states"] == manifest.run_states


@pytest.mark.parametrize(
    "damage", ["missing_raw", "corrupt_raw", "corrupt_payload", "missing_run_record"]
)
def test_corrupt_source_refused_before_publication(populated, tmp_path, damage):
    if damage in {"missing_raw", "corrupt_raw"}:
        path = next((populated.root / "raw").iterdir())
        if damage == "missing_raw":
            # Remove referenced evidence, not the optional failed-response raw.
            digest = populated.read("price_bar")[0].provenance.raw_sha256
            (populated.root / "raw" / digest).unlink()
        else:
            path.write_bytes(b"corrupt")
    elif damage == "corrupt_payload":
        populated.db.execute("UPDATE records SET payload='{}'")
        populated.db.commit()
    else:
        path = next((populated.root / "runs").glob("*.json"))
        data = json.loads(path.read_bytes())
        data["record_ids"][0] = "a" * 64
        path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        backup_store(populated.root, tmp_path / "backup")
    assert not (tmp_path / "backup").exists()


@pytest.mark.parametrize("name", ["market.sqlite3", "raw", "runs"])
def test_backup_tampering_rejected(saved, name):
    _, directory = saved
    path = directory / name
    if name != "market.sqlite3":
        path = next(path.iterdir())
    path.write_bytes(b"tampered")
    with pytest.raises(ValueError):
        verify_backup(directory)


def rehash_manifest(directory, edit):
    path = directory / "backup-manifest.json"
    data = json.loads(path.read_bytes())
    edit(data)
    data["fingerprint"] = backup_fingerprint(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_rehashed_false_record_count_is_rejected(saved):
    _, directory = saved
    rehash_manifest(directory, lambda data: data.update(records=4))
    with pytest.raises(ValueError, match="counts"):
        verify_backup(directory)


def test_rehashed_normalized_corruption_is_rejected(saved):
    _, directory = saved
    database = directory / "market.sqlite3"
    with sqlite3.connect(database) as connection:
        identifier, content = connection.execute(
            "SELECT id,payload FROM records LIMIT 1"
        ).fetchone()
        row = json.loads(content)
        row["close"] += 0.1
        connection.execute("UPDATE records SET payload=? WHERE id=?", (json.dumps(row), identifier))

    def update(data):
        item = next(item for item in data["files"] if item["path"] == "market.sqlite3")
        item.update(sha256=file_hash(database), bytes=database.stat().st_size)

    rehash_manifest(directory, update)
    with pytest.raises(ValueError, match="content hash"):
        verify_backup(directory)


@pytest.mark.parametrize(
    "path", ["../market.sqlite3", "/market.sqlite3", "runs/../secret.json", "raw/secret"]
)
def test_manifest_rejects_escaped_or_noncontract_paths(path):
    with pytest.raises(ValueError):
        BackupFile(path=path, sha256="a" * 64, bytes=0)


def test_restore_refuses_existing_empty_or_populated_destination(saved, tmp_path):
    _, directory = saved
    target = tmp_path / "restore"
    target.mkdir()
    with pytest.raises(FileExistsError):
        restore_store(directory, target)
    (target / "notes.txt").write_text("preserve")
    with pytest.raises(FileExistsError):
        restore_store(directory, target)
    assert (target / "notes.txt").read_text() == "preserve"


def test_backup_output_inside_source_refused(populated):
    with pytest.raises(ValueError, match="outside"):
        backup_store(populated.root, populated.root / "backup")


def test_restore_inside_backup_refused_without_mutation(saved):
    _, directory = saved
    with pytest.raises(ValueError, match="separate"):
        restore_store(directory, directory / "restore")
    assert not (directory / "restore").exists()


def test_repeated_backups_preserve_previous_snapshot(saved, populated, make_bar, tmp_path):
    manifest, first = saved
    old = (first / "backup-manifest.json").read_bytes()
    populated.put([make_bar(index=7)])
    new, second = backup_store(populated.root, tmp_path / "backups")
    assert first != second and manifest.records == 3 and new.records == 4
    assert (first / "backup-manifest.json").read_bytes() == old
    assert verify_backup(first)["records"] == 3


def test_copy_failure_does_not_publish_successful_backup(populated, tmp_path, monkeypatch):
    def fail(*_):
        raise OSError("disk full")

    monkeypatch.setattr(backup.shutil, "copyfile", fail)
    with pytest.raises(OSError):
        backup_store(populated.root, tmp_path / "backups")
    assert not list((tmp_path / "backups").glob("backup-*"))


def test_restore_copy_failure_leaves_no_published_store(saved, tmp_path, monkeypatch):
    _, directory = saved
    target = tmp_path / "restore"

    def fail(*_):
        raise OSError("disk full")

    monkeypatch.setattr(backup.shutil, "copyfile", fail)
    with pytest.raises(OSError):
        restore_store(directory, target)
    assert (target / ".incomplete-store").is_dir()
    assert not (target / "store").exists() and not (target / "restore-receipt.json").exists()


def test_uncoordinated_source_file_change_is_detected(populated, tmp_path, monkeypatch):
    original = backup.shutil.copyfile
    changed = False

    def mutate(source, destination):
        nonlocal changed
        result = original(source, destination)
        if not changed and Path(source).parent.name == "raw":
            Path(source).write_bytes(b"outside mutation")
            changed = True
        return result

    monkeypatch.setattr(backup.shutil, "copyfile", mutate)
    with pytest.raises(ValueError, match="changed during backup"):
        backup_store(populated.root, tmp_path / "backups")
    assert not list((tmp_path / "backups").glob("backup-*"))


def test_invalid_store_and_backup_cli_never_load_credentials_or_registry(tmp_path, capsys):
    assert (
        cli.main(
            [
                "--registry",
                "not-present",
                "--store",
                str(tmp_path / "absent"),
                "backup-store",
                "--output-dir",
                str(tmp_path / "backups"),
            ]
        )
        == 2
    )
    assert not (tmp_path / "absent").exists()
    assert "Traceback" not in capsys.readouterr().err


def test_cli_backup_verify_restore_are_offline(saved, populated, tmp_path, capsys):
    _, directory = saved
    assert cli.main(["--registry", "missing", "verify-backup", str(directory)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "verified"
    assert (
        cli.main(
            [
                "--registry",
                "missing",
                "restore-store",
                str(directory),
                "--destination",
                str(tmp_path / "restore"),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "restored_and_verified" and result["records"] == 3
    assert (
        cli.main(
            [
                "--registry",
                "missing",
                "--store",
                str(populated.root),
                "backup-store",
                "--output-dir",
                str(tmp_path / "other"),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "created_and_verified"


def test_restore_cannot_place_nested_store_inside_original(saved, populated):
    _, directory = saved
    with pytest.raises(ValueError, match="outside"):
        restore_store(directory, populated.root / "nested-restore")
    assert not (populated.root / "nested-restore").exists()


def test_restore_detects_backup_manifest_change_during_copy(saved, tmp_path, monkeypatch):
    _, directory = saved
    original = backup.shutil.copyfile

    def mutate(source, destination):
        result = original(source, destination)
        (directory / "backup-manifest.json").write_bytes(b"replaced")
        return result

    monkeypatch.setattr(backup.shutil, "copyfile", mutate)
    with pytest.raises(ValueError, match="changed during restore"):
        restore_store(directory, tmp_path / "restore")
    assert not (tmp_path / "restore/store").exists()


def test_reentrant_writer_ownership_does_not_cross_threads(populated):
    from concurrent.futures import ThreadPoolExecutor

    with populated.writer_lock(), ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(populated.put_raw, b"other thread")
        with pytest.raises(ValueError, match="cross threads"):
            task.result(timeout=5)


def test_linked_raw_evidence_is_rejected(populated, tmp_path):
    path = next((populated.root / "raw").iterdir())
    original = path.read_bytes()
    outside = tmp_path / "outside"
    outside.write_bytes(original)
    path.unlink()
    try:
        path.symlink_to(outside)
    except OSError:
        path.write_bytes(original)
        pytest.skip("host does not permit symlinks")
    with pytest.raises(ValueError, match="regular files"):
        backup_store(populated.root, tmp_path / "backup")


def test_rehashed_missing_trace_evidence_is_rejected(saved):
    _, directory = saved
    path = next((directory / "runs").iterdir())
    data = json.loads(path.read_bytes())
    data["record_ids"][0] = "a" * 64
    path.write_text(json.dumps(data), encoding="utf-8")

    def update(manifest):
        item = next(item for item in manifest["files"] if item["path"] == f"runs/{path.name}")
        item.update(sha256=file_hash(path), bytes=path.stat().st_size)

    rehash_manifest(directory, update)
    with pytest.raises(ValueError, match="missing evidence"):
        verify_backup(directory)


@pytest.mark.parametrize("damage", ["unrelated_table", "view", "no_primary_key"])
def test_unknown_store_schema_is_not_copied(store, tmp_path, damage):
    if damage == "unrelated_table":
        store.db.execute("CREATE TABLE unrelated(secret TEXT)")
    else:
        store.db.execute("DROP TABLE records")
        if damage == "view":
            store.db.execute("CREATE VIEW records AS SELECT '' AS id, '' AS kind, '' AS payload")
        else:
            store.db.execute("CREATE TABLE records(id TEXT, kind TEXT, payload TEXT)")
    store.db.commit()
    with pytest.raises(ValueError, match="unexpected"):
        backup_store(store.root, tmp_path / "backup")
    assert not (tmp_path / "backup").exists()


def test_transport_bytes_and_links_survive_restore(saved, tmp_path):
    manifest, directory = saved
    assert manifest.schema_version == "2.0.0" and manifest.transport_documents == 1
    restored = Path(restore_store(directory, tmp_path / "extended-restore").store_root)
    receipt = json.loads((restored.parent / "restore-receipt.json").read_bytes())
    assert receipt["transport_documents"] == 1
    assert backup.audit_core(restored, include_transport=True)["transport_documents"] == 1
    for item in manifest.files:
        if item.path.startswith("transport/"):
            assert (directory / item.path).read_bytes() == (restored / item.path).read_bytes()


@pytest.mark.parametrize("damage", ["manifest_hash", "run_id", "time", "missing", "extra"])
def test_transport_corruption_rejected_even_after_rehash(saved, damage):
    _, directory = saved
    path = next((directory / "transport").glob("*.json"))
    data = json.loads(path.read_bytes())
    if damage == "manifest_hash":
        data["acquisition_manifest_sha256"] = "a" * 64
    elif damage == "run_id":
        data["run_id"] = "a" * 32
    elif damage == "time":
        data["attempts"] = [
            {
                "started_at": "2000-01-01T00:00:00Z",
                "attempt": 1,
                "outcome": "success",
                "status_code": None,
            }
        ]
    elif damage == "missing":
        path.unlink()
    else:
        (directory / "transport" / ("a" * 32 + ".json")).write_bytes(path.read_bytes())
    if damage in {"manifest_hash", "run_id", "time"}:
        path.write_text(json.dumps(data), encoding="utf-8")

        def update(manifest):
            item = next(f for f in manifest["files"] if f["path"] == f"transport/{path.name}")
            item.update(sha256=file_hash(path), bytes=path.stat().st_size)

        rehash_manifest(directory, update)
    with pytest.raises((ValueError, OSError)):
        verify_backup(directory)


@pytest.mark.parametrize("damage", ["orphan", "corrupt", "bad_name"])
def test_invalid_source_transport_not_published(populated, tmp_path, damage):
    path = next((populated.root / "transport").glob("*.json"))
    if damage == "orphan":
        (populated.root / "runs" / path.name).unlink()
    elif damage == "corrupt":
        path.write_bytes(b"{}")
    else:
        path.rename(path.with_name("notes.json"))
    with pytest.raises((ValueError, OSError)):
        backup_store(populated.root, tmp_path / "invalid-backup")
    assert not (tmp_path / "invalid-backup").exists()


def test_legacy_backup_preserves_contract_and_restores_without_invented_transport(saved, tmp_path):
    from gold_intelligence.backup import BackupManifest, render_backup

    _, directory = saved
    data = json.loads((directory / "backup-manifest.json").read_bytes())
    data.pop("transport_documents")
    data.update(schema_version="1.0.0", scope="core_store_without_credentials_or_external_reports")
    data["files"] = [f for f in data["files"] if not f["path"].startswith("transport/")]
    data["fingerprint"] = backup_fingerprint(data)
    manifest = BackupManifest.model_validate(data)
    validate(data, json.loads(Path("schemas/backup_manifest.schema.json").read_bytes()))
    write_manifest(directory / "backup-manifest.json", manifest)
    (directory / "backup.fa.md").write_bytes(render_backup(manifest).encode())
    assert verify_backup(directory)["status"] == "verified"
    receipt = restore_store(directory, tmp_path / "legacy-restore")
    assert receipt.schema_version == "1.0.0"
    assert not (Path(receipt.store_root) / "transport").exists()
    validate(
        receipt.model_dump(mode="json"),
        json.loads(Path("schemas/restore_receipt.schema.json").read_bytes()),
    )
