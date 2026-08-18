# 新工程算法实践路线图 — V4基线后时代

> **版本**: v1.0 | **创建日期**: 2026-07-18
> **基线**: V4减半周期逃顶（HalvingTopExitStrategy，综合评分1.592）
> **定位**: V4基线确认后的可执行工程路线图，聚焦"做什么、怎么做、如何验证"
> **关系**: 本文是 [four_objective_framework_design.md](four_objective_framework_design.md) 的工程执行版
> **原则**: 每一步都必须通过V4基线对比验证，不优则回退

---

## 0. 路线图总览

### 0.1 当前状态

```
┌─────────────────────────────────────────────────────────────┐
│                    V4基线后时代工程状态                       │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ✅ 已完成                                                    │
│  ├─ V2基线（牛熊经验法则，评分1.000）                         │
│  ├─ V3做空优化（移除L1做空，评分1.098）                       │
│  ├─ V4减半周期逃顶（四重逃顶，评分1.592）← 当前基线           │
│  ├─ 四类目的框架搭建（DIP_BUY/TOP_EXIT/BEAR_SHORT/BEAR_EXIT）│
│  ├─ 22个哲学特征（V2十五个 + V4七个）                        │
│  └─ 闭环管理器（closed_loop_manager.py）                     │
│                                                               │
│  ⏳ 进行中                                                    │
│  ├─ DIP_BUY抄底优化（布林带+头肩底已测试，边际效益小）        │
│  └─ V4特征→ML整合（7个新特征待整合到LightGBM）               │
│                                                               │
│  ❌ 待启动                                                    │
│  ├─ BEAR_EXIT空平优化（底背离+量能萎缩）                      │
│  ├─ 四类目的集成融合（状态机整合）                            │
│  └─ 实盘验证（纸交易→实盘）                                   │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### 0.2 五阶段路线图

```
Stage 1 ──→ Stage 2 ──→ Stage 3 ──→ Stage 4 ──→ Stage 5
特征整合     抄底优化     空平优化     集成融合     实盘验证
(2-3周)      (2-3周)      (2-3周)      (3-4周)      (持续)

  │            │            │            │            │
  ▼            ▼            ▼            ▼            ▼
V4.1         V4.2         V4.3         V5候选       实盘部署
特征验证      抄底增强      空平增强      状态机       持续迭代
```

### 0.3 核心约束

```
┌─────────────────────────────────────────────────────────────┐
│  工程实践铁律（V4基线后时代）                                 │
│                                                               │
│  1. 每个Stage结束必须通过V4基线综合评分对比（score > 1.0）    │
│  2. 每个新特征/新参数必须有理论假设驱动，禁止瞎试             │
│  3. 每次优化必须记录：假设→实现→回测→结论→下一步              │
│  4. 样本外表现不得显著劣于样本内（过拟合检测）                │
│  5. 减半周期覆盖验证：至少2020+2024两个减半周期               │
│  6. 回退是正常操作，不是失败 — 保留探索记录                   │
└─────────────────────────────────────────────────────────────┘
```

---

## Stage 1：V4特征工程整合（V4.1）

> **目标**：将V4的7个新哲学特征整合到LightGBM特征工程管线，验证ML能否学习V4的时间维度决策
> **预期版本**：V4.1（特征验证版）
> **成功标准**：ML模型在TOP_EXIT场景下的特征重要性中，V4特征排名前30%

### 1.1 任务清单

| # | 任务 | 产出 | 验证方式 |
|---|------|------|---------|
| 1.1 | 扩展 `philosophy_feature_engineer.py` | 新增7个V4特征计算函数 | 单元测试通过 |
| 1.2 | 减半周期特征计算 | `halving_months_after`, `halving_phase`, `halving_position_cap` | 与策略文件结果一致 |
| 1.3 | MA128特征计算 | `ma128_distance_pct`, `ma128_below_days` | 数值合理性校验 |
| 1.4 | 顶部特征计算 | `ath_drawdown_pct`, `bounce_from_low_pct` | 数值合理性校验 |
| 1.5 | LightGBM训练验证 | 包含22个特征的新模型 | Walk-Forward回测 |
| 1.6 | 特征重要性分析 | SHAP值/特征重要性排名 | V4特征在TOP_EXIT场景排名前30% |
| 1.7 | 基线对比回测 | V4.1 vs V4 综合评分 | score ≥ 1.0（不劣于V4） |

### 1.2 V4特征整合技术方案

```python
# philosophy_feature_engineer.py 扩展结构

class PhilosophyFeatureEngineer:
    # V2原有15个特征（已实现）
    # ...

    # === V4新增7个特征 ===

    def _calc_halving_features(self, current_date, df):
        """减半周期三特征（V4哲学贡献5）"""
        # 1. halving_months_after: 距上次减半的月数
        # 2. halving_phase: normal/warn/danger/peak
        # 3. halving_position_cap: 仓位上限 0.0-1.0
        ...

    def _calc_ma128_features(self, df):
        """MA128破位两特征（V4哲学贡献6）"""
        # 4. ma128_distance_pct: 价格距MA128百分比
        # 5. ma128_below_days: 连续低于MA128天数
        ...

    def _calc_top_exit_features(self, df):
        """越高越卖两特征（V4哲学贡献7）"""
        # 6. ath_drawdown_pct: 距历史高点回撤
        # 7. bounce_from_low_pct: 从近期低点反弹幅度
        ...
