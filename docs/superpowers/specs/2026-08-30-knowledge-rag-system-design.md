# 知识库RAG三层融合系统设计Spec

> **文档编号**: 2026-08-30-knowledge-rag-system-design
> **创建日期**: 2026-08-30
> **状态**: Draft
> **作者**: DreamBuddy Team
> **关联**: 中信建投证券知识库管理体系调研（7-EXTERNAL-RESEARCH/finance/risk-models/）

---

## 1. 背景与目标

### 1.1 现状

DreamBuddy-V2 知识库（2-KNOWLEDGE）现有 57 个 md 文件，覆盖 8 个域（TRADING/TECHNICAL/THEORY/OPERATIONS/METHODOLOGY/CHAIN-DEVELOPMENT/PRODUCT-BUSINESS/EXTERNAL-RESEARCH/AI-COGNITION），但存在以下问题：

| 问题 | 影响 |
|------|------|
| 检索只能靠文件名和全文搜索 | 语义相似但标题不同的文档无法被发现 |
| 知识间关联靠人工跨域引用 | 实体关系不透明，无法进行多跳推理 |
| 无可溯源的知识生成 | AI回答无法引用知识库来源，幻觉风险高 |
| 知识库更新与认知记忆脱节 | 4-MEMORY的verify升级不反哺知识库 |

### 1.2 目标

参考中信建投证券的 RAG+向量检索+知识图谱三层融合体系，为 DreamBuddy 构建知识驱动持续进化机制：

```
采集 → 清洗 → 标注 → 索引 → 反馈 → 进化
```

**量化指标：**

| 指标 | 目标 |
|------|------|
| 知识库文档向量化覆盖率 | ≥95% |
| 语义检索 top-5 命中率 | ≥80% |
| 知识图谱实体覆盖 | ≥200实体/≥500关系 |
| RAG回答可溯源率 | ≥90% |
| 幻觉率（无知识支撑的断言） | ≤10% |

---

## 2. 三层融合架构

### 2.1 整体架构

```
┌──────────────────────────────────────────────────────────┐
│                    用户查询 / AI对话                       │
└──────────────────────────┬───────────────────────────────┘
                           │
                    ┌──────▼──────┐
                    │  混合检索层  │ ← 查询路由+多路召回+重排序
                    └──┬───┬───┬─┘
           ┌───────────┘   │   └───────────┐
           │               │               │
    ┌──────▼──────┐  ┌─────▼─────┐  ┌──────▼──────┐
    │  向量检索   │  │ 知识图谱   │  │  BM25关键词 │
    │  ChromaDB   │  │  Neo4j    │  │  全文检索   │
    │  bge-small  │  │  Cypher   │  │  Whoosh    │
    └──────┬──────┘  └─────┬─────┘  └──────┬──────┘
           │               │               │
           └───────────────┼───────────────┘
                           │
                    ┌──────▼──────┐
                    │  RAG生成层  │ ← 检索结果→LLM→可溯源回答
                    └──────┬──────┘
                           │
    ┌──────────────────────┼──────────────────────┐
    │             持续进化闭环                      │
    │  采集 → 清洗 → 标注 → 索引 → 反馈 → 进化     │
    │      ↑                                    │   │
    │      └──── 4-MEMORY认知系统桥接 ──────────┘   │
    └──────────────────────────────────────────────┘
```

### 2.2 层级职责

| 层 | 职责 | 技术 | 输入 | 输出 |
|---|------|------|------|------|
| 向量检索层 | 语义相似度检索 | ChromaDB + bge-small-zh | 文档md | top-k语义块 |
| 知识图谱层 | 实体关系多跳推理 | Neo4j + Cypher | 实体/关系 | 子图/路径 |
| RAG生成层 | 可溯源知识生成 | LLM + prompt工程 | 检索结果 | 带引用的回答 |
| 持续进化层 | 知识闭环更新 | 自动化管线 | 新文档/反馈 | 更新的索引+图谱 |

---

## 3. 阶段1：向量检索层

### 3.1 模块设计

```
2-KNOWLEDGE/9-RAG-INFRA/vector_store/
├── __init__.py
├── chunker.py          # 语义分块器
├── embedder.py         # 向量化器
├── build_index.py      # 构建向量索引
├── search.py           # 语义检索
└── config.py           # 配置
```

