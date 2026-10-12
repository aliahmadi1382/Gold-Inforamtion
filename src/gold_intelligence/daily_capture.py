"""Fixed manual UTC daily collection, with conservative local request reservations."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

from .forward_dataset import read_json
from .goldapi_capture import capture_goldapi, fetch_quote
from .models import aware
from .store_lock import store_lock

START_DATE = date(2026, 10, 13)
MONTHLY_LIMIT = 20


def capture_daily(root, key, fetch=fetch_quote, now=lambda: datetime.now(UTC)):
    if not isinstance(key, str) or not key.strip() or any(c in key for c in "\r\n"):
        raise ValueError("configured key required")
    time = aware(now()).astimezone(UTC)
    if time.date() < START_DATE or time.weekday() >= 5 or time.hour != 14:
        raise ValueError("outside protocol: weekdays 14:00–14:59 UTC from 2026-10-13")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    attempts = root / "attempts"
    attempts.mkdir(exist_ok=True)
    with store_lock(root):
        # Invalid reservations block collection instead of resetting the budget.
        prior = []
        for path in attempts.glob("*.json"):
            try:
                _, item = read_json(path)
                if set(item) != {"utc_date", "reserved_at", "status", "attempts"}:
                    raise ValueError
                reserved = aware(datetime.fromisoformat(item["reserved_at"])).astimezone(UTC)
                if item["utc_date"] != reserved.date().isoformat() or path.stem != item["utc_date"]:
                    raise ValueError
                if type(item["attempts"]) is not int or item["attempts"] != 1:
                    raise ValueError
                if item["status"] != "reserved_no_automatic_retry":
                    raise ValueError
                prior.append(item["utc_date"])
            except (ValueError, KeyError, TypeError, AttributeError, OSError):
                raise ValueError("invalid local request ledger; collection blocked") from None
        day = time.date().isoformat()
        if day in prior:
            raise ValueError("today already reserved; no second request")
        if sum(d[:7] == day[:7] for d in prior) >= MONTHLY_LIMIT:
            raise ValueError("local monthly request budget exhausted")
        reservation = dict(
            utc_date=day,
            reserved_at=time.isoformat(),
            status="reserved_no_automatic_retry",
            attempts=1,
        )
        with (attempts / (day + ".json")).open("x", encoding="utf-8") as output:
            output.write(json.dumps(reservation, indent=2) + "\n")
        # Reservation remains even on crash/failure; provider consumption is not assumed zero.
        return capture_goldapi(root / "quotes", key, fetch, now)
