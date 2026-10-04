# 全局协作框架 SPEC（前端3.1 × DreamOS × DSH × 中台）

> **版本**: v1.0（调研回填完成）
> **日期**: 2026-09-29
> **状态**: ✅ 8 项风险逐项调研完成，4 项前提被证据修正
> **定位**: 四层协作框架的「数据流 + 功能协作」全局打通方案
> **调研方法**: recall 认知记忆 + 5 路并行 Explore agent 代码审计 + 定点 Grep/Glob 验证
>
> **与既有文档关系**:
> | 既有文档 | 维度 | 关系 |
> |----------|------|------|
> | [FRONTEND3_DREAMOS_DSH_GLOBAL_ARCH_SPEC.md](FRONTEND3_DREAMOS_DSH_GLOBAL_ARCH_SPEC.md) (SPEC-A v1.1) | 缺口清单（What） | **互补**：本文档是协作打通方案（How），且调研证据修正了 SPEC-A 部分结论 |
> | [CHAIN_INTEGRATION_SPEC.md](../dream-harness-bridge/docs/CHAIN_INTEGRATION_SPEC.md) (v0.1) | 链路与端口决策 | **关键证据**：R1 的统一入口决策来源 |
> | [SPEC-20260928-POSTGRESQL-CENTRALIZATION.md](../SPEC-20260928-POSTGRESQL-CENTRALIZATION.md) | 数据库中心化 | **关键证据**：R3「不需要融合」决策来源 |
> | [SPEC-20260929-L1-TRACE-PILOT.md](../SPEC-20260929-L1-TRACE-PILOT.md) | trace_id 全链路 | **关键证据**：产物中台 trace 链路已通 |
> | [DSH_SUBAGENT_ARCHITECTURE_SPEC.md](../dream-harness-bridge/docs/DSH_SUBAGENT_ARCHITECTURE_SPEC.md) (v0.2) | DSH 9 Subagent 详设 | **下游**：R2/R4 落地方案升级为该 SPEC v1.0 |
> | [WORKBUDDY_OS_GAP_ANALYSIS.md](../WORKBUDDY_OS_GAP_ANALYSIS.md) (v1.0) | 模块缺口清单 | **输入**：R8 来源，需双向差集复核 |

---

## 一、协作四原则（硬约束）

| # | 原则 | 约束内容 | 违反后果 |
|---|------|---------|---------|
| P1 | **DreamOS 纯编排不执行业务** | A 层 GraphPlanner 只规划执行图，业务计算全部下沉 DSH/节点 | 编排层臃肿，失去 OS 内核定位 |
| P2 | **DSH 隔离执行返回摘要** | Subagent 独立上下文，subagent 间不通信（HC-7），只向 C 层返回 SubagentOutput 摘要 | 上下文污染，Token 爆炸 |
| P3 | **中台横切共享避免重复** | 产物/网关/百炼/认知能力跨层共享，任何层不重复造轮子 | 孤岛、维护成本翻倍 |
| P4 | **数据驱动避幻觉** | DSH 输入必须来自已验证节点输出；LLM 只做提炼+图表生成，不生成原始数据 | 大模型幻觉进入交易决策 |

## 二、四层协作框架总览（端口归属已核实修正）

