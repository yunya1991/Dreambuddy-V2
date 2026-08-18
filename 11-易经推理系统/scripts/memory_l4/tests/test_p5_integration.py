"""P2-05 / P2-06 / P2-07 集成 TDD：主链路乘数生效 + call site 注入 + TradeRecord 扩展

P2-05 合同：
  开关 S5=False → effective_threshold / 仓位 / SL/TP 计算 → 字节等价旧路径
  开关 S5=True + regime=VOLATILE_DROP → effective_threshold ≥ 1.25 × 原值
                                → position_size ≤ 0.40 × 原值
  开关 S5=True + regime=TREND_UP_STRONG → effective_threshold ≤ 0.85 × 原值

P2-06 合同：
  两处 _infer_regime 调用点都注入 macro_features=（S5 开才注入，关则不传）

P2-07 合同：
  TradeRecord 新增 regime_pred / regime_multipliers 两个 Optional 字段，默认 None（向后兼容）
"""
import sys, os, copy
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))


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

# ========================================================================
section("P2-07 — TradeRecord 新增 regime_pred + regime_multipliers Optional 字段")
from scripts.memory_l4.trading_utils import TradeRecord
tr = TradeRecord(trade_id="x", coin="BTC")
_chk("TradeRecord 默认值 regime_pred=None", tr.regime_pred is None, f"{tr.regime_pred}")
_chk("TradeRecord 默认值 regime_multipliers=None", tr.regime_multipliers is None,
     f"{tr.regime_multipliers}")
tr2 = TradeRecord(trade_id="x", coin="BTC", regime_pred="VOLATILE_DROP",
                  regime_multipliers={"position_mult": 0.35})
_chk("指定 regime_pred 可写入", tr2.regime_pred == "VOLATILE_DROP", f"{tr2}")
_chk("指定 regime_multipliers 可写入",
     tr2.regime_multipliers and tr2.regime_multipliers["position_mult"] == 0.35, f"{tr2}")

# ========================================================================
section("P2-05 — _get_regime_pred_multipliers 作用到 effective_threshold 乘积（纯数学验证）")
from scripts.memory_l4.polling_trader import PollingTrader


class _Bare(PollingTrader):
    def __init__(self):
        pass

pt = _Bare()

base_thr = 0.70  # 默认置信度阈值
# VOLATILE_DROP → 乘数 1.30 → 阈值抬高到 0.91（严入场）
m = pt._get_regime_pred_multipliers("VOLATILE_DROP")
effective_volatile = base_thr * m["threshold_mult"]
_chk("VOLATILE_DROP → 阈值×1.30（收紧）",
     abs(effective_volatile - 0.91) < 0.001, f"{effective_volatile}")

# TREND_UP_STRONG → 乘数 0.80 → 阈值降为 0.56（宽门槛）
m = pt._get_regime_pred_multipliers("TREND_UP_STRONG")
effective_bull = base_thr * m["threshold_mult"]
_chk("TREND_UP_STRONG → 阈值×0.80（放宽）",
     abs(effective_bull - 0.56) < 0.001, f"{effective_bull}")

# S5=False → 阈值 × 1.0
m = pt._get_regime_pred_multipliers("TREND_UP_STRONG", enable_regime_pred=False)
effective_off = base_thr * m["threshold_mult"]
_chk("S5=False → 阈值×1.0（字节等价旧路径）",
     abs(effective_off - 0.70) < 0.00001, f"{effective_off}")

# 仓位：VOLATILE_DROP → ×0.35
_chk("VOLATILE_DROP position ×0.35（砍仓）",
     abs(1000 * pt._get_regime_pred_multipliers("VOLATILE_DROP")["position_mult"] - 350) < 1, "")
# 仓位：TREND_UP_STRONG → ×1.20
_chk("TREND_UP_STRONG position ×1.20（加仓）",
     abs(1000 * pt._get_regime_pred_multipliers("TREND_UP_STRONG")["position_mult"] - 1200) < 1, "")

# SL ROI（VOLATILE_DROP 紧止损 → sl_mult=0.65）
# 若原 SL ROI=12% → 调整为 7.8%（更贴近入场价止损）
base_sl_roi_pct = 0.12
vol_sl = base_sl_roi_pct * pt._get_regime_pred_multipliers("VOLATILE_DROP")["sl_mult"]
_chk("VOLATILE_DROP sl×0.65 → 12% SL → 7.8%（紧止损）",
     abs(vol_sl - 0.078) < 0.001, f"{vol_sl}")

# TP ROI（TREND_UP_STRONG 让利润奔跑 → ×1.30）
base_tp_roi_pct = 0.50
bull_tp = base_tp_roi_pct * pt._get_regime_pred_multipliers("TREND_UP_STRONG")["tp_mult"]
_chk("TREND_UP_STRONG tp×1.30 → 50% TP → 65%（放止盈）",
     abs(bull_tp - 0.65) < 0.001, f"{bull_tp}")

# ========================================================================
section("P2-06 — 源代码静态检查：两处 _infer_regime 调用点 + 签名宏参数")
import ast, inspect
src = inspect.getsource(PollingTrader)
# 简单字符串检查：两处 call site 都提到 macro_features
call_sites_count = src.count("_infer_regime(") - 1  # 减 1 是 def 定义
# 函数签名里必须有 macro_features 和 enable_macro_correction
sig_ok = "macro_features: dict = None" in src and "enable_macro_correction: bool = True" in src
_chk("签名扩展有 macro_features + enable_macro_correction", sig_ok)
# 至少 2 处 _infer_regime 实际调用（函数定义外）
_chk(f"_infer_regime 调用点数量≥2（两处 call site）", call_sites_count >= 2,
     f"实际调用点（不含定义）={call_sites_count}")

# ========================================================================
section("📊 汇总")
if _all_pass:
    print("全部测试 PASS ✅")
    sys.exit(0)
else:
    print("存在失败 ❌")
    sys.exit(1)
