# Dreambuddy OS API 规范

> **版本**：v1.0
> **最后更新**：2026-09-30

---

## 1. 接口概览

Dreambuddy OS 提供三类对外接口：

1. **HTTP RESTful API**：基于 Flask，暴露 TradingAgent 能力
2. **CLI 命令行**：基于自定义命令框架
3. **Python API**：TradingAgent 及核心类

---

## 2. 认证方式

### 2.1 HTTP API

当前 API 服务未实现鉴权中间件，默认本地部署（`127.0.0.1`）。生产环境需自行添加 API Key / Token 鉴权。

### 2.2 LLM Provider

LLM API Key 从 `dreamos/capabilities/trading/.env` 或系统环境变量读取。

### 2.3 交易所

Hyperliquid / OKX API 凭据从 `.env` 加载，签名由各适配器内部完成。

---

## 3. 接口详情

### 3.1 HTTP API 端点

基础路径：`/api/v1`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/run` | 执行一次完整推理 |
| POST | `/api/v1/run/async` | 异步执行推理（后台线程） |
| GET | `/api/v1/result/<cycle_id>` | 轮询异步执行结果 |
| POST | `/api/v1/intent` | 只做意图识别 |
| POST | `/api/v1/analyze` | 交易分析（= /run 的交易专用别名） |
| POST | `/api/v1/chat` | 对话式分析（自然语言） |
| GET | `/api/v1/nodes` | 已注册节点列表 |
| GET | `/api/v1/history` | 历史记录 |
| GET | `/api/v1/status` | Agent 状态 |
| GET | `/api/v1/health` | 健康检查 |
| GET | `/api/v1/budget` | 获取预算状态 |
| POST | `/api/v1/budget/reset` | 重置预算 |

### 3.2 POST /api/v1/run

执行一次完整 S-A-C-G 推理。

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `user_input` | str | 否 | 用户自然语言输入 |
| `market_data` | dict | 否 | 市场数据（price/rsi14/ema20/regime 等） |
| `context` | dict | 否 | 上下文信息 |
| `intent_hint` | str | 否 | 意图提示 |
| `phase` | int | 否 | 渐进式编排档位（1/2，其余为完整编排） |

**响应**：

```json
{
  "action": "LONG | SHORT | HOLD",
  "confidence": 0.75,
  "rationale": ["..."],
  "cycle_id": "uuid",
  "intent": {"type": "...", "confidence": 0.8},
  "plan": {"chain": "A", "nodes": ["a1", "a2", "a3"]},
  "latency_ms": 1234,
  "tokens_used": 1500
}
```

**示例**：

```bash
curl -X POST http://localhost:8000/api/v1/run \
  -H "Content-Type: application/json" \
  -d '{"user_input":"BTC 怎么看？","market_data":{"price":65000,"rsi14":45}}'
```

### 3.3 POST /api/v1/run/async

异步执行，请求体同 `/api/v1/run`。返回 `cycle_id`，通过 `GET /api/v1/result/<cycle_id>` 轮询结果。

### 3.4 POST /api/v1/intent

只做意图识别（S 层），不执行编排。

**请求体**：同 `/api/v1/run`（user_input / market_data）。

**响应**：`IntentResult`（意图类型、置信度）。

### 3.5 POST /api/v1/analyze

交易分析专用别名，等价于 `/api/v1/run`，请求体相同。

### 3.6 POST /api/v1/chat

对话式分析，自然语言输入。

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `message` | str | 是 | 分析请求文本 |
| `market_data` | dict | 否 | 市场数据 |

**响应**：同 `/api/v1/run`。

**示例**：

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"BTC 现在可以做多吗？","market_data":{"price":65000}}'
```

### 3.7 GET /api/v1/nodes

获取已注册节点列表。

**查询参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `chain` | str | 按链过滤（A/C/F/G） |

**响应**：节点列表（node_id / name / chain / tags / estimated_latency_ms / estimated_tokens）。

### 3.8 GET /api/v1/history

获取历史执行记录。

**查询参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `limit` | int | 10 | 显示数量 |

**响应**：历史记录列表（cycle_id / intent_type / final_action / final_confidence）。

### 3.9 GET /api/v1/status

获取 Agent 状态。

**响应**：

```json
{
  "cycles_executed": 10,
  "registered_nodes": 30,
  "history_count": 10,
  "checkpoint_count": 5,
  "budget": {
    "mode": "standard",
    "level": "healthy",
    "per_cycle": {"used": 1500, "budget": 6000, "usage_ratio": 0.25}
  }
}
```

### 3.10 GET /api/v1/health

健康检查。

**响应**：`{"status": "ok"}`

### 3.11 GET /api/v1/budget

获取预算状态。

**响应**：预算健康度（level）、各周期已用/预算、层间分配。

### 3.12 POST /api/v1/budget/reset

重置预算计数器。

---

## 4. CLI 命令

