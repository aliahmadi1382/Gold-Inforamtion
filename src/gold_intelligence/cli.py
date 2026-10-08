import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import yaml
from pydantic import ValidationError

from .acquisition import SAFE_PARAMETERS, AcquisitionRun, acquire, list_runs
from .alpha_vantage import ingest_alpha_gold
from .analysis import event_study
from .backup import BackupManifest, RestoreReceipt, backup_store, restore_store, verify_backup
from .brief import ResearchBrief, build_brief, render_persian
from .cftc import FIRST_DATE, CotCapture, ingest_cftc_gold
from .comparison import compare_monthly
from .credentials import credential_environment
from .demo import demo
from .evidence_synthesis import (
    EvidenceSynthesis,
    SynthesisManifest,
    verify_synthesis,
    write_synthesis,
)
from .ingestion import import_cftc, import_prices, import_records, ingest_fred, timestamp
from .local_ui import serve_local
from .macro import MacroContext, MacroPlan, fetch_core, load_plan, macro_context
from .models import RECORD_TYPES, HistoricalEvent, Provenance
from .monthly_research import (
    MonthlyResearch,
    MonthlyResearchPlan,
    load_research_plan,
    monthly_research,
    render_monthly_persian,
)
from .operations_health import OperationsHealth, build_operations_health, write_operations_health
from .positioning import PositioningContext, positioning_context, write_positioning
from .project_roadmap import ProjectRoadmap
from .quality import QualityPolicy, QualityReport, assess, load_policy
from .refresh import RefreshPolicy, RefreshRun, refresh_and_report
from .refresh_review import (
    RefreshReview,
    ReviewManifest,
    select_baseline,
    verify_review,
    write_refresh_review,
)
from .registry import Registry, export_public, load_registry
from .release_calendar import CalendarContext, ReleaseEvidence, calendar_context, import_evidence
from .release_values import (
    ReleaseValueEvidence,
    ReleaseValueReport,
    import_release_values,
    release_value_report,
    render_release_values,
)
from .report_comparison import (
    ComparisonManifest,
    ReportComparison,
    ReportComparisonV1,
    compare_reports,
    verify_comparison,
)
from .research_report import (
    ReportManifest,
    ReportManifestV1,
    ReportSettings,
    ResearchReport,
    ResearchReportV1,
    build_research_report,
    verify_research_bundle,
    write_research_report,
)
from .revision_ledger import (
    RevisionLedger,
    RevisionPlan,
    load_revision_plan,
    render_revision_ledger,
    revision_ledger,
)
from .runtime_evidence import RuntimeEvidence, RuntimeManifest
from .snapshot import MarketSnapshot, snapshot
from .storage import Store
from .transport_evidence import TransportEvidence
from .world_bank import ingest_monthly_gold


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Gold Market Intelligence — research only")
    p.add_argument("--registry", type=Path, default=Path("sources/source_registry.yaml"))
    p.add_argument("--store", type=Path, default=Path("local/market"))
    p.add_argument(
        "--credentials-file",
        type=Path,
        help="explicit local key file; values are not included in manifests",
    )
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("validate-registry")
    d = sub.add_parser("demo", help="generate fictional prices and a research snapshot offline")
    d.add_argument("--output", type=Path, default=Path("local/demo"))
    s = sub.add_parser("schemas")
    s.add_argument("--output", type=Path, default=Path("schemas"))
    sub.add_parser("audit")
    sub.add_parser("runs", help="list local acquisition manifests without credentials")
    c = sub.add_parser("local-ui", help="read-only graphical workspace on loopback")
    c.add_argument("--reports", type=Path, default=Path("local/reports"))
    c.add_argument("--roadmap", type=Path, default=Path("config/project_roadmap.json"))
    c.add_argument("--port", type=int, default=8765)
    c = sub.add_parser("operations-health", help="offline run health; quota remains unmeasured")
    c.add_argument("--refresh-manifest", type=Path)
    c.add_argument("--allow-relocated-refresh", action="store_true")
    c.add_argument("--output-dir", type=Path, required=True)
    c = sub.add_parser("backup-store", help="verified SQLite/raw/acquisition snapshot without keys")
    c.add_argument("--output-dir", type=Path, default=Path("local/backups"))
    c = sub.add_parser("verify-backup", help="verify backup hashes, SQLite and evidence lineage")
    c.add_argument("directory", type=Path)
    c = sub.add_parser("restore-store", help="restore to a new isolated container; no overwrite")
    c.add_argument("directory", type=Path)
    c.add_argument("--destination", type=Path, required=True)
    c = sub.add_parser("fetch-cftc-gold", help="public disaggregated COMEX gold futures history")
    c.add_argument("--start", type=date.fromisoformat, default=FIRST_DATE)
    c.add_argument("--end", type=date.fromisoformat, required=True)
    c = sub.add_parser("positioning-context", help="reconciled weekly COT context known at cutoff")
    c.add_argument("--as-of", type=timestamp, required=True)
    c.add_argument("--max-age-days", type=int, default=14)
    c.add_argument("--output-dir", type=Path, default=Path("local/reports/positioning"))
    c = sub.add_parser("compare-reports", help="compare two verified saved research bundles")
    c.add_argument("before", type=Path)
    c.add_argument("after", type=Path)
    c.add_argument("--output-dir", type=Path, default=Path("local/reports/comparisons"))
    c = sub.add_parser("verify-comparison", help="verify and recompute a saved comparison")
    c.add_argument("directory", type=Path)
    c = sub.add_parser("review-refresh", help="review a saved refresh without network acquisition")
    c.add_argument("directory", type=Path)
    c.add_argument("--baseline", type=Path)
    c = sub.add_parser("verify-review", help="verify and recompute a saved refresh review")
    c.add_argument("directory", type=Path)
    c = sub.add_parser(
        "synthesize-report", help="offline evidence synthesis from a verified report"
    )
    c.add_argument("directory", type=Path)
    c.add_argument("--output-dir", type=Path, default=Path("local/reports/synthesis"))
    c = sub.add_parser("verify-synthesis", help="recompute a self-contained evidence synthesis")
    c.add_argument("directory", type=Path)
    for name in ("research-report", "refresh-report"):
        c = sub.add_parser(
            name,
            help="compose stored research"
            if name == "research-report"
            else "manually refresh sources and build a report",
        )
        if name == "research-report":
            c.add_argument("--as-of", type=timestamp, required=True)
        else:
            c.add_argument("--fred-overlap-days", type=int, default=120)
            c.add_argument("--cot-overlap-days", type=int, default=90)
            c.add_argument("--full-history", action="store_true")
            c.add_argument(
                "--baseline", type=Path, help="explicit verified report bundle to compare"
            )
        c.add_argument("--macro-plan", type=Path, default=Path("config/macro_core.yaml"))
        c.add_argument("--monthly-plan", type=Path, default=Path("config/monthly_research.yaml"))
        c.add_argument("--revision-plan", type=Path, default=Path("config/revision_ledger.yaml"))
        c.add_argument("--policy", type=Path, default=Path("config/quality_history.yaml"))
        c.add_argument("--horizon-days", type=int, default=90)
        c.add_argument("--calendar-max-age-hours", type=float, default=168)
        c.add_argument("--positioning-max-age-days", type=int, default=14)
        c.add_argument(
            "--output-dir",
            type=Path,
            default=Path(
                "local/reports/unified" if name == "research-report" else "local/reports/refresh"
            ),
        )
    c = sub.add_parser("verify-report", help="verify a saved report bundle's hashes and coherence")
    c.add_argument("directory", type=Path)
    c = sub.add_parser("revision-ledger", help="fixed-window adjacent-document revision ledger")
    c.add_argument("--as-of", type=timestamp, required=True)
    c.add_argument("--plan", type=Path, default=Path("config/revision_ledger.yaml"))
    c.add_argument("--output-dir", type=Path, default=Path("local/reports"))
    c = sub.add_parser(
        "import-release-values", help="import reviewed archive values with document identity"
    )
    c.add_argument("path", type=Path)
    c.add_argument("--reviewed", action="store_true", required=True)
    c = sub.add_parser(
        "release-value-report", help="compare document values with exact-date FRED vintages"
    )
    c.add_argument("--as-of", type=timestamp, required=True)
    c.add_argument("--output-dir", type=Path, default=Path("local/reports"))
    c = sub.add_parser("monthly-research", help="local descriptive gold/macro relationships")
    c.add_argument("--as-of", type=timestamp, required=True)
    c.add_argument("--plan", type=Path, default=Path("config/monthly_research.yaml"))
    c.add_argument("--output-dir", type=Path, default=Path("local/reports"))
    c = sub.add_parser(
        "import-release-evidence", help="import reviewed official BLS timing evidence"
    )
    c.add_argument("path", type=Path)
    c.add_argument("--reviewed", action="store_true", required=True)
    c = sub.add_parser("calendar-context", help="upcoming announced times with source evidence")
    c.add_argument("--as-of", type=timestamp, required=True)
    c.add_argument("--horizon-days", type=int, default=90)
    c.add_argument("--output", type=Path)
    c = sub.add_parser("research-brief", help="local Persian data-status brief, JSON and Markdown")
    c.add_argument("--as-of", type=timestamp, required=True)
    c.add_argument("--horizon-days", type=int, default=90)
    c.add_argument("--plan", type=Path, default=Path("config/macro_core.yaml"))
    c.add_argument("--policy", type=Path, default=Path("config/quality_history.yaml"))
    c.add_argument("--output-dir", type=Path, default=Path("local/reports"))
    sub.add_parser("fetch-alpha-gold", help="fetch daily XAUUSD close-only provider history")
    sub.add_parser("fetch-worldbank-gold", help="fetch the reviewed monthly Pink Sheet workbook")
    f = sub.add_parser(
        "fetch-fred-core", help="backfill the reviewed macro set with metadata gates"
    )
    f.add_argument("--plan", type=Path, default=Path("config/macro_core.yaml"))
    f.add_argument("--start", type=date.fromisoformat, default=date(1776, 7, 4))
    f.add_argument("--end", type=date.fromisoformat, required=True)
    f.add_argument("--vintage", type=date.fromisoformat)
    f = sub.add_parser("macro-context", help="select only macro observations known at the cutoff")
    f.add_argument("--plan", type=Path, default=Path("config/macro_core.yaml"))
    f.add_argument("--as-of", type=timestamp, required=True)
    f.add_argument("--mode", choices=["system", "source"], default="system")
    f.add_argument("--vintage", type=date.fromisoformat)
    f.add_argument("--output", type=Path)
    f = sub.add_parser("compare-monthly", help="compare distinct gold series at monthly frequency")
    f.add_argument("--as-of", type=timestamp, required=True)
    f.add_argument("--output", type=Path)
    q = sub.add_parser("quality", help="audit eligible data and report coverage/readiness")
    q.add_argument("--as-of", type=timestamp, required=True)
    q.add_argument("--mode", choices=["system", "source"], default="system")
    q.add_argument("--policy", type=Path, default=Path("config/quality_policy.yaml"))
    q.add_argument("--allow-synthetic", action="store_true")
    q.add_argument("--output", type=Path)
    c = sub.add_parser("import-records", help="validated JSONL plus hash-named raw evidence")
    c.add_argument("path", type=Path)
    c.add_argument("--raw-dir", type=Path, required=True)
    c = sub.add_parser("import-prices")
    c.add_argument("path", type=Path)
    c.add_argument("--source", required=True)
    c.add_argument("--instrument", required=True)
    c.add_argument("--venue", required=True)
    c.add_argument("--dataset", required=True)
    c.add_argument("--timeframe", default="1d")
    c.add_argument("--price-type", default="spot")
    c.add_argument("--currency", default="USD")
    c.add_argument("--unit", default="currency_per_troy_ounce")
    c.add_argument("--volume-unit", choices=["contracts", "shares", "troy_ounces", "ticks"])
    c.add_argument("--contract-expiry", type=date.fromisoformat)
    c.add_argument("--timezone", default="UTC", help="IANA zone matching original bar offsets")
    c.add_argument("--verified-availability", action="store_true")
    c.add_argument("--retrieved-at", type=timestamp)
    c = sub.add_parser("import-cftc")
    c.add_argument("path", type=Path)
    c.add_argument("--market-code", default="088691")
    c.add_argument(
        "--futures-only",
        action="store_true",
        required=True,
        help="attest that the downloaded file is legacy futures-only, not combined",
    )
    f = sub.add_parser("fetch-fred")
    f.add_argument("series")
    f.add_argument("--start", type=date.fromisoformat, required=True)
    f.add_argument("--end", type=date.fromisoformat, required=True)
    f.add_argument("--vintage", type=date.fromisoformat)
    f.add_argument("--series-config", type=Path, default=Path("config/macro_series.yaml"))
    s = sub.add_parser("snapshot")
    s.add_argument("--as-of", type=timestamp, required=True)
    s.add_argument("--instrument", default="XAUUSD")
    s.add_argument("--timeframe", default="1d")
    s.add_argument("--mode", choices=["system", "source"], default="system")
    s.add_argument("--source")
    s.add_argument("--dataset")
    s.add_argument("--venue")
    s.add_argument("--stale-after-hours", type=float, default=96)
    s.add_argument("--output", type=Path)
    e = sub.add_parser("event-study")
    e.add_argument("--event-at", type=timestamp, required=True)
    e.add_argument("--as-of", type=timestamp, required=True)
    e.add_argument("--horizon", type=int, default=20)
    e.add_argument("--instrument", default="XAUUSD")
    e.add_argument("--timeframe", default="1d")
    e.add_argument("--source", required=True)
    e.add_argument("--dataset", required=True)
    e = sub.add_parser("export-public")
    e.add_argument("--kind", choices=list(RECORD_TYPES), required=True)
    e.add_argument("--source", required=True)
    e.add_argument("--output", type=Path, required=True)
    return p


