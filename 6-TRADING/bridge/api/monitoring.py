#!/usr/bin/env python3
"""
请求日志和监控中间件
====================
记录所有 API 请求，提供性能监控和统计
"""

import time
import logging
import functools
from datetime import datetime, timedelta
from collections import defaultdict, deque
from threading import Lock
from flask import request, g, jsonify
from typing import Dict, List, Callable
import json

logger = logging.getLogger(__name__)


class RequestLogger:
    """请求日志记录器"""
    
    _instance = None
    _lock = Lock()
    
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
        
        # 请求记录（滑动窗口）
        self._requests: deque = deque(maxlen=1000)
        
        # 统计计数
        self._stats: Dict[str, Dict] = defaultdict(lambda: {
            'count': 0,
            'errors': 0,
            'total_time': 0.0,
            'min_time': float('inf'),
            'max_time': 0.0
        })
        
        # 端点列表
        self._endpoints: set = set()
        
        # 时间窗口（用于速率限制）
        self._window_start = datetime.now()
        self._window_requests = 0
        
        logger.info("✅ RequestLogger initialized")
    
    def log_request(
        self,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        error: str = None
    ):
        """记录请求"""
        timestamp = datetime.now()
        
        # 记录详情
        record = {
            'timestamp': timestamp.isoformat(),
            'method': method,
            'path': path,
            'status': status_code,
            'duration_ms': duration_ms,
            'error': error
        }
        self._requests.append(record)
        
        # 统计
        endpoint = f"{method} {path}"
        self._endpoints.add(endpoint)
        
        stats = self._stats[endpoint]
        stats['count'] += 1
        stats['total_time'] += duration_ms
        stats['min_time'] = min(stats['min_time'], duration_ms)
        stats['max_time'] = max(stats['max_time'], duration_ms)
        
        if status_code >= 400 or error:
            stats['errors'] += 1
        
        # 速率限制窗口
        self._window_requests += 1
    
    def get_stats(self, hours: int = 1) -> Dict:
        """获取统计信息"""
        cutoff = datetime.now() - timedelta(hours=hours)
        
        # 过滤时间窗口内的请求
        recent_requests = [
            r for r in self._requests
            if datetime.fromisoformat(r['timestamp']) >= cutoff
        ]
        
        if not recent_requests:
            return {
                "requests_in_window": 0,
                "requests_per_minute": 0,
                "error_rate": 0,
                "avg_response_time_ms": 0,
                "endpoints": {}
            }
        
        total = len(recent_requests)
        errors = sum(1 for r in recent_requests if r['status'] >= 400)
        total_duration = sum(r['duration_ms'] for r in recent_requests)
        
        # 按端点统计
        endpoint_stats = {}
        for endpoint, stats in self._stats.items():
            if stats['count'] > 0:
                endpoint_stats[endpoint] = {
                    'requests': stats['count'],
                    'errors': stats['errors'],
                    'avg_ms': round(stats['total_time'] / stats['count'], 2),
                    'min_ms': round(stats['min_time'], 2),
                    'max_ms': round(stats['max_time'], 2),
                    'error_rate': round(stats['errors'] / stats['count'] * 100, 2)
                }
        
        # 计算速率
        window_minutes = hours * 60
        requests_per_minute = round(total / window_minutes, 2) if window_minutes > 0 else 0
        
        return {
            "requests_in_window": total,
            "requests_per_minute": requests_per_minute,
            "total_errors": errors,
            "error_rate": round(errors / total * 100, 2) if total > 0 else 0,
            "avg_response_time_ms": round(total_duration / total, 2),
            "endpoints": endpoint_stats,
            "all_endpoints": list(self._endpoints)
        }
    
    def get_recent(self, limit: int = 50) -> List[Dict]:
        """获取最近的请求"""
        return list(self._requests)[-limit:]
    
    def reset(self):
        """重置统计"""
        self._requests.clear()
        self._stats.clear()
        self._endpoints.clear()
        self._window_requests = 0
        self._window_start = datetime.now()
        logger.info("[Logger] Stats reset")


# 全局实例
request_logger = RequestLogger()


