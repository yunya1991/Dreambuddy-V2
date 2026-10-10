---
name: dream-science-orchestrator
description: "科研引擎统一入口。根据任务类型路由到具体科研 SKILL，复用 dream-research-workflow 的 5 维交叉验证和 hermes 反思，输出可执行开发任务打通调研→开发衔接。触发词：科研编排、研究引擎、调研开发、科研任务"
version: 1.0.0
created: 2026-10-05
updated: 2026-10-05
license: Internal
status: shadow
category: orchestration
triggers: [科研编排, 研究引擎, 调研开发, 科研任务, 研究编排]
depends_on: [dream-research-workflow, dream-science-literature-review, dream-science-cross-disciplinary, dream-science-hypothesis-verification, dream-science-uncertainty-reasoning, dream-science-framework-research, dream-science-statistics-check, dream-science-peer-review, drawio, nature-figure]
provides: [research-orchestration, research-to-development]
---

# Dream Science Orchestrator — 科研引擎统一入口

> 科研引擎的总编排 SKILL，整合 9 个科研 SKILL 形成合力。
> 复用 `dream-research-workflow` 的 5 维交叉验证质量门控和 hermes 反思决策树。
> 打通调研→开发衔接，将科研结论转化为 TDD 可执行开发任务。

> **双位置存储**：本 SKILL 同时存在于：
> - `.trae/skills/dream-science-orchestrator/SKILL.md`（TRAE 调用入口）
> - `1-ARCHITECTURE/skills/research/dream-science-orchestrator/SKILL.md`（项目级索引副本）

---

## 一、何时调用（触发条件）

满足以下任一条件即应调用本 SKILL：

1. **科研任务编排**：用户需要进行系统性科研任务，但不确定调用哪个科研 SKILL
   - 触发词：「科研编排」「研究引擎」「科研任务」「研究编排」
2. **调研→开发衔接**：用户希望将调研结论转化为可执行开发任务
   - 触发词：「调研开发」「科研落地」「研究转开发」
3. **科研质量门控**：需要对科研产出进行 5 维交叉验证评分
4. **hermes 反思**：科研任务结束后，评估是否形成/衍生新 SKILL

---

## 二、任务分类路由

根据用户需求，将科研任务分为 5 类，路由到对应科研 SKILL：

| 任务类型 | 路由目标 SKILL | 触发特征 |
|---------|---------------|---------|
| **调研类** | `dream-science-literature-review` + `dream-science-cross-disciplinary` | 文献综述、领域调研、跨学科研究 |
| **假设类** | `dream-science-hypothesis-verification` + `dream-science-uncertainty-reasoning` | 假设验证、不确定性分析、敏感性测试 |
| **框架类** | `dream-science-framework-research` | 架构设计、框架对比、演进路径 |
| **评审类** | `dream-science-statistics-check` + `dream-science-peer-review` | 统计审查、同行评审、策略验证 |
| **可视化类** | `drawio` + `nature-figure` | 架构图、回测图表、科研绘图 |

### 路由决策流程

```
用户科研需求
    ↓
Step 1: 需求分类（匹配上述 5 类之一）
    ↓
Step 2: 调用对应科研 SKILL
    ↓
Step 3: 科研产出 → 5 维交叉验证门控
    ↓
Step 4: 评分 ≥ 7.0 → 生成可执行开发任务
    ↓
Step 5: hermes 反思（是否衍生新 SKILL）
    ↓
Step 6: 认知 record
```

---

## 三、5 维交叉验证质量门控

> **复用来源**: `dream-research-workflow` 步骤 3（5 维评分交叉验证）

对科研产出进行 5 维评分（0-10），决定是否进入开发阶段：

| 维度 | 评分要点 |
|------|---------|
| 完整性 | 是否覆盖调研全维度（文献+跨学科+假设+验证） |
| 可落地性 | 是否给出代码级实现路径（文件/模块/接口签名） |
| 工程适配性 | 是否适配工程约束（FAIL-OPEN/零回归/模块化） |
| 风险识别 | 是否识别潜在风险（过拟合/数据漂移/统计偏差） |
| 创新性 | 是否引入新视角或跨学科方法 |

### 评分阈值与动作

| 综合评分 | 动作 |
|---------|------|
| ≥ 9.0 | 直接生成开发任务（P0 优先级） |
| 7.0–8.9 | 标注改进项，生成开发任务（P1 优先级） |
| < 7.0 | 退回补充调研，不生成开发任务 |

---

## 四、调研→开发衔接机制

### 核心目标
将科研结论转化为 TDD 可执行开发任务，打通调研→开发断点。

### development_tasks 输出规范

科研产出必须包含 `development_tasks` 模块，格式如下：

```yaml
development_tasks:
  - id: TDD-001
    hypothesis: "<科研假设一句话陈述>"
    test_assertion: "<TDD RED 测试断言，必须断言真实业务逻辑>"
    priority: P0|P1|P2
    depends_on: []
    target_skill: dream-tdd-dev-workflow
    evidence: "<支撑该假设的科研证据>"
```

