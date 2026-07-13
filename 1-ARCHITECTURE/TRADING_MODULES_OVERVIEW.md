# Dreambuddy V2 交易模块全景文档

> **版本**: v2.1 | **更新**: 2026-07-10
> **用途**: 快速了解各交易模块的设计目标、架构和运行方式，便于后期维护
> **最后全链路验证**: 2026-07-10（全模块验证通过）

---

## 全链路检查结果（2026-07-10）

| 模块 | 状态 | 备注 |
|------|------|------|
| Agent A 主链路 | ✅ 正常（LLM决策+离场+记忆+进化参数） | Hyperliquid 合约，20币种 |
| Agent B 主链路 | ✅ 正常（BAC三层+动态链+图压缩+记忆闭环）| Hyperliquid 合约，20币种 |
| Agent C (DreamOS) | ✅ 正常（SACG四层+节点注册表+TradingAgent应用） | 共用 Agent B 账户，16个交易节点 |
| data_server :8765 | ✅ 正常 | 需从 `experiments/ab-trading/` 目录启动 |
| bridge_server :3847 | ✅ 正常 | 35模块 + 11节点 |
| 三屏马丁交易 | ✅ 正常（OKX实盘+V15-CT策略+4H周期） | OKX profile=screen_trade，6币种，5种策略模式 |
| 易经推理交易 | ✅ 正常（BCRM引擎+PollingTrader+OKX实盘） | 独立账户，6币种，5分钟轮询，P2完整版 |
| 三层进化调度器 | ✅ 正常 | 独立进程，三层均完成一次运行 |
| 经典指标系统 :8092 | ✅ 正常 | Flask，ml_trade_service.py |
| 基本面系统 :9094 | ❌ Python 3.9 不兼容 | 需 Python 3.11+ |
| 前端 :3000 | ✅ 可启动（Next.js dev）| 需 nvm 环境 |

### 已知问题

| # | 问题 | 影响 | 状态 |
|---|------|------|------|
| 1 | Agent A Hyperliquid API Wallet 未授权（`0x93842F...`） | 执行下单报错 `does not exist` | ⚠️ 待手动在 app 授权 |
| 2 | 基本面系统需 Python 3.11+ | fundamental_bridge 无法启动 | ⚠️ 环境升级 |

### 启动命令

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading

# 基础服务
python3 data_server.py &                              # 监控 :8765
BRIDGE_PORT=3847 python3 bridge_server.py &           # TS桥接 :3847

# 进化调度器（独立进程）
python3 evolution_scheduler.py &

# 三屏马丁交易
python3 screen_orchestrator.py &                       # 调度 + 执行

# 易经推理交易
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统
python3 -m scripts.memory_l4.polling_trader --interval 300 --coins BTC,ETH,SOL,BNB,XRP,DOGE &

# 经典指标系统（独立）
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/10-经典指标系统
python3 ml_trade_service.py &                          # :8092

# 前端（需 nvm 环境）
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND
export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh"
pnpm dev &                                              # :3000
```

---

## 目录

1. [AB实验总体说明](#一ab实验总体说明)
2. [Agent A — LLM 原生驱动](#二agent-a--llm-原生驱动对照组)
3. [Agent B — Dreambuddy 框架验证](#三agent-b--dreambuddy-框架验证实验组1)
4. [Agent C — DreamOS 内核驱动](#四agent-c--dreamos-内核驱动实验组2)
5. [三屏马丁交易系统](#五三屏马丁交易系统独立okx实盘)
6. [易经推理交易系统](#六易经推理交易系统独立模块okx实盘)
7. [三层进化系统](#七三层进化系统)
8. [关键文件索引](#八关键文件索引)

---

## 一、AB实验总体说明

```
实验目的: 验证"系统框架（Dreambuddy OS）"是否比"LLM原生推理"带来超额收益

三组对比实验:
  Agent A (对照) ─── 纯 LLM 驱动，无系统框架（Hyperliquid 20币种）
  Agent B (实验) ─── Dreambuddy 图架构 + A0-A9 SKILL 框架（Hyperliquid 20币种）
  Agent C (实验) ─── DreamOS SACG 四层内核驱动（共用 Agent B 账户）

公共底座:
  执行层:  execution/aster_spot.py (Hyperliquid EIP-712 签名下单)
  记分:    scoring/scorecard.py (决策日志)
  调度:    orchestrator.py (15分钟心跳 + 事件驱动，常规间隔1H)
  监控:    data_server.py (port:8765) + monitor.html
  桥接:    bridge_server.py (port:3847, FastAPI, 35模块+11节点)
```

---

## 二、Agent A — LLM 原生驱动（对照组）

### 设计目标
不依赖任何系统框架，让 LLM 直接作为"交易大师"做决策，验证原始 LLM 智能的边界。

### 完整执行流程（9步）

```
Step 1: 加载记忆
  ├── 当前大师风格（Jesse Livermore / Jones / Dennis 等）
  ├── Lessons（历史教训，按 普适性×重要性 评分淘汰）
  ├── 进化参数（evolution_engine 已采纳的参数，动态调整策略阈值）
  └── 连胜/连败/最大回撤统计

Step 2: 账户状态
  ├── 实盘模式（Hyperliquid API）
  └── 模拟模式（账户不可用时自动降级，使用 peak_equity 作虚拟资金）

Step 2.5: L1 离场检查（exit_module.run_exit_check）
  ├── ATR 动态止损（入场时自动计算，持续跟踪）
  ├── 移动止损（浮盈超阈值后上移止损锁利）
  └── 触发则平仓并记录 closed_trade

Step 2.6: 最大回撤保护
  └── 回撤≥15% → 强制 HOLD，暂停交易

Step 3: 扫描市场（20个标的）
  └── 采集K线 + 技术指标（EMA20/50/200, RSI14, 量比）

Step 4: LLM 决策（三级回退，SKILL框架驱动）
  1. Trae (trae.ai, claude-sonnet-4-5) — 免费额度，优先
     配额: 12次/天 (AGENT_A_TRAE_DAILY_LIMIT)
  2. DeepSeek V4 (deepseek-chat) — 付费备用
     配额: 24次/天 (AGENT_A_DEEPSEEK_DAILY_LIMIT)
  3. 规则引擎 — 硬编码兜底（0 Token，使用进化参数动态调整阈值）

  LLM 输入: 市场数据 + 记忆（Lessons+大师+进化参数）+ SKILL.md框架
  LLM 输出: action/coin/leverage/confidence/SL/TP/new_lesson/master_switch

Step 4.1: 连续HOLD保护
  └── ≥10轮 HOLD → _break_conservative_loop() 降低入场门槛强制寻找机会

Step 4.2: 连败保护
  └── ≥3次连败 → 强制本轮 HOLD

Step 4.5: L2 智能离场（LLM 主动建议）
  ├── exit_suggestions: LLM 建议平仓某持仓 → execute_exit()
  └── update_exit_levels: LLM 调整止损止盈价位

Step 5: 执行交易
  ├── open_long / open_short（Hyperliquid 市价单）
  └── 开仓成功 → init_position() 初始化 L1 止损跟踪

