# RESEARCH — D1 叙事原语管道五决策点调研建议 v0.1

> **日期**：2026-11-09
> **目的**：为 [SPEC-D1-NARRATIVE-PRIMITIVES-v0.1](../SPEC-D1-NARRATIVE-PRIMITIVES-v0.1.md) §5 的 D1-D5 决策点提供基于①自身代码现状 ②传统金融成熟实践 ③AI 成熟经验 的最优建议，供用户终审。
> **方法**：仓库实证（DB 统计/依赖盘点/Grep）+ 外部文献交叉验证。

---

## D1 encoder 选型 → **FinBERT2 主线（✅ 2026-11-09 实证通过，已锁定），仓内中文 FinBERT 兜底**

> **验证结果（用户关切"中文是否行"→ 实证打消）**：HF `valuesimplex-ai-lab/FinBERT2-base`（15.9k 下载，apache-2.0，language=zh，基于 hfl/chinese-roberta-wwm-ext + 32B 中文金融语料续训）。本机 torch 2.11 + transformers 5.8.0 冒烟通过：中文金融句分词正确、前向 (1,20,768) 正常；加载报告 UNEXPECTED=MLM 头 / MISSING=pooler，属微调场景正常项。模型已入本地 HF 缓存，P1 可直接启动训练。

**三维证据**：

