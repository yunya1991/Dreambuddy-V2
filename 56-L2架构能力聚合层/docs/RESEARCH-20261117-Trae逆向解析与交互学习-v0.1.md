# RESEARCH — 用 33-REA 拆解 Trae，并从交互中学习（v0.1）

> **日期**: 2026-11-17 ｜ **方法**: 33-REA（`l0.rea.mcp` 静态分析）+ 只读产物盘点 + 交互数据统计
> **目标**: 回答两件事——(1) 用 33-REA 能拆出 Trae 的什么；(2) 我们的交互数据能否转化为系统能力。
> **证据等级**（SPEC-33）: `observation` 可复算 ｜ `derivation` 由事实推导 ｜ `inference` 模式判断 ｜ `unknown` 未验证
> **定位**: 研究先行，不进入实现；结论供 56-L2 与 33-REA 的后续 SPEC 使用。
> **上游**: [SPEC-56](../SPEC-56-L2架构能力聚合层.md)、[TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md)、[REA-lobehub协议逆向解析-v0.1.md](./REA-lobehub协议逆向解析-v0.1.md)
> **下游**: Trae 逆向知识工厂（TKF）候选 SPEC、56 GAP 清单、33 训练案例库

---

## §0 结论（先看五条）

1. **Trae 能拆的不是「源码」，而是三类证据**：外壳产物（Electron/VS Code 分叉）、能力清单（agent/model/skill/plugin/MCP）、运行时产物（命令信封、git 快照、会话摘要）。核心 Agent 推理与原始对话落在加密库/远端，本地不可读——这是本轮最大的 `unknown`。
2. **最值得迁移的是五个「装配机制」，不是 UI 代码**：`agent_type × model → skill bundle`、`session × mode → tool_set 快照`、`command → sandbox envelope`、`session → checkpoint`、`session → summary memory`。这五个机制恰好对应 56 的 IF-7 四契约与 L2Envelope/span 缺口。
3. **33-REA 对 Trae 的适配度是「局部可用」**：Python 强、可读 TS 源码中、压缩 JS 弱、加密 DB 不可读。实测对 45MB 的 `ai-completion` 扩展只解析出 **5 文件 / 361 行 / 0 依赖边 / 0 模式**，不能直接当架构分析结论用。
4. **交互学习已有可用基线**：本地可读 **591 个会话摘要文件 / 4,895 条记录 / 1,018 条命令执行信封 / 19 个 git 快照**；足以做「意图→动作→结果→经验」的统计与案例化，但不足以做逐 token/逐工具调用的因果归因。
5. **建议走两源三线**：静态逆向线（外壳+清单）+ 运行时线（tool_set/命令/快照）+ 交互蒸馏线（摘要+执行+快照交叉验证），统一产出 **CapabilityCard / HarnessPattern / InteractionCase / GapCandidate** 四类对象，分别回灌 33 训练案例与 56 的能力/契约缺口。

---

## §1 目标与非目标

### 1.1 目标

| # | 目标 | 判据 |
|---|---|---|
| G1 | 还原 Trae 的 Agent Harness 结构 | 能画出「产品外壳 / 能力装配 / 数据平面」三层，并给出每层证据 |
| G2 | 找出可迁移机制 | 至少 5 个机制，每个都有本地路径证据 + 对应到 56 契约 |
| G3 | 评估 33-REA 适配度 | 明确「能用/不能用/需补什么」，附实测结果 |
| G4 | 建立交互学习基线 | 给出数据规模、指标定义、可提取模式与局限 |
| G5 | 给出下一步路线 | 研究→试点→SPEC 的阶段与门禁，不直接写实现 |

### 1.2 非目标（红线）

1. 不读取、不分析、不复制任何凭据类文件（token / cookie / 登录态）。
2. 不破解加密数据库，不做内存注入、不做运行时 hook。
3. 不执行目标程序，不分发 Trae 的代码、prompt 或资源。
4. 不把 `inference` 级结论写成 `observation`；`known_gaps` 原样保留。
5. 不把交互摘要中的模型自述当作 ground truth——必须与命令信封/快照交叉验证。

---

## §2 证据地图（observation）

