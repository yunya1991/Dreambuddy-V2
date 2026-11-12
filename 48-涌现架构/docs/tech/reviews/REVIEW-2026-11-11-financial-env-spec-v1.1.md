# 评审报告 — SPEC-EMERGENCE-FINANCIAL-ENV v1.1（六维）

- 评审日期：2026-11-11
- 评审对象：[SPEC-EMERGENCE-FINANCIAL-ENV-v1.0.md](../SPEC-EMERGENCE-FINANCIAL-ENV-v1.0.md)（文件名 v1.0，内容版本 v1.1）
- 评审依据：[REVIEW-CHECKLIST-v0.1.md](../REVIEW-CHECKLIST-v0.1.md) 六维检查清单
- 评审方式：文档 vs 仓库现实（逐项核验文件存在性 / 数据分布 / 存量考古 / 强制点）
- 结论：**不通过**。设计层成立，但存在 2 个数据前置性 P0（S 层样本不足、中文模型缺失），若不关闭则 v1 无法产出任何可信结论。文档已按本报告修订为 v1.2。

---

## 0. 一句话结论

> 架构设计（E×S×M×P 四层 + 龙头宇宙投影 40 + 三维联合验证）**方向正确且有调研支撑**；但**当前数据条件不允许任何统计结论**——S 层有效日级样本只有 13 天，F&G 只有 36 天，而 v1 的验收标准是"重判 F&G 的显著性"。必须先回填数据，再谈评估。

---

## 1. 六维逐项结论

| 维度 | 结论 | 关键证据 |
|---|---|---|
| 1 引用存在性 | ✅ **通过**（10/10 文件存在）+ ⚠️ 1 处语义失真 | 见 §2 |
| 2 数据资产健康度 | ❌ **不通过** | S 层仅 13 天有效日级因子；F&G 仅 36 天；40 产出物停滞 11-05 |
| 3 模型-数据版本一致性 | ❌ **不通过** | 云端只有英文 FinBERT，但 64% 有效文本是中文 |
| 4 存量资产盘点 | ❌ **不通过**（原方案重复建设） | 45 评测系统已有 DSR/PBO/purged CV，P0-D 原计划却要新建 |
| 5 门禁强制等级 | ⚠️ **部分通过** | §7.5 统计纪律全为文档自律，无强制点 |
| 6 主链可观测性 | ⚠️ **部分通过** | 无 event→sentiment→factor→verdict 的 joinable trace |

---

## 2. 维度 1：引用存在性 ✅（但有 1 处语义失真）

**逐项核验（全部 OK）**：

```
OK  21-特征工程中心/feature_hub/modules/classic_indicators.py
OK  21-特征工程中心/feature_hub/modules/talib_aligned.py
OK  18-数据获取中心/data_center/processing/factor_extractor.py
OK  18-数据获取中心/data_center/processing/dimension_context.py
OK  18-数据获取中心/data_center/collectors/chain/fear_greed_collector.py
OK  40-周期神经网络系统/asset_classes.py
OK  48-涌现架构/metrics/emergence_metrics.py
OK  9-基本面分析/engines/event_ledger_engine.py
OK  9-基本面分析/engines/event_mapping_engine.py
OK  9-基本面分析/engines/news_contract_validator.py
```

**语义失真（已修）**：v1.1 原文称"39 已有 20927 条语义事件，能提供 FinBERT 上下文"。实测 `semantic_events.jsonl` 的 `source` 分布：

```python
[('trader.log', 20927)]   # 100%，零条新闻事件
```

→ 这些是**交易日志派生事件**，不含任何新闻语义。SPEC 已改为"零新闻语义事件，P0-A 是新建通道而非接线复用"。

**新发现 P0-1**：9 域已有 `event_ledger_engine.py` / `event_mapping_engine.py` / `news_contract_validator.py` 三套事件契约，本 SPEC §3.1 的 `EventSchema` 是第四套。**开工前必须先做契约对齐评估**，否则事件层会出现四个互不兼容的 schema。

---

## 3. 维度 2：数据资产健康度 ❌（最严重）

| 数据 | 实测 | 对 v1 的影响 |
|---|---|---|
| Odaily 新闻 | 3048 条中 **2096 条（69%）无 description**，有效文本 731 条；其中 470 条中文、261 条英/混 | S 层可打分样本只有 731 条 |
| S 层日级因子 | 聚合后**仅 13 天**有效 | **无法计算 ICIR、无法做状态分桶、无法做 5 fold 消融** |
| crypto F&G | 36 天（2026-09-09~10-29） | t>3 检验需要 ≥250 观测；36 天**统计上不可能显著** |
| fear_greed_enhanced | 30 天（4 子维度） | 子维度状态依赖检验样本不足 |
| BTC 价格 | 1765 天（2022-01-01~） | ✅ 唯一充足的数据 |
| 40 产出物 | 停滞于 2026-11-05（`cycle_state.json`/`asset_rotation.json`/`washout_verdicts.json`） | U 层龙头资产的 MA200 锚大面积为空 |
| 云端 40 链路 | 首节点 `p1_real_cycle.py` 失败：`no such table: records`（18 写 PG / 40 读 SQLite） | 云端无法产出新数据 |

