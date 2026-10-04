"""
L4 自迭代: 文档自同步
=======================
代码变更 → dream-doc-sync-workflow → 认知库 record

触发条件:
    1. 代码变更影响公开 API (新增/删除/重命名函数/类)
    2. 新增文件 (可能需要更新 INDEX)
    3. 删除文件 (需要清理引用)
    4. 配置文件变更 (可能影响行为)

同步动作:
    - 更新 0-系统文档管理/INDEX.md
    - 更新 2-KNOWLEDGE 索引
    - doc_lint + link_checker 校验
    - 认知库 record

用法:
    # record_fn 可选：未传入时自动加载认知系统 record（FAIL-OPEN）
    trigger = DocSyncTrigger(project_root=Path("/path/to/dreambuddy-v2"))
    changes = trigger.detect_changes(since_commit="HEAD~1")
    if changes.needs_sync:
        trigger.sync(changes)

自动认知闭环:
    sync() 时 tags 含 "doc-sync" → TAG_HOOKS 触发 dream-doc-sync-workflow
"""

import hashlib
import importlib.util
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── 同步触发规则 ────────────────────────────────────────
TRACKED_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".prisma", ".sql", ".yaml", ".yml"}
IGNORED_PATTERNS = {
    "__pycache__", ".pytest_cache", "node_modules", ".git",
    ".venv", "venv", "dist", "build", ".next",
}
INDEX_FILE = "0-系统文档管理/INDEX.md"
KNOWLEDGE_INDEX = "2-KNOWLEDGE"

# ── 认知系统自动加载（FAIL-OPEN）──────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_COGNITIVE_DIR = _PROJECT_ROOT / "4-MEMORY" / "9-工具与接口"
_cognitive_record_fn_cache: Optional[Callable] = None


def _load_cognitive_record_fn() -> Optional[Callable]:
    """动态加载认知系统 record 函数（FAIL-OPEN：不可用时返回 None）。

    返回的包装函数签名与 record_fn 一致：
        record_fn(content=..., quality_level=..., tags=...) -> memory_id: str
    """
    global _cognitive_record_fn_cache
    if _cognitive_record_fn_cache is not None:
        return _cognitive_record_fn_cache

    if not _COGNITIVE_DIR.exists():
        return None

    try:
        if str(_COGNITIVE_DIR) not in sys.path:
            sys.path.insert(0, str(_COGNITIVE_DIR))
        spec = importlib.util.spec_from_file_location(
            "cognitive_mcp_server", str(_COGNITIVE_DIR / "cognitive_mcp_server.py")
        )
        mcp = importlib.util.module_from_spec(spec)
        sys.modules["cognitive_mcp_server"] = mcp
        spec.loader.exec_module(mcp)

        def _record_wrapper(content: str, quality_level: str = "B",
                            tags: str = "", **kwargs: Any) -> Optional[str]:
            result = mcp._handle_record({
                "content": content,
                "quality_level": quality_level,
                "tags": tags,
                "source": kwargs.get("source", "doc_sync_trigger"),
            })
            if isinstance(result, str):
                try:
                    data = json.loads(result)
                    return data.get("memory_id")
                except (json.JSONDecodeError, ValueError):
                    return None
            return None

        _cognitive_record_fn_cache = _record_wrapper
        return _cognitive_record_fn_cache
    except Exception:  # noqa: BLE001 FAIL-OPEN
        return None


class ChangeType(str, Enum):
    ADDED = "added"          # 新增文件
    MODIFIED = "modified"    # 修改文件
    DELETED = "deleted"      # 删除文件
    RENAMED = "renamed"      # 重命名


class SyncAction(str, Enum):
    SYNC = "sync"            # 需要同步
    SKIP = "skip"            # 无需同步
    FAILED = "failed"        # 同步失败


@dataclass
class FileChange:
    """文件变更"""
    path: str
    change_type: ChangeType
    old_path: Optional[str] = None  # 重命名时
    impact_level: str = "minor"     # minor / major / critical
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "change_type": self.change_type.value,
            "old_path": self.old_path,
            "impact_level": self.impact_level,
            "reason": self.reason,
        }


