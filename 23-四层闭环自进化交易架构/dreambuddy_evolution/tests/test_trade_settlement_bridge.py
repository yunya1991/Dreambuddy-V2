"""
TDD RED: TradeSettlementBridge 测试 (P2-S4 紧耦合流平仓反思回路)
蓝图: 四层闭环进化架构-最小阻力路径总览.md §1.7 + §1.13.6

TradeSettlementBridge 职责:
- store_snapshot(symbol, snapshot) — JSON 持久化
- retrieve_snapshot(symbol) — 检索并删除（消费后清除）
- _reconstruct_snapshot_from_trade(trade_rec) — 降级重建
- on_trade_settled(trade_rec) — 平仓回调: 检索snapshot→ReflectionEngine measure→reflect→learn→feedback
"""
import json
import pytest
from types import SimpleNamespace
from pathlib import Path


class TestTradeSettlementBridgeSnapshot:
    """snapshot 持久化存储与检索"""

    def test_store_and_retrieve_snapshot(self, tmp_path):
        """存储后能检索到 snapshot"""
        from dreambuddy_evolution.engines.trade_settlement_bridge import TradeSettlementBridge
        bridge = TradeSettlementBridge(snapshot_dir=str(tmp_path))
        snap = {"symbol": "BTC", "action": "long", "level0_dstar": "long", "ess_dir": "long",
                "cbr_top1_outcome": "TP", "cluster_id": "c1", "ess_id": "e1", "cbr_sim": 0.8,
                "u_open": 0.1}
        bridge.store_snapshot("BTC", snap)
        retrieved = bridge.retrieve_snapshot("BTC")
        assert retrieved is not None
        assert retrieved["action"] == "long"
        assert retrieved["level0_dstar"] == "long"

    def test_retrieve_consumes_snapshot(self, tmp_path):
        """检索后 snapshot 被删除（防重复反思）"""
        from dreambuddy_evolution.engines.trade_settlement_bridge import TradeSettlementBridge
        bridge = TradeSettlementBridge(snapshot_dir=str(tmp_path))
        snap = {"symbol": "ETH", "action": "short", "level0_dstar": "short"}
        bridge.store_snapshot("ETH", snap)
        # 第一次检索 → 有
        first = bridge.retrieve_snapshot("ETH")
        assert first is not None
        # 第二次检索 → None（已消费）
        second = bridge.retrieve_snapshot("ETH")
        assert second is None


class TestTradeSettlementBridgeOnTradeSettled:
    """平仓回调 → ReflectionEngine 反思回路"""

    def _make_trade_rec(self, direction="long", entry=50000.0, exit_p=51000.0, pnl=10.0,
                        pnl_pct=0.02, exit_reason="take_profit"):
        """构造 mock trade_rec"""
        return SimpleNamespace(
            inst_id="BTC-USDT-SWAP",
            direction=direction,
            entry_price=entry,
            exit_price=exit_p,
            pnl=pnl,
            pnl_pct=pnl_pct,
            entry_time="2026-09-04T00:00:00Z",
            exit_time="2026-09-04T01:00:00Z",
            exit_reason=exit_reason,
            confidence=0.8,
            hexagram="乾",
        )

    def test_on_trade_settled_tp(self, tmp_path):
        """盈利平仓 + 方向对 → CS≥0.7 & TP → ESS +0.02"""
        from dreambuddy_evolution.engines.trade_settlement_bridge import TradeSettlementBridge
        bridge = TradeSettlementBridge(snapshot_dir=str(tmp_path))
        # 存储 snapshot: d*=long, ess_dir=long, cbr=TP
        snap = {"symbol": "BTC", "action": "long", "level0_dstar": "long", "ess_dir": "long",
                "cbr_top1_outcome": "TP", "cluster_id": "c1", "ess_id": "e1", "cbr_sim": 0.8,
                "u_open": 0.1}
        bridge.store_snapshot("BTC", snap)
        # trade_rec: direction=long, pnl>0 → real_direction=long, real_outcome=TP
        trade_rec = self._make_trade_rec(direction="long", exit_p=51000.0, pnl=10.0)
        result = bridge.on_trade_settled(trade_rec)
        assert result["ess_delta"] == pytest.approx(0.02, abs=0.001)
        assert result["cs"] >= 0.7

    def test_on_trade_settled_sl(self, tmp_path):
        """亏损平仓 + 方向反 → CS≤-0.2 & SL → ESS -0.05"""
        from dreambuddy_evolution.engines.trade_settlement_bridge import TradeSettlementBridge
        bridge = TradeSettlementBridge(snapshot_dir=str(tmp_path))
        # snapshot: d*=long, ess_dir=long, cbr=TP (预测做多)
        snap = {"symbol": "BTC", "action": "long", "level0_dstar": "long", "ess_dir": "long",
                "cbr_top1_outcome": "TP", "cluster_id": "c1", "ess_id": "e1", "cbr_sim": 0.8,
                "u_open": 0.1}
        bridge.store_snapshot("BTC", snap)
        # trade_rec: direction=long 但 exit < entry → real_direction=short, SL
        trade_rec = self._make_trade_rec(direction="long", entry=50000.0, exit_p=49000.0,
                                         pnl=-10.0, pnl_pct=-0.02, exit_reason="stop_loss")
        result = bridge.on_trade_settled(trade_rec)
        assert result["ess_delta"] == pytest.approx(-0.05, abs=0.001)
        assert result["cs"] <= -0.2

    def test_on_trade_settled_no_snapshot_reconstruct(self, tmp_path):
        """无持久化 snapshot 时从 trade_rec 降级重建，不崩溃"""
        from dreambuddy_evolution.engines.trade_settlement_bridge import TradeSettlementBridge
        bridge = TradeSettlementBridge(snapshot_dir=str(tmp_path))
        trade_rec = self._make_trade_rec(direction="long", exit_p=51000.0, pnl=10.0)
        # 无 snapshot → 降级重建
        result = bridge.on_trade_settled(trade_rec)
        assert result is not None
        assert "ess_delta" in result
        assert "cs" in result
        # 降级模式下 ess_dir 缺失 → cos(ess,real)=0 → CS 降级但不崩溃

    def test_on_trade_settled_no_snapshot_fail_open(self, tmp_path):
        """trade_rec 无效（无 direction/pnl）时 FAIL-OPEN 返回空 ESS delta"""
        from dreambuddy_evolution.engines.trade_settlement_bridge import TradeSettlementBridge
        bridge = TradeSettlementBridge(snapshot_dir=str(tmp_path))
        # 构造无效 trade_rec（缺关键字段）
        bad_trade_rec = SimpleNamespace(inst_id="X")
        result = bridge.on_trade_settled(bad_trade_rec)
        assert result is not None
        assert result.get("ess_delta", 0) == 0.0  # FAIL-OPEN 中性

    def test_crash_fail_open(self, tmp_path):
        """内部异常时不崩溃，返回空 ESS delta"""
        from dreambuddy_evolution.engines.trade_settlement_bridge import TradeSettlementBridge
        bridge = TradeSettlementBridge(snapshot_dir=str(tmp_path))
        # 传入 None 触发异常
        result = bridge.on_trade_settled(None)
        assert result is not None
        assert result.get("ess_delta", 0) == 0.0
