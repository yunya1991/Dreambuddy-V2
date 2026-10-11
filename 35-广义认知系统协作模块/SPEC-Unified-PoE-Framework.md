# 统一 PoE 框架 SPEC — Evidence-First 工程审计框架

> **版本**: v2.0 (2026-10-11)
> **状态**: 草案（v1.0 经 4 维度调研修正后版本）
> **父文档**: [DESIGN-PHILOSOPHY-PoE.md](../33-REA逆向解析工程/DESIGN-PHILOSOPHY-PoE.md) v1.1、[SPEC-工程实践复现器.md](../33-REA逆向解析工程/SPEC-工程实践复现器.md) v0.3、[SPEC-CognitiveSystem-Evolution.md](./SPEC-CognitiveSystem-Evolution.md)
> **关联**: 认知系统 (4-MEMORY)、33-REA 逆向解析工程、自进化系统 (23-)

---

## 0. 本 SPEC 要解决的问题

当前存在**两套 PoE 实现**，定位重叠且认知侧过重：

| 维度 | 33-REA 侧重型 PoE | 认知系统侧 PoE |
|---|---|---|
| 证明深度 | 五层证明链（Evidence/Decision/Narrative/Methodology/Audit） | 仅 receipt 存在性查询 |
| 门禁 | 三级门禁（PASS/REVIEW/REJECT）+ poe_score | soft/strict/off enforcement |
| 触发场景 | AI 代码合入门禁 | 每次 record/verify/recall |
| 现状 | 设计完成，部分实现（cognitive_integration.py） | 已实现，35 处引用，**过重** |

**问题**：认知系统每次 recall/verify 都跑全量完整性验证 + receipt 查询，开销过大；且与 33-REA 侧的"五层证明链"概念混淆。

**本 SPEC 的统一命题**：**PoE 是同一个机制的两种验证深度**——不是两套机制：
- **深度验证（重型）** = 33-REA 侧：五层证明链 + poe_score + 三级门禁，用于代码开发审核
- **索引查询（轻量）** = 认知系统侧：只验 receipt 存在性（O(1) 查询），用于日常调用

> **v2.0 设计说明**：v1.0 曾用区块链"全节点 vs SPV 轻节点"做类比。经 4 维度调研（详见 §11），该类比存在三个陷阱：(1) PoE 伪造证明链成本低于真实分析，PoW 的"不对称性"不成立；(2) Agent 信用分无真实资产抵押，非 PoS；(3) 本系统单信任方自审计，无拜占庭威胁，Merkle 树属重复建设（git commit hash 已是链式哈希）。v2.0 剥离区块链隐喻，保留工程实质。

---

## 1. 用户核心想法（SPEC 设计输入）

本 SPEC 体现用户的三点核心要求：

### 想法 1：PoE 双模式 + 信任传递

> "代码开发中，POE 机制应该被作重，作为一个代码审核门禁；但是在大认知系统调用时则应该快速轻量调用，如果代码开发中经过 POE 机制验证，新开发中则可以轻量"

映射为设计：
- **重型模式（Heavy）**：代码开发审核门禁，五层证明链 + poe_score + 三级门禁
- **轻量模式（Light）**：认知系统日常调用，只验 receipt 存在性
- **有界信任传递（Bounded Trust Transfer）**：已通过重型 PoE 的产出，后续认知调用可降级为轻量验证或抽样重验（**非无条件跳过**，详见 §2.3）

### 想法 2：PoE + 逆向工程用于新项目调研

> "POE 机制以及逆向工程可以用于新项目调研，这个当然也属于重型深度调研，这个有别于目前项目调研中仅通过 SKILL 等文档类型的调研"

映射为设计：
- **重型深度调研** = PoE + 33-REA 逆向工程（代码级证据链还原）
- **轻量文档调研** = 现有 SKILL/文档型调研（RAG 检索）
- 两者结合：先轻量调研建立框架，再重型逆向验证关键假设

### 想法 3：正向-逆向闭环 + 轻重两类结合

> "正向-逆向闭环可以多用，一般双向验证 + 轻重两类结合"

