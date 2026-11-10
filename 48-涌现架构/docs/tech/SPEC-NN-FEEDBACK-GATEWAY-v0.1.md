# SPEC: 48 NN 反馈与训练网关（v0.1 草案）

> 状态：🟡 草案，待 48 SPEC v0.6 评审；不修改 v0.5 已评审正文
> 日期：2026-11-07
> 归属：48 涌现架构（40 主神经网络的唯一对接口）
> 关联：SPEC-49 v0.14；ADR-0002；50-NN主矛盾评估器 SPEC v0.1

## 1. 定位

48 在 NN 闭环链中承担三个职责：

1. **40 的唯一对接口**：39（已入 L0 MCP）、9（纳入 48 统一口径）、全链路交易数据统一经 48 进入 40；39/9 不直连 40。
2. **训练/反馈网关**：50/23 的决策、执行结果、拒单、跳过、PnL → 统一样本 → 训练建议（建议制 + 门禁）。
3. **涌现度量与相变判定**：E5 能力-规模曲线/临界态判据承担“量变→质变”的判定；E0 基线先行。

## 2. 统一数据口径

### 2.1 输入源

| 源 | 接入方式 | 说明 |
|---|---|---|
| 39 金融语义 | L0 MCP（只读） | 已纳入 L0；48 不复制语义定义 |
| 9 基本面分析 | 纳入 48 统一口径 | 统一字段/时间粒度/版本 |
| 18/19/20/21/38 | 只读数据接口 | 行情/特征/宏观 |
| 42 bus 快照 | 只读 | 8 源信号 + 约束/参数 |
| 40/43 | 只读 | 宏观状态/弹性约束 |
| 50/23 决策与执行 | 反馈接口 | 决策、成交、PnL、拒单、跳过 |
| 13/16/22/11 | 只读审计 | 风控/定容/执行/成交 |
| **11 域交易 recall** | 结构化日志（新增） | `trading_recall()` 召回事件：memory_ids、trace_id、coin、direction |
| **4-MEMORY 认知会话** | 结构化日志（新增） | reflection 事件（reflection_id）+ action 事件（active_reflection_id） |
| **48 emergence bus** | 事件流（已有） | 广播联动事件（E1 cascade） |

### 2.2 事件 schema（建议）

```text
decision_id, source(50-nn|23-evolution), symbol, ts,
constraints(constraint_id, band, cap, leverage, asset_count, long_short_count),
signals(source, direction, confidence, horizon, intent, dimension_hint),
evidence(provenance, agreement, conflict_flags),
decision(action, tier, position_mult, primary_contradiction),
execution(order_id, fill, reject_reason, slippage),
pnl(realized, unrealized, fees),
cognitive_recall(trace_id, memory_ids[], ts, coin, direction, source_domain),
reflection(reflection_id, ts, session_id, suggestions_count),
action(action_type, active_reflection_id, ts, changed_decision, detail),
provenance, version
```

**认知链路字段说明（E1/E4 度量数据源）**：

| 字段 | 来源 | 用途 |
|---|---|---|
| `cognitive_recall` | 11 域 `_inject_cognitive_recall` → 48 `e4b_readout.record_recall()` | E4 readout_rate：召回→决策改变 join |
| `reflection` | 4-MEMORY `cognitive_session` 建议生成（reflection_id） | E4 self_correction：反思→修复精确 join 的一端 |
| `action` | 4-MEMORY `cognitive_session.add_action()`（active_reflection_id） | E4 self_correction：反思→修复精确 join 的另一端 |
| emergence bus 事件 | 48 `emergence_bus` shadow 订阅者 | E1 cascade_sigma：级联尺寸/幂律斜率 |

**trace_id 传递规则**：decision_id → cognitive_recall.trace_id → action.trace_id → execution，保证全链路可 join。

- OOD 隔离：沿用 48 §5 纪律；paper/实盘分目录；黑名单/隔离参数入库。
- 版本化：数据 schema、40/50 权重、基因版本、契约版本。
- 数据保留：recall/reflection/action 事件保留期与 W6 样本一致（2000 条 rolling），脱敏（无 API key/凭证/原文）。

## 3. 训练网关

