"""anomaly_probe.py — E1 真实异常信号探测器（shadow 期喂总线的信号源）。

初版信号源：mcp_shells/_shared/assets/domain_transmission_static.json 的
drift_coupling 值集合——同 regime 内任一域对 coupling 偏离集合 3σ 即上报。
（PSI 突刺探测待 46/4-MEMORY drift_detector 历史序列接口稳定后接入。）

FAIL-OPEN：数据源缺失/无异常 → 返回空表，不抛出。
"""

from __future__ import annotations

import json
import logging
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TRANSMISSION = (
    _REPO_ROOT / "mcp_shells" / "_shared" / "assets" / "domain_transmission_static.json"
)


def probe_coupling(
    transmission_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """扫描 coupling 矩阵，返回超 3σ 的异常信号列表（report_anomaly 入参形状）。"""
    path = Path(transmission_path) if transmission_path else DEFAULT_TRANSMISSION
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        coupling = data["domain_transmission"]["drift_coupling"]
        values = [(pair, float(v["coupling"])) for pair, v in coupling.items()]
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("coupling 矩阵读取失败: %s", exc)
        return []
    if len(values) < 3:
        return []
    nums = [v for _, v in values]
    mean = statistics.fmean(nums)
    std = statistics.pstdev(nums)
    if std == 0:
        return []
    signals = []
    for pair, val in values:
        z = (val - mean) / std
        if abs(z) >= 3.0:
            src, _, tgt = pair.partition("↔")
            signals.append(
                {
                    "source_domain": src.strip() or "unknown",
                    "metric": "coupling",
                    "value": val,
                    "baseline_mean": mean,
                    "baseline_std": std,
                    "detail": {"pair": pair, "target_domain": tgt.strip()},
                }
            )
    return signals


def run_probe(bus: Any, transmission_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """探测并上报到 EmergenceBus，返回实际点燃的 envelope 列表。"""
    fired = []
    for sig in probe_coupling(transmission_path):
        env = bus.report_anomaly(**sig)
        if env is not None:
            fired.append(env)
    return fired
