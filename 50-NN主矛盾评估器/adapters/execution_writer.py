"""50 执行权校验（execution_rights + Mandate + kill-switch，fail-closed）。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RIGHTS_PATH = REPO_ROOT / "47-MCP管理系统" / "registry" / "execution_rights.json"

LIVE_OUTCOMES = {"live:50-bypass"}


def load_rights(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path else DEFAULT_RIGHTS_PATH
    if not target.exists():
        return {"fifty_nn_domain": {"default_outcome": "paper"}}
    return json.loads(target.read_text(encoding="utf-8"))


def is_kill_switch_on(env_var: str = "50_KILL_SWITCH", on_value: str = "1") -> bool:
    return os.environ.get(env_var, "0") == on_value


def resolve_outcome(symbol: str, rights: dict[str, Any]) -> str:
    symbol_cfg = rights.get("symbols", {}).get(symbol) or {}
    if isinstance(symbol_cfg, dict) and symbol_cfg.get("outcome"):
        return symbol_cfg["outcome"]
    domain = rights.get("fifty_nn_domain", {})
    return domain.get("default_outcome") or rights.get("defaults", {}).get("outcome", "paper")


def validate_execution(
    decision: dict[str, Any],
    rights: dict[str, Any],
    mandate: str | None = None,
    kill_switch: bool | None = None,
) -> dict[str, Any]:
    if kill_switch is None:
        kill_switch = is_kill_switch_on()
    if kill_switch:
        return {
            "outcome": "disabled",
            "allowed": False,
            "reason": "kill_switch",
            "decision": decision,
        }

    outcome = resolve_outcome(decision.get("symbol", ""), rights)
    domain = rights.get("fifty_nn_domain", {})

    if outcome in LIVE_OUTCOMES:
        if domain.get("mandate_required_for_live", True) and not mandate:
            outcome = "paper"
            reason = "live_requires_mandate"
        else:
            reason = "live_authorized"
    else:
        reason = outcome

    decision["execution_rights"] = outcome
    decision["mandate_id"] = mandate
    decision["kill_switch"] = kill_switch
    return {
        "outcome": outcome,
        "allowed": outcome != "disabled",
        "reason": reason,
        "decision": decision,
    }
