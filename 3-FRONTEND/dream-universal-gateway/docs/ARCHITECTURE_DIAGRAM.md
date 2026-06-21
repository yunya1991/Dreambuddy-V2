# Dream Universal Gateway — 主前端架构图 v1.0

> 版本: v1.0 | 日期: 2026-06-20 | 适用: 主前端运营快速参考
> 说明: 本文件使用 Mermaid 格式，VS Code / GitHub / GitLab / 系统内 architecture 页面均可直接渲染

---

## 一、五层架构总览

```mermaid
flowchart TB
    subgraph L1["L1 · 用户交互层 UI Layer"]
        direction LR
        A1["💬 Chat 对话界面\n/chat"]
        A2["📊 Dashboard 仪表盘\n/dashboard"]
        A3["📋 Notebook 笔记本\n/notebook"]
        A4["🏛️ Board 审批流\n/board"]
        A5["🚀 Ops 运维\n/ops"]
        A6["🔐 Login/Register\n/login /register"]
    end

    subgraph L2["L2 · 状态管理层 State Layer"]
        direction LR
        B1["auth-store\n用户登录态"]
        B2["chat-store\n对话消息"]
        B3["notebook-store\n笔记本步骤"]
        B4["session-store\nSession ID"]
        B5["credits-store\n积分余额"]
        B6["config-store\n系统配置"]
    end

    subgraph L3["L3 · API 网关层 API Gateway"]
        direction LR
        C1["/api/chat\n主对话接口"]
        C2["/api/intent/analyze\n意图分析"]
        C3["/api/market/*\n行情数据"]
        C4["/api/config/*\n配置管理"]
        C5["/api/notebook/*\n笔记本同步"]
        C6["/api/board/*\n审批流接口"]
        C7["/api/user/*\n用户体系"]
        C8["/api/monitor/*\n监控事件流"]
    end

    subgraph L4["L4 · 意图路由层 Intent Routing"]
        direction LR
        D1["smart-router.ts\n意图 → 链映射"]
        D2["fallback-engine.ts\n四层识别:追问→LLM→规则→默认"]
        D3["intent-memory.ts\nRingBuffer 记忆库"]
    end

    subgraph L5["L5 · 执行链层 Execution Chain"]
        direction LR
        E1["strategy-chain\nS1~S5 策略链"]
        E2["dynamic-chain\n动态闭环链"]
        E3["dev-chain\n开发者E链"]
    end

    subgraph L6["L6 · 基础设施层 Infrastructure"]
        direction LR
        F1["scheduler/cost-keeper\nToken 成本控制"]
        F2["scheduler/skip-gate\n步骤智能跳过"]
        F3["compressor-adapter\n上下文压缩"]
        F4["graph-reflection-bridge\n图+自省融合"]
        F5["knowledge-loader + knowledge-rag\n知识库 RAG"]
        F6["market-data-adapter\n行情数据适配"]
    end

    L1 --> L2 --> L3 --> L4 --> L5 --> L6
```

---

## 二、核心数据流 — 一次用户消息的处理旅程

```mermaid
sequenceDiagram
    autonumber
    actor User as 用户
    participant UI as Chat UI
    participant State as chat-store
    participant API as /api/chat
    participant Intent as smart-router
    participant Memory as intent-memory
    participant Scheduler as cost-keeper
    participant Chain as chain-controller
    participant RAG as knowledge-rag
    participant SkipGate as skip-gate
    participant Reflect as graph-reflection
    participant Compressor as compressor

    User->>UI: 输入: "帮我分析 BTC 近期走势"
    UI->>State: 保存用户消息到本地
    UI->>API: POST /api/chat { message, sessionId }
    
    API->>API: ① 初始化会话 sessionId
    API->>Scheduler: initCostKeeper(sessionId, deep_analysis, moderate)
    
    API->>Intent: ② routeIntent(intent, complexity, context)
    Intent->>Memory: getRecentMemory(sessionId, 10)
    Memory-->>Intent: 返回最近10条对话
    Intent->>Intent: 四层识别: LLM→规则→默认
    Intent-->>API: mode=dynamic, chain=[S1,S2,S3,S4,S5]
    
    API->>Chain: ③ executeChain(sessionId, routingDecision)
    
    loop 执行链循环
        Chain->>Scheduler: markStepStart(sessionId, stepId)
        Scheduler-->>Chain: 返回当前用量
        
        alt 步骤是否可跳过?
            Chain->>SkipGate: shouldSkipStep(step, stepMetadatas)
            SkipGate->>Reflect: graphAwareShouldSkipStep(step, graphState)
            Reflect-->>SkipGate: skipStep=false, reason="..."
            SkipGate-->>Chain: { skipStep: false, reason }
        end
        
        alt 执行步骤（含RAG检索）
            Chain->>RAG: getKnowledgeContextSync(sessionId, query, intent)
            RAG-->>Chain: 返回知识库上下文（失败降级到 n-gram）
            Chain->>Chain: 实际调用 LLM / 外部 API
            Chain->>Scheduler: markStepEnd + tokens
            Chain->>Reflect: recordStepReflection(graphState, step, metadata)
        end
        
        alt Budget 超支?
            Scheduler->>Scheduler: shouldTerminate(sessionId)
            Scheduler-->>Chain: true → 终止后续步骤
        end
        
        alt 上下文过长?
            Chain->>Compressor: compress(payload, targetRatio=0.5)
            Compressor-->>Chain: 返回压缩后的上下文
        end
    end
    
    Chain-->>API: 步骤结果集合
    API->>Scheduler: generateReport(sessionId)
    Scheduler-->>API: 结构化报告 (tokens/steps/skipped)
    
    API->>Memory: pushMemory(sessionId, 用户消息+回复)
    API-->>UI: SSE 流式回复 (step by step) + 最终结果
    UI->>State: 更新本地消息列表
    UI-->>User: 显示对话结果 + 步骤卡片
```

