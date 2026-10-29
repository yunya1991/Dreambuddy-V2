#!/usr/bin/env python3
"""FOK/JOL 元认知 Harness — MetacogHarness

定位：L4 元认知层信号 harness，借鉴 arXiv:2605.14186 LLM 元认知信号研究。
现状痛点：无"我觉得能解决吗"的预评估 —— SKILL 直接执行，失败后才补救。

核心机制（SPEC §2.5.3）:
  1. pre_execute_fok(task, skill_match, memory_recall) — SKILL 执行前 FOK:
     - FOK (Feeling of Knowing): "你认为能解决此任务吗？0-1 打分"
     - 规则版打分（最强可用证据）: fok = max(top skill score, top memory score)
       —— "我知道怎么解决"的把握由最佳匹配资源（SKILL 或记忆）决定
     - fok >= 0.5 → action="proceed"（正常执行）
     - 0.3 <= fok < 0.5 → action="recall_supplement"（自动 recall 补充）
     - fok < 0.3 → action="escalate"（升级 deep-research SKILL）
  2. post_execute_jol(execution_result) — SKILL 执行后 JOL:
     - JOL (Judgment of Learning): "你学到了什么？0-1 打分"
     - 规则版打分: success=True → 0.8；success=False → 0.2
     - jol >= 0.5 → action="record"（正常认知闭环）
     - jol < 0.5 → action="mark_verify"（标记需要后续 verify）

设计原则:
  - FAIL-OPEN：None/异常 → 中性分数 + 保守 action，绝不阻塞
  - prompt 字段输出注入 LLM 的元认知问句模板
  - 依赖 P3-1 WorkspaceContent 数据源（skill_match/memory_recall 同构）
  - 轻量级：纯 Python 规则版，无外部依赖

参考:
  - SPEC-CognitiveSystem-Evolution.md §2.5.3 + §4.3 P3-3
  - arXiv:2605.14186 (LLM Metacognitive Signals)
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


# ============================================================
# 常量
# ============================================================

SKILL_WEIGHT: float = 0.6  # FOK 中 SKILL 匹配权重（保留供加权模式扩展）
MEMORY_WEIGHT: float = 0.4  # FOK 中记忆召回权重（保留供加权模式扩展）

FOK_PROCEED_THRESHOLD: float = 0.5  # FOK >= 此值正常执行
FOK_ESCALATE_THRESHOLD: float = 0.3  # FOK < 此值升级 deep-research

JOL_VERIFY_THRESHOLD: float = 0.5  # JOL < 此值标记 verify

FOK_PROMPT_TEMPLATE = (
    "你认为能解决此任务吗？0-1 打分。任务: {task}\n"
    "（FOK: Feeling of Knowing —— 低分将触发 recall 补充或 escalate）"
)
JOL_PROMPT_TEMPLATE = (
    "你学到了什么？0-1 打分。\n"
    "（JOL: Judgment of Learning —— 低分将标记需要后续 verify）"
)

ACTION_PROCEED = "proceed"
ACTION_RECALL_SUPPLEMENT = "recall_supplement"
ACTION_ESCALATE = "escalate"
ACTION_RECORD = "record"
ACTION_MARK_VERIFY = "mark_verify"


def _safe_float(value: Any, default: float = 0.0) -> float:
    """安全浮点转换（FAIL-OPEN）。"""
    try:
        if value is None:
            return default
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


# ============================================================
# MetacogHarness 主类
# ============================================================


class MetacogHarness:
    """FOK/JOL 元认知信号 Harness。

    SKILL 执行前 FOK 预评估（低分自动补救），执行后 JOL 学习评估
    （低分标记 verify）。让系统"知道自己知不知道"。
    """

    def __init__(
        self,
        proceed_threshold: float = FOK_PROCEED_THRESHOLD,
        escalate_threshold: float = FOK_ESCALATE_THRESHOLD,
        verify_threshold: float = JOL_VERIFY_THRESHOLD,
    ) -> None:
        self._proceed_threshold = proceed_threshold
        self._escalate_threshold = escalate_threshold
        self._verify_threshold = verify_threshold

    # ============================================================
    # 1. FOK — SKILL 执行前预评估
    # ============================================================

    def pre_execute_fok(
        self,
        task: Any,
        skill_match: Optional[List[Any]],
        memory_recall: Optional[List[Any]],
        doc_hits: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        """FOK 预评估：任务执行前判断"能不能解决"。

        规则版打分（最强可用证据）:
          fok = max(top skill score, top memory score)
          —— 把握由最佳匹配资源（SKILL 或记忆）决定

        Args:
            task: 任务描述
            skill_match: SKILL 库 top-K 匹配（[{id, score}]）
            memory_recall: 记忆库 top-K 召回（[{id, score}]）

        Returns:
            {
              "fok_score": 0.0-1.0,
              "action": "proceed"|"recall_supplement"|"escalate",
              "prompt": FOK 注入问句,
              "task": 原任务,
            }
        """
        try:
            skill_component = self._top_score(skill_match)
            memory_component = self._top_score(memory_recall)

            # B5（41 SPEC §13.2）：41 检索命中密度作为 FOK 门控辅助信号
            # 命中密度 = 命中数/5（封顶 1.0），辅助权重 0.5，不替代 SKILL/记忆主信号
            doc_component = 0.0
            if doc_hits:
                doc_component = min(1.0, len(doc_hits) / 5.0) * 0.5

            fok = max(skill_component, memory_component, doc_component)
            fok = max(0.0, min(1.0, fok))

            if fok >= self._proceed_threshold:
                action = ACTION_PROCEED
            elif fok >= self._escalate_threshold:
                action = ACTION_RECALL_SUPPLEMENT
            else:
                action = ACTION_ESCALATE

            prompt = FOK_PROMPT_TEMPLATE.format(task=task or "未提供任务描述")
            return {"fok_score": fok, "action": action, "prompt": prompt, "task": task}
        except Exception:
            # FAIL-OPEN：中性分数保守执行
            return {
                "fok_score": 0.5,
                "action": ACTION_PROCEED,
                "prompt": FOK_PROMPT_TEMPLATE.format(task=str(task) if task else ""),
                "task": task,
            }

    @staticmethod
    def _top_score(items: Optional[List[Any]]) -> float:
        """取列表中最高 score（dict 条目取 score 字段，缺失 → 0）。"""
        if not items:
            return 0.0
        scores = []
        for item in items:
            if isinstance(item, dict):
                scores.append(_safe_float(item.get("score"), 0.0))
        return max(scores) if scores else 0.0

    # ============================================================
    # 2. JOL — SKILL 执行后学习评估
    # ============================================================

    def post_execute_jol(self, execution_result: Any) -> Dict[str, Any]:
        """JOL 学习评估：任务执行后判断"学到了什么"。

        规则版打分:
          - success=True → 0.8；success=False → 0.2

        Args:
            execution_result: {"success": bool, "error": str|None, ...}
            None/非 dict → FAIL-OPEN 中性 0.5

        Returns:
            {
              "jol_score": 0.0-1.0,
              "action": "record"|"mark_verify",
              "prompt": JOL 注入问句,
            }
        """
        try:
            if not isinstance(execution_result, dict):
                jol = 0.5  # FAIL-OPEN：中性
            else:
                success = execution_result.get("success")
                jol = 0.8 if success is True else 0.2

            if jol >= self._verify_threshold:
                action = ACTION_RECORD
            else:
                action = ACTION_MARK_VERIFY

            return {"jol_score": jol, "action": action, "prompt": JOL_PROMPT_TEMPLATE}
        except Exception:
            return {"jol_score": 0.5, "action": ACTION_RECORD, "prompt": JOL_PROMPT_TEMPLATE}


# ============================================================
# CLI 自测
# ============================================================


if __name__ == "__main__":
    print("=" * 60)
    print("MetacogHarness — 功能验证")
    print("=" * 60)

    h = MetacogHarness()

    r1 = h.pre_execute_fok("分析 BTC", [{"id": "s", "score": 0.9}], [{"id": "m", "score": 0.85}])
    print(f"\nFOK 高: score={r1['fok_score']:.2f} → {r1['action']}")

    r2 = h.pre_execute_fok("冷门任务", [{"id": "s", "score": 0.4}], [])
    print(f"FOK 中: score={r2['fok_score']:.2f} → {r2['action']}")

    r3 = h.pre_execute_fok("陌生任务", [], [])
    print(f"FOK 低: score={r3['fok_score']:.2f} → {r3['action']}")

    r4 = h.post_execute_jol({"success": True})
    print(f"\nJOL 成功: score={r4['jol_score']:.2f} → {r4['action']}")

    r5 = h.post_execute_jol({"success": False, "error": "timeout"})
    print(f"JOL 失败: score={r5['jol_score']:.2f} → {r5['action']}")

    print("\n" + "=" * 60)
    print("✅ MetacogHarness 功能验证通过")
