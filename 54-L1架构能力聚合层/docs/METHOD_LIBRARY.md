# 54 方法库 — 数学 / 统计学 / 金融学经典确定性方法

- **版本**: v1.14 ｜ **日期**: 2026-11-15 ｜ **状态**: 🟢 方法清单全部落地（核心 238 + 调研族 149 = 目录 387；已实现 **386**，仅 C11 因缺交易日历登记不可用）；v1.14 接入 D-E12/R18 时空对齐切片，可执行出口 **10 个**，方法口径不变；v1.13 接入 D-E01 与 D-E11/C18，MERS S3 内部计算内核已交付且不改变方法口径；v1.12 D-E02 能力出口接线与 T0.5/A8 首版交付；v1.11 补齐 X/O/P/Q/SC 149 条与核心 66 条真实实现，audit **386/386 PASS**、测试 **666 例全绿**；v1.10 放开注册表校验支持调研族前缀并完成占位登记；v1.9 调研对齐：新增 R02 `pit=false/pit=true` 双口径与 T0.5 合法输入边界，路线修正为 S0–S7，明确能力出口仅覆盖登记范围子集及 h>1 的 Newey-West/HAC 前置；v1.8 新增 §16「日线收盘锚点」冻结口径（1d `ts`=UTC 日首、`bar_close`/`snapshot_last`、跨资产同锚点）；v1.3 增 §0.1 四层边界与 §16 口径冻结；v1.4 修正 §14/§15 过期数据事实，新增三套路线编号映射；v1.5 S3 批 22 方法落地（`l1agg/methods/conditional.py`，audit 45/45 PASS）并补 §16 冻结口径；v1.6 S6 批 62 方法落地（`descriptive.py`/`timeseries.py`/`inference.py`，audit 154/154 PASS，测试 349 例全绿）并补 §16 冻结口径；v1.7 C 组 17 方法落地（`seasonal.py`，audit 171/171 PASS，测试 393 例全绿）并新增 S7 能力层接线（`l1agg/capabilities/` + `capability_manifest.yaml`）
- **扩展**: 机构方法补强见 [RESEARCH-INSTITUTIONAL-L1-METHODS.md](./RESEARCH-INSTITUTIONAL-L1-METHODS.md)（横截面 X 12、算子 O 15、风险 P 14、研究协议 Q 16）；科研统计补强见 [RESEARCH-SCIENTIFIC-METHODS.md](./RESEARCH-SCIENTIFIC-METHODS.md)（SC01–SC92）。**149 条已全部实现并登记**（`l1agg/methods/research_*.py`），目录合计 387 条 = 核心 238 + 调研族 149，已实现 386 条。
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

> `market.candles` 为 S1 新增 scope（2026-11-14 落地，1D/1W/1M 由 `mm_metrics` 日频价格派生）；OHLC 于同日接入：`1h` 取 `{symbol}/USDT` 小时级 `last/high/low`（三腿齐全才输出），`1d/1w/1m` 合并同源 high/low 桶内极值（仅全桶覆盖才 `has_ohlc=true`，不伪造）。库内高低点为 ccxt ticker 24h 滚动口径（meta.ohlc_note 标注），1D 覆盖率不足时 L1 回退 1H。仍缺 OHLC 的标的/周期，I 组必须显式返回 `insufficient_history`。

**确定性等级**（三者都属确定性，区别只在是否需要样本量与分布假设）：

| 等级 | 含义 | 示例 |
|---|---|---|
| D1 | 纯算术/计数/排序，无分布假设 | 均值、次数、分位、回撤、滚动和 |
| D2 | 统计量，需要样本量，结果含抽样误差 | 相关系数、IC、t 值、Hurst |
| D3 | 拟合/检验，含模型假设，须返回诊断量 | ADF、GARCH、OLS、协整、STL |

**统一纪律**：任何 D2/D3 输出必须附带 `sample_n`；`sample_n < 30` 降级为 D1 或拒绝输出。

### §0.1 与其他三层的边界（禁止在本文件新增"场景"）

