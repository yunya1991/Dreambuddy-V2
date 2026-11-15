# SPEC-54 L1 交易层（L1 Trading Layer）

- **版本**: v0.10（B 链路最小闭环打通：编排 `visual_overview.py` 一次进程产 8 面板 + `lights`、`LightsView` 五态渲染、LTL-12 manifest/`_EXECUTORS` 登记；P1-2 批量回放、P0-5 D-E18、P0-4 D-E19、P0-3 聚合曲线/类别看板、P0-2 图表权重、P0-1 资产池 v2、P0-0 方法基座已落地）
- **日期**: 2026-11-15
- **状态**: 🟢 有条件通过（[评审报告](./SPEC评审报告-L1交易层-v0.1.md) 3.30/5；B-LT1…B-LT12 本版全部关闭，按评审 §6 复审判据逐条验收）
- **上游**: `SPEC-54-L1架构能力聚合层.md`（ADR-3/6 只做确定性计算）、`SPEC-54-统计图表化能力.md` v0.22（ADR-V1…V20 / V-G / V-AC / **§4.12 美联储方法 10 条** / §4.14 I35–I39）、`config/asset_pool.yaml` v2、`l1agg/leader_registry.py`、`config/direction_rule.yaml`（`dr-1.1.0`）、`config/weights.yaml`、`l1agg/methods/fed_methods.py`
- **下游**: `l1agg/capabilities/visual.py`、`l1agg/trading/`、`3.1-FRONTEND/src/components/visual/`、`33-REA`/`48-涌现`（T4 反思消费者）、`22-执行引擎中心`（唯一执行方，L1 不下单）

> **一句话**：把「五类龙头资产 → 表格 → 曲线（含聚合加权）→ 资金流向导图 → 信号点亮 → 纸面执行 → 复盘 → 反思进化树 → 优化图表统计」接成一条**确定性可回放**的闭环；L1 只产图与信号，不持有下单客户端。

---

## §1 两个维度（用户 2026-11-15 定调）

| 维度 | 内容 | 交付物 | 代码主体 |
|---|---|---|---|
| **A 交易链路执行闭环** | 资产池 → 数据契约 → 图表 → 信号 → 交接 22 → 复盘 → 反思进化 → 优化反馈 | `signal` 历史 + `comparison` 打分 + 制品 | `l1agg/trading/*` |
| **B 前端展示层图表** | 按类别龙头资产的数据统计 / 处理 / 图表展示 / **信号点亮**（多维权重统计下的趋势延续、惯性、周期、前瞻触发） | `data.visual` + `lights` JSON | `l1agg/capabilities/visual.py` + `3.1-FRONTEND` |

两个维度**共用同一套统计事实**（L1-S），不允许前端二次计算，也不允许交易链路另算一套（ADR-V5 / ADR-V13）。

### 1.1 七段链路与图种映射

| # | 用户口径 | 层 | 图种 | 现有落点 | 缺口 |
|---|---|---|---|---|---|
| 1 | 表格 | T1 | `table` | `D-E12` 对齐切片 8 列 | 缺「按类别分组 + 组内龙头排序」看板（D-E17） |
| 2 | 曲线图 | T2 | `series` | `D-E10` 回撤 / `D-E15` 价格+EMA26 | 缺**多序列加权合成一条聚合曲线**（D-E16） |
| 3 | 资金流向导图 | T3 | `graph`（+`tree` 总览） | `D-E05` 相关网络 `graph`、`overview` tree | 缺 `flow` 边语义（ETF 资金流已入库但未成图，D-E18） |
| 4 | 交易信号 | 点亮 | `signals[]` | `direction_rule` 四轴（internal） | 缺**公开层轴级点亮投影**（D-E19） |
| 5 | 复盘记录 | — | `table` | `comparison` 三重障碍打分 | 缺多资产批量复盘视图 |
| 6 | 反思进化树 | T4 | `tree` 制品 | `artifacts/` + 33/48 读取 | 缺「按类别 → 标的 → 轴」的反思树模板 |
| 7 | 优化图表统计 | — | 权重/参数变更记录 | `weights.yaml` + `weights_hash` | 缺 `chart_weights` 版本化与复盘回写 |

### 1.2 可见性（复用 ADR-V14，硬约束）

| 对象 | 可见性 | 说明 |
|---|---|---|
| `table/series/matrix/tree/graph`、`lights` | **public** | 前端/API 可调；只含统计事实与轴级状态 |
| `signal` / `comparison` / `order` / `fill` / `position` | **internal** | 唯一对外通道仍是 `l1agg/handoff.py` → 22 |
| 方向措辞（看涨/看跌/建议/目标价） | **禁止（任何层）** | 复用 ADR-V10 白名单；`lights.state` 只用 `lit/warm/dim/conflict/unavailable` |

### 1.3 边界（不做）

- 不新建资产分类体系：类别以 `40-周期神经网络系统/asset_classes.py` 为 SSoT（`leader_registry` 已按此对齐）。
- 不引入 LLM / 随机 / 采样（ADR-V15）；点亮与权重全部确定性可回放。
- 不本地写生产表；回填与体检在云端执行（DB 属主 `luke`），本地只用只读副本。
- 不改 22 既有契约；L1→22 仍走 `FinalDecisionSignal v1.1` + `source=l1-chart`。

---

## §2 资产池（五类，`config/asset_pool.yaml` v2：核心 8 锚定 + 扩展池）

### 2.1 用户口径五类 ↔ 40 层 class

| 用户口径 | 40 层 class（SSoT） | 展示分组名 | 龙头 |
|---|---|---|---|
| 加密资产 | `crypto` | 加密 | BTC（leader）/ ETH / SOL |
| 避险资产 | `precious_metal` | 避险 | XAU（leader）/ XAG |
| 大宗商品 | `energy`（+`industrial_metal` 可选） | 大宗 | CL（leader）/ BZ / NG / XCU |
| 美股 | `us_index` + `us_stock` + `us_etf` | 美股 | US500/US100/DJIA + NVDA/AAPL/MSFT/AMZN/GOOGL/META/TSLA/AMD/GEV/SKHYNIX/SPCX |
| 情绪与利率 | `macro` + `rates_credit` | 情绪 | VIX / US10Y / T10Y2Y |

> 展示层的「五类」是**视图分组**，底层 `asset_class` 仍取 40 层，禁止另立枚举。`SPCX` 为 OKX 代币化标的（非证券本体），必须 `proxy: true` + `tokenized: true`。

### 2.2 实测覆盖（2026-11-15，本地只读副本 + OKX 公开 API）

| 标的 | 来源 / 键 | 行数 | 区间 | 判定 |
|---|---|---|---|---|
| BTC | okx `BTC::close_usd` | 22573 行 / 11 指标 | 长历史 | ✅ |
| ETH | okx `ETH::close_usd` | 16885 行 / 5 指标 | 长历史 | ✅ |
| XAU | okx `XAU::close_usd` | 2188 行 | 2023-11-15~2026-11-12 | ✅ |
| XAG | okx `XAG::close_usd` | **290** | 2026-01-27~2026-11-12 | 🟡 `status=partial`、`degraded_reason=history_lt_3y`（n=290≥250 可点亮，但 3 年不足） |
| CL(WTI) | fred `DCOILWTICO` | 9736 | 长历史 | ✅ |
| BZ(布伦特) | fred `DCOILBRENTEU` | 757 | 2023-11-15~2026-11-11 | ✅ |
| NG | fred `DHHNGSP` | 746 | 2023-11-15~2026-11-11 | ✅ |
| US100(纳指) | fred `NASDAQCOM` | 14257 | 长历史 | ✅ |
| US500(标普) | fred `SP500` | 长历史 | — | ✅ |
| DJIA | nasdaq `DJIA::close_usd` | 752 | 2023-11-15~2026-11-13 | ✅（DIA 代理） |
| SPY / QQQ | nasdaq | 752 / 752 | 同上 | ✅ |
| NVDA/AAPL/MSFT/AMZN/GOOGL/META/TSLA | nasdaq | 各 752 | 同上 | ✅ |
| VIX | fred `VIXCLS` | 9511 | 1990-01-02~2026-11-15 | ✅ |
| US10Y | fred `DGS10` | 16397 | 长历史 | ✅ |
| **AMD** | okx `AMD-USDT-SWAP` | **250** | 2026-03-10~2026-11-14 | ✅ 恰达 250 门槛 |
| **GEV** | okx `GEV-USDT-SWAP` | **179** | 2026-05-20~2026-11-14 | ⚠️ `history_lt_250` |
| **SPCX** | okx `SPCX-USDT-SWAP` | **193** | 2026-05-06~2026-11-14 | ⚠️ `history_lt_250` + `tokenized` |
| **SKHYNIX** | okx `SKHYNIX-USDT-SWAP` | **~158**（listTime 2026-06-10） | 2026-08-07~2026-11-14（实测首屏 100） | ⚠️ `history_lt_250` |
| MSTR / COIN / HOOD / PLTR / ORCL | okx `*-USDT-SWAP` | ≈250（2026-02/03 起） | — | 🟡 可入池，默认不进首屏；**MSTR/COIN 留在 `UNBOUND`**（未回填，保持既有可见性断言） |
| DIA / BRK | — | 无 | — | ⛔ 不可用 |

