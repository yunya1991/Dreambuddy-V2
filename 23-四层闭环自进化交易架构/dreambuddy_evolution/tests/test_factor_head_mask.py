"""
M3 RED: build_factor_head_mask 维度对齐 mask 构建测试

验证 mask 从 CROSS_ATTENTION_FACTOR_METRICS 的维度元数据构建，
而非硬编码索引范围。
"""
from __future__ import annotations

import pytest
import torch


class TestBuildFactorHeadMask:
    """测试维度对齐 mask 构建。"""

    def test_function_exists(self):
        """build_factor_head_mask 函数可导入。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            build_factor_head_mask,
        )  # noqa: F401

    def test_mask_shape(self):
        """mask 形状为 (n_dimensions, n_factors)。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            CROSS_ATTENTION_FACTOR_METRICS,
            build_factor_head_mask,
        )

        mask = build_factor_head_mask()
        n_factors = len(CROSS_ATTENTION_FACTOR_METRICS)
        # 维度数 = unique dimensions in order
        dims = []
        for entry in CROSS_ATTENTION_FACTOR_METRICS:
            d = entry[3] if len(entry) > 3 else None
            if d and d not in dims:
                dims.append(d)
        n_dims = len(dims)
        assert mask.shape == (n_dims, n_factors)

    def test_mask_values(self):
        """mask 中 0=允许注意力，-inf=屏蔽。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            build_factor_head_mask,
        )

        mask = build_factor_head_mask()
        # 只包含 0 和 -inf
        zeros = (mask == 0.0)
        neg_inf = torch.isneginf(mask)
        assert (zeros | neg_inf).all()

    def test_each_factor_unmasked_in_exactly_one_head(self):
        """每个因子在恰好一个 head 中未被屏蔽。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            CROSS_ATTENTION_FACTOR_METRICS,
            build_factor_head_mask,
        )

        mask = build_factor_head_mask()
        n_factors = len(CROSS_ATTENTION_FACTOR_METRICS)
        for f in range(n_factors):
            n_unmasked = (mask[:, f] == 0.0).sum().item()
            assert n_unmasked == 1, f"因子 {f} 在 {n_unmasked} 个 head 中未屏蔽，应为 1"

    def test_dimension_assignment_matches_tuple(self):
        """mask 的维度分配与 CROSS_ATTENTION_FACTOR_METRICS 元数据一致。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            CROSS_ATTENTION_FACTOR_METRICS,
            build_factor_head_mask,
        )

        mask = build_factor_head_mask()
        dims = []
        for entry in CROSS_ATTENTION_FACTOR_METRICS:
            d = entry[3] if len(entry) > 3 else None
            if d and d not in dims:
                dims.append(d)

        for f_idx, entry in enumerate(CROSS_ATTENTION_FACTOR_METRICS):
            dim = entry[3] if len(entry) > 3 else None
            head_idx = dims.index(dim)
            # 该因子在其所属维度的 head 中应未被屏蔽
            assert mask[head_idx, f_idx] == 0.0
            # 在其他 head 中应被屏蔽
            for h in range(len(dims)):
                if h != head_idx:
                    assert torch.isneginf(mask[h, f_idx])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