### 3.2 语义分块器（chunker.py）

**分块策略：** 语义分块（非固定token），保留文档结构。

| 分块规则 | 说明 |
|---------|------|
| 一级标题（#） | 独立块，包含标题下的摘要 |
| 二级标题（##） | 独立块，包含标题下内容 |
| 三级标题（###） | 独立块，包含标题下内容 |
| 代码块 | 整块保留，不拆分 |
| 表格 | 整表保留，不拆分 |
| 段落 | 不超过512 token，超长则按句号切分 |

**元数据：** 每个块附带：

```python
{
    "source_file": "1-TRADING/BCRM2推理引擎.md",
    "domain": "1-TRADING",
    "chunk_type": "section",  # section/code/table/paragraph
    "heading": "BCRM2.0 推理引擎",
    "heading_level": 1,
    "position": 0,  # 在文档中的位置索引
    "tags": ["#bcrm", "#推理引擎", "#11-易经推理系统"]
}
```

### 3.3 向量化器（embedder.py）

**模型：** BAAI/bge-small-zh-v1.5

| 属性 | 值 |
|------|-----|
| 维度 | 512 |
| 最大序列长度 | 512 token |
| 许可证 | MIT |
| 语言 | 中文原生 |
| 模型大小 | ~95MB |

**FAIL-OPEN策略：**

| 异常 | 回退 |
|------|------|
| 模型下载失败 | 使用TF-IDF向量作为fallback |
| 单条embedding失败 | 跳过该块，记录warning |
| GPU不可用 | 自动回退CPU |

### 3.4 向量数据库（ChromaDB）

| 配置 | 值 |
|------|-----|
| 持久化路径 | 2-KNOWLEDGE/9-RAG-INFRA/chroma_db/ |
| 集合名 | dreambuddy_knowledge |
| 距离度量 | cosine |
| 批量插入 | 100条/批 |

### 3.5 构建索引（build_index.py）

```python
def build_index(knowledge_dir: Path, force: bool = False):
    """
    扫描2-KNOWLEDGE下所有md文件，语义分块，向量化，存入ChromaDB。

    Args:
        knowledge_dir: 2-KNOWLEDGE根目录
        force: True则重建索引，False则增量更新

    Returns:
        {
            "total_files": int,
            "total_chunks": int,
            "new_chunks": int,
            "updated_chunks": int,
            "failed_chunks": int,
            "duration_sec": float
        }
    """
```

**增量更新机制：**
- 按文件md5哈希判断是否变更
- 仅重新embedding变更文件的块
- 删除已不存在文件的块

### 3.6 语义检索（search.py）

```python
def search(
    query: str,
    top_k: int = 5,
    domain_filter: list[str] | None = None,
    score_threshold: float = 0.3
) -> list[dict]:
    """
    语义检索知识库。

    Args:
        query: 自然语言查询
        top_k: 返回结果数
        domain_filter: 限定域（如["1-TRADING", "3-THEORY"]）
        score_threshold: 相似度下限

    Returns:
        [
            {
                "content": "块内容",
                "source_file": "来源文件",
                "domain": "域",
                "heading": "标题",
                "score": 0.87,
                "tags": ["#bcrm"]
            }
        ]
    """
```

### 3.7 测试用例

| TC | 场景 | 预期 |
|----|------|------|
| TC1 | 构建索引：57个md文件 | total_chunks ≥200，failed=0 |
| TC2 | 增量更新：修改1个文件 | new_chunks对应1文件，其余不变 |
| TC3 | 语义检索："BCRM推理模型" | top-5包含BCRM2推理引擎.md |
| TC4 | 域过滤：domain_filter=["1-TRADING"] | 结果全部来自1-TRADING |
| TC5 | 阈值过滤：score_threshold=0.8 | 仅返回高相关结果 |
| TC6 | FAIL-OPEN：模型不可用 | 回退TF-IDF，不报错 |
| TC7 | 空查询 | 返回空列表，不报错 |
| TC8 | 代码块保留 | 代码块不被拆分 |

---

## 4. 阶段2：知识图谱层

### 4.1 模块设计

