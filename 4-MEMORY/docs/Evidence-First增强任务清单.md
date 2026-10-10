# 方向1-1：Evidence-First 增强认知记忆系统

> **来源**: REA逆向工程思维三方向调研（2026-10-10）
> **REA借鉴**: Evidence-First — 每条结论带 provenance + confidence + known_gaps
> **目标系统**: 4-MEMORY 认知记忆系统
> **状态**: 待实施

---

## 1. 现状分析

当前 `record` 工具签名：
```
record(content="经验内容", quality_level="B", tags="标签1,标签2")
```

**已有**：
- `quality_level`（S/A/B/C/D 离散等级）
- `tags`（标签）
- `source`（来源标识，默认"mcp"，在 [cognitive_mcp_server.py L291](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/9-工具与接口/cognitive_mcp_server.py#L291)）
- `verify` 贝叶斯置信度更新

**缺失（对比REA Evidence结构）**：
1. 无4层事实分级（observation/derivation/inference/unknown）
2. 无连续 `confidence_score`（0.0-1.0），只有离散等级（当前 `confidence=0.3` 硬编码，见 [L298](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/9-工具与接口/cognitive_mcp_server.py#L298)）
3. 无 `known_gaps` 字段（已知局限）
4. 无 `observations` 支撑观察列表
5. 无详细 `provenance` 结构（现有只有 `source` 字符串，缺少文件路径/行号/引擎等详细来源）
6. `verify` 只更新置信度，不更新 `known_gaps`

---

## 2. 增强任务

### T1.1 扩展 record 工具参数（P0）

**目标**：增加4层事实分级 + 连续置信度 + known_gaps + observations，向后兼容。

**涉及文件**：
- `4-MEMORY/9-工具与接口/cognitive_mcp_server.py`（record工具定义）
- 记忆数据库 schema（`4-MEMORY/data/cognitive_memory.db`）

**改动**：
```python
# 新签名（可选参数，向后兼容）
record(
    content: str,
    quality_level: str = "B",           # 保留，作为confidence_level标签
    tags: str = "",
    level: str = "observation",          # 新增: observation/derivation/inference/unknown
    confidence_score: float = None,      # 新增: 0.0-1.0 连续值
    known_gaps: list[str] = None,        # 新增: 已知局限
    observations: list[dict] = None,     # 新增: 支撑观察
)
```

**数据库迁移**：
- memory表增加 `level`、`confidence_score`、`known_gaps`（JSON）、`observations`（JSON）字段
- 旧记录 `level=derivation`，`confidence_score` 从 quality_level 映射（S=0.95, A=0.70, B=0.40, C=0.20, D=0.10）

**验收**：
- 旧调用 `record(content="x", quality_level="B", tags="y")` 正常工作
- 新调用可传入 level/confidence_score/known_gaps/observations
- 数据库迁移不丢数据

### T1.2 verify 工具增强（P1）

**目标**：verify 不仅更新置信度，还更新 known_gaps。

**改动**：
```python
verify(
    memory_id: str,
    success: bool,
    known_gaps_update: list[str] = None,  # 新增: 验证后局限缩小
)
```

**逻辑**：
- `success=True` 且提供 `known_gaps_update` → 用新列表替换旧 known_gaps（验证后局限可能缩小）
- `success=False` → known_gaps 不变（失败不缩小局限）

**验收**：verify 后 known_gaps 可被更新

### T1.3 recall 结果增强（P1）

**目标**：recall 返回结果包含 level/confidence_score/known_gaps，帮助调用方判断证据质量。

**改动**：
- recall 返回的每条 memory 增加 `level`、`confidence_score`、`known_gaps` 字段
- 检索排序可按 `confidence_score` 加权

**验收**：recall 结果包含新字段

### T1.4 硬约束记忆闸门适配（P1）

**目标**：CLAUDE.md 中的硬约束记忆闸门（关键词命中后30秒内record）适配新字段。

**改动**：
- 硬约束记忆默认 `level=derivation`，`confidence_score=0.7`（B级对应）
- 强制 `known_gaps` 非空（即使是 `["未经验证"]`）

**验收**：硬约束记忆入库时带 known_gaps

---

## 3. 与 33-REA 的关系

33-REA 工程的 `core/evidence.py` 定义了 `Evidence` 数据结构（4层事实分级）。本任务是将同样的 Evidence-First 理念应用到认知记忆系统的 `record` 工具，使两条证据链（工程逆向证据 + 认知记忆证据）统一。

---

## 4. 实施顺序（TDD）

每个任务遵循 **RED → GREEN → REFACTOR** 循环：

### T1.1 record参数扩展 + 数据库迁移（P0，1天）
- **RED**：写测试断言 `record(content="x", level="derivation", confidence_score=0.8, known_gaps=["g1"])` 返回的 memory 包含新字段
- **GREEN**：扩展 `_handle_record` + inputSchema + 数据库迁移脚本
- **REFACTOR**：新参数提取为独立函数，数据库操作用事务包裹

### T1.2 verify增强（P1，0.5天）
- **RED**：写测试断言 `verify(memory_id, success=True, known_gaps_update=["g2"])` 后 memory.known_gaps 被更新
- **GREEN**：扩展 `_handle_verify` + verify 方法
- **REFACTOR**：known_gaps 更新逻辑独立

### T1.3 recall结果增强（P1，0.5天）
- **RED**：写测试断言 recall 返回的每条 memory 包含 level/confidence_score/known_gaps
- **GREEN**：扩展 `_handle_recall` 返回字段
- **REFACTOR**：返回字段序列化统一

### T1.4 硬约束闸门适配（P1，0.5天）
- **RED**：写测试断言硬约束记忆入库时 known_gaps 非空
- **GREEN**：CLAUDE.md 闸门逻辑适配
- **REFACTOR**：闸门校验提取为独立函数

---

## 5. 风险

| 风险 | 应对 |
|---|---|
| 数据库迁移影响现有记忆 | 先备份，迁移脚本可回滚 |
| 旧调用方不传新参数 | 新参数全部可选，默认值合理 |
| known_gaps 强制非空增加调用负担 | 默认为 `[]`，硬约束场景才强制 |
