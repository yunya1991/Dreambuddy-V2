import importlib.util
from pathlib import Path


REPO_ROOT = Path("/Users/zhangjiangtao/WorkBuddy/dream-multiskill-v2")


def _load_module(rel_path: str):
    path = REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _payload(out):
    return out["payload"]


def test_a6_entrypoint_outputs_intelligence_summary(tmp_path: Path):
    mod = _load_module("workflows/trading-decision/A6_intelligence/entrypoint.py")
    out = mod.run_a6_intelligence(
        {
            "trace_id": "t-a6",
            "alerts": [{"source": "macro", "severity": "high"}],
            "signal_shift": 0.27,
        },
        output_dir=tmp_path,
    )
    assert out["header"]["source"] == "A6"
    payload = _payload(out)
    assert payload["stage_id"] == "A6"
    assert payload["alert_count"] == 1
    assert Path(payload["artifact_path"]).exists()


def test_a7_entrypoint_outputs_audit_report(tmp_path: Path):
    mod = _load_module("workflows/trading-decision/A7_audit/entrypoint.py")
    out = mod.run_a7_audit(
        {
            "trace_id": "t-a7",
            "checks": {"latency_ms": 120, "slippage_bps": 9},
            "violations": [],
        },
        output_dir=tmp_path,
    )
    assert out["header"]["source"] == "A7"
    assert out["header"]["target"] == "A8"
    payload = _payload(out)
    assert payload["stage_id"] == "A7"
    assert payload["audit_status"] in {"PASS", "REVIEW"}
    assert Path(payload["artifact_path"]).exists()


def test_a8_entrypoint_outputs_theory_practice_verification(tmp_path: Path):
    mod = _load_module("workflows/trading-decision/A8_theory-practice/entrypoint.py")
    out = mod.run_a8_theory_practice(
        {
            "trace_id": "t-a8",
            "hypothesis_score": 0.72,
            "practice_score": 0.69,
        },
        output_dir=tmp_path,
    )
    assert out["header"]["source"] == "A8"
    payload = _payload(out)
    assert payload["stage_id"] == "A8"
    assert payload["gap_score"] >= 0
    assert Path(payload["artifact_path"]).exists()


def test_a9_entrypoint_outputs_exit_plan(tmp_path: Path):
    mod = _load_module("workflows/trading-decision/A9_exit/entrypoint.py")
    out = mod.run_a9_exit(
        {
            "trace_id": "t-a9",
            "unrealized_pnl_pct": 3.8,
            "risk_level": "medium",
        },
        output_dir=tmp_path,
    )
    assert out["header"]["source"] == "A9"
    assert out["header"]["target"] == "A7"
    payload = _payload(out)
    assert payload["stage_id"] == "A9"
    assert payload["exit_action"] in {"TAKE_PROFIT", "STOP_LOSS", "HOLD"}
    assert Path(payload["artifact_path"]).exists()


def test_phase3_trade_skills_exist():
    required = [
        REPO_ROOT / "skills/1-TRADE/dream-intelligence-monitor/SKILL.md",
        REPO_ROOT / "skills/1-TRADE/dream-signal-scoring-spec/SKILL.md",
        REPO_ROOT / "skills/1-TRADE/dream-regime-detector/SKILL.md",
        REPO_ROOT / "skills/1-TRADE/A7-practice-theory/SKILL.md",
        REPO_ROOT / "skills/1-TRADE/A8-theory-practice-verification/SKILL.md",
        REPO_ROOT / "skills/1-TRADE/dream-exit-skill-v2/SKILL.md",
    ]
    for p in required:
        assert p.exists(), f"missing migrated skill: {p}"
