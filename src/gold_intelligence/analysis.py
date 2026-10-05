"""Causal technical features and descriptive (not causal) event windows."""

import math
import statistics
from datetime import datetime

from .models import PriceBar, aware
from .storage import record_id


def price_series(bars: list[PriceBar]) -> list[PriceBar]:
    if not bars:
        raise ValueError("no price observations available at the requested time")
    streams = {
        (
            b.instrument,
            b.venue,
            b.timeframe,
            b.price_type,
            b.contract_expiry,
            b.provenance.source_id,
            b.provenance.dataset,
            b.provenance.unit,
            b.provenance.currency,
            b.provenance.synthetic,
        )
        for b in bars
    }
    if len(streams) != 1:
        raise ValueError("mixed price streams: select one source, dataset, venue and contract")
    by_time = {}
    for bar in bars:
        time = bar.provenance.observed_at
        previous = by_time.get(time)
        rank = (bar.provenance.available_at, bar.provenance.retrieved_at)
        if previous:
            previous_rank = (previous.provenance.available_at, previous.provenance.retrieved_at)
            if rank == previous_rank and record_id(bar) != record_id(previous):
                raise ValueError("conflicting price revisions at the same availability time")
            if rank < previous_rank:
                continue
        by_time[time] = bar
    return [by_time[time] for time in sorted(by_time)]


def technical_features(bars: list[PriceBar]) -> dict:
    bars = price_series(bars)
    closes = [b.close for b in bars]
    result = {
        "bars_available": len(bars),
        "close": closes[-1],
        "sma_20": None,
        "sma_50": None,
        "momentum_20": None,
        "atr_14_sma": None,
        "realized_volatility_20_per_bar": None,
        "trend": "unknown",
        "breakout_20": "unknown",
        "confirmed_swing_structure": "unknown",
    }
    for window in (20, 50):
        if len(bars) >= window:
            result[f"sma_{window}"] = statistics.mean(closes[-window:])
    if len(bars) >= 50:
        fast, slow = result["sma_20"], result["sma_50"]
        result["trend"] = (
            "up" if closes[-1] > fast > slow else ("down" if closes[-1] < fast < slow else "mixed")
        )
    if len(bars) >= 15:
        true_ranges = [
            max(
                bars[i].high - bars[i].low,
                abs(bars[i].high - bars[i - 1].close),
                abs(bars[i].low - bars[i - 1].close),
            )
            for i in range(len(bars) - 14, len(bars))
        ]
        result["atr_14_sma"] = statistics.mean(true_ranges)
    if len(bars) >= 21:
        result["momentum_20"] = closes[-1] / closes[-21] - 1
        returns = [math.log(closes[i] / closes[i - 1]) for i in range(len(bars) - 20, len(bars))]
        result["realized_volatility_20_per_bar"] = statistics.stdev(returns)
        result["prior_20_high"] = max(b.high for b in bars[-21:-1])
        result["prior_20_low"] = min(b.low for b in bars[-21:-1])
        result["breakout_20"] = (
            "above"
            if closes[-1] > result["prior_20_high"]
            else ("below" if closes[-1] < result["prior_20_low"] else "inside")
        )
    # A pivot at i is known only after bar i+2 has closed. Strict comparisons avoid flat ties.
    highs, lows = [], []
    for i in range(2, len(bars) - 2):
        neighbours = bars[i - 2 : i] + bars[i + 1 : i + 3]
        if all(bars[i].high > b.high for b in neighbours):
            highs.append(bars[i].high)
        if all(bars[i].low < b.low for b in neighbours):
            lows.append(bars[i].low)
    if len(highs) >= 2 and len(lows) >= 2:
        result["confirmed_swing_structure"] = (
            "higher_high_higher_low"
            if highs[-1] > highs[-2] and lows[-1] > lows[-2]
            else "lower_high_lower_low"
            if highs[-1] < highs[-2] and lows[-1] < lows[-2]
            else "mixed"
        )
    return result


def event_study(bars: list[PriceBar], event_at: datetime, horizon: int = 20) -> dict:
    aware(event_at)
    if horizon < 1:
        raise ValueError("horizon must be positive")
    bars = price_series(bars)
    before = [b for b in bars if b.provenance.observed_at < event_at]
    after = [b for b in bars if b.provenance.observed_at >= event_at]
    if not before or len(after) < horizon:
        raise ValueError("event window needs a pre-event close and the complete requested horizon")
    baseline = before[-1]
    window = after[:horizon]
    prices = [baseline.close] + [b.close for b in window]
    peak, drawdown = prices[0], 0.0
    for price in prices:
        peak = max(peak, price)
        drawdown = min(drawdown, price / peak - 1)
    trough_index = min(range(len(prices)), key=prices.__getitem__)
    recovery = (
        0
        if min(prices) >= prices[0]
        else next(
            (
                i - trough_index
                for i in range(trough_index + 1, len(prices))
                if prices[i] >= prices[0]
            ),
            None,
        )
    )
    return {
        "method": "close_to_close_event_window_v1",
        "event_at": event_at.isoformat(),
        "horizon_bars": horizon,
        "baseline_at": baseline.provenance.observed_at.isoformat(),
        "window_end": window[-1].provenance.observed_at.isoformat(),
        "baseline_close": prices[0],
        "return": prices[-1] / prices[0] - 1,
        "maximum_upside_from_baseline": max(prices) / prices[0] - 1,
        "maximum_downside_from_baseline": min(prices) / prices[0] - 1,
        "maximum_drawdown": drawdown,
        "bars_to_baseline_after_trough": recovery,
        "evidence_ids": [record_id(b) for b in [baseline] + window],
        "synthetic": baseline.provenance.synthetic,
        "interpretation": "Descriptive association; no causal attribution or executable signal.",
    }
