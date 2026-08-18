import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        inbox_dir: Path = self.server.inbox_dir
        content_length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(content_length)
        envelope = json.loads(raw.decode("utf-8"))

        inbox_dir.mkdir(parents=True, exist_ok=True)
        trace_id = str((envelope.get("header") or {}).get("trace_id") or "no-trace")
        ts = int(time.time() * 1000)
        out_path = inbox_dir / f"{trace_id}-{ts}.json"
        out_path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")

        body = json.dumps({"status": "ACCEPTED", "path": self.path}).encode("utf-8")
        self.send_response(202)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


class DemoHTTPServer(HTTPServer):
    def __init__(self, server_address, handler_cls, inbox_dir: Path):
        super().__init__(server_address, handler_cls)
        self.inbox_dir = inbox_dir
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()


def build_server(*, host: str, port: int, inbox_dir: Path) -> DemoHTTPServer:
    return DemoHTTPServer((host, port), _Handler, inbox_dir=inbox_dir)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--inbox-dir", default="artifacts/trading/http_inbox")
    args = parser.parse_args()

    server = build_server(host=args.host, port=args.port, inbox_dir=Path(args.inbox_dir))
    try:
        server._thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
