# REVIEW v2: 通用金融 Agent 平台 × AI 交易产品 — 定位换位、能力迁移与对标逆向

> 日期：2026-11-13（v2 定位修正）
> 用户拍板：①`/dashboard/agent` 为唯一聊天入口；②禁止独立 LobeHub 实例；③脑暴保持现形态不壳化，后期以「DSH 插件 tab」承载扩展，DSH 插件是未来方向；④云端暂不做多用户鉴权；⑤**Agent 工作台升为平台层（通用金融 Agent 平台），AI 交易降为平台内垂直付费产品，不删除既有能力**
> 方法：模块级源码盘点（3 个 Explore 子代理）+ REA 逆向（LobeHub 源码 / DSH 本机包）+ 46/52/53 既有 SPEC 复用

---

## §0 定位（v2 核心变更）

```text
┌──────────────────────────────────────────────────────────┐
│  L1  通用金融 Agent 平台（Agent 工作台 = 平台门户）        │
│      · 唯一聊天入口（吸收 ChatPanel）                     │
│      · 通用能力：行情 / 研究 / 宏观 / 组合 / 风控 / 知识   │
│      · 共享内核：会话 / 模型路由 / MCP / 审批 / 记忆 / 评测 │
│      · DSH 插件 tab（未来方向）                            │
├──────────────────────────────────────────────────────────┤
│  L2  产品包：AI 交易（付费 entitlement）                   │
│      · 保留现有交易页面（图表 / 持仓 / 订单 / 风控看板）   │
│      · 交易工具 profile：只读查询 + 提案 + 异步回测/推演   │
│      · 写路径 → 27 治理 + 13 风控 + Mandate（不经聊天）    │
└──────────────────────────────────────────────────────────┘
```

一句话：**工作台是「商场」，AI 交易是「店中店」**。换的是导航与产品归属，不是删功能、也不是把交易搬进聊天框。

### 0.1 与上一版的差异

| 项 | v1（昨日评估） | v2（今日定位） |
|---|---|---|
| 工作台 | 唯一聊天入口 | **平台门户 + 唯一聊天入口** |
| AI 交易 | 平台的一个能力面 | **平台内垂直付费产品包** |
| 交易 UI | 保留但未定位 | **明确保留，归入产品包** |
| 脑暴 | 建议壳化 | **不改；后期以 DSH 插件 tab 扩展** |
| 付费 | 未讨论 | **entitlement 开关层先行，鉴权后置** |

---

## §1 结论摘要

| 问题 | 结论 |
|---|---|
| 交易能力整体迁移到工作台是否好？ | ❌ 不是整体迁移，而是**分层暴露**：只读观测/解释（高价值）、研究设计（异步）、执行写（仅提案+审批）、常驻守护（不迁移） |
| 谁是付费产品的护城河？ | 底层确定性能力（23/50/42/12/13/27）+ 认知记忆，不是聊天壳 |
| 工作台像 LobeHub 到什么程度？ | 协议语义同构，功能面差距集中在「多 MCP / 服务端会话 / 工具审批」，三项均自建可控 |
| DSH 插件 tab 是否有现成落点？ | 有：53 模块已有 Cordis 插件规范与市场索引；前端只需新增路由与注册面板 |
| 最大风险 | 平台层与交易产品边界腐化（交易逻辑渗进平台）+ 付费开关可绕过 |

---

## §2 交易侧能力盘点（源码事实）

### 2.1 决策/智能链

| 模块 | 主入口 | 能力 | 状态/副作用 | 建议消费方式 |
|---|---|---|---|---|
| 23 四层自进化 | [evolution_pipeline.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/evolution_pipeline.py) | L1→L2→决策 + L3/L4 反馈闭环 | 强状态、编排级 | 异步任务/定时 |
| 23 事件处理 | [kline_event_handler.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/engines/kline_event_handler.py) | K 线收盘事件、建仓回调 | 强副作用 | 不进聊天 |
| 29 事件驱动 | [event_driven_strategy.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/29-事件驱动策略系统/event_driven/event_driven_strategy.py) | `EventSignal`（signal/strength/elasticity/confidence） | 只读输出 | **同步工具（推荐）** |
| 50 主矛盾评估 | [decision.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/50-NN主矛盾评估器/core/decision.py) | evidence→path→4 维裁决→Dominance→约束钳位→执行权校验→决策落盘 | 落盘（需只读模式） | **同步「解释/复核」** |
| 42 协调层 | [signal_bus.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/42-神经网络交易协调层/signal_bus.py) | 信号只读汇聚、fail-open | 只读 | **同步工具（推荐）** |
| 42 参数 | [param_governor.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/42-神经网络交易协调层/param_governor.py) | 只读加载生效参数集 | 只读 | **同步工具（推荐）** |
| 12 三屏趋势 | [engine.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py) | `evaluate_btc_wind_vane()` 确定性闸门 | 只读 | **同步工具（推荐）** |
| 14 V15 马丁 | [run.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/14-V15经典马丁策略/run.py) | `cmd_signal` 信号生成 | 只读 | 同步工具 |

