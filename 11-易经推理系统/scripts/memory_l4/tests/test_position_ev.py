#!/usr/bin/env python3
"""
test_position_ev.py — Phase B TDD 测试集
对应 Spec §5.2: EV 风险价值雷达（开关 S2 = enable_ev_radar）

RED 失败原因: calc_position_ev 不存在 / _execute_trade 插入点不存在 / 开关短路分支不存在。
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scripts.memory_l4.polling_trader import PollingTrader  # noqa: E402
from scripts.memory_l4.trading_utils import RiskManager  # noqa: E402


# ──────────────────────────────────────────────────────────
# 轻量 mock 构造（同 Phase A 风格，避免真实初始化）
# ──────────────────────────────────────────────────────────
def _make_trader(coins=None, max_positions=3, enable_ev_radar=True,
                 enable_mode_switch=True):
    with patch.object(PollingTrader, "__init__", lambda self, *a, **kw: None):
        t = PollingTrader.__new__(PollingTrader)

    t.coins = list(coins or ["BTC", "SOL", "XAU"])
    t.max_positions = max_positions

    # 4 个开关
    t.enable_mode_switch = enable_mode_switch
    t.enable_ev_radar = enable_ev_radar
    t.enable_multi_horizon = True
    t.enable_ranked_tp = True

    # 持仓跟踪 + OKX
    t.position_tracker = MagicMock(spec=[
        "all_open_positions", "all_closed_positions",
        "get_open_position", "has_open_position", "is_in_cooldown",
    ])
    t.position_tracker.all_open_positions.return_value = []
    t.okx_client = MagicMock()
    t.okx_client.cfg = {"default_leverage": 3}
    t.okx_client.get_positions.return_value = {"ok": True, "positions": []}

    # 黑名单
    t.blacklist_coins = set()
    t.dynamic_blacklist = {}
    t._check_dynamic_blacklist = MagicMock(return_value=(False, ""))

    # 计数/缓存
    t._count_total_positions = MagicMock(return_value=0)
    t._cycle_idx = 0
    t._mode_cache = {}

    # 日志 & 工具（默认 MagicMock，测试可 side_effect 收集）
    t._log = MagicMock()
    t.COOLDOWN_SEC = 8 * 3600
    t.POSITION_PROTECTION_HOURS = 6.0
    t.EXIT_CONFIRM_REQUIRED = 2

    # 离场常量（与 __init__ 中的 tag 保持一致）
    t.EXIT_ACT_SIGNAL_REVERSE = "signal_reverse"
    t.EXIT_ACT_YIJING_FORCE_CLOSE = "yijing_force_close"
    t.EXIT_ACT_P3_EARLY_EXIT = "p3_early_exit"
    t.EXIT_ACT_EV_FORCE_CLOSE = "ev_force_close"

    # EV 雷达阈值 + 权重（Spec §4 默认值；测试手动挂确保 RED→GREEN 行为确定）
    t.EV_FORCE_CLOSE_BELOW = -0.35    # EV<-0.35 强制离场
    t.EV_WARN_LOWER_BOUND = -0.35     # -0.35 ≤ EV < -0.1 收紧止损
    t.EV_WARN_UPPER_BOUND = -0.10
    t.EV_STRONG_HOLD_ABOVE = +0.30    # EV>+0.3 放宽止损
    t.ev_weights = {                  # Spec 默认：7 子分权重，合计 1.0，正偏置 0.3
        "confidence_s": 0.22,
        "direction_consistency_s": 0.18,
        "trend_alignment_s": 0.15,
        "pnl_momentum_s": 0.14,
        "regime_friendly_s": 0.11,
        "holding_age_s": 0.10,
        "liquidity_risk_s": 0.10,
    }
    return t


# =====================================================================
# B-1: calc_position_ev 纯函数（放在 trading_utils.RiskManager 静态方法）
# =====================================================================
class TestCalcPositionEVWeights(unittest.TestCase):
    """Spec 5.2 测试 1: 7 子分权重 & 全中值输入 → EV=0.3"""

    def test_ev_subscores_weights_sum_matches_spec(self):
        """RED 失败原因: RiskManager.calc_position_ev 静态方法不存在"""
        # 全 0.5 归一化子分（Spec 基准）
        subscores = {
            "confidence_s": 0.5,
            "direction_consistency_s": 0.5,
            "trend_alignment_s": 0.5,
            "pnl_momentum_s": 0.5,
            "regime_friendly_s": 0.5,
            "holding_age_s": 0.5,
            "liquidity_risk_s": 0.5,
        }
        weights = {
            "confidence_s": 0.22,
            "direction_consistency_s": 0.18,
            "trend_alignment_s": 0.15,
            "pnl_momentum_s": 0.14,
            "regime_friendly_s": 0.11,
            "holding_age_s": 0.10,
            "liquidity_risk_s": 0.10,
        }
        expected_baseline = 0.3  # 文档正偏置
        # EV = sum(w_i * s_i) - 0.2 + 0.3 ？ 或者直接 sum(w_i*s_i)=0.5 → 输出 0.3？
        # Spec 5.2 写的明确："用全中值输入（每子分=0.5 归一化值）断言 EV=0.3"
        # 我们约定：base_score = ∑w_i * s_i；EV = base_score - 0.2 → 0.5-0.2=0.3 ✓
        ev, subs = RiskManager.calc_position_ev(subscores, weights)
        self.assertAlmostEqual(ev, 0.3, places=4)
        # 权重和必须 = 1.0
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=4)


# =====================================================================
# B-2: EV 四档决策（插入在 _execute_trade 的 P3 提前退出 → 卦象主离场之间）
# =====================================================================
class TestEVForceCloseTier(unittest.TestCase):
    """Spec 5.2 测试 2: EV < -0.35 且非保护期 → 强制离场 2/2 确认"""

    def test_ev_force_close_below_minus_0_35_not_in_protection(self):
        """RED 失败原因: _execute_trade 中 S2 分支未写，或 _handle_ev_four_tier 不存在"""
        t = _make_trader(enable_ev_radar=True)
        t.POSITION_PROTECTION_HOURS = 6.0

        # monkeypatch: 合成 EV 纯函数返回 -0.40（<-0.35）
        import scripts.memory_l4.trading_utils as tu

        ev_calls = []

        def _fake_ev(subscores, weights):
            ev_calls.append(1)
            return -0.40, {k: 0.5 for k in subscores}

        tu.RiskManager.calc_position_ev = staticmethod(_fake_ev)

        close_calls = []

        def _fake_close(inst_id, coin, pos_side, exit_price, exit_reason, **kw):
            close_calls.append({"inst_id": inst_id, "exit_reason": exit_reason})

        t._handle_close_position = _fake_close
        t._exit_confirm = MagicMock(return_value=(True, 2))
        t._clear_exit_confirm = MagicMock()
        t._adjust_sl_tp = MagicMock()

        # 构造一个 age=20h（超出保护期）的持仓评估场景
        # 调用工具函数 _handle_ev_four_tier（RED 阶段不存在 → AttributeError）
        ev_decision = t._handle_ev_four_tier(
            coin="BTC",
            inst_id="BTC-USDT-SWAP",
            pos_side="long",
            position_age_sec=20 * 3600,
            in_protection=False,
            upl=5.0,
            upl_ratio=0.01,
            inference={
                "confidence": 0.80,
                "direction": "UP",
                "price": 60000.0,
                "volatility": 0.03,
            },
            all_inferences={},
        )

        # 断言动作：强制离场 2/2 → handle_close_position 被调用且 exit_reason 前缀 = ev_force_close
        self.assertEqual(len(close_calls), 1,
                         "EV<-0.35 + 非保护期 → 必须执行 1 次平仓")
        self.assertTrue(
            str(close_calls[0]["exit_reason"]).startswith("ev_force_close"),
            f"离场原因前缀必须是 ev_force_close，实际: {close_calls[0]['exit_reason']}",
        )
        # 离场确认累计确认计数器 +1
        t._exit_confirm.assert_called_once()


class TestEVForceCloseInProtectionDisabled(unittest.TestCase):
    """Spec 5.2 测试 3: EV < -0.35 但在保护期内 → 不离场 + 打日志 skip"""

    def test_ev_force_close_disabled_in_protection(self):
        """RED 失败原因: in_protection 门禁分支未写"""
        t = _make_trader(enable_ev_radar=True)
        t.POSITION_PROTECTION_HOURS = 6.0

        import scripts.memory_l4.trading_utils as tu
        tu.RiskManager.calc_position_ev = staticmethod(lambda s, w: (-0.40, {k: 0.5 for k in s}))

        close_calls = []
        t._handle_close_position = lambda **kw: close_calls.append(True) or None
        t._exit_confirm = MagicMock()

        log_msgs = []
        t._log.side_effect = lambda msg, lvl="INFO": log_msgs.append((lvl, msg))

        # age=2h < 6h 保护期
        t._handle_ev_four_tier(
            coin="BTC",
            inst_id="BTC-USDT-SWAP",
            pos_side="long",
            position_age_sec=2 * 3600,
            in_protection=True,
            upl=5.0,
            upl_ratio=0.01,
            inference={"confidence": 0.80, "direction": "UP",
                       "price": 60000.0, "volatility": 0.03},
            all_inferences={},
        )

        self.assertEqual(len(close_calls), 0,
                         "EV 强制离场在保护期内必须绝对禁止调用 close_position")
        self.assertEqual(t._exit_confirm.call_count, 0,
                         "保护期内 even 不触发离场确认计数器")
        self.assertTrue(
            any("protected" in msg.lower() or "skip" in msg.lower() or "保护" in msg
                for _, msg in log_msgs),
            "保护期必须打 'protected skip EV_force' 或类似日志",
        )


class TestEVSwitchOffBypasses(unittest.TestCase):
    """Spec 5.2 测试 4: enable_ev_radar=False → calc_position_ev 从未被调用"""

    def test_ev_switch_off_passes_directly_to_yijing(self):
        """RED 失败原因: 开关关短路分支未写，calc_position_ev 仍被调用"""
        t = _make_trader(enable_ev_radar=False)  # S2=OFF

        import scripts.memory_l4.trading_utils as tu

        ev_call_count = {"n": 0}

        def _fake_ev(subscores, weights):
            ev_call_count["n"] += 1
            return 0.0, {k: 0.5 for k in subscores}

        tu.RiskManager.calc_position_ev = staticmethod(_fake_ev)
        t._exit_confirm = MagicMock()
        t._handle_close_position = MagicMock()

        # 在 S2 关的情况下跑 10 次 _handle_ev_four_tier（如果开关短路，应该直接 return 不调 ev）
        for i in range(10):
            _ = t._handle_ev_four_tier(
                coin="BTC",
                inst_id="BTC-USDT-SWAP",
                pos_side="long",
                position_age_sec=20 * 3600,
                in_protection=False,
                upl=5.0,
                upl_ratio=0.01,
                inference={"confidence": 0.80, "direction": "UP",
                           "price": 60000.0, "volatility": 0.03},
                all_inferences={},
            )

        self.assertEqual(
            ev_call_count["n"], 0,
            f"S2=OFF 时 calc_position_ev 必须从未被调用，实际调用 {ev_call_count['n']} 次",
        )


# =====================================================================
# B-2b: _adjust_sl_tp(tighten/relax) 真实 SL/TP 调整验证（T1新增）
# =====================================================================
class TestAdjustSLTPModulation(unittest.TestCase):
    """T1 实现验证：WARN/STRONG_HOLD 调 SL/TP 基于 ATR 基线 × modulation。

    设计：
      - 基线：LONG 65000，base SL ROI=3%(ATR×1.5)，base TP ROI=9%(ATR×4.5)，Lev=3
      - TIGHTEN (WARN):  SL × 0.7 = 2.1% ROI → SL_px = 65000 × (1 − 2.1%/3) = 64545
                         TP × 0.85 = 7.65% ROI → TP_px = 65000 × (1 + 7.65%/3) = 66657.5
      - RELAX (STRONG_HOLD):  SL × 1.3 = 3.9% ROI → SL_px = 65000 × (1 − 1.3%) = 64155
                              TP × 1.25 = 11.25% ROI → TP_px = 65000 × (1 + 3.75%) = 67437.5
    """

    @staticmethod
    def _mock_position(base_sl_roi=0.03, base_tp_roi=0.09, entry_price=65000.0):
        rec = MagicMock()
        rec.entry_price = entry_price
        rec.base_sl_roi = base_sl_roi
        rec.base_tp_roi = base_tp_roi
        rec.market_snapshot = {}
        return rec

    def test_tighten_long_sl_tp_price_matches_formula(self):
        """WARN tighten: SL 降 30%，TP 降 15%，方向顺序 long: SL < entry < TP"""
        t = _make_trader(coins=["BTC"])
        t.position_tracker.get_open_position.return_value = self._mock_position()
        # 构造完整 logger（_adjust_sl_tp 用 self.logger，若缺 AttributeError 挂）
        t.logger = MagicMock()

        ok = t._adjust_sl_tp(coin="BTC", inst_id="BTC-USDT-SWAP", pos_side="long", mode="tighten")
        self.assertTrue(ok, "tighten 应返回 True（dry-run OKX 也返回 True）")

        # 断言 place_stop_loss_take_profit 被调用一次
        t.okx_client.place_stop_loss_take_profit.assert_called_once()
        kwargs = t.okx_client.place_stop_loss_take_profit.call_args.kwargs
        self.assertEqual(kwargs["instId"], "BTC-USDT-SWAP")
        self.assertEqual(kwargs["posSide"], "long")
        sl_px = float(kwargs["sl_price"])
        tp_px = float(kwargs["tp_price"])
        # LONG：SL < entry(65000) < TP
        self.assertLess(sl_px, 65000, f"tighten SL {sl_px} 应 < entry 65000")
        self.assertGreater(tp_px, 65000, f"tighten TP {tp_px} 应 > entry 65000")
        # 价格精度验证：SL = 65000 × (1 − 0.021/3) = 64545；TP = 65000 × (1 + 0.0765/3) = 66657.5
        self.assertAlmostEqual(sl_px, 64545.0, delta=0.5,
                               msg=f"tighten SL 计算偏差：expect≈64545, actual={sl_px}")
        self.assertAlmostEqual(tp_px, 66657.5, delta=0.5,
                               msg=f"tighten TP 计算偏差：expect≈66657.5, actual={tp_px}")
        # 取消旧 algo 也应调用
        t.okx_client.cancel_all_algo_orders.assert_called_once()

    def test_relax_long_sl_tp_price_matches_formula(self):
        """STRONG_HOLD relax: SL 放 30%，TP 放 25%，顺序 long: SL < entry < TP"""
        t = _make_trader(coins=["BTC"])
        t.position_tracker.get_open_position.return_value = self._mock_position()
        t.logger = MagicMock()

        ok = t._adjust_sl_tp(coin="BTC", inst_id="BTC-USDT-SWAP", pos_side="long", mode="relax")
        self.assertTrue(ok)
        kwargs = t.okx_client.place_stop_loss_take_profit.call_args.kwargs
        sl_px = float(kwargs["sl_price"])
        tp_px = float(kwargs["tp_price"])
        # relax SL = 65000 × (1 − 0.039/3) = 65000 × 0.987 = 64155
        # relax TP = 65000 × (1 + 0.1125/3) = 65000 × 1.0375 = 67437.5
        self.assertAlmostEqual(sl_px, 64155.0, delta=0.5,
                               msg=f"relax SL 计算偏差：expect≈64155, actual={sl_px}")
        self.assertAlmostEqual(tp_px, 67437.5, delta=0.5,
                               msg=f"relax TP 计算偏差：expect≈67437.5, actual={tp_px}")
        self.assertLess(sl_px, 65000)
        self.assertGreater(tp_px, 65000)

    def test_relax_short_direction_guard_pass(self):
        """SHORT relax 方向：TP < entry(65000) < SL"""
        t = _make_trader(coins=["BTC"])
        t.position_tracker.get_open_position.return_value = self._mock_position()
        t.logger = MagicMock()

        ok = t._adjust_sl_tp(coin="BTC", inst_id="BTC-USDT-SWAP", pos_side="short", mode="relax")
        self.assertTrue(ok)
        kwargs = t.okx_client.place_stop_loss_take_profit.call_args.kwargs
        sl_px = float(kwargs["sl_price"])
        tp_px = float(kwargs["tp_price"])
        # SHORT：SL 是"高于 entry 触发"的那一侧，TP 是"低于 entry 触发"
        self.assertLess(tp_px, 65000, f"short relax TP {tp_px} 应 < entry")
        self.assertGreater(sl_px, 65000, f"short relax SL {sl_px} 应 > entry")

    def test_dedup_cache_prevents_duplicate_api_call(self):
        """同一 (inst_id, mode) 2 轮内不应再调 place_stop_loss_take_profit"""
        t = _make_trader(coins=["BTC"])
        t.position_tracker.get_open_position.return_value = self._mock_position()
        t.logger = MagicMock()
        # 第 1 次 → 应调用
        ok1 = t._adjust_sl_tp("BTC", "BTC-USDT-SWAP", "long", "tighten")
        self.assertTrue(ok1)
        first_call_count = t.okx_client.place_stop_loss_take_profit.call_count
        self.assertEqual(first_call_count, 1)
        # 第 2 次（同轮）→ 命中缓存，返回 False 不再调 API
        ok2 = t._adjust_sl_tp("BTC", "BTC-USDT-SWAP", "long", "tighten")
        self.assertFalse(ok2, "同 mode 同轮第 2 次应缓存命中返回 False")
        self.assertEqual(t.okx_client.place_stop_loss_take_profit.call_count, 1,
                         "缓存命中期间不应多次调 API")
        # 过 2 轮 TTL → 过期再次可调
        t._cycle_idx += 3   # TTL=2，cycle_idx 增 3 > 2
        ok3 = t._adjust_sl_tp("BTC", "BTC-USDT-SWAP", "long", "tighten")
        self.assertTrue(ok3)
        self.assertEqual(t.okx_client.place_stop_loss_take_profit.call_count, 2)

    def test_base_roi_missing_skip_silently(self):
        """旧持仓 base_sl_roi/base_tp_roi 为 0 → 不动作，返回 False，不调 API"""
        t = _make_trader(coins=["BTC"])
        t.position_tracker.get_open_position.return_value = self._mock_position(
            base_sl_roi=0.0, base_tp_roi=0.0)
        t.logger = MagicMock()
        ok = t._adjust_sl_tp("BTC", "BTC-USDT-SWAP", "long", "tighten")
        self.assertFalse(ok, "base ROI 缺失时应跳过返回 False")
        t.okx_client.place_stop_loss_take_profit.assert_not_called()

    def test_atr_floor_protect_over_tighten(self):
        """极端收紧场景：base_sl_roi 本来就很小，×0.7 后低于 1.5% ROI → floor 到 1.5%
        例：base_sl_roi=0.01 (1%), tighten → 0.7% < 1.5% floor → 采用 1.5%"""
        t = _make_trader(coins=["BTC"])
        t.position_tracker.get_open_position.return_value = self._mock_position(
            base_sl_roi=0.01, base_tp_roi=0.05, entry_price=100.0)
        t.logger = MagicMock()
        t._adjust_sl_tp("BTC", "BTC-USDT-SWAP", "long", "tighten")
        kwargs = t.okx_client.place_stop_loss_take_profit.call_args.kwargs
        sl_px = float(kwargs["sl_price"])
        # 未 floor 时：0.007 ROI → SL_px = 100 × (1 − 0.007/3) = 99.7667
        # floor 后: 0.015 ROI → SL_px = 100 × (1 − 0.015/3) = 99.5
        self.assertAlmostEqual(sl_px, 99.5, delta=0.01,
                               msg=f"floor 到 1.5%ROI 失败: SL={sl_px}，expect 99.5")

    # ── 边界 B3: 连锁漂移修复（base_roi 冻结）验证 ─────────────
    def test_old_position_base_roi_frozen_after_first_adjust(self):
        """B3 复现：旧持仓(base_roi=0) 先用 fallback 反算；
        第 1 次 tighten 写了新 SL 后，下一轮反算会"把新 SL 当基线"连锁收紧。
        修复后：第 1 次 adjust 冻结 base_roi → 后续 relax 用冻结值而非漂移值。
        """
        t = _make_trader(coins=["BTC"])
        t.logger = MagicMock()

        # 旧持仓：base_sl_roi/base_tp_roi = 0（老版本代码开的仓，没存基线）
        # 但 market_snapshot 中有 SL/TP → fallback 反算能得到基线
        rec = MagicMock()
        rec.entry_price = 65000.0
        rec.base_sl_roi = 0.0
        rec.base_tp_roi = 0.0
        # 初始 SL_px = 64350, TP_px = 66950
        #   SL ROI 反算： |64350-65000|/65000 = 1% × 杠杆3 = 3% ✅
        #   TP ROI 反算： |66950-65000|/65000 = 3% × 杠杆3 = 9% ✅
        rec.market_snapshot = {"stop_loss_px": 64350.0, "take_profit_px": 66950.0}
        t.position_tracker.get_open_position.return_value = rec

        # Step 1: 第一次调 tighten → 基线应为反算得到的 3%/9% → SL=64545 TP=66657.5
        t._cycle_idx = 1
        ok1 = t._adjust_sl_tp("BTC", "BTC-USDT-SWAP", "long", "tighten")
        self.assertTrue(ok1)
        # 验证冻结生效：rec.base_sl_roi / base_tp_roi 被回填
        self.assertAlmostEqual(rec.base_sl_roi, 0.03, delta=1e-6,
                               msg="首次调完 base_sl_roi 应被冻结回 0.03")
        self.assertAlmostEqual(rec.base_tp_roi, 0.09, delta=1e-6,
                               msg="首次调完 base_tp_roi 应被冻结回 0.09")

        # Step 2: 模拟下一轮：OKX 平台上 SL/TP 已经是 tighten 后的值（64545 / 66657.5）
        # 如果没有冻结，下一轮 _get_base_sl_roi 会 fallback 反算，得到 SL ROi =
        # |64545-65000|/65000 *3 = 455/65000*3 = 0.7%*3 = 2.1%（漂移！）
        rec.market_snapshot = {"stop_loss_px": 64545.0, "take_profit_px": 66657.5}

        # 过掉缓存 TTL（2 轮），调用 relax 看结果：
        # 正确（冻结基线 3%）→ relax SL = 0.03*1.3=0.039 → SL_px = 64155
        # 错误（漂移基线 2.1%）→ relax SL = 0.021*1.3=0.0273 → SL_px = 64408.5
        t._cycle_idx = 5  # 和第 1 次差 4 轮 → TTL=2 已过期
        ok2 = t._adjust_sl_tp("BTC", "BTC-USDT-SWAP", "long", "relax")
        self.assertTrue(ok2)
        kwargs = t.okx_client.place_stop_loss_take_profit.call_args.kwargs
        sl_px = float(kwargs["sl_price"])
        self.assertAlmostEqual(sl_px, 64155.0, delta=1.0,
                               msg=f"B3 未冻结时 relax 会漂移到 64408.5；现 SL={sl_px}（应≈64155）")

    def test_old_position_base_roi_via_stable_cache(self):
        """B3 stable fallback：如果 PositionRecord 是不可写对象（dict/immutable），
        则退化为 self._mode_cache 中 ("stable_base_sl_roi", inst_id) 键。"""
        t = _make_trader(coins=["BTC"])
        t.logger = MagicMock()

        # 构造一个不可写 rec：定义 __setattr__ 抛 TypeError（模拟 dataclass frozen=True）
        class _ImmutableRecord:
            __slots__ = ()  # 禁止实例 dict

        # 我们用普通 object 实例但 base_sl_roi 放到 class descriptor 上不可写
        # 更简单：直接 setattr 后再删掉 base_sl_roi，或用 property 拦截
        class _Immutable:
            @property
            def base_sl_roi(self): return 0.0
            @property
            def base_tp_roi(self): return 0.0
            @property
            def entry_price(self): return 65000.0
            @property
            def market_snapshot(self):
                return {"stop_loss_px": 64350.0, "take_profit_px": 66950.0}
        rec = _Immutable()
        t.position_tracker.get_open_position.return_value = rec

        t._cycle_idx = 1
        ok = t._adjust_sl_tp("BTC", "BTC-USDT-SWAP", "long", "tighten")
        self.assertTrue(ok)

        # 稳定缓存应已写入：key=("stable_base_sl_roi", "BTC-USDT-SWAP")
        hit, cached_sl = t._cache_get(("stable_base_sl_roi", "BTC-USDT-SWAP"), ttl_cycles=99999)
        self.assertTrue(hit, "不可写 PositionRecord 时 stable 缓存应被写入")
        self.assertAlmostEqual(cached_sl, 0.03, delta=1e-6,
                               msg=f"stable_base_sl_roi 应为 0.03，实际={cached_sl}")
        # 再次调用 _get_base_sl_roi 应从缓存读而非 fallback 反算
        got = t._get_base_sl_roi("BTC-USDT-SWAP", 65000.0)
        self.assertAlmostEqual(got, 0.03, delta=1e-6,
                               msg=f"第二次读 base_sl_roi 应走缓存得 0.03，实际={got}")


# =====================================================================
# B4: cycle_idx 回退自动清缓存（日期 rollover / 手工 reset 防御）
# =====================================================================
class TestCycleIdxRolloverCacheDefense(unittest.TestCase):
    """Spec 5.5 边界测试: _cycle_idx 回退时 _mode_cache 自动清空防 TTL 错乱。"""

    def test_cycle_monotonic_advance_no_clear(self):
        """正常推进：cycle_idx 单调递增时，mode_cache 不应被清。"""
        t = _make_trader(coins=["BTC"])
        t._cycle_idx = 5
        t._mode_cache[("some_anomaly_coin", "BTC")] = ("payload_A", 4)
        t._mode_cache[("stable_base_sl_roi", "BTC-USDT-SWAP")] = (0.03, 1)

        new_idx = t._advance_cycle_idx()
        self.assertEqual(new_idx, 6)
        self.assertEqual(len(t._mode_cache), 2,
                         "单调推进不应清空 mode_cache")

    def test_cycle_rollback_triggers_clear(self):
        """B4 复现：_cycle_idx 回退时 mode_cache 被清（否则 written_cycle > new_cycle
        导致 TTL = written + 2 > new → 缓存永不过期，S1 永不重算）。"""
        t = _make_trader(coins=["BTC"])
        t._cycle_idx = 30
        t._last_cycle_seen = 30  # 模拟：之前推进过 30 轮，_last_cycle_seen 记录 30
        t._mode_cache[("A",)] = ("pA", 28)
        t._mode_cache[("B",)] = ("pB", 29)
        t._mode_cache[("C",)] = ("pC", 30)

        # 模拟日期 rollover：下一次 run_once 前有人把 _cycle_idx 重置到 0（比如
        # 手工保存/恢复状态，或日期切换逻辑错误）
        t._cycle_idx = 0
        new_idx = t._advance_cycle_idx()
        self.assertEqual(new_idx, 1, "回退后应从 0+1=1 开始")
        self.assertEqual(len(t._mode_cache), 0,
                         f"cycle_idx 回退时应清 mode_cache，残留={list(t._mode_cache.keys())}")
        self.assertEqual(t._last_cycle_seen, 1,
                         "推进后 _last_cycle_seen 应同步更新为新 cycle")

    def test_first_call_never_clears(self):
        """进程启动第一次推进（_cycle_idx 未初始化）不应清空缓存。"""
        t = _make_trader(coins=["BTC"])
        # 模拟 __init__ 前未设 _cycle_idx
        if hasattr(t, "_cycle_idx"):
            delattr(t, "_cycle_idx")
        t._mode_cache[("preload",)] = ("x", 0)
        new_idx = t._advance_cycle_idx()
        self.assertEqual(new_idx, 1)
        # 注意：首进（_prev_idx=-1）命中 _prev_idx < 0 → 不走 clear 分支
        self.assertIn(("preload",), t._mode_cache,
                      "首次 advance 不应该清 preloaded 缓存")


# =====================================================================
# B-5（回放）: 数据驱动分层胜率验证（可选，无真实 P0 数据时 @skip）
# =====================================================================
class TestEVBacktestStratifiedWinRates(unittest.TestCase):
    """Spec 5.2 测试 5: 历史回放分层胜率校验（无数据时 skip）"""

    @unittest.skipIf(
        not Path("/tmp/p0_trade_samples.json").exists(),
        "无 /tmp/p0_trade_samples.json，跳过分层回放测试（本地/CI 不强制数据依赖）",
    )
    def test_ev_stratified_backtest_win_rates(self):
        """RED 失败原因: 回测钩子未写（Phase B 末再补覆盖，先 skip）"""
        self.fail("回测钩子未写（若此测试被执行说明 @skip 条件失效）")


# =====================================================================
# C13/C14（Phase C 真化）: EV 子分 趋势对齐度 + 流动性风险
# =====================================================================
class TestEVSubscoresPhaseCRealized(unittest.TestCase):
    """Phase C: 趋势对齐度 + 流动性风险 从占位 → 真实计算。"""

    # ── C13: trend_alignment_s 覆盖 ────────────────────────────────────
    def test_trend_alignment_full_align_high(self):
        """bagua=long, BTC非bear, 持仓=long, bagua_conf=0.9 → 高分。"""
        t = _make_trader(coins=["BTC"], enable_ev_radar=True)
        # mock _check_btc_trend：非 bearish（大势偏多）
        t._check_btc_trend = lambda: (False, "BTC多头趋势")
        subs = t._build_ev_subscores(
            pos_side="long", position_age_sec=3600, upl_ratio=0.0,
            inference={
                "confidence": 0.6, "direction": "UP", "volatility": 0.03,
                "bagua_direction": "long", "bagua_confidence": 0.9,
            },
        )
        # 0.4*1 + 0.4*1 + 0.2*0.9 = 0.98
        self.assertAlmostEqual(subs["trend_alignment_s"], 0.98, places=3)
        # 高分：显著高于占位 0.5
        self.assertGreater(subs["trend_alignment_s"], 0.85)

    def test_trend_alignment_full_conflict_low(self):
        """bagua=short(反), BTC bearish(反), 持仓=long → 低分。"""
        t = _make_trader(coins=["BTC"], enable_ev_radar=True)
        t._check_btc_trend = lambda: (True, "BTC做空允许")
        subs = t._build_ev_subscores(
            pos_side="long", position_age_sec=3600, upl_ratio=0.0,
            inference={
                "confidence": 0.6, "direction": "UP", "volatility": 0.03,
                "bagua_direction": "short", "bagua_confidence": 0.8,
            },
        )
        # 0.4*0 + 0.4*0 + 0.2*0.8 = 0.16
        self.assertAlmostEqual(subs["trend_alignment_s"], 0.16, places=3)
        self.assertLess(subs["trend_alignment_s"], 0.25)

    def test_trend_alignment_neutral_mid(self):
        """bagua=neutral, BTC 无数据(抛异常降级) → 中值≈0.5。"""
        t = _make_trader(coins=["BTC"], enable_ev_radar=True)
        def _boom():
            raise RuntimeError("网络断开")
        t._check_btc_trend = _boom
        subs = t._build_ev_subscores(
            pos_side="long", position_age_sec=3600, upl_ratio=0.0,
            inference={
                "confidence": 0.5, "direction": "UP", "volatility": 0.03,
                "bagua_direction": "neutral",
            },
        )
        # 0.4*0.5 + 0.4*0.5 + 0.2*0.5 = 0.5
        self.assertAlmostEqual(subs["trend_alignment_s"], 0.5, places=2)

    def test_short_position_bear_btc_align(self):
        """做空持仓 + bagua=short + BTC bearish → 全对齐高分。"""
        t = _make_trader(coins=["BTC"], enable_ev_radar=True)
        t._check_btc_trend = lambda: (True, "BTC做空允许")
        subs = t._build_ev_subscores(
            pos_side="short", position_age_sec=7200, upl_ratio=0.01,
            inference={
                "confidence": 0.8, "direction": "DOWN", "volatility": 0.03,
                "bagua_direction": "short", "bagua_confidence": 0.85,
            },
        )
        # 0.4*1 + 0.4*1 + 0.2*0.85 = 0.97
        self.assertAlmostEqual(subs["trend_alignment_s"], 0.97, places=3)

    # ── C14: liquidity_risk_s 覆盖 ─────────────────────────────────────
    def test_liquidity_stable_high_volume_boom(self):
        """稳定成交量(mean/std大) + 2倍放量 + 低波动率 → 高分。"""
        t = _make_trader(coins=["BTC"], enable_ev_radar=True)
        # 构造 60 根稳定 volume + 末尾 2 倍放量：mean≈100, std≈0
        klines = [{"v": 100.0} for _ in range(59)]
        klines.append({"v": 200.0})  # last=2x mean
        subs = t._build_ev_subscores(
            pos_side="long", position_age_sec=3600, upl_ratio=0.0,
            inference={
                "confidence": 0.5, "direction": "UP", "volatility": 0.01,  # 低 vol
                "kline_data": klines,
            },
        )
        # vol_stability ≈ 1.0; spike≈2/1.02≈2 → normalized 接近上界
        self.assertGreater(subs["liquidity_risk_s"], 0.75,
                           f"稳定+放量+低波应得高分, got={subs['liquidity_risk_s']}")

    def test_liquidity_unstable_shrink_high_vol_low_score(self):
        """量能剧烈波动(1→100锯齿) + 缩量 + 高vol(0.08) → 低分。"""
        t = _make_trader(coins=["BTC"], enable_ev_radar=True)
        klines = []
        for i in range(60):
            klines.append({"v": 1.0 if i % 2 == 0 else 100.0})  # 大跳 → std巨大
        klines[-1] = {"v": 1.0}  # 最后一根缩量
        subs = t._build_ev_subscores(
            pos_side="long", position_age_sec=3600, upl_ratio=0.0,
            inference={
                "confidence": 0.5, "direction": "UP", "volatility": 0.08,  # 高 vol
                "kline_data": klines,
            },
        )
        self.assertLess(subs["liquidity_risk_s"], 0.55,
                        f"不稳定+缩量+高波应得低分, got={subs['liquidity_risk_s']}")

    def test_liquidity_insufficient_kline_data_fallback_05(self):
        """kline<5根或全0 volume → 降级中性 0.5。"""
        t = _make_trader(coins=["BTC"], enable_ev_radar=True)
        # A: 仅 3 根 → <5 fallback
        subs_a = t._build_ev_subscores(
            pos_side="long", position_age_sec=3600, upl_ratio=0.0,
            inference={"kline_data": [{"v": 1} for _ in range(3)]},
        )
        self.assertEqual(subs_a["liquidity_risk_s"], 0.5)
        # B: 60 根但 volume 全=0 → sum=0 fallback
        subs_b = t._build_ev_subscores(
            pos_side="long", position_age_sec=3600, upl_ratio=0.0,
            inference={"kline_data": [{"v": 0} for _ in range(60)]},
        )
        self.assertEqual(subs_b["liquidity_risk_s"], 0.5)
        # C: kline_data 缺失 → 0.5
        subs_c = t._build_ev_subscores(
            pos_side="long", position_age_sec=3600, upl_ratio=0.0,
            inference={},
        )
        self.assertEqual(subs_c["liquidity_risk_s"], 0.5)

    def test_liquidity_exception_graceful_fallback(self):
        """volume 中混入非法值 → 异常捕获降级 0.5。"""
        t = _make_trader(coins=["BTC"], enable_ev_radar=True)
        bad_klines = [{"v": "not_a_number"} for _ in range(20)]
        subs = t._build_ev_subscores(
            pos_side="long", position_age_sec=3600, upl_ratio=0.0,
            inference={"kline_data": bad_klines},
        )
        self.assertEqual(subs["liquidity_risk_s"], 0.5)

    # ── 其它子分未被影响（回归）────────────────────────────────────────
    def test_other_5_subscores_unchanged_from_legacy(self):
        """除 trend_alignment 和 liquidity 外，其余 5 子分行为与占位版本一致。"""
        t = _make_trader(coins=["BTC"], enable_ev_radar=True)
        t._check_btc_trend = lambda: (False, "ok")
        subs = t._build_ev_subscores(
            pos_side="long", position_age_sec=3600, upl_ratio=0.0,
            inference={
                "confidence": 0.5, "direction": "UP", "volatility": 0.03,
            },
        )
        self.assertEqual(subs["confidence_s"], 0.5)
        self.assertEqual(subs["direction_consistency_s"], 1.0)  # long+UP
        self.assertEqual(subs["pnl_momentum_s"], 0.5)          # upl=0%
        self.assertEqual(subs["regime_friendly_s"], 0.6)       # vol=0.03 normal
        self.assertAlmostEqual(subs["holding_age_s"], 1.0 - 1/60, places=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
