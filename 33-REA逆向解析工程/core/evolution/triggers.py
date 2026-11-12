"""Trigger Engine — T-G7 六类触发器 + v0.4.0 两类扩展

SPEC-33-G：
  - §1 G-G7：6 类触发器
  - §2.3 `rea_evolution.yaml` 阈值（version=2；新增 capability_gap / case_pattern）
  - 纯函数输入 signals，不读文件、不写账本；触发结论由 T-G9 控制器消费

工程约束：纯标准库；确定性输出顺序；阈值全部来自配置，不写死。
"""

from __future__ import annotations

from typing import Any, Dict, List

DEFAULT_CONFIG: Dict[str, Any] = {
    "version": 2,
    "window_days": 7,
    "triggers": {
        "repeat_failure": {"min_occurrences": 3},
        "hypothesis_overturned": {"min_consecutive": 2},
        "memory_saturation": {"min_count": 20, "min_idle_days": 30},
        "metric_drift": {
            "cycles_pct": 30,
            "god_components_pct": 30,
            "fan_out_pct": 30,
        },
        "coverage_gap": {"min_occurrences": 5},
        "adoption_drop": {"pct": 20},
        "capability_gap": {"min_references": 2, "min_relevance": 0.6},
        "case_pattern": {"min_cases": 5, "min_distinct_iterations": 3},
    },
}


