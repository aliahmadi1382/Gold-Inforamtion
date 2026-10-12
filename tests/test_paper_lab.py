from datetime import UTC, datetime, timedelta

import pytest

from gold_intelligence.paper_lab import LabQuote, LabSettings, simulate_lab, synthetic_quotes


def quotes(values):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        LabQuote(
            observed_at=start + timedelta(hours=i),
            available_at=start + timedelta(hours=i),
            bid=p,
            ask=p,
        )
        for i, p in enumerate(values)
    ]


def test_next_quote_execution_exact_cash_and_realized_accounting():
    result = simulate_lab(
        quotes([10, 10, 12, 15, 9, 8]),
        LabSettings(initial_cash=100, lookback=2, allocation=1, fee_bps=0, slippage_bps=0),
    )
    buy, sell = result["fills"]
    assert buy["price"] == 15 and buy["quantity"] == pytest.approx(100 / 15)
    assert sell["price"] == 8 and sell["realized_pnl"] == pytest.approx(100 * 8 / 15 - 100)
    assert buy["filled_at"] > buy["decision_at"] and sell["filled_at"] > sell["decision_at"]
    assert result["metrics"]["final_cash"] == pytest.approx(100 * 8 / 15)
    assert result["metrics"]["total_pnl"] == pytest.approx(sell["realized_pnl"])
    assert not result["market_validation"] and not result["broker_connected"]


def test_flat_market_no_orders_and_last_order_cancelled_not_filled():
    flat = simulate_lab(quotes([10] * 8), LabSettings(lookback=2))
    assert flat["fills"] == [] and flat["metrics"]["total_pnl"] == 0
    short = simulate_lab(quotes([10, 10, 12]), LabSettings(lookback=2))
    assert short["orders"][0]["status"] == "cancelled_end_of_sample"
    assert short["fills"] == [] and short["metrics"]["final_quantity"] == 0


def test_prefix_decisions_and_equity_are_independent_of_future_quotes():
    data = synthetic_quotes()
    settings = LabSettings()
    short = simulate_lab(data[:90], settings)
    full = simulate_lab(data, settings)
    assert full["equity"][:90] == short["equity"]
    for a, b in zip(short["orders"], full["orders"], strict=False):
        assert (a["side"], a["decision_at"], a["reference_mean"]) == (
            b["side"],
            b["decision_at"],
            b["reference_mean"],
        )
    assert len([o for o in full["orders"] if o["decision_index"] < 90]) == len(short["orders"])


def test_fee_spread_and_slippage_consume_cash_and_open_equity_is_net_liquidation():
    data = quotes([10, 10, 12, 15])
    data[-1] = data[-1].model_copy(update={"ask": 16})
    settings = LabSettings(
        initial_cash=100, lookback=2, allocation=1, fee_bps=100, slippage_bps=100
    )
    result = simulate_lab(data, settings)
    fill = result["fills"][0]
    quantity = 100 / (16 * 1.01 * 1.01)
    assert fill["quantity"] == pytest.approx(quantity)
    assert fill["fee"] == pytest.approx(quantity * 16 * 1.01 * 0.01)
    assert result["metrics"]["final_equity"] == pytest.approx(quantity * 15 * 0.99 * 0.99)
    assert result["metrics"]["completed_trades"] == 0
    assert result["metrics"]["total_pnl"] == pytest.approx(result["metrics"]["unrealized_pnl"])


@pytest.mark.parametrize("damage", ["real", "nan", "crossed", "naive", "late", "duplicate"])
def test_invalid_or_real_inputs_are_rejected(damage):
    data = quotes([10, 10, 12])
    if damage == "late":
        data[0] = data[0].model_copy(update={"available_at": data[1].observed_at})
    elif damage == "duplicate":
        data[1] = data[0]
    else:
        row = data[0].model_dump()
        if damage == "real":
            row["synthetic"] = False
        elif damage == "nan":
            row["bid"] = float("nan")
        elif damage == "crossed":
            row["bid"] = 12
        else:
            row["observed_at"] = datetime(2024, 1, 1)
        data[0] = row
    with pytest.raises(ValueError):
        simulate_lab(data)


def test_copied_contract_cannot_bypass_synthetic_or_risk_validation():
    data = quotes([10, 10, 12])
    data[0] = data[0].model_copy(update={"synthetic": False})
    with pytest.raises(ValueError):
        simulate_lab(data)
    with pytest.raises(ValueError):
        simulate_lab(quotes([10, 10, 12]), LabSettings().model_copy(update={"allocation": 2}))
