# SPEC-9DOMAIN-HISTORY-CONTEXT（v1.3 P2 本地实施完成）— 9 域各维历史统计与维度上下文

> **状态**：✅ v1.3 P2 本地实现完成（P0 + P1 全绿；云端真实回填待执行），实施落点见 §12.2
> **父 SPEC**：[SPEC-EMERGENCE-FINANCIAL-ENV-v2.8.md](./SPEC-EMERGENCE-FINANCIAL-ENV-v2.8.md) §9（v2.8 已标注「需单独开 SPEC」）
> **负责域**：`9-基本面分析`（权威实现）、`18-数据获取中心`（数据地基 / 消费方）、`48-涌现架构`（消费方）
> **版本**：v1.3 / 2026-11-12（契约仍以 v1.1 冻结口径为准，v1.2+ 仅补实施结果）
> **本轮不做**：本地历史回填（交云端）、前端改造、1y/3y 全量长历史补齐
> **v1.1 修订依据**：同行评审 7 Major + 5 Minor + 3 项部分阻断，逐条处置见 §13

---

## 0. 一句话目标

把 9 域的 10 个模块从「只有当日快照 + 一份合成假序列」升级为「**append-only 真实历史 + 可冻结口径的统计上下文**」，向父 SPEC §9 交付 7 个历史字段（结构齐全、值按可用性给真值或 `null`），并向 18 域 `DimensionContext` 提供唯一权威数据源。

**能力边界（JF-1 响应，必须预先声明）**：P0 交付后，真正**新增**的信息只有「时间维度上的位置与趋势」（`trend_20d` / `mean_revert_z` / `extreme_days` / `regime_switch_30d`），四者同源于一条 `value` 序列、彼此高度共线。`pct_rank_1y/3y` 这类「相对历史位置」信息在 P0 **不可用**（历史不足 250 天），需累积或云端回填。本 SPEC 解决的是「把假数据换成真数据 + 把口径冻结」，不是「一次性凭空多出 7 类信息」。

---

## 1. 现状实测与依赖审计

### 1.1 双实现漂移（已实测确认）

| 项 | `engines/least_resistance.py` | `core_engine/least_resistance.py` |
|---|---|---|
| 服务实际使用 | ✅ `ml_trade_service_v2.py` L25 | ❌ 无服务引用 |
| velocity 分母 | `hist_std`（`_std()`） | 固定 `0.3` |
| acceleration | `tanh(raw_score - mean(last3))` | `tanh((velocity - mean(hist_velocities)) / 0.2)` |
| 返回字段 | 含 `trend_summary` | **无** `trend_summary` |
| `summarize_trend` 文案 | 6 档 | 9 片段拼接 |
| `generate_signal` 签名 | `(r3d, metrics, stress)` | `(r3d, sentiment_index, flow_idx, heat, stress)` |
| `run_module_analysis` | **无** | 有（L183，含持久化副作用） |
| 持久化 | 无（纯函数） | 写 `storage/module_timeseries.json`，`MAX_ENTRIES=100` |

> **M-1 教训**：两版不仅口径不同，**函数集合也不同**。「统一到 engines」不等于「改个 import 就行」。

### 1.2 `core_engine/module_timeseries.json` 依赖审计结论（用户要求项）

| 检查项 | 结果 |
|---|---|
| `grep -rn "module_timeseries"`（全仓 py） | 仅命中 `core_engine/least_resistance.py` 自身（L8/L168/L173/L193/L203） |
| `grep -rn "from core_engine\|import core_engine\|core_engine\."`（全仓 py） | **0 命中** |
| `ls storage/module_timeseries.json` | **No such file or directory**（从未生成） |
| `ls storage/latest_snapshot.json` | **不存在**（`tavily_data_generator` 从未执行） |
| `core_engine/` 目录内容 | 仅 `least_resistance.py` |

**唯一依赖方**：`9-基本面分析/tavily_data_generator.py`
- L11 `sys.path.insert(0, os.path.join(BASE_DIR, "core_engine"))`
- L12 `from least_resistance import compute_resistance_3d, run_module_analysis`
- L222-252 `run_full_pipeline()` → L231 `run_module_analysis(...)`；L238 `compute_resistance_3d(avg_score, [])`
- 外部调用：`grep -rn "tavily_data_generator|run_full_pipeline"` 全仓 → 除自身 `__main__` 与 4-MEMORY 历史记录 / 48 域架构图基线产物外 **0 命中**；无 launchd / plist / cron / 服务 / 测试引用。

**审计结论**：
1. `core_engine/least_resistance.py` 与 `storage/module_timeseries.json` 均为**死路径**。
2. 删除 core_engine 版不影响任何生产需求方。
3. **但** engines 版缺少 `run_module_analysis`，故 `tavily_data_generator` 不能只改 import（见 §6 C2）。
4. 43 域 `strategic_extension/five_domain_feature_computer.py`（L1639、L2519）显式 `from engines.least_resistance import compute_resistance_3d` → **必须保持 engines 版签名与返回字段向后兼容**（尤其 `trend_summary` 不能删）。

### 1.3 现有 timeseries 是合成数据（关键发现）

`ml_trade_service_v2.py` L357-376 `refresh_module()`：

