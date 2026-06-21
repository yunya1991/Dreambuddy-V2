"""
基本面分析模块化API服务 v2
Flask + flask-cors 实现，端口9094
"""

import os
import json
import argparse
import math
from datetime import datetime, timezone, timedelta
from functools import wraps
from threading import Thread
from typing import Dict, Any, List, Optional

from flask import Flask, jsonify, request
from flask_cors import CORS

# 导入内部模块
from data_collector import DataCollector, generate_timeseries
from engines.least_resistance import compute_resistance_3d, generate_signal, summarize_trend
from engines.sentiment_engine import create_sentiment_engine
from engines.signal_engine import create_signal_engine

# ============== 全局变量 ==============
app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STORAGE_DIR = os.path.join(BASE_DIR, "storage")
SNAPSHOT_DIR = os.path.join(STORAGE_DIR, "snapshots")
TIMESERIES_DIR = os.path.join(STORAGE_DIR, "timeseries")

# 确保目录存在
os.makedirs(SNAPSHOT_DIR, exist_ok=True)
os.makedirs(TIMESERIES_DIR, exist_ok=True)

# 全局数据收集器和引擎
collector = DataCollector(STORAGE_DIR)
sentiment_engine = create_sentiment_engine()
signal_engine = create_signal_engine()

# 10个模块定义
MODULES = [
    "news", "flow", "sentiment", "macro",
    "breadth", "intermarket", "valuation", "onchain",
    "calendar", "narrative"
]

# 模块到数据采集方法的映射
MODULE_COLLECTORS = {
    "news": collector.collect_news,
    "flow": collector.collect_flow,
    "sentiment": collector.collect_sentiment,
    "macro": collector.collect_macro,
    "breadth": collector.collect_breadth,
    "intermarket": collector.collect_intermarket,
    "valuation": collector.collect_valuation,
    "onchain": collector.collect_onchain,
    "calendar": collector.collect_calendar,
    "narrative": collector.collect_narrative,
}


# ============== 工具函数 ==============

