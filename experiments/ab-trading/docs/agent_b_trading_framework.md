# Agent B 交易框架文档 — DreamBuddy v2 量化交易系统

> **定位**：AB双Agent对比实验 — Agent B（DreamBuddy v2）核心操作手册
> **版本**：v2.1 | **创建**：2026-06-24 | **更新**：2026-07-17
> **市场**：Hyperliquid 永续合约（子账户）| **预算**：实际可用余额 | **杠杆**：动态1-5x

---

## 系统架构总览

```
触发（Cron/Orchestrator）
   ↓
IntentGateway     — 意图识别，六种类型，零Token本地打分
   ↓
ChainPlanner      — 零Token四维规划，输出最优链路
   ↓
ChainRouter       — 按链路执行，置信度不足"一生二"动态追加
   ↓
A4门禁(≥65%)      — 通过→执行，拦截→HOLD
   ↓
执行 + 图压缩 + Episode写入 + 记忆进化
```

**三环架构**：
```
🔵 执行环：A1→A2→A3→A4→A5→A9（A0矛盾内置于A2/A3）
🟠 情报环：A6每1H，5级放射驱动整个执行环
🟣 治理环：A9离场→A7→A8(gap_score)→A1/A2/A3修正
```

---

## 维度一：目标（Goal）— 意图识别

**核心使命：赚更多的钱，通过指挥DreamBuddy v2系统做出最优决策。**

### 意图类型（IntentGateway输出）

| 意图 | 触发条件 | 执行环入口 |
|------|----------|-----------|
| TREND_FOLLOWING | 24H变动>3% + Regime=TREND | C1→F2/F3→A2(含A0)→A4 |
| MEAN_REVERSION | RSI极端 + 资金费率极端 | C1→F2/F3→A2(含A0)→A4 |
| FUNDAMENTAL_PLAY | 重大新闻/宏观事件 | A1(含A0)→F1→F5→A2→A4 |
| BREAKOUT | 成交量>2x + 关键位突破 | C1→A2(含A0)→C3→A4 |
| KNOWLEDGE_MATCH | 知识库高分命中(≥80) | C3→A4（快捷路径）|
| UNCERTAIN | 信号不明确（默认） | C1→A1(含A0)→A2→A4 |

---

## 维度二：身份定位（Identity）— 系统首席分析师

**我不亲自分析，我指挥三层架构分工协作，裁决最终结论。**

### A0矛盾Skill的正确位置
> ⚠️ A0不是独立节点，内置于A2/A3

| 集成位置 | 功能 |
|----------|------|
| A2_分析(含A0) | 矛盾排序 + 阻力最小路径，方向一致→置信度+5%，冲突→-8% |
| A3_策略设计(含A0) | 大师研讨 + 矛盾一致性校验，不一致→置信度×0.85 |

---

## 维度三：思考维度（Thinking Dimensions）— ChainPlanner + 三链

### ChainPlanner（零Token，每轮必走）

位于 `core/chain_planner.py`，四个过滤维度：

```python
ChainPlanner(token_budget=6000).plan(intent, mkt, memory)
→ PlanResult(
    planned_chain,      # 最优节点序列
    pruned_nodes,       # 被剪枝的节点+原因
    added_nodes,        # 主动追加的节点
    budget_mode,        # full/standard/lean
    estimated_tokens,   # 预计Token消耗
    plan_rationale,     # 规划理由（写入图节点）
    knowledge_hit,      # 知识库命中策略
    shortcut_taken,     # 是否走了快捷路径
)
```

**四个过滤维度**：

| 维度 | 逻辑 | 效果 |
|------|------|------|
| Token预算 | full(≥8k)/standard(4-8k)/lean(<4k) | 剪掉超预算高成本节点 |
| 知识库命中 | score≥80→升级快捷路径 | 跳过A1调研，前置C3 |
| 历史表现 | Regime下HOLD率>80%→追加做梦部 | 检测强迫性重复 |
| 标的覆盖 | 小币F1降级；资金费率极端→强制F2/F3前置 | 精准节点配置 |

