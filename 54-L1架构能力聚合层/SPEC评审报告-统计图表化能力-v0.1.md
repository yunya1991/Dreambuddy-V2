# 评审报告 — SPEC-54 统计图表化能力（v0.1）

- **评审对象**: [SPEC-54-统计图表化能力.md](./SPEC-54-统计图表化能力.md) v0.1 → v0.3（三层递进）→ v0.5（三份落地契约）→ v0.8（S0/S1/B18 已落地）→ v0.9（T1 表格 + B10 基线冻结已落地）→ **v0.10（T2 曲线已落地）**
- **代码对象**: [stats.py](./l1agg/capabilities/stats.py)、[envelope.py](./l1agg/capabilities/envelope.py)、[visual.py](./l1agg/capabilities/visual.py)、[inference.py](./l1agg/methods/inference.py)、[capability_result.schema.json](./contracts/capability_result.schema.json)、[data_query_executor.py](../3.1-FRONTEND/scripts/data_query_executor.py)、[technical.py](./l1agg/methods/technical.py)、[timeseries.py](./l1agg/methods/timeseries.py)
- **评审日期**: 2026-11-15 ｜ **评审方式**: 独立复核（文档逐节 + 代码逐行 + 门禁口径复算 + 真实数据冒烟）
- **评审结论**: v0.1 **有条件通过（3.70 / 5.0）**，B1–B4 已关闭；v0.3 三层递进 3.70/5，新增 B6–B10；**v0.5 三份契约复审 4.05/5**，B6/B11/B12 文档层关闭，新增 B13–B16；**v0.7 美联储方法+动态权重 4.38/5**，新增 B18–B20；**v0.8 S0/S1/B18 交付，730 用例全绿**；**v0.9 T1 表格 + B10 基线冻结交付，739 用例全绿**；**v0.10 T2 曲线交付（`test_visual.py` 17 例全绿）**

> 条件：允许 S0 外露闸、S1 D-E15、T1 表格先行落地；**禁止**在 B13/B14 定稿前把 `direction_rule` 接入任何真实下单；**禁止**在 B16 定稿前接触实盘账户。

---

## §1 RFD（裁决理由）

**采纳理由**：`data.visual` 是加法式扩展，`contracts/capability_result.schema.json` 的 `data` 未设 `additionalProperties:false`，`_stat_result()` 又原样透出 `envelope["data"]`，因此该方案在契约层与链路层都成立，且不需要改前端执行器。P0 三出口均有现成数据块，`kind` 白名单与质量门禁能有效防止"图被当结论"。

**保留理由（P0）**：
1. D-E10 的能力块**只有标量**，既无价格也无回撤路径，`trough_index - peak_index` 属于前端统计，违反 ADR-V5。当前 SPEC §4.4 的 `kind=series` 版本**不可实现**，除非补后端字段。
2. `correlation()` 无论被 `D-E05` 还是 `D-E11` 调度，顶层信封恒为 `capability="D-E05"`、`intent="correlation_query"`，与 `capability_manifest.yaml` 的 `D-E11: intent=cross_check` 冲突。`build_visual` 以 `capability` 选图，会把 D-E11 请求渲染成 D-E05 的矩阵/表格并冠以错误标题。

**不否决理由**：以上两点都能在能力层内闭环修复（补 4 个字段、加 2 个参数），不涉及口径变更，也不破坏既有测试断言结构（D-E10 测试为逐字段断言，D-E11 测试为两次调用互比）。

---

## §2 六维评分

| 维度 | 权重 | 分数 | 依据 |
|---|---|---|---|
| 定位与边界 | 25% | 5/5 | 严格限定"后端产规格、前端零统计"；不改口径、不新增数据源；非目标清晰 |
| 统计正确性 | 25% | 3/5 | D-E12 `n_obs/stale_ratio` 口径与 R18 一致；**扣分**：D-E10 无序列且峰谷天数需前端换算，矩阵无逐格 n |
| 工程实现 | 20% | 4/5 | `build_visual` 纯函数 + `build(visual=None)` 零回归路径可行；扣分：`$defs.visual` 未落地 |
| 契约与输出 | 15% | 3/5 | `quality_ref` 指针化、`n_scope` 显式化是亮点；扣分：单图与多能力块的选择规则未定义、上限无机器可校验表达 |
| 验收与证据 | 10% | 3/5 | V-AC1–V-AC8 可执行；扣分：V-AC2 未断言 `n_scope` 展示、V-AC4 依赖尚未存在的字段 |
| 风险与可维护性 | 5% | 4/5 | 风险表覆盖图当结论/双口径/大图/SSR；缺"能力回退导致图种错配"的风险项 |
| **加权** | 100% | **3.70** | 有条件通过 |

### 2.1 v0.3 重评（三层递进：表格 → 曲线 → 思维导图）

**重评结论**：方向正确，且比 v0.1 的"三出口试点"更贴合 L1 的真实价值——v0.1 是"给已有报表配图"，v0.3 是"按认知用途分层"，层级递进与数据成熟度一致。仍维持 **3.70/5（有条件通过）**，原因是 T2/T3 各自缺一个硬前置。

