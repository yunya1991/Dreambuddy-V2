---
name: dream-completion-evolution-workflow
description: "收尾SKILL(默认名，方便记忆) — SPEC任务完成后的自动收尾编排器: 验收门禁→代码提交→文档同步→SKILL治理→认知闭环→最终报告。智能路由按变更类型决定执行哪些步骤，验收是硬门禁其余FAIL-OPEN。与开工SKILL对称：开工负责启动闭环(调研→SPEC→评审→PLAN)，收尾负责完成闭环(验收→commit→文档→治理→认知→报告)。Invoke when a SPEC task/feature/bugfix is dev-complete and needs wrap-up, or when user says '收尾/wrap up/finish up/complete'. 默认名: 收尾SKILL/wrapup。"
version: 1.0.0
created: 2026-10-09
updated: 2026-10-09
license: Internal
status: active
category: orchestration
triggers: [收尾, 收尾SKILL, wrapup, wrap up, finish up, 项目收尾, 完成闭环, 任务收尾, completion evolution, wrap-up, 收尾编排]
depends_on: [dream-acceptance-verify, dream-code-commit-sync-workflow, dream-doc-sync-workflow, dream-skill-index-governance, mcp_cognitive]
provides: [completion-orchestration, wrapup-workflow, post-dev-closure, smart-routing-gates]
cognitive_links: [VM-1791537826150-c8b4d95a]
---

## Autonomy Boundary

可自主执行：
- 智能路由（git diff 变更分类）
- 各步骤子 SKILL 调度与状态流转
- FAIL-OPEN 红旗记录与状态汇总
- 认知 record/verify 调用
- 最终报告生成

需用户确认：
- 验收不通过时是否继续后续步骤（默认阻塞）
- 大范围改动是否分阶段执行（new_context 传递状态）
- 涉及实盘交易相关的收尾执行

禁止：
- 跳过验收门禁直接提交代码
- 调用其他编排器（本 SKILL 只调度原子 SKILL）
- 将收尾结论直接作为交易指令执行

---

# Dream Completion Evolution Workflow — 收尾编排器

> **默认名：收尾SKILL**（方便记忆）。与**开工SKILL**（`dream-arch-research-orchestrator`）对称：
> - 开工 = 项目启动闭环（调研→SPEC→评审→PLAN）
> - 收尾 = 项目完成闭环（验收→commit→文档→治理→认知→报告）
> - 两者构成项目完整生命周期：开工启动→执行→收尾闭环。

> **双位置存储**：本 SKILL 同时存在于：
> - `.trae/skills/dream-completion-evolution-workflow/SKILL.md`（TRAE 调用入口，本文件）
> - `1-ARCHITECTURE/skills/dream-completion-evolution-workflow/SKILL.md`（项目级索引发现）

> **本质是编排层（纯调度器）**，自身不做验收/提交/文档同步/治理的具体逻辑，而是调度已有原子 SKILL。编排层不调用其他编排器。

---

## 一、何时调用（触发条件）

满足以下任一条件即应调用本 SKILL：

1. **SPEC 任务开发完成**：SPEC 中某任务/功能/bugfix 代码实现完成，需要收尾闭环
   - 触发词：「收尾」「收尾SKILL」「wrapup」「finish up」「项目收尾」「完成闭环」
2. **AI 准备宣称完成**：任何"完成态"表述前的自动收口
   - 触发词：「做完了」「完成了」「done」「complete」「收个尾」
3. **批量改动收口**：多个文件改动后需要统一验收+提交+文档同步+治理
4. **认知事件驱动**：`record` 时 `tags` 含 `wrapup`，自动触发
   - **hook 配置**：`TAG_HOOKS = {"wrapup": "dream-completion-evolution-workflow"}`
   - **FAIL-OPEN**：hook 异常不影响 record 主流程

**不触发的场景**：
- 纯调研/分析任务（无代码变更）→ 仅调用认知 record
- 模块级 API 接入验收 → 调用 `dream-module-post-dev-verify-workflow`
- 项目启动阶段 → 调用开工SKILL（`dream-arch-research-orchestrator`）

---

## 二、Step 0：智能路由（变更分类）

> **借鉴 GitHub Release Please**：扫描 commit diff 分类变更类型，决定执行哪些步骤。不是所有收尾都需要全 6 步——智能路由避免无效执行。

**输入**：`git diff --stat` + `git status --short` + `git log --oneline -5`

**变更分类矩阵**：

