"""Loopback-only, read-only research workspace over reviewed local evidence."""

import hashlib
import json
import os
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import UTC, date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from . import __version__
from .acquisition import AcquisitionRun
from .daily_readiness import build_daily_readiness
from .evidence_synthesis import build_synthesis
from .monthly_stability import monthly_stability
from .operations_health import build_operations_health
from .project_roadmap import load_project_roadmap
from .report_comparison import verify_comparison
from .research_report import load_verified_report
from .storage import canonical, decode_record
from .store_lock import store_lock


def series_identity(record):
    p = record.provenance
    identity = dict(
        kind=record.kind,
        source=p.source_id,
        dataset=p.dataset,
        unit=p.unit,
        currency=p.currency,
        synthetic=p.synthetic,
    )
    if record.kind == "price_close":
        identity.update(
            instrument=record.instrument,
            venue=record.venue,
            timeframe=record.timeframe,
            unit_basis=record.unit_basis,
            session_timezone=record.session_timezone,
        )
    elif record.kind == "observation":
        identity.update(
            series=record.series_id,
            dimensions=record.dimensions,
            vintage=str(record.vintage_date) if record.vintage_date else None,
        )
    elif record.kind == "positioning":
        identity.update(
            market=record.market_code, report_type=record.report_type, category=record.category
        )
    else:
        return None
    return identity


def safe_bundle(directory, root):
    if not directory.resolve().is_relative_to(root) or directory.is_symlink():
        raise ValueError("report directory escapes the configured report root")
    for child in directory.rglob("*"):
        if child.is_symlink():
            raise ValueError("linked report artifacts are not served")
    return load_verified_report(directory)


