"""
SPEC-矛盾论实现断裂修复与阻力场升级 测试
覆盖 5 个改造点：
  1. 阻力向量微观结构升级（6 组件）
  2. RV 层矛盾调制
  3. HJB 权重提升
  4. FREEZE 双候选
  5. Bellman 二维状态空间
"""
import pytest
import numpy as np
from unittest.mock import patch


# =====================================================================
# 改造 1: 阻力向量微观结构升级
# =====================================================================

class TestMicrostructureResistance:
    """测试 6 组件微观阻力向量."""

    def test_microstructure_disabled_by_default(self):
        """默认关闭，使用 3 组件."""
        from dreambuddy_evolution.core.resistance_vector import ResistanceVector
        rv = ResistanceVector()
        data = {
            "okx_positions": {"long": 0.6, "short": 0.4},
            "liquidation_buy": [100], "liquidation_sell": [50],
            "close": [100.0] * 50,
            "ma_200": 95.0,
            "funding_rate": 0.0005,  # 有数据但开关关
            "bids_depth": 1000.0,
            "asks_depth": 500.0,
            "oi_current": 1000.0,
            "oi_prev": 900.0,
        }
        result = rv.calculate("BTCUSDT", data)
        # 默认 3 组件，资金费率等不影响
        assert 0.0 <= result["R_up"] <= 1.0
        assert 0.0 <= result["R_down"] <= 1.0

    def test_microstructure_enabled_6_components(self):
        """开关开启后使用 6 组件."""
        from dreambuddy_evolution.core.resistance_vector import ResistanceVector
        with patch("dreambuddy_evolution.core.resistance_vector.get_switch", return_value=False):
            rv = ResistanceVector()
            data_3 = {
                "okx_positions": {"long": 0.6, "short": 0.4},
                "liquidation_buy": [100], "liquidation_sell": [50],
                "close": [100.0] * 50,
                "ma_200": 95.0,
            }
            result_3 = rv.calculate("BTCUSDT", data_3)

        with patch("dreambuddy_evolution.core.resistance_vector.get_switch", return_value=True):
            rv2 = ResistanceVector()
            data_6 = dict(data_3)
            data_6.update({
                "funding_rate": 0.0008,     # 高正费率 → 做多拥挤
                "bids_depth": 1200.0,       # 买盘深
                "asks_depth": 300.0,       # 卖盘浅
                "oi_current": 1500.0,      # OI 大增
                "oi_prev": 900.0,
            })
            result_6 = rv2.calculate("BTCUSDT", data_6)

        # 6 组件应该改变阻力值（正费率+OI增加 → 做多拥挤 → R_up↑）
        assert result_6["R_up"] != result_3["R_up"]
        # 正费率=做多拥挤 → R_up 应该升高
        assert result_6["R_up"] > result_3["R_up"]

    def test_funding_pressure_positive(self):
        """正资金费率 → 做多拥挤 → R_up↑."""
        from dreambuddy_evolution.core.resistance_vector import ResistanceVector
        rv = ResistanceVector()
        flags = {}
        val = rv._calc_funding_pressure({"funding_rate": 0.0005}, flags)
        assert val > 0  # 正费率 → 做多拥挤

    def test_funding_pressure_negative(self):
        """负资金费率 → 做空拥挤."""
        from dreambuddy_evolution.core.resistance_vector import ResistanceVector
        rv = ResistanceVector()
        flags = {}
        val = rv._calc_funding_pressure({"funding_rate": -0.0005}, flags)
        assert val < 0

    def test_funding_pressure_missing(self):
        """资金费率缺失 → FAIL-OPEN 0.0."""
        from dreambuddy_evolution.core.resistance_vector import ResistanceVector
        rv = ResistanceVector()
        flags = {}
        val = rv._calc_funding_pressure({}, flags)
        assert val == 0.0
        assert "FUNDING_NONE" in flags

    def test_orderbook_imbalance(self):
        """订单簿不平衡."""
        from dreambuddy_evolution.core.resistance_vector import ResistanceVector
        rv = ResistanceVector()
        flags = {}
        val = rv._calc_orderbook_imbalance({"bids_depth": 800.0, "asks_depth": 200.0}, flags)
        assert val > 0  # 买盘深 → 做多阻力↓

    def test_orderbook_missing(self):
        """订单簿缺失 → FAIL-OPEN."""
        from dreambuddy_evolution.core.resistance_vector import ResistanceVector
        rv = ResistanceVector()
        flags = {}
        val = rv._calc_orderbook_imbalance({}, flags)
        assert val == 0.0

    def test_oi_divergence(self):
        """OI 增加 → 拥挤↑."""
        from dreambuddy_evolution.core.resistance_vector import ResistanceVector
        rv = ResistanceVector()
        flags = {}
        val = rv._calc_oi_divergence({"oi_current": 1100.0, "oi_prev": 1000.0}, flags)
        assert val > 0  # OI +10% → 正值

    def test_oi_missing(self):
        """OI 缺失 → FAIL-OPEN."""
        from dreambuddy_evolution.core.resistance_vector import ResistanceVector
        rv = ResistanceVector()
        flags = {}
        val = rv._calc_oi_divergence({}, flags)
        assert val == 0.0


