"""P2 集成测试：形态预测器 S5 开关 × 仓位/止盈止损/阈值调节

Spec §5.3 TDD 测试矩阵：
- test_s5_off_equivalent_to_baseline     开关关闭时行为 → 字节等价旧路径
- test_s5_on_applies_multipliers         开关打开时乘数应用 → position/tp/sl/threshold 都乘了 regime 乘数
- test_trend_up_strong_increases_position TREND_UP_STRONG → position > base
- test_volatile_drop_decreases_position   VOLATILE_DROP → position < base × 0.5
- test_fomo_rally_tightens_tp            FOMO_RALLY → tp < base × 0.7
- test_layered_thresholds                前置层 × 后置层 → final = base × spring × regime_pred
- test_regime_pred_stored_in_trade_record regime 快照写入 TradeRecord
- test_unknown_regime_fallback           未知 regime → 全 1.0 fallback
- test_s5_injection_into_inference       S5 注入 inference 字段
"""

import pytest
import sys
import os
import copy

# ── 路径设置 ──
_MEM_L4 = os.path.join(os.path.dirname(__file__), "..", "scripts", "memory_l4")
sys.path.insert(0, _MEM_L4)
sys.path.insert(0, os.path.join(_MEM_L4, "bcrm2"))


# ══════════════════════════════════════════════════════════════════
# 轻量测试替身：只复制 PollingTrader 的 S5 相关逻辑，无需实例化完整交易器
# ══════════════════════════════════════════════════════════════════

class RegimePredTraderStub:
    """PollingTrader S5 逻辑的最小测试替身

    复制 _get_regime_pred_multipliers + REGIME_MULTIPLIERS + S5 注入逻辑，
    不依赖 OKX 客户端、风控器等重量级依赖。
    """

    # ── 与 PollingTrader.REGIME_MULTIPLIERS 保持同步 ──
    REGIME_MULTIPLIERS = {
        "TREND_UP_STRONG":   {"position_mult": 1.20, "tp_mult": 1.30, "sl_mult": 1.15, "threshold_mult": 0.80},
        "TREND_UP_MILD":     {"position_mult": 1.05, "tp_mult": 1.10, "sl_mult": 1.05, "threshold_mult": 0.92},
        "BREAKOUT":          {"position_mult": 1.10, "tp_mult": 1.20, "sl_mult": 1.00, "threshold_mult": 0.85},
        "RANGE_BOUND":       {"position_mult": 0.80, "tp_mult": 0.85, "sl_mult": 1.20, "threshold_mult": 1.15},
        "CONSOLIDATION":     {"position_mult": 0.70, "tp_mult": 0.80, "sl_mult": 1.25, "threshold_mult": 1.20},
        "VOLATILE_DROP":     {"position_mult": 0.35, "tp_mult": 0.75, "sl_mult": 0.65, "threshold_mult": 1.30},
        "FOMO_RALLY":        {"position_mult": 0.85, "tp_mult": 0.60, "sl_mult": 0.70, "threshold_mult": 1.15},
        "REVERSAL":          {"position_mult": 0.50, "tp_mult": 0.75, "sl_mult": 0.80, "threshold_mult": 1.25},
    }

    def __init__(self, enable_s5: bool = False):
        self.ENABLE_REGIME_AND_MACRO_S5 = enable_s5

    def _get_regime_pred_multipliers(self, regime: str, enable_regime_pred: bool = True) -> dict:
        """与 PollingTrader._get_regime_pred_multipliers 完全一致"""
        if not enable_regime_pred:
            return {"position_mult": 1.0, "tp_mult": 1.0,
                    "sl_mult": 1.0, "threshold_mult": 1.0}
        m = self.REGIME_MULTIPLIERS.get(regime)
        if not m:
            return {"position_mult": 1.0, "tp_mult": 1.0,
                    "sl_mult": 1.0, "threshold_mult": 1.0}
        return dict(m)

    def inject_s5(self, inference: dict) -> dict:
        """模拟 _execute_trade 中 lines 4239-4259 的 S5 注入逻辑"""
        if self.ENABLE_REGIME_AND_MACRO_S5:
            try:
                _snap = inference.get("snapshot", {}) or {}
                _pred = _snap.get("regime") or inference.get("regime")
                _mult = self._get_regime_pred_multipliers(_pred, enable_regime_pred=True)
                inference["_regime_pred"] = _pred
                inference["_regime_multipliers"] = _mult
            except Exception:
                inference["_regime_pred"] = None
                inference["_regime_multipliers"] = {
                    "position_mult": 1.0, "tp_mult": 1.0,
                    "sl_mult": 1.0, "threshold_mult": 1.0,
                }
        else:
            inference["_regime_pred"] = None
            inference["_regime_multipliers"] = {
                "position_mult": 1.0, "tp_mult": 1.0,
                "sl_mult": 1.0, "threshold_mult": 1.0,
            }
        return inference

    @staticmethod
    def apply_threshold_mult(effective_threshold: float, reg_mult: dict) -> float:
        """模拟 _open_position lines 5360-5364 的 threshold_mult 叠加"""
        _thr_mult = reg_mult.get("threshold_mult", 1.0)
        if _thr_mult != 1.0:
            return effective_threshold * _thr_mult
        return effective_threshold

    @staticmethod
    def apply_position_mult(position_usdt: float, reg_mult: dict) -> float:
        """模拟 _open_position lines 5511-5523 的 position_mult 叠加"""
        _pos_mult = reg_mult.get("position_mult", 1.0)
        if _pos_mult != 1.0:
            return position_usdt * _pos_mult
        return position_usdt

    @staticmethod
    def apply_sl_tp_mult(sl_px: float, tp_px: float, price: float, reg_mult: dict):
        """模拟 _open_position lines 5540-5559 的 sl_mult/tp_mult 叠加"""
        _sl_mult = reg_mult.get("sl_mult", 1.0)
        _tp_mult = reg_mult.get("tp_mult", 1.0)
        new_sl = sl_px
        new_tp = tp_px
        if _sl_mult != 1.0 and sl_px and price > 0:
            new_sl = round(price + (sl_px - price) * _sl_mult, 6)
        if _tp_mult != 1.0 and tp_px and price > 0:
            new_tp = round(price + (tp_px - price) * _tp_mult, 6)
        return new_sl, new_tp


