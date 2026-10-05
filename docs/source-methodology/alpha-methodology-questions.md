# Draft questions for Alpha Vantage support

Prepared for the project owner. This document has not been sent. Do not include API keys, account credentials, downloaded price tables or screenshots containing secrets.

Subject: GOLD_SILVER_HISTORY daily GOLD/XAUUSD methodology

We are using the personal free API for local, noncommercial research. Could you clarify the following for `GOLD_SILVER_HISTORY`, `symbol=GOLD`, `interval=daily`, whose response has nominal `XAUUSD` and date/price rows?

1. Is every historical value quoted in USD per troy ounce? Is the unit definition unchanged over the full series?
2. What does the daily `date` represent, and what timezone and closing/reference time define its price?
3. What do Saturday and Sunday values represent: actual observations, carried prices, averages or another calculation?
4. Our acquired history first includes weekend date labels on 2013-03-30. Was there a change in source, instrument, calendar or calculation around that date?
5. Are historical corrections possible, and is an archive of revisions or methodology changes available?
6. Which published methodology explains the underlying reference market and whether this series is suitable for close-to-close return comparisons?

A public methodology URL would be especially helpful. No individual prices or API credentials are needed to answer these questions.
