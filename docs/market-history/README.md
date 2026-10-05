# Gold market history as distinct series

| Era | Research meaning | Data rule |
| --- | --- | --- |
| Early monetary/wholesale history, before 1919 | Institutional evidence, official parity, local monetary systems and London wholesale history | Retain original currency, purity, weight, source and date precision; no invented daily prices |
| London fixing from 1919 | A specific benchmark mechanism, with interruptions and changes over time | Do not splice a GBP fixing into modern USD spot without an explicit conversion and regime label |
| Bretton Woods | Official monetary arrangements and restricted convertibility | Separate official parity from market-traded observations |
| 1968 two-tier transition | Official monetary price and private-market price diverge | Distinct series and regime metadata |
| 1971/1973 transitions | Convertibility suspension and broader floating-exchange-rate transition | Event anchors are different dates, not a single universal series start |
| Modern OTC/exchange/ETF era | Venue-specific benchmarks, dealer prices, futures and fund shares | Preserve instrument, venue, session, expiry, price type and rights |

The [first fixing](https://www.lbma.org.uk/wonders-of-gold/items/the-first-gold-fixing), [1968 split](https://www.lbma.org.uk/wonders-of-gold/items/march-1968-and-the-london-gold-fixing), and [1971 suspension](https://www.federalreservehistory.org/essays/gold-convertibility-ends) provide cited anchors. They do not establish continuous downloadable coverage. See the source audit for dates and corrections.

An archival acquisition manifest should state first/last actual observation, gaps, calendar, extraction method, digitization/OCR checks, revision status and rights. Never interpolate centuries of monetary history into a modern trading backtest. The repository's historical seed file contains event metadata, not a verified historical gold-price dataset.
