---
name: dream-research-workflow
description: "Orchestrates 5-step research: need analysis → multi-source research (finance+github+modular+code) → cross-validation → report → hermes reflection. Invoke for deep research, market research, or tech research."
version: 1.0.0
created: 2026-09-21
updated: 2026-09-21
license: Internal
status: active
category: orchestration
triggers: [深度调研, 市场调研, 技术调研, 多源研究]
depends_on: [dream-contradiction-theory, dream-strategy-research, tavily, deep-research-pro, baidu-scholar-search-skill, bsk]
provides: [research-orchestration]
cognitive_links: [VM-1790001702811-24bffe86]
---

# Dream Research Workflow — 深度调研工作流 SKILL

> 把"命题+约束 → 4 维多源调研 → 5 维交叉验证 → 报告合成 → hermes 反思"的 5 步深度调研流程固化为可复用编排，元 SKILL 为 `dream-qwen-eval-collab`，结尾执行 hermes 反思决定是否再衍生新 SKILL。

> **双位置存储**：本 SKILL 同时存在于：
> - `.trae/skills/dream-research-workflow/SKILL.md`（TRAE 调用入口）
> - `1-ARCHITECTURE/skills/dream-research-workflow/SKILL.md`（项目级索引发现，本文件）

---

## 一、何时调用（触发条件）

满足以下任一条件即应调用本 SKILL：

1. **深度调研**：用户需要对一个命题做系统性、多源、可落地的深度调研
   - 触发词：「深度调研」「市场调研」「技术调研」「多源研究」
2. **4 维调研**：调研需覆盖传统金融/行业实践 + github 代码实现 + 模块化模式适配 + 当前仓库实际代码需求
3. **方案前置**：在制定 spec/落地计划前，需要先沉淀一份可被 `dream-qwen-eval-collab` 评估的调研底稿
4. **hermes 反思**：调研结束后，用户希望反思是否形成/衍生新 SKILL
   - 触发词：「形成 SKILL」「反思」「hermes」「可复用经验」

**与 `dream-qwen-eval-collab` 的边界**：本 SKILL 不调用千问，产出是"本地多源调研报告"；若需要把报告送千问二轮评估，转 `dream-qwen-eval-collab` 步骤 2。

---

## 二、5 步标准流程

### 步骤 1：需求分析（命题 + 约束 + 4 维调研域）

**输入**：用户原始调研需求文本

**处理**：
1. 复用 `dream-contradiction-theory`（A0 矛盾分析）拆解命题：核心命题、主要矛盾、次要矛盾
2. 提取约束条件（时间窗/数据范围/工程上下文/验收标准）
3. 识别 4 维调研域命中情况，标注必选/可选
4. 识别工程约束（参考 `project_memory.md` 硬约束：HC-1a/HC-9/FAIL-OPEN/零回归/模块化开关）

**输出**：调研任务包（YAML）

```yaml
命题: <一句话陈述，含主语+谓语+宾语>
主要矛盾: <调研要解决的核心张力>
约束:
  - 时间窗: <范围>
  - 数据范围: <范围>
  - 工程上下文: <DreamOs/Harness 相关硬约束>
调研域:
  传统金融: 必选          # 经典理论/行业实践/论文
  github 代码: 必选       # 现有成熟实现/参考仓库
  模块化模式: 必选        # 长期适配 DreamOs/Deepseek Harness
  实际代码需求: 必选      # 当前仓库代码状态/依赖/历史
验收标准: <可量化的调研完成判据>
```

### 步骤 2：多源调研（4 维并行）

**输入**：调研任务包

**处理**：按 4 维分别调用对应工具，**并行执行**（独立工具调用可在同一批次发出）：

| 调研域 | 工具 | 调用要点 |
|--------|------|---------|
| 传统金融 | `baidu-scholar-search-skill` + `tavily` | 论文/经典理论/行业实践；tavily 补宏观背景 |
| github 代码 | `deep-research-pro` + `github` | 成熟开源实现、参考仓库、star/issue 活跃度 |
| 模块化模式 | `deep-research-pro` + 本仓库代码检索 | 长期适配 DreamOs/Deepseek Harness 的模块化开关模式 |
| 实际代码需求 | 本仓库 `Grep`/`Glob`/`Read` | 当前依赖、历史实现、相关模块状态 |

