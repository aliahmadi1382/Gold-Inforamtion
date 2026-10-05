# Data contracts and point-in-time semantics

Runtime validators in `src/gold_intelligence/models.py` are authoritative. JSON Schemas in `schemas/` are generated from them; cross-field checks such as OHLC inequalities also require runtime validation. All schemas reject unknown fields; all numeric fields reject NaN and infinity.

## Provenance

| Field | Meaning |
| --- | --- |
| source_id / source_url / provider / dataset | Registry identity, source location, publisher and exact dataset |
| observed_at | Bar end or reference-period label, not publication time |
| available_at | Earliest evidenced availability of this exact version; retrieval time if unknown |
| retrieved_at | When this installation obtained the source bytes |
| availability_basis | `verified_release`, `retrieval_time`, or `synthetic` |
| original_timestamp / original_timezone | Original representation and IANA zone; explicit UTC for date-only period labels |
| unit / currency | Unit definition and ISO currency when applicable |
| transformations / version | Ordered normalization identifiers and provenance contract version |
| license_status / license_id | Access class and specific rights review/contract reference |
| confidence | Data-confidence annotation between 0 and 1, not trading success probability; real imports begin at an uncalibrated 0.5 placeholder pending review |
| raw_sha256 / raw_record_id | Immutable source bytes and row/JSON pointer within them |
| synthetic | Explicit fictional-fixture flag, consistent with availability basis |

All actual timestamps require offsets and compare as instants. IANA zones preserve DST rules. A date-only macro/COT value gets a midnight UTC **period label** and a transformation annotation, not an invented release time. Full source-release evidence must be audited before using `--verified-availability` on price imports. Default availability is retrieval, even if an unverified input file contains an availability column.

`system` replay includes only data known to this installation at the cutoff; `source` replay ignores retrieval dates but still checks availability. Current FRED and annual CFTC imports deliberately use retrieval-time availability because a vintage date or usual Friday schedule does not prove the exact historical publication instant. A FRED vintage request chooses values, not an intraday release timestamp. Never forward-fill a revised monthly value into dates before it was released.

## Price CSV and grains

```csv
observed_at,available_at,open,high,low,close,volume,open_interest
2024-01-02T22:00:00Z,2024-01-02T22:01:00Z,100,103,99,102,,
```

The row above is a format example with fictional numbers. Required columns: observed_at, open, high, low, close. Optional: available_at, volume, open_interest. Unknown, duplicate or ragged columns fail. Duplicate instants fail, including differently written offsets for the same instant. Bar timestamps label **closed bar ends**. O/H/L/C must be positive and ordered. Volume without a unit fails; spot tick counts must be `ticks`, not exchange volume. Futures require expiry. Continuous futures require an explicit future roll/adjustment methodology; they are not silently spliced into spot history. Provider timezone/session definitions belong to dataset metadata.

Stream identity includes source, dataset, instrument, venue, timeframe, price type, expiry, currency, unit and synthetic flag. Analysis refuses mixed streams. USD/troy-ounce, GBP/fine-ounce, CNY/gram, USD/share and contracts are not interchangeable. Any conversion needs FX time, purity, conversion constants and parent record IDs. A benchmark auction is not a 24-hour spot close.

## Other contracts

- `PriceClose`: provider reference price for a daily date label, with instrument, provider venue identifier, positive close, explicit unit basis and nullable session timezone. A separate kind prevents OHLC features from consuming incomplete bars. Midnight UTC is a period label, never an invented session close. Alpha Vantage's `XAUUSD` unit is inferred by instrument convention and flagged until independently confirmed; weekend dates are retained. Availability remains retrieval time.
- `Observation`: series_id, layer, numeric value/null, vintage and dimensions. Dimensions must document country/fund/sector/contract/metric where applicable. Examples: ETF holdings in tonnes vs net flows in currency; gold reserve stock vs period purchases; mine output vs recycling; implied volatility by expiry/strike/delta; futures basis by matched maturity. Dedicated quote, tick and options-chain contracts remain planned.
- `Positioning`: CFTC market, report family, category, long, short, spreading and total OI. Never join legacy non-commercial to disaggregated managed-money as a single category. Current importer is futures-only, not combined futures/options.
- `NewsEvent`: stable event ID, separate event and publication times, entities, hypothesized channels, verification state, links and an original short summary. Full copyrighted articles are excluded. An event is not a trade instruction.
- `CalendarRelease`: schedule, actual release time, reference period, previous/actual and consensus with its own timestamp. Actual values cannot precede release; consensus must precede an actual release. Store schedule/revision changes as new records. Consensus requires its own entitled source. Surprise is actual minus consensus only for matching units and vintages.
- `HistoricalEvent`: date precision and verification distinguish cited milestones from broad research candidates. Candidate years do not supply an exact event-study timestamp.

## Quality controls and limits

Failed rows reject an import as a batch. Missing values remain null. Input duplicates, non-finite values, bad units at stream boundaries, invalid times and missing raw lineage fail validation. Daily gaps above four calendar days generate a review warning, not automatic data filling. Exchange-specific holidays and release-specific freshness SLAs are future work. Configurable reference-age thresholds are operational warnings. Numeric macro context remains uninterpreted; no universal freshness or causal rule is applied. Date-only close prices receive separate session/unit/calendar warnings. The onboarding reconciliation checks normalized dates and values against original JSON rows, not against an independent market-data source.

## Phase-3 macro and monthly reference

`MacroPlan` declares the reviewed native unit, provider unit label, frequency, seasonal adjustment and reference-age limit of each FRED series. Each reviewed acquisition manifest includes the canonical plan and metadata response as raw hashes alongside the observations. `MacroContext` is a separate typed as-of output with per-series available/missing/missing_value/stale states and record IDs. It does not create verified release timestamps, turn vintages into intraday availability, or fill missing latest values.

World Bank monthly gold uses `Observation`, layer `price`, series `WB_GOLD_MONTHLY`, dataset `pink_sheet_gold_monthly_v1`, USD per troy ounce. A month-start UTC timestamp is a reference label only. Dimensions specify instrument GOLD, frequency 1mo, monthly_average and the London-fixing vs spot-average methodology split at June 2025. The raw pointer is a worksheet/cell address; availability remains retrieval time. No bars, daily quotes or interpolated prices are created. The separate monthly diagnostic links all contributing record IDs and preserves both definitions.

## Reviewed timing evidence (0.5)

`ReleaseEvidence` is an attested selected web transcription, not a raw HTML claim. It creates existing `CalendarRelease` records with dataset `bls_reviewed_schedule_v1` or `bls_reviewed_header_v1`, unit `release_event` and raw pointer `entries:<index>`. Reference-month UTC labels and announced New York instants remain distinct. Raw capture time does not backdate local ingestion availability. Actual/previous/consensus and actual delivery time remain null. `CalendarContext` selects the newest captured eligible event version before horizon filtering and exposes evidence age plus UTC/New York/Tehran times. `ResearchBrief` composes quality, macro and calendar output, with daily-backtest readiness fixed false in this release. No existing record contract or content hash has been migrated.
