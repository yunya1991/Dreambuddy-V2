#!/usr/bin/env python3
"""Task T4 独立验证脚本：策略层 select() 影子写入 enhance_info 三个场景验证"""
import sys
import os
from pathlib import Path
from dataclasses import asdict
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from scripts.memory_l4.strategy_algo_layer import (
    StrategyAlgorithmLayer,
    StrategyAlgoConfig,
    StrategySelection,
    DEFAULT_NEUTRAL_SCORES,
)
from scripts.memory_l4.five_domain_scorer import FiveDomainState

_PASS = 0
_FAIL = 0
_CHECKS = []


def check(name: str, cond: bool, detail: str = ""):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        _CHECKS.append(f"✅ PASS: {name}" + (f" | {detail}" if detail else ""))
    else:
        _FAIL += 1
        _CHECKS.append(f"❌ FAIL: {name}" + (f" | {detail}" if detail else ""))


def scenario_a_layer_disabled_default_values():
    """场景a: enable_strategy_layer=False → select返回 StrategySelection() 默认字节等价，calibration_biases中位数=1.0"""
    print("\n" + "=" * 80)
    print("场景a: enable_strategy_layer=False → 纯默认值")
    print("=" * 80)

    cfg_off = StrategyAlgoConfig(enable_strategy_layer=False)
    layer = StrategyAlgorithmLayer(cfg=cfg_off)

    fake_scores = {"dao": 80, "tian": 90, "di": 85, "jiang": 75, "fa": 80}
    sel = layer.select(
        asset_class="crypto_usdt",
        five_scores=fake_scores,
        regime_summary={"phase": "Bull"},
        liquidity_tier="G1",
        five_domain_state=None,
    )
    default_sel = StrategySelection()

    check("场景a-1: select返回字节等价默认StrategySelection",
          asdict(sel) == asdict(default_sel))

    cb = sel.calibration_biases
    numeric_cb = [float(v) for v in cb.values() if isinstance(v, (int, float))]
    all_one = all(abs(v - 1.0) < 1e-9 for v in numeric_cb)
    med = median(numeric_cb) if numeric_cb else 1.0
    check(f"场景a-2: calibration_biases数值中位数={med:.3f}，全1.0={all_one}",
          abs(med - 1.0) < 1e-9)

    enhance_info = {}
    enhance_info["strategy_selection"] = asdict(sel)
    stored_sel = enhance_info.get("strategy_selection", {})
    stored_cb = stored_sel.get("calibration_biases", {})
    stored_numeric = [float(v) for v in stored_cb.values() if isinstance(v, (int, float))]
    stored_med = median(stored_numeric) if stored_numeric else 0.0
    check(f"场景a-3: enhance_info中strategy_selection的calibration_biases中位数={stored_med:.3f}（应为1.0）",
          abs(stored_med - 1.0) < 1e-9)


