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


def test_a0_entrypoint_selects_primary_contradiction():
    mod = _load_module("workflows/trading-decision/A0_contradiction/entrypoint.py")

    out = mod.run_a0_contradiction_analysis(
        {
            "trace_id": "t-a0",
            "contradictions": [
                {"id": "cx1", "score": 2.1, "direction": "UP"},
                {"id": "cx2", "score": 3.5, "direction": "DOWN"},
            ],
        }
    )
    assert out["header"]["source"] == "A0"
    assert out["header"]["target"] == "A1"
    assert out["header"]["loop_type"] == "governance"
    payload = _payload(out)
    assert payload["stage_id"] == "A0"
    assert payload["primary_contradiction"]["id"] == "cx2"
    assert payload["direction"] == "DOWN"


def test_a1_entrypoint_writes_research_artifact(tmp_path: Path):
    mod = _load_module("workflows/trading-decision/A1_research/entrypoint.py")

    out = mod.run_a1_research(
        {
            "trace_id": "t-a1",
            "signals": ["ETF inflow", "OI up"],
            "confidence": 0.64,
        },
        output_dir=tmp_path,
    )
    assert out["header"]["source"] == "A1"
    assert out["header"]["target"] == "A2"
    payload = _payload(out)
    assert payload["stage_id"] == "A1"
    assert payload["artifact_path"]
    assert Path(payload["artifact_path"]).exists()


def test_a2_entrypoint_generates_first_principles_output(tmp_path: Path):
    mod = _load_module("workflows/trading-decision/A2_first-principles/entrypoint.py")

    out = mod.run_a2_first_principles(
        {
            "trace_id": "t-a2",
            "rsi": 75.0,
            "funding_rate": 0.0007,
            "fgi": 72,
        },
        output_dir=tmp_path,
    )
    assert out["header"]["source"] == "A2"
    assert out["header"]["target"] == "A3"
    payload = _payload(out)
    assert payload["stage_id"] == "A2"
    assert payload["least_resistance_path"] in {"UP", "DOWN", "NEUTRAL"}
    assert Path(payload["artifact_path"]).exists()


def test_phase1_trade_skills_exist():
    required = [
        REPO_ROOT / "skills/1-TRADE/dream-contradiction-theory/SKILL.md",
        REPO_ROOT / "skills/1-TRADE/dream-strategy-research/SKILL.md",
        REPO_ROOT / "skills/1-TRADE/dream-first-principles/SKILL.md",
    ]
    for p in required:
        assert p.exists(), f"missing migrated skill: {p}"
