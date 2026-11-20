#!/usr/bin/env python3
"""可装配指针清单（handoff 契约 v1.0）。

用法:
    python3 handoff.py --series DGS10,CPIAUCSL
    python3 handoff.py --series DGS10 --budget 500 --json
    python3 handoff.py --version

用途:
    把本包覆盖的数据对象转成「可装配指针」，装认知管家（CogSteward）的用户
    可直接交给 `cm pack` 按 token 预算装配最小上下文；未安装则按普通 JSON 使用。

约束:
    纯只读、不联网、不写文件；只输出指针与元数据，不含数值之外的解释。
"""

import argparse
import json
import sys

from _kernel import handoff

VERSION = "1.0.0"
HANDOFF_VERSION = handoff.HANDOFF_VERSION
LICENSE = "Public Domain"
SOURCE_NAME = "FRED / Federal Reserve Bank of St. Louis"
SOURCE_URL = "https://fred.stlouisfed.org/"
LIMITS = "仅提供可装配指针，不含判断与建议。"

REGISTRY = {
    "DGS10": ("美国10年期国债收益率", 40, ["M02", "M11", "M12", "M13"]),
    "DGS2": ("美国2年期国债收益率", 40, ["M02", "M11", "M12", "M13"]),
    "DGS3MO": ("美国3个月期国债收益率", 40, ["M02", "M11", "M12", "M13"]),
    "FEDFUNDS": ("联邦基金有效利率", 36, ["M02", "M11", "M12"]),
    "CPIAUCSL": ("美国CPI指数", 40, ["M02", "M11", "M12", "M14"]),
    "UNRATE": ("美国失业率", 36, ["M02", "M11", "M12"]),
    "GDPC1": ("美国实际GDP", 32, ["M11", "M12"]),
    "DTWEXBGS": ("美元贸易加权指数", 36, ["M02", "M11", "M12"]),
}


def build_items(series_list):
    items, missing = [], []
    for s in series_list:
        meta = REGISTRY.get(s)
        if not meta:
            missing.append({"key": s, "code": "E_INPUT", "detail": "未登记的序列"})
            continue
        name, _, methods = meta
        item = {
            "id": "series:" + s,
            "kind": "series",
            "title": name,
            "license": LICENSE,
            "url": "https://fred.stlouisfed.org/series/" + s,
            "method_ids": methods,
            "data_date": None,
        }
        item["estimated_tokens"] = handoff.estimate_tokens(item)
        items.append(item)
    return items, missing


def main(argv=None):
    p = argparse.ArgumentParser(description="可装配指针清单（handoff v1.0）")
    p.add_argument("--series", default="", help="序列，逗号分隔")
    p.add_argument("--budget", type=int, default=2000)
    p.add_argument("--json", action="store_true")
    p.add_argument("--version", action="version", version="market-data-hub " + VERSION)
    a = p.parse_args(argv)

    series_list = [x.strip() for x in a.series.split(",") if x.strip()]
    if not series_list:
        print("E_INPUT：--series 必填，如 DGS10,CPIAUCSL", file=sys.stderr)
        return 2
    if a.budget < 100:
        print("E_INPUT：--budget 不得小于 100", file=sys.stderr)
        return 2

    items, missing = build_items(series_list)
    picked, skipped, used = handoff.pack(items, a.budget)

    result = handoff.envelope(
        skill="market-data-hub",
        target="cogsteward/pack",
        budget=a.budget,
        items=picked,
        missing=missing,
        skipped=skipped,
        used=used,
        limits=LIMITS,
    )

    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            "可装配指针 · target={} · 预算 {} tokens · 已用 {}".format(
                result["target"], a.budget, used
            )
        )
        print("")
        print("| id | 标题 | 许可 | token | 方法ID |")
        print("|---|---|---|---|---|")
        for it in picked:
            print(
                "| {} | {} | {} | {} | {} |".format(
                    it["id"],
                    it["title"],
                    it["license"],
                    it["estimated_tokens"],
                    ",".join(it["method_ids"]),
                )
            )
        if missing:
            print("")
            print("缺失：{}".format("、".join(m["key"] for m in missing)))
        print("")
        print("说明：{}".format(LIMITS))

    return 0 if picked else 1


if __name__ == "__main__":
    sys.exit(main())