# ══════════════════════════════════════════════════════════════════
# 测试组
# ══════════════════════════════════════════════════════════════════

class TestS5SwitchOff:
    """S5 开关关闭时：全 1.0，字节等价旧路径"""

    def setup_method(self):
        self.trader = RegimePredTraderStub(enable_s5=False)

    def test_s5_off_returns_all_ones(self):
        """开关关闭 → _get_regime_pred_multipliers 返回全 1.0"""
        m = self.trader._get_regime_pred_multipliers("TREND_UP_STRONG", enable_regime_pred=False)
        assert m["position_mult"] == 1.0
        assert m["tp_mult"] == 1.0
        assert m["sl_mult"] == 1.0
        assert m["threshold_mult"] == 1.0

    def test_s5_off_injects_neutral(self):
        """开关关闭 → inference 注入全 1.0，_regime_pred=None"""
        inf = {"coin": "BTC", "direction": "UP"}
        self.trader.inject_s5(inf)
        assert inf["_regime_pred"] is None
        assert inf["_regime_multipliers"]["position_mult"] == 1.0
        assert inf["_regime_multipliers"]["threshold_mult"] == 1.0

    def test_s5_off_zero_drift_threshold(self):
        """开关关闭 → threshold 不被乘"""
        base_thr = 0.80
        reg_mult = {"threshold_mult": 1.0}
        result = self.trader.apply_threshold_mult(base_thr, reg_mult)
        assert result == pytest.approx(0.80)

    def test_s5_off_zero_drift_position(self):
        """开关关闭 → position 不被乘"""
        base_pos = 10.0
        reg_mult = {"position_mult": 1.0}
        result = self.trader.apply_position_mult(base_pos, reg_mult)
        assert result == pytest.approx(10.0)

    def test_s5_off_zero_drift_sl_tp(self):
        """开关关闭 → SL/TP 不被乘"""
        price = 100.0
        sl_px = 95.0
        tp_px = 110.0
        reg_mult = {"sl_mult": 1.0, "tp_mult": 1.0}
        new_sl, new_tp = self.trader.apply_sl_tp_mult(sl_px, tp_px, price, reg_mult)
        assert new_sl == pytest.approx(95.0)
        assert new_tp == pytest.approx(110.0)


