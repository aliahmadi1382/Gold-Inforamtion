"""Offline candidate checks; documentation examples cannot grant trading eligibility."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field

from .models import Contract, Hash, Timestamp, aware


class GoldApiReview(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    source_id: Literal["goldapi_candidate"] = "goldapi_candidate"
    raw_sha256: Hash
    source_at: Timestamp
    received_at: Timestamp
    source: str
    symbol: str
    currency: Literal["USD"] = "USD"
    unit: Literal["troy_ounce"] = "troy_ounce"
    price: float = Field(gt=0)
    bid: float = Field(gt=0)
    ask: float = Field(gt=0)
    age_at_receipt_seconds: float = Field(ge=0)
    metadata_status: Literal["source_declared_fields_checked"] = "source_declared_fields_checked"
    trading_eligible: Literal[False] = False
    market_validation: Literal[False] = False


def review_goldapi(content, received_at, expected_source="FOREXCOM", maximum_age_seconds=900):
    """Check explicit unit, epoch/ISO agreement, source identity and bid/ask on supplied bytes."""

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    try:
        if type(maximum_age_seconds) is not int or not 0 <= maximum_age_seconds <= 3600:
            raise ValueError
        received = aware(received_at).astimezone(UTC)
        data = json.loads(content, object_pairs_hook=unique)
        if not isinstance(data, dict):
            raise ValueError
        if (data["metal"], data["currency"], data["unit"]) != ("XAU", "USD", "troy_ounce"):
            raise ValueError
        if not expected_source or data["exchange"] != expected_source:
            raise ValueError
        if data["symbol"] != expected_source + ":XAUUSD":
            raise ValueError
        epoch = data["timestamp"]
        if type(epoch) is not int or epoch <= 0:
            raise ValueError
        source_at = datetime.fromtimestamp(epoch, UTC)
        if not isinstance(data["datetime"], str):
            raise ValueError
        iso = aware(datetime.fromisoformat(data["datetime"].replace("Z", "+00:00")))
        if iso != source_at:
            raise ValueError
        age = (received - source_at).total_seconds()
        if not 0 <= age <= maximum_age_seconds:
            raise ValueError
        if any(isinstance(data[k], bool) for k in ("price", "bid", "ask")):
            raise ValueError
        result = GoldApiReview(
            raw_sha256=hashlib.sha256(content).hexdigest(),
            source_at=source_at,
            received_at=received,
            source=expected_source,
            symbol=data["symbol"],
            price=float(data["price"]),
            bid=float(data["bid"]),
            ask=float(data["ask"]),
            age_at_receipt_seconds=age,
        )
        if result.ask < result.bid:
            raise ValueError
        return result
    except (ValueError, TypeError, KeyError, OverflowError, OSError):
        raise ValueError("candidate quote failed identity, unit, time or bid/ask checks") from None
