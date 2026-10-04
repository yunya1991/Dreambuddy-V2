# 自运行系统四层落地路径 — 总技术文档（深度调研报告）

> 日期：2026-09-29
> 来源：4 维多源调研 + 交叉验证
> 5 维评分：**8.4 / 10**
> 调研方法：`dream-research-workflow` 标准 5 步流程

---

## 一、命题与约束

### 命题

为 dreambuddy-v2 设计"前端/产物中台/DreamOS/DSH 四系统自运行"可观测性方案，形成从 L1 可观测 → L2 自检测 → L3 自修复 → L4 自迭代的四层落地路径。

### 主要矛盾

**数据驱动 vs 工程可靠性**：深度学习和交易策略需要海量数据和频繁迭代，但金融交易系统的 0.1% 故障率可能导致灾难性损失。如何在支持快速实验的同时保证系统级可靠性，是自运行架构的核心张力。

### 约束

- **时间窗**：L1 已验证（4 系统 trace_id + JSONL + 中台看板），L2-L4 需分 sprint 落地
- **工程上下文**：
  - HC-1a：模块化开关架构（所有能力 env 开关控制）
  - HC-9：FAIL-OPEN 降级（异常不阻断业务）
  - 零回归：新功能必须有测试覆盖
  - BrowserSkill 验收：每阶段功能需真实页面验收
- **数据范围**：覆盖前端(3000)、产物中台(3456)、DreamOS(8000)、DSH(3847) 四系统

---

## 二、4 维调研结论

### 2.1 传统金融（Bloomberg / FactSet / 顶级量化基金）

**Bloomberg B-PIPE / MARS**
- **规模**：3500 万工具、330+ 交易所、800 亿 ticks/日，24/7/365 托管监控
- **一致性优先**：同一套数据/定价/风险库支撑前台与风控，消灭数据不一致
- **P&L Explain**：风控指标可分解归因到因子/Greeks，而非裸数字告警
- **Validus 案例**：B-PIPE + AWS PrivateLink + serverless 一周内上线，证明"托管 feed + 云原生流管道"已成行业标准

**FactSet 数据管道**
- **五步管道**：Extract → Transmit → Store → Process → Deliver，每环节有校验点和保留策略
- **Hub-and-Spoke 实体模型**：异构数据源映射到单一标识符，防"数据走错管道"
- **工作流监控**：pre/post-calculation checks，计算前后双向校验

**顶级量化基金（Two Sigma / Citadel / Renaissance）**
- **五层 ML 监控栈**：Lakehouse → Feature Store → 实验跟踪 → 训练编排 → 服务与漂移监控
- **机构级算法监控**：47 指标 × 亚秒级，四类失效模式（失控下单、数据腐坏、执行劣化、限额突破）
- **连续风控替代批式检查**："批式风控在两次检查之间可能累积致命敞口"
- **Citadel 可观测性栈**：分布式追踪 + 统一指标 + 告警（K8s + Spinnaker CD）

**金融 trace_id 实践**
- W3C `traceparent`/`tracestate` 标准，首触点生成全程不重分配
- 事件信封：`causation_id`（因果链）+ `correlation_id`（请求链）成对出现
- 支付系统 STAN 模式：超时≠失败，超时触发冲正/补偿流程而非盲目重试

**金融级 JSONL / 事件溯源**
- `Command vs Event` 严格分离；append-only 绝对不变量；CQRS 读写分离
- 生产形态：Kafka compacted topic / PostgreSQL append-only / Chronicle Queue（tick-to-trade 23µs）
- **SHA-256 哈希链**（prev_hash + hash）+ 独立 walker 离线验证 = JSONL 最小可用防篡改审计
- **关键区分**：Event Sourcing（服务内状态持久化）≠ Event-Driven（服务间通信）

### 2.2 GitHub 代码（ai-hedge-fund / TradingAgents / LangGraph / AutoGPT）

