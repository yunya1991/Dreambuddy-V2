# 54 技术设计 — L1 数据维度能力

- **版本**: v1.0 ｜ **日期**: 2026-11-14 ｜ **状态**: 🟢 首版登记
- **上游**: `SPEC-54-L1架构能力聚合层.md` v0.2（§11 能力全景）
- **下游**: `3.1-FRONTEND/scripts/l1_route_signal.py`（L1 路由）、`34-前端应用训练系统/core/l0_foundation.py`（L0 scope）、`/api/fundamental/**`
- **定位**: 本文是「L1 数据维度能力」的登记与实现口径唯一事实源。能力 = 确定性数据 + 确定性衍生（统计/相关/已具备模型输出），**不含** LLM 生成、合成数据、自建外推。

---

## §1 架构定位

```
L1 意图（TS/Python 双端注册表）
  → 54 能力路由（本文件 §2 的 capability_id）
      → L0 scope（datacenter.series / market.candles / 既有 10 个 scope）
          → 19 DAL（只读 query_*）/ 18 落库 / 已落盘快照
              → CapabilityResult（answer + data + quality）
```

三条边界（与 SPEC ADR 对齐）：

1. 只读：不写 `mm_*`、不回填、不重算快照。
2. 不重复：评分口径属 9/23，54 只消费；采集属 18，54 只读。
3. 可解释：每个能力必须能说明「数据来自哪里、样本多少、是否陈旧」。

---

## §2 数据维度能力登记（v1 首版 32 项）

状态口径：`✅ 已有实现` ｜ `🟡 部分可用` ｜ `⬜ 待实现`。优先级：P0/P1/P2（P0 = SPEC-54 当前迭代）。

### 2.1 A 组：库内时序衍生（16 项，零新增采集）

数据源统一为 `19-DAL mm_metrics`（子类 + 指标名 + 时间序列，实测 348,543 行 / 455 指标）。

| ID | 能力 | 数据依赖 | 确定性计算 | 输出字段 | L1 意图 | mode | 优先级 | 状态 |
|---|---|---|---|---|---|---|---|---|
| D-A01 | 历史序列 | 单序列 | 区间取点 + 降采样(日/周/月) | `points[], span, unit` | metric_series | deterministic | P0 | ⬜ |
| D-A02 | 变化率 | 单序列 | `(v_t/v_{t-n})-1` | `change, change_pct, window` | metric_series | deterministic | P0 | ⬜ |
| D-A03 | CAGR | 正指数型序列 | 首末值 + 年数 | `cagr, years` | metric_series | deterministic | P1 | ⬜ |
| D-A04 | 历史分位 | 单序列 | 经验分位（线性插值） | `percentile, lookback, sample_n` | metric_percentile | deterministic | P1 | 🟡（9 有估值分位可参考） |
| D-A05 | z-score | 单序列 | `(v-μ)/σ`（winsorize p1/p99） | `zscore, mean, std` | metric_percentile | deterministic | P1 | ⬜ |
| D-A06 | 年化波动率 | 单序列 | 日收益率标准差 × √365 | `volatility, window` | metric_series | deterministic | P1 | 🟡（多处有实现） |
| D-A07 | 回撤 | 单序列 | `v/max(prefix)-1` | `drawdown, peak_ts` | drawdown_query | deterministic | P1 | ⬜ |
| D-A08 | 同比 | 月频宏观序列 | 与 12 期前比较 | `yoy, base_ts` | metric_series | deterministic | P1 | 🟡（CPI 同比已有） |
| D-A09 | 环比 | 月频/日频 | 与上一期比较 | `mom, base_ts` | metric_series | deterministic | P1 | ⬜ |
| D-A10 | 实际利率 | `DGS10` + `CPIAUCSL` | 10Y 收益率 − CPI 同比 | `real_rate, nominal, inflation` | metric_derived | deterministic | P1 | ⬜ |
| D-A11 | 双序列滚动相关性 | 两条序列 | Pearson，30/90d 窗口 | `corr, window, sample_n` | correlation_query | deterministic | P2 | 🟡（23/11 有相关计算） |
| D-A12 | 领先滞后相关 | 两条序列 | lag 0–10 的相关系数序列 | `best_lag, corr_by_lag[]` | correlation_query | deterministic | P2 | ⬜ |
| D-A13 | 极端事件频率 | 单序列 | 超阈值天数 / 占比 | `days, ratio, threshold` | metric_series | deterministic | P2 | ⬜ |
| D-A14 | 拥挤度 | 资金费率 + 多空比 + 未平仓 | 三分位加权合成（规则固定） | `score, level, parts[]` | metric_percentile | deterministic | P2 | ⬜ |
| D-A15 | ETF 净流入滚动和 | ETF 净流入序列 | 7/30d 滚动求和 | `sum_7d, sum_30d` | metric_series | deterministic | P2 | ⬜ |
| D-A16 | 稳定币增速 | USDT/USDC 规模序列 | 7/30d 增速 | `growth_7d, growth_30d` | metric_series | deterministic | P2 | ⬜ |

