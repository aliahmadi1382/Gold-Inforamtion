# Operating guide

Run commands from the checkout root; registry/config paths are relative to the current directory. Python 3.11+ is required. The lock file pins tested dependencies. `uv sync --frozen` creates the environment, and `uv run gold --help` lists commands. For a pip-only runtime install, use `python -m pip install .`; development verification uses the locked uv environment.

## Offline verification

```sh
uv sync --frozen
uv run gold validate-registry
uv run gold demo
uv run gold --store local/demo audit
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

Obtain your own API key from FRED. Set it in the environment; `.env.example` is a template and no automatic dotenv loading occurs. In PowerShell:

```powershell
$env:FRED_API_KEY = 'YOUR_OWN_KEY'
uv run gold fetch-fred DFII10 --start 2003-01-01 --end 2026-10-02
```

In a POSIX shell, use `export FRED_API_KEY='YOUR_OWN_KEY'`. Do not commit keys or screenshots of them. `--vintage 2020-03-20` requests a vintage view when supported. The adapter stores null for FRED `.` missing values and preserves realtime interval metadata. It does not convert revised values into first-release history. Source-specific units are in `config/macro_series.yaml`; verify metadata before extending that shortlist. An API-level error aborts the normalized batch. Raw successful pages may remain for diagnosis.

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

Commands return exit code 2 for invalid input, network failure or rejected rights. HTTP errors never print the request URL containing the FRED key. Check the provider schema after a header error; do not silently map a different report family. `gold audit` detects corrupt or missing raw bytes. Back up the entire local directory together with acquisition metadata; copying just the SQLite file loses raw lineage. Close writers before copying SQLite or use its backup API.

There is no automatic refresh scheduler. Monitor/retry orchestration, persistent quarantine manifests, database migrations, calendar-specific gaps and distributed/concurrent ingestion are follow-up work. Never delete raw records solely to make a quality check pass. Tests are offline; live FRED verification requires an actual key and is not claimed by passing fixtures.
