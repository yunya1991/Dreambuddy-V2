# SKILL: debate-adjudication-methodology（裁判评审方法论）

> **版本**: 1.0.0 | **来源**: InspireScore (arXiv 2506.18102) + WSDC Judge Academy + debate.club AI Evaluation
> **用途**: 指导 Layer 1 裁判评审（`adjudicator.py`），对辩论进行 6 维评分 + RFD 裁决理由生成
> **SPEC**: debate-adjudication-training-spec.md v1.2-rc1 §3

## 1. 何时调用

满足以下任一条件：
1. 需要独立裁判对一场辩论做结构化评分（非胜负一句话）
2. 需要为训练层（Layer 2/3）产出可量化的 AdjudicationResult
3. 用户提到 "裁判评审"、"6维评分"、"RFD"、"裁决理由"、"InspireScore"
4. 辩论结束、Verdict 生成**之后**（面向训练，非面向用户展示）

## 2. 6 维评分体系

每维 1-5 分，总分 6-30。INSPIRE 体系将评分拆为**主观**（LLM 判定）与**客观**（可核查）两类：

| 维度 | 类型 | 评分标准（5 分 = 优秀，1 分 = 严重不足） | 来源 |
|------|------|------------------------------------------|------|
| **论证清晰度** clarity | 主观 | 论点是否结构化（claim→warrant→impact），有无逻辑断层 | InspireScore |
| **论点编排** arrangement | 主观 | 论点排列策略、整体逻辑连贯性、首尾呼应 | InspireScore |
| **话题切题** topic_relevance | 主观 | 是否与辩题直接相关，有无跑题/偷换辩题 | InspireScore |
| **情感诉求** emotional_appeal | 主观 | 金句感染力、叙事说服力、价值共鸣 | InspireScore |
| **事实真实性** fact_authenticity | 客观 | 数据/引用/专家是否真实准确 | InspireScore + Web-RAG |
| **逻辑有效性** logical_validity | 客观 | 因果链是否成立，有无逻辑谬误 | InspireScore + 一阶逻辑 |

**附加指标**（不纳入总分，供训练层分析）：
- **反驳力度** rebuttal_strength：对对方论点的反驳效果（WSDC Strategy 维度）
- **证据深度** evidence_depth：证据层级（数据 → 研究 → 专家，越高越强）

## 3. 评分流程

```
1. 输入: transcript (Turn 列表) + verdict (裁判裁决)
2. 逐 Turn 评分: 正方每个 Turn → 6 维评分; 反方每个 Turn → 6 维评分
3. 全场评分: 正方总分 = mean(正方 Turn 评分); 反方总分 = mean(反方 Turn 评分)
4. RFD 生成 (Reason for Decision):
   - 胜方优势论据（哪些维度领先）
   - 败方主要弱点（哪些维度不足）
   - 关键交锋点 key_clash_points（全场势头转折）
5. 输出: AdjudicationResult (可 to_dict() 序列化)
```

**胜负判定**：总分高者胜；相等 → draw。

## 4. 客观维度实现（分版本）

| 维度 | v1 实现 | v2 实现 |
|------|---------|---------|
| 事实真实性 | LLM + 知识库直接核查；三值分类 SUPPORTED / REFUTED / NEI（证据不足） | Uncertainty-gated Web-RAG（仅对不确定事实触发 web search） |
| 逻辑有效性 | LLM 逻辑谬误检测（滑坡/稻草人/诉诸权威/以偏概全） | NL2FOL → SMT Solver 形式化验证 |

**v1 取舍**：确定性优先——用"无法验证"（NEI）显式标注不确定，而非编造核查结论。

## 5. 自评偏差校准（M1 关键约束）

> **风险**：辩论生成与评分同源 → 存在自我确认偏差（倾向给自己生成的论点更高分）。

| 版本 | 方案 | 说明 |
|------|------|------|
| **v1** | 透明声明 + 结构化 Prompt | 评分 Prompt 使用"你现在是独立裁判，**不是辩手**"框架，并**显式声明偏差风险**（比隐藏更安全） |
| **v1.5** | 人工评分基线校准 | 每 10 场抽 1 场人工评分，计算 MAE；MAE > 2 分触发 Prompt 调整 |
| **v2** | 双 LLM 交叉评分 | 引入第二个 LLM 评分取均值；或用更强模型做裁判（裁判 > 辩手） |

**v1 Prompt 铁律**：必须以"独立裁判不是辩手"开场，必须要求"保持中立、不偏向任何一方"。

## 6. 与 Verdict / QualityScore 的共存关系

| 现有组件 | 关系 | 说明 |
|---------|------|------|
| Verdict | **保留不变** | 辩论过程中生成的实时裁决，面向 Telegram 群展示 |
| QualityScore | **被 AdjudicationResult 替代** | 从 7.5/10 粗粒度 → 6 维细粒度；旧接口标记 deprecated |
| Judge (run_deep) | **保留不变** | run_deep 的 Judge 生成面向用户的 Verdict；Layer 1 在 Verdict **之后**执行（面向训练） |

**执行顺序**：辩论结束 → Judge 生成 Verdict → Layer 1 评审 → Layer 2 反思 → Layer 3 训练。
**延迟预算**：Layer 1-3 总延迟 < 10s，超时 FAIL-OPEN 跳过（不阻塞用户看到 Verdict）。

## 7. 与代码协同

| 组件 | 位置 | 职责 |
|------|------|------|
| `AdjudicationResult` | `python-server/adjudicator.py` | 数据契约（6 维 + winner + rfd + key_clash_points） |
| `Adjudicator.adjudicate()` | 同上 | 主入口：transcript + verdict → AdjudicationResult |
| `ADJUDICATION_PROMPT` | 同上 | 独立裁判框架 Prompt |
| `run_post_debate_pipeline()` | `python-server/c_drive_agent.py` | Layer1→2→3 链式调用（FAIL-OPEN） |

## 8. FAIL-OPEN 行为

- 无 LLM / JSON 解析失败 / 异常 → 返回**降级结果**：各维 3 分（中性），winner 取 Verdict 的 winner
- 降级结果 `rfd` 前缀标注 `[降级]`，便于观测
- **不抛异常**——评审失败绝不阻塞辩论主流程

## 9. 认知闭环

```
前置 recall: recall(context="<话题> 裁判评审", top_k=5, min_quality="C")
后置 record: record(content="[裁判评审] <话题> | winner=<X> | 正方<N> vs 反方<M> | 关键交锋<k>",
                   quality_level="B", tags="debate,adjudication,<topic_type>")
```

## 10. 约束

- 评审必须客观，不得预设结论
- 客观维度无法验证时必须标注 NEI，不得编造核查结论
- 自评偏差必须**显式声明**，不得静默处理
- 输出必须可序列化（HC4 可观测）
- 坚持 human-in-the-loop：AI 做评审，最终训练策略由数据驱动