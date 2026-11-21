---
name: "debate-reflection-methodology"
description: "赛后反思5步循环方法论。Invoke when 辩论赛后反思、策略提取、gap分析、改进建议、Practice Loop。"
version: "1.0.0"
status: "active"
category: "cognition"
domain: "1-ARCHITECTURE"
triggers: ["赛后反思", "策略提取", "gap分析", "改进建议", "Practice Loop", "反思循环"]
---

# SKILL: debate-reflection-methodology（赛后反思方法论）

> **版本**: 1.0.0 | **来源**: SuperDebate Guide Ch.17 (Practice Loop) + DebateFlow (Post-Round Self-Evaluation) + Debate Ladder (Deliberate Practice)
> **用途**: 指导 Layer 2 赛后反思（`reflector.py`），从辩论结果中提取"什么策略有效/什么无效"并产出改进建议
> **SPEC**: debate-adjudication-training-spec.md v1.2-rc1 §4

## 1. 何时调用

满足以下任一条件：
1. 需要从一场辩论中提取可复用的策略经验（而非只存"经验发生"）
2. 需要识别证据缺口、遗漏论点、未使用战术
3. 用户提到 "赛后反思"、"复盘"、"策略提取"、"缺口识别"、"Practice Loop"
4. Layer 1 评审完成**之后**（反思依赖 AdjudicationResult）

> **核心洞察**："没有反思循环的练习只积累时间不积累技能。"

## 2. 策略提取（§4.0 前置依赖）

> **问题**：反思需要策略标签，但 `Argument` 只有 thesis/arguments/quote/confidence，无策略字段。
> **解决**：两层提取，Layer B 为兜底。

| 层 | 名称 | 机制 |
|----|------|------|
| **Layer A** | 生成时标签（推荐） | Persona 生成论点时在输出 JSON 增加 `strategy` 字段 |
| **Layer B** | 回溯标签（兜底） | LLM 从已有论点文本识别策略（`STRATEGY_EXTRACT_PROMPT`） |

**策略标签分类法（14 种）**：

| 通用/正方策略 | 反方策略 |
|---------------|---------|
| definition-lock（定义锁定） | definition-attack（定义攻击） |
| preemptive-refutation（预防性反驳） | value-flip（价值翻转） |
| evidence-heavy（证据密集） | counter-example（反例构造） |
| stop-counterplan（反方案应对） | counterplan（替代方案） |
| burden-of-proof（举证责任） | burden-delay（拖延举证） |
| — | disadvantage（劣势论证） |
| — | kritik（批判底层假设） |

**存储**：`Turn.metadata.strategies` + CBR 案例 `strategies_used` + `ReflectionReport.strategy_analysis`。

## 3. 反思五步循环

```
Step 1: 复盘 (Review)
  - 逐轮回放：每个 Turn 的评分变化
  - 关键转折点：哪一轮发生势头翻转 (key_pivot)
  - 裁判视角：RFD 指出的核心分歧

Step 2: 分析 (Analyze)
  - 策略效果：哪些战术（Counterplan/DA/Kritik/定义锁定）被用？效果如何（1-5）？
  - Persona 表现：哪些人格特质贡献了高分维度？
  - 证据分析：哪些数据引用被验证/证伪？

Step 3: 缺口识别 (Gap Identification)
  - evidence_gaps：哪些论点缺乏证据支撑？
  - dropped_args：是否 dropped an argument（对方提出但未回应）？
  - unused_tactics：有哪些可用但未使用的战术？

Step 4: 改进建议 (Refinement)
  - 针对每个缺口给出具体改进方向 (recommendations)
  - 生成"下次辩论推荐策略"标签
  - 更新 Persona 的 traits/expertise 建议 (persona_suggestions)

Step 5: 存储 (Store)
  - 反思报告写入认知系统 (record, quality ≥ B)
  - 策略标签用于训练层权重更新
  - 案例入 CBR 库供下次检索
```

## 4. 反思报告结构

```python
@dataclass
class ReflectionReport:
    topic: str
    review: dict              # Step 1 复盘
    strategy_analysis: dict   # Step 2 策略效果
    persona_analysis: dict    # Step 2 Persona 表现
    evidence_analysis: dict   # Step 2 证据分析
    gaps: dict                # Step 3 缺口
    recommendations: list[str]  # Step 4 改进建议
    strategy_tags: list[str]    # 策略标签（训练层消费）
    persona_suggestions: dict   # Step 4 Persona 建议
    memory_id: str | None       # Step 5 认知系统 memory_id
    timestamp: str
```

**gaps 固定三字段**：`evidence_gaps` / `dropped_args` / `unused_tactics`（缺失时补空列表，保证契约稳定）。

## 5. HC7 策略标签前置（硬约束）

- 反思**前**必须先执行策略提取（§2）
- **无策略标签时跳过策略分析**（`strategy_analysis = {}`），不得编造策略效果
- 理由：循环依赖——反思需要策略，策略应先行

## 6. 与训练层衔接（参数消费闭环）

| 反思产出 | 消费方 | 效果 |
|---------|--------|------|
| `strategy_tags` | `debate_trainer.BayesianStrategyWeights` | 策略→胜率先验更新 |
| `strategy_analysis`（effect ≥ 4） | CBR `effective_strategies` | 下次检索复用有效策略 |
| `gaps.evidence_gaps` | CBR `adaptation_hints` | 下次辩论提示"需要更多数据" |
| `memory_id` | `DebateTrainer` 的 `verify()` | 预测应验 → 贝叶斯置信度升级 |

## 7. 与代码协同

| 组件 | 位置 | 职责 |
|------|------|------|
| `ReflectionReport` | `python-server/reflector.py` | 数据契约（5 步产出） |
| `Reflector.reflect()` | 同上 | 主入口：transcript + AdjudicationResult → ReflectionReport |
| `Reflector.extract_strategies()` | 同上 | §4.0 策略提取（Layer B） |
| `STRATEGY_EXTRACT_PROMPT` | 同上 | 策略识别 Prompt |
| `run_post_debate_pipeline()` | `python-server/c_drive_agent.py` | Layer1→2→3 链式调用 |

## 8. FAIL-OPEN 行为

- 无 LLM / JSON 解析失败 / 异常 → 返回**降级报告**：`review.rfd_summary` 前缀 `[降级]`，其余字段为空结构
- 降级时 `strategy_tags` 仍保留已提取的策略（若有）
- **不抛异常**——反思失败绝不阻塞辩论主流程

## 9. 认知闭环

```
前置 recall: recall(context="<话题> 赛后反思 策略", top_k=5, min_quality="C")
后置 record: record(content="{type:reflection, topic, winner, strategy_tags, gaps, recommendations}",
                   quality_level="B", tags="debate,reflection,<topic_type>")
后续 verify: verify(memory_id, success=<预测是否应验>)
```

**record 内容必须是结构化 JSON**（非自由文本），确保后续 recall 与训练层可解析。

## 10. 约束

- 反思必须基于 AdjudicationResult 的**已有评分**，不得凭空编造
- 无策略标签时必须跳过策略分析（HC7）
- record quality ≥ B；降级结果不写入认知系统
- 输出必须可序列化（HC4 可观测）
- 反思是**后处理扩展**，不改动 v2 辩论引擎核心逻辑（HC3 向后兼容）