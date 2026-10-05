"""Invented archive documents and native FRED payloads; no live requests."""

import json
import runpy
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import validate as validate_schema
from test_release_values import bundle, fred, insert

from gold_intelligence.cli import main
from gold_intelligence.revision_ledger import (
    RevisionPlan,
    load_revision_plan,
    render_revision_ledger,
    revision_ledger,
)
from gold_intelligence.storage import record_id

CAPTURE = datetime(2024, 4, 15, tzinfo=UTC)
ASOF = CAPTURE + timedelta(days=1)
CPI = "cpi_all_items_sa_mom"
UNRATE = "unemployment_rate_sa"


def plan(**changes):
    return RevisionPlan.model_validate(
        dict(
            declared_at="2024-04-01T00:00:00Z",
            start_period="2024-01",
            end_period="2024-01",
            metrics=[CPI],
            selection_reason="Invented fixed-window test",
            **changes,
        )
    )


def document(month=1, value=0.1, prior=0.1, **changes):
    period = f"2024-{month:02d}"
    unit = "percent_change_mom_sa"
    values = [
        dict(
            reference_period=period,
            value=value,
            unit=unit,
            locator="Invented headline cell",
            review_note="Fictional test data",
        )
    ]
    if month > 1 and prior is not None:
        values.append(
            dict(
                reference_period=f"2024-{month - 1:02d}",
                value=prior,
                unit=unit,
                locator="Invented previous cell",
                review_note="Fictional test data",
            )
        )
    data = bundle(
        captured_at=CAPTURE.isoformat(),
        headline_period=period,
        source_url=f"https://www.bls.gov/news.release/archives/cpi_0{month + 1}092024.htm",
        announced_at=f"2024-{month + 1:02d}-09T08:30:00-05:00",
        values=values,
    )
    data.update(changes)
    return data


def add(store, registry, data=None, retrieved=ASOF):
    return insert(store, registry, data or document(), retrieved=retrieved)


def vintages(store, registry, after=100.1, *, current=False):
    for vintage, value in [(date(2024, 2, 9), 100.1), (date(2024, 3, 9), after)]:
        fred(
            store,
            registry,
            [("2023-12-01", 100), ("2024-01-01", value)],
            vintage=None if current else vintage,
            retrieved=ASOF,
        )


def test_complete_pair_lineage_and_exact_vintages(store, registry):
    first = add(store, registry)
    second = add(store, registry, document(2, prior=0.3))
    vintages(store, registry, after=100.3)
    report = revision_ledger(store, registry, plan(), ASOF)
    pair = report.pairs[0]
    assert report.status == "complete"
    assert report.expected_pairs == report.compared_pairs == report.vintage_matched_pairs == 1
    assert report.changed_display_pairs == 1
    assert pair.difference_pp == 0.2
    assert pair.vintage_difference_pp == pytest.approx(0.2)
    assert pair.before.record_id == record_id(first[0])
    assert pair.after.record_id == record_id(second[1])
    assert pair.before_vintage.vintage_date == date(2024, 2, 9)
    assert pair.after_vintage.vintage_date == date(2024, 3, 9)
    assert len(pair.before_vintage.record_ids) == len(pair.after_vintage.record_ids) == 2
    assert not report.first_release_verified and not report.intraday_replay_ready
    assert report.capture_changes == ()


def test_equal_at_display_precision_does_not_require_unrounded_equality(store, registry):
    add(store, registry)
    add(store, registry, document(2))
    vintages(store, registry, after=100.14)
    report = revision_ledger(store, registry, plan(), ASOF)
    assert report.status == "complete"
    assert report.pairs[0].difference_pp == 0
    assert report.pairs[0].vintage_difference_pp == pytest.approx(0.04)
    assert report.changed_display_pairs == 0
    text = render_revision_ledger(report)
    assert "دقت یک رقم اعشار" in text and "نتیجه‌ای نداریم" in text


def test_empty_store_keeps_declared_denominator_and_boundary_month(store, registry):
    p = load_revision_plan(Path("config/revision_ledger.yaml"))
    report = revision_ledger(store, registry, p, ASOF)
    assert report.expected_pairs == 12 and len(report.document_slots) == 14
    assert report.compared_pairs == 0 and report.status == "no_evidence"
    assert all(row.status == "missing_document" for row in report.pairs)
    assert all(row.difference_pp is None for row in report.pairs)
    assert report.document_slots[-1].headline_period == "2020-07"


@pytest.mark.parametrize("missing", [1, 2])
def test_missing_document_is_not_zero_or_substituted(store, registry, missing):
    add(store, registry, document(3 - missing))
    report = revision_ledger(store, registry, plan(), ASOF)
    pair = report.pairs[0]
    assert pair.status == "missing_document" and pair.difference_pp is None
    assert (pair.before is None) == (missing == 1)
    assert (pair.after is None) == (missing == 2)
    assert report.compared_pairs == 0


