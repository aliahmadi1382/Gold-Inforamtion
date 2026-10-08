import hashlib
import json
import runpy
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from test_alpha_vantage import parse
from test_macro import observation
from test_research_report import settings as settings

from gold_intelligence import cli
from gold_intelligence.acquisition import acquire
from gold_intelligence.local_ui import Workspace, handler_for
from gold_intelligence.project_roadmap import ProjectRoadmap, load_project_roadmap
from gold_intelligence.report_comparison import compare_reports
from gold_intelligence.research_report import build_research_report, write_research_report

ROADMAP = Path("config/project_roadmap.json")


def workspace(store, tmp_path, reports=None):
    return Workspace(store.root, reports or tmp_path / "reports", ROADMAP)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_missing_store_does_not_initialize(tmp_path):
    with pytest.raises(ValueError, match="existing"):
        Workspace(tmp_path / "typo", tmp_path / "reports", ROADMAP)
    assert not (tmp_path / "typo").exists()


def test_snapshot_does_not_write_database_or_raw_and_hides_credentials(store, registry, tmp_path):
    store.put(parse(store, registry))
    (store.root / "credentials.env").write_text("SECRET")
    database = store.root / "market.sqlite3"
    before = digest(database)
    ui = workspace(store, tmp_path)
    assert digest(database) == before and ui.summary["records"] == 2
    assert ui.summary["raw_hash_audit"] == "not_run_by_ui"
    assert "SECRET" not in json.dumps(ui.summary)
    assert ui.summary["series"][0]["observations"] == 2


def test_revision_selection_keeps_latest_null_and_exact_source(store, registry, tmp_path):
    first = observation(store, registry, value=10)
    later = observation(store, registry, value=None, available=3, retrieved=3)
    alternate = observation(store, registry, value=50, unit="different_unit")
    store.put([first, later, alternate])
    ui = workspace(store, tmp_path)
    assert ui.summary["records"] == 3 and len(ui.series) == 2
    percent = next(s for s in ui.series.values() if s["identity"]["unit"] == "percent")
    assert percent["versions"] == 2
    assert percent["points"][0]["value"] is None
    assert percent["points"][0]["raw_sha256"] == later.provenance.raw_sha256


def test_vintages_and_dimensions_are_not_merged(store, registry, tmp_path):
    from datetime import date

    store.put(
        [
            observation(store, registry),
            observation(store, registry, vintage=date(2024, 1, 2)),
            observation(store, registry, dimensions={"method": "alternate"}),
        ]
    )
    assert len(workspace(store, tmp_path).series) == 3


def test_future_availability_is_not_plotted(store, registry, tmp_path):
    row = observation(store, registry)
    future = datetime.now(UTC) + timedelta(days=10)
    row = row.model_copy(
        update={
            "provenance": row.provenance.model_copy(
                update={"available_at": future, "retrieved_at": future}
            )
        }
    )
    store.put([row])
    ui = workspace(store, tmp_path)
    assert ui.summary["records"] == 1 and not ui.series


def test_date_filter_has_exact_export_population(store, registry, tmp_path):
    store.put(parse(store, registry))
    ui = workspace(store, tmp_path)
    key = next(iter(ui.series))
    points = ui.points(key, "2024-01-05", "2024-01-05")["points"]
    assert len(points) == 1 and points[0]["date"] == "2024-01-05"
    assert ui.points(key, "2024-01-06", "2024-01-06")["points"] == []
    with pytest.raises(ValueError):
        ui.points(key, "2024-02-01", "2024-01-01")
    with pytest.raises(ValueError):
        ui.points(key, "invalid")
    with pytest.raises(KeyError):
        ui.points("unknown")


def test_corrupt_normalized_record_and_busy_writer_fail_closed(store, registry, tmp_path):
    with store.writer_lock(), pytest.raises(ValueError, match="another writer"):
        workspace(store, tmp_path)
    store.put([observation(store, registry)])
    store.db.execute("UPDATE records SET payload = '{}' ")
    store.db.commit()
    with pytest.raises(ValueError):
        workspace(store, tmp_path)


def test_failed_run_does_not_export_exception_or_parameters(store, tmp_path):
    def fail():
        raise ValueError("SECRET")

    with pytest.raises(ValueError):
        acquire(store, "import-records", {"input_filename": "SECRET"}, fail)
    ui = workspace(store, tmp_path)
    assert ui.summary["runs"][0]["status"] == "failed"
    assert "SECRET" not in json.dumps(ui.summary)


