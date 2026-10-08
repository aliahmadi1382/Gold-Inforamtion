"""Versioned draft event-study protocol; a plan cannot certify data or enable execution."""

import hashlib

from .daily_readiness import build_daily_readiness
from .storage import canonical


def build_event_study_plan(content):
    readiness = build_daily_readiness(content)
    protocol = dict(
        version="event-study-draft-1",
        status="draft_not_preregistered",
        events=["CPI", "Employment Situation"],
        primary_question=(
            "Descriptive gold close-to-close responses around verified release events."
        ),
        event_time="Verified actual first-publication availability in UTC; no assumed 08:30 clock.",
        price_stream="One approved instrument, methodology and source per study; never pooled.",
        primary_response=(
            "100 * (first_verified_session_close_after_event / "
            "last_verified_session_close_before_event - 1)"
        ),
        secondary_response=(
            "100 * (second_verified_session_close_after_event / "
            "last_verified_session_close_before_event - 1)"
        ),
        calendar_policy=(
            "Verified source session calendar, holidays and timezone history; no weekend fill."
        ),
        availability_policy=(
            "Preserve reference/session time, first-publication time and retrieval separately."
        ),
        data_policy=(
            "Reject ambiguous timestamps, conflicting same-session prices and method boundaries."
        ),
        overlap_policy=(
            "Exclude windows containing another included event; record both event IDs and reason."
        ),
        sample_policy=(
            "At least 36 eligible events per family for descriptive summaries; "
            "not a power guarantee."
        ),
        minimum_eligible_events_per_family=36,
        missing_policy=(
            "Record every candidate and exclusion; no imputation or silent event deletion."
        ),
        descriptive_outputs=[
            "eligible events and exclusions",
            "mean and median response",
            "empirical response quartiles",
            "exact event-window ledger",
        ],
        temporal_design=dict(
            development="2012-01-01/2018-12-31",
            evaluation="2019-01-01/2024-12-31",
            rule=(
                "Freeze definitions after development; do not tune on evaluation. "
                "These are draft ranges, not fitted results."
            ),
        ),
        forecasting_scope=(
            "Not specified or executed by this event-response plan; requires a "
            "separate versioned target, decision-time features and out-of-sample "
            "protocol."
        ),
        limitations=[
            "Daily closes do not isolate an intraday announcement reaction.",
            (
                "Event responses are not causal effects or forecast surprises; no "
                "consensus data is assumed."
            ),
            "Response quartiles are dispersion, not confidence intervals.",
            "No strategy, trading costs, executable profit or historical-access certification.",
            "A draft made after examining other project data is not proof of preregistration.",
        ],
    )
    return dict(
        schema_version="1.0.0",
        report_fingerprint=readiness.report_fingerprint,
        report_sha256=readiness.input_sha256,
        as_of=readiness.as_of.isoformat(),
        protocol_sha256=hashlib.sha256(canonical(protocol).encode()).hexdigest(),
        protocol=protocol,
        status="planning_only",
        study_executed=False,
        daily_backtest_ready=False,
        forecasting_test=False,
        requirements=[r.model_dump(mode="json") for r in readiness.requirements],
        execution_steps=[
            "Approve source methodology and storage rights; obtain historical session calendar.",
            "Validate event archive, original values and actual first-publication timestamps.",
            (
                "Build candidate ledger and price windows; audit every exclusion and "
                "overlapping event."
            ),
            (
                "Review development sample, freeze a new protocol version and inspect "
                "evaluation separately."
            ),
            (
                "Publish descriptive results only after independent window, timestamp "
                "and arithmetic checks."
            ),
        ],
    )
