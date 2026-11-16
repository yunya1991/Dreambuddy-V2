# L1 意图校准报告

- 选中：threshold **0.72** / delta **0.08**（约束 FPR≤2%）
- OOD：top1 25.0% / top3 36.7% / FPR 1.8%（n=60/168）
- in_dist：top1 83.2% / top3 93.4%
- holdout：top1 26.7% / top3 43.3%

## 分意图阈值（dev=in_dist，全局 FPR 预算贪心）
- OOD：top1 30.0% / top3 36.7% / FPR 2.4%
- in_dist：top1 83.0% / holdout top1 23.3%
- 门禁（G1/G2/G3）：**未通过**

## uplift ≥0.02 的意图

- 达标（6）：asset_class_trend, calendar_event, contradiction_insight, persistence_strength, risk_control, technical_analysis
- 待剪枝候选（13）：data_insight, data_query, event_analysis, event_listing, fundamental_valuation, leader_compare, metric_series, path_insight, price_query, stat_query, technical_indicator, top_correlation, whale_flow
