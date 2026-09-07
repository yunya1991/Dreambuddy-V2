# 战略层力向量最小阻力方向 实现计划 v1.0
（对应 Spec v1.0 frozen：2026-08-30-strategic-force-vector-design.md）

```
计划状态：可执行（Spec 已审阅确认，用户批准落地）
创建日期：2026-08-30
总工期：6~7 工作日（含回归 + Shadow 验证期）
总任务数：17 项 TC（TDD 红绿循环），覆盖 M1~M3 三个里程碑
硬门槛：4 条铁门槛（T-G1~T-G4）= 任一不达标则阶段不通过，执行秒级回滚
```

---

## 一、执行总览与硬门槛顺序

### 1.1 三阶段里程碑

```
M1 力向量基建 + 适配层 + Kalman（2天）
 │
 ├─ Day 1 上午：force_vector/ 目录 + ForceVector dataclass + LeastResistanceAdapter
 │             + SignalEngineAdapter → TC1 力向量结构（红→绿）
 ├─ Day 1 下午：ForceVectorCalculator（五维统计 + Kalman）→ TC2 Z-score + TC3 Kalman
 ├─ Day 2 上午：FAIL-OPEN 三层防护 + TC10 样本不足回退
 └─ Day 2 下午：M1 评审 → ★T-G1 铁门槛（战略层现有测试 0 回归）
 │
 ▼ 必须 T-G1=0 回归 才允许进入 M2（否则 M1 回滚）
 │
M2 主要矛盾识别 + PCA 共振（2天）
 │
 ├─ Day 3 上午：FeatureCorrelationCalculator（IC + MI 滚动）→ TC4 IC + TC5 MI
 ├─ Day 3 下午：综合排名 + 最优权重（复用 _adaptive_weight）→ TC6 排名 + TC7 权重
 ├─ Day 4 上午：PCAResonanceAnalyzer（五维共振定强度）→ TC8 排名一致性
 └─ Day 4 下午：TC9 双窗口共振 → M2 评审 → ★T-G2 铁门槛（力向量计算 0 异常）
 │
 ▼ 必须 T-G2 通过 才允许进入 M3（否则 M2 回滚）
 │
M3 矛盾转化检测 + 映射 + Shadow 验证（2.5天 + 观察期）
 │
 ├─ Day 5 上午：ElasticityBetaCalculator → TC11 β衰减 + TC12 β放大
 ├─ Day 5 下午：ContradictionTransformDetector（复用 S3/S4）→ TC13 转化检测
 │             + TC16 S3 数据质量预警 + TC17 S4 辅助佐证
 ├─ Day 6 上午：RegimeConditionalCalibrator → TC14 阶段依赖性
 ├─ Day 6 下午：CycleComparator + StrategicMapper → TC15 决策影响
 └─ Day 7：★T-G3 全局回归 + ★T-G4 Shadow 字节等价 → 开启 enable_force_vector
 │
 ▼ Shadow 观察 7 天（JSONL 审计，不注入生产决策）
 └─ 观察期结束 → 评审通过 = 力向量体系落地
```

### 1.2 四条不可逾越硬门槛（任一不达标 = 阶段不通过 → 回滚）

| # | 门槛 | 触发阶段 | 验收命令 | 失败回滚 |
|---|---|---|---|---|
| T-G1 | M1 战略层回归：`test_five_domain_feature_computer.py` + `tests/test_*.py` **0 回归** | M1 结束前 | `cd 11-易经推理系统/scripts/memory_l4 && python -m pytest test_five_domain_feature_computer.py tests/ -q 2>&1 \| tail -5` | `enable_force_vector=False`（默认关，回归 0 差异） |
| T-G2 | M2 力向量计算健壮性：TC1~TC9 **9/9 全绿**，无未捕获异常 | M2 结束前 | `python -m pytest tests/test_force_vector_*.py -v 2>&1 \| tail -10` | 暂停 M3，修复 M2 计算缺陷 |
| T-G3 | M3 全局回归：力向量模块加入后战略层全库 **0 回归** | M3 结束前 | `cd 11-易经推理系统/scripts/memory_l4 && python -m pytest test_five_domain_feature_computer.py tests/ -q 2>&1 \| tail -5` | 逐模块 enable=False → 定位问题模块 → 修复 |
| T-G4 | Shadow 字节等价：`enable_force_vector=True` vs `False`，war_state/cap/mask **完全一致** | M3 Shadow 期 | `python -m pytest tests/test_force_vector_shadow_equivalence.py -v` 看 `assert diff == {}` | `enable_force_vector=False`，力向量仅做 Shadow 输出不注入决策 |