| 变更类型 | 判定 | 执行步骤 | 跳过步骤 |
|----------|------|---------|---------|
| `code-full` | 有 .ts/.py 代码变更 + 测试变更 | 全 6 步 | 无 |
| `code-only` | 仅代码变更，无文档/测试 | 1→2→5→6 | 3→4 |
| `doc-only` | 仅 .md 文档变更 | 3→5→6 | 1→2→4 |
| `bugfix` | commit type=fix + 代码变更 | 1→2→5→6 | 3→4（除非有文档变更） |
| `skill-only` | 仅 SKILL.md 变更 | 4→5→6 | 1→2→3 |
| `config-only` | 仅配置/依赖文件 | 2→5→6 | 1→3→4 |

**输出**：路由决策（步骤执行清单 + 跳过清单）

---

## 三、6 步编排 + 子 SKILL 调度

| 步骤 | 子 SKILL / 工具 | 输入 | 输出 | 门禁类型 |
|------|----------------|------|------|---------|
| **1. 验收门禁** | `dream-acceptance-verify` | 修复方案/需求 | 四文件验收包 | 🚫 硬门禁 |
| **2. 代码提交** | `dream-code-commit-sync-workflow` | git 工作区 | commit hash + 孤儿扫描 | ⚠️ 硬门禁(tsc) |
| **3. 文档同步** | `dream-doc-sync-workflow` | 变更文档路径 | 索引更新 + 校验报告 | ✅ FAIL-OPEN |
| **4. SKILL 治理** | `dream-skill-index-governance` | SKILL 变更 | 注册/版本/依赖检查 | ✅ FAIL-OPEN |
| **5. 认知闭环** | `mcp_cognitive` (record/verify) | 全步骤结果 | 认知记忆 ID | ✅ FAIL-OPEN |
| **6. 最终报告** | 本 SKILL 内部 | 全步骤状态 | 收尾报告 + 红旗清单 | 输出 |

### 步骤 1：验收门禁（硬门禁·不可跳过）

> **借鉴工程实践 DoD**：Microsoft Engineering Playbook "Definition of Done" — 不是"代码写完"而是"质量达标+验证通过+文档更新"。
> **借鉴 GSD Debugger Golden Rule**：不能用原步骤复现并确认症状消失，任何"修复完成"的宣称都无效。

**调度**：调用 `dream-acceptance-verify` 执行五维证据验收：
1. 症状复测（原步骤复测，确认症状消失）
2. 日志证据（grep 修复标记，证明路径执行了）★强制
3. 回归证据（测试全绿，exit=0）
4. 影响面核查（git diff 范围 = 方案声明）
5. 边界验证（≥3 个边界场景）

**产出**：四文件验收包 `acceptance_bundles/<日期>_<标识>/`

**门禁判定**：

| 五维结果 | 判定 | 处置 |
|---------|------|------|
| 全通过 | ✅ 通过 | 进入步骤 2 |
| 有红旗 | 🚩 不通过 | **阻塞后续步骤**，回到开发 |
| 部分通过(降级) | ⚠️ 条件通过 | 需用户确认是否继续 |

---

### 步骤 2：代码提交（硬门禁·tsc/py_compile）

> **借鉴 GitHub 生态**：Release Please 六步链式 detect→bump→push→validate→publish→release；anti-republish guard 防止重复提交。

**调度**：调用 `dream-code-commit-sync-workflow` 执行 7 步提交：
1. 变更解析（git status → 变更清单 + 排除列表）
2. 精确暂存（禁止 `git add .`，逐文件 add）
3. 校验（tsc 硬门禁 + py_compile 硬门禁 + tests 软门禁）
4. Conventional Commit message 生成
5. 提交（git commit + 验证）
6. 孤儿扫描（委托 `dream-code-sync-orphan-scan-workflow`）
7. 提交后四系统同步分发

**门禁判定**：

| tsc/py_compile | 判定 | 处置 |
|---------------|------|------|
| 通过 | ✅ 继续 | 进入步骤 3 |
| 失败 | 🚩 阻塞 | 必须修复后重试 |

**若 Step 0 路由跳过验收**（doc-only/config-only）：本步骤仍执行，但不要求验收包。

---

### 步骤 3：文档+知识库同步（FAIL-OPEN）

> **借鉴产品管理**：DoD 第三支柱 Documentation & Visibility — "如果操作变了，README 或 API 文档必须更新"。

**调度**：调用 `dream-doc-sync-workflow` 执行 7 步文档索引同步：
1. 变更解析（add/delete/modify/move 分类）
2. 更新 `0-系统文档管理/INDEX.md`
3. 更新 `2-KNOWLEDGE` 各域 `INDEX.md`
4. 校验（doc_lint + link_checker）
5. 覆盖率统计（doc_coverage）
6. 飞书 Base 同步
7. 认知 record

