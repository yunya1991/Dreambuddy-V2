#!/usr/bin/env python3
"""本地沙箱：复刻 skillhub-audit-api 的付费协议（仅标准库）。

对齐的真实实现：services/skillhub-audit-api/src/app.js
- 402 + `Payment-Needed`（base64url 账单）→ 携带 `Payment-Proof` 重试 → 200
- 400 INVALID_REQUEST / 413 PAYLOAD_TOO_LARGE / 502 履约确认失败
- 同一 proof 重复提交返回首次结果（already_fulfilled=true）

故障注入（--mode）：
- ok        正常 402 / 验付 / 200
- html      200 但返回非 JSON（模拟网关错误页）
- 502       直接返回履约确认失败
- drop      直接断开连接（模拟网络中断）

沙箱专用凭证：sbx-ok 通过；sbx-invalid 视为凭证无效；sbx-502 触发 502。

用法:
    python3 sandbox/mock/paid_api.py --port 0 --mode ok --delay 0
    # 启动后打印 "PORT <数字>"，供 run_cases.py 读取
"""

import argparse
import base64
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "fixtures"

RESOURCE_PATHS = {"/api/paid/data": "data", "/api/paid/cogsteward": "cogsteward"}
PRICES = {"data": "2.99", "cogsteward": "0.99"}
GOODS = {"data": "数据服务专业版数据查询", "cogsteward": "认知管家工作区体检"}

ALLOWED = {
    "market-data-pro": ["macro", "filings", "onchain", "quotes"],
    "event-context": ["events", "event-context"],
    "market-data-hub": ["macro", "filings", "onchain"],
}

REQUIRED = {
    ("market-data-pro", "macro"): ["series"],
    ("market-data-pro", "quotes"): ["symbols"],
    ("market-data-pro", "filings"): ["ticker"],
    ("market-data-pro", "onchain"): ["chain"],
    ("event-context", "events"): ["subject"],
}

FIXTURES = {
    ("market-data-pro", "macro"): "macro.json",
    ("market-data-pro", "quotes"): "quotes.json",
    ("market-data-pro", "filings"): "filings.json",
    ("market-data-pro", "onchain"): "onchain.json",
    ("event-context", "events"): "events.json",
    ("event-context", "event-context"): "event-context.json",
}


