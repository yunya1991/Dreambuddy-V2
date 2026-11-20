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

import argparse
import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request

DEFAULT_ENDPOINT = "https://www.neodrm.com/api/paid/cogsteward"
DEFAULT_TIMEOUT = 45.0
DEFAULT_RETRIES = 2


class ArgParser(argparse.ArgumentParser):
    """参数错误统一中文提示并返回退出码 1。"""

    def error(self, message):
        if message.startswith("unrecognized arguments:"):
            message = "未知参数：{}；请用 --help 查看可用参数".format(
                message.split(":", 1)[1].strip()
            )
        elif message.startswith("the following arguments are required:"):
            message = "缺少必填参数：{}".format(message.split(":", 1)[1].strip())
        print("ERR 参数错误：{}".format(message), file=sys.stderr)
        raise SystemExit(1)


class TransportError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def post(endpoint, payload, proof, timeout):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"content-type": "application/json", "accept": "application/json"}
    if proof:
        headers["Payment-Proof"] = proof
    req = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
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


def call(endpoint, payload, proof, timeout, retries):
    """无凭证的首次调用会产生新订单，禁止自动重试；带凭证重试是幂等的。"""
    attempts = 1 + (retries if proof else 0)
    for index in range(attempts):
        try:
            status, data = post(endpoint, payload, proof, timeout)
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


def print_payment_required(result, proof):
    if proof:
        print(
            "ERR 支付凭证无效或已过期：请重新获取 Payment-Proof 后重试（同一订单不会重复扣费）",
            file=sys.stderr,
        )
    else:
        print(
            "需要按次付费（金额 {} 元，订单 {}，请在 {} 前完成）".format(
                result.get("amount"), result.get("out_trade_no"), result.get("pay_before")
            )
        )
        print(
            "  商品：{}（资源 {}）".format(
                result.get("goods_name") or "-", result.get("resource_id") or "-"
            )
        )
        print("获取 Payment-Proof 的三种方式：")
        print("  1) 支付宝 AI 按量付费：按 Payment-Needed 账单完成支付后取回凭证；")
        print("  2) 平台订单页：用订单号 {} 查询并复制凭证；".format(result.get("out_trade_no")))
        print("  3) 让 Agent 从支付回调或支付结果邮件中读取凭证。")
    print("完成支付后重试（同一凭证重复提交不会重复扣费）：")
    print("  python3 pay.py --metrics '<同一份指标 JSON>' --proof <Payment-Proof>")


def main(argv=None):
    p = ArgParser(description="认知管家 Pro 按次付费客户端（仅发送指标 JSON）")
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
        status, result = call(
            args.endpoint, payload, args.proof.strip(), args.timeout, args.retries
        )
    except TransportError as exc:
        print("ERR {}：{}".format(exc.code, exc.message), file=sys.stderr)
        return 1

    if status == 402:
        print_payment_required(result, args.proof.strip())
        return 2

    if status == 400:
        print(
            "ERR 请求被拒绝（HTTP 400）：{}".format(result.get("message") or result),
            file=sys.stderr,
        )
        print("请检查指标 JSON 的字段与取值。", file=sys.stderr)
        return 1

    if status == 502:
        print(
            "ERR 服务暂不可用（HTTP 502）：{}".format(result.get("message") or result),
            file=sys.stderr,
        )
        print("结果可能已生成，请用同一 --proof 重试，不会重复扣费。", file=sys.stderr)
        return 1

    if status != 200:
        print(
            "调用失败（HTTP {}）：{}".format(status, result.get("message") or result),
            file=sys.stderr,
        )
        return 1

    print(json.dumps(result.get("content", result), ensure_ascii=False, indent=2))
    if result.get("already_fulfilled"):
        print("\n（该订单此前已交付，本次为幂等重放，未重复扣费）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
