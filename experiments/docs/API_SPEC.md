# Experiments API 规范

> **版本**：v1.0
> **最后更新**：2026-09-30

---

## 1. 接口概览

experiments 模块的对外接口主要包括：

1. **Python API**：核心引擎类（图编排器、意图引擎、执行器、存储管理器、进化引擎）
2. **交易执行接口**：Hyperliquid 合约执行
3. **配置接口**：experiment.json 实验参数

---

## 2. 认证方式

### 2.1 Hyperliquid API

- 使用 `.env` 中配置的 API 私钥进行签名
- 签名工具位于 `execution/hyperliquid/utils/signing.py`
- Agent A 使用主账户，Agent B 使用子账户

### 2.2 LLM Provider

- Trae / DeepSeek API Key 从 `.env` 读取
- 三级回退：Trae → DeepSeek V4 → 基本规则

### 2.3 GitHub PR 评论

- `GH_TOKEN` / `GITHUB_TOKEN` 环境变量
- Agent B PR 编号固定为 `"52"`

---

## 3. 接口详情

### 3.1 IntentRecognitionEngine.recognize

意图识别引擎主入口，执行三层价值转换。

**签名**：

```python
def recognize(
    self,
    user_message: Optional[str] = None,
    mkt_data: Optional[Dict] = None,
    signals: Optional[List[Dict]] = None,
    session_id: Optional[str] = None,
    context: Optional[Dict] = None,
) -> IntentRecognitionResult
```

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `user_message` | str | 否 | 用户自然语言输入 |
| `mkt_data` | dict | 否 | 市场数据 |
| `signals` | list[dict] | 否 | 信号列表 |
| `session_id` | str | 否 | 会话 ID |
| `context` | dict | 否 | 上下文信息 |

**返回**：`IntentRecognitionResult`（包含 objective / okr / blueprint / state / confidence）

**示例**：

```python
from core.intent_engine.engine import IntentRecognitionEngine

engine = IntentRecognitionEngine()
result = engine.recognize(
    user_message="BTC 现在怎么看？",
    mkt_data={"price": 65000, "rsi14": 45},
)
print(result.state, result.confidence)
```

### 3.2 GraphStorageManager

G 层图存储管理器统一入口。

**签名**：

```python
def __init__(
    self,
    storage_path: Optional[str] = None,
    default_compression_strategy: CompressionStrategy = CompressionStrategy.VALUE_PRIORITY,
    default_compression_ratio: float = 0.5,
    auto_compress: bool = False,
)
```

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `storage_path` | str | None | 存储路径（None 表示内存模式） |
| `default_compression_strategy` | CompressionStrategy | VALUE_PRIORITY | 默认压缩策略 |
| `default_compression_ratio` | float | 0.5 | 默认压缩率 |
| `auto_compress` | bool | False | 是否自动压缩 |

**示例**：

```python
from core.g_graph_storage.manager import GraphStorageManager

manager = GraphStorageManager(storage_path="./data/graphs")
```

### 3.3 EvolutionEngine

进化引擎，管理进化提议的生命周期。

**签名**：

```python
def __init__(self, agent_id: str = "a")
```

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `agent_id` | str | "a" | Agent 标识（a/b） |

**进化来源枚举**：

| 枚举值 | 说明 |
|--------|------|
| `a8_theory_practice` | A8 理论与实践验证进化 |
| `dream_oneirology` | 做梦部外部反思进化 |
| `github_best_practice` | GitHub 成熟经验搜索进化 |

**进化状态枚举**：

| 枚举值 | 说明 |
|--------|------|
| `proposed` | 已提议 |
| `backtesting` | 回测中 |
| `observation` | 观察期 |
| `adopted` | 已采用 |
| `rejected` | 已拒绝 |
| `rolled_back` | 已回滚 |

### 3.4 UnifiedNodeExecutor

统一节点执行器，整合注册表+适配器+重试+降级。

**签名**：

```python
def __init__(
    self,
    node_registry: Optional[Any] = None,
    module_registry: Optional[Any] = None,
    enable_retry: bool = True,
    enable_fallback: bool = True,
)
```

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `node_registry` | Any | None | 节点注册表 |
| `module_registry` | Any | None | 模块注册表 |
| `enable_retry` | bool | True | 启用重试 |
| `enable_fallback` | bool | True | 启用降级 |

### 3.5 HyperliquidClient

Hyperliquid 合约执行客户端。

**签名**：

```python
client = HyperliquidClient(agent_id)
opps = client.scan_opportunities()
candles = get_candles(coin, "1h", 100, client.proxies)
```

**功能**：

| 方法 | 说明 |
|------|------|
| `scan_opportunities()` | 扫描交易机会 |
| `get_candles(coin, interval, limit, proxies)` | 获取 K 线数据 |
| 开仓/平仓/查询 | 合约交易执行 |

### 3.6 DecisionLog（评分）

决策日志结构定义。

**签名**：

```python
from scoring.scorecard import DecisionLog, _cycle_id

cycle_id = _cycle_id()
```

---

## 4. 错误码

### 4.1 错误码体系（shared/errors.py）

| 错误码 | 说明 |
|--------|------|
| `OSBaseError` | OS 基础错误 |
| `NodeError` | 节点执行错误 |
| `ErrorCode` | 统一错误码枚举 |
| `wrap_exception()` | 异常包装函数 |
| `ErrorInfo` | 错误信息结构 |

### 4.2 LLM 回退错误

- Trae 失败 → 降级 DeepSeek
- DeepSeek 失败 → 降级基本规则
- 全部失败 → 返回 HOLD 决策

### 4.3 节点执行错误

- 超时：触发重试（指数退避）
- 网络错误：触发重试
- 重试耗尽：触发降级（fallback）
- 降级失败：返回失败结果

---

## 5. 版本管理

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-09-30 | 初始 API 规范 |

实验 ID：`ab-trading-v2`，开始日期 `2026-06-23`，目标周期 84，Cron 间隔 1 小时。
