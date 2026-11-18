"""signal_calibration_metrics：d_star 口径 / ri / ESS 方向 / 放量门槛 的导出测试。"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from exporter.business_metrics_exporter import Collector  # noqa: E402


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def test_signal_calibration_metrics(tmp_path: Path) -> None:
    runtime = tmp_path / "23-四层闭环自进化交易架构/runtime"
    runtime.mkdir(parents=True)
    ts = _now_iso()
    rows = [
        {
            "ts": ts,
            "stage": "N4",
            "symbol": "BTC-USDT-SWAP",
            "data": {
                "d_star_original": "neutral",
                "d_star_shadow": {
                    "d_star_calibrated": "long",
                    "wait_mode": "calibrated",
                    "wait_margin": 0.3,
                },
            },
        },
        {
            "ts": ts,
            "stage": "N4",
            "symbol": "ETH-USDT-SWAP",
            "data": {
                "d_star_original": "neutral",
                "d_star_shadow": {"d_star_calibrated": "WAIT", "wait_mode": "calibrated"},
            },
        },
        {
            "ts": ts,
            "stage": "N9",
            "symbol": "BTC-USDT-SWAP",
            "data": {
                "ri": 0.5,
                "tier": "probe",
                "ess_top_direction": "",
                "vol_threshold": 1.93,
                "reflection_ri": 0.5,
                "reflection_eligible": False,
            },
        },
        {
            "ts": ts,
            "stage": "N9",
            "symbol": "SOL-USDT-SWAP",
            "data": {
                "ri": 0.62,
                "tier": "standard",
                "ess_top_direction": "long",
                "vol_threshold": 2.61,
                "reflection_ri": 0.55,
                "reflection_eligible": True,
            },
        },
    ]
    (runtime / "chain_events-20261118.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )

    collector = Collector(tmp_path, BASE / "config/monitoring.yaml", BASE / "config/domains.yaml")
    text = "\n".join(collector.signal_calibration_metrics())

    assert "dreambuddy_dstar_calibrated_enabled 1" in text
    assert 'dreambuddy_dstar_wait_mode{mode="calibrated"} 1' in text
    assert "dreambuddy_dstar_calibrated_wait_1h 1" in text
    assert "dreambuddy_dstar_calibrated_trade_1h 1" in text
    assert "dreambuddy_dstar_calibrated_flip_1h 2" in text
    assert "dreambuddy_ri_neutral_1h 1" in text
    assert "dreambuddy_ess_direction_empty_1h 1" in text
    assert "dreambuddy_reflection_eligible_1h 1" in text
    assert "dreambuddy_reflection_ri_max 0.55" in text
    assert 'dreambuddy_ri_value{symbol="SOL"} 0.62' in text
    assert 'dreambuddy_ripple_vol_threshold{symbol="BTC"} 1.93' in text
