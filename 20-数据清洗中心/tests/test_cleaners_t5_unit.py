"""T5 · UnitNormalizer：币种→USD / 百分比归一 / 换手率%→ratio。

T5-1  非USD价格 × 汇率表（EUR/JPY/GBP→USD）
T5-2  百分数字段 /100（如 2.5% → 0.025）
T5-3  换手率 % → ratio（同%→/100，但列名可识别）
T5-4  单位已统一（USD / ratio 格式）→ 不改原值
"""
from __future__ import annotations

import pandas as pd


class TestUnitNormalizer:
    # T5-1
    def test_t5_1_non_usd_price_by_fx_table(self) -> None:
        from data_cleaning.cleaners.unit_normalizer import UnitNormalizer
        from data_cleaning.contract import CleaningTrace

        fx = {"EUR": 1.10, "JPY": 0.0067, "GBP": 1.27}  # 1 EUR = 1.10 USD etc
        df = pd.DataFrame({
            "timestamp": pd.date_range("2026-08-01", periods=3, freq="1h"),
            "price_eur": [100.0, 101.0, 102.0],
            "price_jpy": [15000.0, 15100.0, 15200.0],
            "price_gbp": [80.0, 81.0, 82.0],
        })
        norm = UnitNormalizer(fx_rates=fx, price_columns=["price_eur", "price_jpy", "price_gbp"])
        out, action = norm.clean(df, CleaningTrace())
        # EUR: 100 * 1.10 = 110
        assert abs(out["price_eur"].iloc[0] - 110.0) < 1e-9
        # JPY: 15000 * 0.0067 = 100.5
        assert abs(out["price_jpy"].iloc[0] - 100.5) < 1e-9
        # GBP: 80 * 1.27 = 101.6
        assert abs(out["price_gbp"].iloc[0] - 101.6) < 1e-9

    # T5-2
    def test_t5_2_percentage_column_divide_100(self) -> None:
        from data_cleaning.cleaners.unit_normalizer import UnitNormalizer
        from data_cleaning.contract import CleaningTrace

        df = pd.DataFrame({
            "timestamp": pd.date_range("2026-08-01", periods=3, freq="1h"),
            "gdp_growth_pct": [2.5, 3.1, -0.8],
            "unemployment_rate": [4.2, 4.1, 4.3],
        })
        norm = UnitNormalizer(percent_columns=["gdp_growth_pct", "unemployment_rate"])
        out, _ = norm.clean(df, CleaningTrace())
        assert abs(out["gdp_growth_pct"].iloc[0] - 0.025) < 1e-9
        assert abs(out["unemployment_rate"].iloc[1] - 0.041) < 1e-9

    # T5-3
    def test_t5_3_turnover_pct_to_ratio(self) -> None:
        from data_cleaning.cleaners.unit_normalizer import UnitNormalizer
        from data_cleaning.contract import CleaningTrace

        df = pd.DataFrame({
            "timestamp": pd.date_range("2026-08-01", periods=3, freq="1h"),
            "turnover_pct": [1.5, 2.7, 0.9],
        })
        norm = UnitNormalizer(turnover_columns=["turnover_pct"])
        out, _ = norm.clean(df, CleaningTrace())
        assert abs(out["turnover_pct"].iloc[1] - 0.027) < 1e-9

    # T5-4
    def test_t5_4_already_normalized_values_unchanged(self) -> None:
        from data_cleaning.cleaners.unit_normalizer import UnitNormalizer
        from data_cleaning.contract import CleaningTrace

        df = pd.DataFrame({
            "timestamp": pd.date_range("2026-08-01", periods=2, freq="1h"),
            "price_usd": [100.0, 101.0],
            "volume_ratio": [0.015, 0.017],
        })
        norm = UnitNormalizer()  # 空配置
        out, action = norm.clean(df, CleaningTrace())
        # 没匹配任何列 → 值不变，clip/impute计数=0
        assert action.clipped_count == 0
        assert action.imputed_count == 0
        assert out["price_usd"].iloc[0] == 100.0
