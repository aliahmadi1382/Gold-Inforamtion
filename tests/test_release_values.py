import json
from datetime import UTC, date, datetime, timedelta

import pytest

from gold_intelligence.acquisition import acquire, list_runs
from gold_intelligence.cli import main
from gold_intelligence.ingestion import provenance
from gold_intelligence.models import Observation
from gold_intelligence.release_values import (
    DATASET,
    ReleaseValueEvidence,
    import_release_values,
    normalize_values,
    release_value_report,
    render_release_values,
)
from gold_intelligence.storage import record_id

CAPTURE = datetime(2024, 2, 10, tzinfo=UTC)
RETRIEVED = datetime(2024, 2, 11, tzinfo=UTC)
VINTAGE = date(2024, 2, 9)


def bundle(**changes):
    # Invented values and release date; this fixture is not a historical BLS claim.
    data = {
        "source_url": "https://www.bls.gov/news.release/archives/cpi_02092024.htm",
        "captured_at": CAPTURE.isoformat(),
        "metric": "cpi_all_items_sa_mom",
        "release_id": "USDL-24-9999",
        "headline_period": "2024-01",
        "announced_at": "2024-02-09T08:30:00-05:00",
        "timezone_evidence": "Invented EST header",
        "document_status": "archive_as_captured",
        "revision_note": "Fixture: first release not established",
        "values": [
            {
                "reference_period": "2024-01",
                "value": 0.1,
                "unit": "percent_change_mom_sa",
                "locator": "Invented all-items SA column",
                "review_note": "Invented one-decimal fixture",
            }
        ],
    }
    data.update(changes)
    return data


def insert(store, registry, payload=None, retrieved=RETRIEVED):
    evidence = ReleaseValueEvidence.model_validate(payload or bundle())
    content = evidence.model_dump_json().encode()
    records = normalize_values(evidence, registry.get("bls"), store.put_raw(content), retrieved)
    store.put(records)
    return records


def fred(
    store,
    registry,
    values=None,
    *,
    series="CPIAUCSL",
    vintage=VINTAGE,
    retrieved=RETRIEVED,
    response_vintage=None,
    raw_units="lin",
):
    values = values or [("2023-12-01", 100), ("2024-01-01", 100.1)]
    rt = (response_vintage or vintage or retrieved.date()).isoformat()
    rows = [
        {"date": d, "value": "." if v is None else str(v), "realtime_start": rt, "realtime_end": rt}
        for d, v in values
    ]
    content = json.dumps(
        {"realtime_start": rt, "realtime_end": rt, "units": raw_units, "observations": rows}
    ).encode()
    digest = store.put_raw(content)
    source = registry.get("fred").model_copy(
        update={"url": f"https://fred.stlouisfed.org/series/{series}"}
    )
    records = []
    for index, (day, value) in enumerate(values):
        records.append(
            Observation(
                provenance=provenance(
                    source,
                    digest,
                    f"observations:{index}",
                    datetime.fromisoformat(day + "T00:00:00+00:00"),
                    retrieved,
                    series,
                    "index_1982_1984_100_sa" if series == "CPIAUCSL" else "percent_sa",
                    None,
                    day,
                ),
                layer="macro",
                series_id=series,
                value=value,
                vintage_date=vintage,
                dimensions={"realtime_start": rt, "realtime_end": rt},
            )
        )
    store.put(records)
    return records


def test_value_identity_clocks_and_historical_cutoff(store, registry):
    r = insert(store, registry)[0]
    assert r.series_id == "BLS_CPI_U_SA_MOM" and r.provenance.dataset == DATASET
    assert r.provenance.available_at == RETRIEVED
    assert r.dimensions["announced_at"] == "2024-02-09T08:30:00-05:00"
    assert store.read("calendar_release") == []
    assert store.read("observation", CAPTURE, "source") == []
    assert release_value_report(store, registry, CAPTURE).status == "no_evidence"
    report = release_value_report(store, registry, RETRIEVED)
    assert report.documents[0].tehran_time.hour == 17
    assert report.intraday_replay_ready is report.documents[0].first_release_verified is False


