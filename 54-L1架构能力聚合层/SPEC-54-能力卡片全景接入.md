# SPEC-54-能力卡片全景接入（v0.4 · 已补齐缺失项）

> 目标读者：L1 能力层 / 前端研究台 / 平台工程
> 状态：**Draft v1.0，待终审**（P0/P1/R3b/R6 与 AC1–AC10 全部验收；R6 三项已落地，真实流量基线随云端部署累积）
> 关联：[SPEC-54-L1架构能力聚合层](./SPEC-54-L1架构能力聚合层.md)、[SPEC-54-统计图表化能力](./SPEC-54-统计图表化能力.md)、[TECHNICAL_DESIGN](./docs/TECHNICAL_DESIGN.md)

---

## 1. 背景与问题

`/dashboard/visual/research` 卡片模式支持 `＋ / －` 增删能力卡，但实际只能跑通少数能力：

| 观测 | 实测值（云端 2026-11-16，HEAD `bcaf2d0a`） |
|---|---|
| manifest 能力总数 | 94（A16 / B2 / E19 / G24 / J30 / K3） |
| 默认 13 张卡 | 10 张 `invalid_params`；D-K02 空（生产者缺失）；D-K03 空（`gate_pass=0`）；仅 D-K01 有 3 行 |
| D-E17 典型报错 | `invalid_params: class_board() missing 1 required positional argument: 'assets'` |
| 能力数据依赖 | 全部为外部作用域（`series` 27、`candles` 25、`panel` 21…），能力层自身不取数 |
| 前端添加卡片 | `CapabilityPicker.handleAdd` 固定写 `args: {}`，无参数表单 |
| 缺参提示 | `CapabilityCard` 仅一句静态文案，无输入入口 |

**结论**：缺口在**参数装配层**，需补「参数 schema + 服务端装配 + 前端表单 + 空态分级」。

> 上表为修订前基线。R-18 入参校正后，10 张 `invalid_params` 已全部消除（详见 §9、§6 AC1 实测）。

---

## 2. 目标与非目标

### 目标
- G1：94 项能力均可被添加与解释：**86 项由装配器自动补参**（AC1 实测 80 项出数、2 项样本不足、4 项上游产物缺失）、**5 项需用户/外部数据**（D-J30、J25–J28）、**3 项显式禁用**（D-G23 / D-A14 / D-A16）。
- G2：参数由表单显式呈现，可推断的自动填充。
- G3：序列参数统一由服务端按「资产 + 频率 + 区间」装配。
- G4：卡片参数服务端持久化（跨设备一致），并允许池外自定义序列。

### 非目标
- 不新增能力、不改任何能力的统计口径与门禁阈值。
- 不改变 `/api/visual/overview` 现有行为。
- 不实现 K02 的发现流程生成器（另立 SPEC）。

---

## 3. 能力分型（v0.4）

| 类型 | 数量 | 必需参数 | 能力 ID | 装配来源 |
|---|---|---|---|---|
| T0 零参数 | 47 | 无 | D-E05/E06/E09/E11/E20、D-K01~K03、D-G 组 15 项、D-J 组 24 项 | 无需装配；依赖库内产物 |
| T1 单序列 | 11 | `prices` | D-B08/B09、D-A07、D-E02/E03/E04/E07/E10/E15、D-G08/G09 | 资产 close（E15 另需 H/L，R2.3） |
| T1b 序列+事件 | 1 | `prices` + `events` | D-G23 | **事件源缺失 → unsupported** |
| T2a 单序列 | 4 | `series: Sequence` | D-G22、D-J02、D-J04、D-J05 | 资产 close |
| T2b 多资产映射 | 6 | `series: Mapping[str, Sequence]` | D-E12、D-G14、D-G16、D-G25、D-J22、D-J24 | 默认池多资产 |
| T2c 单资产多分项 | 1 | `series: Mapping[str, Any]` | D-A14（拥挤度合成，需资金费率/持仓量/波动率等分项） | **分项源缺失 → unsupported** |
| T3 取值序列 | 10 | `values` | D-A02/A03/A04/A05/A06/A08/A09/A13/A15/A16 | 逐项绑定（R2.5）；A16 **无数据源 → unsupported** |
| T4 取值+日期 | 1 | `values, dates` | D-A01 | T3 + 对齐日期轴 |
| T5 双序列 | 9 | 两个序列 | D-A10/A11/A12、D-E01/E08/E14、D-G19/G20、D-J30 | 按语义分 5 类（R2.1） |
| T6 富输入 | 4 | E16 `series`；E17 `assets`；E18 `flows`；E19 `block` | D-E16/E17/E18/E19 | 实测四种形态（R4） |

合计 47+11+1+4+6+1+10+1+9+4 = **94**。

> 禁用清单（3 项）：**D-G23**（缺事件源）、**D-A14**（缺分项源）、**D-A16**（缺稳定币规模源）。

### 3.1 T0 零参数能力完整清单（47 项）

| 分组 | 数量 | 能力 ID |
|---|---|---|
| E 组 | 5 | D-E05、D-E06、D-E09、D-E11、D-E20 |
| K 组 | 3 | D-K01、D-K02、D-K03 |
| G 组 | 15 | D-G01、D-G02、D-G03、D-G04、D-G05、D-G06、D-G07、D-G10、D-G11、D-G12、D-G13、D-G15、D-G18、D-G21、D-G24 |
| J 组 | 24 | D-J01、D-J03、D-J06、D-J07、D-J08、D-J09、D-J10、D-J11、D-J12、D-J13、D-J14、D-J15、D-J16、D-J17、D-J18、D-J19、D-J20、D-J21、D-J23、D-J25、D-J26、D-J27、D-J28、D-J29 |

