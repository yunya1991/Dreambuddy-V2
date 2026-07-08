import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load(rel_path: str):
    path = REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def main() -> int:
    server_mod = _load("scripts/trading_demo/http_server.py")
    adapters = _load("workflows/trading-decision/transports/adapters.py")

    inbox = REPO_ROOT / "artifacts" / "trading" / "http_inbox"
    server = server_mod.build_server(host="127.0.0.1", port=0, inbox_dir=inbox)
    try:
        host, port = server.server_address
        tp = adapters.HTTPTransport(base_url=f"http://{host}:{port}")
        env = {
            "header": {"trace_id": "trace-demo-1", "loop_type": "execution", "target": "A4", "type": "EVENT"},
            "payload": {"trace_id": "trace-demo-1", "max_drawdown_pct": 1.2, "position_ratio": 0.25, "stop_loss_pct": 1.5},
        }
        rsp = tp.send_envelope(env)
        print(json.dumps(rsp, ensure_ascii=False))
        print(str(inbox))
        return 0
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())

