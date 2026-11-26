"""SL/TP 幂等与去重回归测试（重复设置止盈止损缺陷）。

背景：云端同一持仓出现多份 OCO（MU 6 份 / CRCL 3 份 / LINK 3 份），根因：
1. 同值 SL/TP 重复下发时仍新建 algo 单；
2. 撤单前置查询失败时静默继续挂单；
3. 补挂巡检只判断"有 SL/有 TP"，不清理重复单。
"""

from __future__ import annotations

import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
EXECUTORS = MODULE_ROOT / "executors"
for _p in (MODULE_ROOT, EXECUTORS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import sltp_reconcile  # noqa: E402
from executors.okx_client import OKXSimulatedClient  # noqa: E402

CFG = {
    "api_key": "k",
    "secret_key": "s",
    "passphrase": "p",
    "base_url": "https://www.okx.com",
    "simulated": False,
    "dry_run": False,
    "default_inst_id": "ETH-USDT-SWAP",
    "td_mode": "isolated",
}


def _make_client(pending_by_type, posts):
    """构造真实客户端，替换网络读写为内存桩。"""
    c = OKXSimulatedClient(CFG)
    c.get_instrument = lambda inst_id: {"ok": True, "tick_sz": 0.01, "lot_sz": 0.01}

    def fake_get(path, params=None, auth=True):
        if path == "/api/v5/trade/orders-algo-pending":
            ot = (params or {}).get("ordType")
            return pending_by_type.get(ot, {"code": "0", "msg": "", "data": []})
        return {"code": "0", "msg": "", "data": []}

    def fake_post(path, body, auth=True):
        posts.append((path, body))
        return {"code": "0", "msg": "", "data": [{"algoId": "new-1", "sCode": "0"}]}

    c._get = fake_get
    c._post = fake_post
    c._audit_log = lambda *a, **k: None
    return c


def test_same_sltp_is_noop_without_new_algo_order():
    """已存在同价 OCO 时不得再下单，也不得撤单。"""
    existing = [
        {
            "algoId": "111",
            "posSide": "long",
            "state": "live",
            "sz": "1",
            "slTriggerPx": "100",
            "tpTriggerPx": "110",
        }
    ]
    posts = []
    c = _make_client({"oco": {"code": "0", "msg": "", "data": existing}}, posts)

    r = c.place_stop_loss_take_profit(
        inst_id="ETH-USDT-SWAP",
        pos_side="long",
        stop_loss_px=100,
        take_profit_px=110,
        sz=1,
    )

    assert r.get("ok") is True, r
    assert r.get("unchanged") is True, r
    assert not [p for p in posts if p[0] == "/api/v5/trade/order-algo"], "同值不应重复挂单"
    assert not [p for p in posts if p[0] == "/api/v5/trade/cancel-algos"], "同值不应撤单"


def test_abort_place_when_pending_query_fails():
    """撤单前置查询失败时必须中止挂单，不能盲挂造成重复。"""
    boom = {"code": "50011", "msg": "Too Many Requests", "data": []}
    posts = []
    c = _make_client({"oco": boom, "conditional": boom}, posts)

    r = c.place_stop_loss_take_profit(
        inst_id="ETH-USDT-SWAP",
        pos_side="long",
        stop_loss_px=99,
        take_profit_px=111,
        sz=1,
    )

    assert r.get("ok") is False, r
    assert "cancel" in str(r.get("error", "")).lower()
    assert not [p for p in posts if p[0] == "/api/v5/trade/order-algo"], "查询失败时不应下单"


class _FakeOKX:
    def __init__(self, positions, algos):
        self._positions = positions
        self._algos = [dict(a) for a in algos]
        self.cancelled: list[tuple[str, str]] = []
        self.placed: list[dict] = []

    def get_positions(self, inst_id=None):
        return {"ok": True, "positions": self._positions}

    def get_algo_orders(self, inst_id=None):
        rows = [dict(a) for a in self._algos if a.get("inst_id") == inst_id]
        return {"ok": True, "query_ok": True, "errors": [], "orders": rows, "count": len(rows)}

    def cancel_algo_order(self, inst_id=None, algo_id=None):
        self.cancelled.append((inst_id, str(algo_id)))
        self._algos = [a for a in self._algos if str(a.get("algo_id")) != str(algo_id)]
        return {"ok": True}

    def place_stop_loss_take_profit(self, **kwargs):
        self.placed.append(kwargs)
        return {"ok": True}


class _RateLimitedOKX(_FakeOKX):
    """首查命中 50011 限流，重试成功；用于验证限流不误记为补挂失败。"""

    def __init__(self, positions, algos):
        super().__init__(positions, algos)
        self.query_count = 0

    def get_algo_orders(self, inst_id=None):
        self.query_count += 1
        if self.query_count == 1:
            return {
                "ok": True,
                "query_ok": False,
                "errors": ["conditional:50011:Too Many Requests"],
                "orders": [],
                "count": 0,
            }
        return super().get_algo_orders(inst_id)


def test_reconcile_retries_on_rate_limit_without_counting_failure(tmp_path, monkeypatch):
    """50011 限流应退避重试一次，重试成功不计 failed（防 P1 误报）。"""
    monkeypatch.setattr(sltp_reconcile, "QUERY_RETRY_SLEEP_SEC", 0)
    pos = {
        "inst_id": "AMZN-USDT-SWAP",
        "pos_side": "long",
        "pos": 0.38,
        "avg_px": 257.26,
        "mark_px": 247.19,
        "upl_ratio": -0.117,
    }
    algos = [
        {
            "inst_id": "AMZN-USDT-SWAP",
            "algo_id": "4121721655176310785",
            "pos_side": "long",
            "ord_type": "oco",
            "sl_trigger_px": 235.52,
            "tp_trigger_px": 295.85,
            "sz": 0.38,
            "state": "live",
        }
    ]
    okx = _RateLimitedOKX([pos], algos)

    res = sltp_reconcile.reconcile_sltp(okx, audit_path=tmp_path / "audit.jsonl")

    assert res["failed"] == 0, res
    assert res["skipped"] == 1, res
    assert okx.query_count == 2, "首次限流后应重试一次"
    assert okx.placed == [], "重试拿到已挂 OCO 后不得再补挂"


def test_reconcile_cancels_duplicate_algos_keeps_newest(tmp_path):
    """巡检应清理同持仓重复 OCO，只保留最新一条。"""
    pos = {
        "inst_id": "MU-USDT-SWAP",
        "pos_side": "short",
        "pos": -0.16,
        "avg_px": 600.0,
        "mark_px": 620.0,
        "upl_ratio": -0.01,
    }
    algos = [
        {
            "inst_id": "MU-USDT-SWAP",
            "algo_id": "100",
            "pos_side": "short",
            "ord_type": "oco",
            "sl_trigger_px": 639.28,
            "tp_trigger_px": 560.13,
            "sz": 0.16,
            "state": "live",
        },
        {
            "inst_id": "MU-USDT-SWAP",
            "algo_id": "200",
            "pos_side": "short",
            "ord_type": "oco",
            "sl_trigger_px": 639.28,
            "tp_trigger_px": 560.13,
            "sz": 0.16,
            "state": "live",
        },
        {
            "inst_id": "MU-USDT-SWAP",
            "algo_id": "300",
            "pos_side": "short",
            "ord_type": "oco",
            "sl_trigger_px": 639.28,
            "tp_trigger_px": 560.13,
            "sz": 0.16,
            "state": "live",
        },
    ]
    okx = _FakeOKX([pos], algos)

    res = sltp_reconcile.reconcile_sltp(okx, audit_path=tmp_path / "audit.jsonl")

    assert res["deduped"] == 2, res
    assert sorted(a for _, a in okx.cancelled) == ["100", "200"]
    assert [a["algo_id"] for a in okx._algos] == ["300"]
    assert okx.placed == [], "去重后仍保留完整 OCO，无需补挂"