> T0 仅表示“签名无必需参数”，**不代表有产物**。产物可用性由 AC1 实测归类，禁止默认视为 `ok`。
> **落地实测（v0.6）**：T0 的隐式入参已按「首位置参数名即 kwarg 名」逐项确认并写入装配器
> （`PANEL_CAPS` / `SERIES_IMPLICIT` / `DUAL_IMPLICIT` / `ZERO_ARG_CAPS` / `MATRIX_IMPLICIT`），
> 94 项矩阵 `invalid_params = 0`、`error = 0`（详见 §9 R-18）。

### 3.2 分型判定与复现

分型依据 `inspect.signature` 的必需参数（无默认值、非 VAR_*），可用下列命令复现（实测输出与 §3 表一致）：

```bash
cd 54-L1架构能力聚合层 && python3 - <<'EOF'
import importlib, inspect
from l1agg.capabilities.manifest import load
m = load(); groups = {}
for cid in sorted(m.capabilities):
    c = m.get(cid); mod, _, attr = str(c.executor).rpartition('.')
    fn = getattr(importlib.import_module(f'l1agg.{mod}'), attr)
    req = [p.name for p in inspect.signature(fn).parameters.values()
           if p.default is inspect._empty and p.kind in
           (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)]
    groups.setdefault(','.join(req) or 'ZERO', []).append(cid)
for k, v in groups.items(): print(k, len(v), ' '.join(v))
EOF
```

签名分布：`ZERO 51`（含 T6 四项 `**kwargs`，故 T0 实为 47）、`prices 12`、`series 11`、`values 10`、`factor,forward 3`、`x,y 2`、`factor,prices 2`、`values,dates 1`、`nominal,cpi 1`、`indicator,prices 1`，合计 94。

---

## 4. 需求

### R1 · 参数 schema 单一事实源
- 新增 `l1agg/capabilities/param_schema.py`，为 94 项输出
  `{args:[{name, type, required, default, source, options}], accepts_extra}`。
- `type ∈ {scalar, series, series_map, asset_list, pair, macro_pair, events}`；
  `source ∈ {auto, user, derived, unsupported}`。
- `source=derived`：由其他参数计算得出（如 factor），前端禁止直填。
- `source=unsupported`：当前无数据源，UI 禁用并展示原因。
- **schema 是唯一事实源**：对 `**kwargs` 能力（T6），schema 显式声明优先于签名推断。
- `explain` 返回该 schema（保留 `accepted_params` 兼容）。
- **验收**：94/94 有 schema；除 T6 外，`validate({})` 的 `missing_params` 与 `required=true 且无默认值` 一致；T6 以显式声明为准（见 AC3）。

#### R1.1 schema 结构示例

```json
{
  "capability_id": "D-E08",
  "accepts_extra": false,
  "args": [
    {"name": "factor", "type": "series", "required": true, "source": "derived",
     "derived_by": "momentum_20d", "options": ["momentum_20d", "volatility_20d"]},
    {"name": "forward", "type": "series", "required": true, "source": "derived",
     "derived_by": "forward_returns(1)"},
    {"name": "k", "type": "scalar", "required": false, "default": 5, "options": [3, 5, 10]}
  ],
  "requires_symbol": true,
  "requires_benchmark": false
}
```

#### R1.2 枚举与渲染映射

| type | 前端控件 | 是否允许用户改 |
|---|---|---|
| `scalar` | 数字/枚举下拉 | 是 |
| `series` | 资产下拉（+ 频率） | 是 |
| `series_map` | 资产多选 | 是 |
| `asset_list` | 资产多选（默认池预填） | 是 |
| `pair` | 主资产 + 基准资产 | 是 |
| `macro_pair` | 只读（显示 DGS10 / CPIAUCSL） | 否 |
| `events` | 只读（缺失时禁用） | 否 |
| `json` | 只读（结构由服务端装配或上游传入） | 否 |

`source` 与控件关系：`derived` → 只读并显示派生口径；`unsupported` → 禁用；`user` → 必填。

#### R1.3 生成方式（避免 94 项手写漂移）

1. 以 `inspect.signature` 生成骨架（快照入库 `config/param_schema.yaml`）；
2. 用人工覆盖表 `config/param_schema_overrides.yaml` 修正语义（T5 九项、T6 四项、A16/G23/A14 禁用位）；
3. `param_schema.py` 启动时合并二者，`config/param_schema.yaml` 与代码不一致时测试失败。

### R2 · 服务端序列装配器
新增 `3.1-FRONTEND/scripts/capability_resolve.py`（**编排层，不得进 `l1agg/capabilities/`**），复用 `visual_overview` 的 loader/对齐（抽公共函数）。
新增 `POST /api/visual/capabilities {op:"resolve", capability_id, payload:{symbol?, benchmark?, freq?, days?, assets?, custom_series?, ...}}`；显式参数优先，装配器只补空。

#### R2.0 对齐与 warm-up（必须先于装配实现）

派生序列天然含 NaN（如 `momentum_20d` 前 19 点），而 D-E01 要求等长且 `prices` 全有限。统一规则：

1. **取交集日期轴**：所有参与序列取 `dates` 交集，升序。
2. **warm-up 截断**：从首个所有序列均有限的位置开始截断，`factor/forward/prices/x/y` 与 `dates` 同步截断。
3. **禁止填充**：不得用 0、前值、均值填充 NaN（会污染 IC 与分箱）。
4. **判定顺序**：截断后长度 < 能力 `min_n` → `sample_insufficient`（附 `n/min_n`）；仅在**结构性**错误（长度不等、日期乱序）时返回 `invalid_params`。
5. **单资产基准**：`benchmark` 与 `symbol` 相同时（如 x/y 都选 BTC）允许，但结果标 `degenerate_pair: true`。

#### R2.1 装配规则总表（按语义分组）