### 1.3 TDD 执行铁则（每子任务必遵守）

```
每子任务固定三步：
  ① 先写测试代码 → 运行 → 确认测试 FAIL（红）
  ② 再写实现代码 → 运行 → 确认该测试 PASS（绿）
  ③ 不得修改既有测试用例以逃避失败（test_five_domain_feature_computer.py 等基准测试）

例外：仅当有强证据证明测试本身 fundamentally flawed/过时，才允许修改，需先论证理由。
```

### 1.4 秒级回滚速查

```bash
# 一键完全禁用力向量（不影响任何现有逻辑）
export ENABLE_FORCE_VECTOR=0
# 或在代码中默认 enable_force_vector=False（已是默认值）

# 完全清除力向量代码（极端回滚）
rm -rf "11-易经推理系统/scripts/memory_l4/force_vector/"
rm -f "11-易经推理系统/scripts/memory_l4/tests/test_force_vector_*.py"
# five_domain_feature_computer.py 无改动（力向量是纯新增旁路），无需恢复
```

---

## 二、代码目录结构

```
11-易经推理系统/scripts/memory_l4/
├── five_domain_feature_computer.py    # 现有五计庙算（不改动，力向量旁路接入）
├── force_vector/                       # ★新增力向量模块目录
│   ├── __init__.py                     # 模块导出
│   ├── models.py                       # ForceVector / FeatureCorrelation / PrimaryContradiction / PCAResonance / CycleComparison / ElasticityBeta / ContradictionTransform / StrategicLayerOutput
│   ├── adapters.py                     # LeastResistanceAdapter + SignalEngineAdapter（复用 9-基本面）
│   ├── force_vector_calculator.py     # M1：五维统计 + Kalman 平滑
│   ├── feature_correlation_calculator.py  # M2：IC + MI + 排名 + 权重
│   ├── pca_resonance_analyzer.py      # M2：PCA 五维共振分析
│   ├── elasticity_beta_calculator.py  # M3：弹性系数β
│   ├── contradiction_transform_detector.py  # M3：6类转化条件（复用 S3/S4）
│   ├── regime_conditional_calibrator.py     # M3：CBR 条件期望
│   ├── cycle_comparator.py            # M3：7d+30d 双窗口
│   └── strategic_mapper.py            # M3：映射 war_state/cap/mask + force_vectors
└── tests/
    ├── test_force_vector_models.py        # TC1
    ├── test_force_vector_calculator.py    # TC2, TC3, TC10
    ├── test_feature_correlation.py        # TC4, TC5, TC6, TC7
    ├── test_pca_resonance.py              # TC8, TC9
    ├── test_elasticity_beta.py            # TC11, TC12
    ├── test_contradiction_transform.py    # TC13, TC16, TC17
    ├── test_regime_calibrator.py          # TC14
    ├── test_strategic_mapper.py           # TC15
    └── test_force_vector_shadow_equivalence.py  # T-G4
```

---

## 三、M1 详细任务：力向量基建 + 适配层 + Kalman

### 3.1 关键适配发现（Spec 对齐）

| Spec 定义 | 实际代码 | 适配方案 |
|---|---|---|
| `ForceVector.direction: float [-1,+1]` | `compute_resistance_3d()` 返回 `direction` 是字符串 "up"/"down"/"neutral" | `LeastResistanceAdapter` 转换：`direction_score`(float) → ForceVector.direction；字符串 direction 仅做调试标注 |
| `ForceVector.magnitude: float` | `compute_resistance_3d()` 返回 `direction_score` = raw_score | `direction_score` 的绝对值 → magnitude |
| `confidence` 复用 `_bayesian_confidence` | 需 `predictions>=10` 才生效，否则返回 raw_confidence | 适配器传入 raw_confidence，不足样本时透明降级 |
| `_adaptive_weight` 复用 | 需 `predictions>=5` 才生效 | 同上，不足时返回 base_weight |

