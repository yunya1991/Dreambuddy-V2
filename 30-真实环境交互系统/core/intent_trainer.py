"""IntentTrainer — 30 系统内训练适配器（HC-1a 合规）

替代 spec §3.4 的"扩展 DynamicRecognizer"方案（SD-1）。
- bayesian_memory_updater.py 不存在（SD-2）：本模块内实现 Beta 分布贝叶斯更新
- OrchestrationMemory.update_mapping 不存在（SD-3）：本模块维护 orchestration_mapping.json
- RuleBasedRecognizer.add_rule 不存在（SD-4）：本模块维护 rules.json，不污染 dreamos

3 步训练动作（对齐 SPEC-20260929 §2.1）：
1. update_weights: 贝叶斯后验更新（Beta 分布）
2. distill_to_rules: 高频模式蒸馏（零 Token 规则）
3. refine_orchestration: 场景→链路映射精确化（L3→L0）
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("real_env.intent_trainer")


def _bucket_key_str(bucket_key: Tuple[str, str]) -> str:
    """JSON 键用 | 分隔（避免 tuple 序列化问题）"""
    return f"{bucket_key[0]}|{bucket_key[1]}"


class IntentTrainer:
    """训练逻辑在 30 系统内（HC-1a 合规）"""

    # spec §4.2: 三大思维链 → 编排模式映射
    CHAIN_PATTERN = {
        "trend_following": "c_chain",
        "mean_reversion": "c_chain",
        "breakout": "c_chain",
    }
    DEFAULT_NODES = ["C1", "C2", "C3", "A2", "A4", "A5", "A9"]

    def __init__(
        self,
        weights_path: Path = None,
        rules_path: Path = None,
        orch_path: Path = None,
        distill_accuracy_target: float = 0.85,
    ):
        self._weights_path = Path(weights_path) if weights_path else Path("30-真实环境交互系统/training/weights.json")
        self._rules_path = Path(rules_path) if rules_path else Path("30-真实环境交互系统/training/rules.json")
        self._orch_path = Path(orch_path) if orch_path else Path("30-真实环境交互系统/training/orchestration_mapping.json")
        self._distill_accuracy_target = distill_accuracy_target
        for p in [self._weights_path, self._rules_path, self._orch_path]:
            p.parent.mkdir(parents=True, exist_ok=True)

    # ── Step 1: 贝叶斯后验更新 ──────────────────────────
    def update_weights(self, bucket_key: Tuple[str, str], samples: List) -> None:
        """贝叶斯后验更新（Beta 分布：alpha += correct, beta += wrong）

        简化版贝叶斯（spec §3.4 提到的 bayesian_memory_updater.py 不存在，SD-2）
        """
        weights = self.load_weights()
        key = _bucket_key_str(bucket_key)
        prior = weights.get(key, {"alpha": 1.0, "beta": 1.0, "sample_count": 0})
        correct = sum(1 for s in samples if s.human_label.get("confirmed"))
        wrong = len(samples) - correct
        prior["alpha"] += correct
        prior["beta"] += wrong
        prior["sample_count"] = prior.get("sample_count", 0) + len(samples)
        # 后验均值（Beta 分布均值 = alpha/(alpha+beta)）
        prior["posterior_mean"] = prior["alpha"] / (prior["alpha"] + prior["beta"])
        weights[key] = prior
        self._save_weights(weights)
        logger.info("贝叶斯更新 %s: alpha=%s beta=%s mean=%.3f",
                    key, prior["alpha"], prior["beta"], prior["posterior_mean"])

    # ── Step 2: 规则蒸馏 ────────────────────────────────
    def distill_to_rules(self, bucket_key: Tuple[str, str], samples: List) -> bool:
        """高频模式蒸馏为零 Token 规则

        触发条件：准确率 ≥ distill_accuracy_target
        Returns: True 蒸馏成功，False 不蒸馏
        """
        accuracy = self._compute_accuracy(samples)
        if accuracy < self._distill_accuracy_target:
            logger.info("桶 %s 准确率 %.2f < %.2f，不蒸馏",
                        bucket_key, accuracy, self._distill_accuracy_target)
            return False

        common = self._extract_common_features(samples)
        rules = self.load_rules()
        rules[_bucket_key_str(bucket_key)] = common
        self._save_rules(rules)
        logger.info("桶 %s 蒸馏规则成功（准确率 %.2f）", bucket_key, accuracy)
        return True

    # ── Step 3: 编排映射精确化 ──────────────────────────
    def refine_orchestration(self, bucket_key: Tuple[str, str], samples: List) -> None:
        """场景→链路映射精确化（L3→L0）

        对齐 spec §4.2：TREND_FOLLOWING/MEAN_REVERSION/BREAKOUT → C 链
        """
        gold_intent = bucket_key[0]
        pattern = self.CHAIN_PATTERN.get(gold_intent, "c_chain")
        accuracy = self._compute_accuracy(samples)

        mapping = self.load_orchestration_mapping()
        mapping[_bucket_key_str(bucket_key)] = {
            "pattern": pattern,
            "nodes": list(self.DEFAULT_NODES),
            "score": accuracy,
            "confidence": "high" if accuracy >= 0.85 else "medium",
            "fallback_level": "L0",
            "source_scenario": bucket_key[1],
        }
        self._save_orchestration(mapping)
        logger.info("编排映射 %s → %s (L0)", bucket_key, pattern)

    # ── 持久化辅助 ──────────────────────────────────────
    def load_weights(self) -> Dict[str, Any]:
        if self._weights_path.exists():
            with open(self._weights_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_weights(self, weights: Dict) -> None:
        with open(self._weights_path, "w", encoding="utf-8") as f:
            json.dump(weights, f, ensure_ascii=False, indent=2)

    def load_rules(self) -> Dict[str, Any]:
        if self._rules_path.exists():
            with open(self._rules_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_rules(self, rules: Dict) -> None:
        with open(self._rules_path, "w", encoding="utf-8") as f:
            json.dump(rules, f, ensure_ascii=False, indent=2)

    def load_orchestration_mapping(self) -> Dict[str, Any]:
        if self._orch_path.exists():
            with open(self._orch_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_orchestration(self, mapping: Dict) -> None:
        with open(self._orch_path, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)

    # ── 统计辅助 ────────────────────────────────────────
    @staticmethod
    def _compute_accuracy(samples: List) -> float:
        if not samples:
            return 0.0
        correct = sum(1 for s in samples if s.human_label.get("confirmed"))
        return correct / len(samples)

    @staticmethod
    def _extract_common_features(samples: List) -> Dict[str, Any]:
        """从样本中提取共同特征（取首个样本 market_features 作为基础）"""
        if not samples:
            return {}
        return dict(samples[0].input.get("market_features", {}))
