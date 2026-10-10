# debate-classic-methodology — Oxford 式经典辩论赛制

> SPEC v2.0-rc3 第四节。将 v1 的简单轮次循环升级为正式辩论赛制。

## 一、何时调用

满足以下任一条件：
1. 用户提到 "经典辩论"、"Oxford式辩论"、"正式辩论"、"辩论赛制"
2. 辩论需要结构化赛制（开场/质询/反驳/总结）
3. 辩论 Bot v2 启用 classic_methodology 配置时

## 二、Oxford 式辩论流程

```
阶段1: 开场陈述 (Opening)
  正方开场: 陈述核心论点 + 2-3 个论据
  反方开场: 陈述反对论点 + 2-3 个论据

阶段2: 交叉质询 (Cross-Examination)  [可选]
  反方质询正方: 针对正方论据提问 → 正方回答
  正方质询反方: 针对反方论据提问 → 反方回答

阶段3: 反驳 (Rebuttal)
  正方反驳: 针对反方开场的新论据
  反方反驳: 针对正方开场的新论据

阶段4: 总结 (Closing)
  正方总结: 重申核心论点 + 回应关键反驳
  反方总结: 重申核心论点 + 回应关键反驳
```

## 三、状态机映射

| 辩论阶段 | 状态 | 轮次 | content 类型 |
|----------|------|------|---------------|
| 开场陈述 | bull_open → bear_open | round 1 | Argument |
| 交叉质询 | bull_cross → bear_cross | round 2 (可选) | CrossExamination |
| 反驳 | bull_rebut → bear_rebut | round 3 | Argument |
| 总结 | bull_close → bear_close | round 4 | Argument |
| 裁判 | judging | - | Verdict |

## 四、交叉质询数据模型

```python
@dataclass
class CrossExamination:
    """交叉质询记录。"""
    questioner: str          # 提问方: 'bull' | 'bear'
    respondent: str          # 回答方: 'bull' | 'bear'
    questions: list[str]     # 提问列表（2-3 个）
    answers: list[str]       # 回答列表（与 questions 一一对应）
    raw: str                 # 原始 LLM 输出
```

JSON 输出契约：
```json
{
  "questions": ["数据来源是什么？", "..."],
  "answers": ["来源是 CoinGecko...", "..."]
}
```

## 五、配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| enabled | false | 是否启用 Oxford 式辩论（默认关闭，用简单轮次） |
| cross_examination | false | 是否启用交叉质询阶段 |
| rounds | 4 | 总轮次（开场+质询+反驳+总结=4，精简模式=2） |

精简模式（rounds=2）：跳过交叉质询和反驳，只做开场+总结。

## 六、与 Persona 系统协同

经典辩论赛制配合 Persona 系统：
- 正方 Persona 根据话题动态匹配（如 Crypto → 加密老兵）
- 反方 Persona 根据话题动态匹配（如 Crypto → 传统金融人）
- 裁判 Persona 固定为中立裁判

## 七、与 C-Drive 认知闭环协同

| 阶段 | 认知操作 |
|------|----------|
| 辩论前 | recall(topic) → 检索历史辩论记忆 → 注入 Persona prompt |
| 辩论后 | record(有效论据, quality="B") → 写入 4-MEMORY |
| 验证期 | verify(memory_id, success) → 预测是否应验 → 升级记忆 |

## 八、与营销素材提取协同

MarketingExtractor._extract_cross_exam_highlights() 从交叉质询中提取精彩 Q&A：
- 筛选"被问倒"的 Q&A（answer 短于 20 字 或 question 带犀利关键词）
- 格式化为 "🔥 反方质询正方：Q → A" 的短文案
