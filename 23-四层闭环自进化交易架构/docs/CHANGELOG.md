# 23-四层闭环自进化交易架构 — 变更日志

> **版本**: v1.12 | **更新日期**: 2026-10-07
> **定位**: 模块级变更日志，对齐 [DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md)

---

## [v1.12] - 2026-10-07 (Granger 双链路 + head_multipliers 完整接入)

### 核心成果

交叉验证层 4 个开关全部开启，实现完整双链路（Granger 过去 + Attention 现在）+ head_multipliers 跨轮传递到 NeuralSDE。

### 1. Granger 因果链接入

- **数据源**：从 `market_data["close"]` 价格序列派生 3 维度因子
  - technical: 收益率序列（动量）
  - fundamental: 价格偏离 MA20（均值回归）
  - macro: 20 期滚动波动率（波动率制度）
- **收益率**：对数收益率 `diff(log(price))`
- **触发条件**：价格序列长度 ≥ 30
- **输出**：G_dim + G_confidence，无显著因果时 G_dim=None（降级）

### 2. head_multipliers 完整接入

- `deep_reasoning_engine.reason()` 新增 `head_multipliers: Optional[np.ndarray]` 参数
- 传递链：`reason → neural_sde_forecast → NeuralSDE.forecast(head_multipliers=)`
- **跨轮传递**：`_select_optimal_path` 中保存 `self._last_head_multipliers`，下一轮路径发现时传入 `reason()`
- 转换：`CrossValidationGate.head_adjustment_to_array(dict) → (n_heads,) ndarray`

### 3. 开关状态（全部开启）

| 开关 | 状态 |
|------|------|
| enable_cross_validation_gate | True |
| enable_granger_pipeline | True |
| enable_attention_aggregator | True |
| enable_head_multipliers_adjustment | True |

### 4. 测试

- 新增 `test_cv_full_integration.py`（5 测试）
- 57 个相关测试零回归

---

## [v1.11] - 2026-10-07 (交叉验证层接入 evolution_pipeline 主流程)

### 核心成果

CrossValidationGate 正式接入 `_select_optimal_path()` 主流程，4 个 agi_config 开关配置完成（默认 False），confidence_mult 应用于路径评分，质变事件自动记录到认知系统。

### 1. agi_config 开关（4 个，默认 False）

| 开关 | 作用 |
|------|------|
| `enable_cross_validation_gate` | 交叉验证层总开关 |
| `enable_granger_pipeline` | Granger 因果链（G_dim） |
| `enable_attention_aggregator` | Attention 聚合（A_dim） |
| `enable_head_multipliers_adjustment` | head_multipliers 调整 |

### 2. evolution_pipeline 集成

- **集成点**：Phase 2.5（结构断裂检测之后、弹性约束之前）
- **A_dim**：从 `primary_contradiction.dimension` 获取（现在主矛盾）
- **G_dim**：优先 GrangerPipelineAdapter，失败降级为 None（Q4 降级模式）
- **structural_break**：复用 Phase 2 的 `self._last_structural_break`
- **confidence_mult**：应用于路径评分（一致→1.15 加分，分歧→0.9 减分）
- **质变事件**：`quality_change=True` 时调用 `CognitiveBridge.record_quality_change()`
- **返回值**：新增 `cross_validation` 字段

### 3. FAIL-OPEN 保证

- 开关关闭 → `cv_result` 默认 `{confidence_mult:1.0, ...}`，不影响现有评分
- 任何子组件异常 → 捕获并返回中性结果
- `quality_change` 兼容 bool/dict 两种格式

### 4. 测试

- 新增 `test_cv_pipeline_integration.py`（4 测试）
- 44 个相关测试零回归

---

## [v1.10] - 2026-10-07 (矛盾 Transformer 交叉验证层：v0.8 勘误落地 + 前置 P0 修复)

### 核心成果

矛盾论与 Transformer 融合方案 v0.8 发布，SPEC 评审 v1.2 的 8 项勘误全部应用；3 项前置 P0 修复（TDD-PRE-001/002/003）落地并通过 15 项现有测试零回归。

### 1. 文档勘误（8 项，融合方案 v0.7 → v0.8）

- §10.11.1 `divergence_count` 字段表述修正（"已有"→"实现后将包含"），补充 BTC persistence 推荐范围（30m=[5,7]/1h=[7,10]/1d=[10,14]/1w=[14,20]）
- §10.11.2 `reversion_rate` 0.05→0.15（OU 离散过程 r=1-exp(-Δt/τ)，18 期回归 5% 容差；原 0.05 实际需 59 期），EM 算法→OU 离散过程
- §10.11.3 FOMC 对齐逻辑修正（24h 非对齐 FOMC 6 周）
- §10.11.5 Q5 权重表更新（CUSUM→Welch's t-test，HMM→Markov-Regression，threshold 临时 0.4）
- 新增 §5.1.5a 替代框架对比（5 框架 walk-forward，v0.7 夏普 2.85 排 1）
- 新增 §10.11.4a Q4 单链路 SPRT 在线监测（p0=0.75/p1=0.50，ASN≈73）

### 2. 前置 P0 修复（TDD-PRE-001/002/003）

- TDD-PRE-001: [structural_break_detector.py](../dreambuddy_evolution/core/structural_break_detector.py) `detect_correlation_break` 从 `breaks_cusumolsresid`（statsmodels 0.13+ 移除）改为 `scipy.stats.ttest_ind` Welch's t-test，叠加 `abs(mean_diff)>0.3` 效应量阈值
- TDD-PRE-002: `MarkovRegression(maxiter=100)` → `maxiter=500`，修复 HMM 100% ConvergenceWarning
- TDD-PRE-003: [contradiction_shift_accumulator.py](../dreambuddy_evolution/core/contradiction_shift_accumulator.py) 新增 `consecutive_count` 字段 + `quality_change_log.jsonl` 落盘机制，`STRUCTURAL_BREAK_THRESHOLD` 临时 1.0→0.4

