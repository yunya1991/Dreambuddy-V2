"""易经推理（BCRM2.0 + BDSM）↔ TEE 生产集成工厂。

遵循 NFR-4：本文件位于 tee_core 包内，但 **模块级绝不 import 任何
11-易经推理系统 目录**。易经推理的 concrete raw_client（OKXSimulatedClient）
由 **调用方构造并传入**，我们在函数体内把它适配成 TEE 需要的
ExchangeClient 协议对象。

影子模式（shadow_mode=True, enable_tee=False）：
  - TEE 完整执行 11 步决策链（滑点估计/路由/算法/熔断/审计）
  - 但最终不改变实际下单，只写入 shadow 审计日志
  - 实际下单仍走原始 okx_client.place_order()
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, Tuple


def _resolve_tee_root() -> Path:
    # 相对：integrations/yijing_integration.py → ../.. 即 22-执行引擎中心 根
    here = Path(__file__).resolve().parent
    return here.parent.parent


def _ensure_tee_on_path() -> Path:
    tee_root = _resolve_tee_root()
    tee_root_str = str(tee_root)
    if tee_root_str not in sys.path:
        sys.path.insert(0, tee_root_str)
    return tee_root


def build_yijing_engine(
    *,
    raw_client: Any,
    enable_tee: bool = False,
    shadow_mode: bool = False,
    audit_dir: str | os.PathLike[str] | None = None,
    lark_bridge: Any = None,
) -> Tuple[Any, Dict[str, Any]]:
    """构建易经推理专用 TEE 引擎实例（懒解析内部 import 以兼容非包加载）。

    Args:
        raw_client: OKXSimulatedClient 实例（由 polling_trader 构造并传入）
        enable_tee: 是否启用 TEE 真实执行（False=只观察不拦截）
        shadow_mode: 影子模式（True=记录 TEE 决策到审计日志，不改变下单）
        audit_dir: 审计日志目录
        lark_bridge: 飞书告警桥接（None=FAIL-OPEN 默认）
    """
    _ensure_tee_on_path()
    from tee_core.core.engine import TradeExecutionEngine
    from tee_core.adapters.okx_adapter import OkxAdapter

    base = Path(audit_dir) if audit_dir else _resolve_tee_root() / "audit"
    base = Path(base)
    base.mkdir(parents=True, exist_ok=True)

    exchange_client = OkxAdapter(raw_client=raw_client)
    bridge = lark_bridge

    engine = TradeExecutionEngine(
        exchange_client=exchange_client,
        enable_tee=bool(enable_tee),
        shadow_mode=bool(shadow_mode),
        audit_dir=str(base),
        lark_bridge=bridge,
    )

    info: Dict[str, Any] = {
        "audit_dir": str(base.resolve()),
        "source_label": "YIJING",
        "enable_tee": bool(enable_tee),
        "shadow_mode": bool(shadow_mode),
    }
    return engine, info