**新发现 P0-2（v1 阻塞级）**：**v1 的验收标准（"重判 F&G 显著性"）在当前数据量下不可完成**。

**但这不是死结**：`fear_greed_collector.py` 支持 `limit=0` 拉 alternative.me 全历史（2018-02 至今 ≈ 3000 天），只是**尚未回填**。这是低成本高收益动作：

> **建议新增 P0-E（数据回填，与 P0-D 并行）**：
> 1. 回填 F&G 全历史（2018→今，≈3000 天）
> 2. 回填 Odaily 正文缺失的 2096 条（若源站已删则标注不可恢复）
> 3. 补齐 40 云端 PG/SQLite 后端错配（否则 U 层无 MA200）
>
> 验收：F&G ≥2500 天、S 层日级因子 ≥250 天；否则 v1 只能出"inconclusive"。

---

## 4. 维度 3：模型-数据版本一致性 ❌

| 项 | 事实 | 结论 |
|---|---|---|
| 本地中文模型 | `valuesimplex/FinBERT2` 已 404 | 不可用 |
| 云端模型 | `yiyanghkust/finbert-tone-chinese`（中文，`bert-base-chinese` 微调，Acc 0.88；2026-11-11 用户修正确认） | 模型可用，但**代码未接上** |
| 代码实际加载 | 硬编码 `valuesimplex/FinBERT2`（已 404），中文路径无 env 覆盖 | 云端模型与仓库代码不一致 |
| 文本语言分布 | 731 条中 470 条中文（**64%**） | 64% 文本本应走中文模型 |
| 标签映射 | `FINBERT_ZH_LABEL_MAP` **无 `LABEL_0/1/2`**，而 tone-chinese 恰好只输出这三个标签 | 每条中文 `return None` |
| 实际后果 | `return None` → 静默回退 27 关键词规则引擎 | **"有模型但从未用上"** |
| 路由阈值 | `chinese_ratio >= 0.30`（`sentiment_engine.py:46`） | 中文占比 30% 即判中文 |
| 失败行为 | zh_pipe 为 None 时**跨语言 fallback 到 en_pipe**（`sentiment_engine.py:396-405`） | **静默污染**：不报错、不标记 |

**新发现 P0-3（2026-11-11 修正）**：真实缺陷不是"没有中文模型"，而是**"中文模型在、但代码接不上"**——`finbert-tone-chinese` 输出 `LABEL_0/1/2`，而 `FINBERT_ZH_LABEL_MAP` 只认 `positive/negative/neutral/利好/利空...`，于是 `label_map.get()` 全部落空 → `return None` → 每条中文静默回退规则引擎。这解释了为什么此前观察到"中文全 neutral/无差异"：不是模型不行，是**映射缺三个键**。

**修复要求（已写入 SPEC §4.1 硬约束 4）**：
1. 路由目标模型缺失 → 直接返回 `None`，**禁止**跨语言 fallback
2. 事件必须标 `model="unavailable"` 或 `model="rule_fallback"`，**禁止**伪装成 FinBERT
3. 中期：引入中文金融模型（备选：中文 RoBERTa 金融微调、IDEA-CCNL/Erlangshen-Roberta-110M-Sentiment、或云端自建微调）

---

## 5. 维度 4：存量资产盘点 ❌

| 原 SPEC 计划 | 仓库已有 | 处置 |
|---|---|---|
| 新建 `48/metrics/stat_discipline.py` 实现 DSR/PBO/purged CV | **45-评测系统已实现**：`evaluators/finance/backtest.py` 的 `deflated_sharpe_ratio` / `pbo_cscv` / `probabilistic_sharpe_ratio` / `expected_max_sharpe`；`evaluators/common/split.py` 的 `purged_kfold` / `walk_forward` / `embargo_length` / `verify_no_leakage` | **改为接线复用**（SPEC §7.5 已修） |
| 新建龙头宇宙 | `40/asset_classes.py` + `ASSET-CLASS-MAP.md` 已核验 10 大类 | 已改为投影（v1.1 修） |
| 新建深度文章三层抽象 | `factor_extractor.py` 的 F1/F2/F3 已实现 | 已改为扩展（复用） |
| 新建 EventSchema | 9 域三套事件引擎已存在 | ⚠️ **未处置**（P0-1，需契约对齐评估） |
| VIX 采集 | `nanoclaw/market_data.py` 已有孤立实现 | 应"迁入 18 主链"而非"新写"（SPEC 已表述为"入主链"，需明确不重写解析逻辑） |

