"""四大系统自动同步分发器 — 变更驱动的机器层双保险。

解决"信息太多忘记调用同步 SKILL"的反模式。
post-commit 时根据变更文件类型自动分发到对应系统：
  - SKILL.md 变更      → SKILL 索引系统（auto_register_skill.py）
  - 2-KNOWLEDGE/ 变更   → 知识库系统（build_index.py 增量向量化）
  - 其他 .md 文档变更   → 文档管理系统（写入待同步队列，AI 层消费）
  - 所有变更            → 认知系统（cognitive_hook.py，独立 hook 处理）

FAIL-OPEN：任何子系统失败不阻塞，如实写入日志和待同步队列。
工程约束：HC-1a（独立模块）/ FAIL-OPEN / 零回归 / 只产同步信号
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]  # .../dreambuddy-v2

# 复用 auto_register_skill 的 git 路径发现
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


def _find_git() -> str:
    import shutil
    found = shutil.which("git")
    if found:
        return found
    for candidate in ("/usr/bin/git", "/opt/homebrew/bin/git", "/usr/local/bin/git"):
        if Path(candidate).exists():
            return candidate
    return "git"


_GIT = _find_git()

# 同步日志/队列位置
_SYNC_LOG = _HERE / "auto_sync_dispatcher.log"
_PENDING_QUEUE = _HERE / "pending_sync_queue.json"


# ─────────────────────────────── 变更分类 ───────────────────────────────

def classify_changes(files: list[str]) -> dict[str, list[str]]:
    """将变更文件按目标系统分类。

    Returns:
        {
            "skill_index": [...],      # SKILL.md 变更
            "knowledge_base": [...],   # 2-KNOWLEDGE/ 下文件
            "doc_management": [...],   # 其他 .md 文档
            "other": [...],            # 代码等其他文件
        }
    """
    buckets: dict[str, list[str]] = {
        "skill_index": [],
        "knowledge_base": [],
        "doc_management": [],
        "other": [],
    }
    for f in files:
        p = Path(f)
        name = p.name.lower()
        if name == "skill.md":
            buckets["skill_index"].append(f)
        elif f.startswith("2-KNOWLEDGE/"):
            buckets["knowledge_base"].append(f)
        elif p.suffix.lower() == ".md":
            buckets["doc_management"].append(f)
        else:
            buckets["other"].append(f)
    return buckets


# ─────────────────────────────── 变更检测 ───────────────────────────────

def detect_changes(diff_base: str = "HEAD^") -> list[str]:
    """检测本次 commit 或工作区的变更文件列表。

    diff_base == "HEAD" 时额外检测未跟踪文件（git status --porcelain）。
    """
    files: list[str] = []
    try:
        # 1. git diff 检测已跟踪的变更
        result = subprocess.run(
            [_GIT, "diff", "--name-status", diff_base, "--"],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.split("\t", 1)
                if len(parts) < 2:
                    continue
                status = parts[0].strip()
                if status and status[0] in ("A", "M", "D", "R"):
                    filepath = parts[-1].strip() if status.startswith("R") else parts[1].strip()
                    files.append(filepath)

        # 2. 工作区模式下检测未跟踪文件
        if diff_base == "HEAD":
            status_result = subprocess.run(
                [_GIT, "status", "--porcelain", "--untracked-files=all"],
                cwd=str(_REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if status_result.returncode == 0:
                for line in status_result.stdout.splitlines():
                    if line.startswith("??"):
                        filepath = line[3:].strip()
                        if filepath not in files:
                            files.append(filepath)
    except Exception:
        pass  # FAIL-OPEN
    return files


# ─────────────────────────────── 各系统同步 ───────────────────────────────

def sync_skill_index(skill_files: list[str]) -> dict[str, Any]:
    """SKILL 索引系统：调用 auto_register_skill.py 注册新 SKILL。"""
    if not skill_files:
        return {"status": "skipped", "reason": "no skill changes"}

    # 提取 SKILL 目录（去掉 SKILL.md 文件名）
    skill_dirs = list({str(Path(f).parent) for f in skill_files})

    try:
        from auto_register_skill import register_skills
        report = register_skills(
            skill_dirs=[Path(d) for d in skill_dirs],
            auto_detect=False,
            skip_build=False,
        )
        return {
            "status": report.get("status", "unknown"),
            "skills": skill_dirs,
            "red_flags": report.get("red_flags", []),
        }
    except Exception as e:
        return {"status": "failed", "error": str(e), "skills": skill_dirs}


def sync_knowledge_base(kb_files: list[str]) -> dict[str, Any]:
    """知识库系统：调用 build_index.py 增量更新向量化索引。"""
    if not kb_files:
        return {"status": "skipped", "reason": "no knowledge changes"}

    build_index = _REPO_ROOT / "2-KNOWLEDGE" / "9-RAG-INFRA" / "vector_store" / "build_index.py"
    if not build_index.exists():
        return {"status": "skipped", "reason": "build_index.py not found"}

    try:
        result = subprocess.run(
            [sys.executable, str(build_index)],
            cwd=str(build_index.parent),
            capture_output=True,
            text=True,
            timeout=120,
        )
        return {
            "status": "success" if result.returncode == 0 else "failed",
            "files_count": len(kb_files),
            "stdout_tail": result.stdout[-500:] if result.stdout else "",
            "stderr_tail": result.stderr[-500:] if result.stderr else "",
        }
    except Exception as e:
        return {"status": "failed", "error": str(e)}


def sync_doc_management(doc_files: list[str]) -> dict[str, Any]:
    """文档管理系统：写入待同步队列，由 AI 层 dream-doc-sync-workflow 消费。

    文档索引更新涉及 INDEX.md 格式判断，不适合机器层全自动，
    因此机器层只负责"登记待同步"，AI 层负责实际执行。
    """
    if not doc_files:
        return {"status": "skipped", "reason": "no doc changes"}

    queue = _load_queue()
    for f in doc_files:
        queue["pending"].append({
            "path": f,
            "added_at": datetime.now(timezone.utc).isoformat(),
            "action": "sync_doc_index",
        })
    _save_queue(queue)

    return {
        "status": "queued",
        "files_count": len(doc_files),
        "queue_path": str(_PENDING_QUEUE),
        "note": "AI 层 dream-code-commit-sync-workflow 步骤8 消费此队列",
    }


# ─────────────────────────────── 待同步队列 ───────────────────────────────

def _load_queue() -> dict[str, Any]:
    if _PENDING_QUEUE.exists():
        try:
            return json.loads(_PENDING_QUEUE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"pending": [], "processed": []}


def _save_queue(queue: dict[str, Any]) -> None:
    try:
        _PENDING_QUEUE.parent.mkdir(parents=True, exist_ok=True)
        _PENDING_QUEUE.write_text(
            json.dumps(queue, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass  # FAIL-OPEN


def consume_queue() -> dict[str, Any]:
    """AI 层调用：消费待同步队列，返回待处理项并标记为已处理。"""
    queue = _load_queue()
    pending = queue.get("pending", [])
    if not pending:
        return {"has_pending": False, "items": []}

    # 标记为已处理（AI 层负责实际执行）
    queue["processed"].extend(pending)
    queue["pending"] = []
    _save_queue(queue)

    return {"has_pending": True, "items": pending}


# ─────────────────────────────── 主分发流程 ───────────────────────────────

def dispatch(diff_base: str = "HEAD^") -> dict[str, Any]:
    """主分发流程：检测变更 → 分类 → 分发到各系统。"""
    report: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "diff_base": diff_base,
        "changes": {},
        "results": {},
        "red_flags": [],
    }

    # 1. 检测变更
    files = detect_changes(diff_base)
    if not files:
        report["status"] = "no_changes"
        return report

    # 2. 分类
    buckets = classify_changes(files)
    report["changes"] = {k: len(v) for k, v in buckets.items()}

    # 3. 分发到各系统
    report["results"]["skill_index"] = sync_skill_index(buckets["skill_index"])
    report["results"]["knowledge_base"] = sync_knowledge_base(buckets["knowledge_base"])
    report["results"]["doc_management"] = sync_doc_management(buckets["doc_management"])

    # 4. 汇总红旗
    for system, result in report["results"].items():
        if result.get("status") in ("failed", "validation_failed", "build_failed"):
            report["red_flags"].append(f"[{system}] {result.get('error', result.get('status'))}")
        if result.get("red_flags"):
            for rf in result["red_flags"]:
                report["red_flags"].append(f"[{system}] {rf}")

    report["status"] = "completed_with_red_flags" if report["red_flags"] else "success"
    return report


# ─────────────────────────────── CLI ───────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="auto_sync_dispatcher",
        description="Auto-sync dispatcher for 4 systems (skill index / knowledge base / doc management / cognitive)",
    )
    parser.add_argument(
        "--diff-base",
        default="HEAD^",
        help="Git diff base (default: HEAD^ for post-commit; use HEAD for working tree)",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--consume-queue",
        action="store_true",
        help="Consume the pending doc-sync queue (for AI layer)",
    )
    args = parser.parse_args(argv)

    if args.consume_queue:
        result = consume_queue()
        if args.as_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Pending items: {len(result['items'])}")
            for item in result["items"]:
                print(f"  - {item['path']} ({item['action']})")
        return 0

    try:
        report = dispatch(diff_base=args.diff_base)
    except Exception as e:
        report = {"status": "fatal_error", "error": str(e), "red_flags": [str(e)]}

    # 写日志
    try:
        _SYNC_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_SYNC_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(report, ensure_ascii=False) + "\n")
    except Exception:
        pass

    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human(report)

    return 1 if report.get("red_flags") else 0


def _print_human(report: dict[str, Any]) -> None:
    print("=== Auto-Sync Dispatcher Report ===")
    print(f"Status: {report.get('status')}")
    print(f"Diff base: {report.get('diff_base')}")
    changes = report.get("changes", {})
    if changes:
        print("Changes by system:")
        for system, count in changes.items():
            if count:
                print(f"  {system}: {count} file(s)")
    results = report.get("results", {})
    for system, result in results.items():
        st = result.get("status", "unknown")
        print(f"  [{system}] {st}")
    if report.get("red_flags"):
        print("🚩 Red flags:")
        for rf in report["red_flags"]:
            print(f"   - {rf}")
    else:
        print("✅ No red flags")


if __name__ == "__main__":
    sys.exit(main())
