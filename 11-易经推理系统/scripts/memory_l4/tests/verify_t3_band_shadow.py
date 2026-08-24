#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Task T3 独立验证脚本：ParameterMapper 战略层带宽 clip 影子。

验证：
1) enable_five_domain_front_layer_band=False 时 inference 中不应出现 "_band_shadow" 键
2) 构造 band 且 switch=True 时，应正确写入 inference["_band_shadow"]
3) 真实参数 L/T（传给 mapper.map_global_parameters 的值）未被修改（monkeypatch 验证）
"""
from __future__ import annotations

import sys
import pathlib
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent.parent))

import numpy as np


def _make_minimal_trader(enable_front_band: bool, inject_band: dict | None):
    """构造最小可运行 shell，仅带必要属性。"""
    from scripts.memory_l4.strategy_algo_layer import (
        StrategyAlgorithmLayer, StrategyAlgoConfig
    )
    from scripts.memory_l4.five_domain_scorer import FiveDomainState, FiveDomainHeuristicScorer

    cfg = StrategyAlgoConfig(
        enable_five_domain_front_layer_band=enable_front_band,
    )

    state = FiveDomainState.default_fail_open()
    if inject_band is not None:
        state.front_layer_band["crypto_usdt"] = dict(inject_band)

    layer = StrategyAlgorithmLayer(cfg=cfg)

    cache_path = tempfile.mktemp(suffix=".json")
    scorer = FiveDomainHeuristicScorer(enable=False, state_cache_path=cache_path)

    class _TraderShell:
        pass
    trader = _TraderShell()
    trader._strategy_algo_layer = layer
    trader._five_domain_state_cache = state
    trader._five_domain_scorer = scorer
    trader._logs = []
    def _log(msg, level="INFO"):
        trader._logs.append((level, msg))
    trader._log = _log
    return trader


def _make_mock_mapper():
    """构造 mock mapper：map_global_parameters 和 map_sector_weights 返回固定结构。
    同时用 received 记录实际被调用的参数，用于 monkeypatch 验证。
    """
    received = {}

    class _MockMapper:
        _DEFAULT_IDENTITY_BETAS = {
            "defi": (1.0, 0.0, 0.0),
            "ai": (1.0, 0.0, 0.0),
            "rwa": (1.0, 0.0, 0.0),
            "meme": (1.0, 0.0, 0.0),
            "l2": (1.0, 0.0, 0.0),
        }

        def map_global_parameters(self, L, T, C):
            received["L"] = L
            received["T"] = T
            received["C"] = C
            return {
                "global_position_mult": (0.5, 1.5),
                "ls_ratio_cap": (0.0, 1.0),
                "long_bias": (0.0, 1.0),
                "short_bias": (0.0, 1.0),
                "long_threshold_mult": (0.5, 1.5),
                "short_threshold_mult": (0.5, 1.5),
            }

        def map_sector_weights(self, L, T, C, sector_betas=None):
            received["sw_L"] = L
            received["sw_T"] = T
            received["sw_C"] = C
            return {
                "weights": {"defi": 0.30, "ai": 0.25, "rwa": 0.20, "meme": 0.15, "l2": 0.10},
                "sector_tp_mult": {"defi": 1.0, "ai": 1.0, "rwa": 1.0, "meme": 1.0, "l2": 1.0},
                "sector_sl_mult": {"defi": 1.0, "ai": 1.0, "rwa": 1.0, "meme": 1.0, "l2": 1.0},
            }

    return _MockMapper(), received


def test_1_switch_off_no_band_shadow_key():
    """Case 1: enable_five_domain_front_layer_band=False → inference 不应出现 _band_shadow。"""
    print("[Test 1] switch=False → 无 _band_shadow 键...", end=" ", flush=True)

    trader = _make_minimal_trader(enable_front_band=False, inject_band=None)
    mapper, _ = _make_mock_mapper()
    trader._param_mapper = mapper

    inference = {
        "snapshot": {
            "level_smooth": 0.75,
            "trend_smooth": -0.42,
            "consensus": 0.60,
        }
    }

    from scripts.memory_l4.polling_trader import PollingTrader
    method = PollingTrader._log_param_mapper_snapshot.__get__(trader, PollingTrader)
    method("BTC", "BTCUSDT", inference)

    has_key = "_band_shadow" in inference
    assert not has_key, f"FAIL: switch=False 但 inference 出现了 _band_shadow 键！inference keys={list(inference.keys())}"
    print("PASS ✓ (no _band_shadow key)")


def test_2_switch_on_with_band_writes_shadow():
    """Case 2: switch=True + 注入 band → inference["_band_shadow"] 正确写入。"""
    print("[Test 2] switch=True + band → _band_shadow 写入...", end=" ", flush=True)

    band = {
        "L_min": 0.0, "L_max": 0.5,
        "T_min": -0.3, "T_max": 0.3,
        "sector_weights_min": 0.1, "sector_weights_max": 0.9,
    }
    trader = _make_minimal_trader(enable_front_band=True, inject_band=band)
    mapper, _ = _make_mock_mapper()
    trader._param_mapper = mapper

    L_raw_input = 0.80
    T_raw_input = -0.60
    inference = {
        "snapshot": {
            "level_smooth": L_raw_input,
            "trend_smooth": T_raw_input,
            "consensus": 0.50,
        }
    }

    from scripts.memory_l4.polling_trader import PollingTrader
    method = PollingTrader._log_param_mapper_snapshot.__get__(trader, PollingTrader)
    method("BTC", "BTCUSDT", inference)

    assert "_band_shadow" in inference, f"FAIL: 未写入 _band_shadow！inference keys={list(inference.keys())}"
    shadow = inference["_band_shadow"]

    assert shadow["L_before"] == L_raw_input, f"L_before={shadow['L_before']} != {L_raw_input}"
    assert shadow["T_before"] == T_raw_input, f"T_before={shadow['T_before']} != {T_raw_input}"

    assert shadow["L_after"] <= band["L_max"], f"L_after={shadow['L_after']} > L_max={band['L_max']}"
    assert shadow["L_after"] >= band["L_min"], f"L_after={shadow['L_after']} < L_min={band['L_min']}"
    assert shadow["T_after"] <= band["T_max"], f"T_after={shadow['T_after']} > T_max={band['T_max']}"
    assert shadow["T_after"] >= band["T_min"], f"T_after={shadow['T_after']} < T_min={band['T_min']}"

    for i, s in enumerate(shadow["sec_after"]):
        assert 0.1 <= s <= 0.9, f"sec_after[{i}]={s} 超出 [0.1,0.9]"

    assert shadow["front_band_switch_on"] is True
    assert shadow["band"] == band

    shadow_log_lines = [m for lvl, m in trader._logs if "战略层带宽影子" in m]
    assert len(shadow_log_lines) >= 1, f"FAIL: 未找到[战略层带宽影子]日志！日志数={len(trader._logs)}"

    print(f"PASS ✓ (L_after={shadow['L_after']:.4f} clipped from {L_raw_input}, "
          f"T_after={shadow['T_after']:.4f} clipped from {T_raw_input})")


def test_3_real_params_unchanged_monkeypatch():
    """Case 3: monkeypatch 验证 mapper.map_global_parameters 接收到的 L/T 未被修改。"""
    print("[Test 3] 真实参数 L/T 未被修改(monkeypatch)...", end=" ", flush=True)

    band = {
        "L_min": -1.0, "L_max": 0.0,
        "T_min": 0.5, "T_max": 2.0,
        "sector_weights_min": 0.0, "sector_weights_max": 1.0,
    }
    trader = _make_minimal_trader(enable_front_band=True, inject_band=band)
    mapper, received = _make_mock_mapper()
    trader._param_mapper = mapper

    L_real_input = 0.80
    T_real_input = 0.20
    inference = {
        "snapshot": {
            "level_smooth": L_real_input,
            "trend_smooth": T_real_input,
            "consensus": 0.50,
        }
    }

    from scripts.memory_l4.polling_trader import PollingTrader
    method = PollingTrader._log_param_mapper_snapshot.__get__(trader, PollingTrader)
    method("BTC", "BTCUSDT", inference)

    assert "L" in received, "FAIL: mapper.map_global_parameters 似乎未被调用！"
    assert received["L"] == L_real_input, (
        f"FAIL: 真实 L 参数被修改！传入 mapper 的 L={received['L']}，原始={L_real_input}"
    )
    assert received["T"] == T_real_input, (
        f"FAIL: 真实 T 参数被修改！传入 mapper 的 T={received['T']}，原始={T_real_input}"
    )
    assert received["sw_L"] == L_real_input, (
        f"FAIL: map_sector_weights 的 L 被修改！收到={received['sw_L']}，原始={L_real_input}"
    )
    assert received["sw_T"] == T_real_input, (
        f"FAIL: map_sector_weights 的 T 被修改！收到={received['sw_T']}，原始={T_real_input}"
    )

    shadow = inference.get("_band_shadow")
    assert shadow is not None, "_band_shadow 未写入"
    assert shadow["L_after"] == 0.0, f"影子 L_after 未正确 clip：{shadow['L_after']} (expect 0.0)"
    assert shadow["T_after"] == 0.5, f"影子 T_after 未正确 clip：{shadow['T_after']} (expect 0.5)"

    print(f"PASS ✓ (mapper收到 L={received['L']},T={received['T']} 与原始一致，"
          f"影子 L_after={shadow['L_after']},T_after={shadow['T_after']} 已 clip)")


def main():
    print("=" * 70)
    print("Task T3 验证脚本：ParameterMapper 战略层带宽 clip 影子")
    print("=" * 70)

    all_pass = True
    try:
        test_1_switch_off_no_band_shadow_key()
    except AssertionError as e:
        print(f"FAIL ✗: {e}")
        all_pass = False
    except Exception as e:
        print(f"ERROR ✗: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
        all_pass = False

    try:
        test_2_switch_on_with_band_writes_shadow()
    except AssertionError as e:
        print(f"FAIL ✗: {e}")
        all_pass = False
    except Exception as e:
        print(f"ERROR ✗: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
        all_pass = False

    try:
        test_3_real_params_unchanged_monkeypatch()
    except AssertionError as e:
        print(f"FAIL ✗: {e}")
        all_pass = False
    except Exception as e:
        print(f"ERROR ✗: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
        all_pass = False

    print("=" * 70)
    if all_pass:
        print("RESULT: 全部 3 项验证通过 ✓✓✓")
        return 0
    else:
        print("RESULT: 存在失败项 ✗")
        return 1


if __name__ == "__main__":
    sys.exit(main())
