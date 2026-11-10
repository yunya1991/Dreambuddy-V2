# ruff: noqa: E402  (sys.path 必须先于 asil 导入)
"""TRAE 评注握手验证：accept/reject 覆盖、防篡改隔离、异常回写降级。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from asil.emergence_loop import D2EmergenceLoop, D3EmergenceLoop
from asil.variant_generator import RuleVariant


def _d2(tmp_path) -> D2EmergenceLoop:
    gaps = tmp_path / "gaps.jsonl"
    gaps.write_text("")
    return D2EmergenceLoop(
        gaps_path=gaps,
        reviewer="trae",
        review_dir=tmp_path / "reviews",
        loop_dir=tmp_path / "loops",
    )


def _write_result(request: Path, payload: dict | str) -> None:
    body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    request.with_name(request.name.replace(".request.json", ".result.json")).write_text(body)


class TestAnnotationOverrides:
    def test_accept_overrides_auto_reject(self, tmp_path):
        loop = _d2(tmp_path)
        payload = {"domain": "D2", "gap_id": "GAP-X"}

        decision, reviewer, _ = loop._decide("d2-g1-GAP-X", payload, accepted=False)
        assert (decision, reviewer) == ("reject", "auto")

        req = sorted((tmp_path / "reviews").glob("*.request.json"))[0]
        _write_result(req, {"decision": "accept", "notes": "Trae：条件接受，补验收口径"})

        decision, reviewer, notes = loop._decide("d2-g1-GAP-X", payload, accepted=False)
        assert (decision, reviewer) == ("accept", "trae")
        assert "补验收口径" in notes

    def test_reject_overrides_auto_accept(self, tmp_path):
        loop = _d2(tmp_path)
        payload = {"domain": "D2", "gap_id": "GAP-Y"}

        decision, reviewer, _ = loop._decide("d2-g2-GAP-Y", payload, accepted=True)
        assert (decision, reviewer) == ("accept", "auto")

        req = sorted((tmp_path / "reviews").glob("*.request.json"))[0]
        _write_result(req, {"decision": "reject", "notes": "Trae：方案未覆盖失败路径"})

        decision, reviewer, notes = loop._decide("d2-g2-GAP-Y", payload, accepted=True)
        assert (decision, reviewer) == ("reject", "trae")
        assert "失败路径" in notes


class TestAnnotationSafety:
    def test_annotation_is_bound_to_payload_digest(self, tmp_path):
        loop = _d2(tmp_path)
        req_a = loop.checkpoint.request({"domain": "D2", "gap_id": "A"}, "tag-a")
        _write_result(req_a, {"decision": "accept", "notes": "for A"})

        decision, reviewer, _ = loop._decide("tag-b", {"domain": "D2", "gap_id": "B"}, True)
        assert (decision, reviewer) == ("accept", "auto")  # B 不应读到 A 的评注
        assert req_a.exists()

    def test_invalid_decision_token_is_exposed(self, tmp_path):
        loop = _d2(tmp_path)
        payload = {"domain": "D2", "gap_id": "GAP-Z"}
        req = loop.checkpoint.request(payload, "tag-invalid")
        _write_result(req, {"decision": "maybe", "notes": "模糊意见"})

        decision, reviewer, notes = loop._decide("tag-invalid", payload, True)
        assert (decision, reviewer) == ("accept", "auto")
        assert "无效" in notes
        assert loop.checkpoint.pending[-1]["reason"] == "invalid_result"

    def test_malformed_json_falls_back(self, tmp_path):
        loop = _d2(tmp_path)
        payload = {"domain": "D2", "gap_id": "GAP-BAD"}
        req = loop.checkpoint.request(payload, "tag-bad")
        _write_result(req, "{not-json")

        decision, reviewer, notes = loop._decide("tag-bad", payload, False)
        assert (decision, reviewer) == ("reject", "auto")
        assert "无效" in notes
        assert sorted(tmp_path.glob("reviews/*"))  # 不删除、不崩溃

    def test_absent_annotation_is_pending(self, tmp_path):
        loop = _d2(tmp_path)
        decision, reviewer, notes = loop._decide("tag-pending", {"gap_id": "P"}, True)
        assert (decision, reviewer) == ("accept", "auto")
        assert "待回写" in notes
        assert loop.checkpoint.pending[-1]["reason"] == "awaiting_result"
        assert Path(loop.checkpoint.pending[-1]["request"]).exists()


class TestEndToEndAnnotation:
    def test_d2_run_honors_written_reject(self, tmp_path):
        gaps = tmp_path / "gaps.jsonl"
        gaps.write_text(
            json.dumps(
                {
                    "gap_id": "GAP-E2E",
                    "gap_type": "architecture_gap",
                    "evidence": {},
                    "expected_value": "补验收口径",
                    "status": "open",
                }
            )
        )
        kwargs = {
            "gaps_path": gaps,
            "reviewer": "trae",
            "review_dir": tmp_path / "r",
            "loop_dir": tmp_path / "l",
        }

        first = D2EmergenceLoop(**kwargs).run()
        assert first["history"][0]["reviewer"] == "auto"
        assert first["overall_pass_rate"] == 1.0
        assert len(first["pending_reviews"]) == 1

        req = sorted((tmp_path / "r").glob("*.request.json"))[-1]
        _write_result(req, {"decision": "reject", "notes": "Trae：验收口径不可计算，驳回"})

        second = D2EmergenceLoop(**kwargs).run()
        assert second["history"][0]["reviewer"] == "trae"
        assert second["history"][0]["decision"] == "reject"
        assert second["overall_pass_rate"] == 0.0
        assert second["pending_reviews"] == []

    def test_d3_pending_reviews_exposed(self, tmp_path):
        metrics = {
            "base": {
                "top1": 0.80,
                "ece": 0.10,
                "n_val": 10,
                "holdout_top1": 0.80,
                "holdout_ece": 0.10,
                "n_holdout": 100,
                "holdout_correct": [1] * 80 + [0] * 20,
            },
            "cand": {
                "top1": 0.90,
                "ece": 0.10,
                "n_val": 10,
                "holdout_top1": 0.90,
                "holdout_ece": 0.10,
                "n_holdout": 100,
                "holdout_correct": [1] * 90 + [0] * 10,
            },
        }
        loop = D3EmergenceLoop(
            events_path=tmp_path / "unused.jsonl",
            variants=[RuleVariant("base"), RuleVariant("cand", fallback="majority")],
            reviewer="trae",
            review_dir=tmp_path / "r",
            loop_dir=tmp_path / "l",
        )
        loop._train = [{"ok": True}]
        loop._val = [{"ok": True}]
        loop._holdout = [{"ok": True}]
        loop.evaluate = lambda v: dict(metrics[v.name])

        summary = loop.run(rounds=1)
        assert len(summary["pending_reviews"]) == 1
        assert summary["pending_reviews"][0]["reason"] == "awaiting_result"
        assert Path(summary["pending_reviews"][0]["request"]).exists()
