import io
import json
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gold_intelligence.histdata_review import review_archive

STATUS = b"File: DAT_ASCII_XAUUSD_M1_202609.csv Status Report"
ROW = "20260901 000000;10;12;9;11;0\n"


def content(rows=ROW, extra=False):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("DAT_ASCII_XAUUSD_M1_202609.csv", rows)
        archive.writestr("DAT_ASCII_XAUUSD_M1_202609.txt", STATUS)
        if extra:
            archive.writestr("../unexpected", "x")
    return stream.getvalue()


def review(rows=ROW):
    return review_archive(content(rows), STATUS, "202609", datetime(2026, 10, 8, tzinfo=UTC))


def test_fixed_offset_in_summer_and_source_month_boundaries():
    result = review(ROW + ROW.replace("20260901 000000", "20260930 235900"))
    assert result["first_utc"] == "2026-09-01T05:00:00+00:00"
    assert result["last_utc"] == "2026-10-01T04:59:00+00:00"
    assert not result["daily_backtest_ready"]
    assert not result["gaps"][0]["market_closure_verified"]


@pytest.mark.parametrize(
    "rows",
    [
        ROW + ROW,
        ROW.replace("20260901", "20261001"),
        ROW.replace("000000", "000001"),
        ROW.replace(";12;", ";nan;"),
        ROW.replace(";0\n", ";1\n"),
        "",
    ],
)
def test_reject_invalid_minutes(rows):
    with pytest.raises(ValueError):
        review(rows)


def test_status_binding_and_archive_members():
    for archive, status in ((content(), STATUS + b" changed"), (content(extra=True), STATUS)):
        with pytest.raises(ValueError):
            review_archive(archive, status, "202609", datetime(2026, 10, 8, tzinfo=UTC))


def test_current_month_not_accepted():
    with pytest.raises(ValueError):
        review_archive(content(), STATUS, "202609", datetime(2026, 9, 30, tzinfo=UTC))


def test_duplicate_does_not_hide_later_invalid_price():
    with pytest.raises(ValueError, match="invalid OHLC"):
        review(ROW + ROW + ROW.replace(";12;", ";nan;"))


def test_cli_rejection_receipt_preserves_conflicting_raw_rows(tmp_path):
    archive, status, output = (
        tmp_path / name for name in ("sample.zip", "status.txt", "audit.json")
    )
    archive.write_bytes(content(ROW + ROW.replace(";11;", ";10;")))
    status.write_bytes(STATUS)
    command = [
        sys.executable,
        str(Path(__file__).parents[1] / "scripts/inspect_histdata_export.py"),
        "--archive",
        str(archive),
        "--status",
        str(status),
        "--month",
        "202609",
        "--retrieved-at",
        "2026-10-08T15:00:00+00:00",
        "--output",
        str(output),
    ]
    subprocess.run(command, check=True, capture_output=True)
    result = json.loads(output.read_text())
    assert result["validation_status"] == "rejected"
    assert result["duplicate_extra_rows"] == 1
    assert result["conflicting_minutes"] == 1
    assert result["duplicate_groups"][0]["raw_rows"] == [1, 2]
    original = output.read_bytes()
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert output.read_bytes() == original
