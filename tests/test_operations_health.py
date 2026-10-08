import json
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError, URLError

import pytest
from test_refresh import offline as offline
from test_research_report import settings as settings

from gold_intelligence import cli, ingestion, refresh
from gold_intelligence.acquisition import AcquisitionRun, write_manifest
from gold_intelligence.operations_health import (
    build_operations_health,
    retry_action,
    write_operations_health,
)
from gold_intelligence.refresh import RefreshPolicy, refresh_and_report


def trace(store, number, status, parameters=None, failure="ValueError"):
    started = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=number)
    run = AcquisitionRun(
        run_id=f"{number:032x}",
        operation="fetch-fred",
        application_version="0.13.0",
        started_at=started,
        finished_at=None if status == "running" else started,
        status=status,
        parameters=parameters or {"series": "GDP"},
        failure_type=failure if status == "failed" else None,
    )
    write_manifest(store.root / "runs" / f"{run.run_id}.json", run)
    return run


def test_missing_store_is_not_initialized(tmp_path):
    with pytest.raises(ValueError, match="existing store"):
        build_operations_health(tmp_path / "typo")
    assert not (tmp_path / "typo").exists()


def test_empty_history_is_not_a_pass(store):
    report = build_operations_health(store.root)
    assert report.status == "no_history"
    assert report.python_version and report.market_freshness_assessed is False


def test_overlap_changes_do_not_hide_streak_and_success_resets_it(store):
    trace(store, 1, "failed", {"series": "GDP", "start": "2020-01-01"})
    trace(store, 2, "failed", {"series": "GDP", "start": "2025-01-01"})
    report = build_operations_health(store.root)
    assert report.status == "attention"
    assert [row.consecutive_failures for row in report.runs] == [1, 2]
    assert [row.is_latest for row in report.runs] == [False, True]
    assert len({row.identity_sha256 for row in report.runs}) == 1
    trace(store, 3, "succeeded")
    report = build_operations_health(store.root)
    assert report.status == "clear" and report.runs[-1].consecutive_failures == 0


def test_distinct_series_and_unfinished_runs_remain_visible(store):
    trace(store, 1, "running")
    trace(store, 2, "succeeded")
    trace(store, 3, "failed", {"series": "CPIAUCSL"})
    report = build_operations_health(store.root)
    assert report.status == "attention"
    assert report.runs[0].retry_action == "inspect_unfinished"
    assert report.runs[-1].is_latest


def test_exception_text_and_parameters_are_not_exported(store, tmp_path):
    trace(store, 1, "failed", {"series": "GDP", "input_filename": "SECRET"}, "SECRET")
    report = build_operations_health(store.root)
    destination = tmp_path / "out"
    write_operations_health(report, destination)
    content = (destination / "operations-health.json").read_text()
    assert "SECRET" not in content
    assert report.runs[0].failure_category == "unknown"
    assert report.runs[0].failure_reason is None
    assert report.runs[0].quota_status == "not_measured"
    assert report.runs[0].historical_runtime == "not_recorded"
    with pytest.raises(FileExistsError):
        write_operations_health(report, destination)


def test_corrupt_manifest_and_busy_writer_fail_closed(store):
    path = store.root / "runs" / ("a" * 32 + ".json")
    path.parent.mkdir(exist_ok=True)
    path.write_text("{}")
    with pytest.raises(ValueError):
        build_operations_health(store.root)
    path.unlink()
    with store.writer_lock(), pytest.raises(ValueError, match="another writer"):
        build_operations_health(store.root)


def test_wrong_filename_rejected(store):
    run = trace(store, 1, "succeeded")
    (store.root / "runs" / f"{run.run_id}.json").rename(store.root / "runs" / ("b" * 32 + ".json"))
    with pytest.raises(ValueError, match="filename"):
        build_operations_health(store.root)


@pytest.mark.parametrize(
    "reason,expected",
    [
        ("HTTP_429", "check_quota_before_manual_retry"),
        ("HTTP_503", "manual_retry_after_transport_budget"),
        ("CONNECTION_FAILED", "manual_retry_after_transport_budget"),
        ("HTTP_403", "repair_before_retry"),
        ("VALIDATION_FAILED", "repair_before_retry"),
        (None, "inspect_before_retry"),
    ],
)
def test_retry_decisions(reason, expected):
    assert retry_action("failed", reason) == expected


@pytest.mark.parametrize("attempts", [0, -1, 4, True, 1.5, "3"])
def test_invalid_retry_budget_never_calls_network(monkeypatch, attempts):
    monkeypatch.setattr(ingestion, "urlopen", lambda *a, **k: pytest.fail("network"))
    with pytest.raises(ValueError, match="1 to 3"):
        ingestion.fetch_bytes("https://example.test/?key=SECRET", attempts)


