"""Verify all saved GoldAPI captures and write an offline private coverage report."""

import argparse
import json
from pathlib import Path

from gold_intelligence.forward_dataset import build_forward_dataset

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("local/goldapi-quotes"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = build_forward_dataset(args.input)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    except (ValueError, OSError):
        raise SystemExit(
            "Evidence invalid, missing or output exists; no report overwritten."
        ) from None
    print(f"Verified {report['observation_count']} observations; strategy evaluation not run.")