def run(args) -> dict:
    if args.command == "verify-synthesis":
        return verify_synthesis(args.directory)
    if args.command == "synthesize-report":
        synthesis, directory = write_synthesis(args.directory, args.output_dir)
        return dict(
            status=synthesis.status,
            bundle=str(directory),
            report=str(directory / "synthesis.fa.md"),
            fingerprint=synthesis.fingerprint,
            outcomes=synthesis.outcome_counts,
            daily_backtest_ready=False,
        )
    if args.command == "local-ui":
        return serve_local(args.store, args.reports, args.roadmap, args.port)
    if args.command == "operations-health":
        if args.output_dir.resolve().is_relative_to(args.store.resolve()):
            raise ValueError("health output must be outside the store")
        report = build_operations_health(
            args.store, args.refresh_manifest, allow_relocated_refresh=args.allow_relocated_refresh
        )
        return write_operations_health(report, args.output_dir)
    if args.command == "backup-store":
        manifest, directory = backup_store(args.store, args.output_dir)
        return {
            "status": "created_and_verified",
            "bundle": str(directory),
            "summary": str(directory / "backup.fa.md"),
            "fingerprint": manifest.fingerprint,
            "records": manifest.records,
            "raw_blobs": manifest.raw_blobs,
            "acquisition_runs": manifest.acquisition_runs,
            "run_states": manifest.run_states,
        }
    if args.command == "verify-backup":
        return verify_backup(args.directory)
    if args.command == "restore-store":
        return restore_store(args.directory, args.destination).model_dump(mode="json")
    if args.command == "verify-review":
        return verify_review(args.directory)
    if args.command == "review-refresh":
        # Offline recovery is explicit: no automatic scan can select this run as its own baseline.
        baseline = select_baseline(None, args.baseline)
        review, directory = write_refresh_review(args.directory, baseline)
        return {
            "status": review.status,
            "bundle": str(directory),
            "report": str(directory / "review.fa.md"),
            "fingerprint": review.fingerprint,
            "daily_backtest_ready": False,
        }
    if args.command == "compare-reports":
        report, directory = compare_reports(args.before, args.after, args.output_dir)
        return {
            "status": report.status,
            "bundle": str(directory),
            "report": str(directory / "comparison.fa.md"),
            "fingerprint": report.fingerprint,
            "context_changes": len(report.context_changes),
            "changed_entities": len(report.changes),
            "daily_backtest_ready": False,
        }
    if args.command == "verify-comparison":
        return verify_comparison(args.directory)
    if args.command == "verify-report":
        return verify_research_bundle(args.directory)
    registry = load_registry(args.registry)
    if args.command == "validate-registry":
        return {"sources": len(registry.sources), "valid": True}
    if args.command == "schemas":
        args.output.mkdir(parents=True, exist_ok=True)
        models = {
            **RECORD_TYPES,
            "provenance": Provenance,
            "source_registry": Registry,
            "historical_event": HistoricalEvent,
            "market_snapshot": MarketSnapshot,
            "acquisition_run": AcquisitionRun,
            "quality_policy": QualityPolicy,
            "quality_report": QualityReport,
            "macro_plan": MacroPlan,
            "macro_context": MacroContext,
            "release_evidence": ReleaseEvidence,
            "calendar_context": CalendarContext,
            "research_brief": ResearchBrief,
            "monthly_research_plan": MonthlyResearchPlan,
            "monthly_research": MonthlyResearch,
            "release_value_evidence": ReleaseValueEvidence,
            "release_value_report": ReleaseValueReport,
            "revision_plan": RevisionPlan,
            "revision_ledger": RevisionLedger,
            "research_report": ResearchReport,
            "report_manifest": ReportManifest,
            "report_comparison": ReportComparison,
            "comparison_manifest": ComparisonManifest,
            "cot_capture": CotCapture,
            "positioning_context": PositioningContext,
            "research_report_v1": ResearchReportV1,
            "report_manifest_v1": ReportManifestV1,
            "report_comparison_v1": ReportComparisonV1,
            "refresh_run": RefreshRun,
            "refresh_review": RefreshReview,
            "review_manifest": ReviewManifest,
            "backup_manifest": BackupManifest,
            "restore_receipt": RestoreReceipt,
            "operations_health": OperationsHealth,
            "project_roadmap": ProjectRoadmap,
            "runtime_evidence": RuntimeEvidence,
            "runtime_manifest": RuntimeManifest,
            "transport_evidence": TransportEvidence,
            "evidence_synthesis": EvidenceSynthesis,
            "synthesis_manifest": SynthesisManifest,
        }
        for name, model in models.items():
            schema = {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                **model.model_json_schema(),
            }
            (args.output / f"{name}.schema.json").write_text(
                json.dumps(schema, indent=2) + "\n", encoding="utf-8"
            )
        return {"schemas": len(models)}
    if args.command == "demo":
        return demo(args.output, registry)
    with Store(args.store) as store:
        if args.command == "positioning-context":
            report = positioning_context(store, registry, args.as_of, args.max_age_days)
            directory = write_positioning(report, args.output_dir)
            return {
                "status": report.status,
                "report": str(directory / "positioning.fa.md"),
                "weeks": len(report.weeks),
                "fingerprint": report.fingerprint,
                "irregular_intervals": len(report.irregular_intervals),
                "historical_release_ready": False,
            }
        if args.command in {"research-report", "refresh-report"}:
            settings = ReportSettings(
                macro_plan=load_plan(args.macro_plan),
                quality_policy=load_policy(args.policy),
                monthly_plan=load_research_plan(args.monthly_plan),
                revision_plan=load_revision_plan(args.revision_plan),
                calendar_horizon_days=args.horizon_days,
                calendar_max_evidence_age_hours=args.calendar_max_age_hours,
                positioning_max_age_days=args.positioning_max_age_days,
            )
            if args.command == "refresh-report":
                baseline = select_baseline(args.output_dir, args.baseline, store.root)
                workflow, directory = refresh_and_report(
                    store,
                    registry,
                    settings,
                    RefreshPolicy(
                        fred_overlap_days=args.fred_overlap_days,
                        cot_overlap_days=args.cot_overlap_days,
                        full_history=args.full_history,
                    ),
                    args.output_dir,
                )
                bundle = directory / workflow.report.bundle if workflow.report.bundle else None
                review_status, review_path, review_bundle, review_failure = (
                    "failed",
                    None,
                    None,
                    None,
                )
                try:
                    review, review_directory = write_refresh_review(directory, baseline)
                    review_status = review.status
                    review_path = str(review_directory / "review.fa.md")
                    review_bundle = str(review_directory)
                    with (directory / "refresh.fa.md").open("a", encoding="utf-8") as stream:
                        relative = (
                            (review_directory / "review.fa.md").relative_to(directory).as_posix()
                        )
                        stream.write(f"\n[خلاصهٔ تغییرات و اولویت بررسی]({relative})\n")
                except Exception as exc:
                    # Completed acquisition/report state remains independently visible.
                    review_status = "failed"
                    review_failure = type(exc).__name__
                return {
                    "status": workflow.status,
                    "run_id": workflow.run_id,
                    "manifest": str(directory / "refresh-run.json"),
                    "summary": str(directory / "refresh.fa.md"),
                    "sources": {s.key: s.status for s in workflow.steps},
                    "report_status": workflow.report.status,
                    "research_status": workflow.report.research_status,
                    "bundle": str(bundle) if bundle else None,
                    "report": str(bundle / "research-report.fa.md") if bundle else None,
                    "freshness": {f.key: f.status for f in workflow.report.freshness},
                    "daily_backtest_ready": False,
                    "review_status": review_status,
                    "review": review_path,
                    "review_bundle": review_bundle,
                    "review_failure_type": review_failure,
                }
            report = build_research_report(store, registry, settings, args.as_of)
            directory = write_research_report(report, args.output_dir)
            return {
                "status": report.status,
                "report": str(directory / "research-report.fa.md"),
                "bundle": str(directory),
                "fingerprint": report.fingerprint,
                "as_of": report.as_of.isoformat(),
                "sections": {s.key: s.status for s in report.sections},
                "daily_backtest_ready": False,
            }
        if args.command == "revision-ledger":
            report = revision_ledger(store, registry, load_revision_plan(args.plan), args.as_of)
            args.output_dir.mkdir(parents=True, exist_ok=True)
            (args.output_dir / "revision-ledger.json").write_text(
                report.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
            output = args.output_dir / "revision-ledger.fa.md"
            output.write_text(render_revision_ledger(report), encoding="utf-8")
            return {
                "status": report.status,
                "report": str(output),
                "expected_pairs": report.expected_pairs,
                "compared_pairs": report.compared_pairs,
                "vintage_matched_pairs": report.vintage_matched_pairs,
                "fingerprint": report.fingerprint,
                "intraday_replay_ready": False,
            }
        if args.command == "release-value-report":
            report = release_value_report(store, registry, args.as_of)
            args.output_dir.mkdir(parents=True, exist_ok=True)
            (args.output_dir / "release-values.json").write_text(
                report.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
            output = args.output_dir / "release-values.fa.md"
            output.write_text(render_release_values(report), encoding="utf-8")
            return {
                "status": report.status,
                "report": str(output),
                "documents": len(report.documents),
                "fingerprint": report.fingerprint,
                "intraday_replay_ready": False,
            }
        if args.command == "monthly-research":
            report = monthly_research(store, load_research_plan(args.plan), args.as_of)
            args.output_dir.mkdir(parents=True, exist_ok=True)
            (args.output_dir / "monthly-research.json").write_text(
                report.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
            output = args.output_dir / "monthly-research.fa.md"
            output.write_text(render_monthly_persian(report), encoding="utf-8")
            return {
                "status": report.status,
                "report": str(output),
                "fingerprint": report.fingerprint,
                "estimated_associations": sum(a.status == "estimated" for a in report.associations),
                "daily_backtest_ready": False,
            }
        if args.command == "calendar-context":
            report = calendar_context(store, args.as_of, args.horizon_days)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
            return report.model_dump(mode="json")
        if args.command == "research-brief":
            report = build_brief(
                store,
                registry,
                load_plan(args.plan),
                load_policy(args.policy),
                args.as_of,
                args.horizon_days,
            )
            args.output_dir.mkdir(parents=True, exist_ok=True)
            (args.output_dir / "research-brief.json").write_text(
                report.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
            output = args.output_dir / "research-brief.fa.md"
            output.write_text(render_persian(report), encoding="utf-8")
            return {
                "status": report.quality.status,
                "report": str(output),
                "macro_status": report.macro.status,
                "calendar_status": report.calendar.status,
                "upcoming_events": len(report.calendar.upcoming),
                "daily_backtest_ready": False,
            }
        if args.command == "fetch-fred-core":
            return fetch_core(
                store,
                registry.get("fred"),
                load_plan(args.plan),
                args.start,
                args.end,
                args.vintage,
            )
        if args.command in {"macro-context", "compare-monthly"}:
            if args.command == "macro-context":
                result = macro_context(
                    store, load_plan(args.plan), args.as_of, args.mode, args.vintage
                ).model_dump(mode="json")
            else:
                result = compare_monthly(store, args.as_of)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            return result
        if args.command == "audit":
            return store.audit()
        if args.command == "runs":
            return {"runs": list_runs(store.root)}
        if args.command == "quality":
            report = assess(
                store,
                registry,
                args.as_of,
                load_policy(args.policy),
                args.mode,
                args.allow_synthetic,
            )
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
            return report.model_dump(mode="json")
        if args.command in {
            "import-prices",
            "import-cftc",
            "import-records",
            "fetch-fred",
            "fetch-alpha-gold",
            "fetch-worldbank-gold",
            "fetch-cftc-gold",
            "import-release-evidence",
            "import-release-values",
        }:
            parameters = {
                k: v if isinstance(v, bool) or v is None else str(v)
                for k, v in vars(args).items()
                if k in SAFE_PARAMETERS
            }
            if hasattr(args, "path"):
                parameters["input_filename"] = args.path.name
            if hasattr(args, "futures_only"):
                parameters["futures_only_confirmed"] = args.futures_only
            if args.command == "fetch-alpha-gold":
                parameters.update(source="alpha_vantage_gold", instrument="XAUUSD", timeframe="1d")
            if args.command == "fetch-worldbank-gold":
                parameters.update(
                    source="world_bank_pink_sheet", instrument="GOLD", timeframe="1mo"
                )
            if args.command == "fetch-cftc-gold":
                parameters.update(source="cftc_disaggregated", market_code="088691")
            return acquire(
                store, args.command, parameters, lambda: perform_ingestion(args, store, registry)
            )
        if args.command == "snapshot":
            result = snapshot(
                store,
                args.as_of,
                args.instrument,
                args.timeframe,
                args.mode,
                args.source,
                args.dataset,
                args.venue,
                args.stale_after_hours,
            )
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
            return result.model_dump(mode="json")
        if args.command == "event-study":
            bars = [
                b
                for b in store.read("price_bar", args.as_of)
                if b.instrument == args.instrument
                and b.timeframe == args.timeframe
                and b.provenance.source_id == args.source
                and b.provenance.dataset == args.dataset
            ]
            return event_study(bars, args.event_at, args.horizon)
        if args.command == "export-public":
            records = [
                r
                for r in store.read(args.kind, datetime.now(UTC))
                if r.provenance.source_id == args.source
            ]
            return {"exported": export_public(records, registry, args.output)}
    raise ValueError("unknown command")


def perform_ingestion(args, store, registry) -> int:
    if args.command == "fetch-cftc-gold":
        return ingest_cftc_gold(store, registry.get("cftc_disaggregated"), args.start, args.end)
    if args.command == "import-release-values":
        return import_release_values(store, args.path, registry.get("bls"), reviewed=args.reviewed)
    if args.command == "import-release-evidence":
        return import_evidence(store, args.path, registry.get("bls"), reviewed=args.reviewed)
    if args.command == "fetch-worldbank-gold":
        return ingest_monthly_gold(store, registry.get("world_bank_pink_sheet"))
    if args.command == "fetch-alpha-gold":
        return ingest_alpha_gold(store, registry.get("alpha_vantage_gold"))
    if args.command == "import-records":
        return import_records(store, args.path, args.raw_dir, registry)
    if args.command == "import-prices":
        return import_prices(
            store,
            args.path,
            registry.get(args.source),
            instrument=args.instrument,
            venue=args.venue,
            dataset=args.dataset,
            timeframe=args.timeframe,
            price_type=args.price_type,
            currency=args.currency,
            unit=args.unit,
            volume_unit=args.volume_unit,
            contract_expiry=args.contract_expiry,
            original_timezone=args.timezone,
            retrieved_at=args.retrieved_at,
            verified_availability=args.verified_availability,
        )
    if args.command == "import-cftc":
        return import_cftc(
            store,
            args.path,
            registry.get("cftc_legacy"),
            args.market_code,
            futures_only_confirmed=args.futures_only,
        )
    config = yaml.safe_load(args.series_config.read_text(encoding="utf-8"))["series"]
    if args.series not in config:
        raise ValueError("series is not in the reviewed macro shortlist")
    metadata = config[args.series]
    return ingest_fred(
        store,
        registry.get("fred"),
        args.series,
        args.start,
        args.end,
        metadata["unit"],
        metadata["currency"],
        args.vintage,
    )


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        with credential_environment(args.credentials_file):
            result = run(args)
        print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
        if args.command == "operations-health" and result["status"] != "clear":
            return 3
        if args.command == "refresh-report" and (
            result["status"] != "succeeded"
            or result["review_status"] not in {"compared", "no_baseline"}
        ):
            return 3
        if args.command == "review-refresh" and result["status"] not in {"compared", "no_baseline"}:
            return 3
        if args.command == "fetch-fred-core" and result["status"] != "succeeded":
            return 3
        if args.command == "monthly-research" and result["status"] == "insufficient_data":
            return 3
        if args.command == "positioning-context" and result["status"] != "descriptive_only":
            return 3
        if args.command == "release-value-report" and result["status"] != "compared":
            return 3
        if args.command == "revision-ledger" and result["status"] != "complete":
            return 3
        if args.command == "research-report" and result["status"] == "partial":
            return 3
        return (
            3 if args.command in {"quality", "research-brief"} and result["status"] == "fail" else 0
        )
    except (ValueError, OSError, KeyError, ValidationError, yaml.YAMLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