def load_snapshot(module: str) -> Optional[Dict]:
    """加载模块快照"""
    path = os.path.join(SNAPSHOT_DIR, f"{module}_snapshot.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def save_snapshot(module: str, data: Dict) -> None:
    """保存模块快照"""
    path = os.path.join(SNAPSHOT_DIR, f"{module}_snapshot.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Error] 保存快照失败 {module}: {e}")


def load_timeseries(module: str, days: int = 30) -> List[Dict]:
    """加载时间序列数据"""
    path = os.path.join(TIMESERIES_DIR, f"{module}_timeseries.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 过滤指定天数
                cutoff = datetime.now(timezone.utc) - timedelta(days=days)
                cutoff_str = cutoff.isoformat()
                return [d for d in data if d.get("timestamp", "") >= cutoff_str]
        except Exception:
            pass
    return generate_timeseries(module, days)


def save_timeseries(module: str, data: List[Dict]) -> None:
    """保存时间序列数据"""
    path = os.path.join(TIMESERIES_DIR, f"{module}_timeseries.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Error] 保存时间序列失败 {module}: {e}")


def compute_module_resistance(module: str, raw_data: Dict) -> Dict:
    """
    计算单个模块的三维度

    Args:
        module: 模块名
        raw_data: 原始数据，新格式 {metrics: {core, breakdown}, events, timeseries, timestamp}

    Returns:
        三维度结果
    """
    # 从原始数据提取评分（优先从 metrics.core 读取）
    score_key_map = {
        "news": ("sentiment_sum", 0.5),
        "flow": ("fund_flow_score", 0.0),
        "sentiment": ("sentiment_index", 50),
        "macro": ("policy_score", 0.0),
        "breadth": ("advance_decline_line", 0.0),
        "intermarket": ("dxy_correlation", 0.0),
        "valuation": ("mvrv_ratio", 2.5),
        "onchain": ("exchange_net_flow", 0.0),
        "calendar": ("impact_score", 0.5),
        "narrative": ("market_consensus", 0.5),
    }

    key, default = score_key_map.get(module, ("sentiment_sum", 0.5))

    metrics = raw_data.get('metrics', {}) if isinstance(raw_data, Dict) else {}
    metrics_core = metrics.get('core', {}) if isinstance(metrics, Dict) else {}

    # 优先从 core 读取；如果不存在 core 字段则回退到旧的平铺格式
    if metrics_core and key in metrics_core:
        raw_score = metrics_core[key]
    else:
        raw_score = raw_data.get(key, default)

    # 归一化到 -1 to 1
    if key == "sentiment_index" or key == "sentiment_sum":
        normalized = (raw_score - 50) / 50  # 0-100 -> -1 to 1
    elif key == "mvrv_ratio":
        normalized = (raw_score - 2.5) / 1.5  # 基于2.5中心
    elif key == "exchange_net_flow":
        normalized = max(-1, min(1, raw_score / 500))  # 百万美元级别除以500
    elif key in ["fund_flow_score", "policy_score", "advance_decline_line",
                 "dxy_correlation", "impact_score", "market_consensus"]:
        normalized = max(-1, min(1, raw_score))
    elif isinstance(raw_score, (int, float)):
        normalized = max(-1, min(1, raw_score))
    else:
        normalized = raw_score

    # 历史数据：优先从 raw_data.timeseries 提取，否则使用 load_timeseries
    raw_timeseries = raw_data.get('timeseries', None) if isinstance(raw_data, Dict) else None
    if raw_timeseries and isinstance(raw_timeseries, list) and len(raw_timeseries) > 0:
        first = raw_timeseries[0]
        if isinstance(first, dict) and 'value' in first:
            historical = [p.get('value', 0) for p in raw_timeseries]
        else:
            historical = raw_timeseries
    else:
        ts_data = load_timeseries(module, days=30)
        historical = [d.get("value", 0) for d in ts_data]

    return compute_resistance_3d(normalized, historical)


def build_module_snapshot(module: str) -> Dict:
    """
    构建模块快照

    Args:
        module: 模块名

    Returns:
        完整的模块快照
    """
    # 采集数据
    collector_func = MODULE_COLLECTORS.get(module)
    if not collector_func:
        return {"error": f"Unknown module: {module}"}

    raw_data = collector_func()

    # 计算三维度
    resistance_3d = compute_module_resistance(module, raw_data)

    # metrics 直接存 {core, breakdown} 结构
    metrics = raw_data.get('metrics', {}) if isinstance(raw_data, Dict) else {}

    # signals：把整个 metrics 对象传给 signal_engine.generate_signals
    signals = signal_engine.generate_signals(
        resistance_3d,
        metrics,
        events=raw_data.get('events', []),
        stress="normal"
    )
    signals = signal_engine.rank_signals(signals)

    # metrics_flat：把 metrics.core 和 metrics.breakdown 合并成平铺 dict
    metrics_core = metrics.get('core', {}) if isinstance(metrics, Dict) else {}
    metrics_breakdown = metrics.get('breakdown', {}) if isinstance(metrics, Dict) else {}
    metrics_flat = {}
    for k, v in metrics_core.items():
        if isinstance(v, (int, float, str)):
            metrics_flat[k] = v
    for k, v in metrics_breakdown.items():
        if isinstance(v, (int, float, str)) and k not in metrics_flat:
            metrics_flat[k] = v

    # events：直接用 raw_data.events
    events = raw_data.get('events', [])[:10]

    # timeseries：优先用 raw_data.timeseries，避免两次随机
    ts_data = raw_data.get('timeseries', None) if isinstance(raw_data, Dict) else None
    if not ts_data or not isinstance(ts_data, list):
        ts_data = load_timeseries(module, days=7)

    # 构建响应
    ts = datetime.now(timezone.utc).isoformat()

    # 基础响应
    response = {
        "module": module,
        "ts": ts,
        "resistance_3d": resistance_3d,
        "signals": signals,
        "metrics": metrics,
        "metrics_flat": metrics_flat,
        "events": events,
        "timeseries": ts_data,
        "meta": {
            "source": ["Tavily"] if module in ["news", "flow", "sentiment", "macro", "calendar", "narrative"] else ["Mock"],
            "last_update": ts,
            "data_quality": "high" if module in ["news", "flow", "sentiment", "macro"] else "medium"
        }
    }

    # 传递差异化字段
    diff_fields = ["whale_transactions", "heatmap_data", "nupl", "realized_price", 
                   "market_price", "price_distance_from_realized", 
                   "utxo_age_distribution", "miner_outflow", "hash_rate", "exchange_reserve"]
    for field in diff_fields:
        if field in raw_data:
            response[field] = raw_data[field]

    return response


def refresh_module(module: str) -> Dict:
    """
    刷新模块数据

    Args:
        module: 模块名

    Returns:
        刷新后的快照
    """
    snapshot = build_module_snapshot(module)

    # 保存快照和时间序列
    save_snapshot(module, snapshot)

    # 更新时序数据
    ts_data = generate_timeseries(module, days=90)
    save_timeseries(module, ts_data)

    return snapshot


# ============== 错误处理装饰器 ==============

def handle_errors(f):
    """错误处理装饰器"""
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            print(f"[Error] {f.__name__}: {e}")
            return jsonify({"error": str(e)}), 500
    return decorated


# ============== API 路由 ==============

@app.route("/fundamental/health", methods=["GET"])
@handle_errors
def health():
    """健康检查"""
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "modules": MODULES,
        "version": "2.0"
    })


