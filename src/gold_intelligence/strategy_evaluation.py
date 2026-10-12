"""Fixed chronological evaluation and cost-matched controls; no market-validity claim."""

from datetime import datetime

from pydantic import Field

from .models import Contract
from .real_paper import PaperCosts, PaperRisk, evaluate_real_paper
from .real_shadow import ShadowSettings


class EvaluationPlan(Contract):
    training_observations: int = Field(default=40, ge=2, strict=True)
    minimum_test_observations: int = Field(default=20, ge=2, strict=True)


def account_metrics(ledger, initial_cash, fills):
    peak, maximum = initial_cash, 0.0
    curve = []
    for row in ledger:
        equity = row["indicative_net_equity"]
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak
        maximum = max(maximum, drawdown)
        curve.append(
            dict(
                time=row["received_at"],
                equity=equity,
                drawdown_fraction=drawdown,
                cumulative_fees=row["cumulative_fees"],
            )
        )
    final = curve[-1]["equity"] if curve else initial_cash
    closed = [f for f in fills if f["side"] == "sell"]
    return dict(
        final_net_equity=final,
        net_pnl=final - initial_cash,
        net_return_fraction=final / initial_cash - 1,
        maximum_drawdown_fraction=maximum,
        completed_trades=sum(f["side"] == "sell" for f in fills),
        winning_closed_trades=sum(f["realized_pnl"] > 0 for f in closed),
        win_fraction=sum(f["realized_pnl"] > 0 for f in closed) / len(closed) if closed else None,
        curve=curve,
    )


def hold_control(rows, decisions, settings, costs, risk):
    """One allocation-matched entry on the next eligible quote; failed entry stays cash."""
    cash, quantity, fees = settings.initial_cash, 0.0, 0.0
    pending = None
    attempted = False
    ledger = []
    fee, slip = costs.fee_bps / 10000, costs.slippage_bps / 10000
    for row, d in zip(rows, decisions, strict=True):
        if pending is not None:
            if (
                d["signal"] != "blocked"
                and datetime.fromisoformat(row["source_at"]) > pending
                and 0
                < (datetime.fromisoformat(row["received_at"]) - pending).total_seconds()
                <= settings.maximum_gap_seconds
            ):
                price = row["ask"] * (1 + slip)
                budget = cash * costs.allocation
                exposure_ratio = row["ask"] / (price * (1 + fee))
                liquidation_ratio = row["bid"] * (1 - slip) * (1 - fee) / (price * (1 + fee))
                budget = min(
                    budget,
                    risk.maximum_exposure_fraction
                    * cash
                    / (exposure_ratio + risk.maximum_exposure_fraction * (1 - liquidation_ratio)),
                )
                quantity = budget / (price * (1 + fee))
                fees = quantity * price * fee
                cash -= budget
            pending = None
        if not attempted and d["signal"] != "blocked" and not risk.kill_switch:
            pending = datetime.fromisoformat(row["received_at"])
            attempted = True
        net = cash + quantity * row["bid"] * (1 - slip) * (1 - fee)
        ledger.append(
            dict(received_at=row["received_at"], indicative_net_equity=net, cumulative_fees=fees)
        )
    return account_metrics(ledger, settings.initial_cash, [])


def evaluate_strategy(
    root, settings=None, costs=None, risk=None, plan=None, *, excluded_capture_ids=()
):
    settings = ShadowSettings.model_validate((settings or ShadowSettings()).model_dump())
    costs = PaperCosts.model_validate((costs or PaperCosts()).model_dump())
    plan = EvaluationPlan.model_validate((plan or EvaluationPlan()).model_dump())
    risk = PaperRisk.model_validate((risk or PaperRisk()).model_dump())
    if settings.lookback > plan.training_observations:
        raise ValueError("training observations must cover the declared lookback")
    base = evaluate_real_paper(
        root, settings, costs, risk, excluded_capture_ids=excluded_capture_ids
    )
    dataset = base["input_shadow"]["input_dataset"]
    count = dataset["observation_count"]
    result = dict(
        schema_version="1.0.0",
        scope="fixed_chronological_research_evaluation",
        plan=plan.model_dump(),
        observation_count=count,
        status="insufficient_observations",
        holdout=None,
        market_validation=False,
        broker_connected=False,
        parameters_fitted=False,
        account=base,
        whole_sample_metrics=account_metrics(base["ledger"], settings.initial_cash, base["fills"]),
    )
    if count < plan.training_observations + plan.minimum_test_observations:
        return result
    cutoff = datetime.fromisoformat(
        dataset["observations"][plan.training_observations]["received_at"]
    )
    tested = evaluate_real_paper(
        root,
        settings,
        costs,
        risk,
        decision_start_at=cutoff,
        excluded_capture_ids=excluded_capture_ids,
    )
    if tested["input_shadow"]["input_dataset"] != dataset:
        raise ValueError("evidence changed during evaluation")
    rows = dataset["observations"][plan.training_observations :]
    decisions = tested["input_shadow"]["decisions"][plan.training_observations :]
    ledger = tested["ledger"][plan.training_observations :]
    strategy = account_metrics(ledger, settings.initial_cash, tested["fills"])
    hold = hold_control(rows, decisions, settings, costs, risk)
    valid = sum(d["signal"] != "blocked" for d in decisions)
    result.update(
        status="holdout_computed" if valid else "holdout_no_eligible_quotes",
        holdout=dict(
            cutoff=cutoff.isoformat(),
            training_count=plan.training_observations,
            test_count=len(rows),
            eligible_test_quotes=valid,
            account=tested,
            strategy=strategy,
            cash_control=dict(final_net_equity=settings.initial_cash, net_pnl=0),
            allocation_matched_hold=hold,
            excess_net_pnl_vs_hold=strategy["net_pnl"] - hold["net_pnl"],
        ),
    )
    return result
