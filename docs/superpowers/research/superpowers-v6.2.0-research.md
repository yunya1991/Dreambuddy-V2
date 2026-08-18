# Superpowers v6.2.0 参考研究报告

> 本报告基于对 `/tmp/superpowers-research/superpowers`（package.json `version: 6.2.0`，发布日期 2026-07-23）仓库的实际文件读取，目标是为"将 Superpowers 14 个 SKILL.md 作为元认知流程层的 upstream base"提供彻底的结构、格式、hook 机制与多宿主适配参考。
>
> 所有引用均给出 `file:///tmp/superpowers-research/superpowers/...` 绝对路径与行号范围，便于后续校对与拉取。

---

## 1. 仓库概览

### 1.1 版本与定位

- `name: superpowers`，`version: 6.2.0`，`description: "Superpowers skills and runtime bootstrap for coding agents"`（见 `file:///tmp/superpowers-research/superpowers/package.json` L1-L6）。
- `type: module`，`main: .opencode/plugins/superpowers.js` —— 同一份代码既是 npm 包又是 OpenCode 插件入口；`pi.extensions` 与 `pi.skills` 字段同时声明 Pi 扩展与 skills 目录（同文件 L13-L22）。
- 仓库定位：一套"软件开发方法论 + 编码 Agent 的可组合 Skill 集合 + 启动 bootstrap"，零运行时依赖（`Superpowers is a zero-dependency plugin by design.`，见 `file:///tmp/superpowers-research/superpowers/CLAUDE.md` L37-L38）。

### 1.2 14 个 Skill 清单

通过 `skills/*/SKILL.md` Glob 得到共 14 个目录，与 README 中 "Skills Library" 列表一致（`file:///tmp/superpowers-research/superpowers/README.md` L218-L238）：

| # | Skill 目录名 | 分类 | 附带文件 |
|---|---|---|---|
| 1 | `brainstorming` | Collaboration | `SKILL.md`, `visual-companion.md`, `spec-document-reviewer-prompt.md`, `scripts/`（含 zero-dep 服务器） |
| 2 | `dispatching-parallel-agents` | Collaboration | 仅 `SKILL.md` |
| 3 | `executing-plans` | Collaboration | 仅 `SKILL.md` |
| 4 | `finishing-a-development-branch` | Collaboration | 仅 `SKILL.md` |
| 5 | `receiving-code-review` | Collaboration | 仅 `SKILL.md` |
| 6 | `requesting-code-review` | Collaboration | `SKILL.md`, `code-reviewer.md`（dispatch 模板） |
| 7 | `subagent-driven-development` | Collaboration | `SKILL.md`, `implementer-prompt.md`, `task-reviewer-prompt.md`, `re-review-prompt.md`, `scripts/{review-package, sdd-workspace, task-brief}` |
| 8 | `systematic-debugging` | Debugging | `SKILL.md`, `root-cause-tracing.md`, `defense-in-depth.md`, `condition-based-waiting.md`, `condition-based-waiting-example.ts`, `find-polluter.sh`, `CREATION-LOG.md`, `test-academic.md`, `test-pressure-*.md` |
| 9 | `test-driven-development` | Testing | `SKILL.md`, `writing-good-tests.md` |
| 10 | `using-git-worktrees` | Collaboration | 仅 `SKILL.md` |
| 11 | `using-superpowers` | Meta (bootstrap) | `SKILL.md`, `references/{antigravity,codex,gemini,pi}-tools.md` |
| 12 | `verification-before-completion` | Debugging | 仅 `SKILL.md` |
| 13 | `writing-plans` | Collaboration | `SKILL.md`, `plan-document-reviewer-prompt.md` |
| 14 | `writing-skills` | Meta | `SKILL.md`, `anthropic-best-practices.md`, `graphviz-conventions.dot`, `persuasion-principles.md`, `render-graphs.js`, `testing-skills-with-subagents.md`, `examples/CLAUDE_MD_TESTING.md` |

### 1.3 支持宿主列表

参见 README L8 与 L30-L186，以及 `docs/porting-to-a-new-harness.md` Appendix A（`file:///tmp/superpowers-research/superpowers/docs/porting-to-a-new-harness.md` L785-L794）：

- **Claude Code**（官方 marketplace，Shape A shell-hook）
- **Antigravity (`agy`)**（plugin install，Shape C 生成式 contextFileName）
- **Codex App / Codex CLI**（marketplace，原生 skill discovery，无 session-start hook）
- **Cursor**（marketplace，Shape A shell-hook，camelCase manifest）
- **Factory Droid**（消费 Claude 插件，无新文件）
- **Gemini CLI**（`gemini extensions install`，Shape C instructions-file）
- **GitHub Copilot CLI**（与 Claude Code 共享 hook 路径，`COPILOT_CLI` 环境变量分支）
- **Kimi Code**（marketplace 或 `/plugins install`，manifest `sessionStart.skill` 字段触发）
- **OpenCode**（`opencode.json` plugin 数组，Shape B in-process JS 插件）
- **Pi**（`pi install`，Shape B in-process TS 扩展，无原生 Skill 工具）

---

## 2. SKILL.md 标准格式分析

> 本节归纳出的"标准结构"并非硬性 schema，而是 14 个文件高度一致的稳定模式。权威的写作规范在 `writing-skills/SKILL.md` 中（`file:///tmp/superpowers-research/superpowers/skills/writing-skills/SKILL.md`），其明文规定只在两点上强制：`name`/`description` 必填、frontmatter 总字符数 ≤ 1024（L96-L103）。

### 2.1 frontmatter 字段规范

固定两个字段，YAML 形式：

```yaml
---
name: <kebab-case-id>
description: <Use when ... 第三人称触发条件>
---
```

- **`name`**：必须与目录名一致，仅允许字母/数字/连字符（`writing-skills/SKILL.md` L98：`Use letters, numbers, and hyphens only (no parentheses, special chars)`）。所有 14 个 Skill 都遵守此约定。
- **`description`**：
  - 强制以 `Use when ...` 开头，第三人称（L103, L178-L180）。
  - **只描述触发条件，绝不总结流程**（这是"Description Trap"反模式，L149-L172 给出了正反例）。例如 `subagent-driven-development` 的 description 为 `Use when executing implementation plans with independent tasks in the current session`，刻意省略 "fresh subagent per task + review after each" 这种流程摘要。
  - 总长度建议 < 500 字符；整个 frontmatter 上限 1024 字符（L97）。
  - 跨规范来源：`writing-skills` 引用 `https://agentskills.io/specification` 作为完整字段定义（L96）。
- 不使用其他字段（无 `version`、`tags`、`priority`、`gates` 等）。

### 2.2 HARD-GATE 格式

并非所有 Skill 都有 HARD-GATE，但出现的位置和写法高度一致。典型示例（`file:///tmp/superpowers-research/superpowers/skills/brainstorming/SKILL.md` L12-L14）：

```markdown
<HARD-GATE>
Do NOT invoke any implementation skill, write any code, scaffold any project, or take any implementation action until you have presented a design and the user has approved it. This applies to EVERY project regardless of perceived simplicity.
</HARD-GATE>
```

特征：

1. 用 XML 风格的 `<HARD-GATE> ... </HARD-GATE>` 包裹，置于 frontmatter 之后、正文开头。
2. 句式为"否定式 + 不可绕过条件"（`Do NOT ... until ...`）。
3. 紧随其后通常配一段 **Anti-Pattern / "This Is Too Simple"** 的反理性化段落（L16-L18），形成 "gate + 反借口" 双层防线。

类似形式还有：

- `<EXTREMELY-IMPORTANT>`（`using-superpowers/SKILL.md` L10-L16）：bootstrap 阶段的元级 gate。
- `<SUBAGENT-STOP>`（同文件 L6-L8）：阻止被 dispatch 的子 agent 再次激活 using-superpowers 流程。
- `<Good> ... </Good>` / `<Bad> ... </Bad>` 配对示例（`test-driven-development/SKILL.md` L75-L106）：作为代码示例的语义化包裹。

HARD-GATE 仅出现在 brainstorming；其他 Skill 倾向使用 **"Iron Law" 代码块 + "Common Rationalizations" 表格** 等价地达到"不可绕过"效果（见 2.3、2.4）。

### 2.3 Checklist 格式

强制顺序执行的 Skill（brainstorming、test-driven-development、subagent-driven-development 等）会写一个明文 Checklist，要求 AI 把每项变成 todo：

```markdown
## Checklist

You MUST create a task for each of these items and complete them in order:

1. **Explore project context** — check files, docs, recent commits
2. **Offer the visual companion just-in-time** — NOT upfront. ...
3. **Ask clarifying questions** — one at a time ...
...
9. **Transition to implementation** — invoke writing-plans skill to create implementation plan
```
（`file:///tmp/superpowers-research/superpowers/skills/brainstorming/SKILL.md` L20-L33）

特征：

- 显式声明"You MUST create a task for each ... in order"。
- 每项是 `**动词短语** — 说明` 形式。
- 每项对应 Process Flow 的一个或多个节点（与 dot 图一一对应）。
- 末项往往是"transition to next skill"，构成 Skill 间的契约式衔接（brainstorming → writing-plans）。

### 2.4 Process 段格式

Process 段是 Skill 的"流程契约"，有三种典型形态：

#### (a) DOT/GraphViz 流程图 + 终止态声明（brainstorming、test-driven-development、systematic-debugging、subagent-driven-development、dispatching-parallel-agents、using-superpowers）

