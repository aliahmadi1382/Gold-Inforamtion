"""Versioned contracts shared by adapters, storage, research, and JSON Schema."""

from datetime import date, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must contain an explicit timezone offset")
    return value


Timestamp = Annotated[datetime, AfterValidator(aware)]
NonEmpty = Annotated[str, Field(min_length=1)]
Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
LicenseStatus = Literal["OPEN_PUBLIC", "LICENSED", "RESTRICTED"]
Layer = Literal[
    "price",
    "structure",
    "positioning",
    "macro",
    "central_banks",
    "etf",
    "physical",
    "news",
    "calendar",
    "history",
    "options",
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)


class Provenance(Contract):
    source_id: NonEmpty
    source_url: HttpUrl
    provider: NonEmpty
    dataset: NonEmpty
    observed_at: Timestamp
    available_at: Timestamp
    retrieved_at: Timestamp
    availability_basis: Literal["verified_release", "retrieval_time", "synthetic"]
    original_timestamp: NonEmpty
    original_timezone: NonEmpty
    unit: NonEmpty
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    transformations: tuple[str, ...] = ()
    version: NonEmpty = "1.0.0"
    license_status: LicenseStatus
    license_id: NonEmpty
    confidence: float = Field(ge=0, le=1)
    raw_sha256: Hash
    raw_record_id: NonEmpty
    synthetic: bool = False

    @field_validator("original_timezone")
    @classmethod
    def timezone_exists(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (KeyError, ValueError) as exc:
            raise ValueError("original_timezone must be an IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def chronology(self):
        if self.available_at > self.retrieved_at:
            raise ValueError("available_at cannot be later than retrieved_at")
        if self.availability_basis == "retrieval_time" and self.available_at != self.retrieved_at:
            raise ValueError("unknown release time must use retrieval time as available_at")
        if self.synthetic != (self.availability_basis == "synthetic"):
            raise ValueError("synthetic flag and availability basis must agree")
        return self


class Record(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    provenance: Provenance


class PriceBar(Record):
    kind: Literal["price_bar"] = "price_bar"
    instrument: NonEmpty
    venue: NonEmpty
    timeframe: Literal["1m", "5m", "15m", "1h", "4h", "1d", "1w", "1mo"]
    price_type: Literal["spot", "benchmark", "futures", "etf", "cfd"]
    contract_expiry: date | None = None
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float | None = Field(default=None, ge=0)
    volume_unit: Literal["contracts", "shares", "troy_ounces", "ticks"] | None = None
    open_interest: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def bar_integrity(self):
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("OHLC values do not fit inside low/high")
        if self.provenance.observed_at > self.provenance.available_at:
            raise ValueError("a closed bar cannot be available before its end time")
        if (self.volume is None) != (self.volume_unit is None):
            raise ValueError("volume and volume_unit must both be set or both absent")
        if self.price_type == "futures" and self.contract_expiry is None:
            raise ValueError(
                "futures bars require a contract expiry; no implicit continuous series"
            )
        return self


class Observation(Record):
    """Scalar series, distinguished by metric and explicit dimensions."""

    kind: Literal["observation"] = "observation"
    layer: Layer
    series_id: NonEmpty
    value: float | None
    dimensions: dict[str, str] = Field(default_factory=dict)
    vintage_date: date | None = None


class Positioning(Record):
    kind: Literal["positioning"] = "positioning"
    market_code: str = Field(pattern=r"^\d{6}$")
    report_type: Literal["legacy_futures_only", "disaggregated_futures_only"]
    category: NonEmpty
    long: int = Field(ge=0)
    short: int = Field(ge=0)
    spreading: int | None = Field(default=None, ge=0)
    open_interest: int = Field(ge=0)

    @model_validator(mode="after")
    def positions_fit(self):
        if max(self.long, self.short, self.spreading or 0) > self.open_interest:
            raise ValueError("positions exceed total open interest")
        if self.provenance.observed_at > self.provenance.available_at:
            raise ValueError("report cannot be available before its observation date")
        return self

    @property
    def net(self) -> int:
        return self.long - self.short


class NewsEvent(Record):
    kind: Literal["news_event"] = "news_event"
    event_id: NonEmpty
    headline: NonEmpty
    event_time: Timestamp | None
    published_at: Timestamp
    entities: tuple[str, ...] = ()
    channels: tuple[str, ...] = ()
    verification: Literal["unverified", "primary_source", "corroborated"]
    related_story_urls: tuple[HttpUrl, ...] = ()
    # Store a short original summary, never unlicensed full article text.
    summary: NonEmpty

    @model_validator(mode="after")
    def publication(self):
        if self.published_at > self.provenance.available_at:
            raise ValueError("story cannot be available before publication")
        return self


class CalendarRelease(Record):
    kind: Literal["calendar_release"] = "calendar_release"
    event_id: NonEmpty
    series_id: NonEmpty
    scheduled_at: Timestamp
    actual_release_at: Timestamp | None = None
    reference_period: NonEmpty
    consensus: float | None = None
    consensus_as_of: Timestamp | None = None
    previous: float | None = None
    actual: float | None = None

    @model_validator(mode="after")
    def released_values(self):
        if (self.consensus is None) != (self.consensus_as_of is None):
            raise ValueError("consensus needs its own as-of timestamp")
        if self.consensus_as_of and self.consensus_as_of > self.provenance.available_at:
            raise ValueError("consensus cannot come from the future")
        if self.actual is not None:
            if not self.actual_release_at or self.actual_release_at > self.provenance.available_at:
                raise ValueError("actual requires a release time at or before availability")
            if self.consensus_as_of and self.consensus_as_of >= self.actual_release_at:
                raise ValueError("consensus must precede actual release")
        return self


class HistoricalEvent(Contract):
    event_id: NonEmpty
    title: NonEmpty
    start_date: date
    end_date: date | None = None
    date_precision: Literal["day", "month", "year", "range"]
    regime: NonEmpty
    source_urls: tuple[HttpUrl, ...] = Field(min_length=1)
    verification: Literal["verified", "research_candidate"]
    notes: NonEmpty

    @model_validator(mode="after")
    def date_order(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("historical event end precedes start")
        return self


RECORD_TYPES = {
    "price_bar": PriceBar,
    "observation": Observation,
    "positioning": Positioning,
    "news_event": NewsEvent,
    "calendar_release": CalendarRelease,
}
