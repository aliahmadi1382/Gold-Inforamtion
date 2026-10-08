import hashlib
import json
import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from jsonschema import validate
from test_release_calendar import bundle as calendar_bundle
from test_release_calendar import insert as insert_calendar
from test_release_values import fred
from test_revision_ledger import add, document, vintages

from gold_intelligence import research_report as module
from gold_intelligence.cli import main
from gold_intelligence.macro import load_plan
from gold_intelligence.monthly_research import MonthlyResearchPlan
from gold_intelligence.quality import QualityPolicy
from gold_intelligence.research_report import (
    FILES,
    PARTS,
    ReportManifest,
    ReportSettings,
    ResearchReport,
    build_research_report,
    render_research_report,
    verify_research_bundle,
    write_research_report,
)
from gold_intelligence.revision_ledger import RevisionPlan
from gold_intelligence.storage import Store

ASOF = datetime(2024, 4, 16, tzinfo=UTC)


@pytest.mark.parametrize("damage", ["bytes", "missing", "binding"])
def test_runtime_receipt_is_checked(store, registry, settings, tmp_path, damage):
    from gold_intelligence.runtime_evidence import RuntimeManifest, load_runtime

    report = build_research_report(store, registry, settings, ASOF)
    directory = write_research_report(report, tmp_path)
    content = (directory / "research-report.json").read_bytes()
    runtime = load_runtime(directory, report, content)
    assert runtime.scope == "bundle_writer"
    assert runtime.dependencies["pydantic"]
    assert report.fingerprint == runtime.report_fingerprint
    path = directory / "runtime.json"
    if damage == "bytes":
        path.write_bytes(path.read_bytes() + b" ")
    elif damage == "missing":
        path.unlink()
    else:
        data = json.loads(path.read_bytes())
        data["report_sha256"] = "0" * 64
        encoded = json.dumps(data).encode()
        path.write_bytes(encoded)
        manifest = RuntimeManifest(
            runtime_sha256=hashlib.sha256(encoded).hexdigest(), runtime_bytes=len(encoded)
        )
        (directory / "runtime-manifest.json").write_text(manifest.model_dump_json())
    with pytest.raises(ValueError):
        verify_research_bundle(directory)


def test_legacy_bundle_without_runtime_still_verifies(store, registry, settings, tmp_path):
    from gold_intelligence.runtime_evidence import load_runtime

    report = build_research_report(store, registry, settings, ASOF)
    directory = write_research_report(report, tmp_path)
    (directory / "runtime.json").unlink()
    (directory / "runtime-manifest.json").unlink()
    assert verify_research_bundle(directory)["fingerprint"] == report.fingerprint
    assert (
        load_runtime(directory, report, (directory / "research-report.json").read_bytes()) is None
    )


@pytest.fixture
def settings():
    return ReportSettings(
        macro_plan=load_plan(Path("config/macro_core.yaml")),
        quality_policy=QualityPolicy(),
        monthly_plan=MonthlyResearchPlan(
            start_month="2024-02-01", minimum_pairs=3, rolling_months=3
        ),
        revision_plan=RevisionPlan(
            declared_at="2024-04-01T00:00:00Z",
            start_period="2024-01",
            end_period="2024-01",
            metrics=["cpi_all_items_sa_mom"],
            selection_reason="Invented test scope",
        ),
    )


def test_empty_store_produces_honest_partial_bundle(store, registry, settings, tmp_path):
    report = build_research_report(store, registry, settings, ASOF)
    assert report.status == "partial"
    assert all(s.status == "missing" for s in report.sections)
    assert all(getattr(report, name).as_of == ASOF for name in PARTS)
    assert not report.daily_backtest_ready and not report.intraday_replay_ready
    directory = write_research_report(report, tmp_path / "reports")
    assert verify_research_bundle(directory)["files"] == 13
    text = (directory / "research-report.fa.md").read_text(encoding="utf-8")
    assert "به معنی نبود رویداد نیست" in text and "با صفر جایگزین نشده" in text
    for link in re.findall(r"\]\(([^)]+)\)", text):
        if not link.startswith("https://"):
            assert (directory / link).is_file()
    validate(
        json.loads((directory / "research-report.json").read_text(encoding="utf-8")),
        json.loads(Path("schemas/research_report.schema.json").read_text()),
    )
    validate(
        json.loads((directory / "manifest.json").read_text()),
        json.loads(Path("schemas/report_manifest.schema.json").read_text()),
    )


