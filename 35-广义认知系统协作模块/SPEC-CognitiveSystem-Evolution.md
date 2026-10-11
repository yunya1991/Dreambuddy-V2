# SPEC — 大认知系统进化蓝图

> **版本**: v0.2 (2026-10-11)
> **状态**: ✅ 开发完成（2026-10-12 收尾验收五维全通过）— P0-P3 24/24 全落地：P0 接线修复 3 项 + P1 记忆层 7 项 + P2 路由层 6 项 + P3 元认知层 8 项。全量回归 pytest 250 passed / jest 100 passed / tsc 0 errors。验收包: `acceptance_bundles/2026-10-12_cognitive-system/`，落地 commits: b02855935b + afbea75f24 + 58230064b1（此前 P0/P1/P2-1~P2-3 已分批提交）
> **前状态**: 评审后修改（3 Blocking 已修复，L4 降级为研究探索项）
> **评审**: 62/100 → 修改后接受（Devil's Advocate 6 角色评审）
> **关联系统**: 认知系统(4-MEMORY) + SKILL管理 + 知识库(2-KNOWLEDGE) + 文档管理(0-系统文档管理) + 索引系统 + 33-REA逆向解析工程 + dreamos/core/sense 意图识别 + ReverseDeriver
> **调研基础**: 四路并行深度调研（传统金融 + AI/深度学习 + 人类认知科学 + GitHub项目）

---

## 0. 核心命题

> **五系统已构成广义认知系统的骨架，但骨架之间的"神经突触"尚未完全接通。**
>
> 本 Spec 的目标：接线 + 升级 + 进化，实现大认知系统的绝对领先地位。

### 0.1 当前五系统状态（2026-10-11 治理后）

| 系统 | 规模 | 核心能力 | 健康度 |
|------|------|---------|--------|
| 认知系统 | 18,135 记忆 (S=28/A=52/B=622/C=17,384) | recall/record/verify + 蒸馏 + 贝叶斯 | ✅ |
| SKILL管理 | 247 SKILL (active=207/proposed=28/shadow=12) | lifecycle + registry + drift检测 | ✅ |
| 知识库 | 11 域 + ChromaDB 4,540 chunks | RAG三阶段 + memory_bridge | ✅ |
| 文档管理 | 46 索引 + doc_lint/coverage/link_checker | 五件套规范 + 断链=0 | ✅ |
| 索引系统 | 46 INDEX.md 全量治理完成 | 自动生成 + drift-report | ✅ |

### 0.2 协同评估发现的差距（8条链路：5✅ / 3⚠️ / 2❌）

| 级别 | 差距 | 影响 |
|------|------|------|
| **P0-1** | record_hook/verify_hook 已实现但 MCP 未接线 | cognitive_links 覆盖率 26% 停滞 |
| **P0-2** | record 不触发 RAG 向量化 | 新经验不入知识库 |
| **P1-3** | auto_register_skill 不触发 doc-sync | 5件套文档无保障 |
| **P1-4** | doc-sync 无 verify 闭环 | 置信度不升级 |
| **P2-5** | ChromaDB 计数不自动同步 INDEX | 统计需手动维护 |

---

## 1. 四路调研核心发现

### 1.1 传统金融（Renaissance/Bridgewater/Citadel/JPMorgan）

| 发现 | 来源 | 我们的状态 |
|------|------|-----------|
| **Evidence Ledger** 集中化 | Mint-Agent arxiv 2608.16386 | evidence 散在 record/33-REA，未集中 |
| **防篡改审计 trail** | VCP/SCITT IETF draft | verify 只更新置信度，无不可篡改日志 |
| **Alpha Decay 自动化** | Vibe-Trading 24.4K★ sdm_decay_scan | SKILL 治理偏治理，缺策略级衰减 |
| **Per-edge confidence + citation** | ChainSifter/FinReflectKG | ChromaDB chunk 无 per-edge 置信 |
| **FIBO 语义本体** | FIBO RDF/OWL | 46 INDEX 是文件索引，非语义图 |
| **Believability-weighted 决策** | Bridgewater Principles | 无此机制 |
| **Reflection Node** | JPMorgan Ask David | 调度链末尾无 LLM-judge 回环 |

