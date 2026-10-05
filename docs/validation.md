# Release validation

Release 0.1.0 was verified locally on Windows with Python 3.11 using the locked environment. The test suite contains 52 offline cases, including parameterized cases. CI repeats the suite on Windows and Linux with Python 3.11 and 3.12; the GitHub Actions result is the authority for remote status.

Verified behavior includes closed-bar validity, finite values, timezone awareness/DST, raw and normalized content hashes, atomic failed batches, exact-record idempotence, publication/retrieval cutoffs, future revision exclusion, delayed swing confirmation, mixed-stream rejection, price freshness, event-window arithmetic, restricted export, source-registry matching, FRED pagination/missing values/credential-safe errors, CFTC documented column mapping, generated-schema consistency and the repeatable synthetic demo. The source distribution and Python wheel build successfully.

The demo contains 80 fictional bars. Sample files can be regenerated with `uv run gold demo`; the store contains the raw bytes needed to resolve snapshot evidence IDs. Passing these tests verifies software mechanics, not market-data accuracy, statistical strategy performance or profitability.

Live integration limits: no FRED API key was supplied, so FRED is verified through offline response fixtures. The official CFTC ZIP returned HTTP 403 in this environment; its parser is tested with documented headers and synthetic counts. No vendor entitlement or actual gold-price history is bundled. News, calendar, WGC, LBMA and CME automatic connectors are not implemented. Their contracts, sources and remaining work are documented rather than represented as live features.