映射为设计：
- **正向** = 设计意图 → 代码实现 → 文档/SKILL
- **逆向** = 代码 → REA 还原 → 设计决策 → 方法论
- **闭环** = 正向产出 ↔ 逆向验证（双向一致性校验）
- **轻重结合** = 轻量快速筛查 + 重型深度验证

---

## 2. 统一架构：双模式 + 有界信任传递

### 2.1 双验证深度

```
┌─────────────────────────────────────────────────────────┐
│           PoE 统一信任机制（一个机制，两种验证深度）      │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─────────────────────────┐  ┌──────────────────────┐ │
│  │  深度验证（Heavy/重型）  │  │  索引查询（Light）    │ │
│  │  = 33-REA PoE           │  │  = 认知系统 PoE       │ │
│  │                         │  │                      │ │
│  │  • 五层证明链            │  │  • receipt 存在性    │ │
│  │  • poe_score 计算        │  │  • O(1) 索引查询     │ │
│  │  • 三级门禁 PASS/REVIEW/ │  │  • 不跑全量验证      │ │
│  │    REJECT                │  │  • 不跑五层证明链    │ │
│  │  • Agent 声誉评分        │  │                      │ │
│  └────────────┬────────────┘  └──────────┬───────────┘ │
│               │                          │             │
│               │   证明链摘要              │             │
│               │   (receipt + git_hash)    │             │
│               └──────────┬───────────────┘             │
│                          ▼                             │
│              ┌──────────────────────┐                  │
│              │  Evidence Index      │                  │
│              │  (统一存储层)         │                  │
│              │  • SQLite + WAL 模式  │                  │
│              │  • entry + receipt   │                  │
│              │  • git_commit_hash   │                  │
│              │    (链式溯源等价物)    │                  │
│              └──────────────────────┘                  │
└─────────────────────────────────────────────────────────┘
```

**关键约束**：
- 深度验证产出 → 生成 receipt + 写入 Evidence Index → 轻量查询可索引验证
- 轻量查询**不跑**五层证明链计算，只查 receipt 是否在 Index 中（O(1)）
- `git_commit_hash` 提供链式溯源（工程等价于区块链的链式哈希，无需另建 Merkle 树）

### 2.2 双模式（触发场景）

| 模式 | 触发场景 | 验证深度 | 阻塞策略 | 典型耗时 |
|---|---|---|---|---|
| **重型模式** | AI 代码合入、新项目逆向调研、关键模块审计 | 深度验证（五层证明链） | 阻塞合入（PASS/REVIEW/REJECT） | 秒-分钟级 |
| **轻量模式** | 认知系统 record/verify/recall、日常 SKILL 调用 | 索引查询 | 不阻塞，仅降权/标记 | 毫秒级 |
| **抽样模式** | 已验证产出的后续调用（同进程 + 时间窗口内） | 10% 概率重跑轻量验证 | 无 | 0 或毫秒级 |

**模式选择规则**：
```python
def select_poe_mode(artifact, context):
    if artifact.already_verified and context.same_process_and_within_window:
        return "sample"         # 有界信任传递（10% 抽样重验）
    if context.is_code_merge or context.is_deep_research:
        return "heavy"          # 重型门禁
    if context.is_cognitive_call:  # record/verify/recall
        return "light"          # 轻量索引查询
    return "light"              # 默认轻量
```

### 2.3 有界信任传递机制（v2.0 关键修正）

**核心规则**：已通过重型 PoE 验证的产出，后续可降级为轻量验证或抽样重验。**信任不是无条件的**——经 4 维度调研，业界 SLSA 框架经过论证已放弃传递性（防 SolarWinds 式依赖链攻击），PoE 必须用"有界传递 + 依赖指纹 + 抽样重验"补齐失效条件。

```
首次产出 → 重型 PoE（五层证明链 + poe_score）→ PASS
                    ↓
            receipt + git_commit_hash 写入 Evidence Index
            Agent 声誉分 +0.01
                    ↓
后续认知调用 → 轻量索引查询（只验 receipt）→ 信任
                    ↓
同进程 + 时间窗口内复用 → 抽样模式（10% 概率重验）
```

