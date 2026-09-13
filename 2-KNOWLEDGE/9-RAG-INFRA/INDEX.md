# 9-RAG-INFRA — 知识库 RAG 三层融合系统

> **版本**: v2.0 | **更新日期**: 2026-09-10
> 职责：为 DreamBuddy 知识库提供检索增强生成（RAG）基础设施，
> 将 `2-KNOWLEDGE/` 下的 Markdown 知识与 CBR 案例库转化为可语义检索的向量索引，
> 通过桥接层与认知记忆系统联动，形成"检索→记忆→反哺"闭环。

## 目录结构

```
9-RAG-INFRA/
├── vector_store/            # 阶段1：向量检索层
│   ├── config.py           # 统一配置（模型、维度、路径、批次）
│   ├── chunker.py          # 语义分块器（按标题/代码块/表格）
│   ├── embedder.py         # 向量化器（bge-small-zh + TF-IDF 回退）
│   ├── build_index.py      # 构建向量索引（ChromaDB + 增量更新）
│   └── search.py           # 语义检索（域过滤 + 分数阈值）
├── rag_engine/              # 混合检索引擎
│   └── hybrid_retriever.py # 向量+关键词混合检索 + 权重反哺重排
├── bridge/                  # RAG ↔ 认知记忆桥接层（已建成）
│   ├── memory_bridge.py     # 检索→记忆record + verify→boost反哺
│   ├── cbr_to_vectors.py    # CBR案例库(jsonl)→ChromaDB向量化
│   └── retrieval_memory_map.jsonl  # 检索↔记忆映射表
├── chroma_db/              # ChromaDB 持久化目录（运行时生成）
│   └── chroma.sqlite3      # 18MB，含策略文档+CBR案例+硬约束
├── tests/
│   ├── test_vector_store.py  # TC1-TC8 用例
│   └── test_rag_hotpath_integration.py  # RAG热路径集成测试
├── docs/                   # 设计文档
│   └── rag-hotpath-integration.md  # RAG热路径集成方案（已完成）
└── INDEX.md                # 本文件
```

## 三阶段路线

| 阶段 | 名称 | 检索方式 | 状态 |
|------|------|---------|------|
| 阶段1 | 向量检索层 | 语义向量（bge-small-zh + ChromaDB） | ✅ 已实现 |
| 阶段2 | 混合检索层 | 向量+BM25关键词+权重反哺重排 | ✅ 已实现 |
| 阶段3 | 结构化检索层 | 元数据/标签/source_type过滤 | ✅ 已实现（CBR案例3维标签） |

## 桥接模块（已建成）

### memory_bridge.py

| 函数 | 职责 | 状态 |
|:---|:---|:---|
| `record_retrieval_as_memory()` | RAG检索结果→认知记忆record(C级) | ✅ 运行中 |
| `verify_and_feedback()` | 平仓结果→verify→boost更新 | ✅ 运行中 |

- 检索→记忆映射：`retrieval_memory_map.jsonl` 1654条
- 权重反哺：`weight_feedback.json` 12条（boost 0.9~1.1）

### cbr_to_vectors.py

| 功能 | 状态 |
|:---|:---|
| CBR案例(jsonl)→文本+metadata→ChromaDB upsert | ✅ 200条已入索引 |
| source_type="cbr_case" 标签 | ✅ |
| 3维标签：setup_type / regime / failure_reason | ✅ |

### RAG 热路径集成（polling_trader.py）

| 接入点 | 位置 | 调用频率 | 状态 |
|:---|:---|:---|:---|
| `[RAG-PRE-OPEN]` | 开仓前检索 | 每次开仓 | ✅ 今日26次 |
| `[RAG-PRE-EVO-OPEN]` | 进化开仓前检索 | 进化触发时 | ✅ 今日1次 |
| `[RAG-PRE-EXIT]` | 离场前检索 | 每轮询持仓 | ✅ 今日351次 |
| `[RAG-FEEDBACK]` | 平仓后反哺 | 平仓时 | ✅ 今日0次（无平仓） |
| `[CASE-DISTILL]` | 平仓后蒸馏 | 平仓时 | ✅ 今日0次（无平仓） |

## 数据统计（2026-09-10）

| 指标 | 数值 |
|:---|:---|
| ChromaDB 总 chunks | 3699 |
| 策略文档 chunks | ~3300 |
| CBR案例 chunks | 200 |
| 硬约束总表 chunks | 32 |
| 认知记忆 DB | 1.2MB |
| retrieval_memory_map | 1654条 |
| weight_feedback | 12条 |
| daemon RAG 调用 | 378次/日 |
| daemon 异常 | 0 |

## 知识库内容

| 类型 | 来源 | 数量 |
|:---|:---|:---|
| 策略框架文档 | 2-KNOWLEDGE/1-TRADING/ | 26篇 |
| 经典模式文档 | 2-KNOWLEDGE/1-TRADING/经典模式/ | 7篇+1索引 |
| 硬约束总表 | 2-KNOWLEDGE/1-TRADING/ | 1篇（38条硬约束） |
| CBR案例库 | polling_trader/cbr_cases_v03.jsonl | 202条 |
| 外部研究 | 2-KNOWLEDGE/7-EXTERNAL-RESEARCH/ | 多篇 |

## 设计原则

- **FAIL-OPEN**：模型不可用时自动回退 TF-IDF，保证系统不阻塞；
- **增量更新**：按文件 md5 哈希判断变更，仅重建改动文件；
- **测试隔离**：测试在临时目录运行，不污染真实知识库；
- **只读辅助**：RAG 检索结果注入 context 供推理参考，不修改 BCRM/力向量决策参数。

## 变更记录

| 版本 | 日期 | 变更 |
|:---|:---|:---|
| v2.0 | 2026-09-10 | 补充桥接模块、热路径集成、CBR向量化、数据统计 |
| v1.0 | 2026-08-15 | 初始版本：向量检索层+三阶段路线 |
