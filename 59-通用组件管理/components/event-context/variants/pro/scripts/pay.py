#!/usr/bin/env python3
"""事件上下文专业版客户端：按次付费调用（HTTP 402 + Payment-Proof）。

用法:
    python3 pay.py --cmd events --subject AAPL --since 30
    python3 pay.py --cmd event-context --subject AAPL --latest
    python3 pay.py --cmd events --subject AAPL --since 30 --proof <Payment-Proof>
    python3 pay.py --cmd events --subject AAPL --describe   # 只打印请求体，不联网

流程:
    1) 直接调用 → 服务端返回 402 + out_trade_no/amount/pay_before
    2) 按提示用支付宝完成支付，拿到 Payment-Proof
    3) 同一命令加 --proof 重试 → 200 返回结构化结果（同一凭证不重复计费）

仅使用标准库。环境变量 ECP_ENDPOINT 可覆盖默认地址。
退出码：0 成功 / 2 需要支付 / 1 参数或调用失败
"""

import argparse
import json
import os
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request

ENDPOINT = os.environ.get("ECP_ENDPOINT", "https://www.neodrm.com/api/paid/data")
SKILL = "event-context"
DEFAULT_TIMEOUT = 60.0
DEFAULT_RETRIES = 2

COMMANDS = {
    "events": ["subject", "since", "types", "feed", "limit"],
    "event-context": ["subject", "event-id", "feed", "latest"],
}
EXAMPLES = {
    "events": "--cmd events --subject AAPL --since 30",
    "event-context": "--cmd event-context --subject AAPL --latest",
}
FORM_PATTERN = re.compile(r"^\d{1,2}-[A-Z]{1,3}(/[A-Z])?$")


class ArgParser(argparse.ArgumentParser):
    """参数错误统一中文提示并返回退出码 1（argparse 默认是 2 且是英文）。"""

    def error(self, message):
        if message.startswith("unrecognized arguments:"):
            message = "未知参数：{}；请用 --help 查看可用参数".format(
                message.split(":", 1)[1].strip()
            )
        elif message.startswith("the following arguments are required:"):
            message = "缺少必填参数：{}".format(message.split(":", 1)[1].strip())
        elif message.startswith("argument --cmd: invalid choice"):
            message = "未知命令：{}".format(message.split("invalid choice:", 1)[-1].strip())
        print("ERR 参数错误：{}".format(message), file=sys.stderr)
        raise SystemExit(1)


class TransportError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def post(payload, proof, timeout):
    body = json.dumps(payload).encode("utf-8")
    headers = {"content-type": "application/json", "accept": "application/json"}
    if proof:
        headers["Payment-Proof"] = proof
    req = urllib.request.Request(ENDPOINT, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError as exc:
                raise TransportError(
                    "E_JSON",
                    "服务返回格式不是 JSON（前 120 字符）：{}".format(" ".join(raw.split())[:120]),
                ) from exc
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"message": raw[:300]}
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            raise TransportError(
                "E_TIMEOUT",
                "网络超时（{} 秒）：目标无响应，可增大 --timeout 后重试".format(timeout),
            ) from exc
        raise TransportError(
            "E_NET", "网络连接失败：{}（请检查网络或代理后重试）".format(reason)
        ) from exc
    except (socket.timeout, TimeoutError):
        raise TransportError(
            "E_TIMEOUT", "网络超时（{} 秒）：目标无响应，可增大 --timeout 后重试".format(timeout)
        ) from None
    except ssl.SSLError as exc:
        raise TransportError(
            "E_SSL", "TLS 握手失败：{}（请检查证书或代理设置）".format(exc)
        ) from exc


def call(payload, proof, timeout, retries):
    """无凭证的首次调用会产生新订单，禁止自动重试；带凭证重试是幂等的。"""
    attempts = 1 + (retries if proof else 0)
    for index in range(attempts):
        try:
            status, data = post(payload, proof, timeout)
        except TransportError as exc:
            if (
                proof
                and index + 1 < attempts
                and exc.code in ("E_NET", "E_TIMEOUT", "E_SSL", "E_JSON")
            ):
                time.sleep(0.3 * (index + 1))
                continue
            raise
        if status >= 500 and proof and index + 1 < attempts:
            time.sleep(0.3 * (index + 1))
            continue
        return status, data
    raise TransportError("E_RETRY", "重试次数用尽，请稍后再试")


