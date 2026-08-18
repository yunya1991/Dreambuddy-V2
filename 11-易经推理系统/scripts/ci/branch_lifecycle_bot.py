#!/usr/bin/env python3
import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


LABEL_STALE = "branch-bot/stale"
LABEL_NO_MERGE_BASE = "branch-bot/no-merge-base"
LABEL_EMPTY_DIFF = "branch-bot/empty-diff"
LABEL_MERGED_CANDIDATE = "branch-bot/merged-cleanup-candidate"
LABEL_MANUAL_REVIEW = "branch-bot/manual-review-required"
LABEL_AUTO_CLOSED = "branch-bot/auto-closed"
LABEL_AUTO_DELETED = "branch-bot/auto-deleted"


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Branch lifecycle automation bot")
    parser.add_argument("--repo", default="yunya1991/dream-multiskill-v2")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stale-days", type=int, default=7)
    parser.add_argument("--retention-days", type=int, default=14)
    parser.add_argument("--artifacts-dir", default="artifacts/branch_lifecycle")
    parser.add_argument("--protected-branches", default="main")
    return parser.parse_args(argv)


def classify_pull_request(
    *,
    pr: Dict[str, Any],
    changed_files: List[str],
    has_merge_base: bool,
    stale_days: int,
    now_ts: str,
) -> Dict[str, Any]:
    labels: List[str] = []
    actions: List[str] = []
    risk_level = "L1"

    if not has_merge_base:
        labels.append(LABEL_NO_MERGE_BASE)
        labels.append(LABEL_MANUAL_REVIEW)
        actions.append("add_label")
        actions.append("open_issue")
        return {"risk_level": "L2", "labels": labels, "actions": actions}

    if len(changed_files) == 0:
        labels.append(LABEL_EMPTY_DIFF)
        actions.append("close_pr")
        return {"risk_level": risk_level, "labels": labels, "actions": actions}

    updated = _parse_ts(str(pr.get("updated_at") or now_ts))
    now = _parse_ts(now_ts)
    if (now - updated).days >= stale_days:
        labels.append(LABEL_STALE)
        actions.extend(["add_label", "comment_reminder"])

    return {"risk_level": risk_level, "labels": labels, "actions": actions}


def classify_branch(*, branch: Dict[str, Any], retention_days: int) -> Dict[str, Any]:
    name = str(branch.get("name") or "")
    if branch.get("protected") or name == "main":
        return {"risk_level": "L3", "labels": [LABEL_MANUAL_REVIEW], "actions": []}

    if branch.get("is_merged") and int(branch.get("age_days", 0)) >= retention_days:
        return {
            "risk_level": "L1",
            "labels": [LABEL_MERGED_CANDIDATE, LABEL_AUTO_DELETED],
            "actions": ["delete_branch"],
        }

    return {"risk_level": "L1", "labels": [], "actions": []}


def github_api_call(
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
    token: Optional[str] = None,
) -> Dict[str, Any]:
    url = f"https://api.github.com{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "branch-lifecycle-bot",
    }
    tok = token or os.getenv("GITHUB_TOKEN", "")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8")
            if not text.strip():
                return {}
            return json.loads(text)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"{method} {path} failed: {exc.code} {body}") from exc


def execute_actions(
    *,
    repo: str,
    target: Dict[str, Any],
    actions: List[str],
    labels: List[str],
    dry_run: bool,
    api_call: Callable[[str, str, Optional[Dict[str, Any]]], Dict[str, Any]],
) -> Dict[str, Any]:
    planned = list(actions)
    executed: List[str] = []
    if dry_run:
        return {"planned": planned, "executed": executed}

    if target["type"] == "pr":
        pr_number = int(target["number"])
        if "add_label" in actions and labels:
            api_call("POST", f"/repos/{repo}/issues/{pr_number}/labels", {"labels": labels})
            executed.append("add_label")
        if "comment_reminder" in actions:
            api_call(
                "POST",
                f"/repos/{repo}/issues/{pr_number}/comments",
                {"body": "Automated reminder: PR is stale, please update or close."},
            )
            executed.append("comment_reminder")
        if "close_pr" in actions:
            api_call("PATCH", f"/repos/{repo}/pulls/{pr_number}", {"state": "closed"})
            executed.append("close_pr")
        if "open_issue" in actions:
            api_call(
                "POST",
                f"/repos/{repo}/issues",
                {
                    "title": f"[branch-bot] manual review required for PR #{pr_number}",
                    "body": "Detected no-merge-base or history anomaly. Manual review required.",
                    "labels": [LABEL_MANUAL_REVIEW],
                },
            )
            executed.append("open_issue")

    if target["type"] == "branch":
        branch_name = urllib.parse.quote(str(target["name"]), safe="")
        if "delete_branch" in actions:
            api_call("DELETE", f"/repos/{repo}/git/refs/heads/{branch_name}", None)
            executed.append("delete_branch")

    return {"planned": planned, "executed": executed}


