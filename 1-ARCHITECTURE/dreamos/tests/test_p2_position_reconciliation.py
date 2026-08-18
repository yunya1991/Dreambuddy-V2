"""PROP-20260816 P2 测试 —— 交易所侧平仓对账 (修复 F-2)。

2026-08-15 实盘验证: SOL 持仓被交易所 TP/SL 平掉时本程序收不到事件,
仓位消失后无 pnl 回填认知层 → E层 W/L/贝叶斯永远不更新。
对账契约:
  1. 快照 diff 发现消失持仓 → 查 userFills 确认 closedPnl!=0 的成交
  2. 确认成功 → _feed_cognitive_loop(px_source=real_fill) 回填认知
  3. 确认不到成交 → 只记日志,绝不喂认知 (E层数据完整性门禁)
"""
import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from dreamos.cli.auto_trader import AutoTrader


class _FakeHLClient:
    """伪造 Hyperliquid: userFills 可注入。"""

    user_addr = "0xTEST"

    def __init__(self, fills=None):
        self._fills = fills or []

    def _info(self, payload):
        assert payload.get("type") == "userFills"
        return self._fills


def _make_trader(monkeypatch, fills=None):
    trader = AutoTrader(dry_run=True, exchange="hyperliquid")
    monkeypatch.setattr(trader, "get_exchange_client", lambda: _FakeHLClient(fills))
    return trader


def _seed_snapshot(trader, symbol="SOL", entry=85.0, size=2.0, direction="SHORT", ago_s=3600):
    trader._snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    with open(trader._snapshot_path, "w") as f:
        json.dump({symbol: {
            "entry_price": entry, "size": size, "direction": direction,
            "ts": time.time() - ago_s,
        }}, f)


def test_reconcile_confirmed_close_feeds_cognition(monkeypatch):
    """持仓消失 + fills 确认平仓 → 真实 pnl 回填认知层。"""
    now_ms = int(time.time() * 1000)
    fills = [{
        "coin": "SOL", "px": "80.0", "sz": "2.0",
        "closedPnl": "10.0", "time": now_ms, "dir": "Close Short",
    }]
    trader = _make_trader(monkeypatch, fills)
    _seed_snapshot(trader)

    feed_calls = []
    monkeypatch.setattr(trader, "_feed_cognitive_loop", lambda **kw: feed_calls.append(kw))

    trader._reconcile_disappeared_positions([])  # SOL 已从交易所消失

    assert len(feed_calls) == 1, "确认平仓必须回填认知层"
    kw = feed_calls[0]
    assert kw["px_source"] == "real_fill"
    assert kw["symbol"] == "SOL"
    assert kw["direction"] == "SHORT"
    assert kw["exit_price"] == 80.0
    # 空头 85 → 80 = 盈利 (扣手续费后仍为正)
    assert kw["ret"] > 0
    assert "reconciled" in kw["exit_reason"]
    assert "closedPnl=10.00" in kw["exit_reason"]


def test_reconcile_no_fills_no_feed(monkeypatch):
    """持仓消失但查不到平仓成交 → 不喂认知 (数据完整性门禁)。"""
    trader = _make_trader(monkeypatch, fills=[])
    _seed_snapshot(trader)

    feed_calls = []
    monkeypatch.setattr(trader, "_feed_cognitive_loop", lambda **kw: feed_calls.append(kw))

    trader._reconcile_disappeared_positions([])

    assert feed_calls == [], "未确认成交不得喂认知层"


def test_reconcile_open_fill_only_no_feed(monkeypatch):
    """closedPnl=0 的开仓成交不算平仓 → 不喂认知。"""
    now_ms = int(time.time() * 1000)
    fills = [{"coin": "SOL", "px": "85.0", "sz": "2.0", "closedPnl": "0", "time": now_ms}]
    trader = _make_trader(monkeypatch, fills)
    _seed_snapshot(trader)

    feed_calls = []
    monkeypatch.setattr(trader, "_feed_cognitive_loop", lambda **kw: feed_calls.append(kw))

    trader._reconcile_disappeared_positions([])

    assert feed_calls == []


def test_reconcile_position_still_open_no_feed(monkeypatch):
    """持仓仍在 → 不触发对账。"""
    now_ms = int(time.time() * 1000)
    fills = [{"coin": "SOL", "px": "80.0", "sz": "2.0", "closedPnl": "10.0", "time": now_ms}]
    trader = _make_trader(monkeypatch, fills)
    _seed_snapshot(trader)

    feed_calls = []
    monkeypatch.setattr(trader, "_feed_cognitive_loop", lambda **kw: feed_calls.append(kw))

    trader._reconcile_disappeared_positions(
        [{"symbol": "SOL", "position_amt": -2.0, "entry_price": 85.0}]
    )

    assert feed_calls == []


def test_snapshot_roundtrip_preserves_first_seen_ts(monkeypatch):
    """持续持有的 symbol 保留首次观察 ts (对账窗口起点不漂移)。"""
    trader = _make_trader(monkeypatch)
    pos = [{"symbol": "SOL", "position_amt": -2.0, "entry_price": 85.0}]

    trader._save_position_snapshot(pos)
    snap1 = trader._load_position_snapshot()
    assert "SOL" in snap1
    ts1 = snap1["SOL"]["ts"]
    assert snap1["SOL"]["direction"] == "SHORT"
    assert snap1["SOL"]["size"] == 2.0

    time.sleep(0.01)
    trader._save_position_snapshot(pos)
    snap2 = trader._load_position_snapshot()
    assert snap2["SOL"]["ts"] == ts1, "持续持仓 ts 必须保持首次观察时间"

    # 新 symbol 获得新 ts
    trader._save_position_snapshot(pos + [{"symbol": "BTC-USDT", "position_amt": 0.1, "entry_price": 100.0}])
    snap3 = trader._load_position_snapshot()
    assert "BTC" in snap3, "USDT 后缀应被归一化"
    assert snap3["BTC"]["direction"] == "LONG"
