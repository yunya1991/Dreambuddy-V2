"""
L3 自修复: 断路器与降级
=============================
任何外部依赖连续失败 3 次自动熔断 30 分钟。
LLM 降级链（DeepSeek→Qwen→NoOp）扩展到所有外部依赖。

用法:
    breaker = CircuitBreaker(name="okx_api", threshold=3, timeout_s=1800)
    with breaker:
        result = call_external_api()
    # 连续 3 次失败后自动熔断，30 分钟内直接返回 fallback
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TypeVar, Generic

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "closed"      # 正常，允许请求通过
    OPEN = "open"           # 熔断，拒绝请求
    HALF_OPEN = "half_open"  # 半开，允许有限请求试探


@dataclass
class CircuitStats:
    """断路器统计"""
    total_calls: int = 0
    success_count: int = 0
    failure_count: int = 0
    consecutive_failures: int = 0
    last_failure_ts: Optional[str] = None
    last_success_ts: Optional[str] = None
    opened_at: Optional[str] = None
    open_count: int = 0  # 累计熔断次数

    @property
    def failure_rate(self) -> float:
        return self.failure_count / self.total_calls if self.total_calls > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_calls": self.total_calls,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "consecutive_failures": self.consecutive_failures,
            "failure_rate": round(self.failure_rate, 4),
            "last_failure_ts": self.last_failure_ts,
            "last_success_ts": self.last_success_ts,
            "opened_at": self.opened_at,
            "open_count": self.open_count,
        }


class CircuitBreakerOpen(Exception):
    """断路器打开时抛出"""
    def __init__(self, name: str, opened_at: str, remaining_s: float):
        self.name = name
        self.opened_at = opened_at
        self.remaining_s = remaining_s
        super().__init__(
            f"CircuitBreaker '{name}' is OPEN since {opened_at}, "
            f"remaining cooldown: {remaining_s:.0f}s"
        )


class CircuitBreaker:
    """断路器

    状态转换：
        CLOSED → (连续 N 次失败) → OPEN → (超时后) → HALF_OPEN →
            (成功) → CLOSED
            (失败) → OPEN (重置超时)

    用法:
        breaker = CircuitBreaker(name="okx_api", threshold=3, timeout_s=1800)
        try:
            with breaker:
                result = call_api()
        except CircuitBreakerOpen:
            result = fallback()
    """

    def __init__(
        self,
        name: str,
        threshold: int = 3,
        timeout_s: int = 1800,  # 30 分钟
        half_open_max_calls: int = 1,
    ):
        self.name = name
        self.threshold = threshold
        self.timeout_s = timeout_s
        self.half_open_max_calls = half_open_max_calls
        self._state = CircuitState.CLOSED
        self._stats = CircuitStats()
        self._lock = threading.Lock()
        self._half_open_calls = 0
        self._fallback_fn: Optional[Callable] = None

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._maybe_transition_to_half_open()
            return self._state

    @property
    def stats(self) -> CircuitStats:
        with self._lock:
            return self._stats

    def set_fallback(self, fn: Callable) -> None:
        """设置降级函数"""
        self._fallback_fn = fn

    # ------------------------------------------------------------------
    # 上下文管理器
    # ------------------------------------------------------------------
    def __enter__(self):
        """进入时检查是否允许请求"""
        with self._lock:
            self._maybe_transition_to_half_open()

            if self._state == CircuitState.OPEN:
                remaining = self._remaining_cooldown()
                raise CircuitBreakerOpen(self.name, self._stats.opened_at or "", remaining)

            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    remaining = self._remaining_cooldown()
                    raise CircuitBreakerOpen(self.name, self._stats.opened_at or "", remaining)
                self._half_open_calls += 1

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出时记录成功/失败"""
        with self._lock:
            if exc_type is not None:
                self._on_failure()
            else:
                self._on_success()
        return False  # 不吞异常

    # ------------------------------------------------------------------
    # 带降级的调用
    # ------------------------------------------------------------------
    def call(self, fn: Callable[..., T], *args, **kwargs) -> T:
        """调用函数，断路器打开时返回 fallback

        Args:
            fn: 要调用的函数
            *args, **kwargs: 函数参数

        Returns:
            fn 的返回值，或 fallback 的返回值

        Raises:
            CircuitBreakerOpen: 断路器打开且无 fallback
        """
        try:
            with self:
                return fn(*args, **kwargs)
        except CircuitBreakerOpen:
            if self._fallback_fn is not None:
                logger.info(f"[CircuitBreaker:{self.name}] 使用降级")
                return self._fallback_fn(*args, **kwargs)
            raise
        except Exception:
            if self._fallback_fn is not None:
                logger.warning(f"[CircuitBreaker:{self.name}] 调用失败，使用降级")
                return self._fallback_fn(*args, **kwargs)
            raise

    # ------------------------------------------------------------------
    # 内部状态转换
    # ------------------------------------------------------------------
    def _on_success(self) -> None:
        """调用成功"""
        self._stats.total_calls += 1
        self._stats.success_count += 1
        self._stats.consecutive_failures = 0
        self._stats.last_success_ts = datetime.utcnow().isoformat() + "Z"

        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED
            self._half_open_calls = 0
            logger.info(f"[CircuitBreaker:{self.name}] HALF_OPEN → CLOSED (恢复)")

    def _on_failure(self) -> None:
        """调用失败"""
        self._stats.total_calls += 1
        self._stats.failure_count += 1
        self._stats.consecutive_failures += 1
        self._stats.last_failure_ts = datetime.utcnow().isoformat() + "Z"

        if self._state == CircuitState.HALF_OPEN:
            # 半开时失败 → 重新打开
            self._state = CircuitState.OPEN
            self._stats.opened_at = datetime.utcnow().isoformat() + "Z"
            self._stats.open_count += 1
            self._half_open_calls = 0
            logger.warning(f"[CircuitBreaker:{self.name}] HALF_OPEN → OPEN (试探失败)")

        elif self._state == CircuitState.CLOSED:
            if self._stats.consecutive_failures >= self.threshold:
                self._state = CircuitState.OPEN
                self._stats.opened_at = datetime.utcnow().isoformat() + "Z"
                self._stats.open_count += 1
                logger.warning(
                    f"[CircuitBreaker:{self.name}] CLOSED → OPEN "
                    f"(连续 {self._stats.consecutive_failures} 次失败)"
                )

    def _maybe_transition_to_half_open(self) -> None:
        """检查是否应该从 OPEN 转为 HALF_OPEN"""
        if self._state != CircuitState.OPEN:
            return
        if self._stats.opened_at is None:
            return
        opened = datetime.fromisoformat(self._stats.opened_at.replace("Z", "+00:00")).replace(tzinfo=None)
        elapsed = (datetime.utcnow() - opened).total_seconds()
        if elapsed >= self.timeout_s:
            self._state = CircuitState.HALF_OPEN
            self._half_open_calls = 0
            logger.info(f"[CircuitBreaker:{self.name}] OPEN → HALF_OPEN (冷却完成)")

    def _remaining_cooldown(self) -> float:
        """剩余冷却时间（秒）"""
        if self._stats.opened_at is None:
            return 0.0
        opened = datetime.fromisoformat(self._stats.opened_at.replace("Z", "+00:00")).replace(tzinfo=None)
        elapsed = (datetime.utcnow() - opened).total_seconds()
        return max(0.0, self.timeout_s - elapsed)

    # ------------------------------------------------------------------
    # 管理接口
    # ------------------------------------------------------------------
    def reset(self) -> None:
        """手动重置断路器"""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._stats = CircuitStats()
            self._half_open_calls = 0
            logger.info(f"[CircuitBreaker:{self.name}] 手动重置")

    def to_dict(self) -> Dict[str, Any]:
        """状态快照"""
        with self._lock:
            self._maybe_transition_to_half_open()
            return {
                "name": self.name,
                "state": self._state.value,
                "threshold": self.threshold,
                "timeout_s": self.timeout_s,
                "stats": self._stats.to_dict(),
                "remaining_cooldown_s": self._remaining_cooldown(),
            }


