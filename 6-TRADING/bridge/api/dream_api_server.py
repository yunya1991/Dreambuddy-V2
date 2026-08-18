#!/usr/bin/env python3
"""
Dream Universal Gateway - API服务器核心 v1.1
==============================================
提供完整的REST API + WebSocket接口

新增 v1.1:
- WebSocket 实时数据推送
- 请求日志和性能监控
- 完善的错误处理
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import logging
from datetime import datetime

# 导入各模块API
from .market_data_api import market_bp
from .trade_exec_api import trade_bp
from .skill_router_api import skill_bp
from .intent_router_api import intent_bp
from .bridge_management_api import bridge_bp
from .realtime_api import realtime_bp

# 导入监控模块
from .monitoring import (
    request_logging_middleware,
    register_error_handlers,
    request_logger
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_app(init_websocket: bool = True):
    """创建Flask应用
    
    Args:
        init_websocket: 是否初始化 WebSocket (需要 flask-socketio)
    """
    app = Flask(__name__)
    
    # CORS配置 - 允许前端访问
    CORS(app, resources={
        r"/api/*": {
            "origins": [
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                "http://localhost:3456",
                "http://127.0.0.1:3456",
                "http://localhost:3847"
            ],
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"]
        }
    })
    
    # 注册蓝图
    app.register_blueprint(market_bp, url_prefix='/api/market')
    app.register_blueprint(trade_bp, url_prefix='/api/trade')
    app.register_blueprint(skill_bp, url_prefix='/api/skill')
    app.register_blueprint(intent_bp, url_prefix='/api/intent')
    app.register_blueprint(bridge_bp, url_prefix='/api/bridge')
    app.register_blueprint(realtime_bp, url_prefix='/api/realtime')
    
    # 添加请求日志中间件
    request_logging_middleware(app)
    
    # 注册错误处理器
    register_error_handlers(app)
    
    # 全局请求日志
    @app.before_request
    def log_request():
        logger.info(f"[{datetime.now().isoformat()}] {request.method} {request.path}")
    
    # 健康检查端点
    @app.route('/api/health', methods=['GET'])
    def health_check():
        return jsonify({
            "status": "healthy",
            "service": "Dream Universal Gateway Bridge",
            "version": "1.1.0",
            "timestamp": datetime.now().isoformat(),
            "features": {
                "websocket": True,
                "monitoring": True,
                "logging": True
            },
            "endpoints": {
                "market": "/api/market/*",
                "trade": "/api/trade/*",
                "skill": "/api/skill/*",
                "intent": "/api/intent/*",
                "bridge": "/api/bridge/*",
                "realtime": "/api/realtime/*"
            }
        })
    
    # 监控统计端点
    @app.route('/api/monitor/stats', methods=['GET'])
    def monitor_stats():
        """获取请求统计"""
        hours = request.args.get('hours', 1, type=int)
        return jsonify(request_logger.get_stats(hours=hours))
    
    @app.route('/api/monitor/recent', methods=['GET'])
    def monitor_recent():
        """获取最近请求"""
        limit = request.args.get('limit', 50, type=int)
        return jsonify({
            "requests": request_logger.get_recent(limit=limit)
        })
    
    # 根路径
    @app.route('/', methods=['GET'])
    def index():
        return jsonify({
            "service": "Dream Universal Gateway Bridge API",
            "version": "1.0.0",
            "docs": "/api/health",
            "endpoints": [
                "GET  /api/health - 健康检查",
                "GET  /api/market/ticker/<inst_id> - 获取行情",
                "GET  /api/market/candles/<inst_id> - 获取K线",
                "POST /api/trade/order - 下单",
                "POST /api/skill/execute - 执行SKILL",
                "POST /api/intent/route - 意图路由",
                "GET  /api/bridge/status - 桥接状态"
            ]
        })
    
    # 错误处理 (使用统一的监控模块处理，这里只保留兜底)
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({
            "error": "Not Found",
            "message": f"Endpoint {request.path} not found",
            "available_endpoints": [
                "/api/health",
                "/api/market/*",
                "/api/trade/*",
                "/api/skill/*",
                "/api/intent/*",
                "/api/bridge/*",
                "/api/realtime/*"
            ]
        }), 404
    
    @app.errorhandler(500)
    def internal_error(e):
        logger.error(f"Internal error: {e}")
        return jsonify({
            "error": "Internal Server Error",
            "message": str(e)
        }), 500
    
    # WebSocket 端点说明
    @app.route('/api/realtime/info', methods=['GET'])
    def realtime_info():
        """WebSocket 使用说明"""
        return jsonify({
            "websocket_endpoint": "/socket.io/",
            "events": {
                "connect": "连接成功",
                "subscribe": "订阅频道",
                "unsubscribe": "取消订阅",
                "ticker": "实时行情",
                "ticker_request": "请求行情",
                "subscribe_realtime": "订阅实时数据流"
            },
            "channels": [
                "ticker:BTC-USDT-SWAP",
                "ticker:ETH-USDT-SWAP",
                "candles:BTC-USDT-SWAP"
            ],
            "rest_fallback": {
                "status": "/api/realtime/ws/status",
                "subscribe": "/api/realtime/ws/subscribe",
                "broadcast": "/api/realtime/ws/broadcast"
            }
        })
    
    logger.info("✅ Dream Bridge API Server initialized")
    return app
