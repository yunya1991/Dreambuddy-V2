# FinBERT 情绪因子端到端评估 + 信号增强 SPEC v1.1（本地修订版：深度文章组合因子路线）

> **状态**: Draft → 待评审
> **日期**: 2026-11-11
> **修订自**: SPEC-EMERGENCE-FINBERT-SENTIMENT-FACTOR-EVAL-v1.0.md（云端快讯版）
> **修订原因**: v1.0 的两项核心假设与本地实况不符——①zh_pipe（valuesimplex/FinBERT2）repo 已 404，本地真实可用中文模型为 18 域 `models/finbert-tone-chinese`；②本地无快讯数据（data_center.db 为空、newsflash_history.jsonl 不存在、p3b 为 0 行），真实数据基础是深度文章（中文 500 篇 + 英文 140 篇）

---

## §0 执行摘要（三句话）

1. **本地实况**: 中文模型为 18 域 `finbert-tone-chinese`（本地目录，已在 `score_zh_sentiment.py` 服役，500 篇中文深度文章已产出文章级分数）；英文模型为 ProsusAI/finbert（本地 `models/finbert`），英文深度文章 140 篇待打分。两者输出本质相同——积极/消极/中性三分类，天然归一到同一因子口径。

2. **数据基础**: 中文深度文章 500 篇（2026-06~11，6 个月覆盖）+ 英文深度文章 140 篇（bitcoinmagazine/cointelegraph/decrypt/newsbtc/bitcoinist 五源）+ p3a 因子样本 500 条 + 39 域事件 2.6 万条。无快讯流，因子粒度从日度改为周度/月度 + 文章级横截面。

3. **目标**: 中英文双本地模型对深度文章打分 → 归一合并 → 组合因子构造（含中英文分歧度独有维度）→ 五层评估（IC → 分层 → 消融 → 状态依赖 → 衰减，horizon 适配拉长）→ 达标后接入 48 域训练样本流与五域/BCRM2 权重体系。

---

## §1 本地环境确认（已核实，2026-11-11）

### 1.1 模型资产

| 模型 | 位置 | 状态 | 标签口径 |
|------|------|------|---------|
| finbert-tone-chinese（中文） | `18-数据获取中心/models/finbert-tone-chinese/` | ✅ 本地存在，`score_zh_sentiment.py` 服役中 | 0=Neutral / 1=Positive / 2=Negative（config.id2label 为准） |
| ProsusAI/finbert（英文） | `9-基本面分析/models/finbert/` | ✅ 本地存在，sentiment_engine en_pipe 服役中 | positive / neutral / negative |
| ~~valuesimplex/FinBERT2~~ | — | ❌ repo 404，不可用（v1.0 假设作废） | — |

**归一化**: 两模型输出统一映射为 score ∈ [-1, +1]（positive=+1 / negative=-1 / neutral=0，按模型置信度加权），sentiment ∈ {positive, neutral, negative}。

### 1.2 数据资产

| 数据源 | 位置 | 量 | 覆盖 | 状态 |
|--------|------|-----|------|------|
| 中文深度文章正文 | `18-数据获取中心/backfill/odaily_p0/contents_all.jsonl` | 500 篇 | 2026-06 ~ 2026-11 | ✅ |
| 中文文章级情绪分数 | `18-数据获取中心/backfill/odaily_p0/sentiment.jsonl` | 500 条 | 同上 | ✅ 已产出（段落切窗 + 段长加权） |
| 英文深度文章正文 | `18-数据获取中心/backfill/en_deep_articles/contents_all.jsonl` | 140 篇 | 五源（每源 8-20 篇） | ✅ 待打分 |
| p3a 因子样本 | `18-数据获取中心/backfill/p3a/dominance_agreement.jsonl` | 500 条 | 2026-06 ~ 2026-11 | ✅（claimed vs measured agreement） |
| 39 域事件 | `39-金融语义蒸馏系统/*.jsonl` | 26,232 条 | — | ✅（contradiction 1376 / semantic 20927 / atomic 3929） |
| ~~odaily 快讯流~~ | — | 0 | — | ❌ 不存在（v1.0 假设作废） |

### 1.3 英文回填调度（样本量增长通道）

`backfill_en_deep_articles.py` 已在 luke crontab（每日 02:50，`--per-source 20`），英文样本持续积累中。

