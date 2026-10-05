# Brief-to-repository coverage

| Brief requirement | Concrete location | Status / dependency |
| --- | --- | --- |
| Original supplied text | `original-brief.md` | Preserved verbatim; claims separately audited |
| History before 1919, fixing, Bretton Woods, 1968, floating era | `docs/market-history/`, `docs/gold-monetary-history/`, `data/events/` | Era distinctions and cited anchors; no fabricated prices |
| XAU/USD, fixing, GC, Micro Gold, ETF, CFD | `models.PriceBar`, master spec | Validated bar contract; imported source/venue/type kept distinct |
| Options, tick, bid/ask, spread, futures curve, basis, forwards | Master spec, `data-contracts.md` | Scalar research measures supported; dedicated quote/chain adapters and contracts planned |
| Higher highs/lows, trend, range, breakout/breakdown | `analysis.technical_features` | Implemented delayed pivots, MA trend, prior-window boundaries |
| Liquidity, supply/demand, mean reversion, regime ML | `docs/market-structure/` | Research definitions; not inferred as facts from OHLC |
| COT long/short/spread/OI/net/categories | `ingestion.import_cftc`, `models.Positioning` | Legacy futures-only implemented; managed-money/disaggregated adapter planned |
| COT changes, concentration and crowded trades | `docs/market-structure/` | Future features with same-family history and declared window |
| USD, rates, real yields, inflation, labor, activity | `config/macro_series.yaml`, `ingest_fred` | 22-series shortlist and adapter; live key required |
| DXY, ISM, PMI, confidence, Fed expectations | `docs/macro-drivers/` | Separate providers/methods needed; no proxy silently relabelled |
| Central-bank buying, sales, reserves | `models.Observation`, source registry | Contract and provenance; WGC/IMF import pending rights review |
| ETF holdings, inflows/outflows | Observation contract, source registry | Fund and metric dimensions required; acquisition planned |
| Mine, recycling, jewellery, bars/coins, technology, premiums | Observation contract, master spec | Country/sector/unit definitions; acquisition planned |
| News vs event, geopolitics, transmission channels | `models.NewsEvent`, methodology | Validated contract; feed, deduplication and NLP planned |
| Calendar, consensus, previous, actual, surprise | `models.CalendarRelease` | Release and consensus-time validation; live connector planned |
| Historical event reactions, drawdown, recovery | `analysis.event_study`, `data/events/` | Single-stream descriptive windows implemented; cross-asset study planned |
| Full market-state representation | `snapshot.py`, JSON Schema | Technical and numeric context; missing layers visible; research-only output |
| Four agent phases | Master spec, roadmap | Research foundation implemented; agent orchestration and LLM integration planned |
| Risk controls, kill switch and broker isolation | `docs/trading-methodology/` | Execution acceptance requirements; no live order code |
| Source, timestamp, unit, license, confidence, lineage | `models.Provenance`, `storage.py`, `registry.py` | Validated contracts and raw-to-record audit |
| Raw/bronze/silver/gold/derived architecture | `docs/architecture.md`, `data/*/README.md` | Local store materializes raw and normalized; logical future zones documented |
| Public/licensed/restricted data | Registry, `export-public`, Git ignore and publication check | Default-deny export and tracked data guard; no commercial datasets committed |
| Seven initial questions | `config/project.yaml`, master spec | Defaults explicit; instruments/broker/budget need owner selection |

“Contract” means a validated schema, not an operational data feed. “Planned” means there is no working implementation claimed for that feature. The repo intentionally uses one installable Python package instead of empty top-level directories for every future service.
