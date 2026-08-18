# A6 实战监控指标体系 v1.0

> **目标**: 为 A6 情报监控提供完整的实战监控指标  
> **涵盖维度**: OKX API + 链上数据 + 宏观金融 + 地缘政治 + 技术发展 + 加密政策  
> **分类**: 战略层(周-月) / 战术层(日-周) / 技术层(小时-日)  

---

## 一、OKX 官方监控体系

### 1.1 REST API 监控端点

| 类别 | 端点 | 监控内容 | 频率 | 层级 |
|:---|:---|:---|:---:|:---|
| **系统状态** | `GET /api/v5/system/status` | OKX系统状态 | 每小时 | 战略 |
| **持仓信息** | `GET /api/v5/account/positions` | 当前持仓、未实现盈亏 | 每5分钟 | 技术 |
| **账户余额** | `GET /api/v5/account/balance` | 可用余额、总权益 | 每5分钟 | 技术 |
| **订单状态** | `GET /api/v5/trade/order` | 订单状态变更 | 实时 | 技术 |
| **算法订单** | `GET /api/v5/trade/orders-algo-pending` |  algo订单状态 | 每5分钟 | 技术 |
| **爆仓订单** | `GET /api/v5/public/liquidation-orders` | 全市场爆仓情况 | 每5分钟 | 战术 |
| **ADL警告** | WebSocket: `adl-warning` | 自动减仓警告 | 实时 | 技术 |
| **资金费率** | `GET /api/v5/public/funding-rate` | 当前资金费率 | 每8小时 | 战术 |
| **预测资金费率** | `GET /api/v5/public/funding-rate-summary` | 下次预测费率 | 每8小时 | 战术 |
| **未平仓合约** | `GET /api/v5/public/open-interest` | 全市场持仓量 | 每小时 | 战术 |
| **多空比** | `GET /api/v5/rubik/stat/contracts/long-short-account-ratio` | 账户多空比 | 每小时 | 战术 |
| **主动买卖量** | `GET /api/v5/rubik/stat/trading-data` | 主动买入/卖出量 | 每小时 | 战术 |

### 1.2 WebSocket 实时监控通道

| 通道名称 | 说明 | 监控内容 | 层级 |
|:---|:---|:---|:---|
| **status** | 系统状态 | OKX服务状态变更 | 战略 |
| **account** | 账户信息 | 余额、保证金、盈亏实时推送 | 技术 |
| **positions** | 持仓信息 | 持仓实时推送 | 技术 |
| **orders** | 订单信息 | 订单状态实时推送 | 技术 |
| **fills** | 成交明细 | 成交记录实时推送 | 技术 |
| **balance_and_position** | 余额+持仓 | 综合推送 | 技术 |
| **position-risk-warning** | 仓位风险预警 | ⚠️ 仓位风险实时预警 | 技术 |
| **account-greeks** | 账户希腊值 | 期权风险实时推送 | 技术 |
| **liquidation-orders** | 爆仓订单 | 全市场爆仓实时推送 | 战术 |
| **adl-warning** | ADL警告 | 自动减仓警告 | 技术 |
| **channel-conn-count** | 连接数 | WebSocket连接数监控 | 战略 |

### 1.3 OKX CLI 快速监控命令

```bash
# 账户余额
okx account balance --profile dreamdemo

# 持仓信息
okx swap positions BTC-USDT-SWAP --profile dreamdemo

# 算法订单
okx swap algo orders --instId BTC-USDT-SWAP --profile dreamdemo

# 当前价格
okx market ticker BTC-USDT-SWAP --profile dreamdemo

# 资金费率
okx market funding-rate --instId BTC-USDT-SWAP --profile dreamdemo

# 未平仓合约
okx market open-interest --instId BTC-USDT-SWAP --profile dreamdemo

# 多空比
okx market long-short-account-ratio --instId BTC-USDT-SWAP --profile dreamdemo
```

---

## 二、链上数据监控体系

### 2.1 Glassnode 核心指标

