"""Phase 3 半衰期校准模块测试。

SPEC-Phase2 §5.2 (M4): 4 个半衰期（tech_upgrade/fed_speech/sec_deadline/congressional_hearing）
为经验假设 v0，待 Phase 3 回测验证后用贝叶斯优化校准。

校准框架：
  - event_study.py: 事件研究法，计算事件后 CAR（累计超额收益）
  - synthetic_data.py: 生成已知 true_half_life 的合成事件+K线
  - calibrator.py: Optuna 贝叶斯优化，独立优化每个事件类型的 τ

RED 阶段：模块尚未实现，测试因 ImportError 失败。
"""
import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta

CAL_MOD = "half_life_calibration"


# ================================================================
# event_study.py — 事件研究法 CAR
# ================================================================

class TestEventStudy:
    def test_compute_car_long_event(self):
        """long 事件：事件日做多，持有期内上涨 → CAR 为正。"""
        from half_life_calibration.event_study import compute_car

        dates = pd.date_range("2026-01-01", periods=20, freq="D")
        # 前 10 天横盘 100，事件日(第10天)后涨到 110
        close = [100.0] * 10 + [100, 102, 104, 106, 108, 110, 110, 110, 110, 110]
        prices = pd.DataFrame({"close": close}, index=dates)
        events = [{"date": dates[10], "direction": "long"}]

        result = compute_car(events, prices, half_life=3.0, hold_days_mult=2.0)
        # 持有 2×3=6 天，第10天买入价100，第16天价110 → CAR=10%
        assert result["mean_car"] == pytest.approx(0.10, abs=0.005)
        assert result["win_rate"] == 1.0
        assert result["n_events"] == 1

    def test_compute_car_short_event(self):
        """short 事件：事件日做空，持有期内下跌 → CAR 为正。"""
        from half_life_calibration.event_study import compute_car

        dates = pd.date_range("2026-01-01", periods=20, freq="D")
        close = [100.0] * 10 + [100, 98, 96, 94, 92, 90, 90, 90, 90, 90]
        prices = pd.DataFrame({"close": close}, index=dates)
        events = [{"date": dates[10], "direction": "short"}]

        result = compute_car(events, prices, half_life=3.0, hold_days_mult=2.0)
        # 做空：(100-90)/100 = 10%
        assert result["mean_car"] == pytest.approx(0.10, abs=0.005)

    def test_compute_car_neutral_event_skipped(self):
        """neutral 事件跳过，不计入统计。"""
        from half_life_calibration.event_study import compute_car

        dates = pd.date_range("2026-01-01", periods=15, freq="D")
        prices = pd.DataFrame({"close": [100.0] * 15}, index=dates)
        events = [{"date": dates[5], "direction": "neutral"}]

        result = compute_car(events, prices, half_life=2.0)
        assert result["n_events"] == 0
        assert result["mean_car"] == 0.0

    def test_compute_car_multiple_events_averaged(self):
        """多事件 CAR 取平均。"""
        from half_life_calibration.event_study import compute_car

        dates = pd.date_range("2026-01-01", periods=30, freq="D")
        close = [100.0] * 15 + [100, 101, 102, 103, 104, 105, 106, 107, 108, 109,
                               110, 111, 112, 113, 114]
        prices = pd.DataFrame({"close": close}, index=dates)
        events = [
            {"date": dates[10], "direction": "long"},   # 持6天到close[16]=101 → +1%
            {"date": dates[20], "direction": "long"},   # 持6天到close[26]=111 → +6/105
        ]
        result = compute_car(events, prices, half_life=3.0, hold_days_mult=2.0)
        assert result["n_events"] == 2
        assert result["mean_car"] > 0.0

    def test_compute_car_insufficient_hold_days(self):
        """事件后数据不足持有期 → 用可用天数计算。"""
        from half_life_calibration.event_study import compute_car

        dates = pd.date_range("2026-01-01", periods=12, freq="D")
        close = [100.0] * 10 + [100, 105]  # 只多2天
        prices = pd.DataFrame({"close": close}, index=dates)
        events = [{"date": dates[10], "direction": "long"}]

        # half_life=3, hold=6天，但只剩2天数据
        result = compute_car(events, prices, half_life=3.0, hold_days_mult=2.0)
        assert result["n_events"] == 1
        assert result["mean_car"] == pytest.approx(0.05, abs=0.005)

    def test_compute_car_event_date_not_in_prices(self):
        """事件日不在 K 线中 → 跳过。"""
        from half_life_calibration.event_study import compute_car

        dates = pd.date_range("2026-01-01", periods=10, freq="D")
        prices = pd.DataFrame({"close": [100.0] * 10}, index=dates)
        # 事件日在 K 线范围外
        events = [{"date": datetime(2026, 2, 1, tzinfo=timezone.utc), "direction": "long"}]

        result = compute_car(events, prices, half_life=2.0)
        assert result["n_events"] == 0


# ================================================================
# synthetic_data.py — 合成数据生成
# ================================================================

