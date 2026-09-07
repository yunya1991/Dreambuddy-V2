# 9-RAG-INFRA — 知识库 RAG 三层融合系统

> 职责：为 DreamBuddy 知识库提供检索增强生成（RAG）基础设施，
> 将 `2-KNOWLEDGE/` 下的 Markdown 知识转化为可语义检索的向量索引，
> 并在后续阶段叠加关键词与结构化检索，形成三层融合召回。

## 目录结构

```
9-RAG-INFRA/
├── vector_store/            # 阶段1：向量检索层
│   ├── config.py           # 统一配置（模型、维度、路径、批次）
│   ├── chunker.py          # 语义分块器（按标题/代码块/表格）
│   ├── embedder.py         # 向量化器（bge-small-zh + TF-IDF 回退）
│   ├── build_index.py      # 构建向量索引（ChromaDB + 增量更新）
│   └── search.py           # 语义检索（域过滤 + 分数阈值）
├── tests/
│   └── test_vector_store.py  # TC1-TC8 用例
├── chroma_db/              # ChromaDB 持久化目录（运行时生成）
└── INDEX.md                # 本文件
```

## 三阶段路线

| 阶段 | 名称 | 检索方式 | 状态 |
|------|------|---------|------|
| 阶段1 | 向量检索层 | 语义向量（bge-small-zh + ChromaDB） | ✅ 已实现 |
| 阶段2 | 关键词检索层 | BM25/Whoosh 倒排索引，补充精确匹配 | ⏳ 待实现 |
| 阶段3 | 结构化检索层 | 元数据/标签/关系图谱过滤，三层融合召回 | ⏳ 待实现 |

## 设计原则

- **FAIL-OPEN**：模型不可用时自动回退 TF-IDF，保证系统不阻塞；
- **增量更新**：按文件 md5 哈希判断变更，仅重建改动文件；
- **测试隔离**：测试在临时目录运行，不污染真实知识库。
