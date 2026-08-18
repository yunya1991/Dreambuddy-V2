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


def test_transport_router_routes_execution_and_governance_to_http():
    mod = _load_module("workflows/trading-decision/transports/adapters.py")
    router = mod.TransportRouter(
        http=mod.HTTPTransport(base_url="http://example", sender=lambda url, payload, timeout_ms, headers=None: {"url": url, "headers": headers}),
        mq=mod.MockTransport(),
    )
    envelope = {
        "header": {"loop_type": "execution", "target": "A1", "type": "REQUEST", "trace_id": "t1"},
        "payload": {"trace_id": "t1"},
    }
    rsp = router.send_envelope(envelope)
    assert rsp["url"].endswith("/a1/research")
    envelope["header"]["loop_type"] = "governance"
    envelope["header"]["target"] = "A8"
    rsp2 = router.send_envelope(envelope)
    assert rsp2["url"].endswith("/a8/verification")


def test_transport_router_routes_intelligence_to_redis():
    mod = _load_module("workflows/trading-decision/transports/adapters.py")
    sent = []

    class FakeRedis(mod.RedisStreamsTransport):
        def __init__(self):
            pass

        def xadd(self, stream: str, fields: dict):
            sent.append((stream, fields))
            return {"status": "OK"}

    router = mod.TransportRouter(
        http=mod.HTTPTransport(base_url="http://example"),
        mq=FakeRedis(),
    )
    envelope = {
        "header": {"loop_type": "intelligence", "target": "A4", "type": "EVENT", "trace_id": "t2"},
        "payload": {"trace_id": "t2", "alert_level": "L1"},
    }
    router.send_envelope(envelope)
    assert sent
    assert sent[0][0] == "dream.intelligence.a6.L1"