def b64url(text):
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def load_fixture(name):
    with open(FIXTURE_DIR / name, "r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_data(body):
    skill = str(body.get("skill") or "").strip()
    cmd = str(body.get("cmd") or "").strip()
    if skill not in ALLOWED:
        return "skill 不支持：{}；可选 {}".format(skill or "(空)", " / ".join(ALLOWED))
    if cmd not in ALLOWED[skill]:
        return "cmd 不支持：{}；{} 可选 {}".format(cmd or "(空)", skill, " / ".join(ALLOWED[skill]))
    params = body.get("params") if isinstance(body.get("params"), dict) else {}
    for key in REQUIRED.get((skill, cmd), []):
        if not str(params.get(key) or "").strip():
            return "缺少必填参数：{}".format(key)
    return None


def validate_cogsteward(body):
    metrics = body.get("metrics")
    inventory = body.get("inventory")
    if not isinstance(metrics, dict) and not isinstance(inventory, dict):
        return "缺少可评估数据：metrics 或 inventory 至少提供一项"
    for section, value in (("metrics", metrics), ("inventory", inventory)):
        if value is None:
            continue
        if not isinstance(value, dict):
            return "{} 必须是对象".format(section)
        for key, item in value.items():
            if not isinstance(item, int) or isinstance(item, bool) or item < 0 or item > 1000000:
                return "{}.{} 必须是非负整数（≤1000000）".format(section, key)
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "SandboxPaidAPI/0.1"

    def log_message(self, *args):  # 静默访问日志
        pass

    def _send(self, status, body, headers=None, content_type="application/json; charset=utf-8"):
        raw = body if isinstance(body, bytes) else str(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def _json(self, status, payload, headers=None):
        self._send(status, json.dumps(payload, ensure_ascii=False), headers)

    def do_GET(self):
        state = self.server.state
        if self.path == "/health":
            return self._json(
                200, {"status": "ok", "service": "sandbox-paid-api", "mode": state["mode"]}
            )
        if self.path == "/__stats":
            with state["lock"]:
                return self._json(
                    200,
                    {
                        "requests": state["requests"],
                        "last_body": state["last_body"],
                        "last_proof": state["last_proof"],
                        "delivered": sorted(state["delivered"]),
                    },
                )
        return self._json(404, {"code": "NOT_FOUND", "message": "not found"})

    def do_POST(self):
        state = self.server.state
        mode = state["mode"]

        if mode == "drop":
            self.connection.close()
            return

        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length)
        if state["delay"]:
            time.sleep(state["delay"])

        with state["lock"]:
            state["requests"] += 1

        if len(raw) > 1024 * 1024:
            return self._json(
                413, {"code": "PAYLOAD_TOO_LARGE", "message": "请求体过大（上限 1MB）"}
            )

        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._json(400, {"code": "INVALID_REQUEST", "message": "请求体不是合法 JSON"})

        with state["lock"]:
            state["last_body"] = body

        path = self.path.split("?")[0]
        resource = RESOURCE_PATHS.get(path)
        if not resource:
            return self._json(404, {"code": "NOT_FOUND", "message": "未知资源 {}".format(path)})

        if mode == "html":
            return self._send(
                200, "<html><body>502 Bad Gateway (sandbox)</body></html>", content_type="text/html"
            )
        if mode == "502":
            return self._json(
                502,
                {
                    "code": "FULFILLMENT_CONFIRM_FAILED",
                    "message": "结果已生成但履约确认失败，请稍后使用同一 Payment-Proof 重试",
                },
            )

        error = validate_data(body) if resource == "data" else validate_cogsteward(body)
        if error:
            return self._json(400, {"code": "INVALID_REQUEST", "message": error})

        proof = (self.headers.get("Payment-Proof") or "").strip()
        with state["lock"]:
            state["last_proof"] = proof

        if not proof or proof == "sbx-invalid":
            return self._challenge(resource, body)
        if proof == "sbx-502":
            return self._json(
                502,
                {
                    "code": "FULFILLMENT_CONFIRM_FAILED",
                    "message": "结果已生成但履约确认失败，请稍后使用同一 Payment-Proof 重试",
                },
            )

        with state["lock"]:
            previous = state["delivered"].get(proof)
            if previous:
                return self._json(
                    200,
                    {
                        "resource_id": path,
                        "content": previous["content"],
                        "trade_no": previous["trade_no"],
                        "out_trade_no": previous["out_trade_no"],
                        "already_fulfilled": True,
                        "fulfillment_confirmed": True,
                    },
                )

        content = self._content(resource, body)
        out_trade_no = "PAY_{}_{:03d}".format(int(time.time() * 1000), state["counter"])
        state["counter"] += 1
        record = {
            "content": content,
            "trade_no": "SBXTRADE" + str(state["counter"]),
            "out_trade_no": out_trade_no,
        }
        with state["lock"]:
            state["delivered"][proof] = record

        return self._json(
            200,
            {
                "resource_id": path,
                "content": content,
                "trade_no": record["trade_no"],
                "out_trade_no": out_trade_no,
                "already_fulfilled": False,
                "fulfillment_confirmed": True,
            },
        )

    def _content(self, resource, body):
        if resource == "cogsteward":
            return load_fixture("cogsteward_report.json")
        skill = str(body.get("skill") or "").strip()
        cmd = str(body.get("cmd") or "").strip()
        name = FIXTURES.get((skill, cmd))
        if not name:
            return {
                "error": "NO_FIXTURE",
                "message": "沙箱未准备该命令的样本：{} / {}".format(skill, cmd),
            }
        return load_fixture(name)

    def _challenge(self, resource, body):
        state = self.server.state
        state["counter"] += 1
        out_trade_no = "PAY_{}_{:03d}".format(int(time.time() * 1000), state["counter"])
        pay_before = time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime(time.time() + 1800))
        bill = {
            "amount": PRICES[resource],
            "currency": "CNY",
            "goods_name": GOODS[resource],
            "out_trade_no": out_trade_no,
            "pay_before": pay_before,
            "resource_id": self.path,
            "seller_id": "2088000000000000",
            "service_id": "sbx_service_id",
        }
        with state["lock"]:
            state["pending"][out_trade_no] = {"bill": bill, "body": body}
        header = b64url(json.dumps(dict(bill, seller_signature="sbx-unsigned"), ensure_ascii=False))
        return self._json(
            402,
            {
                "code": "Payment-Needed",
                "message": "需要支付后返回结果",
                "out_trade_no": out_trade_no,
                "amount": bill["amount"],
                "currency": "CNY",
                "goods_name": bill["goods_name"],
                "resource_id": self.path,
                "pay_before": pay_before,
            },
            {"Payment-Needed": header},
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description="本地沙箱付费 API")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--mode", choices=["ok", "html", "502", "drop"], default="ok")
    parser.add_argument("--delay", type=float, default=0.0)
    args = parser.parse_args(argv)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.state = {
        "mode": args.mode,
        "delay": args.delay,
        "counter": 0,
        "requests": 0,
        "last_body": None,
        "last_proof": "",
        "delivered": {},
        "pending": {},
        "lock": threading.Lock(),
    }
    print("PORT {}".format(server.server_address[1]), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    sys.exit(main())