### 3. 测试

- 新增 `test_structural_break_detector_fixes.py` / `test_contradiction_shift_accumulator_fixes.py`
- 15 项 `test_phase2_causal.py` 零回归

### 4. TDD-CV 核心实现（交叉验证层）

- TDD-CV-001: [attention_aggregator.py](../dreambuddy_evolution/core/attention_aggregator.py) — head-weight 求和聚合输出 A_dim
- TDD-CV-002: [cross_validation_gate.py](../dreambuddy_evolution/core/cross_validation_gate.py) — §5.1 五步算法 + Q1~Q5 优化（Bayesian 校准 / floor-ceiling-mean reversion / 冷却期 / 三级降级+SPRT / 加权共识）
- TDD-CV-003: head_multipliers 收敛性验证（r=0.15，20 期回归 [0.95, 1.05]）
- TDD-PRE-004: [sprt_monitor.py](../dreambuddy_evolution/core/sprt_monitor.py) — SPRT 序贯概率比检验（p0=0.75/p1=0.50, α=0.05, β=0.10），集成到 CrossValidationGate 降级模式

### 5. TDD-CV-004: 5 框架 walk-forward 对比验证

- [framework_comparison.py](../dreambuddy_evolution/core/framework_comparison.py) — 5 框架（交叉验证/Bayesian/互信息/Shapley/Granger）配对 walk-forward + DSR + PBO + Holm-Bonferroni 校正
- BTC 30m 87598 期实测：F1 交叉验证 OOS 夏普 7.77, DSR=1.0，显著优于 F2/F4/F5（adj_p<0.001），与 F3 互信息相当
- 结果: [framework_comparison_result.json](../dreambuddy_evolution/data/framework_comparison_result.json)

### 6. TDD-CV-005: Step 2/4/5 落地 — GrangerPipelineAdapter + head_multipliers 接入 + 自进化闭环阶段1

- TDD-CV-Step2: [granger_pipeline_adapter.py](../dreambuddy_evolution/core/granger_pipeline_adapter.py) — 包装 GrangerCausalityChecker，3 维度 Granger 检验 + Bonferroni 多重比较校正（α/ (3×max_lag)）
  - 修复 [granger_causality_checker.py](../dreambuddy_evolution/core/granger_causality_checker.py) statsmodels 0.15 兼容：`grangercausalitytests(verbose=)` 移除 + `adfuller(result_object=)` 兼容回退
- TDD-CV-Step4: `CrossValidationGate.head_adjustment_to_array()` — dict→(n_heads,) ndarray；`deep_reasoning_engine.neural_sde_forecast(head_multipliers=)` 接入 NeuralSDE.forecast
- TDD-CV-Step5 阶段1: `CognitiveBridge.record_quality_change()` — 质变事件→认知记忆 record（B 级，tags=质变/交叉验证/自进化/矛盾论）；granger_reestimate_trigger 信号已在 CrossValidationGate 输出
  - FTCEvolutionBridge 基因创新触发：待交叉验证层稳定运行后接入（渐进策略，见 §10.12 P1-B）
- TDD-CV-006 消融实验: [poc_cv_ablation.py](../dreambuddy_evolution/core/poc_cv_ablation.py) — 5 组对比（全功能/无Q2/无Q5/无Q4/纯Attention）
  - 结果: E0 全功能夏普 1.57，E2 无 Q5 降至 1.35（-0.22），E4 纯 Attention 归零。Q5 类型加权 + 双链路交叉验证是核心价值来源
  - CrossValidationGate 新增 `enable_structural_break_weighting` 开关（Q5 可独立关闭）

---

## [v1.9] - 2026-10-05 (NeuralSDE 路径依赖升级 + v2 上线 + 第 3 轮 PoC 反模式修正)

### 核心成果

NeuralSDE 第 2/3 轮架构优化完成, 路径依赖 SDE 超越 GARCH 3.3x, v2 已上线为 `neural_sde_v1.pt` (生产最优).

### 1. 第 2 轮 (TDD-010/011/012, 已 PASS)

PoC v2 (200ep MSE + sig_dim=15 + z-score 归一化):
- **MAE=269.51** vs GARCH=881.14, **ratio=0.31** (优于 GARCH 3.3x) ✅ PASS
- 权重: [neural_sde_v1_path_sig_v2.pt](../dreambuddy_evolution/data/neural_sde_v1_path_sig_v2.pt)
- 报告: [neural_sde_v1_poc_tdd007_v2.json](../dreambuddy_evolution/data/neural_sde_v1_poc_tdd007_v2.json)
- 测试: 12 个新测试 (TDD-010 z-score / TDD-011 不截断 / TDD-012 QLIKE) + 86 全套无回归

3 个根因修复:
- TDD-010: [neural_sde_model.py](../dreambuddy_evolution/core/neural_sde_model.py) `_compute_log_sig` 拆分 raw + z-score 归一化 (跨样本统计 mean/std), 解决 log_sig 第 3 维 ~7 vs S_t ~2 内部尺度不一致
- TDD-011: `DEFAULT_SIG_DIM=4 → 15` 适配 SignatureEngine esig depth=3 实际输出 (不截断, pad zeros 兼容 numpy 6 维)
- TDD-012: `NeuralSDETrainer(loss_type="qlike"|"mse")` 支持 QLIKE 波动率 loss (验证后确认不适合价格预测, 回退 MSE)

### 2. 第 3 轮 (TDD-013 multitask + 数据扩充, 部分反模式)

