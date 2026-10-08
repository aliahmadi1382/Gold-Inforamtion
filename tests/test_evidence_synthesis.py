import hashlib
import json
from datetime import date, timedelta

import pytest
from test_monthly_research import CUTOFF, seed
from test_monthly_research import make_observation as make_observation
from test_release_values import fred, insert
from test_research_report import ASOF
from test_research_report import settings as settings

from gold_intelligence.cli import main
from gold_intelligence.evidence_synthesis import (
    EvidenceSynthesis,
    association_outcome,
    build_synthesis,
    resolve_pointer,
    verify_synthesis,
    write_synthesis,
)
from gold_intelligence.monthly_research import Association
from gold_intelligence.research_report import build_research_report, write_research_report


def empty_report(store, registry, settings):
    return build_research_report(store, registry, settings, ASOF)


def test_empty_evidence_does_not_claim_market_direction(store, registry, settings):
    report = empty_report(store, registry, settings)
    content = report.model_dump_json().encode()
    synthesis = build_synthesis(content)
    assert synthesis.status == "no_evidence"
    assert synthesis.market_direction == "not_inferred"
    assert synthesis.confidence_probability is None and not synthesis.daily_backtest_ready
    assert synthesis.outcome_counts["not_comparable"] == 0
    data = json.loads(content)
    for finding in synthesis.findings:
        for pointer in finding.pointers:
            resolve_pointer(data, pointer)


@pytest.mark.parametrize(
    "vintage,expected", [(100.1, "matches_display"), (100.4, "vintage_disagreement")]
)
def test_release_vintage_disagreement_is_separate_from_revision(
    store, registry, settings, vintage, expected
):
    insert(store, registry)
    fred(store, registry, [("2023-12-01", 100), ("2024-01-01", vintage)])
    fred(store, registry, [("2023-12-01", 100), ("2024-01-01", 100.3)], vintage=None)
    report = empty_report(store, registry, settings)
    synthesis = build_synthesis(report.model_dump_json().encode())
    release = [f for f in synthesis.findings if f.category == "release"]
    assert [f.outcome for f in release] == [expected, "revision_difference"]
    assert release[0].facts["document_value"] == 0.1
    assert release[0].facts["transformation"] == "100*(current_CPI/prior_CPI-1)"
    assert release[0].facts["record_ids"]
    assert synthesis.status == ("needs_review" if expected == "vintage_disagreement" else "limited")


def test_missing_vintage_remains_missing(store, registry, settings):
    insert(store, registry)
    synthesis = build_synthesis(empty_report(store, registry, settings).model_dump_json().encode())
    assert synthesis.outcome_counts["missing_period"] == 2
    assert all(
        f.facts["compared_value"] is None for f in synthesis.findings if f.category == "release"
    )


@pytest.mark.parametrize(
    "p,s,status,n,expected",
    [
        (0.5, 0.4, "estimated", 3, "method_concordance"),
        (-0.5, -0.4, "estimated", 3, "method_concordance"),
        (-0.5, 0.4, "estimated", 3, "method_disagreement"),
        (0.0, 0.4, "estimated", 3, "method_disagreement"),
        (None, None, "too_short", 3, "insufficient_sample"),
        (0.5, 0.4, "estimated", 2, "insufficient_sample"),
    ],
)
def test_method_comparison_has_no_direction_vote(p, s, status, n, expected):
    association = Association(
        series_id="DGS10",
        population="common",
        method="test",
        months=tuple(date(2024, i + 1, 1) for i in range(n)),
        n=n,
        status=status,
        pearson=p,
        spearman=s,
    )
    assert association_outcome(association, 3) == expected


def test_monthly_evidence_preserves_source_method_sample(
    store, registry, settings, make_observation
):
    seed(store, make_observation)
    report = build_research_report(store, registry, settings, CUTOFF)
    synthesis = build_synthesis(report.model_dump_json().encode())
    findings = [f for f in synthesis.findings if f.category == "monthly"]
    common = [a for a in report.monthly.associations if a.population == "common"]
    assert len(findings) == len(common)
    for finding, association in zip(findings, common, strict=True):
        assert finding.facts["method"] == association.method
        assert finding.facts["months"] == [str(m) for m in association.months]
        assert finding.facts["pearson"] == association.pearson
        assert finding.sources == ("world_bank_pink_sheet", "fred")


