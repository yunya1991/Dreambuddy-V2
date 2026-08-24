# -*- coding: utf-8 -*-
"""PUMP事件根因修复 TDD 测试集.

修复项（对应 2026-08-23 PUMP-USDT-SWAP 亏损事件）:
  1. 卦象→方向映射表准确性（HEX_TO_DIRECTION vs SIXTY_FOUR_GUAS）
  2. 开仓前卦象→方向一致性校验（查表冲突 + 历史滑窗一致性）
  3. 信号反转(SignalReverseStrategy)置信度余量保护 + 硬下限

每个新测试 **先失败** → 对应代码实现后 **再通过**。
"""
import sys
from pathlib import Path
from collections import deque
from typing import Dict, List, Optional, Tuple

import pytest

_MEMORY_L4 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MEMORY_L4))


# ================================================================
# Suite 1: HEX_TO_DIRECTION 映射表准确性审计
# (先修映射表再验证 — 对应 PUMP 中天地否/山风蛊等卦方向错乱源头)
# ================================================================
class TestHexagramDirectionMappingAccuracy:
    """HEX_TO_DIRECTION 必须严格对齐 dialectical_ml_engine.SIXTY_FOUR_GUAS。"""

    def _load_canonical(self) -> Dict[str, str]:
        from bcrm2.dialectical_ml_engine import SIXTY_FOUR_GUAS
        return {info["name"]: info["direction"] for info in SIXTY_FOUR_GUAS.values()}

    def _load_trader_mapping(self) -> Dict[str, str]:
        """通过 AST 解析 polling_trader._get_hexagram_direction 中的 HEX_TO_DIRECTION。"""
        import ast
        src = (_MEMORY_L4 / "polling_trader.py").read_text()
        tree = ast.parse(src)

        mapping: Dict[str, str] = {}

        class Visitor(ast.NodeVisitor):
            def visit_FunctionDef(self, node):
                if node.name != "_get_hexagram_direction":
                    return
                for sub in ast.walk(node):
                    if not isinstance(sub, ast.Dict):
                        continue
                    for k, v in zip(sub.keys, sub.values):
                        if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                            mapping[k.value] = v.value

        Visitor().visit(tree)
        return mapping

    def test_mapping_contains_all_64_hexagrams(self):
        """HEX_TO_DIRECTION 条目数必须 = 64（不多不少）。"""
        canonical = self._load_canonical()
        trader_map = self._load_trader_mapping()
        assert len(canonical) == 64, "SIXTY_FOUR_GUAS 权威表应为 64 卦"
        assert len(trader_map) == 64, (
            f"HEX_TO_DIRECTION 实际={len(trader_map)} 卦，"
            f"缺 {64 - len(trader_map)} 卦"
        )

    def test_no_broken_garbage_keys_from_string_concat_bug(self):
        """不得存在 隐式字符串拼接 产生的垃圾键（如 L2929 拼接bug "山水蒙_dup山风蛊"）。"""
        trader_map = self._load_trader_mapping()
        garbage = [k for k in trader_map if "_dup" in k or len(k) > 5]
        assert garbage == [], f"检测到垃圾键（字符串拼接bug残留）: {garbage}"

    def test_mapping_perfect_match_to_canonical(self):
        """64卦 名称集合 + 方向 必须与权威表 100% 一致，6卦方向错误+11卦缺失均不得重现。"""
        canonical = self._load_canonical()
        trader_map = self._load_trader_mapping()

        missing = set(canonical.keys()) - set(trader_map.keys())
        extra = set(trader_map.keys()) - set(canonical.keys())
        assert missing == set(), f"缺失 {len(missing)} 卦: {sorted(missing)}"
        assert extra == set(), f"多余 {len(extra)} 卦: {sorted(extra)}"

        conflicts: List[str] = []
        for name, canon_dir in canonical.items():
            actual_dir = trader_map[name]
            if actual_dir != canon_dir:
                conflicts.append(
                    f"{name}: 权威={canon_dir!r} 当前={actual_dir!r}"
                )
        assert conflicts == [], (
            f"{len(conflicts)} 卦方向与权威表矛盾: \n  - " + "\n  - ".join(conflicts)
        )


