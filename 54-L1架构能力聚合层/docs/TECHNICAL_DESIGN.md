# 54 总技术文档 — 数据 → 统计 → 关系能力地图

- **版本**: v2.9 ｜ **日期**: 2026-11-15 ｜ **状态**: 🟢 总技术文档（v2.9 D-E02 能力出口接线：manifest `I30/R02` + `percentile_forward` + 前端分位 cue 分派，可执行出口 **8 个**，T0.5/A8 首版经 D-E02 交付（h=1 PIT，含降桶降级披露）；v2.8 方法层全部落地：核心 66 条补登记并实现 + 调研族 149 条从占位转为真实实现，`REGISTRY` 387 条全登记、`implemented=true` **386**，仅 C11 因缺交易日历不可用；audit **386/386 PASS**、测试 **666 例全绿**；`audit(scope=core|research|all)` 与 `--scope` 支持全量校验；v2.7 注册表放开调研族前缀并完成占位登记；v2.6 调研对齐与路线收口）
- **上游**: `SPEC-54-L1架构能力聚合层.md`（ADR/契约/路线）、`docs/METHOD_LIBRARY.md`（方法 SSoT）
- **下游**: `3.1-FRONTEND/scripts/l1_route_signal.py`（L1 路由）、`34-前端应用训练系统/core/l0_foundation.py`（L0 scope）、`/api/fundamental/**`
- **定位**: 本文是 54 的**总技术文档**——上半部（§0）回答「有哪些问题域、每个问题域用什么方法、现在缺什么」；下半部（§1–§6）是能力登记册（ID/依赖/字段/优先级/状态）。

---

## §0 全景：文档地图 / 六类问题 / 数据可行性 / 治理规则

### 0.1 文档地图（谁是 SSoT）

| 文档 | 角色 | 唯一负责的内容 | 当前版本 |
|---|---|---|---|
| [SPEC-54-L1架构能力聚合层.md](../SPEC-54-L1架构能力聚合层.md) | 架构与契约 | ADR、scope 出入参、门禁、路线（S1–S5）、MERS/Discovery | v1.7 |
| **本文 TECHNICAL_DESIGN.md** | **总技术文档 + 能力登记** | 六类问题地图、四层分工（§0.5）、能力 ID `D-*`、状态列、整体进度（§6.2） | **v2.9** |
| [METHOD_LIBRARY.md](./METHOD_LIBRARY.md) | 方法 SSoT | 方法 ID（S/D/T/C/I/M/B/F/H/R/X/O/P/Q/SC）、口径冻结（§16）、数据前提（§15） | v1.12 |
| [RESEARCH-TREND-PERSISTENCE-MODELS.md](./RESEARCH-TREND-PERSISTENCE-MODELS.md) | 调研 | 延续性三层拆解、Tier A/B/C、T 阶段 | v1.2 |
| [RESEARCH-INSTITUTIONAL-L1-METHODS.md](./RESEARCH-INSTITUTIONAL-L1-METHODS.md) | 调研补强 | 机构方法（X/O/P/Q） | — |
| [RESEARCH-SCIENTIFIC-METHODS.md](./RESEARCH-SCIENTIFIC-METHODS.md) | 调研补强 | 科研统计（SC01–SC92） | — |
| [SPEC-54-延续性统计分析模块.md](../SPEC-54-延续性统计分析模块.md) | 场景包 | A1–A7 编排、画像契约、T0.5 后续门禁、文本模板 | v1.5 |
| [SPEC评审报告-延续性统计分析模块-v0.1.md](../SPEC评审报告-延续性统计分析模块-v0.1.md) | 评审档案（只读） | 评审结论与复审记录 | v0.1 |

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
| 对比历史周期的后续表现，当前价格下一阶段可能怎样？ | 用 PIT 历史状态匹配，给出同状态后的条件收益分布；不是周期外推或点预测 | B02/B05/B10、R01/R02/R08；D-E02；T0.5（S3→S4）；T2/D-E14（S4） | `conditional_distribution`：均值/中位/胜率/区间/有效样本量，并固定声明历史统计边界 |

