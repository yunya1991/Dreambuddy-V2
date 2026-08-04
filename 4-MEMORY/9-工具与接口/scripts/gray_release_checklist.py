#!/usr/bin/env python3
"""灰度观察期每日检查脚本（设计节 6.5 检查表 7 项）。

用法：
  python3 scripts/gray_release_checklist.py            # 跑全部 7 项检查
  python3 scripts/gray_release_checklist.py --day 3    # 指定灰度第几天
  python3 scripts/gray_release_checklist.py --json     # JSON 输出（供日志聚合）

设计节 6.5 检查表：
  1. daemon 健康         cognitive-cli healthcheck          status: healthy
  2. SKILL.md 完整性     cognitive-cli skills list          14 个全部 loaded
  3. recall 命中率       cognitive-cli stats recall         process_hit_rate > 60%
  4. process_block 注入  日志统计                           每天 ≥ 5 次
  5. 新 applied 关联率   cognitive-cli stats applied        parent_skill_ids != custom-path 比例 > 60%
  6. mapping 统计累积    cognitive-cli stats mapping        至少 1 个 Skill success ≥ 3
  7. 异常日志            grep error daemon.log             无 SkillLoader/process_block ERROR
"""
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

_SCRIPT_DIR = Path(__file__).parent.parent
_DAEMON_LOG = Path("/tmp/cognitive-daemon.log")


@dataclass
class GrayCheckResult:
    """灰度检查单项结果。"""
    name: str
    passed: bool
    expected: str
    actual: str
    detail: str = ""


def _run_cli(cmd: str) -> Any:
    """执行 cognitive-cli 命令并返回 JSON 结果。"""
    try:
        proc = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            return {}
        return json.loads(proc.stdout)
    except (json.JSONDecodeError, subprocess.TimeoutExpired, OSError):
        return {}


# ---- 7 项检查 ----

def _check_daemon_health() -> GrayCheckResult:
    """检查项 1：daemon 健康。"""
    result = _run_cli("python3 cognitive_loop_entry.py healthcheck")
    status = result.get("status", "unknown")
    return GrayCheckResult(
        name="daemon 健康",
        passed=status == "healthy",
        expected="status: healthy",
        actual=f"status: {status}",
        detail=json.dumps(result, ensure_ascii=False)[:200],
    )


def _check_skill_md_completeness() -> GrayCheckResult:
    """检查项 2：SKILL.md 完整性，14 个全部 loaded。"""
    result = _run_cli("python3 cognitive_loop_entry.py skills list")
    skills = result.get("skills", [])
    loaded_count = sum(1 for s in skills if s.get("loaded"))
    return GrayCheckResult(
        name="SKILL.md 完整性",
        passed=loaded_count == 14,
        expected="14 个全部 loaded",
        actual=f"{loaded_count} 个 loaded",
        detail=f"skills: {[s.get('name') for s in skills if not s.get('loaded')]}未加载",
    )


def _check_recall_hit_rate() -> GrayCheckResult:
    """检查项 3：recall 命中率 process_hit_rate > 60%。"""
    result = _run_cli("python3 cognitive_loop_entry.py stats recall")
    hit_rate = result.get("process_hit_rate", 0.0)
    pct = f"{hit_rate * 100:.0f}%" if hit_rate <= 1.0 else f"{hit_rate:.2f}"
    return GrayCheckResult(
        name="recall 命中率",
        passed=hit_rate > 0.60,
        expected="process_hit_rate > 60%",
        actual=f"process_hit_rate: {pct}",
        detail=pct,
    )


def _check_process_block_injection_count() -> GrayCheckResult:
    """检查项 4：process_block 注入次数每天 ≥ 5 次。"""
    result = _run_cli("python3 cognitive_loop_entry.py stats injection")
    count = result.get("injection_count", 0)
    return GrayCheckResult(
        name="process_block 注入次数",
        passed=count >= 5,
        expected="每天 ≥ 5 次",
        actual=f"今天 {count} 次",
        detail=str(count),
    )


def _check_applied_association() -> GrayCheckResult:
    """检查项 5：新 applied 关联率 > 60%（parent_skill_ids != custom-path）。"""
    result = _run_cli("python3 cognitive_loop_entry.py stats applied")
    applied_list = result.get("applied", [])
    if not applied_list:
        return GrayCheckResult(
            name="新 applied 关联率", passed=False,
            expected="> 60%", actual="无 applied 数据",
        )
    associated = sum(
        1 for a in applied_list
        if a.get("parent_skill_ids", ["custom-path"]) != ["custom-path"]
    )
    ratio = associated / len(applied_list)
    pct = f"{ratio * 100:.0f}%"
    return GrayCheckResult(
        name="新 applied 关联率",
        passed=ratio > 0.60,
        expected="> 60%",
        actual=f"{pct} ({associated}/{len(applied_list)})",
        detail=pct,
    )


def _check_mapping_accumulation() -> GrayCheckResult:
    """检查项 6：mapping 统计累积，至少 1 个 Skill success ≥ 3。"""
    result = _run_cli("python3 cognitive_loop_entry.py stats mapping")
    mapping_stats = result.get("mapping_stats", {})
    max_success = 0
    best_skill = ""
    for skill_name, stats in mapping_stats.items():
        s = stats.get("success", 0)
        if s > max_success:
            max_success = s
            best_skill = skill_name
    return GrayCheckResult(
        name="mapping 统计累积",
        passed=max_success >= 3,
        expected="至少 1 个 Skill success ≥ 3",
        actual=f"最高: {best_skill} success={max_success}",
        detail=f"max_success={max_success}",
    )


def _check_error_logs() -> GrayCheckResult:
    """检查项 7：异常日志无 SkillLoader/process_block ERROR。"""
    error_lines: List[str] = []
    if _DAEMON_LOG.exists():
        try:
            content = _DAEMON_LOG.read_text(encoding="utf-8", errors="ignore")
            for line in content.splitlines():
                if "ERROR" in line and ("SkillLoader" in line or "process_block" in line):
                    error_lines.append(line.strip())
        except OSError:
            pass
    return GrayCheckResult(
        name="异常日志",
        passed=len(error_lines) == 0,
        expected="无 SkillLoader/process_block ERROR",
        actual=f"{len(error_lines)} 条 ERROR",
        detail="\n".join(error_lines[:3]) if error_lines else "clean",
    )


def run_gray_check() -> List[GrayCheckResult]:
    """跑全部 7 项灰度检查。"""
    return [
        _check_daemon_health(),
        _check_skill_md_completeness(),
        _check_recall_hit_rate(),
        _check_process_block_injection_count(),
        _check_applied_association(),
        _check_mapping_accumulation(),
        _check_error_logs(),
    ]


def main():
    import argparse
    parser = argparse.ArgumentParser(description="灰度观察期每日检查（设计节 6.5）")
    parser.add_argument("--day", type=int, help="灰度第几天（1-7）")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    results = run_gray_check()
    passed_count = sum(1 for r in results if r.passed)

    if args.json:
        output = {
            "day": args.day,
            "total": len(results),
            "passed": passed_count,
            "results": [asdict(r) for r in results],
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"{'='*60}")
        print(f"  灰度观察期检查{' (第 ' + str(args.day) + ' 天)' if args.day else ''}")
        print(f"{'='*60}")
        for r in results:
            status = "✅" if r.passed else "❌"
            print(f"  {status} {r.name}: {r.actual} (期望: {r.expected})")
        print(f"{'='*60}")
        print(f"  通过: {passed_count}/{len(results)}")

    # 全部通过返回 0，否则返回 1
    return 0 if passed_count == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
