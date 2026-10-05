from datetime import UTC, datetime, timedelta

import pytest

from gold_intelligence.analysis import event_study, price_series, technical_features
from gold_intelligence.models import Observation
from gold_intelligence.snapshot import snapshot


def test_features_known_monotonic_series(make_bar):
    bars = [make_bar(i, 100 + i) for i in range(60)]
    values = technical_features(bars)
    assert values["sma_20"] == 149.5
    assert values["sma_50"] == 134.5
    assert values["momentum_20"] == pytest.approx(159 / 139 - 1)
    assert values["atr_14_sma"] == 2
    assert values["trend"] == "up"
    assert values["realized_volatility_20_per_bar"] > 0


def test_warmup_and_flat_series(make_bar):
    assert technical_features([make_bar()])["sma_20"] is None
    flat = technical_features([make_bar(i) for i in range(60)])
    assert flat["trend"] == "mixed"
    assert flat["realized_volatility_20_per_bar"] == 0
    assert flat["momentum_20"] == 0


def test_swings_wait_for_right_hand_confirmation(make_bar):
    bars = [
        make_bar(i, close)
        for i, close in enumerate([100, 101, 110, 102, 98, 103, 105, 115, 107, 101, 109, 108])
    ]
    assert technical_features(bars[:-1])["confirmed_swing_structure"] == "unknown"
    assert technical_features(bars)["confirmed_swing_structure"] == "higher_high_higher_low"


def test_breakout_excludes_current_bar(make_bar):
    bars = [make_bar(i) for i in range(20)] + [make_bar(20, 110)]
    result = technical_features(bars)
    assert result["prior_20_high"] == 101
    assert result["breakout_20"] == "above"


def test_future_bars_and_revisions_cannot_change_past_snapshot(store, make_bar):
    bars = [make_bar(i, 100 + i) for i in range(60)]
    store.put(bars)
    cutoff = bars[-1].provenance.available_at
    before = snapshot(store, cutoff)
    future = make_bar(60, 500)
    revision = make_bar(
        59,
        10,
        provenance={
            "available_at": cutoff + timedelta(days=2),
            "retrieved_at": cutoff + timedelta(days=2),
        },
    )
    store.put([future, revision])
    assert snapshot(store, cutoff) == before
    assert snapshot(store, cutoff + timedelta(days=2)).technical["close"] == 500


def test_eligible_revision_replaces_bar_without_duplicating(make_bar):
    base = make_bar()
    revision = make_bar(
        close=200,
        provenance={
            "available_at": base.provenance.available_at + timedelta(days=1),
            "retrieved_at": base.provenance.retrieved_at + timedelta(days=1),
        },
    )
    assert price_series([base, revision]) == [revision]
    with pytest.raises(ValueError, match="conflicting"):
        price_series([base, make_bar(close=201)])


@pytest.mark.parametrize(
    "changes", [{"venue": "OTHER"}, {"timeframe": "1h"}, {"provenance": {"currency": "EUR"}}]
)
def test_incompatible_streams_rejected(make_bar, changes):
    with pytest.raises(ValueError, match="mixed"):
        technical_features([make_bar(), make_bar(1, **changes)])


def test_event_returns_drawdown_and_recovery(make_bar):
    bars = [make_bar(i, close) for i, close in enumerate([100, 120, 90, 105])]
    result = event_study(bars, bars[1].provenance.observed_at, 3)
    assert result["return"] == pytest.approx(0.05)
    assert result["maximum_upside_from_baseline"] == pytest.approx(0.2)
    assert result["maximum_drawdown"] == pytest.approx(-0.25)
    assert result["bars_to_baseline_after_trough"] == 1


def test_event_incomplete_or_no_baseline_fails(make_bar):
    bars = [make_bar(i) for i in range(3)]
    with pytest.raises(ValueError, match="complete"):
        event_study(bars, bars[1].provenance.observed_at, 3)
    with pytest.raises(ValueError, match="pre-event"):
        event_study(bars, bars[0].provenance.observed_at, 2)


def test_synthetic_snapshot_excludes_real_macro(store, make_bar):
    bar = make_bar()
    p = bar.provenance.model_dump()
    p.update(source_id="fred", synthetic=False, availability_basis="retrieval_time")
    macro = Observation(provenance=p, layer="macro", series_id="DFII10", value=2.0)
    store.put([bar, macro])
    result = snapshot(store, bar.provenance.available_at)
    assert result.context["macro"]["status"] == "missing"
    assert result.decision == "NO_TRADE"
    assert result.synthetic


def test_staleness_and_insufficient_data_are_visible(store, make_bar):
    store.put([make_bar()])
    result = snapshot(store, datetime(2024, 2, 1, tzinfo=UTC))
    assert result.price_status == "stale"
    assert result.technical["trend"] == "unknown"
    assert any("warm-up" in warning for warning in result.warnings)


@pytest.mark.parametrize("limit", [0, -1, float("nan"), float("inf")])
def test_staleness_limit_must_be_finite_and_positive(store, make_bar, limit):
    store.put([make_bar()])
    with pytest.raises(ValueError, match="threshold"):
        snapshot(store, datetime(2024, 2, 1, tzinfo=UTC), stale_after_hours=limit)
