"""Replay verified real observations as an offline hypothetical account."""

import argparse
import json
from pathlib import Path

from gold_intelligence.real_paper import evaluate_real_paper

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("local/goldapi-quotes"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = evaluate_real_paper(args.input)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as file:
            file.write(json.dumps(report, indent=2) + "\n")
    except (ValueError, OSError):
        raise SystemExit("Invalid evidence or existing output; no result overwritten.") from None
    print(f"Offline account evaluated: {len(report['fills'])} hypothetical fills; no broker.")