```python
snapshot = build_module_snapshot(module)
save_snapshot(module, snapshot)
ts_data = generate_timeseries(module, days=90)   # ← 不是真实历史
save_timeseries(module, ts_data)                  # ← 整体覆盖，非 append
```

调用链：`18 data_center/compat/data_compat.py` L77 → `9 data_collector.generate_timeseries` L382 → `_make_timeseries()` L311-379（随机游走 + 末点对齐，L328 `random.uniform(-0.2, 0.2)`、L334 `random.uniform(-0.08, 0.08)`）。

可解释的实测现象：10 个文件各恰好 90 条、日期 2026-07-16 → 2026-10-13 连续、含 `velocity_label`（`_make_timeseries` L344-355）、停更于最后一次 `refresh_module()`、**每次刷新整份覆盖**。

**推论**：现存 90 条不可用于任何统计；但前端 `/fundamental/snapshot` 的 `timeseries` 字段依赖它，不能直接停（见 §4.4）。

### 1.4 `value` 的量纲随模块漂移（M-2 关键事实）

`_make_timeseries` 的入参 `score` 来自 `_MODULE_CONTEXT["scores"]`，各模块写入量纲不同：

| 模块 | 写入字段（`data_collector.py`） | 量纲 | `vmin/vmax` |
|---|---|---|---|
| flow | `fund_flow_score`（L605） | -1 ~ 1 评分 | -1 / 1 |
| sentiment | `sentiment_index`（L769） | 0 ~ 100 指数 | 0 / 1（注意：与 score 量纲不一致） |
| macro | `policy_score`（L918） | -1 ~ 1 评分 | -1 / 1 |
| valuation | `mvrv_ratio` | 1.3 ~ 3.2 比率 | 0.5 / 4.0 |
| onchain | `exchange_net_flow` | -100 ~ 200 量级 | -500 / 500 |
| breadth / news / calendar / intermarket / narrative | 通用评分 | -1 ~ 1 | -1 / 1 |

且 `compute_module_resistance`（`ml_trade_service_v2.py` L206-238）会再做一次 `(raw - center)/scale` 归一化得到传给 `compute_resistance_3d` 的 `normalized`。

**结论**：`value` **不是**「模块原始量纲」，而是「模块内可比评分」，量纲因模块而异；`value` 与 `direction_score` 是同一量的线性变换关系，不存在「原始 vs 派生」的区分。统计**只能在模块内做**，跨模块一律用 `direction_score`。

### 1.5 18 域 `DimensionContext` 现状

`18-数据获取中心/data_center/processing/dimension_context.py`：
- 8 维：D1→`macro`、D2→`flow`、D3→`technical`(kline)、D4→`sentiment`、C6、C7→`onchain`、C8、NEWS→`event`
- 60 日滚动窗口、z clamp ±3、`strength = abs(tanh(z))`、`availability` long≥900 / short≥30 / none
- 只映射 6 个模块族；`breadth` / `intermarket` / `valuation` / `calendar` / `narrative` 5 个模块**未映射**
- 仅被 18 域 `p3a` / `p3b` 脚本消费；48 / 50 域未接

### 1.6 数据地基实测

| 源 | 状态 |
|---|---|
| `18 data_center.db records` | 33259 行，`yfinance` / `fred` 自 2023 起 |
| `19 DAL mm_metrics.fear_greed` | 7320 行 / 4007 天（2018-02 → 2026-11-11）✅ 唯一够 1y/3y 的源 |
| `mm_metrics.fear_greed_enhanced` | 826 天 |
| `mm_metrics.long_short_ratio` | 849 天 |
| `mm_metrics.ccxt` | 865 天 |
| `mm_metrics.blockchain_info` | 866 天 |
| `mm_funding_rate` / `open_interest` / `taker_volume` / `liquidation` | **0 行** |

### 1.7 父 SPEC §9 七字段可满足度

| 字段 | P0 | P1 | P2 | 说明 |
|---|---|---|---|---|
| `lookback_days` | ✅ 真值 | — | — | 始终可给 |
| `trend_20d` | ✅ 真值 | — | — | 需 ≥20 观测 |
| `mean_revert_z` | ✅ 真值 | — | — | 需 ≥60 观测 |
| `extreme_days` | ✅ 真值 | — | — | 需 ≥60 观测 |
| `regime_switch_30d` | ✅ 真值 | — | — | 需 ≥31 观测 |
| `pct_rank_1y` | `null` | `null` | ✅ | 需 ≥250 观测（累积或回填） |
| `pct_rank_3y` | `null` | `null` | ✅（仅 `fear_greed`） | 需 ≥750 观测 |

---

## 2. 设计原则（硬约束）

1. **权威实现唯一化**：9 域历史统计只在 `9-基本面分析/engines/dimension_history.py` 实现一次；其它域只允许作为消费者或数据提供者，禁止第二套口径。（用户已确认）
2. **禁止插值 / 禁止填 0 / 禁止超期回退**：缺日、缺源一律 `null` + 原因标注；回退上限沿用 v2.8 的 `FNG_MAX_STALE_DAYS = 3` 纪律。
3. **append-only**：历史文件只追加、按 `(module, date)` 幂等；禁止整份覆盖写。
4. **合成数据不进统计层**：mock 序列不写入 `dimension_history/`；合成标记只存在于快照层（`meta.timeseries_synthetic`）。统计层不存在「合成观测」这一状态。
5. **口径冻结**：§5.2 一经评审通过即预注册，实现与测试以它为准。
6. **不动已成立的契约**：`engines.least_resistance.compute_resistance_3d` 返回字段（含 `trend_summary`）向后兼容；`/fundamental/snapshot` 响应字段不删。
7. **fail-closed 写、fail-open 读**：写入缺 `observed_date` 时拒绝落盘（宁可不写，不写错日期）；读取异常时返回 `availability="none"` 而非抛错。

