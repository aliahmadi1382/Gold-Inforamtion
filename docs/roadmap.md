# Roadmap and release gates

| Milestone | Completion evidence | External dependency |
| --- | --- | --- |
| 0.1 Research foundation | Offline demo, schema/lineage/as-of tests, source audit, complete ten-layer specification | Delivered code; no market-data completeness claim |
| Historical acquisition | Dataset inventory with real coverage/gaps, sample reconciliation, rights decisions and retrieval manifests | Price source, archives, licenses, FRED key |
| Analyst integrations | CFTC disaggregated, WGC/ETF/reserves/physical feeds, official calendar, entitled news, per-series freshness, observed operational reliability | Provider access and consistent release metadata |
| Cross-asset research | Vintage-aware joins, rolling sensitivities, uncertainty, validated regimes, multi-asset event studies, reproducible experiment registry | Sufficient comparable history |
| Evidence-grounded agents | Retrieval/claim citations, tools scoped by role, uncertainty and adversarial-input evaluations | Chosen LLM/model budget; no order access |
| Decision research | Out-of-sample strategy report, costs, calibration, risk policy, paper/shadow operation | Instrument/venue/risk choices |
| Execution | Tested kill switch, daily-loss/exposure enforcement, reconciliation, idempotent orders, rollback/runbook and explicit commissioning | Broker, account authorization and separate review |

Immediate next step is to select and license the actual XAU/USD source, then import a documented sample and verify it against its provider. Additional timeframes, contracts, order-book data and options are prioritized only after the underlying data rights and quality are known. None of these milestones is silently scheduled or represented as finished.
