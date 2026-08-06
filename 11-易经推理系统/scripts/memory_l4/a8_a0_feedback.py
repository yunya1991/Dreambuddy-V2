#!/usr/bin/env python3
"""
A8→A0 反向反馈链路桥接 (#3-b 三层脑理论)。

功能：
  1. 识别 A8 输出的两种格式：
     - trading_a8: {hypothesis_score, practice_score, gap_score, ...}
       （来自 workflows/trading-decision/A8_theory-practice/entrypoint.py）
     - code_a8:    {subsystem, summary{consistency_score}, doc_only_functions, ...}
       （来自 4-MEMORY/9-工具与接口/a8_check_engine.py 的 A8Report.to_dict()）
  2. 转换为 A8GapDimension 数据类
  3. 通过 A0ContradictionEngine.inject_external_contradiction() 写回 A0 矛盾池

理论映射（三层脑理论 #3）：
  - 新皮质(理性) = A0 矛盾分析 → 7维市场扫描 + 第8维 a8_gap
  - 边缘系统(情感/评估) = A8 理论实践校验 → 评估 gap_score
  - A8→A0 写回 = 边缘系统反馈到理性分析回路
    （原始缺失：A8 单向路由到 A1/A2/A3 修正，但不更新 A0 的矛盾维度）
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class FeedbackResult:
    """A8→A0 反馈结果。"""
    injected: bool                       # 是否成功注入
    dim_id: str = ""                     # 注入的维度 id（a8_gap）
    tension: float = 0.0                 # 注入的张力值
    gap_source: str = ""                 # trading_a8 / code_a8
    evidence: str = ""                   # evidence 文本（调试用）
    message: str = ""                    # 跳过原因/错误信息


def _is_trading_a8(a8_output: Dict[str, Any]) -> bool:
    """判断是否为交易 A8 输出（有 hypothesis_score/gap_score）。"""
    if not isinstance(a8_output, dict):
        return False
    # 从 envelope.payload 取 payload
    a = a8_output.get("payload", a8_output)
    return (
        "gap_score" in a
        or "hypothesis_score" in a
        or "practice_score" in a
    )


def _is_code_a8(a8_output: Dict[str, Any]) -> bool:
    """判断是否为代码 A8 报告（a8_check_engine.py A8Report）。"""
    if not isinstance(a8_output, dict):
        return False
    return (
        "summary" in a8_output
        and isinstance(a8_output["summary"], dict)
        and ("consistency_score" in a8_output["summary"]
             or "doc_only" in a8_output["summary"])
    ) or bool(a8_output.get("doc_only_functions") or a8_output.get("code_only_functions"))


def a8_to_a0_feedback(
    engine,
    a8_output: Dict[str, Any],
    source: Optional[str] = None,
) -> FeedbackResult:
    """
    将 A8 输出解析为矛盾维度并注入 A0 引擎。

    Args:
        engine: A0ContradictionEngine 实例
        a8_output: A8 的输出 dict（支持两种格式）
        source: 显式指定来源（"trading_a8" / "code_a8"），
                不指定时自动推断

    Returns:
        FeedbackResult
    """
    # 延迟导入避免循环依赖
    try:
        from .a0_contradiction_engine import A8GapDimension
    except ImportError:  # 脚本直跑
        from a0_contradiction_engine import A8GapDimension

    if engine is None:
        return FeedbackResult(False, message="engine is None")
    if not isinstance(a8_output, dict):
        return FeedbackResult(False, message=f"a8_output 不是 dict: {type(a8_output)}")

    # 来源推断
    if source is None:
        if _is_trading_a8(a8_output):
            source = "trading_a8"
        elif _is_code_a8(a8_output):
            source = "code_a8"
        else:
            return FeedbackResult(
                False,
                message="无法识别 A8 输出格式（缺少 gap_score / consistency_score 字段）",
            )

    # 解析为 A8GapDimension
    if source == "trading_a8":
        a = a8_output.get("payload", a8_output)
        # 字段校验：至少有 gap_score 或 hypothesis/practice 之一，否则判定为"无有效字段"
        has_gap = "gap_score" in a
        has_hypo = "hypothesis_score" in a
        has_prac = "practice_score" in a
        if not (has_gap or (has_hypo and has_prac)):
            return FeedbackResult(
                False,
                message="trading_a8 需要 gap_score 或 (hypothesis_score + practice_score) 字段",
            )
        hypo = float(a.get("hypothesis_score") or 0.0)
        prac = float(a.get("practice_score") or 0.0)
        # gap_score 显式优先，否则计算
        if "gap_score" in a:
            gap = abs(float(a["gap_score"]))
        else:
            gap = abs(hypo - prac)
        details: Dict[str, Any] = {
            "stage_id": a.get("stage_id"),
            "trace_id": a.get("trace_id") or a.get("correlation_id"),
            "timestamp": a.get("timestamp"),
        }
        gap_dim = A8GapDimension(
            source="trading_a8",
            gap_score=round(gap, 4),
            hypothesis_score=round(hypo, 4),
            practice_score=round(prac, 4),
            details=details,
        )
    else:  # code_a8
        summary = a8_output.get("summary", {}) or {}
        has_summary = bool(summary)
        has_docf = bool(a8_output.get("doc_only_functions"))
        has_codef = bool(a8_output.get("code_only_functions"))
        has_cons = "consistency_score" in summary
        if not (has_summary or has_docf or has_codef):
            return FeedbackResult(
                False,
                message="code_a8 需要 summary 或 doc_only_functions 或 code_only_functions 字段",
            )
        if has_cons:
            cons = float(summary["consistency_score"])
        else:
            # 无一致性分数，从 doc/code 推算：matched/(matched + doc_only + code_only)
            matched = int(summary.get("matched") or 0)
            doc_only_n = int(summary.get("doc_only") or len(a8_output.get("doc_only_functions", [])))
            code_only_n = int(summary.get("code_only") or len(a8_output.get("code_only_functions", [])))
            total = matched + doc_only_n + code_only_n
            cons = round(matched / total * 100.0, 2) if total > 0 else 100.0
        gap = round(1.0 - min(100.0, max(0.0, cons)) / 100.0, 4)
        doc_only = a8_output.get("doc_only_functions") or []
        code_only = a8_output.get("code_only_functions") or []
        details = {
            "subsystem": a8_output.get("subsystem", ""),
            "doc_declared": summary.get("doc_declared", 0),
            "code_implemented": summary.get("code_implemented", 0),
            "matched": summary.get("matched", 0),
            "doc_only_count": summary.get("doc_only", len(doc_only)),
            "code_only_count": summary.get("code_only", len(code_only)),
            "consistency_score": round(cons, 2),
            "doc_only": doc_only,
            "code_only": code_only,
        }
        hypo = 1.0
        prac = round(min(100.0, max(0.0, cons)) / 100.0, 4)
        gap_dim = A8GapDimension(
            source="code_a8",
            gap_score=gap,
            hypothesis_score=hypo,
            practice_score=prac,
            details=details,
        )

    # 注入 A0
    try:
        injected = engine.inject_external_contradiction(gap_dim)
    except Exception as e:
        return FeedbackResult(False, message=f"inject_external_contradiction 异常: {e}")

    return FeedbackResult(
        injected=True,
        dim_id=injected.get("dim_id", "a8_gap"),
        tension=float(injected.get("tension", 0.0)),
        gap_source=source,
        evidence=injected.get("evidence", ""),
        message="",
    )


# ======================================================================
# CLI 入口
# ======================================================================
if __name__ == "__main__":
    import json
    import sys
    import argparse

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
    from memory_l4.a0_contradiction_engine import A0ContradictionEngine

    parser = argparse.ArgumentParser(description="A8→A0 反馈链路 CLI")
    parser.add_argument("--a8-json", help="A8 输出 JSON 文件路径")
    parser.add_argument("--gap", type=float, help="测试用直接指定 gap_score")
    parser.add_argument("--consistency", type=float, help="代码 A8 一致性分数(0-100)")
    args = parser.parse_args()

    engine = A0ContradictionEngine()

    if args.a8_json:
        a8 = json.loads(__import__("pathlib").Path(args.a8_json).read_text())
        res = a8_to_a0_feedback(engine, a8)
    elif args.gap is not None:
        res = a8_to_a0_feedback(engine, {
            "stage_id": "A8",
            "hypothesis_score": 0.9,
            "practice_score": round(max(0.0, 0.9 - args.gap), 4),
            "gap_score": args.gap,
            "trace_id": "CLI-TEST",
        })
    elif args.consistency is not None:
        res = a8_to_a0_feedback(engine, {
            "subsystem": "cli-test",
            "summary": {"consistency_score": args.consistency, "doc_only": 1, "code_only": 2},
            "doc_only_functions": ["f1"],
            "code_only_functions": ["f2", "f3"],
        })
    else:
        parser.print_help()
        sys.exit(0)

    print(json.dumps({
        "injected": res.injected,
        "dim_id": res.dim_id,
        "tension": res.tension,
        "gap_source": res.gap_source,
        "evidence": res.evidence,
        "message": res.message,
        "external_pool_size": len(engine._external_contradictions),
    }, ensure_ascii=False, indent=2))
