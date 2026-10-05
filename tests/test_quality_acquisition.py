import json
from datetime import UTC, datetime, timedelta

import pytest

from gold_intelligence.acquisition import acquire, list_runs
from gold_intelligence.cli import main
from gold_intelligence.models import Observation
from gold_intelligence.quality import QualityPolicy, RequiredStream, assess, load_policy
from gold_intelligence.storage import record_id


def check(store, registry, cutoff, **kwargs):
    return assess(store, registry, cutoff, QualityPolicy(), allow_synthetic=True, **kwargs)


def test_empty_store_cannot_pass_quality(store, registry):
    report = check(store, registry, datetime(2024, 1, 1, tzinfo=UTC))
    assert report.status == "fail"
    assert report.data_mode == "empty"
    assert report.issues[0].code == "NO_ELIGIBLE_DATA"


def test_real_readiness_rejects_demo_by_default(store, registry, make_bar):
    bar = make_bar()
    store.put([bar])
    report = assess(store, registry, bar.provenance.available_at, QualityPolicy())
    assert report.status == "fail"
    assert report.issues[0].code == "SYNTHETIC_INPUT"
    assert check(store, registry, bar.provenance.available_at).status == "pass"


def test_inventory_collapses_revisions_without_counting_them_as_more_history(
    store, registry, make_bar
):
    base = make_bar()
    later = base.provenance.available_at + timedelta(days=1)
    revised = make_bar(close=102, provenance={"available_at": later, "retrieved_at": later})
    store.put([base, revised])
    report = check(store, registry, later)
    stream = report.streams[0]
    assert stream.record_versions == 2
    assert stream.unique_observations == 1
    assert stream.extra_versions == 1
    past = check(store, registry, base.provenance.available_at)
    assert past.eligible_records == 1
    assert past.excluded_by_time == 1


def test_quality_respects_both_time_modes(store, registry, make_bar):
    original = make_bar()
    release = original.provenance.available_at
    bar = make_bar(provenance={"retrieved_at": release + timedelta(days=1)})
    store.put([bar])
    assert check(store, registry, release).eligible_records == 0
    assert check(store, registry, release, mode="source").eligible_records == 1


def test_ambiguous_revision_is_a_failure(store, registry, make_bar):
    store.put([make_bar(), make_bar(close=103)])
    report = check(store, registry, datetime(2024, 1, 2, tzinfo=UTC))
    assert report.status == "fail"
    assert any(i.code == "AMBIGUOUS_REVISION" for i in report.issues)


def test_policy_does_not_sum_distinct_venues_to_satisfy_history(store, registry, make_bar):
    store.put([make_bar(), make_bar(venue="OTHER")])
    policy = QualityPolicy(
        required_streams=(
            RequiredStream(kind="price_bar", instrument="XAUUSD", min_observations=2),
        )
    )
    report = assess(store, registry, datetime(2024, 1, 2, tzinfo=UTC), policy, allow_synthetic=True)
    assert len(report.streams) == 2
    assert any(i.code == "REQUIRED_STREAM_MISSING" for i in report.issues)


def test_missing_value_revision_is_resolved_and_zero_is_not_missing(store, registry, make_bar):
    p = make_bar().provenance
    null = Observation(provenance=p, layer="macro", series_id="TEST", value=None)
    later_p = p.model_copy(
        update={
            "available_at": p.available_at + timedelta(days=1),
            "retrieved_at": p.retrieved_at + timedelta(days=1),
        }
    )
    revision = Observation(provenance=later_p, layer="macro", series_id="TEST", value=0)
    store.put([null, revision])
    before = check(store, registry, p.available_at)
    assert before.streams[0].missing_values == 1
    after = check(store, registry, later_p.available_at)
    assert after.streams[0].missing_values == 0


def test_gap_and_age_are_warnings_not_assertions_of_missing_sessions(store, registry, make_bar):
    store.put([make_bar(), make_bar(10)])
    policy = QualityPolicy(max_age_hours={"price_bar": 24})
    report = assess(
        store, registry, datetime(2024, 1, 20, tzinfo=UTC), policy, allow_synthetic=True
    )
    assert report.status == "warning"
    assert report.streams[0].daily_gap_count == 1
    assert report.streams[0].largest_gap_hours == 240
    assert {i.code for i in report.issues} == {"DAILY_GAP_REVIEW", "STALE_REFERENCE"}


