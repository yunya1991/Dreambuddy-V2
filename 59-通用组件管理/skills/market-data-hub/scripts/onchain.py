#!/usr/bin/env python3
"""D5 区块链公开数据：直连公共 RPC 自采区块，本地计算链上指标。

用法:
    python3 onchain.py --chain eth
    python3 onchain.py --chain eth --blocks 50 --json
    python3 onchain.py --version

数据源:
    公有链公共 RPC（ethereum.publicnode.com 主 / rpc.flashbots.net 备）。
    区块数据由节点公开提供、本地自行采集，不经第三方数据商再分发。

输出: Markdown 表格 + 五行尾注；--json 输出结构化结果。仅使用标准库。
"""

import argparse
import json
import math
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import cloud

VERSION = "1.0.0"
UA = {
    "User-Agent": "market-data-hub/1.0 (research; contact: ops@neodrm.com)",
    "Content-Type": "application/json",
}
LICENSE = "公有链数据自采（public chain, self-collected）"
LIMITS = "仅提供已上链区块的统计描述，不含价格、预测或建议。"
METHODS = ["M17"]

RPC = {
    "eth": ["https://ethereum.publicnode.com", "https://rpc.flashbots.net"],
}


def err_code(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return "E_HTTP_{}".format(exc.code)
    if isinstance(exc, ssl.SSLError):
        return "E_TLS"
    if isinstance(exc, (socket.timeout, TimeoutError, urllib.error.URLError)):
        return "E_NET"
    if isinstance(exc, ValueError):
        return "E_EMPTY"
    return "E_SCHEMA"


def rpc_call(url, payload, timeout=25):
    body = json.dumps(payload).encode("utf-8")
    for attempt in range(3):  # 最多重试 2 次，应对公共节点抖动
        try:
            req = urllib.request.Request(url, data=body, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError:
            if attempt == 2:
                raise
        except Exception:
            if attempt == 2:
                raise
        time.sleep(0.8 * (attempt + 1))


def latest_height(url):
    r = rpc_call(url, {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []})
    if "result" not in r:
        raise ValueError("rpc error: " + json.dumps(r.get("error", {}), ensure_ascii=False))
    return int(r["result"], 16)


def fetch_blocks(url, heights):
    """优先批量请求，失败时退化为逐个请求（最多 10 个）。"""
    batch = [
        {"jsonrpc": "2.0", "id": i + 1, "method": "eth_getBlockByNumber", "params": [hex(h), False]}
        for i, h in enumerate(heights)
    ]
    try:
        res = rpc_call(url, batch)
        blocks = [x.get("result") for x in res if isinstance(x, dict)]
        if sum(1 for b in blocks if b) >= max(1, len(heights) // 2):
            return [b for b in blocks if b]
    except Exception:
        pass
    out = []
    for h in heights[:10]:
        r = rpc_call(
            url,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_getBlockByNumber",
                "params": [hex(h), False],
            },
        )
        if r.get("result"):
            out.append(r["result"])
    if not out:
        raise ValueError("no block returned")
    return out


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def std(xs):
    if len(xs) < 2:
        return None
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def summarize(blocks):
    blocks = sorted(blocks, key=lambda b: int(b["number"], 16))
    ts = [int(b["timestamp"], 16) for b in blocks]
    intervals = [ts[i] - ts[i - 1] for i in range(1, len(ts))]
    ratios = [
        int(b["gasUsed"], 16) / int(b["gasLimit"], 16) for b in blocks if int(b["gasLimit"], 16)
    ]
    txs = [len(b.get("transactions", [])) for b in blocks]
    base = [int(b["baseFeePerGas"], 16) / 1e9 for b in blocks if b.get("baseFeePerGas")]
    n = len(blocks)
    return [
        {
            "metric": "区块高度",
            "value": int(blocks[-1]["number"], 16),
            "unit": "block",
            "n": n,
            "method_id": "M17",
        },
        {
            "metric": "出块间隔均值",
            "value": mean(intervals),
            "unit": "s",
            "n": len(intervals),
            "method_id": "M17",
        },
        {
            "metric": "出块间隔标准差",
            "value": std(intervals),
            "unit": "s",
            "n": len(intervals),
            "method_id": "M17",
        },
        {
            "metric": "gas 使用率均值",
            "value": mean(ratios),
            "unit": "ratio",
            "n": len(ratios),
            "method_id": "M17",
        },
        {
            "metric": "单块交易数均值",
            "value": mean(txs),
            "unit": "tx",
            "n": len(txs),
            "method_id": "M17",
        },
        {
            "metric": "base fee 均值",
            "value": mean(base),
            "unit": "gwei",
            "n": len(base),
            "method_id": "M17",
        },
    ], int(ts[-1])


def fmt(v, unit):
    if v is None:
        return "—"
    if unit == "ratio":
        return "{:.2%}".format(v)
    if unit == "gwei":
        return "{:.3f}".format(v)
    if isinstance(v, float):
        return "{:.2f}".format(v)
    return str(v)


def render(chain, rows, height, data_date, missing, channel="local"):
    lines = [
        "{} 链上事实 · 最新区块 {} · 生成于 {}".format(
            chain, height, datetime.now().strftime("%Y-%m-%d %H:%M")
        ),
        "",
        "| 指标 | 数值 | 单位 | 样本量 |",
        "|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            "| {} | {} | {} | {} |".format(
                r["metric"], fmt(r["value"], r["unit"]), r["unit"], r["n"]
            )
        )
    lines += [
        "",
        "方法ID：M17 链上区块指标",
        "数据源：公共 RPC 自采（publicnode 主 / flashbots 备）｜ 通道：{}".format(
            "云端" if channel == "cloud" else "本地直连"
        ),
        "许可：{}".format(LICENSE),
        "缺失：{}".format("、".join(missing) if missing else "无"),
        "说明：{}".format(LIMITS),
    ]
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description="区块链公开数据（D5）")
    p.add_argument("--chain", default="eth")
    p.add_argument("--blocks", type=int, default=50)
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--endpoint",
        default="auto",
        choices=["auto", "cloud", "local"],
        help="数据通道：auto 云端优先并自动回退本地",
    )
    p.add_argument("--version", action="version", version="market-data-hub " + VERSION)
    a = p.parse_args(argv)

    chain = a.chain.lower()
    if chain not in RPC:
        print("E_INPUT：暂不支持 {}，可选：{}".format(chain, ", ".join(RPC)), file=sys.stderr)
        return 2
    if a.blocks < 2 or a.blocks > 200:
        print("E_INPUT：--blocks 取值 2–200", file=sys.stderr)
        return 2

    rows, missing, height, data_date, used = [], [], None, None, "local"
    if a.endpoint != "local":
        payload = cloud.call("onchain", {"chain": chain, "blocks": a.blocks})
        if payload:
            rows = payload.get("rows", [])
            height = payload.get("height")
            data_date = payload.get("data_date")
            used = "cloud"
        elif a.endpoint == "cloud":
            print("数据不可用：云端通道不可用（{}）".format(cloud.describe()))
            return 1

    if used == "local":
        for url in RPC[chain]:
            try:
                h = latest_height(url)
                heights = list(range(h, max(h - a.blocks, 0), -1))
                blocks = fetch_blocks(url, heights)
                rows, ts = summarize(blocks)
                height = max(int(b["number"], 16) for b in blocks)
                data_date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                break
            except Exception as exc:
                missing.append(
                    {
                        "key": url.split("//")[-1].split("/")[0],
                        "code": err_code(exc),
                        "detail": type(exc).__name__,
                    }
                )

    if a.json:
        print(
            json.dumps(
                {
                    "skill": "market-data-hub",
                    "version": VERSION,
                    "module": "D5",
                    "chain": chain,
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "data_date": data_date,
                    "data_route": used,
                    "height": height,
                    "rows": rows,
                    "missing": [] if rows else missing,
                    "method_ids": METHODS,
                    "sources": [
                        {
                            "name": "Public RPC (self-collected)",
                            "url": "https://ethereum.publicnode.com",
                            "license": LICENSE,
                        }
                    ],
                    "limits": LIMITS,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if rows else 1

    if not rows:
        print("数据不可用：全部 RPC 获取失败（{}）".format("、".join(m["key"] for m in missing)))
        return 1
    print(render(chain, rows, height, data_date, [], used))
    return 0


if __name__ == "__main__":
    sys.exit(main())
