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


def _symbol_cfg(symbol: str, rights: dict[str, Any]) -> dict[str, Any]:
    """标的执行权声明：50 分区优先，其次全局 symbols（单出口声明）。"""
    domain_symbols = (rights.get("fifty_nn_domain") or {}).get("symbols") or {}
    for scope in (domain_symbols, rights.get("symbols") or {}):
        cfg = scope.get(symbol)
        if isinstance(cfg, dict) and cfg.get("outcome"):
            return cfg
    return {}


def resolve_outcome(symbol: str, rights: dict[str, Any]) -> str:
    cfg = _symbol_cfg(symbol, rights)
    if cfg:
        return cfg["outcome"]
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
        expected_mandate = _symbol_cfg(decision.get("symbol", ""), rights).get("mandate_id")
        if domain.get("mandate_required_for_live", True) and not mandate:
            outcome = "paper"
            reason = "live_requires_mandate"
        elif expected_mandate and mandate != expected_mandate:
            outcome = "paper"
            reason = f"mandate_mismatch:expected={expected_mandate}"
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
