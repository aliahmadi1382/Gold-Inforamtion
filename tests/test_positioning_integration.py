"""COT in versioned reports; frozen legacy inputs and invented position counts."""

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import validate
from test_cftc_positioning import provider, row
from test_research_report import ASOF
from test_research_report import settings as settings

from gold_intelligence import cftc, research_report
from gold_intelligence.cli import main
from gold_intelligence.report_comparison import (
    ComparisonFile,
    ComparisonManifest,
    ReportComparisonV1,
    compare_reports,
    compare_snapshots,
    render_comparison,
    verify_comparison,
)
from gold_intelligence.research_report import (
    ResearchReport,
    ResearchReportV1,
    build_research_report,
    fingerprint,
    load_verified_report,
    parse_research_report,
    render_research_report,
    verify_research_bundle,
    write_research_report,
)
from gold_intelligence.storage import Store

LEGACY = Path("tests/fixtures/report-v1")


def add_cot(store, registry, monkeypatch, known=ASOF, shift=0, day_offset=0):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return known.astimezone(tz or UTC)

    monkeypatch.setattr(cftc, "datetime", Clock)
    start = date(2024, 4, 2) + timedelta(days=day_offset)
    end = start + timedelta(days=7)
    fetch, _ = provider([row(start, shift), row(end, shift + 1)])
    return cftc.ingest_cftc_gold(store, registry.get("cftc_disaggregated"), start, end, fetch)


def compare(before, after):
    return compare_snapshots(before.model_dump_json().encode(), after.model_dump_json().encode())


def cot_section(report):
    return next(s for s in report.sections if s.key == "positioning")


def test_eight_sections_and_complete_thirteen_file_bundle(
    store, registry, settings, monkeypatch, tmp_path
):
    add_cot(store, registry, monkeypatch)
    report = build_research_report(store, registry, settings, ASOF)
    assert report.schema_version == "2.0.0" and len(report.sections) == 8
    assert cot_section(report).status == "limited"
    assert report.positioning.as_of == report.as_of
    assert report.positioning.eligible_record_versions == 10
    folder = write_research_report(report, tmp_path)
    assert verify_research_bundle(folder)["files"] == 13
    saved, manifest, raw = load_verified_report(folder)
    assert saved == report and manifest.schema_version == "2.0.0"
    assert (
        json.loads((folder / "details/positioning.json").read_bytes())
        == json.loads(raw)["positioning"]
    )
    assert (folder / "details/positioning.fa.md").is_file()
    assert "مدیران سرمایه" in render_research_report(report)
    assert not saved.positioning.historical_release_ready


def test_absent_future_and_stale_cot_are_explicit(store, registry, settings, monkeypatch):
    add_cot(store, registry, monkeypatch, known=ASOF + timedelta(seconds=1))
    before = build_research_report(store, registry, settings, ASOF)
    assert cot_section(before).status == "missing"
    assert before.positioning.status == "no_data"
    assert "به معنی خالص صفر نیست" in render_research_report(before)
    after = build_research_report(store, registry, settings, ASOF + timedelta(days=15))
    assert after.positioning.status == "stale" and cot_section(after).status == "limited"
    assert "دادهٔ قدیمی" in render_research_report(after)


def test_cot_part_uses_same_sqlite_snapshot(store, registry, settings, monkeypatch):
    store.db.execute("PRAGMA journal_mode=WAL")
    original = research_report.macro_context

    def write_while_reading(*args):
        with Store(store.root) as writer:
            add_cot(writer, registry, monkeypatch)
        return original(*args)

    monkeypatch.setattr(research_report, "macro_context", write_while_reading)
    report = build_research_report(store, registry, settings, ASOF)
    assert report.quality.eligible_records == 0 and report.positioning.status == "no_data"
    assert len(store.read("positioning")) == 10
    assert not store.db.in_transaction


def test_cot_page_corruption_stops_unified_report(store, registry, settings, monkeypatch):
    add_cot(store, registry, monkeypatch)
    record = store.read("positioning")[0]
    capture = cftc.CotCapture.model_validate_json(
        cftc.raw_json(store, record.provenance.raw_sha256)
    )
    (store.root / "raw" / capture.pages[0].sha256).write_bytes(b"damaged page")
    with pytest.raises(ValueError, match="corrupt CFTC"):
        build_research_report(store, registry, settings, ASOF)
    assert not store.db.in_transaction


