import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gold_intelligence.acquisition import acquire, list_runs
from gold_intelligence.brief import build_brief, render_persian
from gold_intelligence.cli import main
from gold_intelligence.macro import load_plan
from gold_intelligence.quality import QualityPolicy, assess
from gold_intelligence.release_calendar import (
    ReleaseEvidence,
    calendar_context,
    import_evidence,
    normalize_evidence,
)


def moment(text):
    return datetime.fromisoformat(text)


def bundle(captured="2024-01-01T00:00:00Z", announced="2024-01-15T08:30:00-05:00", **changes):
    # Invented schedule fixtures, not claims about actual BLS release dates.
    payload = {
        "source_url": "https://www.bls.gov/schedule/news_release/cpi.htm",
        "captured_at": captured,
        "timing_basis": "schedule",
        "timezone_evidence": "Invented fixture: Eastern Time",
        "entries": [
            {
                "series_id": "CPIAUCSL",
                "reference_period": "2023-12",
                "announced_at": announced,
                "evidence_note": "Invented test row",
            }
        ],
    }
    payload.update(changes)
    return payload


def insert(store, registry, payload, retrieved="2024-01-02T00:00:00Z"):
    content = json.dumps(payload).encode()
    evidence = ReleaseEvidence.model_validate(payload)
    records = normalize_evidence(
        evidence, registry.get("bls"), store.put_raw(content), moment(retrieved)
    )
    store.put(records)
    return records


def test_schedule_never_creates_actual_values_or_historical_availability(store, registry):
    r = insert(store, registry, bundle())[0]
    assert r.actual_release_at is r.actual is r.consensus is r.previous is None
    assert r.provenance.available_at == moment("2024-01-02T00:00:00Z")
    assert store.read("calendar_release", moment("2024-01-01T12:00:00Z"), "source") == []
    assert store.read("observation") == []
    assert calendar_context(store, moment("2024-01-03T00:00:00Z")).eligible_events == 1


def test_new_york_dst_offsets_and_tehran_conversion(store, registry):
    data = bundle()
    data["entries"] = [
        {
            "series_id": "CPIAUCSL",
            "reference_period": period,
            "announced_at": stamp,
            "evidence_note": "Invented summer/winter fixture",
        }
        for period, stamp in [
            ("2024-02", "2024-03-11T08:30:00-04:00"),
            ("2024-10", "2024-11-08T08:30:00-05:00"),
        ]
    ]
    insert(store, registry, data)
    rows = calendar_context(store, moment("2024-01-03T00:00:00Z"), 366).upcoming
    assert [r.announced_at.hour for r in rows] == [12, 13]
    assert [r.tehran_time.hour for r in rows] == [16, 17]
    assert [r.tehran_time.minute for r in rows] == [0, 0]


@pytest.mark.parametrize(
    "changes",
    [
        {"source_url": "https://example.com/schedule/news_release/cpi.htm"},
        {"source_url": "http://www.bls.gov/schedule/news_release/cpi.htm"},
        {"source_url": "https://www.bls.gov/schedule/news_release/empsit.htm"},
        {"source_url": "https://www.bls.gov/schedule/news_release/cpi.htm?key=test"},
        {"source_url": "https://www.bls.gov:444/schedule/news_release/cpi.htm"},
        {"captured_at": "2024-01-01T00:00:00"},
    ],
)
def test_invalid_or_wrong_source_and_naive_capture_fail(changes):
    with pytest.raises(ValueError):
        ReleaseEvidence.model_validate(bundle(**changes))


@pytest.mark.parametrize(
    "announced", ["2024-01-15T08:30:00-04:00", "2024-03-11T08:30:00-05:00", "2024-01-15T08:30:00"]
)
def test_wrong_seasonal_offset_or_naive_announcement_fails(announced):
    with pytest.raises(ValueError):
        ReleaseEvidence.model_validate(bundle(announced=announced))


def test_capture_cannot_follow_ingestion_and_duplicate_periods_fail(store, registry):
    with pytest.raises(ValueError, match="capture"):
        insert(store, registry, bundle(captured="2024-01-03T00:00:00Z"))
    data = bundle()
    data["entries"] *= 2
    with pytest.raises(ValueError, match="duplicate"):
        insert(store, registry, data)
    assert store.read("calendar_release") == []


def test_archive_embargo_is_not_measured_delivery(store, registry):
    data = bundle(
        announced="2020-03-11T08:30:00-04:00",
        timing_basis="archive_header",
        source_url="https://www.bls.gov/news.release/archives/cpi_03112020.htm",
    )
    data["entries"][0]["reference_period"] = "2020-02"
    r = insert(store, registry, data)[0]
    assert r.actual_release_at is None
    assert r.provenance.availability_basis == "retrieval_time"
    assert store.read("calendar_release", moment("2020-03-12T00:00:00Z"), "source") == []


