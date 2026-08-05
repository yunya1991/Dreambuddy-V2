#!/usr/bin/env python3
"""
认知回测验证统一框架 — TDD 红阶段
验证 P1-1(episodic_block) / P1-2(salience_score) / P1-3(全局广播) 三项更新的价值。

对齐 COGNITIVE_ARCHITECTURE.md §5.5 认知回测验证框架：
  - 每项更新必须通过 A/B 对比验证价值
  - path_advantage ≥ +0.2 才允许落地（报告+告警，不强制回滚）
  - 复用 evaluation_engine.compute_path_advantage / decide_learning_action
"""

import sys
from pathlib import Path
from dataclasses import dataclass, asdict, is_dataclass
from typing import List, Dict, Any

sys.path.insert(0, str(Path(__file__).parent))


def test_backtest_result_dataclass():
    """BacktestResult 数据类应存在且字段完整。"""
    from cognitive_backtest import BacktestResult

    assert is_dataclass(BacktestResult), "BacktestResult 应是 dataclass"
    # 构造一个实例验证字段
    r = BacktestResult(
        update_id="P1-test",
        update_name="test_update",
        metrics_a={"recall_calls": 100},
        metrics_b={"recall_calls": 40},
        path_advantage=0.6,
        decision="upgrade",
        reason="recall 调用减少 60%",
        sample_size=100,
        passed=True,
    )
    d = asdict(r)
    for key in ["update_id", "update_name", "metrics_a", "metrics_b",
                "path_advantage", "decision", "reason", "sample_size", "passed"]:
        assert key in d, f"BacktestResult 缺少字段 {key}"

    print("✅ test_backtest_result_dataclass 通过")
    return True


def test_backtest_p1_1_returns_result():
    """P1-1 episodic_block 回测应返回 BacktestResult。"""
    from cognitive_backtest import backtest_p1_1_episodic_block, BacktestResult

    result = backtest_p1_1_episodic_block()
    assert isinstance(result, BacktestResult), f"应返回 BacktestResult，实际 {type(result)}"
    assert result.update_id == "P1-1", f"update_id 应为 P1-1，实际 {result.update_id}"
    assert result.update_name == "episodic_block", f"update_name 应为 episodic_block"
    assert isinstance(result.metrics_a, dict), "metrics_a 应为 dict"
    assert isinstance(result.metrics_b, dict), "metrics_b 应为 dict"
    assert -1.0 <= result.path_advantage <= 1.0, \
        f"path_advantage 应在 [-1.0, 1.0]，实际 {result.path_advantage}"
    assert result.sample_size > 0, f"sample_size 应 > 0，实际 {result.sample_size}"

    print(f"✅ test_backtest_p1_1_returns_result 通过 (path_advantage={result.path_advantage:.3f})")
    return True


def test_backtest_p1_2_returns_result():
    """P1-2 salience_score 回测应返回 BacktestResult。"""
    from cognitive_backtest import backtest_p1_2_salience_score, BacktestResult

    result = backtest_p1_2_salience_score()
    assert isinstance(result, BacktestResult), f"应返回 BacktestResult，实际 {type(result)}"
    assert result.update_id == "P1-2", f"update_id 应为 P1-2，实际 {result.update_id}"
    assert result.update_name == "salience_score", f"update_name 应为 salience_score"
    assert -1.0 <= result.path_advantage <= 1.0, \
        f"path_advantage 应在 [-1.0, 1.0]，实际 {result.path_advantage}"

    print(f"✅ test_backtest_p1_2_returns_result 通过 (path_advantage={result.path_advantage:.3f})")
    return True


def test_backtest_p1_3_returns_result():
    """P1-3 全局广播回测应返回 BacktestResult。"""
    from cognitive_backtest import backtest_p1_3_global_broadcast, BacktestResult

    result = backtest_p1_3_global_broadcast()
    assert isinstance(result, BacktestResult), f"应返回 BacktestResult，实际 {type(result)}"
    assert result.update_id == "P1-3", f"update_id 应为 P1-3，实际 {result.update_id}"
    assert result.update_name == "global_broadcast", f"update_name 应为 global_broadcast"
    assert -1.0 <= result.path_advantage <= 1.0, \
        f"path_advantage 应在 [-1.0, 1.0]，实际 {result.path_advantage}"

    print(f"✅ test_backtest_p1_3_returns_result 通过 (path_advantage={result.path_advantage:.3f})")
    return True


