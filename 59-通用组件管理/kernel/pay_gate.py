#!/usr/bin/env python3
"""按次付费通道内核：402 挑战、Payment-Proof、幂等重试与响应收尾。

构建期由 tools/sync_kernel.py 注入到组件 `scripts/_kernel/`。
命令表、必填参数与重试命令拼接由各组件的 pay.py 自己维护。
"""

import argparse
import json
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request

from _kernel import headers

DEFAULT_TIMEOUT = 60.0
DEFAULT_RETRIES = 2

INVALID_PROOF = "ERR 支付凭证无效或已过期：请重新获取 Payment-Proof 后重试（同一订单不会重复扣费）"


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


def post(endpoint, payload, proof, timeout, ensure_ascii=True):
    body = json.dumps(payload, ensure_ascii=ensure_ascii).encode("utf-8")
    req_headers = {"content-type": "application/json", "accept": "application/json"}
    if proof:
        req_headers["Payment-Proof"] = proof
    req = urllib.request.Request(endpoint, data=body, headers=req_headers, method="POST")
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


def call(endpoint, payload, proof, timeout, retries, ensure_ascii=True):
    """无凭证的首次调用会产生新订单，禁止自动重试；带凭证重试是幂等的。"""
    attempts = 1 + (retries if proof else 0)
    for index in range(attempts):
        try:
            status, data = post(endpoint, payload, proof, timeout, ensure_ascii)
        except TransportError as exc:
            if (
                proof
                and index + 1 < attempts
                and exc.code in ("E_NET", "E_TIMEOUT", "E_SSL", "E_JSON")
            ):
                time.sleep(headers.backoff(index))
                continue
            raise
        if status >= 500 and proof and index + 1 < attempts:
            time.sleep(headers.backoff(index))
            continue
        return status, data
    raise TransportError("E_RETRY", "重试次数用尽，请稍后再试")


def print_payment_required(result, proof, retry_command, stream=None, error_stream=None):
    out = stream or sys.stdout
    err = error_stream or out
    if proof:
        print(INVALID_PROOF, file=err)
    else:
        print(
            "需要按次付费（金额 {} 元，订单 {}，请在 {} 前完成）".format(
                result.get("amount"), result.get("out_trade_no"), result.get("pay_before")
            ),
            file=out,
        )
        print(
            "  商品：{}（资源 {}）".format(
                result.get("goods_name") or "-", result.get("resource_id") or "-"
            ),
            file=out,
        )
        print("获取 Payment-Proof 的三种方式：", file=out)
        print("  1) 支付宝 AI 按量付费：按 Payment-Needed 账单完成支付后取回凭证；", file=out)
        print(
            "  2) 平台订单页：用订单号 {} 查询并复制凭证；".format(result.get("out_trade_no")),
            file=out,
        )
        print("  3) 让 Agent 从支付回调或支付结果邮件中读取凭证。", file=out)
    print("完成支付后重试（同一凭证重复提交不会重复扣费）：", file=out)
    print("  {}".format(retry_command), file=out)


def print_result(status, data, stream=None, hint_400=""):
    """非 402 的响应收尾：400 / 502 / 其他非 200 / 200。"""
    out = stream or sys.stdout
    if status == 400:
        print("ERR 请求被拒绝（HTTP 400）：{}".format(data.get("message") or data), file=out)
        if hint_400:
            print(hint_400, file=out)
        return 1
    if status == 502:
        print("ERR 服务暂不可用（HTTP 502）：{}".format(data.get("message") or data), file=out)
        print("结果可能已生成，请用同一 --proof 重试，不会重复扣费。", file=out)
        return 1
    if status != 200:
        print("调用失败（HTTP {}）：{}".format(status, data.get("message") or data), file=out)
        return 1
    print(json.dumps(data.get("content", data), ensure_ascii=False, indent=2))
    if data.get("already_fulfilled"):
        print("\n（该订单此前已交付，本次为幂等重放，未重复扣费）")
    return 0