class CircuitBreakerRegistry:
    """断路器注册表 — 管理多个外部依赖的断路器

    用法:
        registry = CircuitBreakerRegistry()
        registry.register("okx_api", threshold=3, timeout_s=1800)
        registry.register("deepseek_llm", threshold=3, timeout_s=1800)
        registry.register("qwen_llm", threshold=3, timeout_s=1800)

        # 使用
        result = registry.call("okx_api", fetch_ticker, "BTC-USDT")
    """

    def __init__(self):
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()

    def register(
        self,
        name: str,
        threshold: int = 3,
        timeout_s: int = 1800,
        fallback_fn: Optional[Callable] = None,
    ) -> CircuitBreaker:
        """注册一个断路器"""
        with self._lock:
            if name in self._breakers:
                return self._breakers[name]
            breaker = CircuitBreaker(name=name, threshold=threshold, timeout_s=timeout_s)
            if fallback_fn is not None:
                breaker.set_fallback(fallback_fn)
            self._breakers[name] = breaker
            return breaker

    def get(self, name: str) -> Optional[CircuitBreaker]:
        return self._breakers.get(name)

    def call(self, name: str, fn: Callable[..., T], *args, **kwargs) -> T:
        """通过指定断路器调用函数"""
        breaker = self._breakers.get(name)
        if breaker is None:
            # 无断路器直接调用
            return fn(*args, **kwargs)
        return breaker.call(fn, *args, **kwargs)

    def status(self) -> Dict[str, Any]:
        """所有断路器状态"""
        return {name: b.to_dict() for name, b in self._breakers.items()}

    def reset_all(self) -> None:
        """重置所有断路器"""
        for b in self._breakers.values():
            b.reset()


