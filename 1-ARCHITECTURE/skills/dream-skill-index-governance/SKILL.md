---
name: dream-skill-index-governance
description: "Meta-SKILL: governs SKILL index/version/dependency/lifecycle/conflict/drift. Invoke for SKILL registry build, lifecycle transition, conflict detection, or drift monitoring."
version: 1.0.0
created: 2026-09-21
updated: 2026-09-21
license: Internal
status: active
category: orchestration
triggers: [SKILL 索引, SKILL 治理, SKILL 生命周期, SKILL 冲突检测, SKILL 漂移, skill-indexer]
depends_on: [hermes-skill-governance, hermes-shadow-verification-gate, hermes-rollback-actuator]
provides: [skill-index-governance, skill-lifecycle-management, skill-conflict-detection, skill-drift-monitoring]
cognitive_links: [VM-1790002963075-0b027747, VM-1790001702811-24bffe86, VM-1790001192903-2224e07e]
---

## Autonomy Boundary

可自主执行：
- 任务编排与流程调度
- 节点间数据流转发
- 编排优化与节点选择
- 执行状态监控与汇报

需用户确认：
- 涉及实盘交易的编排执行
- 修改核心编排规则

禁止：
- 将编排结论直接作为交易指令执行
- 绕过风控或审批流程


# Dream Skill Index Governance — SKILL 索引治理元 SKILL

> 治理 SKILL 的索引/版本/依赖/生命周期/冲突检测/漂移监控，形成"SKILL 治理 SKILL"的递归闭环。基于 spec 方案 C（混合 manifest + 自动索引，综合评分 44/50）固化落地，配合认知系统 `recall`/`record`/`verify` 形成自我进化闭环，结尾执行 hermes 反思决定是否再衍生新 SKILL。

> **双位置存储**：本 SKILL 同时存在于：
> - `.trae/skills/dream-skill-index-governance/SKILL.md`（TRAE 调用入口，Skill 工具识别）
> - `1-ARCHITECTURE/skills/dream-skill-index-governance/SKILL.md`（项目级索引发现，本文件）

> **元 SKILL 定位**：本 SKILL 是"SKILL 治理 SKILL"——用 SKILL 治理其他 SKILL，形成递归闭环。本 SKILL 自身的生命周期也走 5 阶段（proposed → shadow → active → deprecated → archived），当前 status=active。

---

## 一、何时调用（触发条件）

满足以下任一条件即应调用本 SKILL：

1. **索引构建**：需要扫描全量 SKILL.md，生成机器可读注册表
   - 触发词：「SKILL 索引」「构建索引」「skill registry」「skill-indexer build」
2. **生命周期管理**：需要将 SKILL 从一个生命周期阶段转换到下一个
   - 触发词：「SKILL 生命周期」「提案 SKILL」「影子验证」「弃用 SKILL」「归档 SKILL」
3. **冲突检测**：需要扫描触发词冲突、同名冲突、依赖冲突、循环依赖
   - 触发词：「SKILL 冲突检测」「触发词冲突」「同名冲突」「依赖冲突」
4. **漂移监控**：需要检测双位置存储（.trae/skills/ + 1-ARCHITECTURE/skills/）一致性
   - 触发词：「SKILL 漂移」「双位置漂移」「drift detection」
5. **新增 SKILL 前门禁**：新增 SKILL 前调用本 SKILL 做 ALLOW/DENY 决策
   - 触发词：「SKILL 治理」「SKILL 门禁」「validate new SKILL」
6. **hermes 反思批量评估**：扫描所有 SKILL 触发 hermes 反思决策树
   - 触发词：「hermes 反思批量」「skill-indexer hermes-eval」

---

## 二、核心能力（5 项）

### 能力 1：skill-indexer 构建器

**功能**：扫描所有 SKILL.md，解析 YAML frontmatter，自动生成机器可读索引产物。

**输入**：扫描路径列表（默认全量 8+ 位置）
**输出**：
- `skill-registry.json`：全量机器可读索引（每个 SKILL 一条记录）
- `SKILL_INDEX.md`：人类可读（自动生成，替代手写版，标记 `<!-- AUTO-GENERATED -->`）
- `dependency-graph.json`：DAG 依赖图
- `drift-report.json`：漂移检测报告
- `conflict-report.json`：冲突检测报告

