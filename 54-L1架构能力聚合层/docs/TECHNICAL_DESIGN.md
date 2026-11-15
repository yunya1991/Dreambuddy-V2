# 54 总技术文档 — 数据 → 统计 → 关系能力地图

- **版本**: v2.48 ｜ **日期**: 2026-11-15 ｜ **状态**: 🟢 总技术文档（v2.48 登记 L1 交易层新增的 D-E15–D-E19 五个能力出口（趋势曲线 / 聚合曲线 / 分组看板 / 资金流向导图 / 四轴五态点亮投影），可执行出口 44 → **48 个**；v2.47 完成前端 D-A 组 14 个及 D-B08/D-B09/D-G08/D-G09 共 18 个 cue 分派，可执行出口保持 **44 个**；v2.46 接入 D-G09 波动率目标换算出口（P02），可执行出口 **44 个**；v2.45 接入 D-G08 12-1 动量出口（F14 窗口切片），可执行出口 **43 个**；v2.44 接入 D-B09 距 ATH 回撤出口（复用 D20/D21），可执行出口 **42 个**；v2.43 接入 D-B08 趋势斜率出口（T08/T09），可执行出口 **41 个**；v2.42 接入 D-A16 稳定币规模增速出口（S16 多窗口），可执行出口 **40 个**；v2.41 接入 D-A15 ETF 净流入滚动和出口（S20 滚动均值 × 窗口），可执行出口 **39 个**；v2.40 接入 D-A13 极端事件频率出口（S11 阈值 + 计数），可执行出口 **38 个**；v2.39 接入 D-A12 领先滞后相关出口（M11/M12），可执行出口 **37 个**；v2.38 接入 D-A11 双序列滚动相关出口（M04），可执行出口 **36 个**；v2.37 接入 D-A10 实际利率出口（S16 派生），可执行出口 **35 个**；v2.36 接入 D-A09 环比出口（S16），可执行出口 **34 个**；v2.35 接入 D-A08 同比出口（S16），可执行出口 **33 个**；v2.34 接入 D-A07 回撤出口（复用 D-E10 的 D20/D21 执行器），可执行出口 **32 个**；v2.33 接入 D-A06 年化波动率出口（F05），可执行出口 **31 个**；v2.32 接入 D-A04 历史分位出口（S25），可执行出口 **30 个**；v2.31 接入 D-A03 CAGR 出口（S19），可执行出口 **29 个**；v2.30 接入 D-A02 变化率出口（S15/S16），可执行出口 **28 个**；v2.29 接入 D-A01 历史序列出口（S25），可执行出口 **27 个**；v2.28 接入 D-J30 PIT/release_ts 全局出口（SC90/R02），可执行出口 **26 个**；v2.27 接入 D-G14 EWMA 波动/协方差出口（P07/T19），可执行出口 **25 个**；v2.26 接入 D-J24 相关网络与社区发现出口（M05/M21/SC71/SC72），可执行出口 **24 个**；v2.25 接入 D-J22 PCA/SVD/因子分析出口（M19/M20/SC31/SC32/SC33），可执行出口 **23 个**；v2.24 接入 D-G20 分位组合与单调性检验出口（B11/B16/Q04），可执行出口 **22 个**；v2.23 接入 D-G19 IC/ICIR/衰减表出口（B13/B14/B15/Q01/Q02/Q03），可执行出口 **21 个**；v2.22 接入 D-G16 组合 VaR/CVaR 出口（D17/D18/P09/P10），可执行出口 **20 个**；v2.21 接入 D-J02 季节强度与调整出口（C13/T10/SC91），可执行出口 **19 个**；v2.20 接入 D-J04 变点检测出口（T22/T23/SC49/SC50/SC51），可执行出口 **18 个**；v2.19 将 B06 二维交叉表纳入 D-E07，输出状态相邻期联合计数底表并与 B07 行归一化转移概率对齐，可执行出口保持 **17 个**；v2.18 接入 D-G23 事件窗均值调整 CAR + Patell/BMP（Q10/Q11），可执行出口 **17 个**；v2.17 接入 D-E14 一维相关状态→h=1/2 前瞻条件分布（R02 PIT 状态轴共享 B05/B10/R01/R08），可执行出口 **16 个**；v2.16 接入 D-E04 事件研究窗（F19/F21/F23）与 D-E09 计数与共现（R09/B17/R10）能力出口，可执行出口 **14 个**，事件数 <30 降级 partial 但保留 CAR/胜率；同步补齐前端 D-A14/D-G22 cue 分派与 D-E14 的 T-1 扩样本（云端 20 资产 / 54,653 行 `close_1d`，1 维 4 桶 @h=1 全部达标）；v2.15 冻结 D-A14/F26 的 `level` 阈值为 A 分位法（分值历史分布 p20/p60/p80 → 极低/低/偏高/高），接入 D-A14 能力出口；v2.14 接入 D-G22 显著性出口（Q06 HAC t + Q07 Deflated Sharpe），解除 h>1 重叠前瞻收益的推断阻塞；v2.13 打通宏观事件历史回填通道，为 D-E04/D-E09 解除「事件表仅 16 行」的数据阻塞；v2.12 接入 D-E12/R18 时空对齐切片；MERS S3 内部固定网格、BH-FDR、状态机与幂等注册表已交付，S5 对外推荐仍未开放；54-L1 测试 **909 通过 / 0 失败**（v2.27 全量回归；v2.16 同时修复既有日期边界测试的时间炸弹），audit **386/386 PASS**、验证覆盖率 **66.15%**；v2.11 接入 D-E11/C18 与 D-E01；v2.10 D-E05 双序列与多资产矩阵 TopK 全接线、D-E06 全 lag BH-FDR、manifest 真实执行覆盖与 audit 验证覆盖报告；v2.9 D-E02 能力出口接线与 T0.5/A8 首版交付；v2.8 方法层全部落地：`REGISTRY` 387 条全登记、`implemented=true` **386**，仅 C11 因缺交易日历不可用；v2.7 注册表放开调研族前缀并完成占位登记；v2.6 调研对齐与路线收口）
- **上游**: `SPEC-54-L1架构能力聚合层.md`（ADR/契约/路线）、`docs/METHOD_LIBRARY.md`（方法 SSoT）
- **下游**: `3.1-FRONTEND/scripts/l1_route_signal.py`（L1 路由）、`34-前端应用训练系统/core/l0_foundation.py`（L0 scope）、`/api/fundamental/**`
- **定位**: 本文是 54 的**总技术文档**——上半部（§0）回答「有哪些问题域、每个问题域用什么方法、现在缺什么」；下半部（§1–§6）是能力登记册（ID/依赖/字段/优先级/状态）。

---

## §0 全景：文档地图 / 六类问题 / 数据可行性 / 治理规则

### 0.1 文档地图（谁是 SSoT）

| 文档 | 角色 | 唯一负责的内容 | 当前版本 |
|---|---|---|---|
| [SPEC-54-L1架构能力聚合层.md](../SPEC-54-L1架构能力聚合层.md) | 架构与契约 | ADR、scope 出入参、门禁、路线（S1–S5）、MERS/Discovery | v1.44 |
| **本文 TECHNICAL_DESIGN.md** | **总技术文档 + 能力登记** | 六类问题地图、四层分工（§0.5）、能力 ID `D-*`、状态列、整体进度（§6.2） | **v2.48** |
| [METHOD_LIBRARY.md](./METHOD_LIBRARY.md) | 方法 SSoT | 方法 ID（S/D/T/C/I/M/B/F/H/R/X/O/P/Q/SC）、口径冻结（§16）、数据前提（§15） | v1.16 |
| [RESEARCH-TREND-PERSISTENCE-MODELS.md](./RESEARCH-TREND-PERSISTENCE-MODELS.md) | 调研 | 延续性三层拆解、Tier A/B/C、T 阶段 | v1.2 |
| [RESEARCH-INSTITUTIONAL-L1-METHODS.md](./RESEARCH-INSTITUTIONAL-L1-METHODS.md) | 调研补强 | 机构方法（X/O/P/Q） | — |
| [RESEARCH-SCIENTIFIC-METHODS.md](./RESEARCH-SCIENTIFIC-METHODS.md) | 调研补强 | 科研统计（SC01–SC92） | — |
| [SPEC-54-延续性统计分析模块.md](../SPEC-54-延续性统计分析模块.md) | 场景包 | A1–A7 编排、画像契约、T0.5 后续门禁、文本模板 | v1.5 |
| [SPEC评审报告-延续性统计分析模块-v0.1.md](../SPEC评审报告-延续性统计分析模块-v0.1.md) | 评审档案（只读） | 评审结论与复审记录 | v0.1 |
| [SPEC-54-统计图表化能力.md](../SPEC-54-统计图表化能力.md) | 可视化契约 | `data.visual` 图种白名单（table/series/matrix/tree/graph）、渲染门禁、P0–P4 路线 | v0.1（评审中） |
| [SPEC评审报告-统计图表化能力-v0.1.md](../SPEC评审报告-统计图表化能力-v0.1.md) | 评审档案（只读） | 有条件通过（3.70/5）、B1–B5、复审清单 | v0.1 |

**四层分工**：方法库（怎么算）→ 本文 §2（能问什么）→ 场景包（一次问全）→ MERS/Discovery（是否稳定）。完整定义与「场景包 vs 评估层」对比见 **§0.5**（本文自洽，无需跳转）。

### 0.2 六类问题的能力地图

```
① 取数      19 DAL（只读）/ 18 落库 / OKX candles
      ↓
② 对齐      UTC 日收盘 · 跨源去重 · ffill + stale cap · PIT          ← l1agg/align.py
      ↓
③ 单维事实  S/D 组（均值/分位/z/回撤）
      ↓
④ 周期      C 组（月份/星期/月内日/节日）+ T25–T26（FFT 主周期）
      ↓
⑤ 惯性      F12/F17/F18（自相关/反转/连胜）+ T14（方差比）
      ↓
⑥ 延续      T08–T09（斜率）· T13（Hurst）· T20–T21（半衰期）· B13–B15（IC 衰减）
      ↓
⑦ 相关      M01–M12（相关/偏相关/CCF）· M23–M25（同向率/稳定性/突变）
      ↓
⑧ 状态化    B01–B04（分箱/离散化）· B07–B09（转移/稳态/停留）
      ↓
⑨ 多维条件  B05–B06/B10（条件分组/交叉表/条件分位）+ R01/R02/R08
      ↓
⑩ 评估      MERS：RankIC / p_adj / holdout 同号 / 随机数据 stable=0 / 状态机
```

#### 0.2.0 三类用户问题的统一映射（调研对齐）

> 用户设想与现有 S1→S2→S3→S4→S5 路线一致，但「知道趋势发展方向」必须拆成**已经形成的方向、序列自身的延续性、历史同状态后的条件分布**三个问题。三者可以组合回答，不能合并成「下一阶段会涨/跌」。

| 用户问题 | 严格技术含义 | 方法 / 能力出口 | 允许的回答 |
|---|---|---|---|
| 价格与数据对齐后，对比过去与现在，趋势向哪里发展？ | 先描述过去与当前已经形成的方向，再单独度量序列是否有延续性 | 对齐 R18；S15/S16/S25/S28、T08/T09/T13/T14/T20/T21；D-B08、D-E13 | `current_state` + `persistence_profile`：当前方向、斜率、长记忆/均值回复证据及其不确定度 |
| 对照价格与数据，哪些关系对最强？ | 按问题类型分别生成同期、领先滞后、前瞻 IC 与样本外稳定榜单，不能只给一张相关系数榜 | M01–M07/M11–M12/M24–M25、B13/B14；R05/R06；D-E05/D-E06/D-E08/D-E11；MERS D-K01 | `relationship_topk`：必须标注榜单类型、`lag/window/h/n/p_adj/align_method` |
| 对比历史周期的后续表现，当前价格下一阶段可能怎样？ | 用 PIT 历史状态匹配，给出同状态后的条件收益分布；不是周期外推或点预测 | B02/B05/B10、R01/R02/R08；D-E02；T0.5（S3→S4）；D-E14（T2/S4，一维已接线） | `conditional_distribution`：均值/中位/胜率/区间/有效样本量，并固定声明历史统计边界 |

调研印证：延续性三层拆解与 T 阶段见 [RESEARCH-TREND-PERSISTENCE-MODELS.md](./RESEARCH-TREND-PERSISTENCE-MODELS.md)；PIT、滚动研究与多重比较见 [RESEARCH-INSTITUTIONAL-L1-METHODS.md](./RESEARCH-INSTITUTIONAL-L1-METHODS.md)；可复现、不确定度与 PIT 校验见 [RESEARCH-SCIENTIFIC-METHODS.md](./RESEARCH-SCIENTIFIC-METHODS.md)。

**组合回答骨架（规划契约，不替换现有 `CapabilityResult`）**：`current_state / persistence_profile / relationship_topk / conditional_distribution / robustness / quality / caveat`。每项统计必须携带 `n/window/as_of/align_method/timezone`，涉及显著性时补 `p_adj`；尾注固定为「历史统计，不代表未来」，禁止「将会、预计、必然」等措辞。

#### 0.2.1 数据与价格对齐（地基）

| 子问题 | 方法 ID | 能力 ID | 实现状态 |
|---|---|---|---|
| UTC 日收盘、跨源去重、低频 ffill、stale 上限 | 口径见 `align.py`，原语 R18；`market.candles` 1d 另有**收盘锚点** `bar_close`/`snapshot_last`（跨资产统计须同锚点） | D-E12 ✅ | ✅ `l1agg/align.py` / `capabilities/stats.py::alignment_slice` / `l0_foundation.py::_fetch_market_candles` |
| 价格轴派生 1D/1W/1M | S20–S23 | D-B00（🟡→✅） | ✅ `market.candles` |
| 前视规避（PIT，`as_of` / 宏观 `release_ts`） | SC90、R02 | D-J30 ✅ | ✅ R02 `pit=true` 已实现（`conditional.py`：逐时点滚动分位 + `release_ts≤as_of` 过滤）；✅ SC90 方法层已实现；✅ D-J30 全局能力已接线（`stats.py::pit_alignment`：SC90 校验可用时间≤使用时间 + R02 PIT 前瞻分布，违规降级披露） |
| 缺口/陈旧度披露 | S02 | 所有能力 `quality` | ✅ 信封字段已有 |

#### 0.2.2 数据 ↔ 价格相关性

| 子问题 | 方法 ID | 能力 ID | 实现状态 | 门禁 |
|---|---|---|---|---|
| 同期相关（Pearson/Spearman/Kendall/滚动） | M01–M04 | D-E05 ✅ | 双序列 M01/M02/M03/M04/M23 已接线；任一位置缺失/非有限值时按原始位置整行剔除，不错位配对 | ≥60 对齐点 |
| 相关矩阵 TopK / 平均相关度 | M05–M07 | D-E05 ✅ | 多资产矩阵已接线：逐对 paired complete-case + M05/M06/M07，按 \|rho\| 输出 TopK 并披露 BH-FDR | 多资产对齐，≥60 点 |
| 偏相关（剔除共同趋势） | M08 | **未登记** | ✅ 方法层已实现（`correlation.py`）；⬜ 能力未接线 | ≥120 点 |
| 领先滞后 CCF / 最优 lag | M11–M12、T03–T04 | D-E06 ✅ | T03/T04 保留 legacy 描述；M11/M12 为主推断，对完整 lag 搜索空间做 BH-FDR，并有确定性随机负例 | ≥120 点 |
| 相关稳定性 / 突变 | M24–M25 | D-E11 ✅ | ✅ 方法与能力已接线（`correlation.py`） | 滚动窗口 ≥3 |
| 跨资产同向率 | M23、C18 | D-E11 ✅ | M23 与 C18 均已接入 manifest；提供 dates 时按 paired complete-case 的原始行号同步过滤收益与日期，计算自然月同向率 | 多资产对齐 |
| 距离相关（非线性） | M09 | 部分归 D-J24 | ✅ 方法层已实现（`correlation.py`）；⬜ 能力未接线 | ≥120 点 |

**四类榜单不得混排**：

| 榜单 | 方法 / 原语 | 能说明什么 | 不能说明什么 |
|---|---|---|---|
| 同期联动 TopK | M05/M06 + R05 | 同一窗口内共同波动强弱 | 不说明领先关系，也不说明趋势会延续 |
| 历史领先滞后 TopK | M11/M12 + R06 | 历史样本中哪个 lag 的联动最强 | 不自动等于因果或未来可预测 |
| 前瞻关系 TopK | B13/B14，按 h 分别计算 | 因子状态与后续 h 期收益的样本内单调关系 | 未经样本外验证不得推荐 |
| 稳定推荐 TopK | MERS / D-K01 | 通过 BH-FDR、前后半段同号、holdout 同号与 walk-forward 的关系 | 仍不是收益保证或交易信号 |

> 纪律：批量扫描的完整搜索空间是「**关系对 × lag × window × h**」，必须在同一搜索族内做 H13/H14 校正；≥10 组比较不得只挑最大相关而不报 `p_adj`。随机序列负例按 SPEC 验收口径执行。

#### 0.2.3 周期性 / 季节性

| 子问题 | 方法 ID | 能力 ID | 实现状态 | 最小数据 |
|---|---|---|---|---|
| 月份效应（「五穷六绝七翻身」） | C01–C04、C14、C15 | D-E03 ✅ | ✅ 能力层（`capabilities/stats.py::seasonality`）；<60 月标 `seasonality_depth_lt_5y` | **≥5 年（60 个月）** |
| 月内日效应（「八横九涨十回调」类月内节奏） | C07、C08 | D-E03 ✅ | ✅ 方法层 `seasonal.py`（C07/C08） | ≥3 年 |
| 星期效应 | C05 | D-E03 ✅ | ✅ 能力层已接线（`seasonal.py::c05_weekday_effect`） | ≥2 年 |
| 节日/事件前后 | C11 + F19–F23 | D-E04 ✅ | ❌ C11 缺交易日历（登记不可用）；✅ F19/F22/F23 方法层已实现（`timeseries.py`），✅ 事件历史已云端回填入库（`mm_events=550`，2015–2026 共 543 行），✅ 能力出口已接线（`capabilities/stats.py::event_study`） | 事件表 + ≥3 年 |
| 季节强度 / STL | C13、T10、SC91 | D-J02 ✅ | ✅ 已接线（`capabilities/stats.py::seasonal_adjustment`）：C13 月度 ANOVA 式强度、T10 robust STL 与 SC91 X-13 风格分解原始结果并列输出；完整日期轴必填，历史不足 3 年降级为描述性结论 | 计算 n≥60；结论纵深 ≥3 年且 ≥2 周期 |
| 主周期 / 频谱 | T25–T26、SC39、SC41 | D-J05 ⬜ | ✅ T25–T26 方法层已实现（`timeseries.py`，FFT/DFT）；⬜ 能力未接线 | ≥2 个完整周期 |
| 周期失效（变点） | T22–T23、SC49–SC51 | D-J04 ✅ | ✅ 已接线（`capabilities/stats.py::change_point`）：两种 CUSUM、近似/精确 PELT 与 Pettitt 原始结果及日期映射；SC47 Kalman、SC48 互谱相干不属于本出口 | 方法门禁 n≥60；周期失效解释仍需足够历史纵深 |
| 比特币四年周期（≈1,460 日） | T25 + C14 | D-J05 ⬜ | ✅ 方法层已实现（`timeseries.py`）；❌ 样本纵深不足，不出结论 | **≥2 周期 ≈2,920 日** |

> 口径提醒：`C01` 用的是「自然月收益」，与「月内交易日节奏（C07/C08）」是两件事；「八横九涨十回调」若指月份顺序归 C01，若指月内节奏归 C07–C08，回答时必须先声明口径。
>
> **周期三种含义必须分流**：①日历/季节周期 → C 组、D-E03、R03/R15；②趋势/波动/相关状态周期 → B07–B09、T0.5、D-E14；③相似历史片段类比 → 当前尚无完整方法契约，不得用 FFT 或季节性冒充。T25–T26 频谱只识别历史主周期，不证明未来仍按该周期运行；月份强结论与比特币四年周期继续受本表样本纵深门禁约束。

#### 0.2.4 惯性 / 动量

| 子问题 | 方法 ID | 能力 ID | 实现状态 |
|---|---|---|---|
| 收益自相关 ACF/PACF | T01–T02、F12 | D-E08 🟡 | ✅ 方法层（`timeseries.py`） |
| 连胜/连败长度 | F18 | D-E13 ✅ | ✅ 已交付（场景包 + `timeseries.py::f18_runs`） |
| 反转比例（上期涨→本期跌） | F17 | D-E13 🟡 | ✅ 方法层（`timeseries.py::f17_reversal`） |
| 动量 / ROC / 动量排序 | F14–F16 | D-G08 ✅（12-1 动量） | ✅ 能力出口 `momentum_12_1`（F14 在 skip 后窗口真实执行动量/波动/风险调整动量；F15/F16 方法层已实现，跨资产排序未接线） |
| 波动聚集 | T17–T19、F13 | D-G14 🟡（EWMA） | ✅ 方法层（`timeseries.py`） |
| 惯性强度（方差比） | T14 | D-E13 ✅ | ✅ 已交付（场景包 + `timeseries.py::t14_variance_ratio`） |

