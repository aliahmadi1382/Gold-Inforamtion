# Operating guide

## Evidence synthesis (0.19)

Run `uv run gold synthesize-report <verified-report-directory> --output-dir local/reports/synthesis`, then `uv run gold verify-synthesis <synthesis-directory>`. Both commands are offline and execute before opening a store or loading a registry. The self-contained output retains report JSON, typed findings, Persian text and an exact file manifest. In the local report view, filter findings and expand their evidence; the JSON download exports the filtered view with its provenance; use the CLI for a complete self-contained bundle. Restart the service after upgrading to load current rules. See [scope and limits](source-methodology/evidence-synthesis.fa.md).

## Runtime and HTTP evidence (0.18)

New research bundles include `runtime.json` and `runtime-manifest.json`; `verify-report` checks both when present. The scope is the bundle writer, not an independently proven remote computation environment. New acquisitions retain sanitized attempt evidence in `store/transport/<run_id>.json`; existing history remains unknown. Quota is not measured. Preserve `transport/` separately alongside core backups, and keep complete report directories with both runtime sidecars. Restart the local server after acquisition to reload its snapshot. See [method and limitations](source-methodology/runtime-transport.fa.md).

## Local graphical workspace (0.17)

Run `uv run gold --store local/market local-ui` and open `http://127.0.0.1:8765`; Ctrl+C stops this foreground server. On Windows, `Start-Local.cmd` starts/reuses the project background process and opens the browser, `Restart-Local.cmd` rebuilds its data snapshot and `Stop-Local.cmd` stops only the matching owned process. Python/uv, the local store and report folders must already be present. No PowerShell execution-policy change or scheduled startup is required. Browser reload refreshes presentation, not the data snapshot. See [local workspace](source-methodology/local-workspace.fa.md).

Run commands from the checkout root; registry/config paths are relative to the current directory. Python 3.11+ is required. The lock file pins tested dependencies. `uv sync --frozen` creates the environment, and `uv run gold --help` lists commands. For a pip-only runtime install, use `python -m pip install .`; development verification uses the locked uv environment.

## Offline verification

```sh
uv sync --frozen
uv run gold validate-registry
uv run gold demo
uv run gold --store local/demo audit
uv run gold --store local/demo quality --as-of 2024-04-22T22:00:00Z --allow-synthetic
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check_publication.py
```

`demo` writes 80 fictional weekday bars and `local/demo/snapshot.json`. Dates deliberately omit an exchange calendar because this is software test data. Repeating the command inserts zero duplicate records. A real store must use a separate path. For a historical demo snapshot use source replay since all synthetic bytes were generated/retrieved together at the fixture endpoint:

```sh
uv run gold --store local/demo snapshot --as-of 2024-04-19T22:00:00Z --source synthetic_demo
```

The demo endpoint is deterministic; consult the generated CSV for exact dates rather than treating this example timestamp as a live schedule.

## Real prices

Create `local/sources.yaml` by copying `sources/source_registry.yaml`. Replace the `user_price_csv` entry's provider, URL, terms and license ID with the real provider and entitlement. Keep redistribution/training false unless evidenced. The `RESTRICTED` classification does not prohibit private processing of files the operator is entitled to use; it prohibits public export through the provided command.

```sh
uv run gold --registry local/sources.yaml import-prices local/input.csv --source user_price_csv --instrument XAUUSD --venue PROVIDER_NAME --dataset spot_daily_v1
uv run gold snapshot --as-of 2026-10-05T12:00:00Z --source user_price_csv --dataset spot_daily_v1 --venue PROVIDER_NAME --output local/latest.json
```

Use `--price-type futures --contract-expiry YYYY-MM-DD` for individual futures, and `--volume-unit contracts` when volume is supplied. Other units/currencies require `--unit` and `--currency`. For non-UTC input use `--timezone America/New_York` or the correct IANA zone; every timestamp offset must agree with its DST rules. `--retrieved-at` is for faithfully migrating existing acquisition logs; never invent an earlier retrieval. `--verified-availability` uses each CSV row's offset-aware available_at and requires release evidence. Otherwise availability equals retrieval. Close times must be correct, including venue session definitions.

## FRED macro data

Obtain your own API key from FRED. The preferred local setup is documented in the [Persian source guide](education/03-free-data-setup.fa.md): copy `.env.example` to `local/credentials.env`, fill it locally, and load it explicitly:

```sh
uv run gold --credentials-file local/credentials.env fetch-fred DFII10 --start 2003-01-01 --end 2026-10-02
uv run gold runs
```

There is no automatic dotenv loading. Alternatively, set the key in the environment. In PowerShell:

```powershell
$env:FRED_API_KEY = 'YOUR_OWN_KEY'
uv run gold fetch-fred DFII10 --start 2003-01-01 --end 2026-10-02
```

In a POSIX shell, use `export FRED_API_KEY='YOUR_OWN_KEY'`. Do not commit keys or screenshots of them. `--vintage 2020-03-20` requests a vintage view when supported. The adapter stores null for FRED `.` missing values and preserves realtime interval metadata. It does not convert revised values into first-release history. Source-specific units are in `config/macro_series.yaml`; verify metadata before extending that shortlist. An API-level error aborts the normalized batch. Raw successful pages may remain for diagnosis.

