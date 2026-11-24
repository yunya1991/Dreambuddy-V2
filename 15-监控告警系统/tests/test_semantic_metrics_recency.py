"""semantic_metrics：陈旧决策不得继续参与当前态 cv 指标（防告警永不恢复）。"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from exporter.business_metrics_exporter import Collector  # noqa: E402


def _iso(delta_hours: float = 0.0) -> str:
    ts = datetime.now(timezone.utc) - timedelta(hours=delta_hours)
    return ts.isoformat().replace("+00:00", "Z")


def _rec(symbol: str, mode: str | None, age_hours: float) -> dict:
    cv = {"confidence_mult": 1.0, "shift_signal": False, "divergence_count": 0}
    if mode:
        cv["degraded_mode"] = mode
    return {
        "ts": _iso(age_hours),
        "signal": {
            "ts": _iso(age_hours),
            "symbol": symbol,
            "payload": {
                "primary_contradiction": {"dimension": "technical", "strength": 0.6},
                "cross_validation": cv,
            },
        },
    }


def test_stale_decision_excluded_from_state_metrics(tmp_path: Path) -> None:
    runtime = tmp_path / "23-四层闭环自进化交易架构/runtime"
    runtime.mkdir(parents=True)
    rows = [
        _rec("STALE-USDT-SWAP", "both_none", 13.0),  # 超过 12h 时效窗口
        _rec("FRESH-USDT-SWAP", "attention_only", 0.1),
    ]
    (runtime / "execution_decisions.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )

    collector = Collector(tmp_path, BASE / "config/monitoring.yaml", BASE / "config/domains.yaml")
    text = "\n".join(collector.semantic_metrics())

    assert 'dreambuddy_cv_degraded_mode{symbol="STALE-USDT-SWAP",mode="both_none"}' not in text
    assert 'dreambuddy_cv_degraded_mode{symbol="FRESH-USDT-SWAP",mode="attention_only"} 1' in text
    assert "dreambuddy_cv_degraded 1" in text
    assert "dreambuddy_cv_present_ratio 1.0" in text


def test_all_stale_keeps_last_known_values_out(tmp_path: Path) -> None:
    runtime = tmp_path / "23-四层闭环自进化交易架构/runtime"
    runtime.mkdir(parents=True)
    rows = [_rec("OLD-USDT-SWAP", "both_none", 30.0)]
    (runtime / "execution_decisions.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )

    collector = Collector(tmp_path, BASE / "config/monitoring.yaml", BASE / "config/domains.yaml")
    text = "\n".join(collector.semantic_metrics())

    assert "dreambuddy_cv_degraded_mode" not in text
    assert "dreambuddy_cv_present_ratio" not in text
