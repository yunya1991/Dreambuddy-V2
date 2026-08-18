"""P2-03 + P2-04 TDD：_fetch_global_macro_features_once + REGIME_MULTIPLIERS

P2-03 测试合同：
  T1 方法存在，不抛异常，返回 dict
  T2 两次连续调用，第二次命中 cache（不再次实例化 FreeMarketFeed）
  T3 模拟 300s 过去 → 缓存过期，重新拉取
  T4 构造 FMF 抛异常的场景 → graceful 返回空 {}（不影响主链路）

P2-04 测试合同（Spec §5.1）：
  T5 S5=False → 所有 regime multipliers 全 1.0
  T6 S5=True + regime=VOLATILE_DROP → position≤0.40, sl≤0.75, tp≤0.80
  T7 S5=True + regime=FOMO_RALLY → tp≤0.70, sl≤0.80, threshold≤0.90
  T8 S5=True + regime=TREND_UP_STRONG → position≥1.10
  T9 非法 regime → fallback 全 1.0（不报错）
"""
import sys, os, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from scripts.memory_l4.polling_trader import PollingTrader


def _chk(name, cond, detail=""):
    if cond:
        print(f"  [✅ PASS]  {name}")
    else:
        print(f"  [❌ FAIL]  {name}   {detail}")
        globals()["_all_pass"] = False
    return cond


def section(t):
    print(f"\n===== {t} =====")


_all_pass = True


class _BareTrader(PollingTrader):
    """跳过 __init__，只测新增方法（避免交易所连接）"""
    def __init__(self):
        pass

pt = _BareTrader()

# ========================================================================
section("P2-03 T1 — _fetch_global_macro_features_once 存在 + 返回 dict 不抛错")
try:
    d = pt._fetch_global_macro_features_once()
    _chk("返回 dict 类型", isinstance(d, dict))
    _chk("含 liq_* 字段 OR 全空（网络 gating 允许）",
         ("liq_panic_score_0_to_1" in d) or len(d) == 0,
         f"keys={list(d.keys())[:6]}")
except Exception as e:
    _chk("方法存在且不抛异常", False, f"{type(e).__name__}: {e}")

# ========================================================================
section("P2-03 T2/T3 — 5 分钟缓存 TTL 逻辑（模拟时间，不真等 5min）")
# 重置 cache，用一个轻量 mock（不依赖 FMF）直接验证 TTL 结构
pt._macro_feature_cache = {"ts": time.time() - 10, "data": {"cached": True, "v": 1}}
d2 = pt._fetch_global_macro_features_once(cache_ttl_sec=300, _test_skip_network=True)
_chk("T2: 10s 前缓存（<300s TTL） → 命中缓存",
     d2.get("v") == 1 and d2.get("cached") is True, f"实际={d2}")
# 模拟 600 秒前的旧缓存 → 过期
pt._macro_feature_cache = {"ts": time.time() - 600, "data": {"cached": True, "v": 1}}
d3 = pt._fetch_global_macro_features_once(cache_ttl_sec=300, _test_skip_network=True)
# 缓存过期 → fallback 调用真实网络或空 dict
_chk("T3: 600s 前缓存（>300s TTL） → 过期，v != 1",
     d3.get("v") != 1 or "v" not in d3, f"实际={d3}")

# ========================================================================
section("P2-03 T4 — FMF 抛异常 → graceful 返回 {}，不冒泡")
import unittest.mock as mock
_original_import = __builtins__ if isinstance(__builtins__, dict) else __builtins__.__dict__
# 用 mock 让 collect_global 抛异常
class _FakeFeedThrows:
    def collect_global(self):
        raise RuntimeError("boom: network unreachable")

