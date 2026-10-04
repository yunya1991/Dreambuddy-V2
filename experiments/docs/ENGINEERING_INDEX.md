# Experiments 工程索引 (ENGINEERING_INDEX)

> **版本**：v1.0
> **最后更新**：2026-09-30

---

## 1. 模块定位表

| 模块 | 路径 | 定位 | 核心职责 |
|------|------|------|---------|
| AB Trading 实验 | `ab-trading/` | 核心实验工程 | A/B 双 Agent 对比交易实验 |
| Agent A | `ab-trading/agents/agent_a_runner.py` | 对照组 | Raw LLM 驱动交易（六维分析+三级回退） |
| Agent B | `ab-trading/agents/agent_b_runner.py` | 实验组 | Dreambuddy OS 架构验证（BAC三层+进化） |
| Agent C | `agent_c/agent_c.py` | 预留 | 基于 Dream OS 内核的交易分析应用 |
| 核心引擎 | `ab-trading/core/` | 引擎层 | 图编排/意图/执行/存储/进化/节点 |
| 执行层 | `ab-trading/execution/` | 交易执行 | Hyperliquid/OKX 合约、链上 TP-SL |
| 评分层 | `ab-trading/scoring/` | 日志评分 | DecisionLog 结构与保存 |
| 配置 | `ab-trading/config/` | 配置 | experiment.json、.env |
| 文档 | `ab-trading/docs/` | 文档 | A/B 框架、三屏系统设计 |
| 脚本 | `ab-trading/scripts/` | 运维 | 启动脚本、cron、标的筛选 |
| 测试 | `ab-trading/tests/` | 测试 | 压力测试、LLM回退测试 |

---

## 2. 目录地图

```
experiments/
├── ab-trading/
│   ├── agents/                      # Agent 主流程
│   │   ├── agent_a_runner.py        # Agent A（Raw LLM 对照）
│   │   └── agent_b_runner.py        # Agent B（DreamBuddy 实验）
│   ├── core/
│   │   ├── graph_orchestrator.py    # 图编排器（A/C/F 三链）
│   │   ├── chain_router.py          # B 链路执行引擎
│   │   ├── chain_planner.py         # 零 Token 链路规划器
│   │   ├── intent_gateway.py        # 意图识别层
│   │   ├── classic_driver.py        # Classic 模式驱动
│   │   ├── trading_memory.py        # B 交易记忆
│   │   ├── agent_a_memory.py        # A 记忆系统
│   │   ├── agent_a_llm.py           # A LLM 决策
│   │   ├── exit_module.py           # 离场模块
│   │   ├── llm_client.py            # LLM 客户端
│   │   ├── graph_checkpointer.py    # 图检查点
│   │   ├── intent_engine/           # 意图引擎（三层）
│   │   ├── c_execution_layer/       # C层执行
│   │   ├── evolution/               # 进化引擎
│   │   ├── g_graph_storage/         # G层图存储
│   │   ├── nodes/                   # 节点定义 + 注册表
│   │   ├── modules/                 # 模块框架（适配器/指标/API）
│   │   ├── a_graph_orchestrator/    # 图编排器类型
│   │   ├── dual_channel/            # 双通道对比
│   │   ├── memory/                  # 记忆管理
│   │   └── shared/                  # 共享类型与接口
│   ├── execution/
│   │   ├── aster_spot.py            # Hyperliquid 合约执行
│   │   ├── okx_spot.py              # OKX 现货（预留）
│   │   ├── onchain_tpsl.py          # 链上止盈止损
│   │   └── hyperliquid/utils/signing.py
│   ├── scoring/
│   │   └── scorecard.py             # DecisionLog 结构与保存
│   ├── config/
│   │   ├── experiment.json          # 实验参数
│   │   ├── .env.common              # 公共环境变量
│   │   └── .env.template            # 配置模板
│   ├── docs/                        # 技术文档
│   ├── skills/                      # SKILL 定义
│   ├── scripts/                     # 运维脚本
│   ├── tests/                       # 测试
│   └── A系列研报/                    # 研报输出
└── agent_c/
    └── agent_c.py                   # Agent C（预留）
```

---

## 3. 文件清单与职责

### 3.1 agents/ — Agent 主流程

| 文件 | 关键类/函数 | 职责 |
|------|------------|------|
| `agent_a_runner.py` | `fetch_market_context()` | 采集标的 1H K线 + 资金费率 |
| `agent_a_runner.py` | `UNIVERSE_A` (20币种) | A 可交易标的池 |
| `agent_b_runner.py` | `load_memory()` | 加载跨 session 记忆 |
| `agent_b_runner.py` | `UNIVERSE_B` (20币种) | B 可交易标的池 |
| `agent_b_runner.py` | `MEMORY_PATH` | B 记忆存储路径 `data/agent_b_memory.json` |

### 3.2 core/ — 核心引擎

