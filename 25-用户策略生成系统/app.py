"""
25-用户策略生成系统 - Flask 服务（端口 8095）

提供用户策略生成能力链：
- 用户意图 → AI辅助策略生成（S1-S5 链）
- 策略回测（含 metrics_summary）
- 基线对比（综合评分 + 推荐）
- 完整流水线编排

依赖：
- 26-策略管理模块（registry 查询基线策略，可选 HTTP 调用）
- 27-策略治理审批系统（changeset/approval，可选 HTTP 调用）
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Flask, jsonify, request

# 确保模块可导入
_MODULE_DIR = Path(__file__).resolve().parent
if str(_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_MODULE_DIR))

from strategy_gen.backtest_engine import run_backtest
from strategy_gen.baseline import baseline_get, baseline_list, baseline_metrics
from strategy_gen.compare import compare_with_baseline, compute_score
from strategy_gen.intent import generate_from_intent
from strategy_gen.pipeline import run_pipeline

app = Flask(__name__)


# ---------------------------------------------------------------------------
# CORS（前端 localhost:3001 跨域访问）
# ---------------------------------------------------------------------------
@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Admin-Token, X-User-Id"
    return resp


# Admin token（环境变量配置，默认开发用 token）
ADMIN_TOKEN = os.environ.get("STRATEGY_GEN_ADMIN_TOKEN", "dev-gen-token-2026")

# 26 中台服务地址（用于跨模块查询基线策略）
STRATEGY_LIB_BASE = os.environ.get("STRATEGY_LIB_BASE", "http://127.0.0.1:8093")


# ---------------------------------------------------------------------------
# 鉴权与工具
# ---------------------------------------------------------------------------

def _require_admin() -> bool:
    token = request.headers.get("X-Admin-Token", "")
    return token == ADMIN_TOKEN


def _user_id() -> str:
    return request.headers.get("X-User-Id", "default")


def _safe_get_json() -> Dict[str, Any]:
    try:
        return request.get_json(force=True) or {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "ok": True,
        "module": "25-用户策略生成系统",
        "port": int(os.environ.get("STRATEGY_GEN_PORT", "8095")),
        "deps": {
            "strategy_lib_base": STRATEGY_LIB_BASE,
        },
        "endpoints": [
            "/api/v1/gen/intent",
            "/api/v1/gen/backtest",
            "/api/v1/gen/compare",
            "/api/v1/gen/pipeline",
            "/api/v1/baseline/list",
            "/api/v1/baseline/get",
            "/api/v1/baseline/metrics",
            "/api/v1/gen/score",
        ],
    })


# ---------------------------------------------------------------------------
# 用户策略生成 - 意图 → AI辅助设计
# ---------------------------------------------------------------------------

@app.route("/api/v1/gen/intent", methods=["POST"])
def gen_intent():
    """用户意图 → S1-S5 策略链生成策略设计。

    Body:
        intent: 用户意图描述
        symbol: 交易对（可选）
        timeframe: 周期（可选）
    Returns:
        trace_id, regime, baseline_candidates, ai_design{config_patch, reason}
    """
    body = _safe_get_json()
    intent = str(body.get("intent") or "").strip()
    if not intent:
        return jsonify({"ok": False, "error": "missing_intent"}), 400
    symbol = body.get("symbol")
    timeframe = body.get("timeframe")
    try:
        result = generate_from_intent(intent, symbol=symbol, timeframe=timeframe)
        return jsonify({"ok": True, "result": result, "user_id": _user_id()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# 用户策略生成 - 回测验证
# ---------------------------------------------------------------------------

@app.route("/api/v1/gen/backtest", methods=["POST"])
def gen_backtest():
    """对策略执行回测，产出 metrics_summary。

    Body:
        strategy_id: 策略 ID
        source_zip: 策略 zip 路径（可选）
        config_patch: 配置补丁（可选）
    Returns:
        metrics_summary, trades, profit_factor, ...
    """
    body = _safe_get_json()
    strategy_id = str(body.get("strategy_id") or "").strip()
    if not strategy_id:
        return jsonify({"ok": False, "error": "missing_strategy_id"}), 400
    source_zip = str(body.get("source_zip") or "").strip() or None
    kwargs = {k: v for k, v in body.items() if k not in ("strategy_id", "source_zip")}
    try:
        result = run_backtest(strategy_id, source_zip, **kwargs)
        return jsonify({"ok": True, "result": result, "user_id": _user_id()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# 用户策略生成 - 基线对比
# ---------------------------------------------------------------------------

@app.route("/api/v1/gen/compare", methods=["POST"])
def gen_compare():
    """对比用户策略与基线策略。

    Body:
        user_metrics: 用户策略回测指标
        baseline_metrics: 基线策略回测指标
    Returns:
        winner: "user" | "baseline"
        user_score, baseline_score
        delta: 各维度差值
        recommendation: "adopt_user" | "recommend_baseline"
    """
    body = _safe_get_json()
    user_metrics = body.get("user_metrics") if isinstance(body.get("user_metrics"), dict) else {}
    baseline_metrics = body.get("baseline_metrics") if isinstance(body.get("baseline_metrics"), dict) else {}
    if not user_metrics or not baseline_metrics:
        return jsonify({"ok": False, "error": "missing_metrics"}), 400
    try:
        result = compare_with_baseline(user_metrics, baseline_metrics)
        return jsonify({"ok": True, "result": result, "user_id": _user_id()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# 用户策略生成 - 综合评分
# ---------------------------------------------------------------------------

@app.route("/api/v1/gen/score", methods=["POST"])
def gen_score():
    """计算策略综合评分。

    score = pf*0.3 + (1-dd)*0.2 + wr*0.2 + sharpe*0.3
    """
    body = _safe_get_json()
    metrics = body.get("metrics") if isinstance(body.get("metrics"), dict) else {}
    if not metrics:
        return jsonify({"ok": False, "error": "missing_metrics"}), 400
    try:
        score = compute_score(metrics)
        return jsonify({"ok": True, "score": round(score, 4), "user_id": _user_id()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# 用户策略生成 - 完整流水线编排
# ---------------------------------------------------------------------------

@app.route("/api/v1/gen/pipeline", methods=["POST"])
def gen_pipeline():
    """执行完整策略生成流水线：intent → regime → candidate → AI设计 → backtest → compare。

    Body:
        intent: 用户意图
        symbol, timeframe: 可选
    Returns:
        ok, stage, intent, trace_id, ...
    """
    body = _safe_get_json()
    intent = str(body.get("intent") or "").strip()
    if not intent:
        return jsonify({"ok": False, "error": "missing_intent"}), 400
    kwargs = {k: v for k, v in body.items() if k != "intent"}
    try:
        result = run_pipeline(intent, **kwargs)
        return jsonify({"ok": True, "result": result, "user_id": _user_id()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# 基线策略库（只读）
# ---------------------------------------------------------------------------

@app.route("/api/v1/baseline/list", methods=["GET"])
def baseline_list_api():
    """列出所有基线策略。"""
    try:
        items = baseline_list()
        return jsonify({"ok": True, "count": len(items), "items": items})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/v1/baseline/get", methods=["GET"])
def baseline_get_api():
    """获取单个基线策略。

    Query:
        strategy_id: 策略 ID（必填）
        source_zip: 策略 zip 路径（可选）
    """
    strategy_id = str(request.args.get("strategy_id") or "").strip()
    if not strategy_id:
        return jsonify({"ok": False, "error": "missing_strategy_id"}), 400
    source_zip = request.args.get("source_zip")
    try:
        entry = baseline_get(strategy_id, source_zip=source_zip)
        if entry is None:
            return jsonify({"ok": False, "error": "not_found"}), 404
        return jsonify({"ok": True, "baseline": entry})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/v1/baseline/metrics", methods=["GET"])
def baseline_metrics_api():
    """获取基线策略的回测指标。

    Query:
        strategy_id: 策略 ID（必填）
        source_zip: 策略 zip 路径（可选）
    """
    strategy_id = str(request.args.get("strategy_id") or "").strip()
    if not strategy_id:
        return jsonify({"ok": False, "error": "missing_strategy_id"}), 400
    source_zip = request.args.get("source_zip")
    try:
        metrics = baseline_metrics(strategy_id, source_zip=source_zip)
        if metrics is None:
            return jsonify({"ok": False, "error": "not_found"}), 404
        return jsonify({"ok": True, "metrics": metrics})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# 启动入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("STRATEGY_GEN_PORT", "8095"))
    app.run(host="0.0.0.0", port=port, debug=False)
