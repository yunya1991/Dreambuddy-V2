# 54 方法库 — 数学 / 统计学 / 金融学经典确定性方法

- **版本**: v1.1 ｜ **日期**: 2026-11-14 ｜ **状态**: 🟢 首版（238 方法 + 18 关系原语）
- **扩展**: 机构方法补强见 [RESEARCH-INSTITUTIONAL-L1-METHODS.md](./RESEARCH-INSTITUTIONAL-L1-METHODS.md)（横截面 X 12、算子 O 15、风险 P 14、研究协议 Q 16）；科研统计补强见 [RESEARCH-SCIENTIFIC-METHODS.md](./RESEARCH-SCIENTIFIC-METHODS.md)（SC01–SC92），合计约 370 方法。
- **定位**: L1 的「算法选择表」。意图识别只负责选方法，方法只负责**确定性计算**，最终统一用「关系表达原语」把数据状态与价格表现对齐。
- **不做**: 不做推理、不做因果推断、不做机器学习预测、不做 LLM 生成。所有方法满足「同输入同输出」。
- **配套**: [SPEC-54](../SPEC-54-L1架构能力聚合层.md)（契约）、[TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md)（能力登记）、[数据前提](#§15-数据前提与禁区)

---

## §0 三阶流水线（本层唯一执行范式）

```
① 取数   意图 + 实体 → L0 scope（datacenter.series / market.candles / 既有 scope）
② 选法   能力清单 → 方法（本文件 §2–§10，按 §12 路由表选择，顺序固定、失败降级）
③ 表达   方法输出 → 关系原语（§11）→ 固定句式（§13）→ answer
```

**确定性等级**（三者都属确定性，区别只在是否需要样本量与分布假设）：

| 等级 | 含义 | 示例 |
|---|---|---|
| D1 | 纯算术/计数/排序，无分布假设 | 均值、次数、分位、回撤、滚动和 |
| D2 | 统计量，需要样本量，结果含抽样误差 | 相关系数、IC、t 值、Hurst |
| D3 | 拟合/检验，含模型假设，须返回诊断量 | ADF、GARCH、OLS、协整、STL |

**统一纪律**：任何 D2/D3 输出必须附带 `sample_n`；`sample_n < 30` 降级为 D1 或拒绝输出。

---

## §1 分类总览

| 类 | 代码 | 方法数 | 解决的问题 |
|---|---|---|---|
| 单维描述统计 | S | 28 | 这一列数据「是什么样」 |
| 分布形态与稳健统计 | D | 24 | 尾部、偏斜、异常、稳健中心 |
| 时间序列结构 | T | 28 | 趋势、平稳、记忆、波动聚集 |
| 季节性与日历效应 | C | 18 | 月份/星期/时段规律 |
| 技术指标 | I | 34 | 价格自身的形态量化 |
| 多变量/相关/降维 | M | 26 | 谁和谁一起动、谁领先 |
| 分箱/状态/聚合 | B | 18 | 把连续数据变成可统计的状态 |
| 金融专用 | F | 26 | 收益、风险、回撤、因子、事件 |
| 检验 | H | 18 | 这个规律是不是噪音 |
| **关系表达原语** | R | 18 | 数据状态 → 价格表现（最终出口） |

---

## §2 单维描述统计（S，28）

| ID | 方法 | 定义（简） | 输出 | 依赖 |
|---|---|---|---|---|
| S01 | 计数 | n = count(x) | n | stdlib |
| S02 | 有效样本率 | n_valid / n_total | ratio | stdlib |
| S03 | 算术均值 | Σx/n | mean | stdlib |
| S04 | 中位数 | P50 | median | stdlib |
| S05 | 众数（分箱） | 最高频箱中心 | mode | stdlib |
| S06 | 最小值/最大值 | min, max | min,max | stdlib |
| S07 | 极差 | max−min | range | stdlib |
| S08 | 方差（样本） | Σ(x−μ)²/(n−1) | var | stdlib |
| S09 | 标准差 | √var | std | stdlib |
| S10 | 变异系数 | σ/μ | cv | stdlib |
| S11 | 分位（线性插值） | Pk, k∈{1,5,10,25,50,75,90,95,99} | p1..p99 | numpy |
| S12 | 四分位距 | P75−P25 | iqr | numpy |
| S13 | 均值标准误 | σ/√n | se | stdlib |
| S14 | 置信区间（正态近似） | μ ± 1.96·se | ci_low, ci_high | stdlib |
| S15 | 变化量 | x_t − x_{t−k} | diff | stdlib |
| S16 | 变化率 | x_t/x_{t−k} − 1 | pct | stdlib |
| S17 | 对数变化 | ln(x_t/x_{t−k}) | logret | math |
| S18 | 累计变化率 | ∏(1+r)−1 | cum | stdlib |
| S19 | CAGR | (x_end/x_start)^(365/days) − 1 | cagr | stdlib |
| S20 | 滚动均值 | MA(k) | series | pandas |
| S21 | 滚动中位数 | rolling median(k) | series | pandas |
| S22 | 滚动标准差 | rolling std(k) | series | pandas |
| S23 | 滚动极值 | rolling max/min(k) | series | pandas |
| S24 | 排名/名次 | rank(x_t) | rank | pandas |
| S25 | 历史分位 | P(X ≤ x_t) | percentile | numpy |
| S26 | z-score | (x−μ)/σ | z | stdlib |
| S27 | 标准化 min-max | (x−min)/(max−min) | scaled | stdlib |
| S28 | 趋势方向 | sign(rolling slope) | up/down/flat | numpy |

---

## §3 分布形态与稳健统计（D，24）

| ID | 方法 | 定义（简） | 输出 | 依赖 |
|---|---|---|---|---|
| D01 | 偏度 | E[(x−μ)³]/σ³ | skew | scipy |
| D02 | 峰度（超额） | E[(x−μ)⁴]/σ⁴ − 3 | kurt | scipy |
| D03 | 中位数绝对偏差 | MAD = median(|x−med|) | mad | numpy |
| D04 | 稳健 z-score | 0.6745(x−med)/MAD | rz | numpy |
| D05 | 截尾均值 | 去掉上下 p% 后均值 | trimmed_mean | scipy |
| D06 | Winsorize | p1/p99 截断 | series | scipy |
| D07 | 离群标记（IQR） | x < Q1−1.5IQR 或 > Q3+1.5IQR | flags | numpy |
| D08 | 离群标记（MAD） | |rz| > 3.5 | flags | numpy |
| D09 | 经验 CDF | F(x) | cdf | numpy |
| D10 | 直方图分箱 | 等宽/等频 | bins, counts | numpy |
| D11 | 核密度估计 | KDE（高斯核） | density | scipy |
| D12 | QQ 偏离度 | 与正态分位差的最大值 | max_dev | scipy |
| D13 | 正态性检验（Jarque-Bera） | JB 统计量 | jb, p | scipy |
| D14 | 正态性检验（Shapiro） | W 统计量 | w, p | scipy |
| D15 | 分布拟合（对数正态/正态/学生 t） | 参数估计 | params, aic | scipy |
| D16 | 尾部指数（Hill） | 最高 k 个值的幂律指数 | alpha | 自实现 |
| D17 | VaR（历史法） | −P5(returns) | var95 | numpy |
| D18 | CVaR / ES | −E[r | r ≤ P5] | cvar95 | numpy |
| D19 | 最大单期跌幅 | min(returns) | worst | numpy |
| D20 | 最大回撤 | max(1 − x/cummax) | mdd, start, end | numpy |
| D21 | 回撤持续期 | 从峰到收复的天数 | duration | numpy |
| D22 | 上下行波动比 | σ_up/σ_down | ratio | numpy |
| D23 | 盈亏比 | mean(win)/|mean(loss)| | pl_ratio | numpy |
| D24 | 胜率 | count(r>0)/n | win_rate | numpy |

---

## §4 时间序列结构（T，28）

| ID | 方法 | 定义（简） | 输出 | 依赖 |
|---|---|---|---|---|
| T01 | 自相关 ACF(k) | corr(x_t, x_{t−k}) | acf[] | statsmodels |
| T02 | 偏自相关 PACF(k) | 控制中间滞后 | pacf[] | statsmodels |
| T03 | 交叉相关 CCF(k) | corr(x_t, y_{t−k}) | ccf[] | statsmodels |
| T04 | 最优领先/滞后 | argmax|CCF| | lag | numpy |
| T05 | ADF 单位根检验 | t 统计量 | stat, p | statsmodels |
| T06 | KPSS 平稳性检验 | LM 统计量 | stat, p | statsmodels |
| T07 | Ljung-Box 自相关检验 | Q 统计量 | q, p | statsmodels |
| T08 | 趋势斜率（OLS） | β from x~t | slope, r2 | statsmodels |
| T09 | 趋势显著性 | slope t 值 | t, p | statsmodels |
| T10 | STL 分解 | 趋势+季节+残差 | trend, seasonal, resid | statsmodels |
| T11 | 移动平均去趋势 | x − MA(k) | detrended | pandas |
| T12 | 差分（1 阶/季节） | Δx, Δ_s x | series | pandas |
| T13 | Hurst 指数（R/S） | 长期记忆强度 | H | 自实现 |
| T14 | 方差比检验 | VR(k) | vr, z | 自实现 |
| T15 | 波动率（年化） | std(logret)·√365 | vol | numpy |
| T16 | 滚动波动率 | rolling std(k) | series | pandas |
| T17 | 波动率聚集（ACF of |r|） | acf of abs returns | acf[] | statsmodels |
| T18 | GARCH(1,1) 拟合 | ω,α,β | params, forecast | 自实现/可选 arch |
| T19 | EWMA 波动率 | λ 加权 | series | pandas |
| T20 | 半衰期 | 均值回复速度 ln2/λ | halflife | 自实现 |
| T21 | 均值回复（OU 近似） | AR(1) 系数 | phi, halflife | statsmodels |
| T22 | 变点检测（CUSUM） | 累计偏差超界 | breakpoints | 自实现 |
| T23 | 变点检测（PELT 近似） | 最小化分段代价 | breakpoints | sklearn/rptable |
| T24 | 状态持续性 | 同状态平均停留期 | dwell | 自实现 |
| T25 | 谱分析主周期 | FFT 峰值周期 | period | numpy |
| T26 | 周期强度 | 主周期功率占比 | power_ratio | numpy |
| T27 | 分形维数（近似） | log(N(ε))/log(1/ε) | fd | 自实现 |
| T28 | 样本熵 | 序列复杂度 | sampen | 自实现 |

---

## §5 季节性与日历效应（C，18）

| ID | 方法 | 定义（简） | 输出 | 依赖 |
|---|---|---|---|---|
| C01 | 月份效应 | 按月分组的收益均值/中位数 | table[12] | pandas |
| C02 | 月份胜率 | 按月 r>0 占比 | table[12] | pandas |
| C03 | 月份次数统计 | 每月上涨次数/下跌次数 | counts[12] | pandas |
| C04 | 月份排名 | 按均值排序 | ranking[12] | pandas |
| C05 | 星期效应 | 按 weekday 分组 | table[5] | pandas |
| C06 | 小时效应 | 按小时分组（需小时线） | table[24] | pandas |
| C07 | 月内日效应 | 按 day-of-month 分组 | table[31] | pandas |
| C08 | 月初/月末效应 | 前 3 日 vs 后 3 日 | diff, t | pandas |
| C09 | 季度效应 | 按季度分组 | table[4] | pandas |
| C10 | 年内位置 | 距年初天数分位 | series | pandas |
| C11 | 节假日前效应 | 节前 N 日 vs 基准 | mean_diff | pandas |
| C12 | 半年度对比 | H1 vs H2 | diff, t | pandas |
| C13 | 季节性强度 | 季节项方差/总方差 | strength | statsmodels |
| C14 | 月份一致性 | 多年同月同向比例 | consistency | pandas |
| C15 | 月度转移 | 上月涨跌 → 本月涨跌 | matrix[2][2] | pandas |
| C16 | 同日历年分位 | 同月同日历史分布 | percentile | pandas |
| C17 | 剩余交易日统计 | 本月已实现 vs 历史同期 | compare | pandas |
| C18 | 周期对齐（多资产） | 同月跨资产同向率 | ratio | pandas |

---

## §6 技术指标（I，34）

> 数据源：`market.candles`（OKX 真实 K 线）。实现优先 `pandas_ta`（已装），缺失时 pandas 纯实现。

| ID | 方法 | 参数 | 输出 | 依赖 |
|---|---|---|---|---|
| I01 | SMA | 5/10/20/60/120 | ma[] | pandas |
| I02 | EMA | 12/26/50 | ema[] | pandas |
| I03 | WMA | 20 | wma | pandas |
| I04 | 价格相对均线位置 | close/ma−1 | pos | pandas |
| I05 | 均线排列 | ma5>ma20>ma60 | stack | pandas |
| I06 | 金叉/死叉 | ma 交叉事件 | cross | pandas |
| I07 | RSI（Wilder） | 14 | rsi | pandas_ta |
| I08 | RSI 背离 | 价格新高/RSI 未新高 | divergence | 自实现 |
| I09 | MACD | 12/26/9 | dif,dea,hist | pandas_ta |
| I10 | MACD 柱变化 | hist 环比 | delta | pandas |
| I11 | KDJ | 9/3/3 | k,d,j | pandas_ta |
| I12 | ATR | 14 | atr, atr_pct | pandas_ta |
| I13 | 真实波幅 | max(H−L,|H−C₋₁|,|L−C₋₁|) | tr | pandas |
| I14 | 布林带 | 20, 2σ | upper,mid,lower | pandas_ta |
| I15 | 布林带位置 %B | (C−L)/(U−L) | pctB | pandas_ta |
| I16 | 布林带宽 | (U−L)/mid | width | pandas |
| I17 | 量能比 | vol / MA(vol,20) | ratio | pandas |
| I18 | OBV | 量价累积 | obv | pandas_ta |
| I19 | 成交量 z-score | (v−μ)/σ | z | pandas |
| I20 | 支撑位 | 近 N 日低点聚类 | levels[] | 自实现 |
| I21 | 压力位 | 近 N 日高点聚类 | levels[] | 自实现 |
| I22 | 触碰次数 | 价格进入 ±ε 区间次数 | touches | 自实现 |
| I23 | 距支撑/压力距离 | (C−S)/C, (R−C)/C | dist | 自实现 |
| I24 | 突破事件 | C > 前高(20/60) | flag | pandas |
| I25 | 新高/新低天数 | rolling max/min | counts | pandas |
| I26 | 距 ATH 回撤 | C/max(history)−1 | dd | pandas |
| I27 | 唐奇安通道 | 20 日高低 | donchian | pandas |
| I28 | 价格动量 | C/C_{−k}−1 | mom | pandas |
| I29 | 变化率 ROC | k∈{1,5,20} | roc | pandas |
| I30 | 波动率分位 | 当前 vol 历史分位 | percentile | numpy |
| I31 | 回归通道 | 收盘价 OLS ±2σ | channel | statsmodels |
| I32 | 趋势强度 ADX | 14 | adx | pandas_ta |
| I33 | 资金流 MFI | 14 | mfi | pandas_ta |
| I34 | 换手/成交额比 | turnover/vol | ratio | pandas |

---

## §7 多变量 / 相关 / 降维（M，26）

| ID | 方法 | 定义（简） | 输出 | 依赖 |
|---|---|---|---|---|
| M01 | Pearson 相关 | ρ | r, p | scipy |
| M02 | Spearman 秩相关 | ρ_s | r, p | scipy |
| M03 | Kendall τ | τ | t, p | scipy |
| M04 | 滚动相关 | window 30/90/365 | series | pandas |
| M05 | 相关矩阵 | N×N | matrix | pandas |
| M06 | 相关矩阵排序 | 按 |ρ| 排序 TopK | list | pandas |
| M07 | 平均相关度 | 行均值（剔除自身） | score | pandas |
| M08 | 偏相关 | 控制第三变量 | r_partial | 自实现 |
| M09 | 距离相关 | dCor（非线性） | dcor | 自实现 |
| M10 | 互信息 | I(X;Y) | mi | sklearn |
| M11 | 领先滞后 CCF | lag −10..+10 | ccf[] | numpy |
| M12 | 最优滞后 | argmax CCF | lag | numpy |
| M13 | 协整（Engle-Granger） | 残差 ADF | p, beta | statsmodels |
| M14 | OLS 单因子回归 | y ~ x | beta, r2, t | statsmodels |
| M15 | 多因子回归 | y ~ X | betas, r2 | statsmodels |
| M16 | 回归残差平稳性 | 残差 ADF | p | statsmodels |
| M17 | Beta（对基准） | cov/var | beta | numpy |
| M18 | 跟踪误差 | std(r−r_b) | te | numpy |
| M19 | PCA 解释方差 | 前 k 主成分 | ratio[] | sklearn |
| M20 | PCA 载荷 | 主成分权重 | loadings | sklearn |
| M21 | 层次聚类 | 相关距离 | clusters | scipy |
| M22 | K-Means 分群 | k 组 | labels | sklearn |
| M23 | 资产同向率 | 同涨同跌天数占比 | ratio | pandas |
| M24 | 相关性稳定性 | 滚动相关标准差 | stability | pandas |
| M25 | 相关性突变 | 滚动相关 z-score | z, ts | numpy |
| M26 | 因子暴露（简化） | 对市场/规模/动量回归 | exposures | statsmodels |

---

## §8 分箱 / 状态 / 聚合（B，18）

| ID | 方法 | 定义（简） | 输出 | 依赖 |
|---|---|---|---|---|
| B01 | 等宽分箱 | k 等宽区间 | bin_id | pandas |
| B02 | 等频分箱（分位） | 五分位/十分位 | quintile | pandas |
| B03 | 固定阈值分档 | 如恐惧贪婪 0-25/26-50/… | level | stdlib |
| B04 | 状态离散化 | 规则映射（>0.5 高） | state | stdlib |
| B05 | 条件分组统计 | groupby(state) → 均值/胜率/次数 | table | pandas |
| B06 | 二维交叉表 | 状态 × 结果 | crosstab | pandas |
| B07 | 状态转移矩阵 | P(s_{t+1}|s_t) | matrix | pandas |
| B08 | 马尔可夫稳态分布 | 特征向量 | stationary | numpy |
| B09 | 同状态持续性 | 平均停留期 | dwell | pandas |
| B10 | 条件分位 | P(X|state) 分位 | percentiles | pandas |
| B11 | 分箱单调性 | 各箱均值是否单调 | monotonic | numpy |
| B12 | 分箱收益梯度 | 各箱前瞻收益差 | spread | pandas |
| B13 | 信息系数 IC | corr(factor, fwd_ret) | ic | scipy |
| B14 | Rank IC | Spearman(factor, fwd_ret) | ric | scipy |
| B15 | IC 衰减 | IC(k) 随 k 变化 | ic[] | numpy |
| B16 | 分组回测统计 | 各组分位收益 | table | pandas |
| B17 | 共现计数 | 两条件同时发生次数 | count | pandas |
| B18 | 频率表 | 事件频次分布 | freq | pandas |

---

## §9 金融专用（F，26）

| ID | 方法 | 定义（简） | 输出 | 依赖 |
|---|---|---|---|---|
| F01 | 简单收益 | P_t/P_{t−1}−1 | r | pandas |
| F02 | 对数收益 | ln(P_t/P_{t−1}) | lr | numpy |
| F03 | 区间收益 | P_end/P_start−1 | ret | numpy |
| F04 | 年化收益 | (1+r)^(365/d)−1 | ann | numpy |
| F05 | 年化波动 | σ·√365 | vol | numpy |
| F06 | 夏普比率 | (μ−rf)/σ | sharpe | numpy |
| F07 | 索提诺比率 | (μ−rf)/σ_down | sortino | numpy |
| F08 | 卡玛比率 | 年化收益/|MDD| | calmar | numpy |
| F09 | 最大回撤 | 见 D20 | mdd | numpy |
| F10 | 回撤恢复时间 | 见 D21 | days | numpy |
| F11 | 收益偏度/峰度 | 见 D01/D02 | stats | scipy |
| F12 | 自相关（收益） | ACF(1..5) | acf | statsmodels |
| F13 | 波动率聚集 | |r| 的 ACF | acf | statsmodels |
| F14 | 风险调整动量 | 收益/波动 | ratio | numpy |
| F15 | 相对强弱 RS | P/P_benchmark | ratio | pandas |
| F16 | 动量排序 | 跨资产 k 期收益排名 | ranking | pandas |
| F17 | 反转统计 | 上期涨→本期跌比例 | ratio | pandas |
| F18 | 连胜/连败 | 连续同向最大长度 | streak | pandas |
| F19 | 事件窗收益 | t−k..t+k 累计收益 | car | pandas |
| F20 | 异常收益 AR | r − E[r] | ar | numpy |
| F21 | 累计异常收益 CAR | ΣAR | car | numpy |
| F22 | 事件次数统计 | 同事件历史发生次数 | count | pandas |
| F23 | 事件后分布 | 事件后 k 日收益分布 | dist | pandas |
| F24 | 资金费率年化 | rate·3·365 | apr | numpy |
| F25 | 基差 | (futures−spot)/spot | basis | numpy |
| F26 | 拥挤度合成 | 三分位加权（固定权重） | score | numpy |

---

## §10 检验（H，18）

| ID | 方法 | 用途 | 输出 | 依赖 |
|---|---|---|---|---|
| H01 | 单样本 t 检验 | 均值是否 ≠ 0 | t, p | scipy |
| H02 | 双样本 t 检验 | 两组均值差 | t, p | scipy |
| H03 | Welch t 检验 | 方差不等 | t, p | scipy |
| H04 | Mann-Whitney U | 非参数两组差 | u, p | scipy |
| H05 | Wilcoxon 符号秩 | 配对差 | w, p | scipy |
| H06 | 卡方独立性 | 交叉表关联 | chi2, p | scipy |
| H07 | 方差分析 ANOVA | 多月/多组均值 | f, p | scipy |
| H08 | Kruskal-Wallis | 非参数多组 | h, p | scipy |
| H09 | 自相关检验 | 见 T07 | q, p | statsmodels |
| H10 | 单位根检验 | 见 T05 | stat, p | statsmodels |
| H11 | 协整检验 | 见 M13 | p | statsmodels |
| H12 | 正态性检验 | 见 D13/D14 | p | scipy |
| H13 | 多重比较校正（Bonferroni） | p·m | p_adj | 自实现 |
| H14 | 多重比较校正（BH-FDR） | 排序阈值 | q | 自实现 |
| H15 | 置换检验 | 打乱标签重算 | p_perm | numpy |
| H16 | Bootstrap 置信区间 | 重采样 | ci_low, ci_high | numpy |
| H17 | 效应量（Cohen d） | 均值差/合并σ | d | numpy |
| H18 | 统计功效（近似） | 1−β | power | 自实现 |

> 纪律：L1 输出检验结果时必须同时给出 `n`、`p` 与「是否达到常用阈值（0.05）」，**不得**把 `p<0.05` 表述为因果。

---

## §11 关系表达原语（R，18）— 本层的最终出口

> 目标：把「数据处于什么状态」映射为「价格在同一时空下的表现」，只描述历史统计事实，不含预测措辞。

| ID | 原语 | 输入 | 输出（固定字段） | 典型问法 |
|---|---|---|---|---|
| R01 | 条件收益统计 | 状态分组 × 前瞻收益 | `mean, median, win_rate, n, t` | 「资金费率高的时候后续涨吗」 |
| R02 | 分位→前瞻收益 | 当前分位 × fwd 1/3/5/10/20d | `by_horizon[]` | 「恐惧贪婪 20 分位历史上之后怎么走」 |
| R03 | 日历效应表 | 收益 × 月份/星期 | `table[], best, worst, counts` | 「历史上几月份上涨最高、各几次」 |
| R04 | 事件研究窗 | 事件日 × [−5,+10] | `ar[], car, n` | 「FOMC 后 10 天表现」 |
| R05 | 相关矩阵 TopK | 多资产收益 | `pairs[], rho` | 「哪些资产相关性最高」 |
| R06 | 领先滞后 | 双序列 | `best_lag, ccf[]` | 「CPI 领先还是滞后于 BTC」 |
| R07 | 状态转移 | 离散状态序列 | `matrix, next_dist` | 「高波动之后通常进入什么状态」 |
| R08 | 分箱单调性 | 因子 × 前瞻收益 | `bins[], monotonic` | 「这个指标越高后续越好吗」 |
| R09 | 计数表达 | 事件序列 | `up_n, down_n, total` | 「涨了几次」 |
| R10 | 共现频次 | 两条件 | `count, ratio` | 「CPI 超预期且资金费率为负，几次」 |
| R11 | 回撤画像 | 价格序列 | `mdd, duration, recoveries` | 「历史最大回撤多久恢复」 |
| R12 | 极值后表现 | 极值事件 | `fwd_dist, n` | 「历史新高之后」 |
| R13 | 波动率状态→收益 | 波动分位 × fwd | `buckets[]` | 「高波动期收益分布」 |
| R14 | 相关性突变 | 滚动相关 | `z, current, history_avg` | 「相关性是不是异常」 |
| R15 | 季节性一致率 | 多年同月 | `consistency[12]` | 「这个月份规律稳不稳」 |
| R16 | 跨资产同向率 | 多资产 | `ratio, n` | 「美股和 BTC 同涨概率」 |
| R17 | 水平对比 | 两期/两资产 | `diff, pct, rank` | 「现在比历史高多少」 |
| R18 | 时空对齐切片 | 时间窗 × 资产 | `window_rows[]` | 「同一时间段各资产表现」 |

**统一输出强制项**：`n`、`window`、`sample_n`、`is_significant`（仅 D2/D3）、`caveat`（"历史统计，不代表未来"）。

---

## §12 意图 → 方法路由（固定顺序，可降级）

| 意图 | 主方法（按序尝试） | 关系原语 | 数据前提 |
|---|---|---|---|
| metric_series | S15–S19, S25, T08, T15 | R17 | 单序列 ≥30 点 |
| metric_percentile | S25, S26, D09 | R02 | 序列 ≥250 点（分位稳定） |
| metric_meaning | S25 + 释义库 | R17 | 单点 + 历史 |
| seasonality_query | C01–C04, C16, H01, H13 | R03, R15 | 日/月收益 ≥3 年 |
| calendar_query | C05–C09, H01 | R03 | 日收益 ≥2 年 |
| correlation_query | M01–M07, M11–M12 | R05, R06 | 双序列对齐 ≥60 点 |
| conditional_return | B02/B03/B05, F01, H01 | R01, R08 | 因子 + 价格 ≥250 点 |
| event_study | F19–F23, H01 | R04 | 事件表 + 价格 |
| state_transition | B04, B07–B09 | R07 | 状态序列 ≥100 点 |
| drawdown_query | D20–D21, F09–F10 | R11 | 价格序列 ≥250 点 |
| technical_indicator | I01–I34（先 I01/I07/I12/I17） | R08, R13 | candles ≥120 根 |
| cross_check | M23–M25, C18 + 既有 6 scope | R14, R16 | 多资产对齐 |
| relationship_recommend | 只读 MERS 注册表（§14），不实时计算 | —（输出 method_id + 门禁字段） | 注册表存在 |
| discovery_query | 只读最新 Discovery 报告（§15），不实时搜索 | —（输出 candidate 列表） | 报告存在 |

**选择规则**（确定性，无模型）：

1. 别名命中指标 → 取该指标序列；
2. 问题类型词命中（走势/分位/几月/相关/之后/几次/回撤/背离）→ 选对应方法组；
3. 样本量不足 → 降级到 D1 原语（只给均值/计数/当前值）并标注 `insufficient_samples`；
4. 多方法冲突 → 按表格顺序取第一个满足样本要求者；
5. 任何 D3 方法（GARCH/协整/STL）默认不启用，除非显式问「模型/检验」。

---

## §13 输出模板（固定句式，禁止推理措辞）

| 原语 | 模板 |
|---|---|
| R03 | 「{资产} 近 {N} 年按月统计：{月} 月平均 {x}%、上涨 {u}/{n} 次，最高为 {月}，最低为 {月}。」 |
| R01 | 「历史 {N} 次「{状态}」后 {h} 日：均值 {x}%、中位 {y}%、上涨 {u}%（n={n}，t={t}）。」 |
| R05 | 「与 {资产} 相关性最高：{A}({ρ})、{B}({ρ})、{C}({ρ})（窗口 {w}）。」 |
| R02 | 「当前 {指标} 处于 {p}% 分位；历史上同分位区间后 {h} 日：均值 {x}%、上涨 {u}%（n={n}）。」 |
| R09 | 「历史上 {事件} 后上涨 {u} 次、下跌 {d} 次，共 {n} 次。」 |
| R17 | 「当前 {指标} {x}{unit}，较 {基准} {±y}%，处于近 {N} 年 {p}% 分位。」 |

统一尾注：`数据：{source}；样本：{n}；截至：{ts}。历史统计不代表未来。`

---

## §14 实现优先级与依赖

| 阶段 | 方法 | 说明 |
|---|---|---|
| **P1a**（已有依赖即可） | S 全部、D20–D24、T08/T15–T16、C01–C04、M01–M07、B01–B05、F01–F06、H01/H13 | numpy/pandas/scipy 足够 |
| **P1b** | I01/I07/I12/I17（pandas_ta）+ `market.candles` | 需 K 线 scope |
| **P2a** | M11–M12、F19–F23、B07–B09、R01/R04/R07 | 需事件表/状态序列 |
| **P2b** | T05/T10/T13、H15–H16、M13/M19–M21、B13–B15 | statsmodels/sklearn |
| **延后** | T18 GARCH（arch 未装）、T23 PELT、T28 样本熵 | 依赖可选库或自实现 |

**可选库评估**（本地实测）：`numpy/pandas/scipy/statsmodels/sklearn/pandas_ta/talib/bottleneck` 已具备；`arch/quantstats/empyrical/pyfolio/sktime/tsfresh` 未装 —— 前三项对应的核心能力均可用 `pandas+scipy` 等价实现，**不新增依赖**。

---

## §15 数据前提与禁区

**前提（实测）**

| 数据 | 现状 | 支撑方法 |
|---|---|---|
| 宏观/链上/衍生品时序（`mm_metrics`） | 348,543 行，455 指标，部分回溯至 1962 | S/T/C/M/F 绝大多数 |
| 价格长历史 | **库内仅约 2 周**（`bitcoin.current_price_usd` 51 点） | ❌ 需补：OKX `history-candles` 回填 或 CoinGecko chart 回填 |
| 真实 K 线 | 未落库，可现取 OKX | I 组 + 日频统计 |
| 事件表 | `mm_events` 仅 16 行 | R04/F19–F23 受限 |

> **P1 前置**：做季节性/相关/事件研究前，必须先补「日频价格历史」（≥3 年）。否则这类能力只能给出 `insufficient_history`。

**禁区**

| 禁止 | 原因 |
|---|---|
| 因果推断表述（"导致""因为"） | 本层只做统计关联 |
| 未来外推（"将会""预计"） | 非确定性 |
| 机器学习预测输出 | 属 L2 |
| 合成/随机数据参与统计 | 会产生假规律 |
| 无样本量披露的结论 | 违反 D2/D3 纪律 |
| 多重比较不校正 | G 组按月×按资产扫描必须 Bonferroni/FDR |