### 2.2 执行/治理/数据

| 模块 | 主入口 | 属性 | 工作台边界 |
|---|---|---|---|
| 22 执行引擎 | [trade_execution_gateway.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/22-执行引擎中心/trade_execution_gateway.py) | 所有 live/paper 下单收口，强制 `PreTradeGate.check()`，`RiskGatedOkxClient` 拦截下单方法 | **绝不进聊天**；最多发起审批单 |
| 27 治理审批 | [app.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/27-策略治理审批系统/app.py) | 流水线/变更包/审批/审计哈希链 | 只做「提案 + 状态查询」 |
| 13 通用风控 | [README](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/13-通用风控模块/README.md) | L1 事前 / L2 仓位 / L3 事后 | 只读解释，不绕过 |
| 18 数据获取 | [data_center_scheduler.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/18-数据获取中心/data_center_scheduler.py) | 采集调度、质量检查 | 后台运行，工作台只查结果 |
| 51 OKX CLI | 执行入口 | 真实交易 | **绝不进聊天** |

### 2.3 迁移价值判定（回答「迁移是不是真好」）

| 层 | 能力举例 | 用户价值 | 风险 | 结论 |
|---|---|---|---|---|
| A 只读观测/解释 | 信号查询、决策解释、风向标、参数、持仓/风控解释、评测报告 | 高（占日常使用 70%+） | 零 | ✅ **同步工具，优先做** |
| B 研究/设计/推演 | 策略设计、回测、参数寻优、进化报告、战略推演、脑暴 | 高（付费卖点） | 中（算力/时长） | ✅ **异步任务 + 沙箱** |
| C 执行写 | 下单、平仓、改参数、停启用策略 | 必要但低频 | 高（不可逆） | ⚠️ **仅提案卡 + 27 审批，聊天不直连** |
| D 常驻守护 | 实时风控主循环、K 线事件、调度器 | — | — | ❌ **不迁移** |

**结论**：迁移「真好」的只有 A + B。C 的价值是「把入口搬过来」，不是「把执行搬过来」；D 搬了反而破坏确定性。

---

## §3 工作台现状与差距（源码事实）

