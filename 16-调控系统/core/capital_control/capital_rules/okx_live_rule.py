"""
V15 马丁：OKX 实盘资金规则
===========================

系统对应：v15_martin ｜ 账户：AccountType.OKX_LIVE
优先级：10（最高——实盘账户）
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

# 共享模块所在包的父目录（16-调控系统/core）插入 sys.path
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

_SYSTEM_NAME = "v15_martin"
_ACCOUNT_TYPE = AccountType.OKX_LIVE
_DEFAULT_STATIC = 260.0


@register_capital(
    name="capital.okx_live",
    priority=10,
    config_schema={
        "fallback_static_budget": {"type": "object", "default": {_SYSTEM_NAME: _DEFAULT_STATIC}},
        "cache_ttl_sec": {"type": "int", "default": 60},
    },
    description="V15 马丁 OKX 实盘资金查询（复用 unified_position_query 缓存）",
)
def okx_live_capital_handler(
    signal: Optional[Any] = None,
    context: Any = None,
    base_risk: float = 0.0,
    config: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> CapitalResult:
    """capital.okx_live——V15 OKX 实盘。

    参数 context 可选含：
      - ``mode``: CapitalMode 覆盖；默认 DYNAMIC
      - ``positions_result``: fetch_all_positions 结果（缓存共享）
    """
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
        extra_extract={"source": "unified_position_query#fetch_v15_martin_positions"},
    )