| 指标名称 | 说明 | 数据来源 | 监控频率 | 层级 |
|:---|:---|:---|:---:|:---|
| **Exchange Inflow** | 交易所流入量 | Glassnode API | 每小时 | 战术 |
| **Exchange Outflow** | 交易所流出量 | Glassnode API | 每小时 | 战术 |
| **Active Addresses** | 活跃地址数 | Glassnode API | 每天 | 战术 |
| **Transaction Count** | 交易笔数 | Glassnode API | 每天 | 战术 |
| **MVRV Ratio** | 市值/实现价值比 | Glassnode API | 每天 | 战略 |
| **NUPL (Net Unrealized Profit/Loss)** | 未实现盈亏净值 | Glassnode API | 每天 | 战略 |
| **Whale Transactions (>$1M)** | 巨鲸交易(>$1M) | Glassnode API | 实时 | 战术 |
| **Miner Outflow** | 矿工流出 | Glassnode API | 每天 | 战术 |
| **HODL Waves** | HODL波浪(持仓时间分布) | Glassnode API | 每周 | 战略 |
| **Realized Cap HODL Waves** | 实现市值HODL波浪 | Glassnode API | 每周 | 战略 |

#### 关键阈值

| 指标 | 阈值 | 含义 |
|:---|:---|:---|
| **Exchange Inflow** | 单日 > 50,000 BTC | 可能砸盘信号 |
| **Exchange Outflow** | 单日 > 50,000 BTC | 可能囤币信号 |
| **MVRV Ratio** | > 3.5 | 严重高估，可能回调 |
| **MVRV Ratio** | < 1.0 | 严重低估，可能反弹 |
| **NUPL** | > 0.75 | 市场极度贪婪 |
| **NUPL** | < -0.05 | 市场极度恐惧 |
| **Whale Transactions** | 单笔 > 5,000 BTC | 关注巨鲸动向 |

### 2.2 CoinGlass 核心指标

| 指标名称 | 说明 | 数据来源 | 监控频率 | 层级 |
|:---|:---|:---|:---:|:---|
| **Long/Short Ratio** | 多空比(全市场) | CoinGlass API | 每小时 | 战术 |
| **Open Interest** | 未平仓合约价值 | CoinGlass API | 每小时 | 战术 |
| **Liquidation Map** | 清算热力图 | CoinGlass API | 实时 | 技术 |
| **Order Book Depth** | 订单簿深度(L2/L3) | CoinGlass API | 实时 | 技术 |
| **Funding Rate History** | 资金费率历史 | CoinGlass API | 每8小时 | 战术 |
| **Top Traders L/S Ratio** | 顶级交易者多空比 | CoinGlass API | 每小时 | 战术 |
| **Exchange Flow** | 交易所资金流向 | CoinGlass API | 每小时 | 战术 |
| **Stablecoin Inflow** | 稳定币流入 | CoinGlass API | 每天 | 战术 |

#### 关键阈值

| 指标 | 阈值 | 含义 |
|:---|:---|:---|
| **Long/Short Ratio** | > 1.5 | 多头过热，可能回调 |
| **Long/Short Ratio** | < 0.7 | 空头过头，可能反弹 |
| **Open Interest** | 单日增加 > 10% | 资金涌入，趋势可能持续 |
| **Open Interest** | 单日减少 > 10% | 资金撤离，趋势可能反转 |
| **Funding Rate** | > 0.05% | 多头付费，可能过热 |
| **Funding Rate** | < -0.05% | 空头付费，可能超卖 |

### 2.3 CryptoQuant 核心指标

| 指标名称 | 说明 | 数据来源 | 监控频率 | 层级 |
|:---|:---|:---|:---:|:---|
| **Exchange Reservoirs** | 交易所BTC储备 | CryptoQuant API | 每天 | 战略 |
| **Miner Position Index** | 矿工持仓指数 | CryptoQuant API | 每天 | 战术 |
| **Netflow Total (Exchange)** | 交易所净流量 | CryptoQuant API | 每小时 | 战术 |
| **SOPR (Spent Output Profit Ratio)** | 支出产出利润率 | CryptoQuant API | 每天 | 战术 |
| **Mayer Multiple** | 价格/200日MA比 | CryptoQuant API | 每天 | 战略 |

---

## 三、宏观金融监控体系

### 3.1 美联储政策与美元体系

