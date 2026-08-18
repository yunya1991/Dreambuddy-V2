#!/usr/bin/env python3
"""
记忆版本控制 (MemoryVersionControl) — MemOS 风格的记忆版本管理

借鉴 MemOS 的 Git 版本控制理念，为记忆系统提供：
1. commit：创建版本快照（Tier0/Tier1 文件）
2. log：查看版本历史
3. diff：对比版本间差异
4. rollback：回滚到指定版本
5. restore：恢复单个文件到指定版本
6. list_files：查看版本包含的文件

设计原则：
- 轻量级：使用 JSON 存储版本元数据 + 文件快照
- 非侵入式：不修改原文件，所有版本独立存储
- 可追溯：每个 commit 记录变更原因、作者、时间
- 增量存储：内容相同的文件只存一次（按哈希去重）

存储结构：
    4-MEMORY/versions/
    ├── commits.json          # 版本链索引（commit_id → 元数据）
    └── snapshots/            # 文件快照存储
        └── <commit_id>/
            └── <filename>    # 该版本的文件内容

用法（Python 集成）:
    from memory_version_control import MemoryVersionControl

    vc = MemoryVersionControl()

    # 创建版本
    commit_id = vc.commit("归档 TL-006/TL-007 案例段落", author="trae")

    # 查看历史
    for entry in vc.log():
        print(f"{entry['commit_id'][:8]} {entry['timestamp']} {entry['message']}")

    # 查看差异
    diff = vc.diff(commit_id_1, commit_id_2)
    for file_diff in diff:
        print(f"{file_diff['file']}: +{file_diff['added']} -{file_diff['removed']}")

    # 回滚
    vc.rollback(commit_id)

用法（CLI 集成）:
    python3 memory_version_control.py commit -m "归档 TL-006 案例段落"
    python3 memory_version_control.py log
    python3 memory_version_control.py diff <commit_id_1> <commit_id_2>
    python3 memory_version_control.py rollback <commit_id>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_SCRIPT_DIR = Path(__file__).parent
_MEMORY_ROOT = _SCRIPT_DIR.parent

# 受版本控制的 Tier0/Tier1 文件（相对 memory_root 的路径）
TRACKED_FILES: List[str] = [
    "CORE.md",
    "1-原则记忆/ENGINEERING_PRINCIPLES.md",
    "2-方法论记忆/A1_RESEARCH_METHOD.md",
    "2-方法论记忆/A8_THEORY_PRACTICE.md",
    "2-方法论记忆/CONTRADICTION_METHOD.md",
    "5-通用经验/TECH_LESSONS.md",
    "5-通用经验/PROCESS_LESSONS.md",
    "5-通用经验/BEST_PRACTICES.md",
    "5-通用经验/ANTI_PATTERNS.md",
]


def _now_iso() -> str:
    """当前 UTC 时间 ISO 格式"""
    return datetime.now(timezone.utc).isoformat()


def _short_id(commit_id: str, length: int = 8) -> str:
    """commit_id 简短显示"""
    return commit_id[:length]


def _file_hash(content: str) -> str:
    """计算文件内容哈希（用于去重和变更检测）"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


@dataclass
class CommitEntry:
    """版本提交记录"""
    commit_id: str = ""
    parent_id: str = ""                    # 父 commit_id（空表示初始提交）
    timestamp: str = ""
    author: str = "system"
    message: str = ""
    files: Dict[str, str] = field(default_factory=dict)  # {文件路径: 哈希}

    def to_dict(self) -> dict:
        return {
            "commit_id": self.commit_id,
            "parent_id": self.parent_id,
            "timestamp": self.timestamp,
            "author": self.author,
            "message": self.message,
            "files": self.files,
        }


