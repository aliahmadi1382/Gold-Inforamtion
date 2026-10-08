import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import validate
from test_alpha_vantage import parse
from test_research_report import ASOF
from test_research_report import settings as settings

from gold_intelligence.cli import main
from gold_intelligence.daily_readiness import DailyReadiness, build_daily_readiness
from gold_intelligence.evidence_synthesis import resolve_pointer
from gold_intelligence.research_report import build_research_report, write_research_report


def report_bytes(store, registry, settings):
    return build_research_report(store, registry, settings, ASOF).model_dump_json().encode()


def test_empty_report_absence_is_not_confirmation(store, registry, settings):
    content = report_bytes(store, registry, settings)
    result = build_daily_readiness(content)
    assert result.status == "blocked" and result.daily_backtest_ready is False
    assert [r.status for r in result.requirements[:3]] == ["not_assessed"] * 3
    assert result.input_sha256 == hashlib.sha256(content).hexdigest()
    validate(
        result.model_dump(mode="json"),
        json.loads(Path("schemas/daily_readiness.schema.json").read_bytes()),
    )
    for requirement in result.requirements:
        for pointer in requirement.pointers:
            resolve_pointer(json.loads(content), pointer)


def test_date_only_weekend_and_inferred_unit_keep_actual_stream_counts(store, registry, settings):
    store.put(parse(store, registry))
    content = report_bytes(store, registry, settings)
    result = build_daily_readiness(content)
    assert [r.status for r in result.requirements[:3]] == ["needs_evidence"] * 3
    for check in result.requirements[:3]:
        stream = check.facts["streams"][0]
        assert stream["date_only_prices"] == 2 and stream["weekend_date_labels"] == 1
        assert (
            resolve_pointer(json.loads(content), check.pointers[0])["stream_id"]
            == stream["stream_id"]
        )
    assert store.audit()["records"] == 2


def test_absent_price_warnings_never_certify_methodology(store, registry, settings, monkeypatch):
    from gold_intelligence import research_report

    store.put(parse(store, registry))
    original = research_report.assess

    def unrelated(*args, **kwargs):
        quality = original(*args, **kwargs)
        return quality.model_copy(
            update={
                "issues": tuple(
                    issue.model_copy(update={"stream_id": None}) for issue in quality.issues
                )
            }
        )

    monkeypatch.setattr(research_report, "assess", unrelated)
    result = build_daily_readiness(report_bytes(store, registry, settings))
    assert not result.daily_backtest_ready
    assert all(r.status == "not_assessed" for r in result.requirements[:3])


@pytest.mark.parametrize("damage", ["ready", "missing", "duplicate", "promoted", "corrupt_input"])
def test_forged_readiness_and_incomplete_checklists_rejected(store, registry, settings, damage):
    content = report_bytes(store, registry, settings)
    data = build_daily_readiness(content).model_dump(mode="json")
    if damage == "corrupt_input":
        source = json.loads(content)
        source["first_release_verified"] = True
        with pytest.raises(ValueError):
            build_daily_readiness(json.dumps(source).encode())
        return
    if damage == "ready":
        data["daily_backtest_ready"] = True
    elif damage == "missing":
        data["requirements"].pop()
    elif damage == "duplicate":
        data["requirements"][1] = data["requirements"][0]
    else:
        data["requirements"][0]["status"] = "verified"
    with pytest.raises(ValueError):
        DailyReadiness.model_validate(data)


def test_cli_saved_bundle_without_store_or_registry(store, registry, settings, tmp_path, capsys):
    report = build_research_report(store, registry, settings, ASOF)
    directory = write_research_report(report, tmp_path / "reports")
    absent = tmp_path / "absent"
    assert (
        main(["--store", str(absent), "--registry", "missing", "daily-readiness", str(directory)])
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["report_fingerprint"] == report.fingerprint
    assert not absent.exists()


def test_legacy_report_keeps_existing_cutoff_and_unverified_first_release():
    content = Path("tests/fixtures/report-v1/before.json").read_bytes()
    result = build_daily_readiness(content)
    assert result.requirements[3].facts["first_release_verified"] is False
    assert result.report_fingerprint == json.loads(content)["fingerprint"]