# ============================================================================
# LLM 降级链（DeepSeek → Qwen → NoOp）
# ============================================================================

class LLMDegradationChain:
    """LLM 降级链 — 依次尝试多个 LLM provider

    用法:
        chain = LLMDegradationChain()
        chain.add_provider("deepseek", call_deepseek, threshold=3)
        chain.add_provider("qwen", call_qwen, threshold=3)
        chain.add_provider("noop", lambda **kw: {"content": ""}, threshold=999)

        result = chain.call(prompt="分析比特币", max_tokens=500)
    """

    def __init__(self):
        self._registry = CircuitBreakerRegistry()
        self._providers: List[Dict[str, Any]] = []

    def add_provider(
        self,
        name: str,
        fn: Callable,
        threshold: int = 3,
        timeout_s: int = 1800,
        is_fallback: bool = False,
    ) -> None:
        """添加 LLM provider"""
        self._providers.append({
            "name": name,
            "fn": fn,
            "threshold": threshold,
            "timeout_s": timeout_s,
            "is_fallback": is_fallback,
        })
        # 为每个 provider 注册断路器
        fallback = self._providers[-2]["fn"] if len(self._providers) > 1 else None
        self._registry.register(name, threshold=threshold, timeout_s=timeout_s,
                                fallback_fn=fallback)

    def call(self, **kwargs) -> Dict[str, Any]:
        """按优先级依次尝试 LLM provider

        Returns:
            第一个成功的 provider 返回结果

        Raises:
            RuntimeError: 所有 provider 都失败
        """
        for provider in self._providers:
            name = provider["name"]
            fn = provider["fn"]
            try:
                result = self._registry.call(name, fn, **kwargs)
                if result is not None:
                    return {**result, "_provider": name} if isinstance(result, dict) else {"content": result, "_provider": name}
            except Exception as e:
                logger.warning(f"[LLMChain] provider={name} 失败: {e}")
                continue

        # 所有 provider 失败
        return {"content": "", "_provider": "noop", "error": "all providers failed"}

    def status(self) -> Dict[str, Any]:
        return self._registry.status()
