# FinBERT 情绪因子端到端评估 + 信号增强 SPEC (云端开发版)

> **状态**: Draft → 待评审
> **日期**: 2026-11-11
> **执行环境**: 云端 Ubuntu 22.04（已有中英文 FinBERT 模型）
> **前置确认**: 云端 SentimentEngine 的 zh_pipe + en_pipe 均能加载成功

---

## §0 执行摘要（三句话）

1. **本地调研结论**: ProsusAI/finbert（英文）能跑但 zh_pipe (valuesimplex/FinBERT2 repo 已 404) 本地加载失败；Fear&Greed 反向信号 IC=-0.37~-0.48 (p<0.05) 是可靠 benchmark，可作为 FinBERT 因子信号方向的预期基准。

2. **云端优势**: 用户确认云端已有中英文 FinBERT 模型（zh_pipe + en_pipe 均可加载），且云端已长期运行 SentimentEngine 处理 Odaily 快讯 → 可直接在云端跑完整评估，无需先解决模型下载/安装问题。

3. **目标**: 在云端用完整双引擎 SentimentEngine 对 Odaily（+ 其他新闻源）做情绪打分 → 聚合日级因子 → 五层评估（IC → 分层 → 消融 → 状态依赖 → 衰减）→ 如果 IC 达到 Fear&Greed 基准量级 → 接入现有五域/BCRM2 权重体系做信号增强。

---

## §1 云端环境确认（开发前置条件）

### 1.1 SentimentEngine 双引擎状态

云端 SSH 登录后立即验证：

```bash
cd /home/luke/dreambuddy-v2/9-基本面分析
USE_FINBERT=1 python3 -c "
import os; sys.path.insert(0, '.')
from engines.sentiment_engine import SentimentEngine
se = SentimentEngine()
se._ensure_engines()
print(f'eng_ready={se._eng_ready}')
print(f'en_pipe={se._en_pipe is not None}')   # ProsusAI/finbert
print(f'zh_pipe={se._zh_pipe is not None}')   # valuesimplex/FinBERT2 或用户自建中文模型

# 测试英文
r1 = se.analyze_text('BlackRock spot bitcoin ETF sees record inflow of \$1 billion')
print(f'EN test: score={r1[\"score\"]:.3f}, sent={r1[\"sentiment\"]}')

# 测试中文
r2 = se.analyze_text('贝莱德比特币现货ETF单日净流入10亿美元创历史新高')
print(f'ZH test: score={r2[\"score\"]:.3f}, sent={r2[\"sentiment\"]}')
"
```

**预期**: `zh_pipe=True` + 中文文本返回非 0 score + 英文文本也返回非 0 score。

**如果 zh_pipe=False**:
- 检查 `~/.cache/huggingface/hub/models--valuesimplex--FinBERT2/` 是否存在
- 如果 repo 已恢复，直接联网下载：`python3 -c "from transformers import pipeline; pipeline('text-classification', model='valuesimplex/FinBERT2')"`
- 如果 repo 还是 404，需要找替代中文金融 BERT（见 §6）

### 1.2 云端数据覆盖

检查 data_center.db 里云端实际采集的新闻量：

```bash
sqlite3 /home/luke/dreambuddy-v2/18-数据获取中心/data_center.db "
SELECT source, COUNT(*) as rows, 
       COUNT(DISTINCT date(timestamp)) as days,
       MIN(date(timestamp)), MAX(date(timestamp))
FROM records 
WHERE source IN ('odaily_newsflash', 'gdelt', 'panewslab', 'tavily')
GROUP BY source
"
```

**目标**: 至少 6 个月新闻历史，300+ 天有 description 文本 → 才能产出统计显著的 FinBERT 因子 IC。

### 1.3 云端依赖确认

```bash
pip3 list | grep -E "torch|transformers|sentencepiece|lightgbm|xgboost|scikit-learn|yfinance"
```

**必需**: torch, transformers, sentencepiece, scikit-learn
**可选**: lightgbm / xgboost（用于消融实验中的模型对比）

---

