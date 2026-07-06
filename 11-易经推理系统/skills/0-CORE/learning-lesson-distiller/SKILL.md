---
name: learning-lesson-distiller
description: 从 episodes 蒸馏 lessons（规则/禁令/偏好），引入频次与严重度阈值，防止“1 次失败=1 条死规则”的噪声过拟合。
license: Internal
---

# Learning Lesson Distiller

## 目标

- 将 L1 事实（episodes）聚合成 L2 规律（lessons），并保持统计稳健性
- 产出可用于 recall 与门禁的结构化条目，并携带证据引用

## 何时使用

- Step 6 盘后进化
- 每日/每周批处理蒸馏

## 输入（建议字段）

- `episodes_path`
- `window`
  - `last_n_episodes`
  - `time_range`
- `thresholds`
  - `min_frequency`
  - `min_severity`
  - `min_unique_traces`
  - `cooldown_episodes`
- `taxonomy`
  - `symbols_prefix`: `S_` / `F_`
  - `reason_codes`

## 输出

- `lessons_delta`
  - `added[]`
  - `updated[]`
  - `deprecated[]`
- `stats`
  - `symbol_counts`
  - `severity_summary`
- `evidence_refs[]`

## 过程

1. 读取窗口内 episodes，统计 `F_*` / `S_*` 的频次与共现
2. 仅对满足阈值的模式生成/更新 lessons
3. 对低频噪声模式标注为观察中（不晋升为硬规则）
4. 输出 delta（新增/更新/废弃）与可追溯证据引用

## 验证

- 任意新增 lesson 必须包含：触发条件、行动建议、reason_codes、evidence_refs
- 若窗口不足或数据缺失，必须输出 fail-closed（不新增硬规则）

## Contract v0.1（最小审计契约）
- 输入建议包含：`trace_id`、`ts`、`inst_id`（用于产物审计）
- 输出必须包含：`lessons_delta`、`evidence_refs[]`

## Integration
- 上游：`learning-episode-writer` 的 episodes
- 下游：`learning-recall-pack`（召回）、`learning-proposal-generator`（将稳定规律转为治理变更）、`memory-budget-policy`（晋升/降级计划）
- 约定：仅对满足阈值的模式晋升为 lessons，避免低频噪声固化

## Fail-Closed
- 若窗口不足或关键字段缺失：不新增硬规则，并输出可审计原因码
