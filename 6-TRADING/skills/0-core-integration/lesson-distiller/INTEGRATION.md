# learning-lesson-distiller 集成规范 (Process D — D2)

> **原始 SKILL**: dream-multiskill-v2/skills/0-CORE/learning-lesson-distiller/SKILL.md
> **集成团队**: Process D — 交易复盘（三级学习闭环第 2 步）
> **触发时机**: A8 完成后，Process D Step 3

---

## 一、职责

将 `sessions/*/team-b/episode.json` 中的 L1 事实（单次决策记录），提炼为 L2 规律（可复用的经验法则），防止「一次亏损产生一条死规则」的噪声过拟合。

---

## 二、6-TRADING 参数配置

```json
{
  "episodes_path": "6-TRADING/sessions/*/team-b/episode.json",
  "window": {
    "last_n_episodes": 20,
    "time_range": "last_4_weeks"
  },
  "thresholds": {
    "min_frequency": 3,
    "min_severity": 2,
    "min_unique_traces": 2,
    "cooldown_episodes": 10
  }
}
```

---

## 三、Lesson 命名规范（6-TRADING 版）

**失败规律** `F_` 前缀:

| Lesson ID | 含义 | 触发条件 |
|-----------|------|---------|
| F_SHORT_SQUEEZE_UNDERWEIGHTED | 资金费率极值风险评估不足，导致被轧空 | 资金费率 < -5% 时 SHORT 亏损 >= 3次 |
| F_PHASE0_DATA_STALE | Phase-0 未执行直接分析，数据陈旧 | Screen1 价格偏差 > 20% 出现 >= 2次 |
| F_ENTRY_CHASED | 追入当前价格（距支撑 < $2000），RR 不达标 | SKIP → 次日强行入场亏损 >= 2次 |
| F_SLEEPWALK_WAIT | 连续 SKIP 超过 7 次，丧失入场机会 | consecutive_skip >= 7 出现 >= 1次 |

**成功规律** `S_` 前缀:

| Lesson ID | 含义 | 触发条件 |
|-----------|------|---------|
| S_PHASE0_TAVILY_IMPROVES_ACCURACY | Tavily Phase-0 数据显著提高方向准确性 | tavily_realtime data_source + 正确方向 >= 3次 |
| S_BOUNCE_ENTRY_BETTER_RR | 等待反弹入场 RR 优于追入 | 反弹入场 pnl > 0 且 RR > 2 出现 >= 3次 |

---

## 四、输出格式

写入 `sessions/{latest_session}/review/weekly-lessons.json`:

```json
{
  "distillation_date": "2026-05-26",
  "window": "last_20_episodes",
  "lessons_delta": {
    "added": [
      {
        "lesson_id": "F_SHORT_SQUEEZE_UNDERWEIGHTED",
        "frequency": 3,
        "severity": 3,
        "evidence_refs": ["20260526-BTC-SCREEN2-v2-..."],
        "recommendation": "当资金费率 < -5% 时，composite_confidence 自动 * 0.8，L0 仓位上限降至 20%"
      }
    ],
    "updated": [],
    "deprecated": []
  }
}
```

---

## 五、防噪声规则

- 单次事件（frequency=1）不产生 Lesson，标记为「观察中」
- 对立样本（同条件下成功 2 次/失败 2 次）不产生 Lesson
- cooldown 内（同一 Lesson 10 个 episode 内）不重复提炼

---

*最后更新: 2026-05-26*
