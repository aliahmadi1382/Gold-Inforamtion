import csv
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .ingestion import import_prices
from .registry import Registry
from .snapshot import snapshot
from .storage import Store


def demo(root: Path, registry: Registry) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "synthetic_prices.csv"
    start = datetime(2024, 1, 2, 22, tzinfo=UTC)
    dates = []
    while len(dates) < 80:
        if start.weekday() < 5:
            dates.append(start)
        start += timedelta(days=1)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["observed_at", "available_at", "open", "high", "low", "close"])
        previous = 1000.0
        for i, date in enumerate(dates):
            close = round(1000 + 2 * i + 15 * math.sin(i / 4), 4)
            writer.writerow(
                [
                    date.isoformat(),
                    date.isoformat(),
                    previous,
                    max(previous, close) + 5,
                    min(previous, close) - 5,
                    close,
                ]
            )
            previous = close
    with Store(root) as store:
        inserted = import_prices(
            store,
            path,
            registry.get("synthetic_demo"),
            instrument="XAUUSD",
            venue="SYNTHETIC",
            dataset="fictional_daily_v1",
            retrieved_at=dates[-1],
            synthetic=True,
        )
        result = snapshot(store, dates[-1], source_id="synthetic_demo")
        output = root / "snapshot.json"
        output.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return {"inserted": inserted, "snapshot": str(output), "synthetic": True, **store.audit()}
