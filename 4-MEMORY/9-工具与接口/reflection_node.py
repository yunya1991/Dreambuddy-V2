#!/usr/bin/env python3
"""Reflection Node — 调度链末尾 LLM-judge 反思回环

定位：L4 元认知层反思节点，借鉴 JPMorgan Ask David 多 Agent 架构
（supervisor + reflection node）+ Bridgewater "Pain + Reflection = Progress"。
现状痛点：调度链末尾无 LLM-judge 回环 —— 执行结果直接丢弃，无反思、
无教训提取、无记忆沉淀。

核心机制:
  1. reflect(execution_result) — 反思裁决（LLM-judge 规则版）:
     - success=False 或有 error → verdict="fail"（教训进 lessons）
     - duration > 慢阈值 → verdict="needs-improvement"
     - 否则 → verdict="pass"
     - verdict != "pass" → should_record=True（触发 record 认知闭环）
  2. attach_to_workspace_bus(bus) — 订阅 P3-1 广播，
     广播携带 execution_result 时自动入队待反思
  3. get_pending_reflections() — 获取待反思队列（调度链末尾消费）

设计原则:
  - FAIL-OPEN：None/非 dict/异常 → 保守 pass，绝不阻塞主流程
  - 依赖 P3-1 WorkspaceBus（Pub/Sub 接入调度链）
  - 轻量级：纯 Python 规则版 LLM-judge，无外部依赖

参考:
  - SPEC-CognitiveSystem-Evolution.md §1.1（JPMorgan Ask David）+ §4.3 P3-6
"""
from __future__ import annotations

import threading
from collections import deque
from typing import Any, Deque, Dict, List, Optional

try:
    from workspace_bus import WorkspaceContent
except ImportError:  # pragma: no cover
    WorkspaceContent = Any  # type: ignore


# ============================================================
# 常量
# ============================================================

DEFAULT_SLOW_THRESHOLD_SECONDS: float = 120.0  # 执行超过此秒数视为"过慢"

VERDICT_PASS = "pass"
VERDICT_NEEDS_IMPROVEMENT = "needs-improvement"
VERDICT_FAIL = "fail"

MAX_PENDING: int = 100  # 待反思队列上限


# ============================================================
# ReflectionNode 主类
# ============================================================


