"""Inspect a manually acquired HistData archive and its separate status file."""

import argparse
import csv
import hashlib
import io
import json
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from gold_intelligence.histdata_review import review_archive

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--month", required=True)
    parser.add_argument("--retrieved-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    content, status = args.archive.read_bytes(), args.status.read_bytes()
    try:
        result = review_archive(content, status, args.month, args.retrieved_at)
        result["validation_status"] = "accepted_structure"
    except ValueError as exc:
        result = dict(
            validation_status="rejected",
            reason=str(exc),
            daily_backtest_ready=False,
            archive_sha256=hashlib.sha256(content).hexdigest(),
            status_sha256=hashlib.sha256(status).hexdigest(),
            retrieved_at=args.retrieved_at.isoformat(),
            month=args.month,
        )
        if str(exc) == "duplicate or unordered minute":
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                data = archive.read(f"DAT_ASCII_XAUUSD_M1_{args.month}.csv")
            versions = defaultdict(list)
            labels = []
            for line, row in enumerate(csv.reader(io.StringIO(data.decode()), delimiter=";"), 1):
                labels.append(row[0])
                versions[row[0]].append((line, tuple(row[1:])))
            result.update(
                rows=len(labels),
                unique_minutes=len(versions),
                duplicate_extra_rows=sum(len(v) - 1 for v in versions.values()),
                ordering_breaks=sum(b < a for a, b in zip(labels, labels[1:], strict=False)),
                conflicting_minutes=sum(
                    len({values for _, values in v}) > 1 for v in versions.values()
                ),
                duplicate_groups=[
                    dict(source_timestamp=label, raw_rows=[n for n, _ in v])
                    for label, v in versions.items()
                    if len(v) > 1
                ],
                csv_sha256=hashlib.sha256(data).hexdigest(),
            )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(f"Export validation: {result['validation_status']}; receipt: {args.output}")