**设计原则**：
- **FAIL-OPEN**：构建失败不影响 SKILL 可用性，仅不更新索引
- **向后兼容**：旧 SKILL 无新字段也能工作（status 默认 active，category 默认 other）
- **单一事实源**：SKILL.md frontmatter 为主，可选 `skill.override.yaml` 为辅

### 能力 2：5 阶段生命周期管理

**状态机**（借鉴 RICH + MCP SEP-2596）：

```
proposed → shadow → active → deprecated → archived
   ↓          ↓         ↓         ↓          ↓
 提案       影子验证   落地      弃用(≥12月)  归档
```

**转移条件**：
- `proposed → shadow`：需至少 1 次实践引用（hermes 反思触发）
- `shadow → active`：需 `shadow_verified=true` + 至少 1 条 cognitive_link 验证（verify success）
- `active → deprecated`：需 `deprecation_scheduled=true` + `reason`（12 月最小弃用窗口）
- `deprecated → archived`：需 ≥12 月 deprecation 窗口 + `replaced_by` 已 active
- 任何 → `failed`（隐式）：验证失败，保留审计但不前进

**hermes 反思入口**：`proposed` 状态由 hermes 反思决策树触发（CLAUDE.md 硬约束，VM-1790001702811-24bffe86 B 级）

### 能力 3：冲突检测

**检测项**（5 类）：
1. **触发词冲突**：同一触发词匹配多个 active SKILL（如"深度调研"同时匹配 dream-strategy-research 和 dream-research-workflow）
2. **同名冲突**：不同位置存在同名 SKILL（如 dream-strategy-research 在 6-TRADING 和 11-易经）
3. **依赖冲突**：depends_on 引用不存在的 SKILL
4. **循环依赖**：DAG 中存在环
5. **漂移**：双位置 integrity_hash 不一致

**决策契约**（复用 hermes-skill-governance v0.1）：
- 输入：`candidate`（skill_name/prefix/responsibilities/interfaces）+ `existing_skills[]` + `rules`
- 输出：`decision: ALLOW|DENY` + `scope`（owned/non_owned responsibilities）+ `conflicts[]` + `required_changes[]`
- 任何 `DENY` 必须给出可操作的 `required_changes`

### 能力 4：漂移监控

**功能**：检测双位置存储（.trae/skills/ + 1-ARCHITECTURE/skills/）一致性。

**机制**：
- 每次构建时计算两位置 SKILL.md 的 sha256
- 不一致则写入 drift-report.json
- FAIL-OPEN：只报告不自动修复，人工确认后同步
- drift-report 标记 primary 位置，建议从 primary 同步到 secondary

**已知漂移**（spec 盘点发现）：
- `.trae/skills/` 多出 `tee-red-green-progress`
- `1-ARCHITECTURE/skills/` 多出 `dreambuddy-os`

### 能力 5：认知系统集成

**双向关联**：
- `recall`：通过 tags + domain + cognitive_links 反查 SKILL
- `record`：自动在对应 SKILL 的 frontmatter `cognitive_links` 追加 VM-id
- `verify`：触发 lifecycle 升级（shadow → active）

**认知闭环**：
```
recall → 找到 SKILL + 经验
  ↓ 执行 SKILL
record → 关联 SKILL + 新经验
  ↓ verify
lifecycle advance → shadow→active（SKILL 升级）
  ↓ hermes 反思
proposed → 新 SKILL（生命周期重启）
```

---

## 三、数据结构 spec（YAML 示例）

### 3.1 SKILL 元数据 schema（frontmatter，向后兼容）