### 3.2 任务分解

#### T1.1 force_vector/models.py — 数据结构定义（TC1）

**测试先行**：`test_force_vector_models.py::TC1`
```python
# 断言：ForceVector 含 10 字段，类型范围正确
fv = ForceVector(dimension="dao", direction=0.5, magnitude=0.8, confidence=0.7,
                 velocity=0.1, acceleration=0.05, kalman_direction=0.48,
                 kalman_magnitude=0.78, dominant=True, weight=0.3)
assert -1.0 <= fv.direction <= 1.0
assert 0.0 <= fv.magnitude
assert 0.0 <= fv.confidence <= 1.0
# 同理验证 FeatureCorrelation / PrimaryContradiction / PCAResonance / CycleComparison /
# ElasticityBeta / ContradictionTransform / StrategicLayerOutput
```

**实现**：`models.py` 定义 8 个 @dataclass（按 Spec §二/三/四 结构）

#### T1.2 force_vector/adapters.py — 复用适配层

**测试**：`test_force_vector_calculator.py::test_adapter`
```python
# 验证 LeastResistanceAdapter 正确转换
r3d = compute_resistance_3d(0.5, [0.1, 0.2, 0.3])
adapter = LeastResistanceAdapter()
fv_fields = adapter.to_force_vector_fields("dao", r3d, raw_confidence=0.6)
assert isinstance(fv_fields.direction, float)  # 非 "up" 字符串
assert abs(fv_fields.direction - 0.5) < 0.01  # direction_score 映射
# 验证 SignalEngineAdapter
se = SignalEngine()
conf = SignalEngineAdapter().bayesian_confidence(se, "flow", 0.6)
assert 0.0 <= conf <= 1.0
```

**实现**：`adapters.py`
- `LeastResistanceAdapter.to_force_vector_fields(dim, r3d_dict, raw_confidence)` → ForceVector 核心字段
- `SignalEngineAdapter.bayesian_confidence(signal_engine, module_name, raw_conf)` → float
- `SignalEngineAdapter.adaptive_weight(signal_engine, module_name)` → float

#### T1.3 force_vector/force_vector_calculator.py — 五维统计 + Kalman（TC2, TC3）

**测试 TC2**：Z-score 统计计算
```python
# 喂入 30 天稳定币增速递增数据
data = [100 + i * 0.5 for i in range(30)]
calc = ForceVectorCalculator()
result = calc.compute_dao_dimension(data)
assert result.direction > 0  # 递增→正向
assert 0 <= result.magnitude <= 2.0
```

**测试 TC3**：Kalman 平滑
```python
# 原始 direction 有单日跳变
directions = [0.1, 0.1, 0.1, 0.8, 0.1, 0.1]  # 第4天跳变
smoothed = calc.kalman_smooth(directions)
# kalman_direction 跳变幅度 < 50% 原始
assert abs(smoothed[3] - 0.1) < abs(0.8 - 0.1) * 0.5
```

**实现**：`force_vector_calculator.py`
- `compute_dao_dimension(data)` — Z-score + OLS 斜率
- `compute_tian_dimension(data)` — 条件期望 + 分位数
- `compute_di_dimension(data)` — 百分位 + MA 一致性
- `compute_jiang_dimension(data)` — Sharpe + 偏度
- `compute_fa_dimension(data)` — IC + IR
- `kalman_smooth(directions, magnitudes)` — Kalman Filter 平滑
- `compute_all(dao_data, tian_data, di_data, jiang_data, fa_data)` → Dict[str, ForceVector]

#### T1.4 FAIL-OPEN 三层防护（TC10）

**测试 TC10**：
```python
# 样本<7天
calc = ForceVectorCalculator()
result = calc.compute_all(dao_data=[0.1]*5, ...)  # 不足7天
assert result is None  # 回退
# war_state 走现有规则打分（验证不抛异常）
```

