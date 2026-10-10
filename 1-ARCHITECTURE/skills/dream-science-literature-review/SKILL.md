---
name: dream-science-literature-review
description: 专业领域文献综述SKILL，PRISMA系统综述+Socratic引导，聚焦金融/量化/交易文献
version: 1.0.0
created: 2026-10-05
updated: 2026-10-05
license: Internal
status: shadow
category: research
domain: 1-ARCHITECTURE
triggers:
  - 文献综述
  - literature review
  - 金融文献
  - 量化交易调研
  - PRISMA
  - 研究空白
depends_on:
  - dream-research-workflow
provides:
  - literature-review
  - research-gap-identification
cognitive_links:
  - VM-1791173248403-1c154994
  - VM-1791173704722-9afd838c
---

# dream-science-literature-review — 专业领域文献综述

> dreambuddy-v2 科研 SKILL 支柱核心能力之一。借鉴 academic-research-skills 的 PRISMA 系统综述模式，聚焦金融/量化/交易领域文献。

## 一、何时调用

满足以下任一条件：
1. 策略选题前需要系统性文献调研
2. 需要了解某交易领域的研究现状和前沿
3. 需要识别研究空白（research gap）
4. 需要为策略假设提供文献支撑
5. A1 `dream-strategy-research` 调用本 SKILL 做专业领域调研

## 二、PRISMA 综述流程

### 阶段 1：识别（Identification）
- 明确研究问题（PICO 格式：Population/Intervention/Comparison/Outcome）
- 制定检索策略（关键词组合、同义词、布尔运算符）
- 检索数据库（见第三节文献源）

### 阶段 2：筛选（Screening）
- 去重
- 标题/摘要筛选（纳入/排除标准）
- 全文筛选

### 阶段 3：合格（Eligibility）
- 全文阅读
- 数据提取（作者、年份、方法、数据、结果、结论）
- 质量评估

### 阶段 4：纳入（Inclusion）
- 最终纳入文献列表
- 证据矩阵构建
- 研究空白识别

## 三、金融交易文献检索源

| 数据库 | 覆盖范围 | 访问方式 |
|--------|---------|---------|
| arXiv (q-fin) | 量化金融预印本 | 公开 |
| SSRN | 金融经济研究 | 公开/注册 |
| Google Scholar | 综合学术 | 公开 |
| Semantic Scholar | AI/ML+金融交叉 | 公开 API |
| IEEE Xplore | 金融工程/算法交易 | 机构 |
| ScienceDirect | 金融经济学 | 机构 |
| JSTOR | 经典金融文献 | 机构 |
| Wiley Online Library | 金融期刊 | 机构 |

### 检索策略模板
```
主题: <交易主题>
关键词组:
  组1 (核心概念): <关键词1> OR <关键词2> OR ...
  组2 (方法): <方法1> OR <方法2> OR ...
  组3 (市场): <市场1> OR <市场2> OR ...
组合: 组1 AND 组2 AND 组3
时间范围: <起始年>-至今
语言: 中文 + 英文
```

### 复用 dream-research-workflow 的 4 维多源调研

> **复用来源**: `dream-research-workflow` 步骤 2（4 维多源调研）

文献检索不仅限于学术数据库，还应覆盖 4 个维度：

| 调研维 | 工具 | 调用要点 |
|--------|------|---------|
| 传统金融 | baidu-scholar-search-skill + tavily | 论文/经典理论/行业实践 |
| github 代码 | deep-research-pro + github | 成熟开源实现、参考仓库 |
| 模块化模式 | deep-research-pro + 本仓库代码检索 | 适配工程的模块化开关模式 |
| 实际代码需求 | 本仓库 Grep/Glob/Read | 当前依赖、历史实现、相关模块状态 |

**已知坑**：多源结论冲突时不掩盖，记入交叉验证的"矛盾项"。

## 四、证据矩阵模板