### 1.2 AI/深度学习认知架构

| 发现 | 来源 | 我们的状态 |
|------|------|-----------|
| **Intent-Engine 升级为记忆路由器** | L2A/MHAR/Memory-Augmented Transformer | intent 仅做分类，未做检索路由 |
| **双时序知识图** | Zep/Graphiti 29K★ | 记忆无有效期，无"过去为真但现在失效" |
| **SKILL 自验证入库门** | Voyager (技能 self-verification) | 新 SKILL 无验证即可写入库 |
| **贝叶斯+ACT-R 激活模型** | ACT-R 激活-延迟-效用 | recall 排序只看 score，不看频率/时间衰减 |
| **VERITAS process reward** | step 级忠实性监督 | record 无 step 级推理链溯源 |
| **Self-RAG/CRAG 自纠正** | Self-RAG/CRAG | 无自批判/自纠正检索 |
| **Darwin Gödel Machine** | 源码级自进化 | 无代码级自变异 |

### 1.3 人类认知科学

| 发现 | 来源 | 我们的状态 |
|------|------|-----------|
| **预测编码/自由能原理** | Friston, Science Advances 2026 | 认知系统是被动检索，无"预测vs实际"误差驱动 |
| **记忆再巩固边界** | Royal Society B 2026 | verify 统一更新，不区分记忆强度 |
| **遗忘曲线是幂律** | FSRS 7亿数据验证 | 无主动遗忘机制，C/D 级记忆永久留存 |
| **GWT+HOT 双层意识** | arXiv:2512.19155 | 5子系统隔离，无 workspace bus 广播 |
| **元认知 harness** (FOK/JOL) | arXiv:2605.14186 | 无"我觉得能解决吗"的预评估 |
| **Transactive Memory** | arXiv:2606.19911 | 247 SKILL 无"谁擅长什么"的 agent profile |

### 1.4 GitHub 项目对标

| 项目 | Stars | 关键能力 | 适配方向 |
|------|-------|---------|---------|
| **Mem0** | ~48K | 混合存储+事实抽取+91%token节省 | 替换ChromaDB为混合后端 |
| **Zep/Graphiti** | ~29K | 双时序知识图+事实有效性窗口 | 作为知识库graph层叠加 |
| **Letta/MemGPT** | ~24K | 三层记忆(working/recall/archival) | 参考分层改造认知系统 |
| **Cognee** | ~30K | ECL流水线+图谱原生+MCP | 对接知识库升级 |
| **GraphRAG** | ~30K | Leiden社区检测+分层摘要 | 增强跨文档多跳推理 |
| **Voyager** | 论文 | 自动课程+技能库+self-verify | SKILL自动发现/推荐/精炼 |
| **pgmpy** | - | do-calculus+因果发现+贝叶斯网络 | verify升级为因果推理引擎 |
| **PyMC** | - | MCMC/NUTS+变分推断 | 参数优化/walk-forward验证 |
| **CodeQL** | - | 跨过程数据流+污点追踪 | 33-REA从AST升级到语义级 |

---

## 2. 进化蓝图（四层架构）

### 2.1 总体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     L4: 元认知层 (Metacognition)                   │
│   GWT Workspace Bus + HOT Self-Model + FOK/JOL 元认知 Harness      │
│   预测误差门控 + Believability-weighted 决策                       │
├─────────────────────────────────────────────────────────────────┤
│                     L3: 路由层 (Cognitive Router)                  │
│   Intent-Engine → Cross-Attention 三库加权召回                     │
│   L2A 条件访问(80% fast-path) + Agentic RAG 路由决策               │
├─────────────────────────────────────────────────────────────────┤
│                     L2: 记忆层 (Memory Architecture)               │
│   三层记忆(working/recall/archival) + 双时序知识图                 │
│   ACT-R 激活模型 + FSRS 遗忘调度 + Evidence Ledger               │
├─────────────────────────────────────────────────────────────────┤
│                     L1: 基础层 (Five Systems)                     │
│   认知系统 + SKILL管理 + 知识库 + 文档管理 + 索引系统               │
│   + 33-REA Evidence-First + PoE 信任机制 + ReverseDeriver          │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 L1 基础层：接线修复（P0/P1 差距）

