"""
searcher.py — 检索引擎
======================
SPEC-41-文件索引系统 v0.6 §5（P0: L1 文件名检索 / P1: L2 倒排检索）
职责：
  1. search()：统一检索入口——L1 文件名/路径匹配 + L2 倒排匹配，BM25 式打分合并
  2. recall()：BM25 式候选召回（供案例库补充注入，SPEC §5.4/§7.6）
  3. Evidence-First：每条命中带 source/score/snippet/indexed_at（SPEC §2.1）
设计原则：
  1. 检索耗时统计（search_p95_ms/recall_p95_ms 指标来源，SPEC §8.1）
  2. 权限过滤在 search_api 层执行，索引层不过滤（SPEC §5.5）
位置: 41-文件索引系统/core/searcher.py
"""
from __future__ import annotations
import json
import math
import subprocess
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .db import Database


@dataclass
class Hit:
    """单条命中结果（Evidence-First，SPEC §2.1/§4.2）。"""
    source: Dict          # {"path": ..., "line": ...}
    score: float          # 0.0-1.0
    snippet: str          # 命中上下文片段
    type: str             # doc/report/strategy/memory/case/code
    indexed_at: str


@dataclass
class SearchResult:
    """检索结果（SPEC §4.2 结构）。"""
    query: str
    hits: List[Hit] = field(default_factory=list)
    total: int = 0
    took_ms: int = 0


