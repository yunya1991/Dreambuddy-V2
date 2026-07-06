# 交易自动化流程规范（A0-A9）

定义 A0-A9 交易自动化流程、三大闭环架构、通信协议落地基线与当前实现一致性状态。

## 1. 权威协议文档（v2）

- 完整版协议与三大闭环架构已沉淀至：`constraints/workflows-spec/trading-communication-protocol-v2.md`
- 该文档是交易自动化流程在约束层的权威设计输入，覆盖：
  - 三大闭环：执行环 / 情报环 / 治理环
  - 通信协议：消息头、消息类型、传输模式、触发机制
  - 状态机、处罚与重试机制、实现示例

## 2. A0-A9 入口映射（已落地）

- `A0`：`workflows/trading-decision/A0_contradiction/entrypoint.py`
- `A1`：`workflows/trading-decision/A1_research/entrypoint.py`
- `A2`：`workflows/trading-decision/A2_first-principles/entrypoint.py`
- `A3`：`workflows/trading-decision/A3_simulation/entrypoint.py`
- `A4`：`workflows/trading-decision/A4_validation/entrypoint.py`
- `A5`：`workflows/trading-decision/A5_execution/entrypoint.py`
- `A6`：`workflows/trading-decision/A6_intelligence/entrypoint.py`
- `A7`：`workflows/trading-decision/A7_audit/entrypoint.py`
- `A8`：`workflows/trading-decision/A8_theory-practice/entrypoint.py`
- `A9`：`workflows/trading-decision/A9_exit/entrypoint.py`

## 3. 三大闭环目标链路（规范态）

- 执行环（Execution Loop）：`A1 -> A2 -> A3 -> A4 -> A5 -> A9`
- 情报环（Intelligence Loop）：`A6(L0/L1/L1.5/L2/L3) -> A9/A4/A2/observe/A1+A3`
- 治理环（Governance Loop）：`A0 -> A7 -> A8 -> A2/A3`

## 4. 实现一致性审计（2026-05-11）

### 4.1 审计范围

- 对照文档：`constraints/workflows-spec/trading-communication-protocol-v2.md`
- 对照实现：`workflows/trading-decision/A0~A9/entrypoint.py`
- 对照测试：`tests/test_trading_decision_a0_a2_entrypoints.py`、`tests/test_trading_decision_a3_a5_entrypoints.py`、`tests/test_trading_decision_a6_a9_entrypoints.py`

### 4.2 检查结论

- **已实现**
  - A0-A9 阶段入口函数已存在且可执行。
  - 各阶段产物可落地至 `artifacts/trading/`。
  - 各阶段基础字段 `stage_id`、`trace_id`、`timestamp` 已写入结果。
  - 分阶段入口测试通过：`13 passed`。
- **部分实现 / 未实现**
  - 未统一实现协议 `header` 对象（`message_id`、`version`、`source`、`target`、`type`、`priority`、`correlation_id`、`loop_type`、`timeout_ms`）。
  - 未统一实现契约字段：`constraint_version`、`memory_refs[]`、`evidence_refs[]`、`producer`、`schema_version`。
  - 未实现三大闭环编排器（当前是独立入口函数，不是端到端流程调度）。
  - 未实现 A6 `L0/L1/L1.5/L2/L3` 分级触发到 A9/A4/A2/A1+A3 的强约束路由。
  - 未实现治理环 `A7 -> A8 -> A2/A3` 的定时触发（每日 14:00）与自动修正回写。
  - 未实现协议层传输适配（HTTP/MQ）与重试处罚机制。

### 4.3 判定

- 当前状态为：**“阶段能力已迁移（函数级）”**，但尚未达到 **“协议与三大闭环编排完整实现（系统级）”**。

## 5. 技能清单（已迁移）

- 第一批（A0-A2）：
  - `skills/1-TRADE/dream-contradiction-theory/SKILL.md`
  - `skills/1-TRADE/dream-strategy-research/SKILL.md`
  - `skills/1-TRADE/dream-first-principles/SKILL.md`
- 第二批（A3-A5）：
  - `skills/1-TRADE/dream-strategy-designer/SKILL.md`
  - `skills/1-TRADE/dream-strategy-parser/SKILL.md`
  - `skills/1-TRADE/dream-tactical-validator/SKILL.md`
  - `skills/1-TRADE/dream-pretrade-gatekeeper/SKILL.md`
  - `skills/1-TRADE/dream-tactical-executor/SKILL.md`
- 第三批（A6-A9）：
  - `skills/1-TRADE/dream-intelligence-monitor/SKILL.md`
  - `skills/1-TRADE/dream-signal-scoring-spec/SKILL.md`
  - `skills/1-TRADE/dream-regime-detector/SKILL.md`
  - `skills/1-TRADE/A7-practice-theory/SKILL.md`
  - `skills/1-TRADE/A8-theory-practice-verification/SKILL.md`
  - `skills/1-TRADE/dream-exit-skill-v2/SKILL.md`

## 6. 后续约束（按优先级）

- `P0`：补齐统一消息头封装与必填契约字段，保证 A0-A9 全阶段输出同构。
- `P0`：实现 A6 分级路由编排（L0/L1/L1.5/L2/L3 -> 目标阶段）。
- `P1`：实现执行环与治理环调度器（含 A7->A8->A2/A3 回写）。
- `P1`：落地协议层适配（同步 HTTP + 异步 MQ 抽象接口）。
- `P2`：补齐处罚、重试、审计日志和回放能力。
