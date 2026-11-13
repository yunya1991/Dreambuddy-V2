# SPEC-52 Agent 工作台平台化与 AI 交易产品包

- **版本**: v0.2（评审应答版）｜ **日期**: 2026-11-13 ｜ **状态**: 🟡 待确认
- **归属**: 52-lobehub协议集成（平台化 / 产品包唯一事实源）
- **上游约束**: [REVIEW v2](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/52-lobehub协议集成/REVIEW-20261113-云端Agent工作台统一底座评估.md)、52 SPEC v0.5.0、46-DSH v0.2、47-MCP SSoT、53-DSH插件 SPEC v0.2、27 治理、22 执行网关、13 风控
- **下游影响**: 3.1-FRONTEND 导航与工作台、协议层、交易产品包、通用设置、计量账本、插件 tab

---

## §0 Executive Summary

### 0.1 一句话定位

**Agent 工作台升为平台层（通用金融 Agent 平台），AI 交易降为平台内垂直付费产品包；保留全部交易能力，按算力计费，靠用户自有交易 API 打通产品内下单。**

### 0.2 决策（ADR）

| # | 决策 | 依据 |
|---|---|---|
| ADR-1 | **两层定位**：L1 平台（工作台/门户/共享内核）+ L2 产品包（AI 交易） | 用户 2026-11-13 定调 |
| ADR-2 | **唯一聊天入口**：`/dashboard/agent` 吸收 ChatPanel；脑暴引擎与 API 不改，仅入口迁移 | 用户拍板 + 现状两入口 |
| ADR-3 | **不部署独立 LobeHub**：只继承协议语义 | D1/D2 维持 |
| ADR-4 | **写路径唯一**：产品 UI 可直接下单，但必经 22 网关 → 13 PreTradeGate → 27 治理；LLM 只能生成提案，不能直下 | 22/13/27 源码事实 |
| ADR-5 | **用户自带交易 API**：通用设置内配置，加密存储；当前仅后端配置，需新增用户级凭证 | 用户口径 |
| ADR-6 | **按算力计费**：计量 token / 工具调用 / 回测算力秒 / 数据查询 / 插件运行秒 | 用户口径 |
| ADR-7 | **DSH 插件双源**：DeepSeek Harness 官方市场 + 我方自封装插件；自有优先推荐，白名单 + 沙箱 | 53 SPEC + 用户口径 |
| ADR-8 | **暂不做多用户鉴权**：单账户本地，数据模型预留 `user_id/tenant_id` | 用户口径 |
| ADR-9 | **不迁移常驻链路**：23 事件主循环、18 调度、实时风控不进入工作台 | REVIEW v2 §2.3 |

### 0.3 不做什么

| 禁止 | 原因 |
|---|---|
| 部署 LobeHub（desktop/server/docker 任一形态） | 第二套 UI + 双记忆 + 第二运维栈 |
| 聊天/LLM 直接调用下单接口 | 不可逆写路径必须有人确认 + 确定性门禁 |
| 把交易逻辑写进平台通用层 | 平台/产品边界腐化 |
| 脑暴改造成 MCP 壳（本阶段） | 用户明确保留现形态 |
| 关闭 13 风控或绕过 27 审批 | 交易安全红线 |
| 允许插件声明交易写权限 | 供应链风险 |

---

## §1 现状核实

