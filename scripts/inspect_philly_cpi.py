"""Reconcile only headline CPI extracts with native Philadelphia release estimates."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from gold_intelligence.registry import load_registry
from gold_intelligence.release_values import release_value_report
from gold_intelligence.storage import Store, record_id


def review(store, registry, as_of):
    latest = {}
    records = [r for r in store.read("observation", as_of) if r.series_id == "PHILLY_PCPI_FIRST"]
    for record in sorted(records, key=lambda r: (r.provenance.retrieved_at, record_id(r))):
        latest[record.provenance.observed_at.strftime("%Y-%m")] = record
    documents = release_value_report(store, registry, as_of)
    comparisons = []
    for document in documents.documents:
        if document.metric != "cpi_all_items_sa_mom":
            continue
        for value in document.values:
            if value.period_role != "headline":
                continue
            record = latest.get(value.reference_period)
            monthly = (
                100 * ((1 + record.value / 100) ** (1 / 12) - 1)
                if record is not None and record.value is not None
                else None
            )
            comparisons.append(
                dict(
                    release_id=document.release_id,
                    source_url=str(document.source_url),
                    reference_period=value.reference_period,
                    bls_value=value.document_value,
                    bls_record_id=value.document_record_id,
                    philly_record_id=record_id(record) if record is not None else None,
                    raw_sha256=record.provenance.raw_sha256 if record is not None else None,
                    native_annualized=record.value if record is not None else None,
                    monthly_equivalent=monthly,
                    status="missing"
                    if monthly is None
                    else (
                        "matches_display"
                        if abs(monthly - value.document_value) < 0.05
                        else "different_at_display_precision"
                    ),
                )
            )
    return dict(
        scope="headline_CPI_monthly_vintage_estimates_not_delivery_certification",
        as_of=as_of.isoformat(),
        source_versions=len(records),
        reference_months=len(latest),
        transformation="100*((1+annualized_percent/100)**(1/12)-1)",
        same_BLS_upstream=True,
        first_release_verified=False,
        actual_delivery_time="not_measured",
        comparisons=comparisons,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=Path("local/market"))
    parser.add_argument("--registry", type=Path, default=Path("sources/source_registry.yaml"))
    parser.add_argument("--as-of", type=datetime.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.as_of.tzinfo is None:
        parser.error("--as-of must include a timezone")
    if not (args.store / "market.sqlite3").is_file():
        parser.error("existing store required")
    store = Store(args.store)
    try:
        result = review(store, load_registry(args.registry), args.as_of.astimezone(UTC))
    finally:
        store.db.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(dict(output=str(args.output), comparisons=len(result["comparisons"]))))
