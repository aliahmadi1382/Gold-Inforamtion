# Master Data & Research Specification

Version 1.4.0 · reviewed 2026-10-05 · implementation release 0.8.0.
The supplied brief is preserved verbatim in `original-brief.md` as an input artifact, not a verified factual source or a promise of working integrations. This specification and the source audit take precedence for implementation status.

## Objective and scope

Build an evidence-grounded Gold Market Intelligence & Decision System in four independently validated stages. The delivered release supports research acquisition. Daily XAU/USD is the initial target; a provider's date-labeled gold closes and a FRED macro sample have been acquired locally with documented limitations. No broker or current market opinion is assumed. Historical coverage means the earliest defensible evidence **per series and monetary regime**, not a continuous tick history extending back to 1919.

The table records the release-0.3 baseline; later additions are listed in the acceptance history below. The [coverage matrix](coverage-matrix.md) and [execution phases](../phases.fa.md) record current feature status.

| Layer | Required observations and grain | Candidate acquisition | Release 0.3 baseline |
| --- | --- | --- | --- |
| 1 Price | Instrument × venue × contract × price type × bar end or declared date label; OHLC where actually provided | Alpha Vantage gold closes, entitled spot/benchmark providers | Alpha Vantage date-only close adapter and separate contract; canonical OHLC importer; instruments kept separate |
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
4. **Execution:** deterministic risk service, broker adapter, order reconciliation, exposure limits, maximum daily loss, kill switch and monitored exits. No LLM has order credentials or direct order authority. No such service is installed in 0.5.

## Owner choices and defaults

The repository URL and write access were supplied and verified. The owner confirmed daily XAU/USD first, shorter timeframes afterward, free/public sources only, personal free APIs for Alpha Vantage and FRED, and Persian educational material with each phase. These decisions are recorded in `config/project.yaml`. Keys were supplied locally and both APIs were tested. Broker, execution venue and risk limits remain unset. Other supported bar frequencies describe an input contract, not an acquired intraday dataset. Earliest reliable history by era and the hybrid future architecture remain design defaults.

The [execution phases](../phases.fa.md) break the four research-to-execution stages into manageable deliveries. The [education index](../education/README.fa.md) accompanies implemented capabilities and distinguishes price-only observations from complete OHLC.

## Acceptance for this delivery

The offline demo runs without a key; raw lineage verifies; invalid OHLC and timezone-naive timestamps fail; revisions and future releases cannot leak into default as-of queries; synthetic and real context are separated; restricted exports fail before writing; adapters fail clearly on schema drift; all ten layers have explicit status; CI checks tests, schemas, formatting and publication boundaries. Release 0.2 additionally requires acquisition success/failure manifests, per-stream as-of inventories, explicit quality failures, scoped local credentials and Persian training. Full historical harvesting and profitable/live trading are outside these acceptance claims.

Release 0.3 adds successful account-specific acquisition, a distinct daily-close contract, complete saved-byte reconciliation and visible session/unit/calendar limitations. The daily-close readiness profile does not satisfy the OHLC profile. Historical release verification, an independent price comparison and trading-session methodology remain later gates.

Release 0.4 adds seven metadata-checked FRED histories, conservative cutoff-aware macro selection, a three-period vintage example, a distinct monthly World Bank gold reference and monthly comparison. All acquired records reconcile to saved rows/cells. The monthly comparison does not establish daily price accuracy or upstream supplier independence. Source-defined gold units/session/weekend methodology and verified historical release timestamps remain acceptance gates before daily return/backtest research. See [phase-3 evidence](../source-methodology/history-acquisition.fa.md).

Release 0.5 progresses independent calendar/reporting work while daily price methodology remains open. Reviewed BLS timing notes and archived embargo headers never create actual values or first-release availability. The Persian data-status brief is an initial reporting capability, not a completed analyst or decision system. See [timing evidence and limits](../source-methodology/release-evidence.fa.md).

Release 0.6 adds descriptive monthly gold/macro relationships with fixed transformations, explicit samples, missingness gates, methodology-break separation and rolling windows. Release 0.7 adds reviewed economic values tied to specific BLS documents and exact-date FRED vintages. Reissued documents and current revisions remain explicit. Neither delivery establishes causation, profitable strategy behavior or intraday first-delivery times. See [monthly research](../source-methodology/monthly-research.fa.md) and [release-value evidence](../source-methodology/release-values.fa.md).

Release 0.8 expands the reviewed archive coverage to a declared January–June 2020 comparison window, with July headline documents as the terminal boundary. The revision ledger retains every expected pair, ambiguous/missing document slots, exact-date vintage parents and separate same-document capture history. Complete-document selection, raw integrity and independent arithmetic reconciliation are acceptance criteria. This bounded archive comparison does not certify exhaustive revision history, first release or actual delivery. See [revision ledger evidence](../source-methodology/revision-ledger.fa.md).
