"""Reconcile saved phase-3 history and produce a local, reproducible research receipt.

No network access or credentials; run from the repository root.
"""

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from inspect_onboarding import inspect

from gold_intelligence.acquisition import AcquisitionRun
from gold_intelligence.comparison import compare_monthly, latest_periods
from gold_intelligence.ingestion import timestamp
from gold_intelligence.macro import load_plan, macro_context
from gold_intelligence.quality import load_policy
from gold_intelligence.registry import load_registry
from gold_intelligence.storage import Store, record_id
from gold_intelligence.world_bank import parse_monthly_gold


def inspect_history(store, registry, as_of, policy, plan):
    onboarding = inspect(store, registry, as_of, policy)
    checked_raw = set()
    for path in (store.root / "runs").glob("*.json"):
        run = AcquisitionRun.model_validate_json(path.read_bytes())
        if path.stem != run.run_id:
            raise ValueError("manifest filename mismatch")
        for digest in run.raw_sha256:
            if digest not in checked_raw:
                if hashlib.sha256((store.root / "raw" / digest).read_bytes()).hexdigest() != digest:
                    raise ValueError("acquisition raw evidence mismatch")
                checked_raw.add(digest)
    inventory, vintages, monthly_raw = defaultdict(list), [], defaultdict(list)
    for r in store.read("observation", as_of):
        p = r.provenance
        if p.source_id not in {"fred", "world_bank_pink_sheet"}:
            continue
        inventory[(p.source_id, r.series_id, str(r.vintage_date))].append(r)
        if p.source_id == "world_bank_pink_sheet":
            monthly_raw[(p.raw_sha256, p.retrieved_at)].append(r)
        if r.vintage_date:
            vintages.append(r)
    monthly_matches = 0
    for (digest, retrieved), records in monthly_raw.items():
        reparsed = parse_monthly_gold(
            (store.root / "raw" / digest).read_bytes(),
            registry.get("world_bank_pink_sheet"),
            digest,
            retrieved,
        )
        if {record_id(r) for r in reparsed} != {record_id(r) for r in records}:
            raise ValueError("monthly raw-cell reconciliation or coverage mismatch")
        monthly_matches += len(records)
    profiles, latest_values = [], {}
    for (source, series, vintage), records in sorted(inventory.items()):
        unique = latest_periods(records)
        profiles.append(
            {
                "source": source,
                "series": series,
                "vintage": None if vintage == "None" else vintage,
                "record_versions": len(records),
                "unique_periods": len(unique),
                "first_date": unique[0].provenance.observed_at.date().isoformat(),
                "last_date": unique[-1].provenance.observed_at.date().isoformat(),
                "missing_values": sum(r.value is None for r in unique),
                "units": sorted({r.provenance.unit for r in unique}),
            }
        )
        if vintage == "None":
            for r in unique:
                latest_values[(source, series, r.provenance.observed_at)] = r
    revision_example = []
    for old in sorted(vintages, key=lambda r: (r.series_id, r.provenance.observed_at)):
        current = latest_values.get(
            (old.provenance.source_id, old.series_id, old.provenance.observed_at)
        )
        revision_example.append(
            {
                "series": old.series_id,
                "reference_date": old.provenance.observed_at.date().isoformat(),
                "vintage": str(old.vintage_date),
                "vintage_value": old.value,
                "current_value": current.value if current else None,
                "changed": old.value != current.value if current else None,
                "vintage_record_id": record_id(old),
                "current_record_id": record_id(current) if current else None,
            }
        )
    return {
        "schema_version": "1.0.0",
        "as_of": as_of.isoformat(),
        "status": onboarding["status"],
        "backtest_ready": False,
        "onboarding": onboarding,
        "history_inventory": profiles,
        "acquisition_raw_blobs_verified": len(checked_raw),
        "monthly_raw_cells_matched": monthly_matches,
        "macro_context": macro_context(store, plan, as_of).model_dump(mode="json"),
        "historical_cutoff_check": macro_context(
            store, plan, datetime(2020, 3, 20, tzinfo=UTC), "source"
        ).model_dump(mode="json"),
        "revision_example": revision_example,
        "monthly_comparison": compare_monthly(store, as_of),
        "open_gates": [
            "Alpha Vantage historical unit/session/weekend methodology confirmation",
            "Verified release timestamps and historical vintage coverage for research joins",
            "Comparable daily price evidence; monthly agreement is insufficient",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=Path("local/market"))
    parser.add_argument("--registry", type=Path, default=Path("sources/source_registry.yaml"))
    parser.add_argument("--policy", type=Path, default=Path("config/quality_history.yaml"))
    parser.add_argument("--plan", type=Path, default=Path("config/macro_core.yaml"))
    parser.add_argument("--as-of", type=timestamp)
    parser.add_argument("--output", type=Path, default=Path("local/market/history-report.json"))
    args = parser.parse_args()
    with Store(args.store) as store:
        report = inspect_history(
            store,
            load_registry(args.registry),
            args.as_of or datetime.now(UTC),
            load_policy(args.policy),
            load_plan(args.plan),
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
                "history_inventory": report["history_inventory"],
                "monthly_raw_cells_matched": report["monthly_raw_cells_matched"],
                "macro_context_status": report["macro_context"]["status"],
                "comparison": report["monthly_comparison"]["summary"],
                "backtest_ready": report["backtest_ready"],
            },
            indent=2,
        )
    )
    return 3 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
