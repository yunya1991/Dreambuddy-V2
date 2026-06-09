import json
import sys
from pathlib import Path


RULES_PATH = (
    Path(__file__).resolve().parents[1]
    / "SKILLS"
    / "agent-collab-supervisor"
    / "rules.json"
)


def load_rules():
    if not RULES_PATH.exists():
        raise FileNotFoundError(f"rules file not found: {RULES_PATH}")
    with RULES_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)["rules"]


def branch_policy_valid(branch):
    return branch.startswith("agent/") or branch.startswith("milestone/")


def payload_flag(payload, new_key, legacy_key):
    if new_key in payload:
        return bool(payload.get(new_key))
    return bool(payload.get(legacy_key))


def check_task_card_present(payload):
    return bool(payload.get("task_card_present"))


def check_design_review_present(payload):
    return bool(payload.get("design_review_present"))


def check_started_comment_present(payload):
    return "STARTED" in payload.get("comments", [])


def check_scope_change_announcement(payload):
    return (not payload_flag(payload, "scope_change_declared", "scope_changed")) or (
        "UPDATED" in payload.get("comments", [])
    )


def check_block_announcement(payload):
    return (not payload_flag(payload, "block_declared", "execution_blocked")) or (
        "BLOCKED" in payload.get("comments", [])
    )


def check_test_report_present(payload):
    return bool(payload.get("test_report_present"))


def check_non_owner_review_present(payload):
    return bool(payload.get("non_owner_review_present"))


def check_done_comment_present(payload):
    return "DONE" in payload.get("comments", [])


def check_branch_policy_valid(payload):
    return branch_policy_valid(payload.get("branch", ""))


def check_shared_files_declared(payload):
    return bool(payload.get("shared_files_declared"))


CHECKERS = {
    "check_task_card_present": check_task_card_present,
    "check_design_review_present": check_design_review_present,
    "check_started_comment_present": check_started_comment_present,
    "check_scope_change_announcement": check_scope_change_announcement,
    "check_block_announcement": check_block_announcement,
    "check_test_report_present": check_test_report_present,
    "check_non_owner_review_present": check_non_owner_review_present,
    "check_done_comment_present": check_done_comment_present,
    "check_branch_policy_valid": check_branch_policy_valid,
    "check_shared_files_declared": check_shared_files_declared,
}


def build_rule_checkers(rules):
    rule_checkers = {}
    for rule in rules:
        checker_name = rule["checker"]
        if checker_name not in CHECKERS:
            raise KeyError(f"unknown checker '{checker_name}' for rule {rule['id']}")
        rule_checkers[rule["id"]] = CHECKERS[checker_name]
    return rule_checkers


def evaluate_payload(payload):
    rules = load_rules()
    rule_checkers = build_rule_checkers(rules)
    reason_codes = []
    for rule in rules:
        if not rule_checkers[rule["id"]](payload):
            reason_codes.append(rule["id"])

    return {
        "decision": "PASS" if not reason_codes else "BLOCK",
        "reason_codes": reason_codes,
        "evaluated_rule_count": len(rules),
    }


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: check_agent_lifecycle.py <payload.json>")

    payload_path = Path(sys.argv[1])
    with payload_path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)

    result = evaluate_payload(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["decision"] == "PASS" else 1)


if __name__ == "__main__":
    main()