```
┌─────────────────────────────────────────────────────────────────────┐
│ 前端3.1 (Next.js, :3001) — UX 层，不做业务决策                        │
│   43 个 page.tsx / 62+ 组件 / 12 Store / Agent A(技术) + Agent B(基本面)│
│   API 通道: bridge-client.ts → 默认 http://127.0.0.1:3847            │
│            (NEXT_PUBLIC_BRIDGE_URL 可覆盖)                           │
└──────────────┬──────────────────────────────────────────────────────┘
               │ HTTP REST（前端唯一入口 :3847）
┌──────────────┴──────────────────────────────────────────────────────┐
│ :3847 统一入口 — Flask run_api_server.py（DSH integration 层承担）    │
│   已迁移原 6-TRADING/bridge 的 market/trade/skill/bridge 蓝图        │
│   CORS 白名单: :3000/:3456/:3847                                     │
│   ┌──────────────────────────────────────────────────────────────┐ │
│   │ DreamOS SACG 内核 — 纯编排                                     │ │
│   │  S: IntentEngine 6 类意图（前端规则引擎 conf≥0.9 跳 LLM）       │ │
│   │  A: GraphPlanner 选 A/C/F 主链 + 辅助链                        │ │
│   │  C: GraphExecutor + Reflector + Aggregator ← C-Drive-Agent    │ │
│   │  G: GraphStore + Checkpointer                                  │ │
│   │  横切: Registry / Evolution(CBR+KNN+贝叶斯) / Budget           │ │
│   └──────────────────────────────────────────────────────────────┘ │
└──────────────┬──────────────────────────────────────────────────────┘
               │ IPC NDJSON（AlgorithmLayerBridge，stdio）
┌──────────────┴──────────────────────────────────────────────────────┐
│ DSH Subagent (:3080) — 驱动层，仅内部，不暴露给前端（设计决策）        │
│   Cordis 插件运行时 + python-server + jev-judge                      │
│   C-Drive-Agent 4 步循环: recall → 反思(Bull/Bear) → jeval → 路由    │
│   technical(C1-C3) sentiment(F1) macro(F5) flow(F2) onchain(F4)      │
│   valuation(F3) risk(P2) portfolio(P2)                               │
└──────────────┬──────────────────────────────────────────────────────┘
               │ 横切共享
┌──────────────┴──────────────────────────────────────────────────────┐
│ 中台组件                                                              │
│   ① 产物中台（独立 Next.js，HTTP 反代互通，trace_id 链路已通）         │
│   ② 网关中台 Gateway Hub（认证/API配置/参数/积分）✅                   │
│   ③ 百炼集成（API+KB+RAG）🔄 进行中                                   │
│   ④ 认知记忆库（recall/record/verify）— Reflector 已部分接入           │
└─────────────────────────────────────────────────────────────────────┘
```

> **端口归属修正**：上轮梳理将 :3847 标为 DreamOS SACG，证据显示 :3847 实际是 DSH `integration/run_api_server.py` 承担的统一 Flask 入口（`DHB_API_PORT=3847`），DreamOS 内核由其内部挂载；:3080 是 Cordis web profile，按 CHAIN_INTEGRATION_SPEC 决策不暴露给前端（仅 jev-judge 等内部调用）。

## 三、全局数据流（4 条主流）

### 3.1 交易决策流（核心流）

```
用户指令 → [前端:3001] 规则引擎预判(conf≥0.9 直发)
        → bridge-client.ts → [:3847 统一入口]
        → [S] IntentEngine 意图识别（6 类 + 权重）
        → [A] GraphPlanner 选主链（A 决策/C 技术/F 基本面）+ 辅助链
        → [C] GraphExecutor 逐节点执行
              ├─ 每节点后 C-Drive-Agent 4 步循环（分级触发）:
              │    conf>0.75 跳过 | 0.65-0.75 recall+反思
              │    | 0.50-0.65 +Bull/Bear辩论 | <0.50 全链路
              ├─ 数据不足 → IPC NDJSON → DSH subagent 补充（P2 隔离执行）
              └─ Reflector（当前: REDO + recall suggestions；目标: 四步）
        → [C] Aggregator 聚合（方向/置信度 + charts）
        → [G] Checkpointer 持久化 + trace_id 贯穿至产物中台
        → 前端三屏渲染（周线/日线/实时）
```

### 3.2 研究分析流

```
研究助手 → T 域搜索 → DSH subagent(macro/flow/onchain/valuation)
        → SubagentOutput{summary, signals, charts, raw_data}
        → python-server/aggregator.py 汇总 all_signals/all_charts
        → 前端 Agent B 渲染（图表 + 结论）
```

### 3.3 产物交付流（trace 链路已通，证据：SPEC-20260929-L1-TRACE-PILOT）

```
AI 产物 → DreamOS scheduler_data/artifacts（前端 artifact-utils.ts 直读）
        → 产物中台 /api/chain/artifacts（HTTP 反代）
        → trace_id: 前端 → DSH → DreamOS → 产物中台 → /ops/traces 看板
        → 归档 + 邮件路由
```

### 3.4 认知闭环流（横切）