| 组 | 能力 | 参数 → 来源 | 说明 |
|---|---|---|---|
| 单序列 | T1 / T2a | `prices`/`series` = `close_usd(symbol)` | 直接取默认池资产 |
| 多资产映射 | T2b | `series = {sym: close_usd(sym) for sym in assets or 默认池}` | 对齐到公共日期轴 |
| **同资产派生对** | D-E01 | `factor = momentum_20d(close)`；`prices = close` | 函数**内部**从 prices 算前瞻收益 |
| **同资产派生对（收益口径）** | D-E08、D-G19、D-G20 | `factor = momentum_20d(close)`；**`forward = forward_returns(close, h=1)`** | `forward` 是前瞻收益，**不是价格** |
| **相关状态对** | D-E14 | `factor = rolling_corr(close(symbol), close(benchmark), 60)`；`prices = close(symbol)` | factor 是相关系列 |
| 跨资产对 | D-A11、D-A12 | `x = close(symbol)`；`y = close(benchmark)` | 默认 `benchmark=US500` |
| 宏观对 | D-A10 | `nominal = DGS10 月化`；`cpi = CPIAUCSL 水平值月化 + PIT 滞后` | 见 R2.2 |
| 外部指标 | D-J30 | `indicator` = 用户选择（`requires_user`）；`prices = close(symbol)` | 不给默认指标 |
| 资产列表 | T6 | `assets = 默认池 14 或用户多选` | 见 R4 |

`derive_factor` 首版只提供 `momentum_20d = close[t]/close[t-20]-1`，schema 暴露 `factor_kind` 供后续扩展。
`forward_returns` 复用 `l1agg.align.forward_returns`，与 D-E01 内部口径保持一致。

#### R2.2 宏观对（D-A10）绑定细则
- `cpi`：**`CPIAUCSL` 水平值**（月频，1947-01 起 1,226 点），**不得**用 `yoy_pct`（仅 41 点）。
- `nominal`：`DGS10` 日频 → 每月最后观测月化，与 CPI 同轴。
- **PIT**：月 M 的 CPI 仅在 M+1 月中旬后可用，实现 `release_ts = (M+1) 月 15 日`；按 `release_ts ≤ as_of` 过滤。
- 该日期规则为**近似发布日历**，非 FRED 官方 vintage；保留替换为 ALFRED realtime 的接口点。
- 样本不足 → `quality=partial` + `pit_alignment_insufficient`，不得回退“当月即用”。

#### R2.3 H/L 与 ADX 披露（D-E15）
有 `high_1d`/`low_1d` 则装配；否则只传 close 并强制返回 `adx_unavailable: true`，禁止静默降级。

#### R2.4 对齐与长度约束
- 所有成对序列（含 `factor/prices`、`factor/forward`、`x/y`）必须**等长且同日对齐**，**不得 drop NaN** 后传参。
- D-E01 首行即校验 `len(factor) == len(prices)`，装配层须在调用前保证成立。
- 日期轴缺失/不升序 → 直接返回 `invalid_params`，不进入能力函数。

#### R2.5 取值序列逐项绑定（T3）
- `A02/A03/A05/A06/A09/A13/A15`：`values = close_usd(symbol)`。
- `A04/A07`（分位/回撤）：`close_usd`。
- **`A08`（同比）**：`period` 按频率推导（日 252 / 周 52 / 月 12），不得沿用默认 12。
- **`A16`**：`unsupported`（无稳定币规模源）。

#### R2.6 池外自定义序列
- `custom_series: {dates:[...], values:[...]}`，**限制**：长度 ≤ 5000、两数组等长、dates 严格升序且唯一、values 全部有限（拒绝 NaN/Inf），否则 `invalid_params`。
- 结果标 `data_provenance="custom"`；自定义序列不写入 mm_metrics。
- 与 `macro_pair`/`derived` 参数不可混用（同时出现 → `invalid_params`）。

#### R2.7 组合权重校验（D-G16）
`weights` 省略时等权；提供时必须满足 `len(weights) == len(assets)` 且 `sum(weights) ≈ 1`（容差 1e-6），否则 `invalid_params`。

#### R2.8 禁用能力返回契约
`op=resolve` 对 D-G23 / D-A14 / D-A16 返回：
```json
{"ok": false, "code": "unsupported", "reason": "<缺失数据源说明>", "capability_id": "D-A16"}
```
`code` 为固定枚举，AC1 依此分类，不计入 `failed`。

#### R2.9 派生函数契约

```python
def derive_factor(close, kind="momentum_20d", window=20) -> list[float | None]
def forward_returns(close, h=1) -> list[float | None]          # 复用 l1agg.align.forward_returns
def rolling_corr(a, b, window=60) -> list[float | None]
def to_monthly_last(dates, values) -> tuple[list[str], list[float]]
```

- 全部返回**与输入等长**的列表，前导位置为 `None`，由 R2.0 统一截断；不得提前过滤。
- `kind` 首版仅 `momentum_20d`、`volatility_20d`（滚动 20 日收益标准差）。
- 浮点：内部 `float64`；收益不做四舍五入；相关系数输出保留 6 位小数。
- `rolling_corr` 的窗口不足时整段为 `None`，不得用 0 代替。

#### R2.10 T0 产物依赖（AC1 前置）

| 能力 | 依赖产物 | 实测 code（2026-11-16） |
|---|---|---|
| D-K01 | `relationship_registry` 的 candidate/stable 行 | `product_missing`（本库注册表尚未生成） |
| D-K02 | `reports/discovery/<期>/manifest.json + findings.jsonl` | `product_missing`（无生成器） |
| D-K03 | 同库 `gate_pass=1` 行 | `product_missing`（有表无行） |
| D-E19 | 主览图 lights 块 | `product_missing`（上游产物，卡片直连不重建） |
| D-E14 / D-G21 | 更长历史（非重叠 250 桶 / 250 期横截面） | `sample_insufficient`（当前交集 454 / 169） |
| D-J30 / J25–J28 | 用户或外部研究数据（indicator / coords / time,event / effects,se） | `missing_args`（显式缺参，不伪造） |
| 其余 80 项 | 库内 `panel/series/prices` 作用域 | `ok` |

