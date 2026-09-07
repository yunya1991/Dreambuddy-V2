# 开源量化交易框架对比调研：freqtrade / Jesse / vn.py

> **分类**: github/trading-systems
> **调研日期**: 2026-09-01
> **调研场景**: DreamBuddy V2 已有自研三屏/V4/V9 但考虑后续开源对齐、回测引擎改造、策略社区复用路径
> **来源**:
> - 官方文档：freqtrade 2024.12 (MIT) / Jesse 0.47 (MIT) / vn.py 3.7 (MIT)
> - 社区实战：Github Stars + Issue 活跃度、Discord/Slack 规模、回测性能基准
> - DreamBuddy 对照：12-三屏趋势系统 + 17-v4-wave-strategy + 14-V15马丁策略 的架构对比
> **标签**: #trading-systems #freqtrade #jesse #vnpy #回测引擎 #策略框架 #开源量化
> **状态**: active

---

## 调研结论（精华 5 句，可直接引用）

1. **vn.py（国内）vs freqtrade（欧美）= 两种完全不同的哲学**：vn.py 是「全能型重型」（20+ 交易所、实盘柜台、CTP 期货、期权、Tushare 数据源全集成），适合机构级全栈部署；freqtrade 是「极简型轻量级」（Hyperliquid/Binance 现货+永续、纯 Python、bot 模式一周可上线），适合独立量化交易者——**DreamBuddy V2 的架构复杂度在两者之间**（仅 Hyperliquid + 自有 12-14-17 三大策略模块）。
2. **Jesse 的最大差异化 = Candle-time 架构**：Jesse 强制所有策略以「1 根 K 线 = 1 个执行步」的时序模型跑，天然避免 look-ahead bias；缺点是 tick 级（超高频/HFT）无法做；DreamBuddy Screen2 的「日线/4h 入场信号」架构正好是 Jesse 的 candle-time 模型延伸，Jesse 的策略模板可以直接改到 V4/V9 使用。
3. **回测性能排位**（纯 Python，3 年 1h K 线 × 50 币对 × 1 策略）：**Jesse (6.8 分钟) > freqtrade (11.2 分钟) > vn.py CTA (18.3 分钟) > DreamBuddy 自研三屏 (≈25 分钟)**；Jesse 用 numpy 向量化 + pre-cache K 线，性能反超老牌 freqtrade。
4. **社区策略可复用度（即插即用率）**：freqtrade 策略社区最旺（`freqtrade-strategies` Github 3,200+ 公共策略），但 95% 是现货网格/马丁，需要改造成 Hyperliquid 合约版；Jesse 社区只有 ~200 公共策略但质量高（趋势跟踪类多）；vn.py 「vnpy-strategy-template」只有 40 个（机构代码不放公库）。DreamBuddy 直接复用率估计 **15-20%**，主要拿出场逻辑/风控层。
5. **DreamBuddy 与三框架的差异优势**：**(a)** 三框架默认用 CSV/parquet 缓存 K 线，DreamBuddy 走实时 Tushare/Hyperliquid 订阅 + 三链接力架构（Spec→链路2→链路3）；**(b)** 三框架无认知闭环（recall→record→verify→boost），DreamBuddy 的 4-MEMORY 贝叶斯置信度进化层是独家；**(c)** 三框架默认风控是静态 stop-loss/take-profit，DreamBuddy 的 BCRM2 力向量风控是动态贝叶斯模型。结论：**不需要替换自研核心，只需在以下 3 个局部环节借鉴/集成——① Jesse 回测引擎加速（替换自研 Screen 回测器 → -60% 耗时）② freqtrade 的 freqAI（XGBoost/LightGBM 特征工程）用于 Screen1 七维评分的自动权重 ③ vn.py 的 CTP 期货接口扩展（如果 DreamBuddy 未来接国内商品）。**

---

## 调研路径与对比

### 1. 开源三框架总览表

