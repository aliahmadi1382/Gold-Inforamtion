"""Explicit adapters: canonical OHLC CSV, official CFTC legacy CSV, FRED JSON."""

import csv
import io
import json
import os
import re
import time
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .models import RECORD_TYPES, Observation, Positioning, PriceBar, Provenance, aware
from .registry import Registry, Source, validate_record_source
from .storage import Store


def timestamp(value: str) -> datetime:
    return aware(datetime.fromisoformat(value.replace("Z", "+00:00"))).astimezone(UTC)


def provenance(
    source: Source,
    digest: str,
    row_id: str,
    observed: datetime,
    retrieved: datetime,
    dataset: str,
    unit: str,
    currency: str | None,
    original: str,
    available: datetime | None = None,
    synthetic: bool = False,
    timezone: str = "UTC",
    transformations: tuple[str, ...] = (),
) -> Provenance:
    if synthetic != (source.implementation == "synthetic"):
        raise ValueError("synthetic data requires a synthetic registry source")
    return Provenance(
        source_id=source.source_id,
        source_url=source.url,
        provider=source.provider,
        dataset=dataset,
        observed_at=observed,
        available_at=available or retrieved,
        retrieved_at=retrieved,
        availability_basis="synthetic"
        if synthetic
        else ("verified_release" if available else "retrieval_time"),
        original_timestamp=original,
        original_timezone=timezone,
        unit=unit,
        currency=currency,
        transformations=transformations,
        license_status=source.license_status,
        license_id=source.license_id,
        confidence=1.0 if synthetic else 0.5,
        raw_sha256=digest,
        raw_record_id=row_id,
        synthetic=synthetic,
    )


def read_csv(content: bytes) -> list[dict]:
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ValueError("CSV must have unique named columns")
    rows = list(reader)
    if not rows or any(None in row or None in row.values() for row in rows):
        raise ValueError("CSV is empty or has ragged rows")
    return rows


def import_records(store: Store, path: Path, raw_dir: Path, registry: Registry) -> int:
    """Import already normalized JSONL with separately supplied, hash-named raw evidence."""
    records = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        if not isinstance(data, dict) or data.get("kind") not in RECORD_TYPES:
            raise ValueError("unknown JSONL record kind")
        record = RECORD_TYPES[data["kind"]].model_validate(data)
        validate_record_source(record, registry)
        records.append(record)
    if not records:
        raise ValueError("no normalized records supplied")
    for digest in {r.provenance.raw_sha256 for r in records}:
        content = (raw_dir / digest).read_bytes()
        if store.put_raw(content) != digest:
            raise ValueError("imported raw evidence does not match its hash filename")
    return store.put(records)


def import_prices(
    store: Store,
    path: Path,
    source: Source,
    *,
    instrument: str,
    venue: str,
    dataset: str,
    timeframe: str = "1d",
    price_type: str = "spot",
    currency: str = "USD",
    unit: str = "currency_per_troy_ounce",
    retrieved_at: datetime | None = None,
    verified_availability: bool = False,
    synthetic: bool = False,
    volume_unit: str | None = None,
    contract_expiry: date | None = None,
    original_timezone: str = "UTC",
) -> int:
    if "price" not in source.layers:
        raise ValueError("source is not registered for price data")
    content = path.read_bytes()
    rows = read_csv(content)
    required = {"observed_at", "open", "high", "low", "close"}
    optional = {"available_at", "volume", "open_interest"}
    if not required <= rows[0].keys() or rows[0].keys() - required - optional:
        raise ValueError("unexpected price CSV columns; see canonical CSV contract")
    if (verified_availability or synthetic) and "available_at" not in rows[0]:
        raise ValueError("verified/synthetic availability requires available_at column")
    digest = store.put_raw(content)
    retrieved = retrieved_at or datetime.now(UTC)
    records = []
    seen = set()
    for line, row in enumerate(rows, 2):
        observed = timestamp(row["observed_at"])
        if observed in seen:
            raise ValueError(f"duplicate price timestamp at CSV line {line}")
        seen.add(observed)
        original = datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00"))
        if original.utcoffset() != observed.astimezone(ZoneInfo(original_timezone)).utcoffset():
            raise ValueError("CSV timestamp offset does not match declared original timezone")
        available = timestamp(row["available_at"]) if verified_availability or synthetic else None
        volume = float(row["volume"]) if row.get("volume") else None
        records.append(
            PriceBar(
                provenance=provenance(
                    source,
                    digest,
                    f"line:{line}",
                    observed,
                    retrieved,
                    dataset,
                    unit,
                    currency,
                    row["observed_at"],
                    available,
                    synthetic,
                    timezone=original_timezone,
                    transformations=("canonical_csv_v1",),
                ),
                instrument=instrument,
                venue=venue,
                timeframe=timeframe,
                price_type=price_type,
                contract_expiry=contract_expiry,
                **{key: float(row[key]) for key in ("open", "high", "low", "close")},
                volume=volume,
                volume_unit=volume_unit if volume is not None else None,
                open_interest=float(row["open_interest"]) if row.get("open_interest") else None,
            )
        )
    return store.put(records)