> 区分：**惯性**看「符号是否延续」（F17/F18/ACF），**延续性**看「序列是否长记忆」（T13/T14/T20）。两者不能互相替代。

#### 0.2.5 趋势延续性

| 子问题 | 方法 ID | 能力 ID | 实现状态 |
|---|---|---|---|
| 斜率 + 显著性 | T08–T09 | D-B08 ✅ / D-E13 ✅ | ✅ 能力出口 `slope_trend`（T08 斜率/R² + T09 名义 t/p，`hac_corrected=false` 显式披露） |
| Hurst 长记忆 | T13 | D-E13 ✅ | 已交付（n<2000 标 low） |
| AR(1) 半衰期 | T20–T21 | D-E13 ✅ | 已交付 |
| IC 衰减（重叠 + 相位） | B13–B15 | D-E13 ✅ / D-G19 ✅（已接线） | 场景包已交付；`conditional.py` |
| 方向态转移矩阵 | B04、B07–B09 | D-E07 ✅（D-E13 内含方向态） | ✅ 方法与能力已接线（`inference.py` / `capabilities/stats.py`） |
| 单资产状态→历史同状态前瞻分布 | B02/B05 + R01/R02 | T0.5 ✅（S3→S4，经 D-E02 出口交付） | ✅ R02 `pit=true` + A8 场景编排（`persistence/profile.py::conditional_distribution`）+ D-E02 能力出口与前端分派均已接线；首版 h=1、4 桶（样本不足自动降 2 桶并披露），禁止全样本分位边界 |
| Newey-West / Deflated Sharpe | Q06/Q07（SC 组） | D-G22 ✅ | 方法层 `research_pq.py`；能力层 `capabilities/stats.py::hac_significance`（`significance_query`，deterministic，`min_n=250`）。h>1 重叠前瞻收益须经此出口再作显著性结论；DSR 退化时降级 partial 仍保留 HAC t |

#### 0.2.6 单维 → 多维

| 子问题 | 方法 ID | 能力 ID | 实现状态 |
|---|---|---|---|
| 等宽/等频/阈值分箱 | B01–B03 | D-E07 ✅ | ✅ 方法与状态转移能力已接线；分箱本身由方法注册表提供 |
| 二维交叉表 | B06 | D-E07 ✅ | ✅ 已纳入 manifest 与 `state_transition`，输出 `state_t × state_{t+1}` 联合计数底表；B07 对同一状态轴做行归一化 |
| 条件分布（状态 → 前瞻） | B05、B10 + R01/R02/R08 | D-E14 ✅（一维） | ✅ 已接线（`capabilities/stats.py::conditional_distribution`）：输入已压缩的一维相关状态，R02 `pit=true` 统一生成 PIT 桶标签，B05/B10/R01/R08 复用同一状态轴；默认 h=1/2、4 桶，主期限不足降 2 桶，弱后续期限单独降级，h>1 不输出朴素 t/p。**T-1 已入库** 20 资产 / 54,653 行；2 维 4×4 仍需 ≥4000 天/资产，未在一维出口中冒充完成 |
| 降维（PCA/聚类） | M19–M22、SC31–SC38 | D-J22 ✅ | ✅ 方法层已实现；✅ D-J22 已接线（M19/M20/SC31/SC32/SC33 五方法并列）；M21 已归入 D-J24 网络聚类，M22 等聚类方法仍属 D-J23 未接线 |
| 相关网络 / 社区 | M05、M21、SC71–SC72 | D-J24 ✅ | ✅ 方法层已实现（`correlation.py`/`research_sc_b.py`）；✅ 已接线（M05 相关矩阵 → |ρ| 阈值邻接 → SC71 中心性 + SC72 Louvain + M21 层次聚类） | ≥60 点/≥2 变量 |
| 状态爆炸控制 | 门禁：每桶非重叠 n≥250 | — | **规则已定（T2）**；首版限 1–2 维 |

> **D-E14 不直接消费完整 N×N 矩阵**。相关状态先压缩为调研定义的 F1–F12，例如 F1 平均相关度、F2 第一特征值占比、F4 相关突变 z-score、F8 相关稳定性，再与 F11 趋势斜率 t、F12 波动率分位组合；T2 首版仍只选 1–2 维，避免状态数乘积导致每桶样本崩塌。

### 0.3 数据可行性矩阵（决策摘要，事实源为 METHOD_LIBRARY §15）

> 本表实测数值均**引自 [METHOD_LIBRARY §15](./METHOD_LIBRARY.md) 同日快照**，用于解释门禁与样本预算，不另立数据事实源；执行时必须按最新快照重算。

| 需求 | 所需历史 | 现有 | 结论 |
|---|---|---|---|
| 单序列描述统计 | ≥30 点 | 27,290 个 sub::metric 中 25,795 个仅 1 天 | 仅价格类与少数宏观可做 |
| 同期相关 | ≥60 对齐点 | 与 BTC 日频重叠 ≥60 天仅 26 条 | 可做（小池子） |
| 领先滞后 CCF | ≥120 对齐点 | 上述 26 条中更少 | 勉强 |
| 条件收益 / IC | ≥250 对齐点 | ≥250 天序列 28 条 | 仅价格 + 极少数 |
| 星期效应 | ≥2 年 | 1,094 日（≈156 周） | ✅ 可做 |
| 月内日效应 | ≥3 年 | 1,094 日 | 🟡 勉强 |
| 月份效应（五穷六绝） | ≥5 年（60 月） | 36 个月 | ❌ 每月仅 3 个样本 |
| 季节强度 STL | ≥3 年且 ≥2 周期 | 36 个月 | 🟡 勉强 |
| 比特币四年周期 | ≥2×1,460≈2,920 日 | 1,094 日 | ❌ 不足 1 个完整周期 |
| Hurst 可信 | ≥2,000 点 | 1,094 点 | ⚠️ 只给 low，不给 regime |
| 条件分布（h=1，4 桶） | 每桶非重叠 ≥250 | 273/桶 | ✅ 仅 h=1 |
| 条件分布（h≥5） | 每桶非重叠 ≥250 | h=5→54/桶、h=20→13/桶 | ❌ |
| 二维状态（4×4 桶） | 16×250＝4,000 日 | 1,094 日 | ❌ |

> **关键结论**：当前瓶颈不是方法、不是对齐，而是**历史纵深 1,094 日**。除星期效应、h=1 条件分布、单资产延续性画像外，其余周期性/多维结论都只能等 T-1 扩样本（≥3,000 日，理想 ≥5 年）。任何在这些需求上「先跑个数」的输出，都会被 n 不足污染。

### 0.4 文档治理规则（v2.0 起强制）

1. **方法 ID** 只在 METHOD_LIBRARY 新增/改口径；本文与场景包只能引用。
2. **能力 ID `D-*`** 只在本文登记；SPEC-54 只写契约，不新建能力 ID。
3. **场景编排** 只在场景包 SPEC；不得在本文写实现细节。
4. **路线编号**：SPEC 用 S1–S5、方法库 §14 用 S0–S7、场景包用 T0–T4，**跨文档引用必须成对出现**（如「T0 = S3 自身延续性子集」「T0.5 = S3→S4」）。
5. **数据事实唯一事实源是 METHOD_LIBRARY §15**；其他文档只能以「引自 §15」方式保留决策所需摘要或派生样本预算，不得独立更新实测数字，执行时以最新快照重算。
6. **状态列变更**（✅/🟡/⬜）必须同时附代码位置或脚本名，禁止只改图标。

### 0.5 四层分工与边界（v2.1）

> 目的：同一套统计在四份文档里反复出现时，**不重复定义、不重复计数、不重复实现**。四层的原文定义在 [SPEC-54 §3.5](../SPEC-54-L1架构能力聚合层.md)，此处复述以保证本文自洽。

#### 0.5.1 四层各管什么

| 层 | 载体 | 回答什么 | 命名单位 | 是否新增方法 | 出口标识 |
|---|---|---|---|---|---|
| ① **方法层** | [METHOD_LIBRARY.md](./METHOD_LIBRARY.md) + 两份 RESEARCH 补强 | 某个统计量**怎么算**、需要多少样本、D1/D2/D3 哪级 | 方法 ID（`T13`/`M01`/`B13`…）+ 关系原语 `R01–R18` | **是，唯一 SSoT** | 方法 ID 本身 |
| ② **能力层** | **本文 §2 能力登记** + SPEC-54 §四/§五契约 | 用户一句话**能问什么**、走哪个 scope、返回什么信封 | `D-A/B/C/E/G/J/K` 能力 ID | 否（只组合 + 绑 scope） | `D-*` |
| ③ **场景包** | [SPEC-54-延续性统计分析模块.md](../SPEC-54-延续性统计分析模块.md)（代码 `l1agg/persistence/`） | 一个资产「**有没有记忆**」的一站式画像 | `D-E13`（画像）+ A1–A7 编排 | 否（纯编排，全部映射既有方法 ID） | `D-E13` |
| ④ **评估层** | SPEC-54 §14 MERS / §15 Discovery / §17.1.3 S5 回测排名 | 某关系在某资产某期限上**是否稳定、是否推荐** | 评估单元 `eval_id` | 否（批量跑②③的方法并评分） | `D-K01`（推荐）/ `D-K02`（查询） |

一句话类比：方法库是**体检项目表**，能力层是**挂号窗口**，场景包是**体检套餐**，MERS/Discovery 是**年度复查与排名**。

#### 0.5.2 场景包（③）与统计回测相关性（④）的区别

这是最容易混的一对——两者都用「数据 × 价格对齐 + 统计量」，但目标变量和输出完全不同。

| 维度 | 延续性统计分析（③ 场景包） | 统计回测相关性（④ 评估层） |
|---|---|---|
| 目标变量 | 固定为**本资产价格的前瞻收益** | 关系单元的**稳定性评分**（不针对某个资产写死） |
| 问题 | 「这个序列自身有没有记忆」 | 「指标 X 与资产 Y 在 h 期限上的关系是否可复现」 |
| 范围 | 单资产、无条件、一次性 | 跨序列、条件化、周期性重跑 + 状态机 |
| 输出 | 一张画像（7 个数字 + 一句话） | `relationship_registry.db` 排序表 + 推荐 |
| 数据门槛 | 仅需价格（当前纵深见 METHOD_LIBRARY §15） | 价格腿已够；真正缺口是加密域指标纵深与专用表空表（见 METHOD_LIBRARY §15） |
| 共同点 | 共用方法库、共用 `l1agg/align.py`、共用门禁语言（`n≥`、`p_adj`、`align_method`） | 同左 |

#### 0.5.3 边界纪律（硬约束）

1. **方法口径只在方法库定义一次**：本文、场景包、MERS 都只能引用 ID，不得另写一份实现或改参数默认值；口径变更须回写场景包测试与 MERS 网格版本。
2. **评估层不得重定义方法**：MERS/Discovery 只做「批量调用 + 评分 + 排名」，不新增统计量；发现新需求先回方法库登记 ID。
3. **场景包不得输出推荐/排序**：`D-E13` 只给描述性画像与 `status`，不给「该不该买」「哪个资产最好」。
4. **能力登记不重复计数**：`D-E13 = D-E07（状态转移）+ D-E08（分箱/IC）+ T 组方法`的场景编排，不新增方法 ID；`D-E14` 依赖 `D-E05/D-E06/D-E11`。
5. **前瞻收益唯一实现** = `l1agg/align.forward_returns`；场景包 A7 与 MERS B13–B16 必须调同一函数。
6. **能力归属（本文 §2 的读法）**：`D-E13` 归③场景包出口，`D-K01/D-K02` 归④评估层出口，其余 `D-*` 为②能力层出口——同一方法可被多层消费，但在 §2 只登记一次。

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

## §2 数据维度能力登记（103 项：A16 / B10 / C6 / E14 / G25 / J30 / K2）

状态口径：`✅ 已有实现` ｜ `🟡 部分可用` ｜ `⬜ 待实现`，按**本表登记范围**判定；「manifest 已接线」只表示可执行子集，不等于全部依赖方法已接。优先级：P0/P1/P2（P0 = SPEC-54 当前迭代）。

> **v2.10 方法层与验证覆盖口径**：方法库 387 条已登记、**386 条已实现**（仅 C11 缺交易日历不可用），audit 386/386 PASS；PASS 只表示已执行检查通过，不代表六类检查全覆盖。当前验证覆盖率 66.15%，缺失检查与不适用检查分别披露。因此下表中的 `⬜`/`🟡` 只表示**能力尚未接线或编排未闭环**，不再表示“方法缺失”；凡状态列写明“方法层已实现”的，方法可直接 `run()` 调用，但能力出口仍需按 `capability_manifest.yaml` 接线。

### 2.1 A 组：库内时序衍生（16 项，零新增采集）

数据源统一为 `19-DAL mm_metrics`；**行数、序列数与纵深事实唯一来源为 [METHOD_LIBRARY §15](./METHOD_LIBRARY.md)**，本文不另立实测口径。

| ID | 能力 | 数据依赖 | 确定性计算 | 输出字段 | L1 意图 | mode | 优先级 | 状态 |
|---|---|---|---|---|---|---|---|---|
| D-A01 | 历史序列 | 单序列 | 区间取点 + 降采样(日/周/月) | `points[], span, unit` | metric_series | deterministic | P0 | ✅ |
| D-A02 | 变化率 | 单序列 | `(v_t/v_{t-n})-1` | `change, change_pct, window` | metric_series | deterministic | P0 | ✅ |
| D-A03 | CAGR | 正指数型序列 | 首末值 + 年数 | `cagr, years` | metric_series | deterministic | P1 | ✅ |
| D-A04 | 历史分位 | 单序列 | 末值在最近 lookback 期的经验分位 | `percentile, value, lookback, sample_n` | metric_percentile | deterministic | P1 | ✅ S25 + `capabilities.stats.percentile_rank`；`lookback` 缺省全样本，窗口 <60 期降级 `short_lookback`，lookback 超可用历史降级 `lookback_truncated` |
| D-A05 | z-score | 单序列 | `(v-μ)/σ`（winsorize p1/p99） | `zscore, mean, std` | metric_percentile | deterministic | P1 | ⬜ |
| D-A06 | 年化波动率 | 单序列 | 日收益率标准差 × √365 | `volatility, mean_ret, window, sample_n` | metric_series | deterministic | P1 | ✅ F05 + `capabilities.stats.annualized_volatility`；`window` 缺省全样本，有效样本 <60 期降级 `short_window` |
| D-A07 | 回撤 | 单序列 | `v/max(prefix)-1` | `drawdown, peak_ts` | drawdown_query | deterministic | P1 | ✅ 与 D-E10 共用 `capabilities.stats.drawdown`（注入 `capability_id=D-A07`），D20/D21 真实执行；`prices<2` 为空，样本 <250 期降级 |
| D-A08 | 同比 | 月频宏观序列 | 与 12 期前比较 | `yoy, base_ts` | metric_series | deterministic | P1 | ✅ S16（period 可配，默认 12）+ `capabilities.stats.yoy_change`；历史 <2 个完整周期降级 `short_history`，基期 0 降级 `yoy_unavailable` |
| D-A09 | 环比 | 月频/日频 | 与上一期比较 | `mom, base_ts` | metric_series | deterministic | P1 | ✅ S16（k=1）+ `capabilities.stats.mom_change`；基期 0 降级 `mom_unavailable` |
| D-A10 | 实际利率 | `DGS10` + `CPIAUCSL` | 10Y 收益率 − CPI 同比 | `real_rate, nominal, inflation` | metric_derived | deterministic | P1 | ✅ S16 派生 + `capabilities.stats.real_rate`；通胀由 S16（period 默认 12）折算百分点，CPI 基期 0 降级 `inflation_unavailable`，历史 <2 个完整周期降级 `short_history` |
| D-A11 | 双序列滚动相关性 | 两条序列 | Pearson，30/90d 窗口 | `corr, window, sample_n` | correlation_query | deterministic | P2 | ✅ M04 + `capabilities.stats.rolling_correlation`：paired complete-case 后输出 `corr/mean_r/window/n_windows/sample_n`；有效配对 <60 降级 `insufficient_samples` 但保留结果 |
| D-A12 | 领先滞后相关 | 两条序列 | lag 0–10 的相关系数序列 | `best_lag, corr_by_lag[]` | correlation_query | deterministic | P2 | ✅ M11 + M12 + `capabilities.stats.lead_lag_correlation`：M11 输出 lag −max_lag…+max_lag 的相关/p/BH-FDR q，M12 输出最优 lag；有效配对 <120 降级 `insufficient_history` 但保留结果 |
| D-A13 | 极端事件频率 | 单序列 | 超阈值天数 / 占比 | `days, ratio, threshold` | metric_series | deterministic | P2 | ✅ S11（缺省阈值）+ `capabilities.stats.extreme_frequency`；计数为纯聚合，样本 <30 且无阈值即 empty，有阈值降级 `insufficient_samples` |
| D-A14 | 拥挤度 | 资金费率 + 多空比 + 未平仓 | 分位加权合成 + A 分位法四档 | `score, components, weights, level, percentile, thresholds, window, as_of` | metric_percentile | deterministic | P2 | ✅ F26 + `capabilities.stats.crowding`；`level` 按分值历史分布 p20/p60/p80 分档，样本不足/分布退化降级不补阈值 |
| D-A15 | ETF 净流入滚动和 | ETF 净流入序列 | 7/30d 滚动求和 | `sum_7d, sum_30d` | metric_series | deterministic | P2 | ✅ S20 滚动均值 × 窗口长度（算术还原）+ `capabilities.stats.etf_flow_rolling`；`windows` 可配（默认 7/30），样本 <30 降级 `insufficient_samples`，窗口超历史降级 `short_history` |
| D-A16 | 稳定币增速 | USDT/USDC 规模序列 | 7/30d 增速 | `growth_7d, growth_30d` | metric_series | deterministic | P2 | ✅ S16 逐窗口执行 + `capabilities.stats.stablecoin_growth`；`windows` 可配（默认 7/30），样本 <30 降级 `insufficient_samples`，窗口超历史降级 `short_history`，基期 0 降级 `base_zero` |

### 2.2 B 组：技术指标（10 项，依赖 `market.candles`）

数据源：`market.candles` —— **1D/1W/1M 由 `mm_metrics` 日频收盘派生（S1 已落地，价格纵深见 METHOD_LIBRARY §15）**；OHLC 自 2026-11-14 接入（`1h` 取 `{symbol}/USDT` 小时级 `last/high/low`，`1d/1w/1m` 合并同源桶内 high/low）。库内高低点为 ccxt ticker 24h 滚动口径；1D 全桶覆盖不足时 L1 回退 1H 并如实标注。仍无 OHLC 时 I 组直接返回 `insufficient_history`。**禁止** `10-经典指标系统/generate_history.py` 的合成蜡烛。

日线对齐（v2.5）：1d 的 `ts` 统一归一到 UTC 日首，真实观测时刻保留 `close_ts`；`meta.close_anchor` 标注收盘锚点——`bar_close`（`*_1d` 真实日线，锚点=UTC 日末）/ `snapshot_last`（日频快照，锚点=当日最后观测）。**跨资产相关性/领先滞后必须两侧同锚点**：`l1agg.candles.load(..., source_policy="snapshot")` 优先，某标的无快照才退回 `auto` 并在回答标注（实测 BTC–ETH 同期 ρ 从 0.33 → 0.83，最优 lag 回到 0）。

| ID | 能力 | 数据依赖 | 确定性计算 | 输出字段 | L1 意图 | mode | 优先级 | 状态 |
|---|---|---|---|---|---|---|---|---|
| D-B00 | K 线获取 | `market.candles`（日频派生 + 可选 OKX 实时） | 日轴取点 + 1W/1M 聚合 + `is_stale` | `candles[], source, fetched_at` | technical_indicator | deterministic | P1 | ✅ S1 已落地 + `l1agg/candles.py` |
| D-B01 | MA / EMA | candles(close) | N 期均值/指数均值 | `ma20, ma60, ema12, ema26` | technical_indicator | deterministic | P1 | ✅ L1 已接入（I01/I02） |
| D-B02 | RSI | candles(close) | Wilder 14 期 | `rsi14, zone(超买/超卖/中性)` | technical_indicator | deterministic | P1 | ✅ L1 已接入（I07） |
| D-B03 | MACD | candles(close) | EMA12−EMA26，DEA=EMA9(DIF) | `dif, dea, hist, cross` | technical_indicator | deterministic | P1 | ✅ L1 已接入（I09） |
| D-B04 | ATR | candles(HLC) | Wilder 14 期真实波幅 | `atr14, atr_pct` | technical_indicator | deterministic | P1 | ✅ L1 已接入（I12）；回退 1H 时高低点为 ticker 24h 滚动口径（meta 标注） |
| D-B05 | 布林带位置 | candles(close) | 20 期均值 ±2σ | `boll_pos, upper, lower` | technical_indicator | deterministic | P1 | ✅ L1 已接入（I14/I15） |
| D-B06 | 量能比 | candles(volume) | 当前量 / N 日均量 | `vol_ratio, base_vol` | technical_indicator | deterministic | P1 | ✅ L1 已接入（I17） |
| D-B07 | 支撑/压力位 | candles(high/low) | 近 N 日极值 + 触碰次数 | `support, resistance, touches` | technical_indicator | deterministic | P2 | ✅ L1 已接入（I20–I23）；日线 OHLC 不全时回退 1H，无 OHLC 则 `insufficient_history` |
| D-B08 | 趋势斜率 | candles(close) | 线性回归斜率（标准化） | `slope, r2, window` | technical_indicator | deterministic | P2 | ✅ T08 + T09（名义 t/p）+ `capabilities.stats.slope_trend`；默认 90 日窗口、下限 30，样本 <60 降级 `short_window`；明确 `hac_corrected=false` |
| D-B09 | 距 ATH 回撤 | candles(全历史/缓存) | `price/max-1` | `drawdown_from_ath, ath, ath_ts` | technical_indicator | deterministic | P2 | ✅ 复用 D-E10 的 D20/D21 执行器 + `capabilities.stats.ath_drawdown`；`drawdown_from_ath/ath/ath_ts` 为 `current_drawdown/peak_price/peak_ts` 的别名映射，样本 <250 降级 `insufficient_samples` |

