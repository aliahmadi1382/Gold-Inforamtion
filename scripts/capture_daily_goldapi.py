"""Manually collect one weekday quote inside the date-specific UTC hour."""

import argparse
import os
from pathlib import Path

from gold_intelligence.daily_capture import capture_daily

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", type=Path, default=Path("local/credentials.env"))
    args = parser.parse_args()
    key = os.environ.get("GOLDAPI_API_KEY")
    if not key and args.credentials.exists():
        for line in args.credentials.read_text(encoding="utf-8-sig").splitlines():
            if line.strip().startswith("GOLDAPI_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    try:
        folder = capture_daily(Path("local/goldapi-daily"), key)
    except (ValueError, OSError) as exc:
        raise SystemExit(f"Daily capture not completed: {exc}") from None
    print(f"Daily evidence saved privately: {folder}; no orders or scheduler.")