```
任务前 recall(context) → 执行 → 任务后 record(经验)
      → verify(成功/失败) → 贝叶斯置信度更新 → 动态蒸馏
      → hermes 反思决策树 → 可选沉淀新 SKILL
断点: Reflector._recall_suggestions() 已接入 recall（FAIL-OPEN），
      缺 jeval 判断步 + subagent 补资料步
```

## 四、8 项风险调研结论总表（⚠️ = 前提被证据修正）

| # | 风险 | 调研结论 | 真实状态 | 修正后优先级 |
|---|------|---------|---------|------------|
| R1 | 三端口并存 | ⚠️ 统一入口决策已落地：:3847 由 run_api_server 统一服务，原 bridge 蓝图已迁移；:3080 设计上不暴露前端 | **基本已解决**，剩收尾核验 | P2（核验清单） |
| R2 | fundamental 插件混杂 | ✅ 确认：单 tool `get_fundamental_analysis` 统一入口，server.py 单 handler 转发 9-基本面 API | **真实缺口**，但契约+聚合器已就绪 | P0 |
| R3 | 产物中台未融合 | ⚠️ SPEC-20260928 明确决策「不需要融合」，trace 链路已通，前端直读 artifacts 目录 | **决策已定**，非缺口 | 关闭（转 P3 数据库中心化） |
| R4 | DSH 图表能力缺失 | ✅ 确认输出端缺填充，但 ChartSpec 契约 + aggregator 汇总逻辑已存在 | **半截工程**，补填充即可 | P0 |
| R5 | C1 与经典指标重复 | ⚠️ 已是主从模式：C1 调 ClassicIndicatorsClient→:8092，本地仅降级；registry 已注册 type:api | **非重复**，真问题是双份 c1_tech_scan.py 漂移 | P1（合并双实现） |
| R6 | 认知库未接入 Reflector | ⚠️ 已部分接入：构造函数预留 cognitive_adapter，decide() 已调 _recall_suggestions()（FAIL-OPEN） | **半截工程**，缺 jeval+补资料步 | P0 |
| R7 | 前端 40 子页仅 4 个 | ⚠️ 统计失真：实际 43 个 page.tsx；v3 规划的独立子页多以 tab/组件聚合实现 | **口径问题**，真差距在 API Client 与组件分层 | P1 |
| R8 | 11 模块已实现未注册 | 🔄 部分修正：registry 有 88 个 id 字段、18 个带类型（8 local + 10 api），Screen1/2/3 已有编排配置含 fallback 链 | 需双向差集全量核对 | P1 |

## 五、逐项调研结论与打通方案

### 5.1 R1 三端口并存 → 统一网关（基本已解决，剩收尾）

**证据**：
| 位置 | 证据 |
|------|------|
| [bridge-client.ts](../../3.1-FRONTEND/src/lib/bridge-client.ts) L6-L7 | 前端统一入口默认 `http://127.0.0.1:3847`，`NEXT_PUBLIC_BRIDGE_URL` 可覆盖 |
| [run_api_server.py](../dream-harness-bridge/integration/run_api_server.py) L16-L21 | `DHB_API_PORT=3847`，DSH integration 层承担统一入口 |
| run_api_server.py L148-L161 | 原 `6-TRADING/bridge` 的 market/trade/skill/bridge 蓝图已迁移注册 |
| [CHAIN_INTEGRATION_SPEC.md](../dream-harness-bridge/docs/CHAIN_INTEGRATION_SPEC.md) L45/L159/L247 | 设计决策：DSH :3080 不暴露给前端，仅 IPC 内部调用；前端不直接请求 :3080 |

**打通方案**（收尾核验清单）：
1. 全仓库 grep 前端代码确认零直连 `:3080`（bridge-client 已走 :3847 ✅）
2. 废弃 `6-TRADING/bridge/run_server.py`（SPEC 注释已声明将废弃，需执行）
3. 网关中台与 :3847 的关系文档化：认证层在前端侧，业务网关在 :3847

**技术文档**：更新 CHAIN_INTEGRATION_SPEC v0.1 → v1.0（核验项打勾）。

### 5.2 R2 fundamental 插件拆分（P0，真实缺口）

