import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from gold_intelligence.forward_quotes import ForwardQuoteEvidence, capture_spot, review_spot

TIME = datetime(2026, 10, 12, 7, 16, tzinfo=UTC)
RAW = b'{"nominal":"XAUUSD","price":"4000.25","timestamp":"2026-10-12 07:10:57"}'


def test_receipt_is_known_but_provider_timezone_unit_and_freshness_stay_unknown():
    r = review_spot(RAW, TIME, TIME + timedelta(seconds=2))
    assert r.received_at == TIME + timedelta(seconds=2)
    assert r.provider_time_label == "2026-10-12 07:10:57" and r.provider_timezone == "unknown"
    assert r.raw_sha256 == hashlib.sha256(RAW).hexdigest()
    assert not r.trading_eligible and not r.daily_backtest_ready
    data = r.model_dump()
    data["trading_eligible"] = True
    with pytest.raises(ValueError):
        ForwardQuoteEvidence.model_validate(data)


@pytest.mark.parametrize(
    "change",
    [
        {"price": "NaN"},
        {"price": True},
        {"nominal": "OTHER"},
        {"timestamp": "2026-10-12"},
        {"timestamp": "2026-10-12 07:10:57Z"},
        {"unit": "USD"},
    ],
)
def test_invalid_or_changed_schema_is_rejected_without_echoing_provider_data(change):
    data = json.loads(RAW)
    data.update(change)
    with pytest.raises(ValueError, match="spot quote schema"):
        review_spot(json.dumps(data).encode(), TIME, TIME)


def test_notice_and_reversed_receipt_are_not_a_quote():
    with pytest.raises(ValueError):
        review_spot(b'{"Information":"secret"}', TIME, TIME)
    with pytest.raises(ValueError):
        review_spot(RAW, TIME, TIME - timedelta(seconds=1))


def test_single_request_private_receipt_binding_and_no_overwrite(tmp_path):
    calls = []

    def fetch(url, attempts):
        calls.append(attempts)
        return RAW

    times = iter([TIME, TIME + timedelta(seconds=2)])
    folder = capture_spot(tmp_path, "test-secret", fetch, lambda: next(times))
    assert calls == [1] and (folder / "raw.json").read_bytes() == RAW
    receipt = json.loads((folder / "receipt.json").read_text())
    assert receipt["raw_sha256"] == hashlib.sha256(RAW).hexdigest()
    assert "test-secret" not in (folder / "receipt.json").read_text()
    with pytest.raises(FileExistsError):
        capture_spot(tmp_path, "test-secret", fetch, lambda: TIME)
    assert calls == [1]


def test_provider_notice_keeps_raw_and_failed_receipt_without_retry(tmp_path):
    calls = []

    def fetch(url, attempts):
        calls.append(attempts)
        return b'{"Note":"key test-secret quota"}'

    with pytest.raises(ValueError):
        capture_spot(tmp_path, "test-secret", fetch, lambda: TIME)
    assert calls == [1]
    folder = next(tmp_path.iterdir())
    assert (folder / "raw.json").exists() and not (folder / "quote-review.json").exists()
    assert "test-secret" not in (folder / "receipt.json").read_text()


def test_duplicate_json_fields_and_noncanonical_timestamp_do_not_silently_normalize():
    duplicate = RAW.replace(b'"price":"4000.25"', b'"price":"4000.25","price":"4001"')
    for content in (duplicate, RAW.replace(b"2026-10-12", b"2026-1-12")):
        with pytest.raises(ValueError):
            review_spot(content, TIME, TIME)


def test_missing_key_or_naive_local_clock_makes_no_request(tmp_path):
    def fetch(*args, **kwargs):
        pytest.fail("request should not happen")

    with pytest.raises(ValueError):
        capture_spot(tmp_path, None, fetch)
    with pytest.raises(ValueError):
        capture_spot(tmp_path, "test-secret", fetch, lambda: TIME.replace(tzinfo=None))
    assert list(tmp_path.iterdir()) == []