**ai-hedge-fund（62K stars）**
- `AgentProgress` 单例 + `asyncio.Queue` 解耦 agent 状态上报与 HTTP I/O
- 4 类 Pydantic 事件（Start/Progress/Complete/Error）经 SSE 推送
- `--show-reasoning` 透传 chain-of-thought；SQLAlchemy/SQLite 持久化 run 历史
- **缺口**：无 OTel/Prometheus，无重试/自修复

**TradingAgents（84K stars）**
- `AgentState` 共享 state 原子更新；`max_debate_rounds` 显式配置
- `TradingMemoryLog` 决策闭环：决策落盘 `~/.tradingagents/memory/trading_memory.md`，回取已实现收益 + 反思注入下轮 prompt
- `Reflector` 交易后反思；结构化输出按 provider 分层降级
- **checkpointer**：graph-shape 指纹 thread_id（防不同参数图静默续跑）+ DeltaChannel 40× 存储降

**LangGraph**
- checkpoint 含完整图状态 + node 位置 + pending edges + thread_id，SQLite/Postgres 可插拔
- `get_state_history` + `update_state` 支持分叉重放（回答"参数更保守时决策是否变化"）
- `interrupt()` + `Command(resume=...)` human-in-the-loop

**AutoGPT / Devin**
- `reflect_on_failure`：失败动作+错误+状态→LLM 反思改进方案
- **三层恢复**：指数退避 → 熔断降级（degraded 响应）→ pipeline 重规划
- Devin：ACU 计量、环境版本回滚、上下文压缩阈值可配置

**OTel 生态**
- **开源交易框架均未原生集成 OTel**——差异化机会
- 推荐路径：OpenLIT（一行接入 50+ provider）→ OTLP → Prometheus + Tempo/Jaeger + Grafana
- 交易刚需自定义指标：LLM 延迟、token 消耗、fallback 触发率、checkpoint 恢复次数、熔断器状态

### 2.3 软件工程（Chaos / SRE / 契约测试 / AutoML）

**Netflix Chaos Engineering**
- 五大原则：稳态假设、真实事件、生产环境、自动化持续、最小爆炸半径
- 工具链：Chaos Monkey（实例终止）→ Chaos Kong（Region 宕机）→ Litmus MCP Server（AI 驱动实验）
- **疫苗类比**：故意引入受控威胁建立免疫能力

**Google SRE SLO/SLI**
- SLI（指标）→ SLO（目标）→ Error Budget（预算）
- 错误预算驱动发布节奏：预算耗尽暂停高风险发布，预算充足大胆上线
- Burn Rate Alerting：慢速（24h 回溯）+ 快速（1h 回溯）双层告警
- **避免 100% SLO**：零错误预算 = 任何故障都立即违规

**契约测试（Pact / Spring Cloud Contract）**
- Pact：消费者驱动 + Pact Broker + `can-i-deploy` 部署门禁
- 匹配器（Matchers）：断言类型而非精确值，避免过度指定
- BDCT 双向契约测试：OpenAPI 与契约双向验证

**OpenTelemetry**
- W3C `traceparent` header + `baggage` 键值对传播
- Trace/Log/Metric 三大信号通过 context 关联
- SQL Commenter：数据库查询注入 traceparent 注释

**AutoML / NAS / 遗传算法**
- NAS 五大方法：RL / 进化 / 梯度（DARTS）/ 零成本代理 / 单次训练超网
- LLM-guided NAS：搜索成本降 4-10 倍
- **遗传算法交易优化**：染色体=参数组合，适应度=夏普/恢复因子，walk-forward 验证防过拟合
- **关键原则**：稳定区间 > 精确最优；out-of-sample 验证强制；3-5 参数以内防过拟合

### 2.4 本仓库代码现状

**已落地（L1 验证通过）**
- 前端：`trace-id.ts` 生成规范 trace_id + `jsonl-writer.ts` 同步落盘 + `monitor-bus.ts` SSE 推送
- DreamOS：`event_writer.py` 统一事件写入 + `graph_executor.py` 图执行事件（graph_execute.start/end + node.start/end×8 + checkpoint.saved）
- Bridge：`before_request` 钩子提取 X-Trace-Id 写 JSONL
- 产物中台：`/api/ops/traces` 聚合查询 + `/admin/traces` 看板页面

