# 54 总技术文档 — 数据 → 统计 → 关系能力地图

- **版本**: v2.64 ｜ **日期**: 2026-11-16 ｜ **状态**: 🟢 总技术文档（v2.64 关闭 L-CHART 四项阻塞：K-02 冻结 B-2A 轴事实映射，K-03 消除阈值双轨，K-06 冻结 `decide→handoff` 的 band/flags 契约，K-11 登记 T1–T4 `chart_specs`；v2.63 完成 **G-IF1 冻结**：新增 §7.10 冻结记录（已冻结 / 转下游 / 图表层禁止假设三类结论），表 A 补齐 7 个漏登 `data` 键与 `quality.is_stale`/`snapshot_at`、修正能力级 `gate` 枚举 4 → 6 值；实测发现并修复契约缺口 A-7——D-E19 输出 `data.lights` 但 schema 关闭 `data` 扩展键且未登记该键（`jsonschema.validate` 实测 `Additional properties are not allowed ('lights' was unexpected)`），已在 schema 增 `data.lights` + `$defs.lights_row`/`lights_axis` 行契约并补回归测试 `test_envelope_validates_against_json_schema`；同批冻结能力块内部字段清单（表 A-1）与 `mm_events.symbols` 聚合口径；v2.62 关闭 L-STAT 统计层：B-58 提交同步完成——本地 commit `ca6c55a3c6`（35 文件，manifest 50 → **93 条**）已推送 `origin/refactor/13-16-merge`，并经云端 `sudo -n -u luke -H git pull --ff-only` 落地到同一 commit，云端 `capability_manifest.yaml` 实测 **93 条 / 93 唯一**，与本地逐字一致；提交前 `pytest tests -q` 全绿 **1314** 条、ruff/black 通过；§7.2 统计层四项完成判定全部满足，可进入 G-IF1 冻结；v2.61 新增 §7.9 真数据覆盖表：本地只读快照 28 个注册资产中 24 个可用（≥250 期），AMD/GEV/SPCX/SKHYNIX 为 0 样本；93 条能力 min_n 档位与资产数闭合，lights 的 250 门槛刚好满足；5 张衍生品明细表为空、`mm_events` 仅有 `symbols` 文本列等口径缺口已登记；v2.60 关闭 K-09/K-10：`envelope.GATE_METHOD` 单一事实源声明方法级 gate 集合（能力级 6 值 + `skipped`/`calculation_failed`/`empty`/`rejected`），执行覆盖测试对 93 场景逐块递归校验；`data` 关闭 `additionalProperties` 并枚举实际使用的 12 个键；K-12 仅开槽 `quality.snapshot_at`，能力层不伪造快照时点；v2.59 关闭 K-01/K-08：`envelope.build()` 统一为能力块补 `gate`（缺省 `ok`，不覆盖既有值），一处收敛全部 93 出口；schema 能力级 `gate` 枚举补 `partial`/`degraded` 并注明方法级另有 `skipped`/`calculation_failed`/`empty`；执行覆盖测试内对 93 个场景逐个 `jsonschema.validate`（此前只校验 12 个手选出口，故 G/J 组缺 `gate` 未被发现）；新增回归测试 `test_every_capability_block_declares_gate`；v2.58 新增 §7「统计层 → 图表输出 → 信号层」串行推进顺序与接口冻结：三张接口表（统计→图表 / 图表→信号 / 信号→回测评估）+ 12 项信号层前置阻塞清单 + G-IF1/G-IF2/G-IF3 三个冻结点；实测发现 G/J 组 39 个出口的能力块缺 `gate`（违反契约，因 schema 校验测试只覆盖 12 个手选出口而未暴露）；v2.57 接入 J 组 24 个科研统计出口（D-J01/03/06/07/08/09/10/11/12/13/14/15/16/17/18/19/20/21/23/25/26/27/28/29，`capabilities/research_stats.py`，全部 `method_binding: compute`），manifest 69 → **93 条**、可执行出口 69 → **93 个**；同批补齐 `datacenter.panel`（21 项）与 `datacenter.spatial_frame`（D-J25）两个 scope 声明，并新增 `tests/test_research_stats.py`（43 passed）替换不被 pytest 收集的 `_smoke_j.py`；v2.56 接入 G 组 15 个机构统计出口（D-G01/02/03/04/05/06/07/10/11/12/13/15/18/21/24，`capabilities/institutional.py`，全部 `method_binding: compute`），manifest 54 → **69 条**、可执行出口 54 → **69 个**；v2.55 新增 D-K01/D-K02 评估层只读出口（manifest 52 → **54 条**）：D-K01 读 `relationship_registry.db` 取 Top3、D-K02 读 `reports/discovery/**` 最近一期候选，均只读不重算；同批落地 `config/discovery_space.yaml` 预注册搜索空间 + `l1agg/discovery.py` 冻结项校验；v2.54 上线 #35 后半句：`dreambuddy-mers.timer` 每日 08:20 CST 跑全量 MERS 网格（29 job / 5,220 单元），`Persistent=true` 补跑漏窗，`--prune-days 90` 只清 `relationship_eval` 历史行、`relationship_state` 永久保留；新增 `RelationshipRegistry.prune_before()` 与回归测试，unit 文件入库 `deploy/systemd/`；v2.53 关闭 §6.4.5 #35 全量真实验收——29 job / 5,220 单元（20 资产 `close_1d` + 9 个宏观/情绪/资金费率指标对齐 BTC 日轴），BH-FDR 后 `gate_pass=1,057`（20.25%），`method_gate` = ok 3,654 / not_applicable 1,566 / **failed 0**，三轮 `gate_pass` 完全一致且每轮内部复跑 `added=0`，连续三轮通过使 `stable=1,057`、其余 4,163 维持 candidate；验收中发现并修复 B11 空分桶 `float(None)` 崩溃（failed 95→0，commit `2b5b8b8a59`），可执行出口保持 **52 个**；v2.52 新增 D-A05 z-score 出口（`capabilities/stats.py::zscore`，复用 S26，`datacenter.percentile` scope 声明落地），可执行出口 51 → **52 个**；v2.51 新增 D-E20 新闻统一出口（L1S-03，`capabilities/news.py`，只读 `social_volume` 观测成统一信封 + 禁用词自检），可执行出口 50 → **51 个**；v2.50 关闭 §6.4.4 数据阻塞表 #32–#34：C11 节前效应落地（节假日由日期轴「工作日缺失」派生，接入 D-E04）、D-G25 尾部相关接线（复用 P13，下行/上行双尾 + 尾部共现样本门禁）、D-J05 周期/频谱接线（T25/T26/C14 + 历史覆盖周期数门禁），可执行出口 48 → **50 个**；v2.49 将 D-E14 二维状态按 Tier B/D 兜底落地：4×4=A（≥4,000 日）/ 3×3=B（≥2,250 日）/ 2×2=D（≥1,000 日），每格非重叠 ≥250，三档均不达标回退一维并披露 `insufficient_2d`，可执行出口保持 **48 个**；v2.48 登记 L1 交易层新增的 D-E15–D-E19 五个能力出口（趋势曲线 / 聚合曲线 / 分组看板 / 资金流向导图 / 四轴五态点亮投影），可执行出口 44 → **48 个**；v2.47 完成前端 D-A 组 14 个及 D-B08/D-B09/D-G08/D-G09 共 18 个 cue 分派，可执行出口保持 **44 个**；v2.46 接入 D-G09 波动率目标换算出口（P02），可执行出口 **44 个**；v2.45 接入 D-G08 12-1 动量出口（F14 窗口切片），可执行出口 **43 个**；v2.44 接入 D-B09 距 ATH 回撤出口（复用 D20/D21），可执行出口 **42 个**；v2.43 接入 D-B08 趋势斜率出口（T08/T09），可执行出口 **41 个**；v2.42 接入 D-A16 稳定币规模增速出口（S16 多窗口），可执行出口 **40 个**；v2.41 接入 D-A15 ETF 净流入滚动和出口（S20 滚动均值 × 窗口），可执行出口 **39 个**；v2.40 接入 D-A13 极端事件频率出口（S11 阈值 + 计数），可执行出口 **38 个**；v2.39 接入 D-A12 领先滞后相关出口（M11/M12），可执行出口 **37 个**；v2.38 接入 D-A11 双序列滚动相关出口（M04），可执行出口 **36 个**；v2.37 接入 D-A10 实际利率出口（S16 派生），可执行出口 **35 个**；v2.36 接入 D-A09 环比出口（S16），可执行出口 **34 个**；v2.35 接入 D-A08 同比出口（S16），可执行出口 **33 个**；v2.34 接入 D-A07 回撤出口（复用 D-E10 的 D20/D21 执行器），可执行出口 **32 个**；v2.33 接入 D-A06 年化波动率出口（F05），可执行出口 **31 个**；v2.32 接入 D-A04 历史分位出口（S25），可执行出口 **30 个**；v2.31 接入 D-A03 CAGR 出口（S19），可执行出口 **29 个**；v2.30 接入 D-A02 变化率出口（S15/S16），可执行出口 **28 个**；v2.29 接入 D-A01 历史序列出口（S25），可执行出口 **27 个**；v2.28 接入 D-J30 PIT/release_ts 全局出口（SC90/R02），可执行出口 **26 个**；v2.27 接入 D-G14 EWMA 波动/协方差出口（P07/T19），可执行出口 **25 个**；v2.26 接入 D-J24 相关网络与社区发现出口（M05/M21/SC71/SC72），可执行出口 **24 个**；v2.25 接入 D-J22 PCA/SVD/因子分析出口（M19/M20/SC31/SC32/SC33），可执行出口 **23 个**；v2.24 接入 D-G20 分位组合与单调性检验出口（B11/B16/Q04），可执行出口 **22 个**；v2.23 接入 D-G19 IC/ICIR/衰减表出口（B13/B14/B15/Q01/Q02/Q03），可执行出口 **21 个**；v2.22 接入 D-G16 组合 VaR/CVaR 出口（D17/D18/P09/P10），可执行出口 **20 个**；v2.21 接入 D-J02 季节强度与调整出口（C13/T10/SC91），可执行出口 **19 个**；v2.20 接入 D-J04 变点检测出口（T22/T23/SC49/SC50/SC51），可执行出口 **18 个**；v2.19 将 B06 二维交叉表纳入 D-E07，输出状态相邻期联合计数底表并与 B07 行归一化转移概率对齐，可执行出口保持 **17 个**；v2.18 接入 D-G23 事件窗均值调整 CAR + Patell/BMP（Q10/Q11），可执行出口 **17 个**；v2.17 接入 D-E14 一维相关状态→h=1/2 前瞻条件分布（R02 PIT 状态轴共享 B05/B10/R01/R08），可执行出口 **16 个**；v2.16 接入 D-E04 事件研究窗（F19/F21/F23）与 D-E09 计数与共现（R09/B17/R10）能力出口，可执行出口 **14 个**，事件数 <30 降级 partial 但保留 CAR/胜率；同步补齐前端 D-A14/D-G22 cue 分派与 D-E14 的 T-1 扩样本（云端 20 资产 / 54,653 行 `close_1d`，1 维 4 桶 @h=1 全部达标）；v2.15 冻结 D-A14/F26 的 `level` 阈值为 A 分位法（分值历史分布 p20/p60/p80 → 极低/低/偏高/高），接入 D-A14 能力出口；v2.14 接入 D-G22 显著性出口（Q06 HAC t + Q07 Deflated Sharpe），解除 h>1 重叠前瞻收益的推断阻塞；v2.13 打通宏观事件历史回填通道，为 D-E04/D-E09 解除「事件表仅 16 行」的数据阻塞；v2.12 接入 D-E12/R18 时空对齐切片；MERS S3 内部固定网格、BH-FDR、状态机与幂等注册表已交付，S5 对外推荐仍未开放；54-L1 测试 **909 通过 / 0 失败**（v2.27 全量回归；v2.16 同时修复既有日期边界测试的时间炸弹），audit **386/386 PASS**、验证覆盖率 **66.15%**；v2.11 接入 D-E11/C18 与 D-E01；v2.10 D-E05 双序列与多资产矩阵 TopK 全接线、D-E06 全 lag BH-FDR、manifest 真实执行覆盖与 audit 验证覆盖报告；v2.9 D-E02 能力出口接线与 T0.5/A8 首版交付；v2.8 方法层全部落地：`REGISTRY` 387 条全登记、`implemented=true` **386**，仅 C11 因缺交易日历不可用；v2.7 注册表放开调研族前缀并完成占位登记；v2.6 调研对齐与路线收口）
- **上游**: `SPEC-54-L1架构能力聚合层.md`（ADR/契约/路线）、`docs/METHOD_LIBRARY.md`（方法 SSoT）
- **下游**: `3.1-FRONTEND/scripts/l1_route_signal.py`（L1 路由）、`34-前端应用训练系统/core/l0_foundation.py`（L0 scope）、`/api/fundamental/**`
- **定位**: 本文是 54 的**总技术文档**——上半部（§0）回答「有哪些问题域、每个问题域用什么方法、现在缺什么」；下半部（§1–§6）是能力登记册（ID/依赖/字段/优先级/状态）。

---

## §0 全景：文档地图 / 六类问题 / 数据可行性 / 治理规则

### 0.1 文档地图（谁是 SSoT）

| 文档 | 角色 | 唯一负责的内容 | 当前版本 |
|---|---|---|---|
| [SPEC-54-L1架构能力聚合层.md](../SPEC-54-L1架构能力聚合层.md) | 架构与契约 | ADR、scope 出入参、门禁、路线（S1–S5）、MERS/Discovery | v1.47 |
| **本文 TECHNICAL_DESIGN.md** | **总技术文档 + 能力登记** | 六类问题地图、四层分工（§0.5）、能力 ID `D-*`、状态列、整体进度（§6.2）、**串行推进顺序与接口冻结（§7）**、**真数据覆盖表（§7.9）**、**L-STAT 收口证据（§7.9-D6）**、**G-IF1 冻结记录（§7.10）** | **v2.64** |
| [METHOD_LIBRARY.md](./METHOD_LIBRARY.md) | 方法 SSoT | 方法 ID（S/D/T/C/I/M/B/F/H/R/X/O/P/Q/SC）、口径冻结（§16）、数据前提（§15） | v1.19 |
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
| 节日/事件前后 | C11 + F19–F23 | D-E04 ✅ | ✅ C11 已实现（`seasonal.py::c11_pre_holiday`）：节假日由日期轴「工作日缺失=节假日」派生（也可显式传 `holidays`），>10 工作日连续缺口按数据缺口排除；✅ 能力出口 `capabilities/stats.py::event_study` 的 `pre_holiday/holidays` 分支（节前样本 <30 降级 `holiday_events_lt_30`）；✅ F19/F22/F23 方法层已实现，✅ 事件历史已云端回填（`mm_events=550`） | 事件表 + ≥3 年 |
| 季节强度 / STL | C13、T10、SC91 | D-J02 ✅ | ✅ 已接线（`capabilities/stats.py::seasonal_adjustment`）：C13 月度 ANOVA 式强度、T10 robust STL 与 SC91 X-13 风格分解原始结果并列输出；完整日期轴必填，历史不足 3 年降级为描述性结论 | 计算 n≥60；结论纵深 ≥3 年且 ≥2 周期 |
| 主周期 / 频谱 | T25–T26、SC39、SC41 | D-J05 ✅ | ✅ 已接线（`capabilities/stats.py::cycle_spectrum`）：T25 主周期 + T26 周期强度，C14 月度一致性并列；历史跨度 <2,920 天降级 `cycles_lt_2` | ≥2 个完整周期 |
| 周期失效（变点） | T22–T23、SC49–SC51 | D-J04 ✅ | ✅ 已接线（`capabilities/stats.py::change_point`）：两种 CUSUM、近似/精确 PELT 与 Pettitt 原始结果及日期映射；SC47 Kalman、SC48 互谱相干不属于本出口 | 方法门禁 n≥60；周期失效解释仍需足够历史纵深 |
| 比特币四年周期（≈1,460 日） | T25 + C14 | D-J05 ✅ | ✅ D-J05 已接线（`cycle_spectrum`，输出 `cycles=span_days/period` 与 `period_to_reference=period/1,460`）；实测 BTC/ETH 3,377 天 = 2.31 周期，9 个资产 ≥2 周期 | **≥2 周期 ≈2,920 日** |

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
| 二维状态（4×4 / 3×3 / 2×2 桶） | 每格非重叠 ≥250（PIT 预热 250 日后计）；均匀标杆 4,250 / 2,500 / 1,250 日 | 20 资产 1,488–3,377 日，联合分桶非均匀（BTC 3×3 最小格仅 223） | 🟡 Tier D 20/20 实测（BTC/UNI/APT 2×2 最小格 682/412/265）；Tier B 当前 0/20；Tier A 0/20 |

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

> **方法层与验证覆盖口径（v2.50 更新）**：方法库 **392 条已登记、392 条已实现**（v2.50 起核心目录 0 占位，C11 已由日期轴派生日历实现），`audit()` 243/243 PASS（核心 `catalog_total=243`）；PASS 只表示已执行检查通过，不代表六类检查全覆盖。当前验证覆盖率以 `audit` 输出为准，缺失检查与不适用检查分别披露。因此下表中的 `⬜`/`🟡` 只表示**能力尚未接线或编排未闭环**，不再表示“方法缺失”；凡状态列写明“方法层已实现”的，方法可直接 `run()` 调用，但能力出口仍需按 `capability_manifest.yaml` 接线。

### 2.1 A 组：库内时序衍生（16 项，零新增采集）

数据源统一为 `19-DAL mm_metrics`；**行数、序列数与纵深事实唯一来源为 [METHOD_LIBRARY §15](./METHOD_LIBRARY.md)**，本文不另立实测口径。

