# SPEC-56 — L2 架构能力聚合层（契约与 ADR）

> **版本**: v0.9（A0 四契约 v1.1 + A1/A2/A3 已落地；实现状态以 [TECHNICAL_DESIGN.md](./docs/TECHNICAL_DESIGN.md) v1.12 为准）
> **日期**: 2026-11-16
> **状态**: 🟡 修订版 —— 先冻结「L2 是什么、边界在哪、契约是什么」，能力清单与实现状态见 [docs/TECHNICAL_DESIGN.md](./docs/TECHNICAL_DESIGN.md)；修订依据见 [SPEC复审记录-L2能力聚合层-v0.2.md](./SPEC复审记录-L2能力聚合层-v0.2.md)
> **上游 SSoT**:
> - 架构唯一事实源：[SYSTEM_ARCHITECTURE_OVERVIEW.md](../1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md) v4.2
> - 模块归层口径：[3+3架构模块映射.md](../1-ARCHITECTURE/3+3架构模块映射.md) v1.2（§二.2 L2 五子层）
> - 路由边界：[SPEC-v1.4-L0L1L2-路由边界与认知裁决.md](../34-前端应用训练系统/SPEC-v1.4-L0L1L2-路由边界与认知裁决.md) v1.4-r3
> - 层级 MCP：[SPEC-L1L2-MCP-PACKAGING-v0.1.md](../47-MCP管理系统/docs/tech/SPEC-L1L2-MCP-PACKAGING-v0.1.md)
> **下游**: [docs/TECHNICAL_DESIGN.md](./docs/TECHNICAL_DESIGN.md)（能力登记）、06/47/49 各域 SPEC；Harness 能力增强见 [SPEC-56-Harness能力增强-v0.3.md](./SPEC-56-Harness能力增强-v0.3.md)（HCP，复审修订稿）
> **不做什么**: 本文不重复定义 L0/L1 契约，不重写各模块自身 SPEC，不新建业务能力。

---

## §0 摘要

1. **L2 已有可运行骨架**：DreamOS Flask 服务（`0.0.0.0:8000`，12 个 `/api/v1/*` 端点）、34-core 的 Router/Ticket/Mandate 编排件（`router_loop` / `ticket_*` / `mandate_gate` / `gate_45_adapter` / `shell_handles`）、SACG 编排骨架（`sacg_orchestrator` + `okr_nodes` + `okr_acceptance` + `okr_ticket_bridge`）。
2. **L2 已有 5 个层级壳**：`l2.dreamos.mcp`（5 工具）/ `l2.debate.mcp`（3）/ `l2.train.mcp`（3）/ `l2.emergence.mcp`（3）/ 兼容别名 `agent.debate.mcp`（3，deprecated）——L2 活跃工具 **14**，分层配额 L2:30，余量 16。
3. **L2 当前最大缺口不是能力，而是「统一信封 + token 计量 + trace」**。没有 `meta.tokens_used / budget_remaining / model`，层级成本审计与证据边界无法闭合，这也是本文 ADR-03 的由来。
4. **L1 侧准入已可机器判定**（四道闸 G1–G4 + 10 行判定表 + `channel` 三值）；**L2 侧的认知裁决与路线选择已落地**——`cognition_signal` / `l2_route` 由 `runtime/l2_route.py` 裁定、`core/l2_cognition_route.py` 注入，前端落 execution trace 的 `sagc.route`（GAP-13 Closed）。
5. 本文冻结 **10 条 ADR + 6 组接口契约 + 9 道门禁**；能力清单、缺口与推进顺序不在本文，统一登记在 TECHNICAL_DESIGN §2/§6/§7。

---

## §1 定位与非目标

### 1.1 定位

SPEC-56 是 **L2 层的唯一契约入口**：回答「L2 由哪些子层构成、子层之间怎么调用、什么能做/不能做、验收怎么判」，不回答「L2 现在实现了多少」（后者属 TECHNICAL_DESIGN 的能力登记册）。

