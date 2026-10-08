"""Bounded offline inspection of HistData's generic ASCII XAUUSD minute archive."""

import csv
import hashlib
import io
import math
import zipfile
from datetime import UTC, datetime, timedelta, timezone

from .models import aware

EST_FIXED = timezone(timedelta(hours=-5))


def review_archive(content: bytes, status: bytes, month: str, retrieved: datetime):
    period = datetime.strptime(month, "%Y%m")
    if period.strftime("%Y%m") != month:
        raise ValueError("require YYYYMM month")
    retrieved = aware(retrieved).astimezone(UTC)
    following = (period.replace(day=28) + timedelta(days=4)).replace(day=1)
    if following.replace(tzinfo=EST_FIXED).astimezone(UTC) > retrieved:
        raise ValueError("require a fully elapsed source month")
    if len(content) > 10_000_000 or len(status) > 1_000_000:
        raise ValueError("archive or status exceeds limit")
    base = f"DAT_ASCII_XAUUSD_M1_{month}"
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        entries = archive.infolist()
        if (
            len(entries) != 2
            or {e.filename for e in entries} != {base + ".csv", base + ".txt"}
            or sum(e.file_size for e in entries) > 20_000_000
        ):
            raise ValueError("unexpected archive members or expanded size")
        embedded_status = archive.read(base + ".txt")
        if embedded_status != status or f"File: {base}.csv Status Report" not in status.decode():
            raise ValueError("status report does not match archive")
        data = archive.read(base + ".csv")
    previous, count, gaps, days = None, 0, [], {}
    first, last = None, None
    for line, row in enumerate(csv.reader(io.StringIO(data.decode()), delimiter=";"), 1):
        if len(row) != 6:
            raise ValueError("unexpected minute columns")
        local = datetime.strptime(row[0], "%Y%m%d %H%M%S")
        if (
            local.strftime("%Y%m%d %H%M%S") != row[0]
            or local.second
            or not (period <= local < following)
        ):
            raise ValueError("invalid source minute or month")
        instant = local.replace(tzinfo=EST_FIXED).astimezone(UTC)
        if previous is not None and instant <= previous:
            raise ValueError("duplicate or unordered minute")
        o, h, low, close, volume = map(float, row[1:])
        if not all(math.isfinite(v) for v in (o, h, low, close, volume)) or not (
            0 < low <= min(o, close) <= max(o, close) <= h and volume == 0
        ):
            raise ValueError("invalid OHLC or nonzero undocumented volume")
        if previous is not None and instant - previous > timedelta(minutes=1):
            gaps.append(
                dict(
                    preceding_utc=previous.isoformat(),
                    following_utc=instant.isoformat(),
                    absent_minutes=int((instant - previous).total_seconds() / 60) - 1,
                    following_raw_row=line,
                    market_closure_verified=False,
                )
            )
        key = instant.date().isoformat()
        days[key] = days.get(key, 0) + 1
        first = first or instant
        last, previous = instant, instant
        count += 1
    if not count:
        raise ValueError("empty minute archive")
    return dict(
        schema_version="1.0.0",
        source_id="histdata_candidate",
        month=month,
        archive_sha256=hashlib.sha256(content).hexdigest(),
        csv_sha256=hashlib.sha256(data).hexdigest(),
        status_sha256=hashlib.sha256(status).hexdigest(),
        status_matches_archive=True,
        retrieved_at=retrieved.isoformat(),
        availability_basis="retrieval_time",
        source_timezone="UTC-05:00 fixed; no DST",
        offer_side="BID",
        rows=count,
        first_utc=first.isoformat(),
        last_utc=last.isoformat(),
        observed_minutes_by_utc_date=days,
        gaps=gaps,
        volume_interpretation="zero placeholder; no observed market volume",
        price_unit_verified=False,
        calendar_verified=False,
        daily_backtest_ready=False,
        scope="Source-month boundaries do not cover whole UTC boundary days; no returns computed.",
    )
