"""
TightCouplingOrchestrator (§一·七 两条链路紧耦合流)
蓝图: 四层闭环进化架构-最小阻力路径总览.md §一·七

7 步闭环: 观察→推断→实验→测量→反思→学习→泛化→回馈
RippleEngine(§0.7) → test position(§1.5.5) → ReflectionEngine(§1.6) → ESS feedback
"""
import sys
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent


class TightCouplingOrchestrator:
    """紧耦合编排器 — 串联 RippleEngine + ReflectionEngine"""

    def __init__(self, mode: str = "MVP"):
        """
        mode: "MVP" = 松耦合(Lark人工中转), "Phase2" = 紧耦合(全自动)
        """
        self.mode = mode
        for p in [str(REPO_ROOT), str(REPO_ROOT / "dreambuddy_core")]:
            if p not in sys.path:
                sys.path.insert(0, p)
        from ripple_engine import RippleEngine
        from reflection_engine import ReflectionEngine
        from level0_path_cost import compute_d_star
        self.ripple = RippleEngine()
        self.reflection = ReflectionEngine()
        self._compute_d_star = compute_d_star

    def observe(self, market_data: dict[str, Any]) -> dict[str, Any]:
        """步骤① 观察: RippleEngine 龙头检测 + 涟漪扩散 → RI"""
        try:
            leader = market_data.get("leader_symbol", "")
            r_vec = market_data.get("leader_r_vector") or market_data.get("r_vector") or {}
            ess_dir = market_data.get("ess_top_direction", "")
            source = {
                "symbol": leader,
                "r_vector": r_vec,
                "ess_top_direction": ess_dir,
                "vol_5": market_data.get("vol_5", 0),
                "vol_20": market_data.get("vol_20", 1e-9),
                "liq_index_change": market_data.get("liq_index_change", 0),
                "scale_class": market_data.get("scale_class", ""),
            }
            is_source = self.ripple.detect_ripple_source(source)
            ripples = market_data.get("ripples", {})
            ri = self.ripple.compute_ri(ripples) if is_source else 0.50
            return {
                "leader_symbol": leader,
                "leader_r_vector": r_vec,
                "is_ripple_source": is_source,
                "ri": ri,
                "ess_top_direction": ess_dir,
            }
        except Exception as e:
            logger.warning("[FO] observe fail: %s", e)
            return {"ri": 0.50, "is_ripple_source": False, "leader_r_vector": {},
                    "leader_symbol": "", "ess_top_direction": ""}

    def hypothesize(self, obs: dict[str, Any]) -> dict[str, Any]:
        """步骤② 推断: RI 阈值表 → 推断标记"""
        ri = float(obs.get("ri", 0.50))
        action = self.ripple.get_ri_action(ri)
        inference_formed = ri >= 0.55  # §0.7.3: RI≥0.55 才形成推断

        result = {
            "inference_formed": inference_formed,
            "ri": ri,
            "cbr_boost": action["cbr_boost"],
            "ess_temp_mult": action["ess_temp_mult"],
            "ess_dir": obs.get("ess_top_direction", ""),
            "auto_execute": False,
            "lark_notification": False,
        }

        if self.mode == "MVP" and ri >= 0.75:
            result["lark_notification"] = True
        elif self.mode == "Phase2" and inference_formed:
            result["auto_execute"] = True

        return result

    def experiment(
        self,
        r_vector: dict[str, Any],
        hyp: dict[str, Any],
        symbol: str,
        ess_id: str,
        cbr_sim: float,
        cluster_id: str,
    ) -> dict[str, Any]:
        """步骤③ 实验: Level0 d* + 对齐 → 小仓 u=0.1 + snapshot"""
        try:
            d_star_result = self._compute_d_star(r_vector)
            d_star = d_star_result["d_star"]
            ess_dir = str(hyp.get("ess_dir", "")).lower()

            # 对齐检查 (§1.5.5)
            aligned = (d_star.lower() == ess_dir) and d_star in ("long", "short")

            if aligned and hyp.get("inference_formed"):
                u_open = 0.1  # §1.7.6 硬上限
                action = d_star.lower()
            else:
                u_open = 0.0
                action = "WAIT"

            snapshot = self.reflection.create_snapshot(
                symbol=symbol, u_open=u_open, action=action,
                level0_dstar=d_star, ess_id=ess_id, ess_dir=ess_dir,
                cbr_sim=cbr_sim, cbr_top1_outcome="TP", cluster_id=cluster_id,
            )

            return {
                "action": action,
                "u_open": u_open,
                "d_star": d_star,
                "aligned": aligned,
                "pre_trade_snapshot": snapshot,
            }
        except Exception as e:
            logger.warning("[FO] experiment fail: %s", e)
            snap = self.reflection.create_snapshot(
                symbol=symbol, u_open=0.0, action="WAIT",
                level0_dstar="WAIT", ess_id=ess_id, ess_dir="",
                cbr_sim=cbr_sim, cbr_top1_outcome="", cluster_id=cluster_id,
            )
            return {"action": "WAIT", "u_open": 0.0, "pre_trade_snapshot": snap,
                    "aligned": False, "d_star": "WAIT"}

    def measure(
        self,
        exp: dict[str, Any],
        outcome_direction: str,
        outcome_result: str,
    ) -> dict[str, Any]:
        """步骤④ 测量: 模拟交易结算 TP/SL"""
        return {
            "real_direction": outcome_direction.lower(),
            "real_outcome": outcome_result.upper(),
            "u_open": exp.get("u_open", 0.0),
        }

    def reflect(
        self,
        snapshot: dict[str, Any],
        measure: dict[str, Any],
    ) -> dict[str, Any]:
        """步骤⑤ 反思: CS 一致性 + 四维奖惩"""
        cs = self.reflection.calculate_cs(snapshot, measure)
        reward = self.reflection.apply_reward(
            cs=cs,
            outcome=measure.get("real_outcome", ""),
            cluster_id=snapshot.get("cluster_id", ""),
            ess_id=snapshot.get("ess_id", ""),
            gmax=1.0,
        )
        return {"cs": cs, **reward}

    def learn(self, refl: dict[str, Any]) -> dict[str, Any]:
        """步骤⑥ 学习: ESS delta + gmax 更新"""
        return {
            "ess_delta": refl.get("ess_delta", 0.0),
            "gmax_mult": refl.get("gmax_mult", 1.0),
            "cluster_weight_mult": refl.get("cluster_weight_mult", 1.0),
            "anti_pattern_flag": refl.get("anti_pattern_flag", False),
        }

    def feedback(self, learned: dict[str, Any]) -> dict[str, Any]:
        """步骤⑦ 回馈: 更新后 ESS → RippleEngine 下一轮检测"""
        return {
            "ess_delta": learned.get("ess_delta", 0.0),
            "updated_ess_direction": "updated" if learned.get("ess_delta", 0) != 0 else "unchanged",
            "gmax_updated": learned.get("gmax_mult", 1.0) != 1.0,
            "anti_pattern": learned.get("anti_pattern_flag", False),
        }
