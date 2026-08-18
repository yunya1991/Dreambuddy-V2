#!/usr/bin/env python3
"""
L4 全局交易链路统一测试脚本

验证各系统（易经推理、马丁策略、三屏趋势、Agent A/B、Dream OS）
的交易闭环能否正确生成 L4 TradeCase v0.3 案例。

测试流程：
1. 模拟各系统的开仓和平仓操作
2. 验证 L4 案例是否正确生成
3. 检查案例格式是否符合 v0.3 标准
4. 汇总各系统的测试结果
"""

import sys
import json
from datetime import datetime, timezone
from pathlib import Path

# 设置路径
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

L4_ROOT = BASE_DIR / "11-易经推理系统"
sys.path.insert(0, str(L4_ROOT))

from trade_event import TradeEvent
from case_registry import UnifiedCaseRegistry


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def test_yijing_inference(registry):
    """测试易经推理系统"""
    log("=== 测试易经推理系统 ===")
    
    trade_id = f"yj_test_{int(datetime.now(timezone.utc).timestamp())}"
    
    event = TradeEvent(
        event_id=TradeEvent.generate_event_id(),
        system_source="yijing_inference",
        trade_id=trade_id,
        ts_entry="2026-07-21T10:00:00Z",
        ts_exit=datetime.now(timezone.utc).isoformat(),
        symbol="BTC-USDT-SWAP",
        direction="long",
        entry_price=65000,
        exit_price=67000,
        position_size=0.1,
        pnl=200,
        pnl_pct=3.077,
        exit_reason="take_profit",
        decision_context={
            "hexagram": "乾",
            "confidence": 0.75,
            "liangyi_state": {"yang": 0.8, "yin": 0.2},
            "enhance_info": {"market_state": "trend_up", "atr_multiplier": 1.5},
        },
        market_snapshot={"regime": "trend_up", "volatility": 0.02},
        leverage=5.0,
    )
    
    case_id, success = registry.register_trade_event(event)
    
    if success:
        case = registry.get_case(case_id)
        log(f"✅ 易经推理系统测试通过")
        log(f"   case_id: {case_id}")
        log(f"   version: {case.get('version')}")
        log(f"   pnl_pct: {case['decision_outcome']['pnl_pct']:.2f}%")
        log(f"   quadrant: x={case['quadrant']['x']}, y={case['quadrant']['y']}")
    else:
        log(f"❌ 易经推理系统测试失败")
    
    return success, case_id


def test_martin_v15(registry):
    """测试马丁策略 V15"""
    log("\n=== 测试马丁策略 V15 ===")
    
    trade_id = f"martin_test_{int(datetime.now(timezone.utc).timestamp())}"
    
    event = TradeEvent(
        event_id=TradeEvent.generate_event_id(),
        system_source="martin_v15",
        trade_id=trade_id,
        ts_entry="2026-07-21T10:00:00Z",
        ts_exit=datetime.now(timezone.utc).isoformat(),
        symbol="ETH-USDT-SWAP",
        direction="short",
        entry_price=3500,
        exit_price=3350,
        position_size=1.0,
        pnl=150,
        pnl_pct=4.286,
        exit_reason="take_profit",
        decision_context={
            "addon_level": 2,
            "martin_config": {"max_addons": 3, "base_tp_pct": 0.04, "leverage": 5.0},
            "grid_params": {"grid_level": 3},
        },
        market_snapshot={"regime": "trend_down", "volatility": 0.03},
        leverage=5.0,
    )
    
    case_id, success = registry.register_trade_event(event)
    
    if success:
        case = registry.get_case(case_id)
        log(f"✅ 马丁策略测试通过")
        log(f"   case_id: {case_id}")
        log(f"   version: {case.get('version')}")
        log(f"   pnl_pct: {case['decision_outcome']['pnl_pct']:.2f}%")
        log(f"   quadrant: x={case['quadrant']['x']}, y={case['quadrant']['y']}")
    else:
        log(f"❌ 马丁策略测试失败")
    
    return success, case_id