```dot
digraph brainstorming {
    "Explore project context" [shape=box];
    "Ask clarifying questions" [shape=box];
    ...
    "User approves design?" [shape=diamond];
    ...
    "Invoke writing-plans skill" [shape=doublecircle];

    "Explore project context" -> "Ask clarifying questions";
    ...
}
```
（`file:///tmp/superpowers-research/superpowers/skills/brainstorming/SKILL.md` L36-L59）

紧接着用一行声明终止态：

> **The terminal state is invoking writing-plans.** Do NOT invoke frontend-design, mcp-builder, or any other implementation skill. The ONLY skill you invoke after brainstorming is writing-plans.（L61）

特征：

- 用 ``` ```dot ``` 代码块包裹（不是 ```mermaid）。
- 决策节点用 `[shape=diamond]`，普通步骤 `[shape=box]`，终止态 `[shape=doublecircle]` 或 `[shape=box style=filled fillcolor=lightgreen]`（见 `subagent-driven-development/SKILL.md` L77）。
- 子图用 `subgraph cluster_per_task { label="Per Task"; ... }` 表达循环（L51-L70）。
- 边上的标签用 `[label="yes"]` / `[label="no, revise"]`。
- GraphViz 样式规范见 `writing-skills/graphviz-conventions.dot`，并可用 `render-graphs.js` 渲染为 SVG（`writing-skills/SKILL.md` L316-L322）。

#### (b) "Iron Law" 代码块 + 阶段编号（test-driven-development、systematic-debugging、verification-before-completion）

```markdown
## The Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

Write code before the test? Delete it. Start over.
```
（`file:///tmp/superpowers-research/superpowers/skills/test-driven-development/SKILL.md` L31-L46）

```markdown
## The Iron Law

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```
```
（`file:///tmp/superpowers-research/superpowers/skills/systematic-debugging/SKILL.md` L14-L20）

特征：

- 代码块（裸文字）作为"绝对禁令"。
- 紧跟一句"`Violating the letter of the rules is violating the spirit of the rules.`"（test-driven-development L14；systematic-debugging L12；verification-before-completion L13）—— 这是用来封堵"我遵守精神不遵守字面"的理性化路径。
- 阶段编号：systematic-debugging 用 Phase 1-4（L44-L212），test-driven-development 用 RED-GREEN-REFACTOR 循环（L47-L196）。

#### (c) "Gate Function" 伪代码块（verification-before-completion、writing-good-tests）

```markdown
## The Gate Function

```
BEFORE claiming any status or expressing satisfaction:

1. IDENTIFY: What command proves this claim?
2. RUN: Execute the FULL command (fresh, complete)
3. READ: Full output, check exit code, count failures
4. VERIFY: Does output confirm the claim?
   - If NO: State actual status with evidence
   - If YES: State claim WITH evidence
5. ONLY THEN: Make the claim

Skip any step = lying, not verifying
```
```
（`file:///tmp/superpowers-research/superpowers/skills/verification-before-completion/SKILL.md` L23-L36）

`writing-good-tests.md` 同样使用 "Gate Function" 代码块（L65-L79 与 L136-L148），表示写测试前的强制自检。

### 2.5 附带文件模式

Skill 目录允许包含除 `SKILL.md` 之外的文件，遵循 `writing-skills/SKILL.md` L82-L92 的规则：

- **Heavy reference (100+ lines)** → 拆出独立 `.md`，主 SKILL.md 用相对路径链接。
- **Reusable tools / scripts** → 拆出 `scripts/` 子目录。
- **核心原则 / 短代码 (< 50 行)** → 保留 inline。

实际仓库中典型附带文件类型：

| 类型 | 示例 | 引用方式 |
|---|---|---|
| 测试规范参考 | `test-driven-development/writing-good-tests.md` | "When writing or changing any test, read [writing-good-tests.md](writing-good-tests.md) ..."（`test-driven-development/SKILL.md` L206-L211） |
| 调试技术合集 | `systematic-debugging/root-cause-tracing.md`、`defense-in-depth.md`、`condition-based-waiting.md` | "See `root-cause-tracing.md` in this directory ..."（`systematic-debugging/SKILL.md` L113, L279-L283） |
| 子代理 prompt 模板 | `subagent-driven-development/{implementer,task-reviewer,re-review}-prompt.md`；`requesting-code-review/code-reviewer.md` | "Template: [implementer-prompt.md](implementer-prompt.md)"（`subagent-driven-development/SKILL.md` L232, L300, L345） |
| 可执行脚本 | `systematic-debugging/find-polluter.sh`；`subagent-driven-development/scripts/{review-package,sdd-workspace,task-brief}`；`brainstorming/scripts/server.cjs` 等 | "run this skill's `scripts/task-brief PLAN_FILE N`"（`subagent-driven-development/SKILL.md` L206-L216） |
| 跨宿主工具映射 | `using-superpowers/references/{antigravity,codex,gemini,pi}-tools.md` | "read its reference file for special instructions"（`using-superpowers/SKILL.md` L52-L58） |
| 反理性化反例库 | `systematic-debugging/test-academic.md`、`test-pressure-1.md` 等 | 用于 writing-skills 的 RED 阶段 baseline 测试 |
| 元规范文档 | `writing-skills/{anthropic-best-practices.md, persuasion-principles.md, testing-skills-with-subagents.md, graphviz-conventions.dot}` | "see anthropic-best-practices.md ..."（`writing-skills/SKILL.md` L20） |

附带文件用**相对路径**链接（不用 `@`-include，因为 `@` 会强制加载并消耗上下文，见 `writing-skills/SKILL.md` L288）。

---

## 3. 核心 Skill 深度分析

### 3.1 brainstorming

**文件**：`file:///tmp/superpowers-research/superpowers/skills/brainstorming/SKILL.md`（共 151 行）

- **frontmatter**（L1-L4）：
  ```yaml
  ---
  name: brainstorming
  description: "You MUST use this before any creative work - creating features, building components, adding functionality, or modifying behavior. Explores user intent, requirements and design before implementation."
  ---
  ```
  这是少数 description 中带 `You MUST` 的 Skill，刻意用命令式来抬高触发优先级（参见 `using-superpowers/SKILL.md` L29-L31 的 Skill Priority 规则）。
- **HARD-GATE**（L12-L14）：见 2.2 节引用。后面紧跟 Anti-Pattern "This Is Too Simple To Need A Design"（L16-L18），明确指出 "simple projects are where unexamined assumptions cause the most wasted work"。
- **Checklist**（L20-L32）：9 项，强制 in-order。第 2 项 "Offer the visual companion just-in-time — NOT upfront" 是 v6.0.0 引入的关键反模式防御（不主动推 visual companion，只在视觉问题上才提）。
- **Process Flow**（L34-L59）：DOT 图，终止态为 `Invoke writing-plans skill [shape=doublecircle]`。两条回环边：`User approves design? -> Present design sections [label="no, revise"]`、`User reviews spec? -> Write design doc [label="changes requested"]`。
- **Terminal state 声明**（L61）：明文禁止转去 frontend-design / mcp-builder 等实现 skill。
- **Spec self-review**（L112-L120）：四项内联检查（Placeholder scan / Internal consistency / Scope check / Ambiguity check），不重新跑 review，"fix and move on"——这是 v5.0.6 的"inline self-review replaces subagent review loops"决策的产物（见 RELEASE-NOTES L284-L290）。
- **附带文件**：
  - `visual-companion.md`（343 行，未全读）—— 浏览器可视化服务使用指南。
  - `spec-document-reviewer-prompt.md` —— 历史 spec review 子代理模板（v5.0.6 后改为内联 self-review）。
  - `scripts/` —— 零依赖 Node.js WebSocket 服务器（`server.cjs`、`start-server.sh`、`stop-server.sh`、`frame-template.html`、`helper.js`）。

### 3.2 test-driven-development

**文件**：`file:///tmp/superpowers-research/superpowers/skills/test-driven-development/SKILL.md`（共 320 行）

- **frontmatter**（L1-L4）：
  ```yaml
  ---
  name: test-driven-development
  description: Use when implementing any feature or bugfix, before writing implementation code
  ---
  ```
  注意 description **没有任何流程描述**，是 writing-skills 推荐的 "triggering conditions only" 范本（`writing-skills/SKILL.md` L168-L172 把它列为 ✅ GOOD）。
- **Iron Law**（L31-L46）："NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST"，附"Write code before the test? Delete it. Start over." 6 条"No exceptions"列举（`Don't keep it as "reference"`、`Don't "adapt" it while writing tests` 等），逐条封堵理性化路径。
- **RED-GREEN-REFACTOR dot 图**（L48-L69）：`rankdir=LR` 横向流程，红色填色 `#ffcccc`、绿色 `#ccffcc`、蓝色 `#ccccff`，是仓库中唯一带颜色填色的 dot 图。
- **`<Good>` / `<Bad>` 配对示例**（L75-L106, L134-L164）：用 XML 标签包裹代码块，紧随一句点评（如 "Vague name, tests mock not code"）。这种形式比传统 "✅/❌" 更易被 LLM 解析。
- **Common Rationalizations 表**（L212-L227）：11 行，每行都是一句"借口 → 现实"。如 `"I'll test after"` → `Tests written after pass immediately — which proves nothing.`。
- **Red Flags - STOP and Start Over**（L228-L244）：12 个 bullet，最后一行用粗体总结 "All of these mean: Delete code. Start over with TDD."
- **附带文件 `writing-good-tests.md`**（198 行）：v6.2.0 重命名自 `testing-anti-patterns.md`，改为正向规则目录（"six rules that lead with the GOOD example"，RELEASE-NOTES L16）。包含两个 "Gate Function" 代码块（L65-L79 命名 break、L136-L148 mock 评估）和 "The Mutation Check"（L157-L169）。**核心反模式**：string-presence trap（grep 脚本/skill 文本不算测试）和 change-detector trap（断言常量值不能保护任何东西）。