**目标**: 将已实现但未接线的 hooks 接通，完成五系统闭环。

#### 2.2.1 P0-1: record_hook / verify_hook 接线

**现状**: `skill_indexer.py:634` 的 `record_hook()` 和 `verify_hook()` 已实现，但 `cognitive_mcp_server.py` 的 `_handle_record` / `_handle_verify` 未调用它们。

**修复**:
```python
# cognitive_mcp_server.py._handle_record 末尾追加
if any("SKILL" in tag for tag in tags.split(",")):
    skill_indexer.record_hook(
        skill_id=extract_skill_id(content),
        memory_id=memory_id,
        skill_dir=resolve_skill_dir(content)
    )

# cognitive_mcp_server.py._handle_verify 末尾追加
skill_indexer.verify_hook(
    memory_id=memory_id,
    success=success
)
```

**预期效果**: cognitive_links 覆盖率从 26% → 自然提升至 60%+，verify 触发 SKILL lifecycle shadow→active。

#### 2.2.2 P0-2: record → RAG 向量化

**现状**: 新记忆只入认知库，知识库 RAG 检索不到最新经验。

**修复**: 在 `_handle_record` 返回的 `triggered_skills` 中，对 tags 含 `knowledge-ingest` 的记忆**强制标记**并在 Agent 层硬执行 knowledge-ingest SKILL（RAG 向量化）。

#### 2.2.3 P1-3: auto_register_skill → doc-sync

**修复**: 在 `auto_register_skill.py` 注册成功后追加 `dream-doc-sync-workflow` 触发。

#### 2.2.4 P1-4: doc-sync → verify 闭环

**修复**: `dream-doc-sync-workflow` 步骤8 增加对触发记忆的 `verify(memory_id, success=True)`。

---

### 2.3 L2 记忆层：架构升级

#### 2.3.1 三层记忆模型（借鉴 Letta/MemGPT）

```
Working Memory   ← 当前任务上下文（intent_engine 输出 + 当前 SKILL 执行状态）
     ↓ promote
Recall Memory    ← 近期高频访问的记忆（ChromaDB top-K 缓存）
     ↓ consolidate
Archival Memory  ← 长期归档（cognitive_memory.db + 蒸馏产物）
```

**实现**: 在 `cognitive_mcp_server.py` 中增加 `working_memory` 字段（任务级临时存储），recall 时自动提升到 working 层。

#### 2.3.2 双时序知识图（借鉴 Zep/Graphiti）

**问题**: 2024 年的记忆"马丁策略在特定参数下盈利"可能已失效，但系统仍会检索到。

**方案**: 在 ChromaDB 之上叠加 Graphiti 式实体关系图，每条事实带 `valid_time`（何时为真）和 `transaction_time`（何时写入）。

```python
# 记忆 schema 扩展
{
    "content": "马丁策略X在BTC上参数P盈利",
    "valid_time": {"start": "2024-01-01", "end": "2024-06-01"},  # 有效期
    "transaction_time": "2024-01-15",  # 写入时间
    "invalidated_by": null,  # 被哪条新记忆否定
}
```

**recall 升级**: 过滤 `valid_time.end < now` 的记忆，或标记为"历史参考"。

#### 2.3.3 ACT-R 激活模型 + FSRS 遗忘调度

**问题**: 17,384 条 C 级记忆永久留存，检索噪声大。

**方案**: recall 排序不只看 `score`，引入 ACT-R 激活公式：

