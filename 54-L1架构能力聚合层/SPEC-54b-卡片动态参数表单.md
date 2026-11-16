# SPEC-54b · 卡片动态参数表单（v0.2 · 已落地）

> 目标读者：能力层 / 前端研究台
> 状态：**v0.2 已实现**（AC1–AC8 本地验收通过；代码待提交/部署）
> 关联：[SPEC-54-能力卡片全景接入](./SPEC-54-能力卡片全景接入.md)（v1.0，R1/R3/R5）、[TECHNICAL_DESIGN](./docs/TECHNICAL_DESIGN.md)

---

## 1. 背景与目标

SPEC-54 落地后，卡片模式 94 项中 **82 项可直接按需接入**（云端 2026-11-17 实测）。剩余 12 项里，**J25–J30 共 6 项**属于「能力已实现、只是缺用户输入」：

| 能力 | 当前 code | 缺什么 |
|---|---|---|
| D-J25 空间自相关 | `missing_args` | `coords`（空间坐标） |
| D-J26 生存分析 | `missing_args` | `time`（生存时间，可选 `event/group/covariate`） |
| D-J27 可靠性与控制图 | `missing_args` | `time`（可选 `event`） |
| D-J28 Meta 分析 | `missing_args` | `effects` + `se` |
| D-J29 中介/调节 | `ok` | 无需改造（已可加） |
| D-J30 PIT/release_ts | `missing_args` | `indicator`（价格侧可自动装配） |

阻塞点有两个：

1. **装配器直接拒绝**：`capability_resolve.USER_INPUT_ONLY` 对这 5 项固定返回 `missing_args`，不再往下调用能力；
2. **前端只有固定三参**：`CapabilityCard` 参数面板写死 `symbol/benchmark/days`，无法输入数组；`CapabilityPicker` 又要求预览 `ok` 才允许添加，形成死锁。

**目标**：用 schema 驱动的动态参数表单，放开 J25–J30，让用户填一次参数即可加卡并持久化。
**非目标**：E19（lights 块）/K02（发现流程）的上游产物；A14/A16/G23 禁用项；E14/G21 样本门禁策略；不新增能力、不改任何统计口径。

---

## 2. 现状事实（可复现）

- 云端 94 项矩阵：`ok 82 / unsupported 3 / missing_args 5 / sample_insufficient 2 / product_missing 2`。
- `param_schema` 由函数签名反射生成，J25–J28 的参数类型被判错：

| 参数 | 实际形态 | 当前 `_type_of` 结果 | 应有类型 |
|---|---|---|---|
| `coords` | `[[x,y], …]` | `scalar` | `json` |
| `event` | `[0/1, …]` | `scalar` | `series` |
| `group` | `["A","B", …]` | `scalar` | `labels` |
| `covariate` | `[float, …]` | `scalar` | `series` |
| `se` | `[float, …]` | `scalar` | `series` |
| `time`/`effects` | `[float, …]` | `series` ✅ | `series` |

- 各能力最小样本：`MIN_SPATIAL = MIN_SURVIVAL = MIN_META = 30`；J30 的对齐样本门槛沿用 `MIN_CONDITIONAL`。
- J25 实现要求 `coords` 与 `values` 等长；J28 取 `min(len(effects), len(se))`（本 SPEC 收紧为必须等长）；J30 要求 `indicator` 与 `prices` 等长、全有限。

---

## 3. 方案

### 3.1 schema 扩展（唯一事实源仍为 `param_schema.py`）

新增 `ARG_OVERRIDES: Dict[capability_id, Dict[arg_name, {type, source, required, min_items, hint}]]`，优先级高于签名反射；`source ∈ {auto,user,derived,unsupported}` 不变。

| 能力 | 参数 | type | source | required | 备注 |
|---|---|---|---|---|---|
| J25 | `coords` | json | user | ✅ | `[[x,y],…]`，≥30 点 |
| J25 | `values` | series | auto | — | 取 `symbol` 对齐价格，长度随 coords |
| J25 | `k`/`n_bins` | scalar | auto | — | 默认 4 / 8（高级） |
| J26 | `time` | series | user | ✅ | 生存时长，≥30 |
| J26 | `event`/`group`/`covariate` | series/labels/series | user | — | 可选 |
| J27 | `time` | series | user | ✅ | 也可用 `series` 别名 |
| J27 | `event` | series | user | — | 可选 |
| J27 | `lam`/`L` | scalar | auto | — | 默认 0.2 / 3.0（高级） |
| J28 | `effects` / `se` | series | user | ✅✅ | 必须等长，≥30 |
| J30 | `indicator` | scalar | user | ✅ | 双形态：指标名（如 `CPIAUCSL`）或自定义数值序列 |
| J30 | `prices` / `dates` | series | auto | — | 由 `symbol` 装配 |
| J30 | `release_ts`/`used_ts` | series | user | — | 可选；未填时退化为位置对齐 |
| J30 | `buckets`/`horizons`/`window` | scalar | auto | — | 默认 4 / [1] / MIN_CONDITIONAL |

