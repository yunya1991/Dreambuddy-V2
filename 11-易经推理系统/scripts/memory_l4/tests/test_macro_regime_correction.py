"""TDD RED → GREEN for apply_macro_regime_correction (P2-01)

PURE 函数合同：
  apply_macro_regime_correction(base_regime: str,
                                macro_feats: dict,
                                strength: float = 0.6) -> str

修正规则（按优先级从高到低，命中即返回）：
  1. panic_score >= 0.70  (极高恐慌)        → VOLATILE_DROP  (覆盖一切 base)
  2. options_regime_hint=VOLATILE_DROP + iv_level>=HIGH  → VOLATILE_DROP
  3. liq_regime_hint=FOMO_RALLY + panic>=0.4 → FOMO_RALLY
  4. options_skew_sentiment=FEAR_TAIL_PROTECTION + base in TREND_UP 类 → REVERSAL
  5. options_skew_sentiment=FOMO_RALLY_CALL_BINGE + iv_level>=NORMAL → FOMO_RALLY
  6. 默认 → base_regime (不修正)

strength ∈ [0.0, 1.0] 控制覆盖倾向:
  strength=0.0 → 永不覆盖 (100% base passthrough, 即便触发条件)
  strength=1.0 → 命中即强制覆盖
  strength=0.6 → 默认: 规则 1/2 仍覆盖 (extreme conditions pass through always),
                  弱规则 3/4/5 需额外置信门槛 (panic 额外 +0.1, skew 要连中 2 条件)
"""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
# bcrm2 是 memory_l4 下的子包
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from bcrm2.market_regime import (
    apply_macro_regime_correction,
    VALID_8STATE_REGIMES,
)


def _chk(name, cond, detail=""):
    if cond:
        print(f"  [✅ PASS]  {name}")
    else:
        print(f"  [❌ FAIL]  {name}   {detail}")
        all_pass[0] = False
    return cond


def section(t):
    print(f"\n===== {t} =====")


all_pass = [True]

# ========================================================================
section("RED0 — 函数存在且返回 8 态之一（空 dict 不改 base）")
try:
    r = apply_macro_regime_correction("TREND_UP_STRONG", {})
    _chk("函数可调用且返回 str", isinstance(r, str), f"实际返回: {r!r}")
    _chk("空 macro_feats → 原样返回 base", r == "TREND_UP_STRONG", f"实际={r}")
    _chk("返回值 ∈ VALID_8STATE_REGIMES", r in VALID_8STATE_REGIMES, f"实际={r}")
except Exception as e:
    _chk("函数存在 (IMPORTS)", False, f"Exception: {type(e).__name__}: {e}")
    all_pass[0] = False

# ========================================================================
section("R1 — 爆仓极高恐慌 → VOLATILE_DROP（覆盖一切 base, strength≥0.3 生效）")
feats = {"liq_panic_score_0_to_1": 0.75, "liq_panic_level": "EXTREME_PANIC"}
r = apply_macro_regime_correction("TREND_UP_STRONG", feats, strength=0.6)
_chk("base=TREND_UP, panic=0.75 → VOLATILE_DROP (s=0.6)", r == "VOLATILE_DROP", f"实际={r}")
r = apply_macro_regime_correction("FOMO_RALLY", feats, strength=0.6)
_chk("base=FOMO_RALLY, panic=0.75 → VOLATILE_DROP 仍覆盖", r == "VOLATILE_DROP", f"实际={r}")
# 边界：panic=0.69 < 0.70 threshold → 不覆盖
r = apply_macro_regime_correction("TREND_UP_STRONG",
                                  {"liq_panic_score_0_to_1": 0.69},
                                  strength=0.6)
_chk("panic=0.69 < 阈值 0.70 → 不触发 R1", r == "TREND_UP_STRONG", f"实际={r}")
# strength=0.0 → 永不覆盖（即便条件满足）
r = apply_macro_regime_correction("TREND_UP_STRONG", feats, strength=0.0)
_chk("strength=0.0 → 即使 R1 条件满足也不覆盖", r == "TREND_UP_STRONG", f"实际={r}")

# ========================================================================
section("R2 — 期权链 VOLATILE_DROP 信号 + IV≥HIGH → VOLATILE_DROP")
feats = {"options_regime_hint": "VOLATILE_DROP",
         "btc_option_iv_level": "EXTREME",
         "crypto_vix_proxy_pct": 90.0}
r = apply_macro_regime_correction("TREND_UP_STRONG", feats, strength=0.6)
_chk("IV=EXTREME + options_regime=VOLATILE_DROP → VOLATILE_DROP",
      r == "VOLATILE_DROP", f"实际={r}")
# IV 仅 NORMAL → 即便 hint 是 VOLATILE_DROP 也不触发（缺高 IV 确认）
feats2 = {"options_regime_hint": "VOLATILE_DROP", "btc_option_iv_level": "NORMAL"}
r = apply_macro_regime_correction("TREND_UP_STRONG", feats2, strength=0.6)
_chk("IV=NORMAL + VOLATILE_DROP hint → 不触发 R2", r == "TREND_UP_STRONG", f"实际={r}")

