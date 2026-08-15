"""P1-3 real_fill 守卫测试 —— 模拟平仓不得污染认知层。

背景(2026-08-15 实盘验证发现): run_exit_check_all 的平仓回填路径
对 dry_run/估算平仓也无条件调用 _feed_cognitive_loop(),会把模拟 pnl
喂进 record_real_exit() → 认知层记假账(真单未平, W/L/lessons 先污染)。

守卫契约: 仅 px_source == "real_fill" (交易所真实成交均价) 进认知层。
"""
import pytest
from pathlib import Path
import sys

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from dreamos.cli.auto_trader import AutoTrader


class _FakeAsterClient:
    """伪造交易所: 1 个 BTC 空头持仓。"""

    def _aster_fetch_positions(self):
        return ([{
            "coin": "BTC",
            "entry_px": "100.0",
            "position_amt": "-1.0",
            "leverage": "1",
            "mark_px": "105.0",
            "unrealized_pnl_u": "-5.0",
        }], None)


def _make_trader(monkeypatch, feed_calls, exec_result_override=None):
    trader = AutoTrader(dry_run=True, exchange="aster")
    monkeypatch.setattr(trader, "get_exchange_client", lambda: _FakeAsterClient())
    # 强制触发离场决策
    monkeypatch.setattr(
        trader, "check_exit",
        lambda symbol, entry_price, direction: {
            "exit": True, "exit_price": 105.0, "reason": "SL hit",
        },
    )
    # 阻断旁路写入
    monkeypatch.setattr(trader, "update_exit_feedback", lambda *a, **k: True)
    monkeypatch.setattr(
        trader, "_feed_cognitive_loop",
        lambda **kw: feed_calls.append(kw),
    )
    if exec_result_override is not None:
        monkeypatch.setattr(trader, "execute_trade", lambda order: exec_result_override)
    return trader


def test_p1_3_guard_dry_run_exit_not_fed(monkeypatch):
    """dry_run 模拟平仓 → 不得喂认知层。"""
    feed_calls = []
    trader = _make_trader(monkeypatch, feed_calls)  # execute_trade 走真实 dry_run 分支

    result = trader.run_exit_check_all()

    assert result.get("exits") == 1, f"离场路径应执行一次: {result}"
    assert feed_calls == [], (
        f"dry_run 平仓喂入了认知层(污染): {feed_calls}"
    )


def test_p1_3_guard_estimated_exit_not_fed(monkeypatch):
    """实盘但无成交回报(估算价降级) → 不得喂认知层。"""
    feed_calls = []
    trader = _make_trader(
        monkeypatch, feed_calls,
        exec_result_override={"dry_run": False, "real_fill_price": 0},
    )

    result = trader.run_exit_check_all()

    assert result.get("exits") == 1
    assert feed_calls == [], f"估算价平仓喂入了认知层(污染): {feed_calls}"


def test_p1_3_guard_real_fill_is_fed(monkeypatch):
    """交易所真实成交平仓 → 必须喂认知层(闭环不得误伤)。"""
    feed_calls = []
    trader = _make_trader(
        monkeypatch, feed_calls,
        exec_result_override={"result": "SUCCESS", "dry_run": False, "real_fill_price": "104.8"},
    )

    result = trader.run_exit_check_all()

    assert result.get("exits") == 1
    assert len(feed_calls) == 1, "real_fill 平仓必须回填认知层"
    kw = feed_calls[0]
    assert kw["px_source"] == "real_fill"
    assert kw["symbol"] == "BTC"
    assert kw["direction"] == "SHORT"
    assert kw["exit_price"] == pytest.approx(104.8)
    # 空头: entry 100 → exit 104.8 = 亏损, ret 已扣手续费
    assert kw["ret"] < 0