| ID | 能力 | 数据依赖 | 确定性计算 | 输出字段 | L1 意图 | mode | 优先级 | 状态 |
|---|---|---|---|---|---|---|---|---|
| D-A01 | 历史序列 | 单序列 | 区间取点 + 降采样(日/周/月) | `points[], span, unit` | metric_series | deterministic | P0 | ✅ |
| D-A02 | 变化率 | 单序列 | `(v_t/v_{t-n})-1` | `change, change_pct, window` | metric_series | deterministic | P0 | ✅ |
| D-A03 | CAGR | 正指数型序列 | 首末值 + 年数 | `cagr, years` | metric_series | deterministic | P1 | ✅ |
| D-A04 | 历史分位 | 单序列 | 末值在最近 lookback 期的经验分位 | `percentile, value, lookback, sample_n` | metric_percentile | deterministic | P1 | ✅ S25 + `capabilities.stats.percentile_rank`；`lookback` 缺省全样本，窗口 <60 期降级 `short_lookback`，lookback 超可用历史降级 `lookback_truncated` |
| D-A05 | z-score | 单序列 | `(v-μ)/σ`（winsorize p1/p99） | `zscore, mean, std` | metric_percentile | deterministic | P1 | ✅ 已接线（`capabilities/stats.py::zscore`）：复用 S26（p1/p99 截断），输出 `zscore/mean/std/winsorized/lookback/sample_n`；`σ≈0 → z=None` + `zero_variance` 降级（不伪造 0）；`lookback` 缺省全样本、指定须 ≥30；`<30` / 非法 lookback / 日期轴不一致 FAIL-OPEN `empty` |
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
| D-E04 | 事件研究窗 | C11, F19–F23, H01 | 事件表（**已回填入库 550 行**）+ 价格 ≥250 点；节前效应需交易日完整的日期轴 | event_study | P2 | ✅ 已接线（`capabilities/stats.py::event_study`）：事件日对齐到价格轴（取首个不早于事件日的交易日）；F19 事件窗 CAR + F23 事件后分布 + F21 末段 CAR；事件数 <30 降级 partial（`events_lt_30`）但保留数值；`pre_holiday=True`/传 `holidays` 走 C11 节前效应分支（日历由日期轴派生，节前样本 <30 降级 `holiday_events_lt_30`，无工作日缺口 FAIL-OPEN 为 empty） |
| D-E05 | 相关矩阵 TopK | M01–M07 | 多资产对齐 ≥60 点 | correlation_query | P2 | ✅ 双序列 M01–M04/M23 与矩阵 M05–M07 均已接线；逐对 paired complete-case，TopK 披露 BH-FDR |
| D-E06 | 领先滞后 | T03–T04, M11–M12 | 双序列 ≥120 点 | correlation_query | P2 | ✅ M11/M12 主推断覆盖完整 lag 搜索空间并做 BH-FDR；T03/T04 仅保留 legacy 描述 |
| D-E07 | 状态转移 | B02, B06–B09 | 状态序列 ≥100 点 | state_transition | P2 | ✅ B02 等频分位分箱；B06 输出相邻状态联合计数，B07 行归一化为转移概率，B08/B09 输出稳态与停留期；B04 不属于当前 executor |
| D-E08 | 分箱单调性/IC | B11/B13/B14 | 已对齐因子+前瞻收益，总配对样本 ≥250 点 | conditional_return | P2 | ✅ `conditional_ic` 逐行配对；min_n=250 是总样本门禁而非每桶门禁；B15 的 prices/IC decay 入口归 D-E13/D-G19 |
| D-E09 | 计数与共现 | B17 + R09/R10 | 事件序列（**已回填入库 550 行**） | metric_series | P1 | ✅ 已接线（`capabilities/stats.py::count_series`）：`values` 走 R09 涨跌次数，`pairs` 走 B17 共现计数 + R10 一句文案；对齐点 <3 FAIL-OPEN 为 empty |
| D-E10 | 回撤画像 | D20–D21 | 价格 ≥250 点 | drawdown_query | P1 | ✅ 能力层已接线；F09/F10 为同口径库内别名，不重复执行 |
| D-E11 | 跨资产同向率/相关突变 | M23–M25, C18 | 多资产对齐 ≥60 点 | cross_check | P2 | ✅ M23/M24/M25/C18 均已接线；dates 与双收益序列按原始行号同步过滤，无 dates 时不执行 C18 |
| D-E12 | 时空对齐切片 | R18 | 多资产同日数据 | cross_check | P2 | ✅ `capabilities/stats.py::alignment_slice` 已接线；样本不足与空窗口显式降级 |
| **D-E13** | **趋势延续性画像（场景包）** | T13 + T14 + T20/T21 + F18 + B07/B08 + T08/T09 + B13–B15 | 日频价格 ≥250 点（当前纵深见 METHOD_LIBRARY §15） | conditional_return（子集） | **P0** | ✅ 已交付（2026-11-14，27 用例） |
| **D-E14** | **相关状态条件分布（场景包）** | 一/二维相关状态 + B05/B10/R01/R02/R08 | 对齐样本 + **每桶/每格非重叠 ≥250** | conditional_distribution | P2 | ✅ 一维首版（2026-11-15）+ 二维 Tier 阶梯（2026-11-15，`capabilities/stats.py::conditional_distribution`、`methods/conditional.py::r02_percentile_forward`）：一维 R02 PIT 4 桶输出 h=1/2，主期限不足降 2 桶；二维传 `factor2` 走 4×4=A / 3×3=B / 2×2=D 阶梯（每格非重叠 ≥250，按 PIT 预热 250 日后的可用样本计；均匀假设的标杆为 ≥4,250/2,500/1,250 日，实测联合分桶聚集更严，当前 20 资产均落 Tier D）；三档均不达标回退一维并披露 `insufficient_2d`；`tier/cells/buckets_per_axis/min_cell_nonoverlap_n/tier_attempts` 显式返回，弱后续期限单独降级，h>1 不输出朴素 t/p |
| D-E15 | 趋势曲线/多窗口斜率 | I02, T08, I32, I37 | 价格 ≥250 点 | trend_query | P2 | ✅ 已接线（`capabilities/stats.py::trend`）：EMA(12/26/50) 平滑 + 多窗口对数价格斜率(20/60/120/250) + ADX14，可选 I37 Kalman 局部线性趋势；对外只给统计事实 |
| D-E16 | 多成员加权聚合曲线 | S16 | 多资产同日 ≥60 点 | trend_query | P2 | ✅ 已接线（`capabilities/stats.py::aggregate_curve`）：成员先按自身首日 rebase 再按 `chart_weights` 加权，缺口不向前填充，逐点输出 `coverage_ratio/partial_members`；纯聚合展示，不含交易方向 |
| D-E17 | 五类分组看板 | S16, S25, M01, I32 | 跨资产公共日期轴 ≥60 点 | cross_check | P2 | ✅ 已接线（`capabilities/stats.py::class_board`）：`ret_60` 与 D-E12 同口径，组内按 `ret_60` 降序，`lit_n/warm_n` 直接消费 D-E19 计数（零重算）；样本低于 per-anchor 质量门时标 `degraded_reason` 并禁止点亮 |
| D-E18 | 资金流向导图 | M01, M02 | 多资产对齐 ≥60 点 | data_insight | P2 | ✅ 已接线（`capabilities/stats.py::flow_graph`）：ETF 净流入按滚动窗口 z-score 转 flow 边，无 flow 数据时降级 corr-only 且绝不伪造边；边严格 5 键 `src/dst/kind/weight/p_adj` |
| D-E19 | 四轴五态点亮投影 | I37, I36（cycle 轴取 I39 外部归一值） | per-anchor 250（代币化）/ 500 | trend_query | P2 | ✅ 已接线（`capabilities/stats.py::lights`）：轴强度 = \|轴值\|/轴权重（零重算），`lit/warm` 阈值默认 p70/p40 且未标定时显式打标；展示层不重算统计量 |
| D-E20 | 新闻统一出口 | S01, S03 | ≥2 日观测 | trend_query | P1 | ✅ 已接线（`capabilities/news.py::news_digest`）：只读 `mm_metrics.social_volume` 的 `news_count_24h`/`social_volume` 日频观测成统一信封（L1S-03），零重算、不做情绪打分；`scan_forbidden` 自检禁用词（看涨/看跌/建议/目标价/多头/空头/推荐），命中即抛 `ValueError`；库中无新闻条目表，不编造标题/正文/链接；窗口内观测 <2 天 → `empty`，新闻条数部分缺失 → `partial` + `news_metric_partial` |

> **D-E13/D-E14 是场景编排，不新增方法 ID**：D-E13 = D-E07（状态转移）+ D-E08（分箱/IC）+ T 组方法的固定出口，一次调用输出「7 个度量 + 一句话」；D-E14 是「相关状态 → 前瞻分布」的条件化版本。实现、门禁与 T/S 映射见 [SPEC-54-延续性统计分析模块.md](../SPEC-54-延续性统计分析模块.md) 与 [SPEC-54-L1 §3.5](../SPEC-54-L1架构能力聚合层.md)。
>
> **T0.5 也不新增能力 ID**：它位于 S3→S4，复用 D-E02 的 R02 与 D-E13 的自身状态，首版只做 h=1、4 个 PIT 滚动分位桶；每桶非重叠 n≥250，不足按场景包降为 2 桶并披露有效 n。T0.5 已于 v2.9 经 D-E02 出口交付（A8 编排 + 前端分派），不得以全样本分位结果冒充交付。

**硬前提**：E 组价格腿已闭环，当前瓶颈转为**因子池纵深与 PIT 数据契约**（实测事实见 METHOD_LIBRARY §15）。D-E01/D-E02/D-E05/D-E08/D-E11 的能力接线已完成，实际可用性仍受对齐样本限制；D-E13 只依赖价格，不受跨资产因子池限制。

**方法层先行（v2.2）**：S3 批 22 方法已在 `l1agg/methods/conditional.py` 落地并通过 audit（当时 45/45 PASS；`docs/method_audit.json` 现为全量 386 方法产物）：分布 S11/S25/S26、收益风险 F01–F06、分箱 B01–B03、条件/分组 B05/B11/B12/B16、IC B13–B15、检验 H01、表达 R01/R02。门禁已内置（分布/收益 `min_n=30`、条件/IC/分组 `min_n=250`，不足即 `insufficient_samples`），数据回填完成后只需补能力层接线（scope + 意图 + 执行器），不再改方法口径。

**方法层先行（v2.3，统计学注册库全量补全）**：S6 批 62 方法落地——`descriptive.py`（S 组 26 + D 组 22）、`timeseries.py`（T 组 21 + F 组 12）、`inference.py`（H 组 13 + B 组 8 + M 组 2 + R 组 6）。注册表累计 **154 方法**，`method_audit.py` 全 PASS，`tests` 349 例全绿。当时跳过需要 statsmodels/scipy 拟合、FFT 或外部数据的 T05/T06/T10/T18/T23/T25/T26、D14/D15（v1.11 已全部补齐实现）。口径冻结见 [METHOD_LIBRARY §16](./METHOD_LIBRARY.md)。

> **当前计数（v2.50，勿再引用 154 为总量）**：注册表 `REGISTRY` 实际登记 **392 条 = 核心 243 + 调研族 149**；其中 `implemented=true` **392 条**（v2.50 落地 C11 后核心目录已无占位方法）；`implemented=false` **0 条**。核心 243 含 v2.25 前已落地的 I35–I39 美联储方法。方法库目录同为 **392 条**（X12/O15/P14/Q16/SC92），已无“只有编号占位”的方法。`all_specs(scope=...)` 支持 `core`(243)/`research`(149)/`all`(392)，默认 `core` 以保持 `catalog_total == 243`。
>
> 全量 `method_audit.py --scope all` 已于 2026-11-15 13:21 UTC 重跑并写入 [docs/method_audit.json](./method_audit.json)：**implemented 392 / passed 392 / failed 0**，`catalog_total=243`、`research_catalog_total=149`、`registered_total=392`。`l1agg.eval.harness.audit()` 同步为 **243/243 PASS**；六类检查共 **1,458** 项，真实执行 715、不适用 476、缺失 267，**适用检查覆盖率 72.81%**（meta 243/243、gate 243/243、determinism 117/243、synthetic 104/243、null 3/5 适用、reference 5/5 适用）。PASS 不等于完整验证覆盖；上段 154 仅为 v2.3 时点记录，现已被完全包含。

**能力层接线（v2.57 补 J 组 24 个科研统计出口；v2.56 补 G 组 15 个机构统计出口；v2.53 补 D-K01/D-K02 评估层只读出口；v2.52 补 D-A05；v2.51 补 D-E20；v2.50 补 D-G25/D-J05 并扩展 D-E04 节前分支；v2.48 补 D-E15～D-E19；v2.46 补 D-G09；v2.45 补 D-G08；v2.44 补 D-B09；v2.43 补 D-B08；v2.42 补 D-A16；v2.41 补 D-A15；v2.40 补 D-A13；v2.39 补 D-A12；v2.38 补 D-A11；v2.37 补 D-A10；v2.36 补 D-A09；v2.35 补 D-A08；v2.34 补 D-A07；v2.33 补 D-A06；v2.32 补 D-A04；v2.31 补 D-A03；v2.30 补 D-A02；v2.29 补 D-A01；v2.28 补 D-J30；v2.27 补 D-G14；v2.26 补 D-J24；v2.25 补 D-J22；v2.24 补 D-G20；v2.23 补 D-G19；v2.22 补 D-G16；v2.21 补 D-J02；v2.20 补 D-J04；v2.19 补 D-E07/B06；v2.18 补 D-G23；v2.17 补 D-E14；v2.16 补 D-E04/D-E09；v2.15 接入 D-A14；v2.14 扩到 G 组）**：`l1agg/capabilities/` 当前共有 **93 个可执行出口**（A 组 D-A01/D-A02/D-A03/D-A04/D-A05/D-A06/D-A07/D-A08/D-A09/D-A10/D-A11/D-A12/D-A13/D-A14/D-A15/D-A16 + B 组 D-B08/D-B09 + E 组 19 个（含 D-E20 新闻统一出口）+ G 组 D-G01/D-G02/D-G03/D-G04/D-G05/D-G06/D-G07/D-G08/D-G09/D-G10/D-G11/D-G12/D-G13/D-G14/D-G15/D-G16/D-G18/D-G19/D-G20/D-G21/D-G22/D-G23/D-G24/D-G25 + J 组 D-J01/D-J02/D-J03/D-J04/D-J05/D-J06/D-J07/D-J08/D-J09/D-J10/D-J11/D-J12/D-J13/D-J14/D-J15/D-J16/D-J17/D-J18/D-J19/D-J20/D-J21/D-J22/D-J23/D-J24/D-J25/D-J26/D-J27/D-J28/D-J29/D-J30 + K 组 D-K01/D-K02），端到端产出 `CapabilityResult`，并对跨条件分支累计的真实方法调用做 manifest 覆盖校验：

| 文件 | 职责 |
|---|---|
| `capability_manifest.yaml` | 能力 → 意图 / scope / executor / 方法 / `min_n` 的**唯一事实源**（93 条） |
| `l1agg/capabilities/manifest.py` | 加载 + 绑定校验 + `validate_execution`：跨条件分支累计真实成功调用，拒绝未绑定调用与声明但从未执行的方法 |
| `l1agg/eval/harness.py` | 六类检查按 `executed/missing/not_applicable` 统计；方法级、检查级与全局覆盖率进入 JSON/CLI 报告，PASS 不再冒充全覆盖 |
| `l1agg/capabilities/envelope.py` | 统一信封组装 + 契约守卫（`quality` 只在顶层、partial 必带 `degraded_reason`、`answer` 非空） |
| `l1agg/capabilities/stats.py` | 87 个编排函数（本文件自实现 48 + 复用 `institutional.py` 15 + 复用 `research_stats.py` 24）：`conditional_return` / `conditional_distribution` / `drawdown`（D-E10 与 D-A07 共用，注入 `capability_id`） / `seasonality` / `percentile_forward` / `state_transition` / `correlation` / `conditional_ic` / `alignment_slice` / `portfolio_risk` / `ic_profile` / `quantile_monotonic` / `hac_significance` / `crowding` / `event_study`（含 D-E04 节前效应 `pre_holiday` 分支） / `event_car_significance` / `seasonal_adjustment` / `change_point` / `tail_dependence` / `cycle_spectrum` / `count_series` / `trend` / `dimension_reduction` / `correlation_network` / `ewma_risk` / `pit_alignment` / `history_series` / `change_rate` / `cagr` / `percentile_rank` / `zscore` / `annualized_volatility` / `yoy_change` / `mom_change` / `real_rate` / `rolling_correlation` / `lead_lag_correlation` / `extreme_frequency` / `etf_flow_rolling` / `stablecoin_growth` / `slope_trend` / `ath_drawdown` / `momentum_12_1` / `vol_target_scale` / `aggregate_curve` / `class_board` / `flow_graph` / `lights` + `run_capability(id, **kw)` 调度 |
| `l1agg/capabilities/eval_exports.py` | 2 个评估层只读出口：`recommend_relationship`（D-K01 读 `relationship_registry.db`）/ `discovery_query`（D-K02 读 `reports/discovery/**`）；只读、不重算、不写库，`method_binding: display` |
| `l1agg/capabilities/institutional.py` | 15 个机构统计出口：`cross_section_profile`（D-G01）/ `group_neutralize`（D-G02）/ `quantile_portfolio`（D-G03）/ `dispersion_breadth`（D-G04）/ `co_movement`（D-G05）/ `factor_exposure`（D-G06）/ `sequence_operators`（D-G07）/ `inverse_volatility_weights`（D-G10）/ `equal_risk_contribution`（D-G11）/ `risk_contribution`（D-G12）/ `covariance_shrinkage`（D-G13）/ `pca_risk_decomposition`（D-G15）/ `brinson_attribution`（D-G18）/ `fama_macbeth`（D-G21）/ `factor_crowding`（D-G24）；一律经 `l1agg.methods.run` 调 X/O/P/Q 族方法，零重算 |
| `l1agg/capabilities/research_stats.py` | 24 个科研统计出口：`trend_test`（D-J01）/ `outlier_scan`（D-J03）/ `smoothing_filter`（D-J06）/ `spectral_envelope`（D-J07）/ `state_space_filter`（D-J08）/ `coherence_analysis`（D-J09）/ `information_measures`（D-J10）/ `transfer_entropy`（D-J11）/ `complexity_measures`（D-J12）/ `long_memory`（D-J13）/ `tail_risk_extreme`（D-J14）/ `measurement_uncertainty`（D-J15）/ `interval_estimate`（D-J16）/ `power_sample_size`（D-J17）/ `equivalence_test`（D-J18）/ `group_comparison`（D-J19）/ `regression_diagnostics`（D-J20）/ `robust_regression`（D-J21）/ `cluster_structure`（D-J23）/ `spatial_autocorrelation`（D-J25）/ `survival_analysis`（D-J26）/ `reliability_metrics`（D-J27）/ `meta_analysis`（D-J28）/ `missing_data_profile`（D-J29）；一律经 `l1agg.methods.run` 调 SC 族方法，`_call` 把 `ValueError`/数值退化收敛为 `insufficient_history`/`calculation_failed` 后 FAIL-OPEN，零重算 |
| `contracts/capability_result.schema.json` | JSON Schema（测试用 `jsonschema` 逐条校验输出） |

