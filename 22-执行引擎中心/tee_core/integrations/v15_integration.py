"""V15 ↔ TEE 生产集成工厂。

遵循 NFR-4：本文件位于 tee_core 包内，但 **模块级绝不 import 任何
14-V15经典马丁策略 / 15-监控告警系统 目录**。V15 concrete raw_client
由 **调用方构造并传入**，我们在函数体内把它适配成 TEE 需要的
ExchangeClient 协议对象。

支持 importlib.util.spec_from_file_location(...) 直接从绝对路径加载
（无 parent package 的情况也可工作），通过 sys.path 插入实现解析。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, Tuple


def _resolve_tee_root() -> Path:
    # 相对：integrations/v15_integration.py → ../.. 即 22-执行引擎中心 根
    here = Path(__file__).resolve().parent
    return here.parent.parent


def _ensure_tee_on_path() -> Path:
    tee_root = _resolve_tee_root()
    tee_root_str = str(tee_root)
    if tee_root_str not in sys.path:
        sys.path.insert(0, tee_root_str)
    return tee_root


def build_v15_engine(
    *,
    raw_client: Any,
    enable_tee: bool = False,
    shadow_mode: bool = False,
    audit_dir: str | os.PathLike[str] | None = None,
    lark_bridge: Any = None,
) -> Tuple[Any, Dict[str, Any]]:
    """构建 V15 专用 TEE 引擎实例（懒解析内部 import 以兼容非包加载）。"""
    _ensure_tee_on_path()
    from tee_core.core.engine import TradeExecutionEngine
    from tee_core.adapters.okx_adapter import OkxAdapter

    base = Path(audit_dir) if audit_dir else _resolve_tee_root() / "audit"
    base = Path(base)
    base.mkdir(parents=True, exist_ok=True)

    exchange_client = OkxAdapter(raw_client=raw_client)
    # FAIL-OPEN 无 bridge 注入：TradeExecutionEngine.__init__(lark_bridge=None)
    # 内部会 fallback 到默认 LarkBridge（懒加载告警）。
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
        "source_label": "V15",
        "enable_tee": bool(enable_tee),
        "shadow_mode": bool(shadow_mode),
    }
    return engine, info

