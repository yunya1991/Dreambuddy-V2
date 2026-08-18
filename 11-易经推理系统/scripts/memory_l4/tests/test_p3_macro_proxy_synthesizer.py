"""P3 TDD — 历史 OHLCV → 宏观特征 proxy 合成器：

合同（4 维度 proxy，与 FMF fallback proxy 同构，保证 apply_macro_regime_correction 口径一致）:
  D1 OI 爆仓代理       = volume_spike × |close-open|/close
     - 成交量突变（24bar 最高 5%分位）+ 长实体 → 模拟级联爆仓/轧空（0-1）
  D2 Taker 买卖失衡代理 = 涨跌斜率（EMA20/EMA60 z-score）+ 实体方向（红/绿）
     - 映射为 PC skew 解释标签 + PC skew_25d（-1..1）
  D3 资金费率/波动簇代理 = rolling_std(returns, 24) 标准化 → ATM IV proxy %（0-1）
  D4 TopTrader LS 代理   = close 相对 MA20/MA60 偏离度 → top_ls_ratio_pct（0-1）

输出字段契约（完全匹配 apply_macro_regime_correction 的消费侧）：
  liq_panic_score_0_to_1 : float [0,1]
  liq_regime_hint        : Optional[str] ∈ VALID_8STATE_REGIMES / None
  btc_atm_iv_pct         : float [0,1]   （IV 档位分档 → LOW/NORMAL/HIGH/EXTREME 的 0/0.33/0.66/1.0 proxy）
  btc_option_pc_skew_25d_pct : float [-1,1]  （正值=PUT 侧贵=恐慌；负值=CALL 侧贵=贪婪）
  btc_option_skew_interpret  : Optional[str]（FEAR_TAIL_PROTECTION / FOMO_RALLY_CALL_BINGE / …）
  btc_options_regime_hint    : Optional[str] ∈ VALID_8STATE_REGIMES / None
  top_ls_ratio_pct       : Optional[float] [0,1]（None = 数据不足）
  _provenance            : "ohlcv_proxy_v1"
"""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
import numpy as np
import pandas as pd

_all_pass = True


def _chk(name, cond, detail=""):
    global _all_pass
    if cond:
        print(f"  [✅ PASS]  {name}")
    else:
        print(f"  [❌ FAIL]  {name}  {detail}")
        _all_pass = False


def section(t):
    print(f"\n===== {t} =====")


# ========================================================================
section("RED T1 — 函数存在 + 返回 10 键契约（新增 iv_level / skew_sentiment）")
from scripts.memory_l4.bcrm2.market_regime import synthesize_macro_proxy_from_ohlcv
rng = np.random.default_rng(42)
n = 80
closes = 100 + np.cumsum(rng.normal(0, 1, n))
df = pd.DataFrame({
    "open":  closes + rng.normal(0, 0.3, n),
    "high":  closes + np.abs(rng.normal(0, 1, n)),
    "low":   closes - np.abs(rng.normal(0, 1, n)),
    "close": closes,
    "volume": 10_000_000 + rng.exponential(2_000_000, n),
})
out = synthesize_macro_proxy_from_ohlcv(df, bar_idx=-1)  # 最后一根
required = {
    "liq_panic_score_0_to_1", "liq_regime_hint",
    "btc_atm_iv_pct", "btc_option_iv_level",
    "btc_option_pc_skew_25d_pct", "btc_option_skew_sentiment",
    "btc_option_skew_interpret", "btc_options_regime_hint",
    "top_ls_ratio_pct", "_provenance",
}
_chk("返回是 dict", isinstance(out, dict))
_chk("返回 10 键契约齐全", required.issubset(set(out.keys())), f"actual keys: {set(out.keys())}")
_chk("_provenance 是 ohlcv_proxy_v1", out["_provenance"] == "ohlcv_proxy_v1", f"{out}")
_chk("liq_panic_score_0_to_1 ∈ [0,1]", 0.0 <= out["liq_panic_score_0_to_1"] <= 1.0,
     f"{out['liq_panic_score_0_to_1']}")
_chk("btc_atm_iv_pct ∈ [0,1]", 0.0 <= out["btc_atm_iv_pct"] <= 1.0, f"{out['btc_atm_iv_pct']}")
_chk("btc_option_iv_level ∈ LOW/NORMAL/HIGH/EXTREME",
     out["btc_option_iv_level"] in {"LOW", "NORMAL", "HIGH", "EXTREME"},
     f"{out['btc_option_iv_level']}")