```
2-KNOWLEDGE/9-RAG-INFRA/knowledge_graph/
├── __init__.py
├── entity_extractor.py    # 实体关系抽取
├── build_graph.py          # 构建知识图谱
├── graph_search.py         # 图谱检索
└── schema.py               # 图谱Schema定义
```

### 4.2 图谱Schema

**节点类型：**

| 类型 | 属性 | 示例 |
|------|------|------|
| Module | name, path, port | 11-易经推理系统 |
| Concept | name, description | BCRM2.0 |
| Algorithm | name, formula | Kalman Filter |
| File | path, lines, domain | polling_trader.py |
| Strategy | name, type | V4减半周期 |
| Parameter | name, value, unit | θ_match=0.71 |
| DataSource | name, url, frequency | Tether官网 |

**关系类型：**

| 关系 | 含义 | 示例 |
|------|------|------|
| DEPENDS_ON | 模块依赖 | 11-易经 DEPENDS_ON 9-基本面 |
| IMPLEMENTS | 实现概念 | polling_trader.py IMPLEMENTS BCRM2.0 |
| USES_ALGORITHM | 使用算法 | 力向量 USES_ALGORITHM Kalman Filter |
| INJECTS_INTO | 注入到 | S1 sentiment INJECTS_INTO 五计庙算 |
| CONFIGURED_BY | 参数配置 | CBR CONFIGURED_BY θ_match |
| FEEDS_DATA | 数据供给 | Tether官网 FEEDS_DATA 稳定币供应 |
| RELATES_TO | 关联 | BCRM2.0 RELATES_TO CBR |

### 4.3 实体关系抽取（entity_extractor.py）

**抽取策略：** 规则+模式匹配（非LLM），保证确定性。

| 抽取规则 | 方法 |
|---------|------|
| 模块名 | 匹配 `NN-名称` 格式 |
| 文件路径 | 匹配 `*.py` / `*.md` |
| 参数 | 匹配 `参数名 = 值` 格式 |
| 模块依赖 | 从md中的"关联"/"来源"/"注入"段落抽取 |
| 算法 | 从tags中抽取（#kalman #pca等） |
| 数据源 | 匹配URL格式 |

### 4.4 构建图谱（build_graph.py）

```python
def build_graph(knowledge_dir: Path, neo4j_uri: str = "bolt://localhost:7687"):
    """
    扫描知识库md文件，抽取实体关系，构建Neo4j知识图谱。

    Returns:
        {
            "total_nodes": int,
            "total_edges": int,
            "node_by_type": dict,
            "edge_by_type": dict,
            "duration_sec": float
        }
    """
```

### 4.5 图谱检索（graph_search.py）

```python
def graph_search(
    entity: str,
    hops: int = 2,
    relation_filter: list[str] | None = None
) -> dict:
    """
    从知识图谱中检索实体的关联子图。

    Args:
        entity: 实体名称
        hops: 跳数（1=直接关联，2=间接关联）
        relation_filter: 限定关系类型

    Returns:
        {
            "center_node": {"type": "Module", "name": "11-易经推理系统"},
            "neighbors": [
                {"type": "Module", "name": "9-基本面分析", "relation": "DEPENDS_ON"},
                ...
            ],
            "paths": [...]
        }
    """
```

### 4.6 测试用例

| TC | 场景 | 预期 |
|----|------|------|
| TC9 | 抽取实体：BCRM2推理引擎.md | 抽出Module/Concept/Parameter节点 |
| TC10 | 构建图谱：57个md文件 | total_nodes ≥200，total_edges ≥500 |
| TC11 | 图谱检索：查询"11-易经推理系统" | 返回依赖模块、实现概念、使用算法 |
| TC12 | 多跳检索：hops=2 | 返回间接关联实体 |
| TC13 | 关系过滤：relation_filter=["DEPENDS_ON"] | 仅返回依赖关系 |

---

## 5. 阶段3：RAG融合+持续进化闭环

### 5.1 模块设计

```
2-KNOWLEDGE/9-RAG-INFRA/
├── rag_engine/
│   ├── __init__.py
│   ├── hybrid_retriever.py    # 混合检索
│   ├── reranker.py            # 重排序
│   └── generator.py           # RAG生成
├── evolution/
│   ├── __init__.py
│   ├── ingest.py              # 采集+清洗
│   ├── annotate.py            # 自动标注
│   └── feedback.py            # 反馈机制
```

