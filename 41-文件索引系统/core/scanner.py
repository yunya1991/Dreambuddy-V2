"""
scanner.py — 文件扫描器（遍历 + 过滤规则）
=========================================
SPEC-文件索引系统 v0.5 §3 P0 阶段

职责：遍历索引范围内的文件系统，按 index_rules.yaml 的
范围/排除规则过滤，产出 FileMeta 流（生成器，避免全量驻留内存）。

设计原则（对齐 SPEC §1.3）：
  1. 轻量可控：Python 原生实现，零重型依赖
  2. Evidence-First：FileMeta 携带完整来源证据（path/mtime/size）
  3. 生成器模式：大目录树流式产出，内存占用 O(1)

位置: 41-文件索引系统/core/scanner.py
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterator, Optional, Set


@dataclass(frozen=True)
class FileMeta:
    """文件元数据（L1 索引的原始输入，Evidence-First 来源证据）"""

    path: str          # 相对根目录的路径（正斜杠分隔，跨平台一致）
    name: str          # 文件名（含扩展名）
    ext: str           # 扩展名（小写，含点，如 .md；无扩展名为空串）
    mtime: float       # 修改时间戳（epoch 秒）
    size: int          # 字节数


# 默认排除目录（SPEC §6：node_modules、.git、__pycache__、.next、日志、二进制）
DEFAULT_EXCLUDE_DIRS = {
    "node_modules", ".git", "__pycache__", ".next", ".pytest_cache",
    ".venv", "venv", ".cache", ".pm2", ".hermes", ".training-checkpoints",
    ".monitor-backups", ".workbuddy", ".cognitive", ".trae", ".claude",
    ".npm", ".ssh", ".orca_term",
}

# 默认排除的文件扩展名（二进制/日志/压缩包）
DEFAULT_EXCLUDE_EXTS = {
    ".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".pdf", ".zip", ".tar", ".gz", ".tgz",
    ".log", ".sqlite", ".db", ".bak", ".lock",
}

# 排除的文件名模式（精确匹配）
DEFAULT_EXCLUDE_NAMES = {
    ".DS_Store", ".gitkeep", ".gitignore", ".env", ".env.production",
    ".bash_history", ".lesshst", ".sudo_as_admin_successful",
}


class FileScanner:
    """文件扫描器：遍历 + 过滤，产出 FileMeta 生成器。

    用法::

        scanner = FileScanner(root="/path/to/project")
        for meta in scanner.scan():
            ...  # 增量写入 L1 索引
    """

    def __init__(
        self,
        root: str,
        include_exts: Optional[Set[str]] = None,
        exclude_dirs: Optional[Set[str]] = None,
        exclude_exts: Optional[Set[str]] = None,
        exclude_names: Optional[Set[str]] = None,
        max_file_size: int = 10 * 1024 * 1024,  # 10MB，超限跳过（防误索引大文件）
    ) -> None:
        self.root = os.path.abspath(root)
        self.include_exts = include_exts  # None 表示不按扩展名白名单过滤
        self.exclude_dirs = exclude_dirs if exclude_dirs is not None else DEFAULT_EXCLUDE_DIRS
        self.exclude_exts = exclude_exts if exclude_exts is not None else DEFAULT_EXCLUDE_EXTS
        self.exclude_names = exclude_names if exclude_names is not None else DEFAULT_EXCLUDE_NAMES
        self.max_file_size = max_file_size

    # ------------------------------------------------------------------
    # 过滤规则
    # ------------------------------------------------------------------

    def _is_excluded_dir(self, name: str) -> bool:
        return name in self.exclude_dirs

    def _is_excluded_file(self, name: str, ext: str, size: int) -> bool:
        if name in self.exclude_names:
            return True
        if ext in self.exclude_exts:
            return True
        if self.include_exts is not None and ext not in self.include_exts:
            return True
        if size > self.max_file_size:
            return True
        return False

    # ------------------------------------------------------------------
    # 扫描主流程
    # ------------------------------------------------------------------

    def scan(self) -> Iterator[FileMeta]:
        """遍历 root，流式产出通过过滤规则的 FileMeta。

        - 使用 os.walk 自顶向下遍历
        - 剪枝：排除目录直接不进入（in-place 修改 dirs 列表）
        - 符号链接目录跳过（防环）
        """
        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=False):
            # 剪枝排除目录
            dirnames[:] = [d for d in dirnames if not self._is_excluded_dir(d)]

            for fname in filenames:
                fpath = os.path.join(dirpath, fname)
                try:
                    st = os.lstat(fpath)
                except OSError:
                    continue  # 文件消失/权限问题，跳过
                if not os.path.isfile(fpath):
                    continue

                ext = os.path.splitext(fname)[1].lower()
                if self._is_excluded_file(fname, ext, st.st_size):
                    continue

                rel = os.path.relpath(fpath, self.root).replace(os.sep, "/")
                yield FileMeta(
                    path=rel,
                    name=fname,
                    ext=ext,
                    mtime=st.st_mtime,
                    size=st.st_size,
                )

    def scan_count(self) -> int:
        """统计扫描结果数量（用于对账与测试）。"""
        return sum(1 for _ in self.scan())


# ----------------------------------------------------------------------
# 类型推断（P0 基础版：按路径模式推断 type 标记，SPEC §6）
# ----------------------------------------------------------------------

def infer_type(rel_path: str) -> str:
    """按 SPEC §6 索引范围规则推断文件类型标记。

    P0 阶段基于路径模式的轻量推断；P1 引入 chunker 后可结合内容修正。
    """
    p = rel_path.lower()
    parts = p.split("/")

    # report：报告产物目录
    if "reports" in parts or "artifacts" in parts or "acceptance_bundles" in parts:
        return "report"
    # case：案例库
    if "case-study" in parts or "cases" in parts:
        return "case"
    # memory：记忆条目
    if "memory" in parts or "intent-memory" in parts:
        return "memory"
    # code：源码
    if p.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".mjs")):
        return "code"
    # strategy：策略定义与配置
    if p.endswith((".yaml", ".yml", ".toml")):
        return "strategy"
    # doc：SPEC/README/docs 及其余文本（兜底归 doc）
    return "doc"