> **落库状态（2026-11-15 本地只读副本）**：核心 8 + XAG/XCU/DJIA/NVDA/AAPL/MSFT/AMZN/GOOGL/META/TSLA/SPY/QQQ/VIX 共 21 个 `PASS`；`AMD/GEV/SPCX/SKHYNIX` 仍 `MISSING`——**回填必须走云端（DB 属主 `luke`）**，本地只写代码与测试（LT-G8）。

**OKX 探测结论（2026-11-15 实测）**

- 全部为 `*-USDT-SWAP` 线性永续，`ctVal=1`，`ctValCcy=<ticker>`，`state=live`。
- ⚠️ 调用 `/api/v5/market/history-candles` **必须带 `User-Agent`**，否则 403（裸 `urllib` 默认 UA 被拒）。
- ⚠️ 美股代币化标的最早上线 2026-02-25，**不可能有 3 年日频**；故 `min_rows_3y=1090` 对美股一律降级，只保留 `MIN_TREND=250` 硬门。
- OKX 与 Nasdaq 双源并存时**不得**用全局 `source_priority` 判优——OKX 历史更短，会把 752 天砍成 250 天。

### 2.3 定源规则（硬约束，写入 `asset_pool.yaml` v2）

1. **per-symbol 唯一定源**：每个标的在 `anchors[].instrument` 里显式声明 `venue`，运行时不再跨源择优；`source_priority` 只用于**同一 (sub_category, metric) 重复入库时的去重**。
2. **长历史优先**：Nasdaq 有 ≥750 天的一律用 Nasdaq；仅当 Nasdaq/FRED 缺失时才用 OKX（AMD / GEV / SPCX / SKHYNIX / MSTR / COIN）。
3. **历史不足必须显式降级**：`sample_n < 250` → `status=partial` + `degraded_reason="history_lt_250"`，且**禁止点亮**（`lights.state=unavailable`）。
4. **代理必须标注**：`proxy: true`（DJIA→DIA、SPCX→代币化标的、XAU→XAUT），输出必须带 `proxy/unit/sign_flip`（复用 B8 降级契约）。
5. **回填幂等**：新增标的的回填脚本一律 `INSERT OR REPLACE`，云端可重复执行。
6. **质量下限 per-anchor 覆盖（B-LT5）**：`anchors[].history.min_rows` / `extended_anchors[].history.min_rows` 覆盖全局 `quality.min_rows_3y(_trading)`；OKX 代币化美股与短历史标的（AMD/GEV/SPCX/SKHYNIX/XAG/XCU）一律 `min_rows: 250` + `history_lt_3y: true`，Nasdaq/FRED 满 3 年的写 `min_rows: 740`（**不再一刀切给 us_stock 250**，否则等于对 752 天的长历史降标准）。**全局 `quality` 段不动**（[test_asset_pool.py](./tests/test_asset_pool.py) 对 `min_rows_3y == 1090` 的断言继续成立），[coverage_audit.py](./scripts/coverage_audit.py) 改为「先读 per-anchor，缺失再回落全局」，且 `nasdaq` 与 `fred` 同用交易日缺口口径。

### 2.4 `DEFAULT_POOL` 五类首屏（12 个，与前端统一）

```
加密   BTC ETH
避险   XAU XAG
大宗   CL BZ NG
美股   US500 US100 DJIA NVDA
情绪   VIX
```
> 首屏 12 个 = [visual_overview.py](../3.1-FRONTEND/scripts/visual_overview.py) 的 `[:12]` 上限，与 `config/asset_pool.yaml` 的 `pools.default` 逐项一致（`test_asset_pool_v2.py::test_pools_match_leader_registry` 机器断言）。
> `AAPL/MSFT/AMZN/GOOGL/META/TSLA/AMD/GEV/SPCX/SKHYNIX/SPY/QQQ/XCU/T10Y2Y/US10Y` 进 `EXTENDED_POOL`，按类别展开时懒加载（ADR-V6），避免同屏过载；`AMZN` 因此不进首屏。

### 2.5 龙头排名口径（B-LT4，硬约束）

| 项 | 口径 |
|---|---|
| 范围 | 仅 `us_stock` 参与排名；`us_index`/`us_etf`/`crypto`/`commodity` 固定成员，不参与 |
| 打分 | `rank_score = z(20 日均成交额) + z(20 日动量)`，降序取 TopN（N=8） |
| 频率 | 周度，与权重再平衡同 `W-MON` 对齐；周内冻结 |
| 版本 | 每次重排产 `pool_version = rank:{as_of}:{topN 拼接 hash 前 8 位}`，**必须**进 `params_hash`/`replay_key`，否则历史 signal 无法回放 |
| 数据前提 | 需 `us_stock` 成交额字段入库；未入库时降级 `ranking: static` + `rank_source: manual` 并在图 `meta` 标 `rank_degraded` |
| 淘汰规则 | 排名变化只影响**新开仓选股范围**，不改已有 `signal.symbol`；被踢出者仅停止新增，不追溯历史 |
| `role` 扩展（B-LT12） | `leader \| co_leader \| member`；美股三大指数并列为 `co_leader`，`leader_of()` 仍回首个 `leader`，看板与覆盖表全列 `co_leader` |

---

## §3 数据契约

| 项 | 口径 | 复用 |
|---|---|---|
| 时间轴 | 日频 `1D`；加密 UTC 收盘、美股 `America/New_York` 收盘 | `align.py` / `quality_for` |
| As-Of | 全部统计取 `observed_at ≤ as_of` 的最新 vintage | `mm_metric_vintages`（B18） |
| 对齐 | 多资产面板按**原始行 complete-case**，保留行号供日期轴同步过滤 | `stats._panel_rows` |
| 质量块 | `status ∈ {good, partial, empty}` + `degraded_reason` | `envelope.quality_for` |
| 样本门槛 | 趋势/点亮 250；相关 60；领先滞后 120；季节 60（3 年深结论 1095 天） | `stats.MIN_*` |
| 缺失 | `not_collected` / `unavailable` 显式登记，禁止静默空序列 | `leader_registry.UNBOUND` |
| 确定性 | 禁 LLM/随机；`params_hash` / `weights_hash` / `chart_weights_hash` / `replay_key` | ADR-V15/V18 |

---

## §4 图表层契约（维度 B 主体）

### 4.0 方法基座（硬约束，2026-11-15 用户定调）

