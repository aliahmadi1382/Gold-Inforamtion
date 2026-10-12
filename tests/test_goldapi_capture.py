import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from gold_intelligence.goldapi_capture import NoRedirect, capture_goldapi

TIME = datetime(2026, 10, 12, 7, tzinfo=UTC)
RAW = json.dumps(
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


def test_capture_binds_raw_receipt_and_review_and_prevents_overwrite(tmp_path):
    calls = []

    def fetch(key):
        calls.append(key)
        return RAW, 200

    clocks = iter([TIME, TIME + timedelta(seconds=2)])
    folder = capture_goldapi(tmp_path, "private-key", fetch, lambda: next(clocks))
    receipt = json.loads((folder / "receipt.json").read_text())
    review = json.loads((folder / "quote-review.json").read_text())
    assert receipt["raw_sha256"] == review["raw_sha256"] == hashlib.sha256(RAW).hexdigest()
    assert not review["trading_eligible"]
    assert "private-key" not in (folder / "receipt.json").read_text()
    with pytest.raises(FileExistsError):
        capture_goldapi(tmp_path, "private-key", fetch, lambda: TIME)
    assert len(calls) == 1


def test_rejected_payload_preserved_without_review_or_retry(tmp_path):
    calls = []

    def fetch(key):
        calls.append(key)
        return b'{"error":"private-key"}', 200

    with pytest.raises(ValueError, match="capture failed"):
        capture_goldapi(tmp_path, "private-key", fetch, lambda: TIME)
    folder = next(tmp_path.iterdir())
    assert (folder / "raw.json").exists()
    assert not (folder / "quote-review.json").exists()
    assert "private-key" not in (folder / "receipt.json").read_text()
    assert len(calls) == 1


@pytest.mark.parametrize("key", [None, "", "key\nheader"])
def test_invalid_key_never_requests(tmp_path, key):
    with pytest.raises(ValueError):
        capture_goldapi(tmp_path, key, lambda _: pytest.fail("unexpected request"))
    assert not list(tmp_path.iterdir())


def test_redirect_does_not_forward_authentication():
    with pytest.raises(ValueError, match="redirect rejected"):
        NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example")


def test_transport_failure_is_sanitized_and_attempted_once(tmp_path):
    calls = []

    def fetch(key):
        calls.append(key)
        raise ValueError("private-key upstream detail")

    with pytest.raises(ValueError, match="capture failed") as error:
        capture_goldapi(tmp_path, "private-key", fetch, lambda: TIME)
    assert "private-key" not in str(error.value)
    receipt = json.loads(next(tmp_path.iterdir()).joinpath("receipt.json").read_text())
    assert receipt["status"] == "failed" and receipt["attempts"] == 1
    assert len(calls) == 1


def test_reversed_receipt_clock_is_rejected(tmp_path):
    clocks = iter([TIME, TIME - timedelta(seconds=1)])
    with pytest.raises(ValueError):
        capture_goldapi(tmp_path, "private-key", lambda _: (RAW, 200), lambda: next(clocks))
    assert not next(tmp_path.iterdir()).joinpath("quote-review.json").exists()
