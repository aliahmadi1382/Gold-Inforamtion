# Operating guide

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

## CFTC positioning

Use the official [compressed archive](https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm). Choose **Legacy / Futures Only / Text**, unzip locally, then:

```sh
uv run gold import-cftc local/annual.txt --market-code 088691 --futures-only
```

The importer retains non-commercial, commercial and non-reportable long/short positions, non-commercial spreading and total OI. It rejects unsupported headers, explicit combined-report markers and duplicate report dates. Legacy combined files can have the same column names, so `--futures-only` attests that the correct archive family was selected; headers alone cannot prove it. Disaggregated/combined ingestion is not implemented. Annual archives do not establish historical release instants, so availability is retrieval time. Source replay does not bypass that limitation. Preserve the downloaded archive and acquisition details locally. The archive download returned HTTP 403 in the implementation environment; tests cover documented column formats with fictional values, not a successful live archive fetch.

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