### 3.3 systematic-debugging

**文件**：`file:///tmp/superpowers-research/superpowers/skills/systematic-debugging/SKILL.md`（共 283 行）

- **frontmatter**（L1-L4）：
  ```yaml
  ---
  name: systematic-debugging
  description: Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes
  ---
  ```
- **Iron Law**（L14-L20）："NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST"。
- **Four Phases**（L44-L212）：典型的"阶段化" Process 段。
  - Phase 1（L48-L118）：Root Cause Investigation。包含 5 个子步骤，其中第 4 步 "Gather Evidence in Multi-Component Systems" 给出多组件 bash instrumentation 模板（L74-L104），第 5 步指向 `root-cause-tracing.md`。
  - Phase 2（L120-L141）：Pattern Analysis。
  - Phase 3（L143-L167）：Hypothesis and Testing，含"Scientific method"4 步。
  - Phase 4（L169-L212）：Implementation。关键约束：3 次以上 fix 失败 → "Question Architecture"（L198-L212），不允许尝试第 4 次 fix。
- **Red Flags**（L214-L231）：11 个 bullet，包括 "Quick fix for now, investigate later"、"One more fix attempt (when already tried 2+)" 等。
- **your human partner's Signals You're Doing It Wrong**（L233-L242）：5 个用户原话（"Is that not happening?"、"Stop guessing" 等）→ 含义映射。
- **Common Rationalizations 表**（L244-L256）：8 行。
- **Quick Reference 表**（L258-L264）：4 行 Phase 摘要。
- **附带文件**：
  - `root-cause-tracing.md`（169 行）：trace back through call stack 技术，含 5-step trace 示例和 dot 图（`file:///tmp/superpowers-research/superpowers/skills/systematic-debugging/root-cause-tracing.md` L10-L24, L132-L152）。
  - `defense-in-depth.md`：多层验证技术。
  - `condition-based-waiting.md` + `condition-based-waiting-example.ts`：用条件轮询替代固定 timeout。
  - `find-polluter.sh`：二分查找污染测试的脚本。v6.2.0 修复了路径前缀 bug（RELEASE-NOTES L31）。
  - `test-academic.md`、`test-pressure-1/2/3.md`：用于 writing-skills RED 阶段的 baseline 测试场景。
  - `CREATION-LOG.md`：Skill 创建历史。

### 3.4 subagent-driven-development

**文件**：`file:///tmp/superpowers-research/superpowers/skills/subagent-driven-development/SKILL.md`（共 503 行，本仓库最长 SKILL.md）

- **frontmatter**（L1-L4）：
  ```yaml
  ---
  name: subagent-driven-development
  description: Use when executing implementation plans with independent tasks in the current session
  ---
  ```
  description 刻意只描述触发条件（"Use when ... in the current session"），不含 "fresh subagent per task + review" 等流程——这是 writing-skills 反复强调的 Description Trap 防御（见 `writing-skills/SKILL.md` L150-L156 的正反例对照，正例正是这条 description）。
- **没有 HARD-GATE，但有强约束句**：
  - "Fresh subagent per task + task review (spec + quality) + broad final review = high quality, fast iteration"（L13）。
  - "Continuous execution: Do not pause to check in with your human partner between tasks."（L17）—— 反 "should I continue?" 中断。
- **两张 dot 图**：
  1. **When to Use**（L21-L37）：3 个决策菱形（Have plan? Tasks independent? Stay in session?），路由到 subagent-driven / executing-plans / manual。
  2. **The Process**（L47-L107）：subgraph `cluster_per_task` 包住循环体，含 "Fix round R of 5" 5 轮 circuit breaker（L61）、"R = 5?" breaker trip（L64-L67）。终止态：`Use superpowers:finishing-a-development-branch [shape=box style=filled fillcolor=lightgreen]`（L77, L106）。
- **Setup 段**（L110-L155）：v6.2.0 的关键变更——plan-scoped workspace（`.superpowers/sdd/<plan-basename>/`），通过 `scripts/sdd-workspace PLAN_FILE` 解析；ledger 第一行必须写 `# SDD ledger — plan: <plan file path>`，用来防止跨 plan 污染（RELEASE-NOTES L9）。
- **Model Selection**（L157-L192）：按任务复杂度选模型，"Always specify the model explicitly when dispatching a subagent."（L177-L179）。**Turn count beats token price**（L181-L187）：廉价模型常 2-3× 轮次，反而更贵。
- **Task Loop**（L194-L389）：5 个子段：
  1. Dispatch the implementer（L200-L232）—— 用 `scripts/task-brief PLAN_FILE N` 抽取任务文本到文件；BASE 必须用 `git rev-parse HEAD` 在 dispatch 前记录，禁用 `HEAD~1`（会丢多 commit task）。
  2. Handle the report（L234-L255）—— 四种状态 DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED。
  3. Review the task（L257-L300）—— `scripts/review-package PLAN_FILE BASE HEAD` 生成 diff 文件给 reviewer；"Never dispatch a task reviewer without a diff file."（L272）；禁止 controller 预判 findings（"do not flag", "don't treat X as a defect", "at most Minor" 等措辞出现就要停，L286-L292）。
  4. The fix loop（L302-L376）—— **5-round circuit breaker**：R1-R3 resume 原 implementer（context 完整）；R4-R5 dispatch fresh implementer + 更强模型；R5 之后 trip breaker，controller 必须自己 adjudicate（"park with ruling" 或 "STOP: BLOCKED"）。
  5. Complete the task（L377-L389）—— ledger 写 `Task <N>: complete (commits <base7>..<head7>, review clean)` 或 `... <K> parked)`。
- **Final Review**（L391-L414）：whole-branch review，dispatch on most capable model；返回 findings 时只 dispatch **一个** fix subagent（不是 per-finding），避免"per-finding fixers"爆炸成本（L405-L408）。
- **Common Rationalizations 表**（L425-L437）：8 行，每条针对一种 controller 偷懒路径（"Close enough on spec compliance"、"I'll fix it myself"、"One more round will converge" 等）。
- **Example Workflow**（L438-L502）：完整对话示例，含 Task 1 clean / Task 2 fix round 1/5 两种路径。
- **附带文件**：
  - `implementer-prompt.md`：implementer dispatch 模板。
  - `task-reviewer-prompt.md`：单 reviewer（spec compliance + quality 双 verdict）。
  - `re-review-prompt.md`：scoped re-review，v6.2.0 新增（RELEASE-NOTES L10）。
  - `scripts/review-package`：生成 diff 文件。
  - `scripts/sdd-workspace`：解析 plan-scoped 工作目录。
  - `scripts/task-brief`：抽取 task N 的完整文本到 brief 文件。

---

## 4. SessionStart hook 机制

### 4.1 hook 配置文件

仓库根有 2 个 hook 配置：

- `hooks/hooks.json`（Claude Code 用，`file:///tmp/superpowers-research/superpowers/hooks/hooks.json`）：
  ```json
  {
    "hooks": {
      "SessionStart": [
        {
          "matcher": "startup|clear|compact",
          "hooks": [
            {
              "type": "command",
              "command": "\"${CLAUDE_PLUGIN_ROOT}/hooks/run-hook.cmd\" session-start",
              "shell": "bash",
              "async": false
            }
          ]
        }
      ]
    }
  }
  ```
  - `matcher` 用 `"startup|clear|compact"`：只在新建/清空/压缩会话时触发，**不**在 `--resume` 时重注入（v5.0.3 修复，RELEASE-NOTES L348）。
  - `shell: "bash"` 是 v6.2.0 关键修复：Windows 上让 Claude Code ≥ 2.1.81 走 Git Bash，否则 PowerShell 解析 quoted command 报 ParserError、cmd.exe 截断带 `(` 的路径（RELEASE-NOTES L23）。
  - `async: false`：v4.3.0 改为同步，避免 hook 未完成时模型首轮无 bootstrap（RELEASE-NOTES L606-L608）。

- `hooks/hooks-cursor.json`（Cursor 用，`file:///tmp/superpowers-research/superpowers/hooks/hooks-cursor.json`）：
  ```json
  {
    "version": 1,
    "hooks": {
      "sessionStart": [
        { "command": "./hooks/run-hook.cmd session-start" }
      ]
    }
  }
  ```
  - camelCase `sessionStart`、有 `version: 1`、用相对路径、**无** `matcher`/`type`/`async` 字段。
  - 这是 Cursor 与 Claude Code hook schema 的关键差异（porting 文档 L388-L393 警告不要把 Claude Code 模板当成"通用模板"）。

### 4.2 polyglot wrapper `run-hook.cmd`

`file:///tmp/superpowers-research/superpowers/hooks/run-hook.cmd`（47 行）是同一个文件既是 Windows batch 又是 Unix shell 脚本：

- 顶部用 `: << 'CMDBLOCK' ... CMDBLOCK` 让 Unix shell 把 batch 段当成 heredoc 跳过（L1, L40）。
- Windows 部分（L2-L39）依次尝试 `C:\Program Files\Git\bin\bash.exe`、`C:\Program Files (x86)\Git\bin\bash.exe`、`where bash` PATH fallback；找不到时**静默退出 0**（"plugin still works, just without SessionStart context injection" L37-L39），不报错。
- Unix 部分（L42-L46）用 `exec bash "${SCRIPT_DIR}/${SCRIPT_NAME}" "$@"` 直接转交。
- 关键约束：hook 脚本必须**无扩展名**（`session-start` 而非 `session-start.sh`），因为 Claude Code 2.1.x 在 Windows 上对包含 `.sh` 的命令会自动 prepend `bash`，破坏 polyglot 模式（porting 文档 L752-L757）。

