"""50 决策审计 JSONL 追加（每条决策可追溯）。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AUDIT_PATH = REPO_ROOT / "50-NN主矛盾评估器" / "runtime" / "audit" / "decisions.jsonl"


def log_decision(decision: dict[str, Any], audit_path: str | Path | None = None) -> Path:
    target = Path(audit_path) if audit_path else DEFAULT_AUDIT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "logged_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "decision": decision,
    }
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return target