**信任传递的 6 个失效条件**（v1.0 的 3 个扩展为 6 个）：

| # | 失效条件 | 触发动作 | 来源 |
|---|---|---|---|
| 1 | 代码变更（git commit hash 变化） | 信任失效，需重新重型验证 | v1.0 原有 |
| 2 | verify(success=False) | 声誉分下降，升级为重型验证 | v1.0 原有 |
| 3 | 超时（按产出类型分级：代码 1 天 / 文档 30 天） | 降级为轻量验证 | v1.0 改（分级） |
| 4 | 依赖指纹变化（下游代码 hash 变即失效） | 信任失效，重新重型验证 | v2.0 新增 |
| 5 | scope 漂移（为目的 A 验证 ≠ 目的 B 安全） | 需重新验证 | v2.0 新增 |
| 6 | 抽样重验失败（10% 概率重跑，未通过） | 信任降级，触发重型验证 | v2.0 新增 |

> **设计依据**：SLSA 规范明确拒绝传递性，核心理由是依赖链攻击风险。PoE 的有界传递通过"依赖指纹 + scope 限制 + 抽样重验"在工程层面补齐这一风险。skip 模式改为"抽样验"而非全跳过，对齐 SLSA VSA 的 periodic re-verification。

---

## 3. 认知系统侧 PoE 简化方案

### 3.1 当前问题

`cognitive_loop_entry.py` 的 `_check_poe_trust()` 当前实现：
- 每次 recall 都跑 `evidence_ledger.verify_integrity()`（**全量验证，O(N)**）
- 每次 verify 都查 receipt
- 35 处 poe 相关引用，认知侧过重

### 3.2 简化方向（索引查询 + 有界并发）

**改为索引查询**：
- **不再每次跑全量完整性验证**，改为：
  - 启动时跑一次全量验证（健康检查）
  - 日常只验 receipt 是否在 Index 中（O(1) 查询）
  - **v2.0 移除"每 100 次操作跑全量"机制**（依赖信任失效条件，详见 §7 P0 调整）
- **recall 降权简化**：
  - 无 receipt 的记忆 → score * 0.5（保留现有 soft 模式）
  - 不再在 recall 路径跑全量验证（移到健康检查路径）
- **verify 路径简化**：
  - 只查 receipt 存在性，不跑全量验证
  - strict 模式下无 receipt 直接失败（保留）

**并发安全（v2.0 新增）**：
- SQLite 开启 WAL 模式（`PRAGMA journal_mode=WAL`），支持多进程并发读写
- 计数器落库（新增 counter 表 + atomic UPDATE），跨进程共享
- 不用文件 flock（引入新故障面）

### 3.3 enforcement 与 mode 的关系（v2.0 明定）

经调研，`poe_enforcement`（soft/strict/off）与 `poe_mode`（heavy/light/sample）是**正交概念**，不冲突：

| 维度 | 含义 | 决定什么 | 作用层 |
|---|---|---|---|
| `poe_enforcement` | 单次检查的严格度 | 无 receipt 时是否阻塞 | 轻量模式内部 |
| `poe_mode` | 选哪条验证路径 | 跑五层证明链/索引查询/抽样 | 顶层路径选择 |

- `mode=heavy` → 跑 33-REA 五层证明链（enforcement 不适用）
- `mode=light` + `enforcement=strict` → 无 receipt 直接失败
- `mode=light` + `enforcement=soft` → 无 receipt 降权但不阻塞
- `mode=light` + `enforcement=off` → 不检查
- `mode=sample` → 10% 概率重跑 light（enforcement 沿用上次设置）

### 3.4 代码改动点

| 文件 | 当前 | 改为 |
|---|---|---|
| `cognitive_loop_entry.py` `_check_poe_trust()` | 每次跑 `verify_integrity()` | 启动时跑一次，日常只查 receipt |
| `cognitive_loop_entry.py` recall 路径 | 对每条结果跑 `_check_poe_trust` | 只查 receipt 存在性 |
| `cognitive_loop_entry.py` verify 路径 | 跑 `_check_poe_trust` | 只查 receipt 存在性 |
| `evidence_ledger.py` | `verify_integrity()` 全量 | 新增 `verify_receipt_exists(entry_id)` O(1) |
| `evidence_ledger.py` | 默认 SQLite 模式 | 开启 WAL 模式 |
| `evidence_ledger.py` | 无计数器 | 新增 counter 表 + atomic UPDATE |

