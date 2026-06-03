# 审批超时 AI 自动决策规则

脚本: `6-TRADING/scripts/approval_agent.py`
超时阈值: **30 分钟**
检查频率: 每 10 分钟（Hermes cron `a3c5f632fbf4`）

---

## Gate-C 入场审批

### 自动批准（所有条件同时满足）

| 条件 | 阈值 |
|------|------|
| composite_confidence | ≥ 70% |
| A7 评分 | ≥ 32/40 |
| Screen1 得分 | ≥ 55/100 |
| 价格漂移 | < 5% |
| red_team_flag | = false |

### 强制拒绝（任意一条触发）

| 条件 | 阈值 |
|------|------|
| composite_confidence | < 60% |
| Screen1 得分 | < 40/100 |
| 连续 SKIP 次数 | ≥ 3 次 |
| red_team_flag | = true |

### 灰色地带（60%-70%）

保守拒绝 + 推送"建议人工再次确认"到 Trading-RiskControl

---

## A9 离场审批

| 决策 | 条件 |
|------|------|
| 批准离场 | exit_score ≥ 65 或 decision = EXIT |
| 保持持仓 | exit_score < 40 |
| 遵从 A9 建议 | 40-65 区间，参考 decision 字段 |

---

## 人工覆盖

AI 代决后，你可以在**飞书审批中心**查看历史记录并提出异议。
AI 代决的通知消息会标注 `[AI代决]`，包含决策依据和超时时长。
