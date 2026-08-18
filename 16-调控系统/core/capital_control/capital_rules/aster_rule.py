"""
三屏趋势：Aster 资金规则
===========================

系统对应：three_screen ｜ 账户：AccountType.ASTER
优先级：40
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

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

_SYSTEM_NAME = "three_screen"
_ACCOUNT_TYPE = AccountType.ASTER
_DEFAULT_STATIC = 200.0


@register_capital(
    name="capital.aster",
    priority=40,
    config_schema={
        "fallback_static_budget": {"type": "object", "default": {_SYSTEM_NAME: _DEFAULT_STATIC}},
    },
    description="三屏趋势 Aster 资金查询（复用 unified_position_query 缓存，需 ml_trade_service 运行）",
)
def aster_capital_handler(
    signal: Optional[Any] = None,
    context: Any = None,
    base_risk: float = 0.0,
    config: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> CapitalResult:
    config = config or {}
    ctx = context if isinstance(context, dict) else {}
    mode = ctx.get("mode", CapitalMode.DYNAMIC) if isinstance(ctx.get("mode"), CapitalMode) else (
        CapitalMode.FIXED if ctx.get("mode") == "fixed" else CapitalMode.DYNAMIC
    )
    static_budget = _static_from_config(config, _SYSTEM_NAME, _DEFAULT_STATIC)
    return build_result_from_system(
        system=_SYSTEM_NAME,
        account_type_default=_ACCOUNT_TYPE,
        mode=mode,
        static_budget=static_budget,
        context=ctx,
        extra_extract={"source": "unified_position_query#fetch_three_screen_positions"},
    )