```
Activation = ln(Σ t_j^(-d))  # d=衰减率, t_j=第j次使用距今时间
           + W_j * relatedness  # 上下文相关度权重
           + base_level  # 基础置信度
```

**遗忘调度器**: C 级且 30 天无 verify 的记忆自动降权或归档（FSRS 幂律衰减）。

#### 2.3.4 Evidence Ledger（借鉴传统金融 VCP/Mint-Agent）

**问题**: evidence 散在 record 和 33-REA 中，无集中化不可篡改的决策审计 trail。

**方案**: 在 4-MEMORY 与 33-REA 之间引入 `evidence_ledger.py`：

```python
@dataclass
class EvidenceEntry:
    subject: str        # 决策主体
    relation: str       # 决策关系
    object: str         # 决策对象
    timestamp: int     # ns 级时间戳
    source: str        # 来源（file:line / memory_id / SKILL_name）
    confidence: float  # 0.0-1.0
    receipt_hash: str  # 链式哈希（前一entry的sha256）
```

**PoE 增强**: 每条 AI 产出的代码/决策必须带 Evidence Ledger receipt，无 receipt 的产出不被信任。

---

### 2.4 L3 路由层：Intent-Engine 升级

#### 2.4.1 从分类器到记忆路由器

**现状**: `dreamos/core/sense/intent_engine.py` 仅做意图分类（6 种意图类型）。

**升级**: intent 输出向量作为 cross-attention 的 query，对三库（记忆库 + SKILL 库 + 知识库）做注意力加权召回：

```
intent_vector = intent_engine(task_description)  # transformer 输出

# 三库 cross-attention
memory_attn = cross_attention(query=intent_vector, keys=memory_embeddings)
skill_attn = cross_attention(query=intent_vector, keys=skill_embeddings)
knowledge_attn = cross_attention(query=intent_vector, keys=chunk_embeddings)

# 加权召回
recall(task_description, top_k=5, 
       weights=[memory_attn, skill_attn, knowledge_attn])
```

#### 2.4.2 L2A 条件访问（80% fast-path）

**借鉴**: awslabs/hybrid-model-factory 的 L2A (Learning To Attend)。

**方案**: 80% 场景走 fast-path（规则缓存 + intent 分类直出），20% 复杂场景才触发全局 cross-attention 检索。

**效果**: 大幅降低检索延迟和 token 消耗。

#### 2.4.3 Agentic RAG 路由

**借鉴**: arXiv:2501.09136 Agentic RAG 综述。

**方案**: 从 pipeline 转向 routing — intent_engine 决定：
- **是否检索**（简单任务直接走缓存）
- **检索什么**（记忆 vs SKILL vs 知识库 vs 混合）
- **何时停止**（置信度达标即停，不再过度检索）

---

### 2.5 L4 元认知层：自我意识

#### 2.5.1 GWT Workspace Bus（全局工作空间广播）

**借鉴**: arXiv:2512.19155 验证的 GWT+HOT 双层原则。

**方案**: 在 5 子系统之上增加一层 `workspace_bus`，在关键决策点广播跨系统信息：

```
workspace_bus.broadcast({
    "intent": intent_engine_output,
    "memory_recall": top_5_memories,
    "skill_match": top_3_skills,
    "knowledge_retrieval": top_5_chunks,
    "confidence": aggregate_confidence,
})

# 高置信信息被"点燃"广播到所有子系统
if workspace_bus.confidence > 0.8:
    broadcast_to_all_subsystems(workspace_bus.ignited_content)
```

#### 2.5.2 HOT Self-Model（高阶自我监控）

**方案**: 独立的 `self_model.py` 监控 workspace 内容的可靠性：

- **置信度校准**: 检查系统置信度是否匹配实际准确率
- **矛盾检测**: 发现 workspace 中相互矛盾的信息
- **错误监测**: 类比 ACC（前扣带回）的错误监测功能