@dataclass
class ChangeReport:
    """变更报告"""
    changes: List[FileChange] = field(default_factory=list)
    needs_sync: bool = False
    impact_summary: str = ""
    detected_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat() + "Z"
    )

    @property
    def major_changes(self) -> List[FileChange]:
        return [c for c in self.changes if c.impact_level in ("major", "critical")]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "changes": [c.to_dict() for c in self.changes],
            "needs_sync": self.needs_sync,
            "impact_summary": self.impact_summary,
            "detected_at": self.detected_at,
        }


@dataclass
class SyncReport:
    """同步报告"""
    action: SyncAction
    index_updated: bool = False
    knowledge_updated: bool = False
    lint_passed: bool = False
    recorded: bool = False
    memory_id: Optional[str] = None
    reason: str = ""
    synced_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat() + "Z"
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action.value,
            "index_updated": self.index_updated,
            "knowledge_updated": self.knowledge_updated,
            "lint_passed": self.lint_passed,
            "recorded": self.recorded,
            "memory_id": self.memory_id,
            "reason": self.reason,
            "synced_at": self.synced_at,
        }


class DocSyncTrigger:
    """文档自同步触发器

    检测代码变更 → 决定是否需要同步文档 → 执行同步 → 记录认知库

    用法:
        trigger = DocSyncTrigger(
            project_root=Path("/path/to/project"),
            record_fn=cognitive_record,
        )
        changes = trigger.detect_changes(checksums_before, checksums_after)
        if changes.needs_sync:
            report = trigger.sync(changes)
    """

    def __init__(
        self,
        project_root: Path,
        record_fn: Optional[Callable] = None,
        sync_fn: Optional[Callable] = None,
    ):
        self._root = project_root
        # 若未显式传入 record_fn，自动加载认知系统 record（FAIL-OPEN）
        self._record_fn = record_fn if record_fn is not None else _load_cognitive_record_fn()
        self._sync_fn = sync_fn  # dream-doc-sync-workflow 执行函数

    # ── 变更检测 ─────────────────────────────────────────

    @staticmethod
    def _file_checksum(path: Path) -> str:
        """计算文件 MD5 校验和"""
        try:
            with open(path, "rb") as f:
                return hashlib.md5(f.read()).hexdigest()
        except (OSError, IOError):
            return ""

    def _should_track(self, path: Path) -> bool:
        """判断文件是否需要跟踪"""
        rel = str(path.relative_to(self._root)) if path.is_relative_to(self._root) else str(path)

        # 忽略目录
        for ignored in IGNORED_PATTERNS:
            if ignored in rel:
                return False

        # 只跟踪特定扩展名
        return path.suffix in TRACKED_EXTENSIONS

    def _assess_impact(self, path: str, change_type: ChangeType) -> tuple:
        """评估变更影响级别"""
        level = "minor"
        reason = ""

        # API 文件变更 → major
        if any(kw in path for kw in ("api/", "route", "handler", "interface")):
            level = "major"
            reason = "API 接口变更"

        # 配置文件变更 → critical
        if path.endswith((".prisma", ".sql")):
            level = "critical"
            reason = "数据库/Schema 变更"

        # 新增文件 → major
        if change_type == ChangeType.ADDED:
            level = "major" if level == "minor" else level
            reason = reason or "新增文件"

        # 删除文件 → major
        if change_type == ChangeType.DELETED:
            level = "major" if level == "minor" else level
            reason = reason or "删除文件"

        if not reason:
            reason = "常规修改"

        return level, reason

    def detect_changes(
        self,
        before: Dict[str, str],
        after: Dict[str, str],
    ) -> ChangeReport:
        """检测文件变更

        Args:
            before: 变更前的 {path: checksum}
            after: 变更后的 {path: checksum}

        Returns:
            ChangeReport
        """
        changes: List[FileChange] = []
        before_set = set(before.keys())
        after_set = set(after.keys())

        # 新增
        for path in after_set - before_set:
            if self._should_track(Path(path)):
                level, reason = self._assess_impact(path, ChangeType.ADDED)
                changes.append(FileChange(
                    path=path,
                    change_type=ChangeType.ADDED,
                    impact_level=level,
                    reason=reason,
                ))

        # 删除
        for path in before_set - after_set:
            if self._should_track(Path(path)):
                level, reason = self._assess_impact(path, ChangeType.DELETED)
                changes.append(FileChange(
                    path=path,
                    change_type=ChangeType.DELETED,
                    impact_level=level,
                    reason=reason,
                ))

        # 修改
        for path in before_set & after_set:
            if before[path] != after[path] and self._should_track(Path(path)):
                level, reason = self._assess_impact(path, ChangeType.MODIFIED)
                changes.append(FileChange(
                    path=path,
                    change_type=ChangeType.MODIFIED,
                    impact_level=level,
                    reason=reason,
                ))

        needs_sync = any(c.impact_level in ("major", "critical") for c in changes)

        summary_parts = []
        if changes:
            added = sum(1 for c in changes if c.change_type == ChangeType.ADDED)
            modified = sum(1 for c in changes if c.change_type == ChangeType.MODIFIED)
            deleted = sum(1 for c in changes if c.change_type == ChangeType.DELETED)
            summary_parts.append(
                f"+{added} ~{modified} -{deleted}"
            )
            critical = sum(1 for c in changes if c.impact_level == "critical")
            if critical:
                summary_parts.append(f"⚠ {critical} critical")

        return ChangeReport(
            changes=changes,
            needs_sync=needs_sync,
            impact_summary=" | ".join(summary_parts) if summary_parts else "无变更",
        )

    # ── 同步执行 ─────────────────────────────────────────

    def sync(self, changes: ChangeReport) -> SyncReport:
        """执行文档同步

        Args:
            changes: 变更报告

        Returns:
            SyncReport
        """
        if not changes.needs_sync:
            return SyncReport(
                action=SyncAction.SKIP,
                reason="无 major/critical 变更, 跳过同步",
            )

        report = SyncReport(action=SyncAction.SYNC)

        # 调用 dream-doc-sync-workflow
        if self._sync_fn:
            try:
                sync_result = self._sync_fn(
                    changes=changes.to_dict(),
                    project_root=str(self._root),
                )
                if isinstance(sync_result, dict):
                    report.index_updated = sync_result.get("index_updated", False)
                    report.knowledge_updated = sync_result.get("knowledge_updated", False)
                    report.lint_passed = sync_result.get("lint_passed", False)
                report.reason = "dream-doc-sync-workflow 执行完成"
            except Exception as e:  # noqa: BLE001 FAIL-OPEN
                report.action = SyncAction.FAILED
                report.reason = f"同步失败: {e}"
                logger.warning(f"[doc_sync] 同步失败: {e}")
        else:
            # 无 sync_fn → 仅标记需要同步
            report.reason = "检测到变更需同步, 但无 sync_fn 配置"

        # 记录到认知库
        if self._record_fn:
            try:
                major = changes.major_changes
                mem_id = self._record_fn(
                    content=(
                        f"[文档自同步] {changes.impact_summary}, "
                        f"major_changes={len(major)}, "
                        f"action={report.action.value}, "
                        f"reason={report.reason}"
                    ),
                    quality_level="B",
                    tags="doc-sync,文档索引,知识库同步,认知闭环,L4自迭代",
                )
                if mem_id:
                    report.recorded = True
                    report.memory_id = str(mem_id)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[doc_sync] 认知库记录失败: {e}")

        return report

    # ── 便捷方法 ─────────────────────────────────────────

    def scan_checksums(self) -> Dict[str, str]:
        """扫描项目目录, 返回 {path: checksum}"""
        checksums: Dict[str, str] = {}
        for path in self._root.rglob("*"):
            if not path.is_file():
                continue
            rel = str(path.relative_to(self._root))
            if not self._should_track(path):
                continue
            checksums[rel] = self._file_checksum(path)
        return checksums
