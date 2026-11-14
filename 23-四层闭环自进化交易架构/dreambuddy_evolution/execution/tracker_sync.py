"""23 离场接管后的持仓文件同步（数据级，不 import 11 代码）。

背景：23 接管离场执行后，11 的 ``open_positions/<inst>.json`` 会残留已平仓记录
（幽灵仓），进而占满 subpool 容量。本模块只在 23 平仓成功后把该文件移到归档目录，
不改 11 代码、不改 11 运行态；持仓与冷却的权威状态由 22 账本（positions/cooldowns）承担。
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _open_positions_dir() -> Path:
    env = os.getenv("YIJING_OPEN_POSITIONS_DIR")
    if env:
        return Path(env)
    return _REPO_ROOT / "11-易经推理系统" / ".workbuddy" / "memory_l4" / "open_positions"


def archive_closed_position(inst_id: str, positions_dir: Path | None = None) -> Path | None:
    """把已平仓的持仓文件移到 _closed_by_23/，返回归档路径；不存在则返回 None。"""
    if not inst_id:
        return None
    root = Path(positions_dir) if positions_dir else _open_positions_dir()
    src = root / f"{inst_id}.json"
    if not src.exists():
        return None
    archive_dir = root / "_closed_by_23"
    archive_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dst = archive_dir / f"{inst_id}.{ts}.json"
    shutil.move(str(src), str(dst))
    logger.info("持仓文件已归档 %s -> %s", src.name, dst.relative_to(root))
    return dst
