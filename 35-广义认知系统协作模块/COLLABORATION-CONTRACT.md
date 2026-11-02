# 跨系统协作接口契约 — COLLABORATION-CONTRACT

> **版本**: v1.5 | **更新日期**: 2026-11-02
> **定位**: 广义认知系统各子系统间协作调用的**接口契约**（权威定义）
> **SSoT 层级**: L1（协作接口层），各子系统实现必须遵循
> **关联**: [SPEC-CognitiveSystem-Evolution.md](./SPEC-CognitiveSystem-Evolution.md) §2 L1基础层接线 + [SPEC-Unified-PoE-Framework.md](./SPEC-Unified-PoE-Framework.md) §2.3 有界信任传递 + [SYSTEM_ARCHITECTURE_OVERVIEW v4.1](../1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md) §1.7 L0 统一出口层

---

## 0. 契约边界

本契约定义跨系统协作的接口约定，**不含实现**。各子系统按契约在自己的代码层实现。

| 契约 | 定义方 | 实现方 | 状态 |
|---|---|---|---|
| record_hook / verify_hook | 本契约 | 4-MEMORY/cognitive_mcp_server.py + 33-REA/skill_indexer.py | P0-1 已接线 |
| Evidence Ledger 接入 | 本契约 | 4-MEMORY/cognitive_loop_entry.py + evidence_ledger.py | P1-L1-1 已落地 |
| PoE 信任机制 | 本契约 | 4-MEMORY/cognitive_loop_entry.py._check_poe_trust | P1-L1-2b 已落地 |
| 33-REA → Ledger → record 闭环 | 本契约 | 33-REA/cognitive_integration.py + 4-MEMORY | P1-L1-3 已落地 |
| 认知 MCP 工具面（读/写 scope + 信封） | 本契约 §5 | 4-MEMORY/cognitive_mcp_server.py | v1.4 新增（口径先行，scope 实现待落地） |

---

## 1. record_hook / verify_hook 契约

### 1.1 record_hook

**触发**: `cognitive_mcp_server._handle_record` 末尾，当 tags 含 "SKILL" 时调用。

```python
# 契约签名
skill_indexer.record_hook(
    skill_id: str,       # 从 content 提取的 SKILL ID
    memory_id: str,      # record() 返回的记忆 ID
    skill_dir: str,      # SKILL 目录路径
)
```

**契约约束**:
- FAIL-OPEN: hook 失败不阻塞 record 主流程
- 幂等: 同一 memory_id 重复调用不产生重复记录

### 1.2 verify_hook

**触发**: `cognitive_mcp_server._handle_verify` 末尾调用。

```python
skill_indexer.verify_hook(
    memory_id: str,      # 被 verify 的记忆 ID
    success: bool,       # verify 结果
)
```

**契约约束**:
- FAIL-OPEN: hook 失败不阻塞 verify 主流程
- verify(success=False) 触发 SKILL drift 检测

---

## 2. Evidence Ledger 接入契约

### 2.1 record → Ledger

**触发**: `cognitive_loop_entry.record()` 末尾追加 EvidenceEntry。

```python
# 契约
EvidenceEntry(
    subject="record",              # 固定标识来源
    relation="调用了",              # 决策关系
    object=memory_id,              # 被记录的记忆 ID
    source="cognitive_loop_entry.record",  # 来源
    confidence=0.5,                # 置信度
    level="observation",           # 事实分级
)
# append() 返回 receipt_hash
```

**契约约束**:
- FAIL-OPEN: Ledger 写入失败返回空 receipt，不阻塞 record
- receipt_hash 非空 = 写入成功

### 2.2 verify → PoE 信任查询

**触发**: `cognitive_loop_entry.verify()` 开头查询。

```python
# 契约
poe_trust, receipt_hash = _check_poe_trust(memory_id)
# 返回 (bool, Optional[str])
```

**enforcement 模式**（三模式正交）:
| mode | enforcement | 无 receipt 行为 |
|---|---|---|
| light | soft | 不阻塞，质量上限 B + recall 降权 0.5 |
| light | strict | verify 直接失败（硬阻塞） |
| light | off | 不检查 |
| heavy | N/A | 跑五层证明链（33-REA 侧） |
| sample | 沿用上次 | 10% 概率重跑 light |