---

## 三、意图路由决策树

```mermaid
flowchart TD
    A["用户输入 + 上下文\n(user_role, thinking_mode)"] --> B["intent 类型判定\n(fallback-engine.ts 四层识别)"]
    B --> C["intent = deep_analysis / scenario_sim<br/>strategy_verify / market_query / execute_trade / developer"]
    C --> D["复杂度判定<br/>(simple / moderate / complex)"]
    D --> E["smart-router 查表路由<br/>(smart-router.ts:ROUTE_MAP)"]
    
    E --> F["PRO + deep → mode=dynamic<br/>S1~S5 完整链 + 动态闭环"]
    E --> G["FREE + complex → 降级到 S1<br/>role_check=upgrade_required"]
    E --> H["thinking_mode=stepwise → mode=stepwise<br/>每步需用户确认"]
    E --> I["intent=developer → 走 E 链<br/>chain=[DEV_E_CHAIN]"]
    E --> J["market_query → S1 快速返回<br/>仅检索行情/知识库"]
    
    F --> K["执行策略链 strategy-chain"]
    G --> K
    H --> K
    I --> L["执行开发者链 dev-chain"]
    J --> M["直接检索知识库/行情并返回"]
    
    K --> N["Scheduler 全程监控 + Compressor 管理上下文"]
    L --> N
    M --> N
    N --> O["返回结构化报告 + 步骤追踪"]
```

---

## 四、基础设施协作关系（重点）

```mermaid
flowchart LR
    subgraph INFRA["基础设施层（默认全部启用）"]
        direction TB
        
        subgraph COST["成本控制"]
            CK["cost-keeper.ts<br/>┌────────────┐<br/>│ initCostKeeper │<br/>│ markStepStart  │<br/>│ markStepEnd    │<br/>│ shouldTerminate│<br/>│ generateReport │<br/>└────────────┘<br/>Token用量/预算/步骤报告"]
        end
        
        subgraph SKIP["步骤优化"]
            SG["skip-gate.ts<br/>shouldSkipStep()<br/>结合置信度/风险评分<br/>判断步骤是否可跳过"]
        end
        
        subgraph COMPRESS["上下文压缩"]
            CP["compressor-adapter<br/>compress(payload, targetRatio)<br/>文本摘要 + 图结构压缩<br/>GraphStats 保留高价值节点"]
        end
        
        subgraph GRAPH["图+自省"]
            GR["graph-reflection-bridge.ts<br/>createGraphReflectionState()<br/>graphAwareShouldSkipStep()<br/>recordStepReflection()<br/>buildGraphSummary()"]
        end
        
        subgraph RAG["知识库"]
            KL["knowledge-loader.ts + knowledge-rag.ts<br/>getKnowledgeContextSync()<br/>buildRAGContext()<br/>嵌入失败 → n-gram fallback"]
        end
    end

    subgraph CHAIN["执行链（调用者）"]
        SC["strategy-chain (S1~S5)"]
        DC["dynamic-chain"]
        DEV["dev-chain (E链)"]
    end
    
    CHAIN --"每步调用"--> CK
    CHAIN --"步骤决策"--> SG
    CHAIN --"上下文过长时"--> CP
    CHAIN --"图节点追踪"--> GR
    CHAIN --"检索知识库"--> KL
    
    SG --"结合 graph 状态"--> GR
    CP --"读取 graph 摘要"--> GR
    CK --"报告关联步骤"--> GR
```

---

## 五、S 系列步骤链详解

