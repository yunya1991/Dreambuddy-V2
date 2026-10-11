# PoE 设计哲学 — Proof of Engineering

> **版本**: v1.1 (2026-10-11)
> **状态**: 设计哲学文档（顶层协议）— 已通过同行评审并修复所有 Major 意见
> **关联**: [SPEC-工程实践复现器.md](./SPEC-工程实践复现器.md)、认知系统(4-MEMORY)、知识库(2-KNOWLEDGE)、SKILL治理(1-ARCHITECTURE)、文档管理(0-系统文档管理)、索引系统(2-KNOWLEDGE/9-RAG-INFRA)

---

## 0. 核心命题

> **AI 编码时代的信任危机，与区块链的去中心化信任问题同构。**
>
> 区块链用 POW/POS 让陌生人对账本达成共识；AI 编码需要 **Proof of Engineering (PoE)** 让人和系统信任 AI 生成的代码。
>
> **没有证明链的 AI 代码 = 没有挖矿的区块——不应被信任、不可维护、无法积累。**

---

## 1. 理论基础（跨学科三角验证）

### 1.1 区块链共识机制（信任的数学基础）

| 机制 | 核心思想 | PoE 映射 |
|---|---|---|
| **POW** | 付出计算成本证明工作量 | AI 产出必须付出"工程分析成本"（REA 逆向还原）才能被接受 |
| **POS** | 抵押资产证明利益绑定 | Agent 的历史 PoE 通过率作为"信用抵押"，通过率低则权限受限 |
| **链式哈希** | 区块不可篡改 | Evidence provenance + git 历史构成不可篡改的溯源链 |
| **全节点校验** | 独立验证防伪造 | REA 审计 + 认知记忆 verify 构成独立验证层 |
| **最长链共识** | 多数算力决定真相 | 多次 verify 通过的 Evidence 置信度累积，形成"工程共识" |

### 1.2 软件工程证明理论（可复现性的工程基础）

数学家抵制 OpenAI 的本质：**没有证明链的结论不配叫知识**。软件工程等价物：

- **证明链** = Evidence（provenance + level + confidence + known_gaps）
- **可复现性** = 他人可按同一路径重现分析结果
- **已知边界** = known_gaps 显式标注"不知道什么"
- **方法论可迁移** = 从具体项目蒸馏出通用解法

### 1.3 认知科学（记忆与信任的认知基础）

dreambuddy 认知系统的 Evidence-First 机制本身就是"记忆的证明链"：

- `record`：带证据写入（VOYAGER 5 维评分 + 证据分级 + 已知局限）
- `verify`：贝叶斯置信度更新（连续成功 → 升级，失败 → 降级）
- `recall`：按证据质量检索

**PoE 是认知系统在工程维度的投影**：记忆有证明链，代码也必须有证明链。

---

## 2. 多 Agent 辩论（框架研究方法论）

> 借鉴 `dream-science-framework-research` 的多 Agent 辩论模式，6 个角色对 PoE 设计进行交叉质询。

### 2.1 立场陈述

| Agent | 核心主张 | PoE 设计建议 |
|---|---|---|
| **极简主义者** | 奥卡姆剃刀，最简单方案 | PoE 只需 Evidence 层 + Audit 得分，其他层可选 |
| **复杂系统专家** | 考虑涌现和非线性 | 五层证明链必须完整，Agent 信用评分需考虑网络效应 |
| **风控优先者** | 稳健性和安全性 | 门禁阈值保守（evidence_chain_score ≥ 0.7 才合入），FAIL-OPEN |
| **性能追求者** | 最大化效率 | 证明链生成应自动化（REA 自动审计），不增加人工负担 |
| **维护工程师** | 可维护性和可扩展性 | 证明链格式标准化，与五大系统解耦，通过接口集成 |
| **跨学科视角者** | 引入其他学科框架 | 借鉴区块链的 slash 机制设计 Agent 惩罚，借鉴科学论文的 peer review |

### 2.2 交叉质询与妥协

**质询 1**（风控 vs 极简）：极简方案只有 Evidence + Audit，是否足够？