与 54（L1 能力聚合层）的关系：

| 维度 | 54-L1 | 56-L2 |
|---|---|---|
| 驱动 | 确定性算法/统计，零 token | 生成式 LLM 推理，有 token 成本 |
| 契约核心 | `CapabilityResult`（answer/data/quality） | `L2Envelope`（result/meta/trace/budget） |
| 失败形态 | 确定性降级（`degraded`） | 语义降级 + 裁决复核（`needs_review`） |
| 验收 | 方法门禁（n≥、p_adj）+ MERS 状态机 | 45 业务门禁 + OKR 节点验收 + verdict 四态 |
| 对下游 | 只读出口 | 可写（受 Mandate），可触发训练/辩论/编排 |

### 1.2 非目标

1. 不把 L1 能力搬进 L2：能零 token 确定性回答的问题，一律回 L1（唯一判据见 §2.1）。
2. 不新增业务能力：L2 只编排与生成，业务节点来自 Registry（能力层）或 L1 只读出口。
3. 不重写各模块 SPEC：32 辩论、34 训练、46 DSH、48 涌现、52 LobeHub、53 Cordis 的定义权归各自模块。
4. 不把 DreamOS 做成第二套事实源：Ticket 状态、认知记录、数据一律以 L0 为准（ADR-02）。

---

## §2 层级边界

### 2.1 唯一判据（沿用，不新造）

> **是否依赖生成式 LLM 推理** —— 依赖 → L2；不依赖 → L0 或 L1。

灰区规则（沿用 3+3 v1.2 §二）：

| 规则 | 内容 |
|---|---|
| R1 | 本地模型（嵌入 / FinBERT / KNN / CBR / 贝叶斯 / 统计检验）→ L1 |
| R2 | 工具链（pandas / ta-lib / 规则引擎 / 调度器）→ L0/L1 |
| R3 | 混合组件按**主体能力**归层，无 LLM 子集可降级暴露，但归属不变 |
| R4 | 编排 ≠ 生成（GraphExecutor 属机制；Reflector 的 LLM 部分属 L2） |
| R5 | 只要某路径**必须**经过生成式 LLM 才能完成，该路径即 L2 |

### 2.2 L2 五子层（沿用 3+3 v1.2 §二.2）

```
L2-K 内核编排（DreamOS · 新 SACG）
  S 认知驱动规划入口 → A OKR 节点验收 → C 执行驱动 → G 压缩沉淀；C-drive 贯穿
  横切：NodeRegistry / Evolution / Budget / Adapters
        ↓
L2-E 执行编排（DSH Router / Worker）
  常驻 Router（单轮批处理）+ Worker 角色池（每角色工具数受 `enums.max_tools_per_shell` 约束，当前 15）+ Ticket/Mandate + 会话可续
  载体：34-前端应用训练系统/core
        ↓
L2-G 生成式能力层
  32 辩论 / 34 训练 / 48 涌现 / 25 策略生成 / 30 E2E / 3-EVOLUTION
        ↓
L2-P 协议接入层
  46 DSH Harness / 52 LobeHub / 53 Cordis / 24 图压缩
        ↓
L2-A 应用与前端
  3.1 主前端（3001）/ 6 交易中台（bridge 3847）
```

### 2.3 子层职责与失败形态

| 子层 | 回答什么 | 关键载体 | 失败形态 | 是否可被外部宿主调用 |
|---|---|---|---|---|
| L2-K | 一次请求该怎么规划、验收、执行、沉淀 | `dreamos/apps/api_server.py`、`34/core/sacg_orchestrator.py` | 作业失败 / 预算耗尽 / 降级为 L1 事实回答 | ✅ 经 `l2.dreamos.mcp` |
| L2-E | 谁来干、干到哪、断了怎么续 | `34/core/router_loop.py`、`ticket_*`、`mandate_gate.py` | Ticket `paused` / 重启恢复 / 越权拒绝 | ⬜ 暂无 `l2.dsh` |
| L2-G | 需要生成时产出什么 | 32/34/48/25/30 | `inconclusive` / `falsified` / 人工复核 | ✅ 经 `l2.debate/train/emergence` |
| L2-P | 外部协议怎么接、插件怎么装 | 46/52/53/24 | fail-open 降级、deny-by-default 拒绝 | ❌ 宿主侧协议，不做能力面 |
| L2-A | 用户怎么用 | 3.1 / 6 | 前端降级、任务异步化 | ❌ 应用层 |

