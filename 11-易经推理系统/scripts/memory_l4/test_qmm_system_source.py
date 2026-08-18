"""测试 QMM 消费包含 system_source 的 TradeCase v0.3。"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

from scripts.memory_l4.case_registry import UnifiedCaseRegistry
from scripts.memory_l4.trade_event import TradeEvent
from scripts.memory_l4.qmm.engine import run_qmm


def create_test_cases_with_system_source(registry):
    """创建包含 system_source 的测试案例。"""
    cases = []
    
    systems = [
        ("yijing_inference", "乾卦多头信号", 3.5),
        ("martin_v15", "马丁加仓", 2.8),
        ("three_screen", "三屏趋势共振", 4.2),
        ("agent_a", "Agent A 动量信号", -1.2),
        ("agent_b", "Agent B 反转信号", 5.1),
        ("dream_os", "Dream OS 调控", -0.8),
        ("yijing_inference", "坤卦空头信号", -2.5),
        ("martin_v15", "马丁止损", -3.0),
        ("three_screen", "三屏趋势反转", -1.8),
        ("agent_a", "Agent A 突破", 3.8),
        ("agent_b", "Agent B 回撤", 2.1),
        ("dream_os", "Dream OS 加仓", 1.5),
    ]
    
    for i, (system, desc, pnl_pct) in enumerate(systems):
        trade_id = f"qmm_test_{system}_{i}"
        event = TradeEvent(
            event_id=TradeEvent.generate_event_id(),
            system_source=system,
            trade_id=trade_id,
            ts_entry="2026-07-21T10:00:00Z",
            ts_exit=datetime.now(timezone.utc).isoformat(),
            symbol="BTC-USDT-SWAP",
            direction="long" if pnl_pct > 0 else "short",
            entry_price=65000,
            exit_price=65000 * (1 + pnl_pct / 100),
            position_size=0.1,
            pnl=pnl_pct * 10,
            pnl_pct=pnl_pct,
            exit_reason="take_profit" if pnl_pct > 0 else "stop_loss",
            decision_context={"description": desc},
            market_snapshot={"regime": "trend_up" if i % 2 == 0 else "ranging"},
            leverage=5.0,
        )
        
        case_id, success = registry.register_trade_event(event)
        if success:
            case = registry.get_case(case_id)
            cases.append(case)
    
    return cases


def test_qmm_with_system_source():
    """测试 QMM 消费包含 system_source 的案例。"""
    registry = UnifiedCaseRegistry()
    
    print("=== 创建测试案例 ===")
    cases = create_test_cases_with_system_source(registry)
    print(f"创建了 {len(cases)} 个测试案例")
    
    print("\n=== 运行 QMM 引擎 ===")
    output = run_qmm(cases, distills=[])
    
    print("\n=== QMM 输出结果 ===")
    print(f"趋势状态: {output.trend_state}")
    print(f"变化点: {output.trend_change_point}")
    print(f"MRD 方向: {output.mrd_vector.get('direction')}")
    print(f"不确定性: {output.uncertainty:.4f}")
    
    print("\n=== 系统来源统计 ===")
    stats = output.system_source_stats
    if stats:
        for source, data in sorted(stats.items()):
            print(f"\n{source}:")
            print(f"  交易数: {data['count']}")
            print(f"  盈利数: {data['profit_count']}")
            print(f"  亏损数: {data['loss_count']}")
            print(f"  胜率: {data['win_rate']:.2%}")
            print(f"  平均 PnL: {data['avg_pnl']:.4f}%")
            print(f"  平均质量: {data['quality_avg']:.4f}")
    else:
        print("未生成系统来源统计")
    
    print("\n=== 验证 system_source 字段 ===")
    assert "system_source_stats" in output.__dict__, "system_source_stats 字段缺失"
    assert isinstance(output.system_source_stats, dict), "system_source_stats 不是字典类型"
    assert len(output.system_source_stats) > 0, "system_source_stats 为空"
    
    print("\n✅ QMM 成功消费包含 system_source 的 TradeCase v0.3！")
    
    return output


if __name__ == "__main__":
    test_qmm_with_system_source()