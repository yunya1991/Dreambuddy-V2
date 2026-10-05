"""
DreamOS — 交易所能力提供者 (ExchangeCapabilityProvider)

将交易所/账户的交易能力声明为 CapabilitySpec，注册到 NodeRegistry，
供策略匹配引擎 (CapabilityMatcher) 查询。

能力维度:
    - trading.spot / trading.futures / trading.margin / trading.options
    - trading.leverage (properties: max, supported_intervals)
    - trading.order_types.{market,limit,stop,trailing_stop,...}
    - data.ohlcv.{1m,5m,15m,1h,4h,1d}
    - data.orderbook / data.trades
    - execution.rate_limit (properties: requests_per_min, orders_per_min)

设计原则:
    - 仅声明能力，不实现交易逻辑（交易逻辑在 auto_trader.py / okx_client.py / hyperliquid_adapter.py）
    - 能力属性来自交易所公开文档，运行时可通过 update_node_capability_status 更新可用性
    - 不含 API Key 等敏感信息
"""

from __future__ import annotations

from typing import Dict, List, Optional, TYPE_CHECKING

from dreamos.shared.capability import (
    CapabilitySpec, ProviderType, CapabilityStatus,
)

if TYPE_CHECKING:
    from dreamos.registry.node_registry import NodeRegistry


# ============================================================
# 交易所能力配置
# ============================================================

_EXCHANGE_CAPABILITY_CONFIGS: Dict[str, Dict] = {
    "OKX": {
        "trading.spot": {"supported": True},
        "trading.futures": {"supported": True, "settlement": "usdt_swap"},
        "trading.margin": {"supported": True},
        "trading.leverage": {
            "max": 125,
            "supported_intervals": [1, 2, 3, 5, 10, 20, 50, 100, 125],
        },
        "trading.order_types.market": {},
        "trading.order_types.limit": {},
        "trading.order_types.stop": {},
        "trading.order_types.trailing_stop": {},
        "trading.order_types.post_only": {},
        "data.ohlcv.1m": {},
        "data.ohlcv.5m": {},
        "data.ohlcv.15m": {},
        "data.ohlcv.1h": {},
        "data.ohlcv.4h": {},
        "data.ohlcv.1d": {},
        "data.orderbook": {},
        "data.trades": {},
        "execution.rate_limit": {"requests_per_min": 60, "orders_per_min": 100},
    },
    "Hyperliquid": {
        "trading.spot": {"supported": True},
        "trading.futures": {"supported": True, "settlement": "usd_perp"},
        "trading.leverage": {
            "max": 50,
            "supported_intervals": [1, 2, 3, 5, 10, 20, 50],
        },
        "trading.order_types.market": {},
        "trading.order_types.limit": {},
        "trading.order_types.stop": {},
        "trading.order_types.trailing_stop": {},
        "data.ohlcv.1m": {},
        "data.ohlcv.5m": {},
        "data.ohlcv.15m": {},
        "data.ohlcv.1h": {},
        "data.ohlcv.4h": {},
        "data.ohlcv.1d": {},
        "data.orderbook": {},
        "data.trades": {},
        "execution.rate_limit": {"requests_per_min": 120, "orders_per_min": 50},
    },
}

_CAPABILITY_META: Dict[str, Dict[str, str]] = {
    "trading.spot": {"name": "现货交易", "category": "trading"},
    "trading.futures": {"name": "合约交易", "category": "trading"},
    "trading.margin": {"name": "杠杆交易", "category": "trading"},
    "trading.options": {"name": "期权交易", "category": "trading"},
    "trading.leverage": {"name": "杠杆能力", "category": "trading"},
    "trading.order_types.market": {"name": "市价单", "category": "trading"},
    "trading.order_types.limit": {"name": "限价单", "category": "trading"},
    "trading.order_types.stop": {"name": "止损单", "category": "trading"},
    "trading.order_types.trailing_stop": {"name": "移动止损", "category": "trading"},
    "trading.order_types.post_only": {"name": "只挂单", "category": "trading"},
    "data.ohlcv.1m": {"name": "1分钟K线", "category": "data"},
    "data.ohlcv.5m": {"name": "5分钟K线", "category": "data"},
    "data.ohlcv.15m": {"name": "15分钟K线", "category": "data"},
    "data.ohlcv.1h": {"name": "1小时K线", "category": "data"},
    "data.ohlcv.4h": {"name": "4小时K线", "category": "data"},
    "data.ohlcv.1d": {"name": "日线K线", "category": "data"},
    "data.orderbook": {"name": "订单簿", "category": "data"},
    "data.trades": {"name": "成交记录", "category": "data"},
    "execution.rate_limit": {"name": "速率限制", "category": "execution"},
}


# ============================================================
# 交易所能力提供者
# ============================================================

class ExchangeCapabilityProvider:
    """交易所能力提供者 — 将交易所能力注册为 CapabilitySpec

    用法:
        provider = ExchangeCapabilityProvider("OKX")
        caps = provider.get_capabilities()

        # 注册到 NodeRegistry（内部创建轻量节点承载能力）
        provider.register_to(registry)
    """

    def __init__(self, exchange_id: str, config: Optional[Dict] = None):
        self.exchange_id = exchange_id
        self.config = config or _EXCHANGE_CAPABILITY_CONFIGS.get(exchange_id, {})

    def get_capabilities(self) -> List[CapabilitySpec]:
        """生成该交易所的 CapabilitySpec 列表"""
        caps: List[CapabilitySpec] = []
        for cap_id, props in self.config.items():
            meta = _CAPABILITY_META.get(cap_id, {})
            category = meta.get("category", cap_id.split(".")[0])
            name = meta.get("name", cap_id)
            caps.append(CapabilitySpec(
                capability_id=cap_id,
                category=category,
                name=name,
                provider_id=self.exchange_id,
                provider_type=ProviderType.EXCHANGE,
                properties=dict(props),
                status=CapabilityStatus.AVAILABLE,
                tags=[self.exchange_id],
            ))
        return caps

    def register_to(self, registry: "NodeRegistry") -> str:
        """将交易所能力注册到 NodeRegistry

        内部创建一个轻量 ExchangeNode 承载能力，返回注册的 node_id。

        Returns:
            注册的节点 ID（= exchange_id）
        """
        from dreamos.registry.base import BaseNode
        from dreamos.shared.state import NodeResult, State

        caps = self.get_capabilities()

        class _ExchangeNode(BaseNode):
            node_id = self.exchange_id
            name = f"{self.exchange_id} 交易所能力"
            chain = "T"
            tags = ["exchange", self.exchange_id]
            capabilities = caps

            def execute_core(self, state: State) -> NodeResult:
                return NodeResult(node_id=self.node_id, confidence=1.0)

        node = _ExchangeNode()
        # 若已存在则先注销，确保能力可更新
        if registry.exists(self.exchange_id):
            registry.unregister(self.exchange_id)
        registry.register(node)
        return self.exchange_id
