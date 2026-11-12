---
name: dream-rea-architecture-query
description: "决定何时/如何调用 33-REA 逆向解析（l0.rea.mcp）获取架构事实：必调/可选/禁调矩阵 + token 纪律 + Evidence 使用纪律 + 认知回写闭环。Invoke when 架构摸底、进入陌生模块、影响面分析、工程对比、依赖环排查、或任何需要结构化代码事实而非模型印象的场景。"
version: 1.1.0
created: 2026-11-11
updated: 2026-11-11
license: Internal
status: active
category: tooling
triggers: [架构摸底, 逆向解析, REA, 影响面分析, 依赖环, 工程对比, 陌生代码域, 调用链]
depends_on: [cognitive_mcp, l0_gateway]
provides: [rea-query-policy, architecture-fact-layer]
cognitive_links: [VM-1794376918786-b2fd4375, VM-1794376919568-f054b853, VM-1794376925616-4bbf98f8]
---

## Autonomy Boundary

可自主执行：
- 调用 `submit_rea_analyze` / `poll_rea_analyze` / `submit_rea_compare` 等只读工具
- 用 `get_rea_snapshot` 分页读取明细
- 将符合等级映射的 `cognitive_hint` 写入认知库

需用户确认：
- 对 >30,000 文件的目标执行全量分析（必要时先确认 `max_files`）
- 一次性取 `scope=full`

禁止：
- 把 `inference` 级结论当作 `observation` 事实使用
- 省略或改写 `known_gaps`
- 在壳内或本文档流程中调用任何写交易/写策略工具
- 自行拔高 `quality_level`

# Dream REA Architecture Query — 逆向解析调用策略

> 把"什么时候该用 33-REA、怎么用才不烧 token、结论怎么进认知库"固化为可复用策略。
> 工程侧契约见 `33-REA逆向解析工程/SPEC-33-D-REA作为L0MCP的工程开发协作.md`；本文是**协作侧双保险**：即使宿主没有自动接线，任何模型读到本文也能正确调用。

---

## 0. 一句话原则

**要"结构事实"用 REA，要"设计意图"读代码。让事实层约束判断层的输入，不要让判断层去猜事实。**

REA 回答：谁 import 谁、有几个环、路由表是什么、哪些组件是 God component、两个工程差在哪。
REA 不回答：为什么这么写、运行时会不会死锁、业务语义是什么。

---

## 1. 何时调用（决策矩阵）

| 场景 | 判定 | 调用 |
|---|---|---|
| 第一次改动某个代码域，不了解其结构 | **必调** | `analyze(scope=summary)` |
| 判断"改这个文件会影响谁" | **必调** | `trace { target: 工程根, entry: "相对路径" }` → `call_chain.callers` 即引用方；子目录影响面逐个文件查 |
| 两工程/两分支结构对比（如 3.1 vs LobeHub） | **必调** | `compare(scope=summary)` |
| SPEC / 调研需要可复核的现状证据 | **必调** | `analyze`，结论连同 `snapshot_id` 一起引用 |
| 排查依赖环、孤立文件、超大组件 | **必调** | `analyze(scope=architecture)` |
| 找单个符号定义所在文件 | 可选 | 先用 Grep（更快），Grep 无果再 `trace` |
| 单文件小改（<50 行）且已知上下文 | 不必调 | — |
| 理解某段业务逻辑的**意图** | **禁调** | 必须读代码 + git 历史 |
| 排查运行时故障 / 并发 / 时序 | **禁调** | 静态分析无此能力 |
| 安全漏洞、权限绕过验证 | **禁调** | 需动态验证与人工审计 |

**时机铁律**：在动手改之前调，而不是改完再验证。正确顺序：

```text
recall（查历史经验）→ rea analyze（拿结构事实）→ 读关键文件（补语义）→ 动手
```

---

## 2. 调用三步法

