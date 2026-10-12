import json
from datetime import UTC, datetime, timedelta

import pytest

from gold_intelligence.forward_dataset import build_forward_dataset
from gold_intelligence.goldapi_capture import capture_goldapi

TIME = datetime(2026, 10, 12, tzinfo=UTC)


def capture(root, received, source, price=2000):
    raw = json.dumps(
        dict(
            timestamp=int(source.timestamp()),
            datetime=source.isoformat(),
            metal="XAU",
            currency="USD",
            unit="troy_ounce",
            exchange="FOREXCOM",
            symbol="FOREXCOM:XAUUSD",
            price=price,
            bid=price - 1,
            ask=price + 1,
        )
    ).encode()
    clocks = iter([received, received + timedelta(seconds=1)])
    return capture_goldapi(root, "fixture", lambda _: (raw, 200), lambda: next(clocks))


def test_real_contract_has_receipt_gaps_without_inventing_coverage(tmp_path):
    capture(tmp_path, TIME, TIME)
    capture(tmp_path, TIME + timedelta(seconds=600), TIME + timedelta(seconds=300))
    r = build_forward_dataset(tmp_path)
    assert r["observation_count"] == r["unique_source_times"] == 2
    assert r["receipt_gap_seconds"] == [600]
    assert r["age_seconds_max"] == 301
    assert r["missing_interval_count"] is None
    assert not r["synthetic"] and not r["trading_eligible"]


@pytest.mark.parametrize("file", ["raw.json", "receipt.json", "quote-review.json"])
def test_tampered_evidence_prevents_entire_dataset(tmp_path, file):
    folder = capture(tmp_path, TIME, TIME)
    data = json.loads((folder / file).read_text())
    if file == "raw.json":
        data["bid"] = 1998
    elif file == "receipt.json":
        data["raw_sha256"] = "0" * 64
    else:
        data["price"] = 2001
    (folder / file).write_text(json.dumps(data))
    with pytest.raises(ValueError, match="evidence invalid"):
        build_forward_dataset(tmp_path)


def test_duplicate_source_time_and_conflict_are_visible(tmp_path):
    capture(tmp_path, TIME, TIME)
    capture(tmp_path, TIME + timedelta(seconds=10), TIME, 2002)
    r = build_forward_dataset(tmp_path)
    assert r["duplicate_source_observations"] == 1
    assert r["conflicting_source_time_groups"] == 1
    assert r["nonadvancing_source_time_pairs"] == 1


def test_incomplete_capture_is_not_silently_skipped(tmp_path):
    capture(tmp_path, TIME, TIME)
    (tmp_path / "failed").mkdir()
    with pytest.raises(ValueError):
        build_forward_dataset(tmp_path)
