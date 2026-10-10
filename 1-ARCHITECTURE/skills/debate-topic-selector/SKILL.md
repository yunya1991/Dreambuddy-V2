---
name: debate-topic-selector
description: "辩论话题选题引擎：WebSearch热点+交易SKILL信号+用户审校。Invoke when 用户提到选题、话题选题、选题辩论、辩论话题、topic selection时自动调用。"
version: 1.0.0
created: 2026-10-10
updated: 2026-10-10
license: Internal
status: active
category: orchestration
triggers: [选题, 话题选题, 选题辩论, 辩论话题, topic selection, 热点辩论]
depends_on: [dream-research-workflow]
provides: [debate-topic-candidates]
---

## Autonomy Boundary

可自主执行：
- WebSearch 搜索热点话题
- 调用交易 SKILL 获取市场信号
- 整理候选话题清单

需用户确认：
- 最终选题确定
- 辩论方向（正方/反方立场分配）

禁止：
- 未经用户确认直接启动辩论

# 辩论话题选题 SKILL — Debate Topic Selector

> 把"热点搜索 → 信号整合 → 候选生成 → 用户审校 → 选题确认"的 5 步选题流程固化为可复用编排，为 32-对抗性辩论Bot 的交互式辩论模式（方案B）提供话题来源。

---

## 一、何时调用（触发条件）

满足以下任一条件即应调用本 SKILL：

1. **用户要求选题**：用户想要展开辩论但还没确定话题
   - 触发词：「选题」「话题选题」「选题辩论」「辩论话题」「热点辩论」
2. **辩论前置流程**：用户说"来一场辩论""展开辩论"但未给话题
3. **定期选题**：定期从热点中筛选有争议性的话题

**与 `dream-research-workflow` 的边界**：research-workflow 是通用调研；本 SKILL 聚焦"找到有对抗性、有传播价值的话题"，输出是候选清单而非调研报告。

---

## 二、5 步标准流程

### 步骤 1：热点搜索（WebSearch 多维度）

**输入**：用户可选指定领域（crypto/finance/tech/general）

**处理**：
1. WebSearch 搜索当前热点：
   - `crypto hot topics {date}` — 加密货币热点
   - `BTC ETH market debate {date}` — 市场争议话题
   - `AI technology controversy {date}` — 科技争议
2. 提取有**对抗性**的话题（正反方都有论据的）
3. 排除纯新闻（无争议性的事件不选）

**输出**：原始话题池（5-10 条）

### 步骤 2：交易信号整合（调用 SKILL 体系）

**处理**：
1. 检查交易系统是否有当前市场信号（多空分歧大的标的）
2. 调用 `dream-research-workflow` 获取市场情绪
3. 从交易 SKILL 输出中提取"多空分歧大""市场争议高"的话题
4. 如果交易系统无信号或用户不涉及交易，跳过此步

**输出**：交易信号增强话题池（补充 2-3 条）

### 步骤 3：候选生成（评分 + 排序）

**评分维度**（每项 1-5 分）：
- **争议性**：正反方都有强论据？（5=双方势均力敌）
- **传播性**：有金句潜力？话题标签好传播？
- **时效性**：当前热点？有新鲜度？
- **深度**：能展开多轮？不是一句话说完？
- **相关性**：与用户领域（交易/crypto）相关？

**处理**：
1. 对话题池每条评分
2. 取 Top 3-5 候选
3. 为每条标注：正方核心立场 / 反方核心立场 / 推荐轮次

**输出**：候选话题卡（YAML）

```yaml
candidates:
  - topic: "BTC 是数字黄金"
    scores: {争议性: 5, 传播性: 4, 时效性: 4, 深度: 5, 相关性: 5}
    total: 23
    bull_stance: "BTC 具备数字黄金属性，将取代传统价值存储"
    bear_stance: "BTC 波动过大，无法承担价值存储职能"
    recommended_rounds: 2
    key_data: "BTC 市值 $1.3T，黄金 $15T"
  - topic: "..."
    ...
```

### 步骤 4：用户审校（交互式确认）

**处理**：
1. 向用户展示候选清单（按总分排序）
2. 用户可以：
   - 选择某条候选
   - 修改某条候选的措辞/立场
   - 自己提一个新话题
   - 要求重新搜索（换一批）
3. 用户确认后进入步骤 5

**输出**：确认的话题（1 条）

### 步骤 5：选题确认 + 背景材料准备

**处理**：
1. 确认话题 + 正反方立场 + 轮次
2. 如果用户提供了背景文档，读取整理
3. 如果用户未提供，WebSearch 搜索背景材料：
   - 话题相关的最新数据/事件
   - 正方论据来源
   - 反方论据来源
4. 输出选题确认卡

**输出**：选题确认卡（YAML）

```yaml
confirmed:
  topic: "BTC 是数字黄金"
  bull_stance: "BTC 具备数字黄金属性"
  bear_stance: "BTC 无法承担价值存储职能"
  rounds: 2
  background: |
    BTC 市值 $1.3T vs 黄金 $15T
    2024 减半后供给减少
    机构采用：BlackRock IBIT...
  sources:
    - "https://..."
    - "https://..."
```

---

## 三、调用方式

```
用户: "选题辩论"
→ Trae 调用本 SKILL
→ 步骤1-3 自主执行
→ 步骤4 展示候选，等用户选择
→ 步骤5 确认后输出选题确认卡
→ 交给 InteractiveRunner 开始辩论
```

---

## 四、双位置存储

本 SKILL 同时存在于：
- `.trae/skills/debate-topic-selector/SKILL.md`（TRAE 调用入口）
- `1-ARCHITECTURE/skills/debate-topic-selector/SKILL.md`（项目级索引发现）