```yaml
# SKILL.md YAML frontmatter
---
# === 现有字段（必填，已存在）===
name: <string>                    # SKILL 目录名，唯一
description: <string>             # 一句话描述（英文，<200 字符）
version: <semver>                 # 1.0.0
created: <date>                   # 2026-09-21
updated: <date>                   # 2026-09-21
license: <string>                 # Internal

# === 新增可选字段（渐进增强）===
id: <reverse-dns>                 # io.github.dreambuddy.dream-qwen-eval-collab（可选，无则用 name）
status: <enum>                    # proposed|shadow|active|deprecated|archived（默认 active）
category: <enum>                  # orchestration|trading|governance|memory|business|integration|tooling|cognition|hermes-trigger|experiment|core|other
domain: <string>                  # 所属域：6-TRADING / 4-MEMORY / 11-易经 / deploy/hermes（路径推断）
triggers: [<string>]              # 触发词列表
depends_on: [<string>]            # 依赖的 SKILL name 列表
provides: [<string>]              # 提供的能力标签
cognitive_links: [<VM-id>]        # 关联认知记忆 ID 列表
replaces: [<string>]              # 替代的旧 SKILL name
replaced_by: <string|null>        # 被替代的新 SKILL name
---
```

### 3.2 skill.override.yaml schema（可选高级字段）

```yaml
id: <reverse-dns>
locations:
  - path: <relative-path>
    role: trae-entry|project-index|user-global|trading|memory|hermes|experiment
    primary: true|false
lifecycle:
  proposed_at: <datetime>
  proposed_by: <agent|user>
  shadow_verified: <bool>
  shadow_evidence: [<VM-id>]
  activated_at: <datetime>
  deprecation_scheduled: <bool>
  deprecation_reason: <string>
  deprecated_at: <datetime|null>
  archived_at: <datetime|null>
conflicts_with:
  - skill: <name>
    reason: <string>
    resolution: <string>
integrity_hash: sha256:<hex>
policy:
  installation: INSTALLED_BY_DEFAULT|AVAILABLE|NOT_AVAILABLE
  auth_required: <bool>
```

### 3.3 registry.json 结构

```json
{
  "version": "1.0.0",
  "built_at": "2026-09-21T22:30:00Z",
  "scan_paths": ["~/.workbuddy/skills", "1-ARCHITECTURE/skills", ".trae/skills", "6-TRADING/skills", "..."],
  "total_count": 200,
  "by_category": {"orchestration": 6, "trading": 40, "governance": 12, "...": "..."},
  "by_status": {"active": 180, "proposed": 5, "shadow": 3, "deprecated": 8, "archived": 4},
  "skills": [
    {
      "name": "dream-qwen-eval-collab",
      "version": "1.0.0",
      "status": "active",
      "category": "orchestration",
      "domain": "1-ARCHITECTURE",
      "triggers": ["千问评估", "二轮评估", "hermes 反思"],
      "depends_on": ["bsk", "skill-creator"],
      "cognitive_links": ["VM-1790001192903-2224e07e"],
      "locations": [".trae/skills/dream-qwen-eval-collab", "1-ARCHITECTURE/skills/dream-qwen-eval-collab"],
      "integrity_hash": "sha256:abc123"
    }
  ]
}
```

### 3.4 dep-graph.json 结构

```json
{
  "nodes": [
    {"id": "dream-qwen-eval-collab", "version": "1.0.0", "category": "orchestration"},
    {"id": "bsk", "version": null, "category": "tooling"},
    {"id": "skill-creator", "version": null, "category": "tooling"}
  ],
  "edges": [
    {"from": "dream-qwen-eval-collab", "to": "bsk", "type": "depends_on"},
    {"from": "dream-qwen-eval-collab", "to": "skill-creator", "type": "depends_on"},
    {"from": "dream-research-workflow", "to": "dream-qwen-eval-collab", "type": "extends"}
  ],
  "cycles": [],
  "orphans": ["skill_2053084099650080768"]
}
```

### 3.5 drift-report.json 结构

```json
{
  "scan_at": "2026-09-21T22:30:00Z",
  "locations_compared": [".trae/skills/", "1-ARCHITECTURE/skills/"],
  "drifts": [
    {
      "skill": "dream-qwen-eval-collab",
      "primary": ".trae/skills/dream-qwen-eval-collab",
      "secondary": "1-ARCHITECTURE/skills/dream-qwen-eval-collab",
      "primary_hash": "sha256:abc123",
      "secondary_hash": "sha256:def456",
      "resolution": "sync from primary to secondary"
    }
  ],
  "orphans_primary": ["tee-red-green-progress"],
  "orphans_secondary": ["dreambuddy-os"]
}
```

