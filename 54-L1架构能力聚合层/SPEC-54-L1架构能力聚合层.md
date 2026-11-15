# SPEC-54 L1 架构能力聚合层

- **版本**: v1.53 ｜ **日期**: 2026-11-15 ｜ **状态**: 🟢 完整版（v1.53 上线 TD §6.4.5 #35 周期调度：`dreambuddy-mers.timer` 每日 08:20 CST 全量跑 29 job / 5,220 单元，`Persistent=true`，`--prune-days 90` 只清 `relationship_eval` 历史行、`relationship_state` 永久保留；新增 `RelationshipRegistry.prune_before()` + 回归测试，unit 文件入库 `deploy/systemd/`；可执行出口保持 **52 个**；v1.52 迁移 scope 声明：D-A11/D-A12 → `datacenter.correlation`、D-A04 → `datacenter.percentile`，出口数不变 **52 个**；v1.51 关闭 TD §6.4.5 #35：MERS S3 全量真实数据验收在云端完成——29 job / 5,220 单元（20 资产 `close_1d` + 9 个宏观/情绪/资金费率指标对齐 BTC 日轴，min_n=250），BH-FDR 后 `gate_pass=1,057`（20.25%），`method_gate` ok 3,654 / not_applicable 1,566 / **failed 0**，连续三轮 `gate_pass` 完全一致且每轮复跑 `added=0`，`stable=1,057` / `candidate=4,163`；验收中发现并修复 B11 空分桶 `float(None)`（失败 95→0，commit `2b5b8b8a59`）；v1.50 新增 D-A05 z-score 出口（`datacenter.percentile`，复用方法层 S26 winsorize p1/p99），可执行出口 51 → **52 个**；v1.49 新增「金融价尺系统」子 SPEC（待评审、未落地代码）；v1.48 新增 D-E20 新闻统一出口（L1S-03：只读 `mm_metrics.social_volume` 的 `news_count_24h`/`social_volume` 观测成统一信封 + 禁用词自检，不编造条目），可执行出口 50 → **51 个**；v1.47 关闭 §6.4.4 #32–#34：C11 节前效应落地并接入 D-E04（节假日由价格日期轴「工作日缺失」派生，>10 工作日缺口按数据缺口排除）、D-G25 尾部相关接线（复用 P13 下行/上行双尾 + 尾部共现样本门禁）、D-J05 周期/频谱接线（T25/T26/C14 并列 + ≥2 周期/2,920 日跨度门禁），可执行出口 48 → **50 个**，方法层 392 全实现；v1.46 将 D-E14 二维状态按 Tier B/D 兜底落地：4×4=A（≥4,000 日）/3×3=B（≥2,250 日）/2×2=D（≥1,000 日），每格非重叠 ≥250，三档均不达标回退一维并披露 `insufficient_2d`，Tier/格数/每格 n 强制显式返回；v1.0 + S1–S5 五级能力路线 + S1.0 硬前置 + S4 条件外推收口 + MERS 分阶段 + §3.5 四层分工，见 §13–§17；v1.45 登记 L1 交易层 D-E15–D-E19 五个出口（趋势曲线/聚合曲线/分组看板/资金流向/点亮投影），可执行出口 44 → **48 个**；v1.44 完成前端 D-A 组 14 个及 D-B08/D-B09/D-G08/D-G09 共 18 个 cue 分派，可执行出口保持 **44 个**；v1.43 接入 D-G09 波动率目标换算（P02），可执行出口 **44 个**；v1.42 接入 D-G08 12-1 动量（F14 窗口切片），可执行出口 **43 个**；v1.41 接入 D-B09 距 ATH 回撤（复用 D20/D21），可执行出口 **42 个**；v1.40 接入 D-B08 趋势斜率（T08/T09），可执行出口 **41 个**；v1.39 接入 D-A16 稳定币规模增速（S16 多窗口），可执行出口 **40 个**；v1.38 接入 D-A15 ETF 净流入滚动和（S20 滚动均值 × 窗口），可执行出口 **39 个**；v1.37 接入 D-A13 极端事件频率（S11 阈值 + 纯计数），可执行出口 **38 个**；v1.36 接入 D-A12 领先滞后相关（M11/M12），可执行出口 **37 个**；v1.35 接入 D-A11 双序列滚动相关（M04），可执行出口 **36 个**；v1.34 接入 D-A10 实际利率（S16 派生），可执行出口 **35 个**；v1.33 接入 D-A09 环比（S16），可执行出口 **34 个**；v1.32 接入 D-A08 同比（S16），可执行出口 **33 个**；v1.31 接入 D-A07 回撤（复用 D-E10 的 D20/D21），可执行出口 **32 个**；v1.30 接入 D-A06 年化波动率（F05），可执行出口 **31 个**；v1.29 接入 D-A04 历史分位（S25），可执行出口 **30 个**；v1.28 接入 D-A03 CAGR（S19），可执行出口 **29 个**；v1.27 接入 D-A02 变化率（S15/S16），可执行出口 **28 个**；v1.26 接入 D-A01 历史序列（S25），可执行出口 **27 个**；v1.25 接入 D-J30 PIT/release_ts 全局能力（SC90/R02），可执行出口 **26 个**；v1.24 接入 D-G14 EWMA 波动/协方差（P07/T19），可执行出口 **25 个**；v1.23 接入 D-J24 相关网络与社区发现（M05/M21/SC71/SC72），可执行出口 **24 个**；v1.22 接入 D-J22 PCA/SVD/因子分析（M19/M20/SC31/SC32/SC33），可执行出口 **23 个**；v1.21 接入 D-G20 分位组合与单调性检验（B11/B16/Q04），可执行出口 **22 个**；v1.20 接入 D-G19 IC/ICIR/衰减表（B13/B14/B15/Q01/Q02/Q03），可执行出口 **21 个**；v1.19 接入 D-G16 组合 VaR/CVaR（D17/D18/P09/P10），可执行出口 **20 个**；v1.18 接入 D-J02 季节强度与调整（C13/T10/SC91），可执行出口 **19 个**；v1.17 接入 D-J04 变点检测（T22/T23/SC49/SC50/SC51），可执行出口 **18 个**；v1.16 将 B06 二维交叉表纳入 D-E07，输出相邻状态联合计数并与 B07 行归一化概率对齐，可执行出口保持 **17 个**；v1.15 接入 D-G23 事件窗均值调整 CAR + Patell/BMP（Q10/Q11），可执行出口 **17 个**；v1.14 接入 D-E14 一维相关状态条件分布（R02 PIT + B05/B10/R01/R08），可执行出口 **16 个**，二维 T2 仍受样本与状态特征约束；v1.13 接入 D-E04 事件研究窗（F19/F21/F23）与 D-E09 计数与共现（R09/B17/R10）能力出口，可执行出口 **14 个**；v1.12 冻结 D-A14/F26 的 `level` 阈值为 A 分位法（分值历史分布 p20/p60/p80 → 极低/低/偏高/高），接入 D-A14 能力出口，样本不足/分布退化降级不补阈值；v1.11 接入 D-G22 显著性出口（Q06 HAC t + Q07 Deflated Sharpe），解除 h>1 重叠前瞻收益的推断阻塞；v1.10 打通宏观事件历史回填通道（2015–2026 实测 542 条），D-E04/D-E09 由「事件表仅 16 行」改为「待云端入库后接线」；v1.9 D-E12/R18 时空对齐切片交付，并纠正 R02 与矩阵 TopK/C18 的过期状态；S5 对外推荐仍未开放；v1.8 D-E05 矩阵 TopK、D-E11/C18、D-E01 与 MERS S3 内部内核交付；v1.7 D-E02 三层接线与 T0.5 首版交付；v1.6 调研对齐 R02 PIT 双口径与能力状态边界；v1.5 回写日线收盘锚点修复；v1.4 回写 E 组能力层落地与 `stat_query` 意图合并，整体进度由 TECHNICAL_DESIGN §6 汇总）
- **归属**: 54-L1架构能力聚合层（L1 确定性数据能力的唯一聚合出口）
- **上游约束**: 19-DAL Schema/Repo 契约、18-数据获取中心 `DataRecord`、9-基本面分析评分口径、34-前端应用训练系统（意图/SFT 与 route_confidence）
- **下游影响**: 3.1-FRONTEND `/api/data/query`、`/api/fundamental/**`、`/api/agent/chat`、L1 意图注册表（TS/Python 双端）

---

## §0 Executive Summary

### 0.1 一句话定位

**54 不采集、不评分、不做交易信号**，只做一件事：把 18/19/9/23/43 已有的存量数据能力，聚合成 L1 可零 token 执行的**六类能力面**（现在/过去/统计/预测/含义/跨维验证），并把同一套聚合结果同时供 L1 直答与前端基本面模块消费，消灭“前端能看、对话答不了”和“两套口径”。

### 0.2 七条决策（ADR）

| # | 决策 | 依据 |
|---|------|------|
| ADR-1 | **只聚合不重采集**：18/19 是唯一数据源，54 内禁止新采集器与私有落库 | 避免第四套数据口径；18 已有 348,543 行 / 455 指标的历史底座 |
| ADR-2 | **不重复计算基本面评分**：9-基本面分析的模块评分/阶段为 SSoT，54 只消费 | 评分口径变更必须单点生效 |
| ADR-3 | **只读 DAL**：所有过去/统计能力经 `query_*` 只读接口，禁止 54 写 `mm_*` | DAL 写入只属 18/19 采集与回填链路 |
| ADR-4 | **六类能力面统一注册**：每项能力 = `(capability_id, intent, executor, contract, degrade_policy)`，由 Capability Registry 声明 | 新增能力不改造路由，注册即用 |
| ADR-5 | **数据类能力改门禁口径**：`now/past/stat` 类能力以「**指标别名命中 + 查询类型词命中 + 非文档/事件意图 + 参数完整 + 数据质量合格**」为门禁，不再依赖记忆相似度 `route_confidence`；`insight/predict` 类仍走 `route_confidence ≥ 0.65`。`deterministic ≠ 无校验` | 对齐「L1 用确定性能力，不做复杂门禁」；实测「查询比特币价格」记忆匹配仅 0.187 却可确定性作答；三条件用于防误路由（B2） |
| ADR-6 | **FAIL-OPEN + 质量元信息强制**：任何返回必须带 `quality{status, sample_n, span, is_stale, degraded_reason}` | 分位/统计无样本时必须显式降级，禁止静默给数 |
| ADR-7 | **L1 与前端同源**：`/api/fundamental/{module}/snapshot` 的 `metrics/timeseries` 与 L1 执行器共用同一 Aggregator | 前端路由 `src/app/api/fundamental/[...path]/route.ts:69` 硬编码 `timeseries: []`，9 的序列为随机游走合成，必须统一替换 |

### 0.3 不做什么

| 禁止 | 原因 |
|---|---|
| 不新建任何数据采集器 / 不新建数据库表 | 18/19 已覆盖；新采集属 18 职责 |
| 不修改 `mm_metrics` Schema | DAL ADR-19-005 已冻结 Schema 演进策略 |
| 不在本层做 LLM 摘要 | 含义解释走「模板释义库 + 可选 L2 LLM 后置润色」 |
| 不生产交易信号 / 不改风控阈值 | 交易信号属 22/23/43，54 只做数据解释 |
| 不做跨模块评分融合（如把 6 维加权成总分） | 评分融合属 9/23，54 只并列呈现与一致性判定 |

---

## §一、背景与现状（调研结论）

### 1.1 数据资产实测

| 层 | 事实 | 证据 |
|---|---|---|
| 18 采集 | `DataRecord` 统一契约 + 调度器，覆盖 FRED 宏观、Binance 资金费率/多空比、恐惧贪婪、CoinGecko 市值/板块、ETF 流向、稳定币、清算、鲸鱼流、社交声量 | `18-数据获取中心/data_center/scheduler.py`、`backfill_fred_history.py`、`collect_missing_data.py` |
| 19 DAL | 7 域 21 表；`mm_metrics(sub_category, metric_name, timestamp, metric_value)` 实测 **348,543 行 / 5,304 sub_category / 27,290 个 sub::metric 组合 / 455 个不同指标名**，`DGS10` 回溯至 1962、`NASDAQCOM` 1971、`crypto_fear_greed` 2018 起日频 4,066 条 | `19-数据访问层/docs/SCHEMA_DESIGN.md`、`sqlite3 只读实测` |
| 19 查询能力 | 已具备时间点/区间查询：`query_latest_metric`、`query_metric_by_time`、`query_fear_greed_by_time`、`query_funding_by_time`、`query_open_interest_by_time`、`query_liquidation_by_time`、`query_long_short_ratio_by_time`、`query_taker_volume_by_time` | `dreambuddy_dal/implementations/sqlite_unified/market_macro_impl.py` |
| 9 计算层 | `DalSnapshotProvider._history()` 已是真实区间查询；但 `_make_timeseries()` 为随机游走合成序列 | `9-基本面分析/dal_snapshot_provider.py`、`data_collector.py` |
| 34 L1 现状 | 10 个确定性执行器；`route_confidence` 阈值 SSoT = 0.65；意图 golden set 311 条 | `3.1-FRONTEND/scripts/l1_route_signal.py`、`data_query_executor.py`、`34-前端应用训练系统/l1_intent_golden.jsonl` |
| 前端基本面 | 11 个模块（macro/onchain/sentiment/valuation/flow/breadth/capital_flow/intermarket/news/narrative/calendar）；`ModuleSnapshot.timeseries` 在路由层**硬编码为 `[]`**（`src/app/api/fundamental/[...path]/route.ts:69`），9-基本面 `generate_timeseries` 仍被 `ml_trade_service_v2` 等消费 | `3.1-FRONTEND/scripts/fundamental_snapshot.py`、`src/app/api/fundamental/[...path]/route.ts`、`9-基本面分析/data_collector.py` |

### 1.2 能力缺口量化

| 维度 | 现状 | 判定 |
|---|---|---|
| 现在（now） | DAL latest + OKX ticker + 衍生品/ETF/情绪/宏观 | 90% |
| 过去（past） | 数据真实且深厚，但 `data.dal_query` 只取 latest、snapshot 不产序列、9 的序列为合成 | 30% |
| 统计（stat） | 估值百分位（bdsm）、fedwatch 隐含概率、23 层力度分位 | 35% |
| 预测（predict） | bdsm/bcrm2 阶段与置信度、event.state 前瞻、rs_cases | 35% |
| 含义（meaning） | `INSIGHT_KNOWLEDGE` 15 条规则，仅「指标×方向→一句话」 | 40% |
| 跨维验证（cross） | `exec_contradiction_insight` 通用四维一致性；未与具体指标绑定 | 55% |

**核心结论**：缺口集中在「读取与统计暴露」，不在「数据采集」。因此本 SPEC 全部工作为只读聚合，边际成本低。

---

## §二、目标与非目标

### 2.1 目标

1. 前端 11 个基本面模块覆盖的**每一个指标**，均可在 L1 用自然语言确定性问出（覆盖 100%，以 §4.1 映射表为验收基线）。
2. 每个核心指标同时具备：当前值、过去序列、统计位置（分位/z-score）、含义解释、至少 1 个关联维度交叉验证。
3. L1 数据类直答时延 P95 ≤ 800ms（对齐 `RECALL_SLA_MS=800`），零 token。
4. 前端 `timeseries` 全部来自真实 DAL 序列，彻底移除合成序列。

### 2.2 非目标

- 不做新指标采集（如美股财务三表），缺口统一登记为 18 需求。
- 不做预测模型训练；预测能力只做「已有统计/概率资产的结构化暴露 + 明确不确定性」。

---

## §三、架构设计

### 3.1 分层与数据流

```
用户消息
  └─ L1 意图识别（TS l1-intent-registry.ts / Python _FALLBACK_PATTERNS，双端一致）
       └─ 54 Capability Router（capability manifest 命中）
            ├─ NowAggregator   ── L0 datacenter.record / market.ticker / 9 snapshot
            ├─ SeriesAggregator ── L0 datacenter.series  ── DAL query_metric_by_time
            ├─ StatsEngine      ── SeriesAggregator 输出（分位/z-score/波动/变化率）
            ├─ PredictAggregator ── fedwatch / yijing.bdsm / event.state / rs_cases
            ├─ MeaningEngine    ── 指标释义库（YAML）+ 当前水平映射
            └─ CrossCheckEngine ── evolution.contradiction / 23 dimension_force_evaluator
                 └─ 统一 CapabilityResult 信封（含 quality）
                      ├─ L1 直答 answer（模板渲染）
                      └─ /api/fundamental/{module}/snapshot（timeseries/metrics）
```

### 3.2 目录规划

```
54-L1架构能力聚合层/
├── SPEC-54-L1架构能力聚合层.md
├── capability_manifest.yaml          # 能力注册表（唯一事实源）
├── aggregators/
│   ├── now_aggregator.py
│   ├── series_aggregator.py
│   ├── predict_aggregator.py
│   └── crosscheck_aggregator.py
├── stats/
│   ├── engine.py                     # percentile / zscore / cagr / volatility
│   └── quality.py                    # 缺失率/坏值/样本量/陈旧度
├── meaning/
│   ├── metric_glossary.yaml          # 指标释义（是什么/怎么读/水平分档）
│   └── engine.py
├── contracts/
│   ├── capability_result.schema.json   # 唯一契约事实源（quality/answer 顶层化）
│   └── series_query.schema.json
├── reports/
│   └── metrics_health.json             # P0 覆盖体检产物
└── tests/
    ├── test_series_aggregator.py
    ├── test_stats_engine.py
    └── test_capability_manifest.py
```

### 3.3 能力注册表（`capability_manifest.yaml`）

```yaml
version: 1
capabilities:
  - id: metric.series
    intent: metric_series
    mode: deterministic            # deterministic | gated
    data_scope: [datacenter.series]
    params: {metric_ref: required, days: optional, freq: optional}
    degrade: {on_missing: l2_handoff, on_no_history: answer_partial}
  - id: metric.percentile
    intent: metric_percentile
    mode: deterministic
    data_scope: [datacenter.series]
    params: {metric_ref: required, lookback: optional}
  - id: metric.meaning
    intent: metric_meaning
    mode: deterministic
    data_scope: [datacenter.record, datacenter.series]
  - id: metric.crosscheck
    intent: cross_check
    mode: gated
    data_scope: [evolution.contradiction, datacenter.record]
  - id: metric.predict
    intent: metric_predict
    mode: gated
    data_scope: [event.state, yijing.bdsm]
```

`mode: deterministic` 表示 ADR-5 绕过记忆相似度门禁；`mode: gated` 仍需 `route_confidence ≥ 0.65`。

### 3.4 与既有模块的边界

| 模块 | 关系 |
|---|---|
| 18 数据获取中心 | 唯一采集入口；54 发现的缺口登记为 18 需求单 |
| 19 数据访问层 | 唯一读取入口；54 仅调用 `query_*` |
| 9 基本面分析 | 模块评分/阶段 SSoT；54 复用其取值，不重算 |
| 23 四层闭环 | 提供 `dimension_force_evaluator` 力度/分位，crosscheck 复用 |
| 34 训练系统 | 新增意图需同步补 golden set 与 TS 注册表 |
| 3.1 前端 | `/api/fundamental/**` 与 L1 共用聚合结果 |

---

### 3.5 四层分工：方法库 / 能力登记 / 场景包 / 评估层（v1.3 对齐）

> 本节用于消除三份文档的职责重叠：**METHOD_LIBRARY（怎么算）→ TECHNICAL_DESIGN 能力登记 + 本 SPEC（能问什么）→ 场景包（一次问全）→ MERS/Discovery（是否稳定）**。

| 层 | 载体 | 回答什么 | 命名单位 | 是否新增方法 | 门禁语言 |
|---|---|---|---|---|---|
| ① **方法层** | [METHOD_LIBRARY.md](./docs/METHOD_LIBRARY.md) + 两份 RESEARCH 补强 | 某个统计量怎么算、需要多少样本、D1/D2/D3 哪级 | 方法 ID（`T13`/`M01`/`B13`…）+ `R01–R18` 关系原语 | **是（唯一 SSoT）** | `sample_n`、D 级 |
| ② **能力层** | [TECHNICAL_DESIGN.md](./docs/TECHNICAL_DESIGN.md) 能力登记 + 本 SPEC §四/§五 | 用户一句话能问什么、走哪个 scope、返回什么信封 | `D-A/B/C/E/G/J/K/V` 能力 ID | 否（只组合 + 绑 scope） | `quality{status,sample_n,span}` |
| ③ **场景包** | [SPEC-54-延续性统计分析模块.md](./SPEC-54-延续性统计分析模块.md)（`l1agg/persistence/`） | 一个资产「有没有记忆」的一站式画像 | `D-E13`（画像）；A1–A7 全部映射既有方法 ID | 否（纯编排） | 每方法门禁 + 画像 `status` |
| ③-2 **场景包（价尺）** | [SPEC-54-金融价尺系统.md](./SPEC-54-金融价尺系统.md)（`l1agg/fns/`，规划） | 用「社会必要劳动时间」这把尺子量：某资产**贵还是便宜**（劳动小时计价 / 价值偏离 / 成本锚 / 通胀二分解 / SNLT-II 实现缺口），并用**资金流（方向·速度·速率·滞后弹性）做交叉验证** | `D-V01–D-V07`；方法 `V01–V23`（新增 V 组） | **是（唯一新增方法组的场景包，ADR-F8）** | 可证伪 H1–H5 + `market_regime`/`asset_regime` 双状态机 + `flow_confirm` |
| ④ **评估层** | 本 SPEC §14 MERS + §15 Discovery + §17.1.3 的 S5 回测排名 | 某关系/方法在某资产某期限上**是否稳定、是否推荐** | 评估单元 `eval_id` | 否（批量跑②③的方法） | RankIC / `p_adj` / holdout 同号 / 随机数据 `stable=0` |

**三者关系一句话**：方法库是**体检项目表**，能力层是**挂号窗口**，场景包是**体检套餐**，MERS/Discovery 是**年度复查与排名**。

#### 3.5.1 延续性统计分析 vs 统计回测相关性（最易混的一对）

