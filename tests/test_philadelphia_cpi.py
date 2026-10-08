import hashlib
import io
from datetime import UTC, datetime

import pytest
from openpyxl import Workbook

from gold_intelligence.philadelphia_cpi import DATASET, UNIT, ingest_pcpi, parse_pcpi


def workbook(rows=None, unit=None):
    book = Workbook()
    notes = book.active
    notes.title = "NOTES"
    for value in (
        "Variable ID: PCPI",
        unit or "Unit of Measurement: M/M Growth (Annual Rate, Percentage Points)",
        "Source: Bureau of Labor Statistics (BLS)",
    ):
        notes.append([value])
    data = book.create_sheet("DATA")
    for row in (
        ["Consumer Price Index Monthly Vintages (PCPI)"],
        ["M/M Growth (Annual Rate, Percentage Points)"],
        ["Release values"],
        [None],
        ["Date", "First", "Second", "Third", "Most_Recent"],
    ):
        data.append(row)
    for row in rows or [["2026:08", 4.8571, "#N/A", "#N/A", 4.8571]]:
        data.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    book.close()
    return buffer.getvalue()


def test_native_annualization_and_retrieval_availability(registry):
    content = workbook()
    retrieved = datetime(2026, 10, 8, tzinfo=UTC)
    records = parse_pcpi(
        content,
        registry.get("philadelphia_fed_pcpi"),
        hashlib.sha256(content).hexdigest(),
        retrieved,
    )
    assert len(records) == 4
    assert [r.value for r in records] == [4.8571, None, None, 4.8571]
    assert records[0].provenance.unit == UNIT
    assert records[0].provenance.dataset == DATASET
    assert all(r.provenance.available_at == retrieved for r in records)
    assert all(r.vintage_date is None for r in records)
    assert records[0].dimensions["release_time_evidence"] == "not_measured"


@pytest.mark.parametrize("damage", ["unit", "duplicate", "future", "boolean", "bad_month"])
def test_reject_semantically_changed_workbooks(registry, damage):
    rows = [["2026:08", 4.8571, "#N/A", "#N/A", 4.8571]]
    if damage == "duplicate":
        rows += rows
    elif damage == "future":
        rows[0][0] = "2027:01"
    elif damage == "boolean":
        rows[0][1] = True
    elif damage == "bad_month":
        rows[0][0] = "2026:13"
    content = workbook(rows, "Unit of Measurement: CPI level" if damage == "unit" else None)
    with pytest.raises(ValueError):
        parse_pcpi(
            content,
            registry.get("philadelphia_fed_pcpi"),
            hashlib.sha256(content).hexdigest(),
            datetime(2026, 10, 8, tzinfo=UTC),
        )


def test_ingestion_preserves_workbook_lineage(store, registry):
    content = workbook()
    assert ingest_pcpi(store, registry.get("philadelphia_fed_pcpi"), fetch=lambda _: content) == 4
    assert len(store.read("observation", datetime.now(UTC))) == 4
    assert (store.root / "raw" / hashlib.sha256(content).hexdigest()).read_bytes() == content
