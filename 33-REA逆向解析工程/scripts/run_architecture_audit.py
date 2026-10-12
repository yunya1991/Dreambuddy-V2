"""P3-2: 架构自进化闭环 — post-commit 触发。

链路：REA investigate → ArchitectureReverseDeriver 架构债务 →
ReflectionEngine 架构健康度 → JSON 报告持久化。

由 .git/hooks/post-commit 调用，每次 commit 后自动跑（非阻塞，失败不影响 commit）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "23-四层闭环自进化交易架构"))
sys.path.insert(0, str(REPO_ROOT / "33-REA逆向解析工程"))

# 默认扫描目标：自进化系统核心目录
DEFAULT_TARGET = str(
    REPO_ROOT / "23-四层闭环自进化交易架构" / "dreambuddy_evolution"
)
REPORT_PATH = str(
    REPO_ROOT
    / "23-四层闭环自进化交易架构"
    / "dreambuddy_evolution"
    / "gene_data"
    / "architecture_health_report.json"
)


def run_audit(target: str = DEFAULT_TARGET, report_path: str = REPORT_PATH) -> int:
    """执行架构自进化审计闭环。

    Returns:
        0 成功（非阻塞，即使检测到债务也返回 0，不阻断 commit）
    """
    try:
        from core.investigation_workflow import investigate
        from dreambuddy_evolution.engines.reverse_deriver import (
            ArchitectureReverseDeriver,
        )
        from dreambuddy_evolution.engines.reflection_engine import ReflectionEngine

        print("[arch-audit] REA 逆向解析中...")
        result = investigate(target, feature="架构自进化审计(post-commit)")
        evidence = result["evidence"]
        print(f"[arch-audit] Evidence: {len(evidence)} 条, "
              f"known_gaps: {len(result['known_gaps'])} 项")

        debt = ArchitectureReverseDeriver().derive_architecture_debt(evidence)
        report = ReflectionEngine().reflect_architecture(debt)
        report.save_json(report_path)
        print(f"[arch-audit] 报告已写入 {report_path}")
        report.print_summary()

        if report.triggered_windows:
            print(f"\n[arch-audit] ⚠️ 检测到 {len(report.triggered_windows)} 个 "
                  f"refactor 窗口已触发，建议尽快处理。")
        return 0
    except Exception as e:
        print(f"[arch-audit] FAIL-OPEN: 审计失败（不影响 commit）: {e}")
        return 0


if __name__ == "__main__":
    sys.exit(run_audit())
