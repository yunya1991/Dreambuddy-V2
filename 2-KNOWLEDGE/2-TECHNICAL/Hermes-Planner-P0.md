# Hermes-Planner 调度器 (P0: Cost Keeper + Skip Gate)

> **一句话定义**：Hermes-Planner 是 Dream Universal Gateway 的轻量运行时调度器 —— 在不重构既有业务链路的前提下，以 Feature Flag 控制的方式介入 `POST /api/chat` 的执行路径，**追踪 token 用量并跳过不必要的步骤**，核心 KPI 是：**最省 Token · 最优路径**。
>
> 当前版本：**P0（已上线）** · Feature Flag：`USE_SCHEDULER=true/false` · 默认关闭。

---

## 1. 动机与问题陈述

Dream Universal Gateway 的当前消息处理链固定且昂贵：

| 典型请求（"分析 BTC 现在走势"） | 执行内容 | 成本量级 |
|---|---|---|
| Intent 识别 | callDeepSeekAPI × 1 | ~500 tokens |
| 知识库检索 | getKnowledgeContext (文件 IO + 文本切片) | ~300 tokens 注入 |
| S1 调研 / S2 分析 / S3 设计 | callDeepSeekAPI × 3 | 每个 ~800-1500 tokens |
| S4 验证（若开启） | callDeepSeekAPI × 1 + 策略引擎桥接 | ~1000 tokens |
| 市场数据获取 | HTTP / CLI 拉取行情 | 0 LLM tokens，但有延迟 |

**痛点**：

1. **固定路径 —— 所有请求都走完整链路**：一句"你好"也要经过 S1→S2 推理，浪费 token
2. **黑盒成本 —— 无法按请求/意图/步骤查看 token 分布**：优化没有数据支撑
3. **缺乏预算保护 —— 复杂对话可能在单次请求内烧掉数千 token**

P0 的目标不是重写链路，而是**先把"成本可观测 + 步骤可跳过"这两件事做好**，为后续 P1（语义路由 / 动态路径）打基础。

---

## 2. 范围与边界

### P0 在做的事

- ✅ 每次请求的 Token 用量按**步骤**维度记录（"S1 用了多少 · S2 用了多少"）
- ✅ 每次请求按 **意图 + 复杂度** 设置 token 预算上限，达到上限时在日志中标记
- ✅ 请求结束生成结构化报告（总 tokens / 每步明细 / 跳过的步骤）并附加到响应 `cost_report`
- ✅ 轻量启发式 `Skip Gate`：按用户输入 + 意图 + 复杂度判一个步骤是否要跳过或走精简模式
- ✅ 完全由 `USE_SCHEDULER` 环境变量控制，关闭时对业务逻辑零影响（no-op）
- ✅ 异常路径同样执行 cleanup，避免 `Map` 泄漏

### P0 **不做**的事（留给后续阶段）

- ❌ 动态生成执行链（DAG / 多意图组合路由）—— 目前仅跳过/简化，不新增路径
- ❌ LLM 自身的"要不要执行"推理判断（那是 P1 Semantic Router 的范畴）
- ❌ 把报告持久化到数据库（目前只 log + 返回 payload；后续可接监控系统）
- ❌ 真正的"熔断"（达到 budget 时只打 log，不主动中断后续步骤）
- ❌ 按用户/会话维度的长期预算管理

---

## 3. 代码架构

```
src/lib/scheduler/          ← 调度器本体（纯逻辑，无外部依赖，可独立测试）
├── index.ts                ← 统一入口，暴露公共 API + 版本号
├── cost-keeper.ts          ← Cost Keeper（会话级 token 追踪器）
└── skip-gate.ts            ← Skip Gate（轻量启发式步骤旁路判断）

src/app/api/chat/route.ts   ← 集成点（三处接入点 + 一个 Feature Flag）
```

### 3.1 接入方式总览（3 处）

所有接入均由 `SCHEDULER_ENABLED = (process.env.USE_SCHEDULER === 'true')` 守护：

**① CostKeeper 生命周期**（POST handler 顶部 & 底部）

```
request 进来  →  initCostKeeper(chatTraceId, 'pending', 'moderate')
                  ... 业务逻辑（callDeepSeekAPI / executeStepWithSkill）
                  generateReport(chatTraceId)  →  挂到 response.cost_report
                  cleanupSession(chatTraceId)
exception 路径  →  cleanupSession(chatTraceId)  防御性清理
```