- 风控："只有得分没有上下文，无法判断为什么得分低"
- 极简："得分低就打回，不需要知道为什么"
- **妥协**：Evidence + Audit 为 P0 必选层，决策层/叙事层/方法论层为 P1/P2 可选层，但得分计算时可选层缺失会扣分

**质询 2**（性能 vs 风控）：自动化审计 vs 人工确认

- 性能："每个 AI 提交都自动跑 REA，不增加人工"
- 风控："自动审计可能漏判，关键路径需人工确认"
- **妥协**：得分 ≥ 0.8 自动通过；0.5-0.8 人工审核；< 0.5 自动打回

**质询 3**（维护 vs 复杂）：与五大系统的集成深度

- 维护："证明链应该独立，通过标准接口与五大系统交互"
- 复杂："应该深度集成，证明链直接写入认知记忆和知识库"
- **妥协**：证明链格式标准化（JSON Schema），通过认知系统 record 写入，通过知识库 RAG 可检索，不侵入五大系统内部

### 2.3 综合决策

- **P0**：Evidence 层 + Audit 层（必选），自动门禁
- **P1**：决策层 + 叙事层（增强可信度）
- **P2**：方法论层（知识积累）
- **集成方式**：标准化格式 + 认知系统 record 接口，不侵入五大系统

---

## 3. 五大系统协同架构

### 3.1 PoE 证明链在五大系统中的流转

```
AI 生成代码/记忆/SKILL/文档
        │
        ▼
┌─────────────────────────────────────────────────────┐
│              PoE 证明链生成层（REA）                  │
│  Evidence → Design Decision → Narrative → Methodology│
│  + Audit 得分                                         │
└──────────────────────┬──────────────────────────────┘
                       │ 证明链（标准化 JSON）
        ┌──────────────┼──────────────┬──────────────┐
        ▼              ▼              ▼              ▼
┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐
│  认知系统   │ │  知识库     │ │ SKILL治理  │ │ 文档管理   │
│ 4-MEMORY   │ │ 2-KNOWLEDGE│ │1-ARCHITECTURE│ │0-系统文档  │
│            │ │            │ │            │ │            │
│ record 写入 │ │ RAG 可检索 │ │ 注册标记   │ │ INDEX 登记 │
│ verify 更新 │ │ 向量化存储 │ │ 通过率关联 │ │ 覆盖校验   │
│ recall 检索 │ │            │ │            │ │            │
└────────────┘ └────────────┘ └────────────┘ └────────────┘
        │              │              │              │
        └──────────────┴──────┬───────┴──────────────┘
                             ▼
                    ┌────────────────┐
                    │   索引系统      │
                    │ 2-KNOWLEDGE/   │
                    │ 9-RAG-INFRA    │
                    │                │
                    │ 证明链索引     │
                    │ 语义检索入口    │
                    └────────────────┘
```

### 3.2 各系统的 PoE 职责

| 系统 | PoE 职责 | 接口 |
|---|---|---|
| **认知系统** | 证明链的存储与验证中枢 | `record`（写入证明链）、`verify`（置信度更新）、`recall`（按证据检索） |
| **知识库** | 证明链的语义检索 | RAG 向量化，支持"某段代码的设计决策是什么"类查询 |
| **SKILL 治理** | SKILL 的 PoE 标记 | SkillEntry 增加 `poe_score` 字段，反映 SKILL 产出的证明链质量 |
| **文档管理** | 证明链的文档化 | ADR 风格决策记录写入文档索引，doc_coverage 校验证明链文档覆盖 |
| **索引系统** | 证明链的统一入口 | INDEX.md 登记证明链文档，IndexQueryService 支持语义检索 |

### 3.3 协同链路

```
AI 提交变更
    ↓
post-commit hook → auto_sync_dispatcher（已有）
    ↓ 分类
    ├── SKILL.md → skill_indexer 注册（标记 poe_score）
    ├── 2-KNOWLEDGE/ → 知识库向量化（证明链可检索）
    ├── 其他.md → 文档管理待同步队列（INDEX 登记）
    └── 代码变更 → REA 审计（新增）→ 证明链 → 认知系统 record
```

