"""Entirely invented CFTC-shaped counts. No provider history is redistributed."""

import importlib.util
import json
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from jsonschema import validate

from gold_intelligence import cftc
from gold_intelligence.acquisition import acquire, list_runs
from gold_intelligence.cli import main
from gold_intelligence.models import Positioning
from gold_intelligence.positioning import positioning_context, write_positioning
from gold_intelligence.storage import record_id

START = date(2024, 1, 2)
END = date(2024, 1, 30)
NOW = datetime(2024, 2, 1, 18, tzinfo=UTC)


def row(day=START, shift=0):
    # OI 100: reportable long 80 and short 90, nonreportable 20 and 10.
    values = {
        "open_interest_all": 100,
        "tot_rept_positions_long_all": 80,
        "tot_rept_positions_short": 90,
        "prod_merc_positions_long": 10,
        "prod_merc_positions_short": 35,
        "swap_positions_long_all": 5,
        "swap__positions_short_all": 20,
        "swap__positions_spread_all": 10,
        "m_money_positions_long_all": 25 + shift,
        "m_money_positions_short_all": 5,
        "m_money_positions_spread": 5,
        "other_rept_positions_long": 20 - shift,
        "other_rept_positions_short": 10,
        "other_rept_positions_spread": 5,
        "nonrept_positions_long_all": 20,
        "nonrept_positions_short_all": 10,
    }
    return {
        **cftc.TEXT_FIELDS,
        cftc.DATE_FIELD: f"{day}T00:00:00.000",
        **{k: str(v) for k, v in values.items()},
    }


def metadata():
    return {
        "id": cftc.RESOURCE,
        "name": "Disaggregated - Futures Only",
        "viewType": "tabular",
        "rowsUpdatedAt": 100,
        "viewLastModified": 90,
        "columns": [{"fieldName": k, "dataTypeName": v} for k, v in cftc.FIELD_TYPES.items()],
    }


def provider(rows=None, mutate=None):
    rows = [row()] if rows is None else rows
    calls = []

    def fetch(url):
        calls.append(url)
        if url == cftc.METADATA:
            kind, data = "metadata", metadata()
        else:
            params = parse_qs(urlparse(url).query)
            assert "088691" in params["$where"][0]
            if params["$select"] == ["count(*)"]:
                kind, data = "count", [{"count": str(len(rows))}]
            else:
                assert params["$order"] == [f"{cftc.DATE_FIELD} ASC"]
                assert set(params["$select"][0].split(",")) == set(cftc.FIELD_TYPES)
                offset = int(params["$offset"][0])
                kind, data = "page", deepcopy(rows[offset : offset + cftc.PAGE_SIZE])
        if mutate:
            data = mutate(kind, data, calls)
        return json.dumps(data).encode()

    return fetch, calls


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz or UTC)

    monkeypatch.setattr(cftc, "datetime", FixedClock)


def ingest(store, registry, rows=None, mutate=None, end=END):
    fetch, calls = provider(rows, mutate)
    inserted = cftc.ingest_cftc_gold(store, registry.get("cftc_disaggregated"), START, end, fetch)
    return inserted, calls


def test_full_capture_math_cutoff_and_null_spreads(store, registry):
    rows = [row(), row(START + timedelta(days=7), shift=5)]
    inserted, calls = ingest(store, registry, rows)
    assert inserted == 10 and len(calls) == 5
    assert all("api_key" not in url and "token" not in url for url in calls)
    assert positioning_context(store, registry, NOW - timedelta(microseconds=1)).status == "no_data"
    context = positioning_context(store, registry, NOW)
    assert context.status == "stale" and context.latest_observation_age_days == 23
    assert context.eligible_record_versions == 10 and context.eligible_captures == 1
    latest = context.weeks[-1]
    assert latest.known_at == NOW and latest.open_interest_change_7d == 0
    assert sum(g.net for g in latest.categories) == 0
    mm = next(g for g in latest.categories if g.category == "managed_money")
    assert (mm.net, mm.net_percent_open_interest, mm.net_change_7d) == (25, 25.0, 5)
    assert latest.categories[0].spreading is None
    assert latest.categories[-1].spreading is None
    assert all(
        r.provenance.availability_basis == "retrieval_time" for r in store.read("positioning")
    )
    assert positioning_context(store, registry, NOW).fingerprint == context.fingerprint
    assert not context.historical_release_ready and not context.daily_backtest_ready
    assert ingest(store, registry, rows)[0] == 0
    validate(
        context.model_dump(mode="json"),
        json.loads(Path("schemas/positioning_context.schema.json").read_text()),
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("cftc_contract_market_code", "088695"),
        ("futonly_or_combined", "Combined"),
        ("contract_units", "(CONTRACTS OF 10 TROY OUNCES)"),
        ("commodity_name", "SILVER"),
        ("open_interest_all", None),
        ("open_interest_all", True),
        ("open_interest_all", 100),
        ("open_interest_all", "100.0"),
        ("open_interest_all", "-100"),
        ("open_interest_all", "۱۰۰"),
        ("open_interest_all", "NaN"),
        ("tot_rept_positions_short", "89"),
        ("tot_rept_positions_long_all", "81"),
        ("nonrept_positions_short_all", "9"),
        ("swap__positions_spread_all", "11"),
        (cftc.DATE_FIELD, "2024-01-02T01:00:00.000"),
    ],
)
def test_incompatible_or_invalid_rows_are_atomic(store, registry, field, value):
    bad = row(START + timedelta(days=7))
    bad[field] = value
    with pytest.raises(ValueError):
        ingest(store, registry, [row(), bad])
    assert store.read("positioning") == []


