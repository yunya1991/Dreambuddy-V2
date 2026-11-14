# SPEC-M4: 48 信号消费与 40 因子先验接入（50-NN主矛盾评估器）

> 版本：v0.7
> 日期：2026-11-14
> 状态：🟢 Q1-Q7 裁决完成；M4-2 接线、M4-3 五快照验收、M4-4 小额实盘灰度**已部署云端并首轮验证**（coef 0.10 / 单笔 ≤100 USDT / attribution 归因）
> 归属：50-NN主矛盾评估器（改动仅限 50 域）
> 上游：48 涌现架构 `metrics/nn_feedback_gateway.py` → `events/nn_feedback/40_feedback.json` → 40 `factor_contradiction_priors.json`
> 关联：SPEC-M1（神经传递打通）、SPEC-M2（宏观力传导）、SPEC-M3（调度器与共振传感器）、48 `SPEC-NN-FEEDBACK-GATEWAY-v0.1.md`、48 `SPEC-EMERGENCE-FULL-CHAIN-v1.0.md`

---

## 零 · 背景与问题

### 0.1 当前链路

```text
48 nn_feedback_gateway
  └─ events/nn_feedback/40_feedback.json
       ├─ gateway_version / data_version / source_window
       ├─ factor_priors（18 事件先验，10 因子，list）
       ├─ direction_priors（按 symbol 的 long/short/neutral 计数）
       ├─ contradiction_priors（矛盾类型计数）
       ├─ training_suggestions（建议制，advisory_only=true）
       └─ quality（join_coverage 等）
            ↓（40 侧消费 / 聚合）
40 factor_contradiction_priors.json
  └─ factor_direction_priors.{n_samples, factors{name → {dominant_direction, total_weight}}}
     contradiction_priors.{n_events, by_contradiction_type}
            ↓（50 侧，本 SPEC 定义）
50 make_decision
```

### 0.2 问题

50 侧当前对 40 先验只有**审计挂载**：

- `tools/run_shadow.py` 调 `adapters/prior_reader.load_priors_summary()`，只取 top5 因子，写入 `decision.payload["priors_40"]`；
- 该字段不参与 `path_synthesis` / `w4.adjudicate`，对 direction、confidence、position 无任何数值影响；
- 即 48 经 40 传下来的因子方向共识，在 50 决策中**不产生作用**。

### 0.3 本 SPEC 目标

把 `priors_40` 升级为**受控参与 50 决策计算**：

1. 定义 48→40→50 的消费契约与版本约束（50 不直连 48）；
2. 定义因子先验 → path 的映射与调制规则（已在 `core/factor_priors_overlay.py` 实现）；
3. 用真实数据实测影响面，**预注册 overlay 系数**，禁止运行时自适应；
4. 明确门禁、降级、观测与回滚；
5. 明确**不做的事**：本 SPEC 不改 40 决策函数、不消费 `training_suggestions`。

---

## 一 · 范围与边界

### 1.1 范围内

| 项 | 内容 |
|---|---|
| 输入 | 40 `factor_contradiction_priors.json`（`factor_direction_priors.factors`） |
| 接入点 | `synthesize_paths` 与 `_apply_regime_overlay` 之后、`w4.adjudicate` 之前 |
| 计算 | `core/factor_priors_overlay.apply_factor_priors_overlay()` |
| 系数 | 预注册常量，首轮候选集见 §5 |
| 观测 | decision payload 增 `factor_priors_overlay` 审计块 |
| 验收 | 单测 + differential harness 指标 |

### 1.2 范围外（明确不做）

| 不做 | 原因 |
|---|---|
| 50 直读 48 `40_feedback.json` | 48 不是 50 的直接上游；跨层直连会绕过 40 的聚合与 P5 门禁 |
| 消费 `training_suggestions` | 48 标注 `advisory_only=true`，且 50 TrainingGate 只接受 weights/strategy/macro 三类；属 40/50 训练链路，另开 SPEC |
| 改 40 决策函数 | 触碰周期主链与 P5 预注册红线（矛盾事件≥200、语义事件≥1000、x1_ready） |
| 改 50 TrainingGate 白名单 | 本 SPEC 不涉及训练建议 |
| 运行时自适应系数 | 禁止；系数必须预注册、可回滚 |
| 改 `path.direction` | overlay 只调 `confidence`，不重新定向 |

