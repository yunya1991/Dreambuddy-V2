"""认知裁决 → `l2_route` 桥接（SPEC-v1.4 §3.4/§4.1、SPEC-56 IF-1 / GAP-13 / P1-1）。

实现唯一事实源：`56-L2架构能力聚合层/runtime/l2_route.py`。此处只做两件事：
按路径加载该模块（避免跨目录包名耦合）、把裁决结果注入 `route_signal`；
不复制阈值（0.65）与 verdict 判定逻辑。

FAIL-OPEN：运行时不可用或信号畸形时，`route_signal` 原样返回——
不新增字段、不拒答，与 SPEC-v1.4 §5「认知裁决异常 → 默认 unknown + L2」一致
（`decide_cognition_route` 自身已回落 `unknown + deep_reasoning`）。
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Mapping

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_L2_ROUTE_PATH = _REPO_ROOT / "56-L2架构能力聚合层" / "runtime" / "l2_route.py"

_MODULE: Any = None


def _l2() -> Any:
    global _MODULE
    if _MODULE is None and _L2_ROUTE_PATH.is_file():
        try:
            spec = importlib.util.spec_from_file_location("l2_route_56", _L2_ROUTE_PATH)
            module = importlib.util.module_from_spec(spec)
            sys.modules["l2_route_56"] = module
            spec.loader.exec_module(module)
            _MODULE = module
        except Exception as exc:  # noqa: BLE001 — FAIL-OPEN，不阻断路由
            logger.warning("l2_route 运行时加载失败: %s", exc)
    return _MODULE


def attach_cognition_route(route_signal: Mapping[str, Any]) -> Dict[str, Any]:
    """在 `route_signal` 上附加 `cognition_signal`（含 `l2_route`）。"""
    out = dict(route_signal)
    module = _l2()
    if module is None:
        return out
    try:
        out["cognition_signal"] = module.decide_cognition_route(out)
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN，保持原信号
        logger.warning("认知裁决失败（已保持原 route_signal）: %s", exc)
    return out


def attach_to_route_result(result: Mapping[str, Any]) -> Dict[str, Any]:
    """给 L1 路由脚本的完整返回体补 `cognition_signal`。

    只对 `decision == "L2_HANDOFF"` 生效：L1 直答不产生 L2 路线，
    不应被标成 `deep_reasoning`。其余字段与非交接请求原样保留。
    """
    out = dict(result)
    signal = out.get("route_signal")
    if isinstance(signal, Mapping) and signal.get("decision") == "L2_HANDOFF":
        out["route_signal"] = attach_cognition_route(signal)
    return out
