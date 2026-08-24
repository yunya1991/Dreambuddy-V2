# FiveDomainFeatureComputer 设计文档

> 日期：2026-08-22
> 上游规格：[2026-08-21-sunzi-five-domains-evaluation.md](./2026-08-21-sunzi-five-domains-evaluation.md)
> 范围：P0 — 补齐战略层「特征→评分」计算层，使五计庙算从中性默认值变为实际计算

---

## 一、问题定义

### 现状

`FiveDomainHeuristicScorer`（[five_domain_scorer.py](../../11-易经推理系统/scripts/memory_l4/five_domain_scorer.py)）接收五维原始评分(0-100)并映射到决策（war_state/mask/cap/...），决策映射层（6个不等式）实现完整。但 **原始评分从未从市场数据计算过**：

- [polling_trader.py:1100](../../11-易经推理系统/scripts/memory_l4/polling_trader.py#L1100) 调用 `score_and_decide(persist=True)` 不传 `raw_scores_by_class`
- `enable_five_domain=False`，scorer 恒返回 fail-open 默认值 `{dao:50, tian:50, di:50, jiang:50, fa:70}`

### 目标

新增 `FiveDomainFeatureComputer` 模块，从现有特征计算五维原始评分，传给 `FiveDomainHeuristicScorer.score_and_decide(raw_scores, persist=True)`。

### 数据流

```
市场数据(klines/volume/system_state)
  → 现有 bcrm2 特征模块 + 后置层 regime + 系统自省
  → FiveDomainFeatureComputer.compute()
  → raw_scores_by_class = {cls: {dao:0-100, tian:0-100, di:0-100, jiang:0-100, fa:0-100}}
  → FiveDomainHeuristicScorer.score_and_decide(raw_scores_by_class)
  → FiveDomainState(决策)
```

---

## 二、架构

### 方案：单一统一模块

- 文件：`11-易经推理系统/scripts/memory_l4/five_domain_feature_computer.py`
- 一个 `FiveDomainFeatureComputer` 类
- 五个私有方法：`_compute_dao() / _compute_tian() / _compute_di() / _compute_jiang() / _compute_fa()`
- 道天地读取市场数据特征（从现有 bcrm2 模块 + 后置层 regime）
- 将法读取系统配置状态（RiskManager/PerformanceStats/strategy_algo_layer）
- 公共入口：`compute(coin_data, system_state) -> Dict[str, Dict[str, int]]`

### 集成点

修改 [polling_trader.py:1100](../../11-易经推理系统/scripts/memory_l4/polling_trader.py#L1100) `_run_once_five_domain_daily_update()`：

```python
# 当前（问题）
result_state = self._five_domain_scorer.score_and_decide(persist=True)

# 修改后
if self._five_domain_feature_computer:
    raw_scores = self._five_domain_feature_computer.compute(
        coin_data=self._coin_data_cache,
        system_state=self._get_system_state(),
    )
    result_state = self._five_domain_scorer.score_and_decide(
        raw_scores_by_class=raw_scores, persist=True
    )
else:
    result_state = self._five_domain_scorer.score_and_decide(persist=True)
```

### 开关控制

`enable_five_domain=False`（[strategy_algo_layer.py](../../11-易经推理系统/scripts/memory_l4/strategy_algo_layer.py) 的总开关）时：
- feature computer 不执行
- scorer 返回 fail-open 默认值
- 字节等价「战略层不存在」

### 周期（§11.1 L1204）

- 战略层 **日级一次** 粗评分
- 道维度 **周级离线** 批打分不进热路径
- 不出战冷却 + 滞回 每轮轮询(5min)检查计数器状态
- 日级缓存(24h TTL)，道维度周级缓存(7d TTL)

---

## 三、五维评分计算逻辑（严格对齐 §三 逐维打分详解）

### 道 — 方向一致性（0-100）§三 L82-110

| 子指标 | 量化方式 | 数据来源 | 本次实现 |
|--------|----------|----------|----------|
| 央行货币政策方向 | M2增速/利率方向/央行资产负债表变化 | 外部API | fail-open→50 |
| 机构资金净流入 | 稳定币市值变化/ETF流入流出/CEX储备变化 | 外部API | fail-open→50 |
| 政策景气度 | 监管信号方向(SEC/CFTC动向) | 外部API | fail-open→50 |
| 变化率（一阶差分） | 上述指标增速变化方向 | 依赖前三项 | fail-open→50 |
| 大周期位置 | 4年周期锚点 t_rel 位置 | [morph_cycle_predictor.py](../../11-易经推理系统/scripts/memory_l4/bcrm2/morph_cycle_predictor.py) `cycle4y_theory()` | ✅ 计算 |

三层道架构（§三 L102-106）：
- 宏观道（全球流动性周期 M2/利率方向/央行资产负债表）→ fail-open
- 中观道（国内政策周期 监管态度/产业政策）→ fail-open
- 微观道（行业景气周期 链上活动/Gas费趋势/DeFi TVL变化）→ fail-open

**道评分**：5个子指标加权，4个 fail-open→50，仅「大周期位置」实际计算。道分主要由4年周期位置决定，按§五 30% 计入庙算总分。

### 天 — 时间节奏（0-100）§三 L114-138

| 子指标 | 量化方式 | 数据来源 | 本次实现 |
|--------|----------|----------|----------|
| 日历季节性 | Q1效应/Q4效应/周末效应/减半周期季节性 | 日历+历史K线 | ✅ 计算（§七标注"第一个落地"） |
| 美林时钟位置 | 复苏/过热/滞胀/衰退四阶段 | [merrill_clock_features.py](../../11-易经推理系统/scripts/memory_l4/bcrm2/merrill_clock_features.py) | ✅ 计算 |
| 波动率周期 | VIX/ATR分位 | ATR(现有) | ✅ ATR分位计算（VIX无数据→用ATR代理） |
| 流动性周期 | QE/QT阶段 | [merrill_clock_features.py](../../11-易经推理系统/scripts/memory_l4/bcrm2/merrill_clock_features.py) `liquidity_credit_features()` | ✅ 计算 |

**输出**：`seasonality_score ∈ [-1, +1]`，叠加到前置层 Level 评分上（§三 L132）。

**"天时"否定条件**（§三 L134）：天分 < 阈值 → position_factor 上界 × 天分归一化系数。

**过拟合防护**（§三 L136）：滚动窗口回测验证稳定性（2017-2020训练，2021-2024样本外验证），样本外 IC < 0.02 则降权或剔除。

### 地 — 市场结构与价格位置（0-100）§三 L142-172

**§11.1 L1204 数据来源**：后置层 `enhance_result.regime` 代理 + MA 结构

| 子指标 | 量化方式 | 数据来源 | 本次实现 |
|--------|----------|----------|----------|
| regime 代理 | 后置层5态识别→分数映射 | enhance_result.regime | ✅ 计算 |
| 弹簧力场5MA | MA30/65/128/200 + 1400大周期 | [polling_trader.py:5230](../../11-易经推理系统/scripts/memory_l4/polling_trader.py#L5230) `_compute_spring_force_field()` | ✅ 计算 |
| 八卦坤地(支撑阻力) | ~15特征 | [bagua_feature_engine.py](../../11-易经推理系统/scripts/memory_l4/bcrm2/bagua_feature_engine.py) | ✅ 计算 |
| 艮山(市场结构) | ~14特征 | [bagua_feature_engine.py](../../11-易经推理系统/scripts/memory_l4/bcrm2/bagua_feature_engine.py) | ✅ 计算 |
| 斐波那契+枢纽点 | ~20特征 | 现有 | ✅ 计算 |
| 盘整持续时间 | 价格振幅/ATR比值 | 现有K线 | ✅ 计算（补强） |
| Follow-through Day | 下跌→上涨转换信号 | 现有K线 | ✅ 计算（补强） |
| 价格vs MA200距离分位 | 分位统计 | 现有K线 | ✅ 计算（补强） |
| 六种地形分类 | 通形/挂形/支形/隘形/险形/远形 | §三 L157-166 | ✅ 计算 |

**六种地形分类**（§三 L157-166，《孙子兵法·地形篇》）：

| 地形 | 孙子原文 | 市场状态 | 适用策略 |
|------|----------|----------|----------|
| 通形 | 我可以往，彼可以来 | 趋势明确，多空皆可 | 趋势跟踪 |
| 挂形 | 可以往，难以返 | 突破后难以回撤 | 突破策略 |
| 支形 | 我出而不利，彼出而不利 | 震荡盘整 | 均值回归 |
| 隘形 | 我先居之，必盈之以待敌 | 关键支撑阻力位 | 均值回归 |
| 险形 | 我先居之，必居高阳以待敌 | 高波动区间 | 波动率策略 |
| 远形 | 势均难以挑战，战不利 | 趋势不明，方向模糊 | 观望/对冲 |

### 将 — 决策质量与执行纪律（0-100）§三 L176-210

**打分公式**（§三 L196）：将 = 智×20% + 信×25% + 仁×25% + 勇×15% + 严×15%

| 子指标 | 权重 | 量化方式 | 数据来源 | 本次实现 |
|--------|------|----------|----------|----------|
| 智 | 20% | 因子覆盖度/回测完整度/样本外验证 | 系统自省 | ✅ 计算 |
| 信 | 25% | IC/胜率/盈亏比 | [trading_utils.py](../../11-易经推理系统/scripts/memory_l4/trading_utils.py) PerformanceStats | ✅ 计算 |
| 仁 | 25% | 单笔风险≤1-2%/连续亏损降仓 | RiskManager配置 | ✅ 计算 |
| 勇 | 15% | 执行果断 | 系统自省 | ✅ 计算 |
| 严 | 15% | 止损/回撤/单日交易次数/仓位上限 | 系统自省 | ✅ 计算 |

**硬规则**（§三 L198-210）：
- 连续亏损3次→仓位上限降20%（当前 `max_consecutive_losses=999` 禁用，需恢复为3）
- 连续亏损5次→暂停新开仓
- 单日最大交易次数上限
- 连续盈利M次后不自动加仓

### 法 — 策略库与执行规则（0-100）§三 L214-242

**打分公式**（§三 L240）：法 = 策略库完备性×20% + 策略适配度×25% + 风控规则×25% + 回测验证×20% + 复盘迭代×10%

| 子指标 | 权重 | 量化方式 | 数据来源 | 本次实现 |
|--------|------|----------|----------|----------|
| 策略库完备性 | 20% | 6类策略是否实现 | [strategy_algo_layer.py](../../11-易经推理系统/scripts/memory_l4/strategy_algo_layer.py) STYLE_ORDER | ✅ 计算 |
| 策略适配度 | 25% | 地形vs策略匹配 | allowed_style_mask | ✅ 计算 |
| 风控规则完整度 | 25% | 止损/回撤/仓位/相关性 | RiskManager | ✅ 计算 |
| 回测验证度 | 20% | 样本外/夏普/最大回撤/换手率 | [backtest_result.json](../../11-易经推理系统/scripts/memory_l4/new_methodology_backtest_result.json) | ✅ 计算 |
| 复盘迭代机制 | 10% | 定期归因/降权/退役 | 系统自省 | ✅ 计算 |

### 评分标准化

§八 L1160：每个子指标统一用 Z-score/分位数/tanh 映射到 0~100，复用现有 `_normalize_0_100`（[strategy_algo_layer.py:26](../../11-易经推理系统/scripts/memory_l4/strategy_algo_layer.py#L26)）。

### 庙算总分（§五 L968-970）

```
庙算总分 = 道×0.30 + 天×0.15 + 地×0.25 + 将×0.15 + 法×0.15
```

### 仓位映射（§五 L994-999）

| 庙算总分 | 建议仓位上限 |
|----------|-------------|
| ≥85 | 80%~100% |
| 75~84 | 50%~80% |
| 60~74 | 20%~50% |
| <60 | 0%~20%，以防守为主 |

### 维度否决规则（§五 L1001-1008）

| 条件 | 约束 |
|------|------|
| 道<40 | 仓位上限≤30% |
| 将<40 | 仓位上限≤30% |
| 法<40 | 不开新仓 |
| 地<40 且 天<40 | 只允许对冲或空仓 |

---

## 四、错误处理（§九 L1180）

- 每个子指标计算包裹 try/except，异常→中性 50
- 外部数据缺失→fail-open 50（道维度4个子指标）
- 整个 `compute()` 异常→返回 `DEFAULT_NEUTRAL_SCORES = {dao:50, tian:50, di:50, jiang:50, fa:70}`
- 与现有资金调控模块 fail-open 设计一致

---

## 五、测试策略（TDD）

按 §七 落地优先级排序测试用例：

| 优先级 | 维度 | 测试用例 |
|--------|------|----------|
| P1 | 天 | 日历季节性 Q1/Q4效应计算、美林时钟四阶段映射、ATR分位统计、流动性周期映射、4子指标加权汇总 |
| P2 | 地 | regime→分数映射、弹簧力场MA评分、六种地形分类、盘整持续时间量化、FTD信号、MA200距离分位 |
| P3 | 将 | 智/信/仁/勇/严五维自省评分、连续亏损降仓硬规则、单日交易次数上限 |
| P4 | 道 | 大周期位置评分、外部数据fail-open、三层道架构fail-open |
| P5 | 法 | 策略库完备性检查、回测验证度读取、复盘迭代机制检查 |
| P0 | 全局 | compute()异常fail-open、enable=False返回中性默认、日级缓存、子指标异常隔离 |

---

## 六、落地优先级（§七 L1147-1154）

| 优先级 | 维度 | 原因 | 预估工作量 | 数据需求 |
|--------|------|------|-----------|----------|
| 1 | 天 | 缺口最简单、数据源最易获取、可快速验证 | 小 | 仅需日历+历史K线 |
| 2 | 地补强 | 现有最强项只需补2-3指标+地形分类 | 小 | 现有K线数据 |
| 3 | 将 | 统一现有分散逻辑为评分卡+风控否决层独立化 | 中 | 现有系统数据 |
| 4 | 道 | 价值最高但需接入外部数据源+三层道架构 | 中-大 | 需接入外部API |
| 5 | 法 | 需要整理策略库(分层管理)+大量回测验证 | 大 | 现有+历史回测 |
| 6 | 庙算引擎 | 前五维度基本就绪后汇总 | 中 | 前五维度输出 |

本次 P0 实现：五维评分计算层（FiveDomainFeatureComputer），使庙算引擎从中性默认值变为实际计算。按 §七 优先级分步实现各维度。

---

## 七、涉及文件

| 文件 | 操作 |
|------|------|
| `11-易经推理系统/scripts/memory_l4/five_domain_feature_computer.py` | 新增 |
| `11-易经推理系统/scripts/memory_l4/polling_trader.py` L1100 | 修改集成点 |
| `11-易经推理系统/scripts/memory_l4/test_five_domain_feature_computer.py` | 新增测试 |
| `11-易经推理系统/scripts/memory_l4/trading_utils.py` | 恢复 max_consecutive_losses=3（将维度硬规则） |