| 层 | 载体 | 是否产生新方法 ID |
|---|---|---|
| 方法层（本文件） | 方法 ID `T13`/`M01`/`B13`… + 关系原语 `R01–R18` | **是，唯一 SSoT** |
| 能力层 | [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) 能力登记 `D-*` + [SPEC-54](../SPEC-54-L1架构能力聚合层.md) 契约 | 否（组合 + 绑 scope/意图） |
| 场景包 | [SPEC-54-延续性统计分析模块.md](../SPEC-54-延续性统计分析模块.md)（`D-E13` 延续性画像） | **否**（A1–A7 全部映射既有 ID；只做编排、统一降级与文本模板） |
| 评估层 | SPEC-54 §14 MERS / §15 Discovery / §17.1.3 S5 | 否（批量跑上述方法并评分） |

因此：Hurst(T13) 的口径只在 §2 / §16 定义一次；画像模块不得重定义，能力登记不得重命名，MERS 不得另写一份实现。方法口径变更后，必须回写场景包测试与 MERS 网格版本。

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

> **注册表口径（v1.11）**：核心目录 238 = 10 组容量；调研族 149 = X12 + O15 + P14 + Q16 + SC92。`REGISTRY` 实际登记 **387** 条（核心 238 + 调研 149），其中 `implemented=true` **386** 条；`implemented=false` 仅 **1** 条（C11 缺交易日历/节假日表，按纪律登记不可用）。`all_specs(scope=...)` 支持 `core`(238)/`research`(149)/`all`(387)，默认 `core` 以保持 `catalog_total == 238`。

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
| R02 | 分位→前瞻收益 | 当前分位 × fwd 1/3/5/10/20d | `by_horizon[]`；目标契约补 `pit/as_of/effective_n/nonoverlap_n/window/align_method` | 「恐惧贪婪 20 分位历史上之后怎么走」 |
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

**统一输出强制项**：`n`、`window`、`sample_n`、`is_significant`（仅 D2/D3）、`caveat`（"历史统计，不代表未来"）。R02 另须按 §16.1 披露 PIT 口径；`pit=false` 只能标注为样本内回顾，不得进入 T0.5/T2/MERS。

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
| R02 | `pit=true`：「截至 {as_of}，当前 {指标} 处于 {p}% 分位；按当时可见数据识别的历史同分位区间后 {h} 日：均值 {x}%、上涨 {u}%（有效 n={effective_n}，非重叠 n={nonoverlap_n}）。」；`pit=false` 必须改写为「样本内回顾（全样本分位，含未来函数，不用于条件外推）……」，禁止共用条件外推措辞 |
| R09 | 「历史上 {事件} 后上涨 {u} 次、下跌 {d} 次，共 {n} 次。」 |
| R17 | 「当前 {指标} {x}{unit}，较 {基准} {±y}%，处于近 {N} 年 {p}% 分位。」 |

统一尾注：`数据：{source}；样本：{n}；截至：{ts}。历史统计不代表未来。`

---

## §14 实现顺序与依赖（v1.2 重排：按「数据纵深 → 对齐 → 相关 → 条件 → 排名 → 扩展」）