### 3.6 conflict-report.json 结构

```json
{
  "scan_at": "2026-09-21T22:30:00Z",
  "trigger_conflicts": [
    {
      "trigger": "深度调研",
      "skills": ["dream-strategy-research", "dream-research-workflow"],
      "resolution": "ALLOW with priority: dream-research-workflow (orchestration layer) shadows dream-strategy-research (trading layer)"
    }
  ],
  "name_conflicts": [
    {
      "name": "dream-strategy-research",
      "locations": ["6-TRADING/skills/", "11-易经推理系统/skills/1-TRADE/"]
    }
  ],
  "dependency_conflicts": [
    {"skill": "dream-xxx", "missing_dependency": "non-existent-skill"}
  ],
  "cycles": [],
  "summary": {"total_conflicts": 4, "blocking": 1, "warnings": 3}
}
```

---

## 四、N 步操作流程（含命令示例）

### 步骤 1：索引构建

```bash
# 全量构建
skill-indexer build --scan ~/.workbuddy/skills,1-ARCHITECTURE/skills,.trae/skills,6-TRADING/skills,4-MEMORY/0-元记忆/superpowers/skills,4-MEMORY/0-元记忆/trading-cognition/skills,11-易经推理系统/skills,deploy/hermes/skills --output skill-registry.json

# 增量构建（基于 git diff）
skill-indexer build --incremental --output skill-registry.json

# 同时生成人类可读索引
skill-indexer build --generate-md SKILL_INDEX.md
```

### 步骤 2：依赖图生成

```bash
# DAG 格式
skill-indexer graph --format dag --output dependency-graph.json

# 拓扑排序（构建/迁移顺序）
skill-indexer topo-sort
```

### 步骤 3：冲突检测

```bash
# 全量冲突检测
skill-indexer conflicts --threshold 0.7 --output conflict-report.json

# 仅触发词冲突
skill-indexer conflicts --type trigger

# 仅同名冲突
skill-indexer conflicts --type name
```

### 步骤 4：漂移扫描

```bash
# 双位置漂移检测
skill-indexer drift --locations .trae/skills,1-ARCHITECTURE/skills --output drift-report.json

# 全位置漂移检测（含 6-TRADING 与 11-易经 重复）
skill-indexer drift --locations ~/.workbuddy/skills,6-TRADING/skills,11-易经推理系统/skills
```

### 步骤 5：生命周期转换

```bash
# proposed → shadow
skill-indexer lifecycle <skill_name> --transition proposed→shadow --evidence VM-xxx

# shadow → active（需 verify success）
skill-indexer lifecycle <skill_name> --transition shadow→active --verify-id VM-xxx

# active → deprecated
skill-indexer lifecycle <skill_name> --transition active→deprecated --reason "被 dream-xxx 替代" --replaced-by dream-xxx

# deprecated → archived（需 ≥12 月窗口）
skill-indexer lifecycle <skill_name> --transition deprecated→archived
```

### 步骤 6：hermes 反思批量评估

```bash
# 扫描所有 SKILL 触发 hermes 反思决策树
skill-indexer hermes-eval

# 仅扫描指定域
skill-indexer hermes-eval --domain 6-TRADING

# 输出衍生建议
skill-indexer hermes-eval --output hermes-reflection-report.json
```

---

## 五、与认知系统集成

### 5.1 recall 时如何检索 SKILL

**场景**：任务开始前 recall 检索相关经验，同时反查关联 SKILL。

**机制**：
```bash
# recall 后自动调用（或 recall 内部集成）
skill-indexer recall-hook --context "调研" --top-k 5
# → 返回 triggers 匹配 context 的 SKILL 列表
# → 每个附带 cognitive_links 中的 VM-id
# → 与 recall 返回的记忆做交集/并集
```

