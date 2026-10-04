# SPEC-20260930 — 认知 TAG_HOOKS 三大闭环自动化

> **版本**: v1.0 | **日期**: 2026-09-30 | **状态**: 待实现
> **作者**: TRAE Agent | **关联**: CLAUDE.md L65-73 / dream-doc-sync-workflow / wiki-ingest-trigger / dream-self-iteration-workflow

---

## 1. 背景与问题

### 1.1 文档承诺 vs 代码现实

三个 SKILL 文档和 CLAUDE.md 均声称存在 TAG_HOOKS 自动触发机制：

| 文档位置 | 声称行为 |
|----------|---------|
| CLAUDE.md L73 | `record tags 含 doc-sync 时，cognitive_mcp_server.py 的 TAG_HOOKS 自动返回 triggered_skills: ["dream-doc-sync-workflow"]` |
| dream-doc-sync-workflow SKILL §一.2 | `认知系统 record 时 tags 含 doc-sync，自动触发同步` |
| wiki-ingest-trigger SKILL | `record tags contain wiki-compile, TAG_HOOKS emits triggered_skills: [wiki-ingest-trigger]` |
| dream-self-iteration-workflow SKILL §2 | `hermes 反思 → record(tags="hermes反思,SKILL") → 触发 skill-creator` |

**实际代码**（`4-MEMORY/9-工具与接口/cognitive_mcp_server.py` L240-259）：

```python
def _handle_record(args: Dict[str, Any]) -> str:
    # ... 提取 content/quality_level/tags/source ...
    memory_id = _get_cle().record(...)
    return json.dumps({
        "memory_id": memory_id,
        "status": "recorded",
    }, ensure_ascii=False)  # ← 无 triggered_skills 字段
```

**结论**：TAG_HOOKS 是文档描述但代码未实现的 gap。三大闭环当前均为"手动闭环"（依赖 agent 读取 tags 并手动调用 SKILL），非"自动闭环"。

### 1.2 影响范围

| 闭环能力 | 当前状态 | 影响 |
|----------|---------|------|
| 文档同步 | 手动触发 | agent 遗忘则索引断链累积 |
| 认知经验回补 | 手动触发 | 有价值经验不自动回补到 SKILL 执行 |
| hermes 反思 SKILL 创建 | 手动触发 | 反思成果不自动形成 SKILL，经验流失 |

---

## 2. 目标

### 2.1 核心目标

在 `cognitive_mcp_server.py` 的 `_handle_record` 中实现 TAG_HOOKS 机制，使 `record` 返回值包含 `triggered_skills` 字段，驱动三大闭环自动化。

### 2.2 非目标

- 不修改 `recall`/`verify`/`stats`/`health` 的返回格式
- 不修改 `VectorMemoryInterface` 或 `CognitiveLoopEntry` 的核心逻辑
- 不实现 SKILL 的自动加载执行（由 TRAE Agent 读取 `triggered_skills` 后决定加载）
- 不引入外部依赖（纯 Python 标准库实现）

---

## 3. 架构设计

### 3.1 TAG_HOOKS 映射表

```python
TAG_HOOKS: Dict[str, List[str]] = {
    # 文档同步闭环
    "doc-sync": ["dream-doc-sync-workflow"],
    # Wiki 编译闭环
    "wiki-compile": ["wiki-ingest-trigger"],
    # hermes 反思 → SKILL 创建闭环
    "hermes反思": ["dream-self-iteration-workflow"],
    "SKILL": ["skill-creator"],
    # 硬约束记忆（CLAUDE.md §3）
    "硬约束": ["dream-arch-collaboration-workflow"],
}
```

**设计原则**：
- **tag 精确匹配**：不做模糊匹配/正则，tag 字符串完全一致才触发
- **多 tag 叠加**：一条 record 可同时命中多个 hook（如 `tags="doc-sync,hermes反思"` → 触发两个 skill）
- **去重**：多 tag 映射到同一 skill 时只返回一次
- **FAIL-OPEN**：TAG_HOOKS 查询异常不阻塞 record 主流程

### 3.2 数据流

```
Agent 调用 record(content, tags="doc-sync,架构协同")
  ↓
_handle_record()
  ├── 1. 写入记忆（现有逻辑不变）
  ├── 2. 查询 TAG_HOOKS：tags ∩ TAG_HOOKS.keys → matched_hooks
  ├── 3. 收集 triggered_skills = dedup([skill for hook in matched_hooks for skill in TAG_HOOKS[hook]])
  └── 4. 返回 {memory_id, status, triggered_skills: [...]}
  ↓
Agent 读取 response.triggered_skills
  ├── 若非空 → 逐个 Skill 工具加载并执行对应 SKILL
  └── 若空 → 无自动触发，正常继续
```

