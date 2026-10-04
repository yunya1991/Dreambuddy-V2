"""C0-C8 流水线状态跟踪。

追踪策略从创建到部署的完整生命周期：
  C0 env_scan   - 环境扫描
  C1 universe   - 品种筛选
  C2 signals    - 信号生成
  C3 backtest   - 回测验证
  C4 risk       - 风险评估
  C5 optimize   - 参数优化
  C6 plan       - 计划生成
  C7 monitor    - 监控部署
  C8 attribution - 归因分析

状态流转：pending → running → passed/failed/skipped
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# 27 模块数据根目录
_PIPELINE_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "pipeline"
_PIPELINE_DATA_DIR.mkdir(parents=True, exist_ok=True)

# C0-C8 阶段定义
PIPELINE_STAGES = [
    "C0_env_scan",
    "C1_universe",
    "C2_signals",
    "C3_backtest",
    "C4_risk",
    "C5_optimize",
    "C6_plan",
    "C7_monitor",
    "C8_attribution",
]

VALID_STATES = {"pending", "running", "passed", "failed", "skipped"}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _pipeline_state_path() -> Path:
    return _PIPELINE_DATA_DIR / "pipeline_states.jsonl"


def _pipeline_create_state(
    trace_id: str,
    strategy_id: str = "",
    source_zip: str = "",
) -> Dict[str, Any]:
    """创建新的流水线状态记录。"""
    now = _now_ms()
    stages: Dict[str, Any] = {}
    for s in PIPELINE_STAGES:
        stages[s] = {
            "state": "pending",
            "started_at": None,
            "finished_at": None,
            "result": {},
            "error": None,
        }
    return {
        "trace_id": str(trace_id),
        "strategy_id": str(strategy_id or "").strip(),
        "source_zip": str(source_zip or "").strip(),
        "created_at": now,
        "updated_at": now,
        "current_stage": None,
        "stages": stages,
        "overall_state": "pending",
    }


def _pipeline_save(state: Dict[str, Any]) -> bool:
    """保存流水线状态（追加式 JSONL）。"""
    try:
        p = _pipeline_state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        # 更新时间戳
        state["updated_at"] = _now_ms()
        # 查找并替换已有记录，或追加新记录
        tid = str(state.get("trace_id") or "").strip()
        if not tid:
            return False
        entries: List[str] = []
        replaced = False
        if p.exists():
            for ln in p.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    obj = json.loads(ln)
                    if isinstance(obj, dict) and str(obj.get("trace_id") or "") == tid:
                        entries.append(json.dumps(state, ensure_ascii=False))
                        replaced = True
                    else:
                        entries.append(ln)
                except Exception:
                    entries.append(ln)
        if not replaced:
            entries.append(json.dumps(state, ensure_ascii=False))
        p.write_text("\n".join(entries) + "\n", encoding="utf-8")
        return True
    except Exception:
        return False


def _pipeline_load(trace_id: str) -> Optional[Dict[str, Any]]:
    """加载流水线状态。"""
    tid = str(trace_id or "").strip()
    if not tid:
        return None
    p = _pipeline_state_path()
    if not p.exists():
        return None
    for ln in reversed(p.read_text(encoding="utf-8").splitlines()):
        ln = ln.strip()
        if not ln:
            continue
        try:
            obj = json.loads(ln)
            if isinstance(obj, dict) and str(obj.get("trace_id") or "") == tid:
                return obj
        except Exception:
            continue
    return None


def _pipeline_update_stage(
    trace_id: str,
    stage: str,
    state: str,
    *,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """更新流水线中某个阶段的状态。"""
    if stage not in PIPELINE_STAGES:
        return None
    if state not in VALID_STATES:
        return None

    pipeline = _pipeline_load(trace_id)
    if pipeline is None:
        pipeline = _pipeline_create_state(trace_id)

    now = _now_ms()
    stages = pipeline.get("stages", {})
    if stage not in stages:
        stages[stage] = {
            "state": "pending",
            "started_at": None,
            "finished_at": None,
            "result": {},
            "error": None,
        }

    stages[stage]["state"] = state
    if state == "running":
        stages[stage]["started_at"] = now
    elif state in ("passed", "failed", "skipped"):
        stages[stage]["finished_at"] = now
    if result is not None:
        stages[stage]["result"] = result
    if error is not None:
        stages[stage]["error"] = error

    pipeline["stages"] = stages

    # 更新 current_stage 和 overall_state
    if state == "running":
        pipeline["current_stage"] = stage
    elif state in ("passed", "skipped"):
        # 找下一个 pending 阶段
        idx = PIPELINE_STAGES.index(stage)
        next_stage = None
        for s in PIPELINE_STAGES[idx + 1:]:
            if stages.get(s, {}).get("state") == "pending":
                next_stage = s
                break
        pipeline["current_stage"] = next_stage
    elif state == "failed":
        pipeline["current_stage"] = stage

    # 计算 overall_state
    all_states = [stages.get(s, {}).get("state", "pending") for s in PIPELINE_STAGES]
    if any(s == "failed" for s in all_states):
        pipeline["overall_state"] = "failed"
    elif all(s in ("passed", "skipped") for s in all_states):
        pipeline["overall_state"] = "completed"
    elif any(s == "running" for s in all_states):
        pipeline["overall_state"] = "running"
    elif all(s == "pending" for s in all_states):
        pipeline["overall_state"] = "pending"
    else:
        pipeline["overall_state"] = "running"

    _pipeline_save(pipeline)
    return pipeline


def _pipeline_list(
    *,
    strategy_id: Optional[str] = None,
    overall_state: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """列出流水线状态记录。"""
    p = _pipeline_state_path()
    if not p.exists():
        return []
    sid = str(strategy_id or "").strip() if strategy_id else None
    os = str(overall_state or "").strip().lower() if overall_state else None
    out: List[Dict[str, Any]] = []
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
        for ln in reversed(lines):
            ln = ln.strip()
            if not ln:
                continue
            try:
                obj = json.loads(ln)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            if sid and str(obj.get("strategy_id") or "") != sid:
                continue
            if os and str(obj.get("overall_state") or "").lower() != os:
                continue
            out.append(obj)
            if len(out) >= int(limit):
                break
    except Exception:
        pass
    out.reverse()
    return out


__all__ = [
    "PIPELINE_STAGES",
    "VALID_STATES",
    "_pipeline_create_state",
    "_pipeline_save",
    "_pipeline_load",
    "_pipeline_update_stage",
    "_pipeline_list",
]
