"""Local immutable raw blobs and transactional, idempotent SQLite records."""

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .models import RECORD_TYPES, Record, aware


def canonical(value: dict) -> str:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def record_id(record: Record) -> str:
    return hashlib.sha256(canonical(record.model_dump(mode="json")).encode()).hexdigest()


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        (self.root / "raw").mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "market.sqlite3")
        self.db.execute("""CREATE TABLE IF NOT EXISTS records (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL)""")
        self.db.commit()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.db.close()

    def put_raw(self, content: bytes) -> str:
        digest = hashlib.sha256(content).hexdigest()
        path = self.root / "raw" / digest
        try:
            with path.open("xb") as stream:
                stream.write(content)
        except FileExistsError:
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("existing raw blob failed integrity check") from None
        return digest

    def put(self, records: list[Record]) -> int:
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
        return self.db.total_changes - before

    def read(self, kind: str, as_of: datetime | None = None, mode: str = "system") -> list:
        if kind not in RECORD_TYPES or mode not in {"system", "source"}:
            raise ValueError("unknown record kind or replay mode")
        if as_of:
            aware(as_of)
        records = []
        for identifier, payload in self.db.execute(
            "SELECT id, payload FROM records WHERE kind = ?", (kind,)
        ):
            item = RECORD_TYPES[kind].model_validate_json(payload)
            if record_id(item) != identifier:
                raise ValueError("normalized record content hash mismatch")
            p = item.provenance
            if as_of and (p.available_at > as_of or (mode == "system" and p.retrieved_at > as_of)):
                continue
            records.append(item)
        return records

    def audit(self) -> dict:
        count = 0
        for kind in RECORD_TYPES:
            for item in self.read(kind):
                path = self.root / "raw" / item.provenance.raw_sha256
                if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != path.name:
                    raise ValueError("lineage audit failed: missing or corrupt raw blob")
                count += 1
        return {"records": count, "raw_lineage": "verified"}