| 维度 | 延续性统计分析（③ 场景包） | 统计回测相关性（④ 评估层） |
|---|---|---|
| 目标变量 | 固定为**本资产价格的前瞻收益** | 关系单元的**稳定性评分**（不针对某个资产写死） |
| 问题 | 「这个序列自身有没有记忆」 | 「指标 X 与资产 Y 在 h 期限上的关系是否可复现」 |
| 范围 | 单资产、无条件、一次性 | 跨序列、条件化、周期性重跑 + 状态机 |
| 输出 | 一张画像（7 个数字 + 一句话） | `relationship_registry.db` 排序表 + 推荐 |
| 数据门槛 | 仅需价格（四资产各 1,094 点 ✅） | 价格腿已够（28 龙头已绑定）；真正缺口是加密域指标仅 14–44 天、专用表 0 行，全库与 BTC 日频重叠 ≥60 天仅 26 条 |
| 共同点 | 共用方法库、共用 `l1agg/align.py`、共用门禁语言（`n≥`、`p_adj`、`align_method`） | 同左 |

#### 3.5.2 四条硬约束（SSoT）

1. **前瞻收益唯一实现 = `l1agg/align.forward_returns`**。23 的 `FactorICSelector` 现有 `shift(-h).rolling(h).sum().shift(-h+1)` 在 `h>1` 时多位移 `h-1` 天（§17.1.3 已知缺陷 1），S5 前必须改为调用 `align` 或整体废弃；persistence 的 A7 与 MERS 的 B13–B16 必须调同一函数。
2. **IC 的三处消费分工**：persistence A7 = 单资产描述（重叠 + 非重叠相位双口径）；MERS B13–B16 = 跨序列评估（含 `p_adj`/holdout/状态机）；23 = S5 前只保留历史产物，不再新增计算。
3. **能力登记不重复计数**：`D-E13` = `D-E07`（状态转移）+ `D-E08`（分箱/IC）+ T 组方法的**场景编排**，不新增方法 ID；`D-E14` = 相关状态条件分布，依赖 `D-E05/D-E06/D-E11`。方法库改动（如 T13 口径）必须回写场景包测试。
4. **R02 PIT 双口径**：`pit=false`（全样本分位边界）只能作样本内回顾，不得进入 T0.5/T2/MERS；`pit=true` 要求每个历史时点只使用当时可见数据，宏观数据还须满足 `release_ts≤as_of`，是上述场景的唯一合法口径，**已实现**（`conditional.py::r02_percentile_forward`：逐时点滚动分位 + `release_ts` 过滤），能力出口已由 D-E02 接线，A8/T0.5 经此出口交付。算法与输出字段唯一定义见 METHOD_LIBRARY §16.1。

#### 3.5.3 T 阶段 ↔ S 级映射（两套编号必须成对出现）

| persistence 阶段 | 对应 S 级 | 说明 |
|---|---|---|
| T0 ✅ | **S3 的「自身延续性」子集** | 不依赖跨资产回填，已交付 |
| T0.5 ✅ | **S3 → S4 之间** | 单资产状态 → 前瞻分布（R01/R02/R08）；首版 h=1，**已经 D-E02 出口交付**（A8 编排 `persistence/profile.py::conditional_distribution`，`pit=true`，样本不足自动 4→2 桶并披露 `effective_n/nonoverlap_n`） |
| T1a | S3 前置（特征） | 自身状态特征，归 align/特征层 |
| T1b | **S2 因子池** + S3 前置 | 跨资产相关特征；价格腿已绑 28 龙头，加密域指标待回填 |
| T2 🟡 | **S4** | 多维状态 → 前瞻条件分布；D-E14 一维 h=1/2 首版已交付（`capabilities/stats.py::conditional_distribution`），二维 4×4 仍受样本与 F1–F12 状态特征约束 |
| T3a/T3b | **S5**（MERS 下游） | L2 模型，须过 MERS 门禁 |
| T3c/T4 | S5 之后 | 可选 |

> `T*` 编号仅在 persistence 域内有效；跨文档引用必须同时给出 S 级定位，禁止只用 T 编号（避免两套路线漂移）。另：方法库 §14 使用 `S0–S7`（方法实施与能力接线阶段），与本 SPEC 的 `S1–S5` **不是同一编号体系**，映射见 METHOD_LIBRARY §14 末尾「三套路线编号的映射」。整体进度和下一阶段顺序以 [TECHNICAL_DESIGN §6](docs/TECHNICAL_DESIGN.md) 为汇总。

---

## §四、能力矩阵

### 4.1 前端 11 模块 → L1 能力映射（验收基线）

| 模块 | 必须可问的指标（示例） | now | past | stat | predict |
|---|---|---|---|---|---|
| macro | DXY、US10Y、VIX、CPI/PPI 同比、M2、Fed 利率、WALCL、fedwatch | ✅ | ⬜ | ⬜ | ⬜ |
| onchain | 难度变化、内存池、剩余区块、活跃地址、大额转账、交易所余额 30d 变化 | ✅ | ⬜ | ⬜ | — |
| sentiment | 恐惧贪婪、社交声量、新闻量、BTC 市占率 | ✅ | ⬜ | ⬜ | — |
| valuation | 估值阶段、百分位（bdsm） | ✅ | ⬜ | ✅ | ⬜ |
| flow | ETF 总流入/分 issuer、资金费率、多空比、鲸鱼净流、清算、稳定币流通量 | ✅ | ⬜ | ⬜ | — |
| breadth | USDT/USDC 规模、DeFi TVL、全球市值 24h、板块涨跌家数 | ✅ | ⬜ | ⬜ | — |
| capital_flow | 资金流向与强度 | ✅ | ⬜ | ⬜ | — |
| intermarket | 美股/黄金/原油/美元与加密联动 | ✅ | ⬜ | ⬜ | — |
| news | 新闻情绪与事件 | ✅ | ⬜ | — | — |
| narrative | 叙事强度 | ✅ | ⬜ | — | — |
| calendar | 财经日历与事件时点（概率类归 macro/fedwatch） | ✅ | ⬜ | — | — |

（⬜ = 本 SPEC 新增，✅ = 已有）

### 4.2 六类能力定义

| 类 | 定义 | 输出字段 |
|---|---|---|
| now | 最新值 + 时间戳 + 与上期变化 | `value, ts, change, change_pct` |
| past | 区间序列 + 聚合统计 | `points[], agg{mean,min,max,cagr,volatility}` |
| stat | 当前值在历史分布中的位置 | `percentile, zscore, rank, lookback, sample_n` |
| predict | 已有概率/阶段/前瞻的结构化暴露 | `value, horizon, source, confidence, caveat` |
| meaning | 指标是什么/怎么读/当前处于哪个档 | `what, how_to_read, level, implication` |
| cross | 主维与关联维同向/背离 | `primary, peers[{dim,dir,strength}], verdict{consistent|divergent|mixed}` |

---

## §五、接口契约

### 5.1 L0 新增 scope：`datacenter.series`

```jsonc
// 请求
{"scope": "datacenter.series",
 "params": {"sub_category": "CPIAUCSL", "metric_name": "value",
            "days": 365, "freq": "D", "max_days": 1825,
            "agg": ["mean","cagr","volatility"]}}

// 响应（统一 L0 信封 + 54 质量块，quality 固定顶层）
{"ok": true, "source": "dal", "degraded": false, "timestamp": "...",
 "data": {
   "points": [{"ts": 1700000000, "value": 308.4, "unit": "index"}],
   "agg": {"mean": 305.1, "cagr": 0.031, "volatility": 0.004},
   "outlier_flags": []
 },
 "quality": {"status": "good", "sample_n": 252, "span": ["2025-11-14","2026-11-14"],
             "missing_rate": 0.0, "is_stale": false, "degraded_reason": null}
}
```

规则：
- `freq` 归一：`D/W/M`（宏观日频、链上小时频统一降采样到日）
- **入参校验**：`sub_category` 需命中别名白名单或 `^[A-Za-z0-9_./-]{1,64}$`；`days ≤ max_days`（默认 1825），超限截断并在 `quality.degraded_reason=clamped_to_max_days`
- **quality 位置**：只在顶层出现，`data` 内禁止嵌套 `quality`（字段以 `contracts/capability_result.schema.json` 为准）
- 最小样本 `sample_n < 30` → `status=partial`，统计字段返回 null 并写 `degraded_reason=insufficient_samples`
- 坏值过滤：`metric_value IS NULL`、已知哨兵值（如 `tvl_bln=0.0`）剔除并计入 `missing_rate`
- 时间统一 unix 秒（UTC），响应给 ISO 双写

### 5.2 L0 新增 scope：`datacenter.percentile`

```jsonc
{"scope": "datacenter.percentile",
 "params": {"sub_category": "crypto_fear_greed", "metric_name": "value", "lookback_days": 1095}}
→ {"data": {"value": 27, "percentile": 12.4, "zscore": -1.31,
            "lookback": ["2023-11-14","2026-11-14"], "sample_n": 1096},
   "quality": {...}}
```

### 5.3 统一 CapabilityResult 信封

```jsonc
{"ok": true, "capability": "metric.percentile", "intent": "metric_percentile",
 "answer": "恐惧贪婪指数当前 27（恐惧），处于近 3 年 12.4% 分位…",
 "data": {"now": {...}, "past": {...}, "stat": {...}, "meaning": {...}, "cross": {...}},
 "quality": {"status": "good|partial|empty", "sample_n": 1096,
             "is_stale": false, "degraded_reason": null, "sources": ["dal:mm_metrics"]},
 "trace_id": "..."}
```

约束：
- 顶层 `answer` 禁止为空串（`data` 只放业务字段，不再嵌 `answer`/`quality`）；契约以 `contracts/capability_result.schema.json` 为唯一事实源
- 无法作答时 `ok=false` 并走 L2（`l1_no_executor` 同款干净交接）
- `quality.status != good` 时 `answer` 必须包含降级说明（「样本不足，仅返回当前值」）

### 5.4 新增 L1 意图（TS 与 Python 必须同步）

| intent | 识别要点 | 执行器 | mode |
|---|---|---|---|
| `metric_series` | 注册表命中 + 查询类词（多少/最新/走势/历史/数据/现在…，无解读词）；注册表含 18/19/9/前端 11 模块与调研新增能力 | `exec_metric_series` | deterministic-keyword |
| `whale_flow` | 巨鲸/鲸鱼/大户 + 动向/流入流出/转账/最近（排除「说明什么」等解读） | `exec_whale_flow` | deterministic-keyword |
| `calendar_event` | 议息/FOMC/非农/CPI/PPI + 什么时候/下次/日程；或「经济日历」 | `exec_calendar_event` | deterministic-keyword |
| `metric_percentile` | 指标词 + 分位/百分位/历史位置/z-score/贵不贵 | `exec_metric_percentile` | deterministic |
| `metric_meaning` | 指标词 + 是什么意思/怎么读/怎么看/含义 | `exec_metric_meaning` | deterministic |
| `cross_check` | 指标词 + 验证/印证/背离/共振/是否一致 | `exec_cross_check` | gated |
| `metric_predict` | 指标词 + 预测/概率/情景/后续会 | `exec_metric_predict` | gated |

同步清单（缺一不可）：
1. `3.1-FRONTEND/src/lib/l1-intent-registry.ts`（fallbackPattern，顺序置于 data_query 之前）
2. `3.1-FRONTEND/scripts/l1_route_signal.py`（`_FALLBACK_PATTERNS` + `EXECUTORS`）
3. `34-前端应用训练系统/l1_intent_golden.jsonl`（每意图 ≥ 20 条，含口语/简短/多实体变体）
4. TS 侧 `ROUTE_CONFIDENCE_THRESHOLD_HIGH` 保持 0.65（SSoT，禁止另立）

**命中与顺序约束（B2 防误路由）**：
- 能力命中三条件：`指标别名命中` AND `查询类型词命中` AND `非文档/事件意图`
- fallback 顺序固定：`doc_search → whale_flow → event_line_query → calendar_event → event_analysis → metric_* → data_query / price_query`
- `deterministic` 不等于免校验：仍需参数完整性与数据质量校验，校验失败走 L2
- `deterministic-keyword`（`whale_flow` / `calendar_event`）：关键词命中即确定数据口径，直接单维检索直答，**不参与 recall 密度门控**（`route_signal.reasons=["deterministic_keyword_registry"]`）；0.65 阈值本身不变，仍只约束语义意图
- 关键词注册表 SSoT：`54-L1架构能力聚合层/l1agg/series_catalog.py` 的 `WHALE_METRICS` / `EVENT_KINDS` / `CURATED_SERIES`（新增数据词只加一行）
- golden set 必须新增**负样本 ≥10 条**（例：「CPI 文档在哪」→`doc_search`；「CPI 什么时候发布」→`calendar`；「CPI 和 BTC 有关系吗」→`cross_check`）

#### 5.4.1 三段式注册表（数据关键词注册 → 意图识别 → 索引输出）

| 层 | 载体 | 覆盖 | 维护方式 |
|---|---|---|---|
| Tier-1 别名 | `METRIC_ALIASES` | 27 组历史指标别名 | 手工，兼容旧问法 |
| Tier-2 curated | `CURATED_SERIES` | 前端 11 模块 + 18/19 核心 + 调研新增（巨鲸/ETF/链上持仓/RWA/爆仓/稳定币/期权/周期信号）≈90 条 | 新增能力加一行；关键词去空格归一（`ETF总净流入` ≡ `ETF 净流入`） |
| Tier-3 全量目录 | `l1agg/data_catalog.json` | `mm_metrics` 全量 27,290 个 (sub_category, metric_name) | `python3 -m l1agg.catalog_build` 重跑；英文长 token 精确匹配，过滤 stopword |

**意图识别口径**：`count_series_hits ≥ 1` 且含查询类词、无解读类词（说明/意味着/怎么看/影响/为什么/分析/建议）→ `metric_series`；含「与/和/以及/、/同时」等多维并列连接词时交回 `data_query`，不做单维截断。命中后 `route_signal.reasons` 含 `deterministic_keyword_registry`，不参与 recall 密度门控。

**索引输出统一模板**（`format_series_output`，所有单维执行器套用）：

```jsonc
{"kind":"series","id":"sub_category::metric_name","title":"…","unit":"…",
 "days":90,"quality":"good","source":"dal_mm_metrics","points_n":90,
 "value":34.7e8,"as_of":"2026-11-14 06:30","window":{"days":90,"points":90},
 "range":{"min":…,"max":…},"change":{"abs":…,"pct":…},
 "text":"RWA 总规模：最新 34.70亿美元（2026-11-14 06:30 CST）；近 90 天 …"}
```

规则：`scale` 统一缩放（亿/万亿美元）、`sign` 统一展示符号（巨鲸净流入 `sign=-1`）、空数据返回 `value=null` 且 `text` 含「暂无历史数据」，`data.index` 与 `answer` 同源，禁止各执行器自拼文案。

### 5.5 前端契约

`ModuleSnapshot` 保留现有字段，`timeseries` 改为真实序列：

```jsonc
"timeseries": [{"timestamp": "2026-11-14T00:00:00Z", "value": 27,
                "direction_score": -0.46, "velocity": -2, "velocity_label": "快速下降"}]
```

- 生产者：54 `SeriesAggregator`（`days` 由模块声明，默认 90）
- 每个点必须带 `unit`；序列同级带 `data_quality: good|partial|empty` 与 `reason`
- 数据不足返回 `[]` + `reason=no_history|insufficient_samples`，**禁止合成/随机数据**
- 过渡开关：`FUNDAMENTAL_TIMESERIES_SOURCE=54|legacy`（默认 54，可一键回退）

---

## §六、数据质量与统计口径

| 口径 | 规定 |
|---|---|
| 时间 | 存储 unix 秒（UTC），响应 ISO8601 双写；禁止本地时区换算 |
| 频率 | 统一降采样到日频再做统计；小时频指标先取日内均值 |
| 最小样本 | 统计类 `sample_n ≥ 30`；分位窗口默认 3 年，不足则回退全量并标注 |
| 坏值 | 已知哨兵（`tvl_bln=0.0`）与 `NULL` 剔除并计入 `missing_rate`；离群点**只标记不删除**（`outlier_flags`），仅 z-score 计算时 winsorize(p1/p99) |
| 复合指标 | `cagr` 仅适用于恒为正的指数型/存量型序列（CPI 指数、M2、TVL）；费率/多空比/涨跌幅等禁用并返回 `null` |
| 波动率 | 统一定义为日收益率标准差 × √365（年化），禁止与原始值标准差混用 |
| 索引 | P0 迁移：`CREATE INDEX IF NOT EXISTS idx_mm_metrics_lookup ON mm_metrics(sub_category, metric_name, timestamp)` |
| 陈旧度 | `now - max(ts) > 2 × 指标固有周期` → `is_stale=true`（如 CPI 月频超过 45 天） |
| 分位算法 | 线性插值经验分位（`numpy.percentile` 等价实现，不引入新依赖时用纯 Python） |
| 一致性 | 同一指标在 L1 与前端必须来自同一 Aggregator 输出 |

**覆盖体检产物**（P0 交付）：`54-L1架构能力聚合层/reports/metrics_health.json`

```jsonc
{"CPIAUCSL/value": {"rows": 960, "span": ["1947-01-01","2026-11-01"],
                    "freq": "M", "missing_rate": 0.0, "bad_values": 0, "is_stale": false},
 "chains_summary/total_tvl_bln": {"rows": 812, "bad_values": 61, "status": "partial"}}
```

---

## §七、落地计划

### P0（1 个迭代，先打通主链路）

0. **索引迁移**：`CREATE INDEX IF NOT EXISTS idx_mm_metrics_lookup ON mm_metrics(sub_category, metric_name, timestamp)`（B3）
1. 覆盖体检脚本 + `metrics_health.json`（只读，产出指标健康度清单）
2. L0 `datacenter.series` scope（包装 `query_metric_by_time`，含 `max_days` 与白名单校验）+ 单测
3. `exec_metric_series` + L1 意图 `metric_series`（TS/Python 双端）+ golden 20 条 + 负样本 10 条
4. L1 直答端到端：`近一年CPI走势` / `BTC恐惧贪婪近30天变化` 返回真实序列摘要

**验收**：① 两条样例话术返回含 `sample_n` 的真实数据；② `quality.status` 非空；③ P95 ≤ 800ms（≥20 次实测，冷/热各半，记录 p50/p95/max）；④ golden 通过率 ≥ 90% 且既有 311 条无回归；⑤ 索引前后 `EXPLAIN QUERY PLAN` 对比留档。

### P1（统计与含义）

5. `datacenter.percentile` + `StatsEngine`（percentile/zscore/volatility/cagr）
6. `MeaningEngine` + `metric_glossary.yaml`（先覆盖 30 个高频指标，三段式）
7. `exec_metric_percentile` / `exec_metric_meaning` + golden 各 20 条
8. 前端 11 模块 `timeseries` 切真实序列：改造 `src/app/api/fundamental/[...path]/route.ts:69` 的硬编码 `[]`，由 54 `SeriesAggregator` 供给；**不删除** 9-基本面 `generate_timeseries`（仍被 `ml_trade_service_v2` 等消费），用 `FUNDAMENTAL_TIMESERIES_SOURCE` 开关切换

**验收**：每个模块至少 1 个指标可问分位与含义；前端图表数据与 DAL 抽样一致。

### P2（跨维与条件外推）

9. `CrossCheckEngine`（主指标 × 资金/技术/情绪/宏观，复用 `evolution.contradiction` 与 23 力度分位）
10. `PredictAggregator`（fedwatch 概率、bdsm 阶段、event 前瞻；统一 `caveat` 字段）
11. `exec_cross_check` / `exec_conditional_outlook`（gated）+ golden 各 20 条

**验收**：跨维结论可复现（同输入同输出）；模型输出类回答必带来源、样本量与不确定性区间；**禁止点预测**（「将会涨到」「预计点位」等措辞一律不允许）。

---

## §八、风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 各指标时间跨度差异极大（1962 ~ 2018 起） | 分位失真 | 分位默认 3 年窗口 + 强制返回 `lookback/sample_n` |
| 频率混杂（日频/小时频/月频） | 统计口径错 | 先降采样到日频；月频指标分位按「同频历史点」计算 |
| `mm_metrics` 存在坏值与重复点 | 统计偏差 | 体检脚本 + 坏值剔除 + `missing_rate` 披露 |
| 新增意图与既有 `data_query` 冲突 | 误吞／抢路由 | 新意图 fallbackPattern 置于 data_query 之前；data_query 维持双条件共现；golden 回归门禁 |
| 前端合成序列被移除后出现空图 | 体验回退 | 数据不足显示「暂无历史数据」+ `data_quality=partial`，不补假数据 |
| 绕过记忆门禁导致误直答 | 答非所问 | 仅 `deterministic` 能力绕过，且要求「指标词 + 参数」双命中 |

## §九、兼容与回滚

- 54 为**新增层**，不修改任何既有执行器行为；L1 路由新增意图与既有意图共存。
- 回滚点：① 移除 `capability_manifest.yaml` 注册项 → 路由自动回落 L2；② 前端 `timeseries` 可回退为 `[]`。
- L0 scope 新增不影响既有 10 个 scope；`/api/fundamental/**` 响应结构向后兼容（只新增/填充字段）。

## §十、待决策

| # | 问题 | 建议默认 |
|---|---|---|
| Q1 | 分位默认窗口取 3 年还是全历史 | 3 年（并返回 `lookback`） |
| Q2 | 含义解释是否需要 LLM 润色 | 先纯模板；LLM 仅在 L2 后置，L1 不用 |
| Q3 | 指标释义库首批覆盖范围 | 前端 11 模块每个模块 top3 指标（约 30 个） |
| Q4 | 预测类是否纳入 L1（gated）还是全部留在 L2 | 仅暴露「已有概率/阶段资产」；自建外推留 L2 |
| Q5 | `metric_ref` 命名规范（`sub_category/metric_name` 还是自然语言别名） | 双支持：别名表 `meaning/metric_aliases.yaml`（54 维护）+ 原始键 |
| Q6 | 二维状态样本不足（4×4 需 4,000 日/资产）时是否仍出二维结论 | **已决策（v1.46，2026-11-15）**：Tier B/D 兜底 —— 4×4=A（≥4,000 日）/ 3×3=B（≥2,250 日）/ 2×2=D（≥1,000 日），每格非重叠 ≥250；三档均不达标**不出二维结论**，回退一维并披露 `degraded_reason=insufficient_2d`；`tier/buckets_per_axis/cells/min_cell_nonoverlap_n` 强制随结果返回，禁止静默降级；4×4 契约保留，样本到点自动升档 |

---

## §十一、L1 确定性数据能力全景补充（v0.2 新增）

> 排查范围：19 DAL 全部表 + 18/9/10/11/23/37 的计算与落盘资产。**只收录确定性能力**（同输入同输出），排除 LLM 生成、合成数据、自建外推。
> **正式登记册见 [docs/TECHNICAL_DESIGN.md §2](docs/TECHNICAL_DESIGN.md)**：A 组 16 项 + B 组 10 项 + C 组 6 项 = 32 项，含 `D-Axx / D-Bxx / D-Cxx` 能力 ID、依赖、输出字段、意图、优先级与状态。本节为分组概览，逐项明细以技术文档为准（A 组 16 项 / B 组 10 项 / C 组 6 项）。

