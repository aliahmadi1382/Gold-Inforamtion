"""Manually run the fixed daily capture protocol and its offline evidence review."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from gold_intelligence.daily_cycle import run_daily_cycle

if __name__ == "__main__":
    key = os.environ.get("GOLDAPI_API_KEY")
    credentials = Path("local/credentials.env")
    if not key and credentials.exists():
        for line in credentials.read_text(encoding="utf-8-sig").splitlines():
            if line.strip().startswith("GOLDAPI_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    result = run_daily_cycle(Path("local/goldapi-daily"), key)
    target = Path("local/daily-cycles") / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    target.mkdir(parents=True, exist_ok=False)
    (target / "cycle.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Cycle: {result['capture_outcome']}; research: {result['research']['status']}.")
    print(f"Private evidence: {target}; no retries, scheduler or orders.")
