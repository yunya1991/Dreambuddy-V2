# 54 调研 — 科研机构的数学 / 统计学确定性方法（跨领域）

- **版本**: v1.0 ｜ **日期**: 2026-11-14 ｜ **状态**: 🟢 调研结论
- **目的**: 把科研机构（计量、物理、气候、医学、生态、复杂系统）中**可确定复现**的统计方法纳入 L1，使能力不局限于金融，可用于任意「数据化科研」场景。
- **准入**: 公式封闭 + 参数固定惯例 + 可复现（固定 seed / 固定分箱 / 固定容差）。剔除 MCMC、t-SNE/UMAP、隔离森林等随机或黑箱方法（确需使用时固定 seed 并标注 D3-seeded）。
- **配套**: [METHOD_LIBRARY.md](./METHOD_LIBRARY.md)、[RESEARCH-INSTITUTIONAL-L1-METHODS.md](./RESEARCH-INSTITUTIONAL-L1-METHODS.md)、[TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md)

---

## §1 科研机构方法论地图

| 机构 / 体系 | 代表方法 | 可提取的确定性部分 |
|---|---|---|
| **NIST / SEMATECH**（e-Handbook） | 探索性数据分析、测量不确定度（GUM）、统计过程控制、可靠性 | 不确定度传播、控制图（X̄-R / EWMA / CUSUM）、过程能力 Cp/Cpk、拟合优度 |
| **CERN / ROOT** | 直方图统计、χ²/似然拟合、显著性 Z、Bootstrap、系统误差 | 分箱计数、χ² 拟合、Z 值、Bootstrap 区间、误差合成 |
| **US Census（X-13ARIMA-SEATS）** | 季节调整、交易日/假日效应、异常点识别 | STL/X-13 风格分解、AO/LS/TC 异常点、季节强度、修订分析 |
| **NOAA / NASA** | 气候与遥感序列分析 | FFT/Welch 功率谱、小波、Mann-Kendall 趋势、Sen 斜率、EOF/PCA |
| **OECD / Eurostat** | 指数与季节调整、nowcast | 指数分解、同比/环比链式、修订分析、季节调整 |
| **NIH / FDA** | 临床试验统计 | ANOVA/ANCOVA、等效性检验（TOST）、生存分析（KM/log-rank/Cox）、FDR |
| **IPCC** | 集合与不确定性表达 | 集合分位、区间统计、趋势一致性计数（不做归因） |
| **Santa Fe Institute** | 复杂系统 | 幂律/尾指数、DFA/Hurst、网络中心性、多尺度熵 |
| **Max Planck / 统计研究所** | 非参数与稳健统计 | 核密度、稳健回归、极值理论、置换检验 |
| **JHU / WHO** | 流行病学 | KM、log-rank、meta 分析、SIR 描述性拟合 |
| **天文 / 基因组** | 周期与多重检验 | Lomb-Scargle 周期图、BH-FDR、GSEA 式分层富集 |
| **气候 / 生态** | 趋势与空间 | Mann-Kendall、Pettitt 变点、Moran's I、半变异函数 |

> 结论：科研方法比金融方法更强调三件事——**不确定度、可复现、多重比较**。这三点正好补齐 L1 目前最弱的环节。

---

## §2 方法族（SC 系列，共 92 条）

### 2.1 推断与不确定度（SC01–SC12）

| ID | 方法 | 规则 | 输出 | 依赖 |
|---|---|---|---|---|
| SC01 | 统计功效 | 1−β（给定 α、n、效应量） | power | statsmodels |
| SC02 | 最小样本量 | n*（固定 α=0.05, power=0.8） | n_star | statsmodels |
| SC03 | 等效性检验 TOST | 双单侧 t | p, 等效区间 | scipy |
| SC04 | 置换检验 | 打乱标签 N=1000, seed=42 | p_perm | numpy |
| SC05 | Bootstrap 百分位区间 | B=1000, seed=42 | ci_low, ci_high | numpy |
| SC06 | Bootstrap BCa 区间 | 偏差校正加速 | ci_bca | 自实现 |
| SC07 | Jackknife 标准误 | 留一估计 | se_jack | numpy |
| SC08 | Delta 法误差传播 | Var(f) ≈ ∇fᵀΣ∇f | se | numpy |
| SC09 | GUM 不确定度合成 | √Σ(c_i·u_i)² | u_c, U(k=2) | 自实现 |
| SC10 | 预测区间 | ŷ ± t·s√(1+1/n) | pi_low, pi_high | statsmodels |
| SC11 | 容忍区间 | 覆盖比例 γ 的区间 | ti_low, ti_high | 自实现 |
| SC12 | 分割共形区间 | 校准集分位 | ci_conformal | numpy |

