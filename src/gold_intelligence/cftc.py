"""Reviewed CFTC public API: COMEX gold, disaggregated futures only.

Capture complete batches before inserting. Observation dates are labels; historical
publication instants are unknown and never reconstructed from the Friday schedule.
"""

import hashlib
import json
import re
from datetime import UTC, date, datetime
from typing import Literal
from urllib.parse import urlencode

from pydantic import Field, model_validator

from .ingestion import fetch_bytes, provenance
from .models import Contract, Hash, Positioning, Timestamp
from .storage import canonical

RESOURCE = "72hh-3qpy"
API = f"https://publicreporting.cftc.gov/resource/{RESOURCE}.json"
METADATA = f"https://publicreporting.cftc.gov/api/views/{RESOURCE}.json"
DATASET = "cftc_disaggregated_futures_only_gold_v1"
MARKET = "088691"
FIRST_DATE = date(2006, 6, 13)
PAGE_SIZE = 1000
MAX_ROWS = 10000
DATE_FIELD = "report_date_as_yyyy_mm_dd"
GROUPS = {
    "producer_merchant_processor_user": (
        "prod_merc_positions_long",
        "prod_merc_positions_short",
        None,
    ),
    "swap_dealer": (
        "swap_positions_long_all",
        "swap__positions_short_all",
        "swap__positions_spread_all",
    ),
    "managed_money": (
        "m_money_positions_long_all",
        "m_money_positions_short_all",
        "m_money_positions_spread",
    ),
    "other_reportable": (
        "other_rept_positions_long",
        "other_rept_positions_short",
        "other_rept_positions_spread",
    ),
    "nonreportable": ("nonrept_positions_long_all", "nonrept_positions_short_all", None),
}
TEXT_FIELDS = {
    "market_and_exchange_names": "GOLD - COMMODITY EXCHANGE INC.",
    "contract_market_name": "GOLD",
    "cftc_contract_market_code": MARKET,
    "commodity_name": "GOLD",
    "contract_units": "(CONTRACTS OF 100 TROY OUNCES)",
    "futonly_or_combined": "FutOnly",
}
NUMBER_FIELDS = (
    "open_interest_all",
    "tot_rept_positions_long_all",
    "tot_rept_positions_short",
    *(field for fields in GROUPS.values() for field in fields if field),
)
FIELD_TYPES = {
    **dict.fromkeys(TEXT_FIELDS, "text"),
    DATE_FIELD: "calendar_date",
    **dict.fromkeys(NUMBER_FIELDS, "number"),
}
TRANSFORMS = ("cftc_pre_gold_v1", "date_label_utc_midnight_not_release", "capture_hash_lineage")


class CotPage(Contract):
    offset: int = Field(ge=0)
    sha256: Hash


