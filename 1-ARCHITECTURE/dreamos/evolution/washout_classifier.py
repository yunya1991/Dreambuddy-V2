"""WashoutClassifier — 洗盘/真弱势 KNN/CBR + 贝叶斯分类器 (自进化侧).

Spec: docs/superpowers/specs/2026-09-21-washout-detector-design.md §5.4

W4 阶段落地 (纯新增, 零回归):
  - KNN/CBR 检索 top-k 相似历史案例
  - 贝叶斯后验 P(washout | neighbors)
  - 闭环自进化: predict → 交易 → record_case → 案例库增长 → predict 置信度提升
  - evolve() 复用 EvolutionEngine._sandbox_validate 沙箱验证

设计原则 (硬约束):
  - HC-2: KNN/CBR + 贝叶斯闭环 (禁用 LLM, 本文件无 LLM 依赖)
  - 案例库 >= min_cases (默认 30) 才走 KNN, 否则降级规则 (§5.4)
  - reward = tanh(pnl_pct / 0.02) 归一化 [-1, 1] (BayesianUpdater.compute_reward)
  - 复用 EvolutionEngine._sandbox_validate 沙箱验证 (延迟注入, 不硬依赖)
  - FAIL-OPEN: 异常 → WashoutVerdict.unknown(), 不抛错不阻塞

判定阈值 (§5.4):
  - posterior > 0.65 → WASHOUT (高置信度洗盘 → 持有)
  - posterior < 0.35 → WEAKNESS (高置信度真弱势 → 加速离场)
  - 0.35 ≤ posterior ≤ 0.65 → UNKNOWN (中等置信度 → 维持现状)
"""
from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from typing import Dict, Optional

from .washout_case_library import WashoutCase, WashoutCaseLibrary
from .washout_bayesian_updater import BayesianUpdater
from .exploration_policy import ExplorationPolicy

__all__ = ["WashoutClassifier"]

logger = logging.getLogger(__name__)


# 判定阈值 (§5.4)
_WASHOUT_THRESHOLD_HIGH = 0.65  # posterior > 0.65 → WASHOUT
_WEAKNESS_THRESHOLD_LOW = 0.35  # posterior < 0.35 → WEAKNESS


