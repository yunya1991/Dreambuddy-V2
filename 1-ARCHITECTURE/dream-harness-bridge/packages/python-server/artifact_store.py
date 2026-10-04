#!/usr/bin/env python3
"""M1: 统一产物存储中间层 (Artifact Store)

将 subagent/agent 产生的结构化产物归一存储到中台统一管理。
支持 artifact_type 枚举: insight_card / mood_board / bull_bear_debate / briefing / report / chart

设计参考: 7-产物中台/docs/superpowers/specs/2026-05-15-3-frontend-v2-artifact-hub-design.md
- ArtifactStore: 文件系统产物写入/扫描/读取
- MetaStore: SQLite 元数据 (artifact_uri → metadata 映射)

与 D1 (artifact_uri) 协同: subagent 输出 artifact_uri, 此模块负责持久化。
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional
from pathlib import Path


# ── 产物类型枚举 ──────────────────────────────

ARTIFACT_TYPES = {
    "insight_card": "洞察卡片",
    "mood_board": "情绪板",
    "bull_bear_debate": "多空辩论",
    "briefing": "每日简报",
    "report": "分析报告",
    "chart": "图表",
    "decision_log": "决策日志",
}


# ── 路径解析 ──────────────────────────────────

def _resolve_artifacts_root() -> str:
    """解析产物根目录 (与前端 task-manager.ts ARTIFACTS_DIR 对齐)"""
    home = os.environ.get("HOME", "/Users/zhangjiangtao")
    repo_root = os.environ.get("DREAMBUDDY_ROOT", os.path.join(home, "WorkBuddy/dreambuddy-v2"))

    # 优先 dreambuddy/artifacts, fallback 到 repo root
    dreambuddy_path = os.path.join(repo_root, "dreambuddy", "artifacts")
    if os.path.exists(dreambuddy_path):
        return dreambuddy_path
    return os.path.join(repo_root, "artifacts")


def _get_meta_db_path(artifacts_root: str) -> str:
    """获取 SQLite 元数据库路径"""
    meta_dir = os.path.join(artifacts_root, "meta")
    os.makedirs(meta_dir, exist_ok=True)
    return os.path.join(meta_dir, "artifact_hub.sqlite")


# ── MetaStore: SQLite 元数据层 ────────────────

class MetaStore:
    """SQLite 元数据存储 — 产物元数据索引"""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._init_schema()

    def _init_schema(self) -> None:
        """初始化数据库 schema"""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_uri TEXT PRIMARY KEY,
                    artifact_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    module TEXT,
                    tags TEXT,
                    created_at TEXT NOT NULL,
                    metadata TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_artifact_type
                ON artifacts(artifact_type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_created_at
                ON artifacts(created_at DESC)
            """)

    def store(self, artifact_uri: str, artifact_type: str, title: str,
              file_path: str, module: str = "", tags: str = "",
              metadata: str = "") -> None:
        """存储/更新产物元数据"""
        created_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO artifacts
                    (artifact_uri, artifact_type, title, file_path,
                     module, tags, created_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (artifact_uri, artifact_type, title, file_path,
                  module, tags, created_at, metadata))

    def get(self, artifact_uri: str) -> Optional[Dict[str, Any]]:
        """按 URI 获取产物元数据"""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM artifacts WHERE artifact_uri = ?",
                (artifact_uri,)
            ).fetchone()
            return dict(row) if row else None

    def list_by_type(self, artifact_type: str, limit: int = 20) -> List[Dict[str, Any]]:
        """按类型列出产物"""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM artifacts WHERE artifact_type = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (artifact_type, limit)
            ).fetchall()
            return [dict(r) for r in rows]

    def list_all(self, limit: int = 50) -> List[Dict[str, Any]]:
        """列出所有产物"""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM artifacts ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def summary(self) -> Dict[str, int]:
        """产物统计"""
        with sqlite3.connect(self._db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
            type_counts: Dict[str, int] = {}
            rows = conn.execute(
                "SELECT artifact_type, COUNT(*) as cnt "
                "FROM artifacts GROUP BY artifact_type"
            ).fetchall()
            for r in rows:
                type_counts[r[0]] = r[1]
            return {"total": total, **{f"type_{k}": v for k, v in type_counts.items()}}


# ── ArtifactStore: 统一产物存储 ──────────────

class ArtifactStore:
    """统一产物存储中间层

    用法:
        store = ArtifactStore()
        uri = store.store_artifact(
            artifact_type="insight_card",
            title="BTC 技术分析洞察",
            data={"signal": "EMA多头排列", "confidence": 0.72},
            module="technical",
        )
        artifact = store.get_artifact(uri)
        all_artifacts = store.list_artifacts()
    """

    def __init__(self, artifacts_root: Optional[str] = None):
        self._root = artifacts_root or _resolve_artifacts_root()
        self._meta = MetaStore(_get_meta_db_path(self._root))

    def store_artifact(
        self,
        artifact_type: str,
        title: str,
        data: Dict[str, Any],
        module: str = "",
        tags: str = "",
    ) -> str:
        """存储产物到文件系统 + SQLite

        Args:
            artifact_type: 产物类型 (见 ARTIFACT_TYPES)
            title: 产物标题
            data: 产物数据 (JSON 序列化)
            module: 来源模块 (technical/sentiment/...)
            tags: 逗号分隔的标签

        Returns:
            artifact_uri (如 "artifact://technical/abc12345")
        """
        # 生成 artifact_uri
        uri_hash = hash(f"{module}:{title}:{time.time()}") % 100000000
        artifact_uri = f"artifact://{module or 'unknown'}/{uri_hash:08d}"

        # 写入文件系统
        type_dir = Path(self._root) / artifact_type
        type_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"{uri_hash:08d}.json"
        file_path = type_dir / file_name

        payload = {
            "artifact_uri": artifact_uri,
            "artifact_type": artifact_type,
            "title": title,
            "module": module,
            "tags": tags,
            "data": data,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        # 写入 SQLite 元数据
        self._meta.store(
            artifact_uri=artifact_uri,
            artifact_type=artifact_type,
            title=title,
            file_path=str(file_path),
            module=module,
            tags=tags,
            metadata=json.dumps({"data_keys": list(data.keys())} if isinstance(data, dict) else {}),
        )

        return artifact_uri

    def get_artifact(self, artifact_uri: str) -> Optional[Dict[str, Any]]:
        """按 URI 获取产物完整内容"""
        meta = self._meta.get(artifact_uri)
        if not meta:
            return None
        file_path = meta["file_path"]
        if not os.path.exists(file_path):
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_artifacts(self, artifact_type: Optional[str] = None,
                       limit: int = 50) -> List[Dict[str, Any]]:
        """列出产物元数据"""
        if artifact_type:
            return self._meta.list_by_type(artifact_type, limit)
        return self._meta.list_all(limit)

    def summary(self) -> Dict[str, int]:
        """产物统计"""
        return self._meta.summary()


# ── 全局单例 ──────────────────────────────────

_store: Optional[ArtifactStore] = None


def get_artifact_store() -> ArtifactStore:
    """获取全局 ArtifactStore 单例"""
    global _store
    if _store is None:
        _store = ArtifactStore()
    return _store
