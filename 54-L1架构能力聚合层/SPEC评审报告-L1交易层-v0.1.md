# 评审报告 — SPEC-54 L1 交易层（v0.1）

- **评审对象**: [SPEC-54-L1交易层.md](./SPEC-54-L1交易层.md) v0.1（双维度：A 交易链路闭环 / B 前端图表）
- **代码对象**: [visual.py](./l1agg/capabilities/visual.py)、[envelope.py](./l1agg/capabilities/envelope.py)、[overview.py](./l1agg/capabilities/overview.py)、[leader_registry.py](./l1agg/leader_registry.py)、[asset_pool.py](./l1agg/asset_pool.py)、[coverage_audit.py](./scripts/coverage_audit.py)、[asset_pool.yaml](./config/asset_pool.yaml)、[weights.yaml](./config/weights.yaml)、[paper_replay.py](./l1agg/trading/paper_replay.py)、[weight_switch.py](./l1agg/trading/weight_switch.py)
- **评审日期**: 2026-11-15 ｜ **方式**: 文档逐节 + 代码逐行（含行级引用）+ 门禁口径复算 + OKX/本地库真实覆盖复核
- **结论**: **有条件通过（3.30 / 5.0）**；**B-LT1…B-LT5 为 P0 阻断**（不修就无法落码），B-LT6…B-LT11 可边落地边修，B-LT12 为 P2

> 条件：允许先落 **LTL-01/02（资产池 v2，纯配置+注册表+单测）**；**禁止**在 B-LT1/B-LT2/B-LT3 关闭前写 `D-E16/D-E18/lights` 生产者；**禁止**在 B-LT5 关闭前跑 `coverage_audit`（会把全部美股判成不合格）。

---

## §1 RFD（裁决理由）

**采纳理由**：v0.1 的骨架是对的——它把用户的两句话（交易链路闭环 / 前端图表）落成两条可分别验收的线，且没有新造分类、没有新造方法、没有越界到执行层。`D-E16`（聚合曲线）、`D-E19`（点亮）确实填了现存的真空白：目前 `series` 只能画单序列，`direction_rule` 的轴值只在 internal `signal` 里，前端看不到「哪一维在亮」。权重二分（`chart_weights` 默认开 / 交易轴权重默认 on 但受否决门）也正确回应了用户「动态权重不需要关闭」的纠正。

**不否决理由**：全部阻断项都在能力层/配置层内部可闭环，不涉及统计口径变更、不改 22 契约、不动既有 `signal` 表结构。

**保留理由（P0，5 条）**：
1. `spec_version` 写成 `1.1`，而 `visual.py` 的 `build_visual` 用 `!= SPEC_VERSION`（`1.0`）硬判 → D-E16 永远返回 `None`，图根本不产出。
2. `D-E18` 给 graph 边加了 4 个 `flow_*` 字段，而 `overview.validate_graph_dataset` 要求边字段**恰为** `{src,dst,kind,weight,p_adj}` → 直接抛 `ValueError`。
3. `chart_weights` 一词两义（§4.3 指成员、§5.3 指四轴轴权重），一个 hash 无法审计两套语义。
4. 用户明确要「美股龙头**动态排名**」，SPEC 只有静态 `BINDINGS`，需求未覆盖。
5. 资产池的 `min_rows_3y=1090/740` 会把这批新标的（美股 752、OKX 158–250）全判为不合格，而 `test_asset_pool.py` 又断言了 1090。

---

## §2 六维评分

