"""TS HTTP 训练执行器适配器。

通过 HTTP 调用 3.1-FRONTEND 的 TS 训练循环 API route，
实现 TrainingExecutor 协议，让 34 的编排器能触发 TS 层训练。

设计:
  - HTTP client 调用 /api/training/[layer] 端点
  - add_case() → POST add，train() → POST train，get_bucket_count() → GET status
  - 转换 TrainingCase → 层专属 TrainingData
  - FAIL-OPEN：HTTP 超时/失败 → 降级返回，不阻塞编排器
"""
import json
import os
import sys
import urllib.request
import urllib.error
from typing import Any, List, Optional

# sys.path 注入
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)

for _p in [_THIS_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from interfaces.training_executor import TrainingExecutor, TrainingLayer, TrainingResult
from interfaces.training_data_provider import TrainingCase
from core.decision_deriver import derive_expected_decision_with_cdrive
from core.debate_integration import enrich_case_with_debate

# 前端服务地址
_DEFAULT_BASE_URL = "http://localhost:3001"
_BASE_URL = os.environ.get("TRAINING_FRONTEND_URL", _DEFAULT_BASE_URL)
_TIMEOUT = 10  # 秒


class TSHTTPTrainingExecutor(TrainingExecutor):
    """TS HTTP 训练执行器。

    通过 HTTP API 调用 3.1-FRONTEND 的 TS 训练循环，
    实现 TrainingExecutor 协议。
    """

    # 各层桶满阈值（与 TS 端 DEFAULT_BUCKET_THRESHOLD 一致）
    _LAYER_THRESHOLDS = {
        "S": 50,
        "DSH": 50,
        "C": 50,
        "G": 60,
        "LLM": 30,
    }

    # 训练依赖顺序
    _LAYER_DEPENDENCIES = {
        "S": [],
        "DSH": ["S"],
        "C": ["S", "DSH"],
        "G": [],
        "LLM": ["C"],
    }

    def __init__(self, layer: TrainingLayer, base_url: Optional[str] = None):
        self._layer = layer
        self._base_url = (base_url or _BASE_URL).rstrip("/")
        self._cached_bucket_count = 0

    def get_layer(self) -> TrainingLayer:
        return self._layer

    def get_bucket_threshold(self) -> int:
        return self._LAYER_THRESHOLDS.get(self._layer.value, 50)

    def get_bucket_count(self) -> int:
        """从 TS API 获取当前桶中数据量。"""
        try:
            resp = self._http_get(f"/api/training/{self._layer.value.lower()}")
            if resp.get("success"):
                return resp.get("data", {}).get("bucketCount", 0)
        except Exception:
            pass
        return self._cached_bucket_count

    def add_case(self, case: Any) -> bool:
        """向 TS 训练循环添加训练数据。

        将 TrainingCase 转换为层专属 TrainingData 格式后发送。
        """
        training_data = self._convert_case_to_training_data(case)
        try:
            resp = self._http_post(
                f"/api/training/{self._layer.value.lower()}",
                {"action": "add", "data": training_data},
            )
            if resp.get("success") and resp.get("data", {}).get("added"):
                self._cached_bucket_count += 1
                return True
        except Exception:
            pass
        return False

    def train(self) -> TrainingResult:
        """触发 TS 训练循环训练。"""
        try:
            resp = self._http_post(
                f"/api/training/{self._layer.value.lower()}",
                {"action": "train"},
            )
            if resp.get("success"):
                data = resp.get("data", {})
                return TrainingResult(
                    layer=self._layer,
                    success=data.get("trained", False),
                    metrics={
                        "bucket_count": data.get("bucket_count", 0),
                        "bucket_threshold": data.get("bucket_threshold", 0),
                    },
                    message="trained" if data.get("trained") else "not_enough_data",
                )
        except Exception as e:
            return TrainingResult(
                layer=self._layer,
                success=False,
                message=f"degraded: {e}",
            )

    def get_dependencies(self) -> List[TrainingLayer]:
        deps = self._LAYER_DEPENDENCIES.get(self._layer.value, [])
        return [TrainingLayer(d) for d in deps]

    # ========================================================
    # v0.5 P2.3: 增量训练 / Checkpoint / Restore / Model
    # ========================================================

    def trigger_incremental(self) -> TrainingResult:
        """触发 TS 训练循环增量训练。

        POST action=incremental → trainIncrementalLayer
        """
        try:
            resp = self._http_post(
                f"/api/training/{self._layer.value.lower()}",
                {"action": "incremental"},
            )
            if resp.get("success"):
                data = resp.get("data", {})
                return TrainingResult(
                    layer=self._layer,
                    success=data.get("trained", False),
                    metrics={
                        "bucket_count": data.get("bucket_count", 0),
                        "bucket_threshold": data.get("bucket_threshold", 0),
                        "incremental_step": data.get("incrementalStep", 0),
                        "weights": data.get("weights", {}),
                    },
                    message="incremental" if data.get("trained") else "not_enough_data",
                )
        except Exception as e:
            return TrainingResult(
                layer=self._layer,
                success=False,
                message=f"degraded: {e}",
            )

    def checkpoint(self) -> dict:
        """保存模型状态检查点。

        POST action=checkpoint → checkpointLayer
        """
        try:
            resp = self._http_post(
                f"/api/training/{self._layer.value.lower()}",
                {"action": "checkpoint"},
            )
            if resp.get("success"):
                return resp.get("data", {})
            return {"checkpointed": False, "degraded": True}
        except Exception as e:
            return {"checkpointed": False, "degraded": True, "error": str(e)}

    def restore(self, state: dict) -> dict:
        """恢复模型状态。

        POST action=restore → restoreLayer
        """
        try:
            resp = self._http_post(
                f"/api/training/{self._layer.value.lower()}",
                {"action": "restore", "data": state},
            )
            if resp.get("success"):
                return resp.get("data", {})
            return {"restored": False, "degraded": True}
        except Exception as e:
            return {"restored": False, "degraded": True, "error": str(e)}

    def get_model(self) -> dict:
        """获取模型状态 JSON。

        GET /api/training/[layer]/model → getModelSnapshot
        """
        try:
            resp = self._http_get(
                f"/api/training/{self._layer.value.lower()}/model"
            )
            if resp.get("success"):
                return resp.get("data", {})
            return {"degraded": True, "step": 0}
        except Exception:
            return {"degraded": True, "step": 0}

    def _convert_case_to_training_data(self, case: TrainingCase) -> dict:
        """将 TrainingCase 转换为层专属 TrainingData 格式。

        S 层: {message, intent_type, entities}
        DSH 层: {task, node_sequence, outcome}
        C 层: {context_summary, action_taken, outcome, expected_decision}
        G 层: {decisions, rules}
        LLM 层: {intent, learned, outcome, prompt_pattern}
        """
        layer = self._layer.value
        # P1 修复: 从 quality/confidence 派生 outcome + 归一化 prompt_pattern
        from core.outcome_pattern_deriver import derive_outcome, normalize_prompt_pattern
        outcome = derive_outcome(case)
        prompt_pattern = normalize_prompt_pattern(case)

        if layer == "S":
            return {
                "message": case.outcome_text or case.intent,
                "intent_type": case.intent,
                "entities": [],
            }
        elif layer == "DSH":
            return {
                "task": case.intent,
                "node_sequence": case.actions,
                "outcome": outcome,
            }
        elif layer == "C":
            # P3: 复杂案例注入辩论元数据（FAIL-OPEN：引擎不可用时降级 P2/P1）
            enrich_case_with_debate(case)
            return {
                "context_summary": case.intent,
                "action_taken": case.actions[0] if case.actions else "",
                "outcome": outcome,
                "expected_decision": derive_expected_decision_with_cdrive(case),
            }
        elif layer == "G":
            return {
                "decisions": [case.intent],
                "rules": case.learned,
            }
        elif layer == "LLM":
            return {
                "intent": case.intent,
                "learned": case.learned,
                "outcome": outcome,
                "prompt_pattern": prompt_pattern,
            }
        else:
            return {"intent": case.intent, "learned": case.learned}

    def _http_get(self, path: str) -> dict:
        """HTTP GET 请求。"""
        url = f"{self._base_url}{path}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _http_post(self, path: str, body: dict) -> dict:
        """HTTP POST 请求。"""
        url = f"{self._base_url}{path}"
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
