"""Save an offline fixed-split evaluation of verified pilot quotes; no new acquisition."""

import argparse
import json
from pathlib import Path

from gold_intelligence.strategy_evaluation import evaluate_strategy

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = evaluate_strategy(Path("local/goldapi-quotes"))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as file:
            file.write(json.dumps(report, indent=2) + "\n")
    except (ValueError, OSError):
        raise SystemExit("Evidence invalid or output exists; no evaluation overwritten.") from None
    print(f"Evaluation: {report['status']}; market validity not established.")