```python
class SelfModel:
    def monitor(self, workspace_state):
        calibration = self.check_calibration(workspace_state.confidence, 
                                              workspace_state.actual_accuracy)
        contradictions = self.find_contradictions(workspace_state)
        errors = self.detect_errors(workspace_state)
        
        if calibration < 0.5 or contradictions or errors:
            return {"action": "verify", "targets": contradictions + errors}
        return {"action": "proceed"}
```

#### 2.5.3 元认知 Harness（FOK/JOL 信号）

**借鉴**: arXiv:2605.14186 LLM 元认知信号研究。

**方案**: 在 SKILL 执行前注入 FOK（Feeling of Knowing）提示，执行后注入 JOL（Judgment of Learning）：

```
SKILL 执行前: "你认为能解决此任务吗？0-1 打分" → FOK
    ↓ 低 FOK → 自动 recall 补充或 escalate 到 deep-research SKILL
SKILL 执行后: "你学到了什么？0-1 打分" → JOL
    ↓ 低 JOL → 标记为需要后续 verify
```

#### 2.5.4 预测误差门控的 record

**借鉴**: 预测编码/自由能原理（Friston），Royal Society B 2026 记忆再巩固边界。

**方案**: record 前生成"预期"（基于 recall 结果），与实际结果差异大时提高 quality_level 初值（类比情绪记忆增强）：

```python
def record_with_prediction_error(content, expected_outcome, actual_outcome):
    prediction_error = abs(expected_outcome - actual_outcome)
    
    # 只有弱记忆（低 base_level）才在 recall 后接受新信息侵入
    # 对应记忆再巩固边界
    if prediction_error > threshold:
        quality_level = "B"  # 高 prediction error → 提升初始质量
    else:
        quality_level = "C"  # 符合预期 → 正常质量
    
    record(content=content, quality_level=quality_level, 
          tags=f"prediction_error={prediction_error}")
```

---

## 3. 新增子系统：33-REA 深度集成

### 3.1 33-REA 在大认知系统中的定位

33-REA 已有 Evidence-First 哲学和 4 层事实分级，在大认知系统中定位为：

```
33-REA = 广义认知系统的"逆向感知器"

正向: recall → SKILL/知识 → 交易决策 → 结果
逆向: 交易结果 → ReverseDeriver → 33-REA 逆向解析 → Evidence → record/verify
```

### 3.2 CodeQL 升级（从 AST 到语义级）

**现状**: 33-REA 纯 AST 分析（Python AST / TS AST）。

**升级**: 引入 CodeQL 的跨过程数据流分析和污点追踪：

- **跨过程数据流**: 追踪一个变量从创建到使用的完整路径
- **污点追踪**: 识别用户输入到关键操作的传播路径
- **语义级调用链**: 不仅仅是函数调用关系，而是数据依赖关系

### 3.3 33-REA → Evidence Ledger

33-REA 的每条分析结论直接写入 Evidence Ledger：

```
33-REA 分析结论 → EvidenceEntry{
    subject: "函数A的调用链",
    relation: "调用了",
    object: "函数B",
    source: "33-REA:python_analyzer.py:42",
    confidence: 0.85,
    level: "derivation",
    known_gaps: ["无法确定函数B的返回值类型"]
}
```

---

## 3.5 评审修复（v0.2 新增）

### Blocking 修复

#### B1: 18,135 条记忆迁移方案

**问题**: P1-3（双时序知识图）需要为每条记忆回填 `valid_time` 和 `transaction_time`，但现有 18,135 条记忆无此字段。

**修复**: 迁移脚本 `migrate_temporal_fields.py`：
```python
# 所有现有记忆回填默认值
valid_time = {"start": memory.created_at, "end": None}  # ∞ = 仍然有效
transaction_time = memory.created_at
invalidated_by = None
```
- 迁移前全量备份 `cognitive_memory.db`
- 回填后运行回归测试：recall 结果不变（`valid_time.end=None` 的记忆行为不变）
- 回滚方案：恢复备份即可，无数据结构破坏

