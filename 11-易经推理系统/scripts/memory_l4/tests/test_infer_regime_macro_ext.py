"""P2-02 TDD: PollingTrader._infer_regime 签名扩展 + macro_correction 集成

测试目标：
  1) 旧签名调用（不传 macro_features / enable_macro_correction）→ 与旧实现 byte-equivalent 输出
  2) enable_macro_correction=False → 即便 macro_features 里有高恐慌信号，也 100% 用旧推断结果
  3) enable_macro_correction=True → macro_高条件命中时，覆盖原推断结果
"""
import sys, os
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

# 用最小实例化（不传 config，走默认空 dataclass；避免真实盘口初始化）
try:
    # 我们只测 _infer_regime 纯逻辑，不需要连接交易所
    class _BareTrader(PollingTrader):
        def __init__(self):
            # 跳过父类 __init__ 的盘口初始化 — 直接初始化 instance 级字段即可
            pass  # _infer_regime 没有使用任何 self 属性（纯函数式实现），所以 bare 即可

    pt = _BareTrader()
except Exception as e:
    print(f"实例化失败: {type(e).__name__}: {e}")
    pt = None

if pt is None:
    sys.exit(1)

# ========================================================================
section("OLD-EQ — 旧签名（完全不传新参数）→ 输出完全等价旧推断")
# Case 1: 乾为天（纯乾卦，非横盘）→ TREND_UP_STRONG
r_old = pt._infer_regime("乾为天", False, "UP")
_chk("乾为天 + 非横盘 + 向上 → TREND_UP_STRONG", r_old == "TREND_UP_STRONG", f"实际={r_old}")

# Case 2: 艮为山（纯艮卦）→ CONSOLIDATION（艮=横盘整理）
r_old2 = pt._infer_regime("艮为山", False, "UP")
_chk("艮为山（纯艮）→ CONSOLIDATION", r_old2 == "CONSOLIDATION", f"实际={r_old2}")

# Case 3: 震卦 + is_ranging=True → TREND_UP_MILD 应降级为 RANGE_BOUND
r_old3 = pt._infer_regime("震为雷", True, "UP")
_chk("震为雷 + is_ranging=True → 降级 RANGE_BOUND", r_old3 == "RANGE_BOUND", f"实际={r_old3}")

# Case 4: 无卦象 + direction=DOWN + is_ranging=False → VOLATILE_DROP
r_old4 = pt._infer_regime("", False, "DOWN")
_chk("无卦 + DOWN → VOLATILE_DROP", r_old4 == "VOLATILE_DROP", f"实际={r_old4}")

# ========================================================================
section("S5-OFF — enable_macro_correction=False → 即便强 macro 信号也不覆盖")
macro_strong = {"liq_panic_score_0_to_1": 0.80,
                "liq_regime_hint": "VOLATILE_DROP",
                "btc_option_skew_sentiment": "FEAR_TAIL_PROTECTION",
                "btc_option_iv_level": "EXTREME"}

r_off = pt._infer_regime("乾为天", False, "UP", macro_features=macro_strong,
                         enable_macro_correction=False)
_chk("enable=False + 强 macro → 仍 TREND_UP_STRONG (不覆盖)",
      r_off == "TREND_UP_STRONG", f"实际={r_off}")

# 还必须和不带 macro_features 的完全等价
r_nomacro = pt._infer_regime("乾为天", False, "UP")
_chk("enable=False → 完全等价不传任何参数", r_off == r_nomacro, f"{r_off} vs {r_nomacro}")

# ========================================================================
section("S5-ON — enable_macro_correction=True（默认） + 强 macro → 覆盖")
# 极高恐慌 R1 触发：原乾→TREND_UP_STRONG 被覆盖为 VOLATILE_DROP
r_on = pt._infer_regime("乾为天", False, "UP", macro_features=macro_strong)
_chk("enable=True + panic=0.80 → VOLATILE_DROP（R1 覆盖）",
      r_on == "VOLATILE_DROP", f"实际={r_on}")

# 弱信号不覆盖：panic=0.2（CALM）→ 保持原卦象推断
macro_weak = {"liq_panic_score_0_to_1": 0.2}
r_weak = pt._infer_regime("乾为天", False, "UP", macro_features=macro_weak)
_chk("弱 macro → 仍 TREND_UP_STRONG（不覆盖）",
      r_weak == "TREND_UP_STRONG", f"实际={r_weak}")

# FOMO 场景：震为雷（BREAKOUT）+ 强 FOMO 信号 → FOMO_RALLY 覆盖
macro_fomo = {"liq_regime_hint": "FOMO_RALLY", "liq_panic_score_0_to_1": 0.55}
r_fomo = pt._infer_regime("震为雷", False, "UP", macro_features=macro_fomo)
_chk("震(BREAKOUT) + FOMO hint+panic=0.55 → FOMO_RALLY（R3 覆盖）",
      r_fomo == "FOMO_RALLY", f"实际={r_fomo}")

# 尾部保护 + 上涨家族 → REVERSAL
macro_tail = {"btc_option_skew_sentiment": "FEAR_TAIL_PROTECTION"}
r_tail = pt._infer_regime("风天小畜", False, "UP", macro_features=macro_tail)  # 下卦乾=TREND_UP_STRONG 家族
_chk("上涨卦象 + FEAR_TAIL → REVERSAL（R4 覆盖）",
      r_tail == "REVERSAL", f"实际={r_tail}")

# ========================================================================
section("GRACEFUL — FreeMarketFeed 全字段 None → 零错误，不覆盖")
macro_all_none = {"liq_panic_score_0_to_1": None,
                  "liq_regime_hint": None,
                  "btc_option_iv_level": None,
                  "btc_option_skew_sentiment": None,
                  "crypto_vix_proxy_pct": None}
try:
    r_grace = pt._infer_regime("坎为水", False, "DOWN", macro_features=macro_all_none)
    _chk("全 None 不抛异常 → 返回坎=VOLATILE_DROP（不覆盖）",
         r_grace == "VOLATILE_DROP", f"实际={r_grace}")
except Exception as e:
    _chk("全 None 不抛异常", False, f"{type(e).__name__}: {e}")

# ========================================================================
section("📊 汇总")
if _all_pass:
    print("全部测试 PASS ✅")
    sys.exit(0)
else:
    print("存在失败 ❌")
    sys.exit(1)