**FAIL-OPEN 策略**：
- 校验发现断链 → 告警记录，不阻塞
- 飞书同步失败 → 告警记录，不阻塞
- 标记 `doc-sync-warning` 红旗

**若 Step 0 路由跳过**（code-only 无文档变更）：本步骤跳过。

---

### 步骤 4：SKILL 系统治理（FAIL-OPEN）

> **借鉴项目自身**：`dream-skill-index-governance` 双保险机制——auto_register_skill.py（机器层 post-commit hook）+ AI 层确认。

**调度**：调用 `dream-skill-index-governance` 执行：
1. 注册检查（新 SKILL 是否在 registry 中）
2. 版本一致性（双位置存储是否一致）
3. 依赖检查（depends_on 是否都存在）
4. 漂移监控（实际能力 vs 声明能力）
5. 认知闭环（recall→record→verify→lifecycle advance）

**FAIL-OPEN 策略**：
- 仅在本次变更涉及 SKILL.md 时执行
- 注册失败 → 告警记录，标记 `skill-register-failed` 红旗
- 版本不一致 → 告警，建议手动同步

**若 Step 0 路由跳过**（非 skill-only 变更）：本步骤跳过。但若步骤 2 commit 后 post-commit hook 已自动注册，本步骤做确认即可。

---

### 步骤 5：认知闭环（FAIL-OPEN）

> **借鉴 AI Agent 域**：多步编排完成后必须 record 经验 + verify 验证，形成认知闭环，让系统"越用越聪明"。

**调度**：调用 `mcp_cognitive` 的 `record` + `verify`：

```
record(
  content="[收尾闭环] <变更摘要> | 验收: <pass/fail/skip> | commit: <hash> | 文档: <synced/skip> | SKILL治理: <ok/skip> | 红旗: <N>",
  quality_level="B",
  tags="wrapup,收尾,认知闭环,完成闭环,<域标签>"
)
```

若本次收尾验证了已有记忆（如复用了某条经验）：

```
verify(memory_id="VM-xxx", success=true)
```

**FAIL-OPEN 策略**：record 失败不阻塞收尾流程，仅本地日志记录。

---

### 步骤 6：最终报告（内部生成）

> **借鉴 GitHub 生态**：CI/CD 完成后的 status summary + 红旗清单。

**处理**：汇总全步骤状态，生成收尾报告：

```markdown
# 收尾报告

## 基本信息
- 收尾对象：<SPEC任务/功能/bugfix 描述>
- 收尾时间：YYYY-MM-DD HH:MM
- 关联 commit：<sha>

## 步骤执行矩阵

| 步骤 | 子 SKILL | 执行 | 状态 | 红旗 |
|------|---------|------|------|------|
| 0. 智能路由 | 本 SKILL | ✅ | <变更类型> | - |
| 1. 验收门禁 | dream-acceptance-verify | ✅/⏭️ | <pass/fail/skip> | <N> |
| 2. 代码提交 | dream-code-commit-sync-workflow | ✅/⏭️ | <hash/skip> | <N> |
| 3. 文档同步 | dream-doc-sync-workflow | ✅/⏭️ | <synced/skip> | <N> |
| 4. SKILL 治理 | dream-skill-index-governance | ✅/⏭️ | <ok/skip> | <N> |
| 5. 认知闭环 | mcp_cognitive | ✅ | <memory_id> | - |

## 红旗清单
- <如有红旗，逐条列出，含步骤+原因+建议>

## 收尾结论
- [ ] 全步骤通过 → 收尾完成
- [ ] 有红旗 → 需修复后重验

## 认知记忆
- memory_id: VM-xxx
```

**输出**：收尾报告（存入 `acceptance_bundles/<日期>_<标识>/wrapup_report.md`）

---

## 四、状态机

```
[INIT] → start(task_info)
    ↓
[ROUTING] → git diff 分析 → 路由决策
    ↓
[GATE_ACCEPT] → dream-acceptance-verify → pass? → [COMMIT]
    ↓ fail/block                         ↓
    ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←← [DOC_SYNC]
    ↓                                     ↓
[COMMIT] → dream-code-commit-sync → [DOC_SYNC]
    ↓                                     ↓
[DOC_SYNC] → dream-doc-sync-workflow → [SKILL_GOV]
    ↓                                     ↓
[SKILL_GOV] → dream-skill-index-governance → [COGNITIVE]
    ↓                                               ↓
[COGNITIVE] → mcp_cognitive(record/verify) → [REPORT]
    ↓                                               ↓
[REPORT] → 生成收尾报告 → [DONE]
```