**缺口（L2-L4 待补）**
- **PostgreSQL 加速**：JSONL 是纯文本 append-only，大数据量查询慢
- **契约测试**：前端↔中台↔DreamOS↔DSH 四系统间无 API 契约验证
- **SLO 体系**：无策略胜率/回撤/延迟的量化目标和错误预算
- **混沌工程**：未模拟极端行情（闪崩、API 超时、数据丢失）
- **自修复闭环**：异常检测 → 认知库 recall → 自动修复/人工审核 链路未建立
- **参数自优化**：交易策略参数仍手动调优，无自动贝叶斯/遗传优化
- **OTel 集成**：无 Prometheus/Grafana 运维级监控

---

## 三、交叉验证

### 3.1 5 维评分

| 维度 | 分 | 说明 |
|------|-----|------|
| 完整性 | 9 | 4 维全覆盖（金融/github/软件工程/代码），无遗漏 |
| 可落地性 | 9 | 每个模式给出文件路径 + 接口签名级细节 |
| 工程适配性 | 8 | 适配 DreamOS/DSH/SACG/FAIL-OPEN/模块化开关 |
| 风险识别 | 8 | 识别 checkpoint 陷阱、OTel 缺口、过拟合、批式风控缺陷 |
| 创新性 | 8 | 决策反哺闭环、分层恢复、稳定区间优化、哈希链审计 |
| **综合** | **8.4** | 7.0-8.9 区间，标注 P0/P1/P2 改进项 |

### 3.2 矛盾项清单

| # | 冲突描述 | 各维立场 | 倾向结论 |
|---|----------|----------|----------|
| 1 | ai-hedge-fund agent 数口径 | README 称 18，不同快照 19/20 | 以 `ANALYST_CONFIG` 注册表为单一真相源，当前 main 20 个 |
| 2 | 自修复深度 | AutoGPT 倾向 LLM 反思式修复；TradingAgents 倾向工程化降级 | **交易场景应以确定性工程降级为主、LLM 反思为辅**（与 FAIL-OPEN 硬约束一致） |

### 3.3 改进项（P0/P1/P2）

| 优先级 | 改进项 | 来源 | 预计工作量 |
|--------|--------|------|-----------|
| **P0** | PostgreSQL 加速（events 表 + 物化视图） | SPEC 原设计 | 1 sprint |
| **P0** | SSE 进度桥（AgentProgress hub + asyncio.Queue） | ai-hedge-fund | 0.5 sprint |
| **P0** | 决策反哺闭环（TradingMemoryLog ↔ 认知库 record/verify） | TradingAgents | 1 sprint |
| **P1** | graph-shape 指纹 checkpoint | TradingAgents issue #1089 | 0.5 sprint |
| **P1** | 三层自修复（指数退避 → 熔断降级 → pipeline 重规划） | AutoGPT/AgentForge | 1 sprint |
| **P1** | 契约测试（Pact 消费者驱动） | Pact | 1 sprint |
| **P2** | OTel 集成（OpenLIT + Prometheus + Grafana） | 开源缺口 | 1-2 sprint |
| **P2** | 混沌工程（Litmus MCP Server） | Netflix | 1 sprint |
| **P2** | 遗传算法参数优化（walk-forward 验证） | MT5/量化实践 | 2 sprint |
| **P2** | JSONL 哈希链审计 | 金融审计实践 | 0.5 sprint |

---

## 四、可落地结论

### 4.1 四层落地路径（与 SPEC 原文对齐）

#### L1 可观测（P0，已完成基线，待补 PostgreSQL）

| 能力 | 状态 | 代码路径 | 下一步 |
|------|------|----------|--------|
| trace_id 生成与传播 | ✅ 已落地 | `3.1-FRONTEND/src/lib/trace-id.ts` | 加 `causation_id` 因果链 |
| JSONL 事件流 | ✅ 已落地 | `events/{frontend,dreamos,dsh,hub}/{date}.jsonl` | 接入 PostgreSQL |
| 中台聚合查询 | ✅ 已落地 | `7-产物中台/app/api/ops/traces/route.ts` | 加物化视图 |
| 中台看板页面 | ✅ 已落地 | `7-产物中台/app/admin/traces/page.tsx` | 加 SLO 仪表盘 |
| PostgreSQL 加速 | ⏳ P0 | — | 建 `dreamos_sessions`/`dreamos_spans`/`dsh_subagent_calls` 三张表 |

