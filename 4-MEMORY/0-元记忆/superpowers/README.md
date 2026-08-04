# Dreambuddy Superpowers 本地目录维护规范

> **上游版本**: obra/superpowers v6.2.0 (commit: 44c9b2d6e889982ac18c27d05a19fefe335194e1)
> **本地定位**: 认知系统 Process Layer 的元认知流程层（Meta Process Layer）载体
> **最后同步**: 2026-08-01

本目录是 superpowers skills 体系的本地元记忆副本，用于记录目录约定、更新规则、格式红线与索引说明，作为 AI Agent 操作此目录时的执行依据。

---

## 1 目录结构

```
4-MEMORY/0-元记忆/superpowers/
├── README.md                  ← 本文件（规则与索引说明）
├── skills-index.json          ← 技能索引（结构化目录）
└── skills/
    ├── <skill-slug>/
    │   ├── SKILL.md           ← 技能主描述（Frontmatter + 正文）
    │   ├── *.md               ← 补充文档 / 引用资料
    │   └── scripts/           ← 技能依赖脚本（可选）
    └── ...
```

目录结构说明：

- `skills/<skill-slug>/`：单个技能的根目录，slug 采用小写 kebab-case。
- `SKILL.md`：每个技能目录下必须存在该文件，是技能的权威描述入口。
- `*.md`：补充文档，如示例、prompt 片段、最佳实践等，由 SKILL.md 引用。
- `scripts/`：技能运行时需要调用的脚本或工具，可选。
- `skills-index.json`：所有技能的结构化索引，用于程序化检索与路由。

---

## 2 更新规则

### 2.1 只增不改原则

对 `skills/` 目录下已存在的技能文件与目录，**默认执行只增不改原则**：

- 已存在的 `SKILL.md`：允许在正文末尾追加章节、补充 supplement 完善内容；禁止修改已有章节标题、已验证的 Frontmatter 字段值。
- 已存在的补充文档 `*.md`：允许追加，禁止删除或改写已有段落。
- 已存在的 `scripts/`：允许新增脚本，禁止修改或删除已有脚本（除非有明确的修复工单）。
- 如需重写、删除或重构现有技能，必须先在本 README 的「常见问题」中登记变更理由，再发起操作。

该原则的核心目的：保证上游同步与本地积累的 merge 稳定性，防止 Agent 在一次会话中意外破坏已验证的技能资产。

### 2.2 同步上游操作

上游同步源为 `/tmp/superpowers-research/superpowers/` 仓库，同步步骤：

1. 先执行 `git -C /tmp/superpowers-research/superpowers pull` 更新上游仓库。
2. 取新的 HEAD commit hash：`git -C /tmp/superpowers-research/superpowers rev-parse HEAD`。
3. 将本 README 顶部「上游版本同步基线 commit」行更新为新的 hash。
4. 对比 `skills/` 目录：
   - 上游新增技能目录 → 直接拷贝至本地。
   - 上游已有技能 `SKILL.md` 变更 → 采用 three-way merge，**保留本地 supplement 追加的段落**。
   - 上游删除技能 → 本地暂不删除，仅在 `skills-index.json` 中标记 `status: deprecated`。
5. 同步完成后重建 `skills-index.json`（见第 4 章）。

### 2.3 supplement 完善规则

supplement 指本地在不违反「只增不改原则」的前提下，对技能进行的补充性完善：

- **允许的 supplement 操作**：
  - 在 `SKILL.md` 末尾追加 `## Supplement` 章节及其子节。
  - 在技能目录下新增 `supplement-*.md` 文件并在 SKILL.md 中引用。
  - 新增示例代码、反例、错误模式、FAQ。
  - 新增脚本到 `scripts/` 并在 Supplement 中记录使用方式。
- **禁止的 supplement 操作**：
  - 改写或删除上游原有的 Frontmatter 字段。
  - 重写上游原有的章节正文。
  - 将 Supplement 内容插入到原正文中间。
- supplement 完成后，在 `skills-index.json` 中对应技能的 `supplements` 数组追加一条记录，标注日期与简述。

---

## 3 SKILL.md 格式红线

### 3.1 Frontmatter 分隔符 FAIL FAST

**FAIL FAST 原则**：一旦检测到 Frontmatter 不规范，立刻停止处理该技能，抛出 3.4 定义的报错格式，禁止静默忽略或降级处理。

Frontmatter 必须以 YAML 格式包裹，严格使用三个短横线作为分隔符：

```yaml
---
key1: value1
key2: value2
---
```

红线校验项：

1. 文件第 1 行必须精确等于 `---`（不得有空格、不得为 `***` 或 `~~~`）。
2. 必须存在闭合分隔符，即后续存在某一行精确等于 `---`。
3. 两个 `---` 之间的内容必须是合法 YAML（不可出现未缩进的 `:` 后跟无引号的冒号值导致解析错误）。
4. 闭合分隔符后必须空一行再开始正文（可选 `# 标题`）。

违反以上任一条 → 立即 FAIL FAST，输出错误并退出。

### 3.2 必填字段

每个 SKILL.md 的 Frontmatter 中必须包含以下字段，缺失任意一项 → FAIL FAST：

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 小写字母 + 连字符；**必须严格等于父目录名**（例如目录 `test-driven-development/` 下 Frontmatter 的 `name` 必须是 `test-driven-development`）。若不相等 → FAIL FAST |
| `description` | string | 1-2 句描述，存在且长度 ≥ 20 字符，说明技能触发时机与能力边界 |
| `version` | string | （推荐）语义化版本，如 `1.0.0` |
| `author` | string | （推荐）作者标识，`upstream` 或 `local:<your-name>` |
| `tags` | array<string> | （推荐）分类标签 |

### 3.3 推荐字段

