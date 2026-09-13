# dream-harness-bridge SPEC — 基于 DeepSeek Harness 的 DreamOS 分层嵌入整合项目

> **版本**: v0.1 (项目起点 Spec)
> **状态**: 📋 待批准启动 Phase 0 POC
> **创建日期**: 2026-09-13
> **作者**: 用户决策 + AI 评估
> **定位**: 新项目起点 Spec，不是 DreamBuddy-v2 的改造 Spec
> **前置文档**: [RESEARCH_DEEPSEEK_HARNESS.md](../前端设计/RESEARCH_DEEPSEEK_HARNESS.md) (调研稿)

---

## ⚠️ 文档定位

本文件是 **dream-harness-bridge 新项目的起点 Spec**，不是实施 Spec。

目的：
1. 锁定项目方向、设计原则、硬约束边界
2. 划定 DreamBuddy-v2 与新项目的责任边界
3. 定义 Phase 0 POC 的验收门槛 — 必须通过才进 Phase 1
4. 标注开放问题，避免过早进入实施

实施 Spec 在 Phase 0 POC 通过后单独编写。

---

## 一、项目定位

### 1.1 一句话定位

**以 DeepSeek Harness 为通用 agent runtime 基座，以 DreamBuddy-v2 的 SACG 四层为交易领域特化 plugin，通过分层嵌入实现 1+1>2 整合，不重写 DreamBuddy 核心代码。**

### 1.2 核心命题

**Agent = Model + Harness + Domain**

- DeepSeek Harness 公式: `Agent = Model + Harness`（通用 agent runtime）
- 本项目扩展: `Agent = Model + Harness + Domain`（Harness 编排 + 领域特化）
- Domain = DreamBuddy-v2 的 SACG 四层（S 感知 / A 编排 / C 执行+反思维 / G 存储+自进化）

### 1.3 不是什么

| 不是 | 理由 |
|------|------|
| 不是 DreamBuddy-v2 的改造 | DreamBuddy-v2 代码主体保持不动，131 测试 + 硬约束 + 自进化系统完整保留 |
| 不是 DreamBuddy 的 TS 重写 | 重写 = 放弃已验证资产，违背 1+1>2 初衷 |
| 不是把 DreamBuddy 作为黑盒 subprocess | 黑盒化会让 SACG 被 Harness 绕过，拿不到细粒度事件流 |
| 不是替换 DreamOS 编排层 | SACG 与 Harness 是不同抽象层，不竞争不替换，分层嵌入 |

### 1.4 1+1>2 的真实成立条件

5 项真协同（来自调研稿第四章）：
1. Harness append-only session log → 喂养 DreamBuddy A7/A8 自进化
2. Harness Subagent + Agent Teams → 并行化经典指标/基本面 API 调用
3. Harness Trajectory view → G 层可视化审计
4. Cordis 可逆 plugin 挂载/卸载 → 比 DreamBuddy register/unregister 更强
5. Harness Model-as-Plugin → LLM 降级链从硬编码升级为配置驱动

---

## 二、设计原则与硬约束

### 2.1 五条设计原则

| 编号 | 原则 | 含义 |
|------|------|------|
| DP-1 | **不重写** | DreamBuddy-v2 的 Python 代码主体不动，131 测试 + 硬约束 + 自进化系统完整保留 |
| DP-2 | **分层嵌入** | SACG 作为 Cordis plugin 树上的领域特化层，不与 Harness 通用能力竞争 |
| DP-3 | **单一真相源** | 交易状态（仓位/订单/持仓）由 DreamBuddy 内部管理，Harness 不持有 |
| DP-4 | **硬约束不可绕过** | DreamBuddy 的所有硬约束在新架构下必须仍生效，含跨进程场景 |
| DP-5 | **FAIL-OPEN 铁律** | 所有跨语言边界异常 → 中性兜底 + 6 层堆栈日志，绝不阻塞交易热路径 |

### 2.2 项目硬约束（不可妥协）

