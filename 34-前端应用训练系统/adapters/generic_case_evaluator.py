"""通用案例评估器适配器。

不复用 CaseIngestGate（交易域专用，依赖 pnl_pct/rsi14 等），
而是新实现通用四维评估：novelty/significance/anomaly/reproducibility。

设计:
  - novelty: TDR retrieve 无相似 → 1.0（与历史案例差异度）
  - significance: learned 非空 + outcome=success → 0.7（SPEC完成度+验收等级）
  - anomaly: quality=C 或 outcome=failure → 0.6（是否有红旗/异常）
  - reproducibility: 相似案例数 / 10（验收证据是否完整）
  - 决策: overall ≥ 0.5 → INGEST; ≥ 0.3 → DEFERRED; else SKIP
  - FAIL-OPEN：TDR 不可用时 novelty=0.5（中性）
"""
import os
import sys
import json
from typing import Dict, Any

# sys.path 注入
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)
_SCRIPTS_DIR = os.path.join(_PROJECT_ROOT, "scripts")

for _p in [_THIS_DIR, _34_DIR, _SCRIPTS_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from interfaces.case_evaluator import CaseEvaluator, CaseEvaluation, IngestDecision


class GenericCaseEvaluator(CaseEvaluator):
    """通用案例评估器。

    四维评估案例的学习价值，决策是否入库/暂缓/跳过。
    不依赖交易域特定指标（pnl/rsi/volume），适用于通用工程案例。
    """

    def __init__(self):
        self._tdr_retrieve = None

    def _get_tdr_retrieve(self):
        """延迟获取 TDR retrieve 函数。"""
        if self._tdr_retrieve is None:
            try:
                from case_bank_server import retrieve_cases
                self._tdr_retrieve = retrieve_cases
            except Exception:
                self._tdr_retrieve = None
        return self._tdr_retrieve

    def evaluate(self, case: Dict[str, Any]) -> CaseEvaluation:
        """评估案例的学习价值。

        Args:
            case: 案例数据（含 intent/actions/outcome/learned/quality 等）

        Returns:
            CaseEvaluation（决策 + 四维评分 + 原因）
        """
        novelty = self._assess_novelty(case)
        significance = self._assess_significance(case)
        anomaly = self._assess_anomaly(case)
        reproducibility = self._assess_reproducibility(case)

        overall = (novelty + significance + anomaly + reproducibility) / 4.0

        if overall >= 0.5:
            decision = IngestDecision.INGEST
            reason = f"overall={overall:.2f} >= 0.5, ingest for training"
        elif overall >= 0.3:
            decision = IngestDecision.DEFERRED
            reason = f"overall={overall:.2f} >= 0.3, deferred for later"
        else:
            decision = IngestDecision.SKIP
            reason = f"overall={overall:.2f} < 0.3, skip (low training value)"

        return CaseEvaluation(
            decision=decision,
            novelty=novelty,
            significance=significance,
            anomaly=anomaly,
            reproducibility=reproducibility,
            reason=reason,
        )

    def _assess_novelty(self, case: Dict[str, Any]) -> float:
        """新颖性：TDR 中无相似案例 → 1.0。

        通过 TDR retrieve 查询相似案例，越少相似 → 越新颖。
        """
        intent = case.get("intent", "")
        if not intent:
            return 0.3

        retrieve = self._get_tdr_retrieve()
        if retrieve is None:
            return 0.5  # FAIL-OPEN：TDR 不可用时中性

        try:
            result = retrieve(query=intent, top_k=5)
            if not result.get("ok"):
                return 0.5

            scores = result.get("scores", [])
            if not scores:
                return 1.0  # 无相似案例 → 完全新颖

            max_score = max(scores)
            # 相似度越低 → 新颖性越高
            return max(0.0, 1.0 - max_score)
        except Exception:
            return 0.5

    def _assess_significance(self, case: Dict[str, Any]) -> float:
        """重要性：learned 非空 + outcome=success → 高分。"""
        learned = case.get("learned", [])
        outcome = case.get("outcome", "unknown")

        score = 0.0
        if learned:
            score += 0.4
        if outcome == "success":
            score += 0.3
        elif outcome == "partial":
            score += 0.15

        # 验收等级（如有）
        acceptance_level = case.get("acceptance_level", "")
        if acceptance_level in ("full", "conditional"):
            score += 0.3

        return min(score, 1.0)

    def _assess_anomaly(self, case: Dict[str, Any]) -> float:
        """异常性：quality=C 或 outcome=failure → 高分（有学习价值）。"""
        quality = case.get("quality", "C")
        outcome = case.get("outcome", "unknown")

        score = 0.0
        # 低质量案例有更多学习空间
        if quality == "C":
            score += 0.4
        elif quality == "B":
            score += 0.2

        # 失败案例有反模式学习价值
        if outcome == "failure":
            score += 0.3
        elif outcome == "partial":
            score += 0.15

        # 有 known_gaps 也增加学习价值
        known_gaps = case.get("known_gaps", [])
        if known_gaps:
            score += 0.3

        return min(score, 1.0)

    def _assess_reproducibility(self, case: Dict[str, Any]) -> float:
        """可复现性：有验收证据 + learned → 高分。"""
        score = 0.0

        learned = case.get("learned", [])
        if learned:
            score += 0.3

        actions = case.get("actions", [])
        if actions:
            score += 0.2

        # 验收证据
        acceptance_evidence = case.get("acceptance_evidence", {})
        if acceptance_evidence:
            score += 0.3

        # 代码路径
        code_path = case.get("code_path", "")
        if code_path:
            score += 0.2

        return min(score, 1.0)