@pytest.mark.parametrize("change", ["name", "type", "missing", "duplicate", "revision"])
def test_metadata_review_gates(store, registry, change):
    def mutate(kind, data, calls):
        if kind == "metadata":
            if change == "name":
                data["name"] = "Disaggregated - Combined"
            elif change == "type":
                data["columns"][-1]["dataTypeName"] = "text"
            elif change == "missing":
                data["columns"].pop()
            elif change == "duplicate":
                data["columns"].append(data["columns"][0])
            elif len(calls) > 1:
                data["rowsUpdatedAt"] += 1
        return data

    with pytest.raises(ValueError):
        ingest(store, registry, mutate=mutate)
    assert store.read("positioning") == []


@pytest.mark.parametrize("case", ["duplicate", "unordered", "outside", "missing", "extra"])
def test_row_grain_and_boundaries(store, registry, case):
    rows = [row(), row(START + timedelta(days=7))]
    if case == "duplicate":
        rows[1] = rows[0]
    elif case == "unordered":
        rows.reverse()
    elif case == "outside":
        rows[0] = row(START - timedelta(days=1))
    elif case == "missing":
        rows[0].pop("m_money_positions_long_all")
    else:
        rows[0]["unexpected"] = "1"
    with pytest.raises(ValueError):
        ingest(store, registry, rows)
    assert store.read("positioning") == []


@pytest.mark.parametrize(
    "case", ["success", "truncated", "duplicate_boundary", "count_change", "failure"]
)
def test_bounded_pagination_and_atomicity(store, registry, case):
    rows = [row(START + timedelta(days=i)) for i in range(1001)]

    def mutate(kind, data, calls):
        if kind == "count" and len(calls) > 2 and case == "count_change":
            return [{"count": "1000"}]
        if kind == "page" and len(data) == 1:
            if case == "truncated":
                return []
            if case == "duplicate_boundary":
                return [rows[999]]
            if case == "failure":
                raise ValueError("mock request failure")
        return data

    # Move labels into the past while testing >1000 rows.
    rows = [row(date(2008, 1, 1) + timedelta(days=i)) for i in range(1001)]
    fetch, _ = provider(rows, mutate)
    if case == "success":
        assert (
            cftc.ingest_cftc_gold(
                store, registry.get("cftc_disaggregated"), date(2008, 1, 1), END, fetch
            )
            == 5005
        )
    else:
        with pytest.raises(ValueError):
            cftc.ingest_cftc_gold(
                store, registry.get("cftc_disaggregated"), date(2008, 1, 1), END, fetch
            )
        assert store.read("positioning") == []


def test_missing_week_zero_oi_and_non_tuesday_labels(store, registry):
    zero = row(START + timedelta(days=15))
    zero.update(dict.fromkeys(cftc.NUMBER_FIELDS, "0"))
    ingest(store, registry, [row(), zero])
    report = positioning_context(store, registry, NOW)
    assert report.irregular_intervals == ((START, START + timedelta(days=15)),)
    assert report.non_tuesday_labels == (START + timedelta(days=15),)
    assert all(
        g.net_change_7d is None and g.net_percent_open_interest is None
        for g in report.weeks[-1].categories
    )
    assert report.weeks[-1].open_interest_change_7d is None


def test_revisions_selected_as_whole_capture(store, registry, monkeypatch):
    ingest(store, registry)
    monkeypatch.setattr(__import__(__name__), "NOW", NOW + timedelta(days=1))
    ingest(store, registry, [row(shift=2)])
    old = positioning_context(store, registry, NOW - timedelta(days=1))
    new = positioning_context(store, registry, NOW)
    assert old.weeks[0].categories[2].net == 20
    assert new.weeks[0].categories[2].net == 22
    assert new.superseded_record_versions == 5
    assert old.fingerprint != new.fingerprint


def test_same_time_captures_are_ambiguous(store, registry):
    ingest(store, registry)
    ingest(store, registry, [row(shift=1)])
    with pytest.raises(ValueError, match="conflicting"):
        positioning_context(store, registry, NOW)


