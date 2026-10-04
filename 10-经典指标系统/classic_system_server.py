"""classic-system MVP 后端 — Flask 开发/测试服务

为前端 classic-system-client.ts 提供 MVP 端点桥接 DreamOS C3 回测验证节点。

设计原则：
- MVP 仅实现 3 个核心端点：/health + /automation/backtest/run + /evaluation/gate/check
- 其他端点返回 501 Not Implemented（前端能区分 MVP vs 完整服务）
- 不替代 ml_trade_service.py 生产服务，仅开发/测试环境使用
- 端口 8092（与前端契约一致）
- 桥接 DreamOS C3 节点 + backtrader 可选增强（FAIL-OPEN）

启动：
    python3 classic_system_server.py
    # 服务监听 http://127.0.0.1:8092
"""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

from flask import Flask, jsonify, request

# ── DreamOS 路径注入 ──────────────────────────────────────
# 本文件位于 10-经典指标系统/，DreamOS 位于 1-ARCHITECTURE/dreamos/
_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent
_DREAMOS_ARCH = _PROJECT_ROOT / "1-ARCHITECTURE"
if str(_DREAMOS_ARCH) not in sys.path:
    sys.path.insert(0, str(_DREAMOS_ARCH))

# backtrader 适配器可用性
try:
    from dreamos.capabilities.trading.backtest.backtrader_adapter import (
        is_available as _bt_available,
    )
except ImportError:
    _bt_available = None  # type: ignore

# DreamOS C3 节点 + State
try:
    from dreamos.capabilities.trading.nodes.c3_backtest_verify import (
        C3BacktestVerifyNode,
    )
    from dreamos.shared.state import State, NodeResult, NodeStatus
    _C3_AVAILABLE = True
except ImportError:
    C3BacktestVerifyNode = None  # type: ignore
    State = None  # type: ignore
    NodeResult = None  # type: ignore
    NodeStatus = None  # type: ignore
    _C3_AVAILABLE = False


app = Flask(__name__)


# ============================================================
# 1. 健康检查
# ============================================================
@app.route("/health", methods=["GET"])
def health():
    """健康检查端点

    返回 {ok: true, service: "classic-system-mvp", backtrader: bool}
    """
    backtrader_available = bool(_bt_available()) if _bt_available else False
    return jsonify({
        "ok": True,
        "service": "classic-system-mvp",
        "backtrader": backtrader_available,
        "dreamos_c3": _C3_AVAILABLE,
        "ts": int(time.time()),
    }), 200


@app.route("/selfcheck", methods=["GET"])
def selfcheck():
    """系统自检（简化版）"""
    return jsonify({
        "ok": True,
        "service": "classic-system-mvp",
        "checks": {
            "backtrader": bool(_bt_available()) if _bt_available else False,
            "dreamos_c3": _C3_AVAILABLE,
            "flask": True,
        },
        "ts": int(time.time()),
    }), 200


# ============================================================
# 2. 回测 API — 桥接 DreamOS C3 节点
# ============================================================
@app.route("/automation/backtest/run", methods=["POST"])
def backtest_run():
    """运行回测 — 桥接 DreamOS C3 回测验证节点

    接受 payload：
        strategy_name: str (可选)
        timerange: str (可选)
        signals: list[dict] (可选，缺省用最小占位信号)
        klines: list[dict] (可选，提供则触发 backtrader 增强)

    返回 {ok: true, result: {metrics_summary: {total_trades, win_rate, sharpe_ratio, max_drawdown}}}
    """
    try:
        payload = request.get_json(silent=True) or {}
    except Exception:
        payload = {}

    strategy_name = payload.get("strategy_name") or "unknown"
    timerange = payload.get("timerange") or ""
    signals = payload.get("signals") or []
    klines = payload.get("klines") or []

    # 若未提供 signals，使用最小占位信号（保证 C3 能产出非空结果）
    if not signals:
        signals = [
            {
                "symbol": "BTC",
                "direction": "LONG",
                "confidence": 0.75,
                "strategy": strategy_name,
                "layer": "trend",
                "trend": 0.10,
                "rsi": 60.0,
                "momentum": 0.05,
            }
        ]

    # 构造 DreamOS State
    if not _C3_AVAILABLE:
        # DreamOS 不可用 → 返回降级骨架结果
        return jsonify({
            "ok": True,
            "result": {
                "metrics_summary": {
                    "total_trades": 0,
                    "win_rate": 0.0,
                    "sharpe_ratio": 0.0,
                    "max_drawdown": 0.0,
                },
                "degraded": True,
                "reason": "DreamOS C3 节点不可用，返回降级骨架",
            },
            "trace_id": str(uuid.uuid4()),
            "ts": int(time.time()),
        }), 200

    state = State()
    state.market = {"price": 50000, "change_24h": 0.05}
    state.config = {}
    if klines:
        state.config["backtest_klines"] = klines
    state.results["C2"] = NodeResult(
        node_id="C2",
        status=NodeStatus.SUCCESS,
        confidence=0.7,
        outputs={
            "signals": signals,
            "signal_count": len(signals),
            "dominant_direction": "LONG" if signals else "NEUTRAL",
        },
    )

    # 执行 C3 节点
    node = C3BacktestVerifyNode()
    result = node.execute_core(state)

    verified = result.outputs.get("verified_signals", [])
    win_rate = float(result.outputs.get("win_rate", 0.0))
    sharpe = float(result.outputs.get("sharpe", 0.0))
    max_dd = float(result.outputs.get("max_dd", 0.0))
    backtest_source = result.outputs.get("backtest_source", "simplified")

    return jsonify({
        "ok": True,
        "result": {
            "metrics_summary": {
                "total_trades": len(verified),
                "win_rate": win_rate,
                "sharpe_ratio": sharpe,
                "max_drawdown": max_dd,
                "total_pnl": sum(2 * s.get("win_rate", 0.5) - 1 for s in verified),
            },
            "report": {
                "trades": verified,
                "signals": signals,
                "summary": {
                    "strategy": strategy_name,
                    "timerange": timerange,
                    "backtest_source": backtest_source,
                },
            },
        },
        "trace_id": str(uuid.uuid4()),
        "ts": int(time.time()),
    }), 200


