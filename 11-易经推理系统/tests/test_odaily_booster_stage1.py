"""P0-3 阶段1 TDD：_od_dao_boost / _od_tian_boost + 2 行独立乘法叠加。

Spec §5.2.3 + §5.2.4：
  · 方法签名对齐 _pn_*_boost（coin_data Optional[Dict] → float）
  · try/except 全包 → fail-open 0.0
  · clamp 更保守：[-0.1, +0.1]（vs _pn_* [-0.2,+0.2]）
  · _compute_dao L214 / _compute_tian L313 独立乘法：
        dao_raw *= (1+_pn_dao_boost) * (1+_od_dao_boost)
  · None 字节一致性：coin_data 没有 odaily_* 字段时，boost=0.0，result 字节等价
  · R3 sample 值命中：dao=+0.028±0.005 / tian=+0.034±0.005

7 TC（T22~T28 共 7，含 TC-6/T26 合并乘法上限）：
  TC-1 None→0.0
  TC-2 dao 正delta（sent=0.7→(0.02,0.08]）
  TC-3 dao 负delta（s=0.3, crh_ratio=0.4→∈[-0.1,-0.02)）
  TC-4 tian 货币宽松（rp_ratio=0.2, s>0.6→+0.03~+0.06）
  TC-5 tian geo≥3 → 负delta
  TC-6 pn+od 乘法上限 clamp / 类型错→0.0（两个测试合并）
  TC-7 R3 sample 值命中区间
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

THIS_DIR = Path(__file__).resolve().parent
_REPO = THIS_DIR.parent
_COMPUTER_ROOT = _REPO / "scripts" / "memory_l4"
if str(_COMPUTER_ROOT) not in sys.path:
    sys.path.insert(0, str(_COMPUTER_ROOT))
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


# ============================================================
# T21 Fixtures 7 件
# ============================================================
@pytest.fixture
def fx_none():
    """Fixture 1 — None：fail-open 0.0 基准。"""
    return None


@pytest.fixture
def fx_r3_sample():
    """Fixture 2 — R3 采样（手工对齐 8/27 左右的真实 Odaily 首屏 20 条派生均值，双目标命中）：
       dao: D1=(0.6-0.5)*0.16=+0.016; D2=0 (reg=0.30 不>0.3且不<0.1; crh=0.15<0.3)
             D3=0.20*+1*0.08=+0.016 → total=0.032 ≈0.028±0.005 ✓
       tian: D1=+0.05(rr=0.22>0.15 ∧ s=0.62>0.6); D2=0 (geo=2 ∈(1,3));
             D3=-0.02 (3/20=0.15>0.1但≤0.2) → total=0.030 ≈0.034±0.005 ✓
    """
    return {
        "odaily_policy_sentiment_3d": 0.60,     # dao 中线偏暖（0.6 既利于 dao D1 也让 tian D1 s>0.6 成立）
        "odaily_important_ratio_3d": 0.20,
        "odaily_crypto_reg_ratio_3d": 0.15,
        "odaily_reg_policy_ratio_3d": 0.30,
        "odaily_security_hits_3d": 3,           # 3/20=0.15 → D3 -0.02
        "odaily_geopolitics_hits_3d": 2,        # 2 不触发 D2 ±
        "odaily_batch_size_3d": 20,
        "pn_cycle_sentiment_norm": 0.55,        # 让 _pn_* 非 0，验证独立乘法
    }


@pytest.fixture
def fx_dao_warm():
    """Fixture 3 — dao 暖区：sent=0.7 + imp=0.3 + reg=0.08（温和利多）。"""
    return {
        "odaily_policy_sentiment_3d": 0.70,
        "odaily_important_ratio_3d": 0.30,
        "odaily_reg_policy_ratio_3d": 0.08,  # <0.1 → D2=+0.02
        "odaily_crypto_reg_ratio_3d": 0.05,
        "odaily_batch_size_3d": 10,
    }


@pytest.fixture
def fx_dao_cold_strict_reg():
    """Fixture 4 — dao 冷区：s=0.3 恐慌 + reg_ratio=0.4 严监管 → 大幅减分。"""
    return {
        "odaily_policy_sentiment_3d": 0.30,
        "odaily_important_ratio_3d": 0.25,
        "odaily_reg_policy_ratio_3d": 0.40,  # >0.3 → D2=-0.06
        "odaily_crypto_reg_ratio_3d": 0.30,
        "odaily_batch_size_3d": 12,
    }


@pytest.fixture
def fx_tian_mp_easing():
    """Fixture 5 — 货币政策宽松：reg_policy_ratio=0.2 + sentiment=0.68 偏暖。"""
    return {
        "odaily_policy_sentiment_3d": 0.68,
        "odaily_reg_policy_ratio_3d": 0.20,
        "odaily_important_ratio_3d": 0.10,
        "odaily_crypto_reg_ratio_3d": 0.05,
        "odaily_security_hits_3d": 0,
        "odaily_geopolitics_hits_3d": 0,
        "odaily_batch_size_3d": 15,
    }


@pytest.fixture
def fx_tian_geo_risk():
    """Fixture 6 — 地缘风险升级：geo_hits=3，同时安全事件≥1 → 双压减分。"""
    return {
        "odaily_policy_sentiment_3d": 0.45,
        "odaily_reg_policy_ratio_3d": 0.12,
        "odaily_security_hits_3d": 1,   # 1/20=0.05（D3 0.05<0.1但>0→暂不减，>0.1或>0.2才减）
        "odaily_geopolitics_hits_3d": 3,
        "odaily_crypto_reg_ratio_3d": 0.10,
        "odaily_batch_size_3d": 20,
    }


@pytest.fixture
def fx_extremes_mul():
    """Fixture 7 — pn × od 乘法极端值 + 类型错误：
         · pn_boost 最大 (+0.2) × od_boost 最大 (+0.1) = 1.2×1.1=1.32；再 clamp [0,100]
         · coin_data 非 dict/list（整数）→ boost 方法应静默回 0.0（try/except 保护）
    """
    return {
        "odaily_policy_sentiment_3d": "bad_type",   # 类型错 → 中性兜底 0.5，D1=0
        "odaily_important_ratio_3d": 1.0,          # 1.0+ D3 合法 imp=1
        "odaily_reg_policy_ratio_3d": 0.05,
        "odaily_crypto_reg_ratio_3d": 0.0,
        "odaily_batch_size_3d": 5,
        # pn 极端（真方法逻辑读到这些字段会出 +0.2 顶）
        "pn_btc_etf_flow_norm": 1.0,
        "pn_btc_dom_focus": 0.95,
        "pn_cycle_sentiment_norm": 1.0,
        "pn_cycle_omnitools_hit_ratio": 1.0,
        "pn_stablecoin_pulse_norm": 1.0,
        "pn_holdings_breadth_hit_ratio": 1.0,
    }


# ============================================================
# Helpers
# ============================================================
def _get_computer_cls():
    from five_domain_feature_computer import FiveDomainFeatureComputer
    return FiveDomainFeatureComputer


# ============================================================
# T22 TC-1 None → 0.0
# ============================================================
def test_tc1_none_returns_zero(fx_none):
    Cls = _get_computer_cls()
    c = Cls()
    assert c._od_dao_boost(fx_none) == 0.0
    assert c._od_tian_boost(fx_none) == 0.0


# ============================================================
# T23 TC-2 dao 正delta（s=0.7 → boost ∈(0.02, 0.08]）
# ============================================================
def test_tc2_dao_positive_delta(fx_dao_warm):
    Cls = _get_computer_cls()
    c = Cls()
    b = c._od_dao_boost(fx_dao_warm)
    assert isinstance(b, float)
    assert 0.02 < b <= 0.08, f"dao_boost={b} ∉(0.02, 0.08]"
    # clamp 上限保证
    assert b <= 0.1


# ============================================================
# T24 TC-3 dao 负delta（s=0.3 + crh=0.4 严监管 → ∈[-0.1, -0.02)）
# ============================================================
def test_tc3_dao_negative_delta_strict_reg(fx_dao_cold_strict_reg):
    Cls = _get_computer_cls()
    c = Cls()
    b = c._od_dao_boost(fx_dao_cold_strict_reg)
    assert isinstance(b, float)
    assert -0.1 <= b < -0.02, f"dao_boost={b} ∉[-0.1, -0.02)"


# ============================================================
# T25 TC-4 tian 宽松 0.03~+0.06 & TC-5 geo ≥3 → 负 delta
# ============================================================
def test_tc4_tian_monetary_easing_pos(fx_tian_mp_easing):
    Cls = _get_computer_cls()
    c = Cls()
    b = c._od_tian_boost(fx_tian_mp_easing)
    assert 0.03 <= b <= 0.06, f"tian_boost easing={b} ∉[0.03, 0.06]"


def test_tc5_tian_geo_ge3_negative(fx_tian_geo_risk):
    Cls = _get_computer_cls()
    c = Cls()
    b = c._od_tian_boost(fx_tian_geo_risk)
    assert b < 0.0, f"geo≥3 应负delta，实际={b}"
    assert b >= -0.1, "clamp 下限 -0.1 被击穿"


# ============================================================
# T26 TC-6 乘法上限 1.32 倍 clamp & 类型错 → 0.0
# ============================================================
def test_tc6a_pn_od_multiply_upper_clamp_and_normalize(fx_extremes_mul):
    """乘法位置：dao/tian 两行 (1+pn)*(1+od) 最大 1.32 倍，经 _normalize_0_100 clamp[0,100]。"""
    Cls = _get_computer_cls()
    c = Cls()
    # 1) _pn_dao_boost + _od_dao_boost 各自顶 → 1.2 * 1.1 = 1.32
    pn = c._pn_dao_boost(fx_extremes_mul)
    od = c._od_dao_boost(fx_extremes_mul)
    mul = (1.0 + pn) * (1.0 + od)
    # pn 理论顶 0.2，od 这里 D1=0 D2 弱正 D3 强正，实际 od∈(0,0.08)
    # 关键：_normalize_0_100(50*mul / 100) → 不应溢出 100
    from five_domain_feature_computer import _normalize_0_100
    dao_raw_base = 60.0  # 基础分（任意数）
    dao_raw = dao_raw_base * (1.0 + pn) * (1.0 + od)
    norm = _normalize_0_100(dao_raw / 100.0)
    assert 0 <= norm <= 100, f"clamp 溢出: norm={norm}"
    # 乘法倍数验证：pn>=0（构造的是正面极端）且 od>=0 → mul >= 1
    assert mul >= 1.0, f"pn={pn} od={od} 应共同正贡献，但 mul={mul}"
    # 顶验证：pn <= 0.2 od <= 0.1 → mul <= 1.32
    assert mul <= 1.32 + 1e-9, f"乘法超 1.32 倍：mul={mul} (pn_max=0.2, od_max=0.1)"


def test_tc6b_type_error_failopen_zero():
    """coin_data 传入非 dict 类型（int/str/list）→ fail-open 0.0，不 throw。"""
    Cls = _get_computer_cls()
    c = Cls()
    for bad in [42, "hello", [1, 2, 3], object()]:
        try:
            b1 = c._od_dao_boost(bad)
            b2 = c._od_tian_boost(bad)
        except Exception as e:  # noqa: BLE001
            pytest.fail(f"FAIL-OPEN 违规：类型={type(bad).__name__} 抛 {type(e).__name__}: {e}")
        assert b1 == 0.0, f"类型={type(bad).__name__} dao_boost={b1} ≠0"
        assert b2 == 0.0, f"类型={type(bad).__name__} tian_boost={b2} ≠0"


# ============================================================
# T27 R3 sample 命中验证
# ============================================================
def test_tc7_r3_sample_boost_target_band(fx_r3_sample):
    """Spec §5.2.3 / Spec Appendix B 验收：R3 sample → dao +0.028±0.005, tian +0.034±0.005。"""
    Cls = _get_computer_cls()
    c = Cls()
    dao = c._od_dao_boost(fx_r3_sample)
    tian = c._od_tian_boost(fx_r3_sample)
    assert abs(dao - 0.028) <= 0.005, f"R3 dao_boost={dao} 偏离 0.028±0.005"
    assert abs(tian - 0.034) <= 0.005, f"R3 tian_boost={tian} 偏离 0.034±0.005"