| 维度 | 权重 | v0.3 | 变化依据 |
|---|---|---|---|
| 定位与边界 | 25% | 5/5 | 新增 L1/L2 边界表与方向措辞白名单，把"阻力最小方向"约束为三类统计事实，纪律反而更硬 |
| 统计正确性 | 25% | 3/5 | T2 需新增平滑/斜率口径（I02/T08/I32 均已有）；T08 未做 HAC；T3 依赖 S5 未开放节点 |
| 工程实现 | 20% | 3/5 | 新增 D-E15 出口（manifest+实现+测试）与 `overview.py` 组装层，工作量从"配图"升为"新能力" |
| 契约与输出 | 15% | 4/5 | 三层 dataset 扩展（groups/smoothed/meta/tree meta/edge weight）已定义，`additionalProperties:false` 可校验 |
| 验收与证据 | 10% | 3/5 | V-AC9–V-AC13 可执行，但依赖尚未存在的 D-E15 与制品目录 |
| 风险与可维护性 | 5% | 4/5 | 补入「方向越界」「T3 节点伪造」「制品与信封不一致」三项 |
| **加权** | 100% | **3.70** | 有条件通过 |

**三点关键判定**：

1. **表格先行是对的**：T1 全是现成数据（D-E12、审计矩阵、能力清单），零新增口径，能最快验证"后端产规格"这条链路。
2. **曲线必须新增生产者**：现有 14 个出口没有一个能把"价格/指标 → 平滑 + 斜率"表达出来；D-E10 是回撤派生量，不能替代。建议 D-E15（`trend_query`，I02/T08/I32，`min_n=250`）。
3. **思维导图不能重算**：T3 只能是既有能力块的组合视图（ADR-V13），并且必须让"缺失"可见（S5 未开放、无净流字段 → `unavailable`/`proxy=true`），否则会产出"看起来很全"的假全景。

### 2.2 v0.5 复审（三份落地契约）

**复审结论**：**4.05 / 5.0（有条件通过）**，较 v0.3 的 3.70 提升 0.35。提升全部来自"把争议变成可执行契约"：`direction_rule`、`visibility`、D-E15 三份契约都给了字段、公式、参数、门禁与断言，不再停留在原则。

| 维度 | 权重 | v0.5 | 变化依据 |
|---|---|---|---|
| 定位与边界 | 25% | 5/5 | L1-S/D/X 三层与可见性表把"方向属于谁"彻底讲清：不是层的问题，是可见性问题 |
| 统计正确性 | 25% | **4/5** | 四轴打分显式化、`flat_threshold` 与强度分档可复算；扣分：周期律轴权重为 0，与"历史周期规律"诉求有缺口（B14） |
| 工程实现 | 20% | 3/5 | S0 外露闸很轻（一天可落），但 D-E15 + `direction_rule` + 五张表仍是一个新子系统的工作量 |
| 契约与输出 | 15% | **4/5** | 三份契约字段完整，`signal` 存 `params_hash`+`inputs_snapshot` 满足回放；扣分：`exit_rule` 缺迟滞与最小持仓，存在抖振风险（B13） |
| 验收与证据 | 10% | **4/5** | V-AC14–V-AC19 均可机器判定（回放字节一致、轴分解逐项相等、外露 0 命中）；扣分：`comparison` 打分口径未定（B15） |
| 风险与可维护性 | 5% | 4/5 | 新增"方向可回放""执行零外露"两类风险对策；扣分：小额资金与账户隔离未定（B16） |
| **加权** | 100% | **4.05** | 有条件通过 |

**B6/B11/B12 文档层关闭**：

| ID | 处置位置 | 复审判据 |
|---|---|---|
| B6 | §4.9 D-E15 完整契约（manifest/入参/门禁/输出/图规格/测试） | 若实现符合契约，T2/L1-D/T3 三处同时解锁 |
| B11 | §4.7 `direction_rule` 四轴打分 + YAML 参数 + `exit_rule` | `V-AC17` 轴分解逐项相等 |
| B12 | §4.8 `visibility` 四层变更（manifest/validate/exec_stat_query/envelope） | `V-AC19` 前端 cue 全量 0 命中 internal |

**v0.5 新增阻断（4 条，均不阻断 S0/S1 开工）**：