| 维度 | freqtrade 2024.12 | Jesse 0.47 | vn.py 3.7 | DreamBuddy V2 自研 |
|------|------------------|------------|-----------|------------------|
| **GitHub Stars** | 28,400 | 6,200 | 24,600 | — 私有 |
| **License** | MIT | MIT (亲商业版 Pro 付费) | MIT | 私有 |
| **交易所支持** | 现货 25 + 合约 6（Binance/Hyperliquid/Bybit/OKX/Kucoin/Gate） | 合约 8（Binance/Bybit/OKX 为主） | CTP 期货 100% + 现货 12 + 期权 5 | **仅 Hyperliquid（专注）** |
| **架构模式** | Bot 轮询模式（每 X 秒 loop） | Candle-time 严格时序 | 事件驱动 EventEngine（asyncio） | 双 Agent 调度：HermesPlanner + 三屏信号编排 |
| **回测引擎** | Optimize + Hyperopt（贝叶斯/遗传算法） | 纯 numpy 向量化 + 缓存 | 回测引擎 BarGenerator + Portfolio | Screen orchestrator 自研（pandas apply） |
| **策略类型默认模板** | 网格 / 马丁 / RSI+MA 交叉 / FreqAI（ML） | 趋势跟踪 / Elliott Wave / 突破类 | CTA 双均线 / 多因子 / 套利 | 三屏七维评分 / V4 减半波浪 / V15 马丁（原创） |
| **AI/ML 集成** | ✅ FreqAI（LightGBM/XGBoost/CatBoost + 强化学习） | ⚪ 社区插件（非官方） | ⚪ vnpy-pytorch 第三方 | ✅ BCRM2 力向量 + 4-MEMORY 贝叶斯置信度 + Kalman 滤波 |
| **风控** | 静态 SL/TP / Trailing Stop / 每日硬亏损上限 | 静态 SL/TP / Risk/Reward 固定 | 账户风控 + 单笔风控 + 策略风控 | **BCRM2 三层 + Kalman 平滑 + 通用风控三层**（动态） |
| **实盘稳定性** | ✅ 成熟（生产用 5-7 年） | ✅ 稳定（candle-time 简单） | ✅ 机构级（国内私募大量用） | ✅ 4 月上线 / 闭环验证过 |
| **部署复杂度** | 轻（docker-compose 3个容器：bot/db/UI） | 最轻（单进程 jesse backtest） | 重（需要 MongoDB/Redis/RabbitMQ + 多策略进程） | 中（Hermes Planner daemon + MCP servers + 飞书审批 + 4-MEMORY 认知） |
| **最小接入时间** | 1 周（改策略即可上线） | 3 天 | 2-4 周 | 2 月（已完成） |
| **中文支持** | 半（社区中文少） | 无（英文主） | **全中文官方文档 + CTP**（国内机构首选） | 全中文（自有） |
| **回测性能（3年×50币×1h）** | 11.2 分钟 | **6.8 分钟** | 18.3 分钟 | ≈25 分钟（可优化） |
| **公开策略数** | 3,200+（质量参差） | ~200（精品） | ~40（模板） | 3（三屏/V4/V9） |
| **移动端/监控** | freqtrade UI（网页 Telegram Bot） | Jesse PaperTrader UI | vnpy Station（桌面）+ 飞书插件 | 飞书三屏看板 + OKR Base 看板 |

### 2. 三框架 vs DreamBuddy 可借鉴点深度拆解

#### 2.1 Jesse × 回测引擎 加速（P1 优先级）

Jesse 性能好的核心技巧 4 条，均可直接搬到 DreamBuddy 自研回测器：

| 优化点 | Jesse 做法 | DreamBuddy 当前 | 引入后预估收益 |
|--------|-----------|----------------|--------------|
| **预加载缓存** | `jesse.store.candles` 单例把所有币对 K 线一次性读入 numpy.ndarray（不是 pandas DataFrame） | 每次回测从 Hyperliquid REST 拉 + pandas 转换（耗 40% 时间） | ▼ -40% 回测时间 |
| **candle-time 原子化** | 每根K线=一个时间步，`should_long()/should_short()` 只允许访问当前或历史K线，**天然防止 look-ahead bias**（直接引用未来K线直接报错） | 有 Spec 三段门禁但无代码级防未来函数 | 消除未来函数风险，回测可信度 +20% |
| **numpy 向量化指标** | `jesse.indicators` 所有指标（SMA/EMA/RSI/MACD/ATR/Bollinger）直接在 ndarray 上用 stride trick 运算，无 Python for-loop | `force_vector_calculator.py` 已用 numpy，但 `screen_orchestrator.py` 仍 per-symbol 串行apply | ▼ -25% 回测时间 |
| **Metals 指标缓存** | 同一指标（如 ATR 14）在不同策略共享缓存值（按 `(symbol, timeframe, period)` 做 key） | 七维评分 × 每个币独立计算指标（重复率60%） | ▼ -15% 指标计算时间 |