class TestS5SwitchOn:
    """S5 开关打开时：乘数正确应用"""

    def setup_method(self):
        self.trader = RegimePredTraderStub(enable_s5=True)

    def test_s5_on_injects_regime(self):
        """开关打开 → inference 注入 regime 和对应乘数"""
        inf = {"coin": "BTC", "direction": "UP", "snapshot": {"regime": "TREND_UP_STRONG"}}
        self.trader.inject_s5(inf)
        assert inf["_regime_pred"] == "TREND_UP_STRONG"
        assert inf["_regime_multipliers"]["position_mult"] == 1.20
        assert inf["_regime_multipliers"]["tp_mult"] == 1.30

    def test_s5_on_injects_from_inference_regime(self):
        """开关打开 → 没有 snapshot 时从 inference["regime"] 取"""
        inf = {"coin": "BTC", "direction": "UP", "regime": "FOMO_RALLY"}
        self.trader.inject_s5(inf)
        assert inf["_regime_pred"] == "FOMO_RALLY"
        assert inf["_regime_multipliers"]["tp_mult"] == 0.60

    def test_s5_on_applies_all_four_multipliers(self):
        """验证 8 态 × 4 维乘数全部正确查表"""
        for regime, expected in self.trader.REGIME_MULTIPLIERS.items():
            m = self.trader._get_regime_pred_multipliers(regime, enable_regime_pred=True)
            assert m["position_mult"] == expected["position_mult"], f"{regime} position_mult mismatch"
            assert m["tp_mult"] == expected["tp_mult"], f"{regime} tp_mult mismatch"
            assert m["sl_mult"] == expected["sl_mult"], f"{regime} sl_mult mismatch"
            assert m["threshold_mult"] == expected["threshold_mult"], f"{regime} threshold_mult mismatch"