### 2.3 recall → PoE 降权

**触发**: recall 结果返回前，对每条结果查 receipt。

```python
# 契约
has_receipt, _ = _check_poe_trust(memory_id)
# soft: 无 receipt → score *= 0.5 + poe_penalized=True
# strict: 无 receipt → 从结果过滤
```

---

## 3. 33-REA → Ledger → record 闭环契约

### 3.1 prepare_record_params

**触发**: 33-REA `investigate()` 完成后，Agent 调用 record 前。

```python
# 契约
params = prepare_record_params(investigation)
# 返回 {
#   "content": str,              # 格式化的记忆内容
#   "quality_level": "B",        # 默认 B 级
#   "tags": str,                 # 逗号分隔标签
#   "evidence_entries": list[dict],  # 33-REA Evidence → EvidenceEntry dict
# }
```

**契约约束**:
- 每个 evidence_entry 可被 `EvidenceEntry(**dict)` 构造
- Agent 走 `record()` 一条路径写认知库 + Ledger，不另开写入路径

### 3.2 prepare_decision_record_params / prepare_audit_record_params

**状态**: ✅ 已落地（P1-4 已补齐 `evidence_entries` 字段）

```python
# 契约
params = prepare_decision_record_params(decision_result)
params = prepare_audit_record_params(audit_result)
# 返回 {
#   "content": str,
#   "quality_level": "B",  # audit 按 gate 映射 pass→A/review→B/reject→C
#   "tags": str,
#   "evidence_entries": list[dict],  # P1-4: Evidence → EvidenceEntry dict
# }
```

**契约约束**:
- 与 §3.1 prepare_record_params 保持一致，调用 `_convert_evidence_to_entries(result)` 转换
- 无 evidence 时返回 `[]`（非 None / 非缺失键）
- 每个 entry 可被 `EvidenceEntry(**dict)` 构造

---

## 4. P0 落地待办（契约层待实现项）

| 项 | 契约 | 当前状态 | 落地方 |
|---|---|---|---|
| P0-1 | _check_poe_trust 改索引查询（移除全量 verify_integrity） | ✅ 已落地（get_receipt_for O(log N)） | 4-MEMORY/cognitive_loop_entry.py |
| P0-2 | verify_receipt_exists(entry_id) O(1) 查询 | ✅ 已落地 | 4-MEMORY/evidence_ledger.py |
| P0-5 | SQLite WAL 模式 + 计数器落库 | ✅ 已落地（WAL + ledger_counters + increment_counter） | 4-MEMORY/evidence_ledger.py |
| P0-6 | 启动时全量验证（健康检查） | ✅ 已落地（_startup_integrity_passed + 计数器） | 4-MEMORY/cognitive_loop_entry.py |
| P1-3 | 6 信任失效条件 | ✅ 已落地（trust_state 表 + check_trust_validity + 6 失效条件） | 4-MEMORY/evidence_ledger.py |
| P1-4 | prepare_decision/audit_record_params 补 evidence_entries | ✅ 已落地（_convert_evidence_to_entries 复用） | 33-REA/cognitive_integration.py |
| P1-5 | EvidenceEntry 新增 git_commit_hash 列 | ✅ 已落地（含 schema migration） | 4-MEMORY/evidence_ledger.py |

---

## 5. 认知 MCP 工具面契约

> **定位**：定义认知系统对外暴露的 MCP 工具面**读/写边界与调用约束**。这是跨系统（DSH Worker / Trae / 云端 Agent / 前端）调用认知能力的唯一契约来源。
> **背景**：L0 对外采用 port / MCP 双通道（SSoT §1.7）；MCP 面按能力域封装后，**写工具若不加约束，多 agent 并发写会放大认知污染**。

### 5.1 工具面清单与读/写分级

| 工具 | 读/写 | 默认可用 | scope | 说明 |
|---|---|---|---|---|
| `recall` | 读 | ✅ | `read` | 经验检索 |
| `unified_search` | 读 | ✅ | `read` | 统一检索（含 41 号域索引） |
| `stats` / `health` / `l4_status` | 读 | ✅ | `read` | 状态与健康 |
| `record` | **写** | ❌ 默认禁用 | `write` | 写入记忆（落库前过 45 门禁的通道除外） |
| `verify` | **写** | ❌ 默认禁用 | `write` | 置信度更新（触发蒸馏链） |