---

## 二 · 输入契约

### 2.1 必读字段

`40-周期神经网络系统/factor_contradiction_priors.json`：

```json
{
  "schema_version": "factor_contradiction_priors.v0.1",
  "generated_at": "<ISO8601>",
  "factor_direction_priors": {
    "n_samples": 396,
    "factors": {
      "<prefix>.<name>": {
        "dominant_direction": "bullish|bearish",
        "total_weight": 16.0
      }
    }
  },
  "contradiction_priors": {
    "n_events": 1048,
    "by_contradiction_type": {"individual_whole": 1048, "short_long": 170, "macro_micro": 158}
  }
}
```

- 50 **只消费** `factor_direction_priors.factors`；其余字段仅入审计。
- 单条因子缺 `dominant_direction` 或 `total_weight<=0` → 忽略该因子，不报错。
- 未知前缀 → 忽略（计入 `unmapped_factor_count` 审计）。

### 2.2 上游溯源字段（审计用，不参与计算）

从 48 `40_feedback.json` 透传（由 40 聚合或 50 侧旁路读取均可，本 SPEC 采用 50 侧只读旁路，fail-open）：

| 字段 | 用途 |
|---|---|
| `gateway_version` | 契约版本核对 |
| `data_version` | 同一数据版本内结果可复现；版本变化必须重跑 harness |
| `source_window.{n_events,first_ts,last_ts}` | 样本窗口审计 |
| `quality.join_coverage` | 先验可信度提示；当前实测为 0.0，Q5 裁决：**仅告警不阻断** |

### 2.3 新鲜度与样本量门槛

- `generated_at` 超过 **7 天** → 视为陈旧：overlay 不生效（等价 coef=0），审计 `degraded=stale_priors`。
- `generated_at` 缺失 → 同样按陈旧处理，不猜默认值。
- `factor_direction_priors.n_samples < 200` → overlay 不生效，审计 `degraded=insufficient_samples`（Q4 裁决）。
- 不引入真实时间依赖到纯函数；判定由调用方（`run_shadow` / `make_decision`）完成并传入结果。

---

## 三 · 映射与计算规则

### 3.1 因子前缀 → dimension 映射

与 50 现有 `SOURCE_DIM_MAP` 对齐：

| 因子前缀 | 目标 dimension | 依据 |
|---|---|---|
| `macro.*` | `D1` | 40-cycle / 43-strategic / 40-divergence / 40-resonance 均映射 D1 |
| `technical.*` | `D3` | 11-bcrm / 11-washout / 11-bcrm-tactical 均映射 D3 |
| `flow.*` | `D3` | Q1 裁决：暂并战术维，不新开 D2（D2 当前无源，单列会造成空壳维） |
| `event.*` | `C7` | Q2 裁决：首轮仅 C7，NEWS 单独评估，避免事件先验被双计放大 |
| `sentiment.*` | `NEWS` | 情绪/叙事维 |
| `onchain.*` | **不映射（丢弃 + 审计）** | Q7 裁决：50 无链上语义维（C6=估值、D1=宏观利率、D3=技术），且 D2 当前 0 path；映射任一现有维均为语义污染且零效果。详见 §8 Q7 |
| 其他 | 丢弃 | 审计 `unmapped_factor_count` |

### 3.2 方向归一

```text
bullish → long
bearish → short
long / short → 原样
其他 / 缺失 → 丢弃
```

### 3.3 净强度

对某 dimension 的全部命中因子：

```text
strength(dim, path_dir) = Σ(weight × sign) / Σ(weight)
其中 sign = +1 若因子方向 == path_dir，否则 -1
strength ∈ [-1, 1]；无命中 → 0
```

### 3.4 调制

```text
coef     = clamp(输入系数, 0, MAX_COEF)     # MAX_COEF = 0.5，仅代码绝对截断
factor   = 1 + coef × strength
new_conf = clamp01(path.confidence × factor)
```

不变量：

| 条件 | 行为 |
|---|---|
| `coef == 0` | 原样返回（严格等于基线） |
| 先验为空 / 全部未映射 | 原样返回 |
| `path.direction not in (long, short)` | 该 path 不调制 |
| 原对象 | 不修改（`dataclasses.replace`） |
| 输出 | 新 list，顺序与输入一致 |