## Alpha Vantage daily gold closes

```sh
uv run gold --credentials-file local/credentials.env fetch-alpha-gold
uv run gold runs
uv run python scripts/inspect_onboarding.py
```

The first command makes one request to `GOLD_SILVER_HISTORY` with `symbol=GOLD` and `interval=daily`. It requires `ALPHAVANTAGE_API_KEY`. The entire returned history is validated before one normalized transaction, with a run manifest and original bytes. Service notices, wrong nominal, changed fields, duplicate/future dates and invalid prices fail explicitly. Errors do not print provider message bodies, which may echo keys. Avoid repeated calls while diagnosing a free-tier quota notice.

Records are `price_close`, not `price_bar`. Date labels are retained at midnight UTC with a documented transformation; this does not assert a closing time or source timezone. Weekend rows are preserved and flagged. `XAUUSD` maps to USD/troy ounce by instrument convention, marked as inferred, because the response has no unit field. The provider reference is not labelled a broker venue or executable quote. The OHLC `snapshot` and `event-study` commands still require full bars; they do not silently use this stream.

The inspection script uses local bytes only and reports full raw-row reconciliation plus yearly profiles. Its default policy is `config/quality_daily_close.yaml`, requiring a daily gold-close stream and DFII10 history. For a direct quality report at a chosen cutoff:

```sh
uv run gold --store local/market quality --policy config/quality_daily_close.yaml --as-of 2026-10-05T10:35:15.056743Z --output local/market/quality.json
```

Use the actual `as_of` from your inspection report or a current offset-aware timestamp. A copied example cutoff can exclude a newer acquisition. The default OHLC policy remains separate and fails when bars are absent. [First live acquisition findings](source-methodology/first-acquisition.fa.md) describe the observed limits.

## Historical macro and monthly reference (0.4)

```powershell
uv run gold --credentials-file local/credentials.env fetch-fred-core --end 2026-10-05
uv run gold fetch-worldbank-gold
uv run gold --credentials-file local/credentials.env fetch-fred CPIAUCSL --start 2019-12-01 --end 2020-02-01 --vintage 2020-03-20
uv run python scripts/inspect_history.py
$cutoff = (Get-Date).ToUniversalTime().ToString('o')
uv run gold macro-context --as-of $cutoff --output local/market/macro-context.json
uv run gold compare-monthly --as-of $cutoff --output local/market/monthly-comparison.json
```

Use a reviewed acquisition end date no later than today. `fetch-fred-core` defaults to the FRED lower date bound, 1776-07-04; each response starts at the series' actual first period. `--start` can narrow a later refresh, but the command does not automatically skip previously acquired periods. A fresh retrieval creates provenance versions. There is no automatic full-history polling. The seven-series plan is `config/macro_core.yaml`; the existing 22-series shortlist remains available for single-series imports.

The core command verifies current FRED series ID, native units, frequency and seasonal adjustment before fetching observations. Its per-series `fetch-fred-reviewed` manifest traces the canonical plan bytes, metadata response and every observation page. Metadata checks do not establish historical publication clocks. Successful series are retained when another fails; `partial` and `failed` batch results return exit code 3. See `gold runs` for detailed run IDs. Provider errors are reported without response bodies or credential-bearing URLs.

`macro-context` reads only eligible FRED observations for the selected plan and optional explicit `--vintage`. It selects the latest reference period, then the latest available/retrieved revision. Conflicting values at the same rank fail. Current and vintage views, units and dimensions are not silently combined. A latest null stays `missing_value`, without falling back to an older period. Age thresholds measure reference age. Use `--mode source` only with an understanding of verified-release vs retrieval-time availability; it cannot backdate a downloaded vintage.

The World Bank adapter downloads the pinned, reviewed workbook URL in `world_bank.py`. It reads cached cell values without editing the workbook, retains original bytes, checks gold's unit and methodology, rejects unfinished months and records the June 2025 definition change. A changed workbook definition or URL needs review rather than guessed column mapping. Expanded ZIP size is bounded and XML parsing uses `defusedxml`. Records are monthly `observation` values, not bars or daily closes.

`compare-monthly` compares arithmetic means of Alpha Vantage date labels with World Bank monthly averages. It keeps weekend counts, offers a weekday sensitivity calculation, exposes missing weekday slots without guessing holidays, excludes incomplete boundary months and records both definition regimes. Interior gaps remain visible rather than filled. Every result links to contributing record IDs. This is descriptive cross-definition comparison, not daily price validation.

`scripts/inspect_history.py` makes no network calls. It performs raw-row/cell reconciliation, acquisition-blob hash checks including metadata, unique-period inventories, current and historical cutoff checks, a vintage comparison and the monthly diagnostic. The default output is `local/market/history-report.json`; the default quality policy is `config/quality_history.yaml`. It can take a few minutes on a full local history because integrity checks read all records. Warnings about an intentionally old vintage or retired methodology stream are not evidence that current macro series are stale. The [phase-3 note](source-methodology/history-acquisition.fa.md) records actual coverage and open gates.

