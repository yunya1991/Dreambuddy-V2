#!/usr/bin/env python3
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, Tuple


REQUIRED_CHECK = "PR Gate Checks"


def parse_repo_input(repo_input: str) -> str:
    value = repo_input.strip()
    m = re.match(r"^https?://github\.com/([^/]+/[^/]+?)(?:\.git|/)?$", value)
    if m:
        return m.group(1)
    if re.match(r"^[^/]+/[^/]+$", value):
        return value
    raise ValueError(f"Invalid repo input: {repo_input}")


def validate_main_protection(protection_payload: Dict) -> Tuple[bool, str]:
    checks = (
        protection_payload.get("required_status_checks", {})
        .get("checks", [])
    )
    contexts = [item.get("context", "") for item in checks]
    if REQUIRED_CHECK not in contexts:
        return False, f"required check missing: {REQUIRED_CHECK}"
    return True, "main protection includes required PR gate check"


def gh_api_json(path: str) -> Dict:
    res = subprocess.run(
        ["gh", "api", path],
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or res.stdout.strip())
    return json.loads(res.stdout)


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/ci/remote_repo_guard.py <owner/repo|repo_url>", file=sys.stderr)
        return 2

    repo = parse_repo_input(sys.argv[1])
    repo_meta = gh_api_json(f"repos/{repo}")
    default_branch = repo_meta.get("default_branch", "")
    if default_branch != "main":
        print(f"default branch is {default_branch}, expected main", file=sys.stderr)
        return 1

    protection = gh_api_json(f"repos/{repo}/branches/main/protection")
    ok, msg = validate_main_protection(protection)
    if not ok:
        print(msg, file=sys.stderr)
        return 1

    print(f"[remote_repo_guard] repo={repo} ok: {msg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