### 2.4 跨层职责边界（2026-11-16 定位决策）

| 层 | 本质 | 核心工作 | 红线 |
|---|---|---|---|
| **L0** | 确定性能力 | 事实、状态、调度、预算、注册表 | 零 LLM；不做统计判定与业务判断 |
| **L1** | 统计方法 + 涌现架构 | 维护 + **发现**：显著、异常、相似、涌现线索 | 只给候选与证据，不给叙事结论 |
| **L2** | 生成与编排 | **对内：开发端修 bug、做优化（主负载）**；对外：规划/裁决/生成 | 不替 L1 做统计判定；不自证验收 |

**口诀**：**L0 给事实，L1 给证据，L2 给动作。**

由此产生的三条契约约束：

1. **发现权在 L1**：开发端任务的优先级必须来自 L1 的发现（异常/漂移/失效假设/显著机会）或显式 bug 报告，禁止 L2 自行认定「值得优化」。
2. **判定权在 L2、验收权在 45**：L2 可以决定怎么修，但不能宣布修好了；回归与 45 裁决是外部证据（ADR-06）。
3. **计量归 L2、事实归 L0**：开发端闭环的 token 成本、trace、回归结果必须落 `L2Envelope` 并回写 L0，形成可审计的修复台账（ADR-03）。

### 2.5 开发端闭环（L2 主负载）

状态机定义在 `contracts/state_machine.yaml`（7 态 / 10 条边，**不可跳步，非法边直接判红**），由 `scripts/validate_contracts.py` 强制执行：

| from → to | guard | 语义 |
|---|---|---|
| reported → reproduced | `evidence.repro.cmd` 非空且 `fails_on_base=true` | 基线必须失败 |
| reported → abandoned | `reason` | 无法复现 |
| reproduced → root_caused | `root_cause` ≥10 字 | — |
| reproduced → abandoned | `reason` | 放弃 |
| root_caused → fixed | `change_ref.sha` 存在 | — |
| root_caused → abandoned | `reason` | 放弃 |
| fixed → regression_passed | `runner ∈ {pytest,ci,gate45}` 且 `passed=true, exit_code=0` | — |
| fixed → root_caused | `passed=false` + `reason` 必填 | **重开边**，`attempts+1` |
| regression_passed → settled | `settled` 四值齐全 + `run_ids` 非空 | — |
| regression_passed → abandoned | `reason` | 放弃 |

初始态 `reported`；终态 `settled` / `abandoned`；`attempts > 3` 或超 SLA 只能转 `abandoned`。

硬约束：

1. `reported` 必须指向 **L1 发现**或显式**缺陷报告**，禁止 L2 自述「这里可以优化」（G-L2-7）。
2. `regression_passed` 必须给出可复跑命令与结果，不接受「人工确认」（G-L2-8）。
3. 优化类任务必须给出**同一测试集的前后对照**；否则只能标 `candidate`，不得称「提升」。
4. `settled` 必须产出台账记录（IF-5）并回写 L0；四分流沿用 ADR-06。

### 2.6 自扩展插件边界（借鉴 Cordis / Creator Mode）

参考实现：DeepSeek Harness Creator Mode（2026-11-02）以 **Cordis 可逆依赖图**为底座，提供「自检 → 内存实验 → 安装/Preset → 卸载回滚」四段能力。我们只采纳机制，不引入其运行时。