class MemoryVersionControl:
    """
    记忆版本控制系统 — MemOS 风格的版本管理

    提供 commit / log / diff / rollback / restore 能力。
    """

    def __init__(self, memory_root: Optional[Path] = None):
        """
        初始化版本控制系统。

        Args:
            memory_root: 记忆系统根目录。默认 4-MEMORY/
        """
        self.memory_root = Path(memory_root) if memory_root else _MEMORY_ROOT
        self.versions_dir = self.memory_root / "versions"
        self.snapshots_dir = self.versions_dir / "snapshots"
        self.commits_file = self.versions_dir / "commits.json"

        # 确保目录存在
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

        # 加载版本链
        self._commits: Dict[str, CommitEntry] = self._load_commits()

    # ============================================================
    # 持久化
    # ============================================================

    def _load_commits(self) -> Dict[str, CommitEntry]:
        """加载版本链索引"""
        if not self.commits_file.exists():
            return {}
        try:
            data = json.loads(self.commits_file.read_text(encoding="utf-8"))
            commits = {}
            for commit_id, entry_data in data.items():
                commits[commit_id] = CommitEntry(
                    commit_id=entry_data["commit_id"],
                    parent_id=entry_data.get("parent_id", ""),
                    timestamp=entry_data["timestamp"],
                    author=entry_data.get("author", "system"),
                    message=entry_data.get("message", ""),
                    files=entry_data.get("files", {}),
                )
            return commits
        except Exception as e:
            logger.warning(f"加载版本链失败: {e}")
            return {}

    def _save_commits(self) -> None:
        """保存版本链索引"""
        data = {cid: entry.to_dict() for cid, entry in self._commits.items()}
        self.commits_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _get_snapshot_dir(self, commit_id: str) -> Path:
        """获取某个 commit 的快照目录"""
        return self.snapshots_dir / commit_id

    # ============================================================
    # 文件读取
    # ============================================================

    def _read_tracked_file(self, rel_path: str) -> Optional[str]:
        """读取受跟踪的文件内容"""
        fpath = self.memory_root / rel_path
        if not fpath.exists():
            return None
        try:
            return fpath.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"读取文件失败 {rel_path}: {e}")
            return None

    def _get_all_tracked_files(self) -> List[str]:
        """获取所有实际存在的受跟踪文件"""
        return [f for f in TRACKED_FILES if (self.memory_root / f).exists()]

    # ============================================================
    # commit：创建版本快照
    # ============================================================

    def commit(
        self,
        message: str,
        author: str = "system",
        allow_empty: bool = False,
    ) -> str:
        """
        创建版本快照。

        Args:
            message: 提交信息（必填，描述本次变更）
            author: 提交者
            allow_empty: 是否允许空提交（无变更时也创建）

        Returns:
            commit_id（空字符串表示未创建）

        Raises:
            ValueError: message 为空
        """
        if not message.strip():
            raise ValueError("提交信息不能为空")

        tracked_files = self._get_all_tracked_files()
        if not tracked_files:
            logger.warning("没有可跟踪的文件")
            return ""

        # 计算当前文件哈希
        current_files: Dict[str, str] = {}
        for rel_path in tracked_files:
            content = self._read_tracked_file(rel_path)
            if content is not None:
                current_files[rel_path] = _file_hash(content)

        # 检查是否有变更（与最新 commit 比较）
        latest = self._get_latest_commit()
        if latest and not allow_empty:
            if latest.files == current_files:
                logger.info("无变更，跳过提交（使用 allow_empty=True 强制提交）")
                return ""

        # 生成 commit_id（时间戳 + 随机后缀）
        commit_id = self._generate_commit_id()

        # 保存文件快照
        snapshot_dir = self._get_snapshot_dir(commit_id)
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        for rel_path in tracked_files:
            content = self._read_tracked_file(rel_path)
            if content is not None:
                # 快照文件用扁平化命名（/ 替换为 _）
                snapshot_name = rel_path.replace("/", "__")
                (snapshot_dir / snapshot_name).write_text(content, encoding="utf-8")

        # 创建 commit 记录
        entry = CommitEntry(
            commit_id=commit_id,
            parent_id=latest.commit_id if latest else "",
            timestamp=_now_iso(),
            author=author,
            message=message,
            files=current_files,
        )
        self._commits[commit_id] = entry
        self._save_commits()

        logger.info(f"提交成功: {_short_id(commit_id)} {message}")
        return commit_id

    def _generate_commit_id(self) -> str:
        """生成唯一的 commit_id"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        random_suffix = hashlib.sha256(
            f"{timestamp}_{time.time_ns()}".encode()
        ).hexdigest()[:8]
        return f"{timestamp}_{random_suffix}"

    def _get_latest_commit(self) -> Optional[CommitEntry]:
        """获取最新的 commit（按时间戳排序）"""
        if not self._commits:
            return None
        return max(self._commits.values(), key=lambda c: c.timestamp)

    # ============================================================
    # log：查看版本历史
    # ============================================================

    def log(self, limit: int = 20, reverse: bool = False) -> List[Dict[str, Any]]:
        """
        查看版本历史。

        Args:
            limit: 返回数量
            reverse: True=最旧在前，False=最新在前

        Returns:
            版本记录列表
        """
        commits = sorted(
            self._commits.values(),
            key=lambda c: c.timestamp,
            reverse=not reverse,
        )
        result = []
        for entry in commits[:limit]:
            # 计算变更统计
            file_count = len(entry.files)
            parent_files = self._commits[entry.parent_id].files if entry.parent_id and entry.parent_id in self._commits else {}
            added = len([f for f in entry.files if f not in parent_files])
            modified = len([f for f in entry.files if f in parent_files and entry.files[f] != parent_files.get(f)])
            removed = len([f for f in parent_files if f not in entry.files])

            result.append({
                "commit_id": entry.commit_id,
                "short_id": _short_id(entry.commit_id),
                "parent_id": entry.parent_id,
                "timestamp": entry.timestamp,
                "author": entry.author,
                "message": entry.message,
                "file_count": file_count,
                "changes": {"added": added, "modified": modified, "removed": removed},
            })
        return result

    # ============================================================
    # diff：版本间差异
    # ============================================================

    def diff(
        self,
        commit_id_a: str,
        commit_id_b: str,
        file_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        对比两个版本间的差异。

        Args:
            commit_id_a: 旧版本 commit_id
            commit_id_b: 新版本 commit_id
            file_filter: 只查看指定文件（None=全部）

        Returns:
            文件差异列表
        """
        if commit_id_a not in self._commits:
            raise ValueError(f"commit 不存在: {commit_id_a}")
        if commit_id_b not in self._commits:
            raise ValueError(f"commit 不存在: {commit_id_b}")

        entry_a = self._commits[commit_id_a]
        entry_b = self._commits[commit_id_b]

        all_files = sorted(set(entry_a.files.keys()) | set(entry_b.files.keys()))
        result = []

        for rel_path in all_files:
            if file_filter and file_filter not in rel_path:
                continue

            hash_a = entry_a.files.get(rel_path)
            hash_b = entry_b.files.get(rel_path)

            if hash_a == hash_b:
                continue  # 无变更

            status = "modified"
            if hash_a is None:
                status = "added"
            elif hash_b is None:
                status = "removed"

            # 读取两个版本的内容
            content_a = self._read_snapshot(commit_id_a, rel_path) or ""
            content_b = self._read_snapshot(commit_id_b, rel_path) or ""

            # 计算行级 diff
            lines_a = content_a.splitlines(keepends=True)
            lines_b = content_b.splitlines(keepends=True)

            import difflib
            diff_lines = list(difflib.unified_diff(
                lines_a, lines_b,
                fromfile=f"{rel_path}@{_short_id(commit_id_a)}",
                tofile=f"{rel_path}@{_short_id(commit_id_b)}",
                lineterm="",
            ))

            added = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
            removed = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))

            result.append({
                "file": rel_path,
                "status": status,
                "added_lines": added,
                "removed_lines": removed,
                "diff": "".join(diff_lines) if diff_lines else "",
            })

        return result

    def _read_snapshot(self, commit_id: str, rel_path: str) -> Optional[str]:
        """读取某个 commit 的文件快照内容"""
        snapshot_dir = self._get_snapshot_dir(commit_id)
        snapshot_name = rel_path.replace("/", "__")
        fpath = snapshot_dir / snapshot_name
        if not fpath.exists():
            return None
        return fpath.read_text(encoding="utf-8")

    # ============================================================
    # rollback：回滚到指定版本
    # ============================================================

    def rollback(
        self,
        commit_id: str,
        create_backup: bool = True,
        backup_message: str = "",
    ) -> Dict[str, Any]:
        """
        回滚到指定版本（恢复该版本的所有文件到工作区）。

        Args:
            commit_id: 目标 commit_id
            create_backup: 是否在回滚前创建备份 commit
            backup_message: 备份 commit 的消息

        Returns:
            回滚结果
        """
        if commit_id not in self._commits:
            raise ValueError(f"commit 不存在: {commit_id}")

        target = self._commits[commit_id]

        # 创建备份
        backup_id = ""
        if create_backup:
            backup_msg = backup_message or f"回滚前备份 → {_short_id(commit_id)}"
            backup_id = self.commit(backup_msg, author="rollback", allow_empty=True)

        # 恢复文件
        restored_files = []
        skipped_files = []

        for rel_path in target.files.keys():
            content = self._read_snapshot(commit_id, rel_path)
            if content is None:
                skipped_files.append(rel_path)
                continue

            fpath = self.memory_root / rel_path
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(content, encoding="utf-8")
            restored_files.append(rel_path)

        return {
            "rolled_back_to": commit_id,
            "rolled_back_to_short": _short_id(commit_id),
            "backup_commit_id": backup_id,
            "restored_files": restored_files,
            "skipped_files": skipped_files,
            "target_message": target.message,
            "target_timestamp": target.timestamp,
        }

    # ============================================================
    # restore：恢复单个文件到指定版本
    # ============================================================

    def restore(
        self,
        commit_id: str,
        file_path: str,
    ) -> Dict[str, Any]:
        """
        恢复单个文件到指定版本。

        Args:
            commit_id: 目标 commit_id
            file_path: 文件路径（相对 memory_root）

        Returns:
            恢复结果
        """
        if commit_id not in self._commits:
            raise ValueError(f"commit 不存在: {commit_id}")

        target = self._commits[commit_id]
        if file_path not in target.files:
            raise ValueError(f"文件 {file_path} 不在 commit {commit_id} 中")

        content = self._read_snapshot(commit_id, file_path)
        if content is None:
            raise ValueError(f"无法读取快照: {commit_id}/{file_path}")

        fpath = self.memory_root / file_path
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(content, encoding="utf-8")

        return {
            "restored_file": file_path,
            "restored_from": commit_id,
            "restored_from_short": _short_id(commit_id),
            "target_timestamp": target.timestamp,
        }

    # ============================================================
    # list_files：查看版本包含的文件
    # ============================================================

    def list_files(self, commit_id: str) -> List[Dict[str, Any]]:
        """
        查看某个版本包含的所有文件。

        Args:
            commit_id: 目标 commit_id

        Returns:
            文件列表
        """
        if commit_id not in self._commits:
            raise ValueError(f"commit 不存在: {commit_id}")

        entry = self._commits[commit_id]
        result = []
        for rel_path, file_hash in entry.files.items():
            content = self._read_snapshot(commit_id, rel_path) or ""
            result.append({
                "file": rel_path,
                "hash": file_hash,
                "chars": len(content),
                "lines": content.count("\n") + 1 if content else 0,
            })
        return result

    # ============================================================
    # show：查看某个 commit 的详情
    # ============================================================

    def show(self, commit_id: str) -> Dict[str, Any]:
        """查看某个 commit 的详情"""
        if commit_id not in self._commits:
            raise ValueError(f"commit 不存在: {commit_id}")

        entry = self._commits[commit_id]
        parent_files = {}
        if entry.parent_id and entry.parent_id in self._commits:
            parent_files = self._commits[entry.parent_id].files

        added = len([f for f in entry.files if f not in parent_files])
        modified = len([f for f in entry.files if f in parent_files and entry.files[f] != parent_files.get(f)])
        removed = len([f for f in parent_files if f not in entry.files])

        return {
            "commit_id": entry.commit_id,
            "short_id": _short_id(entry.commit_id),
            "parent_id": entry.parent_id,
            "parent_short": _short_id(entry.parent_id) if entry.parent_id else "",
            "timestamp": entry.timestamp,
            "author": entry.author,
            "message": entry.message,
            "file_count": len(entry.files),
            "changes": {"added": added, "modified": modified, "removed": removed},
            "files": list(entry.files.keys()),
        }

    # ============================================================
    # status：查看当前工作区与最新 commit 的差异
    # ============================================================

    def status(self) -> Dict[str, Any]:
        """查看当前工作区与最新 commit 的差异"""
        latest = self._get_latest_commit()
        if not latest:
            return {
                "has_commits": False,
                "message": "还没有任何 commit，使用 commit 命令创建第一个版本",
            }

        tracked_files = self._get_all_tracked_files()
        current_files = {}
        for rel_path in tracked_files:
            content = self._read_tracked_file(rel_path)
            if content is not None:
                current_files[rel_path] = _file_hash(content)

        modified = []
        added = []
        removed = []

        for rel_path in current_files:
            if rel_path not in latest.files:
                added.append(rel_path)
            elif current_files[rel_path] != latest.files[rel_path]:
                modified.append(rel_path)

        for rel_path in latest.files:
            if rel_path not in current_files:
                removed.append(rel_path)

        return {
            "has_commits": True,
            "latest_commit": _short_id(latest.commit_id),
            "latest_message": latest.message,
            "latest_timestamp": latest.timestamp,
            "modified": modified,
            "added": added,
            "removed": removed,
            "is_clean": not (modified or added or removed),
        }


