"""
A2: CausalSampleStore TDD 测试（RED）
SPEC-A2-因果ATE历史样本接入.md §2 / §5

覆盖:
  #1 bootstrap ≥500 且 X/treatment/y 对齐
  #2 源A ≥500 → 独用源A（保真优先）
  #3 源A 不足 + 源B 充足 → 独用源B（绝不混合 live+bootstrap）
  #4 双源皆不足 → 返回空（上层 insufficient_samples）
  #5 源A 标注即持久化（进程重启不丢）
  #6 源B 文件缺失 FAIL-OPEN 不抛异常
  #7 源B 文件更新 → 缓存失效重载
  #8 treatment 退化（单水平）→ 返回空
  #9 treatment=R_up>median 预注册 → significant=True 且 CI 不含 0
  #13 HC-AGI-08: CausalEngine.MIN_SAMPLES == 500 守门
"""
from __future__ import annotations

import json

import numpy as np


def _write_bootstrap_jsonl(path, n, seed=42, constant_rup=None, effect=0.5, noise=0.5):
    """写入 n 条 shadow_rl 风格样本（state{6维}+action+reward）."""
    rng = np.random.default_rng(seed)
    with open(path, "w", encoding="utf-8") as f:
        for _ in range(n):
            rup = float(constant_rup) if constant_rup is not None else float(rng.normal(0.0, 1.0))
            rec = {
                "symbol": "BTC/USDT",
                "state": {
                    "R_up": rup,
                    "R_down": float(rng.normal(0.0, 1.0)),
                    "R_smooth": float(rng.normal(0.0, 1.0)),
                    "R_flow": float(rng.normal(0.0, 1.0)),
                    "R_reflexivity": float(rng.normal(0.0, 1.0)),
                    "quality_score": 1.0,
                },
                "action": "long" if rup > 0 else "WAIT",
                "reward": float(effect * rup + rng.normal(0.0, noise)),
                "next_state": {},
            }
            f.write(json.dumps(rec) + "\n")


def _make_live_samples(n, seed=1):
    """构造 n 条源A（实时矛盾样本，已延迟标注 actual_return）."""
    rng = np.random.default_rng(seed)
    return [
        {
            "power": float(rng.uniform(0.0, 1.0)),
            "time": float(rng.uniform(0.0, 1.0)),
            "consistency": float(rng.uniform(0.0, 1.0)),
            "market_weight": float(rng.uniform(0.0, 1.0)),
            "direction": "long",
            "confidence": 0.7,
            "actual_return": float(rng.normal(0.0, 0.01)),
        }
        for _ in range(n)
    ]


