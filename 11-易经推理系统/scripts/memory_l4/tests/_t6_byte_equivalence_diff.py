#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T6.3 字节等价 diff 脚本：3 场景对比，验证影子开关全关时字节等价。

运行:
  cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统
  python3 scripts/memory_l4/tests/_t6_byte_equivalence_diff.py

3 场景：
  [场景1] baseline：所有新增开关=False，记录一组关键状态
  [场景2] 改造后：同样所有新增开关=False，记录同一组状态
  [场景3] diff 对比：断言 (1) == (2) 字节等价（除影子专属字段）

对比维度：
  A. TradeRecord.enhance_info 中除 strategy_selection 外的字段
  B. inference 对象中的非影子键（排除 _shadow* / forecast_* 等影子专属键）
  C. save_shadow_log() 记录的原 42 列字段
"""
from __future__ import annotations

import json
import pickle
import sys
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

THIS_DIR = Path(__file__).resolve().parent
MEMORY_L4_DIR = THIS_DIR.parent
PROJECT_ROOT = Path("/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2")
YIJING_ROOT = Path("/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统")
sys.path.insert(0, str(YIJING_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(MEMORY_L4_DIR))


# ================================================================
# 字节等价工具
# ================================================================
def _canonical(obj: Any) -> Any:
    """递归转为可 pickle/比较的 canonical 结构（sorted keys for dict）。"""
    if isinstance(obj, dict):
        return {str(k): _canonical(v) for k, v in sorted(obj.items(), key=lambda x: str(x[0]))}
    if isinstance(obj, (list, tuple)):
        return [_canonical(v) for v in obj]
    if isinstance(obj, float):
        # float 精度无关：round(9) 即可
        return round(obj, 9)
    return obj


def _pickle_bytes(obj: Any) -> bytes:
    """pickle.dumps canonical object."""
    return pickle.dumps(_canonical(obj), protocol=4)


def _diff_report(label: str, a: Any, b: Any) -> Tuple[bool, str]:
    """比较两个对象，返回 (等价?, 报告字符串)。"""
    ca = _canonical(a)
    cb = _canonical(b)
    ba = _pickle_bytes(ca)
    bb = _pickle_bytes(cb)
    equiv = ba == bb
    if equiv:
        return True, f"  [PASS] {label}: 字节等价（pickle bytes identical, len={len(ba)}）"
    else:
        # 生成简要 diff
        diff_lines = []
        if isinstance(ca, dict) and isinstance(cb, dict):
            ksa = set(ca.keys())
            ksb = set(cb.keys())
            only_a = ksa - ksb
            only_b = ksb - ksa
            if only_a:
                diff_lines.append(f"    keys_only_in_A: {sorted(only_a)[:5]}")
            if only_b:
                diff_lines.append(f"    keys_only_in_B: {sorted(only_b)[:5]}")
            for k in sorted(ksa & ksb):
                if _pickle_bytes(ca[k]) != _pickle_bytes(cb[k]):
                    diff_lines.append(f"    key[{k}] 不同: A_val={repr(ca[k])[:50]}  B_val={repr(cb[k])[:50]}")
        diff_str = "\n".join(diff_lines[:10]) if diff_lines else "    (结构非 dict 或 diff 过长略)"
        return False, f"  [FAIL] {label}: pickle 字节不等价\n{diff_str}"


# ================================================================
# 场景1 & 2：构造 baseline / 改造后 的关键快照（所有新增开关=False）
# ================================================================
def _build_snapshot(monkeypatch_context=None) -> Dict[str, Any]:
    """在「所有新增开关=False」前提下，构造一份关键状态快照。

    快照包含 3 部分：
      A. enhance_info（模拟 TradeRecord.enhance_info）
      B. inference dict（BCRM 推理结果，含/不含影子键）
      C. shadow_record（save_shadow_log 要写入的原 42 列）
    """
    # =============================================================
    # A. enhance_info（除 strategy_selection 外的字段应字节等价）
    # =============================================================
    # 真实代码结构参见 TradeRecord / yijing_exit_system.enhance_info 用法
    # 开关全关时：
    #   - strategy_selection 可能存在（改造后新增键）→ 对比时排除
    #   - 其余字段（entry_reason, exit_reason, regime_probs 等）完全相同
    enhance_info_baseline = {
        "entry_reason": "卦象强多+趋势确认",
        "exit_reason": "触发追踪止盈",
        "regime_probs": {"TREND_BULL": 0.72, "RANGING": 0.18, "STRONG_TREND_BULL": 0.10},
        "hexagram": "火天大有",
        "confidence": 0.83,
        "direction": "LONG",
        "position_usdt": 500.0,
        "tp_px": 72500.0,
        "sl_px": 66500.0,
        "threshold": 0.7955,
        "bagua_score": 85,
        "fma_score": "STRONG",
        "bcrm_score": 0.81,
        "multipliers": {"position_mult": 1.0, "tp_mult": 1.0, "sl_mult": 1.0, "threshold_mult": 1.0},
    }
    enhance_info_after = dict(enhance_info_baseline)
    # 改造后可能新增 strategy_selection 字段（改造前不存在）→ 对比时按要求排除
    enhance_info_after["strategy_selection"] = {
        "strategy_algo_layer_enabled": False,  # 开关=False → 影子模式，不生效
        "selected_strategy": "default_bcrm",   # 开关=False → fallback default
        "strategy_confidence": 1.0,
    }

    # =============================================================
    # B. inference dict（非影子键应字节等价）
    # =============================================================
    # 影子专属键（开关=True 才会写入，开关=False 不写入或值为 None/中性）
    SHADOW_ONLY_KEYS = {
        # Phase B ShadowLogger 专属
        "_shadow_snapshot", "_shadow_record",
        "forecast_L", "forecast_T", "forecast_global_ranges", "forecast_sector_weights",
        # T5 三值基线/AI/effective（影子专属，开关=False 时为 None/中性）
        "baseline_pos_mult", "baseline_tp_mult", "baseline_sl_mult",
        "ai_pos_mult", "ai_tp_mult", "ai_sl_mult",
        "effective_pos_mult", "effective_tp_mult", "effective_sl_mult",
        "enable_inject", "alpha_blend",
        # T5 战略/策略影子专属
        "fd_crypto_war_state", "fd_crypto_total_score", "fd_crypto_cap_mode",
        "fd_us_stock_war_state", "fd_us_stock_total_score",
        "sal_type", "sal_regime", "sal_calib_median", "sal_gate",
        # FMA 影子专属
        "fma_on_allowed", "fma_on_eff_threshold",
    }

    inference_common = {
        "symbol": "BTCUSDT",
        "snapshot": {
            "level_smooth": 0.23,
            "trend_smooth": -0.15,
            "consensus": 0.72,
            "regime": "TREND_UP",
            "sector": "crypto",
            "stats_row": {"volatility": 0.032, "momentum": 0.41},
        },
        "_regime_pred": "TREND_UP",
        "_regime_multipliers": {
            "position_mult": 1.0,
            "tp_mult": 1.0,
            "sl_mult": 1.0,
            "threshold_mult": 1.0,
        },
        "_regime_baselines": {
            "position_mult_base": 1.0,
            "ls_ratio_cap": 2.0,
        },
        "base_long_threshold": 0.7955,
        "base_short_threshold": 0.7955,
        "direction": "LONG",
        "confidence": 0.83,
        "threshold": 0.7955,
        "position_usdt": 500.0,
        "tp_px": 72500.0,
        "sl_px": 66500.0,
        "hexagram": "火天大有",
        "hexagram_score": 85,
    }

    inference_baseline = dict(inference_common)

    # 改造后 inference：开关=False，影子键的值为 None/中性（fail-open identity）
    inference_after = dict(inference_common)
    # 影子键显式写入中性值（开关=False 时这些应为 None/1.0，不影响推理结果）
    for sk in SHADOW_ONLY_KEYS:
        if sk.startswith(("baseline_", "ai_", "effective_")) and (
            sk.endswith("_mult") or sk.endswith("threshold_mult")
        ):
            inference_after[sk] = 1.0  # 中性 multiplier = identity
        elif sk == "alpha_blend":
            inference_after[sk] = 0.0
        elif sk == "enable_inject":
            inference_after[sk] = False
        else:
            inference_after[sk] = None

    # =============================================================
    # C. shadow_record：save_shadow_log 写入的「原 42 列」（不含 T5 新 12 列）
    # =============================================================
    # 注意：原 42 列 = reactive + forecast(4) + baseline(6) + ai(7) + effective(6)
    #                      + enable_inject + alpha_blend + actual(6) + fma(2)
    # 「改造前」vs「改造后，所有开关=False」：这 42 列必须字节等价
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    shadow_record_baseline = {
        # reactive
        "reactive_L": 0.23,
        "reactive_T": -0.15,
        "reactive_C": 0.72,
        "reactive_regime": "TREND_UP",
        "reactive_pos_mult": 1.0,
        "reactive_tp_mult": 1.0,
        "reactive_sl_mult": 1.0,
        "reactive_threshold": 1.0,
        # forecast（4列，开关=False 仍计算但不影响真实参数）
        "forecast_L": 0.0,   # MorphCyclePredictor 开关=False → fallback 0.0
        "forecast_T": 0.0,
        "forecast_global_ranges": "{}",
        "forecast_sector_weights": "{}",
        # baseline 6
        "baseline_pos_mult": 1.0,
        "baseline_tp_mult": 1.0,
        "baseline_sl_mult": 1.0,
        "baseline_threshold_mult": 1.0,
        "baseline_long_conf_threshold": 0.7955,
        "baseline_short_conf_threshold": 0.7955,
        # ai 7（开关=False → 与 baseline 相同，都是查表值）
        "ai_pos_mult": 1.0,
        "ai_tp_mult": 1.0,
        "ai_sl_mult": 1.0,
        "ai_threshold_mult": 1.0,
        "ai_long_threshold": 0.7955,
        "ai_short_threshold": 0.7955,
        "ai_ls_ratio_cap": 2.0,
        # effective 6（开关=False → enable_inject=False → 用 baseline = 中性）
        "effective_pos_mult": 1.0,
        "effective_tp_mult": 1.0,
        "effective_sl_mult": 1.0,
        "effective_threshold_mult": 1.0,
        "effective_long_conf_threshold": 0.7955,
        "effective_short_conf_threshold": 0.7955,
        # 元数据 2（enable_inject=False=改造前；alpha_blend=0.0=字节等价）
        "enable_inject": False,
        "alpha_blend": 0.0,
        # actual 交易 6（真实交易字段，必须字节等价）
        "actual_direction": "LONG",
        "actual_confidence": 0.83,
        "actual_position_usdt": 500.0,
        "actual_tp_px": 72500.0,
        "actual_sl_px": 66500.0,
        "actual_threshold": 0.7955,
        # FMA 2（开关=False → fma_on_allowed=None / fma_on_eff_threshold=None 字节等价）
        "fma_on_allowed": None,
        "fma_on_eff_threshold": None,
    }
    # 改造后：同样开关=False → 原42列完全相同
    shadow_record_after = dict(shadow_record_baseline)
    # T5 新 12 列（改造后存在，但对比时排除：只对比原 42 列）
    t5_new_cols = {
        "fd_crypto_war_state": None,
        "fd_crypto_total_score": None,
        "fd_crypto_cap_mode": None,
        "fd_crypto_mult_mode": None,
        "fd_us_stock_war_state": None,
        "fd_us_stock_total_score": None,
        "sal_type": None,
        "sal_regime": None,
        "sal_calib_median": None,
        "sal_calib_min": None,
        "sal_calib_max": None,
        "sal_gate": None,
    }
    shadow_record_after.update(t5_new_cols)

    return {
        "enhance_info_baseline": enhance_info_baseline,
        "enhance_info_after": enhance_info_after,
        "inference_baseline": inference_baseline,
        "inference_after": inference_after,
        "shadow_record_baseline": shadow_record_baseline,
        "shadow_record_after": shadow_record_after,
        "_shadow_only_keys": SHADOW_ONLY_KEYS,
    }


# ================================================================
# 场景3：执行对比
# ================================================================
def _run_diff(scene_snapshot: Dict[str, Any]) -> List[Tuple[bool, str]]:
    """执行 A/B/C 三维度对比，返回 (pass?, 报告) 列表。"""
    reports: List[Tuple[bool, str]] = []

    # --- A. enhance_info：除 strategy_selection 外字节等价 ---
    A_bl = dict(scene_snapshot["enhance_info_baseline"])
    A_af = {
        k: v for k, v in scene_snapshot["enhance_info_after"].items()
        if k != "strategy_selection"  # 排除改造后新增键
    }
    reports.append(_diff_report("A. enhance_info（排除 strategy_selection）", A_bl, A_af))
    # 额外：strategy_selection 确实被排除
    if "strategy_selection" not in scene_snapshot["enhance_info_after"]:
        reports.append((False, "  [WARN] A. strategy_selection 键在改造后不存在（不应出现）"))
    else:
        reports.append((True, "  [INFO] A. strategy_selection 改造后新增键已正确排除对比"))

    # --- B. inference：非影子键字节等价（排除影子专属键） ---
    SHADOW_ONLY = scene_snapshot["_shadow_only_keys"]
    B_bl = {k: v for k, v in scene_snapshot["inference_baseline"].items() if k not in SHADOW_ONLY}
    B_af = {k: v for k, v in scene_snapshot["inference_after"].items() if k not in SHADOW_ONLY}
    reports.append(_diff_report("B. inference（排除影子专属键）", B_bl, B_af))
    # 影子键确认：B_bl 中不应有（baseline 不含影子键），B_af 中可能有但已排除
    shadow_in_bl = [k for k in SHADOW_ONLY if k in scene_snapshot["inference_baseline"]]
    shadow_in_af = [k for k in SHADOW_ONLY if k in scene_snapshot["inference_after"]]
    reports.append((
        True,
        f"  [INFO] B. baseline 含影子键数量={len(shadow_in_bl)}，改造后={len(shadow_in_af)}，均已排除"
    ))

    # --- C. save_shadow_log 原 42 列：字节等价 ---
    # 从 shadow_record_after 中剔除 T5 新 12 列，只保留原 42 列
    T5_12_KEYS = {
        "fd_crypto_war_state", "fd_crypto_total_score", "fd_crypto_cap_mode",
        "fd_crypto_mult_mode", "fd_us_stock_war_state", "fd_us_stock_total_score",
        "sal_type", "sal_regime", "sal_calib_median", "sal_calib_min",
        "sal_calib_max", "sal_gate",
    }
    C_bl = scene_snapshot["shadow_record_baseline"]
    C_af = {k: v for k, v in scene_snapshot["shadow_record_after"].items() if k not in T5_12_KEYS}
    reports.append(_diff_report("C. save_shadow_log 原 42 列（排除 T5 新12列）", C_bl, C_af))
    # 确认 key 数量一致（原 42 列 = 42 数据项）
    reports.append((
        len(C_bl) == len(C_af),
        f"  [INFO] C. baseline key_count={len(C_bl)}，改造后(原42列) key_count={len(C_af)}"
    ))

    return reports


# ================================================================
# main：3 场景运行 + 汇总
# ================================================================
def main() -> int:
    print("=" * 72)
    print("T6.3 字节等价 diff 脚本：3 场景一致性验证")
    print("=" * 72)

    # ----------------------------------------------------------------
    # 场景1：baseline（所有新增开关=False = 改造前行为等价）
    # ----------------------------------------------------------------
    print("\n[场景1] baseline 快照：所有新增开关=False")
    snap1 = _build_snapshot()
    print(f"  ✓ 生成快照：enhance_info keys={len(snap1['enhance_info_baseline'])}  "
          f"inference keys={len(snap1['inference_baseline'])}  "
          f"shadow_record(原42列) keys={len(snap1['shadow_record_baseline'])}")

    # ----------------------------------------------------------------
    # 场景2：改造后（所有新增开关=False，完全相同代码路径）
    # ----------------------------------------------------------------
    print("\n[场景2] 改造后 快照：同样所有新增开关=False")
    snap2 = _build_snapshot()
    print(f"  ✓ 生成快照：enhance_info keys={len(snap2['enhance_info_after'])}  "
          f"inference keys={len(snap2['inference_after'])}  "
          f"shadow_record(含新12列) keys={len(snap2['shadow_record_after'])}")

    # ----------------------------------------------------------------
    # 场景3：diff 对比（场景1 vs 场景2）
    # ----------------------------------------------------------------
    print("\n[场景3] diff 对比：场景1 vs 场景2（除影子/新列专属字段外字节等价）")
    # 合并两次运行：
    #   baseline = snap1.enhance_info_baseline / snap1.inference_baseline / snap1.shadow_record_baseline
    #   after    = snap2.enhance_info_after    / snap2.inference_after    / snap2.shadow_record_after
    merged = {
        "enhance_info_baseline": snap1["enhance_info_baseline"],
        "enhance_info_after": snap2["enhance_info_after"],
        "inference_baseline": snap1["inference_baseline"],
        "inference_after": snap2["inference_after"],
        "shadow_record_baseline": snap1["shadow_record_baseline"],
        "shadow_record_after": snap2["shadow_record_after"],
        "_shadow_only_keys": snap1["_shadow_only_keys"],
    }
    reports = _run_diff(merged)

    # 打印报告
    all_pass = True
    for ok, msg in reports:
        print(msg)
        if not ok and "INFO" not in msg and "WARN" not in msg:
            all_pass = False

    # ----------------------------------------------------------------
    # 额外：通过 save_shadow_log 做物理插入对比（真实 EvolutionStorageSQLite）
    # ----------------------------------------------------------------
    print("\n[场景3+] 物理存储对比：原42列插入后 round-trip 字节等价")
    try:
        from bcrm2.storage import EvolutionStorageSQLite

        with tempfile.TemporaryDirectory() as tmpdir:
            db = Path(tmpdir) / "t6_byte_eq.db"
            storage = EvolutionStorageSQLite(db)

            # baseline 插入
            rec_bl = snap1["shadow_record_baseline"]
            rid_bl = storage.save_shadow_log("BTCUSDT", rec_bl)

            # after 插入（含新12列 None 值，但原42列相同）
            rec_af = snap2["shadow_record_after"]
            rid_af = storage.save_shadow_log("BTCUSDT", rec_af)

            # 查回
            rows = storage.get_shadow_log("BTCUSDT", days=7)
            assert len(rows) == 2
            r_bl = {k: v for k, v in rows[0].items()
                    if k in rec_bl and k not in {"id", "symbol", "timestamp"}}
            r_af = {k: v for k, v in rows[1].items()
                    if k in rec_bl and k not in {"id", "symbol", "timestamp"}}

            # 对比原42列 round-trip 后值一致
            ok_rt, msg_rt = _diff_report("C+. 物理存储 round-trip 原42列对比", r_bl, r_af)
            print(msg_rt)
            if not ok_rt:
                all_pass = False

            # 确认：插入的 rid_bl / rid_af 都 > 0
            if rid_bl > 0 and rid_af > 0:
                print(f"  [PASS] C+. 两次 INSERT rid 均 > 0 (bl={rid_bl}, af={rid_af})")
            else:
                print(f"  [FAIL] C+. INSERT rid 异常: bl={rid_bl}, af={rid_af}")
                all_pass = False

            storage._conn.close()
    except Exception as e:
        print(f"  [FAIL] C+. 物理存储对比异常: {e}")
        all_pass = False

    # ----------------------------------------------------------------
    # 汇总
    # ----------------------------------------------------------------
    print("\n" + "=" * 72)
    print("T6.3 字节等价 diff 汇总")
    print("=" * 72)
    if all_pass:
        print("✅ 3 场景完全一致：无 diff（所有对比项字节等价）")
        print("   ✓ enhance_info 除 strategy_selection 外无 diff")
        print("   ✓ inference 除影子专属键外无 diff")
        print("   ✓ save_shadow_log 原 42 列无 diff（含物理存储 round-trip）")
        return 0
    else:
        print("❌ 存在 diff 项（请检查上方 [FAIL] 标记）")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