### 3.3 三大闭环完整链路

#### 闭环1：文档同步自动闭环

```
编码任务完成 → record(tags="doc-sync")
  → TAG_HOOKS 返回 triggered_skills: ["dream-doc-sync-workflow"]
  → Agent 自动加载 dream-doc-sync-workflow SKILL
  → 执行 7 步：变更解析 → INDEX 更新 → 知识库更新 → doc_lint → doc_coverage → 飞书同步 → record(tags="doc-sync")
  → 闭环：下次 recall 可命中本次文档变更经验
```

#### 闭环2：认知经验回补自动闭环

```
发现新经验/反模式 → record(tags="硬约束,xxx域")
  → TAG_HOOKS 返回 triggered_skills: ["dream-arch-collaboration-workflow"]
  → Agent 自动加载 dream-arch-collaboration-workflow SKILL
  → SKILL 调用 recall 检索相关架构记忆 → 验证经验与架构一致性
  → 若需更新架构文档 → record(tags="doc-sync") → 触发闭环1
```

#### 闭环3：hermes 反思 SKILL 创建自动闭环

```
L4 自迭代周期触发 → HermesReflector.reflect(hours=24)
  → 反思发现可复用流程 → record(tags="hermes反思,SKILL")
  → TAG_HOOKS 返回 triggered_skills: ["dream-self-iteration-workflow", "skill-creator"]
  → Agent 自动加载 dream-self-iteration-workflow → 编排 L4 自迭代
  → Agent 自动加载 skill-creator → 创建新 SKILL
  → 新 SKILL 创建完成 → record(tags="doc-sync") → 触发闭环1（新 SKILL 入索引）
```

---

## 4. 实现方案

### 4.1 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `4-MEMORY/9-工具与接口/cognitive_mcp_server.py` | 修改 | 在 `_handle_record` 中添加 TAG_HOOKS 逻辑 |
| `4-MEMORY/9-工具与接口/tests/test_tag_hooks.py` | 新增 | TAG_HOOKS 单元测试 |

### 4.2 cognitive_mcp_server.py 变更

#### 4.2.1 新增 TAG_HOOKS 常量（模块级，`_handle_record` 上方）

```python
# ============================================================
# TAG_HOOKS — record tags → triggered_skills 自动映射
# 文档：CLAUDE.md L73 / dream-doc-sync-workflow SKILL §一.2
# 设计：tag 精确匹配，多 tag 叠加，去重，FAIL-OPEN
# ============================================================

TAG_HOOKS: Dict[str, List[str]] = {
    "doc-sync": ["dream-doc-sync-workflow"],
    "wiki-compile": ["wiki-ingest-trigger"],
    "hermes反思": ["dream-self-iteration-workflow"],
    "SKILL": ["skill-creator"],
    "硬约束": ["dream-arch-collaboration-workflow"],
}


def _resolve_triggered_skills(tags: List[str]) -> List[str]:
    """根据 record tags 查询 TAG_HOOKS，返回去重后的 triggered_skills 列表。

    FAIL-OPEN：任何异常返回空列表，不阻塞 record 主流程。
    """
    try:
        triggered: List[str] = []
        for tag in tags:
            tag = tag.strip()
            if tag in TAG_HOOKS:
                for skill in TAG_HOOKS[tag]:
                    if skill not in triggered:  # 去重
                        triggered.append(skill)
        return triggered
    except Exception:
        return []
```

#### 4.2.2 修改 `_handle_record`（L240-259）

```python
def _handle_record(args: Dict[str, Any]) -> str:
    content = args.get("content", "")
    quality_level = args.get("quality_level", "C")
    tags_str = args.get("tags", "")
    source = args.get("source", "mcp")

    tags = [t.strip() for t in tags_str.split(",")] if tags_str else []

    memory_id = _get_cle().record(
        content=content,
        quality_level=quality_level,
        confidence=0.3,
        tags=tags,
        source=source,
    )

    # TAG_HOOKS：查询 tags → triggered_skills（FAIL-OPEN）
    triggered_skills = _resolve_triggered_skills(tags)

    return json.dumps({
        "memory_id": memory_id,
        "status": "recorded",
        "triggered_skills": triggered_skills,
    }, ensure_ascii=False)
```

### 4.3 测试计划（test_tag_hooks.py）

