import json
from datetime import UTC, datetime

from gold_intelligence.daily_capture import capture_daily
from gold_intelligence.daily_research import review_daily_research
from gold_intelligence.goldapi_capture import capture_goldapi

TIME = datetime(2026, 10, 13, 14, 10, tzinfo=UTC)


def test_no_daily_collection_never_imports_pilot_or_writes_root(tmp_path):
    root = tmp_path / "daily"
    r = review_daily_research(root, TIME)
    assert r["status"] == "awaiting_daily_observations"
    assert r["observations_needed_before_first_comparison"] == 21
    assert r["comparison"] is None and not root.exists()


def test_valid_protocol_quote_warms_research_but_not_execution(tmp_path):
    source = TIME.replace(minute=5)
    raw = json.dumps(
        dict(
            timestamp=int(source.timestamp()),
            datetime=source.isoformat(),
            metal="XAU",
            currency="USD",
            unit="troy_ounce",
            exchange="FOREXCOM",
            symbol="FOREXCOM:XAUUSD",
            price=2000,
            bid=1999,
            ask=2001,
        )
    ).encode()
    capture_daily(tmp_path, "fixture", lambda _: (raw, 200), lambda: TIME)
    r = review_daily_research(tmp_path, TIME)
    assert r["status"] == "gathering_history" and r["current_eligible_history"] == 1
    assert r["observations_needed_before_first_comparison"] == 20
    assert r["comparison"]["fixed_profiles"]["strict_execution_screen"]["blocked_count"] == 1
    assert not r["orders_enabled"] and not r["market_validation"]
    assert review_daily_research(tmp_path, TIME.replace(hour=13))["status"] == "unavailable"


def test_reservation_outside_protocol_is_not_usable_research(tmp_path):
    p = tmp_path / "attempts"
    p.mkdir()
    (p / "2026-10-13.json").write_text(
        json.dumps(
            dict(
                utc_date="2026-10-13",
                reserved_at="2026-10-13T13:00:00+00:00",
                status="reserved_no_automatic_retry",
                attempts=1,
            )
        )
    )
    assert review_daily_research(tmp_path, TIME)["status"] == "unavailable"


def test_pilot_quote_without_daily_reservation_is_not_imported(tmp_path):
    raw = json.dumps(
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
    ).encode()
    capture_goldapi(tmp_path / "quotes", "fixture", lambda _: (raw, 200), lambda: TIME)
    r = review_daily_research(tmp_path, TIME)
    assert r["status"] == "unavailable" and r["comparison"] is None
