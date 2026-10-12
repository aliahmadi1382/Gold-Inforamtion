"""Compare fixed signal-only policies; never relax the paper execution default."""

from .real_shadow import ShadowSettings, evaluate_shadow


def compare_signal_profiles(root, *, excluded_capture_ids=()):
    profiles = {
        "strict_execution_screen": ShadowSettings(),
        "delayed_observation_research": ShadowSettings(
            maximum_age_seconds=900, maximum_gap_seconds=4 * 86400
        ),
    }
    results = {}
    for name, settings in profiles.items():
        report = evaluate_shadow(root, settings, excluded_capture_ids=excluded_capture_ids)
        decisions = report["decisions"]
        results[name] = dict(
            report=report,
            blocked_count=sum(d["signal"] == "blocked" for d in decisions),
            warming_up_count=sum(d["reason"] == "warming_up" for d in decisions),
            candidate_count=sum(
                d["signal"] in {"buy_candidate", "exit_candidate"} for d in decisions
            ),
        )
    return dict(
        schema_version="1.0.0",
        experiment_id="fixed-delayed-signal-comparison-1",
        scope="offline_signal_policy_comparison_only",
        fixed_profiles=results,
        execution_policy_changed=False,
        orders_enabled=False,
        market_validation=False,
        synthetic=False,
        prospective_validation=False,
        limitation="Defined after inspecting two observations; no out-of-sample claim.",
    )
