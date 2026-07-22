"""
Dream OS 交易能力域 — 回测引擎

封装回测相关组件:
    - engine: 回测引擎主类
"""

from __future__ import annotations

# 延迟导入避免循环依赖
def _get_backtest_engine():
    from .engine import DreamOSBacktester
    return DreamOSBacktester