| 维度 | 证据 |
|---|---|
| 代码现状 | [pyproject.toml](../../../../pyproject.toml) 已有 `torch>=2.0` + `sentence-transformers>=2.0`；[sentiment_engine.py](../../../../9-基本面分析/engines/sentiment_engine.py#L321-L350) 已在用**中文 FinBERT pipeline**（transformers，冷启动下载 ~420MB）——即 R2 所需的训练/推理栈**零新增基础设施** |
| AI 成熟经验 | **FinBERT2**（arXiv 2506.06335，2025）：迄今最大中文金融预训练语料（32B tokens）的 bidirectional encoder，判别式金融分类任务上超过所有既有 (Fin)BERT 变体、并超过领先 LLM；论文结论明确"encoder-only 模型在金融 NLP 判别任务上仍不可替代"——与我们"非 LLM 做抽取"的路线完全一致 |
| 金融实践 | 金融 NLP 的判别式任务（事件分类/方向判断/论元抽取）业界标配仍是 encoder 微调（BloombergGPT 评测中 FinBERT 类模型在判别任务上与 LLM 打平或更优），推理成本比 LLM 低 2-3 个数量级，适合 6 万+ 篇存量批处理 |

**结论**：优先级 **FinBERT2 > 仓内中文 FinBERT（已在 sentiment_engine 服役，零成本兜底）> RoBERTa-wwm-ext（通用对照组）**。三个都训，主报表用 FinBERT2，另两个作消融对照——对照成本极低（共用同一标注集与训练管线）。
**风险**：FinBERT2 权重需从 HuggingFace 下载并确认许可证，若不可得自动降级为仓内中文 FinBERT，方案不变。

---

## D2 标注人力 → **建议升级：弱监督聚合（Snorkel 模式），用户只仲裁分歧样本**

初版建议是"R1 预标注 + 用户修订 500 条"（工作量 ~1/3）。调研后可再降一档：

| 维度 | 证据 |
|---|---|
| AI 成熟经验 | **Snorkel 弱监督**（Stanford，VLDB/NeurIPS 系列）：用户写的标注函数（labeling functions）允许多噪声、可相关，生成模型自动去噪聚合出概率标签——官方口径"数小时数天建成训练集，替代数周数月手工标注"。**R1 的规则/触发词典天然就是 labeling functions**，不需要为 Snorkel 额外写东西 |
| 金融实践 | 金融文本标注的成熟做法即 weak supervision + distant supervision（知识库/事件库作远程监督信号），临床与金融文本挖掘综述均将其列为降低标注成本的两条标准路径之一 |
| 代码现状 | R1 规则器本身是 P1 必做项（给 R2 产数据+兜底召回），叠加一个聚合层（多数投票/生成模型）即可，边际工作量小 |

**结论**：路线升级为 **R1 规则（=LFs）→ 弱监督聚合 → 用户只仲裁两类样本：①多 LF 冲突 ②聚合置信度处于 0.4-0.6 模糊带**。预计用户实际标注量从 500 降至 **100-150 条**，且仲裁样本恰好是信息熵最高的（主动学习思想）。500 条的标注预算上限不变，作为质量兜底。

---

## D3 事件库 Top5 类型 → **建议确认原 Top5，并补两条实证校准**

原建议（宏观利率 / 上所公告 / 安全事件 / ETF-监管 / 项目解锁）经外部证据验证**全部成立**，且每类找到量化锚点：

| 事件类型 | 外部实证锚点 | 本地数据支撑 |
|---|---|---|
| 宏观利率（FOMC/CPI） | 传统金融事件研究最成熟类别 | ✅ fred 470 条（2023 起）+ cftc 13 + econ_calendar |
| 上所公告 | 交易所 listing 效应是加密事件研究经典主题 | ⚠️ okx_announcement 本地 **0 条**，需随 P0/P2 回填 |
| 安全事件（hack） | NY Fed 实证：DeFi 黑客事件**日均跌 27%**，且 36% 跌幅发生在首次公开公告**之前** → 事件库必须记录"首公告时间"与"链上可见时间"双时间戳，否则 reaction 窗口系统性偏误 | 需从 newsflash 回溯 |
| ETF/监管 | arXiv 2602.07046：监管冲击 vs 基础设施冲击的市场处理路径显著不同，需作为独立类型 | gdelt 824 条可补充监管事件 |
| 项目解锁 | 实证：解锁量 >5% 流通盘时下跌统计显著，每 1% 解锁≈0.3% 前跌+0.3% 后跌 → **解锁比例必须入 schema**（unlock_pct_supply 字段），不能只记"有解锁" | 需接 unlock calendar 数据源（新采集器或人工种子清单） |

**结论**：Top5 确认，**加两条硬要求**：①事件 schema 增加 `ts_onchain_visible`（最早公开可见时间）与 `unlock_pct_supply`（解锁类专用）；②本地 okx_announcement 为 0 条，上所公告类事件回填依赖 P0 正文爬取 + API 历史翻页（odaily 翻页参数已实测可用）。

---

## D4 存量回填 → **建议维持"深度板块优先"，但据实测数据修正范围**

| 代码现状（实测 [data_center.db](../../../../18-数据获取中心/data_center.db)，33259 行） | 含义 |
|---|---|
| `odaily_post` 本地 **0 条**（63750 为 API 端总量，非本地存量） | 深度文章回填 = 纯 API 工程，分批翻页即可，无量纲风险 |
| `odaily_newsflash` 仅 3048 条、跨度 **2026-08-29→10-29（仅 2 个月）** | 事件库地基不能依赖快讯本地存量，**API 历史翻页回填必须列入 P2**（翻页已实测） |
| 全库最新数据停在 **2026-10-29** | 采集链路疑似停更 ~10 天，P0 启动前需先确认 scheduler 状态 |
| `binance_funding_rate` 仅 92 条（10-06→10-13） | 市场状态向量的 funding/OI 维度**历史覆盖不足**，P2 覆盖率盘点降级方案（用 regime/波动率先行）确认必要 |

**结论**：D4=(b) 深度板块优先不变；补充：①newsflash 历史翻页回填与深度正文回填**并行**（服务事件库而非命题库）；②P0 增加"采集链路健康检查"前置步骤；③funding 维度按降级方案执行。

---

## D5 E5 对接时机 → **建议 (a) 达 candidate 即注入，加三条护栏**

| 维度 | 证据 |
|---|---|
| 代码现状 | E5 当前判读（[e5_strong_primitives.py](../../experiments/e5_cbr_holdout/e5_strong_primitives.py#L43-L45)）：原语为 6 维状态（R_up/R_down/R_smooth/R_flow/R_reflexivity/quality_score）+ is_short，kNN 上限 53.6%。**注入接口 = 在特征向量上新增维度**，单个模式即一个二值/分位维度，技术上 1 个模式就能重跑 |
| 统计实践 | 早注入的风险是"模式库自身的选择偏差污染 E5 结论"。三层防线已在模式侧把关（candidate 已要求 n≥8 + Holm 通过），E5 侧只需保持**同一 fold/holdout 协议**保证与 53.6% 基线可比 |
| 工程实践 | E5 重测全 shadow、单次成本为分钟级脚本运行，失败成本≈0；"攒够 10 个"没有统计上的必要性，反而延迟信号获取 |

**三条护栏**：①只注入 candidate 及以上状态的模式，且 `trials_count` 写入证据字段；②E5 重测复用既有 `cbr_holdout.py` 管线同 fold 同 seed，报告相对 kNN 53.6% 的 delta 与置换检验 p 值；③任一注入后 E5 指标恶化即回滚该原语并降级对应模式（falsified），单向门。

**关联发现（P3 预警）**：全仓 Grep 确认 Holm/PBO/CSCV/SPA/DSR **无任何既有代码实现**，48 域只有 ablation_gate.py（过拟合+稳定性双判据）。三层防线需在 P3 新建统计模块——这是 P3 的真实工作量主体，建议提前认知。

---

## 一页结论

| # | 建议 | 相对初版变化 |
|---|---|---|
| D1 | **FinBERT2 主线 + 仓内中文 FinBERT 兜底 + RoBERTa-wwm-ext 对照** | 明确具体模型，且有仓内零成本兜底 |
| D2 | **弱监督聚合（Snorkel 模式），用户只仲裁 ~100-150 条分歧/模糊样本** | 用户工作量再降 2/3 |
| D3 | Top5 确认；**schema 加双时间戳 + unlock_pct_supply** | 两条实证硬要求 |
| D4 | (b) 不变；**newsflash 历史回填并行 + P0 前置采集链健康检查 + funding 降级** | 依实测数据修正范围 |
| D5 | **(a) 即达即注入 + 三条护栏**；P3 需新建三层防线统计模块 | 加护栏与工作量预警 |

## Sources

- [FinBERT2: A Specialized Bidirectional Encoder for Chinese Financial NLP (arXiv 2506.06335)](https://arxiv.org/html/2506.06335v1)
- [BBT-Fin: Chinese Financial Pre-trained Model, Corpus and Benchmark (arXiv 2302.09432)](https://arxiv.org/pdf/2302.09432.pdf)
- [Snorkel: Rapid Training Data Creation with Weak Supervision](https://pmc.ncbi.nlm.nih.gov/articles/PMC5951191/) / [Snorkel Get Started](https://snorkelproject.org/get-started/)
- [Modern Clinical Text Mining: weak/distant supervision review](https://www.annualreviews.org/docserver/fulltext/biodatasci/4/1/annurev-biodatasci-030421-030931.pdf)
- [The Price of Processing: Information Frictions and Market Efficiency in DeFi (NY Fed SR1153)](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr1153.pdf?sc_lang=en)
- [Same Returns, Different Risks: Infrastructure vs Regulatory Shocks (arXiv 2602.07046)](https://arxiv.org/pdf/2602.07046v2)
- [Token Unlock Calendar: Trading the Supply Shock Events](https://coinxsight.com/blog/on-chain/token-unlock-trading-strategy)
- [How To Check Token Unlock Schedule and Predict Price Impact](https://altcoininvestor.com/how-to-check-token-unlock-schedule/)
- [Why Large Token Unlocks Can Shake Altcoin Markets (E8 Markets)](https://blog.e8markets.com/article/why-large-token-unlocks-can-shake-altcoin-markets-even-as-bitcoin-holds-firm)
