"""Offline sample and single-month sensitivity diagnostics, never confidence intervals."""

from .monthly_research import DRIVERS, REGIMES, SPECS, coefficients, shift_month
from .world_bank import SERIES


def monthly_robustness(report):
    study = report.monthly
    comparisons, influence, rolling = [], [], []
    associations = {(a.method, a.series_id, a.population): a for a in study.associations}
    for method in REGIMES:
        common = [
            r
            for r in study.changes
            if r.method == method and all(r.values[s] is not None for s in SPECS)
        ]
        for series in DRIVERS:
            pair = associations.get((method, series, "pairwise"))
            shared = associations.get((method, series, "common"))
            if pair and shared:
                comparisons.append(
                    dict(
                        method=method,
                        series_id=series,
                        pairwise_n=pair.n,
                        common_n=shared.n,
                        pairwise_pearson=pair.pearson,
                        common_pearson=shared.pearson,
                        pairwise_spearman=pair.spearman,
                        common_spearman=shared.spearman,
                        additional_pairwise_months=[
                            m.isoformat() for m in pair.months if m not in shared.months
                        ],
                    )
                )
            removals = []
            if len(common) - 1 >= study.plan.minimum_pairs:
                for index, removed in enumerate(common):
                    sample = common[:index] + common[index + 1 :]
                    p, s = coefficients(
                        [r.values[SERIES] for r in sample], [r.values[series] for r in sample]
                    )
                    removals.append(
                        dict(
                            removed_month=removed.month.isoformat(),
                            n=len(sample),
                            pearson=p,
                            spearman=s,
                        )
                    )
            defined = [r for r in removals if r["pearson"] is not None]
            base = shared.pearson if shared else None
            largest = (
                max(defined, key=lambda r: abs(r["pearson"] - base))
                if defined and base is not None
                else None
            )
            influence.append(
                dict(
                    method=method,
                    series_id=series,
                    n=len(common),
                    status="estimated"
                    if defined and base is not None
                    else "too_short"
                    if not removals
                    else "constant",
                    baseline_pearson=base,
                    baseline_spearman=shared.spearman if shared else None,
                    pearson_min=min((r["pearson"] for r in defined), default=None),
                    pearson_max=max((r["pearson"] for r in defined), default=None),
                    undefined_removals=len(removals) - len(defined),
                    largest_change_month=largest["removed_month"] if largest else None,
                    largest_absolute_change=abs(largest["pearson"] - base) if largest else None,
                    removals=removals,
                )
            )
    lookup = {(r.last_month, r.method, r.series_id): r for r in study.rolling}
    size = study.plan.rolling_months
    for end in range(size, len(study.changes) + 1):
        sample = study.changes[end - size : end]
        first, last = sample[0].month, sample[-1].month
        reasons = []
        if len({r.method for r in sample}) != 1:
            reasons.append("methodology_break")
        if last != shift_month(first, size - 1):
            reasons.append("noncontiguous")
        missing = [r.month.isoformat() for r in sample if any(r.values[s] is None for s in SPECS)]
        if missing:
            reasons.append("missing_common_changes")
        for series in DRIVERS:
            saved = lookup.get((last, sample[-1].method, series)) if not reasons else None
            rolling.append(
                dict(
                    series_id=series,
                    method=sample[-1].method,
                    first_month=first.isoformat(),
                    last_month=last.isoformat(),
                    pearson=saved.pearson if saved else None,
                    spearman=saved.spearman if saved else None,
                    status="unavailable"
                    if not saved
                    else "estimated"
                    if saved.pearson is not None
                    else "constant",
                    reasons=reasons,
                    missing_months=missing,
                )
            )
    return dict(
        schema_version="1.0.0",
        rules_version="monthly-robustness-1",
        report_fingerprint=report.fingerprint,
        monthly_fingerprint=study.fingerprint,
        as_of=report.as_of.isoformat(),
        minimum_pairs=study.plan.minimum_pairs,
        rolling_months=size,
        sample_comparisons=comparisons,
        influence=influence,
        rolling=rolling,
        daily_backtest_ready=False,
        forecasting_test=False,
        limitations=[
            "Current revised monthly averages, not executable returns or historical availability.",
            "All eligible single-month removals reported; no favorable-result selection.",
            "Removal ranges describe sensitivity, not confidence or significance.",
            "Overlapping rolling windows are dependent; missing windows are not joined.",
            "Pairwise and common samples differ; coefficient differences are not causal effects.",
        ],
    )
