#!/usr/bin/env python3
"""mcp_shells/l1_trading/server.py — L1 交易层只读 MCP（l1.trading.mcp）。

契约：49-交易框架协议/SPEC.md §3.8（10 工具）。
硬约束：
  - 读工具只读聚合 23/40/42/43 状态与执行层持仓/余额；
  - forward_signal 是唯一写工具（需 Mandate），只允许 source=23-evolution 的
    FinalDecisionSignal 进入 l0.trade-exec.mcp 的 paper 执行管道；
  - 不触发信号、不训练、不写回子系统状态；文件缺失/损坏 fail-open 为 degraded。

stdio JSON-RPC 2.0，按需拉起，不常驻。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_shells._shared.envelope_wrap import wrap  # noqa: E402

SHELL_SOURCE = "l1.trading.mcp"
_ROOT = Path(os.environ.get("DREAMBUDDY_ROOT", str(_REPO_ROOT)))

SIGNAL_STATE_PATH = Path(os.environ.get(
    "L1_SIGNAL_STATE_PATH",
    str(_ROOT / "23-四层闭环自进化交易架构" / "runtime" / "signals" / "23_signal_state.json"),
))
SIGNAL_FALLBACK_PATH = Path(os.environ.get(
    "L1_SIGNAL_FALLBACK_PATH",
    str(_ROOT / "11-易经推理系统" / "data" / "event_driven_state.json"),
))
BUS_STATE_PATH = Path(os.environ.get(
    "L1_BUS_STATE_PATH",
    str(_ROOT / "42-神经网络交易协调层" / "runtime" / "bus_state.json"),
))
CONSTRAINT_STATE_PATH = Path(os.environ.get(
    "L1_CONSTRAINT_STATE_PATH",
    str(_ROOT / "42-神经网络交易协调层" / "runtime" / "macro_constraint.json"),
))
CYCLE_STATE_PATH = Path(os.environ.get(
    "L1_CYCLE_STATE_PATH",
    str(_ROOT / "40-周期神经网络系统" / "cycle_state.json"),
))
STRATEGY_MAPPING_PATH = Path(os.environ.get(
    "L1_STRATEGY_MAPPING_PATH",
    str(_ROOT / "40-周期神经网络系统" / "strategy_mapping.json"),
))
STRATEGIC_EXTENSION_PATH = Path(os.environ.get(
    "L1_STRATEGIC_EXTENSION_PATH",
    str(_ROOT / "43-战略承接推演层" / "runtime" / "strategic_extension_signal.json"),
))
TRAINING_REPORT_PATH = Path(os.environ.get(
    "L1_TRAINING_REPORT_PATH",
    str(_ROOT / "23-四层闭环自进化交易架构" / "dreambuddy_evolution"
        / "data" / "neural_sde_v1.training_report.json"),
))
PAPER_SAMPLES_PATH = Path(os.environ.get(
    "L1_PAPER_SAMPLES_PATH",
    str(_ROOT / "mcp_shells" / "l0_trade_exec" / "ml_data" / "samples.jsonl"),
))


def _read_json(path: Path) -> tuple[Any | None, str]:
    """读取 JSON；返回 (data, error_code)。"""
    try:
        if not path.exists():
            return None, "not_found"
        with open(path, encoding="utf-8") as f:
            return json.load(f), ""
    except (OSError, json.JSONDecodeError):
        return None, "invalid"


def _wrap(
    data: Any, *, degraded: bool = False, error_code: str = "", reason: str = "",
    meta: dict[str, Any] | None = None,
) -> str:
    merged_meta = {"tool": meta.pop("tool", "")} if meta else {}
    if meta:
        merged_meta.update(meta)
    if reason:
        merged_meta["reason"] = reason
    return json.dumps(
        wrap(
            data, SHELL_SOURCE, degraded=degraded, error_code=error_code,
            meta=merged_meta,
        ),
        ensure_ascii=False,
    )


def _missing(path: Path, reason: str = "") -> str:
    return _wrap(
        {"available": False, "path": str(path)},
        degraded=True, error_code="not_found",
        reason=reason or "state file not found (fail-open)",
    )


def _load_signal() -> tuple[dict[str, Any] | None, Path, str, bool]:
    """优先 23 最终决策，回退 11 迁移期状态。"""
    data, err = _read_json(SIGNAL_STATE_PATH)
    if data is not None:
        return data, SIGNAL_STATE_PATH, err, False
    data, err = _read_json(SIGNAL_FALLBACK_PATH)
    if data is not None:
        return data, SIGNAL_FALLBACK_PATH, err, True
    return None, SIGNAL_STATE_PATH, err, False


def _summarize(obj: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(obj, dict):
        return {}
    return {k: obj[k] for k in keys if k in obj}


def _cycle_summary() -> dict[str, Any]:
    data, err = _read_json(CYCLE_STATE_PATH)
    if data is None:
        return {"available": False, "error_code": err, "path": str(CYCLE_STATE_PATH)}
    real = data.get("real_cycle") or {}
    btc = ((data.get("technical_anchor") or {}).get("assets") or {}).get("BTC/USDT") or {}
    return {
        "available": True,
        "generated_at": data.get("generated_at"),
        "real_cycle_state": real.get("state"),
        "real_cycle_confidence": real.get("confidence"),
        "btc_above_ma200": btc.get("above"),
        "btc_distance_pct": btc.get("distance_pct"),
        "path": str(CYCLE_STATE_PATH),
    }


def _strategy_summary() -> dict[str, Any]:
    data, err = _read_json(STRATEGY_MAPPING_PATH)
    if data is None:
        return {"available": False, "error_code": err,
                "path": str(STRATEGY_MAPPING_PATH)}
    suggestion = data.get("strategy_suggestion") or {}
    return {
        "available": True,
        "generated_at": data.get("generated_at"),
        "quadrant": (data.get("inputs") or {}).get("quadrant"),
        "stance": suggestion.get("stance"),
        "position_band_pct": suggestion.get("position_band_pct"),
        "path": str(STRATEGY_MAPPING_PATH),
    }


# ── 10 工具 handlers ────────────────────────────────────────────

def get_signal_state(arguments: dict[str, Any]) -> str:
    data, path, err, fallback = _load_signal()
    if data is None:
        return _missing(SIGNAL_STATE_PATH, "23/11 signal state unavailable")
    payload = data.get("payload") if isinstance(data, dict) else None
    out = {
        "available": True,
        "path": str(path),
        "fallback": fallback,
        "signal": data,
    }
    if fallback:
        out["note"] = "23 目标文件缺失，返回 11 event_driven_state 迁移期镜像"
    return _wrap(
        out, degraded=fallback, error_code="degraded" if fallback else "",
        reason="fallback to 11 event_driven_state" if fallback else "",
        meta={"tool": "get_signal_state"},
    )


def get_bus_state(arguments: dict[str, Any]) -> str:
    data, err = _read_json(BUS_STATE_PATH)
    if data is None:
        return _missing(BUS_STATE_PATH, "42 bus_state unavailable")
    signals = list(data.get("signals") or [])
    symbol = arguments.get("symbol")
    if symbol:
        signals = [s for s in signals if s.get("symbol") == symbol]
    limit = max(1, min(int(arguments.get("limit", 50)), 200))
    return _wrap(
        {
            "available": True,
            "path": str(BUS_STATE_PATH),
            "generated_at": data.get("generated_at"),
            "sources": data.get("sources") or [],
            "signal_count": data.get("signal_count"),
            "signals": signals[:limit],
            "count": len(signals[:limit]),
        },
        meta={"tool": "get_bus_state"},
    )


def get_constraint_state(arguments: dict[str, Any]) -> str:
    data, err = _read_json(CONSTRAINT_STATE_PATH)
    if data is not None:
        return _wrap(
            {"available": True, "path": str(CONSTRAINT_STATE_PATH),
             "constraint": data},
            meta={"tool": "get_constraint_state"},
        )
    return _wrap(
        {
            "available": False,
            "candidate_path": str(CONSTRAINT_STATE_PATH),
            "components": {
                "cycle": _cycle_summary(),
                "strategy_mapping": _strategy_summary(),
                "strategic_extension": _read_json(STRATEGIC_EXTENSION_PATH)[0],
                "elastic_params": _read_json(
                    _ROOT / "42-神经网络交易协调层" / "runtime" / "params_active.json"
                )[0],
            },
        },
        degraded=True, error_code="not_found",
        reason="MacroElasticConstraint v1 state file not found (fail-open)",
        meta={"tool": "get_constraint_state"},
    )


def get_cycle_state(arguments: dict[str, Any]) -> str:
    data, err = _read_json(CYCLE_STATE_PATH)
    if data is None:
        return _missing(CYCLE_STATE_PATH, "40 cycle_state unavailable")
    return _wrap(
        {"available": True, "path": str(CYCLE_STATE_PATH), "cycle": data},
        meta={"tool": "get_cycle_state"},
    )


def get_strategic_extension(arguments: dict[str, Any]) -> str:
    data, err = _read_json(STRATEGIC_EXTENSION_PATH)
    if data is None:
        return _missing(
            STRATEGIC_EXTENSION_PATH,
            "43 strategic_extension signal unavailable（43 runtime 可能尚未产出）",
        )
    return _wrap(
        {"available": True, "path": str(STRATEGIC_EXTENSION_PATH),
         "strategic_extension": data},
        meta={"tool": "get_strategic_extension"},
    )


_DIAG_KEYS = {
    "primary_contradiction": (
        "dimension", "direction", "strength", "confidence",
        "cause_score", "effort_result", "continuation_score",
        "gate_state", "meta_cognition", "position_multiplier",
    ),
    "contradiction_shift": (
        "shifted_from", "shifted_to", "new_direction",
        "structural_break_type", "consecutive_count",
    ),
    "cross_validation": (
        "g_dim", "a_dim", "consistent", "confidence_mult",
        "divergence_count", "quality_change",
    ),
    "path": ("optimal_path", "hjb_value", "path_score"),
    "elastic_result": (
        "position_mult", "t_max", "deviation", "constraint_active",
        "aligned", "rebound_risk",
    ),
}


def get_decision_diagnostics(arguments: dict[str, Any]) -> str:
    data, path, err, fallback = _load_signal()
    if data is None:
        return _missing(SIGNAL_STATE_PATH, "23 signal state unavailable")
    payload = data.get("payload") or {}
    diagnostics = {
        key: _summarize(payload.get(key), keys)
        for key, keys in _DIAG_KEYS.items()
    }
    return _wrap(
        {
            "available": True,
            "path": str(path),
            "fallback": fallback,
            "symbol": data.get("symbol"),
            "direction": data.get("direction"),
            "confidence": data.get("confidence"),
            "action": payload.get("action"),
            "position_tier": payload.get("position_tier"),
            "regime": payload.get("regime"),
            "diagnostics": diagnostics,
            "note": "仅暴露摘要 + 置信度；原始权重/张量不下发（DEC-15）",
        },
        degraded=fallback, error_code="degraded" if fallback else "",
        reason="fallback to 11 event_driven_state" if fallback else "",
        meta={"tool": "get_decision_diagnostics"},
    )


def get_training_status(arguments: dict[str, Any]) -> str:
    report, err = _read_json(TRAINING_REPORT_PATH)
    sample_count = 0
    if PAPER_SAMPLES_PATH.exists():
        try:
            with open(PAPER_SAMPLES_PATH, encoding="utf-8") as f:
                sample_count = sum(1 for line in f if line.strip())
        except OSError:
            sample_count = 0
    if report is None and sample_count == 0:
        return _missing(TRAINING_REPORT_PATH, "training report / paper samples unavailable")
    training = _summarize(report or {}, (
        "status", "epochs", "epochs_run", "early_stopped", "n_windows",
        "final_loss", "best_val_loss",
    ))
    return _wrap(
        {
            "available": report is not None,
            "training": training,
            "paper_sample_count": sample_count,
            "paths": {
                "training_report": str(TRAINING_REPORT_PATH),
                "paper_samples": str(PAPER_SAMPLES_PATH),
            },
        },
        degraded=report is None,
        error_code="degraded" if report is None else "",
        reason="training report missing; only paper samples available" if report is None else "",
        meta={"tool": "get_training_status"},
    )


def _call_l0(tool: str, arguments: dict[str, Any]) -> tuple[Any, bool, str, str]:
    """代理 l0.trade-exec.mcp 的 read/ingest handler。"""
    from mcp_shells.l0_trade_exec import server as l0

    handler = getattr(l0, f"_handle_{tool}")
    env = json.loads(handler(arguments))
    reason = str((env.get("meta") or {}).get("reason", ""))
    return env.get("data"), bool(env.get("degraded")), str(env.get("error_code") or ""), reason


def get_positions(arguments: dict[str, Any]) -> str:
    try:
        data, degraded, error_code, reason = _call_l0(
            "get_positions", {"symbol": arguments.get("symbol")},
        )
    except Exception as exc:  # noqa: BLE001 — 代理失败 fail-open
        return _wrap(
            {"available": False, "error": f"{type(exc).__name__}: {exc}"},
            degraded=True, error_code="unavailable",
            reason="l0.trade-exec.mcp unavailable",
            meta={"tool": "get_positions"},
        )
    return _wrap(
        {"available": True, "execution": data},
        degraded=degraded, error_code=error_code, reason=reason,
        meta={"tool": "get_positions", "proxied_from": "l0.trade-exec.mcp"},
    )


def get_balance(arguments: dict[str, Any]) -> str:
    try:
        data, degraded, error_code, reason = _call_l0("get_balance", {})
    except Exception as exc:  # noqa: BLE001
        return _wrap(
            {"available": False, "error": f"{type(exc).__name__}: {exc}"},
            degraded=True, error_code="unavailable",
            reason="l0.trade-exec.mcp unavailable",
            meta={"tool": "get_balance"},
        )
    return _wrap(
        {"available": True, "execution": data},
        degraded=degraded, error_code=error_code, reason=reason,
        meta={"tool": "get_balance", "proxied_from": "l0.trade-exec.mcp"},
    )


def forward_signal(arguments: dict[str, Any]) -> str:
    signal = arguments.get("signal")
    path = SIGNAL_STATE_PATH
    if not isinstance(signal, dict):
        signal, path, _err, _fallback = _load_signal()
    if not isinstance(signal, dict):
        return _missing(SIGNAL_STATE_PATH, "23 FinalDecisionSignal unavailable")

    if signal.get("source") != "23-evolution":
        return _wrap(
            {"available": False, "source": signal.get("source")},
            degraded=True, error_code="conflict",
            reason="forward_signal 只接受 source=23-evolution",
            meta={"tool": "forward_signal"},
        )
    if signal.get("shadow") is True:
        return _wrap(
            {"available": False, "signal_id": signal.get("signal_id")},
            degraded=True, error_code="conflict",
            reason="shadow 信号不允许进入执行层",
            meta={"tool": "forward_signal"},
        )
    if signal.get("mode") != "live":
        return _wrap(
            {"available": False, "mode": signal.get("mode")},
            degraded=True, error_code="conflict",
            reason="forward_signal 只允许 mode=live",
            meta={"tool": "forward_signal"},
        )

    try:
        data, degraded, error_code, reason = _call_l0(
            "ingest_signal",
            {
                "signal": signal,
                "source": "inline",
                "paper_execute": bool(arguments.get("paper_execute", True)),
            },
        )
    except Exception as exc:  # noqa: BLE001
        return _wrap(
            {"available": False, "error": f"{type(exc).__name__}: {exc}"},
            degraded=True, error_code="unavailable",
            reason="l0.trade-exec.mcp unavailable",
            meta={"tool": "forward_signal"},
        )
    return _wrap(
        {
            "available": True,
            "signal_id": signal.get("signal_id"),
            "source_path": str(path),
            "execution": data,
        },
        degraded=degraded, error_code=error_code, reason=reason,
        meta={"tool": "forward_signal", "proxied_from": "l0.trade-exec.mcp"},
    )


_TOOLS = [
    {
        "name": "get_signal_state",
        "description": "读 23 最终决策（FinalDecisionSignal v1）；缺失时回退 11 迁移期镜像。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_bus_state",
        "description": "读 42 信号总线状态；支持 symbol 过滤与 limit。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
            },
        },
    },
    {
        "name": "get_constraint_state",
        "description": "读最新 MacroElasticConstraint v1；缺失时返回 40/42/43 组件摘要（degraded）。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_cycle_state",
        "description": "读 40 周期状态（cycle_state.json）。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_strategic_extension",
        "description": "读 43 战略承接信号（runtime/strategic_extension_signal.json）。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_decision_diagnostics",
        "description": "读 23 主矛盾/质变/交叉验证/路径诊断摘要（DEC-15 脱敏，不下发原始权重/张量）。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_training_status",
        "description": "读 23 训练报告 + 执行层 paper 样本数。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_positions",
        "description": "代理 l0.trade-exec.mcp get_positions（paper 持仓）。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
        },
    },
    {
        "name": "get_balance",
        "description": "代理 l0.trade-exec.mcp get_balance（paper 余额）。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "forward_signal",
        "description": "将 23 FinalDecisionSignal（source=23-evolution, mode=live）转发到执行层 paper 管道；需 Mandate。",
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "signal": {
                    "type": "object",
                    "description": "可选：显式传入 23 信号；缺省从 23 状态文件读取",
                },
                "paper_execute": {"type": "boolean", "default": True},
            },
        },
    },
]

_TOOL_HANDLERS = {
    "get_signal_state": get_signal_state,
    "get_bus_state": get_bus_state,
    "get_constraint_state": get_constraint_state,
    "get_cycle_state": get_cycle_state,
    "get_strategic_extension": get_strategic_extension,
    "get_decision_diagnostics": get_decision_diagnostics,
    "get_training_status": get_training_status,
    "get_positions": get_positions,
    "get_balance": get_balance,
    "forward_signal": forward_signal,
}


def _handle_request(req: dict[str, Any]) -> dict[str, Any] | None:
    method = req.get("method", "")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req.get("id"),
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": SHELL_SOURCE, "version": "0.1"},
                "capabilities": {"tools": {}},
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req.get("id"), "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req.get("id"),
                "result": {"tools": _TOOLS}}
    if method == "tools/call":
        params = req.get("params", {})
        name = params.get("name", "")
        handler = _TOOL_HANDLERS.get(name)
        if handler is None:
            return {
                "jsonrpc": "2.0",
                "id": req.get("id"),
                "error": {"code": -32601, "message": f"Method not found: {name}"},
            }
        started = time.perf_counter()
        text = handler(params.get("arguments", {}) or {})
        return {
            "jsonrpc": "2.0",
            "id": req.get("id"),
            "result": {
                "content": [{"type": "text", "text": text}],
                "isError": False,
                "_meta": {
                    "latency_ms": round(
                        (time.perf_counter() - started) * 1000.0, 2,
                    )
                },
            },
        }
    return {
        "jsonrpc": "2.0",
        "id": req.get("id"),
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }) + "\n")
            sys.stdout.flush()
            continue
        resp = _handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()