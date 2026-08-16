"""PROP-20260816 双腿对冲策略 + 币池动态排名 测试套件。

验收对齐提案 §6:
    1. 确定性单元: 合并PnL计算 / regime门禁 / 单腿不达标→无仓 / 孤儿腿保护
    2. 集成全链: 强信号→双腿开仓→合并+4%→双腿同平→账本闭环
    3. V15 long_only 门禁（SHORT 拒单, LONG 不受影响）
    4. 动态分: 合并排序 / 冷启动 / 回写往返

隔离: conftest 将 HEDGE_POSITIONS_FILE / DYNAMIC_SCORES_FILE 重定向到 tmp_path,
测试永不触碰生产 scheduler_data。
"""
from dreamos.capabilities.trading.hedge_executor import (
    HedgeExecutor,
    HedgePair,
    MIN_LEG_CONF,
    TP_COMBINED_PCT,
    SL_COMBINED_PCT,
)
from dreamos.capabilities.trading import coin_selector
from dreamos.capabilities.trading.v15_executor import V15Executor

RANGE_REGIME = "RANGE_BOUND底部修复(长周期BEAR_TREND未破坏, 置信55%)"
BEAR_REGIME = "BEAR_TREND下行"
PRICES = {"AAA": 10.0, "BBB": 20.0}


def _sig(direction: str, conf: float) -> dict:
    return {"direction": direction, "confidence": conf}


def _cand(symbol: str, score: float = 0.8) -> dict:
    return {"symbol": symbol, "score": score}


class FakeClient:
    """实盘路径 fake（孤儿腿保护 / 真单分支用）。"""

    def __init__(self, short_fails: bool = False, close_fails: bool = False):
        self.short_fails = short_fails
        self.close_fails = close_fails
        self.calls = []

    def set_leverage(self, coin, lev):
        self.calls.append(("set_leverage", coin))

    def open_long(self, coin, usdt, leverage=5, tag="ab"):
        self.calls.append(("open_long", coin))
        return {"ok": True, "sz": usdt * leverage / 10.0, "filled": {"avgPx": 10.0}}

    def open_short(self, coin, usdt, leverage=5, tag="ab"):
        self.calls.append(("open_short", coin))
        if self.short_fails:
            return {"ok": False, "error": "simulated_short_failure"}
        return {"ok": True, "sz": usdt * leverage / 20.0, "filled": {"avgPx": 20.0}}

    def close_position(self, coin, tag="ab"):
        self.calls.append(("close_position", coin))
        if self.close_fails:
            return {"ok": False, "error": "simulated_close_failure"}
        return {"ok": True}


# ── 1. 确定性单元 ────────────────────────────────────────────────


def test_combined_pnl_math():
    """合并PnL: 长腿(10→10.4)+4%×150U=+6U, 短腿(20→19.2)+4%×150U=+6U → +12U=+4%。"""
    pair = HedgePair(
        pair_id="HP-T-001",
        long_symbol="AAA", long_entry=10.0, long_size=15.0,
        short_symbol="BBB", short_entry=20.0, short_size=7.5,
        notional_per_leg=150.0,
    )
    pnl, pct = HedgeExecutor.combined_pnl(pair, 10.4, 19.2)
    assert abs(pnl - 12.0) < 1e-9
    assert abs(pct - 0.04) < 1e-9


def test_regime_gate_blocks_non_range_bound():
    h = HedgeExecutor(dry_run=True)
    r = h.evaluate_entry(
        _cand("AAA"), _cand("BBB"), _sig("LONG", 0.8), _sig("SHORT", 0.8),
        BEAR_REGIME, PRICES,
    )
    assert r["status"] == "SKIPPED"
    assert r["reason"] == "regime_not_range_bound"
    assert not h.has_open_pair()


def test_conf_gate_blocks_weak_leg():
    """单腿 conf 不达标 → 无仓（宁缺毋滥）。"""
    h = HedgeExecutor(dry_run=True)
    r = h.evaluate_entry(
        _cand("AAA"), _cand("BBB"),
        _sig("LONG", 0.7), _sig("SHORT", MIN_LEG_CONF - 0.01),
        RANGE_REGIME, PRICES,
    )
    assert r["status"] == "SKIPPED"
    assert r["reason"] == "conf_below_gate"
    assert not h.has_open_pair()


