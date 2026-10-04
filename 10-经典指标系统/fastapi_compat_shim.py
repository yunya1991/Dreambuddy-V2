"""FastAPI 兼容补丁：恢复 FastAPI 0.103+ 移除的 add_event_handler 方法。

Freqtrade 2025.11.2 的 webserver.py 仍在使用：
    app.add_event_handler(event_type="startup", func=self._api_startup_event)
    app.add_event_handler(event_type="shutdown", func=self._api_shutdown_event)

但 FastAPI 0.103 起，该方法已被移除（推荐改用 lifespan 参数）。
本 shim 通过拦截 FastAPI.__init__ 注入默认 lifespan context manager，
并把 add_event_handler 重新挂回去，让 Freqtrade 无需改动即可工作。

用法：
    import fastapi_compat_shim; fastapi_compat_shim.apply()
    # 然后 import freqtrade 相关模块
"""
from __future__ import annotations
from contextlib import asynccontextmanager
from typing import Callable, Awaitable


def apply() -> None:
    import fastapi

    if hasattr(fastapi.FastAPI, "add_event_handler"):
        # 已有 add_event_handler，无需 patch（旧版 FastAPI）
        return

    _orig_init = fastapi.FastAPI.__init__

    def _patched_init(self, *args, **kwargs):
        startup_handlers: list[Callable[[object], Awaitable[None]]] = []
        shutdown_handlers: list[Callable[[object], Awaitable[None]]] = []

        @asynccontextmanager
        async def default_lifespan(app):
            for h in startup_handlers:
                await h()
            yield
            for h in shutdown_handlers:
                await h()

        # 在实例上挂载 handler 列表，供 add_event_handler 写入
        self._ft_startup_handlers = startup_handlers
        self._ft_shutdown_handlers = shutdown_handlers

        # 如果调用方未显式传 lifespan，注入我们的
        if "lifespan" not in kwargs:
            kwargs["lifespan"] = default_lifespan

        _orig_init(self, *args, **kwargs)

    def add_event_handler(self, event_type: str, func: Callable[[object], Awaitable[None]]) -> None:
        if event_type == "startup":
            self._ft_startup_handlers.append(func)
        elif event_type == "shutdown":
            self._ft_shutdown_handlers.append(func)
        else:
            raise ValueError(
                f"Unsupported event_type {event_type!r}; only 'startup' and 'shutdown' are supported."
            )

    fastapi.FastAPI.__init__ = _patched_init  # type: ignore[assignment]
    fastapi.FastAPI.add_event_handler = add_event_handler  # type: ignore[assignment]


if __name__ == "__main__":
    apply()
    print("[fastapi_compat_shim] FastAPI add_event_handler restored.")