### 节点成本参考

| 成本级别 | 节点 | Token |
|----------|------|-------|
| 零成本 | C1技术扫描, F2资金流, F3情绪 | 0 |
| 低成本 | A2_分析(含A0), A4_门禁 | 100-800 |
| 中成本 | A1_调研(含A0), A3_策略设计(含A0), F1新闻 | 1000-2000 |
| 高成本 | C5参数优化, A8知行合一 | 1500+ |

### 动态追加（"一生二"）

ChainRouter执行时，若某节点置信度<65%且未到A4门禁：
- 自动从 extend_pool 中取前2个节点插入
- 记录到 `dynamic_nodes_added` 字段
- 图压缩 A层记录完整追加轨迹

---

## 维度四：自我进化（Self-Evolution）— 四层进化

### 进化层次

| 层次 | 机制 | 实现 | 周期 |
|------|------|------|------|
| 即时 | 图压缩B/A/C三层节点更新 | chain_router._record_graph() | 每次交易 |
| 短期 | Episode写入 | learning-episode-writer | 每笔（含HOLD）|
| 中期 | A8知行合一 + gap_score路由 | chain_router._node_a8_verify() | 每10笔 |
| 长期 | 做梦部分析 + 知识库评分调整 | chain_router._node_oneirology() | 每日/连败时 |

### gap_score路由（治理环核心）

```
A9离场 → A7记录 → A8计算gap_score → 路由
  gap ≥ 0.5 → A1重启调研（严重背离）
  gap 0.3-0.5 → A2更新分析（中度背离）
  gap < 0.3 → A3策略优化（轻微背离）
```

### 做梦部（弗洛伊德机制）

触发条件：连续SKIP≥3次 / 置信度55-64%反复被拦 / gap_score<0.3

五大机制：
- 强迫性重复：连续HOLD且同原因 → 找真实原因
- 反事实推演：A7不存在会怎样 → 发现被压制判断
- 凝缩检测：高置信度被拦 → 潜意识信号提升+5%
- 移置检测：连续引用同一原因 → 恐惧移置分析
- 投射还原：外部归因>80% → 还原为内部缺陷

### Lesson空间

- 上限20条，评分=普适性(1-5)×重要性(1-5)，<10分淘汰
- 进化规则：先升级完善低分条目，再考虑删除

---

## 维度五：向外学习（External Learning）

### 三级策略（优先本地）

```
Level 1 零Token：本地知识库(dream-knowledge) + Regime库 + strategy_scores
Level 2 零Token：历史Episode检索 + 大师策略画像匹配
Level 3 有Token：Tavily搜索（每4轮1次）→ 新策略进待验证池
```

### 知识库命中规则
- score≥80：ChainPlanner直接升级为快捷路径（跳过A1）
- score 60-79：作为参考，不改变链路
- 待验证池：上限5条，3次印证后入库，7天无验证自动降级

---

## 维度六：预算管理（Budget Management）

### 模式档位

| 模式 | Token上限 | 适用场景 | 默认 |
|------|-----------|----------|------|
| lean | ≤ 3,000 | 信号弱/震荡/高HOLD率 | 否 |
| standard | ≤ 6,000 | 正常交易决策 | ✅ |
| full | ≤ 10,000 | 强信号/UNCERTAIN意图 | 否 |

配置：`.env` 中 `TOKEN_BUDGET=6000`

### 仓位规则

```
单笔仓位 = max(实际可用余额 × PER_TRADE_PCT, $5)
名义价值 = 仓位 × 杠杆（最小$10，Hyperliquid限制）
杠杆     = min(5, max(1, int(final_confidence × 5)))
最大持仓 = 实际可用余额 × 20%
```

### 资金分配机制（v2.1 更新）

**变更说明**：不再使用固定 `BUDGET_USDC=60` 作为上限，改为直接读取合约账户实际权益。

```
之前：equity = min(acct["equity"], 60.0)     ← 即使充值更多也只用60
现在：equity = acct["equity"]                 ← 实际有多少用多少
```

