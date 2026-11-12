"""增量索引（SPEC-33-F T-F17）。

文件级 Merkle：`sha256(路径 + 内容)` 逐文件寻址，跨版本 diff 产出
`added / modified / removed` 三类失效文件。设计边界：
  - 纯本地确定性计算，不联网、不调用模型。
  - 索引文件损坏或版本不符时 FAIL-OPEN：当作首次构建，不抛异常。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

INDEX_VERSION = 1
_SKIP_DIRS = {
    ".git",
    "node_modules",
    ".next",
    ".turbo",
    "dist",
    "build",
    "out",
    "coverage",
    "__pycache__",
    ".venv",
    "venv",
    ".rea",
}
_MAX_FILES = 5000


def _iter_files(root: Path, suffixes: tuple[str, ...]) -> Iterable[Path]:
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            if name.endswith(suffixes):
                count += 1
                if count > _MAX_FILES:
                    return
                yield Path(dirpath) / name


def _digest(path: Path, relative: str) -> str:
    digest = hashlib.sha256()
    digest.update(relative.encode("utf-8"))
    try:
        digest.update(path.read_bytes())
    except OSError:
        digest.update(b"<unreadable>")
    return digest.hexdigest()


def build_merkle(
    root: Path | str, suffixes: tuple[str, ...] = (".py", ".ts", ".tsx", ".js", ".jsx")
) -> dict[str, Any]:
    """构建文件级 Merkle 索引（`root_hash` 由排序后的路径+摘要决定）。"""
    base = Path(root).expanduser()
    files: dict[str, str] = {}
    if base.is_dir():
        for path in _iter_files(base, suffixes):
            try:
                relative = path.resolve().relative_to(base.resolve()).as_posix()
            except (ValueError, OSError):
                relative = path.as_posix()
            files[relative] = _digest(path, relative)
    ordered = sorted(files.items())
    root_hash = hashlib.sha256(
        json.dumps(ordered, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "version": INDEX_VERSION,
        "root": str(base.resolve()) if base.is_dir() else str(base),
        "root_hash": root_hash,
        "files": dict(ordered),
        "count": len(ordered),
    }


def diff_merkle(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    """对比两版索引，返回文件级失效清单。"""
    prev_files = (previous or {}).get("files") or {}
    curr_files = current.get("files") or {}
    prev_keys = set(prev_files)
    curr_keys = set(curr_files)
    added = sorted(curr_keys - prev_keys)
    removed = sorted(prev_keys - curr_keys)
    modified = sorted(k for k in curr_keys & prev_keys if prev_files[k] != curr_files[k])
    unchanged = len(curr_keys & prev_keys) - len(modified)
    return {
        "added": added,
        "modified": modified,
        "removed": removed,
        "unchanged": unchanged,
        "invalidated_files": sorted(added + modified + removed),
        "previous_root_hash": (previous or {}).get("root_hash") or "",
        "root_hash": current.get("root_hash") or "",
        "first_build": previous is None,
    }


def load_index(path: Path | str) -> tuple[dict[str, Any] | None, list[str]]:
    """读取索引；缺失/损坏/版本不符返回 (None, known_gaps)。"""
    target = Path(path)
    if not target.is_file():
        return None, [f"索引不存在，按首次构建处理: {target}"]
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, [f"索引不可读或损坏，按首次构建处理: {type(exc).__name__}: {exc}"]
    if not isinstance(payload, dict) or payload.get("version") != INDEX_VERSION:
        return None, ["索引版本不符，按首次构建处理"]
    if not isinstance(payload.get("files"), dict):
        return None, ["索引缺少 files 字段，按首次构建处理"]
    return payload, []


def save_index(path: Path | str, index: dict[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)
    return target