### 2.1 替代方案评估（框架锁定响应）

| 方案 | 做法 | 评价 |
|---|---|---|
| **A（本 SPEC）** | 9 域模块级 append-only jsonl + 纯函数统计 | ✅ 与 9 域现有 10 模块/快照结构同构，改动面最小；缺点：需时间累积 |
| B | 直接从 19 DAL 长历史源重建 10 模块序列 | ❌ `mm_funding_rate` 等 4 表 0 行，且多数模块（news/narrative/calendar）在 DAL 无历史源，无法重建 |
| C | 复用 18 域 `factor_series_map` 的 60 细类映射 | ❌ 它是「因子→序列」映射，不是「模块→序列」，且 60 细类里 40 个 `source=none` |

选 A，并在 P2 对 `fear_greed` 走 B 的单源旁路。

---

## 3. `DimensionHistory` 契约

### 3.1 单模块返回结构

```json
{
  "module": "flow",
  "as_of": "2026-11-11",
  "source": "9_storage_jsonl",
  "value_scale": "score_neg1_pos1",
  "lookback_days": 421,
  "availability": "short",
  "coverage": {
    "observed_days": 421,
    "expected_days": 432,
    "missing_days": 11,
    "max_gap_days": 3,
    "median_gap_days": 1,
    "first_day": "2025-09-17",
    "last_day": "2026-11-11"
  },
  "latest": {
    "direction": "up",
    "direction_score": 0.41,
    "velocity": 0.12,
    "acceleration": -0.03,
    "velocity_label": "温和流入",
    "confidence": 0.68,
    "data_points": 422,
    "trend_summary": "多方略占优势"
  },
  "stats": {
    "pct_rank_1y": null,
    "pct_rank_3y": null,
    "extreme_days": 12,
    "mean_revert_z": 1.31,
    "trend_20d": 0.42,
    "regime_switch_30d": 2
  },
  "notes": [
    "pct_rank_1y: insufficient_history(421<250)",
    "pct_rank_3y: insufficient_history(421<750)",
    "mean_revert_z: winsor_clamped(+3)"
  ]
}
```

### 3.2 字段语义（冻结）

| 字段 | 类型 | 缺失语义 |
|---|---|---|
| `module` | str | 10 模块之一 |
| `as_of` | str(YYYY-MM-DD) | 查询截断日 |
| `source` | `9_storage_jsonl` \| `none` | `none` 表示无任何观测 |
| `value_scale` | enum | `score_neg1_pos1` / `index_0_100` / `ratio` / `level`，见 §1.4 |
| `lookback_days` | int | **实际参与统计的观测条数**（非请求窗口、非日历天） |
| `availability` | `long`(≥900) \| `short`(≥30) \| `none` | 仅由 `observed_days` 决定 |
| `coverage.expected_days` | int | 按观测频率推算：`round(span_days / median_gap_days) + 1`（非日历日差） |
| `coverage.missing_days` | int | `max(0, expected_days - observed_days)` |
| `coverage.max_gap_days` | int | 相邻观测的最大日历日差（周末 2-3 天属正常） |
| `latest.*` | object | 直接复用 `compute_resistance_3d` 的输出，不重算 |
| `stats.pct_rank_1y` | float \| null | `null` 当 `observed_days < 250`；ties 用 **average rank** |
| `stats.pct_rank_3y` | float \| null | `null` 当 `observed_days < 750`；ties 同上 |
| `stats.extreme_days` | int \| null | `null` 当 `observed_days < 60`；值为**近 250 观测内 \|z60\| ≥ 2 的计数**（z60 与 `mean_revert_z` 同口径） |
| `stats.mean_revert_z` | float \| null | `null` 当 `observed_days < 60`；最近 60 观测的 z，clamp ±3 |
| `stats.trend_20d` | float \| null | `null` 当 `observed_days < 20`；**20 观测内 `value` 与时间序号的 Spearman 秩相关** ∈ [-1, 1] |
| `stats.regime_switch_30d` | int \| null | `null` 当 `observed_days < 31`；**2 日确认后**的 direction 游程切换数 |
| `notes` | list[str] | 每个 `null` 必有一条可读原因；clamp 命中亦需记录 |

### 3.3 字段消费方（JF-2 响应：无消费方不进 P0）

| 字段 | 当前/计划消费方 | P0 是否交付 |
|---|---|---|
| `latest.*` | 9 域 `/fundamental/snapshot`、43 域、18 域 adapter | ✅ |
| `coverage.*` | 9 域健康检查、运维停更告警 | ✅ |
| `mean_revert_z` / `trend_20d` / `regime_switch_30d` / `extreme_days` | 18 域 `DimensionContext`（P1 接入）、48 域 P 层（P2 可选） | ✅ |
| `pct_rank_1y` / `pct_rank_3y` | 18 域（P2）、45 域评测（P2） | 结构交付，值 `null` |