---

## 四 · 实测影响面（系数预注册依据）

### 4.1 实验设置

| 项 | 值 |
|---|---|
| 总线快照 | `42-神经网络交易协调层/runtime/bus_state.json`，`generated_at=2026-11-12T15:45:01Z` |
| evidence | 46 条 |
| path | 39 条 |
| 因子 | 34 个真实因子（`n_samples=396`） |
| 覆盖 dimension | D1 / D3 / C7 / NEWS |
| 时间基准 | 固定 `now = bus.generated_at`，保证可复现 |
| 路径 | `load_evidences → synthesize_paths → overlay → w4.adjudicate` |

基线：

```text
direction=long  total=0.642135  force=0.742839
impact=0.874998 raw_position=82.1068  resonance=true  dominant=true
```

每个非零系数均调制 **33/39 paths（84.62%）**；`path_direction_flips` 恒为 0（因 overlay 只改 confidence）。`divergence_rate=84.62%` 是 path 字段差异率，**不得**解读为决策方向分歧率。

> v0.2 复跑说明：Q2 裁决将 `event.*` 从 `C7+NEWS` 收窄为仅 `C7` 后，已重跑正/反两组扫描。由于当前快照没有可被事件先验调制的 NEWS 方向性 path，两组数据与 v0.1 **完全一致**。该收窄是规范性约束，用于防止未来 NEWS path 出现时事件先验被双计。

### 4.2 正向（真实先验，D3 全 bullish）

| coef | Δtotal | Δforce | Δraw_position | 决策翻转 |
|---:|---:|---:|---:|---|
| 0.00 | 0 | 0 | 0 | 无 |
| 0.05 | +0.006481 | +0.016201 | +0.3240 | 无 |
| 0.10 | +0.012302 | +0.030755 | +0.6151 | 无 |
| 0.15 | +0.017604 | +0.044010 | +0.8802 | 无 |
| 0.20 | +0.022701 | +0.056751 | +1.1350 | 无 |
| 0.30 | +0.032109 | +0.080271 | +1.6054 | 无 |
| 0.50 | +0.050558 | +0.126393 | +2.5279 | 无 |

### 4.3 反向压力（34 因子全部反向，构造场景）

| coef | Δtotal | Δforce | Δraw_position | force 终值 | 决策翻转 |
|---:|---:|---:|---:|---:|---|
| 0.05 | -0.007103 | -0.017758 | -0.3552 | 0.725081 | 无 |
| 0.10 | -0.014243 | -0.035609 | -0.7122 | 0.707230 | 无 |
| 0.15 | -0.021397 | -0.053493 | -1.0699 | 0.689346 | 无 |
| 0.20 | -0.028377 | -0.070944 | -1.4189 | 0.671895 | 无 |
| 0.30 | -0.042573 | -0.106434 | -2.1287 | 0.636405 | **resonance: true→false**（total=0.599562） |
| 0.50 | -0.075467 | -0.188670 | -3.7734 | **0.554169** | resonance=false；force 距 0.5 仅 0.054169 |

### 4.4 由实测导出的三条结论

1. **Δtotal 与 coef 近似线性**，没有非线性放大；系数每 +0.05，仓位约 ±0.35 个百分点。
2. **首轮安全边界在 0.20**：正向与反向均未出现 direction / resonance / dominant 翻转。
3. **0.30 已越界**：反向压力下关闭 resonance；0.50 时 force 逼近方向翻转线。因此 0.50 只能作为代码截断，不得作为生产候选。

### 4.5 证据边界（必须写入评审结论）

- 仅 1 个真实快照，反向场景为合成；**不能**据此估计总体翻转率或跨 regime 稳定性。
- `raw_position` 未经过 `constraint_loader.clamp_position`，不等于最终 `position_pct`。
- `quality.join_coverage=0.0`，先验与决策的可 join 性尚未验证。
- 未纳入 dominance / 执行权 / 实际成交链路。

---

## 五 · 系数预注册

### 5.1 常量

