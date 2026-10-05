---
name: wiki-ingest-trigger
description: "Cognitive event → Wiki ingest trigger. When cognitive record tags contain 'wiki-compile', TAG_HOOKS emits triggered_skills: [wiki-ingest-trigger]. Agent reads this signal and calls wiki_ingest(content, source) via DSH IPC or python-server directly."
version: 1.0.0
created: 2026-09-24
updated: 2026-09-24
license: Internal
status: active
category: trigger
triggers: [wiki-ingest-trigger, wiki compile, 认知编译, wiki-ingest]
depends_on: [cognitive_mcp_server.py, wiki_compiler.py, cordis-plugin-knowledge-wiki]
provides: [cognitive-to-wiki-bridge]
cognitive_links: []
---

## Autonomy Boundary

可自主执行：
- 信号检测与触发判断
- 触发条件评估与告警
- 触发后通知与日志记录

需用户确认：
- 触发后自动执行交易操作

禁止：
- 将触发信号直接转化为交易订单
- 绕过人工确认执行高风险操作


# Wiki Ingest Trigger — 认知→Wiki 反向触发 SKILL

> 认知系统 `record` 时 `tags` 含 `wiki-compile` → TAG_HOOKS 返回 `triggered_skills: ["wiki-ingest-trigger"]` → Agent 识别信号 → 调用 `wiki_ingest` 将经验编译为 Wiki 页面。本 SKILL 是认知记忆与 Wiki 编译层之间的桥梁。

> **双位置存储**：本 SKILL 同时存在于：
> - `.trae/skills/wiki-ingest-trigger/SKILL.md`（TRAE 调用入口）
> - `1-ARCHITECTURE/skills/wiki-ingest-trigger/SKILL.md`（项目级索引发现，本文件）

> **与 `dream-doc-sync-workflow` 的关系**：后者是 `doc-sync` tag → 文档索引同步；本 SKILL 是 `wiki-compile` tag → Wiki 页面编译。同构但对象不同。

---

## 一、何时调用（触发条件）

满足以下任一条件即应调用本 SKILL：

1. **认知事件驱动**：认知系统 `record` 响应包含 `triggered_skills: ["wiki-ingest-trigger"]`
   - **hook 配置**：`TAG_HOOKS = {"wiki-compile": "wiki-ingest-trigger"}`（定义于 `cognitive_mcp_server.py`）
   - **FAIL-OPEN**：hook 异常不影响 record 主流程，返回空触发列表
2. **手动触发**：用户要求将某条经验编译为 Wiki 页面
   - 触发词：「wiki 编译」「认知编译」「wiki ingest」

**不触发的场景**：
- 认知经验质量过低（C 级以下）→ Agent 判断不值得编译
- 经验内容与 Wiki 主题无关（如纯交易信号记录）→ 不调用

---

## 二、触发链路

```
record(tags含"wiki-compile")
    → TAG_HOOKS 匹配 → 返回 triggered_skills: ["wiki-ingest-trigger"]
    → Agent 识别信号（本 SKILL 指引）
    → Agent 判断经验质量是否值得编译（P2 可选，需人工判断）
    → Agent 调用 wiki_ingest(content=经验内容, source="cognitive-memory")
    → Wiki 编译层处理 → 生成/更新 Wiki 页面
```

**关键限制**：认知系统只发信号，不能直接调用 `wiki_ingest`（需 DSH IPC 或 python-server）。Agent 是信号的唯一消费者。

---

## 三、Agent 响应步骤

### 步骤 1：识别信号

检查 `record` 的 MCP 响应中是否包含 `triggered_skills` 字段：

```json
{
  "memory_id": "VM-xxx",
  "triggered_skills": ["wiki-ingest-trigger"]
}
```

### 步骤 2：质量判断（人工介入）

根据 spec P2 设计，Agent 应判断经验是否值得编译为 Wiki 页面：
- **编译**：经验包含可复用的架构知识、流程模式、最佳实践
- **跳过**：经验是纯交易信号记录、临时调试笔记、低质量假设

### 步骤 3：调用 wiki_ingest

判断通过后，调用 `wiki_ingest` 工具：

**方式 A：通过 DSH IPC**（需 DSH web profile 加载 wiki plugin）
```
wiki_ingest(content="经验内容", source="cognitive-memory")
```

**方式 B：直接调用 python-server**（DSH 不可用时降级）
```python
from server import _handle_wiki_ingest
result = _handle_wiki_ingest({"content": "经验内容", "source": "cognitive-memory"})
```

**方式 C：直接调用 wiki_compiler**（最底层）
```python
from wiki_compiler import WikiCompiler
compiler = WikiCompiler()
compiler.ingest(content="经验内容", source="cognitive-memory")
```

### 步骤 4：验证编译结果

调用 `wiki_lint` 检查 Wiki 健康度：
```
wiki_lint()
```

---

## 四、配置参考

| 组件 | 文件 | 配置项 |
|------|------|--------|
| TAG_HOOKS | `4-MEMORY/9-工具与接口/cognitive_mcp_server.py:60` | `{"wiki-compile": "wiki-ingest-trigger"}` |
| Wiki 编译器 | `2-KNOWLEDGE/9-RAG-INFRA/evolution/wiki_compiler.py` | `ingest()` / `query()` / `lint()` |
| IPC server | `1-ARCHITECTURE/dream-harness-bridge/packages/python-server/server.py` | `wiki_ingest` / `wiki_query` / `wiki_lint` |
| DSH plugin | `.dsh-home/profiles/web/cordis.patch.yml` | `dreambuddy-knowledge-wiki` (enabled: true) |

---

## 五、FAIL-OPEN 原则

- 认知 hook 异常 → 不影响 record 主流程
- wiki_ingest 调用失败 → 记录警告，不影响认知记忆写入
- DSH 不可用 → 降级为直接调用 python-server
- 质量判断由 Agent 执行 → 不自动编译低质量经验
