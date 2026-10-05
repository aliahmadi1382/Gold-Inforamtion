"""Comparison fixtures are invented report content, never market observations."""

import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import validate
from test_alpha_vantage import parse as parse_gold
from test_alpha_vantage import response as gold_response
from test_release_calendar import bundle as calendar_bundle
from test_release_calendar import insert as insert_calendar
from test_release_values import fred
from test_research_report import ASOF
from test_research_report import settings as settings
from test_revision_ledger import add, document, vintages

from gold_intelligence.cli import main
from gold_intelligence.report_comparison import (
    ARTIFACTS,
    ComparisonManifest,
    ReportComparison,
    compare_reports,
    compare_snapshots,
    comparison_fingerprint,
    fields,
    render_comparison,
    verify_comparison,
)
from gold_intelligence.research_report import (
    PARTS,
    ResearchReport,
    build_research_report,
    fingerprint,
    load_verified_report,
    overall_status,
    section_states,
    write_research_report,
)
from gold_intelligence.storage import Store


@pytest.fixture
def empty(store, registry, settings):
    return build_research_report(store, registry, settings, ASOF)


def edit(report, update):
    data = report.model_dump(mode="json")
    update(data)
    parts = {name: type(getattr(report, name)).model_validate(data[name]) for name in PARTS}
    data.update({name: part.model_dump(mode="json") for name, part in parts.items()})
    sections = section_states(**parts)
    data["sections"] = [s.model_dump(mode="json") for s in sections]
    data["status"] = overall_status(sections, parts["quality"])
    data["fingerprint"] = fingerprint(data)
    return ResearchReport.model_validate(data)


def compare(before, after):
    return compare_snapshots(before.model_dump_json().encode(), after.model_dump_json().encode())


def test_same_input_has_no_changes_and_keeps_partial_status(empty):
    result = compare(empty, empty)
    assert result.status == "unchanged" and not result.changes and not result.context_changes
    assert result.before.status == result.after.status == "partial"
    assert all(not s.evidence_ids_added and not s.evidence_ids_removed for s in result.sections)
    assert not result.daily_backtest_ready and not result.causal_attribution


def test_build_clocks_and_paths_are_not_data_changes(empty):
    def update(data):
        data["generated_at"] = "2026-10-05T00:00:00Z"
        for name in PARTS:
            if "generated_at" in data[name]:
                data[name]["generated_at"] = data["generated_at"]

    after = edit(empty, update)
    result = compare(empty, after)
    assert result.status == "unchanged"
    assert result.before.report_sha256 != result.after.report_sha256
    moved = result.model_dump(mode="json")
    moved["before"]["location"] = "another directory"
    assert ReportComparison.model_validate(moved).fingerprint == result.fingerprint


@pytest.mark.parametrize("change", ["version", "cutoff", "registry", "settings"])
def test_context_only_changes_are_explicit(empty, change):
    def update(data):
        if change == "version":
            data["software_version"] = "0.9.0"
            for part in PARTS:
                if "software_version" in data[part]:
                    data[part]["software_version"] = "0.9.0"
        elif change == "cutoff":
            data["as_of"] = "2024-04-16T01:00:00Z"
            for part in PARTS:
                data[part]["as_of"] = data["as_of"]
        elif change == "registry":
            data["registry_sha256"] = "a" * 64
        else:
            data["settings"]["calendar_horizon_days"] = 10
            data["calendar"]["horizon_days"] = 10

    result = compare(empty, edit(empty, update))
    assert result.status == "context_only" and len(result.context_changes) == 1
    assert not result.changes
    assert "اثر مستقل" in render_comparison(result)


def test_reversed_cutoff_is_rejected(store, registry, settings, empty):
    newer = build_research_report(store, registry, settings, ASOF + timedelta(hours=1))
    with pytest.raises(ValueError, match="must not precede"):
        compare(newer, empty)