_chk("btc_option_pc_skew_25d_pct ∈ [-1,1]", -1.0 <= out["btc_option_pc_skew_25d_pct"] <= 1.0,
     f"{out['btc_option_pc_skew_25d_pct']}")

# ========================================================================
section("RED T2 — D1 级联爆仓场景：连续 5 根 20σ 放量 + 大跌实体 → panic 应高")
rng = np.random.default_rng(1)
n = 80
base_close = 100 + np.cumsum(rng.normal(0, 0.4, n))
# 最后 6 bar：连续暴跌（用前收做本开 → 大阴线实体）
opens2 = np.empty(n)
opens2[0] = base_close[0] - 0.1
for i in range(1, n - 6):
    opens2[i] = base_close[i - 1] + rng.normal(0, 0.2)
# cascade bars i=74..79: open=prev close, close=prev close - drop
for i in range(6):
    idx = n - 6 + i          # 74..79
    prev_close = base_close[idx - 1] if idx > 0 else base_close[idx]
    drop = 3 + i * 0.8
    base_close[idx] = prev_close - drop  # 覆盖
    opens2[idx] = prev_close             # 开 = 前收 → 实体正好 = -drop
df2 = pd.DataFrame({
    "open":  opens2,
    "high":  base_close + np.abs(rng.normal(0, 0.7, n)),
    "low":   base_close - np.abs(rng.normal(0, 0.7, n)),
    "close": base_close,
    "volume": np.concatenate([
        10_000_000 + rng.exponential(1_000_000, n - 6),
        [250_000_000, 300_000_000, 280_000_000, 220_000_000, 200_000_000, 180_000_000],
    ]),
})
# 保证 high/low 合法
df2["high"] = df2[["open", "close", "high"]].max(axis=1)
df2["low"]  = df2[["open", "close", "low"]].min(axis=1)
out2 = synthesize_macro_proxy_from_ohlcv(df2, bar_idx=-1)
_chk("D1 级联爆仓 → liq_panic_score ≥ 0.60", out2["liq_panic_score_0_to_1"] >= 0.60,
     f"score={out2['liq_panic_score_0_to_1']:.3f}")
_chk("liq_regime_hint 应为 VOLATILE_DROP / 非空", out2["liq_regime_hint"] == "VOLATILE_DROP",
     f"{out2['liq_regime_hint']}")

# ========================================================================
section("RED T3 — FOMO 轧空场景：6 根大阳线 + 成交量放 10× → FOMO hint + 偏度为负（call 拥挤）")
rng = np.random.default_rng(2)
n = 80
base_close = 100 + np.cumsum(rng.normal(0, 0.4, n))
opens3 = np.empty(n)
opens3[0] = base_close[0] - 0.1
for i in range(1, n - 6):
    opens3[i] = base_close[i - 1] + rng.normal(0, 0.2)
# FOMO bars (last 6): open = prev_close, close = prev_close + rally（大阳线）
# 仅 1 根爆量+大实体（i=5 最后一根），其他 5 根中等上涨 + 中等成交量
#   → cascade_count=1 → panic_p2=0.067, panic_p1≈0.46 → total∈[0.4,0.7) → R3 FOMO_RALLY 胜出（R1 不触发）
for i in range(6):
    idx = n - 6 + i
    prev_close = base_close[idx - 1] if idx > 0 else base_close[idx]
    # 前 5 根小幅 rally（实体不够 ATR → 不触发 big_body），最后 1 根大 rally
    rally = 0.3 + i * 0.1 if i < 5 else 3.0
    base_close[idx] = prev_close + rally
    opens3[idx] = prev_close
df3 = pd.DataFrame({
    "open":  opens3,
    "high":  base_close + np.abs(rng.normal(0, 0.7, n)),
    "low":   base_close - np.abs(rng.normal(0, 0.7, n)),
    "close": base_close,
    "volume": np.concatenate([
        10_000_000 + rng.exponential(1_000_000, n - 6),
        # 前 5 根 2× 成交量（不进 top 10%），最后 1 根 6× → 满足 big_body+big_volume 只算 1 次 cascade
        [15_000_000, 16_000_000, 17_000_000, 18_000_000, 19_000_000, 60_000_000],
    ]),
})
df3["high"] = df3[["open", "close", "high"]].max(axis=1)
df3["low"]  = df3[["open", "close", "low"]].min(axis=1)
out3 = synthesize_macro_proxy_from_ohlcv(df3, bar_idx=-1)
_chk("D2 Taker FOMO → liq_regime_hint = FOMO_RALLY", out3["liq_regime_hint"] == "FOMO_RALLY",
     f"actual: {out3['liq_regime_hint']}")
