# 变更日志 — 三屏趋势系统

> **定位**：记录每次变更的原因、内容、验证方式
> **格式**：[版本] - 日期 → 变更类型（新增/修改/修复/删除）
> **当前主线版本**：v4.0.0（Phase 6 双线策略架构）| **Python 包版本**：v1.4.0
> **主线策略**：V4 + 波浪互斥融合 — BTC 年化 56.43%，夏普 1.41，回撤 -43.31%

---

## [v4.0.0] - 2026-07-19

### Phase 6：双线策略架构正式上线 + 主线切换为 V4+波浪互斥融合

- **新增**: 双线策略架构（MAIN + ML_BASELINE 物理隔离）
  - 主策略线 `[MAIN]`：V4 减半周期 + 波浪互斥融合，定位实盘交易、生产部署（✅ 已部署）
  - 机器学习基线 `[ML_BASELINE]`：V5.5 LightGBM 28维哲学特征工程，定位探索验证、特征工程实验（🔬 实验状态）
  - 共享基础设施 `[SHARED]`：物理引擎（pitd_*）+ 回测引擎 + 数据层 + 核心算法层，被两条线共同依赖
  - 文件归属标签体系：`[MAIN]` / `[ML_BASELINE]` / `[SHARED]` 三类，修改规则差异化
  - **影响范围**: docs/STRATEGY_LINES.md（新建）、docs/TECHNICAL_DESIGN.md §8、docs/ENGINEERING_INDEX.md §5
  - **验证方式**: 9年回测对比（BTC）：主线 V4+波浪年化 56.43% vs 副线 V5.5 年化 4.31%
  - **回滚策略**: 主线回退到纯 V4 基线（禁用波浪融合），副线降级保留实验状态

- **修改**: 主策略线从 V5.5 ML 切换为 V4+波浪互斥融合
  - 旧主线 V5.5 LightGBM 严重过拟合（年化 4.31%，夏普 0.3024，回撤 -56.48%），降级为副线
  - 新主线 V4+波浪互斥融合实盘部署，决策链路：五大算法 → V4定方向 → 波浪择时加仓 → 物理置信度调节 → 最终决策
  - **影响范围**: engine.py（编排主线流程）、ml/halving_top_exit_strategy.py、ml/ewave_strategy_adapter.py、ml/altcoin_trend_strategy.py
  - **验证方式**: 9年回测（BTC）年化 56.43% ≥ 纯 V4 基线 53.34%（通过）
  - **回滚策略**: 触发任一回退条件（实盘连续3个月跑输纯 V4 / 回撤>53.24% / 减半预测失败）→ 禁用波浪融合，回退到纯 V4

- **新增**: 波浪互斥融合规则（9种场景，6类规则）
  - V4 多头 + 波浪看多 → V4 仓位 + 波浪加仓（同向叠加）`v4_long_wave_add`
  - V4 多头 + 波浪中性/看空 → 保持 V4 仓位（V4 优先）`v4_long_keep`
  - V4 空仓 + 波浪看多 → 波浪轻仓抄底（上限 30%）`v4_wait_wave_bottom`
  - V4 空仓 + 波浪看空 → 空仓观望 `v4_wait_wave_wait`
  - V4 空头 + 波浪看空 → 保持 V4 空头 `v4_short_keep`
  - V4 空头 + 波浪看多 → V4 空头减半（波浪提示反弹）`v4_short_wave_reduce`
  - **影响范围**: ml/ewave_strategy_adapter.py、ml/ewave_recognizer.py、engine.py
  - **验证方式**: 9年回测对比，V4+波浪融合年化 56.43% > 纯 V4 年化 53.34% > 买入持有 34.80%

- **新增**: 9年回测基线快照（BTC，2026-07-19）
  - 主线 [MAIN] 基线：V4+波浪互斥融合 — 年化 **56.43%**，总收益 **1970.42%**，夏普 **1.4112**，回撤 **-43.31%**，Calmar **1.3031**
  - 纯 V4 基线：年化 53.34%，总收益 1708.54%，夏普 1.3744，回撤 -44.37%，Calmar 1.2022
  - 买入持有基线：年化 34.80%，总收益 655.68%，夏普 0.8024，回撤 -76.40%，Calmar 0.4555
  - 副线 [ML_BASELINE] 基线：V5.5 LightGBM — 年化 4.31%，夏普 0.3024，回撤 -56.48%，28维特征
  - **影响范围**: docs/STRATEGY_LINES.md §6、docs/TECHNICAL_DESIGN.md §8.3
  - **验证方式**: `python ml/comprehensive_strategy_comparison.py --symbol BTC` 复现年化 56.43%