#### B2: FSRS 遗忘调度安全网

**问题**: 17,384 条 C 级记忆自动归档存在数据丢失风险，与"保留审计轨迹"原则矛盾。

**修复**:
1. **C 级先只降权不归档**：recall 排序降权（×0.5），但不从数据库删除
2. **90 天 grace period**：C 级且 90 天无 verify 的记忆进入"候选归档"队列，需人工审核确认
3. **人工审核闸门**：`archival_gate.py` 生成归档候选清单，用户确认后批量归档
4. **全量备份后启用**：FSRS 遗忘调度器启用前必须完成 `cognitive_memory.db` 全量备份

#### B3: 延迟预算 / SLA

**问题**: 三库 cross-attention 对每次 recall 产生 3 倍延迟（SQLite + 247 SKILL embeddings + 4,540 chunks），实时交易场景不可接受。

**修复**: 定义 recall SLA 和测量计划：
- **交易场景 recall SLA ≤ 200ms**（当前实测 ~50ms 单库）
- **L2A fast-path 先做 1 周埋点测量**：在 `recall` 中增加埋点，记录"规则缓存命中率"（预计 70-80%）
- **三库 cross-attention 仅在非实时场景启用**（deep-research / 回测 / 收盘后复盘）
- **实时交易场景**：intent 分类直出 + 单库 recall fast-path

### Major 修复

#### M1: L4 元认知层降级为研究探索项

**问题**: GWT/HOT/FOK/JOL 从意识理论直接跳到工程实现，操作性不足。

**修复**: L4 从 P3 路线图中移除，降级为**研究探索项**，不纳入 P0-P3 承诺时间线。需先做可行性验证（spike）再决定是否升级为正式任务。

#### M2: "80% fast-path" 测量计划

**问题**: 无测量依据。

**修复**: P2-2 前增加前置任务 `P2-1a: recall 埋点测量 1 周`，采集实际规则缓存命中率后再确定 fast-path 比例。

#### M3: Evidence Ledger 链式哈希改 Merkle 树

**问题**: 链式哈希一旦中间断裂则后续全部失效。

**修复**: 改用 Merkle 树结构（局部断裂可隔离），增加写权限控制和哈希碰撞处理。

#### M4: ACT-R 重排序兼容方案

**问题**: ACT-R 激活模型改变全部历史 recall 排序，破坏决策可复现性。

**修复**: P1-4 增加兼容模式：
- `recall(sort_mode="score")` — 原有行为，向后兼容
- `recall(sort_mode="act_r")` — 新激活模型排序
- 默认仍用 `score` 模式，ACT-R 模式需显式启用

#### M5: 时间线调整

**问题**: 24 任务/8-16 周/单人不现实。

**修复**: P0 保留"立即执行"；P1 标"2-4 周"；P2 标"4-8 周（依赖 P1）"；P3 标"探索性，时间待评估"。

#### M6: 层间接口契约

**问题**: 层间接口仅 toy code，无正式契约。

**修复**: 用 ABC 定义各层边界接口：
```python
from abc import ABC, abstractmethod

class CognitiveRouter(ABC):
    """L3 路由层接口"""
    @abstractmethod
    def route(self, intent_vector, databases) -> RecallResult: ...

class EvidenceSink(ABC):
    """L2 Evidence Ledger 接口"""
    @abstractmethod
    def append(self, entry: EvidenceEntry) -> str: ...

class MetacogMonitor(ABC):
    """L4 元认知层接口（探索项）"""
    @abstractmethod
    def monitor(self, workspace_state) -> MonitorResult: ...
```

---

## 4. 进化路径（P0-P3 路线图）

### 4.1 P0: 接线修复（立即执行）

| 序号 | 任务 | 文件 | 预期效果 |
|------|------|------|---------|
| P0-1 | record_hook/verify_hook 接线 | cognitive_mcp_server.py | cognitive_links 26%→60%+ |
| P0-2 | record → RAG 向量化 | _handle_record + knowledge-ingest | 新经验自动入知识库 |
| P0-3 | Evidence Ledger 骨架 | evidence_ledger.py (新建) | 集中化决策审计 trail |

