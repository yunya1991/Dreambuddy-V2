"""
Dream OS 交易能力域 — 执行层

封装实盘交易相关组件:
    - AutoTrader: 自动化交易主类
    - ExchangeClient: 交易所接口封装（未来）
"""

from __future__ import annotations

# 延迟导入避免循环依赖
def _get_auto_trader():
    from .auto_trader import AutoTrader
    return AutoTrader