@app.route("/fundamental/overview", methods=["GET"])
@handle_errors
def overview():
    """全局总览 - 使用综合信号引擎"""
    all_snapshots = {}
    all_snapshots_dict = {}

    for module in MODULES:
        snapshot = load_snapshot(module)
        if snapshot:
            all_snapshots[module] = {
                "direction": snapshot.get("resistance_3d", {}).get("direction", "unknown"),
                "confidence": snapshot.get("resistance_3d", {}).get("confidence", 0),
                "trend_summary": snapshot.get("resistance_3d", {}).get("trend_summary", "")
            }
            all_snapshots_dict[module] = snapshot

    # 使用综合信号引擎
    composite = signal_engine.generate_composite_signals(all_snapshots_dict)

    return jsonify({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "modules": all_snapshots,
        "composite": composite,
        "summary": signal_engine.generate_summary(composite.get("top_signals", [])),
        "top_signals": composite["top_signals"][:5],
        "recommendation": composite["recommendation"],
        "module_count": len(MODULES)
    })


@app.route("/fundamental/composite-signal", methods=["GET"])
@handle_errors
def composite_signal():
    """综合信号 - 聚合所有模块生成跨维度交易建议"""
    all_snapshots = {}
    for module in MODULES:
        snap = load_snapshot(module)
        if snap:
            all_snapshots[module] = snap

    # 如果没有任何快照数据，先刷新
    if not all_snapshots:
        for module in MODULES[:3]:  # 只初始化关键3个模块，避免超时
            refresh_module(module)
            all_snapshots[module] = load_snapshot(module)

    composite = signal_engine.generate_composite_signals(all_snapshots)

    # 同时生成简短的中文摘要（供 AI 调用）
    summary = signal_engine.generate_summary(composite.get("top_signals", []))

    return jsonify({
        "ts": datetime.now(timezone.utc).isoformat(),
        "composite": composite,
        "summary": summary,
        "module_count": len(all_snapshots),
        "modules_used": list(all_snapshots.keys())
    })


@app.route("/fundamental/snapshot", methods=["GET"])
@handle_errors
def snapshot():
    """完整快照 - 返回所有模块的完整数据（兼容旧版前端）"""
    all_modules = {}

    for module in MODULES:
        snap = load_snapshot(module)
        if snap:
            # 保留完整模块数据
            all_modules[module] = snap

    # 1) 调用新的综合信号引擎
    composite = signal_engine.generate_composite_signals(all_modules)

    # 2) 构造 overall 字段
    overall_resistance_3d = {
        "direction": "up" if composite["score"] > 0.15 else "down" if composite["score"] < -0.15 else "neutral",
        "direction_score": composite["score"],
        "velocity": composite.get("avg_velocity", 0),
        "acceleration": composite.get("avg_acceleration", 0),
        "confidence": composite["confidence"],
        "data_points": len(all_modules),
        "trend_summary": composite["recommendation"],
    }

    # 3) overall_signal 用 composite["top_signals"][0]
    overall_signal = composite["top_signals"][0] if composite.get("top_signals") else {
        "type": "hold",
        "strength": 0.5,
        "reason": "等待更多信号",
        "horizon": "medium"
    }

    # 模块得分
    module_scores = {
        m: all_modules.get(m, {}).get("resistance_3d", {}).get("direction_score", 0)
        for m in MODULES
    }

    return jsonify({
        "ts": datetime.now(timezone.utc).isoformat(),
        "overall": {
            "resistance_3d": overall_resistance_3d,
            "signal": overall_signal,
            "module_scores": module_scores
        },
        "overall_composite": composite,
        "modules": all_modules
    })


