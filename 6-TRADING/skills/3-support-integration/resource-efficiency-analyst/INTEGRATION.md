# resource-efficiency-analyst 集成规范 (Process D — RE Token 效率监控)

> **原始 SKILL**: dream-multiskill-v2/skills/3-SUPPORT/resource-efficiency-analyst/SKILL.md v1.0
> **集成位置**: Process D Step 1.5c（DA + CC 完成后）+ 独立日报（每日 06:00）
> **触发时机**: ① Process D 中作为 Step 1.5c 运行 ② 独立日报定时任务（每日）

---

## 一、职责

监控 6-TRADING 最耗 Token 的操作（Team A 3 并行 Agent + master-seminar），在 dream-cost-control 的硬预算上限触发前，提供早期 Token 消耗异常预警（50% 飙升即告警）。

**角色定位**: 只读 + 只写建议报告。不修改配置，不调用接口，不膨胀。

---

## 二、6-TRADING Token 消耗基线（估算）

| 操作 | 估算 Token/次 | 频率 | 月估算 |
|------|-------------|------|--------|
| Screen 1 A1 (调研) | ~8,000 | 每周 | ~32,000 |
| Screen 1 A2 (第一性原理) | ~6,000 | 每周 | ~24,000 |
| Screen 1 A3 (沙盘) | ~7,000 | 每周 | ~28,000 |
| master-seminar (4-6 大师) | ~12,000 | 每周 | ~48,000 |
| Screen 2 (日线，每天) | ~15,000 | 每工作日 | ~300,000 |
| Process D (完整) | ~20,000 | 每周 | ~80,000 |
| dream-data-analysis | ~3,000 | 每周 | ~12,000 |
| dream-oneirology | ~2,000 | 每周 | ~8,000 |

**异常基准**: 任何操作单次消耗超过估算 50% → 立即告警。

---

## 三、四条铁律（强制保留，不修改）

```
铁律一: 不做深度推理 → 只统计、只对比，一次出结果
铁律二: 不做全量扫描 → 只读 Process D 当次产出的最新 1 份报告
铁律三: 无变化不输出 → 数据无异常则输出 "今日数据无异常变化"（≤50字）
铁律四: 每次最多 3 条建议 → 每条必须附 预计节省 Token 数 + 风险评估
```

---

## 四、输入规范（6-TRADING 版）

Process D Step 1.5c 运行时，只读取：
- `sessions/{latest_session}/review/data-analysis-report.json`（DA 输出）
- `sessions/{latest_session}/review/cost-report.json`（CC 输出）
- 本次 Process D 触发时的 session 元数据（不读历史）

---

## 五、输出规范

写入 `sessions/{latest_session}/review/efficiency-report.md`:

```markdown
# 资源效率报告 2026-05-27

## Token 消耗概览
| 操作 | 本次估算 | 基线 | 变化 | 状态 |
|:----|:------:|:---:|:---:|:---:|
| Screen 1 A1/A2/A3 (并行) | ~21,000 | ~21,000 | +0% | 🟢 |
| master-seminar (强化6大师) | ~18,000 | ~12,000 | +50% | 🔴 |
| Process D 完整 | ~22,000 | ~20,000 | +10% | 🟢 |

## 异常告警
🔴 master-seminar 本次消耗超基线 50%（强化模式触发频率上升）

## 降本建议 (最多3条)
### 建议1: 优化 master-seminar 强化触发条件
- 操作: 将 red_team_flag 触发强化模式的阈值从 ">40%" 提高到 ">55%"
- 预计节省: ~6,000 tokens/次，约 ~24,000/月
- 风险: 低 — 适当放宽红队警报阈值，不影响主要偏见检测
- 审批: 需 D3 proposal → 人工确认

## 结论
master-seminar 强化模式触发过于频繁，建议评估 red_team_flag 触发条件。
```

---

## 六、独立日报任务（可选）

若需要每日监控（不仅限于 Process D）：

```
CronCreate 建议: "0 6 * * *"（每日 06:00，与 Process D 同时间，但独立运行）
触发提示词: 运行 resource-efficiency-analyst，读取昨日最新 1 份报告，按四条铁律输出效率日报，写入 review/efficiency-report.md
```

> ⚠️ 独立日报是可选扩展，不在当前 4 个主 CronCreate 任务内。如需启用，手动创建新 Job。

---

## 七、与其他 SKILL 的接口

| 接口 | 方向 | 说明 |
|------|------|------|
| dream-cost-control → resource-efficiency-analyst | 输入 | cost-report 提供 API 用量基础数据 |
| resource-efficiency-analyst → D3 | 输出 | 效率建议可转化为 `martingale_param_update` 或 `trigger_prompt_patch` 提案 |
| 50% 飙升告警 → dream-cost-control | 通知 | 触发 CC P1 预算告警（协同预警，不重复） |

---

*最后更新: 2026-05-27 v1.0 | 集成 resource-efficiency-analyst v1.0 → Process D RE*