- **新增**: 主线修改流程与晋升/回退机制
  - 主线修改流程：修改 → `pytest tests/test_core.py` → `python ml/comprehensive_strategy_comparison.py` → 验证年化 ≥ 56.43%（V4+波浪基线）→ 通过合并 / 未通过回退
  - 副线晋升条件：9年年化 ≥ 56.43% + 夏普 ≥ 1.41 + 回撤 ≤ -43.31% + Walk-Forward AUC ≥ 0.60 + 多币种（BTC/ETH/SOL）均优于主线
  - 主线回退条件（任一）：实盘连续3个月跑输纯 V4 / 最大回撤 > 53.24% / 减半周期预测失败（2025-10 后未见顶）
  - **影响范围**: docs/STRATEGY_LINES.md §4-§5
  - **回滚策略**: 配置回退到纯 V4 基线（禁用波浪融合），分析失败原因后重新申请晋升

- **新增**: 副线工作区 `ml/v55_baseline/`（目录规划，仅创建 README 与 `__init__.py`，不强制迁移）
  - **影响范围**: ml/v55_baseline/
  - **验证方式**: 目录存在性检查 + 后续 V5.5 验证脚本逐步迁移

- **修改**: 技术文档全面更新至 Phase 6 双线架构
  - `TECHNICAL_DESIGN.md` v3.5 → v4.0：§1.2 双线策略架构、§7 版本演进追加 Phase 6、§8 双线策略架构、§9 V4 基线策略与优化原则
  - `ENGINEERING_INDEX.md` → v4.0.0：新增 §4 集成推理层、§5 双线策略架构
  - **影响范围**: docs/TECHNICAL_DESIGN.md、docs/ENGINEERING_INDEX.md
  - **回滚策略**: 恢复 v3.5 版本文档

---

## [v1.4.0] - 2026-07-15

### 集成推理层上线：LightGBM 46维特征 + LLM 辩证推理（按需触发）

- **新增**: LightGBM 集成推理引擎 `ml/algo_ensemble.py`
  - 46维特征分组：趋势一致性 16维 + 贝叶斯置信度 3维 + 经典指标置信度 10维 + 技术基本面融合 4维 + 价值风险评估 4维 + Freqtrade 信号 4维 + 最终信号 5维
  - 核心函数：`predict_ensemble()` / `collect_sample()` / `train_ensemble()` / `extract_ensemble_features()`
  - 模型存储：`ml/models/ensemble/`（含 `collected/` 样本目录与 `versions/` 历史版本）
  - 训练样本：`ml/models/ensemble/collected/samples_YYYY-MM-DD.jsonl`（按日分文件）
  - **影响范围**: ml/algo_ensemble.py、ml/models/ensemble/
  - **验证方式**: `python ml/label_samples.py --train --lookahead 7`，AUC ≥ 0.55

- **新增**: LLM 辩证推理引擎 `ml/llm_reasoning.py`（按需触发，节省 token）
  - 触发规则：集成置信 < 40 → 触发；置信 40-60 + 矛盾 → 触发；置信 ≥ 60 → 不触发
  - 5 类矛盾检测：趋势不一致 / 贝叶斯方向不一致 / 经典指标不一致 / 技术面与基本面不一致 / 逆转信号偏高
  - LLM 服务：DeepSeek API，API Key 来源：进程环境变量 > `experiments/ab-trading/config/.env` > `12-三屏趋势系统/.env`
  - 返回结构：direction / confidence / source / contradiction_analysis / reasoning / risk_note / trust_weight / contradictions / trigger_reason
  - **影响范围**: ml/llm_reasoning.py
  - **验证方式**: 低置信场景触发率统计 + 矛盾检测覆盖 5 类维度