| 维度 | 权重 | 分数 | 依据 |
|---|---|---|---|
| 定位与边界 | 25% | 4/5 | 双维度切分清晰、可见性直接复用 ADR-V14、明确「L1 不下单」；**扣分**：漏掉用户点名的「动态排名」需求（B-LT4） |
| 统计正确性 | 25% | 3/5 | 复用 `direction_rule` 四轴、零重算纪律正确；**扣分**：聚合曲线基期一刀切（B-LT6）、点亮阈值 0.66/0.40 为魔数且 `conflict` 自指（B-LT7）、LT-AC5 把 `ret_60` 与 `cum_ret` 混比（B-LT8） |
| 工程实现 | 20% | 3/5 | 代码落点表完整、复用既有 `_PRODUCERS`/`quality_for`；**扣分**：`spec_version` 硬冲突（B-LT1）、graph 边字段硬冲突（B-LT2）、批量冻结缓存未定义（B-LT10） |
| 契约与输出 | 15% | 3/5 | `D-E16` 的 `members[]`/`chart_weights_hash` 设计合理；**扣分**：权重命名歧义（B-LT3）、看板内嵌 `light_*` 形成第三套口径（B-LT9）、`lights` 与 `visual` 同信封未说明与 ADR-V2 的关系 |
| 验收与证据 | 10% | 3/5 | LT-AC 大体可机器判定；**扣分**：LT-AC5 断言本身错误、LT-AC4 与 D-E17 列重复、缺「短样本剔除后权重再归一」的断言 |
| 风险与可维护性 | 5% | 4/5 | 风险表覆盖 `source_priority` 误选/两套权重/资金流缺失；**扣分**：缺「质量门槛失效」与「批量成本」两项 |
| **加权** | 100% | **3.30** | 有条件通过 |

---

## §3 阻断项

### 3.1 P0（不修无法落码）