| 段 | 语义 | 我们的准入 |
|---|---|---|
| inspect | 只读返回已加载插件、依赖、事件通道、能力面 | 可先开放（只读） |
| experiment | 内存构建与试跑，不落盘、失败不污染 | 需沙箱隔离后开放 |
| install / preset | 安装需 Mandate + 白名单 + `plugin_ready`；preset 可导出分发 | **必须通过 G-L2-9** |
| unload | 卸载回滚副作用（订阅/连接/句柄/定时器） | **无此能力前禁止 install（ADR-10）** |

---

## §3 ADR（本层已冻结的架构决定）

| # | 决定 | 理由 | 约束落地 |
|---|---|---|---|
| **ADR-01** | L2 对 L1 **只读** | L1 是零 token 事实源，写操作会破坏确定性链路 | 层级角色只挂 `l1.trading` 9 个只读 + `l1.intent` / `l1.strategy` / `l1.ops` 只读工具；`forward_signal` 不进 L2 角色 |
| **ADR-02** | L2 **不持有第二套权威状态** | Ticket / 认知 / 数据都以 L0 为单一事实源，否则重启与审计失效 | `ticket_store.py` 只做 L0 追加写与恢复；DreamOS 不直连 DB，走 L0 壳或 in-process DAL |
| **ADR-03** | L2 每个出口必须返回**统一信封**（含 token 计量） | 没有 `tokens_used / budget_remaining / model` 就无法做层级成本审计与证据边界 | 见 §4.3 `L2Envelope`；现网先补 `meta`，再补 `trace` |
| **ADR-04** | L2 写操作一律 **Mandate + 预算 + trace** 三件套 | 训练触发、编排提交、信号写入都是不可逆副作用 | `mandate_gate.py` deny-by-default；`submit_run` / `trigger_training` 在 registry 已标 `requires_mandate: true` |
| **ADR-05** | 交易热路径 **永不 MCP** | 判定/下单/止损跨进程会破坏毫秒级承诺 | 热路径保持 in-process；L2 只能观察，不得触发 L1 执行写 |
| **ADR-06** | G 层沉淀**四分流**（案例 / 认知 / 流程 / 文档） | 沉淀不分流会污染认知库并制造检索噪声 | 收尾 Skill 产出按四类分流；认知写入只经 L0 cognition 壳 `record` |
| **ADR-07** | 插件化遵守 **先消费 → 再封装 → 后治理** | 53 已定硬约束；先自建插件会重复造轮子 | `plugin_whitelist.yaml` deny-by-default；插件必须复用 MCP 壳 |
| **ADR-08** | L2 文档**唯一事实源分层**：架构看 3+3/架构总览，契约看本文，能力登记看 TECHNICAL_DESIGN | 避免同一份 L2 描述散落在 12 个模块目录 | 各模块 SPEC 只写自身实现，不再复述五子层 |
| **ADR-09** | **三层职责边界**：L0 确定性、L1 统计发现、L2 生成与开发端动作 | 三层混用会让「事实/证据/动作」无法分开审计，也会让 L2 变成昂贵的查询层 | L2 内部应用以开发端（修 bug/优化）为主负载；发现权归 L1，验收权归 45，计量归 L2；见 §2.4 |
| **ADR-10** | **自扩展必须可回滚**：先 inspect / experiment，后 install；无 unload 回滚不开放写 | 借鉴 Cordis 可逆依赖图；不可回滚的自改会污染运行时，且无法审计 | 插件 install 前必须通过 G-L2-9；回滚验证覆盖订阅/连接/句柄/定时器四类副作用 |
| **ADR-11** | **总装线段间契约唯一化**：loop 出口 / 工具集 / span / Plan 四契约先冻结，再改行为 | 段与段各自推导会造成「停止原因、工具面、trace、控制权」四处漂移，且编译期发现不了 | 见 §4.7 IF-7；G-L2-10/11；校验器 `validate_contracts.py` |

---

## §4 接口契约