---

## 4. 证明链标准格式

### 4.1 ProofChain 数据结构

```json
{
  "proof_chain_id": "pc_<64 hex>",
  "target": "<目标路径或 AI 产出标识>",
  "ai_context": {
    "agent_id": "<Agent 标识>",
    "model": "<模型名>",
    "prompt_hash": "<prompt 哈希>",
    "timestamp": "<ISO 时间>"
  },
  "layers": {
    "evidence": [ ... ],          // P0 必选
    "audit": { ... },             // P0 必选
    "design_decisions": [ ... ],  // P1 可选
    "narrative": { ... },         // P1 可选
    "methodology": [ ... ]        // P2 可选
  },
  "poe_score": 0.0,               // 0.0-1.0 综合证明链得分
  "created_at": "<ms 时间戳>"
}
```

### 4.2 各层格式规范

#### Evidence 层（P0 必选，复用 `core/evidence.py`）

```json
{
  "evidence_id": "ev_<64 hex>",
  "result": "<结论>",
  "level": "observation | derivation | inference | unknown",
  "provenance": { "file": "<路径>", "line": <行号>, "engine": "<分析器>" },
  "confidence": 0.0,
  "known_gaps": ["<局限>"],
  "observations": [ ... ]
}
```

#### Audit 层（P0 必选）

```json
{
  "evidence_chain_score": 0.0,        // 0.0-1.0 证据链完整度
  "coverage_score": 0.0,              // 0.0-1.0 注释/测试/文档覆盖
  "complexity_score": 0.0,            // 0.0-1.0 复杂度健康度（越低越好，反向计分）
  "cognitive_debt": [                 // 认知债务清单
    {
      "type": "uncommented_complexity | untested_core | magic_number | hardcoded",
      "provenance": { "file": "<路径>", "line": <行号> },
      "severity": "low | medium | high"
    }
  ],
  "gate_decision": "pass | review | reject"  // 门禁决策
}
```

#### Design Decision 层（P1 可选）

```json
{
  "decision_id": "dd_<64 hex>",
  "decision": "<决策描述>",
  "context": "<上下文>",
  "alternatives": ["<被放弃的方案>"],
  "consequences": ["<影响>"],
  "evidence_refs": ["ev_<id>", ...],   // 引用 Evidence 层
  "level": "derivation | inference"
}
```

#### Narrative 层（P1 可选）

```json
{
  "timeline": [
    {
      "commit": "<hash>",
      "timestamp": "<ISO>",
      "author": "<作者>",
      "change_summary": "<变更摘要>",
      "turning_point": true,
      "motivation_inference": "<重构动机推断>"
    }
  ],
  "tech_debt_timeline": [ ... ],
  "evidence_refs": ["ev_<id>", ...]
}
```

#### Methodology 层（P2 可选）

```json
{
  "methodology_id": "mt_<64 hex>",
  "problem_pattern": "<问题模式>",
  "solution_pattern": "<解法模式>",
  "applicability": ["<适用条件>"],
  "known_gaps": ["<局限>"],
  "evidence_refs": ["ev_<id>", ...],   // 跨项目引用
  "level": "derivation"
}
```

---

## 5. 门禁阈值设计

### 5.1 三级门禁

| 级别 | 条件 | 动作 | 类比区块链 |
|---|---|---|---|
| **PASS** | `poe_score ≥ 0.8` 且 `evidence_chain_score ≥ 0.7` | 自动合入 | 验证通过的区块 |
| **REVIEW** | `0.5 ≤ poe_score < 0.8` | 人工审核 | 需确认的区块 |
| **REJECT** | `poe_score < 0.5` 或 `evidence_chain_score < 0.4` | 自动打回 | 无效区块 |

### 5.2 poe_score 计算