| 文献 | 年份 | 方法 | 数据 | 市场 | 核心发现 | 局限性 | 与本研究关系 |
|------|------|------|------|------|---------|--------|------------|
| Author et al. | 2024 | LSTM | BTC 1h | 加密 | 准确率 65% | 未考虑滑点 | 方法可借鉴 |
| ... | ... | ... | ... | ... | ... | ... | ... |

## 五、研究空白识别方法

1. **时间空白**：近 2-3 年是否有新研究？旧方法是否未结合新数据/新模型？
2. **市场空白**：研究是否集中在某些市场（如美股），其他市场（如加密/新兴市场）是否缺乏？
3. **方法空白**：是否有新方法（如 Transformer、图神经网络）未应用到该领域？
4. **维度空白**：是否只研究了收益，未研究风险/交易成本/可执行性？
5. **交叉空白**：是否有其他领域方法未被引入？（调用 `dream-science-cross-disciplinary`）

## 六、Socratic 引导模式

每 5 轮对话执行一次健康检查：
1. 研究问题是否清晰？
2. 检索策略是否全面？
3. 是否有遗漏的重要文献？
4. 证据矩阵是否完整？
5. 研究空白是否有说服力？
6. 下一步行动是否明确？

## 七、输出规范

1. **研究问题**：PICO 格式
2. **检索策略**：关键词组合 + 数据库 + 时间范围
3. **纳入/排除标准**：明确列出
4. **文献流程图**：PRISMA 流程图（可调用 drawio 生成）
5. **证据矩阵**：结构化表格
6. **研究空白**：3-5 个空白点，每个含依据和潜在价值
7. **建议方向**：基于空白提出 2-3 个研究方向
8. **可执行开发任务**（development_tasks）：将研究空白转化为 TDD 任务

### development_tasks 输出规范

> 复用来源: `dream-science-orchestrator` §四（调研→开发衔接机制）

```yaml
development_tasks:
  - id: TDD-001
    hypothesis: "<基于研究空白的可验证假设>"
    test_assertion: "<TDD RED 测试断言，必须断言真实业务逻辑>"
    priority: P0|P1|P2
    depends_on: []
    target_skill: dream-tdd-dev-workflow
    evidence: "<支撑该假设的文献证据（DOI/URL）>"
```

**字段要求**: hypothesis 必须来自研究空白；test_assertion 必须可被 pytest 验证；evidence 必须可追溯到具体文献。

## 八、认知闭环

### 前置 recall（硬约束）
任务开始前调用 `recall` 检索相关历史调研经验：
```
recall(context="<研究主题> 文献调研 量化交易", top_k=5, min_quality="C")
```

### 后置 record
任务完成后将调研产出记录到认知系统：
```
record(content="[文献综述] <主题> | 纳入 <N> 篇 | 研究空白 <N> 个 | 建议方向 <N> 个",
       quality_level="B", tags="科研SKILL,前期调研,文献综述,<主题>")
```

## 九、与现有系统协同

| 协同 SKILL | 协同方式 |
|-----------|---------|
| A1 `dream-strategy-research` | 策略选题前调用本 SKILL 做文献调研 |
| `dream-science-cross-disciplinary` | 识别跨学科研究空白 |
| `dream-science-hypothesis-verification` | 文献综述产出作为假设验证的输入 |
| `drawio` | 生成 PRISMA 流程图 |

## 十、金融交易适配

### 适用场景
- 量化策略选题前的文献调研
- 交易因子有效性的学术证据收集
- 市场异常现象的理论解释

### 局限性
- 金融文献多基于历史数据，市场结构变化可能使结论失效
- 发表偏倚：显著结果更易发表，负面结果可能被遗漏
- 不同市场（A股/美股/加密）的结论不可直接迁移

### 适配建议
- 优先检索近 3 年文献（市场结构变化快）
- 跨市场验证：同一策略在不同市场的表现
- 关注可复现性：优先选择有公开代码的研究

## 十一、约束

- 所有引用必须可验证（提供 DOI 或 URL）
- 不编造文献（7 模式阻断清单）
- 研究空白必须有文献依据，不得凭空捏造
- 坚持 human-in-the-loop：AI 做检索和整理，人类判断研究价值