## §2 五层评估框架（云端开发）

### §2.1 总体架构

```
Step 1: 从 data_center.db 拉所有含 description 的新闻
              │
              ▼
Step 2: 云端 SentimentEngine 双引擎打分
         zh-heavy → zh_pipe (中文 FinBERT)
         mix/en  → en_pipe (ProsusAI/finbert)
              │
              ▼
Step 3: 日级因子聚合（7 个因子 + 时间衰减 τ=24h）
              │
    ┌─────────┼─────────┼─────────┬─────────┐
    ▼         ▼         ▼         ▼         ▼
  层1 IC    层2 分层   层3 消融   层4 状态   层5 衰减
  ICIR       Q1-Q5    +FG对比    高/低波   信号vs horizon
```

### §2.2 FinBERT 因子构造

对每条新闻 → SentimentEngine.analyze_text → 按日期聚合（time_decay 加权）：

| # | 因子名 | 公式 | 预期 horizon |
|---|--------|------|-------------|
| F1 | **sent_mean** | `mean(score × time_decay)` | 3-7d |
| F2 | **sent_dispersion** | `std(score × time_decay)` | 3-10d |
| F3 | **sent_extreme_ratio** | `|score|>0.7 的条数 / 总条数` | 1-5d |
| F4 | **sent_delta** | `F1_today - F1_yesterday` | 1-3d |
| F5 | **sent_count** | 当日有效快讯条数（代理流动性） | 不直接用 |
| F6 | **sent_intensity** | `abs(F1)` | 3-7d |
| F7 | **sent_asymmetry** | `(pos_count - neg_count) / total` | 3-7d |

### §2.3 Layer 1: IC / ICIR 检验

**方法**: Spearman RankIC（因子值 vs 未来 N 日收益率），滚动窗口 ICIR

**FinBERT 因子的 IC 预期**（基于 Fear&Greed benchmark）:
| 因子 | Horizon | 预期 IC | p-value 阈值 |
|------|---------|---------|-------------|
| F1 sent_mean | 3d | -0.3 ~ -0.5 | p < 0.1 |
| F1 sent_mean | 5d | -0.35 ~ -0.55 | p < 0.05 |
| F2 dispersion | 5d | +0.3 ~ +0.5 | p < 0.1 |
| F7 asymmetry | 5d | -0.3 ~ -0.5 | p < 0.05 |

> **信号方向预期**: 反向 (contrarian)——情绪越乐观 (sent_mean > 0) → BTC 未来越跌 (ret < 0)。这是 Fear&Greed benchmark 已验证的方向，FinBERT 应一致。

**淘汰线**: IC 绝对值 < 0.15 且 p > 0.1 → 该因子无效，不进后续层。

### §2.4 Layer 2: 分层回测

每日按 FinBERT 因子值分 5 组 (Q1 最强 → Q5 最弱) → 计算每组未来 5 日收益：

- ✅ Q1-Q5 spread 显著 (t-test p < 0.1) → 有效
- ✅ 曲线尽量单调 → 稳定
- ⚠️ 仅极端组有差异 → 不稳定，只做 regime-aware

**与 Fear&Greed 对比**: Fear&Greed spread ~0.02/5d，FinBERT 应达到类似量级。

### §2.5 Layer 3: 消融实验

三组对比：
```
baseline_tech  = 技术指标 (MA/RSI/ATR/vol/momentum)
plus_finbert   = 技术指标 + FinBERT F1~F7
plus_fg        = 技术指标 + Fear&Greed (对照组)
only_finbert   = 仅 FinBERT
```

**评估指标**:
| 指标 | 基线预期 | +FinBERT 预期提升 |
|------|---------|------------------|
| AUC | 0.50-0.55 (BTC 弱有效) | +0.02~0.05 |
| Sharpe | ±0.3 (波动) | +0.3~0.8 |
| 方向准确率 | 50-52% | +3-6% |

### §2.6 Layer 4: 状态依赖检验