```

### 1.3 验证矩阵

| 验证维度 | 通过标准 | 阻塞条件 |
|---------|---------|---------|
| 特征计算正确性 | 与策略文件结果偏差 < 0.1% | 阻塞，必须修复 |
| 特征重要性 | V4特征在TOP_EXIT场景排名前30% | 不阻塞，但需分析原因 |
| 综合评分 | V4.1 score ≥ 1.0（相对V4） | 阻塞，回退到V4 |
| 过拟合检测 | 样本内外差异 < 20% | 阻塞，需调整特征 |
| 减半周期覆盖 | 2020+2024减半周期均验证 | 阻塞，补充数据 |

---

## Stage 2：DIP_BUY抄底优化（V4.2）

> **目标**：优化抄底时机，提升抄底阶段收益风险比
> **预期版本**：V4.2（抄底增强版）
> **成功标准**：抄底阶段收益提升 ≥ 10% 或 假阳性率降低 ≥ 20%

### 2.0 Walk-Forward 验证基线（2026-07-19）

> 验证脚本：[stage2_dip_buy_validation.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/stage2_dip_buy_validation.py)
> 验证结果：[stage2_dip_buy_result.json](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/backtest_results/stage2_dip_buy_result.json)

**DIP_BUY 场景特征重要性 Walk-Forward 验证**（12折，730天训练/180天测试）：

| 指标 | 值 | 评估 |
|------|-----|------|
| 平均测试AUC | 0.5929 | 一般（0.55-0.65） |
| AUC衰减率 | 37.5% | 中等过拟合风险 |
| DIP_BUY正样本率 | 22.6% | 合理 |

**V2 抄底特征排名**：

| 特征 | 排名 | 重要性 | 评估 |
|------|------|--------|------|
| `weekly_ma200_distance` | #7 | 92.5 | ✅ 有效，Top 10% |
| `dip_buy_level` | #71 | 0.0 | ❌ 冗余（离散化丢失信息） |
| `dip_buy_position_ratio` | #43 | 3.7 | ❌ 冗余（从weekly_ma200_distance派生） |
| `left_side_buy_signal` | #72 | 0.0 | ❌ 冗余（从dip_buy_position_ratio派生） |

**关键发现**：
1. `weekly_ma200_distance` 是唯一有效的V2抄底特征，LightGBM偏好连续值而非离散档位
2. `dip_buy_level`/`dip_buy_position_ratio`/`left_side_buy_signal` 三个派生特征信息冗余
3. V4特征在DIP_BUY场景反而表现更好（平均排名16.3 vs V2抄底48.2），`halving_months_after`排名#1
4. 抄底特征需要增强：引入RSI、成交量等非派生特征

### 2.1 Stage 2.1 假设DIP-001验证（RSI + 成交量，2026-07-19）

> 验证脚本：[stage2_dip_buy_validation.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/stage2_dip_buy_validation.py)
> 验证结果：[stage2_dip_buy_result.json](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/backtest_results/stage2_dip_buy_result.json)

**假设DIP-001**：周线MA200附近 + 日线RSI<30 + 成交量放大 = 高质量抄底点

**新增特征**：`rsi_14`（14日RSI，Wilder平滑法）、`volume_ratio_20d`（当日量/20日均量）
**特征总数**：74 → 76（新增2维哲学8特征）

**Stage 2.1 vs Stage 2.0 对比**：

| 指标 | Stage 2.0 | Stage 2.1 | 变化 | 评估 |
|------|-----------|-----------|------|------|
| 平均测试AUC | 0.5929 | 0.5540 | -0.0389 | ❌ AUC下降 |
| AUC衰减率 | 37.5% | 41.5% | +4.0pp | ❌ 过拟合加剧 |
| 特征总数 | 74 | 76 | +2 | 新增2维 |

**DIP-001 新增特征排名**：

| 特征 | 排名 | 重要性 | Top30%阈值(<=22) | 评估 |
|------|------|--------|------------------|------|
| `rsi_14` | #30 | 8.9 | NO | ❌ 未进Top30% |
| `volume_ratio_20d` | #45 | 2.6 | NO | ❌ 未进Top30% |

**Top 10 特征重要性**（Stage 2.1）：

| 排名 | 特征 | 重要性 | 类别 |
|------|------|--------|------|
| #1 | `halving_months_after` | 237.8 | V4新 |
| #2 | `ma128_distance_pct` | 138.5 | V4新 |
| #3 | `macro_trend_slope` | 124.9 | 趋势 |
| #4 | `vol_compression` | 109.9 | 趋势 |
| #5 | `ma128_below_days` | 106.7 | V4新 |
| #6 | `ath_drawdown_pct` | 102.0 | V4新 |
| #7 | `weekly_ma200_distance` | 82.2 | V2抄底 |
| #8 | `volume_trend_20` | 49.7 | 趋势 |
| #9 | `counter_trend_accum_20` | 42.6 | 趋势 |
| #10 | `price_acceleration_20` | 37.9 | 趋势 |

**四类哲学特征对比**：

| 类别 | 平均排名 | 进入Top30% | 占比 |
|------|----------|------------|------|
| V4新 | 18.1 | 4/7 | 57.1% ✅ |
| DIP001新 | 37.5 | 0/2 | 0.0% ❌ |
| 趋势特征 | 37.2 | — | — |
| V2其他 | 52.6 | 2/11 | 18.2% |
| V2抄底 | 53.0 | 1/4 | 25.0% |

**关键发现**：
1. ❌ **假设DIP-001被拒绝**：RSI和volume_ratio未提升模型预测力，反而导致AUC下降0.0389
2. **过拟合加剧**：衰减率从37.5%升至41.5%，新增特征增加了噪声
3. **V4特征仍主导DIP_BUY场景**：`halving_months_after`排名#1（重要性237.8），V4特征4/7进入Top30%
4. **`weekly_ma200_distance`仍是唯一有效的V2抄底特征**（#7, 82.2）
5. **RSI/volume_ratio的低效原因分析**：
   - RSI作为单独特征在DIP_BUY场景信息量不足，树模型已从价格特征中隐式学到类似信号
   - volume_ratio在加密市场波动剧烈，放量同时出现在顶部和底部，方向性弱
   - 标签定义"未来20日涨幅>15%且回撤<10%"对量价确认不敏感

**Stage 2.1 结论与决策**：
- 🔴 **DIP-001假设标记为REJECTED**
- 🟡 **保留rsi_14和volume_ratio_20d特征代码**（标记practice_validated=False），但不作为DIP_BUY核心特征
- 🟢 **确认V4特征的跨场景强预测力**：halving_months_after/ma128_distance_pct在TOP_EXIT和DIP_BUY场景均排名前列
- 📌 **下一步方向调整**：
  - 放弃"引入传统技术指标增强抄底"路径（RSI/MACD等已被趋势特征隐式覆盖）
  - 转向"特征交互工程"：构建`weekly_ma200_distance × halving_months_after`等交互特征
  - 或直接进入Stage 2.4清理冗余派生特征（dip_buy_level等）

### 2.2 已探索方向与结论

| 方向 | 测试结果 | 结论 |
|------|---------|------|
| 布林带+头肩底（v3.2-v3.5） | 边际效益小 | V2的"越跌越买"已足够有效 |
| 布林带网格加仓 | 略优于V2但复杂度高 | 暂不采纳，保留探索 |
| 双底检测优化 | 有改进空间 | 保留探索 |
| V2抄底特征WF验证 | 1/4有效 | weekly_ma200_distance有效，派生特征冗余 |
| RSI+成交量（DIP-001） | AUC-0.0389，过拟合+4pp | ❌ 假设被拒绝，传统技术指标无增益 |

### 2.3 本阶段任务清单

| # | 任务 | 产出 | 验证方式 | 状态 |
|---|------|------|---------|------|
| 2.0 | V2抄底特征WF基线验证 | stage2_dip_buy_validation.py | AUC+特征排名 | ✅完成 |
| 2.1 | 引入RSI+成交量特征 | 新增rsi_14, volume_ratio_20d | WF验证AUC提升 | ✅完成(假设被拒绝) |
| 2.2 | 量价确认信号 | 成交量+换手率底部特征 | 与纯价格特征对比 | ⏸暂停(DIP-001已拒绝) |
| 2.3 | 多时间框架共振 | 周线+日线+4H底部共振检测 | 共振信号胜率 > 60% | ⏳待做 |
| 2.4 | 清理冗余派生特征 | dip_buy_level等降权或移除 | 特征重要性验证 | ✅完成(见2.5节) |
| 2.5 | 特征交互工程 | ma200×halving等交互特征 | WF验证AUC提升 | ⏳待做(新方向) |
| 2.6 | V4.2基线对比 | V4.2 vs V4 综合评分 | score > 1.0 | ⏳待做 |

### 2.5 Stage 2.4 清理冗余派生特征验证（2026-07-19）

> 验证脚本：[stage2_4_cleanup_validation.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/stage2_4_cleanup_validation.py)
> 验证结果：[stage2_4_cleanup_result.json](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/backtest_results/stage2_4_cleanup_result.json)

**操作内容**：移除3个零重要性派生特征（`dip_buy_level`/`dip_buy_position_ratio`/`left_side_buy_signal`），特征总数 76→73

**Stage 2.4 vs Stage 2.0/2.1 对比**：

| 指标 | Stage 2.0 | Stage 2.1 | Stage 2.4 | 2.4 vs 2.0 |
|------|-----------|-----------|-----------|------------|
| 特征总数 | 74 | 76 | 73 | -1 |
| 平均测试AUC | 0.5929 | 0.5540 | 0.5424 | -0.0505 ❌ |
| AUC衰减率 | 37.5% | 41.5% | 42.9% | +5.4pp ❌ |

**清理后 Top 10 特征**：

| 排名 | 特征 | 重要性 | 类别 | vs Stage 2.1 |
|------|------|--------|------|--------------|
| #1 | `halving_months_after` | 263.8 | V4新 | ↑(237.8→263.8) |
| #2 | `vol_compression` | 142.2 | 趋势 | ↑(#4→#2) |
| #3 | `ma128_distance_pct` | 122.4 | V4新 | ↓(#2→#3) |
| #4 | `macro_trend_slope` | 122.4 | 趋势 | ↓(#3→#4) |
| #5 | `ath_drawdown_pct` | 104.1 | V4新 | ↓(#6→#5) |
| #6 | `weekly_ma200_distance` | 89.1 | V2抄底 | ↑(#7→#6) |
| #7 | `ma128_below_days` | 57.2 | V4新 | ↓(#5→#7) |

**关键发现**：
1. ❌ **移除冗余特征未提升AUC**：AUC下降0.0505，衰减率加剧5.4pp
2. **零重要性≠无用**：三个特征虽 gain importance=0，但影响了 LightGBM 的训练路径（feature_fraction/bagging 随机选择）
3. **`weekly_ma200_distance` 排名提升**：#7→#6，重要性 82.2→89.1（冗余特征移除后，信息更集中）
4. **V4特征仍主导**：4/7进入Top10，`halving_months_after`重要性提升（237.8→263.8）
5. **DIP_BUY场景AUC天花板**：三次验证AUC在0.54-0.59区间，均属"一般"水平，可能已接近特征工程天花板

**Stage 2.4 结论与决策**：
- 🔴 **不强制移除三个特征**：移除后AUC下降，保留特征但标记为ML冗余
- 🟡 **降权处理**：在 `four_objective_feature_mapper.py` 中将权重从1.0降至0.1（已实施）
- 🟡 **元信息标记**：在 `philosophy_feature_engineer.py` 的 FEATURE_METADATA 中添加 `ml_redundant=True` 标记（已实施）
- 📌 **Stage 2 总结论**：
  - DIP_BUY场景的V2抄底特征工程已到瓶颈，`weekly_ma200_distance`是唯一有效特征
  - 传统技术指标（RSI/volume_ratio）无增益
  - 冗余特征移除无增益
  - V4特征（halving/ma128/ath）在DIP_BUY场景有跨场景强预测力
  - **下一步应转向 Stage 2.5 特征交互工程或 Stage 3 BEAR_EXIT 优化**

### 2.4 理论假设库（抄底方向）

```
假设DIP-001: 周线MA200附近 + 日线RSI<30 + 成交量放大 = 高质量抄底点
  状态: REJECTED (2026-07-19)
  WF验证: RSI排名#30(重要性8.9)，volume_ratio排名#45(重要性2.6)，均未进Top30%
  AUC变化: 0.5929 → 0.5540 (-0.0389)，过拟合加剧4.0pp
  结论: 传统技术指标在DIP_BUY场景无增益，已被趋势特征隐式覆盖