| 常量 | 值 | 说明 |
|---|---|---|
| `ENABLE_50_FACTOR_PRIORS_OVERLAY` | `0`（默认关） | 关时等价 coef=0，路径与当前生产一致 |
| `FACTOR_PRIORS_COEF_DEFAULT` | `0.10` | 首轮 shadow 默认 |
| `FACTOR_PRIORS_COEF_CANDIDATES` | `{0.00, 0.05, 0.10, 0.15, 0.20}` | 首轮允许取值集合 |
| `FACTOR_PRIORS_COEF_CEILING` | `0.20` | 首轮生产上限 |
| `MIN_N_SAMPLES` | `200` | 先验样本量下限，低于则 no-op（Q4 裁决） |
| `MAX_COEF` | `0.50` | 代码绝对截断，非生产许可 |
| `50_LIVE_NOTIONAL_USDT` | `100` | M4-4 小额验证：50 侧声明的单笔名义上限（22 取 min(13 定容, 本值)，只降不升）。默认对齐 22 非指数类下限 100 USDT；低于 minSz 会产生 `size_zero` 拒单 |
| `50_LIVE_FACTOR_PRIORS` | `on` | M4-4 live 通道 overlay 默认开启；`off` 等价回滚（shadow 通道仍默认关） |

### 5.2 规则

- 运行时系数只能取 `FACTOR_PRIORS_COEF_CANDIDATES` 中的值；集合外取值直接拒绝并回落默认值，审计 `invalid_coef`。
- 禁止按近期表现、PnL、胜率自适应调系数。
- 升档（如 0.20→0.30）必须：新增多快照实测 → 出影响面报告 → 改本 SPEC 版本 → 评审通过。

---

## 六 · 接入与观测

### 6.1 调用顺序

```python
paths = synthesize_paths(evidences, now=moment)
paths = _apply_regime_overlay(paths, regime_overlay)
# 新增：先验 overlay（开关关闭 / 先验陈旧 / 缺文件时为 no-op）
paths = maybe_apply_factor_priors_overlay(paths, now=moment)   # 50 侧适配层
w4 = adjudicate(paths, reconciliation)
```

### 6.2 审计块

`decision.payload.factor_priors_overlay`：

```json
{
  "enabled": true,
  "coef": 0.10,
  "coef_source": "default|candidate|rejected",
  "priors_path": "40-周期神经网络系统/factor_contradiction_priors.json",
  "priors_generated_at": "2026-11-11T05:47:25Z",
  "priors_schema_version": "factor_contradiction_priors.v0.1",
  "priors_n_samples": 396,
  "priors_data_version": null,
  "modulated_paths": 33,
  "total_paths": 39,
  "modulation_rate": 0.8462,
  "unmapped_factor_count": 0,
  "degraded": []
}
```

`degraded` 取值：`stale_priors` / `missing_priors` / `invalid_coef` / `empty_factors` / `insufficient_samples`。

### 6.3 降级（FAIL-OPEN）

| 场景 | 行为 |
|---|---|
| 文件缺失 | overlay no-op，`degraded=missing_priors`，决策照常 |
| 解析失败 | 同上，记 warning |
| 先验陈旧 | no-op，`degraded=stale_priors` |
| 因子表为空 | no-op，`degraded=empty_factors` |
| `n_samples < 200` | no-op，`degraded=insufficient_samples` |
| 开关关闭 | no-op，不写审计块或 `enabled=false` |
| overlay 抛异常 | 捕获并回退原始 paths，决策照常 |

不得因先验异常中断决策，也不得用默认先验冒充真实先验。

### 6.4 M4-2 接线验证（2026-11-14）

适配层：`adapters/factor_priors_provider.py`；接线点：`make_decision`、`make_shadow_decision`、`build_symbol_decisions`（同一批 path 共用一次 overlay，避免双重口径）。

同一总线快照（`generated_at=2026-11-12T15:45:01Z`，39 paths，`n_samples=396`）：

| 场景 | direction | confidence | 审计摘要 |
|---|---|---|---|
| 开关关闭（默认） | long | 0.642135 | `enabled=false`，`modulated_paths=0` |
| 开启 + coef=0.20 | long | 0.664836 | `coef_source=candidate`，`modulated 33/39`，`rate=0.8462` |