### 4.2 P1: 记忆层升级（2-4 周）

| 序号 | 任务 | 依赖 | 预期效果 |
|------|------|------|---------|
| P1-1 | 三层记忆模型 | P0 完成 | working/recall/archival 分层 |
| P1-2 | FSRS 遗忘调度器 | P1-1 | C/D 级记忆自动衰减 |
| P1-3 | 双时序知识图 | P1-1 | 事实有效期管理 |
| P1-4 | ACT-R 激活模型 | P1-1 | recall 排序升级 |
| P1-5 | auto_register_skill → doc-sync | P0 完成 | 5件套文档保障 |
| P1-6 | doc-sync → verify 闭环 | P1-5 | 文档置信度升级 |
| P1-7 | pgmpy 集成 verify | - | 因果推理能力 |

### 4.3 P2: 路由层升级（4-8 周）

| 序号 | 任务 | 依赖 | 预期效果 |
|------|------|------|---------|
| P2-1 | Intent-Engine → 记忆路由器 | P1 完成 | cross-attention 三库召回 |
| P2-2 | L2A 条件访问 | P2-1 | 80% fast-path 降延迟 |
| P2-3 | Agentic RAG 路由 | P2-1 | 智能检索决策 |
| P2-4 | SKILL 自验证入库门 | P1-5 | Voyager 式 verify-before-commit |
| P2-5 | GraphRAG 社区检测 | P1-3 | 跨文档多跳推理 |
| P2-6 | CodeQL 语义分析 | 33-REA | AST → 语义级 |

### 4.4 P3: 研究探索项（时间待评估）

> ⚠️ L4 元认知层降级为研究探索项（评审 M1 修复）。需先做可行性 spike 验证再决定是否升级为正式任务。

| 序号 | 任务 | 依赖 | 预期效果 |
|------|------|------|---------|
| P3-1 | GWT Workspace Bus | L1-L3 完成 | 跨系统信息广播 |
| P3-2 | HOT Self-Model | P3-1 | 自我监控+错误检测 |
| P3-3 | FOK/JOL 元认知 Harness | P3-1 | 任务前预评估 |
| P3-4 | 预测误差门控 record | P3-2 | 情绪记忆增强 |
| P3-5 | Alpha Decay 自动门禁 | P2-4 | 策略级衰减检测 |
| P3-6 | Reflection Node | P3-1 | LLM-judge 回环 |
| P3-7 | Transactive Memory 索引 | P2-4 | SKILL agent profile |
| P3-8 | FIBO 语义本体 | P1-3 | 文件索引→语义图 |

---

## 5. 绝对领先地位评估

### 5.1 对标矩阵

| 能力 | 我们 | 传统金融 | AI SOTA | GitHub 开源 |
|------|:---:|:---:|:---:|:---:|
| 五系统闭环 | ✅ | ❌ (PDF memo) | ❌ | ❌ |
| Evidence-First 4层分级 | ✅ | ⚠️ (MiFID II 软约束) | ❌ | ❌ |
| SKILL lifecycle 5阶段 | ✅ | ❌ (委员会) | ⚠️ (Voyager 部分) | ❌ |
| Intent → 记忆路由 | 🔧 (升级中) | ❌ | ⚠️ (L2A 论文) | ❌ |
| 双时序知识图 | 📋 (规划) | ❌ | ⚠️ (Zep) | ✅ (Graphiti) |
| 三层记忆 | 📋 (规划) | ❌ | ⚠️ (Letta) | ✅ (MemGPT) |
| 元认知 harness | 📋 (规划) | ❌ | ⚠️ (论文) | ❌ |
| GWT+HOT 意识架构 | 📋 (规划) | ❌ | ⚠️ (arXiv) | ❌ |
| PoE 信任机制 | ✅ | ⚠️ (VCP 草案) | ❌ | ❌ |
| ReverseDeriver 逆向推导 | ✅ | ⚠️ (归因分析) | ❌ | ❌ |
| FSRS 遗忘调度 | 📋 (规划) | ❌ | ❌ | ⚠️ (Anki) |
| Evidence Ledger | 🔧 (P0) | ⚠️ (Mint-Agent) | ❌ | ❌ |