| 能力 | 现状 | 证据 | 结论 |
|---|---|---|---|
| 唯一聊天入口 | ❌ 两个入口 | [ChatPanel.tsx](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/components/features/chat/ChatPanel.tsx#L59) 有脑暴开关；[AgentChatPanel.tsx](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/components/features/agent/AgentChatPanel.tsx) 无 | P0 收口 |
| 导航位置 | AI 交易是一级项，工作台在 collab 分区 | [navigation.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/lib/navigation.ts) | P0 换位 |
| 协议层 | `streamText` + 5 步 loop，仅连 cognition 壳 | [chat/route.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/app/api/agent/chat/route.ts) | 保持 |
| MCP 接入 | 单例单壳 | [mcp-client.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/lib/agent/mcp-client.ts) | P2 多壳 |
| 会话 | localStorage（50 会话/500 条） | `agent-session-store` | P2 服务端化 |
| 工具审批 | 无 | 写工具服务端直接拒绝 | P1 需补 |
| 脑暴 | Python 编排器 + CLI spawn + 180s 超时 | [/api/agent/brainstorm](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/app/api/agent/brainstorm/route.ts) | **按决策不改** |
| DSH 插件 | 53 已有 Cordis 插件规范/市场索引 | 53 SPEC | P2 新 tab |

---

## §4 对标逆向结果

### 4.1 LobeHub（REA，2026-11-13）

- 快照 `910b92354c7c0929`；目标为浅克隆源码，检出 `packages/{agent-runtime,model-runtime,database,skills,heterogeneous-agents}`。
- 事实：2198 文件 / 60.3 万行；manorepo（pnpm）；依赖图 1191 节点/3843 边/**20 个循环**；模式：Monorepo、zustand、TRPC、i18n、SSE、Vitest（1007 测试文件）。
- 已知局限：`apps/web` 未检出 → 路由 0 是检出范围造成的假象，不代表 LobeHub 无页面；REA 正则解析不覆盖复杂 TS。
- 可借鉴（已在 v1 论证）：多 MCP 客户端、服务端会话、工具审批、技能/插件注册表、proactive task。**不建议**借鉴其多租户与插件市场全量。

### 4.2 DeepSeek Harness / DSH（REA + 46 文档）

- REA 对本机 npm 包（`@deepseek-ai/dsh`）只得到 5 个 bundle 文件/704 行，**源码不可静态解析**，结论不采信。
- 有效依据是 [DESIGN-SUPERAGENT-FUSION.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/46-DSH架构/docs/tech/DESIGN-SUPERAGENT-FUSION.md)（已做源码级调研）：
  - 它的骨架：Trigger / Thread / Ticket / Router / Watchdog / Store；
  - 它的空心：上下文只有会话历史、验收靠自报、沉淀只有会话；
  - 我们的补位：L0 六维供给、A 层 OKR + 45 门禁、settle→认知五系统；
  - 红线：单向依赖可卸载、FAIL-OPEN、不双写状态、自吃狗粮。
- 对工作台的直接映射：会话/任务/状态骨架借 DSH 语义，**状态只落 L0**，不新建第二套 Store。

### 4.3 差距收敛

| 缺口 | 采用来源 | 自建/吸收 |
|---|---|---|
| 多 MCP 客户端 | LobeHub | 自建（47 registry 已是事实源） |
| 服务端会话 | LobeHub | 自建（落 38 数据库） |
| 工具审批 | LobeHub | 自建（接 27 审批语义） |
| 任务/线程/触发器 | DSH | 吸收语义，状态落 L0 |
| 插件机制 | DSH（Cordis） | 53 已有规范，前端加 tab |
| 上下文供给/验收/沉淀 | 我们 | 直接复用 L0/45/认知系统 |

---

## §5 目标架构（可落地版）

```text
前端（3.1）
├─ 平台门户 /dashboard/agent        ← 唯一聊天入口（吸收 ChatPanel）
│   ├─ 通用金融工具面（只读）
│   └─ DSH 插件 tab（P2）
├─ 产品区 /dashboard/trade/*        ← AI 交易（付费产品包）
│   ├─ 现有交易页面全部保留
│   └─ 「用 AI 设计策略」入口 → 提案卡 → 27 审批
└─ 治理/监控/概览（不变）

协议层（52）
├─ /api/agent/chat                  ← 共享内核
├─ 模型路由 providers.ts
├─ MCP 客户端（P2 多壳，按产品 profile 过滤）
├─ 会话（P2 服务端化）
└─ 蒸馏桥 outbox → 认知库

能力层（L0 / 47 registry）
├─ 通用金融壳（行情/研究/宏观/组合/风险/知识/评测）
├─ 交易只读壳（12/29/42/50/14/45）
├─ 交易提案壳（27 提案创建，写需 Mandate）
└─ 禁止：22/51 写路径、13 绕过、23 事件主循环

产品开关（entitlement，暂不做鉴权）
└─ 本地配置：product.ai_trading.enabled / tool_profile / quota
```

---

## §6 路线图（P0-P3）

| 阶段 | 内容 | 验收 |
|---|---|---|
| **P0 定位换位** | 导航重排（工作台升平台入口、AI 交易归产品区）；聊天入口收口；保留全部交易页面 | 全站仅 1 个聊天入口；导航符合两层定位；交易页面零删除 |
| **P0 交易只读工具** | 12/29/42/50/14/45 查询工具进工作台（只读 profile） | 工作台可答「信号/决策/参数/评测」；无写能力 |
| **P1 产品包** | entitlement 开关；交易工具 profile；提案卡 → 27 审批；异步回测/推演任务 | 关闭开关后交易工具不可见；提案可审计；异步任务有 trace |
| **P2 DSH 插件 tab** | 新增 tab；Cordis 插件加载/停用；权限沙箱；本地插件注册 | 插件列表可管理；插件不可越权调用交易写 |
| **P2 多 MCP / 会话** | 多壳路由、工具命名空间、服务端会话 | ≥3 壳可用；多设备会话一致 |
| **P3 云端与计费埋点** | 云端 SSE、用量计量、租户字段预留（鉴权后置） | 用量可查；不引入多用户鉴权 |

**明确不做**：部署 LobeHub、脑暴壳化、聊天直连下单、交易逻辑渗入平台通用层。

---

## §7 风险

| 风险 | 等级 | 对策 |
|---|---|---|
| 平台/产品边界腐化 | 高 | 平台工具 profile 白名单；交易工具只在产品包可见 |
| 付费开关被绕过 | 中 | 工具层校验 entitlement，不只靠前端隐藏 |
| 两个聊天入口长期并存 | 高 | P0 强制收口 |
| 聊天驱动不可逆操作 | 高 | 22/51 永不进 profile；提案必须走 27 |
| DSH 第三方插件执行风险 | 中 | 沙箱 + 权限声明 + 默认禁用写 |
| 会话 localStorage 丢失 | 中 | P2 服务端化 |
| 逆向结论被夸大 | 中 | LobeHub 路由 0 是检出假象；DSH REA 仅 bundle，不作架构依据 |

---

## §8 待确认（仅 3 项）

1. **商业模式**：平台通用能力免费、AI 交易付费，是否就是最终口径？付费粒度按「月订阅 / 按策略数 / 按算力」？
2. **交易产品包是否包含实盘入口**：只到「发起审批」还是允许产品内直接下单（后者仍走 22/27，不经聊天）？
3. **DSH 插件来源**：只接本地插件 / 官方市场镜像 / 两者？插件是否允许声明交易只读权限？