### 2.1 静态证据

| 证据源 | 路径 | 规模 | 能回答什么 |
|---|---|---|---|
| 应用外壳 | `/Applications/Trae CN.app` | 1.4 GB；版本 `1.107.1` | 产品形态、内置扩展、主进程入口 |
| 工作台 bundle | `.../app/out/vs/workbench/workbench.desktop.main.js` | 16 MB（另有 solo-lite 11 MB） | 原生 chat 工具框架、`runSubagent` 等工具引用 |
| 内置扩展 | `.../app/extensions/` | 111 个目录 | 语言增强、AI 补全、Git AI、内置 MCP、IM 桥 |
| Agent Manifest | `~/.trae-cn/builtin/baseline/manifests/*.json` | `global` 8 skills；`trae`/`code`/`work`/`design` 四类 agent | `agent_type × model → skills` 的装配表 |
| 用户技能 | `~/.trae-cn/skills/` | 82 个技能目录 | 技能格式（SKILL.md + frontmatter）与用户扩展面 |
| 插件 | `~/.trae-cn/plugins/trae-remote-official/` | 9 个插件 | `plugin.json` / `.mcp.json` / `connector.json` 三件套 |
| 插件索引 | `~/.trae-cn/installed-plugins.json` | 9 条 | 插件来源、版本、安装路径 |

### 2.2 运行时证据

| 证据源 | 路径 | 规模 | 能回答什么 |
|---|---|---|---|
| 会话工具面 | `~/.trae-cn/mcps/<session>/<mode>/<server>/tools/*.json` | 25 个会话、10 种 mode、8 个 server、每 mode 16–37 个工具 | **按会话+agent mode 物化的 tool_set 快照** |
| 内置工具面 | 同上 `integrated_*` | browser 20 / code_mode 1（Exec）/ default 4 | 内置能力与外部 MCP 的分层 |
| 命令执行信封 | `~/Library/Application Support/Trae CN/ModularData/ai-agent/command-execution/*/execution.json` | 1,018 条 | 沙箱、退出码、耗时、cwd、终止原因 |
| 会话快照 | `.../ai-agent/snapshot/<session>/v2/.git` | 19 个 git 仓库 | 每会话可回放的检查点 |
| 工作模式产物 | `.../ai-agent/work-mode-projects/` | 16 个项目目录 | 产物型任务的真实输出（pptx/pdf/xlsx/脚本） |
| 加密数据库 | `.../ai-agent/database.db` | 6.88 GB；文件头非 SQLite | 原始消息/工具调用（**不可读**） |

### 2.3 交互证据

| 证据源 | 路径 | 规模 | 字段 |
|---|---|---|---|
| 会话摘要 | `~/.trae-cn/memory/projects/<project>/2*/session_memory_*.jsonl` | **591 文件 / 4,895 条记录**（2026-08-07 → 2026-11-17） | `intent` / `actions[]` / `outcome` / `learned[]` / `message_summary_time` |
| 项目记忆 | 同目录 `project_memory.md` | 硬约束/工程惯例/经验教训 | 长期规则与教训 |
| 日志 | `~/Library/Application Support/Trae CN/logs/` | aha / networkservice 日志 | 运行态线索（本轮未深挖） |

> `observation`：上述路径与规模均可复算；`learned` 是模型生成的摘要，属于 `inference`，不是原始事实。

---

## §3 Trae 架构还原（三层 + 五机制）

### 3.1 三层结构

```text
A. 产品外壳（VS Code 分叉 + Electron）
   workbench.desktop.main.js / solo-lite / extensions / iCubeFloatingChat
        ↓
B. Agent Harness（能力装配与执行）
   agent_type(trae/code/work/design) × model → skills
   session × mode(solo_agent_lite/solo_work_lite/Explore/Plan/...) → tool_set
   command → sandbox envelope；session → git checkpoint
        ↓
C. 数据平面（可审计产物）
   command-execution / snapshot / work-mode-projects / memory summaries / encrypted DB
```

### 3.2 五个可迁移机制（本轮核心产出）

