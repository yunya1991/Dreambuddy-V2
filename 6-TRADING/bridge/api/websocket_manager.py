#!/usr/bin/env python3
"""
WebSocket 管理器 - 实时数据推送
================================
管理 WebSocket 连接，处理实时行情数据订阅
"""

import json
import threading
import asyncio
import logging
from typing import Dict, Set, Callable, Any
from collections import defaultdict

logger = logging.getLogger(__name__)


class WebSocketManager:
    """WebSocket 连接管理器"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        
        # 连接管理
        self._connections: Set[Any] = set()
        self._connection_lock = threading.Lock()
        
        # 订阅管理: channel -> set of connections
        self._subscriptions: Dict[str, Set[Any]] = defaultdict(set)
        
        # 行情数据缓存
        self._ticker_cache: Dict[str, Dict] = {}
        self._candle_cache: Dict[str, list] = defaultdict(list)
        
        # WebSocket 客户端进程
        self._ws_process = None
        self._ws_thread = None
        self._running = False
        
        logger.info("✅ WebSocketManager initialized")
    
    def add_connection(self, ws) -> None:
        """添加 WebSocket 连接"""
        with self._connection_lock:
            self._connections.add(ws)
            logger.info(f"[WS] Connection added. Total: {len(self._connections)}")
    
    def remove_connection(self, ws) -> None:
        """移除 WebSocket 连接"""
        with self._connection_lock:
            if ws in self._connections:
                self._connections.remove(ws)
            
            # 清理订阅
            for channel in list(self._subscriptions.keys()):
                if ws in self._subscriptions[channel]:
                    self._subscriptions[channel].remove(ws)
                if not self._subscriptions[channel]:
                    del self._subscriptions[channel]
            
            logger.info(f"[WS] Connection removed. Total: {len(self._connections)}")
    
    def subscribe(self, ws, channel: str) -> bool:
        """订阅频道"""
        with self._connection_lock:
            self._subscriptions[channel].add(ws)
            logger.info(f"[WS] {ws} subscribed to {channel}. Total subs: {len(self._subscriptions[channel])}")
            
            # 发送缓存数据
            if channel.startswith("ticker:"):
                inst_id = channel.split(":", 1)[1]
                if inst_id in self._ticker_cache:
                    self._send_to(ws, {
                        "type": "ticker",
                        "channel": channel,
                        "data": self._ticker_cache[inst_id]
                    })
            
            return True
    
    def unsubscribe(self, ws, channel: str) -> bool:
        """取消订阅"""
        with self._connection_lock:
            if ws in self._subscriptions.get(channel, set()):
                self._subscriptions[channel].remove(ws)
                logger.info(f"[WS] {ws} unsubscribed from {channel}")
            return True
    
    def _send_to(self, ws, message: Dict) -> bool:
        """发送消息到单个连接"""
        try:
            ws.send(json.dumps(message))
            return True
        except Exception as e:
            logger.warning(f"[WS] Failed to send to {ws}: {e}")
            self.remove_connection(ws)
            return False
    
    def broadcast(self, channel: str, message: Dict) -> int:
        """广播消息到频道"""
        sent_count = 0
        with self._connection_lock:
            subscribers = self._subscriptions.get(channel, set()).copy()
        
        for ws in subscribers:
            if self._send_to(ws, message):
                sent_count += 1
        
        return sent_count
    
    def update_ticker(self, inst_id: str, data: Dict) -> int:
        """更新行情数据并广播"""
        self._ticker_cache[inst_id] = data
        
        channel = f"ticker:{inst_id}"
        message = {
            "type": "ticker",
            "channel": channel,
            "data": data,
            "timestamp": self._get_timestamp()
        }
        
        return self.broadcast(channel, message)
    
    def update_candles(self, inst_id: str, data: list) -> int:
        """更新K线数据并广播"""
        self._candle_cache[inst_id] = data
        
        channel = f"candles:{inst_id}"
        message = {
            "type": "candles",
            "channel": channel,
            "data": data,
            "timestamp": self._get_timestamp()
        }
        
        return self.broadcast(channel, message)
    
    def get_cache(self, channel: str) -> Any:
        """获取缓存数据"""
        if channel.startswith("ticker:"):
            inst_id = channel.split(":", 1)[1]
            return self._ticker_cache.get(inst_id)
        elif channel.startswith("candles:"):
            inst_id = channel.split(":", 1)[1]
            return self._candle_cache.get(inst_id)
        return None
    
    def _get_timestamp(self) -> str:
        """获取 ISO 时间戳"""
        from datetime import datetime
        return datetime.now().isoformat()
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        with self._connection_lock:
            return {
                "connections": len(self._connections),
                "channels": len(self._subscriptions),
                "subscriptions": sum(len(s) for s in self._subscriptions.values()),
                "ticker_cache_size": len(self._ticker_cache),
                "candle_cache_size": len(self._candle_cache),
                "running": self._running
            }
    
    def get_channels(self) -> list:
        """获取活跃频道列表"""
        with self._connection_lock:
            return list(self._subscriptions.keys())


# 全局单例
ws_manager = WebSocketManager()
