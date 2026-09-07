"""
evolution_data_accessor 单元测试
TDD RED 阶段：先写失败测试，再写实现

覆盖 spec 第8.1节的10个测试用例：
- test_get_evolution_overview_distinguishes_source_tag
- test_get_evolution_overview_range_filter
- test_get_evolution_overview_empty_evolution
- test_get_evolution_timeline_cumulative_daily
- test_get_evolution_timeline_empty
- test_get_evolution_evidence_cs_distribution
- test_get_evolution_evidence_degraded
- test_get_evolution_detail_trade
- test_get_evolution_detail_reflection
- test_get_evolution_detail_not_found
"""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ── 辅助：构造测试用 all_trades.jsonl ──────────────────────────────────────
def _make_trade(trade_id, coin, direction, entry_price, exit_price, pnl, strategy_source,
                exit_time_iso, entry_time_iso=None, pnl_pct=None):
    """构造单条 all_trades.jsonl 记录"""
    if entry_time_iso is None:
        entry_time_iso = exit_time_iso
    if pnl_pct is None:
        pnl_pct = pnl / (entry_price * 10)  # 粗略估算
    return {
        "trade_id": trade_id,
        "coin": coin,
        "inst_id": f"{coin}-USDT-SWAP",
        "direction": direction,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "entry_time": entry_time_iso,
        "exit_time": exit_time_iso,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "exit_reason": "signal_reverse",
        "confidence": 0.8,
        "hexagram": "test",
        "strategy_source": strategy_source,
        "market_snapshot": {},
        "contradiction_list": [],
        "enhance_info": {},
        "reduce_count": 0,
    }


@pytest.fixture
def tmp_trades_file(tmp_path):
    """创建临时 all_trades.jsonl，含 evolution + bcrm 各2笔"""
    now = datetime.now(timezone.utc)
    iso_fmt = lambda dt: dt.isoformat()

    trades = [
        # evolution 子池 2 笔（1胜1负）
        _make_trade("evo_001", "BTC", "long", 58000, 58500, 1.2, "evolution",
                    iso_fmt(now - timedelta(days=10))),
        _make_trade("evo_002", "ETH", "short", 3000, 3050, -0.5, "evolution",
                    iso_fmt(now - timedelta(days=5))),
        # main_pool (bcrm) 2 笔（2胜）
        _make_trade("bcrm_001", "SOL", "long", 100, 105, 2.0, "bcrm",
                    iso_fmt(now - timedelta(days=30))),
        _make_trade("bcrm_002", "ADA", "long", 0.5, 0.55, 0.8, "bcrm",
                    iso_fmt(now - timedelta(days=1))),
    ]
    trades_file = tmp_path / "all_trades.jsonl"
    with open(trades_file, "w", encoding="utf-8") as f:
        for t in trades:
            f.write(json.dumps(t) + "\n")
    return trades_file


@pytest.fixture
def tmp_perf_file(tmp_path):
    """创建临时 performance.json"""
    perf = {
        "total_trades": 4,
        "win_count": 3,
        "loss_count": 1,
        "win_rate": 0.75,
        "total_pnl": 3.5,
        "avg_pnl": 0.875,
        "max_win": 2.0,
        "max_loss": -0.5,
        "consecutive_losses": 0,
        "last_update": "2026-09-05 04:09:00 UTC",
        "data_source": "all_trades.jsonl",
    }
    perf_file = tmp_path / "performance.json"
    with open(perf_file, "w", encoding="utf-8") as f:
        json.dump(perf, f)
    return perf_file


@pytest.fixture
def accessor(tmp_trades_file, tmp_perf_file, monkeypatch):
    """构造 evolution_data_accessor 实例，指向临时文件"""
    from scripts.evolution_data_accessor import EvolutionDataAccessor
    acc = EvolutionDataAccessor(
        trades_file=str(tmp_trades_file),
        perf_file=str(tmp_perf_file),
    )
    return acc


# ── 测试1: evolution vs main_pool 正确区分 ─────────────────────────────────
def test_get_evolution_overview_distinguishes_source_tag(accessor):
    """验证 evolution vs main_pool 按 strategy_source 正确区分"""
    result = accessor.get_evolution_overview(range_days=None)

    assert "evolution" in result
    assert "main_pool" in result
    # evolution: 2笔（1胜1负），总盈亏 1.2 + (-0.5) = 0.7
    assert result["evolution"]["closed_count"] == 2
    assert result["evolution"]["total_pnl"] == pytest.approx(0.7, rel=1e-6)
    assert result["evolution"]["win_rate"] == 0.5
    # main_pool: 2笔（2胜），总盈亏 2.0 + 0.8 = 2.8
    assert result["main_pool"]["closed_count"] == 2
    assert result["main_pool"]["total_pnl"] == pytest.approx(2.8, rel=1e-6)
    assert result["main_pool"]["win_rate"] == 1.0


# ── 测试2: 时间窗口过滤 ─────────────────────────────────────────────────────
def test_get_evolution_overview_range_filter(accessor):
    """验证 7d/30d/all 时间窗口过滤"""
    # 7d: 仅包含最近7天的交易
    result_7d = accessor.get_evolution_overview(range_days=7)
    # evo_002 (5天前) 在7d内，evo_001 (10天前) 不在
    assert result_7d["evolution"]["closed_count"] == 1
    assert result_7d["evolution"]["total_pnl"] == pytest.approx(-0.5, rel=1e-6)
    # bcrm_002 (1天前) 在7d内，bcrm_001 (30天前) 不在
    assert result_7d["main_pool"]["closed_count"] == 1

    # all: 全部4笔
    result_all = accessor.get_evolution_overview(range_days=None)
    assert result_all["evolution"]["closed_count"] == 2
    assert result_all["main_pool"]["closed_count"] == 2


