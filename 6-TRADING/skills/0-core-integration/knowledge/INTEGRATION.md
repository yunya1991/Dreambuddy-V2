# dream-knowledge 集成规范 (Knowledge Base — K1)

> **原始 SKILL**: dream-multiskill-v2/skills/0-CORE/dream-knowledge/SKILL.md v1.1
> **集成职能**: Knowledge Base — 策略知识库
> **存储路径**: 6-TRADING/knowledge/

---

## 一、职责

在每次 Process D A8 复盘后，将本周 Screen 1 策略方向 + A9 离场结果沉淀为知识条目，使下次 Screen 1 Phase-0 可以检索历史经验，避免重复犯同类错误。

---

## 二、知识库目录结构

```
6-TRADING/knowledge/
├── README.md                   # 本目录说明
├── regime_patterns/            # 市场状态模式库
│   ├── bear_with_squeeze.json  # 熊市+资金费率负值（轧空风险）
│   ├── etf_outflow_bear.json   # ETF流出主导熊市
│   └── ...
├── strategy_scores/            # 每个已执行策略的评分记录
│   ├── 20260526-SHORT-futures_martingale.json
│   └── ...
└── master_profiles/            # 大师策略提炼（引用 dream-multiskill-v2）
    └── README.md               # 指向 1-TRADE/dream-regime-detector 的 master_profiles
```

---

## 三、策略评分体系（6-TRADING 版，100分制）

| 维度 | 分值 | 6-TRADING 数据来源 |
|------|------|-------------------|
| 逻辑完整性 | 10 | Screen 1 score (A1+A2+A3 综合) |
| 参数清晰度 | 10 | Screen 2 martingale_grid 完整性 |
| 可执行性 | 10 | A7 gate score / 40 * 10 |
| 历史胜率 | 20 | A9 离场后更新：win/total episodes |
| 风险回报比 | 10 | Screen 2: TP1距离 / SL距离 |
| 实战次数 | 10 | episode count for this strategy_type |
| 市场环境覆盖 | 10 | regime_patterns 匹配数量 |
| 工具兼容性 | 5 | OKX CLI 可执行性（当前 N/A，扣除） |
| 优化空间 | 10 | A8 score_improvement 字段 |
| 扩展性 | 5 | 跨币种适用性 |

**评级**: S (>=80) | A (60-79) | B (40-59) | C (<40)

---

## 四、知识写入触发（Process D Step 2）

写入条件：
1. A9 离场完成 → 写入 `strategy_scores/{session_id}.json`（更新胜率）
2. A8 完成后 → 写入 `regime_patterns/{pattern_name}.json`（新识别的市场模式）

写入格式（strategy_scores 示例）:
```json
{
  "strategy_id": "20260526-SHORT-futures_martingale",
  "symbol": "BTC-USDT-SWAP",
  "screen1_direction": "SHORT",
  "screen1_score": 72,
  "screen2_composite_confidence": 64,
  "entry_date": "2026-05-26",
  "exit_date": null,
  "pnl_usdt": null,
  "pnl_pct": null,
  "status": "holding | closed_tp | closed_sl | closed_forced",
  "knowledge_score": null,
  "knowledge_grade": null,
  "lessons_refs": []
}
```

---

## 五、Screen 1 Phase-0 检索（P0.9 步骤）

在 Screen 1 Phase-0 的 P0.9 步骤（TRIGGER_PROMPTS.md 命名规范，非阻塞）：
```
P0.9: 查询 knowledge/strategy_scores/ 中最近 5 个 BTC 同向（SHORT/LONG）策略的
      平均胜率、平均 RR、最常见失败原因
      → 如胜率 < 30% 且 >=3 条记录，降低本次 screen1_score * 0.85（审慎折扣）
      → 将检索结果注入 data_context 传给 A1/A2/A3
```

---

*最后更新: 2026-05-27 v1.1 — GAP-TX3 fix: Section 五 步骤编号 P0.7 → P0.9 对齐触发提示词*
