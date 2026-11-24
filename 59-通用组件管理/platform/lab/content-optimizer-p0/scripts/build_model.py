#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 samples.csv + go_no_go.json 生成 optimizer_model.json（确定性）。

口径来源：docs/SPEC-20261124-内容优化引擎-content-optimizer-P0可行性验证-v0.1.md
  - §17.3 门禁降级：G1 ∧ G2 ∧ G5 全通过才允许使用统计权重（gate_status=evidence）
  - §17.4 No-Go 默认行为：证据不足时 weight=0、source=prior、规则照常输出
  - §17.5 模型文件契约

约束：
  - 只读 samples.csv / analysis/go_no_go.json，只写 model/optimizer_model.json；
  - 同输入必得同输出（generated_at 除外）；
  - 缺失特征记 null，禁止补 0。

用法：
    cd platform/lab/content-optimizer-p0 && python3 scripts/build_model.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_DIR = os.path.join(BASE_DIR, "scripts")
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import analyze_p0b as p0b  # noqa: E402

MODEL_DIR = os.path.join(BASE_DIR, "model")
MODEL_PATH = os.path.join(MODEL_DIR, "optimizer_model.json")
GO_NO_GO_PATH = os.path.join(BASE_DIR, "analysis", "go_no_go.json")
SCHEMA_VERSION = "1.0"
CN_TZ = timezone(timedelta(hours=8))
WEIGHT_GATES = ("G1", "G2", "G5")

# 先验规则：与统计权重解耦，gate_status=no_signal 时同样输出。
PRIOR_RULES = [
    {
        "id": "title_len",
        "platform": "xiaohongshu",
        "source": "prior",
        "text": "标题 16–24 字，前 8 字放冲突或数字",
    },
    {
        "id": "title_hook",
        "platform": "xiaohongshu",
        "source": "prior",
        "text": "标题用问句或数字开头",
    },
    {
        "id": "hashtag_band",
        "platform": "xiaohongshu",
        "source": "prior",
        "text": "话题 3–6 个，命中赛道关键词",
    },
    {
        "id": "body_len",
        "platform": "xiaohongshu",
        "source": "prior",
        "text": "正文 ≥300 字，首段先给结论",
    },
    {
        "id": "douyin_first3s",
        "platform": "douyin",
        "source": "prior",
        "text": "视频前 3 秒必须有字幕或口播钩子",
    },
    {
        "id": "douyin_hashtag",
        "platform": "douyin",
        "source": "prior",
        "text": "话题 ≤3 个，优先视频而非图文",
    },
    {
        "id": "publish_window",
        "platform": "all",
        "source": "prior",
        "text": "优先 08–12 点或 20–22 点发布",
    },
]


def _now() -> str:
    return datetime.now(CN_TZ).isoformat(timespec="seconds")


def gate_status_of(gates: dict) -> str:
    """G1 ∧ G2 ∧ G5 全通过 → evidence；否则 no_signal。"""
    for gate in WEIGHT_GATES:
        if not (gates.get(gate) or {}).get("pass"):
            return "no_signal"
    return "evidence"


def _features_for(per_feature: list[dict], platform: str, evidence_ok: bool) -> list[dict]:
    rows = [f for f in per_feature if f.get("platform") == platform and f.get("controllable")]
    if not evidence_ok:
        return [
            {
                "name": f.get("feature"),
                "n": f.get("n"),
                "rho": f.get("rho"),
                "status": f.get("status") or "insufficient",
                "weight": 0.0,
                "source": "prior",
            }
            for f in rows
        ]

    total = sum(
        abs(float(f.get("rho") or 0.0))
        for f in rows
        if f.get("qualified") and f.get("rho") is not None
    )
    out = []
    for f in rows:
        qualified = bool(f.get("qualified")) and f.get("rho") is not None
        weight = round(abs(float(f["rho"])) / total, 4) if qualified and total else 0.0
        out.append(
            {
                "name": f.get("feature"),
                "n": f.get("n"),
                "rho": f.get("rho"),
                "status": f.get("status") or "insufficient",
                "weight": weight,
                "source": "evidence" if weight else "prior",
            }
        )
    return out


def build_model(
    rows: list[dict], prep_info: dict, gates: dict, verdict: str, generated_at: str | None = None
) -> dict:
    """由已构建行、预处理信息与门禁结果拼装模型字典（纯函数，便于测试）。"""
    evidence_ok = gate_status_of(gates) == "evidence"
    per_feature = ((gates.get("G2") or {}).get("evidence") or {}).get("per_feature") or []
    deduped_by_platform = {
        platform: int((prep_info.get("deduped_by_platform") or {}).get(platform, 0))
        for platform in p0b.PLATFORMS
    }
    platforms = {}
    for platform in p0b.PLATFORMS:
        platforms[platform] = {
            "n": deduped_by_platform[platform],
            "features": _features_for(per_feature, platform, evidence_ok),
            "rules": [dict(rule) for rule in PRIOR_RULES if rule["platform"] in (platform, "all")],
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "version": 1,
        "generated_at": generated_at or _now(),
        "gate_status": "evidence" if evidence_ok else "no_signal",
        "verdict": verdict or ("Go" if evidence_ok else "No-Go"),
        "source": {
            "rows": int(prep_info.get("raw_total") or len(rows)),
            "deduped": int(prep_info.get("deduped_total") or len(rows)),
            "by_platform": deduped_by_platform,
        },
        "platforms": platforms,
        "rules": [dict(rule) for rule in PRIOR_RULES],
    }


def write_model(model: dict, path: str = MODEL_PATH) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(model, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return path


def load_gates(path: str = GO_NO_GO_PATH) -> tuple[dict, str]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("gates") or {}, data.get("verdict") or ""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="生成 optimizer_model.json")
    parser.add_argument("--samples", default=p0b.SAMPLES_PATH, help="样本 CSV 路径")
    parser.add_argument("--go-no-go", default=GO_NO_GO_PATH, help="go_no_go.json 路径")
    parser.add_argument("--out", default=MODEL_PATH, help="模型输出路径")
    args = parser.parse_args(argv)

    p0b.SAMPLES_PATH = args.samples
    rows, prep_info = p0b.build_rows()
    gates, verdict = load_gates(args.go_no_go)
    model = build_model(rows, prep_info, gates, verdict)
    path = write_model(model, args.out)
    print(
        json.dumps(
            {
                "out": path,
                "gate_status": model["gate_status"],
                "verdict": model["verdict"],
                "rows": model["source"]["rows"],
                "deduped": model["source"]["deduped"],
                "by_platform": model["source"]["by_platform"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
