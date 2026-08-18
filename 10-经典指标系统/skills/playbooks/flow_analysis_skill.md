# 资金流分析 SKILL（外生资金 + 内生杠杆 + 链上行为 → Regime 信号）

更新时间：2026-03-16
状态：Draft（规划先行，不改代码）

## 1. 定位与边界

本 SKILL 作为“资金流分析”模块的工程化蓝图，与新闻分析 SKILL 同级，目标是把以下三类资金维度统一为可分层统计的状态机输出：

- 外生资金（Exogenous）
- 内生杠杆与仓位（Endogenous Positioning）
- 链上与交易所行为（Onchain & Venue Behavior）

本 SKILL 当前定位为研究与风控建议层，不直接触发交易写操作：

- 默认输出 `bias/filter/risk-off` 研究信号与统计报告
- 如需联动执行层，必须通过既有审批与审计链路（R2/R3）

## 2. 核心目标输出

与《基本面分析文档》对齐，最小输出集为：

- `FlowTrend`：方向偏置（bias）
- `FlowImpulse`：变化冲量（filter 辅助）
- `FlowStress`：风险压力（risk-off 主因子）
- `regime_stats`：分状态统计报告（趋势/杠杆/宏观）

输出用途：

- bias：决定方向偏置（long/short/neutral）
- filter：决定是否允许常规执行（enable/disable/slowdown）
- risk-off：决定是否进入降风险模式（hold/reduce/hedge/stop_loss）

## 3. 与新闻分析 SKILL 的同级关系

统一口径：

- 两者同属 `fundamental` 研究域的核心子技能
- 两者都遵循 `skills/SKILLS_技术文档规范.md` 的分级、契约、幂等、限流与证据链规则
- 两者都以 NanoClaw 作为后续可编排执行域

职责分工：

- 新闻分析 SKILL：事件/预期差/风险动作建议
- 资金流分析 SKILL：资金状态机与压力框架
- 融合层（后续）：新闻事件与 FlowStress 联动的门禁建议

## 4. 运行域与能力分级（规划态）

建议拆分为四段能力，保持“计划-执行分离”，并避免“本地脚本直跑”绕开 outbox/receipt 证据链：

1) `flow.analysis.collect.request`（R2 / outbox_channel）
- 仅入队采集请求，不在高权限入口直接外联抓取

2) `nanoclaw.flow.collector`（R1 / sandbox_script）
- NanoClaw 执行采集与清洗，产出原始快照与质量报告

3) `nanoclaw.flow.features_and_regime`（R1 / sandbox_script）
- 计算标准化特征、`FlowTrend/FlowImpulse/FlowStress` 与 regime 标签（趋势/杠杆/宏观/流动性）

4) `nanoclaw.flow.report.generate`（R1 / sandbox_script）
- 生成分状态统计与研究报告（Markdown + JSON）

可选扩展（后续）：

- `flow.analysis.publish.request`（R2 / outbox_channel）：将研究结果投递到只读看板或消息通道

## 5. 数据层设计（与三层框架对齐）

传统金融取长补短的落地约束：

- “资金流/仓位/风险”拆成三条独立线：Flow（净增量资金）、Positioning（杠杆与仓位拥挤）、Stress（流动性与保证金冲击）；对应输出 `FlowTrend/FlowImpulse/FlowStress`，严禁等权混成一个方向分数。
- “量纲归一”优先：流量类指标必须可比化（除以市值/成交额/OI/交易所储备等），避免规模效应主导结论。
- “修订/回填”入模与门禁：revision/backfilled/suspect 进入置信度惩罚与 filter 规则，而不是仅作为日志。

### 5.1 外生资金层（Exogenous）

优先指标：

- ETF 申赎净额、托管余额变化
- 稳定币净发行/净赎回、交易所稳定币余额
- 宏观代理：DXY、真实利率、信用利差、风险偏好

### 5.2 内生杠杆层（Endogenous）

优先指标：

- 资金费率、基差、OI 变化
- 多空清算额、清算密度、保证金压力
- 期权 IV/skew/gamma-vanna 暴露变化

### 5.3 链上与场内行为层（Onchain & Venue）

优先指标：

- 交易所净流入流出（BTC/稳定币）、交易所余额
- 大额地址行为（实体聚类后）
- 矿工/LTH/STH 供给释放

### 5.4 质量与降级（强制）

统一质量枚举：

- `ok/stale/missing/backfilled/suspect`

关键约束：

- `FlowStress` 缺失时 fail-closed，不得放松风险建议
- 输出必须披露 coverage 与 missing_data
- 任一关键指标若发生修订/回填：必须标记 `backfilled/suspect`，并对 `confidence` 与 `filter` 施加惩罚

## 6. 合成方法（先进性方案）

第一阶段（可解释优先）：

1. 对各指标做量纲归一与可比化（按指标字典约定的 normalize_by：市值/成交额/OI/储备等）
2. 对归一化序列做异常处理与缺失标记（winsorize + quality tag）
3. 使用滚动稳健标准化（median/MAD）与分位数映射（rolling percentile），避免固定阈值在制度切换时失效
4. 对标准化序列做平滑与变化提取（EMA + Δ）
5. 形成三条独立线的合成指标（不相互替代）：
   - `FlowTrend_t = Σ w_flow * z_smooth_{flow,t}`（净增量资金偏置）
   - `FlowImpulse_t = Σ w_flow * Δz_{flow,t}`（变化冲量与过滤辅助）
   - `FlowStress_t = Σ w_stress * stress_score_{t}`（尾部压力与脆弱性，含流动性/冲击成本压力项）