### 4.3 `session-start` 脚本实现

`file:///tmp/superpowers-research/superpowers/hooks/session-start`（48 行）做了三件事：

1. **定位 plugin root**（L6-L8）：
   ```bash
   SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
   PLUGIN_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
   ```
   不依赖任何环境变量，自己 `dirname` 重新推导 root。

2. **读取 using-superpowers/SKILL.md 全文 + JSON 转义**（L10-L26）：
   ```bash
   using_superpowers_content=$(cat "${PLUGIN_ROOT}/skills/using-superpowers/SKILL.md" 2>&1 || echo "Error reading using-superpowers skill")

   escape_for_json() {
       local s="$1"
       s="${s//\\/\\\\}"
       s="${s//\"/\\\"}"
       s="${s//$'\n'/\\n}"
       s="${s//$'\r'/\\r}"
       s="${s//$'\t'/\\t}"
       printf '%s' "$s"
   }
   ```
   - 这里 `cat` 整份 `SKILL.md`，**frontmatter 也原样输出**（porting 文档 L360-L363 明确说"frontmatter included — that's fine; it's emitted verbatim"）。
   - `escape_for_json` 用 bash 参数替换 `${s//old/new}`（每个 pattern 一次 C 层 pass），比早期字符循环快 7×（v4.2.0 修复，RELEASE-NOTES L632-L634）。

3. **组装 bootstrap 字符串 + 按 platform 选 JSON 形态**（L27-L47）：
   ```bash
   session_context="<EXTREMELY_IMPORTANT>\nYou have superpowers.\n\n**Below is the full content of your 'superpowers:using-superpowers' skill - your introduction to using skills. For all other skills, use the 'Skill' tool:**\n\n${using_superpowers_escaped}\n</EXTREMELY_IMPORTANT>"

   if [ -n "${CURSOR_PLUGIN_ROOT:-}" ]; then
     printf '{\n  "additional_context": "%s"\n}\n' "$session_context" | cat
   elif [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -z "${COPILOT_CLI:-}" ]; then
     printf '{\n  "hookSpecificOutput": {\n    "hookEventName": "SessionStart",\n    "additionalContext": "%s"\n  }\n}\n' "$session_context" | cat
   else
     printf '{\n  "additionalContext": "%s"\n}\n' "$session_context" | cat
   fi
   ```
   - 三种 JSON 形态：Cursor 用 `additional_context`（snake_case 顶层）、Claude Code 用 `hookSpecificOutput.additionalContext`（嵌套）、Copilot CLI / SDK 标准用 `additionalContext`（camelCase 顶层）。
   - **必须只输出一种**：Claude Code 会同时读 `additional_context` 和 `hookSpecificOutput` 且**不去重**，多输出会双注入（RELEASE-NOTES L446-L447；porting 文档 L373-L379）。
   - 末尾 `| cat` 是为了吸收 broken pipe（Windows 上 `printf` 报 write error，v6.0.0 修复，RELEASE-NOTES L166）。

### 4.4 触发时机与执行方式

- **触发**：宿主在 session 启动（startup）/ clear / compact 时，根据 `hooks.json` 调用 `run-hook.cmd session-start`。Claude Code 通过 `${CLAUDE_PLUGIN_ROOT}` 注入 plugin root；Cursor 用 `CURSOR_PLUGIN_ROOT`（也可能同时设 `CLAUDE_PLUGIN_ROOT`，故分支判断 Cursor 优先）；Copilot CLI 通过 `COPILOT_CLI=1` 标识。
- **执行**：同步（`async: false`），stdout 输出 JSON。宿主解析 JSON 后把 `additionalContext` / `additional_context` 字段内容**追加到模型首轮上下文**。
- **效果**：模型一上线就看到 `<EXTREMELY_IMPORTANT>...using-superpowers 全文...</EXTREMELY_IMPORTANT>`，于是知道"自己有 superpowers"，并按 `using-superpowers/SKILL.md` 的"The Rule"（L18-L24）在响应任何请求前先 invoke 相关 Skill。
- **不重注入**：`startup|clear|compact` matcher 排除了 `resume`，所以 resume session 时不会重复注入（v5.0.3 修复）。
- **hook 失败的优雅降级**：`run-hook.cmd` 在 Windows 找不到 bash 时静默 exit 0，宿主仍能正常运行，只是没有 bootstrap（porting 文档 L246-L251 警告：有 `hooks.json` 机制 ≠ 有 SessionStart 事件，需要单独验证）。

### 4.5 hook 测试

`tests/hooks/test-session-start.sh`（225 行）通过 4 个 `assert_command_output` 调用验证：
1. Claude Code（`CLAUDE_PLUGIN_ROOT` set, `COPILOT_CLI` unset）→ nested `hookSpecificOutput.additionalContext` 形态。
2. `run-hook.cmd` wrapper 也能正确 dispatch 到 `session-start`。
3. Cursor（`CURSOR_PLUGIN_ROOT` set，同时 `CLAUDE_PLUGIN_ROOT` 也 set）→ 必须输出 `additional_context`，且**不能**含 `hookSpecificOutput` 或 `additionalContext`。
4. Copilot CLI（`COPILOT_CLI=1`）→ 输出 `additionalContext`，且不能含另两个字段。
5. 还断言"不再输出 obsolete legacy custom-skill warning"（防止 v3.x 的提示文案回归）。
6. 第一段还验证 `hooks.json` 的 `SessionStart` entry 必须声明 `shell: "bash"` 且 command 以 `run-hook.cmd" session-start` 结尾——直接锁住 v6.2.0 的 Windows 修复（L150-L165）。

---

## 5. 多宿主适配分析

### 5.1 Claude Code 适配

**清单文件**：

- `.claude-plugin/plugin.json`（`file:///tmp/superpowers-research/superpowers/.claude-plugin/plugin.json`，20 行）：仅 `name`/`description`/`version`/`author`/`homepage`/`repository`/`license`/`keywords`。**不**声明 `skills` 或 `hooks` 字段——Claude Code 通过约定自动发现 `skills/` 和 `hooks/hooks.json`（porting 文档 L239-L243）。
- `.claude-plugin/marketplace.json`（20 行）：本地开发 marketplace，`plugins[0].source: "./"`，可被 `/plugin install superpowers@superpowers-dev` 直接装。

**bootstrap 路径**：Shape A shell-hook → `hooks/hooks.json` → `${CLAUDE_PLUGIN_ROOT}/hooks/run-hook.cmd session-start` → `hooks/session-start` → 输出 `hookSpecificOutput.additionalContext` JSON。

**Skill 工具**：Claude Code 有原生 `Skill` 工具，无需 adapter 文件。`using-superpowers/SKILL.md` 的 "Platform Adaptation" 段不列 Claude Code（只列 Codex/Pi/Antigravity，L52-L58）。

### 5.2 Cursor 适配

**清单文件**：`.cursor-plugin/plugin.json`（23 行）：
```json
{
  "name": "superpowers",
  "displayName": "Superpowers",
  ...
  "skills": "./skills/",
  "hooks": "./hooks/hooks-cursor.json"
}
```
- 显式声明 `skills` 和 `hooks` 字段（Cursor 不做约定发现）。
- 多了 `displayName` 字段（Claude 没有）。
- 指向 `hooks-cursor.json`（camelCase 风格）。
- v5.0.3 加入，v6.0.0 删除了 `agents` 和 `commands` 字段（这两个目录已不存在，RELEASE-NOTES L142）。

**bootstrap 路径**：与 Claude Code 共用 `hooks/session-start`，但脚本检测 `CURSOR_PLUGIN_ROOT` 走 `additional_context` 分支。Cursor 可能同时设 `CLAUDE_PLUGIN_ROOT`，所以判断顺序 Cursor 优先（`hooks/session-start` L38-L40）。

**Skill 工具**：与 Claude Code 工具面兼容，无需 `references/cursor-tools.md`（porting 文档 L789）。

### 5.3 Codex 适配（App + CLI）

**清单文件**：`.codex-plugin/plugin.json`（48 行，`file:///tmp/superpowers-research/superpowers/.codex-plugin/plugin.json`）：
```json
{
  "name": "superpowers",
  "version": "6.2.0",
  "skills": "./skills/",
  "hooks": {},
  "interface": {
    "displayName": "Superpowers",
    "shortDescription": "...",
    "longDescription": "...",
    "developerName": "Jesse Vincent",
    "category": "Developer Tools",
    "capabilities": ["Interactive", "Read", "Write"],
    "defaultPrompt": ["I've got an idea for something I'd like to build.", "Let's add a feature to this project."],
    "websiteURL": "...",
    "brandColor": "#F59E0B",
    "composerIcon": "./assets/superpowers-small.svg",
    "logo": "./assets/app-icon.png",
    "screenshots": []
  }
}
```

关键点：

- `"hooks": {}` 显式空对象。**不是省略字段**，也不是 `[]` 或空 inline list——这三种都会被 Codex 当成"未声明"而 fallback 自动发现 `hooks/hooks.json` 并重注册 Claude 的 SessionStart hook（v6.1.1 修复，RELEASE-NOTES L40-L41）。**值必须正好是 `{}`。**
- `interface` 是 Codex marketplace 的展示信息（图标、品牌色、default prompt）。
- Codex 有原生 skill discovery，所以**没有 SessionStart hook**——bootstrap 不是通过 hook 注入，而是依靠 Codex 自己触发 skill（RELEASE-NOTES L59）。

