"""Offline orchestration tests; all provider-shaped numbers are invented fixtures."""

import json
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import validate
from test_alpha_vantage import response
from test_cftc_positioning import provider
from test_macro import observation
from test_research_report import settings as settings
from test_world_bank import workbook

from gold_intelligence import acquisition, cli, refresh
from gold_intelligence.acquisition import AcquisitionRun, acquire
from gold_intelligence.alpha_vantage import parse_gold_history
from gold_intelligence.cftc import FIRST_DATE, ingest_cftc_gold
from gold_intelligence.macro import load_plan
from gold_intelligence.quality import QualityPolicy
from gold_intelligence.refresh import (
    FRED_START,
    RefreshPolicy,
    RefreshRun,
    completed_status,
    fred_overlap_start,
    plan_steps,
    refresh_and_report,
    refresh_lock,
    report_freshness,
    safe_failure_reason,
)
from gold_intelligence.research_report import build_research_report, load_verified_report
from gold_intelligence.storage import record_id
from gold_intelligence.world_bank import parse_monthly_gold


@pytest.fixture
def offline(monkeypatch):
    calls = []

    def alpha(store, source):
        calls.append("alpha_vantage_gold")
        content = response()
        return store.put(
            parse_gold_history(content, source, store.put_raw(content), datetime.now(UTC))
        )

    def monthly(store, source):
        calls.append("world_bank_pink_sheet")
        content = workbook()
        return store.put(
            parse_monthly_gold(content, source, store.put_raw(content), datetime.now(UTC))
        )

    def fred(store, source, spec, start, end, vintage, fetch):
        calls.append(f"fred:{spec.series_id}")
        assert vintage is None and start <= end <= datetime.now(UTC).date()
        registry = SimpleNamespace(get=lambda key: source)
        row = observation(store, registry, series=spec.series_id, unit=spec.unit)
        return store.put([row])

    def cot(store, source, start, end):
        calls.append("cftc_disaggregated")
        fetch, _ = provider()
        return ingest_cftc_gold(store, source, start, end, fetch)

    monkeypatch.setattr(refresh, "ingest_alpha_gold", alpha)
    monkeypatch.setattr(refresh, "ingest_monthly_gold", monthly)
    monkeypatch.setattr(refresh, "fetch_reviewed_series", fred)
    monkeypatch.setattr(refresh, "ingest_cftc_gold", cot)
    return calls


def saved_run(root):
    path = next(root.glob("refresh-*/refresh-run.json"))
    return RefreshRun.model_validate_json(path.read_bytes()), path.parent


def test_all_adapters_and_traces_reach_one_verified_report(
    store, registry, settings, tmp_path, offline
):
    run, folder = refresh_and_report(store, registry, settings, RefreshPolicy(), tmp_path / "out")
    assert offline == [s.key for s in run.steps]
    assert len(offline) == 10 and all(s.status == "succeeded" for s in run.steps)
    assert run.status == "partial"  # Old fixture reference periods remain old after today's fetch.
    assert run.report.status == "succeeded" and run.report.research_status == "partial"
    assert any(f.status == "stale" for f in run.report.freshness)
    assert saved_run(tmp_path / "out")[0] == run
    assert run.started_at <= run.report.as_of <= run.finished_at
    report, manifest, _ = load_verified_report(folder / run.report.bundle)
    assert len(manifest.files) == 13
    assert report.as_of == run.report.as_of and report.fingerprint == run.report.fingerprint
    for step in run.steps:
        trace = AcquisitionRun.model_validate_json(
            (store.root / "runs" / f"{step.run_id}.json").read_bytes()
        )
        assert trace.status == "succeeded" and trace.inserted_records == step.inserted_records
        assert set(trace.record_ids) <= {identifier for identifier, _, _ in store.entries()}
    validate(
        run.model_dump(mode="json"),
        json.loads(Path("schemas/refresh_run.schema.json").read_bytes()),
    )
    prose = (folder / "refresh.fa.md").read_text(encoding="utf-8")
    assert "قدیمی" in prose and "BLS" in prose and "خودکار دریافت نمی‌شوند" in prose


