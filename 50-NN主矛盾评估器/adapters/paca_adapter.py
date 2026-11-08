# R3-03: 16 层 PACA 建议适配器（50 决策 -> 16 get_allocation_advice，建议制，不拦截）。
#
# 零侵入：不修改 16 层任何文件；通过 sys.path 注入加载 16 层模块。
# 建议制：返回值仅作为参考信息（advice 字段），不修改、不拦截 50 层决策。
# 任何异常返回 ok=False 的 fallback 标记，决策链路不受影响。
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
_16_DIR = REPO_ROOT / "16-调控系统"

_ALLOCATOR: Any = None


def _load_allocator() -> Any | None:
    # 按需加载 16 层 CapitalAllocatorComponent（默认 shadow 模式）；失败返回 None。
    # 包名隔离：13 层与 16 层都用顶层 core 包名，加载 16 层前临时摘除 core.*
    # 缓存，加载后恢复原状，避免与 13 层 core 包冲突（已创建的类对象不受影响）。
    global _ALLOCATOR
    if _ALLOCATOR is not None:
        return _ALLOCATOR
    if str(_16_DIR) not in sys.path:
        sys.path.insert(0, str(_16_DIR))
    saved = {k: v for k, v in sys.modules.items() if k == "core" or k.startswith("core.")}
    for k in list(saved):
        del sys.modules[k]
    try:
        from core.capital_allocator.component import CapitalAllocatorComponent  # noqa: E402

        _ALLOCATOR = CapitalAllocatorComponent()
        return _ALLOCATOR
    except Exception:
        return None
    finally:
        for k in [k for k in sys.modules if k == "core" or k.startswith("core.")]:
            del sys.modules[k]
        sys.modules.update(saved)


def get_advice(
    decision: dict[str, Any],
    allocator: Any | None = None,
    equity: float = 10000.0,
) -> dict[str, Any]:
    # 50 决策 -> 16 层 PACA get_allocation_advice（建议制，不拦截）。
    # 返回 {ok, advice, source}；异常/加载失败返回 ok=False，advice=None。
    symbol = str(decision.get("symbol") or "MULTI")
    try:
        if allocator is None:
            allocator = _load_allocator()
        if allocator is None:
            return {
                "ok": False,
                "advice": None,
                "reason": "paca_module_load_failed",
                "source": "16-paca",
            }
        advice = allocator.get_allocation_advice(
            coin=symbol, source_tag="50-nn", equity=float(equity)
        )
        return {"ok": True, "advice": advice, "source": "16-paca"}
    except Exception as exc:
        return {
            "ok": False,
            "advice": None,
            "reason": f"paca_adapter_exception:{exc}",
            "source": "16-paca",
        }