| # | 机制 | 观察到的形态 | 对应 56 契约/缺口 | 迁移价值 |
|---|---|---|---|---|
| **M1** | `agent_type × model → skill bundle` | `manifests/trae.json`：`trae` 6 个 model profile，每个 1–7 个 skills；`work` 10 个 profile，每个 1–14 个 skills | 能力聚合/路由；L2 的 capability catalog | 按模型能力裁剪技能面，而不是全局暴露 |
| **M2** | `session × mode → tool_set` | `mcps/<session>/<mode>/` 下物化工具 JSON；`solo_agent_lite` 37 个、`Explore/Plan` 16 个 | IF-7 `tool_set.schema.json`；G-L2-11 | 工具可见性来自同一次快照，可审计、可回放 |
| **M3** | `command → sandbox envelope` | `execution.json` 含 `ownerHash` / `requestDigest` / `target=sandbox` / `status` / `exitCode` / `terminalReason` / `sandbox.restrictedFiles/Networks` | L2Envelope trace / span；回归证据 | 每条命令都是可验证证据，不靠「人工确认」 |
| **M4** | `session → checkpoint` | `snapshot/<session>/v2/.git`，19 个仓库 | Ticket 可续 / 回滚；ADR-10 可逆性 | 断点续跑与变更回溯的物理载体 |
| **M5** | `session → summary memory` | `intent / actions / outcome / learned`，4,895 条 | G 层四分流；33 训练案例 | 把交互压缩成可检索的经验，而不是原始对话 |

### 3.3 内置工具与外部 MCP 分离（observation）

- 内置 MCP 物化面：`integrated_browser` 20 个、`integrated_code_mode` 1 个（`Exec`）、`integrated_default` 4 个（`GenerateImage/Video`、`Schedule`、`RequestAuthorization`）。
- 原生 chat 工具（如 `runSubagent`）在 workbench bundle 中，属于进程内工具，不物化到 `mcps/`。
- `derivation`：Trae 的「能力面」= 原生工具（进程内）+ 内置 MCP（物化）+ 用户 MCP（物化）+ 插件技能（manifest）四层叠加；审计只能看到后三层，第一层是 `unknown`。

### 3.4 权限与沙箱（observation）

- `~/.trae-cn/permission/global.json`：`activeProfileId = manual_approval`，`filesystem.readWrite` 白名单。
- `~/.trae-cn/sandbox.json`：默认网络 `allow`，文件读写仅 `~/.dsh` 等目录。
- 1,018 条命令全部 `target=sandbox`；`sandbox.outcome=completed`，并记录 `restrictedFiles/Networks`。
- `inference`：这是「人工审批 + 沙箱执行 + 信封留痕」的三段式；与 56 的 G-L2-2（授权）/G-L2-8（回归）同构。

### 3.5 仍然未知（必须保留）

1. 模型侧 Agent loop 的停止原因、最大步数、上下文压缩策略——不在本地 bundle 的明文里。
2. 原始用户 prompt 与逐工具调用参数——在加密 DB 中，本轮不可读。
3. `learned` 字段的生成 prompt 与质量门控——只有结果，没有生成过程。
4. 原生 chat 工具的完整清单与权限——只能从 bundle 字符串间接推断。

---

## §4 33-REA 适配度评估

### 4.1 实测（observation）

对 `/Applications/Trae CN.app/Contents/Resources/app/extensions/ai-completion`（45 MB，5 个 `.js` bundle）执行 `submit_rea_analyze(scope=summary)`：

| 指标 | 结果 |
|---|---|
| 识别语言 | `typescript` |
| 文件 / 行数 | **5 / 361** |
| 依赖节点 / 边 / 环 | **5 / 0 / 0** |
| 组件 / store / 路由 | 0 / 0 / 0 |
| 模式 | 0 |
| Evidence | 8 条（observation 3 / derivation 3 / inference 2） |
| snapshot_id | `ce14ca01ee0d0670` |
| known_gaps | 13 条（压缩产物、动态 import、运行时注入、组件启发式等） |

> 结论：REA 把 3.6 MB 的压缩 `extension.js` 当成「361 行 TS」解析，**结构结论不可用**。这不是 REA 的缺陷，而是目标形态超出其设计边界（源码 AST vs 压缩 bundle）。

