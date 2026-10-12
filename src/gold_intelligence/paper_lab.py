"""Synthetic-only trading mechanics lab; not market validation or a broker connection."""

import hashlib
import math
from datetime import UTC, datetime, timedelta
from statistics import mean
from typing import Literal

from pydantic import Field, model_validator

from .models import Contract, Timestamp
from .storage import canonical


class LabQuote(Contract):
    observed_at: Timestamp
    available_at: Timestamp
    bid: float = Field(gt=0, allow_inf_nan=False)
    ask: float = Field(gt=0, allow_inf_nan=False)
    synthetic: Literal[True] = True

    @model_validator(mode="after")
    def coherent(self):
        if self.ask < self.bid or self.available_at < self.observed_at:
            raise ValueError("crossed quote or availability before observation")
        return self


class LabSettings(Contract):
    initial_cash: float = Field(default=10000, gt=0, allow_inf_nan=False)
    lookback: int = Field(default=20, ge=2, le=250)
    allocation: float = Field(default=0.25, gt=0, le=1, allow_inf_nan=False)
    fee_bps: float = Field(default=2, ge=0, le=100, allow_inf_nan=False)
    slippage_bps: float = Field(default=1, ge=0, le=100, allow_inf_nan=False)
    stop_fraction: float = Field(default=0.03, gt=0, lt=1, allow_inf_nan=False)


def synthetic_quotes():
    """Deterministic fabricated regimes, fixed independently of parameter outcomes."""
    start = datetime(2024, 1, 1, tzinfo=UTC)
    rows = []
    price = 2000.0
    for i in range(180):
        price += (2 if (i // 45) % 2 == 0 else -3) + math.sin(i) * 0.4
        time = start + timedelta(hours=i)
        rows.append(LabQuote(observed_at=time, available_at=time, bid=price - 0.2, ask=price + 0.2))
    return rows


def simulate_lab(quotes, settings=None):
    settings = LabSettings.model_validate((settings or LabSettings()).model_dump())
    quotes = [
        LabQuote.model_validate(q.model_dump() if isinstance(q, LabQuote) else q) for q in quotes
    ]
    for previous, current in zip(quotes, quotes[1:], strict=False):
        if current.observed_at <= previous.available_at:
            raise ValueError("next quote must occur after the prior decision was available")
    fee, slip = settings.fee_bps / 10000, settings.slippage_bps / 10000
    cash, quantity, entry_price, entry_cost = settings.initial_cash, 0.0, 0.0, 0.0
    pending, mids, orders, fills, equity = None, [], [], [], []
    peak, maximum_drawdown, realized, total_fees = cash, 0.0, 0.0, 0.0
    for index, quote in enumerate(quotes):
        now = quote.available_at.isoformat()
        if pending is not None:
            order = orders[pending]
            if order["side"] == "buy":
                price = quote.ask * (1 + slip)
                budget = cash * settings.allocation
                quantity = budget / (price * (1 + fee))
                commission = quantity * price * fee
                entry_price, entry_cost = price, budget
                cash -= budget
                pnl = None
            else:
                price = quote.bid * (1 - slip)
                commission = quantity * price * fee
                proceeds = quantity * price - commission
                pnl = proceeds - entry_cost
                realized += pnl
                cash += proceeds
            fills.append(
                dict(
                    order_id=order["id"],
                    side=order["side"],
                    decision_at=order["decision_at"],
                    filled_at=now,
                    quote_at=quote.observed_at.isoformat(),
                    price=price,
                    quantity=quantity,
                    fee=commission,
                    realized_pnl=pnl,
                    cash_after=cash,
                )
            )
            total_fees += commission
            if order["side"] == "sell":
                quantity, entry_cost, entry_price = 0.0, 0.0, 0.0
            order.update(status="filled", filled_at=now)
            pending = None
        liquidation = quantity * quote.bid * (1 - slip) * (1 - fee)
        net_equity = cash + liquidation
        peak = max(peak, net_equity)
        maximum_drawdown = max(maximum_drawdown, (peak - net_equity) / peak)
        equity.append(
            dict(
                time=now,
                cash=cash,
                quantity=quantity,
                net_liquidation_equity=net_equity,
                unrealized_pnl=liquidation - entry_cost,
            )
        )
        if not all(math.isfinite(v) and v >= 0 for v in (cash, quantity, net_equity)):
            raise ValueError("non-finite or negative accounting state")
        current_mid = quote.bid / 2 + quote.ask / 2
        if len(mids) >= settings.lookback:
            reference = mean(mids[-settings.lookback :])
            side, reason = None, None
            if not quantity and current_mid > reference:
                side, reason = "buy", "above_prior_mean"
            elif quantity and quote.bid <= entry_price * (1 - settings.stop_fraction):
                side, reason = "sell", "stop_observed"
            elif quantity and current_mid < reference:
                side, reason = "sell", "below_prior_mean"
            if side:
                orders.append(
                    dict(
                        id=len(orders) + 1,
                        side=side,
                        reason=reason,
                        decision_at=now,
                        decision_index=index,
                        reference_mean=reference,
                        status="pending_next_quote",
                    )
                )
                pending = len(orders) - 1
        mids.append(current_mid)
    if pending is not None:
        orders[pending]["status"] = "cancelled_end_of_sample"
    identity = dict(
        engine_version="synthetic-paper-1",
        settings=settings.model_dump(mode="json"),
        quotes=[q.model_dump(mode="json") for q in quotes],
    )
    final = equity[-1]["net_liquidation_equity"] if equity else settings.initial_cash
    return dict(
        schema_version="1.0.0",
        engine_version="synthetic-paper-1",
        fingerprint=hashlib.sha256(canonical(identity).encode()).hexdigest(),
        scope="synthetic_mechanics_only",
        market_validation=False,
        daily_backtest_ready=False,
        live_paper_trading=False,
        broker_connected=False,
        settings=settings.model_dump(mode="json"),
        quotes=identity["quotes"],
        orders=orders,
        fills=fills,
        equity=equity,
        metrics=dict(
            final_cash=cash,
            final_quantity=quantity,
            final_equity=final,
            total_pnl=final - settings.initial_cash,
            realized_pnl=realized,
            unrealized_pnl=equity[-1]["unrealized_pnl"] if equity else 0,
            fees=total_fees,
            maximum_drawdown_fraction=maximum_drawdown,
            completed_trades=sum(f["side"] == "sell" for f in fills),
        ),
        limitations=[
            "Fabricated hourly quotes; results do not test gold-market forecasting.",
            "Long-only fractional units, no leverage or financing; these are lab assumptions.",
            "Signals use current known quote and prior means; fills use only the next quote.",
            "Stops are observed triggers with next-quote fills, not guaranteed stop prices.",
            "Net liquidation includes exit fee/slippage; open trades stay open.",
            "No queue, liquidity, market impact, overnight costs or actual broker execution.",
        ],
    )
