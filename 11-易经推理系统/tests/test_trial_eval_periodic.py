#!/usr/bin/env python3
"""P1 回归测试：轻仓试错评估改为定期重评估 + 放宽 reverse 阈值。

修复前：试错评估只跑一次（trial_eval_done 永久 True），reverse 阈值 -0.5% 太敏感。
修复后：每 60min 重评估一次，reverse 阈值放宽到 -3%（轻仓绝对亏损小，容忍噪音）。
"""
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.memory_l4.polling_trader import PollingTrader


def _trader():
    return PollingTrader.__new__(PollingTrader)


# ── 1. 试错动作判定阈值 ──

def test_trial_action_reverse_at_minus_3pct():
    """价格变动 ≤ -3% 判定 reverse（放宽后阈值）。"""
    t = _trader()
    assert t._compute_trial_action(-0.031) == "reverse"
    assert t._compute_trial_action(-0.03) == "reverse"   # 边界包含


def test_trial_action_maintain_between_thresholds():
    """-3% < 变动 < +1% 判定 maintain。"""
    t = _trader()
    assert t._compute_trial_action(-0.029) == "maintain"
    assert t._compute_trial_action(0.0) == "maintain"
    assert t._compute_trial_action(0.009) == "maintain"


def test_trial_action_confirm_at_plus_1pct():
    """价格变动 ≥ +1% 判定 confirm。"""
    t = _trader()
    assert t._compute_trial_action(0.01) == "confirm"
    assert t._compute_trial_action(0.05) == "confirm"


# ── 2. 定期重评估条件 ──

def test_trial_eval_skipped_before_30min():
    """持仓 < 30min 不评估。"""
    t = _trader()
    pos = SimpleNamespace(is_trial=True, last_trial_eval_ts=0.0)
    assert t._should_run_trial_eval(pos, position_age_sec=1799) is False


def test_trial_eval_runs_first_at_30min():
    """持仓 ≥ 30min 且从未评估 → 首次评估。"""
    t = _trader()
    pos = SimpleNamespace(is_trial=True, last_trial_eval_ts=0.0)
    assert t._should_run_trial_eval(pos, position_age_sec=1800) is True


def test_trial_eval_not_rerun_within_60min():
    """距上次评估 < 60min 不重评估。"""
    t = _trader()
    now = time.time()
    pos = SimpleNamespace(is_trial=True, last_trial_eval_ts=now - 3500)  # 58min前
    assert t._should_run_trial_eval(pos, position_age_sec=5400, now_ts=now) is False


def test_trial_eval_rerun_after_60min():
    """距上次评估 ≥ 60min 重评估。"""
    t = _trader()
    now = time.time()
    pos = SimpleNamespace(is_trial=True, last_trial_eval_ts=now - 3600)  # 60min前
    assert t._should_run_trial_eval(pos, position_age_sec=7200, now_ts=now) is True


def test_trial_eval_skips_non_trial():
    """非试错仓不评估。"""
    t = _trader()
    pos = SimpleNamespace(is_trial=False, last_trial_eval_ts=0.0)
    assert t._should_run_trial_eval(pos, position_age_sec=7200) is False


if __name__ == "__main__":
    test_trial_action_reverse_at_minus_3pct()
    test_trial_action_maintain_between_thresholds()
    test_trial_action_confirm_at_plus_1pct()
    test_trial_eval_skipped_before_30min()
    test_trial_eval_runs_first_at_30min()
    test_trial_eval_not_rerun_within_60min()
    test_trial_eval_rerun_after_60min()
    test_trial_eval_skips_non_trial()
    print("✅ P1 试错定期重评估 + 阈值放宽测试通过")