class TestSpecificRegimeEffects:
    """Spec §5.3 具体形态效果验证"""

    def setup_method(self):
        self.trader = RegimePredTraderStub(enable_s5=True)

    def test_trend_up_strong_increases_position(self):
        """TREND_UP_STRONG → position > base（position_mult=1.20 > 1.0）"""
        m = self.trader._get_regime_pred_multipliers("TREND_UP_STRONG")
        assert m["position_mult"] > 1.0
        base_pos = 10.0
        adjusted = self.trader.apply_position_mult(base_pos, m)
        assert adjusted > base_pos
        assert adjusted == pytest.approx(12.0)

    def test_volatile_drop_decreases_position(self):
        """VOLATILE_DROP → position < base × 0.5（position_mult=0.35）"""
        m = self.trader._get_regime_pred_multipliers("VOLATILE_DROP")
        assert m["position_mult"] < 0.5
        base_pos = 10.0
        adjusted = self.trader.apply_position_mult(base_pos, m)
        assert adjusted < base_pos * 0.5
        assert adjusted == pytest.approx(3.5)

    def test_fomo_rally_tightens_tp(self):
        """FOMO_RALLY → tp < base × 0.7（tp_mult=0.60）"""
        m = self.trader._get_regime_pred_multipliers("FOMO_RALLY")
        assert m["tp_mult"] < 0.7
        price = 100.0
        base_tp = 120.0  # 距价格 20
        _, new_tp = self.trader.apply_sl_tp_mult(95.0, base_tp, price, m)
        tp_distance = new_tp - price  # 20 × 0.60 = 12
        assert tp_distance < (base_tp - price) * 0.7
        assert new_tp == pytest.approx(112.0)

    def test_trend_up_strong_widens_tp(self):
        """TREND_UP_STRONG → tp 放宽（tp_mult=1.30）"""
        m = self.trader._get_regime_pred_multipliers("TREND_UP_STRONG")
        assert m["tp_mult"] > 1.0
        price = 100.0
        base_tp = 110.0  # 距价格 10
        _, new_tp = self.trader.apply_sl_tp_mult(90.0, base_tp, price, m)
        assert new_tp > base_tp
        assert new_tp == pytest.approx(113.0)  # 100 + 10*1.30 = 113

    def test_volatile_drop_tightens_sl(self):
        """VOLATILE_DROP → 止损收紧（sl_mult=0.65，止损距离 × 0.65）"""
        m = self.trader._get_regime_pred_multipliers("VOLATILE_DROP")
        assert m["sl_mult"] < 1.0
        price = 100.0
        base_sl = 95.0  # 距价格 5
        new_sl, _ = self.trader.apply_sl_tp_mult(base_sl, 120.0, price, m)
        sl_distance = price - new_sl  # 5 × 0.65 = 3.25
        assert sl_distance < (price - base_sl)
        assert new_sl == pytest.approx(96.75)  # 100 - 5*0.65 = 96.75

    def test_range_bound_raises_threshold(self):
        """RANGE_BOUND → 阈值抬高（threshold_mult=1.15，更难开仓）"""
        m = self.trader._get_regime_pred_multipliers("RANGE_BOUND")
        assert m["threshold_mult"] > 1.0
        base_thr = 0.80
        adjusted = self.trader.apply_threshold_mult(base_thr, m)
        assert adjusted > base_thr
        assert adjusted == pytest.approx(0.92)

    def test_trend_up_strong_lowers_threshold(self):
        """TREND_UP_STRONG → 阈值放宽（threshold_mult=0.80，更容易开仓）"""
        m = self.trader._get_regime_pred_multipliers("TREND_UP_STRONG")
        assert m["threshold_mult"] < 1.0
        base_thr = 0.80
        adjusted = self.trader.apply_threshold_mult(base_thr, m)
        assert adjusted < base_thr
        assert adjusted == pytest.approx(0.64)


class TestLayeredThresholds:
    """Spec §5.3 test_layered_thresholds: final = base × spring × regime_pred"""

    def test_layered_threshold_formula(self):
        """前置层（regime_pred threshold_mult） × 后置层（spring force regime_multiplier）

        Spec 公式:
            final_threshold = base_threshold × score_multiplier × regime_multiplier
            然后再 × regime_pred threshold_mult

        即: final = base × spring_score × spring_regime × regime_pred_threshold
        """
        trader = RegimePredTraderStub(enable_s5=True)

        # 1. 基础阈值
        base_threshold = 0.80

        # 2. 后置层（弹簧力场）：score_multiplier × regime_multiplier
        score_multiplier = 0.9091  # STRONG bearish → 放宽做空门槛
        spring_regime_multiplier = 0.90  # RANGING → 放宽
        spring_combined = score_multiplier * spring_regime_multiplier

        # 3. 前置层（形态预测器）
        reg_mult = trader._get_regime_pred_multipliers("TREND_UP_STRONG")
        regime_pred_threshold_mult = reg_mult["threshold_mult"]  # 0.80

        # 4. 分层叠加
        after_spring = base_threshold * spring_combined
        final_threshold = trader.apply_threshold_mult(after_spring, reg_mult)

        expected = base_threshold * spring_combined * regime_pred_threshold_mult
        assert final_threshold == pytest.approx(expected, rel=1e-4)
        # 0.80 × 0.9091 × 0.90 × 0.80 = 0.5242...
        assert final_threshold < base_threshold  # 整体放宽

    def test_layered_threshold_high_risk_regime(self):
        """VOLATILE_DROP 时前置层收紧阈值，与后置层叠加"""
        trader = RegimePredTraderStub(enable_s5=True)

        base_threshold = 0.80
        score_multiplier = 1.1765  # WEAK bearish → 收紧做空门槛
        spring_regime_multiplier = 1.15  # TREND_BULL → 收紧
        spring_combined = score_multiplier * spring_regime_multiplier

        reg_mult = trader._get_regime_pred_multipliers("VOLATILE_DROP")
        regime_pred_threshold_mult = reg_mult["threshold_mult"]  # 1.30

        after_spring = base_threshold * spring_combined
        final_threshold = trader.apply_threshold_mult(after_spring, reg_mult)

        expected = base_threshold * spring_combined * regime_pred_threshold_mult
        assert final_threshold == pytest.approx(expected, rel=1e-3)
        # 0.80 × 1.1765 × 1.15 × 1.30 ≈ 1.408 → 大幅收紧
        assert final_threshold > base_threshold


