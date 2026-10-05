import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from gold_intelligence.ingestion import import_prices, import_records
from gold_intelligence.models import CalendarRelease, PriceBar, Provenance
from gold_intelligence.registry import Registry, export_public
from gold_intelligence.storage import record_id


@pytest.mark.parametrize(
    "changes",
    [
        {"close": float("nan")},
        {"high": float("inf")},
        {"low": 0},
        {"open": 200},
        {"volume": 20},
        {"price_type": "futures"},
        {"provenance": {"observed_at": datetime(2024, 1, 1)}},
        {"provenance": {"original_timezone": "Unknown/Planet"}},
        {"provenance": {"available_at": datetime(2025, 1, 1, tzinfo=UTC)}},
        {"provenance": {"synthetic": False}},
    ],
)
def test_invalid_prices_fail(make_bar, changes):
    with pytest.raises(ValidationError):
        make_bar(**changes)


def test_store_idempotence_and_tamper_detection(store, make_bar):
    bar = make_bar()
    assert store.put([bar]) == 1
    assert store.put([bar]) == 0
    assert store.audit()["records"] == 1
    (store.root / "raw" / bar.provenance.raw_sha256).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="corrupt"):
        store.audit()


def test_normalized_record_tampering_is_detected(store, make_bar):
    bar = make_bar()
    store.put([bar])
    altered = bar.model_dump(mode="json")
    altered["provenance"]["confidence"] = 0.2
    store.db.execute("UPDATE records SET payload = ?", (json.dumps(altered),))
    store.db.commit()
    with pytest.raises(ValueError, match="content hash"):
        store.audit()


def test_csv_iana_timezone_checks_dst(store, registry, tmp_path):
    path = tmp_path / "prices.csv"
    path.write_text("observed_at,open,high,low,close\n2024-07-01T17:00:00-04:00,100,102,99,101\n")
    assert (
        import_prices(
            store,
            path,
            registry.get("user_price_csv"),
            instrument="XAUUSD",
            venue="test",
            dataset="test",
            original_timezone="America/New_York",
        )
        == 1
    )
    assert store.read("price_bar")[0].provenance.original_timezone == "America/New_York"
    with pytest.raises(ValueError, match="offset"):
        import_prices(
            store,
            path,
            registry.get("user_price_csv"),
            instrument="XAUUSD",
            venue="test",
            dataset="test",
            original_timezone="UTC",
        )


def test_missing_raw_rejects_whole_batch(store, make_bar):
    first, second = make_bar(), make_bar(1)
    fields = second.model_dump()
    fields["provenance"]["raw_sha256"] = "a" * 64
    second = PriceBar.model_validate(fields)
    with pytest.raises(ValueError, match="raw blob"):
        store.put([first, second])
    assert store.read("price_bar") == []


def test_as_of_release_and_retrieval_are_separate(store, make_bar):
    release = datetime(2024, 1, 5, 20, 30, tzinfo=UTC)
    retrieved = release + timedelta(days=2)
    bar = make_bar(provenance={"available_at": release, "retrieved_at": retrieved})
    store.put([bar])
    assert store.read("price_bar", release - timedelta(seconds=1), "source") == []
    assert store.read("price_bar", release, "source") == [bar]
    assert store.read("price_bar", release, "system") == []
    assert store.read("price_bar", retrieved, "system") == [bar]


def test_unverified_availability_cannot_be_backdated(make_bar):
    data = make_bar().provenance.model_dump()
    data.update(
        synthetic=False,
        availability_basis="retrieval_time",
        retrieved_at=datetime(2024, 2, 1, tzinfo=UTC),
    )
    with pytest.raises(ValidationError, match="retrieval time"):
        Provenance(**data)


def test_public_export_checks_whole_batch_before_write(registry, make_bar, tmp_path):
    allowed = make_bar()
    denied = make_bar(
        1,
        provenance={
            "source_id": "user_price_csv",
            "license_status": "RESTRICTED",
            "license_id": "unreviewed-user-import",
        },
    )
    path = tmp_path / "export.jsonl"
    with pytest.raises(ValueError, match="redistribution"):
        export_public([allowed, denied], registry, path)
    assert not path.exists()
    assert export_public([allowed], registry, path) == 1
    with pytest.raises(FileExistsError):
        export_public([allowed], registry, path)


def test_duplicate_registry_source_fails(registry):
    data = registry.model_dump()
    data["sources"] = list(data["sources"]) + [data["sources"][0]]
    with pytest.raises(ValidationError, match="unique"):
        Registry(**data)


def test_csv_bad_second_row_is_atomic(store, registry, tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text(
        "observed_at,open,high,low,close\n2024-01-01T22:00:00Z,100,102,99,101\n"
        "2024-01-02T22:00:00Z,100,102,99,150\n"
    )
    with pytest.raises(ValidationError):
        import_prices(
            store,
            path,
            registry.get("user_price_csv"),
            instrument="XAUUSD",
            venue="test",
            dataset="test",
        )
    assert store.read("price_bar") == []


@pytest.mark.parametrize("second", ["2024-01-01T22:00:00Z", "2024-01-01T17:00:00-05:00"])
def test_csv_duplicate_instants_rejected(store, registry, tmp_path, second):
    path = tmp_path / "duplicate.csv"
    path.write_text(
        "observed_at,open,high,low,close\n2024-01-01T22:00:00Z,100,102,99,101\n"
        f"{second},100,102,99,101\n"
    )
    with pytest.raises(ValueError, match="duplicate"):
        import_prices(
            store,
            path,
            registry.get("user_price_csv"),
            instrument="XAUUSD",
            venue="test",
            dataset="test",
        )


def test_import_records_validates_evidence(store, registry, make_bar, tmp_path):
    bar = make_bar()
    path = tmp_path / "records.jsonl"
    path.write_text(bar.model_dump_json() + "\n", encoding="utf-8")
    assert import_records(store, path, store.root / "raw", registry) == 1
    assert record_id(store.read("price_bar")[0]) == record_id(bar)
    data = json.loads(path.read_text())
    data["provenance"]["license_id"] = "invented-permission"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="registry"):
        import_records(store, path, store.root / "raw", registry)


def test_calendar_cannot_expose_actual_before_release(make_bar):
    p = make_bar().provenance
    fields = dict(
        provenance=p,
        event_id="cpi",
        series_id="CPI",
        reference_period="2023-12",
        scheduled_at=p.observed_at + timedelta(days=1),
        actual=3.0,
    )
    with pytest.raises(ValidationError, match="release time"):
        CalendarRelease(**fields)
    fields["actual_release_at"] = p.available_at
    fields.update(consensus=2.9, consensus_as_of=p.available_at)
    with pytest.raises(ValidationError, match="precede"):
        CalendarRelease(**fields)
