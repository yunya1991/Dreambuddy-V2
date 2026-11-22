"""40→23 周期上下文 trace 契约测试（2026-11-23）。

覆盖：
- adapter 对有效/过期/缺失 cycle_state 的 fail-open 行为；
- data_pipeline 注入点保留 [CycleContext] trace（监控依赖该关键字）。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _load():
    from dreambuddy_evolution.adapters.macro_constraint_adapter import load_macro_constraint

    return load_macro_constraint


def _write_cycle_state(tmp_path: Path, hours_ago: float) -> Path:
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    p = tmp_path / "cycle_state.json"
    p.write_text(
        json.dumps(
            {
                "generated_at": ts,
                "real_cycle": {"state": "expansion"},
                "sector_transmission": {"state": "neutral"},
                "technical_anchor": {"assets": {"BTC/USDT": {"above": True}}},
            }
        ),
        encoding="utf-8",
    )
    return p


def test_cycle_state_available_when_fresh(tmp_path):
    p = _write_cycle_state(tmp_path, 1.0)
    out = _load()(str(p))
    assert out["available"] is True
    assert out["stale"] is False
    assert out["real_cycle_state"] == "expansion"
    assert out["technical_anchor_btc_above"] is True
    assert out["age_hours"] == 1.0


def test_cycle_state_stale_after_72h(tmp_path):
    p = _write_cycle_state(tmp_path, 80.0)
    out = _load()(str(p))
    assert out["available"] is False
    assert out["stale"] is True


def test_cycle_state_missing_fail_open(tmp_path):
    out = _load()(str(tmp_path / "nope.json"))
    assert out["available"] is False


def test_pipeline_keeps_cycle_context_trace():
    """注入点必须保留 [CycleContext] 日志，监控/告警按该关键字采集。"""
    src = (Path(__file__).resolve().parents[1] / "adapters" / "data_pipeline.py").read_text(
        encoding="utf-8"
    )
    assert "[CycleContext]" in src
    assert "load_macro_constraint()" in src