假设DIP-002: 头肩底右肩形成时 + 4H出现底背离 = 抄底确认信号
  状态: untested

假设DIP-003: 多时间框架（周线+日线+4H）同时超卖 = 极端底部区域
  状态: untested

假设DIP-004: BTC减半前12个月的抄底收益 > 减半后24个月的抄底收益
  状态: testing
  WF验证: halving_months_after在DIP_BUY排名#1(重要性237.8)，减半周期对抄底有强预测力

假设DIP-005（新）: weekly_ma200_distance × halving_months_after 交互特征 > 单独特征
  状态: untested
  理论依据: V4特征主导DIP_BUY场景，与V2抄底特征可能存在交互效应
```

### 2.6 V5.1 周期相似性特征探索（2026-07-18，已回退 ❌）

> 验证脚本：[v51_cycle_similarity_validation.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/v51_cycle_similarity_validation.py)
> 消融实验：[v51_ablation_experiment.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/v51_ablation_experiment.py)
> 验证结果：[v51_cycle_similarity_result.json](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/backtest_results/v51_cycle_similarity_result.json)

**探索假设**：基于BTC 4年牛熊周期（减半后18月见顶 + 顶后12.5月见底 + 历史平均跌幅82.3%），构建周期相似性特征预测趋势。

**历史周期统计**（3轮完整周期）：

| 周期 | 减半→顶 | 顶→底 | 跌幅 | 顶→底月度跌幅路径 |
|------|---------|-------|------|------------------|
| 周期1 | 12.2月 | 13.3月 | -85.1% | -32% → -67% → -85% |
| 周期2 | 17.3月 | 11.9月 | -84.1% | -52% → -67% → -84% |
| 周期3 | 18.0月 | 12.4月 | -77.5% | -15% → -55% → -78% |
| **平均** | **15.8月** | **12.5月** | **-82.3%** | -24% → -52% → -80% |

**设计8个特征**：
- V5（4维）：cycle_phase, drawdown_from_cycle_peak, months_since_cycle_peak, bear_phase_progress
- V5.1（4维）：drawdown_vs_hist_avg, cycle_path_similarity, vol_regime_ratio, bear_severity_score

**Walk-Forward 验证结果**（TOP_EXIT场景，12折）：

| 实验 | 特征数 | 测试AUC | vs V4基线 | 衰减率 |
|------|--------|---------|----------|--------|
| **V4基线** | 74 | **0.7087** | 基准 | 29.1% |
| V5.1全部 | 84 | 0.6559 | -0.0527 ❌ | 34.4% |
| V5.1核心3特征 | 79 | 0.6048 | -0.1039 ❌ | 39.5% |

**特征重要性表现**（矛盾现象）：
- `vol_regime_ratio` 排名#1（重要性238.7）
- `months_since_cycle_peak` 排名#2（重要性183.3）
- `drawdown_vs_hist_avg` 排名#4（重要性178.5）
- 3个核心特征排名极高，但模型AUC反而下降

**回退根因分析**：
1. **历史样本不足**：仅3轮完整周期（2012/2016/2020），统计规律不稳定
2. **周期变形风险**：第4周期（2024减半）已偏离历史，ETF引入、机构化等结构性变化使历史规律失效
3. **特征间共线性**：`months_since_cycle_peak`与V4的`halving_months_after`高度相关，LightGBM选择其一导致信息冗余
4. **过拟合加剧**：衰减率从29.1%上升到39.5%，新增特征引入噪音

**决策**：❌ 回退V5.1特征
- FEATURE_NAMES 恢复为24维
- 计算代码保留在 philosophy_feature_engineer.py 中作为探索记录（注释状态）
- 验证脚本保留供后续参考

**经验教训**：
1. 特征重要性高 ≠ 模型预测能力强（需看整体AUC而非单特征排名）
2. 基于有限历史样本（3轮周期）的统计特征风险极高
3. 加密市场结构变化快，历史周期规律可能失效
4. 消融实验中"低效"特征移除后AUC进一步下降，说明特征间存在复杂依赖

### 2.7 V5.2 美联储利率周期特征探索（2026-07-18，已回退 ❌）

> 验证脚本：[v52_fed_rate_validation.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/v52_fed_rate_validation.py)
> 消融实验：[v52_ablation_experiment.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/v52_ablation_experiment.py)
> 验证结果：[v52_fed_rate_result.json](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/backtest_results/v52_fed_rate_result.json)

**探索假设**：基于美联储加息/降息周期构建宏观流动性特征：
- 美联储降息 + BTC低位 → all in 抄底信号
- 美联储加息 + V4见顶 → 开空加大信号

**美联储历史周期**（2015-2026，7个阶段）：

| 周期阶段 | 时间区间 | 利率变化 |
|---------|---------|---------|
| 加息周期1 | 2015-12-16 ~ 2018-12-19 | 0.25%→2.50% |
| 高利率平台1 | 2018-12-19 ~ 2019-07-31 | 2.50% |
| 降息周期1 | 2019-07-31 ~ 2020-03-15 | 2.50%→0.25% |
| 零利率平台 | 2020-03-15 ~ 2022-03-16 | 0.25% |
| 加息周期2 | 2022-03-16 ~ 2023-07-26 | 0.50%→5.50% |
| 高利率平台2 | 2023-07-26 ~ 2024-09-18 | 5.50% |
| 降息周期2 | 2024-09-18 ~ 至今 | 5.50%→3.00% |

**设计5个特征**：
- `fed_rate_action`: 当前动作(-1降息/0持平/+1加息)
- `fed_months_in_cycle`: 当前方向持续月数
- `fed_rate_level`: 当前利率上限(%)
- `fed_easing_btc_dip`: 降息+BTC低位组合信号[0,1]
- `fed_hawkish_top`: 加息+V4见顶组合信号[0,1]

**Walk-Forward 验证结果**：

| 场景 | V4基线(74维) | V5.2全部(79维) | V5.2核心2(76维) |
|------|-------------|---------------|----------------|
| TOP_EXIT AUC | 0.6833 | 0.6811 (-0.0022) | 0.6488 (-0.0345) |
| DIP_BUY AUC | 0.6270 | 0.6114 (-0.0156) | 0.5863 (-0.0407) |

**特征重要性表现**（矛盾现象，与V5.1相同）：
- `fed_months_in_cycle` 在两个场景均排名#1（重要性403.7/354.9）
- `fed_easing_btc_dip` 在DIP_BUY场景排名#24（重要性63.3）
- 核心特征排名极高，但模型整体AUC反而下降

**回退根因分析**：
1. **特征冗余**：`fed_months_in_cycle` 与 V4的 `halving_months_after` 高度相关（都编码时间维度），美联储周期和BTC减半周期在时间上重叠
2. **信号稀疏**：`fed_hawkish_top` 非零占比仅2.2%（加息+V4见顶窗口重叠时间少），无法提供有效训练信号
3. **特征间复杂依赖**：消融实验移除"低效"特征后AUC进一步下降，与V5.1结论一致
4. **宏观特征局限**：仅有2-3个完整美联储周期样本，统计规律不稳定

**决策**：❌ 回退V5.2特征
- FEATURE_NAMES 恢复为24维
- 计算代码保留在 philosophy_feature_engineer.py 中作为探索记录（注释状态）

**经验教训**（V5.1+V5.2累计）：
1. 宏观周期特征（BTC减半/美联储利率）与V4的 `halving_months_after` 存在严重信息冗余
2. 特征重要性排名#1不等于模型提升，需以AUC为最终判据
3. 消融实验中"低效"特征移除后AUC进一步下降的模式在V5.1和V5.2中重复出现
4. 未来宏观特征探索应避免时间维度编码，聚焦于V4未覆盖的独立信号（如资金费率、链上数据等）

---

### 2.6 Stage 2.6 V5.1周期相似性特征探索（2026-07-19）

> **假设**: BTC 4年周期的顶→底月度跌幅路径具有相似性，可用于趋势预测

**特征设计**（8维）：
- `cycle_phase`: 周期阶段（0=累积/1=牛市/2=见顶预警/3=熊市）
- `drawdown_from_cycle_peak`: 距周期内滚动高点回撤%
- `months_since_cycle_peak`: 距周期内已实现高点月数
- `bear_phase_progress`: 熊市进度[0,1]
- `drawdown_vs_hist_avg`: 当前跌幅 - 历史同月数平均跌幅（独立信息76.4%）
- `cycle_path_similarity`: 周期路径相似度[0,1]
- `vol_regime_ratio`: 量能周期位置（独立信息83.7%）
- `bear_severity_score`: 熊市严重度

**验证结果**：
- TOP_EXIT AUC: 0.7087 → 0.6559（-0.0527 ❌）
- 消融实验发现核心3特征排名极高但AUC仍下降
- 根因：历史样本不足（仅3轮周期）、周期变形风险、特征共线性

**决策**：❌ 回退，FEATURE_NAMES恢复为24维

---

### 2.7 Stage 2.7 V5.2美联储利率周期特征探索（2026-07-19）

> **假设**: 美联储降息+BTC低位=all in抄底；加息+V4见顶=开空加大

**特征设计**（5维）：
- `fed_rate_action`: 当前利率方向（-1=降息/0=持平/+1=加息）
- `fed_months_in_cycle`: 当前方向持续月数
- `fed_rate_level`: 当前目标利率上限%
- `fed_easing_btc_dip`: 降息+BTC低位组合信号
- `fed_hawkish_top`: 加息+V4见顶组合信号

**验证结果**：
- TOP_EXIT AUC: 0.6833 → 0.6811（-0.0022 ❌）
- DIP_BUY AUC: 0.6270 → 0.6114（-0.0156 ❌）
- 消融实验：`fed_months_in_cycle`排名#1但AUC进一步下降
- 根因：与`halving_months_after`高度冗余、信号稀疏、宏观特征样本不足

**决策**：❌ 回退

---

### 2.8 Stage 2.8 V5.3方向D：精选独立特征 + 交互特征（2026-07-19）

> **假设**: 通过相关性分析精选高独立信息特征 + 构建非线性交互特征，可突破V5.1/V5.2的瓶颈

**分析阶段**：特征相关性深度分析（`v53_feature_correlation_analysis.py`）
- 3个V5.1特征（`cycle_phase`/`drawdown_from_cycle_peak`/`months_since_cycle_peak`）与V4特征独立信息≈0%，完全冗余
- 4个V5特征保留>56%独立信息：`vol_regime_ratio`(83.7%)、`fed_rate_level`(81.4%)、`drawdown_vs_hist_avg`(76.4%)、`fed_rate_action`(56.1%)
- VIF分析：11/21特征VIF>5，严重多重共线性

**方向D初版**（5精选 + 3交互 = 8特征）：
- 验证结果：TOP_EXIT -0.0398 ❌, DIP_BUY -0.0049 ❌
- 与V5.1/V5.2相同模式：特征重要性高但AUC下降

**消融实验**（`v53_ablation_experiment.py`）— 突破性发现：
1. 逐个单独添加测试发现`fed_months_in_cycle`是"害群之马"（单独添加即AUC下降）
2. 移除`fed_months_in_cycle`后，`drawdown_vs_hist_avg`单独添加即双场景提升（TOP +0.0276, DIP +0.0241）
3. `drawdown_vs_hist_avg + cycle_path_similarity`组合效果最佳

**最终验证**（`v53_final_validation.py`）— 11个候选组合全部双场景提升：

| 组合 | TOP_EXIT Δ | DIP_BUY Δ | 综合得分 |
|------|-----------|----------|---------|
| drawdown + cycle_path_sim | +0.0428 | +0.0283 | +0.0356 |
| fed_level + drawdown + ma200_inter | +0.0239 | +0.0454 | +0.0347 |
| fed_rate_level + drawdown_vs_hist | +0.0458 | +0.0180 | +0.0319 |

**正式集成**：
- FEATURE_NAMES从24维扩展到26维
- 新增哲学9: `drawdown_vs_hist_avg` + `cycle_path_similarity`
- 修复了`extract_series`与验证脚本的计算逻辑差异（计算条件、相似度公式）
- 集成后Walk-Forward验证确认AUC提升保持：TOP_EXIT +0.0428 ✅, DIP_BUY +0.0283 ✅
- 过拟合降低：TOP_EXIT衰减率从31.7%降至27.4%

**关键经验教训**：
1. **消融实验是定位"害群之马"的关键**：`fed_months_in_cycle`虽重要性#1但对模型有害，逐个测试才能发现
2. **计算逻辑一致性至关重要**：验证脚本和正式集成的特征计算逻辑必须完全一致，否则结果不可复现
3. **少量精选特征 > 大量冗余特征**：2个精选特征（26维）优于8个特征（32维），印证"少即是多"
4. **周期相似性的价值在于"偏离度"而非"时间编码"**：`drawdown_vs_hist_avg`（当前跌幅与历史均值的偏离）提供了V4未覆盖的独立信号

---

### 2.9 Stage 2.9 V5.4 方向4：美联储利率精选特征集成（2026-07-19）

> **假设**: `fed_rate_level`（利率绝对水平）作为慢变量状态特征，独立信息81.4%，可提供V4+V5.3未覆盖的宏观流动性维度

**验证**（`v54_direction4_validation.py`）：
- 在V5.3基线上添加`fed_rate_level`：TOP_EXIT +0.0006 ✅, DIP_BUY +0.0058 ✅
- 过拟合不增反降：TOP decay 27.4%→27.3%，DIP decay 31.3%→30.7%
- 消融发现：`fed_rate_action`虽能提升DIP但拉低TOP，`rate_change_6m/12m`全部有害

**决策**：✅ 正式集成，FEATURE_NAMES 26→27维，新增哲学10: 美联储利率水平

---

### 2.10 Stage 2.10 V5.5 方向1/2/3 美联储特征深度探索（2026-07-19）

> **假设**: 在V5.4基础上，分别从利率状态、交互特征、周期阶段三个方向深度挖掘美联储衍生特征

**三方向探索**（`v55_direction123_validation.py`）：

| 方向 | 特征类型 | 结果 | 最佳特征 |
|------|---------|------|---------|
| 方向1 | 利率状态（zscore/change_6m/freq） | ❌ 全部失败 | 无 |
| 方向2 | 利率×价格交互（8个候选） | ✅ 1个突出 | `fed_level_x_cycle_sim` (TOP +0.0166) |
| 方向3 | 周期阶段分类（phase/progress/is_easing） | ✅ 3个有效 | `rate_cycle_phase` (DIP +0.0118) |

**消融实验**：
- `fed_level_x_cycle_sim` + 方向3特征存在冲突，叠加后AUC下降
- `fed_level_x_cycle_sim` 单独添加效果最佳：TOP +0.0166, DIP +0.0006, TOP decay降至25.7%

**正式集成**：
- FEATURE_NAMES 27→28维，新增哲学11: 利率×周期交互
- V5.5最终Walk-Forward：TOP_EXIT 0.7433, DIP_BUY 0.6935

**关键经验教训**：
1. **利率×周期相似度交互有效，利率×价格直接交互有害**：`fed_level×cycle_sim`成功，但`fed_level×ath_dd`严重有害
2. **阶段分类优于进度编码**：`rate_cycle_phase`（分类）有效，`rate_cycle_progress`（连续进度）严重有害（TOP -0.0873）
3. **消融冲突揭示特征耦合**：单独有效的特征组合后可能冲突，必须做叠加消融验证
4. **宏观流动性对周期路径有调制效应**：利率水平×周期相似度交互捕捉了"宏观流动性如何影响周期路径"的非线性关系

---

## Stage 3：BEAR_EXIT空平优化（V4.3）

> **目标**：优化做空平仓时机，减少空单利润回吐
> **预期版本**：V4.3（空平增强版）
> **成功标准**：做空阶段利润回吐减少 ≥ 30%

### 3.1 当前空平逻辑

V3/V4的空平逻辑：斐波那契止盈（23.6%/38.2%/50%/61.8%四档减仓）

**问题**：
- 止盈档位固定，不适应不同下跌速度
- 缺乏底部背离检测，可能在底部前过早平仓
- 无量能萎缩确认，可能误判反弹

### 3.2 本阶段任务清单

| # | 任务 | 产出 | 验证方式 |
|---|------|------|---------|
| 3.1 | 底背离检测 | `bear_divergence_detector.py` | 背离信号准确率 > 65% |
| 3.2 | 量能萎缩确认 | 成交量萎缩特征 | 萎缩+背离组合胜率 > 70% |
| 3.3 | 动态止盈档位 | 根据下跌速度调整斐波那契档位 | 回测验证 |
| 3.4 | 反弹强度评估 | 反弹幅度+持续时间特征 | 强反弹预警准确率 > 60% |
| 3.5 | V4.3基线对比 | V4.3 vs V4 综合评分 | score > 1.0 |

### 3.3 理论假设库（空平方向）

```
假设EXIT-001: 日线底背离 + 4H量能萎缩 = 做空平仓信号
假设EXIT-002: 下跌速度放缓（加速度转正）= 趋势衰竭，准备空平
假设EXIT-003: 反弹幅度 > 下跌幅度的38.2% = 强反弹，加速空平
假设EXIT-004: BTC减半前6个月的做空收益 < 减半后18个月的做空收益
```

---

## Stage 4：四类目的集成融合（V5候选）

> **目标**：将四个独立优化的目的整合为完整交易状态机
> **预期版本**：V5候选（架构升级版，需充分验证）
> **成功标准**：完整策略综合评分 > 1.1（相对V4）

### 4.1 状态机架构

```
┌─────────────────────────────────────────────────────────────┐
│                  四类目的集成状态机                           │
│                                                               │
│   ┌──────────┐    DIP_BUY    ┌──────────┐    TOP_EXIT       │
│   │  WAITING │ ──────────→  │  HOLDING  │ ──────────→      │
│   │ (空仓)   │              │ (牛市持仓)│                   │
│   └──────────┘              └──────────┘                   │
│        ↑                          │                          │
│        │BEAR_EXIT                 │                          │
│        │                          ▼                          │
│   ┌──────────┐              ┌──────────┐                   │
│   │  SHORT   │ ←BEAR_SHORT─ │  EXITING │                   │
│   │ (做空)   │              │ (离场中) │                   │
│   └──────────┘              └──────────┘                   │
│                                                               │
│   状态转换条件由四类目的ML模型预测驱动                       │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 本阶段任务清单

