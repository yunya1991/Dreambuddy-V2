---
name: dream-module-post-dev-verify-workflow
description: "Orchestrates 7-step post-dev module verification: boundary identify → public API list → integration point grep → test run → artifact log check → doc alignment → cognitive closure. Invoke when a module is 'dev complete' to catch 'coded but not wired' regressions before commit."
version: 1.0.0
created: 2026-10-07
updated: 2026-10-07
license: Internal
status: active
category: orchestration
triggers: [模块开发完成, 模块验证, 接入检查, 文档对齐, dev complete, post-dev verify, 模块验收]
depends_on: [dream-doc-sync-workflow, dream-code-sync-orphan-scan-workflow]
provides: [module-post-dev-verify, integration-audit, doc-alignment-check]
cognitive_links: []
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


# Dream Module Post-Dev Verify Workflow — 模块开发完成自动验证工作流

> 把"模块开发完成 → 公开 API 清单 → 接入点全量 grep → 测试运行 → 产物日志验证 → 文档对齐 → 认知闭环"的 7 步流程固化为可复用编排。本 SKILL 是**模块验收的最后一道防线**，专门捕获"代码写完但未接入/未生成文档/未跑测试"的回归——这是用户反复踩到的反模式。

> **双位置存储**：本 SKILL 同时存在于：
> - `.trae/skills/dream-module-post-dev-verify-workflow/SKILL.md`（TRAE 调用入口，本文件）
> - `1-ARCHITECTURE/skills/dream-module-post-dev-verify-workflow/SKILL.md`（项目级索引发现）

> **与相邻 SKILL 的边界**：
> - `dream-code-sync-orphan-scan-workflow`：commit **后**前端 .tsx 孤儿扫描（对象=前端组件）
> - `dream-code-commit-sync-workflow`：commit **驱动**全流程（commit 前/后编排）
> - `dream-doc-sync-workflow`：文档索引同步（对象=已有 .md）
> - **本 SKILL**：模块**开发完成 → 验证**全栈编排（对象=刚写完的模块代码 + 它的文档 + 它的接入点）

---

## 一、为何需要本 SKILL（痛点来源）

> 用户原话（2026-10-07）：「感觉好几次代码开发完都没有按照流程接入，导致开发了反而没用」

典型事故（反模式）：
1. **param_center 4 任务全部完成**：65/65 测试 GREEN、3 条认知经验已 record+verify，但 `16-调控系统/docs/` 完全无 param_center 文档、INDEX.md 未提，开发了反而"在文档体系中隐形"。
2. 子系统调用过的新 API 没有写入 `docs/API_SPEC.md`，下游模块不知道有这能力，自己重写一份。
3. 模块测试通过但 `artifacts/` 无任何运行证据，无法判断是否真在生产路径上跑过。

本 SKILL 把这些反模式在"开发完成"那一刻一次性暴露，避免遗忘。

---

## 二、何时调用（触发条件）

满足以下任一条件即应调用本 SKILL：

1. **模块开发完成**：刚完成一个模块/子系统的代码（TDD GREEN 之后、commit 之前）
   - 触发词：「模块开发完了」「验证模块」「接入检查」「post-dev verify」「模块验收」
2. **功能落地收口**：SPEC 系列任务（D/F/O/M/P）做完，需要在 commit 前自检
   - 触发词：「SPEC 落地完成」「验证接入」
3. **认知事件驱动**：认知系统 `record` 时 `tags` 含 `post-dev-verify`，自动触发
   - **hook 配置**：`TAG_HOOKS = {"post-dev-verify": "dream-module-post-dev-verify-workflow"}`
   - **FAIL-OPEN**：hook 异常不影响 record 主流程
4. **批量任务收尾**：连续完成多个子任务（如 param_center 4 任务），统一做一次验收
5. **疑似失联排查**：模块已开发但下游"不知道有这能力"，反向追查接入点

**不触发的场景**：
- 单文件小修复（无新公开 API）→ 跳过本 SKILL
- 纯文档同步（无代码变更）→ 调用 `dream-doc-sync-workflow`
- commit 后孤儿扫描 → 调用 `dream-code-sync-orphan-scan-workflow`
- 用户未说"完成"（开发中）→ 等用户宣告

