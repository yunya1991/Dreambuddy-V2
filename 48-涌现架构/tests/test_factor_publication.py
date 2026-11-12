"""P3 接线单测：verdict → 发布视图 → 下游白名单 + 双读一致。"""

from __future__ import annotations

import json

import factor_publication as fp
import pytest


def _row(fid: str, verdict: str, **kwargs) -> dict:
    base = {
        "factor_id": fid,
        "horizon": 5,
        "ic": 0.05,
        "t_stat": 3.4,
        "n_obs": 800,
        "trial_id": f"T-{fid}",
        "gate_version": "v1",
        "written_at": "2026-11-12T00:00:00+00:00",
        "script": "test",
    }
    base["verdict"] = verdict
    base.update(kwargs)
    return base


@pytest.fixture()
def paths(tmp_path):
    return tmp_path / "factor_verdicts.jsonl", tmp_path / "factor_registry.json"


def _write(path, rows):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")


def test_only_consumable_verdicts_published(paths):
    verdicts, registry = paths
    _write(
        verdicts,
        [
            _row("E_score", "candidate"),
            _row("S_score", "candidate_weak"),
            _row("M_score", "inconclusive"),
            _row("P_score", "falsified"),
            _row("X_score", "insufficient_data"),
        ],
    )
    doc = fp.publish(verdicts, registry)

    assert set(doc["approved"]) == {"E_score", "S_score"}
    assert set(doc["excluded"]) == {"M_score", "P_score", "X_score"}
    assert doc["counts"] == {"approved": 2, "excluded": 3}
    assert fp.load_approved(registry).keys() == {"E_score", "S_score"}
    assert fp.is_consumable("E_score", registry) is True
    assert fp.is_consumable("M_score", registry) is False


def test_latest_verdict_wins(paths):
    """append-only：后一条 falsified 必须覆盖前一条 candidate。"""
    verdicts, registry = paths
    _write(verdicts, [_row("E_score", "candidate"), _row("E_score", "falsified")])
    doc = fp.publish(verdicts, registry)

    assert doc["approved"] == {}
    assert doc["excluded"]["E_score"]["verdict"] == "falsified"


def test_publish_is_idempotent_except_generated_at(paths):
    verdicts, registry = paths
    _write(verdicts, [_row("E_score", "candidate")])
    first = fp.publish(verdicts, registry)
    second = fp.publish(verdicts, registry)

    first.pop("generated_at")
    second.pop("generated_at")
    assert first == second


def test_missing_registry_does_not_fall_back_to_raw_verdicts(paths):
    """下游不得因发布视图缺失而回读原始 verdict（红线 1）。"""
    verdicts, registry = paths
    _write(verdicts, [_row("E_score", "candidate")])

    assert fp.load_approved(registry) == {}
    assert fp.is_consumable("E_score", registry) is False
    assert fp.load_registry(registry)["missing"] is True


def test_verify_two_way_ok(paths):
    verdicts, registry = paths
    _write(verdicts, [_row("E_score", "candidate")])
    fp.publish(verdicts, registry)

    report = fp.verify_two_way(verdicts, registry)
    assert report["ok"] is True
    assert report["checked"] == 1
    assert report["mismatches"] == []


def test_verify_detects_tampered_registry(paths):
    verdicts, registry = paths
    _write(verdicts, [_row("E_score", "candidate")])
    doc = fp.publish(verdicts, registry)
    doc["approved"]["E_score"]["ic"] = 0.9
    registry.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    report = fp.verify_two_way(verdicts, registry)
    assert report["ok"] is False
    assert report["mismatches"][0]["field"] == "ic"


def test_verify_detects_stale_registry(paths):
    """SSOT 后来降级为 inconclusive，registry 仍挂 candidate → stale。"""
    verdicts, registry = paths
    _write(verdicts, [_row("E_score", "candidate")])
    fp.publish(verdicts, registry)
    _write(verdicts, [_row("E_score", "candidate"), _row("E_score", "inconclusive")])

    report = fp.verify_two_way(verdicts, registry)
    assert report["ok"] is False
    assert report["stale"] == ["E_score"]


def test_verify_detects_unpublished(paths):
    verdicts, registry = paths
    _write(verdicts, [_row("P_score", "candidate")])

    report = fp.verify_two_way(verdicts, registry)
    assert report["ok"] is False
    assert report["unpublished"] == ["P_score"]


def test_cli_publish_verify_show(paths, monkeypatch):
    verdicts, registry = paths
    _write(verdicts, [_row("E_score", "candidate")])
    monkeypatch.setattr(fp, "VERDICTS_PATH", verdicts)
    monkeypatch.setattr(fp, "REGISTRY_PATH", registry)

    assert fp.main(["--publish"]) == 0
    assert fp.main(["--verify"]) == 0
    assert fp.main(["--show"]) == 0
    assert fp.main([]) == 0
