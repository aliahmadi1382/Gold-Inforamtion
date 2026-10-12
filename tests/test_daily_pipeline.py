"""Fabricated provider responses test the full protocol; not real daily observations."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from gold_intelligence.daily_capture import capture_daily
from gold_intelligence.daily_research import review_daily_research


def test_twenty_one_weekday_receipts_cross_month_and_enable_only_signal_comparison(tmp_path):
    start = datetime(2026, 10, 13, 13, 10, tzinfo=UTC)
    days = [start + timedelta(days=i) for i in range(45)]
    times = [d for d in days if d.weekday() < 5][:21]
    calls = []
    for index, time in enumerate(times):
        source = time - timedelta(minutes=5)
        price = 2000 + index
        raw = json.dumps(
            dict(
                timestamp=int(source.timestamp()),
                datetime=source.isoformat(),
                metal="XAU",
                currency="USD",
                unit="troy_ounce",
                exchange="FOREXCOM",
                symbol="FOREXCOM:XAUUSD",
                price=price,
                bid=price - 1,
                ask=price + 1,
            )
        ).encode()

        def fetch(key, raw=raw):
            calls.append(key)
            return raw, 200

        capture_daily(tmp_path, "fixture", fetch, lambda time=time: time)
        report = review_daily_research(tmp_path, time)
        assert report["current_eligible_history"] == index + 1
        assert report["observations_needed_before_first_comparison"] == max(0, 20 - index)
    assert len(calls) == 21
    assert report["status"] == "signal_comparisons_available"
    assert report["protocol_status"]["monthly_reserved_attempts"] == 7
    assert report["protocol_status"]["local_remaining"] == 13
    profiles = report["comparison"]["fixed_profiles"]
    assert profiles["strict_execution_screen"]["blocked_count"] == 21
    assert profiles["delayed_observation_research"]["candidate_count"] == 1
    assert (
        profiles["delayed_observation_research"]["report"]["decisions"][-1]["prior_mean"] == 2009.5
    )
    assert not report["orders_enabled"] and report["performance_conclusion"] == "not_established"


def test_failed_response_remains_accounted_for_while_next_day_can_be_reviewed(tmp_path):
    first = datetime(2026, 10, 13, 13, 10, tzinfo=UTC)
    with pytest.raises(ValueError):
        capture_daily(tmp_path, "fixture", lambda _: (b'{"error":"quota"}', 200), lambda: first)
    failed = next((tmp_path / "quotes").iterdir())
    time = first + timedelta(days=1)
    source = time - timedelta(minutes=5)
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
    capture_daily(tmp_path, "fixture", lambda _: (raw, 200), lambda: time)
    report = review_daily_research(tmp_path, time)
    status = report["protocol_status"]
    assert report["status"] == "gathering_history" and report["current_eligible_history"] == 1
    assert status["monthly_reserved_attempts"] == 2 and status["local_remaining"] == 18
    assert status["recorded_failure_count"] == 1 and status["verified_daily_observations"] == 1
    assert status["coverage"]["excluded_capture_ids"] == [failed.name]
    assert (failed / "raw.json").read_bytes() == b'{"error":"quota"}'
    (failed / "raw.json").write_text("{}")
    assert review_daily_research(tmp_path, time)["status"] == "unavailable"