### 2.2 回归与模型诊断（SC13–SC24）

| ID | 方法 | 规则 | 输出 | 依赖 |
|---|---|---|---|---|
| SC13 | OLS | 最小二乘 | betas, se, r2 | statsmodels |
| SC14 | WLS | 加权最小二乘 | betas, r2 | statsmodels |
| SC15 | Logistic 回归 | MLE | coef, odds_ratio | statsmodels |
| SC16 | Poisson 回归 | MLE | coef, irr | statsmodels |
| SC17 | 分位数回归 | τ=0.1/0.5/0.9 | betas | statsmodels |
| SC18 | Huber 稳健回归 | 固定 ε=1.35 | betas | statsmodels |
| SC19 | Ridge（固定 α） | α=1.0 标准化后 | betas | sklearn |
| SC20 | 多重共线性 VIF | 1/(1−R²_j) | vif[] | statsmodels |
| SC21 | 异方差 Breusch-Pagan | LM 检验 | lm, p | statsmodels |
| SC22 | 异方差 White 检验 | 辅助回归 | lm, p | statsmodels |
| SC23 | 残差自相关 Durbin-Watson | DW≈2 为无自相关 | dw | statsmodels |
| SC24 | 影响点 Cook's D / 杠杆 | D_i, h_ii | flags | statsmodels |

### 2.3 实验设计（SC25–SC30）

| ID | 方法 | 规则 | 输出 | 依赖 |
|---|---|---|---|---|
| SC25 | 单因素 ANOVA | F 检验 | f, p, eta² | scipy |
| SC26 | 双因素 ANOVA | 主效应+交互 | f[], p[] | statsmodels |
| SC27 | ANCOVA | 协变量调整 | f, p | statsmodels |
| SC28 | 重复测量 ANOVA | 组内/组间 | f, p | statsmodels |
| SC29 | 析因设计主效应 | 2^k 对比 | effects[] | numpy |
| SC30 | 事后多重比较 | Tukey HSD / Dunnett | p_adj[] | statsmodels |

### 2.4 降维与结构（SC31–SC38）

| ID | 方法 | 规则 | 输出 | 依赖 |
|---|---|---|---|---|
| SC31 | PCA | 特征分解 | ratio[], loadings | sklearn |
| SC32 | SVD | 奇异值分解 | s[], u, v | numpy |
| SC33 | 因子分析 | 固定 k 因子 | loadings, uniqueness | sklearn |
| SC34 | ICA | seed=42 | sources | sklearn |
| SC35 | 图 Lasso（固定 α） | 偏相关图 | precision, edges | sklearn |
| SC36 | 层次聚类 | 相关距离 + average | dendrogram | scipy |
| SC37 | K-Means（seed=42, k 固定） | 惯性最小 | labels, inertia | sklearn |
| SC38 | 轮廓系数 | 簇内/簇间距离 | silhouette | sklearn |

### 2.5 信号与频谱（SC39–SC48）

| ID | 方法 | 规则 | 输出 | 依赖 |
|---|---|---|---|---|
| SC39 | FFT 频谱 | 幅值谱 | freq[], amp[] | numpy |
| SC40 | Welch 功率谱 | 段长 256, 重叠 50% | psd[] | scipy |
| SC41 | Lomb-Scargle 周期图 | 非均匀采样 | power[], period | scipy |
| SC42 | 离散小波 DWT | db4, 层数 4 | coeffs[] | pywt（可选） |
| SC43 | 小波相干 | 两序列时频相干 | coherence | 自实现/pywt |
| SC44 | Savitzky-Golay 平滑 | 窗口 11, 阶 3 | smoothed | scipy |
| SC45 | Butterworth 滤波 | 4 阶, 截止固定 | filtered | scipy |
| SC46 | Hilbert 包络/瞬时相位 | 解析信号 | envelope, phase | scipy |
| SC47 | Kalman 滤波（固定 Q/R） | 线性状态空间 | state[], gain | 自实现 |
| SC48 | 互谱相干 | 两序列频域相干 | coherence[] | scipy |