**实现**：在 `compute_all` 入口检查样本数 <7 → return None

---

## 四、M2 详细任务：主要矛盾识别 + PCA 共振

### 4.1 任务分解

#### T2.1 feature_correlation_calculator.py — IC + MI（TC4, TC5）

**测试 TC4**：IC 计算
```python
# 构造特征与价格正相关 30 天数据
features = np.arange(30, dtype=float)
returns = features * 0.1 + np.random.normal(0, 0.01, 30)  # 正相关
calc = FeatureCorrelationCalculator()
ic = calc.compute_ic(features, returns)
assert ic > 0  # 正相关→IC>0
# 负相关
returns_neg = -features * 0.1
ic_neg = calc.compute_ic(features, returns_neg)
assert ic_neg < 0
```

**测试 TC5**：MI 计算
```python
# 构造非线性关系（阈值效应）
features = np.random.rand(100)
returns = np.where(features > 0.5, 1.0, -1.0)  # 阈值效应
calc = FeatureCorrelationCalculator()
mi = calc.compute_mi_normalized(features, returns)
assert mi > 0.3  # 非线性关联
ic = calc.compute_ic(features, returns)
assert abs(ic) < 0.2  # 但 IC 低（线性不显著）
```

**实现**：`feature_correlation_calculator.py`
- `compute_ic(feature, returns)` — Spearman 秩相关
- `compute_mi_normalized(feature, returns, n_bins=10)` — 互信息（等频分箱归一化）
- `compute_combined_score(ic, mi, w_linear=0.6, w_nonlinear=0.4)` — 综合关联度

#### T2.2 综合排名 + 最优权重（TC6, TC7）

**测试 TC6**：综合排名
```python
# 构造 5 个特征不同 IC/MI
correlations = [
    FeatureCorrelation("f1", "dao", ic=0.15, mi=0.3),
    FeatureCorrelation("f2", "tian", ic=0.08, mi=0.5),
    ...
]
calc = FeatureCorrelationCalculator()
ranked = calc.rank_features(correlations)
assert ranked[0].feature_name == "f1"  # IC 最高
assert ranked[0].rank == 1
```

**测试 TC7**：最优权重
```python
weights = calc.compute_optimal_weights(correlations, alpha=1.0)
assert abs(sum(weights) - 1.0) < 0.001  # 归一化
assert all(0.02 <= w <= 0.40 for w in weights)  # 约束
# Beta 融合后仍满足约束
se = SignalEngine()
fused = calc.fuse_with_beta(weights, se, module_names)
assert all(0.02 <= w <= 0.40 for w in fused.values())
```

**实现**：
- `rank_features(correlations)` — 按 combined_score 降序排名
- `compute_optimal_weights(correlations, alpha=1.0)` — |IC|^α 归一化 + [0.02, 0.40] 约束
- `fuse_with_beta(ic_weights, signal_engine, module_names)` — 复用 `_adaptive_weight()` L67-89

#### T2.3 pca_resonance_analyzer.py — PCA 五维共振（TC8, TC9）

**测试 TC8**：排名一致性检测
```python
# 连续 2 天排名 Spearman > 0.8
ranks_t1 = ["f1", "f2", "f3", "f4", "f5"]
ranks_t2 = ["f1", "f2", "f3", "f5", "f4"]  # 微调
analyzer = PCAResonanceAnalyzer()
stability = analyzer.compute_rank_stability(ranks_t1, ranks_t2)
assert stability > 0.8  # 稳定
# top-1 切换
ranks_t3 = ["f2", "f1", "f3", "f4", "f5"]  # top-1 变了
shift = analyzer.detect_top1_shift(ranks_t1, ranks_t3)
assert shift == True
```

**测试 TC9**：双窗口共振
```python
dir_7d = 0.5   # 短窗口正向
dir_30d = 0.4  # 长窗口正向
comp = CycleComparator()
result = comp.compare(dir_7d, dir_30d, mag_7d=0.6, mag_30d=0.5)
assert result.resonance_state == "resonance"
assert abs(result.strength_multiplier - 1.2) < 0.01
# 反向
result_rev = comp.compare(0.5, -0.4, 0.6, 0.5)
assert result_rev.resonance_state == "divergence"
assert abs(result_rev.strength_multiplier - 0.6) < 0.01
```