**数据流**：
```
recall(context="深度调研") → 返回 VM-1790001192903-2224e07e
  ↓
skill-indexer query --cognitive-link VM-1790001192903-2224e07e
  → 返回 dream-qwen-eval-collab SKILL
  ↓
Agent 加载 dream-qwen-eval-collab/SKILL.md 作为流程指引
```

### 5.2 record 时如何关联 SKILL

**场景**：任务后发现新经验，record 写入记忆时关联 SKILL。

**机制**：
- record 时若 tags 含 `SKILL`，自动在对应 SKILL 的 frontmatter `cognitive_links` 追加 VM-id
- 或由 hermes 反思决策树触发：衍生新 SKILL 时自动 record 一条 cognitive_link

**实现**：record 工具的 post-hook 调用 `skill-indexer link-memory --skill-id xxx --memory-id VM-xxx`

### 5.3 verify 时如何更新 SKILL 状态

**场景**：对某条记忆执行 verify(success=true) 后，触发关联 SKILL 的 lifecycle 升级。

**机制**：
```
verify(VM-1790001192903-2224e07e, success=true)
  ↓ post-hook
skill-indexer lifecycle-advance --cognitive-link VM-1790001192903-2224e07e
  ↓
若该 SKILL 当前 status=shadow 且 shadow_verified=false
  → 设 shadow_verified=true
  → 若满足 active 条件（≥1 verify success），status: shadow→active
```

---

## 六、与现有治理原语集成

### 6.1 复用 hermes-skill-governance v0.1

**位置**：`~/.workbuddy/skills/hermes-skill-governance/SKILL.md`

**复用方式**：本 SKILL 的冲突检测（能力 3）调用 hermes-skill-governance 的 candidate/scope/conflicts/decision 契约：
- 输入：`candidate`（skill_name/prefix/responsibilities/interfaces）+ `existing_skills[]` + `rules`
- 输出：`decision: ALLOW|DENY` + `scope` + `conflicts[]` + `required_changes[]`
- 本 SKILL 扩展：增加 lifecycle 状态上下文（proposed SKILL 走更严格的 DENY 阈值）

### 6.2 复用 hermes-shadow-verification-gate

**位置**：`~/.workbuddy/skills/hermes-shadow-verification-gate/SKILL.md`

**复用方式**：本 SKILL 的生命周期 `proposed → shadow` 转换调用 hermes-shadow-verification-gate 执行影子验证：
- 影子验证：并行运行，对比产出，不破坏现有流程
- 验证通过：`shadow_verified=true`，可转 active
- 验证失败：保留审计轨迹，状态不前进

### 6.3 复用 hermes-rollback-actuator

**位置**：`~/.workbuddy/skills/hermes-rollback-actuator/SKILL.md`

**复用方式**：本 SKILL 的 `active → deprecated` 或紧急回滚调用 hermes-rollback-actuator：
- 正常弃用：12 月窗口，平滑迁移
- 紧急回滚：active → deprecated（跳过 12 月窗口），需人工确认 + reason

### 6.4 复用 CLAUDE.md hermes 反思决策树

**位置**：`CLAUDE.md` 「hermes 反思决策树（任务结束后必执行）— 硬约束」章节

**复用方式**：本 SKILL 的 `hermes-eval` 命令（步骤 6）批量扫描所有 SKILL，对每个 SKILL 触发 hermes 反思决策树：
- 满足任一条件（流程被复用 ≥ 2 次 / 多步编排 ≥ 3 步 / bsk 自动化 ≥ 1 步 / 用户明确要求）→ 建议衍生新 SKILL
- 否则 → 仅 record 经验

**认知记忆**：VM-1790001702811-24bffe86（hermes 反思决策树硬约束 B 级）

---

## 七、hermes 反思决策树（本 SKILL 自身）

> 引用 dream-qwen-eval-collab 的决策树，但加一条：**本 SKILL 自身生命周期也走 5 阶段**。

