# -*- coding: utf-8 -*-
"""IndexQueryService — 索引语义查询服务

职责：
  1. 将 INDEX.md（知识库目录索引）和 skill-registry.json（SKILL 注册元数据）
     解析为结构化索引条目，向量化到独立的 ChromaDB collection。
  2. 提供语义查询接口，返回 IndexReference（文档/代码/SKILL 定位）。

设计原则（基于经验教训 VM-100018519 / VM-100005240）：
  - 检索配置（top_k / score_threshold / category_filter）映射到流水线决策点，
    不做"只保存不执行"的伪配置。
  - 统一 score 量纲为 0~1 余弦相似度，阈值与 score 同域。
  - 过滤与截断放在重排之后、返回之前，避免低质量条目提前丢弃。
  - FAIL-OPEN：ChromaDB/模型不可用时回退到关键词匹配，不阻塞调用方。

位置: 2-KNOWLEDGE/9-RAG-INFRA/index_query_service.py
"""

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

# === 路径设置 ===
_THIS_DIR = Path(__file__).resolve().parent
_VS_DIR = _THIS_DIR / "vector_store"
for _p in [_THIS_DIR, _VS_DIR]:
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# 直接导入 embedder 模块，绕过 vector_store/__init__.py（避免触发 chromadb 导入）
import importlib.util
_embedder_path = _VS_DIR / "embedder.py"
_spec = importlib.util.spec_from_file_location("embedder", _embedder_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_embedder = _mod._embedder

# 直接加载 config
_config_path = _VS_DIR / "config.py"
_spec2 = importlib.util.spec_from_file_location("vs_config", _config_path)
_mod2 = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(_mod2)
config = _mod2

try:
    import chromadb
except ImportError:
    chromadb = None


# === 索引配置 ===
INDEX_COLLECTION = "dreambuddy_index"
DEFAULT_TOP_K = 5
DEFAULT_SCORE_THRESHOLD = 0.3  # 余弦相似度 0~1，与 score 同域

# 项目根目录（用于解析相对路径）
_PROJECT_ROOT = _THIS_DIR.parent.parent


def _project_root() -> Path:
    return _PROJECT_ROOT


# ============================================================
# 1. 索引条目解析
# ============================================================

def parse_index_md(index_path: Path) -> List[Dict]:
    """解析单个 INDEX.md，提取目录条目。

    支持的格式：
      - ## 标题
      - - [名称](相对路径) 描述
      - | 名称 | 路径 | 描述 | （表格行）
    """
    if not index_path.exists():
        return []

    content = index_path.read_text(encoding="utf-8", errors="ignore")
    entries: List[Dict] = []
    current_heading = ""

    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue

        # 标题行
        heading_match = re.match(r"^#{1,6}\s+(.+)", line)
        if heading_match:
            current_heading = heading_match.group(1).strip()
            continue

        # Markdown 链接：[name](path)
        link_match = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", line)
        for name, rel_path in link_match:
            abs_path = (index_path.parent / rel_path).resolve()
            entries.append({
                "title": name.strip(),
                "path": str(abs_path),
                "category": "doc",
                "description": line.split("]")[-1].strip(" -:：") if "]" in line else current_heading,
                "domain": current_heading or index_path.parent.name,
            })

        # 表格行：| name | path | desc |
        if line.startswith("|") and "|" in line[1:]:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 2 and not cells[0].startswith("---"):
                name = cells[0]
                path_cell = cells[1] if len(cells) > 1 else ""
                desc = cells[2] if len(cells) > 2 else current_heading
                # 路径可能是 markdown 链接或纯路径
                link_in_cell = re.search(r"\[([^\]]+)\]\(([^)]+)\)", path_cell)
                if link_in_cell:
                    rel_path = link_in_cell.group(2)
                else:
                    rel_path = path_cell
                if rel_path:
                    abs_path = (index_path.parent / rel_path).resolve()
                    entries.append({
                        "title": name,
                        "path": str(abs_path),
                        "category": "doc",
                        "description": desc,
                        "domain": current_heading or index_path.parent.name,
                    })

    return entries


def parse_skill_registry(registry_path: Path) -> List[Dict]:
    """解析 skill-registry.json，提取 SKILL 元数据条目。"""
    if not registry_path.exists():
        return []

    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    skills = data.get("skills", [])
    entries: List[Dict] = []
    for s in skills:
        entries.append({
            "title": s.get("name", ""),
            "path": s.get("path", ""),
            "category": "skill",
            "description": s.get("description", ""),
            "domain": s.get("category", "general"),
            "triggers": s.get("triggers", []),
            "status": s.get("status", "unknown"),
        })
    return entries


def discover_index_files() -> List[Path]:
    """发现项目中所有 INDEX.md 文件。"""
    root = _project_root()
    # 主要索引目录
    index_dirs = [
        root / "0-系统文档管理",
        root / "1-ARCHITECTURE",
        root / "2-KNOWLEDGE",
        root / "3-CHAIN-DEVELOPMENT",
        root / "11-易经推理系统",
        root / "16-调控系统",
        root / "deploy",
    ]
    index_files: List[Path] = []
    for d in index_dirs:
        if d.exists():
            index_files.extend(d.rglob("INDEX.md"))
    return index_files


# ============================================================
# 2. 索引构建与查询
# ============================================================

class IndexQueryService:
    """索引语义查询服务。"""

    def __init__(self, collection_name: str = INDEX_COLLECTION,
                 db_path: str = None):
        self.collection_name = collection_name
        self.db_path = db_path or config.CHROMA_DB_PATH
        self._client = None
        self._collection = None
        self._fallback_index: List[Dict] = []  # FAIL-OPEN：内存关键词索引
        self._fallback_file = Path(self.db_path).parent / "index_fallback.json"

    # ---- 初始化 ----

    def _init_client(self):
        if chromadb is None:
            return None
        try:
            if self._client is None:
                self._client = chromadb.PersistentClient(path=self.db_path)
            if self._collection is None:
                self._collection = self._client.get_or_create_collection(
                    name=self.collection_name,
                    metadata={"hnsw:space": config.DISTANCE_METRIC},
                )
            return self._collection
        except Exception:
            return None

    # ---- 构建索引 ----

    def build_index(self, index_files: Optional[List[Path]] = None,
                    registry_path: Optional[Path] = None) -> int:
        """构建索引：解析 INDEX.md + registry → 向量化 → 写入 ChromaDB。

        Returns:
            写入的条目数。FAIL-OPEN：ChromaDB 不可用时写入内存索引。
        """
        entries: List[Dict] = []

        # 1. 解析 INDEX.md
        if index_files is None:
            index_files = discover_index_files()
        for idx_file in index_files:
            entries.extend(parse_index_md(idx_file))

        # 2. 解析 skill-registry.json
        if registry_path is None:
            registry_path = _project_root() / "1-ARCHITECTURE" / "skills" / "_registry" / "registry.json"
        entries.extend(parse_skill_registry(registry_path))

        if not entries:
            return 0

        # 3. 向量化并写入
        collection = self._init_client()
        if collection is not None:
            # 清空旧索引
            try:
                collection.delete(where={})
            except Exception:
                pass

            ids = []
            documents = []
            metadatas = []
            for i, e in enumerate(entries):
                text = f"{e['title']} {e.get('description','')} {' '.join(e.get('triggers',[]))}"
                ids.append(f"idx_{i}")
                documents.append(text)
                metadatas.append({
                    "title": e["title"],
                    "path": e["path"],
                    "category": e["category"],
                    "description": e.get("description", ""),
                    "domain": e.get("domain", "general"),
                })

            # 批量嵌入
            embeddings = [_embedder.embed(doc) for doc in documents]
            collection.add(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)
        else:
            # FAIL-OPEN：持久化到文件（跨进程可用）
            self._fallback_index = entries
            try:
                self._fallback_file.parent.mkdir(parents=True, exist_ok=True)
                self._fallback_file.write_text(
                    json.dumps(entries, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                pass  # 写文件也失败则纯内存

        return len(entries)

    # ---- 查询 ----

    def query(self, query_text: str, top_k: int = DEFAULT_TOP_K,
              score_threshold: float = DEFAULT_SCORE_THRESHOLD,
              category_filter: Optional[List[str]] = None) -> List[Dict]:
        """语义查询索引。

        流水线决策点（配置 → 行为映射）：
          - top_k: 最终截断数量
          - score_threshold: 相似度过滤阈值（0~1，与 score 同域）
          - category_filter: 类别过滤（doc/skill/module/code）

        过滤与截断在重排（ChromaDB 自带相似度排序）之后执行。

        Returns:
            IndexReference 列表，每项含 title/path/category/description/score。
        """
        if not query_text or not query_text.strip():
            return []

        collection = self._init_client()
        results: List[Dict] = []

        if collection is not None and collection.count() > 0:
            query_emb = _embedder.embed(query_text)
            where = None
            if category_filter:
                where = {"category": {"$in": category_filter}}

            raw = collection.query(
                query_embeddings=[query_emb],
                n_results=top_k * 2,  # 多取一些，过滤后截断
                where=where,
            )
            metadatas = raw.get("metadatas", [[]])[0]
            documents = raw.get("documents", [[]])[0]
            distances = raw.get("distances", [[]])[0]

            for meta, doc, dist in zip(metadatas, documents, distances):
                # ChromaDB cosine distance → 相似度：score = 1 - distance
                score = max(0.0, 1.0 - float(dist))
                if score >= score_threshold:
                    results.append({
                        "title": meta.get("title", ""),
                        "path": meta.get("path", ""),
                        "category": meta.get("category", "doc"),
                        "description": meta.get("description", ""),
                        "score": round(score, 4),
                    })
        else:
            # FAIL-OPEN：关键词匹配内存索引
            results = self._keyword_fallback(query_text, top_k, category_filter)

        # 重排后统一截断
        results = results[:top_k]
        return results

    def _keyword_fallback(self, query_text: str, top_k: int,
                          category_filter: Optional[List[str]]) -> List[Dict]:
        """关键词匹配回退（ChromaDB 不可用时）。"""
        # 内存为空时从文件加载（跨进程持久化）
        if not self._fallback_index and self._fallback_file.exists():
            try:
                self._fallback_index = json.loads(
                    self._fallback_file.read_text(encoding="utf-8")
                )
            except Exception:
                pass
        if not self._fallback_index:
            return []

        query_terms = set(re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fa5]", query_text.lower()))
        scored: List[Dict] = []
        for e in self._fallback_index:
            if category_filter and e.get("category") not in category_filter:
                continue
            text = f"{e['title']} {e.get('description','')}".lower()
            hits = sum(1 for t in query_terms if t in text)
            if hits > 0:
                score = hits / max(len(query_terms), 1)
                scored.append({**e, "score": round(score, 4)})

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def count(self) -> int:
        """返回索引条目总数。"""
        collection = self._init_client()
        if collection is not None:
            return collection.count()
        # fallback: 从文件加载
        if not self._fallback_index and self._fallback_file.exists():
            try:
                self._fallback_index = json.loads(
                    self._fallback_file.read_text(encoding="utf-8")
                )
            except Exception:
                pass
        return len(self._fallback_index)


# ============================================================
# 3. CLI 入口
# ============================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="IndexQueryService")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build", help="构建索引")
    p_build.add_argument("--registry", type=Path, default=None)

    p_query = sub.add_parser("query", help="查询索引")
    p_query.add_argument("query_text", type=str)
    p_query.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    p_query.add_argument("--threshold", type=float, default=DEFAULT_SCORE_THRESHOLD)
    p_query.add_argument("--category", nargs="*", default=None)

    args = parser.parse_args()
    svc = IndexQueryService()

    if args.cmd == "build":
        n = svc.build_index(registry_path=args.registry)
        print(f"✅ 索引构建完成: {n} 条")
    elif args.cmd == "query":
        results = svc.query(args.query_text, top_k=args.top_k,
                            score_threshold=args.threshold,
                            category_filter=args.category)
        print(f"查询: {args.query_text} (top_k={args.top_k}, threshold={args.threshold})")
        print(f"返回 {len(results)} 条:")
        for r in results:
            print(f"  [{r['category']}] {r['title']} (score={r['score']})")
            print(f"    {r['path']}")


if __name__ == "__main__":
    main()