- **新增**: 样本标注与训练工具 `ml/label_samples.py`
  - CLI 命令：`--list`（样本统计）/ `--lookahead N`（标注未来 N 日收益）/ `--train`（标注 + 训练一条龙）/ `--test-ratio`（测试集比例）
  - 数据来源：OKX K线 API，按币种分组回填 `_future_return` 字段
  - **影响范围**: ml/label_samples.py、ml/models/ensemble/collected/
  - **验证方式**: `python ml/label_samples.py --list` 查看样本统计

- **修改**: `__init__.py` Python 包版本号 v1.3.0 → v1.4.0
  - **影响范围**: __init__.py
  - **回滚策略**: 恢复 `__version__ = "1.3.0"`

---

## [v4] - 2026-06-30

### Phase 5：V4 减半周期逃顶基线（BTC 专用）

- **新增**: V4 减半周期逃顶策略 `ml/halving_top_exit_strategy.py`
  - `HalvingTopExitStrategy` 类：基于比特币减半周期时间维度的四阶段仓位管理 + 四重逃顶机制
  - 四阶段仓位管理（基于减半后月数）：
    - Normal（0-12月）：仓位上限 100%，正常牛市满仓持有
    - Warn（12-15月）：仓位上限 70%，预警区开始减仓
    - Danger（15-18月）：仓位上限 30%，高危区加速减仓
    - Peak（18-24月）：仓位上限 0%，见顶区清仓等待
    - 24 月后：恢复 100%，MA200 策略接管
  - 四重逃顶机制：减半周期 + 越高越卖 + MA128 破位 + 反弹卖出
  - **影响范围**: ml/halving_top_exit_strategy.py、engine.py
  - **验证方式**: BTC 9年回测，V4 总收益 1440.30% > V3 833.72% > V2 632.47%
  - **回滚策略**: 禁用 V4 策略，回退到 V3 做空优化基线

- **新增**: 比特币减半历史时间锚定
  - 第2次减半 2016-07-09 → 预测见顶 2018-01-09 → 实际见顶 2017-12（约17月）
  - 第3次减半 2020-05-11 → 预测见顶 2021-11-11 → 实际见顶 2021-11（约18月）
  - 第4次减半 2024-04-20 → 预测见顶 2025-10-20 → 待验证
  - **影响范围**: ml/halving_top_exit_strategy.py
  - **验证方式**: 历史回测验证减半周期时间锚定的有效性

- **新增**: V4 三大哲学贡献（特征总数：V2 原有 15 + V4 新增 7 = 22 个哲学特征）
  - 减半周期时间锚定：时间维度比价格维度更确定（3个新特征）
  - 四阶段仓位递减：顶部是区域而非瞬间，分阶段减仓优于一次性清仓（2个新特征）
  - 越高越卖：顶部区域每创新高都是卖出机会（2个新特征）
  - **影响范围**: ml/halving_top_exit_strategy.py、ml/v2_baseline_optimization_principles.md
  - **验证方式**: 消融实验，移除任一哲学贡献后综合评分下降

- **新增**: V4 vs V2 vs V3 综合对比（BTC 9年回测）
  - 总收益率：V2 632.47% → V3 833.72% → V4 **1440.30%**（V4 vs V2 +127.8%）
  - 夏普比率：V2 0.600 → V3 0.670 → V4 **0.900**（V4 vs V2 +50.0%）
  - 最大回撤：V2 77.85% → V3 76.25% → V4 **53.46%**（V4 vs V2 -31.3%）
  - 卡玛比率：V2 0.330 → V3 0.380 → V4 **0.680**（V4 vs V2 +106.1%）
  - 综合评分：V2 1.000 → V3 1.098 → V4 **1.592**（V4 vs V2 +59.2%）
  - 交易次数：V2 92 → V3 66 → V4 **57**（V4 vs V2 -38.0%）
  - **影响范围**: docs/TECHNICAL_DESIGN.md §7 Phase 5
  - **验证方式**: `python ml/9year_strategy_comparison.py` 复现回测结果

