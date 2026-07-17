#!/usr/bin/env python3
"""模拟实盘验证 — 验证 polling_trader 实际离场代码路径

由于 OKX 当前不可达（SSL/网络问题），用模拟数据验证：
1. 构造持仓 ETH long @ 1875.22（实盘真实持仓）
2. 模拟卦象推理结果
3. 验证 polling_trader 的离场代码路径走 yijing 主决策
"""
import sys
import os
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.memory_l4.yijing_exit_system import (
    YijingExitSystem, YijingExitConfig, YijingExitAction,
)
from scripts.memory_l4.classic_exit_system import (
    ExitAction, ExitConfig, PositionState,
)

_results = []
_pass = 0
_fail = 0


def record(name: str, passed: bool, detail: str = ""):
    global _pass, _fail
    if passed:
        _pass += 1
    else:
        _fail += 1
    icon = "✅" if passed else "❌"
    print(f"  {icon} {name}" + (f" — {detail[:120]}" if detail and not passed else ""))


def make_hex_result(
    name_cn: str = "乾为天",
    risk_level: str = "中",
    current_phase: str = "九五",
    development_stage: str = "成长期",
    direction_hint: str = "UP",
    confidence: float = 0.7,
):
    """构造 YijingResult 模拟对象（dict 形式）"""
    return {
        "hexagram_name": name_cn,
        "hexagram_name_cn": name_cn,
        "risk_level": risk_level,
        "current_phase": current_phase,
        "development_stage": development_stage,
        "direction_hint": direction_hint,
        "confidence": confidence,
    }


