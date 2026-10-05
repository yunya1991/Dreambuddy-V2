---
name: dream-code-sync-orphan-scan-workflow
description: "Orchestrates 6-step post-commit orphan-component scan + integration + commit lock for frontend src/. Invoke when git commit/push completes, to detect untracked/modified files and orphan .tsx components that should have been wired up but weren't. Catches 'claimed done but not committed' regressions."
version: 1.0.0
created: 2026-10-04
updated: 2026-10-04
license: Internal
status: active
category: orchestration
triggers: [git commit 完成, git push 完成, 代码同步完成, 孤儿组件扫描, orphan scan, commit 锁定, untracked 检查]
depends_on: [dream-doc-sync-workflow, dream-scattered-file-cleanup]
provides: [orphan-component-scan, commit-lock-verification, untracked-file-detection]
cognitive_links: [VM-1791105132530-a174481c]
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


# Dream Code Sync Orphan Scan Workflow — 代码同步孤儿扫描工作流

> 把"git commit/push 完成 → 前端 src/ 全量扫描 → 孤儿组件接入 → untracked 暴露 → commit 锁定 → 认知闭环"的 6 步流程固化为可复用编排。本 SKILL 是 commit 纪律的最后一道防线，专门捕获"声称已完成但实际未 commit / 未接入"的回归（9-28 P0-P3 事故级别）。

> **双位置存储**：本 SKILL 同时存在于：
> - `.trae/skills/dream-code-sync-orphan-scan-workflow/SKILL.md`（TRAE 调用入口，本文件）
> - `1-ARCHITECTURE/skills/dream-code-sync-orphan-scan-workflow/SKILL.md`（项目级索引发现）

> **与 `dream-scattered-file-cleanup` 的边界**：后者治理**散落文档/配置文件**（5 步流程，盆景式修剪），本 SKILL 治理**前端源码孤儿组件 + commit 纪律**（6 步流程，commit 锁定）。两者同构但对象不同。

---

## 一、何时调用（触发条件）

满足以下任一条件即应调用本 SKILL：

1. **git commit 完成**：刚执行 `git commit` 后，扫描本次 commit 是否遗漏 untracked/modified 文件
   - 触发词：「git commit 完成」「代码同步完成」「commit 锁定」
2. **git push 完成**：刚执行 `git push` 后，扫描远程是否与本地孤儿状态一致
   - 触发词：「git push 完成」「推送完成」
3. **手动孤儿扫描**：用户怀疑有未接入的组件，主动触发全量扫描
   - 触发词：「孤儿组件扫描」「orphan scan」「检查未接入组件」
4. **认知事件驱动**：认知系统 `record` 时 `tags` 含 `orphan-scan`，自动触发
   - **hook 配置**：`TAG_HOOKS = {"orphan-scan": "dream-code-sync-orphan-scan-workflow"}`（可选扩展）
   - **FAIL-OPEN**：hook 异常不影响 record 主流程

**不触发的场景**：
- 后端 Python / Rust 模块孤儿扫描（本 SKILL 仅覆盖前端 src/）
- 文档同步（应调用 `dream-doc-sync-workflow`）
- 散落文档清理（应调用 `dream-scattered-file-cleanup`）
- 单文件小修复（无批量接入需求）

---

## 二、6 步标准流程

### 步骤 1：commit 状态基线（确定扫描范围）

**输入**：刚完成的 commit hash（或 push 远端分支）

**处理**：

```bash
# 1. 获取最近 commit 的 hash + 影响文件清单
git log -1 --format="%H %s" 
git show --stat HEAD

# 2. 暴露 untracked + modified 文件（关键：9-28 P0-P3 事故的根因检测）
git status --short -- 3.1-FRONTEND/src/
```

**判定**：

| 状态 | 判定 | 处理 |
|------|------|------|
| `??` (untracked) | 文件存在但从未 commit | **红旗**：9-28 P0-P3 同款事故，立即接入或 commit |
| `M` (modified) | 已跟踪但有未提交修改 | 检查是否本次 commit 遗漏 |
| `A` (added) | 已暂存但未 commit | 已纳入，无需处理 |
| ` ` (clean) | 干净 | 进入步骤 2 扫描孤儿组件 |

**输出**：commit 状态基线报告（untracked 数 + modified 数 + 影响 .tsx 文件清单）

---

### 步骤 2：全量组件清单（Glob 扫描）

