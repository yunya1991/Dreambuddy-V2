#!/usr/bin/env python3
"""被动训练触发入口 — 收尾 SKILL Step 5.5 调用。

从 JSON 文件读取收尾案例数据，调用编排器触发被动训练，
输出辅导上下文和认知 record 参数供 Trae 使用。

遵循 33-REA cognitive_integration 模式：
  Python 脚本准备 record 参数，不直接调 MCP，由 Trae(Agent) 执行 record 调用。

用法:
  python trigger_passive_training.py --case-data case.json
  python trigger_passive_training.py --case-data case.json --frontend-url http://localhost:3001
  python trigger_passive_training.py --case-data case.json --no-rea
"""
import argparse
import json
import os
import sys
import traceback
from typing import Any, Dict, Optional

# sys.path 注入
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_CORE_DIR = os.path.join(_THIS_DIR, "core")
for _p in [_THIS_DIR, _CORE_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _prepare_record_params(wrapup_case: dict, result: dict) -> Optional[Dict[str, Any]]:
    """准备认知记忆 record 参数。

    遵循 33-REA cognitive_integration.prepare_record_params 模式，
    返回 content/quality_level/tags，由 Trae 调用 mcp_cognitive.record。

    Args:
        wrapup_case: 收尾案例数据
        result: 编排器 trigger_passive_training() 返回结果

    Returns:
        record 参数 dict，或 None（若非 INGEST）
    """
    if result.get("status") != "coaching_started":
        return None

    evaluation = result.get("evaluation", {})
    coaching_ctx = result.get("coaching_context", {})

    domain_tag = wrapup_case.get("domain_tag", "前端训练")
    intent = wrapup_case.get("intent", "")
    outcome = wrapup_case.get("outcome", "unknown")
    acceptance_level = wrapup_case.get("acceptance_level", "")
    decision = evaluation.get("decision", "ingest")
    # 处理 Enum 值（IngestDecision.INGEST → "ingest"）
    if hasattr(decision, "value"):
        decision = decision.value

    content_lines = [
        f"[被动训练] {intent}",
        f"决策: {decision}",
        f"验收等级: {acceptance_level}",
        f"结果: {outcome}",
        f"算法模式: {len(coaching_ctx.get('algorithm_patterns', []))} 个",
        f"调用链: {len(coaching_ctx.get('call_chain', []))} 步",
        f"已知局限: {len(coaching_ctx.get('known_gaps', []))} 项",
    ]
    content = " | ".join(content_lines)

    tags = (
        f"wrapup,收尾,认知闭环,完成闭环,{domain_tag},"
        f"hermes反思,被动训练,在线辅导"
    )

    return {
        "content": content,
        "quality_level": "B",
        "tags": tags,
    }


def run_trigger(
    case_data_path: str,
    frontend_url: Optional[str] = None,
    enable_rea: bool = True,
) -> Dict[str, Any]:
    """执行被动训练触发。

    Args:
        case_data_path: 收尾案例 JSON 文件路径
        frontend_url: 前端服务地址（可选）
        enable_rea: 是否启用 33-REA 解析

    Returns:
        输出结果 dict（status + evaluation + coaching_context + monitoring_checklist + record_params）
    """
    # 1. 读取案例数据
    with open(case_data_path, "r", encoding="utf-8") as f:
        wrapup_case = json.load(f)

    # 2. 创建编排器（FAIL-OPEN）
    try:
        from orchestrator_factory import create_orchestrator
        orchestrator = create_orchestrator(
            frontend_url=frontend_url,
            enable_rea=enable_rea,
        )
    except Exception as e:
        return {
            "status": "error",
            "error": f"orchestrator creation failed: {e}",
            "record_params": None,
        }

    # 3. 触发被动训练
    try:
        result = orchestrator.trigger_passive_training(wrapup_case)
    except Exception as e:
        return {
            "status": "error",
            "error": f"trigger_passive_training failed: {e}",
            "traceback": traceback.format_exc(),
            "record_params": None,
        }

    # 4. 若辅导启动：执行辅导循环 + 生成监控清单 + 准备 record 参数
    if result.get("status") == "coaching_started":
        from coaching_loop import CoachingSession
        session = CoachingSession(result.get("coaching_context", {}))
        # v0.2: 自动执行辅导循环（监控+纠正+评估）
        session.run_coaching_cycle()
        monitoring_checklist = session.get_monitoring_checklist()
        coaching_report = session.to_report()
        record_params = _prepare_record_params(wrapup_case, result)

        return {
            "status": "coaching_started",
            "evaluation": result.get("evaluation", {}),
            "coaching_context": result.get("coaching_context", {}),
            "monitoring_checklist": monitoring_checklist,
            "coaching_report": coaching_report,
            "record_params": record_params,
        }

    # 5. SKIP / DEFERRED 路径
    return {
        "status": result.get("status", "unknown"),
        "reason": result.get("reason", ""),
        "evaluation": result.get("evaluation", {}),
        "record_params": None,
    }


def main():
    parser = argparse.ArgumentParser(
        description="被动训练触发入口 — 收尾 SKILL Step 5.5 调用",
    )
    parser.add_argument(
        "--case-data",
        required=True,
        help="收尾案例 JSON 文件路径",
    )
    parser.add_argument(
        "--frontend-url",
        default=None,
        help="前端服务地址（默认 http://localhost:3001）",
    )
    parser.add_argument(
        "--no-rea",
        dest="enable_rea",
        action="store_false",
        default=True,
        help="禁用 33-REA 解析",
    )
    args = parser.parse_args()

    result = run_trigger(
        case_data_path=args.case_data,
        frontend_url=args.frontend_url,
        enable_rea=args.enable_rea,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    # exit code: 0=success(coaching or skip), 1=error
    sys.exit(0 if result.get("status") != "error" else 1)


if __name__ == "__main__":
    main()
