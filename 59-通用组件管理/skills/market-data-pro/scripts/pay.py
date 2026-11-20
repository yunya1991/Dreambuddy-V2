#!/usr/bin/env python3
"""数据服务专业版客户端：按次付费调用（HTTP 402 + Payment-Proof）。

用法:
    python3 pay.py --cmd macro --series DGS10,CPIAUCSL
    python3 pay.py --cmd quotes --symbols sh600519,hk00700
    python3 pay.py --cmd macro --series DGS10 --proof <Payment-Proof>

流程:
    1) 直接调用 → 服务端返回 402 + out_trade_no/amount/pay_before
    2) 按提示用支付宝完成支付，拿到 Payment-Proof
    3) 同一命令加 --proof 重试 → 200 返回结构化结果

仅使用标准库。环境变量 MDP_ENDPOINT 可覆盖默认地址。
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

ENDPOINT = os.environ.get("MDP_ENDPOINT", "https://www.neodrm.com/api/paid/data")
SKILL = "market-data-pro"
TIMEOUT = 60

COMMANDS = {
    "macro": ["series", "window"],
    "filings": ["ticker", "form", "limit", "facts"],
    "onchain": ["chain", "blocks"],
    "context": ["describe", "cross", "basket", "bucket", "peers", "window"],
    "quotes": ["symbols", "window"],
}


def post(payload, proof=None):
    body = json.dumps(payload).encode("utf-8")
    headers = {"content-type": "application/json", "accept": "application/json"}
    if proof:
        headers["Payment-Proof"] = proof
    req = urllib.request.Request(ENDPOINT, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"message": raw[:500]}


def main(argv=None):
    p = argparse.ArgumentParser(description="数据服务专业版（按次付费）")
    p.add_argument("--cmd", required=True, choices=sorted(COMMANDS))
    p.add_argument("--proof", default="", help="支付宝支付完成后返回的 Payment-Proof 头")
    args, extra = p.parse_known_args(argv)

    params = {}
    key = None
    for token in extra:
        if token.startswith("--"):
            key = token[2:]
            continue
        if key and key in COMMANDS[args.cmd]:
            params[key] = token
        key = None

    status, payload = post({"skill": SKILL, "cmd": args.cmd, "params": params}, args.proof or None)

    if status == 402:
        print("需要按次付费（金额 {} 元，订单 {}，请在 {} 前完成）".format(
            payload.get("amount"), payload.get("out_trade_no"), payload.get("pay_before")))
        print("完成支付后，将支付凭证通过 --proof 重试同一命令：")
        print("  python3 pay.py --cmd {} {} --proof <Payment-Proof>".format(
            args.cmd, " ".join("--{} {}".format(k, v) for k, v in params.items())))
        return 2

    if status != 200:
        print("调用失败（HTTP {}）：{}".format(status, payload.get("message") or payload))
        return 1

    print(json.dumps(payload.get("content", payload), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
