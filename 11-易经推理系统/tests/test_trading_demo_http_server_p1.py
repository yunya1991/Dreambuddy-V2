import importlib.util
import json
from pathlib import Path
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(rel_path: str):
    path = REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_demo_http_server_accepts_envelope_and_persists(tmp_path: Path):
    mod = _load("scripts/trading_demo/http_server.py")
    server = mod.build_server(host="127.0.0.1", port=0, inbox_dir=tmp_path)
    try:
        host, port = server.server_address
        envelope = {"header": {"trace_id": "t1", "loop_type": "execution", "target": "A4"}, "payload": {"k": "v"}}
        req = Request(
            f"http://{host}:{port}/a4/validation",
            data=json.dumps(envelope).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=2) as resp:
            assert resp.status == 202

        written = list(tmp_path.glob("*.json"))
        assert written
        saved = json.loads(written[0].read_text(encoding="utf-8"))
        assert saved["header"]["trace_id"] == "t1"
    finally:
        server.shutdown()
        server.server_close()