> **L1 接入（2026-11-14）**：`l1agg/candles.py`（D-B00，L0 信封 → `CandleSet`，含 `has_ohlc/is_stale`）+ `l1agg/methods/technical.py`（I 组方法）+ `l1agg/technical.py`（`analyze()` 编排，意图 `technical_indicator`，`n<120` 只回 `insufficient_history`，无 OHLC 时 D-B04/D-B07 显式降级，绝不伪造高低点）。测试：`tests/test_technical_indicators.py`。

### 2.3 C 组：已具备模型输出（6 项，零计算）

| ID | 能力 | 数据依赖（L0 scope） | 输出字段 | L1 意图 | mode | 优先级 | 状态 |
|---|---|---|---|---|---|---|---|
| D-C01 | bdsm 估值阶段/分位 | `yijing.bdsm` | `stage, score, percentile` | conditional_outlook | gated | P1 | ✅ |
| D-C02 | bcrm2 方向/置信度/卦象 | `yijing.bcrm2` | `direction, confidence, hexagram` | technical_indicator | gated | P1 | ✅ |
| D-C03 | 事件六维评分 | `event.state` | `scores[6], direction, confidence` | event_analysis | gated | P1 | ✅ |
| D-C04 | 持仓风控状态 | `riskcontrol.trailing` | `state, triggers, trailing_stop` | risk_control | gated | P1 | ✅ |
| D-C05 | 四维一致性 | `evolution.contradiction` | `dims[], verdict` | cross_check | gated | P2 | ✅ |
| D-C06 | 周期状态/战略承接 | `evolution.snapshot` + 43 | `cycle, phase, strategic` | conditional_outlook | gated | P2 | ✅ |

### 2.4 E 组：统计关系与价格表达（19 项，方法库驱动）

> 方法定义见 [METHOD_LIBRARY.md](./METHOD_LIBRARY.md)（238 方法 / 18 关系原语）。本组是「数据状态 → 价格表现」的固定统计出口，禁用因果与预测措辞。

| ID | 能力 | 依赖方法（方法库） | 数据前提 | L1 意图 | 优先级 | 状态 |
|---|---|---|---|---|---|---|
| D-E01 | 条件收益统计 | B02/B05 + F01 + H01 | 因子+价格 ≥250 点 | conditional_return | P2 | ✅ `capabilities/stats.py::conditional_return` 已接线；h=1，先在原价格轴计算前瞻收益，再过滤有效因子对 |
| D-E02 | 分位→前瞻收益 | I30 + R02 | 序列 ≥250 点；T0.5 另需每桶非重叠 n≥250 | metric_percentile | P1 | ✅ 已接线（manifest `I30/R02` + `capabilities/stats.py::percentile_forward` + 前端 `exec_stat_query` 分位 cue 分支，v2.9）；R02 `pit=false/pit=true` 双口径，A8/T0.5 经此出口交付（h=1，含 4→2 桶降级披露） |
| D-E03 | 季节性/日历效应 | C01–C04, C05, C07, C09, C12–C15 | 日收益 ≥60 天（**仅够星期/月内日**；月份效应需 ≥5 年，见 §0.3） | seasonality_query | P1 | ✅ 11 个声明方法均真实执行并输出（`capabilities/stats.py::seasonality`） |
| D-E04 | 事件研究窗 | F19–F23, H01 | 事件表（**已回填入库 550 行**）+ 价格 ≥250 点 | event_study | P2 | ✅ 已接线（`capabilities/stats.py::event_study`）：事件日对齐到价格轴（取首个不早于事件日的交易日）；F19 事件窗 CAR + F23 事件后分布 + F21 末段 CAR；事件数 <30 降级 partial（`events_lt_30`）但保留数值，价格 <250 或事件无法映射时 FAIL-OPEN 为 empty |
| D-E05 | 相关矩阵 TopK | M01–M07 | 多资产对齐 ≥60 点 | correlation_query | P2 | ✅ 双序列 M01–M04/M23 与矩阵 M05–M07 均已接线；逐对 paired complete-case，TopK 披露 BH-FDR |
| D-E06 | 领先滞后 | T03–T04, M11–M12 | 双序列 ≥120 点 | correlation_query | P2 | ✅ M11/M12 主推断覆盖完整 lag 搜索空间并做 BH-FDR；T03/T04 仅保留 legacy 描述 |
| D-E07 | 状态转移 | B02, B06–B09 | 状态序列 ≥100 点 | state_transition | P2 | ✅ B02 等频分位分箱；B06 输出相邻状态联合计数，B07 行归一化为转移概率，B08/B09 输出稳态与停留期；B04 不属于当前 executor |
| D-E08 | 分箱单调性/IC | B11/B13/B14 | 已对齐因子+前瞻收益，总配对样本 ≥250 点 | conditional_return | P2 | ✅ `conditional_ic` 逐行配对；min_n=250 是总样本门禁而非每桶门禁；B15 的 prices/IC decay 入口归 D-E13/D-G19 |
| D-E09 | 计数与共现 | B17 + R09/R10 | 事件序列（**已回填入库 550 行**） | metric_series | P1 | ✅ 已接线（`capabilities/stats.py::count_series`）：`values` 走 R09 涨跌次数，`pairs` 走 B17 共现计数 + R10 一句文案；对齐点 <3 FAIL-OPEN 为 empty |
| D-E10 | 回撤画像 | D20–D21 | 价格 ≥250 点 | drawdown_query | P1 | ✅ 能力层已接线；F09/F10 为同口径库内别名，不重复执行 |
| D-E11 | 跨资产同向率/相关突变 | M23–M25, C18 | 多资产对齐 ≥60 点 | cross_check | P2 | ✅ M23/M24/M25/C18 均已接线；dates 与双收益序列按原始行号同步过滤，无 dates 时不执行 C18 |
| D-E12 | 时空对齐切片 | R18 | 多资产同日数据 | cross_check | P2 | ✅ `capabilities/stats.py::alignment_slice` 已接线；样本不足与空窗口显式降级 |
| **D-E13** | **趋势延续性画像（场景包）** | T13 + T14 + T20/T21 + F18 + B07/B08 + T08/T09 + B13–B15 | 日频价格 ≥250 点（当前纵深见 METHOD_LIBRARY §15） | conditional_return（子集） | **P0** | ✅ 已交付（2026-11-14，27 用例） |
| **D-E14** | **相关状态条件分布（场景包）** | 一维相关状态 + B05/B10/R01/R02/R08 | 对齐样本 + **每桶非重叠 ≥250** | conditional_distribution | P2 | ✅ 一维首版已接线（2026-11-15，`capabilities/stats.py::conditional_distribution`）：R02 PIT 4 桶输出 h=1/2，主期限不足降 2 桶，弱后续期限单独降级；h>1 不输出朴素 t/p。二维 4×4 仍需 ≥4000 天/资产，见 #31 |
| D-E15 | 趋势曲线/多窗口斜率 | I02, T08, I32, I37 | 价格 ≥250 点 | trend_query | P2 | ✅ 已接线（`capabilities/stats.py::trend`）：EMA(12/26/50) 平滑 + 多窗口对数价格斜率(20/60/120/250) + ADX14，可选 I37 Kalman 局部线性趋势；对外只给统计事实 |
| D-E16 | 多成员加权聚合曲线 | S16 | 多资产同日 ≥60 点 | trend_query | P2 | ✅ 已接线（`capabilities/stats.py::aggregate_curve`）：成员先按自身首日 rebase 再按 `chart_weights` 加权，缺口不向前填充，逐点输出 `coverage_ratio/partial_members`；纯聚合展示，不含交易方向 |
| D-E17 | 五类分组看板 | S16, S25, M01, I32 | 跨资产公共日期轴 ≥60 点 | cross_check | P2 | ✅ 已接线（`capabilities/stats.py::class_board`）：`ret_60` 与 D-E12 同口径，组内按 `ret_60` 降序，`lit_n/warm_n` 直接消费 D-E19 计数（零重算）；样本低于 per-anchor 质量门时标 `degraded_reason` 并禁止点亮 |
| D-E18 | 资金流向导图 | M01, M02 | 多资产对齐 ≥60 点 | data_insight | P2 | ✅ 已接线（`capabilities/stats.py::flow_graph`）：ETF 净流入按滚动窗口 z-score 转 flow 边，无 flow 数据时降级 corr-only 且绝不伪造边；边严格 5 键 `src/dst/kind/weight/p_adj` |
| D-E19 | 四轴五态点亮投影 | I37, I36（cycle 轴取 I39 外部归一值） | per-anchor 250（代币化）/ 500 | trend_query | P2 | ✅ 已接线（`capabilities/stats.py::lights`）：轴强度 = \|轴值\|/轴权重（零重算），`lit/warm` 阈值默认 p70/p40 且未标定时显式打标；展示层不重算统计量 |

> **D-E13/D-E14 是场景编排，不新增方法 ID**：D-E13 = D-E07（状态转移）+ D-E08（分箱/IC）+ T 组方法的固定出口，一次调用输出「7 个度量 + 一句话」；D-E14 是「相关状态 → 前瞻分布」的条件化版本。实现、门禁与 T/S 映射见 [SPEC-54-延续性统计分析模块.md](../SPEC-54-延续性统计分析模块.md) 与 [SPEC-54-L1 §3.5](../SPEC-54-L1架构能力聚合层.md)。
>
> **T0.5 也不新增能力 ID**：它位于 S3→S4，复用 D-E02 的 R02 与 D-E13 的自身状态，首版只做 h=1、4 个 PIT 滚动分位桶；每桶非重叠 n≥250，不足按场景包降为 2 桶并披露有效 n。T0.5 已于 v2.9 经 D-E02 出口交付（A8 编排 + 前端分派），不得以全样本分位结果冒充交付。

**硬前提**：E 组价格腿已闭环，当前瓶颈转为**因子池纵深与 PIT 数据契约**（实测事实见 METHOD_LIBRARY §15）。D-E01/D-E02/D-E05/D-E08/D-E11 的能力接线已完成，实际可用性仍受对齐样本限制；D-E13 只依赖价格，不受跨资产因子池限制。

**方法层先行（v2.2）**：S3 批 22 方法已在 `l1agg/methods/conditional.py` 落地并通过 audit（当时 45/45 PASS；`docs/method_audit.json` 现为全量 386 方法产物）：分布 S11/S25/S26、收益风险 F01–F06、分箱 B01–B03、条件/分组 B05/B11/B12/B16、IC B13–B15、检验 H01、表达 R01/R02。门禁已内置（分布/收益 `min_n=30`、条件/IC/分组 `min_n=250`，不足即 `insufficient_samples`），数据回填完成后只需补能力层接线（scope + 意图 + 执行器），不再改方法口径。

**方法层先行（v2.3，统计学注册库全量补全）**：S6 批 62 方法落地——`descriptive.py`（S 组 26 + D 组 22）、`timeseries.py`（T 组 21 + F 组 12）、`inference.py`（H 组 13 + B 组 8 + M 组 2 + R 组 6）。注册表累计 **154 方法**，`method_audit.py` 全 PASS，`tests` 349 例全绿。当时跳过需要 statsmodels/scipy 拟合、FFT 或外部数据的 T05/T06/T10/T18/T23/T25/T26、D14/D15（v1.11 已全部补齐实现）。口径冻结见 [METHOD_LIBRARY §16](./METHOD_LIBRARY.md)。

> **当前计数（v2.25，勿再引用 154 为总量）**：注册表 `REGISTRY` 实际登记 **392 条 = 核心 243 + 调研族 149**；其中 `implemented=true` **391 条**；`implemented=false` 仅 **1 条**（C11 缺交易日历/节假日表，按纪律登记不可用）。核心 243 含 v2.25 前已落地的 I35–I39 美联储方法。方法库目录同为 **392 条**（X12/O15/P14/Q16/SC92），已无“只有编号占位”的方法。`all_specs(scope=...)` 支持 `core`(243)/`research`(149)/`all`(392)，默认 `core` 以保持 `catalog_total == 243`。
>
> 全量 `method_audit.py --scope all` 于 2026-11-15 的快照仍为 I35–I39 接入前口径（`catalog_total=238`），已写入 [docs/method_audit.json](./method_audit.json) 待重跑：**implemented 386 / passed 386 / failed 0**，`research_catalog_total=149`、`registered_total=387`；六类检查共 2316 项，真实执行 1028、不适用 762、缺失 526，适用检查覆盖率 **66.15%**。`pytest tests -q` → **772 passed**。PASS 不等于完整验证覆盖；上段 154 仅为 v2.3 时点记录，现已被完全包含。

**能力层接线（v2.48 补 D-E15～D-E19；v2.46 补 D-G09；v2.45 补 D-G08；v2.44 补 D-B09；v2.43 补 D-B08；v2.42 补 D-A16；v2.41 补 D-A15；v2.40 补 D-A13；v2.39 补 D-A12；v2.38 补 D-A11；v2.37 补 D-A10；v2.36 补 D-A09；v2.35 补 D-A08；v2.34 补 D-A07；v2.33 补 D-A06；v2.32 补 D-A04；v2.31 补 D-A03；v2.30 补 D-A02；v2.29 补 D-A01；v2.28 补 D-J30；v2.27 补 D-G14；v2.26 补 D-J24；v2.25 补 D-J22；v2.24 补 D-G20；v2.23 补 D-G19；v2.22 补 D-G16；v2.21 补 D-J02；v2.20 补 D-J04；v2.19 补 D-E07/B06；v2.18 补 D-G23；v2.17 补 D-E14；v2.16 补 D-E04/D-E09；v2.15 接入 D-A14；v2.14 扩到 G 组）**：`l1agg/capabilities/` 当前共有 **48 个可执行出口**（A 组 D-A01/D-A02/D-A03/D-A04/D-A06/D-A07/D-A08/D-A09/D-A10/D-A11/D-A12/D-A13/D-A14/D-A15/D-A16 + B 组 D-B08/D-B09 + E 组 19 个 + G 组 D-G08/D-G09/D-G14/D-G16/D-G19/D-G20/D-G22/D-G23 + J 组 D-J02/D-J04/D-J22/D-J24/D-J30），端到端产出 `CapabilityResult`，并对跨条件分支累计的真实方法调用做 manifest 覆盖校验：

| 文件 | 职责 |
|---|---|
| `capability_manifest.yaml` | 能力 → 意图 / scope / executor / 方法 / `min_n` 的**唯一事实源**（48 条） |
| `l1agg/capabilities/manifest.py` | 加载 + 绑定校验 + `validate_execution`：跨条件分支累计真实成功调用，拒绝未绑定调用与声明但从未执行的方法 |
| `l1agg/eval/harness.py` | 六类检查按 `executed/missing/not_applicable` 统计；方法级、检查级与全局覆盖率进入 JSON/CLI 报告，PASS 不再冒充全覆盖 |
| `l1agg/capabilities/envelope.py` | 统一信封组装 + 契约守卫（`quality` 只在顶层、partial 必带 `degraded_reason`、`answer` 非空） |
| `l1agg/capabilities/stats.py` | 45 个编排函数：`conditional_return` / `conditional_distribution` / `drawdown`（D-E10 与 D-A07 共用，注入 `capability_id`） / `seasonality` / `percentile_forward` / `state_transition` / `correlation` / `conditional_ic` / `alignment_slice` / `portfolio_risk` / `ic_profile` / `quantile_monotonic` / `hac_significance` / `crowding` / `event_study` / `event_car_significance` / `seasonal_adjustment` / `change_point` / `count_series` / `trend` / `dimension_reduction` / `correlation_network` / `ewma_risk` / `pit_alignment` / `history_series` / `change_rate` / `cagr` / `percentile_rank` / `annualized_volatility` / `yoy_change` / `mom_change` / `real_rate` / `rolling_correlation` / `lead_lag_correlation` / `extreme_frequency` / `etf_flow_rolling` / `stablecoin_growth` / `slope_trend` / `ath_drawdown` / `momentum_12_1` / `vol_target_scale` / `aggregate_curve` / `class_board` / `flow_graph` / `lights` + `run_capability(id, **kw)` 调度 |
| `contracts/capability_result.schema.json` | JSON Schema（测试用 `jsonschema` 逐条校验输出） |

