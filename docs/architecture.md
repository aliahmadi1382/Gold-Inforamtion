# Architecture

```mermaid
flowchart LR
    P[Provider / entitled local file] --> R[Raw bytes + SHA-256]
    R --> A[Adapter and normalization]
    A --> V[Typed validation]
    V --> S[SQLite versioned records]
    S --> T[As-of eligibility and revision selection]
    T --> F[Causal technical features]
    F --> M[Evidence-linked research snapshot]
    S --> E[Descriptive event windows]
    S --> Q[As-of coverage and quality report]
    R --> I[Acquisition run manifest]
    S --> I
    S --> L[Explicit rights check]
    L --> X[Public export]
```

`src/gold_intelligence` groups actual code by responsibility: contracts (`models`), rights (`registry`), immutable raw/transactional normalization (`storage`), adapters (`ingestion`), operation manifests (`acquisition`), coverage checks (`quality`), scoped key loading (`credentials`), features and event research (`analysis`), market state (`snapshot`), and executable commands (`cli`). This replaces empty `ingestion/lbma`, `agents/*` and similar directories in the original sketch with an installable package. Future integrations belong here or in documented services when they exist.

## Storage and reproducibility

Default runtime path is `local/market`, ignored by Git. Raw filenames equal their SHA-256. SQLite rows contain a content hash ID, record kind and canonical JSON; input metadata and retrieval time form part of identity. Inserting the exact same record is idempotent. A later retrieval is a new provenance version; snapshot selection collapses price revisions by bar time. A conflicting same-time revision fails instead of selecting arbitrarily. One import validates the complete batch before a single database transaction. Failed imports may retain raw bytes for inspection but no partial normalized batch.

Logical zones are raw (original bytes), bronze (parsed provider records), silver (normalized contracts), gold (snapshots), derived (versioned features/research) and events (cited metadata). Release 0.5 materializes raw blobs, silver records and acquisition manifests in the local store; bronze parsing is in memory and snapshot/quality output is explicit. It does not operate a distributed lakehouse. Large data later moves to partitioned Parquet/object storage with manifest hashes and migrations.

CLI acquisition records start and terminal status with atomic manifest replacement. Store instrumentation captures raw hashes and normalized IDs, including exact duplicates, without serializing API keys or exception messages. A process crash can leave a `running` manifest; manifests and SQLite are not a distributed transaction. Quality checks inspect all stored record/raw integrity while computing coverage only from as-of eligible versions. Separate venue, contract, unit, vintage and source identities are not pooled to satisfy coverage. The [quality guide](quality-operations.md) defines the limits.

Each snapshot records every contributing price/observation record ID, feature version and parameters. IDs link to SQLite payloads, then raw hash and row locator, then source URL. `gold audit` verifies referenced bytes. Data and derived exports outside the repo must preserve these references and source rights. Feature configuration/code changes require a feature-version bump and regression checks.

## Current operational boundaries

Release 0.4 adds `macro.py` for metadata-gated FRED sets and point-in-time scalar selection, `world_bank.py` for read-only monthly gold ingestion, and `comparison.py` for a separate monthly diagnostic. Macro reference dates do not become release timestamps. Monthly gold is an `Observation` with a methodology dimension, not a `PriceClose` or `PriceBar`. `scripts/inspect_history.py` also reconciles workbook cells and verifies acquisition metadata hashes; the base `Store.audit` only checks bytes referenced by records. Batch FRED acquisition is atomic per series, not across the whole set.

Offline CI has no credentials. FRED, Alpha Vantage gold history and World Bank monthly gold are network adapters; bounded requests, finite response size and explicit errors keep failures visible. Alpha Vantage has its own module, `alpha_vantage.py`, and a separate date-only `PriceClose` contract. Its records never enter OHLC calculations. CFTC supports a local legacy CSV and the separate public disaggregated gold API in `cftc.py`. No cron service, broker, API server, LLM, vector store or dashboard is running. SQLite reads are intended for research-sized batches; scalable indexing/partitioning and a migration framework belong to later releases.

`release_calendar.py` ingests explicit reviewed timing notes into the existing calendar contract. It verifies source URLs, local offsets, raw-note hashes and as-of eligibility, then selects the newest captured schedule before applying the horizon. `brief.py` combines quality, macro and calendar outputs into a local Persian Markdown/JSON brief. It does not call a model, subscribe to a calendar, send notifications or rewrite observation availability. BLS original-file downloading is not claimed.

