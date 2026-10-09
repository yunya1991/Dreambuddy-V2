---
name: dream-code-commit-sync-workflow
description: "Orchestrates code-change auto-commit: change parse → precise stage → validate (tsc/tests) → conventional commit message → commit → orphan-scan → cognitive record. Invoke when code changes are complete and need committing, or when user says 'commit/sync code'."
version: 1.0.0
created: 2026-10-04
updated: 2026-10-04
license: Internal
status: active
category: orchestration
triggers: [提交代码, 代码同步, commit, 代码提交, 同步代码, code commit, 提交变更]
depends_on: [git, tsc, dream-code-sync-orphan-scan-workflow, auto_sync_dispatcher.py, dream-doc-sync-workflow, knowledge-ingest, dream-skill-index-governance]
provides: [code-commit-sync, commit-orchestration, post-commit-scan, post-commit-sync-dispatch]
cognitive_links: [VM-1791126204667-1d31ec21]
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


# Dream Code Commit Sync Workflow — 代码改动自动提交同步工作流

> 把「代码变更 → 变更解析 → 精确暂存 → 校验 → 生成 commit message → 提交 → 孤儿扫描 → 认知闭环」的 7 步代码提交流程固化为可复用编排。本 SKILL 对标 `dream-doc-sync-workflow`（文档自动同步），是代码侧的"改动即提交"自动化通道，杜绝"代码写完但未 commit / 未扫描孤儿"的回归。

> **双位置存储**：本 SKILL 同时存在于：
> - `.trae/skills/dream-code-commit-sync-workflow/SKILL.md`（TRAE 调用入口，本文件）
> - `1-ARCHITECTURE/skills/dream-code-commit-sync-workflow/SKILL.md`（项目级索引发现）

> **与 `dream-code-sync-orphan-scan-workflow` 的边界**：后者是**提交后**的孤儿组件扫描（6 步），本 SKILL 是**驱动提交**的全流程编排（7 步），步骤 6 会调用后者。两者同构但阶段不同。

---

## 一、何时调用（触发条件）

满足以下任一条件即应调用本 SKILL：

1. **代码改动完成需提交**：完成了代码修改（修复/新功能/重构），需要 commit
   - 触发词：「提交代码」「代码同步」「commit」「提交变更」「同步代码」
2. **用户要求直接提交**：用户明确说"改完直接 commit"或"跟踪提交"
3. **认知事件驱动**：认知系统 `record` 时 `tags` 含 `code-commit`，自动触发
   - **hook 配置**：`TAG_HOOKS = {"code-commit": "dream-code-commit-sync-workflow"}`
   - **FAIL-OPEN**：hook 异常不影响 record 主流程
4. **批量改动收口**：多个文件改动后需要统一提交并锁定

**不触发的场景**：
- 纯文档变更（`.md`）→ 调用 `dream-doc-sync-workflow`
- 散落文件清理 → 调用 `dream-scattered-file-cleanup`
- 用户未授权提交（需先确认范围）→ 先问再提交

---

## 二、7 步标准流程

### 步骤 1：变更解析（确定提交范围）

**输入**：工作区 git 状态

**处理**：

```bash
git status --short          # 全量状态
git diff --stat             # 已修改文件统计
git diff --cached --stat    # 已暂存文件统计
```

**变更类型识别**：

| 状态 | 含义 | 处置 |
|------|------|------|
| `M ` / ` M` | 已跟踪文件修改 | 纳入本次提交（除非在排除列表） |
| `A ` / `??` | 新增文件 | 检查是否本次相关，是则纳入 |
| `D ` | 删除文件 | 纳入 |
| `R ` | 重命名 | 纳入 |

**排除规则**（硬约束，禁止纳入）：

- `*.json` 数据缓存文件（如 `backtest_cache/`、`*.db`）
- 生成产物（`node_modules/`、`dist/`、`.next/`）
- 环境变量文件（`.env.local`、`.env.*` 含密钥）
- IDE/系统文件（`.DS_Store`、`.idea/`）
- 与本次改动无关的 modified 文件（如自动生成的回测结果）

**输出**：变更清单（待提交文件路径列表 + 排除文件列表）

---

### 步骤 2：精确暂存（禁止 git add .）

**输入**：变更清单

**处理**：

```bash
# ✅ 精确路径暂存（每个文件单独 add）
git add path/to/file1.ts path/to/file2.py

# ❌ 严格禁止：git add . / git add -A / git add -u
# 会混入无关 modified 文件（如回测缓存、日志）
```

**暂存后验证**：

```bash
git diff --cached --stat    # 确认暂存区内容与预期一致
```

若暂存区混入无关文件，立即 `git reset HEAD <path>` 撤销。

**输出**：已暂存文件清单（与变更清单一致）

---

### 步骤 3：校验（tsc 硬门禁 + tests 软门禁）

**输入**：已暂存文件

**处理**：