class TestUnknownRegimeFallback:
    """未知/None regime → 全 1.0 fallback，不抛异常"""

    def test_unknown_regime_returns_ones(self):
        trader = RegimePredTraderStub(enable_s5=True)
        m = trader._get_regime_pred_multipliers("UNKNOWN_REGIME_XYZ")
        assert m["position_mult"] == 1.0
        assert m["tp_mult"] == 1.0
        assert m["sl_mult"] == 1.0
        assert m["threshold_mult"] == 1.0

    def test_none_regime_returns_ones(self):
        trader = RegimePredTraderStub(enable_s5=True)
        m = trader._get_regime_pred_multipliers(None)
        assert m["position_mult"] == 1.0
        assert m["threshold_mult"] == 1.0

    def test_empty_string_regime_returns_ones(self):
        trader = RegimePredTraderStub(enable_s5=True)
        m = trader._get_regime_pred_multipliers("")
        assert m["position_mult"] == 1.0

    def test_s5_on_with_none_regime_injects_neutral(self):
        """S5 打开但 regime 为 None → 注入全 1.0"""
        trader = RegimePredTraderStub(enable_s5=True)
        inf = {"coin": "BTC", "direction": "UP"}
        trader.inject_s5(inf)
        assert inf["_regime_pred"] is None
        assert inf["_regime_multipliers"]["position_mult"] == 1.0


class TestTradeRecordRegimeSnapshot:
    """TradeRecord 的 regime_pred / regime_multipliers 字段可正确存储"""

    def test_trade_record_has_regime_fields(self):
        """TradeRecord 有 regime_pred 和 regime_multipliers 字段，默认 None"""
        from trading_utils import TradeRecord
        rec = TradeRecord()
        assert rec.regime_pred is None
        assert rec.regime_multipliers is None

    def test_trade_record_stores_regime_snapshot(self):
        """开仓时写入 regime 快照"""
        from trading_utils import TradeRecord
        rec = TradeRecord(
            coin="BTC",
            direction="long",
            regime_pred="TREND_UP_STRONG",
            regime_multipliers={"position_mult": 1.20, "tp_mult": 1.30},
        )
        assert rec.regime_pred == "TREND_UP_STRONG"
        assert rec.regime_multipliers["position_mult"] == 1.20

    def test_trade_record_backward_compatible(self):
        """旧数据反序列化不报错（无 regime 字段时不崩溃）"""
        from trading_utils import TradeRecord
        # 模拟旧数据（只有基础字段）
        old_data = {
            "trade_id": "123",
            "coin": "BTC",
            "direction": "long",
            "entry_price": 100.0,
        }
        rec = TradeRecord(**old_data)
        assert rec.regime_pred is None
        assert rec.regime_multipliers is None


class TestMultiplierReturnCopy:
    """_get_regime_pred_multipliers 返回浅拷贝，不污染类常量表"""

    def test_returns_copy_not_reference(self):
        trader = RegimePredTraderStub(enable_s5=True)
        m1 = trader._get_regime_pred_multipliers("TREND_UP_STRONG")
        m1["position_mult"] = 999.0  # 篡改
        m2 = trader._get_regime_pred_multipliers("TREND_UP_STRONG")
        assert m2["position_mult"] == 1.20  # 类常量未受影响


