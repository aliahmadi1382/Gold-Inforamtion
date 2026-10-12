"""Offline hypothetical fills on verified real quotes with strict temporal eligibility."""

import hashlib
import math
from datetime import datetime

from pydantic import Field

from .models import Contract, aware
from .real_shadow import ShadowSettings, evaluate_shadow
from .storage import canonical


class PaperCosts(Contract):
    allocation: float = Field(default=0.25, gt=0, le=1)
    fee_bps: float = Field(default=2, ge=0, le=100)
    slippage_bps: float = Field(default=1, ge=0, le=100)
    stop_fraction: float = Field(default=0.03, gt=0, lt=1)


class PaperRisk(Contract):
    maximum_exposure_fraction: float = Field(default=0.30, gt=0, le=1)
    maximum_daily_loss_fraction: float = Field(default=0.02, gt=0, lt=1)
    maximum_drawdown_fraction: float = Field(default=0.10, gt=0, lt=1)
    kill_switch: bool = Field(default=False, strict=True)


def evaluate_real_paper(
    root, settings=None, costs=None, risk=None, *, decision_start_at=None, excluded_capture_ids=()
):
    shadow = evaluate_shadow(
        root, settings or ShadowSettings(), excluded_capture_ids=excluded_capture_ids
    )
    costs = PaperCosts.model_validate((costs or PaperCosts()).model_dump())
    risk = PaperRisk.model_validate((risk or PaperRisk()).model_dump())
    if decision_start_at is not None:
        decision_start_at = aware(decision_start_at)
    cash, quantity, basis, realized, fees = shadow["initial_cash"], 0.0, 0.0, 0.0, 0.0
    orders, fills, ledger = [], [], []
    pending = None
    entry_price = 0.0
    day = None
    day_start = peak = last_risk_equity = cash
    daily_halt = drawdown_halt = False
    fee, slip = costs.fee_bps / 10000, costs.slippage_bps / 10000
    for row, decision in zip(
        shadow["input_dataset"]["observations"], shadow["decisions"], strict=True
    ):
        current_day = row["received_at"][:10]
        if current_day != day:
            day, day_start, daily_halt = current_day, last_risk_equity, False
        valid_mark = decision["signal"] != "blocked"
        risk_equity = cash + quantity * row["bid"] * (1 - slip) * (1 - fee)
        if valid_mark:
            peak = max(peak, risk_equity)
            daily_halt |= risk_equity <= day_start * (1 - risk.maximum_daily_loss_fraction)
            drawdown_halt |= risk_equity <= peak * (1 - risk.maximum_drawdown_fraction)
        exposure_breach = (
            valid_mark
            and quantity * row["ask"] > risk.maximum_exposure_fraction * risk_equity + 1e-9
        )
        halt = risk.kill_switch or daily_halt or drawdown_halt or exposure_breach
        if pending is not None:
            order = orders[pending]
            if halt and order["side"] == "buy":
                order["status"] = "cancelled_risk_limit"
            elif (
                decision["signal"] == "blocked"
                or datetime.fromisoformat(row["source_at"])
                <= datetime.fromisoformat(order["decision_at"])
                or datetime.fromisoformat(row["received_at"])
                <= datetime.fromisoformat(order["decision_at"])
                or (
                    datetime.fromisoformat(row["received_at"])
                    - datetime.fromisoformat(order["decision_at"])
                ).total_seconds()
                > shadow["settings"]["maximum_gap_seconds"]
            ):
                order["status"] = "cancelled_next_quote_ineligible"
            else:
                if order["side"] == "buy":
                    price = row["ask"] * (1 + slip)
                    budget = cash * costs.allocation
                    denominator = price * (1 + fee)
                    exposure_ratio = row["ask"] / denominator
                    liquidation_ratio = row["bid"] * (1 - slip) * (1 - fee) / denominator
                    exposure_cap = (
                        risk.maximum_exposure_fraction
                        * cash
                        / (
                            exposure_ratio
                            + risk.maximum_exposure_fraction * (1 - liquidation_ratio)
                        )
                    )
                    budget = min(budget, exposure_cap)
                    quantity = budget / (price * (1 + fee))
                    commission = quantity * price * fee
                    cash -= budget
                    basis = budget
                    entry_price = price
                    pnl = None
                    traded_quantity = quantity
                else:
                    price = row["bid"] * (1 - slip)
                    traded_quantity = quantity
                    commission = quantity * price * fee
                    proceeds = quantity * price - commission
                    pnl = proceeds - basis
                    realized += pnl
                    cash += proceeds
                    quantity, basis = 0.0, 0.0
                fees += commission
                fills.append(
                    dict(
                        order_id=order["id"],
                        side=order["side"],
                        decision_at=order["decision_at"],
                        filled_at=row["received_at"],
                        quote_at=row["source_at"],
                        raw_sha256=row["raw_sha256"],
                        price=price,
                        quantity=traded_quantity,
                        fee=commission,
                        realized_pnl=pnl,
                    )
                )
                order["status"] = "hypothetically_filled"
            pending = None
        side = None
        reason = decision["reason"]
        risk_equity = cash + quantity * row["bid"] * (1 - slip) * (1 - fee)
        if valid_mark:
            peak = max(peak, risk_equity)
            daily_halt |= risk_equity <= day_start * (1 - risk.maximum_daily_loss_fraction)
            drawdown_halt |= risk_equity <= peak * (1 - risk.maximum_drawdown_fraction)
            last_risk_equity = risk_equity
        exposure_breach = (
            valid_mark
            and quantity * row["ask"] > risk.maximum_exposure_fraction * risk_equity + 1e-9
        )
        halt = risk.kill_switch or daily_halt or drawdown_halt or exposure_breach
        if halt and quantity > 0 and valid_mark:
            side, reason = "sell", "risk_exit_next_eligible_quote"
        elif decision["signal"] == "buy_candidate" and quantity == 0 and not halt:
            side = "buy"
        elif decision["signal"] == "exit_candidate" and quantity > 0:
            side = "sell"
        elif (
            decision["signal"] != "blocked"
            and quantity > 0
            and row["bid"] <= entry_price * (1 - costs.stop_fraction)
        ):
            side = "sell"
        if side and (
            decision_start_at is None
            or datetime.fromisoformat(row["received_at"]) >= decision_start_at
        ):
            orders.append(
                dict(
                    id=len(orders) + 1,
                    side=side,
                    decision_at=row["received_at"],
                    status="pending_next_observation",
                    reason=reason,
                )
            )
            pending = len(orders) - 1
        mark = quantity * row["bid"] * (1 - slip) * (1 - fee)
        if not all(math.isfinite(value) for value in (cash, quantity, basis, realized, fees, mark)):
            raise ValueError("non-finite account state")
        ledger.append(
            dict(
                received_at=row["received_at"],
                cash=cash,
                quantity=quantity,
                indicative_net_equity=cash + mark,
                mark_source_at=row["source_at"],
                mark_age_seconds=row["age_at_receipt_seconds"],
                realized_pnl=realized,
                unrealized_pnl=mark - basis,
                cumulative_fees=fees,
                decision=decision,
                risk=dict(
                    entry_halted=halt,
                    daily_loss_halt=daily_halt,
                    drawdown_halt=drawdown_halt,
                    kill_switch=risk.kill_switch,
                    exposure_limit_breached=exposure_breach,
                    mark_eligible=valid_mark,
                    day_start_equity=day_start,
                    maximum_exposure_fraction=risk.maximum_exposure_fraction,
                ),
            )
        )
    # Keep final order pending: adding future observations cannot rewrite earlier decisions.
    identity = dict(
        engine_version="real-paper-2",
        shadow=shadow,
        costs=costs.model_dump(mode="json"),
        risk=risk.model_dump(mode="json"),
        decision_start_at=decision_start_at.isoformat() if decision_start_at else None,
    )
    return dict(
        schema_version="1.0.0",
        engine_version="real-paper-2",
        fingerprint=hashlib.sha256(canonical(identity).encode()).hexdigest(),
        scope="offline_hypothetical_execution_on_verified_real_quotes",
        synthetic=False,
        market_validation=False,
        broker_connected=False,
        live_paper_trading=False,
        input_shadow=shadow,
        costs=costs.model_dump(mode="json"),
        risk=risk.model_dump(mode="json"),
        orders=orders,
        fills=fills,
        ledger=ledger,
        final_cash=cash,
        final_quantity=quantity,
        realized_pnl=realized,
        fees=fees,
        performance_conclusion="not_established",
    )