**调用模板示例**（传统金融维）：

```
baidu-scholar-search-skill(query="<命题关键词> 综述 OR survey", limit=10)
tavily(query="<命题> 行业实践 2025", max_results=8)
```

**调用模板示例**（github 代码维）：

```
deep-research-pro(query="<命题> github 成熟实现", depth="moderate")
github search repos "<关键词>" --sort stars --limit 10
```

**已知坑**（必须遵守）：

| 坑 | 现象 | 解决 |
|----|------|------|
| 多源结论冲突 | 传统金融说 A，github 实现说 B | 不掩盖冲突，记入步骤 3 交叉验证的"矛盾项" |
| 工具返回噪音 | 关键词过宽返回大量无关结果 | 用 `命题+约束` 缩窄，加 `site:`/`filetype:` 限定 |
| 模块化模式缺数据 | 没有现成适配案例 | 用本仓库 `dream-qwen-eval-collab` 沉淀的模式作类比 |
| 实际代码需求被忽略 | 只看外部不看本仓库 | 必须用 `Grep`/`Read` 看当前代码状态，不能凭记忆 |

**输出**：4 份分维调研笔记（markdown 片段，含来源链接/仓库 URL/文件路径）

### 步骤 3：交叉验证（5 维评分）

**输入**：4 份分维调研笔记 + 调研任务包

**评估维度**（5 维评分 0-10）：

| 维度 | 评分要点 |
|------|---------|
| 完整性 | 是否覆盖 4 维调研（传统金融 + github + 模块化 + 实际代码） |
| 可落地性 | 是否给出代码级实现路径（文件/模块/接口签名） |
| 工程适配性 | 是否适配 DreamOs/Deepseek Harness 工程约束（HC-1a/HC-9/FAIL-OPEN/零回归） |
| 风险识别 | 是否识别潜在风险（FAIL-OPEN/零回归/HC-1a/HC-9/数据漂移） |
| 创新性 | 是否引入模块化模式或新视角 |

**评分阈值与动作**：

| 综合评分 | 动作 |
|---------|------|
| ≥ 9.0 | 直接进入步骤 4 报告合成 |
| 7.0–8.9 | 标注改进项（P0/P1/P2），回到步骤 2 补调研薄弱维 |
| < 7.0 | 整个调研任务包重构（命题/约束可能需重定义），回到步骤 1 |

**矛盾项处理**：4 维之间结论冲突时，必须列出"矛盾项清单"，每项标注：冲突描述 / 各维立场 / 倾向结论 / 待验证手段。

**输出**：交叉验证报告（含 5 维评分 + 改进项 + 矛盾项清单）

### 步骤 4：调研报告合成

**输入**：4 份分维笔记 + 交叉验证报告

**报告模板**（必须含以下小节）：

```markdown
# <命题> — 深度调研报告

> 日期：YYYY-MM-DD
> 来源：4 维多源调研 + 交叉验证
> 5 维评分：<X.X> / 10
> 输入任务包：<路径或内联>

## 一、命题与约束
（命题一句话 + 主要矛盾 + 约束列表）

## 二、4 维调研结论
### 2.1 传统金融
（结论 + 来源：论文/行业实践，含链接）
### 2.2 github 代码
（结论 + 参考仓库 URL + 关键实现路径）
### 2.3 模块化模式
（结论 + 适配 DreamOs/Harness 的模式建议）
### 2.4 实际代码需求
（结论 + 本仓库文件路径 + 依赖/历史）

## 三、交叉验证
（5 维评分表 + 矛盾项清单 + 改进项 P0/P1/P2）

## 四、可落地结论
（代码级实现路径：文件/模块/接口签名）

## 五、风险与待验证
（FAIL-OPEN/零回归/HC 合规风险 + 待验证手段）
```

**输出**：调研报告路径（建议 `.trae/documents/<topic>-research-report.md`）

### 步骤 5：hermes 反思

**输入**：调研报告

**处理**：
1. 输出报告路径给用户审阅
2. 用户确认后，调用认知系统 `record` 记录经验
3. **hermes 反思**：评估本次流程是否值得形成/衍生新 SKILL（决策树见第五节）
4. 若报告需送千问二轮评估，转 `dream-qwen-eval-collab` 步骤 2