| 编号 | 约束 | 验证方式 |
|------|------|---------|
| HC-1 | DreamBuddy-v2 核心代码 0 修改 | Phase 0 后 git diff 验证 dreambuddy-v2 主目录无变更 |
| HC-2 | 所有 DreamBuddy 硬约束在新架构下仍生效 | 单元测试 + 集成测试覆盖 MAX_TRIAL_POSITIONS / BDSM direction_constraint / SL/TP 下限 / FAIL-OPEN |
| HC-3 | 交易状态单一真相源在 DreamBuddy | DreamBuddy 内部状态不被 Harness 复制或缓存 |
| HC-4 | 认知记忆系统 DB 单进程独占 | 跨进程只读快照，不共享 DB 句柄 |
| HC-5 | 自进化 reward 信号由 DreamBuddy 内部计算 | Harness 只编排不参与 reward |
| HC-6 | Harness 版本锁定 + 季度升级评估 | package.json 锁定具体 dsh 版本，不自动跟随 preview |
| HC-7 | 所有跨语言边界 FAIL-OPEN | 异常默认中性兜底，6 层堆栈日志 |
| HC-8 | Phase 0 POC 未通过不得进 Phase 1 | 验收门槛见第六章 |

---

## 三、分层嵌入架构（路径 E）

### 3.1 整体分层

