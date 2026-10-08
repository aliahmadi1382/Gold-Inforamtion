"""Review semantics and recovery use invented offline observations only."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import validate
from test_refresh import offline as offline
from test_release_values import fred
from test_report_comparison import edit
from test_research_report import ASOF
from test_research_report import settings as settings

from gold_intelligence import cli, refresh_review
from gold_intelligence.refresh import (
    RefreshPolicy,
    completed_status,
    refresh_and_report,
    report_freshness,
)
from gold_intelligence.refresh_review import (
    Baseline,
    build_review,
    change_kind,
    digest,
    render_review,
    review_fingerprint,
    select_baseline,
    verify_review,
    write_refresh_review,
)
from gold_intelligence.report_comparison import FieldChange
from gold_intelligence.research_report import (
    build_research_report,
    load_verified_report,
    write_research_report,
)


@pytest.fixture
def workflow(store, registry, settings, tmp_path, offline):
    before = build_research_report(store, registry, settings, ASOF)
    baseline_dir = write_research_report(before, tmp_path / "baseline")
    baseline = select_baseline(None, baseline_dir)
    run, folder = refresh_and_report(store, registry, settings, RefreshPolicy(), tmp_path / "out")
    return run, folder, baseline, baseline_dir


def test_compared_review_reconciles_counts_and_exact_evidence(workflow):
    run, folder, baseline, _ = workflow
    review, output = write_refresh_review(folder, baseline)
    assert review.status == "compared"
    assert review.refresh_run_id == run.run_id
    assert review.field_counts["view"] > 0
    assert review.field_counts["numeric"] > 0
    assert sum(review.field_counts.values()) == sum(
        len(row.fields) for row in review.comparison.changes
    )
    assert (output / "inputs/before.json").read_bytes() == baseline.content
    assert (output / "inputs/refresh-run.json").read_bytes() == (
        folder / "refresh-run.json"
    ).read_bytes()
    assert verify_review(output)["files"] == 5
    validate(
        review.model_dump(mode="json"),
        json.loads(Path("schemas/refresh_review.schema.json").read_bytes()),
    )
    assert "ثبات پوشش قیمت" in render_review(review)
    assert not review.daily_backtest_ready and not review.causal_attribution
    # Every priority's pointer resolves to its named copied input.
    for priority in review.priorities:
        value = json.loads((output / priority.input_path).read_bytes())
        for token in priority.pointer.split("/")[1:]:
            token = token.replace("~1", "/").replace("~0", "~")
            value = value[int(token)] if isinstance(value, list) else value[token]


@pytest.mark.parametrize(
    "baseline,status,code",
    [
        (Baseline("missing"), "no_baseline", "BASELINE_MISSING"),
        (Baseline("failed", failure_type="ValueError"), "baseline_failed", "BASELINE_FAILED"),
    ],
)
def test_absent_and_failed_baselines_never_claim_unchanged(workflow, baseline, status, code):
    _, folder, _, _ = workflow
    review, output = write_refresh_review(folder, baseline)
    assert review.status == status and review.comparison is None
    assert not any(review.field_counts.values())
    assert code in {p.code for p in review.priorities}
    assert "نبود مقایسه به معنی نبود تغییر نیست" in render_review(review)
    assert verify_review(output)["review_status"] == status


@pytest.mark.parametrize(
    "before,after,category,bp,ap,expected",
    [
        (0, 1, "result", True, True, "numeric"),
        (0, None, "result", True, True, "missingness"),
        (None, 0, "result", True, True, "missingness"),
        (False, True, "result", True, True, "result"),
        (None, 0, "result", False, True, "view"),
        (0, None, "result", True, False, "view"),
        (1, 2, "age", True, True, "age"),
        ("old", "new", "evidence", True, True, "evidence"),
    ],
)
def test_zero_null_schema_absence_evidence_and_age_are_distinct(
    before, after, category, bp, ap, expected
):
    field = FieldChange(
        path="/value",
        category=category,
        before_present=bp,
        after_present=ap,
        before=before,
        after=after,
    )
    assert change_kind(field) == expected


def test_baseline_snapshot_survives_original_removal(workflow):
    _, folder, baseline, original = workflow
    (original / "research-report.json").unlink()
    review, output = write_refresh_review(folder, baseline)
    assert review.status == "compared" and verify_review(output)["status"] == "verified"


def test_auto_selection_filters_other_stores_and_does_not_skip_corruption(workflow, store):
    run, folder, _, _ = workflow
    assert select_baseline(folder.parent, store_root=store.root).status == "selected"
    assert select_baseline(folder.parent, store_root=folder / "other").status == "missing"
    (folder / run.report.bundle / "research-report.json").write_bytes(b"damaged")
    assert select_baseline(folder.parent, store_root=store.root).status == "failed"


def test_auto_selection_rejects_ambiguous_latest(workflow):
    _, folder, _, _ = workflow
    other = folder.parent / "refresh-duplicate"
    other.mkdir()
    (other / "refresh-run.json").write_bytes((folder / "refresh-run.json").read_bytes())
    assert select_baseline(folder.parent).status == "failed"


def test_baseline_cutoff_after_refresh_start_is_explicit_failure(workflow):
    run, folder, _, _ = workflow
    _, _, after = load_verified_report(folder / run.report.bundle)
    review, output = write_refresh_review(folder, Baseline("selected", after))
    assert review.status == "comparison_failed" and review.failure_type == "ValueError"
    assert verify_review(output)["review_status"] == "comparison_failed"


def test_corrupt_explicit_baseline_does_not_leak_exception_text(tmp_path):
    result = select_baseline(None, tmp_path / "secret=do-not-display")
    assert result.status == "failed" and result.failure_type == "FileNotFoundError"
    assert "secret" not in repr(result)


def test_failed_acquisition_keeps_its_own_priority(workflow):
    run, folder, baseline, _ = workflow
    data = run.model_dump(mode="json")
    step = data["steps"][0]
    step.update(
        status="failed",
        acquisition_status="failed",
        failure_type="ValueError",
        failure_reason="HTTP_403",
    )
    (folder / "refresh-run.json").write_text(json.dumps(data), encoding="utf-8")
    review, output = write_refresh_review(folder, baseline)
    failures = [p for p in review.priorities if p.code == "ACQUISITION_FAILED"]
    assert len(failures) == 1 and "HTTP_403" in failures[0].message
    assert verify_review(output)["status"] == "verified"


def test_failed_report_still_exposes_acquisition_and_baseline(workflow):
    run, folder, baseline, _ = workflow
    data = run.model_dump(mode="json")
    data["status"] = "failed"
    data["report"] = {
        "status": "failed",
        "as_of": run.report.as_of.isoformat(),
        "failure_type": "ValueError",
    }
    (folder / "refresh-run.json").write_text(json.dumps(data), encoding="utf-8")
    review, output = write_refresh_review(folder, baseline)
    assert review.status == "report_failed" and review.after_sha256 is None
    assert "REPORT_UNAVAILABLE" in {p.code for p in review.priorities}
    assert verify_review(output)["files"] == 4


@pytest.mark.parametrize("name", ["review.fa.md", "inputs/after.json", "inputs/refresh-run.json"])
def test_byte_tampering_rejected(workflow, name):
    _, folder, baseline, _ = workflow
    _, output = write_refresh_review(folder, baseline)
    (output / name).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_review(output)


def rehash(output, name):
    manifest = json.loads((output / "manifest.json").read_bytes())
    content = (output / name).read_bytes()
    for item in manifest["files"]:
        if item["path"] == name:
            item.update(sha256=digest(content), bytes=len(content))
    if name == "review.json":
        manifest["fingerprint"] = json.loads(content)["fingerprint"]
    (output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_rehashed_false_priority_rejected_by_recomputation(workflow):
    _, folder, baseline, _ = workflow
    _, output = write_refresh_review(folder, baseline)
    data = json.loads((output / "review.json").read_bytes())
    data["priorities"][0]["message"] = "fabricated conclusion"
    data["fingerprint"] = review_fingerprint(data)
    (output / "review.json").write_text(json.dumps(data), encoding="utf-8")
    rehash(output, "review.json")
    with pytest.raises(ValueError, match="recomputed"):
        verify_review(output)


def test_rehashed_false_prose_rejected(workflow):
    _, folder, baseline, _ = workflow
    _, output = write_refresh_review(folder, baseline)
    (output / "review.fa.md").write_text("false prose", encoding="utf-8")
    rehash(output, "review.fa.md")
    with pytest.raises(ValueError, match="prose"):
        verify_review(output)


def test_repeated_output_preserves_prior_bundle_and_semantic_fingerprint(workflow):
    _, folder, baseline, _ = workflow
    first, output = write_refresh_review(folder, baseline)
    original = (output / "review.json").read_bytes()
    second, other = write_refresh_review(folder, baseline)
    assert output != other and first.fingerprint == second.fingerprint
    assert (output / "review.json").read_bytes() == original


def test_verify_needs_only_copied_inputs(workflow, monkeypatch):
    _, folder, baseline, _ = workflow
    _, output = write_refresh_review(folder, baseline)
    monkeypatch.setattr(
        refresh_review, "load_verified_report", lambda *_: pytest.fail("source read")
    )
    assert verify_review(output)["status"] == "verified"


def test_write_failure_does_not_publish_completed_bundle(workflow, monkeypatch):
    _, folder, baseline, _ = workflow
    original = Path.write_bytes

    def fail(path, content):
        if path.name == "review.json":
            raise OSError("disk full")
        return original(path, content)

    monkeypatch.setattr(Path, "write_bytes", fail)
    with pytest.raises(OSError):
        write_refresh_review(folder, baseline)
    assert not list((folder / "reviews").glob("review-*"))


def test_cli_offline_review_does_not_load_registry_or_store(workflow, capsys):
    _, folder, _, before = workflow
    assert (
        cli.main(
            [
                "--registry",
                "does-not-exist",
                "--store",
                "does-not-exist",
                "review-refresh",
                str(folder),
                "--baseline",
                str(before),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "compared"
    assert cli.main(["verify-review", result["bundle"]]) == 0


def test_cli_refresh_returns_review_without_masking_partial_result(tmp_path, offline, capsys):
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
    assert result["status"] == "partial" and result["review_status"] == "no_baseline"
    assert verify_review(result["review_bundle"])["status"] == "verified"
    assert "خلاصهٔ تغییرات" in Path(result["summary"]).read_text(encoding="utf-8")


def test_cli_refresh_review_failure_still_returns_completed_report(
    tmp_path, offline, capsys, monkeypatch
):
    def fail(*_):
        raise OSError("secret exception text")

    monkeypatch.setattr(cli, "write_refresh_review", fail)
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
    assert result["review_status"] == "failed" and result["review_failure_type"] == "OSError"
    assert result["report_status"] == "succeeded" and Path(result["bundle"]).is_dir()
    assert "secret" not in json.dumps(result)


def test_changed_generation_clock_does_not_change_review_fingerprint(workflow):
    run, folder, baseline, _ = workflow
    _, _, after = load_verified_report(folder / run.report.bundle)
    raw = (folder / "refresh-run.json").read_bytes()
    now = datetime.now(UTC)
    one = build_review(raw, after, baseline, now)
    two = build_review(raw, after, baseline, now + timedelta(seconds=1))
    assert one.fingerprint == two.fingerprint


def test_legacy_schema_absence_is_reviewed_separately_from_missing_data(workflow):
    _, folder, _, _ = workflow
    legacy = Path("tests/fixtures/report-v1/before.json").read_bytes()
    review, output = write_refresh_review(folder, Baseline("selected", legacy))
    assert review.status == "compared"
    assert any(
        p.code == "SCHEMA_INCOMPARABLE" and p.subject == "positioning" for p in review.priorities
    )
    assert not any(row.section == "positioning" for row in review.comparison.changes)
    assert verify_review(output)["status"] == "verified"


def test_second_cli_refresh_uses_preexisting_verified_baseline(tmp_path, offline, capsys):
    arguments = [
        "--store",
        str(tmp_path / "store"),
        "refresh-report",
        "--output-dir",
        str(tmp_path / "out"),
    ]
    assert cli.main(arguments) == 3
    first = json.loads(capsys.readouterr().out)
    assert cli.main(arguments) == 3
    second = json.loads(capsys.readouterr().out)
    assert second["review_status"] == "compared"
    saved = json.loads((Path(second["review_bundle"]) / "review.json").read_bytes())
    assert (
        saved["comparison"]["before"]["fingerprint"]
        == load_verified_report(first["bundle"])[0].fingerprint
    )
    assert verify_review(second["review_bundle"])["status"] == "verified"


def pair_review(run, before, after):
    # Invented trace clocks for testing report semantics, not a live acquisition claim.
    data = run.model_dump(mode="json")
    data["started_at"] = before.as_of.isoformat()
    data["report"].update(
        as_of=after.as_of.isoformat(),
        fingerprint=after.fingerprint,
        research_status=after.status,
        calendar_status=after.calendar.status,
        freshness=[row.model_dump(mode="json") for row in report_freshness(after)],
    )
    from gold_intelligence.refresh import RefreshRun

    traced = RefreshRun.model_validate(data)
    data["status"] = completed_status(traced.steps, traced.report)
    return build_review(
        json.dumps(data).encode(),
        after.model_dump_json().encode(),
        Baseline("selected", before.model_dump_json().encode()),
    )


@pytest.mark.parametrize("mode", ["unchanged", "settings", "age", "recapture", "value"])
def test_report_semantics_flow_through_existing_comparator(
    workflow, store, registry, settings, mode
):
    run, _, _, _ = workflow
    fred(store, registry, vintage=None, retrieved=ASOF)
    before = build_research_report(store, registry, settings, ASOF)
    after = before
    if mode == "settings":

        def update(data):
            data["settings"]["calendar_horizon_days"] = 10
            data["calendar"]["horizon_days"] = 10

        after = edit(before, update)
    elif mode in {"age", "recapture", "value"}:
        later = ASOF + timedelta(hours=1)
        if mode == "recapture":
            fred(store, registry, vintage=None, retrieved=later)
        elif mode == "value":
            fred(
                store,
                registry,
                [("2024-01-01", 100), ("2024-02-01", 103)],
                vintage=None,
                retrieved=later,
            )
        after = build_research_report(store, registry, settings, later)
    review = pair_review(run, before, after)
    assert review.status == "compared"
    if mode == "unchanged":
        assert review.comparison.status == "unchanged" and not any(review.field_counts.values())
    elif mode == "settings":
        assert review.comparison.status == "context_only"
        assert not any(review.field_counts.values())
    elif mode == "age":
        assert review.field_counts["age"] > 0 and review.field_counts["evidence"] == 0
    else:
        assert review.field_counts["evidence"] > 0
    macro_value_fields = [
        field
        for row in review.comparison.changes
        if row.section == "macro" and row.collection == "entries"
        for field in row.fields
        if field.path == "/value"
    ]
    assert bool(macro_value_fields) == (mode == "value")