| 分组维度 | 分割方式 | 预期 |
|---------|---------|------|
| 波动率 regime | vol_20d > median | **高波动期 IC 2-3 倍更强** (Fear&Greed 已验证) |
| 市场方向 | BTC vs MA200 (多/空) | 下跌市负向情绪 IC 更强 |
| 情绪极端 | FG > 0.8 或 < 0.2 | 极端情绪 FinBERT 边际贡献更大 |

### §2.7 Layer 5: 衰减 + 重复性

**衰减曲线**: IC vs horizon (1, 3, 5, 7, 10, 20d)
- 预期: 3-7d IC 峰值 → 10d 衰减 50% → 20d 耗尽

**重复性排查**: FinBERT 因子 vs 已有因子 (动量/波动率/Fear&Greed) 的 Spearman 相关矩阵
- r ≥ 0.7 → 重复代理，需正交化或丢弃
- r 0.3-0.7 → 部分重叠，加 regularization
- r ≤ 0.3 → 真正增量

---

## §3 信号增强（条件执行）

### §3.1 进入条件

**必须同时满足**:
1. Layer 1 IC 至少 2 个因子在 ≥2 个 horizon 上 |IC| > 0.3 且 p < 0.1
2. Layer 4 状态依赖显示高波动期 IC 比低波动期强 ≥ 1.5 倍

### §3.2 交互因子构造（核心创新点）

```python
# 基础反向因子
finbert_contrarian = -sent_mean  # 反向

# 状态依赖交互因子 (核心!)
vol_regime = 1 if vol_20d > vol_median else 0
finbert_vol_interact = finbert_contrarian × vol_regime  # 仅在高波动期生效

# 极端情绪放大
extreme_regime = 1 if abs(sent_mean) > 0.5 else 0
finbert_extreme = finbert_contrarian × extreme_regime
```

### §3.3 接入现有体系

1. **five_domain_subindicator_ic.py**: 把通过检验的 FinBERT 因子纳入 dao/tian 维度的子指标，跑 IC_IR softmax 加权
2. **sentiment_bridge.py**: 扩展为支持多因子输出（当前只桥接 sentiment_score）
3. **BCRM2 washout_features.py**: 评估 FinBERT 反向因子能否给 washout reversal 提供入场确认信号

---

## §4 交付物

| # | 文件 | 位置 | 用途 |
|---|------|------|------|
| 1 | `finbert_factor_evaluation.py` | 云端 `/home/luke/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/` | 五层评估主脚本 |
| 2 | `finbert_daily_factors.csv` | 云端 runtime 输出 | FinBERT 日级因子，可复用 |
| 3 | `finbert_eval_report.json` | 云端 runtime 输出 | 完整评估结果 |
| 4 | `finbert_eval_summary.md` | 云端 runtime 输出 | 人类可读摘要，含 IC/分层/消融/状态依赖结论 |
| 5 | SPEC 更新 | 本地 `docs/superpowers/specs/` | 根据云端评估结果更新 |

---

## §5 验收清单

### P0 云端就绪（立即执行）
- [ ] SSH 登录云端验证 zh_pipe + en_pipe 均加载成功
- [ ] 英文文本 → ProsusAI/finbert 返回非 0 score
- [ ] 中文文本 → zh_pipe 返回非 0 score
- [ ] data_center.db 新闻源覆盖 ≥ 6 个月
- [ ] 依赖 torch + transformers + sentencepiece 已装

### P1 五层评估
- [ ] Layer 1: ≥ 2 个因子 IC 绝对值 > 0.3 且 p < 0.1（基准线）
- [ ] Layer 2: Q1-Q5 spread 显著 (p < 0.1)
- [ ] Layer 3: 消融实验 +FinBERT vs baseline 有正向增量
- [ ] Layer 4: 高波动期 IC ≥ 低波动期 IC × 1.5
- [ ] Layer 5: 衰减曲线在 3-7d 有明显峰值

### P2 信号增强（条件）
- [ ] ≥ 2 个 FinBERT 因子纳入 subindicator IC_IR 加权
- [ ] 交互因子 `FinBERT × vol_regime` IC > 单独 FinBERT IC
- [ ] BCRM2 / washout 模块完成集成测试