def test_direction_mismatch_blocks():
    h = HedgeExecutor(dry_run=True)
    # 短腿 B层给出 LONG（方向不一致）→ 拒
    r = h.evaluate_entry(
        _cand("AAA"), _cand("BBB"), _sig("LONG", 0.8), _sig("LONG", 0.8),
        RANGE_REGIME, PRICES,
    )
    assert r["status"] == "SKIPPED"
    assert r["reason"] == "direction_mismatch"


def test_same_symbol_blocked():
    h = HedgeExecutor(dry_run=True)
    r = h.evaluate_entry(
        _cand("AAA"), _cand("AAA"), _sig("LONG", 0.8), _sig("SHORT", 0.8),
        RANGE_REGIME, PRICES,
    )
    assert r["status"] == "SKIPPED"
    assert r["reason"] == "same_symbol"


def test_orphan_leg_protection_real_mode():
    """实盘: 短腿开仓失败 → 立即平多腿, 账本记 ORPHAN_RECOVERED。"""
    fake = FakeClient(short_fails=True)
    h = HedgeExecutor(dry_run=False, client=fake)
    r = h.evaluate_entry(
        _cand("AAA"), _cand("BBB"), _sig("LONG", 0.8), _sig("SHORT", 0.8),
        RANGE_REGIME, PRICES,
    )
    assert r["status"] == "ORPHAN_RECOVERED"
    assert ("close_position", "AAA") in fake.calls
    assert not h.has_open_pair()


def test_real_mode_close_partial_keeps_pair_open():
    """实盘平仓单腿失败 → 不标记 CLOSED（下周期重试, 防账本漂移）。"""
    fake = FakeClient(close_fails=True)
    h = HedgeExecutor(dry_run=False, client=fake)
    r = h.evaluate_entry(
        _cand("AAA"), _cand("BBB"), _sig("LONG", 0.8), _sig("SHORT", 0.8),
        RANGE_REGIME, PRICES,
    )
    assert r["status"] == "OPEN"
    exits = h.manage_exits({"AAA": 10.8, "BBB": 20.0})  # +4% 触发 TP
    assert exits and exits[0]["action"] == "CLOSE_PARTIAL"
    assert h.has_open_pair()  # 仍是 OPEN, 等待重试


# ── 2. 集成全链（paper）─────────────────────────────────────────


def test_full_chain_paper_open_tp_close():
    """强信号→双腿开仓→合并+4%→双腿同平→账本闭环。"""
    h = HedgeExecutor(dry_run=True)
    r = h.evaluate_entry(
        _cand("AAA"), _cand("BBB"), _sig("LONG", 0.7), _sig("SHORT", 0.7),
        RANGE_REGIME, PRICES,
    )
    assert r["status"] == "OPEN"
    pair_id = r["pair_id"]
    assert h.has_open_pair()

    # 双腿各 +4% 有利 → 合并 +4% 触发 TP
    exits = h.manage_exits({"AAA": 10.4, "BBB": 19.2})
    assert len(exits) == 1
    assert exits[0]["action"] == "CLOSED"
    assert exits[0]["reason"] == "hedge_tp_combined"
    assert abs(exits[0]["combined_pct"] - 0.04) < 1e-6
    assert not h.has_open_pair()

    # 账本闭环: CLOSED + realized_pnl
    pair = h._pairs[pair_id]
    assert pair.status == "CLOSED"
    assert pair.close_reason == "hedge_tp_combined"
    assert abs(pair.realized_pnl - 12.0) < 1e-6


def test_full_chain_paper_sl_circuit_breaker():
    """合并回撤 -6% → 熔断双腿同平。"""
    h = HedgeExecutor(dry_run=True)
    h.evaluate_entry(
        _cand("AAA"), _cand("BBB"), _sig("LONG", 0.7), _sig("SHORT", 0.7),
        RANGE_REGIME, PRICES,
    )
    # 长腿 -12%（-18U）短腿持平 → 合并 -6%
    exits = h.manage_exits({"AAA": 8.8, "BBB": 20.0})
    assert len(exits) == 1
    assert exits[0]["reason"] == "hedge_sl_combined"
    assert exits[0]["combined_pct"] <= SL_COMBINED_PCT + 1e-9


def test_max_one_pair_concurrency():
    h = HedgeExecutor(dry_run=True)
    r1 = h.evaluate_entry(
        _cand("AAA"), _cand("BBB"), _sig("LONG", 0.7), _sig("SHORT", 0.7),
        RANGE_REGIME, PRICES,
    )
    assert r1["status"] == "OPEN"
    r2 = h.evaluate_entry(
        _cand("AAA"), _cand("BBB"), _sig("LONG", 0.7), _sig("SHORT", 0.7),
        RANGE_REGIME, PRICES,
    )
    assert r2["status"] == "SKIPPED"
    assert r2["reason"] == "open_pair_exists"


