"""P2-1b RED: factor_head_mask 微调链路接线.

SPEC §5.4（矛盾论与Transformer架构融合方案）: 逆向推导判定错误维度 →
FactorHeadMaskFineTuner 降权 → override JSON 持久化 → build_factor_head_mask 应用。

attention bias 语义（core/cross_attention.py L152: scores = scores + mask）:
  0.0 = 无影响, 负值 = 抑制, -inf = 屏蔽。
  降权 multiplier m → 该 head 允许值 0.0 → log(m)（m=0.8 → -0.223 抑制）。
"""
import json
import math
from types import SimpleNamespace

import pytest


def _make_derive_result(wrong_dims, confidence=0.7, root_cause_type="dimension_misjudged"):
    return SimpleNamespace(
        per_dimension_correctness={d: (d not in wrong_dims) for d in ("C1", "C2", "C3")},
        confidence=confidence,
        known_gaps=[],
        root_cause="test",
        root_cause_type=root_cause_type,
        wrong_dimensions=list(wrong_dims),
        optimization_action="",
    )


def _make_snapshot_outcome():
    return (
        {"snapshot_id": "snap-1", "symbol": "BTC"},
        {"outcome_id": "out-1", "real_outcome": "loss"},
    )


class TestBridgeUpdatesOverride:
    """ReverseCognitiveBridge: wrong_dims 非空 → 调 tuner 更新 override JSON。"""

    def _bridge(self, tmp_path, **kwargs):
        from dreambuddy_evolution.engines.reverse_cognitive_bridge import (
            ReverseCognitiveBridge,
        )
        return ReverseCognitiveBridge(
            mask_override_path=str(tmp_path / "override.json"), **kwargs
        )

    def test_wrong_dims_creates_override(self, tmp_path):
        bridge = self._bridge(tmp_path)
        snap, out = _make_snapshot_outcome()
        bridge.record_evidence(_make_derive_result(["C1"]), snap, out)
        data = json.loads((tmp_path / "override.json").read_text())
        assert data["C1"] == pytest.approx(0.8)

    def test_cumulative_multiplication(self, tmp_path):
        bridge = self._bridge(tmp_path)
        snap, out = _make_snapshot_outcome()
        bridge.record_evidence(_make_derive_result(["C1"]), snap, out)
        bridge.record_evidence(_make_derive_result(["C1"]), snap, out)
        data = json.loads((tmp_path / "override.json").read_text())
        assert data["C1"] == pytest.approx(0.64)

    def test_clamp_lower_bound(self, tmp_path):
        bridge = self._bridge(tmp_path)
        snap, out = _make_snapshot_outcome()
        for _ in range(10):
            bridge.record_evidence(_make_derive_result(["C2"]), snap, out)
        data = json.loads((tmp_path / "override.json").read_text())
        assert data["C2"] >= 0.1

    def test_no_wrong_dims_writes_nothing(self, tmp_path):
        bridge = self._bridge(tmp_path)
        snap, out = _make_snapshot_outcome()
        bridge.record_evidence(_make_derive_result([]), snap, out)
        assert not (tmp_path / "override.json").exists()

    def test_corrupt_override_fail_open(self, tmp_path):
        (tmp_path / "override.json").write_text("{broken json!!")
        bridge = self._bridge(tmp_path)
        snap, out = _make_snapshot_outcome()
        # 不崩即可（FAIL-OPEN），且重写为合法结构
        bridge.record_evidence(_make_derive_result(["C3"]), snap, out)
        data = json.loads((tmp_path / "override.json").read_text())
        assert data["C3"] == pytest.approx(0.8)

    def test_disabled_bridge_writes_nothing(self, tmp_path):
        bridge = self._bridge(tmp_path, enabled=False)
        snap, out = _make_snapshot_outcome()
        bridge.record_evidence(_make_derive_result(["C1"]), snap, out)
        assert not (tmp_path / "override.json").exists()


class TestBuildMaskAppliesOverride:
    """build_factor_head_mask: 读 override → wrong_dim head 行允许值 → log(m)。"""

    def _build(self, override_path=None):
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            build_factor_head_mask,
        )
        return build_factor_head_mask(override_path=override_path)

    def test_no_override_keeps_zero_allow(self, tmp_path):
        mask = self._build(str(tmp_path / "missing.json"))
        allow_vals = mask[mask > float("-inf")]
        assert (allow_vals == 0.0).all()

    def test_override_maps_to_log_bias(self, tmp_path):
        override = tmp_path / "override.json"
        override.write_text(json.dumps({"C1": 0.8}))
        mask = self._build(str(override))
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            get_factor_dimensions,
        )
        dims = get_factor_dimensions()
        c1_idx = dims.index("C1")
        # C1 head 行: 允许值 = log(0.8)
        c1_allow = mask[c1_idx][mask[c1_idx] > float("-inf")]
        assert c1_allow.numel() > 0
        assert c1_allow.eq(math.log(0.8)).all()
        # 其他 head 行: 允许值仍为 0.0
        other_idx = dims.index("C2")
        other_allow = mask[other_idx][mask[other_idx] > float("-inf")]
        assert other_allow.eq(0.0).all()
        # 屏蔽值不变
        assert (mask == float("-inf")).any()

    def test_corrupt_override_fail_open(self, tmp_path):
        override = tmp_path / "override.json"
        override.write_text("not json at all")
        mask = self._build(str(override))  # 不崩，回退原 mask
        allow_vals = mask[mask > float("-inf")]
        assert (allow_vals == 0.0).all()