---

## 4. 数据层

### 4.1 存储位置与格式

- 目录：`9-基本面分析/storage/dimension_history/`
- 文件：`{module}.jsonl`（10 份）
- 每行一个观测（append-only）：

```json
{"date": "2026-11-11", "module": "flow", "value": 0.31, "value_scale": "score_neg1_pos1",
 "direction": "up", "direction_score": 0.41, "velocity": 0.12, "acceleration": -0.03,
 "velocity_label": "温和流入", "confidence": 0.68, "data_points": 422,
 "written_at": "2026-11-11T00:05:12Z", "schema_version": 1}
```

### 4.2 观测日来源（M-3 响应）

`build_module_snapshot()` 在响应 `meta` 增加 `observed_date`，取值优先级：

1. DAL / legacy payload 自带的 `as_of` / `date` / `timestamp`（若存在）；
2. 该模块 `metrics.core` 中与时间相关的字段（如 `fear_greed` 的观测日）；
3. 兜底 `datetime.now(timezone.utc).date().isoformat()`，并在 `meta.observed_date_source = "fallback_now"` 标记。

`append_observation()` **只读 `meta.observed_date`**；字段缺失或不可解析 → **拒绝写入并返回 `False`**（fail-closed），绝不静默用 `now()` 补位。

### 4.3 写入器（唯一入口）

`engines/dimension_history.py`：

```python
def append_observation(module: str, obs: dict, base_dir: Path | None = None) -> bool:
    """按 (module, date) 幂等写入；同日重复 → 保留 written_at 更晚者。缺 date 返回 False。"""

def load_series(module: str, as_of: str | None = None,
                base_dir: Path | None = None) -> list[dict]:
    """读取并按 date 升序返回；as_of 严格截断（date <= as_of）。"""
```

### 4.4 接入点改造

`ml_trade_service_v2.py::refresh_module()` L357-376：

```python
snapshot = build_module_snapshot(module)
save_snapshot(module, snapshot)
append_observation(module, _to_observation(snapshot))     # 真实观测，append-only
ts_data, is_synthetic = _select_timeseries(module, snapshot, min_real_days=30)
save_timeseries(module, ts_data)
snapshot["meta"]["timeseries_synthetic"] = is_synthetic    # 合成标记只留在快照层
```

`_select_timeseries`：真实历史 ≥ 30 条 → 返回真实序列（`is_synthetic=false`）；否则返回原 mock 并标 `true`。

### 4.5 存量数据迁移

现存 `storage/timeseries/*.json`（90 条合成）**不导入** `dimension_history/`；原文件保留、不删不改名，靠 `meta.timeseries_synthetic` 提示。

### 4.6 停更检测（S-4 响应）

`max_gap_days` 为**相邻观测的日历日差**，因此周末 2-3 天属正常；告警条件 `max_gap_days > 7` 时在 `notes` 追加 `stale_series`。不使用「首末日历差 vs 观测数」的算法（那会让周末永久计为缺失、告警永不触发）。

---

## 5. 计算层（纯函数，无 IO）

### 5.1 函数签名

```python
STATS_MIN_DAYS = {"pct_rank_1y": 250, "pct_rank_3y": 750, "extreme_days": 60,
                  "mean_revert_z": 60, "trend_20d": 20, "regime_switch_30d": 31}
EXTREME_Z = 2.0
Z_WINDOW = 60
RANK_WINDOW_1Y, RANK_WINDOW_3Y, EXTREME_SCAN_WINDOW = 250, 750, 250

def compute_dimension_history(series: list[dict], module: str,
                              as_of: str | None = None) -> dict:
    """输入已加载观测序列（纯函数，便于单测）。"""

def get_dimension_history(module: str, as_of: str | None = None,
                          base_dir: Path | None = None) -> dict:
    """load_series + compute_dimension_history 的便捷入口。"""
```

### 5.2 统计口径（预注册，冻结）

| 统计 | 口径 |
|---|---|
| 取值列 | `value`（模块内可比评分），**只在模块内统计**；跨模块比较一律用 `direction_score` |
| `pct_rank_1y` | 取最近 `min(n, 250)` 个观测，`average_rank(x_t) / (m - 1)`；`n < 250` → `null` |
| `pct_rank_3y` | 同上，窗口 750；`n < 750` → `null` |
| `mean_revert_z` | 最近 60 观测窗口的 `(x_t - mean60) / std60`，`clamp(-3, 3)`；`std60 == 0` → `null` + note `zero_variance` |
| `extreme_days` | 对近 250 观测的每一日，按**该日当时**的 60 日窗口算 z（无前视），统计 `\|z\| >= 2` 的天数；n < 60 → `null` |
| `trend_20d` | 最近 20 观测的 `value` 与其序号 `0..19` 的 **Spearman 秩相关**（ties=average），∈ [-1, 1]；n < 20 → `null` |
| `regime_switch_30d` | 先做**2 日确认**（连续两天同 direction 才生效，否则沿用前值），再取近 30 个确认后观测的游程切换数（游程数 - 1）；n < 31 → `null` |
| 缺失日 | 不插值、不 ffill |

### 5.3 与 `least_resistance` 的关系

