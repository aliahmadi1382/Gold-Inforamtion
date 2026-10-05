# Roadmap and release gates

| Milestone | Completion evidence | External dependency |
| --- | --- | --- |
| 0.1 Research foundation | Offline demo, schema/lineage/as-of tests, source audit, complete ten-layer specification | Delivered code; no market-data completeness claim |
| 0.2 Acquisition trace and quality | Per-run manifests, stream inventories, revision/time/integrity checks, scoped credentials, Persian education and CI | Delivered software; tested with offline fixtures and synthetic data |
| Historical acquisition | Dataset inventory with real coverage/gaps, sample reconciliation, rights decisions and retrieval manifests | Price source, archives, licenses, FRED key |
| Analyst integrations | CFTC disaggregated, WGC/ETF/reserves/physical feeds, official calendar, entitled news, per-series freshness, observed operational reliability | Provider access and consistent release metadata |
| Cross-asset research | Vintage-aware joins, rolling sensitivities, uncertainty, validated regimes, multi-asset event studies, reproducible experiment registry | Sufficient comparable history |
| Evidence-grounded agents | Retrieval/claim citations, tools scoped by role, uncertainty and adversarial-input evaluations | Chosen LLM/model budget; no order access |
| Decision research | Out-of-sample strategy report, costs, calibration, risk policy, paper/shadow operation | Instrument/venue/risk choices |
| Execution | Tested kill switch, daily-loss/exposure enforcement, reconciliation, idempotent orders, rollback/runbook and explicit commissioning | Broker, account authorization and separate review |

The owner confirmed daily XAU/USD first, shorter timeframes later, and free/public sources only. The selected onboarding route is personal free API keys for Alpha Vantage and FRED. The next gate is local key availability, a successful real response, and verification of instrument, units, timestamps, coverage and terms. Alpha Vantage's documented gold history provides closing prices; it must not be passed off as complete OHLC. Its connector is pending real-response validation; FRED's existing connector still needs a live check.

The [Persian execution phases](phases.fa.md) split these broader milestones into ordered deliveries and track their current status. Each delivery includes an [education chapter](education/README.fa.md). Additional timeframes, contracts, order-book data and options follow verified daily coverage. None of these milestones is silently scheduled or represented as finished.
