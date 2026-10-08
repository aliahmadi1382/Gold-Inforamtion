import hashlib
import json

import pytest

from gold_intelligence import __version__, local_launcher


@pytest.mark.parametrize("change", ["pid", "instance", "workspace_id"])
def test_stop_requires_exact_owned_process(monkeypatch, tmp_path, change):
    current = {"pid": 12345, "instance": "current", "workspace_id": "project"}
    receipt = {**current, change: "different"}
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt))
    monkeypatch.setattr(local_launcher, "status", lambda _: current)
    monkeypatch.setattr(local_launcher.os, "kill", lambda *args: pytest.fail("unrelated kill"))
    with pytest.raises(ValueError, match="identity changed"):
        local_launcher.stop_owned("http://127.0.0.1:8765", path, "project")


def test_foreground_server_without_receipt_is_not_killed(monkeypatch, tmp_path):
    monkeypatch.setattr(local_launcher, "status", lambda _: {"pid": 12345})
    monkeypatch.setattr(local_launcher.os, "kill", lambda *args: pytest.fail("kill"))
    with pytest.raises(ValueError, match="Ctrl\\+C"):
        local_launcher.stop_owned("http://127.0.0.1:8765", tmp_path / "absent", "project")


def test_already_running_reuses_without_new_process(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    identifier = hashlib.sha256(str((tmp_path / "local/market").resolve()).encode()).hexdigest()
    monkeypatch.setattr(
        local_launcher, "status", lambda _: {"workspace_id": identifier, "version": __version__}
    )
    monkeypatch.setattr(
        local_launcher.subprocess, "Popen", lambda *a, **k: pytest.fail("new process")
    )
    assert local_launcher.main(["--no-browser"]) == 0


def test_other_workspace_is_not_opened(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(local_launcher, "status", lambda _: {"workspace_id": "other"})
    monkeypatch.setattr(local_launcher.webbrowser, "open", lambda *a: pytest.fail("browser"))
    with pytest.raises(ValueError, match="different local"):
        local_launcher.main([])


def test_invalid_port_never_starts(monkeypatch):
    monkeypatch.setattr(local_launcher, "status", lambda _: pytest.fail("request"))
    with pytest.raises(ValueError, match="1024"):
        local_launcher.main(["--port", "80"])
