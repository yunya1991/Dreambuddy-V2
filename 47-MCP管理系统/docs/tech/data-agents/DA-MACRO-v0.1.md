# DA-MACRO — 宏观数据子 agent 协议

> **版本**: v0.1 ｜ **创建日期**: 2026-11-05 ｜ **状态**: 🟡 草案
> **上游**: [SPEC-L0-DATA-AGENT-v0.1](../SPEC-L0-DATA-AGENT-v0.1.md)
> **查询命令**: `data.dal_query {command: "macro"}`

## 1. 数据源清单

| 数据源 | 采集器 | 频率 | 落库 sub_category |
|---|---|---|---|
| FRED 宏观系列（FEDFUNDS/M2NS/WALCL/CPIAUCSL/PPIACO/INDPRO） | fred_collector | 1h | 同名 |
| FRED 传统金融（VIXCLS/DGS10/DTWEXBGS/SP500/NASDAQCOM/DCOILWTICO/IR14260） | fred_collector | 1h | 同名 |
| yfinance 跨市场标的（^VIX/DX-Y.NYB/GC=F/^GSPC/^IXIC/^TNX/CL=F/BTC-USD） | yfinance_collector | 15min | 同名 |

## 2. 指标口径（DAL 输出键 → 库内来源）

| 输出键 | sub_category | metric_name | 说明 |
|---|---|---|---|
| DXY | DX-Y.NYB | value | 美元指数 |
| US10Y | ^TNX | value | 美债10年收益率 |
| VIX | ^VIX | value | VIX 波动率 |
| Gold | GC=F | value | 黄金 |
| SP500 | SP500 | value | 标普500 |
| Fed_liquidity | WALCL | value | Fed 资产负债表 |
| Fed_rate | FEDFUNDS | value | 联邦基金利率 |
| CPI | CPIAUCSL | value | CPI 指数 |
| PPI | PPIACO | value | PPI |
| WTI | DCOILWTICO | value | WTI 原油 |
| Oil_futures | CL=F | value | 原油期货 |
| NASDAQ | NASDAQCOM | value | 纳指 |

## 3. 质量分级

- **good**: CPI 与 Fed_rate 均有真实值（当前达标）；
- **partial**: 仅行情类指标可用；
- **empty**: 全部缺失（FAIL-OPEN）。

## 4. 派生逻辑归属

- cpi_yoy（同比）：需历史序列计算，规划下沉 DAL 侧实现（当前前端为 null 占位）；
- policy_score / rate_cycle：由消费层基于 DXY/US10Y 推导，口径变更须在本文件登记。

## 5. 训练挂钩

- 采集成功率：fred/yfinance collector 调度成功比（Beta verify）；
- 数据新鲜度：FRED 1h / yfinance 15min 阈值分级；
- 覆盖率：§2 登记指标非空占比。

## 6. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-11-05 | 初版：基于 P0/P1 落地后的真实指标口径登记 |