93 个出口为：D-A01、D-A02、D-A03、D-A04、D-A05、D-A06、D-A07、D-A08、D-A09、D-A10、D-A11、D-A12、D-A13、D-A14、D-A15、D-A16、D-B08、D-B09、D-E01～D-E12（不含场景包 D-E13）、D-E14、D-E15、D-E16、D-E17、D-E18、D-E19、D-E20、D-G01、D-G02、D-G03、D-G04、D-G05、D-G06、D-G07、D-G08、D-G09、D-G10、D-G11、D-G12、D-G13、D-G14、D-G15、D-G16、D-G18、D-G19、D-G20、D-G21、D-G22、D-G23、D-G24、D-G25、D-J01、D-J02、D-J03、D-J04、D-J05、D-J06、D-J07、D-J08、D-J09、D-J10、D-J11、D-J12、D-J13、D-J14、D-J15、D-J16、D-J17、D-J18、D-J19、D-J20、D-J21、D-J22、D-J23、D-J24、D-J25、D-J26、D-J27、D-J28、D-J29、D-J30、D-K01、D-K02。D-E20 新接新闻统一出口（L1S-03）：只把 `mm_metrics.social_volume` 的 `news_count_24h` / `social_volume` 日频观测按日对齐成统一信封（`capability/intent/answer/data/quality`），零重算、不做情绪打分；`answer` 经 `scan_forbidden` 自检禁用词（看涨/看跌/建议/目标价/多头/空头/推荐），命中即抛 `ValueError`；库中无新闻条目表，故仅出计数与热度摘要，绝不编造标题/正文/链接；窗口内有效观测 <2 天 → `status=empty` 降级，新闻条数部分缺失 → `status=partial` + `news_metric_partial`。D-G09 新接波动率目标换算出口：价格先转日简单收益（数据整形），由 P02 计算窗口内实现年化波动与 `scale = target_vol / realized_vol`（target_vol 默认 0.10、window 默认 20、periods 默认 365），能力层不重算波动；收益样本 <60、`target_vol≤0` 或非数值、`window<2`、`periods<1`、日期长度不一致或含非有限值为空；`window` 超过收益长度时截断并降级 `window_truncated`，实现波动为 0 时降级 `zero_volatility` 且系数记 0.0；系数仅描述样本内目标/实现波动之比，不构成交易建议。D-G08 新接 12-1 动量出口：按「跳过最近 `skip` 期（默认 21）、回溯 `lookback` 期（默认 252）」切片后由 F14 真实执行动量/波动/风险调整动量（能力层只做窗口切片与百分比换算），输出 `momentum_12_1/lookback/skip/vol/risk_adjusted/window_start_ts/window_end_ts/truncated/sample_n`；价格样本 <60、`lookback<2`、`skip<0`、非整数参数、日期长度不一致或含非有限值为空；历史不足 `lookback+skip+1` 时截断 lookback 并降级 `short_history`，窗口起点非正降级 `base_zero`。D-B09 新接距 ATH 回撤出口：复用 D-E10 的 `drawdown` 执行器（D20 回撤画像 + D21 持续期），能力层只做 max/索引取点与别名映射，输出 TD 约定的 `drawdown_from_ath/ath/ath_ts`（分别等于 `current_drawdown/peak_price/peak_ts`）并保留 `mdd/duration_days/recovery_days`；价格样本 <2 或全无效值为空，样本 <250 降级 `insufficient_samples`。D-B08 新接趋势斜率出口：取最近 `window` 期（默认 90，下限 30）由 T08 计算对数价格 OLS 斜率与 R²、T09 计算名义 t/p，输出 `slope/r2/window/t/p/hac_corrected/sample_n`，显式标注 `hac_corrected=false`，t/p 只用于相对比较；样本 <60 降级 `short_window` 但保留结果，样本 <30 或 `window<30` 为 empty。D-A16 新接稳定币规模增速出口：S16 逐窗口真实执行 `x_t/x_{t-w}-1` 并折算百分比，能力层只组装多窗口结果，输出 `growth_{k}d/windows/sample_n`；`windows` 可配（默认 7/30），有效样本 <30 降级 `insufficient_samples` 但保留结果，窗口超出历史降级 `short_history`，基期为 0 降级 `base_zero` 并将该窗口置 None，全部窗口不可算 FAIL-OPEN 为 empty。D-A15 新接净流入滚动和出口：S20 真实执行滚动均值，能力层以「均值 × 窗口长度」算术还原滚动和，不做任何分布估计；`windows` 可配（默认 7/30，输出 `sum_{k}d`），有效样本 <30 降级 `insufficient_samples` 但保留结果，窗口超出历史长度降级 `short_history` 并将该窗口置 None，全部窗口不可算 FAIL-OPEN 为 empty。D-A13 新接极端事件频率出口：未给 `threshold` 时由 S11 分位（`quantile` 默认 0.95，取 pN）给出阈值，计数为纯聚合不引入额外估计量，输出 `days/ratio/threshold/side/quantile/sample_n`；样本 <30 且未提供阈值时阈值不可确定为空，提供阈值时 <30 降级 `insufficient_samples` 但保留计数；`side` 支持 above/below/abs。D-A12 新接领先滞后相关出口：paired complete-case 后由 M11 输出 lag −max_lag…+max_lag（默认 10）的相关/p/BH-FDR q/显著性，M12 输出最优 lag，能力层组装 `corr_by_lag[]` 与 `best_lag/best_corr/best_p_adj`；有效配对 <120 降级 `insufficient_history` 但保留结果，配对 <2、`max_lag<1` 或超过配对样本、日期长度不一致为 empty；结论不自动等于因果或未来可预测。D-A11 新接双序列滚动相关出口：按原始位置 paired complete-case 后由 M04 计算滚动 Pearson 相关（`window` 默认 30），输出 `corr`（最近窗口）/`mean_r`/`window`/`n_windows`/`sample_n`；有效配对 <60 降级 `insufficient_samples` 但保留结果，配对 <2、`window<2` 或超过配对样本、日期长度不一致为 empty。D-A10 新接实际利率出口：名义利率（如 DGS10）减 CPI 同比通胀，通胀唯一由 S16（`k=period`，默认 12）真实执行并折算为百分点，能力层只做差值组合，输出 `real_rate/nominal/inflation/base_ts/period/sample_n`；CPI 基期为 0 时通胀与实际利率均不可计算并降级 `inflation_unavailable`，历史 <2 个完整周期降级 `short_history`；样本不足以覆盖 period、`period<1`、双序列长度不一致、日期长度不一致或含非有限值为空。D-A09 新接环比出口：由 S16 以 `k=1` 计算 `x_t/x_{t-1}-1`，输出 `mom/base_ts/sample_n`；至少 2 个有效点，基期为 0 时 `mom=None` 并降级 `mom_unavailable`；样本 <2 为空。D-A08 新接同比出口：由 S16 计算 `x_t/x_{t-period}-1`（period 默认 12），输出 `yoy/base_ts/period/sample_n`；历史长度 <2×period+1 降级 `short_history`，基期为 0 时 `yoy=None` 并降级 `yoy_unavailable`；样本 ≤period 或 period<1 为空。D-A07 新接回撤出口：与 D-E10 共用 `drawdown` 执行器并由调度层注入 `capability_id`，D20/D21 真实执行，输出 TD 约定的 `drawdown/peak_ts` 并保留 `mdd/current_drawdown/duration_days/drawdown_path`；`prices<2` 为空，样本 <250 期降级 `insufficient_samples`。D-A06 新接年化波动率出口：取最近 `window` 期（缺省全样本）由 F05 计算日简单收益标准差 × √365，输出 `volatility/mean_ret/window/sample_n`；有效样本 <60 期降级 `short_window`，样本 <30 或 `window<30` 为空。D-A04 新接历史分位出口：取最近 `lookback` 期（缺省全样本）由 S25 计算末值经验分位，输出 `percentile/value/lookback/sample_n`；窗口 <60 期降级 `short_lookback`，`lookback` 超过可用历史时降级 `lookback_truncated` 并按可用样本计算；样本 <30 或 `lookback<30` 为空。D-A03 新接 CAGR 出口：首末值 + 年数（有日期轴按日历天数、否则按 n-1 天），跨度不足 1 年降级 `short_span`；起止值非正为空。D-A02 新接区间变化率出口：序列末值与 `window` 期前值比较，S15 输出绝对变化、S16 输出变化率；基期值为 0 时变化率不可用降级 `change_pct_unavailable` 并保留绝对变化。D-A01 新接单序列历史序列出口：日期轴必填且与数值等长，按 `freq` 取日/周/月区间最后观测（同日重复取最后）输出 `points[]/span/unit`，当前历史分位复用 S25；缺失率 >20% 降级 `sparse_series`。D-J30 新接 SC90 PIT 时间校验（`available ≤ used`，支持 ISO 与数值时间戳）与 R02 `pit=true` 前瞻分布：`release_ts`/`used_ts` 缺省视为观测时刻，PIT 违规降级 partial 并披露前视风险，过滤后可见样本不足 PIT 窗口时不产出前瞻分布。D-G14 新接 P07 EWMA 组合协方差（λ 默认 0.94）与 T19 逐资产 EWMA 波动序列：多资产面板按原始行 complete-case 后共享同一矩阵，单资产仅走 T19 且不输出协方差，风险结构只描述样本内统计。D-G16 新接 P09 参数法组合 VaR、P10 历史法组合 VaR/CVaR，并以 D17/D18 并列输出逐资产历史 VaR/CVaR；各资产收益按最小公共长度对齐，权重归一化与统计计算全部由方法层完成。D-G19 新接 B13/B14 与 Q01/Q02 的 IC/RankIC/ICIR、Q03 因子 IC 衰减，以及可选价格输入的 B15 价格动量重叠/非重叠 IC 衰减；Q03 收益轴通过首项补 0、右移已对齐 forward 防止多移一期，缺价格时保留核心五方法结果并显式降级。D-G20 新接 B16 分位组统计、B11 组均值严格单调性与 Q04 分位序号 Spearman 检验；factor/forward 按原始位置 complete-case 后共享同一样本轴，spread 仅作描述性统计而非策略收益。D-J02 新接 C13 月度季节强度、T10 robust STL 与 SC91 X-13 风格分解，原始组件与强度并列输出；日期轴必填，历史不足 3 年降级为描述性结论。D-J04 新接 T22/SC49 两种 CUSUM、T23 近似 PELT、SC50 精确 PELT 与 SC51 Pettitt，并列输出原始结果与断点日期映射；SC47 Kalman 与 SC48 互谱相干不属于本出口。D-G23 新接 Q10 均值调整 CAR 与 Q11 Patell/BMP，价格轴事件下标先转为同日收盘收益下标；事件数 <30 或标准化检验不可用时降级并保留 CAR。D-E14 新接一维相关状态条件分布：R02 PIT 桶标签由 B05/B10/R01/R08 共享，默认 h=1/2、4 桶，主期限不足降 2 桶，弱后续期限单独降级；h>1 不输出朴素 t/p。D-J22 新接 M19 相关阵 PCA、M20 载荷、SC31 sklearn PCA、SC32 SVD 与 SC33 因子分析；多变量面板按原始行 complete-case 后共享同一数据矩阵，仅描述数据结构、不生成交易方向。D-J24 新接 M05 相关矩阵、M21 相关距离层次聚类与 SC71/SC72 网络中心性/社区发现：|ρ|≥threshold 生成无向邻接，图规模低于方法门禁时降级披露，仅描述同期相关关系。D-G25 新接 P13 尾部相关：≥2 资产收益面板按原始行 complete-case 后按横截面均值 ≤q 分位切尾，算样本内两两 Pearson；上行尾用收益符号取反后复用同一方法（`upper_tail_by_sign_flip=true`），输出 `rho_down/rho_up/rho_full/amplification/n_tail`；对齐样本 <60 为空，尾部共现 <30 天降级 `tail_events_lt_30`，只描述同期共跌共涨。D-J05 新接 T25 主周期 + T26 周期强度 + C14 月度一致性：`cycles=span_days/period` 与 `period_to_reference=period/1,460` 显式返回；min_n=60、min_span_days=2920，跨度不足降级 `cycles_lt_2`、缺日期轴降级 `dates_missing`，只描述频谱事实。D-E04 新增 `pre_holiday`/`holidays` 分支：C11 由日期轴「工作日缺失=节假日」派生日历（>10 工作日连续缺口按数据缺口排除），节前样本 <30 降级 `holiday_events_lt_30`，无工作日缺口（7×24/周度）为空。其余出口沿用既有门禁与降级口径；二维 D-E14 已接线（v2.49），各出口实际结论均受样本门禁约束。

### 2.5 G 组：机构统计方法（25 项，调研见 RESEARCH-INSTITUTIONAL-L1-METHODS.md）

> 来源：Bridgewater / BlackRock Aladdin / MSCI Barra / AQR / Man AHL / WorldQuant / JPM RiskMetrics / LSEG 等公开方法论中**可公式化**的部分。只描述，不决策。

| ID | 能力 | 分级 | 优先级 | 状态 |
|---|---|---|---|---|
| D-G01 | 横截面 z-score / rank | D1 | P2 | ✅ 已接线（`capabilities/institutional.py::cross_section_profile`）：X01 横截面 z-score + X02 百分位并列输出，n≥30 |
| D-G02 | 组内中性化（板块/规模） | D1 | P2 | ✅ 已接线（`capabilities/institutional.py::group_neutralize`）：X03 组内去均值，输出残差与组均值，n≥30 |
| D-G03 | 分位组合与多空价差 | D2 | P2 | ✅ 已接线（`capabilities/institutional.py::quantile_portfolio`）：X04 等频分桶 + X05 多空价差与 Welch t，n≥30 |
| D-G04 | 横截面离散度 / 市场宽度 | D1 | P2 | ✅ 已接线（`capabilities/institutional.py::dispersion_breadth`）：X06 离散度 + X07 市场宽度并列输出，n≥30 |
| D-G05 | 同向率矩阵 | D1 | P2 | ✅ 已接线（`capabilities/institutional.py::co_movement`）：X08 横截面同向率，n≥30 |
| D-G06 | 因子暴露 / 特质收益（Barra 简化） | D3 | P3 | ✅ 已接线（`capabilities/institutional.py::factor_exposure`）：X09 横截面因子回归 + X10 特质收益，n≥120；缺 factor 时退化为等权市场代理（口径显式披露） |
| D-G07 | 序列算子族（15 个：delay/delta/ts_rank/decay_linear…） | D1 | P2 | ✅ 已接线（`capabilities/institutional.py::sequence_operators`）：O01–O08/O11–O15 单序列算子 + O09/O10 双序列（提供 `other` 时）；d 缺省 20，n≥120 |
| D-G08 | 固定公式因子（12-1 动量、20 日 ts_rank） | D1 | P1 | ✅ 已接线（`capabilities/stats.py::momentum_12_1`）：F14 在「跳过最近 skip 期、回溯 lookback 期」切片上真实执行动量/波动/风险调整动量，输出 `momentum_12_1/lookback/skip/vol/risk_adjusted/sample_n`；min_n=60，历史不足时截断 lookback 并降级 `short_history`；20 日 ts_rank 属 D-G07 序列算子族，未随本能力接线 |
| D-G09 | 波动率目标换算 | D1 | P1 | ✅ 已接线（`capabilities/stats.py::vol_target_scale`）：价格先转日简单收益（数据整形），由 P02 计算窗口实现年化波动与 `scale = target_vol / realized_vol`；target_vol 默认 0.10、window 默认 20、periods 默认 365；收益样本 <60 为空，window 超长截断降级 `window_truncated`，实现波动为 0 降级 `zero_volatility`；系数仅为样本内比值，不构成交易建议 |
| D-G10 | 逆波动权重 | D1 | P2 | ✅ 已接线（`capabilities/institutional.py::inverse_volatility_weights`）：P03 逆波动权重，n≥60 |
| D-G11 | 等风险贡献权重 | D3 | P3 | ✅ 已接线（`capabilities/institutional.py::equal_risk_contribution`）：P04 ERC 迭代权重与风险贡献极差，n≥60 |
| D-G12 | 风险贡献分解 | D1 | P3 | ✅ 已接线（`capabilities/institutional.py::risk_contribution`）：P05 风险贡献占比与总风险，n≥60 |
| D-G13 | 协方差收缩（Ledoit-Wolf） | D3 | P3 | ✅ 已接线（`capabilities/institutional.py::covariance_shrinkage`）：P06 收缩强度 δ 与收缩后协方差（sklearn/analytic 双后端），n≥60 |
| D-G14 | EWMA 波动/协方差（λ=0.94/0.97） | D1 | P1 | ✅ 已接线（`capabilities/stats.py::ewma_risk`）：P07 EWMA 组合协方差（λ 默认 0.94、init_window 20、年化 365）+ T19 逐资产 EWMA 波动序列并列输出；多资产面板按原始行 complete-case，单资产仅走 T19 且不输出协方差；min_n=60，仅描述样本内风险结构 |
| D-G15 | PCA 风险分解 | D3 | P3 | ✅ 已接线（`capabilities/institutional.py::pca_risk_decomposition`）：P08 主成分方差解释比例 TopK，n≥60 |
| D-G16 | 组合 VaR / CVaR | D1 | P2 | ✅ 已接线（`capabilities/stats.py::portfolio_risk`）：P09 参数法组合 VaR + P10 历史法组合 VaR/CVaR，D17/D18 并列输出逐资产历史 VaR/CVaR；min_n=60，按最小公共长度对齐，损失正数口径 |
| D-G17 | 水下曲线 / 回撤画像 | D1 | P1 | ✅ D20/D21/F09/F10/R11 已实现，并经 D-E10 接线（`capabilities/stats.py::drawdown`） |
| D-G18 | Brinson 归因 | D1 | P3 | ✅ 已接线（`capabilities/institutional.py::brinson_attribution`）：P12 配置/选择/交互/主动收益四分解，n≥60 |
| D-G19 | IC / ICIR / 衰减表 | D2 | P2 | ✅ 已接线（`capabilities/stats.py::ic_profile`）：B13/B14 + Q01/Q02 输出 IC/RankIC/ICIR，Q03 输出因子 IC 衰减，可选 prices 执行 B15 价格动量衰减；min_n=250，Q03 收益轴右移防错配，缺价格降级保留核心结果 |
| D-G20 | 分位单调性检验 | D2 | P2 | ✅ 已接线（`capabilities/stats.py::quantile_monotonic`）：B16 输出各分位组统计与最高减最低 spread，B11 检验组均值严格单调，Q04 输出分位序号与组均值 Spearman rho/p；min_n=250，complete-case 对齐，spread 仅为描述性统计 |
| D-G21 | Fama-MacBeth 横截面回归 | D3 | P3 | ✅ 已接线（`capabilities/institutional.py::fama_macbeth`）：Q05 λ/se/t/期数/标的数，n≥250 期 |
| D-G22 | Deflated Sharpe / Newey-West t | D2 | P3 | ✅ |
| D-G23 | 事件窗 CAR + Patell/BMP | D2 | P2 | ✅ 已接线（2026-11-15，`capabilities/stats.py::event_car_significance`）：Q10 均值调整 CAR + Q11 Patell/BMP；价格轴事件下标转为同日收盘收益下标；事件数 <30 或 Q11 不可用时降级 partial，保留 Q10 CAR |
| D-G24 | 因子拥挤度 | D2 | P3 | ✅ 已接线（`capabilities/institutional.py::factor_crowding`）：P13 下行/全样本相关 + P14 相关稳定性（std_rho/|mean_rho|），n≥60；估值价差需外部估值数据，未提供时显式披露 |
| D-G25 | 尾部相关 | D2 | P2 | ✅ 已接线（2026-11-15，`capabilities/stats.py::tail_dependence`）：P13 横截面均值分位切尾后两两 Pearson（下行尾），上行尾用符号取反复用同一方法；输出 rho_down/rho_up/rho_full/n_tail/amplification；min_n=60，尾部共现 <30 天降级 `tail_events_lt_30` |

**分层关系**：A/B/C = 数据维度能力；E = 关系表达；**G = 机构统计方法补强**。G 组不改变 L1 定性——仍只输出历史统计与样本量。

### 2.6 J 组：科研统计方法（30 项，调研见 RESEARCH-SCIENTIFIC-METHODS.md）

