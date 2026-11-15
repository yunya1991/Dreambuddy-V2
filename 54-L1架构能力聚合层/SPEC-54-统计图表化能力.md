# SPEC-54 统计图表化能力（CapabilityVisual）

- **版本**: v0.22（动态权重接入实盘切换：三档灰度 off/shadow/on + 跨运行状态恢复 + 等权否决门注入判定 · L1D-11 已验收）
- **日期**: 2026-11-15
- **状态**: 🟢 有条件通过（4.38/5）；B1–B5 已关闭；B6/B11/B12 文档层关闭且 **S0/S1 已落地（68+ 用例通过）**；B13–B17 已定稿；**B18 vintage 回放已实现（迁移脚本 + As-Of 查询 + 4 用例）**；**T1 表格已实现（D-E12 8 列表 + 能力清单表 + 审计全量×6 矩阵，B10 基线冻结）**；**T2 曲线已实现（D-E10 回撤 series + D-E15 价格/EMA26 series + 斜率表 6 列）**；**T3 已实现（`overview.py` tree + graph，B8 降级契约落码，`test_visual.py` 24 例全绿）**；**L1D-01 已验收（`direction_rule.py` + `config/direction_rule.yaml`，四轴 40/25/20/15，13 例全绿）**；**L1D-02 已验收（`trading.db` 五表 + signal/fill 只追加触发器，7 例全绿）**；**L1X-01 已验收（`l1agg/handoff.py` + 49 契约加法式 `l1-chart`，7 例全绿；契约 5/5 + 示例 5/5 OK）**；**L1X-02 已验收（22 `_PRECHECK_SOURCES` 覆盖 `l1-chart`，6 例全绿）**；**L1D-03 已验收（能力块→规则入参零重算，5 例）**；**L1D-04 已验收（四条平仓规则 + `min_hold_bars` 绕过止损，8 例）**；**L1D-05 已验收（纸面回放 7 例）**；**L1D-06/07 已验收（vol targeting 仓位 + 五项风控/kill switch，12 例）**；**L1X-03 已验收（outbox 幂等 dedupKey + 失败重投，7 例）**；**DOC-01/02 已验收（INDEX v2.20 补 54 小节 + 49 §3.8 更名加注）**；**P2 三项已验收（L1X-04 簇敞口 7 例 / L1D-08 动态权重 6 例 / L1D-09 对照打分 8 例）**；B19/B20 仍待决策；方法编号冲突已修正为 I35–I39
- **上游**: `SPEC-54-L1架构能力聚合层.md`（ADR-3/6 只做确定性计算）、`docs/TECHNICAL_DESIGN.md`、`docs/METHOD_LIBRARY.md`、`.trae/documents/系统图表可视化能力-评估调研报告.md`
- **下游**: `contracts/capability_result.schema.json`、`3.1-FRONTEND/src/components/visual/`、`33-REA逆向解析工程/core/reflection/thought_tree.py`、`48-涌现架构`

> 一句话：L1 把已算好的确定性结果表达成**表格 → 曲线 → 思维导图**三类图；前端零统计；思维树与反思进化器只读取图的落盘制品，反向发现新的数据/资产关系与更优统计算法。

---

## §1 三层递进（2026-11-15 用户定调）

| 层 | 图种 | 回答什么问题 | 数据来源 | 交付判据 |
|---|---|---|---|---|
| **T1 分类梳理** | `table` | 「有哪些数据、怎么分组、样本够不够」 | D-E12 对齐切片、方法审计 386×6、能力清单、MERS 注册表 | 可按资产/类别/周期分组排序；每行带 `n` 与 `quality`；缺数据单列不隐藏 |
| **T2 时序演化** | `series`（曲线） | 「平滑噪声后往哪走、斜率是否一致、趋势强弱」 | 价格/指标序列 + I02 EMA、T08 斜率、I32 ADX（**需新增曲线生产者**，见评审报告 §3.1 B6） | 平滑参数与窗口强制披露；斜率带 `hac_corrected=false`；对外只给统计事实，方向由内部 L1-D 规则产出 |
| **T3 全景思维导图** | `tree`（主）+ `graph`（辅） | 「前瞻/实时共振/跨资产表现的全景，资金往哪流、矛盾主次」 | D-E05 矩阵、D-E06 领先滞后、D-E11/C18 同向率、D-G22 显著性、D-A14 拥挤度、D-E10 回撤、D-E12 切片 | 根→类别→资产→指标分层；每叶可反查能力 ID；缺失节点显式 `unavailable`/`proxy` |
| **T4 反思消费者** | `tree` / `graph` 制品 | 「从图里发现更多维关系、找更优统计学算法」 | T1–T3 的落盘制品（非实时调用 L1） | 制品可版本化、幂等、字节可复现；L1 不反向依赖 33/48 |

### 1.1 L1 / L2 边界（硬约束）

> **2026-11-15 用户修正**：L1 的方向**不来自大模型推理**，而来自「趋势延续 + 惯性 + 历史周期规律」的统计自然延伸——这正是曲线图的意义。因此方向**不是** L2 专属；边界落在「**对外是否可见**」与「**是否确定性可回放**」，而不是「有没有方向」。

| 事项 | 归属 | 说明 |
|---|---|---|
| 平滑值、斜率、ADX、相关系数、`p_adj`、效应量、样本量 | **L1-S（统计层）** | 全部确定性统计量，后端算完 |
| 「市场阻力最小方向」的**统计描述** | **L1-S** | 三类事实：多窗口斜率符号一致性、ADX 区间、EMA 排列（如 12>26>50） |
| 「趋势延续/惯性/周期律 ⇒ 方向」的**规则化判定** | **L1-D（方向层，内部）** | 由 `direction_rule`（显式参数 + 版本号）确定性产出，**禁止 LLM**；结果只写内部 signal 表，**不进信封** |
| 下单 / 平仓 / 仓位 | **L1-X（执行层，内部）** | 小额、有硬风控上限、有 kill switch；**对外零暴露** |
| 「所以应该做多/做空/加仓」类**对外措辞** | **禁止（任何层）** | 信封 `answer`/`visual.title`/前端文案均不得出现；方向只以内部规则记录形式存在 |
| 「主次矛盾」的排序依据（效应量×显著性×稳定性） | **L1-S** | 表格给排序，**因果解释与取舍归 L2** |
| L2 的推理结论 | **L2（大模型）** | 必须与 L1-D 的方向记录做**对照打分**，而不是替代 L1-D |
| 思维树扩展、反思进化、算法选择 | **T4（33-REA / 48）** | 读取制品后自行推理，不要求 L1 参与 |

### 1.2 L1 内部三层与可见性（2026-11-15 新增）

| 子层 | 职责 | 输入 | 输出 | 可见性 |
|---|---|---|---|---|
| **L1-S** | 统计事实 + 图规格 | 价格/指标序列 | `data.capabilities` + `data.visual` | **public**（前端/API 可调） |
| **L1-D** | `direction_rule`：趋势延续 + 惯性 + 周期律 → 方向标签与置信度 | L1-S 的斜率/ADX/EMA/显著性 | `signal` 表（含 `rule_version`/`params_hash`） | **internal**（不返回、不写 `data`） |
| **L1-X** | 风控闸 → 下单/平仓 → fill/position | `signal` + 账户状态 | `order`/`fill`/`position` 表 | **internal**（无任何对外路由） |

- 「对外只允许调用图表能力，不允许执行能力外露」= **可见性分级 + 机器强制**（见 ADR-V14 / V-G11），不是文档约定。
- L1-D 的方向置信度与 L2 的推理结论写入 `comparison` 表，用同一段行情的事后收益打分——这是 L1 闭环与 L2 对照的共同证据（ADR-V17）。

---

## §2 现状与缺口（代码事实，2026-11-15）

| 对象 | 现状 | 对可视化的影响 |
|---|---|---|
| `capability_manifest.yaml` | **14 个出口**（`D-A14`、`D-E01`–`D-E12`、`D-G22`；`D-A14/D-G22` 为并行线新增） | 我的文档此前写「10 个」「12 个」均已过期；V-AC1 改为按能力子集断言，不再硬编码总数 |
| `contracts/capability_result.schema.json` | 顶层 `additionalProperties:false`；`data` 开放；已落 `$defs.visual` | `data.visual` 可加法，T1–T3 共用一套契约 |
| D-E05 矩阵 | `matrix{matrix,names,n}` + `relationship_topk` | T3 的「共振网络」主数据源；只有全局 n |
| D-E10 回撤 | 已补 `drawdown_path/peak_price/trough_price/peak_to_trough_days` | T2 可出回撤曲线；但**无「价格平滑+斜率」生产者** |
| D-E12 对齐切片 | `window_rows{asset,start_value,end_value,ret,n_obs,stale_ratio,first_date,last_date}` | T1 主数据源，字段完备 |
| D-A14 拥挤度 | F26 + A 分位法四档（并行线） | T3 的「资金流/拥挤」代理，需标 `proxy=true` |
| D-G22 显著性 | Q06 HAC t + Q07 Deflated Sharpe（并行线） | T3 的「矛盾是否显著」判据；T2 斜率结论的前置 |
| 方法层 | `I02 EMA`、`T08 趋势斜率`、`I32 ADX` 均 `implemented=true` | T2 无需新方法，只需新能力出口 |
| 前端 | recharts 3.8；`_stat_result` 原样透出 `data` | 渲染器只管画；T3 用 tree 组件（需新建） |

---

## §3 决议（ADR-V）

| ID | 决议 | 理由 |
|---|---|---|
| ADR-V1 | `visual` 只放 `data.visual` | 同层单一真相 |
| ADR-V2 | 每信封最多 1 图；`source_capability` 必须等于信封 `capability` | 一个回答讲一件事 |
| ADR-V3 | `kind` 白名单 `table/series/matrix/tree/graph`，必带 `spec_version="1.0"` | 防契约蔓延 |
| ADR-V4 | `quality.status=="empty"` 或有能力块 `gate!="ok"` 时不产图 | 无质量的图更危险 |
| ADR-V5 | 前端零统计：桶边界、天数差、平滑、斜率、排序一律后端给 | 避免双口径 |
| ADR-V6 | 上限 rows≤500 / points≤500 / cells≤2000 / nodes≤300 | 保护首屏 |
| ADR-V7 | 图不含结论措辞，`caveat` 固定 `历史统计，不代表未来` | L1 纪律 |
| ADR-V8 | `build_visual` 纯函数，`L1_VISUAL_ENABLED=0` 可整体停用 | 零回归兜底 |
| **ADR-V9** | **平滑与斜率必须在 L1 计算**，`dataset.meta` 必带 `smoothing{method,window}`、`unit`、`n` | 用户明确「曲线用于平滑处理」 |
| **ADR-V10** | **对外方向措辞白名单**（仅约束信封 `answer`/`visual.title`/前端文案）：只允许「斜率符号/ADX 区间/EMA 排列」事实句；禁止「看涨/看跌/建议/目标价/阻力最小方向是 X」。**内部 L1-D 的方向记录不受此限**（它必须存在，否则无法形成闭环） | 对外不越界，对内不残缺 |
| **ADR-V11** | **思维导图承载**：层级总览用 `tree`；跨资产共振网络用 `graph`（≤300 节点）；同一信封仍只 1 图，`graph` 作为 `tree` 叶子的下钻 | 用户「思维导图」与「共振网络」是两种结构 |
| **ADR-V12** | **制品落盘**：T1–T3 的 `visual` 同步写 `54-L1架构能力聚合层/artifacts/visual/<capability>/<as_of>.json`，幂等、可版本化；T4 只读制品 | 思维树/反思需要稳定输入 |
| **ADR-V13** | **T3 是组合视图，零重算**：每个节点值必须等于来源能力块的对应字段（±1e-9），禁止 T3 层再聚合 | 避免第三套口径 |
| **ADR-V14** | **可见性机器强制**：能力清单新增 `visibility: public\\|internal`（默认 `public`），`exec_stat_query`/前端路由**只允许**命中 `public`；执行能力即便登记，也无任何对外入口 | 「执行能力不外露」必须是代码闸，不是约定 |
| **ADR-V15** | **方向必须确定性可回放**：`direction_rule` 是纯函数，入参 = L1-S 统计事实 + 显式参数；`signal` 表必须存 `rule_version` + `params_hash` + 输入快照；**禁止 LLM/采样/随机**参与 | 否则无法回测、无法对照、无法反思 |
| **ADR-V16** | **小额硬风控**：单笔名义上限、单日最大亏损、最大持仓数、最大杠杆、总敞口五项为配置常量，越界即拒单；`KILL_SWITCH=1` 立即停止新开仓 | 用户「资金小额、风险可控」 |
| **ADR-V17** | **L2 对照表**：L1-D 方向记录与 L2 结论按同一 `as_of`+`symbol` 写入 `comparison` 表，事后用实现收益打分；L2 不得覆盖 L1-D 记录 | 用户「用于 L2 推理对照」 |
| **ADR-V18** | **动态权重 = 点对点 + 限速 + 可回放**：只用 `observed_at ≤ as_of` 的数据与已实现标签；周度再平衡；单次换手 L1 ≤0.15；轴权重 ∈ [0.05,0.40]；`weights_hash` 必入 `signal` | 权重一旦前视或高频漂移，比固定权重更糟 |
| **ADR-V19** | **等权基线否决权**：动态权重必须样本外胜过等权（250 日滚动超额 >0 且 SPA p<0.05）才允许启用；不达标自动退回等权并记 `weight_fallback=true` | 预测组合之谜：优化权重常输给等权 |
| **ADR-V20** | **修订数据不可覆盖**：宏观/慢频序列以 `(metric, period, observed_at)` 为键追加，禁止用新修订覆盖旧观测；回放取 vintage | 否则动态权重会偷看未来修订值 |

