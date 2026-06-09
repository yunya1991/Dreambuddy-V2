# dream-archive-center 集成规范 (Team A — Screen 1 Phase-0 P0.4b)

> **原始 SKILL**: dream-multiskill-v2/skills/2-INTELLIGENCE/dream-archive-center/SKILL.md v1.0.0
> **集成团队**: Team A (Screen 1 Phase-0)
> **触发时机**: Phase-0 P0.4（宏观驱动）完成后，作为 P0.4b 步骤执行

---

## 一、职责

通过 Tavily 联网搜索 BTC 历史类比情景，在 Screen1 Phase-0 中补充「历史上相似宏观背景下 BTC 走势」数据，为 A1/A2/A3 三个子 Agent 提供历史锚点。

**重要**: P0.4b 是**非 HARD BLOCK 步骤**，搜索失败不阻断 Screen1 执行。

---

## 二、P0.4b 执行规范

```
P0.4b: dream-archive-center 历史情景检索
Step1: 从 P0.4 结果中提取宏观关键词
        (如: "Fed rate hold", "crypto ETF approval", "regulatory pressure", "high leverage")
Step2: 构建搜索查询:
        "Bitcoin {keyword_1} {keyword_2} historical price action 2020 2021 2022 2023 2024"
Step3: Tavily 搜索，取 2-3 条最相关结果
Step4: 提取以下信息：
        - 历史时间窗口（年/季度）
        - BTC 当时走势（涨/跌/横）
        - 关键驱动因子
        - 最终结果（时间窗口末期价格变化%）
Step5: 评估类比有效性：
        - similarity_score 0-3（宏观条件重叠度）
        - key_difference（当前 vs 历史的关键差异）
⚠️ 超时(>15s) 或无有效结果 → 跳过，继续执行，标注 archive_data: "unavailable"
```

---

## 三、输出格式

添加到 `data_context` 的 `historical_analogues` 字段：

```json
{
  "historical_analogues": [
    {
      "period": "2022-Q4",
      "similarity_score": 2,
      "macro_overlap": ["Fed hawkish pause", "crypto regulatory pressure"],
      "btc_outcome_pct": -30,
      "btc_outcome_period": "8 weeks",
      "key_difference": "当前有现货ETF，2022年没有",
      "relevance": "空头情景参考"
    },
    {
      "period": "2021-Q2",
      "similarity_score": 1,
      "macro_overlap": ["regulatory pressure"],
      "btc_outcome_pct": -55,
      "btc_outcome_period": "12 weeks",
      "key_difference": "2021年为纯加密监管，当前为宏观流动性+加密双重压力",
      "relevance": "极端空头情景参考"
    }
  ],
  "analogue_summary": "2/2 个类比案例均支持近期下行压力，历史平均跌幅 -42%",
  "archive_data": "available | unavailable"
}
```

---

## 四、与 A1/A2/A3 的接口

`historical_analogues` 注入规则（在 Phase-0 P0.8 合并 data_context 时包含）：

| Agent | 使用方式 |
|-------|---------|
| A1 (矛盾分析) | 使用类比案例验证「主矛盾」在历史上的表现，避免把当前情况误判为独特 |
| A2 (第一性原理) | 对比历史资金流推导，验证第一性原理推导的历史一致性 |
| A3 (沙盘推演) | 直接作为 S2/S3 情景的历史依据，S2 = 本次类比均值情景 |

---

## 五、失败处理

| 情况 | 处理 |
|------|------|
| Tavily 无相关历史结果 | `historical_analogues = []`, `archive_data: "unavailable"` |
| 搜索质量差（无具体数据）| 标注 `analogue_quality: "low"`，A1/A2/A3 降低引用权重 |
| P0.4b 超时（>15s）| 跳过，不阻塞主流程 |

---

*最后更新: 2026-05-26*