- **新增**: V4 基线优化原则文档 `ml/v2_baseline_optimization_principles.md`
  - 完整版 V4 基线优化原则，作为后续策略迭代的对比基线
  - **影响范围**: ml/v2_baseline_optimization_principles.md
  - **回滚策略**: 不涉及代码变更，文档可独立删除

- **新增**: 非 BTC 趋势跟踪策略 `ml/altcoin_trend_strategy.py`
  - `AltcoinTrendStrategy` 类：非 BTC 币种使用自身 MA200 + 减半影子仓位
  - 与 BTC V4 主策略形成互补，覆盖多币种场景
  - **影响范围**: ml/altcoin_trend_strategy.py、engine.py
  - **验证方式**: ETH/SOL 等非 BTC 币种回测验证

---

## [v3] - 2026-06-15

### Phase 4.5：V3 做空优化基线

- **新增**: V3 做空优化策略 `ml/enhanced_ma200_v3_strategy.py`
  - `EnhancedMA200Strategy v3`：在 V2 基础上引入做空机制与逃顶框架
  - 抄底 + 逃顶双框架，趋势跟踪 + 反转预警
  - **影响范围**: ml/enhanced_ma200_v3_strategy.py、ml/baseline_config_v3.json
  - **验证方式**: BTC 9年回测，V3 总收益 833.72% > V2 632.47%，夏普 0.670 > V2 0.600
  - **回滚策略**: 回退到 V2 基线 `ml/enhanced_ma200_v2_config.json`

- **新增**: V2 vs V3 对比回测脚本 `ml/v2_vs_v3_comparison.py`
  - **影响范围**: ml/v2_vs_v3_comparison.py
  - **验证方式**: 运行对比脚本输出回测结果表

- **修改**: V3 基线配置 `ml/baseline_config_v3.json`
  - 标记 V3 为新的基线版本
  - **影响范围**: ml/baseline_config_v3.json

---

## [v2] - 2026-06-01

### Phase 4.1：V2 基线策略 + 15 个哲学特征工程

- **新增**: V2 基线策略（基于 EnhancedMA200 + 15 个哲学特征）
  - V2 基线作为后续所有策略版本（V3/V4/V5.5）的对比基准
  - BTC 9年回测基线：总收益 632.47%，夏普 0.600，最大回撤 77.85%，卡玛 0.330
  - **影响范围**: ml/enhanced_ma200_v2_config.json
  - **验证方式**: 9年回测复现 V2 基线指标
  - **回滚策略**: 无（V2 为初始基线）

- **新增**: 15 个哲学特征工程
  - 趋势一致性、贝叶斯置信度、经典指标置信度等基础特征
  - 作为后续 V4 新增 7 个特征、V5.5 扩展到 28 维特征的基础
  - **影响范围**: ml/feature_engineer.py、ml/philosophy_feature_engineer.py
  - **验证方式**: 特征重要性排序与消融实验

- **新增**: V2 基线优化原则文档（V4 文档的前身）
  - 作为 V4 减半周期逃顶策略的设计依据
  - **影响范围**: ml/v2_baseline_optimization_principles.md

---

## [v1.3.0] - 2026-05-20

### Phase 3.5：最小阻力方向引擎（三屏趋势算法内核）

- **新增**: 最小阻力方向引擎 `core/least_resistance.py`
  - 核心原理：市场总是沿着阻力最小方向运动（第一性原理）
  - 5 大阻力维度：价格阻力(30%) + 量能阻力(20%) + 动量阻力(20%) + 趋势阻力(20%) + 基本面阻力(10%)
  - 时间三维 × 五维阻力 → 最小阻力三维模型（D/V/A）
  - 量变积累 → 质变突破检测：ACCUMULATION → BREAKTHROUGH_IMMINENT → BREAKTHROUGH_CONFIRMED
  - 双向驱动模型：CONTINUATION / LATE_CONTINUATION / ACCUMULATION / WEAKENING
  - 核心函数：`compute_least_resistance_3d()` / `compute_least_resistance()` / `calc_trend_strength()` / `determine_drive_mode()` / `detect_accumulation_breakthrough()`
  - **影响范围**: core/least_resistance.py、core/config.py、backtest/strategy.py（`LeastResistanceStrategy`）
  - **验证方式**: 纯算法驱动回测，绕过完整推理链验证内核有效性
  - **回滚策略**: 设置 `LEAST_RESISTANCE_ENABLED=False` 回退到静态指标投票