| 文件 | 关键类/函数 | 职责 |
|------|------------|------|
| `graph_orchestrator.py` | `GraphOrchestrator` | 主编排器，A/C/F 三链编排 |
| `graph_orchestrator.py` | `NodeSelector` | 动态节点选择器（意图/上下文/置信度） |
| `graph_orchestrator.py` | `ExecutionGraph` | 执行图结构 |
| `graph_orchestrator.py` | `ResultAggregator` | 结果聚合器 |
| `graph_orchestrator.py` | `ExecutionMode` (枚举) | SEQUENTIAL/PARALLEL/CONDITIONAL/PIPELINE |
| `intent_engine/engine.py` | `IntentRecognitionEngine` | 意图识别引擎（三层价值转换） |
| `intent_engine/engine.py` | `recognize()` | 完整意图识别流程 |
| `c_execution_layer/unified_executor.py` | `UnifiedNodeExecutor` | 统一节点执行器（注册表+适配器+重试+降级） |
| `g_graph_storage/manager.py` | `GraphStorageManager` | G层图存储管理器（G.B/G.A/G.C） |
| `nodes/node_registry.py` | `IOSchema` | 节点输入输出 Schema |
| `nodes/node_registry.py` | `NodeRetryPolicy` | 节点重试策略 |
| `evolution/evolution_engine.py` | `EvolutionEngine` | 进化引擎（三层进化） |
| `evolution/evolution_engine.py` | `EvolutionSource` (枚举) | A8_THEORY_PRACTICE / DREAM_ONEIROLOGY / GITHUB_BEST_PRACTICE |
| `evolution/evolution_engine.py` | `EvolutionStatus` (枚举) | PROPOSED/BACKTESTING/OBSERVATION/ADOPTED/REJECTED/ROLLED_BACK |
| `agent_a_memory.py` | `check_loss_protection_timeout()` | 连败保护 48h 超时检查 |
| `agent_a_memory.py` | `get_loss_protection_countdown()` | 连败保护倒计时 |
| `exit_module.py` | `run_exit_check()` | 离场检查 |
| `exit_module.py` | `init_position()` | 初始化持仓离场 |
| `classic_driver.py` | `ClassicDriver` | Classic 模式驱动器 |

### 3.3 core/nodes/ — 节点清单

| 文件 | 节点 | 职责 |
|------|------|------|
| `a0_contradiction.py` | A0 | 矛盾检测与排序（内置于 A2/A3） |
| `a1_research.py` | A1 | 调研节点 |
| `a2_analysis.py` | A2 | 分析节点（含 A0） |
| `a3_strategy.py` | A3 | 策略设计（含 A0） |
| `a4_gate.py` | A4 | 门禁节点（≥65% 通过） |
| `a9_exit.py` | A9 | 离场节点 |
| `c1_tech_scan.py` | C1 | 技术扫描（零 Token） |
| `f1_news.py` | F1 | 新闻情报 |
| `f2_fund_flow.py` | F2 | 资金流（零 Token） |
| `f3_sentiment.py` | F3 | 情绪面（零 Token） |
| `f4_onchain.py` | F4 | 链上数据 |
| `f5_macro.py` | F5 | 宏观分析 |
| `oneirology.py` | 做梦部 | 弗洛伊德机制分析 |

### 3.4 execution/ — 执行层

| 文件 | 关键类/函数 | 职责 |
|------|------------|------|
| `aster_spot.py` | `HyperliquidClient` | Hyperliquid 合约客户端 |
| `aster_spot.py` | `scan_opportunities()` | 扫描交易机会 |
| `aster_spot.py` | `get_candles()` | 获取 K 线数据 |
| `onchain_tpsl.py` | - | 链上止盈止损 |

### 3.5 scoring/ — 评分层

| 文件 | 关键类/函数 | 职责 |
|------|------------|------|
| `scorecard.py` | `DecisionLog` | 决策日志结构 |
| `scorecard.py` | `_cycle_id()` | 生成周期 ID |

---

## 4. 核心流程索引

### 4.1 Agent A 风控流程

```
加载记忆 → check_loss_protection_timeout() → 连败≥3?
  ├─ 是 + 超过48h → 重置 loss_streak=0，继续正常决策
  ├─ 是 + 未超时 → LLM决策后强制HOLD，保留原始置信度，记录倒计时
  └─ 否 → 正常决策
```

### 4.2 Agent B 资金分配流程

```
client.get_account() → equity = acct["equity"]（不截断）
  ├─ ChainRouter(equity=equity) → pos_usdt = equity × PER_TRADE_PCT
  └─ ClassicDriver(per_trade_usdc=equity × 0.05)
```

### 4.3 意图识别三层流程（S链）

```
Layer 1 收敛：objective_extractor → 单点目标
Layer 2 展开：okr_builder → OKR 线/网
Layer 3 落地：blueprint_builder → 可执行蓝图
```

### 4.4 进化引擎生命周期

```
propose_evolution() → BACKTESTING → OBSERVATION
  → ADOPTED（采用）或 REJECTED（拒绝）
  → ROLLED_BACK（回滚）
```