48 个出口为：D-A01、D-A02、D-A03、D-A04、D-A06、D-A07、D-A08、D-A09、D-A10、D-A11、D-A12、D-A13、D-A14、D-A15、D-A16、D-B08、D-B09、D-E01～D-E12（不含场景包 D-E13）、D-E14、D-E15、D-E16、D-E17、D-E18、D-E19、D-G08、D-G09、D-G14、D-G16、D-G19、D-G20、D-G22、D-G23、D-J02、D-J04、D-J22、D-J24、D-J30。D-G09 新接波动率目标换算出口：价格先转日简单收益（数据整形），由 P02 计算窗口内实现年化波动与 `scale = target_vol / realized_vol`（target_vol 默认 0.10、window 默认 20、periods 默认 365），能力层不重算波动；收益样本 <60、`target_vol≤0` 或非数值、`window<2`、`periods<1`、日期长度不一致或含非有限值为空；`window` 超过收益长度时截断并降级 `window_truncated`，实现波动为 0 时降级 `zero_volatility` 且系数记 0.0；系数仅描述样本内目标/实现波动之比，不构成交易建议。D-G08 新接 12-1 动量出口：按「跳过最近 `skip` 期（默认 21）、回溯 `lookback` 期（默认 252）」切片后由 F14 真实执行动量/波动/风险调整动量（能力层只做窗口切片与百分比换算），输出 `momentum_12_1/lookback/skip/vol/risk_adjusted/window_start_ts/window_end_ts/truncated/sample_n`；价格样本 <60、`lookback<2`、`skip<0`、非整数参数、日期长度不一致或含非有限值为空；历史不足 `lookback+skip+1` 时截断 lookback 并降级 `short_history`，窗口起点非正降级 `base_zero`。D-B09 新接距 ATH 回撤出口：复用 D-E10 的 `drawdown` 执行器（D20 回撤画像 + D21 持续期），能力层只做 max/索引取点与别名映射，输出 TD 约定的 `drawdown_from_ath/ath/ath_ts`（分别等于 `current_drawdown/peak_price/peak_ts`）并保留 `mdd/duration_days/recovery_days`；价格样本 <2 或全无效值为空，样本 <250 降级 `insufficient_samples`。D-B08 新接趋势斜率出口：取最近 `window` 期（默认 90，下限 30）由 T08 计算对数价格 OLS 斜率与 R²、T09 计算名义 t/p，输出 `slope/r2/window/t/p/hac_corrected/sample_n`，显式标注 `hac_corrected=false`，t/p 只用于相对比较；样本 <60 降级 `short_window` 但保留结果，样本 <30 或 `window<30` 为 empty。D-A16 新接稳定币规模增速出口：S16 逐窗口真实执行 `x_t/x_{t-w}-1` 并折算百分比，能力层只组装多窗口结果，输出 `growth_{k}d/windows/sample_n`；`windows` 可配（默认 7/30），有效样本 <30 降级 `insufficient_samples` 但保留结果，窗口超出历史降级 `short_history`，基期为 0 降级 `base_zero` 并将该窗口置 None，全部窗口不可算 FAIL-OPEN 为 empty。D-A15 新接净流入滚动和出口：S20 真实执行滚动均值，能力层以「均值 × 窗口长度」算术还原滚动和，不做任何分布估计；`windows` 可配（默认 7/30，输出 `sum_{k}d`），有效样本 <30 降级 `insufficient_samples` 但保留结果，窗口超出历史长度降级 `short_history` 并将该窗口置 None，全部窗口不可算 FAIL-OPEN 为 empty。D-A13 新接极端事件频率出口：未给 `threshold` 时由 S11 分位（`quantile` 默认 0.95，取 pN）给出阈值，计数为纯聚合不引入额外估计量，输出 `days/ratio/threshold/side/quantile/sample_n`；样本 <30 且未提供阈值时阈值不可确定为空，提供阈值时 <30 降级 `insufficient_samples` 但保留计数；`side` 支持 above/below/abs。D-A12 新接领先滞后相关出口：paired complete-case 后由 M11 输出 lag −max_lag…+max_lag（默认 10）的相关/p/BH-FDR q/显著性，M12 输出最优 lag，能力层组装 `corr_by_lag[]` 与 `best_lag/best_corr/best_p_adj`；有效配对 <120 降级 `insufficient_history` 但保留结果，配对 <2、`max_lag<1` 或超过配对样本、日期长度不一致为 empty；结论不自动等于因果或未来可预测。D-A11 新接双序列滚动相关出口：按原始位置 paired complete-case 后由 M04 计算滚动 Pearson 相关（`window` 默认 30），输出 `corr`（最近窗口）/`mean_r`/`window`/`n_windows`/`sample_n`；有效配对 <60 降级 `insufficient_samples` 但保留结果，配对 <2、`window<2` 或超过配对样本、日期长度不一致为 empty。D-A10 新接实际利率出口：名义利率（如 DGS10）减 CPI 同比通胀，通胀唯一由 S16（`k=period`，默认 12）真实执行并折算为百分点，能力层只做差值组合，输出 `real_rate/nominal/inflation/base_ts/period/sample_n`；CPI 基期为 0 时通胀与实际利率均不可计算并降级 `inflation_unavailable`，历史 <2 个完整周期降级 `short_history`；样本不足以覆盖 period、`period<1`、双序列长度不一致、日期长度不一致或含非有限值为空。D-A09 新接环比出口：由 S16 以 `k=1` 计算 `x_t/x_{t-1}-1`，输出 `mom/base_ts/sample_n`；至少 2 个有效点，基期为 0 时 `mom=None` 并降级 `mom_unavailable`；样本 <2 为空。D-A08 新接同比出口：由 S16 计算 `x_t/x_{t-period}-1`（period 默认 12），输出 `yoy/base_ts/period/sample_n`；历史长度 <2×period+1 降级 `short_history`，基期为 0 时 `yoy=None` 并降级 `yoy_unavailable`；样本 ≤period 或 period<1 为空。D-A07 新接回撤出口：与 D-E10 共用 `drawdown` 执行器并由调度层注入 `capability_id`，D20/D21 真实执行，输出 TD 约定的 `drawdown/peak_ts` 并保留 `mdd/current_drawdown/duration_days/drawdown_path`；`prices<2` 为空，样本 <250 期降级 `insufficient_samples`。D-A06 新接年化波动率出口：取最近 `window` 期（缺省全样本）由 F05 计算日简单收益标准差 × √365，输出 `volatility/mean_ret/window/sample_n`；有效样本 <60 期降级 `short_window`，样本 <30 或 `window<30` 为空。D-A04 新接历史分位出口：取最近 `lookback` 期（缺省全样本）由 S25 计算末值经验分位，输出 `percentile/value/lookback/sample_n`；窗口 <60 期降级 `short_lookback`，`lookback` 超过可用历史时降级 `lookback_truncated` 并按可用样本计算；样本 <30 或 `lookback<30` 为空。D-A03 新接 CAGR 出口：首末值 + 年数（有日期轴按日历天数、否则按 n-1 天），跨度不足 1 年降级 `short_span`；起止值非正为空。D-A02 新接区间变化率出口：序列末值与 `window` 期前值比较，S15 输出绝对变化、S16 输出变化率；基期值为 0 时变化率不可用降级 `change_pct_unavailable` 并保留绝对变化。D-A01 新接单序列历史序列出口：日期轴必填且与数值等长，按 `freq` 取日/周/月区间最后观测（同日重复取最后）输出 `points[]/span/unit`，当前历史分位复用 S25；缺失率 >20% 降级 `sparse_series`。D-J30 新接 SC90 PIT 时间校验（`available ≤ used`，支持 ISO 与数值时间戳）与 R02 `pit=true` 前瞻分布：`release_ts`/`used_ts` 缺省视为观测时刻，PIT 违规降级 partial 并披露前视风险，过滤后可见样本不足 PIT 窗口时不产出前瞻分布。D-G14 新接 P07 EWMA 组合协方差（λ 默认 0.94）与 T19 逐资产 EWMA 波动序列：多资产面板按原始行 complete-case 后共享同一矩阵，单资产仅走 T19 且不输出协方差，风险结构只描述样本内统计。D-G16 新接 P09 参数法组合 VaR、P10 历史法组合 VaR/CVaR，并以 D17/D18 并列输出逐资产历史 VaR/CVaR；各资产收益按最小公共长度对齐，权重归一化与统计计算全部由方法层完成。D-G19 新接 B13/B14 与 Q01/Q02 的 IC/RankIC/ICIR、Q03 因子 IC 衰减，以及可选价格输入的 B15 价格动量重叠/非重叠 IC 衰减；Q03 收益轴通过首项补 0、右移已对齐 forward 防止多移一期，缺价格时保留核心五方法结果并显式降级。D-G20 新接 B16 分位组统计、B11 组均值严格单调性与 Q04 分位序号 Spearman 检验；factor/forward 按原始位置 complete-case 后共享同一样本轴，spread 仅作描述性统计而非策略收益。D-J02 新接 C13 月度季节强度、T10 robust STL 与 SC91 X-13 风格分解，原始组件与强度并列输出；日期轴必填，历史不足 3 年降级为描述性结论。D-J04 新接 T22/SC49 两种 CUSUM、T23 近似 PELT、SC50 精确 PELT 与 SC51 Pettitt，并列输出原始结果与断点日期映射；SC47 Kalman 与 SC48 互谱相干不属于本出口。D-G23 新接 Q10 均值调整 CAR 与 Q11 Patell/BMP，价格轴事件下标先转为同日收盘收益下标；事件数 <30 或标准化检验不可用时降级并保留 CAR。D-E14 新接一维相关状态条件分布：R02 PIT 桶标签由 B05/B10/R01/R08 共享，默认 h=1/2、4 桶，主期限不足降 2 桶，弱后续期限单独降级；h>1 不输出朴素 t/p。D-J22 新接 M19 相关阵 PCA、M20 载荷、SC31 sklearn PCA、SC32 SVD 与 SC33 因子分析；多变量面板按原始行 complete-case 后共享同一数据矩阵，仅描述数据结构、不生成交易方向。D-J24 新接 M05 相关矩阵、M21 相关距离层次聚类与 SC71/SC72 网络中心性/社区发现：|ρ|≥threshold 生成无向邻接，图规模低于方法门禁时降级披露，仅描述同期相关关系。其余出口沿用既有门禁与降级口径；二维 D-E14 仍未接线，各出口实际结论均受样本门禁约束。

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
| D-G08 | 固定公式因子（12-1 动量、20 日 ts_rank） | D1 | P1 | ✅ 已接线（`capabilities/stats.py::momentum_12_1`）：F14 在「跳过最近 skip 期、回溯 lookback 期」切片上真实执行动量/波动/风险调整动量，输出 `momentum_12_1/lookback/skip/vol/risk_adjusted/sample_n`；min_n=60，历史不足时截断 lookback 并降级 `short_history`；20 日 ts_rank 属 D-G07 序列算子族，未随本能力接线 |
| D-G09 | 波动率目标换算 | D1 | P1 | ✅ 已接线（`capabilities/stats.py::vol_target_scale`）：价格先转日简单收益（数据整形），由 P02 计算窗口实现年化波动与 `scale = target_vol / realized_vol`；target_vol 默认 0.10、window 默认 20、periods 默认 365；收益样本 <60 为空，window 超长截断降级 `window_truncated`，实现波动为 0 降级 `zero_volatility`；系数仅为样本内比值，不构成交易建议 |
| D-G10 | 逆波动权重 | D1 | P2 | ⬜ |
| D-G11 | 等风险贡献权重 | D3 | P3 | ⬜ |
| D-G12 | 风险贡献分解 | D1 | P3 | ⬜ |
| D-G13 | 协方差收缩（Ledoit-Wolf） | D3 | P3 | ⬜ |
| D-G14 | EWMA 波动/协方差（λ=0.94/0.97） | D1 | P1 | ✅ 已接线（`capabilities/stats.py::ewma_risk`）：P07 EWMA 组合协方差（λ 默认 0.94、init_window 20、年化 365）+ T19 逐资产 EWMA 波动序列并列输出；多资产面板按原始行 complete-case，单资产仅走 T19 且不输出协方差；min_n=60，仅描述样本内风险结构 |
| D-G15 | PCA 风险分解 | D3 | P3 | ⬜ |
| D-G16 | 组合 VaR / CVaR | D1 | P2 | ✅ 已接线（`capabilities/stats.py::portfolio_risk`）：P09 参数法组合 VaR + P10 历史法组合 VaR/CVaR，D17/D18 并列输出逐资产历史 VaR/CVaR；min_n=60，按最小公共长度对齐，损失正数口径 |
| D-G17 | 水下曲线 / 回撤画像 | D1 | P1 | ✅ D20/D21/F09/F10/R11 已实现，并经 D-E10 接线（`capabilities/stats.py::drawdown`） |
| D-G18 | Brinson 归因 | D1 | P3 | ⬜ |
| D-G19 | IC / ICIR / 衰减表 | D2 | P2 | ✅ 已接线（`capabilities/stats.py::ic_profile`）：B13/B14 + Q01/Q02 输出 IC/RankIC/ICIR，Q03 输出因子 IC 衰减，可选 prices 执行 B15 价格动量衰减；min_n=250，Q03 收益轴右移防错配，缺价格降级保留核心结果 |
| D-G20 | 分位单调性检验 | D2 | P2 | ✅ 已接线（`capabilities/stats.py::quantile_monotonic`）：B16 输出各分位组统计与最高减最低 spread，B11 检验组均值严格单调，Q04 输出分位序号与组均值 Spearman rho/p；min_n=250，complete-case 对齐，spread 仅为描述性统计 |
| D-G21 | Fama-MacBeth 横截面回归 | D3 | P3 | ⬜ |
| D-G22 | Deflated Sharpe / Newey-West t | D2 | P3 | ✅ |
| D-G23 | 事件窗 CAR + Patell/BMP | D2 | P2 | ✅ 已接线（2026-11-15，`capabilities/stats.py::event_car_significance`）：Q10 均值调整 CAR + Q11 Patell/BMP；价格轴事件下标转为同日收盘收益下标；事件数 <30 或 Q11 不可用时降级 partial，保留 Q10 CAR |
| D-G24 | 因子拥挤度 | D2 | P3 | ⬜ |
| D-G25 | 尾部相关 | D2 | P2 | ⬜ |

**分层关系**：A/B/C = 数据维度能力；E = 关系表达；**G = 机构统计方法补强**。G 组不改变 L1 定性——仍只输出历史统计与样本量。

### 2.6 J 组：科研统计方法（30 项，调研见 RESEARCH-SCIENTIFIC-METHODS.md）

> 来源：NIST/SEMATECH、CERN/ROOT、US Census X-13、NOAA/NASA、NIH/FDA、OECD、Santa Fe、JHU/WHO 等公开方法。面向「数据化科研」通用场景，不限于金融。

| ID | 能力 | 分级 | 优先级 | 状态 |
|---|---|---|---|---|
| D-J01 | 趋势检验（Mann-Kendall + Sen） | D2 | P2 | ⬜ |
| D-J02 | 季节强度与调整（STL/X-13 风格） | D2 | P2 | ✅ 已接线（`capabilities/stats.py::seasonal_adjustment`）：C13/T10/SC91 原始结果与季节强度并列输出，min_n=60、min_span_days=1095；不足 3 年保留结果并降级 |
| D-J03 | 异常点识别（AO/LS/TC） | D1 | P2 | ⬜ |
| D-J04 | 变点检测（CUSUM/PELT/Pettitt） | D2 | P2 | ✅ 已接线（`capabilities/stats.py::change_point`）：T22/SC49 CUSUM、T23 近似 PELT、SC50 精确 PELT、SC51 Pettitt，min_n=60；SC47/SC48 不属于本能力 |
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
| D-J22 | PCA/SVD/因子分析 | D3 | P2 | ✅ 已接线（`capabilities/stats.py::dimension_reduction`）：M19/M20/SC31/SC32/SC33 并列，面板 complete-case 共享同一数据矩阵，min_n=60；仅描述数据结构 |
| D-J23 | 聚类与轮廓系数 | D3 | P3 | ⬜ |
| D-J24 | 相关网络与社区发现 | D3 | P3 | ✅ 已接线（`capabilities/stats.py::correlation_network`）：M05 相关矩阵按 |ρ|≥threshold 生成邻接，SC71 度/介数/接近中心性，SC72 Louvain 社区与模块度，M21 相关距离层次聚类；min_n=60、≥2 变量，图规模低于方法门禁时降级为描述 |
| D-J25 | 空间自相关/变异函数 | D2 | P3 | ⬜ |
| D-J26 | 生存分析（KM/log-rank/Cox） | D3 | P3 | ⬜ |
| D-J27 | 可靠性/控制图（X̄-R/EWMA/CUSUM） | D1 | P3 | ⬜ |
| D-J28 | Meta 分析与异质性 | D3 | P3 | ⬜ |
| D-J29 | 缺失机制与插补 | D3 | P2 | ⬜ |
| D-J30 | 质量校验（重复/一致性/PIT） | D1 | P1 | ✅ |

**分层关系**：A/B/C = 数据维度；E = 关系表达；G = 机构方法；**J = 科研统计（通用化）**。J 组使 L1 可用于运营、实验、传感器、气候、医学等任意时序数据场景。

### 2.7 K 组：关系评估与发现（2 项，系统级）

> **归属第④层（评估层）出口**：`D-K01/D-K02` 不是新的统计能力，而是 MERS（SPEC §14）与 Discovery（§15）预计算产物的**只读查询出口**，只做「按评分排序/按条件筛选」，不重算任何方法（见 §0.5.3 纪律 2）。
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
| `datacenter.series` | ✅ 已上线（S0） | D-A01/02/03/06/08/09/13/15/16 | 19 DAL `query_metric_by_time` |
| `datacenter.percentile` | ⬜ 新增 | D-A04/05/07/14 | 同上（服务端统计） |
| `datacenter.correlation` | ⬜ 新增 | D-A11/12 | 同上（双序列对齐） |
| `market.candles` | ✅ 已落地（S1，1D/1W/1M 日频派生 + 1H OHLC + 日线 OHLC 合并） | D-B00–B09 | `mm_metrics` 日频/小时级（`{symbol}/USDT` high/low） |
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
| 最小样本 | `sample_n ≥ 30` 仅是通用统计下限，**专用门禁优先**；不足 → `status=partial` + `degraded_reason=insufficient_samples`，统计字段 `null` |
| 专用样本门禁 | 同期相关 ≥60 对齐点；CCF ≥120；条件统计/IC ≥250；T0.5/T2 按**每桶非重叠 n≥250**，不得以重叠样本凑数。T0.5 首版仅 h=1，h≥5 与多维状态等待 T-1 扩样本 |
| PIT 与披露 | R02 已实现双口径：`pit=false` 只能标为样本内回顾，不得进入 T0.5/T2/MERS；`pit=true`（逐时点滚动分位 + `release_ts≤as_of`）是唯一合法口径。方法层输出已含 `pit/as_of/window/align_method`，能力层接线时补 `effective_n/nonoverlap_n` |
| 统计推断 | h>1 的重叠前瞻收益及趋势显著性推断前必须经 D-G22 出口（Q06 HAC t / Q07 DSR），不允许用朴素 t 值；批量关系扫描按「关系对 × lag × window × h」完整搜索族校正并披露 `p_adj` |
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

## §6 与 SPEC 的关系、版本变更与整体进度

- 本文 = **总技术文档 + 能力登记册**（§0 问题域地图/数据可行性/治理规则；§2 能力 ID/依赖/字段/优先级/状态；本节汇总变更与规划进度）。
- [METHOD_LIBRARY.md](./METHOD_LIBRARY.md) = 算法**选择表与口径 SSoT**（238 方法、18 关系原语、意图→方法路由、输出模板、§16 口径冻结、§15 数据前提）。
- [SPEC-54](../SPEC-54-L1架构能力聚合层.md) = 架构与**契约**（scope 入参出参、门禁、验收、落地计划）。
- 场景包 SPEC = 某类问题的**固定编排**（当前已交付延续性画像 `D-E13`、T0.5 与 D-E14/T2 一维首版；二维 T2 仍待样本与状态特征）。
- 新增能力流程：本文登记 → SPEC 补契约（如涉及新 scope）→ 实现 + 测试 → 更新状态列并附代码位置。

### 6.1 本版更改（v2.48 L1 交易层 D-E15～D-E19；v2.47 前端 D-A/D-B/D-G cue 分派；v2.46 D-G09 波动率目标换算；v2.45 D-G08 12-1 动量；v2.44 D-B09 距 ATH 回撤；v2.43 D-B08 趋势斜率；v2.42 D-A16 稳定币增速；v2.41 D-A15 ETF 净流入滚动和；v2.40 D-A13 极端事件频率；v2.39 D-A12 领先滞后相关；v2.38 D-A11 双序列滚动相关；v2.37 D-A10 实际利率；v2.36 D-A09 环比；v2.35 D-A08 同比；v2.34 D-A07 回撤；v2.33 D-A06 年化波动率；v2.32 D-A04 历史分位；v2.31 D-A03 CAGR；v2.30 D-A02 变化率；v2.29 D-A01 历史序列；v2.28 D-J30 PIT/release_ts 全局能力；v2.27 D-G14 EWMA 波动/协方差；v2.26 D-J24 相关网络与社区发现；v2.25 D-J22 PCA/SVD/因子分析；v2.24 D-G20 分位组合与单调性检验；v2.23 D-G19 IC/ICIR/衰减表；v2.22 D-G16 组合 VaR/CVaR；v2.21 D-J02 季节强度与调整；v2.20 D-J04 变点检测；v2.19 D-E07/B06 联合计数；v2.18 D-G23 事件窗 CAR + Patell/BMP；v2.17 D-E14 一维条件分布；v2.16 D-E04/D-E09 事件与计数出口；v2.15 D-A14/F26 A 分位法 level；v2.14 D-G22 显著性出口；v2.13 事件历史回填通道；v2.12 D-E12/R18；v2.11 C18/D-E01/MERS；v2.10 配对/推断/执行覆盖；v2.9 D-E02 接线与 T0.5 交付；v2.8 方法层全部落地）

**v2.48（本版，L1 交易层 D-E15～D-E19 能力登记）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-E15–D-E19 能力出口 | `capabilities/stats.py::{trend, aggregate_curve, class_board, flow_graph, lights}`、`capability_manifest.yaml`、[SPEC-54-L1交易层.md](../SPEC-54-L1交易层.md) | D-E15 趋势曲线（`technical_indicator`，min_n=250）：I02/T08/I32 多窗口斜率 + ADX14，可选 I37 Kalman；D-E16 聚合曲线（`metric_series`，min_n=60）：成员按首日 rebase 后按 `chart_weights` 加权，缺口不 ffill，逐点披露 `coverage_ratio/partial_members`；D-E17 分组看板（`cross_check`，min_n=60）：`ret_60` 与 D-E12 同口径，`lit_n/warm_n` 直接读 D-E19 计数（零重算）；D-E18 资金流向（`data_insight`，min_n=60）：M01/M02 建边，无 flow 数据降级 corr-only 且绝不伪造边；D-E19 点亮投影（`trend_query`，min_n=500）：轴强度 = 轴值/轴权重零重算，`lit/warm` 默认 p70/p40，未标定显式打标；可执行出口 44→48 |
| 交易层配置与积木 | `config/{asset_pool, chart_weights, weights, baseline_methods, method_rank, direction_rule}.yaml`、`l1agg/trading/**` | 资产池、图表权重、轴权重、基线方法、方法排名与方向规则全部配置化，阈值不硬编码；`l1agg/trading` 提供 batch / cluster / comparison / exit_rule / outbox / paper_replay / risk / rule_inputs / sizing / store / weight_switch，回放与实盘共用同一存储与幂等契约 |
| 验证 | `tests/test_{lights, aggregate, flow_graph, chart_weights, weights, fed_methods, batch_replay, ...}.py` | 54-L1 全量 `pytest tests -q` 全绿（不计并行开发中的 calibrate_light）；`ruff check` / `ruff format` 通过 |

