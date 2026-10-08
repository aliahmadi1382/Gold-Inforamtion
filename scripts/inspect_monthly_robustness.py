"""Derive reproducible monthly sensitivity diagnostics from a verified bundle, offline."""

import argparse
import hashlib
import json
from pathlib import Path

from gold_intelligence.monthly_robustness import monthly_robustness
from gold_intelligence.research_report import load_verified_report

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report, _, content = load_verified_report(args.bundle)
    result = monthly_robustness(report)
    result["report_sha256"] = hashlib.sha256(content).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(f"Reviewed {len(result['influence'])} sensitivity groups, offline.")