```mermaid
flowchart LR
    A["S1_RESEARCH<br/>(研究与检索)"]
    B["S2_ANALYSIS<br/>(数据解析与洞察)"]
    C["S3_DESIGN<br/>(策略设计与规划)"]
    D["S4_VALIDATE<br/>(验证与回测)"]
    E["S5_EXECUTE<br/>(执行与输出)"]

    A --> B --> C --> D --> E
    
    A -.->|"knowledge-rag<br/>知识库 RAG 检索"| RAG((知识库))
    A -.->|"market-data-adapter<br/>获取行情数据"| MARKET((数据源))
    
    B -.->|"analyzeStepConfidence()<br/>置信度/风险评分"| GATES((reflection-gates))
    C -.->|"graphAwareSelfCriticism()<br/>结合图节点自省"| GRAPH((graph-reflection))
    
    D -.->|"skip-gate.shouldSkipStep()<br/>根据置信度决定是否跳过"| SKIP((skip-gate))
    
    E -.->|"strategy-artifacts<br/>产物归档"| ARTIFACT((产物中台))
    
    style A fill:#e1f5ff,stroke:#01579b,stroke-width:2px
    style B fill:#fff9e1,stroke:#9b6d00,stroke-width:2px
    style C fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    style D fill:#fce4ec,stroke:#ad1457,stroke-width:2px
    style E fill:#f3e5f5,stroke:#6a1b9a,stroke-width:2px
```

---

## 六、Feature Flag 与启用状态

| 基础设施模块 | 默认状态 | 环境变量 | 说明 |
|--------------|---------|---------|------|
| scheduler/cost-keeper | ✅ 启用 | `USE_SCHEDULER` | 仅当 `=false` 或 `=0` 时禁用 |
| scheduler/skip-gate | ✅ 启用 | `USE_SCHEDULER` | 与 cost-keeper 联动 |
| compressor-adapter | ✅ 启用 | `USE_SCHEDULER` | 与 cost-keeper 联动，targetRatio 默认 0.5 |
| graph-reflection-bridge | ✅ 启用 | `ENABLE_DYNAMIC_CHAIN` | 图结构 + 自省融合，增强步骤决策 |
| knowledge-loader + RAG | ✅ 启用 | 无条件 | 知识库上下文注入，失败自动降级 n-gram |
| intent-memory | ✅ 启用 | 无条件 | RingBuffer 1000 条，辅助路由决策 |

---

## 七、关键文件索引（Code Reference）

### 7.1 用户层
| 文件 | 职责 |
|------|------|
| [src/app/chat](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/app/chat) | 主对话界面 |
| [src/app/dashboard/page.tsx](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/app/dashboard/page.tsx) | 仪表盘主页面 |
| [src/app/notebook](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/app/notebook) | 笔记本（步骤执行状态） |
| [src/app/board](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/app/board) | 审批流 |
| [src/app/page.tsx](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/app/page.tsx) | 首页路由 |

