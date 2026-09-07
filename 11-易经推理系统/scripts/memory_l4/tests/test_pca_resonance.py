"""TC8: PCA 五维共振分析 + 排名一致性测试。

验证 PCAResonanceAnalyzer.compute_resonance / compute_rank_stability /
detect_top1_shift 三个方法，以及 FAIL-OPEN 中性默认。
对应 Spec §三 Step 4-B（PCA 共振定强度）。
"""
import pytest
import sys
from pathlib import Path

# 将 memory_l4 加入 sys.path（force_vector 包所在目录）
_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))

from force_vector.models import PCAResonance
from force_vector.pca_resonance_analyzer import PCAResonanceAnalyzer


class TestComputeResonance:
    """TC8: PCA 共振分析（定强度）。"""

    def test_full_resonance_all_same_direction(self):
        """五维同向（全正）→ sign_alignment=1.0 → strength_coefficient=1.3。

        全共振不触发 explained_ratio<0.3 的退化惩罚。
        """
        analyzer = PCAResonanceAnalyzer()
        powers = {
            "dao": 0.5, "tian": 0.3, "di": 0.4, "jiang": 0.35, "fa": 0.1,
        }
        result = analyzer.compute_resonance(powers, dominant_dim="dao")
        assert isinstance(result, PCAResonance)
        assert result.dominant_dimension == "dao"
        # 五维同向 → sign_alignment=1.0 → 全共振
        assert result.sign_alignment == pytest.approx(1.0, abs=1e-6)
        assert result.alignment == "full_resonance"
        # 全共振 → ×1.3，且 explained_ratio 不低于 0.3（不触发退化惩罚）
        assert result.strength_coefficient == pytest.approx(1.3, abs=1e-6)
        assert 0.0 <= result.explained_ratio <= 1.0

    def test_full_resonance_all_negative(self):
        """五维同向（全负）→ sign_alignment=1.0 → strength_coefficient=1.3。"""
        analyzer = PCAResonanceAnalyzer()
        powers = {
            "dao": -0.5, "tian": -0.3, "di": -0.4, "jiang": -0.35, "fa": -0.1,
        }
        result = analyzer.compute_resonance(powers, dominant_dim="dao")
        assert result.sign_alignment == pytest.approx(1.0, abs=1e-6)
        assert result.alignment == "full_resonance"
        assert result.strength_coefficient == pytest.approx(1.3, abs=1e-6)

    def test_strong_resonance_three_of_four_aligned(self):
        """其他四维中3个同向 → sign_alignment=0.75 → 强共振 → ×1.2。"""
        analyzer = PCAResonanceAnalyzer()
        powers = {
            "dao": 0.5, "tian": 0.3, "di": 0.4, "jiang": 0.35, "fa": -0.1,
        }
        result = analyzer.compute_resonance(powers, dominant_dim="dao")
        assert result.sign_alignment == pytest.approx(0.75, abs=1e-6)
        assert result.alignment == "strong_resonance"
        assert result.strength_coefficient == pytest.approx(1.2, abs=1e-6)

    def test_conflict_majority_opposite(self):
        """多数反向（4 维中 3 个反向）→ 冲突 → strength_coefficient<=0.5。"""
        analyzer = PCAResonanceAnalyzer()
        powers = {
            "dao": 0.5, "tian": -0.3, "di": -0.4, "jiang": -0.35, "fa": 0.1,
        }
        result = analyzer.compute_resonance(powers, dominant_dim="dao")
        # 主导 dao 为正；其余 4 维 3 负 1 正 → sign_alignment=0.25
        assert result.sign_alignment == pytest.approx(0.25, abs=1e-6)
        assert result.alignment == "conflict"
        assert result.strength_coefficient <= 0.5

    def test_full_conflict_all_opposite(self):
        """其他四维全部与主导反向 → sign_alignment=0.0 → 全冲突 → ×0.3。"""
        analyzer = PCAResonanceAnalyzer()
        powers = {
            "dao": 0.5, "tian": -0.3, "di": -0.4, "jiang": -0.35, "fa": -0.1,
        }
        result = analyzer.compute_resonance(powers, dominant_dim="dao")
        assert result.sign_alignment == pytest.approx(0.0, abs=1e-6)
        assert result.alignment == "full_conflict"
        assert result.strength_coefficient == pytest.approx(0.3, abs=1e-6)

    def test_half_alignment_boundary_is_conflict(self):
        """其他四维中2个同向 → sign_alignment=0.5（边界）→ 冲突 → ×0.5。

        严格弱共振区间为 (0.5, 0.75)；离散 4 维计数下 0.5 落在冲突侧。
        """
        analyzer = PCAResonanceAnalyzer()
        powers = {
            "dao": 0.5, "tian": 0.3, "di": 0.4, "jiang": -0.35, "fa": -0.1,
        }
        result = analyzer.compute_resonance(powers, dominant_dim="dao")
        # 主导 dao 正；其余 2 正(tian,di) 2 负(jiang,fa) → sign_alignment=0.5
        assert result.sign_alignment == pytest.approx(0.5, abs=1e-6)
        assert result.alignment == "conflict"
        assert result.strength_coefficient == pytest.approx(0.5, abs=1e-6)


