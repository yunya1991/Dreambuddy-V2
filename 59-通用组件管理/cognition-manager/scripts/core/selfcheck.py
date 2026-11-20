"""安装自检：契约结构、report 口径、版本与工作区状态。

不写任何文件；`cm selfcheck` 用于安装后、发版前快速确认「装的这份是自洽的」。
"""

from __future__ import annotations

from pathlib import Path

from . import __version__, contract, report

HEALTH_SAMPLES = (
    ({}, "good"),
    ({"broken_links": 1}, "attention"),
    ({"broken_links": 1, "orphan_files": 1, "doc_drift": 1}, "poor"),
)


def run(root=None) -> dict:
    checks = []

    def attempt(name, func):
        try:
            ok, detail = func()
        except Exception as exc:  # 自检自身异常按失败呈现
            ok, detail = False, "检查异常：{}".format(exc)
        checks.append({"check": name, "ok": ok, "detail": detail})

    data = None

    def contract_structure():
        nonlocal data
        data = contract.load()
        return True, "契约 v{}：{} 项指标 / {} 项占比".format(
            data["schema_version"], len(data["metrics"]), len(data["ratios"]))

    def report_alignment():
        problems = contract.problem_keys(data)
        if tuple(report.PROBLEM_KEYS) != tuple(problems):
            return False, "report.PROBLEM_KEYS 与契约不一致"
        labels = contract.labels(data)
        blank = [key for key, label in labels.items() if not str(label).strip()]
        if blank:
            return False, "指标缺少标签：{}".format(", ".join(blank))
        return True, "九项指标与 report 口径一致"

    def health_alignment():
        for values, expected in HEALTH_SAMPLES:
            actual = report.health_of(values)
            if actual != expected:
                return False, "health 抽样不一致：{} → {}（期望 {}）".format(values, actual, expected)
        return True, "health 三档抽样一致"

    attempt("指标契约", contract_structure)
    attempt("report 口径", report_alignment)
    attempt("health 分档", health_alignment)

    workspace = {"initialized": False}
    if root is not None:
        cm_dir = Path(root).expanduser() / ".cm"
        workspace["initialized"] = (cm_dir / "config.yaml").exists() and (cm_dir / "index.db").exists()
        workspace["path"] = str(cm_dir)

    return {
        "ok": all(item["ok"] for item in checks),
        "version": __version__,
        "contract_version": data["schema_version"] if data else None,
        "checks": checks,
        "workspace": workspace,
    }


def format_selfcheck(result: dict) -> str:
    lines = ["认知管家 · 安装自检（v{}）".format(result["version"])]
    if result.get("contract_version"):
        lines.append("指标契约：v{}".format(result["contract_version"]))
    for item in result["checks"]:
        lines.append("  [{}] {}：{}".format("PASS" if item["ok"] else "FAIL", item["check"], item["detail"]))
    workspace = result.get("workspace") or {}
    if "path" in workspace:
        lines.append("工作区：{}（{}）".format(
            workspace["path"], "已初始化" if workspace["initialized"] else "未初始化"))
    lines.append("结论：{}".format("通过" if result["ok"] else "未通过"))
    return "\n".join(lines)