---

## §2 组合因子构造（核心修订：快讯日度 → 深度文章低频）

### 2.1 打分管线

```
中文 500 篇: 复用已有 sentiment.jsonl（零重复计算）
英文 140 篇: ProsusAI/finbert 打分（复用 score_zh_sentiment.py 的切窗+段长加权逻辑改英文版）
              ↓
归一合并: score ∈ [-1,+1]，sentiment 三分类，语言标记 lang ∈ {zh, en}
```

### 2.2 因子定义（两个粒度）

**文章级（横截面，n≈640，统计功效主战场）**:

| # | 因子名 | 公式 | 预期 horizon |
|---|--------|------|-------------|
| A1 | art_sent | 文章级归一分数（发布时点） | 1-4 周 |
| A2 | art_sent_extreme | \|score\|>0.7 的 0/1 标记 | 1-2 周 |
| A3 | art_agreement_gap | p3a 同文章的 claimed vs measured 分歧（联合因子） | 1-4 周 |

**月度/周度时序（n=6 个月，仅作辅助状态维，不做 IC 主检验）**:

| # | 因子名 | 公式 | 说明 |
|---|--------|------|------|
| M1 | sent_mean | 当期文章 score 均值 | 对应 v1.0 F1 |
| M2 | sent_dispersion | 当期 score 标准差 | 对应 v1.0 F2 |
| M3 | sent_asymmetry | (pos-neg)/total | 对应 v1.0 F7 |
| M4 | **cross_lang_divergence** | \|zh_mean - en_mean\| | **独有维度**：中英文叙事分歧，快讯路线不存在 |

### 2.3 信号方向预期

沿用 Fear&Greed 基准（v1.0 附录 A 已验证）：反向（contrarian）——情绪越乐观 → 未来越跌。深度文章预期衰减慢于快讯，IC 峰值 horizon 从 3-7d 拉长至 1-4 周。

---

## §3 五层评估框架（保留 v1.0 框架，适配参数）

| 层 | 方法 | v1.0 参数 | v1.1 适配 |
|----|------|----------|----------|
| L1 IC/ICIR | Spearman RankIC | horizon 1-20d，日度 | **文章级横截面**：因子值 vs 发布后 N 周收益（N=1,2,4,8），n≈640；月度序列仅作辅助 |
| L2 分层回测 | Q1-Q5 五分组 | 5 日收益 | 按文章级因子五分组，发布后 2 周收益，t-test p<0.1 |
| L3 消融 | baseline vs +finbert vs +FG | — | 四组：baseline_tech / +finbert_sentiment / **+p3a_agreement（本地独有对照）** / +FG；指标 AUC/Sharpe/方向准确率 |
| L4 状态依赖 | 高低波动/多空/极端 | — | 保留；波动率 regime 用 vol_20d 中位数分割 |
| L5 衰减+重复性 | IC vs horizon；因子相关矩阵 | 1-20d | horizon 改 1-8 周；**重复性重点**：finbert 情绪 vs p3a agreement vs 39 域 contradiction 三者 Spearman 相关（r≥0.7 丢弃 / 0.3-0.7 正交化 / ≤0.3 真增量） |

**淘汰线（保留 v1.0）**: 文章级 IC 绝对值 < 0.15 且 p > 0.1 → 该因子无效。

---

## §4 信号增强（条件执行）

### 4.1 进入条件

1. L1 文章级至少 2 个因子在 ≥2 个 horizon 上 |IC| > 0.25 且 p < 0.1（较 v1.0 的 0.3 略降——深度文章样本噪声更大）
2. L4 高波动期 IC ≥ 低波动期 × 1.5

### 4.2 接入点

1. **48 域训练样本流**: 通过评估的因子作为新 source 并入 `training_ingest.py` SOURCES（与 p3a/p3b 并列），产出 `finbert_samples.jsonl`
2. **five_domain_subindicator_ic.py**: 因子纳入 dao/tian 维度子指标，跑 IC_IR softmax 加权
3. **BCRM2 washout_features.py**: 评估反向因子作 washout reversal 入场确认信号

---

## §5 交付物

