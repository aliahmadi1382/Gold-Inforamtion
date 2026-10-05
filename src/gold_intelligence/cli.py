import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import yaml
from pydantic import ValidationError

from .acquisition import SAFE_PARAMETERS, AcquisitionRun, acquire, list_runs
from .analysis import event_study
from .credentials import credential_environment
from .demo import demo
from .ingestion import import_cftc, import_prices, import_records, ingest_fred, timestamp
from .models import RECORD_TYPES, HistoricalEvent, Provenance
from .quality import QualityPolicy, QualityReport, assess, load_policy
from .registry import Registry, export_public, load_registry
from .snapshot import MarketSnapshot, snapshot
from .storage import Store


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
        if args.command in {"import-prices", "import-cftc", "import-records", "fetch-fred"}:
            parameters = {
                k: v if isinstance(v, bool) or v is None else str(v)
                for k, v in vars(args).items()
                if k in SAFE_PARAMETERS
            }
            if hasattr(args, "path"):
                parameters["input_filename"] = args.path.name
            if hasattr(args, "futures_only"):
                parameters["futures_only_confirmed"] = args.futures_only
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
        return 3 if args.command == "quality" and result["status"] == "fail" else 0
    except (ValueError, OSError, KeyError, ValidationError, yaml.YAMLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
