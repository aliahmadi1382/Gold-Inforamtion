import json
import runpy
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from gold_intelligence.acquisition import list_runs
from gold_intelligence.cli import main
from gold_intelligence.ingestion import provenance
from gold_intelligence.macro import MacroPlan, fetch_core, load_plan, macro_context
from gold_intelligence.models import Observation
from gold_intelligence.quality import QualityPolicy


def when(day):
    return datetime(2024, 1, day, tzinfo=UTC)


@pytest.fixture
def plan():
    return MacroPlan(series=load_plan(Path("config/macro_core.yaml")).series[:2])


def observation(
    store,
    registry,
    *,
    observed=1,
    available=2,
    retrieved=2,
    value=1,
    series="DFF",
    vintage=None,
    unit="percent",
    dimensions=None,
):
    raw = store.put_raw(b"invented macro fixture")
    p = provenance(
        registry.get("fred"),
        raw,
        f"{observed}:{value}",
        when(observed),
        when(retrieved),
        series,
        unit,
        None,
        f"2024-01-{observed:02}",
        available=when(available) if available != retrieved else None,
    )
    return Observation(
        provenance=p,
        layer="macro",
        series_id=series,
        value=value,
        vintage_date=vintage,
        dimensions=dimensions or {},
    )


def test_reviewed_units_match_existing_shortlist():
    original = yaml.safe_load(Path("config/macro_series.yaml").read_text())["series"]
    for spec in load_plan(Path("config/macro_core.yaml")).series:
        assert spec.unit == original[spec.series_id]["unit"]
        assert spec.currency == original[spec.series_id]["currency"]


def test_future_revisions_and_reference_dates_never_leak(store, registry, plan):
    store.put(
        [
            observation(store, registry, value=10),
            observation(store, registry, value=20, available=5, retrieved=5),
            observation(store, registry, observed=8, value=99),
        ]
    )
    report = macro_context(store, plan, when(3))
    assert report.entries[0].value == 10
    assert report.entries[1].status == "missing"
    assert report.status == "incomplete"
    assert macro_context(store, plan, when(6)).entries[0].value == 20


def test_source_and_system_replay_distinguish_verified_release(store, registry, plan):
    store.put([observation(store, registry, available=2, retrieved=5)])
    assert macro_context(store, plan, when(3)).entries[0].status == "missing"
    assert macro_context(store, plan, when(3), "source").entries[0].value == 1


def test_latest_null_is_not_replaced_by_previous_value(store, registry, plan):
    store.put(
        [
            observation(store, registry, value=10),
            observation(store, registry, observed=3, available=4, retrieved=4, value=None),
        ]
    )
    entry = macro_context(store, plan, when(5)).entries[0]
    assert entry.status == "missing_value" and entry.value is None
    assert entry.reference_at == when(3)
    assert entry.record_id


def test_staleness_measures_reference_age(store, registry, plan):
    store.put([observation(store, registry)])
    entry = macro_context(store, plan, when(10)).entries[0]
    assert entry.status == "stale" and entry.reference_age_days == 9


def test_vintage_is_separate_and_does_not_backdate_availability(store, registry, plan):
    vintage = date(2024, 1, 2)
    store.put(
        [
            observation(store, registry, value=10),
            observation(store, registry, value=8, vintage=vintage, available=8, retrieved=8),
        ]
    )
    assert macro_context(store, plan, when(9)).entries[0].value == 10
    assert macro_context(store, plan, when(9), vintage=vintage).entries[0].value == 8
    assert macro_context(store, plan, when(3), "source", vintage).entries[0].status == "missing"
    with pytest.raises(ValueError, match="vintage"):
        macro_context(store, plan, when(1), vintage=vintage)


@pytest.mark.parametrize("kwargs", [{"unit": "index"}, {"dimensions": {"frequency": "M"}}])
def test_mixed_stream_is_rejected(store, registry, plan, kwargs):
    store.put([observation(store, registry, **kwargs)])
    with pytest.raises(ValueError, match="incompatible"):
        macro_context(store, plan, when(3))