| 指标名称 | 说明 | 数据来源 | 监控频率 | 层级 |
|:---|:---|:---|:---:|:---|
| **Fed Interest Rate** | 美联储利率 | FRED API / Bloomberg | 每次会议后 | 战略 |
| **Fed Watch Tool** | 美联储观察工具(加息概率) | CME Group | 每天 | 战略 |
| **DXY (Dollar Index)** | 美元指数 | TradingView / Yahoo Finance | 每天 | 战略 |
| **US 10Y Treasury Yield** | 美国10年期国债收益率 | FRED API | 每天 | 战略 |
| **SOFR (Secured Overnight Financing Rate)** | 担保隔夜融资利率 | FRED API | 每天 | 战略 |
| **Fed Balance Sheet** | 美联储资产负债表 | FRED API | 每周 | 战略 |

#### 关键阈值

| 指标 | 阈值 | 含义 |
|:---|:---|:---|
| **Fed Interest Rate** | 加息 > 25bp | 利空BTC |
| **Fed Interest Rate** | 降息 > 25bp | 利好BTC |
| **DXY** | > 106 | 美元走强，利空BTC |
| **DXY** | < 100 | 美元走弱，利好BTC |
| **US 10Y Yield** | > 4.5% | 无风险收益率高，利空BTC |
| **US 10Y Yield** | < 3.5% | 无风险收益率低，利好BTC |

### 3.2 股票市场联动

| 指标名称 | 说明 | 数据来源 | 监控频率 | 层级 |
|:---|:---|:---|:---:|:---|
| **S&P 500** | 标普500指数 | Yahoo Finance API | 每天 | 战术 |
| **Nasdaq 100** | 纳斯达克100指数 | Yahoo Finance API | 每天 | 战术 |
| **VIX (Volatility Index)** | 恐慌指数 | Yahoo Finance API | 每天 | 战术 |
| **NVIDIA Stock** | 英伟达股价(AI龙头) | Yahoo Finance API | 每天 | 战术 |
| **MSCI World Index** | MSCI全球指数 | Bloomberg | 每天 | 战略 |

#### 关键阈值

| 指标 | 阈值 | 含义 |
|:---|:---|:---|
| **S&P 500** | 单日跌幅 > 3% | 风险资产抛售，BTC可能跟跌 |
| **VIX** | > 30 | 市场恐慌，BTC可能下跌 |
| **VIX** | < 15 | 市场平静，BTC可能上涨 |

### 3.3 黄金与大宗商品

| 指标名称 | 说明 | 数据来源 | 监控频率 | 层级 |
|:---|:---|:---|:---:|:---|
| **Gold Price (XAU/USD)** | 黄金价格 | Kitco / Yahoo Finance | 每天 | 战略 |
| **WTI Crude Oil** | 西德克萨斯原油 | Yahoo Finance | 每天 | 战略 |
| **Copper Price** | 铜价(经济晴雨表) | Yahoo Finance | 每天 | 战略 |

#### 关键阈值

| 指标 | 阈值 | 含义 |
|:---|:---|:---|
| **Gold Price** | 突破历史新高 | 避险情绪升温，BTC可能受益 |
| **WTI Crude Oil** | > $90 | 通胀预期升温，美联储可能加息 |

---

## 四、地缘政治监控体系

### 4.1 中东局势

| 指标名称 | 说明 | 数据来源 | 监控频率 | 层级 |
|:---|:---|:---|:---:|:---|
| **US-Iran Relations** | 美伊关系 | Tavily Search / Reuters | 每天 | 战略 |
| **Hormuz Strait Status** | 霍尔木兹海峡状态 | Tavily Search / Bloomberg | 实时 | 战略 |
| **Israel-Hamas Conflict** | 以色列-哈马斯冲突 | Tavily Search / Reuters | 每天 | 战略 |
| **Saudi Arabia Oil Production** | 沙特石油产量 | Tavily Search / Bloomberg | 每周 | 战略 |
| **Iran Nuclear Deal** | 伊朗核协议 | Tavily Search / Reuters | 每周 | 战略 |

#### 关键事件