def request_logging_middleware(app):
    """请求日志中间件"""
    
    @app.before_request
    def before_request():
        """请求开始"""
        g.start_time = time.time()
        g.request_id = f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{id(request)}"
        
        logger.debug(f"[{g.request_id}] {request.method} {request.path} started")
    
    @app.after_request
    def after_request(response):
        """请求结束"""
        # 计算耗时
        duration_ms = (time.time() - g.get('start_time', time.time())) * 1000
        
        # 记录
        request_logger.log_request(
            method=request.method,
            path=request.path,
            status_code=response.status_code,
            duration_ms=duration_ms
        )
        
        # 添加响应头
        response.headers['X-Request-ID'] = g.get('request_id', '')
        response.headers['X-Response-Time'] = f"{duration_ms:.2f}ms"
        
        logger.debug(
            f"[{g.get('request_id')}] {request.method} {request.path} "
            f"-> {response.status_code} ({duration_ms:.2f}ms)"
        )
        
        return response
    
    return app


def validate_json(*required_fields):
    """JSON 验证装饰器"""
    def decorator(f: Callable) -> Callable:
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            from flask import request
            
            if not request.is_json:
                return jsonify({
                    "success": False,
                    "error": "Content-Type must be application/json"
                }), 400
            
            data = request.get_json()
            if not data:
                return jsonify({
                    "success": False,
                    "error": "Request body is empty"
                }), 400
            
            missing = [f for f in required_fields if f not in data]
            if missing:
                return jsonify({
                    "success": False,
                    "error": f"Missing required fields: {missing}"
                }), 400
            
            return f(*args, **kwargs)
        return wrapper
    return decorator


def validate_params(**param_schemas):
    """参数验证装饰器"""
    def decorator(f: Callable) -> Callable:
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            from flask import request
            
            errors = []
            
            for param_name, schema in param_schemas.items():
                value = request.args.get(param_name) or request.form.get(param_name) or kwargs.get(param_name)
                
                if schema.get('required') and value is None:
                    errors.append(f"{param_name} is required")
                    continue
                
                if value is not None:
                    param_type = schema.get('type')
                    if param_type == 'int':
                        try:
                            value = int(value)
                        except ValueError:
                            errors.append(f"{param_name} must be an integer")
                    elif param_type == 'float':
                        try:
                            value = float(value)
                        except ValueError:
                            errors.append(f"{param_name} must be a number")
                    elif param_type == 'str':
                        value = str(value)
                    
                    # 枚举验证
                    if 'enum' in schema and value not in schema['enum']:
                        errors.append(
                            f"{param_name} must be one of: {schema['enum']}"
                        )
            
            if errors:
                return jsonify({
                    "success": False,
                    "errors": errors
                }), 400
            
            return f(*args, **kwargs)
        return wrapper
    return decorator


class APIError(Exception):
    """API 异常"""
    
    def __init__(self, message: str, status_code: int = 400, details: Dict = None):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)
    
    def to_dict(self) -> Dict:
        return {
            "success": False,
            "error": self.message,
            "status_code": self.status_code,
            **self.details
        }


def register_error_handlers(app):
    """注册错误处理器"""
    
    @app.errorhandler(APIError)
    def handle_api_error(error: APIError):
        return jsonify(error.to_dict()), error.status_code
    
    @app.errorhandler(400)
    def handle_bad_request(error):
        return jsonify({
            "success": False,
            "error": "Bad Request",
            "message": str(error.description) if hasattr(error, 'description') else "Invalid request"
        }), 400
    
    @app.errorhandler(401)
    def handle_unauthorized(error):
        return jsonify({
            "success": False,
            "error": "Unauthorized",
            "message": "Authentication required"
        }), 401
    
    @app.errorhandler(403)
    def handle_forbidden(error):
        return jsonify({
            "success": False,
            "error": "Forbidden",
            "message": "Access denied"
        }), 403
    
    @app.errorhandler(404)
    def handle_not_found(error):
        return jsonify({
            "success": False,
            "error": "Not Found",
            "message": f"Endpoint {request.path} not found"
        }), 404
    
    @app.errorhandler(429)
    def handle_rate_limit(error):
        return jsonify({
            "success": False,
            "error": "Rate Limit Exceeded",
            "message": "Too many requests, please slow down"
        }), 429
    
    @app.errorhandler(500)
    def handle_internal_error(error):
        logger.error(f"Internal error: {error}")
        return jsonify({
            "success": False,
            "error": "Internal Server Error",
            "message": "An unexpected error occurred"
        }), 500
