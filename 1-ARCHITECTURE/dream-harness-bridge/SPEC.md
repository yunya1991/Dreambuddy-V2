# dream-harness-bridge SPEC — 基于 DeepSeek Harness 的 DreamOS 分层嵌入整合项目

> **版本**: v0.4 (边界守护理论补全版)
> **状态**: 📋 待批准启动 Phase 0 POC（含 P0 修正前置）
> **创建日期**: 2026-09-13
> **作者**: 用户决策 + AI 评估
> **定位**: 新项目起点 Spec，不是 DreamBuddy-v2 的改造 Spec
> **前置文档**:
> - [RESEARCH_DEEPSEEK_HARNESS.md](../前端设计/RESEARCH_DEEPSEEK_HARNESS.md) (Harness 调研稿)
> - [docs/RESEARCH_FEASIBILITY_4DIM.md](docs/RESEARCH_FEASIBILITY_4DIM.md) (四维可行性调研报告 v0.1)
> - [RESEARCH_DREAMOS_HARNESS_FULL_ALIGNMENT.md](../RESEARCH_DREAMOS_HARNESS_FULL_ALIGNMENT.md) (全栈八大子系统对齐调研 v0.2，含边界守护理论附录)
> - [RESEARCH_SACG_HARNESS_MAPPING.md](../RESEARCH_SACG_HARNESS_MAPPING.md) (SACG 四层 → Harness 扩展点详细映射设计 v0.1)

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
| HC-1a | dream-harness-bridge/ 不修改 dreambuddy-v2 其他任何目录的代码 | Phase 0 后 git diff 验证范围，仅 dream-harness-bridge/ 内有变更 |
| HC-1b | dream-harness-bridge/ 只通过明确的 Python import 或 IPC 调用 DreamBuddy | import 路径审计 + IPC 协议白名单 |
| HC-1c | dreambuddy-v2 其他目录的测试套件不受 dream-harness-bridge 影响 | 现有 131 测试 + 新增集成测试独立运行，互不干扰 |
| HC-2 | 所有 DreamBuddy 硬约束在新架构下仍生效 | 单元测试 + 集成测试覆盖 MAX_TRIAL_POSITIONS / BDSM direction_constraint / SL/TP 下限 / FAIL-OPEN |
| HC-3 | 交易状态单一真相源在 DreamBuddy | DreamBuddy 内部状态不被 Harness 复制或缓存 |
| HC-4 | 认知记忆系统 DB 单进程独占 | 跨进程只读快照，不共享 DB 句柄 |
| HC-5 | 自进化 reward 信号由 DreamBuddy 内部计算 | Harness 只编排不参与 reward |
| HC-6 | Harness 版本锁定 + 季度升级评估 + 契约测试 + fork 准备 + 降级演练 | (1) package.json 锁定具体 dsh 版本；(2) 对 Cordis 核心 API（ctx.tools/ctx.on/ctx.effect/dispose）写契约测试套件，每次升级先跑契约；(3) 维护内部 fork 准备便于紧急打补丁；(4) 定期降级演练验证"卸掉 Harness，DreamBuddy 独立运行"（F-09）|
| HC-7 | 所有跨语言边界 FAIL-OPEN | 异常默认中性兜底，6 层堆栈日志 |
| HC-8 | Phase 0 POC 未通过不得进 Phase 1 | 验收门槛见第六章 |
| HC-9 | **Plugin 只透传，不决策**——所有交易判断、状态变更、reward 计算必须在 DreamOS Python 侧执行，TS plugin 不得包含 `if rsi >`、`if position >` 等交易逻辑 | (1) 静态扫描 plugin 源码，禁止出现交易判断关键字；(2) 代码审查 checklist 必检项；(3) 单测覆盖 plugin 只做 IPC 调用+结果翻译 |
| HC-10 | **领域代码零 Harness 依赖**——`dreamos/` 下任何文件不得 import Harness/Cordis 类型，Harness 概念只在 `dream-harness-bridge/` adapter 层翻译 | (1) `grep -rn "from harness\|from cordis\|import.*harness\|import.*cordis" dreamos/` 返回空；(2) CI 门禁拦截 |
| HC-11 | **交易领域事件过滤**——`session_consumer` 只消费交易领域事件（node_execution / node_result / graph_node / intent_gate），通用事件（file_edit / shell_command）不得进入认知记忆 DB | (1) 事件白名单校验；(2) 认知 DB 内容审计不含非交易领域记忆 |