### 2.6 变点与趋势（SC49–SC54）

| ID | 方法 | 规则 | 输出 | 依赖 |
|---|---|---|---|---|
| SC49 | CUSUM 变点 | 累计和越界 | points | 自实现 |
| SC50 | PELT 变点 | 固定惩罚 BIC | points | ruptures（可选）/自实现 |
| SC51 | Pettitt 检验 | 非参数单变点 | p, point | 自实现 |
| SC52 | Mann-Kendall 趋势 | S 统计量 + 正态近似 | tau, p, trend | pymannkendall/自实现 |
| SC53 | Sen 斜率 | 中位斜率 | slope, ci | 自实现 |
| SC54 | 季节 Mann-Kendall | 逐月 S 汇总 | trend, p | 自实现 |

### 2.7 信息论与复杂度（SC55–SC62）

| ID | 方法 | 规则 | 输出 | 依赖 |
|---|---|---|---|---|
| SC55 | 香农熵 | −Σp log p | h | numpy |
| SC56 | 互信息 | I(X;Y) | mi | sklearn |
| SC57 | 传递熵 | 条件互信息（hist 分箱固定） | te | 自实现 |
| SC58 | KL 散度 | D(P‖Q) | kl | scipy |
| SC59 | Lempel-Ziv 复杂度 | 归一化 LZ76 | c | 自实现 |
| SC60 | 样本熵 | m=2, r=0.2σ | sampen | 自实现 |
| SC61 | 排列熵 | m=3, τ=1 | pe | 自实现 |
| SC62 | DFA / Hurst | 去趋势波动分析 | alpha, H | 自实现 |

### 2.8 极值理论（SC63–SC66）

| ID | 方法 | 规则 | 输出 | 依赖 |
|---|---|---|---|---|
| SC63 | 块最大值 GEV 拟合 | MLE | μ, σ, ξ | scipy |
| SC64 | POT / GPD 拟合 | 阈值 P95 | ξ, β | scipy |
| SC65 | 重现水平 | T 年重现值 | level_T | 自实现 |
| SC66 | Hill 尾指数 | 顶部 k 个值 | alpha | 自实现 |

### 2.9 空间与网络（SC67–SC72）

| ID | 方法 | 规则 | 输出 | 依赖 |
|---|---|---|---|---|
| SC67 | Moran's I | 空间自相关 | I, p | libpysal/自实现 |
| SC68 | Geary's C | 局部差异 | C, p | 自实现 |
| SC69 | 半变异函数 | 滞后距离分箱 | gamma(h) | 自实现 |
| SC70 | 普通 Kriging | 变异函数拟合后插值 | pred, var | 自实现 |
| SC71 | 网络中心性 | degree/betweenness/closeness | scores | networkx |
| SC72 | 社区发现 | Louvain（seed=42） | communities, modularity | networkx |

### 2.10 生存与可靠性（SC73–SC78）

| ID | 方法 | 规则 | 输出 | 依赖 |
|---|---|---|---|---|
| SC73 | Kaplan-Meier | 乘积极限 | curve, median | lifelines/自实现 |
| SC74 | Log-rank 检验 | 卡方 | chi2, p | lifelines/自实现 |
| SC75 | Cox 比例风险 | MLE | hr, ci | lifelines |
| SC76 | Weibull 拟合 | MLE | shape, scale | scipy |
| SC77 | MTBF / 失效率 | 总时长/失效数 | mtbf | stdlib |
| SC78 | 控制图 | X̄-R / EWMA / CUSUM | ucl, lcl, alarms | 自实现 |

### 2.11 证据综合（SC79–SC83）

| ID | 方法 | 规则 | 输出 | 依赖 |
|---|---|---|---|---|
| SC79 | 固定效应 meta | 逆方差加权 | pooled, ci | 自实现 |
| SC80 | 随机效应 meta | DerSimonian-Laird | pooled, tau² | 自实现 |
| SC81 | 异质性 I² / Q | 比例与卡方 | i2, q, p | 自实现 |
| SC82 | 漏斗图不对称 | Egger 回归 | intercept, p | statsmodels |
| SC83 | Trim-and-fill | 剪补法 | adj_pooled | 自实现 |