第二阶段（增强但不替代）：

- 同源冗余压缩（PCA/聚类）
- 非线性风险分类器（GBDT/RF）用于识别脆弱状态（默认只用于 stress 与 filter，不直接输出方向）
- 尾部风险校准（EVT/分位回归）用于把 `FlowStress` 映射为可控的 risk-off 强度

## 7. Regime 分层统计（强制验收）

至少三维状态面板：

1. 趋势/区间（trend_strength × vol_bucket）
2. 杠杆拥挤/去杠杆（funding/OI/liquidation percentiles）
3. 宏观 risk-on/off（美元流动性与风险偏好代理）

可选第四维：

4. 流动性/冲击成本 regime（深度/冲击成本/价差代理；缺盘口时用成交额与高频波动代理）

每个 regime 单元必须输出：

- 胜率、期望收益、最大回撤、尾部损失分位数
- 覆盖率（coverage）
- 领先/滞后检验（k-step forward）

## 8. NanoClaw 编排草案（最小 tool_plan）

1. 生成 `trace_id/run_id/policy_version`
2. 入队 `flow.analysis.collect.request`
3. NanoClaw 执行采集并落盘 raw + quality
4. 执行 regime 分类并产出三指标与状态标签
5. 生成分状态统计报告与摘要
6. 写入 outbox 事件链：`tool.plan → tool.start → tool.result → tool.plan.done`
7. 输出可消费的只读信号对象（供 `/fundamental/flows` 展示）

## 9. 契约草案（初版）

### 9.1 request（R2 入队）

```json
{
  "event": "flow.analysis.collect.request",
  "trace_id": "uuid",
  "idempotency_key": "sha256(trace_id+asset+window+policy_version)",
  "requested_at": "2026-03-16T00:00:00Z",
  "payload": {
    "asset": "BTC",
    "window": "24h",
    "freq": "1h",
    "policy_version": "flow_skill_v0",
    "output_root": "ops/nanoclaw/core_task1/flow"
  }
}
```

### 9.2 receipt（执行回执）

```json
{
  "event": "flow.analysis.collect.receipt",
  "trace_id": "uuid",
  "idempotency_key": "same_as_request",
  "ok": true,
  "artifacts": {
    "raw_path": "ops/nanoclaw/core_task1/flow/raw/flow_collection_*.json",
    "regime_path": "ops/nanoclaw/core_task1/flow/outputs/flow_regime_*.json",
    "report_path": "ops/nanoclaw/core_task1/flow/outputs/flow_analysis_*.md"
  },
  "quality": {
    "overall_quality": "ok",
    "coverage": 0.86,
    "missing_data": []
  },
  "errors": []
}
```

## 10. 产物目录建议

沿用现有 NanoClaw 目录并扩展标准化产物：

```text
ops/nanoclaw/core_task1/flow/
  raw/
    flow_collection_*.json
    flow_quality_*.json
  outputs/
    flow_regime_*.json
    flow_analysis_*.md
    flow_regime_stats_*.json
  scripts/
    flow_collector.py
    regime_classifier.py
```

## 11. 分阶段落地路线（先进性规划）

Phase 0（先于一切）：

- 固化数据字典与质量枚举，并版本化（policy_version）
- 固化量纲归一规则（normalize_by）与修订/回填门禁语义（revision/backfilled/suspect）

Phase A（两周）：

- 先落地最小指标集（优先低噪声口径），并补齐历史窗口以支持稳健标准化与分位数
- 固化三指标计算口径（Trend/Impulse/Stress）与只读输出对象（含 evidence 与 quality）
- 固化最小 regime 统计模板（至少三维 + 流动性第四维占位）

Phase B（四周）：

- 引入分状态统计验收与 walk-forward（分 regime 验收胜率/尾部/回撤/coverage）
- 引入跨源一致性与供应商质量评分，完善熔断与降级路径
- 引入 `FlowStress` 的尾部校准与风险动作映射表（仍保持只读建议）

Phase C（后续）：

- 接入新闻事件门禁联动（只读）：事件窗口内以风险优先为主，对 filter/risk-off 施加门禁约束
- 引入非线性脆弱性分类器与压力测试场景（stress 专用）
- 引入多资产扩展（BTC → ETH → 主流篮子）与跨市场 proxy
- 对接统一风险看板与自动化告警通道（R2 outbox publish）

## 12. 验收基线（初版）

- 契约通过率：>= 99%
- 关键字段完备率（time/url/quality）：>= 99%
- `FlowStress` 可用率：>= 95%
- Regime 覆盖率：>= 80%
- 报告可回放率（trace_id 串联全链路）：= 100%

---

本文件为“先规划、后实现”的初步 SKILL 文档。下一步进入实现时，优先补齐 schema（contracts）与 catalog 索引条目，再进入脚本与调度改造。
