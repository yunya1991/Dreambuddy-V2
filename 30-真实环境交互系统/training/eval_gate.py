"""意图识别 eval 回归门

对齐 spec §3.5。跑 eval 集验证训练后准确率/波动/零 Token 占比/路由命中率。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intent_sample_pipeline import IntentSamplePipeline

logger = logging.getLogger("real_env.eval_gate")


@dataclass
class EvalReport:
    """eval 报告（对齐 spec §3.5）"""
    accuracy: float
    drift: float
    passed: bool
    zero_token_ratio: float
    route_hit_ratio: float
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
        """跑 eval 集，返回 EvalReport"""
        eval_samples = self._pipeline.load_split("eval")
        if not eval_samples:
            return EvalReport(0.0, 0.0, False, 0.0, 0.0)

        results: List[bool] = []
        zero_token_count = 0
        route_hit_count = 0
        details: List[dict] = []

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

        accuracy = sum(results) / len(results)
        drift = abs(accuracy - self._last_accuracy) if self._last_accuracy is not None else 0.0
        passed = accuracy >= self.ACCURACY_TARGET and drift < self.ACCURACY_DRIFT_LIMIT

        report = EvalReport(
            accuracy=accuracy,
            drift=drift,
            passed=passed,
            zero_token_ratio=zero_token_count / len(eval_samples),
            route_hit_ratio=route_hit_count / len(eval_samples),
            details=details,
        )
        self._last_accuracy = accuracy
        return report

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
