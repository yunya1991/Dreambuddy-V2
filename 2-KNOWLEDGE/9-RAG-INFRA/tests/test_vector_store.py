# -*- coding: utf-8 -*-
"""向量检索层测试（TC1-TC8）。

测试在临时目录运行，不污染真实知识库。
本机未缓存 bge 模型时，直接启用 TF-IDF 回退路径（与生产 FAIL-OPEN 一致），
TC6 通过桩接 sentence_transformers 模块验证“模型不可用即回退”的检测逻辑。
"""

import os

# 关闭 ChromaDB 遥测，避免测试环境发起网络请求
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

import sys
import types
from pathlib import Path

# 将 9-RAG-INFRA 加入 sys.path，使 vector_store 可作为包导入
_RAG_INFRA_DIR = Path(__file__).resolve().parent.parent
if str(_RAG_INFRA_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_INFRA_DIR))

import pytest
from vector_store import build_index, search, chunk_markdown, Embedder
from vector_store.embedder import _embedder

# 测试环境未缓存 bge 模型：直接启用 TF-IDF 回退路径（与生产 FAIL-OPEN 行为一致），
# 同时避免加载真实模型时导入 torch，保持测试快速且不依赖网络。
_embedder._use_tfidf_fallback = True
_embedder._model = None

# === 测试用 Markdown 固件（4 文件，3 域） ===
FIXTURES = {
    "1-TRADING/BCRM推理引擎.md": """# BCRM推理引擎

> 二元矛盾推理模型，用于识别市场矛盾

## 核心架构

BCRM推理模型通过逐层推理识别市场矛盾，最终输出交易信号。

## 推理链路

K线数据进入L1模型，再经L2融合模型，映射为卦象，产出交易方向。

## 关键参数

L1模型共344个推理单元，L2模型共278个，推理模式为严格模式，失败不降级。
""",
    "1-TRADING/V9马丁基线.md": """# V9马丁基线

## 策略概述

V9马丁基线策略核心参数

## 执行逻辑

马丁加仓遵循网格与风控双重约束，逐档执行。

## 风控规则

单笔最大亏损不超过本金的百分之二，触发后停止加仓。
""",
    "2-TECHNICAL/数据管道.md": """# 数据管道

## 数据源

行情数据来自交易所WebSocket与REST接口，降级时切换备用源。

## 清洗规则

异常K线剔除脏数据，按时间对齐多周期序列。
""",
    "3-THEORY/第一性原理.md": """# 第一性原理

## 定义

从最基础的不可再分假设出发，逐层推导交易系统逻辑。

## 应用

剥离表层噪音，聚焦价格与资金的本质驱动因素。
""",
}


@pytest.fixture(scope="session")
def kb_dir(tmp_path_factory):
    """会话级临时知识库目录，写入固件 Markdown。"""
    d = tmp_path_factory.mktemp("kb")
    for rel, content in FIXTURES.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return d


@pytest.fixture(scope="session")
def db_dir(tmp_path_factory):
    """会话级临时 ChromaDB 目录。"""
    return tmp_path_factory.mktemp("chromadb")


@pytest.fixture(scope="session")
def built_index(kb_dir, db_dir):
    """会话级：构建一次索引，供 TC1 校验、后续用例复用。"""
    return build_index(kb_dir, db_path=str(db_dir))


# ---------- TC1：构建索引 ----------
def test_tc1_build_index(built_index):
    stats = built_index
    assert stats["total_files"] == 4
    assert stats["total_chunks"] >= 10, stats
    assert stats["failed_chunks"] == 0, stats
    assert stats["new_chunks"] >= 10, stats
    assert stats["duration_sec"] >= 0


# ---------- TC2：增量更新 ----------
def test_tc2_incremental_update(kb_dir, db_dir):
    bcrm_rel = "1-TRADING/BCRM推理引擎.md"
    bcrm_path = kb_dir / bcrm_rel

    # 修改 BCRM 文件：仅改动一个词，保持块结构不变
    modified = bcrm_path.read_text(encoding="utf-8").replace("逐层推理", "分层推理")
    bcrm_path.write_text(modified, encoding="utf-8")

    stats = build_index(kb_dir, db_path=str(db_dir))
    expected_chunks = len(chunk_markdown(modified, bcrm_rel, "1-TRADING"))

    assert stats["total_files"] == 4
    assert stats["failed_chunks"] == 0, stats
    # 仅修改 1 个文件 → 更新块数等于该文件的块数，无新增块
    assert stats["updated_chunks"] == expected_chunks, stats
    assert stats["new_chunks"] == 0, stats


# ---------- TC3：语义检索 BCRM ----------
def test_tc3_semantic_search_bcrm(db_dir):
    results = search("BCRM推理模型", db_path=str(db_dir), top_k=5)
    assert len(results) > 0
    assert any(r["source_file"] == "1-TRADING/BCRM推理引擎.md" for r in results), \
        [r["source_file"] for r in results]


# ---------- TC4：域过滤 ----------
def test_tc4_domain_filter(db_dir):
    results = search("交易信号", domain_filter=["1-TRADING"], db_path=str(db_dir))
    assert len(results) > 0
    assert all(r["domain"] == "1-TRADING" for r in results), \
        [r["domain"] for r in results]


# ---------- TC5：高分阈值 ----------
def test_tc5_score_threshold(db_dir):
    # 查询与某块近乎完全一致，保证高相似度
    results = search("V9马丁基线策略核心参数", score_threshold=0.8, db_path=str(db_dir))
    assert len(results) >= 1
    assert all(r["score"] >= 0.8 for r in results), \
        [r["score"] for r in results]


# ---------- TC6：FAIL-OPEN 回退 ----------
def test_tc6_failopen_tfidf(monkeypatch):
    # 桩接 sentence_transformers 模块，避免导入真实 torch 依赖；
    # 令其构造函数抛错，模拟“模型不可用”，验证 FAIL-OPEN 回退 TF-IDF。
    fake_st = types.ModuleType("sentence_transformers")

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated model unavailable")

    fake_st.SentenceTransformer = _boom
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_st)

    emb = Embedder()
    vec = emb.embed("测试文本回退向量")
    assert emb._use_tfidf_fallback is True
    assert vec.shape == (512,)
    assert vec.dtype.name == "float32"


# ---------- TC7：空查询 ----------
def test_tc7_empty_query(db_dir):
    for q in ["", "   ", None]:
        assert search(q, db_path=str(db_dir)) == []


# ---------- TC8：代码块保留不拆分 ----------
def test_tc8_code_block_intact():
    md = """# 测试代码块

说明文字一段。

```python
def hello():
    print("hello")
    return 42
```

结尾文字一段。
"""
    chunks = chunk_markdown(md, "demo.md", "root")
    code_chunks = [c for c in chunks if c["metadata"]["chunk_type"] == "code"]
    assert len(code_chunks) == 1, [c["metadata"]["chunk_type"] for c in chunks]
    code = code_chunks[0]["content"]
    assert "def hello():" in code
    assert 'print("hello")' in code
    assert "return 42" in code