Step 6: 记录决策日志（DecisionLog）
  └── 包含: provider/master/top_lessons/active_positions/smart_exits

Step 7: 更新记忆
  ├── add_lesson()：写入新 Lesson（含评分，低分自动淘汰）
  ├── record_trade()：记录本次交易
  ├── maybe_switch_master()：根据 regime 评估是否切换大师
  └── update_hold_streak()：更新连续HOLD计数

Step 8: 自主调度（申请提前触发）
  ├── 高置信度信号(≥75%) → 1H后复查
  ├── 成交量异常(>2.5x) → 2H后复查
  ├── 连败≥3次 → 6H后强制复盘
  └── 置信度接近门槛(58-65%) → 1H后再试

Step 9: GitHub PR 评论同步（可选）
  └── 需配置 GITHUB_TOKEN + GITHUB_REPOSITORY + PR_NUMBER
```

### LLM 决策框架（SKILL）

Agent A 有专用 SKILL 文件：`skills/agent-a-trading/SKILL.md`

六维决策框架（每轮必走）：
```
目标 → 身份定位 → 三维分析 → 自我进化 → 向外学习 → 预算管理
       (当前大师)  技术+微观   LLM生成   外部信号   Token控制
                  +宏观跨市    Lesson
```

### 大师体系
| 大师 | 风格 | 切换触发 |
|------|------|----------|
| Jesse Livermore | 趋势跟踪（默认） | 初始 |
| Paul Tudor Jones | 宏观反转 | 连亏3次+震荡市 |
| Richard Dennis | 海龟系统 | 错过趋势行情 |
| Stanley Druckenmiller | 高确信押注 | 宏观信号极强 |

切换条件：`maybe_switch_master()` 根据 regime 自动判断

### 关键配置
```
账户:   AGENT_A_ASTER_USER=0x93842F1ea62E7E3c71494d9EA69EfC4F2D6e9934
入口:   agents/agent_a_runner.py
SKILL:  skills/agent-a-trading/SKILL.md
记忆:   data/agent_a_memory.json
配额:   data/agent_a_llm_quota.json
Trae:   TRAE_API_KEY + TRAE_MODEL=claude-sonnet-4-5
币种:   UNIVERSE_A = 20个（BTC/ETH/SOL/HYPE/UNI/LIT/XRP/ZEC/NEAR/WLD/ADA/SUI/ETHFI/ENA/JUP/XLM/GRASS/EIGEN/ZRO/IMX）
默认杠杆: 3x
止损:   4%
止盈:   8%
```

---

## 三、Agent B — Dreambuddy 框架验证（实验组1）

### 设计目标
验证"意图识别→动态链规划→A0-A9节点执行→图压缩记录→进化"这套完整框架的可行性。

### 完整执行流程

```
Step 1: 加载记忆 + DreamBuddy OS SKILL
  └── SKILL: 1-ARCHITECTURE/skills/dreambuddy-os/SKILL.md
  
Step 2: 账户状态

Step 2.5: A9 离场评估（动态链，按预算选路径）
  full模式:   C1技术 + A9综合(规则+LLM) + F链基本面 + 门禁
  standard:   C1技术 + A9综合 + 门禁
  lean模式:   C1纯代码（零Token，经典指标体系）

Step 3: 意图识别（intent_gateway.py）
  - 6种意图: TREND_FOLLOWING/MEAN_REVERSION/FUNDAMENTAL_PLAY
             BREAKOUT/UNCERTAIN/KNOWLEDGE_MATCH
  - 零Token本地打分（技术面+资金费率+RSI+Regime）
  - LLM策略评估（strategy_eval，每轮，可选三标的/策略类型建议）

Step 4: ChainPlanner 零Token规划（chain_planner.py）
  四维过滤:
    1. Token预算 → full/standard/lean 三档
    2. 知识库命中 → score≥80 升级快捷路径
    3. 历史表现 → 当前Regime+标的命中率
    4. 标的覆盖 → 小币降级/资金费率极端强制F2/F3

Step 5: ChainRouter 动态执行（chain_router.py）
  ├── 基础链必走（C1/F2/F3/A2/A4）
  ├── "一生二"：置信度不足 → 追加扩展节点
  ├── A0矛盾内置于 A2/A3（非独立节点）
  └── A2-LLM保护：LLM≥65%时防止A2规则压制到45%以下

Step 6: A4门禁（≥55%） → LONG/SHORT/HOLD

Step 7: 执行交易（Hyperliquid）

Step 8: 图压缩记录（B/A/C三层）
  B层(Blueprint): 意图目标 + Regime
  A层(Architecture): 节点执行序列 + 置信度
  C层(Chronicle): 最终决策 + 执行结果

Step 9: trading_memory 建议闭环
  └── 生成: 待验证建议/风险建议/BAC调整/D-Z-E建议

Step 10: 自我进化
  └── gap_score → A7/A8治理环 → 做梦部
```

### 三环架构

```
🔵 执行环: A1→A2→A3→A4→A5→A9（A0矛盾内置于A2/A3）
🟠 情报环: A6每1H，5级放射驱动
           L0致命→A9离场 | L1→A4验证 | L1.5变→A2更新
           L2中→观察    | L3背离→A1+A3重启
🟣 治理环: A9离场→A7(实践记录)→A8(知行合一,gap_score路由)
           gap>0.5→A1重启 | gap 0.3-0.5→A2更新 | gap<0.3→A3优化
