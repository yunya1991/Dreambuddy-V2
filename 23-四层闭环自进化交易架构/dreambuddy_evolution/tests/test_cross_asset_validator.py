"""
P1-5 RED 测试集 — 跨资产验证器

P1-5: 影子验证不只在 BTC，扩展到 ETH/SOL 等
  - 对多个资产分别跑 check_promotion_with_stats
  - 至少 2 个资产通过才认为基因鲁棒（跨资产通过）
  - 返回跨资产验证报告

参考: architecture-evaluation-23.md P1 改进建议 #5
      dream-science-hypothesis-verification SKILL（鲁棒性验证章节）
"""
from __future__ import annotations

import pytest


# --------------------------------------------------------------------------------
# RED: 模块尚未创建
# --------------------------------------------------------------------------------
def test_module_importable():
    from dreambuddy_evolution.core.cross_asset_validator import (  # noqa: F401
        CrossAssetValidator,
    )


class TestCrossAssetValidator:
    def _strong(self, n=30):
        return [{"pnl_pct": 0.03}] * 22 + [{"pnl_pct": -0.005}] * 8

    def _weak(self, n=30):
        return [{"pnl_pct": 0.01}] * 15 + [{"pnl_pct": -0.01}] * 15

    def test_validate_accepts_dict_of_asset_samples(self):
        """validate 接受 {symbol: samples} 字典."""
        from dreambuddy_evolution.core.cross_asset_validator import CrossAssetValidator
        v = CrossAssetValidator()
        result = v.validate({
            "BTC": self._strong(30),
            "ETH": self._strong(30),
            "SOL": self._strong(30),
        })
        assert "cross_asset_pass" in result
        assert "per_asset" in result
        assert "n_assets_pass" in result

    def test_all_assets_pass_when_strong(self):
        """3 个资产全部强信号 → cross_asset_pass=True."""
        from dreambuddy_evolution.core.cross_asset_validator import CrossAssetValidator
        v = CrossAssetValidator()
        result = v.validate({
            "BTC": self._strong(30),
            "ETH": self._strong(30),
            "SOL": self._strong(30),
        })
        assert result["n_assets_pass"] == 3
        assert result["cross_asset_pass"] is True

    def test_fails_when_only_one_asset_passes(self):
        """只 1 个资产通过 → cross_asset_pass=False（默认需 ≥2）."""
        from dreambuddy_evolution.core.cross_asset_validator import CrossAssetValidator
        v = CrossAssetValidator()
        result = v.validate({
            "BTC": self._strong(30),
            "ETH": self._weak(30),
            "SOL": self._weak(30),
        })
        assert result["n_assets_pass"] == 1
        assert result["cross_asset_pass"] is False

    def test_passes_with_two_assets(self):
        """2 个资产通过 → cross_asset_pass=True（默认阈值 min_assets_pass=2）."""
        from dreambuddy_evolution.core.cross_asset_validator import CrossAssetValidator
        v = CrossAssetValidator()
        result = v.validate({
            "BTC": self._strong(30),
            "ETH": self._strong(30),
            "SOL": self._weak(30),
        })
        assert result["n_assets_pass"] == 2
        assert result["cross_asset_pass"] is True

    def test_min_assets_pass_threshold_configurable(self):
        """min_assets_pass 参数可调."""
        from dreambuddy_evolution.core.cross_asset_validator import CrossAssetValidator
        v = CrossAssetValidator()
        result = v.validate(
            {"BTC": self._strong(30), "ETH": self._strong(30)},
            min_assets_pass=2,
        )
        assert result["cross_asset_pass"] is True
        result2 = v.validate(
            {"BTC": self._strong(30), "ETH": self._strong(30)},
            min_assets_pass=3,
        )
        assert result2["cross_asset_pass"] is False

    def test_per_asset_includes_full_stats(self):
        """每个资产结果应包含完整统计（p_value/effect_size/ci/win_rate/promote）."""
        from dreambuddy_evolution.core.cross_asset_validator import CrossAssetValidator
        v = CrossAssetValidator()
        result = v.validate({"BTC": self._strong(30)})
        btc = result["per_asset"]["BTC"]
        for key in ("promote", "p_value", "effect_size", "ci_lower", "ci_upper", "win_rate"):
            assert key in btc, f"per_asset.BTC 缺少字段: {key}"

    def test_fail_open_on_empty_dict(self):
        """空资产字典应 FAIL-OPEN 返回 cross_asset_pass=False."""
        from dreambuddy_evolution.core.cross_asset_validator import CrossAssetValidator
        v = CrossAssetValidator()
        result = v.validate({})
        assert result["cross_asset_pass"] is False
        assert result["n_assets_pass"] == 0

    def test_skips_assets_with_insufficient_samples(self):
        """样本不足的资产标记为 skipped 不计入 pass."""
        from dreambuddy_evolution.core.cross_asset_validator import CrossAssetValidator
        v = CrossAssetValidator()
        result = v.validate({
            "BTC": self._strong(30),
            "ETH": [{"pnl_pct": 0.05}] * 10,  # 不足 N≥30
        })
        assert result["n_assets_pass"] == 1
        assert result["per_asset"]["ETH"].get("promote") is False
