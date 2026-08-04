# superpowers-evals 参考研究报告

> 研究目标：为"思维路径 A/B 评测系统"（设计节 7.4）借鉴 superpowers-evals 的 drill eval harness 测试方法论——"如何测试一个 Skill 是否真的让 AI 做得更好"。
>
> 研究对象：`/tmp/superpowers-research/superpowers-evals` 仓库（截至 2026-07-31 的 main 分支状态）。
>
> 核心结论：superpowers-evals 的活跃 harness 已从 "drill" 重命名为 **quorum**，"drill" 仅作为历史名残留在 `drill@test.local` commit identity、`DRILL_CODEX_HOME` 等标识符中（见 `file:///tmp/superpowers-research/superpowers-evals/docs/eval-harness-portfolio.md` 第 37 行）。下文以 quorum 称呼其方法论。

---

## 1. 仓库概览

### 1.1 定位

quorum 是 [superpowers](https://github.com/obra/superpowers) 的**行为评测实验室**，定位为"workflow compliance eval lab"——专门测试 Skill 是否真的塑造了 agent 的行为（skill triggering、worktree 行为、subagent 协同、验证反射、review 质量、cost-shaping），而**不是**通用 benchmark。

引自 `file:///tmp/superpowers-research/superpowers-evals/README.md` 第 11-13 行：

> This is not a generic benchmark suite. It is an eval lab for workflow
> compliance: skill triggering, worktree behavior, subagent coordination,
> verification reflexes, review quality, and cost-shaping patterns.

其评测对象是**真实 coding-agent CLI**——Claude、Codex、Antigravity、Gemini、Hermes、Kimi、OpenCode、Pi、Copilot 共 9 种，被驱动以 permissive 模式（如 `--dangerously-skip-permissions`）执行场景任务，然后由独立的 QA agent + 确定性 post-checks 双层判定（见 `file:///tmp/superpowers-research/superpowers-evals/README.md` 第 32-44 行）。

### 1.2 与 Superpowers 主仓的关系

- **子模块关系**：`superpowers-evals` 被父仓 `superpowers` 作为 `evals` 子模块消费（`file:///tmp/superpowers-research/superpowers-evals/README.md` 第 549-557 行）。
- **同步机制**：每次 PR 合入 `main` 后，需要针对父仓 `superpowers` 的 `dev` 分支开一个 follow-up PR，把 `evals` 子模块指针 bump 到新合并的 commit。**未完成该 bump 之前，合入不算"已传播"**。
- **依赖关系**（来自 `file:///tmp/superpowers-research/superpowers-evals/catalog-info.yaml` 与 `ABOUT.md`）：
  - **dependsOn**: `gauntlet`（通用 QA 框架，black-box tester，quorum 通过 spawn 调用其 CLI）
  - **evaluates**: `superpowers-private`（superpowers 是 SUT）
  - **External**: 9 个 coding-agent CLI
- **版本依赖**：`file:///tmp/superpowers-research/superpowers-evals/package.json` 第 9-11 行要求 `bun >= 1.3.13`；核心依赖为 `commander ^12`（CLI）、`zod ^3`（schema 边界）、`yaml ^2`（YAML 解析）、`@primeradianthq/obol ^0.8.0`（token 计价）。

### 1.3 核心价值（对我们评测系统的启发）

quorum 的核心方法论贡献有三点，全部可直接借鉴：

1. **三值裁决（three-valued verdict）**：`pass / fail / indeterminate`。`indeterminate` 专门用于"无法判定"——setup 崩溃、capture 为空、pre-check 失败等。这避免了把"harness 自己坏了"误报成"agent 没做好"。见 `file:///tmp/superpowers-research/superpowers-evals/src/contracts/verdict.ts` 第 4-20 行。
2. **双层独立作证（belt-and-braces）**：LLM 语义判定（Gauntlet-Agent 读 prose ACs）+ 确定性 bash 检查（`checks.sh`），两者**互不可见**，agreement 是强信号，disagreement 是 triage 信号。
3. **7 种失败归因图谱**：把 `fail` 拆成 Pattern 1-7，区分"真缺陷 judge 抓到 / 真缺陷 check 抓到 / 环境缺失 / broken check / capture 坏 / ..."，让 triage 不再是考古。见 `file:///tmp/superpowers-research/superpowers-evals/docs/superpowers/skills/triaging-a-failing-eval.md`。

### 1.4 顶层目录速览

```
superpowers-evals/
├── src/                    # quorum harness 主体（TS on Bun）
│   ├── cli/                # commander CLI: run/list/new/check/show/costs/run-all
│   ├── runner/             # 单次 run 编排（setup→pre→drive→capture→post→compose）
│   ├── checks/             # prelude.sh + checks.sh 加载与执行
│   ├── check/              # 类型化 check verb 分发（FS verbs + transcript verbs）
│   ├── contracts/          # zod schema: verdict/batch/economics/gauntlet/credential
│   ├── agents/             # 每个 coding-agent 的 provisioning 适配器
│   ├── normalize/          # 各 agent session-log → ATIF trajectory 归一化
│   ├── capture/            # session-log 快照/diff + tool-call/ token 捕获
│   ├── run-all/            # scenario × agent 矩阵批量执行
│   ├── scheduler/          # 并发调度（per-credential 限速）
│   ├── setup-helpers/      # fixture 构造器（create_base_repo 等）
│   ├── appliance/          # 共享远程 appliance helper
│   └── composer.ts         # 三值裁决算法
├── scenarios/              # 测试场景（一目录一场景，共 60+）
├── coding-agents/          # 每 agent 的 YAML 配置 + HOWTO/launch-agent
├── fixtures/               # 共享 fixture（template-repo）
├── packages/dashboard/     # 只读 web matrix UI（独立 workspace）
├── container/              # Docker runtime（Dockerfile + bin/quorum shim）
├── docs/                   # 设计文档、specs、plans、baselines、experiments
└── .github/workflows/      # CI（仅静态/单元测试）
```

---

## 2. drill eval harness 架构

> "drill" 是 quorum 的前身名（见 `file:///tmp/superpowers-research/superpowers-evals/docs/eval-harness-portfolio.md` 第 36-37 行），研究"如何测试一个 Skill 是否真的让 AI 做得更好"应聚焦 quorum 的 harness 架构。

### 2.1 核心组件

quorum 的核心是**四个 actor**的清晰分工（`file:///tmp/superpowers-research/superpowers-evals/README.md` 第 257-266 行）：

| Actor | 角色 | 文件位置 |
|---|---|---|
| **Gauntlet** | 通用 QA 框架（`gauntlet` CLI），black-box tester | 外部仓 `prime-radiant-inc/gauntlet` |
| **Gauntlet-Agent** | Gauntlet **内部**的 LLM，驱动 SUT 并对照 ACs 自评 | `<run>/gauntlet-agent/results/<runId>/run.jsonl` + `result.{json,md}` |
| **Coding-Agent** | 被测对象（SUT）：Claude/Codex/.../Copilot | `<run>/home/<config-subdir>/` + `<run>/coding-agent-workdir/` |
| **Quorum** | TS/Bun wrapper，负责 setup/适配/确定性 checks/最终裁决 | `src/` + `<run>/verdict.json` |

**关键设计原则**（来自 `file:///tmp/superpowers-research/superpowers-evals/docs/superpowers/specs/2026-05-22-harness-model-design.md` 第 71-104 行）：

- **P1**：Gauntlet 只做 act+assert（驱动 + 观测），Quorum 只做 arrange+adapt+consume（搭台 + 适配 + 消费）。Quorum **不重新判定**。
- **P2**：ACs 保持纯主观 prose，只让 Gauntlet-Agent 读，绝不为了机器可检而扭曲。
- **P3**：确定性 checks 是独立平行路径，是 outcome facts（"skill X fired"），不是任何 AC 的验证机制。
- **P5**：checks 是 bash 脚本调一组 `bin/` 工具——拒绝把声明式 YAML 扩展成"YAML 内嵌编程语言"的反模式。

### 2.2 测试流程

一次 `quorum run` 的端到端流水线在 `file:///tmp/superpowers-research/superpowers-evals/src/runner/index.ts` 第 1161-1951 行 `runInnerBody` 中实现，阶段顺序如下（每阶段写 `phase.json` 给 dashboard 探活）：

```
1. setup     写 phase=setup
   ├─ 校验 coding-agent yaml 存在 + 必需 env 已 export
   ├─ 加载 story.md frontmatter（quorum_max_time / quorum_tier）
   ├─ 校验 checks.sh 存在（否则短路 indeterminate）
   ├─ 解析 # coding-agents: 指令，若当前 agent 不在白名单 → 短路 indeterminate
   ├─ claude binary PATH 预检（fail-fast 而非深入 gauntlet 才报错）
   ├─ resolveAgent(cfg, os, credential) → 拿到 provisioning 适配器
   ├─ 创建 workdir + throwaway $HOME（<runDir>/home，含 XDG 子目录）
   ├─ agent.provision() → 往 throwaway home 注入 config + auth
   ├─ runSetup(setup.sh) → 用 BASH_ENV=prelude.sh 执行，构造 fixture
   └─ Windows: pushWorkdir 到 guest

2. pre-checks  写 phase 仍为 setup
   ├─ runPhase({phase:'pre', ...}) → source prelude.sh + checks.sh，调用 pre()
   ├─ pre 崩溃（rc≥126/127/≥128 或 signal）→ compose(indeterminate, stage=checks)
   └─ 任一 pre 失败 → compose(indeterminate, "pre-check(s) failed: ...")

3. agent      写 phase=agent
   ├─ resolveLaunchCwd(workdir) — 可被 setup.sh 写 .quorum-launch-cwd 改写
   ├─ snapshot session-log dir（pre-run 文件集，供 post-run diff）
   ├─ populateContextDir() — 把 HOWTO + launch-agent 拷进 <runDir>/gauntlet-agent/context/
   ├─ invokeGauntlet() — spawn gauntlet CLI（async，支持 SIGINT 转发）
   │    └─ gauntlet 内部启动 tmux → 跑 launch-agent → 驱动 coding-agent CLI
   ├─ gauntlet 退出后读 <runDir>/gauntlet-agent/results/<runId>/result.json
   └─ status ∈ {pass, fail, investigate}（errored/异常 → coerce 为 investigate）

4. capture    （仍 phase=agent）
   ├─ opencode/hermes: export 新 sessions 到文件（它们原本存 SQLite/内存）
   ├─ captureToolCallsWithRetry() — 最多 3 次重试 diff，吸收 flush race
   ├─ captureTokenUsage() — 通过 obol 计价，写 coding-agent-token-usage.json
   ├─ copilot: secret-leak 扫描 + expected/unexpected session-state 校验
   ├─ captureCascadeVerdict() — strict-capture 后端（claude/gemini/antigravity/...）
   │    若 sourceLogs=0 或 rowCount=0 → 短路 indeterminate（带 backend-specific 原因）
   └─ codex misplaced-rollout 检测（QA agent 是否忘了 cd $QUORUM_AGENT_CWD）

5. checks     写 phase=checks
   ├─ runPhase({phase:'post', transcriptPath: trajectory.json, ...})
   ├─ post 崩溃 → compose(indeterminate, stage=checks)
   └─ 收集 CheckRecord[]

6. compose    （仍 phase=checks）
   ├─ compose({gauntlet, checks, captureEmpty, error}) → FinalVerdict
   ├─ safeBuildRunEconomics() — 失败降级为 null，绝不破坏已 compose 的 verdict
   └─ 写 verdict.json（含 identity: scenario/agent/credential/os/labels/provenance）
```

退出码：`pass=0`、`fail=1`、`indeterminate=2`（`file:///tmp/superpowers-research/superpowers-evals/README.md` 第 419 行）。

### 2.3 数据流

```text
story.md ──┐
           ├─→ gauntlet CLI ──→ Gauntlet-Agent(LLM) ──┐
launch-agent┤                                          ├─→ result.json
context/   ┘                                          │   {status, summary, reasoning}
                                                     │
coding-agent CLI ──→ session-log(原始)               │
                  ↓                                  │
              normalize/*.ts ──→ ATIF Trajectory ──┐ │
                                  (trajectory.json) │ │
                                                    ↓ ↓
checks.sh ──→ prelude.sh ──→ check-tool.ts ──→ CheckRecord[] ──→ compose ──→ verdict.json
                              check-transcript.ts                  (三值裁决)
```

**关键归一化层**：每个 coding-agent 的 session-log 格式不同（claude `.jsonl`、codex rollout、pi session、kimi wire.jsonl、opencode sqlite export 等），全部归一化到统一的 **ATIF v1.7 Trajectory** 格式（`file:///tmp/superpowers-research/superpowers-evals/src/atif/types.ts` 第 1-73 行）。所有 transcript check verb 都基于 ATIF 的 `ToolCallView`（`{tool, args}` 视图）工作，**与具体 agent 解耦**——这是 quorum 能用同一套 checks.sh 跨 9 种 agent 的根本原因。

---

## 3. 测试用例定义格式

### 3.1 文件格式

quorum 的测试用例 = **一个目录** `scenarios/<name>/`，包含三个必需文件 + 可选附加（`file:///tmp/superpowers-research/superpowers-evals/docs/scenario-authoring.md` 第 12-19 行）：

| 文件 | 用途 | 可执行？ |
|---|---|---|
| `story.md` | 给 Gauntlet-Agent 的简报：扮演的角色、要发送的精确消息、停止条件、ACs | n/a |
| `setup.sh` | 构造 fixture（用 `$QUORUM_WORKDIR`），子进程执行 | **Yes**（`src/scaffold.ts` `fixExecutableBits`） |
| `checks.sh` | 定义 `pre()` 和 `post()` 函数，quorum 的确定性断言。**Sourced**，不执行 | **No**（quorum `source` 它） |
| `fixtures/`（可选） | per-scenario 静态/elicited 内容（plan.md/design.md 等） | — |
| `baseline-manifest.json`（可选） | content-addressed fixture 基线（SHA-256 + mode） | — |

**关键 exec-bit 不对称**（最常见 authoring trap）：`setup.sh` 通过 `spawnSync` 直接执行所以必须可执行；`checks.sh` 在 `bash -c` 里被 `source`（`src/checks/index.ts` `runPhase`），所以**必须不可执行**且只能含函数定义，任何 top-level 语句会被 `quorum check` 的 brace-depth 扫描拒绝。

### 3.2 字段规范

#### story.md frontmatter

`file:///tmp/superpowers-research/superpowers-evals/docs/scenario-authoring.md` 第 138-143 行定义可选 frontmatter：

| Key | 含义 | source of truth |
|---|---|---|
| `id` | 场景 id（必需） | `story-meta.ts` |
| `title` | 一行标题（必需） | `story-meta.ts` |
| `quorum_tier` | `sentinel` \| `full` \| `adhoc`，batch 过滤器（非行为开关） | `readQuorumTier`；`VALID_TIERS` in `src/scaffold.ts` |
| `quorum_max_time` | per-scenario 时长上限，如 `90m`、`30s`、`120`。Regex `^\d+(ms\|s\|m\|h)?$` | `readQuorumMaxTime` |
| `status` | 信息性，默认 `ready` | `readStoryStatus` |
| `tags` | 信息性 | — |

`quorum_tier` 三档语义（`file:///tmp/superpowers-research/superpowers-evals/docs/scenario-authoring.md` 第 145-154 行）：

- **`sentinel`**：快速高信号 smoke，每次 quick sweep 都跑（如单个 skill-auto-triggering check）。保持便宜且确定性。
- **`full`**（默认）：comprehensive suite 的一部分。
- **`adhoc`**：一次性实验，不希望被默认 `--tier full` 扫到，按名显式运行。

#### story.md body

**body 不是任务描述，而是给 QA agent 的 2nd-person 指令**（`file:///tmp/superpowers-research/superpowers-evals/docs/scenario-authoring.md` 第 156-203 行）：

- 告诉它扮演什么角色、要 type 的**精确消息**（"do not paraphrase, do not shorten"）、如何回答 follow-up、何时停止。
- Gauntlet-Agent 启动时**只看到 story**（`buildGauntletArgv` 只传 story 路径，`checks.sh` 不在命令行），所以 ACs 必须在 prose 里。
- **Fence every Gauntlet-Agent turn**：给精确的开场白、canned 中性回复、显式禁止项（"Do NOT mention SQL injection"）。未约束的 grader 会污染实验。
- **Run-completeness vs grade-completeness 分开**：明确何时停止 driving，独立于 pass/fail。否则 grader 会一直 prod 直到拿到 ACs 想要的答案。
- **elicited-fixture 方法论**：skill-execution 场景的 plan 应该用被测 skill 生成，不要手写。手写 prose plan 比真实 `writing-plans` 输出贵 ~2× 并虚高 baseline（methodology correction, `docs/experiments/2026-06-10-sdd-cost-experiments.md`）。

#### Acceptance Criteria

ACs 由 LLM **语义评分**（`file:///tmp/superpowers-research/superpowers-evals/docs/scenario-authoring.md` 第 166-184 行）：

- **命名精确证据** + 文件路径（如 "a `Skill` invocation naming `superpowers:requesting-code-review` appears in the session log"）。
- **允许合法 harness 变体**：Claude 用 native `Skill` call，Codex 用 shell grep `SKILL.md`。只认 native form 的 AC 会 false-fail Codex。
- **Pin ordering** where it matters——"before any implementation `Edit`/`Write`"。
- **关闭 rationalization 逃生舱**：禁止 "looks good" / "ready to merge" approval；设 severity floor（"Critical or Important, not Minor"）。
- **区分 partial pass**——让 grader 能给"修了 bug 但忽略 pushback"打正确分。

#### checks.sh 字段

`checks.sh` 只含两个函数：`pre()` 和 `post()`（`file:///tmp/superpowers-research/superpowers-evals/docs/scenario-authoring.md` 第 394-404 行）：

- **`pre()`** 在 setup.sh 后、Coding-Agent 前。断言 fixture 正是场景假设的样子。失败 → `indeterminate`（fixture 错了，run 不可解释）。崩溃 → `indeterminate`，stage=checks。
- **`post()`** 在 capture 后。断言 outcome。失败 → `fail`。崩溃 → `indeterminate`。
- quorum 对两阶段 source 同一个 `checks.sh`，分别调用 `pre` 和 `post`。

可用环境变量（`file:///tmp/superpowers-research/superpowers-evals/docs/scenario-authoring.md` 第 534-548 行）：

| Var | 何时 | 用途 |
|---|---|---|
| `QUORUM_REPO_ROOT` | always | prelude 从这里解析 dispatcher |
| `QUORUM_RECORD_SINK` | always | record 写入的 jsonl 文件 |
| `QUORUM_AGENT_CONFIG_DIR` | always | Coding-Agent 的隔离 config dir |
| `QUORUM_TRANSCRIPT_PATH` | **post only** | 捕获的 `trajectory.json` |
| `QUORUM_RUN_DIR` | **post only** | run dir，读 sibling artifact |
| `QUORUM_CODING_AGENT` | always | agent config 名，per-agent dispatch |
| `$QUORUM_WORKDIR` | **never in checks.sh** | checks 的 cwd 就是 workdir，用相对路径 |

#### # coding-agents: 指令

`checks.sh` 前 21 行的注释 `# coding-agents: claude,codex` 限制场景只跑列出的 agent（`file:///tmp/superpowers-research/superpowers-evals/docs/scenario-authoring.md` 第 374-380 行）：

- 匹配但空（`# coding-agents: ,`）→ 跳过所有 agent。
- 真缺失（无匹配行）→ 不 gate，全部 agent 可跑。

### 3.3 实际示例（带代码引用）

#### 示例 1：Skill auto-triggering（最小 smoke）

`scenarios/triggering-test-driven-development/`（`file:///tmp/superpowers-research/superpowers-evals/scenarios/triggering-test-driven-development/`）：

**story.md**（`file:///tmp/superpowers-research/superpowers-evals/scenarios/triggering-test-driven-development/story.md`）：

```yaml
---
id: triggering-test-driven-development
title: Agent loads test-driven-development skill before implementing a small feature
status: ready
tags: skill-triggering
quorum_tier: sentinel
---
```

body 关键片段（第 9-24 行）：

> You are an engineer asking the agent under test to add a small,
> testable feature (email validation). Once it has loaded a skill or
> started writing tests/code, you are done.
>
> When the agent is ready for input, type this exact message and press
> Enter — do not paraphrase, do not shorten:
>
> "I need to add a new feature to validate email addresses. It should: ..."
>
> Do not mention TDD, tests-first, or any superpowers concept.

**setup.sh**（`file:///tmp/superpowers-research/superpowers-evals/scenarios/triggering-test-driven-development/setup.sh`）：

```bash
#!/usr/bin/env bash
set -euo pipefail
setup-helpers run create_base_repo
```

**checks.sh**（`file:///tmp/superpowers-research/superpowers-evals/scenarios/triggering-test-driven-development/checks.sh`）：

```bash
pre() {
    git-repo
    git-branch main
}

post() {
    check-transcript skill-called superpowers:test-driven-development
    check-transcript skill-before-implementation-tool superpowers:test-driven-development Edit
    check-transcript skill-before-implementation-tool superpowers:test-driven-development Write
}
```

设计要点：
- story 故意不提 TDD/superpowers，测的是 skill **自动触发**。
- `skill-called` 是 positive anchor（承载判定重量）。
- 两个 `skill-before-implementation-tool` 是 **vacuous-pass**：若 agent 从未 edit/write 实现文件则 vacuously true。positive check 才是判定主体。

#### 示例 2：Judgment / quality（planted bugs）

`scenarios/code-review-catches-planted-bugs/`（`file:///tmp/superpowers-research/superpowers-evals/scenarios/code-review-catches-planted-bugs/`）：

**checks.sh**（`file:///tmp/superpowers-research/superpowers-evals/scenarios/code-review-catches-planted-bugs/checks.sh`）：

```bash
pre() {
    git-repo
    git-branch main
    git-count commits eq 2
    file-exists 'src/db.js'
    file-contains src/db.js '\+ email \+'
    file-contains src/db.js 'function hash\(s\) \{[[:space:]]*return s'
}

post() {
    check-transcript skill-called superpowers:requesting-code-review
    check-transcript tool-called Agent
}
```

设计要点（`file:///tmp/superpowers-research/superpowers-evals/docs/scenario-authoring.md` 第 693-720 行）：
- spec-aware story 显式命名 `superpowers:requesting-code-review`，所以测的是 **review quality** 而非触发。
- `pre()` 断言 planted fixture（SQL 注入 + identity hash）就位后再评分。
- 难判的 judgment criteria（severity floor、"did not approve for merge"）放 **AC prose** 给 Gauntlet-Agent；`checks.sh` 只确认 skill fired + reviewer subagent dispatched。
- `receiving-code-review-pushback` 是配套 judgment scenario，叠加 `check-transcript investigated` + 多个 `not file-contains` / `not file-exists` 断言 agent 拒绝了 bad suggestions。

#### 示例 3：Belt-and-braces deliverable

`scenarios/sdd-go-fractals-opus48/`（`file:///tmp/superpowers-research/superpowers-evals/scenarios/sdd-go-fractals-opus48/`）：

**story.md frontmatter**（第 1-7 行）：

```yaml
---
id: sdd-go-fractals-opus48
title: Agent executes an Opus 4.8-authored Go fractals plan end-to-end via subagent-driven-development
status: ready
tags: subagent-driven-development
quorum_max_time: 90m
---
```

**checks.sh**（`file:///tmp/superpowers-research/superpowers-evals/docs/scenario-authoring.md` 第 748-756 行）：

```bash
post() {
    check-transcript skill-called superpowers:subagent-driven-development
    check-transcript tool-called Agent
    file-exists '**/*_test.go'
    command-succeeds 'go test ./...'
    file-exists 'cmd/fractals/main.go'
    git-count commits gte 4
}
```

设计要点：
- `requires-tool go` 在 `pre()` 里——无 Go 的机器 → `indeterminate`（环境缺失），而非 `fail`（假阴性）。
- AC prose 用文字断言同样事实，Gauntlet-Agent 和确定性 check **互相印证**。disagreement 是 triage 信号。
- `quorum_max_time: 90m` 标明长 run（真实 plan 执行可能 60-90 分钟）。

#### 示例 4：User preference override（HARD-GATE 风格）

`scenarios/user-pref-no-tdd/`（`file:///tmp/superpowers-research/superpowers-evals/scenarios/user-pref-no-tdd/`）：

**checks.sh**（`file:///tmp/superpowers-research/superpowers-evals/scenarios/user-pref-no-tdd/checks.sh`）：

```bash
# coding-agents: claude,codex,gemini,kimi
# A user preference ("don't use TDD") must suppress the test-driven-development
# skill. Restricted to agents with a verified ambient-instructions file.
# Control = the existing triggering-test-driven-development scenario.

pre() {
    git-repo
    git-branch main
}

post() {
    check-transcript skill-not-called superpowers:test-driven-development
}
```

设计要点：
- `# coding-agents:` 指令限制只跑有 ambient-instructions 文件的 4 个 agent。
- `skill-not-called` 是**负向 check**——空 capture → FAIL（防止"什么都没捕获"虚晃过关）。
- 注释明确指出 control 是 `triggering-test-driven-development`——**calibration pair** 思路：同一 skill，对照组测该触发，实验组测该被抑制。

#### 示例 5：Calibration pair（cost 场景）

`scenarios/brainstorming-resists-jump-to-implementation/` 与 `scenarios/cost-checkbox-over-trigger/` 共享相同 fixture，从两侧 bracket 行为（`file:///tmp/superpowers-research/superpowers-evals/scenarios/brainstorming-resists-jump-to-implementation/story.md` 第 45-47 行）：

> Calibration note: this is the design-worthy half of a calibration pair
> with cost-checkbox-over-trigger (identical fixture; the trivial
> checkbox request must NOT trigger brainstorming there, this open-ended
> request MUST trigger it here).

Cost 场景的 AC 认证 **comparability**（"a real, runnable deliverable that exercises the same surface"），不是 dollar 阈值——token economics 保管价格，AC 保持比较两臂诚实。

---

## 4. 评分标准与算法

### 4.1 评分维度

quorum 的"评分"不是单一分数，而是**三层独立证据的合成**：

1. **Gauntlet-Agent 判定**（语义层）：读 story prose ACs，观察 run，自评 `pass / fail / investigate / errored`。输出 `result.json`：`{status, summary, reasoning, run_id}`。
2. **确定性 checks**（deterministic 层）：`pre()` + `post()` 函数调 bare-verb DSL，每 verb 发一条 `CheckRecord`：`{check, args, negated, passed, detail, phase}`。
3. **Capture 健康**（infrastructure 层）：`captureEmpty`（trajectory 是否为 0 行）、source logs 是否存在、misplaced-session 检测等。

#### 三值裁决的语义（`file:///tmp/superpowers-research/superpowers-evals/README.md` 第 411-419 行）

- `pass`：Gauntlet-Agent pass **AND** 所有 post-check pass。
- `fail`：Gauntlet-Agent fail，或某 post-check fail。
- `indeterminate`：setup/pre-check/capture/quorum 失败，Gauntlet `investigate`，或空 trace 时存在 trace check。

退出码：`pass=0`、`fail=1`、`indeterminate=2`。

#### 评分"维度"清单

虽然 quorum 不输出单一分数，但从 verb 词汇和 AC 模式可归纳出以下评分维度：

| 维度 | 对应 verb / 检查 | 示例场景 |
|---|---|---|
| **Skill 触发率** | `skill-called` / `skill-not-called` | triggering-* |
| **Skill 顺序正确性** | `skill-before-tool` / `skill-before-implementation-tool` / `tool-before` | TDD、brainstorming-before-code |
| **Skill 抑制（user pref）** | `skill-not-called` + `# coding-agents:` gate | user-pref-no-* |
| **Subagent dispatch** | `tool-called Agent` + AC 角色命名 | SDD、code-review |
| **工作树/worktree 行为** | `git-count worktrees` / `worktree-created` / `git-branch` | finishing-branch-*、worktree-* |
| **实现交付质量** | `command-succeeds 'go test ./...'` / `file-exists` / `git-count commits gte N` | sdd-go-fractals-* |
| **Investigation 反射** | `investigated`（native Read/Grep 或 shell grep/rg） | receiving-code-review-pushback |
| **Cost 效率** | economics block（token usage + est_cost_usd + duration_ms） + AC comparability | cost-* |
| **Fixture 完整性** | `baseline-manifest`（SHA-256 + mode） | serf-builder-fractals |

### 4.2 评分算法实现

裁决算法在 `file:///tmp/superpowers-research/superpowers-evals/src/composer.ts` 第 42-112 行 `compose()` 函数，是**优先级 precedence**而非投票（第一个匹配赢）：

```typescript
export function compose({ gauntlet, checks, captureEmpty, error }: ComposeArgs): FinalVerdict {
  const base = { schema: 1 as const, gauntlet, checks, economics: null };

  // 1. 任何 error → indeterminate（stage ∈ setup|gauntlet|capture|checks|compose|qa-agent-misconfigured|stopped|unknown）
  if (error) {
    return { ...base, final: 'indeterminate',
      final_reason: `quorum error (${error.stage}): ${error.message}`, error };
  }

  // 2. 任一 pre-check 失败 → indeterminate（fixture 错，gauntlet 可能仍 pass）
  const failedPre = checks.filter((c) => c.phase === 'pre' && !c.passed);
  if (failedPre.length) {
    return { ...base, final: 'indeterminate',
      final_reason: `pre-check(s) failed: ${failedPre.map((c) => c.check).join(', ')}`, error: null };
  }

  // 3. 无 Gauntlet verdict → indeterminate
  if (!gauntlet) {
    return { ...base, final: 'indeterminate', final_reason: 'no Gauntlet-Agent verdict', error: null };
  }

  // 4. Gauntlet investigate/errored → indeterminate
  if (gauntlet.status === 'investigate' || gauntlet.status === 'errored') {
    return { ...base, final: 'indeterminate',
      final_reason: `Gauntlet-Agent did not complete (status: ${gauntlet.status})`, error: null };
  }

  // 5. 空 capture + 存在 trace check → indeterminate（trace check 无意义）
  if (captureEmpty && checks.some((c) => TRACE_PRIMITIVES.has(c.check))) {
    return { ...base, final: 'indeterminate',
      final_reason: 'tool-call capture was empty; trace checks meaningless', error: null };
  }

  // 6. Gauntlet pass + 零 post 失败 → pass
  const failedPost = checks.filter((c) => c.phase === 'post' && !c.passed);
  if (gauntlet.status === 'pass' && failedPost.length === 0) {
    const n = checks.filter((c) => c.phase === 'post').length;
    const reason = n ? `Gauntlet-Agent passed; ${n} post-check(s) passed`
                     : 'Gauntlet-Agent passed; no deterministic checks';
    return { ...base, final: 'pass', final_reason: reason, error: null };
  }

  // 7. 否则 → fail
  const bits: string[] = [];
  if (gauntlet.status !== 'pass') bits.push(`Gauntlet-Agent reported ${gauntlet.status}`);
  if (failedPost.length) bits.push(`${failedPost.length} post-check(s) failed`);
  return { ...base, final: 'fail', final_reason: bits.join('; ') || 'fail', error: null };
}
```

`TRACE_PRIMITIVES` 集合（`file:///tmp/superpowers-research/superpowers-evals/src/composer.ts` 第 8-33 行）列举所有 transcript check verb 名——空 capture 时这些 check 无意义，强制 indeterminate。

#### 关键设计：127 crash band

check verb 退出码三档（`file:///tmp/superpowers-research/superpowers-evals/docs/scenario-authoring.md` 第 510-519 行）：

| Exit | 含义 | 可被 `not` 反转？ |
|---|---|---|
| `0` | check passed | — |
| `1` | check 断言失败 | yes |
| `127` | **broken check**：用法错误、未知 verb、缺必需 arg、未知 op、tool 抛错 | **no**——故意落在 `not` 的 crash band |

`runPhase` 的 phase 级 crash 判定（`file:///tmp/superpowers-research/superpowers-evals/src/checks/index.ts` 第 175-188 行）：

- rc 0 → ok
- rc 126/127/≥128 → crash
- rc 1..125 → ok **iff** ≥1 record emitted, else crash
- signal-kill → **always** crash, even with partial records

crashed phase → `indeterminate`，stage=checks，**绝不**是 `fail`。这是关键：typo'd 或 under-specified check 不能虚晃成 pass 或被 `not` 反转成 silent pass。

#### `not` 的三条 load-bearing 规则

`file:///tmp/superpowers-research/superpowers-evals/src/check/dispatch.ts` 第 173-229 行 `negate()`：

1. 正常 inner pass/fail → 发**一条** record on behalf of inner（`check=<inner>`, `negated:true`, `passed` 反转）。
2. **拒绝反转 missing inner verb**——record 一条 FAIL under `not`，exit 1（honest failed check，非 127）。
3. **拒绝反转 crash**（inner broken 或 threw）——同 rule 2。

所以 `not <typo>` 和 `not <broken-check>` 诚实失败而非 vacuous pass。

### 4.3 baseline 对比机制

quorum 的"baseline 对比"有四种形态：

#### 形态 1：内容寻址 fixture 基线（`baseline-manifest.json`）

`file:///tmp/superpowers-research/superpowers-evals/docs/scenario-authoring.md` 第 319-348 行：当场景必须证明每个付费 cell 从相同 frozen 输入开始，加 `baseline-manifest.json`。Schema v1 列出 `fixtures/` 下所有文件 + Git mode + SHA-256。两处使用同一 manifest：

- `quorum check` 比对 checked-in `fixtures/` 树。
- `pre()` 里放 `baseline-manifest` verb，比对 setup-helpers 播种后的 worktree。

#### 形态 2：Calibration pair（行为对照）

两个场景共享 fixture，从两侧 bracket 行为：
- `brainstorming-resists-jump-to-implementation`（design-worthy → **必须** 触发 brainstorming）
- `cost-checkbox-over-trigger`（trivial checkbox → **必须不** 触发 brainstorming）

两者一起 bracket behavior，校准"何时该/不该触发"。

#### 形态 3：历史 baseline 文档（`docs/baselines/`）

`file:///tmp/superpowers-research/superpowers-evals/docs/baselines/2026-06-09.md` 是典型 baseline 报告：

- 头条：`40 ✓ · 8 ✗ · 2 ⊘ · 22 —`（36 scenarios × 2 backends）
- Matrix 表格：每行 scenario，每列 backend，cell 用 `✓ ✗ ⊘ —`（— 表示 skip）。
- 分桶归因：Bucket A（infra 噪声）/ Bucket B（real agent signal）/ Bucket C（待判定）。
- Net delta from 05-29：结构化对比上次 baseline。
- Action items 表格。

#### 形态 4：run-all matrix + costs 报告

`quorum run-all` 跑 scenario × agent × credential 矩阵，输出 `results/batches/<batch-id>/`：

- `batch.json`（header: id/started_at/finished_at/coding_agents/jobs）
- `results.jsonl`（每 cell 一行 compact record）
- `credentials.snapshot.yaml`（不可变 credential 快照，编辑源 YAML 不能改变已启动 batch 的后续 cell）

`quorum show <batch-id>` 渲染 matrix view（`file:///tmp/superpowers-research/superpowers-evals/src/cli/render-batch.ts` 第 26-32 行的五 glyph：`✓ ✗ ⊘ — ?`）。
`quorum costs <batch-id>` 输出 cost 表（默认只算 coding-agent 侧，`--with-gauntlet` 加 harness 开销）。仅 final `pass` 行标记为 comparable；`fail`/`indeterminate` 可见但不排名。

#### 形态 5：micro-test 控制臂

`file:///tmp/superpowers-research/superpowers-evals/docs/superpowers/skills/micro-testing-prompt-guidance.md` 第 30-37 行：微测试必须包含 no-guidance control——只有这样才能区分"prohibition 有效"（control 违反、prohibition 不违反）vs"prohibition 适得其反"（control 评分**更好**）vs"场景无法诱导该行为"（全 0，inconclusive）。

---

## 5. CI 集成

### 5.1 pre-commit hooks

**仓库未使用 `.pre-commit-config.yaml`**（Glob 搜索 `.pre-commit-config*` 无结果）。质量门控由 `bun run check` 单一命令承担（`file:///tmp/superpowers-research/superpowers-evals/package.json` 第 24 行）：

```json
"check": "biome ci . && tsc --noEmit && bun test test/ && cd packages/dashboard && bun run check"
```

包含：
1. `biome ci .`：lint + format 检查（biome 配置见 `file:///tmp/superpowers-research/superpowers-evals/biome.json`，含 `noExplicitAny`、`noEvolvingTypes`、`noConsole`、`noNonNullAssertion`、`noProcessEnv`、`noDefaultExport`、`useImportType`、`noFloatingPromises` 等严格规则）。
2. `tsc --noEmit`：TypeScript 严格类型检查。
3. `bun test test/`：单元测试套件。
4. `cd packages/dashboard && bun run check`：dashboard workspace 独立检查。

`src/env.ts` 是唯一允许读 `process.env` 的模块（biome 的 `noProcessEnv` 规则全局禁用，仅此处 override），所有其他模块通过 `getEnv()` seam 间接访问——便于单测注入 fake。

### 5.2 CI 配置

`file:///tmp/superpowers-research/superpowers-evals/.github/workflows/test.yml` 是唯一的 GitHub Actions workflow：

```yaml
name: test
on:
  pull_request:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  ts:
    name: ts
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - name: Checkout repository
        run: |
          set -euo pipefail
          git init "$GITHUB_WORKSPACE/repo"
          cd "$GITHUB_WORKSPACE/repo"
          git remote add origin "https://github.com/${GITHUB_REPOSITORY}.git"
          git fetch --depth=1 origin "${GITHUB_SHA}"
          git checkout --detach FETCH_HEAD
      - name: Install Bun
        run: |
          set -euo pipefail
          curl -fsSL https://bun.sh/install | bash -s "bun-v1.3.14"
          echo "$HOME/.bun/bin" >> "$GITHUB_PATH"
      - name: Install dependencies
        working-directory: ${{ github.workspace }}/repo
        run: bun install --frozen-lockfile
      - name: Check (biome + tsc + buntest)
        working-directory: ${{ github.workspace }}/repo
        run: bun run check
      - name: quorum scenario check
        working-directory: ${{ github.workspace }}/repo
        run: bun run quorum check
```

**关键安全边界**（`file:///tmp/superpowers-research/superpowers-evals/README.md` 第 15-29 行）：

- **静态/单元检查**：CI 安全，跑 `biome` + `tsc` + `bun test`，不调 model API，不启 agent CLI。
- **Live evals**：trusted-maintainer 操作，启 Claude Code/Codex/... 在 permissive 模式，收集 raw transcripts/tool calls/filesystem state/session logs。

**公网 CI 必须留在静态/单元侧**——绝不加 API key、live `quorum run` 调用、dangerous-mode agent 启动到公网 CI。这是 quorum 的核心安全模型。

### 5.3 运行脚本

仓库**没有顶层 `scripts/` 目录**（Glob 搜索 `scripts/*` 无结果）。运行脚本分散在：

- **`bun run quorum <cmd>`**：唯一 CLI 入口（`file:///tmp/superpowers-research/superpowers-evals/package.json` 第 16 行 `"quorum": "bun run src/cli/index.ts"`）。
- **`scripts/evals-container`**：Docker 容器 runtime wrapper（README 第 165-172 行调用，但脚本本身可能在仓库外或被 gitignore）。
- **`container/bin/quorum`**：容器内 shim（`file:///tmp/superpowers-research/superpowers-evals/container/bin/quorum`）。
- **`container/bin/evals-tool-versions`**：容器内工具版本探针。
- **`evals-appliance`**：另一个 bin（`file:///tmp/superpowers-research/superpowers-evals/package.json` 第 7 行），共享 appliance CLI。

核心命令清单（`file:///tmp/superpowers-research/superpowers-evals/README.md` 第 394-404 行）：

```bash
bun run quorum list                                          # 列场景
bun run quorum new my-new-scenario                           # 脚手架新场景
bun run quorum check my-new-scenario                         # 静态校验场景
bun run quorum run scenarios/<name> --coding-agent <agent>   # 单跑
bun run quorum run scenarios/<name> --coding-agent claude --credential sonnet
bun run quorum run-all --coding-agents claude,codex --jobs 2 # 矩阵批跑
bun run quorum run-all --coding-agents claude --credentials sonnet,haiku --jobs 2
bun run quorum show <run-or-batch-id>                        # 查 verdict/matrix
bun run quorum costs <run-or-batch-id>                       # 查成本
```

`quorum check` 无参数校验所有场景 + `credentials.yaml`；`run-all` 跑每个场景对每个 selected Coding-Agent，按场景的 `# coding-agents:` 指令过滤。

---

## 6. 测试结果输出

### 6.1 报告格式

#### 单次 run 产物

每个 run 产生一个目录 `results/<scenario>-<agent>-<credential>-<os>-<stamp>-<nonce>/`（`file:///tmp/superpowers-research/superpowers-evals/README.md` 第 421-434 行）：

```
results/<scenario>-<coding-agent>-<os>-<timestamp>-<nonce>/
├── verdict.json                     # 组合裁决（先读这个）
├── gauntlet-agent/                  # Gauntlet-Agent 证据
│   └── results/<runId>/
│       ├── run.jsonl                # 事件流
│       └── result.{json,md}         # 判定
├── coding-agent-workdir/            # Coding-Agent 产出的文件
├── home/                            # throwaway Coding-Agent HOME（含 config + session log）
├── trajectory.json                  # 归一化的 ATIF trace
├── coding-agent-token-usage.json    # Coding-Agent token cost（可计价时）
├── credentials.snapshot.yaml        # 不可变 credential 快照
└── phase.json                       # 当前 phase + pid（dashboard 探活）
```

`results/` 被 gitignore（`file:///tmp/superpowers-research/superpowers-evals/.gitignore` 第 1 行），因为 run artifact 可能含敏感 transcripts/credentials/tool calls/filesystem state。

#### verdict.json schema

`file:///tmp/superpowers-research/superpowers-evals/src/contracts/verdict.ts` 第 53-82 行 `FinalVerdictSchema`：

```typescript
export const FinalVerdictSchema = z.object({
  schema: z.literal(1),
  final: z.enum(['pass', 'fail', 'indeterminate']),
  final_reason: z.string(),
  gauntlet: GauntletLayerSchema.nullable(),       // {status, summary, reasoning, run_id}
  checks: z.array(CheckRecordSchema),             // [{check, args, negated, passed, detail, phase}]
  error: RunErrorSchema.nullable(),               // {stage, message}
  economics: z.record(z.unknown()).nullable(),    // 不透明 economics block
  // Self-identity（dashboard 读侧）：
  scenario: z.string().optional(),
  coding_agent: z.string().optional(),
  started_at: z.string().optional(),
  finished_at: z.string().optional(),
  credential: z.string().optional(),
  os: z.string().optional(),
  labels: CredentialLabelsSchema.optional(),
  // Provenance（PRI-2494）：
  provenance: z.object({
    superpowers_rev: z.string().nullable(),
    superpowers_dirty: z.boolean().nullable(),
    harness_rev: z.string().nullable(),
    agent_cli_version: z.string().nullable(),
    gauntlet_version: z.string().nullable(),
  }).optional(),
});
```

每条 `CheckRecord`（`file:///tmp/superpowers-research/superpowers-evals/src/contracts/verdict.ts` 第 28-36 行）：

```typescript
{
  check: string,        // 子 verb 名（如 "skill-called"），绝非 wrapper "check-transcript"
  args: string[],       // 调用参数
  negated: boolean,     // 是否经 not 反转
  passed: boolean,
  detail: string | null,// 空 string 归一化为 null
  phase: 'pre' | 'post',
}
```

#### 批次产物

`results/batches/<batch-id>/`（`file:///tmp/superpowers-research/superpowers-evals/src/run-all/batch-index.ts`）：

- `batch.json`：header `{schema_version:1, id, started_at, finished_at, coding_agents, jobs}`（indent-2，**无 trailing newline**，是契约）。
- `results.jsonl`：每 cell 一行 compact record，`{scenario, coding_agent, run_id, credential?, labels?, skipped?}`（`skipped` 为 null 时省略，是契约）。
- `credentials.snapshot.yaml`：batch 启动前 freeze 的 credential 配置。

#### 命令行渲染

- `quorum show`（`file:///tmp/superpowers-research/superpowers-evals/src/cli/render.ts`）：单 run verdict 渲染，Dracula 色板（pass 绿 `#50fa7b`、fail 红 `#ff5555`、indeterminate 黄 `#f1fa8c`），no-color 文本是稳定契约。
- `quorum show <batch-id>`（`file:///tmp/superpowers-research/superpowers-evals/src/cli/render-batch.ts`）：matrix view，5 glyph `✓ ✗ ⊘ — ?`，Legend 行 + tally 字符串也是 triage-output 契约。
- `quorum costs`（`file:///tmp/superpowers-research/superpowers-evals/src/cli/costs.ts`）：CODING-AGENT 侧成本表，tolerant view（每 leaf `unknown`，malformed economics 降级为 "unpriced" 而非崩溃）。

### 6.2 版本对比

#### Dashboard（可视化）

`file:///tmp/superpowers-research/superpowers-evals/packages/dashboard/` 是独立 workspace，**零依赖** harness `src/`：

- `scan.ts`：读 `results/` 把 run 分桶到 cell，resolve 每个 cell 的 window/liveness/verdict。filesystem 是唯一真相源；只有不可变 verdict 缓存（present parse 缓存，absence 不缓存——防 live dir 被钉死为 verdict-less）。
- `view.ts` + `templates.ts`：typed HTML 渲染器，`cellHtml` 是 first paint + SSE swap 的单一来源。
- `event-bus.ts`：有界 SSE fan-out。
- `server.ts`：`Bun.serve` 路由 + ~1s scanner 循环。
- 启动：`bun run dashboard [--results <dir>] [--port N] [--manifest <path>]`。
- 输入：`results/` + `grid-manifest.json`（由 `quorum grid-manifest` 生成）。
- **绝不** 启动或停止 run（orchestrator/scheduler 耦合已移除）。

#### Provenance（版本可追溯）

每个 verdict 带 `provenance` block（`file:///tmp/superpowers-research/superpowers-evals/src/runner/provenance.ts`，runner 第 1002-1018 行写入）：

```typescript
{
  superpowers_rev: string | null,    // 被测 superpowers commit
  superpowers_dirty: boolean | null, // 是否有未提交改动
  harness_rev: string | null,        // quorum 自己的 commit
  agent_cli_version: string | null,  // coding-agent CLI 版本
  gauntlet_version: string | null,   // gauntlet 版本
}
```

这让任何 run 都能追溯到具体的 (superpowers, harness, agent CLI, gauntlet) 版本组合——版本对比的基础。

#### baseline 报告对比

`docs/baselines/` 下的报告结构化对比（如 `2026-06-09.md` 第 139-152 行 "Net delta from 05-29"）：

- 标注是否首次该 backend 组合（"first claude + antigravity matrix; no clean per-cell delta"）。
- 结构化故事：capture fix 是否生效、non-pass 是否真信号、standing determination 是否移动。
- Action items 表格：每条标注 Bucket / Owner-ish。

#### experiments 日志

`docs/experiments/` 下每个 experiment campaign 一个日期文件（如 `2026-07-28-codex-efficiency/e1-report.md`），CLAUDE.md 第 169-177 行规定：**negative results 与 wins 同等 billing**，防止已证伪的 candidate 被重新购买。

---

## 7. 借鉴清单总结

| 我们的组件 | 借鉴 superpowers-evals 的实现 | 借鉴方式 | 风险/差异 |
|---|---|---|---|
| **verdict 三值化** | `pass / fail / indeterminate` + precedence-based compose（`src/composer.ts`） | 直接采纳；`indeterminate` 专用于 harness/capture/pre-check 失败 | 我们评"思维路径"而非 skill 触发，"无法判定"语义需重新定义（如"路径未完成"） |
| **双层独立作证** | LLM 语义判定（AC prose）+ 确定性 checks（bash DSL），互不可见 | 强烈借鉴；AC prose 给 LLM judge，deterministic check 独立跑 | 我们可能没有 coding-agent CLI 的 session log，需找别的 deterministic 证据源（最终产物 diff、路径节点覆盖） |
| **场景三件套** | `story.md` + `setup.sh` + `checks.sh` 一目录 | 借鉴结构；story 改为"思维任务 brief"，setup 改为"初始上下文构造"，checks 改为"路径属性断言" | 我们的"fixture"是思维上下文而非 git repo，setup 形态完全不同 |
| **bare-verb DSL** | `file-exists` / `git-count` / `skill-called` / `not` 等 shell 函数 | 借鉴思路；定义思维路径专用 verb：`path-contains-node` / `path-before-node` / `visited-branch` / `not` | 我们需自定义 verb 集合，不能直接复用 FS/transcript verb |
| **127 crash band** | broken check 不可虚晃 pass，不可被 `not` 反转 | 强烈借鉴；防止 typo'd check 静默通过 | 实现简单：verb dispatcher 返回 `{broken:true}` → exit 127 |
| **空 capture 毒化** | 空 trajectory + 存在 trace check → 强制 indeterminate | 借鉴；空思维路径 + 路径属性 check → indeterminate | 我们的"空 capture"可能是 LLM 未产出路径或路径解析失败 |
| **calibration pair** | 两场景共享 fixture 从两侧 bracket 行为 | 借鉴；A/B 评测天然就是 calibration pair（A 路径 vs B 路径同任务） | 我们 A/B 本身就是对照，无需额外构造 |
| **content-addressed fixture** | `baseline-manifest.json`（SHA-256 + mode）保证每 cell 从字节相同输入开始 | 借鉴；A/B 评测必须保证两条路径起始上下文字节相同 | 思维上下文可能是 prompt 字符串，SHA-256 即可 |
| **elicited fixture** | 用被测 skill 生成 fixture，不要手写 | 借鉴；测思维路径时，初始上下文应由真实前序步骤生成 | 我们的"前序步骤"可能是另一个思维 skill |
| **canonical actors** | Gauntlet / Gauntlet-Agent / Coding-Agent / Quorum 四角色清晰分工 | 借鉴；定义我们的 actors：Judge-LLM / Path-Producer-LLM / SUT-path / Eval-Engine | 我们可能 Judge 和 Producer 是同一 LLM 的不同 prompt，需额外隔离 |
| **throwaway $HOME 隔离** | per-run `<runDir>/home` + XDG base dirs，每个 agent config 收在 throwaway home | 借鉴；per-run 隔离防 host state 污染 | 我们若不启 coding-agent CLI，可能只需 prompt 隔离而非文件系统隔离 |
| **zod schema 边界** | 所有跨进程/文件边界 shape 用 zod 校验 | 强烈借鉴；verdict.json / batch.json / economics 全部 schema 化 | Python 侧用 pydantic 等价实现 |
| **phase.json 探活** | 每阶段写 phase.json（含 pid），dashboard 用 `process.kill(pid, 0)` 探活 | 借鉴；长 run 需 liveness 探测 | 我们若 run 较快可省略 |
| **batch 矩阵 + snapshot** | `run-all` 跑 scenario × agent × credential 矩阵，credential 启动前 freeze 不可变 snapshot | 借鉴；A/B 评测就是 (scenario × path-variant × model) 矩阵，prompt 版本 freeze | 我们的 "credential" 是 prompt 模板版本 |
| **7 种失败归因图谱** | Pattern 1-7 区分真缺陷/broken check/环境缺失/capture 坏/... | 强烈借鉴；为思维路径评测定义专属归因图谱 | 我们失败模式不同（如"路径未触发"/"路径错误分支"/"路径过早收敛"） |
| **micro-test cheap tier** | $0.15-0.50/sample 的单 API call 微测试 + no-guidance control | 借鉴；prompt wording A/B 用微测试而非全 run | 我们评思维路径可能无法用单次 API call 模拟 |
| **CI 安全边界** | 静态/单元检查进 CI，live eval 仅 trusted-maintainer | 强烈借鉴；评测本身的 schema 校验进 CI，真 LLM 评测本地跑 | 我们的"live eval"就是调 LLM API，安全模型更简单 |
| **experiment 日志** | `docs/experiments/` 日期文件，negative results 同等 billing | 借鉴；A/B 评测历史可追溯，证伪的 path 变体不被重测 | 直接采纳 |
| **退出码契约** | pass=0 / fail=1 / indeterminate=2 | 借鉴；CI 可区分"失败"与"无法判定" | 直接采纳 |
| **`# coding-agents:` 指令** | checks.sh 前 21 行注释限制场景只跑某些 agent | 借鉴；思维路径评测可限制"只跑某些 model"或"只跑某些 path-variant" | 改名为 `# models:` 或 `# variants:` |
| **`requires-tool` pre-guard** | pre() 里 `requires-tool go`，缺失 → indeterminate 而非 fail | 借鉴；pre-guard 环境依赖 | 我们的依赖可能是 API key、特定 model 访问权 |
| **tolerant 经济视图** | economics 每字段 `unknown`，malformed 降级 "unpriced" 而非崩溃 | 借鉴；token cost / 时长统计容错 | 直接采纳 |
| **ATIF 归一化** | 各 agent session-log 归一化到统一 ATIF v1.7 Trajectory | 借鉴思路；思维路径需统一中间表示 | 我们的"轨迹"是思维节点序列，需自定义 schema |
| **provenance stamp** | 每 verdict 带 superpowers_rev/harness_rev/agent_cli_version/gauntlet_version | 借鉴；A/B 评测必须记录 (prompt 版本, model 版本, eval-engine 版本) | 直接采纳 |
| **vacuous-pass 语义** | `skill-before-tool` 当 tool 未调用时 vacuously true，需配 positive anchor | 借鉴；路径属性 check 需明确 vacuous 语义 | 路径评测中"X before Y"当 Y 未发生时的语义需明确 |
| **negative check 空 guard** | `skill-not-called` 空_capture → FAIL | 借鉴；"路径未访问 X" 空路径时 → FAIL 而非 pass | 直接采纳 |

---

## 8. 对我们 evaluation_engine.py 的设计建议

基于上述研究，给出 `evaluation_engine.py` 的具体设计建议。

### 8.1 核心架构：四 actor + 三值裁决

```python
# evaluation_engine.py 顶层架构

from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional, Literal

class FinalVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INDETERMINATE = "indeterminate"  # 借鉴 quorum：harness 自坏不误报 fail

class JudgeLayer(BaseModel):
    """对应 Gauntlet-Agent：LLM 语义判定。"""
    status: Literal["pass", "fail", "investigate"]  # investigate → indeterminate
    summary: str
    reasoning: str

class CheckRecord(BaseModel):
    """对应 quorum CheckRecord：确定性 check 的单条记录。"""
    check: str           # verb 名（如 "path-contains-node"）
    args: list[str]
    negated: bool        # 是否经 not 反转
    passed: bool
    detail: Optional[str]  # None 而非空字符串
    phase: Literal["pre", "post"]

class RunError(BaseModel):
    """对应 quorum RunError：staged error。"""
    stage: Literal["setup", "judge", "capture", "checks", "compose", "stopped", "unknown"]
    message: str

class Verdict(BaseModel):
    """对应 quorum FinalVerdict。"""
    schema_version: Literal[1] = 1
    final: FinalVerdict
    final_reason: str
    judge: Optional[JudgeLayer] = None
    checks: list[CheckRecord] = Field(default_factory=list)
    error: Optional[RunError] = None
    # Self-identity（A/B 评测维度）
    scenario: str
    path_variant: str          # "A" 或 "B" 等
    model: str
    started_at: str
    finished_at: str
    # Provenance（版本可追溯）
    prompt_rev: Optional[str] = None
    engine_rev: Optional[str] = None
    model_version: Optional[str] = None
```

### 8.2 裁决算法：precedence-based compose

```python
def compose(*, judge: JudgeLayer | None, checks: list[CheckRecord],
            capture_empty: bool, error: RunError | None) -> Verdict:
    """借鉴 src/composer.ts 的 precedence 链。第一个匹配赢，非投票。"""
    
    # 1. 任何 error → indeterminate
    if error:
        return Verdict(final=FinalVerdict.INDETERMINATE,
                       final_reason=f"eval error ({error.stage}): {error.message}",
                       judge=judge, checks=checks, error=error, ...)
    
    # 2. 任一 pre-check 失败 → indeterminate（fixture 错）
    failed_pre = [c for c in checks if c.phase == "pre" and not c.passed]
    if failed_pre:
        return Verdict(final=FinalVerdict.INDETERMINATE,
                       final_reason=f"pre-check(s) failed: {', '.join(c.check for c in failed_pre)}",
                       judge=judge, checks=checks, error=None, ...)
    
    # 3. 无 judge verdict → indeterminate
    if judge is None:
        return Verdict(final=FinalVerdict.INDETERMINATE,
                       final_reason="no judge verdict", ...)
    
    # 4. judge investigate/errored → indeterminate
    if judge.status in ("investigate", "errored"):
        return Verdict(final=FinalVerdict.INDETERMINATE,
                       final_reason=f"judge did not complete (status: {judge.status})", ...)
    
    # 5. 空 capture + 存在路径属性 check → indeterminate
    PATH_TRACE_VERBS = {"path-contains-node", "path-before-node", "visited-branch", ...}
    if capture_empty and any(c.check in PATH_TRACE_VERBS for c in checks):
        return Verdict(final=FinalVerdict.INDETERMINATE,
                       final_reason="path capture was empty; trace checks meaningless", ...)
    
    # 6. judge pass + 零 post 失败 → pass
    failed_post = [c for c in checks if c.phase == "post" and not c.passed]
    if judge.status == "pass" and not failed_post:
        n = sum(1 for c in checks if c.phase == "post")
        reason = (f"judge passed; {n} post-check(s) passed" if n
                  else "judge passed; no deterministic checks")
        return Verdict(final=FinalVerdict.PASS, final_reason=reason, ...)
    
    # 7. 否则 → fail
    bits = []
    if judge.status != "pass":
        bits.append(f"judge reported {judge.status}")
    if failed_post:
        bits.append(f"{len(failed_post)} post-check(s) failed")
    return Verdict(final=FinalVerdict.FAIL,
                   final_reason="; ".join(bits) or "fail", ...)
```

### 8.3 场景定义：三件套 + 思维路径专用 verb

```python
# scenarios/<name>/
#   story.md       — 给 Judge-LLM 的 brief + ACs
#   setup.py       — 构造初始思维上下文（对应 setup.sh）
#   checks.py      — 定义 pre() 和 post()，用 path-DSL

# path-DSL verb 词汇（借鉴 quorum 的 bare-verb + 127 crash band）：
PATH_VERBS = {
    # 路径结构
    "path-contains-node": ...,        # 路径含某节点（对应 skill-called）
    "path-not-contains-node": ...,    # 路径不含某节点（负向，空路径→FAIL）
    "path-node-count": ...,           # 节点数 op N（对应 tool-count）
    "path-before-node": ...,          # 节点 A 在 B 前（对应 tool-before）
    # 分支
    "visited-branch": ...,            # 访问了某分支
    "not-visited-branch": ...,        # 未访问某分支（负向）
    # 顺序
    "thought-before-action": ...,     # 思考节点在行动节点前
    # 完整性
    "path-reached-conclusion": ...,   # 路径到达结论
    "path-not-truncated": ...,        # 路径未截断
}

def not_verb(inner: str, args: list[str]) -> CheckRecord:
    """借鉴 dispatch.ts negate 的三条规则。"""
    if inner not in PATH_VERBS:
        # 规则 2：拒绝反转 missing verb → honest FAIL, exit 1
        return CheckRecord(check="not", args=[inner] + args, negated=False,
                           passed=False, detail=f"unknown inner verb: {inner}",
                           phase=...)
    outcome = PATH_VERBS[inner](args)
    if outcome.broken:
        # 规则 3：拒绝反转 crash → honest FAIL, exit 1
        return CheckRecord(check="not", args=[inner] + args, negated=False,
                           passed=False, detail=f"inner {inner} crashed: {outcome.detail}",
                           phase=...)
    # 规则 1：正常反转
    return CheckRecord(check=inner, args=args, negated=True,
                       passed=not outcome.passed, detail=None, phase=...)
```

### 8.4 A/B 评测矩阵

```python
# 借鉴 run-all/matrix.ts：scenario × path_variant × model 矩阵
@dataclass
class MatrixEntry:
    scenario: str
    path_variant: str        # "A" / "B" 
    model: str
    skipped_reason: Optional[str]  # None=run, "directive"/"tier"/...

def build_matrix(scenarios: list[str], variants: list[str], models: list[str],
                 tier_filter: str | None = None) -> list[MatrixEntry]:
    """借鉴 buildMatrix 的 precedence: directive > draft > tier > model."""
    entries = []
    for scenario in scenarios:
        directive = parse_variants_directive(scenario)  # # variants: A,B in checks.py
        for variant in variants:
            for model in models:
                skip = None
                if directive and variant not in directive:
                    skip = "directive"
                elif tier_filter and get_tier(scenario) != tier_filter:
                    skip = "tier"
                entries.append(MatrixEntry(scenario, variant, model, skip))
    return entries

# 借鉴 credentials.snapshot.yaml：A/B 评测 freeze prompt 模板版本
def freeze_prompt_snapshot(variant: str, batch_dir: Path) -> Path:
    """启动前 freeze 不可变 snapshot，编辑源 prompt 不影响已启动 batch。"""
    snapshot = batch_dir / f"prompt.{variant}.snapshot.yaml"
    shutil.copy(get_prompt_template(variant), snapshot)
    return snapshot
```

### 8.5 归因图谱（借鉴 7 patterns）

为思维路径评测定义专属归因图谱（对应 quorum 的 `docs/superpowers/skills/triaging-a-failing-eval.md`）：

| Pattern | Signature | 含义 | 处置 |
|---|---|---|---|
| **P1 真路径缺陷，judge 抓到** | `final=fail` · `judge=fail` · post-checks 大致干净 | 路径真的错（如未触发关键思维节点） | 读路径找错点 |
| **P2 真路径缺陷，check 抓到（judge 漏判）** | `final=fail` · `judge=pass` · ≥1 post-check 失败 | 路径看似 OK 实则缺关键节点 | 先验证 check 正确（P2 vs P4 rubric） |
| **P3 环境缺失（pre-guarded）** | `final=indeterminate` · pre-check 失败 | 缺 model 访问权/API key | 修环境，非路径 bug |
| **P4 broken check，假 fail** | `final=fail` · check 引用不存在的节点名 | quorum 是 bug，路径没问题 | 修 check |
| **P5 空 capture** | `final=indeterminate` · `capture_empty=true` | 路径未产出或解析失败 | 修 capture/路径 producer |
| **P6 judge investigate** | `final=indeterminate` · `judge.status=investigate` | judge 无法判定（路径太怪/截断） | 人工 review |
| **P7 A/B 分歧** | A pass, B fail（或反之） | 路径变体真有差异 | 这正是 A/B 评测想发现的信号 |

### 8.6 CI 安全边界

```yaml
# .github/workflows/eval-check.yml
# 借鉴 quorum：只跑静态/单元检查，绝不跑 live LLM eval
name: eval-check
on: [pull_request, push]
jobs:
  static:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: pip install -e .[dev]
      - run: ruff check .
      - run: mypy .
      - run: pytest test/
      - run: python -m evaluation_engine check  # 静态校验所有场景
```

live A/B 评测本地或 trusted runner 跑，结果写 `results/`（gitignore）。

### 8.7 关键差异与风险

| 差异点 | quorum 做法 | 我们需调整 |
|---|---|---|
| **SUT 形态** | 真实 coding-agent CLI（有 session log） | 思维路径是 LLM 输出的结构化轨迹，无独立 CLI session log |
| **capture 来源** | 文件系统 session-log diff | LLM 响应解析 + 中间步骤 trace（需自定义"轨迹中间表示"，类比 ATIF） |
| **fixture 形态** | git repo + 文件 | 思维上下文（prompt + 历史对话 + 工具结果） |
| **判断"实现文件"** | `isImplementationPath` 排除 `.git`/`docs`/`node_modules` | 思维路径无"实现文件"概念，需重新定义"关键思维节点" |
| **harness 隔离** | throwaway $HOME + per-agent config | prompt 隔离 + model call 隔离（无文件系统状态污染风险） |
| **calibration pair** | 两场景共享 fixture | A/B 天然就是同任务两路径，无需额外构造 |
| **cost 维度** | token + duration + tool_result bytes | token + duration + 思维节点数 |
| **空 capture 语义** | session-log 为空 | 路径未产出 / 路径解析失败 / 路径被截断（需细分） |

### 8.8 实现优先级建议

**MVP（必须）**：
1. `Verdict` / `CheckRecord` / `RunError` pydantic schema（借鉴 `contracts/verdict.ts`）。
2. `compose()` precedence 链（借鉴 `composer.ts`）。
3. 三件套场景格式 + `path-DSL` 最小 verb 集（`path-contains-node` / `path-before-node` / `not`）。
4. 127 crash band + `not` 三规则（借鉴 `dispatch.ts`）。
5. `quorum check` 等价的静态场景校验。
6. `verdict.json` + `phase.json` 输出。
7. A/B 矩阵 + prompt snapshot freeze。

**Phase 2**：
8. Dashboard（借鉴 `packages/dashboard/`，只读 web UI）。
9. 7-pattern 归因图谱文档。
10. baseline 报告格式 + experiments 日志。
11. provenance stamp（prompt_rev / engine_rev / model_version）。
12. tolerant 经济视图（token cost 容错）。

**Phase 3**：
13. micro-test cheap tier（prompt wording A/B 用单 API call 而非全 run）。
14. calibration pair 自动配对。
15. content-addressed fixture（prompt SHA-256）。

---

## 附录 A：关键文件路径速查

| 用途 | 文件路径 |
|---|---|
| 仓库 README | `file:///tmp/superpowers-research/superpowers-evals/README.md` |
| 场景 authoring 指南 | `file:///tmp/superpowers-research/superpowers-evals/docs/scenario-authoring.md` |
| harness 设计 spec | `file:///tmp/superpowers-research/superpowers-evals/docs/superpowers/specs/2026-05-22-harness-model-design.md` |
| 失败归因图谱 | `file:///tmp/superpowers-research/superpowers-evals/docs/superpowers/skills/triaging-a-failing-eval.md` |
| micro-test 指南 | `file:///tmp/superpowers-research/superpowers-evals/docs/superpowers/skills/micro-testing-prompt-guidance.md` |
| 评测 portfolio map | `file:///tmp/superpowers-research/superpowers-evals/docs/eval-harness-portfolio.md` |
| runner 主流程 | `file:///tmp/superpowers-research/superpowers-evals/src/runner/index.ts` |
| 裁决算法 | `file:///tmp/superpowers-research/superpowers-evals/src/composer.ts` |
| verdict schema | `file:///tmp/superpowers-research/superpowers-evals/src/contracts/verdict.ts` |
| check dispatcher | `file:///tmp/superpowers-research/superpowers-evals/src/check/dispatch.ts` |
| transcript verbs | `file:///tmp/superpowers-research/superpowers-evals/src/check/verbs.ts` |
| skill 检测 | `file:///tmp/superpowers-research/superpowers-evals/src/detect/skill.ts` |
| prelude DSL | `file:///tmp/superpowers-research/superpowers-evals/src/checks/prelude.sh` |
| checks 执行器 | `file:///tmp/superpowers-research/superpowers-evals/src/checks/index.ts` |
| 矩阵构造 | `file:///tmp/superpowers-research/superpowers-evals/src/run-all/matrix.ts` |
| batch index | `file:///tmp/superpowers-research/superpowers-evals/src/run-all/batch-index.ts` |
| baseline 报告样例 | `file:///tmp/superpowers-research/superpowers-evals/docs/baselines/2026-06-09.md` |
| CI workflow | `file:///tmp/superpowers-research/superpowers-evals/.github/workflows/test.yml` |
| 场景示例（triggering） | `file:///tmp/superpowers-research/superpowers-evals/scenarios/triggering-test-driven-development/` |
| 场景示例（review） | `file:///tmp/superpowers-research/superpowers-evals/scenarios/code-review-catches-planted-bugs/` |
| 场景示例（SDD） | `file:///tmp/superpowers-research/superpowers-evals/scenarios/sdd-go-fractals-opus48/` |
| 场景示例（user-pref） | `file:///tmp/superpowers-research/superpowers-evals/scenarios/user-pref-no-tdd/` |
| 场景示例（calibration） | `file:///tmp/superpowers-research/superpowers-evals/scenarios/brainstorming-resists-jump-to-implementation/` |

## 附录 B：术语对照

| quorum 术语 | 我们评测系统的对应概念 |
|---|---|
| Gauntlet | 通用 QA 框架（我们可能不需要，直接用 LLM judge） |
| Gauntlet-Agent | Judge-LLM（读 ACs 语义判定） |
| Coding-Agent | SUT-path（被测思维路径产出者） |
| Quorum | evaluation_engine.py |
| scenario | 思维任务 + 上下文 + ACs + checks |
| story.md | task brief + ACs |
| setup.sh | 初始上下文构造 |
| checks.sh | 路径属性断言（pre + post） |
| skill-called | path-contains-node |
| skill-before-tool | thought-before-action |
| trajectory.json | path.json（思维路径中间表示） |
| verdict.json | verdict.json（直接复用） |
| batch | A/B 评测批次 |
| credential | prompt 模板版本 / model 版本 |
| quorum_tier sentinel | smoke 测（快速高信号） |
| quorum_tier full | 完整评测套件 |
| indeterminate | 无法判定（harness 自坏 / 路径未产出） |
| 127 crash band | broken check 不可虚晃 pass |
| belt-and-braces | LLM judge + 确定性 check 双层独立作证 |
| calibration pair | A/B 评测天然就是 calibration pair |

---

*报告完。基于对 `/tmp/superpowers-research/superpowers-evals` 仓库 README、ABOUT、package.json、catalog-info.yaml、CLAUDE.md、biome.json、.gitignore、.github/workflows/test.yml、src/runner/index.ts、src/composer.ts、src/contracts/verdict.ts、src/check/dispatch.ts、src/check/verbs.ts、src/detect/skill.ts、src/checks/prelude.sh、src/checks/index.ts、src/run-all/matrix.ts、src/run-all/batch-index.ts、src/cli/render.ts、src/cli/render-batch.ts、src/cli/costs.ts、src/economics.ts、src/atif/types.ts、src/scaffold.ts、docs/scenario-authoring.md、docs/eval-harness-portfolio.md、docs/manual-testing.md、docs/superpowers/specs/2026-05-22-harness-model-design.md、docs/superpowers/skills/triaging-a-failing-eval.md、docs/superpowers/skills/micro-testing-prompt-guidance.md、docs/superpowers/plans/2026-05-22-harness-model.md、docs/baselines/2026-06-09.md、docs/audits/2026-06-13-liveness-and-bitrot-audit.md，以及 5 个 scenarios 目录的实际文件读取。*
