"""
Dreambuddy OS — 共享工具函数
"""

from __future__ import annotations

import time
import json
import hashlib
from typing import Any, Callable, Dict, List, Optional, TypeVar, T
from datetime import datetime, timezone


T = TypeVar("T")


# ============================================================
# 计时器
# ============================================================

class Timer:
    """简单的计时器，支持 with 语法"""

    def __init__(self, name: str = ""):
        self.name = name
        self.start_ts: float = 0.0
        self.end_ts: float = 0.0

    def __enter__(self) -> "Timer":
        self.start_ts = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.end_ts = time.perf_counter()

    @property
    def elapsed_ms(self) -> float:
        """耗时（毫秒）"""
        if self.end_ts == 0:
            return (time.perf_counter() - self.start_ts) * 1000
        return (self.end_ts - self.start_ts) * 1000

    @property
    def elapsed_s(self) -> float:
        """耗时（秒）"""
        return self.elapsed_ms / 1000


def timed(fn: Callable) -> Callable:
    """函数计时装饰器（结果会附加 _elapsed_ms）"""
    def wrapper(*args, **kwargs):
        t = Timer(fn.__name__)
        with t:
            result = fn(*args, **kwargs)
        if isinstance(result, dict):
            result["_elapsed_ms"] = t.elapsed_ms
        return result
    return wrapper


# ============================================================
# ID 生成
# ============================================================

def gen_cycle_id(prefix: str = "cycle") -> str:
    """生成 cycle ID"""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    short_hash = hashlib.md5(str(time.time()).encode()).hexdigest()[:6]
    return f"{prefix}_{ts}_{short_hash}"


def gen_session_id() -> str:
    """生成 session ID"""
    return gen_cycle_id("session")


# ============================================================
# 序列化辅助
# ============================================================

def safe_json(obj: Any, default: str = "") -> str:
    """安全 JSON 序列化（处理不可序列化对象）"""
    try:
        return json.dumps(obj, ensure_ascii=False, default=str, indent=2)
    except Exception:
        return default


def safe_get(data: Optional[Dict], path: str, default: Any = None) -> Any:
    """安全嵌套取值
    示例: safe_get({"a": {"b": 1}}, "a.b") -> 1
    """
    if not data or not path:
        return default
    cur: Any = data
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


# ============================================================
# 重试
# ============================================================

def retry(fn: Callable[..., T], attempts: int = 3,
          backoff: float = 1.0, exceptions: tuple = (Exception,)) -> T:
    """简单同步重试

    Args:
        fn: 要重试的函数（无参数）
        attempts: 最大尝试次数
        backoff: 退避因子（秒），每次翻倍
        exceptions: 要重试的异常类型

    Returns:
        函数返回值
    """
    last_exc: Optional[Exception] = None
    wait = backoff
    for i in range(attempts):
        try:
            return fn()
        except exceptions as e:
            last_exc = e
            if i < attempts - 1:
                time.sleep(wait)
                wait *= 2
    if last_exc:
        raise last_exc
    raise RuntimeError("retry: unreachable")


# ============================================================
# 列表辅助
# ============================================================

def chunk(lst: List[T], size: int) -> List[List[T]]:
    """分块"""
    if size <= 0:
        return [lst]
    return [lst[i:i + size] for i in range(0, len(lst), size)]


def dedupe(lst: List[T], key: Optional[Callable[[T], Any]] = None) -> List[T]:
    """去重（保持顺序）"""
    seen = set()
    result = []
    for item in lst:
        k = key(item) if key else item
        if k not in seen:
            seen.add(k)
            result.append(item)
    return result
