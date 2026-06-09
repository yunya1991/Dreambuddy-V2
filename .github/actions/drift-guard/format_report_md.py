import json
from typing import Any, Dict


def format_report_md(report: Dict[str, Any]) -> str:
    lines = []
    lines.append("# Drift Guard Report")
    lines.append("")
    lines.append(f"- Change Class: {report.get('change_class')}")
    lines.append(f"- Verdict: {'PASS' if not report.get('reason_codes') else 'BLOCK'}")
    lines.append(f"- Reason Codes: {', '.join(report.get('reason_codes') or []) or 'NONE'}")
    lines.append("")
    lines.append("## Changed Files By Module")
    lines.append("")
    by_module = report.get("changed_files_by_module") or {}
    for module, files in by_module.items():
        lines.append(f"### {module}")
        for file_path in files:
            lines.append(f"- {file_path}")
        lines.append("")
    lines.append("## Required Docs (sha256)")
    lines.append("")
    docs = report.get("docs_hashes") or {}
    for path, digest in docs.items():
        lines.append(f"- {path}: {digest}")
    lines.append("")
    lines.append("## Raw JSON")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(report, ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    return "\n".join(lines)