### 4.2 能力矩阵

| REA 能力 | 对 Trae 可用性 | 说明 |
|---|---|---|
| PythonAnalyzer | ❌ | Trae 无 Python 主体 |
| TSAnalyzer / TSProjectAnalyzer | 🟡 局部 | 仅对未压缩 `.ts/.js` 有效；压缩 bundle 失效 |
| DependencyGraph / CallChainTracer | 🟡 局部 | 依赖可解析源码；压缩后无法建图 |
| GitHistory | ✅ | 19 个会话快照是标准 git 仓库；应用本体无 `.git` |
| ArchitecturePatternDetector | 🟡 | 对目录/命名有效；对 manifest/物化工具面无效 |
| DesignDecisionRecovery | 🟡 | 只能从「多套实现/兼容层/TODO」推断，不能读 prompt |
| MethodologyAbstraction | ✅ | 适合把 M1–M5 聚类为通用方法论 |
| AIRAudit / PoE | ✅ | 适合给交互案例打证据分与门禁 |
| Reflection / TrainingCases | ✅ | 适合把 InteractionCase 转为训练案例 |
| REA MCP（异步） | ✅ | `submit/poll` 可用；但对加密/压缩目标要降级使用 |

### 4.3 结论

**REA 应作为「证据引擎」而不是「采集器」**：

- 采集层需要新增三个 miner：`bundle_miner`（压缩 JS 字符串/模块边界）、`manifest_miner`（manifest/plugin/MCP tool schema）、`interaction_miner`（memory jsonl + execution envelope + snapshot）。
- REA 负责：证据分级、依赖/调用图（可解析部分）、模式识别、方法论抽象、PoE 审计、训练案例化。
- 对不可读目标，REA 只输出 `unknown`，不得用「0 边/0 模式」冒充「无依赖/无模式」。

---

## §5 交互学习基线（observation + derivation）

### 5.1 数据规模

| 指标 | 数值 |
|---|---|
| 会话摘要文件 | **591** |
| 摘要记录 | **4,895** |
| 时间范围 | 2026-08-07 → 2026-11-17 |
| 平均 actions / 条 | **4.37** |
| 平均 learned / 条 | **3.96** |
| 无 learned 的记录 | 22（0.45%） |
| 命令执行信封 | **1,018**（exited 1,007 / stopped 6 / running 5） |
| 命令耗时 | median **5.86 s**；p90 **26.76 s**；max **1,148.5 s** |
| 会话 git 快照 | **19** |

### 5.2 交互分布（observation）

- 命令 cwd Top5：仓库根 693、`3.1-FRONTEND` 94、`54-L1` 64、`1-ARCHITECTURE` 60、`56-L2` 31。
- `learned` 高频词（粗分词）：问题、采用、数据、方案、状态、导致、字段、机制、路径、逻辑、调用、模式、现有、策略、自进化、本地、错误、模块、缺少。
- `derivation`：交互重心在「架构/契约/数据链路/自进化」，与 54/56 的近期工作一致；「缺少/未实现/需要」类词可作为能力缺口候选。

### 5.3 可提取的四类交互模式

| 模式 | 输入字段 | 可算指标 | 用途 |
|---|---|---|---|
| P1 任务序列 | `intent → actions[]` | 动作数、动作类型分布、重复动作率 | 识别高频工作流，沉淀 SKILL/模板 |
| P2 工具效率 | `actions` + `execution.json` | 命令数/意图、长命令占比、stopped 率、重试率 | 优化工具面与默认命令 |
| P3 失败-修复 | `learned[]` + `outcome` | 失败关键词、根因类别、修复动作 | 训练案例负样本、bugfix 模板 |
| P4 能力缺口 | `learned` 中「缺少/未实现/需要」 | 缺口频次、所属模块、证据 | 直接喂给 56 GAP 清单与 L1 发现 |

### 5.4 局限（必须写进任何结论）

