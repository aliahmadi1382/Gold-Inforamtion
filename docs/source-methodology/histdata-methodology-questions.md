# Draft: conflicting XAUUSD minute rows

Prepared for the project owner; not sent. No credentials, private price tables or account information should be attached.

Subject: Generic ASCII XAUUSD M1 September 2026 — duplicate timestamps with conflicting values

We downloaded HISTDATA_COM_ASCII_XAUUSD_M1202609.zip through the official free download page. The separately downloaded status file matches the status member inside the ZIP.

Our structural review found 29,321 CSV rows, 28,947 unique minute timestamps, 374 additional duplicate rows, 187 reversals of timestamp order and 344 timestamp groups with different values. The first duplicate group includes raw CSV row 306 at source timestamp 20260901 050500. Archive SHA-256: bcd087aa27bdebbd39a00edea0aaf2d230801be6f18f3806ab8d2317ebeebc5a.

Could you provide a corrected archive or explain the meaning and deterministic resolution of these duplicate minute rows? We have not silently sorted, discarded or averaged conflicting prices.

Could you also confirm whether XAUUSD prices are USD per troy ounce, identify the underlying instrument/feed and historical trading-calendar documentation, and describe corrections or revision history? We understand that the file timezone is fixed EST without daylight saving adjustments and that bar prices are based on BID quotes.

This is personal local research, with no request for redistribution, paid access, account creation or model training.