| 阶段 | 方法 | 前置 | 门禁（不满足不得进入下一阶段） |
|---|---|---|---|
| **S0**（已完成） | S15–S19 + R17（单序列直答）；`metric_series` 执行器 | `datacenter.series` | 已上线；但 `timeseries` 贯通未验收（前端 `src/app/api/fundamental/[...path]/route.ts` 仍硬编码 `[]`） |
| **S1** 价格轴 + 对齐层 | 无新方法；新增 `market.candles`（1D/1W/1M）+ `l1agg/align.py` | 价格 ≥1,090 日（已具备） | 任一 D2/D3 输出必带 `sample_n/span/align_method/timezone`；对齐后缺失率 <5% |
| **S2** 相关性 | M01–M07、M11–M12、M24–M25；R05/R06 | S1 + 指标历史 **≥60 对齐点** | `n≥60` 才出同期相关；`n≥120` 才出 CCF；p 值 + 多重比较修正；随机序列 \|ρ\|<0.1 且不显著 |
| **S3** 条件收益 / IC / 分组（✅ 方法层已交付 2026-11-14；能力出口部分完成） | S11/S25/S26、F01–F06、B01–B03/B05/B11–B16、H01、R01/R02 共 22 方法（`l1agg/methods/conditional.py`） | S2 + 指标历史 **≥250 对齐点**（分布/收益类 ≥30） | `n≥250` 才出条件统计/IC/分组；前瞻收益统一走 `align.forward_returns`（方法内禁止位移）；B15 复用 §16 冻结 `ic_decay`；分箱单调性与分组价差必须同时输出；R02 双口径已实现（`pit=true` 见 §16.1），D-E02 能力出口已接线（v1.12） |
| **S4** 条件外推表达 | R01/R02/R08/R11 模板化；T0.5=S3→S4，首版 h=1、4 个 PIT 分位桶 | S3；T0.5/T2 另需 R02 `pit=true` | 必须含区间、样本量与 `pit/as_of/effective_n/nonoverlap_n`；禁止点预测措辞；h>1 重叠前瞻收益及趋势显著性推断前必须实现 Newey-West/HAC，否则只描述、不作显著性结论 |
| **S5** 回测排名 | B13–B16 的产物（复用并修正 23 `FactorICSelector`） | S3 + 样本外切分 | 排名必须含样本外 IC 与 walk-forward；仅 in-sample 排名不得对外 |
| **S6** 方法扩展（✅ 方法层已交付 2026-11-14，62 方法） | S01–S10/S12–S24/S27/S28（26）、D01–D13/D16–D24（22）、T01–T04/T07–T09/T11–T17/T19–T22/T24/T27/T28（21）、F07–F14/F17/F18/F20/F21（12）、H02–H08/H13–H18（13）、B04/B06–B10/B17/B18（8）、M17/M23（2）、R08–R11/R16/R17（6）→ `l1agg/methods/descriptive.py` / `timeseries.py` / `inference.py`；I 组（需 OHLC）、T05/T06/T10/T18/T23/T25/T26、D14/D15 已于 v1.11 补齐实现 | S2/S3 | 复用同一注册表与统一门禁；D2/D3 输出必带 `sample_n`；T13/T14/T20/T21/T24/F18 只调用 `persistence.metrics`，禁止重写口径 |
| **S7** 能力层接线（✅ 10 个可执行出口已交付 2026-11-15；登记范围部分完成） | C 组 17 方法（`l1agg/methods/seasonal.py`，C11 缺交易日历登记不可用）；能力层 `l1agg/capabilities/{manifest,envelope,stats}.py` + `capability_manifest.yaml` + `contracts/capability_result.schema.json`：D-E01/E02/E03/E05/E06/E07/E08/E10/E11/E12 端到端；D-E05 双序列与矩阵 TopK、D-E11/C18、D-E12/R18 均已接线 | S2/S3 + 价格 ≥250 点 | 能力只能绑 `implemented=true` 方法（`manifest.validate`）；样本不足 → `status=partial/empty` + `degraded_reason`，禁止伪造数值；`quality` 只在信封顶层；10 个出口不得表述为登记范围全部完成 |

**与旧版（P1a/P1b/P2a/P2b）差异**：旧版按「依赖库是否就绪」分组，忽略了**指标历史纵深**这一真实瓶颈——实测仅 26 条序列可与 BTC 日频价格对齐 ≥60 天，加密域指标只有 14–44 天。新版按**样本量门禁**分组，样本不足一律降级为 D1 并标 `insufficient_samples`。

**缺口前置（非方法本身）**：S2 必须覆盖**跨资产**（加密/贵金属/能源/工业金属/美股指数/美股 ETF/美股龙头/亚太/外汇/利率信用），分类与 40 层统一；回填由 18 完成（`coinglass` 的 `limit=7` 参数化分页、`stablecoin` `days` 放开、Farside ETF 全表落库、Binance `fundingRate` 按 `startTime` 回溯、stooq/yahoo 补 DJIA 与美股个股）。**当前 `l1agg/leader_registry.BINDINGS` 已绑定 28 个龙头、诚实登记 1 个历史不足（JP225 `not_collected`）**——纵深明细见 §15，本文不重复。

**三套路线编号的映射（禁止混用）**：

