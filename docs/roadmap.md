# Roadmap and release gates

| Milestone | Completion evidence | External dependency |
| --- | --- | --- |
| 0.1 Research foundation | Offline demo, schema/lineage/as-of tests, source audit, complete ten-layer specification | Delivered code; no market-data completeness claim |
| 0.2 Acquisition trace and quality | Per-run manifests, stream inventories, revision/time/integrity checks, scoped credentials, Persian education and CI | Delivered software; tested with offline fixtures and synthetic data |
| 0.3 First live acquisition | Alpha Vantage daily-close connector, distinct price contract, live FRED sample, raw-row reconciliation, year profiles and documented warnings | Received locally; session/calendar/unit interpretation remains limited |
| 0.4 Historical acquisition and macro context | Seven metadata-gated FRED histories, vintage example, World Bank monthly gold, full raw reconciliation and cutoff-aware macro selection | Delivered locally; daily unit/session/calendar and historical release verification remain open |
| 0.5 Reviewed calendar and Persian brief | Official BLS timing-evidence importer, New York/UTC/Tehran clocks, schedule-version selection and local evidence-linked Markdown/JSON report | Manual web extracts; original downloads returned 403; no promotion to actual release or economic-value availability |
| Analyst integrations | CFTC disaggregated, WGC/ETF/reserves/physical feeds, official calendar, entitled news, per-series freshness, observed operational reliability | Provider access and consistent release metadata |
| Cross-asset research | Vintage-aware joins, rolling sensitivities, uncertainty, validated regimes, multi-asset event studies, reproducible experiment registry | Sufficient comparable history |
| Evidence-grounded agents | Retrieval/claim citations, tools scoped by role, uncertainty and adversarial-input evaluations | Chosen LLM/model budget; no order access |
| Decision research | Out-of-sample strategy report, costs, calibration, risk policy, paper/shadow operation | Instrument/venue/risk choices |
| Execution | Tested kill switch, daily-loss/exposure enforcement, reconciliation, idempotent orders, rollback/runbook and explicit commissioning | Broker, account authorization and separate review |

The owner confirmed daily XAU/USD first, shorter timeframes later, and free/public sources only. Personal free API keys for Alpha Vantage and FRED were supplied locally and both connectors were verified live on 2026-10-05. Release 0.4 expands seven macro histories and adds a distinct monthly reference. Gold history supplies date-labeled closes, not complete OHLC. The next gate is explaining its calendar change/weekend prices and inferred units, obtaining comparable daily price evidence and verifying historical releases. The monthly comparison and vintage example do not clear these gates. See the [phase-3 evidence](source-methodology/history-acquisition.fa.md).

The [Persian execution phases](phases.fa.md) split these broader milestones into ordered deliveries and track their current status. Each delivery includes an [education chapter](education/README.fa.md). Additional timeframes, contracts, order-book data and options follow verified daily coverage. None of these milestones is silently scheduled or represented as finished.
