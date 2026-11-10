# ruff: noqa: E402  (sys.path 必须先于 asil 导入)
"""D3/D2 双涌现闭环 pytest。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from asil.emergence_loop import (
    D2EmergenceLoop,
    D3EmergenceLoop,
    RuleVariant,
    TraeReviewCheckpoint,
)


def _write_events(path: Path) -> None:
    rows = []
    for i in range(100):
        if i % 5 == 0:  # 20% 未知 domain：回退策略在这里产生差异
            rows.append(
                {
                    "session_id": f"u{i}",
                    "intent_signals": {"file_domains": ["unknown_dom"]},
                    "intent_proxy": "trade",
                }
            )
        else:
            rows.append(
                {
                    "session_id": f"k{i}",
                    "intent_signals": {"file_domains": ["dom1"]},
                    "intent_proxy": "trade",
                }
            )
    rows.append(
        {
            "session_id": "other1",
            "intent_signals": {"file_domains": ["dom2"]},
            "intent_proxy": "research",
        }
    )
    path.write_text("\n".join(json.dumps(r) for r in rows))


class TestTraeReviewCheckpoint:
    def test_request_and_collect(self, tmp_path):
        cp = TraeReviewCheckpoint(tmp_path)
        req = cp.request({"domain": "D3", "x": 1}, "d3-r1-test")
        assert req.exists()
        assert cp.collect(req) is None  # 尚未回写

        cp.result_path(req).write_text(json.dumps({"decision": "accept", "notes": "ok"}))
        res = cp.collect(req)
        assert res["decision"] == "accept"

    def test_auto_verdict_rules(self):
        assert TraeReviewCheckpoint.auto_verdict(True, True)["decision"] == "accept"
        assert TraeReviewCheckpoint.auto_verdict(True, False)["decision"] == "reject"
        assert TraeReviewCheckpoint.auto_verdict(False, True)["decision"] == "reject"


class TestD3EmergenceLoop:
    def test_loop_accepts_better_variant(self, tmp_path):
        """门禁逻辑：候选 top1 提升且校准不回退 → accept 并换冠军。"""
        loop = D3EmergenceLoop(
            events_path=tmp_path / "unused.jsonl",
            variants=[RuleVariant("base"), RuleVariant("better")],
            reviewer="auto",
            review_dir=tmp_path / "reviews",
            loop_dir=tmp_path / "loops",
        )
        loop._train = [{"ok": True}]  # 跳过真实数据加载
        loop._val = [{"ok": True}]
        metrics = {
            "base": {
                "top1": 0.80,
                "ece": 0.10,
                "n_val": 10,
                "holdout_top1": 0.80,
                "holdout_ece": 0.10,
                "n_holdout": 200,
                "holdout_correct": [1] * 160 + [0] * 40,
            },
            "better": {
                "top1": 0.90,
                "ece": 0.05,
                "n_val": 10,
                "holdout_top1": 0.90,
                "holdout_ece": 0.05,
                "n_holdout": 200,
                "holdout_correct": [1] * 180 + [0] * 20,
            },
        }
        loop.evaluate = lambda v: dict(metrics[v.name])
        summary = loop.run(rounds=1)
        assert summary["rounds"] == 1
        assert summary["history"][0]["decision"] == "accept"
        assert summary["history"][0]["metrics"]["gate"] == "holdout_bootstrap_holm"
        assert summary["history"][0]["metrics"]["ci"]["ci_low"] > 0
        assert summary["champion"] == "better"
        assert summary["champion_metrics"]["top1"] == 0.9
        assert (tmp_path / "loops" / "d3_champion.json").exists()

    def test_loop_rejects_calibration_regression(self, tmp_path):
        """门禁逻辑：top1 提升但 ECE 恶化超容忍度 → reject，冠军不变。"""
        loop = D3EmergenceLoop(
            events_path=tmp_path / "unused.jsonl",
            variants=[RuleVariant("base"), RuleVariant("overconfident")],
            ece_tolerance=0.02,
            reviewer="auto",
            review_dir=tmp_path / "r",
            loop_dir=tmp_path / "l",
        )
        loop._train = [{"ok": True}]
        loop._val = [{"ok": True}]
        metrics = {
            "base": {
                "top1": 0.80,
                "ece": 0.05,
                "n_val": 10,
                "holdout_top1": 0.80,
                "holdout_ece": 0.05,
                "n_holdout": 100,
                "holdout_correct": [1] * 80 + [0] * 20,
            },
            "overconfident": {
                "top1": 0.90,
                "ece": 0.20,
                "n_val": 10,
                "holdout_top1": 0.90,
                "holdout_ece": 0.20,
                "n_holdout": 100,
                "holdout_correct": [1] * 90 + [0] * 10,
            },
        }
        loop.evaluate = lambda v: dict(metrics[v.name])
        summary = loop.run(rounds=1)
        assert summary["history"][0]["decision"] == "reject"
        assert summary["history"][0]["metrics"]["gate"] == "screened_out_on_val"
        assert summary["champion"] == "base"

    def test_real_dataset_smoke(self, tmp_path):
        """真实 1092 条 intent events 上闭环可跑且指标合法。"""
        loop = D3EmergenceLoop(reviewer="auto", review_dir=tmp_path / "r", loop_dir=tmp_path / "l")
        summary = loop.run(rounds=2)
        assert summary["n_train"] > 0 and summary["n_val"] > 0
        assert 0.0 <= summary["champion_metrics"]["top1"] <= 1.0
        assert summary["champion_metrics"]["ece"] >= 0.0

    def test_loop_is_deterministic(self, tmp_path):
        events = tmp_path / "events.jsonl"
        _write_events(events)
        kwargs = {
            "events_path": events,
            "seed": 7,
            "reviewer": "auto",
            "review_dir": tmp_path / "r",
            "loop_dir": tmp_path / "l",
        }
        a = D3EmergenceLoop(**kwargs).run(rounds=3)
        b = D3EmergenceLoop(**kwargs).run(rounds=3)
        assert a["champion"] == b["champion"]
        assert a["champion_metrics"] == b["champion_metrics"]
        assert a["n_val"] == b["n_val"]

    def test_loop_rounds_capped_by_variants(self, tmp_path):
        events = tmp_path / "events.jsonl"
        _write_events(events)
        loop = D3EmergenceLoop(
            events_path=events,
            variants=[RuleVariant("only_one")],
            reviewer="auto",
            review_dir=tmp_path / "r",
            loop_dir=tmp_path / "l",
        )
        summary = loop.run(rounds=5)
        assert summary["rounds"] == 0  # 无候选变体

    def test_trae_reviewer_falls_back_without_result(self, tmp_path):
        events = tmp_path / "events.jsonl"
        _write_events(events)
        rdir = tmp_path / "reviews"
        loop = D3EmergenceLoop(
            events_path=events,
            variants=[
                RuleVariant("baseline_general_sum", fallback="general"),
                RuleVariant("majority_sum", fallback="majority"),
            ],
            reviewer="trae",
            review_dir=rdir,
            loop_dir=tmp_path / "l",
        )
        summary = loop.run(rounds=1)
        assert summary["history"][0]["reviewer"] == "auto"  # 未回写 → 确定性兜底
        assert list(rdir.glob("*.request.json"))


class TestD2EmergenceLoop:
    def _write_gaps(self, path: Path) -> None:
        rows = [
            {
                "gap_id": "GAP-1",
                "gap_type": "architecture_gap",
                "evidence": {},
                "expected_value": "x",
                "status": "open",
            },
            {
                "gap_id": "GAP-2",
                "gap_type": "custom_unknown",
                "evidence": {},
                "expected_value": "y",
                "status": "open",
            },
            {
                "gap_id": "GAP-3",
                "gap_type": "architecture_gap",
                "evidence": {},
                "expected_value": "z",
                "status": "closed",
            },
        ]
        path.write_text("\n".join(json.dumps(r) for r in rows))

    def test_run_produces_scoreboard_and_no_source_mutation(self, tmp_path):
        gaps = tmp_path / "gaps.jsonl"
        self._write_gaps(gaps)
        before = gaps.read_text()
        loop = D2EmergenceLoop(
            gaps_path=gaps,
            use_gate_45=False,
            reviewer="auto",
            review_dir=tmp_path / "r",
            loop_dir=tmp_path / "l",
        )
        summary = loop.run()
        assert summary["n_gaps"] == 2  # closed 被排除
        assert "architecture_gap" in summary["scoreboard"]
        assert summary["scoreboard"]["architecture_gap"]["pass_rate"] == 1.0
        assert summary["champion_template"] == "architecture_gap"
        assert len(summary["gap_feedback"]) == 2
        assert gaps.read_text() == before  # 零执行权：不修改 registry
        assert (tmp_path / "l" / "d2_scoreboard.json").exists()

    def test_unsupported_gap_kept_open(self, tmp_path):
        gaps = tmp_path / "gaps.jsonl"
        self._write_gaps(gaps)
        loop = D2EmergenceLoop(
            gaps_path=gaps, reviewer="auto", review_dir=tmp_path / "r", loop_dir=tmp_path / "l"
        )
        summary = loop.run()
        unknown = [f for f in summary["gap_feedback"] if f["gap_type"] == "custom_unknown"]
        assert unknown and unknown[0]["proposed"] == "keep_open"
