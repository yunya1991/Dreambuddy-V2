# 调研报告：传统金融架构 + AI 多agent 工作流实践

> 任务3前期调研素材 | 日期 2026-09-30 | 为后续 SKILL 形成提供输入
> 调研对象：Bloomberg/Refinitiv/量化平台/Marquee + LangChain/CrewAI/AutoGen/MAF

## 1. 传统金融架构共性模式

1. **垂直分层整合**（Bloomberg 五层）：系统记录 → 系统行动 → 社交网络 → 合规审计 → 数据飞轮。Moat 不在数据本身，而在"采用统一运营词汇表"形成的事实标准 + 审计基底。
2. **数据采集三层存储**：Hot（kdb+/Redis 实时盘口）→ Warm（Parquet/Delta 近期历史）→ Cold（S3 Glacier 深度研究）。热层 append-heavy、冷层 range-scan，避免单一存储承担所有访问模式。
3. **Security Master / Symbology 主数据**：将频繁变动的 ticker（FB→META）映射到持久内部 ID，处理 splits/dividends/mergers，保证多源数据可对齐。
4. **Bitemporality + 事件驱动回测**：双时间戳保证 point-in-time 正确性，避免 restatement/look-ahead bias；事件循环精确模拟实盘执行，配合 Deflated Sharpe Ratio 防 p-hacking。
5. **风控横切独立 veto**（AISA/TAQuant）：Risk Sidecar 独立微服务，Alpha agent 产信号但不直接下单，Risk agent 可否决所有上游决策但不可改策略；事前（限额/敞口）/事中（kill-switch）/事后（归因）三层。
6. **微服务 domain-driven 隔离**：单一职责、strongly-typed contracts、消息总线通信；执行层确定性（deterministic），概率判断上游化，市场压力下行为可预期。
7. **人机协作层**：交易员界面（color-coded/shortcut 降低认知负载）、审批流、多级 kill-switch、audit trail、entitlement 控权。
8. **产物不可变归档**：交易记录、绩效归因、审计日志写入 immutable store，监管可追溯。

## 2. AI 多agent 编排共性模式

1. **Supervisor 中心化路由（90% 生产场景）**：一个 orchestrator 决定谁先跑，worker 间不直接通信；显式 routing 决策可日志化，debuggability 高。Network/Swarm/Hierarchical 分别用于 peer-to-peer/动态 handoff/10+ 大团队。
2. **上下文隔离 vs Fork 双模**：isolated 子代理从空白上下文启动（不污染 supervisor）；fork 继承 supervisor 全状态，复用 prompt cache，省去重复 file-read。
3. **Hierarchical 嵌套**：supervisor-of-supervisors，每层独立路由；超过 8 个 specialist 才值得，否则 over-engineering（成本 2.5-5x）。
4. **多模式编排**（CrewAI）：Sequential（串行）/Hierarchical（Manager 协调）/ProcessFlow（依赖图自动编排），对应 LangGraph 的 Tool-Calling vs Handoff 范式。
5. **记忆分层**：session 级（FileMemoryProvider 对话历史）+ durable 级（Cosmos DB 跨会话，自动抽取记忆条目并 recall）。
6. **FAIL-OPEN + 人机协作**：ToolApprovalAgent("don't ask again" 规则)、human-in-the-loop approval、background agents fan-out、自动 context compaction 防 overflow。
7. **OpenTelemetry 全链路 tracing**：从"出错了"到"确切在哪一步"，监管场景下作为合规证据。
8. **Skill 分布式 over MCP**：把 specialist 的 instructions 移入 orchestrator，而非每个领域都起独立模型（"From Specialist Agents to Distributed Skills over MCP"）。

## 3. DreamBuddy 架构对比分析

| 维度 | DreamBuddy 现状 | 对标 | 评估 |
|---|---|---|---|
| 主骨架 | 前端3.1→DreamOS SACG→DSH 多子agent→子域→产物中台 | Bloomberg 五层 / Supervisor | ✅ 优势：三层协同已对标 |
| 数据采集 | 四中心(18→19→20→21) | Hot/Warm/Cold 三层 | ⚠️ 差距：分层存储不明确，缺 bitemporal |
| 风控横切 | 散落各子域 | Risk Sidecar 独立 veto | ⚠️ 差距：独立 veto 边界不清 |
| 编排模式 | DreamOS SACG 中心化 | LangGraph Supervisor | ✅ 优势：已用中心化；可借鉴 fork 模式 |
| 记忆系统 | 4-MEMORY 认知系统(贝叶斯升级) | MAF FileMemory+Cosmos | ✅ 优势：超越多数框架；已闭环 |
| Skill 化 | 154+ skills A/C/F/G/T | Distributed Skills over MCP | ✅ 优势：已实现 MCP 化 |
| 回测验证 | dream-backtest-verify | 事件驱动+bitemporal | ⚠️ 差距：bitemporal 缺失 |
| 文档同步 | dream-doc-sync 7步 | — | ✅ 优势：独创闭环 |
| 全链路 trace | L1-TRACE 试点 | OpenTelemetry | ⚠️ 差距：未 GA |
| FAIL-OPEN | tsc+tests+HTTP200 | ToolApproval | ✅ 已部分实现 |

