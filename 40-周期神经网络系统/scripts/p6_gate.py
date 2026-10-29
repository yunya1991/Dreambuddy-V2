#!/usr/bin/env python3
"""P6 神经网络深度学习阶段门槛守卫（SPEC_encoder_trend_classifier v0.2 红线 5）。
预注册门槛（禁止运行时放宽）：
  - P5 门槛达标（p5_gate_status.json all_passed == true，即 P1-P5 完成验证）
  - E0 token 序列样本量（token_sequence.parquet 行数）≥ 2000
  - E1 LightGBM 基线固化（baseline_metrics.json 存在且含 accuracy 与 direction_ic 字段）
未达标时 P6 训练入口拒绝启动，输出缺口报告 p6_gate_status.json。
红线：门槛为预注册值，本模块不提供任何绕过参数。
E2 及以后必须以 P1-P5 完成验证为前置门禁，禁止提前训练。
"""
import json
import os
import sys
from datetime import datetime, timezone

BASE = "/home/luke/dreambuddy/40-周期神经网络系统"
P5_GATE_STATUS = os.path.join(BASE, "p5_gate_status.json")
TOKEN_SEQUENCE = os.path.join(BASE, "token_sequence.parquet")
BASELINE_METRICS = os.path.join(BASE, "baseline_metrics.json")
GATE_STATUS_OUT = os.path.join(BASE, "p6_gate_status.json")

# 预注册门槛（禁止调整）
MIN_TOKEN_SAMPLES = 2000


def _load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _count_parquet_rows(path):
    """统计 parquet 行数；pyarrow 不可用时返回 -1（视为未达标并标注原因）。"""
    if not os.path.exists(path):
        return 0, "file_not_found"
    try:
        import pyarrow.parquet as pq
        n = pq.read_metadata(path).num_rows
        return n, "ok"
    except Exception as e:
        return -1, f"read_error: {e}"


def check_gate() -> dict:
    """检查 P6 三项前置条件，返回门槛报告。"""
    p5 = _load_json(P5_GATE_STATUS)
    p5_passed = bool(p5.get("all_passed", False))

    token_n, token_note = _count_parquet_rows(TOKEN_SEQUENCE)
    token_passed = token_n >= MIN_TOKEN_SAMPLES

    baseline = _load_json(BASELINE_METRICS)
    baseline_passed = (
        isinstance(baseline, dict)
        and "accuracy" in baseline
        and "direction_ic" in baseline
    )

    items = [
        {
            "name": "p5_gate_passed",
            "current": {
                "all_passed": p5_passed,
                "decision": p5.get("decision", "unknown"),
            },
            "required": "p5_gate_status.all_passed == true",
            "passed": p5_passed,
            "gap": 0 if p5_passed else 1,
        },
        {
            "name": "e0_token_samples",
            "current": token_n,
            "note": token_note,
            "required": MIN_TOKEN_SAMPLES,
            "passed": token_passed,
            "gap": max(0, MIN_TOKEN_SAMPLES - token_n) if token_n >= 0 else MIN_TOKEN_SAMPLES,
        },
        {
            "name": "e1_baseline_frozen",
            "current": {
                "exists": bool(baseline),
                "has_accuracy": "accuracy" in baseline if isinstance(baseline, dict) else False,
                "has_direction_ic": "direction_ic" in baseline if isinstance(baseline, dict) else False,
            },
            "required": "baseline_metrics.json 含 accuracy 与 direction_ic",
            "passed": baseline_passed,
            "gap": 0 if baseline_passed else 1,
        },
    ]
    all_passed = all(i["passed"] for i in items)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "module": "P6 门槛守卫（预注册，禁止放宽）",
        "items": items,
        "all_passed": all_passed,
        "decision": "ALLOW_TRAINING" if all_passed else "REJECT_TRAINING",
        "note": (
            "门槛全部达标，P6 训练入口开放（E2 小模型训练解锁）"
            if all_passed
            else "门槛未达标，P6 训练入口拒绝启动（SPEC_encoder v0.2 红线 5：E2 及以后必须以 P1-P5 完成验证为前置门禁）"
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