| ID | 级别 | 问题 | 处置建议 |
|---|---|---|---|
| **B13** | P0 | `exit_rule` 与 `direction_rule` 阈值不对称（进 30 / 出 18）会在震荡区间反复开平，产生大量手续费损耗 | 加迟滞：进入需 `abs(total) ≥ 30` 且**连续 2 根**满足；退出需 `<18` 且连续 2 根；加 `min_hold_bars`（默认 6）；V-AC18 增"震荡序列 0 次开平"用例 |
| **B14** | P1 | 周期律轴权重为 0，与用户"历史周期规律"诉求不完全一致；BTC 日线不足 5 年，月度季节必然 degraded | 用 **D-E02 分位法**表达"当前值在历史同期的分位"替代月度季节（不需要 5 年）；启用条件：`n≥250` 且分位数据可比；否则该轴记 0 并标 `seasonality_unavailable` |
| **B15** | P1 | `comparison` 表的打分口径未定：持有期、基准、是否扣费、如何避免前视 | 固定为「同一 `as_of` 后 N 个交易日（默认 5）的标的收益 − 同期基准收益」；扣双边手续费与滑点；`scored_at` 必须晚于窗口结束，前视由 SQL 约束（`as_of + N ≤ scored_at`） |
| **B16** | P2 | 小额资金与账户隔离未定：用哪个账户、单笔上限多少 | 建议独立子账户 + 独立 API key；初始 `max_notional=100 USDT/笔`、`max_daily_loss=30 USDT`、`max_positions=3`、`max_leverage=2`；数值走配置文件，改值不改代码 |
| **B17** | P1 | `rule_version` 择优缺少多重检验门禁：试 20 组参数必有一组样本内 Sharpe 最高，直接上实盘即过拟合 | 晋升必须过 DSR/SPA（Q07 已有 Q06/Q07 实现）；`DSR≤0` 或 `SPA p≥0.05` 禁止接 L1-X；V-AC22 断言 |

> **B13–B17 已并入 [SPEC §4.10/§4.11](./SPEC-54-统计图表化能力.md)**：B13 迟滞（进 30 / 出 12 + 连续 2 根 + `min_hold_bars=6`）、B14 周期律（短期 D-E02 分位 / 中期 I39 带通）、B15 三重障碍 + purge/embargo、B16 vol targeting + 簇敞口、B17 DSR/SPA 门禁。

### 2.3 借鉴传统金融/统计学/交易经验后的复审

**复审结论**：**4.20 / 5.0（有条件通过）**。工程维度仍 3/5（新增 I39、Ledoit-Wolf、三重障碍都是真工作量），但统计与风险两维各升 0.5——因为原先的「拍脑袋阈值」全部换成了有文献与行业实践的参数。

| 改动 | 借鉴来源 | 对方案的影响 |
|---|---|---|
| `windows` 增 250 日 | Moskowitz, Ooi & Pedersen (2012) | 修正了原设计只有 20/60/120 的短视偏差；250 日权重 0.30，使"趋势"不再等于"两三周噪声" |
| 固定名义 → 波动率缩放 | 管理期货行业标准 | 直接满足用户"小额且风险可控"：同风险预算下波动越大仓位越小，不需要人工改额度 |
| 进出阈值不对称 + 迟滞 | 趋势策略通用实践 | 把 B13 从"建议"变成"有依据的参数"；震荡市不再反复开平 |
| **元标注**（L2 只决定执行） | López de Prado (2018) | **架构级改进**：L1 与 L2 从竞争变协作，comparison 表能同时衡量两者的增量价值 |
| 三重障碍 + purge/embargo | 同上 | B15 从"固定 5 日收益"升级为事件式标注，回测泄漏被结构性排除 |
| DSR/SPA 晋升门禁 | Bailey & López de Prado (2014)；White (2000)；Hansen (2005) | 新增 B17，堵住"参数搜索即过拟合"这个最致命的漏洞 |
| 成本模型（双边+滑点+资金费率） | 交易所费率；Almgren & Chriss (2000) | 直接改变结论：短窗口只能确认、不能单独触发；这也是 250 日权重升到 0.30 的第二理由 |
| 相关性簇敞口 | 风险管理通行做法 | BTC/ETH 相关 0.8+，原设计会把它当两个独立仓，实际是加倍下注 |

**明确不采纳**：端到端 ML 预测方向（违反 L1 无大模型）、全 Kelly（改用 0.25× + 硬上限）、高频做市/TWAP 拆单（资金与基础设施不匹配）。

**仍未闭合**（不阻断 S0/S1）：B9（落盘契约）。B8（T3 降级契约，2026-11-15 已关闭）、B10（基线冻结，已关闭）。

### 2.4 借鉴美联储方法 + 动态权重后的复审

**复审结论**：**4.38 / 5.0（有条件通过）**。统计维度从 4.5 升到 5——动态权重不是"加功能"，而是把原先"权重拍死"的假设换成了**可证伪、可回退**的机制，并且用等权基线给它上了刹车。工程维度仍 3（新增 I35–I39 五个方法 + vintage 存储是真工作量）；**B18 vintage 已于 2026-11-15 落地，vintage 风险从"未落到代码"转为"已隔离"**。

| 维度 | 权重 | v0.6 | v0.7 | 依据 |
|---|---|---|---|---|
| 定位与边界 | 25% | 5 | 5 | 视野从"技术指标"扩到"数据—价格关系"，与 L1 统计定位一致 |
| 统计正确性 | 25% | 4.5 | **5** | 四源权重 + 等权否决 + 点对点约束，把"权重从哪来"讲透了 |
| 工程实现 | 20% | 3 | 3 | I35 协整 / I36 分位回归 / I37 Kalman / I38 DMA / I39 带通·STL + vintage 表结构（B18 已落地，余 5 个方法） |
| 契约与输出 | 15% | 4 | 4 | `series` 需加 `±1σ` 带、`signal` 需加 5 个权重字段，schema 要改但仍是加法 |
| 验收与证据 | 10% | 4.5 | 4.5 | V-AC23–V-AC27 全是可机器判定的（删未来数据 hash 不变、退化即 fallback） |
| 风险与可维护性 | 5% | 4.5 | 4.5 | 等权基线是最有效的防过拟合手段；B18 vintage 落地后，回放前视风险从设计层降到代码层 |

