"""Export a report-bound draft protocol, offline; never execute the study."""

import argparse
import json
from pathlib import Path

from gold_intelligence.event_study_plan import build_event_study_plan
from gold_intelligence.research_report import load_verified_report

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    _, _, content = load_verified_report(args.bundle)
    result = build_event_study_plan(content)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print("Draft protocol exported; study not executed and readiness remains false.")