class Workspace:
    def __init__(self, store_root, report_root, roadmap_path):
        self.root = Path(store_root).resolve()
        self.report_root = Path(report_root).resolve()
        database = self.root / "market.sqlite3"
        if not database.is_file() or database.is_symlink():
            raise ValueError("existing regular store database is required")
        self.series = {}
        self.reports = {}
        self.comparisons = {}
        self.report_errors = 0
        self.roadmap = load_project_roadmap(roadmap_path).model_dump(mode="json")
        generated = datetime.now(UTC)
        counts, sources, raw = Counter(), {}, {}
        with (
            store_lock(self.root),
            closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db,
        ):
            db.execute("BEGIN")
            for identifier, kind, payload in db.execute(
                "SELECT id, kind, payload FROM records ORDER BY id"
            ):
                record = decode_record(identifier, kind, payload)
                p = record.provenance
                counts[kind] += 1
                source = sources.setdefault(
                    p.source_id,
                    dict(
                        id=p.source_id,
                        provider=p.provider,
                        versions=0,
                        kinds=Counter(),
                        last_retrieved=None,
                        latest_observed=None,
                    ),
                )
                source["versions"] += 1
                source["kinds"][kind] += 1
                for key, value in (
                    ("last_retrieved", p.retrieved_at),
                    ("latest_observed", p.observed_at),
                ):
                    encoded = value.astimezone(UTC).isoformat()
                    source[key] = max(source[key] or encoded, encoded)
                identity = series_identity(record)
                if identity is None or p.available_at > generated or p.retrieved_at > generated:
                    continue
                key = hashlib.sha256(canonical(identity).encode()).hexdigest()[:24]
                series = self.series.setdefault(
                    key,
                    dict(
                        id=key, identity=identity, versions=0, points={}, availability_basis=set()
                    ),
                )
                series["versions"] += 1
                series["availability_basis"].add(p.availability_basis)
                stamp = p.observed_at.astimezone(UTC).isoformat()
                revision = (p.available_at, p.retrieved_at, identifier)
                old = series["points"].get(stamp)
                if old is not None and old[0] >= revision:
                    continue
                value = (
                    record.close
                    if kind == "price_close"
                    else record.value
                    if kind == "observation"
                    else record.net
                )
                point = dict(
                    date=stamp[:10],
                    observed_at=stamp,
                    value=value,
                    record_id=identifier,
                    raw_sha256=p.raw_sha256,
                    available_at=p.available_at.isoformat(),
                    retrieved_at=p.retrieved_at.isoformat(),
                    availability_basis=p.availability_basis,
                )
                if kind == "positioning":
                    point.update(
                        long=record.long, short=record.short, open_interest=record.open_interest
                    )
                series["points"][stamp] = (revision, point)
            runs = []
            for path in sorted((self.root / "runs").glob("*.json")):
                if path.is_symlink():
                    raise ValueError("linked run manifest is unsupported")
                run = AcquisitionRun.model_validate_json(path.read_bytes())
                if path.stem != run.run_id:
                    raise ValueError("run filename differs from its ID")
                from .transport_evidence import load_transport

                transport = load_transport(self.root, run.run_id)
                runs.append(
                    dict(
                        id=run.run_id,
                        operation=run.operation,
                        status=run.status,
                        started_at=run.started_at.isoformat(),
                        finished_at=run.finished_at.isoformat() if run.finished_at else None,
                        inserted=run.inserted_records,
                        records=len(run.record_ids),
                        raw=len(run.raw_sha256),
                        transport=transport.model_dump(mode="json") if transport else None,
                    )
                )
            for path in (self.root / "raw").iterdir():
                if path.is_file() and not path.is_symlink() and len(path.name) == 64:
                    raw[path.name] = path.stat().st_size
        inventory = []
        for series in self.series.values():
            series["points"] = [item[1] for _, item in sorted(series["points"].items())]
            series["availability_basis"] = sorted(series["availability_basis"])
            points = series["points"]
            inventory.append(
                {key: value for key, value in series.items() if key != "points"}
                | dict(
                    observations=len(points),
                    missing_values=sum(p["value"] is None for p in points),
                    start=points[0]["date"],
                    end=points[-1]["date"],
                    latest_value=points[-1]["value"],
                )
            )
        if self.report_root.exists():
            for path in sorted(self.report_root.rglob("research-report.json")):
                try:
                    report, manifest, content = safe_bundle(path.parent, self.report_root)
                    prose = (path.parent / "research-report.fa.md").read_bytes()
                    expected = next(
                        item for item in manifest.files if item.path == "research-report.fa.md"
                    )
                    if (
                        len(prose) != expected.bytes
                        or hashlib.sha256(prose).hexdigest() != expected.sha256
                    ):
                        raise ValueError("report prose changed during loading")
                    key = hashlib.sha256(
                        str(path.parent.relative_to(self.report_root)).encode()
                    ).hexdigest()[:24]
                    # Only serve verified research JSON; no arbitrary local-file endpoint.
                    from .runtime_evidence import load_computation, load_runtime

                    runtime = load_runtime(path.parent, report, content)
                    computation = load_computation(path.parent, report, content)
                    self.reports[key] = dict(
                        id=key,
                        report=json.loads(content),
                        text=prose.decode("utf-8"),
                        label=path.parent.name,
                        generated_at=report.generated_at.isoformat(),
                        as_of=report.as_of.isoformat(),
                        fingerprint=report.fingerprint,
                        status=report.status,
                        software_version=report.software_version,
                        runtime=runtime.model_dump(mode="json") if runtime else None,
                        computation=computation.model_dump(mode="json") if computation else None,
                        daily_readiness=build_daily_readiness(content).model_dump(mode="json"),
                        monthly_stability=monthly_stability(report),
                        synthesis=build_synthesis(content, generated_at=generated).model_dump(
                            mode="json"
                        ),
                    )
                except (ValueError, OSError, KeyError):
                    self.report_errors += 1
        self.refresh = None
        if self.report_root.exists():
            for path in sorted(self.report_root.rglob("comparison.json")):
                try:
                    directory = path.parent
                    if not (directory / "manifest.json").is_file():
                        continue
                    if directory.is_symlink() or not directory.resolve().is_relative_to(
                        self.report_root
                    ):
                        continue
                    if any(child.is_symlink() for child in directory.rglob("*")):
                        continue
                    verify_comparison(directory)
                    payload = json.loads(path.read_bytes())
                    key = hashlib.sha256(
                        str(directory.relative_to(self.report_root)).encode()
                    ).hexdigest()[:24]
                    self.comparisons[key] = dict(
                        id=key,
                        status=payload["status"],
                        generated_at=payload["generated_at"],
                        before=payload["before"]["as_of"],
                        after=payload["after"]["as_of"],
                        changes=len(payload["changes"]),
                        text=(directory / "comparison.fa.md").read_text(encoding="utf-8"),
                        comparison=payload,
                    )
                except (ValueError, OSError, KeyError):
                    self.report_errors += 1
        self.health = None
        refresh_candidates = []
        if self.report_root.exists():
            for path in self.report_root.rglob("refresh-run.json"):
                if path.is_symlink() or not path.resolve().is_relative_to(self.report_root):
                    continue
                try:
                    from .refresh import RefreshRun

                    candidate = RefreshRun.model_validate_json(path.read_bytes())
                    ids = {run["id"] for run in runs}
                    if all(
                        step.run_id in ids
                        for step in candidate.steps
                        if step.acquisition_status in {"running", "succeeded", "failed"}
                    ):
                        refresh_candidates.append((candidate.started_at, candidate.run_id, path))
                except (ValueError, OSError):
                    continue
        if refresh_candidates:
            self.refresh = max(refresh_candidates)[2]
        try:
            self.health = build_operations_health(
                self.root, self.refresh, allow_relocated_refresh=True
            ).model_dump(mode="json")
        except (ValueError, OSError):
            self.health = dict(
                status="unavailable", runs=[], reason="در زمان بارگذاری شواهد سلامت قابل تأیید نبود"
            )
        self.summary = dict(
            version=__version__,
            workspace_id=hashlib.sha256(str(self.root).encode()).hexdigest(),
            generated_at=generated.isoformat(),
            records=sum(counts.values()),
            kinds=dict(counts),
            sources=sorted(sources.values(), key=lambda x: x["id"]),
            raw_blobs=len(raw),
            raw_bytes=sum(raw.values()),
            runs=sorted(runs, key=lambda x: (x["started_at"], x["id"]), reverse=True),
            run_states=dict(Counter(run["status"] for run in runs)),
            series=sorted(inventory, key=lambda x: (x["identity"]["source"], x["id"])),
            reports=sorted(
                [
                    {
                        key: value
                        for key, value in report.items()
                        if key
                        not in {
                            "report",
                            "text",
                            "synthesis",
                            "daily_readiness",
                            "monthly_stability",
                        }
                    }
                    for report in self.reports.values()
                ],
                key=lambda x: (x["as_of"], x["generated_at"], x["id"]),
                reverse=True,
            ),
            invalid_report_bundles=self.report_errors,
            comparisons=sorted(
                [
                    {key: value for key, value in item.items() if key not in {"text", "comparison"}}
                    for item in self.comparisons.values()
                ],
                key=lambda x: x["generated_at"],
                reverse=True,
            ),
            health=self.health,
            roadmap=self.roadmap,
            data_mode="local_read_only_snapshot",
            revision_policy="latest_available_at_snapshot_time",
            raw_hash_audit="not_run_by_ui",
        )

    def points(self, key, start=None, end=None):
        if key not in self.series:
            raise KeyError("unknown series")
        if start:
            start = date.fromisoformat(start).isoformat()
        if end:
            end = date.fromisoformat(end).isoformat()
        if start and end and start > end:
            raise ValueError("start must not follow end")
        series = self.series[key]
        return {key: value for key, value in series.items() if key != "points"} | dict(
            points=[
                point
                for point in series["points"]
                if (not start or point["date"] >= start) and (not end or point["date"] <= end)
            ]
        )