TDD-013 多任务 loss (0.7 MSE + 0.3 QLIKE):
- [neural_sde_model.py#L899-L944](../dreambuddy_evolution/core/neural_sde_model.py#L899) `_compute_loss` 添加 `multitask` 分支
- 4 个新测试全通过, 90 个全套测试无回归 (49 NeuralSDE + 41 deep_reasoning)

**4 实验 PoC 矩阵** (含 2 个反模式):

| 实验 | Loss | 数据 | final_loss | NeuralSDE MAE | GARCH MAE | ratio | 闸门 |
|------|------|------|------------|---------------|-----------|-------|------|
| v2 (生产最优) | MSE | 17k (1h, 2y) | 0.0073 | **269.51** | 881.14 | **0.31** | ✅ PASS |
| v3 | multitask | 88k (30m, 5y) | 72.677 | 244676 | 324 | 753.87 | ❌ FAIL |
| v3b | MSE | 88k (30m, 5y) | 0.00219 | 512 | 332 | 1.54 | ❌ FAIL |
| v3c | MSE | 80k (1h, 10y) | 0.00246 | 569.76 | 844.85 | **0.67** | ✅ PASS |

### 3. 两个新反模式 (已记录认知库 VM-1791189381322, A 级)

1. **multitask loss 权重失衡**: QLIKE 分量数值 (~72) 远大于 MSE 分量 (~0.002), 0.3*QLIKE 主导优化 → 价格路径发散 (与纯 QLIKE 同症状). 权重 0.7/0.3 是经验值, 实际需基于 loss 分量尺度归一化后加权.
2. **数据频率改变导致 horizon 时长不可比**: 30m K 线 horizon=20=10h vs 1h K 线 horizon=20=20h, 直接 MAE 不可比; GARCH baseline MAE 也变 (881→332). 必须保持预测窗口时长一致.

### 4. v2 生产上线

- [scripts/train_neural_sde.py](../dreambuddy_evolution/scripts/train_neural_sde.py) `select_best_version()` 自动比对所有版本 MAE, 将最优复制为 `neural_sde_v1.pt`
- v2 (MAE=269.51) 已复制为 [neural_sde_v1.pt](../dreambuddy_evolution/data/neural_sde_v1.pt), [deep_reasoning_engine.py#L81](../dreambuddy_evolution/engines/deep_reasoning_engine.py#L81) 加载此版本
- 训练报告: `neural_sde_v1.training_report.json` (MAE=269.51, ratio=0.31, passed=True, sig_dim=15, loss_type=mse)

### 5. 数据扩充资产

新增 Binance 数据下载脚本: [scripts/download_binance_klines.py](../dreambuddy_evolution/scripts/download_binance_klines.py) (公共 API 无需 auth, 支持 symbol/interval/years 参数)
- `btc_close_10y.json` (79941 点 1h 9y, $4308 → $86417) — v3c 使用
- `btc_close_30m.json` (87598 点 30m 5y) — v3/v3b 使用 (验证为反模式, 不再用)

### 6. 统计严谨性现状修正

修正旧评估 (VM-1791180503233 2026-10-05 早期) "无 p 值/效应量/置信区间/样本外验证" 判断 — 已过时. 实际 80 次出现 p_value/effect_size/confidence_interval/walk_forward 横跨 13 文件 (gene_promotion_stats 18 次, walk_forward_validator 9 次, granger 4 次, reflexivity 7 次). 评分 5/10 → 7/10.

### 决策与遗留

- ✅ **生产模型**: v2 (MAE=269.51, ratio=0.31, 优于 GARCH 3.3x)
- ✅ **备选**: v3c (MAE=569.76, ratio=0.67, 优于 GARCH 1.48x, 大数据集)
- ❌ **放弃**: multitask loss 0.7/0.3 固定权重 (反模式)
- ⏸ **未来**: regime detection + 分 regime 训练 (解决 v3c MAE 退化根因), 或自适应 multitask 权重

### 测试统计

- NeuralSDE 相关测试: 49 个 (4 文件: test_neural_sde_optimization + test_neural_sde_forecast_history + test_path_signature_drift_net + test_neural_sde_model)
- deep_reasoning + signature: 41 个
- 总计: 90 个无回归

---

## [v1.8] - 2026-09-11 (Phase 3 链路断裂修复 — 审计发现的 3 个断裂点)

### 核心发现

Phase 3 审计发现与 Phase 4 完全相同的"写入链路断裂"反模式——模块已实现+测试全通过，但模块间数据流断裂，导致哲学逻辑链未完全闭合。

### 断裂1 — HJB lagrangian 矛盾调制从未生效（环节⑤）

- **根因**: `_value_iteration()` L268 调用 `lagrangian()` 不传 `primary_contradiction`；`_select_optimal_path` 先跑 HJB 后识别矛盾（顺序错误）
- **修复**: 
  - [hjb_solver.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/hjb_solver.py) `solve()` + `_value_iteration()` 新增 `primary_contradiction` 参数
  - `_value_iteration()` 内部调用 `lagrangian()` 时传入 `primary_contradiction`
  - `_select_optimal_path` 调整执行顺序：先识别矛盾 → 再跑 HJB 传入 `primary_contradiction`

### 断裂2 — TrendContinuationScorer 从未接入 pipeline（环节③）

- **根因**: TrendContinuationScorer 模块完整+11测试通过，但 `evolution_pipeline.py` 中无任何调用，`continuation_score` 恒为 0.5
- **修复**: `_select_optimal_path` 在矛盾识别后调用 `TrendContinuationScorer.score()`，为每个路径填充 `continuation_score`/`cause_score`/`effort_result` 字段

### 断裂3 — ContradictionFeedback 回流未闭环（环节④）

- **根因**: `get_feedback()` 的 `adjust_weight({}, outcome)` 传空 dict 而非实际 primary_contradiction；回流结果无人消费
- **修复**: 
  - `_select_optimal_path` 存储识别结果到 `self._last_primary_contradiction`
  - `get_feedback()` 传入 `self._last_primary_contradiction` 而非空 dict
  - 存储 `self._contradiction_weight_factor` 供下次 `identify()` 使用（闭环）

### 测试统计

- 总测试文件：62 个（+3 新增测试类）
- 总测试用例：812 个（+7 新增）
- 全部通过

### 哲学逻辑链修复效果（修正后）

| 环节 | v1.6 声称 | 实际审计 | v1.8 修复后 |
|:---|:---:|:---:|:---:|
| ③ 趋势延续性 | 80% | 40%（空壳） | **80%** |
| ④ 验证回流 | 75% | 50%（半闭环） | **75%** |
| ⑤ 最小阻力 | 90% | 70%（断裂） | **90%** |

---

## [v1.7] - 2026-09-11 (Phase 4 市场理解补齐 — 三个写入链路打通)

### 核心发现

Phase 4 的三个子任务模块已有基础实现，但**写入链路断裂**——模块只读返回结果，从未写回消费方状态，导致功能空壳。本次修复打通三个数据写入链路。

### Gap 2 — RegimeClassifier 写回战略层状态

- **SubSystemBridge**: 新增 `set_btc_regime(regime, cls)` + `attach_trader(trader)` 方法
- **KlineEventHandler**: AGI 增强点 E 输出 `agi_btc_regime` 后写回战略层 shadow 状态（仅非 NEUTRAL）
- **polling_trader**: 创建 KlineEventHandler 后注入 trader 引用到 bridge
- **关键设计**: NEUTRAL 不写回（避免覆盖真实值），写入 `_five_domain_state_shadow.btc_regime[cls]`
- 7 个 TDD 测试（新建 `test_subsystem_bridge_btc_regime.py`）

### Gap 1 — PatternDetector 接入 BCRM2.0 技术评估

- **entry_signal_governor**: `compute_bcrm_entry_weight_factor()` 新增 `pattern_factor: float | None = None` 可选参数
- **降权逻辑**: `_apply_pf()` 对非 veto 决策应用形态因子降权，头肩顶看跌+evo_dir=LONG 时 `weight_factor = max(0.3, base * (1 - abs(pf) * 0.3))`
- **KlineEventHandler**: 存储 `_last_agi_pattern` 供 `_evolution_build_position` 读取
- **polling_trader**: 从 `self._kline_handler._last_agi_pattern` 提取 pattern_factor 传入
- **向后兼容**: 默认 0.0/None 等价旧行为
- 6 个 TDD 测试（扩展 `test_evolution_entry_bcrm_soft_weight.py` Group 4）

### Gap 3 — 三因子共振做空模块

- **ThreeFactorShortDetector**（新建 `three_factor_short.py`）: 头肩顶看跌 + BTC regime=WEAK + ETF 流出三因子全满足时允许 SHORT_BAN 豁免
- **三因子条件**: `pattern_factor <= -0.5` + `btc_regime == "WEAK"` + `etf_flow_norm < -0.1`
- **polling_trader**: 五维状态读取前调用 detector 写入 `_fds.three_factor_short_signal["crypto_usdt"]`
- **安全侧 FAIL-OPEN**: 任一因子缺失/异常 → False（维持 SHORT_BAN 铁律，保守侧）
- **受 `enable_three_factor_short` 开关控制**
- 8 个 TDD 测试（新建 `test_three_factor_short.py`）

### 测试统计

- 总测试文件：59 个（+3 新增）
- 总测试用例：776 个（+21 新增）
- 全部通过

---

## [v1.6] - 2026-09-11 (Phase 3 主要矛盾识别 + 最小阻力路径设计落地)

### 新增 — Phase 3.1 PrimaryContradictionIdentifier

修复 L3 路径计算层哲学断裂：从"所有矛盾平均化下求最小阻力"升级为"识别主要矛盾→主要矛盾下调制阻力→最小阻力路径"。

- **PrimaryContradictionIdentifier**: 三步法主要矛盾识别器（共振检测→冲突裁决→主导性评估）
- **共振检测**: 多路径方向一致度，矛盾论§矛盾主要方面量化
- **冲突裁决**: 4维评分法（力量对比+时间紧迫性+证据一致性+市场影响权重），对齐[矛盾分析法.md](../../2-KNOWLEDGE/3-THEORY/矛盾分析法.md) §三 Step2
- **主导性评估**: Wyckoff Cause/Effect + Effort/Result + Minervini 趋势模板增强矛盾强度
- **8 维矛盾映射**: C1-C8 → 6 路径来源（bdsm/trend_following/bcrm/strategic/deep_reasoning/synthesized/l2_gene）
- HC-AGI-18: 异常 FAIL-OPEN 返回 neutral 兜底
- HC-AGI-23: 至少 2 路径才做矛盾分析
- 10 个 TDD 测试

### 新增 — Phase 3.2 TrendContinuationScorer

- **TrendContinuationScorer**: Minervini SEPA 8 条件趋势模板 + VCP 波动率收缩 + Wyckoff 因果/量价
- **趋势模板**: price>ma150/ma200, ma150>ma200, ma200 上升, ma50>ma150/ma200, 52 周区间
- **VCP**: T2/T1 ≤ 0.75 → 1.0，线性衰减至 0.0
- **Cause**: (consolidation_bars - 10) / 50 标准化
- **Effort/Result**: 量价同向 → 0.8，背离 → 0.3
- HC-AGI-20: 字段缺失取 0.5 中性兜底
- 11 个 TDD 测试

### 扩展 — Phase 3.3 lagrangian 矛盾强度调制

- **lagrangian() 新增 primary_contradiction 参数**: 向后兼容（不传则不调制）
- **对齐主要矛盾**: L × (1 - 0.3×strength) 阻力降低
- **逆向主要矛盾**: L × (1 + 0.5×strength) 阻力升高（重心原则）
- HC-AGI-19: 调制后 L ≥ 0.001 下限保护
- 7 个 TDD 测试（扩展 test_hjb_variational_solver.py）

### 扩展 — Phase 3.4 _select_optimal_path 集成

- **评分公式 v3.0**: base_score × HJB增强 × 矛盾强度增强 × 趋势延续性增强
- **矛盾强度增强**: 对齐加分 ×(1+0.2×strength)，逆向减分 ×(1-0.3×strength)
- **趋势延续性增强**: ×(0.8+0.4×cont)
- **新增开关**: enable_contradiction_identifier / enable_trend_continuation / enable_contradiction_feedback（默认 True）
- **向后兼容**: market_data 可选参数，开关全关等价 v1.5
- 5 个 TDD 测试（扩展 test_evolution_pipeline.py）

### 新增 — Phase 3.5 验证回流闭环

- **ContradictionFeedback**: 验证结果回流调整矛盾权重
- **成功升级**: weight_factor = 1.0 + 0.1×min(1, n_trials/10)
- **失败降级**: weight_factor = max(0.3, 1.0 - 0.2×fail_streak)
- HC-AGI-22: weight_factor ∈ [0.3, 1.5]
- 7 个 TDD 测试

### 哲学逻辑链修复效果

| 环节 | v1.5 实现度 | v1.6 实现度 | 修复方式 |
|:---|:---:|:---:|:---|
| ① 多路径=多矛盾 | 85% | 90% | 路径增加矛盾维度标签 |
| ② 识别主要矛盾 | 30% | **85%** | PrimaryContradictionIdentifier 三步法 |
| ③ 趋势延续性 | 40% | **80%** | TrendContinuationScorer 回流 |
| ④ 回测+小仓验证 | 50% | **75%** | ContradictionFeedback 回流 |
| ⑤ 最小阻力计算 | 70% | **90%** | lagrangian 矛盾调制 |

### 测试统计

- 总测试文件：56 个（+3 新增）
- 总测试用例：755 个（+40 新增）
- 全部通过

---

## [v1.5] - 2026-09-11 (L3 HJB/变分法最优路径求解器 + 哲学差距分析)

### 新增 — Phase 2.6 HJB/变分法最优路径求解器

架构图要求 L3 路径计算层包含"HJB/变分法"最优路径求解，原实现为简化 argmin。本次实现真正的 HJB PDE 数值求解器 + 变分法欧拉-拉格朗日路径优化器。

- **HJBPathSolver**: 离散化 HJB PDE 逆向动态规划，求解值函数 V(p,t) + 最优策略 π*(p,t)，终端条件 V[:,T]=0，GBM 转移概率高斯窗 ±2σ
- **VariationalPathOptimizer**: 蒙特卡洛路径集合上欧拉-拉格朗日梯度下降，compute_action 严格复用 PathIntegralEngine 公式
- **solve_optimal_path 三级降级链**: HJB → 变分法 → argmin（HC-AGI-17）
- **新增硬约束**: HC-AGI-15（网格≥32×16）、HC-AGI-16（收敛1e-6≥3轮）、HC-AGI-17（异常强制降级）
- **新增 AGI 开关**: `enable_hjb_solver` + `enable_variational_opt`（默认 True）
- **DeepReasoningEngine 集成**: `find_min_resistance_path` 优先 HJB/变分法，FAIL-OPEN 降级 argmin
- **EvolutionPipeline 集成**: `_select_optimal_path` 注入 HJB 值函数（30% 权重调整 score）
- 23 个 TDD 测试，715 全量测试 0 失败

### 分析 — L3 哲学逻辑链差距（"主要矛盾→阻力最小"）

从哲学角度深度评估"最优路径=发现主要矛盾→阻力最小"逻辑链的实现程度：

| 环节 | 哲学要求 | 实现度 | 核心差距 |
|:---|:---|:---:|:---|
| ①多路径=多矛盾分析 | 6种路径来源对应6类矛盾 | 85% | 路径间并行收集，无对抗/共振分析 |
| ②识别主要矛盾 | 矛盾间对抗→主导者 | **30%** | **核心断裂**：独立评分取最高，非矛盾间比较识别主导者 |
| ③趋势延续性 | 延续性信号回流路径层 | 40% | trend_strength/ADX 在数据层计算但未回流路径发现层 |
| ④回测+小仓验证 | 验证结果回流确认矛盾 | 50% | ShadowRL/Counterfactual 验证后未回流闭环 |
| ⑤最小阻力计算 | 主要矛盾内求阻力最小 | 70% | HJB 的 Lagrangian 未融入矛盾强度调制 |

**核心结论**: 数学算法层已完备，但哲学意图层存在核心断裂 — 当前是"所有矛盾平均化下求最小阻力"，不是"识别出的主要矛盾下求最小阻力"。

**完善方向**（详见 SPEC-主要矛盾识别与最小阻力路径设计.md）：
1. 新增 `_identify_primary_contradiction()` 步骤：共振检测 + 冲突裁决 + 主导性评估
2. HJB `lagrangian()` 接受矛盾强度调制：主要矛盾方向阻力降低，次要方向阻力升高
3. 趋势延续性信号作为路径 `continuation_score` 字段回流
4. 小仓验证结果回流调整矛盾权重形成闭环

### 测试统计

- 总测试文件：53 个
- 总测试用例：715 个
- 全部通过

---

## [v1.4] - 2026-09-11 (P2+P3 接入)

### 修复 — P2 CBR 系统扩展（形态案例接入）

删除新建的 `case_library.py`，改为扩展现有 CBR 系统（11-易经推理系统/scripts/memory_l4/），统一交易案例归属。

- **CBRCase 新增字段**: `pattern`（价格形态）+ `case_type`（trade/pattern），`to_feature_dict` 同步更新
- **CBRQuery 新增字段**: `pattern`（查询形态特征）
- **相似度权重**: `DEFAULT_CASE_SIM_WEIGHTS` 新增 `pattern: 0.15`；`sim_funcs` 新增 `CategoricalSimilarity` 形态精确匹配
- **regime_gate TOP_DROP 接入 CBR**: 检测到头肩顶时检索历史形态案例（FAIL-OPEN），结果注入 `cbr_context`
- **删除 case_library.py**: 统一归 CBR，避免平行库
- 7 个 TDD 测试（test_p2_cbr_extension.py）

### 修复 — P3 AGI 模块懒初始化接入 pipeline

之前 10 个 AGI 模块（causal_engine/signature_engine/path_integral 等）已完整实现（508-808 行），但未接入 pipeline。新增 5 个懒初始化方法到 `evolution_pipeline.py`：

- **CausalEngine 懒初始化**: `_get_causal_engine()` — Phase 2 因果推断
- **SignatureEngine 懒初始化**: `_get_signature_engine()` — Phase 2.5 签名方法
- **PathIntegralEngine 懒初始化**: `_get_path_integral()` — Phase 2.5 路径积分
- **UncertaintyQuantifier 懒初始化**: `_get_uncertainty_quantifier()` — Phase 5 不确定性量化
- **MetaCognitionGate 懒初始化**: `_get_meta_cognition_gate()` — Phase 5 元认知门
- 所有模块 FAIL-OPEN：异常返回 None，不阻塞交易
- 6 个 TDD 测试（test_p3_agi_pipeline.py）

### 四系统统一关系

```
知识库(Markdown) → knowledge_to_gene → 基因库(JSON)
                                              ↓
                                         FTC 组合 → 开仓
                                              ↓
                                    CBR 记录案例(含形态案例)
                                              ↓
                                    CS 评分(0.4·d* + 0.3·ESS + 0.3·CBR)
                                              ↓
认知系统(MCP) ← recall/record/verify（开发经验，独立闭环）
```

### 测试统计

- 总测试文件：52 个
- 总测试用例：692 个
- 全部通过

---

## [v1.3] - 2026-09-11 (P0+P1 接入)

### 修复 — P0 已实现模块接入实盘链路

之前 RegimeGateSwitch、TrendFollowingEngine、GridTradingEngine、ShadowRLTrainer 四个模块都已实现且测试通过，但 `evolution_pipeline.py` 中没有 import 它们——策略引擎和学习闭环都是空转状态。

- **RegimeGateSwitch 接入 pipeline**: `evolution_pipeline.__init__` 初始化 `_regime_gate`；`_discover_paths` 新增 regime 路由路径（TREND→trend_following, RANGE→grid_trading, CRISIS→pause）
- **TrendFollowingEngine 路由接入**: TREND regime 时 `_discover_paths` 添加 trend_following 路径
- **GridTradingEngine 路由接入**: RANGE regime 时 `_discover_paths` 添加 grid_trading 路径
- **ShadowRLTrainer 接入**: `__init__` 初始化 `shadow_rl_trainer` 实例（FAIL-OPEN）
- **run_symbol 返回 regime**: 新增 regime 检测，返回结果新增 `regime` 字段
- 8 个 TDD 测试（test_pipeline_integration.py）

### 修复 — P1 PatternDetector + weight 接入

- **PatternDetector 接入 regime_gate**: `detect_regime` 新增 `klines` 参数，头肩顶 confidence≥0.5 → 返回 `TOP_DROP`；`route_strategy` 新增 TOP_DROP → `pattern_short` 做空信号
- **基因 weight 接入 shadow_backtest**: 新增 `load_gene_weight()` / `calc_weighted_pnl()` / `should_trade()`；weight=0 跳过交易；shadow JSON 和汇总新增 `weighted_pnl_pct` + `weight` 字段
- 6 个 TDD 测试（test_p1_integration.py）

### 测试统计

- 总测试文件：50 个
- 总测试用例：679 个
- 全部通过

---

## [v1.2] - 2026-09-11

### 新增 — 趋势跟踪+正金字塔加仓引擎

- **`engines/trend_following/trend_following_engine.py`** 趋势跟踪引擎（海龟规则）
  - `DonchianChannel` — 20/55 日通道突破信号
  - `ATRStopCalculator` — 2×ATR 止损，4%~15% 上下限保护（HC-TF-01）
  - `PyramidingPositionSizer` — 正金字塔加仓，最多 4 个 Unit，每 0.5N 加仓 1 Unit（HC-TF-02）
  - `TrendExitRule` — 2N 止损或反向突破离场
  - 10 个 TDD 测试全部通过

### 新增 — 网格交易引擎

- **`engines/grid_trading/grid_trading_engine.py`** 网格交易引擎（ATR 自适应间距）
  - `GridParameterCalculator` — ATR×乘数计算网格间距，单格预算比例
  - `GridRiskGate` — 8% 硬止损，趋势市暂停网格（HC-TF-05）
  - 8 个 TDD 测试全部通过

### 新增 — RegimeGateSwitch 市场状态路由

- **`engines/regime_gate.py`** 市场状态路由闸门
  - `detect_regime()` — ADX + 波动率比率 → TREND/RANGE/CRISIS（HC-TF-03）
  - `route_strategy()` — TREND→趋势跟踪，RANGE→V15+网格，CRISIS→暂停（HC-TF-07 FAIL-OPEN）
  - 8 个 TDD 测试全部通过

### 新增 — ShadowRL 训练闭环（Phase 1 AGI 完成）

- **`core/shadow_rl_trainer.py`** 从骨架升级为完整训练器
  - 新增 `SimplePolicy` 类 — REINFORCE policy gradient（纯 numpy，不依赖 finrl）
  - `train_policy()` — 从骨架升级为真实训练，支持 `epochs` + `gene_id` 参数
  - `predict()` — 状态→动作概率 softmax 输出
  - `act()` — 返回概率最大的离散动作
  - `fit()` — REINFORCE + baseline 策略梯度训练，返回 loss_history + episode_reward
  - 8 个新增 TDD 测试，原有 22 个测试无回归

### 新增 — 扩展回测数据

- BTC 4H K线从 600 bar 扩展到 **1500 bar**（2026-01-04 ~ 2026-09-11，8 个月）
- 影子验证样本从 1201 增至 **3104 条**（超过 ShadowRLTrainer.MIN_SAMPLES=2000 阈值）
- ShadowRL Phase3 **自动激活**（3104 ≥ 2000）
- 5 个基因已 promote（CD-ATR-EXPANDING, CD-KNOW-ICT-ORDERBLOCK, CD-NECKLINE-BREAK, CD-KNOW-HEAD-SHOULDERS, CD-KNOW-MOMENTUM-BREAK）

### 新增 — 双向回测 + 动态方向

- `shadow_backtest.py` 支持双向交易（long + short）
- Donchian 突破根据突破方向动态选择多空（上突破做多/下突破做空）
- ATR 扩张 + ADX 趋势根据 SMA20/+DI/-DI 动态选择方向
- P0~P3 优化：方向动态化→权重调整→新信号→ADX 阈值

### 新增 — 新基因

| 基因 | 类型 | 说明 |
|:---|:---|:---|
| CD-DONCHIAN-20-BREAK | condition | 20 日通道突破 |
| CD-DONCHIAN-55-BREAK | condition | 55 日通道突破 |
| CD-DONCHIAN-10-BREAK | condition | 10 日短期突破 |
| CD-ATR-EXPANDING | condition | ATR 波动率扩张 |
| CD-ADX-GT25-TREND | condition | ADX>25 趋势识别 |
| CD-ADX-LT25-RANGE | condition | ADX<25 震荡识别 |
| CD-BOLL-WIDTH-NARROW | condition | 布林带收窄 |
| CD-NECKLINE-BREAK | condition | 颈线跌破做空 |

### 新增 — AGI 评估报告

- `SPEC-AGI升级蓝图.md` 与行业对比评估完成
- 理论架构领先（签名+路径积分+因果+Neural SDE 独一无二）
- Phase 1 完成度 100%（ShadowRL 训练闭环已落地）

### 更新 — 文档同步

- ENGINEERING_INDEX.md v1.0→v1.2：新增 15+ 引擎模块、21 个 core 模块、48 个测试文件
- TECHNICAL_DESIGN.md v1.1→v1.2：扩展回测结果、ShadowRL 训练闭环验证
- 技术债务更新：ShadowRL Phase3 从"未激活"标记为"已解决"

### 测试统计

- 总测试文件：48 个
- 总测试用例：665 个
- 全部通过

---

## [v1.1] - 2026-09-10

### 新增 — 策略知识→基因库三层准入机制

- **TECHNICAL_DESIGN.md** 新增三层准入设计（§2.4 三层准入架构 + §3 候选基因生成 + §7 影子验证结果）
  - Layer 0 候选区：7 个经典模式 GeneCandidate JSON（Livermore/Wyckoff/Darvas/ICT/VWAP/动量/头肩）
  - Layer 1 影子验证区：N≥10 + 胜率≥50% 准入门槛，BTC 4H 600 bar 回测驱动
  - Layer 2 实盘基因库：现有 N≥100 + ESS≥0.5 门槛不变

### 新增 — 影子验证脚本

- `scripts/shadow_backtest.py` BTC 4H 回测引擎
  - 对每个候选基因逐 bar 计算模式触发 + 模拟开仓/平仓
  - 输出 JSON + JSONL 样本到 `gene_data/shadow_validation/`
  - 回测结果：7 个基因均触发，ICT OrderBlock 最有潜力（N=35, 胜率49%, PnL+0.34%）

### 新增 — 候选基因（7 个 GeneCandidate JSON）

| 基因 | 分类 | 来源文档 |
|:---|:---|:---|
| CD-KNOW-LIVERMORE-PP | trend | Livermore关键点交易法.md |
| CD-KNOW-WYCKOFF-SPRING | reversal | Wyckoff量价四阶段.md |
| CD-KNOW-DARVAS-BOX | trend | DarvasBox箱体突破.md |
| CD-KNOW-ICT-ORDERBLOCK | reversal | ICT-SmartMoney加密版.md |
| CD-KNOW-VWAP-REVERSION | reversal | VWAP均值回归策略.md |
| CD-KNOW-MOMENTUM-BREAK | momentum | 动量反转双策略.md |
| CD-KNOW-HEAD-SHOULDERS | reversal | 经典技术形态汇总.md |

### 更新 — TECHNICAL_DESIGN.md 状态确认

- RAG 热路径代码确认完好（之前误判丢失，实际 4 函数 + 3 接入点 + 2 平仓接入全部存在）
- daemon PID=75911 运行正常，今日 RAG 378 次调用零异常
- 策略知识不进 CS 公式（硬约束确认）
- 影子模式红线：影子验证区基因只记录不干预参数

---

## [v1.0] - 2026-09-07

### 新增 — 文档四件套

- **ENGINEERING_INDEX.md** v1.0：模块工程索引（目录地图/文件清单/核心流程/配置参数/测试体系）
- **TECHNICAL_DESIGN.md** v1.0：技术设计文档（四层架构/双起点触发/三层仓位/SL-TP兜底/数据管线/权重体系/稳定性证明）
- **API_SPEC.md** v1.0：接口规格文档（13个核心类/函数的完整签名+输入输出字段表）
- **CHANGELOG.md** v1.0：本文件

### 新增 — 高频进化增强（2026-09-06）

#### 双起点触发
- `engines/reflection_scanner.py` 新增 ReflectionScanner（反思学习扫描器）
  - 从系统级交易索引库（TradeIndexBuilder）统计币种历史胜率
  - `reflection_ri` 映射: win_rate 0.5→0.50, 0.6→0.56, 0.7→0.62, 1.0→0.80
  - 样本量折扣: n=1→0.72, n=2→0.85, n≥3→1.0
- `engines/kline_event_handler.py` 双起点聚合: `ri = max(ripple_ri, reflection_ri)`
  - `signal_source` 字段标记哪个起点触发

#### 三层仓位分级
- `engines/kline_event_handler.py` 三层分级替代固定 u=0.1:
  - probe(ri≥0.40, ×0.4) / standard(ri≥0.55, ×0.7) / trend(ri≥0.70, ×1.0)
  - Regime乘数: STRONG_TREND_BULL ×1.20, RANGING ×0.80, TREND_BEAR ×0.50 等

#### SL/TP 兜底
- `polling_trader.py` `_evolution_build_position` 建仓后立即设置止损止盈:
  - probe: SL=5%, TP=10%
  - standard: SL=3%, TP=6%
  - trend: SL=2%, TP=4%
  - Regime调整: ranging→SL×1.3/TP×0.8, trend_up→TP×1.2

#### 系统级交易索引库
- `engines/trade_index_builder.py` 新增 TradeIndexBuilder:
  - 自动发现JSONL+SQLite交易记录源（扫描深度5层）
  - 统一字段口径，按trade_id去重
  - 索引库: `.workbuddy/trade_index/all_trades_index.jsonl`
  - 验证结果: 83笔/25币/4源

#### 50币种池 + 美股代币配额
- `adapters/coin_scanner.py` 增强:
  - US_STOCK_COINS白名单130+支美股
  - US_STOCK_RATIO=0.5 配额
  - 美股成交量门槛300K USDT（加密5M USDT）
- `polling_trader.py` 币种池合并: 基础24 + 扫描50 = 50币

### 新增 — 数据管线打通（2026-09-05）

- `adapters/data_pipeline.py` DataPipelineAdapter 统一数据管线装配器
- `adapters/okx_market.py` OKXMarketAdapter（K线+Ticker+持仓）
- `adapters/data_center.py` DataCenterAdapter（data_center.db衍生品）
- `adapters/sentiment_bridge.py` SentimentBridge（SentimentEngine桥接）
- `adapters/ess_provider.py` ESSDirectionProvider（策略基因ESS方向）
- `adapters/subsystem_bridge.py` SubSystemBridge（子交易系统信号）
- `adapters/cognitive_bridge.py` CognitiveBridge（Phase3预留接口）
- `adapters/capital_rotation.py` CapitalRotationAdapter（资金轮动检测）
- `adapters/traditional_finance.py` TraditionalFinanceBridge（Regime/Kelly/Vol）
- `adapters/ripple_provider.py` RippleDataProvider（涟漪关联币数据）
- `adapters/narrative_adapter.py` NarrativeAdapter（叙事标签适配）
- `adapters/path_library.py` PathLibrary（最优路径库）

### 新增 — FTC金融思维链层（2026-09-06）

- `adapters/ftc_orchestrator.py` FTCOrchestrator（FTC编排器）
- `adapters/ftc_executor.py` FTC执行器
- `adapters/ftc_schema.py` FTC数据模式
- `adapters/ftc_similarity.py` FTC相似度
- `adapters/ftc_combiner.py` FTC组合器
- `adapters/ftc_gene_innovation.py` FTC基因创新
- `adapters/ftc_evolution_bridge.py` FTC进化桥接
- `adapters/ftc_backtest.py` FTC回测

### 已有功能（基线）

- **L1 ResistanceVector**: 5维阻力向量计算（R_up/R_down/R_smooth/R_flow/R_reflexivity）
- **Level0 路径代价**: d* = argmin 代价方向
- **L2 StrategyGene**: 策略基因库 + ESS排序（28条件 + 16动作 + 组合库）
- **L3 ShadowRLTracker**: 影子RL样本追踪（Phase3激活gmax变异）
- **L4 BellmanVTracker**: V(s) TD(0)时序差分更新
- **RippleEngine**: 涟漪扩散引擎（龙头检测 + R1/R2/R3三层扩散）
- **ReflectionEngine**: 后验反思引擎（CS一致性 + 四维奖惩表）
- **TightCouplingOrchestrator**: 紧耦合7步闭环编排器
- **TradeSettlementBridge**: 平仓反思桥接器
- **Modifiers**: 三修饰子（情绪/资金流/叙事）
- **EvolutionPipeline**: 四层闭环pipeline编排器
- **Weights**: 权威权重唯一源（ESS 4:4:2, R_REFL 4:3:3, CS 0.4:0.3:0.3, CM 4:3:3）

### 已知问题

- **`_mode_cache` 属性错误**: ETH/SOL 仓位（在SL/TP代码前开的仓）在SLTP sync时触发 `'PollingTrader' object has no attribute '_mode_cache'`。这是pre-existing bug，`_mode_cache` 在 `__init__` L912 初始化，但evolution仓位的SLTP sync路径可能跳过init。待修复。

---

**文档版本**: v1.4
**最后更新**: 2026-09-11