---

## 三、核心约束（硬规则）

| 编号 | 约束 | 说明 |
|------|------|------|
| HC-1 | 模块边界先识别 | 不识别边界就 grep 会污染结果（命中其它模块同名 API） |
| HC-2 | 公开 API 必须全量枚举 | 从 `__all__` 或 `api.py` 的 `def` 提取，不能遗漏 |
| HC-3 | 接入点必须有真实引用 | grep 命中数 = 0 → 红旗（"开发了反而没用"反模式） |
| HC-4 | 测试 0 errors 才算 GREEN | 部分失败也算未通过 |
| HC-5 | 产物日志必须存在 | `artifacts/<module>/` 至少 1 个文件，证明真跑过 |
| HC-6 | 文档三处对齐 | (a) 模块自身 README/SPEC；(b) 所属子系统 docs/；(c) `0-系统文档管理/INDEX.md` |
| HC-7 | 认知闭环不可跳过 | 必须 record + verify，tags 含 `post-dev-verify` |

---

## 四、7 步标准流程

### 步骤 1：模块边界识别（确定验证范围）

**输入**：用户提供的模块根路径（如 `16-调控系统/scripts/param_center/`）

**处理**：

```bash
# 1. 确认模块根存在
ls <module_root>

# 2. 列出模块内全部 .py 文件（排除 tests/、__pycache__/）
Glob: <module_root>/**/*.py  (排除 tests/, __pycache__/)

# 3. 读 __init__.py 提取 __all__（公开 API 契约）
Read: <module_root>/__init__.py
```

**判定**：

| 状态 | 判定 | 处置 |
|------|------|------|
| 模块根不存在 | 路径错误 | 终止 + 询问用户实际路径 |
| 无 `__init__.py` | 不是 Python 包 | 退化为目录扫描（按 .py 文件枚举） |
| `__all__` 为空 | 未明确公开 API | 走步骤 2 的 `api.py` 兜底 |

**输出**：模块边界报告（路径 + .py 文件清单 + `__all__` 列表）

---

### 步骤 2：公开 API 清单（grep "def "）

**输入**：步骤 1 的模块边界

**处理**：

```bash
# 1. 优先从 __all__ 提取
# 2. 兜底：grep 所有 def 定义
Grep: "^def |^class " --type py --path <module_root>  (排除 tests/)

# 3. 重点扫描 api.py（对外契约层）
Grep: "^def " --type py --path <module_root>/api.py
```

**判定**：

| 文件 | 角色 | 必检项 |
|------|------|--------|
| `api.py` | 对外契约 | 每个 def 是否在 `__all__` |
| `__init__.py` | 包入口 | 是否 re-export 了 api.py 的全部公开 def |
| `adapters/` 等子目录 | 内部组件 | 不强制对外（可跳过接入检查） |

**输出**：公开 API 清单（函数名 + 文件:行号 + 是否对外）

---

### 步骤 3：接入点验证（grep 每个公开 API 在子系统的引用）

**输入**：步骤 2 的公开 API 清单

**处理**：

```bash
# 对每个对外公开 API，全仓 grep 它的引用点
Grep: "<api_name>" --path /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2  (排除 module_root 自身 + tests/)
```

**判定**：

| grep 命中数 | 含义 | 处置 |
|------------|------|------|
| = 0 | 无人调用 | 🚩 **红旗**：开发了反而没用，必接入或转 shadow |
| = 1（仅 1 个子系统） | 单点接入 | ⚠️ 检查是否应被更多子系统使用 |
| ≥ 2 | 多点接入 | ✅ 正常 |
| 命中点都在 tests/ | 仅测试引用 | 🚩 **红旗**：未进入生产路径 |

**输出**：接入点报告（API → 引用文件清单 + 红旗清单）

---

### 步骤 4：测试运行（pytest 全套）

**输入**：模块的 `tests/` 目录

**处理**：

```bash
# 1. 运行全部测试
pytest <module_root>/tests/ -v --tb=short

# 2. 输出测试矩阵
pytest <module_root>/tests/ --collect-only -q
```

**判定**：

