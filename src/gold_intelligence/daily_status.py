"""Read-only protocol status: local reservations never imply provider quota."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from .daily_capture import MONTHLY_LIMIT, START_DATE
from .forward_dataset import build_forward_dataset, read_json
from .models import aware


def daily_status(root, now):
    time = aware(now).astimezone(UTC)
    root = Path(root)
    result = dict(
        schema_version="1.0.0",
        evaluated_at=time.isoformat(),
        start_date=START_DATE.isoformat(),
        window_utc="14:00–15:00",
        window_tehran="17:30–18:30",
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
    )
    try:
        reservations = {}
        for path in (root / "attempts").glob("*.json"):
            _, item = read_json(path)
            reserved = aware(datetime.fromisoformat(item["reserved_at"])).astimezone(UTC)
            day = reserved.date().isoformat()
            if (
                set(item) != {"utc_date", "reserved_at", "status", "attempts"}
                or path.stem != day
                or item["utc_date"] != day
                or day in reservations
                or type(item["attempts"]) is not int
                or item["attempts"] != 1
                or item["status"] != "reserved_no_automatic_retry"
                or reserved > time
                or reserved.date() < START_DATE
                or reserved.weekday() >= 5
                or reserved.hour != 14
            ):
                raise ValueError
            reservations[day] = reserved
        quotes = root / "quotes"
        dataset = build_forward_dataset(quotes) if quotes.exists() else None
        days = set()
        for row in (dataset or {}).get("observations", []):
            started = datetime.fromisoformat(row["request_started_at"])
            day = started.date().isoformat()
            received = datetime.fromisoformat(row["received_at"])
            if (
                day not in reservations
                or started < reservations[day]
                or day in days
                or started.hour != 14
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
        )
        candidate_day = max(time.date(), START_DATE)
        for offset in range(70):
            day = candidate_day + timedelta(days=offset)
            beginning = datetime(day.year, day.month, day.day, 14, tzinfo=UTC)
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