#### L2 自检测（P0-P1）

| 能力 | 优先级 | 实现路径 | 参考模式 |
|------|--------|----------|----------|
| 测试金字塔 | P0 | DreamOS nodes 覆盖率 70% + DSH subagents 覆盖率 70% | — |
| 契约测试 | P1 | Pact 消费者驱动，前端↔中台↔DreamOS↔DSH | Pact Broker + can-i-deploy |
| BrowserSkill CI 冒烟 | P0 | 关键路径 3 分钟 + nightly 全量 | 现有硬约束 |
| 回测 nightly cron | P1 | `dream-backtest-verify` 嵌入 cron | 现有 SKILL |
| DreamOS 健康检查 | P1 | 节点注册表完整性 + Budget 余量 + Reflector 异常率 | SRE SLI/SLO |
| DSH 健康检查 | P1 | 9 subagent 心跳 + SubagentOutput 4 字段非空率 | SRE SLI/SLO |
| 异常自动写认知库 | P1 | `tags=["auto-detected","anomaly"]` | 认知库 record |

#### L3 自修复（P1-P2）

| 能力 | 优先级 | 实现路径 | 参考模式 |
|------|--------|----------|----------|
| Trace Replay 引擎 | P1 | `POST /api/ops/replay {trace_id, target_env}` | LangGraph checkpoint replay |
| 自动 bugfix 闭环 | P2 | 异常检测 → recall → dream-bugfix-workflow | AutoGPT reflect_on_failure |
| 灰度与回滚 | P2 | Registry 版本化节点 + 流量比例切分 | Canary deployment |
| 断路器与降级 | P1 | 连续失败 3 次熔断 30 分钟 + LLM 降级链 | AgentForge 三层恢复 |

#### L4 自迭代（P2-P3）

| 能力 | 优先级 | 实现路径 | 参考模式 |
|------|--------|----------|----------|
| hermes 反思自动化 | P2 | 每日 cron 分析 24h trace/bug/修复 → skill-creator | 现有 SKILL |
| 参数自优化 | P2-P3 | 贝叶斯优化（交易策略）+ cost_ms 自适应（调度） | 遗传算法 + walk-forward |
| 案例库自动 ingest | P2 | SACG 循环后自动判断学习价值 → evolution-case-ingest | 现有 SKILL |
| 文档自同步 | P2 | 代码变更 → dream-doc-sync-workflow → 认知库 record | 现有 SKILL |

### 4.2 关键架构决策（已确认）

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 编排模型 | Hub-Spoke (DreamOS 中心) | 与 SACG + Matryoshka 学术背书一致；Trace 链路最短 |
| 数据底座 | PostgreSQL 加速版 | 没有它 L1 大数据量查询建不起来 |
| 自运行优先级 | 自测试 → 自修复 → 自迭代 | 底盘不稳则空中楼阁；与 BrowserSkill 硬约束一致 |
| 可观测性栈 | 轻量自建：JSONL + 中台 dashboard + 认知库 | 符合"代码驱动、不盲目引外部依赖"偏好；保留向 OTel 平移可能 |
| DSH 持久化 | 内存 + 关键结果落 PostgreSQL | SSOT 仍在 intent-schema.ts，避免过度设计 |
| 认知库 | 保留 SQLite，作为领域知识库 | 与业务库职责分离；通过 record 时同时写 JSONL 接入事件流 |

---

## 五、数据迁移策略（JSONL → PostgreSQL）— P0 补充

### 5.0.1 迁移原则