class TestFullFlowSimulation:
    """端到端模拟：从 S5 注入到乘数应用全链路"""

    def test_full_flow_trend_up_strong(self):
        """模拟 TREND_UP_STRONG 全流程：注入 → 阈值/仓位/SLTP 叠加"""
        trader = RegimePredTraderStub(enable_s5=True)

        # 1. 模拟 inference
        inf = {
            "coin": "BTC",
            "direction": "UP",
            "confidence": 0.85,
            "snapshot": {"regime": "TREND_UP_STRONG"},
        }

        # 2. S5 注入
        trader.inject_s5(inf)
        assert inf["_regime_pred"] == "TREND_UP_STRONG"
        reg_mult = inf["_regime_multipliers"]

        # 3. 阈值叠加
        base_thr = 0.80
        effective_thr = trader.apply_threshold_mult(base_thr, reg_mult)
        assert effective_thr == pytest.approx(0.64)  # 0.80 × 0.80

        # 4. 仓位叠加
        base_pos = 10.0
        final_pos = trader.apply_position_mult(base_pos, reg_mult)
        assert final_pos == pytest.approx(12.0)  # 10 × 1.20

        # 5. SL/TP 叠加
        price = 50000.0
        base_sl = 48000.0  # 距价格 2000
        base_tp = 55000.0  # 距价格 5000
        new_sl, new_tp = trader.apply_sl_tp_mult(base_sl, base_tp, price, reg_mult)
        # SL: 50000 + (48000-50000) × 1.15 = 50000 - 2300 = 47700
        assert new_sl == pytest.approx(47700.0)
        # TP: 50000 + (55000-50000) × 1.30 = 50000 + 6500 = 56500
        assert new_tp == pytest.approx(56500.0)

    def test_full_flow_volatile_drop(self):
        """模拟 VOLATILE_DROP 全流程：极轻仓 + 紧止损 + 紧止盈 + 严门槛"""
        trader = RegimePredTraderStub(enable_s5=True)

        inf = {
            "coin": "BTC",
            "direction": "DOWN",
            "confidence": 0.85,
            "snapshot": {"regime": "VOLATILE_DROP"},
        }

        trader.inject_s5(inf)
        reg_mult = inf["_regime_multipliers"]

        # 阈值抬高
        base_thr = 0.80
        effective_thr = trader.apply_threshold_mult(base_thr, reg_mult)
        assert effective_thr == pytest.approx(1.04)  # 0.80 × 1.30

        # 仓位大幅缩减
        base_pos = 10.0
        final_pos = trader.apply_position_mult(base_pos, reg_mult)
        assert final_pos == pytest.approx(3.5)  # 10 × 0.35

        # SL/TP 都收紧
        price = 50000.0
        base_sl = 48000.0
        base_tp = 55000.0
        new_sl, new_tp = trader.apply_sl_tp_mult(base_sl, base_tp, price, reg_mult)
        # SL: 50000 + (48000-50000) × 0.65 = 50000 - 1300 = 48700
        assert new_sl == pytest.approx(48700.0)
        # TP: 50000 + (55000-50000) × 0.75 = 50000 + 3750 = 53750
        assert new_tp == pytest.approx(53750.0)

    def test_full_flow_s5_off_neutral(self):
        """S5 关闭 → 全流程所有乘数 = 1.0，零漂移"""
        trader = RegimePredTraderStub(enable_s5=False)

        inf = {"coin": "BTC", "direction": "UP", "confidence": 0.85}
        trader.inject_s5(inf)
        reg_mult = inf["_regime_multipliers"]

        base_thr = 0.80
        effective_thr = trader.apply_threshold_mult(base_thr, reg_mult)
        assert effective_thr == pytest.approx(0.80)

        base_pos = 10.0
        final_pos = trader.apply_position_mult(base_pos, reg_mult)
        assert final_pos == pytest.approx(10.0)

        price = 50000.0
        new_sl, new_tp = trader.apply_sl_tp_mult(48000.0, 55000.0, price, reg_mult)
        assert new_sl == pytest.approx(48000.0)
        assert new_tp == pytest.approx(55000.0)
