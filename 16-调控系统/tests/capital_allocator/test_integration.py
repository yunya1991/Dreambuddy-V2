"""PACA 集成测试：Component.evaluate() 主流程 + 缓存 + 降级 + health_check。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_16_DIR = Path(__file__).resolve().parents[2]  # 16-调控系统/
_CORE_ROOT = _16_DIR / "core"
if str(_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(_CORE_ROOT))

from capital_allocator.component import CapitalAllocatorComponent  # noqa: E402
from capital_allocator.types import AllocatorMode  # noqa: E402


@pytest.fixture
def temp_trades(tmp_path):
    """创建临时 trades.jsonl"""
    trades_file = tmp_path / "trades.jsonl"
    trades = []
    # BTC: 10 胜 5 负，胜率 66.7%
    for i in range(10):
        trades.append({"coin": "BTC-USDT-SWAP", "pnl": 5.0, "pnl_pct": 3.0, "close_ts": float(i)})
    for i in range(5):
        trades.append({"coin": "BTC-USDT-SWAP", "pnl": -3.0, "pnl_pct": -2.0, "close_ts": float(100 + i)})
    # ETH: 3 胜 7 负，胜率 30%
    for i in range(3):
        trades.append({"coin": "ETH-USDT-SWAP", "pnl": 4.0, "pnl_pct": 2.0, "close_ts": float(200 + i)})
    for i in range(7):
        trades.append({"coin": "ETH-USDT-SWAP", "pnl": -6.0, "pnl_pct": -3.0, "close_ts": float(300 + i)})
    with open(trades_file, "w") as f:
        for t in trades:
            f.write(json.dumps(t) + "\n")
    return trades_file


@pytest.fixture
def component(temp_trades):
    """创建 PACA 组件（SHADOW 模式）"""
    return CapitalAllocatorComponent(
        mode=AllocatorMode.SHADOW,
        config_path=Path("/dev/null"),  # 不读配置文件，用默认
        cache_ttl=0,  # 不缓存，每次重新评估
    )


class TestComponentEvaluate:
    def test_evaluate_basic(self, component, temp_trades, monkeypatch):
        """evaluate() 基本流程"""
        # 替换 trades_file 路径
        component._tracker._trades_file = temp_trades
        component._tracker._cache_ttl = 0
        component._tracker._perf_cache = {}  # 清缓存
        component._tracker._last_load_ts = 0

        snap = component.evaluate()
        assert snap is not None
        assert snap.mode == AllocatorMode.SHADOW
        assert snap.total_trades_analyzed == 25
        assert "BTC" in snap.by_coin
        assert "ETH" in snap.by_coin

    def test_evaluate_global_stats(self, component, temp_trades):
        """全局统计正确"""
        component._tracker._trades_file = temp_trades
        component._tracker._cache_ttl = 0
        component._tracker._perf_cache = {}
        component._tracker._last_load_ts = 0

        snap = component.evaluate()
        # BTC 胜率 = 10/15 = 0.667
        assert snap.by_coin["BTC"].position_pct > 0
        # ETH 胜率 = 3/10 = 0.3 → Kelly 可能为 0
        assert snap.by_coin["ETH"].position_pct >= 0

    def test_evaluate_expansion_mult(self, component, temp_trades):
        """扩张乘数在 [0.5, 1.5]"""
        component._tracker._trades_file = temp_trades
        component._tracker._cache_ttl = 0
        component._tracker._perf_cache = {}
        component._tracker._last_load_ts = 0

        snap = component.evaluate()
        assert 0.5 <= snap.expansion_mult <= 1.5

    def test_evaluate_health(self, component, temp_trades):
        """健康等级"""
        component._tracker._trades_file = temp_trades
        component._tracker._cache_ttl = 0
        component._tracker._perf_cache = {}
        component._tracker._last_load_ts = 0

        snap = component.evaluate()
        assert snap.health in ["HEALTHY", "WARNING", "CRITICAL"]

    def test_cache_hit(self, component, temp_trades):
        """缓存命中：第二次 evaluate 不重算"""
        component._tracker._trades_file = temp_trades
        component._tracker._cache_ttl = 3600  # 长缓存
        component._tracker._perf_cache = {}
        component._tracker._last_load_ts = 0
        component._cache_ttl = 3600

        snap1 = component.evaluate()
        snap2 = component.evaluate()
        assert snap1 is snap2  # 同一对象（缓存命中）


class TestGetAdvice:
    def test_get_advice_existing_coin(self, component, temp_trades):
        """获取已有币种建议"""
        component._tracker._trades_file = temp_trades
        component._tracker._cache_ttl = 0
        component._tracker._perf_cache = {}
        component._tracker._last_load_ts = 0

        advice = component.get_allocation_advice("BTC", "bcrm", 1000.0)
        assert "position_pct" in advice
        assert "position_usdt" in advice
        assert "mode" in advice
        assert advice["mode"] == "shadow"
        assert advice["position_usdt"] > 0

    def test_get_advice_cold_start_coin(self, component, temp_trades):
        """冷启动币种（不在缓存中）→ 默认 10%"""
        component._tracker._trades_file = temp_trades
        component._tracker._cache_ttl = 0
        component._tracker._perf_cache = {}
        component._tracker._last_load_ts = 0

        advice = component.get_allocation_advice("SOL", "bcrm", 1000.0)
        assert advice["position_pct"] == 0.10
        assert advice["fallback_used"] is True
        assert "cold_start" in advice["reason"]

    def test_get_advice_fail_open(self, component):
        """异常 → FAIL-OPEN 返回默认"""
        # 不设 trades file → evaluate 会空 → 但 get_advice 内部 try/except
        component._tracker._trades_file = Path("/nonexistent/path")
        component._tracker._cache_ttl = 0
        component._tracker._perf_cache = {}
        component._tracker._last_load_ts = 0
        component._last_snapshot = None
        component._cache_ttl = 0

        advice = component.get_allocation_advice("BTC", "bcrm", 1000.0)
        # 应该返回某种建议（可能是默认或异常降级）
        assert "position_pct" in advice
        assert "position_usdt" in advice


class TestHealthCheck:
    def test_health_check_ok(self, component, temp_trades):
        """health_check 正常"""
        component._tracker._trades_file = temp_trades
        component._tracker._cache_ttl = 0
        component._tracker._perf_cache = {}
        component._tracker._last_load_ts = 0

        hc = component.health_check()
        assert hc["ok"] is True
        assert hc["mode"] == "shadow"
        assert hc["total_coins"] >= 2

    def test_health_check_no_data(self, tmp_path):
        """无数据 → CRITICAL"""
        comp = CapitalAllocatorComponent(
            mode=AllocatorMode.SHADOW,
            config_path=Path("/dev/null"),
            cache_ttl=0,
        )
        comp._tracker._trades_file = tmp_path / "nonexistent.jsonl"
        comp._tracker._cache_ttl = 0
        comp._tracker._perf_cache = {}
        comp._tracker._last_load_ts = 0
        comp._last_snapshot = None
        comp._cache_ttl = 0

        hc = comp.health_check()
        assert hc["ok"] is True  # evaluate 成功了（只是空数据）
        assert hc["health"] == "CRITICAL"


class TestExpansionMult:
    def test_global_expansion_mult(self, component, temp_trades):
        """get_global_expansion_mult"""
        component._tracker._trades_file = temp_trades
        component._tracker._cache_ttl = 0
        component._tracker._perf_cache = {}
        component._tracker._last_load_ts = 0

        mult = component.get_global_expansion_mult()
        assert 0.5 <= mult <= 1.5

    def test_global_expansion_mult_fail_open(self):
        """异常 → 1.0"""
        comp = CapitalAllocatorComponent(
            mode=AllocatorMode.SHADOW,
            config_path=Path("/dev/null"),
            cache_ttl=0,
        )
        # 不 evaluate 直接调
        mult = comp.get_global_expansion_mult()
        # 会触发 evaluate → 空数据 → expansion_mult=1.0（冷启动）
        assert mult == 1.0

    def test_coin_kelly_mult(self, component, temp_trades):
        """get_coin_kelly_mult"""
        component._tracker._trades_file = temp_trades
        component._tracker._cache_ttl = 0
        component._tracker._perf_cache = {}
        component._tracker._last_load_ts = 0

        mult = component.get_coin_kelly_mult("BTC")
        assert 0.0 <= mult <= 2.0

    def test_coin_kelly_mult_cold_start(self, component, temp_trades):
        """冷启动币种 → 1.0"""
        component._tracker._trades_file = temp_trades
        component._tracker._cache_ttl = 0
        component._tracker._perf_cache = {}
        component._tracker._last_load_ts = 0

        mult = component.get_coin_kelly_mult("UNKNOWN")
        assert mult == 1.0