class WashoutClassifier:
    """洗盘/真弱势 KNN/CBR + 贝叶斯分类器 (自进化侧).

    禁用 LLM, 倾向深度学习; 复用 EvolutionEngine._sandbox_validate 沙箱验证.

    用法:
        lib = WashoutCaseLibrary()
        clf = WashoutClassifier(case_library=lib, k_neighbors=5, min_cases=30)
        verdict = clf.predict(features)
        clf.record_case(closed_case)  # 闭环后入库
    """

    def __init__(
        self,
        case_library: WashoutCaseLibrary,
        k_neighbors: int = 5,
        min_cases: int = 30,
        bayesian_updater: Optional[BayesianUpdater] = None,
        sandbox_validate_fn: Optional[callable] = None,
        exploration_policy: Optional[ExplorationPolicy] = None,
    ):
        """初始化分类器.

        Args:
            case_library: 案例库 (WashoutCaseLibrary)
            k_neighbors: KNN 邻居数 (默认 5)
            min_cases: 案例库 < min_cases 时降级规则化判定 (默认 30)
            bayesian_updater: 贝叶斯更新器 (None=默认 Beta(1,1))
            sandbox_validate_fn: 沙箱验证函数 (复用 EvolutionEngine._sandbox_validate)
            exploration_policy: 探索策略 (None=默认 ExplorationPolicy)
        """
        self.case_library = case_library
        self.k_neighbors = max(1, int(k_neighbors))
        self.min_cases = max(1, int(min_cases))
        self.bayesian_updater = bayesian_updater if bayesian_updater is not None else BayesianUpdater()
        self.sandbox_validate_fn = sandbox_validate_fn
        self.exploration_policy = exploration_policy if exploration_policy is not None else ExplorationPolicy()

    # ============================================================
    # 主入口: KNN 检索 + 贝叶斯后验
    # ============================================================
    def predict(self, features: Dict[str, float]):
        """KNN 检索 + 贝叶斯后验 → WashoutVerdict.

        Args:
            features: 特征快照 (12+1 维 F1-F13)

        Returns:
            WashoutVerdict (from bcrm2.washout_detector)

        判定逻辑:
            1. 案例库 < min_cases → 降级规则 (W1-W3 路径)
            2. KNN 检索 top-k 相似案例
            3. 贝叶斯后验 P(washout | neighbors)
            4. posterior > 0.65 → WASHOUT
               posterior < 0.35 → WEAKNESS
               否则 → UNKNOWN

        FAIL-OPEN:
            异常 → WashoutVerdict.unknown(), 不抛错.
        """
        try:
            from scripts.memory_l4.bcrm2.washout_detector import (
                WashoutLabel,
                WashoutVerdict,
            )
        except ImportError:
            # 延迟 import 失败 (sys.path 未配置 bcrm2) → FAIL-OPEN
            return _safe_unknown()

        try:
            # Step 0: 案例库不足 → 降级规则
            if len(self.case_library) < self.min_cases:
                return self._fallback_rule(features, WashoutVerdict, WashoutLabel)

            # Step 1: KNN 检索 top-k 相似案例
            neighbors = self.case_library.knn_search(
                features, k=self.k_neighbors
            )
            if not neighbors:
                return self._fallback_rule(features, WashoutVerdict, WashoutLabel)

            # Step 2: 统计 washout / weakness 邻居数 + reward 回流
            washout_count = sum(
                1 for _, case in neighbors if case.actual_label == "washout"
            )
            weakness_count = sum(
                1 for _, case in neighbors if case.actual_label == "weakness"
            )

            # 阶段2: reward 回流 — 计算邻居平均 reward
            avg_reward = 0.0
            if neighbors:
                total_reward = sum(case.reward for _, case in neighbors)
                avg_reward = total_reward / len(neighbors)

            # Step 3: 贝叶斯后验 P(washout | neighbors, reward)
            posterior = self.bayesian_updater.update_with_reward(
                washout_count=washout_count,
                weakness_count=weakness_count,
                avg_reward=avg_reward,
            )

            # Step 4: 动态阈值 (基于 ExplorationPolicy 退火)
            case_count = len(self.case_library)
            washout_threshold = self.exploration_policy.get_washout_threshold(case_count)
            weakness_threshold = self.exploration_policy.get_weakness_threshold(case_count)

            if posterior > washout_threshold:
                label = WashoutLabel.WASHOUT
                confidence = posterior
            elif posterior < weakness_threshold:
                label = WashoutLabel.WEAKNESS
                confidence = 1.0 - posterior
            else:
                label = WashoutLabel.UNKNOWN
                confidence = 1.0 - abs(posterior - 0.5) * 2.0  # 中位置信度低

            return WashoutVerdict(
                label=label,
                confidence=confidence,
                trigger_activated=True,
                feature_snapshot=dict(features) if features else {},
                reason=(
                    f"knn_bayesian_k={self.k_neighbors}_n={len(neighbors)}"
                    f"_w={washout_count}_s={weakness_count}_post={posterior:.3f}"
                    f"_rw={avg_reward:.3f}"
                ),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(
                "WashoutClassifier.predict FAIL-OPEN err=%s\n%s", e, tb
            )
            return _safe_unknown()

    # ============================================================
    # 降级规则: 案例库不足时走规则化判定 (W1-W3 等价路径)
    # ============================================================
    def _fallback_rule(self, features: Dict[str, float], WashoutVerdict, WashoutLabel):
        """案例库 < min_cases → 降级为规则化判定.

        冷启动 (exploration 开启 + case_count<30): confidence=0.40, 让 probe 仓能触发.
        开关关断: confidence=0.0, 字节等价.
        """
        case_count = len(self.case_library)
        if self.exploration_policy.is_cold_start(case_count):
            confidence = 0.40
            mode = self.exploration_policy.get_exploration_mode(case_count)
            reason = f"fallback_cold_start_n={case_count}_mode={mode}"
        else:
            confidence = 0.0
            reason = f"fallback_insufficient_cases_n={case_count}_min={self.min_cases}"

        return WashoutVerdict(
            label=WashoutLabel.UNKNOWN,
            confidence=confidence,
            trigger_activated=True,
            feature_snapshot=dict(features) if features else {},
            reason=reason,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    # ============================================================
    # 闭环后案例入库 (自进化训练)
    # ============================================================
    def record_case(self, case: WashoutCase) -> None:
        """闭环后记录案例 (用于自进化训练).

        Args:
            case: WashoutCase 闭环案例
        """
        try:
            self.case_library.add(case)
        except Exception as e:
            logger.warning("WashoutClassifier.record_case FAIL-OPEN: %s", e)

    # ============================================================
    # 自进化: 复用 _sandbox_validate 沙箱验证
    # ============================================================
    def evolve(
        self,
        proposal: Optional[Dict] = None,
    ) -> Dict:
        """复用 EvolutionEngine._sandbox_validate 进行自进化验证.

        Args:
            proposal: 编排调整提案 (含 scenario_id/new_pattern/nodes/score)
                      None=使用默认提案

        Returns:
            {"accepted": bool, "score": float, "baseline_score": float, "reason": str}

        设计:
            - sandbox_validate_fn 注入 (复用 EvolutionEngine._sandbox_validate)
            - 无注入 → accepted=False, reason="no_sandbox"
            - 验证通过 → accepted=True, 升级权重
            - 验证未通过 → accepted=False, 保守拒绝

        FAIL-OPEN:
            异常 → accepted=False, 不抛错.
        """
        try:
            if self.sandbox_validate_fn is None:
                return {
                    "accepted": False,
                    "score": 0.0,
                    "baseline_score": 0.0,
                    "reason": "no_sandbox_validate_fn",
                }

            # 默认提案 (washout 场景)
            if proposal is None:
                proposal = {
                    "scenario_id": "washout_default",
                    "new_pattern": "knn_bayesian",
                    "nodes": ["WashoutClassifier"],
                    "score": 0.5,
                }

            # 调用沙箱验证 (复用 EvolutionEngine._sandbox_validate)
            accepted = bool(self.sandbox_validate_fn(proposal))

            return {
                "accepted": accepted,
                "score": float(proposal.get("score", 0.0)),
                "baseline_score": float(proposal.get("baseline_score", 0.0)),
                "reason": "sandbox_passed" if accepted else "sandbox_rejected",
            }
        except Exception as e:
            logger.warning("WashoutClassifier.evolve FAIL-OPEN: %s", e)
            return {
                "accepted": False,
                "score": 0.0,
                "baseline_score": 0.0,
                "reason": f"exception:{type(e).__name__}",
            }


# ============================================================
# FAIL-OPEN 兜底 (延迟 import 失败时)
# ============================================================
def _safe_unknown():
    """延迟 import 失败时的 FAIL-OPEN 兜底.

    构造一个最小 WashoutVerdict.unknown() 等价对象.
    但因为无法 import WashoutVerdict, 返回 None 让上层处理.
    实际上 predict() 调用方应能处理 None, 或上层 ensure sys.path 正确.
    """
    # 尝试多种 import 路径
    for _module_path in (
        "scripts.memory_l4.bcrm2.washout_detector",
        "bcrm2.washout_detector",
    ):
        try:
            mod = __import__(_module_path, fromlist=["WashoutVerdict"])
            return mod.WashoutVerdict.unknown()
        except ImportError:
            continue
    # 所有路径都失败 → 返回 None (上层应处理)
    logger.error("WashoutClassifier: 无法 import WashoutVerdict, 返回 None")
    return None
