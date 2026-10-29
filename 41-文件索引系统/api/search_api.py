"""
search_api.py — 统一检索接口
============================
SPEC-41-文件索引系统 v0.6 §5（部署形态见 §3.2：Python 库直调 + Next.js API Route 封装）
职责：
  1. search(query, filters?, limit)  — 统一检索（L1+L2 合并，Evidence-First）
  2. rebuild(scope?)                 — 全量重建（L1+L2）
  3. update(paths?)                  — 增量更新
  4. status()                        — 索引健康度（SPEC §8.1 六项指标）
  5. recall(query, topK)             — BM25 式候选召回（供案例库补充注入，§5.4）
权限模型（SPEC §5.5）：
  - 前端用户：user_id 传入，按可见范围过滤（私有内容仅本人）
  - 内部 Agent：FIS_AGENT_TOKEN 环境变量凭证，全量可见；进程内直调豁免
  - 校验失败 FAIL-OPEN：返回空结果并记日志，不抛异常
位置: 41-文件索引系统/api/search_api.py
"""
from __future__ import annotations
import json
import logging
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

from core.db import Database
from core.incremental import L2Indexer, LazyValidator
from core.searcher import Searcher

logger = logging.getLogger("fis")

# 私有内容路径约定（与 config/index_rules.yaml visibility 段同源维护，SPEC §5.5）
PRIVATE_PATH_MARKERS = ("private/", "drafts/")