```
┌──────────────────────────────────────────────────────────────────────┐
│                  Harness (Cordis) 通用 agent runtime                  │
│                                                                       │
│   Cordis 微内核 · plugin tree · model adapter · sandbox · approval   │
│   turn/step · session log · agent loop · subagent provider            │
└──────────────────────────────────────────────────────────────────────┘
                    │ 分层嵌入（plugin 接入点）
                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│              DreamBuddy-v2 SACG 四层（作为 Cordis plugin）             │
│                                                                       │
│   ┌──────────────────────────────────────────────────────────────┐   │
│   │ S 层 IntentGateway    → 注册为 agent/pre-step listener       │   │
│   │   6 种交易意图分类，零 Token 本地计算                          │   │
│   │   决定是否接受 step / 路由到哪个 agent preset                  │   │
│   └──────────────────────────────────────────────────────────────┘   │
│   ┌──────────────────────────────────────────────────────────────┐   │
│   │ A 层 GraphOrchestrator → 注册为 agent preset composer        │   │
│   │   四维过滤（Token预算/知识库/Regime命中率/标的覆盖）             │   │
│   │   决定本 turn 用哪些 DreamBuddy 节点                          │   │
│   └──────────────────────────────────────────────────────────────┘   │
│   ┌──────────────────────────────────────────────────────────────┐   │
│   │ C 层节点（A0/A1/A2/.../F2 等）→ 注册为 ctx.tools              │   │
│   │   每个 DreamBuddy 节点作为一个 tool 暴露给 model              │   │
│   │   重试/降级交给 Harness tool pipeline                        │   │
│   │   反思维决策（REDO/INSERT_BEFORE/JUMP_TO/...）保留            │   │
│   │   反思维决策注册为 agent/* event listener                     │   │
│   └──────────────────────────────────────────────────────────────┘   │
│   ┌──────────────────────────────────────────────────────────────┐   │
│   │ G 层 GraphCompressor → 改为 session log 下游 consumer        │   │
│   │   消费 Harness append-only 事件流                              │   │
│   │   做交易领域特化的压缩，喂养 A7/A8 自进化                      │   │
│   └──────────────────────────────────────────────────────────────┘   │
│   ┌──────────────────────────────────────────────────────────────┐   │
│   │ 自进化层 EvolutionEngine + A7/A8 + 做梦部 + D-Z-E              │   │
│   │   完全 DreamBuddy 自有，消费升级后的 G 层                       │   │
│   └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.2 SACG 各层接入 Harness 的具体方式

| SACG 层 | 当前在 DreamBuddy | 整合后定位 | Harness 接入点 | 是否保留价值 |
|---------|------------------|-----------|---------------|-------------|
| **S 层 IntentGateway** | experiments/ab-trading/core/intent_gateway.py | agent/pre-step listener | `agent/pre-step` event | ✅ 不变 |
| **A 层 GraphOrchestrator** | experiments/ab-trading/core/chain_planner.py | agent preset composer | `agent preset` + profile | ✅ 不变 |
| **C 层 UnifiedNodeExecutor** | experiments/ab-trading/core/unified_node_executor.py | tool provider + 反思维 listener | `ctx.tools` + `agent/*` events | ✅ 反思维是核心 |
| **C 层 节点本身** | 35 模块 + 11 本地实现 | ctx.tools 注册的 tool | `ctx.tools` | ✅ 不变 |
| **C 层 重试/降级** | UnifiedNodeExecutor 内置 | 交给 Harness tool pipeline | `tools/pre-execute` / `tools/post-execute` | ⚠️ 瘦身（Harness 已有通用版本） |
| **C 层 反思维决策** | CONTINUE/REDO/INSERT_BEFORE/JUMP_TO/EARLY_TERMINATE | agent/* event listener | `agent/*` events | ✅ 核心保留 |
| **G 层 GraphCompressor** | 6-图结构上下文压缩/skills/graph-compressor | session log 下游 consumer | 消费 `session/event` | ✅ 升级（快照→事件流） |
| **自进化 EvolutionEngine** | 1-ARCHITECTURE/dreamos/evolution/engine.py | DreamBuddy 自有 | 消费升级后 G 层 | ✅ 增强 |

### 3.3 边界划分

**DreamBuddy-v2 内部完全保留**：
- SACG 四层 Python 实现
- 131 测试套件
- 所有硬约束代码（MAX_TRIAL_POSITIONS / BDSM direction_constraint / SL/TP 下限 等）
- 自进化系统（EvolutionEngine + A7/A8 + 做梦部 + D-Z-E）
- 认知记忆系统（cognitive_memory.db）
- 交易状态管理（仓位/订单/持仓）
- 数据清洗 Medallion Architecture
- G-05 级联熔断 4 判据
- 非线性多阶段最优路径理论 6 机制联动

**dream-harness-bridge 项目负责**：
- Cordis plugin 适配层（把 SACG 各层包装为 Cordis plugin）
- 跨语言 IPC 协议（Python ↔ TypeScript）
- session log 消费 adapter（把 Harness 事件流喂给 G 层）
- Model-as-Plugin 配置（LLM 降级链配置化）
- Trajectory 可视化 adapter（可选）
- 集成测试（验证硬约束在新架构下仍生效）

---

## 四、技术栈与依赖

### 4.1 技术栈

| 层 | 技术 | 说明 |
|---|------|------|
| Harness 基座 | TypeScript / Node.js ≥18 | DeepSeek Harness 官方栈 |
| Cordis 微内核 | TypeScript | Harness 内置 |
| 适配层 | TypeScript（Cordis plugin）+ Python（IPC server） | 双语言 |
| DreamBuddy 核心 | Python 3.x | 不动 |
| IPC | HTTP JSON-RPC 或 stdio NDJSON | Phase 0 决定 |
| 测试 | Vitest（TS 侧）+ pytest（Python 侧）+ 集成 E2E | 双栈 |

### 4.2 关键依赖锁定

| 依赖 | 锁定版本 | 理由 |
|------|---------|------|
| `@deepseek-ai/dsh` | 锁定到具体 patch 版本 | preview 阶段 breaking changes 风险 |
| Cordis | 跟随 dsh 版本 | 不单独升级 |
| DreamBuddy-v2 | 当前 master 不动 | HC-1 |
| Node.js | ≥18 LTS | Harness 要求 |
| Python | 3.x（与 DreamBuddy 一致） | 不引入新 Python |

---

## 五、Phase 划分

### 5.1 Phase 0 — POC 验证（必做，不可跳过）

**目标**：用一个最简单 DreamBuddy 节点验证分层嵌入可行。

**范围**：
1. 起项目骨架 `dream-harness-bridge/`（本文件所在目录）
2. clone DeepSeek Harness，跑通 `npx @deepseek-ai/dsh web`
3. 写一个 Cordis plugin，把 DreamBuddy 的 **C1 技术扫描节点** 包装为 ctx.tools 上的 tool
4. 通过 Harness 调用 C1，验证：
   - 调用结果在 Harness session log 中可见
   - DreamBuddy 内部状态未被 Harness 复制
   - 失败时 Harness 能 fallback/重试
5. 写一个 agent/pre-step listener，把 DreamBuddy 的 **IntentGateway** 接入
6. 验证意图分类结果影响 turn 路由

**Phase 0 验收门槛（必须全绿才进 Phase 1）**：

| 门槛 | 验证方式 | 失败后果 |
|------|---------|---------|
| V0-1: C1 节点执行结果在 session log 中可见 | 检查 session.jsonl 含 C1 tool call + result | 不通过则路径 E 核心价值不成立，回路径 B 评估 |
| V0-2: DreamBuddy 内部状态未被 Harness 持有 | git diff + 状态来源审计 | 不通过则违反 HC-3，必须修边界 |
| V0-3: C1 失败时 Harness fallback/重试生效 | 故意让 C1 抛异常，观察 Harness 行为 | 不通过则降级链不可用 |
| V0-4: 端到端延迟 ≤ 直接调用的 1.5× | 性能压测（参考 DreamBuddy ST-02） | 不通过则评估 IPC 协议优化 |
| V0-5: IntentGateway 作为 pre-step listener 生效 | 验证意图分类影响 turn 路由 | 不通过则 S 层嵌入路径需重设计 |
| V0-6: DreamBuddy-v2 核心代码 0 修改 | git diff dreambuddy-v2 主目录 | 不通过则违反 HC-1 |
| V0-7: 所有跨语言边界 FAIL-OPEN | 注入异常，验证中性兜底 | 不通过则违反 HC-7 |

**Phase 0 工期预估**：参考工业级 POC 标准为 1-2 周，实际由用户控制。

### 5.2 Phase 1 — 5 项真协同落地

**前置**：Phase 0 全部门槛通过。

**范围**：
1. 接入经典指标系统（`http://127.0.0.1:8092`）+ 基本面 API（`http://49.233.123.96:3456`）作为并行的两个 subagent
2. 验证并行化 + 降级链
3. 把 G 层升级为消费 Harness session log 的下游 consumer
4. 验证事件流喂养 A7/A8 自进化效率提升
5. LLM 降级链升级为 Model-as-Plugin 配置驱动

**Phase 1 验收门槛**：

| 门槛 | 验证方式 |
|------|---------|
| V1-1: 两个 API 并行调用，端到端延迟显著低于串行 | 性能压测对比 |
| V1-2: 单个 API 失败不影响其他 | 故障注入 |
| V1-3: G 层从 session log 投影出的执行图与原快照等价 | A/B 数据对比 |
| V1-4: A7/A8 自进化基于事件流数据效率提升 | 回测对比 |
| V1-5: LLM 降级链从配置切换而非改代码 | 配置变更测试 |
| V1-6: 所有硬约束在新架构下仍生效 | 集成测试覆盖 HC-2 全部清单 |

### 5.3 Phase 2 — 评估是否做 TS 重写

**前置**：Phase 1 验证 1+1>2 真实成立 + Harness 走到 v1.0 稳定版。

**范围**：评估把 DreamBuddy 核心 Python 能力渐进迁移到 TS 的可行性与必要性。

**决策门槛**：
- 1+1>2 在 Phase 1 是否真实成立（量化指标）
- Harness 是否稳定到 v1.0（breaking changes 频率）
- TS 重写的边际收益是否覆盖重写成本 + 重新验证成本

**默认决策**：不重写。仅在上述门槛全部满足且用户明确决策时启动。

---

## 六、关键技术决策

### 6.1 IPC 协议选择（Phase 0 决定）

| 方案 | 优点 | 缺点 | 倾向 |
|------|------|------|------|
| HTTP JSON-RPC | 调试简单，跨语言友好 | 延迟略高，需端口管理 | 中 |
| stdio NDJSON | 无端口，低延迟，与 Harness 风格一致 | 调试稍复杂 | **倾向** |
| WebSocket | 双向，适合流式 | 复杂度高 | 低 |

**默认决策**：stdio NDJSON，与 Harness subagent provider 风格一致。Phase 0 验证后可调整。

### 6.2 失败传播协议

跨语言边界失败必须显式传播，不可静默：

```
DreamBuddy 异常 → Python 进程 exit code + stderr JSON →
Harness plugin 解析 → tools/post-execute event 标记失败 →
Harness tool pipeline 触发 fallback/重试 →
连续失败 → Lark 告警（5分钟≥3次）
```

**协议格式**（stderr JSON）：
```json
{
  "ok": false,
  "error_code": "E2003",
  "error_msg": "节点执行超时",
  "stack": "...",
  "node_id": "C1",
  "fail_open": true,
  "neutral_default": {"confidence": 0.0, "direction": "HOLD"}
}
```

### 6.3 认知记忆系统跨进程访问

**约束**：cognitive_memory.db 单进程独占（HC-4）。

**方案**：
- DreamBuddy 内部独占 DB 句柄
- Harness 通过 IPC 调用 `recall` / `record` / `verify`，不直接访问 DB
- 跨进程只读快照（若需高频读）通过 IPC 批量拉取，缓存短期有效

### 6.4 自进化 reward 信号边界

**约束**：自进化 reward 由 DreamBuddy 内部计算（HC-5）。

**方案**：
- DreamBuddy 内部仍用真实 PnL 通过 `tanh(pnl_pct/0.02)` 归一化到 [-1,1]
- Harness 只负责编排节点调用顺序，不参与 reward 计算
- reward 信号通过 IPC 返回给 DreamBuddy 自进化层，不进 Harness session log

### 6.5 硬约束保护机制

**约束**：所有 DreamBuddy 硬约束在新架构下必须仍生效（HC-2）。

**方案**：
- 硬约束代码仍在 DreamBuddy 内部，不迁移到 Harness plugin
- Harness 调用 DreamBuddy 节点时，节点内部仍执行硬约束检查
- 若硬约束被触发，节点返回 `fail_open=true + neutral_default`，Harness 收到后走 fallback
- 集成测试覆盖所有硬约束清单

---

## 七、风险清单与缓解

| 编号 | 风险 | 级别 | 缓解措施 |
|------|------|------|---------|
| R-1 | Harness breaking changes 破坏整合 | 高 | 版本锁定 + 抽象 IPC 层 + 季度升级评估（HC-6） |
| R-2 | 跨语言 IPC 失败传播不准 | 中 | 显式 exit code 协议 + 超时 + FAIL-OPEN 兜底（HC-7） |
| R-3 | 硬约束在新架构下被绕过 | **极高** | Phase 0 必须验证（V0-2）+ 集成测试全覆盖（HC-2） |
| R-4 | 认知记忆系统 DB 跨进程冲突 | 中 | 单进程独占 + IPC 只读快照（HC-4） |
| R-5 | 自进化 reward 跨进程延迟 | 中 | DreamBuddy 内部仍做自进化，Harness 不参与（HC-5） |
| R-6 | 双系统状态不一致（仓位/订单/持仓） | **极高** | 单一真相源（HC-3）+ 状态来源审计 |
| R-7 | Python 原生库 ABI 兼容性导致 segfault | 中 | 隔离 import 链（参考记忆 VM-1789089211280-3023a0dc 经验） |
| R-8 | Harness preview 阶段文档与实现不一致 | 中 | 以仓库源码为准，不只信文档 |
| R-9 | Cordis 论文概念在 Python 等价实现不完整 | 中 | OQ-3 研究后再落地（见第九章） |
| R-10 | Phase 0 POC 通过但 Phase 1 发现 1+1>2 不成立 | 中 | Phase 1 验收门槛量化 1+1>2，不成立则回退 |

---

## 八、与现有 DreamBuddy 硬约束的兼容性

引用 project_memory.md 中的硬约束，评估在新架构下是否仍生效：

| 硬约束 | 在 dream-harness-bridge 下 | 兼容性 | 验证方式 |
|--------|--------------------------|--------|---------|
| BDSM direction_constraint (LONG_ONLY/SHORT_ONLY/NEUTRAL) | DreamBuddy 节点内部仍执行 | ✅ 兼容 | 集成测试：开空 LONG_ONLY 币种被拦截 |
| BCRM2.0 MAX_TRIAL_POSITIONS = 2 | DreamBuddy 内部统计 | ✅ 兼容 | 集成测试：第 3 单测试仓被拦截 |
| 战略层 enable_five_domain (默认 False) + 7 子开关 | DreamBuddy 内部开关 | ✅ 兼容 | 配置测试 |
| 战略层关断时取中性默认值 | DreamBuddy 内部兜底 | ✅ 兼容 | 配置测试 |
| 五计庙算总分四档决策 | DreamBuddy 内部计算 | ✅ 兼容 | 单元测试 |
| 方案C 8 开关默认 True | DreamBuddy 内部 | ✅ 兼容 | 配置测试 |
| SL/TP 价格空间下限（常规 SL≥4%/TP≥12%） | DreamBuddy 内部 | ✅ 兼容 | 单元测试 |
| SL/TP 爆仓安全边际约束 | DreamBuddy 内部 | ✅ 兼容 | 单元测试 |
| Medallion Architecture 三层数据清洗 | DreamBuddy 内部 | ✅ 兼容 | 数据流测试 |
| quality.py 硬门禁拦截 | DreamBuddy 内部 | ✅ 兼容 | 数据流测试 |
| FAIL-OPEN 铁律 | DreamBuddy + IPC 边界 | ✅ 兼容（需扩展） | 异常注入测试（V0-7） |
| ATR 自适应 SL/TP | DreamBuddy 内部 | ✅ 兼容 | 单元测试 |
| BCRM2.0 最低名义仓位 250 USDT | DreamBuddy 内部 | ✅ 兼容 | 单元测试 |
| BDSM 单币预算 250 USDT | DreamBuddy 内部 | ✅ 兼容 | 单元测试 |
| 战略层 war_state/direction_state | DreamBuddy 内部 | ✅ 兼容 | 单元测试 |
| evolution probe 仓阈值 | DreamBuddy 内部 | ✅ 兼容 | 单元测试 |
| evolution 方向性集中度检查 | DreamBuddy 内部 | ✅ 兼容 | 单元测试 |
| 自进化 reward 信号 | DreamBuddy 内部 | ✅ 兼容（HC-5） | 集成测试 |
| 自进化矛盾权重 [0.3,1.5] | DreamBuddy 内部 | ✅ 兼容 | 单元测试 |
| G-05 不可逆级联熔断 4 判据 | DreamBuddy 内部 | ✅ 增强（事件流记录） | 集成测试 |

**结论**：所有硬约束兼容。FAIL-OPEN 需扩展到跨语言边界（HC-7）。

---

## 九、开放问题

| 编号 | 问题 | 优先级 | 阻塞 Phase |
|------|------|--------|-----------|
| OQ-1 | Cordis plugin 接入 DreamBuddy Python 节点的具体 Cordis API 是什么 | 高 | Phase 0 |
| OQ-2 | Harness session log 的事件 schema 是否足够覆盖 DreamBuddy SACG 四层事件 | 高 | Phase 0 |
| OQ-3 | stdio NDJSON vs HTTP JSON-RPC 在 DreamBuddy 节点调用场景下的延迟差异 | 高 | Phase 0 |
| OQ-4 | agent/pre-step listener 能否读取 DreamBuddy 的 IntentGateway 输出（6 种意图类型） | 高 | Phase 0 |
| OQ-5 | agent/* event listener 触发反思维决策（REDO/INSERT_BEFORE/JUMP_TO）的机制 | 中 | Phase 0 |
| OQ-6 | Cordis 可逆 plugin 卸载时如何回滚 DreamBuddy 节点注册的副作用 | 中 | Phase 1 |
| OQ-7 | G 层消费 session log 的具体 projection 机制 | 中 | Phase 1 |
| OQ-8 | Model-as-Plugin 配置驱动的 LLM 降级链 schema | 中 | Phase 1 |
| OQ-9 | Trajectory view 是否需要自定义 event source 标注 S/A/C/G 四层 | 低 | Phase 1 |
| OQ-10 | Cordis 论文 temporal/spatial composability 在 Python 等价实现的差距 | 低 | Phase 2 |

---

## 十、目录结构（初始）

```
dream-harness-bridge/
├── SPEC.md                    # 本文件
├── README.md                  # （后续创建）
├── packages/                  # （Phase 0 创建）
│   ├── bridge-core/           # Cordis plugin 适配层
│   │   ├── src/
│   │   │   ├── index.ts
│   │   │   ├── python-ipc.ts  # Python IPC 客户端
│   │   │   ├── node-tool.ts   # DreamBuddy 节点作为 ctx.tools
│   │   │   ├── intent-listener.ts  # S 层 agent/pre-step listener
│   │   │   └── reflection-listener.ts  # C 层反思维 agent/* listener
│   │   └── package.json
│   ├── python-server/          # Python IPC server（DreamBuddy 侧）
│   │   ├── server.py
│   │   ├── protocol.py
│   │   └── requirements.txt
│   └── session-consumer/       # G 层 session log consumer（Phase 1）
│       ├── src/
│       │   └── graph-compressor-adapter.ts
│       └── package.json
├── tests/                      # （Phase 0 创建）
│   ├── integration/
│   │   ├── test_c1_tool.ts     # V0-1
│   │   ├── test_state_boundary.ts  # V0-2
│   │   ├── test_fallback.ts    # V0-3
│   │   ├── test_latency.ts     # V0-4
│   │   ├── test_intent_listener.ts  # V0-5
│   │   ├── test_no_dreambuddy_modification.ts  # V0-6
│   │   └── test_fail_open.ts   # V0-7
│   └── e2e/
└── docs/
    ├── phase0-report.md        # Phase 0 通过后写
    └── phase1-spec.md          # Phase 1 实施 Spec
```

---

## 十一、推进 checklist

### Phase 0 启动前
- [ ] 用户批准本 SPEC
- [ ] 确认路径 E 为最终方案，路径 A/B/D 不再考虑
- [ ] 确认 DreamBuddy-v2 核心代码不动（HC-1）
- [ ] 确认 Phase 0 POC 选 C1 技术扫描节点 + IntentGateway 作为验证对象
- [ ] 确认 IPC 协议默认 stdio NDJSON（OQ-3 验证后可调整）

### Phase 0 执行中
- [ ] 项目骨架创建
- [ ] DeepSeek Harness 跑通 `npx @deepseek-ai/dsh web`
- [ ] C1 节点作为 ctx.tools 接入
- [ ] V0-1 ~ V0-7 全部通过

### Phase 0 通过后
- [ ] 写 phase0-report.md
- [ ] 写 phase1-spec.md
- [ ] 用户决策是否进 Phase 1

---

## 十二、与现有文档的关系

| 文档 | 关系 |
|------|------|
| [RESEARCH_DEEPSEEK_HARNESS.md](../前端设计/RESEARCH_DEEPSEEK_HARNESS.md) | 前置调研稿，本 SPEC 基于其结论 |
| [dreambuddy-os SKILL.md](../skills/dreambuddy-os/SKILL.md) | DreamBuddy SACG 四层定义来源 |
| [DreamBuddy project_memory.md] | 硬约束清单来源，本 SPEC 第八章引用 |
| 后续 phase1-spec.md | Phase 0 通过后编写 |

---

## 十三、变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| v0.1 | 2026-09-13 | 首版：定位 / 设计原则 / 分层嵌入架构 / Phase 划分 / 风险清单 / 硬约束兼容性 / 开放问题 |