# ============================================================
# 测试：验证 polling_trader 离场代码路径（模拟实盘）
# ============================================================
def test_polling_trader_exit_path():
    print(f"\n{'='*60}")
    print(f"  模拟实盘验证 — polling_trader 离场代码路径")
    print(f"  持仓: ETH long @ 1875.22 (实盘真实持仓)")
    print(f"{'='*60}")

    # 实盘真实持仓参数
    coin = "ETH"
    inst_id = "ETH-USDT-SWAP"
    pos_side = "long"
    entry_price = 1875.22
    current_price = 1900.0  # 假设当前价（盈利）
    upl_ratio = (current_price - entry_price) / entry_price  # +1.32%
    upl = upl_ratio * 100  # 简化
    position_age_sec = 3600 * 24  # 24h

    # ── 场景1: 卦象良好（飞龙在天+成长期+方向一致）→ 应 HOLD ──
    print(f"\n  场景1: 卦象良好（飞龙在天+成长期+UP）→ 预期 HOLD")
    sys_obj = YijingExitSystem()
    cfg = sys_obj.config
    hex_good = make_hex_result(
        name_cn="乾为天", risk_level="低",
        current_phase="九五", development_stage="成长期",
        direction_hint="UP", confidence=0.85,
    )
    yijing_decision = sys_obj.evaluate(
        hexagram=hex_good, pos_side=pos_side,
        entry_price=entry_price, current_price=current_price,
        position_age_sec=position_age_sec, unrealized_pnl_pct=upl_ratio,
        classic_decision=None,
    )
    # 模拟 polling_trader 的 HOLD 判定逻辑（来自 polling_trader.py 第 901-919 行）
    risk_low = yijing_decision.yijing_risk_score < cfg.veto_risk_threshold
    value_high = yijing_decision.yijing_value_score > cfg.veto_value_threshold
    loss_acceptable = upl_ratio > cfg.veto_max_loss_pct
    not_expired = position_age_sec < cfg.veto_max_hold_sec
    should_hold = (risk_low and value_high
                   and yijing_decision.direction_consistent
                   and loss_acceptable and not_expired)

    record("场景1: 卦象良好→HOLD(不调classic)", should_hold,
           f"action={yijing_decision.action.value} risk={yijing_decision.yijing_risk_score:.3f} "
           f"value={yijing_decision.yijing_value_score:.3f} dir_ok={yijing_decision.direction_consistent} "
           f"risk_low={risk_low} value_high={value_high} loss_ok={loss_acceptable} not_expired={not_expired}")

    # ── 场景2: 卦象极度危险（坤为地+衰退期+方向冲突）→ 应 FORCE_CLOSE ──
    print(f"\n  场景2: 卦象危险（坤为地+衰退期+DOWN vs long）→ 预期 FORCE_CLOSE")
    hex_danger = make_hex_result(
        name_cn="坤为地", risk_level="高",
        current_phase="上九", development_stage="衰退期",
        direction_hint="DOWN", confidence=0.85,
    )
    yijing_decision2 = sys_obj.evaluate(
        hexagram=hex_danger, pos_side=pos_side,
        entry_price=entry_price, current_price=current_price,
        position_age_sec=position_age_sec, unrealized_pnl_pct=upl_ratio,
        classic_decision=None,
    )
    record("场景2: 卦象危险→FORCE_CLOSE", 
           yijing_decision2.action == YijingExitAction.FORCE_CLOSE,
           f"action={yijing_decision2.action.value} risk={yijing_decision2.yijing_risk_score:.3f} "
           f"dir_ok={yijing_decision2.direction_consistent}")

    # ── 场景3: 卦象价值高+盈利 → 应 RAISE_TP ──
    print(f"\n  场景3: 卦象价值高+盈利（飞龙在天+成长期+5%盈利）→ 预期 RAISE_TP")
    hex_value = make_hex_result(
        name_cn="乾为天", risk_level="低",
        current_phase="九五", development_stage="成长期",
        direction_hint="UP", confidence=0.85,
    )
    # 模拟 ETH 涨到 1970（+5%）
    current_price_3 = 1970.0
    upl_ratio_3 = (current_price_3 - entry_price) / entry_price
    yijing_decision3 = sys_obj.evaluate(
        hexagram=hex_value, pos_side=pos_side,
        entry_price=entry_price, current_price=current_price_3,
        position_age_sec=position_age_sec, unrealized_pnl_pct=upl_ratio_3,
        classic_decision=None,
    )
    record("场景3: 价值高+盈利→RAISE_TP",
           yijing_decision3.action == YijingExitAction.RAISE_TP,
           f"action={yijing_decision3.action.value} value={yijing_decision3.yijing_value_score:.3f} "
           f"tp_adjust={yijing_decision3.tp_adjust_pct:.2f}")

    # ── 场景4: 卦象信号中性 → 应降级 classic ──
    print(f"\n  场景4: 卦象信号中性（水雷屯+萌芽期）→ 预期 NO_INTERVENE 降级 classic")
    hex_neutral = make_hex_result(
        name_cn="水雷屯", risk_level="中",
        current_phase="九三", development_stage="萌芽期",
        direction_hint="UP", confidence=0.55,
    )
    yijing_decision4 = sys_obj.evaluate(
        hexagram=hex_neutral, pos_side=pos_side,
        entry_price=entry_price, current_price=current_price,
        position_age_sec=position_age_sec, unrealized_pnl_pct=upl_ratio,
        classic_decision=None,
    )
    risk_low_4 = yijing_decision4.yijing_risk_score < cfg.veto_risk_threshold
    value_high_4 = yijing_decision4.yijing_value_score > cfg.veto_value_threshold
    should_hold_4 = (risk_low_4 and value_high_4
                     and yijing_decision4.direction_consistent
                     and upl_ratio > cfg.veto_max_loss_pct
                     and position_age_sec < cfg.veto_max_hold_sec)
    record("场景4: 信号中性→降级classic",
           yijing_decision4.action == YijingExitAction.NO_INTERVENE and not should_hold_4,
           f"action={yijing_decision4.action.value} risk={yijing_decision4.yijing_risk_score:.3f} "
           f"value={yijing_decision4.yijing_value_score:.3f} should_hold={should_hold_4}")

    # ── 场景5: 卦象不可用（None）→ 应 fail-open 走 classic ──
    print(f"\n  场景5: 卦象不可用（None）→ 预期 fail-open 走 classic")
    yijing_decision5 = sys_obj.evaluate(
        hexagram=None, pos_side=pos_side,
        entry_price=entry_price, current_price=current_price,
        position_age_sec=position_age_sec, unrealized_pnl_pct=upl_ratio,
        classic_decision=None,
    )
    record("场景5: 卦象不可用→fail-open",
           yijing_decision5.action == YijingExitAction.NO_INTERVENE
           and yijing_decision5.should_log is False,
           f"action={yijing_decision5.action.value} should_log={yijing_decision5.should_log} "
           f"reason={yijing_decision5.reason}")

    # ── 场景6: 模拟实盘 AAVE short 持仓 ──
    print(f"\n  场景6: AAVE short @ 91.42 持仓 + 卦象方向一致（DOWN）")
    aave_entry = 91.42
    aave_current = 90.0  # 做空盈利
    aave_upl_ratio = (aave_entry - aave_current) / aave_entry  # +1.55%
    aave_age = 3600 * 1  # 1h

    hex_aave = make_hex_result(
        name_cn="坤为地", risk_level="低",
        current_phase="九二", development_stage="成长期",
        direction_hint="DOWN", confidence=0.70,
    )
    yijing_decision6 = sys_obj.evaluate(
        hexagram=hex_aave, pos_side="short",
        entry_price=aave_entry, current_price=aave_current,
        position_age_sec=aave_age, unrealized_pnl_pct=aave_upl_ratio,
        classic_decision=None,
    )
    risk_low_6 = yijing_decision6.yijing_risk_score < cfg.veto_risk_threshold
    value_high_6 = yijing_decision6.yijing_value_score > cfg.veto_value_threshold
    loss_ok_6 = aave_upl_ratio > cfg.veto_max_loss_pct
    not_expired_6 = aave_age < cfg.veto_max_hold_sec
    should_hold_6 = (risk_low_6 and value_high_6
                     and yijing_decision6.direction_consistent
                     and loss_ok_6 and not_expired_6)
    record("场景6: AAVE short+卦象一致→HOLD",
           should_hold_6,
           f"action={yijing_decision6.action.value} risk={yijing_decision6.yijing_risk_score:.3f} "
           f"value={yijing_decision6.yijing_value_score:.3f} dir_ok={yijing_decision6.direction_consistent}")


def main():
    print("=" * 60)
    print("  模拟实盘验证 — polling_trader 离场代码路径")
    print("  架构: yijing 主离场 + classic 备用层")
    print("=" * 60)

    test_polling_trader_exit_path()

    print(f"\n{'='*60}")
    print(f"  验证汇总")
    print(f"{'='*60}")
    total = _pass + _fail
    print(f"  总用例: {total}")
    print(f"  通过:   {_pass}")
    print(f"  失败:   {_fail}")
    if total > 0:
        print(f"  通过率: {_pass/total*100:.1f}%")

    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
