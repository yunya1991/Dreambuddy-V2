import json
import re
import sys
from pathlib import Path


HEADER_TO_STATUS = {
    "[协作开工声明 / STARTED]": "STARTED",
    "[协作状态更新 / UPDATED]": "UPDATED",
    "[协作阻塞通知 / BLOCKED]": "BLOCKED",
    "[协作完成回报 / DONE]": "DONE",
    "[方案评审记录 / DESIGN_REVIEW]": "DESIGN_REVIEW",
    "[测试报告 / TEST_REPORT]": "TEST_REPORT",
}


def extract_field(text, label):
    pattern = re.compile(rf"^{re.escape(label)}:\s*(.+)$", re.MULTILINE)
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def extract_bullets_after_label(text, label):
    lines = text.splitlines()
    bullets = []
    collecting = False
    prefix = f"{label}:"
    for line in lines:
        stripped = line.strip()
        if stripped == prefix:
            collecting = True
            continue
        if collecting:
            if not stripped:
                if bullets:
                    break
                continue
            if stripped.startswith("- "):
                bullets.append(stripped[2:].strip())
                continue
            if ":" in stripped and not stripped.startswith("- "):
                break
    return bullets


def first_non_empty(*values):
    for value in values:
        if value:
            return value
    return ""


def detect_execution_mode(text):
    explicit = first_non_empty(
        extract_field(text, "Execution Mode"),
        extract_field(text, "执行模式"),
    )
    if explicit:
        return explicit.strip().upper()
    if "阶段广播" in text or "phase broadcast" in text.casefold():
        return "PHASE_BROADCAST"
    return ""


def detect_direct_takeover(text):
    lowered = text.casefold()
    takeover_keywords = (
        "direct takeover",
        "接力修复",
        "直接接管",
        "授权接管",
        "takeover",
    )
    return any(keyword in lowered for keyword in takeover_keywords)


def parse_structured_comment(text):
    for header, status in HEADER_TO_STATUS.items():
        if text.startswith(header):
            return {
                "status": status,
                "agent": extract_field(text, "Agent"),
                "reviewer": extract_field(text, "Reviewer"),
                "execution_mode": detect_execution_mode(text),
                "direct_takeover": detect_direct_takeover(text),
                "occupied_paths": extract_bullets_after_label(text, "占用范围")
                or extract_bullets_after_label(text, "当前占用范围"),
            }
    return None


def parse_pr_template_field(pr_body, label):
    value = extract_field(pr_body, label)
    if not value:
        return ""
    if value.startswith("<") and value.endswith(">"):
        return ""
    return value


def build_payload(raw):
    comments = []
    structured_comments = []
    for body in raw.get("comments", []):
        parsed = parse_structured_comment(body)
        if parsed:
            comments.append(parsed["status"])
            structured_comments.append(parsed)

    started_comment = next(
        (comment for comment in structured_comments if comment["status"] == "STARTED"),
        None,
    )

    owner_agent = (
        (started_comment or {}).get("agent")
        or parse_pr_template_field(raw.get("pr_body", ""), "Owner Agent")
        or "UNKNOWN"
    )
    owner_agent_key = owner_agent.strip().casefold()
    non_owner_review_present = any(
        comment["status"] == "DESIGN_REVIEW"
        and comment.get("reviewer")
        and comment["reviewer"].strip().casefold() != owner_agent_key
        for comment in structured_comments
    )
    shared_files_declared = any(comment["occupied_paths"] for comment in structured_comments)
    if not shared_files_declared:
        shared_declared = parse_pr_template_field(
            raw.get("pr_body", ""), "Shared Files Declared"
        ).lower()
        shared_files_declared = shared_declared in {"yes", "true"}

    task_card_present = bool(
        parse_pr_template_field(raw.get("pr_body", ""), "Task Card")
    )
    execution_mode = (
        (started_comment or {}).get("execution_mode")
        or first_non_empty(
            parse_pr_template_field(raw.get("pr_body", ""), "Execution Mode"),
            parse_pr_template_field(raw.get("pr_body", ""), "执行模式"),
        ).upper()
        or "STANDARD"
    )
    direct_takeover = any(
        comment.get("direct_takeover") for comment in structured_comments
    )
    scope_change_declared = "UPDATED" in comments
    block_declared = "BLOCKED" in comments

    return {
        "branch": raw.get("branch", ""),
        "owner_agent": owner_agent,
        "execution_mode": execution_mode,
        "direct_takeover": direct_takeover,
        "shared_files_declared": shared_files_declared,
        "task_card_present": task_card_present,
        "design_review_present": "DESIGN_REVIEW" in comments,
        "test_report_present": "TEST_REPORT" in comments,
        "non_owner_review_present": non_owner_review_present,
        "scope_change_declared": scope_change_declared,
        "block_declared": block_declared,
        "scope_changed": scope_change_declared,
        "execution_blocked": block_declared,
        "comments": comments,
    }


def main():
    if len(sys.argv) != 3:
        raise SystemExit(
            "usage: build_agent_lifecycle_payload.py <raw.json> <payload.json>"
        )

    raw_path = Path(sys.argv[1])
    payload_path = Path(sys.argv[2])

    with raw_path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)

    payload = build_payload(raw)

    with payload_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