### 4.1 IF-1：L1 → L2 路由交接契约

来源：[SPEC-v1.4](../34-前端应用训练系统/SPEC-v1.4-L0L1L2-路由边界与认知裁决.md) §4.1 `route_signal`。

```json
{
  "decision": "L1_DIRECT | L2_HANDOFF",
  "route_confidence": 1.0,
  "reasons": ["semantic_intent_match"],
  "match_score": 0.78,
  "case_density": 4,
  "semantic": {"top1": 0.78, "top2": 0.71, "margin": 0.07},
  "cognition_signal": {"coverage": 0.0, "source": "capability_catalog", "verdict": "in_scope|unknown|out_of_scope"}
}
```

L2 侧必须消费的字段（当前落地情况）：

| 字段 | L2 用途 | 现状 |
|---|---|---|
| `decision` | 是否进入 SACG | ✅ `sacg_orchestrator` 消费 |
| `route_confidence` | 门控阈值唯一来源 | ✅ 复用 `core/route_confidence.py` |
| `reasons` | trace 归因 | 🟡 部分透传 |
| `cognition_signal.verdict` | 域内外裁决 → L2 路线 | ✅ 已实现：`56/runtime/l2_route.py`（裁定）+ `34/core/l2_cognition_route.py`（SACG 与 `l1_route_signal` 出口注入） |
| `l2_route` | `retrieval_augmented` / `deep_reasoning` | ✅ 已实现（闭合四字段；前端 `l2-route.ts` 收敛后落 execution trace `sagc.route`） |

### 4.2 IF-2：A 层 OKR 节点契约

来源：`core/okr_nodes.py` 头注释（向后兼容契约）。

```text
{node_id, objective, criteria, source, verify, evidence_id?}
```

`verify` 三值（禁止新增阈值）：

| verify | 适用来源 | 验收方式 |
|---|---|---|
| `evidence_backed` | `rea_evidence` | 证据满足即验收（比对 `evidence_id`） |
| `gap_closed` | `rea_known_gap` | 缺口补齐即验收 |
| `c_action` | `plan_item` | C 层动作非 `REDO` / `EARLY_TERMINATE` 即验收 |

`okr_ticket_bridge.py` 负责把该契约翻译成 Ticket Mandate（`node_id → external_ref`、`criteria → mandate.acceptance`、`verify → completion_policy`），纯函数、无副作用。

### 4.3 IF-3：L2 统一信封（`L2Envelope`，本文首次冻结）

> 现状：各壳与 HTTP 端点返回结构不统一（DreamOS 直接 `jsonify(result)`；MCP 壳走 `envelope_version: '0.1'`）；`meta.tokens_used` 等字段**未在 L2 出口统一出现**。
>
> **冻结前置决策（D1，已采 A）**：在 L0 既有 `envelope_version: '0.1'` 基础上**扩展字段**，不新开 `0.2-l2`；后续新增字段按 ADR-03 升次版本，禁止各壳私加。原 §7「Q1 是否合并」据此关闭。

```json
{
  "ok": true,
  "result": {},
  "meta": {
    "layer": "L2",
    "capability_id": "l2.dreamos",
    "run_id": "run-20261116-xxxx",
    "model": "qwen-max | deepseek-chat | none",
    "tokens_used": 0,
    "budget_remaining": 0,
    "latency_ms": 0,
    "degraded": false,
    "needs_review": false
  },
  "trace": {
    "route": "L2_HANDOFF",
    "reasons": [],
    "sagc": {"S": "done", "A": "done", "C": "done", "G": "skipped"},
    "nodes": []
  },
  "quality": {
    "evidence": "none | partial | full",
    "caveat": "历史统计/模型推断，不代表未来"
  }
}
```