# ============================================================
# CLI
# ============================================================

def _cli_commit(vc: MemoryVersionControl, args) -> int:
    """创建版本"""
    commit_id = vc.commit(args.message, author=args.author, allow_empty=args.allow_empty)
    if not commit_id:
        print("无变更，未创建 commit")
        return 1
    print(f"✅ 提交成功")
    print(f"   commit: {_short_id(commit_id)}")
    print(f"   消息: {args.message}")
    print(f"   作者: {args.author}")
    return 0


def _cli_log(vc: MemoryVersionControl, args) -> int:
    """查看历史"""
    entries = vc.log(limit=args.limit, reverse=args.reverse)
    if not entries:
        print("还没有任何 commit")
        return 1

    print(f"📚 版本历史（共 {len(entries)} 条）\n")
    for entry in entries:
        changes = entry["changes"]
        change_summary = []
        if changes["added"]:
            change_summary.append(f"+{changes['added']}")
        if changes["modified"]:
            change_summary.append(f"~{changes['modified']}")
        if changes["removed"]:
            change_summary.append(f"-{changes['removed']}")
        change_str = " ".join(change_summary) if change_summary else "无变更"

        print(f"  {entry['short_id']}  {entry['timestamp'][:19]}  [{entry['author']}]")
        print(f"           {entry['message']}")
        print(f"           文件: {entry['file_count']} | 变更: {change_str}")
        print()
    return 0


