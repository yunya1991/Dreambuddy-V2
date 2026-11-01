# -*- coding: utf-8 -*-
"""
l0_gate.py — L0 沉淀门禁适配器（P3-3）
========================================
职责（PLAN P3-3 验收）：
- 把 45 的门禁裁决包成 L0 可注入的 `settle_gate(context) -> (allowed, info)`
- 无有效凭证 → 拒绝沉淀；影子模式只记录 `SHADOW_WOULD_BLOCK`，不阻断
- 注入方式（34-前端应用训练系统 L0Foundation）：

    from core.enforcement import Enforcer
    from integrations.l0_gate import build_settle_gate

    l0 = L0Foundation()
    l0.settle(result, {"eval_id": eval_id, ...}, gate=build_settle_gate(enforcer))

context 约定：`context["eval_id"]` 为 45 受理返回的评测 id；缺失按未通过处理
（fail-closed：宁可拒绝沉淀，不可无凭证沉淀）。
"""

from __future__ import annotations

from typing import Any, Callable

from core.enforcement import Enforcer

SettleGate = Callable[[dict[str, Any]], tuple[bool, dict[str, Any]]]


def build_settle_gate(enforcer: Enforcer) -> SettleGate:
    """构造 L0 沉淀门禁：返回 (是否放行, 裁决详情)。"""

    def settle_gate(context: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        eval_id = str((context or {}).get("eval_id") or "").strip()
        decision = enforcer.enforce("l0_settle", eval_id)
        return decision.allowed, decision.to_dict()

    return settle_gate
