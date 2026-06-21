# 策略开发规范（基于 SimpleStrategy）

本规范用于在“经典指标机器学习系统”中持续新增与维护 Freqtrade 策略文件，确保：
- 策略可读、可复现、可回测、可调参
- 策略目录不被其它策略库误加载
- 后续新增策略可直接复制模板并按规范改动

本文以 [SimpleStrategy.py](file:///Users/zhangjiangtao/ft_userdata/%E7%BB%8F%E5%85%B8%E6%8C%87%E6%A0%87%E6%9C%BA%E5%99%A8%E5%AD%A6%E4%B9%A0%E7%B3%BB%E7%BB%9F/user_data/strategies/SimpleStrategy.py) 为“标准模板”。

## 1. 目录与停用方案（方案 A）

### 1.1 策略目录约定

- 本系统策略目录固定为：
  - `/Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/user_data/strategies`
- 本系统新增策略文件只放在上述目录内，避免跨工程引用、避免 `sys.path` 注入。

### 1.2 停用“经典顶级策略”的 Freqtrade 策略目录

观察到以下目录内的策略文件采用了运行时 `sys.path` 注入与动态类生成，容易产生误加载与跨环境不一致问题：
- `/Users/zhangjiangtao/ft_userdata/经典顶级策略/freqtrade/user_data/strategies`

本规范采用“停用而非删除”的低风险方案：
- 不删除、不改造该目录文件
- 运行/回测时显式指定本系统策略目录，避免扫描到其它目录

本系统的回测/运行封装已支持 `--strategy-path`，并在传入 `strategy_path` 时附加到 freqtrade 参数中（见 [ml_trade_service.py:L52565-L52590](file:///Users/zhangjiangtao/ft_userdata/%E7%BB%8F%E5%85%B8%E6%8C%87%E6%A0%87%E6%9C%BA%E5%99%A8%E5%AD%A6%E4%B9%A0%E7%B3%BB%E7%BB%9F/ml_trade_service.py#L52565-L52590)）。

执行约束（必须满足其一）：
- 通过系统封装执行回测/运行时，传入 `strategy_path=/Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/user_data/strategies`
- 或直接运行 freqtrade 时增加 `--strategy-path /Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/user_data/strategies`

## 2. 默认周期（统一为 1h）

为了便于跨策略统一回测、统一数据准备、统一调参，本规范要求：
- 所有新建策略默认 `timeframe = "1h"`
- 配置文件中的全局 `timeframe` 也保持为 `1h`（例如 [config_local_backtest_hyperliquid.json](file:///Users/zhangjiangtao/ft_userdata/%E7%BB%8F%E5%85%B8%E6%8C%87%E6%A0%87%E6%9C%BA%E5%99%A8%E5%AD%A6%E4%B9%A0%E7%B3%BB%E7%BB%9F/user_data/config_local_backtest_hyperliquid.json#L69-L73)）

后续如需切换周期（例如从 1h 改为 5m/15m/4h）：
- 优先只改配置文件的全局 `timeframe`
- 策略内部若显式设置了 `timeframe`，则需要同步调整策略文件；因此建议策略默认保持 `1h`，不要为了单个策略写成其它周期

## 3. 策略文件规范（以 SimpleStrategy 为模板）

### 3.1 文件与类命名

- 文件名：`<StrategyName>.py`（建议 PascalCase），例如 `SimpleStrategy.py`
- 类名：与文件名一致，例如 `class SimpleStrategy(IStrategy):`
- 新策略建议使用语义化文件名与类名：
  - `RsiMeanReversionStrategy.py` / `class RsiMeanReversionStrategy`
  - `MacdTrendFollowingStrategy.py` / `class MacdTrendFollowingStrategy`

### 3.2 必备类属性（最小可运行集合）

每个策略必须显式提供以下属性（保持与 SimpleStrategy 一致的组织方式）：
- `INTERFACE_VERSION = 3`
- `timeframe = "1h"`
- `can_short: bool = True/False`（按策略能力决定）
- `minimal_roi`（允许先用保守占位值，后续调参优化）
- `stoploss`（允许先用保守占位值）
- `process_only_new_candles`
- `use_exit_signal`
- `exit_profit_only`
- `ignore_roi_if_entry_signal`
- `startup_candle_count`
- `order_types`
- `order_time_in_force`

### 3.3 三段式结构（指标 → 入场 → 离场）

必须实现并遵循以下三段式：
- `populate_indicators(self, dataframe, metadata) -> DataFrame`
- `populate_entry_trend(self, dataframe, metadata) -> DataFrame`
- `populate_exit_trend(self, dataframe, metadata) -> DataFrame`

入场/离场字段规范：
- `populate_entry_trend` 内必须初始化并写入：
  - `dataframe["enter_long"] = 0`
  - `dataframe["enter_short"] = 0`
  - `dataframe["enter_tag"] = ""`
- `populate_exit_trend` 内必须初始化并写入：
  - `dataframe["exit_long"] = 0`
  - `dataframe["exit_short"] = 0`

冲突处理（必须）：
- 若同一根 K 同时触发 `enter_long` 与 `enter_short`，必须清零避免同 bar 双向开仓（SimpleStrategy 已实现，见 [SimpleStrategy.py:L135-L137](file:///Users/zhangjiangtao/ft_userdata/%E7%BB%8F%E5%85%B8%E6%8C%87%E6%A0%87%E6%9C%BA%E5%99%A8%E5%AD%A6%E4%B9%A0%E7%B3%BB%E7%BB%9F/user_data/strategies/SimpleStrategy.py#L135-L137)）。

### 3.4 指标库与实现约束

优先使用当前策略模板已使用的库与风格：
- TA-Lib：`import talib.abstract as ta`（SimpleStrategy：RSI/MACD/TEMA/SAR/ATR）
- qtpylib：`from technical import qtpylib`（SimpleStrategy：Bollinger Bands）

禁止项（为可移植性与可审计性）：
- 禁止在策略文件中修改 `sys.path`
- 禁止在策略文件中引入外部工程的策略库实现（跨目录依赖）

### 3.5 参数化（便于后续新增策略与调参）

关键阈值与窗口必须参数化，使用：
- `IntParameter`
- `DecimalParameter`

要求：
- 入场相关参数放在 `space="buy"`
- 离场/风控相关参数放在 `space="sell"`

### 3.6 风控与退出（复用 SimpleStrategy 框架）

建议所有新策略默认复用以下框架，并只调整阈值/触发条件：
- `use_custom_stoploss = True` + `custom_stoploss(...)`（ATR 动态止损/追踪）
- `custom_exit(...)`（分级回撤止盈 + 时间退出）

参考实现：
- [SimpleStrategy.custom_stoploss](file:///Users/zhangjiangtao/ft_userdata/%E7%BB%8F%E5%85%B8%E6%8C%87%E6%A0%87%E6%9C%BA%E5%99%A8%E5%AD%A6%E4%B9%A0%E7%B3%BB%E7%BB%9F/user_data/strategies/SimpleStrategy.py#L166-L230)
- [SimpleStrategy.custom_exit](file:///Users/zhangjiangtao/ft_userdata/%E7%BB%8F%E5%85%B8%E6%8C%87%E6%A0%87%E6%9C%BA%E5%99%A8%E5%AD%A6%E4%B9%A0%E7%B3%BB%E7%BB%9F/user_data/strategies/SimpleStrategy.py#L232-L265)

### 3.7 入场确认（可选但推荐）

如策略需要二次过滤，可实现：
- `confirm_trade_entry(...) -> bool`

参考实现：
- [SimpleStrategy.confirm_trade_entry](file:///Users/zhangjiangtao/ft_userdata/%E7%BB%8F%E5%85%B8%E6%8C%87%E6%A0%87%E6%9C%BA%E5%99%A8%E5%AD%A6%E4%B9%A0%E7%B3%BB%E7%BB%9F/user_data/strategies/SimpleStrategy.py#L267-L293)

### 3.8 可视化（必须）

每个策略必须提供 `plot_config`，至少包含：
- 主图：`close` + 该策略的关键结构（均线/通道/云/布林带等）
- 副图：至少一个核心振荡/趋势指标（如 RSI / MACD / Aroon / Stoch）

参考实现：
- [SimpleStrategy.plot_config](file:///Users/zhangjiangtao/ft_userdata/%E7%BB%8F%E5%85%B8%E6%8C%87%E6%A0%87%E6%9C%BA%E5%99%A8%E5%AD%A6%E4%B9%A0%E7%B3%BB%E7%BB%9F/user_data/strategies/SimpleStrategy.py#L294-L319)

## 4. 新增策略流程（按规范复制即可）

1. 复制 [SimpleStrategy.py](file:///Users/zhangjiangtao/ft_userdata/%E7%BB%8F%E5%85%B8%E6%8C%87%E6%A0%87%E6%9C%BA%E5%99%A8%E5%AD%A6%E4%B9%A0%E7%B3%BB%E7%BB%9F/user_data/strategies/SimpleStrategy.py) 为新文件
2. 修改类名/文件名，并将 `timeframe` 保持为 `1h`
3. 在 `populate_indicators` 中替换或新增本策略指标列
4. 在 `populate_entry_trend` / `populate_exit_trend` 中只写“可复现的规则”，避免隐藏状态机
5. 用 `IntParameter/DecimalParameter` 参数化核心阈值与窗口
6. 保持 `custom_stoploss/custom_exit/plot_config` 结构不变，仅调整参数或触发条件

## 5. 经典策略“落地到策略文件”的 ID 对照（用于后续生成 10 个策略文件）

下表用于把 methodology 页面中的 10 个经典策略，落地为本系统的 10 个独立策略文件。注意：本系统统一默认周期为 `1h`，与页面展示周期不同不影响“规则复现”，但会影响绩效指标，需要后续再做回测验证与调参。

| 策略 id | 文件名建议 | 类名建议 | 核心指标/结构 | 入场规则（概念） | 离场规则（概念） |
|---|---|---|---|---|---|
| turtle_trading | TurtleTradingStrategy.py | TurtleTradingStrategy | Donchian(20/55) + Exit(10) | 突破通道上/下轨顺势入场 | 突破退出通道反向退出 |
| bollinger_band_mean_reversion | BollingerBandMeanReversionStrategy.py | BollingerBandMeanReversionStrategy | Bollinger(20,2σ) | 跌破下轨做多；突破上轨做空 | 回到中轨退出 |
| rsi_mean_reversion | RsiMeanReversionStrategy.py | RsiMeanReversionStrategy | RSI(14) | RSI<阈值做多；RSI>阈值做空 | RSI 回到 50 退出 |
| macd_trend_following | MacdTrendFollowingStrategy.py | MacdTrendFollowingStrategy | MACD/Signal | MACD 上/下穿 Signal 入场 | 反向交叉退出/反手 |
| ichimoku_cloud_trend | IchimokuCloudTrendStrategy.py | IchimokuCloudTrendStrategy | Ichimoku 云 + Tenkan/Kijun | 云上金叉做多；云下死叉做空 | 跌破/突破 Kijun 或反向交叉退出 |
| parabolic_sar_trend | ParabolicSarTrendStrategy.py | ParabolicSarTrendStrategy | Parabolic SAR | 收盘上穿 SAR 做多；下穿做空 | 反向信号退出 |
| keltner_channel_breakout | KeltnerChannelBreakoutStrategy.py | KeltnerChannelBreakoutStrategy | EMA + ATR 通道 | 突破上/下轨入场 | 回到中轨退出 |
| aroon_trend_system | AroonTrendSystemStrategy.py | AroonTrendSystemStrategy | Aroon Up/Down | Up/Down 交叉且阈值过滤入场 | 反向交叉或跌破阈值退出 |
| nr7_volatility_contraction_breakout | Nr7VolatilityContractionBreakoutStrategy.py | Nr7VolatilityContractionBreakoutStrategy | NR7（区间最小） | 突破上一根 NR7 高/低入场 | 突破 NR7 反向线退出 |
| stochastic_oscillator_reversal | StochasticOscillatorReversalStrategy.py | StochasticOscillatorReversalStrategy | Stoch %K/%D | 超卖金叉做多；超买死叉做空 | %K 回到 50 退出 |

## 6. 开发自检清单（复制到 PR/变更说明里即可）

- 新策略文件位于：`经典指标机器学习系统/user_data/strategies/`
- `timeframe` 默认值为 `1h`
- 实现了 `populate_indicators / populate_entry_trend / populate_exit_trend`
- entry/exit 字段初始化齐全，且处理了同 bar 多空冲突
- 核心阈值/窗口使用 `IntParameter/DecimalParameter` 参数化
- 未修改 `sys.path`，未引入外部工程策略依赖
- 保留并复用 `custom_stoploss` 与 `custom_exit`（或明确说明为什么不使用）
- 提供 `plot_config`，主图+副图可解释策略信号
