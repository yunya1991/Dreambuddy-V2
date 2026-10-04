# Experiments 技术设计文档

> **版本**：v1.0
> **最后更新**：2026-09-30

---

## 1. 概述

`experiments/` 模块是 DreamBuddy v2 的交易实验工程，通过 **AB 双 Agent 对比**验证 Dreambuddy OS 架构的可行性。

- **Agent A**：Raw LLM 驱动，仅依赖模型原生推理（对照组）
- **Agent B**：Dreambuddy OS 架构，SACG 四层 + 进化（实验组）
- **Agent C**：基于 Dream OS 内核的交易分析应用（预留）

实验在 Hyperliquid 永续合约市场进行，A/B 同市场、不同决策框架、真实账户隔离。

---

## 2. 架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────┐
│              Experiments 实验工程                │
├─────────────┬───────────────┬───────────────────┤
│  Agent A    │   Agent B     │    Agent C        │
│  (对照组)    │  (实验组)      │   (预留)           │
├─────────────┴───────────────┴───────────────────┤
│              Core 核心引擎层                      │
│  ┌────────┐ ┌──────────┐ ┌──────────┐ ┌───────┐ │
│  │ S意图层 │ │ A编排层  │ │ C执行层  │ │ G存储 │ │
│  └────────┘ └──────────┘ └──────────┘ └───────┘ │
│  ┌────────┐ ┌──────────┐                        │
│  │ 进化层  │ │ 节点注册表 │                        │
│  └────────┘ └──────────┘                        │
├─────────────────────────────────────────────────┤
│              Execution 执行层                     │
│        Hyperliquid / OKX / 链上 TP-SL            │
└─────────────────────────────────────────────────┘
```

### 2.2 SACG 四层架构

| 层 | 全称 | 职责 | 核心模块 |
|----|------|------|---------|
| S | Sense（意图） | 用户目标 → 可执行蓝图 | `intent_engine/engine.py` |
| A | Arrange（编排） | 蓝图 → 执行图（节点选择+预算分配） | `graph_orchestrator.py` |
| C | Compute（执行） | 执行图 → 结果聚合 | `c_execution_layer/unified_executor.py` |
| G | GraphStore（存储） | 状态快照 + 压缩 + 历史 | `g_graph_storage/manager.py` |

### 2.3 A/C/F 三链

| 链 | 职责 | 代表节点 |
|----|------|---------|
| A 链 | 执行闭环（LLM 驱动） | A0/A1/A2/A3/A4/A9 |
| C 链 | 经典量化（零 Token） | C1 技术扫描 |
| F 链 | 基本面（资金流/情绪/新闻） | F1/F2/F3/F4/F5 |

---

## 3. 核心算法

### 3.1 意图识别三层价值转换（S链）

`IntentRecognitionEngine.recognize()` 实现三层转换：

1. **Layer 1 收敛**：`ObjectiveExtractor` 从混沌输入提取单点目标
2. **Layer 2 展开**：`OKRBuilder` 将目标分解为 OKR 线/网
3. **Layer 3 落地**：`BlueprintBuilder` 生成可执行蓝图

```python
objective = self._extract_objective(user_message, mkt_data, signals, context)
if objective.clarify_needed:
    result.state = 'clarifying'
else:
    okr = self._build_okr(objective)
    blueprint = self._build_blueprint(okr, context)
```

### 3.2 动态杠杆计算（Agent B）

`agent_b_runner.py` 基于置信度动态计算杠杆：

- 置信度 = threshold (0.4) → min_lev (1x)
- 置信度 = 0.6 → 约 3x
- 置信度 ≥ 0.8 → max_lev (5x)

### 3.3 连败保护 48h 超时（Agent A）

`check_loss_protection_timeout()` 检查连败保护：

- 连败 ≥ `LOSS_PROTECTION_TRIGGER` (3) 触发保护
- 超过 48h 自动重置 `loss_streak=0`
- 未超时则强制 HOLD，保留原始置信度，记录倒计时

### 3.4 图压缩策略

`GraphStorageManager` 默认使用 `VALUE_PRIORITY` 压缩策略，压缩率 0.5，支持自动压缩。

### 3.5 进化引擎三层来源

`EvolutionEngine` 管理三种进化来源：

| 来源 | 枚举值 | 说明 |
|------|--------|------|
| A8 理论与实践 | `a8_theory_practice` | 内部自我批评自循环 |
| 做梦部反思 | `dream_oneirology` | 潜意识层外部视角 |
| GitHub 经验 | `github_best_practice` | 外部成熟经验验证 |

进化生命周期：`PROPOSED → BACKTESTING → OBSERVATION → ADOPTED/REJECTED → ROLLED_BACK`

---

## 4. 数据流

### 4.1 Agent A 决策流程

```
加载记忆 → check_loss_protection_timeout()
  → fetch_market_context() (1H K线 + 资金费率)
  → agent_a_llm_decide() (三级回退: Trae → DeepSeek → Rule)
  → 连败保护判断 → run_exit_check()
  → 执行交易 (AUTO_EXECUTE)
  → 更新记忆 + Lessons
  → maybe_switch_master()
  → 同步 PR 评论