**新发现 P1-1**：VIX 迁入时若重写解析，会与 nanoclaw 版本产生双口径（同 G10 的价格双源问题）。应改为"提取 → 提升为 18 collector → nanoclaw 反向 import"。

---

## 6. 维度 5：门禁强制等级 ⚠️

§7.5 的六道关（试验记账 / t>3 / DSR / PBO / 嵌套 CV / 样本外冷却）**全部是文档自律**，代码层无强制点：
- 无 `trials.jsonl` 写入点 → N 无法统计 → DSR/PBO 无输入
- 无因子注册闸门 → 任何脚本可绕过 §7.5 直接产 verdict
- `verdict` 四态无枚举定义 → 字符串自由填写

**新发现 P0-4（门禁无强制点）**：必须提供唯一入口 `assert_gate(factor, verdict)`，并在 48 的因子注册/verdict 落盘函数内强制调用（参数级强制，非文档约定）。参照 CHECKLIST 维度 5 的 v0.4 处置范式（`exclude_out_of_sample_interval` 参数 + `is_in_oos_interval` hook）。

---

## 7. 维度 6：主链可观测性 ⚠️

需要 joinable 链：`event_id → sentiment_record → factor_value → verdict → 消费方`。现状：
- 48 已有 `metrics/emergence_metrics.jsonl` + `verdict_dashboard.json`（格式可复用）
- 但事件层/情绪层无 `trace_id`，无法把"某条新闻"追到"某个因子值"
- 无决策回放器（CHECKLIST v0.4 已记录为全仓公共瓶颈）

**新发现 P1-2**：EventSchema 必须加 `trace_id`（= `event_id` 派生），S 层因子与 verdict 全链透传，否则 L-C 三路消融无法归因到具体事件。

---

## 8. 问题清单与处置

| ID | 级别 | 问题 | 处置 | 状态 |
|---|---|---|---|---|
| P0-1 | P0 | EventSchema 与 9 域三套事件契约冲突风险 | **已定方案 C**（SPEC v1.3 §3.0）：三层复用 + 最小扩展，canonical = EventLedger entry，`EventSchema` → `EventRecord`（+7 字段），信封加 `raw_tradefin[]`，类型枚举 +6 类 | **✅ 设计已关闭 / 实现 open** |
| P0-2 | P0 | S 层仅 13 天有效日级因子，v1 验收不可完成 | 新增 P0-E 数据回填（F&G 全历史 + Odaily 正文 + 40 后端修复） | **open** |
| P0-3 | P0 | 中文文本经英文 FinBERT 静默打分（64% 文本受影响） | **已修复（2026-11-11）**：中文模型切 `finbert-tone-chinese` + `id2label`/模型卡契约双来源映射 + 删除跨语言 fallback + `with_meta` 溯源；实测 +0.9992/-0.9981/0.0，9 单测 + 14 回归通过 | **✅ 已关闭** |
| P0-4 | P0 | 统计门禁无强制点，可被绕过 | **已定设计**（SPEC v1.3 §7.6）：唯一入口 `assert_gate()`（7 步短路判定）+ 五态 verdict + `trials.jsonl` + 四强制点（注册/落盘/只读/CI）+ `gate_bypass_log.jsonl` 可审计绕过 | **✅ 设计已关闭 / 实现 open** |
| P1-1 | P1 | VIX 迁入可能产生双口径 | 提取+提升，不重写解析；nanoclaw 反向 import | **open** |
| P1-2 | P1 | 无 joinable trace | EventSchema 加 `trace_id`，全链透传 | **open（文档已写入要求）** |
| P1-3 | P1 | 40 产出物停滞 11-05 + 云端 PG/SQLite 错配 | 并入 P0-E | **open** |
| ✅-1 | — | P0-D 重复建设统计函数 | 改为接线 45 评测系统 | **已修（v1.2）** |
| ✅-2 | — | 39 "20927 条语义事件"表述失真 | 改为"100% trader.log，零新闻" | **已修（v1.2）** |
| ✅-3 | — | 龙头宇宙另起一套 | 改为投影 40 asset_classes | **已修（v1.1）** |

---

## 9. 评审结论

**不通过，需修订后复审。** 修订要点：
1. ✅ 已修：统计设施复用 45、39 表述修正、中文模型事实修正、U 层投影 40
2. ⬜ 待补：P0-E 数据回填章节、P0-1 事件契约对齐方案、P0-4 门禁强制点设计
3. ⬜ 待决：**实施顺序需调整**——原定 P0-D 先行，但 P0-D 的验收依赖 ≥250 天样本；因此 **P0-E（回填）必须与 P0-D 并行启动**，否则 D 做完也无法验收

**预计复审时机**：P0-E 回填完成 + P0-1/P0-4 方案补齐后。