| # | 任务 | 产出 | 验证方式 |
|---|------|------|---------|
| 4.1 | 状态机引擎 | `trading_state_machine.py` | 状态转换逻辑测试 |
| 4.2 | 动态融合权重 | 不同市场阶段各目的权重 | 权重合理性校验 |
| 4.3 | 四类目的模型训练 | 4个独立LightGBM模型 | 各模型AUC > 0.65 |
| 4.4 | 集成策略回测 | V5候选 vs V4 综合评分 | score > 1.1 |
| 4.5 | 多币种验证 | BTC+ETH+SOL均优于V4 | 所有币种score > 1.0 |
| 4.6 | 过拟合深度检测 | Walk-Forward + 置换检验 | 通过检测 |

### 4.3 动态融合权重方案

```python
# 不同市场阶段的四类目的权重
WEIGHTS = {
    "bull_early":    {"DIP_BUY": 0.4, "TOP_EXIT": 0.1, "BEAR_SHORT": 0.1, "BEAR_EXIT": 0.4},
    "bull_peak":     {"DIP_BUY": 0.1, "TOP_EXIT": 0.5, "BEAR_SHORT": 0.1, "BEAR_EXIT": 0.3},
    "bear_early":    {"DIP_BUY": 0.1, "TOP_EXIT": 0.2, "BEAR_SHORT": 0.4, "BEAR_EXIT": 0.3},
    "bear_late":     {"DIP_BUY": 0.3, "TOP_EXIT": 0.1, "BEAR_SHORT": 0.1, "BEAR_EXIT": 0.5},
    "ranging":       {"DIP_BUY": 0.25, "TOP_EXIT": 0.25, "BEAR_SHORT": 0.25, "BEAR_EXIT": 0.25},
}
```

