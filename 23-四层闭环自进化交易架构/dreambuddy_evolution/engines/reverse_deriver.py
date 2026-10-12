"""ReverseDeriver — 金融逆向推导引擎。

从交易结果反推哪个矛盾维度判断错，类比神经网络反向传播：
- forward: 矛盾系统 + 矛盾Transformer → 预测
- loss: CS 一致性得分 + PnL
- backward: ReverseDeriver → per_dimension_error
- SGD: ESS/gmax/因子权重更新

借鉴 33-REA 的 Evidence-First：每条逆向结论带 confidence + known_gaps。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ReverseDeriveResult:
    """逆向推导结果。"""
    per_dimension_correctness: dict[str, bool] = field(default_factory=dict)
    per_dimension_cs: dict[str, float] = field(default_factory=dict)
    wrong_dimensions: list[str] = field(default_factory=list)
    wrong_dimension_pattern: str = ""  # 排序后的错误维度组合，如 "C1+C3"
    root_cause: str = ""
    root_cause_type: str = "unknown"  # factor_error / weight_error / data_error / unknown
    confidence: float = 0.0
    known_gaps: list[str] = field(default_factory=list)
    optimization_action: str = "no_adjustment"


class ReverseDeriver:
    """逆向推导器：从交易结果反推哪个矛盾维度判断错。

    四步法：
    1. 对比每个矛盾维度的预测方向 vs 实际方向
    2. 定位主要矛盾的判断是否正确
    3. 根因分类（factor_error / weight_error / data_error）
    4. 输出 optimization_action
    """

    VALID_DIRECTIONS = {"long", "short", "wait"}

    def derive(self, snapshot: dict[str, Any], outcome: dict[str, Any]) -> ReverseDeriveResult:
        """执行逆向推导。

        Args:
            snapshot: 开仓快照，须含 dimension_predictions: {C1: "long", C2: "short", ...}
            outcome: 交易结果，须含 real_direction: "long"/"short"

        Returns:
            ReverseDeriveResult（FAIL-OPEN：输入不完整时返回 neutral）
        """
        try:
            dim_predictions = snapshot.get("dimension_predictions")
            real_direction = outcome.get("real_direction")

            # FAIL-OPEN：缺少必要数据
            if not dim_predictions or not real_direction:
                return self._neutral_result(snapshot, outcome,
                    "缺少 dimension_predictions 或 real_direction")

            real_direction = str(real_direction).lower()
            if real_direction not in self.VALID_DIRECTIONS:
                return self._neutral_result(snapshot, outcome,
                    f"无效 real_direction: {real_direction}")

            # Step 1: 每维度正确性
            per_dim_correctness, per_dim_cs = self._per_dimension_correctness(
                dim_predictions, real_direction)

            wrong_dims = [d for d, c in per_dim_correctness.items() if not c]
            # 多维度联合归因：排序后的错误维度组合模式（供 CBR 检索）
            wrong_dimension_pattern = "+".join(sorted(wrong_dims))

            # Step 2-3: 根因分析
            root_cause, root_cause_type = self._analyze_root_cause(
                per_dim_correctness, snapshot, outcome)

            # Step 4: 优化动作
            optimization_action = self._recommend_action(
                wrong_dims, root_cause_type, outcome)

            # 置信度：反映推导结论的可靠性（数据充分度），而非正确率
            # 维度越多 → 归因越可靠；单维度判断可信度中等（0.333）
            total = len(per_dim_correctness)
            confidence = round(min(1.0, total / 3.0), 3) if total > 0 else 0.0

            return self._output_evidence(
                per_dim_correctness, per_dim_cs, wrong_dims,
                wrong_dimension_pattern, root_cause, root_cause_type,
                confidence, optimization_action,
            )
        except Exception as e:
            logger.warning("[FO] ReverseDeriver fail: %s", e)
            return self._neutral_result(snapshot, outcome, str(e))

    # ------------------------------------------------------------------
    def _per_dimension_correctness(self, dim_predictions: dict,
                                    real_direction: str) -> tuple[dict, dict]:
        """Step1: 每维度预测方向 vs 实际方向 → 正确性 + 维度CS。"""
        per_dim_correctness: dict[str, bool] = {}
        per_dim_cs: dict[str, float] = {}
        for dim, pred_dir in dim_predictions.items():
            pred_dir = str(pred_dir).lower()
            correct = self._direction_match(pred_dir, real_direction)
            per_dim_correctness[dim] = correct
            per_dim_cs[dim] = 1.0 if correct else -1.0
        return per_dim_correctness, per_dim_cs

    def _output_evidence(self, per_dim_correctness, per_dim_cs, wrong_dims,
                         wrong_dimension_pattern, root_cause, root_cause_type,
                         confidence, optimization_action) -> ReverseDeriveResult:
        """Step4: 输出逆向 Evidence（ReverseDeriveResult）。"""
        known_gaps = [
            "维度预测方向来自 PrimaryContradictionIdentifier 输入 paths",
            "因子值缺失时无法区分 factor_error 与 data_error",
            "动态调用/条件分支的维度判断可能不准确",
        ]
        return ReverseDeriveResult(
            per_dimension_correctness=per_dim_correctness,
            per_dimension_cs=per_dim_cs,
            wrong_dimensions=wrong_dims,
            wrong_dimension_pattern=wrong_dimension_pattern,
            root_cause=root_cause,
            root_cause_type=root_cause_type,
            confidence=confidence,
            known_gaps=known_gaps,
            optimization_action=optimization_action,
        )

    def _direction_match(self, pred: str, real: str) -> bool:
        """预测方向与实际方向是否一致（wait 始终算不匹配）。"""
        if pred not in self.VALID_DIRECTIONS or real not in self.VALID_DIRECTIONS:
            return False
        if pred == "wait" or real == "wait":
            return False
        return pred == real

    def _evidence_trace(self, snapshot: dict, wrong_dim: str) -> dict:
        """Step3: 证据链回溯 — 因子值/权重/数据源定位根因。

        对错误维度的每个因子收集：
        - weight: 因子权重
        - value: 因子实际值（缺失则 None）
        - weight_anomaly: 权重是否异常（>0.8 或 <0.05）
        - value_anomaly: 因子值是否异常（为0或缺失）

        返回 root_cause_candidate:
        - weight_error: 存在权重异常
        - data_error: 因子值缺失
        - factor_error: 因子值正常但判断仍错
        """
        dimension_factors = snapshot.get("dimension_factors") or {}
        factor_values = snapshot.get("factor_values") or {}

        factors_info: dict[str, dict] = {}
        has_weight_anomaly = False
        has_missing_value = False

        for factor_name, weight in (dimension_factors.get(wrong_dim) or {}).items():
            try:
                w = float(weight)
            except (TypeError, ValueError):
                w = 0.0
            value = factor_values.get(factor_name)
            weight_anomaly = w > 0.8 or w < 0.05
            value_anomaly = value is None or value == 0
            if weight_anomaly:
                has_weight_anomaly = True
            if value is None:
                has_missing_value = True
            factors_info[factor_name] = {
                "weight": w,
                "value": value,
                "weight_anomaly": weight_anomaly,
                "value_anomaly": value_anomaly,
            }

        if has_weight_anomaly:
            root_cause_candidate = "weight_error"
        elif has_missing_value:
            root_cause_candidate = "data_error"
        else:
            root_cause_candidate = "factor_error"

        return {
            "dimension": wrong_dim,
            "factors": factors_info,
            "root_cause_candidate": root_cause_candidate,
        }

    def _analyze_root_cause(self, per_dim_correctness: dict[str, bool],
                             snapshot: dict, outcome: dict) -> tuple[str, str]:
        """根因分类。优先使用证据链回溯，回退到错误比例启发式。"""
        wrong_dims = [d for d, c in per_dim_correctness.items() if not c]
        total = len(per_dim_correctness)

        if not wrong_dims:
            return "所有维度判断正确", "unknown"

        # 优先：证据链回溯（需要 dimension_factors）
        dimension_factors = snapshot.get("dimension_factors") or {}
        if dimension_factors:
            candidates = []
            for dim in wrong_dims:
                evidence = self._evidence_trace(snapshot, dim)
                candidates.append(evidence["root_cause_candidate"])

            if candidates:
                # 多数投票决定 root_cause_type
                from collections import Counter
                counter = Counter(candidates)
                root_cause_type = counter.most_common(1)[0][0]
                return (
                    f"维度{','.join(wrong_dims)}判断错误，"
                    f"证据链根因: {root_cause_type}",
                    root_cause_type,
                )

        # 回退：错误比例启发式
        wrong_ratio = len(wrong_dims) / total if total > 0 else 0

        # 多数维度判断错 → 可能是权重问题（主导维度权重不足）
        if wrong_ratio >= 0.5:
            return (f"多数维度({len(wrong_dims)}/{total})判断错误，"
                    f"可能是维度权重分配不当", "weight_error")

        # 少数维度判断错 → 可能是该维度因子计算问题
        if wrong_ratio < 0.5:
            return (f"少数维度({','.join(wrong_dims)})判断错误，"
                    f"可能是因子计算或数据源问题", "factor_error")

        return "判断错误原因待查", "unknown"

    def _recommend_action(self, wrong_dims: list[str], root_cause_type: str,
                          outcome: dict) -> str:
        """建议优化动作。"""
        if not wrong_dims:
            return "no_adjustment"

        real_outcome = str(outcome.get("real_outcome", "")).upper()

        # 亏损且有错误维度 → 降权
        if real_outcome == "SL":
            if root_cause_type == "weight_error":
                return f"降低错误维度权重: {wrong_dims}"
            if root_cause_type == "factor_error":
                return f"审计错误维度因子: {wrong_dims}"
            return f"检查维度: {wrong_dims}"

        # 盈利但有错误维度 → 假成功，谨慎处理
        if real_outcome == "TP":
            return f"记录假成功案例(维度错但盈利): {wrong_dims}"

        return f"监控维度: {wrong_dims}"

    def _neutral_result(self, snapshot: dict, outcome: dict,
                        reason: str) -> ReverseDeriveResult:
        """FAIL-OPEN 中性结果。"""
        return ReverseDeriveResult(
            per_dimension_correctness={},
            per_dimension_cs={},
            wrong_dimensions=[],
            wrong_dimension_pattern="",
            root_cause=f"reverse_derive_failed: {reason}",
            root_cause_type="unknown",
            confidence=0.0,
            known_gaps=[f"逆向推导失败: {reason}"],
            optimization_action="no_adjustment",
        )


# ======================================================================
# 架构域 ReverseDeriver（P3-1，独立于交易域）
# SPEC: reports/SPEC-P3-1-架构级ReverseDeriver.md
# 从 REA 架构 Evidence（文件行数/出度/豁口数/git演化类型）反推设计债务。
# 与交易域 ReverseDeriver 接口隔离，仅共享 Evidence 数据结构概念。
# ======================================================================

import re  # noqa: E402  架构域解析需要


@dataclass
class ArchitectureDebtResult:
    """架构债务推导结果。"""
    debt_dimensions: dict[str, float] = field(default_factory=dict)
    triggered_windows: list[str] = field(default_factory=list)
    refactor_plan: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    known_gaps: list[str] = field(default_factory=list)


# 维度 → (analysis 关键词, 阈值, 解析正则, 债务评分函数)
# 硬约束来源：SPEC-自进化系统逆向解析改进.md §5 H-1~H-6
_DIMENSION_RULES = {
    "file_size": {
        "keywords": ("line_count", "size_audit"),
        "threshold": 800,
        "pattern": r"(\d+)\s*行",
        "action": "拆分",
    },
    "out_degree": {
        "keywords": ("out_degree", "dependency_graph"),
        "threshold": 10,
        "pattern": r"出度[:：]\s*(\d+)",
        "action": "拆分",
    },
    "known_gaps": {
        "keywords": ("known_gap_audit", "fail_open_audit"),
        "threshold": 20,
        "pattern": r"豁口[:：]\s*(\d+)",
        "action": "补 known_gap 还款",
    },
    "git_evolution": {
        "keywords": ("git_history",),
        "threshold": 1.0,  # feat/(feat+refactor) 比值
        "pattern": r"(\d+)\s*feat\s*/\s*(\d+)\s*refactor",
        "action": "增加 refactor 提交",
    },
}


class ArchitectureReverseDeriver:
    """架构域逆向推导器：从架构 Evidence 反推设计债务，触发 refactor 窗口。

    四维度（SPEC §4）：
    1. 文件行数 → H-1: >800 触发 refactor
    2. 出度 → H-2: >10 触发拆分
    3. 豁口数 → H-3/H-4: 登记 + 30天 SLA
    4. git 演化 → H-6: 禁止断裂修复（无 refactor 即债务）

    与交易域 ReverseDeriver 接口隔离，不互相调用。
    """

    def derive_architecture_debt(
        self, evidence_list: list[Any] | None
    ) -> ArchitectureDebtResult:
        """从架构 Evidence 列表推导设计债务。

        Args:
            evidence_list: REA 产出的架构 Evidence 列表（含 result/provenance）

        Returns:
            ArchitectureDebtResult（FAIL-OPEN：空/解析失败返回空结果+known_gaps）
        """
        result = ArchitectureDebtResult()
        if not evidence_list:
            result.known_gaps.append("无架构 Evidence 输入")
            return result

        dim_scores: dict[str, list[tuple[float, str]]] = {}

        for ev in evidence_list:
            try:
                analysis = self._get_analysis(ev)
                result_str = self._get_result(ev)
                target = self._get_target(ev)
                if not analysis or result_str is None:
                    continue

                dim, score = self._parse_dimension(analysis, result_str)
                if dim is not None:
                    dim_scores.setdefault(dim, []).append((score, target))
            except Exception as e:
                eid = getattr(ev, "evidence_id", "unknown")
                result.known_gaps.append(f"Evidence {eid} 解析失败: {e}")

        # 聚合：每维度取最大债务评分
        for dim, entries in dim_scores.items():
            max_score = max(s for s, _ in entries)
            max_target = next(t for s, t in entries if s == max_score)
            result.debt_dimensions[dim] = round(min(max_score, 1.0), 4)

            if max_score >= 1.0:  # value >= threshold → 触发 refactor 窗口
                window_id = f"refactor:{dim}:{max_target}"
                result.triggered_windows.append(window_id)
                priority = "P0" if max_score >= 1.0 else (
                    "P1" if max_score >= 0.8 else "P2"
                )
                result.refactor_plan.append({
                    "dimension": dim,
                    "target": max_target,
                    "score": result.debt_dimensions[dim],
                    "action": _DIMENSION_RULES[dim]["action"],
                    "priority": priority,
                })

        # refactor_plan 按 score 降序
        result.refactor_plan.sort(key=lambda x: x["score"], reverse=True)

        if result.debt_dimensions:
            # 置信度：有数据的维度占比
            result.confidence = round(
                len(result.debt_dimensions) / len(_DIMENSION_RULES), 3
            )

        return result

    # ------------------------------------------------------------------
    @staticmethod
    def _get_analysis(ev: Any) -> str:
        prov = getattr(ev, "provenance", None)
        if isinstance(prov, dict):
            return str(prov.get("analysis", ""))
        return ""

    @staticmethod
    def _get_result(ev: Any) -> str:
        res = getattr(ev, "result", None)
        return str(res) if res is not None else ""

    @staticmethod
    def _get_target(ev: Any) -> str:
        prov = getattr(ev, "provenance", None)
        if isinstance(prov, dict):
            return str(prov.get("file") or prov.get("target") or "unknown")
        return "unknown"

    def _parse_dimension(
        self, analysis: str, result_str: str
    ) -> tuple[str | None, float]:
        """根据 analysis 关键词匹配维度，从 result_str 解析数值并算债务评分。"""
        for dim, rule in _DIMENSION_RULES.items():
            if any(kw in analysis for kw in rule["keywords"]):
                if dim == "git_evolution":
                    m = re.search(rule["pattern"], result_str)
                    if not m:
                        return None, 0.0
                    feat = int(m.group(1))
                    ref = int(m.group(2))
                    total = feat + ref
                    if total == 0:
                        return None, 0.0
                    return dim, feat / total
                m = re.search(rule["pattern"], result_str)
                if not m:
                    return None, 0.0
                value = float(m.group(1))
                threshold = rule["threshold"]
                return dim, value / threshold
        return None, 0.0
