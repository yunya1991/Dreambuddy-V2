"""QMM 输出路径管理。"""

from pathlib import Path


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _workbuddy_dir() -> Path:
    return _workspace_root() / ".workbuddy"


def _memory_l4_dir() -> Path:
    return _workbuddy_dir() / "memory_l4"


def qmm_dir() -> Path:
    """QMM 输出目录。"""
    return _memory_l4_dir() / "qmm"