**证据**：
| 位置 | 证据 |
|------|------|
| [cordis-plugin-fundamental/lib/index.js](../dream-harness-bridge/packages/cordis-plugin-fundamental/lib/index.js) L174-L225 | 仅注册 1 个 tool `get_fundamental_analysis`，统一调 Python server |
| index.js L226-L246 | presentCall/presentResult 统一卡片，无 F1-F5 分别渲染 |
| [server.py](../dream-harness-bridge/packages/python-server/server.py) L857-L896 | `_handle_fundamental_analysis` 单 handler 转发 9-基本面分析 API |
| server.py L1816-L1820 | 分发逻辑只有 `fundamental_analysis` 一个入口 |

**打通方案**：
1. python-server 拆 5 个 handler：`sentiment_analysis` / `flow_analysis` / `valuation_analysis` / `onchain_analysis` / `macro_analysis`（各自请求 9-基本面分析 API 的对应端点）
2. 每个 handler 返回 SubagentOutput 契约（module/summary/signals/charts）
3. Cordis 侧拆 5 个 tool（或 1 个插件注册 5 个 tool），前端按 module 路由渲染
4. 落地走 `dream-subagent-tdd-workflow`（RED: ModuleNotFoundError → GREEN: 共享契约）

**技术文档**：DSH_SUBAGENT_ARCHITECTURE_SPEC v0.2 → v1.0（本方案并入）。

### 5.3 R3 产物中台融合（关闭，决策已定）

**证据**：
| 位置 | 证据 |
|------|------|
| [SPEC-20260928-POSTGRESQL-CENTRALIZATION.md](../SPEC-20260928-POSTGRESQL-CENTRALIZATION.md) L37-L45 | 明确「产物中台与 3.1 前端不需要融合」，唯一通道是 HTTP 反代 |
| [SPEC-20260929-L1-TRACE-PILOT.md](../SPEC-20260929-L1-TRACE-PILOT.md) L201-L253 | trace_id 链路已通：前端 → DSH → DreamOS → 产物中台 `/api/chain/artifacts` → `/ops/traces` 看板 |
| [artifact-utils.ts](../../3.1-FRONTEND/src/app/api/artifacts/artifact-utils.ts) L20-L73 | 前端直读 DreamOS `scheduler_data/artifacts` 目录并返回 meta |

**结论**：R3 非缺口。「融合」被重新定义为「trace 互通 + HTTP 反代 + 各自独立部署」，已实现。剩余的数据库统一（独立 SQLite → PostgreSQL 中心化）由 SPEC-20260928 承接，属 P3。

### 5.4 R4 DSH 图表能力（P0，半截工程）

**证据**：
| 位置 | 证据 |
|------|------|
| [subagent_types.py](../dream-harness-bridge/packages/python-server/subagent_types.py) L26-L68 | ✅ ChartSpec + SubagentOutput{module, summary, signals, charts, raw_data} 契约已定义 |
| [aggregator.py](../dream-harness-bridge/packages/python-server/aggregator.py) L16-L31 | ✅ 生产聚合器已期望多 SubagentOutput，汇总 all_signals/all_charts/raw_data_by_module |
| aggregator.py L44-L90 | ⚠️ 若各 agent charts 为空则 all_charts 为空——瓶颈在填充端 |

**打通方案**：
1. 5 个新 subagent handler（R2 产出）按契约填充 charts（K线/仪表盘/Sankey/热力图等，映射表见 DSH SPEC v0.2 §4.1）
2. 前端复用现有图表组件（fundamental tab 已有组件框架），新增 ChartSpec → 组件的通用渲染器
3. LLM 只生成图表配置与文案，数据必须来自节点已验证输出（P4 硬约束）

**技术文档**：DSH_SUBAGENT_ARCHITECTURE_SPEC v1.0 含 ChartSpec 填充规范 + 前端渲染器约定。

### 5.5 R5 C1 与经典指标去重（P1，非重复，防漂移）

**证据**：
| 位置 | 证据 |
|------|------|
| [experiments/.../c1_tech_scan.py](../../experiments/ab-trading/core/nodes/c1_tech_scan.py) L22-L75 | 优先 `ClassicIndicatorsClient()`→`:8092`，成功标 `source="classic_api"`，失败走 `local_fallback` |
| [classic_indicators.py](../../experiments/ab-trading/core/modules/classic_indicators.py) L56-L79 | `:8092 /api/v1/ml3/indicator` 探活；本地计算是显式降级方案 |
| [dreamos/.../c1_tech_scan.py](../dreamos/capabilities/trading/nodes/c1_tech_scan.py) L42-L107 | 生产版从 state 读 ema20/rsi14/macd 等，不计算指标 |
| [module_registry.yaml](../registry/module_registry.yaml) L1226-L1231 | C1 已注册：`type: api, base_url: http://127.0.0.1:8092` |

