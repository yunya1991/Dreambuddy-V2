import json
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# #3-b 三层脑理论 A8→A0 反向反馈：
#   把 A8 检出的偏差写回 A0 矛盾池（a8_gap 第8维），使"新皮质分析"能感知"边缘系统评估"
_A0_ENGINE_CACHE: Dict[str, Any] = {}  # 全局单例缓存，避免每次新建导致 external 不累积


def _load_protocol_module():
    mod_path = Path(__file__).resolve().parents[1] / "protocol" / "message.py"
    spec = importlib.util.spec_from_file_location("trading_protocol_message", mod_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _get_a0_engine():
    """获取（或懒加载）全局 A0 引擎单例，使 external 矛盾池跨调用累积。"""
    if "engine" in _A0_ENGINE_CACHE:
        return _A0_ENGINE_CACHE["engine"]
    scripts_path = str(Path(__file__).resolve().parents[3] / "scripts")
    if scripts_path not in sys.path:
        sys.path.insert(0, scripts_path)
    try:
        from memory_l4.a0_contradiction_engine import A0ContradictionEngine
        _A0_ENGINE_CACHE["engine"] = A0ContradictionEngine()
    except Exception as _e:
        _A0_ENGINE_CACHE["error"] = str(_e)
        _A0_ENGINE_CACHE["engine"] = None
    return _A0_ENGINE_CACHE.get("engine")


def _feedback_to_a0(result_dict: Dict[str, Any]) -> Dict[str, Any]:
    """把 A8 结果写回 A0 矛盾池。静默失败——不影响 A8 主流程。"""
    info: Dict[str, Any] = {"injected": False}
    engine = _get_a0_engine()
    if engine is None:
        info["error"] = _A0_ENGINE_CACHE.get("error", "A0 engine unavailable")
        return info
    scripts_path = str(Path(__file__).resolve().parents[3] / "scripts")
    if scripts_path not in sys.path:
        sys.path.insert(0, scripts_path)
    try:
        from memory_l4.a8_a0_feedback import a8_to_a0_feedback
        fb = a8_to_a0_feedback(engine, result_dict, source="trading_a8")
        info = {
            "injected": fb.injected,
            "tension": fb.tension,
            "gap_source": fb.gap_source,
            "evidence": fb.evidence,
            "message": fb.message,
            "external_pool_size": len(getattr(engine, "_external_contradictions", [])),
        }
    except Exception as _e:
        info["error"] = f"a8_a0_feedback 异常: {_e}"
    return info


def run_a8_theory_practice(payload: Dict[str, Any], output_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Thin wrapper for A8 theory-practice verification output."""
    proto = _load_protocol_module()
    hypo = float(payload.get('hypothesis_score') or 0.0)
    prac = float(payload.get('practice_score') or 0.0)
    gap = abs(hypo - prac)

    ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    base = Path(output_dir) if output_dir is not None else Path('artifacts/trading')
    base.mkdir(parents=True, exist_ok=True)
    out_path = base / f'a8_theory_practice_{ts}.json'

    result = proto.ensure_contract_fields(
        {
        'stage_id': 'A8',
        'trace_id': payload.get('trace_id'),
        'hypothesis_score': hypo,
        'practice_score': prac,
        'gap_score': gap,
        'timestamp': ts,
        },
        producer="workflows/trading-decision/A8_theory-practice",
    )
    result['artifact_path'] = str(out_path)
    proto.require_contract_fields(result)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    # #3-b A8→A0 反向反馈：写入 a8_gap 第8维矛盾（静默失败）
    fb_info = _feedback_to_a0(result)
    result["a0_feedback"] = fb_info

    return proto.build_envelope(
        source="A8",
        target="A2",
        message_type="FEEDBACK",
        priority="MEDIUM",
        loop_type="governance",
        trace_id=result["trace_id"],
        correlation_id=payload.get("correlation_id"),
        timeout_ms=300000,
        payload=result,
    )
