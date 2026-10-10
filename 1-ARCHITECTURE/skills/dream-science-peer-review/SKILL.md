---
name: dream-science-peer-review
description: 同行评审SKILL，Devil's Advocate让步阈值协议+7模式阻断清单，多视角评审策略逻辑
version: 1.0.0
created: 2026-10-05
updated: 2026-10-05
license: Internal
status: proposed
category: research
domain: 1-ARCHITECTURE
triggers:
  - 同行评审
  - peer review
  - Devil's Advocate
  - 策略评审
  - 审稿
  - 评审报告
depends_on: []
provides:
  - peer-review
  - strategy-audit
  - devils-advocate
cognitive_links:
  - VM-1791173248403-1c154994
  - VM-1791173704722-9afd838c
---

# dream-science-peer-review — 同行评审

> dreambuddy-v2 科研 SKILL 支柱工具集之一。借鉴 academic-research-skills 的 Devil's Advocate 让步阈值协议，多视角评审策略逻辑。

## 一、何时调用

满足以下任一条件：
1. 策略方案需要同行评审
2. 需要多视角审查策略逻辑
3. 需要 Devil's Advocate 反驳检验
4. A8 `dream-theory-practice-verify` 调用本 SKILL 做策略评审

## 二、多视角评审流程

### 评审角色
1. **Journal-Fit Reviewer**：评估策略是否适合当前市场/目标
2. **方法评审**：评估方法论的严谨性和正确性
3. **统计评审**：评估统计分析的合规性（调用 `dream-science-statistics-check`）
4. **Devil's Advocate**：主动寻找策略的致命缺陷

### 评审流程
1. **材料提交**：策略文档 + 回测报告 + 代码
2. **独立评审**：4 个角色独立评审，互不干扰
3. **评审报告**：每个角色输出独立报告
4. **综合决议**：汇总评审意见，给出 Major/Minor 分级
5. **修改反馈**：作者根据意见修改
6. **复审**：重新评审修改后的版本

## 三、Devil's Advocate 让步阈值协议

### 反驳评分
- **1 分**：无根据的质疑，忽略
- **2 分**：有轻微问题，不影响核心逻辑
- **3 分**：有一定道理，但不足以推翻策略
- **4 分**：有说服力的反驳，需要修改策略
- **5 分**：致命缺陷，策略必须重新设计

### 让步规则
- 反驳评分 **≥ 4**：作者必须让步，修改策略
- 反驳评分 **< 4**：作者可坚持原方案，但需提供更强论据
- 争议解决：评分 3 和 4 之间的争议，由 human-in-the-loop 决定

## 四、7 模式阻断清单

> 防止 AI 研究失败模式的检查清单。

| 模式 | 检查项 |
|------|--------|
| **1. 幻觉引用** | 所有引用是否可验证？是否存在编造的文献？ |
| **2. 数据造假** | 数据是否真实？是否有数据来源？ |
| **3. 方法捏造** | 方法是否有理论依据？是否可复现？ |
| **4. 框架锁定** | 是否只考虑了一种框架？是否有替代方案？ |
| **5. 结果幻觉** | 结果是否与数据一致？是否存在过拟合？ |
| **6. 逻辑跳跃** | 推理链是否完整？是否有未声明的假设？ |
| **7. 边界忽略** | 是否声明了结论边界？是否过度外推？ |

## 五、Major/Minor 意见分级

### Major（必须修改）
- 方法论有根本性缺陷
- 数据或结果不可靠
- 结论与证据不符
- 存在未声明的重大假设

### Minor（建议修改）
- 表述不够清晰
- 缺少某些细节
- 图表可以改进
- 引用格式不规范

## 六、评审报告模板

```
# 同行评审报告 — <策略名称>

## 评审摘要
- 整体评价: <接受/修改后接受/拒绝>
- Major 意见: <N> 条
- Minor 意见: <N> 条

## Journal-Fit Reviewer
<评审意见>

## 方法评审
<评审意见>

## 统计评审
<评审意见>

## Devil's Advocate
<反驳意见及评分>

## 综合意见
<Major/Minor 意见清单>

## 修改建议
<具体修改建议>
```

## 七、输出规范

1. **多视角评审报告**：4 个角色的独立评审
2. **Devil's Advocate 评分**：反驳评分 + 让步判定
3. **7 模式阻断清单**：通过/不通过
4. **Major/Minor 意见**：分级意见清单
5. **综合决议**：接受/修改后接受/拒绝

## 八、认知闭环

### 前置 recall
```
recall(context="<策略名称> 同行评审 Devil's Advocate", top_k=5, min_quality="C")
```

### 后置 record
```
record(content="[同行评审] <策略> | Devil's Advocate 评分 <X> | Major <N> | Minor <N> | 决议 <接受/修改/拒绝>",
       quality_level="B", tags="科研SKILL,同行评审,<策略>")
```

## 九、与现有系统协同

| 协同 SKILL | 协同方式 |
|-----------|---------|
| A8 `dream-theory-practice-verify` | 策略验证的同行评审 |
| `dream-science-statistics-check` | 统计评审调用 |
| `dream-science-hypothesis-verification` | 假设验证的评审 |
| `dream-science-framework-research` | 框架方案的评审 |

## 十、金融交易适配

### 适用场景
- 新策略上线前的多视角评审
- 策略改进方案的可行性评估
- 风险事件的事后复盘评审

### 局限性
- 评审质量依赖评审者的市场经验
- 交易策略的"对错"需市场验证，评审无法完全替代
- 评审可能存在群体思维（需 Devil's Advocate 制衡）

### 适配建议
- 评审必须包含实盘风险视角（最大回撤、流动性、滑点）
- Devil's Advocate 角色必须质疑核心假设
- 评审结论需标注置信度，不输出绝对判断

## 十一、约束

- 评审必须客观，不得预设结论
- Devil's Advocate 必须主动寻找缺陷，不得走过场
- 7 模式阻断清单必须逐项检查
- 坚持 human-in-the-loop：AI 做评审，人类做最终决策