## Reviewed release timing and Persian brief (0.5)

```powershell
uv run gold import-release-evidence local/release-research/cpi-schedule-reviewed.json --reviewed
$cutoff = (Get-Date).ToUniversalTime().ToString('o')
uv run gold calendar-context --as-of $cutoff --horizon-days 90 --output local/reports/calendar.json
uv run gold research-brief --as-of $cutoff --output-dir local/reports
```

The import filename above is a local reviewed extraction, not a shipped example or a direct BLS download. `ReleaseEvidence` (generated schema `release_evidence.schema.json`) contains the official BLS URL, capture timestamp, schedule/archive-header basis, timezone evidence, caveats and selected rows. Each row names CPIAUCSL or UNRATE, reference month, an offset-aware New York announcement timestamp and a reviewer note. The source URL must match the series and, for archives, the dated release filename. Read the official page before using `--reviewed`; syntax checks cannot establish transcription accuracy.

Original BLS HTML/ICS requests returned HTTP 403 locally. The delivered evidence was manually reviewed through readable official web pages. Raw hashes refer to the saved reviewed JSON notes, not to original HTML. No network call, account or key is needed for importing those notes or generating the report. Do not call this an automated BLS feed. Future manual review and ingestion is required to refresh it.

Schedules and archived embargo clocks create only `scheduled_at`. Actual delivery, previous/actual values and consensus remain absent. Availability stays at ingestion; capture time is separately preserved in the raw note. Importing an old extract again cannot supersede a newer captured schedule. Selection happens before applying the upcoming horizon, so rescheduling an event outside the window does not resurrect its old date. Simultaneous contradictory captures fail. The calendar context rechecks note hashes and timing fields and labels evidence older than 168 hours stale, even when just reimported.

`research-brief` writes `research-brief.fa.md` and `research-brief.json` locally. It uses the explicit cutoff, current macro plan and history-quality policy; override them with `--plan` or `--policy`. Exit code 3 indicates failed data-quality checks; warning results return 0. The Markdown view displays numbers to at most four decimal places, unit labels, missing states, upcoming announced clocks in three timezones and source record IDs. No order, predictive signal, alert or external publication is generated. Missing upcoming evidence is not proof no event is scheduled. Calendar coverage is limited to the reviewed CPI/employment evidence; cancellations and unobserved source changes are not automatically detected.

## Monthly relationship research (0.6)

```powershell
$studyCutoff = (Get-Date).ToUniversalTime().ToString('o')
uv run gold monthly-research --as-of $studyCutoff --output-dir local/reports
uv run python scripts/inspect_monthly_research.py --store local/market --report local/reports/monthly-research.json
```

This command reads the existing local store; it does not fetch data or require credentials. It writes `monthly-research.fa.md` and `monthly-research.json`. The fixed five-series study uses World Bank monthly gold plus FRED DTWEXBGS, DFII10, DGS10 and CPIAUCSL. `--plan` defaults to `config/monthly_research.yaml`; changes to start, coverage, minimum sample or rolling window must accompany interpretation. The default start is February 2006, using January as the change base. Gold and index changes are percentages; rate differences are percentage points. CPI is month-over-month seasonally adjusted inflation, not year-over-year inflation or release surprise.

Only completed calendar months and versions available/retrieved by the explicit cutoff qualify. Historical vintage requests remain separate. All weekday date labels must be present, with at least 80% non-null values; missing labels and null labels are separately retained. These are research coverage rules, not a certified holiday calendar. A rejected month invalidates its own and the next month's change. June 2025 gold change is excluded at the World Bank method break. Results keep the two price methodologies separate.

The report contains pairwise and common-sample Pearson/Spearman coefficients, exact included months, all monthly levels with input record IDs, reasons for excluded changes and complete contiguous 60-month common-sample windows. Coefficients below the configured minimum of 36 months are absent, not zero. The threshold is a reporting policy, not a power guarantee. Constant series have undefined correlations. No p-values, fitted lags, trading returns or out-of-sample claims are generated. An `insufficient_data` report is still written and returns exit code 3; descriptive results return 0, invalid input/integrity failures return 2.

The independent inspection script recomputes selected monthly levels, coverage, adjacent changes, sample membership and reported Pearson/Spearman coefficients from the SQLite inputs. It does not certify provider definitions or causality. Preserve the code version, configuration, cutoff, local store/raw bytes and JSON fingerprint for reproduction. The output includes current revisions known at the cutoff, not what was known during each historical month. Keep real derived outputs under ignored `local/`. See the [method note](source-methodology/monthly-research.fa.md) and [Persian lesson](education/07-monthly-relationships.fa.md).

## Archive values and exact-date vintages (0.7)

```powershell
uv run gold import-release-values local/release-research/cpi-2020-02-values-reviewed.json --reviewed
uv run gold --credentials-file local/credentials.env fetch-fred CPIAUCSL --start 2019-12-01 --end 2020-02-01 --vintage 2020-03-11
$valueCutoff = (Get-Date).ToUniversalTime().ToString('o')
uv run gold release-value-report --as-of $valueCutoff --output-dir local/reports
```

