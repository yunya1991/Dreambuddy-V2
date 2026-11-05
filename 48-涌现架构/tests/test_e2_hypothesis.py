"""E2 做梦器升级为假设生成器测试（SPEC-EMERGENCE-EVOLUTION v0.5 §4 E2 / §1 E2）。

覆盖：
  - 结构变体生成：确定性（同 seed 同结果）、只做结构性扰动（开关/阈值分箱/标的集）、
    过 schema 校验（位串长度/阈值边界/coins_hash 一致性）、不产出人工已写配置
  - 正负反馈配平：keep_ratio<1 时确定性丢弃低新颖度变体并记录双向计数
  - 「人未写过」判读：编辑距离 >= k 才计新颖；registry 缺失 → 判据悬置（None）
  - ablation gate 双判据：过拟合（IS→OOS 退化超阈）+ 稳定性（切片胜率不足）
    + 最小样本 + 不优于基线即拒；无评估器 → evaluator_missing 不伪造指标
  - 批次 schema 统一两做梦器（33-REA 编排配置 / 4-MEMORY 记忆卫生）→ 同 envelope
  - M2 比率 = (verify 成功 且 编辑距离>=k) / 总生成数
  - run_e2 真实批次：无评估器时如实 evaluator_missing + E6 需求单（不重复发单）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_E2_DIR = Path(__file__).resolve().parents[1] / "experiments" / "e2_hypothesis"
if str(_E2_DIR) not in sys.path:
    sys.path.insert(0, str(_E2_DIR))

import ablation_gate as ag  # noqa: E402
import batch_schema as bs  # noqa: E402
import run_e2  # noqa: E402
import variant_generator as vg  # noqa: E402


@pytest.fixture()
def live_vector() -> dict:
    return {
        "switches_bitmask": "11111111",
        "bdsm_flags": "1110",
        "env_flags": "001110",
        "phase_flags": "11111",
        "threshold_bins": [16, 5, 20, 5],
        "coins": [
            "AMZN",
            "BNB",
            "BTC",
            "ETH",
            "SOL",
            "UNI",
            "XAU",
        ],
        "coins_hash": vg.coins_hash(["AMZN", "BNB", "BTC", "ETH", "SOL", "UNI", "XAU"]),
    }


@pytest.fixture()
def tiny_registry(tmp_path: Path, live_vector: dict) -> Path:
    p = tmp_path / "human_config_hashes.json"
    p.write_text(
        json.dumps({"human_configs": [{"id": "live", "struct_vector": live_vector}]}),
        encoding="utf-8",
    )
    return p


# ---------- 生成器：schema 校验 ----------


def test_validate_variant_accepts_live_vector(live_vector):
    assert vg.validate_variant(live_vector) == []


def test_validate_variant_rejects_bad_bits_and_bounds(live_vector):
    bad = dict(live_vector)
    bad["switches_bitmask"] = "1111"
    assert any("switches_bitmask" in e for e in vg.validate_variant(bad))

    bad2 = dict(live_vector)
    bad2["threshold_bins"] = [16, 5, 999, 5]
    assert any("threshold_bins" in e for e in vg.validate_variant(bad2))

    bad3 = dict(live_vector)
    bad3["coins_hash"] = "deadbeef"
    assert any("coins_hash" in e for e in vg.validate_variant(bad3))


# ---------- 生成器：结构与确定性 ----------


def test_generate_variants_is_deterministic(live_vector):
    a = vg.generate_variants(live_vector, n=12, seed=7)
    b = vg.generate_variants(live_vector, n=12, seed=7)
    assert [x["vector_hash"] for x in a["variants"]] == [x["vector_hash"] for x in b["variants"]]


def test_generate_variants_are_structural_and_valid(live_vector, tiny_registry):
    out = vg.generate_variants(live_vector, n=15, seed=3, registry_path=tiny_registry)
    variants = out["variants"]
    assert len(variants) == 15
    hashes = {v["vector_hash"] for v in variants}
    assert len(hashes) == 15  # 批内无重复
    for v in variants:
        assert vg.validate_variant(v["struct_vector"]) == []
        assert v["transform"] in vg.TRANSFORMS
        dist = vg.edit_distance(v["struct_vector"], live_vector)
        assert dist >= 1
        # 变体必须与人工配置不同（不与 base 相同）
        assert v["vector_hash"] != vg.vector_hash(live_vector)


def test_generate_variants_skip_human_written(live_vector, tiny_registry):
    out = vg.generate_variants(
        live_vector, n=10, seed=11, registry_path=tiny_registry, min_novelty=1
    )
    for v in out["variants"]:
        assert v["novelty"]["min_distance"] >= 1


def test_feedback_balance_drops_lowest_novelty(live_vector, tiny_registry):
    out = vg.generate_variants(
        live_vector, n=12, seed=5, registry_path=tiny_registry, keep_ratio=0.5
    )
    assert len(out["variants"]) == 6
    assert out["feedback"]["n_kept"] == 6
    assert out["feedback"]["n_dropped"] == 6
    kept_dists = [v["novelty"]["min_distance"] for v in out["variants"]]
    dropped_dists = out["feedback"]["dropped_min_distances"]
    assert min(kept_dists) >= max(dropped_dists)


# ---------- 「人未写过」判读 ----------


def test_novelty_missing_registry_is_suspended(live_vector, tmp_path):
    n = vg.assess_novelty(live_vector, registry_path=tmp_path / "nope.json")
    assert n["is_human_written"] is None
    assert "悬置" in n["reason"]


def test_novelty_distance_threshold(live_vector, tiny_registry):
    close = dict(live_vector)
    close["bdsm_flags"] = "0110"  # 只翻 1 位 → distance 1 < k=2
    assert vg.assess_novelty(close, registry_path=tiny_registry)["is_human_written"] is True

    far = dict(live_vector)
    far["bdsm_flags"] = "0001"  # 翻 3 位 → distance 3 >= 2
    far["threshold_bins"] = [16, 5, 25, 5]
    assert vg.assess_novelty(far, registry_path=tiny_registry)["is_human_written"] is False


# ---------- ablation gate ----------


def test_gate_rejects_overfit():
    res = ag.evaluate(
        is_metrics={"total_pnl_pct": 0.30, "n_trades": 40},
        oos_metrics={"total_pnl_pct": -0.10, "n_trades": 20},
        slice_metrics=[0.02, 0.03, 0.01, 0.02],
    )
    assert res["admitted"] is False
    assert any("overfit" in r for r in res["reasons"])


def test_gate_rejects_unstable():
    res = ag.evaluate(
        is_metrics={"total_pnl_pct": 0.05, "n_trades": 40},
        oos_metrics={"total_pnl_pct": 0.01, "n_trades": 20},
        slice_metrics=[-0.05, -0.03, 0.01, -0.02],
    )
    assert res["admitted"] is False
    assert any("stability" in r for r in res["reasons"])


def test_gate_rejects_insufficient_sample():
    res = ag.evaluate(
        is_metrics={"total_pnl_pct": 0.05, "n_trades": 40},
        oos_metrics={"total_pnl_pct": 0.04, "n_trades": 3},
        slice_metrics=[0.01, 0.02, 0.03],
    )
    assert res["admitted"] is False
    assert any("insufficient_sample" in r for r in res["reasons"])


def test_gate_rejects_when_stability_missing():
    res = ag.evaluate(
        is_metrics={"total_pnl_pct": 0.05, "n_trades": 40},
        oos_metrics={"total_pnl_pct": 0.04, "n_trades": 20},
        slice_metrics=None,
    )
    assert res["admitted"] is False
    assert any("stability_unavailable" in r for r in res["reasons"])


def test_gate_rejects_when_not_beating_baseline():
    res = ag.evaluate(
        is_metrics={"total_pnl_pct": 0.05, "n_trades": 40},
        oos_metrics={"total_pnl_pct": -0.27, "n_trades": 20},
        slice_metrics=[0.01, 0.02, 0.03],
        baseline_oos={"total_pnl_pct": -0.27},
    )
    assert res["admitted"] is False
    assert any("not_better_than_baseline" in r for r in res["reasons"])


def test_gate_admits_stable_non_overfit():
    res = ag.evaluate(
        is_metrics={"total_pnl_pct": 0.02, "n_trades": 40},
        oos_metrics={"total_pnl_pct": 0.01, "n_trades": 20},
        slice_metrics=[0.01, 0.02, 0.015, 0.005],
        baseline_oos={"total_pnl_pct": -0.27},
    )
    assert res["admitted"] is True
    assert res["reasons"] == []


def test_gate_without_evaluator_is_not_fabricated():
    res = ag.evaluate(None, None, None)
    assert res["admitted"] is False
    assert res["status"] == "evaluator_missing"
    assert res["is_oos_degradation"] is None


# ---------- 批次 schema 统一 ----------


def test_build_batch_envelope_and_m2():
    items = [
        {
            "variant_id": "v1",
            "struct_vector": {"x": 1},
            "vector_hash": "h1",
            "novelty": {"is_human_written": False, "min_distance": 3},
            "gate": {"admitted": True, "reasons": []},
            "verify": {"success": True, "evaluated_by": "test"},
        },
        {
            "variant_id": "v2",
            "struct_vector": {"x": 2},
            "vector_hash": "h2",
            "novelty": {"is_human_written": True, "min_distance": 1},
            "gate": {"admitted": False, "reasons": ["overfit"]},
            "verify": {"success": True, "evaluated_by": "test"},
        },
        {
            "variant_id": "v3",
            "struct_vector": {"x": 3},
            "vector_hash": "h3",
            "novelty": {"is_human_written": False, "min_distance": 2},
            "gate": {"admitted": True, "reasons": []},
            "verify": {"success": False, "evaluated_by": "test"},
        },
    ]
    batch = bs.build_batch(generator="test", space="trading_struct_vector", items=items)
    assert batch["schema_version"] == bs.SCHEMA_VERSION
    assert set(batch) == {
        "schema_version",
        "batch_id",
        "generated_at",
        "generator",
        "space",
        "items",
        "stats",
    }
    stats = batch["stats"]
    assert stats["n_generated"] == 3
    assert stats["n_novel"] == 2
    # M2：新颖 且 verify 成功 = 1 / 3
    assert stats["n_novel_verified"] == 1
    assert stats["m2_ratio"] == pytest.approx(1 / 3)


def test_batch_adapter_normalizes_rea_dream_output():
    rea = {
        "best_strategy": {"analyzer_sequence": ["a", "b"], "transform": "sequence_permutation"},
        "candidates": [
            {"strategy": {"analyzer_sequence": ["a", "b"], "transform": "current"}, "avg_v": 0.5},
            {
                "strategy": {"analyzer_sequence": ["b", "a"], "transform": "sequence_permutation"},
                "avg_v": 0.6,
            },
        ],
        "improved": True,
    }
    batch = bs.adapter_rea_dreaming(rea)
    assert batch["space"] == "rea_orchestration_config"
    assert batch["stats"]["n_generated"] == 2
    assert all(item["space"] == "rea_orchestration_config" for item in batch["items"])
    # 编排配置无结构向量 → 新颖度判据悬置（None），不伪造
    assert all(item["novelty"]["is_human_written"] is None for item in batch["items"])


def test_batch_adapter_normalizes_memory_dream_output():
    mem = {"merge_candidates": [{"key": "k1"}, {"key": "k2"}], "dedupe_ratio": 0.1}
    batch = bs.adapter_memory_dreaming(mem)
    assert batch["space"] == "memory_hygiene"
    assert batch["stats"]["n_generated"] == 2


# ---------- run_e2 真实批次 ----------


def test_run_e2_without_evaluator_marks_missing_and_emits_gap(tmp_path, live_vector):
    reg = tmp_path / "human_config_hashes.json"
    reg.write_text(
        json.dumps({"human_configs": [{"id": "live", "struct_vector": live_vector}]}),
        encoding="utf-8",
    )
    gaps = tmp_path / "capability_gaps.jsonl"
    result = run_e2.run(
        registry_path=reg, gaps_path=gaps, out_path=tmp_path / "result.json", n=8, seed=1
    )
    assert result["status"] == "ok"
    assert result["verify_status"] == "evaluator_missing"
    assert result["stats"]["n_generated"] == 8
    assert result["stats"]["n_novel"] > 0
    assert result["stats"]["m2_ratio"] == 0.0
    assert result["stats"]["n_verified"] == 0
    assert gaps.exists()
    gap = json.loads(gaps.read_text(encoding="utf-8").strip().splitlines()[0])
    assert gap["created_by"] == "e2_hypothesis"
    assert gap["gap_type"] == "backtest_evaluator_missing"


def test_run_e2_does_not_duplicate_open_gap(tmp_path, live_vector):
    reg = tmp_path / "human_config_hashes.json"
    reg.write_text(
        json.dumps({"human_configs": [{"id": "live", "struct_vector": live_vector}]}),
        encoding="utf-8",
    )
    gaps = tmp_path / "capability_gaps.jsonl"
    run_e2.run(registry_path=reg, gaps_path=gaps, out_path=tmp_path / "r1.json", n=6, seed=1)
    run_e2.run(registry_path=reg, gaps_path=gaps, out_path=tmp_path / "r2.json", n=6, seed=2)
    lines = [ln for ln in gaps.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1


def test_evaluator_gap_routes_to_eval_domain(tmp_path):
    """E2 需求单必须被 E6 路由器指派到 45-评测系统（非人工指派）。"""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "registry"))
    import capability_gaps as cg
    import gap_router as gr

    gap = cg.new_gap("backtest_evaluator_missing", {"probe": True}, created_by="t")
    routed = gr.route_gap(
        gap, gaps_path=tmp_path / "gaps.jsonl", proposals_path=tmp_path / "p.jsonl"
    )
    assert routed == "45-评测系统"