---

## §4 契约

### 4.1 公共字段

```json
"visual": {
  "kind": "table|series|matrix|tree|graph",
  "spec_version": "1.0",
  "title": "≤60 字，不含结论",
  "source_capability": "D-E12",
  "n_scope": "global|per_row|per_cell",
  "dataset": { "...": "按 kind 约定" },
  "encodings": { "...": "按 kind 约定" },
  "quality_ref": "quality",
  "caveat": "历史统计，不代表未来",
  "truncated": false
}
```

### 4.2 各层 dataset（v0.3 扩展以粗体标注）

| 层/kind | dataset | encodings | 新增约束 |
|---|---|---|---|
| T1 `table` | `{columns[{key,label,type}], rows[{}], **groups[]**}` | 无 | `groups` 为可分组列 key 列表；`quality.status!=good` 时首列 `degraded_reason` |
| T2 `series` | `{points[{x,y,**smoothed**,**upper**,**lower**}], **meta{smoothing{method,window},unit,n}**}` | `{x,y,**slope**}` | 平滑必须后端完成；`meta` 必填；原始与平滑同时给时 `y=原始`、`smoothed=平滑` |
| T2 `table`（斜率表） | `{columns,rows}` | 无 | 列固定：`window/slope/se/t/r2/hac_corrected`，`hac_corrected=false` 必须显示 |
| T3 `tree` | `{root{id,label,value,children[],**meta{capability?,series_id?,proxy?,unit?,sign_flip?,reason?}**}}` | `{label,value}` | 节点≤300；每叶必须有 `meta.capability` 或 `meta.series_id`；缺失节点 `value=null, meta.reason` |
| T3 `graph` | `{nodes[{id,label,group}], edges[{src,dst,kind,**,weight,p_adj**}]}` | `{group}` | `kind ∈ {corr,lead_lag,same_direction}`；节点≤300、边≤2000 |

### 4.3 P0 映射（已实证）

- **D-E12 → T1 `table`**：8 列固定，`rows` 即 `window_rows` 原样投影，`n_scope="per_row"`。
- **D-E05 → T3 `matrix`**（暂按 `matrix` 交付，T3 主图仍为 `tree`）：≥3 资产出矩阵，`<3` 降 `table`，`>20` 截断并 `truncated=true`。
- **D-E10 → T2 `series`**：`points[x=date, y=drawdown]`，`max(y)==mdd`，末点==`current_drawdown`。

### 4.4 T2 曲线生产者（B6 的核心决策）

现有能力没有一个「价格/指标 → 平滑 + 斜率」的出口，T2 无法只靠 D-E10 支撑。两个方案：

| 方案 | 内容 | 评价 |
|---|---|---|
| **A（推荐）新增 D-E15 `trend_query`** | 入参 `series/prices + windows`；方法 `I02 EMA` + `T08 斜率` + `I32 ADX`；`min_n=250`；输出平滑点、多窗口斜率表、ADX、EMA 排列 | 语义干净；T2/T3 都复用；需登记 manifest + 能力实现 + 测试 |
| B 扩展 D-E10 | `drawdown(smoothing=…)` | 不推荐：回撤是派生量，平滑价格 ≠ 平滑回撤，会混淆口径 |

- ID 占用提醒：manifest 实测本次为 `D-E01`–`D-E12`，**D-E13/D-E14/D-E15/D-E16 均未登记**，可直接用 D-E15；若并行线先占，改为 D-E16。
- 门禁：`window > n` 时该窗口斜率置 `null` 并标 `degraded_reason="window_gt_sample"`（不伪造、不外推）；`T08` 未做 HAC → 必带 `hac_corrected=false` 与「斜率仅相对比较」；方向结论必须经 D-G22。

### 4.5 T3 全景导图（组合视图，不新增口径）

树形骨架（**已实现**，`l1agg/capabilities/overview.py`，`test_visual.py` 24 例覆盖）：

```text
全市场概览 (as_of)                                    ← root
├─ 前瞻性数据
│  ├─ 领先滞后最优 lag / CCF / BH-FDR q (D-E06)
│  ├─ 自然月同向率 (D-E11.cycle_alignment.ratio)
│  └─ Newey-West t (D-G22.newey_west.t_nw)
├─ 实时共振
│  ├─ 平均 |ρ| (D-E05)、Top1 相关 ρ、Top1 BH-FDR q
│  └─ 对齐切片逐资产 n_obs (D-E12.window_rows[].n_obs，逐行投影)
├─ 跨资产表现
│  ├─ 最大回撤 MDD / 当前回撤 (D-E10)
│  └─ 拥挤度 score / 分位 (D-A14)
├─ 资金流
│  └─ 巨鲸净流入 (L0 series_id=exchanges_whales::whale_netflow_to_ex_usd, proxy=true,
│                 unit=亿美元, sign_flip=-1，仅加密；未接入即 unavailable)
├─ 主次矛盾
│  └─ D-E05 TopK 逐对 ρ（效应量原样投影，不合成、不加权）
└─ 关系推荐
   └─ S5 MERS 关系推荐 → value=null, meta.reason="S5 未开放"
```

- **B8 两类叶硬区分（V-G9，已落码为 `overview._leaf` + `validate_tree_dataset`）**：

| 叶类型 | meta 必填 | 值来源 | 校验 |
|---|---|---|---|
| 能力叶 | `meta.capability`（manifest 可反查） | 能力块字段路径原样 | 值 = 来源字段（±1e-9），`gate != ok` → `null` + reason |
| 序列叶 | `meta.series_id` + `proxy=true` + `unit` + `sign_flip∈{-1,1}` | 已取回的 L0 序列值 × `sign_flip` | 未登记序列拒绝；`scope=crypto` 序列禁止用于非加密资产 |
| 缺源叶 | `meta.reason`（非空） | `value=null` | 有值无源、无值无 reason 一律拒绝 |

- `SERIES_REGISTRY` 是序列叶的唯一白名单（当前仅 1 条加密巨鲸净流）；`CRYPTO_SYMBOLS` 决定 `scope=crypto` 的适用范围。
- 「资金净流」目前**只有加密巨鲸口径**，**禁止**用于股票/外汇；未接入 → `unavailable`，不得用 OI/资金费率冒充净流。
- 组合视图用 `source_capability="T3"`（schema `^(D-[A-Z]\d{2}|T[1-4])$`），不进单能力信封时由 `build_tree/build_graph` 直接返回 `visual`；若要进信封则 `capability="T3"`（ADR-V2 等式仍成立）。
- **`graph` 只在 D-E05 `gate=="ok"` 时产出**：节点=资产矩阵 names（≤300），边=TopK 对（≤2000），`kind` 白名单 `{corr,lead_lag,same_direction}`，边必带 `weight`+`p_adj`。

### 4.6 内部表（L1-D / L1-X，**永不进信封**）

| 表 | 关键字段 | 说明 |
|---|---|---|
| `signal` | `as_of, symbol, rule_version, params_hash, direction ∈ {-1,0,1}, strength, slope_signs, adx_band, ema_order, p_adj, inputs_snapshot` | 不可变；`params_hash` 用于回放同一规则 |
| `order` | `signal_id, side, qty, notional, td_mode, reduce_only, status, reject_reason` | 拒单必须写 `reject_reason`（风控/资金/杠杆） |
| `fill` | `order_id, price, qty, fee, ts` | 只追加 |
| `position` | `symbol, qty, avg_price, unrealized, exposure_usd` | 由 fill 重算，不手改 |
| `comparison` | `as_of, symbol, l1_direction, l1_strength, l2_verdict, realized_ret, scored_at` | L1↔L2 对照（ADR-V17） |

- 五张表放在 `54-L1架构能力聚合层/data/trading.db`（与 `cognitive_memory.db` 隔离）。
- 前端/API **无任何**读取入口；`visibility=internal` 的能力在 `manifest.validate` 阶段即拒绝被 `exec_stat_query` 命中。

### 4.7 `direction_rule` 契约（B11 处置）

**定位**：把 L1-S 的确定性统计事实，按显式参数合成 `direction ∈ {-1,0,1}` 与 `strength ∈ [0,1]`。**纯函数、无 LLM、无随机、无采样**；同输入同参数必须字节一致。

**输入（全部取自 L1-S，禁止在规则内重算）**：

| 字段 | 来源 | 说明 |
|---|---|---|
| `slope_table[{window,slope,se,t,r2}]` | D-E15（T08） | 默认窗口 `[20,60,120]`，对 `ln(price)` OLS；`hac_corrected=false` |
| `adx{adx14,plus_di,minus_di}` | D-E15（I32） | 趋势强度与方向 |
| `ema{ema12,ema26,ema50,order}` | D-E15（I02） | `order ∈ {bull,bear,mixed}` |
| `same_direction_rate{r,n}` | D-E11（C18） | 可选；缺失时 `coherence_missing=true`，该轴记 0 |
| `p_adj` | D-G22（Q06 HAC t） | 可选；`>hac_alpha` 时强度轴打 0.5 折并标 `hac_insignificant` |
| `seasonality{month_effect}` | D-E03 | 可选；深度 <5 年时必须为 `null`，不得参与打分 |

**打分（总分 −100…+100，各轴先取方向再累加）**：

| 轴 | 权重 | 规则 |
|---|---|---|
| 趋势延续 | 40 | 四个窗口的 `sign(slope)` 按 `[0.15,0.25,0.30,0.30]` 加权一致度 × 40（`t` 与 `slope` 异号视为不一致） |
| 趋势强度 | 25 | `adx14<20→0`；`20–25→0.5`；`>25→1.0`；再乘 `sign(plus_di - minus_di)` |
| 惯性（EMA 排列） | 20 | `bull→+1`、`mixed→+0.4`、`bear→−1`，乘 20 |
| 前瞻共振（同向率） | 15 | `(r−0.5)×2` 截断到 `[0,1]`，符号随趋势轴；缺失记 0 |
| 周期律 | 0（本期不参与） | 仅记录到 `signal.seasonality` 供 T4 反思；**BTC 日线深度不足 5 年，强行参与会长期 degraded**（见 B14） |

**输出**：

- `direction = sign(total)`，若 `|total| < flat_threshold(=30)` 则 `direction=0`（无方向）
- `strength = min(1, |total|/100)`；分档 `flat<0.30 ≤ weak<0.55 ≤ moderate<0.75 ≤ strong`（**这是统计强度，不是建议**）
- `signal` 必存：`rule_version`、`params_hash`(sha256 of canonical params)、`direction`、`strength`、`axes{trend,adx,inertia,coherence}`、`flags[]`、`inputs_snapshot`（压缩后原文快照，用于回放）

**参数（YAML 常量 + 版本号，改参必须升 `version`；**最终定稿见 §4.11**）**：

```yaml
direction_rule:
  version: "dr-1.0.0"
  windows: [20, 60, 120, 250]
  window_weights: [0.15, 0.25, 0.30, 0.30]
  adx_bands: [[0, 20, 0.0], [20, 25, 0.5], [25, 100, 1.0]]
  ema: {fast: 12, slow: 26, trend: 50}
  flat_threshold: 30
  exit_threshold: 12
  hysteresis_confirm_bars: 2
  min_hold_bars: 6
  use_same_direction: true
  use_significance: true
  hac_alpha: 0.05
  seasonality_mode: "record_only"
```

**平仓规则（`exit_rule`，用户「根据变化也进行平仓」）**——确定性，任一触发即平：

1. `sign(total)` 与持仓方向相反；
2. `abs(total) < exit_threshold(=12)`，且**连续 2 根**确认（迟滞，防抖振，见 B13）；
3. `adx14 < 20` 且 `ema.order == "mixed"`（趋势结构瓦解）；
4. 触及硬止损（由 L1-X 风控给，不由本规则给）。