硬约束：
1. `tokens_used` 与 `budget_remaining` 必须同源（DreamOS `GlobalBudgetManager`），不得各自记账。
2. `model` 为 `none` 时必须 `tokens_used = 0`（纯编排路径）。
3. 失败用 `ok=false + error_code`，**不得**用 HTTP 200 掩盖。
4. 文本结论不得出现「将会 / 预计 / 必然」（与 54 §0.2 同一纪律）。

### 4.4 IF-4：Ticket / Mandate 契约

来源：`core/mandate_gate.py`（ADR-4/5/9、H7）+ `core/ticket_state.py`。

- Ticket 四态：`live` / `paused` / `waitsForPerson` / `ended`；`paused` 子因：`waiting_event` / `waiting_job` / `waiting_person`。
- Worker 默认只读：`requires_mandate: true` 的写工具**禁止** Worker 持有；判定语义 deny-by-default（未知角色/未知工具/写工具一律拒）。
- 每次判定（含放行）可经 recorder 审计留痕。

### 4.5 IF-5：开发端台账契约（`RepairLedger`）

契约文件：`contracts/repair_ledger.schema.json`（JSON Schema 2020-12，`schema_version=1.1`）；落地 `34-前端应用训练系统/l2_repair_ledger.jsonl`（每行一条）。

> **v1.1（2026-11-17 裁决）**：原契约无法表达「刚入队」——`history[-1].to=state` 要求 `to=reported`，但 `to` 枚举与状态机均无该迁移，导致任何 L1 发现入队必然校验失败。v1.1 允许初始自迁移 `reported→reported`（不计数 `attempts`、无 guard），其余约束不变；自检 2 正 5 负。

必填：`schema_version / task_id / kind / trigger / state / history / attempts / symptom / reported / evidence / metrics / created_at / updated_at`；`settled` 与 `run_ids` 在 `state=settled` 时必填。

关键结构（均可机器校验）：

| 字段 | 约束 |
|---|---|
| `task_id` | `^(fix\|opt)-\d{8}-\d{3}$` |
| `trigger` | `{source, resolver, ref, resolved_at}`；`resolver ∈ {48.experiment_id, 54.discovery_path, github.issue}`，`ref` 必须匹配 resolver |
| `history` | 迁移链；`history[0].from=reported`、`history[-1].to=state`；边必须存在于 `state_machine.yaml` |
| `attempts` | 等于重开边次数，`≤3` |
| `evidence.repro` | `{cmd, fails_on_base=true, artifact_hash}` |
| `evidence.regression` | `{runner ∈ pytest\|ci\|gate45, cmd, exit_code, passed, ts, log_uri}`；`passed=true ⇔ exit_code=0`；`runner=manual` 非法 |
| `evidence.optimization` | `gate45 ∈ {PASS,BLOCK,INCONCLUSIVE}` 与 `stats{test_set,n≥30,effect,p_adj≤0.05}` **至少一项**（可并存） |
| `settled` | `{case,cognition,process,doc}` 四项齐全，各为 `done\|skipped` |
| `metrics` | `[{name,unit,before,after,n?,ci_low?,ci_high?}]` |

校验入口：`python3 scripts/validate_contracts.py --ledger <file>`（`0` 通过 / `1` 失败）。

### 4.6 IF-6：自扩展插件契约

契约文件：`contracts/plugin_extension.schema.json`；`op ∈ {inspect, experiment, install, unload}`，`direction ∈ {request, response}`。

| op | request 必填 | response 必填 |
|---|---|---|
| `inspect` | `request_id` | `plugins[], graph{acyclic:true}` |
| `experiment` | `manifest` | `loaded, errors[], rollback_ok, disk_writes=0` |
| `install` | `manifest, mandate, rollback_verified=true` | `installed, plugin_id, rollback_token{token_id,expires_at,idempotency_key}` |
| `unload` | `plugin_id, rollback_token, mandate` | `unloaded, side_effects_reverted[]` |

`side_effects_reverted` 枚举：`subscription / connection / handle / timer`。
错误码：`E_MANIFEST_INVALID / E_DEP_MISSING / E_CHANNEL_CONFLICT / E_ROLLBACK_FAILED / E_TIMEOUT / E_PERMISSION_DENIED`。