1. **摘要非原始对话**：`intent/actions/learned` 是模型压缩结果，存在遗漏与自我合理化；只能作 `inference`，需与命令信封/快照交叉验证。
2. **无 token/工具调用 ID**：无法精确归因「哪次工具调用导致哪次失败」。
3. **DB 加密**：原始 prompt、工具参数、模型响应不可读；不能声称覆盖全部交互。
4. **幸存者偏差**：只记录被摘要的会话；未摘要/失败会话可能缺失。
5. **隐私**：摘要含用户路径、项目名与业务信息，任何外部分享必须先脱敏。

---

## §6 建议方案：Trae 逆向知识工厂（TKF）

### 6.1 两源三线

```text
静态线  ── app bundle / extensions / manifests / skills / plugins
运行时线 ── mcps tool_set / command-execution / snapshot / work-mode-projects
交互线  ── session_memory jsonl / project_memory / logs
                    ↓
         归一化四对象（Evidence-First）
                    ↓
   ┌────────────────┴─────────────────┐
   33 训练案例库                 56 能力/契约缺口
```

### 6.2 四个规范化对象（草案，不是最终 schema）

| 对象 | 关键字段 | 证据要求 |
|---|---|---|
| `CapabilityCard` | `id, kind(tool/skill/plugin/mode), source_path, agent_type, model, tools[], evidence[]` | 每条能力至少 1 条 `observation` |
| `HarnessPattern` | `id(M1–M5), observed, contract_ref, gap, confidence` | 机制形态可复算；`inference` 标注 |
| `InteractionCase` | `case_id, intent, actions[], tools[], outcome, learned[], metrics, evidence_refs[]` | 摘要 + 至少 1 条命令/快照交叉证据 |
| `GapCandidate` | `gap_id, layer, contract_ref, severity, proposed_check` | 缺口必须能映射到 56 的 GAP/门禁 |

### 6.3 回灌路径

1. **33 训练案例**：`InteractionCase` → `training_cases`，正样本=成功闭环，负样本=stopped/失败/返工；质量门控沿用「无证据引用不入库」。
2. **56 GAP 清单**：M1–M5 对照现有 GAP-17~30，新增「能力装配/工具面快照/命令信封/检查点/摘要记忆」五类缺口。
3. **47 注册表**：把 `tool_set` 快照与 `stop_reason` 契约用于 L2 壳的工具面审计。
4. **56 TECHNICAL_DESIGN**：只登记「已验证的机制」，不把 Trae 的内部实现写成我们的实现。

### 6.4 与 52 蒸馏桥的区别

| 维度 | 52 蒸馏桥 | TKF（本提案） |
|---|---|---|
| 蒸馏对象 | 交易信号/提案/门禁结果 | Harness 机制 + 交互策略 |
| 数据源 | trace/outbox/bridge cursor | 会话摘要/命令信封/快照/manifest |
| 产物 | 认知/案例/信号 | 能力卡/机制卡/交互案例/缺口 |
| 风险 | 信号污染 | 交互摘要偏差、隐私、法律边界 |

---

## §7 路线（研究 → 试点 → SPEC）

| 阶段 | 内容 | 产出 | 门禁 | 状态 |
|---|---|---|---|---|
| **R0** | 本报告：证据地图 + 五机制 + REA 适配度 + 交互基线 | 本文 | 结论均有路径/数字 | ✅ |
| **R1** | 机制卡抽取：M1–M5 各 1 张，附路径与样例 | 5 张 `HarnessPattern` | 每张至少 2 条 observation | ✅（M4 证据较薄，见 §7.1） |
| **R2** | 交互试点：50 个会话，抽 P1–P4，算指标 | `InteractionCase` schema + 试点报告 | 至少 30% 案例有命令/快照交叉证据 | 🟡 摘要级完成；**交叉证据门禁未满足** |
| **R3** | 差距映射：M1–M5 × 56 GAP/门禁 | `GapCandidate` 清单 | 每条缺口有 contract_ref | ✅（5 个候选，未合并官方 GAP 表） |
| **R4** | SPEC：TKF v0.1（采集/归一化/回灌/门禁/隐私） | SPEC 草案 | 评审通过才进入实现 | ⬜ |
| **R5** | 实现（可选）：miner + 校验器 + 试点 | 代码 + 测试 | TDD + 对照实验 | 🟡 miner 已落，校验器待建 |