- ON 相对 OFF 的 `Δconfidence=+0.022701`，与 §4.2 探针结果一致，接线无额外放大。
- `degraded=[]`，无降级触发。
- `unmapped_factor_count=3`：`onchain.hashrate` / `onchain.tvl` / `onchain.active_addr`。Q7 已裁决**保持未映射**（见 §8 Q7），当前行为即最终行为，无需改代码。
- **shadow 组合级未变化**（`confidence=1.0`、`position_pct=55.0`）：shadow 置信度 `sum(|conf×expected_return|)` 已饱和到 1.0，overlay 提升被截断；实际数值影响体现在 `make_decision` 与 per-symbol path 明细中。这是已知观测边界，不表示接线失效。

---

## 七 · 验收

### 7.1 单测（已具备，12 项）

文件：`tests/test_factor_priors_overlay.py`。覆盖一致性提升、反向降低、未命中不变、neutral 跳过、clamp、系数截断、方向归一、混合净强度、不可变性、决策阈值状态透出。

### 7.2 differential 验收指标

工具：`tools/priors_differential_probe.py`（复用 `tools/differential_harness.diff_path_sets`）。

| 指标 | 阈值 |
|---|---|
| coef=0 与基线逐字段一致 | 必须 100% 一致 |
| coef=0.20 反向压力 `\|Δtotal\|` | ≤ 0.03 |
| coef=0.20 反向压力 `direction` 翻转 | 必须 0 |
| coef=0.20 反向压力 `resonance` / `dominant` 翻转 | 必须 0 |
| 调制率 | 记录，不设阈值 |
| 单次运行耗时 | ≤ 2s |

> `priors_data_version` 当前恒为 null：50 直读 40 `factor_contradiction_priors.json`，该文件只带 `schema_version + generated_at`。48 `40_feedback.json` 的 `data_version` 需额外旁路读取，未纳入 M4-2 范围；可复现标识暂用 `schema_version + generated_at` 组合。

### 7.3 M4-3 实测结果（5 快照）

快照来源：`42-神经网络交易协调层/runtime/bus_state.json` 的 git 历史版本；先验固定为当前 40 产物（`generated_at=2026-11-11T05:47:25Z`，`n_samples=396`）。

| 快照日期 | evidence | paths | 基线方向 | 正向 Δtotal@0.20 | 反向 Δtotal@0.20 | 翻转 | 判定 |
|---|---|---:|---|---:|---:|---|---|
| 2026-11-12 | 46 | 39 | long | +0.022701 | -0.028377 | 无 | PASS |
| 2026-11-10 | 45 | 36 | long | +0.015747 | -0.019408 | 无 | PASS |
| 2026-11-09 | 42 | 34 | long | +0.017493 | -0.022177 | 无 | PASS |
| 2026-11-08 | 40 | 33 | long | +0.021743 | -0.025538 | 无 | PASS |
| 2026-10-29 | 10 | 5 | short | 0.000000 | 0.000000 | 无 | 受限 |

判定汇总：

| 验收项 | 结果 |
|---|---|
| coef=0 与基线逐字段一致 | ✅ 5/5 |
| coef=0.20 `max \|Δtotal\| ≤ 0.03` | ✅ 0.028377 |
| coef=0.20 direction/resonance/dominant 翻转 | ✅ 0 次 |
| ≥3 个不同日期 | ✅ 5 个 |
| 至少 1 个 short 方向快照 | ⚠️ 受限（形式满足，实质未验证） |

**short 覆盖缺口**：2026-10-29 快照的 5 条 path 全部位于 `C6`（估值维），其中 4 条 neutral、1 条 short；overlay 只调制 long/short 且 C6 无因子映射，因此调制数为 0。方向上覆盖了 short，但**对称性未被真正验证**。Q7 裁决（onchain 不映射 C6）与此现象一致，不构成新增缺陷。

**高系数边界复核（反向压力）**：

| 快照 | coef=0.30 total | coef=0.30 resonance | coef=0.50 resonance |
|---|---:|---|---|
| 11-12 | 0.599562 | **翻转（跌破 0.6）** | 翻转 |
| 11-09 | 0.621950 | 未翻转（贴近 0.6） | **翻转** |
| 11-08 | 0.614727 | 未翻转 | **翻转** |
| 11-10 | 0.653921 | 未翻转 | 未翻转 |