---

## Stage 5：实盘验证与持续迭代

> **目标**：纸交易→实盘部署，建立持续迭代机制
> **成功标准**：实盘/纸交易3个月跑赢V4基线

### 5.1 本阶段任务清单

| # | 任务 | 产出 | 验证方式 |
|---|------|------|---------|
| 5.1 | 纸交易部署 | V5策略接入纸交易引擎 | 运行30天无异常 |
| 5.2 | 纸交易对比 | V5 vs V4 纸交易绩效 | V5夏普 ≥ V4 |
| 5.3 | 实盘小仓位验证 | 10%仓位实盘部署 | 30天无异常 |
| 5.4 | 实盘全仓位部署 | 100%仓位实盘 | 持续监控 |
| 5.5 | 持续迭代机制 | 每周复盘+每月迭代 | 闭环运转 |

### 5.2 实盘监控指标

| 指标 | 预警阈值 | 回退阈值 |
|------|---------|---------|
| 日收益率 | < -5% | < -10% |
| 周收益率 | < -10% | < -15% |
| 月收益率 | 跑输V4 | 连续2月跑输V4 |
| 最大回撤 | > 60% | > 64.15%（V4的120%） |
| 交易频率 | 异常偏高/偏低 | — |

---

## 附录A：各Stage验证脚本