def test_real_engine_aging_does_not_invent_new_evidence(store, registry, settings):
    fred(store, registry, vintage=None, retrieved=ASOF)
    before = build_research_report(store, registry, settings, ASOF)
    after = build_research_report(store, registry, settings, ASOF + timedelta(hours=1))
    result = compare(before, after)
    assert result.status == "changed"
    assert [f.path for f in result.context_changes] == ["/as_of"]
    assert any(f.category == "age" for c in result.changes for f in c.fields)
    assert all(not s.evidence_ids_added and not s.evidence_ids_removed for s in result.sections)
    assert not any(f.path == "/value" for c in result.changes for f in c.fields)


def test_same_value_new_record_and_null_revision_are_distinct(store, registry, settings):
    fred(store, registry, vintage=None, retrieved=ASOF)
    before = build_research_report(store, registry, settings, ASOF)
    later = ASOF + timedelta(hours=1)
    fred(store, registry, vintage=None, retrieved=later)
    after = build_research_report(store, registry, settings, later)
    result = compare(before, after)
    macro = next(s for s in result.sections if s.key == "macro")
    assert len(macro.evidence_ids_added) == len(macro.evidence_ids_removed) == 1
    rows = [c for c in result.changes if c.section == "macro" and c.collection == "entries"]
    assert rows and any(f.path == "/record_id" for c in rows for f in c.fields)
    assert not any(f.path == "/value" for c in rows for f in c.fields)
    latest = later + timedelta(hours=1)
    fred(
        store, registry, [("2024-01-01", 100), ("2024-02-01", None)], vintage=None, retrieved=latest
    )
    missing = compare(after, build_research_report(store, registry, settings, latest))
    changes = [f for c in missing.changes if c.section == "macro" for f in c.fields]
    assert any(f.path == "/value" and f.before is not None and f.after is None for f in changes)


def test_null_zero_and_absent_field_do_not_collapse(empty):
    zero = edit(empty, lambda d: d["macro"]["entries"][0].update(value=0))
    result = compare(empty, zero)
    field = next(f for c in result.changes for f in c.fields if f.path == "/value")
    assert field.before is None and field.after == 0
    assert field.before_present and field.after_present
    missing = fields({}, {"x": None})[0]
    assert not missing.before_present and missing.after_present and missing.after is None
    assert "مقدار نامعلوم" in render_comparison(result)


def test_reordered_rows_do_not_create_changes(empty):
    def reorder(data):
        for name in ("levels", "changes", "associations", "rolling"):
            data["monthly"][name].reverse()
        data["revisions"]["pairs"].reverse()
        data["revisions"]["document_slots"].reverse()

    assert compare(empty, edit(empty, reorder)).status == "unchanged"


@pytest.mark.parametrize(
    "field,value", [("unit", "different_unit"), ("method", "different_method")]
)
def test_definition_changes_replace_identity_without_numeric_subtraction(empty, field, value):
    after = edit(empty, lambda d: d["monthly"]["levels"][0].update({field: value}))
    rows = [c for c in compare(empty, after).changes if c.collection == "levels"]
    assert {c.action for c in rows} == {"added", "removed"} and len(rows) == 2


def test_common_sample_membership_change_survives_equal_coefficients(empty):
    def update(data):
        row = next(a for a in data["monthly"]["associations"] if a["population"] == "common")
        row["months"] = ["2024-02-01"]
        row["n"] = 1

    rows = [
        c for c in compare(empty, edit(empty, update)).changes if c.collection == "associations"
    ]
    assert len(rows) == 1 and "common" in rows[0].identity
    assert {f.path for f in rows[0].fields} == {"/months", "/n"}


def test_duplicate_semantic_identity_is_rejected(empty):
    after = edit(empty, lambda d: d["monthly"]["levels"].append(d["monthly"]["levels"][0]))
    with pytest.raises(ValueError, match="ambiguous entity"):
        compare(empty, after)