**输入**：前端根目录 `3.1-FRONTEND/src/`

**处理**：

```bash
# 1. 列出全部 .tsx 组件文件
Glob: 3.1-FRONTEND/src/components/features/**/*.tsx

# 2. 列出全部 page.tsx（路由入口）
Glob: 3.1-FRONTEND/src/app/**/page.tsx
```

**输出**：组件清单（路径 + 文件名 + 大小）

**注意事项**：
- 包含子目录（chat/、chain/、ranking/、settings/ 等）
- 同名重复组件需特别标记（如 mood-board/MoodBoardPanel.tsx 事故）

---

### 步骤 3：import 引用扫描（Grep 一次性获取）

**输入**：步骤 2 的组件清单

**处理**：

```bash
# 一次性获取所有 import 引用（避免逐个 grep）
Grep: "from '@/components/features/" --type tsx --type ts
```

**输出**：引用图（哪个 page/组件 import 了哪个子组件）

**优化**：单次 Grep 比逐个 grep 效率高 10x+，特别是组件数 ≥ 20 时

---

### 步骤 4：孤儿识别 + 历史溯源

**输入**：组件清单 + 引用图

**处理**：

1. **对照清单找出无人 import 的孤儿组件**：
   - 在步骤 3 的引用图中查找每个组件的引用计数
   - 引用计数 = 0 → 孤儿候选
   - 引用计数 = 1 且引用者是 page.tsx → 正常接入，跳过
2. **历史溯源（区分"从未接入" vs "曾接入后回退"）**：

```bash
# 对每个孤儿组件查询 git 历史
git log --all -S "组件名" -- 3.1-FRONTEND/src/
```

**判定**：

| git log 结果 | 含义 | 处置 |
|-------------|------|------|
| 无任何记录 | 从未接入（9-28 P0-P3 同款） | **必须接入** |
| 有 add 记录但近期有 delete | 曾接入后被回退（版本回退事故） | **必须接入 + 修复回退** |
| 有 add 记录且当前活跃 | 可能是引用路径错误 | 检查 import 路径是否变更 |

**输出**：孤儿组件清单（组件名 + 历史标签：never-integrated / rolled-back / path-changed）

---

### 步骤 5：接入 + 修复（Agent 并行策略）

**输入**：孤儿组件清单

**处理**：

1. **Agent 并行策略**（独立文件改造可并行）：
   - 每个孤儿组件的接入是独立任务（互不依赖）
   - 主线程可启动 N 个 Agent 并行做接入（N ≤ 孤儿数）
   - 主线程同时做小修复（store 字段补齐 / 类型对齐）
2. **FAIL-OPEN 设计原则**：
   - 子组件无数据时 `return null`，不崩溃
   - 接入字段名错配时，对齐 store 类型（如 session-store.ts 补齐 `lastSynthesis` / `pendingStepConfirmation`）
3. **接入验证**：
   - TypeScript 编译检查：`cd 3.1-FRONTEND && npx tsc --noEmit`
   - 0 errors 才算接入成功

**输出**：接入完成的组件清单 + TypeScript 编译报告

---

### 步骤 6：commit 锁定 + 认知闭环

**输入**：接入完成的组件清单

**处理**：

1. **精确 git add 路径**（避免混入无关 modified）：

```bash
# ✅ 精确路径（推荐）
git add 3.1-FRONTEND/src/components/features/chat/ChatPanel.tsx
git add 3.1-FRONTEND/src/components/features/chat/MessageItem.tsx
# ... 每个接入的组件精确 add

# ❌ 禁止：git add . 或 git add -A（会混入无关 modified）
```

2. **commit 锁定**：

```bash
git commit -m "feat(frontend): 接入 N 个孤儿组件 + commit 锁定

- 接入: <组件清单>
- 修复: <store 字段补齐 / 类型对齐>
- TypeScript: 0 errors
- 经验: VM-xxx"
```

3. **认知闭环**（硬约束）：

```
record(
  content="[代码同步孤儿扫描] commit <hash> | 接入 <N> 孤儿组件 | untracked <U> modified <M> | TypeScript 0 errors | 经验: <关键教训>",
  quality_level="B",
  tags="orphan-scan,代码同步,commit锁定,前端域,FAIL-OPEN,Agent并行,认知闭环"
)

verify(memory_id="VM-xxx", success=true)
```

**输出**：commit hash + 认知记忆 ID

