"""Fixed calendar subperiods of existing descriptive monthly changes, never a backtest."""

from .monthly_research import DRIVERS, REGIMES, SPECS, coefficients
from .world_bank import SERIES

WINDOWS = ((2006, 2009), (2010, 2014), (2015, 2019), (2020, 2024), (2025, 2029))


def monthly_stability(report):
    study = report.monthly
    rows = []
    sample_audit = []
    for first, last in WINDOWS:
        for regime in REGIMES:
            scoped = [
                r for r in study.changes if first <= r.month.year <= last and r.method == regime
            ]
            if not scoped:
                continue
            common = [r for r in scoped if all(r.values[s] is not None for s in SPECS)]
            sample_audit.append(
                dict(
                    calendar_window=f"{first}–{last}",
                    method=regime,
                    candidate_months=len(scoped),
                    included_months=[r.month.isoformat() for r in common],
                    excluded=[
                        dict(
                            month=r.month.isoformat(),
                            missing_series={
                                s: r.exclusions.get(s, "reason_not_recorded")
                                for s in SPECS
                                if r.values[s] is None
                            },
                        )
                        for r in scoped
                        if any(r.values[s] is None for s in SPECS)
                    ],
                )
            )
            for series in DRIVERS:
                pearson = spearman = None
                status = "too_short" if common else "no_overlap"
                if len(common) >= study.plan.minimum_pairs:
                    pearson, spearman = coefficients(
                        [r.values[SERIES] for r in common], [r.values[series] for r in common]
                    )
                    status = "estimated" if pearson is not None else "constant"
                rows.append(
                    dict(
                        calendar_window=f"{first}–{last}",
                        method=regime,
                        series_id=series,
                        population="common",
                        candidate_months=len(scoped),
                        n=len(common),
                        excluded_months=len(scoped) - len(common),
                        months=[r.month.isoformat() for r in common],
                        status=status,
                        pearson=pearson,
                        spearman=spearman,
                    )
                )
    return dict(
        schema_version="1.0.0",
        rules_version="fixed-calendar-2",
        report_fingerprint=report.fingerprint,
        monthly_fingerprint=study.fingerprint,
        as_of=report.as_of.isoformat(),
        minimum_pairs=study.plan.minimum_pairs,
        calendar_windows=[dict(first_year=a, last_year=b) for a, b in WINDOWS],
        rows=rows,
        sample_audit=sample_audit,
        daily_backtest_ready=False,
        forecasting_test=False,
        limitations=[
            "Fixed calendar buckets chosen without selecting favorable coefficients.",
            "Price methodologies remain separate; missing changes are never imputed.",
            "Latest known revisions; no original-release replay or historical availability claim.",
            "Monthly average-price changes are not executable returns.",
            "Subperiod coefficients are descriptive, not confidence intervals or causal evidence.",
            "The final calendar bucket is partial at the report cutoff.",
        ],
    )