**结论**：C1 与 10-经典指标系统是主从关系（已注册、已降级保护），**不存在重复建设**。真问题是 `experiments/ab-trading/.../c1_tech_scan.py` 与 `dreamos/capabilities/trading/nodes/c1_tech_scan.py` **双份实现逻辑漂移**——实验版改动不同步生产版。

**打通方案**：定 dreamos 版为唯一权威，experiments 版改为 import 引用（或标注 frozen 仅历史回测用），加 CI diff 检查。

**技术文档**：CLASSIC_INDICATOR_SINGLE_SOURCE_SPEC.md（P1）。

### 5.6 R6 认知库接入 Reflector（P0，半截工程）

**证据**：
| 位置 | 证据 |
|------|------|
| [reflector.py](../dreamos/core/compute/reflector.py) L64-L81 | ✅ 构造函数已预留 `cognitive_adapter` 参数 |
| reflector.py L128-L177 | ⚠️ decide() 已调 `_recall_suggestions()` 加入 suggestions，但主体仍只有 预算/REDO/冲突/早终止 规则 |
| reflector.py L181-L205 | `_recall_suggestions()` 是唯一接入点，异常 FAIL-OPEN 返回 `[]` |
| [cognitive_loop_adapter.py](../dream-harness-bridge/integration/cognitive_loop_adapter.py) L29-L85 | ✅ recall() 封装已存在（MCP 不可用时 FAIL-OPEN） |

**打通方案**（补齐四步，对齐 DSH SPEC v0.2 §4.4 分级触发）：
1. Step1 recall：✅ 已有，保留
2. Step2 反思扩展：conf<0.65 触发 Bull/Bear 辩论（新增 debate 模块，复用 master-seminar 规划）
3. Step3 jeval 判断：harness 层 3 个 Harness 事件下沉到 C 层 Aggregator 之后调用（noul≥0.85 放行 / <0.50 阻止）
4. Step4 补资料：SUPPLEMENT 时路由对应 DSH subagent（依赖 R2 产出）

**技术文档**：C_LAYER_REFLECTOR_4STEP_SPEC.md（P0），落地走 `dream-tdd-dev-workflow`。

### 5.7 R7 前端子页补齐（P1，口径修正后重新排期）

**证据**：
| 位置 | 证据 |
|------|------|
| Glob `src/app/**/page.tsx` | 实际 **43 个** page.tsx（dashboard 27 + board 5 + three-screens 5 + auth/misc 6） |
| [v3-frontend-architecture.md](../../3.1-FRONTEND/docs/v3-frontend-architecture.md) L187-L268 | 文档规划 40 子页清单（classic 9 / fundamental 11 / monitor 4...） |
| [fundamental/page.tsx](../../3.1-FRONTEND/src/app/dashboard/fundamental/page.tsx) L12-L72 | 11 子页以 tab 聚合（overview/onchain/macro/sentiment/flow...） |
| [monitor/page.tsx](../../3.1-FRONTEND/src/app/dashboard/monitor/page.tsx) L8-L38 | 4 子页以 tab 聚合（SACG总览/DAG/BAC/历史回放） |
| [api-client.ts](../../3.1-FRONTEND/src/lib/api-client.ts) L1-L119 | 单文件统一 request，未按 19 域拆分 |

**结论**：「40 子页仅 4 个（10%）」失真。功能是「单页 tab 聚合」形态而非独立路由——信息架构选择差异，非功能缺失。真差距：
1. `api-client.ts` 单文件 vs 19 域拆分规划（可维护性）
2. 组件平铺（`V3*.tsx` + `features/`）vs 5 层规划（layout/screens/features/primitives/hooks）
3. 路由前缀 `/dashboard/*` vs 规划 `/v3/dashboard/*`