### 2.12 数据质量（SC84–SC90）

| ID | 方法 | 规则 | 输出 | 依赖 |
|---|---|---|---|---|
| SC84 | 缺失机制检验 | Little's MCAR | chi2, p | 自实现 |
| SC85 | KNN 插补 | k=5，距离加权 | filled | sklearn |
| SC86 | 马氏距离离群 | D² > χ²(0.975, df) | flags | scipy |
| SC87 | 缺失模式矩阵 | 共现缺失计数 | pattern | pandas |
| SC88 | 重复记录检测 | 键 + 相似度阈值 | dups | 自实现 |
| SC89 | 一致性规则校验 | 范围/单调/跨字段 | violations | 自实现 |
| SC90 | PIT 时间校验 | 可用时间 ≤ 使用时间 | pass | 自实现 |

### 2.13 季节调整（SC91–SC92）

| ID | 方法 | 规则 | 输出 | 依赖 |
|---|---|---|---|---|
| SC91 | X-13 风格分解 | 趋势/季节/不规则 | components | statsmodels(STL 近似) |
| SC92 | 异常点识别 | AO/LS/TC（3σ 规则） | outliers[] | 自实现 |

---

## §3 科研协议（可复现五原则）

1. **数据版本化**：每次统计记录 `dataset_hash + 时间范围 + 样本数`。
2. **参数登记**：所有窗口/分箱/阈值写进结果（禁止隐式默认）。
3. **随机固定**：Bootstrap/置换/聚类统一 `seed=42`，并在输出标注 `seeded=true`。
4. **多重比较**：≥10 次比较必须 BH-FDR；≥100 次必须报告校正前后 p。
5. **不确定度必报**：D2/D3 结果附 `n`、`CI` 或 `±u`；不报不确定度的结论视为不合格。

---

## §4 新增能力登记（J 组：科研统计，30 项）

| ID | 能力 | 方法 | 分级 | 优先级 | 场景 |
|---|---|---|---|---|---|
| D-J01 | 趋势检验（Mann-Kendall + Sen） | SC52–SC53 | D2 | P2 | 任意长序列单调性 |
| D-J02 | 季节强度与调整 | SC91 + C13 | D2 | P2 | 月度/周度指标 |
| D-J03 | 异常点识别（AO/LS/TC） | SC92 | D1 | P2 | 数据清洗 |
| D-J04 | 变点检测（CUSUM/PELT/Pettitt） | SC49–SC51 | D2 | P2 | 结构变化 |
| D-J05 | 周期/频谱（FFT/Welch/Lomb） | SC39–SC41 | D2 | P2 | 周期性识别 |
| D-J06 | 小波/滤波平滑 | SC42–SC45 | D1 | P3 | 去噪与多尺度 |
| D-J07 | 包络与瞬时相位 | SC46 | D1 | P3 | 振荡信号 |
| D-J08 | Kalman 状态估计 | SC47 | D3 | P3 | 含噪状态 |
| D-J09 | 互谱相干 | SC48 | D2 | P3 | 两序列频域关系 |
| D-J10 | 香农熵/互信息/KL | SC55–SC58 | D2 | P2 | 信息量比较 |
| D-J11 | 传递熵 | SC57 | D2 | P3 | 方向性信息流 |
| D-J12 | 复杂度（LZ/样本熵/排列熵） | SC59–SC61 | D2 | P2 | 序列复杂度 |
| D-J13 | DFA/Hurst | SC62 | D2 | P2 | 长期记忆 |
| D-J14 | 极值拟合与重现水平 | SC63–SC65 | D3 | P3 | 尾部风险 |
| D-J15 | 不确定度合成（GUM） | SC09 | D1 | P2 | 测量/指标误差 |
| D-J16 | 预测/容忍/共形区间 | SC10–SC12 | D2 | P2 | 区间表达 |
| D-J17 | 功效与样本量 | SC01–SC02 | D2 | P3 | 实验设计 |
| D-J18 | 等效性检验 TOST | SC03 | D2 | P3 | 差异判定 |
| D-J19 | ANOVA / ANCOVA / 事后比较 | SC25–SC30 | D2 | P2 | 分组差异 |
| D-J20 | 回归诊断（VIF/BP/White/DW/Cook） | SC20–SC24 | D2 | P2 | 模型可信度 |
| D-J21 | 稳健回归（Huber）/分位回归 | SC17–SC18 | D3 | P3 | 抗离群 |
| D-J22 | PCA/SVD/因子分析 | SC31–SC33 | D3 | P2 | 结构降维 |
| D-J23 | 聚类与轮廓系数 | SC36–SC38 | D3 | P3 | 分组结构 |
| D-J24 | 相关网络与社区 | SC35, SC71–SC72 | D3 | P3 | 关系结构 |
| D-J25 | 空间自相关/变异函数 | SC67–SC69 | D2 | P3 | 空间数据 |
| D-J26 | 生存分析（KM/log-rank/Cox） | SC73–SC75 | D3 | P3 | 持续期/失效 |
| D-J27 | 可靠性/控制图 | SC76–SC78 | D1 | P3 | 过程监控 |
| D-J28 | Meta 分析与异质性 | SC79–SC83 | D3 | P3 | 多研究合并 |
| D-J29 | 缺失机制与插补 | SC84–SC87 | D3 | P2 | 数据质量 |
| D-J30 | 质量校验（重复/一致性/PIT） | SC88–SC90 | D1 | P1 | 所有能力前置 |

