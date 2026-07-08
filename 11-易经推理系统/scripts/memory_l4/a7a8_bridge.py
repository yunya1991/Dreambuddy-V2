"""A7/A8 报告桥接模块。

解析 A7 实践理论报告和 A8 理论验证报告，转译为 L4 可消费的标准格式，
并合并到 ReviewRecord 中。

v0.2 新增模块 — Phase 2 (P1)
"""

import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_a7_report(report_path: Path) -> Dict[str, Any]:
    """解析 A7 实践理论报告。

    Args:
        report_path: A7 报告 JSON 路径

    Returns:
        标准化格式: {practice_audit_result, practice_theory_gap, audit_refs, lessons[]}
    """
    if not report_path.exists():
        return {}

    raw = _load_json(report_path)

    return {
        "practice_audit_result": str(
            raw.get("audit_result") or raw.get("result") or raw.get("summary", "")
        ),
        "practice_theory_gap": str(
            raw.get("practice_theory_gap") or raw.get("gap") or ""
        ),
        "audit_refs": [
            {"type": "repo_file", "ref": str(report_path)}
        ],
        "lessons": raw.get("lessons") or raw.get("takeaways") or [],
        "raw": raw,
    }


def parse_a8_report(report_path: Path) -> Dict[str, Any]:
    """解析 A8 理论验证报告。

    Args:
        report_path: A8 报告 JSON 路径

    Returns:
        标准化格式: {verification_result, theory_critique, confirmed_theories[], contradicted_theories[], consistency_score}
    """
    if not report_path.exists():
        return {}

    raw = _load_json(report_path)

    # 尝试提取一致性评分
    consistency = raw.get("consistency") or raw.get("consistency_score") or raw.get("credibility")
    if consistency is not None:
        try:
            consistency_score = float(consistency) / 100.0 if float(consistency) > 1 else float(consistency)
        except (ValueError, TypeError):
            consistency_score = 0.5
    else:
        consistency_str = str(raw.get("status") or raw.get("verification_status") or "")
        consistency_score = (
            0.9 if "pass" in consistency_str.lower()
            else 0.1 if "fail" in consistency_str.lower()
            else 0.5
        )

    confirmed: List[Dict[str, Any]] = []
    contradicted: List[Dict[str, Any]] = []

    # 尝试提取理论列表
    for item in raw.get("confirmed_theories") or raw.get("validated") or []:
        confirmed.append({
            "theory_name": str(item.get("name") or item.get("theory", "")),
            "confidence": float(item.get("confidence", 0.7)),
        })
    for item in raw.get("contradicted_theories") or raw.get("falsified") or []:
        contradicted.append({
            "theory_name": str(item.get("name") or item.get("theory", "")),
            "confidence": float(item.get("confidence", 0.7)),
        })

    return {
        "verification_result": str(
            raw.get("verification_result") or raw.get("result") or raw.get("summary", "")
        ),
        "theory_critique": str(
            raw.get("theory_critique") or raw.get("critique") or raw.get("analysis", "")
        ),
        "confirmed_theories": confirmed,
        "contradicted_theories": contradicted,
        "consistency_score": round(consistency_score, 4),
        "raw": raw,
    }


def merge_into_review(
    review_record: Dict[str, Any],
    a7_parsed: Dict[str, Any],
    a8_parsed: Dict[str, Any],
) -> Dict[str, Any]:
    """将 A7/A8 解析结果合并到 ReviewRecord。

    Args:
        review_record: ReviewRecord 字典
        a7_parsed: parse_a7_report 的返回值
        a8_parsed: parse_a8_report 的返回值

    Returns:
        更新后的 ReviewRecord
    """
    out = dict(review_record)

    # 合并 A7 到 mistakes/successes
    if a7_parsed:
        out["a7_report_ref"] = "merged"
        gap = a7_parsed.get("practice_theory_gap", "")
        if gap:
            out["mistakes"].append({
                "what": "实践与理论存在差距",
                "why": gap,
                "severity": None,
                "stage_ref": "A7",
                "theory_gap": gap,
            })
        for lesson in a7_parsed.get("lessons", []):
            out["successes"].append({
                "what": str(lesson),
                "why": "A7 实践经验",
                "severity": None,
                "stage_ref": "A7",
                "theory_gap": None,
                "reproducible": None,
            })

    # 合并 A8 到 theory_practice_analysis
    if a8_parsed:
        out["a8_report_ref"] = "merged"
        tpa = out.get("theory_practice_analysis") or {}
        if a8_parsed.get("consistency_score") is not None:
            tpa["consistency_score"] = a8_parsed["consistency_score"]
        if a8_parsed.get("confirmed_theories"):
            tpa["confirmed_theories"] = a8_parsed["confirmed_theories"]
        if a8_parsed.get("contradicted_theories"):
            tpa["contradicted_theories"] = a8_parsed["contradicted_theories"]
        if a8_parsed.get("theory_critique"):
            tpa["gap_analysis"] = a8_parsed["theory_critique"]
        out["theory_practice_analysis"] = tpa

    return out