**bootstrap 路径**：Codex 不注入 `<EXTREMELY_IMPORTANT>` bootstrap，而是依靠 `using-superpowers` skill 的 description 自身被 Codex surface 出来触发模型加载。这是 porting 文档 L534-L553 描述的"surfaced skill index" softer 路径——不保证 wrapper、不保证 tool mapping 注入，需 `references/codex-tools.md` 被模型主动读。

**外部 marketplace 同步**：`scripts/sync-to-codex-plugin.sh`（466 行）把仓库 rsync 到 `prime-radiant-inc/openai-codex-plugins` 仓库的 `plugins/superpowers/` 子目录并开 PR。`EXCLUDES` 数组（L45-L81）锚定根目录，剔除 `.claude/`/`.cursor-plugin/`/`.kimi-plugin/`/`.opencode/`/`.pi/`/`docs/`/`tests/`/`scripts/`/`CLAUDE.md`/`GEMINI.md` 等宿主相关文件，只保留 Codex 需要的内容。

### 5.4 Kimi Code 适配

**清单文件**：`.kimi-plugin/plugin.json`（38 行，`file:///tmp/superpowers-research/superpowers/.kimi-plugin/plugin.json`）：
```json
{
  "name": "superpowers",
  "version": "6.2.0",
  ...
  "skills": "./skills/",
  "sessionStart": { "skill": "using-superpowers" },
  "skillInstructions": "Kimi Code tool mapping for Superpowers skills:\n\n- When a Superpowers skill says to ask the user, ... call Kimi Code's `AskUserQuestion` tool. ...\n- When a Superpowers skill refers to `TodoWrite`, use Kimi Code's `TodoList` tool.\n- When a Superpowers skill says `Task tool (general-purpose)` ..., use Kimi Code's `Agent` tool with a Kimi subagent type. ...",
  "interface": { "displayName": "Superpowers", ... }
}
```

特殊点：

- `sessionStart.skill: "using-superpowers"`：**Kimi 专用字段**，让宿主在 session 启动时主动加载 using-superpowers skill（不是通过 shell hook，也不是通过 in-process 插件）。
- `skillInstructions` 是 inline 的 tool mapping（Kimi Code 把所有 mapping 塞进 manifest 而不是 `references/kimi-tools.md`）。规则覆盖：`AskUserQuestion` 替代问问题、`TodoList` 替代 `TodoWrite`、`Agent` 替代 `Task`（且不能传 `general-purpose` 作为 `subagent_type`，要用 `coder`/`explore`/`plan`）。
- Kimi 是 v6.0.0 加入的三大新宿主之一（RELEASE-NOTES L101）。

### 5.5 OpenCode 适配（Shape B in-process JS）

**清单文件**：根 `package.json` 的 `main: ".opencode/plugins/superpowers.js"`（既是 npm 入口也是 OpenCode 入口）。`.opencode/INSTALL.md` 给出 `opencode.json` 配置：
```json
{ "plugin": ["superpowers@git+https://github.com/obra/superpowers.git"] }
```

**bootstrap 实现**：`.opencode/plugins/superpowers.js`（138 行，`file:///tmp/superpowers-research/superpowers/.opencode/plugins/superpowers.js`）是一个 ES module，导出 `SuperpowersPlugin({ client, directory })` 工厂函数。返回值含两个 hook：

1. `config(config)`（L107-L113）：把 `superpowersSkillsDir` push 进 `config.skills.paths` —— OpenCode 据此发现 skills 目录，**无需 symlink**（v5.0.4 引入，RELEASE-NOTES L332）。
2. `'experimental.chat.messages.transform'(_input, output)`（L124-L137）：在**每个 agent step**（不是每轮）触发；找到 `output.messages` 里的第一条 user 消息，把 bootstrap 文本 `unshift` 进 `parts[0]`。**去重 guard**：检查是否已含 `EXTREMELY_IMPORTANT` 字符串，避免重复注入（L133）。

**bootstrap 字符串构造**（`getBootstrapContent` L62-L100）：

- **module 级缓存**（`_bootstrapCache`，L53-L54）：第一次调用读文件 + 解析 frontmatter，之后直接返回；null sentinel 表示文件缺失。这是 v6.0.0 修复（避免每个 step 重复 `fs.existsSync` + `fs.readFileSync` + 正则，RELEASE-NOTES L221-L223）。
- frontmatter 用简单的正则 + 行解析（L17-L34），避免依赖外部库（保持零依赖）。
- 输出格式：`<EXTREMELY_IMPORTANT>You have superpowers.\n\n...using-superpowers body...\n\n**Tool Mapping for OpenCode:**\n- Create or update todos → todowrite\n- Subagent (general-purpose): → task with subagent_type: "general"\n- Invoke a skill → OpenCode's native skill tool\n...</EXTREMELY_IMPORTANT>`。
- **tool mapping inline** 在 bootstrap 字符串里（Shape B 的典型做法，porting 文档 L493-L496）。

**测试**：`tests/opencode/` 含 `test-bootstrap-caching.mjs`、`test-plugin-loading.sh`、`test-priority.sh`、`test-tools.sh` 等，覆盖缓存行为、fs 调用次数、injection guard、missing-file sentinel、cache reset 共 15 个回归用例（RELEASE-NOTES L221）。

### 5.6 Pi 适配（Shape B in-process TS，无原生 Skill 工具）

**清单文件**：根 `package.json` 的 `pi.extensions: ["./.pi/extensions/superpowers.ts"]` 与 `pi.skills: ["./skills"]`（package.json L15-L22）。`pi install git:github.com/obra/superpowers` 命令据此加载。

**bootstrap 实现**：`.pi/extensions/superpowers.ts`（121 行，`file:///tmp/superpowers-research/superpowers/.pi/extensions/superpowers.ts`）。

关键设计：

- 用 `pi.on("resources_discover", ...)` 注册 skills 目录（L19-L21）—— Pi 有 native skill discovery 但无 `Skill` 工具。
- 用 `pi.on("session_start", ...)` 和 `pi.on("session_compact", ...)` 把 `injectBootstrap` 标志置 `true`（L23-L29），`pi.on("agent_end", ...)` 置 `false`（L31-L33）—— **生命周期标志**而非 per-step dedup（与 OpenCode 的策略不同，porting 文档 L810-L812 警告不能照搬）。
- `pi.on("context", event)`（L35-L56）：检查 `injectBootstrap` 与 dedup marker，构造 user 消息 `{ role: "user", content: [{ type: "text", text: bootstrap }], timestamp: Date.now() }`，**插入到 first non-compactionSummary 消息之后**（L48-L55）。这处理了 compact 后的消息顺序（compact summary 在前，bootstrap 紧随其后）。
- `getBootstrapContent()`（L59-L81）也用 module-level cache（`cachedBootstrap`）。`stripFrontmatter` 用正则。
- `piToolMapping()`（L88-L98）：**同时** inline 在 bootstrap 里**和** `references/pi-tools.md` 文件中——porting 文档 L818-L819 警告"两处都要更新"。
- Pi 没有 `Skill` 工具，所以 mapping 明说"load the relevant `SKILL.md` with `read` when the skill applies"——这是 porting 文档 L526-L531 描述的"sanctioned read-SKILL.md fallback"。

**Type-only import**：`import type { ExtensionAPI } from "@earendil-works/pi-coding-agent"`（L4）。Pi 在运行时直接执行 `.ts` 并提供该类型，**仓库不把 `@earendil-works/pi-coding-agent` 声明为 dependency**——这绕过了"零运行时依赖"规则，因为它是 type-only，编译时消失。porting 文档 L329-L339 警告：如果你的宿主真的 type-check 或 bundle 插件，这种 undeclared type import 会失败，需要事先和 maintainer 确认。

### 5.7 Gemini 适配（Shape C instructions-file）

**清单文件**：`gemini-extension.json`（5 行）：
```json
{
  "name": "superpowers",
  "description": "Core skills library: TDD, debugging, collaboration patterns, and proven techniques",
  "version": "6.2.0",
  "contextFileName": "GEMINI.md"
}
```
- `contextFileName: "GEMINI.md"`：让 Gemini 加载本扩展自带的 `GEMINI.md` 作为 instructions file（**不是**用户 home 里的 GEMINI.md）。
- 没有 `skills` 字段——Gemini 自动发现扩展目录下的 `skills/`。

**bootstrap 实现**：根 `GEMINI.md` 只有 2 行：
```
@./skills/using-superpowers/SKILL.md
@./skills/using-superpowers/references/gemini-tools.md
```
- 用 Gemini 的 `@`-include 语法把 using-superpowers 全文 + gemini-tools.md 全文 inline 进 instructions。
- **不构造字符串、不去 frontmatter**：Gemini 直接加载文件原样（含 frontmatter）。
- **不写 `<EXTREMELY_IMPORTANT>` 前导语**：因为对 instructions-file 形态，内容本身就是 active instruction set，模型不会"重新 invoke"它（porting 文档 L449-L454）。
- porting 文档 L277-L286 警告：`@`-include 在 Gemini-derived 宿主上**不保证**被展开——有的 fork 把 `@./path` 当 hint 让模型自己 read，而不是 inline expansion。**必须用 unique-marker test 验证**：如果 marker 不在 context 里就改成 inline。