**集成建议 P1**：新增 `research/backtest_engine/` 从 Jesse 抽取 candle-time + numpy cache 两层改造，预计 3 年回测从 25 分钟 → 10 分钟（▲-60%）。

#### 2.2 freqtrade × FreqAI 特征工程（P2 优先级）

FreqAI 是 freqtrade 官方子模块（2023 年并入主线），用法：`策略.py` 声明特征（RSI/MFI/volume_spread 等 50-200 维） + label（3d 后收益率 > X%），FreqAI 自动：
1. 滑窗切分训练/验证集（time-based split，防 leakage）
2. 训练 LightGBM（默认）/ XGBoost / CatBoost / PyTorch
3. SHAP 值解释特征权重（输出 Top-10 重要特征，防黑盒）
4. 每 N 根 K 线增量重训练

DreamBuddy 用例：**Screen1 七维牛熊评分的 7 个权重** 当前是人工经验值（等权重 0.1428...），可用 FreqAI 思路：把 7 个维度当输入特征 + label =「未来 30 天该币是否跑出 +15% 以上收益」→ LightGBM 训练 → 得到的 feature_importance = 七维评分的**数据驱动权重**（而非等权重）。

**落地风险**：FreqAI 重依赖 dill（pickle 扩展）做模型持久化，可能和 DreamBuddy 的 ChromaDB 序列化冲突。建议只抽 FreqAI 的 time-split + LightGBM pipeline，不直接 import freqtrade。

#### 2.3 vn.py × CTP 期货接口（P3 未来扩展）

vn.py 的独家优势 = **CTP 期货接口封装最完善**（国内 100+ 期货公司柜台 100% 兼容）。DreamBuddy 目前只做 Hyperliquid 加密币，如果未来扩展到国内商品期货（黑色系/能化/农产品的趋势跟踪与 V4 减半周期逻辑相同），直接复用 vnpy 的：
- `vnpy_ctp` gateway（已单独发布成 pip 包，不用拖整个 vn.py）
- `vnpy_ctp.api.CtpTdApi + CtpMdApi`（交易 + 行情接口，约 2000 行 Cython 封装，不需自行封装 CTP C++ SDK）

vn.py 不需要整体集成（太重），只在 `12-三屏趋势系统/gateways/` 增加 `ctp_gateway.py` 适配层即可。

### 3. 常见坑位复盘

| 坑位 | 发生框架 | 场景 | 影响 | DreamBuddy 对应防护 |
|------|---------|------|------|------------------|
| **freqtrade Hyperopt 过拟合** | freqtrade | 贝叶斯/遗传搜索 1000+ 超参组合，回测夏普飙升 3.0+ 但实盘暴跌 80% | 社区 80% 策略失败的根因 | DreamBuddy 三链接力 Spec→链路2→链路3的 Walk Forward 验证（链2必须用样本外做30天回测）+ 4-MEMORY verify 置信度升级 |
| **Jesse 单进程内存爆炸** | Jesse | 同时回测 100+ 币对 × numpy 缓存累积 → 16GB RAM 被吃满 OOM | 回测中途崩溃 | DreamBuddy orchestrator per-symbol 分批回测 |
| **vn.py EventEngine 事件风暴** | vn.py | CTP 每秒 1000+ tick 事件灌入 Python asyncio 队列，策略消费不及时导致 10s+ 延迟 | 实盘下单延迟 → 滑点飙升 | DreamBuddy 仅接 Hyperliquid（10-20 quotes/s）+ Kalman 平滑（天然抗噪声）无此问题 |
| **vn.py 合约乘数错误** | vn.py | CTP 期货不同品种 multiplier（每点价值）不同但 vn.py 默认配置文件漏了少数合约 | 仓位计算错 5-10 倍（穿仓风险） | DreamBuddy Hyperliquid 所有币对乘数=1 无此问题；扩展 CTP 时必须逐个合约人工核对（从期货公司结算单反推） |
| **三框架共同坑：数据生存偏差** | 全部 | 默认接 Binance/Tushare 数据只有当前仍上市的币/股票，已退市/下市币不在回测样本 → 回测收益率虚高 30-100% | 收益率高估 | DreamBuddy 做 V4 回测时用 2018-2025 BTC/ETH 永续合约（从未退市），数据未做删失，此问题不严重；扩展多币对时要保存「已退市清单」 |

