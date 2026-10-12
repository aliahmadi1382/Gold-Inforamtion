import json
from datetime import UTC, datetime

from gold_intelligence.daily_cycle import run_daily_cycle


def test_closed_window_reviews_without_network_or_collection_writes(tmp_path):
    time = datetime(2026, 10, 12, 14, tzinfo=UTC)

    def fetch(key):
        raise AssertionError("unexpected network")

    root = tmp_path / "daily"
    r = run_daily_cycle(root, "fixture", fetch, lambda: time)
    assert r["capture_outcome"] == "not_completed"
    assert r["research"]["status"] == "awaiting_daily_observations"
    assert not root.exists()


def test_cycle_success_then_same_day_reentry_uses_only_one_request(tmp_path):
    time = datetime(2026, 10, 13, 14, 10, tzinfo=UTC)
    calls = []

    def fetch(key):
        calls.append(key)
        return json.dumps(
            dict(
                timestamp=int(time.timestamp()),
                datetime=time.isoformat(),
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

    a = run_daily_cycle(tmp_path, "fixture", fetch, lambda: time)
    b = run_daily_cycle(tmp_path, "fixture", fetch, lambda: time)
    assert a["capture_outcome"] == "captured_and_checked"
    assert b["capture_outcome"] == "not_completed" and len(calls) == 1
    assert b["research"]["protocol_status"]["verified_daily_observations"] == 1
    assert not b["orders_enabled"] and not b["scheduler_enabled"]
