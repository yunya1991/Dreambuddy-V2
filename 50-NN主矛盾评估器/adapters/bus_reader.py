"""42 总线只读 → 50 evidence。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUS_PATH = REPO_ROOT / "42-神经网络交易协调层" / "runtime" / "bus_state.json"


def to_evidence(signal: dict[str, Any]) -> dict[str, Any]:
    payload = signal.get("payload") if isinstance(signal.get("payload"), dict) else {}
    return {
        "evidence_id": signal.get("signal_id"),
        "source": signal.get("source"),
        "symbol": signal.get("symbol"),
        "granularity": signal.get("granularity") or "per_symbol",
        "direction": signal.get("direction"),
        "confidence": float(signal.get("confidence") or 0.0),
        "horizon": signal.get("horizon"),
        "intent": signal.get("intent"),
        "dimension_hint": payload.get("dimension_hint"),
        "risk_exposure_hint": signal.get("risk_exposure_hint", 0.0),
        "ts": signal.get("ts"),
        "expires_at": signal.get("expires_at"),
        "provenance": "42-bus",
        "payload": payload,
    }


def load_bus_state(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path else DEFAULT_BUS_PATH
    if not target.exists():
        return {"signals": [], "sources": []}
    return json.loads(target.read_text(encoding="utf-8"))


def load_evidences(path: str | Path | None = None) -> list[dict[str, Any]]:
    state = load_bus_state(path)
    return [to_evidence(sig) for sig in state.get("signals", [])]
