# 跨市场周期与多策略配置

## 当前周期定位 (June 2026)

- GDP +2.2%, CPI 3.3-3.8%, PCE 2.7-3.5%, 失业率 4.5%
- RSM定义："Stagflation Lite"（轻度滞胀，GDP仍正增长）
- BTC角色：高贝塔空头标的（与NASDAQ相关性-0.9）

## 四象限策略矩阵

### Recovery（春）
- 核心：BTC 40% + ETH 20% + SOL 10% + NVDA 15%
- 对冲：USDT 5%
- 马丁：LONG全部，满仓1.0

### Overheat（夏）
- 核心：XLE 30% + Gold 20% + BTC 20% + USDT 30%
- 对冲：SHORT SPY 10%
- 马丁：LONG XLE/Gold，BTC轻仓

### Stagflation（秋）← 当前
- 核心：XLP 25% + XLE 20% + Gold 15% + USDT 25%
- 对冲：SHORT BTC 10% + SHORT ETH 5%
- 马丁：LONG XLP/XLE/Gold + SHORT BTC/ETH，仓位0.4

### Reflation（冬）
- 核心：SPY 30% + BTC 20% + USDT 35%
- 马丁：BTC左侧宽间隔，仓位0.5

## 资产相关性矩阵

最佳对冲对：
- Stagflation: Long XLP + Short ETH (相关-0.10)
- Overheat: Long XLE + Short SPY (相关0.40)
- Recovery: Long SOL + Long BTC (相关0.65，同向)
- Reflation: Long SPY + Long Gold (相关0.05)

## 象限切换规则

- Stagflation→Recovery: CPI<2.5%×2月 AND 10Y<4% OR Fed降息
- Stagflation→Overheat: GDP>3% AND CPI>3%
- Stagflation→Reflation: GDP<0 AND CPI<2%
- Recovery→Stagflation: GDP<1% AND CPI>3% → 紧急防御