### 2.2 B 组：技术指标（10 项，依赖 `market.candles`）

数据源：OKX `/api/v5/market/candles`（真实 K 线，1H/4H/1D，`limit ≤ 300`），5 秒进程内缓存；**禁止** `10-经典指标系统/generate_history.py` 的合成蜡烛。

| ID | 能力 | 数据依赖 | 确定性计算 | 输出字段 | L1 意图 | mode | 优先级 | 状态 |
|---|---|---|---|---|---|---|---|---|
| D-B00 | K 线获取 | OKX candles | 直取 + 缓存 + `is_stale` | `candles[], source, fetched_at` | technical_indicator | deterministic | P1 | 🟡（多处现取，无 scope） |
| D-B01 | MA / EMA | candles(close) | N 期均值/指数均值 | `ma20, ma60, ema12, ema26` | technical_indicator | deterministic | P1 | ✅ 实现存在 |
| D-B02 | RSI | candles(close) | Wilder 14 期 | `rsi14, zone(超买/超卖/中性)` | technical_indicator | deterministic | P1 | ✅ |
| D-B03 | MACD | candles(close) | EMA12−EMA26，DEA=EMA9(DIF) | `dif, dea, hist, cross` | technical_indicator | deterministic | P1 | ✅ |
| D-B04 | ATR | candles(HLC) | Wilder 14 期真实波幅 | `atr14, atr_pct` | technical_indicator | deterministic | P1 | ✅ |
| D-B05 | 布林带位置 | candles(close) | 20 期均值 ±2σ | `boll_pos, upper, lower` | technical_indicator | deterministic | P1 | 🟡 |
| D-B06 | 量能比 | candles(volume) | 当前量 / N 日均量 | `vol_ratio, base_vol` | technical_indicator | deterministic | P1 | 🟡 |
| D-B07 | 支撑/压力位 | candles(high/low) | 近 N 日极值 + 触碰次数 | `support, resistance, touches` | technical_indicator | deterministic | P2 | 🟡 |
| D-B08 | 趋势斜率 | candles(close) | 线性回归斜率（标准化） | `slope, r2, window` | technical_indicator | deterministic | P2 | 🟡 |
| D-B09 | 距 ATH 回撤 | candles(全历史/缓存) | `price/max-1` | `drawdown_from_ath, ath, ath_ts` | technical_indicator | deterministic | P2 | ⬜ |

### 2.3 C 组：已具备模型输出（6 项，零计算）

| ID | 能力 | 数据依赖（L0 scope） | 输出字段 | L1 意图 | mode | 优先级 | 状态 |
|---|---|---|---|---|---|---|---|
| D-C01 | bdsm 估值阶段/分位 | `yijing.bdsm` | `stage, score, percentile` | conditional_outlook | gated | P1 | ✅ |
| D-C02 | bcrm2 方向/置信度/卦象 | `yijing.bcrm2` | `direction, confidence, hexagram` | technical_indicator | gated | P1 | ✅ |
| D-C03 | 事件六维评分 | `event.state` | `scores[6], direction, confidence` | event_analysis | gated | P1 | ✅ |
| D-C04 | 持仓风控状态 | `riskcontrol.trailing` | `state, triggers, trailing_stop` | risk_control | gated | P1 | ✅ |
| D-C05 | 四维一致性 | `evolution.contradiction` | `dims[], verdict` | cross_check | gated | P2 | ✅ |
| D-C06 | 周期状态/战略承接 | `evolution.snapshot` + 43 | `cycle, phase, strategic` | conditional_outlook | gated | P2 | ✅ |

### 2.4 E 组：统计关系与价格表达（12 项，方法库驱动）

