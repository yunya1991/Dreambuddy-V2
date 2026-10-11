#!/usr/bin/env python3
"""P4 F6 验收脚本: 训练效果可度量+阈值自动调优。

验收标准:
  - F6: 可查询辅导质量分、纠正次数、训练成果提升
  - TrainingMetrics: 质量分(0-100) + 纠正次数 + 提升幅度
  - PatternMiner: 跨案例模式挖掘
  - FeedbackLoop: 阈值自动调优
"""
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_CORE_DIR = os.path.join(_34_DIR, "core")

for _p in [_THIS_DIR, _34_DIR, _CORE_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def main():
    print("=" * 60)
    print("F6 验收: 训练效果可度量+阈值自动调优")
    print("=" * 60)

    # ── 验收 1: 辅导质量分 ────────────────────────────────
    print("\n[1] 辅导质量分 (0-100):")
    from training_metrics import TrainingMetrics

    metrics = TrainingMetrics()

    # 完全一致 → 100
    perfect = metrics.calculate_quality_score(
        rea_patterns=["recursion", "greedy"],
        trained_patterns=["recursion", "greedy"],
        rea_call_chain=["f1", "f2"],
        trained_call_chain=["f1", "f2"],
    )
    print(f"  完全一致: score={perfect}")
    assert perfect == 100.0
    print("  ✅ 完全一致 → 100")

    # 部分一致
    partial = metrics.calculate_quality_score(
        rea_patterns=["a", "b", "c"],
        trained_patterns=["a", "b"],
        rea_call_chain=["x", "y"],
        trained_call_chain=["x"],
    )
    print(f"  部分一致: score={partial}")
    assert 0 < partial < 100
    print("  ✅ 部分一致 → 0-100")

    # 完全不一致 → 0
    zero = metrics.calculate_quality_score(
        rea_patterns=["a"],
        trained_patterns=["b"],
        rea_call_chain=["x"],
        trained_call_chain=["y"],
    )
    print(f"  完全不一致: score={zero}")
    assert zero == 0.0
    print("  ✅ 完全不一致 → 0")

    # ── 验收 2: 纠正次数 ─────────────────────────────────
    print("\n[2] 纠正次数:")
    metrics.record_correction("pattern_mismatch", "缺少递归模式")
    metrics.record_correction("path_divergence", "执行路径偏移")
    print(f"  纠正次数: {metrics.get_correction_count()}")
    print(f"  纠正记录: {metrics.get_corrections()}")
    assert metrics.get_correction_count() == 2
    print("  ✅ 纠正次数统计正常")

    # ── 验收 3: 训练成果提升 ──────────────────────────────
    print("\n[3] 训练成果提升:")
    metrics.set_before_score(40.0)
    metrics.set_after_score(75.0)
    delta = metrics.get_improvement_delta()
    print(f"  训练前: 40.0, 训练后: 75.0, 提升: {delta}")
    print(f"  是否提升: {metrics.is_improved()}")
    assert delta == 35.0
    assert metrics.is_improved()
    print("  ✅ 训练成果提升可度量")

    # ── 验收 4: 跨案例模式挖掘 ────────────────────────────
    print("\n[4] 跨案例模式挖掘:")
    from training_metrics import PatternMiner

    miner = PatternMiner()
    cases = [
        {"patterns": ["recursion", "greedy"], "source": "cognitive"},
        {"patterns": ["recursion", "iteration"], "source": "cognitive"},
        {"patterns": ["recursion", "divide_conquer"], "source": "skill"},
    ]
    common = miner.mine_common_patterns(cases)
    top = miner.mine_top_patterns(cases, top_n=2)
    print(f"  共同模式: {common}")
    print(f"  Top-2: {top}")
    assert common["recursion"] == 3
    assert top[0][0] == "recursion"
    print("  ✅ 跨案例模式挖掘正常")

    # ── 验收 5: 阈值自动调优 ──────────────────────────────
    print("\n[5] 阈值自动调优:")
    from training_metrics import FeedbackLoop

    # 高质量 → 放宽
    loop_high = FeedbackLoop(initial_novelty_threshold=0.6)
    loop_high.record_training_quality(85.0)
    loop_high.record_training_quality(90.0)
    adjusted_high = loop_high.get_adjusted_thresholds()
    print(f"  高质量训练后阈值: novelty={adjusted_high['novelty_threshold']}")
    assert adjusted_high["novelty_threshold"] <= 0.6
    print("  ✅ 高质量 → 放宽阈值")

    # 低质量 → 收紧
    loop_low = FeedbackLoop(initial_novelty_threshold=0.6)
    loop_low.record_training_quality(30.0)
    loop_low.record_training_quality(25.0)
    adjusted_low = loop_low.get_adjusted_thresholds()
    print(f"  低质量训练后阈值: novelty={adjusted_low['novelty_threshold']}")
    assert adjusted_low["novelty_threshold"] >= 0.6
    print("  ✅ 低质量 → 收紧阈值")

    # ── 总结 ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("F6 验收: ✅ PASS")
    print("  训练效果可度量，支持阈值自动调优")
    print("  - 辅导质量分(0-100) ✅")
    print("  - 纠正次数统计 ✅")
    print("  - 训练成果提升 ✅")
    print("  - 跨案例模式挖掘 ✅")
    print("  - 阈值自动调优 ✅")
    return True


if __name__ == "__main__":
    result = main()
    sys.exit(0 if result else 1)
