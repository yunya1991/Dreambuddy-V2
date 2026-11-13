# prior_reader.py - 50 域消费 40 域因子/矛盾先验（G4 下游消费点，fail-open）
# 读取 40 域 factor_contradiction_priors.json，输出决策可用的先验摘要；
# 文件缺失/解析失败时返回 None（fail-open，不中断 shadow 决策）。
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PRIORS_PATH = REPO_ROOT / "40-周期神经网络系统" / "factor_contradiction_priors.json"


def load_priors_summary(path: str | Path | None = None) -> Optional[dict[str, Any]]:
    target = Path(path) if path else DEFAULT_PRIORS_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("40 先验产物缺失（跳过）: %s", target)
        return None
    except Exception as exc:  # noqa: BLE001 - FAIL-OPEN
        logger.warning("40 先验产物读取失败（降级）: %s %s", target, exc)
        return None

    direction_priors = data.get("factor_direction_priors") or {}
    factors = direction_priors.get("factors") if isinstance(direction_priors, dict) else None
    if not isinstance(factors, dict):
        factors = {}
    top = sorted(
        (
            {
                "factor": name,
                "dominant_direction": cfg.get("dominant_direction"),
                "total_weight": cfg.get("total_weight"),
            }
            for name, cfg in factors.items()
            if isinstance(cfg, dict)
        ),
        key=lambda x: -(x["total_weight"] or 0.0),
    )[:5]

    contradiction = data.get("contradiction_priors") or {}
    return {
        "source": "40/factor_contradiction_priors.json",
        "schema_version": data.get("schema_version"),
        "generated_at": data.get("generated_at"),
        "n_factor_priors": len(factors),
        "top_factors": top,
        "contradiction_n_events": contradiction.get("n_events"),
        "contradiction_by_type": contradiction.get("by_contradiction_type"),
    }