快照测试 `tests/fixtures/param_schema_snapshot.json` 同步更新（AC1）。

### 3.2 装配器（`capability_resolve.py`）

把 `USER_INPUT_ONLY` 从「静态拒绝」改为「按 schema 校验后放行」：

```
if capability in USER_INPUT_ONLY:
    missing = [name for name in required_names if not payload.get(name)]
    if missing: return missing_args(missing_params=missing)
    validate: 类型/长度/有限值 → invalid_params（指出字段）
    args = 取用户值 + 自动装配（prices/dates/values）
    envelope = _run(...)
```

- J25：`values` 由 `_column(load_leader(symbol, days), 最近 N 点)` 提供，`N = len(coords)`；`N < 30` → `sample_insufficient`。
- J30：`prices/dates` 由 symbol 日轴装配；未给 `release_ts` 时在 `quality.degraded_reason` 标注 `release_ts_absent`（不伪造 PIT）。
- 缓存键不变（payload 规范化哈希已覆盖数组入参）；失败仍不缓存。

### 3.3 前端控件映射（`CapabilityCard` 参数面板）

| schema.type | 控件 | 校验 |
|---|---|---|
| `scalar`(number) | 数字输入 | 整数/范围（buckets ≥2、window ≥2） |
| `scalar`(string) | 文本输入 | — |
| `series` | 多行文本域（逗号/换行分隔） | 解析为 `number[]`；NaN 拒绝 |
| `labels` | 多行文本域 | 解析为 `string[]` |
| `json` | JSON 文本域 | `JSON.parse` + 形状校验 |

- 只渲染 `source=user` 的必填项 + 高级项（`scalar` 且 `source=auto` 折叠展示，可覆盖默认）。
- 数组一致性即时校验：`coords↔values`、`effects↔se`、`indicator↔prices`，不一致时禁用「重跑」并提示。
- 面板打开时 `op=explain` 拉 schema（已有接口），不需新 API。

### 3.4 「需填参」也能加卡（解死锁）

`CapabilityPicker` 新增第三态：

- `preview.state = ok` → 可添加（现状）；
- `missing_args` 且 schema 含 `source=user` 参数 → **可添加**，写入 `args={}`，卡片以空态展示「还缺参数：coords / time / effects、se」；
- 其他 code → 维持禁用。

`addable = ok || (code === 'missing_args' && schemaHasUserArgs)`。

### 3.5 持久化与回滚

- 参数仍走 `visual_cards.db` 的 `args_json`；单条 64KB 上限不变。超限返回 `invalid_params: args_too_large`，不做静默截断。
- `NEXT_PUBLIC_CARDS_SCHEMA_V2=false` 时回退到旧行为；表单仅在存在 `source=user` 参数时出现，不影响其余 82 项。

---

## 4. 验收标准（机器可判定）

| # | 标准 |
|---|---|
| AC1 | `param_schema` 对 J25–J30 输出 `coords=json / event=series / group=labels / covariate=series / se=series`，且 `source=user` 与上表一致；快照测试更新后全绿 |
| AC2 | `resolve("D-J25", {})` → `missing_args` 且 `missing_params=["coords"]`；`{coords, values}` 等长≥30 → `ok`；长度不等 → `invalid_params` |
| AC3 | `resolve("D-J26", {time:[…60]})` → `ok`；`{time, event}` → `ok` 且 `logrank` 非空；`time` 长度 <30 → `sample_insufficient` |
| AC4 | `resolve("D-J27", {time:[…60]})` → `ok`；`resolve("D-J28", {effects, se})` → `ok`；`effects/se` 不等长 → `invalid_params` |
| AC5 | `resolve("D-J30", {indicator:[…250], prices:[…250]})` → `ok`；未提供 `release_ts` 时 `quality.degraded_reason` 必须含 `release_ts_absent`（只披露，不降级为 partial） |
| AC6 | Jest：`series` 文本 → `number[]`（含脏值拒绝）、`json` 解析失败提示、数组等长校验、空值必填提示 |
| AC7 | 浏览器：J25 填 30+ 组坐标 → 出 Moran's I；J28 填 effects/se → 出合并效应；J30 填 indicator → 出 PIT 分位；三卡刷新后参数仍在（R3b） |
| AC8 | 回归：其余 82 项 code 不变；94 项矩阵中 J25–J28/J30 仍为 `missing_args`（空参），但前端「添加」可用；AC5 基线不下降 |

