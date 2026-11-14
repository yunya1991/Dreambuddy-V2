# 54 调研 — 大型金融机构的 L1 确定性方法（数据 + 统计 + 分析 + 研究）

- **版本**: v1.0 ｜ **日期**: 2026-11-14 ｜ **状态**: 🟢 调研结论
- **目的**: 在**纯 L1（确定性、零推理）**范畴内，提取大型金融机构公开可复现的统计/分析/研究方法，扩展 [METHOD_LIBRARY.md](./METHOD_LIBRARY.md)（238 → 约 290 方法）。
- **铁律**: 只收「公式封闭 + 参数用行业惯例固定 + 输出可复现」。凡需样本内寻参、权重优化到最优、黑箱模型、因果推断、LLM 生成的，一律剔除。

---

## §0 准入与确定性分级

| 分级 | 判定标准 | 处理 |
|---|---|---|
| D1 | 算术/计数/排序，无分布假设 | 直接可用 |
| D2 | 统计量（相关/IC/t/分位），含抽样误差 | 必须带 `n` 与 `p` |
| D3 | 需要拟合或迭代（协方差收缩、风险平价权重、EWMA、PCA） | 参数固定为行业惯例 + 迭代容差固定 + 返回诊断量 |
| ❌ | 样本内优化、自由参数搜索、ML 预测、因果、LLM | 禁止进 L1 |

**「行业惯例固定参数」清单**（本层唯一允许的参数集）：20/60/120/252 日窗口、五分位/十分位、12-1 动量、EWMA λ=0.94（日）/0.97（月）、95%/99% VaR、1.96σ、t 临界 2.0、p=0.05、Bonferroni/BH 校正、Ledoit-Wolf 解析 λ、风险平价等风险贡献容差 1e-6。

---

## §1 机构方法论地图（只列公开、可公式化部分）

| 机构 | 公开方法 | 可提取的确定性部分 | 剔除部分 |
|---|---|---|---|
| **Bridgewater** | 债务周期、四象限（增长×通胀）、All Weather 风险平价、压力测试 | 四象限标签（数据分位切分）、风险贡献分解、等风险权重、情景冲击 | 周期阶段主观判断、"机器"叙事 |
| **BlackRock Aladdin** | 因子风险模型、协方差收缩、情景/压力测试、VaR | Ledoit-Wolf 收缩、EWMA 协方差、因子暴露回归、情景线性冲击、历史 VaR/CVaR | 组合优化求解、交易成本模型调参 |
| **MSCI Barra** | 结构化风险模型（SRM）、风格因子、特质风险、因子收益 | 横截面标准化、加权最小二乘因子收益、特质收益、因子协方差、风险分解 | 因子定义库的商业参数、优化器 |
| **AQR** | 价值/动量/Carry/防守四风格、时序动量、横截面动量、波动率缩放 | 12-1 动量、横截面 rank、carry（基差/费率）、低波排序、波动率目标换算 | 组合构建优化、容量估计 |
| **Man AHL** | 趋势跟踪、突破、多周期集成、波动率目标 | 多周期 MA 集成、唐奇安突破、ATR 归一、波动率目标换算 | 参数寻优、执行算法 |
| **WorldQuant / Two Sigma** | Alpha101 公式化因子、算子库 | `rank/ts_rank/ts_zscore/ts_corr/decay_linear/delta/delay/scale/signedpower/indneutralize` | 私有 alpha、组合优化、ML |
| **Bloomberg** | 经济日历、事件研究、相关矩阵、相对价值、季节性 | 事件窗 CAR、相关矩阵、季节性表、相对强弱 | BQL 私有字段、预测模型 |
| **JPMorgan RiskMetrics** | EWMA 协方差、VaR | λ 固定 EWMA、参数法/历史法 VaR | 内部风险模型调参 |
| **Goldman (GS Quant)** | 因子回归、情景分析、风险归因 | OLS 因子回归、Brinson 归因、情景冲击 | 结构化产品定价 |
| **LSEG / Refinitiv** | SUE、PEAD、分析师修正 | 标准化未预期盈利、分位分层、修正方向计数 | 一致预期模型 |
| **MSCI / FTSE Russell** | 指数季节性、回撤分析、因子拥挤度 | 月份/月末效应、水下曲线、拥挤度合成（估值价差+相关+换手） | 指数编制决策 |
| **Citadel / Point72 / Renaissance** | 未公开 | 不采用 | 全部 |

> 结论：机构方法中真正"确定性可复现"的，集中在 **横截面统计、时间序列算子、风险分解、归因、检验协议** 五块，恰好是 L1 能承载的。

---

