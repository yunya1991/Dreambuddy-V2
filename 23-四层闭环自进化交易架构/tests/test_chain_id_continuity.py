"""N10 → N12/N14 chain_id 贯通回归。

背景：EntryRunner 构造后给 handler 赋 `_build_position_callback`，但
ResultAggregator 在 handler 构造时已缓存该回调（None），导致建仓回调永久为空，
N10 信号与执行段无法串成同一 chain。本文件锁定：
  1) 回调注入必须穿透到 aggregator；
  2) N10 decision_id/chain_id 统一使用合约 inst 命名空间；
  3) 执行段 N12/N14 必须复用上游 decision_id 作为 chain_id。
"""

from __future__ import annotations

import json
from pathlib import Path

from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
from dreambuddy_evolution.engines.result_aggregator import ResultAggregator
from dreambuddy_evolution.execution import EvolutionEntryLoop
from dreambuddy_evolution.scripts.entry_runner import EntryRunner


def _chain_rows(tmp_path: Path) -> list[dict]:
    rows: list[dict] = []
    for path in tmp_path.glob("chain_events-*.jsonl"):
        rows.extend(json.loads(line) for line in path.read_text().splitlines() if line.strip())
    return rows


class _Adapter:
    def assemble(self, symbol: str, inst_id: str):
        return {"close": [100.0] * 30}


class _Result:
    executed = True
    passed = True
    reason = ""
    reason_code = ""
    order_result = {"ord_id": "ord-open", "avg_px": 100.0}
    sltp_result = None


class _Gateway:
    def __init__(self):
        self.calls: list[dict] = []

    def submit(self, decision):
        self.calls.append(decision)
        return _Result()


def test_entry_runner_callback_reaches_aggregator(monkeypatch, tmp_path):
    """EntryRunner 注入的回调必须真正驱动 N10 与建仓链路。"""
    monkeypatch.setenv("EVOLUTION_CHAIN_EVENTS_DIR", str(tmp_path))
    gateway = _Gateway()
    loop = EvolutionEntryLoop(
        gateway=gateway,
        runtime_dir=tmp_path,
        log_fn=lambda *a, **k: None,
        authority_fn=lambda tag: True,
        blacklist_fn=lambda sym: (False, ""),
        fuse_fn=lambda: None,
        has_position_fn=lambda inst: False,
        cooldown_fn=lambda inst, d: (False, ""),
        direction_state_fn=lambda sym, d: "NEUTRAL",
        subpool_fn=lambda: {"count": 0, "long": 0, "short": 0, "probe_count": 0},
        short_ban_fn=lambda sym, d: {},
        equity_fn=lambda: 1000.0,
        track_mult_fn=lambda kline: 1.0,
        asset_class_fn=lambda sym: "crypto_usdt",
        macro_constraint_fn=lambda cls: {},
        used_notional_fn=lambda: {},
        min_sz_fn=lambda inst: 0.1,
        price_fn=lambda inst: 100.0,
    )
    handler = KlineEventHandler(mode="Phase2", build_position_callback=None)
    EntryRunner(adapter=_Adapter(), handler=handler, loop=loop, symbols=["BTC"])

    handler._trigger_build_position("BTC", "long", "d1", 0.6)

    assert len(gateway.calls) == 1, "回调未穿透到 ResultAggregator"
    rows = _chain_rows(tmp_path)
    n10 = [r for r in rows if r["stage"] == "N10" and r["status"] == "pass"]
    n12 = [r for r in rows if r["stage"] == "N12"]
    assert len(n10) == 1 and len(n12) == 1
    assert n10[0]["chain_id"] == n12[0]["chain_id"]


def test_n10_uses_inst_namespace(monkeypatch, tmp_path):
    monkeypatch.setenv("EVOLUTION_CHAIN_EVENTS_DIR", str(tmp_path))
    captured: dict = {}
    agg = ResultAggregator(
        build_position_callback=lambda **kw: captured.update(kw), router=object()
    )
    agg.trigger_build_position("BTC", "long", "d1", 0.6)

    signal = captured["signal"]
    assert signal["decision_id"].startswith("dec-23-BTC-USDT-SWAP-open-")
    assert signal["symbol"] == "BTC-USDT-SWAP"
    # 回调参数仍保留原始币名，兼容 11/旧调用方
    assert captured["symbol"] == "BTC"

    rows = _chain_rows(tmp_path)
    n10 = [r for r in rows if r["stage"] == "N10" and r["status"] == "pass"]
    assert n10[0]["chain_id"] == signal["decision_id"]


def test_entry_loop_reuses_upstream_chain_id(monkeypatch, tmp_path):
    monkeypatch.setenv("EVOLUTION_CHAIN_EVENTS_DIR", str(tmp_path))
    gateway = _Gateway()
    loop = EvolutionEntryLoop(
        gateway=gateway,
        runtime_dir=tmp_path,
        log_fn=lambda *a, **k: None,
        authority_fn=lambda tag: True,
        blacklist_fn=lambda sym: (False, ""),
        fuse_fn=lambda: None,
        has_position_fn=lambda inst: False,
        cooldown_fn=lambda inst, d: (False, ""),
        direction_state_fn=lambda sym, d: "NEUTRAL",
        subpool_fn=lambda: {"count": 0, "long": 0, "short": 0, "probe_count": 0},
        short_ban_fn=lambda sym, d: {},
        equity_fn=lambda: 1000.0,
        track_mult_fn=lambda kline: 1.0,
        asset_class_fn=lambda sym: "crypto_usdt",
        macro_constraint_fn=lambda cls: {},
        used_notional_fn=lambda: {},
        min_sz_fn=lambda inst: 0.1,
        price_fn=lambda inst: 100.0,
    )
    out = loop.run(
        symbol="BTC",
        action="long",
        u_open=0.5,
        d_star="d1",
        confidence=0.6,
        signal={"decision_id": "dec-upstream-1", "payload": {"chain_id": "dec-upstream-1"}},
    )

    assert out["status"] == "opened"
    assert gateway.calls[0]["payload"]["chain_id"] == "dec-upstream-1"
    rows = _chain_rows(tmp_path)
    n12 = [r for r in rows if r["stage"] == "N12"]
    assert n12 and all(r["chain_id"] == "dec-upstream-1" for r in n12)