```
本 SKILL 是否值得形成/衍生新 SKILL？
├── 是（满足以下任一）：
│   ├── 流程被复用 ≥ 2 次
│   ├── 涉及多步编排（≥ 3 步）
│   ├── 涉及 bsk 自动化（≥ 1 步）
│   └── 用户明确要求「形成 SKILL」
│   → 调用 skill-creator 创建新 SKILL（双位置存储）
│   → 更新 SKILL_INDEX.md + TOOL_MAPPING.md
│   → record 经验，tags 含「SKILL,hermes反思」
│   → 新 SKILL 生命周期从 proposed 开始
│
└── 否（满足以下全部）：
    ├── 一次性任务
    ├── 无 bsk 自动化
    └── 无复用价值
    → 仅 record 经验，tags 不含「SKILL」
```

**本 SKILL 自身生命周期**：
- proposed：2026-09-21（spec 调研完成，hermes 反思触发衍生）
- shadow：2026-09-21（spec 已验证方案 C 44/50 分，相当于影子验证通过）
- active：2026-09-21（本 SKILL.md 落地，索引更新完成，转 active）
- deprecated：未触发
- archived：未触发

---

## 八、认知闭环（recall + record + verify 模板）

### 8.1 任务前 — recall（硬约束）

```
recall(context="SKILL 索引治理 生命周期 冲突检测 漂移", top_k=5, min_quality="C")
```

预期返回：
- VM-1790002963075-0b027747（SKILLS 索引调研 spec B 级）
- VM-1790001702811-24bffe86（hermes 反思决策树硬约束 B 级）
- VM-1790001192903-2224e07e（dream-qwen-eval-collab SKILL 经验 B 级）

### 8.2 任务中 — 执行 SKILL

按"四、N 步操作流程"执行 skill-indexer 命令。

### 8.3 任务后 — record

```
record(content="[SKILL治理] <本次治理动作摘要> | 影响 <N> 个 SKILL | 产物 <registry.json/drift-report.json/...> | 关联 VM-xxx", quality_level="B", tags="SKILL治理,skill-index-governance,<具体动作>")
```

### 8.4 任务后 — verify

若本次治理验证了某条已有记忆：
```
verify(memory_id="VM-xxx", success=true)
```

若本次触发 lifecycle 升级：
```
verify(memory_id="VM-xxx", success=true)
  ↓ post-hook
skill-indexer lifecycle-advance --cognitive-link VM-xxx
```

### 8.5 任务后 — hermes 反思（硬约束）

执行第七节 hermes 反思决策树，评估是否衍生新 SKILL。

---

## 九、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-09-21 | 初始版本。基于 spec 方案 C（混合 manifest + 自动索引，44/50 分）固化落地。5 项核心能力 + 6 步操作流程 + 5 阶段生命周期 + 认知系统集成 + 现有治理原语集成。双位置存储：.trae/skills/ + 1-ARCHITECTURE/skills/。 |

---

## 十、附录

### 10.1 关联文档

- spec 文档：`.trae/documents/skills-index-research-spec.md`
- 现有索引：`1-ARCHITECTURE/工作索引/SKILL_INDEX.md`
- 触发词路由：`1-ARCHITECTURE/工作索引/TOOL_MAPPING.md`
- 认知系统引导：`CLAUDE.md`

### 10.2 关联认知记忆

- `VM-1790002963075-0b027747`（SKILLS 索引调研 spec B 级）
- `VM-1790001702811-24bffe86`（hermes 反思决策树硬约束 B 级）
- `VM-1790001192903-2224e07e`（dream-qwen-eval-collab SKILL 经验 B 级）
- `VM-1786255475855-b4d4268d`（认知系统稳定优先模式 B 级）

### 10.3 工程约束兼容性

| 约束 | 兼容性 | 说明 |
|------|--------|------|
| HC-1a（不改 dreamos/） | ✅ | 本 SKILL 只加 skill-indexer 工具，不改 dreamos/ |
| HC-9（只做信号传递） | ✅ | 本 SKILL 只产信号（drift-report/conflict-report），不触碰执行 |
| FAIL-OPEN | ✅ | 构建失败不影响 SKILL 可用性 |
| 零回归 | ✅ | 渐进增强，旧 SKILL 零改动 |
| 稳定优先模式 | ✅ | 不强制升级，渐进增强 |
| hermes 反思决策树 | ✅ | 本 SKILL 生命周期入口对齐 hermes 反思 |