> **HC-1 细化说明**：原 HC-1（DreamBuddy-v2 核心代码 0 修改）细化为 HC-1a/HC-1b/HC-1c 三条边界规则，明确"子目录单独项目"的物理隔离边界。验证方式从"git diff 主目录无变更"升级为"git diff 范围检查 + import 路径审计 + 双套测试独立运行"。

### 2.3 边界守护理论（互补不冲突的保证）

> 详细分析见 [RESEARCH_DREAMOS_HARNESS_FULL_ALIGNMENT.md 附录 A](../RESEARCH_DREAMOS_HARNESS_FULL_ALIGNMENT.md#八-a边界守护理论互补如何不变成冲突)

DreamOS 与 Harness 的互补关系建立在**三条核心边界**之上，任何一条失守都会让互补变成冲突：

| 边界 | 规则 | 对应硬约束 |
|------|------|-----------|
| **层间边界** | Harness 只管通用运行时，不侵入交易逻辑；DreamOS 只管交易领域，不重写通用 runtime | HC-9、HC-10 |
| **状态边界** | 交易状态单一真相源在 DreamOS，Harness 不持有不缓存 | HC-3、HC-7 |
| **认知边界** | 自进化 reward 由 DreamOS 内部计算，Harness 只编排不参与 | HC-5、HC-11 |

**三条铁律**（所有 plugin 开发必须遵守）：
1. Plugin 只透传，不决策
2. IPC 失败即 FAIL-OPEN，绝不返回缓存
3. 领域代码零 Harness 依赖

**边界失守滑坡模式**：`"图省事" → "临时方案" → "没人反对" → "成为惯例" → 边界消失`

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

### 3.2 DreamOS 分层：操作系统 vs 交易系统

**重要区分**：DreamOS 包含两层，不是一个东西。

| 层级 | 路径 | 定位 |
|------|------|------|
| **DreamOS 操作系统** | `1-ARCHITECTURE/dreamos/core/` + `registry/` + `evolution/` + `shared/` + `adapters/` + `budget/` | 通用 agent 操作系统内核（SACG 四层 + 注册表 + 自进化） |
| **DreamOS 交易系统** | `1-ARCHITECTURE/dreamos/capabilities/trading/` + `dreamos/nodes/` | 交易领域特化能力层（节点 A0-A9/C1-C5/F1-F5/G1-G2 + 执行/回测/策略） |

> ⚠️ 不要指向 `experiments/ab-trading/`——那是早期实验代码。完整真实的 DreamOS 在 `1-ARCHITECTURE/dreamos/`。

### 3.3 SACG 各层接入 Harness 的具体方式（真实路径）

| SACG 层 | 真实位置（DreamOS 操作系统） | 整合后定位 | Harness 接入点 | 是否保留价值 |
|---------|---------------------------|-----------|---------------|-------------|
| **S 层 Sense（感知）** | `dreamos/core/sense/intent_engine.py` + `scenario_classifier.py` + `recognizers/` | agent/pre-step listener | `agent/pre-step` event | ✅ 不变 |
| **A 层 Arrange（编排）** | `dreamos/core/arrange/graph_planner.py` + `node_selector.py` + `execution_graph.py` + `budget_allocator.py` | agent preset composer | `agent preset` + profile | ✅ 不变 |
| **C 层 Compute（计算+反思维）** | `dreamos/core/compute/graph_executor.py` + `node_runner.py` + `reflector.py` | tool provider + 反思维 listener | `ctx.tools` + `agent/*` events | ✅ 反思维是核心 |
| **C 层 Capability（能力注册）** | `dreamos/core/capability/registry.py` + `router.py` | tool 注册中心 | `ctx.tools` | ✅ 不变 |
| **C 层 交易节点本身** | `dreamos/capabilities/trading/nodes/`（A0-A9/C1-C5/F1-F5/G1-G2，交易系统） | ctx.tools 注册的 tool | `ctx.tools` | ✅ 不变 |
| **C 层 重试/降级** | `core/compute/graph_executor.py` 内置 | 交给 Harness tool pipeline | `tools/pre-execute` / `tools/post-execute` | ⚠️ 瘦身（Harness 已有通用版本） |
| **C 层 反思维决策** | `dreamos/core/compute/reflector.py`（CONTINUE/REDO/INSERT_BEFORE/JUMP_TO/EARLY_TERMINATE） | agent/* event listener | `agent/*` events | ✅ 核心保留 |
| **G 层 Governance（治理+存储）** | `dreamos/core/graph_store/`（store/history/compressor/checkpointer）+ `core/memory/` | session log 下游 consumer | 消费 `session/event` | ✅ 升级（快照→事件流） |
| **自进化 EvolutionEngine** | `dreamos/evolution/engine.py` | DreamBuddy 自有 | 消费升级后 G 层 | ✅ 增强 |

### 3.4 边界划分

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
| R-7 | Python 原生库 ABI 兼容性导致 segfault | **低（反而降低）** | 跨进程独立 IPC server 反而**降低**此风险——崩溃不拖累 Harness。F-06 lazy/optional import + F-08 进程健康检查 + F-05 分路径 fail 兜底。参考记忆 VM-1789089211280-3023a0dc 经验 |
| R-8 | Harness preview 阶段文档与实现不一致 | 中 | 以仓库源码为准，不只信文档 |
| R-9 | Cordis 论文概念在 Python 等价实现不完整 | 中 | OQ-3 研究后再落地（见第九章） |
| R-10 | Phase 0 POC 通过但 Phase 1 发现 1+1>2 不成立 | 中 | Phase 1 验收门槛量化 1+1>2，不成立则回退 |

---

## 七补、四维可行性调研修正（v0.3 新增）

> 来源：[docs/RESEARCH_FEASIBILITY_4DIM.md](docs/RESEARCH_FEASIBILITY_4DIM.md) 四维度调研（A 原理+C 案例+B 流程+D 实证）

### 7补.1 P0 修正（阻塞 Phase 0 启动，必须落地）

| 编号 | 修正内容 | 落地点 | 理由 |
|------|---------|--------|------|
| **F-01** | **IPC 契约版本化 + 显式版本协商** | python-server/protocol.py + bridge-core/src/python-ipc.ts | Harness preview（v0.1.x）API 不稳定，无版本协商=静默破坏。每个 IPC 消息必须含 `schema_version` 字段；adapter 在启动时与 Python server 做版本握手；不兼容版本→adapter 拒绝注册 Python tool，走 FAIL-OPEN |
| **F-02** | **协议级不变式强制硬约束** | python-server/server.py + bridge-core/src/node-tool.ts | 硬约束检查必须是交易 IPC 序列的 mandatory step。adapter 在缺少 `constraint_passed: true` 字段时拒绝转发交易请求给 model。不依赖运行时断言，而是通过协议设计强制。分路径：交易路径 FAIL-CLOSED（constraint_passed 缺失=不交易），非交易路径（memory recall）FAIL-OPEN |
| **F-03** | **写入链路断裂的跨语言检测** | tests/integration/test_linkage_alive.ts | 定义端到端契约测试：每个 IPC 方法必须验证 TS adapter → Python → 响应完整流转。已知反模式（模块实现+测试通过但 IPC pipeline 不调用）跨语言下高危（记忆 VM-1789171650348）。每个 Phase 0 IPC 方法必须有"链路活性测试"：注入请求→验证 Python 收到→验证响应回到 TS→验证 session log 记录 |

### 7补.2 P1 修正（强烈建议，影响 Phase 0 质量）

| 编号 | 修正内容 | 落地点 | 理由 |
|------|---------|--------|------|
| **F-04** | **Plugin 生命周期用子集** | bridge-core/src/index.ts | start/stop/health-check 三态足够。卸载语义="停止进程"，重启=从持久化恢复。明确不支持运行时 provider 热替换（Cordis 论文 temporal composability 在跨进程下只能近似，参考 C6/OQ-10） |
| **F-05** | **分路径 fail 策略** | bridge-core/src/node-tool.ts | 交易路径 FAIL-CLOSED（Python 不可达=不交易），非交易（memory recall/data scan）FAIL-OPEN（降级 no-op）。单一"FAIL-OPEN + 默认关"不足（A7 关键洞察：物理隔离强化硬约束，但需分路径） |
| **F-06** | **Python IPC server 原生库隔离** | python-server/server.py | import 链必须与重原生库（causalml/shap/cv2）惰性隔离（lazy/optional import）。记忆 VM-1789089211280 已验证 segfault 风险。跨进程独立 IPC server 反而**降低**此风险（R-7 已修正） |
| **F-07** | **双端 SDK 抽象** | bridge-core/src/sdk/ + python-server/sdk/ | TS 侧 adapter SDK + Python 侧 server SDK，隐藏 wire format。共享 JSON Schema 作为 single source of truth，双端 codegen（TS: json-schema-to-typescript；Python: pydantic）。手写 JSON 解析是反模式（Grafana C3 启示） |
| **F-08** | **进程健康检查** | bridge-core/src/health.ts + python-server/health.py | Sidecar 模式经典风险（B1）。Python IPC server 心跳（每 5s 向 TS 报 alive）；孤儿进程清理（Harness 退出时发 SIGTERM 给 Python）；Harness 退出时优雅关闭 IPC server（drain in-flight requests 5s 后强制 kill） |
| **F-09** | **HC-6 补强** | 见 2.2 节 HC-6 已更新 | 已在 HC-6 中补强：(1) 契约测试套件；(2) 内部 fork 准备；(3) 定期降级演练 |
| **F-10** | **反思维决策跨语言语义等价性** | tests/integration/test_reflection_semantics.ts | OQ-5 升级为 Phase 0 必验项。REDO/INSERT_BEFORE/JUMP_TO/EARLY_TERMINATE 在 TS↔Python 翻译后语义等价性测试。每个反思维决策必须有跨语言等价性测试用例 |

### 7补.3 P2 修正（建议补充，提升长期可维护性）

| 编号 | 修正内容 | 落地点 | 理由 |
|------|---------|--------|------|
| **F-11** | **stdio→gRPC 迁移路径定义** | docs/migration-plan.md | stdio 是 v0.1 选择，Grafana（C3）证明 gRPC 是生产级跨语言 plugin 传输。SPEC 需明确迁移判据：当类型安全/性能成为瓶颈时，迁移到 gRPC + proto。判据：(a) 单次 IPC payload > 1MB；(b) 类型不匹配导致的运行时错误 > 5%；(c) 调试成本超过 gRPC 迁移成本 |
| **F-12** | **事件信封模式** | bridge-core/src/event-envelope.ts + session-consumer/ | adapter 发"信封事件"——外层通用 Harness 事件（tool_call/agent_message），payload 是 DreamBuddy 领域类型（signal_generated/trade_executed/contradiction_detected）。G 层消费 payload，不从通用事件反推领域事实（A4 事件溯源跨上下文标准做法） |
| **F-13** | **不要包装成 Strangler Fig 叙事** | 文档语气调整 | 本方案是稳定共存（Sidecar/Adapter），不是渐进替换（A8/B4/C7 三维一致结论）。错误叙事会误导评审者期待"渐进替换 DreamBuddy" |
| **F-14** | **调试工具配套** | tools/ 目录 | stdio 调试难是真实成本（B5 警示）。补充：(1) 进程级 trace 脚本（strace/dtruss wrapper）；(2) stderr JSON 日志聚合（结构化日志而非裸 stdout）；(3) 双向消息录回放（record/replay 工具） |
| **F-15** | **限制 IPC payload 大小** | bridge-core/src/python-ipc.ts | Airflow Operator 的巨型 context dict 教训（C4）。跨语言下序列化成本高。单次 IPC payload 上限 1MB；超限→分页或引用传递（payload 存共享存储，IPC 只传引用 ID） |

### 7补.4 修正与 Phase 0 验收门槛的映射

| 修正 | 映射的 Phase 0 门槛 | 说明 |
|------|---------------------|------|
| F-01 契约版本化 | V0-1（session log 记录）前置 | 无版本协商的 session log 不可靠 |
| F-02 协议级硬约束 | V0-2（状态隔离）+ V0-7（FAIL-OPEN） | 硬约束强制是 V0-2 的实现机制 |
| F-03 链路活性测试 | V0-1 + V0-5 | 链路活性是 V0-1 和 V0-5 的测试方法 |
| F-04 生命周期子集 | V0-3（fallback/重试） | 生命周期子集决定 fallback 行为 |
| F-05 分路径 fail | V0-7（FAIL-OPEN） | V0-7 需按路径分别验证 |
| F-06 原生库隔离 | V0-4（延迟）+ V0-7 | 原生库 segfault 影响 V0-4 延迟和 V0-7 兜底 |
| F-07 双端 SDK | V0-1~V0-7 所有 | SDK 是所有门槛的实现基础 |
| F-08 进程健康检查 | V0-3（fallback） | 健康检查触发 fallback |
| F-10 反思维语义等价 | V0-5（IntentGateway）扩展 | 反思维是 C 层，与 S 层 V0-5 相关但独立，建议作为 V0-5b |

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

| 编号 | 问题 | 优先级 | 阻塞 Phase | 调研后状态（v0.3） |
|------|------|--------|-----------|-------------------|
| OQ-1 | Cordis plugin 接入 DreamBuddy Python 节点的具体 Cordis API 是什么 | 高 | Phase 0 | **Phase 0 必验**（F-01 契约版本化前置） |
| OQ-2 | Harness session log 的事件 schema 是否足够覆盖 DreamBuddy SACG 四层事件 | 高 | Phase 0 | 需验证 F-12 事件信封模式 |
| OQ-3 | stdio NDJSON vs HTTP JSON-RPC 在 DreamBuddy 节点调用场景下的延迟差异 | ~~高~~ | ~~Phase 0~~ | **已解答**：stdio 优（LSP/MCP/Copilot SDK/stdio Bus 论文实证），需定义 gRPC 迁移路径（F-11） |
| OQ-4 | agent/pre-step listener 能否读取 DreamBuddy 的 IntentGateway 输出（6 种意图类型） | 高 | Phase 0 | **Phase 0 必验**（V0-5 门槛） |
| OQ-5 | agent/* event listener 触发反思维决策（REDO/INSERT_BEFORE/JUMP_TO）的机制 | ~~中~~ → 高 | Phase 0 | **升级为 Phase 0 必验**（F-10 语义等价性） |
| OQ-6 | Cordis 可逆 plugin 卸载时如何回滚 DreamBuddy 节点注册的副作用 | ~~中~~ | ~~Phase 1~~ | **已解答**：跨进程只能近似（A5），用 start/stop/health-check 子集（F-04） |
| OQ-7 | G 层消费 session log 的具体 projection 机制 | 中 | Phase 1 | 需验证 F-12 事件信封模式 |
| OQ-8 | Model-as-Plugin 配置驱动的 LLM 降级链 schema | 中 | Phase 1 | 不变 |
| OQ-9 | Trajectory view 是否需要自定义 event source 标注 S/A/C/G 四层 | 低 | Phase 1 | 不变 |
| OQ-10 | Cordis 论文 temporal/spatial composability 在 Python 等价实现的差距 | ~~低~~ → 中 | Phase 2 | **部分回答**：C6 拆解 Capability Seams 三角色映射，论文细节仍待验证 |
| **OQ-11** | "TS runtime + Python 领域 plugin"无先例的风险评估（D10 结论"有计划的创新"） | **高** | Phase 0 | **v0.3 新增**：需持续评估，Phase 0 POC 是关键验证 |
| **OQ-12** | 进程健康检查与孤儿进程清理的具体实现（F-08 Sidecar 模式经典风险） | **中** | Phase 0 | **v0.3 新增**：心跳间隔、超时阈值、SIGTERM→SIGKILL 降级序列需设计 |

---

## 十、目录结构（子目录单独项目方案）

### 10.1 整体定位

dream-harness-bridge 是 dreambuddy-v2 仓库内的**子目录单独项目**，物理隔离 + 明确边界规则。

```
dreambuddy-v2/                              # 现有项目，整体不动
├── 0-系统文档管理/                           # 不动
├── 1-ARCHITECTURE/                          # ← 架构层
│   ├── dreamos/                             # ← 不动（Python，131测试+硬约束+自进化）
│   │   ├── apps/
│   │   ├── adapters/
│   │   ├── budget/
│   │   ├── cli/
│   │   ├── data/
│   │   ├── evolution/
│   │   ├── registry/
│   │   └── ...
│   ├── skills/                              # 不动
│   │   └── dreambuddy-os/SKILL.md
│   ├── 前端设计/                             # 不动
│   │   └── RESEARCH_DEEPSEEK_HARNESS.md     # 调研稿（已创建）
│   └── dream-harness-bridge/                # ← 唯一新增子目录（单独项目）
│       ├── SPEC.md                          # 项目起点 Spec（本文件）
│       ├── README.md                        # （后续创建）
│       ├── .gitignore                       # 排除 node_modules / dist / .venv
│       ├── package.json                     # TS 侧依赖锁定（dsh 版本锁定 HC-6）
│       ├── tsconfig.json                    # TypeScript 配置
│       ├── packages/                        # TS 侧（Harness plugin 适配层）
│       │   ├── bridge-core/                 # Cordis plugin 适配
│       │   │   ├── src/
│       │   │   │   ├── index.ts
│       │   │   │   ├── python-ipc.ts       # Python IPC 客户端（stdio NDJSON）
│       │   │   │   ├── node-tool.ts         # DreamBuddy 节点→ctx.tools
│       │   │   │   ├── intent-listener.ts   # S层→agent/pre-step listener
│       │   │   │   └── reflection-listener.ts  # C层反思维→agent/* listener
│       │   │   └── package.json
│       │   ├── python-server/               # Python 侧（DreamBuddy IPC server）
│       │   │   ├── server.py               # stdio NDJSON server
│       │   │   ├── protocol.py              # IPC 协议定义
│       │   │   ├── requirements.txt        # Python 侧依赖
│       │   │   └── __init__.py
│       │   └── session-consumer/            # G层→session log 下游 consumer（Phase 1）
│       │       ├── src/
│       │       │   └── graph-compressor-adapter.ts
│       │       └── package.json
│       ├── tests/                           # 集成测试
│       │   ├── integration/                 # V0-1~V0-7 门槛测试
│       │   │   ├── test_c1_tool.ts          # V0-1: session log 记录 C1 执行事件
│       │   │   ├── test_state_boundary.ts   # V0-2: DreamBuddy 状态不被 Harness 持有
│       │   │   ├── test_fallback.ts         # V0-3: 失败时 Harness fallback/重试
│       │   │   ├── test_latency.ts          # V0-4: 端到端延迟 ≤ 直接调用 1.5×
│       │   │   ├── test_intent_listener.ts  # V0-5: IntentGateway pre-step listener
│       │   │   ├── test_no_modification.ts  # V0-6: DreamBuddy 代码 0 修改
│       │   │   └── test_fail_open.ts        # V0-7: 跨语言边界 FAIL-OPEN
│       │   └── e2e/                          # 端到端测试
│       └── docs/                            # 项目文档
│           ├── phase0-report.md             # Phase 0 通过后写
│           └── phase1-spec.md               # Phase 1 实施 Spec
├── 2-GOVERNANCE/                            # 不动
├── ...所有其他现有目录...                      # 不动
└── 23-四层闭环自进化交易架构/                    # 不动
```

### 10.2 物理隔离边界规则

```
┌─────────────────────────────────────────────────────────────────────┐
│                    dreambuddy-v2/ (现有项目)                         │
│                                                                     │
│  ┌─────────────────────────┐    ┌──────────────────────────────┐   │
│  │  现有 Python 代码        │    │  dream-harness-bridge/       │   │
│  │  (1-ARCHITECTURE/dreamos │    │  (TS + IPC server)           │   │
│  │   及所有其他目录)         │    │                              │   │
│  │                          │    │  ┌────────────────────────┐ │   │
│  │  ✅ 131 测试              │    │  │ TS 侧:                 │ │   │
│  │  ✅ 硬约束                │◄──┼──┤ Cordis plugin 适配       │ │   │
│  │  ✅ 自进化                │    │  │ (通过 IPC 调用 Python)  │ │   │
│  │  ✅ 交易状态              │    │  └────────────────────────┘ │   │
│  │                          │    │  ┌────────────────────────┐ │   │
│  │  ← 只允许被 IPC 调用      │    │  │ Python 侧:             │ │   │
│  │    不允许被 TS 修改       │    │  │ stdio NDJSON server     │ │   │
│  └─────────────────────────┘    │  │ (import dreamos.* )     │ │   │
│                                  │  └────────────────────────┘ │   │
│                                  └──────────────────────────────┘   │
│                                                                     │
│  边界规则:                                                            │
│  HC-1a: TS 侧不修改 Python 代码（git diff 验证）                       │
│  HC-1b: Python 侧通过 import 访问 dreamos（明确路径审计）                 │
│  HC-1c: 两套测试独立运行（131测试 + 集成测试）                           │
└─────────────────────────────────────────────────────────────────────┘
```

### 10.3 跨语言调用链路

```
Harness (TS/Node.js)
  │
  ▼ Cordis ctx.tools 注册
node-tool.ts (TypeScript)
  │
  ▼ stdio NDJSON IPC
  │
  ▼ {"method": "execute_node", "node_id": "C1", "params": {...}}
  │
python-server/server.py (Python)
  │
  ▼ import dreamos
  │
  ▼ from dreamos.adapters.skill_adapter import SkillAdapter
  │   from dreamos.registry.node_registry import NodeRegistry
  │
  ▼ NodeRegistry().get("C1").execute(state)
  │
  ▼ 执行结果 + 硬约束检查 + FAIL-OPEN 兜底
  │
  ▼ {"ok": true, "result": {...}}
  │
  ▼ stdio NDJSON 返回
  │
node-tool.ts 解析结果 → ctx.tools 返回 model-facing tool result
  │
  ▼ Harness session log 记录（V0-1 验收门槛）
```

### 10.4 与现有项目的关系

| 维度 | 说明 |
|------|------|
| 仓库 | 同一 git 仓库 dreambuddy-v2 |
| 目录 | 子目录 1-ARCHITECTURE/dream-harness-bridge/ |
| 依赖 | TS 侧通过 IPC 调用 Python 侧；Python 侧 import dreamos.* |
| 测试 | 两套测试独立运行：现有 131 测试 + 新增集成测试 |
| CI | 同一 CI，但测试任务分离（pytest 跑 Python，vitest 跑 TS） |
| 部署 | 单仓库部署，dream-harness-bridge 作为可选启动入口 |
| Plan B 放弃时 | 删 dream-harness-bridge/ 一个目录即可，现有项目零影响 |

---

## 十一、推进 checklist

### Phase 0 启动前
- [ ] 用户批准本 SPEC v0.3
- [ ] 确认路径 E 为最终方案，路径 A/B/D 不再考虑
- [ ] 确认子目录单独项目方案（dreambuddy-v2/1-ARCHITECTURE/dream-harness-bridge/）
- [ ] 确认 HC-1a/HC-1b/HC-1c 三条边界规则
- [ ] 确认 Phase 0 POC 选 C1 技术扫描节点 + IntentGateway 作为验证对象
- [ ] 确认 IPC 协议默认 stdio NDJSON（OQ-3 已解答：stdio 优，需定义 gRPC 迁移路径 F-11）
- [ ] **P0 修正落地**（F-01 契约版本化、F-02 协议级硬约束、F-03 链路活性测试）
- [ ] **P1 修正落地**（F-04 生命周期子集、F-05 分路径 fail、F-06 原生库隔离、F-07 双端 SDK、F-08 进程健康检查、F-10 反思维语义等价性）
- [ ] **HC-6 补强落地**（F-09 契约测试+fork 准备+降级演练）

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
| v0.2 | 2026-09-13 | HC-1 细化为 HC-1a/HC-1b/HC-1c 三条边界规则；第十章改为子目录单独项目方案，增加物理隔离边界图、跨语言调用链路图、与现有项目关系表 |
| v0.3 | 2026-09-13 | 四维可行性调研修正：新增"七补"章节（15 条 F-XX 修正，P0/P1/P2 三级）；HC-6 补强（F-09 契约测试+fork+降级演练）；R-7 修正（独立进程反而降低 ABI 风险）；第九章新增 OQ-11/OQ-12，标注已解答项；checklist 增加 P0/P1/HC-6 落地项；前置文档增加四维调研报告 |
| v0.4 | 2026-09-14 | 边界守护理论补全：新增 HC-9（Plugin 只透传不决策）、HC-10（领域代码零 Harness 依赖）、HC-11（交易领域事件过滤）三条边界防护硬约束；新增 §2.3 边界守护理论章节（三条核心边界 + 三条铁律 + 滑坡模式）；前置文档引用升级至全栈对齐调研 v0.2 |