`monthly_research.py` selects current revisions known at an explicit cutoff, validates five compatible streams, aggregates complete months, and derives adjacent-month changes. It preserves the World Bank method break, missingness and common-sample membership through summary and rolling correlations. The Persian report and typed evidence JSON remain local. The run fingerprint binds software version, plan, cutoff and selected record IDs; `scripts/inspect_monthly_research.py` independently reconciles the reported arithmetic against SQLite inputs. This descriptive view is separate from historical-release replay and daily execution-price research.

`release_values.py` normalizes reviewed BLS archive values into separate macro observation series, retaining document number, header clock, capture and reissue status. It reconstitutes whole evidence bundles and selects the latest capture before comparing values with exact-date FRED vintages and current revisions. CPI headline changes require two index parents from the same vintage. The comparison verifies raw response vintage metadata, native units and row values; all parent IDs are included in the report. Original records and availability clocks remain immutable. BLS evidence hashes cover reviewed JSON extracts, not original HTML, and agreement does not promote an embargo clock to measured delivery.

`revision_ledger.py` adds a declared-window audit of the same reference period across adjacent headline documents. It shares whole-bundle integrity validation with `release_values.py`, retains all eligible capture versions, and chooses the latest entire capture per URL. Separate document slots expose absent or ambiguous candidates; the final planned period requires a following headline document. Pair values and native FRED vintage parents remain linked. Same-URL recaptures are reported separately from cross-document differences. The independent `scripts/inspect_revision_ledger.py` checks complete-ledger raw cells and rational arithmetic without importing either production calculation module. Report completeness never certifies first-release status or historical availability.

`research_report.py` orchestrates these engines without reimplementing their calculations. One explicit UTC cutoff and SQLite read transaction bind quality, macro, calendar, monthly, release-value and revision outputs. Price coverage is a seventh section derived from quality streams. External raw files remain immutable hash-addressed evidence; they are checked but not database-snapshotted. A preexisting transaction is rejected without rolling it back. Integrity failures abort; normal absence can produce a partial report. No prior report files or network requests supply missing components.

The typed aggregate binds settings, registry hash, software version, child cutoffs and derived section states. Its semantic fingerprint excludes generation clocks but retains capture/retrieval times and selected evidence. The writer materializes eleven files and a manifest under a unique `.incomplete-*` directory, verifies them, then renames within the output directory. Failed writes may retain the staging directory; prior runs and unlisted reader notes are preserved. This is a completed-bundle publication boundary, not a power-loss durability guarantee. `verify-report` needs only the bundle and checks byte hashes and JSON coherence; source authenticity and independent arithmetic require separate evidence. Large child reports are duplicated in the aggregate intentionally for a self-contained typed record; the database/raw store is not copied.

`report_comparison.py` consumes saved reports through `load_verified_report`, which returns the same bytes that passed manifest validation. Context differences cover cutoff, settings, software and registry. Semantic keys align streams, periods, methods, sample populations, documents and revision pairs without positional joins. Generation clocks and derived fingerprints are excluded from content differences; record-ID lists are sorted without erasing multiplicity. Duplicate row keys fail. Parent JSON pointers retain the original array locations, while projection separates collections from summaries to avoid counting their entire contents twice. Age and evidence fields are tagged, not causally explained.

Comparisons write four artifacts plus a manifest to a new directory after staging and verification. Two exact source JSON snapshots make `verify-comparison` independent of source paths and the database: it checks bytes and recomputes the typed comparison. Source bundle files beyond those JSON snapshots are not copied or re-audited later; the initial source-bundle verification remains a creation-time check. The comparison fingerprint excludes its generation clock and source locations, but binds input byte hashes and comparator/software versions. Markdown is a bounded view; JSON retains all differences. Price inventory is explicitly a coverage comparison, not a record-value inventory.

`cftc.py` captures metadata, count responses and bounded ordered pages, validates stable visible revision markers and full balances, then inserts one complete batch. Each positioning record references a hashed capture document linking the original raw parts; `Store.audit` checks the immediate capture hash, while `positioning_context` follows and reconciles the complete chain. `positioning.py` selects whole five-category report versions known at the cutoff and writes a separate Persian/JSON report. Its freshness policy uses observation-date age; historical release clocks remain unknown. Unified report/comparison integration requires a later schema-versioned change.
