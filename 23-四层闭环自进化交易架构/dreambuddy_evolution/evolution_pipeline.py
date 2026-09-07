"""
EvolutionPipeline — 四层闭环进化架构编排器
蓝图: 四层闭环进化架构-最小阻力路径总览.md §一 闭环动作流

L1 状态空间 → Level 0 路径代价 → L2 策略匹配 → L3 Shadow-RL → L4 Bellman V(s) → 回馈
"""
import sys
import json
import math
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent


class EvolutionPipeline:
    """
    四层闭环 pipeline.
    MVP: L1→Level0→L2→决策 + L3/L4 骨架追踪.
    """

    def __init__(self, gene_root: Path | str | None = None):
        self.gene_root = Path(gene_root) if gene_root else (
            REPO_ROOT / "dreambuddy_evolution" / "gene_data"
        )

        # L3/L4 初始化
        from dreambuddy_evolution.core.shadow_rl import ShadowRLTracker
        from dreambuddy_evolution.core.bellman_tracker import BellmanVTracker
        self.shadow_rl = ShadowRLTracker()
        self.bellman = BellmanVTracker(alpha=0.1, gamma=0.95)

        # L2 library cache
        self._library = None

    def _load_library(self):
        if self._library is None:
            from dreambuddy_evolution.core import strategy_gene as sgs
            self._library = sgs.load_gene_library(self.gene_root)
        return self._library

    def _resolve_action_direction(self, action_ids: list[str]) -> str:
        """从 action gene 解析方向 (long/short/both/neutral)."""
        try:
            act_dir = self.gene_root / "strategy_genes" / "actions"
            directions = []
            for aid in action_ids:
                f = act_dir / f"{aid}.json"
                if f.exists():
                    g = json.loads(f.read_text(encoding="utf-8"))
                    d = g.get("direction", "neutral")
                    if d != "both":
                        directions.append(d)
            # 优先取非 both 方向
            for d in directions:
                if d in ("long", "short"):
                    return d
            return directions[0] if directions else "neutral"
        except Exception as e:
            logger.warning("[FO] action direction resolve fail: %s", e)
            return "neutral"

    def run_symbol(self, symbol: str, market_data: dict, rv=None) -> dict[str, Any]:
        """
        单 symbol 全 pipeline 运行.
        返回: {l1_r_vector, level0_d_star, l2_top_combo, aligned, action, l3_sample, l4_v}
        """
        from dreambuddy_evolution.core.resistance_vector import ResistanceVector
        from dreambuddy_evolution.core.level0_path_cost import compute_g_diag, compute_d_star
        from dreambuddy_evolution.core import strategy_gene as sgs

        # ============ L1: 状态空间层 ============
        if rv is None:
            rv = ResistanceVector()
        r_out = rv.calculate(symbol, market_data)

        # ============ Level 0: 路径代价计算 ============
        d_star_result = compute_d_star(r_out)
        d_star = d_star_result["d_star"]

        # ============ L2: 策略知识层 ============
        library = self._load_library()
        top_combos = sgs.top_combinations_by_ess(library, min_sample=0)
        top_combo = top_combos[0] if top_combos else None

        # 解析 top strategy 方向
        if top_combo:
            resolved_dir = self._resolve_action_direction(top_combo.get("action_ids", []))
            top_combo["resolved_direction"] = resolved_dir
        else:
            resolved_dir = "neutral"

        # ============ 对齐检查 (§1.5.5) ============
        aligned = False
        if d_star in ("long", "short") and resolved_dir == d_star:
            aligned = True
        elif d_star == "WAIT":
            aligned = False

        # ============ 决策输出 ============
        if aligned and d_star == "long":
            action = "long"
        elif aligned and d_star == "short":
            action = "short"
        elif d_star in ("long", "short") and not aligned:
            action = f"light_{d_star}"  # u=0.1 轻仓 (§1.5.5)
        else:
            action = "WAIT"

        # ============ L3: Shadow-RL 记录 ============
        shadow_reward = r_out["quality_score"] - 0.5  # 简化: quality > 0.5 = 正 reward
        self.shadow_rl.record(
            symbol=symbol,
            state={"R_up": r_out["R_up"], "R_down": r_out["R_down"],
                   "R_smooth": r_out["R_smooth"], "R_flow": r_out["R_flow"],
                   "R_reflexivity": r_out["R_reflexivity"]},
            action=action,
            reward=shadow_reward,
            next_state={},
        )

        # ============ L4: Bellman V(s) 更新 ============
        self.bellman.td_update(symbol, reward=shadow_reward, next_symbol=symbol)

        return {
            "symbol": symbol,
            "l1_r_vector": r_out,
            "level0_d_star": d_star,
            "level0_confidence": d_star_result["confidence"],
            "level0_costs": d_star_result["costs"],
            "l2_top_combo": top_combo,
            "aligned": aligned,
            "action": action,
            "l3_sample_count": self.shadow_rl.sample_count(),
            "l4_v": self.bellman.get_v(symbol),
        }

    def run_batch(self, symbols_data: dict[str, dict], rv=None) -> dict[str, dict]:
        """批量多 symbol pipeline."""
        results = {}
        for sym, data in symbols_data.items():
            try:
                results[sym] = self.run_symbol(sym, data, rv=rv)
            except Exception as e:  # FO-3 FAIL-OPEN
                logger.error("[FO-3] pipeline crash for %s: %s", sym, e)
                results[sym] = {
                    "symbol": sym,
                    "action": "WAIT",
                    "error": str(e),
                    "l1_r_vector": {},
                    "level0_d_star": "WAIT",
                    "l2_top_combo": None,
                    "aligned": False,
                }
        return results

    def get_feedback(self) -> dict[str, Any]:
        """L3/L4 回馈摘要 → L2 ESS 调整 + L1 权重校准."""
        rl_stats = self.shadow_rl.get_stats()
        v_all = self.bellman.get_all_v()
        ess_adjusts = {sym: self.bellman.get_ess_adjustment(sym) for sym in v_all}
        return {
            "l3_stats": rl_stats,
            "l4_v_all": v_all,
            "l4_ess_adjustments": ess_adjusts,
        }
