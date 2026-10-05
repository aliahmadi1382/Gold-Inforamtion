# Contributing

Use the frozen uv environment and run the checks in `docs/operations.md`. Add meaningful tests for financial/data semantics, especially publication lag, revisions, schema drift and source mixups. Provider integrations need explicit source registry entries and rights review; never commit credentials, raw commercial data or news corpora.

New fields require versioned contracts and regenerated schemas (`uv run gold schemas`). Preserve raw evidence, identify transformation versions, and update the coverage matrix so planned integrations are not advertised as working. Fixture values must be synthetic or explicitly cleared for redistribution. Network tests must be opt-in and must not require secrets in pull-request CI.

Source audit claims need primary citations and dates. Research conclusions need eligible evidence and uncertainty; a green software test is not proof of an investment strategy. Any broker integration belongs to a separately commissioned phase with deterministic risk controls.