调研印证：延续性三层拆解与 T 阶段见 [RESEARCH-TREND-PERSISTENCE-MODELS.md](./RESEARCH-TREND-PERSISTENCE-MODELS.md)；PIT、滚动研究与多重比较见 [RESEARCH-INSTITUTIONAL-L1-METHODS.md](./RESEARCH-INSTITUTIONAL-L1-METHODS.md)；可复现、不确定度与 PIT 校验见 [RESEARCH-SCIENTIFIC-METHODS.md](./RESEARCH-SCIENTIFIC-METHODS.md)。

**组合回答骨架（规划契约，不替换现有 `CapabilityResult`）**：`current_state / persistence_profile / relationship_topk / conditional_distribution / robustness / quality / caveat`。每项统计必须携带 `n/window/as_of/align_method/timezone`，涉及显著性时补 `p_adj`；尾注固定为「历史统计，不代表未来」，禁止「将会、预计、必然」等措辞。

#### 0.2.1 数据与价格对齐（地基）

| 子问题 | 方法 ID | 能力 ID | 实现状态 |
|---|---|---|---|
| UTC 日收盘、跨源去重、低频 ffill、stale 上限 | 口径见 `align.py`，原语 R18；`market.candles` 1d 另有**收盘锚点** `bar_close`/`snapshot_last`（跨资产统计须同锚点） | D-E12 ⬜（对齐函数已可用） | ✅ `l1agg/align.py` / `l0_foundation.py::_fetch_market_candles` |
| 价格轴派生 1D/1W/1M | S20–S23 | D-B00（🟡→✅） | ✅ `market.candles` |
| 前视规避（PIT，`as_of` / 宏观 `release_ts`） | SC90、R02 | D-J30 ⬜ | ✅ R02 `pit=true` 已实现（`conditional.py`：逐时点滚动分位 + `release_ts≤as_of` 过滤）；✅ SC90 方法层已实现；⬜ 全局 PIT/release_ts 能力（D-J30）未接线，滚动窗口本身不能替代发布日期与修订处理 |
| 缺口/陈旧度披露 | S02 | 所有能力 `quality` | ✅ 信封字段已有 |

#### 0.2.2 数据 ↔ 价格相关性

| 子问题 | 方法 ID | 能力 ID | 实现状态 | 门禁 |
|---|---|---|---|---|
| 同期相关（Pearson/Spearman/Kendall/滚动） | M01–M04 | D-E05 🟡 | 方法已实现；M01/M02/M04 已接双序列子集，M03 未纳入 manifest | ≥60 对齐点 |
| 相关矩阵 TopK / 平均相关度 | M05–M07 | D-E05 🟡 | ✅ 方法已实现（`correlation.py`）；⬜ 多资产矩阵 TopK 能力未接线 | 多资产对齐，≥60 点 |
| 偏相关（剔除共同趋势） | M08 | **未登记** | ✅ 方法层已实现（`correlation.py`）；⬜ 能力未接线 | ≥120 点 |
| 领先滞后 CCF / 最优 lag | M11–M12、T03–T04 | D-E06 ✅ | ✅ 方法与双序列能力已接线（`correlation.py` / `timeseries.py`） | ≥120 点 |
| 相关稳定性 / 突变 | M24–M25 | D-E11 ✅ | ✅ 方法与能力已接线（`correlation.py`） | 滚动窗口 ≥3 |
| 跨资产同向率 | M23、C18 | D-E11 🟡 | M23 已接能力；C18 方法已实现（`seasonal.py`）但未纳入 manifest | 多资产对齐 |
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
| 节日/事件前后 | C11 + F19–F23 | D-E04 ⬜ | ❌ C11 缺交易日历（登记不可用）；✅ F19/F22/F23 方法层已实现（`timeseries.py`），⬜ 能力未接线 | 事件表 + ≥3 年 |
| 季节强度 / STL | C13、T10、SC91 | D-J02 🟡 | ✅ C13 已实现（ANOVA 式组间方差比）；✅ T10/STL 与 SC91 方法层已实现（`timeseries.py`/`research_sc_b.py`），⬜ 能力未接线 | ≥3 年且 ≥2 周期 |
| 主周期 / 频谱 | T25–T26、SC39、SC41 | D-J05 ⬜ | ✅ T25–T26 方法层已实现（`timeseries.py`，FFT/DFT）；⬜ 能力未接线 | ≥2 个完整周期 |
| 周期失效（变点） | T22–T23、SC49–SC51 | D-J04 🟡 | ✅ T22 CUSUM、T23 PELT 近似与 SC49–SC51 方法层已实现（`timeseries.py`/`research_sc_b.py`），⬜ 能力出口未接线 | ≥3 年 |
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
| 动量 / ROC / 动量排序 | F14–F16 | D-G08 ⬜（12-1 动量） | ✅ F14–F16 方法层已实现（`timeseries.py`）；⬜ 能力未接线 |
| 波动聚集 | T17–T19、F13 | D-G14 🟡（EWMA） | ✅ 方法层（`timeseries.py`） |
| 惯性强度（方差比） | T14 | D-E13 ✅ | ✅ 已交付（场景包 + `timeseries.py::t14_variance_ratio`） |