## §2 方法扩展（统计层，新增 26 条）

### 2.1 横截面统计（Cross-Sectional）

| ID | 方法 | 公式/规则 | 输出 | 依赖 |
|---|---|---|---|---|
| X01 | 横截面 z-score | (x − mean_pool)/std_pool | z | pandas |
| X02 | 横截面百分位 rank | rank(pct=True) | pct | pandas |
| X03 | 中性化（去均值） | x − group_mean（按板块/规模分箱） | resid | pandas |
| X04 | 分位组合排序 | 五分位/十分位 | bucket | pandas |
| X05 | 多空价差 | Q5 均值 − Q1 均值 | spread, t | scipy |
| X06 | 横截面离散度 | std_pool(x) | dispersion | pandas |
| X07 | 市场宽度 | 上涨家数/总家数 | breadth | pandas |
| X08 | 同向率 | 同涨同跌对数/总对数 | ratio | pandas |
| X09 | 因子暴露回归 | 横截面 OLS：r_i = Σβ_k f_ik + ε_i | betas, resid | statsmodels |
| X10 | 特质收益 | ε_i（去因子后残差） | specific | numpy |
| X11 | 因子收益（WLS） | 加权最小二乘（√市值权重） | factor_ret | statsmodels |
| X12 | 横截面自相关 | corr(rank_t, rank_{t−1}) | rho | scipy |

### 2.2 时间序列算子（WorldQuant 风格，全部封闭公式）

| ID | 算子 | 定义 |
|---|---|---|
| O01 | delay(x, d) | x_{t−d} |
| O02 | delta(x, d) | x_t − x_{t−d} |
| O03 | ts_sum(x, d) | Σ_{i=0..d−1} x_{t−i} |
| O04 | ts_mean / ts_std | 滚动均值/标准差 |
| O05 | ts_min / ts_max | 滚动极值 |
| O06 | ts_argmax / ts_argmin | 极值位置（距今天数） |
| O07 | ts_rank(x, d) | 当前值在窗口内的百分位 |
| O08 | ts_zscore(x, d) | (x_t − ts_mean)/ts_std |
| O09 | ts_corr(x, y, d) | 滚动相关 |
| O10 | ts_cov(x, y, d) | 滚动协方差 |
| O11 | decay_linear(x, d) | 线性衰减加权均值（权重 d..1） |
| O12 | scale(x, a) | x · a / Σ|x|（固定 a） |
| O13 | signedpower(x, e) | sign(x)·|x|^e（e 惯例 2） |
| O14 | rank(x) | 横截面百分位 |
| O15 | indneutralize(x, g) | 组内去均值（行业/板块） |

> 以上 15 个算子构成「表达式层」，任意组合仍是确定性公式；L1 只需登记**固定组合**（如 12-1 动量、20 日 ts_rank），禁止自动搜索组合。

### 2.3 风险与组合描述（只描述，不给建议）

| ID | 方法 | 公式/规则 | 输出 | 分级 |
|---|---|---|---|---|
| P01 | 实现波动率 | std(logret, 20)·√365 | vol | D1 |
| P02 | 波动率目标换算 | target_vol / realized_vol | scale | D1 |
| P03 | 逆波动权重 | (1/σ_i)/Σ(1/σ_j) | weights | D1 |
| P04 | 等风险贡献权重 | 迭代至 RC_i 相等，容差 1e-6 | weights, RC | D3 |
| P05 | 风险贡献分解 | RC_i = w_i·(Σw)_i / (wᵀΣw) | RC[] | D1 |
| P06 | 协方差收缩（Ledoit-Wolf） | Σ̂ = δF + (1−δ)S（解析 δ） | cov | D3 |
| P07 | EWMA 波动/协方差 | λ=0.94 日、0.97 月 | ewma | D1 |
| P08 | PCA 风险分解 | 前 k 主成分解释比例 | ratio[], loadings | D3 |
| P09 | 组合 VaR（参数法） | 1.645·√(wᵀΣw)（95%） | var | D1 |
| P10 | 组合 CVaR（历史法） | −mean(r ≤ P5) | cvar | D1 |
| P11 | 水下曲线 | 1 − cum/cummax | series | D1 |
| P12 | Brinson 归因 | 配置 + 选择 + 交互（三分解） | effects | D1 |
| P13 | 尾部相关 | 仅下行样本的相关系数 | rho_down | D2 |
| P14 | 相关性稳定性 | 滚动相关 std / 均值 | stability | D2 |

### 2.4 研究与检验协议