class TestSyntheticData:
    def test_generate_events_returns_list(self):
        """生成指定数量的合成事件。"""
        from half_life_calibration.synthetic_data import generate_events

        events = generate_events(n_events=20, true_half_life=2.0, seed=42)
        assert len(events) == 20
        for ev in events:
            assert "date" in ev
            assert "direction" in ev
            assert ev["direction"] in ("long", "short", "neutral")

    def test_generate_events_deterministic(self):
        """相同 seed 生成相同事件。"""
        from half_life_calibration.synthetic_data import generate_events

        e1 = generate_events(n_events=10, true_half_life=2.0, seed=42)
        e2 = generate_events(n_events=10, true_half_life=2.0, seed=42)
        assert e1 == e2

    def test_generate_prices_has_enough_days(self):
        """生成的 K 线覆盖所有事件 + 持有期。"""
        from half_life_calibration.synthetic_data import generate_events, generate_prices

        events = generate_events(n_events=10, true_half_life=2.0, seed=42)
        prices = generate_prices(events, true_half_life=2.0, seed=42)
        assert isinstance(prices, pd.DataFrame)
        assert "close" in prices.columns
        # 覆盖最后一个事件 + 至少 2×true_half_life 天
        last_event_date = max(ev["date"] for ev in events)
        assert prices.index[-1] >= last_event_date + timedelta(days=4)

    def test_generate_prices_deterministic(self):
        """相同 seed 生成相同价格。"""
        from half_life_calibration.synthetic_data import generate_events, generate_prices

        events = generate_events(n_events=10, true_half_life=2.0, seed=42)
        p1 = generate_prices(events, true_half_life=2.0, seed=42)
        p2 = generate_prices(events, true_half_life=2.0, seed=42)
        pd.testing.assert_frame_equal(p1, p2)

    def test_synthetic_data_car_correlates_with_half_life(self):
        """合成数据：在 true_half_life 附近的 τ 应获得更高 CAR。

        这是端到端验证框架正确性的基础：如果合成数据设计正确，
        用 true_half_life 附近的 τ 计算的 CAR 应显著高于远离 true_half_life 的 τ。
        """
        from half_life_calibration.synthetic_data import generate_events, generate_prices
        from half_life_calibration.event_study import compute_car

        events = generate_events(n_events=30, true_half_life=2.0, seed=42)
        prices = generate_prices(events, true_half_life=2.0, seed=42)

        # τ 接近 true_half_life (2.0)
        car_close = compute_car(events, prices, half_life=2.0, hold_days_mult=2.0)
        # τ 远离 true_half_life (0.5)
        car_far = compute_car(events, prices, half_life=0.5, hold_days_mult=2.0)

        assert car_close["mean_car"] > car_far["mean_car"]


# ================================================================
# calibrator.py — 贝叶斯优化
# ================================================================

class TestCalibrator:
    def test_calibrate_returns_result_with_half_life(self):
        """calibrate_half_life 返回含 half_life 字段的结果。"""
        from half_life_calibration.synthetic_data import generate_events, generate_prices
        from half_life_calibration.calibrator import calibrate_half_life

        events = generate_events(n_events=20, true_half_life=2.0, seed=42)
        prices = generate_prices(events, true_half_life=2.0, seed=42)

        result = calibrate_half_life(
            event_type="test",
            events=events,
            prices=prices,
            tau_range=(0.5, 5.0),
            n_trials=15,
        )
        assert "half_life" in result
        assert "mean_car" in result
        assert "win_rate" in result
        assert "n_events" in result
        assert 0.5 <= result["half_life"] <= 5.0

    def test_calibrate_recovers_true_half_life(self):
        """端到端：校准框架能恢复合成数据的 true_half_life（±50% 容差）。"""
        from half_life_calibration.synthetic_data import generate_events, generate_prices
        from half_life_calibration.calibrator import calibrate_half_life

        true_tau = 2.0
        events = generate_events(n_events=40, true_half_life=true_tau, seed=123)
        prices = generate_prices(events, true_half_life=true_tau, seed=123)

        result = calibrate_half_life(
            event_type="test",
            events=events,
            prices=prices,
            tau_range=(0.5, 5.0),
            n_trials=30,
        )
        # 恢复到 true_half_life ± 50%
        assert abs(result["half_life"] - true_tau) <= true_tau * 0.5

    def test_calibrate_fail_open_on_insufficient_events(self):
        """事件不足时返回 v0 值 + 低置信度标记。"""
        from half_life_calibration.calibrator import calibrate_half_life

        result = calibrate_half_life(
            event_type="test",
            events=[],
            prices=pd.DataFrame({"close": [100.0]}),
            tau_range=(0.5, 5.0),
            n_trials=10,
        )
        assert result["n_events"] == 0
        assert result.get("confidence") == "low"
        # 返回 v0 先验值
        assert "half_life" in result

    def test_calibrate_independent_per_event_type(self):
        """不同事件类型独立校准，结果各自独立。"""
        from half_life_calibration.synthetic_data import generate_events, generate_prices
        from half_life_calibration.calibrator import calibrate_half_life

        # 两种事件类型不同 true_half_life
        events_a = generate_events(n_events=20, true_half_life=1.0, seed=1)
        prices_a = generate_prices(events_a, true_half_life=1.0, seed=1)
        events_b = generate_events(n_events=20, true_half_life=3.0, seed=2)
        prices_b = generate_prices(events_b, true_half_life=3.0, seed=2)

        res_a = calibrate_half_life("type_a", events_a, prices_a, n_trials=15)
        res_b = calibrate_half_life("type_b", events_b, prices_b, n_trials=15)

        # 各自独立优化，互不影响
        assert res_a["event_type"] == "type_a"
        assert res_b["event_type"] == "type_b"