def test_calendar_reschedule_matches_event_identity(store, registry, settings):
    insert_calendar(store, registry, calendar_bundle(announced="2024-05-15T08:30:00-04:00"))
    before = build_research_report(store, registry, settings, ASOF)

    # Retain a known event but change all three display clocks consistently in the saved fixture.
    def update(data):
        row = data["calendar"]["upcoming"][0]
        for field in ("announced_at", "new_york_time", "tehran_time"):
            row[field] = (datetime.fromisoformat(row[field]) + timedelta(days=1)).isoformat()

    result = compare(before, edit(before, update))
    rows = [c for c in result.changes if c.collection == "upcoming"]
    assert len(rows) == 1 and rows[0].action == "modified"
    assert {f.path for f in rows[0].fields} == {"/announced_at", "/new_york_time", "/tehran_time"}


def test_event_exit_is_view_removal_not_cancellation(store, registry, settings):
    insert_calendar(store, registry, calendar_bundle(announced="2024-05-15T08:30:00-04:00"))
    before = build_research_report(store, registry, settings, ASOF)
    after = build_research_report(store, registry, settings, ASOF + timedelta(days=60))
    result = compare(before, after)
    assert any(c.collection == "upcoming" and c.action == "removed" for c in result.changes)
    assert "حذف از پایگاه یا انتشار جدید منبع از آن نتیجه نمی‌شود" in render_comparison(result)


def test_release_values_and_ledger_keep_period_and_capture_identities(store, registry, settings):
    add(store, registry)
    vintages(store, registry)
    before = build_research_report(store, registry, settings, ASOF)
    add(store, registry, document(2, prior=0.3))
    after = build_research_report(store, registry, settings, ASOF)
    result = compare(before, after)
    assert not result.context_changes
    assert any(c.collection == "documents" and c.action == "added" for c in result.changes)
    assert any(c.collection == "captures" and c.action == "added" for c in result.changes)
    pair = next(c for c in result.changes if c.collection == "pairs")
    assert pair.identity == ("cpi_all_items_sa_mom", "2024-01") and pair.action == "modified"
    assert any(f.path == "/difference_pp" and f.after == 0.2 for f in pair.fields)


def test_verified_bundle_is_self_contained_and_preserves_previous_runs(empty, tmp_path):
    source = write_research_report(empty, tmp_path / "source")
    result, first = compare_reports(source, source, tmp_path / "output")
    before = {p.name: p.read_bytes() for p in first.iterdir() if p.is_file()}
    (first / "notes.md").write_text("reader notes", encoding="utf-8")
    _, second = compare_reports(source, source, tmp_path / "output")
    assert first != second and all((first / k).read_bytes() == v for k, v in before.items())
    assert verify_comparison(first) == verify_comparison(second)
    source.rename(source.with_name("moved-original"))
    assert verify_comparison(first)["files"] == len(ARTIFACTS)
    text = (first / "comparison.fa.md").read_text(encoding="utf-8")
    for link in re.findall(r"\]\(([^)]+)\)", text):
        assert (first / link).is_file()
    for name, model in (
        ("comparison.json", "report_comparison"),
        ("manifest.json", "comparison_manifest"),
    ):
        validate(
            json.loads((first / name).read_bytes()),
            json.loads(Path(f"schemas/{model}.schema.json").read_text()),
        )
    assert result.status == "unchanged"


@pytest.mark.parametrize(
    "target", ["research-report.json", "details/calendar.json", "research-report.fa.md"]
)
def test_damaged_input_is_rejected_before_output(empty, tmp_path, target):
    source = write_research_report(empty, tmp_path / "source")
    (source / target).write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        compare_reports(source, source, tmp_path / "output")
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("target", ["comparison.fa.md", "inputs/before.json", "comparison.json"])
def test_comparison_hash_check_rejects_modified_file(empty, tmp_path, target):
    source = write_research_report(empty, tmp_path / "source")
    _, output = compare_reports(source, source, tmp_path / "output")
    (output / target).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_comparison(output)


