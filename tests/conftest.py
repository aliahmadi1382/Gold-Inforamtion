from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from gold_intelligence.models import PriceBar, Provenance
from gold_intelligence.registry import load_registry
from gold_intelligence.storage import Store


@pytest.fixture
def registry():
    return load_registry(Path("sources/source_registry.yaml"))


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "store") as value:
        yield value


@pytest.fixture
def make_bar(store):
    raw = store.put_raw(b"explicitly synthetic test evidence")

    def factory(index=0, close=100.0, **changes):
        when = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=index)
        p_changes = changes.pop("provenance", {})
        p = dict(
            source_id="synthetic_demo",
            source_url="https://example.org/synthetic",
            provider="Gold Market Intelligence test generator",
            dataset="test",
            observed_at=when,
            available_at=when,
            retrieved_at=when,
            availability_basis="synthetic",
            original_timestamp=when.isoformat(),
            original_timezone="UTC",
            unit="currency_per_troy_ounce",
            currency="USD",
            license_status="OPEN_PUBLIC",
            license_id="synthetic-project-fixtures",
            confidence=1,
            raw_sha256=raw,
            raw_record_id=str(index),
            synthetic=True,
        )
        p.update(p_changes)
        fields = dict(
            provenance=Provenance(**p),
            instrument="XAUUSD",
            venue="SYNTHETIC",
            timeframe="1d",
            price_type="spot",
            open=close,
            high=close + 1,
            low=close - 1,
            close=close,
        )
        fields.update(changes)
        return PriceBar(**fields)

    return factory
