"""
28-策略信号触发模块 - Flask 服务（端口 8096）

提供代币筛选 + Freqtrade webhook 接收能力：
- 代币筛选：beta 范围、相关性阈值、聚类分组
- Freqtrade webhook：接收 entry/exit/cancel/fill/status 事件，路由到下游系统

不含 Quant 信号和三屏信号（独立子系统能力）。

依赖：
- 26-策略管理模块（查询策略 source_zip，可选 HTTP 调用）
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, request

# 确保模块可导入
_MODULE_DIR = Path(__file__).resolve().parent
if str(_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_MODULE_DIR))

from signal_trigger.freqtrade.webhook import handle_webhook, query_events
from signal_trigger.universe.screen import (
    cluster_screen,
    screen_by_beta,
    screen_by_correlation,
    screen_tokens,
)
from signal_trigger.universe.universe import (
    _compute_btc_corr_from_closes,
    _universe_beta_from_ret,
    _universe_pair_aliases,
    _universe_pearson_corr,
    _universe_spearman_corr,
)

app = Flask(__name__)


@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Admin-Token, X-User-Id"
    return resp


# Admin token（环境变量配置，默认开发用 token）
SIGNAL_TRIGGER_ADMIN_TOKEN = os.environ.get("SIGNAL_TRIGGER_ADMIN_TOKEN", "dev-signal-token-2026")

# 26 中台服务地址（用于跨模块查询策略）
STRATEGY_LIB_BASE = os.environ.get("STRATEGY_LIB_BASE", "http://127.0.0.1:8093")


# ---------------------------------------------------------------------------
# 鉴权与工具
# ---------------------------------------------------------------------------

def _require_admin() -> bool:
    token = request.headers.get("X-Admin-Token", "")
    return token == SIGNAL_TRIGGER_ADMIN_TOKEN


def _safe_get_json() -> Dict[str, Any]:
    try:
        return request.get_json(force=True) or {}
    except Exception:
        return {}


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        f = float(v)
        if f != f:  # NaN
            return default
        return f
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "ok": True,
        "module": "28-策略信号触发模块",
        "port": int(os.environ.get("SIGNAL_TRIGGER_PORT", "8096")),
        "deps": {
            "strategy_lib_base": STRATEGY_LIB_BASE,
        },
        "endpoints": [
            "/api/v1/universe/screen",
            "/api/v1/universe/screen/beta",
            "/api/v1/universe/screen/corr",
            "/api/v1/universe/cluster",
            "/api/v1/universe/corr",
            "/api/v1/universe/beta",
            "/api/v1/universe/aliases",
            "/webhook/freqtrade",
            "/api/v1/webhook/events",
        ],
    })


# ---------------------------------------------------------------------------
# 代币筛选 API
# ---------------------------------------------------------------------------

@app.route("/api/v1/universe/screen", methods=["POST"])
def universe_screen():
    """代币筛选主入口。

    Body:
        candidates: [{"pair": "BTC/USDT", "close": {ts: price}, "ret": np.ndarray?}, ...]
        beta_range: {"min": 0.5, "max": 1.5}        # 可选
        corr_threshold: 0.6                          # 可选（与 BTC 相关性下限）
        corr_method: "pearson" | "spearman"           # 默认 pearson
        btc_close: {ts: price}                       # BTC 收盘价（用于 beta/corr）
        limit: 50                                     # 最大返回数量

    Returns:
        passed, rejected, stats
    """
    body = _safe_get_json()
    candidates = body.get("candidates") if isinstance(body.get("candidates"), list) else []
    if not candidates:
        return jsonify({"ok": False, "error": "missing_candidates"}), 400

    beta_range = body.get("beta_range") if isinstance(body.get("beta_range"), dict) else None
    corr_threshold = body.get("corr_threshold")
    if corr_threshold is not None:
        corr_threshold = _safe_float(corr_threshold, 0.0)
    corr_method = str(body.get("corr_method") or "pearson").strip().lower()
    btc_close = body.get("btc_close") if isinstance(body.get("btc_close"), dict) else None
    limit = int(body.get("limit") or 50)

    try:
        result = screen_tokens(
            candidates,
            beta_range=beta_range,
            corr_threshold=corr_threshold,
            corr_method=corr_method,
            btc_close=btc_close,
            limit=limit,
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/v1/universe/screen/beta", methods=["POST"])
def universe_screen_beta():
    """按 beta 范围筛选代币。

    Body:
        candidates: [...]
        btc_ret: [float, ...]   # BTC 收益率序列
        beta_min: 0.5           # 默认 0.5
        beta_max: 1.5           # 默认 1.5
    """
    body = _safe_get_json()
    candidates = body.get("candidates") if isinstance(body.get("candidates"), list) else []
    btc_ret_list = body.get("btc_ret") if isinstance(body.get("btc_ret"), list) else []
    if not candidates or not btc_ret_list:
        return jsonify({"ok": False, "error": "missing_candidates_or_btc_ret"}), 400
    beta_min = _safe_float(body.get("beta_min"), 0.5)
    beta_max = _safe_float(body.get("beta_max"), 1.5)
    try:
        import numpy as np
        btc_ret = np.array(btc_ret_list, dtype=float)
        result = screen_by_beta(candidates, btc_ret, beta_min, beta_max)
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/v1/universe/screen/corr", methods=["POST"])
def universe_screen_corr():
    """按相关性阈值筛选代币。

    Body:
        candidates: [...]
        btc_close: {ts: price}
        threshold: 0.6       # 默认 0.6
        method: "pearson"    # 默认 pearson
    """
    body = _safe_get_json()
    candidates = body.get("candidates") if isinstance(body.get("candidates"), list) else []
    btc_close = body.get("btc_close") if isinstance(body.get("btc_close"), dict) else {}
    if not candidates or not btc_close:
        return jsonify({"ok": False, "error": "missing_candidates_or_btc_close"}), 400
    threshold = _safe_float(body.get("threshold"), 0.6)
    method = str(body.get("method") or "pearson").strip().lower()
    try:
        result = screen_by_correlation(candidates, btc_close, threshold, method)
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/v1/universe/cluster", methods=["POST"])
def universe_cluster():
    """对候选代币做 KMeans 聚类。

    Body:
        candidates: [{"pair": "BTC/USDT", "ret": [float, ...]}, ...]
        k: 5   # 聚类数（默认 5）
    """
    body = _safe_get_json()
    candidates = body.get("candidates") if isinstance(body.get("candidates"), list) else []
    if not candidates:
        return jsonify({"ok": False, "error": "missing_candidates"}), 400
    k = int(body.get("k") or 5)
    try:
        result = cluster_screen(candidates, k=k)
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# universe 纯函数 API（DSH 调用入口）
# ---------------------------------------------------------------------------

@app.route("/api/v1/universe/corr", methods=["POST"])
def universe_corr():
    """计算两个序列的相关性。

    Body:
        xs: [float, ...]
        ys: [float, ...]
        method: "pearson" | "spearman"   # 默认 pearson
    """
    body = _safe_get_json()
    xs = body.get("xs") if isinstance(body.get("xs"), list) else []
    ys = body.get("ys") if isinstance(body.get("ys"), list) else []
    if len(xs) < 10 or len(ys) < 10:
        return jsonify({"ok": False, "error": "insufficient_data"}), 400
    method = str(body.get("method") or "pearson").strip().lower()
    try:
        if method == "spearman":
            corr = _universe_spearman_corr(xs, ys)
        else:
            corr = _universe_pearson_corr(xs, ys)
        return jsonify({"ok": True, "corr": (round(corr, 4) if corr is not None else None)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/v1/universe/beta", methods=["POST"])
def universe_beta():
    """计算 beta（基于收益率序列）。

    Body:
        x_ret: [float, ...]   # 基准收益率序列
        y_ret: [float, ...]   # 标的收益率序列
    """
    body = _safe_get_json()
    x_ret_list = body.get("x_ret") if isinstance(body.get("x_ret"), list) else []
    y_ret_list = body.get("y_ret") if isinstance(body.get("y_ret"), list) else []
    if len(x_ret_list) < 10 or len(y_ret_list) < 10:
        return jsonify({"ok": False, "error": "insufficient_data"}), 400
    try:
        import numpy as np
        x_ret = np.array(x_ret_list, dtype=float)
        y_ret = np.array(y_ret_list, dtype=float)
        beta = _universe_beta_from_ret(x_ret, y_ret)
        return jsonify({"ok": True, "beta": (round(beta, 4) if beta is not None else None)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/v1/universe/aliases", methods=["GET"])
def universe_aliases():
    """解析交易对的所有别名形式。

    Query:
        pair: 交易对（如 BTC/USDT）
    """
    pair = str(request.args.get("pair") or "").strip()
    if not pair:
        return jsonify({"ok": False, "error": "missing_pair"}), 400
    try:
        aliases = _universe_pair_aliases(pair)
        return jsonify({"ok": True, "pair": pair, "aliases": aliases})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Freqtrade webhook
# ---------------------------------------------------------------------------

@app.route("/webhook/freqtrade", methods=["POST"])
def freqtrade_webhook():
    """Freqtrade webhook 接收入口。

    Freqtrade 配置 webhook.url 指向此 endpoint，POST 事件 payload。

    事件类型（自动归一）：
        entry | exit | exit_cancel | entry_fill | exit_fill | status
    """
    body = _safe_get_json()
    if not body:
        return jsonify({"ok": False, "error": "empty_payload"}), 400
    try:
        result = handle_webhook(body)
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/v1/webhook/events", methods=["GET"])
def webhook_events():
    """查询 webhook 事件日志。

    Query:
        type: 事件类型（可选过滤）
        pair: 交易对（可选过滤）
        limit: 最大返回数量（默认 100）
    """
    event_type = request.args.get("type")
    pair = request.args.get("pair")
    limit = int(request.args.get("limit") or 100)
    try:
        result = query_events(event_type=event_type, pair=pair, limit=limit)
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# P3: 回测辅助 API（show-trades / download-data / plot-profit）
# ---------------------------------------------------------------------------

# 导入 M25 回测引擎
_M25_DIR = Path(__file__).resolve().parents[1] / "25-用户策略生成系统"
if str(_M25_DIR) not in sys.path:
    sys.path.insert(0, str(_M25_DIR))


@app.route("/api/v1/backtest/trades", methods=["POST"])
def backtest_show_trades():
    """展示回测交易记录。"""
    try:
        from strategy_gen.backtest_engine import show_trades
        body = _safe_get_json()
        strategy_id = body.get("strategy_id")
        if not strategy_id:
            return jsonify({"ok": False, "error": "strategy_id required"}), 400
        result = show_trades(
            strategy_id,
            timerange=body.get("timerange"),
            pairs=body.get("pairs"),
            timeframe=body.get("timeframe"),
        )
        return jsonify(result)
    except ImportError as e:
        return jsonify({"ok": False, "error": f"import_error: {e}"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/v1/backtest/download-data", methods=["POST"])
def backtest_download_data():
    """下载 OHLCV 数据。"""
    try:
        from strategy_gen.backtest_engine import download_data
        body = _safe_get_json()
        pairs = body.get("pairs")
        if not pairs:
            return jsonify({"ok": False, "error": "pairs required"}), 400
        result = download_data(
            pairs,
            timeframe=body.get("timeframe", "1h"),
            timerange=body.get("timerange", "20260101-"),
            exchange=body.get("exchange", "okx"),
        )
        return jsonify(result)
    except ImportError as e:
        return jsonify({"ok": False, "error": f"import_error: {e}"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/v1/backtest/plot-profit", methods=["POST"])
def backtest_plot_profit():
    """生成回测利润图。"""
    try:
        from strategy_gen.backtest_engine import plot_profit
        body = _safe_get_json()
        strategy_id = body.get("strategy_id")
        if not strategy_id:
            return jsonify({"ok": False, "error": "strategy_id required"}), 400
        result = plot_profit(
            strategy_id,
            timerange=body.get("timerange"),
            pairs=body.get("pairs"),
            timeframe=body.get("timeframe"),
        )
        return jsonify(result)
    except ImportError as e:
        return jsonify({"ok": False, "error": f"import_error: {e}"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# 启动入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("SIGNAL_TRIGGER_PORT", "8096"))
    app.run(host="0.0.0.0", port=port, debug=False)