- **修改**: 静态指标投票移除，最小阻力引擎为唯一方向来源
  - **影响范围**: engine.py、core/indicators.py
  - **回滚策略**: 恢复静态指标投票逻辑

---

## [v1.2.0] - 2026-05-10

### Phase 3.4：综合预测引擎（技术基线 + 基本面三维度调节）

- **新增**: 综合预测引擎 `core/composite_predictor.py`
  - 核心公式：`final_confidence = tech_confidence × (1 + fundamental_adjustment)`
  - 三维度模型：Direction / Velocity / Acceleration（来自 9-基本面分析的 LeastResistance 引擎）
  - 四维调节因子：方向匹配(30%) + 速度(30%) + 加速度(20%) + 情绪(20%)
  - 权重配置：technical_base 0.6 / fundamental_adjust 0.4
  - 核心函数：`CompositePredictor.predict()` / `compute_fundamental_3d()` / `analyze_sentiment()` / `generate_signals()` / `compute_fundamental_adjustment()`
  - **影响范围**: core/composite_predictor.py、engine.py
  - **验证方式**: 集成测试 + 调节因子敏感性分析
  - **回滚策略**: 禁用综合预测引擎，回退到纯技术面置信度

---

## [v1.1.0] - 2026-04-25

### Phase 3.3：双路径基本面架构（Path A + Path B）

- **新增**: Path A（AI 驱动）基本面数据源 `data/fundamental_data.py`
  - 数据源：A 系列研报（周报 MD + A1 日报 JSON）
  - 融合入口：`engine.py → fetch_fundamental_data() → fusion.py`
  - 回退机制：无研报时用经典指标系统兜底
  - **影响范围**: data/fundamental_data.py、core/fusion.py
  - **验证方式**: 研报解析单测 + 回退机制验证

- **新增**: Path B（算法驱动）基本面数据源 `data/tavily_data.py`
  - Tavily API 实时搜索 4 维基本面数据（矿工 / 链上 / 宏观 / 跨市场）
  - 30 分钟本地缓存，SDK + HTTP 双模式，年份过滤
  - 核心函数：`fetch_all_tavily_dimensions()` / `collect_miner_economics()` / `collect_onchain_valuation()` / `collect_macro_finance()` / `collect_cross_market()` / `tavily_search()`
  - **影响范围**: data/tavily_data.py、core/fundamental_screen1.py
  - **验证方式**: Tavily API 集成测试 + 4 维数据采集 + 7 维分析 + 文本解析

- **新增**: Path B 核心模块 `core/fundamental_screen1.py`
  - 7 维基本面分析框架：减半周期(纯代码) + Tavily API(4维) + annotation 回退
  - 数据源优先级：Tavily API > 6-TRADING annotation > 纯代码（减半周期）
  - 核心函数：`calc_fundamental_screen1()` / `calc_halving_cycle()` / `fuse_tech_fundamental()` / `_try_tavily_dimensions()` / `load_annotation_dimension()`
  - **影响范围**: core/fundamental_screen1.py
  - **验证方式**: 7 维分析输出 + 加权融合方向/置信度验证

---

## [v1.0.3] - 2026-04-15

### Phase 3.2：币种池优化 + 置信度校准

- **修改**: 币种池精简
  - 聚焦高流动性大币种（BTC/ETH/SOL/BNB）
  - 扩展币种：HYPE/UNI/ARB/ZEC/DOGE（高流动性标的）
  - 剔除低流动性小币种（XRP/ADA/AVAX/LINK/DOT/TRX/MATIC 等）
  - **影响范围**: core/config.py（`CANDIDATE_COINS`）
  - **验证方式**: 币种池变更后全量回测
  - **回滚策略**: 恢复 `CANDIDATE_COINS` 原值

- **新增**: Platt Scaling 置信度校准 `backtest/calibration.py`
  - sigmoid 函数拟合校准曲线
  - 训练方法：`TrendScreenStrategy.train_calibration()`
  - 便捷工厂方法：`TrendScreenStrategy.with_calibration()`
  - 5 折交叉验证避免过拟合
  - 校准效果：训练集 ECE 从 22.6% 降至 1.3%（改善 94%）
  - **影响范围**: backtest/calibration.py、backtest/strategy.py
  - **验证方式**: 5 折 CV ECE 评估 + 参数敏感性分析