> 方法定义见 [METHOD_LIBRARY.md](./METHOD_LIBRARY.md)（238 方法 / 18 关系原语）。本组是「数据状态 → 价格表现」的固定统计出口，禁用因果与预测措辞。

| ID | 能力 | 依赖方法（方法库） | 数据前提 | L1 意图 | 优先级 | 状态 |
|---|---|---|---|---|---|---|
| D-E01 | 条件收益统计 | B02/B05 + F01 + H01 | 因子+价格 ≥250 点 | conditional_return | P2 | ⬜ |
| D-E02 | 分位→前瞻收益 | S25 + R02 | 序列 ≥250 点 | metric_percentile | P1 | ⬜ |
| D-E03 | 季节性/日历效应 | C01–C04, C15, H13 | 日收益 ≥3 年 | seasonality_query | P1 | ⬜ |
| D-E04 | 事件研究窗 | F19–F23, H01 | 事件表 + 价格 | event_study | P2 | ⬜ |
| D-E05 | 相关矩阵 TopK | M01–M07 | 多资产对齐 ≥60 点 | correlation_query | P2 | ⬜ |
| D-E06 | 领先滞后 | M11–M12 | 双序列 ≥60 点 | correlation_query | P2 | ⬜ |
| D-E07 | 状态转移 | B04, B07–B09 | 状态序列 ≥100 点 | state_transition | P2 | ⬜ |
| D-E08 | 分箱单调性/IC | B11–B15 | 因子+前瞻收益 | conditional_return | P2 | ⬜ |
| D-E09 | 计数与共现 | B17 + R09/R10 | 事件序列 | metric_series | P1 | ⬜ |
| D-E10 | 回撤画像 | D20–D21, F09–F10 | 价格 ≥250 点 | drawdown_query | P1 | ⬜ |
| D-E11 | 跨资产同向率/相关突变 | M23–M25, C18 | 多资产对齐 | cross_check | P2 | ⬜ |
| D-E12 | 时空对齐切片 | R18 | 多资产同日数据 | cross_check | P2 | ⬜ |

**硬前提**：E 组全部依赖「日频价格历史 ≥3 年」。当前库内价格仅约 2 周（`bitcoin.current_price_usd` 51 点），**必须先回填 OKX `history-candles` 或 CoinGecko chart**，否则一律返回 `insufficient_history`。

### 2.5 G 组：机构统计方法（25 项，调研见 RESEARCH-INSTITUTIONAL-L1-METHODS.md）

> 来源：Bridgewater / BlackRock Aladdin / MSCI Barra / AQR / Man AHL / WorldQuant / JPM RiskMetrics / LSEG 等公开方法论中**可公式化**的部分。只描述，不决策。

| ID | 能力 | 分级 | 优先级 | 状态 |
|---|---|---|---|---|
| D-G01 | 横截面 z-score / rank | D1 | P2 | ⬜ |
| D-G02 | 组内中性化（板块/规模） | D1 | P2 | ⬜ |
| D-G03 | 分位组合与多空价差 | D2 | P2 | ⬜ |
| D-G04 | 横截面离散度 / 市场宽度 | D1 | P2 | ⬜ |
| D-G05 | 同向率矩阵 | D1 | P2 | ⬜ |
| D-G06 | 因子暴露 / 特质收益（Barra 简化） | D3 | P3 | ⬜ |
| D-G07 | 序列算子族（15 个：delay/delta/ts_rank/decay_linear…） | D1 | P2 | ⬜ |
| D-G08 | 固定公式因子（12-1 动量、20 日 ts_rank） | D1 | P1 | ⬜ |
| D-G09 | 波动率目标换算 | D1 | P1 | ⬜ |
| D-G10 | 逆波动权重 | D1 | P2 | ⬜ |
| D-G11 | 等风险贡献权重 | D3 | P3 | ⬜ |
| D-G12 | 风险贡献分解 | D1 | P3 | ⬜ |
| D-G13 | 协方差收缩（Ledoit-Wolf） | D3 | P3 | ⬜ |
| D-G14 | EWMA 波动/协方差（λ=0.94/0.97） | D1 | P1 | ⬜ |
| D-G15 | PCA 风险分解 | D3 | P3 | ⬜ |
| D-G16 | 组合 VaR / CVaR | D1 | P2 | ⬜ |
| D-G17 | 水下曲线 / 回撤画像 | D1 | P1 | ⬜ |
| D-G18 | Brinson 归因 | D1 | P3 | ⬜ |
| D-G19 | IC / ICIR / 衰减表 | D2 | P2 | ⬜ |
| D-G20 | 分位单调性检验 | D2 | P2 | ⬜ |
| D-G21 | Fama-MacBeth 横截面回归 | D3 | P3 | ⬜ |
| D-G22 | Deflated Sharpe / Newey-West t | D2 | P3 | ⬜ |
| D-G23 | 事件窗 CAR + Patell/BMP | D2 | P2 | ⬜ |
| D-G24 | 因子拥挤度 | D2 | P3 | ⬜ |
| D-G25 | 尾部相关 | D2 | P2 | ⬜ |

