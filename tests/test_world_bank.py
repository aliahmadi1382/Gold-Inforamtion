import io
import json
import runpy
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from gold_intelligence.alpha_vantage import parse_gold_history
from gold_intelligence.comparison import compare_monthly
from gold_intelligence.macro import load_plan
from gold_intelligence.quality import QualityPolicy
from gold_intelligence.registry import export_public
from gold_intelligence.world_bank import GOLD_DESCRIPTION, parse_monthly_gold


def workbook(rows=None, unit="($/troy oz)", description=GOLD_DESCRIPTION, duplicate_column=False):
    """Tiny invented Open XML fixture; no real vendor workbook or data in the repository."""
    rows = rows if rows is not None else [("2025M05", 100), ("2025M06", 120)]
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

    def cell(ref, value):
        if isinstance(value, (int, float)):
            return f'<c r="{ref}"><v>{value}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'

    data = '<row r="5">' + cell("B5", "Gold")
    if duplicate_column:
        data += cell("C5", "Gold")
    data += '</row><row r="6">' + cell("B6", unit) + "</row>"
    for n, (label, value) in enumerate(rows, 7):
        data += f'<row r="{n}">' + cell(f"A{n}", label) + cell(f"B{n}", value) + "</row>"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "[Content_Types].xml",
            (
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Override PartName="/xl/workbook.xml" ContentType='
                '"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                "</Types>"
            ),
        )
        z.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{ns}" xmlns:r="{rel}"><sheets>'
            '<sheet name="Monthly Prices" sheetId="1" r:id="rId1"/>'
            '<sheet name="Description" sheetId="2" r:id="rId2"/></sheets></workbook>',
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                f'<Relationship Id="rId1" Type="{rel}/worksheet" Target="worksheets/sheet1.xml"/>'
                f'<Relationship Id="rId2" Type="{rel}/worksheet" Target="worksheets/sheet2.xml"/>'
                "</Relationships>"
            ),
        )
        z.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{ns}">'
            f'<dimension ref="A1:C{6 + len(rows)}"/><sheetData>{data}</sheetData></worksheet>',
        )
        z.writestr(
            "xl/worksheets/sheet2.xml",
            f'<worksheet xmlns="{ns}">'
            '<dimension ref="A1:CI1"/><sheetData><row r="1">'
            f"{cell('B1', description)}</row></sheetData></worksheet>",
        )
    return out.getvalue()


def parse(store, registry, **kwargs):
    content = workbook(**kwargs)
    return parse_monthly_gold(
        content,
        registry.get("world_bank_pink_sheet"),
        store.put_raw(content),
        datetime(2025, 7, 2, tzinfo=UTC),
    )


def test_monthly_units_method_change_availability_and_no_daily_conversion(
    store, registry, tmp_path
):
    records = parse(store, registry)
    assert [r.value for r in records] == [100, 120]
    assert records[0].dimensions["methodology"] == "london_afternoon_fixing_average"
    assert records[1].dimensions["methodology"] == "spot_daily_average"
    assert records[0].provenance.raw_record_id == "Monthly Prices!B7"
    assert all(r.provenance.available_at == r.provenance.retrieved_at for r in records)
    assert store.put(records) == 2 and store.put(records) == 0
    assert store.read("price_close") == store.read("price_bar") == []
    assert store.read("observation", datetime(2025, 6, 30, tzinfo=UTC), "source") == []
    with pytest.raises(ValueError, match="redistribution"):
        export_public(records, registry, tmp_path / "must-not-exist.jsonl")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"unit": "$/gram"},
        {"description": "Gold, new methodology"},
        {"duplicate_column": True},
        {"rows": [("2025M05", 100), ("2025M05", 101)]},
        {"rows": [("2025M04", 100), ("2025M06", 101)]},
        {"rows": [("2025M07", 100)]},
        {"rows": [("2025M13", 100)]},
        {"rows": [("2025M06", 0)]},
        {"rows": [("2025M06", "nan")]},
        {"rows": [("2025M06", "")]},
        {"rows": []},
    ],
)
def test_changed_or_bad_monthly_input_fails_atomically(store, registry, kwargs):
    with pytest.raises(ValueError):
        store.put(parse(store, registry, **kwargs))
    assert store.read("observation") == []


def test_archive_size_guard(store, registry):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("too-big.xml", b"x" * 30_000_001)
    with pytest.raises(ValueError, match="expanded size"):
        parse_monthly_gold(
            out.getvalue(),
            registry.get("world_bank_pink_sheet"),
            "a" * 64,
            datetime(2025, 7, 2, tzinfo=UTC),
        )


def add_closes(store, registry, rows):
    content = json.dumps({"nominal": "XAUUSD", "data": rows}).encode()
    records = parse_gold_history(
        content,
        registry.get("alpha_vantage_gold"),
        store.put_raw(content),
        datetime(2025, 7, 2, tzinfo=UTC),
    )
    store.put(records)


def test_monthly_comparison_preserves_weekends_and_excludes_boundary_months(store, registry):
    store.put(parse(store, registry))
    add_closes(
        store,
        registry,
        [
            {"date": "2025-05-15", "price": "100"},  # partial first month excluded
            {"date": "2025-06-01", "price": "180"},  # Sunday, retained
            {"date": "2025-06-02", "price": "90"},
            {"date": "2025-06-30", "price": "90"},
        ],
    )
    report = compare_monthly(store, datetime(2025, 7, 3, tzinfo=UTC))
    assert report["excluded_boundary_months"] == ["2025-05"]
    row = report["months"][0]
    assert row["alpha_all_labels_mean"] == 120
    assert row["alpha_weekdays_mean"] == 90
    assert row["relative_difference_all"] == 0
    assert row["relative_difference_weekdays"] == -0.25
    assert row["alpha_weekend_labels"] == 1
    assert row["weekday_slots_without_labels"] == 19
    assert report["status"] == "descriptive_only"
    assert report["first_weekend_label"] == "2025-06-01"
    assert compare_monthly(store, datetime(2025, 6, 30, tzinfo=UTC))["status"] == "no_overlap"


def test_history_inspector_detects_monthly_normalization_mismatch(store, registry, monkeypatch):
    monkeypatch.syspath_prepend(str(Path("scripts").resolve()))
    inspect = runpy.run_path("scripts/inspect_history.py")["inspect_history"]
    records = parse(store, registry)
    store.put(records)
    add_closes(store, registry, [{"date": "2025-06-02", "price": "100"}])
    args = (
        store,
        registry,
        datetime(2025, 7, 3, tzinfo=UTC),
        QualityPolicy(),
        load_plan(Path("config/macro_core.yaml")),
    )
    assert inspect(*args)["monthly_raw_cells_matched"] == 2
    store.put([records[0].model_copy(update={"value": 999})])
    with pytest.raises(ValueError, match="monthly raw-cell"):
        inspect(*args)