> 另需满足 `min_hold_bars ≥ 6` 才允许规则 1–3 生效（止损不受此限），避免短窗口噪声直接推翻持仓。

> 说明：`direction_rule` 的「方向」是统计外推的**标签**，对外不可见；它不与 L2 结论做二选一，而是并列写入 `comparison` 表做事后收益对照（ADR-V17）。

**持仓管理（`sizing`，L1D-06）**：`vol_scale = clip(TARGET_VOL / max(volatility, 1e-4), 0, 3.0)`（`TARGET_VOL=0.02`）；`notional = equity_usdt × strength × vol_scale`；`qty = notional / price`（8 位）；`direction=0` → `reject_reason="no_direction"` 且不下单。`volatility` 必须来自 L1-S 统计块，本层**不重算波动率**；风控越界时**不截断、直接拒**（便于审计）。

**风控五项（`risk`，L1D-07，ADR-V16）**：常量 `max_notional_usdt=500` / `max_daily_loss_usdt=100` / `max_positions=3` / `max_leverage=2.0` / `max_gross_exposure_usdt=1500`（`RISK_VERSION=risk-1.0.0`，改值必须升版本）；`L1_KILL_SWITCH=1` **只停新开仓**（`is_new=False` 的平/减仓放行，否则会把仓位锁死）；拒单顺序 `kill_switch → max_daily_loss → max_positions → max_leverage → max_gross_exposure → cluster_exposure → max_notional`，命中即拒，并由 `record_rejected_order()` 写入 `order.status='rejected'` + `reject_reason`。

**簇敞口（`cluster`，L1X-04，V-AC21）**：簇由 D-E05 矩阵 `|ρ|≥0.70` 并查集聚类；判定式 `(同簇现存敞口 + 新单) / (总敞口 + 新单) ≤ cluster_exposure_cap_pct=0.50`，越界 `reject_reason="cluster_exposure"`（`risk.check_order` 中排在 `max_gross_exposure` 与 `max_notional` 之间）。

**对照打分（`comparison`，L1D-09，ADR-V17）**：同 `(as_of, symbol)` 单行；`l1_direction/l1_strength` 写入即不可变（L2 覆盖 → `ComparisonError`），`l2_verdict` 首写优先；事后按三重障碍（±`2.0×ATR` 或 10 根先到者）打分并扣 `5 bps/边 + 0.5×ATR` 滑点，回写 `realized_ret/scored_at`。

**动态轴权重（`weights`，L1D-08，ADR-V18/V19，默认关闭）**：`enabled=False` 直接返回 `STATIC_WEIGHTS`；开启时四轴权重 ∈[0.05,0.40]、和=1、单次换手 L1 ≤0.15，且必须先过等权否决门（`n≥250`、超额均值 >0、单边 p<0.05），否则退回 `EQUAL_WEIGHTS` 并记 `weight_fallback=true`；`weights_hash` 写入 `signal.inputs_snapshot`（不改表结构）。

### 4.8 `visibility` 契约与执行外露闸（B12 处置）

| 层 | 变更 | 判据 |
|---|---|---|
| `capability_manifest.yaml` | 每条能力新增 `visibility: public\|internal`，**默认 `public`**；未知值在 `manifest.validate` 拒绝 | 14 条现有能力全部补 `public`；D-E15 为 `public`；L1-D/L1-X 相关能力为 `internal` |
| `l1agg/capabilities/manifest.py` | `validate()` 增枚举校验；新增 `assert_public(capability_id)` | 命中 `internal` 直接抛 `PermissionError`（**硬闸，不 FAIL-OPEN**） |
| `3.1-FRONTEND/scripts/data_query_executor.py` | `exec_stat_query` 入口统一先过 `assert_public` | 前端 12 个 cue 无法命中任何 `internal` |
| `envelope.build` | `data` 内禁止出现 `signal/order/fill/position/comparison` 键 | 递归扫描，命中即断言失败 |

### 4.9 D-E15 `trend_query` 契约（B6 处置）

| 项 | 内容 |
|---|---|
| manifest | `id: D-E15`、`intent: trend_query`、`methods: [I02, T08, I32]`、`min_n: 250`、`visibility: public` |
| 入参 | `series[{date,value}]`（或 `prices`+`dates`+可选 `highs/lows`）、`windows=[20,60,120,250]` |
| 门禁 | `n ≥ 250`；`window > n` 的窗口斜率置 `null` 并标 `degraded_reason="window_gt_sample"`，其余窗口照常输出 → 整体 `status=partial` |
| 输出 | `smoothed[{date,ema12,ema26,ema50}]`、`slope_table[{window,slope,se,t,r2,hac_corrected:false}]`、`adx{adx14,plus_di,minus_di}`、`ema_order`、`meta{smoothing{method:"EMA",window:12},unit,n}` |
| 业务含义句 | 仅允许「斜率符号 / ADX 区间 / EMA 排列」三类事实句（ADR-V10 对外口径） |
| 图规格 | `kind=series`，`points{x,y,smoothed}` + `meta.smoothing`，`n_scope="global"`；另出 `table` 斜率表（`kind` 二选一，按请求） |
| 三处消费者 | T2 曲线、L1-D 方向输入、T3 全景叶节点 |
| 测试 | `test_trend_query_shape_and_gates`、`test_trend_query_replay_deterministic`、`test_trend_query_insufficient_history_partial` |

### 4.10 成熟经验借鉴（传统金融 / 统计学 / 交易）

**结论：10 条可直接用，3 条明确不采纳。** 其中第 4 条（元标注）是整套方案最关键的升级——它把「L1 方向 vs L2 推理」从竞争关系变成分层协作。

| # | 成熟经验 | 出处 | 落到我们的哪个改动 | 采纳 |
|---|---|---|---|---|
| 1 | 时序动量看 **1–12 个月**，在 58 个期货品种上跨资产成立 | Moskowitz, Ooi & Pedersen (2012), JFE | `windows` 由 `[20,60,120]` 扩为 `[20,60,120,250]`，权重 `[0.15,0.25,0.30,0.30]` | ✅ |
| 2 | **波动率缩放**（vol targeting）而非固定名义额 | 管理期货/CTA 行业标准 | 仓位 = 单笔风险预算 ÷ (ATR% × 价格)，天然实现"小额且随波动自适应" | ✅ |
| 3 | **迟滞/死区**抑制 whipsaw | 趋势策略通用实践 | B13：进 30 / 出 12 + 连续 2 根 + `min_hold_bars=6` | ✅ |
| 4 | **元标注**：方向与"是否执行/仓位缩放"分离 | López de Prado (2018), AFML | L2 不抢方向，只给 `execute ∈ {0,0.5,1}`；用 `comparison` 量化 L2 增量 | ✅ |
| 5 | **三重障碍标注**（上/下/时间）替代固定持有期 | 同上 | `comparison` 按"障碍先触发者"打标，消除"到期才看收益"的偏差 | ✅ |
| 6 | **Purged K-Fold + embargo** 防泄漏 | 同上 | B15 的前视约束从"SQL 时间比较"升级为 purge + embargo | ✅ |
| 7 | **Deflated Sharpe / SPA** 防多重检验 | Bailey & López de Prado (2014)；White (2000)；Hansen (2005) | `rule_version` 晋升门禁：DSR>0 且 SPA p<0.05（Q07 已有实现） | ✅ |
| 8 | **协方差收缩 + 风险平价**做配置 | Ledoit & Wolf (2004)；Qian (2005) | T3 跨资产配权用 Ledoit-Wolf 收缩 + 风险平价，不用样本协方差/等权 | ✅ |
| 9 | **领先滞后需稳定性检验** | Granger (1969)；转移熵 | D-E06 的 CCF 增加滚动窗口符号一致性，必要时用 Granger/转移熵交叉验证 | ✅ |
| 10 | **周期律用带通滤波/STL 分解**而非月度季节 | Christiano & Fitzgerald (2003)；STL (Cleveland et al., 1990) | B14 升级：分解 30–90 日周期成分看相位与斜率，对样本长度要求远低于 5 年月度季节 | ✅（P2） |
| 11 | 成本模型：双边 taker + 滑点 + 永续资金费率 | 交易所公开费率；Almgren & Chriss (2000) | 回测按 0.05%/边 + 0.5×ATR% 滑点 + 8h 资金费率；并设"覆盖成本的最低持有期" | ✅ |
| 12 | 相关性簇敞口上限（BTC/ETH 高相关不能算两仓） | 风险管理通行做法 | L1-X 增"同簇敞口 ≤ 总敞口 50%"，簇由 D-E05 矩阵聚类给出 | ✅ |
| — | 端到端 ML 直接预测方向 | — | 违反 L1「无大模型」原则；ML 只允许出现在 L2 元标注（第 4 条） | ❌ |
| — | 全 Kelly | Kelly (1956) | 波动估计误差会放大破产概率，改用分数 Kelly（0.25×）并叠加五项硬上限 | ❌（降级） |
| — | 高频做市 / TWAP-VWAP 拆单 | — | 资金规模与基础设施不匹配；小资金用限价单 + `reduce_only` 平仓 | ❌ |

> 成本这一条常被忽略但决定性最大：20 日窗口的翻转频率约 2–4 周一次，若双边成本 0.1% + 滑点 0.5×ATR%（≈0.3–0.8%），单次往返成本可达 0.4–1.0%。因此**短窗口只能用于确认，不能单独触发交易**——这也是把 250 日权重提到 0.30 的第二个理由。

### 4.11 B13–B16 处置（评审建议并入）

| 项 | 原建议 | 定稿 | 依据 |
|---|---|---|---|
| **B13** 迟滞 | 连续 2 根 + `min_hold_bars=6` | 进 30 / 出 12，连续 2 根，`min_hold_bars=6`，`hysteresis_band=12` | §4.10 第 3 条 |
| **B14** 周期律 | 改用 D-E02 分位 | **短期**：D-E02 同期分位（立即可用）；**中期**：新增 I39 带通/STL（P2）后切换为周期成分 | §4.10 第 10 条 |
| **B15** 打分 | 固定 N=5 交易日 | 三重障碍（±2×ATR 或 10 交易日，先到者）+ purge/embargo 回测 + 扣双边成本与资金费率 | §4.10 第 5/6/11 条 |
| **B16** 额度 | 100 USDT/笔 | 单笔风险 0.5% 权益 + vol targeting；独立子账户；日亏 3% 熔断；同簇敞口 ≤50% | §4.10 第 2/12 条 |
| **B17**（新增） | — | `rule_version` 晋升必须过 DSR/SPA，否则禁止接 L1-X（V-AC22） | §4.10 第 7 条 |

**参数定稿（YAML，改值不改代码）**：

```yaml
direction_rule:
  windows: [20, 60, 120, 250]
  window_weights: [0.15, 0.25, 0.30, 0.30]
  flat_threshold: 30
  exit_threshold: 12
  hysteresis_confirm_bars: 2
  min_hold_bars: 6
risk:
  risk_per_trade_pct: 0.005        # 权益的 0.5%
  max_daily_loss_pct: 0.03
  max_positions: 3
  max_leverage: 2
  cluster_exposure_cap_pct: 0.50
  kill_switch: false
labeling:
  barrier_atr_mult: 2.0
  barrier_days: 10
  cost_bps_per_side: 5
  slippage_atr_mult: 0.5
promotion:
  min_dsr: 0.0
  max_spa_p: 0.05
```

### 4.12 美联储方法借鉴（数据—价格关系）

美联储研究的核心和我们是同一件事：**把一堆指标压缩成"当前该紧还是该松"的判断**。差别是它有 100 年宏观样本和修订数据管理，我们只有 3–5 年行情，所以**只借鉴方法，不照搬系数**。