---

## 三、输入输出契约

| 阶段 | 输入 | 输出 |
|------|------|------|
| 步骤 1 | commit hash / push 远端 | commit 状态基线（untracked + modified 数） |
| 步骤 2 | 前端根目录 | 组件清单（路径 + 文件名） |
| 步骤 3 | 组件清单 | 引用图（组件 → 引用者） |
| 步骤 4 | 组件清单 + 引用图 | 孤儿清单（+ 历史标签） |
| 步骤 5 | 孤儿清单 | 接入完成清单 + tsc 报告 |
| 步骤 6 | 接入完成清单 | commit hash + 认知记忆 ID |

---

## 四、多领域调研（Step 2 — MANDATORY）

> **项目硬约束**（VM-1790765308904）：SKILL 创建前必须做多领域调研。本节调研 3 域：技术开发 + GitHub生态 + 产品管理。

### 4.1 技术开发域（Linux Kernel MAINTAINERS + K8s Diátaxis）

**核心借鉴**：

| 模式 | 来源 | 在本 SKILL 的应用 |
|------|------|-------------------|
| `Status: Orphan` 标签 | Linux Kernel MAINTAINERS 文件 | 步骤 4 孤儿识别的 status 标签（never-integrated / rolled-back / path-changed） |
| `Audience×Type` 双维度分类 | K8s Diátaxis | 步骤 2 组件清单的双维度（域 × 类型）整理 |
| `WORM 归档` | SEC 17a-4（金融合规跨界） | commit 锁定 = WORM，git history 即天然不可变日志 |
| `定期 Review` | 文档生命周期管理 | 步骤 6 认知闭环后的 verify 升级 |

**关键洞察**：Linux Kernel 的 MAINTAINERS 文件用 `Status: Orphan` 标记无 owner 的子系统，本 SKILL 借鉴此模式给孤儿组件打三态标签（never-integrated / rolled-back / path-changed），区分"从未接入"和"曾接入后回退"，处置策略不同。

### 4.2 GitHub 生态域（orphan-detection + OWNERS）

**核心借鉴**：

| 模式 | 来源 | 在本 SKILL 的应用 |
|------|------|-------------------|
| `git log -S "name"` 溯源 | Git pickaxe operator | 步骤 4 历史溯源的核心命令 |
| `git status --short` | Git 标准 | 步骤 1 untracked/modified 暴露的核心命令 |
| `OWNERS` 文件 | Chromium / Kubernetes | 给接入后的组件指定 owner（可选扩展） |
| 精确 `git add path` | Git 最佳实践 | 步骤 6 禁止 `git add .` / `git add -A`，必须精确路径 |
| `Dependabot` 依赖图 | GitHub 生态 | 步骤 3 引用图的类比（component → importers） |

**关键洞察**：Git 自带的 `git log -S` (pickaxe) 是溯源神器，能区分"从未接入" vs "曾接入后回退"，这是 9-28 P0-P3 事故根因分析的关键。GitHub 生态的 OWNERS 机制提示我们：接入后的组件应有明确 owner，避免再次成为孤儿。

### 4.3 产品管理域（Amazon PR/FAQ + Google Design Doc）

**核心借鉴**：

| 模式 | 来源 | 在本 SKILL 的应用 |
|------|------|-------------------|
| `Working Backwards` | Amazon PR/FAQ | 从"commit 后应该是什么状态"倒推扫描步骤 |
| `Definition of Done` | Agile / Scrum | "完成"= commit + push + 0 untracked + 0 孤儿（不只是代码写完） |
| `Design Doc lifecycle` | Google | SKILL 本身的 lifecycle：proposed → shadow → active |
| `Post-mortem` 文化 | Google SRE | 9-28 P0-P3 事故的根因分析 → 本 SKILL 的预防机制 |
| `Single-threaded leader` | Amazon 单线程领导 | Agent 并行策略中，每个 Agent 是单线程 owner |

**关键洞察**：Amazon 的 `Definition of Done` 概念最关键——"代码写完" ≠ "完成"，必须 commit + push + 验证 0 untracked + 0 孤儿才算完成。本 SKILL 是 DoD 的自动化检查器。Google SRE 的 Post-mortem 文化启发了"9-28 事故 → 本 SKILL"的转化路径。

### 4.4 调研总结：3 域融合的设计决策

