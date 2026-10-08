"""Local immutable raw blobs and transactional, idempotent SQLite records."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import get_ident

from .models import RECORD_TYPES, Record, aware
from .store_lock import store_lock


def canonical(value: dict) -> str:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def record_id(record: Record) -> str:
    return hashlib.sha256(canonical(record.model_dump(mode="json")).encode()).hexdigest()


def decode_record(identifier: str, kind: str, payload: str) -> Record:
    if kind not in RECORD_TYPES:
        raise ValueError("unknown stored record kind")
    record = RECORD_TYPES[kind].model_validate_json(payload)
    if record_id(record) != identifier:
        raise ValueError("normalized record content hash mismatch")
    return record


@dataclass
class IngestionEvidence:
    raw_sha256: set[str] = field(default_factory=set)
    record_ids: set[str] = field(default_factory=set)
    inserted_records: int = 0


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._capture = None
        self._write_depth = 0
        self._write_owner = None
        self.root.mkdir(parents=True, exist_ok=True)
        with self.writer_lock():
            (self.root / "raw").mkdir(exist_ok=True)
            self.db = sqlite3.connect(self.root / "market.sqlite3")
            self.db.execute("""CREATE TABLE IF NOT EXISTS records (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL)""")
            self.db.commit()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.db.close()

    @contextmanager
    def writer_lock(self):
        # Nested adapter calls in one acquisition reuse the same Store-owned lock.
        if self._write_depth:
            if self._write_owner != get_ident():
                raise ValueError("Store writer ownership cannot cross threads")
            self._write_depth += 1
            try:
                yield
            finally:
                self._write_depth -= 1
        else:
            with store_lock(self.root):
                self._write_depth = 1
                self._write_owner = get_ident()
                try:
                    yield
                finally:
                    self._write_depth = 0
                    self._write_owner = None

    @contextmanager
    def capture_ingestion(self):
        if self._capture is not None:
            raise ValueError("nested acquisition runs are not supported")
        self._capture = evidence = IngestionEvidence()
        try:
            yield evidence
        finally:
            self._capture = None

    def entries(self):
        return self.db.execute("SELECT id, kind, payload FROM records ORDER BY id")

    def put_raw(self, content: bytes) -> str:
        with self.writer_lock():
            return self._put_raw(content)

    def _put_raw(self, content: bytes) -> str:
        digest = hashlib.sha256(content).hexdigest()
        path = self.root / "raw" / digest
        try:
            with path.open("xb") as stream:
                stream.write(content)
        except FileExistsError:
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("existing raw blob failed integrity check") from None
        if self._capture is not None:
            self._capture.raw_sha256.add(digest)
        return digest

    def put(self, records: list[Record]) -> int:
        with self.writer_lock():
            return self._put(records)

    def _put(self, records: list[Record]) -> int:
        # Validate every record and its raw pointer before beginning a transaction.
        rows = []
        checked = set()
        for record in records:
            record = RECORD_TYPES[record.kind].model_validate(record.model_dump())
            digest = record.provenance.raw_sha256
            if digest not in checked:
                path = self.root / "raw" / digest
                if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise ValueError("record has a missing or corrupt raw blob")
                checked.add(digest)
            rows.append((record_id(record), record.kind, canonical(record.model_dump(mode="json"))))
        before = self.db.total_changes
        with self.db:
            self.db.executemany("INSERT OR IGNORE INTO records VALUES (?, ?, ?)", rows)
        inserted = self.db.total_changes - before
        if self._capture is not None:
            self._capture.raw_sha256.update(checked)
            self._capture.record_ids.update(row[0] for row in rows)
            self._capture.inserted_records += inserted
        return inserted

    def read(self, kind: str, as_of: datetime | None = None, mode: str = "system") -> list:
        if kind not in RECORD_TYPES or mode not in {"system", "source"}:
            raise ValueError("unknown record kind or replay mode")
        if as_of:
            aware(as_of)
        records = []
        for identifier, payload in self.db.execute(
            "SELECT id, payload FROM records WHERE kind = ?", (kind,)
        ):
            item = decode_record(identifier, kind, payload)
            p = item.provenance
            if as_of and (p.available_at > as_of or (mode == "system" and p.retrieved_at > as_of)):
                continue
            records.append(item)
        return records

    def audit(self) -> dict:
        count = 0
        checked = set()
        for identifier, kind, payload in self.entries():
            item = decode_record(identifier, kind, payload)
            digest = item.provenance.raw_sha256
            if digest not in checked:
                path = self.root / "raw" / digest
                if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise ValueError("lineage audit failed: missing or corrupt raw blob")
                checked.add(digest)
            count += 1
        return {"records": count, "raw_lineage": "verified"}
