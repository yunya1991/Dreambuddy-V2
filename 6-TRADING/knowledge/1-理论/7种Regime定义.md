# 7种 Regime 定义与检测
> **来源**: dream-multiskill-v2/1-TRADE/dream-regime-detector/SKILL.md
> **类别**: 理论 — 市场状态分类框架

---

## Regime 分类体系

### 1. TREND_BULL（强势牛市）
**检测**: MA200上方+MA50>MA200+ADX>25+RSI 55-75+MACD>0扩张
**策略**: 趋势追踪/突破追入/回调加仓
**大师**: Druckenmiller+++, O'Neil++, Livermore+

### 2. TREND_BEAR（强势熊市）
**检测**: MA200下方+MA50<MA200+ADX>25+RSI 25-45+MACD<0
**策略**: 做空/观望/反弹做空
**大师**: PTJ+++, Soros++, Dalio+

### 3. RANGE_BOUND（震荡盘整）
**检测**: ADX<20+布林带中轨+MA纠缠+RSI 40-60
**策略**: 网格/高抛低吸/期权双卖
**大师**: Michele+++, Livermore++, Tharp+

### 4. HIGH_VOLATILITY（高波动）
**检测**: ATR>2×MA_ATR+布林带扩张+单日波动>3%
**策略**: 小仓位/严格止损/保守阻力配置(liquidity权重↑)
**大师**: PTJ+++, Soros++, Dalio++

### 5. BREAKOUT_PENDING（突破在即）
**检测**: 布林带收窄(宽度<20%历史)+关键位整理+成交量萎缩后放大
**策略**: 等待突破/突破追入/假突破反手
**大师**: Livermore+++, Talmans++

### 6. EXHAUSTION（趋势衰竭）
**检测**: 价格新高/新低+RSI/MACD背离+成交量背离+斜率减缓
**策略**: 减仓/反向布局/期权保护
**大师**: Soros+++, PTJ++

### 7. CRISIS（危机模式）
**检测**: 单日暴跌>10%+FGI<10+大规模清算+交易所故障
**策略**: 暂停交易/等待企稳/抓危机Alpha
**大师**: Dalio+++, PTJ+++, Soros++

## 定时检测
每日3次: 04:00/12:00/20:00 CST
触发蒸馏阈值: Regime突变+置信>0.7