> AC1 首轮只记录 code，不得预先写入“可用”；返回空时严格区分 `product_missing`（上游产物缺席）与 `sample_insufficient`（门禁样本不足）。

### R3 · 前端参数表单
- Picker 按 schema 渲染：`series` → 资产下拉；`series_map` → 多选；`pair` → 主/基准；`macro_pair` → 只读展示绑定；`scalar` → 数字/枚举；`derived/unsupported` → 只读/禁用。
- `handleAdd` 写入真实 args（含默认值），不再固定 `{}`；支持「编辑参数」重跑。
- **验收**：T1/T2a/T2b/T3/T4/T5 各 1 项一次出数；三个 unsupported 呈禁用态并给出原因。

### R3b · 参数服务端持久化
- 新增 `GET/PUT /api/visual/cards/config`，键 `{userId, tabId, panelKey}`，值 `{capability_id, args, data_provenance, updated_at}`。
- **`userId` 必须取自服务端 session，禁止信任请求体**；跨用户读写一律 403。
- 单用户配置上限（如 200 面板 / 1MB），超限 `payload_too_large`。
- localStorage 仅作离线缓存，服务端为唯一事实源。
- **验收**：换浏览器登录后参数与自定义序列一致恢复；伪造 userId 返回 403。
- **落地**：`scripts/cards_config.py`（存储）+ `src/lib/visual/cards-config.ts`（CLI 客户端）+ `src/app/api/visual/cards/config/route.ts`（GET/PUT）+ `config.ts::mergeServerPanels`（服务端→本地合并）；AC8 由 `src/app/api/visual/cards/config/__tests__/route.test.ts` 覆盖。

#### R3b.1 存储结构

新增 SQLite 表（`19-数据访问层/data/visual_cards.db`，不动既有库）：

```sql
CREATE TABLE IF NOT EXISTS card_config (
  user_id          TEXT NOT NULL,
  tab_id           TEXT NOT NULL,
  panel_key        TEXT NOT NULL,
  capability_id    TEXT NOT NULL,
  title            TEXT,                   -- 卡片标题（v0.7 增列，兼容旧表 ALTER）
  kind             TEXT,                   -- series/table/matrix…（v0.7 增列）
  args_json        TEXT NOT NULL,          -- 含 custom_series
  data_provenance  TEXT NOT NULL DEFAULT 'pool',
  updated_at       INTEGER NOT NULL,       -- unix 秒
  PRIMARY KEY (user_id, tab_id, panel_key)
);
CREATE INDEX IF NOT EXISTS idx_card_config_tab ON card_config(user_id, tab_id);
```

| 实现约定（v0.7 落地） | 说明 |
|---|---|
| `PUT` 语义 | **整页快照替换**：先删该 `(user, tab)` 全部行，再写本次面板；`panels=[]` 即清空 |
| tab 元数据 | 每 tab 固定一条 `panel_key='__tab__'`、`args={title}` 的行，承载 tab 标题与「空 tab」事实 |
| tab 删除 | 发 `__tab__` 墓碑行 `args={title, deleted:true}`；merge 时删除本地自建 tab（builtin 不可删） |
| 前端基线 | 拉取成功且服务端有记录时刷新同步基线；无记录则把本地默认配置整页回写（R8 迁移） |
| 失败策略 | 读/写异常一律 FAIL-OPEN，localStorage 继续可用，不阻断看板 |

| 项 | 约束 |
|---|---|
| 单条 `args_json` | ≤ 64KB |
| 单用户总量 | ≤ 1MB 或 200 个面板，超限 `payload_too_large` |
| `PUT` 语义 | 幂等 upsert；`panel_key` 冲突即覆盖 |
| `GET` 语义 | 按 `user_id + tab_id` 返回该页全部面板，按 `panel_key` 排序 |
| 清理 | 用户删除卡片即删行；不保留历史版本 |

### R4 · T6 四项富输入 schema（v0.4 实测修正）

四项签名均为 `*args, **kwargs`，但入参形态各不相同，不能统一按 `assets` 列表处理：

| 能力 | 参数 | 实际类型 | 装配来源 | 实测 |
|---|---|---|---|---|
| D-E16 | `series` | `Mapping[str, Mapping[date, float]]` | 默认池逐资产 `date→close` | ok，2 成员 |
| D-E17 | `assets` | `Mapping[str, {prices, dates}]` | 默认池 + 公共日期轴 | ok，n=746 |
| D-E18 | `flows` | `Sequence[flow edge]` | `mm_metrics` 的 `etf_flow` 滚动 z | ok，12 条边 |
| D-E19 | `block` | lights 块（`gate/lights/meta`） | 需上游 lights 块；未提供 → `missing_args` | missing_args |

- schema 类型：`series_map`（E16/E17）、`json`（E18/E19，新增枚举）。
- E19 需用户/上游传入 `block`，本 SPEC 不自动构造，避免与 D-E19 的输入口径循环依赖。
- **验收**：E16/E17/E18 转换器各出数；E19 缺 `block` 时返回 `missing_args` 且 `missing_params=["block"]`。

### R5 · 空态分级
| code | 触发 | UI |
|---|---|---|
| `missing_args` | `validate` 返回 missing | 高亮表单 |
| `product_missing` | D-K02（生产者缺失） | 预注册空间 + “发现流程未接入” |
| `no_signal` | D-K03（`gate_pass=0`） | 「候选 3 / 通过门禁 0」 |
| `sample_insufficient` | `quality=partial` 且 insufficient | 显示 `n/min_n` |
| `unsupported` | schema `source=unsupported` | 禁用 + 原因（G23/A14/A16） |
| `invalid_params` | 对齐/长度/权重校验失败 | 指出具体字段 |
| `error` | 其余异常 | 原始 reason |

