"""
Dreambuddy OS — HTTP API 服务

基于 Flask 的 RESTful API，对外暴露 TradingAgent 能力。

标准端点（文档 §7.3 定义）:
    POST   /api/v1/run              执行一次完整推理
    POST   /api/v1/intent           只做意图识别
    GET    /api/v1/nodes            已注册节点列表
    GET    /api/v1/history          历史记录
    GET    /api/v1/health           健康检查

扩展端点（工程增强）:
    POST   /api/v1/analyze          交易分析（= /run 的交易专用别名）
    POST   /api/v1/chat             对话式分析（自然语言）
    GET    /api/v1/status           Agent 状态
    POST   /api/v1/budget/reset     重置预算
    GET    /api/v1/budget           获取预算状态

启动:
    python -m dreamos.apps.api_server
    # 或
    from dreamos.apps.api_server import create_app
    app = create_app()
    app.run(host="0.0.0.0", port=8000)
"""

from __future__ import annotations

import os
import threading
from typing import Any, Dict, Optional

from flask import Flask, jsonify, request

from dreamos.apps.trading_agent import TradingAgent


def _parse_phase(raw: Any) -> Optional[int]:
    """解析请求体中的 phase 参数（渐进式编排档位）

    仅接受 1 或 2；其余（None/非法值）返回 None = 完整编排。
    """
    if raw in (1, 2, "1", "2"):
        return int(raw)
    return None