**v2.47（前端 D-A/D-B/D-G cue 分派）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| 前端专用 cue 与分派 | `3.1-FRONTEND/scripts/l1_route_signal.py`、`data_query_executor.py::exec_stat_query`、`src/lib/l1-intent-registry.ts` | 新增 D-A01/D-A02/D-A03/D-A04/D-A06/D-A07/D-A08/D-A09/D-A10/D-A11/D-A12/D-A13/D-A15/D-A16 与 D-B08/D-B09/D-G08/D-G09 共 **18 个能力分派**；专用 cue 先于宽词，避免 ATH→普通回撤、历史分位→前瞻分位、12-1 动量→因子 IC 等截胡；不新增能力出口，仍为 44 个 |
| 取数与对齐契约 | 同上 | 指标经 `resolve_metric → datacenter.series`，值/日期成对过滤并沿用 sign/scale；同比/环比取月频 1825 天；实际利率将 DGS10 与 CPIAUCSL 月频序列按 `YYYY-MM` 对齐；滚动相关/领先滞后在双资产分派中复用共同交易日与统一收盘锚点；D-B09 取 1825 天，其余价格能力取 730 天；缺指标、缺序列、缺第二标的均显式 degraded |
| 验证与金标 | `34-前端应用训练系统/tests/test_l1_route_signal.py`、`l1_intent_golden.jsonl`、§6.4 #39/#40 | 新增 18 条 stat_query 金标；Python 路由/分派 **78 passed**，TypeScript 注册表 **19 passed**；覆盖 capability ID、kwargs、月份对齐、双资产 89 个同步收益及缺失数据 FAIL-OPEN；ruff、ruff format、Prettier 全通过；#39/#40 标记完成（未提交，未操作云端） |

**v2.46（D-G09 波动率目标换算）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-G09 能力出口 | `capabilities/stats.py::vol_target_scale`、`capability_manifest.yaml` | 复用 `metric_derived`（deterministic，`min_n=60`，data_scope `market.candles`）：价格转日简单收益（数据整形）后由 P02 计算窗口实现年化波动与 `scale = target_vol / realized_vol`；可执行出口 43→44 |
| 输入与结果契约 | 同上 | `prices` 必填；`target_vol` 默认 0.10、`window` 默认 20、`periods` 默认 365；输出 `scale/target_vol/realized_vol/window/periods/returns_n/sample_n`；收益 <60、`target_vol≤0`、`window<2`、`periods<1`、日期长度不一致、含非有限值为空；`window` 超长截断降级 `window_truncated`，实现波动为 0 降级 `zero_volatility` |
| 方法层契约坑 | 同上 | P02 为面板方法，必须传**扁平** `{sym: returns}`；传 `{"returns": {...}}` 会让 `_sample_n` 计为 1 而被门禁挡成 insufficient_samples |
| 验证与清单 | 54-L1 全量、§6.4 #30 | 新增 4 例（完整信封 / 与 P02 逐项相等 / 零波动与窗口截断双降级 / 6 类非法输入 FAIL-OPEN），纳入 4 处白名单；`pytest tests --ignore=tests/test_paper_replay.py` → **1060 passed / 0 failed**；本次修改文件 ruff 通过；#30 标记完成（未提交） |

**v2.45（D-G08 12-1 动量）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-G08 能力出口 | `capabilities/stats.py::momentum_12_1`、`capability_manifest.yaml` | 复用 `metric_derived`（deterministic，`min_n=60`，data_scope `market.candles`）：按「跳过最近 `skip` 期（默认 21）、回溯 `lookback` 期（默认 252）」切片后由 F14 真实执行，能力层只做窗口切片与百分比换算；可执行出口 42→43 |
| 输入与结果契约 | 同上 | `prices` 必填；输出 `momentum_12_1/lookback/skip/vol/risk_adjusted/window_start_ts/window_end_ts/truncated/sample_n`；历史不足 `lookback+skip+1` 时截断 lookback 并降级 `short_history`，窗口起点非正降级 `base_zero` |
| 降级与执行覆盖 | `tests/test_capabilities.py` | 新增 4 例：280 点完整信封（窗口 253 点、起点/终点日期对齐）、与 F14 逐项相等、120 点降级 `short_history`（lookback 截断为 98）、样本 <60 / lookback<2 / skip<0 / 非整数参数 / 日期长度不一致 / 含 None FAIL-OPEN；纳入 ID 集合、executor 白名单、JSON Schema 与 manifest 真实执行覆盖 |
| 验证与清单 | 54-L1 全量、§6.4 #29 | `pytest tests --ignore=tests/test_paper_replay.py` → **1056 passed / 0 failed**；本次修改文件 ruff check / ruff format 通过；#29 标记完成（未提交） |

**v2.44（D-B09 距 ATH 回撤）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-B09 能力出口 | `capabilities/stats.py::ath_drawdown`、`capability_manifest.yaml` | 复用 D-E10 `drawdown` 执行器（`technical_indicator`，`min_n=250`，data_scope `market.candles`）：D20/D21 真实执行，能力层只做 max/索引取点与别名映射，输出 `drawdown_from_ath/ath/ath_ts`（= `current_drawdown/peak_price/peak_ts`）；可执行出口 41→42 |
| 降级与执行覆盖 | `tests/test_capabilities.py` | 新增 4 例：300 点完整信封（ATH=398、`ath_ts` 对齐峰值日、回撤 0.623116）、与 D20/D21 逐项相等、30 点降级 `insufficient_samples` 但保留结果、单点/空序列/全 None FAIL-OPEN 且日期长度不足时 `ath_ts=None` 不崩溃；纳入 JSON Schema 与 manifest 真实执行覆盖 |
| 验证与清单 | 54-L1 全量、§6.4 #28 | `pytest tests --ignore=tests/test_paper_replay.py` → **993 passed / 0 failed**（能力模块 169 passed）；本次修改文件 ruff check / ruff format 通过；#28 标记完成（未提交） |

**v2.43（D-B08 趋势斜率）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-B08 能力出口 | `capabilities/stats.py::slope_trend`、`capability_manifest.yaml` | 新增 `technical_indicator`（deterministic，`min_n=60`）：T08 输出对数价格 OLS 斜率与 R²，T09 输出名义 t/p；`window` 默认 90、下限 30；可执行出口 40→41 |
| 输入与结果契约 | 同上 | `prices` 必填；输出 `slope/r2/window/t/p/hac_corrected/sample_n`；显式 `hac_corrected=false`，answer 声明「名义 t 未做 HAC 修正，仅作相对比较」 |
| 降级与执行覆盖 | `tests/test_capabilities.py` | 新增 4 例：120 点完整信封（窗口截取 90 点、slope≈0.002、r2=1）、与 T08/T09 逐项相等、45 点降级 `short_window` 但保留结果、样本 <30 / window<30 / 非整数 window / 日期长度不一致 / 含 None FAIL-OPEN；纳入 JSON Schema 与 manifest 真实执行覆盖 |
| 验证与清单 | 54-L1 全量、§6.4 #27 | `pytest tests --ignore=tests/test_paper_replay.py` → **989 passed / 0 failed**（能力模块 165 passed）；本次修改文件 ruff check / ruff format 通过；#27 标记完成（未提交） |

**v2.42（D-A16 稳定币增速）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-A16 能力出口 | `capabilities/stats.py::stablecoin_growth`、`capability_manifest.yaml` | 复用 `metric_series`（deterministic，`min_n=30`）：S16 逐窗口真实执行 `x_t/x_{t-w}-1` 并折算百分比，能力层只组装多窗口；`windows` 可配（默认 7/30）；可执行出口 39→40 |
| 输入与结果契约 | 同上 | `values` 为稳定币规模序列；输出 `growth_{k}d/windows/sample_n`；`dates` 可选但给定时须等长可解析 |
| 降级与执行覆盖 | `tests/test_capabilities.py` | 新增 4 例：40 点完整信封（与 S16 逐项相等）、自定义窗口一致、20 点降级 `insufficient_samples` / 10 点 30d 窗口降级 `short_history` / 基期 0 降级 `base_zero` 且该窗口 None、样本不足以覆盖任何窗口/window=0/非整数/空 windows/日期长度不一致/含 None FAIL-OPEN；纳入 JSON Schema 与 manifest 真实执行覆盖 |
| 验证与清单 | 54-L1 全量、§6.4 #26 | `pytest tests --ignore=tests/test_paper_replay.py` → **985 passed / 0 failed**（73 个能力相关测试通过）；本次修改文件 ruff check / ruff format 通过；#26 标记完成（未提交） |

**v2.41（D-A15 ETF 净流入滚动和）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-A15 能力出口 | `capabilities/stats.py::etf_flow_rolling`、`capability_manifest.yaml` | 复用 `metric_series`（deterministic，`min_n=30`）：S20 真实执行滚动均值，能力层以「均值 × 窗口长度」算术还原滚动和，不重算分布；`windows` 可配（默认 7/30）；可执行出口 38→39 |
| 输入与结果契约 | 同上 | `values` 必填；输出 `sum_{k}d/windows/sample_n`；`dates` 可选但给定时须等长可解析；货币单位仅用于 answer 展示 |
| 降级与执行覆盖 | `tests/test_capabilities.py` | 新增 4 例：40 点完整信封（`sum_7d/sum_30d` 等于末窗和）、与 S20 逐项相等（自定义窗口）、20 点降级 `insufficient_samples` / 10 点 30d 窗口降级 `short_history` 且该窗口 None、样本不足以覆盖任何窗口/window=0/非整数 window/空 windows/日期长度不一致/含 None FAIL-OPEN；纳入 JSON Schema 与 manifest 真实执行覆盖 |
| 验证与清单 | 54-L1 全量、§6.4 #25 | `pytest tests --ignore=tests/test_paper_replay.py` → **969 passed / 0 failed**（能力模块 157 passed）；本次修改文件 ruff check / ruff format 通过；#25 标记完成（未提交） |

**v2.40（D-A13 极端事件频率）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-A13 能力出口 | `capabilities/stats.py::extreme_frequency`、`capability_manifest.yaml` | 复用 `metric_series`（deterministic，`min_n=30`）：未给 `threshold` 时由 S11 分位（`quantile` 默认 0.95）给出阈值，计数为纯聚合；`side` 支持 above/below/abs；可执行出口 37→38 |
| 输入与结果契约 | 同上 | `values` 必填；输出 `days/ratio/threshold/side/quantile/sample_n`；`dates` 可选但给定时须等长可解析；阈值来源在 answer 中显式披露 |
| 降级与执行覆盖 | `tests/test_capabilities.py` | 新增 4 例：100 点完整信封（阈值与 days 均与 S11 一致）、quantile=0.9 复用 S11、20 点显式阈值降级 `insufficient_samples` 保留计数 / 20 点无阈值 empty、样本 <2/side 非法/NaN 阈值/quantile 越界/日期长度不一致/含 None FAIL-OPEN；纳入 JSON Schema 与 manifest 真实执行覆盖 |
| 验证与清单 | 54-L1 全量、§6.4 #24 | `pytest tests --ignore=tests/test_paper_replay.py` → **965 passed / 0 failed**（能力模块 153 passed）；本次修改文件 ruff check / ruff format 通过；#24 标记完成（未提交） |

**v2.39（D-A12 领先滞后相关）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-A12 能力出口 | `capabilities/stats.py::lead_lag_correlation`、`capability_manifest.yaml` | 新增 `correlation_query`（deterministic，`min_n=120`）：paired complete-case 后由 M11 输出 lag −max_lag…+max_lag（默认 10）的相关/p/BH-FDR q/显著性，M12 输出最优 lag；可执行出口 36→37 |
| 输入与结果契约 | 同上 | `x`/`y` 必填，`dates` 可选但给定时须与原序列等长可解析；输出 `best_lag/best_corr/best_p_adj/corr_by_lag[]/max_lag/sample_n`，`align_method=paired_complete_case` |
| 降级与执行覆盖 | `tests/test_capabilities.py` | 新增 4 例：150 点完整信封（21 个 lag、`best_corr==1.0`）、与 M11/M12 逐项相等、100 点降级 `insufficient_history` 但保留结果、配对 <2/`max_lag<1`/max_lag 超配对样本/日期长度不一致/全无效值 FAIL-OPEN；纳入 JSON Schema 与 manifest 真实执行覆盖 |
| 验证与清单 | 54-L1 全量、§6.4 #23 | `pytest tests --ignore=tests/test_paper_replay.py` → **961 passed / 0 failed**（能力模块 149 passed）；本次修改文件 ruff check / ruff format 通过；#23 标记完成（未提交） |

**v2.38（D-A11 双序列滚动相关）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-A11 能力出口 | `capabilities/stats.py::rolling_correlation`、`capability_manifest.yaml` | 新增 `correlation_query`（deterministic，`min_n=60`）：按原始位置 paired complete-case 后由 M04 计算滚动 Pearson 相关（`window` 默认 30）；可执行出口 35→36 |
| 输入与结果契约 | 同上 | `x`/`y` 必填，`dates` 可选但给定时须与原序列等长可解析（配对后同步过滤）；输出 `corr`（最近窗口）/`mean_r`/`window`/`n_windows`/`sample_n`，`align_method=paired_complete_case` |
| 降级与执行覆盖 | `tests/test_capabilities.py` | 新增 4 例：90 点完整信封（`corr==1.0`、`n_windows==61`）、与方法层 M04 逐项相等、40 点降级 `insufficient_samples` 但保留结果、配对 <2/`window<2`/window 超过配对样本/日期长度不一致/全无效值 FAIL-OPEN；纳入 JSON Schema 与 manifest 真实执行覆盖（M04 在降级分支走 `_call_soft`，仍为同一方法实现） |
| 验证与清单 | 54-L1 全量、§6.4 #22 | `pytest tests --ignore=tests/test_paper_replay.py` → **957 passed / 0 failed**（能力模块 145 passed）；本次修改文件 ruff check / ruff format 通过；#22 标记完成（未提交） |

**v2.37（D-A10 实际利率）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-A10 能力出口 | `capabilities/stats.py::real_rate`、`capability_manifest.yaml` | 新增 `metric_derived`（deterministic，`min_n=13`）：通胀唯一由 S16（`k=period`，默认 12）真实执行并折算百分点，能力层只做 `名义 − 通胀` 差值组合；可执行出口 34→35 |
| 输入与结果契约 | 同上 | `nominal`/`cpi` 必填且等长；输出 `real_rate/nominal/inflation/base_ts/period/sample_n`，`dates` 可选但给定时须等长可解析；`span` 取通胀基期→最新 |
| 降级与执行覆盖 | `tests/test_capabilities.py` | 新增 4 例：36 期完整信封（`real_rate==nominal−inflation`、`base_ts=dates[-13]`、`align_method=period_offset`）、与方法层 S16 逐项相等、18 期降级 `short_history` + 基期 0 降级 `inflation_unavailable`、样本不足以覆盖 period/`period=0`/双序列长度不一致/日期长度不一致/含 None FAIL-OPEN；纳入 JSON Schema 与 manifest 真实执行覆盖 |
| 验证与清单 | 54-L1 全量、§6.4 #21 | `pytest tests --ignore=tests/test_paper_replay.py` → **953 passed / 0 failed**（能力模块 141 passed）；本次修改文件 ruff check / ruff format 通过；#21 标记完成（未提交） |

**v2.36（D-A09 环比）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-A09 能力出口 | `capabilities/stats.py::mom_change`、`capability_manifest.yaml` | 复用 `metric_series`（deterministic，`min_n=2`）：S16 以固定 `k=1` 计算 `x_t/x_{t-1}-1`；可执行出口 33→34 |
| 输入与结果契约 | 同上 | `values` 必填；输出 `mom/base_ts/sample_n`；`dates` 可选但给定时须等长可解析（`base_ts` 取上一期日期、`span` 取上一期→最新） |
| 降级与执行覆盖 | `tests/test_capabilities.py` | 新增 4 例：36 期完整信封（`mom==round(v[-1]/v[-2]-1,6)`、`base_ts=dates[-2]`、`align_method=period_offset`）、与方法层 S16（k=1）逐项相等、基期 0 降级 `mom_unavailable`、样本 <2/日期长度不一致/含 None FAIL-OPEN；纳入 JSON Schema 与 manifest 真实执行覆盖 |
| 验证与清单 | 54-L1 全量、§6.4 #20 | `pytest tests --ignore=tests/test_paper_replay.py` → **949 passed / 0 failed**（能力模块 137 passed）；本次修改文件 ruff check / ruff format 通过；#20 标记完成（未提交） |

**v2.35（D-A08 同比）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-A08 能力出口 | `capabilities/stats.py::yoy_change`、`capability_manifest.yaml` | 复用 `metric_series`（deterministic，`min_n=13`）：S16 计算 `x_t/x_{t-period}-1`（`period` 默认 12）；可执行出口 32→33 |
| 输入与结果契约 | 同上 | `values` 必填；输出 `yoy/base_ts/period/sample_n`，`dates` 可选但给定时须等长可解析（`base_ts` 取基期日期、`span` 取基期→最新）；样本 ≤period 或 `period<1` 直接 empty |
| 降级与执行覆盖 | `tests/test_capabilities.py` | 新增 4 例：36 期完整信封（`yoy==round(v[-1]/v[-13]-1,6)`、`base_ts=dates[-13]`、`align_method=period_offset`）、与方法层 S16 逐项相等、18 期降级 `short_history` + 基期 0 降级 `yoy_unavailable`、样本不足覆盖 period/`period=0`/日期长度不一致/含 None FAIL-OPEN；纳入 JSON Schema 与 manifest 真实执行覆盖 |
| 验证与清单 | 54-L1 能力相关全量、§6.4 #19 | `pytest tests --ignore=tests/test_paper_replay.py` → **945 passed / 0 failed**（能力模块 133 passed）；本次修改文件 ruff check / ruff format 通过；#19 标记完成（未提交） |

**v2.34（D-A07 回撤）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-A07 能力出口 | `capabilities/stats.py::drawdown`（参数化 `capability_id`/`intent`）、`capability_manifest.yaml` | 复用 `drawdown_query`（deterministic，`min_n=250`）：与 D-E10 共用执行器，调度层经 `_EXECUTOR_INTENTS` 注入 `capability_id=D-A07`，D20 最大回撤 + D21 持续/收复天数真实执行；可执行出口 31→32 |
| 输入与结果契约 | 同上 | `prices` 必填；输出 TD 约定的 `drawdown/peak_ts`，并保留 `mdd/current_drawdown/duration_days/drawdown_path` 等既有字段；`dates` 可选（缺失时 `peak_ts=None`）；`prices<2` 直接 empty |
| 降级与执行覆盖 | `tests/test_capabilities.py` | 新增 4 例：300 点完整信封（`drawdown==round(1-price_last/max,6)`、`peak_ts` 对齐高点日期）、与 D-E10 同输入逐项相等、100 点降级 `insufficient_samples`、1 点/空序列 FAIL-OPEN；纳入 JSON Schema 与 manifest 真实执行覆盖 |
| 验证与清单 | 54-L1 能力相关全量、§6.4 #18 | `pytest tests --ignore=tests/test_paper_replay.py` → **941 passed / 0 failed**（能力模块 129 passed）；本次修改文件 ruff check / ruff format 通过；#18 标记完成（未提交） |

**v2.33（D-A06 年化波动率）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-A06 能力出口 | `capabilities/stats.py::annualized_volatility`、`capability_manifest.yaml` | 复用 `metric_series`（deterministic，`min_n=30`）：F05 日简单收益标准差 × √365；可执行出口 30→31 |
| 输入与结果契约 | 同上 | `values` 必填；`window` 缺省取全样本、指定时须 ≥30；输出 `volatility/mean_ret/window/sample_n`；`dates` 可选但给定时须等长可解析；样本 <30、`window<30`、长度不一致或含无效值均直接 empty |
| 降级与执行覆盖 | `tests/test_capabilities.py` | 新增 4 例：120 期窗口完整信封（`align_method=trailing_sample`）、与方法层 F05 逐项相等、40 期窗口降级 `short_window`、29 点/`window=20`/日期长度不一致/含 None FAIL-OPEN；纳入 JSON Schema 与 manifest 真实执行覆盖 |
| 验证与清单 | 54-L1 能力相关全量、§6.4 #17 | `pytest tests --ignore=tests/test_paper_replay.py` → **937 passed / 0 failed**（能力模块 125 passed）；本次修改文件 ruff check / ruff format 通过；#17 标记完成（未提交） |

**v2.32（D-A04 历史分位）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-A04 能力出口 | `capabilities/stats.py::percentile_rank`、`capability_manifest.yaml` | 复用 `metric_percentile`（deterministic，`min_n=30`）：S25 经验分位（`100×count(X≤x_last)/n`，无未来函数）；可执行出口 29→30 |
| 输入与结果契约 | 同上 | `values` 必填；`lookback` 缺省取全样本、指定时须 ≥30；输出 `percentile/value/lookback/sample_n`；`dates` 可选但给定时须等长可解析；样本 <30、非法 lookback、长度不一致均直接 empty |
| 降级与执行覆盖 | `tests/test_capabilities.py` | 新增 4 例：60 期窗口完整信封（`align_method=trailing_sample`）、与方法层 S25 逐项相等、窗口 <60 降级 `short_lookback` + lookback 超历史降级 `lookback_truncated`、29 点/`lookback=10`/日期长度不一致/含 None FAIL-OPEN；纳入 JSON Schema 与 manifest 真实执行覆盖 |
| 验证与清单 | 54-L1 能力相关全量、§6.4 #16 | `pytest tests --ignore=tests/test_paper_replay.py` → **933 passed / 0 failed**（能力模块 121 passed）；本次修改文件 ruff check / ruff format 通过；#16 标记完成（未提交） |