def write_artifacts(
    *,
    base_dir: Path,
    scan: Dict[str, Any],
    actions: Dict[str, Any],
    summary: Dict[str, Any],
    timestamp: str,
) -> Dict[str, Path]:
    base_dir.mkdir(parents=True, exist_ok=True)
    scan_path = base_dir / f"scan-{timestamp}.json"
    actions_path = base_dir / f"actions-{timestamp}.json"
    summary_path = base_dir / f"summary-{timestamp}.json"
    scan_path.write_text(json.dumps(scan, ensure_ascii=False, indent=2), encoding="utf-8")
    actions_path.write_text(json.dumps(actions, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"scan": scan_path, "actions": actions_path, "summary": summary_path}


def _safe_api_call(token: str):
    def _call(method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return github_api_call(method, path, payload, token=token)

    return _call


def _fetch_open_prs(repo: str, api_call) -> List[Dict[str, Any]]:
    prs = api_call("GET", f"/repos/{repo}/pulls?state=open&per_page=100", None)
    return prs if isinstance(prs, list) else []


def _fetch_pr_files(repo: str, pr_number: int, api_call) -> List[str]:
    files = api_call("GET", f"/repos/{repo}/pulls/{pr_number}/files?per_page=100", None)
    out: List[str] = []
    if isinstance(files, list):
        for item in files:
            name = str((item or {}).get("filename") or "").strip()
            if name:
                out.append(name)
    return out


def _has_merge_base(repo: str, head_ref: str, api_call) -> bool:
    try:
        api_call("GET", f"/repos/{repo}/compare/main...{head_ref}", None)
        return True
    except RuntimeError as exc:
        text = str(exc).lower()
        if "no common ancestor" in text or "404" in text:
            return False
        return True


def _fetch_branches(repo: str, api_call) -> List[Dict[str, Any]]:
    branches = api_call("GET", f"/repos/{repo}/branches?per_page=100", None)
    return branches if isinstance(branches, list) else []


def _run(repo: str, dry_run: bool, stale_days: int, retention_days: int, artifacts_dir: str) -> int:
    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required")

    api_call = _safe_api_call(token)
    now_ts = _now_utc().isoformat().replace("+00:00", "Z")
    timestamp = _now_utc().strftime("%Y%m%dT%H%M%SZ")

    open_prs = _fetch_open_prs(repo, api_call)
    branches = _fetch_branches(repo, api_call)
    scan: Dict[str, Any] = {"open_pr_count": len(open_prs), "branch_count": len(branches), "prs": [], "branches": []}
    action_logs: List[Dict[str, Any]] = []
    error_count = 0

    for pr in open_prs:
        number = int(pr.get("number"))
        head_ref = str((pr.get("head") or {}).get("ref") or "")
        changed_files = _fetch_pr_files(repo, number, api_call)
        has_merge_base = _has_merge_base(repo, head_ref, api_call)
        decision = classify_pull_request(
            pr=pr,
            changed_files=changed_files,
            has_merge_base=has_merge_base,
            stale_days=stale_days,
            now_ts=now_ts,
        )
        scan["prs"].append({"number": number, "head_ref": head_ref, "decision": decision})
        try:
            result = execute_actions(
                repo=repo,
                target={"type": "pr", "number": number},
                actions=decision["actions"],
                labels=decision["labels"],
                dry_run=dry_run,
                api_call=api_call,
            )
            action_logs.append({"target": f"pr#{number}", "result": result})
        except Exception as exc:  # pragma: no cover
            error_count += 1
            action_logs.append({"target": f"pr#{number}", "error": str(exc)})

    for branch in branches:
        name = str(branch.get("name") or "")
        if not name:
            continue
        commit = branch.get("commit") or {}
        commit_ts = str((((commit.get("commit") or {}).get("author") or {}).get("date") or now_ts))
        age_days = (_parse_ts(now_ts) - _parse_ts(commit_ts)).days
        is_merged = not bool(api_call("GET", f"/repos/{repo}/pulls?state=open&head={repo.split('/')[0]}:{name}", None))
        branch_view = {
            "name": name,
            "protected": bool(branch.get("protected")),
            "is_merged": is_merged,
            "age_days": age_days,
        }
        decision = classify_branch(branch=branch_view, retention_days=retention_days)
        scan["branches"].append({"name": name, "decision": decision})
        try:
            result = execute_actions(
                repo=repo,
                target={"type": "branch", "name": name},
                actions=decision["actions"],
                labels=decision["labels"],
                dry_run=dry_run,
                api_call=api_call,
            )
            action_logs.append({"target": f"branch:{name}", "result": result})
        except Exception as exc:  # pragma: no cover
            error_count += 1
            action_logs.append({"target": f"branch:{name}", "error": str(exc)})

    summary = {
        "repo": repo,
        "dry_run": dry_run,
        "run_timestamp": now_ts,
        "error_count": error_count,
        "action_log_count": len(action_logs),
    }
    write_artifacts(
        base_dir=Path(artifacts_dir),
        scan=scan,
        actions={"items": action_logs},
        summary=summary,
        timestamp=timestamp,
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if error_count == 0 else 1


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv or [])
    return _run(
        repo=args.repo,
        dry_run=args.dry_run,
        stale_days=args.stale_days,
        retention_days=args.retention_days,
        artifacts_dir=args.artifacts_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main(os.sys.argv[1:]))
