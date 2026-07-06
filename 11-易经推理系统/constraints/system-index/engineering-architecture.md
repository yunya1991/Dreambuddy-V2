# Dream-MultiSkill 工程架构基线（v1.0）

## 1. 文档定位

本文件是 Dream-MultiSkill 的工程架构基线，用于统一以下事项：

- 分层关系与职责边界
- 工作流通信与调用方向
- 经验沉淀到约束的闭环机制
- 版本治理、审计与回滚规则

适用范围：`constraints/`、`workflows/`、`artifacts/`、`skills/`、`docs/`。

## 2. 总体架构分层

```text
┌─────────────────────────────────────────────────┐
│ 底层约束层 (constraints/)                      │
│ - constitution/ - system-index/                │
│ - workflows-spec/ - faq/                       │
└─────────────────────────────────────────────────┘
                    ↓ 约束
┌─────────────────────────────────────────────────┐
│ 记忆工作流 (workflows/memory/) - 底座         │
│ - L1/L2/L3/L4 + review + distill + index + stats │
└─────────────────────────────────────────────────┘
                    ↓ 服务
┌─────────────────────────────────────────────────┐
│ 并联工作流 (四条线)                            │
│ - governance/ trading-decision/ knowledge/ evolution/ │
└─────────────────────────────────────────────────┘
```

核心原则：

- 约束层是唯一规则源（SSOT）。
- 记忆工作流是共享底座，不直接改写约束层。
- 并联工作流按职责分工协作，统一输出到 `artifacts/`。

## 3. 目录架构（当前标准）

```text
dream-multiskill-v2/
├── constraints/
│   ├── constitution/
│   ├── system-index/
│   ├── workflows-spec/
│   └── faq/
├── workflows/
│   ├── memory/
│   ├── trading-decision/
│   ├── governance/
│   ├── knowledge/
│   └── evolution/
├── skills/
├── artifacts/
│   ├── trading/
│   ├── memory/
│   ├── governance/
│   ├── knowledge/
│   └── evolution/
├── docs/
└── .github/workflows/
```

## 4. 三大初期迁移对象与职责

### 4.1 底层约束层（constraints）

- `constitution/`：系统最高约束与原则。
- `system-index/`：架构索引、组件边界、依赖地图。
- `workflows-spec/`：各工作流输入/输出契约、阶段责任、门禁规则。
- `faq/`：常见运行约束与外部系统问答（如 OKX API）。

### 4.2 记忆工作流（workflows/memory）

- 作为底座提供查询、回写、蒸馏、索引、统计服务。
- 维护 L1-L4 生命周期与可追溯证据链。
- 为交易决策和并联工作流提供经验支撑。

### 4.3 交易决策工作流（workflows/trading-decision）

- 承担 A0-A9 决策链编排与产物输出。
- 每阶段执行前后都必须带约束校验与记忆引用。
- 输出统一落地到 `artifacts/trading/`。

## 5. 通信与调用结构（必须遵守）

### 5.1 方向约束

- `constraints -> memory / trading-decision / governance / knowledge / evolution`
- `memory -> trading-decision`（服务调用）
- `trading-decision -> memory`（回写 episode/case）
- `memory -> evolution`（提交约束候选）
- `evolution -> constraints`（唯一允许的约束升级通道）

### 5.2 禁止项

- 禁止 `memory` 直接修改 `constraints`。
- 禁止 `trading-decision` 绕过约束校验直接执行关键动作。
- 禁止无 `trace_id` 和无证据引用的产物进入主链。

## 6. 记忆沉淀到约束的闭环（关键机制）

```text
memory 经验沉淀
  -> 形成 constraint_candidate
  -> evolution/feedback 接收
  -> evolution/audit 评估
  -> evolution/sandbox 回放与压测
  -> (通过) 写入 constraints 新版本
  -> (失败) 驳回并记录原因
  -> evolution/rollback 持续监控与回滚
```

闭环规则：

- 经验升格为制度必须经过 `workflows/evolution/`。
- 每条约束变更都要绑定来源证据：`episode_id/case_id/distill_id`。
- 所有约束发布必须可回放、可审计、可回滚。

## 7. 统一数据契约（v1）

建议所有关键产物统一包含：

- `trace_id`：一次完整决策链唯一 ID
- `stage_id`：A0-A9 或 memory 子阶段标识
- `constraint_version`：执行时使用的约束版本
- `memory_refs[]`：引用的记忆实体 ID
- `evidence_refs[]`：证据文件路径或证据 ID
- `timestamp`：UTC 时间戳
- `decision_summary`：阶段结论摘要

## 8. 运行与治理要求

- Fail-closed：约束校验失败时默认中止关键执行。
- 审计优先：所有主链动作必须可生成审计产物。
- 小步发布：约束升级先沙箱，后主链。
- 回滚可用：每个约束版本都要有回滚目标。

## 9. 构建顺序（执行建议）

1. 固化约束层基线与工作流契约文档。
2. 接入 memory 与 trading-decision 的最小同步调用链。
3. 打通 `memory -> evolution -> constraints` 升级闭环。
4. 建立架构门禁（字段完整性、版本一致性、证据可追溯）。

## 10. 版本信息

- 版本：v1.0
- 状态：基线生效
- 维护目录：`constraints/system-index/`
- 对应通信契约：`constraints/workflows-spec/communication-contract-v0.1.md`