### 5.2 混合检索（hybrid_retriever.py）

**三路召回 + 重排序：**

```python
def hybrid_search(
    query: str,
    top_k: int = 10,
    weights: dict = None  # 默认 vector:0.4, graph:0.3, keyword:0.3
) -> list[dict]:
    """
    三路混合检索：
    1. 向量检索（语义相似度）
    2. 图谱检索（实体关系）
    3. BM25关键词检索

    三路结果合并 → 重排序 → top-k
    """
```

**重排序策略：**

| 信号 | 权重 |
|------|------|
| 向量相似度 | 0.35 |
| 图谱关联度 | 0.25 |
| BM25得分 | 0.20 |
| 域匹配度 | 0.10 |
| 文档新鲜度 | 0.10 |

### 5.3 RAG生成（generator.py）

```python
def generate(
    query: str,
    retrieved_chunks: list[dict],
    max_tokens: int = 2000
) -> dict:
    """
    RAG生成：检索结果 → prompt工程 → LLM → 可溯源回答

    Returns:
        {
            "answer": "回答内容",
            "citations": [
                {"source": "1-TRADING/BCRM2推理引擎.md", "chunk": "..."},
                ...
            ],
            "confidence": 0.85,
            "ungrounded_claims": []  # 无知识支撑的断言
        }
    """
```

**Prompt工程：**

```
你是一个知识库问答助手。根据以下检索到的知识库内容回答问题。
要求：
1. 回答必须基于提供的知识库内容
2. 每个论点必须标注来源 [来源文件名]
3. 如果知识库内容不足以回答，明确说明"知识库中未找到相关信息"
4. 不允许编造未在知识库中出现的信息

知识库内容：
{retrieved_chunks}

问题：{query}
```

### 5.4 持续进化闭环

#### 采集（ingest.py）

| 来源 | 触发 | 处理 |
|------|------|------|
| 开发对话中的调研 | AI主动提示归档 | 按模板写入7-EXTERNAL-RESEARCH |
| 新代码模块 | git hook检测新目录 | 提示生成知识库文档 |
| 外部文档 | 手动导入 | 清洗→分块→向量化 |

#### 清洗

| 步骤 | 规则 |
|------|------|
| 去重 | md5哈希判断 |
| 归一化 | 统一标题层级、链接格式 |
| 消歧 | 同名实体合并 |

#### 标注（annotate.py）

| 标注类型 | 方法 |
|---------|------|
| 域分类 | 从目录路径自动判断 |
| 标签抽取 | 从tags行提取 |
| 实体链接 | 关联到知识图谱节点 |
| 质量评分 | 完整性/准确性/时效性 |

#### 索引

| 索引类型 | 触发 |
|---------|------|
| 向量索引 | 文档变更时增量更新 |
| 图谱索引 | 实体关系变更时更新 |
| BM25索引 | 文档变更时更新 |

#### 反馈（feedback.py）

| 反馈来源 | 处理 |
|---------|------|
| RAG回答被采纳 | 正反馈，提升相关块权重 |
| RAG回答被纠正 | 负反馈，降低相关块权重 |
| 4-MEMORY verify | 认知记忆验证结果反哺知识库 |

#### 进化

| 进化动作 | 触发 |
|---------|------|
| 知识库自动丰富 | 新文档归档 |
| 检索质量提升 | 反馈数据优化重排序权重 |
| 图谱自动扩展 | 新实体关系发现 |
| 过期知识标记 | 季度审查 |

### 5.5 与4-MEMORY桥接

```
4-MEMORY认知系统                    2-KNOWLEDGE知识库
  recall → record → verify          采集 → 清洗 → 标注 → 索引
                ↑                              │
                │                              │
                └──── feedback桥接 ───────────┘
                     │              │
                     │              └→ verify成功 → 知识库块权重+0.1
                     │              └→ verify失败 → 知识库块权重-0.1
                     │
                     └→ RAG检索结果可record为C级记忆
                        C级 → verify → B级 → A级
```

**桥接规则：**

