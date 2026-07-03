"""
Dreambuddy OS — HTTP API 服务

基于 Flask 的 RESTful API，对外暴露 TradingAgent 能力。

端点:
    POST   /api/v1/analyze          交易分析（市场数据驱动）
    POST   /api/v1/chat             对话式分析（自然语言）
    GET    /api/v1/status           Agent 状态
    GET    /api/v1/nodes            已注册节点列表
    GET    /api/v1/history          历史记录
    GET    /api/v1/health           健康检查

启动:
    python -m dreamos.apps.api_server
    # 或
    from dreamos.apps.api_server import create_app
    app = create_app()
    app.run(host="0.0.0.0", port=8000)
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from flask import Flask, jsonify, request

from dreamos.apps.trading_agent import TradingAgent


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