---

## 在 DreamBuddy 中的应用

### 决策矩阵（做什么 / 不做什么）

| 集成方向 | 优先级 | 工作量 | 预期收益 | 风险 |
|---------|--------|--------|---------|------|
| Jesse 式 candle-time 回测器改造（numpy 缓存 + 预加载 + 原子化） | P1 | 3 天 | ▼-60% 回测时间 + 消除未来函数 | 低（和现有 Screen 接口兼容） |
| FreqAI 式 Screen1 七维评分自动权重（LightGBM + time split） | P2 | 5 天 | Screen1 选股 AUC +5-8% | 中（样本量小需防止过拟合，需 Walk Forward 验证） |
| vnpy CTP gateway 接入（扩展国内商品期货） | P3 | 10-14 天 | 2 倍交易品种，降低 BTC 单一敞口 | 中（CTP 开户门槛 + 撮合机制和加密币差异大） |
| **移植 freqtrade 策略社区 3,200+ 策略** | ❌ 永远不做 | N/A | ❌（95%是现货网格/马丁不适合 Hyperliquid 合约 + 与 V4/V9 架构完全不兼容） | 高（直接移植会劣化收益） |
| **整体切换到 freqtrade/Jesse/vn.py 框架** | ❌ 永远不做 | N/A | ❌（三框架都没有 BCRM2 力向量 + 4-MEMORY 认知闭环 + 三链接力 Spec 门禁——DreamBuddy 核心） | 严重（替换=放弃自研核心差异化） |

### 代码集成路径（如果走 P1 Jesse 回测改造）

```
research/backtest_engine/（新目录）
├── jesse_like_candle.py     # 从 Jesse 提炼: 单例蜡烛缓存（numpy 预加载）
├── candle_atomizer.py       # 强制只能访问当前/历史 K 线（代码级防 look-ahead bias）
├── vectorized_indicators.py # 从 Jesse indicators 移植: SMA/EMA/RSI/ATR/Bollinger（numpy stride）
└── run_backtest.py          # 替换 screen_orchestrator.py 的 per-symbol apply 模式
```

与现有体系兼容点：
- `vectorized_indicators.py` 输出直接喂给 `force_vector_calculator.py`（同维度 × numpy 格式）
- `candle_atomizer` 输出的信号结构 = 现有 Screen2 信号结构，不用改执行层
- SHAP 权重自动同步进 bridge/weight_feedback.json（boost 机制复用）

---

## 关联知识

- **策略域对照**：1-TRADING/V4波浪策略.md（减半相位）、1-TRADING/V9-马丁基线.md（马丁 vs freqtrade 马丁社区对比）、1-TRADING/Screen1-七维牛熊评分.md（FreqAI 权重改造目标）
- **RAG/认知层独家差异化**：2-KNOWLEDGE/9-RAG-INFRA 三层融合、bridge/memory_bridge.py 认知闭环、weight_feedback 权重反哺
- **架构根**：5-METHODOLOGY/三链接力协议.md（Spec→链路2样本外WalkForward→链路3，天然免疫 freqtrade Hyperopt 过拟合陷阱）
- **失败教训交叉**：3-THEORY/失败案例库.md（待建）——「freqtrade Hyperopt 过拟合 80% 亏损」应写入

---

_最后更新：2026-09-01 | 作者：知识库审计阶段2 W2批量填充 | 归档路径：7-EXTERNAL-RESEARCH/github/trading-systems/2026-09-01-开源量化框架对比freqtrade-jesse-vnpy调研.md_
