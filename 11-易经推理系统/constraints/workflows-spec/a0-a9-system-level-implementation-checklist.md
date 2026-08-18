# A0-A9 协议与三大闭环系统级实现清单

## 0. 目标定义

- 目标：把当前“函数级 A0-A9 入口能力”升级为“系统级协议编排能力”。
- 范围：执行环、情报环、治理环，以及跨环通信协议、状态机、审计与重试。
- 完成标准：满足 `trading-communication-protocol-v2.md` 的字段、触发、状态、重试和可观测性要求。

## 1. P0（必须先完成）

### P0-1 统一消息协议对象

- [ ] 新建统一协议模块（建议：`workflows/trading-decision/protocol/`）
- [ ] 实现 `MessageHeader` 与 `Envelope` 结构（含字段校验）
- [ ] 落地字段：
  - `message_id`
  - `timestamp`
  - `version`
  - `source`
  - `target`
  - `type`
  - `priority`
  - `correlation_id`
  - `trace_id`
  - `loop_type`
  - `timeout_ms`
- [ ] 各阶段入口输出统一封装为 `{"header": ..., "payload": ...}`

### P0-2 统一必填契约字段

- [ ] 为 A0-A9 阶段结果补齐：
  - `constraint_version`
  - `memory_refs[]`
  - `evidence_refs[]`
  - `producer`
  - `schema_version`
- [ ] 在测试中增加缺字段即失败（fail-closed）断言

### P0-3 A6 五级路由引擎

- [ ] 在 A6 增加分级评估器：`L0/L1/L1.5/L2/L3`
- [ ] 实现路由矩阵：
  - `L0 -> A9`
  - `L1 -> A4`
  - `L1.5 -> A2`
  - `L2 -> observe/log`
  - `L3 -> A1 + A3`
- [ ] 输出标准化情报事件（`type=EVENT/REQUEST`, `loop_type=intelligence`）

### P0-4 执行环基础编排器

- [ ] 实现 `A1 -> A2 -> A3 -> A4 -> A5 -> A9` 串行调度器
- [ ] 支持失败回跳：
  - `A4 fail -> A3`
  - `A5 fail -> A4`
- [ ] 串联统一 `trace_id` 并生成全链路摘要

## 2. P1（应完成）

### P1-1 治理环编排器

- [ ] 实现 `A7 -> A8 -> A2/A3` 调度
- [ ] 实现 `A9 -> A7` 事件触发
- [ ] 实现 A8 定时触发（每日 14:00）接口层（先可本地 cron 适配）

### P1-2 传输抽象层（HTTP + MQ）

- [ ] 同步通道：HTTP 适配器（执行环、治理环）
- [ ] 异步通道：MQ 适配器（情报环）
- [ ] 提供本地 mock transport，保证单测不依赖外部中间件

### P1-3 状态机与错误语义

- [ ] 实现全局状态机（IDLE/SIGNAL/RESEARCH/.../VERIFICATION）
- [ ] 统一错误码：
  - `CONSTRAINT_VALIDATION_FAILED`
  - `MEMORY_REFERENCE_MISSING`
  - `EVIDENCE_INCOMPLETE`
  - `SANDBOX_REGRESSION`
- [ ] 实现超时、重试、降级逻辑

## 3. P2（增强）

### P2-1 处罚与信誉机制

- [ ] 模块级评分、连续失败惩罚、恢复条件
- [ ] 与治理环审计结果联动

### P2-2 可观测性与回放

- [ ] 按 `trace_id` 全链路日志索引
- [ ] 增加链路回放工具（输入摘要、输出摘要、耗时、状态）
- [ ] 增加指标看板（成功率、平均耗时、重试率、失败分布）

## 4. 测试清单

- [ ] 协议对象单测：字段完整性、类型校验、非法输入拒绝
- [ ] 执行环编排测试：正常流、A4 回跳、A5 回跳
- [ ] 情报环路由测试：L0/L1/L1.5/L2/L3 全覆盖
- [ ] 治理环测试：A9->A7->A8->A2/A3 回写闭环
- [ ] 端到端集成测试：三环并行与冲突场景
- [ ] 门禁测试：协议字段缺失即阻断

## 5. 交付物清单

- [ ] `workflows/trading-decision/protocol/*`
- [ ] `workflows/trading-decision/orchestrator/*`
- [ ] `workflows/trading-decision/transports/*`
- [ ] `tests/test_trading_protocol_*.py`
- [ ] `tests/test_trading_orchestrator_*.py`
- [ ] `constraints/workflows-spec/trading.md` 同步系统级状态
- [ ] `constraints/workflows-spec/communication-contract-v0.1.md` 增补同步记录

## 6. 完成验收标准

- [ ] 三大闭环触发路径全部可执行且有自动化测试覆盖
- [ ] 协议字段在主链产物中全量可追溯
- [ ] 任一阶段失败可定位、可回放、可重试
- [ ] 与记忆 L4 交互具备标准化输入输出契约
- [ ] CI 门禁新增系统级闭环检查并通过