# ========================================================================
section("R3 — 爆仓 regime_hint=FOMO_RALLY + panic≥0.4 → FOMO_RALLY")
feats = {"liq_regime_hint": "FOMO_RALLY", "liq_panic_score_0_to_1": 0.55}
r = apply_macro_regime_correction("RANGE_BOUND", feats, strength=0.6)
_chk("base=RANGE, FOMO hint + panic=0.55 → FOMO_RALLY", r == "FOMO_RALLY", f"实际={r}")
# 仅 hint，panic 不足 0.4 → 不触发
feats_w = {"liq_regime_hint": "FOMO_RALLY", "liq_panic_score_0_to_1": 0.30}
r = apply_macro_regime_correction("RANGE_BOUND", feats_w, strength=0.6)
_chk("FOMO hint 但 panic=0.30<0.4 → 不触发 R3", r == "RANGE_BOUND", f"实际={r}")

# ========================================================================
section("R4 — Skew=FEAR_TAIL_PROTECTION + base 是 TREND_UP* → REVERSAL（反转警示）")
feats = {"btc_option_skew_sentiment": "FEAR_TAIL_PROTECTION"}
r = apply_macro_regime_correction("TREND_UP_STRONG", feats, strength=0.6)
_chk("skew=FEAR_TAIL + base=TREND_UP_STRONG → REVERSAL",
      r == "REVERSAL", f"实际={r}")
r = apply_macro_regime_correction("TREND_UP_MILD", feats, strength=0.6)
_chk("skew=FEAR_TAIL + base=TREND_UP_MILD → REVERSAL",
      r == "REVERSAL", f"实际={r}")
# 非 TREND_UP 类 base → R4 不触发（例如 base=RANGE 不变）
r = apply_macro_regime_correction("RANGE_BOUND", feats, strength=0.6)
_chk("skew=FEAR_TAIL + base=RANGE → 不触发 R4", r == "RANGE_BOUND", f"实际={r}")

# ========================================================================
section("R5 — Skew=FOMO_RALLY_CALL_BINGE + IV≥NORMAL → FOMO_RALLY")
feats = {"btc_option_skew_sentiment": "FOMO_RALLY_CALL_BINGE",
         "btc_option_iv_level": "NORMAL"}
r = apply_macro_regime_correction("RANGE_BOUND", feats, strength=0.6)
_chk("CALL_BINGE + IV=NORMAL → FOMO_RALLY", r == "FOMO_RALLY", f"实际={r}")
feats_lo = {"btc_option_skew_sentiment": "FOMO_RALLY_CALL_BINGE",
            "btc_option_iv_level": "LOW"}
r = apply_macro_regime_correction("RANGE_BOUND", feats_lo, strength=0.6)
_chk("CALL_BINGE 但 IV=LOW → 不触发 R5", r == "RANGE_BOUND", f"实际={r}")

# ========================================================================
section("R6 — strength=1.0 vs strength=0.0 的灵敏度对比")
# 用弱规则 R3（FOMO hint + panic=0.41，刚好过线）做对比
feats_edge = {"liq_regime_hint": "FOMO_RALLY", "liq_panic_score_0_to_1": 0.41}
r_full = apply_macro_regime_correction("RANGE_BOUND", feats_edge, strength=1.0)
r_zero = apply_macro_regime_correction("RANGE_BOUND", feats_edge, strength=0.0)
r_def  = apply_macro_regime_correction("RANGE_BOUND", feats_edge, strength=0.6)
_chk("strength=1.0 → 命中覆盖", r_full == "FOMO_RALLY", f"实际={r_full}")
_chk("strength=0.0 → 100% passthrough", r_zero == "RANGE_BOUND", f"实际={r_zero}")
# 默认 0.6：弱规则门槛抬高（panic 需 ≥ 0.5 才在 s=0.6 触发 R3）
# 0.41 < 0.5 → 默认 strength=0.6 下 R3 不触发（保护：不轻易信弱信号）
_chk(f"strength=0.6 (默认) + panic=0.41 → 因 < 门槛 0.5 不触发 R3",
      r_def == "RANGE_BOUND", f"实际={r_def}")

# ========================================================================
section("R7 — 优先级排序验证（R1 > R3：即便 FOMO hint，极高恐慌仍赢）")
feats_conflict = {
    "liq_panic_score_0_to_1": 0.72,    # 触发 R1 → VOLATILE_DROP
    "liq_regime_hint": "FOMO_RALLY",   # 触发 R3 → FOMO_RALLY
    "liq_panic_level": "EXTREME_PANIC",
}
r = apply_macro_regime_correction("TREND_UP_STRONG", feats_conflict, strength=0.6)
_chk("R1 优先级高于 R3 → VOLATILE_DROP 胜出（更高优先级的极端风险）",
      r == "VOLATILE_DROP", f"实际={r}")

# ========================================================================
section("R8 — 缺失字段 / None 值 graceful：全 None → 不修正")
feats_missing = {"liq_panic_score_0_to_1": None,
                 "btc_option_iv_level": None,
                 "btc_option_skew_sentiment": None}
r = apply_macro_regime_correction("VOLATILE_DROP", feats_missing, strength=0.6)
_chk("全 None → 保持 base=VOLATILE_DROP 不变", r == "VOLATILE_DROP", f"实际={r}")
r = apply_macro_regime_correction("FOMO_RALLY", {}, strength=0.6)
_chk("空 dict → 不修正", r == "FOMO_RALLY", f"实际={r}")

# ========================================================================
section("📊 汇总")
if all_pass[0]:
    print("全部测试 PASS ✅")
    sys.exit(0)
else:
    print("存在失败 ❌ — 先 RED 成功，再写 GREEN 代码")
    sys.exit(1)
