"""Audit date-labelled GoldAPI history without assigning close times or units."""

import hashlib
import json
import math
from datetime import date, timedelta


def inspect_history(raw, start, end):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError
            out[key] = value
        return out

    try:
        if (
            not isinstance(start, date)
            or not isinstance(end, date)
            or not 0 <= (end - start).days < 90
        ):
            raise ValueError
        data = json.loads(raw, object_pairs_hook=unique)
        if set(data) != {"metal", "currency", "from", "to", "prices"}:
            raise ValueError
        if (data["metal"], data["currency"], data["from"], data["to"]) != (
            "XAU",
            "USD",
            start.isoformat(),
            end.isoformat(),
        ):
            raise ValueError
        if not isinstance(data["prices"], list):
            raise ValueError
        days = []
        for row in data["prices"]:
            if set(row) != {"date", "price"} or isinstance(row["price"], bool):
                raise ValueError
            day = date.fromisoformat(row["date"])
            if row["date"] != day.isoformat() or not start <= day <= end:
                raise ValueError
            price = float(row["price"])
            if not math.isfinite(price) or price <= 0:
                raise ValueError
            if days and day <= days[-1]:
                raise ValueError
            days.append(day)
        expected = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        return dict(
            schema_version="1.0.0",
            source_id="goldapi_history_candidate",
            raw_sha256=hashlib.sha256(raw).hexdigest(),
            start=start.isoformat(),
            end=end.isoformat(),
            row_count=len(days),
            date_labels=[d.isoformat() for d in days],
            missing_calendar_dates=[d.isoformat() for d in expected if d not in days],
            weekend_labels=[d.isoformat() for d in days if d.weekday() >= 5],
            unit_status="not_explicit_in_response",
            session_status="not_verified",
            source_time_status="date_only",
            historical_availability_status="not_verified",
            bid_ask_status="not_provided",
            trading_eligible=False,
            daily_backtest_ready=False,
        )
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        raise ValueError("historical candidate schema, price or date order rejected") from None