| 事件 | 影响 | BTC反应 |
|:---|:---|:---|
| **霍尔木兹海峡封锁** | 油价暴涨，通胀预期升温 | 短期下跌，长期可能上涨(避险) |
| **美伊开战** | 避险情绪升温 | 短期上涨 |
| **以色列-哈马斯停火** | 避险情绪降温 | 短期下跌 |

### 4.2 俄乌战争

| 指标名称 | 说明 | 数据来源 | 监控频率 | 层级 |
|:---|:---|:---|:---:|:---|
| **Russia-Ukraine Conflict** | 俄乌冲突动态 | Tavily Search / Reuters | 每天 | 战略 |
| **EU-Russia Sanctions** | 欧盟对俄制裁 | Tavily Search / Bloomberg | 每周 | 战略 |
| **Nord Stream Pipeline** | 北溪管道状态 | Tavily Search / Bloomberg | 每周 | 战略 |

### 4.3 中美关系

| 指标名称 | 说明 | 数据来源 | 监控频率 | 层级 |
|:---|:---|:---|:---:|:---|
| **US-China Trade War** | 中美贸易战 | Tavily Search / Bloomberg | 每周 | 战略 |
| **Taiwan Strait Tension** | 台海局势 | Tavily Search / Reuters | 每周 | 战略 |
| **China Crypto Policy** | 中国加密政策 | Tavily Search /-local | 每周 | 战略 |

---

## 五、技术发展监控体系

### 5.1 Bitcoin 核心技术进展

| 指标名称 | 说明 | 数据来源 | 监控频率 | 层级 |
|:---|:---|:---|:---:|:---|
| **Bitcoin Halving** | BTC减半事件 | CoinWarz / OKX | 减半前3个月开始 | 战略 |
| **Lightning Network Capacity** | 闪电网络容量 | 1ML / Lightning Network | 每周 | 战略 |
| **Taproot Adoption** | Taproot采用率 | Glassnode | 每月 | 战略 |
| **Bitcoin Mining Hash Rate** | BTC挖矿算力 | Blockchain.com | 每天 | 战术 |
| **Mining Difficulty** | 挖矿难度 | Blockchain.com | 每2016区块 | 战术 |

#### 关键事件

| 事件 | 影响 | BTC反应 |
|:---|:---|:---|
| **BTC减半** | 区块奖励减半(通胀率下降) | 历史上涨(3-6个月后) |
| **闪电网络容量创新高** | 支付采用率提升 | 长期利好 |
| **挖矿算力创新高** | 网络安全性提升 | 长期利好 |

### 5.2 Ethereum 技术发展

| 指标名称 | 说明 | 数据来源 | 监控频率 | 层级 |
|:---|:---|:---|:---:|:---|
| **Ethereum 2.0 Staking** | ETH2.0质押量 | Beaconcha.in | 每天 | 战略 |
| **Gas Fee** | 以太坊Gas费 | Etherscan | 每天 | 战术 |
| **DeFi TVL** | DeFi总锁仓价值 | DefiLlama | 每天 | 战术 |
| **Layer 2 Adoption** | L2采用率(Arbitrum/Optimism) | L2Beat | 每周 | 战略 |

### 5.3 机构入场与技术采用

| 指标名称 | 说明 | 数据来源 | 监控频率 | 层级 |
|:---|:---|:---|:---:|:---|
| **Bitcoin ETF Inflows/Outflows** | BTC ETF资金流入/流出 | Farside Investors | 每天 | 战术 |
| **Ethereum ETF Inflows/Outflows** | ETH ETF资金流入/流出 | Farside Investors | 每天 | 战术 |
| **MicroStrategy BTC Holdings** | 微策略BTC持仓 | MicroStrategy财报 | 每季度 | 战略 |
| **Tesla BTC Holdings** | 特斯拉BTC持仓 | Tesla财报 | 每季度 | 战略 |
| **Corporate BTC Adoption** | 企业采用BTC | Bitcoin Treasuries | 每周 | 战略 |

#### 关键阈值

| 指标 | 阈值 | 含义 |
|:---|:---|:---|
| **BTC ETF Inflows** | 单日 > $500M | 强烈买入信号 |
| **BTC ETF Outflows** | 单日 > $500M | 强烈卖出信号 |