def test_cpi_uses_same_vintage_adjacent_indices_and_current_revision_is_separate(store, registry):
    insert(store, registry)
    vintage = fred(store, registry)
    current = fred(store, registry, [("2023-12-01", 100), ("2024-01-01", 100.3)], vintage=None)
    report = release_value_report(store, registry, RETRIEVED)
    value = report.documents[0].values[0]
    assert report.status == "compared"
    assert value.release_date_vintage.value == pytest.approx(0.1)
    assert value.release_date_vintage.status == "matches_display"
    assert value.current_revision.difference_from_document == pytest.approx(0.2)
    assert value.current_revision.status == "differs_display"
    assert set(value.release_date_vintage.record_ids) == {record_id(r) for r in vintage}
    assert set(value.current_revision.record_ids) == {record_id(r) for r in current}
    text = render_release_values(report)
    assert "غافلگیری خبر" in text and "0.2" in text
    assert release_value_report(store, registry, RETRIEVED).fingerprint == report.fingerprint


def test_wrong_vintage_cannot_supply_missing_cpi_base(store, registry):
    insert(store, registry)
    fred(store, registry, [("2024-01-01", 100.1)])
    fred(store, registry, [("2023-12-01", 100)], vintage=date(2024, 2, 8))
    result = release_value_report(store, registry, RETRIEVED).documents[0].values[0]
    assert result.release_date_vintage.status == "missing_period"
    assert result.release_date_vintage.value is None


@pytest.mark.parametrize(
    "value,status",
    [
        (100.1499, "matches_display"),
        (100.15, "rounding_boundary"),
        (100.1501, "differs_display"),
        (99.9, "differs_display"),
    ],
)
def test_display_precision_is_not_exact_equality(store, registry, value, status):
    insert(store, registry)
    fred(store, registry, [("2023-12-01", 100), ("2024-01-01", value)])
    result = release_value_report(store, registry, RETRIEVED)
    assert result.documents[0].values[0].release_date_vintage.status == status


def test_unemployment_native_rate_and_reissued_document(store, registry):
    data = bundle(
        metric="unemployment_rate_sa",
        source_url="https://www.bls.gov/news.release/archives/empsit_02092024.htm",
        document_status="reissued",
        reissued_on="2024-02-10",
        captured_at="2024-02-10T17:00:00Z",
    )
    data["values"][0].update(value=4.2, unit="percent_sa")
    insert(store, registry, data)
    fred(store, registry, [("2024-01-01", 4.2)], series="UNRATE")
    report = release_value_report(store, registry, RETRIEVED)
    assert report.documents[0].reissued_on == date(2024, 2, 10)
    value = report.documents[0].values[0].release_date_vintage
    assert value.value == 4.2 and value.transformation == "native_unemployment_rate"


@pytest.mark.parametrize(
    "changes",
    [
        {"source_url": "https://www.bls.gov/schedule/news_release/cpi.htm"},
        {"source_url": "https://www.bls.gov/news.release/archives/cpi_02092024.htm?key=x"},
        {"source_url": "https://www.bls.gov.evil.test/news.release/archives/cpi_02092024.htm"},
        {"announced_at": "2024-02-09T08:30:00-04:00"},
        {"announced_at": "2024-02-09T08:30:00"},
        {"release_id": "USDL-23-9999"},
        {"document_status": "reissued"},
        {"reissued_on": "2024-02-10"},
        {"document_status": "reissued", "reissued_on": "2024-02-12"},
        {"document_status": "reissued", "reissued_on": "2024-02-01"},
        {"captured_at": "2024-02-01T00:00:00Z"},
    ],
)
def test_invalid_document_identity_and_chronology(changes):
    with pytest.raises(ValueError):
        ReleaseValueEvidence.model_validate(bundle(**changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"unit": "index_1982_1984_100_sa"},
        {"value": 0.123},
        {"value": float("inf")},
        {"value": 1e100},
        {"value": -100},
        {"reference_period": "2024-13"},
        {"reference_period": "2023-11"},
        {"reference_period": "2024-02"},
    ],
)
def test_invalid_published_value(changes):
    data = bundle()
    data["values"][0].update(changes)
    with pytest.raises(ValueError):
        ReleaseValueEvidence.model_validate(data)


def test_latest_document_replaces_whole_capture_and_older_reimport_cannot_restore_removed_row(
    store, registry
):
    old = bundle()
    old["values"].insert(0, {**old["values"][0], "reference_period": "2023-12", "value": 0.2})
    insert(store, registry, old)
    newer = bundle(captured_at="2024-02-12T00:00:00Z")
    insert(store, registry, newer, RETRIEVED + timedelta(days=2))
    insert(store, registry, old, RETRIEVED + timedelta(days=3))
    report = release_value_report(store, registry, RETRIEVED + timedelta(days=3))
    assert len(report.documents) == 1 and len(report.documents[0].values) == 1
    assert report.documents[0].values[0].period_role == "headline"