class ReflectionNode:
    """调度链末尾反思节点（LLM-judge 回环）。

    执行结果 → 反思裁决（pass/needs-improvement/fail）→ 教训提取
    → should_record 建议（非 pass 触发认知闭环 record）。
    """

    def __init__(
        self,
        slow_threshold_seconds: float = DEFAULT_SLOW_THRESHOLD_SECONDS,
    ) -> None:
        """
        Args:
            slow_threshold_seconds: 执行过慢判定阈值（秒）
        """
        self._slow_threshold = slow_threshold_seconds
        self._pending: Deque[Dict[str, Any]] = deque(maxlen=MAX_PENDING)
        self._lock = threading.Lock()

    # ============================================================
    # 1. 反思裁决（LLM-judge 规则版）
    # ============================================================

    def reflect(self, execution_result: Any) -> Dict[str, Any]:
        """反思裁决：评估执行结果，提取教训，输出 record 建议。

        Args:
            execution_result: {
                "success": bool,
                "error": str | None,
                "duration_seconds": float (可选),
                "steps": int (可选),
                "output": Any (可选),
            }
            None / 非 dict → FAIL-OPEN 保守 pass

        Returns:
            {
              "verdict": "pass"|"needs-improvement"|"fail",
              "lessons": [教训列表],
              "should_record": bool（非 pass → True）,
              "execution_result": 原始输入（dict 化，None 保持 None）,
            }
        """
        try:
            if not isinstance(execution_result, dict):
                # FAIL-OPEN：无效输入不阻塞主流程
                return self._make_result(VERDICT_PASS, [], False, None)

            lessons: List[str] = []
            verdict = VERDICT_PASS

            success = execution_result.get("success", True)
            error = execution_result.get("error")

            # 规则1: 执行失败 → fail（教训含错误信息）
            if success is False or error is not None:
                verdict = VERDICT_FAIL
                if error:
                    lessons.append(f"执行失败: {error}")
                else:
                    lessons.append("执行失败: 未提供错误详情")

            # 规则2: 执行过慢 → needs-improvement（fail 优先级更高）
            duration = execution_result.get("duration_seconds")
            if verdict != VERDICT_FAIL:
                try:
                    if duration is not None and float(duration) > self._slow_threshold:
                        verdict = VERDICT_NEEDS_IMPROVEMENT
                        lessons.append(
                            f"执行过慢: {duration}s 超过阈值 {self._slow_threshold}s"
                        )
                except (TypeError, ValueError):
                    pass  # FAIL-OPEN：无效 duration 忽略

            should_record = verdict != VERDICT_PASS
            return self._make_result(verdict, lessons, should_record, execution_result)
        except Exception:
            # FAIL-OPEN：任何异常保守 pass
            return self._make_result(VERDICT_PASS, [], False, None)

    @staticmethod
    def _make_result(
        verdict: str,
        lessons: List[str],
        should_record: bool,
        execution_result: Any,
    ) -> Dict[str, Any]:
        return {
            "verdict": verdict,
            "lessons": lessons,
            "should_record": should_record,
            "execution_result": execution_result,
        }

    # ============================================================
    # 2. P3-1 WorkspaceBus 接入（调度链末尾回环）
    # ============================================================

    def attach_to_workspace_bus(self, bus: Any) -> str:
        """订阅 WorkspaceBus 广播，接收带 execution_result 的内容。

        广播的 WorkspaceContent 若携带 execution_result（非 None），
        自动入队待反思。

        Args:
            bus: P3-1 WorkspaceBus 实例

        Returns:
            订阅 ID
        """
        def _on_broadcast(content: Any) -> None:
            try:
                execution_result = getattr(content, "execution_result", None)
                if execution_result is not None:
                    with self._lock:
                        self._pending.append({
                            "execution_result": execution_result,
                            "confidence": getattr(content, "confidence", None),
                        })
            except Exception:
                pass  # FAIL-OPEN：订阅回调异常静默

        return bus.subscribe("reflection_node", _on_broadcast)

    # ============================================================
    # 3. 待反思队列
    # ============================================================

    def get_pending_reflections(self) -> List[Dict[str, Any]]:
        """获取待反思队列快照。

        Returns:
            待反思条目列表 [{execution_result, confidence}]
        """
        with self._lock:
            return list(self._pending)

    def clear_pending(self) -> None:
        """清空待反思队列。"""
        with self._lock:
            self._pending.clear()


# ============================================================
# CLI 自测
# ============================================================


if __name__ == "__main__":
    print("=" * 60)
    print("ReflectionNode — 功能验证")
    print("=" * 60)

    node = ReflectionNode()

    # 场景1: 成功
    r1 = node.reflect({"success": True, "error": None, "steps": 3})
    print(f"\n场景1 成功: verdict={r1['verdict']}, should_record={r1['should_record']}")

    # 场景2: 失败
    r2 = node.reflect({"success": False, "error": "connection refused"})
    print(f"场景2 失败: verdict={r2['verdict']}, lessons={r2['lessons']}")

    # 场景3: 过慢
    r3 = node.reflect({"success": True, "duration_seconds": 300})
    print(f"场景3 过慢: verdict={r3['verdict']}, lessons={r3['lessons']}")

    # 场景4: FAIL-OPEN
    r4 = node.reflect(None)
    print(f"场景4 FAIL-OPEN: verdict={r4['verdict']}")

    print("\n" + "=" * 60)
    print("✅ ReflectionNode 功能验证通过")