---

## 六、加密政策监控体系

### 6.1 美国政策

| 指标名称 | 说明 | 数据来源 | 监控频率 | 层级 |
|:---|:---|:---|:---:|:---|
| **SEC Crypto Policy** | SEC加密政策 | SEC官网 / Tavily Search | 每周 | 战略 |
| **SEC vs Ripple (XRP)** | SEC诉Ripple案 | Tavily Search / Reuter | 每周 | 战略 |
| **Bitcoin ETF Approval** | BTC ETF批准 | SEC官网 / Bloomberg | 批准后每天 | 战略 |
| **Ethereum ETF Approval** | ETH ETF批准 | SEC官网 / Bloomberg | 批准后每天 | 战略 |
| **US Crypto Regulation** | 美国加密监管 | Tavily Search / Bloomberg | 每周 | 战略 |
| **Fed CBDC (Digital Dollar)** | 美联储CBDC(数字美元) | Fed官网 / Tavily Search | 每月 | 战略 |

### 6.2 全球政策

| 指标名称 | 说明 | 数据来源 | 监控频率 | 层级 |
|:---|:---|:---|:---:|:---|
| **China Crypto Ban** | 中国加密禁令 | Tavily Search /-local | 每周 | 战略 |
| **EU MiCA Regulation** | 欧盟MiCA监管 | EU官网 / Tavily Search | 每月 | 战略 |
| **El Salvador Bitcoin Law** | 萨尔瓦多BTC法 | Tavily Search | 每月 | 战略 |
| **India Crypto Tax** | 印度加密税 | Tavily Search | 每月 | 战略 |
| **Japan Crypto Regulation** | 日本加密监管 | Tavily Search | 每月 | 战略 |

---

## 七、监控指标体系总结

### 7.1 按层级分类

| 层级 | 监控频率 | 指标数量 | 核心指标 |
|:---|:---:|:---:|:---|
| **战略层** | 每周-每月 | ~30 | 美联储政策、地缘战争、技术发展、加密政策 |
| **战术层** | 每天-每周 | ~40 | 链上数据、宏观金融、ETF资金流 |
| **技术层** | 实时-每天 | ~20 | OKX API、订单簿、爆仓数据 |

### 7.2 按重要性分类

| 重要性 | 指标 | 说明 |
|:---|:---|:---|
| **P0 (必须监控)** | OKX持仓/账户、BTC价格、资金费率、交易所流入/流出 | 直接影响交易决策 |
| **P1 (重要监控)** | 美联储政策、ETF资金流、巨鲸交易、多空比 | 影响中期走势 |
| **P2 (常规监控)** | 地缘政策、技术发展、加密政策 | 影响长期走势 |

### 7.3 数据来源优先级

| 数据源 | 优先级 | 说明 |
|:---|:---:|:---|
| **OKX API** | ⭐⭐⭐⭐⭐ | 实时、准确、可靠 |
| **Glassnode API** | ⭐⭐⭐⭐ | 链上数据权威 |
| **CoinGlass API** | ⭐⭐⭐⭐ | 衍生品数据全面 |
| **Tavily Search** | ⭐⭐⭐ | 新闻、政策、地缘 |
| **FRED API** | ⭐⭐⭐ | 宏观金融数据权威 |
| **Yahoo Finance API** | ⭐⭐ | 股票市场数据 |

---

## 八、A6 监控流程集成

### 8.1 实时监控流程(每5分钟)

```python
def realtime_monitoring():
    """
    A6 实时监控流程(每5分钟执行一次)
    """
    # 1. OKX 账户监控
    balance = okx_account_balance()
    positions = okx_positions()
    algo_orders = okx_algo_orders()
    
    # 2. OKX 市场数据监控
    ticker = okx_market_ticker()
    funding_rate = okx_funding_rate()
    open_interest = okx_open_interest()
    
    # 3. 链上数据监控(每小时)
    if current_minute == 0:
        exchange_inflow = glassnode_exchange_inflow()
        exchange_outflow = glassnode_exchange_outflow()
        whale_transactions = glassnode_whale_transactions()
    
    # 4. 爆仓监控
    liquidation_orders = okx_liquidation_orders()
    if liquidation_orders:
        trigger_p0_alert("大额爆仓事件")
    
    # 5. 异常检测
    if detect_anomaly(positions, balance, ticker):
        trigger_p1_alert("账户异常")
```