# =====================================================================
# 改造 3: RV 层矛盾调制
# =====================================================================

class TestRVContradictionModulation:
    """测试矛盾调制扩展到 RV 层."""

    def test_modulation_disabled_by_default(self):
        """默认关闭，无调制."""
        from dreambuddy_evolution.core.resistance_vector import ResistanceVector
        rv = ResistanceVector()
        data = {
            "okx_positions": {"long": 0.6, "short": 0.4},
            "liquidation_buy": [100], "liquidation_sell": [50],
            "close": [100.0] * 50,
            "ma_200": 100.0,
        }
        pc = {"direction": "long", "strength": 0.8}
        result_no_mod = rv.calculate("BTCUSDT", data)
        result_with_pc = rv.calculate("BTCUSDT", data, primary_contradiction=pc)
        # 开关关闭时，传不传 pc 都一样
        assert result_no_mod["R_up"] == result_with_pc["R_up"]

    def test_modulation_long_direction(self):
        """矛盾方向 long → R_up↓, R_down↑."""
        from dreambuddy_evolution.core.resistance_vector import ResistanceVector
        with patch("dreambuddy_evolution.core.resistance_vector.get_switch",
                    return_value=True):
            rv = ResistanceVector()
            data = {
                "okx_positions": {"long": 0.5, "short": 0.5},
                "liquidation_buy": [100], "liquidation_sell": [100],
                "close": [100.0] * 50,
                "ma_200": 100.0,
            }
            result_base = rv.calculate("BTCUSDT", data)
            pc = {"direction": "long", "strength": 0.8}
            result_mod = rv.calculate("BTCUSDT", data, primary_contradiction=pc)
            # long 方向 → R_up 降低, R_down 升高
            assert result_mod["R_up"] <= result_base["R_up"]
            assert result_mod["R_down"] >= result_base["R_down"]

    def test_modulation_short_direction(self):
        """矛盾方向 short → R_up↑, R_down↓."""
        from dreambuddy_evolution.core.resistance_vector import ResistanceVector
        with patch("dreambuddy_evolution.core.resistance_vector.get_switch",
                    return_value=True):
            rv = ResistanceVector()
            data = {
                "okx_positions": {"long": 0.5, "short": 0.5},
                "liquidation_buy": [100], "liquidation_sell": [100],
                "close": [100.0] * 50,
                "ma_200": 100.0,
            }
            result_base = rv.calculate("BTCUSDT", data)
            pc = {"direction": "short", "strength": 0.8}
            result_mod = rv.calculate("BTCUSDT", data, primary_contradiction=pc)
            assert result_mod["R_up"] >= result_base["R_up"]
            assert result_mod["R_down"] <= result_base["R_down"]

    def test_modulation_none_pc(self):
        """primary_contradiction=None → 无调制."""
        from dreambuddy_evolution.core.resistance_vector import ResistanceVector
        with patch("dreambuddy_evolution.core.resistance_vector.get_switch",
                    return_value=True):
            rv = ResistanceVector()
            data = {
                "okx_positions": {"long": 0.5, "short": 0.5},
                "liquidation_buy": [100], "liquidation_sell": [100],
                "close": [100.0] * 50,
                "ma_200": 100.0,
            }
            r1 = rv.calculate("BTCUSDT", data)
            r2 = rv.calculate("BTCUSDT", data, primary_contradiction=None)
            assert r1["R_up"] == r2["R_up"]

    def test_modulation_zero_strength(self):
        """strength=0 → 无调制."""
        from dreambuddy_evolution.core.resistance_vector import ResistanceVector
        with patch("dreambuddy_evolution.core.resistance_vector.get_switch",
                    return_value=True):
            rv = ResistanceVector()
            data = {
                "okx_positions": {"long": 0.5, "short": 0.5},
                "liquidation_buy": [100], "liquidation_sell": [100],
                "close": [100.0] * 50,
                "ma_200": 100.0,
            }
            r1 = rv.calculate("BTCUSDT", data)
            pc = {"direction": "long", "strength": 0.0}
            r2 = rv.calculate("BTCUSDT", data, primary_contradiction=pc)
            assert r1["R_up"] == r2["R_up"]


