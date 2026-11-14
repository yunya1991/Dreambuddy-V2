# 评审报告 — SPEC-54 延续性统计分析模块（T0）

- **评审对象**: [SPEC-54-延续性统计分析模块.md](./SPEC-54-延续性统计分析模块.md) v1.0 → **v1.1（复审）**
- **代码对象**: [l1agg/persistence/](./l1agg/persistence/)、[tests/test_persistence.py](./tests/test_persistence.py)、[scripts/persistence_report.py](./scripts/persistence_report.py)、[contracts/persistence.schema.json](./contracts/persistence.schema.json)
- **评审日期**: 2026-11-14 ｜ **复审日期**: 2026-11-14 ｜ **评审方式**: 独立复核（文档 + 代码逐行 + 已知答案测试 + 真实数据复算）
- **评审结论**: v1.0 **有条件通过（4.10 / 5.0）** → v1.1 **通过（4.75 / 5.0，B1/B2/B3 全部关闭）**

> v1.0 条件（已满足）：允许作为 **T0 描述性输出**上线；**禁止**将本模块的 `t` 值当作显著性结论直接进入 L2 建模。v1.1 已通过 `hac_corrected=false` + `note` + 文本披露强制该约束，HAC 实现仍留 T1。

---

## §1 RFD（裁决理由）

**采纳理由**：模块边界与 SPEC-54 的 ADR-3（L1 不做预测）严格一致；7 个指标均可反查方法库 ID；纯 stdlib + 已知答案测试使实现可审计；真实数据已跑出可解释结果，且四资产结论（日频方向延续性极弱）与既有认知不冲突。

**保留理由（v1.0）**：A6 趋势斜率的 `t` 值未做自相关修正，而 SPEC §2 的判读规则依赖 `|t|>2`。这是**统计有效性缺陷**，不是文档瑕疵，必须在契约中显式降级，否则会被下游当作显著性证据。

**v1.1 复审结论**：B1/B2/B3 均已按建议处置，`t` 已从"可被误读为显著性"改为"契约层显式不可作显著性结论"。保留意见降级为 T1 待办（HAC 实现），不再阻断。

**不否决理由**：该缺陷不影响 A1–A5、A7 的可用性，也不影响"日频方向不可延续"这一核心结论（该结论由 φ、VR、P(涨|涨) 三者交叉支持，不依赖 t 值）。

---

## §2 六维评分

| 维度 | 权重 | v1.0 | v1.1 | 依据 |
|---|---|---|---|---|
| 定位与边界 | 25% | 5/5 | 5/5 | 明确不做预测/评分/FinBERT；P1 vs P3 分层清晰 |
| 统计正确性 | 25% | 3/5 | 4/5 | A2/A3/A5 口径正确；B1 已显式降级（HAC 留 T1）、B2 已多相位、B3 已固定 max_chunk；扣 1 分因 HAC 未真正实现 |
| 工程实现 | 20% | 4/5 | 5/5 | 纯 stdlib、无全局状态、异常收敛统一；schema 已落文件并被测试校验 |
| 契约与输出 | 15% | 4/5 | 5/5 | 字段名带单位、null 纪律、固定文本模板、机器契约 + `--json` |
| 验收与证据 | 10% | 5/5 | 5/5 | 27 用例（persistence）+ 146 全量通过 + 真实四资产复算 |
| 风险与可维护性 | 5% | 4/5 | 5/5 | 风险表补入「Hurst 跨期不可比」「趋势 t 放大」并给出可反查字段 |
| **加权** | 100% | **4.10** | **4.75** | v1.1 通过 |

---

## §3 阻断问题