| 编号体系 | 出处 | 用途 | 与本表关系 |
|---|---|---|---|
| `S0–S7` | 本文件 §14 | **方法实施与能力接线阶段**（按样本量门禁切分） | 本表自身 |
| `S1–S5` | SPEC-54-L1 §17.1 | **能力交付阶段**（含 scope 与契约） | S0→S0；S1→S1；S2→S2；S3→S3；S4→S4；S5→S5；本表 S6 在 SPEC 中散落于 S2/S3 的扩展项，S7 是 S2/S3 方法的可执行能力接线 |
| `T0–T4` | 延续性场景包 / 调研 §7 | **场景包阶段**（仅延续性） | T0 = SPEC S3 自身延续性子集；**T0.5 = S3→S4**；T1a → S3 前置；T1b → SPEC S2 + S3 前置；T2 → SPEC S4；T3/T4 → SPEC S5 及之后 |

**可选库评估**（本地实测）：`numpy/pandas/scipy/statsmodels/sklearn/pandas_ta/talib/bottleneck` 已具备；`arch/quantstats/empyrical/pyfolio/sktime/tsfresh` 未装 —— 前三项对应的核心能力均可用 `pandas+scipy` 等价实现，**不新增依赖**。

---

## §15 数据前提与禁区

**前提（2026-11-14 实测，云端快照只读核对）**

| 数据 | 现状 | 支撑方法 |
|---|---|---|
| 日频价格 | ✅ `BTC/ETH/SOL/XAU close_usd` 各 **1,094 点**，2023-11-15 ~ 2026-11-12（约 3 年，缺口 0） | S/T/C/F/M 的价格腿全部可用 |
| 日内价格 | ⚠️ `BTC/USDT last/high/low` 小时级 922 点（2026-09-28 起）；高低点为 ccxt ticker 24h 滚动口径 | `market.candles` 支持 1H（原生）+ 1D/1W/1M（OHLC 合并，覆盖不足不冒充） |
| 宏观时序（FRED） | ✅ 19 条序列与近 3 年价格窗口重叠 ≥250 天（`DGS10` 16,206 天、`NASDAQCOM` 14,066 天…） | 宏观腿的相关/季节/条件收益可用 |
| 跨资产龙头（分类 SSoT = 40 `asset_classes.py`） | ✅ **28 个已绑定**（`leader_registry.BINDINGS`，2026-11-14 核实）：BTC/ETH/SOL/XAU 各 1,094 点，另有 CL 9,545(WTI 代理)、US500 2,521、US100 14,066、DXY 5,235、TLT 16,206(DGS10 代理)、T10Y2Y 12,607、HY_OAS 784、VIX 9,320、CPI 1,009、INDPRO 1,346 等；❌ 1 个诚实登记未采集：JP225（`not_collected`） | ✅ 跨类相关/条件收益主干可用（≥60 对齐点仅 26 条）；❌ 深度仍偏浅 |
| 加密域指标（衍生品/ETF/交易所/链上/稳定币） | ❌ 仅 14–44 天：`derivatives_spot`/`etf_institutional`/`exchanges_whales`/`holdings_onchain_funds`/`stablecoin_rwa` = 28 天；`options` 44、`funding_rate` 40、`btc_onchain` 37、`etf_flow` 14、`okx_derivatives` 8 | ❌ 这些「类内」指标需先回填（龙头价格腿已够） |
| 专用表（`mm_funding_rate`/`mm_open_interest`/`mm_liquidation`/`mm_long_short_ratio`/`mm_taker_volume`/`mm_fear_greed`） | ❌ 本地快照 **0 行** | 同上 |
| 全库序列纵深 | 27,290 个 `sub::metric` 中 **25,795 个仅 1 天**；≥250 天 28 条；与 BTC 日频重叠 ≥60 天仅 **26 条** | 决定当前相关性因子池上限 |
| 事件表 | ❌ `mm_events` 仅 16 行 | R04/F19–F23 受限 |
| 真实 K 线 | 未落库，18 `price_source.py` 已有 OKX `history-candles` 分页 + Binance `klines` 兜底 | I 组 + 日频统计 |

