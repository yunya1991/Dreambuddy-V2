#!/usr/bin/env python3
"""Alertmanager -> Feishu 告警接收器（alert_only，无自动动作）。

接口：
  GET  /healthz
  POST /alert?level=P0|P1|P2|P3   Alertmanager v4 webhook
  POST /notify                    {"level":"P1","text":"..."} 供 watchdog 使用
仅监听 127.0.0.1；凭证从 /etc/dreambuddy-monitoring/monitoring.env 读取。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ENV_FILE = os.environ.get("MONITORING_ENV", "/etc/dreambuddy-monitoring/monitoring.env")
LISTEN = os.environ.get("RECEIVER_LISTEN", "127.0.0.1:9098")
TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
MSG_URL = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
LEVEL_COLOR = {"P0": "red", "P1": "orange", "P2": "yellow", "P3": "blue"}

_lock = threading.Lock()
_dedup: dict[str, float] = {}
_token_cache: dict[str, float | str] = {"value": "", "exp": 0.0}


def _load_env() -> dict[str, str]:
    # systemd 以 root 读取 EnvironmentFile 注入进程环境；进程本身以 luke 运行，
    # 直接读 600 root 文件会失败，因此优先使用环境变量，文件仅作兜底。
    data: dict[str, str] = {
        k: v for k, v in os.environ.items() if k.startswith(("FEISHU_", "RECEIVER_", "DEDUP_"))
    }
    try:
        with open(ENV_FILE, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    data.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except OSError as exc:
        if not data:
            print(f"[receiver] env load failed: {exc}", file=sys.stderr)
    return data


ENV = _load_env()
COOLDOWN = int(ENV.get("DEDUP_COOLDOWN", "1800"))
CHAT = {
    "P0": ENV.get("FEISHU_CHAT_RISK", ""),
    "P1": ENV.get("FEISHU_CHAT_DESK", ""),
    "P2": ENV.get("FEISHU_CHAT_DESK", ""),
    "P3": ENV.get("FEISHU_CHAT_MANAGEMENT", ""),
}


def _token() -> str:
    now = time.time()
    if _token_cache["value"] and float(_token_cache["exp"]) > now + 60:
        return str(_token_cache["value"])
    payload = json.dumps(
        {"app_id": ENV.get("FEISHU_APP_ID", ""), "app_secret": ENV.get("FEISHU_APP_SECRET", "")}
    ).encode()
    req = urllib.request.Request(
        TOKEN_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read().decode())
    if body.get("code") != 0:
        raise RuntimeError(f"token failed: {body.get('code')} {body.get('msg')}")
    _token_cache["value"] = body["tenant_access_token"]
    _token_cache["exp"] = now + int(body.get("expire", 7200))
    return str(_token_cache["value"])


def _send(level: str, text: str) -> bool:
    chat_id = CHAT.get(level) or CHAT["P1"]
    if not chat_id:
        print(f"[receiver] no chat_id for {level}", file=sys.stderr)
        return False
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": LEVEL_COLOR.get(level, "grey"),
            "title": {"tag": "plain_text", "content": f"[{level}] DreamBuddy 监控告警"},
        },
        "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": text}}],
    }
    payload = json.dumps(
        {"receive_id": chat_id, "msg_type": "interactive", "content": json.dumps(card)}
    ).encode()
    req = urllib.request.Request(
        MSG_URL,
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {_token()}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
        return body.get("code") == 0
    except (urllib.error.URLError, RuntimeError) as exc:
        print(f"[receiver] send failed: {exc}", file=sys.stderr)
        return False


def _fingerprint(alert: dict) -> str:
    labels = alert.get("labels") or {}
    raw = json.dumps(labels, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _format(alert: dict) -> str:
    labels = alert.get("labels") or {}
    ann = alert.get("annotations") or {}
    status = "恢复" if alert.get("status") == "resolved" else "触发"
    lines = [
        f"**状态**: {status}",
        f"**告警**: {labels.get('alertname', '-')}",
        f"**级别**: {labels.get('severity', '-')}",
        f"**对象**: {labels.get('cell', labels.get('job', labels.get('instance', '-')))}",
        f"**摘要**: {ann.get('summary', '-')}",
        f"**开始**: {alert.get('startsAt', '-')}",
    ]
    runbook = ann.get("runbook_url")
    if runbook:
        lines.append(f"**Runbook**: {runbook}")
    return "\n".join(lines)


class Handler(BaseHTTPRequestHandler):
    server_version = "dreambuddy-receiver/1.0"

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        print(f"[receiver] {fmt % args}", file=sys.stderr)

    def _json(self, code: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?")[0] == "/healthz":
            self._json(200, {"status": "ok", "credential": bool(ENV.get("FEISHU_APP_SECRET"))})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"error": "invalid json"})
            return

        path, _, query = self.path.partition("?")
        if path == "/notify":
            level = str(body.get("level", "P1")).upper()
            text = str(body.get("text", ""))[:3500]
            if level not in CHAT or not text:
                self._json(400, {"error": "level/text invalid"})
                return
            self._json(200 if _send(level, text) else 502, {"sent": True})
            return

        if path != "/alert":
            self._json(404, {"error": "not found"})
            return

        level = "P1"
        for part in query.split("&"):
            if part.startswith("level="):
                level = part.split("=", 1)[1].upper()
        if level not in CHAT:
            level = "P1"

        accepted = suppressed = failed = 0
        now = time.time()
        for alert in body.get("alerts") or []:
            fp = _fingerprint(alert)
            resolved = alert.get("status") == "resolved"
            with _lock:
                last = _dedup.get(fp, 0.0)
                if not resolved and now - last < COOLDOWN:
                    suppressed += 1
                    continue
                _dedup[fp] = now
            if _send(level, _format(alert)):
                accepted += 1
            else:
                failed += 1
        self._json(
            200 if failed == 0 else 502,
            {"accepted": accepted, "suppressed": suppressed, "failed": failed},
        )


def main() -> int:
    host, _, port = LISTEN.partition(":")
    if not ENV.get("FEISHU_APP_SECRET"):
        print("[receiver] FEISHU_APP_SECRET missing; alerts will not be delivered", file=sys.stderr)
    server = ThreadingHTTPServer((host, int(port)), Handler)
    print(f"[receiver] listening on {LISTEN}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