---

## §5 非金融场景映射（为什么值得进 L1）

| 场景 | 用到的族 | 输出示例 |
|---|---|---|
| 运营指标分析 | SC52/SC91/SC92 | 「近 24 个月 GMV 趋势：Sen 斜率 +3.2%/月，2 个异常月」 |
| 实验/AB 测试 | SC01–SC03, SC25 | 「两组差异 1.8%，p=0.03，功效 0.72，需 n≥1,240」 |
| 传感器/设备监测 | SC47/SC78/SC62 | 「振动序列 Hurst=0.68（长记忆），控制图 3 次越界」 |
| 气候/环境序列 | SC52/SC54/SC39 | 「气温序列 Mann-Kendall τ=0.21，p<0.01，主周期 12 月」 |
| 医学/随访数据 | SC73–SC75 | 「中位生存 18 个月，log-rank p=0.04」 |
| 多研究汇总 | SC79–SC83 | 「合并效应 0.34（95%CI 0.12–0.56），I²=42%」 |
| 数据治理 | SC84–SC90 | 「缺失 3.1%，MCAR 检验 p=0.21，可随机插补」 |

---

## §6 禁区与降级

| 方法 | 处理 |
|---|---|
| MCMC / 贝叶斯采样 | 禁止（非确定性）；仅允许共轭闭式更新 |
| t-SNE / UMAP | 降级为 D3-seeded，且不作为结论依据 |
| 隔离森林 / 随机森林重要性 | 降级 D3-seeded，或多用 PCA/相关替代 |
| 神经网络 / 深度学习 | 禁止进 L1（L2 职责） |
| 因果推断（DoWhy/PC 算法） | 禁止表述因果；Granger/传递熵仅作「时序领先性」 |
| 无 seed 的随机过程 | 禁止；统一 seed=42 |

---

## §7 方法库影响

| 项 | 数量 |
|---|---|
| 原方法库 | 238 |
| 机构扩展（X/O/P/Q） | +42 |
| 科研扩展（SC01–SC92） | +92 |
| **合计（去重后）** | **约 370** |
| 关系原语 | 18（不变，科研结果复用 R01/R03/R09/R17） |
| 能力登记 | A16 + B10 + C6 + E12 + G25 + **J30** = 99 项 |

---

## §8 参考

- NIST/SEMATECH, *e-Handbook of Statistical Methods*（https://www.itl.nist.gov/div898/handbook/）
- U.S. Census Bureau, *X-13ARIMA-SEATS Reference Manual*（https://www.census.gov/data/software/x13as.html）
- CERN, *ROOT Data Analysis Framework*（https://root.cern/）
- JCGM 100:2008, *GUM: Guide to the Expression of Uncertainty in Measurement*
- Mann (1945) / Kendall (1975)：趋势检验；Sen (1968)：斜率估计
- Peng et al. (1994), *Mosaic organization of DNA nucleotides*（DFA）
- DerSimonian & Laird (1986)：随机效应 meta 分析
- Little (1988)：MCAR 检验
- Efron & Tibshirani (1993)：Bootstrap；Davison & Hinkley (1997)：BCa