def test_conflicting_same_capture_documents_fail(store, registry):
    insert(store, registry)
    other = bundle()
    other["values"][0]["value"] = 0.2
    insert(store, registry, other)
    with pytest.raises(ValueError, match="conflicting same-capture"):
        release_value_report(store, registry, RETRIEVED)


def test_duplicate_period_and_missing_headline_are_rejected():
    data = bundle()
    data["values"].append(dict(data["values"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        ReleaseValueEvidence.model_validate(data)
    data = bundle()
    data["values"][0]["reference_period"] = "2023-12"
    with pytest.raises(ValueError, match="headline period"):
        ReleaseValueEvidence.model_validate(data)


def test_capture_after_ingestion_cannot_be_backdated(store, registry):
    with pytest.raises(ValueError, match="capture cannot follow"):
        insert(store, registry, retrieved=CAPTURE - timedelta(seconds=1))
    assert store.read("observation") == []


@pytest.mark.parametrize("tamper", ["normalized", "raw", "partial_bundle"])
def test_evidence_integrity_and_atomic_document_completeness(store, registry, tamper):
    data = bundle()
    data["values"].append({**data["values"][0], "reference_period": "2023-12"})
    rows = insert(store, registry, data)
    if tamper == "normalized":
        store.put([rows[0].model_copy(update={"value": 5})])
    elif tamper == "raw":
        (store.root / "raw" / rows[0].provenance.raw_sha256).write_bytes(b"changed")
    else:
        store.db.execute("DELETE FROM records WHERE id = ?", (record_id(rows[1]),))
        store.db.commit()
    with pytest.raises(ValueError):
        release_value_report(store, registry, RETRIEVED)


@pytest.mark.parametrize("tamper", ["wrong_vintage", "non_native", "normalized_value"])
def test_fred_raw_reconciliation(store, registry, tamper):
    insert(store, registry)
    records = fred(
        store,
        registry,
        response_vintage=date(2024, 2, 8) if tamper == "wrong_vintage" else None,
        raw_units="pch" if tamper == "non_native" else "lin",
    )
    if tamper == "normalized_value":
        store.db.execute("DELETE FROM records WHERE id = ?", (record_id(records[-1]),))
        store.db.commit()
        store.put([records[-1].model_copy(update={"value": 103})])
    with pytest.raises(ValueError):
        release_value_report(store, registry, RETRIEVED)


def test_latest_null_and_future_retrieval_not_backfilled(store, registry):
    insert(store, registry)
    fred(store, registry)
    later = RETRIEVED + timedelta(days=1)
    fred(store, registry, [("2024-01-01", None)], retrieved=later)
    assert release_value_report(store, registry, RETRIEVED).documents[0].values[
        0
    ].release_date_vintage.value == pytest.approx(0.1)
    after = release_value_report(store, registry, later)
    assert after.documents[0].values[0].release_date_vintage.status == "missing_value"


def test_import_review_manifest_and_empty_cli(store, registry, tmp_path, capsys):
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(bundle()), encoding="utf-8")
    with pytest.raises(ValueError, match="review"):
        import_release_values(store, path, registry.get("bls"))
    result = acquire(
        store,
        "import-release-values",
        {"reviewed": True},
        lambda: import_release_values(
            store, path, registry.get("bls"), reviewed=True, retrieved_at=RETRIEVED
        ),
    )
    assert result["inserted"] == 1 and list_runs(store.root)[0]["raw_blobs"] == 1
    assert (
        import_release_values(
            store, path, registry.get("bls"), reviewed=True, retrieved_at=RETRIEVED
        )
        == 0
    )
    output = tmp_path / "out"
    assert (
        main(
            [
                "--store",
                str(store.root),
                "release-value-report",
                "--as-of",
                CAPTURE.isoformat(),
                "--output-dir",
                str(output),
            ]
        )
        == 3
    )
    assert json.loads(capsys.readouterr().out)["status"] == "no_evidence"
    assert json.loads((output / "release-values.json").read_text())["documents"] == []
    assert "موجود نیست" in (output / "release-values.fa.md").read_text(encoding="utf-8")