| 方向 | 条件 | 动作 |
|------|------|------|
| 知识库→记忆 | RAG检索置信度≥0.8 | record为C级记忆，tags含知识库来源 |
| 记忆→知识库 | verify成功 | 知识库对应块feedback_weight +0.1 |
| 记忆→知识库 | verify失败 | 知识库对应块feedback_weight -0.1 |

### 5.6 测试用例

| TC | 场景 | 预期 |
|----|------|------|
| TC14 | 混合检索："力向量如何计算" | 三路召回，重排序后top-5相关 |
| TC15 | RAG生成："BCRM2.0是什么" | 回答带引用，citations非空 |
| TC16 | RAG生成：知识库无相关信息 | 回答"知识库中未找到" |
| TC17 | 反馈：正反馈 | feedback_weight +0.1 |
| TC18 | 反馈：负反馈 | feedback_weight -0.1 |
| TC19 | 4-MEMORY桥接：verify成功 | 知识库块权重增加 |
| TC20 | 持续进化：新文档归档 | 自动索引+图谱更新 |

---

## 6. 技术选型

### 6.1 技术栈

| 组件 | 选型 | 版本 | 理由 |
|------|------|------|------|
| Embedding模型 | BAAI/bge-small-zh-v1.5 | 1.0 | MIT开源，中文原生，512维，轻量 |
| 向量数据库 | ChromaDB | 0.5+ | 纯Python，轻量，持久化 |
| 知识图谱 | Neo4j Community | 5.x | 原生图DB，Cypher查询，社区版免费 |
| 全文检索 | Whoosh | 2.7 | 纯Python，无外部依赖 |
| Python | 3.10+ | - | 与现有项目一致 |
| LLM | 现有模型 | - | RAG生成复用 |

### 6.2 依赖

```
# requirements-rag.txt
chromadb>=0.5.0
sentence-transformers>=2.2.0
whoosh>=2.7.4
neo4j>=5.0.0
# bge-small-zh 通过 sentence-transformers 自动下载
```

### 6.3 FAIL-OPEN策略

| 层 | 异常 | 回退 |
|---|------|------|
| 向量检索 | 模型不可用 | TF-IDF向量 |
| 向量检索 | ChromaDB不可用 | 仅BM25关键词检索 |
| 知识图谱 | Neo4j不可用 | 跳过图谱检索 |
| RAG生成 | LLM不可用 | 返回原始检索结果 |
| 持续进化 | 任何异常 | 记录日志，不阻塞主流程 |

---

## 7. 文件结构

```
2-KNOWLEDGE/
├── 0-SCHEMA/
│   └── rag-architecture.md          # 【新】RAG架构设计文档
├── 9-RAG-INFRA/                     # 【新】RAG基础设施
│   ├── INDEX.md
│   ├── vector_store/
│   │   ├── __init__.py
│   │   ├── chunker.py               # 语义分块器
│   │   ├── embedder.py              # 向量化器
│   │   ├── build_index.py           # 构建向量索引
│   │   ├── search.py                # 语义检索
│   │   └── config.py               # 配置
│   ├── knowledge_graph/
│   │   ├── __init__.py
│   │   ├── schema.py                # 图谱Schema
│   │   ├── entity_extractor.py     # 实体关系抽取
│   │   ├── build_graph.py           # 构建知识图谱
│   │   └── graph_search.py          # 图谱检索
│   ├── rag_engine/
│   │   ├── __init__.py
│   │   ├── hybrid_retriever.py      # 混合检索
│   │   ├── reranker.py              # 重排序
│   │   └── generator.py             # RAG生成
│   ├── evolution/
│   │   ├── __init__.py
│   │   ├── ingest.py                # 采集+清洗
│   │   ├── annotate.py              # 自动标注
│   │   └── feedback.py              # 反馈机制
│   ├── chroma_db/                    # ChromaDB持久化（gitignore）
│   └── tests/
│       ├── test_chunker.py
│       ├── test_embedder.py
│       ├── test_build_index.py
│       ├── test_search.py
│       ├── test_entity_extractor.py
│       ├── test_build_graph.py
│       ├── test_graph_search.py
│       ├── test_hybrid_retriever.py
│       ├── test_reranker.py
│       ├── test_generator.py
│       ├── test_feedback.py
│       └── test_evolution.py
```

---

## 8. 实施计划

### 8.1 三阶段拆分

