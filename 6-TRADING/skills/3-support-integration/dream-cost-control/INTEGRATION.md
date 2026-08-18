# dream-cost-control 集成规范 (Team A Phase-0 守卫 + Process D CC)

> **原始 SKILL**: dream-multiskill-v2/skills/3-SUPPORT/dream-cost-control/SKILL.md v1.0.0
> **集成位置**: ① Team A Screen 1/2 Phase-0 前置预算检查 ② Process D Step 1.5b 成本归因
> **触发时机**: ① 每次 Screen 1/2 执行前 ② Process D Step 1.5（与 DA 并行）

---

## 一、职责

1. **Tavily 预算守卫**：在 Team A Phase-0 执行前检查每日 API 预算余量，防止超限
2. **执行成本记录**：Team B 每次入场后记录实际手续费 + 滑点到 episode.json
3. **Process D 成本归因**：按 SKILL 分解 PnL 来源，输出 ROI 评级（A/B/C/D）
4. **ROI 告警**：连续 D 级 SKILL → 触发 dream-performance-review 评估

---

## 二、触发位置

| 触发场景 | 时机 | 触发方式 |
|---------|------|---------|
| Team A Phase-0 预算检查 | Screen 1/2 最开始 | 强制前置 |
| Team B 执行后成本记录 | B8 (A5) 执行完成后 | 注入 episode.json |
| Process D Step 1.5b | DA 并行 | Process D 流程内 |

---

## 三、Team A Phase-0 预算守卫

### 3.1 预算配置（6-TRADING 版）

```python
budget_6trading = {
    "daily": {
        "tavily": {"limit": 50, "unit": "次/天"},
        "allocation": {
            "screen1_p01_p06": 6,   # P0.1-P0.6 HARD BLOCK
            "screen1_p04b": 1,      # P0.4b archive-center（非阻塞）
            "screen2_phase0": 4,    # Screen 2 日线查询
            "team_b_checks": 2,     # Team B 状态检查
            "buffer": 37            # 剩余缓冲
        }
    }
}
```

### 3.2 预算检查规则

```
Screen 1/2 执行前：
1. 检查今日 Tavily 已用量（从 dream-cost-control 日报读取）
2. 预算使用率 >= 85%:
   → P0.4b archive-center 降级为跳过（archive_data: "budget_limited"）
   → 告警 TAVILY_BUDGET_WARNING 写入 data_context
3. 预算使用率 >= 95%:
   → Screen 1/2 中止，输出 SCREEN_BLOCKED_BUDGET，等待次日重置
   → 写入记忆 screen1_blocked_reason: "tavily_budget_exhausted"
4. 预算正常 (<85%): 正常执行，不影响流程
```

---

## 四、Team B 执行成本记录

B8 (A5) 执行完成后，将以下字段写入 `episode.json` 的 `execution` 段：

```json
{
  "execution": {
    "entry_price": 68500.0,
    "fee_usdt": 1.23,
    "fee_rate_bps": 4,
    "slippage_usdt": 0.45,
    "slippage_bps": 1.5,
    "delay_cost_usdt": 0.12,
    "total_cost_usdt": 1.80,
    "cost_rate_pct": 0.026
  }
}
```

**成本公式**: `total_cost = fee + slippage + delay_cost`

---

## 五、Process D Step 1.5b — 成本归因（与 DA 并行）

### 5.1 输入

```
sessions/*/team-b/episode.json (last_20_episodes)
  → 提取 execution.total_cost_usdt, outcome.pnl_usdt
```

### 5.2 输出

写入 `sessions/{latest_session}/review/cost-report.json`:

```json
{
  "analysis_ts": "2026-05-27T06:10:00+08:00",
  "window": "last_20_episodes",
  "trading_cost": {
    "avg_fee_bps": 4.2,
    "avg_slippage_bps": 1.8,
    "total_cost_usdt_per_trade": 2.1,
    "cost_rate_pct": 0.03
  },
  "api_cost": {
    "tavily_calls_today": 13,
    "tavily_daily_limit": 50,
    "usage_rate": 0.26,
    "budget_status": "OK | WARNING | CRITICAL"
  },
  "skill_roi": {
    "B3_signal_scoring": {"roi_pct": 45, "grade": "B"},
    "B6_gate_c": {"roi_pct": 82, "grade": "A"},
    "IA_bias_injection": {"roi_pct": 31, "grade": "B"},
    "MS_master_seminar": {"roi_pct": 18, "grade": "C"}
  },
  "d_grade_skills": [],
  "cost_alert": {
    "level": "P3 | P2 | P1 | P0",
    "message": "",
    "action": ""
  }
}
```

### 5.3 ROI 评级与 Process D 接口

| ROI 范围 | 评级 | Process D 动作 |
|---------|------|--------------|
| > 50% | A | 正常 |
| 20-50% | B | 正常 |
| 0-20% | C | 在 weekly-lessons 中标注优化建议 |
| < 0% | D | 触发 dream-performance-review 评估该 SKILL |

---

## 六、告警规则（6-TRADING 版）

| 告警级别 | 触发条件 | 行动 |
|---------|---------|------|
| P0 | Tavily 日用量 ≥ 95% | 中止 Screen，输出 SCREEN_BLOCKED_BUDGET |
| P1 | Tavily 日用量 ≥ 85% | 降级 P0.4b，告警写入 data_context |
| P2 | Tavily 日用量 ≥ 70% | 监控，不影响执行 |
| P1 | 单笔 cost_rate > 0.1% | 在 episode.json 标注 HIGH_COST_WARNING |
| P1 | D 级 SKILL 连续 ≥ 3 次 | 触发 dream-performance-review |

---

## 七、与 D2/D3 的接口

| 字段 | 用途 |
|------|------|
| `cost_report.skill_roi` | D3 proposal 的 `martingale_param_update` 依据 |
| `d_grade_skills[]` | dream-performance-review 的 PIP 触发输入 |
| `cost_alert.level` | Process D Step 6 记忆更新中的 `budget_health` 字段 |

---

*最后更新: 2026-05-27 v1.0 | 集成 dream-cost-control v1.0 → Team A P0 + Process D CC*
