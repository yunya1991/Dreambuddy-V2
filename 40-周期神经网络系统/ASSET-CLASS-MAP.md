# 40 周期神经网络 — 资产类型与龙头梳理（v0.1）

> 核验日期：2026-11-09
> 核验方式：OKX 公共 API `GET /api/v5/public/instruments?instType=SWAP`（返回 543 个永续、528 个基础标的）
> 定位：**初期只交易加密，但架构必须容纳全球主流金融资产**。OKX USDT 永续已覆盖加密、贵金属、工业金属、能源、美股指数、美股行业 ETF、美股个股、亚太股指。

---

## 一、结论速览（10 大类 + 龙头）

| # | 资产大类 | 龙头（Leader） | OKX 永续合约 | 状态 | 现有代码落点 |
|---|---|---|---|---|---|
| 1 | 加密（Crypto） | **BTC** | `BTC-USDT-SWAP` | 已接入 | p3_sector_transmission L1_anchor |
| 2 | 贵金属（Precious Metals） | **XAU 黄金** | `XAU-USDT-SWAP` | 部分（仅 spot XAUT） | p3_fund_flow 用 `XAUT/USDT` spot |
| 3 | 工业金属（Base Metals） | **XCU 铜** | `XCU-USDT-SWAP` | 未接入 | — |
| 4 | 能源（Energy） | **CL WTI 原油** | `CL-USDT-SWAP` | 未接入 | — |
| 5 | 美股宽基指数（US Equity Index） | **US500** | `US500-USDT-SWAP` | 仅宏观序列 | p1_ma200 用 yfinance `^GSPC` |
| 6 | 美股行业/风格 ETF | **SPY** | `SPY-USDT-SWAP` | 未接入 | — |
| 7 | 亚太股指（APAC Index） | **JP225 日经** | `JP225-USDT-SWAP` | 未接入 | — |
| 8 | 美股个股（Single Stocks） | **NVDA（AI 算力）** | `NVDA-USDT-SWAP` | 未接入 | — |
| 9 | 外汇（FX） | **DXY 美元指数**（不可直交易） | 无 | 仅宏观序列 | p3_fund_flow `DTWEXBGS` |
| 10 | 利率/信用（Rates & Credit） | **TLT（20Y 美债 ETF）** | `TLT-USDT-SWAP` | 部分 | p3_fund_flow `DGS10` / `T10Y2Y` |

> 说明：9/10 两类在 OKX 无直接永续，用「宏观序列（FRED）+ 可交易代理（TLT）」双轨表达；其余 8 类均有可交易永续。

---

## 二、龙头判定原则（四选一，按优先序）

1. **定价权**：该资产的全球边际定价中心（BTC 之于加密、XAU 之于贵金属、CL 之于能源、US500 之于全球风险资产）。
2. **流动性**：OKX 合约盘口深度与持仓量（OI）为大类内最高。
3. **广度代表性**：自身走势能代表整个类别的风险偏好（SPY 代表美股宽基、SMH 代表半导体、XLE 代表能源股）。
4. **传导源头**：在因果链上处于上游（宏观 → 大类龙头 → 类内层级 → 个股/山寨），下游对其有滞后响应。

**反例约束**：不选「波动最大」或「涨幅最高」的标的做龙头（如 meme、杠杆 ETF SOXL/TQQQ 属于放大器，不是源头）。

---

## 三、各大类成员与层级（OKX 已核验 state=live）

### 3.1 加密（现状已实现，4 层）

| 层 | 成员 | 说明 |
|---|---|---|
| L1_anchor | BTC | 全局锚，宏观力直接承接点 |
| L2_major | ETH, SOL | 主流公链 |
| L3_growth | AVAX, LINK, ADA | 赛道/成长 |
| L4_meme | DOGE, PEPE, WIF | 情绪放大器（风险偏好末端） |