**v6.0.0 → v6.1.0 删除 → v6.2.0 恢复**：Gemini CLI 在 2026-06-18 被 Google EOL，v6.1.0 删除了支持（RELEASE-NOTES L63）；但后来又恢复（v6.2.0 RELEASE-NOTES L27：`Gemini CLI support is restored. ... the install docs and the gemini-tools.md tool-mapping reference are back while permanent removal gets a proper evaluation.`）。

### 5.8 Antigravity 适配

未读取 `.antigravity-plugin/`（仓库中无此目录，根据 porting 文档 L692-L704 描述：`agy plugin install` 通过 `install.sh` 把 manifest + skills + **生成的 context file**（`ANTIGRAVITY.md`）拷贝到 staging dir，由 `agy` 自己 install）。`using-superpowers/references/antigravity-tools.md`（21 行）只列两行映射：subagent → `invoke_subagent`，task tracking → `write_to_file` with `IsArtifact: true, ArtifactType: "task"`（**不是** `manage_task`，那是管后台进程的）。

### 5.9 GitHub Copilot CLI 适配

与 Claude Code 共享 hook 路径，但 `session-start` 检测 `COPILOT_CLI=1` 环境变量走 SDK standard `additionalContext` 分支（v5.0.7 引入，RELEASE-NOTES L272-L274）。`references/copilot-tools.md` 在 v6.1.0 被删除（"had nothing harness-specific left"，RELEASE-NOTES L54）。

### 5.10 各宿主对比汇总

| 宿主 | 形态 | 清单文件 | bootstrap 注入字段 | tool mapping 位置 | 测试目录 |
|---|---|---|---|---|---|
| Claude Code | A (shell-hook) | `.claude-plugin/plugin.json` (无 hooks/skills 字段，约定发现) | `hookSpecificOutput.additionalContext` | native Skill tool，无需 | `tests/hooks/`, `tests/claude-code/` |
| Cursor | A (shell-hook) | `.cursor-plugin/plugin.json` (`hooks`, `skills`, `displayName`) | `additional_context` (snake_case 顶层) | 无需（兼容 Claude 工具面） | `tests/hooks/` |
| Copilot CLI | A (shell-hook) | 共享 Claude 路径，`COPILOT_CLI=1` 分支 | `additionalContext` (camelCase 顶层) | 无需 | `tests/hooks/` |
| Codex App/CLI | 无 hook | `.codex-plugin/plugin.json` (`hooks: {}`, `interface.*`) | 不注入，靠 surfaced skill description 触发 | `references/codex-tools.md` | `tests/codex/`, `tests/codex-plugin-sync/` |
| Kimi Code | manifest 字段触发 | `.kimi-plugin/plugin.json` (`sessionStart.skill`, `skillInstructions`) | manifest 指定加载 using-superpowers | inline `skillInstructions` | `tests/kimi/` |
| OpenCode | B (in-process JS) | `package.json` main + `opencode.json` plugin array | user message unshift, per-step dedup | inline `toolMapping` 常量 | `tests/opencode/` |
| Pi | B (in-process TS) | `package.json` `pi.extensions`/`pi.skills` | user message insert, 生命周期 flag + compact-aware | inline `piToolMapping()` + `references/pi-tools.md`（双处） | `tests/pi/` |
| Gemini | C (instructions-file) | `gemini-extension.json` (`contextFileName`) | 不注入，`@`-include instructions 文件 | `references/gemini-tools.md`，被 `@`-include | （无 in-tree 测试） |
| Antigravity | C (installer-generated) | `.antigravity-plugin/` (install.sh 生成 `ANTIGRAVITY.md`) | installer 生成 context file，`agy plugin install` 拷贝 | inline 在生成的 context file | `tests/antigravity/` |

---

## 6. 测试与 CI

### 6.1 测试目录结构

`tests/` 只放**插件基础设施测试**；**Skill 行为测试**移到了独立仓库 `superpowers-evals`（drill harness，RELEASE-NOTES L161, L102-L104）。`tests/` 子目录按宿主分（见 1.2 节末的 LS 输出）：

- `tests/hooks/test-session-start.sh`（225 行）—— 见 4.5 节。
- `tests/claude-code/`：5 个 shell 脚本，含 `test-subagent-driven-development.sh`（单元）、`test-subagent-driven-development-integration.sh`（端到端，900s timeout）、`test-sdd-workspace.sh`、`test-worktree-native-preference.sh`、`test-worktree-path-policy.sh`，外加 `analyze-token-usage.py`（token 成本追踪）和 `test-helpers.sh`。
- `tests/opencode/`：6 个文件，含 `test-bootstrap-caching.mjs`（15 个回归用例）和 `setup.sh`。
- `tests/pi/test-pi-extension.mjs`：unit test 假装 Pi API，验证 lifecycle handlers 注册、bootstrap 单次注入、dedup guard、compaction re-injection。
- `tests/codex/`、`tests/codex-plugin-sync/`：测试 Codex marketplace manifest 和 `sync-to-codex-plugin.sh` 的 deterministic 输出。
- `tests/kimi/test-plugin-manifest.sh`：断言 manifest 字段完整。
- `tests/antigravity/`：测试 antigravity-tools.md 映射表存活（防止误删）。
- `tests/explicit-skill-requests/`：v4.0.3 引入（RELEASE-NOTES L740-L742），prompt 文件如 `please-use-brainstorming.txt`、`use-systematic-debugging.txt`、`i-know-what-sdd-means.txt`，验证用户明确说出 skill 名时模型仍会 invoke。
- `tests/brainstorm-server/`：brainstorm visual companion 的 HTTP/WebSocket/auth/lifecycle 单元测试。
- `tests/shell-lint/`、`tests/systematic-debugging/test-find-polluter.sh`：工具脚本测试。

### 6.2 pre-commit hooks

`.pre-commit-config.yaml`（22 行）只配置了 **evals 相关的 Python 检查**（`ruff check`、`ruff format --check`、`ty check`），文件路径限 `^evals/.*\.py$`。注意：`evals/` 是独立 submodule（v6.0.2 移除，RELEASE-NOTES L75），所以这个 pre-commit 只在 evals 被本地 clone 时才有效。

shell 脚本 lint 通过 `scripts/lint-shell.sh`（210 行）手动跑：

- 默认只 lint changed files（`git diff --name-only HEAD` + staged + untracked），`--all` 跑全量。
- 自动识别 shell 文件：`.sh` 后缀或 shebang 含 `bash`/`dash`/`ksh`/`sh`。
- `--format` 用 shfmt 格式化（`-i 2 -ci -bn`，2 空格缩进，case 缩进，binary ops 前连字符）。
- ShellCheck 用 `--severity=warning --external-sources --source-path=SCRIPTDIR`；`--strict` 加 `check-extra-masked-returns` 等额外检查。
- 还跑 `sh -n` / `bash -n` 语法检查。

### 6.3 版本同步 CI

`.version-bump.json`（21 行，`file:///tmp/superpowers-research/superpowers/.version-bump.json`）声明 7 处版本字段：

```json
{
  "files": [
    { "path": "package.json", "field": "version" },
    { "path": ".claude-plugin/plugin.json", "field": "version" },
    { "path": ".cursor-plugin/plugin.json", "field": "version" },
    { "path": ".codex-plugin/plugin.json", "field": "version" },
    { "path": ".kimi-plugin/plugin.json", "field": "version" },
    { "path": ".claude-plugin/marketplace.json", "field": "plugins.0.version" },
    { "path": "gemini-extension.json", "field": "version" }
  ],
  "audit": {
    "exclude": ["CHANGELOG.md", "RELEASE-NOTES.md", "node_modules", ".git", ".version-bump.json", "scripts/bump-version.sh"]
  }
}
```

`scripts/bump-version.sh`（220 行）提供三个子命令：

- `--check`：读所有 declared files，比对版本是否一致；不一致报告 drift。
- `--audit`：先 check，再 grep 整个仓库找包含当前版本字符串的"未声明"文件——防止漏登。
- `<new-version>`：用 `jq` 改写所有 declared files 的对应字段，然后跑 audit。

注意 **Pi 没有独立的 plugin.json**——它通过根 `package.json` 的 `pi` 字段声明，所以 `.version-bump.json` 中没有 Pi 专属条目（porting 文档 L729-L730：`pi declares itself in the repo-root package.json, which is already listed — there's nothing new to add`）。同理 OpenCode 也靠根 `package.json`。

### 6.4 Skill 行为测试（drill evals）