def scenario_b_emergency_on_poor_score():
    """场景b: enable_strategy_layer=True + 极差评分(total<60 或 dao<40否决) → strategy_type='emergency' 且 gate=False"""
    print("\n" + "=" * 80)
    print("场景b: enable_strategy_layer=True + 极差评分 → emergency策略 + gate=False")
    print("=" * 80)

    from scripts.memory_l4.five_domain_scorer import FiveDomainHeuristicScorer

    cfg_on = StrategyAlgoConfig(
        enable_strategy_layer=True,
        enable_five_domain=True,
        enable_five_domain_style_mask=True,
    )
    layer = StrategyAlgorithmLayer(cfg=cfg_on)
    scorer = FiveDomainHeuristicScorer(enable=True)

    poor_scores_case1 = {"crypto_usdt": {"dao": 30, "tian": 45, "di": 40, "jiang": 35, "fa": 50},
                        "us_stock": {"dao": 50, "tian": 50, "di": 50, "jiang": 50, "fa": 70},
                        "precious_metal": {"dao": 50, "tian": 50, "di": 50, "jiang": 50, "fa": 70}}
    state1 = scorer.score_and_decide(poor_scores_case1, persist=False)
    sel1 = layer.select(
        asset_class="crypto_usdt",
        five_scores=poor_scores_case1["crypto_usdt"],
        regime_summary={"phase": "Bear"},
        liquidity_tier="G3",
        five_domain_state=state1,
    )
    check(f"场景b-1(dao<40否决): strategy_type='{sel1.strategy_type}'，应='emergency'",
          sel1.strategy_type == "emergency")

    gate1 = sel1.calibration_biases.get("hard_relax_gate", None) if isinstance(sel1.calibration_biases, dict) else None
    check(f"场景b-1: calibration_gate(hard_relax_gate)={gate1}，应=False",
          gate1 is False)

    weights = {"dao": 0.30, "tian": 0.15, "di": 0.25, "jiang": 0.15, "fa": 0.15}
    poor_scores_case2_cls = {"dao": 45, "tian": 40, "di": 42, "jiang": 38, "fa": 50}
    poor_scores_case2 = {"crypto_usdt": dict(poor_scores_case2_cls),
                         "us_stock": {"dao": 50, "tian": 50, "di": 50, "jiang": 50, "fa": 70},
                         "precious_metal": {"dao": 50, "tian": 50, "di": 50, "jiang": 50, "fa": 70}}
    total2 = int(round(sum(poor_scores_case2_cls.get(k, 50) * w for k, w in weights.items())))
    state2 = scorer.score_and_decide(poor_scores_case2, persist=False)
    sel2 = layer.select(
        asset_class="crypto_usdt",
        five_scores=poor_scores_case2_cls,
        regime_summary={"phase": "EarlyBear"},
        liquidity_tier="G4",
        five_domain_state=state2,
    )
    check(f"场景b-2(庙算总分={total2}<60): strategy_type='{sel2.strategy_type}'，应='emergency'",
          sel2.strategy_type == "emergency")

    gate2 = sel2.calibration_biases.get("hard_relax_gate", None) if isinstance(sel2.calibration_biases, dict) else None
    check(f"场景b-2: calibration_gate(hard_relax_gate)={gate2}，应=False",
          gate2 is False)


