"""A0-A9 数据桥接模块。

将 A0-A9 各阶段产出收集、转换并填充到 TradeCase 的 thinking_chain 中。
同时为 A0-A9 各阶段提供 L1 记忆检索接口。

v0.2 新增模块 — Phase 1 (P0)
"""

import json
from datetime import datetime
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.memory_l4.paths import memory_l4_cases_dir, workspace_root

# ── A0-A9 阶段到 thinking_stage 的字段映射 ──

STAGE_FIELD_MAP: Dict[str, Dict[str, str]] = {
    "A0": {
        "decision": "contradiction_identified",
        "contradiction": "core_contradiction",
        "contradiction_analysis": "analysis",
        "evidence_refs": "evidence_refs",
    },
    "A1": {
        "decision": "research_conclusion",
        "rationale": "methodology",
        "evidence_refs": "sources",
    },
    "A2": {
        "decision": "first_principles",
        "rationale": "reasoning",
        "evidence_refs": "references",
    },
    "A3": {
        "decision": "simulation_result",
        "hypothesis": "hypothesis",
        "test_result": "backtest_result",
        "evidence_refs": "data_refs",
    },
    "A4": {
        "decision": "validation_result",
        "hypothesis": "assumption",
        "test_result": "test_outcome",
        "evidence_refs": "validation_refs",
    },
    "A5": {
        "decision": "execution_decision",
        "rationale": "execution_logic",
        "evidence_refs": "order_refs",
    },
    "A6": {
        "decision": "signal_decision",
        "rationale": "signal_rationale",
        "evidence_refs": "metric_refs",
    },
    "A7": {
        "decision": "practice_audit_result",
        "contradiction_analysis": "practice_theory_gap",
        "evidence_refs": "audit_refs",
    },
    "A8": {
        "decision": "verification_result",
        "contradiction_analysis": "theory_critique",
        "test_result": "verification_outcome",
        "evidence_refs": "verification_refs",
    },
    "A9": {
        "decision": "exit_decision",
        "exit_logic": "exit_reasoning",
        "evidence_refs": "exit_refs",
    },
}

STAGES = ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9"]


def collect_stage_outputs(trace_id: str) -> Dict[str, Dict[str, Any]]:
    """从 artifacts/trading/ 收 A0-A9 各阶段产出。

    Args:
        trace_id: 交易追踪标识，对应 artifacts/trading/ 下的子目录或文件前缀

    Returns:
        {stage_id: stage_data} 字典，仅包含存在数据的阶段
    """
    trading_dir = workspace_root() / "artifacts" / "trading"
    outputs: Dict[str, Dict[str, Any]] = {}

    if not trading_dir.exists():
        return outputs

    for stage in STAGES:
        # 查找匹配 trace_id + stage 的 JSON 文件
        for path in trading_dir.rglob(f"*{trace_id}*{stage}*.json"):
            if path.is_file():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    outputs[stage] = {
                        "stage_id": stage,
                        "raw": data,
                        "source_path": str(path),
                        "ts": str(data.get("timestamp") or datetime.now().astimezone().isoformat()),
                    }
                    break  # 每个阶段只取第一个匹配
                except Exception:
                    continue

    return outputs


def build_thinking_stage(stage_id: str, stage_data: Dict[str, Any]) -> Dict[str, Any]:
    """将单个阶段产出转换为 thinking_chain 格式。

    Args:
        stage_id: "A0" ~ "A9"
        stage_data: collect_stage_outputs 返回的阶段数据

    Returns:
        thinking_stage 字典
    """
    field_map = STAGE_FIELD_MAP.get(stage_id, {})
    raw = stage_data.get("raw", {})

    thinking_stage: Dict[str, Any] = {
        "stage": stage_id,
        "ts": stage_data.get("ts"),
        "decision": str(raw.get(field_map.get("decision", "decision"), "")),
        "rationale": None,
        "contradiction": None,
        "contradiction_analysis": None,
        "hypothesis": None,
        "test_result": None,
        "exit_logic": None,
        "evidence_refs": [],
        "stage_output_ref": stage_data.get("source_path"),
    }

    # 填充阶段特有字段
    if "rationale" in field_map:
        thinking_stage["rationale"] = str(raw.get(field_map["rationale"], ""))
    if "contradiction" in field_map:
        thinking_stage["contradiction"] = str(raw.get(field_map["contradiction"], ""))
    if "contradiction_analysis" in field_map:
        thinking_stage["contradiction_analysis"] = str(raw.get(field_map["contradiction_analysis"], ""))
    if "hypothesis" in field_map:
        thinking_stage["hypothesis"] = str(raw.get(field_map["hypothesis"], ""))
    if "test_result" in field_map:
        thinking_stage["test_result"] = str(raw.get(field_map["test_result"], ""))
    if "exit_logic" in field_map:
        thinking_stage["exit_logic"] = str(raw.get(field_map["exit_logic"], ""))

    return thinking_stage


