import json
from datetime import date

import pytest

from gold_intelligence.goldapi_history import inspect_history

START, END = date(2026, 9, 4), date(2026, 9, 7)


def raw(rows):
    return json.dumps(
        dict(
            metal="XAU",
            currency="USD",
            **{"from": START.isoformat(), "to": END.isoformat()},
            prices=rows,
        )
    ).encode()


def test_calendar_missingness_does_not_invent_trading_sessions():
    r = inspect_history(raw([dict(date="2026-09-05", price=2000)]), START, END)
    assert r["weekend_labels"] == ["2026-09-05"]
    assert len(r["missing_calendar_dates"]) == 3
    assert not r["daily_backtest_ready"] and not r["trading_eligible"]
    assert r["unit_status"] == "not_explicit_in_response"


@pytest.mark.parametrize(
    "rows",
    [
        [dict(date="2026-09-05", price=2000), dict(date="2026-09-05", price=2001)],
        [dict(date="2026-09-07", price=2000), dict(date="2026-09-04", price=2000)],
        [dict(date="2026-09-08", price=2000)],
        [dict(date="2026-09-05", price=True)],
        [dict(date="2026-09-05", price="NaN")],
    ],
)
def test_bad_history_not_silently_sorted_deduplicated_or_filtered(rows):
    with pytest.raises(ValueError):
        inspect_history(raw(rows), START, END)
