"""Independent arithmetic reconciliation of a saved study against local SQLite inputs.

Does not call monthly_research aggregation, selection, rank or correlation helpers.
This validates reported levels and samples; it does not certify upstream methodology.
"""

import argparse
import calendar
import json
import math
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path


def check_equal(actual, expected):
    if actual is None or expected is None:
        if actual is not expected:
            raise ValueError("missing/nonmissing result mismatch")
    elif not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-10):
        raise ValueError("numeric reconciliation failed")


def correlation(x, y):
    if len(x) < 2 or len(set(x)) == 1 or len(set(y)) == 1:
        return None
    dx = [v - sum(x) / len(x) for v in x]
    dy = [v - sum(y) / len(y) for v in y]
    return sum(a * b for a, b in zip(dx, dy, strict=True)) / math.sqrt(
        sum(a * a for a in dx) * sum(b * b for b in dy)
    )


def ranked(values):
    return [1 + sum(v < x for v in values) + (sum(v == x for v in values) - 1) / 2 for x in values]


def validate(store_path: Path, report_path: Path):
    report = json.loads(report_path.read_text(encoding="utf-8"))
    with sqlite3.connect(
        f"{(store_path / 'market.sqlite3').resolve().as_uri()}?mode=ro", uri=True
    ) as db:
        records = {
            key: json.loads(value)
            for key, value in db.execute(
                "SELECT id, payload FROM records WHERE kind = 'observation'"
            )
        }
    levels = {}
    for level in report["levels"]:
        selected = [records[key] for key in level["record_ids"]]
        month = date.fromisoformat(level["month"])
        daily = level["series_id"] in {"DTWEXBGS", "DFII10", "DGS10"}
        expected = (
            [
                month.replace(day=d).isoformat()
                for d in range(1, calendar.monthrange(month.year, month.month)[1] + 1)
                if month.replace(day=d).weekday() < 5
            ]
            if daily
            else [month.isoformat()]
        )
        dates = [
            datetime.fromisoformat(r["provenance"]["observed_at"])
            .astimezone(UTC)
            .date()
            .isoformat()
            for r in selected
        ]
        if len(dates) != len(set(dates)) or any(d not in expected for d in dates):
            raise ValueError("duplicate or out-of-period input")
        if any(r["series_id"] != level["series_id"] for r in selected):
            raise ValueError("cross-series input")
        missing = [d for d in expected if d not in dates]
        nulls = [d for d, r in zip(dates, selected, strict=True) if r["value"] is None]
        values = [r["value"] for r in selected if r["value"] is not None]
        if (
            missing != level["missing_labels"]
            or nulls != level["null_labels"]
            or len(expected) != level["expected_labels"]
            or len(values) != level["valid_values"]
        ):
            raise ValueError("coverage reconciliation failed")
        enough = (
            not missing
            and len(values) / len(expected) >= report["plan"]["minimum_valid_weekday_fraction"]
        )
        expected_value = sum(values) / len(values) if values and enough else None
        check_equal(level["value"], expected_value)
        levels[level["series_id"], level["month"]] = expected_value
    for row in report["changes"]:
        month = date.fromisoformat(row["month"])
        previous = (month.replace(day=1) - timedelta(days=1)).replace(day=1).isoformat()
        for series, actual in row["values"].items():
            current, prior = levels[series, row["month"]], levels[series, previous]
            value = None
            if (
                current is not None
                and prior is not None
                and not (series == "WB_GOLD_MONTHLY" and row["month"] == "2025-06-01")
            ):
                value = (
                    current - prior
                    if series in {"DFII10", "DGS10"}
                    else (current - prior) / prior * 100
                )
            check_equal(actual, value)
    for association in report["associations"]:
        series = association["series_id"]
        rows = [
            r
            for r in report["changes"]
            if r["method"] == association["method"]
            and r["values"]["WB_GOLD_MONTHLY"] is not None
            and r["values"][series] is not None
            and (
                association["population"] == "pairwise"
                or all(v is not None for v in r["values"].values())
            )
        ]
        if len(rows) != association["n"] or [r["month"] for r in rows] != association["months"]:
            raise ValueError("association sample mismatch")
        x = [r["values"]["WB_GOLD_MONTHLY"] for r in rows]
        y = [r["values"][series] for r in rows]
        enough = len(rows) >= report["plan"]["minimum_pairs"]
        check_equal(association["pearson"], correlation(x, y) if enough else None)
        check_equal(association["spearman"], correlation(ranked(x), ranked(y)) if enough else None)
    for window in report["rolling"]:
        rows = [
            r
            for r in report["changes"]
            if window["first_month"] <= r["month"] <= window["last_month"]
        ]
        if len(rows) != window["n"] or any(
            r["method"] != window["method"] or any(v is None for v in r["values"].values())
            for r in rows
        ):
            raise ValueError("invalid rolling sample")
        x = [r["values"]["WB_GOLD_MONTHLY"] for r in rows]
        y = [r["values"][window["series_id"]] for r in rows]
        check_equal(window["pearson"], correlation(x, y))
        check_equal(window["spearman"], correlation(ranked(x), ranked(y)))
    return {
        "status": "reconciled",
        "fingerprint": report["fingerprint"],
        "monthly_levels": len(report["levels"]),
        "change_months": len(report["changes"]),
        "associations": len(report["associations"]),
        "rolling_associations": len(report["rolling"]),
        "scope": (
            "Saved inputs, coverage, transformations and reported coefficients; "
            "not causal validation."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=Path("local/market"))
    parser.add_argument("--report", type=Path, default=Path("local/reports/monthly-research.json"))
    args = parser.parse_args()
    print(json.dumps(validate(args.store, args.report), indent=2))


if __name__ == "__main__":
    main()