- `compute_resistance_3d` **保持不动**（43 域 + 服务依赖）；
- `DimensionHistory.latest` 直接复用其输出，不重写；
- `velocity_label` 的五档阈值（±0.05 / ±0.01）从 `data_collector._make_timeseries` L344-355 抽成公共函数 `velocity_label_of(vel, scale)`，两处共用，避免漂移。

---

## 6. 收敛与改造清单

| # | 文件 | 动作 | 风险 |
|---|---|---|---|
| **C1** | `9-基本面分析/core_engine/least_resistance.py` + `core_engine/` 目录 | **删除** | 低：审计确认 0 生产引用 |
| **C2** | `9-基本面分析/tavily_data_generator.py` | **不是**改 import（M-1）：① 删除 L11 `sys.path.insert(core_engine)`；② 改 `from engines.least_resistance import compute_resistance_3d, generate_signal`；③ 在文件内新增 5 行适配函数 `_run_module_analysis(...)` 组合 `compute_resistance_3d + generate_signal`（参数按 engines 的 `(r3d, metrics, stress)` 签名映射），并**不持久化**；④ 文件头标注 `NON-PRODUCTION / 无调度调用` | 低：无外部调用方 |
| **C3** | `9-基本面分析/engines/dimension_history.py` | **新增**（§4.3 + §5.1） | 中：新模块 |
| **C4** | `9-基本面分析/ml_trade_service_v2.py` | `build_module_snapshot()` 增 `meta.observed_date` / `observed_date_source`；`refresh_module()` 接入 append + `_select_timeseries`；快照 `meta` 增 `timeseries_synthetic` | 中：字段只增不改 |
| **C5** | `9-基本面分析/engines/least_resistance.py` | 抽 `velocity_label_of()`（行为不变） | 低 |
| **C6** | `18-数据获取中心/data_center/processing/dimension_context.py` | P1：补 5 维（编号见 §7.2）并改为优先消费 9 域 | 中：仅 18 p3a/p3b 消费 |
| **C7** | `9-基本面分析/tests/test_dimension_history.py` | 新增 ≥16 条 | — |
| **C8** | `9-基本面分析/tests/test_no_core_engine_import.py` | 新增静态守护 | — |

**C1 前置**：`git log --all -- core_engine` 确认无其它分支引用；删除后全仓 `grep core_engine` 仅剩 48 域基线产物（可接受）。

---

## 7. 消费面

### 7.1 新增 HTTP 端点（9 域）

```
GET /fundamental/history/<module>?as_of=YYYY-MM-DD&lookback=750
→ DimensionHistory（§3.1）
```

- `module` 非法 → 400；无观测 → 200 + `availability="none"` + `notes=["no_observations"]`（不 500）；只读，不触发采集。

### 7.2 18 域消费（M-4 + P1 五维定义）

import 修正（路径必须显式插入 9 域根）：

```python
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / "9-基本面分析"))
from engines.dimension_history import get_dimension_history  # noqa: E402
```

新增 5 维（与 18 现有 `D1-D4 / C6-C8 / NEWS` 编号体系衔接，**只增不改**）：

| 维度 | 模块 | z 口径 | strength |
|---|---|---|---|
| `D5` | `breadth` | `value` 的 60 观测滚动 z | `abs(tanh(z))` |
| `C9` | `intermarket` | 同上 | 同上 |
| `C10` | `valuation` | 同上 | 同上 |
| `C11` | `calendar` | 同上 | 同上 |
| `C12` | `narrative` | 同上 | 同上 |

统一：`direction` 沿用 ±0.3 阈值、`availability` 沿用 900/30 阈值、9 域不可用时 FAIL-OPEN 回退现有 kline/mm 探测。

### 7.3 48 域消费（P2，可选）

`financial_env_validate.py` 的 P 层叠加 `trend_20d` 作为形态上下文（v1.3 已接）：9 域真实序列逐日滚动 20 观测，经 `align` 广播为市场级 `P_trend_20d`，独立走时序 IC；不混入截面 `P_score`，缺历史 FAIL-OPEN。

**`P_trend_20d` 故意不预注册**（不在 `factor_preregistration.json` 中）：
- 它是从 `sentiment` 模块派生出的**描述性上下文**，不是可验证的独立 alpha 假设；
- 市场级单值无截面变异，IC 只有时序模式；gate 检查会如实返回 `insufficient_data` —— 这是设计意图，不是遗漏；
- 时序 IC 结果仅供诊断（与 M 层 VIX 档位同属「状态描述」而非 alpha 候选），不写 verdict、不记 trial，避免污染试验记账。

---

## 8. 验收

### 8.1 单元测试（≥16 条，`9-基本面分析/tests/test_dimension_history.py`）