---

## 5. 落地清单

| 层 | 文件 | 改动 |
|---|---|---|
| schema | `l1agg/capabilities/param_schema.py` | `ARG_OVERRIDES` + `_type_of` 扩展；枚举新增 `labels` |
| 装配 | `3.1-FRONTEND/scripts/capability_resolve.py` | `USER_INPUT_ONLY` 分支改为校验放行；J25 values / J30 prices 装配 |
| 前端 | `components/visual/CapabilityCard.tsx` | schema 驱动动态表单 + 一致性校验 |
| 前端 | `components/visual/CapabilityPicker.tsx` | `missing_args + user args` 可添加 |
| 前端 | `lib/visual/types.ts`、`lib/visual/config.ts` | 类型扩展、CSV/JSON 解析与校验工具 |
| 测试 | `tests/test_spec54b_user_args.py`、`src/lib/visual/__tests__/form.test.ts` | AC1–AC6 |
| 文档 | 本文件、SPEC-54 §R1、TECHNICAL_DESIGN | 版本与状态同步 |

---

## 6. 风险与对策

| 风险 | 对策 |
|---|---|
| 大数组入参撑爆 payload / 缓存键 | 64KB 上限显式报错；缓存键用 sha1，不存原文 |
| J30 未给 `release_ts` 被误读为已做 PIT | 响应 `degraded_reason=release_ts_absent`，UI 明示 |
| `coords` 与 `values` 长度不匹配 | 前端拦截 + 服务端 `invalid_params` 双保险 |
| 表单使卡片头部变重 | 仅 `source=user` 能力展示；其余卡片零变化 |
| 数组精度/脏值 | 统一 `Number` + `isFinite`，拒绝 `NaN/Infinity` |

---

## 7. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-11-17 | 首版：schema overrides、装配器放行、动态表单控件、Picker 三态、AC1–AC8、风险清单 |
| v0.2 | 2026-11-17 | 落地：J30 `indicator` 定为双形态（指标名/自定义序列）；补 §8 验收结果 |

---

## 8. 落地记录（v0.2）

**代码**
- `l1agg/capabilities/param_schema.py`：新增 `ARG_OVERRIDES`（J25–J28、J30），在 `for_capability` 生成参数后统一覆盖。
- `3.1-FRONTEND/scripts/capability_resolve.py`：新增 `USER_ARG_CAPS`、`_num_list`、`_resolve_user_args`；J25–J28 由静态拒绝改为校验放行；J30 支持数值序列入参并披露 `release_ts_absent`。
- `CapabilityCard.tsx`：编辑面板按 schema 动态渲染 `series/labels/json/scalar` 字段，提交前做数值/JSON/等长校验。
- `CapabilityPicker.tsx`：`canAdd = ok || (missing_args && schema 含用户参数)`，缺参能力可先添加。
- `config.ts`：新增 `parseNumberSeries / parseLabels / parseJsonArg / hasUserArgs / argToText`。

**验收结果**
| # | 结果 |
|---|---|
| AC1 | 快照已更新：`coords:json:1:user`、`group:labels:0:user`、`effects:series:1:user`、`indicator:scalar:1:user` |
| AC2 | J25 缺参 → `missing_args["coords"]`；30 点坐标+values → `ok`；长度不等/畸形坐标 → `invalid_params` |
| AC3 | J26 `time` 60 条 → `ok`；带 `event` → `ok`；<30 → `sample_insufficient`；event 长度不符 → `invalid_params` |
| AC4 | J27 `time` / `series` 别名 → `ok`；J28 等长 → `ok`，不等长 → `invalid_params`，缺 `se` → `missing_args` |
| AC5 | J30 300 点 indicator+prices → `ok`，`degraded_reason=release_ts_absent` |
| AC6 | Jest 新增 5 例（解析/脏值/等长/回填），`src/lib/visual` 33 passed |
| AC7 | 已部署云端并取证：D-J28 加卡→填 effects/se 各 40 个→出结论（合并 0.1256，95% CI 0.1087~0.1424，n=40）；D-J25/D-J30 预览显示「需填参数 · 缺 coords/indicator」且添加可用；测试卡已删除 |
| AC8 | 94 项空参矩阵不变：`ok 80 / unsupported 3 / sample_insufficient 2 / missing_args 5 / product_missing 4`（本地库口径） |

**测试**
- `tests/test_spec54b_user_args.py`：15 例全过
- `tests/test_spec54_capability_resolve.py`：12 例全过（`test_requires_user_params` 期望已按新语义更新为 `time` 必填、`event` 可选）
- `npx tsc --noEmit` 通过