def build_thinking_chain_from_stages(stage_outputs: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """将多个阶段产出转换为完整的 thinking_chain。

    Args:
        stage_outputs: collect_stage_outputs 的返回值

    Returns:
        thinking_chain 数组，按 A0-A9 顺序排列
    """
    chain: List[Dict[str, Any]] = []
    for stage in STAGES:
        if stage in stage_outputs:
            chain.append(build_thinking_stage(stage, stage_outputs[stage]))
    return chain


def enrich_case_with_stages(
    case_id: str,
    stage_outputs: Dict[str, Dict[str, Any]],
    out_path: Optional[Path] = None,
    episode: Optional[Dict[str, Any]] = None,
) -> Path:
    """将 A0-A9 阶段数据填充到已存在的 TradeCase。

    Args:
        case_id: TradeCase 标识
        stage_outputs: collect_stage_outputs 的返回值
        out_path: 输出路径，默认写入 cases 目录
        episode: 可选，episode 原始数据，用于提取 decision_outcome

    Returns:
        写入的文件路径
    """
    case_path = memory_l4_cases_dir() / f"{case_id}.json"
    if not case_path.exists():
        raise FileNotFoundError(f"TradeCase not found: {case_path}")

    case = json.loads(case_path.read_text(encoding="utf-8"))

    new_chain = build_thinking_chain_from_stages(stage_outputs)
    existing_chain = case.get("thinking_chain") or []

    # 合并: 保留已有阶段，追加新阶段
    existing_stages = {s.get("stage") for s in existing_chain if s.get("stage")}
    for stage in new_chain:
        if stage["stage"] not in existing_stages:
            existing_chain.append(stage)

    case["thinking_chain"] = existing_chain

    # 升级版本标识
    if case.get("version") == "v0.1":
        case["version"] = "v0.2"

    # 初始化 L4 状态 (如果缺失)
    if not case.get("l4_status"):
        case["l4_status"] = "M0_CASE_REGISTERED"

    # 从 episode 提取 decision_outcome (如果缺失且有 episode 数据)
    if not case.get("decision_outcome") and episode:
        out_data = episode.get("outcome") or {}
        case["decision_outcome"] = {
            "pnl_pct": out_data.get("realized_pnl_pct") or out_data.get("unrealized_pnl_pct"),
            "pnl_usdt": out_data.get("realized_pnl_usdt") or out_data.get("unrealized_pnl_usdt"),
            "drawdown": out_data.get("max_drawdown"),
            "exit_reason": out_data.get("exit_reason") or out_data.get("stop_reason"),
            "goal_achieved": out_data.get("goal_achieved"),
        }

    target = out_path or case_path
    target.write_text(json.dumps(case, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def query_memory_for_stage(
    stage_id: str,
    context: Optional[Dict[str, Any]] = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """A0-A9 阶段调用 L1 检索历史参考。

    供 A0-A9 各阶段在运行时调用，从记忆中检索类似历史案例。

    Args:
        stage_id: 当前阶段 "A0" ~ "A9"
        context: 当前阶段的上下文 (regime, inst_id, contradiction 等)
        top_k: 返回数量

    Returns:
        历史参考案例列表，每个包含 case_id, thinking_stage, quadrant
    """
    cases_dir = memory_l4_cases_dir()
    if not cases_dir.exists():
        return []

    results: List[Dict[str, Any]] = []
    for case_path in sorted(cases_dir.glob("*.json")):
        try:
            case = json.loads(case_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        # 查找该 case 中是否有目标阶段
        thinking_chain = case.get("thinking_chain") or []
        target_stage = None
        for s in thinking_chain:
            if s.get("stage") == stage_id:
                target_stage = s
                break

        if target_stage is None:
            continue

        # 如果提供了 context，做简单过滤
        if context:
            regime = context.get("regime")
            case_regime = (case.get("environment_snapshot") or {}).get("regime")
            if regime and case_regime and regime != case_regime:
                continue

        results.append({
            "case_id": case.get("case_id"),
            "inst_id": case.get("inst_id"),
            "stage_data": target_stage,
            "quadrant": case.get("quadrant"),
            "review": case.get("review"),
        })

        if len(results) >= top_k * 2:  # 先多取，后续可按相似度排序
            break

    # 按象限 y 值排序（高置信度优先）
    results.sort(key=lambda r: (r.get("quadrant") or {}).get("y", 0), reverse=True)
    return results[:top_k]