The input above is a locally reviewed document, not a distributed vendor-data example. `ReleaseValueEvidence` records an official dated BLS archive URL, release number, headline period, New York embargo clock, capture time, document/reissue status, revision note and one or two values with units and table locators. Supported metrics are `cpi_all_items_sa_mom` (unit `percent_change_mom_sa`) and `unemployment_rate_sa` (unit `percent_sa`). The headline period is required; only the immediately preceding period may accompany it. Review the entire column header and reissue notice before using `--reviewed`. Contracts and hashes do not independently verify a transcription.

Import creates separate BLS macro observations and an acquisition manifest. It does not populate calendar actuals, invent consensus or modify FRED availability. Reissued documents require a reissue date; archive copies without a reissue notice still do not claim verified first release. Availability remains at local ingestion. A report selects whole documents by latest capture, so an older reimport cannot restore dropped rows. Incomplete or conflicting bundles, source/metric mismatches and raw/normalized discrepancies fail.

The report writes `release-values.fa.md` and `release-values.json`. It compares the document values with the exact FRED vintage on the header's New York date, and separately with current revisions known at the cutoff. Fetch three adjacent CPI index months to compare a headline month's MoM and the preceding month's MoM; fetch two UNRATE months for the equivalent rate comparison. CPI uses native index levels from one vintage, not mixed versions; both response-level realtime dates and raw rows are checked. A missing exact vintage is reported, never replaced with a nearby vintage or current values.

Display consistency means less than 0.05 percentage-point difference from a one-decimal published number; the exact boundary is marked uncertain. Native CPI levels are also rounded, so this is not a claim about unrounded BLS internals. FRED and BLS share the statistical origin. Date-only vintage agreement and a header clock do not establish actual intraday delivery. Current minus archive values are revision comparisons, not release surprises.

Exit code 0 (`compared`) means all selected archive values have historical display consistency and nonmissing current counterparts, within this deliberately narrow comparison scope. Code 3 (`incomplete` or `no_evidence`) accompanies a written report with missing or discrepant comparisons. Invalid input/integrity failures return 2. A successful comparison always retains `intraday_replay_ready: false` and `first_release_verified: false`. Preserve raw extracts, acquisition manifests, record IDs and code version along with the report. See [method and live evidence](source-methodology/release-values.fa.md) and [lesson eight](education/08-release-values-and-vintages.fa.md).

## Fixed-window revision ledger (0.8)

```powershell
$ledgerCutoff = (Get-Date).ToUniversalTime().ToString('o')
uv run gold revision-ledger --plan config/revision_ledger.yaml --as-of $ledgerCutoff
uv run python scripts/inspect_revision_ledger.py
```

The report command reads existing local evidence and makes no network request. Its default plan declares January–June 2020 for the two reviewed metrics; it also requires July headline documents to compare the final June period. The plan contains the declared time, reason, inclusive period range and metrics. This timestamp is operator supplied, not independently certified preregistration. Change and preserve the plan before examining a different study window. Plans allow 1–120 months and unique supported metrics.

For each reference month P, `before` is P in the document with headline P; `after` is P in the document with headline P+1. `difference_pp` is after minus before in percentage points. These are values from latest eligible captures, not certified first releases. Each side is also compared with the exact-date FRED vintage for its document. FRED vintage differences use unrounded computed outputs; document differences use the preserved one-decimal display precision. A zero document difference does not imply zero sub-display or later annual revision.

`revision-ledger.fa.md` and `revision-ledger.json` retain the expected document grid, all expected pairs, complete capture history, raw hashes and document/FRED parent IDs. Missing documents or previous-period cells are explicit. Multiple archive URLs for one metric/headline remain ambiguous even with equal values; the program does not choose a convenient source. Non-increasing header chronology prevents comparison. Conflicting same-capture evidence, identity drift within one URL and raw/normalized inconsistencies fail. Older reimports cannot resurrect values absent in the latest capture.

`capture_changes` separately records added, removed, equal or changed values between consecutive local captures of the **same URL**, restricted to the declared economic periods. It cannot distinguish archive edits from corrected manual transcription without further review. Repeated imports of the same capture are collapsed. With only one capture per URL, there is no evidence about recapture differences. Header clocks never become revision timestamps or historical availability.

Exit 0 (`complete`) requires every planned pair to be comparable and both historical vintages to match at display precision. A written partial/empty report returns 3; invalid evidence or parameters return 2. Completeness only applies to this declared adjacent-document study, and `first_release_verified`/`intraday_replay_ready` remain false. The standalone inspection command expects a complete ledger and independently reconciles its raw cells, FRED rational arithmetic and coverage totals. Its scope excludes certification of the source/transcription, archive recapture causality and intraday timing; full store integrity is separately checked by `gold audit`.

All real outputs remain under ignored `local/`. See the [delivery evidence](source-methodology/revision-ledger.fa.md) and [Persian lesson nine](education/09-revision-ledger.fa.md). A fresh checkout has code and schemas, not these private local records.