- 反向 0.30 在 1/4 long 快照触发共振翻转，另 2 个快照跌破或贴近 0.6 → **0.30 明确越界**。
- 反向 0.50 在 3/4 long 快照触发翻转 → 0.50 仅可作代码截断。
- `direction` 在所有快照、所有系数下均未翻转。
- 结论：首轮上限 **0.20** 得到多快照支撑，维持不变。

**证据边界（必须随报告声明）**：

1. 历史快照搭配的是 2026-11-11 的最新先验，**不是同期数据**，存在前视偏差；本验收只验证系数敏感性与阈值稳定性，不做收益归因。
2. 2026-10-29 快照仅 10 条 evidence、5 条 path，样本质量低，只用于方向覆盖说明。
3. 未经过 `clamp_position`、执行权与成交链路。

### 7.4 数据集要求

- 验收至少 **3 个不同日期的 bus 快照**（M4-3 已用 5 个：10-29、11-08、11-09、11-10、11-12）。
- 至少 1 个快照的方向为 `short`，验证对称性（当前仅形式满足，见 §7.3 缺口）。
- 快照日期与先验 `schema_version + generated_at` 必须留档；`data_version` 待 48 旁路接入后补充。

### 7.5 回滚

- 开关 `ENABLE_50_FACTOR_PRIORS_OVERLAY=0` 立即回退；
- 回退判据：连续 3 个交易日出现 `direction` 或 `resonance` 非预期翻转，或 overlay 导致 shadow 决策分布显著偏移（|Δposition| 均值 > 2）。
- 回滚不删除代码，仅关闭开关并保留审计。
- **M4-4 实盘回滚（三级，任一即可）**：
  1. `python3 tools/run_live.py --factor-priors off`（仅 live 关闭，shadow 不受影响）；
  2. `50_KILL_SWITCH=1`（run_live 与 22 执行器同步停摆）；
  3. `22_LIVE_KILL_SWITCH=1`（仅停执行，保留 50 决策留档）。
- 已成交仓位不因回滚自动平仓，按 22 既有 SL/TP 与冷静期规则处理。

---

## 八 · 裁决记录

| # | 问题 | 裁决 | 落地位置 |
|---|---|---|---|
| Q1 | `flow.*` 是否单列 dimension | **并入 D3**，不新开 D2 | §3.1；`FACTOR_PREFIX_DIM_MAP` |
| Q2 | `event.*` 是否双映射 | **首轮仅 C7**，NEWS 单独评估 | §3.1；`FACTOR_PREFIX_DIM_MAP`；新增单测 |
| Q3 | 首轮默认系数 | **0.10** | §5.1 `FACTOR_PRIORS_COEF_DEFAULT` |
| Q4 | 是否设 `n_samples` 下限 | **200**，低于则 no-op | §2.3 / §5.1 / §6.3；`MIN_N_SAMPLES` |
| Q5 | `join_coverage=0.0` 是否阻断 | **仅告警不阻断** | §2.2 |
| Q6 | 是否消费 48 `direction_priors` | **不消费** | §1.2 范围外 |
| Q7 | `onchain.*`（3 因子）映射 | **不映射，保持丢弃 + 审计**（首轮）；禁止映射到 C6/D1/D3；D2 待有链上证据源后再评估 | §3.1；`unmapped_factor_count` 审计 |

> 裁决后代码与文档一致性：`event.* → C7` 与 `MIN_N_SAMPLES=200` 已在 `core/factor_priors_overlay.py` 落地，overlay 14 项 + 适配层 8 项共 22 项单测通过；正/反实测复跑数据不变（见 §4.1 说明）。

---

## 九 · 里程碑

| 阶段 | 内容 | 交付 |
|---|---|---|
| M4-1 | 评审本 SPEC，裁决 §8 Q1-Q6 | ✅ 已完成（v0.2 定稿） |
| M4-2 | 50 侧适配层 + 开关 + 审计块 | ✅ 已完成（v0.3；`factor_priors_provider` + 8 项单测 + 端到端验证） |
| M4-3 | 3 快照 differential 验收 | ✅ 已完成（v0.5；5 快照，coef=0.20 全通过，short 对称性受限） |
| M4-4 | 小额实盘灰度（用户裁决：跳过 2 周 shadow 观察，直接小额度验证） | ✅ 已接线（v0.6）；开关/额度/归因/回滚见 §9.1 |

