"""
资金规则实现：共享 helper
===========================

目标：避免重复调用 OKX / Hyperliquid / Aster API，全部复用
``unified_position_query.fetch_all_positions()`` 产出的 60s 缓存。

handler 从 ``context["positions_result"]`` 提取各系统的 equity/extra，
组装成 ``CapitalResult`` 返回。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# 让 capital_rules 下的子模块能 import types
_PKG_ROOT = Path(__file__).resolve().parents[2]  # .../16-调控系统/core
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from capital_control.types import (
    AccountType,
    CapitalMode,
    CapitalResult,
    now_iso,
)

_UNIFIED_DIR = _PKG_ROOT
if str(_UNIFIED_DIR) not in sys.path:
    sys.path.insert(0, str(_UNIFIED_DIR))


_ACCOUNT_TYPE_MAP: Dict[str, AccountType] = {
    "okx_live": AccountType.OKX_LIVE,
    "okx_simulated": AccountType.OKX_SIMULATED,
    "hyperliquid": AccountType.HYPERLIQUID,
    "aster": AccountType.ASTER,
}


def _account_type_from_str(value: Optional[str]) -> AccountType:
    if not value:
        return AccountType.UNKNOWN
    return _ACCOUNT_TYPE_MAP.get(value.lower(), AccountType.UNKNOWN)


def _ensure_positions_result(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """从 context 或懒加载 fetch_all_positions，保证 handlers 总能拿到数据。"""
    if isinstance(context, dict) and isinstance(context.get("positions_result"), dict):
        return context["positions_result"]
    try:
        from unified_position_query import fetch_all_positions

        result = fetch_all_positions()
        if isinstance(context, dict):
            context["positions_result"] = result
        return result or {}
    except Exception as exc:
        return {"_fetch_error": str(exc)}


def build_result_from_system(
    system: str,
    account_type_default: AccountType,
    mode: CapitalMode,
    static_budget: float,
    context: Optional[Dict[str, Any]] = None,
    extra_extract: Optional[Dict[str, Any]] = None,
) -> CapitalResult:
    """通用组装函数：从 fetch_all_positions 缓存提取指定系统的资金数据。

    Args:
        system:               系统名（v15_martin / yijing_bcrm / agent_a / ...）
        account_type_default: 缺失 account_type 字段时的兜底
        mode:                 CapitalMode.FIXED / DYNAMIC
        static_budget:        FIXED 模式使用的值 & DYNAMIC 失败的降级值
        context:              上下文，可选含 positions_result 或 unified_position_query 覆盖
        extra_extract:        额外字段补充
    """
    ts = now_iso()
    extra_extract = extra_extract or {}

    if mode == CapitalMode.FIXED:
        return CapitalResult(
            system=system,
            account_type=account_type_default,
            mode=CapitalMode.FIXED,
            total_eq=float(static_budget),
            avail_balance=float(static_budget),
            used_margin=0.0,
            used_pct=0.0,
            fallback_used=True,
            fallback_reason="fixed_mode_static_budget",
            timestamp=ts,
            extra=dict(extra_extract),
        )

    # DYNAMIC 模式：尝试 unified_position_query 缓存
    pos_result = _ensure_positions_result(context)
    fetch_error = pos_result.get("_fetch_error") if isinstance(pos_result, dict) else None
    sys_data = (pos_result or {}).get("systems", {}).get(system) if isinstance(pos_result, dict) else None

    fallback_reason = ""
    if fetch_error:
        fallback_reason = f"unified_fetch_failed: {fetch_error}"
    elif not sys_data:
        fallback_reason = f"system_data_missing: {system}"

    if fallback_reason:
        return CapitalResult(
            system=system,
            account_type=account_type_default,
            mode=CapitalMode.DYNAMIC,
            total_eq=float(static_budget),
            avail_balance=float(static_budget),
            used_margin=0.0,
            used_pct=0.0,
            fallback_used=True,
            fallback_reason=fallback_reason,
            timestamp=ts,
            extra=dict(extra_extract),
        )

    extra_data = sys_data.get("extra") or {}
    account_type = _account_type_from_str(extra_data.get("account_type"))
    if account_type == AccountType.UNKNOWN:
        account_type = account_type_default

    equity = float(sys_data.get("equity") or 0.0)
    avail = float(extra_data.get("avail_balance") or 0.0)
    used = float(extra_data.get("used_margin") or 0.0)
    data_fallback_used = bool(sys_data.get("fallback_used") or extra_data.get("fallback_used"))
    data_fallback_reason = str(
        sys_data.get("fallback_reason") or extra_data.get("fallback_reason") or ""
    )

    # 如果 equity <= 0 → 视为不可用，静态兜底；保留 fallback_reason 溯源
    if equity <= 0.0:
        return CapitalResult(
            system=system,
            account_type=account_type,
            mode=CapitalMode.DYNAMIC,
            total_eq=float(static_budget),
            avail_balance=float(static_budget),
            used_margin=0.0,
            used_pct=0.0,
            fallback_used=True,
            fallback_reason=data_fallback_reason or "equity_zero_or_negative_static_fallback",
            timestamp=ts,
            extra={**extra_extract, **extra_data},
        )

    # avail/used 兜底：equity 有但 extra 没字段
    if avail <= 0.0 and equity > 0.0:
        avail = equity
    if used <= 0.0 and equity > 0.0:
        used = max(0.0, equity - avail)

    used_pct = 0.0
    if equity > 0:
        used_pct = round(used * 100.0 / equity, 2)

    merged_extra = {**extra_extract, **{k: v for k, v in extra_data.items() if k not in extra_extract}}
    return CapitalResult(
        system=system,
        account_type=account_type,
        mode=CapitalMode.DYNAMIC,
        total_eq=round(equity, 2),
        avail_balance=round(avail, 2),
        used_margin=round(used, 2),
        used_pct=used_pct,
        fallback_used=data_fallback_used,
        fallback_reason=data_fallback_reason,
        timestamp=ts,
        extra=merged_extra,
    )


def _static_from_config(config: Optional[Dict[str, Any]], key: str, default: float) -> float:
    if not isinstance(config, dict):
        return default
    static_map = config.get("fallback_static_budget")
    if isinstance(static_map, dict) and isinstance(static_map.get(key), (int, float)):
        return float(static_map[key])
    return default


__all__ = [
    "AccountType",
    "CapitalMode",
    "CapitalResult",
    "build_result_from_system",
    "_static_from_config",
]