| 原则 | 说明 | 硬约束来源 |
|------|------|-----------|
| JSONL 为 SSOT | append-only，永不修改，所有修复以 JSONL 重放为准 | HC-9 FAIL-OPEN |
| PostgreSQL 为物化视图 | 查询加速层，可丢弃重建 | SPEC-20260928 |
| 双写一致性 | 先写 JSONL，成功后再写 PostgreSQL；失败仅 warning | FAIL-OPEN |
| 零停机迁移 | 新旧双写并行，读切换后旧写下线 | 零回归 |

### 5.0.2 目标 Schema（3 张表）

```sql
-- 1. dreamos_sessions（DreamOS 图执行会话）
CREATE TABLE dreamos_sessions (
    id BIGSERIAL PRIMARY KEY,
    trace_id VARCHAR(64) NOT NULL,           -- 20260929-143022-FE-a3f9k2m1
    session_id VARCHAR(64) NOT NULL,         -- DreamOS cycle_id
    graph_name VARCHAR(64) NOT NULL,         -- trading_agent / market_analysis 等
    status VARCHAR(16) NOT NULL,             -- running / completed / failed / timeout
    start_ts TIMESTAMPTZ NOT NULL,
    end_ts TIMESTAMPTZ,
    duration_ms INTEGER,
    total_nodes INTEGER,
    executed_nodes INTEGER,
    budget_tokens INTEGER,
    used_tokens INTEGER,
    termination_reason VARCHAR(128),
    extra JSONB,                             -- 扩展字段（state.extra 快照）
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_dreamos_sessions_trace_id ON dreamos_sessions(trace_id);
CREATE INDEX idx_dreamos_sessions_status_start ON dreamos_sessions(status, start_ts);

-- 2. dreamos_spans（节点执行明细）
CREATE TABLE dreamos_spans (
    id BIGSERIAL PRIMARY KEY,
    trace_id VARCHAR(64) NOT NULL,
    span_id VARCHAR(32) NOT NULL,            -- 8 hex
    parent_span_id VARCHAR(32),              -- NULL for root
    node_id VARCHAR(64) NOT NULL,            -- A1/A2/A3/A4/A5/A9/A_YJ_INFER
    node_type VARCHAR(32) NOT NULL,          -- compute / gate / reflect
    status VARCHAR(16) NOT NULL,             -- ok / fail / skip
    start_ts TIMESTAMPTZ NOT NULL,
    end_ts TIMESTAMPTZ,
    duration_ms INTEGER,
    allocated_tokens INTEGER,
    used_tokens INTEGER,
    confidence DECIMAL(5,4),                 -- DECIMAL 铁律
    error_message TEXT,
    meta JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_dreamos_spans_trace_id ON dreamos_spans(trace_id);
CREATE INDEX idx_dreamos_spans_node_status ON dreamos_spans(node_id, status);

-- 3. dsh_subagent_calls（DSH 子代理调用）
CREATE TABLE dsh_subagent_calls (
    id BIGSERIAL PRIMARY KEY,
    trace_id VARCHAR(64) NOT NULL,
    subagent_type VARCHAR(32) NOT NULL,      -- macro / flow / onchain / valuation / risk / portfolio
    request_payload JSONB,
    response_payload JSONB,
    status VARCHAR(16) NOT NULL,
    duration_ms INTEGER,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_dsh_subagent_calls_trace_id ON dsh_subagent_calls(trace_id);
CREATE INDEX idx_dsh_subagent_calls_type_status ON dsh_subagent_calls(subagent_type, status);
```

### 5.0.3 ETL 管道（JSONL → PostgreSQL）

```
┌─────────────┐     ┌─────────────┐     ┌─────────────────┐
│  JSONL 文件  │────→│  ETL Worker  │────→│  PostgreSQL     │
│  (SSOT)      │     │  (Python)    │     │  (物化视图)      │
└─────────────┘     └─────────────┘     └─────────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │  失败队列    │  ← 写入失败时入队，稍后重试
                    │  (Redis)     │
                    └─────────────┘
```

**ETL Worker 实现要点**：
1. **批量导入**：每 1000 条或 5 秒触发一次批量 INSERT
2. **幂等写入**：`INSERT ... ON CONFLICT (trace_id, span_id) DO NOTHING`
3. **失败重试**：Redis 队列暂存失败记录， exponential backoff 重试（3 次后放弃，写认知库 `tags=["etl-failed"]`）
4. **监控指标**：`etl_processed_total` / `etl_failed_total` / `etl_lag_seconds`