def test_three_screen(registry):
    """测试三屏趋势策略"""
    log("\n=== 测试三屏趋势策略 ===")
    
    trade_id = f"three_screen_test_{int(datetime.now(timezone.utc).timestamp())}"
    
    event = TradeEvent(
        event_id=TradeEvent.generate_event_id(),
        system_source="three_screen",
        trade_id=trade_id,
        ts_entry="2026-07-21T10:00:00Z",
        ts_exit=datetime.now(timezone.utc).isoformat(),
        symbol="SOL-USDT-SWAP",
        direction="long",
        entry_price=180,
        exit_price=195,
        position_size=5.0,
        pnl=75,
        pnl_pct=8.333,
        exit_reason="close_position",
        decision_context={
            "screen_signals": {"screen1": "bullish", "screen2": "bullish", "screen3": "bullish"},
            "strategy_type": "three_screen_trend",
            "paper_trading": False,
        },
        leverage=3.0,
    )
    
    case_id, success = registry.register_trade_event(event)
    
    if success:
        case = registry.get_case(case_id)
        log(f"✅ 三屏趋势策略测试通过")
        log(f"   case_id: {case_id}")
        log(f"   version: {case.get('version')}")
        log(f"   pnl_pct: {case['decision_outcome']['pnl_pct']:.2f}%")
        log(f"   quadrant: x={case['quadrant']['x']}, y={case['quadrant']['y']}")
    else:
        log(f"❌ 三屏趋势策略测试失败")
    
    return success, case_id


def test_agent_a(registry):
    """测试 Agent A"""
    log("\n=== 测试 Agent A ===")
    
    trade_id = f"agent_a_test_{int(datetime.now(timezone.utc).timestamp())}"
    
    event = TradeEvent(
        event_id=TradeEvent.generate_event_id(),
        system_source="agent_a",
        trade_id=trade_id,
        ts_entry="2026-07-21T10:00:00Z",
        ts_exit=datetime.now(timezone.utc).isoformat(),
        symbol="ARB-USDT-SWAP",
        direction="long",
        entry_price=1.2,
        exit_price=1.3,
        position_size=100,
        pnl=10,
        pnl_pct=8.333,
        exit_reason="take_profit",
        decision_context={
            "master": "BTC_Master",
            "confidence": 0.85,
            "lesson": "离场原因:take_profit",
        },
        leverage=5.0,
    )
    
    case_id, success = registry.register_trade_event(event)
    
    if success:
        case = registry.get_case(case_id)
        log(f"✅ Agent A 测试通过")
        log(f"   case_id: {case_id}")
        log(f"   version: {case.get('version')}")
        log(f"   pnl_pct: {case['decision_outcome']['pnl_pct']:.2f}%")
        log(f"   quadrant: x={case['quadrant']['x']}, y={case['quadrant']['y']}")
    else:
        log(f"❌ Agent A 测试失败")
    
    return success, case_id


def test_agent_b(registry):
    """测试 Agent B"""
    log("\n=== 测试 Agent B ===")
    
    trade_id = f"agent_b_test_{int(datetime.now(timezone.utc).timestamp())}"
    
    event = TradeEvent(
        event_id=TradeEvent.generate_event_id(),
        system_source="agent_b",
        trade_id=trade_id,
        ts_entry="2026-07-21T10:00:00Z",
        ts_exit=datetime.now(timezone.utc).isoformat(),
        symbol="AVAX-USDT-SWAP",
        direction="short",
        entry_price=35,
        exit_price=32,
        position_size=2.0,
        pnl=6,
        pnl_pct=8.571,
        exit_reason="stop_loss_hit",
        decision_context={
            "driver_mode": "CLASSIC",
            "strategy": "rsi_reversal",
            "confidence": 0.70,
        },
        leverage=5.0,
    )
    
    case_id, success = registry.register_trade_event(event)
    
    if success:
        case = registry.get_case(case_id)
        log(f"✅ Agent B 测试通过")
        log(f"   case_id: {case_id}")
        log(f"   version: {case.get('version')}")
        log(f"   pnl_pct: {case['decision_outcome']['pnl_pct']:.2f}%")
        log(f"   quadrant: x={case['quadrant']['x']}, y={case['quadrant']['y']}")
    else:
        log(f"❌ Agent B 测试失败")
    
    return success, case_id


