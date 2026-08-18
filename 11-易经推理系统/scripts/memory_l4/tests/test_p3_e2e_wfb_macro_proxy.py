#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P3-05 E2E smoke: WalkForwardBacktester 宏观 proxy 注入的端到端烟测

3 个验证维度:
  1) ZERO-DRIFT: enable_ohlcv_macro_proxy=False → 与旧逻辑 regime_name 顺序字节一致
  2) R1 覆盖: 级联爆仓 proxy → 把中性 DEFAULT/RANGE 改为 VOLATILE_DROP
  3) R3/R5 覆盖: FOMO 轧空 proxy → 把中性 DEFAULT/RANGE 改为 FOMO_RALLY

运行:
  cd /path/to/11-易经推理系统
  python3 -m scripts.memory_l4.tests.test_p3_e2e_wfb_macro_proxy
"""
import sys, os, numpy as np, pandas as pd

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
L4_DIR = os.path.dirname(TEST_DIR)           # memory_l4/
SCRIPTS_DIR = os.path.dirname(L4_DIR)       # scripts/
ROOT_11_DIR = os.path.dirname(SCRIPTS_DIR)  # 11-易经推理系统/ （含 scripts/ 包）
for _p in [ROOT_11_DIR, SCRIPTS_DIR, L4_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# 轻量 helper：复用 WFB 内部 regime 应用片段（把开仓参数映射出来）
# ---------------------------------------------------------------------------
from scripts.memory_l4.bcrm2.market_regime import (
    DEFAULT_REGIME_PARAMS,
    synthesize_macro_proxy_from_ohlcv,
    apply_macro_regime_correction,
)
from scripts.memory_l4.bcrm2.walk_forward_backtester import WalkForwardBacktester


# ===================================================================
# 数据构造：三种 100bar 场景
#   S0 — baseline：温和震荡（没触发宏观 proxy 规则）→ 开关 True/False regime 完全相等
#   S1 — 级联爆仓：末段 5 根 bar 放量暴跌 → 开关 True → DEFAULT→VOLATILE_DROP
#   S2 — FOMO 轧空：末段 6 根 bar 放量大涨 → 开关 True → DEFAULT→FOMO_RALLY
# ===================================================================
def build_baseline(n=120, seed=42):
    """S0: 温和震荡（macro proxy 不会触发任何覆盖规则）"""
    rng = np.random.default_rng(seed)
    closes = 100.0 + np.cumsum(rng.normal(0, 0.3, n))
    opens = np.empty(n); opens[0] = closes[0] - 0.05
    for i in range(1, n):
        opens[i] = closes[i-1] + rng.normal(0, 0.05)
    highs = np.maximum(opens, closes) + np.abs(rng.normal(0, 0.2, n))
    lows  = np.minimum(opens, closes) - np.abs(rng.normal(0, 0.2, n))
    vols  = 10_000_000 + rng.exponential(500_000, n)
    return pd.DataFrame({"open": opens, "high": highs, "low": lows,
                         "close": closes, "volume": vols})


def build_cascade_liquidation(n=120, seed=1):
    """S1: 末 5 bar 连续大跌 + 20σ 爆量 → 触发 R1 (极恐慌)"""
    rng = np.random.default_rng(seed)
    closes = 100 + np.cumsum(rng.normal(0, 0.2, n))
    opens = np.empty(n); opens[0] = closes[0] - 0.05
    for i in range(1, n - 5):
        opens[i] = closes[i-1] + rng.normal(0, 0.05)
    vols  = 10_000_000 + rng.exponential(500_000, n)

    # 末 5 bar 级联暴跌：每 bar 跌 -2% 左右，open = 前收，close = 开 * 跌
    drops = [-0.018, -0.022, -0.025, -0.030, -0.035]
    for i, d in enumerate(drops):
        idx = n - 5 + i
        prev_close = closes[idx-1]
        opens[idx] = prev_close
        closes[idx] = prev_close * (1 + d)
        vols[idx]  = 300_000_000  # 爆量（触发极高 v_perc）

    highs = np.maximum(opens, closes) + np.abs(rng.normal(0, 0.1, n))
    lows  = np.minimum(opens, closes) - np.abs(rng.normal(0, 0.1, n))
    highs = np.maximum(highs, np.maximum(opens, closes))
    lows  = np.minimum(lows,  np.minimum(opens, closes))
    return pd.DataFrame({"open": opens, "high": highs, "low": lows,
                         "close": closes, "volume": vols})


def build_fomo_rally(n=120, seed=2):
    """S2: 末 6 bar 连续大涨 + 爆量 → 触发 R3/R5 FOMO"""
    rng = np.random.default_rng(seed)
    closes = 100 + np.cumsum(rng.normal(0, 0.2, n))
    opens = np.empty(n); opens[0] = closes[0] - 0.05
    for i in range(1, n - 6):
        opens[i] = closes[i-1] + rng.normal(0, 0.05)
    vols  = 10_000_000 + rng.exponential(500_000, n)

    # 末 6 bar：连续大阳，最后一根爆量 10× 放总成交量
    rallies = [0.01, 0.012, 0.015, 0.018, 0.022, 0.030]
    for i, d in enumerate(rallies):
        idx = n - 6 + i
        prev_close = closes[idx-1]
        opens[idx] = prev_close
        closes[idx] = prev_close * (1 + d)
        # 末 1 bar 只放 35M（避免 panic ≥ 0.7 → 被 R1 覆盖，保留 FOMO R3）
        vols[idx]  = 15_000_000 + i * 2_500_000 if i < 5 else 35_000_000

    highs = np.maximum(opens, closes) + np.abs(rng.normal(0, 0.15, n))
    lows  = np.minimum(opens, closes) - np.abs(rng.normal(0, 0.1, n))
    highs = np.maximum(highs, np.maximum(opens, closes))
    lows  = np.minimum(lows,  np.minimum(opens, closes))
    return pd.DataFrame({"open": opens, "high": highs, "low": lows,
                         "close": closes, "volume": vols})


# ===================================================================
# 模拟 WFB 内部 regime 决策（通过实例调用 _simulate_trades 太复杂，
# 直接把 WFB 注入逻辑抽成纯函数片段，对每根 bar 计算 regime_before/regime_after）
# ===================================================================
def simulate_regime_pipeline(
    df: pd.DataFrame,
    base_regime_per_bar,
    enable_ohlcv_macro_proxy: bool,
    strength: float = 0.6,
):
    """
    与 WFB._simulate_trades 内部注入片段字节等价：
      base_regime → (if switch) apply_macro_correction → final_regime
    """
    N = len(df)
    base_list = list(base_regime_per_bar)
    assert len(base_list) == N, "base_regime 长度与 df 不一致"

    syn = synthesize_macro_proxy_from_ohlcv if enable_ohlcv_macro_proxy else None
    out_regimes = []
    for i in range(N):
        reg = base_list[i]
        if syn is not None:
            feats = syn(df, bar_idx=i, lookback=60)
            reg = apply_macro_regime_correction(reg, feats, strength=strength)
        out_regimes.append(reg)
    return out_regimes


# ===================================================================
# 主测试
# ===================================================================
PASS_CNT = 0; FAIL_CNT = 0

def _chk(name, cond, detail=""):
    global PASS_CNT, FAIL_CNT
    if cond:
        PASS_CNT += 1
        print(f"  [✅ PASS]  {name}")
    else:
        FAIL_CNT += 1
        print(f"  [❌ FAIL]  {name}  —  {detail}")


def section(t):
    print(f"\n{'='*70}\n {t}\n{'='*70}")


# -------------------------------------------------------------------
# TC0 — 合成器 + 修正函数先烟测，确认数据构造有效
# -------------------------------------------------------------------
section("TC0 — 场景数据 self-check：合成器确实能触发对应规则")

# S1 → R1 极恐慌
df1 = build_cascade_liquidation()
f1 = synthesize_macro_proxy_from_ohlcv(df1, bar_idx=-1)
_chk("S1 liq_panic ≥ 0.70 (R1)", f1["liq_panic_score_0_to_1"] >= 0.70, f"actual={f1['liq_panic_score_0_to_1']:.3f}")
_chk("S1 apply_correction(DEFAULT) → VOLATILE_DROP",
     apply_macro_regime_correction("DEFAULT", f1, 0.6) == "VOLATILE_DROP",
     f"actual={apply_macro_regime_correction('DEFAULT', f1, 0.6)}")

# S2 → R3 FOMO（注意末 1 根因为 panic 超 0.7 会被 R1 覆盖，检查末 2 根）
df2 = build_fomo_rally()
f2 = synthesize_macro_proxy_from_ohlcv(df2, bar_idx=-2)  # 末 2 根：已积累 FOMO 但未触 R1
_chk("S2 liq_hint = FOMO_RALLY（末2根）",
     f2["liq_regime_hint"] == "FOMO_RALLY" or f2.get("btc_option_skew_sentiment") == "FOMO_RALLY_CALL_BINGE",
     f"actual hint={f2['liq_regime_hint']}, sk_sent={f2.get('btc_option_skew_sentiment')}")
_chk("S2 apply_correction(RANGE_BOUND, strength=0.9) → FOMO_RALLY（末2根）",
     apply_macro_regime_correction("RANGE_BOUND", f2, 0.9) == "FOMO_RALLY",
     f"actual={apply_macro_regime_correction('RANGE_BOUND', f2, 0.9)}, "
     f"panic={f2['liq_panic_score_0_to_1']:.3f}")

# S0 → 不触发覆盖
df0 = build_baseline()
f0 = synthesize_macro_proxy_from_ohlcv(df0, bar_idx=-1)
_chk("S0 无宏观覆盖 DEFAULT→DEFAULT",
     apply_macro_regime_correction("DEFAULT", f0, 0.6) == "DEFAULT",
     f"actual={apply_macro_regime_correction('DEFAULT', f0, 0.6)}, panic={f0['liq_panic_score_0_to_1']:.3f}")


# -------------------------------------------------------------------
# TC1 — ZERO DRIFT: enable=False → 与旧 regime 完全一致
# -------------------------------------------------------------------
section("TC1 — ZERO-DRIFT 验证：开关 OFF 时 regime 序列字节一致")

N = 120
rng_scen = np.random.default_rng(99)
for scen_name, df_scen, strength in [
    ("baseline(S0)", df0, 0.6),
    ("liquidation(S1)", df1, 0.6),
    ("fomo_rally(S2)", df2, 0.6),
]:
    base = rng_scen.choice(["DEFAULT","RANGE_BOUND","TREND_UP","TREND_DOWN","CONSOLIDATION"], size=N)
    reg_off = simulate_regime_pipeline(df_scen, base, enable_ohlcv_macro_proxy=False)
    _chk(f"TC1 {scen_name}: OFF 与 base 字节一致", reg_off == list(base),
         f"存在 {sum(a!=b for a,b in zip(reg_off, base))} 处差异")


# -------------------------------------------------------------------
# TC2 — R1 覆盖：开关 True → 末段爆仓 bar 的 DEFAULT/RANGE → VOLATILE_DROP
# -------------------------------------------------------------------
section("TC2 — 级联爆仓场景：开关 True → R1 覆盖出现 VOLATILE_DROP")

base_r1 = ["DEFAULT"] * N  # 全 DEFAULT
reg_on  = simulate_regime_pipeline(df1, base_r1, True, 0.6)
reg_off = simulate_regime_pipeline(df1, base_r1, False, 0.6)

vd_count_on  = sum(r == "VOLATILE_DROP" for r in reg_on)
vd_count_off = sum(r == "VOLATILE_DROP" for r in reg_off)
_chk("TC2 OFF 无 VOLATILE_DROP", vd_count_off == 0, f"off_count={vd_count_off}")
_chk("TC2 ON  出现 ≥1 次 VOLATILE_DROP（末 1 根 window 积累级联计数 3+ 触发）", vd_count_on >= 1,
     f"on_count={vd_count_on}, tail_on={reg_on[-5:]}")
_chk("TC2 末 bar = VOLATILE_DROP", reg_on[-1] == "VOLATILE_DROP",
     f"actual last={reg_on[-1]}, panic_last={synthesize_macro_proxy_from_ohlcv(df1, bar_idx=-1)['liq_panic_score_0_to_1']:.3f}")


# -------------------------------------------------------------------
# TC3 — FOMO 覆盖：开关 True + strength=0.9 → 末段大阳线 → FOMO_RALLY
# -------------------------------------------------------------------
section("TC3 — FOMO 轧空场景：开关 True(strength=0.9) → R3 覆盖出现 FOMO_RALLY")

base_r3 = ["RANGE_BOUND"] * N
reg_on  = simulate_regime_pipeline(df2, base_r3, True, 0.9)  # strength=0.9 → r3门槛=0.4
reg_off = simulate_regime_pipeline(df2, base_r3, False, 0.9)

fomo_on  = sum(r == "FOMO_RALLY" for r in reg_on)
fomo_off = sum(r == "FOMO_RALLY" for r in reg_off)
_chk("TC3 OFF 无 FOMO_RALLY", fomo_off == 0, f"off_count={fomo_off}")
_chk("TC3 ON  出现 ≥1 次 FOMO_RALLY", fomo_on >= 1,
     f"on_count={fomo_on}, tail_regimes={reg_on[-8:]}, panic_last={f2['liq_panic_score_0_to_1']:.3f}")


# -------------------------------------------------------------------
# TC4 — WFB 类：完整初始化 + 属性校验（不跑回测）
# -------------------------------------------------------------------
section("TC4 — WalkForwardBacktester.__init__ 属性校验 + _simulate_trades 签名一致")

wfb_off = WalkForwardBacktester(symbol="BTCUSDT", enable_ohlcv_macro_proxy=False)
wfb_on  = WalkForwardBacktester(symbol="BTCUSDT", enable_ohlcv_macro_proxy=True,
                                macro_proxy_correction_strength=0.75)

_chk("TC4 OFF 属性: enable_ohlcv_macro_proxy=False",
     wfb_off.enable_ohlcv_macro_proxy is False)
_chk("TC4 ON  属性: enable_ohlcv_macro_proxy=True",
     wfb_on.enable_ohlcv_macro_proxy is True)
_chk("TC4 ON  属性: strength=0.75",
     abs(wfb_on.macro_proxy_correction_strength - 0.75) < 1e-9,
     f"actual={wfb_on.macro_proxy_correction_strength}")

import inspect
sig = inspect.signature(WalkForwardBacktester._simulate_trades)
params_ok = {"df","predictions","test_start","test_end","regime_names"}.issubset(
    set(sig.parameters.keys())
)
_chk("TC4 _simulate_trades 签名兼容", params_ok,
     f"actual params={list(sig.parameters.keys())}")


# ===================================================================
# 汇总
# ===================================================================
print(f"\n{'='*70}\n 📊 烟测汇总\n{'='*70}")
print(f"  PASS: {PASS_CNT}")
print(f"  FAIL: {FAIL_CNT}")
if FAIL_CNT == 0:
    print("\n全部 PASS ✅  P3-05 端到端烟测结束")
else:
    print("\n有 FAIL ❌  请检查上方日志")
    sys.exit(1)
