"""22 x1_live_executor 风控与幂等测试（不触发真实下单）。"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_22_DIR = Path(__file__).resolve().parents[1]
if str(_22_DIR) not in sys.path:
    sys.path.insert(0, str(_22_DIR))

import x1_live_executor as ex  # noqa: E402


def _live_decision(**overrides):
    base = {
        "decision_id": "50-nn|AVAX-USDT-SWAP|1",
        "signal_id": "50-nn|AVAX-USDT-SWAP|1",
        "source": "50-nn",
        "mode": "live",
        "shadow": False,
        "symbol": "AVAX-USDT-SWAP",
        "direction": "long",
        "mandate_id": "mandate-20261113-50-live-avax",
        "execution": {"outcome": "live:50-bypass", "allowed": True},
    }
    base.update(overrides)
    return base


def test_check_rejects_shadow_decision():
    assert ex._check(_live_decision(mode="shadow", shadow=True)) == "not_live_decision"


def test_check_rejects_denied_rights():
    decision = _live_decision(execution={"outcome": "paper", "allowed": True})
    assert ex._check(decision) == "execution_rights_denied"


def test_check_rejects_over_limit_notional():
    assert ex._check(_live_decision(notional_usdt=400)) == "notional_limit"


def test_dry_run_records_without_bridge(monkeypatch, tmp_path):
    monkeypatch.setattr(ex, "_LEDGER", tmp_path / "fills.jsonl")
    monkeypatch.setattr(ex, "_LEDGER_DIR", tmp_path)
    monkeypatch.setattr(ex, "_STATE", tmp_path / "processed.json")
    # 本用例只验证"记账不触桥"，13 判定由 risk_bridge 单测覆盖
    monkeypatch.setattr(
        ex,
        "precheck",
        lambda decision, **kw: {
            "passed": True,
            "reason_code": "OK",
            "reason": "stub",
            "equity": 10000.0,
            "equity_source": "stub",
            "notional_usdt": 100.0,
            "leverage": 3,
            "source": "13-pre-trade-gate",
        },
    )
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text(json.dumps(_live_decision(), ensure_ascii=False) + "\n", encoding="utf-8")

    result = ex.run(outbox, dry_run=True, limit=10)
    assert result["executed"] == 1
    row = json.loads((tmp_path / "fills.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["result"]["dry_run"] is True
    assert row["risk"]["reason_code"] == "OK"

    again = ex.run(outbox, dry_run=True, limit=10)
    assert again["executed"] == 1  # dry-run 不写 processed，真实执行仍会触发
    assert again["skipped"] == 0


def test_risk_blocked_skips_execution(monkeypatch, tmp_path):
    monkeypatch.setattr(ex, "_LEDGER", tmp_path / "fills.jsonl")
    monkeypatch.setattr(ex, "_LEDGER_DIR", tmp_path)
    monkeypatch.setattr(ex, "_STATE", tmp_path / "processed.json")
    monkeypatch.setattr(
        ex,
        "precheck",
        lambda decision, **kw: {
            "passed": False,
            "reason_code": "SIZING_BELOW_MIN",
            "reason": "定容不足",
        },
    )
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text(json.dumps(_live_decision(), ensure_ascii=False) + "\n", encoding="utf-8")

    result = ex.run(outbox, dry_run=True, limit=10)
    assert result["executed"] == 0
    assert result["skipped"] == 1
    assert result["risk_rejected"][0]["reason_code"] == "SIZING_BELOW_MIN"
    assert not (tmp_path / "fills.jsonl").exists()


def _stub_pass_risk():
    return {
        "passed": True,
        "reason_code": "OK",
        "reason": "stub",
        "equity": 730.0,
        "equity_source": "stub",
        "notional_usdt": 73.0,
        "leverage": 3,
        "source": "13-pre-trade-gate",
    }


def test_position_guard_blocks_existing_symbol(monkeypatch, tmp_path):
    monkeypatch.setattr(ex, "_LEDGER", tmp_path / "fills.jsonl")
    monkeypatch.setattr(ex, "_LEDGER_DIR", tmp_path)
    monkeypatch.setattr(ex, "_STATE", tmp_path / "processed.json")
    monkeypatch.setattr(ex, "precheck", lambda decision, **kw: _stub_pass_risk())
    monkeypatch.setattr(
        ex,
        "_bridge_call",
        lambda payload, timeout=90: {
            "ok": True,
            "positions": [{"inst_id": "AVAX-USDT-SWAP", "pos": 1.0}],
        },
    )
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text(json.dumps(_live_decision(), ensure_ascii=False) + "\n", encoding="utf-8")

    result = ex.run(outbox, dry_run=False, limit=10)
    assert result["executed"] == 0
    assert result["skipped"] == 1
    assert result["position_guard_rejected"][0]["reason"] == "symbol_already_open"
    assert not (tmp_path / "fills.jsonl").exists()


def test_position_guard_fail_closed_on_query_error(monkeypatch, tmp_path):
    monkeypatch.setattr(ex, "_LEDGER", tmp_path / "fills.jsonl")
    monkeypatch.setattr(ex, "_LEDGER_DIR", tmp_path)
    monkeypatch.setattr(ex, "_STATE", tmp_path / "processed.json")
    monkeypatch.setattr(ex, "precheck", lambda decision, **kw: _stub_pass_risk())
    monkeypatch.setattr(
        ex, "_bridge_call", lambda payload, timeout=90: {"ok": False, "error": "no creds"}
    )
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text(json.dumps(_live_decision(), ensure_ascii=False) + "\n", encoding="utf-8")

    result = ex.run(outbox, dry_run=False, limit=10)
    assert result["executed"] == 0
    assert result["position_guard_rejected"][0]["reason"] == "position_query_failed"
    # 临时故障不得落幂等：下一轮必须重试
    state = json.loads((tmp_path / "processed.json").read_text(encoding="utf-8"))
    assert state.get("processed", {}) == {}


def test_position_guard_allows_flat_symbol(monkeypatch, tmp_path):
    monkeypatch.setattr(ex, "_LEDGER", tmp_path / "fills.jsonl")
    monkeypatch.setattr(ex, "_LEDGER_DIR", tmp_path)
    monkeypatch.setattr(ex, "_STATE", tmp_path / "processed.json")
    monkeypatch.setattr(ex, "precheck", lambda decision, **kw: _stub_pass_risk())
    monkeypatch.setattr(
        ex,
        "_bridge_call",
        lambda payload, timeout=90: (
            {"ok": True, "positions": []}
            if payload.get("action") == "status"
            else {"ok": True, "order_id": "ord-1", "reference_px": 100.0}
        ),
    )
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text(json.dumps(_live_decision(), ensure_ascii=False) + "\n", encoding="utf-8")

    result = ex.run(outbox, dry_run=False, limit=10)
    assert result["executed"] == 1
    row = json.loads((tmp_path / "fills.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["request"]["notional_usdt"] == 300.0
    assert row["request"]["margin_usdt"] == 100.0
    assert row["order_placed"] is True


def test_cooldown_blocks_reentry_within_8h(monkeypatch, tmp_path):
    monkeypatch.setattr(ex, "_LEDGER", tmp_path / "fills.jsonl")
    monkeypatch.setattr(ex, "_LEDGER_DIR", tmp_path)
    monkeypatch.setattr(ex, "_STATE", tmp_path / "processed.json")
    monkeypatch.setattr(ex, "precheck", lambda decision, **kw: _stub_pass_risk())
    monkeypatch.setattr(
        ex, "_bridge_call", lambda payload, timeout=90: {"ok": True, "positions": []}
    )
    (tmp_path / "processed.json").write_text(
        json.dumps({"processed": {}, "last_entry": {"AVAX-USDT-SWAP": time.time()}}),
        encoding="utf-8",
    )
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text(
        json.dumps(_live_decision(decision_id="50-nn|new-batch"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    result = ex.run(outbox, dry_run=False, limit=10)
    assert result["executed"] == 0
    assert result["skipped"] == 1
    assert result["cooldown_rejected"][0]["symbol"] == "AVAX-USDT-SWAP"
    assert result["cooldown_rejected"][0]["remaining_sec"] > 8 * 3600 - 60
    assert not (tmp_path / "fills.jsonl").exists()


def test_cooldown_expires_after_8h_and_records_entry(monkeypatch, tmp_path):
    monkeypatch.setattr(ex, "_LEDGER", tmp_path / "fills.jsonl")
    monkeypatch.setattr(ex, "_LEDGER_DIR", tmp_path)
    monkeypatch.setattr(ex, "_STATE", tmp_path / "processed.json")
    monkeypatch.setattr(ex, "precheck", lambda decision, **kw: _stub_pass_risk())
    monkeypatch.setattr(
        ex,
        "_bridge_call",
        lambda payload, timeout=90: (
            {"ok": True, "positions": []}
            if payload.get("action") == "status"
            else {"ok": True, "order_id": "ord-1", "reference_px": 100.0}
        ),
    )
    (tmp_path / "processed.json").write_text(
        json.dumps({"processed": {}, "last_entry": {"AVAX-USDT-SWAP": time.time() - 9 * 3600}}),
        encoding="utf-8",
    )
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text(json.dumps(_live_decision(), ensure_ascii=False) + "\n", encoding="utf-8")

    before = time.time()
    result = ex.run(outbox, dry_run=False, limit=10)
    assert result["executed"] == 1
    state = json.loads((tmp_path / "processed.json").read_text(encoding="utf-8"))
    assert state["last_entry"]["AVAX-USDT-SWAP"] >= before


def test_check_uses_class_notional_cap():
    """指数类上限 300U；crypto 上限 300U（= 保证金下限 100U × 3x 杠杆）。"""
    assert ex._notional_cap("US500-USDT-SWAP") == 300
    assert ex._notional_floor("US500-USDT-SWAP") == 150
    assert ex._notional_cap("BTC-USDT-SWAP") == 300
    assert ex._notional_floor("BTC-USDT-SWAP") == 100
    assert ex._notional_floor("CL-USDT-SWAP") == 100
    assert ex._check(_live_decision(notional_usdt=400)) == "notional_limit"
    assert ex._check(_live_decision(symbol="US500-USDT-SWAP", notional_usdt=250)) is None


def test_index_class_applies_floor_and_registry_scope(monkeypatch, tmp_path):
    """指数类 13 定容 73U → 抬到保证金下限 100U×3x=300U，并携带 position_scope=registry。"""
    monkeypatch.setattr(ex, "_LEDGER", tmp_path / "fills.jsonl")
    monkeypatch.setattr(ex, "_LEDGER_DIR", tmp_path)
    monkeypatch.setattr(ex, "_STATE", tmp_path / "processed.json")
    seen_kwargs = {}
    monkeypatch.setattr(
        ex,
        "precheck",
        lambda decision, **kw: (
            seen_kwargs.update(kw)
            or {
                "passed": True,
                "reason_code": "OK",
                "reason": "stub",
                "equity": 730.0,
                "equity_source": "stub",
                "notional_usdt": 73.0,
                "leverage": 3,
                "source": "13-pre-trade-gate",
            }
        ),
    )
    captured = {}

    def fake_bridge(payload, timeout=90):
        if payload.get("action") == "status":
            return {"ok": True, "positions": []}
        captured.update(payload)
        return {"ok": True, "order_id": "ord-us500", "reference_px": 5000.0}

    monkeypatch.setattr(ex, "_bridge_call", fake_bridge)
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text(
        json.dumps(_live_decision(symbol="US500-USDT-SWAP"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    result = ex.run(outbox, dry_run=False, limit=10)
    assert result["executed"] == 1
    assert seen_kwargs == {"notional_cap": 300.0, "notional_floor": 150.0}
    assert captured["notional_usdt"] == 300.0
    assert captured["margin_usdt"] == 100.0
    assert captured["position_scope"] == "registry"


def test_crypto_min_margin_floor_300(monkeypatch, tmp_path):
    """非指数类按单笔保证金下限 100U×3x=300U 下单（13 定容 73U 被抬回）。"""
    monkeypatch.setattr(ex, "_LEDGER", tmp_path / "fills.jsonl")
    monkeypatch.setattr(ex, "_LEDGER_DIR", tmp_path)
    monkeypatch.setattr(ex, "_STATE", tmp_path / "processed.json")
    monkeypatch.setattr(ex, "precheck", lambda decision, **kw: _stub_pass_risk())
    captured = {}

    def fake_bridge(payload, timeout=90):
        if payload.get("action") == "status":
            return {"ok": True, "positions": []}
        captured.update(payload)
        return {"ok": True, "order_id": "ord-btc", "reference_px": 100.0}

    monkeypatch.setattr(ex, "_bridge_call", fake_bridge)
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text(json.dumps(_live_decision(), ensure_ascii=False) + "\n", encoding="utf-8")

    result = ex.run(outbox, dry_run=False, limit=10)
    assert result["executed"] == 1
    assert captured["notional_usdt"] == 300.0
    assert captured["position_scope"] == "registry"


def test_risk_bridge_class_floor_contract():
    """risk_bridge 支持类别下限：73U 定容 → 150U，并标注 notional_policy。"""
    from risk_bridge import precheck

    out = precheck(
        {"symbol": "US500-USDT-SWAP", "direction": "long", "confidence": 0.9},
        equity_override=730.0,
        notional_cap=300,
        notional_floor=150,
    )
    assert out["notional_usdt"] == 150
    assert out["notional_policy"] == "class_floor"

    base = precheck(
        {"symbol": "BTC-USDT-SWAP", "direction": "long", "confidence": 0.9},
        equity_override=730.0,
    )
    assert base["notional_usdt"] <= 100
    assert base["notional_policy"] == "allocator"


def test_risk_bridge_real_gate_contract():
    """真实加载 13：输入不合规方向必须 fail-closed，合规输入返回稳定契约。"""
    from risk_bridge import precheck

    neutral = precheck({"symbol": "BTC-USDT-SWAP", "direction": "neutral", "confidence": 1.0})
    assert neutral["passed"] is False
    assert neutral["reason_code"] == "NO_DIRECTION"

    approved = precheck(
        {"symbol": "BTC-USDT-SWAP", "direction": "long", "confidence": 0.8},
        equity_override=10000.0,
    )
    assert approved["equity_source"] == "override"
    assert approved["equity"] == 10000.0
    assert approved["source"] == "13-pre-trade-gate"
    assert isinstance(approved["passed"], bool)
    if approved["passed"]:
        assert 10.0 <= approved["notional_usdt"] <= 100.0
        assert approved["leverage"] == 3


def test_records_50_fill_into_unified_ledger(tmp_path, monkeypatch):
    """50 成交必须写入 22 账本并打 domain=50 标签（幂等）。"""
    monkeypatch.setenv("POSITION_LEDGER_PATH", str(tmp_path / "ledger.db"))
    from position_ledger import PositionLedger

    rec = {
        "symbol": "AVAX-USDT-SWAP",
        "direction": "long",
        "decision_id": "50-nn|AVAX-USDT-SWAP|1",
        "order_placed": True,
        "order_id": "oid-50-1",
        "fill_px": 10.5,
        "result": {"contracts": 3.0},
    }
    ex._record_position_ledger(rec)
    ex._record_position_ledger(rec)  # 重放不重复入账

    led = PositionLedger()
    holders = led.active_holders("AVAX-USDT-SWAP")
    assert holders and holders[0]["domain"] == "50" and holders[0]["qty"] == 3.0
    assert len(led.recent_fills(10)) == 1


def test_record_skips_unfilled_or_dry_run():
    ex._record_position_ledger({"symbol": "AVAX-USDT-SWAP", "order_placed": False})
    ex._record_position_ledger(
        {"symbol": "AVAX-USDT-SWAP", "order_placed": True, "result": {"contracts": 0}}
    )


def _stub_capacity_bridge(payload, timeout=90):
    if payload.get("action") == "status":
        return {"ok": True, "positions": []}
    return {
        "ok": False,
        "error_code": "max_positions",
        "reason": "max positions reached: 12/12 (scope=registry)",
    }


def test_capacity_reject_is_skip_not_failure(monkeypatch, tmp_path):
    """并发持仓满（max_positions）属正常容量拒绝，整轮仍判 ok，不得触发 JobFailed。"""
    monkeypatch.setattr(ex, "_LEDGER", tmp_path / "fills.jsonl")
    monkeypatch.setattr(ex, "_LEDGER_DIR", tmp_path)
    monkeypatch.setattr(ex, "_STATE", tmp_path / "processed.json")
    monkeypatch.setattr(ex, "precheck", lambda decision, **kw: _stub_pass_risk())
    monkeypatch.setattr(ex, "_bridge_call", _stub_capacity_bridge)
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text(json.dumps(_live_decision(), ensure_ascii=False) + "\n", encoding="utf-8")

    result = ex.run(outbox, dry_run=False, limit=10)
    assert result["status"] == "ok"
    assert result["executed"] == 0
    assert result["skipped"] == 1
    assert result["capacity_rejected"][0]["reason"] == "max_positions"
    # 容量拒绝仍落幂等状态，但状态为 capacity 而非 failed
    state = json.loads((tmp_path / "processed.json").read_text(encoding="utf-8"))
    assert state["processed"]["50-nn|AVAX-USDT-SWAP|1"]["status"] == "capacity"


def test_real_broker_error_still_degrades(monkeypatch, tmp_path):
    """非容量类下单错误仍判 degraded（退出码 1），避免误修复掩盖真实故障。"""
    monkeypatch.setattr(ex, "_LEDGER", tmp_path / "fills.jsonl")
    monkeypatch.setattr(ex, "_LEDGER_DIR", tmp_path)
    monkeypatch.setattr(ex, "_STATE", tmp_path / "processed.json")
    monkeypatch.setattr(ex, "precheck", lambda decision, **kw: _stub_pass_risk())
    monkeypatch.setattr(
        ex,
        "_bridge_call",
        lambda payload, timeout=90: (
            {"ok": True, "positions": []}
            if payload.get("action") == "status"
            else {"ok": False, "error_code": "ticker_unavailable", "reason": "ticker down"}
        ),
    )
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text(json.dumps(_live_decision(), ensure_ascii=False) + "\n", encoding="utf-8")

    result = ex.run(outbox, dry_run=False, limit=10)
    assert result["status"] == "degraded"
    assert result["executed"] == 0
    assert "capacity_rejected" not in result


def test_resolve_sl_tp_by_class_and_symbol():
    """SL/TP 间距按类别/标的配置解析，替代全局固定 1.5%/3.0%。"""
    assert ex._resolve_sl_tp({}, "AVAX-USDT-SWAP") == (3.0, 6.0)  # crypto
    assert ex._resolve_sl_tp({}, "MU-USDT-SWAP") == (4.0, 8.0)  # 标的覆盖优先于类别
    assert ex._resolve_sl_tp({}, "US500-USDT-SWAP") == (2.0, 4.0)  # us_index
    # 决策自带 sl/tp 优先
    assert ex._resolve_sl_tp({"sl_pct": 1.2, "tp_pct": 2.4}, "MU-USDT-SWAP") == (1.2, 2.4)


def test_entry_payload_carries_class_sl_tp(monkeypatch, tmp_path):
    """下单 payload 的 sl_pct/tp_pct 来自类别配置，不再是固定 1.5/3.0。"""
    monkeypatch.setattr(ex, "_LEDGER", tmp_path / "fills.jsonl")
    monkeypatch.setattr(ex, "_LEDGER_DIR", tmp_path)
    monkeypatch.setattr(ex, "_STATE", tmp_path / "processed.json")
    monkeypatch.setattr(ex, "precheck", lambda decision, **kw: _stub_pass_risk())
    captured = {}

    def fake_bridge(payload, timeout=90):
        if payload.get("action") == "status":
            return {"ok": True, "positions": []}
        captured.update(payload)
        return {"ok": True, "order_id": "ord-1", "reference_px": 100.0}

    monkeypatch.setattr(ex, "_bridge_call", fake_bridge)
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text(json.dumps(_live_decision(), ensure_ascii=False) + "\n", encoding="utf-8")

    result = ex.run(outbox, dry_run=False, limit=10)
    assert result["executed"] == 1
    assert captured["sl_pct"] == 3.0
    assert captured["tp_pct"] == 6.0
