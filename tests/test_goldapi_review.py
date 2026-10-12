import json
from datetime import UTC, datetime, timedelta

import pytest

from gold_intelligence.goldapi_review import GoldApiReview, review_goldapi

TIME = datetime(2026, 10, 12, 7, tzinfo=UTC)


def payload():
    return dict(
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


def test_checked_declarations_and_known_age_never_promote_candidate():
    r = review_goldapi(json.dumps(payload()).encode(), TIME + timedelta(seconds=2))
    assert r.source_at == TIME and r.age_at_receipt_seconds == 2
    assert not r.trading_eligible and not r.market_validation
    data = r.model_dump()
    data["trading_eligible"] = True
    with pytest.raises(ValueError):
        GoldApiReview.model_validate(data)


@pytest.mark.parametrize(
    "change",
    [
        {"unit": "gram"},
        {"currency": "EUR"},
        {"exchange": "OANDA"},
        {"symbol": "OTHER:XAUUSD"},
        {"timestamp": True},
        {"timestamp": TIME.timestamp()},
        {"datetime": "2026-10-12T07:00:01Z"},
        {"datetime": "2026-10-12 07:00:00"},
        {"datetime": None},
        {"datetime": []},
        {"bid": 2002},
        {"bid": -1},
        {"price": "NaN"},
        {"ask": True},
    ],
)
def test_bad_metadata_price_or_mixed_source_is_rejected(change):
    data = payload()
    data.update(change)
    with pytest.raises(ValueError):
        review_goldapi(json.dumps(data).encode(), TIME)


def test_stale_future_missing_fields_and_duplicates_fail_closed():
    raw = json.dumps(payload()).encode()
    for received in (TIME - timedelta(seconds=1), TIME + timedelta(seconds=901)):
        with pytest.raises(ValueError):
            review_goldapi(raw, received)
    data = payload()
    data.pop("unit")
    with pytest.raises(ValueError):
        review_goldapi(json.dumps(data).encode(), TIME)
    duplicate = raw[:-1] + b',"bid":1998}'
    with pytest.raises(ValueError):
        review_goldapi(duplicate, TIME)