```

### 核心模块（core/ 目录）

| 模块 | 文件 | 说明 |
|------|------|------|
| 意图识别 | `core/intent_gateway.py` | 6种意图，零Token本地打分 |
| S层意图引擎 | `core/intent_engine/` | LLM增强意图识别（动态+S链） |
| 链路规划 | `core/chain_planner.py` | 四维过滤，零Token规划 |
| 链路执行 | `core/chain_router.py` | 动态节点执行，一生二扩展 |
| 图编排器 | `core/graph_orchestrator.py` | BAC三层统一编排 |
| 图存储 | `core/g_graph_storage/` | 压缩/扩展/历史/桥接 |
| C执行层 | `core/c_execution_layer/` | 动态链融合+反射+重规划 |
| 节点注册 | `core/nodes/node_registry.py` | 11个节点（A0-A9, C1, F1-F3） |
| 模块注册 | `core/modules/module_registry.py` | 35模块 |
| 离场模块 | `core/exit_module.py` | L1/L2/L3三层离场 |
| 交易记忆 | `core/trading_memory.py` | 建议→验证→复盘闭环 |
| 进化引擎 | `core/evolution/` | A8+做梦部+GitHub 三层进化 |

### 关键配置
```
账户:   AGENT_B_ASTER_USER=0x6632da9c91A959eEBf1343f8AFAbf2807414004A
入口:   agents/agent_b_runner.py
SKILL:  1-ARCHITECTURE/skills/dreambuddy-os/SKILL.md
记忆:   data/agent_b_memory.json
图日志: data/agent_b_graph.json
记忆闭环: core/trading_memory.py
门禁:   CONFIDENCE_GATE=0.55
最大杠杆: 5x
止损:   4%
止盈:   8%
币种:   20个（BTC/ETH/SOL/HYPE/UNI/LIT/XRP/ZEC/NEAR/WLD/ADA/SUI等）
```

---

## 四、Agent C — DreamOS 内核驱动（实验组2）

### 设计目标
独立于 Agent B，通过 DreamOS 操作系统的 SACG 四层内核动态调度模块能力完成交易，验证 OS 化调度的价值。与 Agent B 形成第二层对比：**图架构自定义框架 vs DreamOS 标准化OS内核**。

### DreamOS 项目结构

```
1-ARCHITECTURE/dreamos/              ← DreamOS Python 包
  core/
    sense/                           ← S层：意图识别
      intent_engine.py
      token_budget.py
      types.py
      recognizers/
        base.py
        rule_based.py                ← 规则识别器
        llm_based.py                 ← LLM识别器
        dynamic.py                   ← 动态识别器
    arrange/                         ← A层：图编排
      graph_planner.py
      execution_graph.py
      node_selector.py
      budget_allocator.py
      types.py
    compute/                         ← C层：节点执行
      graph_executor.py
      node_runner.py
      aggregator.py
      reflector.py                   ← 反射决策
      types.py
    graph_store/                     ← G层：状态存储
      store.py
      checkpointer.py
      compressor.py
      history.py
      types.py
  nodes/                             ← 交易节点库（16个）
    a0_contradiction.py               ← A0 矛盾论分析
    a1_deep_research.py               ← A1 深度研究
    a2_comprehensive.py               ← A2 综合分析
    a3_strategy.py                    ← A3 策略制定
    a4_gate.py                        ← A4 置信度门禁
    a5_execution.py                   ← A5 交易执行
    a6_regime_monitor.py              ← A6 市场状态监控
    a9_exit_strategy.py               ← A9 离场策略
    c1_tech_scan.py                   ← C1 技术指标扫描
    c2_momentum.py                    ← C2 动量分析
    c3_volatility.py                  ← C3 波动率分析
    f1_news.py                        ← F1 新闻情报
    f2_fund_flow.py                   ← F2 资金流量
    f3_sentiment.py                   ← F3 市场情绪
    f4_onchain.py                     ← F4 链上数据
    f5_macro.py                       ← F5 宏观数据
  registry/                          ← 节点注册表
    node_registry.py
    loader.py
    decorators.py
    version_manager.py
    base.py
  adapters/                          ← 适配器框架
    base.py
    skill_adapter.py
    function_adapter.py
    api_adapter.py
  budget/                            ← Token预算管理
    global_budget.py
    cost_tracker.py
  evolution/                         ← 进化引擎
    engine.py
    gap_analyzer.py
    lesson_distiller.py
    node_optimizer.py
    types.py
  apps/                              ← 应用层
    trading_agent/
      agent.py                       ← TradingAgent 类（SACG全链路）
    cli.py
    api_server.py
  cli/                               ← CLI 交互
    repl.py
    commands.py
    analyze_commands.py
    app.py
  shared/                            ← 共享组件
    state.py
    llm_client.py
    errors.py
    interfaces.py
    utils.py
  config/
    nodes.yaml                       ← 节点配置

experiments/agent_c/
  agent_c.py                         ← Agent C 主程序（625行）
```

### SACG 四层架构

```
用户触发 / 市场数据
 ↓
S层 (Sense) — 意图识别
  dreamos.core.sense.IntentEngine
  识别器: rule_based → llm_based → dynamic（三级）
  → IntentResult (意图类型 + 置信度 + 推荐链路 + Token预算)
 ↓
A层 (Arrange) — 图编排
  dreamos.core.arrange.GraphPlanner
  → 从 NodeRegistry 动态选节点 + 分配预算 + 构建 ExecutionGraph
 ↓
C层 (Compute) — 节点执行
  dreamos.core.compute.GraphExecutor
  → 运行节点 + Reflector反射决策（置信度不足→重跑或降级）+ 结果聚合
 ↓
G层 (GraphStore) — 状态存储
  dreamos.core.graph_store.GraphStore
  → 状态快照 + 历史记录 + 上下文压缩（增量/语义/分片压缩）
 ↓
共用执行层
  HyperliquidClient（aster_spot.py）
  ← 复用 Agent B 的 Hyperliquid API 配置
```

### TradingAgent 应用

`dreamos.apps.trading_agent.TradingAgent` 类将 S-A-C-G 四层内核串联为完整的交易 Agent，内置预算管理和成本跟踪。

**核心方法：**

| 方法 | 说明 |
|------|------|
| `run(user_input, market_data, context, budget_mode)` | 执行一次完整交易分析周期 |
| `analyze(market_data)` | 纯市场数据分析（无用户输入） |
| `chat(message, market_data)` | 对话式交易分析 |
| `history(limit)` | 获取历史记录 |
| `status()` | 获取 Agent 状态（周期数/节点数/预算状态） |

**返回结果结构：**
```python
{
    "cycle_id": str,              # 周期ID
    "intent": {...},              # S层意图识别结果
    "plan": {...},                # A层图编排结果
    "execution": {...},           # C层执行统计
    "action": "LONG|SHORT|HOLD",  # 最终决策
    "confidence": float,          # 置信度
    "rationale": [str],           # 推理依据
    "tokens_used": int,           # Token消耗
    "latency_ms": float,          # 延迟
    "budget_status": {...},       # 预算状态
}
```

**使用示例：**
```python
from dreamos.apps.trading_agent import TradingAgent

