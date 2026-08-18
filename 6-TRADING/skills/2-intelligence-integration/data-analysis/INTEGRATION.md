# dream-data-analysis 集成规范 (Process D — DA / Screen 2 支撑)

> **原始 SKILL**: dream-multiskill-v2/skills/2-INTELLIGENCE/dream-data-analysis/SKILL.md v1.0.0
> **集成团队**: Process D (Step 1.5) + Team A Screen 2 (Phase-2 趋势上下文)
> **触发时机**: Process D — A8 (D1) 完成后；Screen 2 — Phase-2 开始前

---

## 一、职责

将 `sessions/*/team-b/episode.json` 系列做时间序列分析（MA/EMA、趋势速度/加速度、阻力分解、置信度趋势），为 D2 规律提炼提供**量化证据**，并为 Screen 2 Phase-2 的 `dream-backtest` 提供趋势上下文。

---

## 二、触发时机

| 触发场景 | 时机 | 输入 | 输出目标 |
|---------|------|------|---------|
| Process D Step 1.5 | A8 完成后、D2 开始前 | last_20_episodes | `review/data-analysis-report.json` |
| Screen 2 Phase-2 前置 | A1→A2→A3 完成后 | last_20_episodes | 注入 dream-backtest 的 `trend_context` |

---

## 三、输入规范（6-TRADING 版）

```json
{
  "episodes_path": "sessions/*/team-b/episode.json",
  "window": { "last_n_episodes": 20, "time_range": "last_4_weeks" },
  "smoothing_policy": {
    "ma_windows": [5, 10, 20],
    "ema_windows": [8, 21]
  },
  "episode_fields_used": [
    "ts",
    "scoring.composite_confidence",
    "scoring.a7_gate_score",
    "gate.result",
    "outcome.pnl_usdt",
    "skip_tracking.consecutive_skip_count"
  ]
}
```

---

## 四、输出规范

写入 `sessions/{latest_session}/review/data-analysis-report.json`:

```json
{
  "analysis_ts": "2026-05-26T06:10:00+08:00",
  "window": "last_20_episodes",
  "trend": {
    "direction": "up | down | flat | unknown",
    "velocity": null,
    "acceleration": null,
    "trend_confidence": 0.0
  },
  "resistance": {
    "resistance_score": 0,
    "components": {
      "cost_friction": 0, "crowding_friction": 0,
      "vol_friction": 0, "liquidity_friction": 0
    }
  },
  "confidence_trend": {
    "composite_confidence_ma5": null,
    "composite_confidence_ema8": null,
    "direction": "improving | declining | stable"
  },
  "skip_pattern": {
    "skip_rate_last_20": null,
    "avg_consecutive_skips": null,
    "sleepwalk_risk": "low | medium | high"
  },
  "calibration_suggestions": {
    "gate_threshold": { "status": "keep | tighten | loosen", "evidence": "" },
    "position_sizing": { "status": "keep | reduce | increase", "evidence": "" },
    "martingale_intervals": { "status": "keep | widen | narrow", "evidence": "" }
  }
}
```

---

## 五、与 D2 (learning-lesson-distiller) 的接口

D2 在提炼规律时读取 `data-analysis-report.json` 以下字段作为**量化支撑**：

| D2 用途 | 来源字段 |
|---------|---------|
| 验证 F_ 规律触发频率 | `skip_pattern.skip_rate_last_20` |
| 评估 Gate C 阈值是否过严 | `calibration_suggestions.gate_threshold` |
| 梦游预警证据 | `skip_pattern.sleepwalk_risk` |
| D3 gate_threshold_update 提案依据 | `calibration_suggestions.*` |

---

## 六、与 Screen 2 Phase-2 (dream-backtest) 的接口

`dream-backtest` (A8s) 执行前，从 `data-analysis-report` 获取 `trend_context`：

| backtest 参数 | 来自 data-analysis |
|--------------|-------------------|
| 趋势方向一致性校验 | `trend.direction` vs `screen1_direction` |
| 止损距离调整范围 | `resistance.resistance_score`（高阻力 → 宽止损） |
| Phase-2 是否值得执行 | `trend.trend_confidence` < 0.4 → Phase-2 降级，标注 `phase2_skipped: true` |

---

*最后更新: 2026-05-26*