| ID | 问题 | 证据 | 处置建议 |
|---|---|---|---|
| **B-LT1** | `D-E16` 声明 `spec_version="1.1"`，但 `build_visual` 用严格不等判非法 → 图恒为 `None` | [visual.py](./l1agg/capabilities/visual.py) `SPEC_VERSION="1.0"`；`build_visual` 末尾 `if visual["kind"] not in KINDS or visual["spec_version"] != SPEC_VERSION: return None`；[envelope.py](./l1agg/capabilities/envelope.py) 亦按 kind 分支校验 | **二选一**：① 新字段全部放进 `dataset`（`dataset` 结构开放），`spec_version` 保持 `1.0`；② 升 `1.1` 且把两处 `!=` 改为白名单集合校验 + 同步 `contracts/capability_result.schema.json`。**推荐 ①**（零回归、零契约迁移） |
| **B-LT2** | `D-E18` 边新增 `flow_usdt/flow_z/window/direction`，与 graph 边「字段恰为 5 个」冲突 | [overview.py](./l1agg/capabilities/overview.py#L551) `set(edge) != {"src","dst","kind","weight","p_adj"}` 直接抛错 | 边字段仍严格 5 个：`weight = min(1, |flow_z|/3)`、`p_adj = null`（`null` 已被允许，见 L557-559）、`kind = "flow"`；`flow_usdt/direction/window` 放 `dataset.meta.flows[]` 旁挂并按 `edge_index` 关联。若确要加法式扩边，必须同批改 `validate_graph_dataset` + `test_visual.py` |
| **B-LT3** | `chart_weights` 一词两义：§4.3 是**成员/类别权重**，§5.3 是**四轴权重**；`chart_weights_hash` 无法区分两套语义 | SPEC §4.1 权重二分表 vs §5.3 `strength = Σ cw_k × normalized_axis_k` | 拆为：`chart_weights`（成员/类别聚合，hash=`chart_weights_hash`）+ `light_weights`（四轴，hash=`light_weights_hash`）；`config/chart_weights.yaml` 分两个顶层段；LT-G2 断言两 hash 不同名 |
| **B-LT4** | 用户要求的「美股龙头**动态排名**」未落地：只有静态 `BINDINGS` | 用户原话「美股龙头项目（动态排名 微软、苹果、亚马逊、SPCX、英伟达，AMD、海力士，GEV）」；[leader_registry.py](./l1agg/leader_registry.py) 为纯静态字典 | 首版二选一并写进 SPEC：① `ranking: dynamic_weekly`，口径 = `us_stock` 内「20 日均成交额 × 20 日收益」排序取 TopN（`us_etf/us_index` 不参与），排名结果写 `pool_version` 并**必须**入 `params_hash`/`replay_key`（否则历史 signal 无法回放）；② `ranking: static` + 明确登记 LTL-13 待办并标 `rank_source: manual`。**推荐 ①**，但必须先确认 `us_stock` 成交额字段是否入库 |
| **B-LT5** | 质量门槛与资产池 v2 冲突：`min_rows_3y=1090/740` 会对全部新标的判不合格，且既有测试断言 1090 | [coverage_audit.py](./scripts/coverage_audit.py#L242) 取 `min_rows_3y(_trading)` 作唯一下限；[test_asset_pool.py](./tests/test_asset_pool.py#L107) 断言 `== 1090` | `anchors[].history` 增可选 `min_rows`（默认回落 `quality.*`）；`us_stock/us_etf/tokenized` 设 `min_rows: 250` 并标 `history_lt_3y: true`；全局 `quality` 不动，`test_asset_pool` 的 1090 断言继续成立 |

### 3.2 P1（可边落地边修）

| ID | 问题 | 证据 | 处置建议 |
|---|---|---|---|
| **B-LT6** | 聚合曲线基期一刀切：只按 `n<250` 剔成员，XAG（290 点但起点晚 2 个月）会在 `base_date` 后前 60 天独占权重 | SPEC §4.3 规则 1/2 | `base_date = max(各成员首个可用日)`；每点输出 `coverage_ratio = Σ参与成员权重`，`<0.8` 标 `partial_members`；**禁止**前向填充 |
| **B-LT7** | 点亮阈值 0.66/0.40 无依据；`conflict` 用 `foresight.strength` 判自己（自指） | SPEC §5.3 阈值表 | 阈值改为可标定：`light_weights.yaml` 内置 `lit_pct=0.70 / warm_pct=0.40`（历史分位标定）并附标定脚本；`conflict` 只读 `foresight.flags`（`vix_pct≥0.90`、`curve_inverted`）与 `trend` 符号方向，**不读**自身 `strength` |
| **B-LT8** | LT-AC5 断言把标的收益 `ret_60` 与策略累计 `cum_ret` 当同量 | SPEC §12 LT-AC5；`cum_ret` 来自 `paper_replay.metrics` | 改为 `D-E17.ret_60 == D-E12(window=60).ret`（±1e-9）；批量回放与看板只共享**同一** `D-E12` 快照，不做跨量断言 |
| **B-LT9** | `D-E17` 内嵌 `light_trend/inertia/cycle/foresight` 四列，与 `D-E19` 重复计算 → 第三套口径 | SPEC §4.4 固定列 vs §5.2 `lights` | 看板列改为 `lights_ref`（`light_weights_hash`）+ `lit_n/warm_n`，轴明细**只**在 `lights`；ADR-V13 的「零重算」才成立 |
| **B-LT10** | 批量 12 标的 × 700 根下，权重冻结缓存未定义，可能每根重复估 IC | [weight_switch.py](./l1agg/trading/weight_switch.py) `resolve_weights` 按 ISO 周冻结；`paper_replay` 逐根调用 | 明确 `(symbol, iso_week)` 级缓存与断言：同周内 `weights_hash` 与 `inject` 判定一致；批量回放必须复用，且给出成本上界（每标的估计次数 = 周数，非根数） |
| **B-LT11** | §6.4「禁止用复盘收益反向调 `direction_rule` 参数」与 P2-2「DSR/SPA 晋升」表述矛盾 | SPEC §6.4 / §10 P2-2 | 改为：「同一段数据不得既拟合又晋升」；晋升只在独立 holdout（purge/embargo）上做，且同一 `rule_version` 只允许一次晋升记录 |

### 3.3 P2

| ID | 问题 | 处置建议 |
|---|---|---|
| **B-LT12** | `role: leader` 单值，与「三大指数并列」冲突（`leader_of("us_index")` 只能回一个） | `role ∈ {leader, co_leader, member}`；`coverage()` 与 `leaders_by_class()` 全列 `co_leader`；`leader_of()` 语义不变（首个 `leader`） |

---

## §4 非阻断建议

1. **`lights` 与 ADR-V2 的关系需补一句**：ADR-V2 是「每信封最多 1 图」，`lights` 不是图，应在 SPEC 显式声明「`lights` 不受 ADR-V2 约束，但同一信封仍只 1 个 `visual`」。
2. **`DEFAULT_POOL` 漏用户点名标的**：用户明确列了「微软、苹果、亚马逊」，当前首屏只有 NVDA/AMD。建议首屏美股改为 `US500/US100/DJIA/NVDA/AAPL/MSFT`，AMZN/GOOGL/META 留扩展池。
3. **`SKHYNIX` 命名去重**：40 层若用 `000660.KS`，`leaders_by_class()` 会出现两个 code 各一行；注册表应「一标的唯一 code + `aliases`」。
4. **XAG 表述**：§2.2 写「`history_lt_250=0`（290≥250）但 <3 年」易误读，建议直接写 `status=partial, degraded_reason=history_lt_3y`。
5. **`weights.yaml` 默认改 `on` 需附回滚判据**：明确「连续 N 周 `weight_fallback=true` → 自动回 `off` 并告警」，否则 on 在没有证据的情况下等于永久空转。

---

## §5 先行落地许可

| 项 | 许可 | 理由 |
|---|---|---|
| LTL-01/02 资产池 v2 + 注册表扩展 | ✅ 立即开工 | 纯配置 + 静态表 + 单测，不触碰任何图的契约；B-LT5 需先行修（同批） |
| LTL-03 `chart_weights`（拆成两套权重） | ✅ B-LT3 修完即可 | 纯新文件，零回归 |
| LTL-04/05 `D-E16/D-E17` | ⛔ B-LT1/B-LT6/B-LT9 关闭后 | 涉及 `spec_version` 与基期口径 |
| LTL-06 `D-E19` 点亮 | ⛔ B-LT3/B-LT7 关闭后 | 权重语义与阈值标定未定 |
| LTL-07 `D-E18` 资金流导图 | ⛔ B-LT2 关闭后 | graph 边字段会被校验器直接拒绝 |
| LTL-08 批量回放 / LTL-09 `mode:on` | ⛔ B-LT10 关闭后 | 冻结缓存未定义会放大成本 |
| LTL-10/11/12 | 🟡 可并行 | 文档/制品类 |

---

## §6 复审判据

| 关闭条件 | 机器判定 |
|---|---|
| B-LT1 | `pytest tests/test_visual.py` 中对 `D-E16` 的 `build_visual` 返回非 `None`，且 `envelope.build` 不抛错 |
| B-LT2 | `D-E18` 产出经 `validate_graph_dataset` 通过；`set(edge)` 恰为 5 键 |
| B-LT3 | `chart_weights_hash != light_weights_hash`；`paper_replay.replay` 签名内无 `chart_weights` |
| B-LT4 | `pool_version` 进入 `params_hash`；改动排名后历史 `replay_key` 变化可解释 |
| B-LT5 | `coverage_audit` 对 US500/AMD/GEV/SPCX/SKHYNIX 判 `available`（按 per-anchor `min_rows`）；`test_asset_pool` 的 1090 断言仍通过 |
| B-LT6 | 构造 XAG 起点晚 60 天的面板，`agg` 前 60 天 `coverage_ratio<0.8` 且标 `partial_members` |
| B-LT7 | `conflict` 用例：`trend.lit + vix_pct=0.95` → `conflict`；改 `foresight.strength` 不影响判定 |
| B-LT8 | LT-AC5 改为三方比对（`D-E17.ret_60` == `D-E12(w=60).ret`）且通过 |
| B-LT9 | `D-E17` 列内无 `light_*` 明细列，只有 `lights_ref/lit_n` |
| B-LT10 | 同周 5 根重复调用，`weights_hash` 一致且估计次数 == 1 |

---

## §7 与既有 SPEC / 代码的冲突清单

| 冲突点 | SPEC v0.1 写法 | 既有实现 | 结论 |
|---|---|---|---|
| `spec_version` | `1.1` | `visual.py` 只认 `1.0`（严格不等） | 必须改（B-LT1） |
| graph 边字段 | 5 键 + 4 个 `flow_*` | 恰 5 键（`overview.py#L551`） | 必须改（B-LT2） |
| 质量下限 | 只提「250 硬门」 | `min_rows_3y=1090/740` 为全量下限 | 必须改（B-LT5） |
| 权重命名 | 一个 `chart_weights` 两义 | `weights.py` 用 `axis_weights`/`weights_hash` | 必须拆（B-LT3） |
| `role` 取值 | leader/member | `anchor.role ∈ {leader, member}` | P2（B-LT12） |
| 默认权重档 | `mode: on` | `config/weights.yaml: mode: off` | 可改，但需回滚判据（§4.5） |

---

## §8 修订记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-11-15 | 首评：3.30/5 有条件通过；P0 阻断 5 条（B-LT1 `spec_version` / B-LT2 graph 边字段 / B-LT3 权重一义两用 / B-LT4 动态排名缺口 / B-LT5 质量门槛冲突），P1 6 条，P2 1 条；给出先行许可矩阵与 10 条复审判据 |
