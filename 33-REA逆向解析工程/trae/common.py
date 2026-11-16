"""Trae 逆向采集器 — 公共路径与工具函数。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HOME = Path.home()
TRAE_HOME = HOME / ".trae-cn"
TRAE_APP = Path("/Applications/Trae CN.app/Contents/Resources/app")
TRAE_DATA = HOME / "Library/Application Support/Trae CN/ModularData/ai-agent"
MEMORY_ROOT = TRAE_HOME / "memory/projects"


def load_json(path: Path | str, default: Any = None) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def evidence(
    result: Any,
    level: str,
    provenance: dict[str, Any],
    confidence: float = 1.0,
    known_gaps: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "result": result,
        "level": level,
        "provenance": provenance,
        "confidence": confidence,
        "known_gaps": known_gaps or [],
    }


def write_json(path: Path | str, data: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def write_jsonl(path: Path | str, rows: list[dict[str, Any]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
