#!/usr/bin/env python3
"""验证器准确率评估脚本 — 用 gold set 校准验证器。

评估逻辑：
- Gold S/A/B → 期望 pass（高质量记忆应通过验证）
- Gold D → 期望 fail（低质量记忆应被检测出问题）
- Gold C → 模糊区，单独统计
- abstain 不计入准确率（验证器选择不判断）

用法:
  python3 evaluate_verifiers.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from verification_observer import GoldSetManager
from verifiers import (
    CycleConsistencyVerifier, FactualityVerifier, ApplicabilityVerifier,
)

GOLD_STORAGE = str(_SCRIPT_DIR.parent / "data" / "verification_observer")

# Gold quality → expected verdict
def expected_verdict(gold_quality: str) -> str:
    if gold_quality in ("S", "A", "B"):
        return "pass"
    elif gold_quality == "D":
        return "fail"
    return "borderline"  # C 档模糊


def evaluate_verifier(verifier, gold_entries: list) -> Dict:
    correct = 0
    wrong = 0
    abstain = 0
    total = 0
    # 按 gold 质量分级统计
    by_quality: Dict[str, Dict[str, int]] = {}

    for entry in gold_entries:
        exp = expected_verdict(entry.gold_quality)
        if exp == "borderline":
            continue  # C 档单独处理
        total += 1
        sig = verifier.verify(entry.content)
        verdict = sig.verdict

        q = entry.gold_quality
        if q not in by_quality:
            by_quality[q] = {"pass": 0, "fail": 0, "abstain": 0}
        by_quality[q][verdict] += 1

        if verdict == "abstain":
            abstain += 1
        elif verdict == exp:
            correct += 1
        else:
            wrong += 1

    judged = correct + wrong
    accuracy = correct / judged if judged > 0 else 0.0
    coverage = judged / total if total > 0 else 0.0

    return {
        "total": total,
        "correct": correct,
        "wrong": wrong,
        "abstain": abstain,
        "accuracy": round(accuracy, 4),
        "coverage": round(coverage, 4),
        "by_quality": by_quality,
    }


def main():
    gsm = GoldSetManager(storage_path=GOLD_STORAGE)
    entries = [gsm.get(mid) for mid in gsm.list_ids()]
    entries = [e for e in entries if e is not None]
    print(f"Gold Set 条目数: {len(entries)}")

    verifiers = [
        ("CycleConsistency", CycleConsistencyVerifier()),
        ("Factuality", FactualityVerifier()),
        ("Applicability", ApplicabilityVerifier()),
    ]

    print("\n" + "=" * 70)
    print(f"{'验证器':<20} {'准确率':>8} {'覆盖率':>8} {'正确':>6} {'错误':>6} {'弃权':>6}")
    print("-" * 70)

    for name, verifier in verifiers:
        result = evaluate_verifier(verifier, entries)
        print(
            f"{name:<20} {result['accuracy']:>8.1%} {result['coverage']:>8.1%} "
            f"{result['correct']:>6} {result['wrong']:>6} {result['abstain']:>6}"
        )
        # 按质量分级
        for q, stats in result["by_quality"].items():
            print(f"    {q}: pass={stats['pass']} fail={stats['fail']} abstain={stats['abstain']}")

    print("=" * 70)
    print("\n💡 调优建议：")
    print("  - 准确率低 → 调整检测规则/阈值")
    print("  - 弃权率高 → 放宽判断条件，减少 abstain")
    print("  - D 档 fail 检出率低 → 增强低质量检测模式")


if __name__ == "__main__":
    main()
