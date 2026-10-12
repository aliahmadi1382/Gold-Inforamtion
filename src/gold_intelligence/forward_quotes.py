"""Prospective spot receipts; source labels and retrieval clocks must remain separate."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode

from pydantic import Field, model_validator

from .ingestion import fetch_bytes
from .models import Contract, Hash, Timestamp, aware


class ForwardQuoteEvidence(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    source_id: Literal["alpha_vantage_spot_review"] = "alpha_vantage_spot_review"
    nominal: Literal["XAUUSD"] = "XAUUSD"
    raw_sha256: Hash
    request_started_at: Timestamp
    received_at: Timestamp
    provider_time_label: str = Field(pattern=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
    provider_timezone: Literal["unknown"] = "unknown"
    price: float = Field(gt=0, allow_inf_nan=False)
    unit_status: Literal["inferred_not_verified"] = "inferred_not_verified"
    bid_ask_status: Literal["not_provided"] = "not_provided"
    freshness_status: Literal["not_verified"] = "not_verified"
    availability_basis: Literal["local_receipt_only"] = "local_receipt_only"
    trading_eligible: Literal[False] = False
    daily_backtest_ready: Literal[False] = False

    @model_validator(mode="after")
    def clocks(self):
        if self.received_at < self.request_started_at:
            raise ValueError("receipt cannot precede request")
        datetime.strptime(self.provider_time_label, "%Y-%m-%d %H:%M:%S")
        return self


def review_spot(content, started, received):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate source field")
            result[key] = value
        return result

    try:
        payload = json.loads(content, object_pairs_hook=unique)
        if not isinstance(payload, dict) or set(payload) != {"nominal", "price", "timestamp"}:
            raise ValueError
        if payload["nominal"] != "XAUUSD" or isinstance(payload["price"], bool):
            raise ValueError
        return ForwardQuoteEvidence(
            raw_sha256=hashlib.sha256(content).hexdigest(),
            request_started_at=aware(started).astimezone(UTC),
            received_at=aware(received).astimezone(UTC),
            provider_time_label=payload["timestamp"],
            price=float(payload["price"]),
        )
    except (ValueError, TypeError, KeyError, OverflowError):
        raise ValueError("spot quote schema, value or clock validation failed") from None


def capture_spot(root, key, fetch=fetch_bytes, now=lambda: datetime.now(UTC)):
    """Exactly one request; private immutable directory, no market-store writes or retries."""
    if not isinstance(key, str) or not key.strip():
        raise ValueError("configured Alpha key required")
    started = aware(now()).astimezone(UTC)
    target = Path(root) / started.strftime("%Y%m%dT%H%M%S%fZ")
    target.mkdir(parents=True, exist_ok=False)
    receipt = dict(
        endpoint="GOLD_SILVER_SPOT",
        symbol="GOLD",
        started_at=started.isoformat(),
        status="failed",
        trading_eligible=False,
    )
    try:
        url = "https://www.alphavantage.co/query?" + urlencode(
            dict(function="GOLD_SILVER_SPOT", symbol="GOLD", apikey=key)
        )
        content = fetch(url, attempts=1)
        (target / "raw.json").write_bytes(content)
        receipt["raw_sha256"] = hashlib.sha256(content).hexdigest()
        received = aware(now()).astimezone(UTC)
        receipt.update(
            received_at=received.isoformat(), raw_sha256=hashlib.sha256(content).hexdigest()
        )
        evidence = review_spot(content, started, received)
        (target / "quote-review.json").write_text(
            evidence.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        receipt["status"] = "reviewed_not_trading_eligible"
    finally:
        (target / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return target
