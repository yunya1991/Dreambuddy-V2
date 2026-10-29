#!/usr/bin/env python3
"""P5 统计学习阶段门槛守卫（SPEC v0.3 验收标准第 7 条）。

预注册样本量门槛（禁止运行时放宽）：
  - 矛盾事件（contradiction_events.jsonl）≥ 200 条
  - 语义事件（semantic_events.jsonl）≥ 1000 条
  - X1 门槛达标（x1_metrics_status.json gate.x1_ready == true）

未达标时 P5 训练入口拒绝启动，输出缺口报告 p5_gate_status.json。
红线：门槛为预注册值，本模块不提供任何绕过参数。
"""
import json
import os
import sys
from datetime import datetime, timezone

BASE = "/home/luke/dreambuddy"
D39 = os.path.join(BASE, "39-金融语义蒸馏系统")
D40 = os.path.join(BASE, "40-周期神经网络系统")

CONTRADICTION_EVENTS = os.path.join(D39, "contradiction_events.jsonl")
SEMANTIC_EVENTS = os.path.join(D39, "semantic_events.jsonl")
X1_STATUS = os.path.join(D40, "x1_metrics_status.json")
GATE_STATUS_OUT = os.path.join(D40, "p5_gate_status.json")

# 预注册门槛（SPEC v0.2 风险 7b，禁止调整）
MIN_CONTRADICTION = 200
MIN_SEMANTIC = 1000


def _count_lines(path: str) -> int:
    if not os.path.exists(path):
        return 0
    n = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                n += 1
    return n


def _load_x1() -> dict:
    try:
        with open(X1_STATUS, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def check_gate() -> dict:
    """检查 P5 三项前置条件，返回门槛报告。"""
    contradiction_n = _count_lines(CONTRADICTION_EVENTS)
    semantic_n = _count_lines(SEMANTIC_EVENTS)
    x1 = _load_x1()
    gate = x1.get("gate", {}) if isinstance(x1, dict) else {}

    items = [
        {
            "name": "contradiction_events",
            "current": contradiction_n,
            "required": MIN_CONTRADICTION,
            "passed": contradiction_n >= MIN_CONTRADICTION,
            "gap": max(0, MIN_CONTRADICTION - contradiction_n),
        },
        {
            "name": "semantic_events",
            "current": semantic_n,
            "required": MIN_SEMANTIC,
            "passed": semantic_n >= MIN_SEMANTIC,
            "gap": max(0, MIN_SEMANTIC - semantic_n),
        },
        {
            "name": "x1_gate",
            "current": {
                "samples": gate.get("samples", 0),
                "min_samples": gate.get("min_samples", 100),
                "weeks": gate.get("weeks", 0),
                "min_weeks": gate.get("min_weeks", 2),
                "x1_ready": bool(gate.get("x1_ready", False)),
            },
            "required": "x1_ready == true",
            "passed": bool(gate.get("x1_ready", False)),
            "gap": 0 if gate.get("x1_ready") else 1,
        },
    ]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "module": "P5 门槛守卫（预注册，禁止放宽）",
        "items": items,
        "all_passed": all(i["passed"] for i in items),
        "decision": "ALLOW_TRAINING" if all(i["passed"] for i in items) else "REJECT_TRAINING",
        "note": (
            "门槛全部达标，P5 训练入口开放"
            if all(i["passed"] for i in items)
            else "门槛未达标，P5 训练入口拒绝启动（SPEC v0.3 验收标准第 7 条）"
        ),
    }
    return report


def save_report(report: dict) -> None:
    with open(GATE_STATUS_OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


def main() -> int:
    report = check_gate()
    save_report(report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # 退出码：0=放行，1=拦截（供训练入口调用方判断）
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
