"""幽灵仓落账价测试（2026-11-14）

原实现用 entry_price 作为 ghost 平仓价，导致被交易所 SL/TP 成交的仓位
在账本上记为"平进平出"。修复后优先使用交易所真实成交价。
"""

from __future__ import annotations

from dreambuddy_evolution.execution.exit_loop import EvolutionExitLoop


class _GhostOkx:
    def __init__(self, fill_px: float = 0.0):
        self.fill_px = fill_px

    def get_positions(self, inst_id=None):
        return {"ok": True, "positions": []}

    def get_recent_fills(self, inst_id=None, limit=10):
        if self.fill_px <= 0:
            return {"ok": True, "fills": [], "count": 0}
        return {"ok": True, "fills": [{"fill_px": self.fill_px}], "count": 1}


def _run_ghost(okx):
    loop = EvolutionExitLoop(okx_client=okx, enable_rl=False)
    seen = []
    loop.run(
        [
            {
                "inst_id": "ETH-USDT-SWAP",
                "coin": "ETH",
                "pos_side": "long",
                "entry_price": 100.0,
                "current_price": 0.0,
                "position_usdt": 0.0,
            }
        ],
        on_ghost=lambda pos, px: seen.append(px),
    )
    return seen


def test_ghost_uses_exchange_fill_price():
    seen = _run_ghost(_GhostOkx(fill_px=95.0))
    assert seen == [95.0]


def test_ghost_falls_back_to_entry_when_no_fills():
    seen = _run_ghost(_GhostOkx(fill_px=0.0))
    assert seen == [100.0]


def test_ghost_falls_back_when_fill_price_is_dirty():
    """偏离入场价 30% 以上的成交价视为脏数据。"""
    seen = _run_ghost(_GhostOkx(fill_px=10.0))
    assert seen == [100.0]