> **存量第三面（39-金融语义，D6 归 Search 语义面）**：`query_entity`／`semantic_lookup` 为读，`distill_aliases`／`training_feed` 为写；写工具同样默认禁用，受 §5.2 全部约束。

**约束**：写工具必须由调用方显式携带 `write` scope，且 scope 来源是 **Ticket Mandate 的工具授权字段**（SSoT §1.8），不得由调用方自行声明。

### 5.2 调用约束（硬约束）

| # | 约束 |
|---|---|
| C1 | **统一信封**：返回须为 `ok / data / source / timestamp / degraded(reason) / meta`；MCP 层 error/timeout **不等于** `degraded`；源可达无数据 = `ok + data=None` |
| C2a | **FAIL-OPEN（仅增强型能力）**：recall 先验／投机预取等**非主功能**不可用时，调用方返回空（如 `[]`）并继续主流程，**但须标 `degraded=true`**；不得抛出中断 |
| C2b | **主功能禁止 FAIL-OPEN**：统一检索／数据查询／评测裁决不可用时**必须**返回 `ok=false + error_code=unavailable`，禁止把故障伪装成「无结果」（44 SPEC-L0 §3.1 硬规则） |
| C3 | **写幂等**：写工具须以 `external_id` 幂等（沿用 C8 job_runs 回调先例），重复调用不产生重复记录 |
| C4 | **trace 贯穿**：调用须透传 `trace_id`，落 `dreamos_sessions`／`dreamos_spans` |
| C5 | **写门禁**：`record`／`verify` 的结果若用于沉淀或上线，须先过 45 评测门禁（shadow 期仅记录） |
| C6 | **主体（principal）必填**：`principal ∈ {worker, orchestrator, verifier, admin}`；**Worker 默认只读**，写工具的 principal 必须为 `orchestrator`／`verifier`；`settle` 由编排侧执行（G1/B2 定稿） |
| C7 | **工具声明**：只读工具 `readOnlyHint=true`；写工具 `readOnlyHint=false + destructiveHint` 视语义（供宿主侧刻意拦截） |

### 5.3 与其他契约的关系

- §1 `record_hook` / `verify_hook`：仍在写工具**内部**触发，scope 化不改变其触发点与幂等要求。
- §2 Evidence Ledger：写工具的每次调用都产生 `EvidenceEntry`，`receipt_hash` 作为证据边界供 45 与 A 层 `evidence_backed` 验收消费。
- **边界**：本契约只管「谁能写、怎么写」；**分域聚合粒度与部署形态不属于本契约**（见 46-DSH架构评估报告）。

---

## 6. 修订记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-10-11 | 初始版本：从散落 SPEC 收敛 + 定义 4 类协作契约 |
| v1.1 | 2026-10-11 | P0 落地完成：P0-1/2/5/6 全部 ✅（_check_poe_trust 索引查询 + verify_receipt_exists + WAL + 启动健康检查） |
| v1.2 | 2026-10-11 | P1 批次1+2 落地：P1-1 poe_mode + P1-2 sample 10% + P1-3 六失效条件 + P1-5 git_commit_hash 全部 ✅（P1-4 待补） |
| v1.3 | 2026-10-11 | P1-4 落地：prepare_decision/audit_record_params 补 evidence_entries（复用 _convert_evidence_to_entries），P1 全部 ✅ |
| v1.5 | 2026-11-02 | 按 ALIGNMENT-46-47 决议修订 §5：C2 拆 C2a/C2b（增强型可 FAIL-OPEN / 主功能禁止）、新增 C6 principal 矩阵与 C7 tool annotations、登记 39 存量第三面写工具 |
| v1.4 | 2026-11-02 | 新增 §5「认知 MCP 工具面契约」：读/写分级（record/verify 默认禁用，挂 write scope，授权来自 Ticket Mandate）+ 5 条调用约束（信封/FAIL-OPEN/幂等/trace/45 门禁）+ 与其他契约关系；对齐 SSoT v4.1 §1.7/§1.8 |
