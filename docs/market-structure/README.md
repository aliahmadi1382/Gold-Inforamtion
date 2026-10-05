# Technical and positioning methods

All technical calculations use eligible, closed bars from a single stream. No centered window has access to an unclosed future bar.

| Feature | Definition / warm-up |
| --- | --- |
| SMA20/SMA50 | Arithmetic mean of the last 20/50 closes; null before full window |
| Trend | up if close > SMA20 > SMA50; down if reverse; otherwise mixed; unknown before 50 bars |
| Momentum20 | close / close twenty bars earlier minus one; 21 closes |
| ATR14 SMA | Mean of 14 true ranges, each max(high-low, abs(high-prior close), abs(low-prior close)); 15 bars; not Wilder smoothing |
| Realized volatility20 | Sample standard deviation of 20 log returns; per-bar units, no implicit annualization |
| Range/breakout | Prior 20 highs/lows excluding the current bar; compare latest close |
| Confirmed swing structure | Strict 2-left/2-right local pivots; pivot becomes usable only after its two right bars close; compare the last two confirmed highs and lows |
| COT net | Long minus short for the same category, report family and market |

These heuristics describe price behavior. They are not validated regime probabilities or trading signals. Gaps are not filled automatically. Support/resistance labels should identify the exact window/level definition; supply/demand and liquidity require defensible measures, not unexplained chart labels. OHLC bars cannot establish order-book depth or executable spread.

Position changes require comparable report vintages and categories. A crowded-long label needs a declared rolling distribution (for example net/OI percentile), minimum sample size and an out-of-sample evaluation. Concentration is a separate CFTC measure; it is not inferred from aggregate net positions. Options/curve signals require synchronized maturity, venue and timestamp definitions.