> 来源：NIST/SEMATECH、CERN/ROOT、US Census X-13、NOAA/NASA、NIH/FDA、OECD、Santa Fe、JHU/WHO 等公开方法。面向「数据化科研」通用场景，不限于金融。

| ID | 能力 | 分级 | 优先级 | 状态 |
|---|---|---|---|---|
| D-J01 | 趋势检验（Mann-Kendall + Sen） | D2 | P2 | ✅ 已接线（`capabilities/research_stats.py::trend_test`）：SC52 Mann-Kendall τ/z/p + SC53 Sen 斜率与 CI，n≥30 |
| D-J03 | 异常点识别（AO/LS/TC） | D1 | P2 | ✅ 已接线（`capabilities/research_stats.py::outlier_scan`）：SC92 稳健 z 阈值（`k` 默认 3），输出异常点索引与阈值，n≥30 |
| D-J06 | 小波/滤波平滑（DWT/SG/Butterworth） | D1 | P3 | ✅ 已接线（`capabilities/research_stats.py::smoothing_filter`）：SC44 Savitzky-Golay + SC42 小波能量 + SC45 Butterworth 低通，n≥30 |
| D-J07 | Hilbert 包络/瞬时相位 | D1 | P3 | ✅ 已接线（`capabilities/research_stats.py::spectral_envelope`）：SC46 Hilbert 包络/瞬时相位 + SC42 小波分解层级能量，n≥30 |
| D-J08 | Kalman 状态估计 | D3 | P3 | ✅ 已接线（`capabilities/research_stats.py::state_space_filter`）：SC47 局部水平状态空间`process_var`/`obs_var` 可配，输出滤波状态序列与末状态，n≥30 |
| D-J09 | 互谱相干 | D2 | P3 | ✅ 已接线（`capabilities/research_stats.py::coherence_analysis`）：SC48 互谱相干 + SC43 Welch PSD，输出频率轴/相干谱/峰值频率，n≥30 |
| D-J10 | 熵/互信息/KL 散度 | D2 | P2 | ✅ 已接线（`capabilities/research_stats.py::information_measures`）：SC55 香农熵 + SC56 互信息 + SC58 KL/JS；单序列只跑 SC55，提供 `other` 才出配对量，n≥30 |
| D-J11 | 传递熵 | D2 | P3 | ✅ 已接线（`capabilities/research_stats.py::transfer_entropy`）：SC57 双向传递熵与净流向（`lag` 可配），n≥30 |
| D-J12 | 复杂度（LZ/样本熵/排列熵） | D2 | P2 | ✅ 已接线（`capabilities/research_stats.py::complexity_measures`）：SC59 Lempel-Ziv（归一化 `c` + `c_raw`）+ SC60 样本熵 + SC61 排列熵，n≥30 |
| D-J13 | DFA / Hurst | D2 | P2 | ✅ 已接线（`capabilities/research_stats.py::long_memory`）：SC62 多尺度 DFA 与 Hurst 指数，输出尺度表与 H，n≥30 |
| D-J14 | 极值拟合与重现水平（GEV/GPD） | D3 | P3 | ✅ 已接线（`capabilities/research_stats.py::tail_risk_extreme`）：SC63 GEV + SC64 GPD + SC65 重现水平（`return_period` 默认 10），n≥30 |
| D-J15 | 不确定度合成（GUM） | D1 | P2 | ✅ 已接线（`capabilities/research_stats.py::measurement_uncertainty`）：SC09 合成不确定度 `u_c`（仅当提供 `components`）+ SC11 容忍区间；无分量输入时只出容忍区间并显式披露 `u_c/U` 未计算 |
| D-J16 | 预测/容忍/共形区间 | D2 | P2 | ✅ 已接线（`capabilities/research_stats.py::interval_estimate`）：单序列只跑 SC11 容忍区间；提供 `{x,y}` 时由 SC10 预测区间 + SC12 分割共形区间并列，n≥30 |
| D-J17 | 功效与样本量 | D2 | P3 | ✅ 已接线（`capabilities/research_stats.py::power_sample_size`）：SC01 当前功效 + SC02 目标样本量 `n_star`（`effect_size` 缺省用 mean/sd），n≥30 |
| D-J18 | 等效性检验（TOST） | D2 | P3 | ✅ 已接线（`capabilities/research_stats.py::equivalence_test`）：SC03 TOST 双单侧检验，`bound` 缺省按样本自适应并返回 `equivalent` 布尔，n≥30 |
| D-J19 | ANOVA/ANCOVA/事后比较 | D2 | P2 | ✅ 已接线（`capabilities/research_stats.py::group_comparison`）：SC25 单因素 ANOVA F/p + SC30 Tukey HSD；`groups` 内部展开为扁平多键以通过方法层 `_sample_n` 门禁，每组 ≥30 |
| D-J20 | 回归诊断（VIF/BP/White/DW/Cook） | D2 | P2 | ✅ 已接线（`capabilities/research_stats.py::regression_diagnostics`）：SC20 VIF + SC21 Breusch-Pagan + SC22 White + SC23 Durbin-Watson + SC24 Cook 距离，n≥30 |
| D-J21 | 稳健回归/分位回归 | D3 | P3 | ✅ 已接线（`capabilities/research_stats.py::robust_regression`）：SC17 分位回归（`taus` 默认 0.1/0.5/0.9）+ SC18 Huber 稳健回归，n≥30 |
| D-J23 | 聚类与轮廓系数 | D3 | P3 | ✅ 已接线（`capabilities/research_stats.py::cluster_structure`）：SC36 K-Means + SC37 轮廓系数 + SC38 层次聚类，输出标签与簇诊断，n≥30 |
| D-J25 | 空间自相关/变异函数 | D2 | P3 | ✅ 已接线（`capabilities/research_stats.py::spatial_autocorrelation`）：SC67 Moran's I + SC68 Geary's C + SC69 实验变异函数，`k` 近邻可配，n≥30 |
| D-J26 | 生存分析（KM/log-rank/Cox） | D3 | P3 | ✅ 已接线（`capabilities/research_stats.py::survival_analysis`）：SC73 Kaplan-Meier + SC76 Weibull；提供 `group` 走 SC74 log-rank、提供 `covariate` 走 SC75 Cox，n≥30 |
| D-J27 | 可靠性/控制图（X̄-R/EWMA/CUSUM） | D1 | P3 | ✅ 已接线（`capabilities/research_stats.py::reliability_metrics`）：SC77 MTBF/失效率 + SC78 EWMA/控制限告警（`lam`/`L` 可配），n≥30 |
| D-J28 | Meta 分析与异质性 | D3 | P3 | ✅ 已接线（`capabilities/research_stats.py::meta_analysis`）：SC79 固定效应 + SC80 随机效应 + SC81 异质性 I²/τ² + SC82 漏斗图 + SC83 Trim-and-fill，需 `effects`+`se` |
| D-J29 | 缺失机制与插补 | D3 | P2 | ✅ 已接线（`capabilities/research_stats.py::missing_data_profile`）：SC84 缺失机制 + SC85 KNN 插补 + SC86 马氏离群 + SC87 缺失模式，n≥30 |
| D-J30 | 质量校验（重复/一致性/PIT） | D1 | P1 | ✅ |

**分层关系**：A/B/C = 数据维度；E = 关系表达；G = 机构方法；**J = 科研统计（通用化）**。J 组使 L1 可用于运营、实验、传感器、气候、医学等任意时序数据场景。

### 2.7 K 组：关系评估与发现（2 项，系统级）

> **归属第④层（评估层）出口**：`D-K01/D-K02` 不是新的统计能力，而是 MERS（SPEC §14）与 Discovery（§15）预计算产物的**只读查询出口**，只做「按评分排序/按条件筛选」，不重算任何方法（见 §0.5.3 纪律 2）。
> 实现见 SPEC §14（MERS）与 §15（Discovery）。二者是「选法」子系统，不直接产出统计结论。

| ID | 能力 | 数据来源 | 分级 | 优先级 | 状态 |
|---|---|---|---|---|---|
| D-K01 | 方法推荐（relationship_recommend） | `relationship_registry.db`（只读） | D1（读预计算） | P1 | ✅ 已接线（`capabilities/eval_exports.py::recommend_relationship`，Top3 / RankIC 绝对值排序 / candidate 降级） |
| D-K02 | 发现查询（discovery_query） | `reports/discovery/**`（只读） | D1（读预计算） | P2 | ✅ 已接线（`capabilities/eval_exports.py::discovery_query`，最近一期 / 恒标 candidate / 无候选降级） |

**约束**：只读预计算产物 → 无实时随机性；注册表/报告缺失时回落方法库默认顺序（FAIL-OPEN）。

---

## §3 能力 → L0 scope 映射

| scope | 状态 | 支撑能力 | 数据源 |
|---|---|---|---|
| `datacenter.series` | ✅ 已上线（S0） | D-A01/02/03/06/08/09/13/15/16 | 19 DAL `query_metric_by_time` |
| `datacenter.percentile` | ✅ 已声明（D-A04/D-A05 已落地） | D-A04/05 | 同上（服务端统计） |
| `datacenter.correlation` | ✅ 已声明（D-A11/A12 已落地） | D-A11/12 | 同上（双序列对齐） |
| `datacenter.social_volume` | ✅ 既有（只读） | D-E20 | 同上（`mm_metrics.sub_category='social_volume'` 的 `news_count_24h`/`social_volume` 日频观测） |
| `datacenter.panel` | ✅ 已声明（G 组 14 项 + J 组 7 项已落地） | D-G01/02/03/04/05/06/10/11/12/13/15/18/21/24、D-J19/20/21/23/26/27/29 | 同一数据集的多标的 / 多组观测（横截面与面板口径，服务端统计） |
| `datacenter.spatial_frame` | ✅ 已声明（D-J25 已落地） | D-J25 | 坐标 + 观测值（空间自相关 / 变异函数） |
| `market.candles` | ✅ 已落地（S1，1D/1W/1M 日频派生 + 1H OHLC + 日线 OHLC 合并） | D-A07、D-B00–B09 | `mm_metrics` 日频/小时级（`{symbol}/USDT` high/low） |
| `datacenter.record` | ✅ 既有 | D-A 组当前值 | 18 落库最新记录 |
| `market.ticker` | ✅ 既有 | 实时价/24h 高低 | OKX ticker |
| `yijing.bdsm` / `yijing.bcrm2` | ✅ 既有 | D-C01/02 | 快照 JSON |
| `event.state` / `riskcontrol.trailing` | ✅ 既有 | D-C03/04 | 快照/日志 |
| `evolution.contradiction` / `evolution.snapshot` | ✅ 既有 | D-C05/06 | 演化产物 |
| `registry.relationship_eval` | ✅ 已声明（D-K01 已落地） | D-K01 | `data/relationship_registry.db`（`file:...?mode=ro` 只读） |
| `reports.discovery` | ✅ 已声明（D-K02 已落地） | D-K02 | `reports/discovery/<YYYYMMDD-HHMM>/`（manifest.json + findings.jsonl，只读） |

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
- 场景包 SPEC = 某类问题的**固定编排**（当前已交付延续性画像 `D-E13`、T0.5 与 D-E14 一维首版 + 二维 Tier B/D 阶梯；Tier A 4×4 随样本到 4,000 日自动升档，契约不变）。
- 新增能力流程：本文登记 → SPEC 补契约（如涉及新 scope）→ 实现 + 测试 → 更新状态列并附代码位置。

### 6.1 本版更改（v2.62 L-STAT 收口：B-58 提交同步；v2.61 真数据覆盖表；v2.60 K-09/K-10 契约收口；v2.59 K-01/K-08 契约收口；v2.58 §7 串行推进顺序 + 接口盘点；v2.57 J 组 24 个科研统计出口；v2.56 G 组 15 个机构统计出口；v2.55 D-K01/D-K02 评估层出口 + discovery_space 预注册；v2.54 MERS 每日调度 + 90 天保留；v2.53 MERS S3 全量真实数据验收；v2.52 D-A05 z-score；v2.51 D-E20 新闻统一出口；v2.50 C11 节前效应 + D-G25 尾部相关 + D-J05 周期/频谱；v2.49 D-E14 二维 Tier B/D 兜底；v2.48 L1 交易层 D-E15～D-E19；v2.47 前端 D-A/D-B/D-G cue 分派；v2.46 D-G09 波动率目标换算；v2.45 D-G08 12-1 动量；v2.44 D-B09 距 ATH 回撤；v2.43 D-B08 趋势斜率；v2.42 D-A16 稳定币增速；v2.41 D-A15 ETF 净流入滚动和；v2.40 D-A13 极端事件频率；v2.39 D-A12 领先滞后相关；v2.38 D-A11 双序列滚动相关；v2.37 D-A10 实际利率；v2.36 D-A09 环比；v2.35 D-A08 同比；v2.34 D-A07 回撤；v2.33 D-A06 年化波动率；v2.32 D-A04 历史分位；v2.31 D-A03 CAGR；v2.30 D-A02 变化率；v2.29 D-A01 历史序列；v2.28 D-J30 PIT/release_ts 全局能力；v2.27 D-G14 EWMA 波动/协方差；v2.26 D-J24 相关网络与社区发现；v2.25 D-J22 PCA/SVD/因子分析；v2.24 D-G20 分位组合与单调性检验；v2.23 D-G19 IC/ICIR/衰减表；v2.22 D-G16 组合 VaR/CVaR；v2.21 D-J02 季节强度与调整；v2.20 D-J04 变点检测；v2.19 D-E07/B06 联合计数；v2.18 D-G23 事件窗 CAR + Patell/BMP；v2.17 D-E14 一维条件分布；v2.16 D-E04/D-E09 事件与计数出口；v2.15 D-A14/F26 A 分位法 level；v2.14 D-G22 显著性出口；v2.13 事件历史回填通道；v2.12 D-E12/R18；v2.11 C18/D-E01/MERS；v2.10 配对/推断/执行覆盖；v2.9 D-E02 接线与 T0.5 交付；v2.8 方法层全部落地）

**v2.62（本版，L-STAT 收口：B-58 提交同步）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| 本地提交 | commit `ca6c55a3c6`，35 文件（+9084 / −9037），仅含 `54-L1架构能力聚合层/` | manifest 由云端旧版 50 条升为 **93 条**；不夹带其它模块改动 |
| 推送 | `origin/refactor/13-16-merge`（`65aec47a6e..ca6c55a3c6`） | GitHub 作为唯一可信中转，可审计可回滚 |
| 云端同步 | `sudo -n -u luke -H git -C /home/luke/dreambuddy pull --ff-only` | 云端 HEAD = `ca6c55a3`；`capability_manifest.yaml` 实测 **93 条 / 93 唯一**，与本地一致 |
| 提交门禁 | ruff-lint / black / secret-scan 三个 pre-commit 钩子 | 首轮被拦（ruff 自动修 13 处、black 待格式化 16 文件、8 处需手改）；修完重跑全绿 |
| 回归 | `pytest tests -q`（本地，格式化后复跑） | **1314 条全绿**，退出码 0 |
| L-STAT 判定 | §7.2 / §7.8 第 1 步 | 四项完成判定全部满足 → **统计层收口**，进入 G-IF1 冻结 |

**v2.61（真数据覆盖表 / L-STAT 收口证据）**

| 变更 | 数据 / 本文位置 | 结论 |
|---|---|---|
| 资产级覆盖 | §7.9-A，`19-数据访问层/data/dreambuddy_core.db`（`mode=ro`，2026-11-15 23:32 快照） | 28 个注册资产中 24 个 ≥250 期；AMD/GEV/SPCX/SKHYNIX 为 0 样本（归 B-55 云端回填） |
| 能力档位闭合 | §7.9-B，`capability_manifest.yaml` | 93 条能力 min_n 分布 2/3/13/30/60/100/120/250/500，与 24 个可用资产闭合；250 档 17 条刚好满足 lights `min_rows` |
| 数据域核查 | §7.9-C | candles/panel/mm_metrics/social/PIT 充足；5 张衍生品明细表全空、`mm_fear_greed` 1 行 → 相关能力只能降级 |
| 新口径缺口 | §7.9-D | `mm_events` 只有 `symbols` 文本列（无 `symbol`），标的聚合需先解析，纳入 G-IF1 冻结范围；BTC/ETH/SOL/XAU 仅 1094 期，二维 Tier A 不可达 |
| L-STAT 判定 | §7.2 | 覆盖表 ✅；剩余 B-58 提交同步（云端 manifest 必须同为 93）→ **已由 v2.62 关闭** |

**v2.60（K-09 / K-10 契约收口）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| K-09 方法级 gate 入契约 | `l1agg/capabilities/envelope.py`（`GATE_CAPABILITY` / `GATE_METHOD`） | 方法级取值不再靠隐式约定；能力级 6 值与 schema 枚举同源 |
| K-09 回归校验 | `tests/test_capabilities.py::_nested_gates` + 执行覆盖循环 | 93 个场景逐块递归检查内嵌 gate，越界即失败；另加 `test_nested_method_gates_are_declared` 三例定型 |
| K-10 `data` 闭合 | `contracts/capability_result.schema.json` | 由 `additionalProperties: false` 驱动实测枚举：name/as_of/window_days/source/items/notes/assets 7 个新键 + 既有 5 键，共 12 键 |
| K-12 契约开槽 | schema `quality.snapshot_at` | 只开可选槽位，能力层不填（无快照事实源），待 19-DAL 注入 |
| 验证 | `pytest tests -q` | 全绿，1313 → **1314** 条 |

**v2.59（K-01 / K-08 契约收口）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| K-01 能力块补 `gate` | `l1agg/capabilities/envelope.py::build` | 单点兜底：`data.capabilities[*]` 缺省补 `gate="ok"`，不覆盖既有 `partial`/`degraded`；G/J 组 39 出口一次性收敛，无需逐个函数改 |
| K-08 schema 覆盖 93 出口 | `tests/test_capabilities.py::test_manifest_matches_methods_actually_executed_across_capability_branches` | 执行覆盖循环内逐个 `jsonschema.validate`，与执行覆盖同一套场景，避免第二套输入漂移 |
| **新发现并修复**：`gate` 枚举不完整 | `contracts/capability_result.schema.json` | 实测 D-A04 等 12 处产出 `gate=partial`、3 处 `degraded`，原枚举只有 4 值 → 枚举补 `partial`/`degraded`，并注明方法级另有 `skipped`/`calculation_failed`/`empty` |
| 回归测试 | `tests/test_capabilities.py::test_every_capability_block_declares_gate` | 锁住 `D-G01`/`D-J01`/`D-J20`/`D-A04` 四类代表，防止再次整体遗漏 |
| 验证 | `pytest tests -q` | 全绿（新增 1 条用例；原 1312 → 1313） |