@pytest.mark.parametrize(
    "damage",
    [
        "policy",
        "inventory",
        "net",
        "share",
        "delta",
        "missing_group",
        "duplicate_week",
        "age",
        "future_clock",
        "spreading",
        "open_interest",
    ],
)
def test_rehashed_report_cannot_hide_incoherent_positioning(
    store, registry, settings, monkeypatch, damage
):
    add_cot(store, registry, monkeypatch)
    data = build_research_report(store, registry, settings, ASOF).model_dump(mode="json")
    cot = data["positioning"]
    group = cot["weeks"][-1]["categories"][2]
    if damage == "policy":
        data["settings"]["positioning_max_age_days"] = 30
    elif damage == "inventory":
        cot["eligible_record_versions"] += 5
        cot["superseded_record_versions"] += 5
    elif damage == "net":
        group["net"] += 1
    elif damage == "share":
        group["net_percent_open_interest"] += 1
    elif damage == "delta":
        group["net_change_7d"] += 1
    elif damage == "missing_group":
        cot["weeks"][-1]["categories"].pop()
    elif damage == "duplicate_week":
        cot["weeks"].append(cot["weeks"][0])
    elif damage == "age":
        cot["latest_observation_age_days"] += 1
    elif damage == "future_clock":
        cot["weeks"][-1]["known_at"] = "2024-05-01T00:00:00Z"
    elif damage == "spreading":
        cot["weeks"][-1]["categories"][0]["spreading"] = 0
    else:
        cot["weeks"][-1]["open_interest"] += 1
    data["fingerprint"] = fingerprint(data)
    with pytest.raises(ValueError):
        ResearchReport.model_validate(data)


def test_recapture_is_evidence_without_position_change(store, registry, settings, monkeypatch):
    add_cot(store, registry, monkeypatch)
    before = build_research_report(store, registry, settings, ASOF)
    later = ASOF + timedelta(hours=1)
    add_cot(store, registry, monkeypatch, known=later)
    after = build_research_report(store, registry, settings, later)
    result = compare(before, after)
    groups = [
        c for c in result.changes if c.section == "positioning" and c.collection == "categories"
    ]
    assert len(groups) == 10 and all(f.category == "evidence" for c in groups for f in c.fields)
    weeks = [c for c in result.changes if c.section == "positioning" and c.collection == "weeks"]
    assert weeks and all(f.category == "evidence" for c in weeks for f in c.fields)
    assert len(cot_section(result).evidence_ids_added) == 10


def test_changed_positions_match_by_date_and_category(store, registry, settings, monkeypatch):
    add_cot(store, registry, monkeypatch)
    before = build_research_report(store, registry, settings, ASOF)
    later = ASOF + timedelta(hours=1)
    add_cot(store, registry, monkeypatch, known=later, shift=3)
    result = compare(before, build_research_report(store, registry, settings, later))
    changed = next(
        c
        for c in result.changes
        if c.section == "positioning" and c.identity[-2:] == ("2024-04-09", "managed_money")
    )
    net = next(f for f in changed.fields if f.path == "/net")
    assert changed.action == "modified" and (net.before, net.after) == (21, 24)
    assert net.category == "result" and changed.before_pointer.endswith("/categories/2")
    assert "مدیران سرمایه" in render_comparison(result)


def test_age_is_separate_from_values_and_evidence(store, registry, settings, monkeypatch):
    add_cot(store, registry, monkeypatch)
    before = build_research_report(store, registry, settings, ASOF)
    after = build_research_report(store, registry, settings, ASOF + timedelta(days=1))
    result = compare(before, after)
    changes = [f for c in result.changes if c.section == "positioning" for f in c.fields]
    assert len(changes) == 1 and changes[0].category == "age"
    assert changes[0].path == "/latest_observation_age_days"
    assert not cot_section(result).evidence_ids_added


def test_same_schema_missing_data_to_new_data_is_comparable(store, registry, settings, monkeypatch):
    before = build_research_report(store, registry, settings, ASOF)
    add_cot(store, registry, monkeypatch)
    result = compare(before, build_research_report(store, registry, settings, ASOF))
    cot = cot_section(result)
    assert cot.before_status == "missing" and cot.after_status == "limited"
    assert cot.comparison_basis == "both_present" and cot.added == 12
    assert len(cot.evidence_ids_added) == 10


def test_semantic_reorder_has_no_changes(store, registry, settings, monkeypatch, tmp_path):
    add_cot(store, registry, monkeypatch)
    before = build_research_report(store, registry, settings, ASOF)
    data = before.model_dump(mode="json")
    data["positioning"]["weeks"].reverse()
    for week in data["positioning"]["weeks"]:
        week["categories"].reverse()
    data["fingerprint"] = fingerprint(data)
    after = ResearchReport.model_validate(data)
    assert compare(before, after).status == "unchanged"
    folder = write_research_report(after, tmp_path)
    text = (folder / "details/positioning.fa.md").read_text(encoding="utf-8")
    assert "آخرین مشاهده: **2024-04-09**" in text


@pytest.mark.parametrize("direction", ["old_new", "new_old", "old_old"])
def test_schema_absence_is_not_missing_or_changed_positions(
    store, registry, settings, monkeypatch, direction
):
    old = parse_research_report((LEGACY / "before.json").read_bytes())
    add_cot(store, registry, monkeypatch)
    new = build_research_report(store, registry, settings, ASOF)
    before, after = (
        (old, new)
        if direction == "old_new"
        else ((new, old) if direction == "new_old" else (old, old))
    )
    result = compare(before, after)
    cot = cot_section(result)
    assert (
        cot.comparison_basis
        == {
            "old_new": "not_in_before_schema",
            "new_old": "not_in_after_schema",
            "old_old": "neither_schema",
        }[direction]
    )
    assert cot.added == cot.removed == cot.modified == cot.unchanged == 0
    assert not cot.evidence_ids_added and not cot.evidence_ids_removed
    assert not any(c.section == "positioning" for c in result.changes)
    assert "به معنی خالص صفر یا موقعیت بدون تغییر نیست" in render_comparison(result)