@pytest.mark.parametrize("failed_key", ["alpha_vantage_gold", "fred:DGS10", "cftc_disaggregated"])
def test_one_failure_keeps_other_sources_and_redacts_error(
    store, registry, settings, tmp_path, offline, monkeypatch, failed_key
):
    execute = refresh.execute_step

    def dispatch(store, registry, settings, step):
        if step.key == failed_key:

            def fail():
                raise ValueError("https://example.invalid/?api_key=PRIVATE-TEST-KEY")

            return acquire(store, "fetch-alpha-gold", {}, fail, run_id=step.run_id)
        return execute(store, registry, settings, step)

    monkeypatch.setattr(refresh, "execute_step", dispatch)
    run, folder = refresh_and_report(store, registry, settings, RefreshPolicy(), tmp_path / "out")
    assert run.status == "partial" and run.report.status == "succeeded"
    assert sum(s.status == "succeeded" for s in run.steps) == 9
    bad = next(s for s in run.steps if s.key == failed_key)
    assert bad.acquisition_status == "failed" and bad.failure_type == "ValueError"
    assert bad.inserted_records == 0
    for file in [*folder.rglob("*.json"), *folder.rglob("*.md"), *store.root.glob("runs/*.json")]:
        assert b"PRIVATE-TEST-KEY" not in file.read_bytes()


def test_prior_data_can_remain_current_while_its_refresh_failed(
    store, registry, settings, tmp_path, offline, monkeypatch
):
    now = datetime.now(UTC)
    content = response([{"date": str(now.date()), "price": "101.25"}])
    rows = parse_gold_history(
        content, registry.get("alpha_vantage_gold"), store.put_raw(content), now
    )
    store.put(rows)
    settings = settings.model_copy(
        update={"quality_policy": QualityPolicy(max_age_hours={"price_close": 96})}
    )

    def fail(*args):
        raise OSError("sensitive vendor error")

    monkeypatch.setattr(refresh, "ingest_alpha_gold", fail)
    run, folder = refresh_and_report(store, registry, settings, RefreshPolicy(), tmp_path / "out")
    assert run.steps[0].status == "failed"
    assert (
        next(f for f in run.report.freshness if f.key == "alpha_vantage_gold").status == "current"
    )
    report, _, _ = load_verified_report(folder / run.report.bundle)
    price = next(s for s in report.quality.streams if s.identity["kind"] == "price_close")
    assert (
        price.unique_observations == 1 and price.last_observed_at == rows[0].provenance.observed_at
    )
    assert record_id(rows[0]) in {record_id(r) for r in store.read("price_close", run.report.as_of)}
    assert run.status == "partial"


@pytest.mark.parametrize("exception", [KeyboardInterrupt, SystemExit])
def test_interruption_checkpoints_then_stops_and_releases_lock(
    store, registry, settings, tmp_path, offline, monkeypatch, exception
):
    def stop(*args):
        raise exception("private")

    monkeypatch.setattr(refresh, "ingest_monthly_gold", stop)
    with pytest.raises(exception):
        refresh_and_report(store, registry, settings, RefreshPolicy(), tmp_path / "out")
    run, folder = saved_run(tmp_path / "out")
    assert run.status == "interrupted" and run.report.status == "skipped"
    assert [s.status for s in run.steps][:2] == ["succeeded", "interrupted"]
    assert all(s.status == "pending" for s in run.steps[2:])
    assert run.steps[1].acquisition_status == "failed"
    assert offline == ["alpha_vantage_gold"]
    assert not list(folder.glob("reports/*"))
    with refresh_lock(store.root):
        pass


def test_running_checkpoint_contains_previous_results_before_next_source(
    store, registry, settings, tmp_path, offline, monkeypatch
):
    execute = refresh.execute_step
    seen = []

    def observe(store, registry, settings, step):
        run, _ = saved_run(tmp_path / "out")
        assert run.status == "running" and run.finished_at is None
        assert next(s for s in run.steps if s.key == step.key).status == "running"
        assert all(s.status == "succeeded" for s in run.steps if s.key in seen)
        seen.append(step.key)
        return execute(store, registry, settings, step)

    monkeypatch.setattr(refresh, "execute_step", observe)
    refresh_and_report(store, registry, settings, RefreshPolicy(), tmp_path / "out")
    assert len(seen) == 10