### 11.1 事实基线（已核验）

| 事实 | 结论 | 证据 |
|---|---|---|
| DAL 无 OHLCV 表 | 仅有 `tr_daily_stats`；`tr_trades=0`、`po_positions=0`、`rs_cases=0`、`rs_state=1`、`mm_events=16` | `sqlite3` 实测 `19-数据访问层/data/dreambuddy_core.db` |
| 真实 K 线可现取 | OKX `/api/v5/market/candles` 与 `history-candles` 已在多处使用 | `6-TRADING/scripts/dream_strategy_pipeline.py:155`、`11-易经推理系统/.../bdsm_snapshot_writer.py:356-368`、`6-TRADING/scripts/backtest_data_fetcher.py:65` |
| 合成 K 线不可用 | `10-经典指标系统/generate_history.py:75-136` 随机生成 5m 蜡烛 | 同上 |
| 指标实现可复用 | RSI/MACD/ATR/布林/EMA 等在 20 个文件中已实现 | `10-经典指标系统/ml_trade_service.py`、`11-易经.../rsi_sentiment_features.py`、`37-一键启动脚本/g4-volatility-gate.py` |
| 模型输出已落盘 | bdsm/bcrm2/event/riskcontrol/evolution 均有快照 JSON | `34/core/l0_foundation.py:280-326` 的 fetcher |

### 11.2 可新增能力清单（按数据依赖分组）

**A 组：库内时序衍生（依赖已具备，零新增采集，P1）**

| 能力 | 依赖 | 复杂度 | 现成实现 |
|---|---|---|---|
| 历史序列 + 变化率 + CAGR | `mm_metrics` / `query_metric_by_time` | 低 | ⬜（本 SPEC P0） |
| 历史分位 / z-score | 同上 | 低 | 部分（9 估值百分位逻辑可参考） |
| 滚动波动率（年化） | 同上 | 低 | ✅ 多处 |
| 距历史高点回撤 | 同上 | 低 | ⬜ |
| 环比/同比（宏观月频） | CPI/PPI/M2 系列 | 低 | 部分（`exec_data_query` 已有 CPI 同比） |
| 实际利率（10Y − CPI） | `DGS10` + `CPIAUCSL` | 低 | ⬜ |
| 双序列滚动相关性（30/90d） | 任意两条 `mm_metrics` | 中 | ✅ 23 层/11 系统有相关计算 |
| 领先滞后相关（lag 0–10） | 同上 | 中 | ⬜ |
| 极端事件频率（超阈值天数） | 恐惧贪婪/资金费率/清算 | 低 | ⬜ |
| 拥挤度（分位 + 变化率合成） | 资金费率 + 多空比 + 未平仓 | 中 | ✅ F26 + `capabilities.stats.crowding`：`level` 按 A 分位法（分值历史分布 p20/p60/p80）四档，披露 `as_of/window/sample_n`，样本不足或分布退化降级不补阈值 |
| ETF 净流入滚动和（7/30d） | `mm_*` ETF 系列 | 低 | ⬜ |
| 稳定币增速（7/30d） | USDT/USDC 系列 | 低 | ⬜ |

**B 组：技术指标（需新增 `market.candles` scope，确定性但依赖外部行情，P1/P2）**

| 能力 | 依赖 | 复杂度 | 现成实现 |
|---|---|---|---|
| K 线获取（1H/4H/1D，limit≤300） | OKX candles + 5s 缓存 | 低 | ✅ 多处 |
| MA/EMA、RSI、MACD、ATR、布林位置 | candles | 低 | ✅ |
| 量能比（当前量 / N 日均量） | candles | 低 | ✅ |
| 支撑/压力位（近 N 日高低 + 触碰次数） | candles | 中 | 部分 |
| 趋势斜率 / 距 ATH 回撤 | candles | 低 | 部分 |
| 年化波动率 / 波动率分位 | candles + 历史 | 中 | ✅ g4 波动率门 |

**C 组：已具备模型输出（结构化暴露，零计算，P0/P1）**

| 能力 | 来源 | 现成 |
|---|---|---|
| 估值阶段 / 百分位 | `yijing.bdsm` | ✅ |
| 技术方向 / 置信度 / 卦象 | `yijing.bcrm2` | ✅ |
| 事件六维评分 / 前瞻 | `event.state` | ✅ |
| 持仓风控状态 / 触发次数 | `riskcontrol.trailing` | ✅ |
| 四维一致性（资金/技术/情绪/宏观） | `evolution.contradiction` | ✅ |
| 周期状态 / 战略影子 | `evolution.snapshot` + 战略层 | ✅ |

### 11.3 排除项（非确定性，禁止进 L1）

| 排除 | 原因 |
|---|---|
| `10-经典指标系统/generate_history.py` 合成 K 线 | 随机游走，非真实数据 |
| 自建趋势外推 / 情景概率生成 | 非确定性，留 L2 |
| LLM 叙事/新闻解读 | 非确定性 |
| 任何写操作（回填、重算、覆盖快照） | 违反 ADR-3 只读 |

### 11.4 新增能力 → 意图 / scope 映射

| 能力组 | 新增 L0 scope | 新增 L1 意图 | mode |
|---|---|---|---|
| A 组 | `datacenter.series`、`datacenter.percentile`、`datacenter.correlation` | `metric_series`、`metric_percentile`、`correlation_query` | deterministic |
| B 组 | `market.candles`（OKX + 5s 缓存 + `is_stale`） | `technical_indicator` | deterministic（带缓存与降级） |
| C 组 | 复用既有 6 个 scope | `conditional_outlook` | gated（只输出模型输出 + 历史同状态分布，不点预测） |
| **E 组（统计关系）** | 复用 A 组 3 scope + `market.candles` | `seasonality_query`、`conditional_return`、`event_study`、`state_transition`、`drawdown_query` | deterministic |
| 跨维 | `evolution.contradiction` + A/B/E 组 | `cross_check` | gated |
| **G 组（机构方法）** | 复用 A 组 3 scope + `market.candles`（需统一资产池） | 不新增意图，挂在 `metric_series` / `correlation_query` / `conditional_return` 下 | deterministic（D1/D2）；D3 需固定惯例参数与容差 |

**优先级（已确认）**：
- **P0** 维持不变（A 组主链路：`metric_series` + `datacenter.series`）。
- **P1** 增 `market.candles` + `technical_indicator`（先做 MA/RSI/ATR/量能比 4 个）；同批增 E 组的 `seasonality_query`（月份效应/胜率/次数）、`metric_percentile`（分位→前瞻收益）、`drawdown_query`。
- **P2** 增 `correlation_query`（相关矩阵 TopK + 领先滞后）与 `cross_check` 自动组合（同向率/相关突变），以及 `conditional_return`、`event_study`、`state_transition`。

**P1 硬前置（v1.3 更新）**：E 组与 B 组的价格前提**已闭环**——四资产 `close_usd` 各 1,094 点（2023-11-15~2026-11-12，缺口 0），`market.candles` 1D/1W/1M 已落地。但**纵深不足以支撑月度季节性**：月份效应需 ≥5 年（60 个月），现仅 36 个月；四年周期需 ≥2 个周期（≈2,920 日），现 1,094 日。纵深事实统一见 [docs/METHOD_LIBRARY.md §15](docs/METHOD_LIBRARY.md)，本 SPEC 不复制点数。

**方法选择**：全部由 [docs/METHOD_LIBRARY.md](docs/METHOD_LIBRARY.md) 的意图→方法路由表驱动（243 核心方法 / 18 关系原语），L1 只做「选法 + 套模板」，不做推理。

**E 组落地状态（v1.44，2026-11-15）**：

