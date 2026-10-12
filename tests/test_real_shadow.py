import json
from datetime import UTC, datetime, timedelta

import pytest

from gold_intelligence.goldapi_capture import capture_goldapi
from gold_intelligence.real_shadow import ShadowSettings, evaluate_shadow

TIME = datetime(2026, 10, 12, tzinfo=UTC)


def add(root, index, price, age=0):
    received = TIME + timedelta(minutes=index * 10)
    source = received - timedelta(seconds=age)
    raw = json.dumps(
        dict(
            timestamp=int(source.timestamp()),
            datetime=source.isoformat(),
            metal="XAU",
            currency="USD",
            unit="troy_ounce",
            exchange="FOREXCOM",
            symbol="FOREXCOM:XAUUSD",
            price=price,
            bid=price - 1,
            ask=price + 1,
        )
    ).encode()
    clocks = iter([received, received])
    return capture_goldapi(root, "fixture", lambda _: (raw, 200), lambda: next(clocks))


def test_delayed_real_quotes_cannot_create_profit_or_warmup(tmp_path):
    add(tmp_path, 0, 2000, 313)
    add(tmp_path, 1, 2100, 313)
    r = evaluate_shadow(tmp_path)
    assert [d["reason"] for d in r["decisions"]] == ["stale_quote", "stale_quote"]
    assert all(d["prior_eligible_observations"] == 0 for d in r["decisions"])
    assert r["final_cash"] == r["initial_cash"] == 10000
    assert r["fills"] == r["orders"] == [] and r["realized_pnl"] == 0


def test_prior_only_signals_and_future_append_invariance(tmp_path):
    for i, p in enumerate([2000, 2002, 2010]):
        add(tmp_path, i, p)
    settings = ShadowSettings(lookback=2)
    before = evaluate_shadow(tmp_path, settings)
    assert [d["signal"] for d in before["decisions"]] == ["wait", "wait", "buy_candidate"]
    assert before["decisions"][2]["prior_mean"] == 2001
    add(tmp_path, 3, 1900)
    after = evaluate_shadow(tmp_path, settings)
    assert after["decisions"][:3] == before["decisions"]
    assert after["decisions"][3]["signal"] == "exit_candidate"
    assert not after["orders_enabled"] and not after["synthetic"]


def test_gap_resets_warmup(tmp_path):
    add(tmp_path, 0, 2000)
    add(tmp_path, 1, 2002)
    add(tmp_path, 1000, 2100)
    r = evaluate_shadow(tmp_path, ShadowSettings(lookback=2))
    assert r["decisions"][-1]["reason"] == "warming_up"
    assert r["decisions"][-1]["prior_eligible_observations"] == 0


def test_unchecked_modified_settings_revalidated(tmp_path):
    with pytest.raises(ValueError):
        evaluate_shadow(
            tmp_path, ShadowSettings().model_copy(update={"initial_cash": float("nan")})
        )
