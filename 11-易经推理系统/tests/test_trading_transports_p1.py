import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(rel_path: str):
    path = REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_mock_transport_roundtrip():
    mod = _load_module("workflows/trading-decision/transports/adapters.py")
    tp = mod.MockTransport()
    tp.send("execution", {"trace_id": "t1", "type": "REQUEST"})
    got = tp.receive("execution")
    assert got["trace_id"] == "t1"
    assert tp.receive("execution") is None


def test_http_transport_uses_injected_sender():
    mod = _load_module("workflows/trading-decision/transports/adapters.py")
    sent = {}

    def fake_sender(url, payload, timeout_ms):
        sent["url"] = url
        sent["payload"] = payload
        sent["timeout_ms"] = timeout_ms
        return {"status": 202}

    tp = mod.HTTPTransport(base_url="http://localhost:8080", sender=fake_sender)
    rsp = tp.send("governance", {"trace_id": "t2", "type": "EVENT"})
    assert rsp["status"] == 202
    assert sent["url"].endswith("/governance")
    assert sent["payload"]["trace_id"] == "t2"


def test_mq_transport_publish_and_consume():
    mod = _load_module("workflows/trading-decision/transports/adapters.py")
    tp = mod.MQTransport()
    tp.send("intelligence", {"trace_id": "t3", "priority": "HIGH"})
    got = tp.receive("intelligence")
    assert got["priority"] == "HIGH"