### 4.1 基础命令

| 命令 | 别名 | 说明 |
|------|------|------|
| `status` | `st` | 查看 Agent 状态 |
| `nodes` | `ls` | 列出已注册节点（`--chain` / `--tag` 过滤） |
| `history` | `hist` | 查看历史记录（`-n` 数量） |

### 4.2 分析命令

| 命令 | 别名 | 说明 |
|------|------|------|
| `analyze` | `a` | 单次市场数据分析（`--price` / `--rsi` / `--ema20` / `--regime` 等） |
| `chat` | `c` | 对话式分析（`message` 位置参数） |

**analyze 参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `--price` | float | 当前价格 |
| `--rsi` | float | RSI 14 值 |
| `--ema20` / `--ema50` / `--ema200` | float | EMA 值 |
| `--change-24h` / `--change-4h` / `--change-1h` | float | 涨跌幅 % |
| `--vol-ratio` | float | 量比 |
| `--regime` | str | 市场状态（TREND / RANGE） |
| `--funding` | float | 资金费率 |
| `--fgi` | float | 恐惧贪婪指数 (0-100) |
| `--atr` | float | ATR 百分比 |
| `-i` / `--input` | str | 用户输入文本 |

### 4.3 交易与调度命令

| 命令 | 别名 | 说明 |
|------|------|------|
| `auto` | `trade` | 自动交易 |
| `schedule` | `cron` / `job` | 定时调度 |

### 4.4 编排命令

| 命令 | 别名 | 说明 |
|------|------|------|
| `orchestration-backtest` | `orch-backtest` | 编排回测 |
| `orchestration-memory-list` | `orch-memory-list` | 编排记忆列表 |
| `orchestration-memory-show` | `orch-memory-show` | 编排记忆详情 |
| `orchestration-query` | `orch-query` | 编排查询 |
| `orchestration-evolve` | `orch-evolve` | 编排进化 |
| `orchestration-feedback` | `orch-feedback` | 编排反馈 |

### 4.5 独立 CLI 脚本

| 模块 | 命令 | 说明 |
|------|------|------|
| 回测 | `python -m dreamos.cli.dreamos_backtester` | 端到端回测（`--symbols` / `--interval`） |
| 压力测试 | `python -m dreamos.cli.stress_test` | 压力测试 |
| 动态评估 | `python -m dreamos.cli.run_dynamic_evaluator` | 动态编排器运行 |
| 多场景压测 | `python -m dreamos.cli.multi_scenario_stress_test` | 多场景压力测试 |

---

## 5. Python API

### 5.1 TradingAgent

```python
from dreamos.apps.trading_agent import TradingAgent

agent = TradingAgent(
    registry=None,               # NodeRegistry，默认 get_default_registry()
    capability_registry=None,    # 默认 get_default_capability_registry()
    budget_mode="standard",      # lean / standard / full
    auto_register=True,
    default_capability="trading",
    enable_working_memory=True,
)

result = agent.run(
    user_input="BTC 怎么看？",
    market_data={"price": 65000, "rsi14": 45},
)
# result: {action, confidence, rationale, cycle_id, intent, plan, latency_ms, tokens_used}

result = agent.chat(message="BTC 可以做多吗？", market_data={...})
status = agent.status()
history = agent.history(limit=10)
```

### 5.2 GlobalBudgetManager

```python
from dreamos.budget import GlobalBudgetManager, CostTracker

# 预算档位：lean / standard / full
manager = GlobalBudgetManager(mode="standard")
level = manager.get_budget_level()   # healthy / warning / tight / critical / exhausted
manager.reset()
```

### 5.3 动态杠杆计算

```python
from dreamos.capabilities.trading.execution.auto_trader import calc_dynamic_leverage

lev = calc_dynamic_leverage(confidence=0.7, min_lev=1, max_lev=5, threshold=0.4)
```

### 5.4 适配器

```python
from dreamos.adapters import AdapterRegistry
from dreamos.adapters.function_adapter import FunctionAdapter
from dreamos.adapters.skill_adapter import SkillAdapter
from dreamos.adapters.api_adapter import APIAdapter

reg = AdapterRegistry()
reg.register(FunctionAdapter())
reg.register(SkillAdapter())
reg.register(APIAdapter())

node = reg.to_node({"type": "function", "handler": my_func})
```

---

## 6. 错误码

### 6.1 HTTP 状态码

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 404 | 资源不存在（如 cycle_id 无效） |
| 500 | 服务器内部错误 |

### 6.2 预算降级

| BudgetLevel | 行为 |
|-------------|------|
| `healthy` | 正常执行 |
| `warning` | 减少可选节点 |
| `tight` | 跳过 LLM 识别，纯规则模式 |
| `critical` | 进一步降级 |
| `exhausted` | 切换到经典指标系统（零 Token） |

---

## 7. 版本管理

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-09-30 | 初始 API 规范 |