@pytest.mark.parametrize(
    "case",
    ["missing_category", "missing_date", "altered_count", "changed_clock", "raw_page", "metadata"],
)
def test_report_rechecks_full_capture_not_only_latest_group(store, registry, case):
    ingest(store, registry, [row(), row(START + timedelta(days=7))])
    records = store.read("positioning")
    target = records[0]
    if case in {"missing_category", "missing_date"}:
        ids = (
            [record_id(target)]
            if case == "missing_category"
            else [
                record_id(r)
                for r in records
                if r.provenance.observed_at == target.provenance.observed_at
            ]
        )
        with store.db:
            store.db.executemany("DELETE FROM records WHERE id=?", [(i,) for i in ids])
    elif case in {"altered_count", "changed_clock"}:
        data = target.model_dump(mode="json")
        if case == "altered_count":
            data["long"] += 1
        else:
            data["provenance"]["available_at"] = "2024-01-30T18:00:00Z"
            data["provenance"]["availability_basis"] = "verified_release"
        changed = Positioning.model_validate(data)
        with store.db:
            store.db.execute("DELETE FROM records WHERE id=?", (record_id(target),))
        store.put([changed])
    else:
        capture = cftc.CotCapture.model_validate_json(
            cftc.raw_json(store, target.provenance.raw_sha256)
        )
        digest = capture.pages[0].sha256 if case == "raw_page" else capture.metadata_before
        (store.root / "raw" / digest).write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        positioning_context(store, registry, NOW)


@pytest.mark.parametrize("age", [0, 366, True])
def test_invalid_age_policy(store, registry, age):
    with pytest.raises(ValueError):
        positioning_context(store, registry, NOW, age)


def test_manifests_and_cli_local_artifacts(store, registry, monkeypatch, capsys, tmp_path):
    result = acquire(
        store,
        "fetch-cftc-gold",
        {"start": str(START), "end": str(END)},
        lambda: ingest(store, registry)[0],
    )
    assert result["inserted"] == 5
    runs = list_runs(store.root)
    assert runs[0]["raw_blobs"] == 4 and runs[0]["status"] == "succeeded"
    args = [
        "--store",
        str(store.root),
        "positioning-context",
        "--as-of",
        NOW.isoformat(),
        "--output-dir",
        str(tmp_path / "reports"),
    ]
    assert main(args) == 3
    result = json.loads(capsys.readouterr().out)
    path = Path(result["report"])
    assert path.is_file() and "زمان انتشار تاریخی نامعلوم" in path.read_text(encoding="utf-8")
    assert path.with_name("positioning.json").is_file()
    assert main([*args, "--max-age-days", "31"]) == 0
    assert Path(json.loads(capsys.readouterr().out)["report"]) != path


def test_failure_manifest_and_cli_safe_fetch(store, registry, monkeypatch, capsys):
    def execute(store, source, start, end):
        return ingest(store, registry, [row(), row()])[0]

    monkeypatch.setattr("gold_intelligence.cli.ingest_cftc_gold", execute)
    assert main(["--store", str(store.root), "fetch-cftc-gold", "--end", str(END)]) == 2
    assert "duplicate" in capsys.readouterr().err
    assert list_runs(store.root)[0]["status"] == "failed"
    assert store.read("positioning") == []


def test_output_failure_leaves_no_partial_report(store, registry, tmp_path, monkeypatch):
    report = positioning_context(store, registry, NOW)

    def fail(_report):
        raise OSError("simulated output failure")

    monkeypatch.setattr("gold_intelligence.positioning.render_positioning", fail)
    with pytest.raises(OSError):
        write_positioning(report, tmp_path / "reports")
    assert not list((tmp_path / "reports").iterdir())


@pytest.mark.parametrize("count", ["0", "10001", "-1", None])
def test_empty_unbounded_or_invalid_counts(count, store, registry):
    def mutate(kind, data, calls):
        return [{"count": count}] if kind == "count" else data

    with pytest.raises(ValueError):
        ingest(store, registry, mutate=mutate)
    assert store.read("positioning") == []


@pytest.mark.parametrize(
    "change", [None, "net_change_7d", "net_percent_open_interest", "missing_week"]
)
def test_independent_arithmetic_inspection(store, registry, tmp_path, change):
    spec = importlib.util.spec_from_file_location("inspect_cot", "scripts/inspect_positioning.py")
    inspector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inspector)
    ingest(store, registry, [row(), row(START + timedelta(days=7), shift=5)])
    report = positioning_context(store, registry, NOW)
    data = report.model_dump(mode="json")
    if change == "missing_week":
        data["weeks"].pop(0)
    elif change:
        data["weeks"][1]["categories"][2][change] += 1
    path = tmp_path / "report.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    if change:
        with pytest.raises(ValueError):
            inspector.validate(store.root, path)
    else:
        result = inspector.validate(store.root, path)
        assert result["weeks"] == 2 and result["selected_records"] == 10
