# SPEC-F: 33-REA 能力增强 — 对标传统工程与 AI 工程

> 版本：v0.14.0
> 日期：2026-11-12
> 状态：✅ P0 5 项 + P1 10 项 + P2 4 项已落地（未提交）；T-F16 由观察项转为「可选调用」（默认关闭）
> 变更（v0.13.0 → v0.14.0）：T-F16 改为复用现有检索系统——新增 `adapters/semantic_adapter.py`（复用 41 文件索引系统本机向量桥，默认关闭、socket/命令双通道、FAIL-OPEN）与 `section=semantic`；内核不自建 embedding、不访问网络，暂不改 trace 排序
> 变更（v0.12.1 → v0.13.0）：T-F13 受限图查询 DSL（`section=graph`）、T-F15 污点分析外挂（4 类 sink + SARIF 汇入）、T-F17 文件级 Merkle 增量索引、T-F18 Mermaid + 一页 wiki（`section=diagram`）按 TDD 落地
> 变更（v0.12.0 → v0.12.1）：补齐 P1 六项总回归证据（聚焦 35、核心 591 passed、壳 30、注册表 54 active、变更范围 ruff 全绿）
> 变更（v0.11.0 → v0.12.0）：T-F14 运行时/覆盖对账按 TDD 落地；复用 coverage.xml，新增 OTel JSON/JSONL span、零覆盖模块与 `section=runtime`，静态节点按真实观测标注 confirmed/contradicted/unobserved
> 变更（v0.10.0 → v0.11.0）：T-F09 LSP/语言服务适配环按 TDD 落地；Jedi 符号引用、pyright/tsserver 诊断统一降级，新增可选 `lsp` 与 `section=diagnostics`，真实对照实验解析率提升 100 个百分点
> 变更（v0.9.0 → v0.10.0）：T-F08 依赖卫生与 SBOM 按 TDD 落地；deptry/knip/OSV 统一降级，固定无 shell 子进程与最小环境，新增 `section=dependency_hygiene` 和 CycloneDX 1.5 输出
> 变更（v0.8.0 → v0.9.0）：T-F11 metrics 阈值门禁与历史趋势按 TDD 落地；可选 JSON/YAML 配置超阈值产出 Evidence，历史快照输出 delta/direction，缺失或损坏时降级
> 变更（v0.7.0 → v0.8.0）：T-F07 只读 git 变更考古按 TDD 落地；hotspot Top20、共变、bus factor、90 天半径接入 `section=archaeology`，全程无网络
> 变更（v0.6.0 → v0.7.0）：T-F12 确定性 Markdown 语料包按 TDD 落地；`section=pack` 支持字节预算、trimmed 与 cursor 续页，真实 Python 冒烟 2 文件 / 183B
> 变更（v0.5.0 → v0.6.0）：T-F20 deadline/cancel 契约按 TDD 落地；真实 stdio 验证 timeout、协作取消与 5s 强制取消，核心全量回归 556 passed
> 变更（v0.4.0 → v0.5.0）：T-F19 工具目录热/冷分层与 compact schema 按 TDD 落地；真实 engineer 默认目录 5191B，全量回归 556 passed
> 变更（v0.3.0 → v0.4.0）：T-F06 架构约束引擎与 T-F10 SARIF 2.1.0 输出按 TDD 落地；全量回归 556 passed
> 变更（v0.2.0 → v0.3.0）：T-F01~T-F05 全部 TDD 落地（含评测基线 30 条 golden queries）；全量回归 539 passed
> 变更（v0.1.0 → v0.2.0）：新增 §0.6 上游同名工程核实；T-F14 运行时/覆盖从 P2 提级到 P1；新增 T-F19（工具目录热/冷分层）、T-F20（deadline/cancel 契约）；T-F16 语义检索降级为观察项（不承诺）
> 归属：33-REA逆向解析工程（能力内核 + 适配环）
> 上游：[SPEC-33-D](./SPEC-33-D-REA作为L0MCP的工程开发协作.md)、[SPEC-33-E](./SPEC-33-E-LLM混合层-假设生成与PoE裁判.md)
> 输入：2026-11-11 REA 六工具实测（§0.2）+ 传统工程/AI 工程对标调研（§0.4）+ 上游同名工程核实（§0.6）

---

## §0 背景与结论

### 0.1 一句话结论

REA 的**结构层**（依赖图、路由/组件/store 识别、模式识别、调用链、快照分页、字节预算、Evidence 纪律）已达到可用水平；缺的是**规则层、度量层、排序层、评测层**。本期增强全部走**适配环**（子进程外挂成熟工具 + 统一 Evidence 归一），内核继续保持零 LLM 与确定性，不重写任何已有分析器。

### 0.2 现状证据（2026-11-11 实测，`l0_gateway --role engineer`）

| 能力 | 实测数据 | 耗时 |
|---|---|---|
| analyze TS（3.1-FRONTEND） | 526 文件 / 102,389 行；55 页面路由 + 110 API；222 组件；12 store；477 节点 / 689 边 / 4 环；7 种模式；15 条 Evidence | 0.82s |
| analyze Python（33-REA） | 91 项目内模块 / 107 内部依赖 / 819 函数 / 35 外部依赖 | 1.62s |
| trace（feature=agent distill outbox） | 5 种子 → 上游 3 / 下游 7，`callers` 精确到 `src/app/api/agent/chat/route.ts` | 0.68s |
| compare（3-FRONTEND ↔ 3.1-FRONTEND） | 77 个同名函数；差异模块清单 | 1.06s |
| rea_audit（H-001，含目录级 ref） | poe=0.445 → **reject**，level=unknown，未写认知 | 1.32s |
| get_rea_methodology（2 项目） | 0 模板（fail-open，带 known_gaps） | 1.32s |
| 三档 scope 字节数 | summary 15,289 B（≤16KB，evidence 裁剪 5/15）；architecture 54,577 B（≤64KB）；full 1,663 B（仅 snapshot_id） | — |
| 缓存与分页 | 重复调用 `cache_hit=True`；snapshot `total=477 / limit=3 / next_cursor=3` | — |

**结论**：预算、缓存、分页、Evidence 分级都是真做到的；缺口不在"能不能扫"，而在"扫出来之后能不能判定、排序、验收"。

### 0.3 实测缺陷（本期 P0 必修）