**v2.31（D-A03 CAGR）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-A03 能力出口 | `capabilities/stats.py::cagr`、`capability_manifest.yaml` | 复用 `metric_series`（deterministic，`min_n=2`）：S19 输出 `cagr/years/n`；可执行出口 28→29 |
| 输入与结果契约 | 同上 | `values` 必填；`dates` 可选，给定时按首末日历天数折算年数，否则按 `n-1` 天；起止值非正、首末日期跨度非正直接 empty；跨度 <1 年降级 `short_span` 并提示年化仅供参考 |
| 降级与执行覆盖 | `tests/test_capabilities.py` | 新增 4 例：两年翻倍完整信封、与方法层 S19 逐项相等、跨度 <1 年降级、1 点/非正起止值/同日/日期长度不一致 FAIL-OPEN；纳入 JSON Schema 与 manifest 真实执行覆盖 |
| 验证与清单 | 54-L1 能力相关全量、§6.4 #15 | `pytest tests --ignore=tests/test_paper_replay.py` → **929 passed / 0 failed**；本次修改文件 ruff check / ruff format 通过、`git diff --check` 干净；#15 标记完成（未提交） |

**v2.30（D-A02 变化率）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-A02 能力出口 | `capabilities/stats.py::change_rate`、`capability_manifest.yaml` | 复用 `metric_series`（deterministic，`min_n=2`）：S15 绝对变化 + S16 变化率并列输出；可执行出口 27→28 |
| 输入与结果契约 | 同上 | `values` 必填，`window` 默认 1；`window<1` 或样本不足以覆盖区间直接 empty；`dates` 可选但给定时须等长可解析；基期值为 0 时 `change_pct=None`、降级 `change_pct_unavailable`，绝对变化照常输出 |
| 降级与执行覆盖 | `tests/test_capabilities.py` | 新增 4 例：区间变化完整信封、与方法层 S15/S16 逐项相等、基期 0 降级保留绝对变化、1 点/window 越界/window=0/NaN FAIL-OPEN；纳入 JSON Schema 与 manifest 真实执行覆盖 |
| 验证与清单 | 54-L1 能力相关全量、§6.4 #14 | `pytest tests --ignore=tests/test_paper_replay.py` → **925 passed / 0 failed**；本次修改文件 ruff check / ruff format 通过、`git diff --check` 干净；#14 标记完成（未提交） |

**v2.29（D-A01 历史序列）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-A01 能力出口 | `capabilities/stats.py::history_series`、`capability_manifest.yaml` | 复用 `metric_series`（deterministic，`min_n=30`）：单序列按日/周/月区间取最后观测，输出 `points[]/span/unit`，当前历史分位由 S25 真实执行；可执行出口 26→27 |
| 输入与结果契约 | 同上 | `values/dates` 必填且等长、日期轴必须可解析；`freq ∈ {daily,weekly,monthly}`（兼容 day/week/month 与首字母）；同日重复取最后观测；能力层只做区间取点与降采样，不重算分位 |
| 降级与执行覆盖 | `tests/test_capabilities.py` | 新增 4 例：日频完整信封与 S25 分位、周/月降采样与同日去重、缺失率 >20% 触发 `sparse_series`、29 点/长度不一致/非法 freq FAIL-OPEN；纳入 JSON Schema 与 manifest 真实执行覆盖 |
| 验证与清单 | 54-L1 能力相关全量、§6.4 #13 | `pytest tests --ignore=tests/test_paper_replay.py` → **920 passed / 0 failed**；`tests/test_paper_replay.py` 属并行开发中的未跟踪交易模块（`l1agg/trading/` 17:01 仍在改），失败与本次改动无关；本次修改文件 ruff check / ruff format 通过、`git diff --check` 干净；#13 标记完成（未提交） |

**v2.28（D-J30 PIT/release_ts 全局能力）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-J30 能力出口 | `capabilities/stats.py::pit_alignment`、`capability_manifest.yaml` | 复用 `metric_percentile`（deterministic，`min_n=250`）：SC90 校验每条样本「可用时间 ≤ 使用时间」+ R02 `pit=true` 逐时点滚动分位前瞻分布；可执行出口 25→26 |
| 输入与结果契约 | 同上 | `indicator/prices/dates` 必填且等长，`release_ts`（数据发布时刻）与 `used_ts`（使用时刻）可选、缺省视为观测时刻；并列输出 `pit_check`（pass/n_violations/max_lag）与 `r02`（当前分位、分桶、按期限前瞻分布）；能力层不重算统计量 |
| 降级与执行覆盖 | `tests/test_capabilities.py` | 新增 4 例：默认 PIT 通过完整信封、与方法层 SC90/R02 逐项相等、release_ts 滞后 5 天触发 `pit_violations` 且 R02 仍按 release_ts 过滤 / 滞后 60 天可见窗口不足不出前瞻分布、249 点/长度不一致/非法 buckets/非法 window FAIL-OPEN；纳入 JSON Schema 与 manifest 真实执行覆盖 |
| 验证与清单 | 54-L1 全量、§6.4 #12 | `pytest tests` 全量 **913 passed / 0 failed**（退出码 0）；本次修改文件 ruff check / ruff format 通过、`git diff --check` 干净；#12 标记完成（未提交） |

**v2.27（D-G14 EWMA 波动/协方差能力出口）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-G14 能力出口 | `capabilities/stats.py::ewma_risk`、`capability_manifest.yaml` | 复用 `metric_series`（deterministic，`min_n=60`）：P07 EWMA 组合协方差（λ 默认 0.94、init_window 20、年化 365）+ T19 逐资产 EWMA 波动序列并列输出；可执行出口 24→25 |
| 输入与结果契约 | 同上 | 多资产面板按原始行 complete-case 后共享同一矩阵；输出 `covariance`（符号/协方差/年化波动）与 `volatility_series`（逐资产）；单资产仅执行 T19 且不输出协方差；仅描述样本内风险结构，不生成交易方向 |
| 降级与执行覆盖 | `tests/test_capabilities.py` | 新增 4 例：多资产完整信封、脏数据清洗后与 P07/T19 逐项相等、单资产仅 T19、59 点/空面板/非法 lam（≥1）/非法 periods FAIL-OPEN；纳入 JSON Schema 与 manifest 真实执行覆盖 |
| 验证与清单 | 54-L1 全量、§6.4 #11 | `pytest tests` 全量 **909 passed / 0 failed**（退出码 0）；本次修改文件 ruff check / ruff format 通过、`git diff --check` 干净；#11 标记完成（未提交） |

**v2.26（D-J24 相关网络与社区发现能力出口）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-J24 能力出口 | `capabilities/stats.py::correlation_network`、`capability_manifest.yaml` | 复用 `metric_series`（deterministic，`min_n=60`）：M05 相关矩阵 → |ρ|≥threshold 无向邻接 → SC71 中心性 + SC72 Louvain 社区 + M21 层次聚类；可执行出口 23→24 |
| 输入与结果契约 | 同上 | 多变量面板按原始行 complete-case 后共享同一数据矩阵；输出节点、边（含 rho）、中心性、社区与模块度、层次聚类标签并列结果；仅描述同期相关关系，不生成交易方向 |
| 降级与执行覆盖 | `tests/test_capabilities.py` | 新增 4 例：36 节点网络完整结果与信封、脏数据清洗后与方法层逐项相等、59 点/空面板/非法 threshold/非法 k FAIL-OPEN、图规模低于方法门禁时降级为 partial；纳入 JSON Schema 与 manifest 真实执行覆盖 |
| 验证与清单 | 54-L1 全量、§6.4 #10 | `pytest tests` 全量退出码 0，按 v2.25 的 772 例加新增 4 例记为 **776 passed / 0 failed**；本次修改文件 ruff / black 通过；#10 标记完成（未提交） |

**v2.25（D-J22 PCA/SVD/因子分析能力出口）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-J22 能力出口 | `capabilities/stats.py::dimension_reduction`、`capability_manifest.yaml` | 复用 `metric_series`（deterministic，`min_n=60`）：真实执行 M19 相关阵 PCA、M20 载荷、SC31 sklearn PCA、SC32 SVD、SC33 因子分析；可执行出口 22→23 |
| 输入与结果契约 | 同上 | 多变量面板按原始行 complete-case，五方法共享同一数据矩阵；输出各分位解释方差、载荷、奇异值与因子载荷并列结果；仅描述数据结构，不生成交易方向 |
| 降级与执行覆盖 | `tests/test_capabilities.py` | 新增 3 例：五方法完整结果与信封、脏数据清洗后与方法层逐项相等、59 点/空面板/非法 k/单变量 FAIL-OPEN；纳入 JSON Schema 与 manifest 真实执行覆盖 |
| 顺带修正 | `capability_manifest.yaml`、`tests/test_methods_s2.py`、`tests/test_eval_harness.py` | D-E15 补声明条件分支实际执行的 I37 Kalman；方法目录计数 238→243（I35–I39 已实现） |
| 验证与清单 | 54-L1 全量、§6.4 #9 | `pytest tests` 全量退出码 0，按 v2.24 的 769 例加新增 3 例记为 **772 passed / 0 failed**；本次修改文件 ruff / black 通过；#9 标记完成（未提交） |

**v2.24（D-G20 分位组合与单调性检验能力出口）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-G20 能力出口 | `capabilities/stats.py::quantile_monotonic`、`capability_manifest.yaml` | 复用 `metric_series`（deterministic，`min_n=250`）：真实执行 B16 分位组统计、B11 组均值严格单调性与 Q04 分位序号 Spearman 检验；可执行出口 21→22 |
| 输入与结果契约 | 同上 | factor 与已对齐 forward 按原始位置 complete-case，三方法共享同一配对样本轴；B16 输出各桶均值/中位/胜率/样本量与最高减最低 spread，B11 输出严格单调方向与 rho_bin，Q04 输出 rho/p/bucket_returns；spread 仅为描述性统计，非策略收益 |
| 降级与执行覆盖 | `tests/test_capabilities.py` | 新增 3 例：三方法完整结果与信封、脏数据清洗后与方法层结果逐项相等、249 点/空输入/非法 k FAIL-OPEN；纳入 JSON Schema 与 manifest 真实执行覆盖 |
| 验证与清单 | 54-L1 全量、§6.4 #8 | `pytest tests` 全量退出码 0，按既有 766 例加新增 3 例记为 **769 passed / 0 failed**；本次修改文件 ruff / black 通过；#8 标记完成（未提交） |

**v2.23（D-G19 IC/ICIR/衰减表能力出口）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-G19 能力出口 | `capabilities/stats.py::ic_profile`、`capability_manifest.yaml` | 复用 `metric_series`（deterministic，`min_n=250`）：真实执行 B13/B14、Q01/Q02/Q03，并在有效 prices 输入时执行 B15；可执行出口 20→21 |
| 输入与结果契约 | 同上 | factor/forward 按原始位置 complete-case；B13/B14 与 Q01/Q02 并列输出 IC/RankIC/分段 ICIR，Q03 输出多期限因子 IC 衰减，B15 输出价格动量重叠/非重叠 IC 衰减；Q03 的 returns 首项补 0、其余为右移一期 forward，避免 h=1 错配 |
| 降级与执行覆盖 | `tests/test_capabilities.py` | 新增 3 例：六方法完整结果与 h=1 对齐、脏数据 complete-case 后六方法结果逐项相等、缺价格 partial 与短样本/空输入 empty；纳入 JSON Schema 与 manifest 真实执行覆盖 |
| 验证与清单 | 54-L1 全量、§6.4 #7 | `pytest tests` 全量退出码 0，按既有 763 例加新增 3 例记为 **766 passed / 0 failed**；本次修改文件 ruff / black 通过；#7 标记完成（未提交） |

**v2.22（D-G16 组合 VaR/CVaR 能力出口）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-G16 能力出口 | `capabilities/stats.py::portfolio_risk`、`capability_manifest.yaml` | 复用 `metric_series`（deterministic，`min_n=60`）：真实执行 P09 参数法组合 VaR、P10 历史法组合 VaR/CVaR，以及 D17/D18 逐资产历史 VaR/CVaR；可执行出口 19→20 |
| 输入与结果契约 | 同上 | 输入各资产收益与可选权重，按最小公共长度对齐；P09/P10 共用同一面板和权重，P10 有效分位同步给 D17/D18；权重归一化、协方差与尾部分位全部在方法层计算，组合与逐资产结果并列输出，损失为正数口径 |
| 执行覆盖 | `tests/test_capabilities.py` | 新增 3 例：四方法结果与完整信封、最小公共长度对齐及方法层结果逐项相等、59 点/空面板 FAIL-OPEN；纳入 JSON Schema 与 manifest 真实执行覆盖 |
| 验证与清单 | 54-L1 全量、§6.4 #6 | `pytest tests` 全量退出码 0，按既有 760 例加新增 3 例记为 **763 passed / 0 failed**；本次修改文件 ruff / black 通过；#6 标记完成（未提交） |

**v2.21（D-J02 季节强度与调整能力出口）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-J02 能力出口 | `capabilities/stats.py::seasonal_adjustment`、`capability_manifest.yaml` | 复用 `seasonality_query`（deterministic，`min_n=60`，`min_span_days=1095`）：真实执行 C13 月度 ANOVA 式季节强度、T10 robust STL 与 SC91 X-13 风格 STL 近似；可执行出口 18→19 |
| 日期轴与历史纵深降级 | 同上 | 有效数值与日期按原始行号同步过滤；缺完整日期轴或有效样本 <60 FAIL-OPEN 为 empty。历史跨度 <1095 天仍保留全部分解结果，但降级 `partial + seasonality_depth_lt_3y`，只作描述 |
| 原始结果与参数披露 | 同上 | 并列返回 C13/T10/SC91 原始结果与三方法季节强度，不新增统计口径、不合成交易方向；T10 默认 period=7、SC91 默认 period=12，并披露 `min_n/min_span_days/periods/as_of` |
| 执行覆盖 | `tests/test_capabilities.py` | 新增 3 例：三方法原始结果与浅历史降级、59 点短样本 empty、缺日期轴 empty；纳入 JSON Schema 与 manifest 真实执行覆盖 |
| 验证与清单 | 54-L1 全量、§6.4 #5 | `pytest tests` 全量退出码 0，按既有 757 例加新增 3 例记为 **760 passed / 0 failed**；本次修改文件 ruff / black 通过；#5 标记完成（未提交） |

**v2.20（D-J04 变点检测能力出口）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-J04 能力出口 | `capabilities/stats.py::change_point`、`capability_manifest.yaml` | 新增 `change_point_query`（deterministic，`min_n=60`）：真实执行 T22/SC49 CUSUM、T23 近似 PELT、SC50 精确 PELT、SC51 Pettitt；可执行出口 17→18。SC47 Kalman 与 SC48 互谱相干明确排除 |
| 结果与日期轴 | 同上 | 并列返回五个方法的原始结果，不合成方向或二次计算统计量；有效数值与日期按原始行号同步过滤，断点下标映射为 ISO 日期，短样本 FAIL-OPEN 为 empty |
| 执行覆盖 | `tests/test_capabilities.py` | 新增 2 例：阶跃序列五方法结果/日期映射、59 点短样本 empty；纳入 JSON Schema 与 manifest 真实执行覆盖 |
| 验证与清单 | 54-L1 全量、§6.4 #4 | **757 passed / 0 failed**，本次修改文件 ruff / black 通过；#4 标记完成（未提交） |

**v2.19（D-E07/B06 状态联合计数）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| B06 纳入 D-E07 | `capabilities/stats.py::state_transition`、`capability_manifest.yaml` | D-E07 方法绑定扩展为 B02/B06/B07/B08/B09；B06 对 `state_t × state_{t+1}` 输出联合计数底表，B07 沿相同状态轴行归一化为转移概率；复用既有能力 ID，可执行出口保持 17 个 |
| 契约与执行覆盖 | `tests/test_capabilities.py`、`tests/test_visual.py` | 新增联合计数总数、相邻转移样本数及逐行归一化概率一致性测试；同步视觉基线冻结清单，manifest 真实执行覆盖包含 B06 |
| 验证与清单 | 54-L1 全量、§6.4 #3 | **755 passed / 0 failed**，ruff / black 通过；#3 标记完成（未提交） |

**v2.18（D-G23 事件窗 CAR + Patell/BMP）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-G23 能力出口 | `capabilities/stats.py::event_car_significance`、`capability_manifest.yaml` | 新增 `event_study`（deterministic，`min_n=250`）：Q10 估计窗 [-120,-20] 均值调整 CAR + 事件窗 [-5,+10]，Q11 Patell/BMP 标准化检验；与 D-E04 的 F19/F21/F23 描述性事件研究分开，不重复计算口径 |
| 事件轴与降级 | 同上 | 价格轴事件下标减 1 转为同日收盘收益下标；有效事件 <30 降级 `events_lt_30`，Q11 无可用估计窗波动时降级 `patell_bmp_unavailable`，均保留 Q10 CAR，顶层 capability gate 使用 `insufficient_samples` |
| 执行覆盖 | `tests/test_capabilities.py` | 新增 3 例：30 事件完整输出、方法层结果复用与 <30 事件降级、Q11 不可用仍保留 CAR；纳入 JSON Schema 与 manifest 真实执行覆盖 |
| 验证与清单 | 54-L1 全量、§6.4 #2 | **754 passed / 0 failed**，ruff / black 通过；#2 标记完成（未提交） |

**v2.17（D-E14 一维相关状态条件分布）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-E14 能力出口 | `capabilities/stats.py::conditional_distribution`、`capability_manifest.yaml` | 新增 `conditional_distribution`（deterministic，`min_n=250`）：输入已压缩一维相关状态与同步价格轴，R02 PIT 4 桶输出 h=1/2；主期限每桶非重叠不足 250 时降 2 桶，仍不足 FAIL-OPEN；弱后续期限单独降级 |
| PIT 状态轴复用 | `methods/conditional.py::r02_percentile_forward/b11_monotonic`、`methods/inference.py::r08_monotonic_phrase` | R02 新增可选 `include_states`；B11/R08 新增可选 `prebinned`，仅供 D-E14 复用同一 PIT 桶标签，默认行为不变；h>1 不执行 B05/R01，不输出朴素 t/p |
| 执行覆盖 | `tests/test_capabilities.py` | 覆盖 h=1/2 共享桶均值、4→2 桶、仅 h=2 弱期限、短样本/错位输入 empty，以及 JSON Schema 与 manifest 五方法真实执行覆盖 |
| 验证与边界 | 54-L1 全量、§6.4 #1/#31/#36 | **751 passed / 0 failed**；#1 标记完成（未提交）；二维 4×4 仍为独立数据阻塞项 #31，S4/T2 仅标 🟡 |

**v2.16（D-E04 事件研究窗 + D-E09 计数与共现能力出口）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-E04 能力出口 | `l1agg/capabilities/stats.py::event_study`、`capability_manifest.yaml` | `event_study`（deterministic，`min_n=250`）：事件日期经 `bisect_left` 对齐到价格轴（取首个不早于事件日的交易日，盘后事件落下一交易日）；F19 事件窗 CAR + F23 事件后分布 + F21 末段 CAR；`data` 顶层披露 `car/cars/n_events/window/win_rate/post_event`，`params` 披露 `event_gate=30/window/as_of` |
| 软门禁而非硬失败 | `l1agg/capabilities/stats.py::_call_soft` | 方法层 `min_n=30` 对事件数是硬门禁；能力层改用 `_call_soft`：仅 `insufficient_samples` 时复用同一登记函数取小样本结果（`gate=degraded`），事件数 <30 降级 `partial` + `events_lt_30` 并保留 CAR/胜率，禁止因事件少而丢数值 |
| D-E04 FAIL-OPEN 边界 | 同上 | 价格 <250、无 events、事件无法映射价格轴、事件窗全部越界（`n_events=0`）→ `ok=false` + `empty`，不伪造数值 |
| D-E09 能力出口 | `l1agg/capabilities/stats.py::count_series`、`capability_manifest.yaml` | `metric_series`（deterministic，`min_n=3`）：`values` 走 R09 涨跌次数，`pairs` 走 B17 共现计数 + R10 一句文案（两方法均真实执行）；对齐点 <3 FAIL-OPEN 为 empty |
| 执行覆盖 | `tests/test_capabilities.py` | 新增 6 例：事件窗 CAR/胜率/`event_gate`、事件数 <30 降级、空事件与短价格双 FAIL-OPEN；R09 涨跌次数、B17/R10 共现（count/ratio/文案）、<3 点 empty；D-E09 场景补 `pairs` 分支以满足 B17/R10 执行覆盖 |
| 前端 cue 分派（D-A14/D-G22） | `3.1-FRONTEND/scripts/data_query_executor.py`、`scripts/l1_route_signal.py`、`src/lib/l1-intent-registry.ts`、`src/lib/l1-intent-registry.test.ts` | `exec_stat_query` 新增「拥挤度→D-A14」「显著性→D-G22」两条 cue 与分支（`significance` 排在相关性之后，保留「相关性是否显著」走 D-E05）；D-G22 由日线收益直算（本地实测 Newey-West t 与 DSR 正常返回，n=723）；D-A14 按冻结口径要求资金费率/未平仓/多空比三序列齐全，缺项明示降级、不以单指标冒充；`stat_query` 意图正则两端同步并补单测（19 例全绿） |
| 既有测试时间炸弹修复 | `tests/test_l0_datacenter_series.py` | `NOW` 由硬编码 `2026-11-14` 改为「今日 12:00 UTC」滚动基准，事件月份断言改用 `FUTURE_MONTH`；修复随真实日期推移必然失败的 `test_partial_quality_below_30`（v2.14/v2.15 记录的既有失败） |
| D-E14 T-1 扩样本（云端生产写入） | `18-price_source --backfill` + `19-backfill_candles_1d.py` | 写前 `.backup` → `dreambuddy_core-20261115-120035.db`；Binance 日线 20 资产入库：`close_1d` 由 1 资产 / 1,409 天扩到 **20 资产 / 54,653 行**，BTC/ETH 3,377 天（2017-08-17→2026-11-14），`dropped_invalid_days=0`、`integrity_check=ok`；门禁复算 1 维 4 桶 @h=1 **20/20**、@h=2 19/20、@h=3 9/20、@h=5 0/20；2 维 4×4 需 ≥4,000 天/资产，仍不足 |
| 验证 | 54-L1 全量 | `pytest tests` → **718 passed / 0 failed**（v2.15 为 712 例，新增 6 例）；ruff / black 全 0 |