```
raw_score = w1 * evidence_chain_score
          + w2 * coverage_score
          + w3 * (1 - complexity_penalty)

poe_score = clamp(raw_score * layer_completeness_bonus, 0.0, 1.0)

其中：
- w1 = 0.4（证据链完整度权重最高）
- w2 = 0.25（覆盖率）
- w3 = 0.2（复杂度，反向计分）
- w1 + w2 + w3 = 0.85，剩余 0.15 由 layer_completeness_bonus 通过乘数效应体现

layer_completeness_bonus（层完整度乘数，∈ [1.0, 1.176]）:
- 只有 Evidence + Audit (P0):     bonus = 1.0      → poe_score 上限 = 0.85
- + Design Decision (P1):          bonus = 1.05     → poe_score 上限 = 0.8925
- + Narrative (P1):                bonus = 1.1      → poe_score 上限 = 0.935
- + Methodology (P2):              bonus = 1.176    → poe_score 上限 = 1.0

clamp(x, 0.0, 1.0): 若 x > 1.0 取 1.0，若 x < 0.0 取 0.0
```

> **设计说明**：层完整度不是直接加分，而是乘数。这样 P0-only 的产出最高只能到 0.85，激励 Agent 补充 P1/P2 层来提升得分上限，同时保证 poe_score 始终 ∈ [0, 1]。

### 5.3 门禁阈值的成本系数 β

门禁阈值的选择本质是**误通过 vs 误拒绝的成本权衡**：

```
β = cost(误通过) / cost(误拒绝)

加权 F1 = (1+β²)·P·R / (β²·P + R)
```

**β 的取值方法**：
1. **历史事故成本法**（推荐）：统计过去 6 个月因"坏代码合入"导致的事故总成本（人天 + 资金损失），除以因"好代码被打回"导致的效率损失成本
2. **项目类型推荐区间**：

| 项目类型 | β 推荐值 | 说明 |
|---|---|---|
| 交易系统/资金相关 | 3.0–5.0 | 误通过成本极高（可能导致实盘亏损） |
| 核心基础设施 | 2.0–3.0 | 误通过影响面大，但可回滚 |
| 内部工具/脚本 | 1.0–2.0 | 误通过成本中等，可快速修复 |
| 实验性/原型 | 0.5–1.0 | 鼓励创新，误拒绝成本更高 |

> **说明**：β 越大，门禁越保守（倾向拒绝）。交易系统默认 β=3.0，对应 PASS 阈值应偏高（0.8–0.85）。

### 5.4 创新性快速通道（Experimental Fast Track）

> 应对 Devil's Advocate DA-1：防止 PoE 抑制 AI 编码的创新性。

创新性代码往往注释少、无测试、结构非标准，poe_score 会偏低。为避免误拒，引入快速通道：

| 条件 | 动作 |
|---|---|
| AI 产出标记 `experimental: true` | 跳过自动 REJECT，直接进入 REVIEW |
| 人工确认"创新性探索" | 降低 PASS 阈值至 0.6，允许低注释率 |
| experimental 代码合入后 | 必须在 7 天内补充证明链，否则信用分 -0.02 |

**标记规则**：
- Agent 可在提交时声明 `experimental: true`，但需附"创新点说明"
- 同一 Agent 每月 experimental 标记上限为 3 次（防止滥用）
- experimental 代码不计入 `weighted_pass_rate` 分子（避免刷分）

### 5.5 FAIL-OPEN 降级

- 审计失败时：`poe_score = 0.0`，`gate_decision = review`，附 `known_gaps: ["审计失败，需人工确认"]`
- 不阻塞业务流程，但标记为需人工审核

---

## 6. Agent 信用评分规则

### 6.1 Agent Credit Score

借鉴 POS 的 stake 机制和区块链的 slash 机制，采用**任务难度加权**的加权平均公式：