| # | 文件 | 位置 | 用途 |
|---|------|------|------|
| 1 | `score_en_sentiment.py` | `18-数据获取中心/scripts/` | 英文文章打分（复用中文版切窗逻辑） |
| 2 | `finbert_factor_evaluation.py` | `11-易经推理系统/scripts/memory_l4/` | 五层评估主脚本（文章级横截面） |
| 3 | `finbert_daily_factors.csv` | runtime 输出 | 组合因子时序（月度+文章级） |
| 4 | `finbert_eval_report.json` / `finbert_eval_summary.md` | runtime 输出 | 评估结果与人类可读摘要 |

---

## §6 验收清单

### P0 就绪（部分已完成）
- [x] 中文模型本地存在且服役（finbert-tone-chinese）
- [x] 中文 500 篇文章级分数已产出（sentiment.jsonl）
- [x] 英文模型本地存在（ProsusAI/finbert）
- [x] 英文 140 篇正文已回填（en_deep_articles）
- [ ] 英文 140 篇打分完成（score_en_sentiment.py）
- [ ] 中英文归一合并产物落盘

### P1 五层评估
- [ ] L1: ≥2 个文章级因子 |IC|>0.25 且 p<0.1
- [ ] L2: 五分组 spread 显著（p<0.1）
- [ ] L3: +finbert vs baseline 有正向增量；p3a_agreement 对照完成
- [ ] L4: 高波动期 IC ≥ 低波动期 × 1.5
- [ ] L5: 衰减曲线 1-4 周有峰值；三因子相关矩阵完成

### P2 信号增强（条件）
- [ ] 通过因子并入 training_ingest SOURCES
- [ ] subindicator IC_IR 加权完成
- [ ] BCRM2 集成测试完成

---

## §7 风险与 fallback

| 风险 | 概率 | 缓解 |
|------|------|------|
| 月度时序仅 6 点，IC 无统计功效 | **高** | 主检验走文章级横截面（n≈640）；月度仅作辅助状态维；等英文回填积累样本 |
| 英文 140 篇按发布期聚集，横截面独立性不足 | 中 | 按发布月份聚类稳健标准误（cluster-robust SE）；或按周聚合降频 |
| 文章级 IC < 0.15（无信号） | 中 | 接受负结论记入认知库；检查是否标签映射/切窗聚合损失信息 |
| 中英文分歧度因子无先验基准 | 中 | 作探索性维度，不设淘汰线外的强预期；仅报告不进主线 |

---

## §8 执行计划

```
Step 1: [P0] 英文打分脚本 + 中英文归一合并（半天）
Step 2: [P1] 五层评估主脚本 + 首次运行（1 天）
Step 3: [P1] 深度分析：状态依赖/衰减/三因子相关（半天）
Step 4: [P2] 条件执行：接入 training_ingest / subindicator / BCRM2（视结果）
Step 5: [验收] 报告 + SPEC 状态更新
```

---

## 附录 A: Fear&Greed Benchmark（沿用 v1.0，已验证）

| 因子 | Horizon | IC | p-value | 方向 |
|------|---------|-----|---------|------|
| fg_delta_3d | 3d | -0.4826 | 0.013 | 反向 |
| fg_delta_3d | 5d | -0.4532 | 0.022 | 反向 |
| fg_norm | 5d | -0.3775 | 0.027 | 反向 |

FinBERT 深度文章因子达到类似量级即算成功；horizon 预期右移至 1-4 周。

## 附录 B: v1.0 → v1.1 修订对照

| 维度 | v1.0（云端快讯版） | v1.1（本地深度文章版） |
|------|-------------------|----------------------|
| 中文模型 | zh_pipe = valuesimplex/FinBERT2（已 404） | 18 域 finbert-tone-chinese（本地服役） |
| 数据源 | odaily 快讯流（本地不存在） | 中文 500 篇 + 英文 140 篇深度文章 |
| 因子粒度 | 日度（τ=24h 衰减） | 文章级横截面 + 月度/周度辅助 |
| IC horizon | 1-20d | 1-8 周 |
| 独有维度 | — | cross_lang_divergence（中英文分歧度）、art_agreement_gap（与 p3a 联合） |
| 消融对照 | +FG | +FG + **p3a_agreement** |
| 主检验统计功效 | 日度 n 大 | 文章级 n≈640（月度仅 6 点，降级为辅助） |
