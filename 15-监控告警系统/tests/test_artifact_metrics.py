"""artifact_metrics：severity 标签透传 + chain_events 决策流新鲜度（替代 submit 审计判沉默）。"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from exporter.business_metrics_exporter import Collector  # noqa: E402


def _cfg(tmp_path: Path, *items: dict) -> Path:
    path = tmp_path / "monitoring.yaml"
    # JSON 是 YAML 子集，避免测试里拼 YAML 缩进
    path.write_text(json.dumps({"artifacts": list(items)}), encoding="utf-8")
    return path


def test_artifact_metric_carries_severity(tmp_path: Path) -> None:
    art = tmp_path / "x/state.json"
    art.parent.mkdir(parents=True)
    art.write_text("{}", encoding="utf-8")
    cfg = _cfg(
        tmp_path,
        {"name": "demo", "path": "x/state.json", "ttl_seconds": 60, "severity": "P2"},
    )

    text = "\n".join(Collector(tmp_path, cfg, BASE / "config/domains.yaml").artifact_metrics())

    assert 'dreambuddy_artifact_present{artifact="demo",severity="P2"} 1' in text
    assert 'dreambuddy_artifact_ttl_seconds{artifact="demo",severity="P2"} 60.0' in text


def test_decision_flow_age_follows_latest_chain_event(tmp_path: Path) -> None:
    runtime = tmp_path / "23-四层闭环自进化交易架构/runtime"
    runtime.mkdir(parents=True)
    now = datetime.now(timezone.utc)
    fresh = (now - timedelta(seconds=120)).isoformat()
    stale = (now - timedelta(hours=20)).isoformat()
    rows = [
        {"node": "pipeline.decision", "ts": stale, "status": "skip", "data": {"action": "WAIT"}},
        {"node": "pipeline.path_discovery", "ts": stale, "status": "pass"},
        {"node": "pipeline.decision", "ts": fresh, "status": "pass", "data": {"action": "WAIT"}},
    ]
    (runtime / "chain_events-20261125.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    cfg = _cfg(
        tmp_path,
        {
            "name": "decision_flow_23",
            "path": "23-四层闭环自进化交易架构/runtime/chain_events-*.jsonl",
            "chain_event_node": "pipeline.decision",
            "ttl_seconds": 1800,
            "severity": "P1",
        },
    )

    text = "\n".join(Collector(tmp_path, cfg, BASE / "config/domains.yaml").artifact_metrics())

    assert 'dreambuddy_artifact_present{artifact="decision_flow_23",severity="P1"} 1' in text
    age = float(
        next(
            line.split()[1]
            for line in text.splitlines()
            if line.startswith("dreambuddy_artifact_age_seconds")
        )
    )
    assert 60 < age < 300, f"应取最新决策 ts（≈120s），实际 {age}"


def test_decision_flow_missing_when_no_event(tmp_path: Path) -> None:
    cfg = _cfg(
        tmp_path,
        {
            "name": "decision_flow_23",
            "path": "23-四层闭环自进化交易架构/runtime/chain_events-*.jsonl",
            "chain_event_node": "pipeline.decision",
            "ttl_seconds": 1800,
            "severity": "P1",
        },
    )

    text = "\n".join(Collector(tmp_path, cfg, BASE / "config/domains.yaml").artifact_metrics())

    assert 'dreambuddy_artifact_present{artifact="decision_flow_23",severity="P1"} 0' in text