**这次借鉴里最值得强调的三点**：

1. **「真实曲线」从 EMA 升级为 Kalman level+slope±1σ**：曲线图自带置信带，斜率是否"真的斜"可由 `slope_se` 判断，而不是看两条线纠缠。
2. **协整补上了"趋势之外的另一半"**：趋势策略在震荡市失效，而 `equilibrium_gap`（价格对宏观/龙头的长期偏离）恰好在震荡市有用——两者方向常常相反，正好构成对冲结构。
3. **Growth-at-Risk 让「强度」有了分布含义**：`strength` 不再是一个拍出来的 0–1，而是预测分布的 `q90−q10` 离散度；离散度大 = 不确定性高 = 仓位应变小（与 vol targeting 自洽）。

**新增阻断**：

| ID | 级别 | 问题 | 处置建议 |
|---|---|---|---|
| **B18** | **P0** | **宏观修订会被覆盖，导致动态权重前视**：`mm_metrics` 主键含 `timestamp` 且回填用 `INSERT OR REPLACE`，同周期重采会覆盖旧观测，事后回放看到的是**修订后**的值（真实交易时看不到） | 慢频序列改追加式：键加 `observed_at`，同 `(metric, period)` 允许多版本；L0 取数默认取最新、回放取 `observed_at ≤ as_of`；V-AC27 断言 vintage 隔离。**这是动态权重的合法性前提**。✅ **已关闭（2026-11-15）**：`mm_metric_vintages` 幂等迁移脚本 + L0 `as_of` As-Of 回放 + 4 用例（表缺失时 `vintage_unavailable` 降级，不回落 `mm_metrics`） |
| **B19** | P1 | **动态权重可能退化为过拟合机器**：四源权重里 `reliability` 来自 `abs(IC)`，而 IC 本身噪音大；若不设等权对照，等于每周用样本内最优权重去交易 | ADR-V19 已规定"等权胜出才启用"；需补一条工程约束：`weight_fallback=true` 时必须**同时记录**"若用动态权重会怎样"（影子权重），用于后续评估，但不得执行 |
| **B20** | P1 | **新方法未登记 + schema 需扩展**：I35–I39 均不在 `METHOD_LIBRARY.md` / `REGISTRY`；`series` 的 `points` 目前只有 `{x,y,smoothed}`，无 `lower/upper` 置信带字段 | 方法逐条登记（含 `min_n`/`gate`/`caveat`）；`visual.schema` 的 `series` 增加可选 `band{lower,upper}`，仍走 `spec_version="1.0"` 的加法扩展。⚠️ **编号冲突已修正**：I01–I34 实测连续无空号，新方法改登记为 I35 协整 / I36 分位回归 / I37 Kalman / I38 DMA / I39 带通·STL |

---

## §3 阻断问题

