"""Offline coverage of receipt-bound real quotes; never fill missing observations."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from .goldapi_capture import ENDPOINT, LIMIT
from .goldapi_review import GoldApiReview, review_goldapi
from .models import aware


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate evidence field")
            result[key] = value
        return result

    raw = path.read_bytes()
    if len(raw) > LIMIT:
        raise ValueError("evidence exceeds size limit")
    return raw, json.loads(raw, object_pairs_hook=unique)


def build_forward_dataset(root):
    """All capture folders must verify; sorting receipts grants no continuous coverage."""
    rows = []
    folders = sorted(p for p in Path(root).iterdir() if p.is_dir())
    for folder in folders:
        try:
            receipt_bytes, receipt = read_json(folder / "receipt.json")
            saved_bytes, saved = read_json(folder / "quote-review.json")
            raw = (folder / "raw.json").read_bytes()
            if len(raw) > LIMIT:
                raise ValueError
            if (
                receipt["endpoint"] != ENDPOINT
                or type(receipt["http_status"]) is not int
                or receipt["http_status"] != 200
                or type(receipt["attempts"]) is not int
                or receipt["attempts"] != 1
                or receipt["status"] != "metadata_checked_not_trading_eligible"
                or receipt["trading_eligible"] is not False
            ):
                raise ValueError
            started = aware(datetime.fromisoformat(receipt["started_at"])).astimezone(UTC)
            received = aware(datetime.fromisoformat(receipt["received_at"])).astimezone(UTC)
            if received < started:
                raise ValueError
            checked = review_goldapi(raw, received)
            if receipt["raw_sha256"] != checked.raw_sha256:
                raise ValueError
            if GoldApiReview.model_validate(saved) != checked:
                raise ValueError
            rows.append(
                dict(
                    capture_id=folder.name,
                    receipt_sha256=hashlib.sha256(receipt_bytes).hexdigest(),
                    review_sha256=hashlib.sha256(saved_bytes).hexdigest(),
                    request_started_at=started.isoformat(),
                    **checked.model_dump(mode="json"),
                )
            )
        except (ValueError, TypeError, KeyError, AttributeError, OSError):
            raise ValueError(
                "capture evidence invalid or incomplete; dataset not produced"
            ) from None
    rows.sort(key=lambda r: r["received_at"])
    receipts = [datetime.fromisoformat(r["received_at"]) for r in rows]
    sources = [datetime.fromisoformat(r["source_at"]) for r in rows]
    gaps = [(b - a).total_seconds() for a, b in zip(receipts, receipts[1:], strict=False)]
    ages = [r["age_at_receipt_seconds"] for r in rows]
    conflicts = sum(
        len({(r["price"], r["bid"], r["ask"]) for r in rows if r["source_at"] == stamp}) > 1
        for stamp in {r["source_at"] for r in rows}
    )
    return dict(
        schema_version="1.0.0",
        source_id="goldapi_forward_observations",
        synthetic=False,
        trading_eligible=False,
        market_validation=False,
        observation_count=len(rows),
        unique_source_times=len(set(sources)),
        duplicate_source_observations=len(rows) - len(set(sources)),
        conflicting_source_time_groups=conflicts,
        nonadvancing_source_time_pairs=sum(
            b <= a for a, b in zip(sources, sources[1:], strict=False)
        ),
        duplicate_receipt_times=len(receipts) - len(set(receipts)),
        receipt_span_seconds=(receipts[-1] - receipts[0]).total_seconds() if receipts else 0,
        receipt_gap_seconds=gaps,
        maximum_receipt_gap_seconds=max(gaps, default=None),
        age_seconds_min=min(ages, default=None),
        age_seconds_max=max(ages, default=None),
        coverage_basis="captured_observations_only",
        missing_interval_count=None,
        cadence="not_declared",
        strategy_evaluation_status="not_run",
        observations=rows,
    )
