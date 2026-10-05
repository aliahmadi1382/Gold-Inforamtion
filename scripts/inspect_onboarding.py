"""Read-only reconciliation of onboarded prices/macros to raw JSON; local output only.

Run from the repository root with uv run python scripts/inspect_onboarding.py.
This uses saved bytes and makes no API requests. No credential file is opened.
"""

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from gold_intelligence.acquisition import list_runs
from gold_intelligence.ingestion import timestamp
from gold_intelligence.quality import assess, load_policy
from gold_intelligence.registry import load_registry
from gold_intelligence.storage import Store, record_id


def inspect(store, registry, as_of, policy):
    audit = store.audit()
    quality = assess(store, registry, as_of, policy)
    raw = {}
    matched = 0
    mismatches = []
    pointers = defaultdict(set)
    yearly = defaultdict(list)
    source_ids = set()
    for kind in ("price_close", "observation"):
        for record in store.read(kind, as_of):
            p = record.provenance
            if p.source_id not in {"alpha_vantage_gold", "fred"}:
                continue
            source_ids.add(p.source_id)
            if p.raw_sha256 not in raw:
                raw[p.raw_sha256] = json.loads((store.root / "raw" / p.raw_sha256).read_bytes())
            payload = raw[p.raw_sha256]
            field, index = p.raw_record_id.split(":")
            index = int(index)
            row = payload[field][index]
            pointers[(p.source_id, p.raw_sha256, field)].add(index)
            if p.source_id == "alpha_vantage_gold":
                correct = (
                    payload["nominal"] == record.instrument == "XAUUSD"
                    and row["date"] == record.session_date.isoformat() == p.original_timestamp
                    and float(row["price"]) == record.close
                )
                series = record.instrument
                missing = False
            else:
                value = None if row["value"] == "." else float(row["value"])
                correct = (
                    row["date"] == p.observed_at.date().isoformat() == p.original_timestamp
                    and value == record.value
                    and row["realtime_start"] == record.dimensions["realtime_start"]
                    and row["realtime_end"] == record.dimensions["realtime_end"]
                )
                series = record.series_id
                missing = record.value is None
            if correct:
                matched += 1
            else:
                mismatches.append(record_id(record))
            yearly[(p.source_id, series, p.observed_at.year)].append(
                (p.observed_at.date(), missing)
            )
    coverage = []
    for (source, digest, field), indexes in sorted(pointers.items()):
        expected = len(raw[digest][field])
        coverage.append(
            {
                "source_id": source,
                "raw_sha256": digest,
                "field": field,
                "raw_rows": expected,
                "represented_raw_rows": len(indexes),
                "complete": indexes == set(range(expected)),
            }
        )
    profiles = []
    for (source, series, year), rows in sorted(yearly.items()):
        dates = {day for day, _ in rows}
        weekends = {day for day in dates if day.weekday() >= 5}
        profiles.append(
            {
                "source_id": source,
                "series": series,
                "year": year,
                "record_versions": len(rows),
                "unique_dates": len(dates),
                "first_date": min(dates).isoformat(),
                "last_date": max(dates).isoformat(),
                "weekend_date_count": len(weekends),
                "weekend_date_fraction": len(weekends) / len(dates),
                "first_weekend_date": min(weekends).isoformat() if weekends else None,
                "null_versions": sum(missing for _, missing in rows),
            }
        )
    reconciled = bool(matched) and not mismatches and all(r["complete"] for r in coverage)
    return {
        "schema_version": "1.0.0",
        "as_of": as_of.isoformat(),
        "status": "fail" if quality.status == "fail" or not reconciled else quality.status,
        "scope": (
            "Acquisition readiness, not session/calendar, economic accuracy "
            "or backtest certification"
        ),
        "sources": [registry.get(s).model_dump(mode="json") for s in sorted(source_ids)],
        "audit": audit,
        "quality": quality.model_dump(mode="json"),
        "reconciliation": {
            "status": "pass" if reconciled else "fail",
            "matched_record_versions": matched,
            "mismatched_record_ids": mismatches,
            "raw_row_coverage": coverage,
            "meaning": (
                "Stored values/date labels match saved provider bytes; "
                "no independent price-source validation"
            ),
        },
        "yearly_profile": profiles,
        "acquisitions": list_runs(store.root),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=Path("local/market"))
    parser.add_argument("--registry", type=Path, default=Path("sources/source_registry.yaml"))
    parser.add_argument("--policy", type=Path, default=Path("config/quality_daily_close.yaml"))
    parser.add_argument("--as-of", type=timestamp)
    parser.add_argument("--output", type=Path, default=Path("local/market/onboarding-report.json"))
    args = parser.parse_args()
    with Store(args.store) as store:
        report = inspect(
            store,
            load_registry(args.registry),
            args.as_of or datetime.now(UTC),
            load_policy(args.policy),
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "as_of": report["as_of"],
                "report": str(args.output),
                "matched_record_versions": report["reconciliation"]["matched_record_versions"],
                "reconciliation": report["reconciliation"]["status"],
                "issues": [i["code"] for i in report["quality"]["issues"]],
            },
            indent=2,
        )
    )
    return 3 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