class TriggerEngine:
    """按 §2.3 阈值评估演化信号，产出触发结论列表。"""

    def __init__(self, config: Dict[str, Any] | None = None):
        self.config = config or DEFAULT_CONFIG
        self.thresholds = self.config.get("triggers") or {}
        self.window_days = int(self.config.get("window_days") or 7)

    def evaluate(self, signals: Dict[str, Any]) -> List[Dict[str, Any]]:
        signals = signals or {}
        fired: List[Dict[str, Any]] = []
        fired.extend(self._repeat_failure(signals.get("failures") or []))
        fired.extend(self._hypothesis_overturned(signals.get("hypotheses") or []))
        fired.extend(self._memory_saturation(signals.get("memories") or {}))
        fired.extend(self._metric_drift(signals.get("metrics") or {}))
        fired.extend(self._coverage_gap(signals.get("coverage") or []))
        fired.extend(self._adoption_drop(signals.get("adoption") or []))
        fired.extend(self._capability_gap(signals.get("references") or []))
        fired.extend(self._case_pattern(signals.get("cases") or []))
        return fired

    # ---------- 触发器 ----------

    def _repeat_failure(self, failures: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        threshold = int((self.thresholds.get("repeat_failure") or {}).get("min_occurrences", 3))
        groups: Dict[tuple, List[Dict[str, Any]]] = {}
        for item in failures:
            key = (str(item.get("signature") or "unknown"), str(item.get("section") or ""))
            groups.setdefault(key, []).append(item)
        fired = []
        for (signature, section), items in groups.items():
            if len(items) >= threshold:
                fired.append(
                    self._hit("repeat_failure", signature, len(items), threshold, section, items)
                )
        return fired

    def _hypothesis_overturned(self, hypotheses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        threshold = int(
            (self.thresholds.get("hypothesis_overturned") or {}).get("min_consecutive", 2)
        )
        best: List[Dict[str, Any]] = []
        current: List[Dict[str, Any]] = []
        for item in hypotheses:
            if item.get("status") == "overturned":
                current.append(item)
                if len(current) > len(best):
                    best = list(current)
            else:
                current = []
        if len(best) < threshold:
            return []
        section = str(best[-1].get("section") or "")
        evidence = [str(item.get("hypothesis_id") or "") for item in best]
        return [
            self._hit(
                "hypothesis_overturned", "hypothesis", len(best), threshold, section, evidence
            )
        ]

    def _memory_saturation(self, memories: Dict[str, Any]) -> List[Dict[str, Any]]:
        config = self.thresholds.get("memory_saturation") or {}
        min_count = int(config.get("min_count", 20))
        min_idle = int(config.get("min_idle_days", 30))
        count = int(memories.get("count") or 0)
        idle_days = int(memories.get("idle_days") or 0)
        if count >= min_count and idle_days >= min_idle:
            return [self._hit("memory_saturation", "memory", count, min_count, "", [])]
        return []

    def _metric_drift(self, metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
        config = self.thresholds.get("metric_drift") or {}
        fired = []
        for metric, threshold in config.items():
            value = metrics.get(metric)
            if value is None:
                continue
            if float(value) >= float(threshold):
                fired.append(
                    self._hit("metric_drift", metric, float(value), float(threshold), "", [])
                )
        return fired

    def _coverage_gap(self, coverage: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        threshold = int((self.thresholds.get("coverage_gap") or {}).get("min_occurrences", 5))
        fired = []
        for item in coverage:
            occurrences = int(item.get("occurrences") or 0)
            if occurrences >= threshold:
                fired.append(
                    self._hit(
                        "coverage_gap",
                        str(item.get("capability") or "unknown"),
                        occurrences,
                        threshold,
                        str(item.get("section") or ""),
                        [],
                    )
                )
        return fired

    def _adoption_drop(self, adoption: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        threshold = float((self.thresholds.get("adoption_drop") or {}).get("pct", 20))
        fired = []
        for item in adoption:
            previous = float(item.get("previous_rate") or 0.0)
            current = float(item.get("current_rate") or 0.0)
            if previous <= 0:
                continue
            drop_pct = (previous - current) / previous * 100.0
            if drop_pct >= threshold:
                fired.append(
                    self._hit(
                        "adoption_drop",
                        str(item.get("section") or "global"),
                        int(round(drop_pct)),
                        threshold,
                        str(item.get("section") or ""),
                        [],
                    )
                )
        return fired

    def _capability_gap(self, references: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        config = self.thresholds.get("capability_gap") or {}
        min_references = int(config.get("min_references", 2))
        min_relevance = float(config.get("min_relevance", 0.6))
        groups: Dict[str, List[str]] = {}
        for item in references:
            license_name = str(item.get("license") or "").strip()
            if not license_name or license_name.lower() == "unknown":
                continue
            if float(item.get("stack_fit") or 0.0) < min_relevance:
                continue
            capability = str(item.get("capability") or "").strip()
            if not capability:
                continue
            groups.setdefault(capability, []).append(str(item.get("source_url") or capability))
        fired = []
        for capability, evidence in groups.items():
            if len(evidence) >= min_references:
                fired.append(
                    self._hit(
                        "capability_gap",
                        capability,
                        len(evidence),
                        min_references,
                        "",
                        evidence,
                    )
                )
        return fired

    def _case_pattern(self, cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        config = self.thresholds.get("case_pattern") or {}
        min_cases = int(config.get("min_cases", 5))
        min_iterations = int(config.get("min_distinct_iterations", 3))
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for item in cases:
            pattern = str(item.get("pattern") or "").strip()
            if pattern:
                groups.setdefault(pattern, []).append(item)
        fired = []
        for pattern, items in groups.items():
            iterations = {str(item.get("iteration_id") or "") for item in items}
            if len(items) >= min_cases and len(iterations) >= min_iterations:
                evidence = [str(item.get("case_id") or "") for item in items]
                fired.append(
                    self._hit("case_pattern", pattern, len(items), min_cases, "", evidence)
                )
        return fired

    # ---------- 输出 ----------

    def _hit(
        self,
        trigger: str,
        key: str,
        occurrences: float,
        threshold: float,
        section: str,
        evidence: List[Any],
    ) -> Dict[str, Any]:
        return {
            "trigger": trigger,
            "key": key,
            "section": section,
            "occurrences": occurrences,
            "threshold": threshold,
            "window_days": self.window_days,
            "evidence": list(evidence),
        }