1. **能力层已实现**：`l1agg/capabilities/{manifest,envelope,stats}.py` + `capability_manifest.yaml` + `contracts/capability_result.schema.json`。已接线 D-A14（拥挤度合成 + A 分位法四档）、D-E01（条件收益）、D-E02（分位→前瞻收益，A8/T0.5）、D-E03（季节性）、D-E04（事件研究窗）、D-E05/D-E06/D-E11/D-E12（相关/领先滞后/同向率/时空对齐，含矩阵 TopK、C18 与 R18）、D-E07（状态转移 + B06 相邻状态联合计数）、D-E08（条件 IC，需因子源）、D-E09（计数与共现）、D-E10（回撤）、D-E14（一维相关状态条件分布）、D-E15（趋势）；G 组 D-G16（P09/P10 组合 VaR/CVaR + D17/D18 逐资产历史 VaR/CVaR，`metric_series`）于 v1.19 接线，D-G19（B13/B14/Q01/Q02/Q03 因子 IC/RankIC/ICIR/衰减 + 可选 B15 价格动量衰减，`metric_series`）于 v1.20 接线，D-G20（B16 分位组统计 + B11 严格单调性 + Q04 分位序号 Spearman 检验，`metric_series`）于 v1.21 接线，D-G22（Q06 HAC t + Q07 Deflated Sharpe，`significance_query`）于 v1.11 接线，D-G23（Q10 均值调整 CAR + Q11 Patell/BMP，`event_study`）于 v1.15 接线；J 组 D-J02（C13/T10/SC91 季节强度与调整，`seasonality_query`）于 v1.18 接线，D-J04（T22/T23/SC49/SC50/SC51 变点检测，`change_point_query`）于 v1.17 接线，D-J22（M19/M20/SC31/SC32/SC33 面板降维，`metric_series`）于 v1.22 接线，D-J24（M05/M21/SC71/SC72 相关网络与社区发现，`metric_series`）于 v1.23 接线，D-J30（SC90 PIT 时间校验 + R02 `pit=true` 前瞻分布，`metric_percentile`）于 v1.25 接线，D-G14（P07 EWMA 组合协方差 + T19 逐资产 EWMA 波动，`metric_series`）于 v1.24 接线，A 组 D-A01（单序列区间取点 + 日/周/月降采样，`metric_series`，当前历史分位复用 S25）于 v1.26 接线，D-A02（S15 绝对变化 + S16 变化率，`metric_series`）于 v1.27 接线，D-A03（S19 CAGR，`metric_series`）于 v1.28 接线，D-A04（S25 历史分位，`metric_percentile`）于 v1.29 接线，D-A06（F05 年化波动率，`metric_series`）于 v1.30 接线，D-A07（回撤，复用 D-E10 的 `drawdown` 执行器，`drawdown_query`）于 v1.31 接线，D-A08（S16 同比，`metric_series`）于 v1.32 接线，D-A09（S16 环比，`metric_series`）于 v1.33 接线，D-A10（S16 派生实际利率，`metric_derived`）于 v1.34 接线，D-A11（M04 双序列滚动相关，`correlation_query`）于 v1.35 接线，D-A12（M11/M12 领先滞后相关，`correlation_query`）于 v1.36 接线，D-A13（S11 分位阈值 + 极端事件频率计数，`metric_series`）于 v1.37 接线，D-A15（S20 滚动均值 × 窗口长度还原滚动和，`metric_series`）于 v1.38 接线，D-A16（S16 多窗口稳定币规模增速，`metric_series`）于 v1.39 接线，D-B08（T08 对数价格 OLS 斜率/R² + T09 名义 t/p，`technical_indicator`）于 v1.40 接线，D-B09（复用 D-E10 的 D20/D21，输出 `drawdown_from_ath/ath/ath_ts` 别名，`technical_indicator`）于 v1.41 接线，D-G08（skip/lookback 切片后由 F14 执行 12-1 动量/波动/风险调整动量，`metric_derived`）于 v1.42 接线，D-G09（价格转收益后由 P02 输出目标/实现波动比与缩放系数，`metric_derived`）于 v1.43 接线，D-G25（P13 尾部相关，`correlation_query`）于 v1.47 接线，D-J05（T25/T26/C14 周期频谱，`cycle_query`）于 v1.47 接线。方法层注册表 **392 方法全实现**（核心 243 + 调研 149，audit 243/243 PASS；核心含 I35–I39 美联储方法；C 组 18 方法在 `l1agg/methods/seasonal.py`，v1.47 起无占位）。
2. **意图合并（与 §11.4 表的有意偏差）**：前端先合为单一确定性意图 **`stat_query`**，内部按关键词分派到上述能力 ID，另加 `cross_check` 相关子能力。理由：5 个独立意图 × 双端注册表 × 金标集维护成本高，而能力 ID 已能精确定位；后续若要拆分为 §11.4 的 5 个独立意图，只需拆分执行器入口，能力层与 manifest 无需改动。
3. **双端同步点**：`3.1-FRONTEND/scripts/l1_route_signal.py`（EXECUTORS + DETERMINISTIC_INTENTS + fallback pattern）、`data_query_executor.py::exec_stat_query`、`3.1-FRONTEND/src/lib/l1-intent-registry.ts`、`34-前端应用训练系统/l1_intent_golden.jsonl`。
4. **D-E14 边界（v1.14 更新）**：一维首版已接线，输入为已压缩的一维相关状态与同步价格轴；R02 PIT 桶标签由 B05/B10/R01/R08 共享，默认 h=1/2、4 桶，主期限不足降 2 桶，弱后续期限单独降级，h>1 不输出朴素 t/p。二维 4×4 仍受 ≥4000 天/资产与 F1–F12 状态特征约束。D-E01 实际统计仍受因子与价格 ≥250 个有效配对样本门禁约束；D-A14/D-G22 前端 cue 分派已补齐。
5. **D-G23 边界（v1.15 新增）**：独立复用 D-E04 的事件日期对齐，但只调用 Q10/Q11，不重复执行 F19/F21/F23；价格轴事件下标减 1 转为同日收盘收益下标。有效事件 <30 降级 `events_lt_30`，Q11 无可用估计窗波动时降级 `patell_bmp_unavailable`，两种情况均保留 Q10 CAR。
6. **D-E07/B06 边界（v1.16 新增）**：D-E07 在既有 B02 状态轴上增加 B06，对 `state_t × state_{t+1}` 输出 `rows/cols/table/n` 联合计数底表；B07 对同一相邻状态关系做行归一化，B08/B09 继续输出稳态与停留期。复用既有 capability ID，不新增可执行出口，也不改变方法层统计口径。
7. **D-J04 边界（v1.17 新增）**：新增 `change_point_query`（deterministic，`min_n=60`，executor `capabilities.stats.change_point`），真实执行 T22/SC49 两种 CUSUM、T23 近似 PELT、SC50 精确 PELT 与 SC51 Pettitt；SC47 Kalman 与 SC48 互谱相干不属于本能力。输入有效数值与日期按原始行号同步过滤，输出并列保留五方法原始结果及 0 基断点下标的 ISO 日期映射，不合成交易方向、不在能力层重算统计量；有效样本 <60 FAIL-OPEN 为 empty。
8. **D-J02 边界（v1.18 新增）**：复用 `seasonality_query`（deterministic，executor `capabilities.stats.seasonal_adjustment`），真实执行 C13 月度 ANOVA 式季节强度、T10 robust STL（默认 period=7）与 SC91 X-13 风格 STL 近似（默认 period=12）；能力级 `min_n=60`、`min_span_days=1095`。C13 必须提供完整日期轴，有效数值与日期按原始行号同步过滤；有效样本 <60 或缺完整日期轴 FAIL-OPEN 为 empty。历史跨度 <1095 天保留全部分解结果，但 `quality.status=partial`、`degraded_reason=seasonality_depth_lt_3y`，只作描述。并列输出三方法原始 trend/seasonal/resid 组件与季节强度，不改方法层、不新增统计口径、不合成交易方向。
9. **D-G16 边界（v1.19 新增）**：复用 `metric_series`（deterministic，`min_n=60`，executor `capabilities.stats.portfolio_risk`），输入各资产收益序列与可选权重；P09/P10 共用同一面板与权重，分别输出参数法组合 VaR、历史法组合 VaR/CVaR，D17/D18 对同一最小公共长度窗口逐资产输出历史 VaR/CVaR。P10 的有效分位同步给 D17/D18，权重归一化与全部统计计算只由方法层执行；组合与逐资产结果并列，损失为正数口径，有效对齐样本 <60 或空面板 FAIL-OPEN 为 empty。
10. **D-G19 边界（v1.20 新增）**：复用 `metric_series`（deterministic，`min_n=250`，executor `capabilities.stats.ic_profile`）。factor 与已对齐单期 forward 按原始位置 complete-case，B13/B14 与 Q01/Q02 并列输出 IC/RankIC/分段 ICIR，Q03 输出多期限因子 IC 衰减；Q03 的 returns 首项补 0、其余为右移一期 forward，避免 h=1 多预测一期，能力层不重算相关或 ICIR。可选 prices 真实执行 B15 价格动量重叠/非重叠 IC 衰减；缺失或样本不足时 `partial + price_history_unavailable`，保留核心五方法结果且不将 B15 列为本次已执行方法。配对样本 <250 或空输入 FAIL-OPEN 为 empty。
11. **D-G20 边界（v1.21 新增）**：复用 `metric_series`（deterministic，`min_n=250`，executor `capabilities.stats.quantile_monotonic`）。factor 与已对齐 forward 按原始位置 complete-case，B16/B11/Q04 共享同一配对样本轴；B16 输出各分位组均值/中位/胜率/样本量及最高减最低 spread，B11 输出组均值严格单调方向与 rho_bin，Q04 输出分位序号与组均值的 Spearman rho/p/bucket_returns。能力层不重算统计量；spread 仅为描述性统计，非策略收益，不生成交易方向。配对样本 <250、空输入或非法 k 均 FAIL-OPEN 为 empty。
12. **D-J22 边界（v1.22 新增）**：复用 `metric_series`（deterministic，`min_n=60`，executor `capabilities.stats.dimension_reduction`）。多变量面板按原始行 complete-case，M19/M20/SC31/SC32/SC33 共享同一数据矩阵：M19 输出相关阵 PCA 解释方差、M20 输出载荷、SC31 输出 sklearn PCA、SC32 输出 SVD、SC33 输出因子载荷与唯一性。能力层不重算统计量；降维结果仅描述数据结构，不构成交易信号，不生成交易方向；M21 归入 D-J24 网络聚类，M22 等聚类方法属 D-J23，均不在本出口。对齐样本 <60、空面板、单变量或非法 k 均 FAIL-OPEN 为 empty。
13. **D-J24 边界（v1.23 新增）**：复用 `metric_series`（deterministic，`min_n=60`，executor `capabilities.stats.correlation_network`）。多变量面板按原始行 complete-case 后由 M05 输出相关矩阵，按 `|ρ|≥threshold`（threshold∈[0,1]）生成无向邻接；SC71 输出度/介数/接近中心性，SC72 输出 Louvain 社区与模块度，M21 输出相关距离层次聚类标签。能力层不重算统计量；网络结构仅描述同期相关关系，不构成交易信号，不生成交易方向。图节点数低于方法门禁时以 `quality.status=partial` 降级披露；对齐样本 <60、空面板、单变量、非法 threshold 或非法 k 均 FAIL-OPEN 为 empty。
14. **D-G14 边界（v1.24 新增）**：复用 `metric_series`（deterministic，`min_n=60`，executor `capabilities.stats.ewma_risk`）。多资产收益面板按原始行 complete-case 后共享同一矩阵：P07 输出 EWMA 组合协方差（`lam` 默认 0.94、`init_window` 20、`periods` 365）与年化波动，T19 对每个资产输出逐日 EWMA 波动序列。单资产仅执行 T19 且不输出 `covariance` 键；能力层不重算统计量，风险结构仅描述样本内统计，不生成交易方向。`lam` 不落在 (0,1)、`periods<=0`、`init_window<2`、空面板或对齐样本 <60 均 FAIL-OPEN 为 empty。
15. **D-J30 边界（v1.25 新增）**：复用 `metric_percentile`（deterministic，`min_n=250`，executor `capabilities.stats.pit_alignment`）。`indicator/prices/dates` 必填且等长；`release_ts`（数据发布时刻）与 `used_ts`（使用时刻）可选，缺省视为观测时刻；SC90 校验每条样本「可用时间 ≤ 使用时间」并输出 `pass/n/n_violations/max_lag`，R02 `pit=true` 逐时点滚动分位并按 `release_ts ≤ as_of` 过滤输出当前分位与分桶前瞻分布。PIT 违规时 `quality.status=partial`、`degraded_reason=pit_violations` 并披露前视风险，R02 仍按 release_ts 过滤；过滤后可见样本不足 PIT 窗口时不产出前瞻分布并显式说明。能力层不重算统计量，PIT 校验与前瞻分布并列输出，不生成交易方向；对齐样本 <250、指标/价格/release_ts/used_ts 长度不一致或日期无效、非法 buckets/window 均 FAIL-OPEN 为 empty。
16. **D-A01 边界（v1.26 新增）**：复用 `metric_series`（deterministic，`min_n=30`，executor `capabilities.stats.history_series`）。`values/dates` 必填且等长、日期轴须可解析；`freq ∈ {daily,weekly,monthly}`（兼容 day/week/month 与首字母），按区间取最后观测、同日重复取最后，输出 `points[]/span/unit`；当前历史分位由 S25 真实执行。能力层只做区间取点与降采样，不重算统计量；唯一日期缺失率 >20% 时 `quality.status=partial`、`degraded_reason=sparse_series` 并披露缺失率。样本 <30、`values/dates` 长度不一致或日期无效、非法 `freq` 均 FAIL-OPEN 为 empty。
17. **D-A02 边界（v1.27 新增）**：复用 `metric_series`（deterministic，`min_n=2`，executor `capabilities.stats.change_rate`）。`values` 必填，`window` 默认 1；S15 输出绝对变化、S16 输出变化率，两者并列。`window<1` 或有效样本不足以覆盖 `window` 区间直接 FAIL-OPEN 为 empty；`dates` 可选，给定时须与数值等长且可解析。基期值为 0 时 `change_pct=None`，`quality.status=partial`、`degraded_reason=change_pct_unavailable`，绝对变化照常输出。能力层不重算统计量、不生成交易方向。
18. **D-A03 边界（v1.28 新增）**：复用 `metric_series`（deterministic，`min_n=2`，executor `capabilities.stats.cagr`）。`values` 必填；提供 `dates` 时按首末日期实际天数折算 `days`（须 ≥1），缺省或不可用时回退方法层默认 `n−1`。S19 真实执行并输出 `cagr/years`，能力层补充 `span/days` 元信息，不重算统计量、不生成交易方向。折算跨度不足 1 年时 `quality.status=partial`、`degraded_reason=short_span` 并提示「样本跨度不足 1 年」；非正首末价格、天数 ≤0、有效样本 <2 均 FAIL-OPEN 为 empty。
19. **D-A04 边界（v1.29 新增）**：复用 `metric_percentile`（deterministic，`min_n=30`，executor `capabilities.stats.percentile_rank`）。`values` 必填；`lookback` 缺省取全样本，指定时须为整数且 ≥30；窗口取最近 `lookback` 期，`dates` 可选但给定时须与数值等长且可解析。S25 真实执行输出 `percentile/value/n`，能力层补充 `lookback/sample_n`，不重算统计量、不生成交易方向。窗口 <60 期时 `quality.status=partial`、`degraded_reason=short_lookback`；`lookback` 超过可用历史时降级 `lookback_truncated` 并按可用样本计算。有效样本 <30、`lookback<30`、日期长度不一致或含非有限值均 FAIL-OPEN 为 empty。
20. **D-A06 边界（v1.30 新增）**：复用 `metric_series`（deterministic，`min_n=30`，executor `capabilities.stats.annualized_volatility`）。`values` 必填；`window` 缺省取全样本，指定时须为整数且 ≥30；窗口取最近 `window` 个价格点，`dates` 可选但给定时须等长且可解析。F05 真实执行（日简单收益标准差 × √365）输出 `vol/mean_ret/n`，能力层补充 `window/sample_n`，不重算统计量、不生成交易方向。有效样本 <60 期时 `quality.status=partial`、`degraded_reason=short_window` 并提示样本较短。样本 <30、`window<30`、日期长度不一致或含非有限值均 FAIL-OPEN 为 empty。
21. **D-A07 边界（v1.31 新增）**：复用 `drawdown_query`（deterministic，`min_n=250`，executor `capabilities.stats.drawdown`），与 D-E10 共用同一执行器；调度层经 `_EXECUTOR_INTENTS` 注入 `capability_id=D-A07` 与 `intent`，信封与 `data.capabilities` 键随之为 D-A07。D20 最大回撤（峰/谷索引）与 D21 回撤持续/收复天数真实执行，输出 TD 约定的 `drawdown/peak_ts`，同时保留 `mdd/current_drawdown/duration_days/drawdown_path` 等既有字段；`dates` 可选，缺失时 `peak_ts=None`。`prices<2` FAIL-OPEN 为 empty；样本 <250 期降级 `insufficient_samples` 并在 answer 明示「样本不足 250 点」。
22. **D-A08 边界（v1.32 新增）**：复用 `metric_series`（deterministic，`min_n=13`，executor `capabilities.stats.yoy_change`）。`values` 必填；`period` 默认 12（同比），须为整数且 ≥1；`dates` 可选但给定时须等长且可解析，`base_ts` 取基期日期、`span` 取基期→最新。S16 真实执行 `x_t/x_{t-period}-1`，输出 `yoy/base_ts/period/sample_n`，不重算统计量、不生成交易方向。历史长度 <2×period+1（不足 2 个完整周期）时 `quality.status=partial`、`degraded_reason=short_history`；基期值为 0 时 `yoy=None` 并降级 `yoy_unavailable`，answer 明示原因。样本 ≤period、`period<1`、日期长度不一致或含非有限值均 FAIL-OPEN 为 empty。
23. **D-A09 边界（v1.33 新增）**：复用 `metric_series`（deterministic，`min_n=2`，executor `capabilities.stats.mom_change`）。`values` 必填；`dates` 可选但给定时须等长且可解析，`base_ts` 取上一期日期、`span` 取上一期→最新。S16 以固定 `k=1` 真实执行 `x_t/x_{t-1}-1`，输出 `mom/base_ts/sample_n`，不重算统计量、不生成交易方向。基期值为 0 时 `mom=None` 并降级 `mom_unavailable`，answer 明示原因；有效样本 <2、日期长度不一致或含非有限值均 FAIL-OPEN 为 empty。
24. **D-A10 边界（v1.34 新增）**：新增 `metric_derived`（deterministic，`min_n=13`，executor `capabilities.stats.real_rate`）。`nominal`（名义利率，如 DGS10）与 `cpi`（CPI 指数，如 CPIAUCSL）必填且等长；通胀唯一由 S16 以 `k=period`（默认 12）真实执行并折算为百分点，能力层只做 `名义 − 通胀` 差值组合，输出 `real_rate/nominal/inflation/base_ts/period/sample_n`。CPI 基期为 0 时通胀与实际利率均不可计算并降级 `inflation_unavailable`；历史 <2 个完整周期降级 `short_history`；样本不足以覆盖 period、`period<1`、双序列长度不一致、日期长度不一致或含非有限值均 FAIL-OPEN 为 empty。
25. **D-A11 边界（v1.35 新增）**：复用 `correlation_query`（deterministic，`min_n=60`，executor `capabilities.stats.rolling_correlation`）。`x`/`y` 必填，`dates` 可选但给定时须与原序列等长可解析；按原始位置 paired complete-case 后由 M04 计算滚动 Pearson 相关（`window` 默认 30），输出 `corr`（最近窗口）/`mean_r`/`window`/`n_windows`/`sample_n`，`align_method=paired_complete_case`。有效配对 <60 降级 `insufficient_samples` 但保留结果（走 `_call_soft`，统计仍由 M04 执行）；有效配对 <2、`window<2` 或 window 超过配对样本、日期长度不一致或含非有限值均 FAIL-OPEN 为 empty。结论只描述同期联动强弱，不说明领先关系或未来延续。
26. **D-A12 边界（v1.36 新增）**：复用 `correlation_query`（deterministic，`min_n=120`，executor `capabilities.stats.lead_lag_correlation`）。`x`/`y` 必填，`dates` 可选但给定时须与原序列等长可解析；paired complete-case 后由 M11 输出 lag −max_lag…+max_lag（默认 10）的相关/p/BH-FDR q/显著性，M12 输出最优 lag，能力层组装 `corr_by_lag[]` 与 `best_lag/best_corr/best_p_adj`。有效配对 <120 降级 `insufficient_history` 但保留结果（`_call_soft`）；配对 <2、`max_lag<1` 或超过配对样本、日期长度不一致或含非有限值均 FAIL-OPEN 为 empty。结论只描述历史样本中的联动强弱，不自动等于因果或未来可预测。
27. **D-A13 边界（v1.37 新增）**：复用 `metric_series`（deterministic，`min_n=30`，executor `capabilities.stats.extreme_frequency`）。`values` 必填，`side ∈ {above,below,abs}`（默认 above）；阈值二选一：调用方给定 `threshold` 时直接使用，缺省时由 S11 分位线性插值以 `quantile`（默认 0.95，须落在 (0,1)）取阈值，`methods` 如实记录是否执行 S11。能力层只做 `v>=cut` / `v<=cut` / `|v|>=|cut|` 的纯计数与 `days/n` 比率，不引入任何新估计量、不生成交易方向。有效样本 <30 且无阈值时无法确定阈值，FAIL-OPEN 为 empty（answer 明示「阈值不可确定」）；<30 且有阈值降级 `insufficient_samples`；`side` 非法、`threshold` 为 NaN、`quantile` 越界、含非有限值均 FAIL-OPEN 为 empty。
28. **D-A15 边界（v1.38 新增）**：复用 `metric_series`（deterministic，`min_n=30`，executor `capabilities.stats.etf_flow_rolling`）。`values` 为净流入金额序列，`windows` 可配（默认 `(7, 30)`，须为正整数、去重保序），输出 `sum_{k}d`；S20 真实执行滚动均值，能力层只做「均值 × 窗口长度」算术还原，不重算分布、不生成方向。有效样本 <30 降级 `insufficient_samples` 但保留结果；某窗口超出历史长度降级 `short_history` 并将该窗口置 None；全部窗口不可算、`windows` 为空或非法、`dates` 与原序列不等长、含非有限值均 FAIL-OPEN 为 empty。`unit` 仅用于 answer 文案，不参与计算。
29. **D-A16 边界（v1.39 新增）**：复用 `metric_series`（deterministic，`min_n=30`，executor `capabilities.stats.stablecoin_growth`）。`values` 为稳定币规模序列，`windows` 可配（默认 `(7, 30)`，须为正整数、去重保序），输出 `growth_{k}d`；S16 逐窗口真实执行 `x_t/x_{t-w}-1`，能力层只组装多窗口并折算百分比，不重算统计量。有效样本 <30 降级 `insufficient_samples` 但保留结果；窗口超出历史长度降级 `short_history`；基期为 0 降级 `base_zero` 并将该窗口置 None；全部窗口不可算、`windows` 为空或非法、`dates` 与原序列不等长、含非有限值均 FAIL-OPEN 为 empty。
30. **D-B08 边界（v1.40 新增）**：新增 `technical_indicator` 意图（deterministic，`min_n=60`，executor `capabilities.stats.slope_trend`，data_scope `market.candles`）。取最近 `window` 期（默认 90，下限 30）价格子序列：T08 真实执行对数价格 OLS 斜率与 R²，T09 执行名义 t/p，输出 `slope/r2/window/t/p/hac_corrected/sample_n`。**t/p 为名义值，未做 HAC 修正**，`hac_corrected=false` 必须随结果返回且在 answer 声明「仅作相对比较」，不得用于显著性推荐。有效样本 <60 降级 `short_window` 但保留结果；样本 <30、`window<30`、非整数 window、`dates` 与原序列不等长、含非有限值均 FAIL-OPEN 为 empty。
31. **D-B09 边界（v1.41 新增）**：复用 `technical_indicator`（deterministic，`min_n=250`，executor `capabilities.stats.ath_drawdown`，data_scope `market.candles`），与 D-E10 共用 `drawdown` 执行器（thin wrapper），调度层显式传 `capability_id=D-B09` 与 `intent`。D20/D21 真实执行，能力层不重算回撤，只在既有 `block` 上补别名 `drawdown_from_ath`/`ath`/`ath_ts`（分别等于 `current_drawdown`/`peak_price`/`peak_ts`），使 TD 字段契约可直接消费。`prices<2` FAIL-OPEN 为 empty；样本 <250 期降级 `insufficient_samples`（沿用 `drawdown` 既有降级词）并在 answer 明示样本不足；未提供 `dates` 时 `ath_ts=None` 但不崩溃。结论只描述当前价距历史最高价的回撤幅度，不生成买卖方向。
32. **D-G08 边界（v1.42 新增）**：`metric_derived`（deterministic，`min_n=60`，executor `capabilities.stats.momentum_12_1`，data_scope `market.candles`）。12-1 动量 = 跳过最近 `skip` 期（默认 21）后回溯 `lookback` 期（默认 252）的累计收益。**能力层只做窗口切片（数据整形）**，动量/波动/风险调整动量一律由 F14 在切片上真实执行，禁止能力层自实现收益计算。输出 `momentum_12_1/lookback/skip/vol/risk_adjusted/window_start_ts/window_end_ts/truncated/sample_n`。历史不足 `lookback+skip+1` 时把 lookback 截断到可用长度并降级 `short_history`，窗口起点价格非正降级 `base_zero`；价格样本 <60、`lookback<2`、`skip<0`、参数非整数、日期轴长度不一致或含 None/非有限值 FAIL-OPEN 为 empty。20 日 `ts_rank` 属 D-G07 序列算子族，本能力未接线。
33. **D-G09 边界（v1.43 新增）**：`metric_derived`（deterministic，`min_n=60`，executor `capabilities.stats.vol_target_scale`，data_scope `market.candles`）。价格序列先转日简单收益（**数据整形**），再由 P02 计算窗口内实现年化波动与 `scale = target_vol / realized_vol`，能力层禁止重算波动率。默认 `target_vol=0.10`、`window=20`、`periods=365`；输出 `scale/target_vol/realized_vol/window/periods/returns_n/sample_n`。收益样本 <60、`target_vol≤0` 或非数值、`window<2`、`periods<1`、日期轴长度不一致或含 None/非有限值 FAIL-OPEN 为 empty；`window` 超过收益长度时截断并降级 `window_truncated`，实现波动为 0 时降级 `zero_volatility`。**P02 是面板方法，必须传扁平 `{sym: returns}`**，嵌套 `{"returns": {...}}` 会被方法门禁计为 1 个样本。结论只描述样本内目标/实现波动之比，不构成交易建议。
34. **登记范围复核（v1.50 更新计数）**：52 个可执行出口（含 D-A01、D-A02、D-A03、D-A04、D-A05、D-A06、D-A07、D-A08、D-A09、D-A10、D-A11、D-A12、D-A13、D-A15、D-A16、D-B08、D-B09、D-E15 trend、D-E16 aggregate_curve、D-E17 class_board、D-E18 flow_graph、D-E19 lights、D-G08、D-G09、D-G14、D-G16、D-G19、D-G20、D-J02、D-J04、D-J22、D-J24、D-J30 与 D-E20）不等于 E 组登记范围全部完成。D-E05 双序列与 M05–M07 矩阵 TopK 均已接线；D-E11 已绑定 C18，提供 dates 时执行自然月同向率；D-E01 已按 B02/B05/F01/H01 契约接线，h=1 前瞻收益先在原价格轴计算再过滤有效因子对；D-E12 已按 R18 契约接线，样本不足与空窗口均显式降级为 empty；D-A14 已按 A 分位法（分值历史分布 p20/p60/p80）输出 `level` 并接线；D-E04 事件日经 `bisect_left` 对齐到价格轴（盘后事件落下一交易日），事件数 <30 降级 partial 但保留 CAR/胜率；D-E09 `values` 走 R09、`pairs` 走 B17+R10，对齐点 <3 FAIL-OPEN。
35. **前端 D-A/D-B/D-G cue 分派（v1.44 新增）**：`stat_query` 已接入 D-A01/D-A02/D-A03/D-A04/D-A06/D-A07/D-A08/D-A09/D-A10/D-A11/D-A12/D-A13/D-A15/D-A16 与 D-B08/D-B09/D-G08/D-G09，共 18 个新增分派，不重复增加能力出口。Python/TypeScript fallback 同步，专用 cue 先于宽词；指标序列保留值/日期位置与目录 sign/scale，同比/环比取月频 1825 天；D-A10 将 DGS10 与 CPIAUCSL 月频序列按 `YYYY-MM` 对齐，避免发布日期不同造成空交集；D-A11/D-A12 复用双资产共同交易日、统一收盘锚点和同步日收益；D-B09 使用 L0 最大 1825 天窗口。缺指标、缺序列或缺第二标的均 FAIL-OPEN。金标新增 18 条；Python 78 例与 TypeScript 19 例通过，覆盖 capability ID/kwargs/月份对齐/89 个同步收益/降级边界，ruff 与 Prettier 通过；未操作云端、未提交 Git。
36. **D-G25 边界（v1.47 新增）**：复用 `correlation_query`（deterministic，`min_n=60`，executor `capabilities.stats.tail_dependence`，data_scope `market.candles`）。多资产收益面板按原始行 complete-case 后，P13 以横截面均值收益 ≤ `q` 分位（默认 0.2）切尾，输出下行尾 Pearson `rho_down/rho_full/n_down/n`；上行尾以取反面板复用同一 P13 方法（**不新增 R 组方法 ID，R 组容量 18 已满**），能力层只做配对重组与 `amplification = rho_down / rho_full` 算术，不重算相关系数。输出 `pairs{key:{rho_down,rho_up,rho_full}}/amplification/strongest_pair/n_tail/n`。对齐样本 <60 FAIL-OPEN 为 empty；尾部共现样本 <30 降级 `tail_events_lt_30`。结论只描述同期尾部共跌/共涨强度，不说明领先关系、不构成交易方向。
37. **D-J05 边界（v1.47 新增）**：新增 `cycle_query` 意图（deterministic，`min_n=60`，`min_span_days=2920`，executor `capabilities.stats.cycle_spectrum`，data_scope `market.candles, mm_metrics`）。T25 去线性趋势 DFT 主周期与 T26 周期强度并列执行，提供 `dates` 时 C14 月度一致性一并输出；能力层输出 `period/freq_index/amplitude/power_ratio/span_days/cycles/reference_days/period_to_reference/month_consistency`，其中 `cycles = span_days / period`、`period_to_reference = period / 1,460`（比特币四年周期参照），**周期数与参照倍率必须显式返回**，禁止用「约等于四年」代替量化披露。跨度 <2,920 天（2×1,460）或 `cycles<2` 降级 `cycles_lt_2`；缺日期轴降级 `dates_missing`。结论只描述样本内主导周期与历史覆盖度，不外推下一周期时点、不构成交易方向。
38. **D-E04 节前分支边界（v1.47 新增）**：`event_study` 新增 `pre_holiday`/`holidays`/`lookback` 参数；`pre_holiday=true` 或显式传 `holidays` 时走 C11（不走事件表路径）。节假日由价格日期轴的**工作日缺失**派生（周末不计缺口，`DGS10`/`NASDAQCOM` 等美股序列可直接还原 NYSE 休市日），连续缺失 >10 个工作日按数据缺口计入 `excluded_gaps` 并排除，不视为节假日；计算 n 与价格序列等长对齐（`ret_dates = price_dates[1:][-len(returns):]`）。输出 `pre_mean/base_mean/diff/t/p/n_pre/n_base/n_holidays/excluded_gaps/calendar/lookback/pre_dates/n`。日期轴无工作日缺口（7×24 或周度序列）FAIL-OPEN 为 empty；节前样本 <30 降级 `holiday_events_lt_30`；两组方差为 0 时 `t/p` 返回 None 而非报错。
39. **登记范围复核（v1.48 更新计数）**：可执行出口 50 → **51 个**（新增 D-E20 新闻统一出口），manifest 共 51 条能力声明；`min_n` 与所绑方法门禁保持一致，`methods` 仅引用 `implemented=true` 方法（当前 392 条全实现、0 占位）。
40. **D-E20 边界（v1.48 新增）**：`trend_query`（deterministic，`min_n=2`，executor `capabilities.news.news_digest`，data_scope `datacenter.social_volume`，`method_binding: display`）。只读 `mm_metrics.sub_category='social_volume'` 的 `news_count_24h` / `social_volume` 日频观测，按日对齐输出统一信封（`capability/intent/answer/data/quality`），零重算、不做情绪打分；`answer` 经 `scan_forbidden` 自检「看涨/看跌/建议买入/建议卖出/目标价/多头/空头/推荐」，命中即抛 `ValueError`（fail-closed）；库中**无新闻条目表**，故仅出计数与热度摘要，禁止编造标题/正文/链接；`as_of` 给定即严格截断（`day <= as_of`）；窗口内有效观测 <2 天 → `status=empty` 降级，新闻条数部分缺失 → `status=partial` + `news_metric_partial`，`quality.sample_n` 与 `span` 必须显式返回。
41. **D-A05 边界（v1.50 新增）**：`metric_percentile`（deterministic，`min_n=30`，executor `capabilities.stats.zscore`，data_scope `datacenter.percentile`，`method_binding: compute`）。复用方法层 **S26**（winsorize p1/p99、`min_n=30`、`std=0 → z=None`），能力层只做窗口切片与参数校验，**禁止在能力层重算均值/标准差**；输出 `zscore/mean/std/winsorized/lookback/sample_n`。`MIN_ZSCORE=30`、`MIN_ZSCORE_LOOKBACK=60`：样本 <30 → `empty`；窗口 <60 降级 `short_lookback`；`lookback` 超过可用历史降级 `lookback_truncated` 并按可用样本计算；`σ≈0` 降级 `zero_variance` 且 `z=None`（禁止把零方差伪造成 0）。结论只描述「当前值偏离自身历史均值多少个标准差」，不生成买卖方向。
42. **MERS 全量验收边界（v1.51 新增）**：执行器 `scripts/mers_eval.py` 只读 DAL，写自有 `data/mers/registry.db`（`data/` 已 gitignore），**不写任何 `mm_*` 生产表**；job 样本 <250 记入 `skipped` 而不是静默截断；每 job 单元数固定 180，`method_gate` 三态（ok / not_applicable / failed），`not_applicable` 不计入通过也不伪造输入；`data_version` 必须显式传入（默认当日），同版本复跑命中 `get_eval` 短路、不推进 streak，跨版本才推进；`stable` 遇 `data_version` 变化按契约回退 candidate，故**稳定态需每日运行维持**；状态推进以 `relationship_state` 为 previous，`evaluate_grid` 返回副本里的 candidate 不代表落库状态；保留策略已落地（`RelationshipRegistry.prune_before` + `--prune-days 90`，只清 `relationship_eval` 历史行、`relationship_state` 永久保留），周期任务为 `dreambuddy-mers.timer`（每日 08:20 CST，`Persistent=true`）。

**日线对齐修复（v1.5，2026-11-14）**：`market.candles` 1d 的 `ts` 统一归一到 **UTC 日首**（真实观测时刻保留 `close_ts`），并新增 `meta.close_anchor ∈ {bar_close, snapshot_last}` 与 `source_policy ∈ {auto, snapshot, bars}`。**跨资产横截面统计（D-E05/D-E06/D-E11）必须两侧同锚点**：执行器优先 `source_policy=snapshot`，某标的无快照才退回 `auto` 并在回答标注。修复前 BTC（真实日线 00:00）与 ETH（快照 16:00）锚点混用，同期 ρ=0.33 且最优 lag=+1；修复后 ρ=0.83、最优 lag=0（n=727）。

---

## §十三、方法总目录与分类评审（v1.0）

### 13.1 五套方法资产汇总

| 资产 | 文件 | 规模 | 定位 |
|---|---|---|---|
| 经典方法库 | [docs/METHOD_LIBRARY.md](docs/METHOD_LIBRARY.md) | 238 方法 + 18 关系原语 | 金融/时序/统计基础 |
| 机构方法 | [docs/RESEARCH-INSTITUTIONAL-L1-METHODS.md](docs/RESEARCH-INSTITUTIONAL-L1-METHODS.md) | X 12 + O 15 + P 14 + Q 16 | 横截面/算子/风险/研究协议 |
| 科研方法 | [docs/RESEARCH-SCIENTIFIC-METHODS.md](docs/RESEARCH-SCIENTIFIC-METHODS.md) | SC01–SC92（13 族） | 通用数据化科研 |
| 能力登记 | [docs/TECHNICAL_DESIGN.md](docs/TECHNICAL_DESIGN.md) | A16+B10+C6+E12+G25+J30 = 99 项 | 唯一登记册 |
| 方法路由 | METHOD_LIBRARY §12 | 12 意图 → 方法组 | L1 选法 |

### 13.2 统一分类（按「数据形态 × 分析目的」）