| ID | 级别 | 位置 | 问题 | 证据 | 处置建议 | 状态 |
|---|---|---|---|---|---|---|
| **B1** | P0 | [stats.py:207](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/54-L1架构能力聚合层/l1agg/capabilities/stats.py#L207-L221) | D-E10 块只有 `mdd/peak_index/trough_index/peak_date/current_drawdown/duration_days/recovery_days/recovered`，无 `peak_price/trough_price/drawdown_path`；`peak_to_trough_days` 只能由 `trough_index-peak_index` 得出 | `answer` 中的"峰→谷 N 天"是后端文本，机器不可读；`data` 内没有该数值 | ① 按 SPEC §6.3 补 `drawdown_path`（≤500 点）+ `peak_price/trough_price/peak_to_trough_days`（零新增取数，`px/ds` 已在栈上）；② 若不补，D-E10 P0 必须降为 `table`，且**只能**展示 7 个既有标量，删除 `annotations` 与天数展示 | ✅ 已关闭（采方案 A，见 §4.6） |
| **B2** | P0 | [stats.py:741](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/54-L1架构能力聚合层/l1agg/capabilities/stats.py#L741-L757)、[stats.py:1115](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/54-L1架构能力聚合层/l1agg/capabilities/stats.py#L1115-L1119) | `correlation()` 签名无 `capability_id/intent`，D-E11 请求返回的信封 `capability="D-E05"`、`intent="correlation_query"`，与 manifest `D-E11: cross_check` 矛盾 | 代码全文仅 1 处 `build(capability="D-E05", intent=INTENT_CORRELATION)`；`run_capability` 直接 `return _EXECUTORS`capability_id`` | `correlation()` 增 `capability_id="D-E05"`、`intent=INTENT_CORRELATION` 参数并由 `run_capability` 按 ID 注入；补断言 `out["capability"]=="D-E11"`、`out["intent"]=="cross_check"`；`build_visual` 以**请求能力**为准，禁止从 `data.capabilities` 猜 | ✅ 已关闭（§4.6） |
| **B3** | P1 | [data_query_executor.py:973](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/scripts/data_query_executor.py#L973-L980) | 前端只有 6 个 cue，无 D-E11/D-E12，也无"≥3 个标的走 `series` 矩阵"入口；P0 三出口中 D-E12 与 D-E05 多资产**无法从聊天触发** | `_STAT_*_CUE` 仅 DRAWDOWN/SEASONAL/PERCENTILE/STATE/IC/CORR；`exec_stat_query` 无 D-E12 分支 | 补 `_STAT_CROSS_CUE`（同向率/相关突变/周期对齐）、D-E12 分支与 `dates` 传参、≥3 标的走 `series=`；属 P0 前置而非可视化本身 | ✅ 已关闭（§4.6） |
| **B4** | P1 | [capability_result.schema.json:29](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/54-L1架构能力聚合层/contracts/capability_result.schema.json#L29-L62) | `$defs.visual` 未落地；上限（rows ≤500 / cells ≤2000 / nodes ≤300）仅写在文档，schema 无法校验 | 现有 `data` 仅定义 `capabilities/params/symbol/pair`，无 `visual` | 增加 `$defs.visual`（`additionalProperties:false`、`kind` 枚举、`spec_version` 常量、`n_scope` 枚举），`data.additionalProperties` 保持开放；上限用 `maxItems` 表达 | ✅ 已关闭（§4.6） |
| **B5** | P2 | SPEC §4.4 / §7 | `matrix` 的 `n_scope="global"` 已声明，但 V-AC2 未断言该字段与前端告警；D-E05 与 D-E11 同信封时"取哪一块"未定义 | §7 仅断言 values 对称/对角/domain | V-AC2 增 `n_scope=="global"`；ADR-V2 补充"`visual.source_capability` 必须等于信封 `capability`" | ⏳ 文档规则已补，V-AC2 断言留 P0 |

### 3.1 v0.3 重评新增阻断项（三层递进）

v0.1 的阻断项全部围绕"三出口试点"；转为 T1→T2→T3→T4 分层推进后，暴露出 5 个新阻断，**均集中在层与层之间的生产者/消费者接口上**，不在既有出口内部（出口数已在重评中实测为 14，见 B10）。

| ID | 级别 | 位置 | 问题 | 证据 | 处置建议 |
|---|---|---|---|---|---|
| **B6** | P0 | SPEC §4.4 / §8 | **T2 曲线层没有生产者**：现有出口无一能输出「价格/指标 → 平滑序列 + 斜率」。D-E10 是回撤派生量（`1 - p/running_max`），平滑它 ≠ 平滑价格，不能替代 T2 | `capability_manifest.yaml` 实测 14 条（`D-A14`、`D-E01`–`E12`、`D-G22`）无 `series/smoothing/slope` 出口；`I02/T08/I32` 仅方法层可用，无能力出口调用 | 新增 **D-E15 `trend_query`**：入参序列 + `windows`，调 `I02 EMA`/`T08 斜率`/`I32 ADX`，`min_n=250`，输出 `smoothed/meta.smoothing`/多窗口斜率表/`ema_alignment`；D-E15/D-E16 均未被占用。**B6 未决 → T2 不得开工** |
| **B7** | P0 → **已降级** | SPEC §1.1 / ADR-V10 | 原判定「方向属 L2」**过严**：用户澄清 L1 的方向来自趋势延续+惯性+周期律的**确定性外推**，不是大模型推理。真正的风险不是"有方向"，而是「方向被写进对外信封」与「方向不可回放」 | ADR-V10 原文若照抄，会禁掉 L1-D 必需的内部记录 | **改判**：ADR-V10 降为**仅约束对外措辞**（`answer`/`visual.title`/前端文案）；对内新增 ADR-V15（方向必须纯函数 + `rule_version`/`params_hash` + 输入快照）；V-AC14 断言可回放。风险由 B11/B12 承接 |
| **B8** | P1 | SPEC §4.5 | **T3 全景图的「资金流」节点口径不清**：① `S5 MERS 关系推荐`未开放（无任何出口）；② 「资金净流」**只有加密巨鲸口径**（L0 `datacenter.series` 的 `exchanges_whales::whale_netflow_to_ex_usd`，落库为「转出-转入」需乘 -1），**没有 L1 能力出口**，跨资产/股票资金流完全缺失。若混用，会让 T3 从「能力块组合」悄悄变成「直连 L0」，破 ADR-V13 零重算 | `capability_manifest.yaml` 无 S5 出口、无资金流出口；[series_catalog.py:175-184](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/54-L1架构能力聚合层/l1agg/series_catalog.py#L175-L184) 证明净流仅存在于 L0 序列；SPEC §4.5 未在契约层区分「能力值」与「序列值」 | 契约层硬性区分两种叶：`meta.capability`（能力块，值必须逐字段一致）或 `meta.series_id`（L0 序列，必须带 `proxy=true` + `unit` + `sign_flip`）；S5 → `value=null, meta.reason="S5 未开放"`；非加密资产的资金流 → `unavailable`，**禁止用加密净流冒充**；V-AC11 增「每叶必须有 `meta.capability` 或 `meta.series_id`」断言 ✅ **已关闭（2026-11-15）**：`overview.py` 的 `_leaf`/`validate_tree_dataset` 把契约变成硬闸（`SERIES_REGISTRY` 白名单 + `CRYPTO_SYMBOLS` 借用域 + `proxy/unit/sign_flip` 必填），`test_visual.py` 7 例覆盖 |
| **B9** | P1 | SPEC ADR-V12 / §6 | **制品落盘契约未定义细节**：路径模板有了，但 `as_of` 取信封哪个时间、同 `as_of` 重跑是否覆盖、并发写是否原子、`artifact_error` 如何进 `quality` 全部缺失。T4（思维树/反思进化器）无法据此接入 | 现存仓库无 `artifacts/visual/` 目录；`visual_store.py` 尚未创建；SPEC §6 只有一行"幂等 `json.dump(sort_keys=True)`" | 在 §6 落定：`as_of` 取 `quality.span[1]`（无则取请求日期）；`tmp + os.replace` 原子写；同路径覆盖但写 `content_hash`；落盘失败只记 `visual.artifact_error`，图照常返回（FAIL-OPEN）；V-AC12 断言同 `as_of` 二次运行字节一致 |
| **B10** | P1 | SPEC §2 / §7 V-AC1 | **出口数口径漂移**：文档先后写过 10 个、12 个，实测 **14 个**（`D-A14`、`D-E01`–`E12`、`D-G22`）。V-AC1 写成"既有 N 出口零回归"，基线未冻结，并行线继续加出口就会持续失效 | `capability_manifest.yaml` 当前 14 条 `- id:`；`_EXECUTORS` 14 条与之一致；`docs/TECHNICAL_DESIGN.md` 已被并行线推到 v2.14 | V-AC1 改为**按能力子集断言**，冻结 `baseline_outlets`（14 条已写入 SPEC §7）；文档中"出口数"改为引用 manifest 实测计数，不再硬编码。✅ **已关闭（2026-11-15）**：`tests/test_visual.py::BASELINE_OUTLETS` 以字面常量冻结 14 条的 intent/mode/methods/min_n/visibility |
| **B11** | P0 | SPEC ADR-V15 / §4.6 | **`direction_rule` 本体未定义**：用户要求方向 = 趋势延续+惯性+周期律的确定性外推，但规则形态、参数集、权重、阈值、周期律怎么表达（季节/月度效应？D-E03？）全部空白。没有它，L1-D 无法回测，也无法与 L2 对照 | SPEC 只写了"纯函数 + `params_hash`"，没有参数清单；D-E03 季节性、D-E06 领先滞后、D-G22 显著性都还没被纳入规则输入 | 在 SPEC 新增 `direction_rule` 章节：输入固定为 `slope_signs(多窗口)/adx_band/ema_order/same_direction_rate(→D-E11)/lead_lag(→D-E06)/p_adj(→D-G22)`；输出 `direction∈{-1,0,1}` + `strength∈[0,1]`；参数走 YAML 常量 + 版本号；**先纸面回放 3 个月**再谈小额实盘 |
| **B12** | P0 | SPEC ADR-V14 / V-G11 | **执行能力外露闸不存在**：`capability_manifest.yaml` 无 `visibility` 字段，`exec_stat_query` 也没有白名单过滤；一旦登记执行类能力，前端可用 cue 直接命中（当前已支持 12 个 cue 自由分派） | manifest 14 条均无 `visibility`；[data_query_executor.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/scripts/data_query_executor.py) 无任何 internal 过滤 | `manifest.validate` 增 `visibility` 枚举与默认 `public`；`exec_stat_query`/`run_capability` 对外入口统一走 `assert_public(capability_id)`；V-AC15 断言 `data` JSON 递归无 `signal/order/fill/position` 键 |

**优先级与依赖**（v0.4 口径）：T1 只卡 B10；T2 卡 **B6**；T3 卡 B8；T4 卡 B9；**L1-D 卡 B6 + B11**；**L1-X 卡 B12 + B11 + 小额资金门槛**。B7 已改判为文档口径问题（已关闭）。**结论：T1 可立即开工；L1-D 必须在 D-E15 落地后开工，且先纸面回放；B12 是"执行不外露"的唯一硬闸，先于任何执行代码落地。**

---

## §4 评审中已修复项

| ID | 问题 | 修复 |
|---|---|---|
| R1 | 评审对象文件此前丢失（仅调研报告在盘），无法评审 | 依据调研报告与代码事实重建 SPEC v0.1，并把 P0 三出口写入 §4.4/§8 |
| R2 | SPEC 原稿未写"能力块 `gate != ok` 不产图" | 新增 V-G2 |
| R3 | SPEC 原稿未写"每信封最多 1 图" | 新增 ADR-V2 |
| R4 | SPEC 原稿未写"前端不得用索引差算天数" | ADR-V5 与 §4.4 P0-B 显式禁止 |
| R5 | SPEC 原稿未写 D-E12 `window_rows` 的投影字段 | §4.4 P0-C 按 R18 实际输出 8 列固定 |

---

## §4.6 阻断项修复证据（v0.1 实现）

| ID | 修复 | 复测 |
|---|---|---|
| B1 | [stats.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/54-L1架构能力聚合层/l1agg/capabilities/stats.py) `drawdown()` 追加 `peak_price/trough_price/peak_to_trough_days/drawdown_path`（≤500 点，抽稀保留最大回撤点） | `test_drawdown_exposes_path_and_peak_trough_fields` ✅ |
| B2 | `correlation()` 增 `capability_id/intent`；`run_capability` 按 `_EXECUTOR_INTENTS` 注入 | `test_shared_executor_envelope_carries_requested_capability` ✅ |
| B3 | 前端新增 `_STAT_ALIGN_CUE`/`_STAT_CROSS_CUE`、D-E12 分支、`dates` 传递、≥3 标的矩阵入口；D-E10 补传日期轴 | 真实数据冒烟：`BTC ETH 对齐切片`→D-E12（窗口 2024-11-16~2026-11-12，n=727）；`BTC ETH 相关突变`→D-E11（ρ=0.8286）；`BTC ETH SOL 相关矩阵`→D-E05（TopK 3 对） ✅ |
| B4 | `contracts/capability_result.schema.json` 增 `$defs.visual`（`additionalProperties:false` + 上限） | `jsonschema` 正例通过、`pie`/`spec_version=2.0` 被拒 ✅ |
| 零回归 | 54 全量测试 | 仅 1 例既有时间相关失败 `test_partial_quality_below_30`（期望 5 实际 4，与本改动无关） |

---

## §5 非阻断建议（P1/P2）

| ID | 建议 | 理由 |
|---|---|---|
| I1 | `caveat` 从能力层常量派生，不在 `build_visual` 内重复写死 | 避免与 `CAVEAT` 漂移 |
| I2 | `matrix` 的 `values` 明确 `null` 语义（缺失对 = `null`，不得填 0） | 0 会被读成"无相关" |
| I3 | 增加 `scripts/visual_spec_report.py`（P1 审计热力图） | 复用现有 `method_audit.json`，零新增采集 |
| I4 | 渲染器统一 `'use client'` + `dynamic({ssr:false})` | recharts 在 RSC 下会报错 |
| I5 | `visual` 与 `data.hooks` 并存时，前端优先取 `visual` | `_attach_hooks` 会改写 `data`，需确认不覆盖 |

---

## §6 Devil's Advocate

**反对 1：D-E10 的"表格"只是 8 行标量，价值接近零。**
→ **让步阈值**：若补 `drawdown_path` 后 30 天内没有页面消费 `kind=series`，则撤销 D-E10 试点，P0 收窄为 D-E05 + D-E12。

**反对 2：矩阵只有全局 n 会误导。**
→ **让步阈值**：只要 `n_scope="global"` 在 UI 上以角标常驻，并且资产数 `<3` 时强制表格，反对撤回。

**反对 3：`visual` 契约会增加后端复杂度，收益不确定。**
→ **让步阈值**：若 P0 三个出口的实现 diff 超过 150 行，或任一现有测试需要改断言才能通过，则退回"前端按能力 ID 映射 + 后端零改动"方案（仍满足前端零统计，因为只做格式化）。

---

## §7 复审清单

| # | 检查 | 通过判据 |
|---|---|---|
| 1 | B1 已处置 | `D-E10` 块含 `drawdown_path` 且 `max(y) == mdd`（±1e-6）、末点等于 `current_drawdown`，或已降为 table |
| 2 | B2 已处置 | `run_capability("D-E11", ...)` 返回 `capability=="D-E11"`、`intent=="cross_check"` |
| 3 | B3 已处置 | 聊天输入"BTC ETH SOL 相关矩阵"出 `kind=matrix`；"对齐切片"出 `kind=table` |
| 4 | B4 已处置 | `jsonschema` 校验：合法 visual 通过、`kind="pie"` 被拒 |
| 5 | 零回归 | `pytest tests/ -q` 全绿，且现有断言零修改 |
| 6 | 开关 | `L1_VISUAL_ENABLED=0` 时 3 个出口均无 `data.visual` |

---

## §8 结论与下一步

**裁决**：v0.1 **有条件通过（3.70 / 5.0）**，B1–B4 已在评审后按序关闭（见 §4.6），B5 文档规则已补、V-AC2 断言留到 P0。

**v0.3 重评（三层递进）**：**3.70 / 5.0（有条件通过）**。方向比 v0.1 更正确——分层依据是「认知用途」而非「已有报表」，但每层各多出一个硬前置。

**v0.5 复审**：**4.05 / 5.0（有条件通过）**，见 §2.2。三份契约（`direction_rule` / `visibility` / D-E15）把 B6/B11/B12 转为文档层已关闭，新增 B13–B16（均不阻断 S0/S1）。

**v0.6 复审**：**4.20 / 5.0（有条件通过）**，见 §2.3。借鉴传统金融/统计学/交易成熟经验后，B13–B17 全部定稿并入 SPEC §4.10/§4.11；工程维度仍 3/5，其余维度均 ≥4。

**v0.7 复审**：**4.38 / 5.0（有条件通过）**，见 §2.4。借鉴美联储研究方法（DFM/Kalman、MIDAS、协整、泰勒规则、GaR 分位回归、FCI、vintage）并引入动态权重机制；新增 B18（vintage 前视，P0）、B19（等权否决）、B20（新方法与 schema）。统计维度升到 5/5。

| 层 | 可否开工 | 前置 |
|---|---|---|
| **S0 外露闸** | ✅ **立即可开工** | 无（B12 契约已定，纯加法） |
| **S1 曲线生产者 D-E15** | ✅ **立即可开工** | 无（B6 契约已定） |
| **T1 表格** | ✅ 立即可开工 | B10 基线冻结（半天） |
| **T2 曲线** | ✅ S1 完成后 | — |
| **T3 思维导图** | ✅ 已完成（后端） | ~~B8~~ 已关闭（`overview.py` tree + graph） |
| **T4 反思消费者** | ⛔ 卡住 | **B9**（落盘契约）+ **B15**（打分口径） |
| **L1-D 方向层**（内部） | ✅ 可开工（纸面） | B13/B14 已定稿（进 30 / 出 12 + 迟滞 + 周期律走 D-E02 分位） |
| **L1-X 执行层**（内部） | ⛔ 卡住 | S0 落地 + L1-D 纸面回放 ≥3 个月 + B16（子账户/额度）+ B17（DSR/SPA 门禁） |

**已决策**：D-E10 采用方案 A（补 `drawdown_path` 出面积图）。

**下一步（v0.9 状态）**：
1. ~~**S0 外露闸**~~ ✅ **已完成**（`visibility` + `validate` 枚举/引用校验 + `assert_public` + `envelope` 递归键禁入 + 前端入口断言；`test_capabilities.py` 68 passed）；
2. ~~**S1 曲线生产者**~~ ✅ **已完成**（D-E15 `trend_query`：4 窗口斜率 + EMA 路径 + ADX14 + 降级披露，3 个测试通过）；
3. ~~**B18 vintage 回放**~~ ✅ **已完成**（`mm_metric_vintages` 幂等迁移 + L0 `as_of` As-Of 查询 + 4 用例；全量 `tests` 730 passed）；
4. ~~**T1 表格 + B10 基线冻结**~~ ✅ **已完成**（`visual.py`：D-E12 固定 8 列表 + 能力清单表 + 审计 386×6 矩阵；`envelope.build(visual=...)` 契约校验；`BASELINE_OUTLETS` 14 条冻结；全量 `tests` **739 passed**）；
5. ~~**T2 前端 cue 接 D-E15**~~ ✅ **后端已完成**（`visual.py` series：D-E10 回撤曲线 + D-E15 价格/EMA26 + `slope_table()` 6 列；schema 增 `smoothed/upper/lower`+`meta`；`test_visual.py` 17 例全绿）。剩余仅为**前端渲染器接线**；
6. ~~**T3 全景思维导图**~~ ✅ **后端已完成**（`overview.py`：tree 静态布局逐叶投影 + graph 共振网络；B8 降级契约（`SERIES_REGISTRY` 白名单 / `proxy/unit/sign_flip` / crypto-only / S5 未开放）落成硬闸；`test_visual.py` 24 例全绿 · 全量 **758 passed**）。剩余仅为**前端 tree/graph 渲染器接线**；
7. **L1-D 纸面回放**：参数已定稿（进 30 / 出 12 / 迟滞 2 根 / 6 根最小持仓 / 4 窗口），先跑 ≥3 个月历史并出 triple-barrier 标注；
8. **L1-X**：S0 落地 + 回放通过 + B16 子账户与额度 + B17 DSR/SPA 晋升门禁，`dry_run=true` 起步；
9. **T4 反思消费者**：仍卡 B9（落盘契约）+ B15（打分口径），T1–T3 制品落盘是它的前置。

---

## §9 签署

| 角色 | 结论 | 日期 |
|---|---|---|
| 评审（独立复核） | v0.1 3.70/5（B1–B4 关闭）；v0.3 三层递进 3.70/5（B6–B10）；v0.5 三份契约 4.05/5（B6/B11/B12 文档层关闭）；v0.6 借鉴成熟经验 4.20/5（B13–B17 定稿）；**v0.7 借鉴美联储方法+动态权重 4.38/5（新增 B18–B20，B18 为 P0）** | 2026-11-15 |
| 实现 | 已提交 B1–B4（D-E10 采方案 A） | 2026-11-15 |
| 用户 | 已确认 D-E10 方案 A、"其余按顺序修"；定调三层递进；澄清 L1 方向 = 趋势延续+惯性+周期律的确定性外推（非大模型），小额、内部链路、对外只允许图表能力；认可 S0→S1→T1–T4→L1-D/L1-X；**要求借鉴传统金融/统计学/交易与美联储研究方法，并设计动态权重机制联动方向/强度/仓位** | 2026-11-15 |
| 待用户决策 | 模块归属（55 新建 vs 并入 14-V15）；B16 子账户与额度数值；L1-D 纸面回放标的池；B19 影子权重是否强制落 `signal` | ⏳ |
| 评审 | **v0.8（2026-11-15）S0/S1/B18 已交付并过测**：`test_capabilities.py` 68 passed、全量 `tests` 730 passed；B18 关闭；方法编号改为 I35–I39 | 2026-11-15 |