**v2.58（§7 串行推进顺序与接口冻结）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| 推进节奏定稿 | §7.1–§7.2 | 统计层 → 图表输出 → 信号层；**写代码串行、只读调研可并行**；三层各给可判定完成定义（统计层要求云端 manifest 同为 93） |
| 三个接口冻结点 | §7.3 | G-IF1（统计层收口）/ G-IF2（图表层收口）/ G-IF3（信号层开工前），未冻结不得进下一层 |
| 接口表 A：统计层 → 图表层 | §7.4 + `contracts/capability_result.schema.json` | 盘点信封 25 个字段与 `visual` 五种 kind 分支；发现 6 项缺口 |
| 接口表 B：图表层 → 信号层 | §7.5 + `capabilities/lights.py` / `config/direction_rule.yaml` / `handoff.py` | 盘点 `lights[]` 行、`meta`、规则 12 组参数、`FinalDecisionSignal v1.1`；发现 8 项缺口 |
| 接口表 C：信号层 → 回测/评估/22 | §7.6 | 列 8 个交接字段；`trading.db` signal 表 DDL 本轮未逐列核对（标注为缺口） |
| 信号层前置阻塞清单 | §7.7 | K-01…K-12，P0 四项：缺 `gate`（39 出口）/ 轴名错位 / 阈值双轨 / 动态权重开关未开 |
| **实测缺陷（新增）** | 实测 `D-G01`/`D-J01`/`D-J20` block keys | 能力块缺 `gate`，违反 schema `required: ["gate","methods"]`；`tests/test_capabilities.py:3737-3752` 的 schema 校验只覆盖 12 个手选出口，故全绿为假阳性 |

**v2.57（批次 B-23…B-46：J 组 24 个科研统计出口）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| 单序列族 10 项 | `capabilities/research_stats.py`（`trend_test` / `outlier_scan` / `smoothing_filter` / `spectral_envelope` / `state_space_filter` / `complexity_measures` / `long_memory` / `tail_risk_extreme` / `power_sample_size` / `meta_analysis`）、manifest D-J01/D-J03/D-J06/D-J07/D-J08/D-J12/D-J13/D-J14/D-J17/D-J28、§2.7 | 分别复用 SC52+SC53 / SC92 / SC42+SC44+SC45 / SC42+SC46 / SC47 / SC59+SC60+SC61 / SC62 / SC63+SC64+SC65 / SC01+SC02 / SC79–SC83；`min_n=30`，一律经 `l1agg.methods.run` |
| 双序列族 5 项 | `capabilities/research_stats.py`（`coherence_analysis` / `information_measures` / `transfer_entropy` / `interval_estimate` / `equivalence_test`）、manifest D-J09/D-J10/D-J11/D-J16/D-J18、§2.7 | 分别复用 SC48+SC43 / SC55(+SC56+SC58 提供 `other` 时) / SC57 / SC10+SC12（提供 `{x,y}`）或 SC11（单序列）/ SC03；全部可选分支显式披露降级原因 |
| 面板 / 分组族 5 项 | `capabilities/research_stats.py`（`group_comparison` / `regression_diagnostics` / `robust_regression` / `cluster_structure` / `missing_data_profile`）、manifest D-J19/D-J20/D-J21/D-J23/D-J29、§2.7 | 分别复用 SC25+SC30 / SC20–SC24 / SC17+SC18 / SC36–SC38 / SC84–SC87；D-J19 内部把 `groups` 展开成扁平多键，避免方法层 `_sample_n` 把「组数」误判为样本量 |
| 时间 / 空间 / 可靠性族 4 项 | `capabilities/research_stats.py`（`spatial_autocorrelation` / `survival_analysis` / `reliability_metrics` / `measurement_uncertainty`）、manifest D-J25/D-J26/D-J27/D-J15、§2.7 | 分别复用 SC67+SC68+SC69 / SC73+SC76(+SC74/SC75) / SC77+SC78 / SC09+SC11；D-J15 无 `components` 时不伪造 `u_c`，只出 SC11 容忍区间并披露 |
| 门禁与 FAIL-OPEN | `capabilities/research_stats.py::_call`、`_empty` | `ValueError` → `insufficient_history`、数值退化 → `calculation_failed`，一律收敛为 `empty` 信封；短样本不抛异常。D-J19 的 `k_groups` 改取原始 `groups` 长度，避免扁平化后 KeyError |
| 计数同步 | 本文头部 + §2.5 四处 + §2.7 二十四行 + §3 两个 scope 行、母 SPEC | 可执行出口 69 → **93 个**，manifest **93 条**；§2.5 新增 `research_stats.py` 行、`stats.py` 编排函数 63 → 87；§3 补 `datacenter.panel` / `datacenter.spatial_frame` 两行 |
| 测试 | `tests/test_research_stats.py`（43 passed，替换不被 pytest 收集的 `_smoke_j.py`）、`tests/test_capabilities.py` | 覆盖 24 项正向断言、可选分支（J10 无 `other` / J15 无 `components` / J16 单序列 / J26 无 `group`）、11 项短样本 fail-open 参数化、JSON 确定性、`method_binding=compute`、methods 排序去重；执行覆盖新增 24 个 executor 白名单 + 25 条 scenario（J16 两条）+ `research_stats.run_method` 双重 monkeypatch；54-L1 全量 **1312 passed** |

**v2.56（批次 B-08…B-22：G 组 15 个机构统计出口）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| 横截面族 6 项 | `capabilities/institutional.py`（`cross_section_profile` / `group_neutralize` / `quantile_portfolio` / `dispersion_breadth` / `co_movement` / `factor_exposure`）、manifest D-G01…D-G06、§2.7 | 分别复用 X01+X02 / X03 / X04+X05 / X06+X07 / X08 / X09+X10；门禁 n：横截面 30、因子回归 120；缺 `factor` 时 X09 退化为等权市场代理并在 answer 明示 |
| 序列算子 D-G07 | `capabilities/institutional.py::sequence_operators`、manifest D-G07、§2.7 | O01–O08 + O11–O15 单序列 + O09/O10 双序列（提供 `other` 时）；`d` 缺省 20 并按样本安全截断；n≥120 |
| 组合风险族 6 项 | `capabilities/institutional.py`（`inverse_volatility_weights` / `equal_risk_contribution` / `risk_contribution` / `covariance_shrinkage` / `pca_risk_decomposition` / `brinson_attribution`）、manifest D-G10/D-G11/D-G12/D-G13/D-G15/D-G18、§2.7 | 分别复用 P03 / P04 / P05 / P06 / P08 / P12；n≥60；协方差收缩并列 `sklearn` / `analytic` 后端 |
| 回归与拥挤度 | `capabilities/institutional.py`（`fama_macbeth` / `factor_crowding`）、manifest D-G21/D-G24、§2.7 | D-G21 复用 Q05（λ/se/t/期数/标的数，n≥250 期）；D-G24 复用 P13 + P14，稳定性输出 `std_rho/|mean_rho|` 标量，估值价差未提供时显式披露而非伪造 |
| 一致性修复 | `capabilities/institutional.py`、`capability_manifest.yaml` | ① P08 `ratio` 为 list，原 `.values()` 误用 → `sum(ratio)`；② P14 `stability` 为 dict，原按 float 格式化 → 标量派生；③ O09/O10 需要 `{"x","y"}` 而原传裸序列 → 修正并写入 D-G07 manifest 声明，使 `methods ⊆ manifest` 与执行覆盖双向闭合；15 个 answer 统一补「样本」披露以匹配信封硬校验 |
| 计数同步 | 本文头部 + §2.5 三处 + §2.7 + §3、母 SPEC | 可执行出口 54 → **69 个**，manifest **69 条**；§2.5 新增 `institutional.py` 行、`stats.py` 编排函数 48 → 63 |
| 测试 | `tests/test_institutional.py`（25 passed）、`tests/test_capabilities.py` | 覆盖信封契约、`methods ⊆ manifest`、非 good 必含「样本」、输出确定性、空态降级（横截面 <3 标的 / 算子短序列 / P 族短样本 / Q05 <250 期）、O09/O10 双序列路径、D-G24 稳定性标量；54-L1 全量 **1269 passed** |

**v2.55（批次 B-06/B-07：Discovery 搜索空间预注册 + 评估层只读出口）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| Discovery 搜索空间 | `config/discovery_space.yaml`、`l1agg/discovery.py::load_space` | 预注册冻结项全部机器校验：`seed=42`、6 变换、20 方法（须在 `REGISTRY` 登记且不越出预注册子集）、价格前瞻收益 h∈{1,5,20}、序列池 ≤40 且资产序列必须能解析到 `asset_pool.yaml` 的 `anchors[].storage.sub_category`、双序列 ≤300 对、预算 ≤5,000 单元/≤10 分钟/≤50 发现、BH-FDR 强制开（alpha=0.05）、去重阈值 0.95、分段固定 70/30 且 holdout 一致率 ≥0.6；输出 `space_hash` 供 manifest 复现；全量空间超预算属预注册常态，发现器按固定枚举顺序确定性截断 |
| D-K01 方法推荐 | `capabilities/eval_exports.py::recommend_relationship`、`capability_manifest.yaml`（D-K01 / `registry.relationship_eval`）、§2.7、§3 | 只读 `data/relationship_registry.db`（`file:...?mode=ro`），`WHERE target=? AND horizon=? AND gate_pass=1 AND status IN ('stable','candidate') ORDER BY abs(rank_ic) DESC, n DESC LIMIT 3`；Top1 `stable` → `good`，`candidate` → `partial` + `candidate_only`；注册表缺失/不可读 → `empty`；不重算、不写库 |
| D-K02 发现查询 | `capabilities/eval_exports.py::discovery_query`、`capability_manifest.yaml`（D-K02 / `reports.discovery`）、§2.7、§3 | 只读最近一期 `reports/discovery/<YYYYMMDD-HHMM>/`（取同时有 `manifest.json` + `findings.jsonl` 的最大目录名），按 RankIC 绝对值排序截断，输出恒标 `status=candidate`；本期 0 候选 → `partial` + `no_findings`（统计事实，非数据缺失）；报告目录缺失 → `empty` |
| 计数同步 | 本文头部 + §2.5 三处 + §2.7 + §3、母 SPEC | 可执行出口 52 → **54 个**，manifest **54 条**；§2.5 新增 `eval_exports.py` 行并补 K 组边界段 |
| 测试 | `tests/test_discovery_space.py`（13 passed）、`tests/test_eval_exports.py`（9 passed）、`tests/test_capabilities.py` | 空间：哈希确定性 / 方法登记 / 资产可解析 / 9 类篡改拒绝（seed、变换、方法、资产、重复、预算、FDR、分段、配对上限）；出口：缺表空态、无匹配空态、candidate 降级、stable 提级、gate_pass=0 排除、最新报告优先、无候选降级、批量调度器路由；54-L1 全量 **1244 passed** |

**v2.54（本版，上线 #35 云端周期调度 + registry 保留策略）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| 保留策略 | `l1agg/mers.py::RelationshipRegistry.prune_before(cutoff_iso)`；`scripts/mers_eval.py --prune-days` | 只删 `relationship_eval` 中 `eval_at < cutoff` 的历史行，`relationship_state`（每 unit 当前状态）永久保留；`--prune-days 0` 为不清理默认值；summary 新增 `retention{keep_days,cutoff,pruned_rows,rows_after_prune}`；每日 08:20 一轮 ≈5,220 行，90 天保留 ≈47 万行封顶 |
| 周期任务 | `deploy/systemd/dreambuddy-mers.service` / `.timer` | `OnCalendar=*-*-* 08:20:00`（CST，避开 06:00–07:00 数据批次）、`Persistent=true`、`RandomizedDelaySec=300`、`Type=oneshot`、`TimeoutStartSec=3600`；以 `User=luke` 身份只读 DAL、写自有 `data/mers/`；输出落 `data/mers/last_summary.json` + journald |
| 默认版本口径 | `--data-version` 默认当日（`date +%F`） | 同日重复触发命中 `get_eval` 短路（`added=0`、不推进 streak）；跨日自动生成新 `eval_id` 推进状态；**稳定态需每日运行维持** |
| 回归 | `tests/test_mers.py::test_prune_drops_history_but_keeps_current_state` | 180 行删除 + 1 行保留、state 仍为 `pass_streak=2`、同 cutoff 二次清理 0 行；`tests/test_mers.py` 5 passed |

**v2.53（本版，关闭 §6.4.5 #35：MERS S3 全量真实数据验收）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| 全量验收执行器 | `scripts/mers_eval.py`（commit `53952864c2`）、§6.4.5 #35 | 29 job = 20 个 `close_1d` 资产 + 9 个宏观/情绪/资金费率指标（DGS10/NASDAQCOM/SP500/VIXCLS/T10Y2Y/DCOILWTICO/DTWEXBGS/crypto_fear_greed/funding_rate，`align` 到 BTC 日轴，`min_n=250`，不足计入 `skipped`）；每 job 固定 180 单元 → **5,220 单元** |
| 云端实测结果 | 云端 43.160.201.117 只读 `dreambuddy_core.db`；`data/mers/registry.db` | `gate_pass=1,057`（**20.25%**），`method_gate` = ok 3,654 / not_applicable 1,566 / **failed 0**；`p_adj` 2.03e-44～0.99961；job 上限 180：BTC/XLM 77、ETH/LTC/UNI/XRP 70、SP500 42、NASDAQCOM/T10Y2Y 28、DCOILWTICO 7；APT 与 DGS10/VIXCLS/DTWEXBGS/fear_greed/funding_rate 为 0 |
| 状态机验证 | `l1agg/mers.py::transition_state` / `RelationshipRegistry.record` | 三轮（`data_version=accept-20261115-r1/r2/r3`，同快照模拟连续版本）后 `stable=1,057`（`pass_streak=3`）、`candidate=4,163`（`fail_streak=3`）；`decayed/retired` 只能由 stable 进入，与契约一致。stable 遇 `data_version` 变化按契约回退 candidate，故**必须每日运行**才能维持 |
| 幂等 | `evaluate_grid` 在 `_evaluate_unit` 之前查 `get_eval(eval_id)` | 三轮 `added=0`（r1/r2/r3 内部第二遍均 5,220/10,440/15,660 行不变）；跨轮新增行来自 `data_version` 变化生成的新 `eval_id`，不是重复计算 |
| 验收中修复 | `methods/conditional.py::b11_monotonic`（commit `2b5b8b8a59`） | 真实数据并列值使分位边界塌缩产生空桶，`b16_group_stats` 返回 `mean=None` → `float(None)` 崩溃 95 单元；修复为过滤 `n>0 且 mean 非空`，非空桶 <2 显式报错；**failed 95 → 0**、`gate_pass` 1,028 → 1,057；补 2 例回归测试 |
| 保留项（未做） | §6.4.5 #35 剩余半句 | 云端周期调度（timer）未安装；registry 每日追加 5,220 行（≈190 万行/年），保留/归档策略未定，须在周期任务上线前确定；S5 对外推荐仍未开放 |
| 验收包 | `acceptance_bundles/20261115_mers_real_data/` | `acceptance_report.md` + `repro_after.log` + `test.log`（54-L1 全量 **1,192 passed**、audit 392/392）+ `mers_summary{,_r2,_r3}.json` + `fix.diff` |

**v2.52（本版，批次 B-04：新增 D-A05 z-score 出口）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| D-A05 z-score | `capabilities/stats.py::zscore`、`capability_manifest.yaml`（D-A05 / `datacenter.percentile`）、§2.5、§3 | 复用方法层 **S26**（winsorize p1/p99、`min_n=30`、`std=0 → z=None`），能力层只做窗口切片与参数校验，不重算均值/标准差；输出 `zscore/mean/std/winsorized/lookback/sample_n`；`MIN_ZSCORE=30`、`MIN_ZSCORE_LOOKBACK=60`；样本 <30 → `empty`，窗口 <60 降级 `short_lookback`，`lookback` 超历史降级 `lookback_truncated`，`σ≈0` 降级 `zero_variance` 且 `z=None`（禁止伪造 0） |
| 计数同步 | 本文 §2.5 三处、母 SPEC 第 34/41 条 | 可执行出口 51 → **52 个**，manifest 52 条；`stats.py` 编排函数 47 → 48 |
| 测试 | `tests/test_zscore.py`（6 passed）、`tests/test_capabilities.py`（189 passed） | 覆盖正常 z、29 样本 empty、零方差降级、`lookback` 截断、日期轴不一致、`run_capability("D-A05", ...)` 可调度；executor 白名单与 scenario 已补 |

**v2.50（本版，关闭 §6.4.4 #32–#34：C11 节前效应 / D-G25 尾部相关 / D-J05 周期频谱）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| C11 节假日前效应 | `methods/seasonal.py::{c11_pre_holiday, derive_holidays}`、`capability_manifest.yaml`（D-E04 methods + C11） | 「工作日缺失=节假日」派生交易日历（无需外部付费源；周末不算缺口，>10 个工作日连续缺口按数据缺口排除并计入 `excluded_gaps`），支持显式 `holidays`；节前 `lookback` 个交易日收益 vs 非节前基线，Welch t；方法门禁 n≥60；顺带修复 `_diff_t` 两组均为常数时 df 分母为 0 的隐患（t/p 置 None，均值差保留） |
| #32 能力出口 | `capabilities/stats.py::event_study`（`pre_holiday` / `holidays` / `lookback`）、本文 §0.3、§2.4 D-E04、§6.4.4 #32 | 事件路径不变；`pre_holiday=True` 或传 `holidays` 走 C11 分支，输出 `pre_mean/base_mean/diff/t/p/n_pre/n_holidays/excluded_gaps/calendar/pre_dates`；节前样本 <30 降级 `holiday_events_lt_30`；日期轴无工作日缺口（7×24/周度）FAIL-OPEN 为 empty 并说明不适用 |
| D-G25 尾部相关 | `capabilities/stats.py::tail_dependence`、`capability_manifest.yaml` | 复用既有 **P13**（不新增方法 ID，规避 R 组容量上限）：横截面均值 ≤q 分位切尾后的样本内 Pearson；上行尾用收益符号取反后复用同一方法（`upper_tail_by_sign_flip=true`）；输出 `rho_down/rho_up/rho_full/amplification/n_tail`；min_n=60，尾部共现 <30 天降级 `tail_events_lt_30`；仅描述同期共跌共涨，不含因果 |
| D-J05 周期/频谱 | `capabilities/stats.py::cycle_spectrum`、`capability_manifest.yaml` | T25 去趋势主周期 + T26 周期强度，日期轴可用时 C14 月度一致性并列（缺日期不改道，降级 `dates_missing`）；显式返回 `cycles=span_days/period` 与 `period_to_reference=period/1,460`；min_n=60、min_span_days=2920，跨度不足降级 `cycles_lt_2`；只描述频谱事实 |
| 云端实测（v2.50） | 云端 43.160.201.117 只读 `dreambuddy_core.db`（`close_1d` 20 资产 / 54,653 行） | **D-J05**：BTC 3,377 天 → 主周期 1,125.7 天、`cycles=3.0`、`period_to_reference=0.77`、`power_ratio=0.322`（ETH 同周期 1,125.7 / 3.0 / 0.36；BNB 1,098.7）；SOL 2,287 天 `span_days<2920` → `partial + cycles_lt_2`。**D-G25**：BTC/ETH/BNB/LTC/ADA/XRP 对齐 3,116 天、尾部共现 624 天，最强对 BTC\|ETH（`rho_down=0.070` vs `rho_full=0.004`，`amplification=0.07`）；跨资产切尾样本出现机械负相关（如 ADA\|ETH `rho_down=-0.286`），故只作同期共跌/共涨描述。**D-E04 节前**：BTC 7×24 日期轴无工作日缺口 → `empty` 且 answer 明示「节前效应不适用」；`us_NASDAQCOM_value` 仅 202 点，被事件研究 250 点门禁拦为 `empty`｜#32 正向效应量仍需 ≥250 个交易日的真实美股日线（云端 FRED 仅存 latest + `obs_count`，未落逐日观测） |
| 验证 | `tests/test_methods_seasonal.py`（C11 派生/显式/缺口护栏/无缺口 4 例）、`tests/test_capabilities.py`（D-E04 节前 2 例、D-G25 2 例、D-J05 3 例 + 执行覆盖矩阵补 3 个场景）、`tests/test_visual.py`（D-E04 methods 基线）、`tests/test_methods_{s2,research}.py`（占位分支改测） | 54-L1 全量 `pytest tests -q --ignore=tests/test_calibrate_light.py` 全绿；`audit()` **243/243 PASS**（`implemented=true` 392，核心目录 0 占位）；`ruff check` 0 错（仅并行 LTL-16 文件历史告警），`python3 -m black --line-length 100` 无改动 |

