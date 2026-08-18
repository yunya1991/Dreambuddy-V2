"""
Agent A/B/C：Hyperliquid 资金规则
=====================================

系统：agent_a / agent_b / agent_c_memory ｜ 账户：AccountType.HYPERLIQUID
优先级：30

注意：三条系统共用同一个 Hyperliquid handler（内部按 system 参数分流）。
因为 execute_chain 会按 category 执行所有启用规则，所以这里注册一个
规则名 ``capital.hyperliquid``，它会从 context["target_system"] 或默认
遍历 agent_a / agent_b / agent_c_memory 三个系统并在 extra 中分别返回。

为了让主组件能按 ``enabled_systems`` 精确匹配，CapitalControlComponent 内
部将按 system 维度调用 ``_hyperliquid_one_system(system, ...)``，不走
``execute_chain(CAPITAL)`` 对 HL 的直接展开。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve()
_CORE_DIR = _HERE.parents[1]
_RISK_DIR = _HERE.parents[3] / "13-通用风控模块"
_RISK_CORE_DIR = _RISK_DIR / "core"
for _p in (_CORE_DIR, _RISK_DIR, _RISK_CORE_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

try:
    from core.registry import register_capital  # noqa: E402
except ImportError:
    from registry import register_capital  # noqa: E402
from capital_control.types import (  # noqa: E402
    AccountType,
    CapitalMode,
    CapitalResult,
)
from ._shared import (  # noqa: E402
    _static_from_config,
    build_result_from_system,
)

_ACCOUNT_TYPE = AccountType.HYPERLIQUID
_DEFAULT_STATIC_BY_SYSTEM: Dict[str, float] = {
    "agent_a": 60.0,
    "agent_b": 60.0,
    "agent_c_memory": 0.0,
}


def _hyperliquid_one_system(
    system: str,
    context: Dict[str, Any],
    config: Dict[str, Any],
) -> CapitalResult:
    """单系统版本：供 CapitalControlComponent 内部按 enabled_systems 分别调用。"""
    mode = context.get("mode", CapitalMode.DYNAMIC) if isinstance(context.get("mode"), CapitalMode) else (
        CapitalMode.FIXED if context.get("mode") == "fixed" else CapitalMode.DYNAMIC
    )
    static_default = _DEFAULT_STATIC_BY_SYSTEM.get(system, 0.0)
    static_budget = _static_from_config(config, system, static_default)
    return build_result_from_system(
        system=system,
        account_type_default=_ACCOUNT_TYPE,
        mode=mode,
        static_budget=static_budget,
        context=context,
        extra_extract={"source": f"unified_position_query#fetch_{system}_positions"},
    )


@register_capital(
    name="capital.hyperliquid",
    priority=30,
    config_schema={
        "fallback_static_budget": {
            "type": "object",
            "default": _DEFAULT_STATIC_BY_SYSTEM,
        },
    },
    description="Agent A/B/C Hyperliquid 资金查询（复用 unified_position_query 缓存）",
)
def hyperliquid_capital_handler(
    signal: Optional[Any] = None,
    context: Any = None,
    base_risk: float = 0.0,
    config: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, CapitalResult]:
    """默认返回 {system: CapitalResult} 字典，覆盖 Agent A/B/C 三个系统。"""
    config = config or {}
    ctx = context if isinstance(context, dict) else {}
    target_systems: List[str]
    if isinstance(ctx.get("target_system"), str):
        target_systems = [ctx["target_system"]]
    else:
        target_systems = ["agent_a", "agent_b", "agent_c_memory"]
    results: Dict[str, CapitalResult] = {}
    for sys_name in target_systems:
        try:
            results[sys_name] = _hyperliquid_one_system(sys_name, ctx, config)
        except Exception as exc:  # 单系统失败不影响其他
            results[sys_name] = CapitalResult(
                system=sys_name,
                account_type=_ACCOUNT_TYPE,
                mode=CapitalMode.DYNAMIC,
                total_eq=float(_DEFAULT_STATIC_BY_SYSTEM.get(sys_name, 0.0)),
                avail_balance=float(_DEFAULT_STATIC_BY_SYSTEM.get(sys_name, 0.0)),
                used_margin=0.0,
                used_pct=0.0,
                fallback_used=True,
                fallback_reason=f"hyperliquid_handler_error: {exc}",
            )
    return results
