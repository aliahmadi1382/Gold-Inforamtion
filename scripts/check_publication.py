"""Fail CI if runtime/private data or unreviewed data artifacts are tracked."""

import json
import subprocess
from pathlib import Path

ALLOWED_DATA = {"data/events/historical_events.json"}
ALLOWED_EXAMPLES = {
    "examples/README.md",
    "examples/synthetic_prices.csv",
    "examples/synthetic_snapshot.json",
}


def main():
    tracked = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
    errors = []
    for name in filter(None, tracked):
        path = Path(name)
        if (
            name.startswith(("local/", ".venv/", "artifacts/"))
            or path.suffix.lower() in {".db", ".sqlite3", ".sqlite", ".pem", ".key"}
            or (path.name.startswith(".env") and path.name != ".env.example")
        ):
            errors.append(name)
        if name.startswith("data/") and path.name != "README.md" and name not in ALLOWED_DATA:
            errors.append(name)
        if name.startswith("examples/") and name not in ALLOWED_EXAMPLES:
            errors.append(name)
    sample = Path("examples/synthetic_snapshot.json")
    if sample.exists() and json.loads(sample.read_text())["synthetic"] is not True:
        errors.append(str(sample))
    if errors:
        raise SystemExit("Unapproved tracked artifacts: " + ", ".join(sorted(set(errors))))
    print("Publication boundary check passed.")


if __name__ == "__main__":
    main()