**② callDeepSeekAPI 的 tracking 参数**（每一次 LLM 调用处）

函数新增可选第三个参数 `tracking?: { sessionId, stepId, stepName }`。当提供时：
- 进入函数 → `markStepStart(sessionId, stepId, stepName)`
- API 返回 → `markStepEnd(sessionId, stepId, stepName, { promptTokens, completionTokens }, 'llm')`
- 如果 API 不返回 `usage` 字段 → fallback 到 `estimateTokens` 粗估

**③ executeStepWithSkill 的 Skip Gate**（循环步骤内）

在每步执行前：
```
shouldSkipStep(step as StepName, userInput, intent, complexity)
  → 若 skip → markStepSkipped(sessionId, step, step, reason)
              返回 "**step: 已跳过**（reason）" 占位
  → 若不 skip → 正常执行，并由内部 callDeepSeekAPI 的 tracking 负责记录
```

### 3.2 数据结构

**CostKeeper 会话状态（src/lib/scheduler/cost-keeper.ts）**

```
sessionStates: Map<sessionId, {
  config: CostKeeperConfig,        // 含 enabled / defaultBudgetTokens / budgetsByComplexity
  intent: string,                   // 'market_query' | 'deep_analysis' | ...
  complexity: 'simple'|'moderate'|'complex',
  steps: StepTokenRecord[],         // 每步明细
  skippedSteps: string[],           // 被跳过的步骤 + reason
  totalTokens: number,              // 累计
  budgetTokens: number,             // 本请求预算（按 complexity 查表）
  terminated: boolean,              // 是否触达预算（仅日志，不主动中断）
  createdAt: number,
}>
```

**StepTokenRecord**

```typescript
{
  stepId, stepName,                        // 步骤标识
  promptTokens, completionTokens, totalTokens,
  latencyMs,                               // 耗时
  skippedByGate: boolean, skipReason?,     // 若是 Skip Gate 跳过
  moduleType: 'llm' | 'market' | 'rag' | 'strategy_engine' | 'other',
}
```

**Skip Gate 的判断源（src/lib/scheduler/skip-gate.ts）**

```typescript
judgeStep({
  userInput,           // 原始消息文本
  intent,              // 'market_query' | 'simple_qa' | 'deep_analysis' | ...
  complexity,          // 'simple' | 'moderate' | 'complex'
  sessionId,
  previousStepOutput?, // 已有上下文长度
  currentStep,         // 'S1_RESEARCH' | 'MARKET_DATA' | 'STRATEGY_ENGINE' | ...
  symbolsFoundInInput, // 从输入提取的 BTC / ETH / 黄金等资产名
})
```

### 3.3 STEP_META（步骤元信息表）

`STEP_META` 是 Skip Gate 的核心静态配置表，每条记录描述**一个步骤在什么情况下必需**。当前已注册的 step：

| step | 说明 | 典型触发词 |
|---|---|---|
| `MARKET_DATA` | 实时行情获取（0 LLM tokens，但有延迟） | "btc", "eth", "gold", "价格", "支撑", "阻力"… |
| `RAG_KNOWLEDGE` | 知识库向量检索（~50-300 tokens 注入） | 概念解释类请求通常不跳过 |
| `STRATEGY_ENGINE` | Python 策略回测引擎（0 LLM tokens） | "回测", "验证", "策略"… |
| `S1_RESEARCH` | S1 调研（500-1500 tokens） | 通常用于深分析/策略决策链 |
| `S2_ANALYSIS` | S2 分析（500-1500 tokens） | 同上 |
| `S3_DESIGN` | S3 策略设计（500-1500 tokens） | 设计策略/落地建议 |
| `S4_VALIDATE` | S4 验证（最昂贵，含 Python 桥接） | "验证"/"回测"/"风险评估" |
| `S5_EXECUTE` | S5 执行计划（仅真正需要交易操作时启用） | "开仓"/"买入"/"执行" |
| `USER_PREFERENCE_MEMORY` | 用户偏好记忆注入（~100 tokens） | 个性化场景 |

每个 step 的 `intentBlacklist`（强跳过）与 `requiredWhen`（强执行）字段构成 Skip Gate 的核心信号源。

---

## 4. 关键流程走一遍

以请求 `{"message": "你好", "session_id": "u_123"}` 为例（预期走 simple_qa）：