> **前置修正（v1.2）**：真实瓶颈是**指标历史纵深**，不是价格。价格腿已满足 3 年要求；相关性要等**跨资产历史回填**（龙头已 14 条达标，缺口为道指/美股个股/ETF/工业金属/天然气/布油）。样本不足时一律降级为 D1 并标 `insufficient_samples`，禁止输出相关性。
>
> **跨资产口径（v1.2）**：分类 SSoT = 40 `asset_classes.py`（`ASSET_CLASSES`/`G1_ANCHORS`/`G0_MACRO`）；54 只在 `l1agg/leader_registry.py` 做「龙头 → DAL 序列」绑定，代理序列（CL/DXY/US500/US100/TLT）标 `proxy=True`，未采集项登记在 `UNBOUND` 并由 `align.load_leader()` 抛 `not_collected`。**新增龙头只需加一行绑定即可进入对齐层与相关性，无需改方法层**。

**禁区**

| 禁止 | 原因 |
|---|---|
| 因果推断表述（"导致""因为"） | 本层只做统计关联 |
| 未来外推（"将会""预计"） | 非确定性 |
| 机器学习预测输出 | 属 L2 |
| 合成/随机数据参与统计 | 会产生假规律 |
| 无样本量披露的结论 | 违反 D2/D3 纪律 |
| 多重比较不校正 | G 组按月×按资产扫描必须 Bonferroni/FDR |

---

## §16 已实现方法的冻结口径（v1.6 起，持续增补）

> 本表是**口径 SSoT**：场景包（`D-E13` 延续性画像）与 MERS 只引用、不重定义；方法口径变更须同步 `tests/test_persistence.py` 与 MERS `grid_hash`。