| 目标 | 输入 | 输出 | 门禁 |
|---|---|---|---|
| 40 主神经网络 | 48 统一数据、E5 度量 | 训练建议（不直接改权重） | 40 P5/P6（DEC-29）；建议制 + 审计 |
| 50 主矛盾评估器 | 50 决策/执行/PnL + 48 数据 | 50 权重/策略更新建议 | 50 训练门禁（待定）；provenance 隔离 |
| 23（对照） | 只读其输出 | **不训练、不改动** | 23 独立；仅作为对照基线 |

> 训练建议必须记录：提出者、数据版本、评估指标、采纳/拒绝、回滚点。

### 3.1 40 输入迁移（M6 修复）

40 当前直读 39/9；切换 48 为唯一对接口需要：

1. 40 侧输入适配器（48 schema → 40 既有输入字段）；
2. **双读校验**：48 与直读并行，值差异在容忍范围内才切换；
3. 切换开关（`ENABLE_40_VIA_48=0` 默认关）；
4. 40 P5/P6 门禁不变；切换不得改变既有 encoder 维度/权重。

### 3.2 数据保留与访问（Minor）

- 保留期：W6 样本 2000 条；交易全链路数据按 DEC-27；训练数据版本化。
- 访问控制：仅 48 训练网关与 50/40 训练进程可读；执行/审计数据脱敏（无 API key/凭证）。
- OOD 隔离与黑名单参数沿用 48 §5 纪律。

## 4. 基因登记（gene registry）

| 流向 | 内容 | 规则 |
|---|---|---|
| **48 → 40** | 数据/训练/度量 | 主供体；遵守 40 门禁 |
| **NN → 23** | 50 验证过的优质基因 | 经 42→23 shadow 端口；选择性采纳；不破坏 23 主链 |
| **23 → NN** | **仅设计参考/复制** | 不做持续基因流；不 import；不构成运行时依赖 |

字段：`gene_id, source, version, module|config, shadow_evidence, promotion_state, rollback`。

## 5. 对照实验（23 vs 50）

- 同一输入快照，48 汇总两链输出；
- 指标：方向一致率、主矛盾维度一致率、置信度校准、paper PnL、最大回撤、换手率、W6 归因覆盖率、无双计审计；
- ≥4-8 周 shadow；评审后决定 live 灰度/收敛；
- 23 的运行时状态不被 50/48 写入（48 只读其输出）。

## 6. 与 48 v0.5 现有 Phase 的关系

| Phase | 关系 |
|---|---|
| E0 基线 | 训练/对照的前置；E0b 回放器仍是缺口 |
| E1 广播总线 | 可复用为 NN 链事件通道（shadow） |
| E2 做梦器 | 可作为训练建议/假设生成的上游（后续） |
| E3 coupling 反事实 | 训练数据因果校验 |
| E4 度量面板 | 扩展为 NN 链 KPI（方向/维度/校准/PnL） |
| E5 规模相变 | 承担“量变→质变”判定 |
| E6 需求驱动闭环 | 与 50 训练建议接口对接 |

## 7. 边界

- 48 不直接改 40/50 权重；不直接下单；不写 23。
- 39 语义定义仍以 39 为准；48 只消费不复制。
- 9 纳入 48 后，9 的原始能力/输出仍以 9 为准，48 做统一口径适配。
- 任何扩域需 48 SPEC v0.6 评审（DEC-42）。

## 8. 待办

1. 48 SPEC v0.6：统一数据 schema + 训练网关 + 基因登记评审。
2. E0b 回放器补齐（训练/对照前置）。
3. NN 链 KPI 接入 E4 度量面板。
4. 与 50 R4 对齐训练建议接口与门禁。
5. **认知链路数据采集（E1/E4 脱离 pipeline_only 前置）**：
   - 11 域 `_inject_cognitive_recall` 增加结构化 recall 日志（调用 48 `e4b_readout.record_recall()`）；
   - 排查并修复 `active_reflection_id` 覆盖率 0% 问题（4-MEMORY `cognitive_session` 建议生成链路）；
   - `e4b_reflection.py` 升级为 `active_reflection_id` 精确 join（替代时序代理）；
   - 交易域 recall 数据 ≥30 条 + reflection_id 覆盖率 ≥30% 后，E4 readout/self-correction 脱离 `pipeline_only`。