#!/usr/bin/env python3
"""
test_multi_horizon_predict.py — Phase C TDD 测试集（S3 = enable_multi_horizon）
对应 Spec §5.3: 多 horizon 预测 + 最佳离场 K 线推荐

RED 失败原因:
  - RiskManager.predict_multi_horizon 静态方法不存在
  - PollingTrader._recommend_exit_bars 方法不存在 / 开关短路分支未写
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scripts.memory_l4.polling_trader import PollingTrader  # noqa: E402
from scripts.memory_l4.trading_utils import RiskManager  # noqa: E402


def _make_trader(coins=None, max_positions=3, enable_multi_horizon=True):
    """轻量 mock 构造（复用 Phase A/B 风格）"""
    with patch.object(PollingTrader, "__init__", lambda self, *a, **kw: None):
        t = PollingTrader.__new__(PollingTrader)
    t.coins = list(coins or ["BTC", "SOL", "XAU"])
    t.max_positions = max_positions
    t.enable_mode_switch = True
    t.enable_ev_radar = True
    t.enable_multi_horizon = enable_multi_horizon
    t.enable_ranked_tp = True
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
    # Phase C: 多 horizon 默认参数（Spec §4.3.1）
    t.HORIZON_BAR_CANDIDATES = [1, 2, 3, 6, 10, 20, 30]  # 对齐 BCRM2 多 horizon 训练
    t.HORIZON_PREP_EXIT_MARGIN = 3  # 与 best_k_bar 差 3 根内 → PREP_EXIT
    return t


# =====================================================================
# C-1: predict_multi_horizon 纯函数结构（Spec 5.3 多 horizon 输出形状）
# =====================================================================
class TestPredictMultiHorizonShape(unittest.TestCase):
    """Spec 5.3 测试 1: 返回结构含 horizons + recommended_action"""

    def test_predict_multi_horizon_returns_horizons_and_action(self):
        """RED 失败原因: RiskManager.predict_multi_horizon 静态方法不存在"""
        # 构造占位推理输入（模拟 BCRM 粗推理输出简化版）
        base_inference = {
            "confidence": 0.80,
            "direction": "UP",
            "price": 60000.0,
            "volatility": 0.03,
            # 五角校验得分（0~1），越多维度一致 → 长 horizon 置信度高
            "pentagon_scores": {"bagua": 0.82, "trend": 0.76, "regime": 0.71,
                                "macro": 0.65, "cross": 0.59},
        }
        k_candidates = [1, 2, 3, 6, 10, 20, 30]

        result = RiskManager.predict_multi_horizon(base_inference, k_candidates)

        # 返回 dict 必须含 horizons 列表 + recommended_action
        self.assertIsInstance(result, dict)
        self.assertIn("horizons", result)
        self.assertIn("recommended_action", result)
        self.assertIsInstance(result["horizons"], list)
        self.assertEqual(len(result["horizons"]), len(k_candidates),
                         "每个候选 K-bar 对应一个 horizon 条目")
        # 每个 horizon 条目: {k_bar, confidence, direction, expected_roi_pct}
        for h, k_expected in zip(result["horizons"], k_candidates):
            self.assertEqual(h["k_bar"], k_expected)
            self.assertIn("confidence", h)
            self.assertIn("direction", h)
            self.assertIn("expected_roi_pct", h)
        # recommended_action ∈ {"HOLD", "PREP_EXIT", "EXTEND_TRACK", "NOOP"}
        self.assertIn(
            result["recommended_action"],
            {"HOLD", "PREP_EXIT", "EXTEND_TRACK", "NOOP"},
            f"recommended_action={result['recommended_action']} 不在合法集合",
        )


# =====================================================================
# C-2: 最佳 horizon > 已持仓 K 线数 → HOLD（继续赚完趋势）
# =====================================================================
class TestRecommendExitBarsHold(unittest.TestCase):
    """Spec 5.3 测试 2: best_k_bar > held_k_bar → HOLD"""

    def test_best_horizon_longer_than_held_holds(self):
        """RED 失败原因: PollingTrader._recommend_exit_bars 不存在"""
        t = _make_trader(enable_multi_horizon=True)
        # monkeypatch: 让 RiskManager.predict_multi_horizon 返回 best_k_bar=40
        # （通过 horizon 里 confidence 最高的 k_bar=40 触发 HOLD 推荐）
        import scripts.memory_l4.trading_utils as tu

        def _fake_pred(inference, k_candidates):
            horizons = []
            for k in k_candidates:
                # k=20 置信度最高（在候选[1,2,3,6,10,20,30]中）
                c = 0.5 if k != 20 else 0.91
                horizons.append({
                    "k_bar": k, "confidence": c,
                    "direction": "UP", "expected_roi_pct": 0.05,
                })
            return {"horizons": horizons, "recommended_action": "HOLD"}

        tu.RiskManager.predict_multi_horizon = staticmethod(_fake_pred)

        # 已持仓 k_bar=10，best=20 → 远没到最佳离场站（20>10+3=13），应 HOLD
        result = t._recommend_exit_bars(
            coin="BTC", pos_side="long",
            held_k_bar=10,  # 持仓 10 根 1H-K ≈ 10h
            inference={"confidence": 0.80, "direction": "UP",
                       "price": 60000.0, "volatility": 0.03,
                       "pentagon_scores": {}},
            k_candidates=getattr(t, "HORIZON_BAR_CANDIDATES", [1, 2, 3, 6, 10, 20, 30]),
        )

        self.assertIsInstance(result, dict)
        self.assertIn("best_k_bar", result)
        self.assertIn("recommended_action", result)
        self.assertEqual(result["best_k_bar"], 20)
        self.assertEqual(result["recommended_action"], "HOLD",
                         f"best=20 > held=10+margin=3 → 必须 HOLD，实际={result['recommended_action']}")


# =====================================================================
# C-3: 最佳 horizon < 已持仓 + 反向 → PREP_EXIT（准备离场）
# =====================================================================
class TestRecommendExitBarsPrepExit(unittest.TestCase):
    """Spec 5.3 测试 3: best_k_bar << held_k_bar 且反向 → PREP_EXIT"""

    def test_best_horizon_way_shorter_than_held_and_reverse_marks_prep_exit(self):
        """RED 失败原因: PREP_EXIT 分支未写"""
        t = _make_trader(enable_multi_horizon=True)

        import scripts.memory_l4.trading_utils as tu

        def _fake_pred(inference, k_candidates):
            horizons = []
            for k in k_candidates:
                # 多做 long，但 horizon 的最佳方向为 DOWN（反向）
                # 且 best_k_bar = 3（最短之一）
                c = 0.90 if k == 3 else 0.5
                horizons.append({
                    "k_bar": k, "confidence": c,
                    "direction": "DOWN",   # 与持仓 long 相反
                    "expected_roi_pct": -0.03 if k == 3 else 0.0,
                })
            return {"horizons": horizons, "recommended_action": "PREP_EXIT"}

        tu.RiskManager.predict_multi_horizon = staticmethod(_fake_pred)

        result = t._recommend_exit_bars(
            coin="BTC", pos_side="long",
            held_k_bar=25,  # 持仓已过 25h，远超 best=3
            inference={"confidence": 0.80, "direction": "UP",
                       "price": 60000.0, "volatility": 0.03,
                       "pentagon_scores": {}},
            k_candidates=getattr(t, "HORIZON_BAR_CANDIDATES"),
        )

        self.assertEqual(result["best_k_bar"], 3)
        self.assertEqual(result["recommended_action"], "PREP_EXIT",
                         f"反向 + best=3 << held=25 → 必须 PREP_EXIT")


# =====================================================================
# C-4: S3 开关关闭 → predict_multi_horizon 从未被调用
# =====================================================================
class TestMultiHorizonSwitchOffBypasses(unittest.TestCase):
    """Spec 5.3 测试 4: enable_multi_horizon=False → 直接 BYPASS"""

    def test_switch_off_predict_never_called(self):
        """RED 失败原因: 开关短路分支未写，predict_multi_horizon 仍被调用"""
        t = _make_trader(enable_multi_horizon=False)  # S3=OFF

        import scripts.memory_l4.trading_utils as tu
        call_count = {"n": 0}

        def _fake_pred(inference, k_candidates):
            call_count["n"] += 1
            return {"horizons": [], "recommended_action": "NOOP"}

        tu.RiskManager.predict_multi_horizon = staticmethod(_fake_pred)

        for _ in range(10):
            _ = t._recommend_exit_bars(
                coin="BTC", pos_side="long", held_k_bar=10,
                inference={"confidence": 0.8, "direction": "UP",
                           "price": 60000.0, "volatility": 0.03},
            )

        self.assertEqual(
            call_count["n"], 0,
            f"S3=OFF 时 predict_multi_horizon 必须从未被调用，实际 {call_count['n']} 次",
        )


# =====================================================================
# C-5: S3 HORIZON_PREP_EXIT_MARGIN 热配置 reload 验证
# =====================================================================
class TestHorizonPrepExitMarginHotConfig(unittest.TestCase):
    """C6 实现验证：_load_evolution_config 中 horizon_prep_exit_margin
    会覆盖 self.HORIZON_PREP_EXIT_MARGIN 默认值。

    注意：HORIZON_BAR_CANDIDATES 不做热配置（变更需重训多 horizon 模型）。
    """

    @staticmethod
    def _make_minimal_trader():
        with patch.object(PollingTrader, "__init__", lambda self, *a, **kw: None):
            t = PollingTrader.__new__(PollingTrader)
        t.enable_mode_switch = t.enable_ev_radar = t.enable_multi_horizon = t.enable_ranked_tp = True
        t._cycle_idx = 0
        t._mode_cache = {}
        t._log = MagicMock()
        t.confidence_threshold = 0.50
        t.HORIZON_BAR_CANDIDATES = [1, 2, 3, 6, 10, 20, 30]
        t.HORIZON_PREP_EXIT_MARGIN = 3
        import scripts.memory_l4.paths as paths_mod
        return t, paths_mod

    def test_config_overrides_horizon_margin(self):
        """config.json 写出 horizon_prep_exit_margin=5 → self.HORIZON_PREP_EXIT_MARGIN=5"""
        import json as _json
        import tempfile
        from pathlib import Path as _Path

        with tempfile.TemporaryDirectory() as td:
            tmp = _Path(td)
            (tmp / "data" / "okx_sim").mkdir(parents=True)
            cfg = {"horizon_prep_exit_margin": 5}
            (tmp / "data" / "okx_sim" / "config.json").write_text(
                _json.dumps(cfg), encoding="utf-8")

            t, paths_mod = self._make_minimal_trader()
            orig_ws = getattr(paths_mod, "workspace_root", None)
            try:
                paths_mod.workspace_root = lambda: tmp
                t._load_evolution_config(initial=False)
            finally:
                if orig_ws is not None:
                    paths_mod.workspace_root = orig_ws

            self.assertEqual(
                t.HORIZON_PREP_EXIT_MARGIN, 5,
                msg="reload 后 HORIZON_PREP_EXIT_MARGIN 应覆盖为 5")

    def test_config_missing_key_keeps_default(self):
        """config.json 不写 horizon_prep_exit_margin → 保持默认 3"""
        import json as _json
        import tempfile
        from pathlib import Path as _Path

        with tempfile.TemporaryDirectory() as td:
            tmp = _Path(td)
            (tmp / "data" / "okx_sim").mkdir(parents=True)
            (tmp / "data" / "okx_sim" / "config.json").write_text(
                _json.dumps({"confidence_threshold": 0.55}), encoding="utf-8")

            t, paths_mod = self._make_minimal_trader()
            orig_ws = getattr(paths_mod, "workspace_root", None)
            try:
                paths_mod.workspace_root = lambda: tmp
                t._load_evolution_config(initial=False)
            finally:
                if orig_ws is not None:
                    paths_mod.workspace_root = orig_ws

            self.assertEqual(t.HORIZON_PREP_EXIT_MARGIN, 3,
                             msg="config 未写 horizon_prep_exit_margin → 保持默认 3")

    def test_config_invalid_value_keeps_default(self):
        """config.json 写非法值（0 / 负数 / 字符串）→ 保持默认"""
        import json as _json
        import tempfile
        from pathlib import Path as _Path

        with tempfile.TemporaryDirectory() as td:
            tmp = _Path(td)
            (tmp / "data" / "okx_sim").mkdir(parents=True)
            # 0 不在 (0, 20] 范围内 → 应被拒绝
            cfg = {"horizon_prep_exit_margin": 0}
            (tmp / "data" / "okx_sim" / "config.json").write_text(
                _json.dumps(cfg), encoding="utf-8")

            t, paths_mod = self._make_minimal_trader()
            orig_ws = getattr(paths_mod, "workspace_root", None)
            try:
                paths_mod.workspace_root = lambda: tmp
                t._load_evolution_config(initial=False)
            finally:
                if orig_ws is not None:
                    paths_mod.workspace_root = orig_ws

            self.assertEqual(t.HORIZON_PREP_EXIT_MARGIN, 3,
                             msg="horizon_prep_exit_margin=0 非法 → 保持默认 3")


if __name__ == "__main__":
    unittest.main(verbosity=2)