> K02/K03：只做空态与解释，不生成数据、不放宽门禁。

### R6 · 性能、并发与观测
- P95 目标**分档**：单资产能力 ≤ 3s；多资产能力（T2b/T6/J22）≤ 8s；命中 60s 缓存时 ≤ 3s。
- 缓存键 `(capability_id, symbol, freq, benchmark, assets_hash, args_hash)`。
- 卡片并发上限 6，超出排队。
- **观测**：`resolve` 记录 `capability_id / code / 耗时 / n`，按日聚合成功率、P50/P95、失败 code 分布；连续 5 分钟失败率 >20% 需可定位到具体能力。
- **落地状态（v0.9）**：`resolve` 已在响应 `meta.elapsed_ms` / `quality.n` 输出单次观测字段。
  - **性能根因已修复**：一次性 CLI 每次请求都要付 ~11s 的 Python import（sklearn/scipy/statsmodels），实测 import **10.77s**、真实计算仅 **0.05s**；13 卡并发全部撞 25s 超时返回 503。新增常驻 worker `scripts/capability_resolve_server.py` + `src/lib/visual/resolve-worker.ts`，import 只付一次、请求串行复用（worker 失败自动回落一次性 CLI）。
  - **实测**：冷启动 12.9s；热请求 0.05–0.07s；13 个能力并发全部 200、总耗时 **1.83s**（最慢 0.82s），优于「单资产 ≤3s / 多资产 ≤8s」目标。
  - 仍需真实流量后再定阈值：分档 P95 报表、60s 结果缓存、按日聚合。
  - 同期修复前端死锁：`CapabilityCard` 原用 `loading` 作 effect guard，依赖变化触发 cleanup 后 `loading` 永不复位 → 卡片永久骨架屏；改为 `requestId` 竞态丢弃 + 「最后发起的请求必关 loading」。
  - **60s 结果缓存（v1.0 已落地）**：`capability_resolve.cache_key = capability_id + sha1(规范化 payload)`，TTL 60s、上限 256 条、LRU 淘汰；**只缓存 `code=ok`**，失败结果立即重试；命中时 `meta.cache=hit` 并按命中耗时计入观测。实测同参二次请求 `0ms`（`meta.cache=hit`）。
  - **按日聚合 + 分档 P95 报表（v1.0 已落地）**：`scripts/resolve_metrics.py` 落 SQLite `19-数据访问层/data/visual_metrics.db`（表 `resolve_metric`，90 天保留）；`daily_report()` 输出按日成功率、P50/P95、失败 code 分布、`single/multi/cache` 分档 P95 与超阈 `breaches`，并在近 5 分钟失败率 >20% 且样本 ≥5 时输出 `alerts`（可定位到具体能力）。`GET /api/visual/capabilities/metrics?days=7` 提供同口径 JSON（30s 缓存）。
  - 实测（本地 worker）：`D-E10` miss 3ms → hit 0ms；`D-J22` miss 269ms；报表 `p95=269ms`，未触发任何分档超阈。

### R7 · API 契约

**`POST /api/visual/capabilities`**

请求（`op=explain`）：
```json
{"op": "explain", "capability_id": "D-E08"}
```
响应：`{ok, capability_id, schema, visual_hint}`

请求（`op=resolve`）：
```json
{"op": "resolve", "capability_id": "D-A11",
 "payload": {"symbol": "BTC", "benchmark": "US500", "freq": "1d", "days": 750}}
```
响应：
```json
{"ok": true, "capability_id": "D-A11", "code": "ok",
 "data": {"...": "能力原始信封"},
 "quality": {"status": "ok|partial", "n": 730, "as_of": "2026-11-14"},
 "visual": {"kind": "series", "...": "..."},
 "meta": {"elapsed_ms": 812, "data_provenance": "pool", "warmup_trimmed": 19}}
```

| code | HTTP | 含义 |
|---|---|---|
| `ok` | 200 | 成功（含 `quality=partial`） |
| `missing_args` | 200 | 缺必需参数（业务失败） |
| `invalid_params` | 200 | 参数非法（对齐/长度/权重/自定义序列） |
| `unsupported` | 200 | 数据源缺失（G23/A14/A16） |
| `product_missing` | 200 | 产物未生成（K02） |
| `no_signal` | 200 | 门禁无信号（K03） |
| `sample_insufficient` | 200 | 截断后样本不足 |
| `not_found` | 404 | capability_id 不存在 |
| `unauthorized` | 401 | 未登录 |
| `rate_limited` | 429 | 超限流 |
| `error` | 500 | 未捕获异常（AC1 计为 failed） |

- 鉴权：两个路由均要求登录；`explain` 只读、`resolve` 计入限流（60 次/分钟/用户）。
- 响应统一 `code` 字段，前端按 R5 渲染，禁止用 HTTP 状态区分业务分支。

### R8 · 兼容与迁移

- `explain` 保留 `accepted_params`（标 `deprecated`），新增 `schema`；前端两期切换，二期移除旧字段。
- 前端新增 TS 类型 `CapabilitySchema`（`3.1-FRONTEND/src/lib/visual/types.ts`），与后端字段一一对应。
- 历史卡片 `args` 为空时：首次加载按 schema 填默认值并回写服务端，`migrated_at` 记录在 `card_config.updated_at`。
- 默认 13 张卡不改 ID，只补 `args`。
- **落地状态（v0.8）**：`CapabilitySchema` 已加到 [types.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/components/visual/types.ts)，`explainCapability` 返回 `schema`；`defaultArgsForSchema` 只写 `symbol` / `benchmark` / auto 标量默认值（跳过 `days` 与 derived/required），新增卡片不再写 `args: {}`。