**打通方案**：
- 不盲目拆 40 个独立路由（tab 聚合对交易工作台场景更优），而是**修订文档口径**使其与实现对齐
- API Client 按域拆分（19 域），组件按 5 层归位——纯前端重构，不阻塞主链路
- 缺失能力补页：risk/portfolio 视图（依赖 DSH P2 subagent）

**技术文档**：v3-frontend-architecture.md 修订 v2（口径对齐）+ FRONTEND_API_DOMAIN_SPLIT_SPEC.md（P1）。

### 5.8 R8 模块注册（P1，双向差集核对）

**证据**：
| 位置 | 证据 |
|------|------|
| [module_registry.yaml](../registry/module_registry.yaml) | 88 个 id/module_id/name 字段；18 个带类型标注（8 `type: local` + 10 `type: api`） |
| registry L15-L154 | Screen1/2/3 已有编排配置：id=dream-screen1-first 等，含 factory_function、fallback_reason（Screen1 不可用降级 A2、Screen2 降级 C 链）、依赖 dream-contradiction-theory |
| [WORKBUDDY_OS_GAP_ANALYSIS.md](../WORKBUDDY_OS_GAP_ANALYSIS.md) | 称三屏「❌ 无实现需新建」——与 registry 已有编排配置存在出入，需复核 skill 代码侧实现状态 |

**结论**：registry 比「35 配置 11 实现」更丰富（Screen 编排链已配置），但「配置先行、代码未落地」与「代码已落地、未注册」两种错位并存。

**打通方案**：双向差集全量核对——
1. registry 88 条目 → 逐一核验代码存在性（配置→代码）
2. 6-TRADING/skills/ + experiments/ 已有实现 → 逐一核验注册状态（代码→配置，A0-A4/A9/oneirology 等）
3. 输出《Registry 双向差集核对报告》，错位项批量补注册/补实现

**技术文档**：REGISTRY_RECONCILIATION_REPORT.md（P1），核对后更新 GAP_ANALYSIS v2。

## 六、技术文档规划（P0-P3 实施路径）

### P0 — 架构闭环（打通主链路数据流）

| # | 文档/交付物 | 对应风险 | 下游执行 |
|---|-----------|---------|---------|
| P0-1 | DSH_SUBAGENT_ARCHITECTURE_SPEC v1.0（fundamental 拆 5 subagent + ChartSpec 填充规范 + 前端渲染器约定） | R2+R4 | `dream-subagent-tdd-workflow` |
| P0-2 | C_LAYER_REFLECTOR_4STEP_SPEC.md（recall✅→反思+Bull/Bear→jeval 下沉→subagent 补资料） | R6 | `dream-tdd-dev-workflow` |

### P1 — 决策质量（消除漂移与错位）

| # | 文档/交付物 | 对应风险 | 下游执行 |
|---|-----------|---------|---------|
| P1-1 | CLASSIC_INDICATOR_SINGLE_SOURCE_SPEC.md（dreamos 版唯一权威 + CI diff） | R5 | 直接实施 |
| P1-2 | REGISTRY_RECONCILIATION_REPORT.md（双向差集）→ GAP_ANALYSIS v2 | R8 | `dream-eng-mgmt-workflow` 排期 |
| P1-3 | FRONTEND_API_DOMAIN_SPLIT_SPEC.md（19 域拆分 + 5 层组件归位） | R7 | 前端重构迭代 |
| P1-4 | v3-frontend-architecture.md 修订 v2（文档口径对齐 tab 聚合实现） | R7 | 文档修订 |

### P2 — 补齐（依赖 P0 产出）

| # | 文档/交付物 | 依赖 |
|---|-----------|------|
| P2-1 | risk-agent / portfolio-agent 新建 SPEC（VaR/相关性/压力测试 + 仓位/再平衡） | P0-1 契约落地 |
| P2-2 | 前端 risk/portfolio 视图页 | P2-1 |
| P2-3 | CHAIN_INTEGRATION_SPEC v1.0（R1 核验项打勾 + run_server.py 废弃执行） | 核验清单完成 |

### P3 — 升级（长期）