def import_cftc(
    store: Store,
    path: Path,
    source: Source,
    market_code: str = "088691",
    retrieved_at: datetime | None = None,
    *,
    futures_only_confirmed: bool = False,
) -> int:
    """Official annual legacy futures-only CSV. No guessed Friday release times."""
    if source.source_id != "cftc_legacy":
        raise ValueError("CFTC adapter requires the cftc_legacy registry source")
    if not futures_only_confirmed:
        raise ValueError("confirm the file is legacy futures-only; headers alone are insufficient")
    content = path.read_bytes()
    rows = read_csv(content)
    # CFTC archive families use both human-readable and underscore-style headers.
    # Only explicit legacy fields are mapped; disaggregated names cannot pass this check.
    aliases = {
        "CFTC Contract Market Code": "CFTC_Contract_Market_Code",
        "As of Date in Form YYYY-MM-DD": "As_of_Date_In_Form_YYYY-MM-DD",
        "Open Interest (All)": "Open_Interest_All",
        "Noncommercial Positions-Long (All)": "NonComm_Positions_Long_All",
        "Noncommercial Positions-Short (All)": "NonComm_Positions_Short_All",
        "Noncommercial Positions-Spreading (All)": "NonComm_Positions_Spread_All",
        "Commercial Positions-Long (All)": "Comm_Positions_Long_All",
        "Commercial Positions-Short (All)": "Comm_Positions_Short_All",
        "Nonreportable Positions-Long (All)": "NonRept_Positions_Long_All",
        "Nonreportable Positions-Short (All)": "NonRept_Positions_Short_All",
    }
    mapped_rows = []
    for row in rows:
        mapped = {aliases.get(key.strip(), key.strip()): value for key, value in row.items()}
        if len(mapped) != len(row):
            raise ValueError("ambiguous CFTC header aliases")
        mapped_rows.append(mapped)
    rows = mapped_rows
    required = {
        "CFTC_Contract_Market_Code",
        "As_of_Date_In_Form_YYYY-MM-DD",
        "Open_Interest_All",
        "NonComm_Positions_Long_All",
        "NonComm_Positions_Short_All",
        "NonComm_Positions_Spread_All",
        "Comm_Positions_Long_All",
        "Comm_Positions_Short_All",
        "NonRept_Positions_Long_All",
        "NonRept_Positions_Short_All",
    }
    if not required <= rows[0].keys():
        raise ValueError("unsupported CFTC headers; expected legacy futures-only annual CSV")
    digest = store.put_raw(content)
    retrieved = retrieved_at or datetime.now(UTC)
    records = []
    seen = set()
    for line, row in enumerate(rows, 2):
        family = row.get("FutOnly_or_Combined", "FutOnly").strip().lower()
        if family not in {"futonly", "futures only"}:
            raise ValueError("combined futures/options files are not supported by this adapter")
        if row["CFTC_Contract_Market_Code"].strip().zfill(6) != market_code:
            continue
        report_date = date.fromisoformat(row["As_of_Date_In_Form_YYYY-MM-DD"][:10])
        if report_date in seen:
            raise ValueError("duplicate CFTC report date; do not mix report families")
        seen.add(report_date)
        observed = datetime.combine(report_date, datetime.min.time(), UTC)
        for category, prefix in (
            ("non_commercial", "NonComm"),
            ("commercial", "Comm"),
            ("non_reportable", "NonRept"),
        ):

            def integer(key, row=row):
                return int(row[key].strip().replace(",", ""))

            records.append(
                Positioning(
                    provenance=provenance(
                        source,
                        digest,
                        f"line:{line}:{category}",
                        observed,
                        retrieved,
                        "legacy_futures_only",
                        "contracts",
                        None,
                        report_date.isoformat(),
                        transformations=(
                            "cftc_legacy_csv_v1",
                            "date_only_period_label_utc",
                            "operator_attested_legacy_futures_only",
                        ),
                    ),
                    market_code=market_code,
                    report_type="legacy_futures_only",
                    category=category,
                    long=integer(f"{prefix}_Positions_Long_All"),
                    short=integer(f"{prefix}_Positions_Short_All"),
                    spreading=integer("NonComm_Positions_Spread_All")
                    if prefix == "NonComm"
                    else None,
                    open_interest=integer("Open_Interest_All"),
                )
            )
    if not records:
        raise ValueError("no matching CFTC gold market records")
    return store.put(records)