def handler_for(workspace, port):
    runtime = dict(
        pid=os.getpid(),
        instance=uuid4().hex,
        version=__version__,
        workspace_id=workspace.summary["workspace_id"],
        data_mode="local_read_only_snapshot",
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send_body(self, status, content, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
            )
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if self.headers.get("Host") not in allowed:
                self.send_body(403, b"loopback host required", "text/plain")
                return
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://{host}" for host in allowed}:
                self.send_body(403, b"same origin required", "text/plain")
                return
            path = urlsplit(self.path)
            try:
                if path.path in {"/", "/app.js", "/markdown.js", "/style.css"}:
                    name = {
                        "/": "index.html",
                        "/app.js": "app.js",
                        "/markdown.js": "markdown.js",
                        "/style.css": "style.css",
                    }[path.path]
                    mime = {
                        "index.html": "text/html",
                        "app.js": "text/javascript",
                        "markdown.js": "text/javascript",
                        "style.css": "text/css",
                    }[name]
                    self.send_body(
                        200,
                        files("gold_intelligence").joinpath("web", name).read_bytes(),
                        mime + "; charset=utf-8",
                    )
                    return
                if path.path == "/api/status":
                    result = runtime
                elif path.path == "/api/summary":
                    result = workspace.summary
                elif path.path == "/api/series":
                    query = parse_qs(path.query)
                    result = workspace.points(
                        query["id"][0], query.get("start", [None])[0], query.get("end", [None])[0]
                    )
                elif path.path == "/api/report":
                    result = workspace.reports[parse_qs(path.query)["id"][0]]
                elif path.path == "/api/comparison":
                    result = workspace.comparisons[parse_qs(path.query)["id"][0]]
                else:
                    self.send_body(404, b"not found", "text/plain")
                    return
                self.send_body(
                    200,
                    json.dumps(result, ensure_ascii=False, allow_nan=False).encode(),
                    "application/json; charset=utf-8",
                )
            except (ValueError, KeyError):
                self.send_body(400, b"invalid local view request", "text/plain")

    return Handler


def serve_local(store, reports, roadmap, port=8765):
    if not 1024 <= port <= 65535:
        raise ValueError("port must be from 1024 to 65535")
    workspace = Workspace(store, reports, roadmap)
    with ThreadingHTTPServer(("127.0.0.1", port), handler_for(workspace, port)) as server:
        print(f"Gold local workspace: http://127.0.0.1:{port} — read-only snapshot", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return {"status": "stopped"}