**v2.49（D-E14 二维状态 Tier B/D 兜底）**

| 变更 | 代码 / 本文位置 | 结论 |
|---|---|---|
| R02 二维分位 | `methods/conditional.py::r02_percentile_forward`（`indicator2`/`factor2`/`x2` + `label2`）、`_r02_rolling_state`、`_r02_describe` | 两轴各自 PIT 滚动分位后做笛卡尔积，`cell = axis1 * buckets + axis2`；`by_horizon[].by_cell` 逐格给 `n/effective_n/nonoverlap_n/mean/median/p10/p90/win_rate/t/p`，空格显式 n=0；二维强制 `pit=True`，并输出 `current_percentile_2/bucket_1/bucket_2/cell` |
| D-E14 档位阶梯 | `capabilities/stats.py::conditional_distribution`（`factor2/name2/buckets_per_axis`）、`capability_manifest.yaml` | 4×4=A（≥4,000 日）→ 3×3=B（≥2,250 日）→ 2×2=D（≥1,000 日），每格非重叠 ≥250；降档即 `quality.status=partial` 并写 `degraded_reason=bucket_nonoverlap_lt_250`；三档均不达标时 `dim=1` + `degraded_reason=insufficient_2d` 回退一维（一维 4→2 桶） |
| 披露字段 | 同上 | 返回 `dim/tier/requested_tier/degraded_tier/requested_buckets_per_axis/buckets_per_axis/cells/min_cell_nonoverlap_n/tier_attempts`；答案句显式写「Tier X + 每格非重叠下限」，禁止静默降级；二维不输出 R08 单调性（一维序数无单调语义） |
| 数据实测与结论 | 本文 §0.3、§2.4、§6.4 #31/#36 | 云端真实数据（20日动量×20日波动率）：BTC 3,357 根 → A/B/D 最小格 110/223/682；UNI 2,230 → 43/105/412；APT 1,468 → 38/81/265，三者均落 Tier D。联合分桶聚集使 3×3 当前 0 资产达标；4×4 契约保留，样本增长后自动升档。OKX 现货 listTime=2021-01-29，否决 pre-2017 扩样 |
| 验证 | `tests/test_capabilities.py::test_conditional_distribution_two_axis_*`（5 例） | 覆盖 Tier A 16 格 / Tier B 9 格 / Tier D 4 格 / 低于 2×2 回退一维 / factor2 长度不一致 FAIL-OPEN；54-L1 全量 pytest 通过，`ruff check` / `python3 -m black --line-length 100` 通过 |

**v2.48（L1 交易层 D-E15–D-E19 能力登记）**

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
| audit 验证覆盖报告 | `eval/harness.py`、`scripts/method_audit.py`、`docs/method_audit.json` | 区分 executed/missing/not_applicable；392/392 PASS（2026-11-15 重跑）与 72.81% 覆盖率同时披露 |
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
| [METHOD_LIBRARY.md](./METHOD_LIBRARY.md) | v1.19 | v1.19：C11 节假日前效应落地（日历由日期轴派生），核心 243 方法 `implemented=true` 达 243、占位 0；D-G25/D-J05 接线不改方法口径（P13/T25/T26/C14 均为既有方法）；v1.18：D-E14 一维相关状态条件分布接线，可执行出口 16 个 |
| [SPEC-54-L1架构能力聚合层.md](../SPEC-54-L1架构能力聚合层.md) | v1.56 | v1.56：J 组 24 个科研统计出口（D-J01/03/06…D-J29）接入，可执行出口 69 → 93 个，manifest 93 条，新增 `datacenter.panel` / `datacenter.spatial_frame` scope；v1.55：G 组 15 项接入；v1.47：关闭 §6.4.4 #32–#34（C11 节前效应接入 D-E04、D-G25 尾部相关、D-J05 周期/频谱） |
| [SPEC-54-延续性统计分析模块.md](../SPEC-54-延续性统计分析模块.md) | v1.5 | T0.5/A8 首版经 D-E02 出口交付（h=1 PIT，含降桶降级披露）；R02 `pit=true` 已实现；不改 A1–A7 冻结口径 |
| 三份 RESEARCH 文档 | 保持原文（仅同步能力计数） | 作为调研证据，不改写方法结论；RESEARCH-SCIENTIFIC 的能力出口计数同步为 14，分别支撑延续性分层、机构研究协议与科研可复现/PIT 校验 |

**整体进度（按登记范围，而非按方法数量）**：

| 路线（成对映射） | 当前状态 | 已交付 | 尚未闭环 |
|---|---|---|---|
| SPEC S1 ↔ 方法 S1 | 🟡 核心底座完成 + 11 模块本地验收通过 | `market.candles`、UTC 对齐、前瞻收益、价格回显、日线同锚点；`fundamental_snapshot._l0_module_timeseries` 本地只读快照实测 **11/11 模块 timeseries 非空**（sample_n：macro 254、onchain 88、sentiment 90、valuation 11、flow 69、breadth 11、capital_flow 31、intermarket 87、news 39、narrative 90、calendar 15） | valuation/breadth/calendar 为 partial（样本 11/15 天，远低于请求窗口），需 18 侧补历史；通过 ≠ 样本充分 |
| SPEC S2 ↔ 方法 S2 | 🟡 方法完成、能力部分接线 | M01–M07/M11–M12/M24–M25 方法；D-E05 双序列与矩阵 TopK、D-E06 BH-FDR、D-E11/C18 可执行；D-A14 拥挤度合成（A 分位法四档）已接线 | 完整四类榜单契约（稳定推荐仍归 MERS/S5） |
| SPEC S3 ↔ 方法 S3/S6/S7；T0=S3 子集 | 🟢 方法、能力与 MERS S3 已全量验收 | S3 批 22 方法、S6 扩展、22 个 manifest 出口（含 D-A14/D-E01/D-E02/D-E04/D-E09/D-E12/D-E14/D-G16/D-G19/D-G20/D-G22/D-G23/D-J02/D-J04）；T0/D-E13 已交付；R02 `pit=true` 与 MERS 180 单元内部内核已实现；事件历史已云端回填入库（`mm_events=550`）；D-E04 节前效应（C11，日历由日期轴派生）/D-G25 尾部相关（P13 双尾）/D-J05 周期频谱（T25+T26+C14）已于 v2.50 接线；**v2.53 全量真实数据验收通过**：29 job / 5,220 单元、`gate_pass=1,057`（20.25%）、`failed=0`、`stable=1,057`、三轮幂等 `added=0` | D-E14 样本纵深；云端周期调度（含 registry 保留策略） |
| **T0.5=S3→S4** | ✅ 首版已交付（v2.9） | R02 `pit=true` + A8 编排 + D-E02 出口与前端分派；h=1、4 桶 PIT 滚动分位，样本不足自动降 2 桶并披露 `effective_n/nonoverlap_n` | 真实数据纵深不足时按契约降级；h>1 显著性须走 D-G22 出口（已接线） |
| SPEC S4 ↔ T2 | ⬜ | 条件分布非点预测的契约已明确；h>1 显著性出口 D-G22（Q06/Q07）已接线 | T-1 扩样本、T1a/T1b、F1–F12 状态特征、1–2 维场景出口；每桶非重叠 ≥250 的样本纵深仍未满足 |
| SPEC S5 ↔ T3及后续 | ⬜ | MERS S3 内部内核、BH-FDR、holdout 同号、状态机、幂等注册表与随机负例已交付 | walk-forward 完整验收、Discovery、只读推荐/发现出口；不得提前开放 `relationship_recommend` |

### 6.3 下一阶段顺序（blocker 驱动）

1. **R02 `pit=true` 与 T0.5 已交付（v2.9）**：`conditional.py::r02_percentile_forward` 双口径 + A8 编排 + D-E02 出口（manifest/executor/前端分派）均已接线；样本不足按场景包降 2 桶并披露 `effective_n/nonoverlap_n`，不输出点预测。
2. **MERS S3 已全量验收并进入每日调度，下一关键路径是 S5**：v2.53 在云端真实库跑通 29 job / 5,220 单元（`gate_pass=1,057`、`failed=0`、三轮幂等 `added=0`、`stable=1,057`）；v2.54 上线 `dreambuddy-mers.timer`（每日 08:20 CST，`Persistent=true`，`--prune-days 90` 清历史 eval 行、state 永久保留）。**稳定态需每日运行维持**（stable 遇 `data_version` 变化按契约回退 candidate）；S5 须等周期运行积累 holdout/walk-forward 证据后再开放；R03/R04/F19 仍需真实日历/事件上下文，单出口交付不等于显著性结论。
3. **继续补齐 S2/S3 登记范围**：D-E05 矩阵 TopK、D-E11/C18、D-E01、D-E12/R18、D-A14、D-E04/D-E09 已完成（v2.16 接线事件研究窗与计数共现）；L1 前端 `data_query_executor` 的 D-A14（拥挤度）与 D-G22（显著性）cue 分派已同步补齐（`3.1-FRONTEND/scripts/data_query_executor.py` + `l1_route_signal.py` + `src/lib/l1-intent-registry.ts`）；D-E14 的 T-1 扩样本已在云端落地（20 资产 / 54,653 行 `close_1d`），一维场景编排与能力出口已于 v2.17 接线；2 维 4×4 仍需 ≥4000 天/资产。四类榜单分别披露搜索空间与 `p_adj`，不得混排。
4. **T2 一维首版已交付，二维继续受样本约束**：T-1 已在云端唯一生产写入口执行完毕（2026-11-15，20 资产 / 54,653 行 `close_1d`，BTC/ETH 3377 天）；D-E14 已接入已压缩一维相关状态的 PIT h=1/2 条件分布，2 维 4×4 仍需 ≥4000 天/资产且 F1–F12 PIT 特征另行完成。h>1 显著性结论统一走 D-G22 出口，不得用朴素 t 值。
5. **最后开放 S5**：MERS/Discovery 通过 holdout、walk-forward、BH-FDR 和随机负例后，才开放稳定推荐与发现查询。

### 6.4 待完成清单（2026-11-15）

> **完成标记**：每完成一项，将状态改为 ✅ 并记录完成日期与 commit hash（如已提交）。
> **优先级**：P0 > P1 > P2 > P3；可交付性：数据与方法全部就绪 > 方法已实现 > 数据阻塞。

#### 6.4.1 可立即交付（数据与方法全部就绪）

| # | 能力 ID | 能力名 | 优先级 | 状态 | 缺口说明 | 预计工作量 |
|---|---------|--------|--------|------|----------|-----------|
| 1 | **D-E14** | 条件分布（状态→前瞻）场景编排 | P1 | ✅ 2026-11-15 | 一维首版 + 二维 Tier B/D 兜底均已交付：manifest + `conditional_distribution` executor + R02 PIT 共享桶标签（一维 4→2 桶、二维 4×4=A/3×3=B/2×2=D 阶梯、三档不达标回退一维）+ 弱期限降级；降级档位与每格 n 显式返回；54-L1 全量 pytest 通过 | 已完成 |
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

> 2026-11-15 云端实测（43.160.201.117 `dreambuddy_core.db`，`mm_metrics.metric_name='close_1d'` 共 20 资产 / 54,653 行）：最长纵深 3,377 天（BTC/ETH，2017-08-17 起），最短 1,488 天（APT/USDT）。以下四行的阻塞判定已按实测回调，不再沿用估算。

| # | 能力 ID | 能力名 | 优先级 | 状态 | 阻塞原因（2026-11-15 实测） | 预计解除时间 |
|---|---------|--------|--------|------|----------|-------------|
| 31 | **D-E14（2 维）** | 二维状态组合（4×4 / 3×3 / 2×2） | P2 | ✅ 2026-11-15（Tier B+D 兜底） | 已按 Tier B/D 落地：4×4=A / 3×3=B / 2×2=D，每格非重叠 ≥250（PIT 预热 250 日后计）。云端真实数据实测（20日动量×20日波动率）：BTC/USDT 3,357 根日线 → A 档最小格 110、B 档 223、D 档 682，落 **Tier D**；UNI/USDT 2,230 → 43/105/412；APT/USDT 1,468 → 38/81/265，均落 **Tier D**。即当前 20 资产 2×2 全达标、3×3 暂 0 达标（联合分桶聚集，非均匀），4×4 需样本继续增长后自动升档。OKX pre-2017 日线否决（BTC-USDT/ETH-USDT 现货 listTime=2021-01-29，比库内 2017-08-17 更浅），跨 venue 拼接仍列为可选外部扩样（需先过口径评审） | 已完成（Tier D 全覆盖；Tier B/A 随样本纵深自动升档） |
| 32 | **C11** | 节日/事件日历 | P2 | ✅ 2026-11-15 | 已解除：`methods/seasonal.py::c11_pre_holiday` 实现「工作日缺失=节假日」派生（`derive_holidays`，>10 工作日连续缺口按数据缺口排除并计入 `excluded_gaps`），支持显式 `holidays`；能力出口为 `capabilities/stats.py::event_study` 的 `pre_holiday`/`holidays` 分支（D-E04），节前样本 <30 降级 `holiday_events_lt_30`，无工作日缺口（7×24/周度）FAIL-OPEN 为 empty；方法自检 243/243 PASS。云端实测：BTC（7×24）日期轴无工作日缺口 → `empty` 并明示「节前效应不适用」；`us_NASDAQCOM_value` 仅 202 点被 250 点事件研究门禁拦截 → 同样 empty。**节前效应量的正向实测仍缺 ≥250 个交易日的美股日线**：云端 FRED 记录只存 latest + `obs_count`（如 DGS10 `obs_count=16,399`），未落逐日观测行 | 已完成（代码/接线）；效应量实测待 18 侧补齐 FRED 逐日观测或接入外部美股日线 |
| 33 | **D-G25** | 尾部相关 | P2 | ✅ 2026-11-15 | 已解除：复用既有 **P13**（横截面均值 ≤q 分位切尾后的样本内 Pearson，METHOD_LIBRARY 已登记，无需新增方法 ID），`capabilities/stats.py::tail_dependence` 输出 `rho_down/rho_up/rho_full/n_tail/amplification`；上行尾用符号取反复用同一方法；min_n=60，尾部共现 <30 天降级 `tail_events_lt_30`。云端实测（BTC/ETH/BNB/LTC/ADA/XRP）：对齐 3,116 天、尾部共现 624 天，最强对 BTC|ETH（`rho_down=0.070` vs `rho_full=0.004`）；跨资产切尾样本有机械负相关（ADA|ETH `rho_down=-0.286`），故仅作同期描述 | 已完成 |
| 34 | **D-J05** | 比特币四年周期 | P2 | ✅ 2026-11-15 | 已解除：`capabilities/stats.py::cycle_spectrum` 接线 T25 主周期 + T26 周期强度 + C14 月度一致性，输出 `cycles=span_days/period` 与 `period_to_reference=period/1,460`；min_n=60、min_span_days=2920，跨度不足降级 `cycles_lt_2`、缺日期轴降级 `dates_missing`。云端实测：BTC/ETH 3,377 天主周期 1,125.7 天、`cycles=3.0`、`period_to_reference=0.77`、`power_ratio` 0.322/0.360；BNB 3,296 天 → 1,098.7 天；SOL 2,287 天 <2,920 → `partial + cycles_lt_2` | 已完成 |

#### 6.4.5 S 级路线里程碑

| # | 里程碑 | 状态 | 缺口说明 | 预计工作量 |
|---|--------|------|----------|-----------|
| 35 | **S2/S3 全量真实数据验收 + 云端周期调度** | ✅（v2.54） | 云端真实库跑通 29 job / 5,220 单元：`gate_pass=1,057`（20.25%）、`method_gate` ok 3,654 / not_applicable 1,566 / failed 0、`stable=1,057`、三轮幂等 `added=0`；验收中修复 B11 空桶 `float(None)`（失败 95→0）。周期调度已上线：`dreambuddy-mers.timer` 每日 **08:20 CST**（`Persistent=true`），`--prune-days 90` 只清 `relationship_eval` 历史行、`relationship_state` 永久保留；unit 文件入库 `deploy/systemd/` | 已完成 |
| 36 | **S4 T2 条件外推表达** | 🟡 | T0.5 与 D-E14 一维 h=1/2 首版已交付（#1 ✅）；T2 二维已按 Tier B/D 兜底落地（4×4=A/3×3=B/2×2=D，Tier A 待样本到 4,000 日自动升档）；Tier D 资产可出二维表达，Tier 边界与每格 n 需随结果披露 | 剩余仅 Tier A 样本纵深（样本自然增长） |
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
- **数据阻塞**：0 项（#31-#34 已于 2026-11-15 全部解除；#32 正向效应量实测待 18 侧 FRED 逐日观测）
- **S 级路线**：2 项（#36-#37；#35 已于 2026-11-15 验收关闭）
- **基础设施**：1 项待办 + 2 项已完成（#38-#40）
- **总计**：40 项（✅ 37 项，待办 3 项）

**下一步**：数据阻塞已清零，剩余 3 项为 S 级路线（#37 S5 对外推荐、#36 Tier A 样本纵深）与验收基础设施（#38 S1 11 模块历史查询验收）。#35 的全量验收已通过，其遗留的**云端周期调度 + registry 保留策略**已登记在 #35 缺口说明与 §6.3 第 2 条，不另开编号。

**文档治理**：见 §0.4；实测数字只在 METHOD_LIBRARY §15 独立维护，其他文档只能引用或保留标注「引自 §15」的决策摘要，执行时按最新快照重算。

---

## §7 统计层 → 图表输出 → 信号层：串行推进顺序与接口冻结（v2.58）

### §7.1 决策：写代码串行，只读调研可并行

2026-11-15 用户决定推进节奏为 **统计层 → 图表输出 → 信号层**（先看到数据结果，再谈信号）。本层执行口径：

- **串行的是写代码**：同一时刻只允许一个层产生代码变更；
- **可并行的是只读调研**（接口盘点、字段核对、口径比对），不产生写冲突；
- **禁止**跨层代偿：信号层不得直接调 `run_capability` 重算统计量，图表层不得读 `trading.db`。

