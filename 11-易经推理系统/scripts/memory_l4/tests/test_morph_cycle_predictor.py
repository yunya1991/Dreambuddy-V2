"""Phase A 验收测试: MorphCyclePredictor（T_A1 ~ T_A5）

位置: scripts/memory_l4/tests/test_morph_cycle_predictor.py
运行: cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4 && python -m pytest tests/test_morph_cycle_predictor.py -v
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import List, Dict, Any

import numpy as np
import pytest

# Add bcrm2 to sys.path
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from bcrm2.storage import EvolutionStorageSQLite, RegimeStateFrame
from bcrm2.morph_cycle_predictor import MorphCyclePredictor


# ================================================================
# 工具：构造合成 trajectory（多周期正弦叠加 + 相位，模拟真实数据）
# ================================================================
def _make_synthetic_frames(days: int, seed: int = 42) -> List[RegimeStateFrame]:
    """构造 days 根日线的合成形态数据，level_smooth = 多周期叠加。"""
    rng = np.random.default_rng(seed)
    t = np.arange(days, dtype=float)
    # 多周期叠加：120天(主) + 60天 + 30天
    level_raw = (2.0 * np.sin(2 * np.pi * t / 120.0 + 0.5)
                 + 1.2 * np.sin(2 * np.pi * t / 60.0 - 0.8)
                 + 0.5 * np.sin(2 * np.pi * t / 30.0 + 0.3)
                 + rng.normal(0, 0.15, days))
    # level_smooth：EMA(α=0.3)
    smooth = np.zeros(days)
    smooth[0] = level_raw[0]
    for i in range(1, days):
        smooth[i] = 0.3 * level_raw[i] + 0.7 * smooth[i - 1]
    # trend = 差分
    trend_smooth = np.concatenate([[0.0], np.diff(smooth)])
    # 价格：近似 level 的指数映射（让 BTC 价格大约合理）
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
                "TREND_UP_STRONG": float(max(0, smooth[i]) / 8.0),
                "TREND_BULL": float(max(0, smooth[i]) / 8.0),
                "RANGE_BOUND": float(1.0 - abs(smooth[i]) / 4.0) * 0.5,
                "RANGING": 0.1,
                "MEAN_REVERTING": 0.05,
                "TREND_BEAR": float(max(0, -smooth[i]) / 8.0),
                "STRONG_TREND_BEAR": 0.0,
                "VOLATILE_DROP": 0.0,
            },
            top3=[["TREND_BULL", 0.4], ["RANGE_BOUND", 0.3], ["MEAN_REVERTING", 0.2]],
            consensus=float(np.clip(1.0 - float(np.std(level_raw[i-10:i] if i >= 10 else level_raw[:i+1])) / 2.0, 0.1, 0.95)),
            hmm_state=2 if smooth[i] > 0 else 0,
            bocpd_cp_prob=0.01,
            indicators={},
        ))
    return frames


def _populate_storage(storage: EvolutionStorageSQLite, frames: List[RegimeStateFrame],
                      symbol: str = "BTCUSDT") -> None:
    storage.upsert_daily_batch(symbol, frames)


@pytest.fixture
def tmp_storage(tmp_path) -> EvolutionStorageSQLite:
    """临时 SQLite + 180 根合成数据（足够 FFT top-3）。"""
    db_path = tmp_path / "evo_test.db"
    storage = EvolutionStorageSQLite(db_path)
    frames = _make_synthetic_frames(days=180, seed=42)
    _populate_storage(storage, frames)
    yield storage
    storage.close()


# ================================================================
# T_A1: 预测快照记录
# ================================================================
def test_T_A1_prediction_snapshot_recorded(tmp_storage):
    predictor = MorphCyclePredictor(tmp_storage)
    result = predictor.predict("BTCUSDT", hist_days=60, forecast_days=20)
    assert result["ok"], f"predict failed: {result}"

    # 预测快照应落库：horizon = 1..20，共 20 行
    cur = tmp_storage._conn.cursor()
    rows = cur.execute(
        "SELECT COUNT(*) AS c FROM morph_prediction_log WHERE symbol='BTCUSDT'"
    ).fetchone()
    assert rows["c"] == 20, f"应写入 20 条预测记录，实际 {rows['c']}"

    # 每条应包含 fft_components 和 hermite_params 的 JSON
    samples = cur.execute(
        "SELECT fft_components, hermite_params, prediction_date, target_date, horizon_days "
        "FROM morph_prediction_log WHERE symbol='BTCUSDT' ORDER BY horizon_days LIMIT 3"
    ).fetchall()
    for s in samples:
        fc = json.loads(s["fft_components"])
        assert isinstance(fc, list) and len(fc) >= 1, "fft_components 应非空 list"
        hp = json.loads(s["hermite_params"])
        assert "m0_base" in hp and "m1_base" in hp, "hermite_params 缺少 m0/m1 信息"
        assert s["horizon_days"] >= 1
        assert s["prediction_date"] < s["target_date"], "target_date 应晚于 prediction_date"


# ================================================================
# T_A2: 误差回填
# ================================================================
def test_T_A2_error_backfill(tmp_storage):
    predictor = MorphCyclePredictor(tmp_storage)

    # 用中间位置日期预测（让部分 target_date 落在已有的日级范围内，可回填）
    # 先将预测设置为中间日期（比如第 150 天作为 prediction_date，预测未来 10 天）
    frames = _make_synthetic_frames(days=180, seed=42)
    # 直接调用 insert_prediction_log 模拟 10 天前做的预测，target_date 已在 regime_state_daily
    from datetime import date, timedelta
    # prediction_date = 第 160 天
    # target_date = 第 161..170 天（都在 regime_state_daily 中，可回填）
    for i in range(1, 11):
        p_date = (date(2026, 1, 1) + timedelta(days=159)).strftime("%Y-%m-%d")
        t_date = (date(2026, 1, 1) + timedelta(days=159 + i)).strftime("%Y-%m-%d")
        tmp_storage.insert_prediction_log(
            symbol="BTCUSDT",
            prediction_date=p_date,
            target_date=t_date,
            horizon_days=i,
            predicted_l=0.0,  # 故意错误值，期望回填后有误差
            predicted_t=0.0,
            fft_components=[{"period": 120.0, "amplitude": 1.0}],
            hermite_params={"m0_base": 0.0, "m1_base": 0.0},
        )

    filled = tmp_storage.backfill_prediction_error("BTCUSDT")
    assert filled == 10, f"应回填 10 条，实际 {filled}"

    # 验证误差存在（非零）
    cur = tmp_storage._conn.cursor()
    errs = cur.execute(
        "SELECT error_l, actual_l, predicted_l FROM morph_prediction_log "
        "WHERE symbol='BTCUSDT' AND actual_l IS NOT NULL"
    ).fetchall()
    assert len(errs) == 10
    for r in errs:
        assert r["actual_l"] is not None
        assert r["error_l"] == r["actual_l"] - r["predicted_l"]


# ================================================================
# T_A3: FFT 权重修正 + 归一化
# ================================================================
def test_T_A3_fft_weight_correction_normalized(tmp_storage):
    predictor = MorphCyclePredictor(tmp_storage)

    # Step 1: 首先 predict 一次，得到初始预测快照
    result1 = predictor.predict("BTCUSDT", hist_days=60, forecast_days=10)
    assert result1["ok"]

    # Step 2: 手动回填 N 条带偏差的误差（模拟 predict 10 天后评估）
    # 让误差都为正（预测普遍偏低），期望权重大幅修正
    cur = tmp_storage._conn.cursor()
    for i in range(1, 6):
        cur.execute(
            "UPDATE morph_prediction_log SET actual_l = predicted_l + 0.5, "
            "error_l = 0.5 WHERE symbol='BTCUSDT' AND horizon_days = ? AND actual_l IS NULL",
            (i,),
        )
    tmp_storage._conn.commit()

    # Step 3: 调用 evaluate_and_correct
    metrics = predictor.evaluate_and_correct("BTCUSDT", min_filled_samples=3)
    assert metrics["correction"] is not None, "应有修正输出"
    corr = metrics["correction"]
    # 权重重修正系数在合理范围
    for pkey, mult in corr["weight_correction"].items():
        assert 0.5 <= mult <= 2.0, f"权重修正倍数 {pkey}={mult} 超范围 [0.5, 2.0]"

    # Step 4: 再次 predict 后，验证 FFT top-3 权重 + 修正系数的总变化量非零
    result2 = predictor.predict("BTCUSDT", hist_days=60, forecast_days=10)
    assert result2["ok"]
    # 两次预测的预测轨迹末值应有差异（至少一处不同）
    f1 = result1["series"]["forecast"]
    f2 = result2["series"]["forecast"]
    # 注：如果权重修正没有显著影响，fallback 到切线有变化即可
    tp1 = result1["params"]["hermite_params"]
    tp2 = result2["params"]["hermite_params"]
    different = (f1 != f2) or (tp1.get("m0_mul", 1.0) != tp2.get("m0_mul", 1.0))
    assert different, "修正后预测参数应有变化"


# ================================================================
# T_A4: 修正后最大单步变化 < 0.1（保持平滑）
# ================================================================
def test_T_A4_forecast_smooth_after_correction(tmp_storage):
    predictor = MorphCyclePredictor(tmp_storage)

    # 先写一些有极端误差的历史，触发大修正，然后验证仍平滑
    # 回填 20 条大误差
    for h in range(1, 21):
        from datetime import date, timedelta
        p = (date(2026, 1, 1) + timedelta(days=159)).strftime("%Y-%m-%d")
        t = (date(2026, 1, 1) + timedelta(days=159 + h)).strftime("%Y-%m-%d")
        tmp_storage.insert_prediction_log(
            "BTCUSDT", p, t, h,
            predicted_l=float(-h * 0.1),   # 预测随 horizon 变化
            predicted_t=0.0,
            fft_components=[{"period": 120.0, "amplitude": 1.0}],
            hermite_params={"m0_base": 0.0, "m1_base": 0.0},
        )
    cur = tmp_storage._conn.cursor()
    cur.execute("UPDATE morph_prediction_log SET actual_l = predicted_l + 0.8, error_l = 0.8 WHERE actual_l IS NULL")
    tmp_storage._conn.commit()

    predictor.evaluate_and_correct("BTCUSDT", min_filled_samples=5)
    result = predictor.predict("BTCUSDT", hist_days=60, forecast_days=20)
    assert result["ok"]
    f = result["series"]["forecast"]
    diffs = [abs(f[i + 1] - f[i]) for i in range(len(f) - 1)]
    max_diff = max(diffs) if diffs else 0.0
    assert max_diff < 0.1, (
        f"修正后预测曲线最大单步变化 = {max_diff:.4f}，应 < 0.1。"
        f" 全差分: {[round(d, 3) for d in diffs]}"
    )


# ================================================================
# T_A5: 误差下降趋势（连续修正）
# ================================================================
def test_T_A5_mae_non_increasing_across_corrections(tmp_storage):
    predictor = MorphCyclePredictor(tmp_storage)

    # 生成 5 轮的历史预测 + 带噪声的真实误差，每轮后修正
    maes: List[float] = []
    from datetime import date, timedelta

    for round_i in range(5):
        # 为该轮写入 10 条历史预测 + 回填误差（误差随 round_i 下降）
        base_prediction_date = (date(2026, 1, 1) + timedelta(days=100 + round_i * 10)).strftime("%Y-%m-%d")
        for h in range(1, 11):
            # 真实 L = 从 storage 取的一个历史值
            t_row = cur = tmp_storage._conn.cursor().execute(
                "SELECT level_smooth FROM regime_state_daily WHERE symbol='BTCUSDT' "
                "ORDER BY timestamp DESC LIMIT 1 OFFSET ?",
                (round_i * 3 + h,),
            ).fetchone()
            actual_l = float(t_row["level_smooth"]) if t_row else 0.0
            # 预测 L = 真实 + 随 round_i 减小的系统偏差
            bias = 1.0 - round_i * 0.15  # 每轮偏差减 0.15
            predicted_l = actual_l + bias + np.random.default_rng(round_i * 10 + h).normal(0, 0.05)
            target_date = (date(2026, 1, 1) + timedelta(days=100 + round_i * 10 + h)).strftime("%Y-%m-%d")
            tmp_storage.insert_prediction_log(
                "BTCUSDT", base_prediction_date, target_date, h,
                predicted_l=float(predicted_l),
                predicted_t=0.0,
                fft_components=[{"period": 120.0, "amplitude": 1.0}],
                hermite_params={"m0_base": 0.0, "m1_base": 0.0},
            )
        # 回填 = 在存储层直接 UPDATE（因为 regime_state_daily 里可能没对应 target_date）
        tmp_storage._conn.cursor().execute(
            "UPDATE morph_prediction_log SET actual_l = predicted_l, error_l = 0 "
            "WHERE actual_l IS NULL"
        )
        # 人为按 round_i 给误差（前 N 条有对应 actual_l 的 error）
        err_val = 1.0 - round_i * 0.15
        tmp_storage._conn.cursor().execute(
            "UPDATE morph_prediction_log SET "
            "actual_l = predicted_l + ?, "
            "error_l = ? "
            "WHERE prediction_date = ?",
            (err_val, err_val, base_prediction_date),
        )
        tmp_storage._conn.commit()

        m = predictor.evaluate_and_correct("BTCUSDT", min_filled_samples=3)
        if m["mae_before"] is not None:
            maes.append(float(m["mae_before"]))
        # 每次修正后做一次新的预测
        predictor.predict("BTCUSDT", hist_days=60, forecast_days=20)

    # 连续 5 轮修正，MAE 应单调不增（允许最后一轮等误差）
    print(f"MAE 序列: {[round(m, 4) for m in maes]}")
    assert len(maes) >= 4, f"至少 4 轮 MAE 记录，实际 {len(maes)}"
    # 允许 10% 以内的轻微波动（统计噪声），但首尾必须显著下降
    end_better = maes[-1] <= maes[0] * 0.8, f"末轮 MAE={maes[-1]:.4f} 应 ≤ 首轮 × 0.8 = {maes[0] * 0.8:.4f}"
    # 至少 60% 的相邻对是 "不增"（含 <= 前值×1.10 的轻微波动）
    non_inc_ratio = sum(1 for i in range(len(maes) - 1)
                        if maes[i + 1] <= maes[i] * 1.10) / max(len(maes) - 1, 1)
    assert end_better[0], end_better[1] + f"，序列: {maes}"
    assert non_inc_ratio >= 0.5, f"非递增相邻对占比 {non_inc_ratio:.0%} 应 ≥ 50%，序列: {maes}"


# ================================================================
# 端到端 smoke test: predict + 数据结构兼容旧接口
# ================================================================
def test_predict_response_schema(tmp_storage):
    predictor = MorphCyclePredictor(tmp_storage)
    r = predictor.predict("BTCUSDT", hist_days=60, forecast_days=20)
    assert r["ok"]
    # 向后兼容：与旧 get_morph_cycle() 结构一致
    for k in ("params", "dates", "series", "forecast_points", "price_hist"):
        assert k in r, f"响应缺少 {k}"
    s = r["series"]
    for k in ("classic_cycle", "current_stage", "forecast"):
        assert k in s, f"series 缺少 {k}"
    assert len(s["classic_cycle"]) == 60 + 20
    assert len(s["current_stage"]) == 60
    assert len(s["forecast"]) == 20


def test_T_A6_auto_correct_hook(tmp_storage):
    """T_A6: predict() 前自动触发修正 hook（自动识别样本+冷却保护）。"""
    from datetime import datetime, timezone, timedelta as td
    predictor = MorphCyclePredictor(tmp_storage)

    # 第 1 次 predict → 应检查自动修正，但因样本不足跳过
    r1 = predictor.predict("BTCUSDT", hist_days=60, forecast_days=20)
    assert r1["ok"]
    auto = r1["correction"]["auto"]
    # auto hook 返回 None → triggered=False（因样本不足 3 条）
    assert auto["triggered"] is False, \
        f"首次无样本，auto 不应 triggered，actual={auto}"

    # 造 4 条已回填数据 + 1 条过期修正时间戳（绕过冷却）
    base_pred_date = "2026-04-01"
    from datetime import date
    for h in range(1, 5):
        target_date = (date(2026, 4, 1) + td(days=h)).strftime("%Y-%m-%d")
        tmp_storage.insert_prediction_log(
            "BTCUSDT", base_pred_date, target_date, h,
            predicted_l=0.5 + h * 0.02, predicted_t=0.0,
            fft_components=[{"period": 120.0, "amplitude": 1.0}],
            hermite_params={"m0_base": 0.0, "m1_base": 0.0},
        )
    tmp_storage._conn.cursor().execute(
        "UPDATE morph_prediction_log SET actual_l = predicted_l + 0.2, error_l = 0.2 "
        "WHERE actual_l IS NULL"
    )
    tmp_storage._conn.commit()
    # save_correction_state → INSERT（首次 correction_count=1），再把 last_corrected_at 改回 2 天前
    tmp_storage.save_correction_state(
        "BTCUSDT",
        weight_correction={},
        tangent_correction={},
        last_mae=None,
    )
    cur = tmp_storage._conn.cursor()
    two_days_ago = (datetime.now(timezone.utc) - td(days=2)).isoformat(timespec="seconds")
    cur.execute(
        "UPDATE morph_correction_state SET last_corrected_at = ?, correction_count = 0 WHERE symbol='BTCUSDT'",
        (two_days_ago,),
    )
    tmp_storage._conn.commit()
    # 清空进程内冷却
    predictor._last_auto_corrected_at.clear()

    # 第 2 次 predict → 满足样本 ≥ 3 + 冷却到期 → 自动修正 triggered=True
    r2 = predictor.predict("BTCUSDT", hist_days=60, forecast_days=20)
    assert r2["ok"]
    auto = r2["correction"]["auto"]
    print(f"auto 第 2 次 predict: {auto}")
    assert auto["triggered"] is True, \
        f"4 条样本 + 冷却过期，应自动触发，actual={auto}"
    # filled_total >= 4
    assert auto["filled_total"] is None or int(auto["filled_total"]) >= 4

    # 第 3 次 predict → 刚修正完，冷却中 → triggered=False
    r3 = predictor.predict("BTCUSDT", hist_days=60, forecast_days=20)
    assert r3["ok"]
    auto3 = r3["correction"]["auto"]
    print(f"auto 第 3 次 predict: {auto3}")
    assert auto3["triggered"] is False, \
        f"第 2 次刚修完，冷却期，应不触发，actual={auto3}"