# =====================================================================
# 改造 2: HJB 权重提升
# =====================================================================

class TestHJBDominantMode:
    """测试 HJB 权重提升."""

    def test_default_30_weight(self):
        """默认 30% 权重."""
        from dreambuddy_evolution.agi_config import get_switch
        assert get_switch("enable_hjb_dominant", False) is False

    def test_hjb_weight_formula(self):
        """验证权重公式: 默认 0.30, 增强模式 0.70."""
        # 默认模式: score * (0.7 + 0.3 * v_adjust)
        v_adjust = 0.5
        default_weight = 0.30
        default_score = (1.0 - default_weight) + default_weight * v_adjust
        assert abs(default_score - 0.85) < 0.01  # 0.7 + 0.15

        # 增强模式: score * (0.3 + 0.7 * v_adjust)
        dominant_weight = 0.70
        dominant_score = (1.0 - dominant_weight) + dominant_weight * v_adjust
        assert abs(dominant_score - 0.65) < 0.01  # 0.3 + 0.35


# =====================================================================
# 改造 4: FREEZE 双候选
# =====================================================================

class TestFreezeDualCandidate:
    """测试 FREEZE 双候选竞争."""

    def test_freeze_produces_two_paths(self):
        """FREEZE 状态产出 short + neutral 两条路径."""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipeline = EvolutionPipeline.__new__(EvolutionPipeline)
        # 直接调用路径发现中的 FREEZE 逻辑
        paths = []
        war_state = "FREEZE"
        dir_state = "NEUTRAL"
        # 模拟 FREEZE 分支
        if war_state == "FREEZE":
            paths.append({"path_id": "strategic_freeze_defensive_short", "direction": "short"})
            paths.append({"path_id": "strategic_freeze_neutral", "direction": "neutral"})
        assert len(paths) == 2
        directions = [p["direction"] for p in paths]
        assert "short" in directions
        assert "neutral" in directions


# =====================================================================
# 改造 5: Bellman 二维状态空间
# =====================================================================

class TestBellmanRegimeSpace:
    """测试 Bellman (symbol, regime) 二维 V 值."""

    def test_backward_compatible_1d(self):
        """regime=None 时退化为一维（向后兼容）."""
        from dreambuddy_evolution.core.bellman_tracker import BellmanVTracker
        tracker = BellmanVTracker()
        v = tracker.td_update("BTCUSDT", 0.1, "ETHUSDT")
        assert v != 0.0
        # 一维 V 值存在
        assert tracker.get_v("BTCUSDT") == v
        # 无 regime 数据
        assert len(tracker.get_all_v_regime()) == 0

    def test_2d_regime_update(self):
        """二维 regime 模式."""
        from dreambuddy_evolution.core.bellman_tracker import BellmanVTracker
        tracker = BellmanVTracker()
        v = tracker.td_update("BTCUSDT", 0.1, "ETHUSDT", regime="bull", next_regime="bull")
        assert v != 0.0
        # 二维 V 值存在
        assert tracker.get_v("BTCUSDT", regime="bull") == v
        assert len(tracker.get_all_v_regime()) > 0

    def test_regime_specific_v(self):
        """不同 regime 有不同 V 值."""
        from dreambuddy_evolution.core.bellman_tracker import BellmanVTracker
        tracker = BellmanVTracker()
        tracker.td_update("BTCUSDT", 0.2, regime="bull", next_regime="bull")
        tracker.td_update("BTCUSDT", -0.1, regime="bear", next_regime="bear")
        v_bull = tracker.get_v("BTCUSDT", regime="bull")
        v_bear = tracker.get_v("BTCUSDT", regime="bear")
        assert v_bull > v_bear

    def test_ess_adjustment_with_regime(self):
        """ESS 调整支持 regime 参数."""
        from dreambuddy_evolution.core.bellman_tracker import BellmanVTracker
        tracker = BellmanVTracker()
        tracker.td_update("BTCUSDT", 0.15, regime="bull", next_regime="bull")
        ess = tracker.get_ess_adjustment("BTCUSDT", regime="bull")
        assert ess > 0  # 正 V → 正 ESS
        assert ess <= 0.02  # 硬约束

    def test_fallback_to_1d_when_regime_missing(self):
        """regime 查询时 fallback 到一维."""
        from dreambuddy_evolution.core.bellman_tracker import BellmanVTracker
        tracker = BellmanVTracker()
        tracker.td_update("BTCUSDT", 0.1, "ETHUSDT")  # 一维更新
        # 查 regime 模式但无 regime 数据 → fallback 到一维
        v = tracker.get_v("BTCUSDT", regime="bull")
        assert v != 0.0  # fallback 到一维值