虽然 `evals/` submodule 已移出仓库（v6.0.2，RELEASE-NOTES L75），但 README L258-L259 与 CLAUDE.md L102-L104 仍记录：drill 在 [superpowers-evals](https://github.com/prime-radiant-inc/superpowers-evals/) 仓库，clone 到 `evals/` 后通过真实 tmux session 跑 Claude Code / Codex / Gemini CLI，用 LLM verifier 判定 skill compliance。

CLAUDE.md L94-L101 强调："Skills are not prose — they are code that shapes agent behavior."，任何 skill 修改必须在 PR 中带 before/after eval 结果。这是修改 SKILL.md 的最高门槛。

---

## 7. 借鉴清单总结

| 我们的组件 | 借鉴 Superpowers 的实现 | 借鉴方式 | 风险/差异 |
|---|---|---|---|
| 元认知流程层 SKILL.md 格式 | frontmatter 严格 `name`+`description` 两字段，description 只写触发条件不写流程（防 Description Trap，`writing-skills/SKILL.md` L150-L172） | 直接照搬格式 | 需配套校验脚本（仓库无现成 SKILL.md linter，靠 `writing-skills/SKILL.md` 文档约束 + 人工 review） |
| 不可绕过的流程 gate | `<HARD-GATE>` XML 标签 + Iron Law 代码块 + "Violating the letter is violating the spirit"（brainstorming L12-L14；test-driven-development L14, L31-L46；systematic-debugging L12-L20） | 三种形式按 gate 强度选用：HARD-GATE 最强、Iron Law 次之、Gate Function 用于前置自检 | LLM 是否真把 XML 标签当 gate 取决于训练；需要 eval 验证（仓库靠 drill evals 反复验证） |
| 反理性化防御 | "Common Rationalizations" 表 + "Red Flags - STOP" bullet list（test-driven-development L212-L244；systematic-debugging L244-L256；subagent-driven-development L425-L437） | 每条 excuse 配一句 reality 反驳；red flag 末尾用粗体总结 | 表格内容必须基于真实 baseline 测试得到的 rationalization，不能编（`writing-skills/SKILL.md` L518-L526 的 RED 阶段） |
| 流程图作为权威流程 | ``` ```dot ``` 代码块 + 终止态声明（`subagent-driven-development/SKILL.md` L47-L108） | 用 GraphViz dot 而非 mermaid；终止态用 `[shape=doublecircle]` 或 `[shape=box style=filled fillcolor=lightgreen]` | dot 不会被宿主原生渲染，需要 `render-graphs.js` 离线渲染；模型直接读 dot 文本作为流程契约 |
| 子代理 prompt 模板 | 独立 `.md` 文件，主 SKILL.md 用相对路径链接（`subagent-driven-development/SKILL.md` L232, L300, L345 引用 `implementer-prompt.md` 等） | 模板文件含 placeholder（`{DESCRIPTION}` 等），dispatch 时填充 | 模板演进需与 SKILL.md 同步，否则 dispatch 用过期模板（仓库无校验） |
| Skill 间衔接契约 | 末项 checklist 显式声明"invoke X skill"（brainstorming L32 → writing-plans；SDD L423 → finishing-a-development-branch） | 用 "REQUIRED SUB-SKILL: Use superpowers:X" 标记（`writing-skills/SKILL.md` L283-L286） | 衔接是单向声明，被调用方无义务反向确认；如果中间 skill 被跳过，整条链断 |
| SessionStart bootstrap 注入 | `<EXTREMELY_IMPORTANT>` wrapper + using-superpowers 全文（`hooks/session-start` L27；`.opencode/plugins/superpowers.js` L89-L97；`.pi/extensions/superpowers.ts` L65-L75） | 三种 shape 各有实现，但 wrapper 文本一致 | Shape A 注入含 frontmatter（verbatim cat）；Shape B/C strip frontmatter；不同 shape 注入内容**不完全一致** |
| 多宿主适配 | 三种 shape（shell-hook / in-process / instructions-file，porting 文档 L168-L298） | 我们的元认知层需在多种宿主（CLI/IDE/Agent）下加载，可参考 porting 决策树 | 每加一个宿主需独立 acceptance test（"make a react todo list" 必须 auto-trigger brainstorming，CLAUDE.md L78-L82） |
| Polyglot hook wrapper | `hooks/run-hook.cmd`（同一文件 batch + shell，L1-L46） | Mac/Linux `:` heredoc 跳过 batch；Windows batch 找 bash；找不到静默 exit 0 | 必须 extensionless（防 Claude Code Windows `.sh` 自动 prepend bash） |
| 版本同步 | `.version-bump.json` + `scripts/bump-version.sh`（7 处 declared fields + audit grep） | 维护一份"版本字段清单"，发版时一次性 jq 改写 | 新增宿主 manifest 必须登记进 `.version-bump.json`，否则版本漂移 |
| Codex 外部 fork 同步 | `scripts/sync-to-codex-plugin.sh`（466 行，EXCLUDES 锚定根目录防误匹配嵌套 `scripts/`） | rsync + git PR 自动化，deterministic（同 SHA 跑两次 PR diff 相同） | EXCLUDES 必须锚定 `/` 前缀（否则 `skills/brainstorming/scripts/` 会被 `scripts/` pattern 误剔除，脚本注释 L43-L44 明确警告） |
| Skill 行为测试 | drill evals（独立仓库，真实 tmux + LLM verifier） | 行为测试放仓库外、用真实宿主 session 跑 | 测试慢且贵，不能在 CI 频繁跑；prerequisite 是 drill harness setup |
| Bootstrap 字符串缓存 | module-level cache + null sentinel（`.opencode/plugins/superpowers.js` L53-L54, L62-L100；`.pi/extensions/superpowers.ts` L14） | 第一次 read+parse 后缓存，避免 per-step 重复 fs 调用 | 缓存生命周期 = session 生命周期；session 中途改 SKILL.md 不会重读 |
| Bootstrap dedup guard | 检查 `EXTREMELY_IMPORTANT` marker（OpenCode L133）或自定义 marker（pi `BOOTSTRAP_MARKER` L7） | lifecycle callback 可能 per-step 触发，必须 dedup | pi 用自定义 marker，OpenCode 用 `EXTREMELY_IMPORTANT`——后者更鲁棒（不需 harness 常量） |
| Compaction 后重注入 | `pi.on("session_compact")` set flag（`.pi/extensions/superpowers.ts` L27-L29）；OpenCode 靠 per-step re-inject + dedup | 形态 B 必须处理 compact；形态 A 靠 `matcher: "compact"` 触发；形态 C 不需要 | 不同 shape 策略不可互换（porting 文档 L810-L812 警告） |
| Tool mapping 双处维护 | pi inline `piToolMapping()` + `references/pi-tools.md`（porting 文档 L818-L819） | 避免单点失效 | 必须两处同步更新，否则模型读到的 mapping 与实际 dispatch 不一致 |
| 插件零依赖约束 | "Superpowers is a zero-dependency plugin by design."（CLAUDE.md L37-L38） | 拒绝任何运行时 npm 依赖；type-only import 可接受（pi 的 `ExtensionAPI`） | brainstorm server 因此重写为 zero-dep（v5.0.2，RELEASE-NOTES L357-L366） |
| Skill 写作元规范 | `writing-skills/SKILL.md`（677 行）+ `anthropic-best-practices.md` + `persuasion-principles.md` + `testing-skills-with-subagents.md` | 把"如何写 SKILL.md"本身做成一个 Skill，TDD 化（RED: baseline pressure test → GREEN: minimal skill → REFACTOR: close loopholes） | 写作规范演进需自身 TDD 验证；修改 writing-skills 本身需要更高门槛 |
| Micro-test wording 验证 | `writing-skills/SKILL.md` L576-L585：5+ reps per variant、always include no-guidance control、manually read every match、variance is a metric | 改 SKILL.md 措辞前先用 micro-test 验证不退化 | 比 drill eval 便宜，但不能替代压力测试 |
| Match the Form to the Failure | `writing-skills/SKILL.md` L459-L474：4 种 baseline failure 类型 → 4 种 guidance form（prohibition / recipe / structural / conditional） | 写 guidance 前先分类失败类型，避免 prohibition 用在 shaping 问题上（会 backfire） | 需 micro-test 数据支撑；prohibition 是默认倾向，需主动反向选择 |

---

## 8. 拉取 upstream 的操作建议

### 8.1 推荐：git subtree + 路径过滤

把 Superpowers 14 个 SKILL.md 作为 upstream base 拉进我们仓库，避免直接 fork 整个仓库（我们不需要 hooks/scripts/tests/docs 等）。

```bash
# 1. 添加 upstream（一次性）
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
git remote add superpowers-upstream https://github.com/obra/superpowers.git

# 2. 拉取 v6.2.0 tag 到 subtree 路径
git fetch superpowers-upstream v6.2.0
git subtree add --prefix=docs/superpowers/upstream/v6.2.0 superpowers-upstream/v6.2.0 --squash

# 3. 后续同步（升级时）
git subtree pull --prefix=docs/superpowers/upstream/v6.2.0 superpowers-upstream v6.3.0 --squash
# 解冲突后 commit
```

**优势**：

- 保留 upstream git 历史（`--squash` 压缩为单 commit，避免污染主分支历史）。
- 升级时能用 `git log docs/superpowers/upstream/v6.2.0/skills/` 看到 upstream 变更。
- 我们自己的 SKILL.md 修改在另一路径（如 `docs/superpowers/adapted/`），与 upstream 物理隔离，方便 rebase。

**风险**：

- `git subtree` 在大仓库下 merge 慢；可以考虑 sparse-checkout 替代（见 8.2）。
- `--squash` 丢失细粒度 commit 历史，排查 bug 时只能回到 upstream 仓库本身看。

### 8.2 替代：sparse-checkout + 同步脚本

如果只想要 `skills/` 子目录：

```bash
# 在独立工作树里 sparse-checkout
git clone --filter=blob:none --no-checkout https://github.com/obra/superpowers.git /tmp/superpowers-sparse
cd /tmp/superpowers-sparse
git sparse-checkout init --cone
git sparse-checkout set skills
git checkout v6.2.0

# rsync 到我们仓库
rsync -av --delete \
  --exclude='*.sh' --exclude='*.cjs' --exclude='*.js' --exclude='*.ts' --exclude='*.html' \
  /tmp/superpowers-sparse/skills/ \
  /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/docs/superpowers/upstream/v6.2.0/skills/

cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
git add docs/superpowers/upstream/v6.2.0/skills/
git commit -m "sync superpowers v6.2.0 skills (SKILL.md + reference .md only)"
```

**rsync EXCLUDES 启发自 Superpowers 自己的 `sync-to-codex-plugin.sh` L45-L81**：脚本注释明确警告 EXCLUDES 必须用 `/` 前缀锚定根目录，否则 `skills/brainstorming/scripts/` 会被 `scripts/` pattern 误剔除（L43-L44）。

### 8.3 只拉 SKILL.md（最小化方案）

如果只想跟 SKILL.md 本身，不要附带 .md / scripts：

```bash
# 用 find + cp
SRC=/tmp/superpowers-research/superpowers/skills
DST=/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/docs/superpowers/upstream/v6.2.0/skills
mkdir -p "$DST"
find "$SRC" -name SKILL.md -type f | while read -r f; do
  rel="${f#$SRC/}"
  mkdir -p "$DST/$(dirname "$rel")"
  cp "$f" "$DST/$rel"
done
```

注意：这样会丢失 `writing-good-tests.md`、`root-cause-tracing.md` 等 reference 文件，以及 `implementer-prompt.md` 等 dispatch 模板——而这些文件被 SKILL.md 用相对路径引用（如 `subagent-driven-development/SKILL.md` L232 `[implementer-prompt.md](implementer-prompt.md)`）。**不建议最小化方案**，会破坏 SKILL.md 的引用完整性。

### 8.4 推荐方案：完整 skills/ 子树 + 适配层

最终建议：

```
docs/superpowers/
├── upstream/
│   └── v6.2.0/
│       └── skills/                    # git subtree 拉 upstream 完整 skills/
│           ├── brainstorming/
│           │   ├── SKILL.md
│           │   ├── visual-companion.md
│           │   ├── spec-document-reviewer-prompt.md
│           │   └── scripts/          # 含 server.cjs 等
│           ├── test-driven-development/
│           │   ├── SKILL.md
│           │   └── writing-good-tests.md
│           └── ...
├── adapted/                           # 我们的适配版
│   └── skills/                        # 改造后的 SKILL.md（如换 tool mapping、调整流程）
├── patches/                           # upstream → adapted 的 patch 序列
│   ├── 01-rename-namespace.patch
│   └── 02-inject-our-bootstrap.patch
└── research/
    └── superpowers-v6.2.0-research.md  # 本报告
```

升级流程：

1. `git subtree pull` 拉新版本到 `upstream/v6.3.0/`。
2. 跑 `diff -r upstream/v6.2.0/skills upstream/v6.3.0/skills` 看变更。
3. 重新 apply `patches/` 到新版本生成 `adapted/`，失败则手动 rebase patch。
4. 跑我们的元认知流程层 evals 验证 adapted 行为不退化。

### 8.5 upstream 变更监控

建议订阅 [obra/superpowers](https://github.com/obra/superpowers) releases（RELEASE-NOTES.md 是单一权威变更日志，CLAUDE.md L260 提到"Removed vestigial CHANGELOG.md in favor of RELEASE-NOTES.md"）。重点关注：

- `RELEASE-NOTES.md` 顶部新版本段——尤其 "Skills" 子段（每个 Skill 的行为塑造内容变更都附 micro-test 证据，如 v6.2.0 L14-L19 的 TDD reference 重命名）。
- `skills/writing-skills/SKILL.md` 的修改——这是元规范，影响所有其他 SKILL.md 的写法。
- `skills/using-superpowers/SKILL.md` 的修改——这是 bootstrap 内容，影响所有宿主的注入。
- `hooks/session-start` 的修改——影响所有 Shape A 宿主的 bootstrap 字符串构造。
- `docs/porting-to-a-new-harness.md` 的修改——影响我们新增宿主适配的决策树。

### 8.6 不要直接改 upstream 文件

CLAUDE.md L42-L44 明确："PRs that restructure, reword, or reformat skills to 'comply' with Anthropic's skills documentation will not be accepted without extensive eval evidence."。同理，我们**不应**直接修改 upstream 拉进来的 SKILL.md，而应在 `adapted/` 层做转换：

- namespace 改写（`superpowers:brainstorming` → 我们的 namespace）
- tool mapping 替换（`Skill` tool → 我们的 skill loader）
- bootstrap wrapper 替换（`<EXTREMELY_IMPORTANT>` → 我们的 wrapper）
- 流程裁剪（如不需要 visual companion，删 brainstorming 的 Step 2）

转换用脚本化 patch 而非手工编辑，方便 upstream 升级时重新 apply。

---

## 附录 A：关键文件路径速查

| 用途 | 路径 |
|---|---|
| 14 个 SKILL.md 入口 | `file:///tmp/superpowers-research/superpowers/skills/*/SKILL.md` |
| Skill 写作元规范 | `file:///tmp/superpowers-research/superpowers/skills/writing-skills/SKILL.md` |
| Bootstrap 入口 skill | `file:///tmp/superpowers-research/superpowers/skills/using-superpowers/SKILL.md` |
| SessionStart hook 脚本 | `file:///tmp/superpowers-research/superpowers/hooks/session-start` |
| Polyglot wrapper | `file:///tmp/superpowers-research/superpowers/hooks/run-hook.cmd` |
| Claude hook 配置 | `file:///tmp/superpowers-research/superpowers/hooks/hooks.json` |
| Cursor hook 配置 | `file:///tmp/superpowers-research/superpowers/hooks/hooks-cursor.json` |
| OpenCode 插件 | `file:///tmp/superpowers-research/superpowers/.opencode/plugins/superpowers.js` |
| Pi 扩展 | `file:///tmp/superpowers-research/superpowers/.pi/extensions/superpowers.ts` |
| Gemini 入口 | `file:///tmp/superpowers-research/superpowers/GEMINI.md` + `gemini-extension.json` |
| 各宿主 manifest | `file:///tmp/superpowers-research/superpowers/.{claude,cursor,codex,kimi}-plugin/plugin.json` |
| 跨宿主 porting 指南 | `file:///tmp/superpowers-research/superpowers/docs/porting-to-a-new-harness.md` |
| 版本同步声明 | `file:///tmp/superpowers-research/superpowers/.version-bump.json` |
| 版本 bump 脚本 | `file:///tmp/superpowers-research/superpowers/scripts/bump-version.sh` |
| Codex fork 同步脚本 | `file:///tmp/superpowers-research/superpowers/scripts/sync-to-codex-plugin.sh` |
| Hook 测试 | `file:///tmp/superpowers-research/superpowers/tests/hooks/test-session-start.sh` |
| Shell lint | `file:///tmp/superpowers-research/superpowers/scripts/lint-shell.sh` |
| Release notes | `file:///tmp/superpowers-research/superpowers/RELEASE-NOTES.md` |
| 贡献者指南 | `file:///tmp/superpowers-research/superpowers/CLAUDE.md`（`AGENTS.md` 是其 symlink） |

## 附录 B：v6.2.0 关键变更摘要（与元认知流程层相关）

摘自 `file:///tmp/superpowers-research/superpowers/RELEASE-NOTES.md` L3-L34：

1. **SDD workspace plan-scoped**（L9）：`.superpowers/sdd/<plan-basename>/` 替代 flat `.superpowers/sdd/`；`sdd-workspace` 脚本要求 plan file 作为第一参数；ledger 第一行必须命名所属 plan；final review clean 后删除该 plan 的 workspace。
2. **SDD fix-loop resume implementer**（L10）：R1-R3 resume 原 implementer（而非 fresh dispatch）；新增 `re-review-prompt.md` 做 scoped re-review；5-round circuit breaker + controller adjudication。
3. **`testing-anti-patterns.md` → `writing-good-tests.md`**（L16）：从负面反模式目录改为正面规则目录；吸收 falsifiability discipline（name the break、derive expectations independently、mutation check）；明令禁止 string-presence trap 与 change-detector trap。
4. **TDD "Why Order Matters" 改为 rationalization 表行**（L17）：直接删除会退化 test-first 行为（control 8/10 → treatment 5/10，跨 Claude 与 Codex 验证），所以保留论点但移入 rationalization 表。
5. **`finishing-a-development-branch` 不再主动提供 discard**（L18）：discard 改为 explicit-request-only，需 typed-confirmation。
6. **Recap/persuasion prose 全库清理**（L19）：brainstorming、systematic-debugging、dispatching-parallel-agents、verification-before-completion、executing-plans、subagent-driven-development、requesting-code-review、receiving-code-review、using-git-worktrees、writing-plans、writing-skills 全部删除 Bottom Line / Key Principles / Real-World Impact / Advantages 段。
7. **SessionStart hook 通过 Git Bash dispatch**（L23）：`shell: "bash"` 解决 Windows 上 PowerShell ParserError 与 cmd.exe quote-stripping 问题。
8. **Gemini CLI 支持恢复**（L27）：v6.1.0 删除后恢复，等永久移除评估。
9. **`find-polluter.sh` 修复路径前缀 bug**（L31）：`find .` 输出 `./`-prefixed 路径，导致 `-path "src/**/*.test.ts"` 匹配不到，`wc -l` 空输入误报 "Found 1"。
10. **SDD skill test 不再 flake**（L33）：per-file timeout 提到 900s；assert 改为 case-insensitive；`assert_order` 失败时 dump output 便于诊断。

这些变更的共性：**每个行为塑造内容的修改都附带 micro-test 或 eval 证据**（"Each cut was micro-tested with subagent probes, and the one cut that measurably degraded behavior was reworked rather than shipped." L14）。这是我们借鉴 SKILL.md 时必须遵守的最高原则——任何 adapted 版本的修改都需配套 eval，不能凭"看起来更好"动刀。

---

**报告完。**