强烈建议补充的字段（非 FAIL FAST，但会在索引中标记 `warnings`）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `tags` | array<string> | 标签，便于检索分组 |
| `dependencies` | array<string> | 依赖的其他技能 ID 或工具名 |
| `anti_patterns` | array<string> | 不该调用本技能的反例场景 |
| `examples` | array<string> | 典型输入示例的一句话描述 |
| `supplements` | array<object> | 本地 supplement 记录，`{date, summary}` |
| `upstream_ref` | string | 上游对应路径或 commit 引用 |

### 3.4 报错格式

所有格式红线校验失败必须使用统一 JSON 报错格式输出至 stderr：

```json
{
  "error": "SKILL_VALIDATION_FAILED",
  "code": "FRONTMATTER_MISSING_CLOSE_DELIMITER",
  "skill_id": "sp-brainstorming",
  "file": "skills/brainstorming/SKILL.md",
  "line": 7,
  "message": "第 1 行必须是 '---'，实际发现的是 '```yaml'",
  "rule": "3.1 Frontmatter分隔符FAIL FAST"
}
```

`code` 枚举（使用时按需扩展）：

- `FRONTMATTER_MISSING_OPEN`
- `FRONTMATTER_MISSING_CLOSE_DELIMITER`
- `FRONTMATTER_INVALID_YAML`
- `REQUIRED_FIELD_MISSING`
- `REQUIRED_FIELD_WRONG_TYPE`
- `TRIGGERS_EMPTY`
- `ID_SLUG_MISMATCH`

---

## 4 skills-index.json 说明

`skills-index.json` 是技能体系的结构化索引，用于程序化查询、路由与校验，结构如下：

```json
{
  "meta": {
    "schema_version": "1.0.0",
    "generated_at": "2026-08-01T00:00:00Z",
    "upstream_commit": "44c9b2d6e889982ac18c27d05a19fefe335194e1",
    "generator": "manual|script:<path>"
  },
  "skills": [
    {
      "id": "sp-brainstorming",
      "slug": "brainstorming",
      "name": "brainstorming",
      "path": "skills/brainstorming/SKILL.md",
      "description": "...",
      "triggers": ["brainstorming", "头脑风暴"],
      "tags": ["planning", "creative"],
      "author": "upstream",
      "version": "1.0.0",
      "status": "active|deprecated|draft",
      "supplements": [
        {"date": "2026-08-01", "summary": "新增本地示例3则"}
      ],
      "warnings": ["缺少推荐字段 tags"],
      "validation": {
        "passed": true,
        "errors": []
      }
    }
  ]
}
```

维护规则：

1. 每次执行「2.2 同步上游操作」或「2.3 supplement 完善规则」后，**必须**重建本文件。
2. `skills[]` 顺序按 `slug` 字母序排列。
3. `validation` 字段应包含运行第 3 章红线校验的结果。
4. 对已删除（上游已删除但本地保留）的技能，`status` 置为 `deprecated`，并在 `warnings` 中注明。
5. `meta.upstream_commit` 必须与本 README 顶部的基线 commit hash 保持一致。

---

## 5 常见问题

### Q1：某个 Skill 不适用我们场景怎么办？
**（也即 Q1-原文：上游 SKILL.md 与本地 supplement 发生冲突如何处理？）**

A：在 supplement 「适用范围」章节写清楚不适用场景，并在「本土化适配说明」写替代方案。SkillLoader 仍会加载该 Skill，但 recall 时如果任务在不适用范围，match_score 会自动降低。上游正文与 supplement 冲突时：保留本地 supplement 段落不改动；上游正文变更采用「追加新节」方式落地，例如在原章节后新增 `## Upstream Update @<hash>` 章节记录差异。禁止直接覆盖本地 supplement。

### Q2：我们有新的本土方法论需要作为流程注入，但不是原版 14 Skill？
**（也即 Q2-原文：新增本地自创技能 / 上游格式违规本地如何处理？）**

A：在 `skills/` 下新建 `local-<method-name>/` 目录，写自己的 `SKILL.md`（严格遵循第 3 章格式红线）和 supplement。SkillLoader 会自动加载并标记 `localized=true, upstream=false`。**name 必须以 `local-` 前缀开头**，避免与上游未来的 Skill 命名冲突。`status` 初始为 `draft`，经过至少 3 次实战验证后改为 `active`。如果是上游违反格式红线而本地需临时处理：按「只增不改原则」，禁止改写上游 Frontmatter 或正文，新增 `supplement-local-fix.md` 记录临时补丁，并在技能的 `warnings` 中加 `upstream_format_issue` 标记。

### Q3：上游更新会覆盖我的 supplement 吗？
**（也即 Q3-原文：同步上游时如何保证本地 supplement 不丢失？）**

A：不会。同步脚本有白名单：`dreambuddy-supplement.md`、`local-*.md`、`skills-index.json` 不会被上游覆盖。同步流程（第 2.2 节）第 4 步对比目录时已明确保留白名单文件。如果不小心覆盖，用 `git restore` 从备份恢复，或从 `_archive/` 下的备份还原。

### Q4：如何验证我改完后所有 Skill 都加载正确？
**（也即 Q4-原文：`skills-index.json` 与实际 `skills/` 目录不一致时以谁为准？）**

A：运行 `cognitive-cli skills list` 查看全部 14 个状态为 `loaded`，且每个 `checklists_count > 0` 和 `hard_gates_count > 0`。`skills-index.json` 与实际 `skills/` 不一致时 **以 `skills/` 目录实际内容为准**。发现不一致时应立即触发索引重建：`cognitive-cli skills rebuild-index`，按第 4 章结构遍历目录、执行 3 章红线校验、输出新的 `skills-index.json`。