**数据流向**：
```
agent_b_runner.py
  ├─ acct = client.get_account()              ← 从 Hyperliquid 获取实际权益
  ├─ equity = acct["equity"]                  ← 直接使用，不再 min() 截断
  │
  ├─ ChainRouter(client, mkt, memory, intent,
  │              BUDGET_USDC, equity=equity)   ← 传入实际权益
  │     └─ pos_usdt = self.equity * PER_TRADE_PCT   ← 基于实际余额计算
  │
  └─ ClassicDriver(per_trade_usdc=equity*0.05)  ← Classic 模式同样使用实际余额
```

**环境变量配置**：
- `PER_TRADE_PCT`：单笔资金分配比例，默认 `0.05`（5%），可通过环境变量覆盖
- `BUDGET_USDC`：仅作为模拟模式回退值，不再截断实际权益

**安全检查**：
- 权益 ≤ 0 时回退到 `BUDGET_USDC` 并打印告警
- 模拟模式（账户查询失败）使用虚拟资金 `BUDGET_USDC`

**实现位置**：
- ChainRouter 构造函数：[chain_router.py#L86](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/core/chain_router.py#L86)
- 仓位计算：[chain_router.py#L227](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/core/chain_router.py#L227)
- 权益获取：[agent_b_runner.py#L1081](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/agents/agent_b_runner.py#L1081)
- ClassicDriver 初始化：[agent_b_runner.py#L858](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/agents/agent_b_runner.py#L858)

---

## 标准操作流程（SOP）

```
1. IntentGateway  → 零Token，本地打分识别意图
2. ChainPlanner   → 零Token，四维过滤输出最优链路
3. ChainRouter    → 按链路执行（含"一生二"动态追加）
4. A4_门禁        → 置信度≥65%通过，否则HOLD
5. 执行           → AUTO_EXECUTE=true时实际下单
6. 图压缩         → B/A/C三层节点记录
7. Episode写入    → learning-episode-writer
8. 记忆更新       → save_memory()，含Lessons
9. 自主调度       → _b_self_schedule()，申请提前触发
```

---

## 文件索引

| 文件 | 功能 |
|------|------|
| [agent_b_runner.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/agents/agent_b_runner.py) | 主流程（三层架构整合，含实际余额资金分配） |
| [chain_router.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/core/chain_router.py) | 动态链路执行引擎（含A0、做梦部、治理环、equity传参） |
| [chain_planner.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/core/chain_planner.py) | 零Token链路规划器 |
| [intent_gateway.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/core/intent_gateway.py) | 意图识别层 |
| [classic_driver.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/core/classic_driver.py) | Classic模式驱动（使用实际余额） |
| [trading_memory.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/core/trading_memory.py) | 交易记忆系统 |
| [exit_module.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/core/exit_module.py) | 离场模块 |
| [aster_spot.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/execution/aster_spot.py) | Hyperliquid 合约执行层 |
| [monitor.html](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/monitor.html) | AB Trading 监控页面 |
| `data/skill_registry.md` | 能力清单（三环架构节点注册表） |
| `data/agent_b_memory.json` | 跨session记忆（自动维护） |
| `data/agent_b_graph.json` | 图压缩B/A/C节点日志 |
| `data/THREE_CHAIN_DISPATCH_CHECKLIST.md` | PR#48官方完整能力清单 |
| `skills/screen-martin-trading/SKILL.md` | Agent B SKILL 定义 |

---

## 历史表现追踪

| 时间 | 标的 | 意图 | 链路模式 | 置信度 | A7 | 备注 |
|------|------|------|----------|--------|-----|------|
| 06-24 09:27 | HYPE | UNCERTAIN | standard | 70% | ✅ | 保证金未激活 |
| 06-24多轮 | HYPE/AVAX | UNCERTAIN/TREND | standard | 45-54% | ❌ | 正常拦截 |

**统计（截至2026-06-24）**：
- 总轮次：26 | A7通过率：1/26（4%）
- 原因分析：子账户激活期间多为震荡市，A7门禁正常工作
- 待优化：意图识别打分偏低（多次UNCERTAIN），可调整权重