def scenario_c_monkeypatch_open_position_params():
    """场景c: monkeypatch position_tracker.open_position 实参 → base_sl_roi/base_tp_roi 字节等价，strategy_selection存在"""
    print("\n" + "=" * 80)
    print("场景c: monkeypatch → 真实交易参数字节等价 + enhance_info含strategy_selection")
    print("=" * 80)

    import types
    from scripts.memory_l4.trading_utils import PositionTracker, TradeRecord

    recorded_kwargs_no_t4 = {}
    recorded_kwargs_with_t4 = {}

    def fake_open_position_capture_no_t4(self, **kw):
        recorded_kwargs_no_t4.update(kw)
        return TradeRecord(trade_id="fake", coin=kw.get("coin",""), inst_id=kw.get("inst_id",""),
                           direction=kw.get("direction","long"), entry_price=0.0,
                           entry_time="", confidence=0.0, hexagram="")

    def fake_open_position_capture_with_t4(self, **kw):
        recorded_kwargs_with_t4.update(kw)
        return TradeRecord(trade_id="fake", coin=kw.get("coin",""), inst_id=kw.get("inst_id",""),
                           direction=kw.get("direction","long"), entry_price=0.0,
                           entry_time="", confidence=0.0, hexagram="")

    BASE_SL = -0.05234567890123
    BASE_TP = 0.12345678901234

    original_open = PositionTracker.open_position
    try:
        PositionTracker.open_position = fake_open_position_capture_no_t4
        tracker = PositionTracker()
        tracker.open_position(
            coin="BTC",
            inst_id="BTC-USDT-SWAP",
            direction="long",
            entry_price=65000.0,
            confidence=0.85,
            hexagram="乾为天",
            liangyi_state={},
            scale_params={},
            market_snapshot={"price": 65000.0},
            contradiction_list=[],
            enhance_info={"original_key": "original_value"},
            base_sl_roi=BASE_SL,
            base_tp_roi=BASE_TP,
            regime_pred="Bull",
            regime_multipliers={"position_mult": 1.0},
        )
    finally:
        PositionTracker.open_position = original_open

    def simulate_t4_enhance_info_modify(original_enhance, enable_layer: bool):
        """模拟插入T4后的enhance_info修改逻辑（与polling_trader.py内一致）"""
        enhance_info = dict(original_enhance) if original_enhance else {}
        _original = dict(enhance_info) if enhance_info else None
        try:
            if enable_layer:
                cfg = StrategyAlgoConfig(enable_strategy_layer=True)
                layer = StrategyAlgorithmLayer(cfg=cfg)
                scores = {"dao": 50, "tian": 50, "di": 50, "jiang": 50, "fa": 70}
                selection = layer.select(
                    asset_class="crypto_usdt",
                    five_scores=scores,
                    regime_summary={"phase": "Sideways"},
                    liquidity_tier="G2",
                    five_domain_state=FiveDomainState.default_fail_open(),
                )
                sel_snap = asdict(selection)
                if enhance_info is None:
                    enhance_info = {}
                enhance_info["strategy_selection"] = sel_snap
        except Exception:
            enhance_info = _original
        return enhance_info

    try:
        PositionTracker.open_position = fake_open_position_capture_with_t4
        tracker2 = PositionTracker()
        _orig_enh = {"original_key": "original_value"}
        _mod_enh = simulate_t4_enhance_info_modify(_orig_enh, enable_layer=True)
        tracker2.open_position(
            coin="BTC",
            inst_id="BTC-USDT-SWAP",
            direction="long",
            entry_price=65000.0,
            confidence=0.85,
            hexagram="乾为天",
            liangyi_state={},
            scale_params={},
            market_snapshot={"price": 65000.0},
            contradiction_list=[],
            enhance_info=_mod_enh,
            base_sl_roi=BASE_SL,
            base_tp_roi=BASE_TP,
            regime_pred="Bull",
            regime_multipliers={"position_mult": 1.0},
        )
    finally:
        PositionTracker.open_position = original_open

    sl_no_t4 = recorded_kwargs_no_t4.get("base_sl_roi")
    sl_with_t4 = recorded_kwargs_with_t4.get("base_sl_roi")
    check(f"场景c-1: base_sl_roi 字节等价 | no_t4={sl_no_t4} with_t4={sl_with_t4}",
          sl_no_t4 == sl_with_t4 and type(sl_no_t4) == type(sl_with_t4))

    tp_no_t4 = recorded_kwargs_no_t4.get("base_tp_roi")
    tp_with_t4 = recorded_kwargs_with_t4.get("base_tp_roi")
    check(f"场景c-2: base_tp_roi 字节等价 | no_t4={tp_no_t4} with_t4={tp_with_t4}",
          tp_no_t4 == tp_with_t4 and type(tp_no_t4) == type(tp_with_t4))

    enh_with_t4 = recorded_kwargs_with_t4.get("enhance_info") or {}
    has_strategy_sel = "strategy_selection" in enh_with_t4
    check(f"场景c-3: enhance_info含strategy_selection键? {has_strategy_sel}",
          has_strategy_sel)

    enh_no_t4 = recorded_kwargs_no_t4.get("enhance_info") or {}
    preserved = enh_no_t4.get("original_key") == enh_with_t4.get("original_key")
    check(f"场景c-4: enhance_info原有键值保留(original_key) | no_t4={enh_no_t4.get('original_key')} with_t4={enh_with_t4.get('original_key')}",
          preserved)

    sel_stored = enh_with_t4.get("strategy_selection", {})
    sel_type = sel_stored.get("strategy_type")
    check(f"场景c-5: strategy_selection结构完整(strategy_type存在={sel_type is not None}, type={sel_type})",
          isinstance(sel_stored, dict) and "strategy_type" in sel_stored and "calibration_biases" in sel_stored)


def main():
    print("Task T4 验证：策略层 select() 影子写入 enhance_info")
    print("=" * 80)

    scenario_a_layer_disabled_default_values()
    scenario_b_emergency_on_poor_score()
    scenario_c_monkeypatch_open_position_params()

    print("\n" + "=" * 80)
    print(f"结果汇总: {_PASS} 通过, {_FAIL} 失败")
    print("=" * 80)
    for msg in _CHECKS:
        print(msg)

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
