"""Evaluate real captured quotes offline; produce shadow decisions without fills."""

import argparse
import json
from pathlib import Path

from gold_intelligence.real_shadow import evaluate_shadow

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("local/goldapi-quotes"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = evaluate_shadow(args.input)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as file:
            file.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    except (ValueError, OSError):
        raise SystemExit("Invalid evidence or existing output; no result overwritten.") from None
    print(f"Shadow evaluated {len(result['decisions'])} real observations; orders disabled.")
