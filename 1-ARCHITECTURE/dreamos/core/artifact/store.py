"""产物中台核心存储 (M1)

统一存储 DreamOS 产物，支持按类型/标签/时间检索。
存储路径: {DATA_ROOT}/artifacts/{artifact_type}/{artifact_id}.json
"""

import json
import time
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class ArtifactType(str, Enum):
    """产物类型枚举 (F7.5 扩展)"""
    INSIGHT_CARD = "insight_card"
    MOOD_BOARD = "mood_board"
    BULL_BEAR_DEBATE = "bull_bear_debate"
    BRIEFING = "briefing"
    REPORT = "report"
    CHART = "chart"


class ArtifactMeta:
    """产物元数据"""

    def __init__(
        self,
        artifact_id: str,
        artifact_type: ArtifactType,
        title: str,
        created_at: float,
        tags: Optional[List[str]] = None,
        source: Optional[str] = None,
        summary: Optional[str] = None,
    ):
        self.artifact_id = artifact_id
        self.artifact_type = artifact_type
        self.title = title
        self.created_at = created_at
        self.tags = tags or []
        self.source = source
        self.summary = summary

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type.value,
            "title": self.title,
            "created_at": self.created_at,
            "created_at_iso": datetime.fromtimestamp(self.created_at).isoformat(),
            "tags": self.tags,
            "source": self.source,
            "summary": self.summary,
        }


class ArtifactStore:
    """产物中台存储

    用法:
        store = ArtifactStore()
        artifact_id = store.save(
            artifact_type=ArtifactType.BRIEFING,
            title="2026-09-28 盘前简报",
            data={...},
            tags=["daily", "pre-market"],
        )
        briefs = store.list(artifact_type=ArtifactType.BRIEFING)
        full = store.get(artifact_id)
    """

    def __init__(self, data_root: Optional[Path] = None):
        if data_root is None:
            # 默认: dreamos/scheduler_data/artifacts
            data_root = Path(__file__).resolve().parent.parent.parent / "scheduler_data"
        self._root = data_root / "artifacts"
        self._root.mkdir(parents=True, exist_ok=True)

    def _type_dir(self, artifact_type: ArtifactType) -> Path:
        d = self._root / artifact_type.value
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _artifact_path(self, artifact_type: ArtifactType, artifact_id: str) -> Path:
        return self._type_dir(artifact_type) / f"{artifact_id}.json"

    def save(
        self,
        artifact_type: ArtifactType,
        title: str,
        data: Dict[str, Any],
        tags: Optional[List[str]] = None,
        source: Optional[str] = None,
        summary: Optional[str] = None,
        artifact_id: Optional[str] = None,
    ) -> str:
        """保存产物，返回 artifact_id"""
        artifact_id = artifact_id or f"{artifact_type.value}_{uuid.uuid4().hex[:12]}"
        now = time.time()
        meta = ArtifactMeta(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            title=title,
            created_at=now,
            tags=tags,
            source=source,
            summary=summary,
        )
        record = {
            "meta": meta.to_dict(),
            "data": data,
        }
        path = self._artifact_path(artifact_type, artifact_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2, default=str)
        return artifact_id

    def get(self, artifact_id: str, artifact_type: Optional[ArtifactType] = None) -> Optional[Dict[str, Any]]:
        """获取产物完整内容（meta + data）"""
        if artifact_type:
            path = self._artifact_path(artifact_type, artifact_id)
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
            return None
        # 跨类型搜索
        for at in ArtifactType:
            path = self._artifact_path(at, artifact_id)
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        return None

    def list(
        self,
        artifact_type: Optional[ArtifactType] = None,
        tags: Optional[List[str]] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """列出产物（仅 meta，不含 data，避免大 payload）"""
        metas: List[Dict[str, Any]] = []
        types = [artifact_type] if artifact_type else list(ArtifactType)
        for at in types:
            d = self._type_dir(at)
            for f in sorted(d.glob("*.json"), reverse=True):
                try:
                    record = json.loads(f.read_text(encoding="utf-8"))
                    meta = record.get("meta", {})
                    if tags and not set(tags).issubset(set(meta.get("tags", []))):
                        continue
                    metas.append(meta)
                except (json.JSONDecodeError, OSError):
                    continue
        metas.sort(key=lambda m: m.get("created_at", 0), reverse=True)
        return metas[offset:offset + limit]

    def delete(self, artifact_id: str, artifact_type: Optional[ArtifactType] = None) -> bool:
        """删除产物"""
        if artifact_type:
            path = self._artifact_path(artifact_type, artifact_id)
            if path.exists():
                path.unlink()
                return True
            return False
        for at in ArtifactType:
            path = self._artifact_path(at, artifact_id)
            if path.exists():
                path.unlink()
                return True
        return False

    # ── M3: 产物搜索 ──────────────────────────────

    def search(
        self,
        keyword: str,
        artifact_type: Optional[ArtifactType] = None,
        tags: Optional[List[str]] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """M3: 关键词搜索产物

        搜索范围: title / summary / tags / data (递归字符串匹配)
        """
        if not keyword:
            return []
        kw = keyword.lower()
        results: List[Dict[str, Any]] = []
        types = [artifact_type] if artifact_type else list(ArtifactType)

        def _match_text(text: Any) -> bool:
            if text is None:
                return False
            return kw in str(text).lower()

        def _match_recursive(obj: Any) -> bool:
            """递归搜索 data 中的字符串值"""
            if isinstance(obj, str):
                return _match_text(obj)
            if isinstance(obj, dict):
                return any(_match_recursive(v) for v in obj.values())
            if isinstance(obj, list):
                return any(_match_recursive(v) for v in obj)
            return False

        for at in types:
            d = self._type_dir(at)
            for f in sorted(d.glob("*.json"), reverse=True):
                try:
                    record = json.loads(f.read_text(encoding="utf-8"))
                    meta = record.get("meta", {})
                    data = record.get("data", {})
                    # tag 过滤
                    if tags and not set(tags).issubset(set(meta.get("tags", []))):
                        continue
                    # 关键词匹配: title / summary / tags / data
                    hit = (
                        _match_text(meta.get("title"))
                        or _match_text(meta.get("summary"))
                        or any(_match_text(t) for t in meta.get("tags", []))
                        or _match_recursive(data)
                    )
                    if hit:
                        results.append(meta)
                except (json.JSONDecodeError, OSError):
                    continue
        results.sort(key=lambda m: m.get("created_at", 0), reverse=True)
        return results[:limit]

    def stats(self) -> Dict[str, Any]:
        """M2: 产物统计 (按类型计数)"""
        counts: Dict[str, int] = {}
        total_size = 0
        for at in ArtifactType:
            d = self._type_dir(at)
            files = list(d.glob("*.json"))
            counts[at.value] = len(files)
            for f in files:
                total_size += f.stat().st_size
        return {
            "total": sum(counts.values()),
            "by_type": counts,
            "total_size_bytes": total_size,
        }
