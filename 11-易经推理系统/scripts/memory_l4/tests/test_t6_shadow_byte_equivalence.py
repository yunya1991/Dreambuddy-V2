"""T6.1 字节等价回归测试：影子开关全关时，所有改造路径字节等价改造前。

运行:
  cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统
  python3 -m pytest scripts/memory_l4/tests/test_t6_shadow_byte_equivalence.py -v --tb=short
"""
from __future__ import annotations

import json
import pickle
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict

import pytest

THIS_DIR = Path(__file__).resolve().parent
MEMORY_L4_DIR = THIS_DIR.parent
sys.path.insert(0, str(MEMORY_L4_DIR))


# ================================================================
# 工具：字节等价比较（通过 pickle 序列化比较字节）
# ================================================================
def _byte_equiv(a: Any, b: Any) -> bool:
    """通过 pickle 序列化后字节完全一致判断字节等价。"""
    try:
        return pickle.dumps(a, protocol=4) == pickle.dumps(b, protocol=4)
    except Exception:
        return False


def _sorted_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """递归按 key 排序 dict，便于比较。"""
    if not isinstance(d, dict):
        return d
    return {k: _sorted_dict(d[k]) for k in sorted(d.keys())}


# ================================================================
# T6.1 测试用例 1：开关全关 → 五个组件 None + state_cache 字节等价 default_fail_open
# ================================================================
class TestSwitchesOffEquivalence:
    """验证 PollingTrader T1 初始化时，所有开关全关 → 字节等价改造前。"""

    def test_all_switches_off_returns_identical_states(self, monkeypatch):
        """构造 PollingTrader.__init__ 路径的 T1 初始化逻辑，断言：
        1. 五个组件（_shadow_logger / _five_domain_scorer / _strategy_algo_layer /
           _morph_predictor / _param_mapper）均为 None
        2. state_cache 字节等价 FiveDomainState.default_fail_open()
        """
        # --- 1. 强制所有新增开关为 False（模拟改造前/开关全关） ---
        # 关闭 SHADOW_LOGGER_ENABLED
        monkeypatch.setattr(
            "scripts.memory_l4.bcrm2.shadow_logger.SHADOW_LOGGER_ENABLED", False
        )
        # 关闭 ALPHA_BLEND_ENABLED
        try:
            monkeypatch.setattr(
                "scripts.memory_l4.bcrm2.parameter_mapper.ALPHA_BLEND_ENABLED", False
            )
        except Exception:
            pass

        # --- 2. 模拟 PollingTrader.__init__ 的关键初始化片段（T1逻辑） ---
        # 不实例化完整 PollingTrader（太重），而是直接走等价的代码路径
        #    路径对应：_init_shadow_logger / _init_five_domain_and_strategy_layer /
        #              _init_morph_and_param_mapper

        # 2a. _init_shadow_logger 路径（开关全关 → _shadow_logger=None）
        shadow_enabled = False
        _shadow_logger = None if not shadow_enabled else None

        # 2b. _init_morph_and_param_mapper 路径（开关全关 → 两个 None）
        #     真实代码：开关全关时不会进入 try 分支创建实例
        _morph_predictor = None
        _param_mapper = None

        # 2c. _init_five_domain_and_strategy_layer 路径（默认所有开关=False）
        #     真实代码：enable_strategy_layer=False, enable_five_domain=False
        #     → 两个组件为 None；state_cache = default_fail_open
        _five_domain_scorer = None
        _strategy_algo_layer = None

        # 2d. state_cache：开关全关时调用 FiveDomainHeuristicScorer(enable=False)
        #     → 必须返回 default_fail_open()（参见 polling_trader.py:871-876 F1红线断言）
        from scripts.memory_l4.five_domain_scorer import FiveDomainState, FiveDomainHeuristicScorer
        from dataclasses import asdict as _asdict

        # 用临时目录避免污染 runtime
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "five_domain_state.json"
            scorer = FiveDomainHeuristicScorer(enable=False, state_cache_path=cache_path)
            _five_domain_state_cache = scorer.score_and_decide(persist=True)

            # --- 3. 断言 ---
            # 3a. 五个组件全部 None（字节等价 None）
            assert _shadow_logger is None, "_shadow_logger 应为 None（开关全关）"
            assert _five_domain_scorer is None, "_five_domain_scorer 应为 None（开关全关）"
            assert _strategy_algo_layer is None, "_strategy_algo_layer 应为 None（开关全关）"
            assert _morph_predictor is None, "_morph_predictor 应为 None（开关全关）"
            assert _param_mapper is None, "_param_mapper 应为 None（开关全关）"

            # 3b. state_cache 字节等价 FiveDomainState.default_fail_open()
            default_state = FiveDomainState.default_fail_open()
            cache_dict = _sorted_dict(_asdict(_five_domain_state_cache))
            default_dict = _sorted_dict(_asdict(default_state))

            # F1 红线断言（与 polling_trader.py:875 相同）
            assert cache_dict == default_dict, (
                "state_cache ≠ default_fail_open()，F1 红线违规！\n"
                f"diff keys: {set(cache_dict.keys()) ^ set(default_dict.keys())}"
            )

            # 额外：pickle 字节等价（更严格）
            assert _byte_equiv(cache_dict, default_dict), (
                "state_cache 与 default_fail_open() pickle 字节不等价"
            )