def test_reschedule_outside_horizon_does_not_resurrect_old_time(store, registry):
    old = bundle()
    insert(store, registry, old)
    insert(
        store,
        registry,
        bundle(captured="2024-01-02T00:00:00Z", announced="2024-03-15T08:30:00-04:00"),
        retrieved="2024-01-03T00:00:00Z",
    )
    insert(store, registry, old, retrieved="2024-01-04T00:00:00Z")
    context = calendar_context(store, moment("2024-01-05T00:00:00Z"), 30)
    assert context.eligible_events == 1 and not context.upcoming
    assert context.status == "no_upcoming_evidence"


def test_same_capture_conflict_is_not_resolved_by_import_order(store, registry):
    insert(store, registry, bundle())
    insert(
        store,
        registry,
        bundle(announced="2024-01-16T08:30:00-05:00"),
        retrieved="2024-01-03T00:00:00Z",
    )
    with pytest.raises(ValueError, match="conflicting"):
        calendar_context(store, moment("2024-01-04T00:00:00Z"))


def test_old_capture_is_stale_even_if_just_imported(store, registry):
    insert(store, registry, bundle(), retrieved="2024-01-09T00:00:00Z")
    context = calendar_context(store, moment("2024-01-10T00:00:00Z"))
    assert context.status == "stale_evidence" and context.upcoming[0].stale_evidence


def test_calendar_does_not_inherit_macro_measurement_age_threshold(store, registry):
    insert(store, registry, bundle())
    report = assess(
        store,
        registry,
        moment("2024-01-10T00:00:00Z"),
        QualityPolicy(max_age_hours={"series:CPIAUCSL": 24}),
    )
    assert report.streams[0].freshness_limit_hours is None
    assert all(i.code != "STALE_REFERENCE" for i in report.issues)


def test_calendar_reconciles_source_evidence_and_hash(store, registry):
    r = insert(store, registry, bundle())[0]
    store.put([r.model_copy(update={"scheduled_at": moment("2024-01-16T13:30:00Z")})])
    with pytest.raises(ValueError, match="differs from"):
        calendar_context(store, moment("2024-01-03T00:00:00Z"))
    (store.root / "raw" / r.provenance.raw_sha256).write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        calendar_context(store, moment("2024-01-03T00:00:00Z"))


def test_attested_import_traces_evidence_and_exact_reimport_is_idempotent(
    store, registry, tmp_path
):
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(bundle()), encoding="utf-8")
    with pytest.raises(ValueError, match="review"):
        import_evidence(store, path, registry.get("bls"))

    def execute():
        return import_evidence(
            store,
            path,
            registry.get("bls"),
            reviewed=True,
            retrieved_at=moment("2024-01-02T00:00:00Z"),
        )

    result = acquire(store, "import-release-evidence", {"reviewed": True}, execute)
    assert result["inserted"] == 1 and execute() == 0
    assert list_runs(store.root)[0]["raw_blobs"] == 1


def test_brief_exposes_missing_macro_and_announced_times_with_record_ids(store, registry):
    records = insert(store, registry, bundle())
    brief = build_brief(
        store,
        registry,
        load_plan(Path("config/macro_core.yaml")),
        QualityPolicy(),
        moment("2024-01-03T00:00:00Z"),
    )
    assert brief.macro.status == "incomplete" and brief.daily_backtest_ready is False
    text = render_persian(brief)
    assert "فاقد دادهٔ مجاز" in text
    assert "2024-01-15 17:00 +0330" in text
    assert "CPIAUCSL / 2023-12" in text
    assert str(records[0].provenance.source_url) in text
    assert brief.calendar.upcoming[0].record_id in text


def test_brief_cli_writes_matching_local_artifacts_and_exits_three_on_quality_fail(tmp_path):
    output = tmp_path / "report"
    result = main(
        [
            "--store",
            str(tmp_path / "empty"),
            "research-brief",
            "--as-of",
            datetime.now(UTC).isoformat(),
            "--output-dir",
            str(output),
        ]
    )
    assert result == 3
    payload = json.loads((output / "research-brief.json").read_text(encoding="utf-8"))
    assert payload["quality"]["status"] == "fail"
    assert payload["calendar"]["status"] == "no_upcoming_evidence"
    assert "وضعیت کنترل کیفیت: خطا" in (output / "research-brief.fa.md").read_text(encoding="utf-8")
