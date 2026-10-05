# Historical event study protocol

`gold event-study` computes a descriptive single-stream window. Baseline is the last close strictly before the event instant. The first post-event observation closes at or after that instant; the full requested number of bars must exist. If an event falls inside a daily candle, the result is a close-to-close association, not an isolated event-time return. Intraday identification needs an appropriate price feed and event timestamp.

Outputs include ending return, maximum close-based upside/downside relative to baseline, peak-to-trough maximum drawdown across baseline plus window, and bars from the minimum close to the first subsequent recovery of the baseline. Recovery is null if unobserved within the window and zero if prices never fell below baseline. None of these are intrabar high/low excursions or causal effects. Different definitions must use different method versions.

Before a cross-asset study, pre-register the event and window, verify date/time precision, preserve USD/yield/equity/oil evidence separately, define control windows and confounders, record policy response and positioning as known then, and report uncertainty. Overlapping crises and hindsight-selected events cannot prove a profitable strategy. Research candidates in `data/events/historical_events.json` have no verified price reaction attached.
