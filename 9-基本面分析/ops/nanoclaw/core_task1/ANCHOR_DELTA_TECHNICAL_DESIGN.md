# 新闻分析锚点-增量技术设计

**版本**: v1.0  
**日期**: 2026-03-18  
**范围**: `core_task1` 新闻简报与事件账本链路

## 1. 目标

将新闻分析从“按时间窗全量重算”升级为“早餐锚点 + 日内增量修订”，避免每次运行都从头开始，提升参数与趋势演化的连续性。

## 2. 设计原则

- 锚点优先：每日仅一次高质量早餐锚点，作为当日统一基线
- 增量更新：日内仅计算相对锚点的变化，不重置全局解释
- 可追溯：每次锚点和增量都写入 registry，支持审计和复盘
- 向后兼容：保留现有 V9.3/V9.8 账本、brief 产物与参数体系

## 3. 数据结构

### 3.1 锚点登记簿

- 路径：`raw/anchor_registry.jsonl`
- 单行对象核心字段：
  - `anchor_id`, `anchor_date`, `generated_at`
  - `market_trend_state`, `market_trend_meta`
  - `params`（平均信号、负面占比、高风险占比、窗口开启率等）
  - `signal_snapshot`（composite/macro/industry/company/recommendation/position）
  - `event_map`（按标题簇聚合的事件基线）
  - `top_narratives`

### 3.2 增量登记簿

- 路径：`raw/delta_registry.jsonl`
- 单行对象核心字段：
  - `update_id`, `anchor_id`, `anchor_date`, `generated_at`
  - `changes`（新增/消退/保留事件计数，分数漂移，动作漂移）
  - `param_drift`（相对锚点的参数漂移）
  - `signal_snapshot`（本次运行信号快照）

### 3.3 状态快照文件

- 锚点快照：`raw/anchor_snapshot_YYYYMMDD_HHMM.json`
- 增量快照：`raw/delta_update_YYYYMMDD_HHMM.json`

## 4. 模式与调度语义

- `anchor`: 写入新锚点
- `delta`: 读取锚点并写入增量变化
- `reset`: 强制重建锚点（用于异常恢复）
- `auto`: 若当日无锚点则 `anchor`，否则 `delta`

CLI 新参数：

- `--update-mode {auto,anchor,delta,reset}`
- `--anchor-date YYYY-MM-DD`
- `--force-anchor`

## 5. 关键算法

### 5.1 事件映射

- 使用标题簇键（已有 `_cluster_key`）构建 `event_map`
- 保留每簇核心字段：事件类型、风险动作、可信度、叙事状态、有效分数

### 5.2 增量变化检测

- 集合差：
  - `added = current - anchor`
  - `resolved = anchor - current`
  - `retained = current ∩ anchor`
- retained 内变化：
  - `|community_effective_score_delta| >= 0.2` 记为分数漂移
  - `risk_action_proposal` 变化记为动作漂移

### 5.3 参数漂移

针对以下指标记录 `anchor/current/delta`：

- `avg_signal_score`
- `negative_ratio`
- `high_risk_ratio`
- `active_narrative_ratio`
- `window_gate_open_ratio`
- `expectation_unknown_ratio_macro`

## 6. 与现有链路关系

- 不替换 `event_ledger`、`brief_v1/v3`、`methodology_changelog`
- 在原有结果上新增状态层输出，供 `/fundamental/news` 展示“相对早餐变化”
- 保持已有 schema 与风险门控不变

## 7. 失败与回退

- `delta` 模式找不到锚点：自动回退到 `anchor` 并写入锚点
- 写 registry 失败：抛出异常，保持流程显式失败，不静默吞错
- 模式错误输入：由 argparse choices 直接阻断

## 8. 验收标准

- 同一天首次 `auto` 运行生成锚点，后续 `auto` 运行生成增量
- 增量结果包含新增/消退/漂移三类变化
- 所有产物写入 `raw/` 并在返回对象中暴露路径
- 旧命令不带新参数仍可成功执行
