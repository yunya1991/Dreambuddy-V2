"""账本三层口径一致性回归：positions / domain_positions / v_effective 必须对齐。

覆盖根因（2026-11-27 巡检发现）：
- A: reconcile(source="22-reconciled") 漏关 50-nn/23/11 自动管理源的幽灵仓
- B: record_fill 全平后 L1 positions.status 留 open（应为 closed）→ 产生 qty=0 status=open 幽灵行
- C: set_status 未传 domain 时 L2 domain_positions 不同步
- C2: set_status("closed") 不清零 qty → status=closed 但 qty>0（BNB 17 张同类）
- 自愈: 历史坏行（status=open 且 qty=0 且 closed_at 非空）经 reconcile 翻为 closed
- 安全: legacy / 空 source 的人工补录行不被 reconcile 自动关闭
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # 22-执行引擎中心
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from position_ledger import PositionLedger  # noqa: E402


def _ledger(tmp_path, name: str = "consistency.db") -> PositionLedger:
    return PositionLedger(tmp_path / name)


def _raw_l1(led: PositionLedger, inst_id: str, pos_side: str):
    with led._connect() as conn:
        return conn.execute(
            "SELECT qty, status, closed_at, source FROM positions"
            " WHERE inst_id=? AND pos_side=?",
            (inst_id, pos_side),
        ).fetchone()


def _raw_l2(led: PositionLedger, inst_id: str, pos_side: str, domain: str):
    with led._connect() as conn:
        return conn.execute(
            "SELECT qty, status, closed_at FROM domain_positions"
            " WHERE inst_id=? AND pos_side=? AND domain=?",
            (inst_id, pos_side, domain),
        ).fetchone()


# ── 根因 A：reconcile 必须能关闭 50-nn 幽灵仓（连续 2 轮确认） ──
def test_reconcile_closes_50_nn_ghost_position(tmp_path):
    led = _ledger(tmp_path)
    led.record_fill("NVDA-USDT-SWAP", "short", "open", 5.0, 120.0, source="50-nn", domain="50")

    # 第一轮缺失：不下结论（防 OKX 快照瞬时不全）
    first = led.reconcile([], source="22-reconciled", ghost_confirm=lambda _i, _s: False)
    assert first["closed"] == 0
    assert led.get_position("NVDA-USDT-SWAP", "short") is not None

    # 第二轮确认缺失：关闭
    second = led.reconcile([], source="22-reconciled", ghost_confirm=lambda _i, _s: True)
    assert second["closed"] == 1
    assert led.get_position("NVDA-USDT-SWAP", "short") is None

    l1 = _raw_l1(led, "NVDA-USDT-SWAP", "short")
    assert l1["qty"] == 0.0 and l1["status"] == "closed"
    l2 = _raw_l2(led, "NVDA-USDT-SWAP", "short", "50")
    assert l2 is not None and l2["qty"] == 0.0 and l2["status"] == "closed"


def test_reconcile_closes_23_evolution_ghost_position(tmp_path):
    """23-evolution 幽灵仓同样须被对账关闭（23 自有出口可能漏落账）。"""
    led = _ledger(tmp_path)
    led.record_fill("UNI-USDT-SWAP", "long", "open", 20.0, 8.0, source="23-evolution")

    led.reconcile([], source="22-reconciled", ghost_confirm=lambda _i, _s: True)

    assert led.get_position("UNI-USDT-SWAP", "long") is None
    assert _raw_l1(led, "UNI-USDT-SWAP", "long")["status"] == "closed"


# ── 根因 A 之二：50-nn 数量漂移必须被校正 ──
def test_reconcile_corrects_50_nn_qty_drift(tmp_path):
    led = _ledger(tmp_path)
    led.record_fill("COIN-USDT-SWAP", "short", "open", 10.0, 200.0, source="50-nn", domain="50")

    # 交易所报告数量减半（部分平仓未走 record_fill），且不是本对账源写入
    out = led.reconcile(
        [{"inst_id": "COIN-USDT-SWAP", "pos_side": "short", "qty": 5.0, "avg_entry": 200.0}],
        source="22-reconciled",
    )
    assert out["updated"] == 1
    pos = led.get_position("COIN-USDT-SWAP", "short")
    assert pos["qty"] == 5.0
    # 真实流水保留原 source 与均价，不覆盖成 22-reconciled
    assert pos["source"] == "50-nn"
    assert pos["avg_entry"] == 200.0


# ── 安全边界：legacy / 空 source 不被自动关闭 ──
def test_reconcile_does_not_close_manual_legacy_source(tmp_path):
    led = _ledger(tmp_path)
    # 人工补录行（source 空 / legacy）：交易所无此仓也不应被 reconcile 自动平掉
    led.record_fill("GOLD-USDT-SWAP", "long", "open", 1.0, 2000.0, source="")
    with led._connect() as conn:
        conn.execute("UPDATE positions SET source='' WHERE inst_id=?", ("GOLD-USDT-SWAP",))

    out = led.reconcile([], source="22-reconciled", ghost_confirm=lambda _i, _s: True)
    assert out["closed"] == 0
    assert led.get_position("GOLD-USDT-SWAP", "long") is not None


# ── 根因 B：全平后 L1 status 必须为 closed ──
def test_full_close_sets_l1_status_closed(tmp_path):
    led = _ledger(tmp_path)
    led.record_fill("WIF-USDT-SWAP", "long", "open", 10.0, 2.0, source="23-evolution")
    led.apply_partial_close("WIF-USDT-SWAP", "long", 10.0, 2.5, source="23-evolution")

    l1 = _raw_l1(led, "WIF-USDT-SWAP", "long")
    assert l1["qty"] == 0.0
    assert l1["status"] == "closed"
    assert l1["closed_at"] is not None


def test_partial_close_keeps_l1_status_open(tmp_path):
    led = _ledger(tmp_path)
    led.record_fill("NEAR-USDT-SWAP", "long", "open", 10.0, 3.0, source="23-evolution")
    led.apply_partial_close("NEAR-USDT-SWAP", "long", 4.0, 3.5, source="23-evolution")

    l1 = _raw_l1(led, "NEAR-USDT-SWAP", "long")
    assert l1["qty"] == 6.0
    assert l1["status"] == "open"
    assert l1["closed_at"] in (None, "")


# ── 根因 C：set_status 未传 domain 也必须同步 L2 ──
def test_set_status_closed_syncs_l2_without_domain(tmp_path):
    led = _ledger(tmp_path)
    led.record_fill("ARB-USDT-SWAP", "long", "open", 3.0, 1.0, source="50-nn", domain="50")

    ok = led.set_status("ARB-USDT-SWAP", "long", "closed")
    assert ok is True

    l2 = _raw_l2(led, "ARB-USDT-SWAP", "long", "50")
    assert l2 is not None and l2["status"] == "closed"


# ── 根因 C2：set_status("closed") 必须清零 qty，消除 closed 但 qty>0 ──
def test_set_status_closed_zeroes_qty(tmp_path):
    led = _ledger(tmp_path)
    led.record_fill("DOT-USDT-SWAP", "long", "open", 5.0, 7.0, source="23-evolution")

    led.set_status("DOT-USDT-SWAP", "long", "closed")

    l1 = _raw_l1(led, "DOT-USDT-SWAP", "long")
    assert l1["status"] == "closed" and l1["qty"] == 0.0
    l2 = _raw_l2(led, "DOT-USDT-SWAP", "long", "23")
    assert l2["status"] == "closed" and l2["qty"] == 0.0
    # 三层口径一致：qty 汇总为 0
    assert led.position_qty_sum() == 0.0
    assert led.domain_qty_sum() == 0.0


# ── 自愈：历史坏行被 reconcile 翻正 ──
def test_reconcile_self_heals_open_qty_zero_ghost(tmp_path):
    """存量 status=open 但 qty=0 且 closed_at 非空的坏行，reconcile 必须翻为 closed。"""
    led = _ledger(tmp_path)
    led.record_fill("ETH-USDT-SWAP", "long", "open", 1.0, 1800.0, source="22-reconciled")
    with led._connect() as conn:
        conn.execute(
            "UPDATE positions SET qty=0, closed_at='2026-11-20T00:00:00Z'"
            " WHERE inst_id=? AND pos_side=?",
            ("ETH-USDT-SWAP", "long"),
        )
    # 复现生产坏行：status 仍是 open（record_fill 旧路径未翻）
    assert _raw_l1(led, "ETH-USDT-SWAP", "long")["status"] == "open"

    led.reconcile([], source="22-reconciled")

    assert _raw_l1(led, "ETH-USDT-SWAP", "long")["status"] == "closed"


def test_reconcile_self_heal_is_idempotent(tmp_path):
    led = _ledger(tmp_path)
    led.record_fill("ETH-USDT-SWAP", "long", "open", 1.0, 1800.0, source="22-reconciled")
    with led._connect() as conn:
        conn.execute(
            "UPDATE positions SET qty=0, closed_at='2026-11-20T00:00:00Z'"
            " WHERE inst_id=? AND pos_side=?",
            ("ETH-USDT-SWAP", "long"),
        )
    led.reconcile([], source="22-reconciled")
    led.reconcile([], source="22-reconciled")  # 复跑不得重复落账/报错

    fills = [r for r in led.recent_fills(10) if r["action"] == "close"]
    assert len(fills) == 0  # 自愈只翻状态，不重复写 close 成交