**图例**: ✅ 已实现 | 🔧 开发中 | 📋 已规划 | ⚠️ 部分实现 | ❌ 无

### 5.2 领先判断

**当前已领先**: 五系统闭环、Evidence-First 分级、SKILL lifecycle、PoE 信任机制、ReverseDeriver。

**P0-P1 完成后领先**: + Evidence Ledger、三层记忆、FSRS 遗忘、ACT-R 激活、双时序知识图。

**P2-P3 完成后绝对领先**: + Intent 路由器、元认知 harness、GWT+HOT 意识架构。这组合在任何单一传统金融、AI 论文或开源项目中都不存在。

---

## 6. 与 33-REA 逆向解析工程的协同

### 6.1 正向-逆向闭环

```
正向（推理）:
  intent_engine → recall → SKILL/知识 → 交易决策 → 结果

逆向（解析）:
  交易结果 → ReverseDeriver → 33-REA 逆向解析
    → Evidence (4层分级) → Evidence Ledger
    → record (新经验) → verify (贝叶斯升级)
    → SKILL lifecycle advance (shadow→active)
    → RAG 向量化 (知识库更新)
```

### 6.2 33-REA 赋能点

1. **策略逆向**: 给定一个盈利策略的源码，33-REA 逆向其架构和关键算法
2. **错误逆向**: 给定一个亏损交易，33-REA 逆向决策链，找到错误节点
3. **竞品逆向**: 给定一个开源交易系统 URL，33-REA 逆向其核心设计
4. **自身逆向**: 33-REA 可以逆向分析 dreambuddy 自身的历史代码，辅助理解遗留设计意图

---

## 7. 实施原则

1. **TDD 先行**: 每个 P0/P1 任务先写 RED 测试（断言新功能不存在），再实现 GREEN
2. **FAIL-OPEN**: 所有升级失败不影响现有功能，仅不增强
3. **认知闭环**: 每个任务完成后 record + verify，形成经验闭环
4. **渐进增强**: 旧记忆/SKILL/文档零改动，新字段向后兼容
5. **稳定优先**: 不强制升级，C 级记忆/SKILL 保留审计轨迹

---

## 8. 关联文档

- [33-REA/SPEC.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/33-REA逆向解析工程/SPEC.md) — 逆向解析工程规格
- [33-REA/DESIGN-PHILOSOPHY-PoE.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/33-REA逆向解析工程/DESIGN-PHILOSOPHY-PoE.md) — PoE 设计哲学
- [CLAUDE.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/CLAUDE.md) — 认知系统协作引导
- [SKILL_INDEX.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/工作索引/SKILL_INDEX.md) — SKILL 索引（247 SKILL）
- [ENGINEERING_INDEX.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/ENGINEERING_INDEX.md) — 工程索引

---

## 9. 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v0.1 | 2026-10-11 | 初始草案。基于四路并行深度调研（传统金融+AI/DL+认知科学+GitHub）+ 五系统协同评估 + 33-REA Evidence-First + PoE 信任机制。四层进化架构（L1基础→L2记忆→L3路由→L4元认知）+ P0-P3 路线图。 |
| v0.2 | 2026-10-11 | 评审后修改（62/100 修改后接受）。3 Blocking 修复：B1 记忆迁移方案、B2 FSRS 安全网（降权不归档+90天grace+人工闸门）、B3 延迟预算SLA≤200ms。6 Major 修复：M1 L4降级研究探索项、M2 fast-path测量计划、M3 Merkle树、M4 ACT-R兼容模式、M5时间线调整、M6 ABC接口契约。 |