> 区分：**惯性**看「符号是否延续」（F17/F18/ACF），**延续性**看「序列是否长记忆」（T13/T14/T20）。两者不能互相替代。

#### 0.2.5 趋势延续性

| 子问题 | 方法 ID | 能力 ID | 实现状态 |
|---|---|---|---|
| 斜率 + 显著性 | T08–T09 | D-B08 🟡 / D-E13 ✅ | 场景包已交付（无 HAC） |
| Hurst 长记忆 | T13 | D-E13 ✅ | 已交付（n<2000 标 low） |
| AR(1) 半衰期 | T20–T21 | D-E13 ✅ | 已交付 |
| IC 衰减（重叠 + 相位） | B13–B15 | D-E13 ✅ / D-G19 🟡（方法层已实现） | 场景包已交付；`conditional.py` |
| 方向态转移矩阵 | B04、B07–B09 | D-E07 ✅（D-E13 内含方向态） | ✅ 方法与能力已接线（`inference.py` / `capabilities/stats.py`） |
| 单资产状态→历史同状态前瞻分布 | B02/B05 + R01/R02 | T0.5 ✅（S3→S4，经 D-E02 出口交付） | ✅ R02 `pit=true` + A8 场景编排（`persistence/profile.py::conditional_distribution`）+ D-E02 能力出口与前端分派均已接线；首版 h=1、4 桶（样本不足自动降 2 桶并披露），禁止全样本分位边界 |
| Newey-West / Deflated Sharpe | Q06/Q07（SC 组） | D-G22 ⬜ | ✅ 方法层已实现（`research_pq.py`）；⬜ 能力未接线。h>1 重叠前瞻收益在显著性推断前为硬前置 |

#### 0.2.6 单维 → 多维

| 子问题 | 方法 ID | 能力 ID | 实现状态 |
|---|---|---|---|
| 等宽/等频/阈值分箱 | B01–B03 | D-E07 ✅ | ✅ 方法与状态转移能力已接线；分箱本身由方法注册表提供 |
| 二维交叉表 | B06 | D-E07 🟡 | ✅ 方法已实现（`inference.py::b06_crosstab`），未纳入当前 manifest |
| 条件分布（状态 → 前瞻） | B05、B10 + R01/R02/R08 | D-E14 ⬜ | 🟡 方法层可用（R02 `pit=true` 已实现）；场景编排、能力出口与样本纵深未闭环 |
| 降维（PCA/聚类） | M19–M22、SC31–SC38 | D-J22 ⬜ | ✅ 方法层已实现（`correlation.py`/`research_sc_a.py`）；⬜ 能力未接线 |
| 相关网络 / 社区 | M21、SC71–SC72 | D-J24 ⬜ | ✅ 方法层已实现（`correlation.py`/`research_sc_b.py`）；⬜ 能力未接线 |
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