class Searcher:
    """检索引擎。

    用法::
        searcher = Searcher()
        result = searcher.search("部署文档", limit=20)
        chunks = searcher.recall("nginx 配置", topK=50)
    """

    # P95 滑动窗口（SPEC §8.1：滑动窗口 1000 次）
    _WINDOW = 1000

    def __init__(self, db: Optional[Database] = None) -> None:
        self.db = db or Database.instance()
        self._search_latencies: deque = deque(maxlen=self._WINDOW)
        self._recall_latencies: deque = deque(maxlen=self._WINDOW)

    # ---------- 指标（status() 消费） ----------

    @property
    def search_p95_ms(self) -> int:
        return self._p95(self._search_latencies)

    @property
    def recall_p95_ms(self) -> int:
        return self._p95(self._recall_latencies)

    @staticmethod
    def _p95(window: deque) -> int:
        if not window:
            return 0
        s = sorted(window)
        return int(s[min(len(s) - 1, math.ceil(0.95 * len(s)) - 1)])

    # ---------- 统一检索（SPEC §5.1） ----------

    def search(
        self,
        query: str,
        filters: Optional[Dict] = None,
        limit: int = 20,
    ) -> SearchResult:
        """统一检索：L1 文件名匹配 + L2 倒排匹配，合并去重按得分排序。

        filters: {"type": [...], "module": [...], "since": ts, "until": ts}
        """
        t0 = time.monotonic()
        limit = max(1, min(int(limit), 100))  # 上限 100（SPEC §5.1）
        hits: Dict[str, Hit] = {}
        # L1：文件名/路径匹配（P0 能力）
        for hit in self._search_l1(query, filters, limit):
            hits.setdefault(hit.source["path"], hit)
        # L2：倒排匹配（P1 能力，chunks 表有数据时生效）
        for hit in self._search_l2(query, filters, limit):
            path = hit.source["path"]
            if path in hits:
                # 同文件取高分，分数叠加衰减（避免单文件刷屏）
                prev = hits[path]
                hits[path] = hit if hit.score > prev.score else prev
            else:
                hits[path] = hit
        # L3：向量召回（P5 能力，D1——ChromaDB 桥接，FAIL-OPEN 降级纯 BM25）
        for hit in self._search_l3(query, filters, limit):
            path = hit.source["path"]
            if path in hits:
                prev = hits[path]
                hits[path] = hit if hit.score > prev.score else prev
            else:
                hits[path] = hit
        ranked = sorted(hits.values(), key=lambda h: -h.score)[:limit]
        took = int((time.monotonic() - t0) * 1000)
        self._search_latencies.append(took)
        return SearchResult(query=query, hits=ranked, total=len(hits), took_ms=took)

    def _search_l1(self, query: str, filters: Optional[Dict], limit: int) -> List[Hit]:
        """L1 元数据检索：文件名/路径子串匹配（大小写不敏感）。"""
        q = query.lower().strip()
        if not q:
            return []
        sql = "SELECT path, type, indexed_at FROM files WHERE lower(path) LIKE %s"
        args: list = [f"%{q}%"]
        if filters and filters.get("type"):
            sql += " AND type = ANY(%s)"
            args.append(list(filters["type"]))
        sql += " ORDER BY mtime DESC LIMIT %s"
        args.append(limit)
        with self.db.connection() as conn:
            rows = conn.execute(sql, args).fetchall()
        hits: List[Hit] = []
        for path, ftype, indexed_at in rows:
            # 打分：命中位置越靠前得分越高（文件名命中 > 深路径命中）
            lower_path = path.lower()
            pos = lower_path.find(q)
            name_start = lower_path.rfind("/") + 1
            score = 0.6 if pos >= name_start else 0.4
            score *= 1.0 / (1 + 0.05 * lower_path.count("/"))  # 浅路径微加成
            hits.append(Hit(
                source={"path": path, "line": None},
                score=round(min(score, 1.0), 4),
                snippet=path,
                type=ftype,
                indexed_at=indexed_at.isoformat() if indexed_at else "",
            ))
        return hits

    def _search_l2(self, query: str, filters: Optional[Dict], limit: int) -> List[Hit]:
        """L2 倒排检索：tokens 表匹配 + BM25 式打分（chunks 有数据时生效）。"""
        from .tokenizer import tokenize  # 延迟导入（P1 模块）
        terms = tokenize(query)
        if not terms:
            return []
        # 按词分桶召回：每个查询词独立按 tf 降序取最多 1000 行（窗口函数），
        # 避免高频词挤占单一总窗口导致其他查询词的行被截断（如『意图』3460 行
        # 挤掉『注册表』623 行，新写入的意图注册表文档单词得分进不了精排前列）
        sql = (
            "SELECT path, ftype, indexed_at, heading, position, content, tf FROM ("
            "SELECT f.path, f.type AS ftype, f.indexed_at, c.heading, c.position, c.content, t.tf, "
            "row_number() OVER (PARTITION BY t.token ORDER BY t.tf DESC) AS rn "
            "FROM tokens t JOIN chunks c ON c.id = t.chunk_id "
            "JOIN files f ON f.id = c.file_id WHERE t.token = ANY(%s)"
        )
        args: list = [terms]
        if filters and filters.get("type"):
            sql += " AND ftype = ANY(%s)"
            args.append(list(filters["type"]))
        sql += ") bucketed WHERE rn <= 1000"
        with self.db.connection() as conn:
            rows = conn.execute(sql, args).fetchall()
        if not rows:
            return []
        # BM25 式打分：tf 饱和 + 多词命中加成
        chunk_scores: Dict[tuple, float] = {}
        chunk_meta: Dict[tuple, tuple] = {}
        for path, ftype, indexed_at, heading, position, content, tf in rows:
            key = (path, position)
            s = (tf / (tf + 1.2)) * (1.0 / len(terms))  # tf 饱和项
            chunk_scores[key] = chunk_scores.get(key, 0.0) + s
            chunk_meta[key] = (ftype, indexed_at, heading, content)
        # 标题命中加成：heading 包含查询词的块优先（对齐 L1 层『文件名命中优先』原则，
        # 使意图注册表等标题精确命中的元数据文档不被纯词频竞争挤出结果）
        for key, meta in chunk_meta.items():
            heading = meta[2]
            if heading and any(t in heading for t in terms):
                chunk_scores[key] = chunk_scores.get(key, 0.0) * 1.5
        hits: List[Hit] = []
        for (path, position), score in sorted(chunk_scores.items(), key=lambda x: -x[1])[:limit]:
            ftype, indexed_at, heading, content = chunk_meta[(path, position)]
            snippet = (heading + " — " if heading else "") + content[:120].replace("\n", " ")
            hits.append(Hit(
                source={"path": path, "line": position},
                score=round(min(score, 1.0), 4),
                snippet=snippet,
                type=ftype,
                indexed_at=indexed_at.isoformat() if indexed_at else "",
            ))
        return hits

    # ---------- L3 向量召回（P5/D1：ChromaDB 桥接，SPEC §5） ----------

    _BRIDGE = [
        "sudo", "-n", "-u", "luke",
        "/home/luke/venv-trading/bin/python",
        "/home/ubuntu/fis-p0/scripts/vector_bridge.py",
    ]
    _BRIDGE_TIMEOUT = 8  # 秒（超时视为向量通道不可用，FAIL-OPEN）

    def _search_l3(self, query: str, filters: Optional[Dict], limit: int) -> List[Hit]:
        """L3 向量召回：spawn venv-trading 桥接 ChromaDB（FAIL-OPEN，异常返回空）。

        开关：FIS_L3_VECTOR=1 时启用（默认关闭——保持 P0 search <100ms 验收，
        混合检索入口如 CLI cmd=search 显式开启）。
        """
        import os
        if os.environ.get("FIS_L3_VECTOR", "").lower() not in ("1", "true", "yes"):
            return []
        items = self._vector_query_daemon(query, limit)
        if items is None:
            # 常驻桥接不可用 → 降级 spawn 模式（一次性进程）
            try:
                proc = subprocess.run(
                    self._BRIDGE,
                    input=json.dumps({"query": query, "top_k": min(limit, 10)}),
                    capture_output=True,
                    text=True,
                    timeout=self._BRIDGE_TIMEOUT,
                )
                items = json.loads(proc.stdout or "[]")
                if not isinstance(items, list):
                    return []
            except Exception:
                return []
        hits: List[Hit] = []
        for it in items[:limit]:
            sf = str(it.get("source_file") or "").strip("/")
            if not sf:
                continue
            row = self._lookup_file(sf, filters)
            if not row:
                continue  # 41 未索引的文件不进入结果（保持 Evidence 可溯源）
            path, ftype, indexed_at = row
            snippet = (it.get("heading") + " — " if it.get("heading") else "") + str(it.get("snippet") or "")[:120].replace("\n", " ")
            hits.append(Hit(
                source={"path": path, "line": None},
                score=round(min(float(it.get("score") or 0.0), 1.0), 4),
                snippet=snippet,
                type=ftype,
                indexed_at=indexed_at.isoformat() if indexed_at else "",
            ))
        return hits

    _DAEMON_SOCK = "/tmp/fis_vector_bridge.sock"
    _DAEMON_TIMEOUT = 2  # 秒（常驻桥接查询超时，超时降级 spawn）

    def _vector_query_daemon(self, query: str, limit: int):
        """常驻桥接查询：成功返回 list，不可用/异常返回 None（降级 spawn）。"""
        import socket as _socket
        try:
            s = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
            s.settimeout(self._DAEMON_TIMEOUT)
            s.connect(self._DAEMON_SOCK)
            s.sendall(json.dumps({"query": query, "top_k": min(limit, 10)}).encode("utf-8") + b"\n")
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
            s.close()
            line = buf.split(b"\n", 1)[0].decode("utf-8", "replace").strip()
            if not line:
                return None
            resp = json.loads(line)
            if not resp.get("ok"):
                return None
            items = resp.get("results")
            return items if isinstance(items, list) else None
        except Exception:
            return None

    def _lookup_file(self, source_file: str, filters: Optional[Dict]):
        """向量 source_file（相对 2-KNOWLEDGE）→ 41 files.path（带模块前缀）。"""
        sql = "SELECT path, type, indexed_at FROM files WHERE path = %s OR path LIKE %s LIMIT 1"
        args: list = [source_file, "%/" + source_file]
        if filters and filters.get("type"):
            sql = sql.replace("LIMIT 1", "AND type = ANY(%s) LIMIT 1")
            args.append(list(filters["type"]))
        try:
            with self.db.connection() as conn:
                return conn.execute(sql, args).fetchone()
        except Exception:
            return None

    # ---------- 候选召回（SPEC §5.4，供案例库补充注入） ----------

    def recall(self, query: str, topK: int = 50) -> List[Dict]:
        """BM25 式候选召回：返回 chunk 级候选（path/heading/position/content/score）。"""
        t0 = time.monotonic()
        topK = max(1, min(int(topK), 200))
        result = [
            {
                "path": h.source["path"],
                "line": h.source.get("line"),
                "heading": "",
                "score": h.score,
                "snippet": h.snippet,
                "type": h.type,
            }
            for h in self._search_l2(query, None, topK)
        ]
        self._recall_latencies.append(int((time.monotonic() - t0) * 1000))
        return result