硬约束：`install` 缺 `rollback_verified=true` 即被 schema 拒绝；`experiment` 的 `disk_writes` 必须为 `0`；`unload` 必须回滚授权 token 对应的四类副作用。

### 4.7 IF-7：总装线四契约（A0 冻结，2026-11-16）

> 目的：先冻结「段与段之间」的机器可判定契约，不改任何行为；后续 A1 单模块改造均以此为准。

| 契约 | 文件 | 关键判据 |
|---|---|---|
| 停止原因 | `contracts/stop_reason.schema.json`（v1.1） | 7 值；必填 `trace_id`；`parked` 必带 `waiting_for_human/async_tool/client` 之一且 `resumable=true`；`done/error/no_next_context` 不可续跑 |
| 工具集快照 | `contracts/tool_set.schema.json` | 工具名唯一；`effect=write` ⇒ `requires_mandate=true`；`effect=trade` ⇒ Mandate + 审批只能 `human/deny`；权限顺序固定 `deny→mode→allow→human` |
| 观测 span | `contracts/span.schema.json` | 8 段枚举（sense/arrange/capability/compute/gate/memory/scheduler/artifact）；`ended_at ≥ started_at`；`model_id=none` ⇒ `tokens=0`；`context_hash=sha256:*` |
| 规划/交接 | `contracts/plan_handoff.schema.json`（v1.1） | 必填 `trace_id`；`mode ∈ {self,handoff,agents_as_tools}`；handoff 必须交权，agents_as_tools 必须保留控制权并 `return_to`；`soft_tokens ≤ hard_tokens`；步骤序号从 1 连续；至少一个 evaluator 或 tripwire |

硬约束：

1. 任一 loop 结束只允许返回 `stop_reason` 结构，禁止 UI/服务端各自推导。
2. 工具可见性与审批必须来自同一次 `tool_set` 快照，禁止各端自建白名单。
3. span 在 DreamOS/52/3.1 使用同名字段，禁止私有 trace 字段。
4. Plan 必须带外部验收（evaluator 或 tripwire），否则不得进入执行。

校验：`python3 scripts/validate_contracts.py --self-test`；单文件用 `--stop-reason / --tool-set / --span / --plan`。

> **v1.1 裁决（2026-11-16 评审）**：`stop_reason` 与 `plan_handoff` 必填 `trace_id`，与 span 一一对账；`no_next_context` 改为不可续跑（需新输入）。自检 `SELF-TEST PASSED (28/28)`，A0 已关闭。评审记录见 [REVIEW-20261116](./docs/REVIEW-20261116-A0契约与总装线对标评审.md)。

---

## §5 门禁

| # | 门禁 | 判据 | 失败后果 |
|---|---|---|---|
| G-L2-1 | 层级准入 | 请求命中「生成式 LLM 必需」或 L1 明确 `L2_HANDOFF` | 回 L1，不得为了用 LLM 而路由 L2 |
| G-L2-2 | 授权门禁 | 写工具必须 `requires_mandate=true` 且 Mandate 有效 | 拒绝并审计，不静默成功 |
| G-L2-3 | 预算门禁 | `budget_remaining ≥ 预估成本` | 降级为 L1 事实回答或拒答 |
| G-L2-4 | 验收门禁 | OKR `verify` 通过 + 45 业务门禁（shadow 期只记录）；注入点 `core/gate_45_runtime.py::resolve_settle_gate()`（默认关） | `degraded` / `needs_review` |
| G-L2-5 | 证据门禁 | 生成结论必须可回溯到 `nodes[]` 或 L1 只读事实 | 标 `quality.evidence=none`，禁止当结论用 |
| G-L2-6 | 层级配额 | L2 工具数 ≤ 30（当前 14） | 注册被 `validate_mcp_registry.py` 拒绝 |
| G-L2-7 | 发现来源门禁 | `trigger.source` ∈ {`l1_finding`, `bug_report`} 且 `ref` 匹配 resolver（`validate_trigger`） | 拒绝开工，退回「先由 L1 出具发现」 |
| G-L2-8 | 回归门禁 | `runner ∈ {pytest,ci,gate45}`、`passed=true`、`exit_code=0`；优化类 `gate45=PASS` 或 `stats{n≥30,p_adj≤0.05}` | 只能标 `fixed`，不得进 `settled` |
| G-L2-9 | 可回滚门禁 | `install.rollback_verified=true` 且 `unload.side_effects_reverted` 覆盖四类 | 禁止 `install`，只允许 inspect/experiment |
| G-L2-10 | 循环出口门禁 | loop 结束必须返回合法 `stop_reason`；`parked` 必须带子因且可续跑 | 判红，trace 不可作为验收证据 |
| G-L2-11 | 工具集门禁 | 可见性与审批只能来自同一次 `tool_set` 快照；交易类工具不得 `auto` | 拒绝执行并审计 |

