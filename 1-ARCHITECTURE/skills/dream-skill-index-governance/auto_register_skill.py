"""SKILL 自动注册器 — 新 SKILL 创建后自动归档进入治理系统。

解决"新 SKILL 创建后忘记手动运行 skill_indexer build"的反模式。
双保险之一（机器层）：被 git post-commit hook 调用，检测新增 SKILL.md 后自动注册。
双保险之二（AI 层）：dream-skill-index-governance / skill-creator SKILL 强制调用。

流程：
  1. 检测新增 SKILL.md（git diff --name-status 或显式传入路径）
  2. 对每个新 SKILL 运行 validate
  3. 运行 build --all 重建 registry.json + 报告
  4. 检测新 SKILL 是否引入冲突/漂移
  5. 输出注册报告（JSON）+ 可选写入日志

FAIL-OPEN：任何步骤失败不阻塞 git/AI 主流程，但如实报告红旗。
工程约束：HC-1a（独立模块）/ HC-9（只产索引信号）/ FAIL-OPEN / 零回归
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 复用 skill_indexer 的核心函数
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from skill_indexer import (  # noqa: E402
    ALL_SKILL_ROOTS,
    build,
    detect_conflicts,
    detect_drift,
    scan_skills,
    validate,
)

_REGISTRY_DIR = _HERE.parent / "_registry"
_REPO_ROOT = _HERE.parents[2]  # .../dreambuddy-v2


# ─────────────────────────────── git 路径发现 ───────────────────────────────

def _find_git() -> str:
    """发现 git 可执行文件路径，兼容 PATH 不含 /usr/bin 的环境。"""
    import shutil
    found = shutil.which("git")
    if found:
        return found
    for candidate in ("/usr/bin/git", "/opt/homebrew/bin/git", "/usr/local/bin/git"):
        if Path(candidate).exists():
            return candidate
    return "git"  # fallback，由调用方捕获异常


_GIT = _find_git()


# ─────────────────────────────── 检测新增 SKILL ───────────────────────────────

def detect_new_skills_from_git(
    repo_root: Path, diff_base: str = "HEAD"
) -> list[Path]:
    """从 git 检测新增的 SKILL.md 文件。

    检测范围：
    1. git diff <diff_base> 中状态为 A（新增）/ R（重命名）的 SKILL.md
    2. git status --porcelain 中状态为 ??（未跟踪）的 SKILL.md
       （仅 diff_base == "HEAD" 时检测，用于 AI 手动调用场景；
        post-commit 模式用 HEAD^ 时不检测未跟踪文件，因为已 commit）

    Args:
        diff_base: 比较基准。
            - "HEAD"（默认）：工作区 vs HEAD，用于 AI 手动调用。
            - "HEAD^"：本次 commit vs 上一次，用于 post-commit hook。
    """
    try:
        new_skills: list[Path] = []

        # 1. git diff 检测已跟踪的新增/重命名
        result = subprocess.run(
            [_GIT, "diff", "--name-status", diff_base, "--"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.split("\t", 1)
                if len(parts) < 2:
                    continue
                status, filepath = parts[0].strip(), parts[1].strip()
                if status.startswith("A") or (status.startswith("R") and len(parts) >= 3):
                    target = parts[-1].strip() if status.startswith("R") else filepath
                    if target.endswith("SKILL.md"):
                        new_skills.append(repo_root / target)

        # 2. git status 检测未跟踪文件（仅 diff_base == "HEAD" 时）
        if diff_base == "HEAD":
            status_result = subprocess.run(
                [_GIT, "status", "--porcelain", "--untracked-files=all"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if status_result.returncode == 0:
                for line in status_result.stdout.splitlines():
                    if not line.startswith("??"):
                        continue
                    filepath = line[3:].strip()
                    if filepath.endswith("SKILL.md"):
                        p = repo_root / filepath
                        if p not in new_skills:
                            new_skills.append(p)

        return new_skills
    except Exception:
        return []  # FAIL-OPEN


# ─────────────────────────────── 注册主流程 ───────────────────────────────

def register_skills(
    skill_dirs: list[Path] | None = None,
    *,
    auto_detect: bool = True,
    skip_build: bool = False,
    diff_base: str = "HEAD",
) -> dict[str, Any]:
    """注册一个或多个新 SKILL 到治理系统。

    Args:
        skill_dirs: 显式指定的 SKILL 目录列表（不含 SKILL.md 文件名）。
                    若为空且 auto_detect=True，则从 git 自动检测。
        auto_detect: 是否从 git 自动检测新增 SKILL。
        skip_build: 是否跳过全量 build（仅 validate，不更新 registry）。

    Returns:
        注册报告 dict，含 detected / validated / built / conflicts / drift / red_flags。
    """
    report: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "detected_skills": [],
        "validation": {},
        "registry_updated": False,
        "registry_count_before": None,
        "registry_count_after": None,
        "conflicts_involving_new": [],
        "drift_involving_new": [],
        "red_flags": [],
        "status": "unknown",
    }

    # 1. 确定待注册 SKILL 列表
    targets: list[Path] = []
    if skill_dirs:
        targets.extend(Path(d) for d in skill_dirs)
    if auto_detect and not targets:
        targets = detect_new_skills_from_git(_REPO_ROOT, diff_base=diff_base)

    # 去重 + 转成目录路径（去掉 SKILL.md）
    seen: set[str] = set()
    unique_targets: list[Path] = []
    for t in targets:
        d = t.parent if t.name == "SKILL.md" else t
        key = str(d.resolve())
        if key not in seen:
            seen.add(key)
            unique_targets.append(d)

    report["detected_skills"] = [str(d) for d in unique_targets]

    if not unique_targets:
        report["status"] = "no_new_skills"
        return report

    # 2. 逐个 validate
    all_valid = True
    for skill_dir in unique_targets:
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            report["validation"][str(skill_dir)] = {
                "valid": False,
                "errors": ["SKILL.md not found"],
                "warnings": [],
            }
            all_valid = False
            report["red_flags"].append(f"SKILL.md not found: {skill_dir}")
            continue
        result = validate(skill_dir)
        report["validation"][str(skill_dir)] = result
        if not result["valid"]:
            all_valid = False
            for err in result["errors"]:
                report["red_flags"].append(f"validate error [{skill_dir.name}]: {err}")
        for warn in result.get("warnings", []):
            report["red_flags"].append(f"validate warning [{skill_dir.name}]: {warn}")

    # 3. 全量 build（重建 registry + 冲突/漂移报告）
    if not skip_build:
        try:
            # 记录 build 前数量
            registry_path = _REGISTRY_DIR / "registry.json"
            if registry_path.exists():
                before = json.loads(registry_path.read_text(encoding="utf-8"))
                report["registry_count_before"] = before.get("total_count")

            build_result = build(ALL_SKILL_ROOTS, _REGISTRY_DIR)
            report["registry_updated"] = True

            after_registry = build_result.get("registry", {})
            report["registry_count_after"] = after_registry.get("total_count")

            # 4. 检查新 SKILL 是否引入冲突/漂移
            new_names = {d.name for d in unique_targets}
            conflicts = build_result.get("conflicts", {})
            conflicts_text = json.dumps(conflicts, ensure_ascii=False)
            for name in new_names:
                if name in conflicts_text:
                    report["conflicts_involving_new"].append(name)

            drift = build_result.get("drift", {})
            drift_text = json.dumps(drift, ensure_ascii=False)
            for name in new_names:
                if name in drift_text:
                    report["drift_involving_new"].append(name)

        except Exception as e:
            report["red_flags"].append(f"build failed: {e}")
            report["status"] = "build_failed"

    # 5. 汇总状态
    if report["red_flags"]:
        report["status"] = "completed_with_red_flags"
    elif all_valid:
        report["status"] = "success"
    else:
        report["status"] = "validation_failed"

    return report


# ─────────────────────────────── CLI ───────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="auto_register_skill",
        description="Auto-register new SKILL.md into governance registry",
    )
    p.add_argument(
        "skill_dirs",
        nargs="*",
        type=Path,
        help="Explicit SKILL directories to register (default: auto-detect from git)",
    )
    p.add_argument(
        "--no-auto-detect",
        action="store_true",
        help="Disable git auto-detection (only register explicit dirs)",
    )
    p.add_argument(
        "--skip-build",
        action="store_true",
        help="Only validate, do not rebuild registry",
    )
    p.add_argument(
        "--diff-base",
        default="HEAD",
        help="Git diff base for auto-detection (default: HEAD; use HEAD^ for post-commit hook)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Output report as JSON",
    )
    p.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Append report to this log file",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        report = register_skills(
            skill_dirs=args.skill_dirs if args.skill_dirs else None,
            auto_detect=not args.no_auto_detect,
            skip_build=args.skip_build,
            diff_base=args.diff_base,
        )
    except Exception as e:
        # FAIL-OPEN：顶层异常不阻塞
        report = {
            "status": "fatal_error",
            "error": str(e),
            "red_flags": [f"fatal: {e}"],
        }

    # 输出
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human_report(report)

    # 写入日志文件
    if args.log_file:
        try:
            args.log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(args.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(report, ensure_ascii=False) + "\n")
        except Exception:
            pass  # FAIL-OPEN

    # 退出码：有红旗返回 1（供 hook 判断），无红旗返回 0
    return 1 if report.get("red_flags") else 0


def _print_human_report(report: dict[str, Any]) -> None:
    print("=== SKILL Auto-Register Report ===")
    print(f"Status: {report.get('status')}")
    print(f"Detected: {len(report.get('detected_skills', []))} skill(s)")
    for s in report.get("detected_skills", []):
        print(f"  - {s}")
    if report.get("registry_count_before") is not None:
        print(
            f"Registry: {report['registry_count_before']} → "
            f"{report.get('registry_count_after')} (updated={report.get('registry_updated')})"
        )
    if report.get("conflicts_involving_new"):
        print(f"⚠️  Conflicts involving new skills: {report['conflicts_involving_new']}")
    if report.get("drift_involving_new"):
        print(f"⚠️  Drift involving new skills: {report['drift_involving_new']}")
    if report.get("red_flags"):
        print("🚩 Red flags:")
        for rf in report["red_flags"]:
            print(f"   - {rf}")
    else:
        print("✅ No red flags")


if __name__ == "__main__":
    sys.exit(main())