def _cli_diff(vc: MemoryVersionControl, args) -> int:
    """查看差异"""
    try:
        diffs = vc.diff(args.commit_a, args.commit_b, file_filter=args.file)
    except ValueError as e:
        print(f"❌ {e}")
        return 1

    if not diffs:
        print("无差异")
        return 0

    print(f"📊 差异: {_short_id(args.commit_a)} → {_short_id(args.commit_b)}\n")
    for d in diffs:
        status_icon = {"added": "➕", "modified": "📝", "removed": "➖"}.get(d["status"], "?")
        print(f"{status_icon} {d['file']} ({d['status']})")
        print(f"   +{d['added_lines']} -{d['removed_lines']}")
        if args.verbose and d["diff"]:
            print(f"   ---")
            for line in d["diff"].split("\n")[:30]:
                print(f"   {line}")
            if len(d["diff"].split("\n")) > 30:
                print(f"   ... (更多 {len(d['diff'].split(chr(10))) - 30} 行)")
        print()
    return 0


def _cli_rollback(vc: MemoryVersionControl, args) -> int:
    """回滚"""
    if not args.force:
        print("❌ 回滚需要 --force 参数确认")
        print("   这将覆盖当前工作区文件，请先确认")
        return 1

    try:
        result = vc.rollback(args.commit_id, create_backup=not args.no_backup)
    except ValueError as e:
        print(f"❌ {e}")
        return 1

    print(f"✅ 回滚成功")
    print(f"   目标: {_short_id(result['rolled_back_to'])} ({result['target_timestamp'][:19]})")
    print(f"   消息: {result['target_message']}")
    if result["backup_commit_id"]:
        print(f"   备份: {_short_id(result['backup_commit_id'])}")
    print(f"   恢复文件: {len(result['restored_files'])} 个")
    for f in result["restored_files"]:
        print(f"     - {f}")
    if result["skipped_files"]:
        print(f"   跳过文件: {len(result['skipped_files'])} 个")
    return 0


