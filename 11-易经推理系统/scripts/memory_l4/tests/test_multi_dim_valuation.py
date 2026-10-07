"""TDD-SVC-002: 多维度相对估值（Multi-dim Valuation）测试 — TDD 先红后绿。

验证 multi_dim_valuation.py：
  - compute_multi_dim_score_from_percentiles(pcts, weights) -> Dict[str, float]
    纯函数：从各维度百分位合成分数
  - compute_multi_dim_valuation(coin, db_path) -> Dict[str, float]
    主函数：获取数据 + 调用纯函数

维度（SPEC §4.4）：
  - MC/Fees: 0.5（主维度，复用 E8 逻辑）
  - MC/TVL: 0.3（DeFi 专用，反映资本效率）
  - PEG 调整: 0.2（增长调整，高增长可承受高估值）

合成公式（SPEC §3.2 指标 2）：
  multi_dim_score = 1.0 - (weighted_pct / 50.0)
    映射到 [-1, +1]，与 E8 一致
  score > 0.3：多维低估
  score < -0.3：多维高估

铁律（SPEC §0.2）：
  R3 多维交叉验证：低估判断需至少 2 个维度同时 < 40 百分位才确认
  R4 FAIL-OPEN：数据不足不触发信号

权重归一化（SPEC §7.2 FAIL-OPEN）：
  缺数据维度权重置 0，剩余维度权重归一化
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import patch

# 将 force_vector 加入 sys.path
_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))


def _import_multi_dim():
    """辅助：延迟导入 multi_dim_valuation 模块。"""
    from force_vector.multi_dim_valuation import (
        compute_multi_dim_score_from_percentiles,
        compute_multi_dim_valuation,
    )
    return compute_multi_dim_score_from_percentiles, compute_multi_dim_valuation


# ---------------------------------------------------------------------------
# 纯函数测试：compute_multi_dim_score_from_percentiles
# ---------------------------------------------------------------------------

class TestMultiDimScoreImport:
    """RED: 模块与符号必须可导入。"""

    def test_module_importable(self):
        from force_vector.multi_dim_valuation import (
            compute_multi_dim_score_from_percentiles,
            compute_multi_dim_valuation,
        )
        assert callable(compute_multi_dim_score_from_percentiles)
        assert callable(compute_multi_dim_valuation)


class TestMultiDimScoreFromPercentiles:
    """纯函数：从各维度百分位合成分数。"""

    def test_all_dimensions_low_undervalued(self):
        """三维度都低 [20, 25, 30] → score > 0.3，confirmed_low=True。

        SPEC §8.1: 三维度百分位 [20, 25, 30]，权重 [0.5, 0.3, 0.2] → score ≈ +0.52
        """
        compute_pure, _ = _import_multi_dim()
        result = compute_pure(
            pcts={"mc_fees": 20.0, "mc_tvl": 25.0, "peg": 30.0},
            weights={"mc_fees": 0.5, "mc_tvl": 0.3, "peg": 0.2},
        )
        # weighted_pct = 0.5*20 + 0.3*25 + 0.2*30 = 10 + 7.5 + 6 = 23.5
        # score = 1.0 - 23.5/50 = 0.53
        assert result["multi_dim_score"] == pytest.approx(0.53, abs=0.05)
        assert result["multi_dim_score"] > 0.3  # 多维低估
        assert result["confirmed_low"] is True  # 3 维都 < 40
        assert result["dimensions_available"] == 3
        assert result["mc_fees_pct"] == 20.0
        assert result["mc_tvl_pct"] == 25.0
        assert result["peg_pct"] == 30.0

    def test_single_dimension_undervalued(self):
        """单维度可用（仅 MC/Fees=20）→ score = +0.6，confirmed_low=False。

        SPEC §8.1: 单维度可用（仅 MC/Fees=20）→ score = +0.6
        权重归一化：缺数据维度权重置 0，剩余维度权重归一化到 1.0
        """
        compute_pure, _ = _import_multi_dim()
        result = compute_pure(
            pcts={"mc_fees": 20.0},  # 仅 MC/Fees 可用
            weights={"mc_fees": 0.5, "mc_tvl": 0.3, "peg": 0.2},
        )
        # 权重归一化：mc_fees 从 0.5 → 1.0
        # weighted_pct = 1.0 * 20 = 20
        # score = 1.0 - 20/50 = 0.6
        assert result["multi_dim_score"] == pytest.approx(0.6, abs=0.05)
        assert result["confirmed_low"] is False  # 只有 1 维 < 40，不满足 R3
        assert result["dimensions_available"] == 1

    def test_all_dimensions_missing_returns_zero(self):
        """全部维度缺失 → score = 0.0（FAIL-OPEN 中性）。

        SPEC §8.1: 全部维度缺失 → score = 0.0
        """
        compute_pure, _ = _import_multi_dim()
        result = compute_pure(
            pcts={},  # 无任何维度数据
            weights={"mc_fees": 0.5, "mc_tvl": 0.3, "peg": 0.2},
        )
        assert result["multi_dim_score"] == 0.0
        assert result["confirmed_low"] is False
        assert result["dimensions_available"] == 0

    def test_high_valuation_negative_score(self):
        """三维度都高 [80, 85, 90] → score < -0.3（多维高估）。

        weighted_pct = 0.5*80 + 0.3*85 + 0.2*90 = 40 + 25.5 + 18 = 83.5
        score = 1.0 - 83.5/50 = 1.0 - 1.67 = -0.67
        """
        compute_pure, _ = _import_multi_dim()
        result = compute_pure(
            pcts={"mc_fees": 80.0, "mc_tvl": 85.0, "peg": 90.0},
            weights={"mc_fees": 0.5, "mc_tvl": 0.3, "peg": 0.2},
        )
        assert result["multi_dim_score"] < -0.3  # 多维高估
        assert result["multi_dim_score"] == pytest.approx(-0.67, abs=0.05)
        assert result["confirmed_low"] is False

    def test_requires_two_dimensions_for_confirmation(self):
        """R3: score > 0.3 需 ≥2 维度 < 40 百分位才确认低估。

        场景：MC/Fees=20（低）+ MC/TVL=70（高）+ PEG=70（高）
        weighted_pct = 0.5*20 + 0.3*70 + 0.2*70 = 10 + 21 + 14 = 45
        score = 1.0 - 45/50 = 0.1 → 不 > 0.3，confirmed_low=False（仅 1 维 < 40）
        """
        compute_pure, _ = _import_multi_dim()
        result = compute_pure(
            pcts={"mc_fees": 20.0, "mc_tvl": 70.0, "peg": 70.0},
            weights={"mc_fees": 0.5, "mc_tvl": 0.3, "peg": 0.2},
        )
        assert result["multi_dim_score"] == pytest.approx(0.1, abs=0.05)
        assert not (result["multi_dim_score"] > 0.3)  # 不满足低估阈值
        assert result["confirmed_low"] is False  # 仅 1 维 < 40

    def test_two_low_dimensions_confirms_low(self):
        """R3: 2 维度 < 40 百分位 → confirmed_low=True。

        场景：MC/Fees=20 + MC/TVL=25（都低）+ PEG=70（高）
        weighted_pct = 0.5*20 + 0.3*25 + 0.2*70 = 10 + 7.5 + 14 = 31.5
        score = 1.0 - 31.5/50 = 0.37 → > 0.3，confirmed_low=True（2 维 < 40）
        """
        compute_pure, _ = _import_multi_dim()
        result = compute_pure(
            pcts={"mc_fees": 20.0, "mc_tvl": 25.0, "peg": 70.0},
            weights={"mc_fees": 0.5, "mc_tvl": 0.3, "peg": 0.2},
        )
        assert result["multi_dim_score"] == pytest.approx(0.37, abs=0.05)
        assert result["multi_dim_score"] > 0.3
        assert result["confirmed_low"] is True  # 2 维 < 40

    def test_score_clamped_to_range(self):
        """multi_dim_score 必须在 [-1, +1] 范围内。"""
        compute_pure, _ = _import_multi_dim()
        # 极端低估：所有维度 0
        result = compute_pure(
            pcts={"mc_fees": 0.0, "mc_tvl": 0.0, "peg": 0.0},
            weights={"mc_fees": 0.5, "mc_tvl": 0.3, "peg": 0.2},
        )
        assert result["multi_dim_score"] == 1.0  # 满量程低估
        assert -1.0 <= result["multi_dim_score"] <= 1.0

        # 极端高估：所有维度 100
        result = compute_pure(
            pcts={"mc_fees": 100.0, "mc_tvl": 100.0, "peg": 100.0},
            weights={"mc_fees": 0.5, "mc_tvl": 0.3, "peg": 0.2},
        )
        assert result["multi_dim_score"] == -1.0  # 满量程高估
        assert -1.0 <= result["multi_dim_score"] <= 1.0

    def test_default_weights_when_none(self):
        """weights=None 时使用默认权重 [0.5, 0.3, 0.2]。"""
        compute_pure, _ = _import_multi_dim()
        result = compute_pure(
            pcts={"mc_fees": 20.0, "mc_tvl": 30.0, "peg": 40.0},
            weights=None,  # 使用默认
        )
        # 默认权重 0.5/0.3/0.2
        # weighted_pct = 0.5*20 + 0.3*30 + 0.2*40 = 10 + 9 + 8 = 27
        # score = 1.0 - 27/50 = 0.46
        assert result["multi_dim_score"] == pytest.approx(0.46, abs=0.05)


# ---------------------------------------------------------------------------
# 主函数测试：compute_multi_dim_valuation（集成）
# ---------------------------------------------------------------------------

class TestComputeMultiDimValuation:
    """主函数：从 DB 获取数据 + 调用纯函数。"""

    def test_returns_dict_with_required_keys(self):
        """返回 dict 包含必需字段：multi_dim_score, confirmed_low 等。"""
        _, compute_fn = _import_multi_dim()
        # mock 数据获取函数，让赛道内百分位计算可预测
        with patch(
            "force_vector.multi_dim_valuation._fetch_dimension_percentiles",
            return_value={"mc_fees": 20.0, "mc_tvl": 25.0, "peg": 30.0},
        ):
            result = compute_fn("UNI", "/fake/db.db")
        required_keys = {"multi_dim_score", "confirmed_low", "dimensions_available"}
        assert required_keys.issubset(result.keys())
        assert result["multi_dim_score"] > 0.3
        assert result["confirmed_low"] is True

    def test_returns_neutral_when_data_missing(self):
        """数据缺失 → multi_dim_score = 0.0（FAIL-OPEN）。"""
        _, compute_fn = _import_multi_dim()
        with patch(
            "force_vector.multi_dim_valuation._fetch_dimension_percentiles",
            return_value={},  # 无任何维度数据
        ):
            result = compute_fn("UNKNOWN", "/fake/db.db")
        assert result["multi_dim_score"] == 0.0
        assert result["confirmed_low"] is False

    def test_returns_neutral_for_unknown_coin(self):
        """未知币（不在赛道）→ multi_dim_score = 0.0。"""
        _, compute_fn = _import_multi_dim()
        result = compute_fn("UNKNOWNCOIN", "/fake/db.db")
        assert result["multi_dim_score"] == 0.0
