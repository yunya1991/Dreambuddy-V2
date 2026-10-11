# 跨系统协作接口契约 — COLLABORATION-CONTRACT

> **版本**: v1.0 | **更新日期**: 2026-10-11
> **定位**: 广义认知系统各子系统间协作调用的**接口契约**（权威定义）
> **SSoT 层级**: L1（协作接口层），各子系统实现必须遵循
> **关联**: [SPEC-CognitiveSystem-Evolution.md](./SPEC-CognitiveSystem-Evolution.md) §2 L1基础层接线 + [SPEC-Unified-PoE-Framework.md](./SPEC-Unified-PoE-Framework.md) §2.3 有界信任传递

---

## 0. 契约边界

本契约定义跨系统协作的接口约定，**不含实现**。各子系统按契约在自己的代码层实现。

| 契约 | 定义方 | 实现方 | 状态 |
|---|---|---|---|
| record_hook / verify_hook | 本契约 | 4-MEMORY/cognitive_mcp_server.py + 33-REA/skill_indexer.py | P0-1 已接线 |
| Evidence Ledger 接入 | 本契约 | 4-MEMORY/cognitive_loop_entry.py + evidence_ledger.py | P1-L1-1 已落地 |
| PoE 信任机制 | 本契约 | 4-MEMORY/cognitive_loop_entry.py._check_poe_trust | P1-L1-2b 已落地 |
| 33-REA → Ledger → record 闭环 | 本契约 | 33-REA/cognitive_integration.py + 4-MEMORY | P1-L1-3 已落地 |

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

**状态**: ⏳ 待补齐 `evidence_entries` 字段（P1-4 任务）

---

## 4. P0 落地待办（契约层待实现项）

| 项 | 契约 | 当前状态 | 落地方 |
|---|---|---|---|
| P0-1 | _check_poe_trust 改索引查询（移除全量 verify_integrity） | ✅ 已落地（get_receipt_for O(log N)） | 4-MEMORY/cognitive_loop_entry.py |
| P0-2 | verify_receipt_exists(entry_id) O(1) 查询 | ✅ 已落地 | 4-MEMORY/evidence_ledger.py |
| P0-5 | SQLite WAL 模式 + 计数器落库 | ✅ 已落地（WAL + ledger_counters + increment_counter） | 4-MEMORY/evidence_ledger.py |
| P0-6 | 启动时全量验证（健康检查） | ✅ 已落地（_startup_integrity_passed + 计数器） | 4-MEMORY/cognitive_loop_entry.py |
| P1-3 | 6 信任失效条件 | ✅ 已落地（trust_state 表 + check_trust_validity + 6 失效条件） | 4-MEMORY/evidence_ledger.py |
| P1-4 | prepare_decision/audit_record_params 补 evidence_entries | 缺失 | 33-REA/cognitive_integration.py |
| P1-5 | EvidenceEntry 新增 git_commit_hash 列 | ✅ 已落地（含 schema migration） | 4-MEMORY/evidence_ledger.py |

---

## 5. 修订记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-10-11 | 初始版本：从散落 SPEC 收敛 + 定义 4 类协作契约 |
| v1.1 | 2026-10-11 | P0 落地完成：P0-1/2/5/6 全部 ✅（_check_poe_trust 索引查询 + verify_receipt_exists + WAL + 启动健康检查） |
| v1.2 | 2026-10-11 | P1 批次1+2 落地：P1-1 poe_mode + P1-2 sample 10% + P1-3 六失效条件 + P1-5 git_commit_hash 全部 ✅（P1-4 待补） |
