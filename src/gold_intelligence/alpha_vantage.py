"""Alpha Vantage's date/price history; no inferred OHLC, exchange or session clock."""

import json
import os
import re
from datetime import UTC, date, datetime
from urllib.parse import urlencode

from .ingestion import fetch_bytes, provenance
from .models import PriceClose, aware
from .registry import Source
from .storage import Store

DATASET = "gold_silver_history_daily_v1"


def parse_gold_history(
    content: bytes, source: Source, digest: str, retrieved_at: datetime
) -> list[PriceClose]:
    aware(retrieved_at)
    if source.source_id != "alpha_vantage_gold" or "price" not in source.layers:
        raise ValueError("gold history requires the alpha_vantage_gold registry source")
    try:
        payload = json.loads(content)
    except (ValueError, UnicodeError):
        raise ValueError("Alpha Vantage returned invalid JSON") from None
    if not isinstance(payload, dict):
        raise ValueError("unexpected Alpha Vantage response structure")
    # Provider messages may echo credentials. Keep their bodies in local raw evidence only.
    if any(key in payload for key in ("Information", "Note", "Error Message")):
        raise ValueError(
            "Alpha Vantage returned a service notice or error; "
            "check key access or daily quota before retrying"
        )
    if set(payload) != {"nominal", "data"} or payload["nominal"] != "XAUUSD":
        raise ValueError("unsupported Alpha Vantage gold schema or nominal; expected XAUUSD")
    rows = payload["data"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("Alpha Vantage gold history is empty or malformed")
    records = []
    seen = set()
    for index, row in enumerate(rows):
        try:
            if not isinstance(row, dict) or set(row) != {"date", "price"}:
                raise ValueError
            original = row["date"]
            if not isinstance(original, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", original):
                raise ValueError
            session_date = date.fromisoformat(original)
            if session_date in seen or session_date > retrieved_at.astimezone(UTC).date():
                raise ValueError
            if not isinstance(row["price"], str):
                raise ValueError
            price = float(row["price"])
            record = PriceClose(
                provenance=provenance(
                    source,
                    digest,
                    f"data:{index}",
                    datetime.combine(session_date, datetime.min.time(), UTC),
                    retrieved_at,
                    DATASET,
                    "currency_per_troy_ounce",
                    "USD",
                    original,
                    transformations=(
                        "alpha_vantage_gold_history_v1",
                        "date_only_period_label_utc_not_session_close",
                        "unit_inferred_from_XAUUSD_instrument_convention",
                        "provider_weekend_labels_preserved",
                    ),
                ),
                instrument="XAUUSD",
                venue="ALPHA_VANTAGE_REFERENCE",
                session_date=session_date,
                unit_basis="instrument_convention",
                close=price,
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            # No row contents in diagnostics: malformed responses can contain secrets.
            raise ValueError(
                f"invalid or duplicate Alpha Vantage gold row at index {index}"
            ) from None
        seen.add(session_date)
        records.append(record)
    return records


def ingest_alpha_gold(store: Store, source: Source, fetch=fetch_bytes) -> int:
    if source.source_id != "alpha_vantage_gold":
        raise ValueError("gold history requires the alpha_vantage_gold registry source")
    key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not key:
        raise ValueError("set ALPHAVANTAGE_API_KEY before fetching")
    params = {
        "function": "GOLD_SILVER_HISTORY",
        "symbol": "GOLD",
        "interval": "daily",
        "apikey": key,
    }
    # One request per invocation: automatic retries can consume the free daily quota.
    content = fetch("https://www.alphavantage.co/query?" + urlencode(params), attempts=1)
    retrieved = datetime.now(UTC)
    digest = store.put_raw(content)
    return store.put(parse_gold_history(content, source, digest, retrieved))
