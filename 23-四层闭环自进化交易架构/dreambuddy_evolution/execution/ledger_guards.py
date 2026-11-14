"""23 域开仓闸门的 22 账本数据源（替代 11 的 PositionTracker / last_close_info）。

用法（未来 23 独立开仓 runner）::

    guards = LedgerGuards(gateway)
    loop = EvolutionEntryLoop(gateway=gateway,
                              has_position_fn=guards.has_position,
                              cooldown_fn=guards.cooldown,
                              subpool_fn=guards.subpool, ...)

只读 22 账本，不 import 11 任何模块。
"""

from __future__ import annotations

from typing import Any, Iterable

DEFAULT_TAGS: tuple[str, ...] = (
    "23-evolution",
    "evolution",
    "bcrm",
    "strategy",
    "event_arbitrage",
)


def _owned(pos: dict[str, Any], tags: Iterable[str]) -> bool:
    source = str(pos.get("source") or "")
    return any(t and t in source for t in tags)


class LedgerGuards:
    """把 22 账本投影成 EvolutionEntryLoop 需要的闸门回调。"""

    def __init__(
        self,
        gateway: Any,
        tags: Iterable[str] = DEFAULT_TAGS,
        cooldown_sec: float = 1800,
    ):
        self._gateway = gateway
        self._tags = tuple(tags)
        self._cooldown_sec = float(cooldown_sec)

    def _open_positions(self) -> list[dict[str, Any]]:
        fn = getattr(self._gateway, "list_positions", None)
        rows = fn() if callable(fn) else []
        return [r for r in rows or [] if float(r.get("qty") or 0) > 0 and _owned(r, self._tags)]

    def has_position(self, inst_id: str) -> bool:
        return any(str(p.get("inst_id")) == str(inst_id) for p in self._open_positions())

    def cooldown(self, inst_id: str, direction: str = "") -> tuple[bool, str]:
        fn = getattr(self._gateway, "is_in_cooldown", None)
        if not callable(fn) or not fn(str(inst_id), self._cooldown_sec):
            return False, ""
        row = self._gateway.get_cooldown(str(inst_id)) or {}
        return True, str(row.get("exit_reason") or "in_cooldown")

    def subpool(self) -> dict[str, int]:
        rows = self._open_positions()
        return {
            "count": len(rows),
            "long": sum(1 for r in rows if str(r.get("pos_side")) == "long"),
            "short": sum(1 for r in rows if str(r.get("pos_side")) == "short"),
        }
