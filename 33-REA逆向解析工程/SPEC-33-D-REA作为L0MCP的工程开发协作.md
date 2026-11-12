# SPEC-D: 33-REA 作为 L0 MCP 的工程开发协作

> 版本：v0.1.0
> 日期：2026-11-11
> 状态：✅ P0+P1+P2 全部落地（2026-11-11，测试全绿），待评审
> 归属：33-REA逆向解析工程（能力提供方） × 47-MCP管理系统（协议/注册面）
> 上游：[SPEC-L0-MCP-PACKAGING-v0.3](../47-MCP管理系统/docs/tech/SPEC-L0-MCP-PACKAGING-v0.3.md)、[TECH-L0-MCP-v0.1](../47-MCP管理系统/docs/tech/TECH-L0-MCP-v0.1.md)、[COLLABORATION-CONTRACT.md](../35-广义认知系统协作模块/COLLABORATION-CONTRACT.md)
> 输入：2026-11-11 现状核查（壳/注册表/实测输出体积）
> 配套：SKILL `dream-rea-architecture-query`（协作路径，与本 SPEC 工程路径构成双保险）

---

## §0 背景与结论

### 0.1 一句话结论

**L0 MCP 的位置已经对了，但壳与能力脱节：`l0.rea.mcp` 只接了 Python 分析器，对 TS/React 项目会返回高置信度的错误结论；且未注册到任何宿主、输出全量 304KB 不可控。本 SPEC 只做"打通 + 控量 + 接治理"三件事。**

### 0.2 现状证据（可复核）