def test_integrity_scan_reports_unknown_kind_and_missing_raw(store, registry, make_bar):
    bar = make_bar()
    store.put([bar])
    (store.root / "raw" / bar.provenance.raw_sha256).unlink()
    store.db.execute("INSERT INTO records VALUES (?, ?, ?)", ("bad", "unknown", "{}"))
    store.db.commit()
    report = check(store, registry, bar.provenance.available_at)
    assert {i.code for i in report.issues} == {"RAW_MISSING", "INVALID_RECORD"}
    assert report.total_records == 2
    assert report.valid_records == 1
    with pytest.raises(ValueError):
        store.audit()


def test_registry_drift_is_visible(store, registry, make_bar):
    bar = make_bar(provenance={"license_id": "unreviewed-new-license"})
    store.put([bar])
    report = check(store, registry, bar.provenance.available_at)
    assert any(i.code == "SOURCE_MISMATCH" for i in report.issues)


def test_success_manifest_traces_deduplicated_records(store, make_bar):
    bar = make_bar()
    first = acquire(store, "import-prices", {"dataset": "test"}, lambda: store.put([bar]))
    second = acquire(store, "import-prices", {"dataset": "test"}, lambda: store.put([bar]))
    runs = list_runs(store.root)
    assert [r["inserted_records"] for r in runs] == [1, 0]
    assert all(r["referenced_records"] == 1 for r in runs)
    manifest = json.loads((store.root / "runs" / (second["run_id"] + ".json")).read_text())
    assert manifest["record_ids"] == [record_id(bar)]
    assert manifest["raw_sha256"] == [bar.provenance.raw_sha256]
    assert first["run_id"] != second["run_id"]


def test_failed_manifest_retains_raw_evidence_without_exception_secrets(store):
    def fail():
        store.put_raw(b"provider response")
        raise ValueError("accidental provider error contains API_KEY=secret")

    with pytest.raises(ValueError):
        acquire(store, "fetch-fred", {"series": "DFII10"}, fail)
    raw_manifest = next((store.root / "runs").glob("*.json")).read_text()
    assert "secret" not in raw_manifest
    manifest = json.loads(raw_manifest)
    assert manifest["status"] == "failed"
    assert manifest["failure_type"] == "ValueError"
    assert len(manifest["raw_sha256"]) == 1
    assert manifest["record_ids"] == []
    assert store._capture is None


def test_manifest_rejects_unknown_parameters_before_running(store):
    with pytest.raises(ValueError, match="credentials"):
        acquire(store, "fetch-fred", {"api_key": "secret"}, lambda: pytest.fail("executed"))


def test_quality_cli_writes_failure_report_and_returns_distinct_exit(tmp_path, capsys):
    output = tmp_path / "quality.json"
    result = main(
        [
            "--store",
            str(tmp_path / "store"),
            "quality",
            "--as-of",
            "2024-01-01T00:00:00Z",
            "--output",
            str(output),
        ]
    )
    assert result == 3
    assert json.loads(output.read_text())["status"] == "fail"
    assert '"status": "fail"' in capsys.readouterr().out


def test_cli_ingestion_creates_failed_run_for_bad_file(tmp_path, capsys):
    root = tmp_path / "store"
    assert (
        main(
            [
                "--store",
                str(root),
                "import-prices",
                str(tmp_path / "missing.csv"),
                "--source",
                "user_price_csv",
                "--instrument",
                "XAUUSD",
                "--venue",
                "TEST",
                "--dataset",
                "test",
            ]
        )
        == 2
    )
    assert list_runs(root)[0]["status"] == "failed"
    capsys.readouterr()


def test_default_policy_parses_explicit_series_keys():
    from pathlib import Path

    policy = load_policy(Path("config/quality_policy.yaml"))
    assert policy.max_age_hours["series:DFII10"] == 168