with mock.patch.object(pt, "_get_macro_feed_instance", return_value=_FakeFeedThrows()):
    # 清缓存，强制走 fetch
    pt._macro_feature_cache = {"ts": 0, "data": {}}
    try:
        d_fail = pt._fetch_global_macro_features_once(cache_ttl_sec=0)
        _chk("FMF 抛异常 → 返回空 dict", d_fail == {}, f"实际={d_fail}")
    except Exception as e:
        _chk("FMF 抛异常 → graceful 不冒泡", False, f"{type(e).__name__}: {e}")

# ========================================================================
section("P2-04 T5 — enable=False → 全 1.0（字节等价旧路径）")
m = pt._get_regime_pred_multipliers("TREND_UP_STRONG", enable_regime_pred=False)
_chk("S5=False 全 1.0",
     m.get("position_mult") == 1.0 and m.get("tp_mult") == 1.0
     and m.get("sl_mult") == 1.0 and m.get("threshold_mult") == 1.0,
     f"实际={m}")

# ========================================================================
section("P2-04 T6 — VOLATILE_DROP（暴跌） → 砍仓位 + 紧止损 + 松止盈 + 严入场")
m = pt._get_regime_pred_multipliers("VOLATILE_DROP")
_chk("VOLATILE_DROP position_mult ≤ 0.40", m.get("position_mult", 999) <= 0.40, f"{m}")
_chk("VOLATILE_DROP sl_mult ≤ 0.75（紧止损）", m.get("sl_mult", 999) <= 0.75, f"{m}")
_chk("VOLATILE_DROP tp_mult ≤ 0.80（落袋为安）", m.get("tp_mult", 999) <= 0.80, f"{m}")
_chk("VOLATILE_DROP threshold_mult ≥ 1.25（严入场）", m.get("threshold_mult", 0) >= 1.25, f"{m}")

# ========================================================================
section("P2-04 T7 — FOMO_RALLY → 小幅仓位 + 极紧止盈（过热兑现）")
m = pt._get_regime_pred_multipliers("FOMO_RALLY")
_chk("FOMO_RALLY tp_mult ≤ 0.70（极紧止盈，见好就收）", m.get("tp_mult", 999) <= 0.70, f"{m}")
_chk("FOMO_RALLY sl_mult ≤ 0.80（紧止损）", m.get("sl_mult", 999) <= 0.80, f"{m}")
_chk("FOMO_RALLY threshold_mult ≥ 1.10（严入场）", m.get("threshold_mult", 0) >= 1.10, f"{m}")

# ========================================================================
section("P2-04 T8 — TREND_UP_STRONG（强趋势） → 加仓 + 放止盈 + 松止损 + 宽门槛")
m = pt._get_regime_pred_multipliers("TREND_UP_STRONG")
_chk("TREND_UP_STRONG position_mult ≥ 1.10", m.get("position_mult", 0) >= 1.10, f"{m}")
_chk("TREND_UP_STRONG tp_mult ≥ 1.20（让利润奔跑）", m.get("tp_mult", 0) >= 1.20, f"{m}")
_chk("TREND_UP_STRONG sl_mult ≥ 1.10（松止损，留空间）", m.get("sl_mult", 0) >= 1.10, f"{m}")
_chk("TREND_UP_STRONG threshold_mult ≤ 0.85（宽门槛，顺势多入场）", m.get("threshold_mult", 999) <= 0.85, f"{m}")

# ========================================================================
section("P2-04 T9 — 非法 regime 字符串 → 全 1.0 fallback 不报错")
try:
    m = pt._get_regime_pred_multipliers("NOT_A_VALID_REGIME_XXX")
    _chk("非法 regime → 全 1.0 fallback",
         m.get("position_mult") == 1.0 and m.get("threshold_mult") == 1.0, f"{m}")
except Exception as e:
    _chk("非法 regime 不报错", False, f"{type(e).__name__}: {e}")

# ========================================================================
section("📊 汇总")
if _all_pass:
    print("全部测试 PASS ✅")
    sys.exit(0)
else:
    print("存在失败 ❌")
    sys.exit(1)