代码：[p3_sector_transmission.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/40-周期神经网络系统/scripts/p3_sector_transmission.py#L24-L29)、[p3_resonance_matrix.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/40-周期神经网络系统/scripts/p3_resonance_matrix.py#L39-L45)

### 3.2 贵金属

| 角色 | 标的 | 合约 | ctVal |
|---|---|---|---|
| 龙头 | XAU 黄金 | `XAU-USDT-SWAP` | 0.001 XAU |
| 成员 | XAG 白银 | `XAG-USDT-SWAP` | 0.01 XAG |
| 成员 | XPT 铂金 | `XPT-USDT-SWAP` | 0.001 XPT |
| 成员 | XPD 钯金 | `XPD-USDT-SWAP` | 0.001 XPD |

### 3.3 工业金属

| 角色 | 标的 | 合约 | ctVal |
|---|---|---|---|
| 龙头 | XCU 铜 | `XCU-USDT-SWAP` | 1 XCU |

### 3.4 能源

| 角色 | 标的 | 合约 | ctVal |
|---|---|---|---|
| 龙头 | CL WTI 原油 | `CL-USDT-SWAP` | 0.1 CL |
| 成员 | BZ 布伦特 | `BZ-USDT-SWAP` | 0.01 BZ |
| 成员 | NG 天然气 | `NG-USDT-SWAP` | 1 NG |
| 代理 | USO 原油 ETF | `USO-USDT-SWAP` | 1 USO |

### 3.5 美股宽基指数

| 角色 | 标的 | 合约 | ctVal |
|---|---|---|---|
| 龙头 | US500（S&P 500） | `US500-USDT-SWAP` | 1 US500 |
| 成员 | US100（Nasdaq 100） | `US100-USDT-SWAP` | 1 US100 |
| 成员 | SPX | `SPX-USDT-SWAP` | 1 SPX |

### 3.6 美股行业/风格 ETF

| 角色 | 标的 | 合约 | 代表 |
|---|---|---|---|
| 龙头 | SPY 宽基 | `SPY-USDT-SWAP` | 美股整体 |
| 成员 | QQQ | `QQQ-USDT-SWAP` | 科技成长 |
| 成员 | IWM | `IWM-USDT-SWAP` | 小盘 |
| 成员 | SMH | `SMH-USDT-SWAP` | 半导体 |
| 成员 | XLE | `XLE-USDT-SWAP` | 能源股 |
| 成员 | XLV | `XLV-USDT-SWAP` | 医疗 |
| 成员 | XBI | `XBI-USDT-SWAP` | 生物科技 |
| 成员 | URNM | `URNM-USDT-SWAP` | 铀矿 |
| 债券代理 | TLT | `TLT-USDT-SWAP` | 20Y 美债价格 |

### 3.7 亚太股指

| 角色 | 标的 | 合约 | ctVal |
|---|---|---|---|
| 龙头 | JP225 日经 225 | `JP225-USDT-SWAP` | 1 JP225 |
| 成员 | KR200 韩国 KOSPI200 | `KR200-USDT-SWAP` | 1 KR200 |

### 3.8 美股个股（龙头为 NVDA，其余为类内代表）

| 分组 | 成员 |
|---|---|
| AI 算力（龙头组） | NVDA, AMD, AVGO, TSM, ASML, MU, ARM |
| 科技平台 | AAPL, MSFT, GOOGL, AMZN, META, NFLX |
| 金融 | GS, JPM, V, BRKB, IBKR |
| 加密相关 | COIN, MSTR, HOOD, CRCL |
| 能源/工业 | XOM, CVX, OXY, GE, CAT（无）、DELL |

> 注：个股在 OKX 为上架型永续，部分标的交易时段/流动性弱于加密；应作为「类内末端」，不参与大类龙头判定。

### 3.9 外汇（不可直交易）

- 龙头代理：**DXY 美元指数**（FRED `DTWEXBGS` 广义美元指数，或 `DX-Y.NYB`）
- 交叉验证：`XAU/USD`（金价与美元反向）在 p3_fund_flow 已产出 `gold_vs_usd` 滚动相关

### 3.10 利率/信用（不可直交易）

- 价格代理：`TLT-USDT-SWAP`（20Y 美债 ETF，价格与收益率反向）
- 宏观序列：`DGS10`（10Y 收益率）、`T10Y2Y`（期限利差）、`HY OAS`（信用利差）
- 现状：p3_fund_flow 已用 `DGS10`、`DTWEXBGS`、`SP500`

---

## 四、目标传导拓扑（三层，多资产类别）

```
G0 全球宏观层（不可交易，仅门控）
  增长-通胀时钟（INDPRO/CPI）· 美元 DXY · 利率 DGS10/T10Y2Y · 信用 HY OAS
        │
        ▼
G1 大类龙头层（可交易，类间传导矩阵 R(s)）
  BTC │ XAU │ CL │ US500 │ JP225 │ TLT
        │
        ▼
G2 类内层级（类内轮动/广度）
  加密 L1→L4 │ 贵金属 XAU→XAG/XPT/XPD │ 能源 CL→BZ/NG │
  美股 US500→SPY/QQQ/IWM/SMH/XLE→个股 │ 亚太 JP225→KR200
```

- **类间传导**：G1 层两两计算 R(s)、Granger、t_arrive。注意 OKX 股票/商品永续存在交易时段缺口，日线对齐需按「共同交易日」取样。
- **类内传导**：加密沿用现有 L1-L4；美股为「指数 → ETF → 个股」三级；商品为「龙头 → 成员」两级。
- **宏观力 F_macro**：由 G0 → G1 计算（现有 `50/core/macro_force.py` 的框架可直接复用，但权重表需按大类扩展）。

---

## 五、现状盘点（代码事实，含行号）

| 脚本 | 资产集合 | 数据源 | 与目标差异 |
|---|---|---|---|
| [p3_sector_transmission.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/40-周期神经网络系统/scripts/p3_sector_transmission.py#L24-L29) | 加密 4 层共 9 标的 | OKX | 仅加密，无跨类 |
| [p3_resonance_matrix.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/40-周期神经网络系统/scripts/p3_resonance_matrix.py#L39-L45) | 同上 9 标的，锚=BTC | OKX | 仅 BTC vs 加密，缺跨类 R |
| [p1_ma200_anchor.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/40-周期神经网络系统/scripts/p1_ma200_anchor.py#L20-L30) | BTC/ETH/SOL/UNI/AAVE/NEAR/ARB/LINK + SPX | **Binance + yfinance** | 与 40 其余脚本的 OKX 源不一致 |
| [p3_fund_flow.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/40-周期神经网络系统/scripts/p3_fund_flow.py#L233-L250) | SP500/DGS10/DTWEXBGS + BTC/XAUT | FRED + OKX spot | 黄金用 spot `XAUT/USDT`，非永续 `XAU-USDT-SWAP` |
| [p2_asset_rotation.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/40-周期神经网络系统/scripts/p2_asset_rotation.py#L77-L82) | 黄金 GC=F / 美元 DX-Y.NYB / 10Y ^TNX / 标普 ^GSPC | yfinance | 全是 yfinance，未用 OKX 可交易合约 |
| [cycle_state.json](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/40-周期神经网络系统/cycle_state.json) | technical_anchor 仅加密 + SPX | — | 大类龙头（XAU/CL/US500）无 MA200 锚 |
| [asset_rotation.json](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/40-周期神经网络系统/asset_rotation.json) | 6 项（crypto_btc/eth, gold, dollar, treasury_yield, equity） | — | 有 gold/equity 但数据常为 null（yfinance 失败） |

### 已识别的 5 个结构性缺口

1. **双源并存**：p1 用 Binance、p2 用 yfinance、p3 用 OKX。同一资产三套价格 → MA200/动量/相关性口径不可比。建议统一以 OKX 永续为主源，yfinance/FRED 仅作宏观序列。
2. **黄金标的错位**：`XAUT/USDT`（实物金 spot，已核验存在）vs `XAU-USDT-SWAP`（黄金永续）。前者适合基本面参考，后者才是可交易龙头合约。
3. **单锚假设**：现有 `ANCHOR = "BTC/USDT"` 把全球宏观力全部灌入 BTC。多类架构下应改为「G0 → G1 多锚」，BTC 只是 G1 成员之一。
4. **权重表只覆盖加密**：`50/core/macro_force.py` 的 `LAYER_COMPONENT_WEIGHTS` 只有 L1-L4 加密层，不能把 `L4_meme` 的 D4=2.0 套到个股/ETF。
5. **无跨类 R 矩阵**：resonance_matrix 只有 BTC vs 加密 8 标的，缺少 BTC↔XAU、BTC↔US500、XAU↔DXY 等跨类传导。

---

## 六、OKX 合约可用性核验（抽样，2026-11-09）

- SWAP 总数 543，基础标的 528，`state=live`。
- 已核验合约：`XAU/XAG/XPT/XPD/XCU/CL/BZ/NG/USO/US500/US100/SPX/JP225/KR200/SPY/QQQ/TLT/IWM/XLE/XLV/SMH/XBI/URNM/NVDA/AAPL/TSLA/MSFT/META/GOOGL/AMZN/COIN/MSTR` 均为 `-USDT-SWAP`。
- 无 FX 直盘（EUR/USD 等）→ 外汇只能走宏观序列 + 金/美元反向验证。
- 股票类永续存在交易时段限制，日线需按共同交易日对齐（不同于 7×24 加密）。

---

## 七、演进路径（建议，未实施）

| 阶段 | 范围 | 依赖 | 验收 |
|---|---|---|---|
| P0（现状） | 加密 4 层 + 宏观序列 | 已跑通 | washout 全链刷新（云端） |
| P1（已实施 2026-11-09） | 接入贵金属 + 能源龙头（XAU/CL），跨类 R(BTC↔XAU, BTC↔CL)，G1 六锚全量 | OKX 日线 | R 显著性 + t_arrive 稳定；`cross_asset_matrix.json` 产出 |
| P2 | 跨类 R 显著性调优 + 股票类永续流动性/交易时段质量校验（US500/JP225/TLT 已随 P1 接入） | 交易时段对齐 | 大类间 Granger 显著且 t_arrive 稳定 |
| P3 | 类内 ETF/个股轮动（SPY→SMH/XLE→NVDA 等） | 流动性筛选 | 类内层级动量梯度有效 |

**统一原则**：G0 宏观 → G1 大类龙头（6 个可交易锚）→ G2 类内层级；龙头永不使用杠杆 ETF（SOXL/TQQQ）或 meme 代币。

---

## 八、待决问题（已确认，默认方案）

> 用户 2026-11-09 确认，已固化为 [asset_classes.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/40-周期神经网络系统/asset_classes.py) 常量，代码不再硬编码。

1. 黄金主源：**双轨已确认** —— `XAU-USDT-SWAP` 做交易/传导；`XAUT/USDT` spot 仅作宏观背离参考（`GOLD_DUAL_TRACK`）。
2. 股票类永续日线对齐：**已确认按 OKX 24h 连续报价对齐**（`EQUITY_ALIGNMENT="continuous_24h"`），产出物逐标的标注 `session`。
3. G1 大类锚：**已确认包含 TLT**（`TLT_IN_G1=True`），利率类参与跨类 R 矩阵；`DGS10/T10Y2Y/HY OAS` 留在 G0 宏观层。G1 共 6 锚：BTC、XAU、CL、US500、JP225、TLT。