---

## 4. 33-REA 侧重型 PoE（代码审核门禁）

### 4.1 保持现有设计

33-REA 侧的五层证明链 + poe_score + 三级门禁设计**不变**，详见：
- [DESIGN-PHILOSOPHY-PoE.md](../33-REA逆向解析工程/DESIGN-PHILOSOPHY-PoE.md) v1.1
- [SPEC-工程实践复现器.md](../33-REA逆向解析工程/SPEC-工程实践复现器.md) v0.3

### 4.2 与认知系统的协同（v2.0 修正写入路径）

33-REA 重型 PoE 通过后：
1. 生成 `ProofChain`（标准化 JSON）
2. 将证明链摘要（receipt + git_commit_hash）写入 Evidence Index
3. 通过 `cognitive_integration.py` 的 `prepare_*_record_params()` 写入认知系统
4. Agent 声誉分更新（通过 `verify(success=True)`）

**v2.0 修正——统一写入路径**：
- `prepare_record_params()` 已返回 `evidence_entries` 字段（P1-L1-3 已实现）
- `prepare_decision_record_params()` / `prepare_audit_record_params()` **需补齐 `evidence_entries` 字段**（当前缺失，导致重复写入路径）
- 统一由 Agent 走 `record()` 一条路径写认知库 + Index，不另开"证明链摘要写入"第二条路径

后续认知调用该产出时：
- 轻量索引查询 receipt 存在 → 信任
- 不再重跑五层证明链

---

## 5. 新增：PoE + 逆向工程用于新项目调研（用户新想法 2）

### 5.1 两种调研模式的区别

| 维度 | 轻量文档调研（现有） | 重型逆向调研（新增） |
|---|---|---|
| 数据源 | SKILL 文档、RAG 知识库、已沉淀记忆 | 目标项目源码 + git 历史 + 依赖图 |
| 方法 | RAG 语义检索 + recall | 33-REA 四阶段（Locate→Trace→Reduce→Annotate）+ PoE 五层 |
| 产出 | 调研报告（文本） | 证明链（Evidence + 设计决策 + 方法论） |
| 可信度 | 中（依赖文档准确性） | 高（代码级证据，可复现） |
| 耗时 | 秒级 | 分钟-小时级 |
| 适用场景 | 熟悉项目内调研、快速补课 | 新项目深度调研、关键决策验证、架构对标 |

### 5.2 重型逆向调研工作流

```
新项目/开源项目调研
        │
        ▼
┌─────────────────────────────────────┐
│  阶段 1：轻量文档调研（建立框架）     │
│  • RAG 检索已有认知                  │
│  • 读 README / 架构文档              │
│  • 形成初步假设                       │
└──────────────────┬──────────────────┘
                   │ 初步假设
                   ▼
┌─────────────────────────────────────┐
│  阶段 2：重型逆向调研（验证假设）     │
│  • 33-REA investigate(target)       │
│  • recover_decisions(target)        │
│  • abstract_methodology(target)     │
│  • 生成五层证明链                    │
└──────────────────┬──────────────────┘
                   │ 证明链
                   ▼
┌─────────────────────────────────────┐
│  阶段 3：双向验证（正向 vs 逆向）     │
│  • 文档声称的架构 vs 代码还原的架构   │
│  • 不一致 → 标记 known_gaps          │
│  • 一致 → 证明链置信度 +              │
└──────────────────┬──────────────────┘
                   │ 验证后的证明链
                   ▼
┌─────────────────────────────────────┐
│  阶段 4：沉淀（写入认知系统）         │
│  • record(证明链) → Evidence Index   │
│  • 方法论入库知识库（RAG 可检索）     │
│  • 后续调研可 recall 复用             │
└─────────────────────────────────────┘
```

### 5.3 新项目调研的安全边界（v2.0 明定）

