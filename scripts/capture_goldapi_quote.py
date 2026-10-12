"""Capture one private GoldAPI quote manually, without retries or trading."""

import argparse
import os
from pathlib import Path

from gold_intelligence.goldapi_capture import capture_goldapi

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", type=Path, default=Path("local/credentials.env"))
    parser.add_argument("--output-root", type=Path, default=Path("local/goldapi-quotes"))
    args = parser.parse_args()
    key = os.environ.get("GOLDAPI_API_KEY")
    if not key and args.credentials.exists():
        for line in args.credentials.read_text(encoding="utf-8-sig").splitlines():
            if line.strip().startswith("GOLDAPI_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    try:
        folder = capture_goldapi(args.output_root, key)
    except (ValueError, OSError):
        raise SystemExit(
            "Capture failed; no retry. Inspect private receipt where available."
        ) from None
    print(f"Private quote evidence saved: {folder}; trading eligibility remains false.")
