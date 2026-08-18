"""
Dream OS — 能力域根包

所有业务能力域的容器。Dream OS 内核通过 CapabilityRegistry 发现和加载此包下的能力域。

当前能力域:
    - trading: 交易能力域（旗舰内建能力）

未来扩展:
    - knowledge: 知识管理能力域
    - data_analysis: 数据分析能力域
    - content_generation: 内容生成能力域

用法:
    from dreamos.core.capability import CapabilityRegistry
    registry = CapabilityRegistry()
    registry.discover_and_register("dreamos.capabilities")
"""

from __future__ import annotations

# 延迟导入，避免循环依赖
def _get_trading_capability():
    from .trading import TradingCapability
    return TradingCapability()
