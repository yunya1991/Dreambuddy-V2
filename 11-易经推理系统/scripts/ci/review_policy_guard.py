#!/usr/bin/env python3
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Iterable, Tuple


def review_policy_check(author_login: str, owner_login: str, review_states: Iterable[str]) -> Tuple[bool, str]:
    if author_login == owner_login:
        return True, "owner bypass: no manual approval required"

    approved = sum(1 for state in review_states if state == "APPROVED")
    if approved >= 1:
        return True, f"approved reviews={approved}"

    return False, "non-owner PR requires at least one APPROVED review"


def gh_api_get(url: str, token: str) -> dict | list:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def write_summary(message: str, ok: bool) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = ["## Review Policy Guard", ""]
    lines.append(f"- Result: {'PASSED' if ok else 'FAILED'}")
    lines.append(f"- Detail: {message}")
    lines.append("")
    Path(summary_path).write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    token = os.getenv("GITHUB_TOKEN", "")
    repo = os.getenv("GITHUB_REPOSITORY", "")
    event_path = os.getenv("GITHUB_EVENT_PATH", "")
    owner_login = os.getenv("OWNER_LOGIN", "yunya1991")

    if not token or not repo or not event_path:
        print("GITHUB_TOKEN, GITHUB_REPOSITORY, GITHUB_EVENT_PATH are required.", file=sys.stderr)
        return 2

    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    pr = event.get("pull_request", {})
    pr_number = pr.get("number")
    author_login = pr.get("user", {}).get("login", "")

    if not pr_number or not author_login:
        print("PR context missing in event payload.", file=sys.stderr)
        return 2

    reviews_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
    reviews = gh_api_get(reviews_url, token)
    states = [item.get("state", "") for item in reviews]

    ok, message = review_policy_check(author_login, owner_login, states)
    write_summary(message, ok)

    if not ok:
        print(f"Review policy guard failed: {message}", file=sys.stderr)
        return 1

    print(f"Review policy guard passed: {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
