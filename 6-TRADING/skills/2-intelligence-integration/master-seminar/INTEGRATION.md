# master-seminar 集成规范 (Team A — MS)

> **原始 SKILL**: dream-multiskill-v2/skills/2-INTELLIGENCE/master-seminar/SKILL.md v1.0.0
> **集成团队**: Team A (Screen 1 A3 完成后) + Process D (大师动态进化)
> **触发时机**: Screen1 每次 A3 (dream-strategy-designer) 完成后

---

## 一、职责

召唤已蒸馏的交易大师，对 Screen1 周线方向进行**多空阵营辩论**，通过对抗性讨论暴露分析盲点，并为 `screen1_score` 提供外部校验权重（调整±5~15分）。

---

## 二、触发条件

| 条件 | 是否触发 | 辩论模式 |
|------|---------|---------|
| Screen1 完成 A3 后（正常） | 必须触发 | 标准 2 阵营 |
| `screen1_score < 60` 或 `red_team_flag = true` | 必须触发 | 强化 4 阵营 |
| 持仓期间价格偏差 >10% | 按需触发 | 紧急 2 阵营 |

---

## 三、大师阵营设计（6-TRADING BTC 版）

### 标准阵营（每次）

| 阵营 | 大师ID | 核心关注 |
|-----|-------|---------|
| 多头阵营 | `trend-master` | 价格动量 + 资金流入趋势延续 |
| 多头阵营 | `fundamental-master` | 供需关系 + 减半效应 + 机构积累 |
| 空头阵营 | `mean-reversion-master` | 历史估值上限 + 超涨回调 |
| 空头阵营 | `macro-risk-master` | 宏观压力 + 流动性收缩 + 监管 |

### 扩展阵营（`red_team_flag=true` 时额外触发）

| 阵营 | 大师ID | 核心关注 |
|-----|-------|---------|
| 极端空头 | `black-swan-master` | 尾部风险 + 系统性崩溃情景 |
| 量化中性 | `quant-master` | 纯数据驱动 + 统计显著性 |

---

## 四、辩论输入

从 Screen1 已完成产物读取：

```json
{
  "data_context": "(Phase-0 Tavily 数据)",
  "strategy_type": "(A3 输出方向 + S1/S2/S3情景)",
  "red_team_flag": false,
  "knowledge_context": "knowledge/strategy_scores/ 中最近5个同向策略的胜率/RR"
}
```

---

## 五、输出规范

写入 `sessions/{session_id}/team-a/screen1/master-debate.json`:

```json
{
  "debate_ts": "2026-05-26T20:30:00+08:00",
  "session_id": "20260526-BTC-SCREEN1-v3",
  "proposed_direction": "SHORT",
  "camps": {
    "bull": {
      "master_ids": ["trend-master", "fundamental-master"],
      "top_3_arguments": [],
      "confidence_in_bull": 35,
      "strongest_evidence": ""
    },
    "bear": {
      "master_ids": ["mean-reversion-master", "macro-risk-master"],
      "top_3_arguments": [],
      "confidence_in_bear": 65,
      "strongest_evidence": ""
    }
  },
  "key_contested_points": [],
  "master_consensus": {
    "direction": "SHORT",
    "consensus_score": 65,
    "agreement_level": "moderate"
  },
  "screen1_score_adjustment": {
    "original_score": 72,
    "adjustment": 0,
    "adjusted_score": 72,
    "reason": "大师辩论基本一致，维持原分"
  }
}
```

---

## 六、`screen1_score` 调整规则

| 大师共识与Screen1方向关系 | `agreement_level` | 调整幅度 |
|------------------------|------------------|---------|
| 完全一致 | `strong` (>75% 共识) | +5 分 |
| 基本一致 | `moderate` (55-75%) | 0 |
| 分歧 | `split` (45-55%) | −5 分 |
| 明显对立 | `opposed` (<45%) | −15 分，标注 `MASTER_DEBATE_WARNING` |

→ `adjusted_score` 写入 `project_trading_session_state.md` 的 `screen1_score` 字段（替换原始分）

---

## 七、master_profiles 目录

大师档案存储在 `6-TRADING/knowledge/master_profiles/`:
- 初始大师档案由 `dream-multiskill-v2/skills/1-TRADE/dream-regime-detector` 的 `master_profiles/` 目录提供
- 6-TRADING 版档案格式额外包含 `historical_accuracy`（BTC 预判准确率）

---

## 八、Process D 大师动态进化

在 A8 批评完成后执行大师进化更新（Process D Step 3.5）：

```
读取上周 Screen1 预判方向 vs 实际 PnL 结果：
→ 正确预判（预判方向 + PnL>0）: confidence_weight +0.1
→ 错误预判（预判方向 + PnL<0）: confidence_weight −0.05
→ 写入 knowledge/master_profiles/{master_id}.json 的 historical_accuracy 字段
→ 下次辩论时，高 historical_accuracy 的大师观点权重更高
```

---

*最后更新: 2026-05-26*