def test_run_all_returns_list():
    """run_all 应返回 List[BacktestResult]，包含 5 项（P1-1/2/3 + P2-9/P2-7）。"""
    from cognitive_backtest import run_all, BacktestResult

    results = run_all()
    assert isinstance(results, list), f"应返回 list，实际 {type(results)}"
    assert len(results) == 5, f"应包含 5 项结果，实际 {len(results)}"
    for r in results:
        assert isinstance(r, BacktestResult), "每个元素应为 BacktestResult"
    ids = [r.update_id for r in results]
    assert ids == ["P1-1", "P1-2", "P1-3", "P2-9", "P2-7"], \
        f"update_id 顺序应为 P1-1/2/3 + P2-9/P2-7，实际 {ids}"

    print(f"✅ test_run_all_returns_list 通过 ({len(results)} 项)")
    return True


def test_p2_9_active_inference_runs():
    """P2-9 事前预测回测可运行"""
    from cognitive_backtest import backtest_p2_9_active_inference
    result = backtest_p2_9_active_inference()
    assert result.update_id == "P2-9"
    assert -1.0 <= result.path_advantage <= 1.0
    return True


def test_p2_7_rumination_runs():
    """P2-7 反刍回测可运行"""
    from cognitive_backtest import backtest_p2_7_rumination
    result = backtest_p2_7_rumination()
    assert result.update_id == "P2-7"
    assert -1.0 <= result.path_advantage <= 1.0
    return True


def test_path_advantage_in_range():
    """所有回测的 path_advantage 应在 [-1.0, 1.0]。"""
    from cognitive_backtest import run_all

    results = run_all()
    for r in results:
        assert -1.0 <= r.path_advantage <= 1.0, \
            f"{r.update_id} path_advantage={r.path_advantage} 超出 [-1.0, 1.0]"

    print("✅ test_path_advantage_in_range 通过")
    return True


def test_decision_valid():
    """所有 decision 应在 upgrade/alert/quarantine/observe 中。"""
    from cognitive_backtest import run_all

    valid = {"upgrade", "alert", "quarantine", "observe"}
    results = run_all()
    for r in results:
        assert r.decision in valid, \
            f"{r.update_id} decision={r.decision} 不在 {valid} 中"

    print("✅ test_decision_valid 通过")
    return True


def test_p1_2_reduces_recall_calls():
    """P1-2 salience_score 回测应显示 recall 调用减少（metrics_b < metrics_a）。"""
    from cognitive_backtest import backtest_p1_2_salience_score

    result = backtest_p1_2_salience_score()
    a_calls = result.metrics_a.get("recall_calls", 0)
    b_calls = result.metrics_b.get("recall_calls", 0)
    # 若无历史数据（sample_size==0），跳过断言
    if result.sample_size > 0:
        assert b_calls <= a_calls, \
            f"salience 过滤后 recall 调用应减少: A={a_calls}, B={b_calls}"
        assert result.path_advantage >= 0, \
            f"salience 减少调用应产生非负 path_advantage: {result.path_advantage}"

    print(f"✅ test_p1_2_reduces_recall_calls 通过 (A={a_calls}, B={b_calls})")
    return True


def test_print_report_runs():
    """print_report 应能正常运行，不抛异常。"""
    from cognitive_backtest import run_all, print_report

    results = run_all()
    # 只验证不抛异常
    print_report(results)
    print("✅ test_print_report_runs 通过")
    return True


if __name__ == "__main__":
    tests = [
        test_backtest_result_dataclass,
        test_backtest_p1_1_returns_result,
        test_backtest_p1_2_returns_result,
        test_backtest_p1_3_returns_result,
        test_run_all_returns_list,
        test_p2_9_active_inference_runs,
        test_p2_7_rumination_runs,
        test_path_advantage_in_range,
        test_decision_valid,
        test_p1_2_reduces_recall_calls,
        test_print_report_runs,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            if t():
                passed += 1
        except Exception as e:
            failed += 1
            print(f"❌ {t.__name__} 失败: {type(e).__name__}: {e}")
    print(f"\n{'='*60}")
    print(f"总计: {passed} 通过, {failed} 失败")
    sys.exit(0 if failed == 0 else 1)