### 9.1 M4-4 小额实盘灰度方案（v0.6）

**前提事实**：50 已有 live 通道（`tools/run_live.py` → `runtime/live/outbox.jsonl` → `22/x1_live_executor.py`），执行权注册表已为 72 标的 / 9 类配置 `live:50-bypass`（mandate `mandate-20261114-50-live-multi`，与 40 `asset_classes` 的 G1/G2 可交易全集对齐）。M4-4 不是"新开 live"，而是在既有通道上开启 overlay 并收紧额度。

| 维度 | 落地 |
|---|---|
| 开关 | `run_live.py` 默认 `--factor-priors on`（源 `50_LIVE_FACTOR_PRIORS`），把 `ENABLE_50_FACTOR_PRIORS_OVERLAY=1` 注入进程环境；shadow 通道仍默认关闭 |
| 系数 | `--coef` 只接受 §5.1 候选集，缺省 0.10（`FACTOR_PRIORS_COEF`），越界由 `resolve_coef()` 回落并审计 |
| 小额 | `--notional-usdt` 默认 100（`50_LIVE_NOTIONAL_USDT`），写入决策 `notional_usdt`；22 执行层取 `min(13 定容, 声明值)`，只降不升；22 按类别再有 100/150/300 USDT 的 cap 与 floor。低于标的 minSz 的声明会被 bridge 判 `size_zero`（fail-closed，不下单） |
| 归因（决策侧） | `payload.factor_priors_overlay.attribution` = 用 overlay 前 path 复算的反事实基线 `{baseline.direction/confidence/position_pct, delta, direction_flip}`；同时保留 `enabled/coef/modulation_rate/degraded` |
| 归因（成交侧） | `tools/live_attribution.py` 将 outbox × `22/audit/x1_live_fills.jsonl` 按 `decision_id` join，输出分标的/分系数的 Δ 与成交情况 |
| 复现 | 每次 `run_live` 的 `latest.json` 记录 `overlay{enabled,coef,coef_source}` 与 `notional_usdt`，与 outbox 决策一一对应 |

**归因口径（便于更新修复）**：

1. `delta.confidence > 0` = 先验与当前方向同向加权；`< 0` = 逆向压制；`direction_flip=true` 需人工复核（首轮应极少出现）。
2. `degraded` 非空（`stale_priors` / `insufficient_samples` / `missing_priors`）说明先验未生效，此时决策等价于关闭状态，不得计入"overlay 效果"。
3. 成交侧当前只有开仓台账，`pnl_available=false`；收益归因待平仓回报 join 后补充，不阻塞灰度。

**观察窗口与判据**：

- 首轮观察 **≥20 笔已成交 live 决策**（或 5 个交易日，先到者为准），期间系数锁定 0.10，禁止调参。
- 触发回滚的任一条件：出现 `direction_flip`；`|delta.confidence|` 均值 > 0.05；连续 3 笔同标的重复开仓被 `position_guard` 拦截；22 出现 `risk_blocked` 连续 3 次。
- 观察结束输出：`live_attribution.py` 报告 + 是否维持 0.10 / 升 0.15 / 回滚至 0 的结论，写入本 SPEC 版本记录。

### 9.2 云端部署与首轮验证（2026-11-14，v0.7）

**部署事实**：云端 `43.160.201.117` 的 `origin/main = e5433117`（含 M4-4 提交 `f13c2c90d0`）。
调度不新增、不改 unit：

| 环节 | 云端现状 |
|---|---|
| 42 总线 | crontab `*/15 * * * * … run_bus.py`（`ENABLE_11_STATE_ADAPTER=1`），`generated_at` 持续刷新 |
| 50→22 实盘链路 | `dreambuddy-nn-live-chain.timer`，`OnCalendar=*:02/5`，service 串联 `run_live.py` → `x1_live_executor.py --limit 20`（并发上限 12，`position_scope=registry`） |
| 50 shadow | crontab 每 15 分钟（`:07/:22/:37/:52`）跑 `run_shadow.py` |

**首轮证据（13:32:01 自动触发）**：

