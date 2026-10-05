# Master Data & Research Specification

Version 1.0.0 · reviewed 2026-10-05 · implementation release 0.1.0.
The supplied brief is preserved verbatim in `original-brief.md` as an input artifact, not a verified factual source or a promise of working integrations. This specification and the source audit take precedence for implementation status.

## Objective and scope

Build an evidence-grounded Gold Market Intelligence & Decision System in four independently validated stages. The delivered release is a runnable research foundation. A daily XAU/USD stream is the initial analysis target; no real price feed, broker, proprietary dataset or current market opinion is assumed. Historical coverage means the earliest defensible evidence **per series and monetary regime**, not a continuous tick history extending back to 1919.

| Layer | Required observations and grain | Candidate acquisition | Release 0.1 |
| --- | --- | --- | --- |
| 1 Price | Instrument × venue × contract × price type × bar end; OHLC, volume unit, OI; future quote/tick/curve records | Licensed spot provider, LBMA/IBA, CME | Validated canonical OHLC importer; benchmark/spot/futures/ETF/CFD kept separate |
| 2 Structure | Stream × as-of × feature version; trend, range, pivots, momentum, volatility | Derived only from eligible price observations | SMA, momentum, ATR, realized volatility, prior range breakout, delayed confirmed pivots |
| 3 Positioning | Market code × report family × category × report date × vintage | CFTC annual archives | Legacy futures-only CSV parser; net positions; other families explicitly planned |
| 4 Macro | Series × reference period × release/vintage × unit | FRED/ALFRED, BLS, BEA, Fed, Treasury; licensed ISM/PMI/DXY providers | FRED adapter and 22-series shortlist; relationships remain research hypotheses |
| 5 Central banks | Country/institution × period × measure; tonnes and reserve share | WGC, IMF, national authorities | Scalar observation contract and documented acquisition requirements |
| 6 ETF/institutional | Fund × share class × day × holdings/flow metric | WGC, fund issuers | Contract; holdings, creations and cash flow must not be conflated |
| 7 Physical | Geography × period × sector × volume/premium metric | WGC, SGE, national sources | Contract; mine, recycling, jewellery, bars/coins, technology and regional premiums |
| 8 News/geopolitics | Story version plus separately identified real-world event | Official statements and entitled news feed | Validated event/story contract; no feed or sentiment classifier |
| 9 Calendar | Event × reference period × schedule version × release version | Official release schedules; entitled consensus provider | Validated schedule/actual/consensus contract; no live scheduler |
| 10 Historical events | Event × date precision × regime, with cited evidence | Primary archives and official histories | Cited seed milestones, candidate research list, executable event windows |

## Required semantics

Every observation carries source, URL, provider, dataset, observed/available/retrieved timestamps, original time representation and timezone, unit, currency, transformations, schema version, rights label, confidence, raw hash and raw record pointer. Confidence measures documented data confidence; it is not the probability of a profitable trade. Unknown values stay null or missing with an explanation; zero is never a missing-value substitute.

Raw bytes are retained locally before normalized records are inserted. Publication requires an explicit registry grant. `OPEN_PUBLIC` describes access, not automatic redistribution or training permission. Derived products inherit review obligations from every parent input.

Time-aware queries use `available_at <= as_of`. Default `system` mode also requires `retrieved_at <= as_of`. Explicit `source` mode can replay verified historical publication times while ignoring when this installation downloaded the record. Unknown publication times remain retrieval-time bounded in either mode. Report-period timestamps, vintage dates and scheduled releases are never interchangeable.

## Market-state representation

The snapshot includes price/technical state; uninterpreted macro, positioning, central-bank, ETF, physical and options evidence when imported; news/calendar versions when manually imported; input IDs, feature version and configured freshness threshold. Missing layers do not become neutral, bullish or bearish labels. There is no claimed liquidity/order-book measurement, geopolitical probability, confidence score, causal macro model or machine-learned regime in this release. The trend label is an explicit moving-average heuristic.

For future real-time snapshots add quote freshness, clock skew, exchange sessions, sequence gaps, spread, revision arrival, provider health and incomplete-bar handling. A finalized bar endpoint must not receive partial candles without a separate contract.

## Phase boundaries

1. **Research:** auditable acquisition, rights, normalization, history, methods and reproducible features. Delivered foundation; real-data coverage remains source dependent.
2. **Analyst:** verified feed integrations, schedule/release ingestion, freshness per series, correlations and regimes evaluated across time, evidence-linked narratives. Missing evidence and conflicting signals remain visible.
3. **Decision:** validated strategy produces LONG/SHORT/NO TRADE, entry/stop/target, instrument-aware size, costs, risk/reward, calibrated confidence, invalidation and evidence. Requires out-of-sample testing and paper/shadow operation.
4. **Execution:** deterministic risk service, broker adapter, order reconciliation, exposure limits, maximum daily loss, kill switch and monitored exits. No LLM has order credentials or direct order authority. No such service is installed in 0.1.

## Owner choices and defaults

The repository URL and write access were supplied and verified. The remaining unanswered questions are represented in `config/project.yaml`: earliest reliable history by era; daily XAU/USD first; hybrid future architecture; broker and commercial entitlements unset; research only. Other supported bar frequencies describe an input contract, not an acquired intraday dataset. These defaults can be changed without rewriting the data model.

## Acceptance for this delivery

The offline demo runs without a key; raw lineage verifies; invalid OHLC and timezone-naive timestamps fail; revisions and future releases cannot leak into default as-of queries; synthetic and real context are separated; restricted exports fail before writing; adapters fail clearly on schema drift; all ten layers have explicit status; CI checks tests, schemas, formatting and publication boundaries. Full historical harvesting and profitable/live trading are outside these acceptance claims.