```
agent_credit = 0.4 * weighted_pass_rate
             + 0.3 * poe_avg_score
             + 0.2 * verify_success_rate
             + 0.1 * (1 - score_std)

其中：
- weighted_pass_rate: 任务难度加权的 PASS 率
    weighted_pass_rate = Σ(pass_i * difficulty_i) / Σ(difficulty_i)
    difficulty_i ∈ [0.5, 2.0]，由变更规模（文件数+行数）和模块重要性决定
    （防止 Agent 通过大量简单任务刷分）
- poe_avg_score: Agent 产出的平均 poe_score（0.0-1.0）
- verify_success_rate: Agent 产出被 verify 成功的比率
- score_std: poe_score 的标准差（越小越稳定，1 - std 作为稳定性得分）
```

> **防刷分机制**：`weighted_pass_rate` 引入难度加权，简单任务（difficulty=0.5）对信用分的贡献只有复杂任务（difficulty=2.0）的 1/4，抑制"刷简单任务"行为。

### 6.2 信用等级与权限

| 信用分 | 等级 | 权限 | 类比 |
|---|---|---|---|
| ≥ 0.8 | **Trusted** | 自动通过（PASS 阈值降至 0.7） | POS 验证者 |
| 0.6-0.8 | **Verified** | 标准门禁 | 普通节点 |
| 0.4-0.6 | **Cautious** | 所有产出需人工审核 | 待验证节点 |
| < 0.4 | **Restricted** | 限制合入权限，需 mentor 审批 | slash 后节点 |

### 6.3 奖惩机制

| 事件 | 信用分变动 | 类比 |
|---|---|---|
| PoE PASS | +0.01（衰减） | 区块奖励 |
| PoE REJECT | -0.05 | slash |
| verify(success=True) | +0.02 | 验证者奖励 |
| verify(success=False) | -0.03 | 验证失败惩罚 |
| 方法论被复用 ≥ 3 次 | +0.05 | 长期贡献奖励 |

### 6.4 与认知系统的协同

- Agent 信用分通过认知系统 `record(tags="agent-credit")` 存储
- `verify` 成功/失败自动更新信用分
- 信用分作为 `recall` 的排序因素之一（高信用 Agent 的产出优先检索）

---

## 7. 冷启动方案

> 解决"鸡生蛋"问题：PoE 依赖 N≥100 样本调优权重和阈值，但初期无数据。

### 7.1 初始默认值（无数据时使用）

| 参数 | 初始值 | 调整触发条件 |
|---|---|---|
| w1 (Evidence 权重) | 0.4 | N≥100 后做消融实验 |
| PASS 阈值 | 0.75（略保守） | 误通过率 > 10% → 0.8；误拒率 > 30% → 0.7 |
| β（成本比） | 3.0（交易系统默认） | 有 6 个月事故数据后用历史成本法重算 |
| Agent 信用初始分 | 0.5（Verified） | 完成 10 次产出后开始计算 |

### 7.2 渐进调优机制

```
阶段 A (N < 30): 使用初始默认值，只记录数据不调参
阶段 B (30 ≤ N < 100): 做初步敏感性分析，微调阈值（±0.05）
阶段 C (N ≥ 100): 做正式消融实验和 ROC 分析，更新权重和阈值
```

### 7.3 数据收集方式

- 样本来源：dreambuddy 自身 git log 中的 AI 提交
- 标注方式：人工标注可维护性（1-5 分），每周标注 10-20 个
- 特征提取：对每个样本跑 REA 审计，提取 poe_score 各分量

---

## 8. 演进路径

### 阶段 1：P0 核心（Evidence + Audit 门禁）

- 实现 `ai_audit.py`（Evidence 层 + Audit 层）
- 实现 `poe_score` 计算和三级门禁
- 接入 post-commit hook，AI 代码变更自动审计
- 证明链通过认知系统 `record` 存储

### 阶段 2：P1 增强（决策层 + 叙事层）

- 实现 `design_decision_recovery.py`
- 实现 `evolution_narrative.py`
- 证明链层完整度加成生效
- ADR 记录写入文档管理系统

### 阶段 3：P2 积累（方法论层 + Agent 信用）

- 实现 `methodology_abstraction.py`
- 实现 Agent 信用评分
- 方法论入库知识库，支持 RAG 检索
- SKILL 治理增加 `poe_score` 字段