**分层关系**：A/B/C = 数据维度能力；E = 关系表达；**G = 机构统计方法补强**。G 组不改变 L1 定性——仍只输出历史统计与样本量。

### 2.6 J 组：科研统计方法（30 项，调研见 RESEARCH-SCIENTIFIC-METHODS.md）

> 来源：NIST/SEMATECH、CERN/ROOT、US Census X-13、NOAA/NASA、NIH/FDA、OECD、Santa Fe、JHU/WHO 等公开方法。面向「数据化科研」通用场景，不限于金融。

| ID | 能力 | 分级 | 优先级 | 状态 |
|---|---|---|---|---|
| D-J01 | 趋势检验（Mann-Kendall + Sen） | D2 | P2 | ⬜ |
| D-J02 | 季节强度与调整（STL/X-13 风格） | D2 | P2 | ⬜ |
| D-J03 | 异常点识别（AO/LS/TC） | D1 | P2 | ⬜ |
| D-J04 | 变点检测（CUSUM/PELT/Pettitt） | D2 | P2 | ⬜ |
| D-J05 | 周期/频谱（FFT/Welch/Lomb-Scargle） | D2 | P2 | ⬜ |
| D-J06 | 小波/滤波平滑（DWT/SG/Butterworth） | D1 | P3 | ⬜ |
| D-J07 | Hilbert 包络/瞬时相位 | D1 | P3 | ⬜ |
| D-J08 | Kalman 状态估计 | D3 | P3 | ⬜ |
| D-J09 | 互谱相干 | D2 | P3 | ⬜ |
| D-J10 | 熵/互信息/KL 散度 | D2 | P2 | ⬜ |
| D-J11 | 传递熵 | D2 | P3 | ⬜ |
| D-J12 | 复杂度（LZ/样本熵/排列熵） | D2 | P2 | ⬜ |
| D-J13 | DFA / Hurst | D2 | P2 | ⬜ |
| D-J14 | 极值拟合与重现水平（GEV/GPD） | D3 | P3 | ⬜ |
| D-J15 | 不确定度合成（GUM） | D1 | P2 | ⬜ |
| D-J16 | 预测/容忍/共形区间 | D2 | P2 | ⬜ |
| D-J17 | 功效与样本量 | D2 | P3 | ⬜ |
| D-J18 | 等效性检验（TOST） | D2 | P3 | ⬜ |
| D-J19 | ANOVA/ANCOVA/事后比较 | D2 | P2 | ⬜ |
| D-J20 | 回归诊断（VIF/BP/White/DW/Cook） | D2 | P2 | ⬜ |
| D-J21 | 稳健回归/分位回归 | D3 | P3 | ⬜ |
| D-J22 | PCA/SVD/因子分析 | D3 | P2 | ⬜ |
| D-J23 | 聚类与轮廓系数 | D3 | P3 | ⬜ |
| D-J24 | 相关网络与社区发现 | D3 | P3 | ⬜ |
| D-J25 | 空间自相关/变异函数 | D2 | P3 | ⬜ |
| D-J26 | 生存分析（KM/log-rank/Cox） | D3 | P3 | ⬜ |
| D-J27 | 可靠性/控制图（X̄-R/EWMA/CUSUM） | D1 | P3 | ⬜ |
| D-J28 | Meta 分析与异质性 | D3 | P3 | ⬜ |
| D-J29 | 缺失机制与插补 | D3 | P2 | ⬜ |
| D-J30 | 质量校验（重复/一致性/PIT） | D1 | P1 | ⬜ |