class SearchAPI:
    """统一检索接口（Python 库直调形态；前端经 Next.js API Route 代理调用）。

    用法（进程内直调，Agent 豁免凭证）::
        api = SearchAPI(root="/path/to/project")
        result = api.search("部署文档")
    """

    def __init__(self, root: str, db: Optional[Database] = None) -> None:
        self.root = Path(root).resolve()
        self.db = db or Database.instance()
        self.searcher = Searcher(db=self.db)
        self.l2 = L2Indexer(root=str(self.root), db=self.db)
        self.lazy = LazyValidator(root=str(self.root), db=self.db)

    # ---------- 权限过滤（SPEC §5.5） ----------

    @staticmethod
    def _is_private(path: str) -> bool:
        p = path.lower()
        return any(m in p for m in PRIVATE_PATH_MARKERS)

    def _apply_visibility(self, hits: List, user_id: Optional[str], agent_authorized: bool) -> List:
        """按调用方身份过滤：Agent 全量可见；前端用户私有内容仅本人。"""
        if agent_authorized:
            return hits
        return [
            h for h in hits
            if not self._is_private(h.source["path"]) or (user_id and user_id in h.source["path"])
        ]

    @staticmethod
    def _check_agent_token(token: Optional[str]) -> bool:
        """校验内部 Agent 凭证（Bearer）。失败 FAIL-OPEN 由调用方处理。"""
        expected = os.environ.get("FIS_AGENT_TOKEN", "")
        if not expected:
            return False
        return bool(token) and token == expected

    # ---------- 检索接口（SPEC §5.1） ----------

    def search(
        self,
        query: str,
        filters: Optional[Dict] = None,
        limit: int = 20,
        user_id: Optional[str] = None,
        agent_token: Optional[str] = None,
    ) -> Dict:
        """统一检索。返回 SPEC §4.2 结构。

        - user_id：前端用户（NextAuth 会话解析后传入）
        - agent_token：内部 Agent Bearer 凭证（进程内直调可豁免——不传且 user_id 为空时视为内部直调）
        """
        agent_authorized = self._check_agent_token(agent_token) or (
            agent_token is None and user_id is None  # 进程内直调豁免（SPEC §5.5）
        )
        if not agent_authorized and not user_id:
            # 凭证校验失败 → FAIL-OPEN：空结果 + 日志（SPEC §5.5）
            logger.warning("credential check failed, FAIL-OPEN empty result")
            return {"query": query, "hits": [], "total": 0, "took_ms": 0}
        # 惰性校验（SPEC §2.3）：超预算降级跳过，不阻塞检索
        lazy = self.lazy.check()
        if lazy["changed"] and not lazy["degraded"]:
            self.l2.update_changed()
        result = self.searcher.search(query, filters=filters, limit=limit)
        hits = self._apply_visibility(result.hits, user_id, agent_authorized)
        return {
            "query": query,
            "hits": [asdict(h) for h in hits],
            "total": result.total,
            "took_ms": result.took_ms,
        }

    # ---------- 索引管理（SPEC §5.2） ----------

    def rebuild(self, scope: Optional[str] = None) -> Dict:
        """全量重建（L1+L2）。schema 不兼容时由 db 层触发（SPEC §4.1）。"""
        t0 = time.monotonic()
        stats = self.l2.rebuild()
        stats["took_ms"] = int((time.monotonic() - t0) * 1000)
        logger.info("rebuild done: %s", json.dumps(stats, ensure_ascii=False))
        return stats

    def update(self, paths: Optional[List[str]] = None) -> Dict:
        """增量更新（paths 为空时全范围检测变更）。"""
        t0 = time.monotonic()
        stats = self.l2.update_changed()
        stats["took_ms"] = int((time.monotonic() - t0) * 1000)
        logger.info("update done: %s", json.dumps(stats, ensure_ascii=False))
        return stats

    def status(self) -> Dict:
        """索引健康度（SPEC §8.1 六项指标）。"""
        with self.db.connection() as conn:
            indexed_files = conn.execute("SELECT count(*) FROM files").fetchone()[0]
            chunk_count = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
            token_count = conn.execute("SELECT count(*) FROM tokens").fetchone()[0]
            last_indexed = conn.execute(
                "SELECT max(indexed_at) FROM files"
            ).fetchone()[0]
        lazy = self.lazy.check()
        # v1.1：reconcile_diff 增加 wiki 页面变更维度（SPEC §8.1，对齐 §7.11 lint 对账联动）
        with self.db.connection() as conn:
            wiki_total = conn.execute(
                "SELECT count(*) FROM files WHERE type='wiki'"
            ).fetchone()[0]
        return {
            "indexed_files": indexed_files,
            "chunks": chunk_count,
            "tokens": token_count,
            "index_freshness": {
                "last_indexed_at": last_indexed.isoformat() if last_indexed else None,
                "lazy_check_ms": lazy["took_ms"],
                "lazy_degraded": bool(lazy["degraded"]),
            },
            "reconcile_diff": {
                "changed": lazy["changed"],
                "wiki_pages": wiki_total,  # wiki 页面维度（变更检测经惰性校验/定时对账覆盖）
            },
            "search_p95_ms": self.searcher.search_p95_ms,
            "recall_p95_ms": self.searcher.recall_p95_ms,
            "schema_version": self.db.schema_version(),
        }

    # ---------- 候选召回（SPEC §5.4，供案例库补充注入） ----------

    # ---------- L1 文件清单查询（A1，SPEC §5.6，供 SACG DocIndexView 消费） ----------
    def list_files(
        self,
        root: Optional[str] = None,
        type: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 500,
    ) -> Dict:
        """L1 元数据清单查询（files 表，毫秒级）。

        - root：根目录名过滤（如 0-系统文档管理 / 2-KNOWLEDGE）
        - type：文件类型过滤（doc/report/strategy/memory/case/code/wiki/skill）
        - category：SACG 分类（由 type + 路径推导，兼容 SACG DocItem）
        - 返回字段对齐 SACG DocItem：path/root/category/last_synced/size_bytes
        """
        rows = self.db.query_files(root=root, type=type, limit=limit)
        items = []
        for r in rows:
            p = r["path"]
            parts = p.split("/", 1)
            file_root = parts[0] if len(parts) > 1 else ""
            # category 推导：优先显式参数，否则 type + 路径首段
            cat = category or (r["type"] if r["type"] != "doc" else ("doc:" + file_root if file_root else "doc"))
            items.append({
                "path": p,
                "root": file_root,
                "category": cat,
                "last_synced": r["indexed_at"].isoformat() if hasattr(r["indexed_at"], "isoformat") else str(r["indexed_at"]),
                "size_bytes": r["size"],
            })
        return {"files": items, "count": len(items)}

    def recall(self, query: str, topK: int = 50, agent_token: Optional[str] = None) -> List[Dict]:
        """BM25 式候选召回（chunk 级）。凭证校验失败 FAIL-OPEN 返回空列表。"""
        if not self._check_agent_token(agent_token) and agent_token is not None:
            logger.warning("recall credential check failed, FAIL-OPEN empty result")
            return []
        return self.searcher.recall(query, topK=topK)
