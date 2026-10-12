"""Offline protocol-bound signal review; no API request or order."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from gold_intelligence.daily_research import review_daily_research

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = review_daily_research(Path("local/goldapi-daily"), datetime.now(UTC))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as file:
        file.write(json.dumps(result, indent=2) + "\n")
    print(f"Daily review status: {result['status']}; no orders.")