经调研，33-REA 的 `investigate(target, feature, entry)` **已支持任意路径**（`investigation_workflow.py:497`），`trace_git_history(repo_path, target_path)` 显式接收 repo_path。但：
- Local-only / read-only 在代码层**未强制**（靠 Trae sandbox 兜底）
- workflow 内部可能隐式假设 dreambuddy-v2 结构（SKILL 目录、4-MEMORY），分析任意项目时依赖图/入口检测会失准

**v2.0 约束**：
- 外部项目调研需显式声明 `external_project: true`
- 33-REA 需适配外部项目的目录结构探测（不假设 SKILL/4-MEMORY 存在）
- 调研产出隔离存储（不写入 dreambuddy 自身认知库，除非显式 approve）

### 5.4 新项目调研的 PoE 门禁

新项目调研产出的**调研报告**也需过 PoE 门禁：
- **Evidence 层**：每条架构结论必须有代码级证据（file:line）
- **Design Decision 层**：还原目标项目的设计决策（为什么这么设计）
- **Methodology 层**：抽象出可迁移到 dreambuddy 的方法论
- **Audit 层**：调研报告的证明链完整度得分

**门禁**：
- `poe_score ≥ 0.7` → 调研报告可信，可作为决策依据
- `0.4 ≤ poe_score < 0.7` → 需人工补充验证
- `poe_score < 0.4` → 调研不充分，需重新逆向

---

## 6. 正向-逆向闭环（用户新想法 3）

### 6.1 闭环定义

```
正向（设计→实现）：
  设计意图 → 代码实现 → 文档/SKILL → 认知记忆

逆向（实现→设计）：
  代码 → 33-REA 还原 → 设计决策 → 方法论 → 认知记忆

闭环校验：
  正向产出的"设计意图" vs 逆向还原的"设计决策"
  一致 → 证明链置信度提升
  不一致 → 标记认知债务，触发修正
```

### 6.2 闭环的轻重两类结合

| 闭环类型 | 正向 | 逆向 | 校验方式 |
|---|---|---|---|
| **轻量闭环** | SKILL 文档描述 | recall 检索已有记忆 | 文档 vs 记忆一致性 |
| **重型闭环** | 设计文档 + 注释 | 33-REA 代码级还原 | 文档 vs 代码证据一致性 |

**结合策略**：
- 日常迭代：轻量闭环（快速筛查文档与记忆的一致性）
- 关键模块/新项目：重型闭环（代码级证据验证设计意图）
- 重大变更后：先轻量筛查，发现不一致再升级为重型

### 6.3 闭环触发时机

| 事件 | 触发闭环类型 |
|---|---|
| AI 代码合入 | 重型闭环（33-REA 审计 vs 设计文档） |
| 认知记忆 verify | 轻量闭环（记忆 vs SKILL 文档） |
| 新项目调研 | 重型闭环（代码 vs 文档） |
| SKILL 更新 | 轻量闭环（SKILL vs 认知记忆） |
| 定期巡检（如每周） | 轻量筛查 + 发现问题升级重型 |

---

## 7. 实现优先级（v2.0 调整）

### P0（立即，认知侧简化 + 并发安全）

- [ ] **P0-1**: `_check_poe_trust()` 改为索引查询（移除每次全量验证）
- [ ] **P0-2**: 新增 `evidence_ledger.verify_receipt_exists(entry_id)` O(1) 查询
- [ ] **P0-3**: recall 路径只查 receipt 存在性，不跑全量验证
- [ ] **P0-4**: ❌ **v2.0 移除**（原"100 次跑全量"机制，依赖 P1-3 信任失效条件）
- [ ] **P0-5**: ✅ **v2.0 新增**——SQLite WAL 模式 + 计数器落库（前置并发安全）
- [ ] **P0-6**: ✅ **v2.0 新增**——启动时跑一次全量验证（健康检查）

> **依赖倒置修正**：v1.0 的 P0-4（100 次跑全量）安全网本质是 P1-3（信任失效条件）。v2.0 将 P0-4 移除，P0 先只做"启动时全量 + 日常只查 receipt"，信任失效条件（P1-3）同批次推进，避免间隙期"可信但实际已失效"。

