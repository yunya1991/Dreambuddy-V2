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


def test_redis_streams_transport_xadd_encodes_envelope():
    mod = _load_module("workflows/trading-decision/transports/adapters.py")
    sent = {}

    class FakeRedis(mod.RedisStreamsTransport):
        def __init__(self):
            pass

        def _execute(self, *parts):
            sent["parts"] = parts
            return ["1690000000-1"]

    tp = FakeRedis()
    envelope = {
        "header": {"loop_type": "intelligence", "target": "A4", "type": "EVENT", "trace_id": "t1"},
        "payload": {"trace_id": "t1", "alert_level": "L1"},
    }
    stream = tp.topic_for_envelope(envelope)
    tp.send_envelope(envelope)
    assert stream == "dream.intelligence.a6.L1"
    assert sent["parts"][0] == "XADD"

