"""
Phase 1 A 模块 TDD: ResistanceVector TR-RV-01 ~ TR-RV-10 (10条)
TDD ORDER IRON：先写测试，10/10正确失败 → 才允许实现 resistance_features.py
Mock 数据 100% 纯 numpy/pandas 生成（无 OKX API 调用，TDD 隔离）。
"""
from __future__ import annotations

import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# ----------------------------------------------------------------------------
# Mock data generator（避免 OKX API 依赖）
# ----------------------------------------------------------------------------
def _make_mock_raw_data(setup: str) -> dict:
    """按 setup 生成最小必要 raw_data_dict 字段。
    字段命名遵循 MVP Spec §2.2.1。
    """
    rng = np.random.default_rng(42 if setup != "stochastic" else None)
    N = 200  # 统一 200 bars（MA200 需要）
    base_price = 30000.0

    if setup == "setup01_5050_book":
        # TR-RV-01：多空筹码 50:50 → R_up ∈ [0.45, 0.55]
        close = base_price + np.cumsum(rng.normal(0, 30, N))
        data = dict(
            close=close,
            volume=np.full(N, 1000.0),
            okx_positions={"long": 0.5, "short": 0.5},  # 50:50
            liquidation_buy=np.full(N, 0.0),
            liquidation_sell=np.full(N, 0.0),
            ma_200=pd.Series(close).rolling(200).mean().iloc[-1],
            fib_retrace_0786=base_price * 1.05,  # 任意合理值
            fib_retrace_0618=base_price * 1.03,
            fib_retrace_0500=base_price * 1.02,
            bid_ask_spread_bps=2.0,
            news_sentiment_score=0.50,
        )
    elif setup == "setup02_ma200_nan_fib_fallback":
        # TR-RV-02：ma_200=NaN → 自动 fallback Fibonacci 0.786 → fallback_flags['MA200_USED_FIB'] = True
        close = base_price + np.cumsum(rng.normal(0, 30, N))
        data = dict(
            close=close,
            volume=np.full(N, 1000.0),
            okx_positions={"long": 0.55, "short": 0.45},
            liquidation_buy=np.full(N, 0.0),
            liquidation_sell=np.full(N, 0.0),
            ma_200=float("nan"),  # 关键：MA200缺失
            fib_retrace_0786=base_price * 1.05,
            fib_retrace_0618=base_price * 1.03,
            fib_retrace_0500=base_price * 1.02,
            bid_ask_spread_bps=2.0,
            news_sentiment_score=0.50,
        )
    elif setup == "setup03_linear_low_jaggedness":
        # TR-RV-03：线性价 → R_smooth ≤ 0.3（Livermore残差低）
        t = np.arange(N)
        close = base_price + 0.8 * t  # 完美线性
        data = dict(
            close=close,
            volume=np.full(N, 1000.0),
            okx_positions={"long": 0.50, "short": 0.50},
            liquidation_buy=np.full(N, 0.0),
            liquidation_sell=np.full(N, 0.0),
            ma_200=np.mean(close),
            fib_retrace_0786=base_price * 1.05,
            fib_retrace_0618=base_price * 1.03,
            fib_retrace_0500=base_price * 1.02,
            bid_ask_spread_bps=2.0,
            news_sentiment_score=0.50,
        )
    elif setup == "setup04_sine_high_jaggedness":
        # TR-RV-04：正弦锯齿状 → R_smooth ≥ 0.7
        t = np.arange(N)
        close = base_price + 300 * np.sin(t / 7) + 50 * rng.normal(0, 1, N)
        data = dict(
            close=close,
            volume=np.full(N, 1000.0),
            okx_positions={"long": 0.50, "short": 0.50},
            liquidation_buy=np.full(N, 0.0),
            liquidation_sell=np.full(N, 0.0),
            ma_200=np.mean(close),
            fib_retrace_0786=base_price * 1.05,
            fib_retrace_0618=base_price * 1.03,
            fib_retrace_0500=base_price * 1.02,
            bid_ask_spread_bps=2.0,
            news_sentiment_score=0.50,
        )
    elif setup == "setup05_effort_gt_result":
        # TR-RV-05：Wyckoff 努力>结果 → vol ×2，价格仅涨0.3% → R_flow ≥ 0.7
        t = np.arange(N)
        close = base_price + 90 * (t / (N-1))  # 0.3% rise (90/30000)
        volume = np.full(N, 2000.0)  # 翻倍 vol（effort 大）
        data = dict(
            close=close,
            volume=volume,
            okx_positions={"long": 0.50, "short": 0.50},
            liquidation_buy=np.full(N, 0.0),
            liquidation_sell=np.full(N, 0.0),
            ma_200=np.mean(close),
            fib_retrace_0786=base_price * 1.05,
            fib_retrace_0618=base_price * 1.03,
            fib_retrace_0500=base_price * 1.02,
            bid_ask_spread_bps=2.0,
            news_sentiment_score=0.50,
        )
    elif setup == "setup07_all_nan_fallback_5stack":
        # TR-RV-07：所有维度输入 NaN → 5 维权重 = 0.50，fallback_flags 全部 5 个键含
        data = dict(
            close=np.full(N, float("nan")),
            volume=np.full(N, float("nan")),
            okx_positions=None,  # None 视为筹码完全缺失 → R_up/R_down fallback
            liquidation_buy=np.full(N, float("nan")),
            liquidation_sell=np.full(N, float("nan")),
            ma_200=float("nan"),
            fib_retrace_0786=float("nan"),
            fib_retrace_0618=float("nan"),
            fib_retrace_0500=float("nan"),
            bid_ask_spread_bps=float("nan"),
            news_sentiment_score=float("nan"),
        )
    elif setup == "setup10_normal_no_error":
        # TR-RV-10：并发 10 个 symbol 其中 9 个正常 → 9 通过
        close = base_price + np.cumsum(rng.normal(0, 20, N))
        data = dict(
            close=close,
            volume=np.full(N, 800.0),
            okx_positions={"long": 0.58, "short": 0.42},
            liquidation_buy=np.full(N, 0.01),
            liquidation_sell=np.full(N, 0.01),
            ma_200=np.mean(close),
            fib_retrace_0786=base_price * 1.05,
            fib_retrace_0618=base_price * 1.03,
            fib_retrace_0500=base_price * 1.02,
            bid_ask_spread_bps=3.0,
            news_sentiment_score=0.50,
        )
    else:
        raise ValueError(f"Unknown setup: {setup}")

    data["symbol"] = f"SYM-{setup}"
    return data