### 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| id | ✅ | 任务唯一 ID（TDD-XXX 格式） |
| hypothesis | ✅ | 科研假设一句话陈述 |
| test_assertion | ✅ | TDD RED 测试断言，必须断言真实业务逻辑（非 Mock） |
| priority | ✅ | P0（核心）/ P1（重要）/ P2（次要） |
| depends_on | ✅ | 依赖的其他任务 ID |
| target_skill | ✅ | 执行开发的目标 SKILL（默认 dream-tdd-dev-workflow） |
| evidence | ✅ | 支撑假设的科研证据来源 |

### test_assertion 规范

**必须**：
- 断言真实业务逻辑（如"回测收益率 > 基准"）
- 可被测试框架验证（pytest/assert）
- 与 hypothesis 直接对应

**禁止**：
- 仅断言 Mock 行为
- 断言实现细节（如"调用了某函数"）
- 无法验证的模糊断言

### 示例

```yaml
development_tasks:
  - id: TDD-001
    hypothesis: "RSI 超卖反弹策略在震荡市中收益率优于趋势跟踪"
    test_assertion: "assert backtest_rsi_reversal(oscillation_data)['return'] > backtest_trend_following(oscillation_data)['return']"
    priority: P0
    depends_on: []
    target_skill: dream-tdd-dev-workflow
    evidence: "dream-science-literature-review 报告 §3.2，震荡市 RSI 策略胜率 62%"
```

---

## 五、hermes 反思决策树

> **复用来源**: `dream-research-workflow` 步骤 5（hermes 反思决策树）

科研任务结束后，评估是否值得形成/衍生新 SKILL：

```
本次科研流程是否值得形成/衍生 SKILL？
├── 是（满足以下任一）：
│   ├── 流程被复用 ≥ 2 次
│   ├── 涉及多步编排（≥ 3 步）
│   ├── 涉及多工具并行调用（≥ 2 个外部工具）
│   └── 用户明确要求「形成 SKILL」
│   → 调用 skill-creator 创建新 SKILL
│   → record 经验，tags 含「SKILL,hermes反思」
│
└── 否（满足以下全部）：
    ├── 一次性科研任务
    ├── 单一数据源
    └── 无复用价值
    → 仅 record 经验
    → tags 不含「SKILL」
```

---

## 六、输入输出契约

| 阶段 | 输入 | 输出 |
|------|------|------|
| 需求分类 | 用户科研需求 | 任务类型 + 路由目标 |
| 科研执行 | 路由目标 | 科研产出报告 |
| 质量门控 | 科研产出 | 5 维评分 + 改进项 |
| 开发衔接 | 评分 ≥ 7.0 的产出 | development_tasks（TDD 任务清单） |
| hermes 反思 | 科研流程 | 是否衍生新 SKILL 的决策 |
| 认知闭环 | 全部产出 | recall + record + verify |

---

## 七、复用能力清单

| 复用来源 SKILL | 复用能力 | 用途 |
|---------------|---------|------|
| `dream-research-workflow` | 5 维交叉验证评分 | 科研产出质量门控 |
| `dream-research-workflow` | hermes 反思决策树 | 新 SKILL 衍生决策 |
| `dream-research-workflow` | 调研报告模板 | 标准化科研产出格式 |
| `dream-strategy-research` | 信号充分性评估 | 假设验证的证据评级 |
| `dream-strategy-research` | A0 矛盾分析（C1-C7） | 假设验证的矛盾检测 |
| `asset-research` | 美林时钟周期判定 | 跨学科宏观周期映射 |

---

## 八、认知闭环（recall + record + verify）

**任务开始前**（硬约束，不可跳过）：

```
recall(context="科研编排 <任务关键词>", top_k=5, min_quality="C")
```

**任务完成后**：

```
record(content="[科研编排] <任务类型> | 5维评分 <X.X> | 开发任务 <N>个 | 衍生SKILL: <是/否>",
       quality_level="B",
       tags="科研SKILL,科研编排,研究引擎,调研开发,认知闭环")

# 如已验证某条已有记忆
verify(memory_id="VM-xxx", success=true)
```

---

## 九、相关 SKILL

| 类型 | 名称 | 用途 |
|------|------|------|
| 编排 | `dream-research-workflow` | 4 维多源调研 + 5 维交叉验证（能力来源） |
| 调研 | `dream-science-literature-review` | 文献综述 |
| 调研 | `dream-science-cross-disciplinary` | 跨学科研究 |
| 假设 | `dream-science-hypothesis-verification` | 假设验证 |
| 假设 | `dream-science-uncertainty-reasoning` | 不确定性推理 |
| 框架 | `dream-science-framework-research` | 框架研究 |
| 评审 | `dream-science-statistics-check` | 统计审查 |
| 评审 | `dream-science-peer-review` | 同行评审 |
| 可视化 | `drawio` | 架构图 |
| 可视化 | `nature-figure` | 科研图表 |
| 开发 | `dream-tdd-dev-workflow` | TDD 开发（development_tasks 目标） |
| 元 | `skill-creator` | hermes 反思后创建新 SKILL |
| 认知 | `recall`/`record`/`verify` | 认知闭环 |

---

## 十、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-10-05 | 初始版本：任务分类路由 + 5 维门控 + 调研→开发衔接 + hermes 反思 |
