# Acquisition and quality operations (0.4)

CLI ingestion now writes a manifest to `STORE/runs/<run_id>.json` before invoking the adapter. Successful or failed completion replaces the manifest atomically with finish time, application version, safe parameters, raw hashes, normalized IDs and inserted count. An identical re-import can reference records while inserting zero new records. Failures retain acquired raw evidence. Abrupt termination can leave `running`; never infer success from it. These files are local and are not a tamper-proof signing system or automatic retry service.

`gold runs` lists statuses without parameter values or exception bodies. Direct calls to the adapter library remain untracked unless wrapped in `acquire`; `gold demo` remains a deterministic fixture generator. Real acquisition CLI commands use the wrapper. No database migration is needed for existing stores.

```sh
uv run gold --store local/demo quality --as-of 2024-04-22T22:00:00Z --allow-synthetic --output local/demo/quality.json
uv run gold --store local/market quality --as-of 2026-10-05T12:00:00Z --output local/market/quality.json
uv run gold --store local/market runs
```

Quality reports include total/valid/eligible records, time-excluded records, stream identities, unique reference periods, extra versions, actual first/last observations, missing fractions after revision selection, age thresholds, daily calendar-gap warnings and provenance findings. Integrity is checked across the store, including time-excluded records, while coverage statistics use eligible records only. Unknown kinds, corrupted normalized IDs, missing raw files and current registry mismatches cannot silently pass.

`system` respects availability and local retrieval time; `source` ignores retrieval only. Different venues, currencies, datasets, report categories and explicit vintages remain separate. Required minimum observations must be satisfied by one stream; versions and unrelated streams are never summed. Ambiguous latest revisions are errors, even though one deterministic record is retained for diagnostic counts. Null is missing; zero is a value. Synthetic input fails the real-data gate unless explicitly allowed; mixed real/synthetic stores always fail.

The policy is validated from `config/quality_policy.yaml` and its canonical hash is in every report. `max_age_hours` accepts kind keys and `series:<id>` overrides. Age means reference-period age, not proof a provider missed a release. Daily gaps compare elapsed calendar hours only. No exchange-specific trading-session completeness is claimed. Missing policy thresholds mean freshness is not assessed for that stream, not that it is fresh.

Exit codes: **0** for pass or warnings, **3** for a completed quality report with failures or a partial/failed `fetch-fred-core` batch, **2** for command/input/system errors. Passing quality does not clear source licensing or prove historical publication times. `macro-context` statuses describe availability, not a quality certification. Keep real reports under `local/` and do not upload derived data automatically.

Explicit credentials loading uses `--credentials-file local/credentials.env`. Only FRED_API_KEY and ALPHAVANTAGE_API_KEY are supported; values are scoped to the command and restored afterward. No shell expressions are evaluated. `fetch-alpha-gold` uses the same acquisition trace as the other ingestion commands and makes a single request without automatic retries.

Quality report schema 1.1 adds `date_only_prices` and `weekend_date_labels` to stream inventories. Daily-close data triggers `DATE_ONLY_PRICE`; an instrument-convention unit triggers `UNIT_INFERRED`; retained Saturday/Sunday labels trigger `WEEKEND_DATE_LABELS`. These are explicit limitations, not requests to discard rows. `config/quality_daily_close.yaml` is a separate onboarding profile; it does not weaken the default OHLC policy. `scripts/inspect_onboarding.py` additionally verifies all stored gold/FRED values and dates against raw pointers, checks that each acquired raw row is represented, and records yearly calendar/null counts without another network request. Reconciliation failure returns 3. It does not establish independent price accuracy or historical release instants.
