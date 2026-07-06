#!/usr/bin/env python3
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


def load_event(event_path: str) -> Dict:
    path = Path(event_path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def collect_changed_files(event: Dict) -> List[str]:
    changed: List[str] = []
    for commit in event.get("commits", []):
        for key in ("added", "modified", "removed"):
            changed.extend(commit.get(key, []))
    # Deduplicate while keeping order
    return list(dict.fromkeys(changed))


def main() -> int:
    repo = os.getenv("GITHUB_REPOSITORY", "")
    ref = os.getenv("GITHUB_REF", "")
    sha = os.getenv("GITHUB_SHA", "")
    actor = os.getenv("GITHUB_ACTOR", "")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    event_name = os.getenv("GITHUB_EVENT_NAME", "")
    event_path = os.getenv("GITHUB_EVENT_PATH", "")

    event = load_event(event_path)
    head_commit = event.get("head_commit", {})
    changed_files = collect_changed_files(event)

    audit = {
        "audit_version": "v1",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "repository": repo,
        "event_name": event_name,
        "ref": ref,
        "sha": sha,
        "actor": actor,
        "run_id": run_id,
        "head_commit": {
            "id": head_commit.get("id", ""),
            "message": head_commit.get("message", ""),
            "author": head_commit.get("author", {}),
            "url": head_commit.get("url", ""),
        },
        "changed_files_count": len(changed_files),
        "changed_files": changed_files,
    }

    output_dir = Path("artifacts/merge_audit")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"merge_audit_{sha[:12] or 'unknown'}.json"
    output_file.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")

    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        lines = [
            "## Post Merge Audit",
            "",
            f"- repository: `{repo}`",
            f"- ref: `{ref}`",
            f"- sha: `{sha}`",
            f"- actor: `{actor}`",
            f"- changed_files_count: `{len(changed_files)}`",
            f"- audit_file: `{output_file}`",
            "",
        ]
        Path(summary_path).write_text("\n".join(lines), encoding="utf-8")

    print(f"Audit file generated: {output_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