| # | 事实 | 证据位置 |
|---|---|---|
| E1 | 壳已存在，6 工具：`submit/poll_rea_{analyze,trace,compare}`，两段式异步 + JSONL job 持久层 + shadow 双跑 | [server.py](../mcp_shells/l0_rea/server.py) |
| E2 | 注册表登记 `l0.rea.mcp`，`status: available`，6 工具全部 `read_write: read`、`requires_mandate: false` | [mcp_capabilities.yaml](../47-MCP管理系统/registry/mcp_capabilities.yaml#L137-L180) |
| E3 | 角色投影已有：`research` = analyze；`engineer` = analyze + compare | [mcp_capabilities.yaml](../47-MCP管理系统/registry/mcp_capabilities.yaml#L486-L498) |
| E4 | **`S33_rea_analyze` 目录分支只调 `DependencyGraph` + `CallChainTracer`，二者均仅扫 `.py` 且用 `ast.parse`** | [dsh_nodes.py](./dsh_nodes.py#L166-L234)、[dependency_graph.py](./core/dependency_graph.py#L82-L113)、[call_chain_tracer.py](./core/call_chain_tracer.py#L82-L101) |
| E5 | 本轮新增的 `TSProjectAnalyzer` 只接在 CLI 与 `investigation_workflow`，**未接入 `dsh_nodes`** | [ts_project_analyzer.py](./core/ts_project_analyzer.py)、[investigation_workflow.py](./core/investigation_workflow.py) |
| E6 | `scope` 参数在目录分支被读取但**未使用**（仅传给 recorder） | [dsh_nodes.py](./dsh_nodes.py#L116-L126) |
| E7 | `submit_rea_compare` 的 schema 复用 `{target, feature, trace_id}`，缺 `target_a`/`target_b`（节点实际按 a/b 取值） | [server.py](../mcp_shells/l0_rea/server.py#L201-L221)、[dsh_nodes.py](./dsh_nodes.py#L344-L370) |
| E8 | 宿主机 [.trae/mcp.json](../.trae/mcp.json) 只注册 `cognitive`；[mcp_profiles.json](../47-MCP管理系统/registry/mcp_profiles.json) 无 rea profile | 两文件本体 |
| E9 | 实测 3.1-FRONTEND（518 文件 / 101,276 行）：全量 JSON **303,827 B**，人读摘要 `--top 10` **8,089 B**，扫描 **0.5 s** | 2026-11-11 本地实测 |

### 0.3 问题清单

| # | 问题 | 后果 |
|---|---|---|
| P-01 | 壳对 TS 项目返回"未找到 Python 文件"+`confidence=1.0` | 比不调用更危险：用高置信度错误结论污染模型判断 |
| P-02 | `scope` 死参数 | 无法控制输出粒度 |
| P-03 | `raw` 全量内联 | 一次 analyze ≈ 8–10 万 token，比模型自己读文件还贵 |
| P-04 | 无跨进程缓存 | 多轮对话重复全量扫描 |
| P-05 | compare schema 错 | 模型按 schema 填参必错 |
| P-06 | 未注册宿主 | 任何 AI 客户端都调不到 |
| P-07 | 认知注入靠调用方自觉 | 任意模型大概率漏写，闭环断裂 |

### 0.4 非目标（明确不做）

| 不做 | 原因 |
|---|---|
| 不重写壳的协议/信封/job 机制 | 已满足 SPEC-L0 §3.2，改动面越大回归风险越高 |
| 不新增写工具（record/verify 不进入 rea 壳） | ADR-9/H7：Worker 角色只读；认知写入由宿主侧 SKILL 执行 |
| 不改 `l0.rea-client.mcp`（npm rea-agents 面） | 已 `deprecated`，由本壳取代 |
| 不做动态/运行时分析 | 33-REA 定位是静态只读 |
| 不引入新的 MCP SDK 依赖 | 沿用现有 stdio 实现 |

---

## §1 目标与验收指标

| 编号 | 目标 | 可测判据 |
|---|---|---|
| G-D1 | 语言路由正确 | `submit_rea_analyze(target="3.1-FRONTEND")` 返回 `language: "typescript"`、文件数量级 ≈518、路由 ≈56；**不出现**"未找到 Python 文件"；Python 目录结果与本 SPEC 前一致 |
| G-D2 | 输出可控 | 默认（summary）响应 ≤ **16,384 B**；`scope=full` 不内联 raw，返回 `snapshot_id`，响应 ≤ **4,096 B** |
| G-D3 | 缓存生效 | 同目标二次调用 `meta.cache_hit=true` 且耗时 < 200 ms |
| G-D4 | compare 可用 | `submit_rea_compare` 的 `inputSchema.properties` 同时含 `target_a`/`target_b`；gateway `--role engineer` 的 `tools/list` 含该工具 |
| G-D5 | 权限不退化 | gateway `--role engineer` 的 `tools/list` 恰好 10 工具（含 analyze/trace/compare/snapshot）；调角色外工具 `eval_analyze` → `ok=false, error_code=forbidden`；写类工具仍为 0 |
| G-D6 | 注册表一致 | `python3 47-MCP管理系统/registry/scripts/validate_mcp_registry.py` 通过；`mcpctl` 工具面与 `TOOL_DEFS` 无漂移 |
| G-D7 | 零回归 | 33-REA 现有测试全绿 + `mcp_shells/l0_rea/test_l0_rea_server.py` 全绿 |
| G-D8 | 认知可回写 | poll 成功结果内含结构化 `cognitive_hint`，字段可被 `record` 直接消费（不自动写） |

---

## §2 总体设计

### 2.1 分层与职责

```text
┌─────────────────────────────────────────────────────────┐
│ 宿主（任意 AI / IDE / Agent）                              │
│   ├─ 工程路径：MCP client → l0_gateway --role engineer    │
│   └─ 协作路径：SKILL dream-rea-architecture-query         │
├─────────────────────────────────────────────────────────┤
│ l0_gateway（P1 已有）：角色白名单 ≤10 工具 / 只读 / 越权 forbidden │
├─────────────────────────────────────────────────────────┤
│ l0.rea.mcp（已有，本 SPEC 修补）                            │
│   submit_* / poll_* 两段式 + JSONL job + 统一信封           │
├─────────────────────────────────────────────────────────┤
│ dsh_nodes（本 SPEC 修补）                                  │
│   语言路由 → TSProjectAnalyzer | Python 旧路径              │
│   快照落盘 + 内容寻址缓存 + cognitive_hint                  │
├─────────────────────────────────────────────────────────┤
│ 33-REA core（已有）：TS 项目级分析 / 依赖图 / 调用链 / 模式识别 │
└─────────────────────────────────────────────────────────┘
```

**职责硬边界**：
- 壳只做"协议解析 → 节点调用 → 信封映射"，不承载业务判断。
- **壳不写认知库**（需要写权限，违反 Worker 只读）。壳只返回 `cognitive_hint`，由宿主侧 SKILL 转调 `record`。
- SKILL 只做决策与纪律，不实现分析能力。

### 2.2 语言路由（解决 P-01）

`dsh_nodes` 新增统一入口 `_detect_target_language(target)`：

| 判定顺序 | 命中条件 | 走哪条路径 |
|---|---|---|
| 1 | 文件且后缀 `.py` | `PythonAnalyzer`（现状不变） |
| 2 | 文件且后缀 ∈ `_TS_EXTS` | `TSProjectAnalyzer`（单文件模式） |
| 3 | 目录含 `tsconfig.json` 或 `package.json` 或 `src/app` | `TSProjectAnalyzer` 项目级 |
| 4 | 其余目录 | `DependencyGraph` + `CallChainTracer`（现状不变） |

**改动点**：`S33_rea_analyze`、`S33_rea_trace`、`S33_rea_compare`、`_analyze_project` 四处共用该路由，杜绝各写一套。

**TS 分支输出映射**（与既有 `result` 契约对齐，避免调用方改）：

```text
summary      ← f"架构分析: {stats.files} 文件, {graph.edges} 依赖, {cycles} 环, {routes} 路由"
evidence     ← TSProjectAnalyzer 产出的 Evidence（observation/derivation/inference）
raw.modules  ← graph.nodes
raw.dependencies ← graph.adjacency
raw.cycles   ← graph.cycles
raw.call_graph   ← {callers, callees}（TS 以 import 反向邻接近似）
raw.ts       ← {routes, api_routes, components, stores, god_components, monorepo, patterns, external_deps}
```

### 2.3 输出分级与快照（解决 P-02/P-03）

`scope` 三档（**默认 `summary`**）：

| scope | 返回内容 | 软上限 |
|---|---|---|
| `summary`（默认） | `summary` + `stats` + `patterns` + `known_gaps` + Evidence **聚合计数** + 前 5 条 Evidence + `snapshot_id` | 16 KB |
| `architecture` | summary 全部 + `routes`/`api_routes`/`stores`/`god_components`/`cycles` + hubs/orphans 前 20 | 64 KB |
| `full` | **不内联 raw**，只返回 `snapshot_id` + `stats` + `degenerate` 标记 | 4 KB |

**快照落盘**：`33-REA逆向解析工程/reflection_data/snapshots/<snapshot_id>.json`，`snapshot_id = sha256(target_abs + tree_hash)[:16]`。

**新增工具** `get_rea_snapshot`（读、无副作用）：

```text
get_rea_snapshot(snapshot_id, section, cursor=0, limit=50)
  section ∈ {modules, dependencies, cycles, call_graph, components, routes,
             stores, god_components, external_deps, evidence}
  → {items, next_cursor, total, section}
```

> 该工具追加进 `TOOL_DEFS` 与注册表 `l0.rea.mcp.tools`，`port: analysis`、`read_write: read`。工具总数 6 → 7，仍在 `worker_roles` 与 SPEC-L0 软上限（80）之内。

### 2.4 内容寻址缓存（解决 P-04）

- **key**：`sha256("\n".join(sorted(f"{rel_path}:{mtime_ns}:{size}" for f in files)))`
- **位置**：`33-REA逆向解析工程/reflection_data/mcp_cache/<key>.json`
- **命中**：`meta.cache_hit=true`、`meta.cached_at`、`meta.source_key`
- **失效**：文件集合任一变化即换 key，旧缓存按 LRU 上限 200 个清理
- **强制重扫**：`args.force=true` 跳过读缓存（仍写缓存）
- 缓存只存**分析结果**，不存 job 状态（job 仍走 JSONL 追加，职责不混）

### 2.5 compare 契约修正（解决 P-05）

三个 submit 工具改为**各自独立 schema**：

| 工具 | properties | required |
|---|---|---|
| `submit_rea_analyze` | `target`, `scope`, `force`, `trace_id` | `target` |
| `submit_rea_trace` | `target`, `feature`, `entry`, `trace_id` | `target`, `feature` |
| `submit_rea_compare` | `target_a`, `target_b`, `feature`, `scope`, `trace_id` | `target_a`, `target_b` |

`scope` 的 enum 为 `["summary","architecture","full"]`，并在 description 中注明**默认 summary**与字节上限。

### 2.6 cognitive_hint 契约（解决 P-07）

`poll_*` 成功时，结果追加（**不改变原 result 结构**）：

```json
"cognitive_hint": {
  "content": "[33-REA][<target>] <summary>；环 <n>；模式 <p1,p2>；局限 <k> 条",
  "tags": "33-REA,架构分析,<language>,<target_basename>",
  "quality_level": "B",
  "level": "observation",
  "snapshot_id": "abc123...",
  "verify_when": "该目标的结构性结论被改动后（如新增/消除依赖环）"
}
```

**等级映射（硬约束，禁止调用方自行拔高）**：

| Evidence 主导级别 | `quality_level` | 写不写 |
|---|---|---|
| `observation` | B | 写 |
| `derivation` | B | 写 |
| `inference` | C | 写（标注推断） |
| `unknown` / degraded | — | **不写**，只留 `known_gaps` |

**一次分析最多一条 hint**（防噪音，避免淹没 recall 排序）。

### 2.7 接入方式（解决 P-06）

**推荐：单条 gateway 接入**（不是把 7 个工具全暴露）。

`mcp_profiles.json` 新增：

```json
"rea-engineer": {
  "description": "本地只读：REA 架构分析 + 功能追踪 + 工程对比（角色白名单 10 工具）",
  "command": "python3",
  "args": ["<REPO_ROOT>/mcp_shells/l0_gateway/server.py", "--role", "engineer"],
  "env": { "PYTHONPATH": "<REPO_ROOT>", "PYTHONIOENCODING": "utf-8" }
}
```

宿主机 `.trae/mcp.json` 增加对应条目（与 `cognitive` 并存，互不替代）。

**engineer 白名单（10 工具满额）**：`data_fetch`、`data_store_read`、`recall`、`submit/poll_rea_analyze`、`submit/poll_rea_trace`、`submit/poll_rea_compare`、`get_rea_snapshot`。越权验证锚点改为 `eval_analyze`（属 verifier）。

**为什么走 gateway 而不是直连壳**：直连会把全部 7 个 REA 工具无差别暴露，且无法按角色收窄；gateway 的 `tools/list` 精确等于角色白名单，越权返回 `forbidden`，壳异常会自动重拉。工具面更小 = 模型选错工具的概率更低。

---

## §3 分阶段实施

### P0 — 打通与控量（本期必做）

| # | 任务 | 主要文件 | 验收 |
|---|---|---|---|
| T-D1 | 新增 `_detect_target_language` 并接入 analyze/trace/compare/`_analyze_project` | [dsh_nodes.py](./dsh_nodes.py) | G-D1 |
| T-D2 | `scope` 三档生效 + 快照落盘 | [dsh_nodes.py](./dsh_nodes.py) | G-D2 |
| T-D3 | 新增 `get_rea_snapshot` 工具 + 注册表登记 | [server.py](../mcp_shells/l0_rea/server.py)、[mcp_capabilities.yaml](../47-MCP管理系统/registry/mcp_capabilities.yaml) | G-D6 |
| T-D4 | compare/analyze/trace schema 拆分修正 | [server.py](../mcp_shells/l0_rea/server.py) | G-D4 |
| T-D5 | 补 RED 测试：TS 路由、scope 截断、schema 必填项、快照分页 | `mcp_shells/l0_rea/test_l0_rea_server.py`、`33-REA逆向解析工程/tests/` | G-D7 |

### P1 — 缓存与接入

| # | 任务 | 主要文件 | 验收 |
|---|---|---|---|
| T-D6 | 内容寻址缓存 + LRU 清理 + `force` 开关 | 33-REA core | G-D3 |
| T-D7 | `mcp_profiles.json` 新增 `rea-engineer`，宿主 `.trae/mcp.json` 注册 | [mcp_profiles.json](../47-MCP管理系统/registry/mcp_profiles.json)、[.trae/mcp.json](../.trae/mcp.json) | G-D4/G-D5 |
| T-D8 | 写 SKILL `dream-rea-architecture-query` 并双位置落地 | `.trae/skills/`、`1-ARCHITECTURE/skills/` | 可由任意宿主加载 |

### P2 — 认知闭环自动化

| # | 任务 | 说明 | 验收 |
|---|---|---|---|
| T-D9 | `poll_*` 注入 `cognitive_hint`（含等级映射） | 壳仍只读 | G-D8 |
| T-D10 | SKILL 侧规定：hint 校验 → `record` → 改动后 `verify` | 不自动写，避免违反 Worker 只读 | 认知库可检索到本次分析 |
| T-D11 | 分析前 `recall` 命中去重（同 snapshot 不重复分析） | 降 token | 二次任务走 recall 命中 |

---

## §4 硬约束

1. **禁止**在壳内新增写能力；`record`/`verify` 永不进入 `l0.rea.mcp`。
2. **默认** `scope=summary`；未显式要求 `full` 时不得返回 raw 明细。
3. **禁止**把 `inference` 级 Evidence 作为 `observation` 上报（等级映射见 §2.6）。
4. `known_gaps` **必须**原样透传到调用方，禁止在摘要中省略。
5. TS 项目**必须**走 `TSProjectAnalyzer`；Python 项目**必须**走原路径，二者不得混用。
6. 缓存命中**必须**在 `meta` 标记 `cache_hit=true`，便于统计真实成本。
7. 新增/修改的工具**必须**先登记注册表再上线（47 §3 P0 原则）。

---

## §5 回滚边界

- 改动集中在三处：`dsh_nodes.py` 的路由与输出整形、`server.py` 的工具定义、注册表两条记录。
- 回滚方式：`git revert` 对应 commit；job 持久层、信封层、gateway 层零改动，回滚不影响既有调用方。
- 快照与缓存目录为纯产物（`reflection_data/snapshots/`、`mcp_cache/`），删除不影响正确性。

---

## §6 风险

| 风险 | 影响 | 对策 |
|---|---|---|
| 超大仓库（如 LobeHub 20k 文件）扫描耗时/内存 | job 超时、壳被网关重拉 | 设 `max_files`（默认 30,000），超限返回 `degraded=true` + `known_gaps`，不静默截断 |
| 缓存 key 只含 mtime/size，极端情况误判 | 返回过期结构 | key 追加 path 列表哈希；支持 `force=true`；同一 commit 内文件数变化必然换 key |
| TS 静态分析盲区（动态 import、运行时路由） | 漏边 | 依赖 `known_gaps` 透传；SKILL 侧规定"结构结论需抽样复核" |
| 模型把 summary 当全貌 | 误判影响面 | SKILL 强制写"未经 `get_rea_snapshot` 复核的影响面结论标注为推断" |
| 认知 hint 被模型改写后写入 | 记忆污染 | SKILL 侧只接受 schema 校验通过的 hint，禁止改写 `quality_level`/`level` |

---

## §7 与既有 SPEC 的关系

| 文档 | 关系 |
|---|---|
| SPEC-L0-MCP-PACKAGING v0.3 | 本 SPEC 是其 P2 域内的能力修补，不改封装协议 |
| TECH-L0-MCP v0.1 | 壳运行时/信封/网关实现以其为准 |
| COLLABORATION-CONTRACT v1.6 | 认知写入治理以其为准；本 SPEC 只产出 hint，不越权写 |
| SPEC-33-反思层 | 反思/replay 池与本 SPEC 的快照并存，快照供分页读取，replay 供复盘 |
| SPEC-33-E | 在其工具面上扩展 audit/methodology/adapt_plan；角色白名单 ≤10 的规则沿用 |
| 3.1 SPEC-A/B/C | 无依赖；本 SPEC 是开发期工具链，不触碰前端代码 |

---

## §8 落地进度（2026-11-11）

| 任务 | 状态 | 证据 |
|---|---|---|
| T-D1 语言路由 | ✅ | `tests/test_dsh_rea_spec_d.py::test_detect_target_language` / `test_analyze_ts_project_routes_to_ts_analyzer`；3.1-FRONTEND 实测 522 文件 / 101,875 行、55 页面 + 109 API；**子目录目标向上继承 `tsconfig.json`**（`src/lib/agent` 场景实测修复） |
| T-D2 scope 三档 + 快照 | ✅ | 实测 summary 15,214 B（≤16KB）、architecture 54,422 B（≤64KB）、full 1,663 B（仅 snapshot）；`test_full_scope_returns_snapshot_only` |
| T-D3 `get_rea_snapshot` | ✅ | 工具面 7 个；`test_snapshot_pagination` / `test_snapshot_invalid_section`；未知 ID → `snapshot_not_found`；实测 dependencies 475 节点 / 688 边分 3 页读完 |
| T-D4 schema 拆分 | ✅ | `test_analyze_schema_scope_and_force` / `test_compare_schema_requires_target_a_b` |
| T-D5 RED 测试 | ✅ | 33-REA 全量 297 passed；`mcp_shells/l0_rea` + `l0_gateway` 16 passed |
| T-D6 内容寻址缓存 | ✅ | 二次调用 `cache_hit=true`（同一目标 summary 0.59 s → architecture 0.21 s）；`test_cache_hit_on_second_call` / `test_force_bypasses_cache` |
| T-D7 profile + 宿主注册 | ✅ | `mcp_profiles.json` `rea-engineer`；`.trae/mcp.json` `rea` server；冷启动 `tools/list` = 8 工具 |
| T-D8 SKILL 双位置 | ✅ | `.trae/skills/dream-rea-architecture-query/`、`1-ARCHITECTURE/skills/...`，registry 已注册 |
| T-D9 `cognitive_hint` | ✅ | summary/architecture 均带 hint（level/quality_level/tags/verify_when）；full 不产出（契约见 §2.6） |
| T-D10 SKILL 侧 record/verify | ✅ | `dream-rea-architecture-query` v1.1.0 §5 三段式：5.1 hint 校验（level/content/tags/known_gaps 缺一不写）→ 5.2 record（等级映射 + `rea-fp` 标记）→ 5.3 改动后 verify（须复跑分析，未复跑/降级禁止 verify，同一 memory_id 只 verify 一次）；双位置同步 |
| T-D11 分析前 recall 去重 | ✅ | `scripts/rea_recall_gate.py`：指纹 `sha1(真实路径\|git HEAD\|scope)[:12]`，输出 `recall_query`/`record_marker`；`decide`：同指纹且 ≤7 天 reuse（复用 snapshot_id），指纹变化/超期/无时间戳 reanalyze；SKILL §3.1 固化为硬流程；`test_t_d11_recall_gate.py` 7 passed |

**§8.1 三场景实测（冷启动 gateway `--role engineer`）**

| 场景 | 目标 | scope | 耗时 | payload | 关键结果 |
|---|---|---|---|---|---|
| A 架构摸底 | 3.1-FRONTEND | summary | 0.40 s | 15,290 B | 524 文件 / 7 个模式 / 4 依赖环 / 18 God 组件；hint=B；`trimmed.evidence=5/15` |
| B 陌生模块 | 52-lobehub协议集成 | summary | 0.21 s | 2,619 B | Python 路由 13 模块（项目内）/ 20 内部依赖 / 16 外部依赖 / 179 函数；快照 modules 分页可读 |
| C 影响面 | 3.1-FRONTEND | architecture | 0.21 s | 54,422 B | 反向依赖 Top：`src/components/index.ts` 72 处、`src/stores/index.ts` 35 处、`src/lib/api-client.ts` 31 处；68 orphan |

**§8.2 已裁决（2026-11-11，用户确认「改」）**：`worker_roles.engineer` 白名单扩至 **10 工具满额**，纳入 `submit_rea_trace`/`poll_rea_trace`；越权验证锚点改为角色外工具 `eval_analyze`（属 verifier，调它必须 `forbidden`）。

**§8.3 三场景实测暴露的四处缺陷已修复（2026-11-11）**

| # | 缺陷 | 修法 | 实测 |
|---|---|---|---|
| 1 | 证据裁剪静默：summary 只回 5/15 条，无任何标记 | `_fit_size` / `_shape_result` 写 `trimmed.{section}={kept,total}` | `trimmed.evidence={kept:5,total:15}`，payload 15,290 B |
| 2 | TS `trace` 的 `feature` 不参与匹配，等于全量图 dump（231 callers / 476 callees） | 按路径→文件内容匹配种子（≤5），只回一跳子图（每种子 ≤10）+ `matched`/`stats` | `feature="sacg timeline"` → 命中 `BACTimeline.tsx` 等 4 个种子；输出 6 upstream / 8 downstream，0.31 s |
| 3 | Python 模块清单混入 stdlib（`argparse`/`json`…），模块数虚高 | 用文件系统推导项目内模块，外部依赖单列 `external_modules` | 52 项目：13 模块（项目内）/ 16 外部 / 20 内部依赖（原报 35 模块 / 77 边） |
| 4 | 影响面无法按子目录回答；`entry="index.ts"` 会静默指向错误模块 | `entry` 泛名多命中时不再猜测（输 `known_gaps`），改用 `feature`；影响面以子目录文件为 `entry` 查 callers | `entry="src/lib/agent/distill-outbox.ts"` → callers=`app/api/.../route.ts`；`entry="index.ts"` → 明确告警并退回 feature |

回归：33-REA 全量 **301 passed**；`l0_rea` + `l0_gateway` **16 passed**；ruff 全绿。

**附带修复**：`investigation_workflow` 目录分支接入 `TSProjectAnalyzer`（locate/trace），`detect_architecture_patterns` 前端路由，`tests/test_integration.py` 的 full 契约对齐 §2.3。
