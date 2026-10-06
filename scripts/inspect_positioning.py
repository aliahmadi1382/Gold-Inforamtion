"""Independently reconcile a saved COT context to raw cells and stored versions.

No imports from the acquisition or positioning calculation modules. This checks
lineage, selected coverage and arithmetic, not publisher truth or release timing.
"""

import argparse
import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime
from pathlib import Path

FIELDS = {
    "producer_merchant_processor_user": (
        "prod_merc_positions_long",
        "prod_merc_positions_short",
        None,
    ),
    "swap_dealer": (
        "swap_positions_long_all",
        "swap__positions_short_all",
        "swap__positions_spread_all",
    ),
    "managed_money": (
        "m_money_positions_long_all",
        "m_money_positions_short_all",
        "m_money_positions_spread",
    ),
    "other_reportable": (
        "other_rept_positions_long",
        "other_rept_positions_short",
        "other_rept_positions_spread",
    ),
    "nonreportable": ("nonrept_positions_long_all", "nonrept_positions_short_all", None),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(store_path, report_path):
    report = json.loads(report_path.read_text(encoding="utf-8"))
    cutoff = datetime.fromisoformat(report["as_of"])
    with sqlite3.connect(
        f"{(store_path / 'market.sqlite3').resolve().as_uri()}?mode=ro", uri=True
    ) as db:
        records = {}
        for identifier, payload in db.execute(
            "SELECT id, payload FROM records WHERE kind='positioning'"
        ):
            item = json.loads(payload)
            p = item["provenance"]
            if p["source_id"] != "cftc_disaggregated" or any(
                datetime.fromisoformat(p[k]) > cutoff for k in ("available_at", "retrieved_at")
            ):
                continue
            require(
                hashlib.sha256(payload.encode()).hexdigest() == identifier, "record hash mismatch"
            )
            records[identifier] = item
    require(records, "arithmetic reconciliation requires eligible positioning data")
    latest = {}
    blobs = {}

    def raw(digest):
        require(re.fullmatch("[a-f0-9]{64}", digest), "invalid hash")
        if digest not in blobs:
            content = (store_path / "raw" / digest).read_bytes()
            require(hashlib.sha256(content).hexdigest() == digest, "raw hash mismatch")
            blobs[digest] = json.loads(content)
        return blobs[digest]

    for identifier, item in records.items():
        p = item["provenance"]
        key = (p["observed_at"][:10], item["category"])
        known = datetime.fromisoformat(p["retrieved_at"])
        if key in latest and known == latest[key][0]:
            raise ValueError("ambiguous eligible positioning versions")
        if key not in latest or known > latest[key][0]:
            latest[key] = (known, identifier)
    days = sorted({key[0] for key in latest})
    require([w["observed_date"] for w in report["weeks"]] == days, "reported date coverage differs")
    checked = set()
    previous = None
    previous_nets = {}
    irregular = []
    for week in report["weeks"]:
        day = week["observed_date"]
        capture = raw(week["capture_sha256"])
        require(week["known_at"] == capture["retrieved_at"], "capture clock mismatch")
        for name in ("metadata_before", "metadata_after", "count_before", "count_after"):
            raw(capture[name])
        rows = [r for page in capture["pages"] for r in raw(page["sha256"])]
        require(len(rows) == capture["expected_rows"], "capture row count differs")
        candidates = [r for r in rows if r["report_date_as_yyyy_mm_dd"][:10] == day]
        require(len(candidates) == 1, "ambiguous raw date")
        row = candidates[0]
        require(
            row["cftc_contract_market_code"] == "088691"
            and row["futonly_or_combined"] == "FutOnly"
            and row["contract_units"] == "(CONTRACTS OF 100 TROY OUNCES)",
            "raw market/family/unit mismatch",
        )
        oi = int(row["open_interest_all"])
        require(week["open_interest"] == oi, "open interest differs from raw")
        delta_days = (
            (datetime.fromisoformat(day) - datetime.fromisoformat(previous["observed_date"])).days
            if previous
            else None
        )
        exact = delta_days == 7
        if previous and not exact:
            irregular.append([previous["observed_date"], day])
        require(
            week["previous_observed_date"] == (previous["observed_date"] if previous else None),
            "previous date differs",
        )
        require(
            week["delta_status"]
            == (
                "seven_day_pair"
                if exact
                else ("irregular_interval" if previous else "first_observation")
            ),
            "delta interval status differs",
        )
        require(
            week["open_interest_change_7d"] == (oi - previous["open_interest"] if exact else None),
            "OI delta differs",
        )
        groups = week["categories"]
        require([g["category"] for g in groups] == list(FIELDS), "category coverage differs")
        totals = [0, 0]
        nets = {}
        for group in groups:
            category = group["category"]
            expected_id = latest[(day, category)][1]
            require(group["record_id"] == expected_id, "selected record is not latest eligible")
            item = records[expected_id]
            p = item["provenance"]
            require(p["raw_sha256"] == week["capture_sha256"], "raw pointer differs")
            require(
                p["available_at"] == p["retrieved_at"] == week["known_at"],
                "retrieval clocks differ",
            )
            long_field, short_field, spread_field = FIELDS[category]
            long, short = int(row[long_field]), int(row[short_field])
            spread = int(row[spread_field]) if spread_field else None
            for key, value in {"long": long, "short": short, "spreading": spread}.items():
                require(group[key] == item[key] == value, "category value differs from raw")
            net = long - short
            require(group["net"] == net, "net arithmetic differs")
            share = group["net_percent_open_interest"]
            require(
                share is None
                if oi == 0
                else share is not None and math.isclose(share, net * 100 / oi, abs_tol=1e-10),
                "net/OI arithmetic differs",
            )
            require(
                group["net_change_7d"] == (net - previous_nets[category] if exact else None),
                "net delta differs",
            )
            totals[0] += long + (spread or 0)
            totals[1] += short + (spread or 0)
            nets[category] = net
            checked.add(expected_id)
        require(totals == [oi, oi] and sum(nets.values()) == 0, "aggregate reconciliation failed")
        previous, previous_nets = week, nets
    require(report["irregular_intervals"] == irregular, "irregular interval profile differs")
    require(report["eligible_record_versions"] == len(records), "eligible version count differs")
    require(
        report["superseded_record_versions"] == len(records) - len(checked),
        "superseded count differs",
    )
    non_tuesdays = [d for d in days if datetime.fromisoformat(d).weekday() != 1]
    require(report["non_tuesday_labels"] == non_tuesdays, "weekday profile differs")
    age = (cutoff.date() - datetime.fromisoformat(days[-1]).date()).days
    require(report["latest_observation_age_days"] == age, "observation age differs")
    require(
        report["status"] == ("stale" if age > report["max_age_days"] else "descriptive_only"),
        "freshness status differs",
    )
    return {
        "status": "verified",
        "weeks": len(days),
        "selected_records": len(checked),
        "eligible_versions": len(records),
        "raw_blobs_checked": len(blobs),
        "first_date": days[0],
        "last_date": days[-1],
        "irregular_intervals": irregular,
        "non_tuesday_labels": non_tuesdays,
        "scope": "coverage and raw-backed arithmetic; no publisher or release-time certification",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=Path("local/market"))
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=Path("local/reports/positioning-validation.json")
    )
    args = parser.parse_args()
    result = validate(args.store, args.report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
