# SPEC: 趋势跟踪 + 正金字塔加仓 + 网格交易策略落地

> **状态：** Spec（待评审）
> **创建：** 2026-09-10
> **目标：** 为自进化系统扩展两类进阶"策略型"交易方法（不是单纯买入卖出）：① 趋势跟踪（海龟法则）+ 正金字塔顺势加仓，作为 V15 倒金字塔的"趋势市镜像"；② 网格交易，作为震荡市波动套利层。两者通过 regime 闸门软切换，补齐 V15"无止损 + 单边必爆"的致命短板。
> **约束：** FAIL-OPEN 铁律不可破坏；工业级代码标准；不新增不必要文件；硬约束遵循 CLAUDE.md（SL ≥ 4% / TP ≥ 12% / 爆仓安全边际优先 / 测试仓 ≤ 2 单 / 最小名义仓位 ≥ 250 USDT）。
> **调研根：** [2026-09-10-传统金融进阶策略调研-金字塔网格对冲.md](../2-KNOWLEDGE/7-EXTERNAL-RESEARCH/finance/trading-classics/2026-09-10-传统金融进阶策略调研-金字塔网格对冲.md)
> **基线对照：** [V9-马丁基线.md](../2-KNOWLEDGE/1-TRADING/V9-马丁基线.md) + [v15_trader.py#L2441](../14-V15经典马丁策略/core/v15_trader.py) `_place_addon_grid_orders`

***

## 零 · 问题总结

### 0.1 现状缺口

| 维度 | 现状 | 缺口 |
|:--|:--|:--|
| V15 倒金字塔 | 1 首单 + 4 加仓 = 总 5 单，8% 间距，4% 止盈，**无止损** | 单边下跌 40%+ 必爆仓（LUNA/FTM 前车之鉴） |
| 趋势跟踪 | ❌ 未实现 | CTA 40 年实盘验证的最扎实策略，与 V15 对称互补 |
| 正金字塔加仓 | ❌ 未实现 | Livermore 1929 + 海龟 1983 经典加仓法，趋势市必备 |
| 网格交易 | ❌ 未实现 | 震荡市波动套利层，与 V15 不同波动尺度叠加 |
| Donchian 通道 | ❌ V15 signal 模块缺 | 海龟法则核心信号源（20/55 日高低点突破） |
| ATR 计算 | ❌ V15 signal 模块缺 | 2N 止损 / 仓位 Unit 的数学基础 |
| regime 闸门 | V15 RegimeManager 仅多空方向，未区分趋势市/震荡市 | 需扩展为策略选择闸门 |

### 0.2 战略定位

```
            趋势市（ADX>25 + 价格突破 Donchian 55日）
                ↓ regime_gate = "TREND"
        ┌───────────────────────────────┐
        │  趋势跟踪 + 正金字塔（新增）       │  ← 2N ATR 止损 + 0.5N 加仓
        │  - 入场：20日突破（快）/ 55日突破（慢）│
        │  - 止损：2×ATR（强制注入）          │
        │  - 加仓：每上涨 0.5N 加 1 Unit（最多4）│
        │  - 离场：跌破 10日低点 / 2N 止损     │
        └───────────────────────────────┘

            震荡市（ADX<25 + 价格在布林带内）
                ↓ regime_gate = "RANGE"
        ┌───────────────────────────────┐
        │  V15 倒金字塔（现有）+ 网格（新增）  │  ← 8% 加仓 + 网格高频套利
        │  - V15 处理大波动（8% 间距）       │
        │  - 网格处理小波动（ATR 自适应间距） │
        └───────────────────────────────┘

            危机市（20日波动率 > 历史 90 分位）
                ↓ regime_gate = "CRISIS"
        ┌───────────────────────────────┐
        │  全策略暂停 + 仅风控减仓            │
        └───────────────────────────────┘
```

### 0.3 与现有系统的关系

| 现有模块 | 关系 | 说明 |
|:--|:--|:--|
| V15 倒金字塔 | **对称镜像** | 趋势市走正金字塔，震荡市走 V15 倒金字塔，regime 闸门切换 |
| strategy_gene.py | **零摩擦入库** | ESS=H:S:N=4:4:2 评分天然适配，新策略作为 condition/action/combination |
| traditional_finance.py | **复用 RegimeDetector** | 现有 RegimeDetector 三态（trend_up/trend_down/ranging/crisis）直接作为 regime 闸门 |
| 五计庙算 war_state | **上游开关** | war_state=BAN 时所有策略探索停止（Hox 级围栏） |
| ReflectionEngine | **学习闭环** | 趋势跟踪低胜率高夏普，S 维度突出，ReflectionEngine 自动学习信号权重 |

***

## 一 · 架构设计

### 1.1 核心新增组件

```
                          ┌─────────────────────────────────────────────────┐
                          │      TrendFollowingEngine（新增）              │
                          │  (23-四层闭环自进化交易架构/dreambuddy_evolution/ │
                          │   engines/trend_following/)                    │
                          ├─────────────────────────────────────────────────┤
                          │                                                  │
  v15_signal.py ─────────→ │  DonchianChannel                                │
  （新增 calc_donchian,    │  → 20日/55日高低点突破信号                       │
   calc_atr）              │                                                  │
                          │  ATRStopCalculator                               │
                          │  → 2×ATR 止损价（多头/空头）                      │
                          │                                                  │
                          │  PyramidingPositionSizer                          │
                          │  → Unit = (Account × 1%) / (N × PointValue)     │
                          │  → 每 0.5N 加仓 1 Unit，最多 4 Unit              │
                          │                                                  │
                          │  TrendExitRule                                   │
                          │  → 跌破 10日低点（快）/ 20日低点（慢）            │
                          │  → 2N 止损触发                                   │
                          └─────────────────────────────────────────────────┘

                          ┌─────────────────────────────────────────────────┐
                          │      GridTradingEngine（新增）                  │
                          │  (engines/grid_trading/)                        │
                          ├─────────────────────────────────────────────────┤
                          │                                                  │
                          │  GridParameterCalculator                         │
                          │  → 间距 Δ = ATR × k（k=1.0~2.0，币种自适应）     │
                          │  → 网格数 N = (P_high - P_low) / Δ              │
                          │  → 单格金额 q = 仓位预算 / N（递减式）          │
                          │                                                  │
                          │  GridOrderPlacer                                 │
                          │  → 等距布置买卖限价单                            │
                          │  → 价格每跌一格买入、每涨一格卖出                │
                          │                                                  │
                          │  GridRiskGate                                    │
                          │  → 硬止损线：跌破下界 X% 停止加仓               │
                          │  → 趋势市暂停：regime=TREND 时停止网格           │
                          └─────────────────────────────────────────────────┘

                          ┌─────────────────────────────────────────────────┐
                          │      RegimeGateSwitch（新增，复用 TraditionalFinanceBridge）│
                          ├─────────────────────────────────────────────────┤
                          │                                                  │
                          │  detect_regime(kline_data)                       │
                          │  → TREND（ADX>25 + Donchian 突破）              │
                          │  → RANGE（ADX<25 + 布林带内）                   │
                          │  → CRISIS（20日波动率 > 历史 90 分位）           │
                          │                                                  │
                          │  route_strategy(regime)                          │
                          │  → TREND → TrendFollowingEngine                  │
                          │  → RANGE → V15 + GridTradingEngine              │
                          │  → CRISIS → 暂停开新仓                          │
                          └─────────────────────────────────────────────────┘
```

### 1.2 数据流

```
K线收盘事件
    ↓
KlineEventHandler.on_kline_close()
    ↓
RegimeGateSwitch.detect_regime(kline_data)
    ↓ regime ∈ {TREND, RANGE, CRISIS}
    ├── regime == "TREND"
    │   ↓
    │   TrendFollowingEngine.evaluate(kline_data)
    │   ├── DonchianChannel.breakout_signal() → 20日/55日突破
    │   ├── ATRStopCalculator.calc_stop(entry_price, atr) → 2×ATR 止损
    │   ├── PyramidingPositionSizer.calc_unit(account, atr) → Unit 仓位
    │   └── TrendExitRule.check_exit(position, kline_data) → 离场信号
    │   ↓
    │   生成 trade_signal → BCRM2 风控检查 → 执行
    │
    ├── regime == "RANGE"
    │   ↓
    │   V15 倒金字塔（现有 _place_addon_grid_orders）
    │   + GridTradingEngine.evaluate(kline_data)
    │   ↓
    │   生成 trade_signal → BCRM2 风控检查 → 执行
    │
    └── regime == "CRISIS"
        ↓
        暂停开新仓 + 仅允许平仓/减仓
```

### 1.3 模块归属与冻结约束

| 模块 | 归属目录 | 冻结约束 |
|:--|:--|:--|
| TrendFollowingEngine | `23-四层闭环自进化交易架构/dreambuddy_evolution/engines/trend_following/` | 独立包，符合"自进化系统离场策略代码归属 dreambuddy_evolution/engines/"约束 |
| GridTradingEngine | `23-四层闭环自进化交易架构/dreambuddy_evolution/engines/grid_trading/` | 独立包 |
| RegimeGateSwitch | `23-四层闭环自进化交易架构/dreambuddy_evolution/engines/regime_gate.py` | 复用 TraditionalFinanceBridge.RegiDetector，扩展策略路由 |
| Donchian/ATR 信号 | `14-V15经典马丁策略/core/v15_signal.py`（新增函数） | 复用现有 v15_signal 模块，不新建文件 |
| strategy_gene 入库 | `23-四层闭环自进化交易架构/dreambuddy_evolution/gene_data/strategy_genes/` | 复用现有 gene 库结构 |

***

## 二 · 落地切片（TDD 分阶段）

### Phase A：Donchian 通道 + ATR 信号模块（基础层）

**目标：** 为 V15 signal 模块补齐海龟法则核心信号源。

**TDD 任务：**

1. **RED：** 写 `test_donchian_atr.py`，断言 `ModuleNotFoundError` for `from v15_signal import calc_donchian, calc_atr`
2. **GREEN：** 在 `v15_signal.py` 新增：
   - `calc_atr(highs, lows, closes, period=14)` — Average True Range
   - `calc_donchian(highs, lows, period=20)` — Donchian 通道（上轨=period 日最高，下轨=period 日最低）
3. **边界测试：**
   - 数据不足（< period）返回中性默认值
   - 极端值（全相同价格）不报错
4. **验收：** `pytest test_donchian_atr.py` 全绿

**关键参数：**
```python
# ATR
ATR_PERIOD = 14  # 标准 14 日
# True Range = max(H-L, |H-PC|, |L-PC|)
# ATR = TR 的 SMA 或 EMA

# Donchian
DONCHIAN_FAST = 20   # 海龟快系统
DONCHIAN_SLOW = 55   # 海龟慢系统
# 突破信号：收盘价 > 上轨（做多）/ 收盘价 < 下轨（做空）
```

### Phase B：TrendFollowingEngine + 正金字塔加仓（核心层）

**目标：** 实现趋势跟踪策略 + 顺势金字塔加仓 + 2N 止损。

**TDD 任务：**

1. **RED：** 写 `test_trend_following_engine.py`，断言 `ModuleNotFoundError` for `from dreambuddy_evolution.engines.trend_following import TrendFollowingEngine`
2. **GREEN：** 新建 `engines/trend_following/__init__.py` + `trend_following_engine.py`，实现：
   - `TrendFollowingEngine.evaluate(kline_data, account_state)` → 生成 trade_signal
   - `DonchianChannel.breakout_signal(kline_data)` → 突破信号
   - `ATRStopCalculator.calc_stop(entry_price, atr, direction)` → 2×ATR 止损
   - `PyramidingPositionSizer.calc_unit(account, atr, point_value)` → Unit 仓位
   - `PyramidingPositionSizer.calc_addon tiers(current_price, entry_price, atr)` → 0.5N 加仓阶梯
   - `TrendExitRule.check_exit(position, kline_data)` → 离场信号
3. **验收：**
   - 20 日突破 + 2N 止损 + 0.5N 加仓 = 海龟快系统
   - 55 日突破 + 2N 止损 + 0.5N 加仓 = 海龟慢系统
   - 单测覆盖：趋势确认、止损触发、加仓阶梯、离场信号

**关键参数（硬约束）：**
```python
# 仓位
RISK_PER_TRADE = 0.01  # 1% 账户风险（海龟标准）
MAX_UNITS = 4          # 最多 4 个加仓 Unit（正金字塔）
ADDON_INTERVAL = 0.5   # 每 0.5×ATR 加仓 1 Unit

# 止损（硬约束：SL ≥ 4%）
ATR_STOP_MULTIPLIER = 2.0  # 2×ATR 止损
# 若 2×ATR < 4%，则 SL = 4%（下限保护）
# 若 2×ATR > 15%，则 SL = 15%（上限保护）

# 止盈
EXIT_FAST = 10  # 跌破 10 日低点离场（快系统）
EXIT_SLOW = 20  # 跌破 20 日低点离场（慢系统）

# 最小名义仓位
MIN_NOTIONAL = 250  # USDT（与 BCRM2.0/evolution 对齐）
```

### Phase C：GridTradingEngine（震荡市层）

**目标：** 实现网格交易，与 V15 在不同波动尺度叠加。

**TDD 任务：**

1. **RED：** 写 `test_grid_trading_engine.py`，断言 `ModuleNotFoundError` for `from dreambuddy_evolution.engines.grid_trading import GridTradingEngine`
2. **GREEN：** 新建 `engines/grid_trading/__init__.py` + `grid_trading_engine.py`，实现：
   - `GridParameterCalculator.calc_params(kline_data, budget)` → 间距 Δ、网格数 N、单格金额 q
   - `GridOrderPlacer.place_grid(client, inst_id, params)` → 布置买卖限价单
   - `GridRiskGate.check_stop(position, kline_data)` → 硬止损线检查
3. **验收：**
   - 间距 Δ = ATR × k（k=1.0~2.0）
   - 硬止损线：跌破下界 X% 停止加仓
   - 趋势市暂停：regime=TREND 时停止网格

**关键参数：**
```python
# 网格间距
GRID_ATR_MULTIPLIER = 1.0  # Δ = 1×ATR（可调 1.0~2.0）
GRID_MAX_COUNT = 20         # 最多 20 格
GRID_SINGLE_BUDGET_RATIO = 0.05  # 单格 = 5% 仓位预算（递减式）

# 硬止损（硬约束：SL ≥ 4%）
GRID_STOP_LOSS_PCT = 0.08  # 跌破下界 8% 停止加仓
# 与 V15 的 8% 加仓间距对齐

# 趋势市暂停
GRID_REGIME_FILTER = True  # regime=TREND 时停止网格
```

### Phase D：RegimeGateSwitch（策略路由层）

**目标：** 实现 regime 闸门软切换，路由到对应策略。

**TDD 任务：**

1. **RED：** 写 `test_regime_gate_switch.py`，断言 `ModuleNotFoundError` for `from dreambuddy_evolution.engines.regime_gate import RegimeGateSwitch`
2. **GREEN：** 新建 `engines/regime_gate.py`，实现：
   - `RegimeGateSwitch.detect_regime(kline_data)` → TREND/RANGE/CRISIS
   - `RegimeGateSwitch.route_strategy(regime)` → 调用对应引擎
   - 复用 `TraditionalFinanceBridge.RegimeDetector` 的 ADX/波动率逻辑
3. **验收：**
   - TREND: ADX>25 + Donchian 突破
   - RANGE: ADX<25 + 价格在布林带内
   - CRISIS: 20 日波动率 > 历史 90 分位
   - 软切换：V15 + 趋势跟踪可双层叠加（不同仓位隔离）

### Phase E：strategy_gene 入库 + ESS 评分接入

**目标：** 将新策略作为 condition/action/combination 入库，ESS 评分。

**TDD 任务：**

1. 新增 condition 基因：
   - `CD-DONCHIAN-20-BREAK.json`（20 日突破）
   - `CD-DONCHIAN-55-BREAK.json`（55 日突破）
   - `CD-ATR-EXPANDING.json`（ATR 扩张，趋势确认）
   - `CD-ADX-GT25-TREND.json`（ADX>25 趋势市）
   - `CD-BOLL-WIDTH-NARROW.json`（布林带收窄，网格入场）
   - `CD-ADX-LT25-RANGE.json`（ADX<25 震荡市）
2. 新增 action 基因：
   - `AC-PYRAMID-UNIT-0.5N.json`（正金字塔 0.5N 加仓）
   - `AC-ATR-STOP-2N.json`（2×ATR 止损）
   - `AC-GRID-PLACE-ATR.json`（网格 ATR 间距布置）
3. 新增 combination：
   - `CB-TREND-001`（趋势跟踪快系统：20日突破 + 2N止损 + 0.5N加仓）
   - `CB-TREND-002`（趋势跟踪慢系统：55日突破 + 2N止损 + 0.5N加仓）
   - `CB-GRID-030`（网格交易：布林带收窄 + ATR间距 + 硬止损8%）
4. ESS 评分：初始 N=0 → 冷启动（样本<20 不调整权重）

### Phase F：Shadow + 小额实盘并行验证

**目标：** 双轨验证策略有效性。

**任务：**

1. **Shadow mode：**
   - 用 `shadow_backtest.py` 跑 3-6 个月历史数据
   - 对比 V15 基线 vs 趋势跟踪 + 网格组合
   - 验收标准：Sharpe > V9/V15 基线、MaxDD < V9/V15 基线
2. **小额实盘：**
   - 趋势跟踪：50U 保证金（250U 名义价值 @5x）
   - 网格：50U 保证金
   - 测试周期：1-2 周
   - 监控：止损触发率、加仓次数、滑点
3. **上线门槛：**
   - Sharpe Ratio > V9 基线（BTC > 1.50, SOL > 1.85, ETH > 2.05）
   - MaxDD < V9 基线
   - 无爆仓事件

***

## 三 · 验收标准

### 3.1 功能验收

| 验收项 | 标准 | 测试方式 |
|:--|:--|:--|
| Donchian 通道 | 20/55 日突破信号正确 | `test_donchian_atr.py` |
| ATR 计算 | 14 日 ATR 与 talib.ATR 一致 | `test_donchian_atr.py` |
| 趋势跟踪入场 | 20/55 日突破触发 | `test_trend_following_engine.py` |
| 2N 止损 | 止损价 = entry ± 2×ATR，下限 4%，上限 15% | 单测 |
| 正金字塔加仓 | 每 0.5N 加 1 Unit，最多 4 Unit | 单测 |
| 网格间距 | Δ = ATR × k，自适应 | `test_grid_trading_engine.py` |
| 网格硬止损 | 跌破下界 8% 停止加仓 | 单测 |
| regime 闸门 | TREND/RANGE/CRISIS 正确路由 | `test_regime_gate_switch.py` |
| strategy_gene 入库 | 新增 6 condition + 3 action + 3 combination | `load_gene_library()` 通过 |

### 3.2 性能验收

| 指标 | V9/V15 基线 | 趋势跟踪+网格目标 |
|:--|:--|:--|
| Sharpe Ratio（BTC） | 1.50 | > 1.50 |
| Sharpe Ratio（SOL） | 1.85 | > 1.85 |
| Sharpe Ratio（ETH） | 2.05 | > 2.05 |
| Max Drawdown | V9 基线 | < V9 基线 |
| 爆仓事件 | V15 单边必爆 | 0（2N 止损注入） |

### 3.3 硬约束验收（CLAUDE.md 对齐）

| 硬约束 | 标准 | 落地方式 |
|:--|:--|:--|
| SL ≥ 4% / TP ≥ 12% | 趋势跟踪 SL=2×ATR，下限 4% | ATRStopCalculator 下限保护 |
| 爆仓安全边际 | SL 先触发再爆仓 | 2×ATR 止损严格位于爆仓价安全侧 |
| 测试仓 ≤ 2 单 | trend=probe 最多 2 单 | PyramidingPositionSizer 限制 |
| 最小名义仓位 ≥ 250 USDT | MIN_NOTIONAL = 250 | 与 BCRM2.0/evolution 对齐 |
| FAIL-OPEN | 任何异常→中性兜底+日志 | TrendFollowingEngine/GridTradingEngine 全异常捕获 |
| 仓位上限 | 加仓后综合杠杆不超爆仓线 | PyramidingPositionSizer 爆仓检查 |

***

## 四 · 风险与回滚

### 4.1 风险清单

| 风险 | 概率 | 影响 | 缓解措施 |
|:--|:--|:--|:--|
| 趋势跟踪震荡市 whipsaw | 高 | 中 | regime 闸门过滤，仅 ADX>25 启用 |
| 网格单边踏空 | 中 | 高 | 硬止损 8% + 趋势市暂停 |
| 2N 止损过紧被插针 | 中 | 中 | ATR 上限 15% + 滑点保护 |
| V15 + 趋势跟踪仓位冲突 | 中 | 高 | 仓位隔离 + BCRM2 风控检查 |
| regime 误判 | 中 | 高 | CRISIS 兜底（暂停开新仓） |
| 流动性枯竭 | 低 | 高 | 限高流动性币种（BTC/ETH/SOL） |

### 4.2 回滚方案

| 回滚级别 | 触发条件 | 动作 |
|:--|:--|:--|
| L1 | 单笔亏损 > 5% | 暂停趋势跟踪 1 小时 |
| L2 | 单日亏损 > 10% | 暂停所有新策略，仅 V15 运行 |
| L3 | Sharpe < V9 基线（回测） | 不上线 |
| L4 | 爆仓事件 | 立即下线，全量回滚 |

### 4.3 灰度推进

```
Step 1: Shadow mode 回测（3-6 月历史数据）
    ↓ 验收通过
Step 2: 小额实盘（50U 保证金，1-2 周）
    ↓ 验收通过
Step 3: 正常仓位（250U 名义价值，1 个月）
    ↓ 验收通过
Step 4: 全量上线（多币种扩展）
```

***

## 五 · 硬约束清单（供认知库 record）

> 以下约束一旦用户确认，立即调用 `record` 写入认知库（≥B 级 + 硬约束 tag）。

| ID | 硬约束 | 级别 |
|:--|:--|:--|
| HC-TF-01 | 趋势跟踪 SL 必须为 2×ATR，下限 4%，上限 15% | B |
| HC-TF-02 | 正金字塔最多 4 个加仓 Unit，每 0.5N 加仓 1 Unit | B |
| HC-TF-03 | regime=TREND 时启用趋势跟踪，regime=RANGE 时启用 V15+网格，regime=CRISIS 时暂停开新仓 | B |
| HC-TF-04 | V15 + 趋势跟踪仓位必须隔离，不可同一仓位叠加 | B |
| HC-TF-05 | 网格交易必须设硬止损 8%，趋势市必须暂停网格 | B |
| HC-TF-06 | 测试仓（tier=probe）最多 2 单，最小名义仓位 250 USDT | B |
| HC-TF-07 | TrendFollowingEngine/GridTradingEngine 任何异常→中性兜底+日志，不阻塞交易（FAIL-OPEN） | B |
| HC-TF-08 | 趋势跟踪 + 正金字塔代码归属 dreambuddy_evolution/engines/trend_following/，符合独立包冻结约束 | B |
| HC-TF-09 | 网格交易代码归属 dreambuddy_evolution/engines/grid_trading/ | B |
| HC-TF-10 | 上线门槛：Sharpe > V9 基线（BTC>1.50, SOL>1.85, ETH>2.05）+ MaxDD < V9 基线 + 0 爆仓 | B |

***

## 六 · 落地顺序

```
Phase A: Donchian + ATR 信号模块（基础层，无风险）
    ↓
Phase B: TrendFollowingEngine + 正金字塔（核心层）
    ↓
Phase C: GridTradingEngine（震荡市层）
    ↓
Phase D: RegimeGateSwitch（策略路由层）
    ↓
Phase E: strategy_gene 入库 + ESS 评分
    ↓
Phase F: Shadow + 小额实盘并行验证
    ↓
上线（灰度推进）
```

每个 Phase 遵循 TDD：RED（写测试断言 ModuleNotFoundError）→ GREEN（实现）→ REFACTOR（重构）。

***

## 七 · 不做的事（边界）

- ❌ 不实现 DCA（P4，优先级最低，独立沉淀层）
- ❌ 不实现对冲/统计套利（P3，与 V15 互斥，独立并行层）
- ❌ 不修改 V15 现有 `_place_addon_grid_orders` 逻辑（仅新增镜像分支）
- ❌ 不修改 strategy_gene.py 的 ESS 公式（仅入库新基因）
- ❌ 不修改五计庙算 war_state（仅消费其输出）
- ❌ 不新建非必要文件（所有新代码归入 dreambuddy_evolution/engines/ 或 v15_signal.py）

***

*SPEC 完。等待用户确认后，硬约束 HC-TF-01~10 立即写入认知库，然后按 Phase A→F 依次落地。*
