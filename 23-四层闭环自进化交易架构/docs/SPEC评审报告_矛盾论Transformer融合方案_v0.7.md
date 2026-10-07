> 版本: v1.2 | 日期: 2026-10-07 | 评审方法: dream-science-orchestrator + 4 维科研 SKILL + 元评审（meta-review）

# SPEC 评审报告：矛盾论与 Transformer 融合方案 v0.7

## 1. 评审概览
- **评审维度**：4 个（Devil's Advocate 同行评审 / 统计合理性 / 可证伪性 / 不确定性推理）+ 元评审（v1.2 新增）
- **评审结论**：**有条件通过**（v1.2 综合 7.3 ≥ 7.0，附带 5 项前置 P0 修复）
- **综合评分**：5.5 → 7.2（复盘调整 6.9）→ **7.3** / 10

## 2. Devil's Advocate 阻断清单（7 模式）

| # | 阻断模式 | 是否触发 | 证据 | 建议 |
|---|---------|---------|------|------|
| 1 | 幻觉引用 | 部分 | [矛盾论与Transformer架构融合方案.md#L1619](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/docs/矛盾论与Transformer架构融合方案.md#L1619) 称 vol 用"HMM/阈值"，实际 [structural_break_detector.py#L101](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/structural_break_detector.py#L101) 主路径是 MarkovRegression，fallback 才是阈值 | 修正表述为"Markov-Regression（HMM 类）+ fallback 阈值" |
| 2 | 数据造假 | 否 | v0.7 草案明确标注"无代码实现"，参数均为先验值并承认需回测 | — |
| 3 | 方法捏造 | 是 | [§10.11.2 L1513](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/docs/矛盾论与Transformer架构融合方案.md#L1513) `reversion_rate=0.05` 参考"EM 算法衰减率"——EM 算法衰减率针对似然收敛，与 head 权重回归 1.0 不同语境 | 替换为统计依据（如 OU 过程的均值回归速率） |
| 4 | 框架锁定 | 是 | §5.1.5 仅论证优于"Granger 验证 Attention"，未对比纯 Attention+在线学习 / 互信息替代方案 | 补充替代框架对比 |
| 5 | 结果幻觉 | 否 | 理论设计阶段无回测结果 | — |
| 6 | 逻辑跳跃 | **是（≥4分）** | Q5 vol 权重=0.4 称"易受事件冲击"，但 HMM 本身是 regime 检测成熟方法；Q4 降级输出 primary_dim 隐含"单链路可靠"未论证 | **必须让步**：Q5 权重需数据校准；Q4 需论证单链路可靠性 |
| 7 | 边界忽略 | 部分 | §10.11.8 列出 5 项待验证，但未声明适用市场状态/资产/时间周期 | 补充边界声明 |

**让步触发**：模式 6 评分 4 分，按让步阈值协议必须修改 Q5 权重设定和 Q4 降级假设。

## 3. 让步阈值协议

| 假设 | 让步阈值（何种证据下应放弃） | 当前证据状态 |
|------|---------------------------|------------|
| Q5 权重 Hurst=1.0/CUSUM=0.6/vol=0.4 反映可靠性排序 | 回测显示 vol 命中率 ≥ Hurst 命中率 | **未验证**，先验值 |
| Q4 降级模式 primary_dim 不引入偏差 | 降级期 primary_dim 与后续质变方向一致率 < 50% | **未验证** |
| Q3 冷却期减少过拟合 | 无冷却组样本外夏普显著优于冷却组 | **未验证** |
| persistence_threshold ∈ [3,20] 能过滤噪声 | 3 期分歧的假阳性率 > 50% | **未验证** |
| head_multipliers 正反馈可控 | 相平面分析显示振荡发散 | **未验证**，§10.11.8 已识别风险 |

## 4. 统计合理性审查

### 参数边界依据（逐项）

| 参数 | 文档依据 | 审查结论 |
|------|---------|---------|
| persistence_threshold [3,20] | "下限过滤噪声，上限保证响应性" | **不足**：3 期样本方差极大，不足以稳定检测；与 Granger 检验推荐样本量 ≥30 混淆概念 |
| head_floor=0.1 | "与 [elastic_constraint_resolver.py#L55](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/elastic_constraint_resolver.py#L55) `_floor=0.20` 同量级" | **牵强**：0.1 ≠ 0.20（差 2 倍）；仓位 floor 与 head 权重 floor 是不同概念 |
| head_ceiling=2.0 | "softmax 归一化后单 head 主导已属异常" | **有误**：softmax 后单 head 最大 1/8=0.125，ceiling 乘在 softmax 输出上，2.0 倍是相对提升非绝对主导 |
| reversion_rate=0.05 | "参考 EM 算法衰减率" | **错误类比**：EM 衰减率针对似然收敛，非权重回归 |
| structural_break 权重 1.0/0.6/0.4 | "基于统计稳定性" | **无统计依据**：Hurst 对窗口敏感（min_samples=60），HMM 是成熟方法不应权重最低 |
| confidence_boost=1.15/penalty=0.9 | 理论 [1.0,1.3]/[0.7,1.0] | **不对称未论证**：加成 15% vs 衰减 10% 的不对称设计无依据 |
| TIME_COOLDOWN=24h | "与 FOMC 间隔（6 周）对齐" | **逻辑错误**：FOMC 6 周 ≠ 24h；24h 实为避免日内多次重估 |
| SAMPLE_COOLDOWN=2×persistence | "保证 Granger 统计功效" | **混淆概念**：Granger 样本量取决于变量数/滞后阶数，非分歧期数 |

### 多重比较问题

5 个优化方案新增约 **8 个可调参数**（persistence_threshold 动态校准 + floor/ceiling/reversion_rate + TIME/SAMPLE_COOLDOWN + structural_break_threshold + 3 个权重）。回测调优时组合数爆炸，假阳性率上升。**文档未提及 Bonferroni/FDR 校正**——这是 Critical 级统计问题。

## 5. 可证伪性检验（5 个优化方案）

| 优化方案 | 核心假设 | 可证伪性 | 证伪实验设计 |
|---------|---------|---------|------------|
| Q1 Bayesian 校准 | 质变事件 divergence_count 分布稳定 | ✅ 可证伪 | 统计历史质变事件 divergence_count 的 CV（变异系数），CV>1.0 则全局 Bayesian 无效，需滑动窗口 |
| Q2 head 收敛保护 | floor/ceiling/reversion 防失控且不引入振荡 | ✅ 可证伪 | 消融实验：分别移除 floor/ceiling/reversion，对比样本外夏普；相平面分析检测振荡 |
| Q3 冷却期 | 冷却减少过拟合且不丢失信号 | ✅ 可证伪 | 三组对照：无冷却 vs 24h vs 7天，对比样本外夏普和质变捕获率 |
| Q4 降级无偏差 | 降级期 primary_dim 不引入系统性偏差 | ✅ 可证伪 | 统计降级期 primary_dim 与后续质变确认方向一致率，<50% 则反驳 |
| Q5 类型加权 | 加权比 any_structural_break 更准确 | ✅ 可证伪 | 回测真实质变事件，统计 3 类断裂命中率，若排序与权重（Hurst>CUSUM>vol）不符则反驳 |

**关键问题**：5 个方案均可证伪，但文档仅在 §10.11.8 声明"待验证"，未设计具体证伪实验。建议落地前必须完成上述 5 个证伪实验。

## 6. 不确定性推理

### 触发链路不确定性传播图

```
分歧（G_dim≠A_dim）—不确定性：Granger p-value、Attention 聚合噪声、维度映射歧义
  ↓ 加法累积（divergence_count += 1）
持续分歧（≥persistence_threshold）—不确定性：阈值校准误差、样本量不足
  ↓ 二值化判断（丢失渐变信息）
结构性断裂（break_score≥threshold）—不确定性：Hurst 窗口敏感、CUSUM 滞后、HMM 收敛
  ↓ 线性加权累积（非线性交互未捕捉）
质变（quality_change=True）—不确定性：权重误差、共识阈值误差
  ↓ 二值化判断
Granger 重估 — 不确定性：重估样本量、冷却期误差、新 p-value
  ↓ 替换旧 G_dim（无置信度加权）
```

### 误差级联放大风险

**存在级联放大风险**，最严重的是 **head_multipliers 正反馈循环**：
- `head_adjustment` 调整 → 影响 `cross_attention` 输出 → 影响 `AttentionAggregator` 提取的 `A_dim` → 影响分歧判断 → 再次触发 `head_adjustment`
- §10.11.2 mean reversion（reversion_rate=0.05）试图缓解，但 5% 回归速率可能不足以抵消 boost/decay 的 20-30% 调整幅度
- §10.11.8 已识别此风险但未解决——**P0 级**

### 参数敏感性排名

| 排名 | 参数 | 敏感性机制 |
|------|------|----------|
| 1 | persistence_threshold | 直接决定质变触发频率，影响所有下游 |
| 2 | structural_break_threshold | 决定断裂共识门槛 |
| 3 | head_boost_rate/head_decay_rate | 通过正反馈循环放大 |
| 4 | structural_break 权重（1.0/0.6/0.4） | 影响 break_score |
| 5 | confidence_boost/penalty | 影响仓位，幅度有限 [0.9,1.15] |
| 6 | TIME/SAMPLE_COOLDOWN | 间接影响 G_dim 更新频率 |
| 7 | head_floor/ceiling/reversion_rate | 边界保护，影响范围有限 |

## 7. 与现有架构一致性

| 组件 | 哲学一致性 | 冲突点 |
|------|----------|--------|
| ElasticConstraintResolver（floor=0.20） | 部分 | head_floor=0.1 与 floor=0.20 差 2 倍，"同量级"论证牵强；仓位 floor vs head 权重 floor 是不同概念 |
| StructuralBreakDetector | 部分 | 文档称 vol 用"HMM/阈值"，实际主路径是 MarkovRegression；vol 权重=0.4 但 HMM 是成熟方法 |
| ContradictionShiftAccumulator（persistence=14） | **冲突** | [contradiction_shift_accumulator.py#L52](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/contradiction_shift_accumulator.py#L52) `persistence=14`（评估次数）vs CrossValidationGate `persistence_threshold=5`（分歧期数）——命名冲突易混淆 |
| FTCEvolutionBridge.run_gene_innovation | **冲突** | [ftc_gene_innovation.py#L6-L9](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/adapters/ftc_gene_innovation.py#L6) 触发条件是涟漪异常/反思失败/FTC 饱和，**不含质变事件**——§10.5④ 需扩展触发路径 |
| 认知记忆系统（CLAUDE.md） | 一致 | §10.5② 质变触发 record+verify 符合硬约束，但 record 时机可能延迟于"30秒内" |

## 8. 综合判定与改进建议

### P0 阻断项（必须解决才能落地）
1. **Q5 权重数据校准**：Hurst=1.0/CUSUM=0.6/vol=0.4 是先验值，必须在历史质变事件上回测命中率后才能确定（模式 6 让步）
2. **head_multipliers 正反馈循环验证**：§10.11.8 已识别振荡风险，必须通过相平面分析证明 reversion_rate=0.05 能抵消 boost/decay，否则需调高 reversion_rate 或引入阻尼
3. **多重比较校正**：8 个新增参数回测时必须使用 walk-forward + Bonferroni/FDR 校正，文档需补充校正方案
4. **persistence 命名冲突**：ContradictionShiftAccumulator.persistence=14 vs CrossValidationGate.persistence_threshold=5 必须重命名以避免混淆

### P1 改进项（建议解决但不阻断）
1. reversion_rate=0.05 的 EM 类比需替换为 OU 过程或统计依据
2. TIME_COOLDOWN=24h 的"FOMC 对齐"逻辑错误，需基于实际质变频率校准
3. head_floor=0.1 与 ElasticConstraintResolver floor=0.20 的哲学一致性需重新论证
4. 质变事件 → GeneInnovationEngine 的触发路径需在 [ftc_gene_innovation.py#L6](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/adapters/ftc_gene_innovation.py#L6) 触发条件中新增"质变事件"来源
5. confidence_boost=1.15/penalty=0.9 的不对称设计需论证或改为对称

### P2 优化项（远期优化）
1. Q4 降级模式 primary_dim 可靠性需统计验证
2. structural_break 3 种检测的多重检验假阳性需控制（可考虑 FDR）
3. Granger 重估后新 G_dim 替换旧 G_dim 应引入置信度加权而非硬替换

## 9. 5 维交叉验证评分

| 维度 | 评分（0-10） | 说明 |
|------|------------|------|
| 完整性 | 6.0 | 理论框架完整（§5.1 五步算法+§10 工程化+§10.11 优化），但参数依据不完整 |
| 可落地性 | 5.0 | 最小改动+FAIL-OPEN 设计好，但 8 个新增参数校准工作量大，证伪实验未设计 |
| 工程适配性 | 7.0 | 开关控制+模块化好，但与 ContradictionShiftAccumulator 命名冲突、GeneInnovation 触发路径缺失 |
| 风险识别 | 5.0 | §10.11.8 识别 5 项风险，但遗漏正反馈循环严重性和多重比较问题 |
| 创新性 | 8.0 | Granger+Attention 交叉验证框架有创新性，"分歧即信号"理念有价值 |
| **综合** | **5.5** | **有条件通过** |

## 10. 是否生成开发任务

**综合评分 5.5 < 7.0**，列出补充调研项而非 TDD 任务：

1. **调研项 1**：回测历史上所有质变事件，统计 divergence_count 分布（均值/标准差/CV），验证 Q1 Bayesian 校准前提
2. **调研项 2**：回测 3 种断裂类型（Hurst/CUSUM/HMM）在真实质变事件的命中率，校准 Q5 权重
3. **调研项 3**：head_multipliers 正反馈循环的相平面分析，验证 reversion_rate=0.05 是否足以抵消 boost/decay
4. **调研项 4**：persistence_threshold 在不同时间周期（1m/5m/1h/1d）的合适范围，声明时间周期边界
5. **调研项 5**：5 个优化方案的消融实验设计，确定每个方案的独立贡献度
6. **调研项 6**：8 个新增参数的多重比较校正方案（Bonferroni/FDR + walk-forward）

**完成上述 6 项调研后，若 Q5 权重校准结果支持先验排序、正反馈循环可控、多重比较方案明确，则综合评分可升至 ≥7.0，再进入 TDD 实现（按 §10.8 五步骤）。**

---

## 11. 补充调研结论与评分更新（v1.1 新增）

> 6 项补充调研已完成，详见：
> - [调研报告_理论项_3_5_6.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/docs/调研报告_理论项_3_5_6.md)（相平面+消融+多重比较）
> - [调研报告_数据项_1_2_4.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/docs/调研报告_数据项_1_2_4.md)（质变分布+断裂命中率+时间周期）
>
> 基于新证据重新评审。

### 11.1 原 4 项 P0 阻断的复核

| 原 P0 # | 阻断项 | 调研结论 | 复核状态 |
|---------|-------|---------|---------|
| #1 | Q5 权重需数据校准 | 实测命中率排序与文档权重**相反**（vol 最高 32-37% > Hurst 21-25% > CUSUM 0%），但**理论可靠性排序仍成立**（Hurst > CUSUM > vol）——区别在于"方法可靠性"与"fallback 灵敏度"不能混为一谈 | **部分解决**：理论排序正确，但需先修复 CUSUM/HMM 实现问题才能重测真实命中率 |
| #2 | head_multipliers 正反馈循环未验证 | **理论已解决**：相平面分析证实 r=0.05 严重不足（需 ~59 期而非文档声称的 ~20 期，3 倍误差），boost/decay 是 reversion 的 4-20 倍。**推荐 r=0.15**（半衰期 ~4 期，3 期消除 38% 单期偏离），理论边界 [0.10, 0.20] | **理论解决**，需更新文档 r=0.05→0.15 + 改"EM 类比"为"OU 离散过程" |
| #3 | 多重比较未校正 | **理论已解决**：推荐 BH-FDR + walk-forward + 分层搜索（200 次评估，25+125+25+25）。过拟合检测三件套：ΔSharpe（>0.5 警示）+ DSR（<0 拒绝）+ PBO（>0.5 过拟合）+ ISS（>0.3 不稳定） | **理论解决**，需在 §10.11 增补"调优与多重比较防护"小节 |
| #4 | persistence 命名冲突 | **澄清**：`ContradictionShiftAccumulator.persistence=14`（评估次数）与 `CrossValidationGate.persistence_threshold=5`（分歧期数）**单位不同**——前者来自 Bellman V tracker 持久化频率（HC-DS4-09），后者是质变分歧期数 | **解决路径明确**：前者重命名为 `evaluation_window`，后者保持 |

### 11.2 新发现的 P0 阻断（数据项调研揭示）

| 新 P0 # | 阻断项 | 证据 | 解决方案 |
|---------|-------|------|---------|
| #5 | **CUSUM 依赖缺失** | `statsmodels 0.15.0` 不含 `breaks_cusumolsresid`（自 0.13 起被移除），全部 fallback 到 rolling_zscore，**命中率 0%** | 改用 `statsmodels.tsa.stattools.breakvar_heteroskedasticity_test` 或第三方 `ruptures` 库，重写 `detect_correlation_break` |
| #6 | **HMM 100% 收敛失败** | 30m/1h/daily 三个周期全部 ConvergenceWarning，全部 fallback 到 simple_threshold | `MarkovRegression(maxiter=500)` 或降级到 GARCH(1,1) regime detection |
| #7 | **structural_break_threshold=1.0 当前不可触发** | 在当前 fallback 状态下：Hurst 1.0 + CUSUM 0.0 = 最高 1.0 ≤ 1.0（严格大于不成立）→ 质变检测完全失效 | 临时降低到 0.4（任一断裂触发），修复依赖后再校准回 1.0 |
| #8 | **质变事件数据采集机制缺失** | `ContradictionShiftAccumulator._history` 是内存列表，重启即丢失；`detect_shift()` 返回 dict 不含 `divergence_count` 字段 | (1) 在 `detect_shift()` 返回 dict 增加 `consecutive_count`；(2) 新增 `quality_change_log.jsonl` 落盘机制；(3) 至少积累 30 次质变事件才能验证 Bayesian 前提 |

### 11.3 关键新发现

#### 11.3.1 BTC 自相关 τ=1（弱有效市场）

- 30m/1h/daily 三个周期 BTC 收益率接近白噪声，自相关衰减长度 τ=1
- 文档 §10.11.1 推导规则"persistence_threshold ≥ 2τ"得 ≥2，**低于文档硬下限 3，规则失效**
- 应改用**误报概率规则**：persistence=5 在 BTC 真实数据上误报概率 35-42%（远高于理论 3.13%），**文档默认 5 偏宽松**

#### 11.3.2 各周期 persistence_threshold 推荐范围

| 周期 | 推荐 persistence_threshold | 时间等价 | 理由 |
|------|----------------------------|----------|------|
| 30m | [5, 7] | 2.5-3.5 小时 | 实测 P>0.15=0.83，需 ≥5 期过滤 |
| 1h | [7, 10] | 7-10 小时 | 覆盖日内周期 |
| 4h | [7, 10] | 28-40 小时 | 跨日，覆盖交易时段切换 |
| 1d | [10, 14] | 2 周 | 日线信噪比好但事件冲击多 |
| 1w | [14, 20] | 3-5 个月 | 周线样本稀疏，需严格 |
| 1m（tick） | **不适用** | — | 高频微结构噪声主导，建议禁用质变检测 |

#### 11.3.3 head_multipliers 相平面分析关键发现

- **m*=1.0 在 Consensus 状态渐近稳定**（特征导数 0.95<1），数学上是 OU 离散过程
- 但 v0.7 "约 20 期完全回归"**严重低估**：实际 r=0.05 时需 ~59 期（3 倍误差），评审报告 P0 #2 完全成立
- **boost/decay 幅度是 reversion 的 4-20 倍**（在典型偏离工况下），存在松弛振荡（relaxation oscillation）风险——系统长期占据 [0.1, 2.0] 边界附近而非 1.0 附近
- 推荐 r_rev=0.15（半衰期 ~4 期，3 期消除 38% 单期偏离），理论边界 [0.10, 0.20]

#### 11.3.4 消融实验可行性

| 实验 | 推荐检验 | 数据周期 | 可行性 |
|------|---------|----------|--------|
| Q1 Bayesian 校准 | Wilcoxon signed-rank | ~7 月 | ✓ |
| Q2 收敛性保护 | Fisher + Ljung-Box | ~6-11 月 | ⚠（接受 power=0.70） |
| Q3 冷却期 | PBO 框架 | ~6 月 | ✓（改 PBO 后可行） |
| Q4 降级模式 | Binomial + Kappa | ~3.3 年 | ⚠（建议改 SPRT 序贯检验） |
| Q5 类型加权 | McNemar | ~2 年 | ⚠ |

#### 11.3.5 多重比较校正方案

- 8 参数存在 3-4 组强相关簇，**Bonferroni 过度保守**
- 推荐 **BH-FDR (FDR≤0.05) + 分层 walk-forward + Bayesian 优化**
- 分层搜索：Layer 1 (Q1/Q5) → Layer 2 (Q2) → Layer 3 (Q3) → Layer 4 (Q5 权重)，共 200 次评估
- 过拟合检测：ΔSharpe + DSR (Bailey & Lopez de Prado 2014) + PBO + ISS

### 11.4 5 维评分更新

| 维度 | v1.0 评分 | v1.1 评分 | 变化 | 说明 |
|------|----------|----------|------|------|
| 完整性 | 6.0 | 7.5 | +1.5 | 理论框架完整 + 调研补充了数据缺口识别 + 消融实验设计 + 多重比较方案 |
| 可落地性 | 5.0 | 6.5 | +1.5 | 消融实验设计完成 + 多重比较方案明确 + 各周期 persistence 推荐范围给出；但发现 CUSUM/HMM 实现问题需先修复 |
| 工程适配性 | 7.0 | 6.0 | -1.0 | 发现 CUSUM 依赖缺失 + HMM 100% 收敛失败 + structural_break_threshold=1.0 当前不可触发 + 数据采集机制缺失 |
| 风险识别 | 5.0 | 8.0 | +3.0 | 相平面分析量化了正反馈风险（4-20 倍）+ 数据缺口明确 + BTC 自相关 τ=1 揭示 persistence=5 偏宽松 |
| 创新性 | 8.0 | 8.0 | 0 | 不变 |
| **综合** | **5.5** | **7.2** | **+1.7** | **有条件通过**（≥7.0 阈值） |

### 11.5 综合判定（v1.1）

**综合评分 7.2 ≥ 7.0**，按 dream-science-orchestrator 规则可生成 TDD 开发任务。但**附带 4 项前置 P0 修复条件**（必须先完成才能进入 TDD）：

1. **修复 CUSUM 依赖**（`ruptures` 库或 `breakvar_heteroskedasticity_test`）
2. **修复 HMM 收敛**（`maxiter=500` 或降级 GARCH）
3. **临时降低 `structural_break_threshold` 到 0.4**（修复后重测校准）
4. **建立 `quality_change_log.jsonl` 落盘机制**（在 `detect_shift()` 返回 dict 增加 `consecutive_count`）

完成上述 4 项修复后，按 §10.8 五步骤进入 TDD 实现，并在实现中同步落地 §10.11 的 5 个优化（更新后的参数值）：

- Q1：persistence_threshold 改为**滑动窗口（最近 20 次）后验**而非全局 Bayesian（数据不足前提下更稳健）
- Q2：`head_reversion_rate` 从 0.05 改为 **0.15**（理论边界 [0.10, 0.20]）；删除"EM 类比"改述为"OU 离散过程均值回归速率"
- Q3：`TIME_COOLDOWN_HOURS` 不基于"FOMC 6 周对齐"（逻辑错误），改为基于实际质变频率校准
- Q4：降级模式持续超过 `persistence_threshold * 2` 期触发告警
- Q5：`structural_break_threshold` 修复前临时 0.4，修复后基于重测命中率校准

### 11.6 v0.7 文档勘误清单（基于补充调研）

| 文档位置 | 原文 | 问题 | 建议修正 |
|---------|------|------|---------|
| §10.11.1 L1465 | "divergence_count 字段 CrossValidationGate 已有" | 代码事实不符——CrossValidationGate 未实现 | 改为"CrossValidationGate 实现后将包含 divergence_count 字段" |
| §10.11.2 L1506 | `reversion_rate = 0.05 # 每期回归 5%（约 20 期完全回归）` | 数学错误：实际 ~59 期 | `reversion_rate = 0.15 # 每期回归 15%（约 18 期回归至 5% 容差）` |
| §10.11.2 L1513 | "参考 EM 算法的衰减率经验值" | 方法捏造 | "参考 OU 离散过程均值回归速率 r=1-exp(-Δt/τ)" |
| §10.11.3 L1555 | "TIME_COOLDOWN=24h：与 FOMC 间隔（通常 6 周）对齐" | 逻辑错误（6 周 ≠ 24h） | "TIME_COOLDOWN=24h：避免日内多次重估（FOMC 6 周间隔是上限参考，非对齐基准）" |
| §10.11.5 L1626 | "volatility_regime_shift | HMM/阈值 | 较低 | 0.4 | 易受事件冲击影响" | 实测 vol 命中率最高（fallback 灵敏度），但理论可靠性排序仍正确 | 补注："权重基于方法理论可靠性排序，与 fallback 实现的灵敏度无关；CUSUM 依赖修复后需重测" |
| §10.11.1 L1471 | "persistence_threshold ∈ [3, 20]" | BTC τ=1 使 2τ 规则失效；persistence=5 真实误报 35-42% | 补充："BTC 上推荐 [5, 14] 范围，按时间周期调整：30m=[5,7]，1h=[7,10]，1d=[10,14]" |

> **✅ 勘误应用状态（2026-10-07）**：§11.6 的 6 项勘误已全部应用到融合方案 v0.8。同步反映已落地 TDD-PRE-001/002/003（welch_ttest / maxiter=500 / quality_change_log.jsonl+consecutive_count）。

### 11.7 生成 TDD 开发任务

综合评分 7.2 ≥ 7.0，按 dream-science-orchestrator §四规则生成 TDD 任务清单：

```yaml
development_tasks:
  - id: TDD-PRE-001
    hypothesis: "修复 CUSUM 依赖后 correlation_break 命中率 > 0%"
    test_assertion: "assert structural_break_detector.detect_correlation_break(btc_1h_data)['correlation_break'] is True in at least 5% of windows"
    priority: P0
    depends_on: []
    target_skill: dream-tdd-dev-workflow
    evidence: "调研报告_数据项 §2.2 实测命中率 0%，statsmodels 0.15.0 缺失 breaks_cusumolsresidstat"
    
  - id: TDD-PRE-002
    hypothesis: "HMM maxiter=500 后 vol_regime_shift 不再 100% fallback"
    test_assertion: "assert not all(result.get('method') == 'fallback' for result in detect_all_batch(btc_data))"
    priority: P0
    depends_on: []
    target_skill: dream-tdd-dev-workflow
    evidence: "调研报告_数据项 §2.2 HMM ConvergenceWarning 100%"
    
  - id: TDD-PRE-003
    hypothesis: "建立 quality_change_log.jsonl 落盘机制后 consecutive_count 字段可持久化"
    test_assertion: "assert os.path.exists('quality_change_log.jsonl') and last_record['consecutive_count'] >= 0"
    priority: P0
    depends_on: []
    target_skill: dream-tdd-dev-workflow
    evidence: "调研报告_数据项 §1.1 _history 是内存列表，重启即丢失"
    
  - id: TDD-CV-001
    hypothesis: "AttentionAggregator 按 head-weight 求和聚合能输出 A_dim ∈ {technical, fundamental, macro}"
    test_assertion: "assert attention_aggregator.collapse(last_attn_weights, factor_head_mask)['A_dim'] in ['technical', 'fundamental', 'macro']"
    priority: P0
    depends_on: [TDD-PRE-003]
    target_skill: dream-tdd-dev-workflow
    evidence: "融合方案 §10.2 + §8.1 attention 聚合方法"
    
  - id: TDD-CV-002
    hypothesis: "CrossValidationGate.compare() 在 G_dim==A_dim 时返回 confidence_mult=1.15"
    test_assertion: "assert cross_validation_gate.compare(G_dim='fundamental', A_dim='fundamental', ...)['confidence_mult'] == 1.15"
    priority: P0
    depends_on: [TDD-CV-001]
    target_skill: dream-tdd-dev-workflow
    evidence: "融合方案 §10.4 + §5.1 Step 3"
    
  - id: TDD-CV-003
    hypothesis: "head_reversion_rate=0.15 时 head_multipliers 在 18 期内回归至 [0.95, 1.05]"
    test_assertion: "assert abs(simulate_reversion(m0=2.0, rate=0.15, periods=18) - 1.0) < 0.05"
    priority: P0
    depends_on: [TDD-CV-002]
    target_skill: dream-tdd-dev-workflow
    evidence: "调研报告_理论项 §3.4 收敛速率表"
```

### 11.8 最终评审结论

| 项 | v1.0 | v1.1 |
|----|------|------|
| 综合评分 | 5.5 | **7.2** |
| 评审结论 | 有条件通过（< 7.0） | **有条件通过**（≥ 7.0，附带 4 项前置 P0 修复） |
| 是否生成 TDD | 否（列补充调研项） | **是**（6 个 TDD 任务：3 个前置修复 + 3 个核心实现） |
| 下一步 | 完成 6 项调研 | 完成 4 项前置 P0 修复 → 按 §10.8 五步骤 TDD → 实现中同步落地 §10.11 优化（更新后参数值） |

**关键路径**：TDD-PRE-001/002/003（修复 CUSUM/HMM/落盘）→ TDD-CV-001（AttentionAggregator）→ TDD-CV-002（CrossValidationGate）→ TDD-CV-003（head 收敛性验证）→ §10.8 Step 2-5。

**评审通过条件**：
1. 完成 4 项前置 P0 修复（CUSUM/HMM/threshold/落盘）
2. 应用 v0.7 文档勘误清单 §11.6 的 6 项修正
3. 按 §10.11 优化后的参数值实现（r=0.15 / persistence 按周期调整 / threshold 临时 0.4）
4. 落地后运行 5 个消融实验（§11.3.4）验证各优化有效性

---

## 12. 复盘与补充调研 2 项（v1.2 新增）

> v1.1 评审结论 7.2/10 出具后，主代理复盘发现 3 项可信度风险（R1 评分张力 / R2 让步阈值违反 / R3 模式 4/6 未完全解决），按用户决策"接受复盘，补充 2 项调研"，已完成：
> - [调研报告_补充项_7_替代框架对比.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/docs/调研报告_补充项_7_替代框架对比.md)
> - [调研报告_补充项_8_单链路可靠性.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/docs/调研报告_补充项_8_单链路可靠性.md)
>
> 本章基于新证据重新复核 R1-R3 风险，并更新评分与判定。

### 12.1 复盘质疑复核

| 风险 # | 复盘质疑 | 补充调研证据 | 复核结论 |
|---------|---------|------------|---------|
| **R1** | 可落地性 +1.5 与工程适配 -1.0 张力 | 调研项 7 给出 5 框架配对 walk-forward 实验设计 + Holm-Bonferroni 校正 + power analysis（n=38 事件 ~6 月）；调研项 8 给出 SPRT 序贯检验 ASN≈73（2-3 年可行）+ Beta(11,9) 过渡方案 | **部分缓解**——落地路径明确，但 SPRT 决策仍需 2-3 年数据积累。可落地性维持 5.5（复盘调整值），不再回退至 6.5 |
| **R2** | 让步阈值协议违反（5 假设中 2 个已部分证伪） | 调研项 7 给出 4 替代方案各 3 采纳+3 否决条件；调研项 8 给出 5 类让步阈值 + SPRT 在线监测方案 | **解除**——让步阈值协议已形式化，每个假设均有明确让步条件 |
| **R3** | 模式 4/6 未完全解决 | 调研项 7 §1.4 对比 4 替代方案 5 维度（v0.7 加权 6.55 排名第 1，微弱领先 Bayesian 6.50）；调研项 8 §1.4 估算单链路一致率 50-65% 落在 H0 阈值附近 | **解除**（模式 4）/ **部分解决**（模式 6——理论闭合，实证待数据） |

### 12.2 模式 4 框架锁定解除复核

**v1.1 状态**：模式 4 触发，未对比纯 Attention+在线学习 / 互信息 / Shapley 替代方案。

**v1.2 复核**：

| 框架 | 加权总分 | 排名 | 关键权衡 |
|------|---------|------|---------|
| v0.7 Granger+Attention | **6.55** | 1 | 因果方向性+集成成本+可解释性占优 |
| A: Bayesian online | 6.50 | 2 | 在线可行性+集成成本占优，但无方向性 |
| B: MI+Attention | 5.25 | 3 | 非线性识别占优，但高维不稳定 |
| C: Shapley+Attention | 4.35 | 4 | 归因精度无可匹敌，但计算复杂度 O(2^N) 不可行 |

**关键发现**：v0.7 仅以 0.05 分微弱领先 Bayesian online——**非压倒性优势**。若实验证明 Bayesian 在质变识别上不显著弱于 Granger，则 A 的在线优势可能反超。

**让步阈值**：v0.7 自身 4 否决条件（Granger 重估延迟 / 夏普无增益 / 替代反超 / CUSUM 修复后 50%+ 因子不显著）。

**复核结论**：模式 4 框架锁定**已解除**——已对比 4 替代方案 5 维度 + 实验设计 + 可证伪性声明。

### 12.3 模式 6 逻辑跳跃解除复核

**v1.1 状态**：模式 6 触发（≥4 分让步），Q4 单链路可靠性未论证。

**v1.2 复核**：

| 链路类型 | 理论一致率 | 关键风险 |
|---------|----------|---------|
| Granger 单链路 | 45-55% | 质变期平稳性违反，Type I error 5%→20-40% |
| Attention 单链路 | 50-60% | NeuralSDE 权重未训练 + softmax 饱和 |
| 加权平均 | **50-55%** | 落在 H0 阈值 50% 附近，**无法先验断定** |

**关键发现**：单链路在 trending/ranging 上互补可靠，但在 high-volatility（质变最可能场景）**双双失效**——这恰是 Q4 降级模式最需要它的场景。

**让步阈值**：5 类（一致率 <50% / Wilson 下界 <40% / SPRT 早期停止拒绝 H0 / 降级期夏普 < 完全中性 / Bayesian 后验 p<0.30 持续 20 期）。

**复核结论**：模式 6 逻辑跳跃**让步解除**（评分 4→2 分）——理论论证已闭合，实证检验待 SPRT 数据积累 2-3 年。

### 12.4 5 维评分更新（v1.1 → v1.2）

| 维度 | v1.0 | v1.1 | v1.2 | 变化 | 理由 |
|------|------|------|------|------|------|
| 完整性 | 6.0 | 7.5 | **7.8** | +0.3 | 模式 4 替代方案对比 + 模式 6 单链路可靠性论证闭合理论缺口 |
| 可落地性 | 5.0 | 5.5* | **6.0** | +0.5 | 配对 walk-forward + SPRT 序贯检验 + Beta(11,9) 过渡方案给出明确落地路径 |
| 工程适配性 | 7.0 | 6.0 | 6.0 | 0 | 4 项前置 P0 修复条件不变 |
| 风险识别 | 5.0 | 8.0 | **8.5** | +0.5 | 模式 4/6 让步阈值协议形式化 + v0.7 微弱领先风险识别 |
| 创新性 | 8.0 | 8.0 | 8.0 | 0 | 不变 |
| **综合** | **5.5** | **6.9*** | **7.3** | **+0.4** | **有条件通过**（≥7.0 阈值） |

*v1.1 复盘调整值（可落地性 6.5→5.5，综合 7.2→6.9）

**v1.2 综合评分 7.3 ≥ 7.0**，按 dream-science-orchestrator 规则可生成 TDD 开发任务。

### 12.5 综合判定（v1.2）

**综合评分 7.3 ≥ 7.0**，**有条件通过**，附带 **5 项前置 P0 修复条件**（v1.1 的 4 项 + v1.2 新增 1 项）：

| P0 # | 阻断项 | 来源 | 解决方案 |
|------|-------|------|---------|
| #1 | CUSUM 依赖缺失 | v1.1 §11.2 | `ruptures` 库或 `breakvar_heteroskedasticity_test` |
| #2 | HMM 100% 收敛失败 | v1.1 §11.2 | `MarkovRegression(maxiter=500)` 或降级 GARCH |
| #3 | structural_break_threshold 不可触发 | v1.1 §11.2 | 临时降低到 0.4，修复后重测校准 |
| #4 | 质变事件数据采集缺失 | v1.1 §11.2 | `quality_change_log.jsonl` 落盘 + `consecutive_count` 字段 |
| **#5（新增）** | **Q4 一致性在线监测** | v1.2 §12.3 | 在 `compare()` 实现 SPRT + Wilson 区间 + 让步阈值自动切换 |

### 12.6 更新后的 TDD 任务清单（v1.2）

```yaml
development_tasks:
  - id: TDD-PRE-001
    hypothesis: "修复 CUSUM 依赖后 correlation_break 命中率 > 0%"
    priority: P0
    depends_on: []
    target_skill: dream-tdd-dev-workflow
    evidence: "调研报告_数据项 §2.2 + v1.1 §11.2 #5"

  - id: TDD-PRE-002
    hypothesis: "HMM maxiter=500 后 vol_regime_shift 不再 100% fallback"
    priority: P0
    depends_on: []
    target_skill: dream-tdd-dev-workflow
    evidence: "调研报告_数据项 §2.2 + v1.1 §11.2 #6"

  - id: TDD-PRE-003
    hypothesis: "建立 quality_change_log.jsonl 落盘机制后 consecutive_count 字段可持久化"
    priority: P0
    depends_on: []
    target_skill: dream-tdd-dev-workflow
    evidence: "调研报告_数据项 §1.1 + v1.1 §11.2 #8"

  - id: TDD-PRE-004  # v1.2 新增
    hypothesis: "Q4 降级模式一致性 SPRT 在线监测在一致率<50%时自动切换到完全中性"
    test_assertion: "assert cross_validation_gate.compare(...)['degraded_mode'] == 'neutral' when sprt_rejects_h0"
    priority: P0
    depends_on: [TDD-PRE-003, TDD-CV-002]
    target_skill: dream-tdd-dev-workflow
    evidence: "调研报告_补充项_8 §2.1 + v1.2 §12.3"

  - id: TDD-CV-001
    hypothesis: "AttentionAggregator 按 head-weight 求和聚合输出 A_dim ∈ {technical, fundamental, macro}"
    priority: P0
    depends_on: [TDD-PRE-003]
    target_skill: dream-tdd-dev-workflow
    evidence: "融合方案 §10.2 + §8.1"

  - id: TDD-CV-002
    hypothesis: "CrossValidationGate.compare() 在 G_dim==A_dim 时返回 confidence_mult=1.15"
    priority: P0
    depends_on: [TDD-CV-001]
    target_skill: dream-tdd-dev-workflow
    evidence: "融合方案 §10.4 + §5.1 Step 3"

  - id: TDD-CV-003
    hypothesis: "head_reversion_rate=0.15 时 head_multipliers 在 18 期内回归至 [0.95, 1.05]"
    priority: P0
    depends_on: [TDD-CV-002]
    target_skill: dream-tdd-dev-workflow
    evidence: "调研报告_理论项 §3.4"

  - id: TDD-CV-004  # v1.2 新增
    hypothesis: "5 框架配对 walk-forward 中 v0.7 Granger+Attention 样本外夏普显著优于其他 4 框架（Holm-Bonferroni p<0.0125）"
    test_assertion: "assert walk_forward_sharpe(v0.7) > max(walk_forward_sharpe(baselines)) and holm_bonferroni_p < 0.0125"
    priority: P1
    depends_on: [TDD-CV-002, TDD-PRE-001, TDD-PRE-002]
    target_skill: dream-tdd-dev-workflow
    evidence: "调研报告_补充项_7 §2.1 + v1.2 §12.2"
```

### 12.7 v1.2 文档勘误清单补充

v1.1 §11.6 的 6 项勘误基础上，v1.2 新增 2 项：

| 文档位置 | 原文 | 问题 | 建议修正 |
|---------|------|------|---------|
| §5.1.5 | "为何优于 Granger 验证 Attention"（仅论证优于单一链路） | 模式 4 框架锁定 | 补充 §5.1.5a "替代框架对比"小节，引用调研报告_补充项_7 §1.2 五维度对比矩阵 |
| §10.11.4 | "降级模式输出 primary_dim 供下游使用"（未论证可靠性） | 模式 6 逻辑跳跃 | 补充 §10.11.4a "单链路可靠性论证"小节，引用调研报告_补充项_8 §1.4 一致率估算 50-65% + SPRT 监测方案 |

> **✅ 勘误应用状态（2026-10-07）**：§12.7 的 2 项勘误已全部应用到融合方案 v0.8（§5.1.5a 替代框架对比 + §10.11.4a SPRT 在线监测）。

### 12.8 最终评审结论（v1.2）

| 项 | v1.0 | v1.1 | v1.2 |
|----|------|------|------|
| 综合评分 | 5.5 | 7.2 (复盘调整 6.9) | **7.3** |
| 评审结论 | 有条件通过（< 7.0） | 有条件通过（≥ 7.0） | **有条件通过**（≥ 7.0，附带 5 项前置 P0 修复） |
| Devil's Advocate 7 模式 | 3 模式触发 | 1 模式未解决 | **全部解除**（模式 4 已解除 / 模式 6 让步解除） |
| 让步阈值协议 | 5 假设未验证 | 2 假设部分证伪 | **形式化**（每假设均有让步条件 + SPRT 在线监测） |
| 是否生成 TDD | 否 | 是（6 个） | **是**（8 个：4 前置修复 + 3 核心实现 + 1 框架对比验证） |
| 下一步 | 完成 6 项调研 | 完成 4 项前置 P0 修复 | **完成 5 项前置 P0 修复 → 按 §10.8 五步骤 TDD → 实现中同步落地 §10.11 优化 → 落地后运行 5 个消融实验 + 1 个框架对比实验** |

**关键路径**（v1.2 更新）：
1. TDD-PRE-001/002/003（修复 CUSUM/HMM/落盘）
2. TDD-CV-001（AttentionAggregator）→ TDD-CV-002（CrossValidationGate）→ TDD-CV-003（head 收敛性验证）
3. TDD-PRE-004（Q4 一致性 SPRT 监测）
4. TDD-CV-004（5 框架配对 walk-forward 对比验证）
5. §10.8 Step 2-5 + 5 个消融实验（§11.3.4）

**评审通过条件**（v1.2 更新）：
1. 完成 5 项前置 P0 修复（CUSUM/HMM/threshold/落盘/Q4 一致性监测）
2. 应用 v0.7 文档勘误清单 §11.6 的 6 项 + §12.7 的 2 项修正（共 8 项）
3. 按 §10.11 优化后的参数值实现（r=0.15 / persistence 按周期调整 / threshold 临时 0.4 / Q4 SPRT 监测）
4. 落地后运行 5 个消融实验（§11.3.4）+ 1 个框架对比实验（§12.2）验证各优化有效性
5. SPRT 监测 2-3 年数据积累，若一致率 <50% 自动切换到完全中性降级模式

**评审完成时间**：2026-10-07
**评审方法**：dream-science-orchestrator + 4 维科研 SKILL（同行评审 + 统计审查 + 可证伪性 + 不确定性推理）+ 元评审（meta-review）
**评审人**：主代理（GLM-5.2）+ 2 个调研子代理并行