| # | 美联储做法 | 我们的对应问题 | 落点 | 采纳 |
|---|---|---|---|---|
| 1 | **动态因子模型 + Kalman**（GDP Nowcast） | 「真实曲线」到底该用 EMA 还是状态空间 | D-E15 增 `kalman` 平滑：输出 `level/slope` 及 `±1σ` 带 | ✅ |
| 2 | **混合频率**（MIDAS） | 日/周/月数据混用 | 多窗口按频率给不同权重，不强行重采样 | ✅ |
| 3 | **误差修正 / 协整**（长期均衡 + 短期偏离） | 「数据与价格关系」不只有趋势，还有回归 | 新增 **I35 协整**，产出 `equilibrium_gap` 轴 | ✅ |
| 4 | **泰勒规则式反应函数**（显式系数、可审计） | `direction_rule` 的形态 | 已成型；补"每个指标相对中性水平的 gap 标准化" | ✅ |
| 5 | **Growth-at-Risk 分位回归**（Adrian et al., 2019） | 「前瞻性」与「强度」怎么量化 | 新增 **I36 分位回归**：`strength = q90−q10` 的预测离散度，而非点预测 | ✅ |
| 6 | **金融状况指数 FCI**（多变量加权合成） | T3 全景如何合成一个可读指数 | 合成指数用 Ledoit-Wolf + 风险平价（§4.10 第 8 条） | ✅ |
| 7 | **实时数据与修订**（ALFRED / vintage） | 宏观序列被修订 → 回放前视 | 序列追加式存储 + `observed_at`；回放只用 `observed_at ≤ as_of` 的版本 | ✅（硬要求） |
| 8 | **不确定性指数**（Jurado, Ludvigson & Ng, 2015） | 高不确定期模型失效 | 不确定高时权重向等权收缩（收缩系数见 §4.13） | ✅ |
| 9 | **预测组合**（Bates & Granger, 1969）及**组合之谜**（Smith & Wallis, 2009） | 动态权重常常不如等权 | 等权基准为对照组，样本外胜出才启用 | ✅（硬约束） |
| 10 | **状态依赖权重**（DMA, Koop & Korobilis, 2012；区制 Hamilton, 1989） | 权重该随市场状态变 | 用遗忘因子 + 区制切换，而非滚动回归硬拟合 | ✅ |

> 第 9 条是这次借鉴里最重要的**刹车**：文献反复发现"精心优化的组合权重"在样本外常输给等权。所以动态权重必须有**等权对照**，输了就退回等权——这不是保守，是证据。

### 4.13 动态权重机制（契约）

**定位**：让 `direction_rule` 的四轴权重、以及统计方法的选择权重，随「该方法近期有效性」调整，但**严格点对点（point-in-time）、限速、可回放**。

**权重四源**：

| 源 | 含义 | 计算 |
|---|---|---|
| `prior` | 经济先验（美联储看重什么：就业、通胀、金融条件、期限利差、信用利差） | 配置常量，总和为 1 |
| `reliability` | 方法/指标近期有效性 | `abs(IC)`（滚动 250 日，purge+embargo 10 日）或 `1/σ_forecast` |
| `stability` | 换手惩罚 | 与上期权重的 L1 距离 |
| `uncertainty` | 不确定期收缩 | 高不确定 → 向 `prior` 收缩（`λ_u ∈ [0,0.5]`） |

**合成**：

```
w*_i ∝ prior_i × (abs(IC_i) + ε)^κ / (σ_i + ε)          # κ=1
w* ← simplex_project(w*)                                 # 非负、和为 1
w* ← clip(w*, 0.05, 0.40) → 再归一
w_t = (1−α)·w_{t−1} + α·w*   ,  α = 0.1                  # 部分调整
L1(w_t, w_{t−1}) ≤ 0.15                                  # 单次换手上限
```

**更新节律与冻结**：

- 默认**周度**再平衡（`rebalance="W-MON"`）；再平衡之间权重**完全冻结**，日内绝不改权重。
- 估计窗口 `expanding`，最少 500 个交易日；标签必须已实现（`as_of + barrier_days ≤ now`）。
- **纸面回放期间权重锁定**为 `weights_version` 初始值，不允许边回放边调参（否则回放无意义）；实现为 `replay(weights_locked=True)`。

**启用守护（缺一不可）**：

1. 与等权基准做 250 日滚动对照，超额收益 >0 且 `SPA p < 0.05`；
2. 单次 `L1` 变化 ≤0.15；
3. 任一轴权重落在 `[0.05, 0.40]`；
4. `weights_version` + `weights_hash` 写入 `signal`，同 hash 必须复现同权重。

**落库字段**（`signal` 表扩展）：`weights_version`、`weights_hash`、`weights_effective_date`、`axis_weights{trend,adx,inertia,coherence,gap}`、`weight_sources{prior,ic,stability,uncertainty}`。

**实盘切换（v0.22 落地，L1D-11）**：

| 档位 | 计算 | 注入 `decide` | 用途 |
|---|---|---|---|
| `off`（默认） | 否 | 否（静态 40/25/20/15） | 与引入前字节一致；`signal` 仍记静态 `weights_hash` |
| `shadow` | 是，落库 `weights_hash`/`axis_weights`/`weight_sources` | 否 | 不改交易行为地积累「动态 vs 静态」对照证据 |
| `on` | 是 | **过等权否决门才注入** | 生产启用；否决未过不注入，沿用静态先验并记 `weight_fallback` |

- 开关优先级：调用方参数 > 环境变量 `L1_DYNAMIC_WEIGHTS` > `config/weights.yaml` > `off`；非法值抛 `WeightSwitchError`（fail-closed，不静默降级）。
- 跨运行状态：`previous_weights` / `last_effective_date` / `weight_fallback` 由 `weight_switch.load_state()` 从 `trading.db.signal` 最后一条带权重记录恢复，同 ISO 周内**权重与注入判定一起冻结**（避免「上周被否决、本周冻结却按优化权重注入」的错位）。
- 等权对照口径：`excess_j = fwd_j × Σ_i (w_prev_i − 0.25) × unit_axis_i,j`，只用已实现标签；轴值一律取 `axis_weights=1` 的**单位轴值**，避免注入后的加权分数反过来污染 IC 估计（IC 对正数缩放不变，σ 同步缩放，故 reliability 一致）。
- 落库口径：`recorded_weights()` 统一决定写进 `signal` 的权重 —— `off` 与「否决期」一律记静态先验 40/25/20/15（等权只作统计零假设、不落地，否则下一轮对照退化为「等权 vs 等权 = 全 0」，`oos_gate` 永久不过）；`shadow` 与 `on` 记同一口径，差别只在是否注入 `decide`。
- 晋级/回滚：只改 `config/weights.yaml` 或环境变量，不改代码；`signal.weights_hash` 全程可审计，回滚到 `off` 后新信号立即回到静态先验，历史信号不受影响。

**「真实曲线」的形态变化**：D-E15 的 `series` 从单线改为「原值 + Kalman level + `±1σ` 带」，曲线图因此自带置信区间；`slope` 同时给 `slope_se`，斜率是否"真的斜"一眼可辨。

### 4.14 需要新增的统计方法（登记清单）

| ID | 方法 | 用途 | 最小样本 | 优先级 |
|---|---|---|---|---|
| **I35** | 协整（Engle-Granger / Johansen） | `equilibrium_gap` 轴：数据与价格的长期偏离 | 500 | P1 |
| **I36** | 分位回归（quantile regression） | 前瞻分布：`q10/q50/q90` 与 `strength` | 500 | P1 |
| **I37** | Kalman / DFM 平滑 | 「真实曲线」level+slope±1σ | 250 | P1 |
| **I38** | DMA / 区制权重 | 状态依赖权重 | 750 | P2 |
| **I39** | 带通滤波 / STL 分解 | 30–90 日周期成分（相位与斜率） | 750 | P2 |

> I01–I34 已被方法库占用（实测 `I.` 前缀连续无空号），新方法一律从 **I35** 续号；B14 的带通/STL 由 I39 承担。

> 五条都必须走方法层登记（`METHOD_LIBRARY.md` + `REGISTRY`），能力层不直接实现；`min_n` 不足一律 `status=partial`，不得静默降级。

**落地状态（v0.21，逐条可核）**：

| ID | 实现位置 | 出口 | 审计 |
|---|---|---|---|
| I35 | `l1agg/methods/fed_methods.py::i35_cointegration` | `equilibrium_gap{beta,alpha,gap,gap_z,half_life,adf_p,cointegrated}` → `direction_rule` gap 轴 | audit PASS |
| I36 | `fed_methods.py::i36_quantile_regression` | `q10/q50/q90/dispersion` → `strength_mode="quantile_dispersion"` | audit PASS |
| I37 | `fed_methods.py::i37_kalman` | D-E15 `capabilities["D-E15"]["kalman"]`（level/slope/±1σ/slope_se/trail），`meta.smoothing` 保持 EMA | audit PASS |
| I38 | `fed_methods.py::i38_dma` | `weights{models}/best/switched/entropy/effective_n`，可作动态权重先验 | audit PASS |
| I39 | `fed_methods.py::i39_bandpass` | `period_days/amplitude/phase_deg/cycle_slope` | audit PASS |

工具函数（§4.12 第 2/4/6/8 条）：`midas_weights`（MIDAS）、`taylor_gap`（泰勒规则显式系数）、`fci_composite`（Ledoit-Wolf + 风险平价）、`uncertainty_index`（Jurado λ_u∈[0,0.5]）。§4.13 四源合成与周度冻结已落 `l1agg/trading/weights.py`，五个字段已落 `signal` 表（schema v2）；**实盘切换三档已接 `paper_replay.replay(weights_mode=…, weight_state=…, db_path=…)`（默认 `off`，见 §4.13「实盘切换」）**。B18 写入路径已接：`market_macro_impl.upsert_metric` 每次采集先 `INSERT OR IGNORE` 到 `mm_metric_vintages`（PK 含 `observed_at`），主表覆盖不再消灭旧观测。

---

## §5 门禁

| ID | 门禁 | 不满足时 |
|---|---|---|
| V-G1 | `ok=true` 且 `quality.status != empty` | 不产 `visual` |
| V-G2 | 来源能力块 `gate == "ok"` | 不产 `visual` |
| V-G3 | `kind` 白名单 + `spec_version` | 返回 `None`（FAIL-OPEN） |
| V-G4 | 上限未超 | 降 `table` + `truncated=true` |
| V-G5 | `title`/`answer` 不含结论措辞 | 替换默认标题 |
| V-G6 | 前端只读 `dataset` | 代码评审阻断 |
| V-G7 | `L1_VISUAL_ENABLED=0` | 全量不产图 |
| **V-G8** | T2 必带 `meta.smoothing{method,window}` 与 `n` | 不产 `series` |
| **V-G9** | T3 每个叶必须有 `meta.capability`（值一致 ±1e-9）或 `meta.series_id`（带 `proxy/unit/sign_flip`） | 该叶标 `unavailable` |
| **V-G10** | 制品落盘成功且与信封字节一致 | 记 `artifact_error`，图仍返回（FAIL-OPEN） |
| **V-G11** | 外露审计：`exec_stat_query` 命中能力必须 `visibility=public`；`data` 内不得出现 `signal/order/fill/position` 任何字段 | 启动即失败（硬闸，非 FAIL-OPEN） |
| **V-G12** | 风控五项（单笔名义/单日亏损/持仓数/杠杆/总敞口）任一越界 | 拒单并写 `reject_reason`；`KILL_SWITCH=1` 停止开仓 |

---

## §6 代码落点

```python
# l1agg/capabilities/visual.py
def build_visual(*, capability: str, data: Mapping[str, Any],
                 quality_block: Mapping[str, Any]) -> Optional[Dict[str, Any]]: ...

# l1agg/capabilities/envelope.py
def build(*, capability, intent, answer, data, quality_block, trace_id=None,
          visual: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]: ...
```

- `visual=None` 时不写 `data["visual"]`（零回归）。
- 制品写入：`l1agg/capabilities/visual_store.py`（幂等 `json.dump(sort_keys=True)`，路径 `artifacts/visual/<capability>/<as_of>.json`）。
- T3 组装：`l1agg/capabilities/overview.py`（只读各能力块，不重算）。

---

## §7 验收

