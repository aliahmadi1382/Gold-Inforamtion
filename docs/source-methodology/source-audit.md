# Source audit of the supplied brief

Checked 2026-10-05 against primary pages. This is an audit of architectural claims, not a full audit of every historical event or a legal opinion. Page accessibility does not grant ingestion, redistribution or model-training rights. Registry `planned` URLs identify candidates; not every listed terms endpoint was reviewed as a license grant.

| Claim in brief | Finding and implementation consequence | Primary source |
| --- | --- | --- |
| First London fixing on 12 September 1919, £4.933/fine troy ounce | Confirmed as a historical fixing milestone; not the birth of all international gold pricing | [LBMA](https://www.lbma.org.uk/wonders-of-gold/items/the-first-gold-fixing) |
| 1968 two-tier system | Confirmed distinction between official monetary transactions and a floating private market; keep regimes separate | [LBMA](https://www.lbma.org.uk/wonders-of-gold/items/march-1968-and-the-london-gold-fixing) |
| 1971/1973 floating era | Dollar-gold convertibility ended 15 August 1971; the wider exchange-rate transition was not a single identical date for all series | [Federal Reserve History](https://www.federalreservehistory.org/essays/gold-convertibility-ends) |
| WGC prices from 1978 | Page describes monthly, quarterly and annual averages in several currencies; do not advertise tick or uninterrupted daily spot history from this claim | [WGC prices](https://www.gold.org/goldhub/data/gold-prices) |
| Historical LBMA prices restricted since 2025 | Page specifies 18 March 2025 and licensing through IBA; no public bulk history is committed | [WGC prices](https://www.gold.org/goldhub/data/gold-prices) |
| COT starts 1986; disaggregated 2009 | Needs report-specific precision: legacy futures-only archive from 1986; combined from March 1995; disaggregated publication from September 2009 with earlier backfill. Pre-September 1992 frequency differs | [CFTC archives](https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm), [backfill](https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalViewable/index.htm) |
| COT report date usable as information date | Incorrect for a historical as-of join; use actual release evidence, including delays, or conservative retrieval time | [CFTC release schedule](https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm) |
| GC represents 100 troy ounces | Confirmed; MGC is 10. Contract quantity is not the quoted per-ounce price or account exposure | [CME](https://www.cmegroup.com/markets/metals/precious/gold-futures.html) |
| 2025 central-bank purchases 863.3 tonnes | The cited table reports 863.3 for **central banks and other institutions**. Treat as that publication's estimate/category, retain vintage, and do not hard-code as a current signal | [WGC full-year 2025](https://www.gold.org/goldhub/research/gold-demand-trends/gold-demand-trends-full-year-2025/central-banks) |
| Linked Reuters report dated 2026-10-05 | Could not be opened in this review; contents and claim remain unverified. It is not imported or used as evidence | Original URL retained only in the supplied brief |
| No usable GitHub connection | Superseded: authenticated repository access was available during implementation | Operational observation, not a market claim |

FRED adapter behavior follows its [observations API](https://fred.stlouisfed.org/docs/api/fred/series_observations.html) and [API key requirements](https://fred.stlouisfed.org/docs/api/api_key.html). Official release schedules such as [BLS CPI](https://www.bls.gov/schedule/news_release/cpi.htm) are preferred over hard-coded recurring local times. The brief's calendar times are examples, not a universal release schedule.

No current gold-price estimate, geopolitical label or trading recommendation has been derived from these pages.
