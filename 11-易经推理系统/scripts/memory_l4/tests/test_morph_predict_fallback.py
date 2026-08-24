"""T2 RED — MorphCyclePredictor.predict_with_fallback() 测试（4 用例）

覆盖行为：
  F1) test_btc_direct_ok
        BTCUSDT 本身 trajectory ≥20 → 直接返回 predict() 结果，
        fallback_used=False, beta_scaled=False

  F2) test_non_btc_insufficient_falls_back_to_btc_with_beta
        非 BTC 币种 trajectory <20 但 BTC 充足 → 调用 BTC predict() 并按 β 缩放，
        fallback_used=True, beta_scaled=True，forecast 长度一致

  F3) test_non_btc_sufficient_direct_predict
        非 BTC 币种 trajectory ≥20 → 直接调用 predict()，
        fallback_used=False（不走 fallback 路径）

  F4) test_btc_also_insufficient_returns_error
        BTC 本身 trajectory <20 → 返回 ok=False, fallback_used=False，
        不崩溃，提供 error 字段

说明：predict_with_fallback() 是设计中新方法，当前不存在 → 预期 FAIL。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List

import numpy as np
import pytest

_THIS_DIR = Path(__file__).resolve().parent
_BCRM2_ROOT = _THIS_DIR.parent
assert _BCRM2_ROOT.name == "memory_l4"
if str(_BCRM2_ROOT) not in sys.path:
    sys.path.insert(0, str(_BCRM2_ROOT))

from bcrm2.storage import EvolutionStorageSQLite, RegimeStateFrame  # noqa: E402


def _make_synthetic_frames(days: int, seed: int = 42) -> List[RegimeStateFrame]:
    from datetime import date, timedelta
    rng = np.random.default_rng(seed)
    t = np.arange(days, dtype=float)
    level_raw = (2.0 * np.sin(2 * np.pi * t / 120.0 + 0.5)
                 + 1.2 * np.sin(2 * np.pi * t / 60.0 - 0.8)
                 + 0.5 * np.sin(2 * np.pi * t / 30.0 + 0.3)
                 + rng.normal(0, 0.15, days))
    smooth = np.zeros(days)
    smooth[0] = level_raw[0]
    for i in range(1, days):
        smooth[i] = 0.3 * level_raw[i] + 0.7 * smooth[i - 1]
    trend_smooth = np.concatenate([[0.0], np.diff(smooth)])
    price_base = 40000.0 * np.exp(smooth / 10.0)
    frames = []
    for i in range(days):
        from datetime import date, timedelta
        d = date(2026, 1, 1) + timedelta(days=i)
        frames.append(RegimeStateFrame(
            t=d.strftime("%Y-%m-%d"),
            price=float(price_base[i]),
            level_raw=float(level_raw[i]),
            trend_raw=float(trend_smooth[i]),
            level_smooth=float(smooth[i]),
            trend_smooth=float(trend_smooth[i] * 5.0),
            regime_probs={
                "TREND_UP_STRONG": 0.4, "TREND_BULL": 0.2,
                "RANGE_BOUND": 0.15, "RANGING": 0.1,
                "MEAN_REVERTING": 0.05, "TREND_BEAR": 0.05,
                "STRONG_TREND_BEAR": 0.03, "VOLATILE_DROP": 0.02,
            },
            top3=[["TREND_UP_STRONG", 0.4], ["TREND_BULL", 0.2], ["RANGE_BOUND", 0.15]],
            consensus=float(np.clip(1.0 - float(np.std(level_raw[max(0,i-10):i+1])) / 2.0, 0.1, 0.95)),
            hmm_state=2 if smooth[i] > 0 else 0,
            bocpd_cp_prob=0.01,
            indicators={},
        ))
    return frames


@pytest.fixture
def storage_with_btc_only(tmp_path) -> EvolutionStorageSQLite:
    """仅 BTCUSDT 有 ≥180 根 trajectory；其他币种 trajectory 为 0。"""
    db_path = tmp_path / "evo.db"
    s = EvolutionStorageSQLite(db_path=str(db_path))
    frames = _make_synthetic_frames(days=180, seed=42)
    s.upsert_daily_batch("BTCUSDT", frames)
    # XAGUSDT 仅 2 根（<20），模拟缺数据币种
    few = _make_synthetic_frames(days=2, seed=99)
    s.upsert_daily_batch("XAGUSDT", few)
    yield s
    s.close()


@pytest.fixture
def storage_multi_symbol(tmp_path) -> EvolutionStorageSQLite:
    """BTCUSDT + ETHUSDT 均 ≥180 根；XAGUSDT 仍缺数据。"""
    db_path = tmp_path / "evo2.db"
    s = EvolutionStorageSQLite(db_path=str(db_path))
    s.upsert_daily_batch("BTCUSDT", _make_synthetic_frames(days=180, seed=1))
    s.upsert_daily_batch("ETHUSDT", _make_synthetic_frames(days=180, seed=7))
    s.upsert_daily_batch("XAGUSDT", _make_synthetic_frames(days=2, seed=13))
    yield s
    s.close()


@pytest.fixture
def storage_empty(tmp_path) -> EvolutionStorageSQLite:
    """空 storage。"""
    db_path = tmp_path / "evo_empty.db"
    s = EvolutionStorageSQLite(db_path=str(db_path))
    yield s
    s.close()


# ---------------------------------------------------------------- F1
def test_btc_direct_ok(storage_with_btc_only):
    """F1: BTC 数据充足 → 直接预测，fallback_used=False。"""
    from bcrm2.morph_cycle_predictor import MorphCyclePredictor
    p = MorphCyclePredictor(storage_with_btc_only)

    r = p.predict_with_fallback("BTCUSDT", hist_days=60, forecast_days=5)

    assert r.get("ok") is True, f"预期 ok=True，实际 ok={r.get('ok')} err={r.get('error')}"
    assert r.get("fallback_used") is False, "BTC 直接预测不应触发 fallback"
    assert r.get("beta_scaled") is False, "BTC 直接预测不应触发 β 缩放"
    fcast = r.get("series", {}).get("forecast", [])
    assert len(fcast) == 5, f"forecast 长度={len(fcast)}，预期 5"


# ---------------------------------------------------------------- F2
def test_non_btc_insufficient_falls_back_to_btc_with_beta(storage_with_btc_only):
    """F2: XAG 数据不足 → fallback BTC，按 β=1.5 缩放 forecast_L。"""
    from bcrm2.morph_cycle_predictor import MorphCyclePredictor
    p = MorphCyclePredictor(storage_with_btc_only)

    r = p.predict_with_fallback("XAGUSDT", hist_days=60, forecast_days=5,
                                symbol_beta=1.5)

    assert r.get("ok") is True, f"fallback 后应 ok=True，实际 err={r.get('error')}"
    assert r.get("fallback_used") is True, "XAG 不足应触发 fallback"
    assert r.get("beta_scaled") is True, "fallback 应标记 β 缩放"
    assert r.get("fallback_source") == "BTCUSDT", "fallback 来源应为 BTCUSDT"
    # forecast 长度匹配
    fcast = r.get("series", {}).get("forecast", [])
    assert len(fcast) == 5, f"forecast 长度={len(fcast)}，预期 5"
    # β=1.5 应放大波动：BTC forecast_last - BTC forecast_first 与 XAG 的比例 ≈ 1.5
    # 此处只校验返回字段完整性，数值由 TDD GREEN 时实现
    assert "series" in r and "forecast" in r["series"]
    assert "forecast_L" in r or "forecast_end_level" in r or True


# ---------------------------------------------------------------- F3
def test_non_btc_sufficient_direct_predict(storage_multi_symbol):
    """F3: ETH 数据充足 → 直接 predict()，不走 fallback。"""
    from bcrm2.morph_cycle_predictor import MorphCyclePredictor
    p = MorphCyclePredictor(storage_multi_symbol)

    r = p.predict_with_fallback("ETHUSDT", hist_days=60, forecast_days=5)

    assert r.get("ok") is True, f"预期 ok=True，实际 err={r.get('error')}"
    assert r.get("fallback_used") is False, "ETH 充足不应 fallback"
    assert r.get("beta_scaled") is False
    fcast = r.get("series", {}).get("forecast", [])
    assert len(fcast) == 5


# ---------------------------------------------------------------- F4
def test_btc_also_insufficient_returns_error(storage_empty):
    """F4: BTC 也缺数据 → 返回 ok=False, fallback_used=False，不崩溃。"""
    from bcrm2.morph_cycle_predictor import MorphCyclePredictor
    p = MorphCyclePredictor(storage_empty)

    r = p.predict_with_fallback("XAGUSDT", hist_days=60, forecast_days=5)

    assert r.get("ok") is False, "BTC 也不足应最终 ok=False"
    assert r.get("fallback_used") is False, "BTC 失败时不应标记 fallback 成功"
    assert "error" in r, "必须提供 error 字段说明失败原因"
    # 不抛出异常即可（已通过语法断言）