def _cli_restore(vc: MemoryVersionControl, args) -> int:
    """恢复单个文件"""
    if not args.force:
        print("❌ 恢复需要 --force 参数确认")
        return 1
    try:
        result = vc.restore(args.commit_id, args.file_path)
    except ValueError as e:
        print(f"❌ {e}")
        return 1
    print(f"✅ 恢复成功")
    print(f"   文件: {result['restored_file']}")
    print(f"   来源: {_short_id(result['restored_from'])} ({result['target_timestamp'][:19]})")
    return 0


def _cli_show(vc: MemoryVersionControl, args) -> int:
    """查看 commit 详情"""
    try:
        info = vc.show(args.commit_id)
    except ValueError as e:
        print(f"❌ {e}")
        return 1
    print(f"📋 Commit 详情")
    print(f"   ID: {info['commit_id']}")
    print(f"   父: {info['parent_short'] or '(无)'}")
    print(f"   时间: {info['timestamp'][:19]}")
    print(f"   作者: {info['author']}")
    print(f"   消息: {info['message']}")
    print(f"   文件: {info['file_count']} 个")
    changes = info["changes"]
    if changes["added"] or changes["modified"] or changes["removed"]:
        print(f"   变更: +{changes['added']} ~{changes['modified']} -{changes['removed']}")
    print(f"   文件列表:")
    for f in info["files"]:
        print(f"     - {f}")
    return 0


