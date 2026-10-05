import json
import runpy
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest

from gold_intelligence.acquisition import list_runs
from gold_intelligence.alpha_vantage import ingest_alpha_gold, parse_gold_history
from gold_intelligence.cli import main
from gold_intelligence.models import PriceClose
from gold_intelligence.quality import QualityPolicy, RequiredStream, assess
from gold_intelligence.registry import export_public, validate_record_source


# Invented prices in the observed provider schema; no vendor data in repository fixtures.
def response(rows=None, **changes):
    payload = {
        "nominal": "XAUUSD",
        "data": rows
        if rows is not None
        else [
            {"date": "2024-01-07", "price": "102.25"},
            {"date": "2024-01-05", "price": "101.5"},
        ],
    }
    payload.update(changes)
    return json.dumps(payload).encode()


def parse(store, registry, content=None):
    content = content if content is not None else response()
    return parse_gold_history(
        content,
        registry.get("alpha_vantage_gold"),
        store.put_raw(content),
        datetime(2024, 1, 8, 12, tzinfo=UTC),
    )


def test_dates_are_labels_and_weekends_are_preserved_without_fabricated_candles(store, registry):
    records = parse(store, registry)
    assert len(records) == 2
    close = records[0]
    assert close.session_date.isoformat() == "2024-01-07"  # Sunday, not silently removed.
    assert close.close == 102.25
    assert close.provenance.observed_at == datetime(2024, 1, 7, tzinfo=UTC)
    assert close.provenance.available_at == close.provenance.retrieved_at
    assert close.provenance.availability_basis == "retrieval_time"
    assert close.session_timezone is None
    assert close.unit_basis == "instrument_convention"
    assert not {"open", "high", "low", "volume"} & close.model_dump().keys()
    validate_record_source(close, registry)
    assert store.put(records) == 2
    assert store.put(records) == 0
    assert store.read("price_bar") == []
    assert store.read("price_close", datetime(2024, 1, 7, tzinfo=UTC), "source") == []
    assert store.audit()["records"] == 2


@pytest.mark.parametrize(
    "content",
    [
        b"not json",
        b"[]",
        response(nominal="XAGUSD"),
        response(extra="unexpected"),
        response([]),
        response([{"date": "2024-01-01", "price": "100", "open": "99"}]),
        response([{"date": "2024-01-01", "price": "nan"}]),
        response([{"date": "2024-01-01", "price": "-1"}]),
        response([{"date": "2024-01-01", "price": True}]),
        response([{"date": "2024-01-09", "price": "100"}]),
        response([{"date": "20240101", "price": "100"}]),
        response([{"date": "2024-01-01", "price": "100"}] * 2),
    ],
)
def test_bad_schema_values_and_duplicate_or_future_dates_reject_whole_batch(
    store, registry, content
):
    with pytest.raises(ValueError):
        parse(store, registry, content)
    assert store.read("price_close") == []


@pytest.mark.parametrize("field", ["Information", "Note", "Error Message"])
def test_service_messages_do_not_echo_keys(store, registry, field):
    with pytest.raises(ValueError) as error:
        parse(store, registry, json.dumps({field: "API key private-secret rejected"}).encode())
    assert "private-secret" not in str(error.value)


def test_fetch_uses_one_request_with_correct_parameters_and_records_raw(
    store, registry, monkeypatch
):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "test-only-key")
    calls = []

    def fetch(url, *, attempts):
        calls.append(url)
        params = parse_qs(urlsplit(url).query)
        assert urlsplit(url).hostname == "www.alphavantage.co"
        assert params == {
            "function": ["GOLD_SILVER_HISTORY"],
            "symbol": ["GOLD"],
            "interval": ["daily"],
            "apikey": ["test-only-key"],
        }
        assert attempts == 1
        return response()

    assert ingest_alpha_gold(store, registry.get("alpha_vantage_gold"), fetch) == 2
    assert len(calls) == 1
    assert store.audit()["records"] == 2


def test_missing_key_does_not_request_network(store, registry, monkeypatch):
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ALPHAVANTAGE_API_KEY"):
        ingest_alpha_gold(store, registry.get("alpha_vantage_gold"), lambda *_: pytest.fail())


def test_quality_warns_about_known_limits_and_close_does_not_satisfy_ohlc(store, registry):
    records = parse(store, registry)
    store.put(records)
    policy = QualityPolicy(required_streams=(RequiredStream(kind="price_bar"),))
    report = assess(store, registry, records[0].provenance.retrieved_at, policy)
    assert report.data_mode == "real"
    assert report.status == "fail"
    assert {issue.code for issue in report.issues} == {
        "REQUIRED_STREAM_MISSING",
        "RELEASE_TIME_UNKNOWN",
        "DATE_ONLY_PRICE",
        "UNIT_INFERRED",
        "WEEKEND_DATE_LABELS",
    }
    assert report.streams[0].weekend_date_labels == 1
    assert report.streams[0].date_only_prices == 2
    assert report.streams[0].unique_observations == 2


def test_close_contract_rejects_intraday_labels_and_ohlc_fields(store, registry):
    item = parse(store, registry)[0].model_dump()
    with pytest.raises(ValueError):
        PriceClose.model_validate({**item, "open": 100})
    item["provenance"]["observed_at"] = datetime(2024, 1, 7, 22, tzinfo=UTC)
    with pytest.raises(ValueError, match="date label"):
        PriceClose.model_validate(item)


def test_provider_data_cannot_be_publicly_exported(store, registry, tmp_path):
    records = parse(store, registry)
    target = tmp_path / "public.jsonl"
    with pytest.raises(ValueError, match="redistribution"):
        export_public(records, registry, target)
    assert not target.exists()


def test_cli_alpha_failure_is_traced_without_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    assert main(["--store", str(tmp_path / "store"), "fetch-alpha-gold"]) == 2
    assert list_runs(tmp_path / "store")[0]["status"] == "failed"
    capsys.readouterr()


@pytest.mark.parametrize("change", ["none", "missing_row", "wrong_value"])
def test_saved_byte_reconciliation_checks_values_and_full_raw_coverage(store, registry, change):
    records = parse(store, registry)
    if change == "missing_row":
        records = records[:1]
    elif change == "wrong_value":
        records[0] = records[0].model_copy(update={"close": 150.0})
    store.put(records)
    inspect = runpy.run_path("scripts/inspect_onboarding.py")["inspect"]
    report = inspect(store, registry, datetime(2024, 1, 8, 12, tzinfo=UTC), QualityPolicy())
    assert report["reconciliation"]["status"] == ("pass" if change == "none" else "fail")
    assert report["status"] == ("warning" if change == "none" else "fail")