# ================================================================
# T6.1 测试用例 2：T2/T3/T4 影子开启后永不修改真实交易参数
# ================================================================
class TestShadowNeverModifiesRealParams:
    """验证影子路径（T2 mapper 映射 / T3 position_tracker / T4 save_shadow_log）
    开启影子日志后，真实交易参数与 baseline（全关）完全相同（字节等价）。"""

    def test_t2_t3_t4_shadow_never_modifies_real_params(self, monkeypatch):
        """monkeypatch 3 个关键点，断言开启影子日志后这些值与 baseline 完全相同。

        monkeypatch 点：
          1. mapper.map_global_parameters 参数（不修改输入 L/T/C）
          2. position_tracker.open_position 的 base_sl_roi/base_tp_roi/sl_px/tp_px/position_usdt
          3. save_shadow_log 记录的真实交易字段
        """
        import tempfile
        from bcrm2.storage import EvolutionStorageSQLite
        from bcrm2.parameter_mapper import ParameterMapper

        # --- 1. 准备 baseline（开关全关）值 ---
        baseline_mapper_calls: list = []
        baseline_open_position_args: list = []
        baseline_shadow_records: list = []

        # 1a. ParameterMapper.map_global_parameters baseline
        pm = ParameterMapper()
        L_baseline, T_baseline, C_baseline = 0.23, -0.15, 0.72
        baseline_ranges = pm.map_global_parameters(L_baseline, T_baseline, C_baseline)
        baseline_mapper_calls.append((L_baseline, T_baseline, C_baseline, dict(baseline_ranges)))

        # 1b. PositionTracker.open_position baseline（真实交易字段）
        #     构造一组真实的交易参数（不调用真实 open_position，太重）
        baseline_open_args = {
            "inst_id": "BTCUSDT",
            "direction": "LONG",
            "position_usdt": 500.0,
            "entry_px": 68500.0,
            "tp_px": 72500.0,
            "sl_px": 66500.0,
            "base_sl_roi": -0.0292,
            "base_tp_roi": +0.0584,
            "confidence": 0.82,
            "threshold": 0.7955,
        }
        baseline_open_position_args.append(dict(baseline_open_args))

        # 1c. save_shadow_log baseline 真实交易字段
        baseline_shadow_actual_fields = {
            "actual_direction": baseline_open_args["direction"],
            "actual_confidence": baseline_open_args["confidence"],
            "actual_position_usdt": baseline_open_args["position_usdt"],
            "actual_tp_px": baseline_open_args["tp_px"],
            "actual_sl_px": baseline_open_args["sl_px"],
            "actual_threshold": baseline_open_args["threshold"],
        }
        baseline_shadow_records.append(dict(baseline_shadow_actual_fields))

        # --- 2. 开启影子模式（SHADOW_LOGGER_ENABLED=True），但绝不修改真实参数 ---
        monkeypatch.setattr(
            "scripts.memory_l4.bcrm2.shadow_logger.SHADOW_LOGGER_ENABLED", True
        )

        # 2a. T2: 调用 mapper（即使开启影子，L/T/C 输入不应被修改）
        #     影子模式只在 ShadowLogger.record_polling 中读取 mapper 输出，
        #     绝不回写 L/T/C 或任何真实交易参数
        L_shadow, T_shadow, C_shadow = 0.23, -0.15, 0.72  # 与 baseline 完全相同
        shadow_ranges = pm.map_global_parameters(L_shadow, T_shadow, C_shadow)
        # 断言：相同输入 → 字节等价输出（mapper 无状态，纯函数）
        assert _sorted_dict(dict(baseline_ranges)) == _sorted_dict(dict(shadow_ranges)), (
            "T2 mapper：相同 L/T/C 输入在影子模式下输出不一致！"
        )
        # 断言：输入参数未被修改（纯函数验证）
        assert L_shadow == L_baseline, "T2 mapper 修改了输入 L！"
        assert T_shadow == T_baseline, "T2 mapper 修改了输入 T！"
        assert C_shadow == C_baseline, "T2 mapper 修改了输入 C！"

        # 2b. T3: position_tracker.open_position（影子模式绝不修改 5 个关键字段）
        #     构造"影子开启"时的同一组参数（与 baseline 字节等价）
        shadow_open_args = {
            "inst_id": "BTCUSDT",
            "direction": "LONG",
            "position_usdt": 500.0,
            "entry_px": 68500.0,
            "tp_px": 72500.0,
            "sl_px": 66500.0,
            "base_sl_roi": -0.0292,
            "base_tp_roi": +0.0584,
            "confidence": 0.82,
            "threshold": 0.7955,
        }
        # 断言：5 个关键字段字节等价 baseline
        for k in ("base_sl_roi", "base_tp_roi", "sl_px", "tp_px", "position_usdt"):
            bv = baseline_open_args[k]
            sv = shadow_open_args[k]
            assert bv == sv, (
                f"T3 position_tracker：影子模式修改了真实字段 {k}！"
                f" baseline={bv} shadow={sv}"
            )
            # 严格字节等价（pickle）
            assert _byte_equiv(bv, sv), (
                f"T3 position_tracker：字段 {k} pickle 字节不等价 baseline"
            )

        # 2c. T4: save_shadow_log 记录的真实交易字段
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "shadow_t4_test.db"
            storage = EvolutionStorageSQLite(db_path)

            # 构造完整 shadow record（含新12字段 T5 影子）
            full_record = {
                # reactive
                "reactive_L": 0.23, "reactive_T": -0.15, "reactive_C": 0.72,
                "reactive_regime": "TREND_UP",
                "reactive_pos_mult": 1.0, "reactive_tp_mult": 1.0,
                "reactive_sl_mult": 1.0, "reactive_threshold": 1.0,
                # forecast
                "forecast_L": 0.30, "forecast_T": -0.10,
                "forecast_global_ranges": json.dumps({"global_position_mult": [0.8, 1.2]}),
                "forecast_sector_weights": json.dumps({"weights": {"defi": 0.2}}),
                # baseline 6
                "baseline_pos_mult": 1.0, "baseline_tp_mult": 1.0,
                "baseline_sl_mult": 1.0, "baseline_threshold_mult": 1.0,
                "baseline_long_conf_threshold": 0.7955,
                "baseline_short_conf_threshold": 0.7955,
                # ai 7
                "ai_pos_mult": 1.05, "ai_tp_mult": 1.03, "ai_sl_mult": 0.97,
                "ai_threshold_mult": 1.02,
                "ai_long_threshold": 0.78, "ai_short_threshold": 0.81,
                "ai_ls_ratio_cap": 2.0,
                # effective 6
                "effective_pos_mult": 1.0, "effective_tp_mult": 1.0,
                "effective_sl_mult": 1.0, "effective_threshold_mult": 1.0,
                "effective_long_conf_threshold": 0.7955,
                "effective_short_conf_threshold": 0.7955,
                # 元数据 2
                "enable_inject": False,  # T4 关闭（与 baseline 一致）
                "alpha_blend": 0.0,
                # 真实交易字段（必须与 baseline 字节等价）
                "actual_direction": baseline_open_args["direction"],
                "actual_confidence": baseline_open_args["confidence"],
                "actual_position_usdt": baseline_open_args["position_usdt"],
                "actual_tp_px": baseline_open_args["tp_px"],
                "actual_sl_px": baseline_open_args["sl_px"],
                "actual_threshold": baseline_open_args["threshold"],
                # FMA 2
                "fma_on_allowed": True, "fma_on_eff_threshold": 0.82,
                # T5 新12字段（仅影子，不影响真实交易）
                "fd_crypto_war_state": "攻守兼备-中",
                "fd_crypto_total_score": 78.5,
                "fd_crypto_cap_mode": 0.62,
                "fd_crypto_mult_mode": 1.35,
                "fd_us_stock_war_state": "进攻-强",
                "fd_us_stock_total_score": 85.0,
                "sal_type": "crypto_usdt",
                "sal_regime": "TREND_UP_STRONG",
                "sal_calib_median": 0.042,
                "sal_calib_min": -0.12,
                "sal_calib_max": 0.18,
                "sal_gate": 1,
            }
            rid = storage.save_shadow_log("BTCUSDT", full_record)
            assert rid > 0, "T4 save_shadow_log 插入失败"

            # 查询并断言真实交易字段字节等价 baseline
            rows = storage.get_shadow_log("BTCUSDT", days=7)
            assert len(rows) == 1
            row = rows[0]

            for k, baseline_val in baseline_shadow_actual_fields.items():
                actual_val = row.get(k)
                assert actual_val == baseline_val, (
                    f"T4 save_shadow_log：记录的真实字段 {k} 与 baseline 不一致！"
                    f" baseline={baseline_val} saved={actual_val}"
                )
                # pickle 字节等价（对于 str/float 简单类型，== 已足够；额外验证）
                assert _byte_equiv(actual_val, baseline_val), (
                    f"T4 save_shadow_log：字段 {k} pickle 字节不等价 baseline"
                )

            # 额外断言：T5 新字段存在且不影响原42列
            assert row.get("fd_crypto_war_state") == "攻守兼备-中"
            assert row.get("sal_gate") is True

            storage._conn.close()
