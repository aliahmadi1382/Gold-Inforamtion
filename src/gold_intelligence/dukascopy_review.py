"""Inspect a manually exported UTC hourly BID file without certifying daily returns."""

import csv
import hashlib
import io
import math
from datetime import UTC, date, datetime, timedelta

from .models import aware


def review_hourly_bid(content: bytes, start: date, end: date, retrieved: datetime):
    retrieved = aware(retrieved).astimezone(UTC)
    if start > end or end >= retrieved.date() or (end - start).days > 366:
        raise ValueError("require a bounded interval of fully elapsed UTC dates")
    if len(content) > 10_000_000:
        raise ValueError("export exceeds size limit")
    reader = csv.reader(io.StringIO(content.decode("utf-8-sig")))
    if next(reader, None) != ["Etc/UTC", "Open", "High", "Low", "Close", "Volume"]:
        raise ValueError("unexpected UTC hourly export header")
    groups, previous = {}, None
    for line, row in enumerate(reader, 2):
        if len(row) != 6:
            raise ValueError("unexpected export columns")
        timestamp = aware(datetime.fromisoformat(row[0]))
        if timestamp.utcoffset() != timedelta(0) or any(
            (timestamp.minute, timestamp.second, timestamp.microsecond)
        ):
            raise ValueError("timestamp must be aligned to a UTC hour")
        if not start <= timestamp.date() <= end or timestamp + timedelta(hours=1) > retrieved:
            raise ValueError("bar outside elapsed requested interval")
        if previous is not None and timestamp <= previous:
            raise ValueError("duplicate or unordered hour")
        previous = timestamp
        o, h, low, close, volume = map(float, row[1:])
        if not all(math.isfinite(v) for v in (o, h, low, close, volume)) or not (
            0 < low <= min(o, close) <= max(o, close) <= h and volume >= 0
        ):
            raise ValueError("invalid hourly OHLC or volume")
        groups.setdefault(timestamp.date(), []).append((timestamp.hour, o, h, low, close, line))
    days = []
    current = start
    while current <= end:
        bars = groups.get(current, [])
        hours = [bar[0] for bar in bars]
        days.append(
            dict(
                date=current.isoformat(),
                weekday=current.weekday(),
                observed_hours=hours,
                absent_hours=[h for h in range(24) if h not in hours],
                observed_bar_count=len(bars),
                observed_bar_ohlc=None
                if not bars
                else dict(
                    open=bars[0][1],
                    high=max(b[2] for b in bars),
                    low=min(b[3] for b in bars),
                    close=bars[-1][4],
                ),
                raw_rows=[b[5] for b in bars],
                complete_session_verified=False,
            )
        )
        current += timedelta(days=1)
    if not groups:
        raise ValueError("empty export")
    return dict(
        schema_version="1.0.0",
        source_id="dukascopy_candidate",
        raw_sha256=hashlib.sha256(content).hexdigest(),
        retrieved_at=retrieved.isoformat(),
        export_timezone="Etc/UTC",
        offer_side="BID",
        instrument="XAU/USD",
        price_type="cfd",
        timeframe="1h",
        availability_basis="retrieval_time",
        volume_unit_verified=False,
        daily_backtest_ready=False,
        daily_returns_computed=False,
        scope="Observed hourly rows only; absent hours are not certified market closures.",
        start=start.isoformat(),
        end=end.isoformat(),
        rows=sum(len(v) for v in groups.values()),
        days=days,
    )
