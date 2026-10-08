"""Start/open/restart only this project's own read-only loopback process."""

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import webbrowser
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from . import __version__


def status(url):
    try:
        with urlopen(url + "/api/status", timeout=1) as response:
            result = json.loads(response.read(8192))
            return result if isinstance(result, dict) else None
    except (URLError, OSError, ValueError):
        return None


def stop_owned(url, receipt_path, workspace_id):
    current = status(url)
    if current is None:
        return
    if not receipt_path.is_file():
        raise ValueError("No owned launch receipt; stop the foreground server with Ctrl+C.")
    receipt = json.loads(receipt_path.read_bytes())
    if (
        any(current.get(key) != receipt.get(key) for key in ("pid", "instance", "workspace_id"))
        or current.get("workspace_id") != workspace_id
    ):
        raise ValueError("Process identity changed; refusing to stop an unrelated process.")
    if type(current.get("pid")) is not int or current["pid"] <= 0 or current["pid"] == os.getpid():
        raise ValueError("Invalid owned process ID.")
    os.kill(current["pid"], signal.SIGTERM)
    for _ in range(30):
        if status(url) is None:
            return
        time.sleep(0.2)
    raise ValueError("Previous local server has not stopped.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Open this project's local research workspace")
    parser.add_argument("--port", type=int, default=8765)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--restart", action="store_true")
    action.add_argument("--stop", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        raise ValueError("Port must be from 1024 to 65535.")
    project = Path.cwd()
    store = (project / "local/market").resolve()
    workspace_id = hashlib.sha256(str(store).encode()).hexdigest()
    url = f"http://127.0.0.1:{args.port}"
    logs = project / "local/ui-runtime"
    receipt = logs / f"server-{args.port}.json"
    if args.restart or args.stop:
        stop_owned(url, receipt, workspace_id)
    if args.stop:
        print("Local workspace stopped.")
        return 0
    current = status(url)
    if current is not None and current.get("workspace_id") != workspace_id:
        raise ValueError("Port belongs to a different local workspace; choose another port.")
    if current is not None and current.get("version") != __version__:
        raise ValueError("A previous version is running; use Restart-Local.cmd.")
    if current is None:
        logs.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        with (
            (logs / f"server-{stamp}.log").open("wb") as out,
            (logs / f"server-{stamp}.error.log").open("wb") as err,
        ):
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "gold_intelligence.cli",
                    "--store",
                    "local/market",
                    "local-ui",
                    "--port",
                    str(args.port),
                ],
                cwd=project,
                stdout=out,
                stderr=err,
                creationflags=flags,
                start_new_session=os.name != "nt",
            )
        for _ in range(45):
            if process.poll() is not None:
                raise ValueError("Startup failed; inspect local/ui-runtime/*.error.log.")
            current = status(url)
            if current is not None:
                if current.get("workspace_id") != workspace_id:
                    raise ValueError("Port identity changed during startup.")
                receipt.write_text(json.dumps(current, indent=2), encoding="utf-8")
                break
            time.sleep(0.5)
        else:
            raise ValueError("Startup has not completed; inspect local/ui-runtime logs.")
    if not args.no_browser:
        webbrowser.open(url)
    print(f"Local workspace ready: {url}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from None