**状态定义**:
- `INIT`: 初始状态
- `ROUTING`: Step 0 智能路由
- `GATE_ACCEPT`: Step 1 验收门禁（硬门禁）
- `COMMIT`: Step 2 代码提交（硬门禁）
- `DOC_SYNC`: Step 3 文档同步（FAIL-OPEN）
- `SKILL_GOV`: Step 4 SKILL 治理（FAIL-OPEN）
- `COGNITIVE`: Step 5 认知闭环（FAIL-OPEN）
- `REPORT`: Step 6 最终报告
- `DONE`: 完成

**转移条件**:
- `pass()`: 当前步骤通过 → 下一步骤（FAIL-OPEN 步骤总是 pass）
- `block()`: 硬门禁不通过 → 阻塞，回到开发
- `skip()`: Step 0 路由决定跳过 → 下一执行步骤

---

## 五、输入输出契约

| 阶段 | 输入 | 输出 |
|------|------|------|
| Step 0 | git diff + git status + git log | 路由决策（执行清单+跳过清单） |
| Step 1 | 修复方案/需求 + 测试 | 四文件验收包（repro_after.log + fix.diff + test.log + acceptance_report.md） |
| Step 2 | git 工作区 | commit hash + 孤儿扫描报告 |
| Step 3 | 变更文档路径列表 | 更新后的 INDEX.md + 校验报告 + 覆盖率 |
| Step 4 | SKILL 变更 | 注册/版本/依赖检查报告 |
| Step 5 | 全步骤结果 | 认知记忆 ID |
| Step 6 | 全步骤状态 | wrapup_report.md |

---

## 六、多领域调研（Step 2 — MANDATORY）

> **项目硬约束**（VM-1790765308904）：SKILL 创建前必须做多领域调研。本节调研 5 域。

### 6.1 工程实践域（Microsoft DoD + GSD Debugger）

| 模式 | 来源 | 在本 SKILL 的应用 |
|------|------|-------------------|
| Definition of Done 四支柱 | Microsoft Engineering Playbook | 步骤 1-4 对应：验证(验收)→质量(提交)→文档(同步)→治理 |
| DoD vs AC 区分 | no-bullshit-agile | 验收=AC(功能对不对)，收尾=DoD(达标没) |
| "未验证≠完成" Red Flag | agent-skills DoD | 步骤 1 验收是硬门禁，跳过=无效收尾 |
| Undone Work + 技术债登记 | no-bullshit-agile | 红旗清单记录未完成项，标记技术债 |

### 6.2 GitHub 生态域（Release Please + CI/CD）

| 模式 | 来源 | 在本 SKILL 的应用 |
|------|------|-------------------|
| 六步链式 detect→bump→validate→publish→release | fp release pipeline | 6 步编排+状态机流转 |
| anti-republish guard | fp release pipeline | 步骤 2 commit 后验证 git log，防止重复提交 |
| smoke test post-build | fp release pipeline | 步骤 1 验收 = smoke test（修复路径真的执行了） |
| Release PR as gate | Release Please | 步骤 1 验收门禁 = 收尾的"Release PR" |
| loop prevention (bot actor + msg filter) | gate-keeper CI/CD | 智能路由 Step 0 避免无效执行循环 |

### 6.3 产品管理域（Launch Checklist + Retrospective）

| 模式 | 来源 | 在本 SKILL 的应用 |
|------|------|-------------------|
| Go-live checklist with sign-off | 产品管理 launch checklist | 步骤 1 验收门禁 = sign-off gate |
| Post-release retrospective | Sprint retrospective | 步骤 6 最终报告 = mini retrospective |
| Rollback plan documented | Launch checklist | 红旗清单含回退建议 |
| Stakeholder acceptance | DoD Release/Milestone | 验收报告含"用户确认"签字位 |

### 6.4 AI Agent 域（Multi-step Orchestration）

| 模式 | 来源 | 在本 SKILL 的应用 |
|------|------|-------------------|
| 状态机编排 INIT→stages→DONE | LangChain/CrewAI | 四、状态机 9 状态流转 |
| FAIL-OPEN 降级 | Agent workflow closure | 步骤 3-5 全部 FAIL-OPEN，失败不阻塞但必记录 |
| 纯调度不重复子能力 | Orchestrator pattern | 编排层只调度原子 SKILL，不调用其他编排器 |
| 认知闭环 record+verify | 项目认知系统 | 步骤 5 认知闭环 |

### 6.5 项目自身域（已有 SKILL 模式）

