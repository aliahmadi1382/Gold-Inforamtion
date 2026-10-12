from decimal import Decimal

import pytest
from test_real_shadow import add

from gold_intelligence.real_paper import PaperCosts, evaluate_real_paper
from gold_intelligence.real_shadow import ShadowSettings


def test_buy_sell_round_trip_reconciles_independent_decimal_costs(tmp_path):
    for i, price in enumerate([2000, 2002, 2010, 2012, 1990, 1988]):
        add(tmp_path, i, price)
    r = evaluate_real_paper(tmp_path, ShadowSettings(lookback=2))
    assert [f["side"] for f in r["fills"]] == ["buy", "sell"]
    D = Decimal
    entry = D("2013") * D("1.0001")
    qty = D("2500") / (entry * D("1.0002"))
    exit_price = D("1987") * D("0.9999")
    proceeds = qty * exit_price * D("0.9998")
    assert r["final_cash"] == pytest.approx(float(D("7500") + proceeds))
    assert r["realized_pnl"] == pytest.approx(float(proceeds - D("2500")))
    assert r["final_quantity"] == 0
    assert r["fills"][0]["quote_at"] > r["fills"][0]["decision_at"]


def test_delayed_next_quote_cancels_pending_without_fill(tmp_path):
    for i, p in enumerate([2000, 2002, 2010]):
        add(tmp_path, i, p)
    add(tmp_path, 3, 2012, age=313)
    r = evaluate_real_paper(tmp_path, ShadowSettings(lookback=2))
    assert r["orders"][0]["status"] == "cancelled_next_quote_ineligible"
    assert r["fills"] == [] and r["final_cash"] == 10000


def test_end_pending_and_prefix_ledger_are_stable(tmp_path):
    for i, p in enumerate([2000, 2002, 2010]):
        add(tmp_path, i, p)
    a = evaluate_real_paper(tmp_path, ShadowSettings(lookback=2))
    assert a["orders"][0]["status"] == "pending_next_observation"
    add(tmp_path, 3, 2012)
    b = evaluate_real_paper(tmp_path, ShadowSettings(lookback=2))
    assert a["ledger"] == b["ledger"][:3]
    assert len(b["fills"]) == 1


def test_costs_revalidated_and_actual_delayed_input_cannot_fill(tmp_path):
    add(tmp_path, 0, 2000, age=313)
    add(tmp_path, 1, 2100, age=313)
    r = evaluate_real_paper(tmp_path)
    assert not r["synthetic"] and not r["live_paper_trading"]
    assert r["fills"] == [] and r["fees"] == 0
    with pytest.raises(ValueError):
        evaluate_real_paper(tmp_path, costs=PaperCosts().model_copy(update={"fee_bps": -1}))


def test_quote_predating_decision_cannot_fill_even_within_age_limit(tmp_path):
    for i, p in enumerate([2000, 2002, 2010]):
        add(tmp_path, i, p)
    add(tmp_path, 2.05, 2012, age=45)
    r = evaluate_real_paper(tmp_path, ShadowSettings(lookback=2))
    assert r["fills"] == []
    assert r["orders"][0]["status"] == "cancelled_next_quote_ineligible"


def test_long_gap_cancels_pending_execution(tmp_path):
    for i, p in enumerate([2000, 2002, 2010]):
        add(tmp_path, i, p)
    add(tmp_path, 1000, 2012)
    r = evaluate_real_paper(tmp_path, ShadowSettings(lookback=2))
    assert r["fills"] == []
    assert r["orders"][0]["status"] == "cancelled_next_quote_ineligible"