| 设计决策 | 借鉴来源 | 体现在 SKILL 的 |
|----------|----------|-----------------|
| 三态孤儿标签 | Linux Kernel MAINTAINERS + GitHub pickaxe | 步骤 4 |
| `Definition of Done` 检查器 | Amazon PR/FAQ | 步骤 1 + 步骤 6 |
| 精确 `git add path` | Git 最佳实践 | 步骤 6 |
| Agent 并行 + 单线程 owner | Amazon Single-threaded leader | 步骤 5 |
| FAIL-OPEN 设计 | Google SRE 优雅降级 | 步骤 5 |
| `定期 Review` + verify 升级 | 文档生命周期 | 步骤 6 |

---

## 五、相关 SKILL 与工具

| 类型 | 名称 | 用途 |
|------|------|------|
| 同构 | `dream-scattered-file-cleanup` | 散落文档治理（对象不同，模式可复用） |
| 同构 | `dream-doc-sync-workflow` | 文档索引同步（同构流程，对象不同） |
| 元 | `skill-creator` | 本 SKILL 的创建工具 |
| 工具 | `Glob` | 步骤 2 组件清单扫描 |
| 工具 | `Grep` | 步骤 3 import 引用扫描 |
| 工具 | `git log -S` | 步骤 4 历史溯源（pickaxe） |
| 工具 | `git status --short` | 步骤 1 untracked/modified 暴露 |
| 工具 | `npx tsc --noEmit` | 步骤 5 TypeScript 编译检查 |
| 认知 | `recall`/`record`/`verify` | 认知闭环 |

---

## 六、hermes 反思决策树

> 引用元 SKILL `dream-qwen-eval-collab` 第五节决策树模式。

```
本次代码同步是否值得形成/衍生 SKILL？
├── 是（满足以下任一）：
│   ├── 流程被复用 ≥ 2 次（本 SKILL 已是第 2 次，9-28 + 10-04）
│   ├── 涉及多步编排（≥ 3 步，本 SKILL 6 步）
│   ├── 涉及外部工具调用（≥ 1 个 git CLI）
│   └── 用户明确要求「形成 SKILL」（本次用户已明确要求）
│   → 调用 skill-creator 创建新 SKILL
│   → record 经验，tags 含「SKILL,hermes反思,orphan-scan」
│
└── 否（满足以下全部）：
    ├── 一次性代码同步（无复用价值）
    ├── 仅单步操作
    └── 无孤儿组件
    → 仅 record 经验
    → tags 不含「SKILL」
```

---

## 七、认知闭环（recall + record + verify）

**任务开始前**（硬约束，不可跳过）：

```
recall(context="代码同步 孤儿组件 commit 锁定 untracked 前端域", top_k=5, min_quality="C")
```

**任务完成后**（步骤 6）：

```
record(content="[代码同步孤儿扫描] commit <hash> | 接入 <N> 孤儿组件 | untracked <U> modified <M> | TypeScript 0 errors | 经验: <关键教训>",
       quality_level="B",
       tags="orphan-scan,代码同步,commit锁定,前端域,FAIL-OPEN,Agent并行,认知闭环")

verify(memory_id="VM-xxx", success=true)
```

---

## 八、FAIL-OPEN 与异常处理

| 异常场景 | 处理策略 |
|----------|---------|
| Glob 找不到 .tsx 文件 | 跳过扫描，记录告警 `no-components-found` |
| Grep 找不到 import 引用 | 全部组件标记为孤儿候选，进入步骤 4 历史溯源 |
| `git log -S` 无记录 | 标记 `never-integrated`，强制接入 |
| `npx tsc` 编译失败 | 记录错误清单，不阻塞 commit，但需人工修复后重新 commit |
| Agent 并行接入失败 | 单个 Agent 失败不影响其他，记录失败清单 |
| 认知 record 失败 | 不阻塞 commit，仅本地日志记录 |
| `git add` 路径错误 | 立即 `git reset HEAD <path>` 撤销，重新精确 add |

**核心原则**：孤儿扫描永不阻塞 commit 主流程，所有异常降级为告警。但 `git add -A` / `git add .` 是**严格禁止**（会混入无关 modified）。

---

## 九、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-10-04 | 初始版本，6 步流程 + 3 域调研 + 双触发模式 + FAIL-OPEN。来源经验 VM-1791105132530-a174481c（9-28 P0-P3 事故 + 10-04 24 个孤儿组件批量接入） |
