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

import json
import os
import re
import sys

from _kernel import pay_gate

ENDPOINT = os.environ.get("ECP_ENDPOINT", "https://www.neodrm.com/api/paid/data")
SKILL = "event-context"
DEFAULT_TIMEOUT = pay_gate.DEFAULT_TIMEOUT
DEFAULT_RETRIES = pay_gate.DEFAULT_RETRIES

COMMANDS = {
    "events": ["subject", "since", "types", "feed", "limit"],
    "event-context": ["subject", "event-id", "feed", "latest"],
}
EXAMPLES = {
    "events": "--cmd events --subject AAPL --since 30",
    "event-context": "--cmd event-context --subject AAPL --latest",
}
FORM_PATTERN = re.compile(r"^\d{1,2}-[A-Z]{1,3}(/[A-Z])?$")


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
    pay_gate.print_payment_required(payload, args.proof, build_retry_command(args, params))


def main(argv=None):
    parser = pay_gate.ArgParser(description="事件上下文专业版（按次付费）")
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
        status, data = pay_gate.call(
            ENDPOINT, payload, args.proof.strip(), args.timeout, args.retries
        )
    except pay_gate.TransportError as exc:
        print("ERR {}：{}".format(exc.code, exc.message))
        return 1

    if status == 402:
        print_payment_required(data, args, params)
        return 2

    return pay_gate.print_result(status, data, hint_400="请检查参数写法（python3 pay.py --help）。")


if __name__ == "__main__":
    sys.exit(main())