| ID | 验收项 | 判据 |
|---|---|---|
| V-AC1 | 基线能力零回归（**按子集断言，不写总数**） | 冻结 `baseline_outlets = [D-A14, D-E01, D-E02, D-E03, D-E04, D-E05, D-E06, D-E07, D-E08, D-E09, D-E10, D-E11, D-E12, D-G22]`；上述每个能力除新增 `visual` 外逐字段相等；并行线继续加出口不影响本断言 |
| V-AC2 | D-E05 matrix | 对称、对角 1、`domain=[-1,1]`、`n_scope="global"` |
| V-AC3 | D-E05 双资产 | 出 `table`，不发热力图 |
| V-AC4 | D-E10 series | ≤500 点，首点 0，末点=`current_drawdown`，`max(y)=mdd` |
| V-AC5 | D-E12 table | 8 列齐全，`n_scope="per_row"` |
| V-AC6 | 降级不产图 | `empty` 无图；`partial` 表格首列含 `degraded_reason` |
| V-AC7 | 开关 | `L1_VISUAL_ENABLED=0` 全无 `visual` |
| V-AC8 | 前端零统计 | 组件内无业务 `reduce/sum` |
| **V-AC9** | T2 平滑可复现 | 同输入同参数 → 同输出；`meta.smoothing` 必填 |
| **V-AC10** | T2 措辞纪律 | 抽检 20 条无「看涨/看跌/建议/目标价/阻力最小方向是」 |
| **V-AC11** | T3 tree 可反查 | 节点≤300；每叶有 `meta.capability` 或 `meta.series_id`；无空节点（缺失必须 `unavailable`+`reason`）✅ `test_t3_tree_leaves_project_capability_blocks_without_recompute` / `test_t3_tree_marks_missing_sources_as_unavailable` |
| **V-AC12** | 制品幂等 | 同 `as_of` 重跑字节一致 |
| **V-AC13** | T3 零重算 | 节点值与来源能力块差 ≤1e-9 ✅ 按 `TREE_LAYOUT` 逐叶断言（含 D-E12 逐行 `n_obs`；0 保留不隐藏） |
| **V-AC14** | 方向可回放 | 同 `rule_version`+`params_hash`+同输入快照 → 同 `direction`/`strength`（字节一致） |
| **V-AC15** | 执行零外露 | 前端/API 全量路由枚举后无任何入口可达 `signal/order/fill/position`；`data` JSON 递归扫描无这些键 |
| **V-AC16** | 风控与 kill switch | 构造越界单 → 被拒且 `reject_reason` 正确；`KILL_SWITCH=1` 后 0 新开仓 |
| **V-AC17** | `direction_rule` 轴分解正确 | 给定固定快照，`axes{trend,adx,inertia,coherence}` 与 §4.7 公式逐项相等；`abs(total) < 30` 时 `direction=0` |
| **V-AC18** | 平仓规则可回放 | 构造四类触发（反向/衰减/结构瓦解/止损），各命中对应 `exit_reason`；无触发时不平仓 |
| **V-AC19** | `visibility` 硬闸 | `assert_public("internal 能力")` 抛 `PermissionError`；前端 12 个 cue 全量枚举后 0 命中 internal |
| **V-AC20** | 波动率缩放仓位 | 同权益、同风险预算下，ATR% 翻倍 → 名义仓位减半（误差 <1%）；超 `max_leverage` 拒绝 |
| **V-AC21** | 相关性簇敞口 | BTC/ETH 同簇合计 > 总敞口 50% → 拒新开仓并写 `reject_reason="cluster_exposure"` |
| **V-AC22** | 规则晋升门禁 | `DSR ≤ 0` 或 `SPA p ≥ 0.05` 的 `rule_version` 禁止接入 L1-X |
| **V-AC23** | 权重无前视 | 把 `as_of` 之后的数据整段删除后重算，`weights_hash` 必须不变 |
| **V-AC24** | 权重约束 | 和为 1（±1e-9）、每轴 ∈ [0.05,0.40]、单次 L1 ≤0.15；违反即拒绝写入 |
| **V-AC25** | 权重可回放 | 同 `weights_version` + 同输入 → 同 `axis_weights`（字节一致） |
| **V-AC26** | 等权否决权 | 构造动态权重样本外输给等权的序列 → `weight_fallback=true` 且实际生效权重 == 等权 |
| **V-AC27** | vintage 隔离 | 同周期出现两次修订时，`as_of` 早于第二次 `observed_at` 的回放只能看到第一次的值 |

---

## §8 路线

| 阶段 | 内容 | 依赖 |
|---|---|---|
| **S0 外露闸**（先行，零决策） | `visibility` 字段 + `manifest.validate` + `assert_public` + `envelope` 键禁入 | 无（B12 处置 §4.8） |
| **S1 曲线生产者** | D-E15 `trend_query`（I02/T08/I32）+ 三处消费者 | 无（B6 处置 §4.9） |
| **T1 表格** | D-E12 对齐切片表 + 方法审计 386×6 矩阵表 + 能力清单表 | B10 基线冻结（✅ 已落地） |
| **T2 曲线** | D-E15 → `series` + 斜率表；D-E10 回撤曲线 | S1（✅ 已落地） |
| **T3 思维导图** | `overview.py` 组合视图（tree）+ 共振网络（graph） | B8 降级契约（✅ 已落地：`test_visual.py` 7 例） |
| **L1-D 方向层**（内部） | `direction_rule` 纯函数（4 窗口）+ `signal` 表；**纸面回放 3 个月** | S1 + 参数确认（B13/B14 已定稿） |
| **P1.5 动态权重**（内部） | 四源权重 + 等权基准对照 + Kalman「真实曲线」；先作为 `direction_rule` 的可选层，默认关闭 | I37 Kalman + I36 分位回归 + ADR-V18/V19；**必须先跑等权对照** |
| **L1-X 信号交接层**（内部） | **L1 不持有下单客户端**：`direction_rule` → `signal` 表 → 幂等 outbox（dedupKey）→ **22 执行**；vol targeting / 风控五项 / 簇敞口 / kill switch 在 L1 侧只做前置校验 | S0 + L1-D 回放 + B16 账户 + 与 22 `FinalDecisionSignal v1.1` 映射（见 §12 `L1X-01/02`） |
| **T4 反思** | 制品落盘 → `thought_tree.py` 读取、48-涌现消费；comparison 用三重障碍 + purge/embargo | B9 + B15（已定稿） |
| **P2 增强** | I39 带通/STL 周期轴；T3 用 Ledoit-Wolf + 风险平价配权；D-E06 稳定性检验 | T4 之后 |

---

## §9 风险

| 风险 | 影响 | 对策 |
|---|---|---|
| 图被当结论 | 用户忽略样本不足 | V-G1/G2 + 降级列 |
| 「阻力最小方向」越界 | 变成 L2 结论 | ADR-V10 白名单 + V-AC10 |
| T2 无数据源 | 曲线层空转 | B6 决策：新增 D-E15 |
| T3 节点伪造 | 全景失真 | V-G9/V-AC11 + `unavailable/proxy` |
| 制品与信封不一致 | T4 读到过期图 | ADR-V12 原子写 + V-AC12 |
| 并行线覆盖 | 改动丢失 | 独立 worktree 或先提交 |
| 大图卡首屏 | 体验 | ADR-V6 上限 |
| SSR 报错 | 页面 500 | `'use client'` + 动态导入 |

---

## §10 边界

- 不改任何统计口径与 `quality` 计算；图只是「已有结果的另一种表达」。
- T2 的平滑/斜率是**新增计算**，但必须走方法层（I02/T08/I32），不得在能力层手写公式。
- T3 不新增数据源、不重算；缺失就降级。
- 不把 `visual` 写进 `quality`，也不在 `data.capabilities` 内重复。

---