def test_revision_values_and_current_changes_survive_composition(store, registry, settings):
    add(store, registry)
    add(store, registry, document(2, prior=0.3))
    vintages(store, registry, after=100.3)
    fred(
        store,
        registry,
        [("2023-12-01", 100), ("2024-01-01", 100.2), ("2024-02-01", 100.4)],
        vintage=None,
        retrieved=ASOF,
    )
    report = build_research_report(store, registry, settings, ASOF)
    assert report.revisions.status == "complete"
    assert report.revisions.pairs[0].difference_pp == 0.2
    assert report.revisions.changed_display_pairs == 1
    assert report.releases.documents[0].values[0].current_revision.status == "differs_display"
    assert report.macro.entries[-2].value == 100.4
    text = render_research_report(report)
    assert "1 جفت اختلاف در دقت نمایش دارد" in text
    assert "یک ماه ممکن است در چند سند تکرار شود" in text


def test_cutoff_and_timezone_are_shared_and_retrieval_bounded(store, registry, settings):
    fred(store, registry, vintage=None, retrieved=ASOF + timedelta(seconds=1))
    report = build_research_report(store, registry, settings, ASOF)
    offset = ASOF.astimezone(timezone(timedelta(hours=3, minutes=30)))
    other = build_research_report(store, registry, settings, offset)
    assert report.fingerprint == other.fingerprint
    assert all(e.record_id is None for e in report.macro.entries)
    assert all(not r.record_ids for r in report.monthly.levels)
    assert report.quality.excluded_by_time == 2


def test_build_clocks_do_not_change_fingerprint(store, registry, settings):
    report = build_research_report(store, registry, settings, ASOF)
    data = report.model_dump(mode="json")
    for key in ("monthly", "releases", "revisions"):
        data[key]["generated_at"] = "2026-01-01T00:00:00Z"
    data["generated_at"] = "2026-01-01T00:00:00Z"
    assert ResearchReport.model_validate(data).fingerprint == report.fingerprint
    changed = settings.model_copy(update={"calendar_horizon_days": 10})
    assert report.fingerprint != build_research_report(store, registry, changed, ASOF).fingerprint


@pytest.mark.parametrize("part", PARTS)
def test_mixed_cutoffs_are_rejected(store, registry, settings, part):
    data = build_research_report(store, registry, settings, ASOF).model_dump(mode="json")
    data[part]["as_of"] = "2024-04-15T00:00:00Z"
    with pytest.raises(ValueError, match="share exactly one cutoff"):
        ResearchReport.model_validate(data)