# ── 测试3: evolution 无数据时降级 ──────────────────────────────────────────
def test_get_evolution_overview_empty_evolution(tmp_path, tmp_perf_file):
    """evolution 无平仓记录时降级返回 null"""
    from scripts.evolution_data_accessor import EvolutionDataAccessor
    # 仅含 bcrm 交易
    now = datetime.now(timezone.utc)
    trades = [_make_trade("bcrm_001", "SOL", "long", 100, 105, 2.0, "bcrm",
                          now.isoformat())]
    trades_file = tmp_path / "all_trades.jsonl"
    with open(trades_file, "w") as f:
        for t in trades:
            f.write(json.dumps(t) + "\n")

    acc = EvolutionDataAccessor(trades_file=str(trades_file), perf_file=str(tmp_perf_file))
    result = acc.get_evolution_overview(range_days=None)

    assert result["evolution"]["closed_count"] == 0
    assert result["evolution"]["total_pnl"] is None
    assert result["evolution"]["win_rate"] is None
    assert result["main_pool"]["closed_count"] == 1


# ── 测试4: 累计/daily 计算正确 ──────────────────────────────────────────────
def test_get_evolution_timeline_cumulative_daily(accessor):
    """验证累计盈亏和每日盈亏计算"""
    result = accessor.get_evolution_timeline(range_days=None)

    assert "dates" in result
    assert "cumulative" in result
    assert "daily" in result
    assert len(result["dates"]) > 0
    # cumulative 最后一天 = 总盈亏
    evo_total = sum(result["daily"]["evolution"])
    assert evo_total == pytest.approx(0.7, rel=1e-6)
    # cumulative 是累加
    cum_evo = result["cumulative"]["evolution"]
    assert cum_evo[-1] == pytest.approx(0.7, rel=1e-6)
    # trade_points 存在
    assert "trade_points" in result
    assert len(result["trade_points"]["evolution"]) == 2


# ── 测试5: 无数据时返回空数组 ──────────────────────────────────────────────
def test_get_evolution_timeline_empty(tmp_path, tmp_perf_file):
    """无平仓记录时返回空数组"""
    from scripts.evolution_data_accessor import EvolutionDataAccessor
    trades_file = tmp_path / "all_trades.jsonl"
    trades_file.write_text("")  # 空文件

    acc = EvolutionDataAccessor(trades_file=str(trades_file), perf_file=str(tmp_perf_file))
    result = acc.get_evolution_timeline(range_days=None)

    assert result["dates"] == []
    assert result["cumulative"]["evolution"] == []
    assert result["cumulative"]["main_pool"] == []
    assert result["daily"]["evolution"] == []
    assert result["daily"]["main_pool"] == []


# ── 测试6: cs_distribution 分位数计算（降级模式） ───────────────────────────
def test_get_evolution_evidence_cs_distribution(accessor):
    """验证 cs_distribution 降级返回（ReflectionEngine 未持久化）"""
    result = accessor.get_evolution_evidence(range_days=None)

    # MVP 降级：所有字段返回空 + degraded=true
    assert result.get("degraded") is True
    assert result["ess_curve"]["evolution_avg"] == []
    assert result["reflection_count"]["evolution"] == 0
    assert result["cs_distribution"]["evolution"]["samples"] == []
    assert result["gmax_trajectory"]["gmax_mult"] == []


# ── 测试7: cognitive_memory.db 访问失败时降级 ──────────────────────────────
def test_get_evolution_evidence_degraded(accessor):
    """验证降级标记"""
    result = accessor.get_evolution_evidence(range_days=None)
    # 已确认 ReflectionEngine 未持久化，始终降级
    assert result["degraded"] is True


# ── 测试8: trade 详情字段 ──────────────────────────────────────────────────
def test_get_evolution_detail_trade(accessor):
    """验证 trade 详情字段"""
    result = accessor.get_evolution_detail(detail_type="trade", detail_id="evo_001")

    assert result is not None
    assert result["type"] == "trade"
    assert result["trade_id"] == "evo_001"
    assert result["symbol"] == "BTC"
    assert result["direction"] == "long"
    assert result["source_tag"] == "evolution"
    assert result["entry_price"] == 58000
    assert result["exit_price"] == 58500
    assert result["pnl"] == pytest.approx(1.2, rel=1e-6)


# ── 测试9: reflection 详情降级 ─────────────────────────────────────────────
def test_get_evolution_detail_reflection(accessor):
    """验证 reflection 详情降级（ReflectionEngine 未持久化）"""
    result = accessor.get_evolution_detail(detail_type="reflection", detail_id="r_001")

    assert result is not None
    assert result.get("degraded") is True
    assert "message" in result


# ── 测试10: id 不存在返回 None ─────────────────────────────────────────────
def test_get_evolution_detail_not_found(accessor):
    """验证 id 不存在返回 None"""
    result = accessor.get_evolution_detail(detail_type="trade", detail_id="nonexistent")
    assert result is None