## §11 修订记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-11-15 | 初稿：`data.visual`、5 图种、P0 三出口、7 门禁、8 验收 |
| v0.2 | 2026-11-15 | 关闭 B1–B4：D-E10 补回撤路径与峰谷字段；信封按能力 ID 回填；前端补 D-E11/D-E12 cue 与矩阵入口；schema 落 `$defs.visual` |
| v0.3 | 2026-11-15 | **三层递进重评**：T1 表格 / T2 曲线（平滑+斜率+ADX）/ T3 思维导图（tree+graph）/ T4 反思消费者；新增 ADR-V9–V13、V-G8–V-G10、V-AC9–V-AC13；明确 L1/L2 边界与方向措辞白名单；提出 D-E15 曲线生产者方案；出口数按 manifest 实测 **14**（D-A14、D-E01–E12、D-G22），V-AC1 改为按子集断言 |
| v0.4 | 2026-11-15 | **L1 内部方向/执行层（用户修正）**：方向不需要由大模型推理得出，而由「趋势延续+惯性+周期律」的确定性规则产生 → 新增 §1.2 三层与可见性、ADR-V10 改为仅约束对外措辞、新增 ADR-V14–V17（可见性机器强制 / 方向可回放 / 小额硬风控 / L2 对照表）、§4.6 五张内部表、V-G11–V-G12、V-AC14–V-AC16 |
| v0.5 | 2026-11-15 | **三份落地契约**：§4.7 `direction_rule`（四轴打分 + YAML 参数 + 版本 + `exit_rule` 四条平仓触发）、§4.8 `visibility` 外露闸（manifest/manifest.validate/assert_public/envelope 键禁入）、§4.9 D-E15 `trend_query` 完整契约；路线改为 S0 外露闸 → S1 曲线生产者 → T1–T4 → L1-D/L1-X；新增 V-AC17–V-AC19 |
| v0.6 | 2026-11-15 | **成熟经验借鉴 + B13–B17 定稿**：§4.10 引入时序动量（4 窗口含 250 日）、波动率缩放、迟滞死区、元标注（L2 只决定执行与否）、三重障碍、Purged K-Fold+embargo、DSR/SPA 晋升门禁、Ledoit-Wolf+风险平价、领先滞后稳定性、带通/STL 周期、成本模型、相关性簇敞口；§4.11 给出 B13–B17 定稿与 YAML 参数；新增 V-AC20–V-AC22；`windows` 扩为 `[20,60,120,250]`，`exit_threshold` 由 18 改为 12 |
| v0.7 | 2026-11-15 | **美联储方法 + 动态权重**：§4.12 借鉴 DFM/Kalman、MIDAS、协整/ECM、泰勒规则式反应函数、Growth-at-Risk 分位回归、FCI 合成、实时修订（vintage）、不确定性收缩、预测组合与组合之谜、DMA/区制权重；§4.13 定义四源动态权重（prior/reliability/stability/uncertainty）+ 周度再平衡 + 换手上限 + 等权否决权；§4.14 登记 I34 协整 / I35 分位回归 / I36 Kalman / I37 DMA；新增 ADR-V18–V20、V-AC23–V-AC27；路线插 P1.5 |
| v0.8 | 2026-11-15 | **S0 + S1 + B18 落地**：S0 `visibility_default`/`visibility_internal` + `Capability.visibility` + `validate()` 枚举/引用校验 + `assert_public()` 硬闸 + `envelope` 递归键禁入 + 前端 `exec_stat_query` 入口断言；S1 `D-E15 trend_query`（EMA12/26/50 + 20/60/120/250 对数斜率含 se/t/r2 + ADX14 + 降级披露）与 manifest 登记；B18 `mm_metric_vintages` 幂等迁移脚本 + L0 `as_of` As-Of 回放（`observed_at ≤ as_of` 取最晚版本，表缺失时 `vintage_unavailable` 降级不回落 `mm_metrics`）；§4.9 门禁改为 `window > n` 置 null；方法编号冲突修正（协整 I35 / 分位回归 I36 / Kalman I37 / DMA I38 / 带通 STL I39） |
| v0.9 | 2026-11-15 | **T1 表格 + B10 基线冻结落地**：新增 `l1agg/capabilities/visual.py`（`build_visual` 纯函数 + V-G1/G2/G3/G4/G7 门禁 + D-E12 固定 8 列表 + 能力清单表 + 审计 386×6 矩阵）与 `envelope.build(visual=...)` 契约校验（source_capability 必须等于信封能力、rows≤500、spec_version 白名单）；`table.dataset` 增可选 `groups`；D-E12 接图；`BASELINE_OUTLETS` 14 条冻结为测试常量；`tests/test_visual.py` 9 例 · 全量 **739 passed** |
| v0.10 | 2026-11-15 | **T2 曲线落地**：`visual.py` 增 `series` 生产者 —— D-E10 回撤路径（`y`=drawdown，首点 0 / 末点=`current_drawdown` / `max`=`mdd`，无 dates 用索引作 x）与 D-E15 价格+EMA26（`y`=原始价、`smoothed`=EMA26，`meta.smoothing{method:"EMA",window:26}`+`unit/n/periods/slope_windows`）；D-E15 能力块增 `prices` 尾部原始价（加法式，零口径变更）与 `slope_table()` 固定 6 列（`window/slope/se/t/r2/hac_corrected`，空窗口保留 null）；`envelope` 增 series V-G8 校验（非空 points、`meta.smoothing{method,window}`、`meta.n`）；schema `series.points` 增 `smoothed/upper/lower`、`dataset.meta`；`test_visual.py` 17 例全绿 |
| v0.11 | 2026-11-15 | **T3 全景思维导图落地（B8 关闭）**：新增 `l1agg/capabilities/overview.py` —— `build_tree`（根→类别→指标，静态 `TREE_LAYOUT` 逐叶按字段路径原样投影；D-E12 逐行 `n_obs`；S5/资金流/缺源一律 `value=null`+`meta.reason`）与 `build_graph`（仅 D-E05 `gate=="ok"` 产出，节点≤300 / 边≤2000 / `kind` 白名单 / 边必带 `weight`+`p_adj`）；B8 降级契约为代码：`SERIES_REGISTRY` 白名单 + `CRYPTO_SYMBOLS` 作用域 + `proxy/unit/sign_flip` 必填校验；`validate_tree_dataset`/`validate_graph_dataset` 同时被 `envelope._check_visual` 的 tree/graph 分支复用；schema `source_capability` 放宽为 `^(D-[A-Z]\d{2}|T[1-4])$`、graph 边补 `weight/p_adj`；`test_visual.py` 24 例全绿 · 全量 **758 passed** |
| v0.12 | 2026-11-15 | **L1D-01 方向规则落地**：新增 `config/direction_rule.yaml`（`dr-1.0.0`，windows `[20,60,120,250]`、权重 `[0.15,0.25,0.30,0.30]`、进阶 30 / 退出 12 / 迟滞 2 根）与 `l1agg/direction_rule.py`（纯函数 `score/decide`，四轴 40/25/20/15，`t` 与 `slope` 异号记不一致，缺窗口按剩余权重归一 + `degraded_windows`，`p_adj>hac_alpha` 强度轴折半 + `hac_insignificant`，周期律仅记录不进分，`params_hash=sha256(规范参数)`，方向/强度/分档/flags/inputs_snapshot 全落记录）；`tests/test_direction_rule.py` 13 例全绿 |
| v0.13 | 2026-11-15 | **L1D-02 五表账本落地**：新增 `l1agg/trading/store.py` —— `data/trading.db` 建 `signal/order/fill/position/comparison` 五表（外键、CHECK 约束、`UNIQUE(as_of,symbol,rule_version)`）；`signal`/`fill` 由 SQLite 触发器拒绝 UPDATE/DELETE（只追加为机器约束）；`migrate()` 幂等（`IF NOT EXISTS` + `user_version=1`，二次执行 `created=[]`）；`append_signal()` 校验必填/`direction∈{-1,0,1}`/`strength∈[0,1]` 并把 JSON 字段规范序列化；`list_signals()` 仅供内部回放；`tests/test_trading_store.py` 7 例全绿 |
| v0.14 | 2026-11-15 | **L1→22 交接打通**：① `l1agg/handoff.py` —— `signal`→`FinalDecisionSignal v1.1`（crypto 龙头映射 `*-USDT-SWAP`，非加密显式 `HandoffError`；`decision_id` 由 `(symbol,as_of,direction,rule_version,params_hash)` 确定性派生；`payload` 带 `adapter=54-l1`/`as_of`/`l1_*`），映射后过 49 契约 jsonschema；② 49 契约按 ADR-0003 **加法式**增补 `source=l1-chart`（`if/then` 保持 23/50 原 12 字段必填），manifest 重冻（`spec_version=v0.15`），`validate_contracts` 5/5 + 示例 5/5 OK；③ 22 网关 `_PRECHECK_SOURCES=(23-evolution,l1-chart)` + `_precheck_decision`（缺 `decision_id` / `expires_at` 过期即拒，reason 带来源），`from_dict` 的 `action` 增加 `payload.action` 兜底（契约口径，23/50 顶层优先不变）；`test_handoff.py` 7 + `test_l1_chart_gate.py` 6 全绿 |
| v0.15 | 2026-11-15 | **L1D-03/04 落地**：① `l1agg/trading/rule_inputs.py` —— `build_inputs()` 把 `D-E15/D-E11/D-G22/D-E03` 能力块投影为规则入参（零重算；`gate!=ok` → `None`；`p_adj` 缺省由 `t_nw` 的 `erfc` 双侧 p 换算）；② `l1agg/trading/exit_rule.py` —— 四条平仓规则（方向反转 / `|total|<12` 连续 2 根 / `ADX<20 且 EMA mixed` / 硬止损）+ `min_hold_bars=6` 守卫 + 止损绕过；`test_rule_inputs_exit.py` 14 例全绿 · 54 套件 **811 passed / 6 既有失败**（`test_capabilities.py` 的 `D-G19` 未接线，非本批引入） |
| v0.16 | 2026-11-15 | **L1D-05 纸面回放落地**：新增 `l1agg/trading/paper_replay.py` —— `replay()` 从 `warmup=250` 起逐根「`stats.trend` → `rule_inputs.build_inputs` → `direction_rule.decide` → `exit_rule.evaluate`」，**信号在下一根收盘成交**（`pending` 机制，避免同根信息偏差）；输出 `signals`（含 `inputs_snapshot`/`params_hash`）、`trades`、`metrics{bars,n_entries,n_closed,win_rate,avg_ret,cum_ret,turnover}`、`replay_key=sha256(signals 五字段规范投影)`；`persist_signals()` 写 `trading.db` 并把 `UNIQUE` 冲突计为 `duplicates`（断点重放不重复）；`tests/test_paper_replay.py` **7 passed** |
| v0.17 | 2026-11-15 | **L1D-06/07 持仓管理与风控落地**：① `l1agg/trading/sizing.py` —— vol targeting（`clip(0.02/vol,0,3)`）→ `notional=equity×strength×scale` → `qty=notional/price`，`direction=0` 不下单，波动率只取 L1-S 输入不重算；② `l1agg/trading/risk.py` —— 五项常量（500/100/3/2.0/1500）+ `RISK_VERSION`、`L1_KILL_SWITCH`（只停新开仓、平减仓放行）、六类拒因固定顺序、`record_rejected_order()` 写 `order(status='rejected', reject_reason)`；§4.7 补两组常量口径；`tests/test_sizing_risk.py` **12 passed** |
| v0.18 | 2026-11-15 | **L1X-03 outbox 幂等投递落地**：新增 `l1agg/trading/outbox.py` —— 独立 `data/outbox.db`（不改五表），`dedup_key=sha256({"decision_id":…})`（无 `decision_id` 时退化为 `symbol/as_of/direction/rule_version/params_hash`）；`enqueue()` 同键返回 `duplicate` 且不改原行；状态机 `queued→sent`/`queued→failed→sent`，`replay_pending()` 把发送异常/`False` 记 `failed` 并 `attempts+1`，已 `sent` 永不再发；`tests/test_outbox.py` **7 passed** |
| v0.19 | 2026-11-15 | **DOC-01/02 收尾**：① `0-系统文档管理/INDEX.md` v2.20 新增「54-L1架构能力聚合层」小节（母 SPEC / 本 SPEC / T0 SPEC / 技术设计 / 方法库 / 能力清单 / 评审报告 / `l1agg/trading/` 共 8 条）；`link_checker.py` 610 链接 / 2 条断链均为 `archive/trae-documents/` 存量；② `49-交易框架协议/SPEC.md` §3.8 更名「L1 闭环工具面 MCP」并加命名澄清注（L1-S public / L1-D internal / L1-X 只把 `l1-chart` 交接 22，ADR-0003），10 工具契约不变 |
| v0.20 | 2026-11-15 | **P2 三项收口**：① `l1agg/trading/cluster.py` —— D-E05 矩阵 `|ρ|≥0.70` 并查集聚类 + 同簇敞口占比闸门，`risk.check_order` 新增 `cluster_exposure_usdt`（`cluster_exposure_cap_pct=0.50`，拒因 `cluster_exposure`），`sizing` 透传（7 例）；② `l1agg/trading/weights.py` —— 四轴动态权重（∈[0.05,0.40]、换手 ≤0.15、`weights_hash`），等权否决门 `n≥250 且超额>0 且 p<0.05`，不达标退回等权 + `weight_fallback`，**默认关闭**（6 例）；③ `l1agg/trading/comparison.py` —— 对照表同键幂等 + L2 不可覆盖 L1-D + 三重障碍事后打分（扣 5bps/边 + 0.5×ATR）回写 `realized_ret/scored_at`（8 例）；§4.7 补齐四组口径；54 套件 **867 tests / 867 passed** |
| v0.21 | 2026-11-15 | **美联储方法逐条落地**：① 新增 `l1agg/methods/fed_methods.py` —— I35 协整（临界值 ADF）、I36 分位回归（QuantReg）、I37 Kalman 局部线性趋势（常方差、非 MLE）、I38 DMA 遗忘因子、I39 带通/周期；`GROUP_CAPACITY["I"]=34→39`，audit **242/242 PASS**（catalog 243、登记 392）；② D-E15 增 `kalman` 块（level/slope/±1σ/slope_se/trail），`meta.smoothing` 仍为 EMA，<250 点降级 `kalman_unavailable`；③ `direction_rule` v1.1.0 —— `axis_weights` 参数化 + 可选 `gap` 轴（默认关闭、均值回归符号、±1 截断）+ `midas` 开关 + `strength_mode=quantile_dispersion`；④ `weights.py` v1.1.0 —— `prior×(|IC|+ε)/(σ+ε)` → simplex → clip → α=0.1 部分调整 → 换手限速，周度 `W-MON` 冻结、回放锁、`λ_u` 收缩、`weight_sources` 五源；⑤ `store.py` schema v2 —— `signal` 增 5 个权重字段（幂等 ALTER）；⑥ B18 写入路径接上 `mm_metric_vintages`（`upsert_metric` 先追加观测再覆盖主表，同秒修订 observed_at 单调 +1s）；新增 `tests/test_fed_methods.py`（I35–I39 + 4 工具，14 例）、`test_weights.py` 7 例、`test_direction_rule.py` 7 例、`test_visual.py` 2 例、`test_trading_store.py` 2 例、DAL `tests/test_mm_metric_vintage_write.py` 3 例；54 套件 **904 passed** |
| v0.22 | 2026-11-15 | **动态权重接入实盘切换（L1D-11）**：新增 `l1agg/trading/weight_switch.py` —— 三档灰度 `off`（默认，静态 40/25/20/15，字节不变）/ `shadow`（算并落库、不注入）/ `on`（过等权否决门才注入）；开关「显式参数 > `L1_DYNAMIC_WEIGHTS` > `config/weights.yaml` > off」，非法值 `WeightSwitchError` fail-closed；`load_state()` 从 `trading.db.signal` 恢复 `previous_weights`/`last_effective_date`/`weight_fallback`，同 ISO 周内**权重与注入判定一起冻结**；`oos_excess_series()` 用已实现标签构造等权对照（不引入前视）；`apply_to_params()` 注入后 `params_hash` 随之变化可回放；`recorded_weights()` 让否决期落静态先验（避免等权对照退化成全 0、门永久锁死）；`paper_replay.replay()` 逐根用**单位轴值**（`axis_weights=1`，IC 对正数缩放不变）估权重、把 5 个权重字段落 `signal`、payload 增 `weights{mode,n_updates,n_frozen,n_fallback}`，并支持 `db_path` 跨运行续状态；新增 `tests/test_weight_switch.py` **10 例** + `test_paper_replay.py` **+5 例**；本次相关 5 套件 **63 passed**，54 全量通过。**真实数据实测（BTC/USDT 日线 700 根，2024-12-15~2026-11-14）**：65 次周度再平衡全部被等权否决门拦下（`n=250`，`excess_mean≈-1.1e-4`，`p≈0.83`），故 `on` 与 `off` 决策、胜率、换手完全一致——接线与门禁按预期工作，但静态先验在样本外尚未跑赢等权，**动态权重暂不具备开闸证据**（晋级需先让 `oos_excess` 转正） |

---

## §12 待完成项台账与验收（2026-11-15）


> 本表是 L1（统计图表 → 方向 → 交接 22）的唯一待办台账。**每完成一项**：把状态改为 `✅ 已验收`，在「验收证据」列补命令/文件/测试结果，并在 §12.3 追加一行；未验收不得改状态。L1 不持有下单客户端，交易统一由 22 执行。

### 12.1 状态图例

`⬜ 待办` · `🟡 进行中` · `✅ 已验收` · `⛔ 阻塞`

### 12.2 台账

#### A. L1-S 公开面（数据 / 衍生数据 / 图表 / 新闻）