| # | 文档/交付物 | 说明 |
|---|-----------|------|
| P3-1 | Checkpointer 升级 LangGraph 级别（中断恢复/回溯） | 参考 COMPETITIVE_ANALYSIS §2.4 |
| P3-2 | PostgreSQL 中心化（产物中台 + 前端 SQLite 收编） | SPEC-20260928 已承接 |
| P3-3 | 百炼集成完成（API+KB+RAG 全量） | 进行中 |

## 七、术语澄清（硬约束，引用 VM-1790255435891）

| 术语 | 含义 | 抽象层 |
|------|------|--------|
| **SACG** | 内核分层架构（S感知/A编排/C执行/G存储） | DreamOS 内核 |
| **A/C/F 链** | 能力域链路（A 决策链 A0-A9 / C 技术链 C1-C5 / F 基本面链 F1-F5） | 业务能力域 |
| **前端 C 系列** | 前端 classic 模式本地思维链 C1-C8 | 前端展示层 |

⚠️ 代码中 `orchestrate/route.ts` 的 `step.chain` 应标 `SACG` 而非 `C`；`reasoningPath` 应列 `['S感知','A编排','C执行','G存储']`。

## 八、功能协作矩阵（层 × 能力域）

| 能力域 | 前端3.1 (:3001) | :3847 统一入口 + SACG | DSH (:3080 内部) | 中台 |
|--------|---------|--------------|--------------|------|
| 意图识别 | 规则引擎预判 | S: IntentEngine | — | — |
| 编排规划 | — | A: GraphPlanner | — | — |
| 技术执行 | Agent A 展示 | C: GraphExecutor → C1(api:8092) | technical-agent | 10-经典指标系统 |
| 基本面 | Agent B 展示（tab 聚合） | C: 节点调度 | sentiment/macro/flow/onchain/valuation（待拆） | 百炼 KB/RAG |
| 反思决策 | — | C: Reflector(recall✅/jeval 待下沉)+Aggregator | C-Drive-Agent | 认知记忆库 |
| 状态持久化 | — | G: GraphStore+Checkpointer | — | （P3 PostgreSQL） |
| 产物交付 | artifact-utils 直读 + 产物页 | scheduler_data/artifacts 产出 | — | 产物中台（trace 已通） |
| 认证网关 | 登录/配置 | — | — | Gateway Hub ✅ |
| 自进化 | — | Evolution(CBR+KNN+贝叶斯) | 案例回灌 | 认知蒸馏 |
| 可观测 | /ops/traces 看板入口 | trace_id 产生 | trace_id 传递 | trace_id 汇聚 ✅ |

## 九、调研修正记录（对 SPEC-A v1.1 的修订建议）

| SPEC-A 原结论 | 本次调研修正 |
|--------------|-------------|
| 三端口并存需统一到 :3847（P0 缺口） | :3847 统一入口已落地（run_api_server 承担），:3080 设计为内部，降 P2 核验 |
| 产物中台未融合（缺口） | SPEC-20260928 已决策不融合，trace 链路已通，关闭 |
| C1 与经典指标重复 | 主从调用已建立，真问题是双份 c1_tech_scan.py 漂移 |
| 前端 40 子页仅 4 个（10%） | 实际 43 page.tsx，子页功能以 tab 聚合实现，差距口径需修订 |
| 认知库未接入 Reflector | recall 已接入（FAIL-OPEN），缺 jeval+补资料两步，半截工程 |
| Registry 35 配置 11 实现 | registry 88 条目、18 带类型，Screen 编排链已配置，需双向差集复核 |

## 十、下一步行动

1. 用户审阅本 SPEC（重点：4 项前提修正是否认可）
2. 审阅通过后：P0-1/P0-2 两个 SPEC 细化（分别走 subagent-tdd / tdd-dev workflow）
3. P1 项转 `dream-eng-mgmt-workflow` 排期
4. 每项迁移完成后按用户规则走 BrowserSkill 页面真实验收

## 十一、本 SPEC 不覆盖项

| 不覆盖项 | 责任方 |
|---------|--------|
| 单 subagent 的 TDD 实现细节 | `dream-subagent-tdd-workflow` |
| P0-P3 工程排期与里程碑 | `dream-eng-mgmt-workflow` |
| 行业对标（Bloomberg/LangGraph 等） | SPEC-B（已有，独立文档） |
| 文档索引同步 | `dream-doc-sync-workflow` |
