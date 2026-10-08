import hashlib
import json

import pytest
from test_daily_readiness import report_bytes
from test_research_report import settings as settings

from gold_intelligence.event_study_plan import build_event_study_plan
from gold_intelligence.evidence_synthesis import resolve_pointer
from gold_intelligence.storage import canonical


def test_empty_report_draft_cannot_grant_execution_and_all_evidence_is_bound(
    store, registry, settings
):
    content = report_bytes(store, registry, settings)
    result = build_event_study_plan(content)
    assert result["status"] == "planning_only"
    assert not result["study_executed"] and not result["daily_backtest_ready"]
    assert not result["forecasting_test"]
    assert result["report_sha256"] == hashlib.sha256(content).hexdigest()
    assert (
        result["protocol_sha256"]
        == hashlib.sha256(canonical(result["protocol"]).encode()).hexdigest()
    )
    assert result["protocol"]["status"] == "draft_not_preregistered"
    for requirement in result["requirements"]:
        for pointer in requirement["pointers"]:
            resolve_pointer(json.loads(content), pointer)
    result["protocol"]["events"].append("altered")
    assert build_event_study_plan(content)["protocol"]["events"] == ["CPI", "Employment Situation"]


def test_false_source_readiness_is_rejected_instead_of_turning_plan_into_results(
    store, registry, settings
):
    data = json.loads(report_bytes(store, registry, settings))
    data["daily_backtest_ready"] = True
    with pytest.raises(ValueError):
        build_event_study_plan(json.dumps(data).encode())
