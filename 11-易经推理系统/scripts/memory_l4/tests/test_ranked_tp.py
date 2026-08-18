#!/usr/bin/env python3
"""
test_ranked_tp.py — Phase C TDD 测试集（S4 = enable_ranked_tp）
对应 Spec §5.3: 排名止盈三档（落差阈值触发 Top1 止盈）

RED 失败原因:
  - RiskManager.calc_ranked_tp_gap 静态方法不存在
  - PollingTrader._handle_ranked_tp_top1 方法不存在 / 开关短路分支未写
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scripts.memory_l4.polling_trader import PollingTrader  # noqa: E402
from scripts.memory_l4.trading_utils import RiskManager  # noqa: E402


def _make_trader(coins=None, max_positions=3, enable_ranked_tp=True):
    """轻量 mock 构造（复用 Phase A/B/C 风格）"""
    with patch.object(PollingTrader, "__init__", lambda self, *a, **kw: None):
        t = PollingTrader.__new__(PollingTrader)
    t.coins = list(coins or ["BTC", "SOL", "XAU"])
    t.max_positions = max_positions
    t.enable_mode_switch = True
    t.enable_ev_radar = True
    t.enable_multi_horizon = True
    t.enable_ranked_tp = enable_ranked_tp
    t.position_tracker = MagicMock(spec=[
        "all_open_positions", "all_closed_positions",
        "get_open_position", "has_open_position", "is_in_cooldown",
    ])
    t.position_tracker.all_open_positions.return_value = []
    t.okx_client = MagicMock()
    t.okx_client.cfg = {"default_leverage": 3}
    t.blacklist_coins = set()
    t.dynamic_blacklist = {}
    t._check_dynamic_blacklist = MagicMock(return_value=(False, ""))
    t._count_total_positions = MagicMock(return_value=0)
    t._cycle_idx = 0
    t._mode_cache = {}
    t._log = MagicMock()
    t.POSITION_PROTECTION_HOURS = 6.0
    t.EXIT_CONFIRM_REQUIRED = 2
    t.EXIT_ACT_EV_FORCE_CLOSE = "ev_force_close"
    # Phase C: 排名止盈默认参数（Spec §4.3）
    t.RANKED_TP_GAP_RATIO: float = 0.70      # 落差 0.7 → Top1 远领先
    t.RANKED_TP_MIN_PROFIT_USDT: float = 5.0  # Top1 至少盈利 5U 才触发（防噪声）
    t.EXIT_ACT_RANKED_TP = "ranked_tp"        # 排名止盈离场 tag
    return t


# =====================================================================
# C-5: calc_ranked_tp_gap 纯函数结构（落差 = (top1-top2)/top1）
# =====================================================================
class TestCalcRankedTpGapShape(unittest.TestCase):
    """Spec 5.3 测试 5: 排名落差计算函数结构"""

    def test_gap_calc_matches_spec(self):
        """RED 失败原因: RiskManager.calc_ranked_tp_gap 静态方法不存在"""
        # 按 upl（USDT）排序的 3 持仓：Top1=+20U，Top2=+6U，Top3=+1U
        # Spec 定义 gap_ratio = (Top1 − Top2) / Top1（Top1>0 时）
        # 本例: (20−6)/20 = 0.70 → 刚好 ≥ 阈值 0.70 → trigger=True
        ranked = [
            {"coin": "A", "upl": 20.0, "upl_ratio": 0.10},
            {"coin": "B", "upl": 6.0,  "upl_ratio": 0.03},
            {"coin": "C", "upl": 1.0,  "upl_ratio": 0.005},
        ]
        result = RiskManager.calc_ranked_tp_gap(ranked, min_profit_usdt=5.0)

        self.assertIsInstance(result, dict)
        self.assertIn("top1_idx", result)
        self.assertIn("gap_ratio", result)
        self.assertIn("trigger", result)
        self.assertEqual(result["top1_idx"], 0)
        self.assertAlmostEqual(result["gap_ratio"], 0.70, places=4)
        self.assertTrue(result["trigger"], "gap_ratio=0.70 ≥ 阈值 0.70 → 必须 trigger=True")


# =====================================================================
# C-6: 落差 > 0.7 + Top1 盈利≥5U → 执行排名止盈（2/2 确认后）
# =====================================================================
class TestRankedTpTrigger(unittest.TestCase):
    """Spec 5.3 测试 6: 落差 0.75 > 0.7 → Top1 止盈触发"""

    def test_top1_far_ahead_triggers_tp(self):
        """RED 失败原因: PollingTrader._handle_ranked_tp_top1 方法不存在"""
        t = _make_trader(enable_ranked_tp=True)
        t._exit_confirm = MagicMock(return_value=(True, 2))  # 2/2 确认
        t._clear_exit_confirm = MagicMock()

        import scripts.memory_l4.trading_utils as tu
        tu.RiskManager.calc_ranked_tp_gap = staticmethod(
            lambda ranked, min_profit_usdt=5.0: {
                "top1_idx": 0, "gap_ratio": 0.75, "trigger": True,
            }
        )
        close_calls = []

        def _fake_close(inst_id, coin, pos_side, exit_price, exit_reason, **kw):
            close_calls.append({"coin": coin, "exit_reason": exit_reason})

        t._handle_close_position = _fake_close

        # 构造 3 持仓 upl 列表（落差 0.75，Top1=BTC 盈利 +22U）
        positions_with_pnl = [
            {"coin": "BTC", "inst_id": "BTC-USDT-SWAP", "pos_side": "long",
             "upl": 22.0, "upl_ratio": 0.11, "entry_price": 60000.0,
             "mark_price": 60660.0, "position_age_sec": 20 * 3600,
             "in_protection": False,
             "inference": {"price": 60660.0, "confidence": 0.80,
                           "direction": "UP", "volatility": 0.03}},
            {"coin": "SOL", "inst_id": "SOL-USDT-SWAP", "pos_side": "long",
             "upl": 5.5, "upl_ratio": 0.028, "entry_price": 140.0,
             "mark_price": 143.92, "position_age_sec": 10 * 3600,
             "in_protection": False,
             "inference": {"price": 143.92, "confidence": 0.74,
                           "direction": "UP", "volatility": 0.04}},
            {"coin": "XAU", "inst_id": "XAU-USDT-SWAP", "pos_side": "long",
             "upl": 1.0, "upl_ratio": 0.004, "entry_price": 2300.0,
             "mark_price": 2309.2, "position_age_sec": 8 * 3600,
             "in_protection": False,
             "inference": {"price": 2309.2, "confidence": 0.68,
                           "direction": "UP", "volatility": 0.018}},
        ]

        decision = t._handle_ranked_tp_top1(positions_with_pnl, gap_threshold=0.70)

        self.assertIsInstance(decision, dict)
        self.assertEqual(decision.get("triggered"), True,
                         "落差 0.75 > 0.70 且 2/2 确认 → triggered=True")
        self.assertEqual(len(close_calls), 1, "必须执行 1 次排名止盈平仓")
        self.assertTrue(
            str(close_calls[0]["exit_reason"]).startswith("ranked_tp"),
            f"离场原因前缀必须是 ranked_tp，实际={close_calls[0]['exit_reason']}",
        )
        self.assertEqual(close_calls[0]["coin"], "BTC", "Top1=BTC 必须被止盈")
        t._exit_confirm.assert_called_once()


# =====================================================================
# C-7: 落差 < 0.7 → 不触发排名止盈（按常规离场）
# =====================================================================
class TestRankedTpNoTriggerWhenGapSmall(unittest.TestCase):
    """Spec 5.3 测试 7: 落差 0.3 < 0.7 → 不触发"""

    def test_narrow_gap_does_not_trigger(self):
        """RED 失败原因: 不触发分支未写（trigger=False时仍调 close）"""
        t = _make_trader(enable_ranked_tp=True)
        t._exit_confirm = MagicMock()

        import scripts.memory_l4.trading_utils as tu
        tu.RiskManager.calc_ranked_tp_gap = staticmethod(
            lambda ranked, min_profit_usdt=5.0: {
                "top1_idx": 0, "gap_ratio": 0.30, "trigger": False,
            }
        )
        close_calls = []
        t._handle_close_position = lambda **kw: close_calls.append(True) or None

        positions_with_pnl = [
            {"coin": "A", "inst_id": "A-SWAP", "pos_side": "long",
             "upl": 10.0, "upl_ratio": 0.05, "entry_price": 100.0,
             "mark_price": 105.0, "position_age_sec": 15 * 3600,
             "in_protection": False,
             "inference": {"price": 105.0, "confidence": 0.75,
                           "direction": "UP", "volatility": 0.03}},
            {"coin": "B", "inst_id": "B-SWAP", "pos_side": "long",
             "upl": 7.0, "upl_ratio": 0.035, "entry_price": 80.0,
             "mark_price": 82.8, "position_age_sec": 15 * 3600,
             "in_protection": False,
             "inference": {"price": 82.8, "confidence": 0.72,
                           "direction": "UP", "volatility": 0.03}},
            {"coin": "C", "inst_id": "C-SWAP", "pos_side": "long",
             "upl": 5.0, "upl_ratio": 0.025, "entry_price": 60.0,
             "mark_price": 61.5, "position_age_sec": 15 * 3600,
             "in_protection": False,
             "inference": {"price": 61.5, "confidence": 0.70,
                           "direction": "UP", "volatility": 0.03}},
        ]

        decision = t._handle_ranked_tp_top1(positions_with_pnl, gap_threshold=0.70)

        self.assertEqual(decision.get("triggered"), False,
                         "落差 0.30 < 0.70 → 必须 trigger=False")
        self.assertEqual(len(close_calls), 0, "落差不够 → 绝对不能平仓")
        self.assertEqual(t._exit_confirm.call_count, 0,
                         "未触发时 even 不调用离场确认计数器")


# =====================================================================
# C-8: 保护期内禁止排名止盈（即使满足落差）
# =====================================================================
class TestRankedTpDisabledInProtection(unittest.TestCase):
    """Spec 5.3 测试 8: Top1 在保护期内 → skip + 日志"""

    def test_top1_in_protection_skipped_even_gap_large(self):
        """RED 失败原因: in_protection 门禁未写"""
        t = _make_trader(enable_ranked_tp=True)
        t._exit_confirm = MagicMock()

        import scripts.memory_l4.trading_utils as tu
        # 即使 gap=0.8 很大
        tu.RiskManager.calc_ranked_tp_gap = staticmethod(
            lambda ranked, min_profit_usdt=5.0: {
                "top1_idx": 0, "gap_ratio": 0.80, "trigger": True,
            }
        )
        close_calls = []
        t._handle_close_position = lambda **kw: close_calls.append(True) or None

        log_msgs = []
        t._log.side_effect = lambda msg, lvl="INFO": log_msgs.append((lvl, msg))

        # 但 Top1 的 age=2h < 6h 保护期（in_protection=True）
        positions_with_pnl = [
            {"coin": "BTC", "inst_id": "BTC-USDT-SWAP", "pos_side": "long",
             "upl": 30.0, "upl_ratio": 0.15, "entry_price": 60000.0,
             "mark_price": 60900.0, "position_age_sec": 2 * 3600,
             "in_protection": True,   # ← 关键：保护期
             "inference": {"price": 60900.0, "confidence": 0.85,
                           "direction": "UP", "volatility": 0.03}},
            {"coin": "SOL", "inst_id": "SOL-USDT-SWAP", "pos_side": "long",
             "upl": 6.0, "upl_ratio": 0.03, "entry_price": 140.0,
             "mark_price": 144.2, "position_age_sec": 10 * 3600,
             "in_protection": False,
             "inference": {"price": 144.2, "confidence": 0.74,
                           "direction": "UP", "volatility": 0.04}},
            {"coin": "XAU", "inst_id": "XAU-USDT-SWAP", "pos_side": "long",
             "upl": 1.0, "upl_ratio": 0.004, "entry_price": 2300.0,
             "mark_price": 2309.2, "position_age_sec": 10 * 3600,
             "in_protection": False,
             "inference": {"price": 2309.2, "confidence": 0.68,
                           "direction": "UP", "volatility": 0.018}},
        ]

        decision = t._handle_ranked_tp_top1(positions_with_pnl, gap_threshold=0.70)

        self.assertEqual(decision.get("triggered"), False,
                         "Top1 在保护期内 → 必须 trigger=False")
        self.assertEqual(len(close_calls), 0,
                         "保护期内排名止盈绝对禁止调用 close_position")
        self.assertEqual(t._exit_confirm.call_count, 0,
                         "保护期内 not 调用离场确认计数器")
        self.assertTrue(
            any("protected" in msg.lower() or "skip" in msg.lower() or "保护" in msg
                for _, msg in log_msgs),
            "保护期必须打 'protected skip ranked_tp' 或类似日志",
        )


# =====================================================================
# C-9: S4 开关关闭 → 排名分支短路（calc_ranked_tp_gap 从未被调用）
# =====================================================================
class TestRankedTpSwitchOffBypasses(unittest.TestCase):
    """Spec 5.3 测试 9: enable_ranked_tp=False → 直接 BYPASS（附加断言）"""

    def test_switch_off_gap_never_called(self):
        """RED 失败原因: S4=OFF 短路分支未写"""
        t = _make_trader(enable_ranked_tp=False)  # S4=OFF

        import scripts.memory_l4.trading_utils as tu
        call_count = {"n": 0}

        def _fake_gap(ranked, min_profit_usdt=5.0):
            call_count["n"] += 1
            return {"top1_idx": 0, "gap_ratio": 0.9, "trigger": False}

        tu.RiskManager.calc_ranked_tp_gap = staticmethod(_fake_gap)
        t._exit_confirm = MagicMock()
        t._handle_close_position = MagicMock()

        positions_with_pnl = [
            {"coin": "A", "inst_id": "A-SWAP", "pos_side": "long",
             "upl": 20.0, "upl_ratio": 0.10, "entry_price": 100.0,
             "mark_price": 110.0, "position_age_sec": 20 * 3600,
             "in_protection": False,
             "inference": {"price": 110.0, "confidence": 0.8,
                           "direction": "UP", "volatility": 0.03}},
            {"coin": "B", "inst_id": "B-SWAP", "pos_side": "long",
             "upl": 4.0, "upl_ratio": 0.02, "entry_price": 80.0,
             "mark_price": 81.6, "position_age_sec": 20 * 3600,
             "in_protection": False,
             "inference": {"price": 81.6, "confidence": 0.7,
                           "direction": "UP", "volatility": 0.03}},
        ]

        for _ in range(10):
            _ = t._handle_ranked_tp_top1(positions_with_pnl, gap_threshold=0.70)

        self.assertEqual(
            call_count["n"], 0,
            f"S4=OFF 时 calc_ranked_tp_gap 必须从未被调用，实际 {call_count['n']} 次",
        )


# =====================================================================
# C-4b (T2新增): S4 阈值 config.json 热配置 reload 验证
# =====================================================================
class TestRankedTpHotConfigReload(unittest.TestCase):
    """T2 实现验证：_load_evolution_config 中 ranked_tp_gap_ratio / ranked_tp_min_profit_usdt
    会覆盖 self.RANKED_TP_GAP_RATIO / self.RANKED_TP_MIN_PROFIT_USDT 默认值。"""

    @staticmethod
    def _make_minimal_trader_with_config_paths(tmp_path: Path):
        """只挂 _load_evolution_config 需要的最小字段，避免真实 __init__。"""
        with patch.object(PollingTrader, "__init__", lambda self, *a, **kw: None):
            t = PollingTrader.__new__(PollingTrader)
        t.enable_mode_switch = t.enable_ev_radar = t.enable_multi_horizon = t.enable_ranked_tp = True
        t._cycle_idx = 0
        t._mode_cache = {}
        t._log = MagicMock()
        t.confidence_threshold = 0.50
        # 默认值（与 __init__ 保持一致）
        t.RANKED_TP_GAP_RATIO = 0.70
        t.RANKED_TP_MIN_PROFIT_USDT = 5.0
        # 临时 workspace_root patch：保证 config.json 路径定位到 tmp_path
        import scripts.memory_l4.paths as paths_mod
        return t, paths_mod

    def test_config_overrides_s4_defaults_on_init_reload(self):
        """config.json 中写出两个键 → 初始 reload 后 self.RANKED_TP_* 同步更新"""
        import json as _json
        import tempfile
        from pathlib import Path as _Path

        with tempfile.TemporaryDirectory() as td:
            tmp = _Path(td)
            # 模拟 workspace_root() 返回 tmp，使得 data/okx_sim/config.json 在 tmp 下
            (tmp / "data" / "okx_sim").mkdir(parents=True)
            cfg = {"ranked_tp_gap_ratio": 0.65, "ranked_tp_min_profit_usdt": 8.5}
            (tmp / "data" / "okx_sim" / "config.json").write_text(
                _json.dumps(cfg), encoding="utf-8")

            t, paths_mod = self._make_minimal_trader_with_config_paths(tmp)
            orig_ws = getattr(paths_mod, "workspace_root", None)
            try:
                paths_mod.workspace_root = lambda: tmp
                # initial=True (L214 调用路径) — 但 risk_manager 不存在，所以 initial=True 会抛异常然后静默 pass
                # 我们用 initial=False，因为 initial=True 要求 risk_manager 安全门
                t._load_evolution_config(initial=False)
            finally:
                if orig_ws is not None:
                    paths_mod.workspace_root = orig_ws

            self.assertAlmostEqual(
                t.RANKED_TP_GAP_RATIO, 0.65, delta=1e-6,
                msg="reload 后 RANKED_TP_GAP_RATIO 应覆盖为 0.65")
            self.assertAlmostEqual(
                t.RANKED_TP_MIN_PROFIT_USDT, 8.5, delta=1e-6,
                msg="reload 后 RANKED_TP_MIN_PROFIT_USDT 应覆盖为 8.5")
            # 也检查 [进化阈值/reload] 日志被打出（含 S4 字段）
            log_args = [c.args for c in t._log.call_args_list]
            s4_msgs = [a[0] for a in log_args if "RANKED_TP" in a[0]]
            self.assertTrue(len(s4_msgs) >= 1,
                            f"_log 应包含 RANKED_TP 覆盖日志，实际：{log_args}")

    def test_config_missing_keys_keeps_defaults_unchanged(self):
        """config.json 只写 confidence_threshold（不写 S4 两个键）→ 保持默认"""
        import json as _json
        import tempfile
        from pathlib import Path as _Path

        with tempfile.TemporaryDirectory() as td:
            tmp = _Path(td)
            (tmp / "data" / "okx_sim").mkdir(parents=True)
            (tmp / "data" / "okx_sim" / "config.json").write_text(
                _json.dumps({"confidence_threshold": 0.55}), encoding="utf-8")

            t, paths_mod = self._make_minimal_trader_with_config_paths(tmp)
            orig_ws = getattr(paths_mod, "workspace_root", None)
            try:
                paths_mod.workspace_root = lambda: tmp
                t._load_evolution_config(initial=False)
            finally:
                if orig_ws is not None:
                    paths_mod.workspace_root = orig_ws

            # 保持默认，未被改动
            self.assertAlmostEqual(t.RANKED_TP_GAP_RATIO, 0.70, delta=1e-9)
            self.assertAlmostEqual(t.RANKED_TP_MIN_PROFIT_USDT, 5.0, delta=1e-9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