**实现**：
- `compute_resonance(five_dim_powers, dominant_dim)` — PCA 分解 + sign_alignment + strength_coefficient
- `compute_rank_stability(ranks_t, ranks_t_prev)` — Spearman 秩相关
- `detect_top1_shift(ranks_t, ranks_t_prev)` — top-1 切换检测

---

## 五、M3 详细任务：矛盾转化检测 + 映射 + Shadow

### 5.1 任务分解

#### T3.1 elasticity_beta_calculator.py（TC11, TC12）

**测试 TC11**：β衰减
```python
# 构造 β_7d/β_30d < 0.5 持续3天
price_changes = [0.01, 0.005, 0.002]  # 7天价格变化率递减
force_changes = [0.05, 0.05, 0.05]    # 力向量不变
calc = ElasticityBetaCalculator()
result = calc.compute(price_changes_7d, force_changes_7d,
                      price_changes_30d, force_changes_30d)
assert result.decay_signal == True
assert result.decay_days >= 3
```

**测试 TC12**：β放大（对称构造）

**实现**：`elasticity_beta_calculator.py`
- `compute(price_7d, force_7d, price_30d, force_30d)` — OLS 回归 ΔPrice ~ ΔForce
- 持续3天计数衰减/放大

#### T3.2 contradiction_transform_detector.py — 复用 S3/S4（TC13, TC16, TC17）

**测试 TC13**：矛盾转化检测
```python
# 3个转化条件同时触发
detector = ContradictionTransformDetector()
result = detector.detect(
    elasticity_beta=ElasticityBeta(beta_ratio=0.3, decay_signal=True, ...),
    rank_shift=True,
    resonance_break=True,
    cbr_divergence=False,
    s3_pass_rate=0.8,  # 正常
)
assert result.transforming == True
assert abs(result.confidence - 0.50) < 0.01  # 3/6
```

**测试 TC16**：S3 数据质量预警
```python
# S3 pass_rate < 0.7 持续3天
result = detector.detect(..., s3_pass_rate=0.6, s3_low_days=3)
assert result.transform_type == "data_quality_warning"
assert abs(result.data_quality_factor - 0.7) < 0.01
```

**测试 TC17**：S4 辅助佐证
```python
# S4 crr>0.3 且维度主导切换已触发 → 置信度权重 ×1.2
result = detector.detect(..., rank_shift=True, s4_crr=0.4, s4_mr=0.8)
assert result.transforming == True
# 验证置信度被 ×1.2 提升
```

**实现**：`contradiction_transform_detector.py`
- `detect(elasticity_beta, rank_shift, resonance_break, cbr_divergence, s3_pass_rate, s3_low_days, s4_crr, s4_mr)` → ContradictionTransform
- 6 类条件监控 + 置信度聚合
- S3 pass_rate 降级 + S4 crr/mr 辅助佐证
- **复用 S3**：调用 `news_contract_validator.validate_batch()` 获取 pass_rate
- **复用 S4**：调用 `event_mapping_engine.map_event_type()` 统计 crr/mr（参考 `_fd_S_dao_boost` L974-1003）

#### T3.3 regime_conditional_calibrator.py（TC14）

**测试 TC14**：
```python
# E[r|event,regime_current] 与 E[r|event,all] 方向相反
calibrator = RegimeConditionalCalibrator()
adj = calibrator.compute_adjustment(
    e_r_current=+2.3, e_r_all=-1.0  # 方向相反
)
assert abs(adj) < 0.3  # adjustment_factor < 0.3
# 力向量强度 ×0.5
```

**实现**：`regime_conditional_calibrator.py`
- `compute_adjustment(e_r_current, e_r_all)` → float
- CBR 案例库条件期望查询

#### T3.4 cycle_comparator.py + strategic_mapper.py（TC15）

