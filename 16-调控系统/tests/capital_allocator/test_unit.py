"""PACA 单元测试：Layer 1-4 各层独立测试。

覆盖：
- Layer 1: PerformanceTracker 统计正确性 + Bayesian Shrinkage
- Layer 2: KellySizer Kelly 公式 + Half-Kelly + 仓位映射 + 冷启动
- Layer 3: HierarchicalAllocator 分层分配 + 权重调整
- Layer 4: GlobalExpansionGate 阶梯匹配 + 安全约束 + 冷却
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# 路径设置
_16_DIR = Path(__file__).resolve().parents[2]  # 16-调控系统/
_CORE_ROOT = _16_DIR / "core"
if str(_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(_CORE_ROOT))

from capital_allocator.types import (  # noqa: E402
    AllocatorMode,
    CoinPerformance,
    HealthLevel,
)
from capital_allocator.layers.kelly_sizer import KellySizer  # noqa: E402
from capital_allocator.layers.hierarchical_allocator import HierarchicalAllocator  # noqa: E402
from capital_allocator.layers.expansion_gate import GlobalExpansionGate  # noqa: E402
from capital_allocator.layers.performance_tracker import PerformanceTracker  # noqa: E402


# ============================================================
# Layer 2: KellySizer
# ============================================================

class TestKellySizer:
    def test_kelly_fraction_basic(self):
        """Kelly 公式：胜率 60%, 盈亏比 1.5 → f = 0.6 - 0.4/1.5 = 0.333"""
        f = KellySizer.kelly_fraction_fn(0.6, 1.5)
        assert f == pytest.approx(0.3333, abs=0.01)

    def test_kelly_fraction_zero_wl(self):
        """盈亏比 <= 0 → Kelly = 0"""
        assert KellySizer.kelly_fraction_fn(0.6, 0.0) == 0.0
        assert KellySizer.kelly_fraction_fn(0.6, -1.0) == 0.0

    def test_kelly_fraction_negative(self):
        """胜率低 → Kelly 为负 → 返回 0"""
        f = KellySizer.kelly_fraction_fn(0.3, 1.0)
        assert f == 0.0  # 0.3 - 0.7/1.0 = -0.4 → max(0, -0.4) = 0

    def test_half_kelly(self):
        """Half-Kelly = Kelly * 0.5"""
        sizer = KellySizer(kelly_fraction=0.5)
        assert sizer.half_kelly(0.4) == 0.2

    def test_position_cold_start(self):
        """冷启动（n < 5）→ DEFAULT_PCT"""
        sizer = KellySizer(default_pct=0.10, cold_start_min_trades=5)
        assert sizer.kelly_to_position(0.3, 3) == 0.10

    def test_position_normal(self):
        """正常仓位：clamp 到 [MIN, MAX]"""
        sizer = KellySizer(min_pct=0.03, max_pct=0.25, cold_start_min_trades=5)
        pos = sizer.kelly_to_position(0.15, 10)
        assert pos == 0.15  # 在 [0.03, 0.25] 内

    def test_position_clamp_min(self):
        """仓位低于 MIN → clamp 到 MIN"""
        sizer = KellySizer(min_pct=0.03, max_pct=0.25, cold_start_min_trades=5)
        pos = sizer.kelly_to_position(0.01, 10)
        assert pos == 0.03

    def test_position_clamp_max(self):
        """仓位高于 MAX → clamp 到 MAX"""
        sizer = KellySizer(min_pct=0.03, max_pct=0.25, cold_start_min_trades=5)
        pos = sizer.kelly_to_position(0.50, 10)
        assert pos == 0.25

    def test_position_zero_kelly(self):
        """Kelly = 0 → 仓位 = 0（不冷启动时）"""
        sizer = KellySizer(cold_start_min_trades=5)
        assert sizer.kelly_to_position(0.0, 10) == 0.0

    def test_kelly_mult(self):
        """Kelly 乘数映射：half_f ∈ [0,1] → [0, 2.0]"""
        sizer = KellySizer()
        assert sizer.get_kelly_mult(0.0) == 0.0
        assert sizer.get_kelly_mult(0.5) == 1.0
        assert sizer.get_kelly_mult(1.0) == 2.0
        assert sizer.get_kelly_mult(1.5) == 2.0  # 上限


# ============================================================
# Layer 3: HierarchicalAllocator
# ============================================================

class TestHierarchicalAllocator:
    def test_default_weights(self):
        """默认子池权重"""
        alloc = HierarchicalAllocator()
        assert alloc.DEFAULT_WEIGHTS["bdsm"] == 0.25
        assert alloc.DEFAULT_WEIGHTS["bcrm"] == 0.40

    def test_allocate_subpools_basic(self):
        """基础子池分配"""
        alloc = HierarchicalAllocator()
        coin_kelly = {}  # 空
        result = alloc.allocate_subpools(1.0, coin_kelly)
        # 空输入 → 默认权重
        assert "bdsm" in result
        assert "bcrm" in result

    def test_min_weight_floor(self):
        """子池权重下限保护"""
        alloc = HierarchicalAllocator(
            subpool_weights={"bdsm": 0.01, "bcrm": 0.99},
            min_subpool_weight=0.10,
        )
        # 即使 bdsm 权重极低，也不低于 0.10
        result = alloc._adjust_weights({"bdsm": 0.1, "bcrm": 5.0})
        assert result["bdsm"] >= 0.10

    def test_allocate_coin(self):
        """子池内按 Kelly 分配"""
        alloc = HierarchicalAllocator()
        # 两个币 kelly_f 分别 0.2 和 0.3 → 总 0.5
        pos = alloc.allocate_coin(100.0, 0.2, 0.5)
        assert pos == pytest.approx(40.0)  # 100 * 0.2/0.5

    def test_allocate_coin_zero_total(self):
        """Kelly 总和为 0 → 返回 0"""
        alloc = HierarchicalAllocator()
        assert alloc.allocate_coin(100.0, 0.0, 0.0) == 0.0


# ============================================================
# Layer 4: GlobalExpansionGate
# ============================================================

class TestGlobalExpansionGate:
    def test_cold_start(self):
        """交易不足 window → 不扩张（1.0）"""
        gate = GlobalExpansionGate(window=30)
        stats = {"w_l_ratio": 3.0, "n_trades": 10}
        assert gate.get_expansion_multiplier(stats) == 1.0

    def test_expand_high_wl(self):
        """W/L ≥ 2.0 → ×1.5"""
        gate = GlobalExpansionGate(window=30, cooldown_hours=0)
        stats = {"w_l_ratio": 2.5, "n_trades": 50}
        mult = gate.get_expansion_multiplier(stats)
        assert mult == pytest.approx(1.5, abs=0.01)

    def test_expand_medium_wl(self):
        """W/L ≥ 1.0 → ×1.2"""
        gate = GlobalExpansionGate(window=30, cooldown_hours=0)
        stats = {"w_l_ratio": 1.5, "n_trades": 50}
        mult = gate.get_expansion_multiplier(stats)
        assert mult == pytest.approx(1.2, abs=0.01)

    def test_baseline_wl(self):
        """W/L ≥ 0.5 → ×1.0"""
        gate = GlobalExpansionGate(window=30, cooldown_hours=0)
        stats = {"w_l_ratio": 0.7, "n_trades": 50}
        mult = gate.get_expansion_multiplier(stats)
        assert mult == pytest.approx(1.0, abs=0.01)

    def test_shrink_low_wl(self):
        """W/L < 0.5 → ×0.7"""
        gate = GlobalExpansionGate(window=30, cooldown_hours=0)
        stats = {"w_l_ratio": 0.3, "n_trades": 50}
        mult = gate.get_expansion_multiplier(stats)
        assert mult == pytest.approx(0.7, abs=0.01)

    def test_safety_clamp(self):
        """安全约束：mult ∈ [0.5, 1.5]"""
        gate = GlobalExpansionGate(
            window=30, cooldown_hours=0,
            max_exposure=0.80, min_exposure=0.10,
        )
        stats = {"w_l_ratio": 100.0, "n_trades": 50}  # 极端高
        mult = gate.get_expansion_multiplier(stats)
        assert mult <= 1.5

    def test_fail_open_on_exception(self):
        """异常 → 1.0"""
        gate = GlobalExpansionGate()
        mult = gate.get_expansion_multiplier({"w_l_ratio": "invalid"})
        assert mult == 1.0


# ============================================================
# Layer 1: PerformanceTracker
# ============================================================

class TestPerformanceTracker:
    @pytest.fixture
    def temp_trades(self, tmp_path):
        """创建临时 trades.jsonl"""
        trades_file = tmp_path / "trades.jsonl"
        trades = [
            {"coin": "BTC-USDT-SWAP", "pnl": 10.0, "pnl_pct": 5.0, "close_ts": 1000},
            {"coin": "BTC-USDT-SWAP", "pnl": -5.0, "pnl_pct": -2.5, "close_ts": 2000},
            {"coin": "ETH-USDT-SWAP", "pnl": 8.0, "pnl_pct": 4.0, "close_ts": 1500},
            {"coin": "ETH-USDT-SWAP", "pnl": 12.0, "pnl_pct": 6.0, "close_ts": 2500},
        ]
        with open(trades_file, "w") as f:
            for t in trades:
                f.write(json.dumps(t) + "\n")
        return trades_file

    def test_load_basic(self, temp_trades):
        """基础加载 + 统计"""
        tracker = PerformanceTracker(
            trades_file=temp_trades,
            cache_ttl=0,
            shrinkage_threshold=30,
        )
        perf = tracker.get_performance()
        assert "BTC" in perf
        assert "ETH" in perf
        assert perf["BTC"].n_trades == 2
        assert perf["BTC"].n_wins == 1
        assert perf["ETH"].n_trades == 2
        assert perf["ETH"].n_wins == 2

    def test_global_stats(self, temp_trades):
        """全局统计"""
        tracker = PerformanceTracker(trades_file=temp_trades, cache_ttl=0)
        stats = tracker.get_global_stats()
        assert stats["n_trades"] == 4
        assert stats["n_wins"] == 3
        assert stats["win_rate"] == pytest.approx(0.75, abs=0.01)

    def test_bayesian_shrinkage(self, temp_trades):
        """Bayesian Shrinkage：小样本收缩"""
        tracker = PerformanceTracker(
            trades_file=temp_trades,
            cache_ttl=0,
            shrinkage_prior_strength=30,
            shrinkage_threshold=30,
        )
        perf = tracker.get_performance()
        # BTC: n=2 < 30 → 收缩
        btc = perf["BTC"]
        # 收缩后胜率应介于币种胜率(0.5)和全局胜率(0.75)之间
        assert btc.shrunk_win_rate > 0.5
        assert btc.shrunk_win_rate < 0.75

    def test_coin_normalize(self, temp_trades):
        """币种名归一化"""
        tracker = PerformanceTracker(trades_file=temp_trades, cache_ttl=0)
        perf = tracker.get_performance()
        # BTC-USDT-SWAP → BTC
        assert "BTC" in perf
        assert "BTC-USDT-SWAP" not in perf

    def test_empty_file(self, tmp_path):
        """空 trades 文件"""
        trades_file = tmp_path / "empty.jsonl"
        trades_file.write_text("")
        tracker = PerformanceTracker(trades_file=trades_file, cache_ttl=0)
        perf = tracker.get_performance()
        assert len(perf) == 0
        stats = tracker.get_global_stats()
        assert stats["n_trades"] == 0

    def test_missing_file(self, tmp_path):
        """文件不存在"""
        tracker = PerformanceTracker(
            trades_file=tmp_path / "nonexistent.jsonl",
            cache_ttl=0,
        )
        perf = tracker.get_performance()
        assert len(perf) == 0

    def test_disk_cache(self, temp_trades, tmp_path):
        """磁盘缓存"""
        cache_file = tmp_path / "cache.json"
        tracker = PerformanceTracker(
            trades_file=temp_trades,
            cache_file=cache_file,
            cache_ttl=3600,
        )
        perf1 = tracker.get_performance()
        assert cache_file.exists()  # 缓存已写入

        # 第二个 tracker 从磁盘缓存读
        tracker2 = PerformanceTracker(
            trades_file=temp_trades,
            cache_file=cache_file,
            cache_ttl=3600,
        )
        perf2 = tracker2.get_performance()
        assert perf1["BTC"].n_trades == perf2["BTC"].n_trades
