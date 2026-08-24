"""
dreambuddy_dal.compat — 历史兼容层（解决 Experience 698940：5 处独立 TradeRecord 定义漂移）
- 真实 SSoT 类：dreambuddy_dal.unified_models（类型完全一致，通过模块级 __getattr__ 懒转发）
- 符号首次访问（属性查找）触发 DeprecationWarning 1 次（全局）
- 2026-09-30 之后旧路径将清理（见 CHANGELOG Deprecated）

⚠️ 注意：真正的 5 处旧定义（trading_utils.py / dreamos_backtester.py / yijing_trainer.py /
backtest engine / ab_comparison.py）需要在 P0-7 步骤手工改 `from X import TradeRecord`
→ `from dreambuddy_dal.compat import TradeRecord`（最后再换 direct import from unified_models）
"""
from __future__ import annotations

import warnings
from typing import Any

# SSoT 真实类存这里（不直接 import 到全局符号表，避免首加载就警告）
import dreambuddy_dal.unified_models as _ssot

# 需要转发的符号集合（对齐 unified_models.__all__）
_FORWARD_SYMBOLS = {
    # 4 核心 + 辅助
    "TradeRecord", "PositionState", "DailyStats", "RiskState", "RiskCaseRecord", "CloseInfo",
    # 6 枚举
    "TradeDirection", "TradeStatus", "ExitReason", "RiskLevel", "TrialStatus", "PositionStyle",
    # 工具
    "LEGACY_TRADE_RECORD_SYMBOLS",
}

# 旧路径符号注册表（用于测试/巡检）
LEGACY_TRADE_RECORD_SYMBOLS: dict[str, tuple] = {
    # P0 先登记 1 处；其余 4 处 P0-7 接入时补全
    "dreambuddy_dal.compat.TradeRecord": ("TradeRecord", "TradeRecord", "2026-09-30"),
}

# 警告只发一次（全局标记）
_warned: set[str] = set()

_DEPRECATION_MSG = (
    "请改用 from dreambuddy_dal.unified_models import {sym} / "
    "from dreambuddy_dal import {sym} ；"
    "dreambuddy_dal.compat 为历史兼容层，将于 2026-09-30 移除。"
    "（Experience 698940 教训：避免 5 处独立 TradeRecord 定义字段漂移）"
)


def __getattr__(name: str) -> Any:
    """
    Python 3.7+ 模块级 __getattr__：当 name 不在全局命名空间里时调用。
    - 只有真正访问符号（from compat import X 或 compat.X）才触发警告
    - 每个符号仅警告一次
    """
    if name == "LEGACY_TRADE_RECORD_SYMBOLS":
        return LEGACY_TRADE_RECORD_SYMBOLS
    if name in _FORWARD_SYMBOLS:
        # 真实从 SSoT 取出（保证类型完全等价）
        if not hasattr(_ssot, name):
            raise AttributeError(f"dreambuddy_dal.compat.{name} 不存在")
        obj = getattr(_ssot, name)
        # 警告（每符号仅一次）
        if name not in _warned:
            _warned.add(name)
            warnings.warn(
                _DEPRECATION_MSG.format(sym=name),
                DeprecationWarning,
                stacklevel=2,
            )
        return obj
    raise AttributeError(f"module 'dreambuddy_dal.compat' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(list(_FORWARD_SYMBOLS) + ["__name__", "__doc__", "__all__"])


__all__ = sorted(_FORWARD_SYMBOLS)
