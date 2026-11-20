"""L4_meme 层合成指标测试（build_meme_layer_metrics）。

口径（2026-11-20 用户确认）：
  - meme_temperature   = 社交热度 40% + 情绪极性 35% + 风险偏好 25%
  - structure_risk     = 前 10 持仓集中度映射（只做折扣，不产生方向）
  - meme_heat_composite= BSC meme 评分 + Solana 毕业率（双链）
web3 数据缺失必须返回 degraded，不得编造数值。
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
)

from p3_meme_platform_monitor import build_meme_layer_metrics  # noqa: E402


def _block(**over):
    base = {
        "degraded": False,
        "web3_hype_med": 249232.5,
        "web3_sentiment_mean": 0.1,
        "web3_high_risk_ratio": 0.0678,
        "web3_top10_conc_med": 87.0,
        "web3_meme_score_med": 2.8762,
    }
    base.update(over)
    return base


def test_temperature_from_three_inputs():
    out = build_meme_layer_metrics(_block(), graduation_rate_pct=12.0)

    # hype: log10(249232.5)=5.3966 → (5.3966-5)/1.5 = 0.2644
    assert out["inputs"]["hype"] == 0.2644
    # sentiment +0.1 → (0.1+1)/2 = 0.55
    assert out["inputs"]["sentiment"] == 0.55
    # 高危 6.78% / 15% = 0.452
    assert out["inputs"]["risk_appetite"] == 0.452
    # 温度 = mean(0.2644, 0.55, 0.452) = 0.4221
    assert out["meme_temperature"] == 0.4221
    assert out["meme_direction"] == "neutral"


def test_hot_and_cold_direction():
    hot = build_meme_layer_metrics(
        _block(web3_hype_med=5_000_000, web3_sentiment_mean=1.0, web3_high_risk_ratio=0.2),
        graduation_rate_pct=30.0,
    )
    assert hot["meme_direction"] == "hot"
    assert hot["meme_temperature"] == 1.0

    cold = build_meme_layer_metrics(
        _block(web3_hype_med=50_000, web3_sentiment_mean=-1.0, web3_high_risk_ratio=0.0),
        graduation_rate_pct=0.0,
    )
    assert cold["meme_direction"] == "cold"
    assert cold["meme_temperature"] == 0.0


def test_structure_risk_mapping():
    # 87% 集中度 → (87-60)/40 = 0.675
    out = build_meme_layer_metrics(_block(), graduation_rate_pct=12.0)
    assert out["structure_risk"] == 0.675
    # ≤60% 视为分散
    low = build_meme_layer_metrics(_block(web3_top10_conc_med=45.0), graduation_rate_pct=12.0)
    assert low["structure_risk"] == 0.0
    # ≥100% 饱和
    high = build_meme_layer_metrics(_block(web3_top10_conc_med=120.0), graduation_rate_pct=12.0)
    assert high["structure_risk"] == 1.0


def test_heat_composite_two_chains():
    out = build_meme_layer_metrics(_block(), graduation_rate_pct=12.0)
    # BSC: (2.8762-2)/2.5 = 0.35048；Solana: (12-5)/20 = 0.35
    assert out["inputs"]["bsc_meme_score"] == 0.3505
    assert out["inputs"]["sol_graduation"] == 0.35
    assert out["meme_heat_composite"] == 0.3502


def test_degraded_when_web3_missing():
    for block in (None, {}, {"degraded": True, "reason": "no-web3-market-record"}):
        out = build_meme_layer_metrics(block, graduation_rate_pct=12.0)
        assert out["degraded"] is True
        assert out["meme_temperature"] is None
        assert out["structure_risk"] is None
        assert out["meme_heat_composite"] is None


def test_missing_solana_still_gives_single_chain_heat():
    out = build_meme_layer_metrics(_block(), graduation_rate_pct=None)
    assert "sol_graduation" not in out["inputs"]
    assert out["meme_heat_composite"] == 0.3505


def _history(n=40):
    """构造 n 条历史横截面（hype 10万→29.5万 / 情绪 -1→0.95 / 高危 0→19.5%）。"""
    return [
        {
            "web3_hype_med": 100_000 + i * 5_000,
            "web3_sentiment_mean": -1.0 + i * 0.05,
            "web3_high_risk_ratio": i * 0.005,
        }
        for i in range(n)
    ]


def test_percentile_mode_after_30_samples():
    out = build_meme_layer_metrics(_block(), graduation_rate_pct=12.0, history=_history(40))

    assert out["calibration"]["mode"] == "percentile"
    assert out["calibration"]["history_n"] == 40
    assert set(out["calibration"]["parts_mode"].values()) == {"percentile"}
    # hype 249232 → 30/40；情绪 0.1 → 22/40（历史值有浮点误差，0.1 不等）；高危 6.78% → 14/40
    assert out["inputs"]["hype"] == 0.75
    assert out["inputs"]["sentiment"] == 0.55
    assert out["inputs"]["risk_appetite"] == 0.35
    assert out["meme_temperature"] == 0.55
    assert out["meme_direction"] == "neutral"
    # structure_risk / 双链热度仍走绝对量纲（有界指标，不做分位）
    assert out["structure_risk"] == 0.675


def test_below_30_samples_falls_back_to_fixed_anchors():
    out = build_meme_layer_metrics(_block(), graduation_rate_pct=12.0, history=_history(10))

    assert out["calibration"]["mode"] == "fixed"
    assert out["calibration"]["history_n"] == 10
    assert out["inputs"]["hype"] == 0.2644
    assert out["meme_temperature"] == 0.4221