<a id="unified-research-report-09"></a>

## Unified research report (0.12)

Build all research sections from the existing real store at one explicit cutoff. The example uses the recorded delivery cutoff, not the current time; later ingestions require a correspondingly chosen cutoff. No API call or credential loading occurs.

```powershell
uv run gold --store local/market research-report --as-of 2026-10-05T14:32:01Z --output-dir local/reports/unified
```

The command prints `bundle`, `report`, section statuses and a fingerprint. Every run gets a new `research-<generation-time>-<suffix>` directory; previous output and reader notes are preserved. The overview is `research-report.fa.md`; `research-report.json` contains the complete typed aggregate. `details/` contains quality, macro, calendar, monthly, release-value, revision and positioning JSON, plus four Persian detail reports. Report/manifest schema `2.0.0` lists thirteen artifacts. Schema-1 bundles retain eleven artifacts and no COT section. A `.incomplete-*` directory can remain after failure and must not be treated as a completed report.

Use the printed bundle path in the commands below; the placeholder is not a literal existing directory:

```powershell
$reportBundle = 'local/reports/unified/research-REPLACE-WITH-PRINTED-RUN'
uv run gold verify-report $reportBundle
uv run python scripts/inspect_monthly_research.py --store local/market --report "$reportBundle/details/monthly-research.json"
uv run python scripts/inspect_revision_ledger.py --store local/market --report "$reportBundle/details/revision-ledger.json" --output local/reports/unified-revision-validation.json
uv run python scripts/inspect_positioning.py --store local/market --report "$reportBundle/details/positioning.json" --output local/reports/unified-positioning-validation.json
```

`verify-report` requires only the saved bundle, without opening the store or registry. It checks byte integrity, typed contracts, shared cutoff/version/settings, section summaries and exact equality of child JSON to embedded components. It does not authenticate the issuer, prove source accuracy, reconcile arithmetic to raw data or validate unlisted reader notes. The independent scripts do require the original local store; the ledger script checks complete ledgers. Keep manifests and listed files unchanged, and add notes in a separate unlisted file.

`research-report` defaults to `config/macro_core.yaml`, `config/monthly_research.yaml`, `config/revision_ledger.yaml` and `config/quality_history.yaml`; override with `--macro-plan`, `--monthly-plan`, `--revision-plan` and `--policy`. Calendar options are `--horizon-days` (1–366, default 90) and `--calendar-max-age-hours` (>0 to 8760, default 168). COT uses `--positioning-max-age-days` (1–365, default 14). Missing eligible COT makes the section missing; stale data is explicitly labeled. Available COT remains limited by retrieval-bound historical availability. There is no synthetic allowance or source-replay option for this combined report. Existing standalone commands remain available.

Exit 0 means a bundle was produced with status `compiled` or `with_limits`; inspect the latter's limitations. Exit 3 means a readable `partial` bundle was produced because an essential section is missing or quality failed on normal absence. Exit 2 denotes input/integrity/output failure; no newly completed bundle is promised. `verify-report` exits 0 for a verified bundle and 2 for validation/file errors. A fresh checkout has no real records and will normally produce `partial`.

All components are recomputed in one SQLite read transaction, with one `system` cutoff. Reference dates, freshness thresholds and document vintages remain distinct. A matching semantic fingerprint excludes build clocks but includes evidence, settings, registry hash, cutoff and software version; it is not a digital signature. The report cannot clear daily backtest or intraday-release gates. See [current delivery evidence](source-methodology/integrated-positioning.fa.md) and [Persian lesson thirteen](education/13-integrated-positioning.fa.md); the [0.9 delivery note](source-methodology/unified-research-report.fa.md) documents the earlier format.

<a id="comparing-saved-research-runs-010"></a>

## Comparing saved research runs (0.12)

`compare-reports` takes two completed `research-report` bundle directories, in before/after order. The after cutoff must be equal or later; generation time does not determine the order. Replace the placeholders with the printed `bundle` paths from the chosen runs:

```powershell
$beforeReport = 'local/reports/unified/research-BEFORE-RUN'
$afterReport = 'local/reports/unified/research-AFTER-RUN'
uv run gold compare-reports $beforeReport $afterReport --output-dir local/reports/comparisons
```

No registry, store, key or network access is required. Both complete input bundles are verified before comparison, and exactly the checked main-JSON bytes become the source snapshots. A new `comparison-*` directory contains `comparison.fa.md`, complete `comparison.json`, `inputs/before.json`, `inputs/after.json` and `manifest.json`. Real input copies and derived values remain subject to the original source rights; keep them under ignored `local/`. Prior runs are preserved; `.incomplete-*` output after failure is not a completed comparison.

```powershell
$comparisonBundle = 'local/reports/comparisons/comparison-PRINTED-RUN'
uv run gold verify-comparison $comparisonBundle
```

Verification checks four file hashes/sizes, the typed comparison and fingerprint, then recomputes the comparison from its two included input snapshots. The original bundle locations are not needed. This verifies computational coherence within the supported comparator version, not economic truth, publisher authenticity or all original source-bundle files. Unlisted notes are preserved and outside verification.