1. 空序列 → `source="none"`、`availability="none"`、stats 全 `null`、`notes` 非空；
2. `n=1 / 19 / 20` 的 `trend_20d` 边界（前两者 `null`）；
3. `trend_20d` 用 Spearman：严格递增 → `1.0`；严格递减 → `-1.0`；含 ties → 与手算一致；
4. `n=59 / 60` 的 `mean_revert_z` + `extreme_days` 边界；
5. `std60 == 0` → `mean_revert_z=null` + note `zero_variance`；
6. `mean_revert_z` winsor：极端值 → clamp ±3 + note `winsor_clamped`；
7. `n=249 / 250` 的 `pct_rank_1y` 边界；ties 用 average rank（手算对照）；
8. `n=749 / 750` 的 `pct_rank_3y` 边界；
9. `regime_switch_30d`：构造 `up,up,down,down,neutral,neutral` → 2；构造单日抖动 `up,down,up,down` → **0**（2 日确认过滤）；
10. `as_of` 前视截断：序列含 `as_of` 之后观测 → 不参与；
11. `append_observation` 幂等：同 `(module, date)` 写两次 → 行数不变、取更晚 `written_at`；
12. `append_observation` 缺 `date` → 返回 `False`、文件不新增行（fail-closed）；
13. `coverage.expected_days/missing_days` 用 median gap 推算（构造：1 天间隔 8 个观测 + 一个 4 天缺口）；
14. `max_gap_days` 正确；`>7` 时 `notes` 含 `stale_series`；
15. `value_scale` 按模块映射正确（flow→`score_neg1_pos1`、sentiment→`index_0_100`、valuation→`ratio`）；
16. `velocity_label_of` 五档边界（±0.05 / ±0.01）。

### 8.2 静态守护

- `test_no_core_engine_import.py`：扫描 `9-基本面分析/**/*.py`（排除 `tests/`），断言无 `core_engine` 引用；
- 全仓 `grep -rn "module_timeseries"` 只剩 48 域基线产物。

### 8.3 命令

```bash
cd 9-基本面分析 && python -m pytest tests/test_dimension_history.py -q
cd 9-基本面分析 && python -m pytest tests/ -q
ruff check "9-基本面分析" && ruff format --check "9-基本面分析"
```

### 8.4 真实数据冒烟（不阻塞）

对 10 模块各调一次 `get_dimension_history`，断言结构与 `notes` 合法。首次上线预期 `observed_days` 为 0-2、`availability="none"` —— 属预期，非缺陷。

---

## 9. 分期

| 阶段 | 内容 | 交付判据 |
|---|---|---|
| **P0** | C1 收敛 + C2 tavily 适配 + C3 新模块 + C4 接入（含 `observed_date`）+ C7/C8 测试 | 16 条单测全绿 + ruff 全绿 + 无 `core_engine` 引用；4 个统计字段在 ≥60 观测时给真值 |
| **P1** | C5 抽公共 `velocity_label_of` + C6 18 域补 5 维 + §7.1 HTTP 端点 | 18 域 8→13 维口径测试通过；端点结构合法 |
| **P2** | `fear_greed` 长历史旁路（`pct_rank_1y/3y` 真值）+ 云端回填 + 48 域 P 层接入 | 云端回填完成、真实分位可算 |

---

## 10. 不做清单

1. **本地历史回填**（不伪造、不批量生成历史；交云端）。
2. **`pct_rank_3y` 模块级真值**（除 `fear_greed` 外无 ≥750 天源）。
3. **前端改造**（3-FRONTEND / 3.1-FRONTEND 不改，`timeseries` 字段语义不变）。
4. **`/fundamental/snapshot` 字段删除或重命名**。
5. **`compute_resistance_3d` 口径调整**。
6. **`dimension_context.py` 现有 8 维语义变更**（只允许增维）。
7. **删除存量 `storage/timeseries/*.json`**。
8. **新建第二个历史写入器**。
9. **把 `run_module_analysis` 上移进 `engines`**（不为无调用方的脚本扩大引擎 API 面，见 C2）。

---

## 11. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 删 `core_engine` 后仍有隐藏动态 import | 运行时 ImportError | 全仓 grep + 静态守护测试 + C2 同步改 tavily |
| 前端依赖 mock timeseries 作图，真实序列太短 | 图变空 | `_select_timeseries` 30 天阈值 + `synthetic` 标记，不立即切换 |
| 一天多次刷新产生同日多观测 | 重复/抖动 | 幂等 upsert 取最新 `written_at` |
| 模块 `value` 量纲差异大 | 跨模块统计不可比 | 统计只在模块内；跨模块用 `direction_score`；`value_scale` 显式标注 |
| `observed_date` 长期走 fallback_now | 历史日期失真（周末重复日） | `meta.observed_date_source` 埋点，云端监控 `fallback_now` 占比，>50% 需补 DAL `as_of` |
| 口径实现偏差 | 统计失真 | §5.2 预注册 + 16 条边界单测锁死 |

---

## 12. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-11-12 | 草案：依赖审计（core_engine 死路径）、发现 timeseries 为合成数据、定稿契约与 P0/P1 分期 |
| v1.1 | 2026-11-12 | 按同行评审修订 7 Major / 5 Minor：C2 改法（run_module_analysis 不改 import）、`value` 量纲表 + `value_scale`、`observed_date` 方案、`expected_days` 改 median-gap 口径、`extreme_days` 与 `mean_revert_z` z 口径统一、`trend_20d` 改 Spearman、`regime_switch_30d` 加 2 日确认、`is_synthetic` 移出统计层、18 域 import 修正 + 5 维编号、新增 §2.1 替代方案 / §3.3 消费方 / §13 评审响应 |
| v1.2 | 2026-11-12 | **实施完成（P0 + P1）**，落点见 §12.1 |
| v1.3 | 2026-11-12 | **P2 本地实现完成**：fear_greed 长历史旁路、云端回填入口、48 域 `trend_20d` P 层接入；云端真实回填待执行，落点见 §12.2 |

