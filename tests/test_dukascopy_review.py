from datetime import UTC, date, datetime

import pytest

from gold_intelligence.dukascopy_review import review_hourly_bid

HEADER = "Etc/UTC,Open,High,Low,Close,Volume\n"
ROW = "2026-10-01T00:00:00+00:00,10,12,9,11,5\n"


def review(text):
    return review_hourly_bid(
        text.encode(), date(2026, 10, 1), date(2026, 10, 3), datetime(2026, 10, 8, tzinfo=UTC)
    )


def test_absence_is_not_invented_ohlc_or_verified_closure():
    result = review(HEADER + ROW)
    assert result["rows"] == 1
    assert result["days"][0]["raw_rows"] == [2]
    assert result["days"][1]["observed_bar_ohlc"] is None
    assert result["days"][0]["absent_hours"] == list(range(1, 24))
    assert not result["daily_backtest_ready"]
    assert not result["days"][0]["complete_session_verified"]


@pytest.mark.parametrize(
    "text",
    [
        HEADER + ROW + ROW,
        HEADER.replace("Etc/UTC", "EST") + ROW,
        HEADER + ROW.replace("+00:00", "+01:00"),
        HEADER + ROW.replace("00:00:00", "00:30:00"),
        HEADER + ROW.replace(",12,", ",nan,"),
        HEADER + ROW.replace(",9,", ",13,"),
        HEADER,
    ],
)
def test_reject_ambiguous_or_invalid_exports(text):
    with pytest.raises(ValueError):
        review(text)


def test_reject_current_date_and_naive_retrieval():
    for retrieved in (datetime(2026, 10, 3, tzinfo=UTC), datetime(2026, 10, 8)):
        with pytest.raises(ValueError):
            review_hourly_bid(
                (HEADER + ROW).encode(), date(2026, 10, 1), date(2026, 10, 3), retrieved
            )