| 项 | 事实 | 来源 |
|---|---|---|
| 导航 | AI 交易为一级项；Agent 工作台在 collab 分区 | [navigation.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/lib/navigation.ts) |
| 聊天入口 | ChatPanel（有脑暴开关）与 AgentChatPanel（工作台）并存 | [ChatPanel.tsx](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/components/features/chat/ChatPanel.tsx#L59)、[AgentChatPanel.tsx](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/components/features/agent/AgentChatPanel.tsx) |
| 协议层 | `streamText` + 5 步 loop，仅接 cognition 壳 | [chat/route.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/app/api/agent/chat/route.ts) |
| MCP 客户端 | 单例单壳 | [mcp-client.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/lib/agent/mcp-client.ts) |
| 会话 | localStorage（50 会话 / 500 条） | `agent-session-store` |
| 交易凭证 | 仅后端配置，无用户级配置/连接 | 用户口径 + 22 配置 |
| 下单链路 | 全部收口 22 网关，强制 `PreTradeGate.check()` | [trade_execution_gateway.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/22-执行引擎中心/trade_execution_gateway.py) |
| 治理 | 流水线/变更包/审批/审计哈希链 | [27 app.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/27-策略治理审批系统/app.py) |
| 插件 | 53 已有 Cordis 规范、白名单、市场索引 | [53 SPEC](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/53-DSH插件模块/SPEC-53-DSH插件生态接入总规范.md) |

---

## §2 定位与能力边界

### 2.1 两层结构

```text
L1 通用金融 Agent 平台
├─ Agent 工作台（唯一聊天入口 / 门户）
├─ 通用金融能力（行情/研究/宏观/组合/风险/知识/评测）
├─ DSH 插件 tab（官方市场 + 自有优选）
└─ 共享内核：模型路由 / MCP / 会话 / 审批 / 记忆 / 计量

L2 产品包：AI 交易（按算力付费）
├─ 保留现有交易页面（图表/持仓/订单/风控/复盘）
├─ 产品内下单（用户自有 API → 51 用户 venue → OKX CLI；后端自有链路仍走 22 → 13 → 27）
├─ AI 辅助：只读解释 / 提案 / 异步回测与推演
└─ 产品工具 profile（与平台 profile 隔离）
```

### 2.2 能力分层规则

| 层 | 进工作台形态 | 举例 |
|---|---|---|
| A 只读观测/解释 | 同步工具 | 12 风向标、29 EventSignal、42 信号/参数、50 决策解释、45 评测 |
| B 研究/设计/推演 | 异步任务 | 回测、参数寻优、23 进化报告、43 战略推演、脑暴（现形态） |
| C 执行写 | 仅产品 UI + 人工确认 | 下单/平仓/改参数 → 22/13/27 |
| D 常驻守护 | 不迁移 | 23 事件主循环、18 调度、实时风控 |

---

## §3 功能规格

### F1 导航换位与统一入口（P0）

- 导航分区调整为：**平台（工作台/通用能力/插件）｜产品（AI 交易）｜运营（概览/监控/治理）**。
- `/dashboard/agent` 成为平台默认入口；`/dashboard/trade/*` 全部保留，归入产品区。
- ChatPanel 合并进 AgentChatPanel：会话列表、消息渲染、脑暴开关统一；`/api/agent/brainstorm` 不改。
- 验收：全站仅一个聊天渲染入口；交易页面零删除；脑暴可从工作台触发。

### F2 交易产品包（P1）

- 保留现有交易页面与功能；新增产品包门禁：未开通时页面可见但操作锁定（只读演示）。
- **执行路径双轨（强制隔离）**：
  - **前端 / 产品用户路径**：订单票据 → `POST /api/venue/order-intents`（草稿）→ 人工确认 → `POST /api/venue/order-intents/{id}/confirm` → 51 用户 venue HTTP Bridge → `okx` CLI。**不经过 22 网关**。
  - **后端自有链路**：22 网关 → 13 PreTradeGate → 27 策略/权限校验 → 交易所。凭证与配置全部来自后端，**不读取 51 用户 venue 的任何凭证/状态**。
- 用户凭证：默认 demo；live 需在设置页人工解锁（短语 `UNLOCK LIVE TRADING`，TTL 60s–8h，重启失效）。
- AI 只生成 `order_intent`（草稿），用户点击确认后才进入上述 51 路径。
- 隔离工程：独立凭证目录、独立审计 JSONL、独立 BFF 前缀、独立 bridge token，四条边界互不复用。
- 实现状态（2026-11-13）：
  - 门禁：`src/lib/product/entitlement.ts` + `GET /api/product/entitlement`；`/api/venue/*` 对 `account/`、`order-intents`、`live/`、凭证写入返回 403 `PRODUCT_NOT_ENTITLED`；本地 owner 默认开通，`PRODUCT_AI_TRADING_STATUS=inactive` 可验证锁定形态。
  - 前端锁定：设置页双面板与交易页下单票据在未开通时显示锁定提示，账户数据查询不发起。

### F3 用户交易 API 配置（P1）

- 通用设置新增「用户交易 API」：交易所固定 OKX、label、API Key / Secret Key / Passphrase、环境（模拟/实盘）、连接测试。
- 存储：AES-256-GCM 落 `51-OKX CLI 系统/runtime/user_venue/credentials.enc`（0600，独立密钥文件）；响应永不回传明文，仅返回后 4 位掩码。
- 权限：保存前用该 Key 探测 `account config.perm`；含 `withdraw` 直接拒绝保存。
- 注入：调用时以 `OKX_API_KEY` / `OKX_SECRET_KEY` / `OKX_PASSPHRASE` 仅注入本次子进程，**不写 `~/.okx/config.toml`**。
- 未配置凭证时账户/下单接口 fail-closed（`venue_credentials_missing`），不隐式回落到任何 profile。
- 多账户：首发单交易所单账户，schema 预留多账户。

### F4 按算力计费与 entitlement（P2）

- 计量维度：LLM token（输入/输出）、工具调用次数、回测算力秒、数据查询行数、插件运行秒。
- 统一单位 **CU**（Compute Unit），换算表配置化（初值待定价评审）。
- 流程：reserve（预扣）→ 执行 → settle（结算）→ `usage_ledger` 追加写。
- 余额为 0：平台只读可用；交易产品锁定；回测/推演拒绝并提示。
- 单账户实现：固定 `local` 用户；schema 预留 `user_id/tenant_id`。

### F5 DSH 插件 tab（P3）

- 新增 tab：来源分「官方 / 自有 / 社区（只读展示）」；自有插件置顶推荐。
- 安装流程：发现 → 校验（hash/签名）→ 白名单 → 沙箱 profile 启用 → 审计。
- 插件清单字段：id、version、source、permissions、hash、sandbox、status。
- 权限仅允许：`read:market`、`read:trading`（只读）、`ui:panel`；**禁止 write:trading / fs / net 未声明**。

### F6 工具 profile（P1）

| profile | 可见工具 | 使用方 |
|---|---|---|
| platform | 通用金融只读 + 认知 | 工作台默认 |
| trading_read | 12/29/42/50/14/45 只读 | 交易产品内 AI |
| trading_proposal | 生成 order_intent / 策略提案（不执行） | 交易产品内 AI |
| admin | 治理查询（不写） | 内部 |

- profile 由服务端按产品开关注入，前端不可自选越权。
- 实现（2026-11-13）：`src/lib/agent/tool-profiles.ts` 定义白名单与边界声明；`/api/agent/chat` 接收 `surface`（workbench/trading），服务端结合 entitlement 解析 profile 后过滤 MCP 工具；未开通时 `trading` 自动降级为 `platform`。

### F7 用量与审计可视化（P2）

- 用量页：CU 余额、按维度明细、按会话/任务聚合。
- 审计：每次下单/提案/插件启用写审计事件，关联 trace_id。

---

## §4 架构落点

| 层 | 落点 | 说明 |
|---|---|---|
| 导航 | `src/lib/navigation.ts` | 三分区重排 |
| 工作台 | `src/app/dashboard/agent/page.tsx`、`AgentChatPanel.tsx` | 吸收 ChatPanel |
| 脑暴入口 | 工作台 composer | 复用 `/api/agent/brainstorm` |
| 交易产品 | `src/app/dashboard/trade/*` | 保留 + 门禁 |
| 设置 | `src/app/dashboard/settings/*` | 新增交易 API 配置 |
| 协议层 | `src/app/api/agent/chat/route.ts` + `src/lib/agent/tool-profiles.ts` | profile 注入（已落地）；计量中间件待 P2 |
| MCP | `src/lib/agent/mcp-client.ts` | P3 多壳（本期不阻塞） |
| 凭证 | `51-OKX CLI 系统/src/okx_venue/credentials.py` + 前端 `src/lib/venue-client.ts` | AES-256-GCM + 权限探测（已落地；不使用 `src/lib/trading/credential-vault.ts`） |
| 下单（产品通道） | `src/app/api/venue/[...path]/route.ts` → 51 bridge → `okx` CLI | 用户自有 API；不经 22 |
| 下单（后端通道） | `src/app/api/trade/orders/route.ts` → 22 网关 | 后端自有链路，禁止绕过 13/27 |
| 计量 | `src/lib/billing/meter.ts` + `/api/billing/balance|usage` | reserve→settle，JSONL 账本（已落地） |
| 插件 | `src/app/dashboard/plugins/*` + `src/lib/plugins/registry.ts` + `src/lib/dsh/plugins.ts` | 白名单发现/校验/沙箱启停/审计 + 真实安装（`dsh plugin --profile sandbox add/remove`） |

### 4.1 新增 API

| Method | Path | 用途 |
|---|---|---|
| GET/POST/DELETE | `/api/venue/credentials` | 用户凭证 CRUD（已落地） |
| POST | `/api/venue/credentials/test` | 连接测试（已落地） |
| GET | `/api/product/entitlement` | 产品包开通状态（已落地） |
| GET | `/api/billing/balance` / `/api/billing/usage` | CU 余额 / 明细聚合（已落地） |
| POST | `/api/venue/order-intents` | order_intent 草稿（已落地） |
| POST | `/api/venue/order-intents/{id}/confirm` | 人工确认下单（已落地） |
| POST | `/api/trade/orders` | 后端链路下单（22 网关，非产品通道） |
| GET/POST/DELETE | `/api/venue/*` | 51 用户 venue BFF（health/account/market/order-intent/live/audit） |
| GET/POST | `/api/plugins`、`/api/plugins/{id}/enable`、`/api/plugins/audit` | 插件列表 / 沙箱启停 / 审计（已落地；支持 scoped 包名） |
| GET | `/api/dsh/plugins?profile=sandbox` | 读取本地 DSH profile 已安装插件（package.json + bundles） |
| POST | `/api/dsh/plugins/install` / `/uninstall` | 真实安装/卸载：`dsh plugin --profile <p> add|remove`（白名单 + 核心保护） |

### 4.2 数据表（目标 schema；P2/P3 未落库）

> 当前实现（2026-11-13）：
> - entitlement = 进程内判断（env `PRODUCT_AI_TRADING_STATUS` + 默认开通），未建表；
> - 用户凭证 = `51-OKX CLI 系统/runtime/user_venue/credentials.enc`（AES-256-GCM，0600）；
> - order_intent / live gate = 51 bridge 进程内存态（重启失效）；
> - 审计 = `51-OKX CLI 系统/runtime/audit/user_venue_calls.jsonl` 追加写；
> - F4 用量账本 = `52-lobehub协议集成/runtime/usage_ledger.jsonl`（`PRODUCT_USAGE_DIR` 可覆盖）；
> - F5 插件状态/审计 = 同目录 `plugin_state.json` + `plugin_audit.jsonl`。
> 下表为 P2/P3 引入持久化时的目标 schema。

- `product_entitlement(user_id, product_id, status, balance_cu, updated_at)`
- `usage_ledger(id, user_id, product_id, dimension, quantity, cu_cost, ref, trace_id, created_at)`
- `exchange_credential(id, user_id, exchange, label, cipher_blob, permissions, status, last_tested_at)`
- `order_intent(id, user_id, symbol, side, qty, type, price, risk_snapshot, status, created_at)`
- `plugin_registry(id, name, version, source, permissions, hash, status, installed_at)`
- `plugin_audit(id, plugin_id, action, result, trace_id, created_at)`

### 4.3 落地状态（2026-11-13 审计）

| 规格 | 状态 | 落点 / 缺口 |
|---|---|---|
| F1 导航换位与统一入口 | ✅ 已落地 | `src/lib/navigation.ts` 三分区；`/dashboard/agent` 双模式吸收 ChatPanel；交易页改为入口跳转 |
| F2 产品包门禁 | ✅ 已落地（本地 owner 默认开通） | `src/lib/product/entitlement.ts`、`/api/product/entitlement`、`/api/venue/*` 403 门禁、三面板锁定态 |
| F2 产品内下单双轨 | ✅ 已落地 | 产品：`/api/venue/order-intents` → 51 bridge；后端：`/api/trade/orders` → 22 网关，互不复用凭证 |
| F3 用户交易 API 配置 | ✅ 已落地 | 51 `credentials.py`/`server.py` + 前端 `VenueCredentialPanel` |
| F4 按算力计费与 entitlement | ✅ 已落地（文件账本） | `src/lib/billing/meter.ts`（reserve→settle、只追加账本）+ `/api/billing/balance|usage`；chat 按 token/工具调用结算；`PRODUCT_USAGE_DIR` 可覆盖账本目录；零余额锁定交易面（403 INSUFFICIENT_CU） |
| F5 DSH 插件 tab | ✅ 已落地（含真实安装） | `/dashboard/plugins` 增加「DSH插件」tab：读取 `$DSH_HOME/profiles/sandbox` 安装态；安装走 `dsh plugin --profile sandbox add <pkg>`（仅白名单 npm 包，本地插件不重复安装）；卸载保护 `@deepseek-ai/dsh-base|dsh-headless`；所有动作写 plugin_audit.jsonl |
| F6 工具 profile | ✅ 已落地（白名单按现有壳） | `src/lib/agent/tool-profiles.ts` + `/api/agent/chat` 服务端注入；交易/提案工具待对应 MCP 壳注册后自动生效 |
| F7 用量与审计可视化 | ✅ 已落地 | `/dashboard/usage`：CU 余额/预扣/维度聚合/最近账本 + 用户 venue 审计 + 插件启停审计；导航「运营 → 用量与审计」 |

---

## §5 安全与治理

| 项 | 规格 |
|---|---|
| 凭证加密 | AES-256-GCM；密钥独立文件（0600）；仅在 51 用户 venue 进程内解密注入子进程，后端 22 不读取用户凭证 |
| LLM 边界 | 凭证与明文密钥永不进入 prompt/工具返回；AI 仅见脱敏账户摘要 |
| 下单防重 | 幂等键（intent_id + 客户端 nonce）；重复提交拒绝 |
| 风控 | 13 L1/L2/L3 不绕过；单笔名义上限 + 日亏损上限 |
| 实盘闸门 | 默认 paper；live 需开关 + 确认短语 + 当日二次确认 |
| 插件安全 | 沙箱 profile；权限白名单；hash 校验；默认禁用写 |
| 计费防绕过 | 计量在服务端工具分发与任务调度层，前端仅展示 |

---

## §6 里程碑

| 阶段 | 范围 | 完成判据 |
|---|---|---|
| P0 | 导航换位、唯一聊天入口、交易页面保留 | 单入口 + 三分区 + 零删除 |
| P1 | 用户交易 API、产品内下单、AI 提案 | 配置→测试→paper 下单闭环；密钥不回传 |
| P2 | 算力计量、entitlement、用量页 | 每笔消耗入账；零余额降级 |
| P3 | DSH 插件 tab、多 MCP、服务端会话 | 官方+自有插件可装可用；插件无写权限 |
| P4 | 云端部署与审计可视化 | 云端可用；审计可追溯 |

---

## §7 验收标准

- **G0 入口**：全站仅一个聊天渲染入口；工作台为平台默认页。
- **G1 产品保留**：`/dashboard/trade/*` 全部可达；未开通时只读锁定而非删除。
- **G2 凭证**：保存后接口不回传明文；提现权限 Key 被拒；连接测试可区分网络/权限/签名错误。
- **G3 下单**：产品通道 intent→confirm→51 用户 venue→OKX CLI 全链路 trace（无 intent 的直接调用被拒）；后端通道仍为 22→13→27→交易所，两条链路互不复用凭证。
- **G4 计量**：chat/工具/回测均写 ledger；余额扣减准确；零余额拒绝付费能力。
- **G5 插件**：官方插件可安装；自有插件置顶；插件无法调用交易写接口。

---

## §8 风险

| 风险 | 等级 | 对策 |
|---|---|---|
| 用户 API 密钥泄露 | 高 | 加密 + 不回传 + 日志掩码 + 最小权限 |
| 产品内下单被误触 | 高 | 二次确认 + 默认 paper + 名义上限 + kill switch |
| 平台/产品边界腐化 | 高 | profile 白名单 + 目录隔离 + 评审门禁 |
| 计费绕过 | 中 | 服务端计量 + 追加账本 + 对账 |
| 插件供应链 | 中 | 官方源优先 + hash + 沙箱 + 默认禁写 |
| 两入口回潮 | 中 | G0 门禁 |
| 定价不合理 | 中 | CU 换算表先配置化，灰度调参 |

---

## §9 评审点详细解答（v0.2 补充）

> 以下为建议方案，供确认；标注「待定价评审」的数值在灰度两周后用真实账单校准。

### 9.1 CU 定义与换算表

**建议：计量与定价分离。** CU 只做「成本归一单位」，单价 `unit_price_cny` 独立配置，避免调价时改计量逻辑。

**1.1 基准定义**：1 CU ≈ 默认模型 1k 输入 token 的边际成本。换算表首版：

| 维度 | 计量 | CU 系数 |
|---|---|---|
| LLM 输入 | 每 1k tokens | 1.0 |
| LLM 输出 | 每 1k tokens | 4.0（输出通常 3-4 倍成本） |
| 工具调用（基础壳） | 每次 | 1.0 |
| 工具调用（重型壳：REA/回测触发） | 每次 | 10.0 |
| 回测算力 | 每 CPU 分钟 × 复杂度系数 | 1.0（灰度期按 ¥0.06-0.10/CPU小时校准） |
| 数据查询 | 每 1k 行 | 1.0 |
| 插件运行 | 每 10 秒 | 1.0 |

复杂度系数 = `1 + 0.2 × (标的数 - 1) + 0.1 × (回测年数 - 1)`，上限 5，防止长周期回测把账打穿。

**1.2 预扣/结算**：

- reserve = 预估 CU × 1.2（上限：单次请求 500 CU，单个回测任务 5,000 CU）；
- 执行后 settle 实际值，差额退回；
- 余额 < 10% 提示；= 0 时平台降级为只读，交易产品与回测锁定；
- 免费额度建议 1,000 CU/月（试用），付费包按 CU 充值。

**1.3 单价（目标毛利 30%）**：`unit_price_cny = 单 CU 混合成本 ÷ (1 - 30%)`。按默认模型混合成本 ¥0.0021/CU 测算，首发价 **¥0.003/CU**（毛利约 30%，留少量缓冲）。若实际账单成本 > ¥0.0021/CU，按公式上调或启用模型倍率，不牺牲毛利。账单按日聚合，账本追加写、不更新。

**验收**：同一会话重放 3 次，ledger 金额偏差 ≤ 2%；reserve+settle 后余额 = 期初 - 实际消耗。

### 9.2 首发交易所范围

**建议：首发只支持 OKX，但先抽出适配器接口。**

理由：现有实现是 OKX 单栈（`OKXAdapter` / `OKXCLI` / `OKXSimulatedClient`，见 [trade_execution_gateway.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/22-执行引擎中心/trade_execution_gateway.py) 与 22 `docs/API_SPEC.md`），22 文档虽写「多交易所路由」，实际适配器只有 OKX。首期上多交易所会把「凭证模型 + 下单幂等 + 风控口径」同时放大三倍风险。

**规格**：

- 定义 `ExchangeAdapter` 契约：`marketData / placeOrder / cancelOrder / positions / testConnection` + 能力位（passphrase、testnet、websocket、统一账户）；
- 首发实现 `OkxAdapter`（含 passphrase 字段、模拟盘/实盘切换）；
- 第二个交易所（建议 Binance 或 Bybit）放到 P4，用接口验证抽象是否成立；
- 不支持「一个用户多交易所并行」直到 P4。

**验收**：适配器单测用 mock 覆盖下单/撤单/持仓/连接测试；更换实盘/模拟盘仅改配置不改调用方。

### 9.3 产品内下单边界

**建议：首发仅「手动单」，不做策略自动执行/跟单。** 分三阶段：

| 阶段 | 能力 | 前置条件 |
|---|---|---|
| S1（首发） | 手动单：开仓/平仓/撤单；AI 只生成 `order_intent` 草稿，用户确认后执行 | 用户 API + entitlement + 13 风控 |
| S2（半自动） | 预批准规则集：策略触发后生成待确认单，逐单人工确认 | S1 稳定运行 ≥ 4 周；单笔名义上限；日亏损上限 |
| S3（全自动） | 策略自动执行 | 独立付费档 + 签署风险授权（Mandate）+ kill switch + 日亏损硬上限 + 连续 3 个月 S1/S2 审计无事故 |

理由：27 治理审的是「策略变更」，不是「逐单授权」；自动执行的授权模型、责任边界、审计成本完全不同，不能混在首发里。

**验收**：S1 期间任何无 `intent_id` 的下单请求被 403；自动执行相关开关在 S1 代码中不存在（不是隐藏，而是未实现）。

### 9.4 插件只读交易权限

**建议：首发不向第三方开放 `read:trading`。**

- 第三方插件：仅 `read:market`（公开行情）+ `ui:panel`；
- 自有插件：可申请 `read:trading`（持仓/订单只读），需签名 manifest + 代码评审；
- 理由：持仓与盈亏是最敏感数据，插件 + prompt injection 组合可导致数据外泄；且第三方插件运行在平台进程内，权限边界必须最严。

**若后续开放（P4+）的最小条件**：逐插件用户显式授权、字段级白名单（默认不含订单历史）、调用频控、审计留痕、随时吊销、禁止接触任何凭证。

**验收**：第三方插件调用 `read:trading` 返回 `PERMISSION_DENIED` 且写审计；自有插件权限与 manifest 一致。

### 9.5 未开通产品时的页面形态

**建议：可见但锁定，并区分「未开通」与「未配置」。**

- 未开通（无 entitlement）：页面可见，展示功能说明与静态/演示数据；真实账户数据不加载；破坏性按钮禁用；API 返回 403 `PRODUCT_NOT_ENTITLED`；
- 已开通但未配置 API：页面可用，下单区显示「去配置交易 API」引导；
- 单用户本地阶段：owner 默认开通，付费墙路径先在代码中打通但不启用。

理由：完全隐藏会让用户不知道产品存在，也不利于后续转化；但绝不能在未授权时加载真实持仓。**服务端门禁为准，前端隐藏只做体验。**

**验收**：未开通账号访问交易 API 全部 403；页面无真实数据；配置引导可跳转设置页。

### 9.6 竞品锚点与 30% 毛利测算

**9.6.1 竞品锚点**（公开报道，未逐一核价，仅作定价带参考）

| 平台 | 计费方式 | 锚点 |
|---|---|---|
| Coze / 扣子 | 基础免费 + 专业版按席位/按量 | 付费起步约 ¥39.9/月 |
| Kimi（月之暗面） | 沙箱按小时 + token 另算 | ¥0.072/沙箱小时 |
| Anthropic Claude Managed Agents | 按会话小时 | $0.08/会话小时 |
| Dify | 开源自托管 / 云订阅 | 按部署与席位 |
| LobeHub | 开源自托管 / 云 | 开源免费，云按订阅 |

**9.6.2 定价结构（按算力为主，轻订阅覆盖固定成本）**

| 包 | 价格 | 含 CU | 等效单价 | 说明 |
|---|---|---|---|---|
| 免费试用 | ¥0 | 1,000 CU/月 | — | 只读 + 少量问答 |
| 基础包 | ¥39/月 | 13,000 CU | ¥0.003/CU | 对齐 Coze ¥39.9 入门价 |
| 标准包 | ¥99/月 | 33,000 CU | ¥0.003/CU | 并发/历史/插件位增加 |
| 算力加购 | ¥30 | 10,000 CU | ¥0.003/CU | 不设折扣，守住毛利 |
| 交易产品开通 | 首次充值 ≥ ¥30 | — | — | 不另收订阅费，纯按算力 |

**9.6.3 毛利测算**

| 单 CU 混合成本 | ¥0.003 售价毛利率 | 结论 |
|---|---|---|
| ¥0.0015 | 50.0% | 可降价换量 |
| ¥0.0021 | 30.0% | 目标线 |
| ¥0.0024 | 20.0% | 触发调价 |
| ¥0.0025+ | ≤16.7% | 必须上调或启用模型倍率 |

- 调价触发：连续 7 天实际成本 > ¥0.0021/CU，或单月毛利 < 28%；
- 模型倍率：经济 0.5x / 标准 1.0x / 高级 4.0x，保证换模型不侵蚀毛利；
- 回测定价对标 Kimi ¥0.072/小时：目标将 CPU 成本控制在 ¥0.06-0.10/CPU小时，灰度期用真实账单校准系数。

### 9.7 五项结论汇总

| # | 评审点 | 建议 |
|---|---|---|
| 1 | CU 换算 | 计量/定价分离；1 CU≈1k 输入 token；售价 ¥0.003/CU（成本 ≤¥0.0021 时毛利 30%），对齐 Coze ¥39.9 入门价 |
| 2 | 交易所范围 | 首发 OKX + 适配器接口；第二家放 P4 |
| 3 | 下单边界 | 首发仅手动单；半自动/全自动分 S2/S3，需独立授权 |
| 4 | 插件读权限 | 第三方仅读行情；自有插件可读交易，需签名+评审 |
| 5 | 未开通形态 | 可见但锁定；服务端 403；区分未开通/未配置 |

---

## §10 附录：源码事实索引

- 导航：[navigation.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/lib/navigation.ts)
- 协议层：[chat/route.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/app/api/agent/chat/route.ts)
- MCP：[mcp-client.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/lib/agent/mcp-client.ts)
- 下单网关：[trade_execution_gateway.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/22-执行引擎中心/trade_execution_gateway.py)
- 决策解释：[decision.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/50-NN主矛盾评估器/core/decision.py)
- 信号总线：[signal_bus.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/42-神经网络交易协调层/signal_bus.py)
- 治理：[27 app.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/27-策略治理审批系统/app.py)
- 插件：[53 SPEC](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/53-DSH插件模块/SPEC-53-DSH插件生态接入总规范.md)