def test_new_capture_drops_previous_value_without_resurrection(store, registry):
    add(store, registry)
    original = document(2)
    add(store, registry, original)
    add(
        store,
        registry,
        document(2, prior=None, captured_at=(CAPTURE + timedelta(hours=1)).isoformat()),
    )
    add(store, registry, original, retrieved=ASOF + timedelta(days=1))
    report = revision_ledger(store, registry, plan(), ASOF + timedelta(days=1))
    assert report.pairs[0].status == "missing_previous_value"
    assert report.pairs[0].after is None
    assert report.capture_changes[0].status == "removed"
    assert len(report.captures) == 3
    add(
        store,
        registry,
        document(2, prior=0.2, captured_at=(CAPTURE + timedelta(hours=2)).isoformat()),
        retrieved=ASOF + timedelta(days=2),
    )
    restored = revision_ledger(store, registry, plan(), ASOF + timedelta(days=2))
    assert [c.status for c in restored.capture_changes] == ["removed", "added"]
    assert restored.pairs[0].after.value == 0.2


@pytest.mark.parametrize(
    "old,new,status,delta",
    [
        (0.1, 0.3, "changed_display", 0.2),
        (0.1, 0.1, "unchanged_display", 0.0),
        (None, 0.1, "added", None),
    ],
)
def test_same_url_capture_history_is_separate(store, registry, old, new, status, delta):
    add(store, registry)
    add(store, registry, document(2, prior=old))
    add(
        store,
        registry,
        document(2, prior=new, captured_at=(CAPTURE + timedelta(hours=1)).isoformat()),
    )
    report = revision_ledger(store, registry, plan(), ASOF)
    assert len(report.capture_changes) == 1
    change = report.capture_changes[0]
    assert change.status == status and change.difference_pp == delta
    assert change.before_capture_id != change.after_capture_id
    assert report.pairs[0].after.value == new


def test_asof_excludes_later_ingestion_even_when_header_and_capture_are_old(store, registry):
    add(store, registry)
    add(store, registry, document(2), retrieved=ASOF + timedelta(days=1))
    report = revision_ledger(store, registry, plan(), ASOF)
    assert report.pairs[0].status == "missing_document"
    assert len(report.captures) == 1
    assert revision_ledger(store, registry, plan(), CAPTURE).status == "no_evidence"


def test_two_urls_for_one_headline_are_ambiguous_even_with_equal_values(store, registry):
    add(store, registry)
    add(
        store,
        registry,
        document(
            source_url="https://www.bls.gov/news.release/archives/cpi_02102024.htm",
            announced_at="2024-02-10T08:30:00-05:00",
        ),
    )
    add(store, registry, document(2))
    report = revision_ledger(store, registry, plan(), ASOF)
    assert report.document_slots[0].status == "ambiguous"
    assert len(report.document_slots[0].candidate_capture_ids) == 2
    assert report.pairs[0].status == "ambiguous_document"
    assert report.pairs[0].before is None
    assert report.pairs[0].difference_pp is None


def test_conflicting_same_capture_fails(store, registry):
    add(store, registry)
    add(store, registry, document(value=0.2))
    with pytest.raises(ValueError, match="conflicting same-capture"):
        revision_ledger(store, registry, plan(), ASOF)


def test_identity_drift_at_same_url_fails(store, registry):
    add(store, registry)
    add(
        store,
        registry,
        document(release_id="USDL-24-8888", captured_at=(CAPTURE + timedelta(hours=1)).isoformat()),
    )
    with pytest.raises(ValueError, match="conflicting release identities"):
        revision_ledger(store, registry, plan(), ASOF)


def test_invalid_document_chronology_does_not_compute_delta(store, registry):
    add(
        store,
        registry,
        document(
            source_url="https://www.bls.gov/news.release/archives/cpi_04092024.htm",
            announced_at="2024-04-09T08:30:00-04:00",
        ),
    )
    add(store, registry, document(2))
    report = revision_ledger(store, registry, plan(), ASOF)
    assert report.pairs[0].status == "invalid_document_order"
    assert report.pairs[0].difference_pp is report.pairs[0].vintage_difference_pp is None


def test_reissued_archives_preserve_notes_without_certifying_first_release(store, registry):
    add(
        store,
        registry,
        document(
            document_status="reissued",
            reissued_on="2024-03-01",
            revision_note="Fictional correction notice",
        ),
    )
    add(store, registry, document(2))
    vintages(store, registry)
    report = revision_ledger(store, registry, plan(), ASOF)
    assert report.status == "complete" and not report.first_release_verified
    assert "Fictional correction notice" in render_revision_ledger(report)