@pytest.mark.parametrize(
    "phase", ["build_research_report", "write_research_report", "verify_research_bundle"]
)
def test_report_failure_is_distinct_and_never_reuses_previous_output(
    store, registry, settings, tmp_path, offline, monkeypatch, phase
):
    out = tmp_path / "out"
    out.mkdir()
    old = out / "research-report.fa.md"
    old.write_text("previous notes", encoding="utf-8")

    def fail(*args):
        raise OSError("private report failure")

    monkeypatch.setattr(refresh, phase, fail)
    run, folder = refresh_and_report(store, registry, settings, RefreshPolicy(), out)
    assert all(s.status == "succeeded" for s in run.steps)
    assert run.status == "failed" and run.report.failure_type == "OSError"
    assert run.report.bundle is None and not run.report.freshness
    assert old.read_text() == "previous notes"
    assert "private" not in (folder / "refresh-run.json").read_text()


def test_missing_acquisition_manifest_cannot_be_success(
    store, registry, settings, tmp_path, offline, monkeypatch
):
    monkeypatch.setattr(refresh, "execute_step", lambda *args: {"inserted": 0})
    run, _ = refresh_and_report(store, registry, settings, RefreshPolicy(), tmp_path / "out")
    assert all(s.status == "failed" and s.acquisition_status == "unavailable" for s in run.steps)
    assert all(s.inserted_records is None for s in run.steps)
    assert run.report.status == "succeeded" and run.status == "partial"


def test_bootstrap_gap_overlap_and_full_history_are_explicit(store, registry, settings):
    start = datetime(2024, 8, 1, tzinfo=UTC)
    cold = plan_steps(store, settings, RefreshPolicy(), start)
    assert all(s.start == FRED_START for s in cold if s.key.startswith("fred:"))
    assert cold[-1].start == FIRST_DATE
    store.put([observation(store, registry, observed=10)])
    warm = plan_steps(store, settings, RefreshPolicy(), start)
    dff = next(s for s in warm if s.key == "fred:DFF")
    assert dff.start == date(2024, 1, 10) - timedelta(days=120)
    assert dff.end == start.date()  # Includes the months-long gap, not just the last 120 days.
    full = plan_steps(store, settings, RefreshPolicy(full_history=True), start)
    assert next(s for s in full if s.key == "fred:DFF").start == FRED_START
    assert full[-1].start == FIRST_DATE


@pytest.mark.parametrize(
    ("latest", "days", "frequency", "expected"),
    [
        (date(2026, 8, 1), 120, "M", date(2026, 4, 1)),
        (date(2026, 9, 1), 120, "M", date(2026, 5, 1)),
        (date(2026, 7, 1), 120, "Q", date(2026, 1, 1)),
        (date(2026, 9, 29), 90, "W", date(2026, 6, 30)),
        (date(2026, 10, 2), 120, "D", date(2026, 6, 4)),
    ],
)
def test_fred_overlap_aligns_complete_periods_without_relaxing_parser(
    latest, days, frequency, expected
):
    assert fred_overlap_start(latest, date(2026, 10, 6), days, frequency, False) == expected
    assert fred_overlap_start(latest, date(2026, 10, 6), days, frequency, True) == FRED_START


@pytest.mark.parametrize(
    ("exception", "reason"),
    [
        (ValueError("provider request failed with HTTP 403"), "HTTP_403"),
        (ValueError("provider request failed with HTTP 429"), "HTTP_429"),
        (ValueError("set FRED_API_KEY before fetching"), "MISSING_CREDENTIALS"),
        (ValueError("set ALPHAVANTAGE_API_KEY before fetching"), "MISSING_CREDENTIALS"),
        (ValueError("provider connection failed after bounded retries"), "CONNECTION_FAILED"),
        (ValueError("provider request failed with HTTP 403 api_key=private"), "VALIDATION_FAILED"),
        (OSError("private"), "STORAGE_ERROR"),
        (RuntimeError("private"), "UNEXPECTED_ERROR"),
        (KeyboardInterrupt(), "INTERRUPTED"),
    ],
)
def test_failure_reason_is_allowlisted_and_never_contains_provider_text(exception, reason):
    assert safe_failure_reason(exception) == reason