| ID | 级别 | 事项 | 验收标准（可复测） | 状态 | 验收证据 |
|---|---|---|---|---|---|
| L1S-01 | P0 | 基本面下新增「数据与图表」tab（当前只有独立页 `/dashboard/visual`） | 基本面 tabs 出现该 tab；切换后渲染 tree/graph/series/table；`pnpm tsc --noEmit` 通过；空数据降级不报错 | ✅ 已验收（2026-11-15） | 抽出 `components/visual/VisualWorkbench.tsx` 双端复用；`fundamental/page.tsx` 新增 `charts` tab；`npx tsc --noEmit` exit 0；`jest src/components/visual` 2 passed；`fundamental-panels-query` 5 passed |
| L1S-02 | P0 | 资产池改为后端龙头注册表驱动（BTC/黄金/原油/三大美股指数/美股代币龙头/VIX），前端零硬编码 | `/api/visual/overview` 返回的 `assets` 与 `leader_registry` 绑定集合一致；未绑定资产显式 `unavailable`；单测断言默认池 | ✅ 已验收（2026-11-15） | `leader_registry.DEFAULT_POOL/default_pool()`（10 个：BTC/XAU/CL/US500/US100/DJIA/VIX/NVDA/AAPL/TSLA）；`visual_overview.py` 删除 `DEFAULT_ASSETS` 改读注册表；COIN/MSTR 入 `UNBOUND` 显式登记；`pytest test_leader_registry.py` 13 passed；实跑 `assets` 与注册表一致、`unavailable=[]`、5 张图 |
| L1S-03 | P1 | 新闻纳入 L1-S 统一出口（只读、无方向措辞） | AGENT 工作台问新闻返回统一信封（capability/as_of/source/items）；禁用词扫描通过 | ✅ 已验收（2026-11-15，后端出口；前端 `dashboard/news` 迁移另立项） | 新增 **D-E20**（manifest 50 → **51** 条）：`l1agg/capabilities/news.py::news_digest` 只读 `mm_metrics.social_volume` 的 `news_count_24h`/`social_volume` 观测 → `envelope.build` 统一信封（`capability=D-E20`/`intent=trend_query`/`answer`/`data.source`/`data.items`/`quality`），零重算、不做情绪打分；`scan_forbidden` 命中「看涨/看跌/建议买入/建议卖出/目标价/多头/空头/推荐」即抛 `ValueError`；无条目表不编造标题/正文/链接；`as_of` 严格截断；<2 天 → empty、条数部分缺失 → partial；`stats.py` 已登记调度且 `supported()` 含 D-E20；`tests/test_news_digest.py` **7 passed**；真实库 `as_of=2026-11-14` → `ok=True / good / 38 条观测 / 缺失 0 天`；54 模块全量 `pytest tests -q` EXIT=0 |
| L1S-04 | P1 | T1–T3 制品落盘（ADR-V12） | 每次产图写 `artifacts/visual/<capability>/<as_of>.json`；重复执行字节一致；幂等单测 | ✅ 已验收（2026-11-15） | `l1agg/persistence/artifacts.py`（`write_artifact`/`read_artifact`/`list_artifacts`/`persist_visuals`）：规范 JSON（`sort_keys` + 固定分隔符 + 末尾 LF）+ 临时文件 `os.replace` 原子写 + 路径 token 白名单 + `L1_ARTIFACTS_ENABLED` FAIL-OPEN；`visual_overview.py` 产图后按 `source_capability` 分组落盘并回显 `artifacts{written,unchanged,errors}`；`tests/test_artifacts.py` **14 passed**；实跑 `--days 400` 首次 ✅ 写 7 个能力（D-E10/E12/E15/E16/E17/E18/T3），二次 exec **全部 `unchanged`**、零重写 |
| L1S-05 | P2 | T4 反思消费接线（33/48 读制品） | 读侧 smoke：`thought_tree.py` 能加载最新制品并回显 capability 列表 | ✅ 已验收（2026-11-15） | `l1agg/persistence/artifacts.py::consume_latest`（逐能力取最新 + 全局 `as_of` + 空态 `ok=True`）+ `33-REA.../core/reflection/thought_tree.py::load_l1_visual_artifacts`（sys.path 桥接 + FAIL-OPEN）；`tests/test_artifacts.py` **16 passed**、`33-REA.../tests/test_l1_artifacts_smoke.py` **2 passed**；真实制品 smoke → `capabilities=['D-E10','D-E12','D-E15','D-E16','D-E17','D-E18','T3']`、`as_of=2026-11-11` |
| L1S-06 | P2 | SPEC 状态刷新（头部 / §2 出口数） | 头部状态与 §2 计数和 `capability_manifest.yaml` 实测一致 | ✅ 已验收（2026-11-15） | 机检脚本：manifest 实测 **50 条**（ID 唯一 50）；`TECHNICAL_DESIGN.md` 头部「48 → **50 个**」+ §2.5「50 个可执行出口」「唯一事实源（50 条）」、母 SPEC §588「manifest 共 50 条能力声明」三处全部 =50；`stats.py` 非私有编排函数 **47** 与 manifest `capabilities.stats.*` 引用数 **47** 一致；`pytest tests/test_capabilities.py` 全绿（同批 B-03 新增 D-E20 后已同步刷新为 **51**：TD 头部/§2.5 三处 + 母 SPEC 头部/§588） |

| L1S-07 | P0 | B18 vintage 写入路径（修订不覆盖旧观测） | 每次采集追加 `mm_metric_vintages`；As-Of 只读 `observed_at ≤ as_of` | ✅ 已验收（2026-11-15） | `market_macro_impl.upsert_metric` 覆盖主表前先 `INSERT OR IGNORE` 追加观测（缺表自动建表建索引，同周期同秒 `observed_at` 单调 +1s）；`19-数据访问层/tests/test_mm_metric_vintage_write.py` **3 passed**（主表覆盖 / vintage 不丢观测 / As-Of 截断） |

#### B. L1-D 方向层（internal，永不进信封）

| ID | 级别 | 事项 | 验收标准（可复测） | 状态 | 验收证据 |
|---|---|---|---|---|---|
| L1D-01 | P0 | `direction_rule` 纯函数 + YAML 参数 + `rule_version`/`params_hash` | 同输入同参数字节一致；四轴打分与 §4.7 一致；单测覆盖 flat / 多 / 空 / 降级 | ✅ 已验收（2026-11-15） | `config/direction_rule.yaml`（`dr-1.1.0`：`axis_weights` 参数化 + 可选 gap 轴 + `midas` 开关 + `strength_mode`）+ `l1agg/direction_rule.py`（`score/decide/params_hash`）＋ `tests/test_direction_rule.py` **20 passed**（long 94 / short −97 / flat 4 / 全缺降级 / 缺窗归一 / t 异号 / HAC 折半 / 周期律仅记录 / 字节一致） |
| L1D-02 | P0 | `data/trading.db` 五表（signal/order/fill/position/comparison）建表与迁移 | 迁移幂等；signal 只追加不可变；表结构断言 | ✅ 已验收（2026-11-15） | `l1agg/trading/store.py`：`migrate()` 二次执行 `created=[]` 且 `user_version=2`（v2 补 5 个权重列，幂等 ALTER）；`signal`/`fill` UPDATE/DELETE 抛 `sqlite3.IntegrityError`（触发器）；`UNIQUE(as_of,symbol,rule_version)` 拒重复；FK/CHECK 生效；`append_signal` 契约校验；`tests/test_trading_store.py` **9 passed** |
| L1D-03 | P1 | 规则入参构造器（D-E15 / D-E11 / D-G22 / D-E03 → 规则输入） | 只读能力块、不重算；缺失轴按 `coherence_missing` / `null` 降级；单测 | ✅ 已验收（2026-11-15） | `l1agg/trading/rule_inputs.py`：`build_inputs()` 仅投影 `slope_table/adx14/ema/same_direction_rate`；`gate!=ok` 或缺失 → `None`（由规则打降级旗标）；`p_adj` 优先取块内值，否则 `erfc(|t_nw|/√2)` 换算（不重估）；`build_inputs → decide` 直连得 40/25/20/15 四轴；`test_rule_inputs_exit.py` 14 例全绿 |
| L1D-04 | P1 | `exit_rule` 四条 + `min_hold_bars=6` + 迟滞 2 根 | 四条触发各 1 例；止损不受 `min_hold_bars` 限制；单测 | ✅ 已验收（2026-11-15） | `l1agg/trading/exit_rule.py`：方向反转 / `|total|<12` 连续 2 根 / `ADX<20 且 EMA mixed` / 硬止损；规则 1–3 受 `min_hold_bars=6` 约束（`MIN_HOLD_GUARD` + `blocked_by_min_hold`），止损 `stop_loss_bypass` 直接平；`low_bars` 在阈值上方自动归零；8 例覆盖 |
| L1D-05 | P1 | 纸面回放 3 个月 | 产出 `signal` 历史 + 胜率/换手；同一 `as_of` 可重放 | ✅ 已验收（2026-11-15） | `l1agg/trading/paper_replay.py`：逐根 `stats.trend`→`build_inputs`→`decide`→`exit_rule`，**下一根收盘成交**；`metrics` 含 `bars/n_entries/n_closed/win_rate/avg_ret/cum_ret/turnover=2×开仓数/根数`；`replay_key=sha256(signals 规范投影)` 同输入字节一致、改参数即变；`persist_signals()` 落 `trading.db`（二次全 `duplicates`，不重复写）；`tests/test_paper_replay.py` **7 passed** |
| L1D-06 | P1 | 持仓管理（vol targeting → target position） | 输出内部仓位建议并受风控五项约束；单测 | ✅ 已验收（2026-11-15） | `l1agg/trading/sizing.py`：`vol_scale=clip(0.02/vol,0,3)`、`notional=equity×strength×scale`、`qty=notional/price`；`direction=0` → `no_direction` 不下单；越界由 `risk.check_order` 拒（不截断）；`tests/test_sizing_risk.py` 中 5 例（目标/缩放/空信号/非法入参/确定性）通过 |
| L1D-07 | P1 | 风控五项常量 + `KILL_SWITCH` | 越界拒单并写 `reject_reason`；kill switch 停止新开仓；单测 | ✅ 已验收（2026-11-15） | `l1agg/trading/risk.py`：五项常量（500/100/3/2.0/1500）+ `RISK_VERSION`；`L1_KILL_SWITCH=1` 只拦新开仓、`is_new=False` 放行；六类拒因命中即拒（顺序固定）；`record_rejected_order()` 写 `order(status='rejected', reject_reason)`；`tests/test_sizing_risk.py` **12 passed** |
| L1D-08 | P2 | P1.5 动态权重（四源 + 等权否决） | 样本外不胜等权 → `weight_fallback=true`；默认关闭 | ✅ 已验收（2026-11-15，P2） | `l1agg/trading/weights.py`（v1.1.0）：`w* ∝ prior×(|IC|+ε)/(σ+ε)` → simplex → clip [0.05,0.40] → `w_t=0.9w_{t-1}+0.1w*` → 单次换手 L1 ≤0.15；周度 `W-MON` 冻结（`weights_frozen`）、纸面回放锁（`weights_locked_replay`）、`λ_u∈[0,0.5]` 向先验收缩、估计窗口 <500 日标 `estimation_window_lt_500`；`oos_gate` 要求 n≥250 且 `excess_mean>0` 且单边 p<0.05，否则退回等权 + `weight_fallback=true`；`enabled=False`（默认）返回 `STATIC_WEIGHTS` 并标 `dynamic_disabled`；输出 `weight_sources{prior,ic,sigma,reliability,uncertainty,stability}` + `axis_weights{gap}` + `weights_hash`；`tests/test_weights.py` **13 passed** |
| L1D-10 | P1 | 美联储调研方法逐条落地（I35 协整 / I36 分位回归 / I37 Kalman / I38 DMA / I39 带通） | 5 个方法登记且 audit 全 PASS；D-E15 出 Kalman 置信带且 `meta.smoothing` 不变；gap 轴默认关闭、开启后进 `axes` | ✅ 已验收（2026-11-15） | `l1agg/methods/fed_methods.py`（`GROUP_CAPACITY["I"]=39`，audit 242/242 PASS）；`midas_weights` / `taylor_gap` / `fci_composite`（Ledoit-Wolf+风险平价）/ `uncertainty_index`；D-E15 payload 顶层 `kalman{level,slope,level_sigma,slope_se,band,trail}`，<250 点降级 `kalman_unavailable`；`rule_inputs.build_inputs` 可透传 `equilibrium_gap`/`forward_distribution`；`tests/test_fed_methods.py` **14 passed**、`test_visual.py` +2 |
| L1D-09 | P2 | `comparison` 表 + 事后收益打分 | 同 `as_of+symbol` 写入并打分；L2 不可覆盖 L1-D | ✅ 已验收（2026-11-15，P2） | `l1agg/trading/comparison.py`：`record_comparison` 同键幂等、方向/强度不一致抛 `ComparisonError`（L2 不可覆盖 L1-D），`l2_verdict` 首写优先；`triple_barrier` 按 ±2×ATR 或 10 根先到者定标签，扣 5bps/边 + 0.5×ATR 滑点；`score_comparison` 回写 `realized_ret/scored_at`；`tests/test_comparison.py` **8 passed** |
| L1D-11 | P0 | 动态权重接入实盘切换（三档灰度 + 跨运行状态 + 否决门注入判定） | 默认 `off` 时回放字节不变；`shadow` 落权重不改决策；`on` 仅过门注入、未过沿用静态先验；同 ISO 周内权重与注入判定一起冻结；跨运行从 `signal` 恢复；非法开关值 fail-closed | ✅ 已验收（2026-11-15） | `l1agg/trading/weight_switch.py`（`MODES=off/shadow/on`、`resolve_mode` 显式>env>yaml>off、`load_state` 从 `signal` 恢复 4 轴归一权重 + `weight_fallback`、`oos_excess_series` 等权对照、`apply_to_params` 注入）+ `config/weights.yaml`（默认 off）+ `paper_replay.replay(weights_mode/weight_state/weights_locked/db_path)` 逐根传 `axis_weights` 并落 5 个权重字段、payload 增 `weights{mode,n_updates,n_frozen,n_fallback}`；`tests/test_weight_switch.py` **10 passed** + `tests/test_paper_replay.py` 新增 5 例（默认静态 / shadow 不改决策 / on 未过门不注入 / 同周冻结 / 从 DB 续状态），本次相关 5 套件 **63 passed**、54 全量通过 |

