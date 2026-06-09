#!/usr/bin/env python3
"""
实时数据 WebSocket API
======================
通过 WebSocket 提供实时行情数据推送
"""

import json
import logging
import threading
import subprocess
import time
from queue import Queue, Empty
from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)

# 尝试导入 flask-socketio
try:
    from flask_socketio import SocketIO, emit, join_room, leave_room
    SOCKETIO_AVAILABLE = True
except ImportError:
    SOCKETIO_AVAILABLE = False
    logger.warning("Flask-SocketIO not available. Run: pip install flask-socketio")

# 创建 Blueprint
realtime_bp = Blueprint('realtime', __name__)

# SocketIO 实例（由主应用创建）
socketio = None

# OKX WebSocket 数据队列
ws_data_queue = Queue()
ws_running = False
ws_thread = None


def init_socketio(app):
    """初始化 SocketIO"""
    global socketio
    if SOCKETIO_AVAILABLE:
        socketio = SocketIO(
            app,
            cors_allowed_origins="*",
            async_mode='threading',
            ping_timeout=60,
            ping_interval=25
        )
        _register_socketio_handlers()
        logger.info("✅ SocketIO initialized")
        return socketio
    return None


def _register_socketio_handlers():
    """注册 SocketIO 事件处理器"""
    if not SOCKETIO_AVAILABLE or socketio is None:
        return
    
    @socketio.on('connect')
    def handle_connect():
        logger.info(f"[WS] Client connected: {request.sid}")
        emit('connected', {
            'sid': request.sid,
            'message': 'Connected to Dream Universal Gateway'
        })
    
    @socketio.on('disconnect')
    def handle_disconnect():
        logger.info(f"[WS] Client disconnected: {request.sid}")
    
    @socketio.on('subscribe')
    def handle_subscribe(data):
        """订阅行情频道"""
        channel = data.get('channel', '')
        if not channel:
            emit('error', {'message': 'Channel required'})
            return
        
        # 解析频道类型和标的
        if ':' in channel:
            channel_type, inst_id = channel.split(':', 1)
        else:
            channel_type = channel
            inst_id = None
        
        room = channel  # 使用频道作为 room
        join_room(room)
        
        logger.info(f"[WS] {request.sid} subscribed to {channel}")
        
        # 发送确认
        emit('subscribed', {
            'channel': channel,
            'message': f'Subscribed to {channel}'
        })
        
        # 发送缓存数据
        from .websocket_manager import ws_manager
        cached_data = ws_manager.get_cache(channel)
        if cached_data:
            emit('snapshot', {
                'channel': channel,
                'data': cached_data
            })
    
    @socketio.on('unsubscribe')
    def handle_unsubscribe(data):
        """取消订阅"""
        channel = data.get('channel', '')
        if channel:
            leave_room(channel)
            emit('unsubscribed', {
                'channel': channel,
                'message': f'Unsubscribed from {channel}'
            })
    
    @socketio.on('ticker')
    def handle_ticker_request(data):
        """请求行情数据"""
        inst_id = data.get('inst_id', 'BTC-USDT-SWAP')
        
        # 获取实时行情
        from ..scripts.okx_cli import OKXCLI
        try:
            okx = OKXCLI(profile='paper')
            result = okx.get_ticker(inst_id)
            
            emit('ticker_response', {
                'inst_id': inst_id,
                'data': result.get('data', {}),
                'success': result.get('success', False)
            })
        except Exception as e:
            emit('error', {
                'message': f'Failed to get ticker: {str(e)}'
            })
    
    @socketio.on('subscribe_realtime')
    def handle_subscribe_realtime(data):
        """订阅实时行情（启动 OKX WebSocket）"""
        global ws_running
        
        inst_ids = data.get('inst_ids', ['BTC-USDT-SWAP'])
        
        if not ws_running:
            _start_okx_ws(inst_ids)
        
        for inst_id in inst_ids:
            room = f"ticker:{inst_id}"
            join_room(room)
        
        emit('realtime_subscribed', {
            'inst_ids': inst_ids,
            'message': 'Subscribed to real-time data'
        })


def _start_okx_ws(inst_ids: list):
    """启动 OKX WebSocket 客户端"""
    global ws_running, ws_thread
    
    if ws_running:
        return
    
    ws_running = True
    ws_thread = threading.Thread(
        target=_okx_ws_loop,
        args=(inst_ids,),
        daemon=True
    )
    ws_thread.start()
    logger.info(f"[WS] OKX WebSocket loop started for {inst_ids}")


def _okx_ws_loop(inst_ids: list):
    """OKX WebSocket 数据循环"""
    global ws_running
    
    import sys
    PROJECT_ROOT = __file__.parent.parent.parent
    sys.path.insert(0, str(PROJECT_ROOT))
    
    from ..scripts.okx_cli import OKXCLI
    
    okx = OKXCLI(profile='paper')
    
    while ws_running:
        try:
            for inst_id in inst_ids:
                result = okx.get_ticker(inst_id)
                if result.get('success'):
                    data = result.get('data', {})
                    
                    # 通过 SocketIO 广播
                    if socketio:
                        channel = f"ticker:{inst_id}"
                        socketio.emit('ticker', {
                            'inst_id': inst_id,
                            'data': data
                        }, room=channel)
                    
                    # 更新缓存
                    from .websocket_manager import ws_manager
                    ws_manager.update_ticker(inst_id, data)
            
            time.sleep(5)  # 每5秒更新一次
            
        except Exception as e:
            logger.error(f"[WS] OKX WS loop error: {e}")
            time.sleep(10)


def stop_okx_ws():
    """停止 OKX WebSocket"""
    global ws_running
    ws_running = False
    logger.info("[WS] OKX WebSocket loop stopped")


# ========== REST API 端点 ==========

@realtime_bp.route('/ws/status', methods=['GET'])
def ws_status():
    """WebSocket 状态"""
    from .websocket_manager import ws_manager
    
    stats = ws_manager.get_stats()
    channels = ws_manager.get_channels()
    
    return jsonify({
        "websocket_enabled": SOCKETIO_AVAILABLE,
        "stats": stats,
        "channels": channels
    })


@realtime_bp.route('/ws/subscribe', methods=['POST'])
def http_subscribe():
    """HTTP 订阅（轮询模式）"""
    data = request.get_json() or {}
    inst_id = data.get('inst_id', 'BTC-USDT-SWAP')
    
    from .websocket_manager import ws_manager
    from ..scripts.okx_cli import OKXCLI
    
    try:
        okx = OKXCLI(profile='paper')
        result = okx.get_ticker(inst_id)
        
        # 更新缓存
        if result.get('success'):
            ws_manager.update_ticker(inst_id, result.get('data', {}))
        
        return jsonify(result)
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@realtime_bp.route('/ws/broadcast', methods=['POST'])
def http_broadcast():
    """HTTP 广播（用于测试）"""
    data = request.get_json() or {}
    channel = data.get('channel', '')
    message = data.get('message', {})
    
    if not channel:
        return jsonify({
            "success": False,
            "error": "Channel required"
        }), 400
    
    from .websocket_manager import ws_manager
    
    if socketio:
        socketio.emit('broadcast', {
            'channel': channel,
            'message': message
        }, room=channel)
        return jsonify({
            "success": True,
            "broadcasted_to": channel
        })
    else:
        count = ws_manager.broadcast(channel, message)
        return jsonify({
            "success": True,
            "recipients": count
        })