def test_known_world_bank_method_break_uses_latest_period_but_keeps_both_streams(
    store, registry, settings
):
    cutoff = datetime(2025, 7, 1, tzinfo=UTC)
    content = workbook()
    store.put(
        parse_monthly_gold(
            content, registry.get("world_bank_pink_sheet"), store.put_raw(content), cutoff
        )
    )
    settings = settings.model_copy(
        update={"quality_policy": QualityPolicy(max_age_hours={"series:WB_GOLD_MONTHLY": 1800})}
    )
    report = build_research_report(store, registry, settings, cutoff)
    row = next(r for r in report_freshness(report) if r.key == "world_bank_pink_sheet")
    assert row.status == "current" and row.reference_at == datetime(2025, 6, 1, tzinfo=UTC)
    assert row.age_days == 30
    streams = [s for s in report.quality.streams if s.identity["source_id"] == row.key]
    assert len(streams) == 2  # Method break remains part of research evidence.
    malformed = streams[0].model_copy(
        update={"identity": {**streams[0].identity, "currency": "EUR"}}
    )
    view = SimpleNamespace(
        quality=SimpleNamespace(streams=[malformed, streams[1]]),
        macro=report.macro,
        positioning=report.positioning,
    )
    row = next(r for r in report_freshness(view) if r.key == "world_bank_pink_sheet")
    assert row.status == "unchecked" and row.reference_at is None


@pytest.mark.parametrize("kind", ["vintage", "future", "unit", "dimension"])
def test_ineligible_series_do_not_suppress_bootstrap(store, registry, settings, kind):
    options = {
        "vintage": {"vintage": date(2024, 1, 2)},
        "future": {"retrieved": 20},
        "unit": {"unit": "wrong"},
        "dimension": {"dimensions": {"frequency": "different"}},
    }[kind]
    store.put([observation(store, registry, **options)])
    steps = plan_steps(store, settings, RefreshPolicy(), datetime(2024, 1, 10, tzinfo=UTC))
    assert next(s for s in steps if s.key == "fred:DFF").start == FRED_START


def test_lock_blocks_other_process_and_recovers_after_owner_exits(store):
    script = "from pathlib import Path; from gold_intelligence.refresh import refresh_lock; "
    script += "ctx = refresh_lock(Path(__import__('sys').argv[1])); ctx.__enter__(); print('owned')"
    with refresh_lock(store.root):
        result = subprocess.run(
            [sys.executable, "-c", script, str(store.root)], capture_output=True, text=True
        )
        assert result.returncode != 0 and "another refresh owns" in result.stderr
    result = subprocess.run(
        [sys.executable, "-c", script, str(store.root)], capture_output=True, text=True
    )
    assert result.returncode == 0 and "owned" in result.stdout
    with refresh_lock(store.root):
        pass


def test_invalid_policy_fails_before_any_acquisition(store, registry, settings, tmp_path, offline):
    with pytest.raises(ValueError):
        refresh_and_report(
            store,
            registry,
            settings,
            RefreshPolicy().model_copy(update={"cot_overlap_days": 0}),
            tmp_path / "out",
        )
    assert not offline and not (tmp_path / "out").exists()


def test_repeated_execution_preserves_previous_bundle(store, registry, settings, tmp_path, offline):
    before, folder = refresh_and_report(
        store, registry, settings, RefreshPolicy(), tmp_path / "out"
    )
    saved = (folder / "refresh-run.json").read_bytes()
    after, other = refresh_and_report(store, registry, settings, RefreshPolicy(), tmp_path / "out")
    assert folder != other and before.run_id != after.run_id
    assert (folder / "refresh-run.json").read_bytes() == saved
    assert (
        load_verified_report(folder / before.report.bundle)[0].fingerprint
        == before.report.fingerprint
    )