**record 模板**：

```
record(
  content="[深度调研] <命题一句话> | 4维覆盖 <命中/4> | 评分 <X.X> | 矛盾项 <N> | 报告: <路径>",
  quality_level="B",
  tags="深度调研,协作流程,多源研究,hermes反思,可复用,<域标签>"
)
```

---

## 三、输入输出契约

| 阶段 | 输入 | 输出 |
|------|------|------|
| 步骤 1 | 用户原始需求 | 调研任务包（YAML） |
| 步骤 2 | 调研任务包 | 4 份分维调研笔记（markdown） |
| 步骤 3 | 4 份笔记 + 任务包 | 交叉验证报告（5 维评分 + 矛盾项） |
| 步骤 4 | 4 份笔记 + 验证报告 | 调研报告（路径） |
| 步骤 5 | 调研报告 | 用户审阅 + 认知 record + 可选新 SKILL / 转千问评估 |

---

## 四、相关 SKILL 与文档

| 类型 | 名称 | 用途 |
|------|------|------|
| 元 | `dream-qwen-eval-collab` | 本 SKILL 的元编排，hermes 反思决策树来源 |
| 上游 | `dream-contradiction-theory` | A0 矛盾分析（命题拆解、主要矛盾识别） |
| 上游 | `dream-strategy-research` | A1 深度调研（交易域情报收集，可复用其多源模式） |
| 工具 | `tavily` | 联网搜索（宏观/行业背景） |
| 工具 | `deep-research-pro` | 多源深度研究（github + 模块化模式） |
| 工具 | `baidu-scholar-search-skill` | 学术论文搜索（传统金融理论） |
| 工具 | `github` | 仓库搜索（github 代码维） |
| 下游 | `dream-qwen-eval-collab` | 报告送千问二轮评估（步骤 5 可选转出） |
| 下游 | `dream-tdd-dev-workflow` | 报告落地为 TDD 开发流程 |
| 元 | `skill-creator` | hermes 反思后创建新 SKILL |
| 认知 | `recall`/`record`/`verify` | 认知闭环 |

---

## 五、hermes 反思决策树

> 引用元 SKILL `dream-qwen-eval-collab` 第五节决策树（来源记忆 `VM-1790001702811-24bffe86`，B 级硬约束）。

```
本次调研流程是否值得形成/衍生 SKILL？
├── 是（满足以下任一）：
│   ├── 流程被复用 ≥ 2 次
│   ├── 涉及多步编排（≥ 3 步）
│   ├── 涉及多工具并行调用（≥ 2 个外部工具）
│   └── 用户明确要求「形成 SKILL」
│   → 调用 skill-creator 创建新 SKILL
│   → record 经验，tags 含「SKILL,hermes反思」
│
└── 否（满足以下全部）：
    ├── 一次性调研
    ├── 单一数据源
    └── 无复用价值
    → 仅 record 经验
    → tags 不含「SKILL」
```

---

## 六、认知闭环（recall + record + verify）

**任务开始前**（硬约束，不可跳过）：

```
recall(context="深度调研 <命题关键词>", top_k=5, min_quality="C")
```

**任务完成后**：

```
record(content="<本次调研摘要> | 4维覆盖 <命中/4> | 评分 <X> | 报告: <路径>",
       quality_level="B",
       tags="深度调研,协作流程,多源研究,hermes反思,可复用,<域标签>")

# 如已验证某条已有记忆
verify(memory_id="VM-xxx", success=true)
```

**已沉淀的认知记忆**（可 recall 复用）：

| Memory ID | 等级 | 内容摘要 |
|-----------|------|---------|
| `VM-1790001702811-24bffe86` | B | hermes 反思决策树硬约束（4 延伸 SKILL 配套） |
| `VM-1790000355655-0124d10d` | B | 千问评估协作流程（含 4 维调研域定义） |
| 本 SKILL 创建后新增 | B | 深度调研落地经验，tags 含「SKILL,深度调研,hermes反思」 |

---

## 七、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-09-21 | 初始版本，5 步流程 + 4 维多源调研 + 5 维交叉验证 + hermes 反思决策树 |