理由：三层依赖是单向的（统计量 → 制品 → 方向），倒序做信号层等于用未标定阈值猜方向；并行做三层会让 manifest 计数、阈值口径、字段契约三类错误同时扩散。

### §7.2 三层范围与可判定完成定义

| 层 | 范围 | 完成判定（全部满足才算 ✅） |
|---|---|---|
| L-STAT 统计层 | 93 个能力出口 + 方法层 386 个 `implemented` | ① `pytest tests -q` 全绿 ✅（1314）；② 93 条 manifest 与 `_EXECUTORS` 双向闭合 ✅；③ 真数据覆盖表（能力 × 资产 × 样本量）产出 ✅（§7.9）；④ 云端与本地 manifest 计数一致 ✅（B-58：`ca6c55a3c6`，云端 93 = 本地 93） |
| L-CHART 图表层 | T1 表格 / T2 曲线 / T3 树图 + D-E15–D-E19 制品 | ① `visual` 规格过 `capability_result.schema.json`；② T2 曲线 + D-E19 lights 制品可复跑；③ 阈值口径定稿并回写 `config/chart_weights.yaml`；④ `artifacts/` 落盘幂等 |
| L-SIGNAL 信号层 | `direction_rule` → `signal` 表 → `handoff` → 22 | ① 四轴→方向映射无缺口；② `params_hash` 含资产池版本；③ 纸面回放基线复跑一致；④ 非加密标的降级路径明确 |

**图表层交付物必须包含两类**：给人看的图 + 给信号层读的机器制品（`lights[]`）。只交前者，信号层必然返工。

### §7.3 三个接口冻结点（不能拖到下一层）

| 冻结点 | 时点 | 冻结内容 | 未冻结的后果 |
|---|---|---|---|
| **G-IF1** | 统计层收口时 ✅ **已冻结（v2.63，§7.10）** | `capability_result` 信封字段、`gate` 枚举、`methods` 披露、`as_of/PIT` 语义、缺失→降级约定、`data.lights` 行契约、块内字段清单 | 图表层按旧字段消费，G/J 组 39 个新出口全部返工 |
| **G-IF2** | 图表层收口时 | 四轴 `strength` 口径、`lit_pct/warm_pct` 标定口径、`lights[]` 行 schema、`band/flags` 字段 | 信号层无法启动（阈值双轨、轴名错位） |
| **G-IF3** | 信号层开工前 | `direction_rule` 参数版本、`trading.db` 写入契约、纸面回放基线 | 回放不可复现，灰度切换无审计依据 |

### §7.4 接口表 A：统计层 → 图表层

**生产者**：`l1agg/capabilities/*.py` 的 `build()`；**契约**：`contracts/capability_result.schema.json`；**消费者**：`build_visual`、前端渲染、`artifacts/` 落盘。

| 字段 | 类型 / 约束 | 口径 | 缺失/降级 |
|---|---|---|---|
| `ok` | boolean | `status=empty` → false | L1 据此转 L2 |
| `capability` | `^D-[A-Z]\d{2}$` | 必须在 manifest 登记 | 未登记 → 契约违规 |
| `intent` | string | 与 manifest `intent` 一致 | — |
| `answer` | string | 非 good 时必须含「样本/降级/不足」 | `build` 抛 ValueError |
| `data.capabilities[cid].gate` | enum 6 值：`ok`/`partial`/`degraded`/`insufficient_samples`/`insufficient_history`/`no_data` | 能力级门禁（方法级另有 `skipped`/`calculation_failed`/`empty`/`rejected`，只出现在块内方法结果，不入本枚举） | schema 失败 |
| `data.capabilities[cid].methods` | string[]，minItems 1，`^[A-Z]{1,2}\d{2}$` | **必须 ⊆ manifest.methods** | 超出 → 执行覆盖校验失败 |
| `data.capabilities[cid].reason` | string | 降级原因 | 可选 |
| `data.params / symbol / pair` | object / string? / [string,string] | 回显入参 | 可选 |
| `data.name` | string? | 资产/口径显示名 | 可选 |
| `data.as_of` | string? | **数据时点**＝已对齐观测的最后一个交易日（ISO 日期，UTC 日轴），不是运行时刻、不带时区偏移 | 可选 |
| `data.window_days` | integer ≥1 | 回显窗口长度（自然日/交易日由 `params` 说明） | 可选 |
| `data.source` | string? | 数据来源标识（如 `market.candles`） | 可选 |
| `data.items` | array | 列表型明细项；**元素结构未冻结**，图表层只做透传/展示，禁止按固定列解析 | 可选 |
| `data.notes` | string / string[] / null | 口径说明与告警；**可能为单串**，不得假定数组 | 可选 |
| `data.assets` | object / array / null | 资产池/分组映射 | 可选 |
| `data.lights` | array\<object\> | D-E19 轴级点亮事实（行契约见 `$defs.lights_row` / 表 B-1），**不是图种** | 无入参 → 键省略 |
| `data.visual` | 见下 | 每信封最多 1 个 | 无图 → 省略 |
| `quality.status` | enum(`good`/`partial`/`empty`) | 唯一质量块，只在顶层 | — |
| `quality.sample_n` | integer ≥0 | 参与计算的有效样本 | — |
| `quality.span` | [string,string]? | [首日, 末日] UTC | — |
| `quality.is_stale` | boolean | 末端观测是否超过 stale 上限 | 必填 |
| `quality.degraded_reason` | string? | partial/empty 时**必填** | 缺失 → schema 失败 |
| `quality.sources / missing_rate / align_method / timezone` | 可选 | 数据血缘 | — |
| `quality.snapshot_at` | string? | 数据快照时点（UTC）；**能力层不填**，只能由 19-DAL 快照层注入（K-12） | 图表层见 null → 不得自行补时点 |
| `visual.kind` | enum(table/series/matrix/tree/graph) | — | — |
| `visual.spec_version` | const `1.0` | 规格版本 | — |
| `visual.title` | ≤60 字 | — | — |
| `visual.source_capability` | `^D-[A-Z]\d{2}$` 或 `T1–T4` | 血缘 | — |
| `visual.n_scope` | enum(global/per_row/per_cell) | 样本口径 | — |
| `visual.dataset` | 按 kind 分支 | table: columns/rows/groups；series: points/meta；matrix: 20×20 上限；tree: root；graph: nodes/edges | — |
| `visual.encodings / annotations` | object | 前端零统计 | 可选 |
| `visual.quality_ref` | const `quality` | 指向顶层 quality | — |
| `visual.caveat` | string ≥1 | 必填免责语 | — |
| `visual.truncated` | boolean | 截断标记；rows/points 超 500 时截断并置 true | — |
| 产图门禁（V-G1/V-G2/V-G7） | — | `quality.status=="empty"` 或来源块 `gate!="ok"` 或 `L1_VISUAL_ENABLED=0` → **不产 `visual`**（键省略，不产空图） | 违规 → 空图/假图 |
| `visual.source_capability` 约束 | 强制 `==` 信封 `capability`（ADR-V2） | 生产侧禁止输出 `T*`；T1–T4 已登记为 `chart_specs`（v2.64） | 违规 → `build` 抛 ValueError |
| `visual` 五 kind 现状 | table/series/tree/graph 有生产者；**matrix 保留但无生产者** | 图表层不得为“用上 matrix”而自造数据 | — |

**表 A-1 能力块内部字段清单（图表层允许读取的全部块内字段，v2.63 冻结）**

> 契约对能力块**内部**字段不做闭合（`data.capabilities[cid]` 除 `gate`/`methods` 外允许扩展键）。因此图表层只能读取下表显式登记的字段；新增读取任何其他块内字段，必须先在本表登记并同步 `$defs`，否则属契约外依赖。

| 能力 | 允许读取的块内字段 | 生产者 |
|---|---|---|
| D-E10 | `drawdown_path[{date,drawdown}]`、`mdd` | `visual._drawdown_series` |
| D-E12 | `window`、`window_rows[{asset,start_value,end_value,ret,n_obs,stale_ratio,first_date,last_date}]` | `visual._alignment_table` |
| D-E15 | `prices[]`、`smoothed[{date,ema26}]`、`meta{n,windows}`、`slope_table[{window,slope,se,t,r2,hac_corrected}]` | `visual._trend_series` / `visual.slope_table` |
| D-E16 | `points[{date,agg,ema26,members,coverage_ratio,partial_members}]`、`meta{smoothing,unit,n,members}` | `visual._aggregate_series` |
| D-E17 | `rows[{class,symbol,label,role,last,ret_20,ret_60,ret_120,ret_250,vol_60,mdd,adx14,corr_to_leader_90d,lights_ref,lit_n,warm_n,n,stale_ratio,status,degraded_reason}]` | `visual._class_board_table` |
| D-E18 | `nodes[]`、`edges[]`、`meta{flows,reason}`、`visual`、`truncated`、`flags` | `flow.flow_block` |
| D-E19 | `lights[]`（行契约 `$defs.lights_row`）、`summary`、`meta{...}` | `lights.light_block` |

**表 A 缺口（实测，2026-11-15）**

| # | 缺口 | 证据 | 影响 |
|---|---|---|---|
| A-1 | ~~**G/J 组 39 个出口的能力块缺 `gate`**~~ **已修复（v2.59）** | 实测 `D-G01`/`D-J01`/`D-J20` 修复前 block keys 均无 `gate` | `envelope.build()` 统一补 `gate`（缺省 `ok`，不覆盖既有值），一处收敛全部 93 出口 |
| A-2 | ~~schema 校验测试只覆盖 12 个手选出口~~ **已修复（v2.59）** | 执行覆盖测试现对 93 个场景逐个 `jsonschema.validate` | 全绿不再假阳性 |
| A-3 | ~~方法级 `gate` 未入契约~~ **已修复（v2.60）** | `envelope.GATE_METHOD` 显式声明方法级集合（能力级 6 值 + `skipped`/`calculation_failed`/`empty`/`rejected`）；执行覆盖测试对 93 场景逐块递归校验 | 方法级 gate 不再是隐式约定 |
| A-4 | ~~`data` 未闭合 `additionalProperties`~~ **已修复（v2.60）** | `data` 关闭扩展键，枚举实际使用的 12 个键（capabilities/params/symbol/pair/name/as_of/window_days/source/items/notes/assets/visual） | 图表层可做严格字段校验 |
| A-5 | ~~`visual.source_capability` 允许 `T1–T4` 但 manifest 无 T* 实体~~ **已修复（v2.64，K-11）** | `capability_manifest.yaml` 新增 `chart_specs`，登记 T1–T4 的 id/kind/description/sources | `Manifest.chart_specs` 可加载四类规格；`validate()` 拒绝未知 sources；制品血缘可反查能力或上游图表规格 |
| A-6 | `quality.snapshot_at` 契约已开槽（v2.60），暂无生产者 | schema 已有可选字段，能力层不填（无快照事实源） | 快照戳须由 19-DAL 快照层注入，禁止能力层推断（K-12，见 §7.10 第 3 类） |
| A-7 | ~~D-E19 的 `data.lights` 未入契约~~ **已修复（v2.63）** | 实测 `lights()` 的 `data keys = ['capabilities','lights','params']`，`jsonschema.validate` 报 `Additional properties are not allowed ('lights' was unexpected)`；AST 扫描确认其余出口 `build(data=)` 键全部 ⊆ 12 键 | schema 增 `data.lights` + `$defs.lights_row`/`lights_axis`；补回归测试 `test_envelope_validates_against_json_schema` |

### §7.5 接口表 B：图表层 → 信号层

**生产者**：`l1agg/capabilities/lights.py::light_block`（D-E19）；**消费者**：`l1agg/direction_rule.py::decide`、`l1agg/handoff.py::build_final_decision`。

**B-1 `lights[]` 行字段（D-E19 能力块）**

| 字段 | 取值 / 约束 | 口径 |
|---|---|---|
| `gate` | `ok` / `empty` | 无入参 → `empty` + `reason=no_entries` |
| `methods` | `[I37, I39, I36]` | 固定三方法 |
| `lights[].symbol` | string | 透传 entry |
| `lights[].class` | string | `entry.class` 或 `entry.view`，缺省「未分类」 |
| `lights[].as_of` | string? | 透传，**无时区约束** |
| `lights[].axes.{trend,inertia,cycle,foresight}` | object | 四轴固定顺序 |
| `…axes[*].state` | enum(`lit`/`warm`/`dim`/`conflict`/`unavailable`) | `conflict` 仅 trend=lit 且 foresight 命中 `CONFLICT_FLAGS` |
| `…axes[*].strength` | float ∈[0,1] 或 null | null → `axis_missing` |
| `…axes[*].bucket` | enum(high/mid/low/none) | 由阈值切分 |
| `…axes[*].evidence` | object | 零重算，仅回显方法事实 |
| `…axes[*].flags` | string[] | 轴级旗标 |
| `lights[].strength` | float 或 null | 按 `light_weights` 归一的加权合成（**不是**方向分） |
| `lights[].summary` | `{lit_n,warm_n,conflict_n,unavailable_n}` | 四轴计数 |
| `lights[].light_weights_hash` | string | 权重+阈值指纹 |
| `lights[].n` / `min_rows` | int | 样本行数与门槛（默认 250） |
| `lights[].status` | `available` / `partial` | 四轴齐全才 available |
| `meta.light_weights` / `_hash` / `_source` / `_mode` / `weights_degraded` | — | 三权分立审计字段 |
| `meta.thresholds` | `{lit_pct, warm_pct}` | 当前配置值 |
| `meta.thresholds_uncalibrated` | boolean | `calibrated_at` 为空 → true |
| `meta.conflict_flags` | `[vix_pct_ge_0.90, vix_divergence, curve_inverted]` | 只读旗标白名单 |

**B-2 `direction_rule` 入参（`config/direction_rule.yaml`，`dr-1.1.0`）**

| 参数 | 值 | 说明 |
|---|---|---|
| `windows` / `window_weights` | `[20,60,120,250]` / `[0.15,0.25,0.30,0.30]` | 多窗一致性 |
| `axis_weights` | `trend 40 / adx 25 / inertia 20 / coherence 15 / gap 0` | **与 lights 轴名不同** |
| `gap_axis` | `enabled: false` | 协整均衡缺口，未启用 |
| `strength_mode` | `abs_total` | 备选 `quantile_dispersion`（ref 0.10） |
| `midas` | `enabled: false` | Beta 多项式混合频率 |
| `adx_bands` | `[0,20,0] / [20,25,0.5] / [25,100,1]` | ADX 分档打分 |
| `ema` | fast 12 / slow 26 / trend 50 | — |
| `flat_threshold` / `exit_threshold` | 30 / 12 | 进场 / 迟滞平仓 |
| `hysteresis_confirm_bars` / `min_hold_bars` | 2 / 6 | 迟滞与最短持有 |
| `use_same_direction` / `use_significance` / `hac_alpha` | true / true / 0.05 | 显著性门 |
| `seasonality_mode` | `record_only` | 只记录不打分 |

**B-2A K-02 轴事实映射（v2.64 冻结）**

| 消费侧字段 | 唯一事实源 | 投影 / 权重规则 |
|---|---|---|
| `lights.axes.trend` | `direction_rule.score.axes.trend`；上游 D-E15 `slope_table` | `clamp01(abs(axis_value) / axis_weights.trend)`；展示合成只用 `light_weights.trend` |
| `lights.axes.inertia` | `direction_rule.score.axes.inertia`；上游 D-E15 `ema/ema_order`（I02） | `clamp01(abs(axis_value) / axis_weights.inertia)`；展示合成只用 `light_weights.inertia` |
| `lights.axes.foresight` | `direction_rule.score.axes.coherence`；上游 D-E11 `cycle_alignment` | 仅做 `coherence → foresight` 改名投影，`clamp01(abs(axis_value) / axis_weights.coherence)` |
| `lights.axes.cycle` | I39 `cycle[-1].value / amplitude / period_days` | `strength=clamp01(abs(cycle[-1].value)/amplitude)`；振幅或尾值缺失则不产强度并打标；`period_days∉[30,90]` 只打标、不伪造相位；`light_weights.cycle` 只参与展示合成，**不是归一化除数** |
| `direction_rule.axes.adx` | D-E15 `adx{adx,plus_di,minus_di}`（I32），经 `rule_inputs.build_inputs` 投影为 `adx14/plus_di/minus_di` | 按 `adx_bands` 与 `axis_weights.adx=25` 打分；**不进入 lights 四轴，不读 light_weights** |
| `direction_rule.axes.gap` | 调用方显式传入的 I35 `equilibrium_gap` | 默认 `gap=0` 关闭且不进入 `axes`；不进入 lights 四轴 |

信号层不得把 `lights[]` 直接当作 `direction_rule` 入参：方向决策仍由 `rule_inputs.build_inputs(D-E15/D-E11/...) → direction_rule.decide` 产生；`lights[]` 是展示与审计制品。两组轴名可以不同，但上表映射与来源不得再漂移。

**B-3 `handoff` 契约（`49-交易框架协议/contracts/final_decision_signal.v1.1.json`）**

入参 `signal` 必填：`as_of`、`symbol`、`rule_version`、`params_hash`、`direction∈{-1,0,1}`、`strength∈[0,1]`；可选 `band`、`flags`。

**K-06 契约冻结**：`band/flags` 的唯一生产者是 `direction_rule.decide()`；`band=strength_band(decide.strength)`，`flags` 来自规则评分与降级路径。handoff 必须原值透传到 `payload.l1_band/l1_flags`。`lights.flags` 仅表达展示/审计降级，禁止作为信号 flags 来源；lights 不新增方向 `band`。

出参：`signal_id`=`l1-chart|dec-l1-…`、`ts`、`symbol`（仅 `*-USDT-SWAP`）、`direction`（short/neutral/long）、`confidence`=`strength`、`horizon`、`risk_exposure_hint`、`expires_at`（默认 TTL 15 min）、`mode∈{live,paper,shadow}`、`payload{decision_id, action, position_tier, position_mult, notional_usdt, adapter="54-l1", as_of, l1_direction, l1_strength, l1_band, l1_flags, rule_version, params_hash}`；仓位档 `probe<0.55 ≤ standard<0.75 ≤ trend`。

**表 B 缺口（P0 级为主）**