| 状态 | 判定 | 处置 |
|------|------|------|
| 全部 GREEN | 通过 | ✅ 进入步骤 5 |
| 有 FAIL | 失败 | 🚩 必须修复后重跑 |
| 有 ERROR | 异常 | 🚩 必须修复后重跑 |
| 0 tests collected | 无测试 | 🚩 必须补测试（TDD 反模式） |

**输出**：测试报告（passed/failed/error 计数 + 失败清单）

---

### 步骤 5：产物日志验证（artifacts/ 目录检查）

**输入**：模块对应的 artifacts 路径

**处理**：

```bash
# 1. 定位 artifacts 目录
Glob: <parent>/artifacts/<module_name>/**

# 2. 读最近的运行产物（按修改时间排序）
ls -lt <parent>/artifacts/<module_name>/ | head -5
```

**判定**：

| 状态 | 含义 | 处置 |
|------|------|------|
| 目录存在 + ≥ 1 文件 | 已跑过 | ✅ 记录最近产物路径 |
| 目录存在但空 | 跑过但未持久化 | ⚠️ 检查持久化逻辑 |
| 目录不存在 | 从未真跑 | 🚩 即使 tests GREEN，生产路径未触发，需补 e2e |

**输出**：产物日志报告（路径 + 最近修改时间 + 内容预览）

---

### 步骤 6：文档对齐（三处同步检查）

**输入**：步骤 1-5 的验证结果

**处理**：

```bash
# (a) 模块自身文档
Glob: <module_root>/*.md            # 是否有 README/SPEC
Glob: <module_root>/docs/*.md       # 是否有 docs 子目录

# (b) 所属子系统 docs/
# 例：param_center 属于 16-调控系统，应被 16-调控系统/docs/ENGINEERING_INDEX.md 提及
Grep: "<module_name>" --path <subsystem>/docs/

# (c) 0-系统文档管理/INDEX.md
Grep: "<module_name>" --path 0-系统文档管理/INDEX.md
```

**判定**：

| 检查项 | 状态 | 处置 |
|--------|------|------|
| (a) 模块自身文档 | 有 README 或 SPEC | ✅ |
| (a) 模块自身文档 | 无 | 🚩 创建 `<module_root>/README.md`（精简版：定位/对外 API/依赖/接入点） |
| (b) 子系统 docs 提及 | grep 命中 | ✅ |
| (b) 子系统 docs 未提及 | grep 0 命中 | 🚩 在 `ENGINEERING_INDEX.md` 加一节 |
| (c) INDEX.md 提及 | grep 命中 | ✅ |
| (c) INDEX.md 未提及 | grep 0 命中 | ⚠️ 评估是否需要进 INDEX（子系统级一般由 docs 间接覆盖即可） |

**输出**：文档对齐报告（三处状态 + 缺失清单）

**调用链**：本步骤若发现文档缺失，触发 `dream-doc-sync-workflow` 做同步。

---

### 步骤 7：认知闭环（record + verify）

**输入**：步骤 1-6 的全部验证结果

**处理**：

```
record(
  content="[模块开发完成验证] module=<name> | API=<N> 接入点=<M> 红旗=<R> | tests=<passed>/<total> | artifacts=<yes/no> | 文档三处对齐=<a/b/c 状态> | 关键教训: <一句话>",
  quality_level="B",
  tags="post-dev-verify,模块验收,<domain>域,FAIL-OPEN,认知闭环"
)

# 如验证了已有记忆
verify(memory_id="VM-xxx", success=true)
```

**输出**：认知记忆 ID + 验证报告全量

---

## 五、输入输出契约

| 阶段 | 输入 | 输出 |
|------|------|------|
| 步骤 1 | 模块根路径 | 模块边界报告（.py 清单 + __all__） |
| 步骤 2 | 模块边界 | 公开 API 清单（函数名 + 行号 + 对外标记） |
| 步骤 3 | 公开 API 清单 | 接入点报告（API → 引用清单 + 红旗） |
| 步骤 4 | tests/ 目录 | 测试报告（pass/fail/error 计数） |
| 步骤 5 | artifacts 路径 | 产物日志报告（路径 + 最近修改时间） |
| 步骤 6 | 模块路径 + 子系统路径 | 文档对齐报告（三处状态） |
| 步骤 7 | 全部验证结果 | 认知记忆 ID + 全量验证报告 |

