"""意图识别 eval 回归门

对齐 spec §3.5。跑 eval 集验证训练后准确率/波动/零 Token 占比/路由命中率。

v2 优化（对齐行业标准 LUIS/Watson/Rasa DIET）：
- 增加 Precision/Recall/F1 (macro) 按意图 one-vs-rest 计算
- 增加 混淆矩阵（行=gold，列=predicted）
- 增加 FN/FP 错误分析列表
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intent_sample_pipeline import IntentSamplePipeline

logger = logging.getLogger("real_env.eval_gate")


@dataclass
class EvalReport:
    """eval 报告（对齐 spec §3.5 + 行业标准指标）"""
    accuracy: float
    drift: float
    passed: bool
    zero_token_ratio: float
    route_hit_ratio: float
    # v2 新增：行业标准指标
    precision: Dict[str, float] = field(default_factory=dict)
    recall: Dict[str, float] = field(default_factory=dict)
    f1: Dict[str, float] = field(default_factory=dict)
    f1_macro: float = 0.0
    confusion_matrix: List[List[int]] = field(default_factory=list)
    intent_labels: List[str] = field(default_factory=list)
    fn_list: List[dict] = field(default_factory=list)
    fp_list: List[dict] = field(default_factory=list)
    details: List[dict] = field(default_factory=list)


class IntentEvalGate:
    """eval 集回归门"""

    def __init__(
        self,
        pipeline: IntentSamplePipeline,
        route_fn: Optional[Callable] = None,
        accuracy_target: float = 0.75,
        drift_limit: float = 0.03,
        zero_token_target: float = 0.50,
    ):
        self._pipeline = pipeline
        self._route_fn = route_fn
        self.ACCURACY_TARGET = accuracy_target
        self.ACCURACY_DRIFT_LIMIT = drift_limit
        self.ZERO_TOKEN_TARGET = zero_token_target
        self._last_accuracy: Optional[float] = None

    def run_eval(self) -> EvalReport:
        """跑 eval 集，返回 EvalReport（含 F1/混淆矩阵/FN-FP 错误分析）"""
        eval_samples = self._pipeline.load_split("eval")
        if not eval_samples:
            return EvalReport(0.0, 0.0, False, 0.0, 0.0)

        results: List[bool] = []
        zero_token_count = 0
        route_hit_count = 0
        details: List[dict] = []
        predictions: List[tuple] = []  # (gold, predicted, sample_id, user_query)

        for sample in eval_samples:
            output = self._call_dreamos_intent_route(sample.input["user_query"])
            predicted = output.get("predicted_intent")
            gold = sample.gold["gold_intent"]
            correct = predicted == gold
            results.append(correct)
            if output.get("level") == "rule":
                zero_token_count += 1
            if correct:
                route_hit_count += 1
            details.append({
                "sample_id": sample.sample_id,
                "gold": gold,
                "predicted": predicted,
                "correct": correct,
            })
            predictions.append((gold, predicted, sample.sample_id, sample.input["user_query"]))

        accuracy = sum(results) / len(results)
        drift = abs(accuracy - self._last_accuracy) if self._last_accuracy is not None else 0.0
        passed = accuracy >= self.ACCURACY_TARGET and drift < self.ACCURACY_DRIFT_LIMIT

        # v2: 计算行业标准指标
        precision, recall, f1, f1_macro, confusion_matrix, intent_labels, fn_list, fp_list = \
            self._compute_classification_metrics(predictions)

        report = EvalReport(
            accuracy=accuracy,
            drift=drift,
            passed=passed,
            zero_token_ratio=zero_token_count / len(eval_samples),
            route_hit_ratio=route_hit_count / len(eval_samples),
            precision=precision,
            recall=recall,
            f1=f1,
            f1_macro=f1_macro,
            confusion_matrix=confusion_matrix,
            intent_labels=intent_labels,
            fn_list=fn_list,
            fp_list=fp_list,
            details=details,
        )
        self._last_accuracy = accuracy
        return report

    @staticmethod
    def _compute_classification_metrics(predictions: List[tuple]):
        """计算 Precision/Recall/F1 (one-vs-rest) + 混淆矩阵 + FN/FP 列表

        Args:
            predictions: [(gold, predicted, sample_id, user_query), ...]

        Returns:
            (precision, recall, f1, f1_macro, confusion_matrix, labels, fn_list, fp_list)
        """
        # 收集所有意图标签（gold ∪ predicted），按字母序稳定排序
        all_labels = sorted(set(g for g, _, _, _ in predictions) | set(p for _, p, _, _ in predictions if p))
        label_to_idx = {label: i for i, label in enumerate(all_labels)}
        n = len(all_labels)

        # 混淆矩阵
        cm = [[0] * n for _ in range(n)]
        for gold, predicted, _, _ in predictions:
            if predicted is None:
                continue  # None 不进混淆矩阵（视为未命中）
            g_idx = label_to_idx[gold]
            p_idx = label_to_idx[predicted]
            cm[g_idx][p_idx] += 1

        # 每意图 one-vs-rest 的 TP/FP/FN
        precision: Dict[str, float] = {}
        recall: Dict[str, float] = {}
        f1: Dict[str, float] = {}
        fn_list: List[dict] = []
        fp_list: List[dict] = []

        for label in all_labels:
            tp = sum(1 for g, p, _, _ in predictions if g == label and p == label)
            fp = sum(1 for g, p, _, _ in predictions if g != label and p == label)
            fn = sum(1 for g, p, _, _ in predictions if g == label and p != label)

            prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1_val = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
            precision[label] = prec
            recall[label] = rec
            f1[label] = f1_val

        # macro F1 = 所有意图 F1 的算术平均
        f1_macro = sum(f1.values()) / len(f1) if f1 else 0.0

        # FN 列表：gold != predicted 的样本（漏判）
        for gold, predicted, sample_id, query in predictions:
            if gold != predicted:
                fn_list.append({
                    "sample_id": sample_id,
                    "gold": gold,
                    "predicted": predicted,
                    "user_query": query[:60],
                })

        # FP 列表：predicted != gold 的样本（误判来源）
        for gold, predicted, sample_id, query in predictions:
            if predicted is not None and predicted != gold:
                fp_list.append({
                    "sample_id": sample_id,
                    "predicted": predicted,
                    "gold": gold,
                    "user_query": query[:60],
                })

        return precision, recall, f1, f1_macro, cm, all_labels, fn_list, fp_list

    def _call_dreamos_intent_route(self, user_input: str) -> dict:
        """调用 DreamOS /intent/route（HC-7 FAIL-OPEN）"""
        if self._route_fn:
            try:
                return self._route_fn(user_input)
            except Exception as e:
                logger.warning("route_fn 失败，降级: %s", e)
                return {"predicted_intent": None, "confidence": 0.0, "level": "failopen"}
        import requests
        try:
            resp = requests.post(
                "http://localhost:8000/api/v1/intent/route",
                json={"text": user_input},
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "predicted_intent": data.get("predicted_intent"),
                    "confidence": data.get("confidence", 0.0),
                    "level": data.get("level", "remote"),
                }
            return {"predicted_intent": None, "confidence": 0.0, "level": "failopen"}
        except Exception as e:
            logger.warning("DreamOS 不可用，降级: %s", e)
            return {"predicted_intent": None, "confidence": 0.0, "level": "failopen"}
