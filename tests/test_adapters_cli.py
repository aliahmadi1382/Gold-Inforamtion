import csv
import json
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.error import HTTPError

import pytest

from gold_intelligence.cli import main
from gold_intelligence.demo import demo
from gold_intelligence.ingestion import fetch_bytes, import_cftc, ingest_fred
from gold_intelligence.models import HistoricalEvent


def fred_page(offset, total, values):
    return json.dumps(
        {
            "count": total,
            "offset": offset,
            "observations": [
                {
                    "date": f"2024-01-{i + 1:02}",
                    "value": value,
                    "realtime_start": "2024-01-05",
                    "realtime_end": "2024-01-05",
                }
                for i, value in enumerate(values, offset)
            ],
        }
    ).encode()


def test_fred_pagination_nulls_and_vintage(store, registry, monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "not-a-real-key")
    pages = iter([fred_page(0, 3, ["2.1", "."]), fred_page(2, 3, ["2.3"])])
    requests = []

    def fetch(url):
        requests.append(url)
        return next(pages)

    count = ingest_fred(
        store,
        registry.get("fred"),
        "DFII10",
        date(2024, 1, 1),
        date(2024, 1, 5),
        "percent",
        vintage=date(2024, 1, 5),
        fetch=fetch,
    )
    assert count == 3
    assert "offset=2" in requests[1]
    assert "realtime_start=2024-01-05" in requests[0]
    items = store.read("observation")
    assert [item.value for item in items] == [2.1, None, 2.3]
    assert all(item.provenance.available_at == item.provenance.retrieved_at for item in items)
    assert all("not-a-real-key" not in item.model_dump_json() for item in items)
    assert store.read("observation", datetime(2024, 1, 5, tzinfo=UTC), "source") == []


def test_fred_missing_key_does_not_request(store, registry, monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    with pytest.raises(ValueError, match="FRED_API_KEY"):
        ingest_fred(
            store,
            registry.get("fred"),
            "DFII10",
            date(2024, 1, 1),
            date(2024, 1, 5),
            "percent",
            fetch=lambda _: pytest.fail("network was called"),
        )


def test_fred_repeated_page_is_rejected(store, registry, monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    pages = iter([fred_page(0, 2, ["2.1"]), fred_page(0, 2, ["2.1"])])
    with pytest.raises(ValueError, match="response structure"):
        ingest_fred(
            store,
            registry.get("fred"),
            "DFII10",
            date(2024, 1, 1),
            date(2024, 1, 5),
            "percent",
            fetch=lambda _: next(pages),
        )
    assert store.read("observation") == []


def test_cftc_requires_report_family_attestation(store, registry, tmp_path):
    with pytest.raises(ValueError, match="confirm"):
        import_cftc(store, tmp_path / "not-read-yet.csv", registry.get("cftc_legacy"))


def test_fred_partial_page_failure_keeps_normalized_batch_empty(store, registry, monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    pages = iter([fred_page(0, 3, ["2.1"]), b'{"observations": [], "count": 3, "offset": 1}'])
    with pytest.raises(ValueError, match="incomplete"):
        ingest_fred(
            store,
            registry.get("fred"),
            "DFII10",
            date(2024, 1, 1),
            date(2024, 1, 5),
            "percent",
            fetch=lambda _: next(pages),
        )
    assert store.read("observation") == []


def test_http_error_redacts_key(monkeypatch):
    def fail(*_args, **_kwargs):
        raise HTTPError("https://example.org/?api_key=SECRET", 403, "Forbidden", {}, None)

    monkeypatch.setattr("gold_intelligence.ingestion.urlopen", fail)
    with pytest.raises(ValueError) as error:
        fetch_bytes("https://example.org/?api_key=SECRET")
    assert "SECRET" not in str(error.value)
    assert "403" in str(error.value)


def test_cftc_native_headers_filter_and_net(store, registry, tmp_path):
    path = tmp_path / "annual.txt"
    headers = [
        "CFTC Contract Market Code",
        "As of Date in Form YYYY-MM-DD",
        "Open Interest (All)",
        "Noncommercial Positions-Long (All)",
        "Noncommercial Positions-Short (All)",
        "Noncommercial Positions-Spreading (All)",
        "Commercial Positions-Long (All)",
        "Commercial Positions-Short (All)",
        "Nonreportable Positions-Long (All)",
        "Nonreportable Positions-Short (All)",
    ]
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        # Explicit fictional counts; official column names only.
        writer.writerow(["088691", "2024-01-02", 1000, 500, 100, 50, 300, 750, 150, 100])
        writer.writerow(["084691", "2024-01-02", 1000, 500, 100, 50, 300, 750, 150, 100])
    assert import_cftc(store, path, registry.get("cftc_legacy"), futures_only_confirmed=True) == 3
    items = store.read("positioning")
    assert {r.category: r.net for r in items} == {
        "non_commercial": 400,
        "commercial": -450,
        "non_reportable": 50,
    }
    assert all(r.market_code == "088691" for r in items)
    assert all(r.provenance.availability_basis == "retrieval_time" for r in items)


def test_demo_is_offline_reproducible_and_auditable(tmp_path, registry):
    first = demo(tmp_path, registry)
    output = (tmp_path / "snapshot.json").read_bytes()
    second = demo(tmp_path, registry)
    assert first["inserted"] == 80
    assert second["inserted"] == 0
    assert second["records"] == 80
    assert (tmp_path / "snapshot.json").read_bytes() == output
    assert json.loads(output)["synthetic"] is True


def test_cli_error_and_registry(capsys):
    assert main(["validate-registry"]) == 0
    assert '"valid": true' in capsys.readouterr().out
    assert main(["--registry", "nonexistent-registry.yaml", "validate-registry"]) == 2
    assert "error:" in capsys.readouterr().err


def test_generated_schemas_match_runtime(tmp_path):
    assert main(["schemas", "--output", str(tmp_path)]) == 0
    for path in tmp_path.glob("*.schema.json"):
        assert json.loads(path.read_text()) == json.loads((Path("schemas") / path.name).read_text())


def test_demo_snapshot_matches_json_schema(tmp_path, registry):
    import jsonschema

    demo(tmp_path, registry)
    jsonschema.validate(
        json.loads((tmp_path / "snapshot.json").read_text()),
        json.loads(Path("schemas/market_snapshot.schema.json").read_text()),
        format_checker=jsonschema.FormatChecker(),
    )


def test_historical_event_seeds_are_valid_and_unique():
    events = json.loads(Path("data/events/historical_events.json").read_text())
    parsed = [HistoricalEvent.model_validate(e) for e in events]
    assert len({e.event_id for e in parsed}) == len(parsed)
    assert any(e.verification == "research_candidate" for e in parsed)
