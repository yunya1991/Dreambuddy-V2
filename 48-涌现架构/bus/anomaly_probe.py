"""anomaly_probe.py — E1 真实异常信号探测器（shadow 期喂总线的信号源）。

信号源一：mcp_shells/_shared/assets/domain_transmission_static.json 的
drift_coupling 值集合——同 regime 内任一域对 coupling 偏离集合 3σ 即上报。
信号源二（PSI 突刺探测）：.workbuddy/l1_training/domain_discovery_training.jsonl
半年域状态时序——各域 PSI 按周分块求均值，最新块相对历史块 3σ 即上报。

FAIL-OPEN：数据源缺失/无异常 → 返回空表，不抛出。
"""

from __future__ import annotations

import json
import logging
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TRANSMISSION = (
    _REPO_ROOT / "mcp_shells" / "_shared" / "assets" / "domain_transmission_static.json"
)
DEFAULT_STATE_SERIES = _REPO_ROOT / ".workbuddy" / "l1_training" / "domain_discovery_training.jsonl"

PSI_DOMAINS = ("cognition", "rea", "search", "semantic", "data", "eval")
PSI_BLOCK_DAYS = 7  # 分块粒度：自然周
PSI_MIN_HISTORY_BLOCKS = 3  # 历史块下限（不足则跳过该域）
PSI_IGNITE_Z = 3.0  # 与总线 IGNITE_Z 一致


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


def probe_psi_spike(
    series_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """各域 PSI 按周分块求均值，最新块相对历史块 3σ 突刺检测。

    数据源：domain_discovery_training.jsonl（每行 input.domain_states.<域>.psi）。
    返回 report_anomaly 入参形状的信号列表；FAIL-OPEN：任何异常返回空表。
    """
    path = Path(series_path) if series_path else DEFAULT_STATE_SERIES
    try:
        blocks: Dict[str, Dict[int, List[float]]] = {}
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:  # noqa: BLE001 — 坏行跳过
                    continue
                ts = row.get("timestamp") or ""
                states = (row.get("input") or {}).get("domain_states") or {}
                if not ts:
                    continue
                try:
                    block_key = datetime.fromisoformat(ts).toordinal() // PSI_BLOCK_DAYS
                except (ValueError, TypeError):
                    continue
                for domain in PSI_DOMAINS:
                    psi = (states.get(domain) or {}).get("psi")
                    if psi is None:
                        continue
                    try:
                        blocks.setdefault(domain, {}).setdefault(block_key, []).append(float(psi))
                    except (TypeError, ValueError):
                        continue
        signals: List[Dict[str, Any]] = []
        for domain in PSI_DOMAINS:
            per_domain = blocks.get(domain) or {}
            keys = sorted(per_domain)
            if len(keys) < PSI_MIN_HISTORY_BLOCKS + 1:
                continue
            hist = [statistics.fmean(per_domain[k]) for k in keys[:-1]]
            latest = statistics.fmean(per_domain[keys[-1]])
            mean = statistics.fmean(hist)
            std = statistics.pstdev(hist)
            if std == 0:
                continue
            z = (latest - mean) / std
            if abs(z) >= PSI_IGNITE_Z:
                signals.append(
                    {
                        "source_domain": domain,
                        "metric": "psi_spike",
                        "value": latest,
                        "baseline_mean": mean,
                        "baseline_std": std,
                        "detail": {
                            "z_score": z,
                            "n_blocks": len(keys),
                            "block_days": PSI_BLOCK_DAYS,
                            "series_path": str(path),
                        },
                    }
                )
        return signals
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("PSI 突刺探测失败（FAIL-OPEN）: %s", exc)
        return []


def run_probe(
    bus: Any,
    transmission_path: Optional[Path] = None,
    series_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """探测（coupling 3σ + PSI 突刺）并上报到 EmergenceBus，返回实际点燃的 envelope 列表。"""
    fired = []
    signals = probe_coupling(transmission_path) + probe_psi_spike(series_path)
    for sig in signals:
        env = bus.report_anomaly(**sig)
        if env is not None:
            fired.append(env)
    return fired