**可借鉴清单**：① Supervisor 显式 routing 日志化 ② forked subagents 节省 supervisor 上下文 ③ 自动 context compaction ④ OpenTelemetry 全链路 trace ⑤ Distributed Skills over MCP ⑥ 三层存储 + bitemporal ⑦ Risk Sidecar 独立 veto。

## 4. 规范流程建议（结合三方实践）

1. **数据分层采集**：Hot（Redis k线/盘口）→ Warm（Parquet 历史回测，bitemporal 双时间戳）→ Cold（归档）。所有回测走 Warm 层 point-in-time 数据，禁 look-ahead bias。
2. **风控横切独立 veto**：Risk 作为独立 sidecar（不属任何子域），Strategy→Risk→Execution 链路；Risk 可否决不可改策略；事前限额/事中 kill-switch/事后归因三层。
3. **Supervisor 显式路由日志**：DreamOS SACG 每次路由记 `routing_decision → worker → result`，接入 OpenTelemetry 全链路 trace，便于事后归因与监管审计。
4. **上下文双模管理**：worker 默认 isolated（不污染 supervisor 上下文）；需继承 supervisor 决策上下文用 fork（复用 prompt cache）；长链路自动 compaction 防 overflow。
5. **记忆三层闭环**：session 级（对话历史）+ durable 级（4-MEMORY 认知，recall→record→verify 贝叶斯升级）+ wiki 级（LLM wiki 编译）。三者索引统一同步（doc-sync）。
6. **FAIL-OPEN 与人机协作**：敏感操作（下单/调仓/审批）走 human-in-the-loop；告警走飞书 IM；LLM 降级链 DeepSeek→Qwen→NoOp 兜底不阻塞热路径。
7. **Skill 分布式 over MCP**：子域能力（BCRM/BDSM/宏观/经典指标/Superpower）以 Skill 注册到 MCP，DSH/DreamOS 按需调用，避免每领域起独立 agent（成本 3-10x）。
8. **产物不可变归档**：交易记录、绩效归因、审计日志写入 immutable store；产物中台统一查询入口；doc-sync 自动同步索引防断链。
9. **Security Master 主数据**：建立币种/标的持久内部 ID 映射，处理 splits/renaming，保证多源数据对齐。
10. **回测验证闭环**：dream-backtest-verify 5步（load trades→fetch klines→detector gate→rebound attribution→value report），Deflated Sharpe Ratio 防 p-hacking。

## 5. SKILL 设计建议

**核心能力清单**：
- 意图识别（零 Token 本地，6 类意图）
- SACG 四层编排（蓝图/执行图/时间线/图存储）
- NodeRegistry（35 模块配置 + 11 本地实现）
- 认知闭环（recall→record→verify）
- 文档同步（dream-doc-sync 7步）
- FAIL-OPEN 验证（tsc+tests+HTTP200）
- 风控 sidecar 拦截
- 产物归档（immutable + 索引同步）

**调用流程**：
```
用户意图
  ↓
recall 检索（硬约束，免费只读）
  ↓
SACG 规划蓝图（Supervisor 路由，记 routing 日志）
  ↓
DSH 子 agent 执行（isolated 默认 / fork 继承）
  ↓
风控 sidecar 拦截（veto 或放行）
  ↓
产物中台归档（immutable + doc-sync）
  ↓
record + verify 闭环（贝叶斯升级）
  ↓
wiki 编译（tags 含 wiki-compile 触发）
```

**认知闭环机制**：每次执行后 record 经验→verify 触发贝叶斯置信度更新与动态蒸馏→doc-sync 同步文档索引→recall 下次命中。硬约束决策（含"必须/禁止/默认/阈值"关键词）30秒内 record，质量 ≥B 级，tags 标"硬约束"+域。失败路径同样 record（反模式），verify(success=false) 降低置信度。

**关键设计原则**：编排层纯调度不重建能力（dreambuddy-os 已践行）；LLM 不直接交易判断（HC-9），熟悉架构→能力调用→内容整合→探索补充四阶段；每层职责单一边界清晰，前端默认不直连 DSH/DreamOS 8000。

---

**参考来源**：
- Bloomberg: datainterpretations.com/bloomberg-terminals, travelrisksafety.com/insights/bloomberg-for-every-industry, systemdesignhandbook.com/guides/bloomberg-system-design-interview
- Refinitiv/LSEG: developers.lseg.com Refinitiv Data Library Concepts, flashalpha.com/articles/flashalpha-vs-lseg-refinitiv-workspace
- 量化平台: atavest.com/microservices-architecture-trading-platforms, taquant.com/research AISA & Whitepaper, sophie-ai-finance.com/wiki/quant/alpha-factory, kanopylabs.com/blog/how-to-build-an-ai-native-quant-trading-platform
- AI agent: langchain.com/blog/organizing-context-in-a-multi-agent-harness, callsphere.ai/blog/langgraph-supervisor-multi-agent-orchestration-2026, aipromptshub.co/tutorial/multi-agent-coordination-patterns, juejin.cn/post/7635681418753556520 (CrewAI), devblogs.microsoft.com/agent-framework (MAF BUILD 2026)