@pytest.mark.parametrize("after", [None, 100.3])
def test_missing_or_mismatched_fred_vintage_is_incomplete(store, registry, after):
    add(store, registry)
    add(store, registry, document(2))
    if after is not None:
        vintages(store, registry, after=after)
    report = revision_ledger(store, registry, plan(), ASOF)
    assert report.compared_pairs == 1 and report.vintage_matched_pairs == 0
    assert report.status == "incomplete"


def test_current_fred_values_never_fill_missing_vintage(store, registry):
    add(store, registry)
    add(store, registry, document(2))
    fred(store, registry, vintage=None, retrieved=ASOF)
    pair = revision_ledger(store, registry, plan(), ASOF).pairs[0]
    assert pair.before_vintage.status == pair.after_vintage.status == "missing_period"


def test_metric_isolation_and_native_unemployment_units(store, registry):
    add(store, registry)
    add(store, registry, document(2))
    for month, day, value in [(1, "2024-02-09", 4.2), (2, "2024-03-09", 4.3)]:
        payload = document(month, value=value, prior=4.3)
        payload["metric"] = UNRATE
        payload["source_url"] = payload["source_url"].replace("cpi_", "empsit_")
        for entry in payload["values"]:
            entry["unit"] = "percent_sa"
        add(store, registry, payload)
        fred(
            store,
            registry,
            [("2024-01-01", value)],
            series="UNRATE",
            vintage=date.fromisoformat(day),
            retrieved=ASOF,
        )
    data = plan().model_dump()
    data["metrics"] = [UNRATE]
    report = revision_ledger(store, registry, RevisionPlan.model_validate(data), ASOF)
    assert report.status == "complete" and len(report.captures) == 2
    assert report.pairs[0].difference_pp == 0.1
    assert report.pairs[0].before.unit == "percent_sa"


def test_integrity_is_checked_before_comparison(store, registry):
    rows = add(store, registry)
    path = store.root / "raw" / rows[0].provenance.raw_sha256
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="raw hash mismatch"):
        revision_ledger(store, registry, plan(), ASOF)


def test_fingerprint_is_stable_and_scope_sensitive(store, registry):
    add(store, registry)
    first = revision_ledger(store, registry, plan(), ASOF)
    assert first.fingerprint == revision_ledger(store, registry, plan(), ASOF).fingerprint
    data = plan().model_dump()
    data["end_period"] = "2024-02"
    assert (
        first.fingerprint
        != revision_ledger(store, registry, RevisionPlan.model_validate(data), ASOF).fingerprint
    )


@pytest.mark.parametrize(
    "change",
    [
        {"start_period": "2024-13"},
        {"end_period": "2023-12"},
        {"end_period": "2034-01"},
        {"metrics": [CPI, CPI]},
        {"metrics": []},
        {"declared_at": "2024-04-01T00:00:00"},
    ],
)
def test_invalid_plans_fail(change):
    payload = plan().model_dump()
    payload.update(change)
    with pytest.raises(ValueError):
        RevisionPlan.model_validate(payload)


def test_cli_empty_report_and_schema_roundtrip(tmp_path, capsys):
    args = [
        "--store",
        str(tmp_path / "empty"),
        "revision-ledger",
        "--as-of",
        ASOF.isoformat(),
        "--output-dir",
        str(tmp_path / "reports"),
    ]
    assert main(args) == 3
    result = json.loads(capsys.readouterr().out)
    assert result["expected_pairs"] == 12
    assert (tmp_path / "reports/revision-ledger.fa.md").exists()
    assert (tmp_path / "reports/revision-ledger.json").exists()
    validate_schema(
        json.loads((tmp_path / "reports/revision-ledger.json").read_text(encoding="utf-8")),
        json.loads(Path("schemas/revision_ledger.schema.json").read_text(encoding="utf-8")),
    )


@pytest.mark.parametrize("field", ["difference_pp", "vintage_value"])
def test_independent_checker_accepts_raw_arithmetic_and_rejects_tampered_report(
    store, registry, tmp_path, field
):
    add(store, registry)
    add(store, registry, document(2, prior=0.3))
    vintages(store, registry, after=100.3)
    report = revision_ledger(store, registry, plan(), ASOF)
    path = tmp_path / "ledger.json"
    path.write_text(report.model_dump_json(), encoding="utf-8")
    check = runpy.run_path("scripts/inspect_revision_ledger.py")["validate"]
    assert check(store.root, path)["status"] == "verified"
    data = json.loads(path.read_text(encoding="utf-8"))
    if field == "difference_pp":
        data["pairs"][0][field] = 0.9
    else:
        data["pairs"][0]["before_vintage"]["value"] = 0.9
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="numeric reconciliation"):
        check(store.root, path)