### 7.2 API 层
| 文件 | 职责 |
|------|------|
| [src/app/api/chat/route.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/app/api/chat/route.ts) | 主对话处理入口（初始化 scheduler + 路由 + 执行链） |
| [src/app/api/intent/analyze/route.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/app/api/intent/analyze/route.ts) | 独立意图分析接口 |
| [src/app/api/market/*](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/app/api/market) | 行情/运营数据接口 |
| [src/app/api/config/*](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/app/api/config) | API 配置 / 策略设置 / 交易参数 |
| [src/app/api/notebook/*](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/app/api/notebook) | 笔记本状态同步 |
| [src/app/api/user/*](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/app/api/user) | 用户体系（签到/余额/登录） |

### 7.3 意图路由层
| 文件 | 职责 |
|------|------|
| [src/lib/intent/smart-router.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/intent/smart-router.ts) | 核心路由逻辑：intent → chain + mode + credits |
| [src/lib/intent/fallback-engine.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/intent/fallback-engine.ts) | 四层识别（追问→LLM→规则→默认） |
| [src/lib/intent/intent-memory.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/intent/intent-memory.ts) | RingBuffer 记忆库（1000 条） |

### 7.4 执行链层
| 文件 | 职责 |
|------|------|
| [src/lib/strategy/chain-controller.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/strategy/chain-controller.ts) | S1~S5 策略链执行器 |
| [src/lib/dynamic-chain/runner.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/dynamic-chain/runner.ts) | 动态闭环链（plan-execute-reflect） |
| [src/lib/dynamic-chain/graph-planner.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/dynamic-chain/graph-planner.ts) | 动态链步骤规划（权威源：S 系列步骤定义） |
| [src/lib/dev-chain/index.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/dev-chain/index.ts) | 开发者 E 链 |
| [src/lib/strategy/steps/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/strategy/steps) | S1~S5 每步具体实现 |

### 7.5 基础设施层
| 文件 | 职责 |
|------|------|
| [src/lib/scheduler/cost-keeper.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/scheduler/cost-keeper.ts) | Token 用量追踪、预算控制、终止判断、报告生成 |
| [src/lib/scheduler/skip-gate.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/scheduler/skip-gate.ts) | 步骤跳过判断（结合置信度/风险评分） |
| [src/lib/compressor-adapter/index.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/compressor-adapter/index.ts) | 上下文压缩统一入口（文本摘要 + 图结构） |
| [src/lib/graph-reflection-bridge.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/graph-reflection-bridge.ts) | 图结构状态管理 + 自省融合（增强 skip 判断 / 压缩 / 反思） |
| [src/lib/knowledge-loader.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/knowledge-loader.ts) | 知识库加载与上下文注入 |
| [src/lib/knowledge-rag.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/knowledge-rag.ts) | RAG 核心（嵌入 / 检索 / 上下文构建 / n-gram 降级） |
| [src/lib/reflection-gates.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/reflection-gates.ts) | 置信度/风险评分 + skip gate 判断 |

### 7.6 状态管理
| 文件 | 职责 |
|------|------|
| [src/stores/chat-store.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/stores/chat-store.ts) | 对话消息列表 + 状态 |
| [src/stores/auth-store.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/stores/auth-store.ts) | 用户登录态 + JWT |
| [src/stores/notebook-store.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/stores/notebook-store.ts) | 笔记本步骤状态 |
| [src/stores/credits-store.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/stores/credits-store.ts) | 积分余额 |

---

## 八、运维快速参考

### 8.1 常见故障排查路径

| 现象 | 排查路径 | 关键日志 / 指标 |
|------|---------|-----------------|
| 对话无回复 | UI → chat-store → /api/chat → smart-router → chain-controller | `[CostKeeper]`, `[Intent]`, SSE stream |
| 回复质量低 | RAG 知识库是否完整？ → graph-reflection 置信度？ → compressor 是否过度压缩？ | GraphReport confidence, RAG chunks loaded |
| 对话被截断 | cost-keeper Budget 是否超限？ → 检查 moderate/complex 预算配置 | `[CostKeeper] ⚠ BUDGET EXCEEDED` |
| 某步骤被跳过 | skip-gate 判断逻辑 → graph-reflection 节点置信度 → 检查 S1/S2 stepMetadatas | `shouldSkipStep()` return value |
| 知识库检索空结果 | knowledge-loader 是否加载成功？ → RAG 嵌入 API key 是否配置？ → n-gram fallback 是否触发 | `loadAllKnowledge()`, `[RAG] Embedding failed` |

### 8.2 环境变量速查

```bash
# 基础设施开关（默认已启用，无需配置）
USE_SCHEDULER="true"                    # cost-keeper + skip-gate + compressor 总开关
ENABLE_DYNAMIC_CHAIN="true"             # dynamic-chain + graph-reflection 闭环

# RAG 配置（必填项，缺失时自动降级到 n-gram）
DEEPSEEK_API_KEY="your-api-key-here"    # RAG 嵌入 / 对话模型

# 数据库
DATABASE_URL="postgresql://..."         # PostgreSQL (Prisma)

# 认证
AUTH_SECRET="your-secret"               # Auth.js v5
```

### 8.3 性能瓶颈优先级

| 优先级 | 瓶颈点 | 监控指标 | 优化方向 |
|--------|--------|---------|---------|
| P0 | LLM 调用（S1~S5 每步） | totalTokens / stepLatency | cost-keeper 预算控制 + skip-gate 跳步优化 |
| P1 | RAG 检索（每次 S1） | embeddingLatency / chunksLoaded | 知识库缓存 + 更高效的嵌入模型 |
| P2 | Compressor（上下文 >200 条时触发） | compressRatio / originalTokens | 调整 targetRatio，减少不必要的压缩 |
| P3 | graph-reflection 节点追踪 | graphState.size / nodesProcessed | 惰性更新节点状态，避免高频计算 |

---

## 九、测试与验证

| 测试文件 | 覆盖范围 | 运行方式 |
|---------|---------|---------|
| [tests/infrastructure-integration-test.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/tests/infrastructure-integration-test.ts) | 5 大基础设施独立正确性 + 协作顺畅度 | `pnpm tsx tests/infrastructure-integration-test.ts` |
| [tests/smart-router-v2-stress-test.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/tests/smart-router-v2-stress-test.ts) | smart-router 各种 intent × role × thinking_mode 组合 | `pnpm tsx tests/smart-router-v2-stress-test.ts` |
| [tests/integration-three-systems.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/tests/integration-three-systems.ts) | 主前端 + 审批 + 产品中台三系统联动 | `pnpm tsx tests/integration-three-systems.ts` |

> 核心测试已通过：infrastructure-integration-test = 41/41 ✅

---

*本文档为运营快速参考，详细设计请查阅 [docs/ARCHITECTURE.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/docs/ARCHITECTURE.md)*