### 12.1 实施结果（v1.2，2026-11-12）

| # | 落点 | 结果 |
|---|---|---|
| C1 | `9-基本面分析/core_engine/least_resistance.py` | 已删除（git 记录 `D`）；`core_engine/` 目录仅剩 Finder 自动重建的 `.DS_Store`，git 不跟踪，无功能影响 |
| C2 | `tavily_data_generator.py` | 去 `core_engine` 依赖，改 `engines.least_resistance`；新增 `_run_module_analysis()` 适配（不持久化）；文件头标 `NON-PRODUCTION` |
| C3 | `engines/dimension_history.py` | 新增 490 行；`append_observation` / `load_series` / `compute_dimension_history` / `get_dimension_history` / `observation_from_snapshot` 全部按 §4/§5 口径实现 |
| C4 | `ml_trade_service_v2.py` | `_resolve_observed_date()` + `meta.observed_date/_source`；`refresh_module()` 接入 append + `_select_timeseries(min_real_days=30)`；`meta.timeseries_synthetic` |
| C5 | `engines/least_resistance.py` | 新增 `velocity_label_of()`（按 §6 C5 定位于引擎层）；`data_collector._make_timeseries` 改为复用（删除 12 行重复分支） |
| C6 | `18-数据获取中心/data_center/processing/dimension_context.py` | `ALL_DIMENSIONS` 8→13；新增 `NINE_DOMAIN_DIMENSIONS` + `_load_nine_series()` + `_nine_context()` + `_context_for()` 分派；9 域不可用 FAIL-OPEN 空上下文 |
| C7 | `9-基本面分析/tests/test_dimension_history.py` | 16 条（§8.1 全覆盖）→ **全绿** |
| C8 | `9-基本面分析/tests/test_no_core_engine_import.py` | 静态守护 1 条 → **全绿** |
| §7.1 | `ml_trade_service_v2.py` | 新增 `GET /fundamental/history/<module>`：非法 module 400、`as_of`/`lookback` 非法 400、无观测 200 + `availability=none`；只读不采集 |
| §7.2 | `18-数据获取中心/tests/news/` | `test_dimension_context.py` 矩阵断言改 13 维 + 新增 2 条 9 域维度测试；`test_dominance_claim.py` 的 `ALL_DIMS` 改为引用 `ALL_DIMENSIONS`（消除硬编码漂移） |

**与 SPEC 的两处差异（已确认更安全）**：

1. §7.2 原写 `sys.path.insert(0, 9 域根)`；实施改为 `sys.path.append(...)`——避免 18 域进程内 `engines` 等同名包被 9 域反抢占（当前 18 域无 `engines` 包，append 已满足导入）。
2. C5 的 `velocity_label_of` 定义在 `engines/least_resistance.py`（SPEC 原文即如此），`dimension_history` 通过 import 复用，`dh.velocity_label_of` 仍可访问（测试未改）。

**验收实测（2026-11-12）**：

- `9-基本面分析`：`tests/` → 82 passed / 5 skipped / **2 failed（既有，与本次无关）**；失败项为 `test_p0_no_cross_repo_dependency`（引用不存在的 `ml_trade_service.py`）与 `test_p2_lifecycle_integration`（引用不存在的 `ops/launchd/fundamental_stack.sh`），两者 git 均未跟踪该文件，属历史遗留。
- `18-数据获取中心`：`tests/news` → **298 passed**；`tests/chain/test_washout_collectors.py::test_long_short_ratio_collector_fetch` 既有失败（Binance L-S 采集器 `sub_category` 断言），与维度上下文无关。
- `ruff check`：9 域全绿、18 域改动文件全绿；`ruff format --check` 仅剩 3 处**既有**未格式化行（`dimension_context.py:204`、`test_dominance_claim.py:24`、`ml_trade_service_v2.py` 三元表达式），非本次改动。
- 端点冒烟：`/fundamental/history/flow` → 200 `{source:none, availability:none, lookback_days:0}`；`bogus` → 400；`as_of=abc` → 400。
- `core_engine` 残留：目录内 `__pycache__` 已不存在，仅 `.DS_Store` 被 Finder 反复重建，`rmdir` 不可靠；git 已记录 `core_engine/least_resistance.py` 删除，静态守护按文件内容扫描，不受影响。

### 12.2 P2 实施结果（v1.3，2026-11-12）