def test_frozen_legacy_report_serialization_and_bundle(tmp_path):
    raw = (LEGACY / "before.json").read_bytes()
    report = parse_research_report(raw)
    assert type(report) is ResearchReportV1
    assert report.model_dump(mode="json") == json.loads(raw)
    assert not hasattr(report.settings, "positioning_max_age_days")
    folder = write_research_report(report, tmp_path)
    assert verify_research_bundle(folder)["files"] == 11
    assert load_verified_report(folder)[0].fingerprint == report.fingerprint
    validate(
        report.model_dump(mode="json"),
        json.loads(Path("schemas/research_report_v1.schema.json").read_bytes()),
    )


def test_frozen_comparator_one_recomputes_exactly_and_verifies_without_source_store(tmp_path):
    left, right = [(LEGACY / name).read_bytes() for name in ("before.json", "after.json")]
    saved = ReportComparisonV1.model_validate_json((LEGACY / "comparison.json").read_bytes())
    result = compare_snapshots(
        left,
        right,
        saved.before.location,
        saved.after.location,
        saved.software_version,
        saved.generated_at,
        "1.0.0",
    )
    assert result == saved and len(result.changes) == 6
    outputs = {
        "comparison.json": (LEGACY / "comparison.json").read_bytes(),
        "inputs/before.json": left,
        "inputs/after.json": right,
        "comparison.fa.md": b"Frozen empty-store compatibility fixture",
    }
    (tmp_path / "inputs").mkdir()
    for name, content in outputs.items():
        (tmp_path / name).write_bytes(content)
    manifest = ComparisonManifest(
        fingerprint=saved.fingerprint,
        files=[
            ComparisonFile(path=k, sha256=hashlib.sha256(v).hexdigest(), bytes=len(v))
            for k, v in outputs.items()
        ],
    )
    (tmp_path / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    assert verify_comparison(tmp_path)["status"] == "verified"


@pytest.mark.parametrize("version", [None, "3.0.0", "1.0"])
def test_unknown_or_missing_versions_rejected(version):
    data = json.loads((LEGACY / "before.json").read_bytes())
    if version is None:
        data.pop("schema_version")
    else:
        data["schema_version"] = version
    with pytest.raises(ValueError, match="unsupported"):
        parse_research_report(data)


def test_manifest_cannot_claim_legacy_file_set_for_new_report(store, registry, settings, tmp_path):
    folder = write_research_report(build_research_report(store, registry, settings, ASOF), tmp_path)
    manifest = json.loads((folder / "manifest.json").read_bytes())
    manifest["schema_version"] = "1.0.0"
    manifest["files"] = [f for f in manifest["files"] if "positioning" not in f["path"]]
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="manifest differs"):
        verify_research_bundle(folder)


def test_rehashed_cot_detail_tamper_fails(store, registry, settings, monkeypatch, tmp_path):
    add_cot(store, registry, monkeypatch)
    folder = write_research_report(build_research_report(store, registry, settings, ASOF), tmp_path)
    path = folder / "details/positioning.json"
    data = json.loads(path.read_bytes())
    data["weeks"][0]["categories"][0]["net"] += 1
    content = json.dumps(data).encode()
    path.write_bytes(content)
    manifest = json.loads((folder / "manifest.json").read_bytes())
    entry = next(f for f in manifest["files"] if f["path"] == "details/positioning.json")
    entry.update(sha256=hashlib.sha256(content).hexdigest(), bytes=len(content))
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="detail differs"):
        verify_research_bundle(folder)


def test_cli_policy_and_mixed_schema_comparison(
    store, registry, settings, monkeypatch, tmp_path, capsys
):
    add_cot(store, registry, monkeypatch)
    assert (
        main(
            [
                "--store",
                str(store.root),
                "research-report",
                "--as-of",
                ASOF.isoformat(),
                "--positioning-max-age-days",
                "1",
                "--output-dir",
                str(tmp_path / "new"),
            ]
        )
        == 3
    )
    output = json.loads(capsys.readouterr().out)
    folder = Path(output["bundle"])
    assert load_verified_report(folder)[0].positioning.status == "stale"
    old = write_research_report(
        parse_research_report((LEGACY / "before.json").read_bytes()), tmp_path / "old"
    )
    comparison, dest = compare_reports(old, folder, tmp_path / "comparison")
    assert (
        comparison.schema_version == "2.0.0"
        and cot_section(comparison).comparison_basis == "not_in_before_schema"
    )
    assert verify_comparison(dest)["status"] == "verified"
    validate(
        comparison.model_dump(mode="json"),
        json.loads(Path("schemas/report_comparison.schema.json").read_bytes()),
    )