def test_conflicting_revisions_fail_without_arbitrary_value_choice(store, registry, plan):
    store.put([observation(store, registry, value=1), observation(store, registry, value=2)])
    with pytest.raises(ValueError, match="conflicting"):
        macro_context(store, plan, when(3))


def mock_provider(url, bad_metadata=False):
    parts = urlsplit(url)
    params = parse_qs(parts.query)
    series = params["series_id"][0]
    assert params["api_key"] == ["private-test-key"]
    if parts.path.endswith("/observations"):
        return json.dumps(
            {
                "count": 1,
                "offset": 0,
                "observations": [
                    {
                        "date": "2024-01-01",
                        "value": "1",
                        "realtime_start": "2024-01-05",
                        "realtime_end": "2024-01-05",
                    }
                ],
            }
        ).encode()
    return json.dumps(
        {
            "seriess": [
                {
                    "id": series,
                    "units": "wrong" if bad_metadata else "Percent",
                    "frequency_short": "D",
                    "seasonal_adjustment_short": "NSA",
                }
            ]
        }
    ).encode()


def test_reviewed_batch_traces_plan_metadata_and_observations(store, registry, plan, monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "private-test-key")
    result = fetch_core(
        store, registry.get("fred"), plan, date(2024, 1, 1), date(2024, 1, 5), fetch=mock_provider
    )
    assert result["status"] == "succeeded" and result["inserted"] == 2
    runs = list_runs(store.root)
    assert len(runs) == 2 and all(r["raw_blobs"] == 3 for r in runs)
    assert all("private-test-key" not in p.read_text() for p in (store.root / "runs").glob("*"))


def test_metadata_drift_blocks_only_affected_series_and_cli_exits_nonzero(
    store, registry, plan, monkeypatch, tmp_path
):
    monkeypatch.setenv("FRED_API_KEY", "private-test-key")

    def fetch(url):
        bad = "series_id=DFF" in url
        assert not (bad and "/observations" in url)
        return mock_provider(url, bad_metadata=bad)

    result = fetch_core(
        store, registry.get("fred"), plan, date(2024, 1, 1), date(2024, 1, 5), fetch=fetch
    )
    assert result["status"] == "partial" and result["inserted"] == 1
    assert {r["status"] for r in list_runs(store.root)} == {"failed", "succeeded"}
    assert {r.series_id for r in store.read("observation")} == {"DGS10"}
    monkeypatch.setattr("gold_intelligence.cli.fetch_core", lambda *_: result)
    assert main(["--store", str(tmp_path / "cli"), "fetch-fred-core", "--end", "2024-01-05"]) == 3


def test_missing_key_records_safe_failures_without_network(store, registry, plan, monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    result = fetch_core(
        store,
        registry.get("fred"),
        plan,
        date(2024, 1, 1),
        date(2024, 1, 5),
        fetch=lambda *_: pytest.fail("network called"),
    )
    assert result["status"] == "failed" and result["inserted"] == 0
    assert len(list_runs(store.root)) == 2


def test_history_audit_checks_metadata_bytes_not_only_observation_bytes(
    store, registry, plan, monkeypatch
):
    monkeypatch.setenv("FRED_API_KEY", "private-test-key")
    fetch_core(
        store, registry.get("fred"), plan, date(2024, 1, 1), date(2024, 1, 5), fetch=mock_provider
    )
    metadata = next(p for p in (store.root / "raw").iterdir() if b'"seriess"' in p.read_bytes())
    metadata.write_bytes(b"changed metadata")
    assert store.audit()["raw_lineage"] == "verified"  # Base audit covers record-linked bytes.
    monkeypatch.syspath_prepend(str(Path("scripts").resolve()))
    inspect = runpy.run_path("scripts/inspect_history.py")["inspect_history"]
    with pytest.raises(ValueError, match="acquisition raw evidence"):
        inspect(store, registry, datetime.now(UTC), QualityPolicy(), plan)