#### C. L1 → 22 交接（L1 不执行）

| ID | 级别 | 事项 | 验收标准（可复测） | 状态 | 验收证据 |
|---|---|---|---|---|---|
| L1X-01 | P0 | L1 `signal` → 22 `FinalDecisionSignal v1.1` 映射 | 映射函数 + jsonschema 校验；不改 22 既有字段口径 | ✅ 已验收（2026-11-15） | `l1agg/handoff.py`（`build_final_decision` / `validate_final_decision`）+ 49 契约加法式增补 `l1-chart` 来源（ADR-0003，`if/then` 保 23/50 原 12 字段必填不变）；`pytest tests/test_handoff.py` **7 passed**；`validate_contracts.py` 5 契约 + 5 示例全 OK |
| L1X-02 | P0 | 22 对 `source=l1-chart` 强制 `decision_id`/`expires_at` | 缺 `decision_id` 拒；过期拒；新增单测 | ✅ 已验收（2026-11-15） | `trade_execution_gateway.py`：`_PRECHECK_SOURCES=(23-evolution,l1-chart)` + `_precheck_decision`（reason 带来源）；`tests/test_l1_chart_gate.py` **6 passed**（缺 id 拒 / 过期拒 / 通过前置后进 13 / 23 源回归 / 其他源不拦 / 审计落盘） |
| L1X-03 | P1 | outbox 幂等（dedupKey）+ 失败重投 | 重复 signal 只执行一次；断点重投不重复 | ✅ 已验收（2026-11-15） | `l1agg/trading/outbox.py`：独立 `data/outbox.db`（不动已验收五表），`dedup_key=sha256(decision_id)`（缺省用 `symbol/as_of/direction/rule_version/params_hash`）；同键二次入队返回 `duplicate` 且不改原行；`replay_pending()` 发送失败记 `failed`+`attempts+1`、成功记 `sent` 且不再重发；`tests/test_outbox.py` **7 passed** |
| L1X-04 | P2 | 簇敞口（D-E05 聚类）≤ 总敞口 50% | 同簇两仓被拒或降仓；单测 | ✅ 已验收（2026-11-15，P2） | `l1agg/trading/cluster.py`：`clusters()` 用 `|ρ|≥0.70` 并查集聚类（簇号按出现顺序 `c1…`）；`check_cluster_exposure()` 计算「含新单同簇敞口 / 含新单总敞口」，>50% → `reject_reason="cluster_exposure"`；`risk.check_order` 新增 `cluster_exposure_usdt`（排在 gross 与 notional 之间）+ `cluster_exposure_cap_pct=0.50`，`sizing.target_position` 透传；`tests/test_cluster_exposure.py` **7 passed** |

#### D. 文档与索引

| ID | 级别 | 事项 | 验收标准（可复测） | 状态 | 验收证据 |
|---|---|---|---|---|---|
| DOC-01 | P1 | `0-系统文档管理/INDEX.md` 补 54 条目 | INDEX 可检索到 54；`link_checker` 通过 | ✅ 已验收（2026-11-15） | INDEX v2.20 新增「54-L1架构能力聚合层」小节 8 行（母 SPEC v1.20 / 本 SPEC v0.18 / T0 SPEC v1.6 / TECHNICAL_DESIGN / METHOD_LIBRARY / capability_manifest / 评审报告 / `l1agg/trading/`）；`link_checker.py` 610 链接 / 2 存量断链（均在 `archive/trae-documents/`，非本次变更） |
| DOC-02 | P1 | 49 §3.8「L1 交易层 MCP」改名/加注（与 54 的 L1 区分） | 49 与 54 不再同名冲突；评审可区分 | ✅ 已验收（2026-11-15） | `49-交易框架协议/SPEC.md` §3.8 标题改为「L1 闭环工具面 MCP（`l1.trading.mcp`，10 工具）— 历史名…」并加命名澄清注（L1-S/L1-D/L1-X 分层 + `l1-chart` → 22 + ADR-0003 链接）；10 工具契约与调用方未改 |

### 12.3 执行顺序与验收记录

顺序：`L1S-01` → `L1S-02` → `L1D-01` → `L1D-02` → `L1X-01` → `L1X-02` → 其余按级别推进。

| 日期 | ID | 状态 | 验收证据 |
|---|---|---|---|
| 2026-11-15 | — | 台账建立 | 本节 |
| 2026-11-15 | L1S-01 | ✅ 已验收 | `tsc --noEmit` exit 0；`jest src/components/visual` 2 passed；`fundamental-panels-query` 5 passed |
| 2026-11-15 | L1S-02 | ✅ 已验收 | `pytest test_leader_registry.py` 13 passed；实跑默认池 10 资产全 available、5 张图 |
| 2026-11-15 | L1D-01 | ✅ 已验收 | `pytest tests/test_direction_rule.py` 13 passed；四轴 40/25/20/15 与 §4.7 一致、`params_hash` 可回放 |
| 2026-11-15 | L1D-11 | ✅ 已验收 | `pytest tests/test_weight_switch.py tests/test_paper_replay.py tests/test_weights.py tests/test_trading_store.py tests/test_direction_rule.py` **63 passed**；默认 `off` 决策与权重哈希不变、`on` 未过否决门不注入 |
| 2026-11-15 | L1D-02 | ✅ 已验收 | `pytest tests/test_trading_store.py` 7 passed；迁移幂等（`created=[]`）、signal/fill 只追加触发器 |
| 2026-11-15 | L1X-01 | ✅ 已验收 | `pytest tests/test_handoff.py` 7 passed；49 契约 `validate_contracts` 5/5 + 示例 5/5 OK；BTC→`BTC-USDT-SWAP`、XAU/CL/US500 显式拒绝 |
| 2026-11-15 | L1X-02 | ✅ 已验收 | `pytest tests/test_l1_chart_gate.py` 6 passed；`source=l1-chart` 缺 `decision_id` → `MISSING_DECISION_ID`、过期 → `SIGNAL_EXPIRED`；23 源行为回归不变 |
| 2026-11-15 | L1D-03 | ✅ 已验收 | `pytest tests/test_rule_inputs_exit.py`（入参 6 例）passed；`build_inputs → decide` 四轴 40/25/20/15；空能力块全 `None` 降级 |
| 2026-11-15 | L1D-04 | ✅ 已验收 | 同文件 8 例：四条规则各 1 例、`min_hold` 拦截规则 1–3、止损绕过 `min_hold`、`low_bars` 归零；54 套件 811 passed / 6 既有失败（D-G19 未接线） |
| 2026-11-15 | L1D-05 | ✅ 已验收 | `pytest tests/test_paper_replay.py` **7 passed**（3.9s）：`replay_key` 同输入一致 / 改 `flat_threshold` 即变、signal 历史 130 根有序且字段齐、`metrics` 胜率与 `turnover=2×n_entries/bars` 自洽、首笔成交落在首个非零 signal 的**下一根收盘**、`persist_signals` 二次落库全 `duplicates`、样本不足抛 `ValueError` |
| 2026-11-15 | L1D-06 | ✅ 已验收 | `sizing.py`：vol 0.02→scale 1、0.01→2、0.004→3（封顶）；equity 400 + strength 1 + vol 0.02 → notional 400 / qty 4 / leverage 1.0；同参重复调用返回完全相同的 dict |
| 2026-11-15 | L1D-07 | ✅ 已验收 | `pytest tests/test_sizing_risk.py` **12 passed**：五类越界各 1 例（daily_loss/positions/leverage/gross/notional）+ kill switch 拦新开仓但放行 `is_new=False` + 拒单真实落到 `order` 表（`status='rejected'`，未知拒因抛 `ValueError`） |
| 2026-11-15 | L1X-03 | ✅ 已验收 | `pytest tests/test_outbox.py` **7 passed**：同决策二次入队 `duplicate`（仅 1 行）、`dedup_key` 与 `sha256({"decision_id":…})` 一致且随 `as_of`/方向变化、发送异常 → `failed`+`attempts=1` 后重投成功、已 `sent` 不再重发（第二次 `sent=0`）、`send→False` 记 `send_returned_false`、不同信号两行 |
| 2026-11-15 | DOC-01 | ✅ 已验收 | `0-系统文档管理/INDEX.md` v2.20 新增 54 小节（8 条目的链接均可解析）；`link_checker.py --summary` → 610 链接 / 2 断链，2 条均为 `archive/trae-documents/performance-adaptive-capital-allocator-spec.md` 存量问题 |
| 2026-11-15 | DOC-02 | ✅ 已验收 | `49-交易框架协议/SPEC.md` §3.8 已改名并加注；文档内链接 `./docs/adr/ADR-0003-l1-chart-source.md` 存在 |
| 2026-11-15 | 全量回归 | ✅（1 项既有失败） | `pytest 54-L1架构能力聚合层/tests` → **843 tests / 842 passed / 1 failure**；唯一失败为 `test_capabilities.py::test_manifest_loads_and_validates`（期望 `D-G20` 已登记，manifest 实无此 ID，属并行线未接线，非本批引入）；`22-执行引擎中心/tests/test_l1_chart_gate.py` **6 passed** |
| 2026-11-15 | L1S-04 | ✅ 已验收 | `l1agg/persistence/artifacts.py` + `visual_overview.py` 接线；`pytest tests/test_artifacts.py` **14 passed**（幂等/原子/路径安全/FAIL-OPEN）；实跑首次写 7 能力、二次全部 `unchanged` |
| 2026-11-15 | L1S-03 | ✅ 已验收 | 新增 D-E20（manifest **51** 条）：`capabilities/news.py::news_digest` 只读 `social_volume` 观测成统一信封 + `scan_forbidden` 自检禁用词 + 无条目表不编造；`pytest tests/test_news_digest.py` **7 passed**；真实库 38 条观测 / good；54 全量 EXIT=0 |
| 2026-11-15 | L1S-05 | ✅ 已验收 | `consume_latest` + `thought_tree.load_l1_visual_artifacts`；`pytest tests/test_artifacts.py` **16 passed**、`33-REA/tests/test_l1_artifacts_smoke.py` **2 passed**；真实制品回显 7 个 capability |
| 2026-11-15 | L1S-06 | ✅ 已验收 | manifest 实测 50 条 / ID 唯一 50；`TECHNICAL_DESIGN.md`（头部 + §2.5 三处）与母 SPEC §588 计数全部 =50；`stats.py` 编排函数 47 = manifest `stats.*` 引用 47；`pytest tests/test_capabilities.py` 全绿 |
| 2026-11-15 | L1X-04 | ✅ 已验收（P2） | `pytest tests/test_cluster_exposure.py` **7 passed**：ρ0.92 → BTC/ETH 同簇、GOLD 独立；阈值 0.95 时拆簇；同簇合计 400+100=500；含新单 700/1000 → 拒 `cluster_exposure`；300/1100 → 放行；`risk.check_order` 与 `sizing.target_position` 均按簇拒 |
| 2026-11-15 | L1D-08 | ✅ 已验收（P2） | `pytest tests/test_weights.py` **6 passed**：默认 `enabled=False` 返回静态权重 + `dynamic_disabled`；`oos_gate` 三档（无样本/负超额/显著正超额）；门未过 → 等权 + `weight_fallback`；过门后权重 ∈[0.05,0.40] 且趋势轴最大；`previous_weights=EQUAL` 时换手 ≤0.15；两次调用结果完全一致 |
| 2026-11-15 | L1D-09 | ✅ 已验收（P2） | `pytest tests/test_comparison.py` **8 passed**：同键幂等、L2 改方向/强度抛 `ComparisonError`、`l2_verdict` 首写优先；上/下障碍各 1 例（gross 0.02 → 扣 0.006 → net 0.014）；10 根时间退出 net −0.006；`score_comparison` 回写 `realized_ret/scored_at` 且 L1 字段不变；`direction=0` 记 0 + `flat_position` |
| 2026-11-15 | 全量回归（P2 后） | ✅ 0 失败 | `pytest 54-L1架构能力聚合层/tests` → **867 tests / 867 passed**（并行线补齐 `D-G20` 后此前那 1 项既有失败已消失） |