def test_rehashed_and_refingerprinted_false_summary_fails_recomputation(empty, tmp_path):
    source = write_research_report(empty, tmp_path / "source")
    _, output = compare_reports(source, source, tmp_path / "output")
    data = json.loads((output / "comparison.json").read_bytes())
    data["sections"][0]["unchanged"] += 1
    data["fingerprint"] = comparison_fingerprint(data)
    content = (json.dumps(data) + "\n").encode()
    (output / "comparison.json").write_bytes(content)
    manifest = json.loads((output / "manifest.json").read_bytes())
    manifest["fingerprint"] = data["fingerprint"]
    row = next(f for f in manifest["files"] if f["path"] == "comparison.json")
    row.update(sha256=hashlib.sha256(content).hexdigest(), bytes=len(content))
    (output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="recomputed"):
        verify_comparison(output)


@pytest.mark.parametrize("path", ["../secret.json", "/absolute.json", "inputs/../../secret.json"])
def test_manifest_rejects_traversal(path):
    with pytest.raises(ValueError):
        ComparisonManifest(fingerprint="a" * 64, files=[dict(path=path, sha256="b" * 64, bytes=1)])


def test_disk_failure_does_not_publish_partial_comparison(empty, tmp_path, monkeypatch):
    source = write_research_report(empty, tmp_path / "source")
    original = Path.write_bytes

    def fail(path, content):
        if path.name == "comparison.fa.md":
            raise OSError("Simulated full disk")
        return original(path, content)

    monkeypatch.setattr(Path, "write_bytes", fail)
    with pytest.raises(OSError, match="full disk"):
        compare_reports(source, source, tmp_path / "output")
    assert not list((tmp_path / "output").glob("comparison-*"))
    assert list((tmp_path / "output").glob(".incomplete-*"))


def test_cli_does_not_open_database_or_registry(empty, tmp_path, capsys):
    source = write_research_report(empty, tmp_path / "source")
    assert (
        main(
            [
                "--store",
                str(tmp_path / "no-db"),
                "--registry",
                "absent.yaml",
                "compare-reports",
                str(source),
                str(source),
                "--output-dir",
                str(tmp_path / "output"),
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "unchanged"
    assert not (tmp_path / "no-db").exists()
    assert main(["--registry", "absent.yaml", "verify-comparison", output["bundle"]]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "verified"


def test_input_snapshot_uses_exact_bytes_that_passed_hash_check(empty, tmp_path, monkeypatch):
    source = write_research_report(empty, tmp_path)
    path = source / "research-report.json"
    original = Path.read_bytes
    calls = []

    def mutate_after_read(file):
        content = original(file)
        if file == path:
            calls.append(file)
            file.write_bytes(b"changed after read")
        return content

    monkeypatch.setattr(Path, "read_bytes", mutate_after_read)
    report, manifest, snapshot = load_verified_report(source)
    assert len(calls) == 1 and report == empty
    saved = next(f for f in manifest.files if f.path == "research-report.json")
    assert hashlib.sha256(snapshot).hexdigest() == saved.sha256


def test_unchanged_price_coverage_cannot_certify_underlying_prices(
    store, registry, settings, tmp_path
):
    store.put(parse_gold(store, registry, gold_response([{"date": "2024-01-05", "price": "100"}])))
    before = build_research_report(store, registry, settings, ASOF)
    with Store(tmp_path / "different-source-history") as other:
        other.put(
            parse_gold(other, registry, gold_response([{"date": "2024-01-05", "price": "900"}]))
        )
        after = build_research_report(other, registry, settings, ASOF)
    result = compare(before, after)
    assert result.status == "unchanged"
    assert "یکسانی پوشش، یکسانی تمام قیمت‌ها" in render_comparison(result)


def test_field_paths_escape_keys_and_preserve_add_remove_presence():
    change = fields({"a/b~c": 7}, {})[0]
    assert change.path == "/a~1b~0c"
    assert change.before_present and not change.after_present
    assert change.before == 7 and change.after is None