---

## 六、多领域调研（Step 2 — MANDATORY）

> **项目硬约束**（VM-1790765308904）：SKILL 创建前必须做多领域调研。本节调研 3 域：技术开发 + GitHub 生态 + 产品管理。

### 6.1 技术开发域（Linux Kernel MAINTAINERS + K8s Diátaxis）

**核心借鉴**：

| 模式 | 来源 | 在本 SKILL 的应用 |
|------|------|-------------------|
| `Status: Supported` 标签 | Linux Kernel MAINTAINERS | 步骤 3 接入点状态（integrated / orphan / shadow-only） |
| `Diátaxis` 四象限分类 | K8s 文档体系 | 步骤 6 文档三处对齐：Tutorial + How-to + Reference + Explanation |
| `Make target` 全量验证 | Linux Kernel `make test` | 步骤 4 测试运行必跑全套 |
| `Coverage gate` | CI/CD 工程 | 步骤 3 接入点 = 0 触发红旗（类比 coverage 0% 失败） |

**关键洞察**：Linux Kernel 的 MAINTAINERS 文件用 `Status: Supported` 区分"有人维护"vs"Orphan"。本 SKILL 步骤 3 借鉴此模式，把接入点状态分为 `integrated`（已接入）/ `orphan`（无人调用）/ `shadow-only`（仅测试引用），三态对应不同处置。

### 6.2 GitHub 生态域（codecov + GitHub Actions）

**核心借鉴**：

| 模式 | 来源 | 在本 SKILL 的应用 |
|------|------|-------------------|
| `coverage gate` 失败 | Codecov CI gate | 步骤 3 接入点 = 0 → 直接 RED（不通过） |
| `workflow-run-action` | GitHub Actions 历史查询 | 步骤 5 artifacts 目录 = GitHub Actions 的运行产物归档 |
| `git log -S "<api_name>"` | Git pickaxe | 步骤 3 接入点 0 命中时溯源：是"从未接入"还是"曾接入后回退" |
| `dependabot` 依赖图 | GitHub 生态 | 步骤 2 公开 API 清单 = 本模块对外暴露的"接口契约" |
| `OWNERS` 文件 | Chromium / Kubernetes | 步骤 7 记忆 record 含 owner 标签（可选扩展） |

**关键洞察**：GitHub Actions 的 `workflow-run-action` 把每次 CI 运行的 artifacts 归档，本 SKILL 步骤 5 借鉴此模式，用 `artifacts/<module>/` 目录的存在性判断"是否真跑过"——这是测试 GREEN 之外的第二道证据。

### 6.3 产品管理域（Amazon PR/FAQ + Google Design Doc）

**核心借鉴**：

| 模式 | 来源 | 在本 SKILL 的应用 |
|------|------|-------------------|
| `Working Backwards` | Amazon PR/FAQ | 从"模块开发完成后应该是什么状态"倒推 7 步 |
| `Definition of Done` | Agile / Scrum | "完成" = 7 步全 GREEN，不只是代码写完 |
| `Design Doc lifecycle` | Google | 模块文档三态：proposed（仅 SPEC）→ shadow（开发中）→ active（开发完+接入） |
| `Launch Checklist` | Google SRE 上线检查清单 | 本 SKILL = 模块的 Launch Checklist |
| `Single-threaded leader` | Amazon | 每个模块应有一个 owner（步骤 7 record 含 owner tag） |

**关键洞察**：Amazon 的 `Definition of Done` 概念最关键——"代码写完" ≠ "完成"，必须 API 接入 + 测试 GREEN + 产物日志 + 文档对齐 + 认知闭环全部通过才算完成。本 SKILL 是 DoD 的自动化检查器，对应 Google SRE 的 Launch Checklist。

### 6.4 调研总结：3 域融合的设计决策

