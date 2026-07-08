"""QMM 单入口：run_qmm() + run_qmm_with_gate()。"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .data_prep import prepare_events
from .gate import GateResult, GateRunner
from .mrd import compute_mrd
from .paths import qmm_dir
from .triple_screen import ScreenConfig, compute_triple_screen
from .trend_velocity import compute_trend_velocity
from .types import MDRResult, QMMOutput
from .uncertainty import compute_uncertainty


def run_qmm(
    cases: List[Dict[str, Any]],
    distills: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> QMMOutput:
    """QMM 离线内核入口。

    执行流程:
    1. 数据准备
    2. 三屏对齐
    3. 阻力方向
    4. 趋势速度 + 变化点
    5. 不确定性
    6. 输出 + 写入文件
    """
    # 版本三元组
    from .data_prep import _compute_data_version

    data_version = _compute_data_version(cases)
    feature_def_version = "fd-1.0"
    qmm_version = "qmm-v1.0"

    # Step 1: 数据准备
    events = prepare_events(cases, distills)

    # 失败语义检查
    if len(events) < 3:
        output = QMMOutput(
            trend_state="UNKNOWN",
            trend_change_point="STABLE",
            mrd_vector={
                "direction": "NEUTRAL", "resistance_up": 50,
                "resistance_down": 50, "confidence": 0,
            },
            uncertainty=1.0,
            reason_codes=["INSUFFICIENT_DATA"],
            evidence_refs=[e.event_id for e in events],
            data_version=data_version,
            feature_def_version=feature_def_version,
            qmm_version=qmm_version,
        )
        _save_output(output, qmm_dir(), gate_status="OFFLINE")
        return output

    # Step 2: 三屏对齐
    screen_config = ScreenConfig(**config) if config else ScreenConfig()
    ts_result = compute_triple_screen(events, screen_config)

    # Step 3: 阻力方向
    mrd_result = compute_mrd(events)

    # Step 4: 趋势速度
    vel_result = compute_trend_velocity(events)

    # Step 5: 不确定性
    unc = compute_uncertainty(
        ts_result, mrd_result, vel_result["velocity"], len(events),
    )

    # Step 6: 构建输出
    output = QMMOutput(
        snapshot_ts=datetime.now().astimezone().isoformat(timespec="seconds"),
        data_version=data_version,
        feature_def_version=feature_def_version,
        qmm_version=qmm_version,
        trend_state=ts_result["trend_state"],
        trend_change_point=vel_result["change_point"],
        mrd_vector={
            "direction": mrd_result.direction,
            "resistance_up": mrd_result.resistance_up,
            "resistance_down": mrd_result.resistance_down,
            "confidence": mrd_result.confidence,
        },
        uncertainty=unc,
        triple_screen={
            "long": _screen_to_dict(ts_result["long"]),
            "mid": _screen_to_dict(ts_result["mid"]),
            "short": _screen_to_dict(ts_result["short"]),
            "alignment": ts_result["alignment"],
        },
        velocity=vel_result["velocity"],
        acceleration=vel_result["acceleration"],
        reason_codes=_build_reason_codes(ts_result, mrd_result, vel_result),
        evidence_refs=[e.event_id for e in events[-10:]],
    )

    # Step 7: 写入输出
    _save_output(output, qmm_dir(), gate_status="OFFLINE")

    return output


def run_qmm_with_gate(
    cases: List[Dict[str, Any]],
    distills: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
    gate_config: Optional[Dict[str, Any]] = None,
) -> tuple:
    """QMM 内核 + 门禁联合入口。

    返回: (QMMOutput, GateResult)
    门禁不通过时，gate_status 标记为 FAILED。
    """
    # 先运行 QMM 内核
    output = run_qmm(cases, distills, config)

    # 从 cases 重新获取 events 用于回测
    events = prepare_events(cases, distills)

    # 门禁需要足够数据
    if len(events) < 15:
        gate_result = GateResult(
            backtest=None,  # type: ignore[arg-type]
            overfitting=None,  # type: ignore[arg-type]
            drift=None,  # type: ignore[arg-type]
            passed=False,
            reason_codes=["INSUFFICIENT_DATA_FOR_GATE"],
        )
        _update_gate_status(qmm_dir(), gate_result)
        return output, gate_result

    # 执行门禁
    gc = gate_config or {}
    use_xgb = gc.get("xgb_mode", True)  # 默认使用 XGBoost
    runner = GateRunner(
        n_folds=gc.get("n_folds", 3),
        min_train=gc.get("min_train", 80),
        min_test=gc.get("min_test", 5),
        xgb_mode=use_xgb,
        raw_cases=cases if use_xgb else None,
    )
    gate_result = runner.run(events)
    runner.save_gate_result(gate_result)

    # 更新 QMM 快照中的 gate_status
    _update_gate_status(qmm_dir(), gate_result)

    return output, gate_result


def _screen_to_dict(sr) -> Dict[str, Any]:
    from .types import ScreenResult
    if isinstance(sr, ScreenResult):
        return {
            "timeframe": sr.timeframe,
            "direction": sr.direction,
            "confidence": sr.confidence,
            "x_mean": sr.x_mean,
            "y_mean": sr.y_mean,
            "profit_rate": sr.profit_rate,
            "case_count": sr.case_count,
        }
    return sr


def _build_reason_codes(
    ts_result: Dict, mrd_result: MDRResult, vel_result: Dict,
) -> List[str]:
    """构建英文大写原因代码。"""
    codes: List[str] = []

    alignment = ts_result.get("alignment", 0)
    if alignment > 0.5:
        codes.append("BULLISH_ALIGNMENT")
    elif alignment < 0:
        codes.append("DIVERGENCE")

    if mrd_result.direction == "UP":
        codes.append("MRD_BULLISH")
    elif mrd_result.direction == "DOWN":
        codes.append("MRD_BEARISH")

    cp = vel_result.get("change_point", "STABLE")
    if cp == "ACCELERATING":
        codes.append("ACCELERATING")
    elif cp == "REVERSING":
        codes.append("REVERSING")

    if not codes:
        codes.append("NEUTRAL")

    return codes


def _save_output(
    output: QMMOutput, out_dir: Path, gate_status: str = "OFFLINE",
) -> None:
    """写入 QMM 快照和信号索引。"""
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = output.snapshot_ts.replace(":", "-") if output.snapshot_ts else "unknown"
    snapshot_path = out_dir / f"qmm_snapshot_{ts}.json"

    data = _to_dict(output)
    data["gate_status"] = gate_status
    snapshot_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # signals_index.json — 最新信号索引
    index_path = out_dir / "signals_index.json"
    index_data = {
        "version": output.version,
        "snapshot_ts": output.snapshot_ts,
        "data_version": output.data_version,
        "feature_def_version": output.feature_def_version,
        "qmm_version": output.qmm_version,
        "trend_state": output.trend_state,
        "trend_change_point": output.trend_change_point,
        "uncertainty": output.uncertainty,
        "reason_codes": output.reason_codes,
        "evidence_refs": output.evidence_refs,
        "gate_status": gate_status,
        "output_file": str(snapshot_path),
    }
    index_path.write_text(
        json.dumps(index_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _update_gate_status(out_dir: Path, gate_result: "GateResult") -> None:
    """更新 signals_index.json 中的 gate_status。"""
    index_path = out_dir / "signals_index.json"
    if not index_path.exists():
        return

    data = json.loads(index_path.read_text(encoding="utf-8"))
    gate_status = "PASSED" if gate_result.passed else "FAILED"
    gate_results = gate_result.to_dict()
    data["gate_status"] = gate_status
    data["gate_results"] = gate_results

    index_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    output_file = data.get("output_file")
    if isinstance(output_file, str) and output_file:
        snapshot_path = Path(output_file)
        if snapshot_path.exists():
            snapshot_data = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshot_data["gate_status"] = gate_status
            snapshot_data["gate_results"] = gate_results
            snapshot_path.write_text(
                json.dumps(snapshot_data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )


def _to_dict(obj: Any) -> Dict[str, Any]:
    """dataclass 转 dict。"""
    if hasattr(obj, "__dataclass_fields__"):
        result = {}
        for field in obj.__dataclass_fields__:
            val = getattr(obj, field)
            result[field] = _to_dict(val)
        return result
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_dict(x) for x in obj]
    return obj
