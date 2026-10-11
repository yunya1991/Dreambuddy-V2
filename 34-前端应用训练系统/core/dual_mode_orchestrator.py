"""双模式训练调度器。

统一调度主动训练（横向批量统计）和被动训练（纵深Trae在线辅导）。
管理双模式的资源分配和优先级。

P3 扩展:
  - 资源配额管理 (ResourceManager)
  - 训练队列 + 重试机制 (TrainingQueue)
  - 状态监控 (get_status)
"""
import os
import sys
from typing import Dict, List, Optional

# sys.path 注入：确保可从任何上下文 import
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_ADAPTERS_DIR = os.path.join(_34_DIR, "adapters")
for _p in [_THIS_DIR, _34_DIR, _ADAPTERS_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from interfaces.training_data_provider import TrainingDataProvider
from interfaces.training_executor import TrainingExecutor, TrainingLayer
from interfaces.case_evaluator import CaseEvaluator
from interfaces.rea_parser import REAParser

# P3: 资源管理 + 训练队列
try:
    from resource_manager import ResourceManager, ACTIVE_QUOTA, PASSIVE_QUOTA
    from training_queue import TrainingQueue, QueuedTask
    _P3_AVAILABLE = True
except Exception:
    _P3_AVAILABLE = False
    ResourceManager = None
    ACTIVE_QUOTA = None
    PASSIVE_QUOTA = None
    TrainingQueue = None
    QueuedTask = None


class DualModeTrainingOrchestrator:
    """双模式训练调度器。

    职责：
    - 管理主动训练采集器和被动训练触发器
    - 协调双模式资源分配（被动优先于主动）
    - 不阻塞用户交互
    - P3: 资源配额管理 + 训练队列 + 状态监控
    """

    def __init__(
        self,
        data_providers: List[TrainingDataProvider],
        training_executors: List[TrainingExecutor],
        case_evaluator: CaseEvaluator,
        rea_parser: Optional[REAParser] = None,
    ):
        self._data_providers = data_providers
        self._training_executors = training_executors
        self._case_evaluator = case_evaluator
        self._rea_parser = rea_parser
        self._passive_training_active = False

        # P3: 资源管理 + 训练队列
        self._active_rm = ResourceManager(ACTIVE_QUOTA) if _P3_AVAILABLE else None
        self._passive_rm = ResourceManager(PASSIVE_QUOTA) if _P3_AVAILABLE else None
        self._queue = TrainingQueue(max_retries=3) if _P3_AVAILABLE else None
        self._active_training_running = False

    def run_active_training(self, limit: int = 100) -> dict:
        """执行主动训练（横向批量采集+桶满触发）。

        低优先级后台任务，凌晨低峰期执行。
        被动训练进行时自动暂停。
        """
        if self._passive_training_active:
            return {"status": "skipped", "reason": "passive_training_active"}

        results = []
        for provider in self._data_providers:
            cases = provider.fetch_cases(limit=limit)
            for case in cases:
                for executor in self._training_executors:
                    if executor.get_layer().value in case.layer_tags:
                        executor.add_case(case)
                        if executor.get_bucket_count() >= executor.get_bucket_threshold():
                            result = executor.train()
                            results.append(result)

        return {"status": "completed", "training_results": len(results)}

    def trigger_passive_training(self, wrapup_case: dict) -> dict:
        """触发被动训练（Trae在线辅导）— v0.5 模式。

        v0.5 流程（替代 v0.2 桶满触发）:
          1. CaseIngestGate 评估
          2. 33-REA 解析
          3. rea_to_tdr_adapter 转换为 TrainingCase
          4. 对涉及的层执行 v0.5 增量训练:
             a. get_model() → pre_model（训练前模型快照）
             b. checkpoint() → 保存检查点（用于 restore 回滚）
             c. add_case() → 加入训练数据
             d. trigger_incremental() → 增量训练（单案例即可，不等桶满）
             e. get_model() → post_model（训练后模型快照）
          5. 构建 coaching_context 含 pre_models/post_models/training_results

        中优先级，收尾后立即执行。可抢占主动训练。
        FAIL-OPEN: trigger_incremental/get_model 异常不崩溃。

        Args:
            wrapup_case: 收尾案例数据（含SPEC信息、验收证据、代码路径等）

        Returns:
            训练状态 dict
        """
        self._passive_training_active = True
        try:
            # 1. 评估案例价值
            evaluation = self._case_evaluator.evaluate(wrapup_case)
            if evaluation.decision.value == "skip":
                return {"status": "skipped", "reason": evaluation.reason}

            # 2. 33-REA解析（如可用）— SPEC §2.3 要求 analyze + trace 都调用
            rea_result = None
            if self._rea_parser and "code_path" in wrapup_case:
                # 2.1 analyze 获取架构+依赖图
                analyze_result = self._rea_parser.analyze(
                    target_path=wrapup_case["code_path"],
                )
                # 2.2 trace 获取调用链+算法模式
                trace_result = self._rea_parser.trace(
                    target_path=wrapup_case["code_path"],
                    feature=wrapup_case.get("feature", ""),
                    entry=wrapup_case.get("entry"),
                )
                # 合并：trace 的 call_chain/algorithm_patterns + analyze 的 dependency_graph
                rea_result = trace_result
                if analyze_result.dependency_graph:
                    rea_result.dependency_graph = analyze_result.dependency_graph

            # 3. 转换为 TrainingCase（通过 rea_to_tdr_adapter）
            from rea_to_tdr_adapter import rea_to_training_cases
            training_cases = rea_to_training_cases(wrapup_case, rea_result)

            # 4. v0.5 增量训练: get_model(pre) → checkpoint → add_case → trigger_incremental → get_model(post)
            pre_models: Dict[str, dict] = {}
            post_models: Dict[str, dict] = {}
            training_results: Dict[str, dict] = {}

            for executor in self._training_executors:
                layer_val = executor.get_layer().value
                # 找到该 executor 对应的训练案例
                layer_cases = [
                    c for c in training_cases if layer_val in c.layer_tags
                ]
                if not layer_cases:
                    continue

                # 4a. get_model → 获取训练前模型状态（与 post_model 格式一致）
                try:
                    pre_models[layer_val] = executor.get_model()
                except (NotImplementedError, Exception):
                    pre_models[layer_val] = {"degraded": True}

                # 4b. checkpoint → 保存检查点（用于 restore 回滚）
                try:
                    executor.checkpoint()
                except (NotImplementedError, Exception):
                    pass  # checkpoint 失败不阻塞

                # 4c. add_case → 加入训练数据
                for case in layer_cases:
                    try:
                        executor.add_case(case)
                    except Exception:
                        pass  # FAIL-OPEN

                # 4d. trigger_incremental → 增量训练（不等桶满）
                try:
                    result = executor.trigger_incremental()
                    training_results[layer_val] = {
                        "success": result.success,
                        "metrics": result.metrics,
                        "message": result.message,
                    }
                except (NotImplementedError, Exception):
                    training_results[layer_val] = {
                        "success": False, "degraded": True,
                    }

                # 4e. get_model → 获取训练后模型状态
                try:
                    post_models[layer_val] = executor.get_model()
                except (NotImplementedError, Exception):
                    post_models[layer_val] = {"degraded": True}

            # 5. 构建 v0.5 辅导上下文（含模型快照）
            return {
                "status": "coaching_started",
                "evaluation": evaluation.__dict__,
                "rea_result": rea_result.__dict__ if rea_result else None,
                "coaching_context": self._build_coaching_context(
                    wrapup_case, rea_result,
                    pre_models=pre_models,
                    post_models=post_models,
                    training_results=training_results,
                ),
            }
        finally:
            self._passive_training_active = False

    def get_status(self) -> dict:
        """获取双模式运行状态（P3 状态监控）。

        Returns:
            {
                active_training: bool,
                passive_training: bool,
                queue_size: int,
                resource_usage: {...},
            }
        """
        status = {
            "active_training": self._active_training_running,
            "passive_training": self._passive_training_active,
            "queue_size": self._queue.size() if self._queue else 0,
            "resource_usage": {},
        }

        if self._active_rm:
            status["resource_usage"]["active"] = self._active_rm.get_usage_report()
        if self._passive_rm:
            status["resource_usage"]["passive"] = self._passive_rm.get_usage_report()

        if self._queue:
            tasks = self._queue.get_all_tasks()
            status["queue_details"] = {
                "total_tasks": len(tasks),
                "pending": sum(1 for t in tasks if t.status == "pending"),
                "running": sum(1 for t in tasks if t.status == "running"),
                "completed": sum(1 for t in tasks if t.status == "completed"),
                "failed": sum(1 for t in tasks if t.status == "failed"),
            }

        return status

    def _build_coaching_context(
        self, wrapup_case: dict, rea_result,
        pre_models: Dict[str, dict] = None,
        post_models: Dict[str, dict] = None,
        training_results: Dict[str, dict] = None,
    ) -> dict:
        """构建Trae在线辅导的上下文（v0.5 含模型快照）。"""
        return {
            "case_intent": wrapup_case.get("intent", ""),
            "case_outcome": wrapup_case.get("outcome", ""),
            "acceptance_level": wrapup_case.get("acceptance_level", ""),
            "algorithm_patterns": rea_result.algorithm_patterns if rea_result else [],
            "call_chain": rea_result.call_chain if rea_result else [],
            "dependency_graph": rea_result.dependency_graph if rea_result else {},
            "known_gaps": rea_result.known_gaps if rea_result else [],
            "monitoring_checks": [
                "各层训练是否符合33-REA解析的算法模式",
                "DSH执行路径是否与调用链一致",
                "C层反思是否覆盖known_gaps",
                "G层图结构是否与依赖图匹配",
            ],
            "pre_models": pre_models or {},
            "post_models": post_models or {},
            "training_results": training_results or {},
        }
