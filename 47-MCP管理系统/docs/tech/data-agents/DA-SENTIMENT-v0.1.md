# DA-SENTIMENT — 情绪数据子 agent 协议

> **版本**: v0.1 ｜ **创建日期**: 2026-11-05 ｜ **状态**: 🟡 草案
> **上游**: [SPEC-L0-DATA-AGENT-v0.1](../SPEC-L0-DATA-AGENT-v0.1.md)
> **查询命令**: `data.dal_query {command: "sentiment"}`（P1 已落地）

## 1. 数据源清单

| 数据源 | 采集器 | 频率 | 落库 sub_category |
|---|---|---|---|
| 加密恐惧贪婪指数 | fear_greed_collector | 30min | crypto_fear_greed |
| 恐惧贪婪增强版（四分项） | fear_greed_enhanced_collector | 30min | fear_greed_enhanced |
| 社交讨论量 | social_volume 采集链路 | 30min | social_volume |

## 2. 指标口径（DAL 输出键 → 库内来源）

| 输出键 | sub_category | metric_name | 说明 |
|---|---|---|---|
| crypto_fear_greed | crypto_fear_greed | value | 真实恐惧贪婪指数（0-100） |
| fg_momentum | fear_greed_enhanced | momentum | 动量分项 |
| fg_volatility | fear_greed_enhanced | volatility | 波动率分项 |
| fg_capital_flow | fear_greed_enhanced | capital_flow | 资金流分项 |
| fg_funding | fear_greed_enhanced | funding | 费率分项 |

## 3. 质量分级

- **good**: crypto_fear_greed 有真实值（当前达标，P1 验证指数 71）；
- **derived**: 真实源缺失，回退 VIX 公式派生（仅作降级路径）；
- **empty**: 全部缺失（FAIL-OPEN）。

## 4. 派生逻辑归属

- sentiment_classification（贪婪/中性/恐惧）：阈值 >65 / 35-65 / <35，由消费层推导，口径变更须在本文件登记；
- VIX 派生回退公式：index = 100 − (VIX − 15) × 5，仅当真实源缺失时使用。

## 5. 训练挂钩

- 采集成功率：fear_greed 采集器调度成功比（Beta verify）；
- 数据新鲜度：30min 阈值分级；
- 覆盖率：§2 登记指标非空占比。

## 6. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-11-05 | 初版：基于 P1 落地后的真实指标口径登记，真实源优先、VIX 派生仅作回退 |
