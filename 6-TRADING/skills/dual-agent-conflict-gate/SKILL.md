---
name: dual-agent-conflict-gate
description: 双代理协作冲突前置门禁。每次 agent 开始任务前调用，读取 git status / 分支状态，检查文件边界、共享文件占用、契约冻结级别与并行条件，输出 SAFE / WARNING / BLOCK + reason_codes。触发词：冲突检查、协作门禁、任务前检查、conflict gate、开始任务
version: "1.0"
created: "2026-05-17"
status: "已上线"
---

# Dual-Agent Conflict Gate：双代理协作冲突前置门禁

> 每次 agent 开始一个任务前**必须**主动调用本 SKILL。
> 输出 `BLOCK` 时不得继续执行任务，必须先解决冲突。

---

## 目标

在双代理并行开发中，防止以下四类问题在任务执行后才被发现：

- **文件边界冲突**：触碰对方主责域的文件
- **共享文件占用冲突**：共享文件已被另一代理修改中
- **契约未冻结冲突**：依赖的接口契约尚未达到 L1，不具备并行条件
- **并行条件不满足**：边界不清、输入输出不清、存在同文件依赖

---

## 输入

```json
{
  "agent_id": "claude | solo",
  "task_name": "任务名称",
  "task_description": "任务描述（可选）",
  "files_to_modify": ["路径1", "路径2"],
  "contracts_depended": ["contract名称1"],
  "branch": "当前工作分支（可选，脚本自动读取）"
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `agent_id` | ✅ | 当前代理身份：`claude` 或 `solo` |
| `task_name` | ✅ | 任务名称，用于审计记录 |
| `files_to_modify` | ✅ | 本次任务计划修改的文件列表 |
| `contracts_depended` | ✅ | 本次任务依赖的契约名称列表（无依赖传 `[]`） |
| `task_description` | ❌ | 任务描述，辅助冲突判断 |
| `branch` | ❌ | 自动从 `git branch --show-current` 读取 |

---

## 输出

```json
{
  "decision": "SAFE | WARNING | BLOCK",
  "reason_codes": [],
  "conflict_details": [],
  "git_snapshot": {
    "branch": "...",
    "modified_files": [],
    "untracked_files": [],
    "staged_files": []
  },
  "recommended_action": "..."
}
```

| decision | 含义 | agent 行为 |
|----------|------|-----------|
| `SAFE` | 无冲突，可执行 | 继续任务 |
| `WARNING` | 存在潜在风险，可执行但需留意 | 继续任务，在任务卡中记录风险 |
| `BLOCK` | 存在明确冲突，禁止继续 | 停止任务，按 `recommended_action` 处理 |

---

## reason_codes 说明

| code | 级别 | 含义 |
|------|------|------|
| `BOUNDARY_VIOLATION` | BLOCK | 计划修改的文件属于对方主责域 |
| `SHARED_FILE_CONFLICT` | BLOCK | 共享文件已有未提交修改（git dirty） |
| `CONTRACT_NOT_FROZEN` | BLOCK | 依赖的契约未达到 L1 冻结级别 |
| `PARALLEL_CONDITION_FAILED` | BLOCK | 并行三条件不满足（边界/输入输出/同文件依赖） |
| `WRONG_BRANCH` | BLOCK | 当前分支不是对应的 `agent/*` 分支 |
| `MILESTONE_BRANCH_DIRTY` | WARNING | `milestone/*` 分支有未合并变更 |
| `UNTRACKED_SHARED_FILE` | WARNING | 共享文件区有未追踪文件 |
| `CONTRACT_LEVEL_L0` | WARNING | 依赖契约为 L0（临时），不建议并行依赖 |

---

## 决策规则

### 1. 分支检查（fail-closed）

- 当前分支必须匹配 `agent/{agent_id}/*` 格式
- 在 `main` 或 `milestone/*` 分支上直接提交 → `BLOCK` + `WRONG_BRANCH`

### 2. 文件边界检查

对照主责域配置（`gatekeeper_config.json`）：

- `claude` 计划修改 SOLO 主责域文件 → `BLOCK` + `BOUNDARY_VIOLATION`
- `solo` 计划修改 Claude Code 主责域文件 → `BLOCK` + `BOUNDARY_VIOLATION`
- 双方均不能直接修改"需申请"共享文件，未在任务板中登记占用 → `BLOCK` + `SHARED_FILE_CONFLICT`

### 3. git status 检查

自动执行 `git status --porcelain`，提取当前仓库脏文件列表：

- 脏文件与本次 `files_to_modify` 有交叉且属于共享文件 → `BLOCK` + `SHARED_FILE_CONFLICT`
- 脏文件属于对方主责域（另一代理正在修改） → `BLOCK` + `BOUNDARY_VIOLATION`
- `milestone/*` 分支存在未合并变更 → `WARNING` + `MILESTONE_BRANCH_DIRTY`

### 4. 契约冻结级别检查

对照 `gatekeeper_config.json` 中的契约注册表：

- 契约不存在于注册表 → `BLOCK` + `CONTRACT_NOT_FROZEN`
- 契约级别为 `L0` → `WARNING` + `CONTRACT_LEVEL_L0`
- 契约级别为 `L1` 或 `L2` → 通过

### 5. 并行条件三检

自动检查以下三条是否同时满足：

1. `files_to_modify` 与对方主责域无交叉（边界清楚）
2. `contracts_depended` 全部达到 L1（输入输出清楚）
3. `git status` 中无同名文件被另一代理修改（无同文件依赖）

三条全满足 → `SAFE`；任一不满足 → `BLOCK` + `PARALLEL_CONDITION_FAILED`

---

## 合规要求

1. **每次任务开始前必须调用**，不得跳过
2. 输出 `BLOCK` 时任务**必须暂停**，不得绕过
3. 冲突裁决规则：
   - 小冲突（`WARNING`）：agent 自行记录，继续推进
   - 中冲突（`BLOCK` 单项）：由 SOLO 裁决并更新协作底座
   - 大冲突（`BLOCK` 多项）：暂停并行，退回上一冻结点，用户介入
4. 每次检查结果应写入任务卡的"冲突检查记录"字段

---

## 调用示例

```bash
python3 scripts/conflict_gate.py \
  --agent claude \
  --task "搭建 ops-ui 页面壳" \
  --files "7-ARTIFACT-HUB-V2/src/ops-ui/index.ts,7-ARTIFACT-HUB-V2/src/ops-ui/health.ts" \
  --contracts "health-summary.v1"
```

输出示例（SAFE）：

```json
{
  "decision": "SAFE",
  "reason_codes": [],
  "conflict_details": [],
  "git_snapshot": {
    "branch": "agent/claude/ops-ui-shell",
    "modified_files": [],
    "untracked_files": [],
    "staged_files": []
  },
  "recommended_action": "可以继续执行任务。"
}
```

输出示例（BLOCK）：

```json
{
  "decision": "BLOCK",
  "reason_codes": ["BOUNDARY_VIOLATION", "CONTRACT_NOT_FROZEN"],
  "conflict_details": [
    "文件 7-ARTIFACT-HUB-V2/src/router-engine.ts 属于 SOLO 主责域",
    "契约 workflow-summary.v1 尚未注册，未达到 L1"
  ],
  "git_snapshot": {
    "branch": "agent/claude/ops-ui-shell",
    "modified_files": ["7-ARTIFACT-HUB-V2/src/router-engine.ts"],
    "untracked_files": [],
    "staged_files": []
  },
  "recommended_action": "停止任务。请联系 SOLO 将 router-engine.ts 相关变更收口，并等待 workflow-summary.v1 契约冻结至 L1 后再并行。"
}
```

---

## 与协作底座文档的对应关系

| 本 SKILL 检查项 | 协作文档章节 |
|----------------|------------|
| 文件边界检查 | §5 主责域划分 |
| 共享文件占用检查 | §9 共享文件规则 |
| 契约冻结级别检查 | §8 契约冻结机制 |
| 并行条件三检 | §6.4 并行条件 |
| 分支规则检查 | §7 分支与里程碑规则 |
| 冲突裁决建议 | §12 冲突处理机制 |