```
(1) POST 入口
    chatTraceId = 'chat_171819_XYZ'
    USE_SCHEDULER=true  →  initCostKeeper(chatTraceId, 'pending', 'moderate')

(2) 意图识别 recognizeIntent
    → recognizeIntentLLM 调用 callDeepSeekAPI（无 tracking，不走 CostKeeper）
      注：P0 目前只在 S 系列步骤的 callDeepSeekAPI 中传 tracking；
          intent recognition 本身不计入步骤追踪，留作 P1 优化项
    → 返回 { intent: 'simple_qa', complexity: 'simple', confidence: 0.9 }

(3) 路由 routing
    → chain = ['direct_answer']

(4) generateChainResponse(chain=['direct_answer'], ...)
    → 进入 executeStepWithSkill(step='direct_answer',
                                schedulerContext={ userInput:'你好',
                                                    intent:'simple_qa',
                                                    complexity:'simple' })
       ├─ Skip Gate 判断：
       │    - 'direct_answer' 不是 STEP_META 中已知 step
       │    - judgeStep 返回 decision='execute', confidence='low'
       │    → 默认执行（不跳过）
       │
       └─ 因为 S 系列检查 (step.startsWith('S')) 不匹配，
          走静态响应（或 fallback 路径）

(5) 响应收尾
    generateReport(chatTraceId) → { totalTokens: 0, steps: [], skippedSteps: [], … }
    cleanupSession(chatTraceId)
    return NextResponse.json({ …, cost_report: {...} })
```

**一个更能体现价值的例子**：`"什么是布林带？"`

- Intent → `concept_explain`（概念解释）
- 路由 chain 可能包含 MARKET_DATA、RAG_KNOWLEDGE、S1_RESEARCH…
- Skip Gate 判断：
  - MARKET_DATA → 用户没提到具体资产/价格关键词 → **skip**（**~0 tokens**）
  - STRATEGY_ENGINE → 用户没提"回测/验证" → **skip**
  - S1_RESEARCH → intent `concept_explain` 在 intentBlacklist → **skip**
  - 实际只保留 RAG_KNOWLEDGE + LLM 回答（原本固定链路可能烧掉 3k+ tokens，现压缩到 1k- 内）

---

## 5. 公共 API 速查

所有 API 均从 `@/lib/scheduler` 导出：

| API | 说明 |
|---|---|
| `initCostKeeper(sessionId, intent, complexity, customConfig?)` | 请求开始调用，初始化预算 |
| `markStepStart(sessionId, stepId, stepName)` | 标记步骤开始计时（由 callDeepSeekAPI 内部调用） |
| `markStepEnd(sessionId, stepId, stepName, {promptTokens, completionTokens, totalTokens?}, moduleType)` | 步骤结束 & 记录 token |
| `markStepSkipped(sessionId, stepId, stepName, reason)` | 记录被跳过的步骤 |
| `shouldTerminate(sessionId): boolean` | 是否已达到预算（目前仅打 log，不主动中断） |
| `getCurrentUsage(sessionId)` | 返回 { used, budget, percentage, stepCount } |
| `generateReport(sessionId): CostKeeperReport` | 生成结构化报告（含每步明细） |
| `cleanupSession(sessionId)` | 请求结束必须调用（防御性清理） |
| `estimateTokens(text: string)` | 当 API 不返回 usage 时的粗估器 |
| `PLANNER_VERSION` | `"0.1.0 (P0: CostKeeper + SkipGate)"` |
| `judgeStep(ctx: GateContext): SkipJudgment` | Skip Gate 单步细判 |
| `shouldSkipStep(step, userInput, intent, complexity)` | route.ts 中更易用的一行 API |
| `judgeAllSteps(userInput, intent, complexity, sessionId)` | 一次生成所有步骤的执行建议（用于调试/前端展示） |

---

## 6. 开关与配置

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `USE_SCHEDULER` | false | 全局 Feature Flag。**设置为 `true` 才启用 Cost Keeper + Skip Gate** |
| `SCHEDULER_BUDGET_TOKENS` | 5000 | 默认预算（当 complexity 未命中 budgetsByComplexity 表时使用） |

**budgetsByComplexity 内置默认**：

```
simple:   1200    （简单问答，~1 次 LLM 调用）
moderate: 3500    （中等分析，~2-3 次 LLM）
complex:  8000    （完整策略链，S1-S5 全链路）
```

**在请求响应中查看 P0 效果**：当 `USE_SCHEDULER=true` 时，返回 payload 的 `data.cost_report` 形如：