> **v2.8 方法层口径**：方法库 387 条已登记、**386 条已实现**（仅 C11 缺交易日历不可用），audit 386/386 PASS。因此下表中的 `⬜`/`🟡` 只表示**能力尚未接线或编排未闭环**，不再表示“方法缺失”；凡状态列写明“方法层已实现”的，方法可直接 `run()` 调用，但能力出口仍需按 `capability_manifest.yaml` 接线。

### 2.1 A 组：库内时序衍生（16 项，零新增采集）

数据源统一为 `19-DAL mm_metrics`；**行数、序列数与纵深事实唯一来源为 [METHOD_LIBRARY §15](./METHOD_LIBRARY.md)**，本文不另立实测口径。

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
| D-B08 | 趋势斜率 | candles(close) | 线性回归斜率（标准化） | `slope, r2, window` | technical_indicator | deterministic | P2 | 🟡 |
| D-B09 | 距 ATH 回撤 | candles(全历史/缓存) | `price/max-1` | `drawdown_from_ath, ath, ath_ts` | technical_indicator | deterministic | P2 | ⬜ |

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

### 2.4 E 组：统计关系与价格表达（14 项，方法库驱动）

> 方法定义见 [METHOD_LIBRARY.md](./METHOD_LIBRARY.md)（238 方法 / 18 关系原语）。本组是「数据状态 → 价格表现」的固定统计出口，禁用因果与预测措辞。

| ID | 能力 | 依赖方法（方法库） | 数据前提 | L1 意图 | 优先级 | 状态 |
|---|---|---|---|---|---|---|
| D-E01 | 条件收益统计 | B02/B05 + F01 + H01 | 因子+价格 ≥250 点 | conditional_return | P2 | 🟡 方法已实现（`l1agg/methods/conditional.py`），待能力层接线 |
| D-E02 | 分位→前瞻收益 | S25 + R02 | 序列 ≥250 点；T0.5 另需每桶非重叠 n≥250 | metric_percentile | P1 | ✅ 已接线（manifest `I30/R02` + `capabilities/stats.py::percentile_forward` + 前端 `exec_stat_query` 分位 cue 分支，v2.9）；R02 `pit=false/pit=true` 双口径，A8/T0.5 经此出口交付（h=1，含 4→2 桶降级披露） |
| D-E03 | 季节性/日历效应 | C01–C04, C05, C07, C09, C12–C15 | 日收益 ≥60 天（**仅够星期/月内日**；月份效应需 ≥5 年，见 §0.3） | seasonality_query | P1 | ✅ 能力层已接线（`capabilities/stats.py::seasonality`，`seasonal.py` 17 方法） |
| D-E04 | 事件研究窗 | F19–F23, H01 | 事件表 + 价格 | event_study | P2 | ⬜ |
| D-E05 | 相关矩阵 TopK | M01–M07 | 多资产对齐 ≥60 点 | correlation_query | P2 | 🟡 M01/M02/M04/M23 双序列子集已接线；M05–M07 方法已实现，矩阵 TopK 出口未接 |
| D-E06 | 领先滞后 | T03–T04, M11–M12 | 双序列 ≥120 点 | correlation_query | P2 | ✅ 能力层已接线（`capabilities/stats.py::correlation`，n≥120 才出 CCF） |
| D-E07 | 状态转移 | B02, B04, B07–B09 | 状态序列 ≥100 点 | state_transition | P2 | ✅ 能力层已接线（`capabilities/stats.py::state_transition`） |
| D-E08 | 分箱单调性/IC | B11–B15 | 因子+前瞻收益 ≥250 点 | conditional_return | P2 | ✅ 能力层已接线（`capabilities/stats.py::conditional_ic`） |
| D-E09 | 计数与共现 | B17 + R09/R10 | 事件序列 | metric_series | P1 | 🟡 B17/R09/R10 方法层已实现（`inference.py`），事件表仍薄（`mm_events` 16 行） |
| D-E10 | 回撤画像 | D20–D21, F09–F10 | 价格 ≥250 点 | drawdown_query | P1 | ✅ 能力层已接线（`capabilities/stats.py::drawdown`，样本不足降 partial） |
| D-E11 | 跨资产同向率/相关突变 | M23–M25, C18 | 多资产对齐 ≥60 点 | cross_check | P2 | 🟡 M23/M24/M25 已接线；C18 方法已实现但未纳入 manifest |
| D-E12 | 时空对齐切片 | R18 | 多资产同日数据 | cross_check | P2 | ⬜ |
| **D-E13** | **趋势延续性画像（场景包）** | T13 + T14 + T20/T21 + F18 + B07/B08 + T08/T09 + B13–B15 | 日频价格 ≥250 点（当前纵深见 METHOD_LIBRARY §15） | conditional_return（子集） | **P0** | ✅ 已交付（2026-11-14，27 用例） |
| **D-E14** | **相关状态条件分布（场景包）** | D-E05/D-E06/D-E11 的状态特征 + R01/R02/R08 | 多资产对齐 + **每桶非重叠 ≥250** | correlation_query 扩展 | P2 | ⬜（T2；方法层可用（R02 `pit=true` 已实现），场景出口与样本纵深未完成，依赖 T-1 扩样本） |

