import io
import json
from urllib.error import HTTPError, URLError

import pytest

from gold_intelligence import ingestion
from gold_intelligence.acquisition import acquire
from gold_intelligence.transport_evidence import capture_transport, load_transport


@pytest.mark.parametrize("code,count", [(403, 1), (429, 3), (503, 3)])
def test_failed_acquisition_captures_bounded_attempts_without_secrets(
    store, monkeypatch, code, count
):
    secret = "SECRET_API_KEY"

    def fail(*args, **kwargs):
        raise HTTPError("https://example.org/?api_key=" + secret, code, secret, {}, None)

    monkeypatch.setattr(ingestion, "urlopen", fail)
    monkeypatch.setattr(ingestion.time, "sleep", lambda _: None)
    identifier = "a" * 32
    with pytest.raises(ValueError, match=f"HTTP {code}"):
        acquire(
            store,
            "fetch-cftc-gold",
            {},
            lambda: ingestion.fetch_bytes("https://example.org/?api_key=" + secret),
            run_id=identifier,
        )
    evidence = load_transport(store.root, identifier)
    assert len(evidence.attempts) == count
    assert [a.attempt for a in evidence.attempts] == list(range(1, count + 1))
    assert all(a.status_code == code for a in evidence.attempts)
    content = (store.root / "transport" / f"{identifier}.json").read_text()
    assert secret not in content and "example.org" not in content
    assert evidence.quota_status == "not_measured"


def test_transport_scope_resets_and_nested_capture_is_isolated(monkeypatch):
    def fail(*args, **kwargs):
        raise URLError("private provider exception")

    monkeypatch.setattr(ingestion, "urlopen", fail)
    with capture_transport() as outer:
        with capture_transport() as inner, pytest.raises(ValueError):
            ingestion.fetch_bytes("https://example.org", attempts=1)
        assert not outer and len(inner) == 1
        with pytest.raises(ValueError):
            ingestion.fetch_bytes("https://example.org", attempts=1)
    with pytest.raises(ValueError):
        ingestion.fetch_bytes("https://example.org", attempts=1)
    assert len(outer) == 1 and len(inner) == 1


def test_transport_rejects_changed_run_and_wrong_identifier(store):
    result = acquire(store, "import-records", {}, lambda: 0)
    evidence = load_transport(store.root, result["run_id"])
    assert evidence.attempts == ()
    assert load_transport(store.root, "0" * 32) is None
    path = store.root / "runs" / f"{result['run_id']}.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="differs"):
        load_transport(store.root, result["run_id"])


def test_transport_extra_payload_is_rejected(store):
    result = acquire(store, "import-records", {}, lambda: 0)
    path = store.root / "transport" / f"{result['run_id']}.json"
    data = json.loads(path.read_bytes())
    data["url"] = "https://example.org/?api_key=private"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_transport(store.root, result["run_id"])


def test_retry_then_success_and_response_limit(monkeypatch):
    calls = 0

    def respond(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise HTTPError("private", 503, "private", {}, None)
        return io.BytesIO(b"public data")

    monkeypatch.setattr(ingestion, "urlopen", respond)
    monkeypatch.setattr(ingestion.time, "sleep", lambda _: None)
    with capture_transport() as attempts:
        assert ingestion.fetch_bytes("https://example.org") == b"public data"
    assert [(a.attempt, a.outcome) for a in attempts] == [(1, "http_error"), (2, "success")]
    monkeypatch.setattr(ingestion, "urlopen", lambda *a, **k: io.BytesIO(b"x" * 20_000_001))
    with capture_transport() as attempts, pytest.raises(ValueError, match="20 MB"):
        ingestion.fetch_bytes("https://example.org")
    assert len(attempts) == 1 and attempts[0].outcome == "response_too_large"


def test_thread_capture_does_not_mix_attempts():
    from concurrent.futures import ThreadPoolExecutor

    from gold_intelligence.transport_evidence import record_attempt, started_now

    def capture(code):
        with capture_transport() as attempts:
            record_attempt(started_now(), 1, "http_error", code)
        return attempts

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(capture, [403, 429]))
    assert [[a.status_code for a in attempts] for attempts in results] == [[403], [429]]


def test_transport_rejects_attempt_outside_run(store):
    result = acquire(store, "import-records", {}, lambda: 0)
    path = store.root / "transport" / f"{result['run_id']}.json"
    data = json.loads(path.read_bytes())
    data["attempts"] = [
        {
            "started_at": "2000-01-01T00:00:00Z",
            "attempt": 1,
            "outcome": "success",
            "status_code": None,
        }
    ]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="timestamps"):
        load_transport(store.root, result["run_id"])