- **新增**: 过拟合检测工具 `backtest/overfitting.py`
  - 置换检验 / 参数敏感性分析 / 交易成本敏感性测试
  - 核心函数：`permutation_test()` / `parameter_sensitivity_analysis()` / `cost_sensitivity_test()`
  - **影响范围**: backtest/overfitting.py
  - **验证方式**: BTC 参数敏感性评分 21.0/100（稳健，过拟合风险低）

---

## [v1.0.2] - 2026-04-05

### Phase 3.1：BTC 风向标闸门

- **新增**: BTC 风向标闸门 `engine.py → evaluate_btc_wind_vane()`
  - BTC 日线 MA128 连续跌破检测（3日确认）
  - BTC 周线 MA200 站上检测
  - 三种闸门状态：强制做多 / 做空闸门开 / 双向开放
  - 优先级：周线 MA200 > 日线 MA128 > 中间状态
  - 三条大原则：
    - 规则3：BTC 周收盘价 > 周线 MA200 → 强制做多，禁止做空（最高优先级）
    - 规则1：BTC 连续3日收盘 < 日线 MA128 → 做空闸门打开，做多关闭
    - 中间：未跌破 MA128 且未站上 MA200 → 双向开放
  - 集成到 `five_algo_decision()` 最高优先级
  - **影响范围**: engine.py、core/config.py（`BTC_WIND_VANE_*` 配置项）
  - **验证方式**: 6 场景全量验证通过
  - **回滚策略**: 设置 `BTC_WIND_VANE_ENABLED=False` 关闭闸门

- **修改**: 非 BTC 币种使用 BTC 风向标数据过滤
  - 传入 `btc_daily_df` / `btc_weekly_df` / `btc_trend_direction` 参数
  - **影响范围**: engine.py `compute_trend_signal_from_dataframes()`

---

## [v1.0.1] - 2026-03-20

### Phase 3：逐仓 + 价值风险 + 加仓系统

- **新增**: 逐仓模式（isolated margin, 5x 杠杆）
  - 50% 初始仓位 / 70% 加仓上限
  - **影响范围**: core/config.py（`MARGIN_MODE` / `MAX_LEVERAGE` / `MAX_POSITION_PCT`）
  - **验证方式**: 仓位计算单测 + 回测对比

- **新增**: 价值风险评估 `core/risk_reward.py`
  - Elder-ray 趋势强度 + 背离检测
  - 30 日波动率放大（vs BTC 基准）
  - 风险回报比计算（RR 阈值 1.5）
  - 价值 < 风险时仓位限制 5%
  - 核心函数：`calc_elder_ray()` / `calc_30d_volatility()` / `get_vol_adjusted_params()` / `calc_risk_reward_ratio()` / `calc_position_sizing()`
  - **影响范围**: core/risk_reward.py、engine.py `compute_value_risk_assessment()`
  - **验证方式**: Elder-ray 8 类趋势分类 + 背离检测单测

- **新增**: 加仓系统 `core/risk_reward.py → evaluate_addon_opportunity()`
  - 逆势背离加仓：BTC 亏损≥8% + 背离 + 价值>风险（其他币按波动率比）
  - 顺势趋势强度加仓：盈利≥50% + Elder-ray 强度≥65
  - 最多 2 次加仓
  - **影响范围**: core/risk_reward.py、engine.py `evaluate_addon_decision()`
  - **验证方式**: 加仓场景回测 + 风控约束验证

- **新增**: 自动止盈止损（波动率放大）
  - 止盈百分比 = 4% × vol_ratio（限制在 0.5-2.5）
  - 止损百分比 = 10% × vol_ratio
  - **影响范围**: engine.py `compute_value_risk_assessment()`
  - **验证方式**: 波动率放大参数边界测试

---

## [v1.0.0] - 2026-03-01

### Phase 1 + Phase 2：核心框架 + 深化扩展（初始版本）