```text
1) submit_rea_analyze { target, scope: "summary", trace_id }
   → 立即返回 job_id（state=running）
2) poll_rea_analyze { job_id }
   → state=running 则等待后再 poll；state=success 取 result + cognitive_hint
   → state=failed 读 error，不要重试同一参数超过 1 次
3) 需要明细时：get_rea_snapshot { snapshot_id, section, cursor, limit }
```

要点：
- `submit` 是异步的，**不要**在 submit 后立刻断言结果。
- `trace` 需要 `feature`，`compare` 需要 `target_a` + `target_b`，缺参直接报 `invalid`。
- `trace` 的 `feature` 会按路径/文件内容匹配种子模块（返回 `matched`），`call_chain` 只含种子的一跳上下游子图（每种子 ≤10），不是全量图 dump。
- `entry` 只给文件名（如 `index.ts`）且多命中时**不会被猜测**，会退回 `feature` 匹配并在 `known_gaps` 说明；影响面查询请给相对路径。
- 结果带 `trimmed.{section}.{kept,total}` 表示明细被裁剪，完整内容经 `get_rea_snapshot` 分页读。
- 结果 `degraded=true` 时先看 `meta.reason`，再决定是否换 `scope` 或缩小目标。

---

## 3. Token 纪律（硬约束）

实测基线（3.1-FRONTEND，518 文件 / 101,276 行）：全量 JSON **303,827 B**，摘要 **8,089 B**，比值 **37×**。

| 规则 | 说明 |
|---|---|
| **默认 `scope=summary`** | ≤16 KB，约 3k token。够回答 80% 的问题 |
| `architecture` 仅在需要路由表/环/God component 明细时用 | ≤64 KB |
| **`full` 默认不用** | 它不返回明细，只返回 `snapshot_id`；明细必须走分页 |
| 分页 `limit` 默认 50，单次 ≤200 | 禁止把 `total` 一次拉完 |
| 同一目标在同一任务内**只分析一次** | 先走 §3.1 指纹去重，命中则复用 `snapshot_id` |
| `force=true` 只在怀疑缓存过期时用 | 默认走缓存，二次调用 <200ms |

**反模式**：把 `raw.modules` / `dependencies` 整块贴进上下文——这比让模型自己读文件还贵。

### 3.1 分析前 recall 去重（T-D11，硬流程）

```text
1) python3 33-REA逆向解析工程/scripts/rea_recall_gate.py --target <工程根> --scope summary
   → 输出 fingerprint / recall_query / record_marker
2) recall(context=recall_query, top_k=3, min_quality="C")
3) 判定：
   命中同指纹且 ≤7 天 → reuse：直接 get_rea_snapshot{snapshot_id}，禁止再次 submit
   指纹不同 / 超期 / 无时间戳 → reanalyze：正常走 §2 三步法
```

- 指纹 = `sha1(真实路径 | git HEAD | scope)[:12]`；HEAD 前进、scope 变化、路径变化都视为需要重跑。
- 复用时必须在回复中注明 `snapshot_id` 与「复用，未重新分析」，禁止把复用结论包装成「刚分析」。
- 记录时必须写入 `record_marker`（见 §5），否则下次命不中。

---

## 4. Evidence 使用纪律

每条结论带 `level` + `confidence` + `known_gaps`，按级别使用：

| level | 含义 | 允许的表述 |
|---|---|---|
| `observation` | 可复算的结构事实 | "本项目有 X 个模块、Y 条依赖边" |
| `derivation` | 由事实推导（如检测到 4 个环） | "检测到 4 个循环依赖（依据 X）" |
| `inference` | 模式判断（如认定为 Feature-Sliced） | "**推断**为 Feature-Sliced 架构，未逐目录核对" |
| `unknown` | 分析失败/覆盖不足 | "未能确认，已知局限：…" |

硬性要求：
1. `known_gaps` **必须原样传递**给最终结论，不得因为"看起来不重要"而省略。
2. 影响面结论若未用 `get_rea_snapshot` 复核，**必须**标注为推断。
3. 引用 REA 结论时带上 `snapshot_id`，便于他人复核。
4. `degraded=true` 的结果不得作为验收证据。

---

## 5. 认知闭环（T-D10，三段式硬流程）