| 设计决策 | 借鉴来源 | 体现在 SKILL 的 |
|----------|----------|-----------------|
| 接入点三态标签 | Linux Kernel MAINTAINERS + GitHub pickaxe | 步骤 3 |
| `Definition of Done` 7 项检查器 | Amazon PR/FAQ + Agile DoD | 步骤 1-7 全流程 |
| `Coverage gate` 红旗机制 | Codecov CI | 步骤 3 接入点 = 0 触发红旗 |
| `Artifacts 归档` 验证 | GitHub Actions workflow-run | 步骤 5 |
| `Diátaxis` 文档四象限 | K8s 文档体系 | 步骤 6 文档三处对齐 |
| `Launch Checklist` 模式 | Google SRE | 本 SKILL 整体定位 |
| `定期 Review` + verify 升级 | 文档生命周期 | 步骤 7 |

---

## 七、相关 SKILL 与工具

| 类型 | 名称 | 用途 |
|------|------|------|
| 上游 | `dream-tdd-dev-workflow` | 模块开发的 RED-GREEN-REFACTOR 循环 |
| 下游 | `dream-code-commit-sync-workflow` | 验证通过后驱动 commit |
| 同构 | `dream-code-sync-orphan-scan-workflow` | commit 后孤儿扫描（对象不同：前端组件 vs 后端模块） |
| 同构 | `dream-doc-sync-workflow` | 文档索引同步（步骤 6 触发） |
| 同构 | `dream-backtest-verify` | 交易子系统回测验证（专用于策略） |
| 元 | `skill-creator` | 本 SKILL 的创建工具 |
| 工具 | `Glob` | 步骤 1 模块边界 + 步骤 5 artifacts 扫描 |
| 工具 | `Grep` | 步骤 2 公开 API + 步骤 3 接入点 + 步骤 6 文档对齐 |
| 工具 | `pytest` | 步骤 4 测试运行 |
| 认知 | `recall`/`record`/`verify` | 步骤 7 认知闭环 |

---

## 八、hermes 反思决策树

> 引用元 SKILL `dream-qwen-eval-collab` 第五节决策树模式。

```
本次模块开发完成是否值得形成/衍生 SKILL？
├── 是（满足以下任一）：
│   ├── 流程被复用 ≥ 2 次（本 SKILL 已是第 1 次正式化，但用户多次踩到反模式）
│   ├── 涉及多步编排（≥ 3 步，本 SKILL 7 步）
│   ├── 涉及多工具调用（Glob + Grep + pytest + record，≥ 4 个）
│   └── 用户明确要求「形成 SKILL」（本次用户已明确要求）
│   → 调用 skill-creator 创建新 SKILL
│   → record 经验，tags 含「SKILL,hermes反思,post-dev-verify」
│
└── 否（满足以下全部）：
    ├── 一次性单文件改动
    ├── 无新公开 API
    └── 无文档/接入变更
    → 仅 record 经验
    → tags 不含「SKILL」
```

---

## 九、FAIL-OPEN 与异常处理

| 异常场景 | 处理策略 |
|----------|---------|
| 模块根路径不存在 | 终止 + 询问用户实际路径 |
| `__init__.py` 缺失 | 退化为目录扫描，记录告警 `no-package-init` |
| `api.py` 缺失 | 步骤 2 兜底用 `__all__` 或全量 `def` grep |
| grep 接入点 = 0 | 🚩 红旗，不阻塞流程，但步骤 7 record 必须含 `red-flag` tag |
| pytest 失败 | 🚩 必须修复后才能进入 commit（与 `dream-code-commit-sync-workflow` HC 一致） |
| `artifacts/` 不存在 | 🚩 红旗，记录告警 `no-artifacts-evidence` |
| 文档三处全缺失 | 🚩 红旗，触发 `dream-doc-sync-workflow` 自动补齐 |
| 认知 record 失败 | 不阻塞验证，仅本地日志记录 |
| 模块属于"实验性"（experiments/） | 降低文档要求（README 即可），跳过 INDEX.md 检查 |

**核心原则**：验证永不阻塞 commit 主流程（commit 由 `dream-code-commit-sync-workflow` 决定），但所有红旗必须在认知 record 中如实标记，由用户决定是否阻塞。

---

## 十、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-10-07 | 初始版本，7 步流程 + 3 域调研 + 双触发模式（用户主动+认知事件驱动）+ FAIL-OPEN。来源：用户痛点「开发了反而没用」+ param_center 4 任务收口验证 |
