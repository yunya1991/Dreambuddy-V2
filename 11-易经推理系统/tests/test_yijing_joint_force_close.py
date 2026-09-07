#!/usr/bin/env python3
"""P2 回归测试：易经离场增加浮亏≥3% 且 risk>0.7 联合触发 FORCE_CLOSE。

背景：原 FORCE_CLOSE 阈值 risk≥0.80 过高，试错仓 risk 多在 0.4-0.6，
导致浮亏 -10% 仍不干预。新增联合条件填补 0.7<risk<0.8 且实际亏损的盲区。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.memory_l4.polling_trader import PollingTrader


def _trader():
    return PollingTrader.__new__(PollingTrader)


def test_joint_force_close_triggers_when_loss_and_high_risk():
    """浮亏≤-3% 且 risk>0.7 → 应升级 FORCE_CLOSE。"""
    t = _trader()
    assert t._should_joint_force_close(upl_ratio=-0.031, risk_score=0.71) is True


def test_joint_force_close_needs_both_conditions():
    """仅浮亏或仅高风险 → 不触发（必须同时满足）。"""
    t = _trader()
    # 浮亏够但 risk 不够
    assert t._should_joint_force_close(upl_ratio=-0.05, risk_score=0.69) is False
    # risk 够但浮亏不够
    assert t._should_joint_force_close(upl_ratio=-0.02, risk_score=0.85) is False
    # 盈利状态
    assert t._should_joint_force_close(upl_ratio=0.02, risk_score=0.9) is False


def test_joint_force_close_boundary():
    """边界：浮亏=-3% 或 risk=0.7 均不触发（严格大于/小于）。"""
    t = _trader()
    # 浮亏刚好=-3%（不满足 ≤-3%）且 risk=0.7（不满足 >0.7）→ 不触发
    assert t._should_joint_force_close(upl_ratio=-0.03, risk_score=0.7) is False
    # 浮亏<-3% 但 risk=0.7（不满足 >0.7）→ 不触发
    assert t._should_joint_force_close(upl_ratio=-0.0301, risk_score=0.7) is False
    # 浮亏<-3% 且 risk>0.7 → 触发
    assert t._should_joint_force_close(upl_ratio=-0.0301, risk_score=0.701) is True


if __name__ == "__main__":
    test_joint_force_close_triggers_when_loss_and_high_risk()
    test_joint_force_close_needs_both_conditions()
    test_joint_force_close_boundary()
    print("✅ P2 浮亏+风险联合 FORCE_CLOSE 测试通过")