> **D-E13/D-E14 是场景编排，不新增方法 ID**：D-E13 = D-E07（状态转移）+ D-E08（分箱/IC）+ T 组方法的固定出口，一次调用输出「7 个度量 + 一句话」；D-E14 是「相关状态 → 前瞻分布」的条件化版本。实现、门禁与 T/S 映射见 [SPEC-54-延续性统计分析模块.md](../SPEC-54-延续性统计分析模块.md) 与 [SPEC-54-L1 §3.5](../SPEC-54-L1架构能力聚合层.md)。
>
> **T0.5 也不新增能力 ID**：它位于 S3→S4，复用 D-E02 的 R02 与 D-E13 的自身状态，首版只做 h=1、4 个 PIT 滚动分位桶；每桶非重叠 n≥250，不足按场景包降为 2 桶并披露有效 n。T0.5 已于 v2.9 经 D-E02 出口交付（A8 编排 + 前端分派），不得以全样本分位结果冒充交付。

**硬前提**：E 组价格腿已闭环，当前瓶颈转为**因子池纵深与 PIT 数据契约**（实测事实见 METHOD_LIBRARY §15）。D-E01/D-E02/D-E05/D-E08/D-E11 的完整登记范围仍受对齐样本与能力接线限制；D-E13 只依赖价格，不受跨资产因子池限制。

**方法层先行（v2.2）**：S3 批 22 方法已在 `l1agg/methods/conditional.py` 落地并通过 audit（当时 45/45 PASS；`docs/method_audit.json` 现为全量 386 方法产物）：分布 S11/S25/S26、收益风险 F01–F06、分箱 B01–B03、条件/分组 B05/B11/B12/B16、IC B13–B15、检验 H01、表达 R01/R02。门禁已内置（分布/收益 `min_n=30`、条件/IC/分组 `min_n=250`，不足即 `insufficient_samples`），数据回填完成后只需补能力层接线（scope + 意图 + 执行器），不再改方法口径。

**方法层先行（v2.3，统计学注册库全量补全）**：S6 批 62 方法落地——`descriptive.py`（S 组 26 + D 组 22）、`timeseries.py`（T 组 21 + F 组 12）、`inference.py`（H 组 13 + B 组 8 + M 组 2 + R 组 6）。注册表累计 **154 方法**，`method_audit.py` 全 PASS，`tests` 349 例全绿。当时跳过需要 statsmodels/scipy 拟合、FFT 或外部数据的 T05/T06/T10/T18/T23/T25/T26、D14/D15（v1.11 已全部补齐实现）。口径冻结见 [METHOD_LIBRARY §16](./METHOD_LIBRARY.md)。

