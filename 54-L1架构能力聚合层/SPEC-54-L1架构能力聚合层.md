# SPEC-54 L1 架构能力聚合层

- **版本**: v1.1 ｜ **日期**: 2026-11-14 ｜ **状态**: 🟢 完整版（v1.0 + S1–S5 五级能力路线 + S1.0 硬前置 + S4 条件外推收口 + MERS 分阶段，见 §13–§17）
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
| 19 DAL | 7 域 21 表；`mm_metrics(sub_category, metric_name, timestamp, metric_value)` 实测 **348,543 行 / 5,304 sub_category / 455 指标**，`DGS10` 回溯至 1962、`NASDAQCOM` 1971、`crypto_fear_greed` 2018 起日频 4,066 条 | `19-数据访问层/docs/SCHEMA_DESIGN.md`、`sqlite3 只读实测` |
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
| `metric_series` | 指标词 + 时间范围词（近一年/近 30 天/历史走势/变化率） | `exec_metric_series` | deterministic |
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
- fallback 顺序固定：`doc_search → event_line_query → metric_* → data_query / price_query`
- `deterministic` 不等于免校验：仍需参数完整性与数据质量校验，校验失败走 L2
- golden set 必须新增**负样本 ≥10 条**（例：「CPI 文档在哪」→`doc_search`；「CPI 什么时候发布」→`calendar`；「CPI 和 BTC 有关系吗」→`cross_check`）

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
| 拥挤度（分位 + 变化率合成） | 资金费率 + 多空比 + 未平仓 | 中 | ⬜ |
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

**P1 硬前置（新增）**：E 组与 B 组月度/季节性统计依赖「日频价格历史 ≥3 年」。实测库内价格仅约 2 周（`bitcoin.current_price_usd` 51 点），必须先回填 OKX `history-candles` 或 CoinGecko chart；否则相关能力一律返回 `insufficient_history`。

**方法选择**：全部由 [docs/METHOD_LIBRARY.md](docs/METHOD_LIBRARY.md) 的意图→方法路由表驱动（238 方法 / 18 关系原语），L1 只做「选法 + 套模板」，不做推理。

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

**评估结论：顺序合理，附和「数据 → 关系 → 元方法」的依赖链，且每级都有用户可见产出。需三处修正**：

1. **S1 必须同时覆盖「过去」**：只做「现在」可查，S2/S3 无数据可用 → 价格回填与资产池定义并入 S1 的前置（S1.0）。
2. **S4 改名「条件外推表达」**：不做点预测。只允许「当前状态 → 历史同状态的前瞻分布 + 区间」，或暴露既有模型输出（标 `model_output`）；禁止「将会/预计点位」。
3. **S5 的 MERS 提前做内部窄版**：S3 需要「哪个方法与该指标关系最强」来选法，因此 MERS 的计算内核在 S3 就要具备（仅内部使用、不对外推荐）；对外推荐与 Discovery 留在 S5。

### 17.1.0 S1.0 硬前置（整条路线唯一阻断项，必须先完成）

| # | 任务 | 产出 | 验收 |
|---|---|---|---|
| 1 | `mm_metrics` 索引迁移 | `(sub_category, metric_name, timestamp)` 复合索引 | `EXPLAIN QUERY PLAN` 走索引；区间查询 P95≤300ms ✅ 2026-11-14（本地 p95 0.78ms；云端索引已存在） |
| 2 | 资产池定稿 | `config/asset_pool.yaml`：BTC/ETH/SOL + 纳指(IXIC)/标普(SPX)/黄金(XAU)/原油(WTI)/美债(US10Y) | 8 个资产各有 `instrument/storage/timezone`；类别龙头唯一；`python3 -m l1agg.asset_pool` 校验通过 ✅ 2026-11-14 |
| 3 | 价格历史回填 | OKX `history-candles` 日频 ≥3 年（缺失回退 CoinGecko chart） | 每资产 ≥1,090 条（3 年日历日 1095/1096 闰年浮动）；缺口率 <1% ✅ 2026-11-14 云端执行：BTC/ETH/SOL/XAU 各 1,094 条 × `close_usd`/`volume_usd`，跨度 2023-11-15~2026-11-12，缺口 0 |
| 4 | 覆盖体检报告 | `reports/coverage/<date>.md`：每个 metric 的 n / 起止 / 缺失率 / 异常值标记 | 报告生成且 metric 清单与 DAL 一致 |

> 四项全部通过才可进入 S1；任一项失败则 S2/S3 不得启动（相关性、条件收益都会因样本不足而产生假规律）。

| 级 | 能力 | 交付物（用户可见） | 依赖 | 验收门禁 |
|---|---|---|---|---|
| **S1** | 前端各模块数据可查（现在 + 过去） | 11 个基本面模块全部字段可查；每模块真实 `timeseries`（30/90/365 天）；行情/宏观/链上/情绪/资金 实时与历史同入口 | 索引迁移；`datacenter.series`；价格回填 ≥3 年（S1.0） | 每模块 ≥3 个自然语言查询命中 L1；`timeseries` 非空且 `sample_n` 正确；P95≤800ms |
| **S2** | 多维数据相关性组合 | 相关矩阵 TopK、领先滞后、滚动相关、同向率、固定权重合成指标；「哪些资产相关性最高」可直答 | S1 + 统一资产池（8 资产） | 输出带 `n/p/window`；随机序列相关系数≈0 且不显著；合成指标权重固定可复现 |
| **S3** | 高相关数据与价格的统计关系 | 条件收益、分位→前瞻分布、分箱单调性、日历效应、回撤画像（R01/R02/R03/R08/R11） | S2 + MERS 计算内核（内部） | 每关系输出 `n/win_rate/mean/p_adj/单调性`；随机数据无显著；方法选择可追溯 `method_id` |
| **S4** | 过去 + 现在的条件外推表达（非点预测） | 「当前处于 X 状态，历史同状态后 h 日分布：均值/中位/胜率/区间」；既有模型输出（bdsm/bcrm2/event）gated 暴露 | S3 | 必须含区间与样本量；无模型输出时降级为纯历史分布；禁止点预测措辞（抽检 20 条） |
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

### 17.2 与 L1 的关系（重申）

MERS 与 Discovery 只改变「**选哪个方法**」，不改变「**输出什么**」——L1 输出永远是「方法 + 样本量 + 统计量 + 历史事实 + caveat」。

### 17.3 建议（5 条）

1. **先回填价格，再谈推荐**：没有 ≥3 年日频价格，MERS 就是无本之木；建议把回填作为 P1 第 0 项。
2. **MERS 先做窄网格**：首期只 10 方法 × 3 期限 × 8 资产，跑满 8 周再扩；一次性铺 370 方法会导致运维与解释成本失控。
3. **Discovery 单独隔离**：独立目录、独立预算、独立报告，禁止与 MERS 共享状态，避免污染推荐。
4. **上线前做两次负样本验收**：随机序列 + 打乱标签，`stable`/`findings` 必须为 0，这是唯一能证明防过拟合的硬证据。
5. **把 `recommend_method` 的回退路径做成默认行为**：注册表缺失/过期/未通过门禁时，静默回落到方法库默认顺序，保证 L1 永不因推荐系统故障而不可用。

---

## §十二、修订记录（v0.1 → v1.1）

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

