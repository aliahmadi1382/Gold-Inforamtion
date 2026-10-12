"""Offline hypothetical fills on verified real quotes with strict temporal eligibility."""

import hashlib
import math
from datetime import datetime

from pydantic import Field

from .models import Contract
from .real_shadow import ShadowSettings, evaluate_shadow
from .storage import canonical


class PaperCosts(Contract):
    allocation: float = Field(default=0.25, gt=0, le=1)
    fee_bps: float = Field(default=2, ge=0, le=100)
    slippage_bps: float = Field(default=1, ge=0, le=100)
    stop_fraction: float = Field(default=0.03, gt=0, lt=1)


def evaluate_real_paper(root, settings=None, costs=None):
    shadow = evaluate_shadow(root, settings or ShadowSettings())
    costs = PaperCosts.model_validate((costs or PaperCosts()).model_dump())
    cash, quantity, basis, realized, fees = shadow["initial_cash"], 0.0, 0.0, 0.0, 0.0
    orders, fills, ledger = [], [], []
    pending = None
    entry_price = 0.0
    fee, slip = costs.fee_bps / 10000, costs.slippage_bps / 10000
    for row, decision in zip(
        shadow["input_dataset"]["observations"], shadow["decisions"], strict=True
    ):
        if pending is not None:
            order = orders[pending]
            if (
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
        if decision["signal"] == "buy_candidate" and quantity == 0:
            side = "buy"
        elif decision["signal"] == "exit_candidate" and quantity > 0:
            side = "sell"
        elif (
            decision["signal"] != "blocked"
            and quantity > 0
            and row["bid"] <= entry_price * (1 - costs.stop_fraction)
        ):
            side = "sell"
        if side:
            orders.append(
                dict(
                    id=len(orders) + 1,
                    side=side,
                    decision_at=row["received_at"],
                    status="pending_next_observation",
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
            )
        )
    # Keep final order pending: adding future observations cannot rewrite earlier decisions.
    identity = dict(
        engine_version="real-paper-1", shadow=shadow, costs=costs.model_dump(mode="json")
    )
    return dict(
        schema_version="1.0.0",
        engine_version="real-paper-1",
        fingerprint=hashlib.sha256(canonical(identity).encode()).hexdigest(),
        scope="offline_hypothetical_execution_on_verified_real_quotes",
        synthetic=False,
        market_validation=False,
        broker_connected=False,
        live_paper_trading=False,
        input_shadow=shadow,
        costs=costs.model_dump(mode="json"),
        orders=orders,
        fills=fills,
        ledger=ledger,
        final_cash=cash,
        final_quantity=quantity,
        realized_pnl=realized,
        fees=fees,
        performance_conclusion="not_established",
    )