| 数据形态 \ 目的 | 描述 | 关系 | 结构/变化 | 不确定度 |
|---|---|---|---|---|
| 单序列 | S01–S28, D01–D24 | R01–R03, R09, R17 | T01–T28, SC49–SC62 | SC01–SC12, SC63–SC66 |
| 双序列/多序列 | M01–M08 | M09–M12, R05–R06, R14–R16 | SC39–SC48, SC67–SC72 | SC79–SC83 |
| 面板/横截面 | X01–X08 | X09–X12, G03–G05 | SC31–SC38 | SC25–SC30 |
| 事件/生存 | F19–F23 | R04, R10, R12 | SC73–SC78 | SC13–SC24 |
| 高维信号 | I01–I34 | B13–B15, O01–O15 | SC62, SC39–SC47 | SC14–SC16 |
| 数据质量 | SC84–SC90 | — | — | SC09, SC15–SC16 |

### 13.3 准入评审结论

**结论：全部保留（370 方法）**，但必须满足四条调用纪律：

1. 参数显式登记（窗口/分箱/阈值/seed），禁止隐式默认；
2. D2/D3 必须返回 `n`、`p` 或 `CI`；
3. 批量扫描（≥10 次比较）强制 BH-FDR；
4. 随机类方法统一 `seed=42` 并标 `D3-seeded`。

### 13.4 统一调用契约（所有方法一致）

```json
{
  "method_id": "M01",
  "inputs": {"series": [{"ts": "...", "value": 0}], "params": {}},
  "params": {"window": 90, "horizon": 5},
  "meta": {"seed": 42, "data_version": "sha1:...", "caller": "l1"}
}
```

```json
{
  "ok": true,
  "method_id": "M01",
  "value": {"rho": 0.42, "p": 0.0003},
  "quality": {"n": 512, "span": "2021-01..2026-11", "seeded": false, "degraded": false, "degraded_reason": ""},
  "caveat": "历史统计，不代表未来"
}
```

---

## §十四、周期性关系评估与推荐系统（MERS）

### 14.1 定位与边界

- **做什么**：按固定口径周期性评估「数据能力 × 统计方法 × 目标序列（默认价格）」的关系强度，产出排序注册表，供 L1 选法时**优先使用**。
- **不做什么**：不产生交易信号、不做参数优化、不做因果解释、不预测。
- **确定性来源**：固定网格 + 固定评分权重 + 固定分段 + 版本化数据 → 同输入同结果。
- **分两阶段交付**：S3 具备「计算内核」（生成注册表，仅供内部选法，L1 不得直答推荐）；S5 才开放「对外推荐」（`relationship_recommend` 意图上线）。
- **S3 实现状态（v1.8）**：`l1agg/mers.py` + `config/mers_grid.yaml` 已实现固定 180 单元、全批 BH-FDR、前后半段与末 30% 同号门禁、状态机和 SQLite 幂等注册表；同版本重跑不推进状态，固定随机序列三期 `stable=0`。R03/R04/F19 在缺少日历/事件上下文时明确 `not_applicable`，不伪造结果；生产周期写入仍只能在云端执行。

### 14.2 评估单元与预注册网格

```
评估单元 = (dataset, metric, method_id, params, transform, target, horizon)
默认网格：
  transform ∈ {raw, diff, pct, zscore60, ts_rank60, quintile5}
  method    ∈ {M01, M02, M11, B11, B13, B14, R01, R03, R04, F19}（首期 10 个）
  horizon   ∈ {1, 5, 20}（日频）
  target    ∈ {资产池价格}（可扩展到任意目标序列）
```

网格写入 `config/mers_grid.yaml` 并计算 `grid_hash`；**运行期不得修改网格**（改动即新版本）。

### 14.3 评分与门禁

| 项 | 规则 |
|---|---|
| 主排序 | `|RankIC|`（Spearman，signal_t vs fwd_ret_{t+h}）降序 |
| 辅助指标 | ICIR、方向命中率、Q5−Q1 价差、分箱单调性、覆盖率、前后半段稳定性 |
| 展示分 RSS（固定权重） | `0.4·|RankIC| + 0.2·min(|ICIR|/3,1) + 0.2·(2·hit−1) + 0.1·monotonicity + 0.1·stability` |
| **门禁（全部满足才可推荐）** | n≥250；BH-FDR `p_adj<0.05`；前后半段 RankIC 同号；末 30% holdout 同号；coverage≥0.8 |

### 14.4 状态机

```
candidate --连续3期通过--> stable --连续2期失败--> decayed --连续4期失败--> retired
stable --数据版本变更--> candidate（保留历史评分）
```

### 14.5 存储（`54/data/relationship_registry.db`）

```sql
CREATE TABLE relationship_eval (
  eval_id        TEXT PRIMARY KEY,  -- sha1(dataset|metric|method|params|target|horizon|data_version)
  dataset        TEXT, metric TEXT, method TEXT, params_json TEXT, transform TEXT,
  target         TEXT, horizon INTEGER,
  n              INTEGER, rank_ic REAL, icir REAL, hit_rate REAL, spread REAL,
  monotonicity   REAL, stability REAL, coverage REAL,
  p_value        REAL, p_adj REAL, rss REAL, status TEXT,
  data_version   TEXT, grid_hash TEXT, eval_at TEXT, run_id TEXT
);
CREATE INDEX idx_rel_pick ON relationship_eval(target, horizon, status, rank_ic DESC);
```

`eval_id` 确定性 → upsert 幂等，重跑不产生重复行。

### 14.6 调度

- `jobs/periodic_eval.py`，systemd timer / cron：日频数据每日 03:10，周频数据每周一 03:10；
- 增量：按 `data_version` 跳过未变更单元；单次运行预算 ≤ 10 分钟；
- 失败 FAIL-OPEN：保留上一期注册表，写 `run_status=failed`，不阻塞 L1。

### 14.7 L1 消费协议

新增意图 `relationship_recommend`（deterministic，只读注册表）：

1. 查询 `status IN (stable, candidate)` 且通过门禁、按 `rank_ic DESC, n DESC` 取 Top3；
2. 输出必须含 `method_id, |RankIC|, n, p_adj, stability, eval_at, data_version`；
3. Top1 未通过门禁 → 回落 `METHOD_LIBRARY §12` 默认方法序；
4. 措辞固定：「历史 {n} 个样本上，{方法} 与该目标的关系强度 |RankIC|={x}（p_adj={p}，评估于 {date}）。」

### 14.8 验收

- 同 `data_version` 重跑，注册表 `eval_id` 与 `rank_ic` 完全一致（字节级 diff 为空）；
- 单次运行 ≤10 分钟、≤5000 单元；
- L1 询问时 Top 推荐与注册表一致，且带全部门禁字段；
- 注入随机数据时 `stable` 数量为 0（负样本验收）。

---

## §十五、探索发现模式（Discovery）

### 15.1 定位

在**预注册的有限搜索空间**内枚举「数据组合 × 统计算法 × 变换」，输出确定性的关系候选；只陈述统计事实，不做推理。

### 15.2 搜索空间（预注册，禁止运行时扩张）

| 维度 | 取值 | 说明 |
|---|---|---|
| 序列池 | 资产池 + 宏观白名单（≤40 条） | `config/discovery_space.yaml` |
| 组合 | 单序列；双序列（pair ≤ 300 对） | 三序列及以上禁 |
| 变换 | raw / diff / pct / zscore60 / ts_rank60 / quintile5 | 固定 6 种 |
| 方法 | M01/M02/M11/M12、B01–B05、B11–B15、R01–R04、SC52、SC62 | 固定子集（关系型） |
| 目标 | 价格前瞻收益 h∈{1,5,20}；可配任意目标序列 | 默认价格 |
| 预算 | ≤5,000 单元/次；≤10 分钟；seed=42 | 超限截断并记录 |

### 15.3 流程（固定六步）

```
① 载入 manifest（序列池 + 网格 + data_version + grid_hash）
② 枚举候选（去重：同序列同变换同方法只算一次）
③ 打分（RankIC / ICIR / 命中率 / 单调性 / 稳定性）
④ BH-FDR 校正（全批 p 值）
⑤ 信号去重（两两 |corr|>0.95 时保留 |RankIC| 高者）
⑥ 分段与留出：前 70% 筛选，末 30% holdout 仅验证不参与选择
```

### 15.4 产物（`54/reports/discovery/<YYYYMMDD-HHMM>/`）

| 文件 | 内容 |
|---|---|
| `manifest.json` | 搜索空间快照、`grid_hash`、seed、data_version、代码版本 |
| `findings.jsonl` | 每行一个候选：公式、参数、n、rank_ic、p_adj、stability、holdout_ic、status=candidate |
| `SUMMARY.md` | Top20 表 + 数据源分布 + 方法分布 + 淘汰原因统计 |

### 15.5 治理（硬规则）

1. Discovery 结果**不得直接进 L1 直答**；须经 MERS 连续 3 期复核晋升 `stable`；
2. 每期 `manifest.json` 必须可复现（同 hash 同结果）；
3. 禁止用 holdout 反复调参；一轮只允许一次 holdout 验证；
4. 发现数量上限 50，超出按 |RankIC| 截断；
5. 所有输出标注 `candidate`，禁止因果与预测措辞。

### 15.6 L1 查询协议

新增意图 `discovery_query`（deterministic，只读最新报告）：
「最近一期发现：{方法} 作用于 {序列}（变换 {t}）与 {目标} 的关系 |RankIC|={x}（n={n}，p_adj={p}，状态 candidate）。」

### 15.7 验收

- 同 manifest 重跑，`findings.jsonl` 完全相同；
- 纯随机序列注入：FDR 后 `findings` 为 0；
- 5000 单元运行 ≤10 分钟；
- holdout 与筛选段符号一致率 ≥ 0.6 才允许进入候选。

---

## §十六、本轮评审结论

### 16.1 评分（1–5）

| 维度 | MERS | Discovery | 说明 |
|---|---|---|---|
| 统计正确性 | 4 | 4 | 门禁完整，但需 FDR 强制 |
| 确定性/可复现 | 5 | 5 | eval_id/manifest 哈希 + 固定网格 |
| 防过拟合 | 4 | 3 | Discovery 依赖预注册与 holdout 纪律 |
| 性能 | 4 | 3 | 5000 单元预算需向量化 |
| 可解释 | 5 | 5 | 全部输出 n/p/方法 ID |
| 可运维 | 4 | 4 | 定时任务 + FAIL-OPEN |
| **综合** | **4.3** | **3.9** | |

### 16.2 风险与对策

| # | 风险 | 对策 |
|---|---|---|
| 1 | 多重检验导致假发现 | BH-FDR 强制 + holdout 隔离 + MERS 3 期晋升 |
| 2 | 数据窥探（反复看 holdout） | 一轮一次 holdout，记录 `holdout_used=true` |
| 3 | 推荐随时间失效 | 状态机 decayed/retired + 每期重评 |
| 4 | 未来函数（全样本分位） | 分位边界用当期横截面，PIT 校验 |
| 5 | 计算成本 | 单元预算 + 增量 + 序列缓存 |
| 6 | 语义越界 | 模板禁令 + 强制 caveat + 评审抽检 |
| 7 | 冷启动（价格仅 2 周） | 先回填 ≥3 年；否则 MERS 只评估非价格目标 |
| 8 | 单一市场状态过拟合 | 分高/低波动两段报告，不做加权 |

### 16.3 阻断项（P1 前必须闭环）

- **B1 价格历史**：回填 OKX `history-candles` 或 CoinGecko，≥3 年日频；
- **B2 资产池**：定义 8 个资产（BTC/ETH/SOL + 纳指/标普/黄金/原油/美债）；
- **B3 预注册文件**：`config/mers_grid.yaml`、`config/discovery_space.yaml` 落库并冻结；
- **B4 FDR 强制**：所有批量评估默认 BH 校正，不可关；
- **B5 holdout 隔离**：末 30% 数据在筛选阶段不可见（代码级隔离）；
- **B6 MERS 分阶段开关**：S3 阶段注册表只允许内部调用（配置 `MERS_EXTERNAL_RECOMMEND=false`），S5 门禁通过后才可置 `true` 并开放 `relationship_recommend`。

### 16.4 结论

**有条件通过**（MERS 4.3 / Discovery 3.9）：架构与确定性成立，B1–B6 闭环后进入 S1。

---

## §十七、完整落地路线与建议

### 17.1 五级能力路线（按能力层级逐项落地，替代原 P0–P3 表述）

**评估结论：顺序合理，附和「数据 → 关系 → 元方法」的依赖链，且每级都有用户可见产出。需四处修正**：

1. **S1 必须同时覆盖「过去」**：只做「现在」可查，S2/S3 无数据可用 → 价格回填与资产池定义并入 S1 的前置（S1.0）。
2. **S4 改名「条件外推表达」**：不做点预测。只允许「当前状态 → 历史同状态的前瞻分布 + 区间」，或暴露既有模型输出（标 `model_output`）；禁止「将会/预计点位」。
3. **S5 的 MERS 提前做内部窄版**：S3 需要「哪个方法与该指标关系最强」来选法，因此 MERS 的计算内核在 S3 就要具备（仅内部使用、不对外推荐）；对外推荐与 Discovery 留在 S5。
4. **相关性之前插入对齐层、排名后置（v1.2 新增）**：实测仅 26 条序列可与 BTC 日频价格对齐 ≥60 天，加密域指标只有 14–44 天 → 必须先建 `market.candles` + `l1agg/align.py`，并通过加密域历史回填；「回测排名」是 B13–B16 的下游产物，不是与统计学方法并列的阶段。详见 §17.1.3。

### 17.1.0 S1.0 硬前置（整条路线唯一阻断项，必须先完成）

| # | 任务 | 产出 | 验收 |
|---|---|---|---|
| 1 | `mm_metrics` 索引迁移 | `(sub_category, metric_name, timestamp)` 复合索引 | `EXPLAIN QUERY PLAN` 走索引；区间查询 P95≤300ms ✅ 2026-11-14（本地 p95 0.78ms；云端索引已存在） |
| 2 | 资产池定稿 | `config/asset_pool.yaml`：BTC/ETH/SOL + 纳指(IXIC)/标普(SPX)/黄金(XAU)/原油(WTI)/美债(US10Y) | 8 个资产各有 `instrument/storage/timezone`；类别龙头唯一；`python3 -m l1agg.asset_pool` 校验通过 ✅ 2026-11-14 |
| 3 | 价格历史回填 | OKX `history-candles` 日频 ≥3 年（缺失回退 CoinGecko chart） | 每资产 ≥1,090 条（3 年日历日 1095/1096 闰年浮动）；缺口率 <1% ✅ 2026-11-14 云端执行：BTC/ETH/SOL/XAU 各 1,094 条 × `close_usd`/`volume_usd`，跨度 2023-11-15~2026-11-12，缺口 0 |
| 4 | 覆盖体检报告 | `reports/coverage/<date>.md`：每个 metric 的 n / 起止 / 缺失率 / 异常值标记 | 报告生成且 metric 清单与 DAL 一致 ✅ 2026-11-14 云端执行：8/8 锚定资产 PASS；27,202 series / 344,936 行；NULL 1,580（0.46%）；负 epoch 4,388 行登记为 FRED 真实历史；跨源重复 2 组（`BTC_FUTURES_CME`、`funding_rate`） |

> 四项全部通过才可进入 S1；任一项失败则 S2/S3 不得启动（相关性、条件收益都会因样本不足而产生假规律）。

| 级 | 能力 | 交付物（用户可见） | 依赖 | 验收门禁 |
|---|---|---|---|---|
| **S1** | 前端各模块数据可查（现在 + 过去） | 11 个基本面模块全部字段可查；每模块真实 `timeseries`（30/90/365 天）；行情/宏观/链上/情绪/资金 实时与历史同入口 | 索引迁移；`datacenter.series`；价格回填 ≥3 年（S1.0） | 每模块 ≥3 个自然语言查询命中 L1；`timeseries` 非空且 `sample_n` 正确；P95≤800ms |
| **S2 🟡** | 多维数据相关性组合 | 相关矩阵 TopK、领先滞后、滚动相关、同向率、固定权重合成指标；「哪些资产相关性最高」可直答 | S1 + 统一资产池（8 资产）+ **加密域历史回填（≥60 对齐点）** | 输出带 `n/p/window/align_method`；`n≥60` 才出同期相关、`n≥120` 才出 CCF；随机序列相关系数≈0 且不显著。当前方法层完成，D-E05 矩阵 TopK、D-E11/C18 与 D-E12/R18 已接线；D-A14/F26 固定权重分已就绪，`level` 阈值冻结前不接完整能力 |
| **S3 🟡** | 高相关数据与价格的统计关系 | 条件收益、分位→前瞻分布、分箱单调性、日历效应、回撤画像（R01/R02/R03/R08/R11） | S2 + MERS 计算内核（内部） | 每关系输出 `n/win_rate/mean/p_adj/单调性`；随机数据无显著；方法选择可追溯 `method_id`。D-E01/D-E02 与 R02 PIT 能力出口已交付；MERS S3 内部 180 单元网格、BH-FDR、状态机与幂等注册表已实现，待全量真实数据验收及云端周期调度 |
| **S4 ⬜** | 过去 + 现在的条件外推表达（非点预测） | 「当前处于 X 状态，历史同状态后 h 日分布：均值/中位/胜率/区间」；既有模型输出（bdsm/bcrm2/event）gated 暴露 | S3；T0.5/T2 另需 R02 `pit=true`（已实现） | 必须含区间、样本量及 `pit/as_of/effective_n/nonoverlap_n`；无模型输出时降级为纯历史分布；禁止点预测措辞（抽检 20 条）；h>1 显著性推断须经 D-G22 出口（Q06 HAC t / Q07 DSR），不得用朴素 t 值 |
| **S5** | 统计方法扩展 + 回测推荐 + 探索发现 | MERS v1 注册表（10 方法 × 3 期限 × 8 资产）+ `relationship_recommend`；Discovery v1（≤2000 单元）+ `discovery_query`；G/J 组方法扩展 | S1–S4 全部稳定 | MERS 重跑字节一致；随机数据 `stable=0`；Discovery 随机数据 `findings=0`；5000 单元≤10min |

**阶段映射**：S1 = 原 P0 + 价格回填；S2 = 原 P2 相关性部分；S3 = 原 P1 关系表达；S4 = 原 P2 预测类收口；S5 = 原 P1/P3 的 MERS 与 Discovery 扩展。

### 17.1.1 逐级推进纪律

- 每级完成后**先跑该级门禁再做下一级**，不允许跨级并行开发；
- 每级必须新增对应 golden 用例（自然语言 → 期望能力/方法），并入 `test_l1_intent_golden.py`；
- 每级结束产出「能力清单 + 实测样例 + 未覆盖项」三段报告，作为下一级输入；
- 任一级 FAIL 时只回滚该级能力开关，不影响已上线能力。

### 17.1.2 非锚定代币策略（一生二、二生三）

锚定表只保留 8 个有 ≥3 年历史的资产；**其他代币不逐一定义**：

1. 用户显式询问某代币时，经 `6-TRADING/scripts/okx_cli.py` 按需取数（`on_demand_only: true`，不做全市场扫描）；
2. 代币归入其 `asset_class`，与该类别龙头锚定资产建立统计关系：`corr_btc_90d/365d`、`beta_btc_90d`、`corr_eth_90d`、分位桶；
3. 样本 <90 条时降级为 `insufficient_samples`，不输出相关性；
4. 缓存 1 小时（`cache_ttl_seconds: 3600`），避免重复拉取；
5. **边界**：代币基本面、叙事、团队、解锁等属 L2，L1 只输出与龙头资产的统计关系，不做代币研究。

> 配置见 `config/asset_pool.yaml` 的 `dynamic` 段；加载器 `l1agg/asset_pool.py` 负责校验（含 benchmarks 必须在锚定表内）。

### 17.1.3 数据纵深实测与顺序修正（v1.2，2026-11-14 调研结论）

**结论：原 S1–S5 顺序成立，但「过去数据」的瓶颈判断需修正——不是价格，是指标历史纵深；且相关性之前必须插入「对齐层」，回测排名应降为 S3/S4 的下游。**

实测证据（云端快照只读）：

| 数据面 | 实测 | 判定 |
|---|---|---|
| 日频价格 | `BTC/ETH/SOL/XAU close_usd` 各 1,094 点，2023-11-15 ~ 2026-11-12，缺口 0 | ✅ S1.0 已闭环 |
| 宏观 FRED | 19 条序列与近 3 年价格窗口重叠 ≥250 天 | ✅ 可用 |
| 加密域指标 | `derivatives_spot`/`etf_institutional`/`exchanges_whales`/`holdings_onchain_funds`/`stablecoin_rwa` 均 28 天；`options` 44、`funding_rate` 40、`btc_onchain` 37、`etf_flow` 14、`okx_derivatives` 8 | ❌ 不满足相关性门禁 |
| 专用表 | `mm_funding_rate`/`mm_open_interest`/`mm_liquidation`/`mm_long_short_ratio`/`mm_taker_volume`/`mm_fear_greed` 本地 0 行 | ❌ |
| 全库纵深 | 27,290 个 `sub::metric` 中 25,795 个仅 1 天；≥250 天 28 条；与 BTC 日频重叠 ≥60 天仅 26 条 | 决定 S2 因子池上限 |
| 事件表 | `mm_events` 16 行（历史回填通道已就绪：2015–2026 共 542 条，待云端入库） | 回填入库前 R04/F19–F23 仍不可做 |

**修正后的推进顺序（与 METHOD_LIBRARY §14 对齐）**：