**分层关系**：A/B/C = 数据维度；E = 关系表达；G = 机构方法；**J = 科研统计（通用化）**。J 组使 L1 可用于运营、实验、传感器、气候、医学等任意时序数据场景。

### 2.7 K 组：关系评估与发现（2 项，系统级）

> 实现见 SPEC §14（MERS）与 §15（Discovery）。二者是「选法」子系统，不直接产出统计结论。

| ID | 能力 | 数据来源 | 分级 | 优先级 | 状态 |
|---|---|---|---|---|---|
| D-K01 | 方法推荐（relationship_recommend） | `relationship_registry.db`（只读） | D1（读预计算） | P1 | ⬜ |
| D-K02 | 发现查询（discovery_query） | `reports/discovery/**`（只读） | D1（读预计算） | P2 | ⬜ |

**约束**：只读预计算产物 → 无实时随机性；注册表/报告缺失时回落方法库默认顺序（FAIL-OPEN）。

---

## §3 能力 → L0 scope 映射

| scope | 状态 | 支撑能力 | 数据源 |
|---|---|---|---|
| `datacenter.series` | ⬜ 新增 | D-A01/02/03/06/08/09/13/15/16 | 19 DAL `query_metric_by_time` |
| `datacenter.percentile` | ⬜ 新增 | D-A04/05/07/14 | 同上（服务端统计） |
| `datacenter.correlation` | ⬜ 新增 | D-A11/12 | 同上（双序列对齐） |
| `market.candles` | ⬜ 新增 | D-B00–B09 | OKX candles + 5s 缓存 |
| `datacenter.record` | ✅ 既有 | D-A 组当前值 | 18 落库最新记录 |
| `market.ticker` | ✅ 既有 | 实时价/24h 高低 | OKX ticker |
| `yijing.bdsm` / `yijing.bcrm2` | ✅ 既有 | D-C01/02 | 快照 JSON |
| `event.state` / `riskcontrol.trailing` | ✅ 既有 | D-C03/04 | 快照/日志 |
| `evolution.contradiction` / `evolution.snapshot` | ✅ 既有 | D-C05/06 | 演化产物 |

---

## §4 质量、降级与缓存

| 项 | 规定 |
|---|---|
| 返回信封 | `{answer, data, quality{status, sample_n, span, is_stale, degraded_reason}}`，`quality` 固定顶层 |
| 最小样本 | 统计类 `sample_n ≥ 30`；不足 → `status=partial` + `degraded_reason=insufficient_samples`，统计字段 `null` |
| 陈旧度 | `now - max(ts) > 2×固有周期` → `is_stale=true`（CPI 月频 > 45d；日频 > 3d） |
| 缓存 | A 组：进程内 60s TTL（按 scope+参数哈希）；B 组：candles 5s TTL |
| 超时 | 单能力 1.5s 软超时；总链路 ≤ 800ms P95（A 组）/ ≤ 2s（B 组含外呼） |
| 离群 | 只标记 `outlier_flags`，不删除；winsorize(p1/p99) 仅用于 z-score |
| 空结果 | `answer` 必须说明「暂无数据/样本不足」，禁止静默空串 |

---

## §5 非确定性排除项（禁止进入本层）

| 排除 | 原因 |
|---|---|
| `10-经典指标系统/generate_history.py` 合成 K 线 | 随机游走，非真实数据 |
| 自建趋势外推 / 情景概率生成 | 非确定性，L2 职责 |
| LLM 叙事、新闻解读、情绪推断 | 非确定性 |
| 任何写操作（回填、重算、覆盖快照） | 违反只读边界 |
| 跨模块评分加权融合（如六维合成总分） | 属 9/23 口径，54 只并列展示 |

---

## §6 与 SPEC 的关系与演进

- 本文 = 能力**登记册**（ID/依赖/字段/优先级/状态）。
- [METHOD_LIBRARY.md](./METHOD_LIBRARY.md) = 算法**选择表**（238 方法、18 关系原语、意图→方法路由、输出模板）。
- [SPEC-54](../SPEC-54-L1架构能力聚合层.md) = 架构与**契约**（scope 入参出参、门禁、验收、落地计划）。
- 新增能力流程：本文登记 → SPEC 补契约（如涉及新 scope）→ 实现 + 测试 → 更新状态列。
- 状态变更须同时回写本文与 SPEC §11；跨模块口径变化须先在 54 修订，禁止双写。