| 模式 | 来源 | 在本 SKILL 的应用 |
|------|------|-------------------|
| 五维证据验收 | dream-acceptance-verify | 步骤 1 调度 |
| 7 步精确提交 | dream-code-commit-sync-workflow | 步骤 2 调度 |
| 7 步文档同步 | dream-doc-sync-workflow | 步骤 3 调度 |
| 双保险注册 | dream-skill-index-governance | 步骤 4 调度 |
| 双位置存储 | 所有 dream-* SKILL | 本 SKILL 双位置 |
| 认知闭环 record+verify | CLAUDE.md 硬约束 | 步骤 5 执行 |

---

## 七、hermes 反思决策树

```
本次收尾是否值得形成/衍生 SKILL？
├── 是（满足以下任一）：
│   ├── 收尾流程被复用 ≥ 2 次
│   ├── 涉及多步编排（≥ 3 步，本 SKILL 6 步）
│   ├── 涉及多子 SKILL 调度（≥ 2 个，本 SKILL 5 个）
│   └── 用户明确要求「形成 SKILL」
│   → 调用 skill-creator 创建/更新 SKILL
│   → record 经验，tags 含「SKILL,hermes反思,收尾」
│
└── 否（满足以下全部）：
    ├── 一次性收尾
    ├── 仅单步操作
    └── 无复用价值
    → 仅 record 经验
    → tags 不含「SKILL」
```

---

## 八、认知闭环（recall + record + verify）

**任务开始前**（硬约束，不可跳过）：

```
recall(context="收尾 验收 commit 文档同步 认知闭环 编排器", top_k=5, min_quality="C")
```

**任务完成后**（步骤 5）：

```
record(content="[收尾闭环] <变更摘要> | 验收: <pass/fail/skip> | commit: <hash> | 文档: <synced/skip> | SKILL治理: <ok/skip> | 红旗: <N>",
       quality_level="B",
       tags="wrapup,收尾,认知闭环,完成闭环,<域标签>")
verify(memory_id="VM-xxx", success=true)
```

---

## 九、FAIL-OPEN 与异常处理

| 异常场景 | 处理策略 | 门禁类型 |
|----------|---------|---------|
| 验收五维不通过 | **阻塞后续步骤**，回到开发 | 🚫 硬门禁 |
| 验收部分通过(降级) | 需用户确认是否继续 | 🚫 条件门禁 |
| tsc/py_compile 失败 | **阻塞提交**，修复后重试 | 🚫 硬门禁 |
| 文档同步断链 | 告警记录，不阻塞，标记 `doc-sync-warning` | ✅ FAIL-OPEN |
| 飞书同步失败 | 告警记录，不阻塞，标记 `feishu-sync-failed` | ✅ FAIL-OPEN |
| SKILL 注册失败 | 告警记录，不阻塞，标记 `skill-register-failed` | ✅ FAIL-OPEN |
| 认知 record 失败 | 不阻塞，仅本地日志 | ✅ FAIL-OPEN |
| 子 SKILL 不可用 | 跳过该步骤，标记 `skill-unavailable` 红旗 | ✅ FAIL-OPEN |

**核心原则**：
- 硬门禁（验收 + tsc/py_compile）必须通过才继续
- 软门禁/FAIL-OPEN 步骤失败降级为红旗
- 所有红旗必须在步骤 6 最终报告中如实列出
- 红旗不阻塞但不可隐瞒

---

## 十、与开工SKILL的对称关系

| 维度 | 开工SKILL | 收尾SKILL |
|------|----------|----------|
| 名称 | dream-arch-research-orchestrator | dream-completion-evolution-workflow |
| 默认名 | 开工SKILL / kickoff | 收尾SKILL / wrapup |
| 阶段 | 项目启动 | 项目完成 |
| 流程 | 调研→SPEC→评审→PLAN | 验收→commit→文档→治理→认知→报告 |
| 步骤数 | 5 阶段 | 6 步 + Step 0 路由 |
| 门禁 | 每阶段用户确认门 | 验收硬门禁 + 其余 FAIL-OPEN |
| 子 SKILL | dream-contradiction-theory 等 | dream-acceptance-verify 等 |
| 状态机 | INIT→PROBLEM→RESEARCH→SPEC→REVIEW→PLAN→DONE | INIT→ROUTING→GATE_ACCEPT→COMMIT→DOC_SYNC→SKILL_GOV→COGNITIVE→REPORT→DONE |
| 认知闭环 | 每阶段 record + 全流程 verify | 步骤 5 record+verify |
| 对称点 | 用户确认门 = 验收门禁 | 验收门禁 = 用户确认门 |

---

## 十一、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-10-09 | 初始版本，6 步编排 + Step 0 智能路由 + 门禁式 + FAIL-OPEN + 与开工SKILL对称 |