### 5.0.4 双写切换计划

| 阶段 | 动作 | 验证 | 回滚条件 |
|------|------|------|----------|
| T0 | 仅写 JSONL（现状） | — | — |
| T1 | 双写：JSONL + PostgreSQL（新代码） | 每日对比 JSONL vs PostgreSQL 记录数 | 不一致率 > 0.1% |
| T2 | 读切换：中台 API 从 PostgreSQL 读 | 响应时间 < 100ms | 查询超时率 > 1% |
| T3 | 旧写下线：停止 JSONL 写入（保留文件） | 7 天无异常 | 任意异常 |

---

## 六、安全合规 — P0 补充

### 6.1 金融级审计

| 审计项 | 实现方案 | 合规对标 |
|--------|----------|----------|
| **操作留痕** | 所有 CREATE/UPDATE/DELETE 写入 `AuditLog` 表（操作人、时间、IP、前后值） | SPEC-20260928 AuditLog 硬约束 |
| **不可变日志** | JSONL append-only + SHA-256 哈希链（prev_hash + hash） | 金融审计实践（Occasio） |
| **数据保留** | JSONL 保留 90 天，PostgreSQL 保留 2 年，AuditLog 永久保留 | MiFID II / 国内监管 |
| **访问控制** | 中台 `/admin/traces` 页面需登录 + RBAC；API 加 JWT 鉴权 | Bloomberg EMRS 模式 |

### 6.2 监管报送

| 报送项 | 频率 | 格式 | 实现 |
|--------|------|------|------|
| 交易决策记录 | 实时 | JSONL + PostgreSQL | 含 trace_id、策略版本、参数、风控检查结果 |
| 风控指标日报 | 每日 | CSV/PDF | 胜率、回撤、夏普、最大回撤、持仓集中度 |
| 异常交易报告 | 实时 | 飞书/邮件 | 触发条件：单日回撤 > 5%、连续亏损 > 3 笔、仓位超限 |
| 策略变更审计 | 每次变更 | AuditLog | 策略参数修改需双人复核（4-eyes principle） |

### 6.3 数据脱敏

| 数据类型 | 脱敏规则 | 存储位置 |
|----------|----------|----------|
| 用户 API Key | AES-256 加密，日志中替换为 `***` | PostgreSQL `encrypted_credentials` 表 |
| 持仓金额 | 日志中保留，对外 API 脱敏为区间（如 "10-50万"） | 应用层处理 |
| 策略参数 | 核心参数（如 V15 马丁倍数）仅存储哈希值 | PostgreSQL + JSONL 同步脱敏 |
| 个人信息 | 手机号/邮箱掩码（138****5678） | 中台展示层 |

### 6.4 合规检查点

```yaml
# 每次交易决策前必须通过
pre_trade_checks:
  - name: 仓位限制
    rule: 单币种仓位 <= 总资金 20%
    severity: block  # 阻断交易
  - name: 回撤限制
    rule: 当日回撤 <= 5%
    severity: block
  - name: 杠杆限制
    rule: 合约杠杆 <= 3x
    severity: block
  - name: 冷却期
    rule: 开仓冷却 4h / 平仓冷却 8h
    severity: block
  - name: 流动性检查
    rule: 24h 成交额 >= $1M
    severity: warn   # 仅警告

# 每次交易执行后必须记录
post_trade_checks:
  - name: 成交价格偏离
    rule: 成交价 vs 预期价偏差 <= 0.5%
    severity: alert  # 告警但不阻断
  - name: 滑点监控
    rule: 滑点 <= 0.3%
    severity: alert
```

---

## 七、风险与待验证

### 7.1 风险矩阵