# ============================================================
# 3. 评估 Gate 检查 — 简化门禁
# ============================================================
@app.route("/evaluation/gate/check", methods=["POST"])
def gate_check():
    """Gate 检查 — 简化门禁评估

    接受 payload：
        gate_id: str (可选)
        strategy_id: str (可选)
        changeset: dict (可选)

    返回 {ok: true, pass: bool, gate_id, gate_result, thresholds, violations, warnings}
    """
    try:
        payload = request.get_json(silent=True) or {}
    except Exception:
        payload = {}

    gate_id = payload.get("gate_id") or str(uuid.uuid4())
    strategy_id = payload.get("strategy_id") or "unknown"

    # 简化门禁规则：
    # 1. strategy_id 不能为空
    # 2. changeset（若提供）不能含 "force_apply": True
    changeset = payload.get("changeset") or {}
    violations: List[str] = []
    warnings: List[str] = []

    if not strategy_id or strategy_id == "unknown":
        violations.append("strategy_id 必填")

    if isinstance(changeset, dict) and changeset.get("force_apply") is True:
        violations.append("force_apply=True 不允许，必须走审批流程")

    # 简化阈值（与 BCRM backtest_gate 经验对齐）
    thresholds = {
        "win_rate_min": 0.50,
        "sharpe_min": 0.0,
        "max_drawdown_max": 0.30,
    }

    gate_pass = len(violations) == 0

    return jsonify({
        "ok": True,
        "pass": gate_pass,
        "gate_id": gate_id,
        "gate_result": {
            "strategy_id": strategy_id,
            "violations_count": len(violations),
            "warnings_count": len(warnings),
        },
        "thresholds": thresholds,
        "violations": violations,
        "warnings": warnings,
        "ts": int(time.time()),
    }), 200


# ============================================================
# 4. 其他端点 — 501 Not Implemented
# ============================================================
@app.route("/<path:_path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
def not_implemented(_path: str):
    """未实现的端点统一返回 501

    前端通过 501 区分 MVP 服务 vs 完整 ml_trade_service.py 生产服务。
    """
    return jsonify({
        "ok": False,
        "error": f"endpoint /{_path} not implemented in MVP server",
        "service": "classic-system-mvp",
        "hint": "MVP 仅实现 /health, /automation/backtest/run, /evaluation/gate/check",
        "ts": int(time.time()),
    }), 501


def main():
    """启动 MVP 服务"""
    print("=" * 60)
    print("Classic-System MVP Server")
    print(f"  Port: 8092")
    print(f"  DreamOS C3: {'available' if _C3_AVAILABLE else 'unavailable (degraded)'}")
    if _bt_available:
        print(f"  backtrader: {'available' if _bt_available() else 'not installed'}")
    else:
        print(f"  backtrader: adapter not loaded")
    print("  Endpoints:")
    print("    GET  /health")
    print("    POST /automation/backtest/run")
    print("    POST /evaluation/gate/check")
    print("    *    → 501 Not Implemented")
    print("=" * 60)
    app.run(host="127.0.0.1", port=8092, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
