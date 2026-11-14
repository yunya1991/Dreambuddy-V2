"""cycle_state_adapter：40 产出物承接字段口径。"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategic_extension.cycle_state_adapter import build_bridge_inputs  # noqa: E402


def _cs(records: int, confidence: str = "high"):
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_coverage": {"records": records},
        "real_cycle": {"state": "plateau", "confidence": confidence},
    }


def test_factor_coverage_uses_48_month_baseline():
    """云端仅 45 个月历史时，覆盖度应接近 1（原先 /800 会压到 0.056）。"""
    out = build_bridge_inputs(_cs(45), "crypto_usdt")
    assert out["factor_coverage_pct"] == 0.9375


def test_factor_coverage_full_history_capped():
    out = build_bridge_inputs(_cs(869), "crypto_usdt")
    assert out["factor_coverage_pct"] == 1.0
