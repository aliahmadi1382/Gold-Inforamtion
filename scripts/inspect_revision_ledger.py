"""Reconcile a complete saved ledger using raw cells and rational arithmetic.

This deliberately does not import the ledger or release-value calculation code.
It verifies the displayed comparisons, not first-release status or data delivery.
"""

import argparse
import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime
from fractions import Fraction
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def equal(actual, expected):
    require(
        actual is not None and math.isclose(actual, float(expected), abs_tol=1e-10, rel_tol=1e-10),
        "numeric reconciliation failed",
    )


def validate(store_path, report_path):
    report = json.loads(report_path.read_text(encoding="utf-8"))
    require(report["status"] == "complete", "this arithmetic check requires a complete ledger")
    with sqlite3.connect(
        f"{(store_path / 'market.sqlite3').resolve().as_uri()}?mode=ro", uri=True
    ) as db:
        records = dict(db.execute("SELECT id, payload FROM records WHERE kind = 'observation'"))
    checked, blobs = set(), {}
    cutoff = datetime.fromisoformat(report["as_of"])

    def raw(digest):
        require(re.fullmatch(r"[0-9a-f]{64}", digest), "invalid raw hash")
        if digest not in blobs:
            content = (store_path / "raw" / digest).read_bytes()
            require(hashlib.sha256(content).hexdigest() == digest, "raw hash mismatch")
            blobs[digest] = json.loads(content)
        return blobs[digest]

    def record(identifier):
        payload = records[identifier]
        require(hashlib.sha256(payload.encode()).hexdigest() == identifier, "record hash mismatch")
        item = json.loads(payload)
        p = item["provenance"]
        require(
            all(
                datetime.fromisoformat(p[key]) <= cutoff
                for key in ["observed_at", "available_at", "retrieved_at"]
            ),
            "record exceeds cutoff",
        )
        checked.add(identifier)
        return item

    captures = {c["capture_id"]: c for c in report["captures"]}
    require(len(captures) == len(report["captures"]), "duplicate capture")
    for capture in captures.values():
        source = raw(capture["raw_sha256"])
        require(
            all(capture["evidence"][key] == value for key, value in source.items()),
            "report capture differs from raw evidence",
        )
        require(len(source["values"]) == len(capture["record_ids"]), "partial capture")
        require(datetime.fromisoformat(source["captured_at"]) <= cutoff, "capture exceeds cutoff")
        for index, identifier in enumerate(capture["record_ids"]):
            row = record(identifier)
            p = row["provenance"]
            require(
                p["raw_sha256"] == capture["raw_sha256"]
                and p["raw_record_id"] == f"values:{index}",
                "document pointer mismatch",
            )
            require(
                row["value"] == source["values"][index]["value"]
                and p["unit"] == source["values"][index]["unit"],
                "document value/unit mismatch",
            )

    def archive(anchor, period, metric, headline):
        capture = captures[anchor["capture_id"]]
        evidence = raw(capture["raw_sha256"])
        require(
            evidence["metric"] == metric and evidence["headline_period"] == headline,
            "wrong metric or headline document",
        )
        index = capture["record_ids"].index(anchor["record_id"])
        entry = evidence["values"][index]
        require(
            anchor["reference_period"] == entry["reference_period"] == period,
            "wrong economic period",
        )
        require(
            anchor["unit"] == entry["unit"] and anchor["locator"] == entry["locator"],
            "anchor unit/locator mismatch",
        )
        equal(anchor["value"], Fraction(str(entry["value"])))
        return Fraction(str(entry["value"]))

    def fred(comparison, metric, period, published, expected_date):
        require(comparison["vintage_date"] == expected_date, "wrong vintage date")
        points = {}
        for identifier in comparison["record_ids"]:
            row = record(identifier)
            p = row["provenance"]
            require(
                p["source_id"] == "fred" and row["vintage_date"] == expected_date,
                "wrong parent source or vintage",
            )
            require(
                row["series_id"] == ("CPIAUCSL" if metric.startswith("cpi_") else "UNRATE"),
                "wrong FRED metric",
            )
            payload = raw(p["raw_sha256"])
            require(
                payload["units"] == "lin"
                and all(payload[k] == expected_date for k in ["realtime_start", "realtime_end"]),
                "wrong raw vintage or transformation",
            )
            require(re.fullmatch(r"observations:\d+", p["raw_record_id"]), "invalid row pointer")
            entry = payload["observations"][int(p["raw_record_id"].split(":")[1])]
            require(entry["value"] != ".", "missing raw value")
            value = Fraction(entry["value"])
            equal(row["value"], value)
            require(p["observed_at"][:10] == entry["date"], "FRED reference mismatch")
            require(entry["date"] not in points, "duplicate FRED parent period")
            points[entry["date"]] = value
        if metric.startswith("cpi_"):
            serial = int(period[:4]) * 12 + int(period[5:]) - 1
            year, month = divmod(serial - 1, 12)
            previous = f"{year:04d}-{month + 1:02d}-01"
            require(
                set(points) == {previous, period + "-01"}, "CPI requires adjacent index parents"
            )
            value = 100 * (points[period + "-01"] / points[previous] - 1)
        else:
            require(set(points) == {period + "-01"}, "UNRATE requires one period")
            value = points[period + "-01"]
        equal(comparison["value"], value)
        equal(comparison["difference_from_document"], value - published)
        require(
            abs(value - published) < Fraction(1, 20) and comparison["status"] == "matches_display",
            "display agreement mismatch",
        )
        return value

    p = report["plan"]
    start = int(p["start_period"][:4]) * 12 + int(p["start_period"][5:]) - 1
    end = int(p["end_period"][:4]) * 12 + int(p["end_period"][5:]) - 1
    months = [f"{s // 12:04d}-{s % 12 + 1:02d}" for s in range(start, end + 2)]
    expected = {(metric, month) for metric in p["metrics"] for month in months[:-1]}
    require(
        {(r["metric"], r["reference_period"]) for r in report["pairs"]} == expected
        and len(report["pairs"]) == len(expected),
        "coverage denominator mismatch",
    )
    expected_slots = {(metric, month) for metric in p["metrics"] for month in months}
    require(
        {(s["metric"], s["headline_period"]) for s in report["document_slots"]} == expected_slots
        and len(report["document_slots"]) == len(expected_slots),
        "document slots mismatch",
    )
    for slot in report["document_slots"]:
        require(
            slot["status"] == "present" and len(slot["candidate_capture_ids"]) == 1,
            "incomplete document slot",
        )
    changed = 0
    for pair in report["pairs"]:
        period, metric = pair["reference_period"], pair["metric"]
        following = months[months.index(period) + 1]
        require(pair["next_headline_period"] == following, "wrong adjacent headline")
        before = archive(pair["before"], period, metric, period)
        after = archive(pair["after"], period, metric, following)
        delta = after - before
        equal(pair["difference_pp"], delta)
        require(
            pair["status"] == ("unchanged_display" if delta == 0 else "changed_display"),
            "comparison status mismatch",
        )
        changed += delta != 0
        vintage_values = []
        for key, published in [("before", before), ("after", after)]:
            capture = captures[pair[key]["capture_id"]]
            vintage_values.append(
                fred(
                    pair[key + "_vintage"],
                    metric,
                    period,
                    published,
                    capture["evidence"]["announced_at"][:10],
                )
            )
        equal(pair["vintage_difference_pp"], vintage_values[1] - vintage_values[0])
    require(
        all(
            report[key] == len(expected)
            for key in ["expected_pairs", "compared_pairs", "vintage_matched_pairs"]
        ),
        "summary count mismatch",
    )
    require(report["changed_display_pairs"] == changed, "changed count mismatch")
    return dict(
        status="verified",
        fingerprint=report["fingerprint"],
        document_captures=len(captures),
        adjacent_pairs=len(expected),
        vintage_comparisons=2 * len(expected),
        parent_records=len(checked),
        scope="raw-backed adjacent-pair arithmetic; no first-release or intraday certification",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=Path("local/market"))
    parser.add_argument("--report", type=Path, default=Path("local/reports/revision-ledger.json"))
    parser.add_argument(
        "--output", type=Path, default=Path("local/reports/revision-ledger-validation.json")
    )
    args = parser.parse_args()
    result = validate(args.store, args.report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
