# dream-performance-review 集成规范 (Process D — PR 量化 SKILL 评估)

> **原始 SKILL**: dream-multiskill-v2/skills/3-SUPPORT/dream-performance-review/SKILL.md v4.0.0
> **集成位置**: Process D Step 0 前置（与 OE + A8 并行）
> **触发时机**: 每周一 06:00 Process D，在 OE+A8 并行启动的同时运行

---

## 一、职责

对 6-TRADING pipeline 中的关键 SKILL 做 5 维量化评分，让 Process D 的 A8 复盘从定性转向定量；D 级 SKILL 触发改进计划（PIP）或替换提案，关闭改进闭环。

---

## 二、触发条件（6-TRADING 版）

| 触发场景 | 时机 | 模式 |
|---------|------|------|
| 常规周度评估 | 每周一 Process D Step 0 | 评估全部关键 SKILL |
| dream-cost-control D 级告警 | cost-report.d_grade_skills 非空 | 仅评估告警 SKILL |
| consecutive_skip_count ≥ 7 (梦游) | OE 或 B9 触发 | 重点评估 B6 Gate C + B3 评分 |

---

## 三、6-TRADING 关键 SKILL 评估清单

| SKILL ID | SKILL 名称 | 核心评估指标 | 数据来源 |
|---------|-----------|-----------|---------|
| B3 | dream-signal-scoring-spec | 8维评分 vs 实际 PnL 方向准确率 | episode.json outcome |
| B6 | dream-pretrade-gatekeeper | Gate C 通过率 / SKIP 后 PnL 对比 | episode.json gate.result |
| B9 | learning-episode-writer | episode.json 字段完整率 | 抽查 episode schema |
| IA | dream-intelligence-analysis | BIAS_FLAG 标记频率 vs 后续预测准确率 | a1/a2-contradiction.md |
| MS | master-seminar | adjusted_score 方向 vs 实际 PnL 一致率 | master-debate.json |
| DA | dream-data-analysis | calibration_suggestions 被 D3 采纳率 | weekly-proposals.json |
| D2 | learning-lesson-distiller | lesson 在后续 episode 中的验证命中率 | cross-session 追踪 |
| OE | dream-oneirology | compulsive_skip_analysis 预警准确率 | episode skip vs alert timing |

---

## 四、5 维评分体系（6-TRADING 适配）

| 维度 | 权重 | 6-TRADING 计算方式 |
|------|------|-----------------|
| 执行准确率 | 30% | 该 SKILL 参与的 episode → 实际 PnL 正确率 |
| 响应延迟 | 20% | 该 SKILL 在 Screen 执行链中的平均耗时（估算）|
| 资源效率 | 20% | 来自 dream-cost-control 的 ROI 评级（A=100/B=75/C=50/D=25）|
| 改进闭环 | 15% | 该 SKILL 产出的问题被 D3 提案修复的比率 |
| 合规达标 | 15% | 该 SKILL 产物通过 ai-trading-compliance 检查的比率 |

---

## 五、输出规范

写入 `sessions/{latest_session}/review/skill-performance-report.json`:

```json
{
  "analysis_ts": "2026-05-27T06:05:00+08:00",
  "window": "last_7_days",
  "skills_evaluated": [
    {
      "skill_id": "B6",
      "skill_name": "dream-pretrade-gatekeeper",
      "scores": {
        "accuracy": 78,
        "latency": 90,
        "efficiency": 75,
        "improvement": 60,
        "compliance": 100
      },
      "weighted_score": 79.5,
      "grade": "B",
      "key_finding": "Gate C 在 red_team_flag=true 时 SKIP 率偏高（72%），建议检查阈值 70 是否过严",
      "pip_triggered": false
    },
    {
      "skill_id": "MS",
      "skill_name": "master-seminar",
      "scores": {
        "accuracy": 55,
        "latency": 80,
        "efficiency": 50,
        "improvement": 40,
        "compliance": 85
      },
      "weighted_score": 60.5,
      "grade": "C",
      "key_finding": "大师方向与实际 PnL 一致率仅 55%，低于基准 65%",
      "pip_triggered": false
    }
  ],
  "d_grade_skills": [],
  "summary": "本周 8 个关键 SKILL 中 2 个 A / 4 个 B / 2 个 C，无 D 级，整体稳健"
}
```

---

## 六、PIP 与替换触发规则（6-TRADING 版）

| 条件 | 动作 |
|------|------|
| 连续 2 周 grade=C 或 1 周 grade=D | 在 `weekly-proposals.json` 新增 `skill_improvement_plan` 提案 |
| 连续 3 周 grade=D | 在 `weekly-proposals.json` 新增 `skill_replacement` 提案（R3 级，须人工审批）|
| Gate C (B6) grade=D | 优先级 P0，直接输出紧急提案 |

---

## 七、与其他 Process D 步骤的接口

| 产物字段 | 用途 |
|---------|------|
| `skill-performance-report.grade` | A8 `key_findings` 的量化依据 |
| `d_grade_skills[]` | D2 lesson 提炼时的特别关注标记 |
| `pip_triggered=true` | D3 自动生成 `skill_improvement_plan` 提案 |
| 与 dream-cost-control 交叉 | `efficiency` 维度分直接取 cost-report 的 ROI grade |

---

*最后更新: 2026-05-27 v1.0 | 集成 dream-performance-review v4.0 → Process D PR*
