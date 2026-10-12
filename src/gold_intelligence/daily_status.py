"""Read-only protocol status: local reservations never imply provider quota."""

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .daily_capture import MONTHLY_LIMIT, START_DATE, read_reservations, window_hour
from .forward_dataset import build_forward_dataset, read_json
from .goldapi_capture import ENDPOINT, LIMIT
from .models import aware


def daily_status(root, now):
    time = aware(now).astimezone(UTC)
    root = Path(root)
    result = dict(
        schema_version="1.0.0",
        evaluated_at=time.isoformat(),
        start_date=START_DATE.isoformat(),
        window_utc="13:00–14:00",
        window_tehran="16:30–17:30",
        monthly_local_limit=MONTHLY_LIMIT,
        provider_remaining_quota=None,
        scheduler_enabled=False,
        status="verified",
        monthly_reserved_attempts=None,
        local_remaining=None,
        verified_daily_observations=None,
        reserved_without_verified_quote=None,
        next_manual_window_at=None,
        capture_allowed_now=False,
        recorded_failure_count=None,
        recorded_failures=[],
    )
    try:
        reservations = read_reservations(root, time)
        quotes = root / "quotes"
        failures, capture_days = [], set()
        for folder in sorted(p for p in quotes.iterdir() if p.is_dir()) if quotes.exists() else []:
            receipt_bytes, receipt = read_json(folder / "receipt.json")
            started = aware(datetime.fromisoformat(receipt["started_at"])).astimezone(UTC)
            day = started.date().isoformat()
            if (
                day not in reservations
                or started < reservations[day]
                or started > time
                or started.hour != window_hour(started.date())
                or day in capture_days
                or receipt["endpoint"] != ENDPOINT
                or receipt["trading_eligible"] is not False
            ):
                raise ValueError
            capture_days.add(day)
            if receipt["status"] == "failed":
                if type(receipt["attempts"]) is not int or receipt["attempts"] != 1:
                    raise ValueError
                if (folder / "quote-review.json").exists():
                    raise ValueError
                if "received_at" in receipt:
                    received = aware(datetime.fromisoformat(receipt["received_at"])).astimezone(UTC)
                    if not started <= received <= time:
                        raise ValueError
                raw_path = folder / "raw.json"
                if raw_path.exists():
                    raw = raw_path.read_bytes()
                    if len(raw) > LIMIT or hashlib.sha256(raw).hexdigest() != receipt["raw_sha256"]:
                        raise ValueError
                elif "raw_sha256" in receipt:
                    raise ValueError
                failures.append(
                    dict(
                        capture_id=folder.name,
                        utc_date=day,
                        receipt_sha256=hashlib.sha256(receipt_bytes).hexdigest(),
                        raw_sha256=receipt.get("raw_sha256"),
                        outcome="recorded_failed_capture",
                    )
                )
            elif receipt["status"] != "metadata_checked_not_trading_eligible":
                raise ValueError
        excluded = [f["capture_id"] for f in failures]
        dataset = (
            build_forward_dataset(quotes, excluded_capture_ids=excluded)
            if quotes.exists()
            else None
        )
        days = set()
        for row in (dataset or {}).get("observations", []):
            started = datetime.fromisoformat(row["request_started_at"])
            day = started.date().isoformat()
            received = datetime.fromisoformat(row["received_at"])
            if (
                day not in reservations
                or started < reservations[day]
                or day in days
                or started.hour != window_hour(started.date())
                or received > time
            ):
                raise ValueError
            days.add(day)
        month = time.strftime("%Y-%m")
        used = sum(day.startswith(month) for day in reservations)
        result.update(
            monthly_reserved_attempts=used,
            local_remaining=max(0, MONTHLY_LIMIT - used),
            verified_daily_observations=len(days),
            reserved_without_verified_quote=len(reservations) - len(days),
            coverage=dataset,
            recorded_failure_count=len(failures),
            recorded_failures=failures,
        )
        candidate_day = max(time.date(), START_DATE)
        for offset in range(70):
            day = candidate_day + timedelta(days=offset)
            beginning = datetime(day.year, day.month, day.day, window_hour(day), tzinfo=UTC)
            end = beginning + timedelta(hours=1)
            consumed = sum(d.startswith(day.strftime("%Y-%m")) for d in reservations)
            if (
                day.weekday() < 5
                and day.isoformat() not in reservations
                and consumed < MONTHLY_LIMIT
                and time < end
            ):
                result["next_manual_window_at"] = beginning.isoformat()
                result["capture_allowed_now"] = beginning <= time < end
                break
        return result
    except (ValueError, TypeError, KeyError, AttributeError, OSError):
        result.update(
            status="unavailable",
            reason="شواهد پروتکل ناقص یا نامعتبر است؛ ظرفیت و پوشش قابل تأیید نیست.",
        )
        return result
