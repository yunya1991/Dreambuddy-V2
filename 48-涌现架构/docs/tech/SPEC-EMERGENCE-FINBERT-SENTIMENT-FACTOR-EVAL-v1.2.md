# FinBERT 情绪因子评估 SPEC v1.2（架构对齐版：FinBERT 归位 9 域打分服务，39 为唯一语义层）

> **状态**: Draft → 待评审
> **日期**: 2026-11-12
> **修订自**: SPEC-EMERGENCE-FINBERT-SENTIMENT-FACTOR-EVAL-v1.1.md（本地深度文章版）
> **对齐母文档**: SPEC-EMERGENCE-FINANCIAL-ENV-v1.0.md（实际版本 v2.8，2026-11-12）
> **修订原因**: 母 SPEC v2.8 已确立四层涌现环境架构（E 金融事件 × S 金融语义情绪 × M 市场情绪 × P 市场形态），明确 39 为唯一语义层、FinBERT 归位为 9 域打分服务、因子须过四道关且 verdict 只能由 assert_gate() 产出。v1.1 的『FinBERT 独立因子管线』定位与母 SPEC 冲突，本版完成对齐。

---

## §0 执行摘要（三句话）

1. **归位**: FinBERT 不再作为独立因子管线，归位为 9 域打分服务——`9-基本面分析/engines/sentiment_engine.py` 双引擎（中文 yiyanghkust/finbert-tone-chinese，LABEL_0=Neutral / LABEL_1=Positive / LABEL_2=Negative；英文 ProsusAI/finbert）。G11 已修复中文引擎静默回退规则引擎问题，实测 +0.9992 / -0.9981 / 0.0。

2. **数据流**: 本地深度文章（中文 500 篇 + 英文 140 篇）打分产物降级为 S 层输入，经 39 语义层（唯一语义层）进入 E×S×M×P 四层对齐管线；v1.1 的文章级独立因子主检验（art_sent 等直接进五层评估）废止。

3. **评估**: 因子评估对齐母 SPEC 四道关（正交化 → 增量 IC → 状态分桶 → DSR/PBO），verdict 只能由 `48-涌现架构/registry/factor_gate.py` 的 `assert_gate()` 产出，trials.jsonl 写入（G9 待接入）。

---

## §1 与母 SPEC v2.8 的对齐动作（v1.1 → v1.2）

| # | 维度 | v1.1（本地深度文章版） | v2.8 母 SPEC | v1.2 对齐动作 |
|---|------|----------------------|--------------|---------------|
| 1 | FinBERT 定位 | 独立打分管线，直接产出文章级因子 | 归位 9 域打分服务 | 打分统一走 sentiment_engine，产物作为 S 层输入 |
| 2 | 语义层 | 39 域事件仅作 L5 三因子相关性对照 | 39 为唯一语义层（S 层 canonical） | 深度文章情绪分数经 39 语义层进入四层管线；复用 48 域 S 层适配器 `load_semantic_sentiment()` + `--semantic-events`（G15，实测 68 行） |
| 3 | 评估框架 | 五层评估（IC→分层→消融→状态依赖→衰减），自设淘汰线 | 四道关（正交化→增量 IC→状态分桶→DSR/PBO）+ assert_gate() 唯一 verdict 入口 | 评估框架替换为四道关；统计函数复用 45 评测系统（deflated_sharpe_ratio / pbo_cscv / purged_kfold / walk_forward），Harvey-Liu-Zhu t>3.0 门槛 |
| 4 | 资产范围 | 未定义（隐含单资产） | U 层龙头宇宙（40 域 asset_classes.py 投影，G1 六锚 BTC/XAU/CL/US500/JP225/TLT；用户点名 XAU/XAG/CL/BZ/NG/XCU） | 因子评估限定龙头宇宙；价格唯一主源 OKX -USDT-SWAP（U-1），黄金双轨（U-2） |
| 5 | F&G 基准 | 达到 F&G 量级即算成功（附录 A 量化达标线） | P-1：F&G IC=-0.4826 (p=0.013) 不构成统计发现，仅 contrarian 方向性线索 | F&G 降级为方向先验，废止量化达标线 |
| 6 | 情绪反向 | 无条件反向预期（§2.3） | P-3：情绪反向必须条件化（情绪极值 × 拥挤/估值联合触发） | 反向检验加条件化交互项，不做无条件主效应检验 |
| 7 | 数据契约 | 自定义输出格式 | EventRecord + DimensionSignal 统一契约，EventLedger 为 canonical（G12） | 产物按统一契约输出 |

---

## §2 保留的本地实况（v1.1 有效部分，继续有效）

- 本地无快讯流（odaily_newsflash 为空），真实数据基础是深度文章（中文 500 篇 + 英文 140 篇，2026-06~11 覆盖）
- 双本地模型归一化口径：score ∈ [-1,+1]，sentiment ∈ {positive, neutral, negative}
- cross_lang_divergence（中英文分歧度）保留为 S 层候选信号（探索性维度，不设强预期，仅报告不进主线）
- 英文回填调度（crontab 每日 02:50，--per-source 20）继续积累样本
- P-4 纪律：任何打分路径必须显式确认 FinBERT 引擎真实加载，禁止静默回退规则引擎

---

## §3 修订后的执行计划

```
Step 1: [G1·P0] 39 事件 sentiment 字段接口——sentiment_engine 为 39 semantic_events
        提供事件级打分（母 SPEC 未修复项，本 SPEC 的核心增量）
Step 2: 深度文章打分产物按 DimensionSignal 契约写入 S 层（复用 G15 适配器）
Step 3: [G9·P0] 四道关评估接入：trials.jsonl 写入 + assert_gate() verdict
Step 4: [G4·P0] 龙头宇宙定义落地后，在 U 层做 E×S×M×P 联合验证
Step 5: 验收报告 + 本 SPEC 状态更新
```

---

## §4 依赖的母 SPEC 缺口项（未修复，P0）

- G1：39 与 FinBERT 无接口，39 事件无 sentiment 字段
- G4：无龙头宇宙定义（leader_universe.json）
- G9：统计函数未接入 48 因子评估，无 trials.jsonl 写入点

---

## §5 风险与 fallback

| 风险 | 概率 | 缓解 |
|------|------|------|
| G1/G4/G9 均未修复，四层管线无法端到端跑通 | 高 | Step 1-4 按缺口依赖排序推进；深度文章打分可先行积累（零阻塞） |
| 39 semantic_events 100% source=trader.log，零新闻语义事件 | 高 | 深度文章情绪分数是 S 层新闻语义信号的主要补充来源 |
| 月度时序仅 6 点无统计功效 | 高 | 沿用 v1.1 结论：文章级横截面为主，月度仅辅助状态维 |