def fetch_bytes(url: str, attempts: int = 3) -> bytes:
    """Bounded requests; never expose request URLs (which may contain credentials)."""
    for attempt in range(attempts):
        try:
            request = Request(url, headers={"User-Agent": "GoldMarketIntelligence/0.1"})
            with urlopen(request, timeout=30) as response:
                content = response.read(20_000_001)
                if len(content) > 20_000_000:
                    raise ValueError("provider response exceeds 20 MB limit")
                return content
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
                raise ValueError(f"provider request failed with HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError):
            if attempt == attempts - 1:
                raise ValueError("provider connection failed after bounded retries") from None
        time.sleep(2**attempt)
    raise ValueError("provider request failed")


def ingest_fred(
    store: Store,
    source: Source,
    series_id: str,
    start: date,
    end: date,
    unit: str,
    currency: str | None = None,
    vintage: date | None = None,
    fetch=fetch_bytes,
) -> int:
    if source.source_id != "fred" or not re.fullmatch(r"[A-Z0-9_]+", series_id):
        raise ValueError("invalid FRED source or series ID")
    if start > end or (vintage and vintage > datetime.now(UTC).date()):
        raise ValueError("invalid observation interval or future vintage")
    key = os.environ.get("FRED_API_KEY")
    if not key:
        raise ValueError("set FRED_API_KEY in the environment before fetching")
    records = []
    offset = 0
    expected_total = None
    seen_dates = set()
    series_source = Source.model_validate(
        {**source.model_dump(), "url": f"https://fred.stlouisfed.org/series/{series_id}"}
    )
    for _page in range(100):
        params = dict(
            series_id=series_id,
            api_key=key,
            file_type="json",
            limit=10000,
            offset=offset,
            observation_start=start.isoformat(),
            observation_end=end.isoformat(),
            sort_order="asc",
            units="lin",
        )
        if vintage:
            params.update(realtime_start=vintage.isoformat(), realtime_end=vintage.isoformat())
        content = fetch("https://api.stlouisfed.org/fred/series/observations?" + urlencode(params))
        try:
            payload = json.loads(content)
            rows, total = payload["observations"], int(payload["count"])
            if (
                not isinstance(rows, list)
                or total < 0
                or int(payload["offset"]) != offset
                or offset + len(rows) > total
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise ValueError("unexpected FRED response structure") from None
        if not rows and offset < total:
            raise ValueError("incomplete FRED pagination")
        if expected_total is not None and total != expected_total:
            raise ValueError("FRED count changed during pagination; retry the acquisition")
        expected_total = total
        retrieved = datetime.now(UTC)
        digest = store.put_raw(content)
        for index, row in enumerate(rows):
            original = row["date"]
            observed_date = date.fromisoformat(original)
            if observed_date in seen_dates or not start <= observed_date <= end:
                raise ValueError("duplicate or out-of-range FRED observation")
            seen_dates.add(observed_date)
            observed = datetime.combine(observed_date, datetime.min.time(), UTC)
            records.append(
                Observation(
                    provenance=provenance(
                        series_source,
                        digest,
                        f"observations:{index}",
                        observed,
                        retrieved,
                        series_id,
                        unit,
                        currency,
                        original,
                        transformations=("fred_json_v1", "date_only_period_label_utc"),
                    ),
                    layer="macro",
                    series_id=series_id,
                    value=None if row["value"] == "." else float(row["value"]),
                    vintage_date=vintage,
                    dimensions={
                        "realtime_start": row["realtime_start"],
                        "realtime_end": row["realtime_end"],
                    },
                )
            )
        offset += len(rows)
        if offset >= total:
            return store.put(records)
    raise ValueError("FRED pagination exceeded 100 pages; narrow the observation range")