`unchanged` means no differences within the compared content/context; `context_only` means only cutoff/settings/software/registry changed; `changed` means at least one semantic entity differs. All three successfully produced outcomes exit 0, even when the input report is partial. Invalid/corrupt inputs, reversed cutoffs, ambiguous row identities or output errors exit 2. Inspect input and section statuses; success does not certify data completeness. `verify-comparison` also uses exit 0/2.

New comparisons use schema/comparator `2.0.0` and accept both research-report schema `1.0.0` and `2.0.0`. Saved schema-1 comparisons still recompute with comparator 1; no new fields are injected into legacy inputs. The comparison manifest remains schema `1.0.0` because its four-file structure is unchanged. If either report schema lacks COT, that section is marked `not_in_schema`, its comparison basis records which input lacks it, and no position/evidence differences are inferred. Machine counts are zero because no rows were compared; Markdown shows dashes. Missing data in two schema-2 inputs is a separate, comparable state. Entity rows match by meaning, with original JSON pointers for inspection. Lists of parent record IDs are sorted; metadata clocks and derived report fingerprints are not market changes. The complete JSON retains every reported difference; Markdown previews at most twelve entities and four fields per entity per section, with approximate age display. Input byte hashes bind exact snapshots even when data-change status is unchanged. Source paths and comparison generation time do not affect its fingerprint.

Price coverage cannot establish equality of underlying prices. Added/removed evidence means membership in the report, not database insertion/deletion; an ID change can be a recapture without a numeric revision. Common-sample membership remains visible. Attribution is not inferred from simultaneous context and output changes. See [delivery evidence](source-methodology/report-comparison.fa.md) and [Persian lesson eleven](education/11-comparing-research-runs.fa.md).

## CFTC positioning

The public API connector needs no key. It is restricted to **COMEX gold 088691 / Disaggregated / Futures Only / 100-troy-ounce contracts / all maturities**:

```sh
uv run gold fetch-cftc-gold --start 2006-06-13 --end 2026-10-06
uv run gold positioning-context --as-of 2026-10-06T12:00:00Z --max-age-days 14
```

The dates above are an example; choose the desired observation interval and an explicit cutoff at or after your actual acquisition. A past cutoff excludes newly fetched history. No Friday availability is inferred. The connector checks source metadata, bounded ordered pages, before/after counts and revision markers, complete row identity, integer counts and both OI balances before committing the normalized batch. A failed acquisition preserves already-saved raw evidence and a failure manifest; it adds no partial normalized batch. Retry the entire interval after a visible provider update. There is no continuous job.

`positioning-context` reconciles complete eligible captures against all their normalized records, chooses the newest whole five-group version per observation date, and writes a new directory with Persian Markdown and full JSON. Missing categories, raw tampering and ambiguous same-time captures fail. Only pairs exactly seven days apart receive deltas. Irregular intervals and non-Tuesday labels remain visible; age is measured from the observation date using the configured threshold. Exit code 3 means `no_data` or `stale`; 2 means an error, and 0 means descriptive output within that age policy. None means trading readiness.

For an independent arithmetic check, replace the report path with the one printed by the command:

```sh
uv run python scripts/inspect_positioning.py --report local/reports/positioning/positioning-RUN/positioning.json --output local/reports/positioning-validation.json
```

The inspector checks selected coverage, raw cells, nets, OI shares, deltas and profile counts. `gold audit` verifies the immediate record-to-capture hash; `positioning-context` and the inspector also follow capture links to pages and metadata. The same context is now included in schema-2 `research-report` bundles and compared by `compare-reports` when both input schemas include it; the standalone command remains available. See [method and live evidence](source-methodology/cot-positioning.fa.md) and [lesson twelve](education/12-cot-positioning.fa.md).

### Manual legacy import

Use the official [compressed archive](https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm). Choose **Legacy / Futures Only / Text**, unzip locally, then:

```sh
uv run gold import-cftc local/annual.txt --market-code 088691 --futures-only
```

The importer retains non-commercial, commercial and non-reportable long/short positions, non-commercial spreading and total OI. It rejects unsupported headers, explicit combined-report markers and duplicate report dates. Legacy combined files can have the same column names, so `--futures-only` attests that the correct archive family was selected; headers alone cannot prove it. This CSV importer does not accept disaggregated or combined files; the separate API connector above handles disaggregated gold futures only. Annual archives do not establish historical release instants, so availability is retrieval time. Source replay does not bypass that limitation. Preserve the downloaded archive and acquisition details locally. The compressed archive download returned HTTP 403 during initial implementation; its parser tests use fictional values. The later API acquisition is a separate, successfully tested access path.

## Manual refresh and report (0.13)

Run once from the repository root with the existing local key file:

```powershell
uv run gold --credentials-file local/credentials.env refresh-report
```

