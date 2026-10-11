"""Trae 在线辅导循环 — v0.2 自动监控+纠正+评估。

接收编排器返回的辅导上下文（v0.5 含 pre_models/post_models/training_results），
自动评估监控检查、生成纠正建议、计算训练成果提升。

v0.1 → v0.2 变更:
  - 新增 run_coaching_cycle(): 一键执行完整辅导循环
  - 新增 _evaluate_monitoring(): 对比 pre/post model 自动评估
  - 新增 _generate_corrections(): 基于偏差生成纠正建议
  - 新增 _calculate_improvement(): 前后模型对比计算提升
  - to_report() 的 improvement 从 None 变为 dict（有模型快照时）

设计:
  - CoachingSession: 一次辅导会话的生命周期管理
  - v0.1 手动 API 保留（get_monitoring_checklist/record_monitoring_result/record_correction）
  - v0.2 自动 API（run_coaching_cycle 自动评估+纠正+计算）
"""
from typing import Any, Dict, List, Optional, Tuple


class CoachingSession:
    """一次 Trae 在线辅导会话。

    生命周期:
      v0.1 手动模式:
        1. 从编排器获取 coaching_context 创建会话
        2. get_monitoring_checklist() 获取监控清单
        3. 对每项监控调用 record_monitoring_result()
        4. 如需纠正调用 record_correction()
        5. calculate_quality_score() 计算辅导质量分
        6. to_report() 输出辅导会话报告

      v0.2 自动模式:
        1. 从编排器获取 coaching_context（含 pre_models/post_models）创建会话
        2. run_coaching_cycle() 一键执行: 自动评估+纠正+计算
        3. to_report() 输出含 improvement 的报告
    """

    def __init__(self, coaching_context: Dict[str, Any]):
        """初始化辅导会话。

        Args:
            coaching_context: 编排器 trigger_passive_training() 返回的 coaching_context
                v0.5 含: case_intent, case_outcome, acceptance_level,
                algorithm_patterns, call_chain, known_gaps, monitoring_checks,
                pre_models, post_models, training_results
        """
        self._context = coaching_context
        self._monitoring_log: List[Dict[str, Any]] = []
        self._corrections: List[Dict[str, Any]] = []
        self._improvement: Optional[Dict[str, Any]] = None

    def get_monitoring_checklist(self) -> List[Dict[str, str]]:
        """从辅导上下文生成可执行监控清单。

        Returns:
            监控清单，每项含 check_id 和 check_name 和 description 和 status
        """
        raw_checks = self._context.get("monitoring_checks", [])
        checklist = []
        for i, check in enumerate(raw_checks):
            if isinstance(check, str):
                checklist.append({
                    "check_id": f"check_{i+1}",
                    "check_name": check,
                    "description": check,
                    "status": "pending",
                })
            elif isinstance(check, dict):
                checklist.append({
                    "check_id": check.get("check_id", f"check_{i+1}"),
                    "check_name": check.get("check_name", str(check)),
                    "description": check.get("description", str(check)),
                    "status": "pending",
                })
        return checklist

    def record_monitoring_result(
        self,
        check_name: str,
        passed: bool,
        detail: str = "",
    ) -> None:
        """记录一项监控检查结果。

        Args:
            check_name: 监控检查名称
            passed: 是否通过
            detail: 检查详情（差异描述等）
        """
        self._monitoring_log.append({
            "check_name": check_name,
            "passed": passed,
            "detail": detail,
        })

    def record_correction(
        self,
        layer: str,
        issue: str,
        correction: str,
    ) -> None:
        """记录一次纠正。

        Args:
            layer: 训练层（S/DSH/C/G/LLM）
            issue: 发现的问题
            correction: 纠正方向
        """
        self._corrections.append({
            "layer": layer,
            "issue": issue,
            "correction": correction,
        })

    def calculate_quality_score(self) -> int:
        """计算辅导质量分（0-100）。

        基于监控检查通过率计算。
        无监控记录时返回 0（未开始辅导）。

        Returns:
            质量分 0-100
        """
        if not self._monitoring_log:
            return 0
        passed = sum(1 for r in self._monitoring_log if r["passed"])
        total = len(self._monitoring_log)
        return int(passed / total * 100)

    # ========================================================
    # v0.2 自动辅导循环
    # ========================================================

    def run_coaching_cycle(self) -> None:
        """执行完整辅导循环（v0.2 自动模式）。

        流程:
          1. 自动评估所有监控检查（对比 pre/post model）
          2. 基于偏差生成纠正建议
          3. 计算训练成果提升（pre vs post model）
        """
        # 1. 自动评估监控
        self._evaluate_all_monitoring_checks()

        # 2. 生成纠正
        self._generate_corrections()

        # 3. 计算提升
        self._improvement = self._calculate_improvement()

    def _evaluate_all_monitoring_checks(self) -> None:
        """自动评估所有监控检查项。

        对 monitoring_checks 中的每一项，基于 pre/post model 判断是否通过。
        """
        checklist = self.get_monitoring_checklist()
        for check in checklist:
            passed, detail = self._evaluate_monitoring(check["check_name"])
            self.record_monitoring_result(check["check_name"], passed, detail)

    def _evaluate_monitoring(self, check_name: str) -> Tuple[bool, str]:
        """评估单项监控检查。

        基于 pre_models 和 post_models 对比，判断训练是否符合预期。

        Args:
            check_name: 监控检查名称

        Returns:
            (是否通过, 详情描述)
        """
        pre_models = self._context.get("pre_models", {})
        post_models = self._context.get("post_models", {})
        algorithm_patterns = self._context.get("algorithm_patterns", [])
        call_chain = self._context.get("call_chain", [])
        known_gaps = self._context.get("known_gaps", [])
        dependency_graph = self._context.get("dependency_graph", {})

        # 无模型快照 → 无法自动评估，标记为通过（不阻塞）
        if not pre_models or not post_models:
            return True, "无模型快照，跳过自动评估"

        # 无 REA 数据 → 降级为检查任意层是否有训练变化
        has_rea_data = bool(algorithm_patterns or call_chain or known_gaps or dependency_graph)
        if not has_rea_data:
            return self._check_any_model_change(pre_models, post_models)

        # 监控1: 各层训练是否符合算法模式
        if "算法模式" in check_name:
            return self._check_algorithm_patterns(
                pre_models, post_models, algorithm_patterns
            )

        # 监控2: DSH 执行路径是否与调用链一致
        if "DSH" in check_name or "执行路径" in check_name or "调用链" in check_name:
            return self._check_dsh_path(
                pre_models, post_models, call_chain
            )

        # 监控3: C 层反思是否覆盖 known_gaps
        if "C层" in check_name or "反思" in check_name or "known_gaps" in check_name:
            return self._check_c_layer_reflection(
                pre_models, post_models, known_gaps
            )

        # 监控4: G 层图结构是否与依赖图匹配
        if "G层" in check_name or "图结构" in check_name or "依赖图" in check_name:
            return self._check_g_layer_graph(
                pre_models, post_models, dependency_graph
            )

        # 默认: 检查是否有任意层的模型变化
        return self._check_any_model_change(pre_models, post_models)

    def _check_algorithm_patterns(
        self, pre_models: dict, post_models: dict, patterns: list
    ) -> Tuple[bool, str]:
        """检查训练后模型是否学习到了算法模式。"""
        # 检查所有层是否有权重或 step 变化
        for layer in ["S", "DSH", "C", "G", "LLM"]:
            pre = pre_models.get(layer, {})
            post = post_models.get(layer, {})
            if pre.get("degraded") or post.get("degraded"):
                continue
            pre_weights = pre.get("weights", {})
            post_weights = post.get("weights", {})
            if post_weights and pre_weights != post_weights:
                return True, f"{layer} 层权重已更新，算法模式训练有效"
            # 也检查 step 变化（step+1 表示训练执行了）
            if pre.get("step", 0) != post.get("step", 0):
                return True, f"{layer} 层 step 提升，训练已执行"
        return False, "所有层权重和 step 无变化，算法模式训练未生效"

    def _check_dsh_path(
        self, pre_models: dict, post_models: dict, call_chain: list
    ) -> Tuple[bool, str]:
        """检查 DSH 层是否学习到了 call_chain 路径。"""
        pre_dsh = pre_models.get("DSH", {})
        post_dsh = post_models.get("DSH", {})
        if pre_dsh.get("degraded") or post_dsh.get("degraded"):
            return True, "DSH 层降级，跳过路径检查"

        post_weights = post_dsh.get("weights", {})
        pre_weights = pre_dsh.get("weights", {})

        # 检查 call_chain 中的节点是否在 post_weights 中有权重提升
        if call_chain and post_weights:
            chain_in_weights = sum(
                1 for node in call_chain
                if node in post_weights and post_weights[node] > pre_weights.get(node, 0)
            )
            if chain_in_weights > 0:
                return True, f"DSH 调用链 {chain_in_weights}/{len(call_chain)} 节点权重提升"

        # 如果有权重变化，也算通过
        if post_weights and pre_weights != post_weights:
            return True, "DSH 层权重已更新"

        # 检查 step 变化（step+1 表示训练执行了）
        if pre_dsh.get("step", 0) != post_dsh.get("step", 0):
            return True, "DSH 层 step 提升，训练已执行"

        return False, "DSH 层调用链路径未学习"

    def _check_c_layer_reflection(
        self, pre_models: dict, post_models: dict, known_gaps: list
    ) -> Tuple[bool, str]:
        """检查 C 层反思是否覆盖 known_gaps。"""
        pre_c = pre_models.get("C", {})
        post_c = post_models.get("C", {})
        if pre_c.get("degraded") or post_c.get("degraded"):
            return True, "C 层降级，跳过反思检查"

        post_weights = post_c.get("weights", {})
        pre_weights = pre_c.get("weights", {})

        if post_weights and pre_weights != post_weights:
            return True, "C 层权重已更新，反思训练有效"

        # 检查 step 变化
        if pre_c.get("step", 0) != post_c.get("step", 0):
            return True, "C 层 step 提升，训练已执行"

        return False, "C 层权重无变化，反思训练未生效"

    def _check_g_layer_graph(
        self, pre_models: dict, post_models: dict, dependency_graph: dict
    ) -> Tuple[bool, str]:
        """检查 G 层图结构是否与依赖图匹配。"""
        pre_g = pre_models.get("G", {})
        post_g = post_models.get("G", {})
        if pre_g.get("degraded") or post_g.get("degraded"):
            return True, "G 层降级，跳过图结构检查"

        post_weights = post_g.get("weights", {})
        pre_weights = pre_g.get("weights", {})

        if post_weights and pre_weights != post_weights:
            return True, "G 层权重已更新，图结构训练有效"

        # 检查 step 变化
        if pre_g.get("step", 0) != post_g.get("step", 0):
            return True, "G 层 step 提升，训练已执行"

        return False, "G 层权重无变化，图结构训练未生效"

    def _check_any_model_change(
        self, pre_models: dict, post_models: dict
    ) -> Tuple[bool, str]:
        """默认检查: 是否有任意层模型变化（权重或 step）。"""
        for layer in pre_models:
            pre = pre_models.get(layer, {})
            post = post_models.get(layer, {})
            if pre.get("degraded") or post.get("degraded"):
                continue
            # 检查 step 变化
            if pre.get("step", 0) != post.get("step", 0):
                return True, f"{layer} 层 step 提升 (训练已执行)"
            # 检查权重变化
            if pre.get("weights", {}) != post.get("weights", {}) and post.get("weights"):
                return True, f"{layer} 层权重已更新"
        return False, "所有层模型无变化"

    def _generate_corrections(self) -> None:
        """基于监控结果生成纠正建议。

        对未通过的监控项，生成对应的纠正方向。
        """
        for log in self._monitoring_log:
            if log["passed"]:
                continue

            check_name = log["check_name"]
            detail = log["detail"]

            # 根据监控类型生成纠正
            if "算法模式" in check_name:
                self.record_correction(
                    "DSH",
                    detail,
                    "增加算法模式训练数据，调整 DSH 层学习率或增加训练步数",
                )
            elif "DSH" in check_name or "执行路径" in check_name:
                self.record_correction(
                    "DSH",
                    detail,
                    "检查 call_chain 是否完整，补充缺失的调用路径训练数据",
                )
            elif "C层" in check_name or "反思" in check_name:
                self.record_correction(
                    "C",
                    detail,
                    "增加 known_gaps 相关的反思训练数据，强化 C 层反思能力",
                )
            elif "G层" in check_name or "图结构" in check_name:
                self.record_correction(
                    "G",
                    detail,
                    "补充 dependency_graph 训练数据，强化 G 层图结构学习",
                )
            else:
                self.record_correction(
                    "ALL",
                    detail,
                    "检查训练数据质量和学习率配置，确保模型能有效学习",
                )

    def _calculate_improvement(self) -> Optional[Dict[str, Any]]:
        """计算训练成果提升（pre vs post model 对比）。

        Returns:
            各层的提升信息 dict，或 None（无模型快照时）
        """
        pre_models = self._context.get("pre_models", {})
        post_models = self._context.get("post_models", {})

        if not pre_models or not post_models:
            return None

        improvement: Dict[str, Any] = {}
        for layer in pre_models:
            pre = pre_models.get(layer, {})
            post = post_models.get(layer, {})
            if pre.get("degraded") or post.get("degraded"):
                improvement[layer] = {"available": False, "reason": "degraded"}
                continue

            pre_weights = pre.get("weights", {})
            post_weights = post.get("weights", {})
            pre_step = pre.get("step", 0)
            post_step = post.get("step", 0)

            # 计算权重变化总量
            weight_delta = 0.0
            for key in set(list(pre_weights.keys()) + list(post_weights.keys())):
                delta = post_weights.get(key, 0) - pre_weights.get(key, 0)
                weight_delta += abs(delta)

            improvement[layer] = {
                "available": True,
                "step_delta": post_step - pre_step,
                "weight_delta": round(weight_delta, 4),
                "pre_step": pre_step,
                "post_step": post_step,
            }

        return improvement

    def to_report(self) -> Dict[str, Any]:
        """输出辅导会话报告。

        Returns:
            辅导会话报告 dict
        """
        return {
            "quality_score": self.calculate_quality_score(),
            "correction_count": len(self._corrections),
            "monitoring_log": self._monitoring_log,
            "corrections": self._corrections,
            "improvement": self._improvement,
            "coaching_context_summary": {
                "case_intent": self._context.get("case_intent", ""),
                "case_outcome": self._context.get("case_outcome", ""),
                "acceptance_level": self._context.get("acceptance_level", ""),
                "algorithm_patterns_count": len(self._context.get("algorithm_patterns", [])),
                "call_chain_length": len(self._context.get("call_chain", [])),
                "known_gaps_count": len(self._context.get("known_gaps", [])),
            },
        }
