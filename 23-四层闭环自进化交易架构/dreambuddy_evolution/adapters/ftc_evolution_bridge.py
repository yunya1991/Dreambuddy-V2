"""
ftc_evolution_bridge — FTC 进化闭环桥接器

职责:
  1. 盈亏 → ReflectionEngine.apply_reward → ess_delta, gmax_mult
     → 回灌到 FTC orchestrator (更新 FTC ESS + gmax + ε)
  2. 涟漪信号 → FTC 候选生成
  3. 反思洞察 → FTC 候选生成
  4. L2 基因创新: 异常检测 → 新基因候选 → 验证 → 写入基因组

这是 FTC 系统与现有进化闭环的集成层，不修改 core/engines/ 代码。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .ftc_schema import FTC, FTCStep, gen_ftc_id, gen_step_id
from .ftc_orchestrator import FTCOrchestrator
from .ftc_gene_innovation import GeneInnovationEngine

logger = logging.getLogger(__name__)


class FTCEvolutionBridge:
    """FTC 进化闭环桥接器"""

    def __init__(
        self,
        orchestrator: FTCOrchestrator,
        gene_innovation: Optional[GeneInnovationEngine] = None,
        reflection_engine: Optional[Any] = None,
        gene_root: Optional[str] = None,
    ):
        self._orch = orchestrator
        self._gene_innovation = gene_innovation or GeneInnovationEngine(gene_root)
        self._reflection = reflection_engine
        # gmax 用于组合变异，初始 0.3
        self._gmax = 0.3

    # ─── 1. 盈亏回灌: ReflectionEngine → FTC ────────────────────

    def on_trade_settlement(
        self,
        ftc_id: str,
        confidence_score: float,
        outcome: str,
        pnl_pct: float,
    ) -> dict[str, Any]:
        """
        交易结算后调用，通过 ReflectionEngine 计算奖惩并回灌 FTC。

        Args:
            ftc_id: 触发该交易的 FTC ID
            confidence_score: CS 信心分（方向判断准确度）
            outcome: "TP" (止盈) 或 "SL" (止损)
            pnl_pct: 盈亏百分比

        Returns:
            {ess_delta, gmax_mult, ftc_ess_before, ftc_ess_after, epsilon}
        """
        ftc = self._orch.get_ftc(ftc_id)
        if not ftc:
            return {}

        ess_before = ftc.ess or 0.0

        # 通过 ReflectionEngine 计算奖惩（如果有）
        ess_delta = 0.0
        gmax_mult = 1.0

        if self._reflection is not None:
            try:
                reward = self._reflection.apply_reward(
                    cs=confidence_score,
                    outcome=outcome,
                    cluster_id=ftc_id,
                    ess_id=ftc_id,
                    gmax=self._gmax,
                )
                ess_delta = reward.get("ess_delta", 0.0)
                gmax_mult = reward.get("gmax_mult", 1.0)
            except Exception as e:
                logger.warning(f"[FO] reflection apply_reward failed: {e}")
                # 降级: 直接用 pnl 更新
                ess_delta = 0.02 if pnl_pct > 0 else -0.05
                gmax_mult = 1.2 if pnl_pct > 0 else 0.5
        else:
            # 无 ReflectionEngine 时降级处理
            if confidence_score >= 0.7 and pnl_pct > 0:
                ess_delta = 0.02
            elif confidence_score <= -0.2 and pnl_pct < 0:
                ess_delta = -0.05
                gmax_mult = 0.5
            elif confidence_score >= 0.7 and pnl_pct < 0:
                gmax_mult = 1.2  # 假失败，增加探索

        # 回灌 FTC ESS
        new_ess = max(0.0, min(1.0, ess_before + ess_delta))
        ftc.ess = new_ess

        # 回灌 gmax（用于后续组合变异）
        self._gmax = max(0.1, min(0.5, self._gmax * gmax_mult))

        # 更新 ε 探索因子
        self._orch.update_epsilon_on_trade(confidence_score, pnl_pct)

        logger.info(
            f"[FTC-Bridge] {ftc_id}: CS={confidence_score:.2f} {outcome} "
            f"ESS {ess_before:.3f}→{new_ess:.3f} (Δ={ess_delta:+.3f}) "
            f"gmax={self._gmax:.3f} ε={self._orch.epsilon:.3f}"
        )

        return {
            "ess_delta": ess_delta,
            "gmax_mult": gmax_mult,
            "ftc_ess_before": round(ess_before, 4),
            "ftc_ess_after": round(new_ess, 4),
            "gmax": round(self._gmax, 4),
            "epsilon": round(self._orch.epsilon, 4),
        }

    @property
    def gmax(self) -> float:
        return self._gmax

    # ─── 2. 涟漪信号 → FTC 候选 ─────────────────────────────────

    def generate_ftc_from_ripple(self, ripple_signals: list[dict]) -> list[FTC]:
        """
        从涟漪系统信号生成 FTC 候选。

        每个信号被包装为一个简易 FTC:
          condition: 信号对应的 condition 基因
          inference: 信号描述
          action: 信号方向
        """
        new_ftcs: list[FTC] = []

        for sig in ripple_signals:
            try:
                direction = sig.get("direction", "long")
                strength = float(sig.get("strength", 0))
                vol_ratio = float(sig.get("vol_ratio", 1.0))

                # 根据信号特征构建 condition
                conditions = []
                if vol_ratio >= 1.3:
                    conditions.append(FTCStep(
                        step_id=gen_step_id(),
                        type="condition",
                        description=f"放量 vol_ratio={vol_ratio:.2f}",
                        gene_ref="CD-VOL-SURGE",
                        data_required=["vol_5", "vol_20", "vol_ratio"],
                        threshold=1.3,
                    ))
                if strength >= 0.5:
                    conditions.append(FTCStep(
                        step_id=gen_step_id(),
                        type="condition",
                        description=f"信号强度={strength:.2f}",
                        gene_ref="CD-CAPITAL-INFLOW",
                        data_required=["capital_flow"],
                        threshold=0.5,
                        depends_on=[conditions[-1].step_id] if conditions else [],
                    ))

                if not conditions:
                    continue

                action_gene = "AC-LONG" if direction == "long" else "AC-SHORT"
                steps = conditions + [
                    FTCStep(
                        step_id=gen_step_id(),
                        type="inference",
                        description=f"涟漪信号: {sig.get('symbol', '')} {direction}",
                        logic="外研系统检测到的市场信号",
                        depends_on=[conditions[-1].step_id],
                    ),
                    FTCStep(
                        step_id=gen_step_id(),
                        type="action",
                        description=f"{direction} (涟漪信号)",
                        gene_ref=action_gene,
                        depends_on=[conditions[-1].step_id],
                    ),
                ]

                ftc = FTC(
                    ftc_id=gen_ftc_id("FTC-RIPPLE"),
                    name=f"涟漪-{sig.get('symbol', 'unknown')}",
                    steps=steps,
                    source="ripple",
                )
                new_ftcs.append(ftc)
            except Exception as e:
                logger.warning(f"[FO] ripple→FTC failed: {e}")
                continue

        # 注册到 orchestrator
        for ftc in new_ftcs:
            from .ftc_similarity import align_to_anchors, get_track_by_similarity
            ftc.knowledge_alignment = align_to_anchors(ftc, top_k=3)
            ftc.track = get_track_by_similarity(ftc.max_similarity)
            self._orch._ftcs[ftc.ftc_id] = ftc

        logger.info(f"[FTC-Bridge] 涟漪信号生成 {len(new_ftcs)} 条 FTC 候选")
        return new_ftcs

    # ─── 3. 反思洞察 → FTC 候选 ─────────────────────────────────

    def generate_ftc_from_reflection(self, insights: list[dict]) -> list[FTC]:
        """
        从反思引擎洞察生成 FTC 候选。

        洞察格式: {pattern, suggested_condition, suggested_action}
        """
        new_ftcs: list[FTC] = []

        for insight in insights:
            try:
                pattern = insight.get("pattern", "")
                cond_gene = insight.get("suggested_condition", "CD-CAPITAL-INFLOW")
                act_gene = insight.get("suggested_action", "AC-LONG")

                steps = [
                    FTCStep(
                        step_id=gen_step_id(),
                        type="condition",
                        description=f"反思模式: {pattern}",
                        gene_ref=cond_gene,
                        data_required=["capital_flow", "vol_ratio"],
                    ),
                    FTCStep(
                        step_id=gen_step_id(),
                        type="inference",
                        description=f"内省洞察: {pattern}",
                        logic="复盘反思得出的因果推理",
                        depends_on=[],
                    ),
                    FTCStep(
                        step_id=gen_step_id(),
                        type="action",
                        description=f"反思建议: {act_gene}",
                        gene_ref=act_gene,
                        depends_on=[],
                    ),
                ]

                ftc = FTC(
                    ftc_id=gen_ftc_id("FTC-REFLECT"),
                    name=f"反思-{pattern[:20]}",
                    steps=steps,
                    source="reflection",
                )
                new_ftcs.append(ftc)
            except Exception as e:
                logger.warning(f"[FO] reflection→FTC failed: {e}")
                continue

        for ftc in new_ftcs:
            from .ftc_similarity import align_to_anchors, get_track_by_similarity
            ftc.knowledge_alignment = align_to_anchors(ftc, top_k=3)
            ftc.track = get_track_by_similarity(ftc.max_similarity)
            self._orch._ftcs[ftc.ftc_id] = ftc

        logger.info(f"[FTC-Bridge] 反思洞察生成 {len(new_ftcs)} 条 FTC 候选")
        return new_ftcs

    # ─── 4. L2 基因创新全流程 ───────────────────────────────────

    def run_gene_innovation(
        self,
        ripple_signals: list[dict] | None = None,
        reflection_insights: list[dict] | None = None,
        ftc_ess_convergence: bool = False,
    ) -> dict[str, Any]:
        """
        运行 L2 基因创新完整流程:
          1. 检测异常 → 生成候选
          2. 探索轨道验证（回测）
          3. 通过门槛 → 写入基因组

        Returns:
            {candidates: [...], validated: [...], written: [...]}
        """
        # 1. 检测异常
        candidates = self._gene_innovation.detect_anomalies(
            ripple_signals=ripple_signals,
            reflection_insights=reflection_insights,
            ftc_ess_convergence=ftc_ess_convergence,
        )

        validated = []
        written = []

        for cand in candidates:
            # 2. 探索轨道验证: 构建一个包含该基因的简易 FTC，跑回测
            test_ftc = self._build_validation_ftc(cand)
            result = self._orch.run_backtest_one(test_ftc.ftc_id) if test_ftc else None

            if result:
                n_samples = result.get("N", 0)
                ess = result.get("ess", 0.0)
                passed = self._gene_innovation.validate_candidate(cand.gene_id, n_samples, ess)
                if passed:
                    validated.append(cand.gene_id)
                    # 3. 写入基因组
                    if self._gene_innovation.write_gene_to_library(cand):
                        written.append(cand.gene_id)

        logger.info(
            f"[L2-Gene] 创新流程: 候选={len(candidates)} "
            f"验证通过={len(validated)} 写入基因组={len(written)}"
        )

        return {
            "candidates": [c.gene_id for c in candidates],
            "validated": validated,
            "written": written,
        }

    def _build_validation_ftc(self, candidate) -> Optional[FTC]:
        """为基因候选构建验证用 FTC"""
        try:
            steps = [
                FTCStep(
                    step_id=gen_step_id(),
                    type="condition",
                    description=candidate.description,
                    gene_ref=candidate.gene_id,
                    data_required=["vol_ratio", "capital_flow", "oi_change_pct"],
                ),
                FTCStep(
                    step_id=gen_step_id(),
                    type="inference",
                    description=f"L2 创新基因验证: {candidate.gene_id}",
                    logic=candidate.expression,
                    depends_on=[],
                ),
                FTCStep(
                    step_id=gen_step_id(),
                    type="action",
                    description="验证方向",
                    gene_ref="AC-LONG",
                    depends_on=[],
                ),
            ]
            ftc = FTC(
                ftc_id=gen_ftc_id("FTC-L2-VAL"),
                name=f"L2验证-{candidate.gene_id}",
                steps=steps,
                source="mutation",
            )
            self._orch._ftcs[ftc.ftc_id] = ftc
            return ftc
        except Exception:
            return None
