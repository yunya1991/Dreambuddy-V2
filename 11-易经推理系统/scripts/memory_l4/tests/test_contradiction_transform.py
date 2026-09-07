"""TC13/TC16/TC17: 矛盾转化检测器测试。

验证 6 类转化条件监控 + S3/S4 引擎集成 + FAIL-OPEN。
对应 Spec §三-A Step 3-A-2 ContradictionTransform。

6 类转化条件：
  1. elasticity_decay        弹性衰减（elasticity_beta.decay_signal）
  2. elasticity_amplification 弹性放大（elasticity_beta.amplification_signal）
  3. dominant_shift          维度主导切换（rank_shift）
  4. resonance_break         共振破裂（resonance_break）
  5. cbr_divergence          CBR背离（cbr_divergence）
  6. data_quality_warning    数据质量预警（s3_pass_rate<0.7 持续3天）

置信度 = 触发条件数 / 6
S4辅助：crr>0.3或mr<0.5时，已触发条件置信度权重 ×1.2（不增加触发数）
transforming = 触发条件数>=2 或 data_quality_warning触发 或 (S4佐证 且 触发条件数>=1)
"""
import pytest
import sys
from pathlib import Path

# 将 memory_l4 注入 sys.path，使 force_vector.* 可导入
_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))

from force_vector.contradiction_transform_detector import ContradictionTransformDetector
from force_vector.models import ContradictionTransform, ElasticityBeta


def _make_beta(decay: bool = False, amplification: bool = False) -> ElasticityBeta:
    """构造一个中性弹性系数β，按需打开衰减/放大信号。"""
    return ElasticityBeta(
        beta_7d=1.0,
        beta_30d=1.0,
        beta_ratio=1.0,
        decay_signal=decay,
        amplification_signal=amplification,
        decay_days=3 if decay else 0,
        amplification_days=3 if amplification else 0,
    )


class TestContradictionTransformMultiCondition:
    """TC13: 3 个转化条件同时触发。"""

    def test_three_conditions_triggered_transforming_true_confidence_half(self):
        """decay_signal=True + rank_shift=True + resonance_break=True
        → transforming=True, confidence≈0.50(3/6)。
        """
        det = ContradictionTransformDetector()
        beta = _make_beta(decay=True)
        result = det.detect(
            elasticity_beta=beta,
            rank_shift=True,
            resonance_break=True,
        )

        assert isinstance(result, ContradictionTransform)
        # 三个条件触发 → transforming
        assert result.transforming is True
        # 置信度 = 3/6 ≈ 0.50（无 S4 佐证，不放大）
        assert result.confidence == pytest.approx(0.50, rel=1e-6)
        # 三个触发条件均在列表中
        assert "elasticity_decay" in result.trigger_conditions
        assert "dominant_shift" in result.trigger_conditions
        assert "resonance_break" in result.trigger_conditions
        assert len(result.trigger_conditions) == 3
        # 数据质量因子正常（未触发预警）
        assert result.data_quality_factor == pytest.approx(1.0)

    def test_no_condition_triggered_returns_none_type(self):
        """无任何条件触发 → transforming=False, transform_type='none', confidence=0.0。"""
        det = ContradictionTransformDetector()
        beta = _make_beta()
        result = det.detect(elasticity_beta=beta)

        assert result.transforming is False
        assert result.transform_type == "none"
        assert result.confidence == pytest.approx(0.0)
        assert result.trigger_conditions == []
        assert result.data_quality_factor == pytest.approx(1.0)


class TestContradictionTransformDataQualityWarning:
    """TC16: S3 数据质量预警。"""

    def test_data_quality_warning_when_s3_low_3_days(self):
        """s3_pass_rate=0.6, s3_low_days=3 → data_quality_warning, factor=0.7。"""
        det = ContradictionTransformDetector()
        beta = _make_beta()
        result = det.detect(
            elasticity_beta=beta,
            s3_pass_rate=0.6,
            s3_low_days=3,
        )

        assert result.transform_type == "data_quality_warning"
        assert result.data_quality_factor == pytest.approx(0.7)
        # 数据质量预警触发 → transforming
        assert result.transforming is True
        assert "data_quality_warning" in result.trigger_conditions

    def test_data_quality_warning_not_triggered_when_low_days_below_threshold(self):
        """s3_pass_rate=0.6 但 s3_low_days=2（不足3天）→ 不触发预警，factor=1.0。"""
        det = ContradictionTransformDetector()
        beta = _make_beta()
        result = det.detect(
            elasticity_beta=beta,
            s3_pass_rate=0.6,
            s3_low_days=2,
        )

        assert "data_quality_warning" not in result.trigger_conditions
        assert result.data_quality_factor == pytest.approx(1.0)
        assert result.transform_type == "none"

    def test_data_quality_warning_not_triggered_when_pass_rate_ok(self):
        """s3_pass_rate=0.9（正常）即使 low_days=3 也不触发预警。"""
        det = ContradictionTransformDetector()
        beta = _make_beta()
        result = det.detect(
            elasticity_beta=beta,
            s3_pass_rate=0.9,
            s3_low_days=3,
        )

        assert "data_quality_warning" not in result.trigger_conditions
        assert result.data_quality_factor == pytest.approx(1.0)