| 方法 ID | 冻结口径 | 输入 | 冻结参数 | 代码位置 |
|---|---|---|---|---|
| T13 Hurst（R/S） | 输入**收益序列**（价格直算会得 H≈1.5）；分块 `8,16,…,min(n/2,256)`；每块 R/S 取均值；简化 Anis-Lloyd 修正 `(k−0.5)/k`（不含 k>340 长段修正）；`log(R/S)~log(k)` OLS 斜率；`n<2000` 标 `confidence=low` 且不展示 regime | returns | `min_chunk=8, max_chunk=256, corrected=True` | `l1agg/persistence/metrics.py::hurst_rs` |
| T14 VR(q) | `VR=Var(q期收益和)/q/Var(1期)`；同方差 z；正态近似 p；下溢截断 `1e-12`（禁止输出 0） | returns | `q∈{2,5,10,20}` | `metrics.py::variance_ratio` |
| T20/T21 AR(1)/半衰期 | `φ=corr(r_t,r_{t+1})`；`half=ln0.5/ln\|φ\|`，`\|φ\|≥1` 返回 `null` | returns | — | `metrics.py::ar1_halflife` |
| F18 连胜/连败 | 按收益符号切 run；`r==0` **跳过**并计入 `n_zero` | returns | — | `metrics.py::run_length_stats` |
| B07/B08 状态转移 | 2×2 计数行归一；**仅方向态（涨/跌）**，波动 regime 归 T0.5/T1a；`r==0` 跳过；`π_up=p_du/(p_ud+p_du)`；停留期 `1/p_switch` | returns | 非零样本 ≥30 | `metrics.py::transition_matrix` |
| T08/T09 趋势斜率 | `ln(price)~t` OLS；输出 `slope/se/t/r2`；**未做 HAC**，`hac_corrected=false`，仅相对比较 | prices | — | `metrics.py::trend_slope` |
| B13–B15 IC 衰减 | 因子=过去 `lookback` 期收益，目标=h 期前瞻收益；Spearman；重叠 + **h 个相位非重叠**（均值/极差） | prices | `lookback=20, h∈{1,5,20}` | `metrics.py::ic_decay` |
| R02 前瞻收益 | `fwd[i]=P[i+h]/P[i]−1`，**无额外位移**；与 23 `FactorICSelector` 的旧实现不等价 | prices | `h≥1` | `l1agg/align.py::forward_returns` |
| S11 分位 | `pos=q×(n−1)` 线性插值，与 numpy `percentile(method="linear")` 同口径 | series | `q∈{1,5,10,25,50,75,90,95,99}` | `methods/conditional.py::s11_percentiles` |
| S25 历史分位 | `100×count(X≤x_last)/n`（PIT，无未来函数） | series | 取末点 | `conditional.py::s25_percentile` |
| S26 z-score | 先 winsorize p1/p99 再算 μ/σ（ddof=1），z 取末点；σ≤1e-12 → `null` | series | `winsorize=True` | `conditional.py::s26_zscore` |
| F01–F06 收益/风险 | F01 复用 `align.simple_returns`；F02 `ln(P_t/P_{t−1})`；F04 `(1+μ)^365−1`；F05 `σ√365`；F06 `(ann−rf)/ann_vol`，σ=0 → `null` | series | 年化因子 365，`rf=0` | `conditional.py::f01_simple_return` … `f06_sharpe` |
| B01/B02/B03 分箱 | B01 等宽 `min(int((v−lo)/w), k−1)`；B02 边=线性插值分位（左闭右开、末桶闭合）；B03 阈值由参数给出（`level=count(th<v)`），不写死在数据里 | series | `B01 k=10`、`B02 k=5`、`B03 th=(25,50,75)` | `conditional.py::b01_width_bins` / `b02_quantile_bins` / `b03_threshold_levels` |
| B05/R01 条件分组 | state×target 分组统计；R01 句式固定「历史 N 次「state」后 h 日：均值/中位/上涨占比（n, t）」；同 n 取表内首个最大组 | state+target | `min_n=250, h=1` | `conditional.py::b05_conditional` / `r01_conditional_phrase` |
| B16/B11/B12 分组统计 | factor 按线性插值分位分 k 组；组内 均值/中位/胜率/n；`spread`=最高组−最低组；B11 仅组均值**严格**单调才 `increasing/decreasing`，`rho_bin`=Spearman(桶序, 组均值) | factor+target | `k=5, min_n=250` | `conditional.py::b16_group_stats` / `b11_monotonic` / `b12_gradient` |
| B13/B14 IC / Rank IC（方法层） | target 必须由 §16 `forward_returns` 产出后传入，**方法内不做位移**；B13=Pearson、B14=Spearman，p 走 t 分布 | factor+target | `min_n=250` | `conditional.py::b13_ic` / `b14_rank_ic` |
| B15（方法层） | 直接调用 §16 `metrics.ic_decay`，仅补 `nonoverlap_gate` 标记，**不复制口径** | prices | `lookback=20, h∈{1,5,20}` | `conditional.py::b15_ic_decay` |
| H01 单样本 t | `t=μ/(s/√n)`，p 走 t 分布（df=n−1）；`p<0.05` 仅表述为显著，不表述因果 | series | `min_n=30` | `conditional.py::h01_one_sample_t` |
| R02（方法层，双口径均已实现） | `pit=false`：末点与全部历史样本共用一组全样本分位边界（非滚动）→ 同分位桶内 h 期前瞻收益，只作样本内回顾；`pit=true`：逐时点滚动分位 + `release_ts≤as_of` 过滤，T0.5/T2/MERS 唯一合法口径（见 §16.1）。桶=等频 `buckets=10`；前瞻收益复用 §16 `forward_returns` | indicator+price（`pit=true` 可选 `timestamps/release_ts`） | `pit=false/true, buckets=10, h∈{1,3,5,10,20}, window≥2` | `conditional.py::r02_percentile_forward` |
| S1-c 价格回显（asof） | 取 `<= 目标日` 的最近价格点（UTC 日收盘，**禁止未来函数**）；输出当时价/现价/变化 + `asof_day/staleness_days/sample_n/span/align_method/timezone/gate` | prices + 目标日 | `max_stale_days=3` | `l1agg/price_echo.py::price_echo` |
| 默认价格基准（硬约束） | 加密→BTC；美股个股/ETF/股指→US500(US100/DJIA)；美联储/宏观→XAU(US500/US100)；大宗商品→CL(BZ/NG)；避险→XAU；未分类→BTC | `sub_category/metric_name` 或资产类别 | 关键词表 `_KEYWORD_GROUPS` | `l1agg/price_echo.py::resolve_anchor` |
| 方法注册表 | 每方法 `MethodSpec(method_id/group/layer/input_kind/min_n/output_schema)` + `run()` 统一门禁；未实现方法按 §1 容量生成占位（`implemented=False`），禁止空壳冒充 | 方法 ID | 重复登记报错；占位方法调用抛 `MethodUnavailable` | `l1agg/methods/registry.py` |
| 自动评估 harness | 六检：meta / gate / determinism / synthetic / null / reference；产物 `docs/method_audit.json` | 已登记方法 | 随机白噪声假阳率 ≤20%、合成解命中；失败方法不得进入选法 | `l1agg/eval/harness.py`、`scripts/method_audit.py` |
| S 组描述统计（v1.6） | 方差/标准差 `ddof=1`；分位线性插值（同 S11）；S05/S10 等宽分箱 `k=10`；S14 `μ±1.96·se`；S18 `is_returns=False` 用价格比、`True` 用 `∏(1+r)`；S19 年化 365 天；S20–S23 前 `k−1` 点为 `null`；S28 末 k 点 OLS，`\|t\|<2` 记 `flat` | series | `S01 min_n=1`、`S13/S14 min_n=2` | `descriptive.py::s01_count` … `s28_direction` |
| D 组分布形态（v1.6） | 偏度/峰度用**总体矩**（不扣自由度）；MAD 未乘 1.4826；D17/D18 返回正数形式损失（`q=5`）；D20/D21 输入**价格**且与 `drawdown_profile` 同口径；D13 JB 用 χ²(2) 上尾 | series | `D17/D18 min_n=30` | `descriptive.py::d01_skew` … `d24_win_rate` |
| T 组时序结构（v1.6） | ACF 分母用 `n`（非 `n−k`）；`CCF(k)=corr(x_t,y_{t+k})`，**k>0 表示 x 领先 y**；T07 χ²(m) 上尾；T15 输入收益、年化 √365；T19 λ=0.94；T22 标准化累计偏差阈值 `5`；T27 盒计数 `logN~log k`；T28 `m=2, r=0.2σ` | series/pairs | `T13 min_n=64`；`T14/T20/T21/T24 min_n=30` | `timeseries.py::t01_acf` … `t28_sample_entropy` |
| F 组补充（v1.6） | F07/F08 年化因子 365（输入价格）；F18 复用 `run_length_stats`（输入收益）；F20 `r−E[r]`；F21 末 `window` 期 AR 之和 | series | `min_n=30`（F09/F10=2） | `timeseries.py::f07_sortino` … `f21_car` |
| H 组检验（v1.6） | H02 合并方差 t；H03 Welch-Satterthwaite；H04/H05 正态近似 + 并列秩修正；H06 列联表 χ²；H07 单因素 ANOVA；H08 Kruskal-Wallis + 并列修正；H13 Bonferroni；H14 BH-FDR；H15/H16 固定 `seed=42` | pairs/series | `min_n=10` | `inference.py::h02_two_sample_t` … `h18_power` |
| B 组状态（v1.6） | B06 联合计数；B07 行随机矩阵；B08 幂迭代（tol 1e-12）；B09 `1/(1−p_ii)`；B10 条件分位 `p10/25/50/75/90` | labels / state+target | `B10 min_n=250` | `inference.py::b06_crosstab` … `b18_frequency` |
| M17/M23（v1.6） | M17 `β=cov(x,y)/var(x)`、`α=ȳ−βx̄`、`r2=ρ²`；M23 零收益对不计入 | pairs | `M17 min_n=30` | `inference.py::m17_beta` / `m23_co_movement` |
| R08–R17（v1.6） | R08 复用 B11 只补句式；R09/R10/R11/R16/R17 输出固定 `phrase`（含样本量），禁止点预测措辞 | 见各方法 | 同上游方法 | `inference.py::r08_monotonic_phrase` … `r17_level_compare` |
| C 组日历效应（v1.7） | 一律按**自然月/星期/月内日/季度**分组（非交易日节奏）；月收益按 `∏(1+r)−1` 聚合；C13 用「月度组间方差/总方差」（ANOVA 式，**非 STL 季节项**），总方差=0 → `null`；C14 一致性=`max(涨年数,跌年数)/年数`；C15 只统计相邻月转移；C16 锚定**最新日期**的 (月,日)；C17 同月同进度（day-of-month）；C18 两资产按自然月同向率 | returns + dates | `C05 min_n=30`、`C06 min_n=24`、其余 `min_n=60`；`dates` 缺失直接 `ValueError` | `seasonal.py::c01_month_effect` … `c18_cycle_alignment` |
| C11 节假日前效应 | **不可用**：缺交易日历/节假日表（`mm_events` 仅 16 行），按纪律登记占位、调用抛 `MethodUnavailable` | events | — | `seasonal.py`（`register_unavailable`） |
| 能力层信封（v1.7） | `ok/capability/intent/answer/data/quality/trace_id` 固定；`quality` **只在顶层**；`status!=good` 必须带 `degraded_reason` 且 `answer` 含「样本/不足/降级」；`answer` 禁止空串；能力只能绑 `implemented=true` 方法且 `capability.min_n ≥ method.min_n` | — | `contracts/capability_result.schema.json` 为 SSoT | `l1agg/capabilities/envelope.py` / `manifest.py` / `stats.py` |
| 季节性强结论门 | 月/星期效应需 ≥60 个月；不足时 `status=partial` + `degraded_reason=seasonality_depth_lt_5y`，结论只作描述 | — | `months_for_conclusion=60` | `capabilities/stats.py::seasonality` |
| 日线收盘锚点（v1.7） | `market.candles` 1d 的 `ts` 一律归一到 **UTC 日首**，真实观测/收盘时刻存 `close_ts`；`meta.close_anchor` ∈ `bar_close`（`*_1d` 真实日线，收盘锚点=UTC 日末）/ `snapshot_last`（日频快照，=当日最后观测）。**跨资产横截面统计必须两侧同锚点**（`source_policy=snapshot` 优先、缺失才退回 `auto` 并标注），混用会让同期相关被系统性低估（实测 BTC–ETH：混用 ρ≈0.33、同锚点 ρ≈0.83） | candles | `source_policy ∈ {auto,snapshot,bars}` | `34-前端应用训练系统/core/l0_foundation.py::_fetch_market_candles`、`l1agg/candles.py::load` |

