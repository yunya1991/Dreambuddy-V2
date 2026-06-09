#!/usr/bin/env python3
"""
Dream Universal Gateway - 桥接层API服务器 v1.1
===============================================
连接前端(dream-universal-gateway) 和 后端(scripts/)

功能:
- 封装 scripts/ 中的 Python 脚本为 REST API
- 提供市场数据、交易执行、情报监控等接口
- 支持用户意图路由到对应 SKILL
- WebSocket 实时数据推送 (v1.1)
- 请求日志和性能监控 (v1.1)

端口: 3847
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bridge.api.dream_api_server import create_app
from bridge.api.realtime_api import init_socketio

if __name__ == "__main__":
    app = create_app()
    
    # 尝试初始化 WebSocket
    try:
        socketio = init_socketio(app)
        ws_enabled = socketio is not None
    except ImportError:
        print("⚠️  Flask-SocketIO not installed. WebSocket disabled.")
        print("   Run: pip install flask-socketio")
        ws_enabled = False
        socketio = None
    
    # 启动配置
    host = os.getenv("BRIDGE_HOST", "127.0.0.1")
    port = int(os.getenv("BRIDGE_PORT", "3847"))
    debug = os.getenv("BRIDGE_DEBUG", "false").lower() == "true"
    
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║        Dream Universal Gateway - Bridge API Server v1.1      ║
╠══════════════════════════════════════════════════════════════╣
║  Status:     ✅ Running                                     ║
║  Host:       {host}:{port}                                          ║
║  Mode:       {'DEBUG' if debug else 'PRODUCTION'}                                        ║
║  WebSocket:  {'✅ Enabled' if ws_enabled else '❌ Disabled'}                              ║
║                                                              ║
║  Endpoints:                                                  ║
║  - /api/health          Health check                         ║
║  - /api/market/*        Market data (K线/行情)               ║
║  - /api/trade/*         Trade execution (交易执行)           ║
║  - /api/skill/*         SKILL routing (SKILL路由)           ║
║  - /api/intent/*        Intent routing (意图路由)           ║
║  - /api/bridge/*        Bridge management (桥接管理)         ║
║  - /api/realtime/*      Real-time data (实时数据)           ║
║  - /api/monitor/*       Monitoring (监控统计)               ║
║                                                              ║
║  WebSocket:   ws://{host}:{port}/socket.io/                     ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    if socketio:
        # 使用 SocketIO 运行 (allow_unsafe_werkzeug 用于生产环境)
        socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)
    else:
        # 回退到普通 Flask
        app.run(host=host, port=port, debug=debug)
