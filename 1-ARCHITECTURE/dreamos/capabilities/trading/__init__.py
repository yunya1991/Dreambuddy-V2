"""
Dream OS — 交易能力域 (Trading Capability Domain)

交易能力域是 Dream OS 的旗舰内建能力域，聚焦"通过交易赚钱"这一核心意图。

设计原则:
    - 纯粹交易: 节点只实现交易逻辑，不干预编排调度
    - 内核无关: 不依赖内核具体实现，只通过标准接口接入
    - 独立演进: 交易策略、参数、阈值可独立迭代，不影响 OS 内核

用法:
    from dreamos.capabilities.trading import TradingCapability

    cap = TradingCapability()
    cap.register(registry)  # 将交易节点注册到内核注册表

    # 或通过 CapabilityRegistry 自动发现
    from dreamos.core.capability import CapabilityRegistry
    registry = CapabilityRegistry()
    registry.discover_and_register("dreamos.capabilities")
"""

from __future__ import annotations

from typing import Dict, List, Optional, Any

from dreamos.registry import NodeRegistry


# 交易能力域元数据
CAPABILITY_ID = "trading"
CAPABILITY_NAME = "交易能力域"
CAPABILITY_DESCRIPTION = "通过交易赚钱的完整能力实现，包含矛盾分析、技术扫描、策略制定、风控门禁、执行离场等22个交易节点"
CAPABILITY_VERSION = "2.2.0"

# 交易能力域支持的意图类型
SUPPORTED_INTENTS = [
    "TREND_FOLLOWING",      # 趋势跟随
    "MEAN_REVERSION",       # 均值回归
    "BREAKOUT",             # 突破交易
    "MOMENTUM",             # 动量交易
    "ARBITRAGE",            # 套利
    "SCALPING",             # 剥头皮
    "SWING_TRADING",        # 波段交易
    "POSITION_TRADING",     # 仓位交易
    "MARKET_ANALYSIS",      # 市场分析
    "RISK_MANAGEMENT",      # 风险管理
    "PORTFOLIO_REBALANCE",  # 组合再平衡
]

# 交易能力域标签（用于意图匹配）
CAPABILITY_TAGS = [
    "trading", "trade", "交易", "做多", "做空", "买入", "卖出",
    "btc", "eth", "sol", "crypto", "合约", "杠杆", "止损", "止盈",
    "趋势", "突破", "反转", "动量", "波动率", "技术指标",
]


class TradingCapability:
    """交易能力域 — Dream OS 旗舰内建能力

    职责:
        1. 封装交易节点的注册与发现
        2. 声明支持的意图类型和匹配标签
        3. 提供交易专用配置（阈值、链路、策略参数）
        4. 作为内核与交易节点之间的标准接口
    """

    capability_id: str = CAPABILITY_ID
    name: str = CAPABILITY_NAME
    description: str = CAPABILITY_DESCRIPTION
    version: str = CAPABILITY_VERSION
    supported_intents: List[str] = SUPPORTED_INTENTS
    tags: List[str] = CAPABILITY_TAGS

    def __init__(self):
        self._nodes_registered = False
        self._config: Dict[str, Any] = {}

    # ── 节点注册 ──────────────────────────────────

    def register(self, registry: Optional[NodeRegistry] = None) -> int:
        """将交易节点注册到内核注册表

        Args:
            registry: 目标注册表，None 使用默认注册表

        Returns:
            注册的节点数量
        """
        from dreamos.capabilities.trading.nodes import register_all
        count = register_all(registry=registry)
        self._nodes_registered = True
        return count

    def is_registered(self) -> bool:
        """检查节点是否已注册"""
        return self._nodes_registered

    # ── 意图匹配 ──────────────────────────────────

    def can_handle(self, intent_type: str, keywords: Optional[List[str]] = None) -> float:
        """判断本能力域能否处理给定意图

        Returns:
            匹配置信度 (0.0 ~ 1.0)
        """
        if intent_type in self.supported_intents:
            return 1.0

        # 关键词匹配
        if keywords:
            matched = sum(1 for kw in keywords if any(tag in kw.lower() for tag in self.tags))
            if matched > 0:
                return min(0.5 + matched * 0.1, 0.9)

        return 0.0

    # ── 配置管理 ──────────────────────────────────

    def get_default_config(self) -> Dict[str, Any]:
        """获取交易能力域默认配置"""
        return {
            "confidence_threshold_long": 0.62,
            "confidence_threshold_short": 0.62,
            "min_trade_interval_minutes": 30,
            "default_leverage": 3,
            "max_leverage": 5,
            "risk_per_trade": 10.0,
            "stop_loss_atr_multiplier": 1.0,
            "take_profit_atr_multiplier": 2.0,
            "default_chain": ["C1", "C2", "C3", "A1", "A2", "A3", "A4", "A5", "A9"],
            "scenario_classification": True,
            "a7_gate_enabled": True,
            "evolution_enabled": True,
        }

    def configure(self, config: Dict[str, Any]) -> None:
        """更新能力域配置"""
        self._config.update(config)

    def get_config(self) -> Dict[str, Any]:
        """获取当前配置（合并默认值和用户配置）"""
        default = self.get_default_config()
        default.update(self._config)
        return default

    # ── 元信息 ────────────────────────────────────

    def info(self) -> Dict[str, Any]:
        """返回能力域信息"""
        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "supported_intents": self.supported_intents,
            "tags": self.tags,
            "nodes_registered": self._nodes_registered,
            "config": self.get_config(),
        }

    def __repr__(self) -> str:
        return (f"<TradingCapability id={self.capability_id} "
                f"version={self.version} "
                f"registered={self._nodes_registered}>")


# 便捷函数
def get_trading_capability() -> TradingCapability:
    """获取交易能力域单例"""
    return TradingCapability()


# ── Phase 1: A系列选币层导出 ──────────────────────
from dreamos.capabilities.trading.coin_selector import CoinSelector, CoinSelectorNode

__all__ = [
    "TradingCapability",
    "get_trading_capability",
    "CoinSelector",
    "CoinSelectorNode",
]
