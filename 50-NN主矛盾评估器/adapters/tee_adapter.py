# R3-04: 22 层 tee_core paper 执行适配器（50 决策 -> 22 TradeExecutionEngine，shadow 模式）。
#
# 零侵入：不修改 22 层任何文件；通过 sys.path 注入加载 22 层模块。
# paper 边界：默认 shadow_mode=True + no-op paper client，不触真实交易所、不下真实单。
# neutral 决策跳过执行链；任何异常 fail-safe 返回 ok=False，不阻断 50 层主链路。
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
_22_DIR = REPO_ROOT / "22-执行引擎中心"


class _PaperClient:
    # no-op paper client：shadow 模式下不应被真正调用；若被调用则显式拒绝真实下单。
    def place_order(self, **kwargs):
        raise RuntimeError("paper_client_forbidden_real_order")


def _load_engine_cls() -> Any | None:
    # 按需加载 22 层 TradeExecutionEngine；失败返回 None。
    if str(_22_DIR) not in sys.path:
        sys.path.insert(0, str(_22_DIR))
    try:
        from tee_core.core.engine import TradeExecutionEngine  # noqa: E402

        return TradeExecutionEngine
    except Exception:
        return None


def build_parent_req(decision: dict[str, Any], equity: float = 10000.0) -> dict[str, Any]:
    # 50 决策 -> 22 层 parent_req（paper 近似：sz 以 USDT 计价数量近似，无价格源时用 1.0）。
    direction = str(decision.get("direction") or "neutral")
    position_pct = float(decision.get("position_pct") or 0.0)
    position_usdt = max(0.0, equity * position_pct / 100.0)
    sz = float(decision.get("sz") or position_usdt or 1.0)
    return {
        "inst_id": str(decision.get("symbol") or "MULTI"),
        "side": "buy" if direction == "long" else "sell",
        "sz": sz,
        "td_mode": "isolated",
        "pos_side": "net",
        "source": "50-nn",
        "tag": "50-nn-paper",
        "reason": str(decision.get("signal_id") or ""),
        "metadata": {
            "signal_id": decision.get("signal_id"),
            "confidence": decision.get("confidence"),
            "position_pct": position_pct,
            "shadow": decision.get("shadow", True),
        },
    }


def execute_decision(
    decision: dict[str, Any],
    engine: Any | None = None,
    equity: float = 10000.0,
) -> dict[str, Any]:
    # 50 决策 -> 22 层 TradeExecutionEngine.execute（paper/shadow 模式）。
    # 返回 {ok, receipt, source}；neutral 跳过；异常/加载失败 fail-safe 返回 ok=False。
    direction = str(decision.get("direction") or "neutral")
    if direction == "neutral":
        return {
            "ok": False,
            "receipt": None,
            "reason": "neutral_no_execution",
            "source": "22-tee-core",
        }
    try:
        if engine is None:
            engine_cls = _load_engine_cls()
            if engine_cls is None:
                return {
                    "ok": False,
                    "receipt": None,
                    "reason": "tee_module_load_failed",
                    "source": "22-tee-core",
                }
            engine = engine_cls(exchange_client=_PaperClient(), shadow_mode=True)
        parent_req = build_parent_req(decision, equity=equity)
        receipt = engine.execute(parent_req)
        return {"ok": True, "receipt": receipt, "source": "22-tee-core"}
    except Exception as exc:
        return {
            "ok": False,
            "receipt": None,
            "reason": f"tee_adapter_exception:{exc}",
            "source": "22-tee-core",
        }
