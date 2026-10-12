import json
from datetime import UTC, datetime

from gold_intelligence.daily_status import daily_status


def test_missing_collection_is_zero_local_not_provider_quota_and_no_write(tmp_path):
    root = tmp_path / "missing"
    r = daily_status(root, datetime(2026, 10, 12, 9, tzinfo=UTC))
    assert r["verified_daily_observations"] == 0 and r["local_remaining"] == 20
    assert r["provider_remaining_quota"] is None and not r["scheduler_enabled"]
    assert r["next_manual_window_at"] == "2026-10-13T14:00:00+00:00"
    assert not root.exists()


def test_corrupt_ledger_never_shows_zero_usage(tmp_path):
    (tmp_path / "attempts").mkdir()
    (tmp_path / "attempts" / "2026-10-13.json").write_text("{}")
    r = daily_status(tmp_path, datetime(2026, 10, 13, 14, tzinfo=UTC))
    assert r["status"] == "unavailable" and r["local_remaining"] is None
    assert not r["capture_allowed_now"]


def test_weekend_and_window_end_skip_to_next_weekday(tmp_path):
    r = daily_status(tmp_path, datetime(2026, 10, 16, 15, tzinfo=UTC))
    assert r["next_manual_window_at"] == "2026-10-19T14:00:00+00:00"


def test_reserved_without_quote_is_not_reported_as_success(tmp_path):
    folder = tmp_path / "attempts"
    folder.mkdir()
    (folder / "2026-10-13.json").write_text(
        json.dumps(
            dict(
                utc_date="2026-10-13",
                reserved_at="2026-10-13T14:00:00+00:00",
                status="reserved_no_automatic_retry",
                attempts=1,
            )
        )
    )
    r = daily_status(tmp_path, datetime(2026, 10, 13, 14, 20, tzinfo=UTC))
    assert r["monthly_reserved_attempts"] == 1 and r["local_remaining"] == 19
    assert r["reserved_without_verified_quote"] == 1 and r["verified_daily_observations"] == 0
    assert not r["capture_allowed_now"]
    assert r["next_manual_window_at"] == "2026-10-14T14:00:00+00:00"