def test_duplicate_acquisition_id_does_not_overwrite_existing_trace(store, monkeypatch):
    identifier = "a" * 32
    writer = acquisition.write_manifest

    def observe(path, run):
        if path.exists():
            AcquisitionRun.model_validate_json(path.read_bytes())
        writer(path, run)

    monkeypatch.setattr(acquisition, "write_manifest", observe)
    result = acquire(store, "fetch-alpha-gold", {}, lambda: 0, run_id=identifier)
    saved = Path(result["manifest"]).read_bytes()
    with pytest.raises(FileExistsError):
        acquire(
            store,
            "fetch-alpha-gold",
            {},
            lambda: pytest.fail("must not execute"),
            run_id=identifier,
        )
    assert Path(result["manifest"]).read_bytes() == saved
    with pytest.raises(ValueError):
        acquire(store, "fetch-alpha-gold", {}, lambda: 0, run_id="../escape")


@pytest.mark.parametrize("kind", ["stale", "missing", "missing_value", "unchecked", "calendar"])
def test_completed_downloads_do_not_override_freshness(kind):
    steps = [SimpleNamespace(status="succeeded")]
    report = SimpleNamespace(
        status="succeeded",
        research_status="with_limits",
        freshness=[SimpleNamespace(status="current")],
        calendar_status="scheduled_events",
    )
    assert completed_status(steps, report) == "succeeded"
    if kind == "calendar":
        report.calendar_status = "stale_evidence"
    else:
        report.freshness[0].status = kind
    assert completed_status(steps, report) == "partial"


def test_latest_null_and_missing_threshold_stay_explicit(store, registry, settings):
    store.put(
        [
            observation(store, registry, value=10),
            observation(store, registry, observed=3, value=None),
        ]
    )
    now = datetime.now(UTC)
    content = response()
    store.put(
        parse_gold_history(content, registry.get("alpha_vantage_gold"), store.put_raw(content), now)
    )
    report = build_research_report(store, registry, settings, now)
    freshness = {r.key: r for r in report_freshness(report)}
    assert freshness["alpha_vantage_gold"].status == "unchecked"
    assert freshness["fred:DFF"].status == "missing_value"
    assert freshness["fred:DGS10"].status == "missing"


def test_cli_partial_result_is_schema_backed_and_needs_no_explicit_cutoff(
    tmp_path, offline, capsys
):
    assert (
        cli.main(
            [
                "--store",
                str(tmp_path / "store"),
                "refresh-report",
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )
        == 3
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "partial" and result["report_status"] == "succeeded"
    assert len(result["sources"]) == len(load_plan(Path("config/macro_core.yaml")).series) + 3
    assert Path(result["report"]).is_file() and Path(result["summary"]).is_file()
    assert not result["daily_backtest_ready"]


def test_corrupt_raw_blocks_report_after_downloads(
    store, registry, settings, tmp_path, offline, monkeypatch
):
    original = refresh.ingest_alpha_gold

    def corrupt(store, source):
        result = original(store, source)
        row = store.read("price_close")[0]
        (store.root / "raw" / row.provenance.raw_sha256).write_bytes(b"damaged")
        return result

    monkeypatch.setattr(refresh, "ingest_alpha_gold", corrupt)
    run, _ = refresh_and_report(store, registry, settings, RefreshPolicy(), tmp_path / "out")
    assert run.steps[0].status == "succeeded"  # Acquisition alone is not report certification.
    assert run.status == "failed" and run.report.status == "failed"


@pytest.mark.parametrize("damage", ["status", "missing_source", "duplicate_id", "clock", "manual"])
def test_saved_summary_rejects_inconsistent_state(
    store, registry, settings, tmp_path, offline, damage
):
    run, _ = refresh_and_report(store, registry, settings, RefreshPolicy(), tmp_path / "out")
    data = run.model_dump(mode="json")
    if damage == "status":
        data["status"] = "succeeded"
    elif damage == "missing_source":
        data["steps"].pop()
    elif damage == "duplicate_id":
        data["steps"][1]["run_id"] = data["steps"][0]["run_id"]
    elif damage == "clock":
        data["report"]["as_of"] = "2000-01-01T00:00:00Z"
    else:
        data["manual_inputs"] = []
    with pytest.raises(ValueError):
        RefreshRun.model_validate(data)