```

### 4.2 Agent B 决策流程

```
加载记忆 → Dreambuddy OS SKILL 调用
  → 意图识别 (intent_gateway)
  → BAC 三层架构规划 (chain_planner + chain_router)
  → 动态执行 (unified_executor)
  → 自我进化 (evolution_engine)
  → D-Z-E 开发链
  → 执行交易 → 更新记忆
```

### 4.3 图存储数据流

```
S(意图) → G.B(蓝图)
A(编排) → G.A(架构)
C(执行) → G.C(记录)
       ↓
   GraphCompressor 压缩
   GraphExpander 展开
   History 历史版本
```

---

## 5. 接口设计

### 5.1 IntentRecognitionEngine

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

### 5.2 GraphStorageManager

```python
def __init__(
    self,
    storage_path: Optional[str] = None,
    default_compression_strategy: CompressionStrategy = CompressionStrategy.VALUE_PRIORITY,
    default_compression_ratio: float = 0.5,
    auto_compress: bool = False,
)
```

### 5.3 EvolutionEngine

```python
def __init__(self, agent_id: str = "a")

def propose_evolution(self, source: EvolutionSource, ...) -> ...
```

### 5.4 HyperliquidClient

```python
client = HyperliquidClient(agent_id)
opps = client.scan_opportunities()
candles = get_candles(coin, "1h", 100, client.proxies)
```

---

## 6. 状态管理

### 6.1 Agent A 记忆

存储于 `data/agent_a_memory.json`，包含：教训 (Lessons)、交易记录、大师切换、连胜连败、连败保护状态。

### 6.2 Agent B 记忆

存储于 `data/agent_b_memory.json`，包含：`regime_history`、`lessons`、`recent_decisions`、`win_streaks`、`loss_streaks`、`active_positions`、`prior_cycle_suggestions`、`next_cycle_suggestions`。

### 6.3 图检查点

`graph_checkpointer.py` 提供执行图状态持久化。

### 6.4 进化池

`data/evolution/{agent_id}_evolution_pool.json` 和 `{agent_id}_evolution_history.json`。

---

## 7. 配置管理

### 7.1 配置文件

| 文件 | 说明 |
|------|------|
| `config/experiment.json` | 实验参数（账户/标的/仓位/评分权重） |
| `config/.env.common` | 公共环境变量 |
| `config/.env.template` | 配置模板 |
| `config/.env.screen` | 三屏模式配置 |

### 7.2 环境变量

| 变量 | 说明 |
|------|------|
| `AUTO_EXECUTE` | 自动执行交易开关 |
| `PER_TRADE_PCT` | 单笔仓位比例 |
| `GH_TOKEN` / `GITHUB_TOKEN` | GitHub PR 评论 Token |

---

## 8. 错误处理

### 8.1 LLM 三级回退（Agent A）

`agent_a_llm.py` 实现：Trae → DeepSeek V4 → 基本规则。

### 8.2 节点重试策略

`NodeRetryPolicy`：`max_retries=3`，重试条件 `timeout`/`network_error`，指数退避。

### 8.3 统一节点执行器降级

`UnifiedNodeExecutor` 支持 `enable_fallback=True`，节点失败时降级到备选路径。

### 8.4 执行异常保护（Agent A）

交易执行包裹 `try/except`，API 失败不崩溃。

---

## 9. 扩展性设计

### 9.1 节点注册表

粗-中-细三层结构（链→模块→节点），支持从模块注册表自动生成节点注册，多维度索引（链/模块/标签/阶段）。

节点类型：`skill_node`、`api_node`、`local_node`、`composite_node`。

### 9.2 适配器框架

`modules/adapter_framework.py` 将 SKILL/API/本地函数统一包装为节点，OS 内核无需关心具体实现。

### 9.3 进化系统

三层进化来源，提议-回测-观察-采用的完整生命周期，支持回滚。

### 9.4 Agent C 预留

基于 Dream OS 内核，共用 Agent B 的 Hyperliquid API 和配置，可做对比测试。

---

## 10. 变更记录

| 日期 | 版本 | 变更内容 |
|------|------|---------|
| 2026-09-30 | v1.0 | 初始文档创建（从代码提取） |