# ================================================================
# Suite 2: SignalReverseStrategy 置信度余量保护 + 硬下限
# (对应 PUMP: effective_threshold=0.6357, conf=0.65 barely过 → 应需 margin≥0.05 才触发)
# ================================================================
class TestSignalReverseMarginAndHardFloor:
    """反转信号阈值必须满足：
    - 硬下限 min_reverse_threshold：threshold 不得低于此（默认生产值 0.70）
    - 余量 reverse_confidence_margin：confidence - threshold ≥ 此值（默认 0.05）
    - 保护期内：margin × 2
    """

    def _make_ctx(self, pos_side="long", direction="DOWN",
                  confidence=0.75, in_protection=False,
                  effective_threshold=None, coin="PUMP"):
        from bcrm2.exit_manager import ExitContext
        return ExitContext(
            coin=coin,
            inference={"direction": direction},
            pos_info={"pos_side": pos_side},
            tracker_pos=None,
            in_protection=in_protection,
            age_hours=6.0,
            confidence=confidence,
            effective_threshold=effective_threshold,
        )

    # ─────────────────── 硬下限保护 ───────────────────
    def test_hard_floor_lifts_below_min_threshold(self):
        """【PUMP复现】effective_threshold=0.6357 被硬下限抬到 0.70。"""
        from bcrm2.exit_strategies import SignalReverseStrategy

        # prod-like params: 硬下限0.70, margin0.05
        strat = SignalReverseStrategy(
            base_threshold=0.7, min_reverse_threshold=0.70,
            reverse_confidence_margin=0.05, exit_confirm_required=1,
        )
        # 0.66 confidence > 0.6357 (was PASSING pre-fix) but < 0.70 hard floor
        ctx = self._make_ctx(
            pos_side="long", direction="DOWN",
            confidence=0.66, effective_threshold=0.6357)
        d = strat.evaluate(ctx)
        assert d.action == "pass", (
            "硬下限0.70 未生效：effective_threshold=0.6357 + conf=0.66 "
            "应该被硬下限拦住，实际却触发了"
        )

    def test_hard_floor_satisfied_allows_signal(self):
        """硬下限0.70 满足 (0.75) + margin 充足 → 正常触发。"""
        from bcrm2.exit_strategies import SignalReverseStrategy

        strat = SignalReverseStrategy(
            base_threshold=0.7, min_reverse_threshold=0.70,
            reverse_confidence_margin=0.05, exit_confirm_required=1,
        )
        # 0.75 >= hard floor 0.70, and 0.75 - 0.70 = 0.05 (exactly margin)
        ctx = self._make_ctx(
            pos_side="long", direction="DOWN",
            confidence=0.75, effective_threshold=0.6357)
        d = strat.evaluate(ctx)
        assert d.action == "force_close"

    # ─────────────────── 余量保护 ───────────────────
    def test_margin_violation_blocks_close(self):
        """【PUMP复现】conf=0.65 vs eff_thr=0.6357 → margin=0.0143 < 0.05 → 不触发。"""
        from bcrm2.exit_strategies import SignalReverseStrategy

        strat = SignalReverseStrategy(
            base_threshold=0.7, min_reverse_threshold=0.0,  # 只测试 margin
            reverse_confidence_margin=0.05, exit_confirm_required=1,
        )
        ctx = self._make_ctx(
            pos_side="long", direction="DOWN",
            confidence=0.65, effective_threshold=0.6357)
        d = strat.evaluate(ctx)
        assert d.action == "pass", (
            f"margin保护未生效: conf={0.65} thr={0.6357} "
            f"margin={0.65-0.6357:.4f} < 0.05 → 应当pass, 实际 {d.action}"
        )

    def test_margin_satisfied_allows_close(self):
        """conf=0.70 vs eff_thr=0.6357 → margin=0.0643 >= 0.05 → 允许触发。"""
        from bcrm2.exit_strategies import SignalReverseStrategy

        strat = SignalReverseStrategy(
            base_threshold=0.7, min_reverse_threshold=0.0,
            reverse_confidence_margin=0.05, exit_confirm_required=1,
        )
        ctx = self._make_ctx(
            pos_side="long", direction="DOWN",
            confidence=0.70, effective_threshold=0.6357)
        d = strat.evaluate(ctx)
        assert d.action == "force_close"

    # ─────────────────── 保护期 margin ×2 ───────────────────
    def test_protection_period_margin_is_doubled(self):
        """保护期：margin×2 = 0.10。conf 0.80 - thr 0.70 = 0.10 刚好通过。"""
        from bcrm2.exit_strategies import SignalReverseStrategy

        strat = SignalReverseStrategy(
            base_threshold=0.7,
            protected_conf_boost=0.0,  # 简化：不叠加 boost
            protected_min_threshold=0.70,
            min_reverse_threshold=0.0,
            reverse_confidence_margin=0.05,
            exit_confirm_required=1,
        )
        # 非保护期：margin = 0.05, 0.74 - 0.70 = 0.04 < 0.05 → pass
        ctx_norm = self._make_ctx(
            pos_side="long", direction="DOWN",
            confidence=0.74, effective_threshold=0.70,
            in_protection=False)
        assert strat.evaluate(ctx_norm).action == "pass"

        # 保护期：margin × 2 = 0.10, 0.80 - 0.70 = 0.10 刚好过
        ctx_prot = self._make_ctx(
            pos_side="long", direction="DOWN",
            confidence=0.80, effective_threshold=0.70,
            in_protection=True)
        d = strat.evaluate(ctx_prot)
        assert d.action == "force_close", (
            "保护期 margin×2=0.10 未生效（0.80-0.70=0.10应刚好通过）"
        )

    def test_protection_period_margin_violation_blocks(self):
        """保护期 margin×2 = 0.10。conf 0.78 - thr 0.70 = 0.08 < 0.10 → 拦。"""
        from bcrm2.exit_strategies import SignalReverseStrategy

        strat = SignalReverseStrategy(
            base_threshold=0.7,
            protected_conf_boost=0.0,
            protected_min_threshold=0.70,
            min_reverse_threshold=0.0,
            reverse_confidence_margin=0.05,
            exit_confirm_required=1,
        )
        ctx = self._make_ctx(
            pos_side="long", direction="DOWN",
            confidence=0.78, effective_threshold=0.70,
            in_protection=True)
        d = strat.evaluate(ctx)
        assert d.action == "pass", (
            "保护期 margin×2=0.10 应拦截 conf=0.78 (margin 0.08 < 0.10), 但实际放行"
        )

    # ─────────────────── 兼容性：默认参数不破坏旧行为 ───────────────────
    def test_default_params_backward_compatible(self):
        """默认值（margin=0, min=0 禁用）→ 与修复前行为字节等价。"""
        from bcrm2.exit_strategies import SignalReverseStrategy

        strat = SignalReverseStrategy(
            base_threshold=0.7, exit_confirm_required=2)  # 使用完全默认
        ctx = self._make_ctx(
            pos_side="long", direction="DOWN",
            confidence=0.71, effective_threshold=0.70)  # margin 只有 0.01
        # 默认无margin + 无下限：第1次 hold, 第2次 force_close（修复前等价）
        d1 = strat.evaluate(ctx)
        assert d1.action == "hold"
        d2 = strat.evaluate(ctx)
        assert d2.action == "force_close"