### 7.1 R1/R2 试点产出（2026-11-17）

**代码**（33-REA 新增采集前置层）：

- [trae/](../../33-REA逆向解析工程/trae/)：`bundle_miner.py` / `manifest_miner.py` / `interaction_miner.py` / `run_pilot.py`
- 测试：[test_trae_miners.py](../../33-REA逆向解析工程/tests/test_trae_miners.py)，8 项通过（本地只读）
- 运行：`PYTHONPATH=33-REA逆向解析工程 python3 -m trae.run_pilot --out reports/trae-20261117 --sessions 50`

**产物**：

| 产物 | 路径 | 内容 |
|---|---|---|
| 机制卡 | [mechanism_cards.md](../../33-REA逆向解析工程/reports/trae-20261117/mechanism_cards.md) | M1–M5 + bundle 取证 |
| 试点报告 | [pilot_report.md](../../33-REA逆向解析工程/reports/trae-20261117/pilot_report.md) | 数据、动作分布、缺口主题、局限 |
| 交互案例 | [interaction_cases.jsonl](../../33-REA逆向解析工程/reports/trae-20261117/interaction_cases.jsonl) | 627 条 `InteractionCase` |
| 能力清单 | [manifest.json](../../33-REA逆向解析工程/reports/trae-20261117/manifest.json) | agent/model/skill/plugin/MCP 面 |
| Bundle 取证 | [bundle.json](../../33-REA逆向解析工程/reports/trae-20261117/bundle.json) | 3 个 bundle 的字符串级 observation |
| 汇总指标 | [interaction_summary.json](../../33-REA逆向解析工程/reports/trae-20261117/interaction_summary.json) | 会话/命令/快照指标 |
| 证据包 | [evidence.json](../../33-REA逆向解析工程/reports/trae-20261117/evidence.json) | 三线证据与 known_gaps |
| R3 差距映射 | [gap_mapping.md](../../33-REA逆向解析工程/reports/trae-20261117/gap_mapping.md) | M1–M5 × 56 GAP/门禁矩阵 |
| R3 候选缺口 | [gap_candidates.json](../../33-REA逆向解析工程/reports/trae-20261117/gap_candidates.json) | 5 个 `GAP-T*` 候选 + contract_ref |

**关键数字（快照，随运行变化）**：

| 指标 | 值 |
|---|---|
| M1 agent/model | `trae` 6 / `code` 6 / `design` 4 / `work` 10；skills 1–14 |
| M2 会话/mode/tool | 25 会话 / 10 mode / 每 mode 16–37 工具 |
| M3 命令信封 | 1,006 条；exited 997 / stopped 6 / running 2；median 5.09 s / p90 27.39 s / max 1,148.5 s |
| M4 快照 | 19 个，均为 git 仓库 |
| M5 交互 | 50 会话 / 627 记录；动作条目 edit 816 / test 598 / read 322 / run 279 / doc 248 |
| 缺口主题 | 数据/检索 34、部署/云端 26、前端/接口 15、路由/分层 14、门禁/验收 13、MCP/工具 10、trace/观测 5 |
| Bundle | toolId 候选 2 个（`runSubagent` / `ReplyUser`），无结构结论 |

**R2 门禁未满足的原因**：命令信封没有 `session_id`/`trace_id`，无法把命令归因到具体会话；当前 627 条案例全部是摘要级 `inference`。这不是 miner 的缺陷，而是数据源缺字段。下一步要么给信封补 ID，要么只把「缺口主题」作为 L1 发现线索，不声称因果。

**R3 差距映射结果（5 个候选，状态 `candidate`）**：

| 候选 | 机制 | 现有 GAP | 契约 | 优先级 | 判定 |
|---|---|---|---|---|---|
| GAP-T1 | M1 | GAP-02/13/19 | IF-1 / IF-7 | P1 | 部分覆盖，缺 `capability_bundle_id`/`model_profile` |
| GAP-T2 | M2 | GAP-19/23/25 | IF-7 / G-L2-11 | P1 | 契约已有，缺会话级 hash/diff 审计 |
| **GAP-T3** | M3 | GAP-01/24/30 | IF-3 / IF-7 / G-L2-8 | **P1** | **唯一硬证据阻塞项：join_rate=0%** |
| GAP-T4 | M4 | GAP-20/24 | IF-4 / ADR-10 | P2 | 未覆盖，缺 checkpoint 契约 |
| GAP-T5 | M5 | GAP-15/29 | IF-5 / ADR-06 / G-L2-5/7 | P1 | 缺证据门控与训练接线 |