def test_dream_os(registry):
    """测试 Dream OS"""
    log("\n=== 测试 Dream OS ===")
    
    trade_id = f"dream_os_test_{int(datetime.now(timezone.utc).timestamp())}"
    
    event = TradeEvent(
        event_id=TradeEvent.generate_event_id(),
        system_source="dream_os",
        trade_id=trade_id,
        ts_entry="2026-07-21T10:00:00Z",
        ts_exit=datetime.now(timezone.utc).isoformat(),
        symbol="BTC-USDT-SWAP",
        direction="long",
        entry_price=65000,
        exit_price=64500,
        position_size=0.1,
        pnl=-50,
        pnl_pct=-0.769,
        exit_reason="dream_os_close_HIGH",
        decision_context={
            "strategy_id": "yijing_inference",
            "system_name": "易经推理系统",
            "fusion_mode": "yijing_classic_fusion",
            "urgency": "HIGH",
            "mode": "dry_run",
        },
        leverage=5.0,
    )
    
    case_id, success = registry.register_trade_event(event)
    
    if success:
        case = registry.get_case(case_id)
        log(f"✅ Dream OS 测试通过")
        log(f"   case_id: {case_id}")
        log(f"   version: {case.get('version')}")
        log(f"   pnl_pct: {case['decision_outcome']['pnl_pct']:.2f}%")
        log(f"   quadrant: x={case['quadrant']['x']}, y={case['quadrant']['y']}")
    else:
        log(f"❌ Dream OS 测试失败")
    
    return success, case_id


def verify_all_cases(registry):
    """验证所有生成的案例格式"""
    log("\n=== 验证所有 L4 案例格式 ===")
    
    all_cases = []
    for source in ["yijing_inference", "martin_v15", "three_screen", "agent_a", "agent_b", "dream_os"]:
        cases = registry.list_cases(source)
        all_cases.extend(cases)
    
    log(f"共找到 {len(all_cases)} 个 L4 案例")
    
    errors = []
    for case_id in all_cases:
        case = registry.get_case(case_id)
        if not case:
            errors.append(f"{case_id}: 案例不存在")
            continue
        
        if case.get("version") != "v0.3":
            errors.append(f"{case_id}: 版本不正确，应为 v0.3")
        
        if not case.get("system_source"):
            errors.append(f"{case_id}: 缺少 system_source")
        
        if not case.get("thinking_chain"):
            errors.append(f"{case_id}: 缺少 thinking_chain")
        
        if not case.get("decision_context"):
            errors.append(f"{case_id}: 缺少 decision_context")
        
        if not case.get("quadrant"):
            errors.append(f"{case_id}: 缺少 quadrant")
        elif not isinstance(case["quadrant"], dict):
            errors.append(f"{case_id}: quadrant 应为对象格式")
    
    if errors:
        log(f"❌ 发现 {len(errors)} 个格式错误:")
        for err in errors:
            log(f"   - {err}")
        return False
    else:
        log(f"✅ 所有案例格式验证通过")
        return True


def main():
    registry = UnifiedCaseRegistry()
    
    results = []
    
    results.append(("易经推理系统", *test_yijing_inference(registry)))
    results.append(("马丁策略 V15", *test_martin_v15(registry)))
    results.append(("三屏趋势策略", *test_three_screen(registry)))
    results.append(("Agent A", *test_agent_a(registry)))
    results.append(("Agent B", *test_agent_b(registry)))
    results.append(("Dream OS", *test_dream_os(registry)))
    
    format_ok = verify_all_cases(registry)
    
    log("\n" + "="*60)
    log("L4 全局交易链路统一测试结果")
    log("="*60)
    
    passed = sum(1 for _, success, _ in results if success)
    total = len(results)
    
    log(f"\n测试通过率: {passed}/{total}")
    
    for name, success, case_id in results:
        status = "✅" if success else "❌"
        log(f"  {status} {name}: {case_id}")
    
    log(f"\n格式验证: {'✅ 通过' if format_ok else '❌ 失败'}")
    
    if passed == total and format_ok:
        log("\n🎉 所有测试通过！L4 全局交易链路统一接入验证完成")
    else:
        log("\n⚠️ 部分测试未通过，请检查错误信息")


if __name__ == "__main__":
    main()