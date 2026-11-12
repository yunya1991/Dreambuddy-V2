"""SPEC-9DOMAIN-HISTORY-CONTEXT-v1.1 C8 — 9 域生产代码禁止 import core_engine。

core_engine/least_resistance.py 已确认为死路径（0 生产引用），收敛到 engines 后
必须防止被重新引入，形成第二套口径。
"""

from __future__ import annotations

import re
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
FORBIDDEN = re.compile(r"core_engine")
SKIP_DIRS = {"tests", "__pycache__", "node_modules"}


def _production_files() -> list[Path]:
    files: list[Path] = []
    for path in BASE.rglob("*.py"):
        parts = path.relative_to(BASE).parts
        if any(p in SKIP_DIRS or p.startswith(".") for p in parts[:-1]):
            continue
        files.append(path)
    return files


def test_no_core_engine_import_in_production_code():
    hits: list[str] = []
    for path in _production_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), 1):
            if FORBIDDEN.search(line):
                hits.append(f"{path.relative_to(BASE)}:{lineno}: {line.strip()}")
    assert hits == [], "9 域生产代码不得引用 core_engine：\n" + "\n".join(hits)
