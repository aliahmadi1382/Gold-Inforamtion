"""Protocol-bound daily signal review, separate from pilot and execution datasets."""

from pathlib import Path

from .daily_status import daily_status
from .delayed_research import compare_signal_profiles


def review_daily_research(root, now):
    status = daily_status(root, now)
    result = dict(
        schema_version="1.0.0",
        protocol_status=status,
        scope="protocol_bound_daily_signal_research",
        synthetic=False,
        orders_enabled=False,
        market_validation=False,
        performance_conclusion="not_established",
        status="unavailable",
        current_eligible_history=None,
        observations_needed_before_first_comparison=None,
        comparison=None,
    )
    if status["status"] != "verified":
        return result
    if status["verified_daily_observations"] == 0:
        result.update(
            status="awaiting_daily_observations",
            current_eligible_history=0,
            observations_needed_before_first_comparison=21,
        )
        return result
    try:
        comparison = compare_signal_profiles(
            Path(root) / "quotes",
            excluded_capture_ids=[f["capture_id"] for f in status["recorded_failures"]],
        )
        profile = comparison["fixed_profiles"]["delayed_observation_research"]
        report = profile["report"]
        # Bind recomputation to the exact dataset already reviewed against reservations.
        if report["input_dataset"] != status["coverage"]:
            raise ValueError
        last = report["decisions"][-1]
        history = last["prior_eligible_observations"] + (last["signal"] != "blocked")
        needed = max(0, report["settings"]["lookback"] + 1 - history)
        result.update(
            status="gathering_history" if needed else "signal_comparisons_available",
            current_eligible_history=history,
            observations_needed_before_first_comparison=needed,
            comparison=comparison,
        )
    except (ValueError, OSError):
        return result
    return result
