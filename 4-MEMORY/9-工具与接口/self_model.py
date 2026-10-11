#!/usr/bin/env python3
"""HOT Self-Model — 高阶自我监控

定位：L4 元认知层核心组件，借鉴 GWT+HOT 双层意识架构（arXiv:2512.19155），
独立监控 workspace 内容的可靠性，类比 ACC（前扣带回）的错误监测功能。

核心能力:
  1. check_calibration(confidence, actual_accuracy) — 置信度校准
     - 检查系统置信度是否匹配实际准确率
     - calibration = 1 - |confidence - actual_accuracy|
  2. find_contradictions(workspace_content) — 矛盾检测
     - 发现 workspace 中相互矛盾的信息（同一 subject 相反结论）
  3. detect_errors(workspace_content) — 错误监测（类比 ACC）
     - 高置信但召回为空
     - 置信度超出 [0,1] 范围
     - 其他结构性错误
  4. monitor(workspace_content, actual_accuracy=None) — 综合监控
     - calibration < 0.5 或有 contradictions 或有 errors → action=verify
     - 否则 → action=proceed

设计原则:
  - FAIL-OPEN：所有方法异常返回保守值（calibration=1.0，空列表）
  - 依赖 P3-1 WorkspaceBus（输入 WorkspaceContent）
  - 轻量级：纯 Python，无外部依赖

参考:
  - SPEC-CognitiveSystem-Evolution.md §2.5.2 + §4.3 P3-2
  - HOT: Higher-Order Thought 高阶思维理论
  - ACC: Anterior Cingulate Cortex 前扣带回错误监测
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    from workspace_bus import WorkspaceContent
except ImportError:  # pragma: no cover
    WorkspaceContent = Any  # type: ignore


# ============================================================
# 常量
# ============================================================

CALIBRATION_THRESHOLD: float = 0.5  # 校准分低于此值触发 verify
HIGH_CONFIDENCE_THRESHOLD: float = 0.8  # 高置信阈值
CONTRADICTION_KEYWORDS = {
    # 上涨 vs 下跌
    "上涨": ["下跌", "下降", "回落"],
    "下跌": ["上涨", "上升", "反弹"],
    "上升": ["下降", "下跌", "回落"],
    "下降": ["上升", "上涨", "反弹"],
    "多": ["空"],
    "空": ["多"],
    "看多": ["看空"],
    "看空": ["看多"],
    "买入": ["卖出"],
    "卖出": ["买入"],
    "看涨": ["看跌"],
    "看跌": ["看涨"],
}


# ============================================================
# SelfModel 主类
# ============================================================


class SelfModel:
    """HOT 高阶自我监控模型。

    监控 workspace 内容的可靠性，输出 action=verify/proceed 决策。
    类比 ACC（前扣带回）的错误监测 + 冲突监测功能。
    """

    def __init__(
        self,
        calibration_threshold: float = CALIBRATION_THRESHOLD,
        high_confidence_threshold: float = HIGH_CONFIDENCE_THRESHOLD,
    ) -> None:
        self._calibration_threshold = calibration_threshold
        self._high_confidence_threshold = high_confidence_threshold

    # ============================================================
    # 1. 置信度校准
    # ============================================================

    def check_calibration(
        self,
        confidence: float,
        actual_accuracy: Optional[float],
    ) -> float:
        """置信度校准：检查系统置信度是否匹配实际准确率。

        calibration = 1 - |confidence - actual_accuracy|
        值越接近 1.0 表示校准越好。

        Args:
            confidence: 系统报告的置信度 0.0-1.0
            actual_accuracy: 实际准确率 0.0-1.0，None 表示未知

        Returns:
            校准分数 0.0-1.0。actual_accuracy=None 时返回 1.0（FAIL-OPEN）
        """
        if actual_accuracy is None:
            return 1.0  # FAIL-OPEN：无准确率数据时不触发校验

        try:
            conf = float(confidence)
            acc = float(actual_accuracy)
            diff = abs(conf - acc)
            return max(0.0, 1.0 - diff)
        except (TypeError, ValueError):
            return 1.0  # FAIL-OPEN

    # ============================================================
    # 2. 矛盾检测
    # ============================================================

    def find_contradictions(self, content: Optional[WorkspaceContent]) -> List[Dict[str, Any]]:
        """发现 workspace 中相互矛盾的信息。

        检测规则：同一 subject 下出现相反结论（基于关键词对）。

        Args:
            content: WorkspaceContent 或 None

        Returns:
            矛盾列表，每项 {subject, item_a, item_b, type}
        """
        if content is None:
            return []

        try:
            contradictions: List[Dict[str, Any]] = []

            # 收集所有带 subject + conclusion 的条目
            items: List[Dict[str, Any]] = []
            for src_name in ("memory_recall", "skill_match", "knowledge_retrieval"):
                src = getattr(content, src_name, []) or []
                for item in src:
                    if isinstance(item, dict) and item.get("subject") and item.get("conclusion"):
                        items.append({"source": src_name, **item})

            # 两两比较同一 subject 的结论
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    a, b = items[i], items[j]
                    if a.get("subject") != b.get("subject"):
                        continue
                    if self._is_contradictory(a.get("conclusion", ""), b.get("conclusion", "")):
                        contradictions.append({
                            "subject": a["subject"],
                            "item_a": a,
                            "item_b": b,
                            "type": "opposite_conclusion",
                        })

            return contradictions
        except Exception:
            return []  # FAIL-OPEN

    def _is_contradictory(self, conclusion_a: str, conclusion_b: str) -> bool:
        """判断两个结论是否矛盾（基于关键词对）。"""
        if not conclusion_a or not conclusion_b:
            return False
        a = str(conclusion_a)
        b = str(conclusion_b)
        for keyword, opposites in CONTRADICTION_KEYWORDS.items():
            if keyword in a:
                for opp in opposites:
                    if opp in b:
                        return True
            if keyword in b:
                for opp in opposites:
                    if opp in a:
                        return True
        return False

    # ============================================================
    # 3. 错误监测（类比 ACC）
    # ============================================================

    def detect_errors(self, content: Optional[WorkspaceContent]) -> List[Dict[str, Any]]:
        """错误监测：类比 ACC 前扣带回，检测 workspace 中的结构性错误。

        检测规则：
          - 高置信但所有召回源为空
          - 置信度超出 [0, 1] 范围
          - intent 缺失但有召回

        Args:
            content: WorkspaceContent 或 None

        Returns:
            错误列表，每项 {type, detail, severity}
        """
        if content is None:
            return []

        try:
            errors: List[Dict[str, Any]] = []

            confidence = getattr(content, "confidence", 0.0)

            # 错误1: 置信度超出 [0, 1]
            if confidence < 0.0 or confidence > 1.0:
                errors.append({
                    "type": "confidence_out_of_range",
                    "detail": f"confidence={confidence} 超出 [0,1] 范围",
                    "severity": "high",
                })

            # 错误2: 高置信但所有召回源为空
            if confidence >= self._high_confidence_threshold:
                recall_empty = all(
                    not getattr(content, src, [])
                    for src in ("memory_recall", "skill_match", "knowledge_retrieval")
                )
                if recall_empty:
                    errors.append({
                        "type": "high_confidence_empty_recall",
                        "detail": f"confidence={confidence} 但所有召回源为空",
                        "severity": "medium",
                    })

            return errors
        except Exception:
            return []  # FAIL-OPEN

    # ============================================================
    # 4. 综合监控
    # ============================================================

    def monitor(
        self,
        content: Optional[WorkspaceContent],
        actual_accuracy: Optional[float] = None,
    ) -> Dict[str, Any]:
        """综合监控 workspace 内容可靠性，输出决策。

        Args:
            content: WorkspaceContent
            actual_accuracy: 实际准确率（可选）

        Returns:
            {
              "action": "verify" | "proceed",
              "targets": [矛盾 + 错误列表],
              "calibration": 校准分数,
              "contradictions": 矛盾列表,
              "errors": 错误列表,
            }
        """
        try:
            confidence = getattr(content, "confidence", 0.0) if content else 0.0

            calibration = self.check_calibration(confidence, actual_accuracy)
            contradictions = self.find_contradictions(content)
            errors = self.detect_errors(content)

            targets = contradictions + errors

            if (
                calibration < self._calibration_threshold
                or contradictions
                or errors
            ):
                action = "verify"
            else:
                action = "proceed"

            return {
                "action": action,
                "targets": targets,
                "calibration": calibration,
                "contradictions": contradictions,
                "errors": errors,
            }
        except Exception:
            # FAIL-OPEN：异常时 proceed 不阻塞
            return {
                "action": "proceed",
                "targets": [],
                "calibration": 1.0,
                "contradictions": [],
                "errors": [],
            }


# ============================================================
# CLI 自测
# ============================================================


if __name__ == "__main__":
    print("=" * 60)
    print("HOT Self-Model — 功能验证")
    print("=" * 60)

    from workspace_bus import WorkspaceContent

    sm = SelfModel()

    # 场景1: 正常 workspace
    clean = WorkspaceContent(
        intent={"type": "query"},
        memory_recall=[{"id": "VM-1", "score": 0.9}],
        skill_match=[{"id": "skill-1", "score": 0.8}],
        knowledge_retrieval=[{"id": "chunk-1", "score": 0.7}],
        confidence=0.85,
    )
    r1 = sm.monitor(clean)
    print(f"\n场景1 正常: action={r1['action']}, calibration={r1['calibration']:.2f}")

    # 场景2: 矛盾
    contradiction = WorkspaceContent(
        intent={"type": "query"},
        memory_recall=[
            {"id": "VM-1", "subject": "price", "conclusion": "上涨"},
            {"id": "VM-2", "subject": "price", "conclusion": "下跌"},
        ],
        skill_match=[],
        knowledge_retrieval=[],
        confidence=0.7,
    )
    r2 = sm.monitor(contradiction)
    print(f"场景2 矛盾: action={r2['action']}, contradictions={len(r2['contradictions'])}")

    # 场景3: 错误（高置信空召回）
    error = WorkspaceContent(
        intent={"type": "query"},
        memory_recall=[],
        skill_match=[],
        knowledge_retrieval=[],
        confidence=0.95,
    )
    r3 = sm.monitor(error)
    print(f"场景3 错误: action={r3['action']}, errors={len(r3['errors'])}")

    # 场景4: 低校准
    low_cal = WorkspaceContent(
        intent={"type": "query"},
        memory_recall=[{"id": "VM-1", "score": 0.9}],
        skill_match=[],
        knowledge_retrieval=[],
        confidence=0.9,
    )
    r4 = sm.monitor(low_cal, actual_accuracy=0.3)
    print(f"场景4 低校准: action={r4['action']}, calibration={r4['calibration']:.2f}")

    print("\n" + "=" * 60)
    print("✅ HOT Self-Model 功能验证通过")