| 阶段 | 内容 | 门禁 |
|---|---|---|
| S0 ✅ | 单点 + 周期序列直答（`metric_series`） | 已上线 |
| **S1-a** | 新增 L0 scope `market.candles`（1D/1W/1M，由 `mm_metrics` 日频价格派生） | 任一资产 ≥1,090 根；`quality/sample_n/span` 齐全 |
| **S1-b** | 新增对齐层 `l1agg/align.py`（UTC 日收盘口径、跨源去重、低频 ffill、前瞻收益、样本门禁） | 对齐后缺失率 <5%；任何 D2/D3 输出必带 `align_method/timezone` |
| **S1-c** | 价格回显 `l1agg/price_echo.py`：任意历史时点 → 当时价 + 现价 + 变化；默认基准按品类（加密→BTC、美股→US500/US100/DJIA、宏观→XAU+美股指数、大宗→CL、避险→XAU、其他→BTC） | `asof_day/staleness_days/sample_n/span/align_method/timezone/gate` 齐全；禁止未来函数；抽查 20 条与库内原始行一致 |
| **S1-d** ✅ | 四类追问钩子 `l1agg/hooks.py`（回显/龙头对照/相关性 Top/延续性强度）+ 三项可执行能力 `l1agg/relations.py`：任何确定性答案末尾追加 4 个可选下一步，`data.hooks` 同步结构化返回 | 钩子 query 必须能被 `l1_route_signal` 确定性路由到对应执行器（4/4 L1_DIRECT）；无年份日期「9月9日」解析为当年最近一次过去；`leader_gap/top_correlated/persistence_strength` 均带 `sample_n/span/align_method`。**相关性口径**：排除同质价格（自身/同赛道币价、市值、盘口、成交量），按指标观测频率分组（daily n≥120 / weekly n≥52 / monthly n≥36）独立 BH-FDR，样本不足单列 `low_sample` 不参与排名，资产价格相关单列 `price_baseline` |
| **S2-p** | **跨资产历史回填**（18 职责，云端执行，幂等）；分类口径与 **40 层 `asset_classes.py` 完全统一**，54 仅做绑定（`l1agg/leader_registry.py`）：已绑定 28 个龙头、诚实登记 1 个历史不足 | 对齐点 ≥250 天的跨资产龙头 ≥10 条（当前 28 条达标，2026-11-14 回填后） |
| S2 🟡 | 相关性（M01–M07/M11–M12/M24–M25 + R05）方法注册表 + 评估 harness 已落地；D-E05 双序列与矩阵 TopK、D-E06、D-E11/C18、D-E12/R18 可执行；D-A14 拥挤度合成（A 分位法四档）已接线 | `n≥60` 同期、`n≥120` CCF；p 值走 t 分布 + BH-FDR；harness 六检 11/11 PASS；随机白噪声负例 `\|ρ\|<0.15` 且假阳率 ≤20%。D-A14 的 `level` 四档已冻结并接线，剩余为完整四类榜单契约 |
| S3 🟡 | 条件收益/IC/分组方法层已交付，T0/D-E13、T0.5/D-E02 与 D-E01 等能力出口已交付；R02 双口径及能力接线均已完成 | `n≥250`；T0.5/T2 只接受 R02 `pit=true`；h>1 重叠前瞻收益须经 D-G22 出口（Q06/Q07）再作显著性结论 |
| S4 🟡 | 条件外推表达（非点预测）；T0.5 与 D-E14 一维 h=1/2 已交付 | 含区间与 `pit/as_of/effective_n/nonoverlap_n`；每桶非重叠 n≥250；h>1 不输出朴素 t/p；二维 T2 仍等扩样本与 F1–F12 状态特征 |
| S5 | 回测排名：复用并修正 23 `FactorICSelector` | 必须含样本外 IC 与 walk-forward |

> **与场景包的关系（v1.3）**：延续性画像（`D-E13`，T0）是「**S3 自身延续性子集**」的已落地实现，不是 S3 之外的新阶段；S3 的证据不依赖 S2-p 回填（只用价格），而 S2 的相关性仍受因子池上限约束。T 阶段与 S 级的完整映射见 §3.5.3。

**已知缺陷（S5 前必须修，属 23 域）**：
1. `forward_returns` 的 `L.shift(-h).rolling(h).sum().shift(-h+1)` 在 `h>1` 时多位移 `h-1` 天；
2. `ic_ir` 用 5 个 horizon 的 IC 求 mean/std，非标准滚动时间序列 IC_IR；`win_rate` 的 n=5 无统计意义；
3. 价格源读 `price_path` JSON，未走 19/L0，违反「唯一数据源」。

**S1 验收结果（2026-11-14 真实库实测）**：

| 检查项 | 实测 | 判定 |
|---|---|---|
| `market.candles` 1d（BTC，1825 天窗口） | `sample_n=1094`、`2023-11-15~2026-11-12`、`quality=good`、`missing_rate=0.0`、`has_ohlc=false` | ✅ 过（≥1,090 根） |
| 1w / 1m | 157 根 / 37 根，quality 均 good | ✅ 过 |
| 对齐：`CPIAUCSL`（月频） | `aligned_n=1063`、`stale_ratio=0.93`、`max_stale_days=45`、`gate60=ok` | ✅ 过（月频自动放宽陈旧上限） |
| 对齐：`DGS10`（日频，含周末） | `aligned_n=1094`、`stale_ratio=0.31` | ✅ 过 |
| 对齐：`crypto_fear_greed` | `aligned_n=1094`、`stale_ratio=0.001` | ✅ 过 |
| 对齐：`derivatives_spot.fut_open_interest_usd` | `aligned_n=8`、`missing_rate=0.99`、`gate=insufficient_samples` | ✅ 正确拦截（证明 S2 前必须先回填） |
| 对齐：`etf_flow.total_flow` | `aligned_n=15`、`gate=insufficient_samples` | ✅ 正确拦截 |
| `align` 单测 | 12 条全通过（含「h 期前瞻收益不得多位移」回归） | ✅ 过 |

**S2 缺口决策与验收（2026-11-14，v1.3-6）**

| 缺口 | 决策 | 依据 / 落地 |
|---|---|---|
| OI 长历史（规范序列 `open_interest.open_interest_value` 仅 32 天） | **禁止跨所/跨口径拼接**；新增 Binance Vision 日频 `sum_open_interest_value` 单所长历史序列 `open_interest.open_interest_value_binance`（USD）+ `open_interest_btc_binance` | 实测 OKX rubik 全合约聚合口径与 ccxt 单合约同日相差 ~35%，拼接会产生假跳变；Binance Vision 免 Key、2020 起、含 USD 口径，1095 天可一次回填。规范序列保持 ccxt 原口径不动，S2/S3 若要长历史须**显式选 `_binance` 指标** |
| 清算（liquidation） | **永久 `not_collected`（不采集）**，任何方法遇到必须返回 `not_collected` | OKX/Binance 仅 24h 快照，Coinglass 历史需付费 Key；不编造 |
| OKX OI / 多空账户比仅 180 天 | 保留为**交叉验证源**（`open_interest_value_ccy` / `long_short_ratio`），不承担长历史主链 | 免费源硬上限（更早窗口返回 `50030 Illegal time range`） |
| 大户多空比 | OKX `long-short-account-ratio-contract` 分窗口回填 **730 天**，作为多空长历史主链 | `begin/end` 实测可回溯 700+ 天 |
| 资金费率 | 主链 Binance `fapi/v1/fundingRate` **1096 天**；OKX 96 天保留交叉验证 | OKX funding-history 只保留约 96 天，且向旧翻页必须用 `after=` |
| ETF 净流入 | Farside 全量 **730 天**（13 发行人列 + `total_flow`，百万美元） | 云端直连 Cloudflare 403，经 `r.jina.ai` 只读代理取 Markdown 表格 |

**S2 回填验收（云端 `mm_metrics` 实测）**：加密域 ≥250 天序列 **26 条**（BTC/ETH/SOL/XAU 价格+成交量各 1,094、Binance 费率 1,096、ETF 13 列 730、大户多空 730、XAG 290、XCU 255），S2-p 门禁「≥10 条」通过；OI 180 天、清算 0 天为已登记缺口，不阻塞 S2 相关性（n≥60/120 门禁）。

**跨资产龙头注册（S1-b 同步注册，分类 SSoT = 40 层）**

分类**不在 54 另立**：[leader_registry.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/54-L1架构能力聚合层/l1agg/leader_registry.py) 直接加载 `40-周期神经网络系统/asset_classes.py` 的 `ASSET_CLASSES / G1_ANCHORS / G0_MACRO`，54 只补「龙头 → DAL 序列」绑定；无数据者进 `UNBOUND` 并附原因，`align.load_leader()` 遇到即抛 `not_collected`，**禁止静默空序列**。

实测覆盖（2026-11-14 跨资产回填后，`min_days=250`，`coverage_summary` 云端复检 28 available / 1 not_collected）：

| 大类（40 口径） | 已绑定（n≥250） | 未采集（诚实登记） |
|---|---|---|
| crypto | BTC 1,094 / ETH 1,094 / SOL 1,094 | — |
| precious_metal | XAU 1,094 / XAG 290（OKX 永续） | — |
| industrial_metal | XCU 255（OKX 永续） | — |
| energy | CL 9,545（FRED WTI 代理）/ BZ 757（DCOILBRENTEU 代理）/ NG 746（DHHNGSP 代理） | — |
| us_index | **US500 2,521（标普）/ US100 14,066（纳指）/ DJIA 752（DIA 代理）** + VIX 9,320 | — |
| us_stock | NVDA / AAPL / MSFT / TSLA / AMZN / GOOGL / META 各 752（Nasdaq） | — |
| us_etf | SPY 752 / QQQ 752（Nasdaq） | — |
| apac_index | — | JP225（OKX 永续 2026-09 上线，67 天 < 250 天） |
| fx | DXY 5,235（DTWEXBGS 代理） | — |
| rates_credit | TLT 16,206（DGS10 代理）/ T10Y2Y 12,607 / HY_OAS 784 | — |
| macro（G0 门控） | CPI 1,009 / INDPRO 1,346 | — |

> 口径说明：`CL/DXY/US500/US100/TLT/DJIA/BZ/NG` 为**代理序列**，绑定中 `proxy=True`，任何输出必须带出。道指用 DIA（道指 ETF）代理——Nasdaq 公开 API 无 `^DJI` 指数历史、Yahoo 对云端 IP 返回 429、FRED `DJIA` 已停更；美股/ETF/金属/能源由 `scripts/backfill_cross_asset_leaders.py` 幂等回填（Nasdaq API + OKX 永续 + FRED API），后续只需在 `BINDINGS` 增加一行即自动进入对齐层与相关性，无需改方法层。

### 17.2 与 L1 的关系（重申）

MERS 与 Discovery 只改变「**选哪个方法**」，不改变「**输出什么**」——L1 输出永远是「方法 + 样本量 + 统计量 + 历史事实 + caveat」。

### 17.3 建议（5 条）

1. **先回填价格，再谈推荐**：没有 ≥3 年日频价格，MERS 就是无本之木；建议把回填作为 P1 第 0 项。
2. **MERS 先做窄网格**：首期只 10 方法 × 3 期限 × 8 资产，跑满 8 周再扩；一次性铺 370 方法会导致运维与解释成本失控。
3. **Discovery 单独隔离**：独立目录、独立预算、独立报告，禁止与 MERS 共享状态，避免污染推荐。
4. **上线前做两次负样本验收**：随机序列 + 打乱标签，`stable`/`findings` 必须为 0，这是唯一能证明防过拟合的硬证据。
5. **把 `recommend_method` 的回退路径做成默认行为**：注册表缺失/过期/未通过门禁时，静默回落到方法库默认顺序，保证 L1 永不因推荐系统故障而不可用。

---

## §十二、修订记录（v0.1 → v1.53）

### v1.53（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.53-1 | §14 / TD §6.4.5 #35 | **上线云端周期调度**：`deploy/systemd/dreambuddy-mers.{service,timer}`，`OnCalendar=*-*-* 08:20:00`（CST，避开 06:00–07:00 数据批次）、`Persistent=true`、`RandomizedDelaySec=300`、`Type=oneshot`、`TimeoutStartSec=3600`；以 `User=luke` 只读 DAL、写自有 `data/mers/`，输出 `data/mers/last_summary.json` + journald |
| v1.53-2 | §14 保留策略 | 新增 `RelationshipRegistry.prune_before(cutoff_iso)` 与 `scripts/mers_eval.py --prune-days`（默认 0）：只删 `relationship_eval` 中 `eval_at < cutoff` 的历史行，`relationship_state` 永久保留；每日 ≈5,220 行，90 天封顶 ≈47 万行；summary 增加 `retention{keep_days,cutoff,pruned_rows,rows_after_prune}` |
| v1.53-3 | §14 版本口径 | `--data-version` 默认当日：同日重复触发命中 `get_eval` 短路（`added=0`、不推进 streak），跨日自动推进；**稳定态需每日运行维持**（stable 遇版本变化回退 candidate） |
| v1.53-4 | §17/测试 | `tests/test_mers.py::test_prune_drops_history_but_keeps_current_state`（180 行删除 / 1 行保留 / state 保持 `pass_streak=2` / 同 cutoff 二次清理 0 行）；`tests/test_mers.py` 5 passed |

### v1.52（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.52-1 | §3 | **启用 `datacenter.correlation` scope**：manifest D-A11（`rolling_correlation`）与 D-A12（`lead_lag_correlation`）`data_scope` 由 `datacenter.series` 迁到 `datacenter.correlation`，能力层 `quality.sources` 同步（双序列对齐语义不再借用单序列 scope）；出口数不变 52 |
| v1.52-2 | §3 | D-A04（`percentile_rank`）`data_scope` 对齐到 `datacenter.percentile`（与 D-A05 同 scope）；TD §3 scope 表收敛为 `datacenter.percentile → D-A04/05`、`market.candles → D-A07、D-B00–B09`，表与 manifest 一致 |
| v1.52-3 | §17/测试 | `tests/test_capabilities.py` 四处 `data_scope` 断言同步更新，D-A11/D-A12 行为用例未改动仍全绿 |

### v1.51（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.51-1 | §14 / TD §6.4.5 #35 | **MERS S3 全量真实数据验收通过**：新增执行器 `scripts/mers_eval.py`（commit `53952864c2`），把 20 个 `close_1d` 资产与 9 个宏观/情绪/资金费率指标（DGS10/NASDAQCOM/SP500/VIXCLS/T10Y2Y/DCOILWTICO/DTWEXBGS/crypto_fear_greed/funding_rate）经 `align`（min_n=250）构成 29 个 job × 180 单元 = **5,220 单元**；云端只读 `dreambuddy_core.db` 实测 `gate_pass=1,057`（**20.25%**）、`p_adj` 2.03e-44～0.99961 |
| v1.51-2 | §14 状态机 / 幂等 | 同一快照以 `data_version=accept-20261115-r1/r2/r3` 模拟连续版本：三轮 `gate_pass` 完全一致（1,057），连续通过使 `stable=1,057`（`pass_streak=3`）、其余 `candidate=4,163`（`fail_streak=3`）；`decayed/retired` 只能由 stable 进入，符合契约；每轮内部复跑 `added=0`（同 `data_version` 命中 `get_eval` 短路，不重算、不推进 streak） |
| v1.51-3 | 方法层修复 | 验收发现 95/5,220 单元 `method_gate=failed`，根因为真实数据并列值使分位边界塌缩产生空桶、`b16_group_stats` 返回 `mean=None` → `b11_monotonic` `float(None)` 崩溃；修复 `methods/conditional.py` 过滤 `n>0 且 mean 非空`、非空桶 <2 显式报错（commit `2b5b8b8a59`），**failed 95 → 0**、`gate_pass` 1,028 → 1,057；补 2 例回归测试 |
| v1.51-4 | §14 保留项 / §17 | 未做：云端周期调度 timer、registry 保留/归档策略（每日 5,220 行 ≈190 万行/年）、S5 对外推荐；验收包 `acceptance_bundles/20261115_mers_real_data/`（报告 + repro 日志 + test 日志 + 三轮 summary + fix.diff）；54-L1 全量 **1,192 passed**、`method_audit --scope all` **392/392 PASS** |

### v1.50（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.50-1 | §2.5/§3 | **新增 D-A05 z-score 出口**：`capabilities/stats.py::zscore`，manifest 新增 D-A05（`metric_percentile` / `datacenter.percentile` / `[S26]` / `min_n: 30` / `method_binding: compute`）；能力层只做窗口切片与参数校验，统计量全部复用方法层 S26（winsorize p1/p99、`std=0 → z=None`）；`MIN_ZSCORE=30`、`MIN_ZSCORE_LOOKBACK=60`，零方差降级 `zero_variance` 不伪造 0 |
| v1.50-2 | 全局计数 | 可执行出口 51 → **52 个**，manifest 共 **52 条**；`stats.py` 编排函数 47 → **48 个**；TD §2.5 三处与母 SPEC 第 34 条同步 |
| v1.50-3 | §17/测试 | 新增 `tests/test_zscore.py`（6 passed：正常 z / 29 样本 empty / 零方差 / `lookback` 截断 / 日期轴不一致 / `run_capability` 调度）；`tests/test_capabilities.py` executor 白名单与 scenario 补 D-A05，**189 passed** |

### v1.49（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.49-1 | §3.5 | **新增模块「金融价尺系统」（FNS）**：独立子 SPEC [SPEC-54-金融价尺系统.md](./SPEC-54-金融价尺系统.md) **v1.2**（已按评审 v0.1 关闭 7 项阻断，待复审）。定位=把"社会必要劳动时间"做成可计算尺子（劳动含量 λ / MELT / Sraffa 标准商品 / 成本锚 / SNLT-II 实现缺口），用于劳动小时计价、价值偏离与均值回归、通胀二分解 `dlnP = dlnMELT + dlnλ`、劳动尺度真实利率；**新增第四轴「资金流尺」作交叉验证**（方向/速度/速率/滞后弹性 β，ADR-F9 只验证不定义） |
| v1.49-2 | 全局 | 方法编号新增 **V 组**（`V01–V23`）、能力编号新增 **D-V 组**（`D-V01–D-V07`）；`D-K` 已属评估层（MERS/Discovery）不得复用。**落地前置**：`methods/registry.py` 的 `GROUP_CAPACITY` 增 `"V": 23`（唯一跨模块改动） |
| v1.49-3 | 数据前置 | 需 18 侧补 9 条季频数据：`OPHNFB`/`COMPNFB`/`ULCNFB`/`HOANBS`/`GDPC1`/`PRS85006173`/`A460RC1Q027SBEA`（VA_nfb，待核验）/存货销售比/平均利润率 `r̄`（利润总额÷固定资本净存量）；年度 BEA 投入产出表离线导入（V3 阶段）。当前 54 内**无任一 V 方法实现**，状态=SPEC v1.2 待复审 |

### v1.47（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.47-1 | §十 Q6/§3.5.3 | **C11 节前效应落地（#32）**：`seasonal.py` 用 `@register("C11", ...)` 替换占位，`derive_holidays(ds)` 由日期轴「工作日缺失=节假日」派生（周末不计缺口，连续缺失 >`MAX_HOLIDAY_GAP_WEEKDAYS=10` 计入 `excluded_gaps` 并排除）；`c11_pre_holiday` 输出 `pre_mean/base_mean/diff/t/p/n_pre/n_base/n_holidays/excluded_gaps/calendar/lookback/pre_dates/n`；修复 `_diff_t` 在两组方差为 0 时 `df=0` 的除零崩溃（返回 `t/p=None`） |
| v1.47-2 | §3.5.3/§11.4 | **D-E04 扩展节前分支**：`event_study` 新增 `pre_holiday/holidays/lookback`，命中时走 `_pre_holiday_effect`（价格日期轴等长校验后 `ret_dates=price_dates[1:][-len(returns):]`）；无工作日缺口 FAIL-OPEN 为 empty，节前样本 <30 降级 `holiday_events_lt_30`，`params.calendar_source` 披露日历来源 |
| v1.47-3 | §3.5.3/§11.4 | **D-G25 尾部相关接线（#33）**：复用 `correlation_query`，executor `capabilities.stats.tail_dependence`，**复用 P13（R 组容量 18 已满，不新增方法 ID）**；下行尾按横截面均值收益 ≤q 切尾，上行尾取反面板复用同一方法，输出 `pairs{rho_down,rho_up,rho_full}/amplification/strongest_pair/n_tail/n`；对齐样本 <60 empty，尾部共现 <30 降级 `tail_events_lt_30` |
| v1.47-4 | §3.5.3/§11.4 | **D-J05 周期/频谱接线（#34）**：新增 `cycle_query` 意图，executor `capabilities.stats.cycle_spectrum`，T25/T26/C14 并列；输出 `period/cycles/span_days/reference_days/period_to_reference/power_ratio/month_consistency`；`min_span_days=2920`（2×1,460），跨度不足或 `cycles<2` 降级 `cycles_lt_2`，缺日期轴降级 `dates_missing` |
| v1.47-5 | §17/测试 | manifest 扩至 **50 条**可执行出口；新增 C11 三例（日期轴派生、显式 holidays + 长缺口守卫、无缺口空效应）、D-E04 节前两例、D-G25 两例、D-J05 三例，并纳入 executor 唯一性、ID 集合、JSON Schema 与真实执行覆盖矩阵；改写在 C11 实现后失效的三处占位测试；全量 pytest 通过、`audit()` 243/243 PASS、ruff/black 通过 |
| v1.47-6 | 云端实测 | 云端 43.160.201.117 只读 `dreambuddy_core.db`（`close_1d` 20 资产 / 54,653 行）：**D-J05** BTC/ETH 3,377 天 → 主周期 1,125.7 天、`cycles=3.0`、`period_to_reference=0.77`、`power_ratio` 0.322/0.360，BNB 3,296 天 → 1,098.7 天，SOL 2,287 天 <2,920 → `partial + cycles_lt_2`；**D-G25** 6 资产对齐 3,116 天 / 尾部共现 624 天，最强对 BTC\|ETH（`rho_down=0.070` vs `rho_full=0.004`），切尾样本存在机械负相关故只作同期描述；**D-E04 节前** BTC 无工作日缺口 → `empty`（明示不适用），`us_NASDAQCOM_value` 202 点被 250 点门禁拦截 → `empty`。结论：#32 代码与出口已闭环，**节前效应量的正向实测仍缺 ≥250 个交易日的美股日线**（云端 FRED 仅存 latest + `obs_count`，未落逐日观测），已在 TD §6.4.4 标注为 18 侧数据前置 |

### v1.46（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.46-1 | §十 Q6/§3.5.3 | **二维状态降级口径决策**：D-E14 传 `factor2` 时按每格非重叠 ≥250（按 PIT 预热 250 日后的可用样本计）做档位阶梯 4×4=A → 3×3=B → 2×2=D；三档均不达标不出二维结论，`dim=1` + `degraded_reason=insufficient_2d` 回退一维（一维仍按 4→2 桶降级）；4×4 契约不变，样本到量自动升档，不新增能力 ID/意图 |
| v1.46-2 | §3.5.3/§11.4 | R02 扩展二维：`data` 支持 `indicator2/factor2/x2` + `label2`，两轴各自 PIT 滚动分位后笛卡尔积（`cell = axis1 * buckets + axis2`），`by_horizon[].by_cell` 逐格输出 `effective_n/nonoverlap_n/mean/median/p10/p90/win_rate/t/p`；二维强制 `pit=True`；`_r02_rolling_state` 在无 `release_ts` 时走切片快路径（结果等价，避免 O(n²) 过滤） |
| v1.46-3 | §17/测试 | 能力层新增 `factor2/name2/buckets_per_axis`，返回 `dim/tier/requested_tier/degraded_tier/requested_buckets_per_axis/buckets_per_axis/cells/min_cell_nonoverlap_n/tier_attempts`，答案句显式披露 Tier 与每格非重叠下限；新增 5 例（Tier A/B/D、低于 2×2 回退一维、`factor2` 长度不一致 FAIL-OPEN），全量 pytest + `ruff check` + `python3 -m black --line-length 100` 通过 |
| v1.46-4 | 数据实测 | 云端真实数据（20日动量×20日波动率）：BTC 3,357 根 → A/B/D 档最小格 110/223/682；UNI 2,230 → 43/105/412；APT 1,468 → 38/81/265，三者均落 Tier D（2×2）。联合分桶聚集使 3×3 当前 0 资产达标，4×4 契约保留、样本增长后自动升档；OKX 现货 `listTime=2021-01-29`，否决 pre-2017 扩样，跨 venue 拼接仍需口径评审 |

