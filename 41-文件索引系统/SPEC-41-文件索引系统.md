# SPEC — 41-文件索引系统

> **版本**: v0.1 (2026-10-21)
> **状态**: 草案（待评审）
> **定位**: dreambuddy 的统一文件索引与检索子系统
> **上游关联**: 前端搜索优化方案（3.1-FRONTEND/docs/前端搜索优化方案.md）

---

## 0. 文档定位

本文档定义 **41-文件索引系统** 的完整设计规格。它承接前端搜索优化方案的阶段二/三诉求，为全项目提供统一的文件/文档索引构建、增量更新与检索能力，作为前端全局搜索、Agent 代码检索、文档管理的统一索引底座。

核心价值：**给调用方一个查询词，返回带来源证据的文件/文档命中结果，支撑『搜得到、跳得转、可追溯』。**

---

## 1. 背景与动机

### 1.1 问题

dreambuddy 当前面临以下检索痛点：

- 前端仅报告页有 taskId 精确匹配，无全局搜索入口（见前端搜索优化方案现状分析）
- 项目模块已达 40+ 个，文档/报告/策略/记忆分散在各模块目录，人工翻找成本高
- Agent（DSH 链路）需要检索工程文件时，只能逐目录遍历，效率低且不可复用
- 后端 case-retriever 检索能力未与文件/文档检索打通

### 1.2 现有方案的不足

| 方案 | 不足 |
|---|---|
| 文件系统遍历 | 每次全量扫描，慢且无相关性排序 |
| 前端内存索引 | 数据量增长后内存膨胀，多端不共享 |
| 直接引入 Meilisearch | 当前数据规模下运维成本偏高，应作为演进选项 |

### 1.3 设计目标

1. **统一索引底座**：一次构建，多端消费（前端全局搜索、Agent 检索、文档管理）
2. **增量更新**：基于 mtime/hash 的变更检测，避免全量重建
3. **Evidence-First**：每条命中结果带来源（路径+行号/片段+得分），与 33-REA 工程哲学一致
4. **轻量可控**：Python 原生实现，SQLite 存储，零重型依赖
5. **可演进**：预留 Meilisearch/向量检索适配器接口

---

## 2. 核心设计哲学

### 2.1 Evidence-First（证据优先）

每条检索结果必须包含：

- **source**: 来源（文件路径、行号或片段定位）
- **score**: 相关性得分（0.0-1.0）
- **snippet**: 命中上下文片段
- **indexed_at**: 索引时间戳（判断新鲜度）

### 2.2 分层索引

| 层级 | 内容 | 更新频率 |
|---|---|---|
| L1 元数据索引 | 路径/文件名/类型/mtime/size | 实时（fs 事件或按需） |
| L2 内容索引 | 标题/摘要/正文分词（倒排） | 变更时增量 |
| L3 语义索引（预留） | 向量嵌入 | 按需构建 |

---

## 3. 系统架构

```
41-文件索引系统/
├── SPEC-文件索引系统.md        # 本文档
├── core/
│   ├── scanner.py              # 文件扫描器（遍历+过滤规则）
│   ├── indexer.py              # 索引构建（L1/L2）
│   ├── incremental.py          # 增量更新（mtime/hash 检测）
│   └── searcher.py             # 检索引擎（倒排匹配+打分）
├── adapters/
│   ├── meilisearch_adapter.py  # Meilisearch 适配器（预留）
│   └── vector_adapter.py       # 向量检索适配器（预留）
├── api/
│   └── search_api.py           # 统一检索接口（供前端/Agent 调用）
├── config/
│   └── index_rules.yaml        # 索引范围/排除规则
├── scripts/
│   └── rebuild_index.py        # 全量重建入口
└── tests/
```

### 3.1 数据流

```
文件系统 → scanner（过滤）→ indexer（分词+倒排）→ SQLite 索引库
                                                      ↓
前端全局搜索 / Agent 检索 ← search_api（打分+片段） ← searcher
```

---

## 4. 数据结构

### 4.1 索引存储（SQLite）

- **files** 表：id, path, type, mtime, size, hash, indexed_at
- **tokens** 表：token, file_id, positions, tf
- **documents** 表：file_id, title, summary, lang

### 4.2 检索结果结构

```json
{
  "query": "搜索词",
  "hits": [
    {
      "source": {"path": "...", "line": 12},
      "score": 0.87,
      "snippet": "...命中上下文...",
      "type": "report|strategy|memory|doc|code",
      "indexed_at": "2026-10-21T22:00:00Z"
    }
  ],
  "total": 42,
  "took_ms": 18
}
```

---

## 5. 接口设计

### 5.1 统一检索接口

```
search(query, filters?, limit=20) -> SearchResult
``n
- **filters**: 按类型（报告/策略/记忆/文档/代码）、模块、时间范围过滤
- **limit**: 默认 20，上限 100

### 5.2 索引管理接口

```
rebuild(scope?) -> Stats        # 全量重建
update(paths) -> Stats          # 增量更新
status() -> IndexStatus         # 索引健康度（文件数/新鲜度/耗时）
```

### 5.3 与前端的对接

- 前端通过 Next.js API Route 代理调用 search_api
- 结果结构与前端搜索优化方案 3.2 阶段二的 /api/search 对齐

---

## 6. 索引范围与规则（初始）

| 范围 | 类型标记 |
|---|---|
| 各模块 SPEC/README/docs（*.md） | doc |
| 报告产物（reports/、artifacts/） | report |
| 策略定义与配置 | strategy |
| 记忆/案例库条目 | memory |
| 源码（*.py/*.ts/*.tsx，仅元数据+标题级） | code |

排除：node_modules、.git、__pycache__、.next、日志、二进制文件。

---

## 7. 实施路线

| 阶段 | 内容 | 验收 |
|---|---|---|
| P0 | scanner + L1 元数据索引 + 基础检索 | 全项目文件可按名检索，<100ms |
| P1 | L2 内容倒排索引 + 增量更新 + search_api | 全文检索可用，变更文件 5s 内可检索 |
| P2 | 前端 /api/search 对接 + 类型过滤 | 前端全局搜索走本系统 |
| P3 | Meilisearch/向量适配器（按需） | 数据量超阈值或语义检索需求触发 |

---

## 8. 风险与对策

| 风险 | 对策 |
|---|---|
| 索引与文件不一致 | mtime+hash 双重校验，status() 暴露新鲜度 |
| 索引库膨胀 | SQLite 分表+定期压缩，冷数据降级为 L1 |
| 检索越权 | search_api 层按调用方身份过滤 |

---

## 9. 参考

- 33-REA逆向解析工程 SPEC（Evidence-First 哲学与文档格式）
- 3.1-FRONTEND/docs/前端搜索优化方案.md（上游需求）
- Meilisearch / Typesense 官方文档（演进选型依据）