### 阶段 4：生态闭环（五大系统深度协同）

- 索引系统支持证明链语义检索
- 知识库 RAG 支持"某功能的设计决策"类查询
- 文档管理系统校验证明链文档覆盖
- Agent 信用分影响 SKILL 执行权限

---

## 8. 与现有系统的集成点

| 现有模块 | 集成方式 | 改动 |
|---|---|---|
| `4-MEMORY/9-工具与接口/cognitive_mcp_server.py` | `record` 支持 proof_chain 内容 | 无侵入，content 字段传入 |
| `2-KNOWLEDGE/9-RAG-INFRA/index_query_service.py` | 证明链向量化，支持语义检索 | 新增 proof_chain 类别 |
| `1-ARCHITECTURE/skills/dream-skill-index-governance/skill_indexer.py` | SkillEntry 增加 `poe_score` | 扩展数据结构 |
| `1-ARCHITECTURE/skills/dream-skill-index-governance/auto_sync_dispatcher.py` | 代码变更触发 REA 审计 | 新增分类 `code_change` |
| `0-系统文档管理/4-工具与自动化/doc_coverage.py` | 校验证明链文档覆盖 | 新增校验项 |
| `33-REA逆向解析工程/core/` | 生成证明链各层 | 新增模块（见 SPEC） |

### 8.1 AI 编码流水线接入点

PoE 审计在 AI 编码流水线中的触发位置和阻塞策略：

```
AI Agent 生成代码
       │
       ▼
  本地测试通过？──否──→ 打回（不触发 PoE）
       │是
       ▼
┌─────────────────────────────────────┐
│  REA 审计（异步，不阻塞本地开发）      │
│  - 生成 ProofChain                   │
│  - 计算 poe_score                     │
│  - 判定 gate_decision                 │
└──────────────────┬──────────────────┘
                   │
       ┌───────────┼───────────┐
       ▼           ▼           ▼
    PASS        REVIEW       REJECT
       │           │           │
  自动合入     人工审核      自动打回
  (不阻塞)    (阻塞提交)    (阻塞提交)
```

**阻塞策略**：
- `PASS`：不阻塞，自动合入
- `REVIEW`：阻塞提交，等待人工审核（可设超时 24h 自动降级为 REJECT）
- `REJECT`：阻塞提交，Agent 需修改后重新提交

**异步审计**：
- REA 审计在后台执行，Agent 可继续生成下一段代码
- 审计结果通过认知系统 `record` 写入，并通知 Agent
- 对于大型变更（> 100 文件），采用增量分析，先审计核心路径

---

## 9. 风险与约束

| 风险 | 应对 |
|---|---|
| 证明链生成增加 AI 编码延迟 | REA 审计异步执行，不阻塞提交；增量分析缓存 |
| inference 级结论产生幻觉 | 强制标注 known_gaps；inference 结论不计入 evidence_chain_score 分子 |
| Agent 信用分被操纵 | 引入一致性惩罚（标准差大扣分）；verify 独立验证 |
| 五大系统集成复杂度 | 标准化 ProofChain JSON Schema，通过接口解耦 |
| 过度审计导致开发效率下降 | 分层门禁，P0 只跑 Evidence+Audit，P1/P2 可选 |

---

## 10. 开放问题

- [ ] **Q1**: poe_score 的权重（w1-w4）如何调优？是否需要贝叶斯优化？
- [ ] **Q2**: Agent 信用分的初始值和收敛速度如何设定？
- [ ] **Q3**: 证明链的存储成本如何控制？是否需要归档机制？
- [ ] **Q4**: 跨项目方法论抽象的输入来源——是 REA 历史累积还是主动分析标杆项目？
- [ ] **Q5**: PoE 门禁是否会误伤创新性代码（低注释但高价值）？如何平衡？

---

## 11. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| 1.0.0 | 2026-10-11 | 初始版本：核心命题 + 跨学科理论基础 + 多Agent辩论 + 五大系统协同 + 证明链格式 + 门禁阈值 + Agent信用评分 + 演进路径 |
