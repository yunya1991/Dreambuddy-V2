# -*- coding: utf-8 -*-
"""settle 五系统全通道(T-DSH-P3 P3-1)。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 P3·常驻(settle 五系统全通道) + §⑦ 沉淀层
(认知经验 · SKILL 可复用流程 · 调研知识 · 文档 · 索引) + ADR-9(settle 由编排侧
Settle 节点执行,Worker 只读) + H1 FAIL-OPEN + H2(开关默认关)。

定位: settle 的分发层——把同一份 (result, context) 分发给五个沉淀通道。
通道本体(认知 record / SKILL 提炼 / 知识入库 / 文档落盘 / 索引更新)以
callable 注入,本模块不实现各系统写逻辑,只做开关判定 + 隔离执行 + 逐一上报。

硬约束:
  HC-1 FAIL-OPEN: 单通道异常 → 该通道 failed,其余通道照常;坏输入 → {}
  HC-2 开关默认关: enable_settle_channel_<name> 缺省 False
  通道执行顺序固定(SETTLE_CHANNELS 声明序),报告键全覆盖五通道
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

# 五系统沉淀通道(DESIGN §⑦)
SETTLE_CHANNELS = ("cognitive", "skill", "knowledge", "docs", "index")

# 状态口径
_STATUS_OK = "ok"
_STATUS_FAILED = "failed"
_STATUS_DISABLED = "disabled"
_STATUS_UNCONFIGURED = "unconfigured"


def channel_switch(name: Any) -> str:
    """通道开关名(HC-2): enable_settle_channel_<name>。"""
    return "enable_settle_channel_%s" % name


def is_channel_enabled(name: Any, flags: Optional[Dict[str, Any]] = None) -> bool:
    """通道开关读取(HC-2)。未知通道/非 dict flags/缺键 → False(默认关)。"""
    try:
        if name not in SETTLE_CHANNELS:
            return False
        if not isinstance(flags, dict):
            return False
        return bool(flags.get(channel_switch(name), False))
    except Exception:
        return False


def settle_via_channels(
    result: Any,
    context: Optional[Dict[str, Any]] = None,
    channels: Optional[Dict[str, Callable[[Any, Dict[str, Any]], Any]]] = None,
    flags: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """把 (result, context) 分发给开启的沉淀通道,逐通道上报。

    返回 {channel: {"status": ok/failed/disabled/unconfigured, "detail": ...}}。
    单通道异常不阻塞其余通道(H1);channels/flags 坏输入 → {}(FAIL-OPEN)。
    """
    try:
        if not isinstance(channels, dict) or not isinstance(flags, dict):
            return {}
        ctx = context if isinstance(context, dict) else {}
        report: Dict[str, Dict[str, Any]] = {}
        for name in SETTLE_CHANNELS:
            if not is_channel_enabled(name, flags):
                report[name] = {"status": _STATUS_DISABLED, "detail": None}
                continue
            fn = channels.get(name)
            if not callable(fn):
                report[name] = {"status": _STATUS_UNCONFIGURED, "detail": None}
                continue
            try:
                detail = fn(result, ctx)
                report[name] = {"status": _STATUS_OK, "detail": detail}
            except Exception as exc:
                report[name] = {
                    "status": _STATUS_FAILED,
                    "detail": "%s: %s" % (type(exc).__name__, exc),
                }
        return report
    except Exception:
        return {}
