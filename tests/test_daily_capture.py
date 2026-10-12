import json
from datetime import UTC, datetime

import pytest

from gold_intelligence.daily_capture import capture_daily

TIME = datetime(2026, 10, 13, 14, 10, tzinfo=UTC)


def test_success_and_failed_attempt_each_block_second_request(tmp_path):
    calls = []

    def fetch(key):
        calls.append(key)
        return json.dumps(
            dict(
                timestamp=int(TIME.timestamp()),
                datetime=TIME.isoformat(),
                metal="XAU",
                currency="USD",
                unit="troy_ounce",
                exchange="FOREXCOM",
                symbol="FOREXCOM:XAUUSD",
                price=2000,
                bid=1999,
                ask=2001,
            )
        ).encode(), 200

    folder = capture_daily(tmp_path, "fixture", fetch, lambda: TIME)
    assert (folder / "quote-review.json").exists()
    with pytest.raises(ValueError, match="already reserved"):
        capture_daily(tmp_path, "fixture", fetch, lambda: TIME)
    assert len(calls) == 1


def test_failed_request_reservation_is_not_reset(tmp_path):
    calls = []

    def fetch(key):
        calls.append(key)
        raise ValueError("failed")

    with pytest.raises(ValueError):
        capture_daily(tmp_path, "fixture", fetch, lambda: TIME)
    with pytest.raises(ValueError, match="already reserved"):
        capture_daily(tmp_path, "fixture", fetch, lambda: TIME)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "clock",
    [
        TIME.replace(hour=13),
        TIME.replace(day=17),
        TIME.replace(day=12),
        TIME.replace(tzinfo=None),
    ],
)
def test_wrong_window_weekend_start_or_naive_clock_never_requests(tmp_path, clock):
    with pytest.raises(ValueError):
        capture_daily(tmp_path, "fixture", lambda _: pytest.fail("network"), lambda: clock)
    assert not list(tmp_path.iterdir())


def test_corrupt_ledger_blocks_collection(tmp_path):
    (tmp_path / "attempts").mkdir()
    (tmp_path / "attempts" / "2026-10-13.json").write_text("{}")
    with pytest.raises(ValueError, match="invalid local"):
        capture_daily(tmp_path, "fixture", lambda _: pytest.fail("network"), lambda: TIME)


def test_monthly_limit_counts_reserved_failures_before_network(tmp_path):
    folder = tmp_path / "attempts"
    folder.mkdir()
    for day in range(1, 21):
        stamp = f"2026-10-{day:02d}"
        (folder / (stamp + ".json")).write_text(
            json.dumps(
                dict(
                    utc_date=stamp,
                    reserved_at=stamp + "T14:00:00+00:00",
                    attempts=1,
                    status="reserved_no_automatic_retry",
                )
            )
        )
    with pytest.raises(ValueError, match="monthly request budget"):
        capture_daily(
            tmp_path, "fixture", lambda _: pytest.fail("network"), lambda: TIME.replace(day=30)
        )