```bash
# 硬门禁：TypeScript 编译（前端改动时）
cd 3.1-FRONTEND && npx tsc --noEmit

# 硬门禁：Python 语法检查（后端改动时）
python3 -m py_compile <changed_py_files>

# 软门禁：相关测试（有则跑，无则跳过）
# 不阻塞提交，失败记录告警
```

**门禁策略**：

| 检查项 | 类型 | 失败处理 |
|--------|------|---------|
| `tsc --noEmit` | 硬门禁 | **阻塞提交**，必须修复后重试 |
| `py_compile` | 硬门禁 | **阻塞提交**，必须修复后重试 |
| 单元测试 | 软门禁 | 记录告警，可继续提交（标记 `test-failed`） |
| lint | 软门禁 | 记录告警，可继续提交 |

**FAIL-OPEN 例外**：若改动仅为文档/配置（无 .ts/.py 代码变更），跳过 tsc/py_compile。

**输出**：校验报告（硬门禁结果 + 软门禁结果）

---

### 步骤 4：生成 Conventional Commit Message

**输入**：变更清单 + 改动摘要

**处理**：

根据改动内容选择 type：

| type | 场景 |
|------|------|
| `fix` | bug 修复 |
| `feat` | 新功能 |
| `refactor` | 重构（无功能变更） |
| `perf` | 性能优化 |
| `docs` | 文档 |
| `test` | 测试 |
| `chore` | 构建/工具/依赖 |
| `style` | 格式（不影响逻辑） |

**格式**：

```
<type>(<scope>): <subject>

<body 详细说明，可选>

<footer，可选：BREAKING CHANGE / 关联 issue>
```

**subject 规则**：
- 中文优先（项目沟通语言）
- ≤ 50 字
- 祈使句（"修复…" / "迁移…" / "接入…"）
- 不加句号

**scope 规则**：
- 前端：`frontend` / `bridge` / `classic`
- 后端：`m27` / `m26` / `m25` / `m28`
- 跨模块：`core` / `infra`

**输出**：commit message 字符串

---

### 步骤 5：提交

**输入**：暂存区 + commit message

**处理**：

```bash
git commit -m "<commit message>"
```

**提交后验证**：

```bash
git log -1 --format="%H %s"     # 确认 commit 成功
git status --short              # 确认工作区无残留未提交的相关改动
```

**输出**：commit hash + 提交摘要

---

### 步骤 6：提交后孤儿扫描（委托 dream-code-sync-orphan-scan-workflow）

**输入**：commit hash

**处理**：

调用 `dream-code-sync-orphan-scan-workflow` 执行 6 步扫描：

1. commit 状态基线（untracked/modified 暴露）
2. 全量组件清单（Glob）
3. import 引用扫描（Grep）
4. 孤儿识别 + 历史溯源
5. 接入 + 修复（FAIL-OPEN）
6. commit 锁定 + 认知闭环

**若发现孤儿组件**：
- 接入后重新 commit（步骤 2-5 循环）
- 精确 add 接入的组件文件

**输出**：孤儿扫描报告（孤儿数 + 接入数）

---

### 步骤 7：认知闭环（record + verify）

**输入**：提交结果 + 孤儿扫描结果

**处理**：

```
record(
  content="[代码提交同步] commit <hash> | 改动 <N> 文件 | 类型: <type> | tsc: <pass/fail> | 孤儿: <发现F>/接入I> | 排除: <E> 个无关文件",
  quality_level="B",
  tags="code-commit,代码同步,commit锁定,前端域,FAIL-OPEN,认知闭环"
)

verify(memory_id="VM-xxx", success=true)
```

**输出**：认知记忆 ID

---

### 步骤 8：提交后四系统同步分发（双保险·AI 层）

> **硬约束（不可跳过）**：commit 完成后必须执行本步骤，根据本次提交的文件类型分发到对应系统同步。
> 本步骤与 `post-commit` hook 中的 `auto_sync_dispatcher.py`（机器层）构成双保险。
> 机器层已自动执行轻量级同步（SKILL 注册、知识向量化、文档队列登记），本步骤负责**确认 + 补充执行**需要 AI 判断的同步。

**输入**：本次 commit 的文件清单 + `pending_sync_queue.json`

**处理**：

**8.1 消费机器层待同步队列**

```bash
python3 1-ARCHITECTURE/skills/dream-skill-index-governance/auto_sync_dispatcher.py --consume-queue
```

若返回 `has_pending: true`，说明有文档变更待同步，继续 8.2。

**8.2 按文件类型分发同步**

| 本次提交文件类型 | 目标系统 | 必须执行的同步 |
|-----------------|---------|---------------|
| `SKILL.md` 新增/修改 | SKILL 索引系统 | 确认 `auto_sync_dispatcher` 已注册；若未注册则手动调用 `auto_register_skill.py` |
| `2-KNOWLEDGE/` 下文件 | 知识库系统 | 确认向量化已运行；若未运行则手动执行 `build_index.py` |
| 其他 `.md` 文档 | 文档管理系统 | 调用 `dream-doc-sync-workflow` 更新 INDEX.md |
| 代码文件 | 无 | 跳过（无索引同步需求） |