### v1.43（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.43-1 | §3.5.3/§11.4 | D-G09 波动率目标换算能力接线（`metric_derived`，deterministic，`min_n=60`，data_scope `market.candles`）：价格转日简单收益（数据整形）后由 P02 计算窗口实现年化波动与 `scale = target_vol / realized_vol`；输出 `scale/target_vol/realized_vol/window/periods/returns_n/sample_n`；`window` 超长降级 `window_truncated`，零波动降级 `zero_volatility`；可执行出口 43→44 |
| v1.43-2 | §17/测试 | 新增 4 例：完整信封（119 个收益、scale×realized≈target）、与 P02 逐项相等（扁平 `{sym: returns}`）、零波动与窗口截断双降级、6 类非法输入 FAIL-OPEN；纳入 ID 集合、executor 白名单、JSON Schema 与真实执行覆盖；`pytest tests --ignore=tests/test_paper_replay.py` → **1060 passed / 0 failed**；本次修改文件 ruff 通过 |

### v1.42（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.42-1 | §3.5.3/§11.4 | D-G08 12-1 动量能力接线（`metric_derived`，deterministic，`min_n=60`，data_scope `market.candles`）：能力层只按 `skip`/`lookback` 切片（数据整形），F14 在切片上真实执行动量/波动/风险调整动量；输出 `momentum_12_1/lookback/skip/vol/risk_adjusted/window_start_ts/window_end_ts/truncated/sample_n`；历史不足 `lookback+skip+1` 截断 lookback 并降级 `short_history`，窗口起点非正降级 `base_zero`；可执行出口 42→43 |
| v1.42-2 | §17/测试 | 新增 4 例：280 点完整信封（窗口 253 点、起止日期对齐）、与 F14 逐项相等、120 点降级 `short_history`（lookback 截断为 98）、样本 <60 / lookback<2 / skip<0 / 非整数参数 / 日期长度不一致 / 含 None FAIL-OPEN；纳入 ID 集合、executor 白名单、JSON Schema 与真实执行覆盖；`pytest tests --ignore=tests/test_paper_replay.py` → **1027 passed / 0 failed**；本次修改文件 ruff check / ruff format 通过；20 日 `ts_rank` 属 D-G07 未随本能力接线 |

### v1.41（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.41-1 | §3.5.3/§11.4 | D-B09 距 ATH 回撤能力接线（复用 `technical_indicator`，deterministic，`min_n=250`，data_scope `market.candles`）：thin wrapper 复用 D-E10 `drawdown` 执行器（D20/D21），调度层显式注入 `capability_id=D-B09`；在既有 block 上补别名 `drawdown_from_ath/ath/ath_ts` = `current_drawdown/peak_price/peak_ts`；样本 <250 降级 `insufficient_samples` 并在 answer 明示，未提供 `dates` 时 `ath_ts=None` 不崩溃；可执行出口 41→42 |
| v1.41-2 | §17/测试 | 新增 4 例：300 点完整信封（`drawdown_from_ath≈0.25`、`ath=150`）、与 D20/D21 逐项相等、100 点降级 `insufficient_samples` 但保留结果、样本 <2 / 含 None / dates 长度不足 FAIL-OPEN；纳入 ID 集合、executor 白名单、JSON Schema 与真实执行覆盖；`pytest tests --ignore=tests/test_paper_replay.py` → **993 passed / 0 failed**（能力模块 169 passed）；本次修改文件 ruff check / ruff format 通过 |

### v1.40（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.40-1 | §3.5.3/§11.4 | D-B08 趋势斜率能力接线（新增 `technical_indicator` 意图，deterministic，`min_n=60`，data_scope `market.candles`）：取最近 `window` 期（默认 90、下限 30）子序列，T08 输出对数价格 OLS 斜率/R²，T09 输出名义 t/p；输出 `slope/r2/window/t/p/hac_corrected/sample_n`，显式 `hac_corrected=false`；样本 <60 降级 `short_window` 但保留结果；可执行出口 40→41 |
| v1.40-2 | §17/测试 | 新增 4 例：120 点完整信封（窗口截取 90 点、slope≈0.002、r2=1）、与 T08/T09 逐项相等、45 点降级 `short_window` 但保留结果、样本 <30 / window<30 / 非整数 window / 日期长度不一致 / 含 None FAIL-OPEN；纳入 JSON Schema 与真实执行覆盖；`pytest tests --ignore=tests/test_paper_replay.py` → **989 passed / 0 failed**（能力模块 165 passed）；本次修改文件 ruff check / ruff format 通过 |

### v1.39（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.39-1 | §3.5.3/§11.4 | D-A16 稳定币规模增速能力接线（复用 `metric_series`，deterministic，`min_n=30`）：S16 逐窗口真实执行 `x_t/x_{t-w}-1` 并折算百分比，`windows` 可配（默认 7/30），输出 `growth_{k}d/windows/sample_n`；样本 <30 降级 `insufficient_samples` 但保留结果，窗口超历史降级 `short_history`，基期 0 降级 `base_zero` 并将该窗口置 None，全部窗口不可算为 empty；可执行出口 39→40 |
| v1.39-2 | §17/测试 | 新增 4 例：40 点完整信封（与 S16 逐项相等）、自定义窗口一致、20 点降级 `insufficient_samples` / 10 点 30d 窗口降级 `short_history` / 基期 0 降级 `base_zero`、样本不足以覆盖任何窗口/window=0/非整数/空 windows/日期长度不一致/含 None FAIL-OPEN；纳入 JSON Schema 与真实执行覆盖；`pytest tests --ignore=tests/test_paper_replay.py` → **985 passed / 0 failed**；本次修改文件 ruff check / ruff format 通过 |

### v1.38（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.38-1 | §3.5.3/§11.4 | D-A15 ETF 净流入滚动和能力接线（复用 `metric_series`，deterministic，`min_n=30`）：S20 真实执行滚动均值，能力层以「均值 × 窗口长度」算术还原滚动和，`windows` 可配（默认 7/30），输出 `sum_{k}d/windows/sample_n`；样本 <30 降级 `insufficient_samples` 但保留结果，窗口超历史降级 `short_history` 并将该窗口置 None，全部窗口不可算为 empty；可执行出口 38→39 |
| v1.38-2 | §17/测试 | 新增 4 例：40 点完整信封（`sum_7d/sum_30d` 等于末窗和）、与 S20 逐项相等（自定义窗口）、20 点降级 `insufficient_samples` / 10 点 30d 窗口降级 `short_history` 且该窗口 None、样本不足以覆盖任何窗口/window=0/非整数 window/空 windows/日期长度不一致/含 None FAIL-OPEN；纳入 JSON Schema 与真实执行覆盖；`pytest tests --ignore=tests/test_paper_replay.py` → **969 passed / 0 failed**（能力模块 157 passed）；本次修改文件 ruff check / ruff format 通过 |

### v1.37（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.37-1 | §3.5.3/§11.4 | D-A13 极端事件频率能力接线（复用 `metric_series`，deterministic，`min_n=30`）：S11 分位线性插值给阈值（`quantile` 默认 0.95）或调用方直接给定 `threshold`，能力层仅做 above/below/abs 三侧计数与 `days/n` 比率，输出 `days/ratio/threshold/side/quantile/sample_n`；样本 <30 且无阈值无法确定阈值即 empty，<30 且有阈值降级 `insufficient_samples`；可执行出口 37→38 |
| v1.37-2 | §17/测试 | 新增 4 例：100 点完整信封（S11 p95 阈值、`days==5`）、与 S11 分位逐项相等、25 点有阈值降级分支、5 类 FAIL-OPEN（含 None 值、非法 side、NaN 阈值、越界 quantile）；纳入 JSON Schema 与真实执行覆盖；`pytest tests --ignore=tests/test_paper_replay.py` → **965 passed / 0 failed**（能力模块 153 passed）；本次修改文件 ruff check / ruff format 通过 |

### v1.36（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.36-1 | §3.5.3/§11.4 | D-A12 领先滞后相关能力接线（复用 `correlation_query`，deterministic，`min_n=120`）：M11 输出 lag −max_lag…+max_lag（默认 10）的相关/p/BH-FDR q/显著性，M12 输出最优 lag，能力层组装 `corr_by_lag[]`/`best_lag/best_corr/best_p_adj`；有效配对 <120 降级 `insufficient_history` 但保留结果；可执行出口 36→37 |
| v1.36-2 | §17/测试 | 新增 4 例：150 点完整信封（21 个 lag、`best_corr==1.0`）、与 M11/M12 逐项相等、100 点降级分支、5 类 FAIL-OPEN；纳入 JSON Schema 与真实执行覆盖；`pytest tests --ignore=tests/test_paper_replay.py` → **961 passed / 0 failed**（能力模块 149 passed）；本次修改文件 ruff check / ruff format 通过 |

### v1.35（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.35-1 | §3.5.3/§11.4 | D-A11 双序列滚动相关能力接线（复用 `correlation_query`，deterministic，`min_n=60`）：paired complete-case 后由 M04 计算窗口相关，输出 `corr/mean_r/window/n_windows/sample_n`；有效配对 <60 降级 `insufficient_samples` 但保留结果，配对 <2、`window<2` 或超样本、日期长度不一致为 empty；可执行出口 35→36 |
| v1.35-2 | §17/测试 | 新增 4 例：90 点完整信封（`corr==1.0`、`n_windows==61`）、与方法层 M04 逐项相等、40 点降级分支、5 类 FAIL-OPEN；纳入 JSON Schema 与真实执行覆盖；`pytest tests --ignore=tests/test_paper_replay.py` → **957 passed / 0 failed**（能力模块 145 passed）；本次修改文件 ruff check / ruff format 通过 |

### v1.34（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.34-1 | §3.5.3/§11.4 | D-A10 实际利率能力接线（新增 `metric_derived`，deterministic，`min_n=13`）：`nominal`/`cpi` 必填等长，通胀由 S16（`k=period`，默认 12）真实执行并折算百分点，能力层只做差值组合，输出 `real_rate/nominal/inflation/base_ts/period/sample_n`；CPI 基期 0 降级 `inflation_unavailable`，历史 <2 周期降级 `short_history`，样本不足以覆盖 period/`period<1`/长度不一致/含无效值为 empty；可执行出口 34→35 |
| v1.34-2 | §17/测试 | 新增 4 例：36 期完整信封（`real_rate==nominal−inflation`、`base_ts=dates[-13]`、`align_method=period_offset`）、与方法层 S16 逐项相等、降级分支、5 类 FAIL-OPEN；纳入 JSON Schema 与真实执行覆盖；`pytest tests --ignore=tests/test_paper_replay.py` → **953 passed / 0 failed**（能力模块 141 passed）；本次修改文件 ruff check / ruff format 通过 |

### v1.33（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.33-1 | §3.5.3/§11.4 | D-A09 环比能力接线（复用 `metric_series`，deterministic，`min_n=2`）：S16 以固定 `k=1` 计算 `x_t/x_{t-1}-1`，输出 `mom/base_ts/sample_n`；基期为 0 降级 `mom_unavailable`，样本 <2/日期长度不一致/含无效值为 empty；可执行出口 33→34 |
| v1.33-2 | §17/测试 | 新增 4 例：36 期完整信封（`mom==round(v[-1]/v[-2]-1,6)`、`base_ts=dates[-2]`、`align_method=period_offset`）、与方法层 S16（k=1）逐项相等、基期 0 降级分支、3 类 FAIL-OPEN；纳入 JSON Schema 与真实执行覆盖；`pytest tests --ignore=tests/test_paper_replay.py` → **949 passed / 0 failed**（能力模块 137 passed）；本次修改文件 ruff check / ruff format 通过 |

### v1.32（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.32-1 | §3.5.3/§11.4 | D-A08 同比能力接线（复用 `metric_series`，deterministic，`min_n=13`）：S16 计算 `x_t/x_{t-period}-1`（`period` 默认 12），输出 `yoy/base_ts/period/sample_n`；历史 <2 个完整周期降级 `short_history`，基期为 0 降级 `yoy_unavailable`，样本 ≤period/`period<1`/日期长度不一致/含无效值为 empty；可执行出口 32→33 |
| v1.32-2 | §17/测试 | 新增 4 例：36 期完整信封（`yoy==round(v[-1]/v[-13]-1,6)`、`base_ts=dates[-13]`、`align_method=period_offset`）、与方法层 S16 逐项相等、双降级分支（short_history / yoy_unavailable）、4 类 FAIL-OPEN；纳入 JSON Schema 与真实执行覆盖；`pytest tests --ignore=tests/test_paper_replay.py` → **945 passed / 0 failed**（能力模块 133 passed）；本次修改文件 ruff check / ruff format 通过 |

### v1.31（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.31-1 | §3.5.3/§11.4 | D-A07 回撤能力接线（复用 `drawdown_query`，deterministic，`min_n=250`）：与 D-E10 共用 `capabilities.stats.drawdown`，由 `_EXECUTOR_INTENTS` 注入 `capability_id/intent`；D20/D21 真实执行，输出 `drawdown/peak_ts` 并保留 `mdd/current_drawdown/duration_days/drawdown_path`；`prices<2` 为 empty，样本 <250 期降级 `insufficient_samples`；可执行出口 31→32 |
| v1.31-2 | §17/测试 | 新增 4 例：300 点完整信封（`drawdown==round(1-price_last/max,6)`、`peak_ts` 对齐高点）、与 D-E10 同输入逐项相等（含 `drawdown_path`）、100 点降级、1 点/空序列 FAIL-OPEN；纳入 JSON Schema 与真实执行覆盖；`pytest tests --ignore=tests/test_paper_replay.py` → **941 passed / 0 failed**（能力模块 129 passed）；本次修改文件 ruff check / ruff format 通过 |

### v1.30（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.30-1 | §3.5.3/§11.4 | D-A06 年化波动率能力接线（复用 `metric_series`，deterministic，`min_n=30`）：F05 真实执行（日简单收益标准差 × √365），`window` 缺省全样本且指定时须 ≥30，输出 `volatility/mean_ret/window/sample_n`；有效样本 <60 期降级 `short_window`，样本 <30/`window<30`/日期长度不一致/含无效值为 empty；可执行出口 30→31 |
| v1.30-2 | §17/测试 | 新增 4 例：120 期窗口完整信封（`align_method=trailing_sample`、`span=[dates[-120],dates[-1]]`）、与方法层 F05 逐项相等、40 期窗口降级 `short_window`、4 类 FAIL-OPEN；纳入 JSON Schema 与真实执行覆盖；`pytest tests --ignore=tests/test_paper_replay.py` → **937 passed / 0 failed**（能力模块 125 passed）；本次修改文件 ruff check / ruff format 通过 |

### v1.29（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.29-1 | §3.5.3/§11.4 | D-A04 历史分位能力接线（复用 `metric_percentile`，deterministic，`min_n=30`）：S25 真实执行经验分位（`100×count(X≤x_last)/n`，无未来函数），`lookback` 缺省全样本且指定时须 ≥30，输出 `percentile/value/lookback/sample_n`；窗口 <60 期降级 `short_lookback`，lookback 超可用历史降级 `lookback_truncated`，样本 <30/非法 lookback/日期长度不一致/含无效值为 empty；可执行出口 29→30 |
| v1.29-2 | §17/测试 | 新增 4 例：60 期窗口完整信封（`align_method=trailing_sample`、`span=[dates[-60],dates[-1]]`）、与方法层 S25 逐项相等、短窗口与超长 lookback 双降级、4 类 FAIL-OPEN；纳入 JSON Schema 与真实执行覆盖；`pytest tests --ignore=tests/test_paper_replay.py` → **933 passed / 0 failed**（能力模块 121 passed）；本次修改文件 ruff check / ruff format 通过 |

### v1.28（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.28-1 | §3.5.3/§11.4 | D-A03 CAGR 能力接线（复用 `metric_series`，deterministic，`min_n=2`）：S19 真实执行输出 `cagr/years`，提供 `dates` 时按首末日期实际天数折算 `days`（缺省回退 `n−1`），能力层补充 `span/days`；折算跨度不足 1 年降级 `short_span`，非正首末价格/天数 ≤0/样本 <2 为 empty；可执行出口 28→29 |
| v1.28-2 | §17/测试 | 新增 CAGR 完整信封（含 `cagr==round(2^(365/730)−1,6)`、`years==2.0`、`days==730.0`）、与方法层 S19 逐项相等、短跨度降级、1 点/非正价格/日期长度不一致/无日期回退共 4 例，纳入 JSON Schema 与真实执行覆盖；`pytest tests --ignore=tests/test_paper_replay.py` → **929 passed / 0 failed**；本次修改文件 ruff check / ruff format 通过 |

### v1.27（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.27-1 | §3.5.3/§11.4 | D-A02 变化率能力接线（复用 `metric_series`，deterministic，`min_n=2`）：S15 绝对变化 + S16 变化率并列输出，`window` 默认 1；`window<1` 或样本不足以覆盖区间直接 empty；基期 0 时 `change_pct=None` 降级 `change_pct_unavailable` 并保留绝对变化；可执行出口 27→28 |
| v1.27-2 | §17/测试 | 新增区间变化完整信封、与方法层 S15/S16 逐项相等、基期 0 降级、1 点/window 越界/window=0/NaN 共 4 例，纳入 JSON Schema 与真实执行覆盖；`pytest tests --ignore=tests/test_paper_replay.py` → **925 passed / 0 failed**；本次修改文件 ruff check / ruff format 通过 |

### v1.26（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.26-1 | §3.5.3/§11.4 | D-A01 历史序列能力接线（复用 `metric_series`，deterministic，`min_n=30`）：单序列区间取点 + 日/周/月降采样（每区间取最后观测，同日重复取最后），输出 `points[]/span/unit`，当前历史分位由 S25 真实执行；缺失率 >20% 降级 `sparse_series`；能力层不重算统计量、不生成交易方向；可执行出口 26→27 |
| v1.26-2 | §17/测试 | 新增日频完整信封与 S25 分位、周/月降采样与同日去重、稀疏序列降级、29 点/长度不一致/非法 freq 共 4 例，纳入 JSON Schema 与真实执行覆盖；`pytest tests --ignore=tests/test_paper_replay.py` → **920 passed / 0 failed**；本次修改文件 ruff check / ruff format 通过 |

### v1.25（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.25-1 | §3.5.3/§11.4 | D-J30 PIT/release_ts 全局能力接线（复用 `metric_percentile`，deterministic，`min_n=250`）：SC90 校验「可用时间 ≤ 使用时间」+ R02 `pit=true` 逐时点滚动分位前瞻分布并列输出；`release_ts`/`used_ts` 缺省视为观测时刻，PIT 违规降级 partial 并披露前视风险，过滤后可见窗口不足不出前瞻分布；仅描述历史统计、不生成交易方向；可执行出口 25→26 |
| v1.25-2 | §17/测试 | 新增默认 PIT 通过完整信封、与方法层 SC90/R02 逐项相等、release_ts 滞后触发 `pit_violations` 且 R02 仍按 release_ts 过滤 / 滞后 60 天可见窗口不足、249 点/长度不一致/非法 buckets/非法 window 共 4 例，纳入 JSON Schema 与真实执行覆盖；`pytest tests` 全量 **913 passed / 0 failed**；本次修改文件 ruff check / ruff format 通过 |

### v1.24（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.24-1 | §3.5.3/§11.4 | D-G14 EWMA 波动/协方差出口接线（复用 `metric_series`，deterministic，`min_n=60`）：P07 EWMA 组合协方差（λ 默认 0.94/init_window 20/periods 365）+ T19 逐资产 EWMA 波动序列并列输出；多资产面板按原始行 complete-case，单资产仅走 T19 且不输出协方差；仅描述样本内风险结构、不生成交易方向；可执行出口 24→25 |
| v1.24-2 | §17/测试 | 新增多资产完整结果与信封、脏数据清洗后与 P07/T19 逐项相等、单资产仅 T19、59 点/空面板/非法 lam/非法 periods 共 4 例，纳入 JSON Schema 与真实执行覆盖；`pytest tests` 全量 **909 passed / 0 failed**；本次修改文件 ruff check / ruff format 通过 |

### v1.23（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.23-1 | §3.5.3/§11.4 | D-J24 相关网络与社区发现出口接线（复用 `metric_series`，deterministic，`min_n=60`）：M05 相关矩阵 → `|ρ|≥threshold` 无向邻接 → SC71 中心性 + SC72 Louvain 社区与模块度 + M21 相关距离层次聚类；仅描述同期相关关系、不生成交易方向；图规模低于方法门禁时 partial 降级；可执行出口 23→24 |
| v1.23-2 | §17/测试 | 新增 36 节点网络完整结果与信封、面板 complete-case 后与方法层逐项相等、59 点/空面板/非法 threshold/非法 k empty、图规模不足降级 partial 共 4 例，纳入 JSON Schema 与真实执行覆盖；`pytest tests` 全量退出码 0，按 v1.22 的 772 例加新增 4 例记为 **776 passed / 0 failed**；本次修改文件 ruff / black 通过 |

### v1.22（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.22-1 | §3.5.3/§11.4 | D-J22 PCA/SVD/因子分析出口接线（复用 `metric_series`，deterministic，`min_n=60`）：M19 相关阵 PCA、M20 载荷、SC31 sklearn PCA、SC32 SVD、SC33 因子分析真实执行；多变量面板按原始行 complete-case 共享数据矩阵，仅描述数据结构、不生成交易方向；聚类 M21/M22 仍属 D-J23；可执行出口 22→23 |
| v1.22-2 | §17/测试 | 新增五方法完整结果与信封、面板 complete-case 后与方法层逐项相等、59 点/空面板/单变量/非法 k empty 共 3 例，纳入 JSON Schema 与真实执行覆盖；顺带修正 D-E15 的 I37 声明与方法目录计数 238→243；`pytest tests` 全量退出码 0，按 v1.21 的 769 例加新增 3 例记为 **772 passed / 0 failed**；本次修改文件 ruff / black 通过 |