```json
{
  "totalTokens": 1248,
  "promptTokens": 820,
  "completionTokens": 428,
  "skippedSteps": [
    "MARKET_DATA: 用户输入未提到任何具体资产（BTC/ETH/黄金等），无需获取实时行情或回测",
    "STRATEGY_ENGINE: 同上"
  ],
  "budgetTokens": 1200,
  "status": "ok"
}
```

---

## 7. 观测 & 调试

### 7.1 日志关键词

```
[Hermes-Planner] P0 Scheduler ENABLED: CostKeeper + SkipGate    // 启动时
[Hermes-Planner] CostKeeper initialized: session=...             // POST 入口
[Hermes-Planner] session=... | total=1248/3500 | skipped=2 steps // 请求结束
[CostKeeper] Step end: S1_RESEARCH | 824 tokens | 1423ms | ...   // 每步明细（verbose 级）
[SkipGate] SKIP MARKET_DATA: 用户输入未提到任何具体资产...       // 跳过步骤时
```

### 7.2 调试提示

- 关闭 scheduler → `USE_SCHEDULER=false`（或不设置），所有接入点都成 no-op
- 想强制跳过某步骤以验证 → 临时在 `STEP_META[step].intentBlacklist.push('your_intent')` 加一条
- 想看每步 token 明细 → 在 `initCostKeeper` 的 customConfig 中传 `logLevel: 'verbose'`
- 想改单请求预算 → 在 customConfig 中覆盖 `defaultBudgetTokens` 或某 complexity 预算

---

## 8. 已知限制 & 后续演进路径

### 8.1 已知限制

| 项 | 状态 | 备注 |
|---|---|---|
| 调度器目前是**进程内 Map** | P0 限制 | 多实例部署时数据不可跨实例共享；对单服务足够 |
| Skip Gate 是**纯启发式**（关键词 + 意图映射） | P0 限制 | 有一定误判，但轻量；后续可接 Embedding 相似度 |
| 预算耗尽时**只打日志不主动中断** | 设计决策 | 防止误判把用户关在门外；P1 可引入"软预算"与降级路径 |
| `callDeepSeekAPI` 的 tracking 目前**仅在 S 系列步骤处显式传入** | P0 范围 | Intent 识别、知识库相关不统计（可在 P1 扩展） |
| `direct_answer`、`knowledge_base` 等 chain step 未在 STEP_META 中注册 | P0 范围 | 它们走默认执行（不跳过）；后续可补齐 |
| 数据未持久化 | P0 范围 | 需要观测时再引入文件 DB / 指标系统 |

### 8.2 已规划的后续阶段

- **P1 — Semantic Router / Embedding Skip Gate**：用 DeepSeek embeddings 做更准的"用户输入 ↔ 步骤必要性"匹配，替换纯关键词
- **P2 — 动态执行链**：不再使用固定 `S1_RESEARCH → S2_ANALYSIS → …`，而是按意图 + 用户上下文动态裁剪/重排
- **P3 — 多意图组合路由**：`detectCombinedIntents` / `buildCombinedChain` 已有原型，可在 P3 接入调度器做路径规划
- **P4 — 预算保护 & 指标化**：把预算耗尽真正升级为降级路径（返回静态响应），把 `cost_report` 汇总到时间序列指标

### 8.3 与 Hermes Agent 的关系

`Hermes-Planner` 是 `Hermes Agent` 的**内部运行时调度子系统**：
- `Hermes Agent` 负责：平台接入、会话管理、Skill 加载、工具调用
- `Hermes-Planner` 负责：在已有链路上做**成本可观测 + 路径优化**

两者目前通过 `src/lib/scheduler` 的纯函数接口协作，不要求 Agent 做结构性改动。

---

## 9. 为什么 P0 这样做（设计原则回顾）

| 原则 | P0 如何落地 |
|---|---|
| **Feature Flag 优先** | 所有改动以 `SCHEDULER_ENABLED` 包裹，关了就是 no-op |
| **最小侵入** | 不重构既有 callDeepSeekAPI / executeStepWithSkill 签名，仅新增可选参数 |
| **可观测** | 每步都有 structured record；请求结束有 report；console 有日志 |
| **可回滚** | 关闭 flag 后所有行为等价于上线前 |
| **渐进式** | 先把"能观测"做对 → 再在 P1/P2 做"会决策"（Semantic Router、动态链） |

> 本文档由系统在完成 P0 集成后自动归档，作为后续推进 Hermes-Planner 的设计基线。任何对调度器的后续修改都应以此文档为起点，并在修改后更新对应章节。