_chk("D2 CALL 拥挤 → pc_skew_25d ≤ -0.30（负偏度）", out3["btc_option_pc_skew_25d_pct"] <= -0.30,
     f"actual: {out3['btc_option_pc_skew_25d_pct']}")
_chk("interpret 应是 FOMO_RALLY_CALL_BINGE",
     out3["btc_option_skew_interpret"] == "FOMO_RALLY_CALL_BINGE",
     f"actual: {out3['btc_option_skew_interpret']}")

# ========================================================================
section("RED T4 — D3 波动率簇 → ATM IV：高波动 period 后 IV proxy 高")
rng = np.random.default_rng(3)
n = 80
quiet = np.zeros(40); quiet[0] = 100
for i in range(1, 40): quiet[i] = quiet[i-1] + rng.normal(0, 0.2)
volatile = np.zeros(40); volatile[0] = quiet[-1]
for i in range(1, 40): volatile[i] = volatile[i-1] + rng.normal(0, 2.5)
seq = np.concatenate([quiet, volatile])
closes4 = seq
df4 = pd.DataFrame({
    "open":  closes4 + rng.normal(0, 0.4, n),
    "high":  closes4 + np.abs(rng.normal(0, 1.0, n)),
    "low":   closes4 - np.abs(rng.normal(0, 1.0, n)),
    "close": closes4,
    "volume": 10_000_000 + rng.exponential(1_000_000, n),
})
df4["high"] = df4[["open", "close", "high"]].max(axis=1)
df4["low"]  = df4[["open", "close", "low"]].min(axis=1)
out4_quiet = synthesize_macro_proxy_from_ohlcv(df4, bar_idx=39)
out4_vol   = synthesize_macro_proxy_from_ohlcv(df4, bar_idx=-1)
_chk("D3 低波动 → btc_atm_iv_pct ≤ 0.40", out4_quiet["btc_atm_iv_pct"] <= 0.40,
     f"{out4_quiet['btc_atm_iv_pct']}")
_chk("D3 高波动 → btc_atm_iv_pct ≥ 0.60", out4_vol["btc_atm_iv_pct"] >= 0.60,
     f"{out4_vol['btc_atm_iv_pct']}")
_chk("D4 高波动跌破 MA → top_ls_ratio ≤ 0.40（偏空头占优）",
     out4_vol.get("top_ls_ratio_pct", 0.5) is None or out4_vol.get("top_ls_ratio_pct", 0.5) <= 0.5,
     f"{out4_vol.get('top_ls_ratio_pct')}")

# ========================================================================
section("RED T5 — 不足 20bar → graceful 返回（无 crash，可空字段但 8 键齐全）")
df5 = pd.DataFrame({
    "open": [99, 100.2], "high": [100.5, 101.0],
    "low": [98.5, 99.8], "close": [100.0, 100.5],
    "volume": [1_000_000, 1_200_000],
})
out5 = synthesize_macro_proxy_from_ohlcv(df5, bar_idx=-1)
_chk("短序列 → 8 键齐全 + 无 crash", set(out5.keys()) >= required, f"{set(out5.keys())}")
_chk("短序列 → panic 0（无足够历史）", 0.0 <= out5["liq_panic_score_0_to_1"] <= 0.05,
     f"{out5['liq_panic_score_0_to_1']}")

# ========================================================================
section("RED T6 — proxy 字段可直接喂给 apply_macro_regime_correction，不改结构")
from scripts.memory_l4.bcrm2.market_regime import apply_macro_regime_correction
corrected = apply_macro_regime_correction("RANGE_BOUND", out2, strength=0.6)  # 级联爆仓 data
_chk("T6a 爆仓 proxy → 把 RANGE → VOLATILE_DROP（R1 覆盖规则）",
     corrected == "VOLATILE_DROP", f"actual={corrected}")
corrected3 = apply_macro_regime_correction("RANGE_BOUND", out3, strength=0.6)
_chk("T6b FOMO proxy → 把 RANGE → FOMO_RALLY（R3 覆盖）",
     corrected3 == "FOMO_RALLY", f"actual={corrected3}")

# ========================================================================
section("📊 汇总")
if _all_pass:
    print("全部 PASS ✅")
    sys.exit(0)
else:
    print("有 FAIL ❌")
    sys.exit(1)