### 4.5 G层图存储协作

```
运行时三层：S(意图) → A(编排) → C(执行)
       ↓          ↓          ↓
存储三层：  G.B(蓝图)   G.A(架构)   G.C(记录)
```

---

## 5. 配置参数索引

### 5.1 experiment.json

| 配置路径 | 值 | 说明 |
|---------|-----|------|
| `experiment.id` | `ab-trading-v2` | 实验 ID |
| `experiment.start_date` | `2026-06-23` | 开始日期 |
| `experiment.target_cycles` | `84` | 目标周期数 |
| `experiment.cron_interval_hours` | `1` | 间隔小时 |
| `position_sizing.per_trade_pct` | `0.05` | 单笔 5% |
| `position_sizing.max_leverage` | `5` | 最大 5x |
| `position_sizing.hard_stop_loss_pct` | `0.04` | 止损 4% |
| `position_sizing.take_profit_pct` | `0.08` | 止盈 8% |
| `scoring.weights.pnl_pct` | `0.30` | PnL 权重 30% |
| `scoring.weights.win_rate` | `0.20` | 胜率权重 20% |

### 5.2 运行时环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AUTO_EXECUTE` | `false` | 自动执行交易 |
| `PER_TRADE_PCT` | `0.05` | 单笔仓位比例 |
| `GH_TOKEN` / `GITHUB_TOKEN` | - | GitHub PR 评论 Token |

### 5.3 图存储默认参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `default_compression_strategy` | `VALUE_PRIORITY` | 默认压缩策略 |
| `default_compression_ratio` | `0.5` | 默认压缩率 50% |
| `auto_compress` | `false` | 自动压缩 |

### 5.4 节点重试策略

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `max_retries` | `3` | 最大重试次数 |
| `retry_on` | `["timeout", "network_error"]` | 重试条件 |
| `backoff_strategy` | `exponential` | 退避策略 |
| `base_delay_ms` | `100` | 基础延迟 |
| `max_delay_ms` | `10000` | 最大延迟 |

---

## 6. 测试体系

| 测试文件 | 说明 |
|---------|------|
| `tests/stress_test.py` | 压力测试 |
| `tests/test_agent_b_fixes.py` | Agent B 修复验证 |
| `tests/test_llm_fallback.py` | LLM 三级回退测试 |
| `test_bridge_server.py` | 桥接服务器测试 |
| `test_dynamic_chain_fusion.py` | 动态链路融合测试 |
| `test_dynamic_intent_recognizer.py` | 动态意图识别测试 |
| `test_full_mode.py` | 全模式测试 |
| `test_g_graph_storage.py` | G层图存储测试 |
| `test_graph_orchestrator.py` | 图编排器测试 |
| `test_intent_engine.py` | 意图引擎测试 |
| `test_interface_layer.py` | 接口层测试 |
| `test_os_e2e.py` | OS 端到端测试 |
| `test_s_layer_llm_integration.py` | S层 LLM 集成测试 |
| `test_stress_test.py` | 压力测试（500轮） |
| `test_tpsl.py` | 止盈止损测试 |
| `test_trading.py` | 交易测试 |

---

## 7. 技术债务

| 项目 | 说明 | 位置 |
|------|------|------|
| OKX 现货预留 | `okx_spot.py` 仅预留未实现 | `execution/okx_spot.py` |
| Agent C 预留 | Agent C 基于 Dream OS 内核，功能待完善 | `agent_c/agent_c.py` |
| 记忆清理 | 需要定期清理 `data/` 下记忆文件 | `scripts/run_memory_cleanup.sh` |
| 进化调度 | 进化引擎需通过 launchd 定期触发 | `evolution_scheduler.py` |

---

## 8. 快速导航

| 目标 | 跳转 |
|------|------|
| Agent A 入口 | [agent_a_runner.py](../ab-trading/agents/agent_a_runner.py) |
| Agent B 入口 | [agent_b_runner.py](../ab-trading/agents/agent_b_runner.py) |
| 图编排器 | [graph_orchestrator.py](../ab-trading/core/graph_orchestrator.py) |
| 意图引擎 | [engine.py](../ab-trading/core/intent_engine/engine.py) |
| 统一执行器 | [unified_executor.py](../ab-trading/core/c_execution_layer/unified_executor.py) |
| 图存储 | [manager.py](../ab-trading/core/g_graph_storage/manager.py) |
| 节点注册表 | [node_registry.py](../ab-trading/core/nodes/node_registry.py) |
| 进化引擎 | [evolution_engine.py](../ab-trading/core/evolution/evolution_engine.py) |
| Hyperliquid 执行 | [aster_spot.py](../ab-trading/execution/aster_spot.py) |
| 实验配置 | [experiment.json](../ab-trading/config/experiment.json) |
| 技术设计 | [TECHNICAL_DESIGN.md](TECHNICAL_DESIGN.md) |
| API 规范 | [API_SPEC.md](API_SPEC.md) |
