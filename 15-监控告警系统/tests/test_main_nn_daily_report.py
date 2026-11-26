"""main-nn 每日复盘 / SLO / 误报台账测试（TD §14.7、§14.9 P3）。"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "scripts"))

import main_nn_daily_report as report_mod  # noqa: E402
from main_nn_daily_report import (  # noqa: E402
    build_report,
    load_ledger,
    mark_fp,
    render_fp_list,
    render_markdown,
)

_DAY = datetime.now(report_mod.CST).date()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )


def _event(stage: str, cid: str, status: str = "pass", reason: str = "") -> dict:
    rec = {
        "source": "main-nn",
        "stage": stage,
        "status": status,
        "trace_id": f"trace-{cid}",
        "ts": _now_iso(),
        "data": {},
    }
    if reason:
        rec["reason_category"] = reason
    return rec


def _fixture(repo: Path) -> None:
    _write_jsonl(
        repo / "50-NN主矛盾评估器/runtime" / f"chain_events-{_DAY.strftime('%Y%m%d')}.jsonl",
        [
            _event("M6", "a"),
            _event("M7", "a"),
            _event("M11", "a"),
            _event("M12", "a"),
            _event("M13", "a"),
            _event("M6", "b"),
            _event("M11", "b"),
            _event("M12", "b"),
            _event("M6", "c", status="skip", reason="wait_evidence_missing"),
            _event("M6", "d", status="skip"),
        ],
    )
    _write_jsonl(
        repo / "50-NN主矛盾评估器/runtime" / "decisions.jsonl",
        [
            {"ts": _now_iso(), "symbol": "BTC", "mode": "live", "decision_id": "d1"},
            {"ts": _now_iso(), "symbol": "ETH", "mode": "live", "decision_id": "d2"},
            {"ts": _now_iso(), "symbol": "SOL", "mode": "shadow", "decision_id": "d3"},
        ],
    )
    _write_jsonl(
        repo / "22-执行引擎中心/audit" / "x1_live_fills.jsonl",
        [
            {
                "ts": _now_iso(),
                "decision_id": "d1",
                "order_placed": True,
                "request": {"sl_pct": 1.5, "tp_pct": 3.0},
            },
            {
                "ts": _now_iso(),
                "decision_id": "d2",
                "order_placed": True,
                "request": {"sl_pct": 0, "tp_pct": 0},
            },
            {
                "ts": _now_iso(),
                "decision_id": "d9",
                "order_placed": True,
                "request": {"sl_pct": 2.0, "tp_pct": 4.0},
            },
        ],
    )
    _write_jsonl(
        repo / "50-NN主矛盾评估器/runtime/live" / "outbox.jsonl",
        [
            {
                "ts": _now_iso(),
                "mode": "live",
                "decision_id": "d1",
                "mandate_id": "mandate-x",
                "execution": {"outcome": "live:50-bypass"},
            },
            {
                "ts": _now_iso(),
                "mode": "live",
                "decision_id": "d2",
                "execution": {"outcome": "paper"},
            },
            {
                "ts": _now_iso(),
                "mode": "shadow",
                "decision_id": "d3",
                "execution": {"outcome": "paper"},
            },
        ],
    )


def test_slo_metrics_and_markdown(tmp_path: Path) -> None:
    _fixture(tmp_path)
    rep = build_report(tmp_path, _DAY, prometheus=None)

    chain = rep["chain"]
    assert chain["events"] == 10
    # 分母只算已出箱(M12)的链：a(完整) + b(缺 M13)；c/d 为 skip 主动终止，不计入
    assert chain["signal_chains"] == 2
    assert chain["complete_chains"] == 1
    assert chain["completion_ratio"] == 0.5
    assert chain["missing_stage"] == {"M7": 1, "M11": 0, "M13": 1}
    assert chain["wait_total"] == 2
    assert chain["wait_broken"] == 1
    assert chain["wait_attributable_ratio"] == 0.5
    assert chain["wait_vs_broken_ratio"] == 0.5
    assert chain["wait_reasons"] == {"wait_evidence_missing": 1}

    ex = rep["execution"]
    assert ex["live_decisions"] == 2
    assert ex["executor_processed"] == 0
    assert ex["placed_orders"] == 3
    assert ex["sltp_attached"] == 2
    assert ex["decision_fill_join_ratio"] == 0.6667
    assert ex["sltp_attach_ratio"] == 0.6667
    assert ex["live_outbox"] == 2
    assert ex["single_exit_violations"] == 1

    values = {item["key"]: item for item in rep["slo"]}
    assert values["chain_completion"]["ok"] is False
    assert values["single_exit_violation"]["ok"] is False
    assert rep["ok"] is False

    md = render_markdown(rep)
    assert "## SLO" in md and "## 链路" in md and "## 执行" in md and "## 误报台账" in md
    assert "50.00%" in md
    assert "✅ SLO 达标" not in md


def test_join_uses_outbox_when_decisions_ledger_lags(tmp_path: Path) -> None:
    """decisions.jsonl 未落 live 决策时，outbox 的 decision_id 仍应支撑成交回溯。"""
    _write_jsonl(
        tmp_path / "50-NN主矛盾评估器/runtime/live" / "outbox.jsonl",
        [
            {
                "ts": _now_iso(),
                "mode": "live",
                "decision_id": "d-outbox",
                "mandate_id": "mandate-x",
                "execution": {"outcome": "live:50-bypass"},
            }
        ],
    )
    _write_jsonl(
        tmp_path / "22-执行引擎中心/audit" / "x1_live_fills.jsonl",
        [
            {
                "ts": _now_iso(),
                "decision_id": "d-outbox",
                "order_placed": True,
                "request": {"sl_pct": 1.5, "tp_pct": 3.0},
            }
        ],
    )
    rep = build_report(tmp_path, _DAY, prometheus=None)
    assert rep["execution"]["live_decisions"] == 1
    assert rep["execution"]["decision_fill_join_ratio"] == 1.0


def test_join_falls_back_to_executor_processed(tmp_path: Path) -> None:
    """outbox 滚动淘汰后，执行器台账仍应支撑存量成交回溯。"""
    _write_jsonl(
        tmp_path / "22-执行引擎中心/audit" / "x1_live_fills.jsonl",
        [
            {
                "ts": _now_iso(),
                "decision_id": "d-hist",
                "order_placed": True,
                "request": {"sl_pct": 1.5, "tp_pct": 3.0},
            }
        ],
    )
    state = tmp_path / "22-执行引擎中心/runtime" / "x1_live_processed.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(
        json.dumps({"processed": {"d-hist": {"status": "executed", "ts": _now_iso()}}}),
        encoding="utf-8",
    )
    rep = build_report(tmp_path, _DAY, prometheus=None)
    assert rep["execution"]["live_decisions"] == 0
    assert rep["execution"]["executor_processed"] == 1
    assert rep["execution"]["decision_fill_join_ratio"] == 1.0


def test_prometheus_fail_open(tmp_path: Path) -> None:
    _fixture(tmp_path)
    rep = build_report(tmp_path, _DAY, prometheus="http://127.0.0.1:1")
    assert rep["alerts"]["available"] is False
    assert rep["alerts"]["error"]
    assert rep["false_positive"]["rate"] is None  # 告警不可用 → 不再推断误报率


def test_alert_episode_counting(tmp_path: Path, monkeypatch) -> None:
    base = 1_760_000_000

    def fake_http(url: str, timeout: float = 6.0) -> dict:
        return {
            "status": "success",
            "data": {
                "result": [
                    {
                        "metric": {"alertname": "MainNNConstraintDegraded", "severity": "P2"},
                        "values": [[base, "1"], [base + 300, "1"], [base + 1200, "1"]],
                    },
                    {
                        "metric": {"alertname": "MainNNExecutionRightsMismatch", "severity": "P0"},
                        "values": [[base, "1"]],
                    },
                ]
            },
        }

    monkeypatch.setattr(report_mod, "_http_json", fake_http)
    alerts = report_mod.collect_alerts("http://prom", base, base + 3600)
    assert alerts["available"] is True
    assert alerts["alerts"]["MainNNConstraintDegraded"]["episodes"] == 2
    assert alerts["alerts"]["MainNNExecutionRightsMismatch"]["episodes"] == 1
    assert alerts["firing_episodes"] == 3


def test_fp_ledger_mark_dedup_and_rate(tmp_path: Path, monkeypatch) -> None:
    _fixture(tmp_path)
    ledger_path = tmp_path / "reports" / "fp_ledger.json"
    mark_fp(ledger_path, "MainNNConstraintDegraded", "首批样本不足", _DAY.isoformat())
    mark_fp(ledger_path, "MainNNConstraintDegraded", "改为人工确认", _DAY.isoformat())
    data = load_ledger(ledger_path)
    assert len(data["entries"]) == 1
    assert data["entries"][0]["note"] == "改为人工确认"
    assert "MainNNConstraintDegraded" in render_fp_list(data)

    monkeypatch.setattr(
        report_mod,
        "collect_alerts",
        lambda prom, s, e: {
            "available": True,
            "error": "",
            "alerts": {"MainNNConstraintDegraded": {"episodes": 3, "samples": 5, "severity": "P2"}},
            "firing_episodes": 3,
        },
    )
    rep = build_report(tmp_path, _DAY, prometheus="http://prom", ledger_path=ledger_path)
    assert rep["false_positive"]["marked"] == 1
    assert rep["false_positive"]["rate"] == 0.3333
    assert rep["false_positive"]["within_slo"] is False
    assert "33.33%" in render_markdown(rep)