**v2.15（冻结 D-A14 `level` 阈值 + 能力出口）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| A 分位法四档 | `l1agg/methods/timeseries.py::f26_crowding_score` / `_f26_level` | `level` 阈值取**分值历史分布**的 p20/p60/p80（`<p20 极低 / p20–p60 低 / p60–p80 偏高 / ≥p80 高`），禁止改用固定等宽四档/五档；同时输出 `percentile / thresholds / window / as_of / pit=false` |
| 降级而非补阈值 | 同上 | 样本 < 方法 `min_n=60` → `level_status=insufficient_sample`；分值分布极差≈0 → `degenerate_distribution`；两种情形均 `level=None, thresholds=None`，不发明兜底阈值 |
| D-A14 能力出口 | `l1agg/capabilities/stats.py::crowding`、`capability_manifest.yaml` | `metric_percentile`（deterministic，`min_n=60`）：复用 F26，`n<60` FAIL-OPEN 为 empty，方法层降级时 `partial` + `degraded_reason`，`params` 披露 `level_method/level_quantiles/window/as_of/pit` |
| 执行覆盖 | `tests/test_methods_timeseries_extra.py`、`tests/test_capabilities.py` | 四档边界、分位口径（非固定常量）、`as_of/window/sample_n` 披露、两类降级；D-A14 纳入 manifest 可运行性、JSON Schema 与真实执行覆盖校验 |
| 验证 | 54-L1 全量 | `pytest tests` → **711 passed / 1 failed**（共 712）；失败用例 `test_l0_datacenter_series::test_partial_quality_below_30` 为日期边界既有失败（HEAD 干净副本同样失败）；ruff / black 全 0 |
| 云端事件回填执行 | `43.160.201.117`（`sudo -u luke`，写前 `.backup`） | 采集 `appended=542`、入库 `upserted=542`；`mm_events` 17 → **550** 行，2015–2026 共 543 行（fomc 103/cpi 145/nfp 157/macro_other 145），`integrity_check=ok`、`event_id` 重复 0；四类事件均过 ≥30 门禁 |
| D-E14 可行性量化 | 本地只读 19 快照 | 仅 BTC/USDT 有连续 **1409 天** `_1d`（2023-01-01→2026-11-09，零缺口）；1 维 4 桶 @h=1 每桶 **352** ✅、h=2 → 176 ✗、2 维 4×4 桶 → 88 ✗（需 ≥4000 天）；其余 24 资产仅 `chart_*` 91 天，资金费率/未平仓/多空比本地 0 行 |
| S1 11 模块历史查询验收 | `fundamental_snapshot._l0_module_timeseries`（本地只读快照） | **11/11 timeseries 非空**；sample_n：macro 254 / onchain 88 / sentiment 90 / valuation 11 / flow 69 / breadth 11 / capital_flow 31 / intermarket 87 / news 39 / narrative 90 / calendar 15；valuation/breadth/calendar 为 `partial`（样本远低于请求窗口） |

**v2.14（D-G22 显著性出口，改动能力出口 + 文档）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-G22 显著性出口 | `l1agg/capabilities/stats.py::hac_significance`、`capability_manifest.yaml` | 新增 `significance_query`（deterministic，`min_n=250`）：Q06 Bartlett 核 HAC t（`t_nw/se/lag`）+ Q07 Deflated Sharpe（`dsr/sr0/n_trials`），统计量全部复用方法层 `l1agg.methods.run`，能力层不重算 |
| 降级与门禁 | 同上 + `tests/test_capabilities.py` | `n<250` → `empty`（提示样本不足）；Q06 退化 → `empty`；Q07 退化 → `partial` + `degraded_reason=dsr_unavailable`，仍保留 HAC t；`n_trials` 显式回传 |
| 执行覆盖 | `tests/test_capabilities.py` | D-G22 纳入 manifest 可运行性、JSON Schema 与真实执行覆盖校验（Q06/Q07 双方法必须实际调用成功） |
| 状态纠偏 | §0.2.4、§2.4、§4.2、§6.2、§6.3 | h>1 重叠前瞻收益的「HAC 前置」由「未实现」改为「出口已具备」；S4 剩余阻塞仅剩 T-1 扩样本、F1–F12 状态特征与 1–2 维场景出口 |
| 验证 | 54-L1 全量 | `pytest tests` → **703 passed / 1 failed**（共 704）；失败用例 `test_l0_datacenter_series::test_partial_quality_below_30` 在 HEAD 干净副本同样失败（日期边界，与本次改动无关）；ruff / black 全 0 |

**v2.13（事件历史回填通道）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| 宏观事件历史回填 | `18-数据获取中心/data_center/collectors/tradefin/macro_history_backfill.py`、`data_center/cli/backfill_macro_calendar.py` | FOMC 用官方日历（2021+ 现页、2015–2020 历史年页，决议日从声明链接提取）；BLS 用年度发布日历，直连被 403 时回退 Wayback；实测 2015–2026 共 **542** 条（fomc 101 / cpi 143 / nfp 155 / macro_other 143），两源零失败 |
| 历史入库与窗口隔离 | `19-数据访问层/scripts/backfill_events_history.py`、`sync_events_to_dal.py` | 历史回填纯 `INSERT OR REPLACE`、不过滤时间窗；日常 sync 的 DELETE 改为**窗口内**，避免把 2015 起的历史行清空 |
| 状态纠偏 | §0.3、§2.4、§4.2、§6.2、§6.3 | D-E04/D-E09 于 v2.15 由「回填通道就绪、待云端入库」改为「已入库 550 行、能力出口待接线」，不提前宣称能力已交付 |
| 验证 | 18/19 新增用例、18 全量、19 全量 | 事件回填 5 例 + DAL 2 例通过；19 全量 **166 passed**；18 全量 666 passed / 4 例与本次改动无关的既有失败（FRED key、新闻语料规模） |

**v2.12（D-E12/R18 时空对齐切片）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-E12/R18 时空对齐切片 | `capabilities/stats.py::alignment_slice`、`capability_manifest.yaml` | `cross_check/gated` 出口真实调用 R18；UTC 日收盘、同日最后观测、跨源去重、ffill 与 `max_stale_days` 口径由方法层统一执行 |
| 降级与执行覆盖 | `tests/test_capabilities.py` | 30 点有效窗口返回 good；历史不足与空窗口均 FAIL-OPEN 为 empty；D-E12 纳入 JSON Schema、manifest 可运行性及真实执行覆盖校验 |
| D-A14 状态纠偏 | §2.1、§2.4、§6.3 | F26 固定权重 `0.4/0.3/0.3` 仅交付 `score/components/weights/n`；`level` 阈值未冻结，不自行发明阈值或宣称完整交付 |
| 验证 | `pytest tests -q`、ruff、black、py_compile | **698 passed**；D-E12 与 R18 联合回归 62 例通过；静态检查通过 |

**v2.11（C18/D-E01/MERS，改动代码 + 文档）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-E11/C18 接线 | `capabilities/stats.py::_paired_rows`、`correlation`、`capability_manifest.yaml` | 提供 dates 时执行自然月同向率；缺失行按原始位置同步过滤 x/y/dates，无 dates 时不伪造 C18 结果 |
| D-E01 条件收益出口 | `capabilities/stats.py::conditional_return`、`capability_manifest.yaml` | B02/B05/F01/H01 四方法真实执行；h=1 前瞻收益先在原价格轴生成，再过滤有效因子对；可执行出口 8→9 |
| MERS S3 内部内核 | `l1agg/mers.py`、`config/mers_grid.yaml`、`tests/test_mers.py` | 6 transforms × 10 methods × 3 horizons = 180 单元；统一 BH-FDR、稳定性门禁、状态机和 SQLite 幂等注册表；R03/R04/F19 缺日历/事件上下文时明确 `not_applicable` |
| MERS 状态边界与负例 | `transition_state` + 固定随机序列三期测试 | candidate 三期通过晋升 stable；stable 两期失败后进入 decayed，再连续四期失败才 retired；stable 遇版本变更回 candidate；随机数据三期 stable=0 |
| 验证 | `pytest tests -q`、全量 audit、ruff | **695 passed**；**implemented 386 / passed 386 / failed 0**；执行 1028、不适用 762、缺失 526；MERS 与能力联合回归 45 例通过 |

**v2.10（配对/推断/执行覆盖，改动代码 + 文档）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| 双序列与 D-E08 配对修复 | `capabilities/stats.py::_paired_floats` + 缺失位置回归 | 任一位置为 None、非法数值、NaN/Inf 时整行剔除，禁止分别过滤后错位配对 |
| D-E05/D-E06 关系推断 | `capabilities/stats.py::correlation` | D-E05 双序列与矩阵 TopK 全接线；D-E06 由 M11/M12 输出完整 lag BH-FDR，T03/T04 保留 legacy 描述 |
| D-E08/B15 契约 | `capability_manifest.yaml`、`conditional_ic` | D-E08 只接 B11/B13/B14 的已对齐 factor/forward；B15 prices/IC decay 归 D-E13/D-G19 |
| manifest 真实执行覆盖 | `manifest.py::validate_execution` + 跨分支集成测试 | 修正 D-E02/I30、D-E03 五个季节性方法、D-E07/B02、D-E10 重复别名等账面绑定漂移 |
| audit 验证覆盖报告 | `eval/harness.py`、`scripts/method_audit.py`、`docs/method_audit.json` | 区分 executed/missing/not_applicable；386/386 PASS 与 66.15% 覆盖率同时披露 |
| 验证 | `pytest tests -q`、全量 audit | v2.10 时点 **686 passed**；**implemented 386 / passed 386 / failed 0**；执行 1028、不适用 762、缺失 526 |

**v2.9（D-E02 接线与 T0.5 交付，改动代码 + 文档）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-E02 前端分派接线 | `3.1-FRONTEND/scripts/data_query_executor.py`（`_STAT_PERCENTILE_CUE` + 分派链 + `dates` 传参） | 分位/百分位/percentile/同分位/前瞻收益/前瞻分布 cue → D-E02；kwargs 带 `prices/dates/symbol`，PIT 日期轴齐备；既有五类 cue 分派与降级路径不回归 |
| 可执行出口 7→8 | `capability_manifest.yaml`、`l1agg/capabilities/stats.py::percentile_forward`（本已就绪，本次核实） | D-E02 经 `persistence/profile.py::conditional_distribution`（A8，`pit=True`）输出分位→前瞻分布；样本不足自动 4→2 桶并披露 `effective_n/nonoverlap_n` |
| T0.5/A8 首版交付 | §0.2.5/§2.4/§0.5/§6.2/§6.3 | T0.5 由 ⬜ 转 ✅（h=1 PIT）；下一关键路径转为 MERS 内核与 S3 全量验收；h>1 显著性仍受 Newey-West/HAC 前置约束 |
| 验证 | mock K线端到端 + cue 回归脚本；`pytest tests` 全量 exit=0 | D-E02 answer/数据块正确（`pit=true`、降桶披露、历史统计尾注）；D-E03/E05/E07/E08/E10 分派不回归 |

**v2.8（方法层全部落地，改动代码）**

| 变更 | 代码位置 | 结论 |
|---|---|---|
| 核心 66 条补登记并实现 | `l1agg/methods/technical.py`（I03–I34 中缺的 22）、`correlation.py`（M08–M10/M13–M16/M18–M22/M26）、`inference.py`（H09–H12、R03–R07/R12–R15/R18）、`timeseries.py`（T05/T06/T10/T18/T23/T25/T26、F15/F16/F19/F22–F26）、`descriptive.py`（D14/D15） | 66 条全部真实计算并登记，核心 238 条 `implemented=true` 237（仅 C11 不可用） |
| 调研族 149 条转为实现 | `research_xo.py`（X12+O15=27）、`research_pq.py`（P14+Q16=30）、`research_sc_a.py`（SC01–SC46）、`research_sc_b.py`（SC47–SC92） | 149 条全部实现；`research.py` 降为纯编号表（`spec_of`/`specs_of`），不再登记占位 |
| 校验范围扩展 | `l1agg/eval/harness.py::audit(scope=...)`、`scripts/method_audit.py --scope` | 支持 `core`(238)/`research`(149)/`all`(387)；本次以 `--scope all` 生成 [method_audit.json](./method_audit.json) |
| 验证 | audit / pytest | **implemented 386 / passed 386 / failed 0**；`pytest tests -q` → **666 passed**；每个已实现 ID 在测试中均有引用（0 缺口） |
| 旧断言修正 | `tests/test_methods_s2.py`、`tests/test_methods_research.py` | “T05/T18 仍为占位”改为“仅 C11 为占位”，与新状态一致 |

> 口径说明：X/O/P/Q/SC 的 `layer` 与 `min_n` 仍以 `research.py` 编号表为准；SC25/SC30 的分组输入为 `input_kind="panel"`（扁平多键或 `groups` 键），SC79–SC83 的 meta 输入为 `{"effects","se"}` 并提供 synthetic 用例。

**v2.7（注册表放开调研族）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| 注册表前缀放开 | `l1agg/methods/registry.py`（`RESEARCH_CAPACITY`/`ALL_CAPACITY`/`_split_id()`） | `_validate_id` 支持 `X/O/P/Q/SC`（`SC` 为双字母前缀，不按首字符解析）；`_placeholder` 同步改用 `ALL_CAPACITY` |
| 调研族占位登记 | `l1agg/methods/research.py`（新建，由 `methods/__init__.py` 导入） | 149 条 `X12/O15/P14/Q16/SC92` 全部 `register_unavailable`，`implemented=false`，调用抛 `MethodUnavailable`；未写任何空壳实现 |
| 校验范围分层 | `l1agg/methods/registry.py::all_specs(scope=...)` | 新增 `scope="core"|"research"|"all"`（238/149/387），默认 `core`，既有 `catalog_total == 238` 断言不受影响 |
| 审计产物扩展 | `l1agg/eval/harness.py`、[docs/method_audit.json](./method_audit.json) | summary 增加 `research_catalog_total=149`、`registered_total=321`；全量重跑 **implemented 171 / passed 171 / failed 0**；`pytest tests -q` → 397 passed |
| 同步文档 | METHOD_LIBRARY v1.10、本文 §0.1/§2/§6.1 | 目录口径统一为 387 = 核心 238 + 调研族 149 |

**v2.6（调研对齐）**

| 变更 | 本文位置 | 结论 |
|---|---|---|
| 三类用户问题统一映射 | §0.2.0 | 将「趋势方向」拆为已形成方向、序列延续性、历史同状态条件分布；统一组合回答骨架，禁止把历史统计写成点预测 |
| 关系榜单与周期口径分流 | §0.2.2–§0.2.3 | 同期、领先滞后、前瞻 IC、稳定推荐四类榜单不得混排；日历周期、状态周期、相似历史片段不得互相冒充 |
| R02 PIT 双口径与 T0.5 blocker | §0.2.1/§0.2.5、§2.4、§4 | `pit=false/pit=true` 双口径均已实现（`pit=true` 为逐时点滚动分位 + `release_ts` 过滤）；T0.5/T2/MERS 只接受 `pit=true`。T0.5 位于 S3→S4，首版 h=1，当前 blocker 为场景编排、每桶非重叠 n≥250 样本纵深与 D-E02 出口 |
| D-E14 降维约束 | §0.2.6、§2.4 | 不直接消费完整 N×N 矩阵，先压缩为 F1–F12；T2 首版限 1–2 维并按每桶非重叠样本验收 |
| 专用质量门禁 | §4 | 通用 `n≥30` 不再覆盖相关/CCF/条件统计专用门槛；补 PIT 披露、完整搜索族 `p_adj` 与 h>1 Newey-West/HAC 前置 |
| 能力状态纠偏 | §2 | 登记数修正为 **103 项 / E14 项**；区分 **171 方法 audit 全 PASS**、**7 个 manifest 可执行出口**与登记范围完整交付。同步修正 D-E02/E05/E11/E13/E14、D-G17/G20、D-J02/J04 等状态 |
| 文档治理 | §0.3–§0.4、§6.2 | 方法实施路线统一为 S0–S7；数据实测只由 METHOD_LIBRARY §15 独立维护，其他文档保留明确标注的决策摘要并在执行时重算 |

> v2.5 的日线收盘锚点修复（UTC 日首、`bar_close/snapshot_last`、跨资产同锚点）与其记录的 397 例测试基线全部保留。v2.6 仅修订文档；**v2.7 改动了代码**（registry / research.py / harness），并已复跑 audit 与 397 例测试。

### 6.2 关联文档与整体规划进度

**本版同步文档**：

| 文档 | 目标版本 | 同步内容 |
|---|---|---|
| [METHOD_LIBRARY.md](./METHOD_LIBRARY.md) | v1.17 | v1.17：D-E04（F19/F21/F23）与 D-E09（R09/B17/R10）接线，可执行出口 14 个；v1.16：F26 `level` 冻结为 A 分位法（分值历史分布 p20/p60/p80）；方法口径未因接线改变 |
| [SPEC-54-L1架构能力聚合层.md](../SPEC-54-L1架构能力聚合层.md) | v1.21 | v1.21：D-G20 接入 B16 分位组统计、B11 严格单调性与 Q04 Spearman 检验，可执行出口 22 个；v1.20：D-G19 IC/ICIR/衰减表出口已接线；S5 对外推荐仍未开放 |
| [SPEC-54-延续性统计分析模块.md](../SPEC-54-延续性统计分析模块.md) | v1.5 | T0.5/A8 首版经 D-E02 出口交付（h=1 PIT，含降桶降级披露）；R02 `pit=true` 已实现；不改 A1–A7 冻结口径 |
| 三份 RESEARCH 文档 | 保持原文（仅同步能力计数） | 作为调研证据，不改写方法结论；RESEARCH-SCIENTIFIC 的能力出口计数同步为 14，分别支撑延续性分层、机构研究协议与科研可复现/PIT 校验 |

**整体进度（按登记范围，而非按方法数量）**：

| 路线（成对映射） | 当前状态 | 已交付 | 尚未闭环 |
|---|---|---|---|
| SPEC S1 ↔ 方法 S1 | 🟡 核心底座完成 + 11 模块本地验收通过 | `market.candles`、UTC 对齐、前瞻收益、价格回显、日线同锚点；`fundamental_snapshot._l0_module_timeseries` 本地只读快照实测 **11/11 模块 timeseries 非空**（sample_n：macro 254、onchain 88、sentiment 90、valuation 11、flow 69、breadth 11、capital_flow 31、intermarket 87、news 39、narrative 90、calendar 15） | valuation/breadth/calendar 为 partial（样本 11/15 天，远低于请求窗口），需 18 侧补历史；通过 ≠ 样本充分 |
| SPEC S2 ↔ 方法 S2 | 🟡 方法完成、能力部分接线 | M01–M07/M11–M12/M24–M25 方法；D-E05 双序列与矩阵 TopK、D-E06 BH-FDR、D-E11/C18 可执行；D-A14 拥挤度合成（A 分位法四档）已接线 | 完整四类榜单契约（稳定推荐仍归 MERS/S5） |
| SPEC S3 ↔ 方法 S3/S6/S7；T0=S3 子集 | 🟡 方法、能力与 MERS S3 内核部分交付 | S3 批 22 方法、S6 扩展、22 个 manifest 出口（含 D-A14/D-E01/D-E02/D-E04/D-E09/D-E12/D-E14/D-G16/D-G19/D-G20/D-G22/D-G23/D-J02/D-J04）；T0/D-E13 已交付；R02 `pit=true` 与 MERS 180 单元内部内核已实现；事件历史已云端回填入库（`mm_events=550`）；前端 cue 分派已补 D-A14/D-G22（路由 + 执行器 + 单测三处对齐） | S3 全量真实数据验收；D-E14 样本纵深；云端周期调度 |
| **T0.5=S3→S4** | ✅ 首版已交付（v2.9） | R02 `pit=true` + A8 编排 + D-E02 出口与前端分派；h=1、4 桶 PIT 滚动分位，样本不足自动降 2 桶并披露 `effective_n/nonoverlap_n` | 真实数据纵深不足时按契约降级；h>1 显著性须走 D-G22 出口（已接线） |
| SPEC S4 ↔ T2 | ⬜ | 条件分布非点预测的契约已明确；h>1 显著性出口 D-G22（Q06/Q07）已接线 | T-1 扩样本、T1a/T1b、F1–F12 状态特征、1–2 维场景出口；每桶非重叠 ≥250 的样本纵深仍未满足 |
| SPEC S5 ↔ T3及后续 | ⬜ | MERS S3 内部内核、BH-FDR、holdout 同号、状态机、幂等注册表与随机负例已交付 | walk-forward 完整验收、Discovery、只读推荐/发现出口；不得提前开放 `relationship_recommend` |