**8.3 文档同步执行（若有文档变更）**

```
# 调用 dream-doc-sync-workflow 执行 7 步文档索引同步
# 变更解析 → 0-系统文档管理/INDEX 更新 → 2-KNOWLEDGE 索引更新 → 校验 → 覆盖率 → 飞书同步 → 认知记录
```

**8.4 知识入库执行（若有知识变更且未被机器层覆盖）**

```
# 调用 knowledge-ingest 执行 5 步知识沉淀
# 分类 → 原子存储 → 向量化 → 认知 record → 索引 reload
```

**输出**：四系统同步确认报告（各系统 status + 红旗）

**红旗判定**：
- 文档变更但未调用 `dream-doc-sync-workflow` → 🚩 必须执行
- 知识变更但向量化未运行 → 🚩 必须执行
- SKILL 变更但未在 registry 中 → 🚩 必须注册

---

## 三、输入输出契约

| 阶段 | 输入 | 输出 |
|------|------|------|
| 步骤 1 | git status | 变更清单 + 排除列表 |
| 步骤 2 | 变更清单 | 已暂存文件清单 |
| 步骤 3 | 已暂存文件 | 校验报告（硬+软门禁） |
| 步骤 4 | 变更清单 + 摘要 | commit message |
| 步骤 5 | 暂存区 + message | commit hash |
| 步骤 6 | commit hash | 孤儿扫描报告 |
| 步骤 7 | 提交+扫描结果 | 认知记忆 ID |
| 步骤 8 | commit 文件清单 + 待同步队列 | 四系统同步确认报告 |

---

## 四、相关 SKILL 与工具

| 类型 | 名称 | 用途 |
|------|------|------|
| 同构 | `dream-doc-sync-workflow` | 文档自动同步（步骤8调用） |
| 下游 | `dream-code-sync-orphan-scan-workflow` | 提交后孤儿扫描 |
| 同构 | `dream-scattered-file-cleanup` | 散落文件治理 |
| 下游 | `knowledge-ingest` | 知识沉淀（步骤8调用） |
| 下游 | `dream-skill-index-governance` | SKILL 索引治理（步骤8确认） |
| 工具 | `auto_sync_dispatcher.py` | 四系统同步分发器（机器层） |
| 工具 | `git` | 版本控制 |
| 工具 | `tsc --noEmit` | TypeScript 编译检查 |
| 工具 | `py_compile` | Python 语法检查 |
| 认知 | `recall`/`record`/`verify` | 认知闭环 |

---

## 五、hermes 反思决策树

```
本次代码提交是否值得形成/衍生 SKILL？
├── 是（满足以下任一）：
│   ├── 流程被复用 ≥ 2 次
│   ├── 涉及多步编排（≥ 3 步，本 SKILL 7 步）
│   ├── 涉及外部工具调用（git/tsc/py_compile）
│   └── 用户明确要求「形成 SKILL」
│   → 调用 skill-creator 创建/更新 SKILL
│   → record 经验，tags 含「SKILL,hermes反思,code-commit」
│
└── 否（满足以下全部）：
    ├── 一次性提交
    ├── 仅单文件小修
    └── 无复用价值
    → 仅 record 经验
    → tags 不含「SKILL」
```

---

## 六、认知闭环（recall + record + verify）

**任务开始前**（硬约束）：

```
recall(context="代码提交 git commit 孤儿扫描 精确暂存", top_k=5, min_quality="C")
```

**任务完成后**（步骤 7）：

```
record(content="[代码提交同步] commit <hash> | <N> 文件 | <type> | tsc: <result> | 孤儿: <F>/<I>",
       quality_level="B",
       tags="code-commit,代码同步,commit锁定,认知闭环")
verify(memory_id="VM-xxx", success=true)
```

---

## 七、FAIL-OPEN 与异常处理

| 异常场景 | 处理策略 |
|----------|---------|
| tsc 编译失败 | **阻塞提交**，修复后重试（硬门禁） |
| py_compile 失败 | **阻塞提交**，修复后重试（硬门禁） |
| 测试失败 | 告警记录，可继续提交（标记 `test-failed`） |
| 暂存区混入无关文件 | 立即 `git reset HEAD <path>`，重新精确 add |
| commit 冲突 | 中止，提示用户解决冲突后重试 |
| 孤儿扫描失败 | 不阻塞，记录告警，下次提交时重扫 |
| 认知 record 失败 | 不阻塞，仅本地日志 |

**核心原则**：
- 硬门禁（tsc/py_compile）必须通过才提交
- 软门禁（tests/lint）降级为告警
- `git add .` / `git add -A` 严格禁止

---

## 八、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-10-04 | 初始版本，7 步流程 + 精确暂存 + 软硬门禁 + 孤儿扫描委托 + FAIL-OPEN |