### A.1 Stage 1 验证脚本

```bash
cd 12-三屏趋势系统

# 1. 特征计算单元测试
python -m pytest tests/test_philosophy_features.py -v

# 2. V4.1基线对比回测
python -c "
from ml.halving_top_exit_strategy import HalvingTopExitStrategy
from backtest.engine import BacktestEngine
# 训练含22特征的LightGBM模型
# Walk-Forward回测
# 对比V4基线
"
```

### A.2 通用基线对比模板

```python
# 所有Stage结束时的标准验证流程
def validate_against_v4_baseline(new_strategy_results):
    """新策略必须通过此验证才能采纳"""
    v4_baseline = {
        "sharpe": 0.900, "calmar": 0.680,
        "maxdd": 0.5346, "winrate": 0.5179, "trades": 57
    }
    score = (
        0.4 * (new_results["sharpe"] / v4_baseline["sharpe"])
      + 0.3 * (new_results["calmar"] / v4_baseline["calmar"])
      + 0.15 * (v4_baseline["maxdd"] / new_results["maxdd"])
      + 0.1 * (new_results["winrate"] / v4_baseline["winrate"])
      + 0.05 * trade_freq_score(new_results["trades"])
    )
    return score > 1.0, score
```

---

## 附录B：假设库管理规范