### R9 · 回滚与灰度

- 特性开关 `NEXT_PUBLIC_CARDS_SCHEMA_V2`：关闭后 Picker 恢复 `args: {}` 与静态提示（现行为），`resolve` 路由保留但不被调用。
- 灰度：先对内部账号开启（`user_id` 白名单），观察 24h 无 `error` 再全量。
- 回滚代价：新增表与新增路由，不改既有表结构，无需数据迁移；回滚只切开关。
- **落地状态（v0.8）**：开关已实现（`CapabilityPicker` 中 `SCHEMA_V2 = process.env.NEXT_PUBLIC_CARDS_SCHEMA_V2 !== 'false'`，默认开）；`user_id` 白名单灰度未实现，当前等价全量开启（回滚路径已验证：关闭后回落到 `validate + run` + `args: {}`）。

---

## 5. 数据流

```
Picker ──explain──▶ param_schema（derived / unsupported / requires_user）
   │
   └─add card(args)──▶ CapabilityCard ──PUT cards/config(session.userId)──▶ 服务端
                              │
                              └─POST op=resolve──▶ capability_resolve.py
                                                        │
              load_daily / pool / align / derive_factor / forward_returns / rolling_corr
                                                        │
                                              run_capability(id, **args)
                                                        │
                                   envelope(code/quality/visual) ──▶ 渲染
```

---

## 6. 分期与门禁

| 期 | 内容 | 覆盖 | 依赖 |
|---|---|---|---|
| P0 | R1 + R2（T0/T1/T2a/T2b/T3 除 A16/T4/T5 中 7 项）+ R3 + R3b | **85 项** | 无 |
| P1 | 宏观对 D-A10（CPI PIT）+ D-J30 用户选指标 + R4（T6 4 项）+ R2.3 H/L | 6 项 | P0 |
| P2 | R6 观测与缓存（R5 空态、R2.8 unsupported 已随 P0/P1 完成） | 全局 + G23/A14/A16 | ✅ 常驻 worker + 60s 缓存 + 日聚合/分档 P95 报表 + 5 分钟告警；阈值待云端真实流量校准 |

**验收门禁（机器可判定）**
- **AC1**：`scripts/capability_matrix_check.py` 遍历 94 项 `op=resolve`，输出 JSON 到 `reports/capability_matrix_<YYYYMMDD>.json`，结构为 `{generated_at, total, by_code:{…}, items:[{capability_id, code, n, elapsed_ms, reason}]}`；`failed` 必须为 0，`unsupported` 必须恰为 `{D-G23, D-A14, D-A16}`，`items` 必须 94 条且 `capability_id` 无重复。
- **AC2**：T1/T2a/T2b/T3/T4/T5 各至少 1 项在浏览器卡片模式出数（截图 + 响应留证）。
  - **状态（v0.9）：✅ 已取证**（dev `localhost:3001`，匿名态；`cards/config` 因未登录返回 401，不影响出数）：

| 型 | 能力 | 浏览器可见结果 | 截图 |
|---|---|---|---|
| T1 单序列 | D-E10 | 回撤折线图（Y 0–0.6 / X 19–499），`status good · n 745` | `acceptance_bundles/20261116_spec54_ac2/T1_D-E10.jpg` |
| T2a 序列 | D-J02 | 季节强度 C13=0.1423 / STL=0.0643 / X-13=0.3461，`status partial · seasonality_depth_lt_3y · n 745` | `T2a_D-J02.jpg` |
| T2b 多资产映射 | D-J22 | PCA「面板 14 变量 / 170 对齐样本」，`status good · n 170` | `T2b_D-J22.jpg` |
| T3 取值序列 | D-A08 | 同比 0.59%（基期前 252 期），`status good · n 745` | `T3_D-A08.jpg` |
| T4 取值+日期 | D-A01 | 745 观测、当前 68897.3、历史 15.70% 分位，`status good · n 745` | `T4_D-A01.jpg` |
| T5 双序列 | D-A11 | 滚动 Pearson 0.6808（均值 0.3732，484 窗口，n=513），`status good · n 513` | `T5_D-A11.jpg` |
- **AC3**：除 T6 外，`validate({})` 的 missing 与 schema required 一致；T6 以显式声明为准（schema 覆盖签名），单测含该例外。
- **AC4**：D-A10 在 `as_of` 变化时 `used_month ≤ as_of - 1 月` 恒成立（PIT 单测）。
- **AC5**：落地前记录 `pytest 54-L1架构能力聚合层/tests -q` 的通过数作为基线，落地后不得下降。
  - **基线（v0.8 实测）**：collect **1466** 项；全量运行 **0 failed**（`.pytest_cache/v/cache/lastfailed` 为空）；v2.62 记录的 1314 已因 G/J 组与本次新增用例上升。**新增 31 项**：`test_spec54_capability_resolve.py`（11，含 94 项 schema 快照）+ `test_spec54_cards_config.py`（11）+ `test_spec54_resolve_metrics.py`（9，缓存/聚合/P95/告警）。
- **AC6**：D-E08/G19/G20 的 `forward` 与 `forward_returns(close, 1)` 完全一致（单测断言，防再次误传价格）。
- **AC7**：`custom_series` 超长/含 NaN/日期乱序均返回 `invalid_params`（边界单测）。
- **AC8**：`PUT cards/config` 使用伪造 `userId` 返回 403（安全单测）。✅ 已由 `cards/config/__tests__/route.test.ts` 覆盖（含 401/403/400/413 四档）。
- **AC9**：warm-up 截断后，`factor/forward/prices/x/y` 与 `dates` 等长且全有限（单测：`momentum_20d` 输入 100 点 → 输出 80 点，NaN 数为 0）。
- **AC10**：`resolve` 返回 `meta.warmup_trimmed` 与实际截断点数一致，且 `quality.n + warmup_trimmed == 原始交集长度`（单测）。

