# 执行引擎中心 — 接口规格

> **版本**：v1.0 | **更新日期**：2026-10-11

## 1. 核心接口

### 1.1 执行引擎 Engine

```python
class TradingEngine:
    def execute(self, order_request: OrderRequest) -> OrderResponse: ...
    def cancel(self, order_id: str) -> CancelResponse: ...
    def get_status(self, order_id: str) -> OrderStatus: ...
    def get_positions(self) -> List[Position]: ...
```

### 1.2 订单协议 Protocol

```python
@dataclass
class OrderRequest:
    symbol: str           # 交易对，如 BTC-USDT
    side: str             # buy / sell
    order_type: str       # market / limit / twap
    quantity: Decimal     # 下单数量
    price: Optional[Decimal] = None  # 限价单价格
    strategy: str         # 策略标识
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None

@dataclass
class OrderResponse:
    order_id: str
    status: str           # submitted / partial / filled / cancelled / rejected
    filled_quantity: Decimal
    avg_price: Decimal
    slippage: Decimal
    timestamp: datetime
```

### 1.3 执行算法 Algorithm

```python
class ExecutionAlgorithm(ABC):
    @abstractmethod
    def execute(self, request: OrderRequest, adapter: ExchangeAdapter) -> OrderResponse: ...
```

实现类：
- `DirectMarketAlgorithm` — 直连市价
- `SmartPassiveAlgorithm` — 智能被动
- `SmartTWAPAlgorithm` — 智能 TWAP

### 1.4 交易所适配器 Adapter

```python
class ExchangeAdapter(ABC):
    @abstractmethod
    def place_order(self, request: OrderRequest) -> OrderResponse: ...
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool: ...
    @abstractmethod
    def get_order_status(self, order_id: str) -> OrderStatus: ...
```

实现类：
- `OKXAdapter` — OKX 实盘
- `PaperAdapter` — 模拟盘

## 2. 配置接口

```python
class TEEConfig:
    exchange: str                    # 默认交易所
    default_algorithm: str           # 默认执行算法
    max_slippage_bps: int            # 最大滑点阈值（基点）
    kill_switch_enabled: bool        # 熔断开关
    failopen_enabled: bool           # FAIL-OPEN 开关
    audit_enabled: bool              # 审计开关
```

## 3. 审计接口

```python
class Auditor:
    def record_order(self, request: OrderRequest, response: OrderResponse) -> None: ...
    def record_event(self, event: AuditEvent) -> None: ...
    def query(self, symbol: str, start: datetime, end: datetime) -> List[AuditRecord]: ...
```

## 4. 集成接口

### 4.1 V15 集成

```python
class V15Integration:
    def on_v15_signal(self, signal: dict) -> OrderRequest: ...
```

### 4.2 易经集成

```python
class YijingIntegration:
    def on_yijing_signal(self, signal: dict) -> OrderRequest: ...
```