# ================================================================
# Suite 3: 开仓前卦象→方向一致性校验（查表 + 历史滑窗）
# (对应 PUMP: 天地否 映射SHORT + 历史统计SHORT，仅 08:19 异常输出 UP/0.87)
# ================================================================
class TestEntryHexagramDirectionConsistency:
    """开仓前 _check_hexagram_consistency_for_entry 返回三要素：
    (block: bool, conf_mult: float, raise_a_floor_to: Optional[float], reason: str)

    插入点：A项过滤之后、P0卦象黑名单之后、增强器之前。
    """

    # 模拟"最近N次相同卦象方向记录"的结构 (List[Tuple[hex_name, actual_dir]])
    # actual_dir = "long"/"short" 对应推理结果当时的决策方向（或卦象映射方向）
    HIST_WINDOW_TYPE = List[Tuple[str, str]]

    def _call_check(self, hex_name: str, decision_direction: str,
                    decision_confidence: float,
                    history: Optional[HIST_WINDOW_TYPE] = None,
                    min_hist_for_dominant: int = 3,
                    dominant_min_ratio: float = 0.60):
        """直接调用 polling_trader 内部函数（提取为类方法后可独立测试）。"""
        # 通过 importlib 导入独立单元函数
        from polling_trader import PollingTrader
        history = history or []
        return PollingTrader._check_hexagram_consistency_for_entry(
            hex_name=hex_name,
            decision_direction=decision_direction,  # "UP"/"DOWN"
            decision_confidence=decision_confidence,
            history_window=history,
            min_hist_for_dominant=min_hist_for_dominant,
            dominant_min_ratio=dominant_min_ratio,
            # 查表：从方法内部调用 _get_hexagram_direction（无需外部传）
        )

    # ─────────────────── 查表冲突 ───────────────────
    def test_lookup_conflict_short_vs_long_decision_blocks(self):
        """【PUMP复现】天地否 = SHORT，但决策方向 LONG → 查表冲突：block=True + 惩罚置信度。"""
        from polling_trader import PollingTrader
        res = PollingTrader._check_hexagram_consistency_for_entry(
            hex_name="天地否",
            decision_direction="UP",      # long
            decision_confidence=0.87,     # PUMP 开仓置信度
            history_window=[],
        )
        assert res["block"] is True or res["confidence_multiplier"] < 1.0 or res.get("raise_a_floor_to"), (
            f"查表冲突未生效！天地否=SHORT, 决策=UP(LONG) "
            f"→ 应当block或置信度×<1.0或抬高门槛, 实际: {res}"
        )
        # 至少应该把置信度压下来，PUMP的0.87 应当乘 0.7 或 直接block
        new_conf = 0.87 * res["confidence_multiplier"]
        assert new_conf < 0.85, (
            f"查表冲突惩罚太轻！原 0.87 × {res['confidence_multiplier']} = {new_conf:.3f}, "
            f"仍能过 A 项门槛(0.70)而无地板抬高时会放行"
        )
        # 并且应当把 A 项门槛抬高到 0.85+
        assert (res.get("raise_a_floor_to") or 0) >= 0.85, (
            f"查表冲突时必须抬高 A 项门槛。当前 raise_a_floor_to={res.get('raise_a_floor_to')!r}"
        )

    def test_lookup_consistent_long_hex_vs_long_decision_passes(self):
        """查表一致（乾为天=long vs 决策=UP）→ 无任何惩罚。"""
        from polling_trader import PollingTrader
        res = PollingTrader._check_hexagram_consistency_for_entry(
            hex_name="乾为天",
            decision_direction="UP",
            decision_confidence=0.80,
            history_window=[],
        )
        assert res["block"] is False
        assert res["confidence_multiplier"] == 1.0
        assert res.get("raise_a_floor_to") in (None, 0.0, 0.70)

    def test_lookup_neutral_hex_no_penalty(self):
        """查表 neutral（山水蒙=short现在权威是short，改用天水讼=neutral）→ 无惩罚。"""
        from polling_trader import PollingTrader
        res = PollingTrader._check_hexagram_consistency_for_entry(
            hex_name="天水讼",     # neutral
            decision_direction="UP",
            decision_confidence=0.75,
            history_window=[],
        )
        assert res["block"] is False
        assert res["confidence_multiplier"] == 1.0

    # ─────────────────── 历史滑窗一致性 ───────────────────
    def test_history_dominant_vs_current_conflict_blocks(self):
        """【PUMP复现】天地否 近20次全部 DOWN(SHORT)，当前 UP → 历史+查表双冲突：硬 block。"""
        from polling_trader import PollingTrader
        history: List[Tuple[str, str]] = [("天地否", "short")] * 5  # 5次SHORT
        res = PollingTrader._check_hexagram_consistency_for_entry(
            hex_name="天地否",
            decision_direction="UP",       # LONG（与历史+查表均冲突）
            decision_confidence=0.87,
            history_window=history,
            min_hist_for_dominant=3,
            dominant_min_ratio=0.60,
        )
        assert res["block"] is True, (
            f"查表+历史双冲突时必须硬block，实际 block={res['block']} res={res}"
        )

    def test_history_unstable_hex_applies_soft_penalty(self):
        """同一卦象 历史方向分布 < 60% 一致（不稳定）→ soft 惩罚，不block。"""
        from polling_trader import PollingTrader
        history: List[Tuple[str, str]] = [
            ("风天小畜", "long"),
            ("风天小畜", "short"),
            ("风天小畜", "long"),
            ("风天小畜", "short"),
            ("风天小畜", "long"),  # 5次: 3long/2short → 60% 刚好到阈值
        ]
        # 再加 2 short → 3 long / 4 short → 一致率 42.8% < 60%
        history.append(("风天小畜", "short"))
        history.append(("风天小畜", "short"))
        res = PollingTrader._check_hexagram_consistency_for_entry(
            hex_name="风天小畜",
            decision_direction="UP",
            decision_confidence=0.78,
            history_window=history,
            min_hist_for_dominant=3,
            dominant_min_ratio=0.60,
        )
        assert res["block"] is False, "不稳定卦象不应硬block（数据不足/暂态）"
        assert res["confidence_multiplier"] <= 0.90, (
            f"不稳定卦象应给予置信度×≤0.90惩罚，当前={res['confidence_multiplier']}"
        )

    def test_history_consistent_matches_lookup_no_penalty(self):
        """历史主导方向 与 查表方向 一致，且匹配决策 → 无任何惩罚。"""
        from polling_trader import PollingTrader
        history: List[Tuple[str, str]] = [("乾为天", "long")] * 6
        res = PollingTrader._check_hexagram_consistency_for_entry(
            hex_name="乾为天",
            decision_direction="UP",
            decision_confidence=0.82,
            history_window=history,
        )
        assert res["block"] is False
        assert res["confidence_multiplier"] == 1.0
        assert not res.get("raise_a_floor_to")