### P1（短期，有界信任传递）

- [ ] **P1-1**: `poe_mode` 选择器实现（heavy/light/sample）
- [ ] **P1-2**: 有界信任传递机制（已验证产出的后续调用降级为抽样）
- [ ] **P1-3**: 6 信任失效条件（代码变更/verify失败/超时分级/依赖指纹/scope漂移/抽样重验）
- [ ] **P1-4**: ✅ **v2.0 新增**——`prepare_decision_record_params` / `prepare_audit_record_params` 补齐 `evidence_entries` 字段
- [ ] **P1-5**: ✅ **v2.0 新增**——EvidenceEntry 新增 `git_commit_hash` 列

### P2（中期，新项目调研）

- [ ] **P2-1**: 33-REA `investigate()` 适配外部项目结构（不假设 dreambuddy 目录）
- [ ] **P2-2**: 新项目调研工作流 SKILL（轻量→重型→双向验证→沉淀）
- [ ] **P2-3**: 调研报告的 PoE 门禁（poe_score ≥ 0.7）
- [ ] **P2-4**: 外部项目调研隔离存储（不写 dreambuddy 认知库，除非 approve）

### P3（长期，正向-逆向闭环）

- [ ] **P3-1**: 轻量闭环（文档 vs 记忆一致性校验）
- [ ] **P3-2**: 重型闭环（代码 vs 设计文档一致性）
- [ ] **P3-3**: 定期巡检触发器（轻量筛查 + 升级机制）

---

## 8. 与现有文档的关系 + 待落地清单

### 8.1 文档关系

| 现有文档 | 本 SPEC 的关系 |
|---|---|
| [DESIGN-PHILOSOPHY-PoE.md](../33-REA逆向解析工程/DESIGN-PHILOSOPHY-PoE.md) v1.1 | 保留，作为重型 PoE 的详细设计（区块链类比作为沟通隐喻保留，不作为安全保证） |
| [SPEC-工程实践复现器.md](../33-REA逆向解析工程/SPEC-工程实践复现器.md) v0.3 | 保留，作为 33-REA 侧的实现 SPEC |
| [SPEC-CognitiveSystem-Evolution.md](./SPEC-CognitiveSystem-Evolution.md) | 认知侧 PoE 部分按本 SPEC §3 简化 |
| 本 SPEC | **统一顶层框架**，定义双模式 + 有界信任传递 + 闭环 |

### 8.2 五大系统协同——已落地 vs 待落地（v2.0 去空话）

经调研，原 SPEC §3.2 的五大系统协同点中，部分是"空话"。v2.0 明确区分：

| 集成点 | 状态 | 说明 |
|---|---|---|
| 认知系统 record/verify/recall | ✅ 已实现 | `_check_poe_trust` 34 处引用 |
| 知识库 RAG 向量化证明链 | ⏳ 待落地 | SPEC-CognitiveSystem-Evolution §0.2 P0-2 自认"record 不触发 RAG" |
| SKILL 治理 poe_score 字段 | ⏳ 待落地 | 1-ARCHITECTURE 下 0 处 poe_score 引用 |
| 文档管理 doc_coverage 校验 | ⏳ 待落地 | 0-系统文档管理下 0 处 poe 引用 |
| 索引系统 verify_receipt_exists | ⏳ 待落地 | 仅存在于 SPEC，无实现 |

> **v2.0 约束**：待落地的 4 个集成点不作为"已实现能力"宣传，移入 P3+ 待落地清单。

### 8.3 "同一会话"定义（v2.0 明定 Q1）

经调研，`.cognitive/sessions/` 目录存在但未接入 PoE。v2.0 明确定义：
- **"同一会话" = 进程级 + 时间窗口（默认 1 小时）**
- 不依赖 `.cognitive/sessions/`（该目录未接入 PoE）
- 进程退出或超 1 小时 → 信任降级为轻量验证

---

## 9. 开放问题（v2.0 更新）