```
测试文件：4-MEMORY/9-工具与接口/tests/test_tag_hooks.py

T1: test_tag_hooks_doc_sync
    record(tags="doc-sync") → triggered_skills == ["dream-doc-sync-workflow"]

T2: test_tag_hooks_wiki_compile
    record(tags="wiki-compile") → triggered_skills == ["wiki-ingest-trigger"]

T3: test_tag_hooks_hermes_reflection
    record(tags="hermes反思") → triggered_skills == ["dream-self-iteration-workflow"]

T4: test_tag_hooks_skill_creation
    record(tags="SKILL") → triggered_skills == ["skill-creator"]

T5: test_tag_hooks_hard_constraint
    record(tags="硬约束") → triggered_skills == ["dream-arch-collaboration-workflow"]

T6: test_tag_hooks_multi_tag_dedup
    record(tags="doc-sync,hermes反思") → triggered_skills == ["dream-doc-sync-workflow", "dream-self-iteration-workflow"]

T7: test_tag_hooks_no_match
    record(tags="普通经验,交易域") → triggered_skills == []

T8: test_tag_hooks_empty_tags
    record(tags="") → triggered_skills == []

T9: test_tag_hooks_fail_open
    Mock _get_cle().record() raises → _handle_record 仍返回（triggered_skills 可能为空，但不崩溃）

T10: test_tag_hooks_dedup_same_skill
    两个 tag 映射同一 skill → triggered_skills 只含一个
    （需要 TAG_HOOKS 中有两个 tag 映射同一 skill，当前设计无此情况，可跳过或扩展映射）
```

### 4.4 向后兼容

- `triggered_skills` 是新增字段，旧调用方忽略此字段不受影响
- `triggered_skills` 为空列表时等价于无触发，行为与当前一致
- 不修改 `recall`/`verify`/`stats`/`health` 的返回格式

---

## 5. 验收标准

| # | 标准 | 验证方法 |
|---|------|---------|
| AC1 | `_handle_record` 返回值包含 `triggered_skills` 字段 | 调用 record 检查 response JSON |
| AC2 | `tags="doc-sync"` → `triggered_skills=["dream-doc-sync-workflow"]` | T1 测试通过 |
| AC3 | 多 tag 叠加正确去重 | T6 测试通过 |
| AC4 | 无匹配 tag → `triggered_skills=[]` | T7/T8 测试通过 |
| AC5 | TAG_HOOKS 异常不阻塞 record | T9 测试通过 |
| AC6 | 10/10 测试全部通过 | `pytest tests/test_tag_hooks.py -v` |
| AC7 | 现有 cognitive 测试无回归 | `pytest tests/ -v` 全量通过 |

---

## 6. 风险与降级

| 风险 | 概率 | 影响 | 降级策略 |
|------|------|------|---------|
| TAG_HOOKS 查询异常 | 低 | record 返回无 triggered_skills | FAIL-OPEN 返回空列表 |
| tag 拼写错误不匹配 | 中 | 闭环不触发 | 文档强调 tag 精确匹配；可考虑后续加 fuzzy match |
| Agent 不读取 triggered_skills | 中 | 闭环退化为手动 | TRAE Agent 需识别 response 中 triggered_skills 字段 |
| TAG_HOOKS 映射过时 | 低 | 新 SKILL 不被触发 | 映射表可配置化（后续从 registry.json 动态加载） |

---

## 7. 后续演进（非本 SPEC 范围）

1. **动态 TAG_HOOKS**：从 `1-ARCHITECTURE/skills/_registry/registry.json` 动态加载 tag→skill 映射，而非硬编码
2. **tag 模糊匹配**：支持 `doc-sync-*` 通配符或正则
3. **triggered_skills 执行策略**：Agent 支持 `auto-invoke`（自动执行）vs `suggest`（仅建议）两种模式
4. **hook 链路可观测**：record 返回 `hook_trace` 字段记录 tag→skill 匹配过程

---

## 8. 关联文档

| 文档 | 关系 |
|------|------|
| [CLAUDE.md](../CLAUDE.md) L65-73 | 硬约束来源：doc-sync 必须触发 |
| [dream-doc-sync-workflow SKILL](skills/dream-doc-sync-workflow/SKILL.md) | 闭环1：文档同步 7 步流程 |
| [wiki-ingest-trigger SKILL](skills/wiki-ingest-trigger/SKILL.md) | Wiki 编译闭环 |
| [dream-self-iteration-workflow SKILL](skills/dream-self-iteration-workflow/SKILL.md) | 闭环3：hermes 反思 + L4 自迭代 |
| [cognitive_mcp_server.py](../4-MEMORY/9-工具与接口/cognitive_mcp_server.py) | 实现目标文件 |