推荐顺序：**T3 → T5 → T1 → T2 → T4**。其中 T1/T2/T4 可能已被 A1-2/A1-3/Ticket 部分实现，推广前必须代码复核，避免重复开缺口；`GAP-T*` 尚未合并进 56 官方 GAP-31+。

---


## §8 风险与红线

| # | 风险 | 处置 |
|---|---|---|
| R1 | 法律/ToS：逆向产品可能违反许可 | 只做本地只读互操作性研究；不分发代码/prompt；不绕过保护 |
| R2 | 凭据泄漏 | token/cookie/登录态一律不读；路径不写入报告 |
| R3 | 加密库误判 | DB 标 `unknown`；不用「查不到」推导「不存在」 |
| R4 | 压缩 bundle 误判 | 只输出字符串/模块边界级 observation；结构结论标 inference |
| R5 | 摘要偏差 | 与命令信封/快照交叉验证；无交叉证据的案例降级为 inference |
| R6 | 隐私 | 报告中路径/项目名脱敏；训练案例只保留模式，不保留业务数据 |

---

## §9 待决策（进入 R1 前）

| # | 决策点 | 选项 | 建议 |
|---|---|---|---|
| D1 | 拆解范围 | A 只 Trae IDE；B 只 SOLO/Work 模式；C 两者 | **C**：外壳与 Harness 分开取证，避免混淆 |
| D2 | 交互学习深度 | A 摘要级；B 摘要+命令+快照；C 自建 trace | **B**：现有数据可支撑；C 需改运行时，暂不做 |
| D3 | 交付形态 | A 仅本报告；B 报告+R1/R2 试点；C 直接 SPEC | **B（已执行）**：R1/R2 试点已产出，R2 交叉证据门禁未满足 |
| D4 | 是否登记 | A 仅 56 docs；B 同步 INDEX；C 同步 56 GAP | **B 已完成；C 待评审**：报告已入 INDEX，`GAP-T*` 候选已产出但未并入官方 GAP-31+ |

---

## §10 复跑命令（便于复核）

```bash
# 1) REA 实测（MCP 异步）
# submit_rea_analyze(target="/Applications/Trae CN.app/Contents/Resources/app/extensions/ai-completion", scope="summary")
# poll_rea_analyze(job_id="job-a40e01f401e0")  # snapshot_id=ce14ca01ee0d0670

# 2) 交互摘要统计
python3 - <<'PY'
import json,glob,os,collections,statistics
root=os.path.expanduser('~/.trae-cn/memory/projects/<project>')
files=glob.glob(root+'/2*/session_memory_*.jsonl')
recs=[json.loads(l) for f in files for l in open(f,encoding='utf-8') if l.strip()]
print(len(files),len(recs),statistics.mean(len(r.get('actions',[])) for r in recs))
PY

# 3) 命令信封统计
python3 - <<'PY'
import json,glob,os,collections
fs=glob.glob(os.path.expanduser('~/Library/Application Support/Trae CN/ModularData/ai-agent/command-execution/*/execution.json'))
print(len(fs),collections.Counter(json.load(open(f)).get('status') for f in fs))
PY
```

---

## §11 版本

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-11-17 | 首版：证据地图、五机制、REA 适配度、交互基线、TKF 提案、R0–R5 路线 |
| v0.1.1 | 2026-11-17 | 落地 R1/R2：三个 miner + 8 项测试 + 5 张机制卡 + 627 条交互案例；R2 交叉证据门禁未满足 |
| v0.1.2 | 2026-11-17 | 落地 R3：`gap_mapper.py` + 5 个 `GAP-T*` 候选 + 映射矩阵；推荐顺序 T3→T5→T1→T2→T4 |