### 8.2 每日监控流程(每天0900)

```python
def daily_monitoring():
    """
    A6 每日监控流程(每天0900执行)
    """
    # 1. 宏观金融数据
    fed_rate = fred_fed_interest_rate()
    dxy = yahoo_finance("DX-Y.NYB")
    us10y_yield = fred_us10y_yield()
    sp500 = yahoo_finance("^GSPC")
    vix = yahoo_finance("^VIX")
    
    # 2. 链上数据
    mvrv_ratio = glassnode_mvrv_ratio()
    nupl = glassnode_nupl()
    active_addresses = glassnode_active_addresses()
    sopr = cryptoquant_sopr()
    
    # 3. ETF资金流
    btc_etf_inflows = farside_btc_etf_inflows()
    
    # 4. 地缘政治
    us_iran_relations = tavily_search("US Iran relations latest")
    israel_hamas = tavily_search("Israel Hamas conflict latest")
    
    # 5. 加密政策
    sec_crypto_policy = tavily_search("SEC crypto policy latest")
    
    # 6. 生成每日情报报告
    generate_daily_intelligence_report()
```

### 8.3 每周监控流程(每周一0900)

```python
def weekly_monitoring():
    """
    A6 每周监控流程(每周一0900执行)
    """
    # 1. 战略层指标
    btc_halving_countdown = check_btc_halving_countdown()
    lightning_network_capacity = get_lightning_network_capacity()
    eth2_staking = get_eth2_staking()
    defi_tvl = get_defi_tvl()
    
    # 2. 机构持仓
    microstrategy_btc = get_microstrategy_btc_holdings()
    corporate_btc_adoption = get_corporate_btc_adoption()
    
    # 3. 全球政策
    eu_mica = tavily_search("EU MiCA regulation latest")
    china_crypto = tavily_search("China crypto policy latest")
    us_crypto_regulation = tavily_search("US crypto regulation latest")
    
    # 4. 生成每周战略报告
    generate_weekly_strategic_report()
```

---

## 九、异常检测算法

### 9.1 价格波动异常

```python
def detect_price_anomaly(current_price, historical_prices):
    """
    检测价格波动异常
    """
    # 计算过去24小时波动率
    volatility_24h = calculate_volatility(historical_prices, period="24h")
    
    # 如果当前价格波动 > 2倍平均波动率 → 异常
    if abs(current_price - historical_prices[-1]) > 2 * volatility_24h:
        return True, "价格波动异常"
    
    return False, None
```

### 9.2 成交量异常

```python
def detect_volume_anomaly(current_volume, historical_volumes):
    """
    检测成交量异常
    """
    # 如果当前成交量 > 3倍平均成交量 → 异常
    if current_volume > 3 * mean(historical_volumes):
        return True, "成交量异常放大"
    
    return False, None
```

### 9.3 巨鲸交易异常

```python
def detect_whale_anomaly(whale_transactions):
    """
    检测巨鲸交易异常
    """
    # 如果单笔交易 > 5,000 BTC → 异常
    for tx in whale_transactions:
        if tx['amount'] > 5000:
            return True, f"巨鲸交易异常: {tx['amount']} BTC"
    
    return False, None
```

### 9.4 资金费率异常

```python
def detect_funding_rate_anomaly(current_funding_rate, historical_funding_rates):
    """
    检测资金费率异常
    """
    # 如果资金费率 > 0.1% 或 < -0.1% → 异常
    if abs(current_funding_rate) > 0.001:
        return True, f"资金费率异常: {current_funding_rate}"
    
    return False, None
```

---

## 十、版本历史

| 版本 | 日期 | 更新内容 |
|:---:|:---|:---|
| **1.0.0** | 2026-04-26 | 初始版本，建立完整监控指标体系 |

---

**最后更新**: 2026-04-26  
**维护者**: A6 (dream-intelligence-monitor)  
**审核者**: 顾问团队