| # | 缺口 | 证据 | 影响 |
|---|---|---|---|
| B-1 | ~~**轴名错位**：lights 四轴 `trend/inertia/cycle/foresight` vs 规则五轴 `trend/adx/inertia/coherence/gap`~~ **已关闭（v2.64，K-02）** | `lights._INNER_AXIS` 只映射 foresight→coherence；`cycle` 靠 I39 外部传入；`adx` 在 lights 无对应轴 | 冻结 B-2A 映射：ADX=D-E15/I32→方向规则；cycle=I39 尾值/自身振幅→展示轴；信号层不直接消费 lights 作为方向入参 |
| B-2 | ~~阈值双轨：`lights.DEFAULT_THRESHOLDS` = 0.70/0.40，`config` = 0.764706/0.572400~~ **已关闭（v2.64，K-03）** | `DEFAULT_THRESHOLDS` 仅作配置缺失/非法时兜底；`cfg=None` 也先加载 `chart_weights.yaml` | `resolve_thresholds` 统一读取标定值 0.764706/0.572400；回归测试覆盖无 cfg 路径 |
| B-3 | ~~`band` / `flags` 未被 lights 产出~~ **已关闭（v2.64，K-06）** | 实测 `direction_rule.decide` 已产出 `band/flags`，handoff 原值写入 `l1_band/l1_flags`；缺的是端到端契约证据 | 新增 `test_k06_decide_band_and_flags_reach_handoff_payload`；lights 不复制方向分档 |
| B-4 | `params_hash` 不含资产池版本 | `config/weights.yaml` 无 `pool_version`（LTL-15 未落） | 池变更后回放不可靠 |
| B-5 | 动态权重开关未开 | `weights.yaml mode: "off"`（LTL-09） | 轴向权重固定 40/25/20/15，无灰度验证 |
| B-6 | `as_of` 无时区/TTL 约定 | lights 透传、handoff 自造 `ts` | 跨时区回放可能错位 |
| B-7 | 非加密标的无法 handoff | `execution_symbol` 只认 `BINDINGS.asset_class=="crypto"`，其余抛 `HandoffError` | 20 资产池里仅 BTC/ETH 可执行，其余只能 shadow |
| B-8 | 三权分立易被误用 | `light_weights`(0.40/0.25/0.15/0.20) ≠ `axis_weights`(40/25/20/15) | 若混用，图表强度会被当成方向分 |

### §7.6 接口表 C：信号层 → 回测 / 评估 / 22 执行

| 字段 | 生产者 | 消费者 | 约束 |
|---|---|---|---|
| `decision_id` | `handoff` | 22 幂等 / outbox 去重（L1X-03） | `(symbol, as_of, direction, rule_version, params_hash)` 确定性派生 |
| `signal_id` | `handoff` | 22 | `l1-chart|{decision_id}` |
| `direction` / `strength` | `direction_rule` | `handoff`、回放 | -1/0/1；[0,1] |
| `params_hash` | `direction_rule` | 22、回放、灰度审计 | 参数变更必须升 `version` |
| `weights_hash` | 动态权重层 | 审计（L1D-08） | `off` 时为静态先验指纹 |
| `position_tier` / `position_mult` | `handoff` | 22 | probe/standard/trend；= strength |
| `expires_at` / `mode` | `handoff` | 22 | TTL 15 min；live/paper/shadow |
| `band` / `flags` | `direction_rule` | 22、评估层 | **当前 lights 侧未产出**（B-3） |

**表 C 缺口**：`trading.db` 的 `signal` 表 DDL 与上表字段未做逐列核对（本轮只盘点 6 个代码/配置资产）；`paper_replay` 与 `handoff` 的 `mode` 语义需对齐；评估层读 `signal` 表的 PIT 口径未定义。

### §7.7 信号层前置阻塞清单

| 优先级 | 编号 | 阻塞项 | 解除条件 | 归属层 |
|---|---|---|---|---|
| **P0** | K-01 | ~~G/J 组 39 出口能力块缺 `gate`~~ **✅ 已关闭（v2.59）** | `envelope.build()` 统一补 `gate`（缺省 `ok`）；回归测试 `test_every_capability_block_declares_gate` | L-STAT（G-IF1） |
| **P0** | K-02 | ~~lights 四轴与规则五轴错位（缺 `adx`、`cycle` 未权重化）~~ **✅ 已关闭（v2.64）** | B-2A 已冻结：`adx`=D-E15/I32→方向规则；`cycle.strength=clamp01(abs(I39 尾值)/amplitude)`，展示权重与归一化分母分离 | L-CHART（G-IF2） |
| **P0** | K-03 | ~~阈值双轨 0.70/0.40 vs 0.7647/0.5724~~ **✅ 已关闭（v2.64）** | `resolve_thresholds(cfg=None)` 先读 `chart_weights.yaml` 标定值，DEFAULT 仅最终兜底；新增无 cfg 回归测试 | L-CHART（G-IF2） |
| **P0** | K-04 | `weights.yaml mode: off` | 明确灰度档位与注入条件后才可开工 | L-SIGNAL（G-IF3） |
| P1 | K-05 | `pool_version` 未入 `params_hash` | 资产池版本纳入派生 | L-SIGNAL |
| P1 | K-06 | ~~`band`/`flags` 未产出~~ **✅ 已关闭（v2.64）** | 冻结信号侧唯一生产者 `direction_rule.decide`；`decide→handoff` 端到端测试验证 `l1_band/l1_flags` 原值透传并通过 49 契约 | L-CHART/G-IF2 |
| P1 | K-07 | 非加密标的无 handoff 路径 | 明确 shadow-only 或新增标的映射白名单 | L-SIGNAL |
| P1 | K-08 | ~~schema 校验覆盖不足（仅 12 出口）~~ **✅ 已关闭（v2.59）** | 执行覆盖测试内对 93 个场景逐个 `jsonschema.validate`；同批发现并修复 `gate` 枚举缺 `partial`/`degraded` | L-STAT |
| P2 | K-09 | ~~方法级 `gate` 未入契约~~ **✅ 已关闭（v2.60）** | `envelope.GATE_METHOD` 单一事实源 + 递归校验 | L-STAT |
| P2 | K-10 | ~~`data` 未闭合 `additionalProperties`~~ **✅ 已关闭（v2.60）** | 枚举 12 个真实键后关闭扩展 | L-STAT |
| P2 | K-11 | ~~`visual.source_capability` 的 T* 无实体~~ **✅ 已关闭（v2.64）** | T1–T4 已登记为 `chart_specs`；`Manifest` 加载实体并校验 sources 引用 | L-CHART |
| P2 | K-12 | `quality.sources` 无快照戳 | **🟡 契约已开槽（v2.60）**：`quality.snapshot_at` 已入 schema；待 19-DAL 快照层提供值，能力层不伪造 | L-STAT |

### §7.8 推进顺序（自本版起）

1. **L-STAT 收口 ✅（v2.62 完成）**：K-01 / K-08 / K-09 / K-10 已关闭（v2.59–v2.60），K-12 契约已开槽待 19-DAL；真数据覆盖表 ✅（§7.9），B-58 提交同步 ✅（`ca6c55a3c6`，云端 manifest 93 = 本地 93）→ 统计层四项判定全满足，**G-IF1 冻结已按第 2 步完成**。
2. **G-IF1 冻结 ✅（v2.63 完成）**：表 A 字段核对无遗漏；修复 A-7（D-E19 `data.lights` 未入契约）；冻结结论见 §7.10（已冻结 / 转下游 / 图表层禁止假设），**L-CHART 允许开工**。
3. **L-CHART（四项阻塞已关闭，v2.64）**：范围先砍到 **T2 曲线 + D-E19 lights 制品**，T1 作为副产物、T3 后置；K-02 / K-03 / K-06 / K-11 均已关闭，下一步执行 G-IF2 总冻结。
4. **G-IF2 冻结**：`lights[]` 行 schema 与阈值口径定稿。
5. **L-SIGNAL**：只补 K-04 / K-05 / K-07 + 复跑纸面回放，不重写 `direction_rule`。
6. **G-IF3 冻结**：回放基线与 `signal` 表契约确认后再开灰度。

### §7.9 真数据覆盖表（v2.61，L-STAT 收口证据）

**口径**：`19-数据访问层/data/dreambuddy_core.db`（261 MB，本地只读副本，`mode=ro` 打开，快照时间 2026-11-15 23:32）；资产与指标取 `config/asset_pool.yaml` 的 `storage.sub_category` + `storage.metric`，不做任何推定。

**A. 资产级覆盖（28 个注册资产）**

| 资产 | sub_category / metric | 样本 | 起 | 止 | 门禁判定 |
|---|---|---|---|---|---|
| BTC | BTC / close_usd | 1094 | 2023-11-15 | 2026-11-12 | ≥250 ✅、≥750 ✅、≥4000 ❌ |
| ETH | ETH / close_usd | 1094 | 2023-11-15 | 2026-11-12 | 同上 |
| SOL | SOL / close_usd | 1094 | 2023-11-15 | 2026-11-12 | 同上 |
| XAU | XAU / close_usd | 1094 | 2023-11-15 | 2026-11-12 | 同上 |
| IXIC | NASDAQCOM / value | 14263 | 1971-02-05 | 2026-11-15 | 全档 ✅（含 ≥4000） |
| SPX | SP500 / value | 2718 | 2016-11-07 | 2026-11-15 | ≥250 ✅、≥4000 ❌ |
| WTI | DCOILWTICO / value | 9742 | 1986-01-02 | 2026-11-15 | 全档 ✅ |
| US10Y | DGS10 / value | 16403 | 1962-01-02 | 2026-11-15 | 全档 ✅ |
| VIX | VIXCLS / value | 9517 | 1990-01-02 | 2026-11-15 | 全档 ✅ |
| T10Y2Y | T10Y2Y / value | 12607 | 1976-06-01 | 2026-11-09 | 全档 ✅ |
| BZ | DCOILBRENTEU / value | 757 | 2023-11-15 | 2026-11-11 | ≥250 ✅ |
| NG | DHHNGSP / value | 746 | 2023-11-15 | 2026-11-11 | ≥250 ✅、≥750 ❌ |
| XAG | XAG / close_usd | 290 | 2026-01-27 | 2026-11-12 | ≥250 ✅（临界） |
| XCU | XCU / close_usd | 255 | 2026-03-03 | 2026-11-12 | ≥250 ✅（临界） |
| DJIA / NVDA / AAPL / MSFT / AMZN / GOOGL / META / TSLA / SPY / QQQ | 同名 / close_usd | 各 752 | 2023-11-15 | 2026-11-13 | ≥250 ✅、≥750 ✅ |
| **AMD / GEV / SPCX / SKHYNIX** | 同名 / close_usd | **0** | — | — | **全档 ❌（本地无数据）** |

合计 28 个资产：**24 个可用（≥250 期）**，4 个为 0 样本。≥750 期 22 个，≥4000 期 5 个。

**B. 能力门禁档位 × 达标资产数**

| min_n 档 | 能力数 | 达标资产数 | 说明 |
|---|---|---|---|
| 2 / 3 / 13 | 4 / 1 / 2 | 24 | 变化率、计数、同比类，无样本压力 |
| 30 | 38 | 24 | J 组科研统计全部落此档 |
| 60 | 26 | 24 | 相关/季节/横截面 |
| 100 / 120 | 1 / 3 | 24 | 状态转移、领先滞后 |
| 250 | 17 | 24 | lights 行门槛（`min_rows=250`）刚好满足 |
| 500 | 1 | 22 | XAG/XCU 不达标 |

**C. 数据域覆盖**

| 域 | 实测 | 结论 |
|---|---|---|
| `market.candles`（36 条能力） | 20 个加密对 `close_1d` 各 3377 期 + 28 资产日线 | 充足 |
| `datacenter.panel`（21 条） | 同上，≥3 标的成立 | 充足 |
| `mm_metrics`（9 条） | `funding_rate` 8005、`etf_flow` 11872、`stablecoins_top_10` 8008、`tether_current` 8398 | 充足 |
| `datacenter.social_volume`（1 条） | `social_volume` 2453 | 充足 |
| `mm_events`（3 条） | `mm_events` 548 行（字段 `symbols`，无 `symbol` 列） | 事件数够 30，但**跨标的聚合需按 `symbols` 解析** |
| `mm_metric_vintages`（PIT） | 1,289,146 行 | 充足 |
| **空数据域** | `mm_funding_rate` / `mm_open_interest` / `mm_long_short_ratio` / `mm_taker_volume` / `mm_liquidation` 均 **0 行**；`mm_fear_greed` **1 行** | 拥挤度/持仓类能力本地只能 fail-open；`crypto_fear_greed`（7506 期）可替代情绪源 |

**D. 结论与后续**

1. **L-STAT 覆盖表 ✅**：93 条能力的 `min_n` 与 24 个可用资产可闭合，lights 的 250 门槛刚好满足；
2. **AMD / GEV / SPCX / SKHYNIX 仍为 0 样本** → 归 B-55（云端回填），本地不得伪造；
3. **5 张衍生品明细表为空** → 依赖它们的拥挤度/持仓类能力只能降级，需在图表层标注 `no_data` 而非静默 0；
4. **BTC/ETH/SOL/XAU 仅 1094 期（2023-11 起）** → 二维 Tier A（≥4000 日）不可达，按 Tier B/D 兜底，契约不变；
5. `mm_events` 无 `symbol` 列（只有 `symbols` 文本），事件类能力做标的聚合时必须先解析，属 G-IF1 需冻结的口径 → **已在 §7.10 冻结**：`events` 为事件日期序列（无标的维度），`symbols` 由取数侧解析后过滤传入；
6. **L-STAT 收口证据（v2.62）**：本地 commit `ca6c55a3c6`（35 文件，仅 `54-L1架构能力聚合层/`）→ 推送 `origin/refactor/13-16-merge` → 云端 `sudo -n -u luke -H git pull --ff-only` 落地同一 commit，云端 `capability_manifest.yaml` 实测 **93 条 / 93 唯一**（与本地一致），提交前 `pytest tests -q` **1314 条全绿**、ruff/black 通过 → 统计层完成判定四项全满足。

### §7.10 G-IF1 冻结记录（v2.63，统计层 → 图表层）

- **冻结点**：§7.3 G-IF1；**范围**：§7.4 接口表 A + §7.5 表 B-1 的 `lights[]` 行；**判定**：字段**无遗漏** → ✅ **已冻结，L-CHART 允许开工**（2026-11-15）。
- **核对方法（可复现）**：① 表 A ↔ `contracts/capability_result.schema.json` 逐字段比对；② 实跑 `lights()` 信封过 `jsonschema.validate`；③ AST 扫描 `l1agg/capabilities/*.py` 全部 `build(data=)` 与 `payload` 字典键，确认 ⊆ schema；④ `pytest tests -q` 退出码 0。

#### 10.1 已冻结（图表层可直接消费）

| 冻结项 | 冻结值 |
|---|---|
| 顶层字段 | 固定 7 个 `ok/capability/intent/answer/data/quality/trace_id`，无扩展 |
| `data` 键 | **13 个**：capabilities / params / symbol / pair / name / as_of / window_days / source / items / notes / assets / **lights** / visual |
| 能力级 `gate` | 6 值 `ok/partial/degraded/insufficient_samples/insufficient_history/no_data` |
| 方法级 `gate` | 10 值 = 上 6 值 + `skipped/calculation_failed/empty/rejected`（只在块内方法结果，不入 `block.gate`） |
| `methods` | 非空、`⊆ manifest.methods`（执行覆盖校验强制） |
| `as_of` | **数据时点**＝对齐后最后一个观测日（ISO 日期，UTC 日轴）；不是运行时刻，不带时区偏移 |
| PIT | `mm_metric_vintages.release_ts ≤ as_of`（D-J30）；能力层只读对齐，不回溯改写历史 |
| `quality.snapshot_at` | 可选且**能力层恒不填**（K-12）；图表层见 `null` 不得自行补 |
| 缺失→降级 | `sample_n=0` → `empty`（`ok=false`）；`< min_n` → `partial`+`insufficient_samples`；陈旧 → `partial`+`stale_data`；`partial/empty` 必填 `degraded_reason`，且 `answer` 必含「样本/降级/不足」 |
| `visual` 产图门禁 | V-G1/V-G2/V-G7：`quality.status=="empty"` / 来源块 `gate!="ok"` / `L1_VISUAL_ENABLED=0` → 不产图（键省略） |
| `visual` 上限 | table.rows、series.points 各 500（超限截断 + `truncated=true`）；matrix 20×20；graph 300 节点 / 2000 边；tree 叶子须带能力或 L0 序列 |
| `data.lights` | 行契约 `$defs.lights_row`（11 必填：symbol/class/as_of/axes/strength/summary/light_weights_hash/n/min_rows/status/flags）+ `$defs.lights_axis`（5 必填：state/strength/bucket/evidence/flags） |
| 块内字段 | 仅 §7.4 **表 A-1** 登记的 D-E10/E12/E15/E16/E17/E18/E19 七个能力；其余不承诺 |
| `mm_events` 聚合口径 | 事件类能力（D-E04 / D-E09 / D-G23）的 `events` 入参是**事件日期序列，无标的维度**；`mm_events.symbols` 文本列不进入能力层，跨标的聚合由取数侧解析 `symbols` 并按标的过滤后传入；能力层只回显 `event_type` |

#### 10.2 转下游冻结（不阻塞图表层开工）

| 项 | 归属 |
|---|---|
| T1–T4 实体登记（A-5） | ✅ 已关闭（v2.64，K-11） |
| 轴名错位 `adx`/`cycle`（B-1） | ✅ 已关闭（v2.64，K-02，B-2A） |
| 阈值双轨 0.70/0.40 vs 0.7647/0.5724（B-2） | ✅ 已关闭（v2.64，K-03） |
| `band`/`flags` 未产出（B-3） | ✅ 已关闭（v2.64，K-06，信号侧契约） |
| `snapshot_at` 生产者 | 待 19-DAL 快照层（K-12） |
| `weights mode` / `pool_version` / 非加密 handoff（B-4/B-5/B-7） | L-SIGNAL（K-04/K-05/K-07） |

#### 10.3 图表层禁止假设（硬边界）

1. **禁止自行取数/重算**：不读 `trading.db`、不调 `run_capability` 重算统计量；只消费信封、`data.visual`、`data.lights`。
2. **禁止读取未登记的块内字段**：`data.capabilities[cid]` 内部未闭合，表 A-1 之外字段属契约外依赖。
3. **禁止改写时间语义**：`as_of` 不是运行时刻、不补时区；`snapshot_at` 不得自行生成。
4. **禁止假定结构**：`items` 元素结构未冻结；`notes` 可能为单串而非数组。
5. **禁止在降级态造图**：`gate != ok` 或 `quality.status == empty` 时不得产图或补 0。
6. **禁止假定 matrix/tree 有生产者**：matrix 当前无 producer，使用前须先登记。
7. **禁止假定事件能力有标的维度**（`symbols` 需取数侧解析）。
8. **禁止把 `lights[].strength` 当方向分**：`light_weights`（0.40/0.25/0.15/0.20）≠ `axis_weights`（40/25/20/15），三权分立。
9. **禁止伪造血缘**：`visual.source_capability` 必须等于信封 `capability`，不得输出 `T*`。

#### 10.4 本次实测证据

- **A-7 契约缺口**：`lights()` 输出 `data keys = ['capabilities','lights','params']`，旧 schema 关闭 `data` 扩展 → `Additional properties are not allowed ('lights' was unexpected)`；已补 `data.lights` 与行/轴 `$defs`，并新增回归测试 `test_envelope_validates_against_json_schema`（`tests/test_lights.py`）。
- **AST 扫描**：`build(data=)` 键集合 = {as_of, assets, capabilities, items, name, notes, pair, params, source, symbol, window_days}，其余 93 出口无越界；`lights` 是唯一例外且已登记。
- **回归**：schema 变更后 `pytest tests -q` 全绿（退出码 0）；`capability_manifest.yaml` 仍 **93 条**（本冻结不增删能力出口）。