def collect_params(parser, args):
    allowed = COMMANDS[args.cmd]
    raw = {
        "subject": args.subject,
        "since": args.since,
        "types": args.types,
        "feed": args.feed,
        "limit": args.limit,
        "event-id": args.event_id,
        "latest": args.latest,
    }
    params = {}
    for key, value in raw.items():
        if value is None or value is False:
            continue
        if key not in allowed:
            parser.error(
                "参数 --{} 不适用于 cmd {}（可用：--{}）".format(
                    key, args.cmd, "、--".join(allowed)
                )
            )
        params[key] = True if key == "latest" else str(value)

    if args.cmd == "events" and not params.get("subject"):
        parser.error("缺少必填参数 --subject（示例：python3 pay.py {}）".format(EXAMPLES["events"]))
    if args.cmd == "event-context" and not (params.get("subject") or params.get("event-id")):
        parser.error(
            "缺少必填参数：--subject 或 --event-id（示例：python3 pay.py {}）".format(
                EXAMPLES["event-context"]
            )
        )

    for key in ("since", "limit"):
        if key in params and (not params[key].isdigit() or int(params[key]) <= 0):
            parser.error("--{} 必须是正整数".format(key))
    if "types" in params:
        for token in params["types"].split(","):
            if not FORM_PATTERN.match(token.strip()):
                parser.error("--types 取值不合法：{}（示例：8-K,10-Q）".format(token))
    return params


def build_retry_command(args, params):
    parts = ["python3", "pay.py", "--cmd", args.cmd]
    for key in COMMANDS[args.cmd]:
        if key == "latest":
            if params.get("latest"):
                parts.append("--latest")
            continue
        if key in params:
            parts.extend(["--{}".format(key), params[key]])
    parts.extend(["--proof", "<Payment-Proof>"])
    return " ".join(parts)


def print_payment_required(payload, args, params):
    if args.proof:
        print("ERR 支付凭证无效或已过期：请重新获取 Payment-Proof 后重试（同一订单不会重复扣费）")
    else:
        print(
            "需要按次付费（金额 {} 元，订单 {}，请在 {} 前完成）".format(
                payload.get("amount"), payload.get("out_trade_no"), payload.get("pay_before")
            )
        )
        print(
            "  商品：{}（资源 {}）".format(
                payload.get("goods_name") or "-", payload.get("resource_id") or "-"
            )
        )
        print("获取 Payment-Proof 的三种方式：")
        print("  1) 支付宝 AI 按量付费：按 Payment-Needed 账单完成支付后取回凭证；")
        print("  2) 平台订单页：用订单号 {} 查询并复制凭证；".format(payload.get("out_trade_no")))
        print("  3) 让 Agent 从支付回调或支付结果邮件中读取凭证。")
    print("完成支付后重试（同一凭证重复提交不会重复扣费）：")
    print("  {}".format(build_retry_command(args, params)))


def main(argv=None):
    parser = ArgParser(description="事件上下文专业版（按次付费）")
    parser.add_argument("--cmd", required=True, choices=sorted(COMMANDS), help="事件命令")
    parser.add_argument("--proof", default="", help="支付宝支付完成后返回的 Payment-Proof 头")
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT, help="单次请求超时秒数（默认 60）"
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help="带凭证时的重试次数（默认 2；无凭证不重试）",
    )
    parser.add_argument("--describe", action="store_true", help="只打印将发送的请求体，不联网")
    parser.add_argument("--subject", help="主体代码，如 AAPL；event-context 也可只给 event-id")
    parser.add_argument("--event-id", dest="event_id", help="事件哈希；可配合 --feed 反查")
    parser.add_argument("--since", help="events：回看天数（正整数）")
    parser.add_argument("--types", help="events：表单类型，逗号分隔，如 8-K,10-Q")
    parser.add_argument("--feed", help="事件源，如 sec / fed")
    parser.add_argument("--limit", help="返回条数（正整数）")
    parser.add_argument("--latest", action="store_true", help="event-context：装配最近一次事件")
    args = parser.parse_args(argv)

    if args.timeout <= 0:
        parser.error("--timeout 必须大于 0")
    if args.retries < 0:
        parser.error("--retries 不能为负数")

    params = collect_params(parser, args)
    payload = {"skill": SKILL, "cmd": args.cmd, "params": params}

    if args.describe:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    try:
        status, data = call(payload, args.proof.strip(), args.timeout, args.retries)
    except TransportError as exc:
        print("ERR {}：{}".format(exc.code, exc.message))
        return 1

    if status == 402:
        print_payment_required(data, args, params)
        return 2

    if status == 400:
        print("ERR 请求被拒绝（HTTP 400）：{}".format(data.get("message") or data))
        print("请检查参数写法（python3 pay.py --help）。")
        return 1

    if status == 502:
        print("ERR 服务暂不可用（HTTP 502）：{}".format(data.get("message") or data))
        print("结果可能已生成，请用同一 --proof 重试，不会重复扣费。")
        return 1

    if status != 200:
        print("调用失败（HTTP {}）：{}".format(status, data.get("message") or data))
        return 1

    print(json.dumps(data.get("content", data), ensure_ascii=False, indent=2))
    if data.get("already_fulfilled"):
        print("\n（该订单此前已交付，本次为幂等重放，未重复扣费）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