**测试 TC15**：
```python
mapper = StrategicMapper()
result = mapper.map(
    final_direction=0.5, final_magnitude=0.6,
    resonance_state="resonance",
    contradiction=ContradictionTransform(
        transforming=True, transform_type="elasticity_decay", ...)
)
assert result.war_state == "COOLDOWN"  # elasticity_decay→COOLDOWN
assert result.aggregate_position_cap_pct < 0.5 * 1.0  # cap ×0.5
assert result.allowed_style_mask["trend_follow"] == False  # 禁 trend_follow
```

**实现**：`strategic_mapper.py`
- `map(final_direction, final_magnitude, resonance_state, contradiction, ...)` → StrategicLayerOutput
- 按 Spec §四 映射表实现 war_state/cap/mask/position_mult
- 矛盾转化对决策的调整表（6 类 transform_type）

#### T3.5 Shadow 字节等价（T-G4）

**测试**：`test_force_vector_shadow_equivalence.py`
```python
# enable_force_vector=True vs False
output_on = strategic_layer.compute(..., enable_force_vector=True)
output_off = strategic_layer.compute(..., enable_force_vector=False)
# war_state/cap/mask 完全一致
assert output_on.war_state == output_off.war_state
assert output_on.aggregate_position_cap_pct == output_off.aggregate_position_cap_pct
assert output_on.allowed_style_mask == output_off.allowed_style_mask
# force_vectors 仅在开启时存在
assert output_on.force_vectors is not None
assert output_off.force_vectors is None
```

---

## 六、依赖与风险

### 6.1 外部依赖

| 依赖 | 来源 | 状态 | FAIL-OPEN |
|---|---|---|---|
| numpy | 已安装 | ✅ | - |
| scipy.stats.spearmanr | 已安装 | ✅ | - |
| sklearn MI / PCA | 需确认 | ⚠️ | 异常时回退 \|magnitude\|×confidence 权重 |
| filterpy (Kalman) | 需确认 | ⚠️ | 异常时回退原始值（跳过 Kalman） |

**Day 1 首要任务**：确认 scipy/sklearn/filterpy 可用性，缺失时先用纯 numpy 实现降级版。

### 6.2 风险与缓解

| 风险 | 等级 | 缓解 |
|---|---|---|
| compute_resistance_3d direction 字符串 vs float | 中 | LeastResistanceAdapter 适配层转换 |
| _bayesian_confidence 需 predictions>=10 | 低 | 不足时透明返回 raw_confidence |
| sklearn 不可用 | 中 | MI 用 numpy 直方图实现降级版；PCA 用 numpy SVD 实现 |
| 特征池数据不足 | 中 | <30天回退 \|magnitude\|×confidence 权重 |
| 现有测试回归 | 低 | 力向量是纯新增旁路，five_domain_feature_computer.py 无改动 |

---

## 七、字节等价保证（核心约束）

```
enable_force_vector=False（默认）
  → 力向量模块不执行
  → force_vectors=None
  → war_state/cap/mask 走现有规则打分
  → 下游字节等价"力向量不存在"

enable_force_vector=True（Shadow 模式）
  → 力向量模块执行，输出 force_vectors
  → war_state/cap/mask 仍走现有规则打分（Shadow 不注入决策）
  → force_vectors 写入 JSONL 审计日志
  → 7 天观察期后评审通过才允许注入决策
```

---

## 八、执行检查清单

- [ ] M1 Day 1：确认 scipy/sklearn/filterpy 依赖
- [ ] M1 Day 1：models.py + adapters.py + TC1 绿
- [ ] M1 Day 2：force_vector_calculator.py + TC2/TC3/TC10 绿
- [ ] M1 Day 2：★T-G1 战略层 0 回归
- [ ] M2 Day 3：feature_correlation_calculator.py + TC4/TC5 绿
- [ ] M2 Day 4：TC6/TC7/TC8/TC9 绿 + ★T-G2
- [ ] M3 Day 5：elasticity_beta + contradiction_transform + TC11~13/16/17 绿
- [ ] M3 Day 6：regime_calibrator + strategic_mapper + TC14/TC15 绿
- [ ] M3 Day 7：★T-G3 全局回归 + ★T-G4 Shadow 字节等价
- [ ] Shadow 7 天观察期 → 评审 → 落地