| 阶段 | 内容 | 模块 | 测试 | 周期 |
|------|------|------|------|------|
| **阶段1** | 向量检索层 | chunker + embedder + build_index + search | TC1-TC8 | 第1迭代 |
| **阶段2** | 知识图谱层 | schema + entity_extractor + build_graph + graph_search | TC9-TC13 | 第2迭代 |
| **阶段3** | RAG融合+进化 | hybrid_retriever + reranker + generator + evolution | TC14-TC20 | 第3迭代 |

### 8.2 硬门槛

| 门槛 | 阶段 | 条件 |
|------|------|------|
| G1 向量覆盖 | 阶段1 | 57个md文件 ≥95% 成功向量化 |
| G2 检索命中 | 阶段1 | 10个标准查询 top-5命中率 ≥80% |
| G3 FAIL-OPEN | 阶段1 | 模型不可用时TF-IDF回退正常 |
| G4 图谱覆盖 | 阶段2 | ≥200节点 / ≥500关系 |
| G5 图谱多跳 | 阶段2 | 2跳查询正确返回间接关联 |
| G6 RAG可溯源 | 阶段3 | 回答引用率 ≥90% |
| G7 幻觉率 | 阶段3 | 无知识支撑断言 ≤10% |
| G8 进化闭环 | 阶段3 | 新文档归档后自动索引 |

### 8.3 验收标准

- **阶段1验收：** G1+G2+G3 全部通过，向量检索可用
- **阶段2验收：** G4+G5 全部通过，图谱检索可用
- **阶段3验收：** G6+G7+G8 全部通过，RAG融合+进化闭环完整

---

## 9. 与现有系统的集成

### 9.1 与2-KNOWLEDGE的集成

| 集成点 | 说明 |
|--------|------|
| 向量索引数据源 | 2-KNOWLEDGE下所有md文件 |
| 图谱实体来源 | md文件中的模块/概念/参数 |
| 进化采集 | 7-EXTERNAL-RESEARCH归档触发索引更新 |
| 0-SCHEMA/rag-architecture.md | RAG架构设计文档 |

### 9.2 与4-MEMORY的桥接

| 方向 | 机制 |
|------|------|
| 知识库→记忆 | RAG检索结果record为C级记忆 |
| 记忆→知识库 | verify结果反哺知识库块权重 |

### 9.3 与开发流程的集成

| 场景 | 触发 | 动作 |
|------|------|------|
| 开发对话中调研 | AI检测到WebSearch/GitHub分析 | 提示归档到7-EXTERNAL-RESEARCH → 自动索引 |
| 新代码模块 | git hook检测新目录 | 提示生成知识库文档 → 自动索引 |
| AI回答问题 | 查询触发知识检索 | RAG生成可溯源回答 |

---

## 10. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| bge-small模型下载失败 | 中 | 高 | 预下载到本地，TF-IDF fallback |
| Neo4j部署复杂 | 中 | 中 | 阶段2可选，先用NetworkX替代验证 |
| 向量化57文件耗时长 | 低 | 低 | 增量更新，首次构建后仅更新变更 |
| RAG回答质量不达标 | 中 | 高 | prompt工程迭代+反馈优化 |
| 知识图谱实体抽取错误 | 中 | 中 | 规则+人工审核，逐步迭代 |

---

## 11. 附录

### 11.1 中信建投参考

详见 [7-EXTERNAL-RESEARCH/finance/risk-models/中信建投知识库管理体系调研.md](../../2-KNOWLEDGE/7-EXTERNAL-RESEARCH/finance/risk-models/中信建投知识库管理体系调研.md)

### 11.2 术语表

| 术语 | 含义 |
|------|------|
| RAG | Retrieval-Augmented Generation，检索增强生成 |
| 向量检索 | 基于embedding的语义相似度检索 |
| 知识图谱 | 实体-关系网络，支持多跳推理 |
| 语义分块 | 按文档结构切分，保留上下文 |
| 混合检索 | 向量+图谱+关键词三路召回 |
| 持续进化 | 采集→清洗→标注→索引→反馈→进化闭环 |
| FAIL-OPEN | 异常时回退不阻塞，保证可用性 |

---

_最后更新：2026-08-30 | 状态：Draft_