agent = TradingAgent(budget_mode="standard")
result = agent.run(
    user_input="BTC 现在怎么看？",
    market_data={"price": 65000, "rsi14": 45, ...},
)
print(result["action"], result["confidence"])
```

### 节点注册表（NodeRegistry）

| 类别 | 节点 | 说明 |
|------|------|------|
| A系列（分析） | A0 矛盾论 | 矛盾分析法 |
| | A1 深度研究 | 深度基本面研究 |
| | A2 综合分析 | 多因子综合 |
| | A3 策略制定 | 策略生成 |
| | A4 门禁 | 置信度门禁 |
| | A5 执行 | 交易执行 |
| | A6 状态监控 | 市场状态监控 |
| | A9 离场策略 | 离场评估 |
| C系列（技术） | C1 技术扫描 | 技术指标扫描 |
| | C2 动量 | 动量分析 |
| | C3 波动率 | 波动率分析 |
| F系列（情报） | F1 新闻 | 新闻情报 |
| | F2 资金流 | 资金流量 |
| | F3 情绪 | 市场情绪 |
| | F4 链上 | 链上数据 |
| | F5 宏观 | 宏观数据 |

### 与 Agent B 的核心区别

| 维度 | Agent B | Agent C |
|------|---------|---------|
| 框架来源 | 自定义 intent_gateway + chain_router | DreamOS 标准化 SACG 内核 |
| 节点发现 | 硬编码节点名字符串 | NodeRegistry 动态注册发现 |
| 编排逻辑 | ChainPlanner 规则化（Token预算四维过滤）| GraphPlanner 图化调度 + 预算分配 |
| 状态管理 | JSON文件型记忆 | GraphStore 结构化状态（多压缩策略） |
| 适配器 | 直接调用 Python 函数 | AdapterFramework 统一接口契约 |
| 进化 | trading_memory + 外部进化调度器 | 内置 evolution 引擎 |
| CLI | 无 | 完整 REPL + 命令行工具 |
| 验证目的 | 验证框架流水线的可行性 | 验证 OS 化调度的工程价值 |

### 关键配置
```
入口:    experiments/agent_c/agent_c.py → AgentC 类
内核:    1-ARCHITECTURE/dreamos/ (Python包)
账户:    复用 Agent B 的 Hyperliquid API（共用执行层）
历史:    experiments/ab-trading/data/agent_c_b/*.json
节点库:  dreamos/nodes/（16个交易节点：A系列8个 + C系列3个 + F系列5个）
注册表:  dreamos.registry.NodeRegistry
TradingAgent: dreamos.apps.trading_agent.TradingAgent（SACG全链路+预算管理）
预算管理: dreamos.budget.GlobalBudgetManager + CostTracker
数据API: data_server.py /api/dreamos/analyze?symbol=BTC
```

---

## 五、三屏马丁交易系统（独立，OKX实盘）

### 设计目标
基于 Elder 三屏系统，前两屏由 AI 研报驱动做战略+战术判断，第三屏由经典指标负责精准执行，AI 不可用时全经典接管。使用 OKX 合约进行马丁策略交易。

### 三屏分工（AI驱动，经典指标降级）

```
Screen 1 — 战略层（周报驱动）
  驱动源: A系列研报/周报/screen1_*.md（每周一更新）
  功能:   7维评分（技术40/链上15/减半10/矿工10/宏观10/跨市场10/情绪5）
          → 确定大方向（牛/熊/震荡）+ 关键价位
  降级:   经典技术指标（MA200三日确认/MACD趋势/RSI月线）
      ↓
Screen 2 — 战术层（A1日报驱动 + 多策略回退）
  驱动源: A系列研报/A1研报/a1_regime_*.json（每日更新）
  功能:   根据 Regime → 马丁参数（加仓间隔/止盈倍数/vol_mult）
          → 预设入场方案（限价单位置/加仓梯级/止盈目标）
  降级1:  AI-V15 多因子评分（Screen1 35% + A1日报 30% + 周报 20% + A6情报 15%）
  降级2:  V15-CT 技术策略（斐波那契+布林带+MACD+ADX，4H周期）
  降级3:  V9基线策略（固定参数马丁兜底，"涨三不追、跌四不压"）
      ↓
Screen 3 — 执行层（A6情报 + 经典指标执行）
  驱动源: A系列研报/A6研报/*.md（每4H更新）
          → 监控 P0/P1告警 + recommendation
  执行:   screen_executor.py
          - 接收 Screen1/2 的方向约束和币种池
          - V15-CT：斐波那契分区入场 + 布林带均值回归 + MACD/ADX趋势确认
          - V9：马丁加仓（最多3层）+ 波动率自适应参数
          - MA200动态止损（日线+周线）
          - OKX CLI 下单（多币种合约）
```

### 策略模式（5种）

| 模式 | 说明 | 配置值 |
|------|------|--------|
| auto | 自动模式：LLM → AI-V15 → V15-CT → V9 四级回退 | `auto` |
| v9 | 仅 V9 基线策略 | `v9` |
| ai_v15 | 仅 AI-V15 多因子评分 | `ai_v15` |
| v15_ct | 仅 V15-CT 技术策略（斐波那契+布林带+MACD+ADX） | `v15_ct` |
| dual | 对照模式：AI三屏 + V15-CT 同时运行，AI优先，AI WAIT时用V15-CT兜底 | `dual` |

**dual 对照模式逻辑：**
```
1. 同时运行 AI三屏策略 和 V15-CT技术策略
2. AI有入场信号 → 直接用AI结果（附带V15-CT对比参考）
3. AI为WAIT但V15-CT有信号 → 用V15-CT入场
4. 两者都WAIT → 保持等待
5. AI不可用 → 纯V15-CT技术策略运行（降级为v15_ct模式）
```

### V15-CT 策略核心逻辑

```
入场分区（基于价格相对均线位置）：
  ABOVE_ALL  → 价格在所有均线之上 → 趋势确认，等回调入场
  IN_ZONE    → 价格在均线区间内 → 布林带均值回归 + MACD/ADX 趋势确认
  BELOW_ALL  → 价格在所有均线之下 → 只做多模式下等待

马丁加仓：
  最大层数: 3层
  加仓间距: 波动率自适应（默认8%，按BTC波动率比例调整）
  仓位递增: 每层 BASE_ADDON_PCT（默认8%）

止盈止损：
  止盈: 波动率自适应（默认4%，按波动率缩放）
  止损: MA200动态止损（日线MA200 + 周线MA200，取更近的）

K线周期: 4H
只做多模式: 是（BELOW_ALL等待，不做空）
```

### 降级链（完整四级）

```
正常:     AI研报驱动 → Screen1方向 + Screen2参数 → Screen3经典执行
部分降级: A6不可用 → Screen3使用技术指标判断持仓（前两屏AI仍工作）
全降级1:  LLM不可用 → AI-V15 多因子评分
全降级2:  AI-V15置信不足 → V15-CT 技术策略
全降级3:  V15-CT不适用 → V9基线策略（固定参数，永远可用）
```

### 研报加载（report_loader.py）

```python
load_weekly()           # Screen1 战略参考，TTL 1H
load_a1_daily()         # Screen2 战术参考，TTL 30min（兼容新旧JSON格式）
load_a6_intel()         # Screen3 情报参考，TTL 15min
get_all_reports()       # 全量加载（weekly + a1_daily + a6_intel）
```

### 自主调度（screen_orchestrator.py）

```
触发条件:
  1. 1H常规心跳（NORMAL_INTERVAL_H=1）
  2. BTC 1H波动 > 2%（VOLATILITY_PCT=2.0）
  3. A6情报有新内容（check_new_intel 检测 date 变化）
  4. P0级告警（A6研报含 p0_alerts>0）
  5. 关键价位自主申请

守护进程: launchd plist → com.dreambuddy.screen_monitor.plist
调度状态: data/screen_orchestrator_state.json
```

### 候选币种（6个）

| 币种 | 合约 | 说明 |
|------|------|------|
| BTC | BTC-USDT-SWAP | 波动基准 |
| ETH | ETH-USDT-SWAP | 主流币 |
| SOL | SOL-USDT-SWAP | 高波动 |
| BNB | BNB-USDT-SWAP | 平台币 |
| DOGE | DOGE-USDT-SWAP | Meme币 |
| XRP | XRP-USDT-SWAP | 主流币 |

### 保证金与仓位

```
默认仓位比例: 5%（BASE_POSITION_PCT）
最大仓位比例: 25%（MAX_POSITION_PCT）
最低保证金: 20 USDT（MIN_MARGIN_USD）
默认杠杆: 10x（DEFAULT_LEVERAGE）
名义价值 = 保证金 × 杠杆
马丁加仓: 最多3层，每层+8%仓位
```

### 关键配置
```
交易所:  OKX（okx-trade-cli，profile=screen_trade）
API密钥: 5af4066c-ccad-45b7-8205-ebaf1d08930a
研报:    experiments/ab-trading/A系列研报/
入口:    screen_orchestrator.py (调度) → screen_executor.py (Screen3执行)
引擎:    screen_engine.py (三屏逻辑整合)
经典执行: classic_executor.py（ATR止损+OKX下单）
策略模式: v15_ct（当前）
监控API: data_server.py /api/screen/status
状态文件: data/screen_trade_state.json
配置文件: config/.env
  SCREEN_STRATEGY_MODE=v15_ct
  SCREEN_AUTO_EXECUTE=true
  MIN_MARGIN_USD=20
  DEFAULT_LEVERAGE=10
```

---

## 六、易经推理交易系统（独立模块，OKX实盘）

### 设计目标
以易经六十四卦作为推理框架，配合完整的 BCRM（矛盾-阴阳-四象-八卦-六十四卦）推理引擎，形成完全独立的交易决策系统。使用独立 OKX 账户进行实盘交易。

### 项目结构

```
11-易经推理系统/
  .env                             ← 独立环境配置（密钥/参数隔离）
  constraints/                      ← 约束层（宪法+机器可读规范）
    qmm/
      phase-1.md ~ phase-4.md      ← QMM四阶段方法论
  workflows/                        ← 工作流（记忆L4/治理/交易决策/知识/进化）
  skills/
    0-CORE/                         ← 核心SKILL
    1-TRADE/                        ← A0-A9完整SKILL副本
    2-INTELLIGENCE/                 ← 情报SKILL
    3-SUPPORT/                      ← 支撑SKILL
    4-GENERIC/                      ← 通用SKILL
  scripts/
    memory_l4/
      bcrm/                         ← ⭐ BCRM 推理引擎（核心）
        engine.py                   ← BCRMEngine 主引擎
        yijing_engine.py            ← 易经引擎（六十四卦）
        bagua_engine.py             ← 八卦引擎
        liangyi_engine.py           ← 两仪引擎（阴阳二气）
        force_engine.py             ← 五行引擎
        scale_engine.py             ← 六爻引擎
        sixty_four_guas.py          ← 六十四卦定义（卦辞/爻辞）
        backtest_gate.py            ← 回测门禁（策略验证）
        knowledge_base.py           ← 知识库
        walk_forward.py             ← 滚动验证
        strategy_diversity.py       ← 策略多样性评估
        output_contract.py          ← 输出契约
        guardrail.py                ← 护栏机制
        market_preprocessor.py      ← 市场预处理器
        memory_adapter.py           ← 记忆适配器
        case_writer.py              ← Case写入器
        a_series_bridge.py          ← A系列研报桥接
        _constants.py               ← 常量定义
      qmm/                          ← QMM 质量度量模块
        engine.py                   ← QMM引擎
        gate.py                     ← QMM门禁
        mrd.py                      ← 均值回归检测
        drift.py                    ← 漂移检测
        overfitting.py              ← 过拟合检测
        trend_velocity.py           ← 趋势速度
        triple_screen.py            ← 三屏验证
        xgb_predictor.py            ← XGBoost预测器
        data_prep.py                ← 数据准备
        types.py                    ← 类型定义
        backtest.py                 ← 回测引擎
      polling_trader.py             ← ⭐ 轮询交易器（主程序）
      okx_simulated.py              ← OKX 客户端（实盘/模拟）
      trading_utils.py              ← 交易工具集（风控/绩效/仓位）
      learning_scheduler.py         ← 学习调度器（定期重训）
      process_guardian.py           ← 进程守护 + 异常告警
      knowledge_bridge.py           ← 知识库桥接
      ab_bridge.py                  ← ⚡ 对外桥接接口（AB系统）
      shared_memory_bus.py          ← 共享内存总线
      pipeline.py                   ← 数据管道
      paths.py                      ← 路径管理
      yijing_monitor.py             ← 监控服务
      yijing_trainer.py             ← 训练器
      stats_engine.py               ← 统计引擎
      review_engine.py              ← 复盘引擎
      distill_engine.py             ← 蒸馏引擎
      self_evolution_engine.py      ← 自我进化引擎
      case_registry.py              ← Case注册表
      batch_backtest.py             ← 批量回测
      failure_analyzer.py           ← 失败分析器
      scenario_extender.py          ← 场景扩展器
      quadrant_migrator.py          ← 四象限迁移器
      screen_martin_bridge.py       ← 三屏马丁桥接
      a0a9_bridge.py                ← A0-A9桥接
      a7a8_bridge.py                ← A7-A8桥接
      a_research_bridge.py          ← A系列研报桥接
      memory_graph.py               ← 记忆图谱
      meta_learning_tasks.py        ← 元学习任务
      migration_mapper.py           ← 迁移映射器
      index_builder.py              ← 索引构建器
      query_similar.py              ← 相似查询
      dashboard_renderer.py         ← 仪表盘渲染
      agent_acl.py                  ← Agent ACL控制
      com.yijing.trading.plist     ← launchd 守护进程配置
      start_trading.sh              ← 启动脚本
      install_trading.sh            ← 安装脚本
  data/
    okx_sim/
      config.json                   ← 兜底配置
  artifacts/
    trading/                        ← 交易产物
    memory/                         ← 记忆产物
    evolution/                      ← 进化产物
    governance/                     ← 治理产物
    knowledge/                      ← 知识产物
  tests/
    e2e_l4_test.py                  ← 端到端测试
    stress_test_l4.py               ← 压力测试
  docs/
    architecture.md                 ← 架构文档
    README.md
```

### BCRM 推理引擎（核心）

```
BCRM = 矛盾(Basic Contradiction) → 阴阳(LiangYi) → 四象(SiXiang) → 八卦(BaGua) → 六十四卦

推理流程:
  1. 市场数据预预处理 → 提取矛盾特征
  2. 两仪引擎 → 阴阳二气识别（多空力量对比）
  3. 四象 → 趋势+动能四象限划分
  4. 八卦 → 八种市场状态（乾/坤/震/巽/坎/离/艮/兑）
  5. 六十四卦 → 具体交易决策（卦辞解读+策略匹配）

输出契约:
  - direction: UP/DOWN/NEUTRAL
  - confidence: 0~1
  - hexagram: 卦名 + 卦辞
  - entry_price: 入场价格
  - stop_loss_px: 止损价
  - take_profit_px: 止盈价
  - reasons: 推理依据列表
```

### PollingTrader 轮询交易器

```
核心功能（P2 完整版）:
  P2-1a: 平仓后自动生成 case 存入 L4
  P2-1b: 定期重训 LiangyiEngine + QMM
  P2-2a: 动态仓位（置信度 + 波动率）
  P2-2b: 日最大亏损限制 + 连续亏损熔断
  P2-3: 交易绩效统计 + PnL 持久化
  P2-4: BCRM 矛盾格式修复
  P2-5: 进程守护 + 异常告警 + 日志持久化

核心组件:
  BCRMEngine         — 易经推理主引擎（矛盾→阴阳→四象→八卦→六十四卦）
  BaguaEngine        — 八卦引擎
  OKXSimulatedClient — OKX 客户端（实盘/模拟/试运行）
  PerformanceTracker — 绩效统计器
  RiskManager        — 风控管理器
  PositionTracker    — 仓位跟踪器
  LearningScheduler  — 学习调度器（定期重训）
  ProcessGuardian    — 进程守护
  KnowledgeBridge    — 知识库桥接

启动方式:
  python -m scripts.memory_l4.polling_trader --once
  python -m scripts.memory_l4.polling_trader --interval 300 --coins BTC,ETH,SOL,BNB,XRP,DOGE
```

### 风控体系（RiskManager）

```
动态仓位计算:
  基础仓位比例 × 置信度系数 × 波动率系数
  - 置信度系数: 0.5 + confidence × 1.0（置信越高仓位越大）
  - 波动率系数: 0.02 / volatility（波动越高仓位越小，反比）
  - 范围: min_position_size_pct ~ max_position_size_pct

保证金限制:
  最低保证金: 10 USDT（MIN_MARGIN_USDT）
  默认杠杆: 10x（DEFAULT_LEVERAGE）
  名义价值 = 保证金 × 杠杆

熔断机制:
  日亏损限制: -50 USDT（DAILY_LOSS_LIMIT）
  最大连续亏损: 5次（MAX_CONSECUTIVE_LOSSES）
  最大持仓数: 3个（MAX_POSITIONS）
```

### OKX 客户端（okx_simulated.py）

```
支持模式:
  - 实盘模式 (simulated=false, dry_run=false) → 真实下单
  - 模拟盘模式 (simulated=true) → OKX 模拟盘 API
  - 试运行模式 (dry_run=true) → 不下单，只输出日志

交易功能:
  - 市价开多/开空
  - 市价平多/平空
  - 止损止盈设置
  - 持仓查询
  - 余额查询
  - K线数据获取
  - 合约信息查询

默认配置:
  - 初始保证金: 10 USDT（DEFAULT_MARGIN_USDT）
  - 杠杆: 10x（DEFAULT_LEVERAGE）
  - 名义价值: 100 USDT（10 × 10）
```

### 对外桥接（ab_bridge.py）

```
数据流:
  AB Trading (WorkBuddy) ──→ shared_memory_bus ──→ BCRM 易经大模型
                                                    ↓
                                              liangyi_engine.learn_from_cases()
                                                    ↓
                                              对比学习 & 元路由

ACL 权限控制:
  agent_a:        发布 + 读取
  agent_b:        发布 + 读取
  bcrm_engine:    读取 + 发布
  bcrm_sim_trader:读取 + 发布
  screen_engine:  读取 + 发布
  tavily_macro:   读取 + 发布
  a_research:     读取 + 发布

对外 API（通过 data_server.py）:
  GET /api/yijing/status     ← 当前系统状态
  GET /api/yijing/trade      ← 持仓/余额/绩效
```

### 关键配置
```
交易所:  OKX（独立账户，实盘）
API密钥: d988a164-dd4a-462d-a884-ed8a39c09e8f
入口:    scripts/memory_l4/polling_trader.py → PollingTrader 类
引擎:    scripts/memory_l4/bcrm/engine.py → BCRMEngine
OKX客户端: scripts/memory_l4/okx_simulated.py → OKXSimulatedClient
风控:    scripts/memory_l4/trading_utils.py → RiskManager
桥接:    scripts/memory_l4/ab_bridge.py（shared_memory_bus）
配置文件: .env
  OKX_API_KEY=d988a164-dd4a-462d-a884-ed8a39c09e8f
  OKX_SIMULATED=false
  OKX_DRY_RUN=false
  CONFIDENCE_THRESHOLD=0.45
  DAILY_LOSS_LIMIT=-50.0
  MAX_CONSECUTIVE_LOSSES=5
  MIN_MARGIN_USDT=10.0
  DEFAULT_MARGIN_USDT=10.0
  DEFAULT_LEVERAGE=10
  MAX_POSITIONS=3
  POLLING_INTERVAL=300
  POLLING_COINS=BTC,ETH,SOL,BNB,XRP,DOGE
  POLLING_BAR=1H
币种:    6个（BTC/ETH/SOL/BNB/XRP/DOGE）
守护进程: launchd → com.yijing.trading.plist
```

---

## 七、三层进化系统

### 架构

```
evolution_scheduler.py ← 独立调度进程（非 agent_a_runner 内部调用）
 ↓
EvolutionScheduler.run_all_evolution_checks()
  ├── A8 检验（每24H）
  │     a8_evolution.py → A8TheoryPracticeEvolution
  │     - 检验 A0-A7 理论与实践背离
  │     - 发现背离 → 提出假说 → SimpleBacktestEngine 验证
  │     - 生成进化提议（EvolutionSource.A8_THEORY_PRACTICE）
  │
  ├── 做梦部反思（每12H）
  │     dream_evolution.py → DreamOneirologyEvolution
  │     - 梦境解析：提取被系统压制的判断
  │     - 潜意识探测："想说但没说"的市场判断
  │     - 反事实推演：历史决策的替代路径
  │     - 四象限预言：乐观/中性/悲观/被忽视（各赋概率）
  │
  └── GitHub 成熟经验（每48H）
        github_evolution.py → GithubBestPracticeEvolution
        - 联网搜索高star开源交易策略
        - 提取策略参数和思路
        - 回测验证适用性
        - 生成进化提议（需联网权限）
```

### 进化生命周期

```
proposed → backtesting → observation → adopted
                      ↘ rejected
                      ↘ rolled_back
```

### 进化结果如何影响各系统

```python
# Agent A: agent_a_runner.py Step 1
evolution_params = get_evolution_params(memory)
# 含: momentum_threshold/volume_threshold/rsi_oversold/use_ema_cross 等

# Agent B: trading_memory.py 建议闭环
# gap_score → A8 进化引擎 → 参数优化建议

# Agent C: dreamos.evolution 内置引擎
# node_optimizer + gap_analyzer + lesson_distiller

# 三屏马丁: V15-CT / V9 参数通过 vol_mult 动态调整
# 易经系统: self_evolution_engine + QMM 漂移检测
```

### 当前接入状态

| 系统 | 进化接入情况 |
|------|------------|
| Agent A | ✅ 读取 `evolution_params` 用于调整规则阈值；三层进化由独立 `evolution_scheduler.py` 定时运行 |
| Agent B | ✅ `trading_memory.py` 建议闭环；治理环 gap_score → A8 |
| Agent C | ✅ DreamOS 内置 evolution 模块（gap_analyzer + node_optimizer + lesson_distiller）|
| 三屏马丁 | ✅ vol_mult 波动率自适应 + V15-CT 策略参数调优 |
| 易经系统 | ✅ self_evolution_engine + QMM漂移检测 + walk_forward滚动验证 |
| 独立进化调度 | `evolution_scheduler.py` 需独立启动，不随 agent_a_runner 自动运行 |

### 启动进化调度器
```bash
cd experiments/ab-trading
python3 evolution_scheduler.py
# 或后台运行
nohup python3 evolution_scheduler.py > logs/evolution_scheduler.log 2>&1 &
```

---

## 八、关键文件索引

### 入口文件
| 系统 | 文件 | 说明 |
|------|------|------|
| Agent A | `experiments/ab-trading/agents/agent_a_runner.py` | 9步执行流程，Hyperliquid |
| Agent B | `experiments/ab-trading/agents/agent_b_runner.py` | Dreambuddy OS 验证，Hyperliquid |
| Agent C | `experiments/agent_c/agent_c.py` | DreamOS SACG驱动，共用B账户 |
| DreamOS内核 | `1-ARCHITECTURE/dreamos/` | Python包，SACG四层 |
| 三屏调度 | `experiments/ab-trading/screen_orchestrator.py` | 三屏自主调度 |
| 三屏执行 | `experiments/ab-trading/screen_executor.py` | OKX马丁执行（V15-CT/V9/AI-V15）|
| 三屏引擎 | `experiments/ab-trading/screen_engine.py` | 三屏逻辑整合 |
| 经典执行 | `experiments/ab-trading/classic_executor.py` | ATR止损+双模式 |
| 研报加载 | `experiments/ab-trading/report_loader.py` | 周报/A1日报/A6情报 |
| 易经主程序 | `11-易经推理系统/scripts/memory_l4/polling_trader.py` | PollingTrader轮询交易 |
| 易经引擎 | `11-易经推理系统/scripts/memory_l4/bcrm/engine.py` | BCRMEngine推理引擎 |
| 易经OKX | `11-易经推理系统/scripts/memory_l4/okx_simulated.py` | OKX实盘/模拟客户端 |
| 易经桥接 | `11-易经推理系统/scripts/memory_l4/ab_bridge.py` | 共享内存总线桥接 |
| 全局调度 | `experiments/ab-trading/orchestrator.py` | 15min心跳+事件驱动 |
| 进化调度 | `experiments/ab-trading/evolution_scheduler.py` | 三层进化（独立进程）|
| 监控服务 | `experiments/ab-trading/data_server.py` | port:8765 |
| 桥接服务 | `experiments/ab-trading/bridge_server.py` | port:3847，35模块 |

### 核心模块
| 模块 | 路径 | 说明 |
|------|------|------|
| Hyperliquid执行 | `experiments/ab-trading/execution/aster_spot.py` | EIP-712签名下单 |
| LLM三级回退 | `experiments/ab-trading/core/agent_a_llm.py` | Trae→DeepSeek→规则 |
| Agent A记忆 | `experiments/ab-trading/core/agent_a_memory.py` | Lessons+大师+进化参数 |
| 意图识别 | `experiments/ab-trading/core/intent_gateway.py` | 6种意图类型（B用）|
| 链路规划 | `experiments/ab-trading/core/chain_planner.py` | 零Token四维规划（B用）|
| 链路执行 | `experiments/ab-trading/core/chain_router.py` | 动态节点执行（B用）|
| S层意图引擎 | `experiments/ab-trading/core/intent_engine/` | LLM增强意图识别 |
| 图编排器 | `experiments/ab-trading/core/graph_orchestrator.py` | BAC三层编排 |
| 图存储 | `experiments/ab-trading/core/g_graph_storage/` | 压缩/扩展/历史 |
| C执行层 | `experiments/ab-trading/core/c_execution_layer/` | 动态链融合+反射 |
| 离场模块 | `experiments/ab-trading/core/exit_module.py` | L1/L2/L3三层离场 |
| 进化引擎 | `experiments/ab-trading/core/evolution/evolution_engine.py` | 生命周期管理 |
| A8进化 | `experiments/ab-trading/core/evolution/a8_evolution.py` | 理论实践验证 |
| 做梦部进化 | `experiments/ab-trading/core/evolution/dream_evolution.py` | 潜意识反思 |
| GitHub进化 | `experiments/ab-trading/core/evolution/github_evolution.py` | 联网学习 |
| 回测引擎 | `experiments/ab-trading/core/evolution/backtest_engine.py` | 进化提议验证 |
| 交易记忆 | `experiments/ab-trading/core/trading_memory.py` | 建议→验证→复盘（B用）|
| 节点注册 | `experiments/ab-trading/core/nodes/node_registry.py` | 11节点 |
| 模块注册 | `experiments/ab-trading/core/modules/module_registry.py` | 35模块 |

### DreamOS 核心
| 模块 | 路径 | 说明 |
|------|------|------|
| S层意图 | `dreamos/core/sense/intent_engine.py` | 三级识别器（规则/LLM/动态）|
| A层编排 | `dreamos/core/arrange/graph_planner.py` | 图规划+预算分配 |
| C层执行 | `dreamos/core/compute/graph_executor.py` | 节点执行+反射 |
| G层存储 | `dreamos/core/graph_store/store.py` | 状态+压缩+历史 |
| 节点库 | `dreamos/nodes/` | 16个交易节点（A系列8个 + C系列3个 + F系列5个）|
| 注册表 | `dreamos/registry/node_registry.py` | 节点注册发现 |
| 适配器 | `dreamos/adapters/` | Skill/Function/API三种适配器 |
| 预算管理 | `dreamos/budget/` | 全局预算+成本跟踪 |
| 进化引擎 | `dreamos/evolution/` | gap分析+节点优化+Lesson蒸馏 |
| TradingAgent | `dreamos/apps/trading_agent/agent.py` | SACG全链路应用+预算管理 |
| CLI | `dreamos/cli/` | REPL + 命令行工具 |

### 易经系统核心
| 模块 | 路径 | 说明 |
|------|------|------|
| BCRM主引擎 | `scripts/memory_l4/bcrm/engine.py` | 矛盾→阴阳→四象→八卦→六十四卦 |
| 易经引擎 | `scripts/memory_l4/bcrm/yijing_engine.py` | 六十四卦推理 |
| 两仪引擎 | `scripts/memory_l4/bcrm/liangyi_engine.py` | 阴阳二气识别 |
| 八卦引擎 | `scripts/memory_l4/bcrm/bagua_engine.py` | 八卦状态分类 |
| 回测门禁 | `scripts/memory_l4/bcrm/backtest_gate.py` | 策略验证门禁 |
| 策略多样性 | `scripts/memory_l4/bcrm/strategy_diversity.py` | 多策略评估 |
| QMM引擎 | `scripts/memory_l4/qmm/engine.py` | 质量度量+漂移检测 |
| 轮询交易器 | `scripts/memory_l4/polling_trader.py` | 主交易循环 |
| OKX客户端 | `scripts/memory_l4/okx_simulated.py` | 实盘/模拟下单 |
| 风控工具 | `scripts/memory_l4/trading_utils.py` | RiskManager+PerformanceTracker |
| 共享内存总线 | `scripts/memory_l4/shared_memory_bus.py` | 跨系统通信 |
| 对外桥接 | `scripts/memory_l4/ab_bridge.py` | AB系统桥接 |

### SKILL 文件
| SKILL | 路径 | 使用方 |
|-------|------|--------|
| Agent A 交易大师 | `experiments/ab-trading/skills/agent-a-trading/SKILL.md` | Agent A LLM提示词 |
| 三屏马丁交易 | `experiments/ab-trading/skills/screen-martin-trading/SKILL.md` | 三屏系统 |
| Dreambuddy OS | `1-ARCHITECTURE/skills/dreambuddy-os/SKILL.md` | Agent B |

### 数据目录
```
experiments/ab-trading/data/
  agent_a_memory.json         ← Agent A 记忆（Lessons/大师/进化参数）
  agent_a_llm_quota.json      ← Agent A LLM每日配额
  agent_b_memory.json         ← Agent B 记忆
  agent_b_graph.json          ← Agent B 图压缩记录
  agent_c_b/                  ← Agent C 历史决策
  screen_trade_state.json     ← 三屏马丁交易状态
  screen_orchestrator_state.json ← 三屏调度状态
  screen_llm_quota.json       ← 三屏LLM配额
  evolution/
    a_evolution_pool.json     ← Agent A 进化提议池
    a_evolution_history.json  ← 历史进化记录
    dream_journal.json        ← 做梦部日志
    a8_inspection_log.json    ← A8检验日志
    github_search_log.json    ← GitHub搜索日志
  orchestrator_state.json     ← 调度状态
  decision_logs/              ← 决策日志
A系列研报/
  周报/screen1_*.md            ← Screen1 战略参考
  A1研报/a1_regime_*.json      ← Screen2 战术参考
  A6研报/*.md                  ← Screen3 情报参考
logs/                          ← 各系统运行日志

11-易经推理系统/data/
  okx_sim/config.json          ← OKX兜底配置
artifacts/
  trading/                     ← 交易产物
  memory/                      ← 记忆产物
  evolution/                   ← 进化产物
```

### 环境变量配置

**AB实验（experiments/ab-trading/config/.env）**:
```bash
# Hyperliquid 账户
AGENT_A_ASTER_USER=0x93842F1ea62E7E3c71494d9EA69EfC4F2D6e9934
AGENT_A_ASTER_SIGNER=...
AGENT_A_ASTER_SIGNER_PRIVATE_KEY=...
AGENT_B_ASTER_USER=0x6632da9c91A959eEBf1343f8AFAbf2807414004A
AGENT_B_ASTER_SIGNER=...
AGENT_B_ASTER_SIGNER_PRIVATE_KEY=...

# OKX 三屏马丁
SCREEN_OKX_PROFILE=screen_trade
OKX_API_KEY=5af4066c-ccad-45b7-8205-ebaf1d08930a
OKX_SECRET_KEY=0B3334CB7E98B039BAE11D9A914FC7C2
OKX_PASSPHRASE=Zjt@199107293419

# LLM
TRAE_API_KEY=...                        # Agent A 优先使用
TRAE_MODEL=claude-sonnet-4-5
DEEPSEEK_API_KEY=...                    # Agent A/B 备用
TAVILY_API_KEY=...                      # 搜索/A1研报

# LLM 配额
AGENT_A_TRAE_DAILY_LIMIT=12
AGENT_A_DEEPSEEK_DAILY_LIMIT=24
SCREEN_LLM_DAILY_LIMIT=12

# 三屏马丁策略
SCREEN_STRATEGY_MODE=v15_ct
SCREEN_AUTO_EXECUTE=true
MIN_MARGIN_USD=20
DEFAULT_LEVERAGE=10

# 运行模式
AUTO_EXECUTE=true
PER_TRADE_PCT=0.05
INITIAL_CAPITAL=10000
```

**易经系统（11-易经推理系统/.env）**:
```bash
# OKX 独立账户
OKX_API_KEY=d988a164-dd4a-462d-a884-ed8a39c09e8f
OKX_SECRET_KEY=1403C63E5E096D418AA2A52B137B97CC
OKX_PASSPHRASE=Zjt@199107293419
OKX_BASE_URL=https://www.okx.com
OKX_SIMULATED=false
OKX_DRY_RUN=false

# LLM
DEEPSEEK_API_KEY=sk-xxxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
TAVILY_API_KEY=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

# 风控
CONFIDENCE_THRESHOLD=0.45
DAILY_LOSS_LIMIT=-50.0
MAX_CONSECUTIVE_LOSSES=5
DEFAULT_POSITION_PCT=0.10
MIN_MARGIN_USDT=10.0
DEFAULT_MARGIN_USDT=10.0
DEFAULT_LEVERAGE=10
MAX_POSITIONS=3

# 轮询
POLLING_INTERVAL=300
POLLING_COINS=BTC,ETH,SOL,BNB,XRP,DOGE
POLLING_BAR=1H
INITIAL_EQUITY=100.0
```

---

## 附：系统关系图

```
                    ┌──────────────── AB对比实验 ──────────────────────────┐
                    │                                                      │
         Agent A               Agent B                  Agent C           │
        (LLM原生)           (Dreambuddy框架)           (DreamOS内核)       │
   Jesse Livermore风格       意图→动态链→节点           SACG四层            │
   Trae→DeepSeek→规则        图压缩+记忆闭环           NodeRegistry        │
   进化系统(独立调度)        三环架构治理                AdapterFramework    │
         │                       │                         │              │
         └───────────── Hyperliquid 执行层（aster_spot.py）────────────────┘

   ┌──────────────────── 独立交易系统 ───────────────────────────┐
   │                                                             │
   │       三屏马丁交易系统                  易经推理交易系统      │
   │  Screen1 ← 周报(AI/降级=经典TA)    BCRM推理引擎              │
   │  Screen2 ← A1日报(AI/V15-CT/V9)    矛盾→阴阳→四象→八卦→64卦  │
   │  Screen3 ← A6情报+经典指标执行     PollingTrader轮询         │
   │  四级降级: AI→AI-V15→V15-CT→V9    QMM质量度量+漂移检测      │
   │  OKX 合约马丁策略（20U保证金起）   OKX 实盘（10U保证金起）   │
   │  6币种 (BTC/ETH/SOL/BNB/DOGE/XRP)  6币种 (BTC/ETH/SOL/BNB/XRP/DOGE) │
   │  profile=screen_trade              独立账户                  │
   └─────────────────────────────────────────────────────────────┘

   ┌──────────────────── 进化系统（独立调度）────────────────────┐
   │  evolution_scheduler.py（独立进程）                          │
   │  ├── A8 理论实践验证（24H）→ 检验理论与实践背离              │
   │  ├── 做梦部外部反思（12H）→ 潜意识视角+四象限预言            │
   │  └── GitHub成熟经验搜索（48H）→ 联网学习+回测验证            │
   │  进化结果 → memory.evolution.adopted_params → Agent A读取    │
   │  Agent B: trading_memory + gap_score → A8                   │
   │  Agent C: dreamos.evolution 内置引擎                        │
   │  三屏马丁: vol_mult 波动率自适应                             │
   │  易经系统: self_evolution_engine + QMM漂移检测               │
   └──────────────────────────────────────────────────────────────┘

   ┌──────────────────── 基础设施 ──────────────────────────────┐
   │  data_server.py    :8765  统一监控 API（A/B/C/三屏/易经）   │
   │  bridge_server.py  :3847  TS桥接（35模块+11节点，FastAPI）  │
   │  orchestrator.py          15min调度（A/B公用）              │
   │  前端 Next.js      :3000  主前端仪表盘                      │
   │  经典指标系统      :8092  ml_trade_service.py（Flask）      │
   │  基本面系统        :9094  待 Python 3.11 启动               │
   └────────────────────────────────────────────────────────────┘
```
