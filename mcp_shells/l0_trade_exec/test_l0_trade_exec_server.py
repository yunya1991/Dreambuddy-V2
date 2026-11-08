#!/usr/bin/env python3
"""交易执行壳（l0.trade-exec.mcp）契约测试 — 阶段三/四验收。

覆盖（全部零网络、零外部服务依赖）：
  - tools/list 工具面与注册表登记一致（10 工具 + 写工具 annotations）
  - 统一信封结构（ok/degraded/meta.mode=paper/meta.cost）
  - 注册表自描述能力注入（meta.shadow_capable / oracle_verifiable / config_version）
  - 执行权闸门：live:11-bypass / disabled 标的 → execution_rights_conflict
  - ingest_signal 前置过滤：neutral / expired / duplicate
  - training_hooks 样本落盘（signal_skipped / risk_rejected）
  - get_account_mode：mode=paper + execution_rights 摘要
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER = _REPO_ROOT / "mcp_shells" / "l0_trade_exec" / "server.py"

WRITE_TOOLS = {"place_order", "cancel_order", "ingest_signal"}
READ_TOOLS = {
    "get_positions",
    "get_balance",
    "pre_trade_check",
    "check_exit",
    "get_account_mode",
    "reconcile",
    "read_signals",
}


def _call(name: str, arguments: dict, env: dict) -> dict:
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    proc = subprocess.run(
        [sys.executable, str(SERVER)],
        input=json.dumps(req),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=60,
    )
    assert proc.stdout.strip(), f"no stdout; stderr={proc.stderr[-500:]}"
    outer = json.loads(proc.stdout)
    return json.loads(outer["result"]["content"][0]["text"])


def _list_tools(env: dict) -> list:
    proc = subprocess.run(
        [sys.executable, str(SERVER)],
        input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=60,
    )
    return json.loads(proc.stdout)["result"]["tools"]


@pytest.fixture()
def env(tmp_path: Path) -> dict:
    rights = tmp_path / "rights.json"
    rights.write_text(
        json.dumps(
            {
                "version": "test",
                "defaults": {"outcome": "paper", "conflict_policy": "reject_mcp"},
                "symbols": {
                    "ETH-USDT-SWAP": {"outcome": "live:11-bypass"},
                    "SOL-USDT-SWAP": {"outcome": "disabled"},
                },
            }
        ),
        encoding="utf-8",
    )
    e = dict(os.environ)
    e["TRADE_EXEC_LEDGER_DIR"] = str(tmp_path / "ledger")
    e["TRADE_EXEC_RIGHTS_PATH"] = str(rights)
    e["TRADE_EXEC_SAMPLE_PATH"] = str(tmp_path / "samples.jsonl")
    e["MCP_TRACE_ID"] = "trace-trade-exec-test"
    return e


def test_tools_list_matches_registry(env):
    tools = _list_tools(env)
    names = {t["name"] for t in tools}
    assert names == WRITE_TOOLS | READ_TOOLS
    for t in tools:
        ann = t.get("annotations", {})
        if t["name"] in WRITE_TOOLS:
            assert ann.get("readOnlyHint") is False
        else:
            assert ann.get("readOnlyHint") is True


def test_execution_rights_live_rejected(env):
    res = _call("place_order", {"symbol": "ETH-USDT-SWAP", "side": "buy", "size": 0.1}, env)
    assert res["ok"] is False
    assert res["error_code"] == "execution_rights_conflict"
    assert "live:11-bypass" in res["data"]["reason"]
    assert res["meta"]["mode"] == "paper"


def test_execution_rights_disabled_rejected(env):
    res = _call("place_order", {"symbol": "SOL-USDT-SWAP", "side": "buy", "size": 1}, env)
    assert res["error_code"] == "execution_rights_conflict"
    assert "disabled" in res["data"]["reason"]


def test_invalid_params_and_envelope(env):
    res = _call("place_order", {"symbol": "BTC-USDT-SWAP", "side": "hold", "size": 1}, env)
    assert res["ok"] is False
    assert res["error_code"] == "invalid"
    assert set(res["meta"]["cost"]) == {"latency_ms", "slippage_bps"}
    assert res["trace_id"] == "trace-trade-exec-test"


def test_ingest_neutral_skipped(env):
    sig = {
        "signal_id": "t-neutral",
        "source": "test",
        "ts": "2026-11-05T00:00:00+00:00",
        "symbol": "BTC",
        "direction": "neutral",
        "confidence": 0.0,
    }
    res = _call("ingest_signal", {"signal": sig}, env)
    assert res["data"]["skipped"] is True
    assert res["data"]["reason"] == "neutral direction"


def test_ingest_expired_skipped(env):
    sig = {
        "signal_id": "t-expired",
        "source": "test",
        "ts": "2026-01-01T00:00:00+00:00",
        "symbol": "BTC",
        "direction": "long",
        "confidence": 0.8,
        "expires_at": "2026-01-01T00:01:00+00:00",
    }
    res = _call("ingest_signal", {"signal": sig, "size": 0.01}, env)
    assert res["degraded"] is True
    assert res["error_code"] == "signal_expired"


def test_ingest_duplicate_skipped(env):
    ledger_dir = Path(env["TRADE_EXEC_LEDGER_DIR"])
    ledger_dir.mkdir(parents=True, exist_ok=True)
    (ledger_dir / "paper_ledger.json").write_text(
        json.dumps(
            {
                "balance": 1000.0,
                "initial_capital": 1000.0,
                "realized_pnl": 0.0,
                "fee_paid": 0.0,
                "positions": {},
                "pending_orders": {},
                "fills": [],
                "executed_signals": [
                    {
                        "signal_id": "t-dup",
                        "ts": "2026-11-05T00:00:00+00:00",
                        "ord_id": "paper_mkt_x",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    sig = {
        "signal_id": "t-dup",
        "source": "test",
        "ts": "2026-11-05T00:00:00+00:00",
        "symbol": "BTC",
        "direction": "long",
        "confidence": 0.8,
    }
    res = _call("ingest_signal", {"signal": sig, "size": 0.01}, env)
    assert res["data"]["skipped"] is True
    assert "duplicate" in res["data"]["reason"]


def test_training_samples_written(env):
    sig_neutral = {
        "signal_id": "t-s1",
        "source": "test",
        "ts": "2026-11-05T00:00:00+00:00",
        "symbol": "BTC",
        "direction": "neutral",
        "confidence": 0.0,
    }
    _call("ingest_signal", {"signal": sig_neutral}, env)
    sample_path = Path(env["TRADE_EXEC_SAMPLE_PATH"])
    assert sample_path.exists()
    kinds = [json.loads(line)["kind"] for line in sample_path.read_text().splitlines() if line]
    assert "signal_skipped" in kinds
    rec = json.loads(sample_path.read_text().splitlines()[0])
    assert rec["trace_id"] == "trace-trade-exec-test"
    assert rec["mode"] == "paper"


def test_capabilities_injected_from_registry(env):
    """v1.1-mcp 自描述字段：壳运行时按 source 从注册表注入 meta。"""
    res = _call("get_account_mode", {}, env)
    assert res["meta"]["shadow_capable"] is True
    assert res["meta"]["oracle_verifiable"] is True
    assert res["meta"]["config_version"]


def test_account_mode_reports_rights(env):
    res = _call("get_account_mode", {}, env)
    assert res["data"]["mode"] == "paper"
    assert res["data"]["exchange"] == "okx"
    rights = res["data"]["execution_rights"]
    assert rights["available"] is True
    assert rights["defaults"]["outcome"] == "paper"
    assert "ETH-USDT-SWAP" in rights["declared_symbols"]


def _seed_ledger(env, positions: dict) -> None:
    led_dir = Path(env["TRADE_EXEC_LEDGER_DIR"])
    led_dir.mkdir(parents=True, exist_ok=True)
    (led_dir / "paper_ledger.json").write_text(
        json.dumps(
            {
                "balance": 1000.0,
                "initial_capital": 1000.0,
                "realized_pnl": 0.0,
                "fee_paid": 0.0,
                "positions": positions,
                "pending_orders": {},
                "fills": [],
                "executed_signals": [],
            }
        ),
        encoding="utf-8",
    )


def test_check_exit_empty_positions(env):
    """无持仓时 check_exit 返回空决策集，不报错（Fail-Open）。"""
    res = _call("check_exit", {}, env)
    assert res["ok"] is True
    assert res["data"]["count"] == 0
    assert res["data"]["should_exit_count"] == 0


def test_check_exit_evaluates_paper_position(env):
    """有持仓时逐仓调用 13 域 ExitEngine，返回 action/should_exit/reason。"""
    _seed_ledger(
        env,
        {
            "BTC": {
                "inst_id": "BTC-USDT-SWAP",
                "pos_side": "long",
                "pos": 0.1,
                "avg_px": 50000.0,
                "opened_at": "2026-11-05T00:00:00+00:00",
            }
        },
    )
    res = _call("check_exit", {"symbol": "BTC-USDT-SWAP"}, env)
    assert res["data"]["count"] == 1
    d = res["data"]["decisions"][0]
    assert d["inst_id"] == "BTC-USDT-SWAP"
    assert d["action"] in {"CLOSE", "REDUCE", "HOLD", "RAISE_TP"}
    assert isinstance(d["should_exit"], bool)


def test_sizing_clamp_never_upsizes():
    """PositionSizer 建议只作上限：超限收紧、未超限保持、建议缺失不生效。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location("trade_exec_server_under_test", SERVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    sizing = {"ok": True, "base_size_coins": 0.01}
    assert mod._apply_sizing_clamp(0.5, sizing) == 0.01
    assert sizing["clamped"] is True
    assert sizing["requested_size"] == 0.5

    sizing2 = {"ok": True, "base_size_coins": 0.01}
    assert mod._apply_sizing_clamp(0.005, sizing2) == 0.005
    assert sizing2["clamped"] is False

    # 建议缺失/为 0（如行情不可用）→ 不改变原值
    assert mod._apply_sizing_clamp(0.5, {"ok": False}) == 0.5
    assert mod._apply_sizing_clamp(0.5, {"ok": True, "base_size_coins": 0}) == 0.5