The default reviewed plan produces ten independent acquisitions: Alpha Vantage, World Bank, seven FRED series and CFTC. Each gets its own acquisition manifest even on failure. Ordinary source errors are isolated; completed inserts remain committed. The report is then built from eligible stored evidence at a cutoff taken after all acquisition attempts. A failed refresh can therefore leave usable older data in the report; the Persian summary explicitly separates acquisition outcomes from reference-period freshness. Missing values remain missing.

The printed `summary` path is the entry point. `manifest` contains checkpoints, settings, actual requested ranges, acquisition run IDs, failure types and output status; no key values or provider exception messages. The printed `bundle` points to a normal schema-2 research bundle for `verify-report` or `compare-reports`. Each run has a new directory under ignored `local/reports/refresh/`; older runs are preserved. The workflow manifest itself is not part of the research bundle's hash verification.

Defaults request FRED from 120 days before each latest eligible current observation through today's UTC date, and COT from 90 days before its latest eligible observation. A long gap since the previous acquisition remains included. With no eligible local series, history starts at FRED's lower API date or CFTC's reviewed first date. `--full-history` requests the entire current history. `--fred-overlap-days` (1–3650) and `--cot-overlap-days` (14–3650) customize overlap. Revisions outside the chosen interval are not detected. Alpha Vantage and World Bank always retrieve their full response history; Alpha Vantage is attempted once per invocation.

FRED start bounds are rounded back to the month/quarter start, or to the latest observed weekly label's weekday, before requesting data. Out-of-range rows still fail validation. The latest compatible World Bank period supplies freshness across its two known methodological eras, while the full report keeps those streams separate. Safe reason codes include `HTTP_403`, `HTTP_429`, `CONNECTION_FAILED`, `MISSING_CREDENTIALS`, `VALIDATION_FAILED`, `STORAGE_ERROR` and `UNEXPECTED_ERROR`; arbitrary exception text is never serialized. An HTTP code records rejection, not its underlying cause.

The report uses the existing `--macro-plan`, `--monthly-plan`, `--revision-plan`, `--policy`, `--horizon-days`, `--calendar-max-age-hours` and `--positioning-max-age-days` options. Invalid settings fail before network acquisition. No `--as-of` is accepted: the post-acquisition cutoff is explicit in the output. Use the separate offline `research-report` for a caller-chosen historical cutoff.

Exit 0 means all acquisition traces succeeded, the research bundle verified, automatic inputs have current reference age under their policies, calendar evidence is usable and the research report is not partial. Research status `with_limits` can still occur. Exit 3 means `partial` (a failed source, missing/stale/unchecked freshness or partial research/calendar coverage) or `failed` (report build/write/verification failed). Preflight/configuration/lock/storage errors exit 2. BLS schedules, reviewed release-value extracts and exact-date FRED vintages are explicitly not auto-refreshed.

Checkpoints are atomically replaced before and after steps. Ctrl+C records interruption where possible; forced termination can leave `running`, which is not success. There is no resume or whole-workflow retry. A new invocation preserves completed data. The original `refresh.lock` remains; release 0.15 additionally shares `writer.lock` between refresh, independent acquisitions, Store writes and backup. Contending operations fail rather than wait indefinitely. Persistent lock files are not evidence of active ownership; never delete them to bypass coordination. Direct SQL and external file writers must be stopped separately.

See [method and limits](source-methodology/manual-refresh.fa.md) and [Persian lesson fourteen](education/14-manual-refresh.fa.md). No scheduler or broker connection is installed.

## Refresh review (0.14)

`refresh-report --baseline PATH` selects and reads a verified prior research bundle before acquisition. Without it, the latest-cutoff completed refresh with a successful report in the same output directory and store is selected. Ambiguous, unreadable or corrupt candidates are explicit failures, without falling back. After moving a store to a different computer/path, use an explicit baseline for the first run. The current refresh is never selected as its own automatic baseline.

The original refresh `status`, manifest and report remain independent. The CLI adds `review_status`, `review`, `review_bundle` and `review_failure_type`. Exit 3 also covers review failures; `no_baseline` alone is not a failure. The Persian refresh summary links to the review. Review schema 1 is separate from unchanged RefreshRun schema 1; existing readers and legacy research/comparison schemas remain supported.

```sh
uv run gold review-refresh PATH_TO_SAVED_REFRESH --baseline PATH_TO_RESEARCH_BUNDLE
uv run gold verify-review PATH_TO_REVIEW_BUNDLE
```

These two commands are offline and do not open the store or registry. Offline review requires an explicit baseline to compare; without it, it produces `no_baseline`. Each run publishes a new review folder, with full comparison JSON, Persian priorities, exact copied refresh/report inputs and a manifest. Verification recomputes comparison, priorities, counts and prose from copied inputs; it is not publisher authentication or proof of acquisition/network events. See [method](source-methodology/refresh-review.fa.md) and [lesson fifteen](education/15-refresh-review.fa.md).

## Offline operational health (0.16)