---

## 7. 已定决策

1. **默认基准**：`benchmark = US500`（仅用于跨资产对与相关状态对）。
2. **宏观绑定**：`nominal=DGS10`、`cpi=CPIAUCSL 水平值`，月化 + `release_ts=(M+1)/15` PIT。
3. **参数持久化**：服务端，`userId` 取自 session。
4. **K02/K03**：只做空态与解释。
5. **池外序列**：允许，`custom_series` + `data_provenance=custom`，≤5000 点。
6. **禁用清单**：D-G23 / D-A14 / D-A16 三项，待各自数据源补齐后重新评估。

---

## 8. 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| `forward` 被误传为价格 | IC/分桶结论失真 | R2.1 明确收益口径 + AC6 断言 |
| CPI 未做 PIT | 前视偏差 | R2.2 + AC4 |
| `custom_series` 滥用 | DoS / 口径污染 | R2.6 限制 + `data_provenance` 落库 |
| `cards/config` 越权 | 跨用户数据泄露 | R3b session 取 userId + AC8 |
| 装配器混入能力层 | 分层腐化 | 红线：只放 `3.1-FRONTEND/scripts/` |
| 多资产能力拖慢首屏 | 体验下降 | R6 分档 P95 + 缓存 + 并发上限 |
| CPI 近似发布日历不准 | 边界日期的 PIT 误判 | 标注近似 + 预留 ALFRED vintage 替换点 |

---

## 9. 评审记录

### 第一轮（v0.1 → v0.2）
| # | 结论 | 处置 |
|---|---|---|
| F1 | T2 混装单序列与多资产 | 拆 T2a/T2b |
| F2 | D-G23 需 events | 设 T1b + unsupported |
| F3 | D-E15 ADX 依赖 H/L | R2.3 披露 |
| F4 | D-A16 无数据源 | unsupported |
| F5 | D-A08 period=12 日频语义错 | R2.5 按频率推导 |
| F6 | T6 `**kwargs` 无法静态识别 | R4 显式 schema |
| F7 | factor=benchmark 错误 | R2.1 同资产派生对 |
| F8 | D-E14 factor 应为滚动相关 | R2.1 相关状态对 |
| F9 | CPI 需水平值 + PIT | R2.2 + AC4 |
| F11 | J30 indicator 是序列 | requires_user |

### 第二轮（v0.2 → v0.3）
| # | 结论 | 处置 |
|---|---|---|
| R-1 | E08/G19/G20 的 forward 必须是前瞻收益 | R2.1 收益口径 + AC6 |
| R-2 | E01 要求等长对齐，不得 drop | R2.4 |
| R-3 | A14 需单资产多分项，非多资产价格 | 新设 T2c + unsupported |
| R-4 | G16 权重未校验 | R2.7 |
| R-5 | AC3 与 T6 签名冲突 | AC3 例外条款 |
| R-6 | unsupported 无返回契约 | R2.8 + AC1 分类 |
| R-7 | G1 与 unsupported 矛盾 | §2 G1 改写 |
| R-8 | P0 含 A10 但标“依赖无” | A10 移 P1 |
| R-9 | AC5 无基线 | 明确基线记录 |
| R-10 | custom_series 无限制 | R2.6 + AC7 |
| R-11 | userId 来源未定义 | R3b + AC8 |
| R-12 | P95 单一目标不合理 | R6 分档 |
| R-13 | 缺观测要求 | R6 观测条款 |
| R-14 | CPI 发布日近似 | R2.2 标注 + 替换点 |
| R-15 | 评审记录漏 F6 | 已补 |
| R-16 | A14 与 R2.1 表述冲突 | 已统一为 T2c |
| R-17 | T6 并非统一 `assets` 列表，实为四种入参（E18 需 flows、E19 需 lights 块） | §3 改「富输入」；R4 按实测重写，E18 由 etf_flow 装配，E19 需上游 block |
| R-18 | T0 中 35 项（G01–G24、J01–J27）经 `**kwargs` 隐式要求 `panel`/`target`，签名不可见 | **已闭环**：按「首位置参数名即 kwarg 名」+ 首次 `ValueError` 文案反向确认，落成 5 张映射（`PANEL_CAPS` 13 / `SERIES_IMPLICIT` 11 / `DUAL_IMPLICIT` 7 / `MATRIX_IMPLICIT` 4 / `ZERO_ARG_CAPS` 3）；`panel` 统一传 `{sym: [float]}`；J20/J21 用收益矩阵 + 等长 `y`，J23/J29 用 `X`，G21 用 `factor/target` 双收益矩阵；E03/E04/J02/J04/J05/E12/G14/G16/J22/J24 补 `dates`，E04 由 `mm_events` 装配；J19 `groups` 改为数值分组而非标签 |

---