- [x] **Q1**: 信任传递的"同一会话"如何定义？→ **v2.0 已定**：进程级 + 1 小时窗口（§8.3）
- [ ] **Q2**: 新项目调研时，33-REA 分析外部项目的隐式假设（dreambuddy 目录结构）如何适配？（§5.3 已部分回答，待 P2-1 落地验证）
- [ ] **Q3**: 正向-逆向闭环的"一致性"如何量化？（完全匹配？关键路径匹配？）
- [ ] **Q4**: 轻量闭环的触发频率？（每次 verify？定时？事件驱动？）
- [x] **Q5**: 信任有效期是否分级？→ **v2.0 已定**：按产出类型分级（代码 1 天 / 文档 30 天，§2.3 失效条件 #3）
- [ ] **Q6**: **v2.0 新增**——dirty tree（未提交改动）是否触发信任失效？
- [ ] **Q7**: **v2.0 新增**——33-REA 分析外部项目时 git hash 取的是哪个 repo？

---

## 10. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| 1.0 | 2026-10-11 | 初始版本：统一双层级 + 双模式 + 信任传递 + 新项目调研 + 正向-逆向闭环 |
| 2.0 | 2026-10-11 | 经 4 维度调研修正：剥离区块链隐喻（PoW/PoS/slash/Merkle）→ 保留工程实质；信任传递改有界传递（6 失效条件 + 抽样重验）；P0 优先级调整（移除 100 次机制，新增 WAL + 计数器落库）；跨系统协同去空话（4 集成点移入待落地清单）；enforcement/mode 正交关系明定；补齐 decision/audit 写入字段；明定"同一会话"定义 |

---

## 11. 调研依据（v2.0 修正的 4 维度评估）

本 SPEC v2.0 的修正基于以下 4 维度并行调研结论：

### 11.1 架构合理性 + 范式对比

- 业界 SLSA（OpenSSF）4 级供应链保证，**明确拒绝传递性**（防 SolarWinds 式依赖链攻击）
- C2PA / SynthID / Claude watermark 聚焦内容溯源，不验证正确性
- Aider git-blame 极轻量（git metadata）
- PoE 五层证明链自定义复杂度远超业界共识，但优势在"语义级证明"（设计决策+方法论）
- **修正应用**：信任传递改为有界传递 + 依赖指纹 + 抽样重验（§2.3）

### 11.2 区块链类比严谨性（Devil's Advocate）

- **PoW 陷阱**：PoE 伪造证明链成本低于真实分析（不对称性倒置）
- **PoS 陷阱**：Agent 信用分无真实资产抵押，5 次 +0.01 PASS 即回本，新建 Agent ID 重置（女巫攻击零成本）
- **SPV 盲区**：receipt 写入者=证明链生成者同一方，无独立激励背书
- **Merkle 威胁模型不成立**：本系统单信任方自审计，无拜占庭威胁，git commit hash 已是链式哈希
- **修正应用**：剥离区块链术语，Evidence Ledger → Evidence Index（§2.1），Agent 信用 → Agent 声誉（非 PoS）

### 11.3 工程落地可行性

- SPV 简化改动小（~3 处 + 1 个新方法）
- **并发坑**：当前 `threading.RLock` 仅进程内同步，多进程不共享计数器；SQLite 未开 WAL
- **git hash 绑定缺口**：EvidenceEntry 无 `git_commit_hash` 列
- 33-REA `investigate()` 已支持任意路径，但隐式假设 dreambuddy 结构
- **依赖倒置**：P0-4（100 次跑全量）安全网实为 P1-3（信任失效条件）
- **修正应用**：P0 调整（§7），并发安全前置（§3.2），git hash 绑定（P1-5）

### 11.4 跨系统协同冲突

- `prepare_decision_record_params` / `prepare_audit_record_params` **缺 evidence_entries 字段**（真实冲突）
- enforcement(soft/strict/off) vs mode(heavy/light/skip) 关系未定义（边界模糊）
- 五大系统协同 4 个集成点是空话（RAG/SKILL poe_score/doc_coverage/verify_receipt_exists）
- "同一会话" vs `.cognitive/sessions/` 未对齐（真实缺口）
- **修正应用**：写入路径统一（§4.2），enforcement/mode 正交（§3.3），去空话（§8.2），"同一会话"明定（§8.3）