### v1.21（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.21-1 | §3.5.3/§11.4 | D-G20 分位组合与单调性检验出口接线（复用 `metric_series`，deterministic，`min_n=250`）：B16 输出分位组统计与最高减最低 spread，B11 检验组均值严格单调，Q04 输出分位序号与组均值 Spearman rho/p；factor/forward 按原始位置 complete-case，spread 仅为描述性统计、非策略收益；可执行出口 21→22 |
| v1.21-2 | §17/测试 | 新增三方法完整结果与信封、complete-case 后三方法结果逐项相等、249 点/空输入/非法 k empty 共 3 例，纳入 JSON Schema 与真实执行覆盖；`pytest tests` 全量退出码 0，按既有 766 例加新增 3 例记为 **769 passed / 0 failed**；本次修改的 `stats.py` 与 `test_capabilities.py` ruff / black 通过 |

### v1.20（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.20-1 | §3.5.3/§11.4 | D-G19 IC/ICIR/衰减表出口接线（复用 `metric_series`，deterministic，`min_n=250`）：B13/B14 与 Q01/Q02 输出 IC/RankIC/ICIR，Q03 输出因子 IC 衰减，可选 prices 执行 B15 价格动量重叠/非重叠衰减；Q03 收益轴首项补 0 并右移 forward，缺价格降级保留核心五方法结果；可执行出口 20→21 |
| v1.20-2 | §17/测试 | 新增六方法完整结果与 h=1 对齐、complete-case 后六方法结果逐项相等、缺价格 partial 与短样本/空输入 empty 共 3 例，纳入 JSON Schema 与真实执行覆盖；`pytest tests` 全量退出码 0，按既有 763 例加新增 3 例记为 **766 passed / 0 failed**；本次修改的 `stats.py` 与 `test_capabilities.py` ruff / black 通过 |

### v1.19（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.19-1 | §3.5.3/§11.4 | D-G16 组合 VaR/CVaR 出口接线（复用 `metric_series`，deterministic，`min_n=60`）：P09 参数法组合 VaR、P10 历史法组合 VaR/CVaR 与 D17/D18 逐资产历史 VaR/CVaR 并列输出；最小公共长度对齐，P10 有效分位同步给 D17/D18，权重归一化与统计计算复用方法层；可执行出口 19→20 |
| v1.19-2 | §17/测试 | 新增四方法结果与信封、方法层结果逐项相等及对齐、短样本/空面板 empty 共 3 例，纳入 JSON Schema 与真实执行覆盖；`pytest tests` 全量退出码 0，按既有 760 例加新增 3 例记为 **763 passed / 0 failed**；本次修改的 `stats.py` 与 `test_capabilities.py` ruff / black 通过 |

### v1.18（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.18-1 | §3.5.3/§11.4 | D-J02 季节强度与调整出口接线（复用 `seasonality_query`，deterministic，`min_n=60`，`min_span_days=1095`）：C13 月度 ANOVA 式强度、T10 robust STL 与 SC91 X-13 风格 STL 近似；完整日期轴同步过滤，不足 3 年降级 `partial + seasonality_depth_lt_3y`，原始分解组件与季节强度并列输出；可执行出口 18→19 |
| v1.18-2 | §17/测试 | 新增三方法结果与浅历史降级、59 点短样本 empty、缺日期轴 empty 共 3 例，纳入 JSON Schema 与真实执行覆盖；`pytest tests` 全量退出码 0，按既有 757 例加新增 3 例记为 **760 passed / 0 failed**；本次修改的 `stats.py` 与 `test_capabilities.py` ruff / black 通过 |

### v1.17（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.17-1 | §3.5.3/§11.4 | D-J04 变点检测出口接线（`change_point_query`，deterministic，`min_n=60`）：T22/SC49 两种 CUSUM、T23 近似 PELT、SC50 精确 PELT、SC51 Pettitt 原始结果与日期映射并列输出；SC47/SC48 明确排除，可执行出口 17→18 |
| v1.17-2 | §17/测试 | 新增阶跃序列五方法结果/日期映射与 59 点短样本 empty 共 2 例，纳入 JSON Schema 与真实执行覆盖；`pytest tests` 全量退出码 0，按既有 755 例加新增 2 例记为 **757 passed / 0 failed**；本次修改的 `stats.py` 与 `test_capabilities.py` ruff / black 通过 |

### v1.16（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.16-1 | §3.5.3/§11.4 | D-E07 纳入 B06 二维交叉表：输出 `state_t × state_{t+1}` 联合计数底表，B07 对同一状态轴行归一化为转移概率；manifest 方法绑定更新为 B02/B06/B07/B08/B09，可执行出口保持 17 个 |
| v1.16-2 | §17/测试 | 新增联合计数总数、相邻转移样本数及与 B07 逐行概率一致性测试；同步视觉基线和真实执行覆盖；`pytest tests` → **755 passed / 0 failed**，ruff / black 通过 |

### v1.15（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.15-1 | §3.5.3/§11.4 | D-G23 事件窗推断出口接线（`event_car_significance`，deterministic，`min_n=250`）：Q10 估计窗均值调整 CAR + Q11 Patell/BMP；与 D-E04 描述性事件研究分离，价格轴事件下标转为同日收盘收益下标；可执行出口 16→17 |
| v1.15-2 | §17/测试 | 新增 30 事件完整输出、<30 事件降级、Q11 不可用保留 CAR 共 3 例；纳入 JSON Schema 与真实执行覆盖；`pytest tests` → **754 passed / 0 failed**，ruff / black 通过 |

### v1.14（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.14-1 | §3.5.3/§11.4 | D-E14 一维相关状态条件分布出口接线（`conditional_distribution`，deterministic，`min_n=250`）：R02 PIT 状态轴共享 B05/B10/R01/R08，默认 h=1/2、4 桶，主期限不足降 2 桶，弱后续期限单独降级；h>1 不输出朴素 t/p。可执行出口 15→16（含既有 D-E15） |
| v1.14-2 | §17/测试 | R02 新增可选 `include_states`，B11/R08 新增可选 `prebinned`，默认口径不变；新增 4 个 D-E14 场景并纳入 JSON Schema 与真实执行覆盖；`pytest tests` → **751 passed / 0 failed**。二维 4×4 仍为独立阻塞项，不标记 T2 全部完成 |

### v1.13（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.13-1 | §3.5.3/§11.4 | D-E04 事件研究窗能力出口接线（`event_study`，deterministic，`min_n=250`，executor `capabilities.stats.event_study`）：事件日期经 `bisect_left` 对齐到价格轴（取首个不早于事件日的交易日），F19 事件窗 CAR + F23 事件后分布 + F21 末段 CAR；事件数 <30 降级 `partial` + `events_lt_30` 但保留 CAR/胜率（`_call_soft` 仅在方法层 `insufficient_samples` 时复用同一登记函数取小样本结果），价格 <250 或无有效事件时 FAIL-OPEN 为 empty |
| v1.13-2 | §3.5.3/§11.4 | D-E09 计数与共现能力出口接线（`metric_series`，deterministic，`min_n=3`，executor `capabilities.stats.count_series`）：`values` 走 R09 涨跌次数、`pairs` 走 B17 共现计数 + R10 一句文案（两方法均真实执行），对齐点 <3 FAIL-OPEN 为 empty；可执行出口 12→14 |
| v1.13-3 | §17/测试 | D-E04/D-E09 纳入 manifest 可运行性、JSON Schema 与真实执行覆盖校验（D-E09 场景补 `pairs` 分支）；`pytest tests` → 718 passed / 0 failed；同步修复 `test_l0_datacenter_series` 的硬编码日期时间炸弹（`NOW` 改滚动基准） |
| v1.13-4 | §3.5.3/§11.4 | 前端 cue 分派补齐：`exec_stat_query` 新增拥挤度→D-A14、显著性→D-G22；`l1_route_signal.py` 与 `src/lib/l1-intent-registry.ts` 的 `stat_query` 正则同步加入新 cue（显著性置于相关性之后，保留「相关性是否显著」走 D-E05），并补 jest 用例（19 例全绿） |

### v1.12（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.12-1 | §四/§11.4/§17 | 冻结 D-A14/F26 `level` 阈值为 **A 分位法**：取分值历史分布的 p20/p60/p80 划分 `<p20 极低 / p20–p60 低 / p60–p80 偏高 / ≥p80 高`，禁止改用固定等宽四档/五档；同时披露 `percentile/thresholds/window/as_of/sample_n`（`pit=false` 回顾口径）。样本低于方法 `min_n=60` 或分值分布极差≈0 时 `level=None` 并标记 `level_status`，不补兜底阈值 |
| v1.12-2 | §3.5.3/§11.4 | D-A14 能力出口接线（`metric_percentile`，deterministic，`min_n=60`，executor `capabilities.stats.crowding`）：复用 F26，`n<60` FAIL-OPEN 为 empty，方法层降级时 `partial` + `degraded_reason`；可执行出口 11→12 |

### v1.11（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.11-1 | §四/§11.5/§17.1.3 | 新增 D-G22 显著性出口（`significance_query`，deterministic，`min_n=250`）：Q06 Bartlett 核 HAC t + Q07 Deflated Sharpe，统计量只复用方法层；`n<250` 与 Q06 退化 FAIL-OPEN 为 empty，Q07 退化降级 partial 并保留 HAC t。h>1 重叠前瞻收益的「HAC 前置」由「未实现」改为「出口已具备」，S4 剩余阻塞收窄为扩样本与状态特征 |

### v1.10（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.10-1 | §四/§14 | 宏观事件历史回填通道就绪（FOMC/BLS，2015–2026 实测 542 条），D-E04/D-E09 的数据阻塞改为「待云端入库后接线」；日常 sync 的 DELETE 收窄到窗口内以保留历史行 |

### v1.9（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.9-1 | §3.5/§11/§17 | D-E12/R18 时空对齐切片交付，可执行出口 9→10；样本不足与空窗口显式降级，manifest 真实执行覆盖同步纳入 |
| v1.9-2 | §3.5.2/§11.4/§17.1.3 | 纠正 R02 未接线、矩阵 TopK/C18 未接等过期表述；D-A14/F26 固定权重分与 `level` 阈值阻塞分开登记 |

### v1.8（2026-11-15）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.8-1 | §四/§14/§17 | D-E05 矩阵 TopK、D-E11/C18、D-E01 与 MERS S3 内部内核交付；可执行出口增至 9 个，S5 对外推荐保持关闭 |

### v1.6（2026-11-14）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.7 | §3.5.3、§11.4、§17.1 | D-E02 三层接线（manifest `I30/R02` + `percentile_forward` + 前端 `exec_stat_query` 分位 cue 与 `dates` 传参），可执行出口 7→8；T0.5/A8 首版经 D-E02 交付（h=1 PIT，4→2 桶降级披露）；未接线清单移除 D-E02 |
| v1.6-1 | §3.5.2–§3.5.3、§11.4 | 新增 R02 PIT 双口径硬约束：T0.5/T2/MERS 只接受 `pit=true`（v1.6 时点尚未实现，v1.11 已在 `conditional.py` 落地）；明确 T0.5=S3→S4 的 blocker 与 7 个能力出口的子集边界 |
| v1.6-2 | §17.1、§17.1.3 | S2/S3 改为方法层完成、能力登记范围部分交付；补 `pit/as_of/effective_n/nonoverlap_n`、每桶非重叠门禁及 h>1 Newey-West/HAC 前置；整体进度与后续顺序统一指向 TECHNICAL_DESIGN §6 |
| v1.6-3 | METHOD_LIBRARY v1.9、延续性场景包 v1.3、TECHNICAL_DESIGN v2.6 | 同步 R02 方法口径、T0.5 场景依赖、103 项能力状态、四类关系榜单、三种周期口径与 S0–S7 路线映射；仅文档变更，不宣称新增代码能力 |

### v1.5（2026-11-14）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.5-1 | §11.4、METHOD_LIBRARY §16、TECHNICAL_DESIGN §2.2 | 日线 `ts` 归一到 UTC 日首并保留 `close_ts`；新增 `close_anchor/source_policy`，跨资产相关与领先滞后强制同锚点；记录 BTC–ETH 同期相关修复证据与 397 例测试基线 |

### v1.4（2026-11-14）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.4-1 | §11.4、能力层与 manifest | 回写 D-E03/E05/E06/E07/E08/E10/E11 共 7 个可执行出口、171 方法 audit 与统一 `CapabilityResult`；前端合并为 `stat_query`，同步双端意图注册与金标集 |

### v1.3（2026-11-14）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.3-1 | §3.5（新增） | 新增「四层分工：方法库 / 能力登记 / 场景包 / 评估层」，明确延续性统计分析（场景包 `D-E13`）与统计回测相关性（§14 MERS / §15 Discovery / S5 排名）在目标变量、范围、输出、数据门槛上的差异 |
| v1.3-2 | §3.5.2 / §3.5.3（新增） | 三条 SSoT 硬约束（前瞻收益唯一实现 `align.forward_returns`；IC 三处消费分工；能力登记不重复计数）+ T 阶段 ↔ S 级映射（T0=S3 自身延续性子集、T1b=S2 因子池、T2=S4、T3=S5） |
| v1.3-3 | §17.1.3 | 补「与场景包的关系」注：`D-E13` 是 S3 子集的已落地实现，不依赖 S2-p 回填；S2 相关性仍受因子池上限约束 |
| v1.3-4 | 技术文档 §2.4 | 登记 `D-E13`（✅ 已交付）/ `D-E14`（⬜），标注为场景编排不新增方法 ID；E 组硬前提由「价格仅 2 周」更新为「价格腿已闭环，瓶颈转为因子池纵深」 |
| v1.3-5 | 方法库 §0.1、§16 | 新增四层边界表与「已实现方法冻结口径」表（T13/T14/T20-21/F18/B07-08/T08-09/B13-15/R02），成为口径 SSoT |
| v1.3-6 | §17.1.3（新增）、`scripts/backfill_crypto_derivatives.py` | S2 缺口决策：OI 禁止跨所拼接（新增 Binance Vision `open_interest_value_binance` 1095 天）、清算永久 `not_collected`、OKX 180 天降为交叉验证；资金费率主链 Binance 1096 天、ETF Farside 730 天 |
| v1.3-7 | §17.1.3 验收表 | S2 回填验收：加密域 ≥250 天序列 26 条（门禁 ≥10 通过）；OI 180 天/清算 0 天为已登记缺口，不阻塞 S2 n≥60/120 相关性 |
| v1.3-8 | 技术文档 §0 / §2 / §3 / §6 | 总技术文档升级 v2.0：新增文档地图、六类问题能力地图（对齐/相关/周期/惯性/延续/单维→多维）、数据可行性矩阵、6 条治理规则；能力登记修正（101 项）、`D-B00` 改 1D/1W/1M 日频派生、`D-E03` 标注月度季节性数据不足、`datacenter.series`/`market.candles` 改 ✅ |
| v1.3-9 | §1.1 / §11.3 / 方法库 §14/§15 | 消除过期事实：删除「价格仅约 2 周 / `bitcoin.current_price_usd` 51 点」，改为价格腿已闭环；龙头由「14 已绑 / 15 未采集」改为「28 已绑定 + 1 诚实登记（JP225）」；新增 S0–S6 / S1–S5 / T0–T4 三套编号映射，规定跨文档引用必须成对出现 |
| v1.3-10 | 技术文档 §0.5 / §2.7（新增 §0.5） | 总技术文档升级 v2.1：新增 §0.5「四层分工与边界」（四层载体表 + 场景包 vs 评估层对比表 + 6 条边界纪律），使四层关系在总技术文档内自洽、不依赖跳转本文 §3.5；§2.7 K 组标注为第④层评估层只读出口 |

### v1.2（2026-11-14）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.2-1 | §17.1.3 | 新增「数据纵深实测与顺序修正」：价格腿已满足（1,094 日/3 年），真实瓶颈为加密域指标仅 14–44 天、专用表 0 行；相关性前插入 `market.candles` + 对齐层，排名后置为 S3/S4 下游 |
| v1.2-2 | §17.1 第 4 条、§17.1 表 S2 行 | 增补第四处修正；S2 依赖追加「跨资产历史回填（≥60 对齐点）」，门禁追加 `n≥60/120` 与 `align_method` |
| v1.2-3 | 方法库 §14、§15、§0 | §14 由 P1a/P1b/P2a/P2b 重排为 S0–S6（按样本量门禁）；§15 修正「价格仅约 2 周」过期事实并补实测；§0 标注 `market.candles` 为 S1 新增 scope |
| v1.2-4 | §17.1.3、§17.1 表 S2-p | 跨资产分类与 40 层 `asset_classes.py` 统一（SSoT=40）；新增 `l1agg/leader_registry.py` 绑定 14 龙头 + 诚实登记 15 未采集；`align.load_leader()` 对未采集抛 `not_collected`；S2-p 由「加密域回填」扩为「跨资产回填」 |
| v1.2-5 | §17.1.3 覆盖表、§17.1 表 S2-p | 跨资产回填落地：新增 `scripts/backfill_cross_asset_leaders.py`（Nasdaq 个股/ETF + OKX 金属 + FRED 能源，幂等），云端回填 14 条序列 8,065 点；`coverage_summary` 28 available / 1 not_collected（JP225 历史不足）；DJIA 用 DIA 代理 |

### v1.1（2026-11-14）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.1-1 | §17.1、§17.1.0 | 落地路线改为 S1–S5 五级能力路线；新增 S1.0 硬前置（索引迁移 / 资产池 / 价格回填 ≥3 年 / 覆盖体检）及其验收 |
| v1.1-2 | §11.3、§16.3 | S4 更名「条件外推表达」：`predict_snapshot` → `conditional_outlook`，只输出模型输出 + 历史同状态分布，禁止点预测；新增 B6 MERS 分阶段开关 |
| v1.1-3 | §14.1 | MERS 分两阶段交付：S3 仅内部计算内核（`MERS_EXTERNAL_RECOMMEND=false`），S5 才开放对外推荐 |
| v1.1-4 | §17.1.1 | 新增逐级推进纪律：先过门禁再进下一级；每级补 golden 用例；每级产出三段报告；单级可回滚 |

### v1.0（2026-11-14）

| 编号 | 位置 | 内容 |
|---|---|---|
| v1.0-1 | §13 | 方法总目录：5 套资产（238 + 57 + 92 + 18 + 99 项能力）分类汇总，确立「全部保留 + 四条调用纪律」 |
| v1.0-2 | §14 | 新增 MERS 周期性关系评估与推荐系统：预注册网格、RankIC 主排序、5 项门禁、状态机、注册表 schema、L1 消费协议 |
| v1.0-3 | §15 | 新增 Discovery 探索发现模式：≤5000 单元预注册空间、六步流程、manifest 可复现、候选不得直接进 L1 |
| v1.0-4 | §16 | 本轮评审：MERS 4.3 / Discovery 3.9，8 项风险对策，B1–B5 阻断项，结论「有条件通过」 |
| v1.0-5 | §17 | 完整落地路线 P0–P3 与 5 条建议（先回填价格、窄网格、隔离 Discovery、负样本验收、回退默认化） |
| v1.0-6 | 方法库 §12、技术文档 §2.7 | 新增意图 `relationship_recommend` / `discovery_query`；新增 K 组能力登记 2 项 |

### v0.2（2026-11-14）

| 评审编号 | 修订位置 | 修订内容 |
|---|---|---|
| R1 / B1 | §1.1 表、ADR-7、§7-P1.8、§5.5 | 明确前端 `timeseries` 硬编码于 `route.ts:69`；只切前端来源、不删除 9 的 `generate_timeseries`；新增 `FUNDAMENTAL_TIMESERIES_SOURCE` 开关 |
| R2 / B2 | ADR-5、§5.4 | 补「指标别名 + 查询类型词 + 非文档意图」三条件、固定 fallback 顺序、负样本 ≥10 条 |
| R3 / B3 | §5.1、§6、§7-P0 | 补 `max_days`、`sub_category` 白名单/字符校验、索引迁移、P95 实测方法与 `EXPLAIN QUERY PLAN` 留档 |
| R4 / B4 | §5.1、§5.2、§5.3 | `quality`/`answer` 统一顶层，`data` 仅业务字段，契约指向 `contracts/capability_result.schema.json` |
| R5 / B5 | §6 | 离群只标记不删除（winsorize 仅用于 z-score）、`cagr` 适用范围、波动率统一定义 |
| R6 / I1–I6、O1–O3 | §3.2、§4.1、§5.5、§10 | 补 `reports/` 目录、calendar 的 predict 归位、前端 `unit/data_quality/reason`、别名表路径 |
| 新增 | §11 | 补全确定性数据能力全景（库内衍生 / 技术指标 / 模型输出 / 排除项 / scope-意图映射） |
| 新增 | `docs/TECHNICAL_DESIGN.md` | 建立「数据维度能力」正式登记册：A 组 16 项 + B 组 10 项 + C 组 6 项 = 32 项，含能力 ID/依赖/字段/意图/优先级/状态，作为唯一登记事实源 |
| 新增 | `docs/TECHNICAL_DESIGN.md` §2.4、`docs/METHOD_LIBRARY.md` | 新增 E 组「统计关系与价格表达」12 项（D-E01–D-E12）；建立方法库 238 方法 / 18 关系原语 / 意图→方法路由 / 固定输出模板；确认 P1 增 `market.candles`+`technical_indicator`+季节性，P2 增相关性与跨维自动组合 |
| 新增 | `docs/TECHNICAL_DESIGN.md` §2.5、`docs/RESEARCH-INSTITUTIONAL-L1-METHODS.md` | 新增 G 组「机构统计方法」25 项（D-G01–D-G25）：横截面统计/WorldQuant 算子/风险分解/研究检验协议；确立固定参数惯例与 D1/D2/D3 分级，方法库扩至约 290 |
| 新增 | `docs/TECHNICAL_DESIGN.md` §2.6、`docs/RESEARCH-SCIENTIFIC-METHODS.md` | 新增 J 组「科研统计方法」30 项（D-J01–D-J30）+ SC01–SC92 方法族（推断/回归诊断/实验设计/降维/信号/变点趋势/信息论/极值/空间网络/生存/meta/数据质量/季节调整）；方法库扩至约 370，能力登记 99 项 |