def test_ledger_persistence_roundtrip():
    """开仓落盘 → 新实例恢复账本（重启不丢账）。"""
    h1 = HedgeExecutor(dry_run=True)
    r = h1.evaluate_entry(
        _cand("AAA"), _cand("BBB"), _sig("LONG", 0.7), _sig("SHORT", 0.7),
        RANGE_REGIME, PRICES,
    )
    assert r["status"] == "OPEN"
    h2 = HedgeExecutor(dry_run=True)  # 重新加载
    assert h2.has_open_pair()
    assert h2.get_open_pair().pair_id == r["pair_id"]


def test_holding_inside_band_no_action():
    """合并 PnL 在 (-6%, +4%) 区间内 → 不触发动作。"""
    h = HedgeExecutor(dry_run=True)
    h.evaluate_entry(
        _cand("AAA"), _cand("BBB"), _sig("LONG", 0.7), _sig("SHORT", 0.7),
        RANGE_REGIME, PRICES,
    )
    exits = h.manage_exits({"AAA": 10.1, "BBB": 20.1})  # 微幅波动
    assert exits == []
    assert h.has_open_pair()


# ── 3. V15 long_only 门禁 ───────────────────────────────────────


def test_v15_long_only_rejects_short():
    ex = V15Executor(long_only=True, dry_run=True)
    r = ex.execute_signal({
        "symbol": "AAA", "direction": "SHORT", "confidence": 0.9, "entry_price": 10.0,
    })
    assert r["status"] == "REJECTED"
    assert r["reason"] == "v15_long_only"


def test_v15_long_only_allows_long():
    ex = V15Executor(long_only=True, dry_run=True)
    r = ex.execute_signal({
        "symbol": "AAA", "direction": "LONG", "confidence": 0.9, "entry_price": 10.0,
    })
    assert r["status"] == "OPEN"


def test_v15_default_allows_short_backward_compat():
    """默认 long_only=False → 行为与改造前一致（scan_main 存量路径不受影响）。"""
    ex = V15Executor(dry_run=True)
    r = ex.execute_signal({
        "symbol": "AAA", "direction": "SHORT", "confidence": 0.9, "entry_price": 10.0,
    })
    assert r["status"] == "OPEN"


# ── 4. 动态排名层 ───────────────────────────────────────────────


def test_merge_dynamic_scores_ranking():
    """merged = 0.7×weekly + 0.3×dyn; 冷启动 dyn=0.5。"""
    pool = [
        {"symbol": "A", "score": 0.9},
        {"symbol": "B", "score": 0.5},
        {"symbol": "C", "score": 0.6},
    ]
    dyn = {"A": {"dyn_score": 0.1}, "C": {"dyn_score": 0.9}}
    merged = coin_selector.merge_dynamic_scores(pool, dyn)
    # A: 0.7×0.9+0.3×0.1=0.66 | B: 0.7×0.5+0.3×0.5=0.50 | C: 0.7×0.6+0.3×0.9=0.69
    assert [m["symbol"] for m in merged] == ["C", "A", "B"]
    assert abs(merged[0]["merged_score"] - 0.69) < 1e-6
    assert abs(merged[1]["merged_score"] - 0.66) < 1e-6
    assert abs(merged[2]["merged_score"] - 0.50) < 1e-6


def test_merge_dynamic_scores_cold_start():
    """无动态分文件 → dyn=0.5 中性, 保持周报排名。"""
    pool = [{"symbol": "A", "score": 0.9}, {"symbol": "B", "score": 0.4}]
    merged = coin_selector.merge_dynamic_scores(pool, {})
    assert [m["symbol"] for m in merged] == ["A", "B"]
    assert all(m["dyn_score"] == 0.5 for m in merged)


def test_dynamic_score_writeback_roundtrip():
    coin_selector.record_dynamic_score("HEMI", 0.27, "LONG")
    coin_selector.record_dynamic_score("HEMI", 0.31, "LONG")
    coin_selector.record_dynamic_score("XMR", 0.4, "SHORT")
    scores = coin_selector.load_dynamic_scores()
    assert scores["HEMI"]["dyn_score"] == 0.31
    assert scores["HEMI"]["cycles_seen"] == 2
    assert scores["HEMI"]["last_dir"] == "LONG"
    assert scores["XMR"]["dyn_score"] == 0.4
