"""Manually capture one spot quote for source review; never trade or automatically retry."""

import argparse
import os
from pathlib import Path

from gold_intelligence.forward_quotes import capture_spot

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", type=Path, default=Path("local/credentials.env"))
    parser.add_argument("--output-root", type=Path, default=Path("local/forward-quotes"))
    args = parser.parse_args()
    key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not key and args.credentials.exists():
        for line in args.credentials.read_text(encoding="utf-8-sig").splitlines():
            if line.strip().startswith("ALPHAVANTAGE_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    try:
        target = capture_spot(args.output_root, key)
    except (ValueError, OSError):
        raise SystemExit(
            "Capture failed or quote rejected; no retry. Check the private receipt where available."
        ) from None
    print(f"Spot source evidence saved: {target}; trading eligibility remains false.")