For offline operational status in 0.16, use `uv run gold --store local/market operations-health --output-dir local/operations-health/NEW-NAME`. Optionally supply `--refresh-manifest PATH`; a historical store path requires `--allow-relocated-refresh`, with acquisition state/count checks. Output must be new and outside the store. Exit 3 indicates `attention` or `no_history`; exit 0 means clear recorded operations, not market freshness. Quota is unmeasured, historical runtime unrecorded, and retry guidance does not execute requests. See [operational health](source-methodology/operations-health.fa.md).

## Core-store backup and restore (0.15)

```powershell
uv run gold --store local/market backup-store --output-dir local/backups
uv run gold verify-backup PATH_TO_BACKUP
uv run gold restore-store PATH_TO_BACKUP --destination local/restore-tests/NEW_NAME
uv run gold --store local/restore-tests/NEW_NAME/store audit
```

These commands are offline and bypass registry/store creation on preflight. A missing source is refused, not initialized. The package contains a SQLite online snapshot including committed WAL pages, every content-hashed raw blob and acquisition JSON, a version-1 manifest and a Persian summary. Keys, auxiliary store reports, external report bundles, code/config, lock files and journal files are not copied. Preserve those reports/config separately and provision credentials through the owner's secure path.

Backup holds the shared nonblocking project-writer lock and validates both source and staged copy, including all records, direct lineage, metadata/failed raw blobs and acquisition references. It publishes a fresh directory only after verification; disk or integrity failure can leave `.incomplete-backup-*` without claiming success. Running/failed historical acquisitions retain their status. A local same-disk copy is not off-device disaster recovery.

Restore requires a new **container** path and publishes its verified store under `NEW_NAME/store`, with a receipt alongside it. Existing containers, even empty, and locations inside the backup or original source are refused. Failed copying can leave `.incomplete-store` in the new container; it never replaces the current store. Exit 0 requires successful verification and publication/receipt; input, lock, corruption and storage errors exit 2. Exact report reproduction needs matching interpreter as well as code, dependencies, cutoff, registry and settings. See [method](source-methodology/store-recovery.fa.md) and [lesson sixteen](education/16-store-recovery.fa.md).

## Other layers via normalized records

Prepare JSONL conforming to a runtime record contract and a directory of original raw evidence files named by SHA-256. Provider, license, layer and synthetic flags must match the registry:

```sh
uv run gold --registry local/sources.yaml import-records local/observations.jsonl --raw-dir local/input-raw
```

This supports observations, positioning, news and calendar contracts without claiming an automatic vendor connector. It preserves input provenance and validates hashes; it does not invent missing metadata or certify a human transformation's faithfulness. Imported context and news/calendar versions appear as uninterpreted evidence. Relevance filtering remains a research responsibility.

## Research and export

```sh
uv run gold --store local/demo event-study --event-at 2024-03-01T00:00:00Z --as-of 2024-05-01T00:00:00Z --horizon 20 --source synthetic_demo --dataset fictional_daily_v1
uv run gold --store local/demo export-public --kind price_bar --source synthetic_demo --output local/demo-public.jsonl
uv run gold schemas
```

Event windows require complete observations; dates with only a research-candidate year must first be resolved to a documented instant. Public export checks every record against the registry before writing and refuses to overwrite a file. It does not grant rights to arbitrary derived snapshots. Keep all real source/derived outputs under `local/` until a separate publication review.

## Failure handling and maintenance

Commands return exit code 2 for invalid input, network failure or rejected rights. A completed `quality` report with status `fail` or a partial/failed `fetch-fred-core` batch returns 3; `pass` and `warning` return 0. HTTP errors never print request URLs containing keys. Check the provider schema after a header error; do not silently map a different report family. `gold audit` detects corrupt or missing raw bytes. Back up the entire local directory together with acquisition metadata; copying just the SQLite file loses raw lineage. Close writers before copying SQLite or use its backup API.

CLI ingestion commands write per-run manifests under the store's `runs/` directory. `gold runs` lists their status, raw/normalized references and counts. `gold quality` evaluates stream coverage, revisions, missing values, reference age and raw/source integrity at an explicit cutoff. See [quality operations](quality-operations.md) for policy, failure and crash semantics.

There is no automatic refresh scheduler. Monitor/retry orchestration, per-row quarantine/recovery, database migrations, calendar-specific gaps and distributed/concurrent ingestion are follow-up work. Run manifests record failures but do not provide a quarantine or rollback service. Never delete raw records solely to make a quality check pass. CI tests are offline. The live Alpha Vantage/FRED checks recorded on 2026-10-05 are separate, account-specific observations, not guarantees of future service availability.

COT comparison keys include source, dataset, market, family, unit, observation date and category. Net values, evidence recaptures and observation age remain distinct. Markdown previews the newest changed COT dates first. Report schema/version and the COT source-registry hash are calculation context; source release instants remain unverified.


## تحویل ۰٫۲۰: بازیابی شواهد شبکه

پشتیبان نسخهٔ ۲ transport را همراه SQLite/raw/runs حفظ می‌کند؛ verify/restore نسخهٔ ۱ نیز پشتیبانی می‌شود. گزارش‌ها و ضمیمه‌ها خارج از دامنه‌اند. [دامنه و کنترل‌ها](source-methodology/transport-recovery.fa.md).