> **当前计数（v2.8，勿再引用 154 为总量）**：注册表 `REGISTRY` 实际登记 **387 条 = 核心 238 + 调研族 149**；其中 `implemented=true` **386 条**；`implemented=false` 仅 **1 条**（C11 缺交易日历/节假日表，按纪律登记不可用）。方法库目录同为 **387 条**（X12/O15/P14/Q16/SC92），已无“只有编号占位”的方法。`all_specs(scope=...)` 支持 `core`(238)/`research`(149)/`all`(387)，默认 `core` 以保持 `catalog_total == 238`。
>
> 全量 `method_audit.py --scope all` 已于 2026-11-15 重跑并写入 [docs/method_audit.json](./method_audit.json)：**implemented 386 / passed 386 / failed 0**，`catalog_total=238`、`research_catalog_total=149`、`registered_total=387`；`pytest tests -q` → **666 passed**。上段 154 仅为 v2.3 时点记录，现已被完全包含。

**能力层接线（v2.9）**：方法层不再是瓶颈——`l1agg/capabilities/` 已把 E 组 8 个能力接到方法注册表，端到端产出 `CapabilityResult`：

| 文件 | 职责 |
|---|---|
| `capability_manifest.yaml` | 能力 → 意图 / scope / executor / 方法 / `min_n` 的**唯一事实源**（8 条） |
| `l1agg/capabilities/manifest.py` | 加载 + 校验：能力只能绑 `implemented=true` 方法、`capability.min_n ≥ method.min_n`、同一意图 mode 不得混用 |
| `l1agg/capabilities/envelope.py` | 统一信封组装 + 契约守卫（`quality` 只在顶层、partial 必带 `degraded_reason`、`answer` 非空） |
| `l1agg/capabilities/stats.py` | 6 个编排函数：`drawdown` / `seasonality` / `percentile_forward` / `state_transition` / `correlation` / `conditional_ic` + `run_capability(id, **kw)` 调度 |
| `contracts/capability_result.schema.json` | JSON Schema（测试用 `jsonschema` 逐条校验输出） |

已登记 8 个可执行出口：D-E02（R02 分位→前瞻收益，A8/T0.5）、D-E03（C 组）、D-E05/D-E06/D-E11（M/T 组）、D-E07（B 组）、D-E08（B 组 IC）、D-E10（D/F 组回撤）。其中 **D-E05 仅双序列子集，D-E11 尚未绑定 C18**，不能据此宣称登记范围全部完成。**尚未接线**：D-E01（缺因子池纵深）、D-E04（缺事件表）、D-E09（事件表薄）、D-E12（需多资产同日切片）、D-E14（场景编排与样本纵深未闭环）。

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
| D-G14 | EWMA 波动/协方差（λ=0.94/0.97） | D1 | P1 | 🟡 波动腿已实现（`timeseries.py::t19_ewma_vol`）；✅ EWMA 波动/协方差方法层已实现（`research_pq.py::P07`），⬜ 协方差能力未接线 |
| D-G15 | PCA 风险分解 | D3 | P3 | ⬜ |
| D-G16 | 组合 VaR / CVaR | D1 | P2 | 🟡 单资产 VaR/CVaR 已实现（`descriptive.py::d17_var`/`d18_cvar`）；✅ 组合层方法已实现（`research_pq.py::P09/P10`），⬜ 能力未接线 |
| D-G17 | 水下曲线 / 回撤画像 | D1 | P1 | ✅ D20/D21/F09/F10/R11 已实现，并经 D-E10 接线（`capabilities/stats.py::drawdown`） |
| D-G18 | Brinson 归因 | D1 | P3 | ⬜ |
| D-G19 | IC / ICIR / 衰减表 | D2 | P2 | ✅ B13–B15（`conditional.py`）与 Q01/Q02/Q03（`research_pq.py`，IC/RankIC、ICIR、IC 衰减）方法层已实现；⬜ 能力未接线 |
| D-G20 | 分位单调性检验 | D2 | P2 | 🟡 B11/B16 已实现（`conditional.py`）；B11 已随 D-E08 接线，B16 分组统计尚未接入完整分位组合出口 |
| D-G21 | Fama-MacBeth 横截面回归 | D3 | P3 | ⬜ |
| D-G22 | Deflated Sharpe / Newey-West t | D2 | P3 | ⬜ |
| D-G23 | 事件窗 CAR + Patell/BMP | D2 | P2 | 🟡 F20/F21（AR/CAR）与 F19/F22/F23 已实现；✅ Patell/BMP 方法已实现（`research_pq.py::Q10/Q11`），⬜ 事件表与能力未接线 |
| D-G24 | 因子拥挤度 | D2 | P3 | ⬜ |
| D-G25 | 尾部相关 | D2 | P2 | ⬜ |

