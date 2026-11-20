#!/usr/bin/env python3
"""纯 HTTP 客户端：把调用方显式提供的指标 JSON 发给体检服务。

安全边界：
- 不遍历目录、不读取任何文档、不访问 .cm 数据库；
- 唯一输入是命令行里的 --metrics JSON（或显式指定的 --metrics-file）；
- 唯一网络目标是体检察看服务，不发送本机路径、文件名或正文。

用法:
    python3 pay.py --metrics '{"metrics":{"broken_links":2},"inventory":{"documents":50}}'
    python3 pay.py --metrics '{"..."}' --proof <Payment-Proof>
    python3 pay.py --metrics '{"..."}' --describe   # 只打印请求体，不联网

退出码：0 成功 / 2 需付款（402）/ 1 失败
"""

import json
import os
import sys

from _kernel import pay_gate

DEFAULT_ENDPOINT = "https://www.neodrm.com/api/paid/cogsteward"
DEFAULT_TIMEOUT = 45.0
DEFAULT_RETRIES = pay_gate.DEFAULT_RETRIES
RETRY_COMMAND = "python3 pay.py --metrics '<同一份指标 JSON>' --proof <Payment-Proof>"


def print_payment_required(result, proof):
    pay_gate.print_payment_required(result, proof, RETRY_COMMAND, error_stream=sys.stderr)


def main(argv=None):
    p = pay_gate.ArgParser(description="认知管家 Pro 按次付费客户端（仅发送指标 JSON）")
    p.add_argument(
        "--metrics", required=True, help='指标 JSON，例如 {"metrics":{...},"inventory":{...}}'
    )
    p.add_argument("--metrics-file", default="", help="可选：从显式指定文件读取同一份 JSON")
    p.add_argument("--proof", default="", help="支付宝支付完成后返回的 Payment-Proof 头")
    p.add_argument("--endpoint", default=os.environ.get("COGSTEWARD_ENDPOINT", DEFAULT_ENDPOINT))
    p.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT, help="单次请求超时秒数（默认 45）"
    )
    p.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help="带凭证时的重试次数（默认 2；无凭证不重试）",
    )
    p.add_argument("--describe", action="store_true", help="只打印将发送的请求体，不联网")
    args = p.parse_args(argv)

    if args.timeout <= 0:
        p.error("--timeout 必须大于 0")
    if args.retries < 0:
        p.error("--retries 不能为负数")

    raw = args.metrics
    if args.metrics_file:
        with open(args.metrics_file, "r", encoding="utf-8") as fh:
            raw = fh.read()

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print("ERR --metrics 不是合法 JSON：{}".format(exc), file=sys.stderr)
        return 1

    if args.describe:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    try:
        status, result = pay_gate.call(
            args.endpoint,
            payload,
            args.proof.strip(),
            args.timeout,
            args.retries,
            ensure_ascii=False,
        )
    except pay_gate.TransportError as exc:
        print("ERR {}：{}".format(exc.code, exc.message), file=sys.stderr)
        return 1

    if status == 402:
        print_payment_required(result, args.proof.strip())
        return 2

    return pay_gate.print_result(
        status,
        result,
        stream=sys.stderr,
        hint_400="请检查指标 JSON 的字段与取值。",
    )


if __name__ == "__main__":
    sys.exit(main())