- **新增**: 三屏趋势系统初始版本（Python 包版本 v1.0.0）
  - 三层趋势分析引擎（周线 / 日线 / 4H）
  - 静态指标投票 + 三维动态融合（direction / speed / acceleration）
  - 动态优先原则
  - 趋势一致性判断（`core/trend_consistency.py`）
  - 动态权重调整（`core/dynamic_weights.py`）
  - **影响范围**: core/、engine.py
  - **验证方式**: `python tests/test_core.py` 核心测试套件
  - **回滚策略**: 无（初始版本）

- **新增**: 五大算法模式综合决策 `engine.py → five_algo_decision()`
  - 静态指标投票 + 三维动态融合 + 动态权重 + 贝叶斯寻优 + 技术面基本面撮合
  - 置信度 → 仓位映射（5档：heavy/medium/moderate/light/trial/micro）
  - **影响范围**: engine.py、core/config.py（`POSITION_TIERS`）
  - **验证方式**: `test_five_algo_decision()` 测试用例

- **新增**: 贝叶斯置信度 + 经典指标置信度融合
  - 贝叶斯置信度：`core/dynamic_weights.py → calc_bayesian_confidence()`
  - 经典指标置信度：`core/indicators.py → calc_classic_indicator_confidence()`
  - **影响范围**: core/dynamic_weights.py、core/indicators.py
  - **验证方式**: `test_bayesian_confidence()` / `test_fusion()` 测试用例

- **新增**: 技术面 + 基本面撮合 `core/fusion.py → fuse_technical_fundamental()`
  - 一致 / 中性 / 矛盾三场景融合规则
  - **影响范围**: core/fusion.py
  - **验证方式**: `test_fusion()` 测试用例

- **新增**: Freqtrade 入场信号集成（Screen 3）
  - HTTP 桥接：`classic_bridge.py` 调用 10-经典指标系统 `/api/freqtrade/signals`
  - 信号服务：`signals.py` 提供 `fetch_freqtrade_signals()` / `align_freqtrade_with_trend()`
  - 基本面缺失回退到经典指标
  - **影响范围**: classic_bridge.py、signals.py、engine.py
  - **验证方式**: `test_full_signal()` 测试用例

- **新增**: 信号池架构 `signal_pool/`
  - `pool.json` 多币种多策略信号缓存
  - `scanner.py` 守护进程定时扫描（默认每 5 分钟）
  - **影响范围**: signal_pool/scanner.py、signal_pool/pool.json
  - **验证方式**: `python3 signal_pool/scanner.py --once` 单次扫描

- **新增**: 回测引擎 `backtest/`
  - `BacktestEngine` 向量化回测（手续费 + 滑点 + 杠杆 + 物理增强）
  - `BuyAndHoldStrategy` / `MovingAverageStrategy` / `TrendScreenStrategy` 基线策略
  - `WalkForwardAnalyzer` 滚动向前验证
  - 绩效指标：夏普 / 最大回撤 / 胜率 / 盈亏比
  - **影响范围**: backtest/
  - **验证方式**: `python3 backtest/run_backtest.py` 演示脚本

- **新增**: ML 策略模块 `ml/`
  - `MLStrategy` 特征工程 + 模型推理 + 信号生成
  - `TrendClassifier` 分类/回归模型定义与训练
  - `tune_hyperparams()` 网格/贝叶斯超参数搜索
  - `ModelVersionManager` 模型注册、版本切换、灰度上线
  - **影响范围**: ml/
  - **验证方式**: Walk-Forward 滚动训练（训练窗口 365 天，重训练间隔 30 天）

---

## 维护规则

- 每次代码变更后必须在此文件追加变更记录
- 变更记录需包含：版本号、日期、变更类型、变更内容、影响范围、验证方式、回滚策略
- 主线 [MAIN] 变更必须通过 9 年回测验证（年化 ≥ 56.43%）后方可合并
- 副线 [ML_BASELINE] 变更必须通过 Walk-Forward 验证（AUC ≥ 0.55）后方可合并
- 共享基础设施 [SHARED] 变更必须同时验证两条策略线

---

_最后更新：2026-07-25 | 来源：12-三屏趋势系统（v4.0.0 双线策略架构）_