def _fetch_live_price(symbol: str) -> float:
    """从 Hyperliquid 拉取实时中间价。失败返回 0。"""
    import json as _json
    import urllib.request
    try:
        req = urllib.request.Request(
            "https://api.hyperliquid.xyz/info",
            data=_json.dumps({"type": "allMids"}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            mids = _json.loads(resp.read().decode())
        return float(mids.get(symbol.upper(), 0))
    except Exception:
        return 0.0


def _enrich_market_data(market_data: Dict) -> Dict:
    """如果 market_data 中没有 price，从 Hyperliquid 获取实时价格注入。"""
    if not market_data.get("price") and market_data.get("symbol"):
        price = _fetch_live_price(market_data["symbol"])
        if price > 0:
            market_data["price"] = price
    return market_data


def create_app(agent: Optional[TradingAgent] = None,
               budget_mode: str = "standard") -> Flask:
    """创建 Flask 应用

    Args:
        agent: 复用已有的 TradingAgent 实例，None 则新建
        budget_mode: 预算模式 (lean/standard/full)

    Returns:
        Flask 应用实例
    """
    app = Flask(__name__)

    # 配置
    app.config["JSON_AS_ASCII"] = False  # 支持中文
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB

    # Agent 实例
    _agent = agent or TradingAgent(budget_mode=budget_mode)

    # ============================================================
    # 路由
    # ============================================================

    @app.get("/api/v1/health")
    def health():
        """健康检查"""
        return jsonify({
            "status": "ok",
            "service": "dreambuddy-os",
            "version": "0.1.0",
        })

    @app.get("/api/v1/status")
    def get_status():
        """Agent 运行状态"""
        return jsonify(_agent.status())

    @app.get("/api/v1/nodes")
    def list_nodes():
        """列出所有已注册节点"""
        nodes = _agent.registry.list_nodes()
        return jsonify({
            "total": len(nodes),
            "nodes": [
                {
                    "node_id": n.node_id,
                    "name": n.name,
                    "chain": n.chain,
                    "description": n.description,
                    "tags": list(n.tags or []),
                    "estimated_tokens": n.estimated_tokens,
                    "estimated_latency_ms": n.estimated_latency_ms,
                }
                for n in nodes
            ],
        })

    @app.post("/api/v1/run")
    def run_analysis():
        """执行一次完整推理（文档 §7.3 标准端点）

        请求体:
            {
                "user_input": "",               // 可选：用户自然语言输入
                "market_data": { ... },         // 可选：市场数据
                "context": {},                  // 可选：上下文
                "phase": 1                      // 可选：渐进式编排档位（1=仅必要节点）
            }
        """
        data = request.get_json(silent=True) or {}
        user_input = data.get("user_input", "")
        market_data = data.get("market_data", {})
        context = data.get("context", {})
        intent_hint = data.get("intent_hint")
        phase = _parse_phase(data.get("phase"))

        if not market_data and not user_input:
            return jsonify({"error": "user_input or market_data required"}), 400

        market_data = _enrich_market_data(market_data)

        try:
            result = _agent.run(
                user_input=user_input,
                market_data=market_data,
                context=context,
                intent_hint=intent_hint if isinstance(intent_hint, dict) else None,
                phase=phase,
            )
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": f"执行失败: {str(e)}"}), 500

    # ── 异步编排（20260829-bridge S7）：提交即返，轮询取果 ──
    # 解决同步 /run 54s 级延迟阻塞前端的问题。
    # 内存注册表 + 锁；容量上限 200 条，超出淘汰最旧。
    _async_results: Dict[str, Dict[str, Any]] = {}
    _async_lock = threading.Lock()
    _ASYNC_MAX_ENTRIES = 200

    def _async_trim_locked() -> None:
        while len(_async_results) > _ASYNC_MAX_ENTRIES:
            _async_results.pop(next(iter(_async_results)), None)

    @app.post("/api/v1/run/async")
    def run_analysis_async():
        """异步执行完整推理：立即返回 {cycle_id, status:"accepted"}（HTTP 202），
        后台线程执行，GET /api/v1/result/<cycle_id> 轮询结果。

        请求体同 /api/v1/run（user_input/market_data/context/intent_hint/phase）。
        """
        data = request.get_json(silent=True) or {}
        user_input = data.get("user_input", "")
        market_data = data.get("market_data", {})
        context = data.get("context", {})
        intent_hint = data.get("intent_hint")
        phase = _parse_phase(data.get("phase"))

        if not market_data and not user_input:
            return jsonify({"error": "user_input or market_data required"}), 400

        market_data = _enrich_market_data(market_data)

        from dreamos.shared.utils import gen_cycle_id
        async_cycle_id = gen_cycle_id("async")
        # 把异步句柄写入 context，便于结果回溯
        if isinstance(context, dict):
            context.setdefault("async_cycle_id", async_cycle_id)

        with _async_lock:
            _async_results[async_cycle_id] = {
                "status": "pending", "result": None, "error": None,
            }
            _async_trim_locked()

        def _worker() -> None:
            with _async_lock:
                entry = _async_results.get(async_cycle_id)
                if entry is not None:
                    entry["status"] = "running"
            try:
                result = _agent.run(
                    user_input=user_input,
                    market_data=market_data,
                    context=context,
                    intent_hint=intent_hint if isinstance(intent_hint, dict) else None,
                    phase=phase,
                )
                with _async_lock:
                    _async_results[async_cycle_id] = {
                        "status": "done", "result": result, "error": None,
                    }
            except Exception as e:  # noqa: BLE001 — 异步任务必须兜底
                with _async_lock:
                    _async_results[async_cycle_id] = {
                        "status": "error", "result": None, "error": str(e),
                    }

        threading.Thread(
            target=_worker, name=f"dreamos-async-{async_cycle_id}", daemon=True,
        ).start()
        return jsonify({"cycle_id": async_cycle_id, "status": "accepted"}), 202

    @app.get("/api/v1/result/<cycle_id>")
    def get_async_result(cycle_id: str):
        """轮询异步编排结果：{cycle_id, status, result?, error?}
        status: pending → running → done | error；未知 cycle_id 返回 404。"""
        with _async_lock:
            entry = _async_results.get(cycle_id)
            if entry is None:
                return jsonify({"error": f"unknown cycle_id: {cycle_id}"}), 404
            return jsonify({"cycle_id": cycle_id, **entry})

    @app.post("/api/v1/intent")
    def recognize_intent():
        """只做意图识别（文档 §7.3 标准端点）

        不执行完整分析链路，仅返回 S 层意图识别结果。

        请求体:
            {
                "user_input": "分析 BTC 趋势",   // 用户输入
                "market_data": { ... },         // 可选：市场数据
                "context": {}                   // 可选：上下文
            }
        """
        data = request.get_json(silent=True) or {}
        user_input = data.get("user_input", "")
        market_data = data.get("market_data", {})
        context = data.get("context", {})

        if not user_input and not market_data:
            return jsonify({"error": "user_input or market_data required"}), 400

        try:
            intent_result = _agent.intent_engine.recognize(
                user_message=user_input,
                market=market_data,
                context=context,
            )
            return jsonify({
                "intent_type": intent_result.intent_type,
                "confidence": intent_result.confidence,
                "recommended_chain": intent_result.recommended_chain,
                "base_chain": getattr(intent_result, "base_chain", []),
                "extend_nodes": getattr(intent_result, "extend_nodes", []),
                "rationale": getattr(intent_result, "rationale", ""),
                "recognizers_used": getattr(intent_result, "recognizers_used", []),
                "total_tokens": getattr(intent_result, "total_tokens", 0),
                "total_latency_ms": getattr(intent_result, "total_latency_ms", 0),
                "clarify_needed": getattr(intent_result, "clarify_needed", False),
                "clarify_question": getattr(intent_result, "clarify_question", ""),
            })
        except Exception as e:
            return jsonify({"error": f"意图识别失败: {str(e)}"}), 500

    @app.post("/api/v1/analyze")
    def analyze():
        """交易分析（市场数据驱动）

        请求体:
            {
                "market_data": { ... },     // 市场数据
                "user_input": "",            // 可选：用户输入
                "context": {}                // 可选：上下文
            }
        """
        data = request.get_json(silent=True) or {}
        market_data = data.get("market_data", {})
        user_input = data.get("user_input", "")
        context = data.get("context", {})

        if not market_data and not user_input:
            return jsonify({"error": "market_data or user_input required"}), 400

        try:
            result = _agent.run(
                user_input=user_input,
                market_data=market_data,
                context=context,
            )
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": f"分析失败: {str(e)}"}), 500

    @app.post("/api/v1/chat")
    def chat():
        """对话式分析

        请求体:
            {
                "message": "BTC 现在能做多吗？",
                "market_data": { ... }        // 可选
            }
        """
        data = request.get_json(silent=True) or {}
        message = data.get("message", "")
        market_data = data.get("market_data", {})

        if not message:
            return jsonify({"error": "message required"}), 400

        try:
            result = _agent.chat(message=message, market_data=market_data)
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": f"对话失败: {str(e)}"}), 500

    @app.get("/api/v1/history")
    def get_history():
        """历史记录

        Query 参数:
            limit: 返回数量（默认 10）
        """
        try:
            limit = int(request.args.get("limit", 10))
            limit = min(max(limit, 1), 100)
            entries = _agent.history(limit=limit)
            return jsonify({
                "total": len(entries),
                "entries": entries,
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.post("/api/v1/budget/reset")
    def reset_budget():
        """重置预算"""
        try:
            _agent.budget.reset()
            return jsonify({"status": "ok", "budget": _agent.budget.status()})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.get("/api/v1/budget")
    def get_budget():
        """获取预算状态"""
        return jsonify(_agent.budget.status())

    # ============================================================
    # 错误处理
    # ============================================================

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "not found"}), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({"error": "method not allowed"}), 405

    @app.errorhandler(500)
    def server_error(e):
        return jsonify({"error": "internal server error"}), 500

    return app


def main():
    """命令行启动入口"""
    import argparse

    parser = argparse.ArgumentParser(description="Dreambuddy OS HTTP API Server")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument("--budget", default="standard",
                        choices=["lean", "standard", "full"],
                        help="预算模式")
    parser.add_argument("--debug", action="store_true", help="调试模式")
    args = parser.parse_args()

    app = create_app(budget_mode=args.budget)

    print(f"🚀 Dreambuddy OS API Server starting...")
    print(f"   Host: {args.host}:{args.port}")
    print(f"   Budget mode: {args.budget}")
    print(f"   Health: http://localhost:{args.port}/api/v1/health")
    print(f"   Status: http://localhost:{args.port}/api/v1/status")
    print()

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