---

## §6 路线

| 阶段 | 目标 | 完成判据 |
|---|---|---|
| **A0** | 总装线四契约冻结 | IF-7 四 schema + 校验器自检全绿；不改任何运行时行为 |
| **P0** | 信封与契约收口 | `L2Envelope` 在 DreamOS 12 端点与 4 个 L2 壳统一出现；`tokens_used/budget_remaining/model` 有值；回归测试覆盖 |
| **P1** | 路由路线契约化 | `route_signal.l2_route` 落地，`retrieval_augmented / deep_reasoning` 可机器读取并写入 trace |
| **P2** | 编排面补壳 | `l2.dsh.mcp` 只读（Router 摘要 / Ticket 状态 / Worker 角色），写操作仍需 Mandate |
| **P3** | 开发端台账（GAP-15） | 每次修复/优化产出 `RepairLedger`（IF-5）；周报可算修复率、回归通过率、单任务 token |
| **P4** | 插件自扩展（GAP-16） | inspect 只读可用；experiment 沙箱；unload 四类副作用回滚验证通过后才开放 install |
| **P5** | 文档与注册表对齐 | 清理 `dreamos/README.md` 归档漂移；`l2.train` `source_modules` 与 34/gate_45 对齐；49 §3.8 同步 |

---

## §7 待决问题

| # | 决策点 | 选项 | 建议 |
|---|---|---|---|
| Q1 | `l2.dsh` 本轮是否注册 | A 注册 3 只读；B 暂缓 | **A**：当前 Worker 编排只有 IPC，外部宿主完全不可观测 |
| Q2 | `agent.debate.mcp` 别名何时退役 | A 下个迭代；B 保留到 53 插件化后 | **A**：双壳并存会让工具面账目失真 |
| Q3 | 45 门禁转硬门的时点 | A 误拦率 <5% 即转；B 先累计 2 周 shadow | **B**：与 34 DD4 一致，避免误杀 |
| Q4 | Worker 角色工具上限口径 | A 以注册表 `max_tools_per_shell=15` 为准；B 以 3+3 文档「≤10」为准并改注册表 | **已决 B（已落地）**：注册表增 `max_tools_per_role: 10`，校验器角色检查改用它；单壳上限仍 15 |
| Q5 | 两宿主 C 层是否统一 | A 保持两宿主两实现（DreamOS `core/compute` / 34 `cdrive_v3_router`）；B 抽公共契约层 | **A**：先由 IF-2 OKR 契约保证一致性，避免过早抽象 |
| Q6 | 开发端台账粒度 | A 每任务一条（含优化对照）；B 每 commit 一条 | **A**：commit 粒度无法承载「症状-根因-回归」证据链 |
| Q7 | 自扩展开放范围 | A 只读 inspect；B 生成 + 人工审核后 install；C 全自动热装 | **B**：符合 ADR-10，先攒回滚验证样本再谈 C |
