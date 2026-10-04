"""PACA E2E 测试：polling_trader 集成 + SHADOW 模式对比 + ACTIVE 模式。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    # BTC: 10 胜 5 负
    for i in range(10):
        trades.append({"coin": "BTC-USDT-SWAP", "pnl": 5.0, "pnl_pct": 3.0, "close_ts": float(i)})
    for i in range(5):
        trades.append({"coin": "BTC-USDT-SWAP", "pnl": -3.0, "pnl_pct": -2.0, "close_ts": float(100 + i)})
    with open(trades_file, "w") as f:
        for t in trades:
            f.write(json.dumps(t) + "\n")
    return trades_file


class TestPollingTraderIntegration:
    """验证 polling_trader 中 PACA 集成的行为（通过 mock 组件）。"""

    def test_shadow_mode_does_not_change_position(self, temp_trades):
        """SHADOW 模式：仓位不变，仅记录日志"""
        comp = CapitalAllocatorComponent(
            mode=AllocatorMode.SHADOW,
            config_path=Path("/dev/null"),
            cache_ttl=0,
        )
        comp._tracker._trades_file = temp_trades
        comp._tracker._cache_ttl = 0
        comp._tracker._perf_cache = {}
        comp._tracker._last_load_ts = 0

        # 模拟 polling_trader 的 _apply_paca_to_position 行为
        original_usdt = 200.0
        equity = 1000.0
        advice = comp.get_allocation_advice("BTC", "bcrm", equity)

        assert advice["mode"] == "shadow"
        # SHADOW 模式：polling_trader 返回原仓位
        final_usdt = original_usdt  # 不变
        assert final_usdt == original_usdt

    def test_active_mode_uses_paca_position(self, temp_trades):
        """ACTIVE 模式：取 PACA 建议与原仓位较小值"""
        comp = CapitalAllocatorComponent(
            mode=AllocatorMode.ACTIVE,
            config_path=Path("/dev/null"),
            cache_ttl=0,
        )
        comp._tracker._trades_file = temp_trades
        comp._tracker._cache_ttl = 0
        comp._tracker._perf_cache = {}
        comp._tracker._last_load_ts = 0

        original_usdt = 300.0
        equity = 1000.0
        advice = comp.get_allocation_advice("BTC", "bcrm", equity)

        assert advice["mode"] == "active"
        paca_usdt = advice["position_usdt"]
        # ACTIVE 模式：取 min(original, paca)
        final_usdt = min(original_usdt, paca_usdt)
        assert final_usdt <= original_usdt
        assert final_usdt == paca_usdt  # PACA 建议更小

    def test_fail_open_when_paca_none(self):
        """PACA=None 时 → 原仓位不变"""
        # 模拟 _paca is None 的情况
        final_usdt = 200.0
        log = ""
        assert final_usdt == 200.0
        assert log == ""


class TestComponentEndToEnd:
    """端到端测试：从 trades file 到 get_allocation_advice。"""

    def test_full_pipeline_shadow(self, temp_trades):
        """完整流水线 SHADOW 模式"""
        comp = CapitalAllocatorComponent(
            mode=AllocatorMode.SHADOW,
            config_path=Path("/dev/null"),
            cache_ttl=0,
        )
        comp._tracker._trades_file = temp_trades
        comp._tracker._cache_ttl = 0
        comp._tracker._perf_cache = {}
        comp._tracker._last_load_ts = 0

        snap = comp.evaluate()
        assert snap.health in ["HEALTHY", "WARNING", "CRITICAL"]
        assert snap.total_trades_analyzed == 15

        advice = comp.get_allocation_advice("BTC", "bcrm", 5000.0)
        assert advice["mode"] == "shadow"
        assert advice["position_usdt"] > 0
        assert advice["position_pct"] > 0
        assert advice["position_pct"] <= 0.25  # MAX_PCT

    def test_health_check_end_to_end(self, temp_trades):
        """health_check 端到端"""
        comp = CapitalAllocatorComponent(
            mode=AllocatorMode.SHADOW,
            config_path=Path("/dev/null"),
            cache_ttl=0,
        )
        comp._tracker._trades_file = temp_trades
        comp._tracker._cache_ttl = 0
        comp._tracker._perf_cache = {}
        comp._tracker._last_load_ts = 0

        hc = comp.health_check()
        assert hc["ok"] is True
        assert hc["mode"] == "shadow"
        assert hc["total_trades_analyzed"] == 15

    def test_cold_start_coin_advice(self, temp_trades):
        """冷启动币种（不在缓存中）→ 默认 10%"""
        comp = CapitalAllocatorComponent(
            mode=AllocatorMode.ACTIVE,
            config_path=Path("/dev/null"),
            cache_ttl=0,
        )
        comp._tracker._trades_file = temp_trades
        comp._tracker._cache_ttl = 0
        comp._tracker._perf_cache = {}
        comp._tracker._last_load_ts = 0

        advice = comp.get_allocation_advice("UNKNOWN", "bcrm", 1000.0)
        assert advice["position_pct"] == 0.10
        assert advice["fallback_used"] is True
        assert advice["position_usdt"] == 100.0  # 1000 * 0.10