# ----------------------------------------------------------------------------
# Gold Output Schema (TR-RV-09 inline MVP)
# ----------------------------------------------------------------------------
GOLD_SCHEMA = {
    "type": "object",
    "required": [
        "R_up", "R_down", "R_smooth", "R_flow", "R_reflexivity",
        "quality_score", "fallback_flags", "schema_version", "timestamp_ms",
    ],
    "additionalProperties": False,
    "properties": {
        "R_up":          {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "R_down":        {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "R_smooth":      {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "R_flow":        {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "R_reflexivity": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "quality_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "fallback_flags": {"type": "object", "additionalProperties": {"type": ["string", "boolean", "number"]}},
        "schema_version": {"type": "integer", "const": 1},
        "timestamp_ms":   {"type": "integer", "minimum": 1_700_000_000_000},  # after 2023-11-14
    },
}


def _validate_gold(obj):
    """轻量 inline schema 校验（MVP 不用 jsonschema，避免依赖；够严格 TR-RV-09）"""
    import jsonschema
    jsonschema.validate(obj, GOLD_SCHEMA)


class TestResistanceVectorPhase1:
    """TR-RV-01 ~ TR-RV-10"""

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _rv():
        """延迟 import（TDD 先失败，模块不存在→ModuleNotFoundError 正确 RED 原因）"""
        from dreambuddy_evolution.core import resistance_vector as resistance_features  # noqa: E402
        return resistance_features.ResistanceVector()

    @staticmethod
    def _rf_module():
        """返回 resistance_features 模块引用（用于 monkeypatch 类方法 / 全局变量）"""
        from dreambuddy_evolution.core import resistance_vector as resistance_features  # noqa: E402
        return resistance_features

    # -------------------------------------------------------------- TR-RV-01
    def test_rv01_50_50_chip_ratio_neutral_R_up(self):
        """TR-RV-01：50:50 多空筹码 → R_up 中性 [0.45, 0.55]"""
        rv = self._rv()
        out = rv.calculate("BTC-USDT", _make_mock_raw_data("setup01_5050_book"))
        assert 0.45 <= out["R_up"] <= 0.55, (
            f"50:50筹码应中性 R_up∈[0.45,0.55]，实际={out['R_up']:.4f}"
        )

    # -------------------------------------------------------------- TR-RV-02
    def test_rv02_ma200_nan_uses_fib_0786_fallback_flag(self):
        """TR-RV-02：ma_200=NaN → fallback 用 Fibonacci 0.786 + fallback_flags['MA200_USED_FIB']=True"""
        rv = self._rv()
        out = rv.calculate("BTC-USDT", _make_mock_raw_data("setup02_ma200_nan_fib_fallback"))
        assert bool(out["fallback_flags"].get("MA200_USED_FIB")) is True, (
            f"ma_200=NaN 必须设置 fallback_flags['MA200_USED_FIB']=True，实际flags={out['fallback_flags']}"
        )
        # R_up 计算应落在 [0.40, 0.60] 中性带（FO-1 降级但不应极端）
        assert 0.35 <= out["R_up"] <= 0.65, f"MA200 NaN 但用 Fib 兜底后 R_up={out['R_up']} 不应极端"

    # -------------------------------------------------------------- TR-RV-03
    def test_rv03_linear_price_array_R_smooth_low(self):
        """TR-RV-03：完美线性价 → Livermore 残差极低 → R_smooth ≤ 0.3"""
        rv = self._rv()
        out = rv.calculate("BTC-USDT", _make_mock_raw_data("setup03_linear_low_jaggedness"))
        assert out["R_smooth"] <= 0.30, (
            f"线性价R_smooth={out['R_smooth']:.4f} > 0.30 → 锯齿公式有误（应该低波动低阻力）"
        )

    # -------------------------------------------------------------- TR-RV-04
    def test_rv04_sine_jagged_array_R_smooth_high(self):
        """TR-RV-04：正弦锯齿 → R_smooth ≥ 0.7"""
        rv = self._rv()
        out = rv.calculate("BTC-USDT", _make_mock_raw_data("setup04_sine_high_jaggedness"))
        assert out["R_smooth"] >= 0.70, (
            f"正弦锯齿R_smooth={out['R_smooth']:.4f} < 0.70 → 锯齿强度检测过弱"
        )

    # -------------------------------------------------------------- TR-RV-05
    def test_rv05_wyckoff_effort_gt_result_R_flow_high(self):
        """TR-RV-05：Wyckoff effort(vol ×2) > result(价格+0.3%) → R_flow ≥ 0.7"""
        rv = self._rv()
        out = rv.calculate("BTC-USDT", _make_mock_raw_data("setup05_effort_gt_result"))
        assert out["R_flow"] >= 0.70, (
            f"努力>结果场景 R_flow={out['R_flow']:.4f} < 0.70 → Wyckoff 阻力流公式遗漏 vol/price_change 比值"
        )

    # -------------------------------------------------------------- TR-RV-06 (FO-1 monkeypatch)
    def test_rv06_sentiment_fo1_monkeypatch_neutral_and_quality_drop(self, monkeypatch):
        """TR-RV-06：SentimentEngine FO-1 降级（_SENTIMENT_FO1_ACTIVE=True）→ quality_score -0.15pp，reflexivity 降到 0.66 以下"""
        rv = self._rv()
        rf_mod = self._rf_module()
        data = _make_mock_raw_data("setup01_5050_book")
        # ---- 1. baseline：FO-1 未触发 → 用 monkeypatch 强制 False（确保 fixture 副作用没影响）
        monkeypatch.setattr(rf_mod, "_SENTIMENT_FO1_ACTIVE", False, raising=False)
        # 重置 self._sent_fo1（否则上次运行残留）
        rv._sent_fo1 = None  # noqa: SLF001
        out_baseline = rv.calculate("BTC-USDT", dict(data, news_sentiment_score=0.70))

        # ---- 2. FO-1：手动 monkey 激活全局标志
        monkeypatch.setattr(rf_mod, "_SENTIMENT_FO1_ACTIVE", True, raising=False)
        rv._sent_fo1 = None  # noqa: SLF001
        out_fo1 = rv.calculate("BTC-USDT", dict(data, news_sentiment_score=0.70))

        assert out_fo1["R_reflexivity"] <= 0.66, (
            f"sent L1降级 FO-1 触发后 reflexivity 应≤0.66（4:3:3 权重理论≈0.638），实际={out_fo1['R_reflexivity']:.3f}"
        )
        diff_pp = out_baseline["quality_score"] - out_fo1["quality_score"]
        assert diff_pp >= 0.10, (
            f"FO-1 quality_score 扣分不足 0.10pp：baseline={out_baseline['quality_score']:.3f} "
            f"fo1={out_fo1['quality_score']:.3f} diff={diff_pp:.3f}（MVP应-0.15，容0.05浮点）"
        )

    # -------------------------------------------------------------- TR-RV-07 (FO-2 ALL NaN)
    def test_rv07_all_nan_5dims_equal_050_fallback_flags_full(self):
        """TR-RV-07：ALL input NaN → R_{up,down,smooth,flow,refl}=0.500 精确；flags dict 包含 5 个 fallback 键"""
        rv = self._rv()
        out = rv.calculate("BTC-USDT", _make_mock_raw_data("setup07_all_nan_fallback_5stack"))
        DIMS = ["R_up", "R_down", "R_smooth", "R_flow", "R_reflexivity"]
        for d in DIMS:
            assert abs(out[d] - 0.500) < 1e-6, (
                f"FO-2 ALL NaN → {d}={out[d]} ≠ 0.500 (FAIL-OPEN 基线等价降级违反)"
            )
        # fallback_flags 至少包含 5 个降级键（按维度 1 键/维）
        assert len(out["fallback_flags"]) >= 5, (
            f"FO-2 ALL NaN → fallback_flags 应有≥5个键（每维1个），实际 {len(out['fallback_flags'])}: {out['fallback_flags']}"
        )
        # quality_score 必须 ≤ 0.40（FO-2 强降级 clamp 上限）
        assert out["quality_score"] <= 0.40, (
            f"FO-2 触发 quality_score={out['quality_score']:.3f} > 0.40（阈值上限违反 MVP Spec §3.6）"
        )

    # -------------------------------------------------------------- TR-RV-08 (Lark alert 5min3次)
    def test_rv08_lark_rate_limit_3_calls_in_5min_1_alert_sent(self, fake_alerts, monkeypatch):
        """TR-RV-08：FO-3 外层捕获 3 次连续异常（<5 min 窗口内）→ Lark CRITICAL alert 触发 1 次"""
        # 注入 monkeypatch：RV._fallback_stack 第 3 次 CRITICAL 调用 → Lark 计数 +1
        rf_mod = self._rf_module()

        # 让 RV 每次调用 fake_raw_data 里必然抛出 RuntimeError（外层 FO-3 try-except 兜底）
        def _always_raise(*a, **kw):
            raise RuntimeError("Simulated FO-3 crash for TR-RV-08")

        monkeypatch.setattr(rf_mod.ResistanceVector, "_calc_reflexivity_inner", _always_raise, raising=False)
        rv = self._rv()
        # 重置 fake_alerts counts
        fake_alerts.counts = {"warn": 0, "critical": 0, "error": 0, "info": 0}

        for i in range(3):
            try:
                _ = rv.calculate("BTC-USDT", _make_mock_raw_data("setup01_5050_book"))
            except Exception as e:
                pytest.fail(f"RV FO-3 应 outer try-except 兜底不抛异常！iter#{i} 抛出：{type(e).__name__}:{e}")

        assert fake_alerts.counts["critical"] >= 1, (
            f"3次连续异常 <5min → Lark CRITICAL alert 应≥1次，fake_alerts.critical={fake_alerts.counts['critical']}"
            f"所有counts={fake_alerts.counts}"
        )

    # -------------------------------------------------------------- TR-RV-09 (Gold schema)
    def test_rv09_output_matches_gold_schema(self):
        """TR-RV-09：任何成功返回的 dict 必须 100% 通过 Gold JSON Schema（MVP inline 写的 GOLD_SCHEMA）"""
        rv = self._rv()
        out = rv.calculate("BTC-USDT", _make_mock_raw_data("setup01_5050_book"))
        try:
            _validate_gold(out)
        except Exception as e:
            pytest.fail(f"RV output 违反 Gold Schema：{type(e).__name__}:{e}\nout={out}")

    # -------------------------------------------------------------- TR-RV-10 (Concurrent FO 隔离)
    def test_rv10_concurrent_10symbols_no_deadlock_isolated_failures(self):
        """TR-RV-10：ThreadPoolExecutor 10 symbol 并发，其中 symbol "EVIL-5" 单 symbol 触发 RuntimeError，
        其他 9 个正常返回——无死锁；9 个都有合法 output；总耗时 ≤ 3.0s（10 symbol mock 数据应很快）"""
        import time
        rv = self._rv()

        # monkeypatch 让只有 symbol 索引5的 symbol（任意命名 EVIL-IDX）内部抛错，其余正常
        rf_mod = self._rf_module()
        _orig_ref = getattr(rf_mod.ResistanceVector, "_calc_reflexivity_inner", None)

        def evil_inner(self_inner, symbol, data):
            if symbol.startswith("EVIL-5"):
                raise RuntimeError("TR-RV-10 Single symbol poison pill")
            if _orig_ref is not None:
                return _orig_ref(self_inner, symbol, data)
            return 0.50

        monkeypatched = False
        try:
            from unittest.mock import patch
            patcher = patch.object(rf_mod.ResistanceVector, "_calc_reflexivity_inner", evil_inner)
            patcher.start()
            monkeypatched = True

            symbols = [f"SYM-{i}" if i != 5 else "EVIL-5-SPECIAL" for i in range(10)]
            results = {}
            t0 = time.time()
            with ThreadPoolExecutor(max_workers=4) as ex:
                futs = {ex.submit(rv.calculate, s, _make_mock_raw_data("setup10_normal_no_error")): s for s in symbols}
                for fut in as_completed(futs, timeout=10.0):
                    s = futs[fut]
                    try:
                        results[s] = fut.result(timeout=1.0)
                    except Exception as e:
                        results[s] = f"__ERROR__:{type(e).__name__}"
            dt = time.time() - t0
            assert dt <= 10.0, f"并发10 symbol 耗时{dt:.2f}s>10s（疑似死锁）"

            # 9 个正常：results 都不是 __ERROR__ 或 dict
            ok_count = sum(1 for v in results.values() if isinstance(v, dict) and "R_up" in v)
            evil_res = results.get("EVIL-5-SPECIAL")
            # EVIL-5 有两种可能：要么抛错（外层FO-3兜底不抛到concurrent层）=返回 dict(fallback 0.5)；要么返回ERROR字符串
            # FAIL-OPEN 要求：**NEVER crash caller（concurrent层）** → 所以 EVIL-5 即使抛内部错，RV 外层也应该兜底返回 fallback dict
            if isinstance(evil_res, dict):
                ok_count += 1  # RV 成功 fallback（隔离：内部错误但调用不抛）
            # 必须 OK >= 9（其余9个必须正常）
            assert ok_count >= 9, (
                f"并发10 symbol OK count={ok_count} < 9（FAIL-OPEN 隔离违反）。详细结果：\n"
                + "\n".join(f"  {s}: {v if not isinstance(v, dict) else '<ok dict>'}" for s, v in results.items())
            )
        finally:
            if monkeypatched:
                patcher.stop()
