# ruff: noqa: E402
"""ASIL 变体生成器 — D3/D2 双闭环的「下一代候选」产生器。

设计约束：
- 确定性、零 LLM、零 GPU（沿用 C12）
- 只基于结构化反馈（历史 metrics / plan 诊断），不做自由文本猜测
- 生成结果必须可被现有门禁评估，不接受「无法验证」的提案
"""

from __future__ import annotations

import copy
import sys
from dataclasses import asdict, dataclass
from itertools import product
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# D3：意图规则变体
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RuleVariant:
    """意图预测策略变体（规则层，零 LLM）。"""

    name: str
    fallback: str = "general"  # general / majority
    min_conf: float = 0.0  # 低于阈值则回退
    aggregate: str = "sum"  # sum（全部 domain 计分）/ top_domain（仅最强 domain）


DEFAULT_D3_VARIANTS: List[RuleVariant] = [
    RuleVariant("baseline_general_sum", fallback="general", min_conf=0.0, aggregate="sum"),
    RuleVariant("majority_sum", fallback="majority", min_conf=0.0, aggregate="sum"),
    RuleVariant("majority_conf60", fallback="majority", min_conf=0.6, aggregate="sum"),
    RuleVariant("majority_conf50_top", fallback="majority", min_conf=0.5, aggregate="top_domain"),
]

_FALLBACKS = ["general", "majority"]
_MIN_CONFS = [0.0, 0.3, 0.4, 0.5, 0.6, 0.7]
_AGGREGATES = ["sum", "top_domain"]


def _sig(params: Dict[str, Any]) -> tuple:
    return (
        params.get("fallback"),
        round(float(params.get("min_conf", 0.0)), 3),
        params.get("aggregate"),
    )


class D3VariantGenerator:
    """从闭环历史中生成未探索的规则组合。

    反馈利用：
    - 去重：历史已出现过的参数组合不再提案
    - 校准回归剪枝：若某 min_conf 导致 ECE 回归超容忍度，则屏蔽 >= 该阈值的提案
    - 距离优先：优先提出与冠军只差一个维度的变体（局部搜索）
    """

    def __init__(self, max_proposals: int = 4):
        self.max_proposals = max_proposals

    def propose(
        self,
        history: Sequence[Dict[str, Any]],
        champion: RuleVariant,
        ece_tolerance: float = 0.02,
    ) -> List[RuleVariant]:
        explored = {_sig(asdict(champion))}
        blocked_min_conf: List[float] = []

        for rec in history:
            metrics = rec.get("metrics") or {}
            params = metrics.get("params")
            if params:
                explored.add(_sig(params))
            if rec.get("decision") != "reject":
                continue
            base = rec.get("baseline_metrics") or {}
            if (
                params
                and params.get("min_conf") is not None
                and metrics.get("ece") is not None
                and base.get("ece") is not None
                and metrics["ece"] > base["ece"] + ece_tolerance
            ):
                blocked_min_conf.append(float(params["min_conf"]))

        champ = asdict(champion)
        scored: List[tuple] = []
        for fb, mc, ag in product(_FALLBACKS, _MIN_CONFS, _AGGREGATES):
            sig = (fb, round(mc, 3), ag)
            if sig in explored:
                continue
            if any(mc >= b for b in blocked_min_conf):
                continue
            distance = (
                (fb != champ["fallback"])
                + (round(mc, 3) != round(champ["min_conf"], 3))
                + (ag != champ["aggregate"])
            )
            name = f"evo_{fb}_c{mc}_{ag}"
            scored.append(
                (distance, name, RuleVariant(name=name, fallback=fb, min_conf=mc, aggregate=ag))
            )

        scored.sort(key=lambda x: (x[0], x[1]))
        return [v for _, _, v in scored[: self.max_proposals]]


# ---------------------------------------------------------------------------
# D2：方案模板策略
# ---------------------------------------------------------------------------
_STDLIB = set(getattr(sys, "stdlib_module_names", set()))


def _is_stdlib_module(module: str) -> bool:
    root = str(module).replace("\\", "/").split("/")[0].split(".")[0]
    return root in _STDLIB


@dataclass(frozen=True)
class TemplatePolicy:
    """下一代方案模板策略（对 generator 输出做确定性后处理）。"""

    kind: str
    description: str

    def apply(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        p = copy.deepcopy(plan)
        if self.kind == "stdlib_to_dependencies":
            modules = p.get("modules") or []
            keep = [m for m in modules if not _is_stdlib_module(m)]
            moved = [m for m in modules if _is_stdlib_module(m)]
            p["modules"] = keep
            p["dependencies"] = list(dict.fromkeys((p.get("dependencies") or []) + moved))
        elif self.kind == "dedupe_modules":
            p["modules"] = list(dict.fromkeys(p.get("modules") or []))
        elif self.kind == "flag_missing_skeleton":
            p["requires_code_skeleton"] = not bool(p.get("code_skeleton"))
        elif self.kind == "attach_acceptance":
            p["acceptance"] = {
                "expected_value": p.get("expected_value") or "",
                "measurable_required": True,
            }
        return p


_POLICY_ORDER = [
    "stdlib_to_dependencies",
    "dedupe_modules",
    "flag_missing_skeleton",
    "attach_acceptance",
]
_POLICY_DESC = {
    "stdlib_to_dependencies": "把标准库模块从 modules 移入 dependencies，避免污染项目模块集合",
    "dedupe_modules": "去除 modules 重复项",
    "flag_missing_skeleton": "缺少 code_skeleton 时显式标记 requires_code_skeleton",
    "attach_acceptance": "把 expected_value 固化为可度量的验收要求",
}


class D2TemplateGenerator:
    """从 D2 历史诊断中生成下一代模板策略。"""

    def __init__(self, max_policies: int = 3):
        self.max_policies = max_policies

    def propose(self, history: Sequence[Dict[str, Any]]) -> List[TemplatePolicy]:
        kinds = set()
        for rec in history:
            diag = ((rec.get("metrics") or {}).get("plan_diagnostics")) or {}
            if diag.get("stdlib_modules"):
                kinds.add("stdlib_to_dependencies")
            if (diag.get("module_count") or 0) != (diag.get("unique_module_count") or 0):
                kinds.add("dedupe_modules")
            if diag.get("has_code_skeleton") is False:
                kinds.add("flag_missing_skeleton")
            if diag.get("expected_value"):
                kinds.add("attach_acceptance")
        ordered = [k for k in _POLICY_ORDER if k in kinds]
        return [
            TemplatePolicy(kind=k, description=_POLICY_DESC[k])
            for k in ordered[: self.max_policies]
        ]

    @staticmethod
    def compose(policies: Sequence[TemplatePolicy]):
        """把多条策略合成为一个 apply(plan) 可调用对象。"""

        def _apply(plan: Dict[str, Any]) -> Dict[str, Any]:
            out = plan
            for policy in policies:
                out = policy.apply(out)
            return out

        return _apply


def plan_diagnostics(plan: Dict[str, Any], expected_value: Optional[str] = None) -> Dict[str, Any]:
    """采集方案诊断特征，供 D2TemplateGenerator 使用。"""
    modules = [m for m in (plan.get("modules") or []) if isinstance(m, str)]
    return {
        "modules": modules,
        "module_count": len(modules),
        "unique_module_count": len(set(modules)),
        "stdlib_modules": [m for m in modules if _is_stdlib_module(m)],
        "has_code_skeleton": bool(plan.get("code_skeleton")),
        "expected_value": expected_value or plan.get("expected_value") or "",
    }
