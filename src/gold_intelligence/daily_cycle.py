"""One manual capture-and-review cycle; no scheduler, retries or orders."""

from datetime import UTC, datetime

from .daily_capture import capture_daily
from .daily_research import review_daily_research
from .goldapi_capture import fetch_quote
from .models import aware


def run_daily_cycle(root, key, fetch=fetch_quote, now=lambda: datetime.now(UTC)):
    started = aware(now()).astimezone(UTC)
    outcome, folder = "not_completed", None
    try:
        folder = str(capture_daily(root, key, fetch, now))
        outcome = "captured_and_checked"
        reason = None
    except ValueError as exc:
        # Capture/admission errors are already sanitized by the scoped collector.
        reason = str(exc)
    except OSError:
        reason = "local file operation failed"
    finished = aware(now()).astimezone(UTC)
    if finished < started:
        raise ValueError("cycle clock reversed")
    return dict(
        schema_version="1.0.0",
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        capture_outcome=outcome,
        capture_folder=folder,
        capture_reason=reason,
        research=review_daily_research(root, finished),
        scheduler_enabled=False,
        orders_enabled=False,
    )