| ID | 方法 | 规则 | 输出 |
|---|---|---|---|
| Q01 | IC / RankIC | corr(factor_t, fwd_ret_{t+1}) | ic |
| Q02 | ICIR | mean(IC)/std(IC) | icir |
| Q03 | IC 衰减表 | h ∈ {1,3,5,10,20} | ic_by_h |
| Q04 | 分位单调性检验 | 五分位收益 Spearman | rho, p |
| Q05 | Fama-MacBeth | 逐期横截面回归 → 系数序列均值/t | lambda, t |
| Q06 | Newey-West t | 滞后 L=⌊4(n/100)^{2/9}⌋ | t_nw |
| Q07 | Deflated Sharpe | 多重试验次数 N 校正 | dsr |
| Q08 | 子样本稳健性 | 前后半段/牛熊分段的 IC 差 | delta |
| Q09 | 参数扰动 | 固定网格 {10,20,60,120} 的结论方向一致性 | pass_ratio |
| Q10 | 事件窗 CAR | 估计窗 [−120,−20]，事件窗 [−5,+10] | car, n |
| Q11 | Patell/BMP 标准化检验 | 标准化异常收益的 Z | z, p |
| Q12 | Bootstrap 置信区间 | 固定 seed=42，B=1000 | ci |
| Q13 | 置换检验 | 固定 seed，N=1000 | p_perm |
| Q14 | 多重比较校正 | Bonferroni / BH-FDR | p_adj |
| Q15 | 样本充分性检查 | n ≥ 30（月度）/ 250（日度） | ok, reason |
| Q16 | PIT 校验 | 数据可用时间 ≤ 信号时间 | pass |

---

## §3 研究方法扩展（协议层，固定五步）

```
① 假设表述      "指标 X 处于状态 S 时，价格在 h 日的历史统计表现"
② 数据与对齐    日频/月频、时区统一、PIT 校验、缺失标记（禁止插补后当真实值）
③ 统计表达      分位/条件收益/事件窗/相关（本文件 §2 + METHOD_LIBRARY §11）
④ 稳健性        子样本 + 参数扰动 + 多重检验校正（Q06/Q08/Q09/Q14）
⑤ 结论措辞      只陈述历史统计与样本量，附 caveat；不做因果与预测
```

**关键协议细节**

- **事件研究**：正常收益用「均值调整」或「市场模型」（OLS，估计窗 120 日），事件窗不重叠；多事件需聚类稳健。
- **季节性**：月度效应必须用 Newey-West t（重叠样本自相关会高估显著性）；按月×按资产扫描必须 BH-FDR。
- **分层回测**：分位边界用**当期横截面**确定，禁止用全样本分位（未来函数）。
- **PIT**：宏观数据用发布日而非统计期（如 CPI 当月值在次月发布），否则统计失真。

---

## §4 新增能力登记（G 组：机构方法，23 项）

| ID | 能力 | 依赖 | 分级 | 优先级 | 数据前提 |
|---|---|---|---|---|---|
| D-G01 | 横截面 z-score / rank | X01–X02 | D1 | P2 | 多资产同日 |
| D-G02 | 组内中性化 | X03 | D1 | P2 | 板块/规模分组 |
| D-G03 | 分位组合与多空价差 | X04–X05 | D2 | P2 | 因子+前瞻收益 |
| D-G04 | 横截面离散度/宽度 | X06–X07 | D1 | P2 | 多资产 |
| D-G05 | 同向率矩阵 | X08 | D1 | P2 | 多资产 |
| D-G06 | 因子暴露/特质收益 | X09–X11 | D3 | P3 | 因子收益序列 |
| D-G07 | 序列算子族（15 个） | O01–O15 | D1 | P2 | 单序列 |
| D-G08 | 固定公式因子（12-1 动量、20 日 ts_rank 等） | O 族组合 | D1 | P2 | ≥252 日 |
| D-G09 | 波动率目标换算 | P01–P02 | D1 | P2 | 价格序列 |
| D-G10 | 逆波动权重 | P03 | D1 | P2 | 多资产 |
| D-G11 | 等风险贡献权重 | P04 | D3 | P3 | 多资产 + 协方差 |
| D-G12 | 风险贡献分解 | P05 | D1 | P3 | 权重 + 协方差 |
| D-G13 | 协方差收缩（LW） | P06 | D3 | P3 | ≥60 期 |
| D-G14 | EWMA 波动/协方差 | P07 | D1 | P2 | 序列 |
| D-G15 | PCA 风险分解 | P08 | D3 | P3 | 多资产 |
| D-G16 | 组合 VaR/CVaR | P09–P10 | D1 | P2 | 权重 + 协方差 |
| D-G17 | 水下曲线/回撤画像 | P11 + D20 | D1 | P1 | 价格 |
| D-G18 | Brinson 归因 | P12 | D1 | P3 | 组合+基准权重 |
| D-G19 | IC/ICIR/衰减表 | Q01–Q03 | D2 | P2 | 因子+前瞻收益 |
| D-G20 | 分位单调性检验 | Q04 | D2 | P2 | 同上 |
| D-G21 | Fama-MacBeth | Q05 | D3 | P3 | 横截面面板 |
| D-G22 | Deflated Sharpe / NW t | Q06–Q07 | D2 | P3 | 收益序列 + 试验次数 |
| D-G23 | 事件窗 CAR + Patell/BMP | Q10–Q11 | D2 | P2 | 事件表 + 价格 |
| D-G24 | 因子拥挤度 | P13–P14 + 估值价差 | D2 | P3 | 多资产 + 估值 |
| D-G25 | 尾部相关 | P13 | D2 | P2 | 多资产 |

