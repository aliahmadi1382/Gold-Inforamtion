from decimal import Decimal

import pytest
from test_real_shadow import add

from gold_intelligence.real_paper import PaperCosts, PaperRisk, evaluate_real_paper
from gold_intelligence.real_shadow import ShadowSettings
from gold_intelligence.strategy_evaluation import EvaluationPlan, evaluate_strategy


def test_holdout_has_fixed_boundary_no_training_orders_or_future_leak(tmp_path):
    for i, p in enumerate([2000, 2002, 2010, 2012, 1990, 1988]):
        add(tmp_path, i, p)
    settings = ShadowSettings(lookback=2)
    plan = EvaluationPlan(training_observations=3, minimum_test_observations=3)
    r = evaluate_strategy(tmp_path, settings, plan=plan)
    assert r["status"] == "holdout_computed"
    h = r["holdout"]
    assert h["training_count"] == 3 and h["test_count"] == 3
    assert all(o["decision_at"] >= h["cutoff"] for o in h["account"]["orders"])
    assert all(f["quote_at"] > f["decision_at"] for f in h["account"]["fills"])
    expected = Decimal("7500") + (
        Decimal("2500")
        / (Decimal("1991") * Decimal("1.0001") * Decimal("1.0002"))
        * Decimal("1987")
        * Decimal("0.9999")
        * Decimal("0.9998")
    )
    assert h["allocation_matched_hold"]["final_net_equity"] == pytest.approx(float(expected))
    assert h["strategy"]["final_net_equity"] == pytest.approx(float(expected))
    add(tmp_path, 6, 1900)
    later = evaluate_strategy(tmp_path, settings, plan=plan)
    assert later["holdout"]["cutoff"] == h["cutoff"]
    assert later["holdout"]["strategy"]["curve"][:3] == h["strategy"]["curve"]
    assert not r["market_validation"] and not r["parameters_fitted"]


def test_insufficient_and_all_stale_holdout_never_establish_performance(tmp_path):
    add(tmp_path, 0, 2000, age=313)
    assert evaluate_strategy(tmp_path)["status"] == "insufficient_observations"
    for i in range(1, 6):
        add(tmp_path, i, 2000 + i, age=313)
    r = evaluate_strategy(
        tmp_path,
        ShadowSettings(lookback=2),
        plan=EvaluationPlan(training_observations=3, minimum_test_observations=3),
    )
    assert r["status"] == "holdout_no_eligible_quotes"
    assert r["holdout"]["allocation_matched_hold"]["net_pnl"] == 0
    assert r["holdout"]["account"]["fills"] == []


def test_exposure_cap_and_kill_switch_act_before_entry(tmp_path):
    for i, p in enumerate([2000, 2002, 2010, 2012]):
        add(tmp_path, i, p)
    r = evaluate_real_paper(
        tmp_path,
        ShadowSettings(lookback=2),
        PaperCosts(allocation=1),
        PaperRisk(maximum_exposure_fraction=0.1),
    )
    last = r["ledger"][-1]
    assert last["quantity"] * 2013 / last["indicative_net_equity"] <= 0.1 + 1e-10
    killed = evaluate_real_paper(
        tmp_path, ShadowSettings(lookback=2), risk=PaperRisk(kill_switch=True)
    )
    assert killed["fills"] == killed["orders"] == []


def test_loss_halt_exits_next_quote_and_drawdown_halt_stays_latched(tmp_path):
    for i, p in enumerate([2000, 2002, 2010, 2012, 1400, 1410, 2200, 2300]):
        add(tmp_path, i, p)
    r = evaluate_real_paper(
        tmp_path, ShadowSettings(lookback=2), risk=PaperRisk(maximum_drawdown_fraction=0.03)
    )
    assert r["ledger"][4]["risk"]["daily_loss_halt"]
    assert r["ledger"][4]["risk"]["drawdown_halt"]
    assert [f["side"] for f in r["fills"]] == ["buy", "sell"]
    assert r["orders"][1]["reason"] == "risk_exit_next_eligible_quote"
    assert r["ledger"][-1]["risk"]["entry_halted"]


def test_modified_risk_is_revalidated(tmp_path):
    with pytest.raises(ValueError):
        evaluate_real_paper(
            tmp_path, risk=PaperRisk().model_copy(update={"maximum_daily_loss_fraction": -1})
        )


def test_daily_halt_resets_with_new_utc_day_without_erasing_global_risk(tmp_path):
    for i, p in enumerate([2000, 2002, 2010, 2012, 1400, 1410]):
        add(tmp_path, i, p)
    add(tmp_path, 150, 2200)
    r = evaluate_real_paper(
        tmp_path, ShadowSettings(lookback=2), risk=PaperRisk(maximum_drawdown_fraction=0.9)
    )
    assert r["ledger"][4]["risk"]["daily_loss_halt"]
    assert not r["ledger"][-1]["risk"]["daily_loss_halt"]
    assert r["ledger"][-1]["risk"]["day_start_equity"] == pytest.approx(
        r["ledger"][-2]["indicative_net_equity"]
    )
