#!/usr/bin/env python3
"""数据服务专业版客户端：按次付费调用（HTTP 402 + Payment-Proof）。

用法:
    python3 pay.py --cmd macro --series DGS10,CPIAUCSL
    python3 pay.py --cmd quotes --symbols sh600519,hk00700
    python3 pay.py --cmd macro --series DGS10 --proof <Payment-Proof>
    python3 pay.py --cmd macro --series DGS10 --describe   # 只打印请求体，不联网

流程:
    1) 直接调用 → 服务端返回 402 + out_trade_no/amount/pay_before
    2) 按提示用支付宝完成支付，拿到 Payment-Proof
    3) 同一命令加 --proof 重试 → 200 返回结构化结果（同一凭证不重复计费）

仅使用标准库。环境变量 MDP_ENDPOINT 可覆盖默认地址。
退出码：0 成功 / 2 需要支付 / 1 参数或调用失败
"""

import json
import os
import sys

from _kernel import pay_gate

ENDPOINT = os.environ.get("MDP_ENDPOINT", "https://www.neodrm.com/api/paid/data")
SKILL = "market-data-pro"
DEFAULT_TIMEOUT = pay_gate.DEFAULT_TIMEOUT
DEFAULT_RETRIES = pay_gate.DEFAULT_RETRIES

COMMANDS = {
    "macro": ["series", "window"],
    "filings": ["ticker", "form", "limit", "facts"],
    "onchain": ["chain", "blocks"],
    "quotes": ["symbols", "window"],
}
REQUIRED = {
    "macro": "series",
    "filings": "ticker",
    "onchain": "chain",
    "quotes": "symbols",
}
EXAMPLES = {
    "macro": "--cmd macro --series DGS10,CPIAUCSL",
    "filings": "--cmd filings --ticker AAPL --form 10-K --limit 5",
    "onchain": "--cmd onchain --chain bitcoin --blocks 144",
    "quotes": "--cmd quotes --symbols sh600519,hk00700",
}


def collect_params(parser, args):
    params = {}
    allowed = COMMANDS[args.cmd]
    for key in sorted({key for keys in COMMANDS.values() for key in keys}):
        value = getattr(args, key)
        if value is None:
            continue
        if key not in allowed:
            parser.error(
                "参数 --{} 不适用于 cmd {}（可用：--{}）".format(
                    key, args.cmd, "、--".join(allowed)
                )
            )
        params[key] = str(value)

    missing = REQUIRED.get(args.cmd)
    if missing and not params.get(missing):
        parser.error(
            "缺少必填参数 --{0}（示例：python3 pay.py {1}）".format(
                missing, EXAMPLES.get(args.cmd, "")
            )
        )
    for key in ("limit", "blocks"):
        if key in params and (not params[key].isdigit() or int(params[key]) <= 0):
            parser.error("--{} 必须是正整数".format(key))
    return params


def build_retry_command(args, params):
    parts = ["python3", "pay.py", "--cmd", args.cmd]
    for key in COMMANDS[args.cmd]:
        if key in params:
            parts.extend(["--{}".format(key), params[key]])
    parts.extend(["--proof", "<Payment-Proof>"])
    return " ".join(parts)


def print_payment_required(payload, args, params):
    pay_gate.print_payment_required(payload, args.proof, build_retry_command(args, params))


def main(argv=None):
    parser = pay_gate.ArgParser(description="数据服务专业版（按次付费）")
    parser.add_argument("--cmd", required=True, choices=sorted(COMMANDS), help="数据命令")
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
    parser.add_argument("--series", help="macro：逗号分隔的序列，如 DGS10,CPIAUCSL")
    parser.add_argument("--window", help="时间窗口，如 30d / 3m / 1y")
    parser.add_argument("--ticker", help="filings：股票代码，如 AAPL")
    parser.add_argument("--form", help="filings：表单类型，如 10-K / 10-Q / 8-K")
    parser.add_argument("--limit", help="filings：返回条数（正整数）")
    parser.add_argument("--facts", help="filings：指定字段，逗号分隔")
    parser.add_argument("--symbols", help="quotes：逗号分隔的代码，如 sh600519,hk00700")
    parser.add_argument("--chain", help="onchain：链名，如 bitcoin")
    parser.add_argument("--blocks", help="onchain：统计区块数（正整数）")
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