class TestCausalSampleStore:
    """双源历史因果样本库（独立估计、退化保护、缓存、FAIL-OPEN）."""

    def _store(self, tmp_path, shadow=None, live=None, **kw):
        from dreambuddy_evolution.core.causal_sample_store import CausalSampleStore

        return CausalSampleStore(
            shadow_path=str(shadow or (tmp_path / "boot.jsonl")),
            live_path=str(live or (tmp_path / "live.json")),
            **kw,
        )

    def test_bootstrap_returns_ge_500_when_shadow_rl_present(self, tmp_path):
        """#1: 源B ≥500 → source=bootstrap，X/treatment/y 长度对齐."""
        boot = tmp_path / "boot.jsonl"
        _write_bootstrap_jsonl(boot, 600)
        store = self._store(tmp_path, shadow=boot)
        result = store.build_ate_samples()
        assert result is not None
        assert result["source"] == "bootstrap"
        assert result["n"] >= 500
        assert result["X"].shape[0] == len(result["treatment"]) == len(result["y"]) == result["n"]

    def test_live_source_priority_when_enough(self, tmp_path):
        """#2: 源A ≥500 → 独用源A，不使用源B."""
        boot = tmp_path / "boot.jsonl"
        _write_bootstrap_jsonl(boot, 600)
        store = self._store(tmp_path, shadow=boot)
        live = _make_live_samples(600)
        result = store.build_ate_samples(live_samples=live)
        assert result is not None
        assert result["source"] == "live"
        assert result["n"] == 600

    def test_no_mixed_source_estimation(self, tmp_path):
        """#3（评审 M3）: 源A 不足 + 源B 充足 → 独用源B，绝不产生 live+bootstrap."""
        boot = tmp_path / "boot.jsonl"
        _write_bootstrap_jsonl(boot, 600)
        store = self._store(tmp_path, shadow=boot)
        live = _make_live_samples(100)
        result = store.build_ate_samples(live_samples=live)
        assert result is not None
        assert result["source"] == "bootstrap"
        assert result["source"] != "live+bootstrap"
        assert result["n"] == 600

    def test_both_insufficient_returns_none(self, tmp_path):
        """#4: 源A 空 + 源B 无文件 → 返回 None."""
        store = self._store(tmp_path, shadow=tmp_path / "nope.jsonl")
        assert store.build_ate_samples(live_samples=[]) is None

    def test_label_and_persist_contradiction_sample(self, tmp_path):
        """#5（评审 m5）: 源A 标注即落盘，新实例可读回."""
        from dreambuddy_evolution.core.contradiction_identifier import (
            ContradictionWeightLearner,
        )

        path = tmp_path / "contradiction_samples.json"
        learner = ContradictionWeightLearner(storage_path=str(path))
        learner.record_prediction(
            {"power": 0.6, "time": 0.5, "consistency": 0.7, "market_weight": 0.2},
            "long",
            0.8,
        )
        learner.label_previous(0.012)

        reloaded = ContradictionWeightLearner(storage_path=str(path))
        assert reloaded.labeled_count == 1

    def test_missing_file_fail_open(self, tmp_path):
        """#6: 源B 路径不存在 → 不抛异常，返回 None."""
        store = self._store(tmp_path, shadow=tmp_path / "not_exist.jsonl")
        store.build_ate_samples()  # 不应抛异常

    def test_bootstrap_cache_invalidation_on_mtime_change(self, tmp_path):
        """#7: 文件更新（大小/mtime 变化）→ 缓存失效并重载."""
        boot = tmp_path / "boot.jsonl"
        _write_bootstrap_jsonl(boot, 600, seed=1)
        store = self._store(tmp_path, shadow=boot)
        r1 = store.build_ate_samples()
        assert r1 is not None and r1["n"] == 600

        _write_bootstrap_jsonl(boot, 1200, seed=7)
        r2 = store.build_ate_samples()
        assert r2 is not None and r2["n"] == 1200

    def test_degenerate_treatment_returns_insufficient(self, tmp_path):
        """#8（评审 M1）: R_up 恒定 → treatment 单水平 → 退化保护 → 返回 None."""
        boot = tmp_path / "boot.jsonl"
        _write_bootstrap_jsonl(boot, 600, constant_rup=0.3)
        store = self._store(tmp_path, shadow=boot)
        assert store.build_ate_samples() is None

    def test_bootstrap_treatment_R_up_is_significant(self):
        """#9（评审 M2）: 预注册 treatment=R_up>median，固定种子切片 → 显著."""
        from dreambuddy_evolution.core.causal_engine import CausalEngine
        from dreambuddy_evolution.core.causal_sample_store import CausalSampleStore

        import tempfile
        import os

        with tempfile.TemporaryDirectory() as td:
            boot = os.path.join(td, "boot.jsonl")
            _write_bootstrap_jsonl(boot, 800, seed=123, effect=1.0, noise=0.3)
            store = CausalSampleStore(
                shadow_path=boot, live_path=os.path.join(td, "live.json")
            )
            triplet = store.build_ate_samples()
            assert triplet is not None
            result = CausalEngine().estimate_ate(
                triplet["X"], triplet["treatment"], triplet["y"], method="dml"
            )
            assert result["method"] not in ("insufficient_samples", "error")
            assert result["significant"] is True
            assert not (result["lower_bound"] <= 0 <= result["upper_bound"])


class TestMinSamplesInvariant:
    """#13 HC-AGI-08: 因果引擎最小样本量下限守门."""

    def test_min_samples_remains_500(self):
        from dreambuddy_evolution.core.causal_engine import CausalEngine

        assert CausalEngine.MIN_SAMPLES == 500