### B.1 假设记录格式

```yaml
hypothesis_id: DIP-001
stage: Stage 2
status: pending  # pending / testing / validated / failed / archived
created: 2026-07-18
description: "周线MA200附近 + 日线RSI<30 + 成交量放大 = 高质量抄底点"
theory_basis: "超卖+支撑位+量能确认的三重共振"
features_required:
  - ma200_distance_pct
  - rsi_14
  - volume_ratio_20d
backtest_result: null  # 待测试
conclusion: null
next_action: "Stage 2 启动时测试"
```

### B.2 假设生命周期

```
提出假设 → pending
    ↓
回测验证 → testing
    ↓
验证通过 → validated → 整合到策略
验证失败 → failed → 归档，记录教训
    ↓
长期不用 → archived
```

---

## 附录C：风险管理与回退流程

### C.1 回退决策树

```
新策略回测完成
    │
    ├─ 综合评分 > 1.1？ ──→ 采纳，更新基线
    │
    ├─ 1.0 < 评分 ≤ 1.1？ ──→ 评估过拟合风险
    │       ├─ 样本内外差异 < 15% → 采纳，标记"边际改进"
    │       └─ 样本内外差异 ≥ 15% → 回退，记录"过拟合风险"
    │
    └─ 评分 ≤ 1.0？ ──→ 回退
            ├─ 分析失败原因（特征/模型/参数/理论）
            ├─ 记录经验教训
            └─ 保留探索代码，归档回测结果
```

### C.2 回退操作清单

| 步骤 | 操作 | 文件 |
|------|------|------|
| 1 | 标记版本为"探索失败" | `optimization_results/{version}_failed.json` |
| 2 | 记录失败原因和关键发现 | 同上 |
| 3 | 策略配置回退到V4基线 | `halving_top_exit_strategy.py` 默认参数 |
| 4 | 分析失败原因 | 形成经验教训文档 |
| 5 | 保留探索代码 | 用于后续参考 |
| 6 | 归档回测结果 | `optimization_results/` |

---

**文档维护**: 每个Stage结束时更新状态和结论
**最后更新**: 2026-07-18
**当前阶段**: Stage 1 待启动（V4特征→ML整合）
**下一步行动**: 启动 Stage 1 任务1.1 — 扩展 `philosophy_feature_engineer.py`