# ============== 模块端点 ==============

def make_module_handlers():
    """为每个模块创建处理器"""

    def create_handlers(module_name):
        # Snapshot
        @app.route(f"/fundamental/{module_name}/snapshot", methods=["GET"], endpoint=f"snapshot_{module_name}")
        @handle_errors
        def get_snapshot():
            snapshot = load_snapshot(module_name)
            if not snapshot:
                snapshot = refresh_module(module_name)
            return jsonify(snapshot)

        # Timeseries
        @app.route(f"/fundamental/{module_name}/timeseries", methods=["GET"], endpoint=f"timeseries_{module_name}")
        @handle_errors
        def get_timeseries():
            range_param = request.args.get("range", "7d")
            days = {"7d": 7, "30d": 30, "90d": 90}.get(range_param, 7)
            ts_data = load_timeseries(module_name, days)
            return jsonify({
                "module": module_name,
                "range": range_param,
                "data": ts_data
            })

        # Signals
        @app.route(f"/fundamental/{module_name}/signals", methods=["GET"], endpoint=f"signals_{module_name}")
        @handle_errors
        def get_signals():
            snapshot = load_snapshot(module_name)
            if not snapshot:
                snapshot = refresh_module(module_name)
            return jsonify({
                "module": module_name,
                "signals": snapshot.get("signals", [])
            })

        # Events
        @app.route(f"/fundamental/{module_name}/events", methods=["GET"], endpoint=f"events_{module_name}")
        @handle_errors
        def get_events():
            limit = int(request.args.get("limit", 20))
            category = request.args.get("category")

            snapshot = load_snapshot(module_name)
            if not snapshot:
                snapshot = refresh_module(module_name)

            events = snapshot.get("events", [])
            if category:
                events = [e for e in events if category.lower() in str(e.get("category", "")).lower()]

            return jsonify({
                "module": module_name,
                "count": len(events),
                "events": events[:limit]
            })

        # Refresh
        @app.route(f"/fundamental/{module_name}/refresh", methods=["POST"], endpoint=f"refresh_{module_name}")
        @handle_errors
        def refresh():
            snapshot = refresh_module(module_name)
            return jsonify({
                "module": module_name,
                "status": "refreshed",
                "snapshot": snapshot
            })

    for module in MODULES:
        create_handlers(module)


make_module_handlers()


# ============== 启动函数 ==============

def background_collector():
    """后台数据采集"""
    print("[Background] Starting data collection...")
    while True:
        try:
            for module in MODULES:
                refresh_module(module)
                print(f"[Background] Refreshed {module}")
        except Exception as e:
            print(f"[Background] Collection error: {e}")


def start_background_thread():
    """启动后台采集线程"""
    thread = Thread(target=background_collector, daemon=True)
    thread.start()
    print("[Background] Collector thread started")


def main():
    """主入口"""
    parser = argparse.ArgumentParser(description="基本面分析API服务 v2")
    parser.add_argument("--port", type=int, default=9094, help="端口号")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="主机地址")
    parser.add_argument("--no-collect", action="store_true", help="禁用自动采集")
    args = parser.parse_args()

    print(f"[Init] 初始化数据采集...")

    # 初始化所有模块数据
    for module in MODULES:
        try:
            refresh_module(module)
            print(f"[Init] {module} initialized")
        except Exception as e:
            print(f"[Init] {module} init failed: {e}")

    # 启动后台采集
    if not args.no_collect:
        start_background_thread()

    print(f"[Init] 启动Flask服务 on {args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