### §16.1 R02 PIT 双口径与条件分布门禁（v1.9 契约增补）

| 口径 | 状态 | 分位与桶边界 | 允许用途 |
|---|---|---|---|
| `pit=false` | ✅ 已实现（仅样本内回顾） | 末点与所有历史样本共用全样本分位和桶边界，含未来函数 | 仅限明确标注的样本内回顾；不得进入 T0.5/T2/MERS，不得作为显著性或推荐证据 |
| `pit=true` | ✅ 已实现（`conditional.py::r02_percentile_forward`） | 每个历史时点 t 只在固定回看 `window` 内使用截至 t 可见的数据计算分位、桶边界和状态；宏观数据还须 `release_ts≤t`。当前状态同理截至 `as_of`，再聚合与当前同桶的历史 h 期前瞻收益 | T0.5/T2/MERS 的唯一合法口径；已经 D-E02 能力出口交付（v1.12，含 4→2 桶降级披露） |

**目标输出契约**：每个 h 返回 `pit/as_of/window/align_method/effective_n/nonoverlap_n`；`effective_n` 是具有有效前瞻收益的样本数，`nonoverlap_n` 是按 h 去重重叠后的样本数。T0.5 首版固定 `h=1, buckets=4`，每桶按 `nonoverlap_n≥250` 验收，不足按场景包降为 2 桶并披露，不得用重叠样本凑数；h≥5 与多维 T2 等 T-1 扩样本。

**推断边界**：h>1 的重叠前瞻收益及趋势斜率显著性推断前，Newey-West/HAC 是硬前置；未实现前只能给描述统计，不能给显著性结论。批量扫描按「关系对 × lag × window × h」完整搜索族做 BH-FDR/Bonferroni 并披露 `p_adj`。整体进度与实施顺序由 [TECHNICAL_DESIGN §6](./TECHNICAL_DESIGN.md) 汇总，本节只定义方法口径。