def test_synthesis_clock_does_not_change_fingerprint(store, registry, settings):
    content = empty_report(store, registry, settings).model_dump_json().encode()
    one = build_synthesis(content, generated_at=ASOF)
    two = build_synthesis(content, generated_at=ASOF + timedelta(days=1))
    assert one.fingerprint == two.fingerprint and one.generated_at != two.generated_at


@pytest.mark.parametrize("damage", ["bytes", "rehash_claim", "prose", "duplicate", "path", "input"])
def test_self_contained_bundle_recomputes_and_rejects_false_evidence(
    store, registry, settings, tmp_path, damage
):
    report_dir = write_research_report(empty_report(store, registry, settings), tmp_path / "report")
    _, directory = write_synthesis(report_dir, tmp_path / "synthesis")
    assert verify_synthesis(directory)["status"] == "verified"
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    if damage == "duplicate":
        manifest["files"].append(manifest["files"][0])
    elif damage == "path":
        manifest["files"][0]["path"] = "../private.json"
    else:
        name = {
            "bytes": "synthesis.json",
            "rehash_claim": "synthesis.json",
            "prose": "synthesis.fa.md",
            "input": "inputs/research.json",
        }[damage]
        path = directory / name
        if damage == "rehash_claim":
            data = json.loads(path.read_bytes())
            data["findings"][0]["facts"]["n"] = 999
            from gold_intelligence.storage import canonical

            # Even a self-consistent forged fingerprint must fail rule recomputation.
            payload = {k: v for k, v in data.items() if k not in {"fingerprint", "generated_at"}}
            data["fingerprint"] = hashlib.sha256(canonical(payload).encode()).hexdigest()
            EvidenceSynthesis.model_validate(data)
            manifest["fingerprint"] = data["fingerprint"]
            path.write_text(json.dumps(data))
        elif damage == "input":
            data = json.loads(path.read_bytes())
            data["fingerprint"] = "0" * 64
            path.write_text(json.dumps(data))
        else:
            path.write_bytes(path.read_bytes() + b" ")
        if damage != "bytes":
            for item in manifest["files"]:
                if item["path"] == name:
                    item["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                    item["bytes"] = len(path.read_bytes())
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        verify_synthesis(directory)


def test_offline_cli_does_not_initialize_store(store, registry, settings, tmp_path):
    directory = write_research_report(empty_report(store, registry, settings), tmp_path / "report")
    missing = tmp_path / "missing"
    assert (
        main(
            [
                "--store",
                str(missing),
                "synthesize-report",
                str(directory),
                "--output-dir",
                str(tmp_path / "synthesis"),
            ]
        )
        == 0
    )
    assert not missing.exists()
    bundle = next((tmp_path / "synthesis").glob("synthesis-*"))
    assert main(["--store", str(missing), "verify-synthesis", str(bundle)]) == 0


def test_contract_rejects_forged_counts_and_direction(store, registry, settings):
    data = build_synthesis(
        empty_report(store, registry, settings).model_dump_json().encode()
    ).model_dump(mode="json")
    data["market_direction"] = "bullish"
    with pytest.raises(ValueError):
        EvidenceSynthesis.model_validate(data)
    data["market_direction"] = "not_inferred"
    data["outcome_counts"]["no_evidence"] = 999
    with pytest.raises(ValueError):
        EvidenceSynthesis.model_validate(data)


def test_legacy_schema_does_not_invent_positioning():
    from test_positioning_integration import LEGACY

    content = (LEGACY / "before.json").read_bytes()
    result = build_synthesis(content)
    periods = next(f for f in result.findings if f.id == "comparability:periods")
    assert "cftc_disaggregated" not in periods.sources
    assert periods.facts["cot_reference"] is None
    assert all("/positioning" not in p for f in result.findings for p in f.pointers)
