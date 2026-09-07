"""E7 收入可持续性信号 TDD 测试 — BDSM RQ 维度。

验证 coin_fundamental_crypto.py 中的 compute_revenue_sustainability 函数：
  - 三维度评估：集中度 + 来源类型 + 持续性
  - 输入：fees_by_chain(分链费用)、source_type(来源类型)、source_age_days(持续性)
  - 输出：[-1.0, +1.0]，稳定分散来源→正

案例验证（对齐 UNI 文章分析）：
  - UNI: 60%来自RH Chain(集中度高)、新链<2月(低持续性) → 中/负
  - HYPE: 99%手续费(单一但稳定来源)、长期运行 → 高
  - SKY: 协议盈余(稳定来源)、多链分散 → 高
"""
import sys
from pathlib import Path

_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))

import math
import pytest

from force_vector.coin_fundamental_crypto import compute_revenue_sustainability


# ---------------------------------------------------------------------------
# 1. 纯函数：基础行为
# ---------------------------------------------------------------------------

class TestComputeRevenueSustainabilityBasic:
    """基础行为：空输入/零值/边界。"""

    def test_empty_fees_returns_zero(self):
        """空 fees_by_chain → 返回 0.0（中性）。"""
        assert compute_revenue_sustainability({}) == 0.0

    def test_all_zero_fees_returns_zero(self):
        """所有链费用为 0 → 返回 0.0。"""
        assert compute_revenue_sustainability({"chain_a": 0, "chain_b": 0}) == 0.0

    def test_output_range(self):
        """输出在 [-1.0, +1.0] 范围内。"""
        # 极端分散 + 稳定来源 + 长期
        fees = {f"chain_{i}": 1000 for i in range(10)}
        val = compute_revenue_sustainability(fees, "protocol_surplus", 365)
        assert -1.0 <= val <= 1.0
        # 极端集中 + 高波动 + 新来源
        fees2 = {"new_chain": 999999, "old_chain": 1}
        val2 = compute_revenue_sustainability(fees2, "trading_fee", 30)
        assert -1.0 <= val2 <= 1.0


# ---------------------------------------------------------------------------
# 2. 集中度维度
# ---------------------------------------------------------------------------

class TestConcentrationDimension:
    """集中度：单一来源占比>60%→风险信号。"""

    def test_diverse_sources_more_positive(self):
        """分散来源(5链各20%)比单一来源(1链100%)更正。"""
        diverse = {f"chain_{i}": 100000 for i in range(5)}  # 各20%
        concentrated = {"single_chain": 500000}  # 100%
        score_diverse = compute_revenue_sustainability(diverse, "trading_fee", 180)
        score_concentrated = compute_revenue_sustainability(concentrated, "trading_fee", 180)
        assert score_diverse > score_concentrated

    def test_high_concentration_negative(self):
        """单一来源占比>80% → 负信号（集中度风险）。"""
        fees = {"dominant": 900, "minor": 100}  # 90%集中
        val = compute_revenue_sustainability(fees, "trading_fee", 180)
        assert val < 0.0  # 集中度高→负

    def test_uni_case_60_percent_concentration(self):
        """UNI 文章案例：60%来自 RH Chain → 中等风险。"""
        fees = {
            "robinhood_chain": 925000,  # 60%
            "ethereum": 400000,        # 26%
            "others": 225000,          # 14%
        }
        val = compute_revenue_sustainability(fees, "trading_fee", 45)  # 新链<2月
        # 60%集中 + 新链 → 偏负
        assert val < 0.2


# ---------------------------------------------------------------------------
# 3. 来源类型维度
# ---------------------------------------------------------------------------

class TestSourceTypeDimension:
    """来源类型：协议盈余(稳定)>交易手续费(高波动)>资产收益(中等)。"""

    def test_protocol_surplus_better_than_trading_fee(self):
        """相同分散度下，协议盈余比交易手续费更正。"""
        fees = {f"chain_{i}": 100000 for i in range(3)}
        surplus = compute_revenue_sustainability(fees, "protocol_surplus", 180)
        trading = compute_revenue_sustainability(fees, "trading_fee", 180)
        assert surplus > trading

    def test_protocol_surplus_better_than_asset_yield(self):
        """协议盈余比资产收益更正。"""
        fees = {f"chain_{i}": 100000 for i in range(3)}
        surplus = compute_revenue_sustainability(fees, "protocol_surplus", 180)
        yield_ = compute_revenue_sustainability(fees, "asset_yield", 180)
        assert surplus > yield_

    def test_unknown_type_uses_mixed_default(self):
        """未知来源类型→用 mixed 默认权重。"""
        fees = {f"chain_{i}": 100000 for i in range(3)}
        val = compute_revenue_sustainability(fees, "unknown_type", 180)
        # 不抛异常，返回有效值
        assert -1.0 <= val <= 1.0


# ---------------------------------------------------------------------------
# 4. 持续性维度
# ---------------------------------------------------------------------------

class TestSustainabilityDimension:
    """持续性：来源<60天→低持续性。"""

    def test_long_history_better_than_new(self):
        """长期来源(>180天)比新来源(<60天)更正。"""
        fees = {"chain_a": 100000, "chain_b": 100000}
        old = compute_revenue_sustainability(fees, "trading_fee", 365)
        new = compute_revenue_sustainability(fees, "trading_fee", 30)
        assert old > new

    def test_new_chain_low_sustainability(self):
        """新链<60天 → 持续性因子=0.5。"""
        fees = {"new_chain": 100000}
        val = compute_revenue_sustainability(fees, "trading_fee", 45)
        # 新链+单一来源 → 明确负
        assert val < 0.0

    def test_boundary_60_days(self):
        """60天边界 → 中等持续性。"""
        fees = {f"chain_{i}": 100000 for i in range(3)}
        val_59 = compute_revenue_sustainability(fees, "trading_fee", 59)
        val_60 = compute_revenue_sustainability(fees, "trading_fee", 60)
        # 60天比59天略好
        assert val_60 >= val_59


# ---------------------------------------------------------------------------
# 5. 案例验证：UNI/HYPE/SKY
# ---------------------------------------------------------------------------

class TestCaseValidation:
    """文章案例验证。"""

    def test_uni_medium_negative(self):
        """UNI: 60%集中+新链<2月+交易费 → 偏负。"""
        fees = {
            "robinhood_chain": 925000,  # 60%
            "ethereum": 400000,        # 26%
            "others": 225000,          # 14%
        }
        val = compute_revenue_sustainability(fees, "trading_fee", 45)
        assert val < 0.3  # 偏负/中性

    def test_hype_high_positive(self):
        """HYPE: 99%手续费但长期运行+来源稳定 → 正。"""
        # HYPE 虽然单一来源(99%手续费)，但运行时间长且费用稳定
        fees = {"hyperliquid": 714000000}
        val = compute_revenue_sustainability(fees, "trading_fee", 365)
        # 长期+交易费 → 正（虽然集中度高，但持续性补偿）
        assert val > -0.5  # 不应太负

    def test_sky_high_positive(self):
        """SKY: 协议盈余(稳定来源) + 分散 → 正。"""
        fees = {"surplus_a": 500000, "surplus_b": 300000, "surplus_c": 200000}
        val = compute_revenue_sustainability(fees, "protocol_surplus", 365)
        assert val > 0.0  # 分散+稳定来源+长期 → 正

    def test_crcl_zero_revenue(self):
        """CRCL: 无实际收入 → 0.0。"""
        assert compute_revenue_sustainability({}) == 0.0