`poll` 成功会返回 `cognitive_hint`。必须按「hint 校验 → record → 改动后 verify」执行，缺一段即闭环未完成。

### 5.1 hint 校验（写前）

| 检查项 | 不通过处置 |
|---|---|
| `level ∈ {observation, derivation, inference, unknown}` | 不写，回复说明异常 |
| `content` 非空且不含 `snapshot_id` 之外的臆造结论 | 不写 |
| `tags` 完整（hint.tags 原样） | 补齐后写，不得删减 |
| `known_gaps` 原样保留（可再加，不可减） | 缺失则不写 |

`level = unknown` 或 `degraded=true` → **不写**，只在回复中说明局限。

### 5.2 record（写）

| 情况 | 动作 |
|---|---|
| `level ∈ {observation, derivation}` | `record(quality_level="B", tags=hint.tags)` |
| `level = inference` | `record(quality_level="C", tags=hint.tags + ",推断")` |
| 一次分析 | **最多写 1 条**（防噪音） |
| content 末尾 | **必须**追加 §3.1 的 `record_marker`（`rea-fp:<指纹>`），否则下次去重命不中 |

**禁止**：改写 hint 里的 `content`/`quality_level`/`level`。壳已按 §SPEC-D 2.6 映射完成，改写等于污染记忆库。

### 5.3 改动后 verify（写后）

只有在**实际改动完成并复跑分析**后才允许 verify：

| 复跑结果 | 动作 |
|---|---|
| 结论仍成立（如环仍在 / 依赖边未变） | `verify(memory_id, success=true)` |
| 结论被推翻（如环已消除 / 文件已拆分） | `verify(memory_id, success=false)`，并在回复中给出反例证据 |
| 未复跑 / 分析失败 / `degraded` | **禁止 verify**（凭感觉 verify 会污染置信度） |
| 同一 `memory_id` | 只 verify 一次；重复 verify 不产生新信息 |

verify 证据要求：附本次 `snapshot_id` 或复跑命令，不接受「我确认过了」。

---

## 6. 与其他 SKILL 的衔接

| 上游 SKILL | 衔接点 |
|---|---|
| `dream-bugfix-workflow` | 根因分析前先 `analyze`，用结构事实缩小怀疑范围 |
| `dream-arch-research-orchestrator` | 架构调研的"现状"章节直接引用 `analyze` 结果 |
| `dream-feature-landing-workflow` | 落地前用 `analyze(scope=architecture)` 确认改动边界 |
| `dream-code-commit-sync-workflow` | 大改动后对比改动前后的环/孤儿数量变化 |
| `dream-acceptance-verify` | 验收证据中可引用 `snapshot_id`（仅 observation/derivation） |
| 广义认知系统 `recall` | 分析前先查同目标快照，避免重复分析 |

---

## 7. 故障处理

| 现象 | 处置 |
|---|---|
| `error=missing_target` | 检查 target 是否为绝对路径 |
| `error=invalid_target_type` | 确认是目录或 `.py`/`.ts`/`.tsx` 文件 |
| `error_code=forbidden` | 该工具不在当前角色白名单（engineer 含 analyze/trace/compare/snapshot；`eval_analyze` 属 verifier）；改用对应角色或换工具 |
| `state=failed` | 读 `error`；同一参数最多重试 1 次，之后缩范围或降 `scope` |
| 结果"未找到 Python 文件"但目标明显是 TS 项目 | 语言路由失效（应为 `typescript`）；**不要采信该结论**，改传含 `tsconfig.json` 的工程根路径，或 `force=true` 重跑 |
| job 长时间 `running` | 先 `poll` 3 次（间隔递增），仍 running 则放弃并说明 |

---

## 8. 三条反模式（见到就停）

1. **拿 REA 结论当设计意图**：它只描述结构，不解释动机。
2. **`scope=full` 一把梭**：把 300KB 塞进上下文，token 立涨 10 万级。
3. **对 TS 项目采信"未找到 Python 文件"**：这是已知缺陷（SPEC-D P-01），结论无效。
