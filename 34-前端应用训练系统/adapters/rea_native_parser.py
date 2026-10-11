"""33-REA 原生解析器适配器。

通过直接 Python import 调用 33-REA逆向解析工程/dsh_nodes.py，
实现 REAParser 协议，为被动训练提供算法模式和调用链解析。

设计:
  - 直接 import dsh_nodes（Python-to-Python，无 IPC 开销）
  - sys.path 注入 33-REA 目录（复刻 dsh_nodes.py 的 path 注入模式）
  - S33 输出 → REAParseResult 转换
  - FAIL-OPEN：import 失败/分析异常 → 空 REAParseResult
"""
import os
import sys
from typing import Optional

# sys.path 注入：34 目录 + 33-REA 目录
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
_REA_DIR = os.path.join(_PROJECT_ROOT, "33-REA逆向解析工程")

for _p in [_THIS_DIR, os.path.dirname(_THIS_DIR), _REA_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from interfaces.rea_parser import REAParser, REAParseResult

# Evidence level 映射：33-REA EvidenceLevel → TDR evidence_level (L1-L4)
_EVIDENCE_LEVEL_MAP = {
    "observation": "L1",
    "derivation": "L2",
    "inference": "L3",
    "unknown": "L4",
}


class REANativeParser(REAParser):
    """33-REA 原生解析器。

    直接 import 33-REA 的 S33_rea_analyze 和 S33_rea_trace 函数，
    将其输出转换为 REAParseResult 供被动训练使用。
    """

    def __init__(self):
        self._rea_module = None

    def _get_rea(self):
        """延迟 import dsh_nodes，避免初始化时失败。"""
        if self._rea_module is None:
            try:
                import dsh_nodes
                self._rea_module = dsh_nodes
            except Exception:
                self._rea_module = None
        return self._rea_module

    def analyze(self, target_path: str, scope: str = "architecture") -> REAParseResult:
        """分析目标工程的架构和依赖。

        Args:
            target_path: 工程路径
            scope: 分析范围 (architecture/modules/dependencies/full)

        Returns:
            解析结果（含依赖图等），FAIL-OPEN 返回空结果
        """
        rea = self._get_rea()
        if rea is None:
            return REAParseResult(raw_evidence={"error": "rea_import_failed"})

        try:
            output = rea.S33_rea_analyze({
                "target": target_path,
                "scope": scope,
            })
            return self._convert_output(output, is_trace=False, target_path=target_path)
        except Exception as e:
            return REAParseResult(raw_evidence={"error": f"analyze_failed: {e}"})

    def trace(self, target_path: str, feature: str, entry: Optional[str] = None) -> REAParseResult:
        """追踪目标工程的功能调用链和算法模式。

        Args:
            target_path: 工程路径
            feature: 要追踪的功能描述
            entry: 可选入口函数/类名

        Returns:
            解析结果（含调用链、算法模式等），FAIL-OPEN 返回空结果

        Note:
            S33_rea_trace 当前不调用 algorithm_reducer，适配层在此补充调用，
            以提供完整的 algorithm_patterns（不修改 33-REA 核心逻辑）。
        """
        rea = self._get_rea()
        if rea is None:
            return REAParseResult(raw_evidence={"error": "rea_import_failed"})

        try:
            params = {"target": target_path, "feature": feature}
            if entry:
                params["entry"] = entry
            output = rea.S33_rea_trace(params)
            result = self._convert_output(output, is_trace=True, target_path=target_path)
            # 适配层补充：调用 33-REA 的 algorithm_reducer 增强 pattern 识别
            self._augment_with_algorithm_reducer(result, target_path, entry)
            return result
        except Exception as e:
            return REAParseResult(raw_evidence={"error": f"trace_failed: {e}"})

    def _augment_with_algorithm_reducer(
        self, result: REAParseResult, target_path: str, entry: Optional[str]
    ) -> None:
        """调用 33-REA algorithm_reducer 补充 algorithm_patterns。

        原地修改 result.algorithm_patterns，FAIL-OPEN。
        """
        try:
            from core.algorithm_reducer import reduce_algorithm
            import os
            # algorithm_reducer 仅支持单文件
            if not os.path.isfile(target_path):
                return
            reduced = reduce_algorithm(target_path, function_name=entry)
            patterns = reduced.get("patterns", []) or []
            for p in patterns:
                # algorithm_reducer 输出格式: {"type": "条件分支 conditional_branch", ...}
                p_type = p.get("type") or p.get("name") or str(p) if isinstance(p, dict) else str(p)
                # 提取英文名（最后一个 token）
                if p_type:
                    tokens = str(p_type).split()
                    p_name = tokens[-1] if tokens else str(p_type)
                    if p_name and p_name not in result.algorithm_patterns:
                        result.algorithm_patterns.append(p_name)
            # 合并 evidence（增强置信度）
            for e in reduced.get("evidence", []) or []:
                if hasattr(e, "to_dict"):
                    result.raw_evidence.setdefault("algorithm_evidence", []).append(e.to_dict())
        except Exception:
            # FAIL-OPEN：algorithm_reducer 不可用不影响主流程
            pass

    @staticmethod
    def _convert_output(output: dict, is_trace: bool, target_path: str = "") -> REAParseResult:
        """将 33-REA SubagentOutput 转换为 REAParseResult。

        S33_rea_analyze 输出:
            result.raw.dependencies → dependency_graph
            result.raw.call_graph → call_chain (扁平化)
            result.evidence[] → algorithm_patterns + evidence_level + confidence

        S33_rea_trace 输出:
            result.call_chain → call_chain
            result.evidence[] → evidence_level + confidence
            result.known_gaps → known_gaps
        """
        if not output.get("ok"):
            return REAParseResult(raw_evidence={"error": output.get("error", "unknown")})

        result = output.get("result", {})
        evidence_list = result.get("evidence", [])

        # 提取 evidence_level（取最高级别）和 confidence（取均值）
        levels = [
            _EVIDENCE_LEVEL_MAP.get(e.get("level", ""), "L3")
            for e in evidence_list
        ]
        evidence_level = min(levels, key=lambda l: int(l[1:])) if levels else "L3"
        confidences = [e.get("confidence", 0.5) for e in evidence_list]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5

        # 提取 known_gaps（从所有 evidence 汇总）
        known_gaps = []
        for e in evidence_list:
            known_gaps.extend(e.get("known_gaps", []))
        known_gaps.extend(result.get("known_gaps", []))

        # 提取 observations
        observations = []
        for e in evidence_list:
            observations.extend(e.get("observations", []))

        # 提取算法模式（从 evidence result 字符串中提取关键词）
        algorithm_patterns = []
        for e in evidence_list:
            res = str(e.get("result", ""))
            for pattern in ["recursion", "divide_conquer", "dynamic_programming",
                            "iteration", "accumulator", "backtracking", "greedy"]:
                if pattern in res.lower():
                    algorithm_patterns.append(pattern)

        # 提取 dependency_graph 和 call_chain
        raw = result.get("raw", {})
        dependency_graph = raw.get("dependencies", {})
        # 单文件场景：raw 无 dependencies，从 imports 构造简化版依赖图
        if not dependency_graph and raw.get("imports"):
            dep_from_imports = {}
            file_name = os.path.basename(target_path) if target_path else "module"
            for imp in raw["imports"]:
                if isinstance(imp, dict):
                    module = imp.get("module", "")
                    if module:
                        dep_from_imports.setdefault(file_name, []).append(module)
            dependency_graph = dep_from_imports
        call_graph = raw.get("call_graph", {})

        # call_chain: 从 call_graph 或 trace 结果中提取
        call_chain = []
        if is_trace:
            cc = result.get("call_chain", {})
            call_chain = cc.get("entry_chain", []) or list(cc.get("callees", {}).keys())
        else:
            # analyze 的 call_graph 有 callers/callees
            callees = call_graph.get("callees", {})
            call_chain = list(callees.keys()) if callees else []

        return REAParseResult(
            algorithm_patterns=list(set(algorithm_patterns)),
            call_chain=call_chain,
            dependency_graph=dependency_graph,
            known_gaps=list(set(known_gaps)),
            observations=observations,
            evidence_level=evidence_level,
            confidence=avg_confidence,
            raw_evidence=output,
        )