```text
latest.json : overlay={enabled:true, coef:0.1, coef_source:"default"}, notional_usdt=100
outbox      : XAU-USDT-SWAP long, modulated_paths=3/5, degraded=[]
attribution : baseline 0.706156 → 0.716805 (Δconf +0.010649), direction_flip=false
归因摘要    : 251 决策 / overlay 生效 11 / coef=0.1 ×11 / 降级 0 / flip 0
              mean Δconf +0.002369, mean Δposition +0.188918
```

**本地不设 live 调度**（硬约束）：本地与云端共用同一 OKX 账户，双跑会双开仓（各自 `position_guard` 只看本机 11 持仓）。本地仅保留 shadow / differential / 单测能力。

**已知边界**：单笔名义低于标的 `minSz` 时 22 会 `size_zero` 拒单；首轮取 100 USDT 以覆盖 BTC 等 `lotSz` 较大的标的。

---

## 十 · 复现命令

```bash
cd 50-NN主矛盾评估器

# 单测
python3 -m pytest tests/test_factor_priors_overlay.py -q

# 真实先验影响面
python3 tools/priors_differential_probe.py --out /tmp/priors_probe.json

# 反向压力场景
python3 tools/priors_differential_probe.py \
  --priors /tmp/priors_inverted.json --out /tmp/priors_probe_inverted.json

# M4-3 多快照验收（先导出 git 历史快照）
for sha in 7d97c0ed58 b285b501fc 5b46722ff4 bbf1dce103 3a3c1d6511; do
  git show "$sha:42-神经网络交易协调层/runtime/bus_state.json" > "/tmp/bus_$sha.json"
  python3 tools/priors_differential_probe.py --bus-state "/tmp/bus_$sha.json" \
    --out "/tmp/m4_3/fwd_$sha.json" >/dev/null
  python3 tools/priors_differential_probe.py --bus-state "/tmp/bus_$sha.json" \
    --priors /tmp/priors_inverted.json --out "/tmp/m4_3/inv_$sha.json" >/dev/null
done

# M4-4 live 灰度（overlay 默认开，coef=0.10，单笔 ≤100 USDT）
python3 tools/run_live.py --symbols BTC-USDT-SWAP --notional-usdt 100 --coef 0.10
python3 tools/live_attribution.py   # outbox × 22 成交台账归因

# M4-4 回滚（仅关 live overlay，不改代码）
python3 tools/run_live.py --factor-priors off
```

---

## 版本记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-11-14 | 首版草案：消费契约、映射与计算规则、实测影响面、系数预注册、门禁与验收 |
| v0.2 | 2026-11-14 | Q1-Q6 全部裁决：flow 并 D3、event 仅 C7、默认系数 0.10、n_samples 下限 200、join_coverage 仅告警、不消费 direction_priors；代码与单测同步，实测复跑 |
| v0.3 | 2026-11-14 | M4-2 接线：新增 `adapters/factor_priors_provider.py`，接入 `make_decision` / `make_shadow_decision` / `build_symbol_decisions`；开关默认关闭；新增 §6.4 接线验证；登记 Q7（`onchain.*` 待裁决） |
| v0.4 | 2026-11-14 | Q7 裁决：`onchain.*` 首轮不映射（丢弃 + 审计），禁止映射 C6/D1/D3；修正 v0.3 中“onchain→C6”的错误建议（C6 在 50 语义为估值维） |
| v0.5 | 2026-11-14 | M4-3 五快照验收：coef=0.20 正向/反向全通过，max\|Δtotal\|=0.028377，零翻转；反向 0.30 已越界；新增 §7.3 结果与证据边界；审计补 `priors_schema_version`，`data_version` 标 null |
| v0.6 | 2026-11-14 | M4-4 小额实盘灰度：run_live 默认开启 overlay（`--factor-priors on`）+ `--coef` 候选集校验 + `--notional-usdt`；决策 payload 增 `attribution` 反事实基线；22 执行层按 `min(13 定容, 声明值)` 只降不升；新增 `tools/live_attribution.py`；回滚三级写入 §7.5 |
| v0.7 | 2026-11-14 | M4-4 已部署云端（`origin/main=e5433117`）并首轮验证：overlay 生效、coef 0.10、无降级、零 flip；单笔名义默认对齐 22 下限 100 USDT（20 USDT 会因 minSz 触发 `size_zero`）；新增 §9.2 部署与验证证据、硬约束「本地不设 live 调度」 |