| # | 缺陷 | 证据 | 根因 |
|---|---|---|---|
| P-F01 | Python analyze 同一响应内数字自相矛盾 | summary「91 模块 / 107 依赖」vs Evidence「144 节点 / 524 边」 | [dependency_graph.py](../33-REA逆向解析工程/core/dependency_graph.py#L138-L153) 统计全部 py 文件（含 tests、外部模块），summary 只统计项目内，两者口径未标注 |
| P-F02 | `compare.common.modules` 恒为空 | 77 个同名函数命中，common.modules=[] | modules 按完整路径比对（两工程路径必不同），functions 按裸名比对，同一响应两套口径 |
| P-F03 | `target_refs` 不支持目录级引用 | `"src/stores"` 未解析 → 1/2 命中 → poe 0.445 → reject + unknown | [hypothesis.py](../33-REA逆向解析工程/core/hypothesis.py#L49-L74) 只做「节点全等 / 路径后缀 / 点分 / 扩展名归一」，无目录前缀展开；且部分命中直接落到 reject 与 unknown |

### 0.4 对标差距矩阵（调研结论 → 任务映射）

> 本矩阵对标的是**传统工程工具链与 AI 工程实践**，不是同名上游工程 `morluto/rea`；后者核实见 §0.6。

**传统工程**

| # | 能力维度 | REA 现状 | 代表工具/实践 | 差距 | 任务 |
|---|---|---|---|---|---|
| P-F04 | 规则/缺陷检查 | 无 | Semgrep、SonarQube、ESLint、ruff | 只有结构，无规则引擎与基线告警 | T-F04 |
| P-F05 | 复杂度/死代码/克隆 | 无 | radon、lizard、vulture、jscpd | 无圈复杂度、未使用符号、重复代码 | T-F05 |
| P-F06 | 类型级诊断 | 无 | pyright、mypy、tsc | 不读类型注解，跨模块类型断裂不可见 | T-F09 |
| P-F07 | 架构约束判定 | 弱（有图无规则） | ArchUnit、import-linter、dependency-cruiser | 无法判定「禁止 store→api」类违例 | T-F06 |
| P-F08 | 依赖卫生 / SBOM | 弱（只有 external_deps 列表） | deptry、knip、Syft、OSV-Scanner | 未对账声明依赖与实际引用，无 CVE/许可证 | T-F08 |
| P-F09 | 结构度量门禁与趋势 | 有指标无门禁 | Structure101、NDepend、jQAssistant | 有 cycles/hubs/orphans，无阈值门禁与历史趋势 | T-F11 |
| P-F10 | 变更考古 | 无 | code-maat、CodeScene | 无 git 共变矩阵、hotspot、bus factor | T-F07 |
| P-F11 | 运行时/覆盖视角 | 无 | coverage.py、OpenTelemetry、py-spy | 只有静态链，不知零覆盖模块与真实 span | T-F14 |
| P-F12 | 污点分析 | 无 | CodeQL、Semgrep taint | 无 source→sink 数据流 | T-F15 |
| P-F13 | 标准输出 | 无 | SARIF 2.1.0 | 结果进不了 GitHub Code Scanning / IDE | T-F10 |

**AI 工程**

| # | 能力维度 | REA 现状 | 代表实践 | 差距 | 任务 |
|---|---|---|---|---|---|
| P-F14 | 相关性排序 | 弱（关键词种子 + 一跳） | Aider repo map（tree-sitter + PageRank + token 预算二分） | 477 节点时覆盖不足，无重要性排序，content 兜底从未触发 | T-F02 |
| P-F15 | 符号级检索 | 无 | Serena（LSP）、clangd index、pyright index | 无 find_references / 类型层级 / diagnostics | T-F09 |
| P-F16 | 语义检索 | 无 | Cursor 索引、Cody、GraphRAG | 词面不重叠即漏检 | T-F16 |
| P-F17 | 语料打包 | 弱（有快照无打包） | repomix、gitingest | 无「一包可读语料」供宿主 LLM | T-F12 |
| P-F18 | 增量索引 | 弱（有内容寻址缓存） | Cursor Merkle、SCIP | 无文件级失效与跨版本 diff | T-F17 |
| P-F19 | 文档/wiki/架构图 | 弱（有 narrative/decisions） | DeepWiki、Swimm、Mermaid | 无读者向 wiki 与自动架构图 | T-F18 |
| P-F20 | 评测基线 | **无** | SWE-bench、RepoBench、CodeRAG-Bench | 无 recall@k / 证据存活率，任何增强都无法证伪 | T-F03 |
| P-F21 | ad-hoc 图查询 | 无 | jQAssistant（Neo4j） | 固定输出，无法按需查询 | T-F13 |
| P-F22 | 工具目录/上下文开销 | 弱（9 工具全量 schema） | 上游 hot/cold catalog、Aider 上下文分层 | 无热/冷分层，能力增长会线性推高 `tools/list` 体积 | T-F19 |
| P-F23 | 任务生命周期 | 弱（submit/poll 无取消、无截止） | 上游 "Error recovery and deadline ownership"、MCP cancellation | 宿主只能无限轮询，无法中止长任务 | T-F20 |

### 0.5 非目标（明确不做）

1. **不重写分析器**：不替换 TS/Python 解析器，不追求 Semantic 级精度；精度问题交给 LSP/编译器外挂。
2. **不把 LLM 放进内核**：任何摘要、命名、排序建议都不在内核产生。
3. **不做平台**：不引入 SonarQube 服务端、不建代码扫描 SaaS，只取规则语义。
4. **不默认返回全图**：字节预算与 `full→snapshot_id` 规则不变。
5. **不自研漏洞库**：CVE/许可证只做透传与汇总。

### 0.6 上游同名工程核实（`morluto/rea`，2026-11-11）

**身份核实**：NPM `rea-agents@6.8.0` 的实现仓库为 `morluto/rea`（截至 2026-11-11 API 返回：451k stars / 111k forks / 2026-04 创建 / TypeScript / 约 156MB / 133 个 MCP 工具）。其 `src/` 能力域为 `ghidra / ida / apktool / frida / gdb / dotnet / electron / evm / firmware / flutter / android / ios / harmony`。

**结论一：不是同一坐标系。** 上游做**二进制与应用包逆向**（函数级反编译、原生/托管边界、静态↔运行时对账）；本工程做**源码架构解析**（TS/Python 依赖图、路由/组件/store、调用链、假设裁判）。因此 v0.1.0 中"我们缺 N 项"的表述**不能用来评价上游**，上游也不存在被我们"补齐"的同一功能面。

**结论二：逐项核实（GitHub code search 全仓计数）**

| 能力 | 上游 | 证据 |
|---|---|---|
| 圈复杂度/度量 | ❌ 无 | `cyclomatic` = 0 |
| 相关性排序（PPR/rank） | ❌ 无 | `pagerank` = 0，`rank` = 0，`score` = 1 |
| recall@k 评测基线 | ❌ 无 | `recall@` = 0 |
| 规则引擎（Semgrep 式） | ❌ 无 | `semgrep` = 0 |
| SARIF 自产 | ❌ 无 | 仅 `docs/development/testing.md` 提到 CI 内跑 **CodeQL** 产 SARIF，非自身输出格式 |
| git 变更考古 | ❌ 无 | `hotspot`/`churn` 命中均为 Ghidra 启动、ProcessOwnership 噪声 |
| LSP 符号检索 | ❌ 无 | `lsp` 命中为 fixture 字符串与 pyc 解析代码，无 LSP 客户端 |
| 上下文/预算纪律 | ✅ 强 | `budget` 30 处、`deadline` 34、`limitation` 30、`evidence` 233 |
| 工具目录热/冷分层 | ✅ 有 | "Hot/cold catalog discovery""Tool family advertising scope""Compact input schema profile""Generated catalog" |
| 静态↔运行时交叉 | ✅ 有（核心卖点） | `reconcile_javascript_runtime`、`correlate_static_and_runtime`、`compare_static_and_observed_endpoints` |
| 效率评测语料 | ✅ 有（非 recall@k） | `tests/support/analysis-efficiency/` 确定性检查器 + fixtures；`experiments/analysis-efficiency` 已归档 |

**结论三：对本 SPEC 的三点修订**

- **A 真增益**：上游同样缺"度量 / 排序 / 评测 / 规则 / 变更考古 / SARIF 自产"六类，说明本 SPEC 的 P0/P1 主体不是重复造轮子，而是源码工程治理轴上的真实空白。
- **B 借鉴后调整**：① `T-F14` 运行时/覆盖**从 P2 提级到 P1**——上游把"静态结论必须有运行时观测对账"作为差异化核心；② 新增 `T-F19` 工具目录热/冷分层与 compact schema（本 SPEC 要加 5 个 section，schema 会膨胀，需控制宿主上下文开销）；③ 新增 `T-F20` deadline/cancel 契约（上游专设 "Error recovery and deadline ownership"，我们只有 submit/poll，无取消与截止时间）。
- **C 降级**：`T-F16` 语义混合检索降级为**观察项（不承诺）**——上游没有、我们也没有 recall 基线支撑，先不排期。

**方法局限（如实说明）**：上游仓库约 156MB，核实手段为 GitHub code search 计数 + 文档阅读（README / `docs/reference/mcp-contracts.md` 2404 行 / `docs/development/testing.md` / `docs/capability-composition.md`），属粗粒度抽样；`ownership` 命中 916 次多为 "capability ownership" 语义，非代码归属分析。逐条确认需浅克隆后做 AST 级核查。

---

## §1 目标与验收指标

| 目标 | 内容 | 验收指标 |
|---|---|---|
| G-F1 | 修 3 个实测缺陷 | 同一响应内模块/边数一致（脚本断言）；compare 的 modules 与 functions 口径统一；目录级 ref 可解析或降级为 review（不再误判 reject） |
| G-F2 | trace 相关性排序 | 30 条 golden query 上 recall@10 ≥ 0.80；输出 ≤8KB；同输入两次运行结果**逐字节一致** |
| G-F3 | 评测 harness 可跑 | `python3 scripts/rea_eval.py` 输出 recall@k / precision / 证据存活率 / 字节预算命中率 |
| G-F4 | 度量层接入 | radon/lizard/vulture/jscpd 至少 3 个可用；工具缺失时 `degraded=true` 且不抛错 |
| G-F5 | 架构约束判定 | 规则文件可声明「禁止 A→B」「禁止跨层引用」；违例产出 Evidence 且带文件行号 |
| G-F6 | 变更考古 | 输出 hotspot Top20、共变矩阵、bus factor；只用本地 git，无网络 |
| G-F7 | SARIF 输出 | 产出 SARIF 2.1.0，通过 schema 校验并可被 GitHub Code Scanning 消费 |
| G-F8 | LSP 符号检索 | `target_refs` 复核的解析率相对当前基线提升 ≥20 个百分点（对照实验） |
| G-F9 | 工具目录热/冷分层 | `tools/list` 默认只暴露"热"工具与 compact schema；冷工具需显式 `family` 参数发现；单次 `tools/list` 响应 ≤8KB |
| G-F10 | deadline / cancel 契约 | 每个 submit 支持 `deadline_ms`；新增 `cancel_rea_<kind>`，取消后 job 在 5s 内进入 `cancelled` 终态并落持久层 |

---

## §2 总体设计

### 2.1 三环分层（关键约束）

```
内核环（确定性 · 零 LLM · 无网络）
  ├── 现有分析器（TS/Python/依赖图/调用链/模式识别）
  └── 新增：PPR 排序、约束引擎、Evidence 归一

适配环（子进程 · 超时 · FAIL-OPEN · degraded 标记）
  ├── 质量度量：radon / lizard / vulture / jscpd
  ├── 规则扫描：ruff / ESLint / Semgrep（可选）
  ├── 类型诊断：pyright / tsc --noEmit
  ├── 依赖治理：import-linter / dependency-cruiser / deptry / knip
  └── 变更考古：git log（本地命令，无网络）

宿主环（LLM · 不在 33 内）
  └── 消费 Evidence → 写 wiki / 架构图 / 改造方案
```

**硬性分界**：适配环的每个工具都是「子进程 + 超时 + 输出解析 → Evidence」，禁止在主进程 import 它们的 Python 包并深度耦合。

### 2.2 相关性排序子图（解决 P-F14）

替代当前「关键词种子 + 一跳」的 trace 实现：

```
输入：target, feature, entry(可选), budget_bytes(默认 8192), hops(默认 2)
步骤：
  1. 种子集 = 路径匹配 ∪ 内容匹配 ∪ entry（显式指定时权重最高）
  2. 在现有 adjacency 上做 Personalized PageRank
     - 固定 damping=0.85、固定 max_iter=50、tol=1e-8
     - 禁止随机初始化（用均匀分布作为初始向量）
  3. 从 Top-K 种子做 1..hops 跳扩展，按 PPR 分数降序
  4. 预算内二分裁剪（按字节数），被裁掉的条目写入 trimmed
输出：ranked_nodes[score], edges, seeds, stats, trimmed, evidence(排序算法+参数)
```

**确定性要求**：同 target + feature + budget 两次运行，输出逐字节一致（禁止依赖 dict 顺序之外的随机性；所有集合输出前排序）。

### 2.3 契约修正（解决 P-F01/F02/F03）

| 缺陷 | 修法 | 约束 |
|---|---|---|
| P-F01 双口径 | Python analyze 的 Evidence 明确标注 `scope: "all_files"` 或 `"project_internal"`，并在 summary 与 Evidence 使用同一分母；或 Evidence 直接复述 summary 数字 | 不得改 summary 语义 |
| P-F02 compare 口径 | modules 增加按「相对路径尾段名」比对的 `common_module_names`；`common.modules` 保留完整路径语义并在字段说明中标注 | 只增字段，不改已有字段 |
| P-F03 目录级 ref | `resolve_target_refs` 增加目录前缀展开：ref 是某节点路径前缀时，记为该目录下所有节点命中；目录命中导致 ratio 极高时**gate 仍不得为 pass**（目录不构成精确定位），最高 review | 目录命中必须写入 reasons |

### 2.4 度量适配层（解决 P-F05）

| 工具 | 语言 | 产出 | 缺失时 |
|---|---|---|---|
| radon | Python | 圈复杂度（cc_rank）、可维护性指数 MI | degraded |
| lizard | Python/TS | 函数级复杂度、参数个数、函数长度 | degraded |
| vulture | Python | 未使用函数/变量/导入（置信度 ≥80 才采信） | degraded |
| jscpd | TS | 重复代码块（≥50 token） | degraded |

统一输出 `metrics` section：

```json
{
  "section": "metrics",
  "tools": {"radon": {"available": true, "version": "6.0.1"}, "jscpd": {"available": false, "reason": "npx not found"}},
  "complexity": {"max_cc": 24, "avg_cc": 3.1, "top": [{"file": "...", "function": "...", "cc": 24}]},
  "dead_code": [{"file": "...", "symbol": "...", "confidence": 90}],
  "duplication": {"ratio": 0.07, "blocks": 12},
  "evidence": [],
  "known_gaps": []
}
```

### 2.5 架构约束引擎（解决 P-F07）

规则文件 `rea_rules.yaml`（仓库根可选）：

```yaml
version: 1
layers:                      # 层的成员定义（glob）
  ui:      ["3.1-FRONTEND/src/components/**", "3.1-FRONTEND/src/app/**"]
  store:   ["3.1-FRONTEND/src/stores/**"]
  lib:     ["3.1-FRONTEND/src/lib/**"]
rules:
  - id: no-store-to-api
    type: forbid_edge
    from: store
    to: lib/agent
    message: "store 不得直接依赖 agent 客户端"
  - id: no-cross-layer-cycle
    type: forbid_cycle
    scope: [ui, store, lib]
  - id: max-fan-out
    type: threshold
    metric: fan_out
    max: 25
    scope: ui
```

违例输出统一 Evidence（`level=derivation`，含 `file`/`line`/`rule_id`）。

### 2.6 变更考古（解决 P-F10）

只用本地 `git log`（`--numstat --name-only`），不做网络请求：

- **hotspot**：变更次数 × 复杂度（没有复杂度就用行数）Top-N
- **共变矩阵**：同一 commit 内共同出现的文件对，`support ≥ 5 且 confidence ≥ 0.6` 才输出
- **bus factor**：按作者聚合文件数，累计 50% 所需作者数 ≤1 视为高风险
- **变更半径**：近 90 天被修改文件与其依赖邻居的比值

### 2.7 LSP 适配（解决 P-F06/F15）

- Python：`pyright --outputjson`（诊断）；符号引用优先用 `pyright` 的语言服务器或 `jedi` 兜底（**待核实，见 Q3**）
- TS：`tsserver` 的 `findReferences` / `getDefinition`
- 进程池 + 单次请求超时 5s + 启动超时 20s；不可用时整段降级为 `degraded`
- 用途**仅限**：`target_refs` 精确复核、`trace` 种子扩展、诊断汇入 Evidence

### 2.8 SARIF 输出（解决 P-F13）

把 `cognitive_debt`、规则违例、known_gaps 转 SARIF 2.1.0：

```
tool.driver.name = "33-REA"
results[].ruleId   = 缺陷/规则 ID
results[].level    = error|warning|note（pass→note, review→warning, reject→error）
results[].locations[].physicalLocation.artifactLocation.uri = 相对仓库路径
```

落盘 `reflection_data/sarif/<snapshot_id>.sarif`，并在 `get_rea_snapshot` 增加 `section=sarif`。

### 2.9 评测 harness（解决 P-F20 · 最高优先级之一）

- 语料：`tests/eval/golden_queries.yaml`，30-50 条，形如

```yaml
- id: Q-001
  target: 3.1-FRONTEND
  feature: "agent distill outbox"
  expected: ["src/lib/agent/distill-outbox.ts", "src/app/api/agent/chat/route.ts"]
  must_not_include: ["src/components/AppShell.tsx"]
```

- 指标：`recall@k`、`precision@k`、证据存活率（输出中保留的 Evidence 条数 / 产出条数）、字节预算命中率
- 门槛（CI 可断言）：trace recall@10 ≥ 0.80；analyze 产出的每条结论都有 Evidence

### 2.10 语料打包（解决 P-F17）

`get_rea_snapshot(section=pack)`：按「文件 → 符号 → 依赖」顺序输出单文件 Markdown，带字节预算与 `trimmed`，供宿主 LLM 直接读。**内核不生成任何自然语言摘要**，只做结构化拼接。

### 2.11 工具目录热/冷分层与 compact schema（解决 G-F9 · 借鉴上游）

本期要新增 5 个 section（metrics / rules / archaeology / sarif / pack）与可能的 `auditor` 角色，`tools/list` 的 schema 开销会显著上涨。分层规则：

```
热（hot）：engineer 角色默认暴露 → 完整 inputSchema
  submit/poll_rea_analyze, submit/poll_rea_trace, submit/poll_rea_compare,
  get_rea_snapshot, rea_audit, get_rea_methodology, recall

冷（cold）：默认只给 name + description + family，调用方显式请求后展开 schema
  rea_metrics, rea_rules, rea_archaeology, rea_sarif, rea_pack, rea_cancel_*

发现协议：
  tools/list?family=metrics        → 返回该族完整 schema
  tools/list                       → 热工具完整 schema + 冷工具单行条目
预算：热工具整体 ≤8KB；单个冷族 schema ≤4KB；超限走 trimmed
```

**约束**：分层只影响 `tools/list` 的呈现，不影响 `tools/call` 的能力；冷工具仍可被直接调用。

### 2.12 deadline 与取消契约（解决 G-F10 · 借鉴上游）

现状只有 `submit_* / poll_*`，无截止时间与取消，宿主只能一直轮询。

```
submit_*.deadline_ms：可选，默认 120000；超时 job 置 state=timeout（终态）
cancel_rea_<kind>.job_id：
  1. 置 cancel_requested 标记（持久层）
  2. worker 在安全检查点（节点边界，非任意打断）退出 → state=cancelled
  3. 5s 内未响应 → 强制置 cancelled 并记录 forced=true
poll_*：新增终态 cancelled / timeout；两者都带 reason
```

**约束**：取消是**协作式**的（检查点退出），不做线程强杀；`cancelled` 的 job 不产出 result，只保留已完成部分的 `partial_stats`。

### 2.13 剩余 P1 实施契约（2026-11-12 已评审）

按方案 A 逐项垂直落地，每项独立完成 RED → GREEN → 接线 → 回归 → SPEC/认知闭环，禁止六项一次性实现后统一测试。顺序与最小契约如下：

1. **T-F12**：确定性 Markdown 按「文件 → 符号 → 依赖」拼接；`section=pack` 支持字节预算与 `trimmed`，不生成自然语言摘要。
2. **T-F07**：复用只读 git 基础，输出 hotspot Top20、共变矩阵、bus factor、90 天变更半径；接入 `section=archaeology`，全程无网络。
3. **T-F11**：复用 metrics 适配器，可选配置声明阈值并与历史快照比较；超阈值产出 Evidence，可选非零退出码不作为本期必做项。
4. **T-F08**：整合依赖清单、deptry/knip 与 OSV，输出未使用依赖、CVE 和 CycloneDX SBOM。OSV 允许联网，但仅通过固定可执行命令与参数调用，禁止 `shell=True`，限制超时且不得读取或上传凭据；`REA_OSV_ENABLED=0` 可禁用，工具/网络失败均 `degraded`。
5. **T-F09**：Python 使用 pyright 诊断与 Jedi 引用兜底，TS 使用 tsserver；启动/请求超时分别 20s/5s。仅接入 `target_refs` 精确复核、trace 种子扩展与诊断 Evidence，以对照测试验证解析率提升 ≥20 个百分点。
6. **T-F14**：复用 coverage.xml 解析并增加 OTel JSON/JSONL span 输入；列出零覆盖模块，为静态节点标注 `confirmed/contradicted`，接入 `section=runtime`。报告缺失时降级，不伪造运行数据。

所有新增 section 只增不改既有字段；engineer 工具白名单保持 10 个；不清理既有工作树，不提交代码。

---

## §3 分阶段实施

### P0 — 修缺陷 + 建度量（本期必做）

| 任务 | 内容 | 依赖 | 验收 |
|---|---|---|---|
| T-F01 | 修 P-F01/F02/F03（双口径、compare 口径、目录级 ref） | 无 | G-F1 |
| T-F02 | trace v2：PPR + 预算裁剪 + 确定性 | 无 | G-F2 |
| T-F03 | 评测 harness（golden_queries + 指标报告） | T-F02 | G-F3 |
| T-F04 | 规则扫描适配：ruff / ESLint，输出归一为 Evidence | 无 | 有违例即出 Evidence，工具缺失 degraded |
| T-F05 | 度量适配层：radon / lizard / vulture / jscpd | 无 | G-F4 |

> 顺序约束：T-F03 必须在 T-F02 之后立刻做——否则后续所有增强都无法证伪。

### P1 — 治理、符号精度与运行时对账

| 任务 | 内容 | 依赖 | 验收 |
|---|---|---|---|
| T-F06 | 架构约束引擎 + `rea_rules.yaml` | T-F01 | G-F5 |
| T-F07 | 变更考古：hotspot / 共变 / bus factor | 无 | G-F6 |
| T-F08 | 依赖卫生 + SBOM：deptry / knip / OSV | 无 | 未使用依赖与 CVE 可列出 |
| T-F09 | LSP 适配：find_references + diagnostics | 无 | G-F8 |
| T-F10 | SARIF 输出 + `section=sarif` | T-F04/T-F06 | G-F7 |
| T-F11 | 结构度量门禁与趋势（阈值 + 历史快照对比） | T-F05 | 超阈值即 Evidence + 非零退出码（可选） |
| T-F12 | 语料打包 `section=pack` | 无 | ≤预算、可被宿主直接读 |
| T-F14 | 运行时/覆盖：coverage.py + OTel span 汇入图（**v0.2.0 从 P2 提级**） | 运行环境 | 零覆盖模块可列出；静态结论可被运行时观测标注 confirmed/contradicted |
| T-F19 | 工具目录热/冷分层 + compact schema（**v0.2.0 新增**） | 无 | G-F9 |
| T-F20 | deadline / cancel 契约（**v0.2.0 新增**） | 无 | G-F10 |

> T-F14 提级理由见 §0.6：上游把"静态结论必须有运行时观测对账"当作差异化核心，我们的 trace/analyze 目前只有静态一侧。

### P2 — 语义与扩展

| 任务 | 内容 | 依赖 | 验收 |
|---|---|---|---|
| T-F13 | ad-hoc 图查询 DSL（受限的路径/子图查询） | T-F06 | 查询结果带 Evidence |
| T-F15 | 污点分析外挂（Semgrep/CodeQL，SARIF 汇入） | T-F10 | 至少 3 类 sink 可检出 |
| T-F16 | 语义检索：复用 41 文件索引系统向量桥（`REA_SEMANTIC_ENABLED=1` 开启，默认关闭） | 41-文件索引系统 | 通道可用时返回带路径/分数的 top-k 命中；通道缺失返回 degraded + known_gaps，不伪造数据 |
| T-F17 | 增量索引（Merkle / 跨版本 diff） | 无 | 文件级失效，重复分析量下降可测 |
| T-F18 | 文档/wiki 与架构图（宿主侧 LLM 消费 Evidence） | T-F12 | 产出一张 Mermaid 架构图 + 一页 wiki |

---

## §4 硬约束

1. **内核零 LLM**：33 内不得出现任何模型调用；LLM 只在宿主环。
2. **适配环一律子进程**：外部工具必须带超时（默认 120s）、失败 FAIL-OPEN、结果标 `degraded` 与原因。
3. **不得引入常驻平台**：禁止 SonarQube/Neo4j/CodeScene 服务端依赖。
4. **确定性**：PPR 固定参数与初始化；所有集合类输出排序后再序列化。
5. **证据先行**：每条新增结论必须带 `provenance` + `confidence` + `known_gaps`；无证据的结论不得输出。
6. **字节预算不放松**：新 section 默认 ≤8KB；超限必须 `trimmed` 留痕。
7. **只增不改**：既有工具的字段语义不变；新能力加到新 section / 新工具，不破坏 SPEC-D/E 契约。
8. **白名单不扩**：engineer 保持 10 工具；新能力优先以 `get_rea_snapshot` 的 section 形式提供，必须新增工具时走独立角色（见 Q1）。
9. **不输出原始文件内容**：语料打包需经预算裁剪，禁止整仓转储。
10. **取消必须协作式**：禁止线程强杀；检查点只在节点边界，强制取消需标 `forced=true`。
11. **分层只改呈现**：热/冷目录只影响 `tools/list`，不得改变任何工具的调用能力与返回契约。

---

## §5 回滚边界

| 变更 | 回滚方式 |
|---|---|
| trace v2 | 保留 `trace_v1` 开关（参数 `algorithm=legacy`），默认 v2；回归失败即切回 |
| 适配环工具 | 每个适配器独立开关（`REA_ADAPTER_RADON=0` 等），关闭即回到纯内核输出 |
| 规则引擎 | 无 `rea_rules.yaml` 时完全跳过，零行为变化 |
| SARIF / pack | 纯新增 section，不改变既有字段 |
| 变更考古 | 只读 git，无写入；删除任务即回滚 |
| 工具目录分层（T-F19） | `REA_CATALOG_HOT_ONLY=0` 恢复为全量 schema 一次返回 |
| deadline / cancel（T-F20） | `REA_DEADLINE_ENABLED=0` 时忽略 `deadline_ms`；cancel 工具保留但仅置标记、不改变轮询语义 |

---

## §6 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 适配工具版本漂移导致输出格式变化 | 解析失败 | 每个适配器有 schema 断言 + 失败降级；CI 固定版本 |
| jscpd 依赖 node/npx | 云端可能不可用 | 视为可选，缺失即 degraded |
| LSP 常驻进程拖慢 MCP 冷启动 | 宿主超时 | 懒启动 + 空闲 60s 回收 + 启动超时 20s |
| PPR 让结果"看起来更全"但实际相关性下降 | 误导演示 | 用 T-F03 harness 做前后对照，recall 不升即回滚 |
| 规则误报引发无谓改造 | 信任度下降 | 规则默认 `note` 级；只有显式配置才升 `error` |
| 变更考古在大仓库上慢 | 超时 | 限制 `git log` 时间窗（默认 180 天）与文件数上限 |
| 冷工具被分层隐藏，宿主"找不到能力" | 可用性下降 | 冷工具仍返回单行条目 + `family` 提示；文档与 SKILL 同步更新 |
| 取消检查点粒度不足，只能 forced 取消 | 取消语义名不副实 | 只在节点边界检查；单节点最长执行时间纳入预算（大目录拆分分析单元） |

---

## §7 与既有 SPEC 的关系

| 文档 | 关系 |
|---|---|
| SPEC-33-D | 本 SPEC 沿用其输出分级、快照缓存、MCP 契约；新增能力以 section/工具扩展方式接入 |
| SPEC-33-E | T-F01 直接修 E 的裁判缺陷（P-F03）；T-F03 harness 为 E 的假设判定提供可量化基线 |
| SPEC-33-输出场景-意图系统 | T-F12 pack 与 T-F18 wiki 为其输出形态补齐"可读语料" |
| SPEC-33-反思层 | 变更考古（T-F07）为反思层提供真实变更事实，替代流程日志 |
| COLLABORATION-CONTRACT v1.6 | 本 SPEC 不新增写工具；所有新能力只读 |
| `morluto/rea`（上游同名工程，非本工程上游代码） | 仅作能力对标参考（§0.6）：借鉴其静态↔运行时对账、工具目录热/冷分层、deadline/cancel 三项；不引入其代码与依赖 |
| SPEC-33-G（反思进化与策略晋级） | 消费本 SPEC 的 T-F03（评测基线）、T-F06（约束引擎）、T-F11（度量门禁）作为晋级门禁的输入；本 SPEC 不承担策略晋级 |

---

## §8 落地进度

| 任务 | 状态 | 证据 |
|---|---|---|
| T-F01 | ✅ 已落地 | [test_t_f01_contract_fixes.py](./tests/test_t_f01_contract_fixes.py) 5 passed：① Python analyze 同时产出 `scope=project_internal`（复述 summary 的 modules/edges 数值）与 `scope=all_files` 两条依赖图证据，`provenance.modules/edges` 与 `stats` 同分母；② `compare.common.common_module_names` 按相对路径 basename 比对（`src/a/cartStore.ts` ↔ `src/b/cartStore.ts` 命中），`common.modules` 保持完整路径语义不变；③ `resolve_target_refs` 支持目录前缀展开，`audit_hypothesis` 对目录命中写入 reasons 且 gate 封顶 review（不再误判 pass/reject+unknown） |
| T-F02 | ✅ 已落地 | [graph_rank.py](./core/graph_rank.py) 手写确定性 PPR（damping=0.85/max_iter=50/tol=1e-8，无随机初始化，节点字典序，分数 6 位）；trace v2 输出 `algorithm/ranked_nodes/edges/seeds/trimmed`，默认 `budget_bytes=8192`、`hops=2`，`algorithm=legacy` 可一键回滚。证据：[test_t_f02_trace_ppr.py](./tests/test_t_f02_trace_ppr.py) 5 passed（含两次运行 `json.dumps(sort_keys=True)` 逐字节一致、3000B 预算下 trimmed 生效） |
| T-F03 | ✅ 已落地 | [golden_queries.yaml](./tests/eval/golden_queries.yaml) 30 条（20 单文件 + 10 双文件关联）；[rea_eval.py](./scripts/rea_eval.py) 输出 recall@k/precision@k/证据存活率/预算命中率；基线 [baseline.json](./tests/eval/baseline.json)：recall@10=0.9833、budget_hit=1.0、evidence_min_ok=true、pass=true（Q26 为唯一 0.5 召回，期望 `task-manager.ts` 排名被 planner 目录淹没，作为已知缺口保留）。测试 4 passed（含 golden 文件存在性校验与 limit=3 端到端） |
| T-F04 | ✅ 已落地 | [rules_adapter.py](./adapters/rules_adapter.py)：ruff/ESLint 子进程 → 统一 findings + 每条告警一条 Evidence（带 file/line/column/rule）；工具缺失/超时/禁用 → `degraded=true` 不抛错；`get_rea_snapshot(section="rules")` 现场采集。测试 7 passed（含真实 ruff F401、ESLint 输出注入、snapshot section、单工具开关） |
| T-F05 | ✅ 已落地 | [metrics_adapter.py](./adapters/metrics_adapter.py)：radon（cc/MI 数值）+ lizard（函数级 cc/length/params）+ vulture（≥80% 死代码）+ jscpd（本地 bin，缺失 degraded）；本机 radon/lizard/vulture 三工具可用，满足 G-F4「≥3 个可用」；`get_rea_snapshot(section="metrics")` 接入。测试 6 passed（含真实 radon/vulture、全工具缺失 FAIL-OPEN、jscpd report 注入、snapshot section） |
| T-F06 | ✅ 已落地 | [rules_engine.py](./core/rules_engine.py) 支持 `forbid_edge/forbid_cycle/threshold` 与 YAML 层/规则加载；[dsh_nodes.py](./dsh_nodes.py) 自动发现 `rea_rules.yaml`，违例 Evidence 前置避免 summary 裁剪，并在首次快照落盘前附加供下游消费。[test_t_f06_rules_engine.py](./tests/test_t_f06_rules_engine.py) 8 passed；相关 ruff 全绿 |
| T-F07 | ✅ 已落地 | [archaeology_adapter.py](./adapters/archaeology_adapter.py) 复用 `_run_git`，单次只读 `git log --relative --no-merges --name-only` 汇总 hotspot Top20、稀疏共变对、bus factor（覆盖≥50%提交的最少作者）与 90 天变更半径，无网络；非仓库返回 `degraded=true` + Evidence。`section=archaeology` 按 hotspot 分页。[test_t_f07_archaeology.py](./tests/test_t_f07_archaeology.py) RED 为适配器缺失与壳 enum 断言失败，GREEN 4 passed（真实 5 提交/3 作者 git 仓库、Top20、降级、快照）；l0_rea 15、gateway 15、核心 554 + reflection_loop 8 passed，ruff 全绿；同一 2 个 `/nonexistent` 写路径用例仍受沙箱限制 |
| T-F08 | ✅ 已落地 | [dependency_hygiene_adapter.py](./adapters/dependency_hygiene_adapter.py) 整合现有依赖清单解析、deptry DEP002、knip dependencies/devDependencies 与 OSV-Scanner，输出 `unused_dependencies/vulnerabilities/cves` 和确定性 CycloneDX 1.5 SBOM；固定 argv、`shell=False`、30s 上限且仅转发 PATH/NO_COLOR，`REA_OSV_ENABLED=0` 禁用联网，工具/网络/解析失败均 `degraded=true` 且保留 SBOM。`section=dependency_hygiene` 按未使用依赖分页，不新增工具。[test_t_f08_dependency_hygiene.py](./tests/test_t_f08_dependency_hygiene.py) RED 为适配器 ImportError 与壳 enum 断言失败，GREEN 5 passed；相关核心 21、l0_rea/gateway 各 15、核心 565 + reflection_loop 8 passed，ruff 全绿；真实 analyze→snapshot 冒烟生成 1 组件 SBOM，OSV 禁用且本机缺 deptry 时正确降级；同一 2 个 `/nonexistent` 写路径用例仍受沙箱限制 |
| T-F09 | ✅ 已落地 | [lsp_adapter.py](./adapters/lsp_adapter.py) 以隔离子进程运行 Jedi、pyright 与按项目复用的 tsserver，启动/请求超时 20s/5s、空闲 60s 回收，工具缺失或协议失败均 `degraded=true`；tsserver stdin 使用逐行 JSON、stdout 按 Content-Length 解帧，重入锁与帧格式有回归测试。可选 `lsp` 仅增强 `target_refs` 与 trace 种子，`section=diagnostics` 不新增工具且 engineer 白名单保持 10 个。[test_t_f09_lsp_adapter.py](./tests/test_t_f09_lsp_adapter.py) RED 覆盖适配器缺失、schema 缺字段、重入死锁与错误请求帧，GREEN 8 passed；真实 Jedi 对照解析率 0%→100%，真实 tsserver 返回 consumer.ts 引用及 TS2322，trace 种子与 analyze→diagnostics 均非降级；相关核心 18、l0_rea/gateway 合计 30、核心全量与 reflection_loop 8 passed，ruff 全绿；同一 2 个 `/nonexistent` 写路径用例仍受沙箱限制 |
| T-F10 | ✅ 已落地 | [sarif_adapter.py](./adapters/sarif_adapter.py) 将 `cognitive_debt`、ruff/ESLint findings、架构约束与 `known_gaps` 归一为 SARIF 2.1.0，含 gate→level、相对路径/行列映射与 Evidence dataclass 序列化；artifact 落盘 `reflection_data/sarif/<snapshot_id>.sarif`，`section=sarif` 支持分页与 8KB 预算。[test_t_f10_sarif_adapter.py](./tests/test_t_f10_sarif_adapter.py) 9 passed；OASIS 官方 schema 校验通过；全量回归 556 tests / 0 failures / 0 errors |
| T-F11 | ✅ 已落地 | [metrics_adapter.py](./adapters/metrics_adapter.py) 新增可选 `apply_metrics_policy`：JSON/YAML `thresholds` 支持 max_cc/avg_cc/dead_code/duplication_ratio，超阈值写 `gates.violations` 与 derivation Evidence；历史 metrics JSON 快照输出 current/previous/delta/direction，配置或历史缺失/损坏时 `degraded=true` 且不伪造趋势，未提供输入时原报告不变。[dsh_nodes.py](./dsh_nodes.py) 与 MCP schema 接入 `metrics_config/metrics_history`，不新增工具。[test_t_f11_metrics_gates.py](./tests/test_t_f11_metrics_gates.py) RED 为 `apply_metrics_policy` ImportError，壳 RED 为 `metrics_config` KeyError；GREEN 6 passed，T-F05+T-F11 12 passed，l0_rea/gateway 各 15 passed，核心 560 + reflection_loop 8 passed，ruff 全绿；同一 2 个 `/nonexistent` 写路径用例仍受沙箱限制 |
| T-F12 | ✅ 已落地 | [pack_builder.py](./core/pack_builder.py) 以快照为输入，按「文件 → 符号 → 依赖」生成确定性 Markdown，不复制自然语言 summary；完整文件块受 `budget_bytes` 限制，裁剪写 `trimmed.files`，`next_cursor/cursor` 可续页；Python 符号复用 PythonAnalyzer，TS 使用现有 components/stores。[test_t_f12_pack_builder.py](./tests/test_t_f12_pack_builder.py) RED 为 `ModuleNotFoundError: core.pack_builder`，GREEN 4 passed；壳 schema RED 后转绿，l0_rea 15 passed、gateway 15 passed、ruff 全绿；核心回归 550 + reflection_loop 8 passed，另 2 个既有 `/nonexistent` 写路径用例被当前沙箱策略拦截（非断言失败）；真实 Python analyze→pack 冒烟 2 文件 / 183B / 无裁剪 |
| T-F14 | ✅ 已落地 | [runtime_adapter.py](./adapters/runtime_adapter.py) 复用 coverage.xml 解析并支持 OTel JSON/JSONL（resourceSpans 或裸 span），输出零覆盖模块、归一化 span 与静态节点 `confirmed/contradicted/unobserved`；`contradicted` 仅表示报告中所有行 hits=0，不推断生产不可达，未观测不伪造数据。`section=runtime` 复用快照 modules、支持 `otel_path`、分页与 8KB `trimmed`，engineer 白名单仍 10 个。[test_t_f14_runtime_adapter.py](./tests/test_t_f14_runtime_adapter.py) RED 为适配器 ImportError、壳 enum 缺字段及损坏 coverage/游标边界失败，GREEN 8 passed；真实 `coverage run/xml` + OTel 双格式冒烟得到 confirmed/contradicted/unobserved，真实 stdio MCP 返回 coverage+otel confirmed；六项 P1 聚焦 35、l0_rea/gateway 各 15、核心 581 + reflection_loop 8 passed，变更范围 ruff 全绿；同一 2 个 `/nonexistent` 写路径用例仍受沙箱限制 |
| T-F19 | ✅ 已落地 | [server.py](../mcp_shells/l0_gateway/server.py) 仅对 engineer 的 `tools/list` 做目录投影：10 个白名单热工具保留调用语义完整的 compact schema，未来冷工具默认仅 `name/description/family`，`family` 显式展开完整 schema；8KB/4KB 预算按完整 JSON-RPC 响应裁剪并写 `trimmed`，`REA_CATALOG_HOT_ONLY=0` 恢复全量 schema，`tools/call` 路径不变。[test_l0_gateway_server.py](../mcp_shells/l0_gateway/test_l0_gateway_server.py) 新增 7 passed（含注册表副本注入冷工具、超预算与直调契约），gateway 15 passed、l0_rea 10 passed、ruff 全绿；真实 engineer 默认 5191B / 10 工具，回滚 6581B；33-REA 全量回归 556 tests / 0 failures / 0 errors |
| T-F20 | ✅ 已落地 | [server.py](../mcp_shells/l0_rea/server.py) 三个 submit 均支持 `deadline_ms`（默认 120000），新增 `cancel_rea_analyze/trace/compare`，直壳工具面 12 个、engineer 网关白名单仍 10 个；timeout/cancelled 均带 reason 且不产出 result，取消先持久化 `cancel_requested`，节点边界协作退出 `forced=false`，5s 未响应仅强制写 `cancelled + forced=true`，不强杀线程；`REA_DEADLINE_ENABLED=0` 忽略 deadline，cancel 仅置标记。[test_l0_rea_server.py](../mcp_shells/l0_rea/test_l0_rea_server.py) 新增 6 个聚焦用例通过（含工具面），l0_rea 15 passed、gateway 15 passed、ruff 全绿；真实 stdio 验证 timeout、协作取消、5.007s 强制取消；33-REA 核心全量回归 556 tests / 0 failures / 0 errors |
| P1 六项总回归 | ✅ 通过 | 聚焦 T-F07/T-F08/T-F09/T-F11/T-F12/T-F14：35 passed / 0 failed；33-REA 核心 `pytest tests -q --ignore=tests/test_reflection_loop.py` 581 passed + `pytest tests/test_reflection_loop.py` 10 passed = **591 passed / 0 failed / 0 errors**；`l0_rea` 15 passed、`l0_gateway` 15 passed；注册表 `✅ 10 存量壳 + 0 规划壳 / 54 active 工具 / 上限 80`；变更文件（六项 adapter/core + 6 个测试 + 两个壳 server）ruff `All checks passed`。拆跑原因：`tests/test_reflection_loop.py` 含 `/nonexistent` 写路径用例，整批运行会被当前沙箱整体拦截（非断言失败），与 T-F04/F07/F08/F09/F11/F12/F14 记录一致 |
| T-F13 受限图查询 DSL | ✅ 已完成 | `core/graph_query.py`：`section=graph` 支持 `nodes` / `edges` / `neighbors <node> [depth≤3]`，过滤白名单字段 + `=`/`~=`（无 eval、正则≤200 字符）；非法查询返回 `invalid_query`。`tests/test_t_f13_graph_query.py` 11 passed |
| T-F15 污点分析外挂 | ✅ 已完成 | `adapters/taint_adapter.py`：4 类 sink（command_exec / sql_exec / unsafe_deserialize / xss），同行 sanitizer 排除，source→sink 同行关联；Semgrep 仅在配置本地规则时子进程调用，否则内置扫描并 `degraded=true`；`section=taint` 独立输出，`section=sarif` 默认汇入（`include_taint`）。`tests/test_t_f15_taint.py` 5 passed |
| T-F17 增量索引 | ✅ 已完成 | `core/incremental_index.py`：文件级 `sha256(路径+内容)` Merkle、`added/modified/removed` 跨版本 diff 与 `invalidated_files`；索引缺失/损坏 FAIL-OPEN 按首次构建；`S33_rea_incremental_index` 节点 + `submit_rea_analyze{incremental:true}` 附加 diff（不改变分析结果）。`tests/test_t_f17_incremental_index.py` 5 passed |
| T-F18 Mermaid + 一页 wiki | ✅ 已完成 | `core/diagram.py`：`section=diagram` 输出按顶层目录分组的 Mermaid flowchart（节点≤40/边≤80，超限计入 known_gaps）与一页 Markdown（概览/枢纽/层级/Evidence 摘要/已知局限，超字节预算按行截断）；同输入逐字节一致，内核零 LLM。`tests/test_t_f18_diagram.py` 6 passed |
| T-F16 语义检索（复用检索系统） | ✅ 已完成（可选调用，默认关闭） | `adapters/semantic_adapter.py`：只连本机 Unix socket（`REA_SEMANTIC_SOCK`，默认 `/tmp/fis_vector_bridge.sock`）或本机命令（`REA_SEMANTIC_CMD`），不建 embedding、不访问网络；命中按 score 降序、同路径去重、分数夹紧 [0,1]，无路径命中丢弃并计 `known_gaps`；通道缺失/超时/响应损坏一律 `degraded=true`。新增 `get_rea_snapshot(section="semantic", query=...)` 与 MCP schema 枚举。`tests/test_t_f16_semantic.py` 10 passed；`l0_rea` 契约 15 passed；全量回归 669 + 10 = 679 passed / 0 failed / 0 errors；注册表 57 active / 上限 80；ruff 全绿。局限：未改 trace 排序（混合排序需 T-F03 基线支撑） |
| P2 四项总回归 | ✅ 通过 | 33-REA `632 passed`（核心，不含 reflection_loop）`+ 10 passed`（reflection_loop）= **642 passed / 0 failed / 0 errors**；`l0_rea` 15 passed、`l0_gateway` 15 passed；注册表 `✅ 10 存量壳 / 57 active 工具 / 上限 80`（每壳上限 15，engineer 白名单仍 10）；四项 + SPEC-E 六项变更范围 ruff `All checks passed`。新增 `section=graph` / `section=taint` / `section=diagram`，`section=sarif` 默认汇入污点 findings |

---

## §9 开放问题（需评审决策）

| # | 问题 | 建议 |
|---|---|---|
| Q1 | 新能力挂在哪里？engineer 已满 10 | 优先挂 `get_rea_snapshot` 的 section（metrics/rules/archaeology/sarif/pack）；确需独立工具时新建 `auditor` 角色（≤10，只读） |
| Q2 | 是否引入 networkx 做 PPR？ | 先手写 50 行 PPR（图规模 ≤5k 节点足够），避免新依赖；超过 5k 节点再评估 |
| Q3 | LSP 用 pyright 还是 jedi 兜底？ | 优先 pyright（与类型诊断同一进程）；jedi 仅作降级。需实测冷启动耗时后定 |
| Q4 | jscpd 需要 node/npx，云端是否允许 | 云端若不可用则仅本地启用，标记 degraded，不阻塞 CI |
| Q5 | SARIF 是否进 CI 门禁 | 第一阶段只产出不上门禁；等误报率 <10% 再考虑 |
| Q6 | 冷工具是否单独设 `auditor` 角色？ | 建议设：`auditor` = rea_metrics / rea_rules / rea_archaeology / rea_sarif / rea_pack + get_rea_snapshot + recall（≤10，只读），engineer 保持 10 不动 |
| Q7 | T-F14 的运行时观测源 | 本地优先 `coverage.py`（Python）/ 可选 OTel span 导入；不做线上埋点，避免把 REA 变成运行时可观测平台 |
| Q8 | deadline 默认值 120s 是否合适 | 当前 TS 大工程 analyze 0.82s、Python 1.62s，120s 有充足余量；大仓库以分析单元拆分而非放大 deadline |