@pytest.mark.parametrize("code,calls", [(403, 1), (429, 3), (503, 3)])
def test_transport_budget_and_redaction(monkeypatch, code, calls):
    observed = []
    sleeps = []

    def fail(*args, **kwargs):
        observed.append(1)
        raise HTTPError("https://example.test/?key=SECRET", code, "SECRET", {}, None)

    monkeypatch.setattr(ingestion, "urlopen", fail)
    monkeypatch.setattr(ingestion.time, "sleep", sleeps.append)
    with pytest.raises(ValueError, match=f"HTTP {code}") as error:
        ingestion.fetch_bytes("https://example.test/?key=SECRET")
    assert "SECRET" not in str(error.value)
    assert len(observed) == calls and sleeps == ([1, 2] if calls == 3 else [])


def test_connection_retries_are_bounded(monkeypatch):
    observed = []

    def fail(*args, **kwargs):
        observed.append(1)
        raise URLError("SECRET")

    monkeypatch.setattr(ingestion, "urlopen", fail)
    monkeypatch.setattr(ingestion.time, "sleep", lambda _: None)
    with pytest.raises(ValueError, match="bounded retries"):
        ingestion.fetch_bytes("https://example.test")
    assert len(observed) == 3


def test_cli_is_offline_and_skips_registry(store, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_registry", lambda *a: pytest.fail("registry"))
    args = cli.parser().parse_args(
        ["--store", str(store.root), "operations-health", "--output-dir", str(tmp_path / "out")]
    )
    result = cli.run(args)
    assert result["status"] == "no_history"
    assert json.loads((tmp_path / "out" / "operations-health.json").read_text())["runs"] == []


def test_refresh_partial_and_trace_linkage(store, registry, settings, tmp_path, offline):
    run, folder = refresh_and_report(
        store, registry, settings, RefreshPolicy(), tmp_path / "refresh"
    )
    manifest = folder / "refresh-run.json"
    report = build_operations_health(store.root, manifest)
    assert report.refresh_status == run.status == "partial"
    assert report.status == "attention" and len(report.runs) == 10
    assert report.refresh_sha256
    trace_path = store.root / "runs" / f"{run.steps[0].run_id}.json"
    original = trace_path.read_bytes()
    changed = json.loads(original)
    changed["operation"] = "fetch-fred"
    trace_path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="operation/source"):
        build_operations_health(store.root, manifest)
    trace_path.write_bytes(original)
    data = json.loads(manifest.read_text())
    data["store_root"] = str(tmp_path / "previous-device")
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="relocation"):
        build_operations_health(store.root, manifest)
    relocated = build_operations_health(store.root, manifest, allow_relocated_refresh=True)
    assert relocated.refresh_store_relation == "relocated_explicitly"
    data = json.loads(manifest.read_text())
    data["steps"][0]["inserted_records"] = 0
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="counts"):
        build_operations_health(store.root, manifest, allow_relocated_refresh=True)


def test_output_inside_store_rejected(store):
    args = cli.parser().parse_args(
        [
            "--store",
            str(store.root),
            "operations-health",
            "--output-dir",
            str(store.root / "health"),
        ]
    )
    with pytest.raises(ValueError, match="outside"):
        cli.run(args)


def test_refresh_http_failure_is_safe_and_not_a_quota_claim(
    store, registry, settings, tmp_path, offline, monkeypatch
):
    def denied(*args, **kwargs):
        raise ValueError("provider request failed with HTTP 403")

    monkeypatch.setattr(refresh, "ingest_cftc_gold", denied)
    _, folder = refresh_and_report(store, registry, settings, RefreshPolicy(), tmp_path / "refresh")
    report = build_operations_health(store.root, folder / "refresh-run.json")
    failures = [row for row in report.runs if row.status == "failed"]
    assert len(failures) == 1
    assert failures[0].failure_reason == "HTTP_403"
    assert failures[0].retry_action == "repair_before_retry"
    assert failures[0].quota_status == "not_measured"


def test_missing_fred_credentials_are_classified_without_exception_text():
    assert (
        refresh.safe_failure_reason(
            ValueError("set FRED_API_KEY in the environment before fetching")
        )
        == "MISSING_CREDENTIALS"
    )
    assert (
        refresh.safe_failure_reason(ValueError("set FRED_API_KEY SECRET before fetching"))
        == "VALIDATION_FAILED"
    )


@pytest.mark.parametrize("with_history,expected", [(False, 3), (True, 0)])
def test_health_cli_exit_code(store, tmp_path, capsys, with_history, expected):
    if with_history:
        trace(store, 1, "succeeded")
    assert (
        cli.main(
            ["--store", str(store.root), "operations-health", "--output-dir", str(tmp_path / "out")]
        )
        == expected
    )
    assert '"status"' in capsys.readouterr().out
