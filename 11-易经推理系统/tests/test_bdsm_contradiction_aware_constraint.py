"""三层矛盾感知方向约束算法 — TDD RED→GREEN。

当前 _compute_direction 只看 bds_score±0.3 硬阈值，忽略 confidence、value_exit、
valuation_percentile 三个联动信号，造成 (-0.3, 0) 区间"矛盾带"——value_exit=full_exit
但 direction=NEUTRAL 放行做多。SOL 实证 27 笔 24 亏(88.9%)。

新算法 _compute_direction_v2 三层递进：
  L1 置信度加权阈值: effective_threshold = 0.3 × (1 - 0.5 × confidence)
     bds < -effective_threshold → SHORT_ONLY
  L2 价值退出否决: value_exit.action=="full_exit" AND bds_score<0 AND confidence>=0.70
     → LONG_BLOCKED（禁做多，不强制做空，比 SHORT_ONLY 温和）
  L3 估值-BDS 矛盾: valuation_percentile>85 AND bds_score<0 AND data_quality=="sufficient"
     → LONG_BLOCKED（L2 未触发时的补充防线）

LONG_BLOCKED 语义：拦截 want=long(UP)，放行 want=short(DOWN)，cap_multiplier 保持原值。
开关 enable_contradiction_aware_constraint 默认 True，False → 走旧 _compute_direction 字节等价。
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BASE_11 = os.path.dirname(_THIS_DIR)  # 11-易经推理系统/
_FORCE_VEC_DIR = os.path.join(_BASE_11, "scripts", "memory_l4", "force_vector")
for _p in (_FORCE_VEC_DIR, _BASE_11):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class TestComputeDirectionV2(unittest.TestCase):
    """三层矛盾感知方向约束 — 纯函数级 RED 测试。"""

    # ── L1: 置信度加权阈值 ──
    def test_l1_high_confidence_narrows_threshold_triggers_short_only(self) -> None:
        """conf=0.875 → effective_threshold=0.169；bds=-0.20(<-0.169) → SHORT_ONLY。

        旧算法: |−0.20|<0.3 → NEUTRAL（放行）。
        新算法 L1: conf 高收窄阈值，−0.20<−0.169 → SHORT_ONLY（强烈看空）。
        """
        from bdsm_snapshot_writer import _compute_direction_v2  # noqa: WPS433
        self.assertEqual(
            _compute_direction_v2(
                bds_score=-0.20, confidence=0.875, data_quality="sufficient",
                value_exit_action="none", valuation_percentile=50.0,
            ),
            "SHORT_ONLY",
        )

    def test_l1_low_confidence_keeps_wide_threshold_stays_neutral(self) -> None:
        """conf=0.40 → effective_threshold=0.24；bds=-0.20(>-0.24) → NEUTRAL（L1 不触发）。

        低置信度不收窄阈值，避免信号不可靠时误触发。
        """
        from bdsm_snapshot_writer import _compute_direction_v2  # noqa: WPS433
        self.assertEqual(
            _compute_direction_v2(
                bds_score=-0.20, confidence=0.40, data_quality="partial",
                value_exit_action="none", valuation_percentile=50.0,
            ),
            "NEUTRAL",
        )

    def test_l1_long_side_symmetric_high_conf_narrows_to_long_only(self) -> None:
        """conf=1.0 → threshold=0.15；bds=+0.16(>0.15) → LONG_ONLY。"""
        from bdsm_snapshot_writer import _compute_direction_v2  # noqa: WPS433
        self.assertEqual(
            _compute_direction_v2(
                bds_score=0.16, confidence=1.0, data_quality="sufficient",
                value_exit_action="none", valuation_percentile=50.0,
            ),
            "LONG_ONLY",
        )

    # ── L2: 价值退出否决 → LONG_BLOCKED（关键中间档） ──
    def test_l2_full_exit_plus_negative_bds_plus_high_conf_yields_long_blocked(self) -> None:
        """SOL 核心案例: full_exit + bds=-0.1264<0 + conf=0.875>=0.70 → LONG_BLOCKED。

        旧算法: NEUTRAL（放行做多）→ 亏损。
        新算法 L2: LONG_BLOCKED（禁做多，允许做空，不强制做空）。
        """
        from bdsm_snapshot_writer import _compute_direction_v2  # noqa: WPS433
        self.assertEqual(
            _compute_direction_v2(
                bds_score=-0.1264, confidence=0.875, data_quality="sufficient",
                value_exit_action="full_exit", valuation_percentile=89.66,
            ),
            "LONG_BLOCKED",
        )

    def test_l2_full_exit_but_low_confidence_stays_neutral(self) -> None:
        """conf=0.50<0.70 → L2 不触发，保持 NEUTRAL（FAIL-OPEN，置信度不足不强拦）。"""
        from bdsm_snapshot_writer import _compute_direction_v2  # noqa: WPS433
        self.assertEqual(
            _compute_direction_v2(
                bds_score=-0.1264, confidence=0.50, data_quality="partial",
                value_exit_action="full_exit", valuation_percentile=89.66,
            ),
            "NEUTRAL",
        )

    def test_l2_full_exit_but_positive_bds_stays_neutral(self) -> None:
        """bds=+0.05>0 → 不满足"bds<0"条件，L2 不触发，NEUTRAL。

        价值退出可能由估值泡沫触发(非基本面恶化)，不强制 LONG_BLOCKED。
        """
        from bdsm_snapshot_writer import _compute_direction_v2  # noqa: WPS433
        self.assertEqual(
            _compute_direction_v2(
                bds_score=0.05, confidence=0.875, data_quality="sufficient",
                value_exit_action="full_exit", valuation_percentile=95.0,
            ),
            "NEUTRAL",
        )

    def test_l2_reduce30_does_not_trigger_long_blocked(self) -> None:
        """value_exit=reduce30（非 full_exit）→ L2 不触发；构造 val_pct≤85 避免 L3 误触发 → NEUTRAL。

        reduce30 是温和减仓建议，不构成对抗性矛盾。
        """
        from bdsm_snapshot_writer import _compute_direction_v2  # noqa: WPS433
        self.assertEqual(
            _compute_direction_v2(
                bds_score=-0.1264, confidence=0.875, data_quality="sufficient",
                value_exit_action="reduce30", valuation_percentile=70.0,
            ),
            "NEUTRAL",
        )

    # ── L3: 估值-BDS 矛盾 → LONG_BLOCKED（L2 未触发的补充防线） ──
    def test_l3_high_valuation_plus_negative_bds_sufficient_yields_long_blocked(self) -> None:
        """val_pct=88>85 AND bds=-0.10<0 AND sufficient → LONG_BLOCKED（L2 未触发因 full_exit 缺失）。"""
        from bdsm_snapshot_writer import _compute_direction_v2  # noqa: WPS433
        self.assertEqual(
            _compute_direction_v2(
                bds_score=-0.10, confidence=0.875, data_quality="sufficient",
                value_exit_action="none", valuation_percentile=88.0,
            ),
            "LONG_BLOCKED",
        )

    def test_l3_high_valuation_but_low_confidence_stays_neutral(self) -> None:
        """conf=0.50, dq=partial → L3 不触发（置信度+数据质量双重门禁）。"""
        from bdsm_snapshot_writer import _compute_direction_v2  # noqa: WPS433
        self.assertEqual(
            _compute_direction_v2(
                bds_score=-0.10, confidence=0.50, data_quality="partial",
                value_exit_action="none", valuation_percentile=88.0,
            ),
            "NEUTRAL",
        )

    def test_l3_normal_valuation_stays_neutral(self) -> None:
        """val_pct=60<85 → L3 不触发。"""
        from bdsm_snapshot_writer import _compute_direction_v2  # noqa: WPS433
        self.assertEqual(
            _compute_direction_v2(
                bds_score=-0.10, confidence=0.875, data_quality="sufficient",
                value_exit_action="none", valuation_percentile=60.0,
            ),
            "NEUTRAL",
        )

    # ── 层级优先级：L1 > L2 > L3 ──
    def test_priority_l1_short_only_overrides_l2_long_blocked(self) -> None:
        """bds=-0.20, conf=0.875, full_exit → L1 触发 SHORT_ONLY（最强制约）。

        L1 优先于 L2：当 bds_score 足够负（超过 L1 收窄阈值）时直接 SHORT_ONLY，
        L2 的 LONG_BLOCKED 不再适用（SHORT_ONLY 更强）。
        """
        from bdsm_snapshot_writer import _compute_direction_v2  # noqa: WPS433
        self.assertEqual(
            _compute_direction_v2(
                bds_score=-0.20, confidence=0.875, data_quality="sufficient",
                value_exit_action="full_exit", valuation_percentile=89.66,
            ),
            "SHORT_ONLY",
        )

    def test_priority_l2_overrides_l3_when_both_match(self) -> None:
        """L2+L3 都触发但值相同的场景下，L2 优先（L2 更明确：full_exit+高置信）。

        构造: bds=-0.10, conf=0.875, full_exit, val=88 → L2 和 L3 都满足，
        结果 LONG_BLOCKED（L2 和 L3 输出相同，L2 优先语义）。
        """
        from bdsm_snapshot_writer import _compute_direction_v2  # noqa: WPS433
        self.assertEqual(
            _compute_direction_v2(
                bds_score=-0.10, confidence=0.875, data_quality="sufficient",
                value_exit_action="full_exit", valuation_percentile=88.0,
            ),
            "LONG_BLOCKED",
        )

    # ── data_quality 门禁 ──
    def test_insufficient_data_quality_forces_neutral_regardless_of_signals(self) -> None:
        """data_quality=insufficient → 强制 NEUTRAL（FAIL-OPEN，信号不可靠不强拦）。"""
        from bdsm_snapshot_writer import _compute_direction_v2  # noqa: WPS433
        self.assertEqual(
            _compute_direction_v2(
                bds_score=-0.20, confidence=0.875, data_quality="insufficient",
                value_exit_action="full_exit", valuation_percentile=95.0,
            ),
            "NEUTRAL",
        )

    # ── 开关向后兼容 ──
    def test_switch_off_falls_back_to_old_compute_direction(self) -> None:
        """enable_contradiction_aware_constraint=False → 走旧 _compute_direction 逻辑。

        bds=-0.1264 旧算法 NEUTRAL（字节等价"开关不存在"）。
        """
        from bdsm_snapshot_writer import _compute_direction_v2  # noqa: WPS433
        self.assertEqual(
            _compute_direction_v2(
                bds_score=-0.1264, confidence=0.875, data_quality="sufficient",
                value_exit_action="full_exit", valuation_percentile=89.66,
                enable_contradiction_aware_constraint=False,
            ),
            "NEUTRAL",
        )


class TestApplyBDSMDirectionConstraintLongBlocked(unittest.TestCase):
    """消费端 _apply_bdsm_direction_constraint 新增 LONG_BLOCKED 分支。"""

    def setUp(self) -> None:
        _THIS = Path(__file__).resolve().parent
        _B11 = str(_THIS.parent)  # 11-易经推理系统/
        _MEM_L4 = os.path.join(_B11, "scripts", "memory_l4")
        # 路径顺序严格：先移除再插入，最终 _B11 最前（scripts.* 绝对包解析需要）
        for _p in (_MEM_L4, _B11):
            if _p in sys.path:
                sys.path.remove(_p)
        sys.path.insert(0, _MEM_L4)
        sys.path.insert(0, _B11)
        # 清理 scripts 命名空间包缓存：bdsm_snapshot_writer 导入时可能污染
        # scripts.__path__ 为错误值（scripts/memory_l4/scripts），导致后续
        # from scripts.memory_l4.polling_trader import 失败。
        for _mod_key in list(sys.modules.keys()):
            if _mod_key == "scripts" or _mod_key.startswith("scripts."):
                del sys.modules[_mod_key]

    def _make_trader(self, snap_coin_entry: dict, coin: str = "SOL") -> object:
        from unittest.mock import MagicMock, patch
        from scripts.memory_l4.polling_trader import PollingTrader
        with patch.object(PollingTrader, "__init__", lambda self, *a, **kw: None):
            t = PollingTrader.__new__(PollingTrader)
        t._log = MagicMock()
        t.BDSM_COINS = frozenset({"SOL", "UNI", "ETH", "BTC"})
        snap = {"version": "1.0", "coins": {coin: snap_coin_entry}}
        t._bdsm_snapshot_cache = {"ts": float("inf"), "snapshot": snap}
        return t

    def test_long_blocked_intercepts_up_direction(self) -> None:
        """LONG_BLOCKED + want UP(做多) → 拦截，返回 bdsm_long_blocked_dropped。"""
        t = self._make_trader({
            "available": True, "direction_constraint": "LONG_BLOCKED",
            "cap_multiplier": 0.25, "exit_action": "NONE",
            "data_quality": "sufficient", "confidence": 0.875,
        })
        is_pass, reason = t._apply_bdsm_direction_constraint("SOL", "UP")
        self.assertFalse(is_pass, f"LONG_BLOCKED 应拦截 UP: {reason}")
        self.assertIn("bdsm_long_blocked_dropped", reason)

    def test_long_blocked_allows_down_direction(self) -> None:
        """LONG_BLOCKED + want DOWN(做空) → 放行（不强制做空，但允许）。"""
        t = self._make_trader({
            "available": True, "direction_constraint": "LONG_BLOCKED",
            "cap_multiplier": 0.25, "exit_action": "NONE",
            "data_quality": "sufficient", "confidence": 0.875,
        })
        is_pass, reason = t._apply_bdsm_direction_constraint("SOL", "DOWN")
        self.assertTrue(is_pass, f"LONG_BLOCKED 应放行 DOWN: {reason}")
        self.assertIn("bdsm_long_blocked_short_allowed", reason)

    def test_long_blocked_neutral_when_confidence_insufficient(self) -> None:
        """data_quality=partial → LONG_BLOCKED 降级放行（置信度不足不强拦）。"""
        t = self._make_trader({
            "available": True, "direction_constraint": "LONG_BLOCKED",
            "cap_multiplier": 0.25, "exit_action": "NONE",
            "data_quality": "partial", "confidence": 0.375,
        })
        is_pass, reason = t._apply_bdsm_direction_constraint("SOL", "UP")
        self.assertTrue(is_pass, f"置信度不足应放行: {reason}")
        self.assertIn("bdsm_confidence_insufficient", reason)


if __name__ == "__main__":
    unittest.main()