> 与既有 A–E 组的关系：A/B/C 组是「数据维度能力」，E 组是「关系表达」，**G 组是机构统计方法的补强**；G 组不改变 L1 的定性——仍然只描述历史统计。

---

## §5 数据前提矩阵

| 能力簇 | 需要 | 现有 | 缺口 |
|---|---|---|---|
| 横截面（G01–G06） | 多资产同日收益、板块标签 | 有宏观/加密多序列，缺统一资产池 | 需定义「资产池」（BTC/ETH/SOL + 美股指数 + 黄金/原油） |
| 序列算子（G07–G08） | ≥252 日单序列 | `mm_metrics` 宏观满足，加密价格仅 2 周 | 需 OKX history-candles 回填 |
| 风险（G09–G16） | 多资产协方差 | 同上 | 同上 + 对齐 |
| 研究协议（G19–G25） | 因子面板 + 前瞻收益 | 部分 | 需因子表（可由 A 组派生） |
| PIT | 发布日字段 | 未见 | 需在 DAL 增加 `release_ts`（或在 54 侧映射表） |

---

## §6 禁止清单（机构方法在 L1 的红线）

| 禁止 | 原因 |
|---|---|
| 用历史数据优化权重（均值-方差最优、最大夏普） | 样本内拟合，非确定性表达 |
| 自由参数搜索（网格择优） | 引入选择偏差；只允许固定网格做**稳健性描述** |
| 组合优化器输出"应配多少" | 属决策，非统计表达 |
| 因果表述（"X 导致 Y"） | 机构同样只做关联陈述 |
| 未来函数（全样本分位、事后行业分类） | 会产生假规律 |
| 单一检验就下结论 | 必须多重比较校正 |
| ML/因子挖掘自动搜索 | 属 L2 |

---

## §7 落地优先级（相对既有 P0–P2）

| 阶段 | 内容 |
|---|---|
| **P1 追加** | D-G17 水下曲线/回撤画像（与 E10 合并）、D-G08 固定公式因子（12-1 动量、20 日 ts_rank）、D-G09 波动率目标换算、D-G14 EWMA 波动 |
| **P2** | D-G01–G05 横截面统计、D-G07 算子族、D-G16 VaR/CVaR、D-G19/G20 IC 与单调性、D-G23 事件窗、D-G25 尾部相关 |
| **P3** | D-G06 因子暴露、D-G11–G13 风险权重与收缩、D-G15 PCA、D-G18 Brinson、D-G21 FM 回归、D-G22 Deflated Sharpe、D-G24 拥挤度 |

**方法库影响**：新增 26 条（X 12 + O 15 算子按 1 族计 + P 14 + Q 16 ≈ 42 条明细），方法库总量约 280–290。

---

## §8 参考

- WorldQuant, *101 Formulaic Alphas*（2015）：算子族 rank / ts_rank / ts_corr / decay_linear / delta / delay / scale / signedpower / indneutralize
- MSCI Barra, *Structured Risk Model* 方法论：横截面 WLS 因子收益 + 特质风险 + 因子协方差
- Ledoit & Wolf (2004), *Honey, I Shrunk the Sample Covariance Matrix*
- J.P. Morgan, *RiskMetrics Technical Document*：EWMA λ=0.94/0.97
- Bailey & López de Prado (2014), *The Deflated Sharpe Ratio*
- Harvey, Liu & Zhu (2016), *… and the Cross-Section of Expected Returns*：t > 3 门槛
- Patell (1976) / Boehmer-Musumeci-Poulsen (1991)：事件研究标准化检验
- Brinson, Hood & Beebower (1986)：归因三分解
- Newey & West (1987)：重叠样本 t 调整