### 6.3 下一阶段顺序（blocker 驱动）

1. **R02 `pit=true` 与 T0.5 已交付（v2.9）**：`conditional.py::r02_percentile_forward` 双口径 + A8 编排 + D-E02 出口（manifest/executor/前端分派）均已接线；样本不足按场景包降 2 桶并披露 `effective_n/nonoverlap_n`，不输出点预测。
2. **MERS S3 内核已交付，下一关键路径是 S3 全量真实数据验收**：180 单元、BH-FDR、holdout 同号、状态机、幂等与随机负例已验证；生产周期评估只能在云端执行，R03/R04/F19 仍需真实日历/事件上下文，单出口交付不等于显著性结论。
3. **继续补齐 S2/S3 登记范围**：D-E05 矩阵 TopK、D-E11/C18、D-E01、D-E12/R18、D-A14、D-E04/D-E09 已完成（v2.16 接线事件研究窗与计数共现）；L1 前端 `data_query_executor` 的 D-A14（拥挤度）与 D-G22（显著性）cue 分派已同步补齐（`3.1-FRONTEND/scripts/data_query_executor.py` + `l1_route_signal.py` + `src/lib/l1-intent-registry.ts`）；D-E14 的 T-1 扩样本已在云端落地（20 资产 / 54,653 行 `close_1d`），一维场景编排与能力出口已于 v2.17 接线；2 维 4×4 仍需 ≥4000 天/资产。四类榜单分别披露搜索空间与 `p_adj`，不得混排。
4. **T2 一维首版已交付，二维继续受样本约束**：T-1 已在云端唯一生产写入口执行完毕（2026-11-15，20 资产 / 54,653 行 `close_1d`，BTC/ETH 3377 天）；D-E14 已接入已压缩一维相关状态的 PIT h=1/2 条件分布，2 维 4×4 仍需 ≥4000 天/资产且 F1–F12 PIT 特征另行完成。h>1 显著性结论统一走 D-G22 出口，不得用朴素 t 值。
5. **最后开放 S5**：MERS/Discovery 通过 holdout、walk-forward、BH-FDR 和随机负例后，才开放稳定推荐与发现查询。

### 6.4 待完成清单（2026-11-15）

> **完成标记**：每完成一项，将状态改为 ✅ 并记录完成日期与 commit hash（如已提交）。
> **优先级**：P0 > P1 > P2 > P3；可交付性：数据与方法全部就绪 > 方法已实现 > 数据阻塞。

#### 6.4.1 可立即交付（数据与方法全部就绪）

| # | 能力 ID | 能力名 | 优先级 | 状态 | 缺口说明 | 预计工作量 |
|---|---------|--------|--------|------|----------|-----------|
| 1 | **D-E14** | 条件分布（状态→前瞻）场景编排 | P1 | ✅ 2026-11-15（未提交） | 一维首版已交付：manifest + `conditional_distribution` executor + R02 PIT 共享桶标签 + 4→2 桶/弱期限降级；54-L1 全量 751 例通过。二维 4×4 不在本项范围，见 #31 | 已完成 |
| 2 | **D-G23** | 事件窗 CAR + Patell/BMP | P2 | ✅ 2026-11-15（未提交） | 已交付 manifest + `event_car_significance`：Q10 均值调整 CAR + Q11 Patell/BMP；同日收盘收益下标对齐、<30 事件与 Q11 不可用降级；54-L1 全量 754 例通过 | 已完成 |
| 3 | **D-E07** | 二维交叉表（B06） | P2 | ✅ 2026-11-15（未提交） | 已纳入 manifest 与 `state_transition`：B06 输出相邻状态联合计数，B07 行归一化为转移概率；同步视觉基线与真实执行覆盖，54-L1 全量 755 例通过 | 已完成 |
| 4 | **D-J04** | 变点检测（CUSUM/PELT/Pettitt） | P2 | ✅ 2026-11-15（未提交） | 已交付 manifest + `change_point`：T22/SC49、T23/SC50、SC51 五方法真实执行，原始结果与日期映射并列输出；54-L1 全量 757 例通过 | 已完成 |
| 5 | **D-J02** | 季节强度与调整（STL/X-13） | P2 | ✅ 2026-11-15（未提交） | 已交付 manifest + `seasonal_adjustment`：C13/T10/SC91 三方法真实执行，完整日期轴同步过滤，原始分解结果与季节强度并列输出；不足 3 年降级为描述性结论，54-L1 全量 760 例通过 | 已完成 |

#### 6.4.2 短期交付（方法已实现，P1/P2 优先级）

| # | 能力 ID | 能力名 | 优先级 | 状态 | 缺口说明 | 预计工作量 |
|---|---------|--------|--------|------|----------|-----------|
| 6 | **D-G16** | 组合 VaR/CVaR | P2 | ✅ 2026-11-15（未提交） | 已交付 manifest + `portfolio_risk`：P09/P10 组合参数法/历史法风险与 D17/D18 逐资产历史风险并列输出；最小公共长度对齐、权重归一化与统计计算复用方法层，54-L1 全量 763 例通过 | 已完成 |
| 7 | **D-G19** | IC/ICIR/衰减表 | P2 | ✅ 2026-11-15（未提交） | 已交付 manifest + `ic_profile`：B13/B14/Q01/Q02/Q03 核心五方法 + 有效价格时 B15 真实执行；Q03 收益轴右移防错配，缺价格降级、短样本 empty，54-L1 全量 766 例通过 | 已完成 |
| 8 | **D-G20** | 分位单调性检验（B16） | P2 | ✅ 2026-11-15（未提交） | 已交付 manifest + `quantile_monotonic`：B16 分位组统计、B11 严格单调性与 Q04 Spearman rho/p 真实执行；complete-case 共享样本轴，spread 明确为描述性统计，短样本/空输入/非法 k 均为 empty，54-L1 全量 769 例通过 | 已完成 |
| 9 | **D-J22** | PCA/SVD/因子分析 | P2 | ✅ 2026-11-15（未提交） | 已交付 manifest + `dimension_reduction`：M19/M20/SC31/SC32/SC33 真实执行，面板 complete-case 共享数据矩阵，仅描述数据结构；聚类 M21/M22 归 D-J23；54-L1 全量 772 例通过 | 已完成 |
| 10 | **D-J24** | 相关网络与社区发现 | P2 | ✅ 2026-11-15（未提交） | 已交付 manifest + `correlation_network`：M05 相关矩阵 → |ρ| 阈值邻接 → SC71 中心性 + SC72 Louvain 社区 + M21 层次聚类；面板 complete-case，仅描述同期相关、不生成交易方向；图规模不足方法门禁时降级披露；54-L1 全量 776 例通过 | 已完成 |
| 11 | **D-G14** | EWMA 波动/协方差 | P1 | ✅ 2026-11-15（未提交） | 已交付 manifest + `ewma_risk`：P07 EWMA 组合协方差与 T19 逐资产 EWMA 波动序列并列输出，多资产面板 complete-case，单资产仅 T19；非法 lam/periods 与 59 点样本为空；54-L1 全量 909 例通过 | 已完成 |
| 12 | **D-J30** | PIT/release_ts 全局能力 | P1 | ✅ 2026-11-15（未提交） | 已交付 manifest + `pit_alignment`：SC90 校验「可用时间 ≤ 使用时间」（release_ts/used_ts 支持 ISO 与数值时间戳）+ R02 `pit=true` 前瞻分布并列输出；PIT 违规降级 partial 并披露前视风险，过滤后可见窗口不足不出前瞻分布，249 点/长度不一致/非法 buckets/window 为空；54-L1 全量 913 例通过 | 已完成 |

#### 6.4.3 中期交付（P0 基础能力）

| # | 能力 ID | 能力名 | 优先级 | 状态 | 缺口说明 | 预计工作量 |
|---|---------|--------|--------|------|----------|-----------|
| 13 | **D-A01** | 历史序列 | P0 | ✅ 2026-11-15（未提交） | 已交付 manifest + `history_series`：单序列区间取点 + 日/周/月降采样（每区间取最后观测，同日重复取最后），输出 `points[]/span/unit`；当前历史分位由 S25 真实执行；日期轴必填且等长，缺失率 >20% 降级 partial，29 点/长度不一致/非法 freq 为空；能力相关 920 例通过 | 已完成 |
| 14 | **D-A02** | 变化率 | P0 | ✅ 2026-11-15（未提交） | 已交付 manifest + `change_rate`：S15 绝对变化 + S16 变化率并列输出，`window` 默认 1；基期 0 降级 `change_pct_unavailable` 保留绝对变化，1 点/window 越界/window=0/NaN 为空；能力相关 925 例通过 | 已完成 |
| 15 | **D-A03** | CAGR | P1 | ✅ 2026-11-15（未提交） | 已交付 manifest + `cagr`：S19 真实执行，含日期轴时按首末日期实际天数折算年数（缺日期回退 n−1），输出 `cagr/years/span/days`；跨度不足 1 年降级 `short_span`，非正价格/天数≤0/1 点为空；能力相关 929 例通过 | 已完成 |
| 16 | **D-A04** | 历史分位 | P1 | ✅ 2026-11-15（未提交） | 已交付 manifest + `percentile_rank`：S25 真实执行末值经验分位，`lookback` 缺省全样本（须 ≥30），输出 `percentile/value/lookback/sample_n`；窗口 <60 期降级 `short_lookback`，lookback 超可用历史降级 `lookback_truncated`，29 点/非法 lookback/长度不一致为空；能力相关 933 例通过 | 已完成 |
| 17 | **D-A06** | 年化波动率 | P1 | ✅ 2026-11-15（未提交） | 已交付 manifest + `annualized_volatility`：F05 真实执行（日简单收益 σ × √365），`window` 缺省全样本（须 ≥30），输出 `volatility/mean_ret/window/sample_n`；有效样本 <60 期降级 `short_window`，29 点/window<30/长度不一致/含无效值为空；能力相关 937 例通过 | 已完成 |
| 18 | **D-A07** | 回撤 | P1 | ✅ 2026-11-15（未提交） | 已交付 manifest + 复用 `drawdown`（注入 `capability_id=D-A07`）：D20/D21 真实执行，输出 `drawdown/peak_ts` 及 `mdd/current_drawdown/duration_days/drawdown_path`；与 D-E10 同输入逐项一致；`prices<2` 为空，100 点样本降级 `insufficient_samples`；能力相关 941 例通过 | 已完成 |
| 19 | **D-A08** | 同比 | P1 | ✅ 2026-11-15（未提交） | 已交付 manifest + `yoy_change`：S16 真实执行 `x_t/x_{t-period}-1`（`period` 默认 12），输出 `yoy/base_ts/period/sample_n`；历史 <2 个完整周期降级 `short_history`，基期 0 降级 `yoy_unavailable`，样本 ≤period 或 period<1 为空；能力相关 945 例通过 | 已完成 |
| 20 | **D-A09** | 环比 | P1 | ✅ 2026-11-15（未提交） | 已交付 manifest + `mom_change`：S16 以 `k=1` 真实执行 `x_t/x_{t-1}-1`，输出 `mom/base_ts/sample_n`；基期 0 降级 `mom_unavailable`，样本 <2 或日期长度不一致为空；能力相关 949 例通过 | 已完成 |
| 21 | **D-A10** | 实际利率 | P1 | ✅ 2026-11-15（未提交） | 已交付 manifest + `real_rate`：通胀由 S16（`k=period`，默认 12）真实执行并折算百分点，能力层只做 `名义 − 通胀` 差值，输出 `real_rate/nominal/inflation/base_ts/period/sample_n`；CPI 基期 0 降级 `inflation_unavailable`，历史 <2 个完整周期降级 `short_history`，样本不足以覆盖 period、period<1、双序列/日期长度不一致或含无效值为空；能力相关 953 例通过 | 已完成 |
| 22 | **D-A11** | 双序列滚动相关 | P2 | ✅ 2026-11-15（未提交） | 已交付 manifest + `rolling_correlation`：M04 真实执行滚动 Pearson 相关（window 默认 30），输出 `corr/mean_r/window/n_windows/sample_n`；有效配对 <60 降级 `insufficient_samples` 但保留结果，配对 <2、window<2 或超样本、日期长度不一致为 empty；能力相关 957 例通过 | 已完成 |
| 23 | **D-A12** | 领先滞后相关 | P2 | ✅ 2026-11-15（未提交） | 已交付 manifest + `lead_lag_correlation`：M11 输出 lag −max_lag…+max_lag（默认 10）的相关/p/BH-FDR q/显著性，M12 输出最优 lag；输出 `best_lag/best_corr/best_p_adj/corr_by_lag[]`；有效配对 <120 降级 `insufficient_history` 但保留结果，配对 <2、max_lag<1 或超样本、日期长度不一致为 empty；能力相关 961 例通过 | 已完成 |
| 24 | **D-A13** | 极端事件频率 | P2 | ✅ 2026-11-15（未提交） | 已交付 manifest + `extreme_frequency`：阈值缺省由 S11 分位（quantile 默认 0.95）给出，`side` 支持 above/below/abs，输出 `days/ratio/threshold/side/quantile/sample_n`；样本 <30 且无阈值为空，显式阈值 <30 降级 `insufficient_samples` 但保留计数；能力相关 965 例通过 | 已完成 |
| 25 | **D-A15** | ETF 净流入滚动和 | P2 | ✅ 2026-11-15（未提交） | 已交付 manifest + `etf_flow_rolling`：S20 真实执行滚动均值，能力层以「均值 × 窗口长度」算术还原滚动和（不重算分布），`windows` 可配（默认 7/30），输出 `sum_{k}d/windows/sample_n`；样本 <30 降级 `insufficient_samples` 但保留结果，窗口超历史降级 `short_history` 并将该窗口置 None，全部窗口不可算为空；能力相关 969 例通过 | 已完成 |
| 26 | **D-A16** | 稳定币增速 | P2 | ✅ 2026-11-15（未提交） | 已交付 manifest + `stablecoin_growth`：S16 逐窗口真实执行并折算百分比，能力层只组装多窗口，`windows` 可配（默认 7/30），输出 `growth_{k}d/windows/sample_n`；样本 <30 降级 `insufficient_samples` 但保留结果，窗口超历史降级 `short_history`，基期 0 降级 `base_zero` 并将该窗口置 None，全部窗口不可算为空；能力相关 985 例通过 | 已完成 |
| 27 | **D-B08** | 趋势斜率 | P2 | ✅ 2026-11-15（未提交） | 已交付 manifest + `slope_trend`：T08 对数价格 OLS 斜率/R² + T09 名义 t/p，显式 `hac_corrected=false`；`window` 默认 90、下限 30，样本 <60 降级 `short_window` 但保留结果，样本 <30 或 window<30 为空；能力相关 165 例通过 | 已完成 |
| 28 | **D-B09** | 距 ATH 回撤 | P2 | ✅ 2026-11-15（未提交） | 已交付 manifest + `ath_drawdown`：复用 D-E10 `drawdown`（D20/D21 真实执行），输出 `drawdown_from_ath/ath/ath_ts` 别名（= current_drawdown/peak_price/peak_ts），样本 <250 降级 `insufficient_samples`，价格 <2 或全无效值为空；能力相关 169 例通过 | 已完成 |
| 29 | **D-G08** | 12-1 动量 | P1 | ✅ 2026-11-15（未提交） | 已交付 manifest + `momentum_12_1`：按 skip/lookback 切片后由 F14 真实执行动量/波动/风险调整动量，输出 `momentum_12_1/lookback/skip/vol/risk_adjusted/window_start_ts/window_end_ts/truncated/sample_n`；历史不足时截断 lookback 并降级 `short_history`，样本 <60、lookback<2、skip<0、非整数参数、日期长度不一致为空；20 日 ts_rank 属 D-G07 未随本能力接线；本次全量 1056 例通过 | 已完成 |
| 30 | **D-G09** | 波动率目标换算 | P1 | ✅ 2026-11-15（未提交） | 已交付 manifest + `vol_target_scale`：价格转日简单收益后由 P02 计算窗口实现年化波动与 `scale = target_vol / realized_vol`（默认 target 0.10 / window 20 / periods 365），输出 `scale/target_vol/realized_vol/window/periods/returns_n/sample_n`；收益 <60、`target_vol≤0`、`window<2`、`periods<1`、日期长度不一致为空；window 超长降级 `window_truncated`，零波动降级 `zero_volatility`；本次全量 1060 例通过 | 已完成 |

#### 6.4.4 数据阻塞（需更多样本或新数据源）

| # | 能力 ID | 能力名 | 优先级 | 状态 | 阻塞原因 | 预计解除时间 |
|---|---------|--------|--------|------|----------|-------------|
| 31 | **D-E14（2 维）** | 二维状态组合（4×4） | P2 | ⬜ | 需 16×250=4,000 日/资产，当前最长 3,377 天 | T+~2 年（自然增长）或外部数据源回填 |
| 32 | **C11** | 节日/事件日历 | P2 | ⬜ | 缺交易日历（登记不可用） | 需接入交易日历数据源 |
| 33 | **D-G25** | 尾部相关 | P2 | ⬜ | 依赖样本纵深 | T+~1 年 |
| 34 | **D-J05** | 比特币四年周期 | P2 | ⬜ | 需 ≥2 周期 ≈2,920 日，当前 3,377 天（BTC）刚达标，但其他资产不足 | 部分资产可交付 |

#### 6.4.5 S 级路线里程碑

| # | 里程碑 | 状态 | 缺口说明 | 预计工作量 |
|---|--------|------|----------|-----------|
| 35 | **S2/S3 全量真实数据验收** | ⬜ | MERS S3 内部 180 单元网格、BH-FDR、状态机与幂等注册表已实现；待全量真实数据验收及云端周期调度 | 4h |
| 36 | **S4 T2 条件外推表达** | 🟡 | T0.5 与 D-E14 一维 h=1/2 首版已交付（#1 ✅）；T2 的二维 4×4 仍受样本纵深阻塞（#31），不能据一维出口宣称全部完成 | 剩余受 #31 阻塞 |
| 37 | **S5 对外推荐** | ⬜ | MERS/Discovery 通过 holdout、walk-forward、BH-FDR 和随机负例后，才开放稳定推荐与发现查询 | 8h |

#### 6.4.6 基础设施项

| # | 项目 | 状态 | 缺口说明 | 预计工作量 |
|---|------|------|----------|-----------|
| 38 | **S1 11 模块历史查询验收** | 🟡 | 11/11 timeseries 非空，但 valuation/breadth/calendar 为 partial | 2h |
| 39 | **前端 D-A 组 cue 分派** | ✅ | 已接入 D-A01~D-A16 中除既有 D-A14 外的 14 个出口；指标/实际利率/双资产分派及降级边界均有本地测试 | 已完成 |
| 40 | **前端 D-B 组 cue 分派** | ✅ | 已接入 D-B08/D-B09/D-G08/D-G09；ATH 取 1825 天，专用 cue 优先于宽词 | 已完成 |

---

**统计**：
- **可立即交付**：0 项待办 + 5 项已完成（#1-#5）
- **短期交付**：0 项待办 + 25 项已完成（#6-#30）
- **中期交付**：0 项（#29-#30 已完成）
- **数据阻塞**：4 项（#31-#34）
- **S 级路线**：3 项（#35-#37）
- **基础设施**：1 项待办 + 2 项已完成（#38-#40）
- **总计**：40 项（✅ 32 项，待办/阻塞 8 项）

**下一步**：短期交付已清零，剩余 8 项为数据阻塞（#31-#34）、S 级路线（#35-#37）与验收基础设施（#38）；按编号下一项为 #35（S2/S3 全量真实数据验收，需云端窗口）。本轮仅完成 #39/#40 本地闭环，未执行云端验收。

**文档治理**：见 §0.4；实测数字只在 METHOD_LIBRARY §15 独立维护，其他文档只能引用或保留标注「引自 §15」的决策摘要，执行时按最新快照重算。