**分层关系**：A/B/C = 数据维度能力；E = 关系表达；**G = 机构统计方法补强**。G 组不改变 L1 定性——仍只输出历史统计与样本量。

### 2.6 J 组：科研统计方法（30 项，调研见 RESEARCH-SCIENTIFIC-METHODS.md）

> 来源：NIST/SEMATECH、CERN/ROOT、US Census X-13、NOAA/NASA、NIH/FDA、OECD、Santa Fe、JHU/WHO 等公开方法。面向「数据化科研」通用场景，不限于金融。

| ID | 能力 | 分级 | 优先级 | 状态 |
|---|---|---|---|---|
| D-J01 | 趋势检验（Mann-Kendall + Sen） | D2 | P2 | ⬜ |
| D-J02 | 季节强度与调整（STL/X-13 风格） | D2 | P2 | 🟡 C13 季节强度已实现（`seasonal.py`，ANOVA 式组间方差比）；✅ T10/STL 与 SC91（X-13 风格分解）方法层已实现，⬜ 能力未接线 |
| D-J03 | 异常点识别（AO/LS/TC） | D1 | P2 | ⬜ |
| D-J04 | 变点检测（CUSUM/PELT/Pettitt） | D2 | P2 | 🟡 T22 CUSUM 已实现（`timeseries.py`）；✅ T23 PELT/Pettitt 与 SC47–SC51 方法层已实现，⬜ 能力出口未接线 |
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
| 统计推断 | h>1 的重叠前瞻收益及趋势显著性推断前必须实现 Newey-West/HAC；未实现前只描述、不作显著性结论。批量关系扫描按「关系对 × lag × window × h」完整搜索族校正并披露 `p_adj` |
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
- 场景包 SPEC = 某类问题的**固定编排**（当前已交付延续性画像 `D-E13`；T0.5/T2 为后续编排，不新增能力 ID）。
- 新增能力流程：本文登记 → SPEC 补契约（如涉及新 scope）→ 实现 + 测试 → 更新状态列并附代码位置。

### 6.1 本版更改（v2.9 D-E02 接线与 T0.5 交付；v2.8 方法层全部落地；v2.7 注册表放开；v2.6 调研对齐）

**v2.9（本版，改动代码 + 文档）**

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
| [METHOD_LIBRARY.md](./METHOD_LIBRARY.md) | v1.12 | v1.12：D-E02 能力出口接线（manifest `I30/R02` + executor + 前端分派），T0.5/A8 经 D-E02 交付；v1.11：核心 66 条 + 调研族 149 条全部实现，注册表 387 全登记、386 已实现（仅 C11 不可用），audit 386/386、测试 666 例；同时保留 v1.10 调研族前缀口径、v1.9 的 R02 `pit=false/pit=true` 双口径、T0.5 合法输入与输出披露、S0–S7 路线映射、S7 可执行子集边界、h>1 HAC 前置 |
| [SPEC-54-L1架构能力聚合层.md](../SPEC-54-L1架构能力聚合层.md) | v1.7 | D-E02 已接线（8 个可执行出口）、T0.5 首版交付；PIT 硬约束、T0.5=S3→S4、S2/S3 方法层与能力出口分层状态、整体路线门禁 |
| [SPEC-54-延续性统计分析模块.md](../SPEC-54-延续性统计分析模块.md) | v1.5 | T0.5/A8 首版经 D-E02 出口交付（h=1 PIT，含降桶降级披露）；R02 `pit=true` 已实现；不改 A1–A7 冻结口径 |
| 三份 RESEARCH 文档 | 保持原文 | 作为调研证据，不改写为实现状态；分别支撑延续性分层、机构研究协议与科研可复现/PIT 校验 |

