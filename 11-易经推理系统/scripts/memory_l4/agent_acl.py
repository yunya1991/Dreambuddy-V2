from typing import Any, Dict, Optional


def authorize(agent_id: str, action: str, acl_config: Optional[Dict[str, Dict[str, Any]]]) -> Dict[str, Any]:
    aid = str(agent_id or "unknown")
    act = str(action or "").strip().lower()
    if not act:
        return {"allow": False, "reason": "missing_action", "agent_id": aid, "action": act}
    if not isinstance(acl_config, dict):
        return {"allow": False, "reason": "missing_acl_config", "agent_id": aid, "action": act}
    agent_rules = acl_config.get(aid)
    if not isinstance(agent_rules, dict):
        return {"allow": False, "reason": "agent_not_configured", "agent_id": aid, "action": act}
    allow = bool(agent_rules.get(act))
    return {
        "allow": allow,
        "reason": "ok" if allow else "action_denied",
        "agent_id": aid,
        "action": act,
    }