class TestRankStability:
    """TC8: 排名一致性检测（Spearman 秩相关）。"""

    def test_identical_ranks_high_stability(self):
        """连续2天排名完全一致 → Spearman=1.0 → stability>0.8。"""
        analyzer = PCAResonanceAnalyzer()
        ranks_t_prev = [1, 2, 3, 4, 5]
        ranks_t = [1, 2, 3, 4, 5]
        stab = analyzer.compute_rank_stability(ranks_t, ranks_t_prev)
        assert 0.0 <= stab <= 1.0
        assert stab > 0.8

    def test_slightly_perturbed_still_high(self):
        """轻微扰动（末两位互换）→ Spearman 仍 >0.8。"""
        analyzer = PCAResonanceAnalyzer()
        ranks_t_prev = [1, 2, 3, 4, 5]
        ranks_t = [1, 2, 3, 5, 4]
        stab = analyzer.compute_rank_stability(ranks_t, ranks_t_prev)
        assert stab > 0.8

    def test_failopen_on_bad_input(self):
        """异常输入（长度不一致/空）→ 返回中性默认 0.5。"""
        analyzer = PCAResonanceAnalyzer()
        assert analyzer.compute_rank_stability([], [1, 2, 3]) == pytest.approx(0.5, abs=1e-6)
        assert analyzer.compute_rank_stability([1], [1]) == pytest.approx(0.5, abs=1e-6)


class TestTop1Shift:
    """TC8: top-1 特征切换检测。"""

    def test_top1_unchanged_no_shift(self):
        """排名完全一致 → top-1 未切换 → False。"""
        analyzer = PCAResonanceAnalyzer()
        ranks_t_prev = [1, 2, 3, 4, 5]
        ranks_t = [1, 2, 3, 4, 5]
        assert analyzer.detect_top1_shift(ranks_t, ranks_t_prev) is False

    def test_top1_switched(self):
        """top-1 特征切换（rank=1 从 idx0 变 idx1）→ True。"""
        analyzer = PCAResonanceAnalyzer()
        ranks_t_prev = [1, 2, 3, 4, 5]   # feature 0 是 top-1
        ranks_t = [2, 1, 3, 4, 5]        # feature 1 变为 top-1
        assert analyzer.detect_top1_shift(ranks_t, ranks_t_prev) is True

    def test_top1_unchanged_when_only_lower_ranks_shuffle(self):
        """仅末位排名变化、top-1 不变 → False。"""
        analyzer = PCAResonanceAnalyzer()
        ranks_t_prev = [1, 2, 3, 4, 5]
        ranks_t = [1, 2, 3, 5, 4]
        assert analyzer.detect_top1_shift(ranks_t, ranks_t_prev) is False