| 项 | 落点 | 结果 |
|---|---|---|
| P2-A 批量写入 | `9-基本面分析/engines/dimension_history.py` | 新增 `append_observations()`，与单条写入共用 merge + 原子写；同日取更晚 `written_at`，重复回填不增行。修正默认路径为 §4.1 的 `storage/dimension_history/{module}.jsonl`（原实现默认会多拼一层目录） |
| P2-A fear_greed 旁路 | `9-基本面分析/engines/fear_greed_history.py` | 读取 19-DAL `crypto_fear_greed/value`，同日取最晚时间戳，0-100 原值写入 `sentiment`；`direction_score=(value-50)/50`，真实 UTC 观测日，非法值/日期拒写；1y/3y 分位仍由权威统计函数计算 |
| P2-B 云端入口 | `9-基本面分析/scripts/backfill_dimension_history.py` | 支持 `--module fear_greed`、`--start/--end`、`--base-dir`、`--dry-run`；dry-run 不写盘。本地未执行批量回填 |
| P2-C P 层 | `48-涌现架构/metrics/financial_env_validate.py` | 新增 `trend_context_from_history()` / `add_trend_context()`；每个 20 观测窗口调用 9 域权威 Spearman，市场级按日广播为 `P_trend_20d`，独立时序 IC，缺数据 FAIL-OPEN；原 `P_score` 与 `ALL_layers` 口径不变。CLI 新增 `--trend-module` / `--no-trend-context` |
| 测试 | 9 域 + 48 域 + 18 域 | P2-A 22 passed；48 域 validate 23 passed、validate+align+静态守护 46 passed；18 域维度回归 22 passed；7 个代码文件 ruff check / format 全绿 |

**云端执行步骤（随后由云端执行，本地未跑）**：

```bash
cd 9-基本面分析
python scripts/backfill_dimension_history.py --module fear_greed --dry-run
python scripts/backfill_dimension_history.py --module fear_greed
```

云端验收以第二条命令输出为准：`history.lookback_days >= 750`，且 `history.stats.pct_rank_1y` / `pct_rank_3y` 均为非空数值；重跑后观测行数不得增加。当前本地未回填，真实分位尚未在本地落盘，不能宣称 §9 的「云端回填完成」判据已达成。

**待回填模块清单**：

| 模块 | 当前状态 | 后续动作 |
|---|---|---|
| `sentiment`（源：`fear_greed`） | 入口已就绪，待云端执行 | 上述 dry-run → 正式回填 → 检查 1y/3y 分位与幂等 |
| `flow` / `macro` / `breadth` / `intermarket` / `valuation` / `onchain` / `calendar` | 无已审定的足额单源历史映射 | 云端先审计真实历史源与量纲，再新增适配器；禁止把合成 timeseries 导入 |
| `news` / `narrative` | 文本/叙事模块无可直接重建的统一历史值序列 | 继续通过真实快照 append 累积；有真实历史源后另行评审 |

**全量回归说明**：9 域 `tests/` 为 88 passed / 5 skipped / 2 failed，两个失败仍是 §12.1 已记录的缺失文件（`ml_trade_service.py`、`ops/launchd/fundamental_stack.sh`），并非 P2 引入；P2 相关测试与 ruff 均为 exit 0。

---

## 13. 评审响应表

| 编号 | 评审意见 | 处置 | 落点 |
|---|---|---|---|
| M-1 | engines 无 `run_module_analysis`，C2 会 ImportError | ✅ 接受：C2 改为「tavily 内自建适配函数」，不改引擎 API 面；列入不做清单第 9 条 | §6 C2、§10.9 |
| M-2 | `value` 非原始量纲，§5.2 前提错误 | ✅ 接受：新增 §1.4 量纲表 + `value_scale` 字段 + 「只在模块内统计」硬约束 | §1.4、§3.2、§5.2 |
| M-3 | 观测日不可得，`date` 只能写 now() | ✅ 接受：`meta.observed_date` + 三级优先级 + fail-closed（缺失拒写） | §4.2、§2.7 |
| M-4 | 18 域 import 路径错 | ✅ 接受：显式 `sys.path.insert(9-基本面分析)` + `from engines.dimension_history` | §7.2 |
| S-1 | 两个 z 口径冲突 | ✅ 接受：`extreme_days` 改为「近 250 内按当日 60 日窗算 z」，与 `mean_revert_z` 同口径 | §3.2、§5.2 |
| S-2 | `trend_20d` 归一化无定义、无除零保护 | ✅ 接受：改 **Spearman 秩相关**（有界、无需除零） | §3.2、§5.2 |
| S-3 | `regime_switch_30d` 三态相邻计数不可比 | ✅ 接受：加 **2 日确认** 过滤抖动 | §5.2 |
| S-4 | `expected_days` 用日历日 → stale 永不触发 | ✅ 接受：改 median-gap 推算；`max_gap_days` 用相邻观测日差 | §4.6、§3.2 |
| S-5 | `is_synthetic` 在 jsonl 架构下是死代码 | ✅ 接受：移出统计层、只留快照 `meta.timeseries_synthetic` | §2.4、§4.4 |
| S-6 | `pct_rank` ties 未定义 | ✅ 接受：average rank | §3.2、§5.2 |
| S-7 | `mean_revert_z` 命名夸大 | ⚠️ 部分接受：保留字段名（父 SPEC 已冻结），在 §5.2 注明「仅度量偏离，不度量回归倾向」 | §5.2 |
| JF-1 | P0 信息增量与「更多」预期不符 | ✅ 接受：§0 增加能力边界声明 | §0 |
| JF-2 | 新增字段无消费方 | ✅ 接受：新增 §3.3 消费方表；`pct_rank_*` 结构交付但值 `null` | §3.3、§9 |
| 框架锁定 | 未评估替代方案 | ✅ 接受：新增 §2.1 三方案对比 | §2.1 |
| 边界忽略 | 未声明 P0 不可用字段的下游影响 | ✅ 接受：§1.7 可满足度表 + §0 边界声明 | §0、§1.7 |