**数目核对（纠正记忆）**：[SPEC-54-统计图表化能力.md §4.12](./SPEC-54-统计图表化能力.md#L345) 共 **10 条**美联储做法。其中 **4 条**落成方法 ID（I35 协整 / I36 分位回归 / I37 Kalman·DFM / I38 DMA·区制），**6 条**落成不可绕过的机制约束（MIDAS 混频 / 泰勒式 gap 标准化 / FCI 合成 / vintage / 不确定性收缩 / 预测组合等权对照）；另 **I39 带通·STL 周期分解**属同簇补充（§4.12 未单列，代码已注册）。故「方法 ID 层 = 5 个，机制层 = 6 条」——**不是 10 个方法 ID**。

| # | 美联储做法（§4.12 原序） | 固化形态 | ID / 落点 | 在 L1 交易层的位置 |
|---|---|---|---|---|
| 1 | 动态因子模型 + Kalman | 方法 ID | **I37** | trend 轴 `level/slope/±1σ`（D-E15 平滑口径） |
| 2 | 混合频率 MIDAS | 机制 | 多窗口 `[20,60,120,250]` 分频加权 | trend 轴多窗口合成，不重采样 |
| 3 | 误差修正 / 协整 | 方法 ID | **I35** | `equilibrium_gap` 轴（gap，默认关闭，点亮可读） |
| 4 | 泰勒规则式反应函数 | 机制 | 相对中性水平的 `gap` 标准化 | 轴值标准化口径 |
| 5 | Growth-at-Risk 分位回归 | 方法 ID | **I36** | `strength = q90 − q10`（前瞻分布宽度，非点预测） |
| 6 | 金融状况指数 FCI | 机制 | Ledoit-Wolf + 风险平价 | D-E16 聚合曲线合成口径 |
| 7 | 实时数据与修订 vintage | 机制（硬） | `mm_metric_vintages.observed_at` | 全图 `as_of` 唯一口径 |
| 8 | 不确定性指数 | 机制 | 向 `prior` 收缩 `λ_u ∈ [0, 0.5]` | 权重收缩 |
| 9 | 预测组合 + 组合之谜 | 机制（硬刹车） | 等权对照 + SPA | 权重晋升唯一否决门 |
| 10 | 状态依赖权重 DMA / 区制 | 方法 ID | **I38** | 区制权重（换手限速来源） |
| + | 周期分解（同簇补充） | 方法 ID | **I39** | `cycle` 轴相位（30–90 日） |

**硬约束（LT-G11 / LT-G12 机器判定）**：

1. **基座固定**：上表 5 个 ID 与 6 条机制**永久占位**，不可被动态排名淘汰、不可降权为 0、不可被同类方法替换。
2. **其余方法择优**：方法库共 243 个（[test_methods_s2.py](./tests/test_methods_s2.py#L41) 断言）；除基座 5 个外的 **238 个**按动态排名竞争**非基座槽位**，每槽位只取 TopK=2（`config/method_rank.yaml`），依据 `reliability = abs(IC)`（滚动 250 日、purge+embargo 10 日）+ 稳定性 + 可算性（样本门槛满足）。
3. **两集合不相交**：`baseline_methods ∩ ranked_methods = ∅`；排名结果不得写入基座槽位。
4. **可回放**：`baseline_version` + `method_rank_hash` 必须进 `params_hash`/`replay_key`；同 `as_of` 同 hash 复现同排名。
5. **基座缺失即降级**：任一基座方法因样本不足不可算 → 该图 `status=partial`、对应灯 `unavailable`，**不得**用排名方法顶替（否则基座名存实亡）。

### 4.1 权重语义二分（用户 2026-11-15 修正，硬约束）

| 权重 | 作用对象 | 默认 | 门禁 | 落库/审计 |
|---|---|---|---|---|
| **`chart_weights`（图表成员/类别权重）** | 聚合曲线/类别的**展示合成**（D-E16/D-E17 的加权与排序） | **`on`（默认开）** | 无否决门；只要求归一 + 范围校验 | `chart_weights_hash` 入 `visual.meta` |
| **`light_weights`（点亮四轴权重）** | `lights.strength` 的四轴合成（trend/inertia/cycle/foresight） | **`on`（默认开）** | 无否决门；阈值按历史分位标定 | `light_weights_hash` 入 `lights` |
| **交易轴权重**（`axis_weights`） | `direction_rule` 打分的四轴权重 → 影响 signal | **`on`**（`config/weights.yaml`，`off` 降为应急回滚档） | 保留等权否决门（ADR-V19）+ 换手限速 | `weights_hash` 入 `signal` |

- **硬约束**：`chart_weights` 走独立配置文件 `config/chart_weights.yaml`，**禁止**出现在 `paper_replay`/`direction_rule` 入参中（LT-G2 机器断言）。
- `chart_weights` 可由前端调参（滑块），调参只改展示，不改决策；每次变更写 `chart_weights_hash` 与 `source ∈ {config, ui, equal}`。
- **三套权重互不共用（B-LT3）**：`chart_weights`（成员/类别）、`light_weights`（四轴点亮）、`axis_weights`（交易四轴）三个字段名、三份配置段、三个 hash；任一 hash 不得被另一套复用（否则审计无法区分「展示变了」还是「决策变了」）。

### 4.2 图种与用途

| 图种 | 能力 ID | 回答什么 | dataset 要点 |
|---|---|---|---|
| `table` | `D-E17` 类别看板 | 「每类龙头谁强谁弱、样本够不够」 | 组内按 `ret_60` 排序；必带 `n/stale_ratio/status` |
| `series` | `D-E16` 聚合曲线 | 「一类资产整体在往哪走」 | 多成员加权合成一条 `agg` 曲线 + `members[]` |
| `series` | `D-E15` | 「单标的平滑与斜率」 | 已有 |
| `graph` | `D-E18` 资金流向导图 | 「钱从哪类流向哪类」 | 新增 `kind="flow"` 边 + `flow_z` |
| `tree` | `overview` | 「全景：类别 → 标的 → 轴」 | 已有，按五类分组 |
| `signals` | `D-E19` 点亮 | 「哪些轴亮着」 | 轴级状态数组，非图种，随信封 `data.lights` 返回 |

### 4.3 `D-E16` 聚合曲线（新增生产者）

```json
"visual": {
  "kind": "series",
  "spec_version": "1.1",
  "source_capability": "D-E16",
  "dataset": {
    "points": [{"x": "2026-11-14", "y": 101.23, "agg": 101.23,
                "members": {"BTC": 104.1, "ETH": 98.7}}],
    "meta": {
      "smoothing": {"method": "EMA", "window": 26},
      "unit": "rebased_index", "normalize": "rebased_100", "base_date": "2026-01-02",
      "n": 250,
      "chart_weights": {"BTC": 0.35, "ETH": 0.15, "XAU": 0.20, "CL": 0.10, "US500": 0.20},
      "chart_weights_hash": "<64 hex，与 weights_hash 同口径，不带前缀>", "chart_weights_source": "config",
      "members": [{"symbol": "BTC", "weight": 0.35, "n": 250,
                   "stale_ratio": 0.0, "proxy": false, "status": "available"}]
    }
  },
  "encodings": {"x": "date", "y": "agg", "members": "members"}
}
```

规则：

1. **基期**：`base_date = max(各成员首个可用日)`，全部成员 rebase 到该日 = 100（B-LT6）；禁止用固定日历日一刀切。
2. **先归一后加权**：按 `chart_weights` 线性加权；**禁止**对原始价格直接加权（量纲不同）。
3. **短样本剔除**：成员 `n < 250` → 权重置 0 并标 `insufficient_history`，其余权重重新归一（不静默用短样本）。
4. **覆盖度披露**：每点输出 `coverage_ratio = Σ 参与加权成员权重`；`< 0.8` 的点标 `partial_members` 并保留原始 `members` 值；**禁止前向填充**。
5. **校验分层**：配置加载期 fail-closed（范围/和为 1，越界抛 `ChartWeightsError`，启动即失败）；运行期若仍非法 → 降级等权 + `weights_degraded=true`，**不返回 None**（`build_visual` 是 FAIL-OPEN 语义，不能整图静默消失）。
6. `meta.smoothing` 与 `meta.n` 必填（V-G8 不变）。
7. **`spec_version` 保持 `"1.0"`**（B-LT1）：新字段全部放 `dataset`/`meta`（结构开放），[visual.py](./l1agg/capabilities/visual.py) 的 `!= SPEC_VERSION` 硬判不改，避免整图被拒。

> **P0-2 落点（2026-11-15 已实现）**：[chart_weights.yaml](./config/chart_weights.yaml)（`cw-1.0.0`）+ [chart_weights.py](./l1agg/chart_weights.py)。
> `load()` 加载期 fail-closed（范围/和为 1/`light_weights` 四轴齐全/阈值 `0≤warm≤lit≤1`）；`normalize()` simplex 归一；
> `chart_weights_hash()` / `light_weights_hash()` 带域标签（`chart|` / `light|`）做域分离，阈值变更也改 light 指纹；
> `prune_short_members()` 实现规则 3；`resolve_members()` 实现规则 5（`mode=off` → 等权回滚档；运行期非法 → 等权 + `weights_degraded`）；
> `assert_no_chart_weights()` 递归拦 LT-G2 越界注入。规则 1/4/6（`base_date` / `coverage_ratio` / `smoothing`）属 D-E16 生产者，随 P0-3 落地。

### 4.4 `D-E17` 类别看板（`table`，固定列）

`class | symbol | label | role | last | ret_20 | ret_60 | ret_120 | ret_250 | vol_60 | mdd | adx14 | corr_to_leader_90d | lights_ref | lit_n | warm_n | n | stale_ratio | status`

- `groups = ["class", "role"]`；组内默认按 `ret_60` 降序（排序在后端完成，ADR-V5）。
- `status != available` 时首列追加 `degraded_reason`（复用 `_table_with_degrade`）。
- **不重复算点亮（B-LT9）**：看板只给 `lights_ref`（= `light_weights_hash`）与 `lit_n/warm_n` 计数，四轴明细**只**在 `D-E19` 的 `lights` 中；否则同一事实出现两套口径，违反 ADR-V13 零重算。

### 4.5 `D-E18` 资金流向导图（`graph` 扩 `flow`）

```json
"dataset": {
  "nodes": [{"id": "class:crypto", "label": "加密", "group": "class"},
            {"id": "BTC", "label": "BTC", "group": "crypto"}],
  "edges": [{"src": "class:us_index", "dst": "class:crypto", "kind": "flow",
             "weight": 0.6, "p_adj": null}],
  "meta": {"flows": [{"edge_index": 0, "flow_usdt": 1.2e9, "flow_z": 1.8,
                      "window": 5, "direction": "net_out_of_src"}]}
}
```

- **边字段严格 5 键（B-LT2）**：`{src,dst,kind,weight,p_adj}`；[overview.py](./l1agg/capabilities/overview.py#L551) 用 `set(edge) != {...}` 硬判，多一个字段即抛错。`flow` 边取 `weight = min(1, |flow_z| / 3)`、`p_adj = null`（`null` 已被允许，见 L557-559）。
- 流水明细旁挂 `dataset.meta.flows[]`，以 `edge_index` 关联；**边键校验器不改**（仍严格 5 键），仅把 `flow` 加入 `GRAPH_EDGE_KINDS` 白名单（[overview.py](./l1agg/capabilities/overview.py#L25)），不动 `test_visual.py` 的既有断言。
- `direction` 语义固定为**相对 src**：`net_out_of_src` / `net_into_src`，消除「谁流入谁」歧义。
- 数据源：`etf_flow`（11821 行 / 17 指标）、`derivatives_spot`（净流入代理）、`funding_rate`；**无流数据时降级为 `corr`-only 导图并给 `reason="flow_unavailable"`**（不伪造边）。
- 节点 ≤ 300、边 ≤ 2000 不变；`flow` 边按 `|flow_z|` 排序取 TopK。

### 4.6 图纪律（沿用）

`title ≤ 60 字且不含结论`、`caveat="历史统计，不代表未来"`、`rows/points ≤ 500`、`L1_VISUAL_ENABLED=0` 全量停用。

---

## §5 信号层与「信号点亮」（维度 B 核心）

### 5.0 信号触发层次（在方法基座上研究，硬约束）

信号不是「指标凑一起投票」，而是**基座事实 → 排名增量 → 点亮 → 判定**四层单向流：

| 层 | 输入 | 允许做什么 | 禁止做什么 |
|---|---|---|---|
| **L0 基座事实** | I37 `level/slope`、I35 `gap`、I36 `q10/q50/q90`、I38 区制权重、I39 周期相位 + §4.0 六条机制 | 必须全算；缺一即 `partial/unavailable` | 不得用排名方法顶替基座槽位 |
| **L1 排名增量** | 238 个非基座方法，每槽位 TopK=2 | 只能**加权修饰**已有轴值（幅度上限 ±20%） | 不得反转基座轴符号；不得新增轴 |
| **L2 点亮** | L0+L1 轴值 → `light_weights` | 分档 `lit/warm/dim/conflict/unavailable` | 不得输出方向措辞 |
| **L3 判定** | 轴值 → `direction_rule.decide`（internal） | 产 `signal` → 22 | 不对外暴露；不复算 L0/L1 |

- **符号保护（LT-G12）**：`sign(axis_after) == sign(axis_baseline)` 必须成立；且 `|axis_after − axis_baseline| / max(|axis_baseline|, ε) ≤ 0.20`，越界即回退基座值并记 `rank_clipped=true`。
- **触发顺序**：先判 L0 是否 `available`（不可用则直接 `unavailable`，不进入 L1），再叠 L1、再点亮、最后判定。顺序颠倒会产出「排名方法救活基座缺失」的伪信号。

### 5.1 四轴 + 周期 + 前瞻

| 轴 | 统计事实（L1-S） | 现有实现 |
|---|---|---|
| `trend` 趋势延续 | 20/60/120/250 对数斜率符号一致性 × 窗口权重 | `D-E15` + `direction_rule` axis |
| `adx` 趋势强度 | ADX14 分档 `[[0,20,0],[20,25,0.5],[25,∞,1]]` | 同上 |
| `inertia` 惯性 | 滚动收益自相关 / 动量衰减 | 同上 |
| `coherence` 前瞻共振 | 龙头 vs 成员同向率（C18/D-E11）+ 领先滞后 | 同上 |
| `cycle` 周期 | 30–90 日周期相位 + 月度季节强度（≥5 年才作强结论，否则描述） | **I39** 带通·STL / `D-J02` |
| `foresight` 前瞻 | **I36** 分位回归 `q10/q50/q90` 宽度 + VIX 分位、`T10Y2Y` 倒挂、Brent−WTI 价差、NG 库存代理、DGS10 变化率 | I36 + 本节新增（全部为**统计事实**，非预测） |

### 5.2 `lights` 对象（public，随信封 `data.lights`）

```json
"lights": [{
  "symbol": "BTC", "class": "crypto", "as_of": "2026-11-14",
  "axes": {
    "trend":    {"state": "lit",  "strength": 0.78, "bucket": "high",
                 "evidence": {"capability": "D-E15", "field": "slope_60", "value": 0.0021},
                 "flags": []},
    "inertia":  {"state": "warm", "strength": 0.54, "bucket": "mid", "…": "…"},
    "cycle":    {"state": "dim",  "strength": 0.21, "bucket": "low",
                 "flags": ["seasonality_depth_lt_5y"]},
    "foresight":{"state": "conflict", "strength": 0.62, "bucket": "mid",
                 "flags": ["vix_divergence"]}
  },
  "summary": {"lit_n": 1, "warm_n": 1, "conflict_n": 1, "unavailable_n": 0},
  "light_weights_hash": "sha256:…"
}]
```

### 5.3 点亮规则（阈值，写入 `config/chart_weights.yaml`）

| 条件 | `state` |
|---|---|
| `strength ≥ lit_pct`（默认 **0.70**，历史分位标定）且无反向旗标 | `lit` |
| `warm_pct ≤ strength < lit_pct`（默认 **0.40**） | `warm` |
| `strength < warm_pct` | `dim` |
| `trend.lit` 且 `foresight.flags` 含 `vix_pct≥0.90` / `curve_inverted`（**只读旗标，不读 `foresight.strength`**） | `conflict` |
| 任一基座方法不可算 / `gate != ok` / `n < 250` / `not_collected` | `unavailable` |

- `strength = Σ_k lw_k × normalized_axis_k`，`lw` 取 **`light_weights`**（B-LT3：与 `chart_weights`、交易 `axis_weights` 三者互不共用）；同输入同 `light_weights_hash` 必须字节一致（LT-G3）。
- **阈值标定（B-LT7）**：`lit_pct/warm_pct` 由 `scripts/calibrate_light.py` 在基座方法上按 2023-11 起全样本四轴强度分位回算（`lit_pct = p70`、`warm_pct = p40`），结果与 `calibrated_at` 写入 `config/chart_weights.yaml` 的 `light_weights` 段；未标定时用 0.70/0.40 且 `lights.meta.thresholds_uncalibrated=true`。
- **禁止**输出方向：`state` 只表达「统计一致性/强度」，不表达多空；任何「看涨/看跌/建议」措辞被 LT-G1 扫描拦下。
- `unavailable` 优先于一切：历史不足的标的（GEV/SPCX/SKHYNIX）只能 `unavailable`；任一基座方法缺算同样 `unavailable`（§4.0 约束 5）。

### 5.4 点亮 → 内部信号的关系

```
图（public） ──轴级事实──▶ lights（public）
     │                        │
     └──── 同一批统计事实 ─────┴──▶ direction_rule（internal）──▶ signal ──▶ 22
```

点亮是 `direction_rule` 的**公开投影**（同输入、同 `as_of`、零重算），不是第二套判定：`lights.axes.*.strength` 必须等于内部轴分解的归一化值（±1e-9，LT-AC4）。

---

## §6 执行闭环（维度 A）

| 步 | 动作 | 落点 | 门禁 |
|---|---|---|---|
| A1 资产池 | 读 `asset_pool.yaml` v2 + `leader_registry` | `asset_pool.py` / `leader_registry.py` | 未绑定显式 `not_collected` |
| A2 取数 | 云端回填（幂等）/ 本地只读副本 | `scripts/backfill_*` | 不写生产表 |
| A3 图表 | `stats.*` → `visual` | `capabilities/*` | V-G1…V-G10 |
| A4 信号 | `paper_replay.replay()` 逐根 | `trading/paper_replay.py` | `replay_key` 可复现 |
| A5 交接 | `handoff` → `FinalDecisionSignal v1.1` | `l1agg/handoff.py` | 49 契约 + 22 前置校验 |
| A6 复盘 | `comparison` 三重障碍打分 | `trading/comparison.py` | L2 不可覆盖 L1-D |
| A7 反思 | 制品 → `tree` → 33/48 | `artifacts/` | 幂等、字节一致 |
| A8 优化 | DSR/SPA 晋升门禁 → 权重/参数变更 | `weights.py` / `chart_weights.yaml` | 不达标禁止晋级 |

### 6.1 多资产批量回放（P1）

- 每个标的**独立** `signal`（`UNIQUE(as_of,symbol,rule_version)` 不变）；跨标的只做**风控汇总**（`cluster.clusters` / `risk.check_order` 的总敞口/簇敞口），不合并成组合信号。
- **冻结缓存（B-LT10）**：权重按 `(symbol, iso_week)` 缓存，同周内 `weights_hash` 与 `inject` 判定必须完全一致；估计次数 = 周数（非根数），12 标的 × 700 根 ≈ 12 × 100 次而非 8400 次。
- 输出 `batch_metrics{symbol, bars, n_entries, win_rate, avg_ret, cum_ret, turnover}`；**看板口径与回放不混比**（B-LT8）：`D-E17.ret_60` 只与 `D-E12(window=60).ret` 对齐，`cum_ret` 只用于复盘表。

### 6.2 复盘（A6）

复用 `comparison` 既有字段（实表口径：`l1_direction/l1_strength/l2_verdict/realized_ret/scored_at`，**无** `l2_direction/l2_strength`），新增**按类聚合**的复盘表（[batch.py](./l1agg/trading/batch.py) `review_table`）：`class | n | win_rate | avg_ret | avg_hold_bars | scored_at`；未打分行（`realized_ret IS NULL`）不入分母、只计 `n_pending`，`hold_bars` 缺失时 `avg_hold_bars=null` 并计 `hold_bars_missing`，`class` 取 `leader_registry.class_of`（未绑定 → `unbound`），表为内部视图（ADR-V14）不建信封。

### 6.3 反思进化树（A7）

制品路径 `artifacts/reflect/<as_of>/tree.json`，结构固定三层：`类别 → 标的 → 轴`，每叶 `meta{capability, series_id, proxy, unit, state, strength}`；33 `thought_tree.py` / 48 只读，不回写 L1。

### 6.4 优化反馈（A8）

只允许两条落地：① 交易轴权重（晋升门禁 DSR>0 且 SPA p<0.05）；② `chart_weights`/`light_weights`（纯展示，允许直接调参，但必须版本化并留对应 hash）。

**同一段数据不得既拟合又晋升（B-LT11）**：参数搜索与晋升必须在**独立 holdout** 上做（purge + embargo 各 10 日），同一 `rule_version` 只允许一次晋升记录；否则 DSR/SPA 只是在为样本内拟合盖章。

---

## §7 前端契约

| 项 | 契约 |
|---|---|
| 路由 | 复用 `/dashboard/visual`；`lights` 随 `/api/visual/overview` **同包返回**（不单开 `/api/visual/lights`，避免二次进程） |
| 编排 | [visual_overview.py](../3.1-FRONTEND/scripts/visual_overview.py) 单进程产 `tree/graph/D-E10/D-E12/D-E15/D-E16/D-E17/D-E18` 共 8 面板 + `lights`（D-E16/D-E17 走 `build_visual`，D-E18 取 `data.capabilities["D-E18"]["visual"]`；`lights` 直接调 `lights()`） |
| 组件 | `LightsView.tsx`（D-E19 五态 + 四轴 chip）、`SeriesView.tsx`（D-E16 覆盖度带 `coverage_ratio`/`partial_members`）、`GraphView.tsx`（D-E18 `flow` 箭头 + `meta.flows` tooltip）、`ClassBoard` 复用既有表格渲染 |
| 零统计 | 组件内无业务 `reduce/sum`；排序、分档、归一全部后端给（ADR-V5） |
| 降级 | `status!=good` 显示 `degraded_reason` 徽标；`unavailable` 灯置灰且不可点 |
| 交互 | 点灯 → 下钻 `table`（D-E17 行）；点类别节点 → 下钻 `tree` 叶；点成员 → `D-E15` 曲线 |
| 权重调参 | 只有 `chart_weights` 滑块；提交写 `chart_weights_hash`，**无任何交易轴权重入口**（LT-G2） |
| 首屏 | 12 个默认标的（§2.4），展开类别时懒加载 `EXTENDED_POOL` |

---

## §8 门禁（LT-G）

| ID | 门禁 | 机器判定 |
|---|---|---|
| LT-G1 | 无方向措辞 | 扫描 `title/answer/labels`，命中「看涨/看跌/建议/目标价/阻力最小方向是」即失败 |
| LT-G2 | 双权重隔离 | `paper_replay`/`direction_rule` 入参签名无 `chart_weights`；两套 hash 字段不同名 |
| LT-G3 | 点亮可回放 | 同 `as_of`+同 `chart_weights_hash` → `lights` 字节一致 |
| LT-G4 | 聚合先归一 | `D-E16` 成员均 rebase 100；越界/和≠1 抛 `ChartWeightsError` |
| LT-G5 | 无前视 | 删除 `as_of` 之后数据重算，`chart_weights_hash`/`replay_key` 不变 |
| LT-G6 | 短历史不点亮 | `n<250` 或 `not_collected` → `state=unavailable` |
| LT-G7 | 资金流不伪造 | 无 flow 数据 → `graph` 降级 `corr`-only + `reason` |
| LT-G8 | 不写生产表 | 本地仅 `mode=ro` 打开 `dreambuddy_core.db` |
| LT-G9 | 执行零外露 | 递归扫描 `data` 键，不得出现 `signal/order/fill/position` |
| LT-G10 | 容量上限 | 节点≤300 / 边≤2000 / points≤500 / rows≤500 |
| LT-G11 | 基座不可淘汰 | `baseline_methods = {I35,I36,I37,I38,I39} ∪ 6 条机制`；`baseline ∩ ranked = ∅`；排名结果不得落入基座槽位；`baseline_version` 入 `params_hash` |
| LT-G12 | 排名增量不越权 | `sign(axis_after) == sign(axis_baseline)` 且相对偏差 ≤20%，越界回退基座并记 `rank_clipped=true`；`method_rank_hash` 入 `replay_key` |
| LT-G13 | 点亮不受 ADR-V2 约束 | `data.lights` 可与非 `visual` 字段共存，但同一信封仍**只允许 1 个** `visual` |

---

## §9 代码落点

| 新增/修改 | 文件 | 内容 |
|---|---|---|
| 改 | `config/asset_pool.yaml` → v2 | 核心 8 锚定不动（兼容 v1 断言）+ `extended_anchors`（20 个：避险/大宗/美股个股·ETF/情绪）+ `view_class` 五类视图 + `view_order` + `pools.default(12)/extended(15)` + `history.min_rows` per-anchor 门槛 + `tokenized` 标记 + 定源规则注释 |
| 改 | `l1agg/asset_pool.py` | 解析 `extended_anchors`/`pools`/`view_order`/`tokenized`/`min_rows`/`history_lt_3y`；新增 `all_anchors` / `by_view` / `views` / `pool()` / `min_rows_for()`；`resolve` 跨核心+扩展；校验：`tokenized ⇒ proxy`、`history_lt_3y ⇒ min_rows`、pools 引用必须可解析、id/别名跨段唯一 |
| 改 | `l1agg/leader_registry.py` | `BINDINGS` 补 4 个（AMD/GEV/SPCX/SKHYNIX，`tokenized=True`+`proxy=True`）；**MSTR/COIN 保留 `UNBOUND`**（未回填，保持既有可见性断言）；`DEFAULT_POOL` 12 项五类化 + 新增 `EXTENDED_POOL`、`VIEW_CLASSES`、`view_of`、`pool_by_view`；`coverage()` 增 `partial`+`degraded_reason`+`tokenized` |
| 改 | `scripts/coverage_audit.py` | 先读 per-anchor `min_rows`（缺失回落全局）；`nasdaq` 纳入交易日缺口口径；覆盖体检范围扩到 `all_anchors()`（核心+扩展） |
| 改 | `scripts/backfill_okx_prices.py` | `--extended` 显式回填扩展池；`--only` 时在核心+扩展中查找（否则 AMD/GEV/SPCX/SKHYNIX 无法单独回填）；默认仍只回填核心，幂等 `INSERT OR REPLACE` |
| 新 | `config/chart_weights.yaml` | 五类成员权重 + 点亮阈值 + `version`（`cw-1.0.0`：`chart_weights` 12 项 / `views` 5 项 / `light_weights` 4 轴 / `thresholds` / `constraints`） |
| 新 | `l1agg/chart_weights.py` | `load` / `normalize` / `validate_weights` / `chart_weights_hash` / `light_weights_hash` / `prune_short_members` / `resolve_members` / `assert_no_chart_weights`（LT-G2/G3 + §4.3 规则 3/5） |
| 新 | `l1agg/capabilities/aggregate.py` | `D-E16` 聚合曲线（`aggregate_curve` / `aggregate_block`）+ `D-E17` 类别看板（`class_board`） |
| 改 | `l1agg/capabilities/visual.py` | `_PRODUCERS` 增 `D-E16/D-E17`；新增 `CLASS_BOARD_COLUMNS`（固定 19 列）；`KINDS` 与 `spec_version="1.0"` 不动 |
| 改 | `contracts/capability_result.schema.json` | `series.points` 增 `agg/members/coverage_ratio/partial_members`（§4.3 逐点披露；向后兼容） |
| — | `l1agg/capabilities/envelope.py` | 本期无需改：`_check_visual` 未对 `series.meta` 设封闭白名单；`graph` 边 `flow` 属 `D-E18`（LTL-07） |
| 新 | `l1agg/capabilities/lights.py` | ✅ P0-4 已落地：`D-E19` 轴级点亮投影（读 `direction_rule` 轴值 + I39 周期，零重算；五档状态 + `conflict` 只读旗标 + 短样本 `unavailable`） |
| 新 | `l1agg/capabilities/flow.py` | ✅ P0-5 已落地：`D-E18` 资金流向导图（`flow` 边 5 键 + `meta.flows[]`；无流数据降级 `corr`-only） |
| 新 | `l1agg/trading/batch.py` | ✅ P1-2 已落地：`batch_replay`（逐标的回放 + `batch_metrics{7 键}` + `replay_key`，失败隔离、不合并组合信号）+ `review_table`（按 40 层 `class` 聚合，6 列固定，内部视图） |
| 改 | `config/weights.yaml` | `mode: off → on`（`off` 保留为回滚档） |
| 改 | `capability_manifest.yaml` + `l1agg/capabilities/manifest.py` | ✅ LTL-12 已落地：登记 `D-E16/D-E17/D-E18/D-E19`（`visibility: public`）；新增 `method_binding ∈ {compute,display}`（缺省 `compute`），`display` 能力只披露方法血缘、不参与 `validate_execution` 的执行覆盖统计 |
| 改 | `l1agg/capabilities/stats.py` | ✅ 新增 `aggregate_curve/class_board/flow_graph/lights` 四个延迟导入薄壳并进 `_EXECUTORS`（48 条，与 manifest 严格相等；延迟导入避免 `capabilities/__init__ → stats → aggregate` 循环） |
| 新 | `config/baseline_methods.yaml` | 基座固化：`{I35,I36,I37,I38,I39}` + 6 条机制开关 + `baseline_version` |
| 新 | `config/method_rank.yaml` | 非基座槽位 TopK、`reliability` 窗口（250）、purge/embargo（10）、`rank_topk=2` |
| 新 | `l1agg/methods/ranking.py` | 动态排名：`rank(methods, as_of) → [(method_id, score)]` + `method_rank_hash`；断言与基座不相交 |
| 新 | `scripts/calibrate_light.py` | 点亮阈值分位标定（`lit_pct=p70`、`warm_pct=p40`），回写 `chart_weights.yaml.light_weights` |
| 新 | `tests/test_chart_weights.py`、`test_aggregate_visual.py`、`test_lights.py`、`test_flow_graph.py`、`test_batch_replay.py`、`test_asset_pool_v2.py` | 见 §12 |

**`method_binding` 契约（硬约束，2026-11-15 随 LTL-12 定调）**

| 取值 | 含义 | `validate_execution` 行为 |
|---|---|---|
| `compute`（缺省） | 能力执行时**必须**调用声明的每个方法 | 声明的 method 未被执行 → `ManifestError`（`require_complete=True`） |
| `display` | 纯投影/展示能力，`methods` 仅披露**方法血缘**（该图的数据来源），执行时直接消费上游结果 | 不进入 `incomplete` 判定，不计入 coverage 分子/分母；`mode`/`min_n`/`visibility` 等其余校验不变 |

> 未标 `display` 而实际不调方法层 → 测试立刻红（`test_manifest_matches_methods_actually_executed_across_capability_branches`）。因此**任何新增纯投影能力必须显式写 `method_binding: display`**，不得靠放宽 `require_complete` 绕过。

---

## §10 路线

| 阶段 | 内容 | 依赖 | 判据 |
|---|---|---|---|
| **P0-0** 方法基座固化 | `baseline_methods.yaml` + `l1agg/methods/ranking.py` + `method_rank.yaml`；断言基座 5 ID + 6 机制不可淘汰 | §4.0 | LT-G11/G12；`test_baseline_methods.py` 全绿 |
| **P0-1** 资产池 v2 | AMD/GEV/SPCX/SKHYNIX 入池 + 定源规则 + 五类分组 + per-anchor `min_rows` | 本次 OKX 实测 | `test_asset_pool_v2.py` 全绿（30 例）；`coverage()` 无 `missing` ← **依赖云端回填**（本地只读副本不回填：`sudo -u luke` + `backfill_okx_prices.py --only AMD,GEV,SPCX,SKHYNIX`，写前 `sqlite3 .backup`） |
| **P0-2** `chart_weights` | 配置文件 + 解析/归一/hash + 双权重隔离 | P0-1 | LT-G2/G4；`test_chart_weights.py` |
| **P0-3** D-E16/D-E17 | 聚合曲线 + 类别看板 | P0-2 | LT-AC1/AC2/AC4 |
| **P0-4** D-E19 点亮 | 轴级投影 + 五档状态 | P0-3 + `direction_rule` | LT-G3/G6、LT-AC3 |
| **P1-1** D-E18 资金流 | `flow` 边 + 导图 | `etf_flow` 已有 | LT-G7、LT-AC6 |
| **P1-2** 批量回放 | 多标的 `signal` + 按类复盘表 | P0-4 | LT-AC5 |
| **P1-3** D-E16/D-E17/D-E18/D-E19 登记 | `capability_manifest.yaml` + `_EXECUTORS` + `method_binding` | P1-1 | LTL-12 关闭；`supported()==manifest()` 48↔48 |
| **P2-1** 反思进化树 | 制品 + 33/48 读侧 smoke | P1-2 | LT-AC7 |
| **P2-2** 优化反馈 | DSR/SPA 晋升 + `chart_weights` 复盘 | P2-1 | LT-AC8 |

---

## §11 风险

| 风险 | 影响 | 对策 |
|---|---|---|
| OKX 代币化美股历史短 | 点亮误判 | LT-G6 强制 `unavailable`；`tokenized/proxy` 必标 |
| `source_priority` 跨源误选 | 752 天被砍到 250 天 | §2.3 定源规则 + 单测断言 `sample_n` |
| 两套权重混用 | 展示影响决策 | LT-G2 签名级隔离 |
| 聚合曲线量纲混算 | 曲线失真 | 先 rebase 100 再加权（LT-G4） |
| 资金流数据缺 | 导图空转 | LT-G7 降级不伪造 |
| 点亮被读成「买卖」 | 越过 L1 纪律 | LT-G1 + `state` 语义白名单 |
| 首屏资产过多 | 卡顿 | 12 默认 + 懒加载扩展池 |

---

## §12 验收

| ID | 验收标准（可复测） |
|---|---|
| LT-AC1 | `D-E16` 同输入同 `chart_weights_hash` → `agg` 曲线字节一致；成员 rebase 后首点=100 |
| LT-AC2 | `D-E17` 列齐全、组内按 `ret_60` 降序、`status!=available` 首列 `degraded_reason` |
| LT-AC3 | `lights.axes.{trend,inertia,cycle,foresight}` 与内部轴分解归一值差 ≤1e-9 |
| LT-AC4 | 短样本标的（GEV/SPCX/SKHYNIX）一律 `unavailable` 且 `flags` 含原因 |
| LT-AC5 | `D-E17.ret_60 == D-E12(window=60).ret`（≤1e-9）；`cum_ret` 只出现在回放/复盘链路（`batch_metrics`），**不得**进入 `D-E17` 看板列；复盘表按 §6.2 固定 6 列（聚合口径 `avg_ret`），两者口径不混比（[test_batch_replay.py](./tests/test_batch_replay.py) 机器断言） |
| LT-AC6 | `D-E18` 有 flow 数据出 `flow` 边、无数据出 `corr`-only + `reason` |
| LT-AC7 | `artifacts/reflect/<as_of>/tree.json` 幂等（重跑字节一致） |
| LT-AC8 | `off` 回滚档下 `signal` 与 v0.22 字节一致；`on` 才允许权重注入 |
| LT-AC9 | LT-G1 措辞扫描 20 条样本 0 命中 |
| LT-AC10 | 前端 `npx tsc --noEmit` 通过；`jest src/components/visual` 全绿 |
| LT-AC11 | 基座 5 个方法 ID + 6 条机制在 `baseline_methods` 中恒在；与 `ranked_methods` 交集为空；基座方法样本不足时产出 `unavailable` 而非由排名方法顶替 |
| LT-AC12 | `light_weights` 标定后可复算：`lit_pct == p70`、`warm_pct == p40`（±1e-6），且 `calibrated_at` 落库 |
| LT-AC13 | `D-E16` 成员起点晚 60 天时，前 60 天 `coverage_ratio < 0.8` 且标 `partial_members`；`base_date == max(成员首个可用日)` |

---

## §13 待完成项台账

| ID | 级别 | 事项 | 状态 |
|---|---|---|---|
| LTL-01 | P0 | `config/asset_pool.yaml` v2（五类 + OKX 代币化美股 + 定源规则） | ✅ 2026-11-15（v2：核心 8 + `extended_anchors` 20 + `view_order` + `pools`；`python -m l1agg.asset_pool` 校验通过） |
| LTL-02 | P0 | `leader_registry` BINDINGS 补标的 + `DEFAULT/EXTENDED_POOL` 五类化 | ✅ 2026-11-15（补 AMD/GEV/SPCX/SKHYNIX 共 4 个；MSTR/COIN 因未回填保留 `UNBOUND`；首屏 12 项 + `EXTENDED_POOL` 15 项 + `pool_by_view` 五类） |
| LTL-03 | P0 | `config/chart_weights.yaml` + `l1agg/chart_weights.py`（归一/校验/hash） | ✅ 2026-11-15（`cw-1.0.0`；[test_chart_weights.py](./tests/test_chart_weights.py) 29 例全绿：加载期 fail-closed / 运行期降级等权 / 短样本裁剪重归一 / `chart|`·`light|` 域分离 hash / LT-G2 递归拦截 / 交易层签名扫描无 chart 入参；阈值标定 LTL-16 与 D-E16 接线 LTL-04 仍待做） |
| LTL-04 | P0 | `D-E16` 聚合曲线（先 rebase 后加权） | ✅ 2026-11-15（[aggregate.py](./l1agg/capabilities/aggregate.py)：`base_date=max(首个可用日)`、rebased_100、EMA26、逐点 `coverage_ratio`、`<0.8→partial_members`、无前向填充、短样本剔除重归一、`chart_weights_hash` 覆盖最终权重；[test_aggregate.py](./tests/test_aggregate.py) 覆盖） |
| LTL-05 | P0 | `D-E17` 类别看板（组内排序 + 降级列） | ✅ 2026-11-15（`class_board`：固定 19 列、五类 `view_order` + 组内 `ret_60` 降序、`status != available` 首列 `degraded_reason`、`lights_ref/lit_n/warm_n` 零重算；并入 [test_aggregate.py](./tests/test_aggregate.py)） |
| LTL-06 | P0 | `D-E19` 点亮投影（五档状态 + 轴值零重算） | ✅ 2026-11-15（[lights.py](./l1agg/capabilities/lights.py)：`axes_from_direction` 把 `direction_rule` 的 trend/inertia/coherence 归一为点亮 trend/inertia/foresight（`|v|/w`，零重算、±1e-9），cycle 取 I39 外部归一值；五档 `lit/warm/dim/conflict/unavailable`、`conflict` 仅由 `trend.lit` + foresight 只读旗标触发（不读 strength）；短样本/`gate!=ok`/`not_collected` 整标的 unavailable；缺失轴剔除后权重重新归一；权重非法→等权降级、`mode=off`→等权回滚；`light_weights_hash`（含阈值）确定性；`data.lights` 随信封返回、不产 `visual`；[test_lights.py](./tests/test_lights.py) 25 例全绿；`capability_manifest.yaml` 登记仍随 LTL-12） |
| LTL-07 | P1 | `D-E18` 资金流向导图（`flow` 边 + 降级） | ✅ 2026-11-15（[flow.py](./l1agg/capabilities/flow.py)：`flow_edges` 严格 5 键 `{src,dst,kind,weight,p_adj}`、`kind="flow"`、`weight=min(1,\|z\|/3)`、`p_adj=null`；按 `|flow_z|` 降序 TopK 且 `meta.flows[].edge_index` 一一对应；`direction` 仅 `net_out_of_src\|net_into_src`，非法回落留痕；无流数据 → `corr`-only + `reason="flow_unavailable"`、连 corr 也缺 → `ok=false/empty`；`GRAPH_EDGE_KINDS` 增 `flow`（边键硬判不变）；[test_flow_graph.py](./tests/test_flow_graph.py) 14 例；真实 `etf_flow` 取数留待云端回填后接线） |
| LTL-08 | P1 | 多资产批量回放 + 按类复盘表 | ✅ 2026-11-15（[batch.py](./l1agg/trading/batch.py)：`batch_replay` 逐标的调 `paper_replay.replay`、输出 `batch_metrics{symbol,bars,n_entries,win_rate,avg_ret,cum_ret,turnover}` + 逐标的 `replay_key`，失败隔离（`skipped` + reason，不伪造指标）且 `flags=[no_portfolio_signal]` 明确不合并组合信号；`review_table` 按 `leader_registry.class_of` 聚合 6 列、未打分行只计 `n_pending`、`hold_bars` 缺失留空计数、内部视图不外发；[test_batch_replay.py](./tests/test_batch_replay.py) 13 例；未做权重晋升门（LTL-16）与真实多标的数据接线） |
| LTL-09 | P1 | `config/weights.yaml` `mode: on`（`off` 保留回滚） | ⬜ |
| LTL-10 | P2 | 反思进化树制品 + 33/48 读侧 smoke | ⬜ |
| LTL-11 | P2 | 优化反馈（DSR/SPA 晋升 + `chart_weights` 复盘） | ⬜ |
| LTL-12 | P1 | `capability_manifest.yaml` 登记 4 个新出口 + INDEX 登记本 SPEC | ✅ 2026-11-15（manifest 增 `D-E16/D-E17/D-E18/D-E19` 四条（`visibility: public`、`method_binding: display`）+ `stats._EXECUTORS` 增 4 个延迟导入薄壳（48 条 ↔ 48 条严格相等）；`manifest.py` 引入 `method_binding ∈ {compute,display}` 并对 `display` 能力豁免「声明方法必须被执行」门禁（纯投影不调方法层）；`test_capabilities.py` executor 名集合补齐；`run_capability('D-E19'/'D-E16')` 实测可达；`python3 -m pytest tests -q` EXIT=0；INDEX 已登记本 SPEC） |
| LTL-13 | P0 | 方法基座固化（`baseline_methods.yaml` + `ranking.py` + `method_rank.yaml`，基座 5 ID + 6 机制不可淘汰） | ✅ 2026-11-15（[test_baseline_methods.py](./tests/test_baseline_methods.py) 12 例全绿；54 全量 EXIT=0） |
| LTL-14 | P0 | 资产池 v2 per-anchor `min_rows` 覆盖（修 B-LT5，`coverage_audit` 先读 per-anchor） | ✅ 2026-11-15（[test_asset_pool_v2.py](./tests/test_asset_pool_v2.py) 30 例；AMD/GEV/SPCX/SKHYNIX=250，Nasdaq/FRED=740，okx 3 年=1090；**数据回填待云端**：本地只读副本 AMD/GEV/SPCX/SKHYNIX 仍 `MISSING`，OKX dry-run 已验 inst_id 与行数 250/179/193/159） |
| LTL-15 | P0 | 龙头动态排名 `pool_version` 入 `params_hash`（B-LT4） | ⬜（随 P0-2/D-E17 排名落地；本版只固化 `DEFAULT/EXTENDED_POOL` 静态成员，未引入 `us_stock` 成交额打分） |
| LTL-16 | P1 | `light_weights` + `scripts/calibrate_light.py` 阈值分位标定（B-LT7） | ⬜ |

### 修订记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-11-15 | 首版：确立双维度（A 交易链路闭环 / B 前端图表）；权重语义二分（`chart_weights` 默认开无门禁 vs 交易轴权重默认 on 保留等权否决门）；资产池五类 + OKX 代币化美股实测（AMD 250 / GEV 179 / SPCX 193 / SKHYNIX ~158，均需 `history_lt_250` 降级）；新增 `D-E16` 聚合曲线 / `D-E17` 类别看板 / `D-E18` 资金流导图 / `D-E19` 点亮；新增 LT-G1…G10、LT-AC1…AC10、LTL-01…12 |
| v0.2 | 2026-11-15 | 据 [评审](./SPEC评审报告-L1交易层-v0.1.md) 关闭 B-LT1…B-LT12：`spec_version` 回 1.0（B-LT1）；graph 边严格 5 键 + `meta.flows[]`（B-LT2）；`chart_weights`/`light_weights`/`axis_weights` 三权分立（B-LT3）；龙头动态排名 + `pool_version` 入 hash（B-LT4）；per-anchor `min_rows`（B-LT5）；聚合基期 `max(首个可用日)` + `coverage_ratio`（B-LT6）；阈值分位标定 + `conflict` 只读旗标（B-LT7）；LT-AC5 改三方比对（B-LT8）；看板改 `lights_ref`（B-LT9）；冻结缓存断言（B-LT10）；holdout 晋升口径（B-LT11）；`role` 扩 `co_leader`（B-LT12）。**新增 §4.0 方法基座硬约束**（美联储 §4.12 共 10 条 → 5 个方法 ID + 6 条机制，永久占位）+ §5.0 信号四层触发（L0 基座 → L1 排名增量 ±20% → L2 点亮 → L3 判定）+ LT-G11…G13、LT-AC11…AC13、LTL-13…16、P0-0 |
| v0.3 | 2026-11-15 | **P0-0 方法基座落地**：新增 [baseline_methods.yaml](./config/baseline_methods.yaml)（5 ID + 6 机制，配置缺失/停用/多出即 fail-closed）、[method_rank.yaml](./config/method_rank.yaml)（window 250 / purge 10 / embargo 10 / topk 2）、[ranking.py](./l1agg/methods/ranking.py)（`load_baseline` / `load_rank_config` / `rank` / `assert_disjoint` / `blend_axis`）、[test_baseline_methods.py](./tests/test_baseline_methods.py)（12 例）；LTL-13 关闭，54 全量测试 EXIT=0 |
| v0.4 | 2026-11-15 | **P0-1 资产池 v2 落地**：`config/asset_pool.yaml` 升 v2（核心 8 锚定结构与 `quality` 段不动 + `extended_anchors` 20 + `view_class`/`view_order` 五类视图 + `pools.default(12)/extended(15)` + per-anchor `history.min_rows` + `tokenized`）；`asset_pool.py` 增 `all_anchors/by_view/views/pool/min_rows_for` 与 `tokenized⇒proxy`、`history_lt_3y⇒min_rows`、pools 可解析性校验；`leader_registry.py` 补 AMD/GEV/SPCX/SKHYNIX（`tokenized+proxy`）、首屏 12 项、`EXTENDED_POOL`、`VIEW_CLASSES/pool_by_view`、`coverage()` 增 `partial/history_lt_250` 降级；`coverage_audit.py` 先读 per-anchor 且 `nasdaq` 用交易日缺口口径；`backfill_okx_prices.py` 增 `--extended`。修正 §2.4 首屏数目（原写 13 实列 14 → 统一为 12，与前端 `[:12]` 对齐）；`us_stock` 不再一刀切 250（Nasdaq 满 3 年按 740）。新增 [test_asset_pool_v2.py](./tests/test_asset_pool_v2.py) 30 例；LTL-01/LTL-02/LTL-14 关闭，LTL-15 留待排名落地；**数据回填须在云端执行**（本地只读副本仍缺 4 个代币化标的） |
| v0.5 | 2026-11-15 | **P0-2 图表权重落地**：新增 [chart_weights.yaml](./config/chart_weights.yaml)（`cw-1.0.0`：成员 12 项 / 五类 `views` / `light_weights` 4 轴 / `thresholds` / `constraints`）与 [chart_weights.py](./l1agg/chart_weights.py)（加载期 fail-closed、运行期降级等权 FAIL-OPEN、simplex 归一、`chart|`/`light|` 域分离 hash、短样本裁剪重归一、LT-G2 递归拦截）；`chart_weights_hash` 统一为 64 hex（与 `weights_hash` 同口径，不带 `sha256:` 前缀）；新增 [test_chart_weights.py](./tests/test_chart_weights.py) 29 例；LTL-03 关闭；阈值标定（LTL-16）与 D-E16 接线（LTL-04）仍待做 |
| v0.6 | 2026-11-15 | **P0-3 D-E16/D-E17 落地**：新增 [aggregate.py](./l1agg/capabilities/aggregate.py)（`aggregate_curve`/`aggregate_block`：`base_date=max(成员首个可用日)`、先 rebase=100 后按 `resolve_members` 权重合成、EMA26、逐点 `coverage_ratio` 与 `<0.8→partial_members`、**无前向填充**、短样本剔除重归一、`weights_degraded`/`pruned` 显式披露；`class_board`：固定 19 列、`view_order` + 组内 `ret_60` 降序、`status != available` 首列 `degraded_reason`、`lights_ref/lit_n/warm_n` 零重算）；[visual.py](./l1agg/capabilities/visual.py) 注册 `D-E16/D-E17` 生产者并导出 `CLASS_BOARD_COLUMNS`；[capability_result.schema.json](./contracts/capability_result.schema.json) `series.points` 增 `agg/members/coverage_ratio/partial_members`（向后兼容，`spec_version` 仍 `1.0`）；新增 [test_aggregate.py](./tests/test_aggregate.py) 19 例；LTL-04/LTL-05 关闭；54 全量 `pytest tests -q` EXIT=0；仍不做云端回填（P0-1 数据缺口不变）与 git commit |
| v0.7 | 2026-11-15 | **P0-4 D-E19 点亮落地**：新增 [lights.py](./l1agg/capabilities/lights.py)。轴映射 `trend/inertia/coherence → trend/inertia/foresight`（`|axis_value|/axis_weight`，零重算 ≤1e-9；`adx`/`gap` 不进点亮），`cycle` 取 I39 外部归一值；五档 `lit/warm/dim/conflict/unavailable` + `bucket high/mid/low`；`conflict` **只读旗标**（`vix_pct_ge_0.90`/`vix_divergence`/`curve_inverted`，仅当 `trend.lit`，不读 `foresight.strength`）；`unavailable` 优先（`n<min_rows`/`gate!=ok`/`not_collected`，抓 `history_lt_250` 等 reason）；总体 `strength=Σ lw×norm`，缺失轴剔除后按剩余 `light_weights` 重新归一；运行期权重非法→等权 + `weights_degraded`、`mode=off`→等权回滚；阈值越界回落 0.70/0.40；`light_weights_hash`（含阈值）确定、`data.lights` 随信封返回且不产 `visual`；新增 [test_lights.py](./tests/test_lights.py) 25 例；LTL-06 关闭；54 全量 EXIT=0。**未做**：`capability_manifest.yaml` 登记（随 LTL-12）、阈值分位标定（LTL-16）、云端回填与 git commit |
| v0.8 | 2026-11-15 | **P0-5 D-E18 落地**：新增 [flow.py](./l1agg/capabilities/flow.py)。`flow_edges` 严格 5 键边（`kind="flow"`、`weight=min(1,\|flow_z\|/3)`、`p_adj=null`），按 `|flow_z|` 降序 TopK，`dataset.meta.flows[].edge_index` 与边一一对应，`direction` 只允许 `net_out_of_src/net_into_src`（非法回落 + 留痕），坏行/端点缺失/截断均显式 flags；无流数据 → `corr`-only 降级（复用 `D-E05` 共振网络）+ `meta.reason="flow_unavailable"` + `quality.partial`，流与相关网络双缺 → `ok=false/empty`（LT-G7 不伪造边）；`GRAPH_EDGE_KINDS` 增 `flow`（边键硬判不变，`test_visual.py` 断言不动）；新增 [test_flow_graph.py](./tests/test_flow_graph.py) 14 例；LTL-07 关闭；54 全量 EXIT=0。**未做**：`etf_flow`/`derivatives_spot`/`funding_rate` 真实取数接线（依赖云端回填）、`capability_manifest.yaml` 登记（LTL-12）、git commit |
| v0.9 | 2026-11-15 | **P1-2 落地**：新增 [batch.py](./l1agg/trading/batch.py)。`batch_replay` 逐标的调 `paper_replay.replay`（同一 `(标的, iso_week)` 权重冻结由 L1D-08 保证，本模块不另算权重），输出 `batch_metrics{symbol,bars,n_entries,win_rate,avg_ret,cum_ret,turnover}` + `replay_keys` + `params_hash`，失败隔离（`skipped` + reason，不伪造指标）；`flags=[no_portfolio_signal]` 机器声明「不合并组合信号」，`risk` 仅透传 `cluster/risk` 汇总；`review_table` 按 40 层 `class` 聚合 6 列（未打分行只计 `n_pending`，`hold_bars` 缺失留空计数，`unbound` 兜底），为 internal 视图不建信封。SPEC 校正：§6.2 `comparison` 实表字段为 `l1_direction/l1_strength/l2_verdict/realized_ret/scored_at`；LT-AC5 改为「`cum_ret` 只在回放/复盘链路、不得进 `D-E17` 列」。新增 [test_batch_replay.py](./tests/test_batch_replay.py) 13 例；LTL-08 关闭；54 全量 EXIT=0。**未做**：真实多标的数据接线、权重晋升门（LTL-16）、`weights.yaml mode: on`（LTL-09）、git commit |
| v0.10 | 2026-11-15 | **B 链路最小闭环打通 + LTL-12 落地**。（1）**P0 编排**：[visual_overview.py](../3.1-FRONTEND/scripts/visual_overview.py) 单进程产 8 面板（`tree/graph/D-E10/D-E12/D-E15/D-E16/D-E17/D-E18`）+ `lights`，替代「每图一次 python spawn」；`_load_series` 改 5 元组（新增逐标的 `raw`），新增 `_zscore/_load_flows/_flow_nodes/_min_rows/_lights_entries/_board_assets/_extra_panels`；D-E16/D-E17 走 `build_visual`、D-E18 取 `data.capabilities["D-E18"]["visual"]`（`envelope.build` 把 visual 放 `data.visual` 而非信封顶层）；`_FLOW_AGGREGATE_KEYS` 过滤 `total_flow` 等聚合行避免伪造 `etf:*` 边；实跑 3.0s / 154 KB / 12 条 `flow` 边。（2）**P0 渲染**：新增 [LightsView.tsx](../3.1-FRONTEND/src/components/visual/LightsView.tsx)（五态色 + 四轴 chip + 阈值/hash 页脚，2 例 jest），`SeriesView` 增覆盖度带（`coverage_ratio` 着色、`partial_members` 入 title），`GraphView` 增 `flow` 绿色边 + 箭头（收在节点外沿）+ `meta.flows` tooltip，`VisualRenderer` 透传 `dataset.meta`，`VisualWorkbench` 挂载「点亮投影」卡。（3）**LTL-12**：`capability_manifest.yaml` 登记 4 出口 + `method_binding: display`（纯投影只披露血缘、不参与执行覆盖）；`stats.py` 增 4 个延迟导入薄壳，`_EXECUTORS` 48 条与 manifest 严格相等；`manifest.validate` 校验 `method_binding` 枚举；`capability_result.schema.json` graph `kind` 枚举补 `flow`。证据：脚本实跑 8 visuals + lights 12 行；`npx tsc --noEmit` 0 错；`jest src/components/visual` 全绿；`python3 -m pytest tests -q` EXIT=0。**未做**：`weights.yaml mode: on`（LTL-09）、`light_weights` 阈值标定（LTL-16）、云端回填（AMD/GEV/SPCX/SKHYNIX）、git commit |