def test_verified_research_and_comparison_and_corrupt_bundle_exclusion(
    store, registry, settings, tmp_path
):
    reports = tmp_path / "reports"
    report = build_research_report(store, registry, settings, datetime(2024, 1, 10, tzinfo=UTC))
    first = write_research_report(report, reports)
    second = write_research_report(report, reports)
    compare_reports(first, second, reports / "comparisons")
    ui = workspace(store, tmp_path, reports)
    assert len(ui.reports) == 2 and len(ui.comparisons) == 1
    derived = next(iter(ui.reports.values()))["synthesis"]
    assert derived["report_fingerprint"] == report.fingerprint
    assert derived["market_direction"] == "not_inferred"
    assert all("synthesis" not in row for row in ui.summary["reports"])
    stability = next(iter(ui.reports.values()))["monthly_stability"]
    assert stability["report_fingerprint"] == report.fingerprint
    assert stability["monthly_fingerprint"] == report.monthly.fingerprint
    assert not stability["daily_backtest_ready"]
    assert all("monthly_stability" not in row for row in ui.summary["reports"])
    assert next(iter(ui.comparisons.values()))["status"] == "unchanged"
    (first / "research-report.fa.md").write_text("tampered")
    ui = workspace(store, tmp_path, reports)
    assert len(ui.reports) == 1 and ui.report_errors == 1


@contextmanager
def running(ui):
    with ThreadingHTTPServer(("127.0.0.1", 0), handler_for(ui, 0)) as server:
        server.RequestHandlerClass = handler_for(ui, server.server_port)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            thread.join(timeout=2)


@pytest.mark.parametrize(
    "endpoint", ["/", "/app.js", "/markdown.js", "/style.css", "/api/summary", "/api/status"]
)
def test_http_static_and_snapshot_headers(store, tmp_path, endpoint):
    with running(workspace(store, tmp_path)) as base, urlopen(base + endpoint) as response:
        assert response.status == 200 and response.headers["Cache-Control"] == "no-store"
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.read()


@pytest.mark.parametrize(
    "endpoint,code",
    [
        ("/api/series?id=unknown", 400),
        ("/api/report?id=unknown", 400),
        ("/api/comparison?id=unknown", 400),
        ("/api/series", 400),
        ("/credentials.env", 404),
        ("/../local/credentials.env", 404),
        ("/api/file?path=local/credentials.env", 404),
    ],
)
def test_no_arbitrary_file_routes(store, tmp_path, endpoint, code):
    with running(workspace(store, tmp_path)) as base, pytest.raises(HTTPError) as error:
        urlopen(base + endpoint)
    assert error.value.code == code


@pytest.mark.parametrize(
    "headers", [{"Host": "attacker.test"}, {"Origin": "https://attacker.test"}]
)
def test_cross_origin_and_rebinding_hosts_rejected(store, tmp_path, headers):
    with running(workspace(store, tmp_path)) as base, pytest.raises(HTTPError) as error:
        urlopen(Request(base + "/api/summary", headers=headers))
    assert error.value.code == 403


def test_post_cannot_refresh_or_mutate(store, tmp_path):
    with running(workspace(store, tmp_path)) as base, pytest.raises(HTTPError) as error:
        urlopen(Request(base + "/api/refresh", data=b"{}", method="POST"))
    assert error.value.code == 501


def test_cli_does_not_load_registry_or_create_store(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_registry", lambda *args: pytest.fail("registry"))
    args = cli.parser().parse_args(["--store", str(tmp_path / "missing"), "local-ui"])
    with pytest.raises(ValueError, match="existing"):
        cli.run(args)


@pytest.mark.parametrize("change", ["duplicate", "completed_with_remaining", "wrong_active"])
def test_roadmap_rejects_false_completion_and_ambiguous_status(change):
    data = json.loads(ROADMAP.read_text(encoding="utf-8"))
    if change == "duplicate":
        data["phases"][1]["id"] = "0"
    elif change == "completed_with_remaining":
        data["phases"][3]["status"] = "completed"
    else:
        data["current_phase"] = "7"
    with pytest.raises(ValueError):
        ProjectRoadmap.model_validate(data)


def test_phase_document_matches_single_source():
    render = runpy.run_path("scripts/update_project_phases.py")["render"]
    assert Path("docs/phases.fa.md").read_text(encoding="utf-8") == render(
        load_project_roadmap(ROADMAP)
    )
