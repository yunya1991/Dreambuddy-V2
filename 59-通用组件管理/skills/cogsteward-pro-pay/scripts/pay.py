#!/usr/bin/env python3
"""纯 HTTP 客户端：把调用方显式提供的指标 JSON 发给体检服务。

安全边界：
- 不遍历目录、不读取任何文档、不访问 .cm 数据库；
- 唯一输入是命令行里的 --metrics JSON（或显式指定的 --metrics-file）；
- 唯一网络目标是体检察看服务，不发送本机路径、文件名或正文。

用法:
    python3 pay.py --metrics '{"metrics":{"broken_links":2},"inventory":{"documents":50}}'
    python3 pay.py --metrics '{"..."}' --proof <Payment-Proof>

退出码：0 成功 / 2 需付款（402）/ 1 失败
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_ENDPOINT = "https://www.neodrm.com/api/paid/cogsteward"
TIMEOUT = 45


def post(endpoint, payload, proof=None):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"content-type": "application/json", "accept": "application/json"}
    if proof:
        headers["Payment-Proof"] = proof
    req = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
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
    p = argparse.ArgumentParser(description="认知管家 Pro 按次付费客户端（仅发送指标 JSON）")
    p.add_argument(
        "--metrics", required=True, help='指标 JSON，例如 {"metrics":{...},"inventory":{...}}'
    )
    p.add_argument("--metrics-file", default="", help="可选：从显式指定文件读取同一份 JSON")
    p.add_argument("--proof", default="", help="支付宝支付完成后返回的 Payment-Proof 头")
    p.add_argument("--endpoint", default=os.environ.get("COGSTEWARD_ENDPOINT", DEFAULT_ENDPOINT))
    args = p.parse_args(argv)

    raw = args.metrics
    if args.metrics_file:
        with open(args.metrics_file, "r", encoding="utf-8") as fh:
            raw = fh.read()

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print("ERR --metrics 不是合法 JSON：{}".format(exc), file=sys.stderr)
        return 1

    status, result = post(args.endpoint, payload, args.proof.strip() or None)

    if status == 402:
        print(
            "需要按次付费（金额 {} 元，订单 {}，请在 {} 前完成）".format(
                result.get("amount"), result.get("out_trade_no"), result.get("pay_before")
            )
        )
        print("完成支付后，将支付凭证通过 --proof 重试同一命令。")
        return 2

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