---

## §6 风险与 fallback

| 风险 | 概率 | 缓解 |
|------|------|------|
| 云端 zh_pipe 也无法加载 | 低（用户确认已有模型） | 1. 手动 `hf download` 到本地 models 目录 2. 换中文模型（见下方） 3. 暂时只用 ProsusAI/finbert + 英文新闻源 |
| 新闻历史不足 3 个月 | 中 | 1. 先回补 Odaily 历史 2. 同时接 Gdelt/Tavily 扩展覆盖 |
| FinBERT IC < 0.15（无信号） | 低但需准备 | 1. 可能数据源/模型质量问题 → 换模型或清洗数据 2. 可能情绪不是 factor → 接受负结论，记录到认知库 |

### §6.1 中文金融 BERT 备选（zh_pipe 失败时）

| 模型 | repo_id | 特点 |
|------|---------|------|
| hfl/chinese-finbert-wwm-ext | HuggingFace | 哈工大，金融领域预训练 |
| pankajr123/finbert-chinese | HuggingFace | 社区微调版 |
| 自建 | 本地训练 | 用 SentimentEngine 规则引擎打标签 + BERT 微调 |

**切换方法**:
```python
# SentimentEngine.py 第 346 行，把硬编码的 repo_id 改成环境变量
ZH_REPO_ID = os.environ.get("FINBERT_ZH_MODEL", "valuesimplex/FinBERT2")
# 这样云端只需 export FINBERT_ZH_MODEL=xxx 就能切换
```

---

## §7 开发执行计划

```
Day 1: [云端确认] 验证 zh_pipe + en_pipe + 数据覆盖 + 依赖
         ↓
Day 2: [脚本编写] finbert_factor_evaluation.py（五层评估主脚本）
         ↓
Day 3: [运行 + 诊断] 首次评估 + IC/ICIR + 分层回测 + 消融
         ↓
Day 4: [深度分析] 状态依赖 + 衰减 + 重复性 → 识别有效因子
         ↓
Day 5: [信号增强] 交互因子构造 + 接入 subindicator IC_IR 加权（条件）
         ↓
Day 6: [验收 + 报告] 五层评估验收清单 + MD 摘要 + SPEC 更新
```

---

## 附录 A: Fear&Greed Benchmark（已验证）

作为 FinBERT 因子的预期信号方向和强度基准：

| 因子 | Horizon | IC | p-value | 方向 | 状态依赖 |
|------|---------|-----|---------|------|---------|
| fg_delta_3d | 3d | **-0.4826** | 0.013 | 反向 | 高波动 IC 2.3× |
| fg_delta_3d | 5d | **-0.4532** | 0.022 | 反向 | 高波动 IC 2.3× |
| fg_norm | 5d | **-0.3775** | 0.027 | 反向 | 相似 |
| fg_momentum | 5d | -0.0477 | 0.842 | 低波动期无效 | **高波动 IC 20×更强** |

**预期 FinBERT 因子达到类似 IC 值就是成功**——不需要比 Fear&Greed 更强，作为另类因子能提供不同维度的增量信息即可。

## 附录 B: 本地 vs 云端差异回顾

| 维度 | 本地（macOS） | 云端（Ubuntu 22.04） | 备注 |
|------|-------------|-------------------|------|
| transformers | ✅ | ✅（用户确认） | |
| torch | ✅ | ✅ | |
| sentencepiece | ✅ | ✅ | zh_pipe tokenizer 需要 |
| en_pipe (ProsusAI/finbert) | ✅ 本地 `models/finbert/` | ✅ | |
| zh_pipe | ❌ repo 404 | ✅（用户确认已有） | **云端核心优势** |
| Odaily 覆盖 | 13 天有效日因子 | 待查 | 云端应更长 |
| Fear&Greed | 36 天 | 待查 | 可直接用 |
| GPU | 无（CPU FP32 ~47ms/条） | 可能有 | FP16 加速 5× |