def _cli_status(vc: MemoryVersionControl, args) -> int:
    """查看工作区状态"""
    status = vc.status()
    if not status["has_commits"]:
        print(status["message"])
        return 1

    print(f"📊 工作区状态")
    print(f"   最新 commit: {status['latest_commit']}")
    print(f"   消息: {status['latest_message']}")
    print(f"   时间: {status['latest_timestamp'][:19]}")

    if status["is_clean"]:
        print(f"   状态: ✅ 干净（无未提交变更）")
    else:
        print(f"   状态: ⚠️ 有未提交变更")
        if status["modified"]:
            print(f"   修改: {len(status['modified'])} 个")
            for f in status["modified"]:
                print(f"     ~ {f}")
        if status["added"]:
            print(f"   新增: {len(status['added'])} 个")
            for f in status["added"]:
                print(f"     + {f}")
        if status["removed"]:
            print(f"   删除: {len(status['removed'])} 个")
            for f in status["removed"]:
                print(f"     - {f}")
    return 0


def _cli_list_files(vc: MemoryVersionControl, args) -> int:
    """查看版本文件列表"""
    try:
        files = vc.list_files(args.commit_id)
    except ValueError as e:
        print(f"❌ {e}")
        return 1
    print(f"📁 版本 {_short_id(args.commit_id)} 包含 {len(files)} 个文件\n")
    for f in files:
        print(f"  {f['file']}")
        print(f"     哈希: {f['hash']} | 字符: {f['chars']} | 行数: {f['lines']}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="记忆版本控制（MemOS 风格）")
    sub = parser.add_subparsers(dest="command")

    # commit
    p_commit = sub.add_parser("commit", help="创建版本快照")
    p_commit.add_argument("-m", "--message", required=True, help="提交信息")
    p_commit.add_argument("--author", default="trae", help="提交者")
    p_commit.add_argument("--allow-empty", action="store_true", help="允许空提交")

    # log
    p_log = sub.add_parser("log", help="查看版本历史")
    p_log.add_argument("--limit", type=int, default=20, help="返回数量")
    p_log.add_argument("--reverse", action="store_true", help="最旧在前")

    # diff
    p_diff = sub.add_parser("diff", help="对比版本间差异")
    p_diff.add_argument("commit_a", help="旧版本 commit_id")
    p_diff.add_argument("commit_b", help="新版本 commit_id")
    p_diff.add_argument("--file", help="只查看指定文件")
    p_diff.add_argument("--verbose", "-v", action="store_true", help="显示详细 diff")

    # rollback
    p_rollback = sub.add_parser("rollback", help="回滚到指定版本")
    p_rollback.add_argument("commit_id", help="目标 commit_id")
    p_rollback.add_argument("--force", action="store_true", help="确认回滚")
    p_rollback.add_argument("--no-backup", action="store_true", help="不创建备份")

    # restore
    p_restore = sub.add_parser("restore", help="恢复单个文件")
    p_restore.add_argument("commit_id", help="目标 commit_id")
    p_restore.add_argument("file_path", help="文件路径")
    p_restore.add_argument("--force", action="store_true", help="确认恢复")

    # show
    p_show = sub.add_parser("show", help="查看 commit 详情")
    p_show.add_argument("commit_id", help="commit_id")

    # status
    sub.add_parser("status", help="查看工作区状态")

    # list-files
    p_ls = sub.add_parser("list-files", help="查看版本文件列表")
    p_ls.add_argument("commit_id", help="commit_id")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        raise SystemExit(1)

    vc = MemoryVersionControl()

    handlers = {
        "commit": _cli_commit,
        "log": _cli_log,
        "diff": _cli_diff,
        "rollback": _cli_rollback,
        "restore": _cli_restore,
        "show": _cli_show,
        "status": _cli_status,
        "list-files": _cli_list_files,
    }
    raise SystemExit(handlers[args.command](vc, args))
