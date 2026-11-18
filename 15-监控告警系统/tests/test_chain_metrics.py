"""chain_metrics：N11 主动拦截不应被计为断链。"""

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


def test_blocked_chain_excluded_from_completion(tmp_path: Path) -> None:
    runtime = tmp_path / "23-四层闭环自进化交易架构/runtime"
    runtime.mkdir(parents=True)
    ts = _now_iso()

    def ev(stage: str, chain: str, status: str = "pass", data: dict | None = None) -> dict:
        return {
            "ts": ts,
            "stage": stage,
            "status": status,
            "chain_id": chain,
            "trace_id": f"trace-{chain}",
            "data": data or {},
        }

    rows = [
        # 完整链路
        ev("N10", "dec-full"),
        ev("N11", "dec-full"),
        ev("N12", "dec-full"),
        ev("N14", "dec-full"),
        # 已有持仓被 N11 主动拦截：不是断链
        ev("N10", "dec-blocked"),
        ev("N11", "dec-blocked", "blocked", {"gate": "duplicate_position"}),
    ]
    (runtime / "chain_events-20261118.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )

    collector = Collector(tmp_path, BASE / "config/monitoring.yaml", BASE / "config/domains.yaml")
    text = "\n".join(collector.chain_metrics())

    assert "dreambuddy_chain_completion_ratio 1.0" in text
    assert 'dreambuddy_chain_missing_stage_total{stage="N12"} 0' in text
    assert 'dreambuddy_chain_missing_stage_total{stage="N14"} 0' in text
    assert 'dreambuddy_chain_blocked_total{gate="duplicate_position"} 1' in text
