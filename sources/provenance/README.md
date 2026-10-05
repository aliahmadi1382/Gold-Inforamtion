# Acquisition manifest guidance

Keep real manifests beside local raw files, outside the public repository. Record source registry ID, exact public endpoint without credentials, request parameters without secrets, HTTP retrieval time/status, original filename/document version, byte count, SHA-256, observed coverage, units, timezone, parser version, license review reference and quality findings. Preserve the provider file unchanged.

Runtime normalized records already contain the required observation-level provenance, raw hash and row pointer. A snapshot's evidence ID resolves to that normalized record in SQLite. `gold audit` verifies the raw hash chain. The raw file is necessary for independent re-parsing; a source URL alone is insufficient. Calendar publication evidence and manual archival transcription checks should be stored in the acquisition manifest before an observation receives `verified_release` status.