## 10. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-11-16 | 首版，基于云端 94 能力实测 |
| v0.2 | 2026-11-16 | 按 F1–F11 修订：拆型、重写装配规则、CPI PIT、unsupported、持久化、custom_series |
| v0.3 | 2026-11-16 | 按 R-1~R-16 修订：forward 收益口径、等长对齐、A14 拆 T2c、权重/自定义序列校验、session 越权、P95 分档、观测、AC1–AC8 |
| v0.4 | 2026-11-16 | 补齐缺失项：§3.1 T0 清单、§3.2 分型复现、R1.1 schema 示例、R1.2 控件映射、R1.3 生成方式、R2.0 warm-up、R2.9 派生契约、R2.10 产物依赖、R3b.1 存储结构、R7 API 契约、R8 兼容迁移、R9 回滚灰度、AC9/AC10、§11 附录 |
| v0.5 | 2026-11-16 | 落地期修正 R-17：T6 实为四种富输入（E16 series / E17 assets / E18 flows / E19 block），R4 重写，枚举新增 `json` |
| v0.6 | 2026-11-16 | R-18 闭环：94 项矩阵 `ok 80 / sample_insufficient 2 / product_missing 4 / missing_args 5 / unsupported 3 / error 0`；E19 按上游产物归 `product_missing`，J25–J28 由 `invalid_params` 改 `missing_args` |
| v0.7 | 2026-11-16 | R3b 落地：`visual_cards.db` + `GET/PUT /api/visual/cards/config`（userId 仅取 session，伪造 403）+ 整页快照替换 + `__tab__` 元数据/墓碑行 + `title/kind` 增列 + `mergeServerPanels`；新增 18 条单测（7 路由 + 6 合并 + 11 存储） |
| v0.9 | 2026-11-16 | AC2 浏览器取证 6/6 通过（T1 D-E10 / T2a D-J02 / T2b D-J22 / T3 D-A08 / T4 D-A01 / T5 D-A11，截图归档 `acceptance_bundles/20261116_spec54_ac2/`）；过程中定位并修复两个真问题：① `resolve` 每次请求付 ~11s import → 常驻 worker（冷 12.9s / 热 0.05s / 13 并发 1.83s）；② `CapabilityCard` 用 `loading` 作 effect guard 导致 cleanup 后永久骨架屏 → 改 `requestId` 竞态控制；R6 仅剩「P95 报表/结果缓存/日聚合」待真实流量 |
| v1.0 | 2026-11-17 | R6 收口：60s 结果缓存（ok-only、LRU 256、`meta.cache`）、`resolve_metrics.py` 按日聚合/分档 P95/失败 code 分布/5 分钟能力级告警、`GET /api/visual/capabilities/metrics` 报表出口；新增 `test_spec54_resolve_metrics.py` 9 项；实测同参二次 0ms |
| v0.8 | 2026-11-16 | 收口剩余项：R3 修复（Picker 走 `explain(schema) → resolve`，新增卡片写默认 args 而非 `{}`，此前 80 项会因空参预览失败而无法添加）、R8 TS 类型 `CapabilitySchema`、R9 开关 `NEXT_PUBLIC_CARDS_SCHEMA_V2`、参数编辑点「重跑」回写看板触发同步；§11 落地清单修正（删除不存在的 `param_schema.yaml`）；AC5 基线 1466/0 failed（新增 94 项 schema 快照防漂移），AC2 明示未执行；同步 TECHNICAL_DESIGN §6.2/§6.4.6 #41 与 INDEX |

---

## 11. 附录

### 11.1 术语

| 术语 | 含义 |
|---|---|
| 能力（capability） | `l1agg/capabilities/*` 中的纯函数，注册于 manifest，共 94 项 |
| 信封（envelope） | 能力统一返回结构，含 `ok/degraded/reason/data/quality` |
| 池（pool） | `leader_registry.DEFAULT_POOL` 的 14 个资产 |
| 装配（resolve） | 按 schema 把「资产 + 频率 + 区间」变成能力所需序列参数 |
| warm-up 截断 | 派生序列前导 NaN 段整段丢弃，保证输入全有限且等长 |
| 禁用（unsupported） | 数据源缺失、不可装配的能力（G23/A14/A16） |

### 11.2 落地文件清单

| 类型 | 路径 |
|---|---|
| schema | `54-L1架构能力聚合层/l1agg/capabilities/param_schema.py`（单一事实源：94 项定义 + `UNSUPPORTED`/`DERIVED`/`BENCHMARK_CAPS` 等常量表，不另设 YAML） |
| 装配器 | `3.1-FRONTEND/scripts/capability_resolve.py`（含 R-18 隐式入参映射、`_load_events`、60s 结果缓存与逐次观测） |
| 观测 | `3.1-FRONTEND/scripts/resolve_metrics.py`（`resolve_metric` 表 + 按日聚合 / 分档 P95 / 5 分钟告警）；`.../capabilities/metrics/route.ts`（GET 报表） |
| 常驻 worker | `3.1-FRONTEND/scripts/capability_resolve_server.py`（stdin/stdout 行协议）+ `src/lib/visual/resolve-worker.ts`（单例进程、请求串行、失败回落 CLI） |
| 路由 | `3.1-FRONTEND/src/app/api/visual/capabilities/route.ts`（`op=explain/resolve`）、`.../cards/config/route.ts`（GET/PUT） |
| 前端 | `components/visual/CapabilityPicker.tsx`、`CapabilityCard.tsx`、`DataResearchCardBoard.tsx`、`lib/visual/types.ts`、`lib/visual/config.ts`、`lib/visual/cards-config.ts`、`lib/visual/api.ts` |
| 验收 | `54-L1架构能力聚合层/scripts/capability_matrix_check.py`、`tests/test_spec54_capability_resolve.py`、`tests/test_spec54_cards_config.py`、`tests/test_spec54_resolve_metrics.py`、`src/app/api/visual/cards/config/__tests__/route.test.ts` |
| 存储 | `19-数据访问层/data/visual_cards.db`、`19-数据访问层/data/visual_metrics.db`（运行时生成，已被 `.gitignore` 的 `data/` 覆盖） |

### 11.3 上线顺序

1. 建表 → 2. 落 schema（含 overrides）→ 3. 装配器 + 单测（AC9/AC10/AC6/AC7）→ 4. 路由（AC8）→ 5. 前端表单（开关关闭态）→ 6. 跑 AC1 生成矩阵报告 → 7. 白名单灰度 → 8. 全量并更新 §6 的“未实测项”。
