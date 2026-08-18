# LightGBM 特征消费分类总览

> 本文档梳理12-三屏趋势系统中LightGBM消费的全部特征，按来源和功能分类，
> 并标注哪些特征来自实践回测验证，便于后续从实践回测中继续优化。
>
> 更新时间：2026-07-18
> 特征总数：107+维（跨3个特征管道）
> 基线策略: V4减半周期逃顶（HalvingTopExitStrategy，综合评分1.592）
> 哲学特征: 26维（V2十五个 + V4七个 + V5.3两个周期相似性精选）

---

## 一、三个LightGBM消费管道

系统中有**3个独立的LightGBM消费管道**，各自消费不同来源的特征：

| 管道 | 特征工程 | LightGBM模型 | 特征维度 | 存储位置 |
|------|---------|-------------|---------|---------|
| **A. 价格特征管道** | [feature_engineer.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/feature_engineer.py) `TrendFeatureEngineer` | [models.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/models.py) `LightGBMModel` | ~30维 | `ml/models/current/` |
| **B. 阻力特征管道** | [lr_feature_engineer.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/lr_feature_engineer.py) `LeastResistanceFeatureEngineer` | [models.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/models.py) `LightGBMModel` | 67+维（含哲学26维） | `ml/models/current/` |
| **C. 集成推理管道** | [algo_ensemble.py](file:///Users/zhangjiangtao/WorkBuddy-v2/12-三屏趋势系统/ml/algo_ensemble.py) `extract_ensemble_features` | [algo_ensemble.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/algo_ensemble.py) `EnsemblePredictor` | 62维（含哲学26维） | `ml/models/ensemble/` |

---

## 二、管道A：价格特征管道（~30维）

**来源**：[feature_engineer.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/feature_engineer.py) `TrendFeatureEngineer`
**理论基础**：Alexander Elder三重滤网系统 + Elder-ray指标
**特征来源类型**：⚡理论驱动（非实践回测）

### A1. 趋势方向 direction（8维）— [feature_engineer.py:114-162](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/feature_engineer.py#L114-L162)

| 特征名 | 计算逻辑 | 来源类型 |
|--------|---------|---------|
| `ema_slope_{13,26,50,100}` | EMA斜率（4个周期） | ⚡理论 |
| `price_vs_ema_{13,26,50,100}` | 价格相对EMA的归一化位置（4个周期） | ⚡理论 |
| `trend_alignment` | EMA13/26/50/100多头排列得分(0-1) | ⚡理论 |
| `ema13_slope_dir` | EMA13斜率符号 | ⚡理论 |
| `hl_position_{20,60}` | 价格在过去N天high-low区间中的位置 | ⚡理论 |

### A2. 趋势变化 change（9维）— [feature_engineer.py:164-248](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/feature_engineer.py#L164-L248)

| 特征名 | 计算逻辑 | 来源类型 |
|--------|---------|---------|
| `bullish_divergence` | Elder-ray看涨背离强度 | ⚡理论 |
| `bearish_divergence` | Elder-ray看跌背离强度 | ⚡理论 |
| `bull_power_negative` | Bull Power穿越零线转负 | ⚡理论 |
| `bear_power_positive` | Bear Power穿越零线转正 | ⚡理论 |
| `macd_hist_change` | MACD柱变化率 | ⚡理论 |
| `macd_reversal_signal` | MACD柱方向反转 | ⚡理论 |
| `momentum_turn_{10,20}` | 动量转折（一阶导数符号变化） | ⚡理论 |
| `rsi_bear_divergence` | RSI看跌背离 | ⚡理论 |
| `rsi_bull_divergence` | RSI看涨背离 | ⚡理论 |

### A3. 趋势速率 velocity（9维）— [feature_engineer.py:250-293](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/feature_engineer.py#L250-L293)

| 特征名 | 计算逻辑 | 来源类型 |
|--------|---------|---------|
| `price_velocity_{5,10,20}` | 多周期ROC（3个周期） | ⚡理论 |
| `price_acceleration_{10,20}` | 二阶导数加速度（2个周期） | ⚡理论 |
| `vol_adj_velocity_{5,10,20}` | ATR归一化速度（3个周期） | ⚡理论 |
| `ema13_slope_accel` | EMA斜率加速度 | ⚡理论 |
| `momentum_accel_10` | 10日动量加速度 | ⚡理论 |

### A4. Elder-ray力量 power（10维）— [feature_engineer.py:295-371](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/feature_engineer.py#L295-L371)

| 特征名 | 计算逻辑 | 来源类型 |
|--------|---------|---------|
| `bull_power_norm` | 归一化多头力量 | ⚡理论 |
| `bear_power_norm` | 归一化空头力量 | ⚡理论 |
| `bull_power_slope` | 多头力量趋势 | ⚡理论 |
| `bear_power_slope` | 空头力量趋势 | ⚡理论 |
| `bull_exhaustion` | 多头衰竭信号 | ⚡理论 |
| `bear_exhaustion` | 空头衰竭信号 | ⚡理论 |
| `power_balance` | 多空平衡 | ⚡理论 |
| `power_balance_change` | 多空平衡变化 | ⚡理论 |
| `both_weakening` | 双方力量同时减弱（变盘前兆） | ⚡理论 |
| `bull_cross_negative` / `bear_cross_positive` | 力量穿越零线 | ⚡理论 |

### A5. 多尺度层级 hierarchy（8维）— [feature_engineer.py:373-466](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/feature_engineer.py#L373-L466)

| 特征名 | 计算逻辑 | 来源类型 |
|--------|---------|---------|
| `macro_trend_slope` | 周线级(EMA100)大趋势方向 | ⚡理论 |
| `macro_trend_dir` | 大趋势方向符号 | ⚡理论 |
| `micro_trend_slope` | 日线级(EMA13)小趋势方向 | ⚡理论 |
| `trend_scale_alignment` | 大小趋势一致性 | ⚡理论 |
| `counter_trend_accum_{10,20}` | 小趋势与大趋势反向累积强度 | ⚡理论 |
| `reversal_warning` | 趋势逆转预警 | ⚡理论 |
| `vol_compression` | 波动率压缩/扩张 | ⚡理论 |
| `volume_trend_20` | 量价配合 | ⚡理论 |

---

## 三、管道B：阻力特征管道（60+维）

**来源**：[lr_feature_engineer.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/lr_feature_engineer.py) `LeastResistanceFeatureEngineer`
**理论基础**：最小阻力方向理论（五维阻力融合）
**特征来源类型**：⚡理论驱动 + 🔬实践回测（哲学15维）

### B1. 五维阻力 daily_res（7维）— [lr_feature_engineer.py:219-227](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/lr_feature_engineer.py#L219-L227)

| 特征名 | 计算逻辑 | 来源类型 |
|--------|---------|---------|
| `daily_res_{price,volume,momentum,trend,fundamental}` | 日线五维阻力差（5维） | ⚡理论 |
| `daily_res_diff` | 日线总阻力差 | ⚡理论 |
| `daily_confidence` | 日线置信度 | ⚡理论 |

### B2. 五维阻力 weekly_res（7维）— [lr_feature_engineer.py:229-236](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/lr_feature_engineer.py#L229-L236)

| 特征名 | 计算逻辑 | 来源类型 |
|--------|---------|---------|
| `weekly_res_{price,volume,momentum,trend,fundamental}` | 周线五维阻力差（5维） | ⚡理论 |
| `weekly_res_diff` | 周线总阻力差 | ⚡理论 |
| `weekly_confidence` | 周线置信度 | ⚡理论 |

### B3. 跨周期一致性 cross（8维）— [lr_feature_engineer.py:238-255](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/lr_feature_engineer.py#L238-L255)

| 特征名 | 计算逻辑 | 来源类型 |
|--------|---------|---------|
| `cross_dir_consistency` | 周/日方向一致性(1/-1/0) | ⚡理论 |
| `cross_dir_diff` | 周/日阻力差之差 | ⚡理论 |
| `cross_conf_ratio` | 日/周置信度比 | ⚡理论 |
| `cross_{price,volume,momentum,trend,fundamental}_diff` | 各维度周/日差异（5维） | ⚡理论 |

### B4. 历史变化 daily_vel/weekly_vel（4维）— [lr_feature_engineer.py:257-284](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/lr_feature_engineer.py#L257-L284)

| 特征名 | 计算逻辑 | 来源类型 |
|--------|---------|---------|
| `daily_velocity` | 日线阻力差速度 | ⚡理论 |
| `daily_conf_velocity` | 日线置信度速度 | ⚡理论 |
| `daily_acceleration` | 日线阻力差加速度 | ⚡理论 |
| `weekly_velocity` / `weekly_acceleration` | 周线速度/加速度 | ⚡理论 |

### B5. 多窗口统计 daily_window/weekly_window（20+维）— [lr_feature_engineer.py:286-303](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/lr_feature_engineer.py#L286-L303)

| 特征名 | 计算逻辑 | 来源类型 |
|--------|---------|---------|
| `daily_dir_mean_{1,3,5,10,20}` | 多窗口阻力差均值（5维） | ⚡理论 |
| `daily_dir_std_{1,3,5,10,20}` | 多窗口阻力差方差（5维） | ⚡理论 |
| `daily_conf_mean_{1,3,5,10,20}` | 多窗口置信度均值（5维） | ⚡理论 |
| `daily_dir_slope_{1,3,5,10,20}` | 多窗口阻力差斜率（5维） | ⚡理论 |
| `weekly_dir_mean_{1,3,5,10}` | 周线多窗口均值（4维） | ⚡理论 |

### B6. 趋势强度 trend_strength/dominant（2维）— [lr_feature_engineer.py:287-303](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/lr_feature_engineer.py#L287-L303)

| 特征名 | 计算逻辑 | 来源类型 |
|--------|---------|---------|
| `trend_strength_est` | 趋势强度估计 | ⚡理论 |
| `dominant_res_dim` | 当前主导阻力维度索引 | ⚡理论 |

### B7. 基本面 screen1/fundamental_9（15+维）— [fundamental_adapter.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/fundamental_adapter.py)

| 特征名 | 计算逻辑 | 来源类型 |
|--------|---------|---------|
| `s1_{composite,momentum,value,growth,quality,sentiment}` | Screen1六维（6维） | ⚡理论 |
| `f9_{pe_ttm,pb,roe,revenue_growth,profit_growth,debt_ratio,cash_ratio,gross_margin,net_margin}` | 9基本面信号（9维） | ⚡理论 |

### B8. ⭐ 哲学贡献特征 philosophy（26维：V2十五个+V4七个+V5.3两个）— [philosophy_feature_engineer.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/philosophy_feature_engineer.py) + [halving_top_exit_strategy.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/halving_top_exit_strategy.py)

#### V2原有哲学特征（15维，V2基线验证）

| 特征名 | 哲学贡献 | 来源类型 | 实践验证 |
|--------|---------|---------|---------|
| `btc_regime_label` | BTC/小币分化 | 🔬实践回测 | 9年4币种 |
| `btc_alt_divergence` | BTC/小币分化 | 🔬实践回测 | 9年4币种 |
| `is_btc_asset` | BTC/小币分化 | 🔬实践回测 | 9年4币种 |
| `alt_short_risk_score` | BTC/小币分化 | 🔬实践回测 | UNI -99.62%→+41.76% |
| `weekly_ma200_distance` | 左侧抄底 | 🔬实践回测 | 8.5%时间触发，ML唯一有效V2抄底特征 |
| `dip_buy_level` | 左侧抄底 | 🔬实践回测 | ⚠️ML冗余：贡献BTC +246pp但WF重要性=0.0 |
| `dip_buy_position_ratio` | 左侧抄底 | 🔬实践回测 | ⚠️ML冗余：派生特征，WF重要性=0.0 |
| `left_side_buy_signal` | 左侧抄底 | 🔬实践回测 | ⚠️ML冗余：三级派生链末端，WF重要性=0.0 |
| `bear_short_layer` | 分层仓位 | 🔬实践回测 | 3/5成优于5/7成 |
| `fib_tp_remaining_ratio` | 分层仓位 | 🔬实践回测 | 337天触发止盈 |
| `layered_position_target` | 分层仓位 | 🔬实践回测 | 9年4币种 |
| `position_adjustment` | 分层仓位 | 🔬实践回测 | 9年4币种 |
| `btc_bull_confirmed` | 双牛过滤 | 🔬实践回测 | 9年4币种 |
| `self_bull_confirmed` | 双牛过滤 | 🔬实践回测 | 9年4币种 |
| `double_bull_score` | 双牛过滤 | 🔬实践回测 | UNI双牛率16% |

#### V4新增哲学特征（7维，已整合 + Walk-Forward验证完成）

| 特征名 | 哲学贡献 | 来源类型 | 实践验证 | 整合状态 | WF排名 | 重要性 |
|--------|---------|---------|---------|---------|--------|--------|
| `halving_months_after` | 减半周期时间锚定 | 🔬实践回测 | 9年BTC回测，评分1.592 | ✅核心 | #1 | 155.9 |
| `halving_phase` | 减半周期时间锚定 | 🔬实践回测 | normal/warn/danger/peak四阶段 | ⚠️冗余 | #61 | 0.0 |
| `halving_position_cap` | 四阶段仓位递减 | 🔬实践回测 | 100%→70%→30%→0%递减 | ⚠️冗余 | #64 | 0.0 |
| `ma128_distance_pct` | 四阶段仓位递减 | 🔬实践回测 | MA128破位卖出核心 | ✅核心 | #8 | 52.9 |
| `ma128_below_days` | 越高越卖 | 🔬实践回测 | 连续低于MA128天数 | ✅核心 | #10 | 38.5 |
| `ath_drawdown_pct` | 越高越卖 | 🔬实践回测 | 距历史高点回撤 | ✅核心 | #5 | 89.9 |
| `bounce_from_low_pct` | 越高越卖 | 🔬实践回测 | 从近期低点反弹幅度 | ⚠️低相关 | #43 | 2.2 |

> **Stage 1 Walk-Forward 验证结论**（2026-07-19）：
> - 核心V4特征（4个）平均排名 #6.0/74 = Top 8.1%，**验证通过**
> - `halving_months_after` 排名 #1，是TOP_EXIT场景最重要的特征
> - `halving_phase` 和 `halving_position_cap` 与 `halving_months_after` 信息冗余，LightGBM选择了连续值版本
> - `bounce_from_low_pct` 更适合 BEAR_EXIT 场景，在 TOP_EXIT 中相关性低
> - V4 vs V2 排名优势：+22.3 位（V4平均排名27.4 vs V2平均排名49.7）
> - 改进标签（期末跌幅>20%）下，平均测试AUC=0.6888，衰减率26.7%
>
> **V4特征整合计划**：详见 [engineering_algorithm_roadmap.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/engineering_algorithm_roadmap.md) Stage 1
> **验证脚本**：[walk_forward_v4_validation.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/walk_forward_v4_validation.py)
> **验证结果**：[stage1_improved_label_result.json](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/backtest_results/stage1_improved_label_result.json)

#### Stage 2.1 新增哲学特征（2维，假设DIP-001验证完成）

| 特征名 | 哲学贡献 | 来源类型 | 实践验证 | 整合状态 | DIP_BUY WF排名 | 重要性 |
|--------|---------|---------|---------|---------|---------------|--------|
| `rsi_14` | 量价抄底确认 | 🧪假设测试 | ❌假设被拒绝 | ⚠️低效 | #30 | 8.9 |
| `volume_ratio_20d` | 量价抄底确认 | 🧪假设测试 | ❌假设被拒绝 | ⚠️低效 | #45 | 2.6 |

> **Stage 2.1 假设DIP-001验证结论**（2026-07-19，REJECTED）：
> - 假设：周线MA200附近 + 日线RSI<30 + 成交量放大 = 高质量抄底点
> - 新增2维哲学8特征（特征总数 74→76）
> - DIP_BUY场景WF验证：AUC 0.5929→0.5540（**-0.0389**），衰减率 37.5%→41.5%（**+4.0pp**）
> - `rsi_14` 排名 #30（重要性8.9），`volume_ratio_20d` 排名 #45（重要性2.6），均未进Top30%
> - **结论**：传统技术指标在DIP_BUY场景无增益，已被趋势特征隐式覆盖
> - **决策**：保留特征代码（practice_validated=False），不作为DIP_BUY核心特征
>
> **对比Top 10特征**：V4特征主导DIP_BUY场景（4/7进Top30%），`halving_months_after`#1(237.8)，`weekly_ma200_distance`仍是唯一有效的V2抄底特征(#7, 82.2)
>
> **验证脚本**：[stage2_dip_buy_validation.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/stage2_dip_buy_validation.py)
> **验证结果**：[stage2_dip_buy_result.json](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/backtest_results/stage2_dip_buy_result.json)

#### Stage 2.4 冗余特征清理验证（2026-07-19）

> **操作**：移除3个零重要性派生特征（`dip_buy_level`/`dip_buy_position_ratio`/`left_side_buy_signal`），特征总数 76→73
> **验证脚本**：[stage2_4_cleanup_validation.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/stage2_4_cleanup_validation.py)
> **验证结果**：[stage2_4_cleanup_result.json](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/backtest_results/stage2_4_cleanup_result.json)

**Stage 2.4 vs Stage 2.0/2.1 对比**：

| 指标 | Stage 2.0 | Stage 2.1 | Stage 2.4 | 2.4 vs 2.0 |
|------|-----------|-----------|-----------|------------|
| 特征总数 | 74 | 76 | 73 | -1 |
| 平均测试AUC | 0.5929 | 0.5540 | 0.5424 | -0.0505 ❌ |
| AUC衰减率 | 37.5% | 41.5% | 42.9% | +5.4pp ❌ |

**关键发现**：
1. ❌ 移除冗余特征未提升AUC：零重要性≠无用，三个特征影响LightGBM训练路径
2. `weekly_ma200_distance` 排名提升 #7→#6（重要性 82.2→89.1）
3. V4特征仍主导：`halving_months_after`重要性 237.8→263.8
4. DIP_BUY场景AUC天花板：三次验证AUC在0.54-0.59区间，已接近特征工程天花板

**Stage 2.4 决策**：
- 不强制移除三个特征，保留但标记为ML冗余（`ml_redundant=True`）
- 在 `four_objective_feature_mapper.py` 中降权 1.0→0.1（已实施）
- **Stage 2 总结论**：DIP_BUY特征工程已到瓶颈，转向 Stage 2.5 特征交互工程或 Stage 3 BEAR_EXIT 优化

#### Stage 2.8 V5.3 周期相似性精选特征（2维，Walk-Forward双场景验证通过）

| 特征名 | 哲学贡献 | 来源类型 | 实践验证 | 整合状态 | TOP_EXIT WF排名 | DIP_BUY WF排名 |
|--------|---------|---------|---------|---------|----------------|---------------|
| `drawdown_vs_hist_avg` | 周期相似性精选 | 🔬实践回测 | ✅双场景提升 | ✅已集成 | #17 (重要性82.2) | #22 (重要性57.6) |
| `cycle_path_similarity` | 周期相似性精选 | 🔬实践回测 | ✅双场景提升 | ✅已集成 | #34 (重要性43.7) | #34 (重要性41.5) |

> **V5.3 验证结论**（2026-07-19，ADOPTED）：
> - 来源：V5.1周期相似性8特征 → 相关性分析 → 消融实验 → 精选2特征
> - 特征总数 76→78（哲学特征 24→26维）
> - TOP_EXIT场景WF验证：AUC 0.6833→0.7261（**+0.0428**），衰减率 31.7%→27.4%（**-4.3pp**）
> - DIP_BUY场景WF验证：AUC 0.6587→0.6871（**+0.0283**），衰减率 34.1%→31.3%（**-2.8pp**）
> - `drawdown_vs_hist_avg`：当前跌幅 - 历史同月数平均跌幅，仅在熊市阶段(phase==3.0)计算
> - `cycle_path_similarity`：周期路径相似度[0,1]，与drawdown_vs_hist_avg协同效果最佳
> - 关键发现：消融实验定位"害群之马"`fed_months_in_cycle`（重要性#1但对模型有害）
> - **决策**：✅ 正式集成到 FEATURE_NAMES，哲学特征从24维扩展到26维
>
> **验证脚本**：[v53_feature_correlation_analysis.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/v53_feature_correlation_analysis.py)、[v53_direction_d_validation.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/v53_direction_d_validation.py)、[v53_ablation_experiment.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/v53_ablation_experiment.py)、[v53_final_validation.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/v53_final_validation.py)
> **验证结果**：[v53_direction_d_result.json](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/backtest_results/v53_direction_d_result.json)、[v53_ablation_result.json](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/backtest_results/v53_ablation_result.json)、[v53_final_validation.json](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/backtest_results/v53_final_validation.json)

---

## 四、管道C：集成推理管道（62维）

**来源**：[algo_ensemble.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/algo_ensemble.py) `extract_ensemble_features`
**理论基础**：五大算法输出融合
**特征来源类型**：⚡算法输出 + 🔬实践回测（哲学26维）

### C1. 趋势一致性 tc（16维）— [algo_ensemble.py:129-149](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/algo_ensemble.py#L129-L149)

| 特征名 | 计算逻辑 | 来源类型 |
|--------|---------|---------|
| `tc_weekly_{confidence,reversal,bull,bear,speed,accel,static_dir}` | 周线趋势一致性（7维） | ⚡算法输出 |
| `tc_daily_{confidence,reversal,bull,bear,speed,accel,static_dir}` | 日线趋势一致性（7维） | ⚡算法输出 |
| `tc_consistent` | 周日一致性 | ⚡算法输出 |
| `tc_consistency_confidence` | 一致性置信度 | ⚡算法输出 |

### C2. 贝叶斯置信度 bayes（3维）— [algo_ensemble.py:151-155](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/algo_ensemble.py#L151-L155)

| 特征名 | 计算逻辑 | 来源类型 |
|--------|---------|---------|
| `bayes_confidence` | 贝叶斯置信度 | ⚡算法输出 |
| `bayes_bull_prob` | 上涨概率 | ⚡算法输出 |
| `bayes_bear_prob` | 下跌概率 | ⚡算法输出 |

### C3. 经典指标置信度 classic（9维）— [algo_ensemble.py:157-170](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/algo_ensemble.py#L157-L170)

| 特征名 | 计算逻辑 | 来源类型 |
|--------|---------|---------|
| `classic_s1_{confidence,bull,bear,dynamics_bonus}` | Screen1周线（4维） | ⚡算法输出 |
| `classic_s2_{confidence,bull,bear,dynamics_bonus}` | Screen2日线（4维） | ⚡算法输出 |
| `classic_overall_confidence` | 综合置信度 | ⚡算法输出 |
| `classic_trend_consistent` | 趋势一致性 | ⚡算法输出 |

### C4. 技术基本面融合 fusion（4维）— [algo_ensemble.py:172-177](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/algo_ensemble.py#L172-L177)

| 特征名 | 计算逻辑 | 来源类型 |
|--------|---------|---------|
| `fusion_tech_conf` | 技术面置信度 | ⚡算法输出 |
| `fusion_fund_conf` | 基本面置信度 | ⚡算法输出 |
| `fusion_consistent` | 技术基本面一致 | ⚡算法输出 |
| `fusion_conflict_level` | 冲突级别 | ⚡算法输出 |

### C5. 价值风险评估 vr（4维）— [algo_ensemble.py:179-187](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/algo_ensemble.py#L179-L187)

| 特征名 | 计算逻辑 | 来源类型 |
|--------|---------|---------|
| `vr_vol_ratio` | 波动率比率 | ⚡算法输出 |
| `vr_rr_ratio` | 风险收益比 | ⚡算法输出 |
| `vr_value_gt_risk` | 价值>风险 | ⚡算法输出 |
| `vr_tp_pct` | 止盈百分比 | ⚡算法输出 |

### C6. Freqtrade信号 ft（4维）— [algo_ensemble.py:189-196](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/algo_ensemble.py#L189-L196)

| 特征名 | 计算逻辑 | 来源类型 |
|--------|---------|---------|
| `ft_1h_signal` | 1小时信号方向 | ⚡算法输出 |
| `ft_1h_confidence` | 1小时置信度 | ⚡算法输出 |
| `ft_4h_signal` | 4小时信号方向 | ⚡算法输出 |
| `ft_4h_confidence` | 4小时置信度 | ⚡算法输出 |

### C7. 最终信号 fs（5维）— [algo_ensemble.py:198-207](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/algo_ensemble.py#L198-L207)

| 特征名 | 计算逻辑 | 来源类型 |
|--------|---------|---------|
| `fs_direction` | 最终方向 | ⚡算法输出 |
| `fs_confidence` | 最终置信度 | ⚡算法输出 |
| `fs_trend_consistent` | 趋势一致 | ⚡算法输出 |
| `fs_fusion_consistent` | 融合一致 | ⚡算法输出 |
| `fs_freqtrade_consistent` | Freqtrade一致 | ⚡算法输出 |

### C8. ⭐ 哲学贡献特征 ph（26维：V2十五个+V4七个+V5.3两个）— [algo_ensemble.py:209-225](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/algo_ensemble.py#L209-L225)

与管道B的B8完全一致，前缀改为`ph_`，通过`full_signal["philosophy"]`注入。
V4新增7个特征待整合到`algo_ensemble.py`的`extract_ensemble_features()`中。

---

## 五、特征来源类型统计

| 来源类型 | 标记 | 特征数 | 占比 | 说明 |
|---------|------|-------|------|------|
| ⚡理论驱动 | `theory` | ~85维 | ~73% | Elder三重滤网、最小阻力理论、技术指标 |
| ⚡算法输出 | `algo_output` | ~40维 | ~34% | 五大算法的结构化输出 |
| 🔬实践回测（V2） | `practice_backtest` | 15维 | ~13% | V2增强版MA200策略9年回测消融验证 |
| 🔬实践回测（V4） | `practice_backtest_v4` | 7维 | ~6% | V4减半周期逃顶策略9年回测验证（待整合） |

> 注：占比按管道B+C去重计算，有重叠（哲学特征在两个管道都有）
> V4新增7个特征当前在策略文件中，待整合到特征工程管线（详见 Stage 1 路线图）

---

## 六、实践回测优化方向（待挖掘）

以下方向可从实践回测中提取新特征，补充到现有管道：

### 6.1 已有理论特征的实践验证（优先级：高）

现有~85维理论特征中，哪些在9年回测中真正有效？可通过消融分析验证：

| 待验证特征组 | 验证方法 | 预期产出 |
|-------------|---------|---------|
| `ema_slope_{13,26,50,100}` | 逐个移除看回测影响 | 标记有效/冗余周期 |
| `bullish/bearish_divergence` | 对比有/无背离特征的策略收益 | 验证Elder-ray背离实战价值 |
| `vol_compression` | 波动率压缩后突破的回测收益 | 验证压缩信号有效性 |
| `counter_trend_accum_{10,20}` | 逆势累积信号触发后的收益 | 验证逆转预警准确性 |
| `power_balance` | 多空平衡极值后的走势 | 验证力量平衡预测力 |

### 6.2 从v2策略消融中提取新特征（优先级：高）

v2策略消融分析中发现但尚未提取为特征的实践规律：

| 实践发现 | 潜在特征 | 回测证据 |
|---------|---------|---------|
| 3/5成仓位优于5/7成 | `optimal_short_ratio` | 3/5成+457% vs 5/7成+398% |
| 斐波那契止盈在BTC效果不明显 | `fib_tp_effectiveness` | +457% vs +452%，仅+4.53pp |
| 抄底8%时间贡献主要收益 | `dip_buy_concentration` | 222天贡献+246pp |
| UNI双牛率仅16% | `alt_bull_scarcity` | UNI 89%时间空仓最优 |

### 6.3 跨币种实践特征（优先级：中）

现有特征都是单币种内部的，缺少跨币种相对强弱：

| 潜在特征 | 计算逻辑 | 实践依据 |
|---------|---------|---------|
| `btc_dominance_trend` | BTC市值占比变化趋势 | BTC强弱决定小币牛熊 |
| `alt_season_score` | 小币相对BTC超额收益 | 小币季节性轮动 |
| `cross_asset_correlation` | BTC与小币相关性变化 | 熊市相关性升高 |
| `btc_volatility_regime` | BTC波动率分位数 | 高波动=系统性行情 |

### 6.4 回测统计特征（优先级：中）

从历史回测统计中提取的特征，而非实时计算：

| 潜在特征 | 计算逻辑 | 实践依据 |
|---------|---------|---------|
| `historical_win_rate` | 同一信号历史胜率 | 9年回测统计 |
| `regime_conditional_return` | 当前regime下历史平均收益 | 牛/熊/震荡分regime统计 |
| `max_drawdown_in_regime` | 当前regime下历史最大回撤 | 风险控制 |
| `optimal_holding_period` | 同一信号最优持仓天数 | 9年回测优化 |

---

## 七、四类目的特征交叉分类（新增）

> 2026-07-18 新增：基于"四类目的 + 动态实践闭环"框架，
> 将所有特征按交易目的重新组织，形成"按来源（三管道）+ 按目的（四类）"双维度分类。
>
> 详见: [four_objective_framework_design.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/four_objective_framework_design.md)
> 映射器: [four_objective_feature_mapper.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/four_objective_feature_mapper.py)

### 7.1 四类目的定义

| 目的 | 中文名 | 场景 | 优化目标 |
|-----|-------|------|---------|
| **DIP_BUY** | 牛市抄底 | 价格接近/跌破周线MA200，底部区域 | 更早识别底部、更高收益风险比 |
| **TOP_EXIT** | 牛市离场 | 牛市末期/头部，趋势衰竭 | 更早在顶部离场、减少回吐 |
| **BEAR_SHORT** | 熊市做空 | 跌破MA200，下跌趋势确认 | 更准的做空入场点、更低假突破 |
| **BEAR_EXIT** | 熊市空平 | 熊市末期/底部，下跌衰竭 | 更早平空、避免反弹回吐 |

### 7.2 各目的核心特征（权重 ≥ 0.8）

以下特征对对应目的有高度相关性（理论分析 + 实践验证），
是各目的优化的重点特征组。

#### DIP_BUY（牛市抄底）核心特征

| 特征名 | 来源管道 | 权重 | 说明 |
|-------|---------|------|------|
| `weekly_ma200_distance` | 哲学特征 | 1.0 | 价格相对周线MA200的距离 — 抄底核心指标 |
| `dip_buy_level` | 哲学特征 | 1.0 | 已触发的抄底档位 |
| `dip_buy_position_ratio` | 哲学特征 | 1.0 | 抄底建议仓位比例 |
| `left_side_buy_signal` | 哲学特征 | 1.0 | 左侧抄底信号强度 |
| `bullish_divergence` | 价格特征 | 0.9 | 看涨背离强度 |
| `rsi_bull_divergence` | 价格特征 | 0.9 | RSI看涨背离 |
| `bear_exhaustion` | 价格特征 | 0.9 | 空头衰竭信号 |
| `btc_bull_confirmed` | 哲学特征 | 0.9 | BTC牛市确认 |
| `double_bull_score` | 哲学特征 | 0.9 | 双牛过滤得分 |
| `reversal_warning` | 价格特征 | 0.8 | 趋势逆转预警 |

#### TOP_EXIT（牛市离场）核心特征

| 特征名 | 来源管道 | 权重 | 说明 |
|-------|---------|------|------|
| `halving_months_after` | 哲学特征（V4新增） | 1.0 | 距减半月数 — 逃顶时间锚定核心 |
| `halving_phase` | 哲学特征（V4新增） | 1.0 | 减半阶段（warn/danger/peak） |
| `halving_position_cap` | 哲学特征（V4新增） | 1.0 | 减半周期仓位上限 |
| `ma128_distance_pct` | 哲学特征（V4新增） | 0.9 | 价格距MA128百分比 — 破位卖出 |
| `ma128_below_days` | 哲学特征（V4新增） | 0.9 | 连续低于MA128天数 |
| `ath_drawdown_pct` | 哲学特征（V4新增） | 0.9 | 距历史高点回撤 — 越高越卖 |
| `bounce_from_low_pct` | 哲学特征（V4新增） | 0.9 | 从近期低点反弹幅度 — 反弹卖出 |
| `bearish_divergence` | 价格特征 | 0.9 | 看跌背离强度 |
| `rsi_bear_divergence` | 价格特征 | 0.9 | RSI看跌背离 |
| `bull_exhaustion` | 价格特征 | 0.9 | 多头衰竭信号 |
| `macro_trend_slope` | 价格特征 | 0.8 | 周线级大趋势方向 |
| `bull_power_negative` | 价格特征 | 0.8 | Bull Power转负 |
| `tc_weekly_confidence` | 集成特征 | 0.8 | 周线趋势一致性置信度 |
| `tc_weekly_reversal` | 集成特征 | 0.8 | 周线逆转分数 |

#### BEAR_SHORT（熊市做空）核心特征

| 特征名 | 来源管道 | 权重 | 说明 |
|-------|---------|------|------|
| `btc_regime_label` | 哲学特征 | 0.9 | BTC牛熊状态标签 |
| `alt_short_risk_score` | 哲学特征 | 0.9 | 小币做空风险评分 |
| `bear_short_layer` | 哲学特征 | 1.0 | 做空档位 |
| `layered_position_target` | 哲学特征 | 0.9 | 分层仓位目标 |
| `weekly_composite_res` | 阻力特征 | 0.9 | 周线综合阻力 |
| `weekly_price_res` | 阻力特征 | 0.9 | 周线价格阻力 |
| `weekly_daily_align` | 阻力特征 | 0.9 | 周线日线一致性 |
| `multi_timeframe_score` | 阻力特征 | 0.9 | 多周期综合得分 |
| `ema_slope_100` | 价格特征 | 0.9 | EMA100斜率（大趋势方向） |
| `tc_weekly_bear` | 集成特征 | 0.9 | 周线空头方向 |
| `bayes_bear_prob` | 集成特征 | 0.8 | 贝叶斯空头概率 |

#### BEAR_EXIT（熊市空平）核心特征

| 特征名 | 来源管道 | 权重 | 说明 |
|-------|---------|------|------|
| `bear_exhaustion` | 价格特征 | 0.9 | 空头衰竭信号 |
| `left_side_buy_signal` | 哲学特征 | 0.9 | 左侧抄底信号（下跌终止信号） |
| `bullish_divergence` | 价格特征 | 0.8 | 看涨背离（下跌反转信号） |
| `rsi_bull_divergence` | 价格特征 | 0.8 | RSI看涨背离 |
| `fib_tp_remaining_ratio` | 哲学特征 | 1.0 | 斐波那契止盈剩余仓位 |
| `dip_buy_level` | 哲学特征 | 0.8 | 抄底档位（底部确认信号） |
| `reversal_warning` | 价格特征 | 0.8 | 趋势逆转预警 |

### 7.3 特征-目的映射表使用方法

完整映射（含所有119个特征对四个目的的权重）存储在：
`four_objective_feature_mapper.py` → `FEATURE_OBJECTIVE_MAP`

**典型用法**：

```python
from ml.four_objective_feature_mapper import FourObjectiveFeatureMapper

mapper = FourObjectiveFeatureMapper()

# 获取某目的的核心特征
core_dip_features = mapper.get_core_features("dip_buy")

# 获取某目的的所有相关特征（按权重降序）
all_dip_features = mapper.get_objective_features("dip_buy", threshold=0.5)

# 获取某个特征对四个目的的权重分布
divergence_weights = mapper.get_feature_objectives("bullish_divergence")

# 为某目的生成标签（ground truth）
labels = mapper.generate_labels(prices_df, "dip_buy")
```

### 7.4 分场景验证与闭环迭代

特征优化必须通过"分场景回测"验证，形成闭环：

```
理论假设 → 特征设计 → 分场景回测 → 对比基线 → 采纳/回退 → 反馈理论
```

相关工具：
- **分场景回测引擎**: [scenario_backtest_engine.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/scenario_backtest_engine.py)
  - 四类目的分别评估
  - 特征消融实验
  - 综合评分（vs v2基线）
- **闭环迭代管理器**: [closed_loop_manager.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/closed_loop_manager.py)
  - 假设库管理
  - 实验记录
  - 基线版本管理
  - 知识库积累

**关键原则**：
- 每类目的单独优化，不被全周期平均掩盖
- 新增特征必须做消融实验，证明增量贡献
- 所有改进必须和V4基线对比，综合评分 > 1.0才可采纳
- 不行就回退，保留记录用于学习
- V4基线：HalvingTopExitStrategy（综合评分1.592，夏普0.900，回撤53.46%）
