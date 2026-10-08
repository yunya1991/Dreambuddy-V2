"""P3 T17 端到端验收：参数中心查询 + 影子记录全链路

模拟开仓流程：
  1. 子系统查询参数中心 → 得到 SL/TP 参数
  2. 影子记录 param_center_recommended + actual_used + deviation_pct
  3. 查询 deviation_report 验证记录存在
  4. 验证参数满足硬约束

运行：
  python -m pytest 16-调控系统/scripts/param_center/tests/test_e2e.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 路径设置
_THIS = Path(__file__).resolve()
_PARAM_CENTER = _THIS.parent.parent
_SCRIPTS_16 = _PARAM_CENTER.parent
_PROJECT_ROOT = _SCRIPTS_16.parent.parent
_YIJING_SCRIPTS = _PROJECT_ROOT / "11-易经推理系统" / "scripts"
for p in [_YIJING_SCRIPTS, _SCRIPTS_16, _PARAM_CENTER]:
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

from param_center.api import get_sltp_params  # noqa: E402
from param_center.shadow_integration import ParamCenterShadowLogger  # noqa: E402
from memory_l4.bcrm2.sl_tp_config import SLTPParams  # noqa: E402


def test_e2e_open_position_flow(tmp_path):
    """端到端：开仓查询参数中心 + 影子记录"""
    # 用临时 DB 避免污染生产数据
    db_path = tmp_path / "test_deviation.db"
    shadow = ParamCenterShadowLogger(db_path=db_path)

    # 1. 子系统查询参数中心（模拟 BTC long chop）
    params = get_sltp_params("BTC", market_regime="chop", use_cache=False)
    assert isinstance(params, SLTPParams)
    assert params.sl_floor >= 0.03
    assert params.tp_floor >= 0.12

    # 2. 影子记录（参数中心推荐值 = 子系统实际使用值）
    recommended = {
        "sl_floor": params.sl_floor,
        "tp_floor": params.tp_floor,
        "atr_mult": params.atr_mult_range[0],
    }
    actual_used = dict(recommended)  # P3 阶段推荐值=实际值
    record_id = shadow.record_deviation(
        symbol="BTC",
        recommended=recommended,
        actual_used=actual_used,
        weights={"param_center": 1.0},
        confidence=0.8,
        event_type="open",
    )
    assert record_id is not None, "影子记录应返回 ID"

    # 3. 查询 deviation_report 验证记录
    report = shadow.query_deviation_report("BTC", days=1)
    assert len(report) >= 1, "应至少有 1 条记录"
    rec = report[0]
    assert rec["symbol"] == "BTC"
    assert rec["event_type"] == "open"
    # 偏差应为 0（推荐值=实际值）
    assert rec["deviation_pct"] == pytest.approx(0.0, abs=1e-6)


def test_e2e_deviation_detection(tmp_path):
    """端到端：参数中心推荐值 vs 子系统实际值有偏差时正确记录"""
    db_path = tmp_path / "test_dev2.db"
    shadow = ParamCenterShadowLogger(db_path=db_path)

    # 推荐值 SL=4%, 实际使用 SL=5% → 偏差 25%
    shadow.record_deviation(
        symbol="ETH",
        recommended={"sl_floor": 0.04, "tp_floor": 0.12, "atr_mult": 4.5},
        actual_used={"sl_floor": 0.05, "tp_floor": 0.12, "atr_mult": 4.5},
        confidence=0.7,
        event_type="polling",
    )
    report = shadow.query_deviation_report("ETH", days=1)
    assert len(report) == 1
    # SL 偏差 = |0.04-0.05|/0.04 = 0.25, TP 偏差 = 0 → 均值 0.125
    assert report[0]["deviation_pct"] == pytest.approx(0.125, abs=1e-3)


def test_e2e_daily_summary(tmp_path):
    """端到端：每日偏差统计摘要"""
    db_path = tmp_path / "test_dev3.db"
    shadow = ParamCenterShadowLogger(db_path=db_path)

    # 写入 3 条记录
    for i in range(3):
        shadow.record_deviation(
            symbol="SOL",
            recommended={"sl_floor": 0.04, "tp_floor": 0.12, "atr_mult": 4.5},
            actual_used={"sl_floor": 0.04 + i * 0.01, "tp_floor": 0.12, "atr_mult": 4.5},
            confidence=0.6,
            event_type="polling",
        )
    summary = shadow.get_daily_deviation_summary("SOL", days=1)
    assert summary["count"] == 3
    assert summary["avg_deviation"] > 0
    assert summary["max_deviation"] >= summary["avg_deviation"]


def test_e2e_hard_constraints_all_symbols(tmp_path):
    """端到端：多个币种查询参数中心，全部满足硬约束"""
    test_cases = [
        ("BTC", "chop"),
        ("BTC", "bull"),
        ("BTC", "bear"),
        ("PEPE", "chop"),
        ("PEPE", "bull"),
        ("DOGE", "bear"),
        ("NVDA", "chop"),
        ("ETH", "bull"),
        ("SOL", "bear"),
    ]
    for symbol, regime in test_cases:
        params = get_sltp_params(symbol, market_regime=regime, use_cache=False)
        assert params.sl_floor >= 0.03, (
            f"{symbol}/{regime} SL={params.sl_floor} < 3%"
        )
        assert params.tp_floor >= 0.12, (
            f"{symbol}/{regime} TP={params.tp_floor} < 12%"
        )
        assert params.tp_floor / params.sl_floor >= 2.0, (
            f"{symbol}/{regime} RR={params.tp_floor/params.sl_floor} < 2"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