class TestContradictionTransformS4Aux:
    """TC17: S4 辅助佐证提升置信度。"""

    def test_s4_crr_boosts_confidence_and_transforming(self):
        """crr=0.4 + rank_shift=True → transforming=True，置信度比无 crr 时更高。

        无 crr：仅 rank_shift 触发1条件 → confidence=1/6≈0.1667, transforming=False
        有 crr=0.4(>0.3)：S4 佐证 → confidence=1/6×1.2=0.20, transforming=True
        """
        det = ContradictionTransformDetector()
        beta = _make_beta()

        # 无 crr：仅 rank_shift 触发 1 条件
        result_no_crr = det.detect(
            elasticity_beta=beta,
            rank_shift=True,
            s4_crr=0.0,
            s4_mr=1.0,
        )
        # 有 crr=0.4：S4 辅助佐证
        result_with_crr = det.detect(
            elasticity_beta=beta,
            rank_shift=True,
            s4_crr=0.4,
            s4_mr=1.0,
        )

        # crr=0.4 时 transforming=True（S4 佐证 + 1 条件）
        assert result_with_crr.transforming is True
        # 无 crr 时仅1条件、无 S4 佐证 → transforming=False
        assert result_no_crr.transforming is False
        # 置信度有 ×1.2 提升，比无 crr 时更高
        assert result_with_crr.confidence > result_no_crr.confidence
        # 触发数不增加（仍为1）
        assert len(result_with_crr.trigger_conditions) == 1
        assert len(result_no_crr.trigger_conditions) == 1

    def test_s4_low_mr_boosts_confidence(self):
        """mr=0.4(<0.5) 同样触发 S4 佐证 → 置信度提升。"""
        det = ContradictionTransformDetector()
        beta = _make_beta()

        result_normal = det.detect(
            elasticity_beta=beta,
            resonance_break=True,
            s4_crr=0.0,
            s4_mr=1.0,
        )
        result_low_mr = det.detect(
            elasticity_beta=beta,
            resonance_break=True,
            s4_crr=0.0,
            s4_mr=0.4,
        )

        assert result_low_mr.confidence > result_normal.confidence
        # S4 佐证不增加触发数
        assert len(result_low_mr.trigger_conditions) == 1

    def test_s4_aux_confidence_capped_at_one(self):
        """6 条件全触发 + S4 佐证 → 置信度封顶 1.0（不超过1.2）。"""
        det = ContradictionTransformDetector()
        beta = _make_beta(decay=True, amplification=True)
        result = det.detect(
            elasticity_beta=beta,
            rank_shift=True,
            resonance_break=True,
            cbr_divergence=True,
            s3_pass_rate=0.6,
            s3_low_days=3,
            s4_crr=0.4,
            s4_mr=0.4,
        )
        # 6 条件全触发
        assert len(result.trigger_conditions) == 6
        # 置信度封顶 1.0
        assert result.confidence == pytest.approx(1.0)
        assert result.transforming is True


class TestContradictionTransformFetchS3:
    """S3 news_contract_validator 集成 + FAIL-OPEN。"""

    def test_fetch_s3_pass_rate_returns_float_for_valid_list(self):
        """合法 news_list → 返回 [0,1] 内的 float。"""
        det = ContradictionTransformDetector()
        news = [
            {"title": "BTC大涨", "content": "突破新高", "event_type": "price_up"},
        ]
        rate = det.fetch_s3_pass_rate(news)
        assert isinstance(rate, float)
        assert 0.0 <= rate <= 1.0

    def test_fetch_s3_pass_rate_failopen_on_exception(self, monkeypatch):
        """validate_batch 抛异常 → FAIL-OPEN 返回 0.8（中性）。"""
        det = ContradictionTransformDetector()
        import engines.news_contract_validator as ncv  # noqa: E402

        def _raise(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(ncv, "validate_batch", _raise)
        rate = det.fetch_s3_pass_rate([{"title": "x"}])
        assert rate == pytest.approx(0.8)


class TestContradictionTransformFetchS4:
    """S4 event_mapping_engine 集成 + FAIL-OPEN。"""

    def test_fetch_s4_crr_mr_returns_tuple_for_valid_list(self):
        """合法 news_list → 返回 (crr, mr) 元组，crr∈[0,1], mr∈[0,1]。"""
        det = ContradictionTransformDetector()
        news = [
            {"title": "美联储加息", "content": "加息25bp", "event_type": "rate_hike"},
            {"title": "就业数据", "content": "非农强劲", "event_type": "employment"},
        ]
        crr, mr = det.fetch_s4_crr_mr(news)
        assert isinstance(crr, float)
        assert isinstance(mr, float)
        assert 0.0 <= crr <= 1.0
        assert 0.0 <= mr <= 1.0

    def test_fetch_s4_crr_mr_failopen_on_none_input(self):
        """news_list=None（不可迭代）→ FAIL-OPEN 返回 (0.0, 1.0)。"""
        det = ContradictionTransformDetector()
        crr, mr = det.fetch_s4_crr_mr(None)
        assert crr == pytest.approx(0.0)
        assert mr == pytest.approx(1.0)


class TestContradictionTransformFailOpen:
    """detect() 异常时 FAIL-OPEN 返回中性结果。"""

    def test_detect_with_none_beta_returns_neutral(self):
        """elasticity_beta=None → FAIL-OPEN 不崩，返回 transforming=False。"""
        det = ContradictionTransformDetector()
        result = det.detect(elasticity_beta=None)
        assert isinstance(result, ContradictionTransform)
        assert result.transforming is False
        assert result.transform_type == "none"
        assert result.confidence == pytest.approx(0.0)