**整体进度（按登记范围，而非按方法数量）**：

| 路线（成对映射） | 当前状态 | 已交付 | 尚未闭环 |
|---|---|---|---|
| SPEC S1 ↔ 方法 S1 | 🟡 核心底座完成 | `market.candles`、UTC 对齐、前瞻收益、价格回显、日线同锚点 | 前端 11 模块全量历史查询覆盖仍按 SPEC 独立验收，不能由底座完成自动判全绿 |
| SPEC S2 ↔ 方法 S2 | 🟡 方法完成、能力部分接线 | M01–M07/M11–M12/M24–M25 方法；D-E05 双序列子集、D-E06、D-E11 可执行 | D-E05 多资产矩阵 TopK、D-E11 的 C18 及完整四类榜单契约 |
| SPEC S3 ↔ 方法 S3/S6/S7；T0=S3 子集 | 🟡 方法与场景部分交付 | S3 批 22 方法、S6 扩展、8 个 manifest 出口（含 D-E02）；T0/D-E13 已交付；R02 `pit=true` 已实现 | D-E01 出口、MERS 内部计算内核与 S3 全量验收 |
| **T0.5=S3→S4** | ✅ 首版已交付（v2.9） | R02 `pit=true` + A8 编排 + D-E02 出口与前端分派；h=1、4 桶 PIT 滚动分位，样本不足自动降 2 桶并披露 `effective_n/nonoverlap_n` | 真实数据纵深不足时按契约降级；h>1 显著性仍受 Newey-West/HAC 前置约束 |
| SPEC S4 ↔ T2 | ⬜ | 条件分布非点预测的契约已明确 | T-1 扩样本、T1a/T1b、F1–F12 状态特征、1–2 维场景出口；h>1 显著性另受 HAC 阻塞 |
| SPEC S5 ↔ T3及后续 | ⬜ | MERS/Discovery 契约与门禁已设计 | 样本外、walk-forward、BH-FDR、随机负例、注册表与只读推荐/发现出口 |

### 6.3 下一阶段顺序（blocker 驱动）

1. **R02 `pit=true` 与 T0.5 已交付（v2.9）**：`conditional.py::r02_percentile_forward` 双口径 + A8 编排 + D-E02 出口（manifest/executor/前端分派）均已接线；样本不足按场景包降 2 桶并披露 `effective_n/nonoverlap_n`，不输出点预测。
2. **下一关键路径转为 MERS 内核与 S3 全量验收**：D-E02 输出仍需经 MERS（BH-FDR、holdout 同号、随机负例）才可升级为稳定推荐，单出口交付不等于显著性结论。
3. **补齐 S2/S3 登记范围**：完成 D-E05 矩阵 TopK、D-E11 的 C18、D-E01 等出口；四类榜单分别披露搜索空间与 `p_adj`，不得混排。
4. **扩样本后再做 T2**：T-1 由云端唯一生产写入口执行；随后完成 T1a/T1b 与 F1–F12 PIT 特征，再交付 1–2 维 D-E14。任何 h>1 显著性结论必须先有 Newey-West/HAC。
5. **最后开放 S5**：MERS/Discovery 通过 holdout、walk-forward、BH-FDR 和随机负例后，才开放稳定推荐与发现查询。

**文档治理**：见 §0.4；实测数字只在 METHOD_LIBRARY §15 独立维护，其他文档只能引用或保留标注「引自 §15」的决策摘要，执行时按最新快照重算。