@pytest.mark.parametrize("case", ["version", "policy", "plan", "mode", "summary", "fingerprint"])
def test_incoherent_or_modified_report_is_rejected(store, registry, settings, case):
    data = build_research_report(store, registry, settings, ASOF).model_dump(mode="json")
    if case == "version":
        data["monthly"]["software_version"] = "other"
    elif case == "policy":
        data["quality"]["policy_sha256"] = "0" * 64
    elif case == "plan":
        data["calendar"]["horizon_days"] = 10
    elif case == "mode":
        data["macro"]["mode"] = "source"
    elif case == "summary":
        data["sections"][0]["status"] = "available"
    else:
        data["registry_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        ResearchReport.model_validate(data)


@pytest.mark.parametrize("damage", ["raw", "normalized", "source"])
def test_integrity_failure_stops_report_and_closes_read_transaction(
    store, registry, settings, damage
):
    rows = fred(store, registry, retrieved=ASOF)
    if damage == "raw":
        (store.root / "raw" / rows[0].provenance.raw_sha256).write_bytes(b"corrupt")
    elif damage == "normalized":
        with store.db:
            store.db.execute("UPDATE records SET payload = '{}' ")
    else:
        row = rows[0]
        store.put(
            [
                row.model_copy(
                    update={"provenance": row.provenance.model_copy(update={"provider": "wrong"})}
                )
            ]
        )
    with pytest.raises(ValueError, match="blocked by data integrity"):
        build_research_report(store, registry, settings, ASOF)
    assert not store.db.in_transaction


def test_synthetic_store_is_not_presented_as_real_research(store, registry, settings, make_bar):
    store.put([make_bar()])
    with pytest.raises(ValueError, match="SYNTHETIC_INPUT"):
        build_research_report(store, registry, settings, ASOF)


def test_component_failure_is_not_replaced_by_old_disk_report(store, registry, settings, tmp_path):
    old = tmp_path / "research-report.fa.md"
    old.write_text("Existing reader notes", encoding="utf-8")
    rows = fred(store, registry, vintage=None, retrieved=ASOF)
    p = rows[0].provenance.model_copy(update={"unit": "wrong_unit"})
    store.put([rows[0].model_copy(update={"provenance": p})])
    with pytest.raises(ValueError, match="incompatible stream"):
        build_research_report(store, registry, settings, ASOF)
    assert old.read_text() == "Existing reader notes" and not store.db.in_transaction


def test_database_snapshot_excludes_concurrent_commit(store, registry, settings, monkeypatch):
    store.db.execute("PRAGMA journal_mode=WAL")
    original = module.macro_context

    def concurrent_write(*args):
        with Store(store.root) as writer:
            fred(writer, registry, vintage=None, retrieved=ASOF)
        return original(*args)

    monkeypatch.setattr(module, "macro_context", concurrent_write)
    report = build_research_report(store, registry, settings, ASOF)
    assert report.quality.eligible_records == 0
    assert all(e.record_id is None for e in report.macro.entries)
    assert all(not row.record_ids for row in report.monthly.levels)
    assert len(store.read("observation")) == 2


def test_existing_transaction_is_not_rolled_back(store, registry, settings):
    store.db.execute("BEGIN")
    with pytest.raises(ValueError, match="outside an existing"):
        build_research_report(store, registry, settings, ASOF)
    assert store.db.in_transaction
    store.db.rollback()


def test_stale_calendar_is_visible_at_shared_cutoff(store, registry, settings):
    insert_calendar(
        store,
        registry,
        calendar_bundle(
            announced="2024-05-15T08:30:00-04:00",
            entries=[
                dict(
                    series_id="CPIAUCSL",
                    reference_period="2024-04",
                    announced_at="2024-05-15T08:30:00-04:00",
                    evidence_note="Invented calendar",
                )
            ],
        ),
    )
    report = build_research_report(store, registry, settings, ASOF)
    state = next(s.status for s in report.sections if s.key == "calendar")
    assert state == "limited" and report.calendar.upcoming[0].stale_evidence
    assert "نیازمند بررسی دوباره" in render_research_report(report)


def test_new_runs_preserve_previous_artifacts_and_reader_notes(store, registry, settings, tmp_path):
    report = build_research_report(store, registry, settings, ASOF)
    first = write_research_report(report, tmp_path)
    before = (first / "research-report.fa.md").read_bytes()
    (first / "reader-notes.md").write_text("Personal review", encoding="utf-8")
    second = write_research_report(report, tmp_path)
    assert first != second and (first / "research-report.fa.md").read_bytes() == before
    assert (first / "reader-notes.md").read_text() == "Personal review"
    assert verify_research_bundle(first) == verify_research_bundle(second)


@pytest.mark.parametrize("target", ["research-report.fa.md", "details/macro.json"])
def test_tampered_file_fails_bundle_verification(store, registry, settings, tmp_path, target):
    directory = write_research_report(
        build_research_report(store, registry, settings, ASOF), tmp_path
    )
    (directory / target).write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_research_bundle(directory)


def test_rehashed_mismatched_detail_is_detected(store, registry, settings, tmp_path):
    directory = write_research_report(
        build_research_report(store, registry, settings, ASOF), tmp_path
    )
    path = directory / "details/calendar.json"
    data = json.loads(path.read_bytes())
    data["horizon_days"] = 10
    content = json.dumps(data).encode()
    path.write_bytes(content)
    manifest = json.loads((directory / "manifest.json").read_bytes())
    item = next(f for f in manifest["files"] if f["path"] == "details/calendar.json")
    item.update(sha256=hashlib.sha256(content).hexdigest(), bytes=len(content))
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="detail differs"):
        verify_research_bundle(directory)


@pytest.mark.parametrize("path", ["../secret.json", "/absolute.json", "details/../../secret.json"])
def test_manifest_rejects_escaping_paths(store, registry, settings, tmp_path, path):
    directory = write_research_report(
        build_research_report(store, registry, settings, ASOF), tmp_path
    )
    data = json.loads((directory / "manifest.json").read_bytes())
    data["files"][0]["path"] = path
    with pytest.raises(ValueError):
        ReportManifest.model_validate(data)


def test_failed_write_does_not_publish_a_partial_run(
    store, registry, settings, tmp_path, monkeypatch
):
    report = build_research_report(store, registry, settings, ASOF)
    original = Path.write_bytes

    def fail(path, content):
        if path.name == "calendar.json":
            raise OSError("Simulated disk failure")
        return original(path, content)

    monkeypatch.setattr(Path, "write_bytes", fail)
    with pytest.raises(OSError, match="Simulated disk"):
        write_research_report(report, tmp_path)
    assert not list(tmp_path.glob("research-*"))
    assert list(tmp_path.glob(".incomplete-*"))


def test_cli_partial_and_independent_bundle_verification(tmp_path, capsys):
    code = main(
        [
            "--store",
            str(tmp_path / "empty"),
            "research-report",
            "--as-of",
            ASOF.isoformat(),
            "--output-dir",
            str(tmp_path / "reports"),
        ]
    )
    assert code == 3
    result = json.loads(capsys.readouterr().out)
    directory = Path(result["bundle"])
    assert (
        main(["--registry", str(tmp_path / "no-registry.yaml"), "verify-report", str(directory)])
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["files"] == len(FILES) and result["status"] == "verified"
