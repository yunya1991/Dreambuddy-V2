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


def test_http_send_envelope_maps_to_spec_endpoint_and_adds_jwt_header():
    mod = _load_module("workflows/trading-decision/transports/adapters.py")
    captured = {}

    def fake_sender(url, payload, timeout_ms, headers=None):
        captured["url"] = url
        captured["headers"] = headers or {}
        captured["payload"] = payload
        return {"status": 202}

    tp = mod.HTTPTransport(base_url="http://localhost:8080", sender=fake_sender, jwt_token="test-token")
    envelope = {"header": {"target": "A4", "loop_type": "execution"}, "payload": {"trace_id": "t1"}}
    rsp = tp.send_envelope(envelope)
    assert rsp["status"] == 202
    assert captured["url"].endswith("/a4/validation")
    assert captured["headers"]["Authorization"] == "Bearer test-token"

