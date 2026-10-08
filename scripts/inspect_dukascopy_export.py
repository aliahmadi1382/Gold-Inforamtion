"""Offline audit of the official widget's manually exported UTC hourly BID CSV."""

import argparse
import json
from datetime import date, datetime
from pathlib import Path

from gold_intelligence.dukascopy_review import review_hourly_bid

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--retrieved-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.input.name.startswith("XAU-USD_1Hour_BID_"):
        parser.error("requires an explicitly named XAU-USD hourly BID export")
    result = review_hourly_bid(args.input.read_bytes(), args.start, args.end, args.retrieved_at)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(f"Verified structure of {result['rows']} hourly rows; daily readiness remains false.")