| ID | 级别 | 位置 | 问题 | 证据 | v1.0 处置建议 | v1.1 状态 |
|---|---|---|---|---|---|---|
| **B1** | P1 | [metrics.py:197](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/54-L1架构能力聚合层/l1agg/persistence/metrics.py#L197-L221) | A6 对数价格 OLS 的 `t` 未做 Newey-West/HAC 修正。残差强自相关，`t` 被严重放大 | XAU `t=101.0`、`R²=0.9033`；BTC `t=16.37`、`R²=0.197`。日频趋势序列残差 ACF 显著非零，名义 `|t|>2` 不等价于显著 | ① 加 note 并写入文本 / ② 实现 HAC | ✅ **已关闭**：采用 ①，输出 `hac_corrected=false` + `note="t 未做 HAC 修正，仅作相对比较，不作显著性结论"`，文本追加「t 未做自相关修正」，SPEC §2/§7 同步；HAC 实现转 T1 |
| **B2** | P2 | [metrics.py:224](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/54-L1架构能力聚合层/l1agg/persistence/metrics.py#L224-L277) | A7 非重叠采样固定相位 `i % h == 0`，换相位结果会变，存在相位选择偏差 | h=20 时非重叠样本仅 53 个，换相位后 IC 可差 0.1 量级 | 输出 h 个相位的均值与极差 | ✅ **已关闭**：遍历 h 个相位，输出 `ric_nonoverlap`（均值）、`ric_nonoverlap_min/max`（极差）、`n_phases`、`n_nonoverlap`；实测 BTC h=20 均值 0.0436、极差 −0.1025~0.2251，证明单相位不可用 |
| **B3** | P2 | [metrics.py:22](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/54-L1架构能力聚合层/l1agg/persistence/metrics.py#L22-L79) | A1 的 chunk 集合随 `n` 变化（n=1093 时最大 512），滚动窗口下 H 会跳变，跨期不可比 | chunks=[8,16,32,64,128,256,512]，无 max_chunk 约束 | 固定 `max_chunk=256` 并写入契约，或输出 `hurst_max_chunk` | ✅ **已关闭**：`HURST_MAX_CHUNK=256` 固定上限，输出 `max_chunk` 与 `quality.hurst_max_chunk`；四资产 H 按新口径重算（BTC 0.6225→0.6470） |

---

## §4 评审过程中已修复项

| ID | 问题 | 位置 | 修复 | 复测 |
|---|---|---|---|---|
| R1 | `variance_ratio` 的 `p` 被 `round(…, 4)`，1e-12 被抹成 `0.0`，违反 SPEC §4.3「禁止用 0 表示无 p 值」 | metrics.py:100 | 移除 p 的 round | 新增 `test_variance_ratio_p_never_zero` ✅ |
| R2 | 样本够但方法失败时 `status=good` + `degraded_reason=partial_methods_failed`，契约自相矛盾 | profile.py:111-117 | 引入 `degraded` 状态 | `test_build_profile_records_failed_methods` 断言 status=degraded ✅ |
| R3 | Hurst docstring 声称「Anis-Lloyd 修正」但只做 `(k-0.5)/k`，实测同序列可给 0.19/0.61/0.62 | metrics.py:23 | 改为「简化修正（不含 k>340 长段修正）」并披露 | 文档一致性 ✅ |
| R4 | SPEC §2 A1 未写明输入是**收益序列**，照文档实现可能对价格算得 H≈1.5 | SPEC §2 | 显式声明输入域 | 文档一致性 ✅ |
| R5 | 原实现为单文件 `l1agg/persistence.py`，与"模块文件夹"要求不符 | — | 重构为包（constants/_stats/metrics/profile/report） | 137 passed ✅ |

### 4.1 复审阶段修复项（v1.1）

| ID | 问题 | 修复 | 复测 |
|---|---|---|---|
| B1 | 趋势 `t` 未做 HAC 且可被误读为显著性 | `trend_slope` 输出 `hac_corrected=False` + `note`；文本追加「t 未做自相关修正」；SPEC §2 判读改为"仅相对比较" | `test_trend_slope_declares_no_hac` ✅ |
| B2 | IC 非重叠口径固定单一相位 | 遍历 h 个相位，输出均值 + `min/max` + `n_phases` + `n_nonoverlap` | `test_ic_decay_reports_all_phases` ✅ |
| B3 | Hurst chunk 随 n 增长，跨期不可比 | `HURST_MAX_CHUNK=256` 固定上限；输出 `max_chunk`、`regime_displayable`、`quality.hurst_max_chunk` | `test_hurst_chunks_capped_for_comparability` ✅ |
| I1 | A4/A5 零收益口径不一致 | A5 改为跳过零收益，A4/A5 均输出 `n_zero` | `test_zero_returns_skipped_and_counted` ✅ |
| I2 | `days` 语义易被读成交易日 | `quality.lookback_days` 回显自然日窗口；CLI help 与 SPEC §5.2 明示 | `test_profile_quality_declares_comparability` ✅ |
| I3 | 无机器可校验契约 | 新增 `contracts/persistence.schema.json`（draft-07，profile/errorProfile） | `test_profile_matches_schema`（jsonschema 校验）✅ |
| I4 | CLI 只能整批落盘 | 新增 `--json`：单资产输出 profile 到 stdout 且不落盘 | `test_report_cli_json_single_asset` ✅ |
| I6 | `hurst` 缺 `max_chunk` | 已输出 | 同 B3 用例 ✅ |
| 反对 2 | 低置信度仍展示 regime 会误导 | `regime_displayable=false` 时文本改为「Hurst=…（口径敏感，仅参考，不作结论）」，不出现持续/反持续/随机 | `test_profile_text_hides_regime_when_low_confidence` ✅ |

---

## §5 非阻断建议（P2/P3）

| ID | 建议 | 理由 | v1.1 状态 |
|---|---|---|---|
| I1 | A5 把 `r==0` 归为 down；A4 丢弃 `r==0`。两处口径不一致 | 契约应统一；都跳过并输出 `n_zero` | ✅ 已采纳 |
| I2 | `days` 实为自然日窗口，建议改名 `lookback_days` | 避免被读成交易日 | ✅ 已采纳（`quality.lookback_days`；入参名保留 `days` 以兼容脚本） |
| I3 | 补 `contracts/persistence.schema.json` | 无机器可校验契约 | ✅ 已采纳 |
| I4 | CLI 增加 `--json` 单资产输出 | 便于前端接入 | ✅ 已采纳 |
| I5 | 跨资产横向比较时强制 BH-FDR（H14） | 4 资产 × 7 指标 = 28 次比较 | ⏳ 转 T1/MERS（本模块不做跨资产推断） |
| I6 | `hurst` 增加 `max_chunk` 字段 | 支撑 B3 可比性判定 | ✅ 已采纳 |

---

## §6 Devil's Advocate（反对意见与让步阈值）

**反对 1：这个模块的信息量为零。**
φ≈0、VR≈0.97–1.12、P(涨|涨)≈0.52–0.55，等于用 7 个指标证明了"日频方向不可预测"。这不需要 300 行代码。
→ **让步阈值**：若 T1/T2 出现「在特定相关 regime 下 VR 稳定 >1.2 且样本外复现」，反对撤回。在此之前，本模块的价值定位应表述为**证伪工具 + 基线**，而非"发现规律"。（v1.1 维持，且 B2 的相位极差进一步证明 h=20 的 IC 不可单点解读）

**反对 2：Hurst 输出会诱导误读。**
H=0.62 配上"持续"标签，用户不会看 `confidence=low`。
→ **让步阈值**：`confidence=low` 时文本模板必须改为「H=0.62（口径敏感，仅参考，不作结论）」并禁止展示 `regime` 标签。**v1.1 已落地，该项撤回。**

**反对 3：纯 stdlib 手写统计有实现风险。**
自写 Pearson/Spearman/OLS/R/S，任一实现错都会静默污染结果。
→ **让步阈值**：现有已知答案测试（AR(1) φ 恢复 ±0.08、精确指数 R²≈1、已知转移矩阵 38/39）已覆盖主要路径；若 CI 上出现任一不稳定或与 scipy 抽样比对偏差 >1e-6，则改用 scipy 并接受依赖成本。

**反对 4：`t=101` 会污染下游。**
最危险的不是数值错，而是数值"太漂亮"。
→ **让步阈值**：B1 落地（HAC 或显式 note）即可撤回。**v1.1 已落地 note + 文本披露，该项撤回**（HAC 实装留 T1）。

---

## §7 验收复测证据（v1.1 复测）

| 项 | 命令 / 对象 | 结果 |
|---|---|---|
| 全量回归 | `python3 -m pytest tests/ -q` | **146 passed**（persistence 27），零失败 |
| 真实数据 | `python3 scripts/persistence_report.py --json`（四资产） | 四资产 profile 正常，`max_chunk=256`，`regime_displayable=false` |
| 结构约束 | BTC profile | `status=good`、`sample_n=1093`、`hurst.confidence=low`、7 项非空 |
| 文本纪律 | 四资产 text | 无"将会/预计/建议"、无"持续/反持续/随机"；均含 `历史统计，不代表未来` |
| 降级路径 | 常数价格合成库 | `status=degraded`、`failed_methods` 含 variance_ratio、文本含"降级" |
| 契约一致性 | `test_profile_matches_schema` | profile 与 errorProfile 均通过 draft-07 校验 |
| CLI 接入 | `--json` 单资产 | stdout 为单个 profile，未产生落盘文件 |

---

## §8 结论与下一步

**裁决**：v1.1 **通过（4.75 / 5.0）**。B1/B2/B3 全部关闭，I1/I2/I3/I4/I6 已落地，反对 2/4 撤回。

**残留（不阻断发布，转 T1）**：
1. HAC/Newey-West 实装（当前仅契约层降级）；
2. 跨资产横向比较的 BH-FDR（I5）；
3. Hurst 低置信度下的样本扩充（当前 1,093 日 < 2,000 门槛）。

**下一步（需用户决策）**：
1. T1 是否启动：相关状态特征 F1–F12 PIT 化。
2. 是否把 `contracts/persistence.schema.json` 接入 API 层响应校验（`/api/data/query`）。

---

## §9 签署

| 角色 | 结论 | 日期 |
|---|---|---|
| 评审（独立复核） | v1.0 有条件通过 4.10/5 → v1.1 通过 4.75/5 | 2026-11-14 |
| 实现 | v1.1 提交（B1/B2/B3 + I 类关闭） | 2026-11-14 |
| 用户 | 待确认 §8 下一步 | — |