| 风险 | 等级 | 对策 |
|------|------|------|
| DreamOS 单点瓶颈 | 中 | Registry 支持节点分组 + Budget 限制并发；预留 Event Bus 升级路径 |
| 双写一致性（JSONL + PostgreSQL） | 中 | JSONL 是 append-only SSOT，PostgreSQL 是物化视图；失败时以 JSONL 重放修复 |
| BrowserSkill 验收慢影响 CI | 高 | 分层：冒烟（关键路径 3 分钟）+ 全量（nightly） |
| 自修复误操作 | 高 | L3 强制人工审核环节；所有自动修复必须留 trace_id 可回滚 |
| 认知库噪音 | 中 | 自动 record 默认 C 级，verify 后才升级；定期清理 verify_count=0 且 30 天前的 C 级记忆 |
| 过拟合（参数自优化） | 高 | 强制 walk-forward 验证；3-5 参数以内；稳定区间 > 精确最优 |
| 批式风控缺陷 | 高 | 机构级监控已证明"连续风控替代批式检查"；必须升级到亚秒级 |
| **数据隐私泄露** | **高** | **API Key AES-256 加密；持仓金额区间脱敏；策略参数哈希存储** |
| **LLM 幻觉** | **高** | **L3 自修复强制人工审核；修复方案沙箱验证；禁止自动修改风控规则** |
| **供应链安全** | **中** | **Dependabot 每日扫描；关键依赖锁定版本；安全审计季度执行** |
| **模型漂移** | **高** | **实时漂移检测（特征分布/预测置信度）；漂移 > 阈值时自动降级保守策略** |

### 7.2 待验证项

| # | 待验证 | 验证手段 | 时间节点 |
|---|--------|----------|----------|
| 1 | PostgreSQL events 表写入性能（10万条/日） | 压测脚本 | L1 sprint |
| 2 | Pact 契约测试在多语言环境（TS/Python）的兼容性 | POC | L2 sprint |
| 3 | 遗传算法参数优化在 V15 马丁策略上的效果 | walk-forward 回测 | L4 sprint |
| 4 | Litmus MCP Server 在交易场景的混沌实验 | GameDay | L3 sprint |
| 5 | OpenLIT 一行接入对 DreamOS LangGraph 的侵入性 | 试点 | L2 sprint |
| 6 | **JSONL→PostgreSQL ETL 双写一致性（不一致率 < 0.1%）** | **每日对账脚本** | **L1 sprint** |
| 7 | **审计日志哈希链验证（SHA-256 walker）** | **离线验证脚本** | **L1 sprint** |

---

## 八、参考来源

### 调研笔记（子文档）
- `2-KNOWLEDGE/2-TECHNICAL/金融交易系统可观测性实践调研.md` — 传统金融维
- `.trae/documents/ai-trading-observability-selfhealing-research.md` — GitHub 代码维
- `2-KNOWLEDGE/2-TECHNICAL/软件工程自检测自修复自迭代实践调研笔记_20260929.md` — 软件工程维
- 本仓库代码调研（Agent 产出，见上下文）— 代码现状维

### 外部来源
- Bloomberg B-PIPE / MARS / PORT 官方文档
- FactSet Client Data Integration / Portfolio Analytics
- quant.engineering / breakingalpha.io 监控框架
- W3C TraceContext / OpenTelemetry 官方规范
- ai-hedge-fund / TradingAgents / LangGraph / AutoGPT GitHub 仓库
- Netflix Chaos Engineering / Google SRE Book
- Pact / Spring Cloud Contract 官方文档
- OpenLIT / IBM mcp-context-forge GitHub 仓库
- NAS / AutoML / 遗传算法交易优化学术论文

---

## 九、下一步行动

1. **L1 PostgreSQL 加速**：建 `dreamos_sessions`/`dreamos_spans`/`dsh_subagent_calls` 三张表 + ETL Worker
2. **安全合规落地**：AuditLog 表 + 数据脱敏 + 合规检查点 + 监管报送
3. **L2 测试金字塔**：DreamOS nodes + DSH subagents 覆盖率基线 70%
4. **认知库记录**：`record(content="...", quality_level="B", tags="深度调研,自运行,四层落地,可观测性,可复用")`
5. **送千问二轮评估**：调用 `dream-qwen-eval-collab`，输入更新后的报告