class CotCapture(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    dataset: Literal["cftc_disaggregated_futures_only_gold_v1"] = DATASET
    resource: Literal["72hh-3qpy"] = RESOURCE
    start: date
    end: date
    retrieved_at: Timestamp
    metadata_before: Hash
    metadata_after: Hash
    count_before: Hash
    count_after: Hash
    expected_rows: int = Field(gt=0, le=MAX_ROWS)
    pages: tuple[CotPage, ...]

    @model_validator(mode="after")
    def valid_bounds(self):
        if not FIRST_DATE <= self.start <= self.end:
            raise ValueError("invalid CFTC observation interval")
        if [p.offset for p in self.pages] != list(range(0, self.expected_rows, PAGE_SIZE)):
            raise ValueError("CFTC page offsets do not cover the declared row count")
        return self


def integer(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+", value, flags=re.ASCII):
        raise ValueError("CFTC counts must be nonnegative integer strings")
    return int(value)


def metadata_version(content):
    data = json.loads(content)
    if not isinstance(data, dict) or (data.get("id"), data.get("name"), data.get("viewType")) != (
        RESOURCE,
        "Disaggregated - Futures Only",
        "tabular",
    ):
        raise ValueError("unexpected CFTC dataset metadata")
    columns = data.get("columns")
    if not isinstance(columns, list) or any(not isinstance(c, dict) for c in columns):
        raise ValueError("invalid CFTC metadata columns")
    fields = [c.get("fieldName") for c in columns]
    if any(not isinstance(f, str) for f in fields) or len(set(fields)) != len(fields):
        raise ValueError("ambiguous CFTC metadata columns")
    types = {c["fieldName"]: c.get("dataTypeName") for c in columns}
    if any(types.get(field) != expected for field, expected in FIELD_TYPES.items()):
        raise ValueError("CFTC field types changed; review the provider schema")
    version = (data.get("rowsUpdatedAt"), data.get("viewLastModified"))
    if any(type(v) is not int or v < 0 for v in version):
        raise ValueError("CFTC metadata lacks revision markers")
    return version


def count_rows(content):
    rows = json.loads(content)
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError("invalid CFTC count response")
    if set(rows[0]) != {"count"}:
        raise ValueError("invalid CFTC count response")
    count = integer(rows[0]["count"])
    if not 0 < count <= MAX_ROWS:
        raise ValueError("CFTC interval is empty or exceeds the bounded history limit")
    return count


def query_url(start, end, offset=None):
    where = (
        f"cftc_contract_market_code='{MARKET}' AND "
        f"{DATE_FIELD} >= '{start.isoformat()}T00:00:00' AND "
        f"{DATE_FIELD} <= '{end.isoformat()}T00:00:00'"
    )
    params = {"$where": where, "$select": "count(*)"}
    if offset is not None:
        params.update(
            {
                "$select": ",".join(FIELD_TYPES),
                "$order": f"{DATE_FIELD} ASC",
                "$limit": PAGE_SIZE,
                "$offset": offset,
            }
        )
    return API + "?" + urlencode(params)


def parse_row(row):
    if not isinstance(row, dict) or set(row) != set(FIELD_TYPES):
        raise ValueError("unexpected CFTC row fields or missing values")
    if any(row[field] != value for field, value in TEXT_FIELDS.items()):
        raise ValueError("CFTC market, report family or contract unit mismatch")
    label = row[DATE_FIELD]
    if not isinstance(label, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T00:00:00\.000", label):
        raise ValueError("CFTC observation must be a date label at midnight")
    day = date.fromisoformat(label[:10])
    counts = {field: integer(row[field]) for field in NUMBER_FIELDS}
    oi = counts["open_interest_all"]
    groups = {
        category: (counts[long], counts[short], counts[spread] if spread else None)
        for category, (long, short, spread) in GROUPS.items()
    }
    for side, total_field in enumerate(("tot_rept_positions_long_all", "tot_rept_positions_short")):
        reportable = sum(v[side] + (v[2] or 0) for k, v in groups.items() if k != "nonreportable")
        if reportable != counts[total_field] or reportable + groups["nonreportable"][side] != oi:
            raise ValueError("CFTC category positions do not reconcile to open interest")
    return day, oi, groups


def raw_json(store, digest):
    path = store.root / "raw" / digest
    if not path.is_file():
        raise ValueError("missing CFTC raw evidence")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError("corrupt CFTC raw evidence")
    return content


def capture_records(store, source, capture, digest):
    """Reconcile every captured page and reconstruct the exact normalized batch."""
    if source.source_id != "cftc_disaggregated" or str(source.url) != API:
        raise ValueError("CFTC adapter requires its reviewed public API registry source")
    if metadata_version(raw_json(store, capture.metadata_before)) != metadata_version(
        raw_json(store, capture.metadata_after)
    ):
        raise ValueError("CFTC dataset changed during acquisition; retry the complete batch")
    if any(
        count_rows(raw_json(store, h)) != capture.expected_rows
        for h in (
            capture.count_before,
            capture.count_after,
        )
    ):
        raise ValueError("CFTC count changed during acquisition")
    records = []
    previous = None
    for page in capture.pages:
        rows = json.loads(raw_json(store, page.sha256))
        expected = min(PAGE_SIZE, capture.expected_rows - page.offset)
        if not isinstance(rows, list) or len(rows) != expected:
            raise ValueError("CFTC page is truncated or exceeds its declared count")
        for index, row in enumerate(rows):
            day, oi, groups = parse_row(row)
            observed = datetime.combine(day, datetime.min.time(), UTC)
            if not capture.start <= day <= capture.end or observed > capture.retrieved_at:
                raise ValueError("CFTC observation is outside the interval or in the future")
            if previous is not None and day <= previous:
                raise ValueError("duplicate or unordered CFTC observation dates")
            previous = day
            for category, (long, short, spread) in groups.items():
                records.append(
                    Positioning(
                        provenance=provenance(
                            source,
                            digest,
                            f"row:{page.offset + index}:{category}",
                            observed,
                            capture.retrieved_at,
                            DATASET,
                            "contracts",
                            None,
                            row[DATE_FIELD],
                            transformations=TRANSFORMS,
                        ),
                        market_code=MARKET,
                        report_type="disaggregated_futures_only",
                        category=category,
                        long=long,
                        short=short,
                        spreading=spread,
                        open_interest=oi,
                    )
                )
    return records


def ingest_cftc_gold(store, source, start, end, fetch=fetch_bytes):
    if source.source_id != "cftc_disaggregated" or str(source.url) != API:
        raise ValueError("CFTC adapter requires its reviewed public API registry source")
    if not FIRST_DATE <= start <= end:
        raise ValueError("invalid CFTC observation interval")
    before = fetch(METADATA)
    metadata_version(before)
    metadata_before = store.put_raw(before)
    content = fetch(query_url(start, end))
    count_before = store.put_raw(content)
    total = count_rows(content)
    pages = tuple(
        CotPage(offset=offset, sha256=store.put_raw(fetch(query_url(start, end, offset))))
        for offset in range(0, total, PAGE_SIZE)
    )
    count_after = store.put_raw(fetch(query_url(start, end)))
    metadata_after = store.put_raw(fetch(METADATA))
    capture = CotCapture(
        start=start,
        end=end,
        retrieved_at=datetime.now(UTC),
        metadata_before=metadata_before,
        metadata_after=metadata_after,
        count_before=count_before,
        count_after=count_after,
        expected_rows=total,
        pages=pages,
    )
    digest = store.put_raw(canonical(capture.model_dump(mode="json")).encode())
    records = capture_records(store, source, capture, digest)
    return store.put(records)
