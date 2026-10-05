# Brief-to-repository coverage

| Brief requirement | Concrete location | Status / dependency |
| --- | --- | --- |
| Original supplied text | `original-brief.md` | Preserved verbatim; claims separately audited |
| History before 1919, fixing, Bretton Woods, 1968, floating era | `docs/market-history/`, `docs/gold-monetary-history/`, `data/events/` | Era distinctions and cited anchors; no fabricated prices |
| XAU/USD, fixing, GC, Micro Gold, ETF, CFD | `models.PriceBar`, master spec | Validated bar contract; imported source/venue/type kept distinct |
| Free daily gold-price history | `alpha_vantage.py`, `models.PriceClose` | Live acquisition verified; date-only closes; unit/session/calendar limits flagged; no fabricated OHLC |
| Options, tick, bid/ask, spread, futures curve, basis, forwards | Master spec, `data-contracts.md` | Scalar research measures supported; dedicated quote/chain adapters and contracts planned |
| Higher highs/lows, trend, range, breakout/breakdown | `analysis.technical_features` | Implemented delayed pivots, MA trend, prior-window boundaries |
| Liquidity, supply/demand, mean reversion, regime ML | `docs/market-structure/` | Research definitions; not inferred as facts from OHLC |
| COT long/short/spread/OI/net/categories | `ingestion.import_cftc`, `models.Positioning` | Legacy futures-only implemented; managed-money/disaggregated adapter planned |
| COT changes, concentration and crowded trades | `docs/market-structure/` | Future features with same-family history and declared window |
| USD, rates, real yields, inflation, labor, activity | `config/macro_core.yaml`, `macro.py`, `ingest_fred` | Seven full macro histories acquired with metadata checks and cutoff selection; 22-series broader shortlist; historical release-time verification remains open |
| Long monthly gold reference | `world_bank.py`, `comparison.py` | Pink Sheet from 1960 acquired locally; separate monthly definition, June 2025 method break and descriptive comparison; no fabricated daily history |
| DXY, ISM, PMI, confidence, Fed expectations | `docs/macro-drivers/` | Separate providers/methods needed; no proxy silently relabelled |
| Central-bank buying, sales, reserves | `models.Observation`, source registry | Contract and provenance; WGC/IMF import pending rights review |
| ETF holdings, inflows/outflows | Observation contract, source registry | Fund and metric dimensions required; acquisition planned |
| Mine, recycling, jewellery, bars/coins, technology, premiums | Observation contract, master spec | Country/sector/unit definitions; acquisition planned |
| News vs event, geopolitics, transmission channels | `models.NewsEvent`, methodology | Validated contract; feed, deduplication and NLP planned |
| Calendar, consensus, previous, actual, surprise | `release_calendar.py`, `release_values.py`, `models.CalendarRelease` | Reviewed BLS schedules and separate document-linked macro values with vintage comparison; calendar actual delivery, consensus, surprise and live refresh still absent |
| Historical event reactions, drawdown, recovery | `analysis.event_study`, `data/events/` | Single-stream descriptive windows implemented; cross-asset study planned |
| Full market-state representation | `snapshot.py`, JSON Schema | Technical and numeric context; missing layers visible; research-only output |
| Four agent phases | Master spec, roadmap | Research foundation implemented; agent orchestration and LLM integration planned |
| Risk controls, kill switch and broker isolation | `docs/trading-methodology/` | Execution acceptance requirements; no live order code |
| Source, timestamp, unit, license, confidence, lineage | `models.Provenance`, `storage.py`, `registry.py` | Validated contracts and raw-to-record audit |
| Acquisition history and coverage | `acquisition.py`, `quality.py`, `config/quality_policy.yaml` | Per-run manifests and per-stream as-of inventories; revision, missingness, integrity and age checks |
| Phased development and owner education | `docs/phases.fa.md`, `docs/education/` | Dependency-aware deliveries, nine Persian chapters, glossary and exercises |
| Cross-document revisions and coverage | `revision_ledger.py`, `config/revision_ledger.yaml` | Fixed-window adjacent-document comparisons with exact-date vintages; complete-capture selection, ambiguity/missingness and separate recapture history; no first-release or delivery-time certification |
| Monthly gold/macro relationships | `monthly_research.py`, `config/monthly_research.yaml` | Current-revision descriptive changes, common/pairwise samples, Pearson/Spearman, contiguous rolling windows, method-break and missingness gates; not causal or predictive research |
| Readable local research status | `brief.py`, `gold research-brief` | Persian Markdown plus evidence JSON; macro and calendar states, missingness and limitations; no trading narrative or recommendation |
| Raw/bronze/silver/gold/derived architecture | `docs/architecture.md`, `data/*/README.md` | Local store materializes raw and normalized; logical future zones documented |
| Public/licensed/restricted data | Registry, `export-public`, Git ignore and publication check | Default-deny export and tracked data guard; no commercial datasets committed |
| Seven initial questions | `config/project.yaml`, master spec | Daily XAU/USD and free personal APIs confirmed; keys supplied locally; broker/risk choices deferred |

“Contract” means a validated schema, not an operational data feed. “Planned” means there is no working implementation claimed for that feature. The repo intentionally uses one installable Python package instead of empty top-level directories for every future service.
