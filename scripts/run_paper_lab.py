"""Run synthetic trading mechanics offline; no market source or broker is accessed."""

import argparse
import json
from pathlib import Path

from gold_intelligence.paper_lab import LabSettings, simulate_lab, synthetic_quotes

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initial-cash", type=float, default=10000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = simulate_lab(synthetic_quotes(), LabSettings(initial_cash=args.initial_cash))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print("Synthetic mechanics lab saved; market validation remains false.")
