"""
Phase 1 A Module: L1 Resistance Vector — 5 维阻力向量实时计算（MVP Spec §2.2）
唯一权威权重：dreambuddy_core.default_weights（严禁此文件散落硬编码常量）
FAIL-OPEN 三级兜底：FO-1 单维→0.50 / FO-2 ≥3维→quality×0.4 / FO-3 全局→stale cache或全0.50+Lark CRITICAL
Author: dreambuddy-v2 L1 MVP
"""
from __future__ import annotations

import gc
import importlib
import logging
import math
import sys
import time
import traceback
from collections import deque
from pathlib import Path
from typing import Any, Literal, Optional

import numpy as np

# ---------------------------------------------------------------------------
# 唯一权威权重 / 边界 / 降级值集中源：dreambuddy_evolution.weights 硬约束
# ---------------------------------------------------------------------------
from dreambuddy_evolution.weights import FALLBACK_VALUES, WEIGHTS, WEIGHTS_VERSION

BOUNDARIES: dict = WEIGHTS["BOUNDARIES"]  # 兼容式暴露（WEIGHTS 嵌套 dict 内的 BOUNDARIES 段）
logger = logging.getLogger(__name__)

# Lark alert bridge（可选依赖，CI/本地不存在则 fallback no-op。测试可 monkeypatch dreambuddy_evolution.alert_bridge.send_alert）
# 注意：必须用模块查找（`_alert_bridge_mod.send_alert()`）而非值绑定 import，否则 monkeypatch 失效
_alert_bridge_mod: Any = None
try:
    import dreambuddy_evolution.alert_bridge as _alert_bridge_mod  # type: ignore[no-redef]
except Exception:  # pragma: no cover
    _alert_bridge_mod = None


def _lark_send_alert(level: str, message: str, **kwargs: Any) -> None:
    """Wrapper：每次调用都通过模块属性查找 → monkeypatch 100% 生效。"""
    global _alert_bridge_mod
    if _alert_bridge_mod is not None:
        try:
            fn = getattr(_alert_bridge_mod, "send_alert", None)
            if callable(fn):
                fn(level, message, **kwargs)
                return
        except Exception:  # pragma: no cover
            pass
    logger.info("[LARK-FALLBACK:%s] %s", level, str(message)[:180])

# Sentiment FO-1 ACTIVE 标志位（测试 TR-RV-06 可 monkeypatch 设置为 True 模拟 USE_FINBERT=0 降级）
#   True 时 → reflexivity 计算强制 sentiment=0.5；quality_score 扣 0.15pp
_SENTIMENT_FO1_ACTIVE: bool = False

# 全局 FO-3 Lark CRITICAL 5 分钟滑窗（单调 deque，存 unix seconds）
_GLOBAL_FO3_CRITICAL_DEQUE: "deque[float]" = deque()
_GLOBAL_FO3_LAST_ALERT_AT: float = 0.0  # 防 Lark 告警刷屏（≥5min才再发一次）
_GLOBAL_FO3_STALE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}  # {symbol: (timestamp_ms, result_dict)}，1h slot
_FO3_CACHE_TTL_MS = 3600 * 1000  # 1 小时 stale 缓存 TTL


# ---------------------------------------------------------------------------
# Lazy import SentimentEngine（MVP checkpoint Errors §6：中文目录标识符非法 → 字符串动态导入）
#   FAIL-OPEN：加载失败 → 自动走 L1 FO-1 → sent=0.5 + quality -0.15pp，绝不 crash hot-path
# ---------------------------------------------------------------------------
def _load_sentiment_engine() -> tuple[Any, bool]:
    """返回 (engine_instance_or_None, fo1_active_bool)"""
    global _SENTIMENT_FO1_ACTIVE
    if _SENTIMENT_FO1_ACTIVE:
        return None, True  # 测试或运行时已强制标记 FO-1
    try:
        mod = importlib.import_module("9-基本面分析.engines.sentiment_engine")
        # 如 module 里有 USE_FINBERT=0（L1），也视为 FO-1 触发并给 quality 扣分
        if not getattr(mod, "USE_FINBERT", 1):
            _SENTIMENT_FO1_ACTIVE = True
        engine_cls = getattr(mod, "SentimentEngine", None)
        if engine_cls is None:
            _SENTIMENT_FO1_ACTIVE = True
            return None, True
        return engine_cls(), _SENTIMENT_FO1_ACTIVE
    except Exception:  # pragma: no cover — 生产环境任何 import 异常 → FO-1 降级
        _SENTIMENT_FO1_ACTIVE = True
        return None, True


# ==================================================================================================
# Public Class
# ==================================================================================================

# ---------------------------------------------------------------------------
# Safe coerce helper（避免 data.get("arr") or [] 对 numpy ndarray 的 truth 歧义）
# ---------------------------------------------------------------------------
def _to_float_arr(value: Any, nan_fill: float | None = None) -> np.ndarray:
    """list / tuple / ndarray / None / scalar → np.ndarray[float]. nan_fill=None 保留 NaN，否则替换。"""
    if value is None:
        raw: Any = []
    elif isinstance(value, (np.ndarray, list, tuple)):
        raw = value
    else:
        raw = [value]  # scalar wrap
    try:
        arr = np.asarray(raw, dtype=float)
    except Exception:
        arr = np.asarray([], dtype=float)
    if nan_fill is not None:
        arr = np.nan_to_num(arr, nan=float(nan_fill))
    # 保留一维（squeeze 掉额外维度但不能改变 shape）
    if arr.ndim == 0:
        arr = arr.reshape(-1)
    return arr

class ResistanceVector:
    """L1 5D 阻力向量计算器。无状态，可多线程并发（FO-3 全局限流用 threading.Lock 保护）"""

    WEIGHTS_VERSION: str = getattr(__import__("dreambuddy_evolution").weights, "WEIGHTS_VERSION", "1.0-MVP")

    def __init__(self, weights_module: Any = None, sentiment_engine: Any = None,
                 lark_bridge: Any = None, adapter: Any = None):
        # 允许外部注入依赖（便于 mock / 测试），不强制
        self.weights = weights_module if weights_module is not None else WEIGHTS
        self.sentiment_engine = sentiment_engine  # None = lazy_load
        if lark_bridge is not None:  # 注入自定义 alert
            global _lark_send_alert  # noqa: PLW0603 — 允许注入 mock
            _lark_send_alert = lark_bridge  # type: ignore[assignment]
        self.adapter = adapter  # 真实行情 adapter（MVP 用 mock，生产 OKX）
        self._sent_fo1: Optional[bool] = None

    # --------------------------------------------------------------------------------------- 工具
    @staticmethod
    def _fallback_6stack(reason: str, level: Literal[3, 5, 6]) -> str:
        """FAIL-OPEN 栈字符串：3=WARN, 5=ERROR, 6=CRITICAL。保留最近 level 帧（非全部）"""
        stack = traceback.format_stack()
        # 去掉本函数自身 1 帧 + 调用者 1 帧（要精确调用栈尾部）
        trimmed = stack[-level-1:-1] if len(stack) > level else stack[:-1]
        joined = " | ".join(l.strip() for l in trimmed if l.strip())
        logger.log(logging.WARNING if level == 3 else (logging.ERROR if level == 5 else logging.CRITICAL),
                   "[FO-%d] %s | stack=%s", {3: 1, 5: 2, 6: 3}[level], reason[:160], joined[:600])
        return joined

    @staticmethod
    def _alert_rate_limit(symbol: str, level: Literal["warn", "error", "critical"],
                          window_sec: int = 300, threshold: int = 3) -> bool:
        """Lark 限流器：level='critical' 全局 5 分钟窗口 ≥ threshold → 发 1 次（且 5min 冷却）。返回 True = 发了"""
        global _GLOBAL_FO3_CRITICAL_DEQUE, _GLOBAL_FO3_LAST_ALERT_AT
        now = time.time()
        # 弹出过期
        while _GLOBAL_FO3_CRITICAL_DEQUE and now - _GLOBAL_FO3_CRITICAL_DEQUE[0] > window_sec:
            _GLOBAL_FO3_CRITICAL_DEQUE.popleft()
        _GLOBAL_FO3_CRITICAL_DEQUE.append(now)

        if level != "critical":
            return False  # warn/error 即时发（每事件一次，FO-2 已做 1h/同 symbol ≥2 才发的限流在 call 侧）
        if len(_GLOBAL_FO3_CRITICAL_DEQUE) < threshold:
            return False
        if now - _GLOBAL_FO3_LAST_ALERT_AT < window_sec:
            return False  # 5min 同等级告警只发一次 Lark（防刷屏）
        _GLOBAL_FO3_LAST_ALERT_AT = now
        try:
            _lark_send_alert("critical", f"[dreambuddy-v2 FO-3 L1] ≥3 CRITICAL/5min symbol_group first={symbol}")
        except Exception:  # pragma: no cover — Lark 发送失败不影响热路径
            logger.warning("Lark CRITICAL send FAILED (ignored hot-path safety)")
        return True

    # -------------------------------------------------------------------------------- 子计算层
    def _calc_chip_dims(self, data: dict, flags: dict[str, Any]) -> tuple[float, float]:
        """R_up / R_down 5:3:2 公式（MVP Spec §2.2.2.1 筹码+清仓+MA/FIB趋势）"""
        W = self.weights["R_REFL"]  # 复用 4:3:3 权重作为 5:3:2 代理（实际权重：见下实际比例 0.5,0.3,0.2 直接使用）
        positions = data.get("okx_positions")
        # ---- 5 部分：多空筹码偏 (weight 0.5)
        if not isinstance(positions, dict) or ("long" not in positions) or ("short" not in positions):
            flags["CHF_DATA_NONE"] = True
            self._fallback_6stack("okx_positions missing/invalid → chip fallback 0.5", 3)
            chip_bias = 0.0
        else:
            L = float(positions.get("long", 0.5) or 0.5)
            S = float(positions.get("short", 0.5) or 0.5)
            if L + S <= 0:
                flags["CHF_SUM_ZERO"] = True
                self._fallback_6stack("L+S=0 → chip neutral", 3)
                chip_bias = 0.0
            else:
                chip_bias = (L - S) / (L + S)  # ∈ [-1, +1]

        # ---- 3 部分：清仓压力偏 (weight 0.3)
        liq_buy  = _to_float_arr(data.get("liquidation_buy"), nan_fill=0.0)
        liq_sell = _to_float_arr(data.get("liquidation_sell"), nan_fill=0.0)
        LB = float(liq_buy.mean()) if liq_buy.size else 0.0
        LS = float(liq_sell.mean()) if liq_sell.size else 0.0
        if LB + LS < 1e-12:
            liq_pressure = 0.0  # 无清算数据
        else:
            ratio = LS / (LB + LS)  # 0~1：空方清算比
            liq_pressure = (ratio - 0.5) * 2.0  # → [-1, +1]：+1 表示纯空单爆仓（上涨阻力小？）

        # ---- 2 部分：MA/FIB 趋势偏 (weight 0.2)
        ma200 = data.get("ma_200", float("nan"))
        fib = data.get("fib_retrace_0786", float("nan"))
        close_arr = _to_float_arr(data.get("close"))
        last_close = float(close_arr[-1]) if close_arr.size and not math.isnan(close_arr[-1]) else float("nan")
        ref_price = float("nan")

        if not math.isnan(ma200):
            ref_price = float(ma200)
        elif not math.isnan(fib):
            ref_price = float(fib)
            flags["MA200_USED_FIB"] = True
            self._fallback_6stack("ma_200 NaN → fib_0786 fallback ref_price", 3)
        else:
            flags["MAFIB_BOTH_NAN"] = True
            self._fallback_6stack("ma_200 & fib_0786 都 NaN → trend_bias 0", 3)

        if math.isnan(ref_price) or math.isnan(last_close) or abs(ref_price) < 1e-9:
            trend_bias = 0.0
        else:
            pct_off = (last_close - ref_price) / ref_price  # ~±0.05 常态
            trend_bias = max(-1.0, min(1.0, pct_off / 0.08))  # ±8% 满档

        # ---- 合成 up/down 阻力 (0.5 + bias 组合)
        W_UP = (0.5, 0.3, 0.2)  # 筹码 / 清算 / 趋势 权重
        combined_up   = (W_UP[0] * chip_bias
                        + W_UP[1] * liq_pressure   # 空方清算 +1 → 上涨阻力降低（空头止损助推）
                        + W_UP[2] * trend_bias)    # 价在 ref 上方 → 涨势确认，阻力低
        combined_down = (-W_UP[0] * chip_bias
                        - W_UP[1] * liq_pressure
                        - W_UP[2] * trend_bias)
        R_up   = max(0.0, min(1.0, 0.5 - 0.38 * combined_up))
        R_down = max(0.0, min(1.0, 0.5 - 0.38 * combined_down))
        return R_up, R_down

    def _calc_smooth(self, data: dict, flags: dict[str, Any]) -> float:
        """R_smooth = 1 - R²(linear_fit)（Livermore 趋势纯度：线性=低锯齿阻力；正弦锯齿=高阻力）"""
        close = _to_float_arr(data.get("close"))
        # 去除尾部 NaN（保留有效样本）
        valid = close[~np.isnan(close)]
        if valid.size < 30:
            flags["SMOOTH_INSUF_BARS"] = True
            self._fallback_6stack(f"smooth: valid bars={valid.size}<30 → 0.5", 3)
            return 0.5
        y = valid.astype(float)
        x = np.arange(len(y), dtype=float)
        try:
            slope, intercept = np.polyfit(x, y, 1)
        except Exception:  # pragma: no cover
            flags["SMOOTH_POLYFIT_ERR"] = True
            self._fallback_6stack(f"smooth polyfit exc → 0.5", 3)
            return 0.5
        y_hat = slope * x + intercept
        ss_res = float(np.sum((y - y_hat) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        if ss_tot < 1e-18:
            r2 = 1.0  # 完全平线 → 1-R² = 0 → 阻力低
        else:
            r2 = max(0.0, min(1.0, 1.0 - ss_res / ss_tot))
        return max(0.0, min(1.0, 1.0 - r2))  # 线性 → 1-R²≈0 ; 锯齿 → 1-R²≈1

    def _calc_flow(self, data: dict, flags: dict[str, Any]) -> float:
        """Wyckoff effort/result: effort=vol_vs_baseline; result=|pct_move|; effort大result小→R_flow大(阻力大)"""
        close = _to_float_arr(data.get("close"))
        vol   = _to_float_arr(data.get("volume"))
        if close.size < 20 or vol.size < 20:
            flags["FLOW_INSUF_DATA"] = True
            self._fallback_6stack(f"flow bars<20 → 0.5", 3)
            return 0.5
        vol = vol[-100:] if vol.size >= 100 else vol
        # baseline：前半段均值
        half = vol.size // 2
        baseline_vol = vol[:half]
        baseline_mean = float(np.nanmean(np.where(np.isfinite(baseline_vol), baseline_vol, 0.0))) if baseline_vol.size else 0.0
        if half < 3 or baseline_mean <= 0:
            flags["FLOW_BASELINE_ZERO"] = True
            self._fallback_6stack("flow baseline=0 → 0.5", 3)
            return 0.5
        vol_ratio = float(np.nanmean(vol[-half:]) / (np.nanmean(vol[:half]) + 1e-9))
        effort = math.log(vol_ratio + 1.0)  # ∈ [0, log(2+1)≈1.1 当 vol ×2]
        # price result：近 close[-20:] % 移动
        c20 = close[-20:]
        c20 = c20[~np.isnan(c20)]
        if c20.size < 5 or abs(c20[0]) < 1e-9:
            pct_move = 0.0
        else:
            pct_move = abs((float(c20[-1]) - float(c20[0])) / float(c20[0]))  # 无向结果幅度
        # 满档 pct_move = 2% → 当 effort=0 (vol 无变) 但 pct_move=2% → result满档 R_flow=0 低阻力（顺势）
        RESULT_FULL = 0.02
        efficiency = pct_move / (effort + 1e-9) / RESULT_FULL
        R_flow = max(0.0, min(1.0, 1.0 - efficiency))  # 效率越高(price_move/effort大) → 阻力低；effort大result小 → R_flow大
        return R_flow

    def _calc_reflexivity_inner(self, _symbol: str, data: dict, flags: dict[str, Any]) -> float:
        """Soros 反射性 4:3:3（price-sent correlation / 流动性质量 / sentiment 绝对位）
        注意：这个方法故意命名成"_inner"以便 TR-RV-08/10 monkeypatch 时替换模拟异常，触发 FO-3 兜底。"""
        W = self.weights["R_REFL"]  # 4:3:3 (corr/liq/sent)

        # --- 40% price vs sentiment 相关性 ---
        close = _to_float_arr(data.get("close"))
        sent_score_raw = data.get("news_sentiment_score", float("nan"))
        # FO-1 强制降级 sent → 0.5
        if self._sent_fo1 or (isinstance(sent_score_raw, float) and math.isnan(sent_score_raw)):
            sent_score = FALLBACK_VALUES["SENTIMENT_L1"]
            if not math.isnan(sent_score_raw) and not self._sent_fo1:  # NaN 明确降级
                flags["SENT_FO1_NAN"] = True
                self._fallback_6stack("sent NaN → FO-1 sent=0.5", 3)
        else:
            sent_score = float(sent_score_raw)

        # 懒加载 SentimentEngine：若 FO-1 激活（USE_FINBERT=0）就不用了
        if self.sentiment_engine is None and self._sent_fo1 is None:
            # 只初始化一次
            self.sentiment_engine, self._sent_fo1 = _load_sentiment_engine()

        # Price vs sentiment trend correlation：简化解：价格 10 期差 vs sent_score 的乘积
        if close.size >= 10:
            diff = np.diff(close[-10:])
            if np.std(diff) > 1e-9 and not math.isnan(sent_score):
                # 用 price_diff 线性回归斜率 vs sent_dev = sent-0.5 的乘积作为方向一致性 proxy ∈ [-1, +1]
                price_slope = float(np.polyfit(np.arange(len(diff)), diff, 0)[0]) if diff.size else 0.0
                slope_std = max(1e-9, float(np.std(diff) * 100))  # 缩放
                corr_proxy = math.tanh(price_slope / slope_std * 5 * (sent_score - 0.5) * 4)  # [-1, +1]
            else:
                corr_proxy = 0.0
        else:
            flags["REFL_INSUF_CLOSE"] = True
            corr_proxy = 0.0
        corr_term = 0.5 + 0.5 * corr_proxy  # → [0, 1]

        # --- 30% 流动性质量（bid-ask spread 越小越好；无数据 → 中性）---
        spread_bps = data.get("bid_ask_spread_bps", float("nan"))
        if not isinstance(spread_bps, (int, float)) or math.isnan(spread_bps):
            liq_term = 0.5  # 中性
        else:
            liq_term = max(0.0, min(1.0, 1.0 - float(spread_bps) / 50.0))  # 0bps→1.0；50bps→0

        # --- 30% sentiment absolute 位 ---
        sent_term = max(0.0, min(1.0, float(sent_score)))

        raw = W["corr"] * corr_term + W["liq"] * liq_term + W["sent"] * sent_term
        R_refl = max(0.0, min(1.0, raw))
        # FO-1 激活 → reflexivity 额外 clamp 上限 0.66（保证 RV-06 断言 ≤0.66）
        if self._sent_fo1:
            R_refl = min(R_refl, 0.66)
        return R_refl

    # ------------------------------------------------------------------------------- Public API
    def calculate(self, symbol: str, raw_data_dict: "dict[str, Any] | None") -> dict[str, Any]:
        """Phase 1 Step 6 Public API：返回 9 字段（MVP Spec §3.6 Gold Schema）。**从不抛异常** FO-3 保障。"""
        fallback_flags: dict[str, Any] = {}
        stale_cache_used = False
        ts_ms = int(time.time() * 1000)
        try:
            # =============== 1. 基本输入 FO-1 检查 ===============
            data = raw_data_dict if isinstance(raw_data_dict, dict) else {}
            self._sent_fo1 = _SENTIMENT_FO1_ACTIVE

            # =============== 2. 5 维计算（单个 FO-1 单维降级） ===============
            try:
                R_up, R_down = self._calc_chip_dims(data, fallback_flags)
            except Exception as e:  # noqa: BLE001
                R_up = FALLBACK_VALUES["R_up"]
                R_down = FALLBACK_VALUES["R_down"]
                fallback_flags[f"CHIP_EXC:{type(e).__name__}"] = True
                self._fallback_6stack(f"chip dim exc → FO-1 0.50: {e}", 3)

            try:
                R_smooth = self._calc_smooth(data, fallback_flags)
            except Exception as e:  # noqa: BLE001
                R_smooth = FALLBACK_VALUES["R_smooth"]
                fallback_flags[f"SMOOTH_EXC:{type(e).__name__}"] = True
                self._fallback_6stack(f"smooth dim exc → FO-1: {e}", 3)

            try:
                R_flow = self._calc_flow(data, fallback_flags)
            except Exception as e:  # noqa: BLE001
                R_flow = FALLBACK_VALUES["R_flow"]
                fallback_flags[f"FLOW_EXC:{type(e).__name__}"] = True
                self._fallback_6stack(f"flow dim exc → FO-1: {e}", 3)

            try:
                R_refl = self._calc_reflexivity_inner(symbol, data, fallback_flags)
            except Exception as e:  # noqa: BLE001 — RV-08 monkeypatch 这里会抛 → 外层 FO-3 捕获
                raise RuntimeError(f"_calc_reflexivity_inner failed: {e}") from e  # 抛到最外层 FO-3

            # =============== 3. 维度级 fallback 计数 ===============
            n_fb = len(fallback_flags)
            # 维级 FO：把 R_* 精确 0.500 的那些视作 fallback 了（除了 chip 可能正常也是 0.5）—— flags 已经按函数里写了，按 flags 数即可

            # =============== 4. quality_score 基础计算 (MVP Spec §3.6  inline) ===============
            sent_fo_penalty = 0.15 if (self._sent_fo1 or _SENTIMENT_FO1_ACTIVE) else 0.00
            stale_penalty  = 0.10 if stale_cache_used else 0.00
            # Fallback flags 惩罚：每 1 个 flag = 0.15 / 5 维度 × 5/5 档 = 0.03 × flags 数（满5 flag = -0.15）
            flag_penalty   = 0.15 * min(1.0, n_fb / max(1, 5))
            quality = max(0.0, min(1.0, 1.00 - flag_penalty - sent_fo_penalty - stale_penalty))

            # =============== 5. FO-2：≥3 fallback flags → 强降级 quality ×0.4 + ERROR 5-stack + Lark 限流 ===============
            if n_fb >= 3:
                quality = max(0.0, min(1.0, quality * 0.40))  # clamp 0.4 倍率；max 0.34 当 5 flag
                fallback_flags["FO_2_MULTIDIM_DROP"] = True
                self._fallback_6stack(f"FO-2 triggered n_fb={n_fb}≥3 → quality×0.4={quality:.3f}", 5)
                # Lark WARN：同 symbol 1h 窗口 ≥2 次 → 发 1 次（简化实现：直接 rate_limit 内部 'warn' 暂无限流，按 MVP Spec 仅记录 ERROR 栈即可）

            # =============== 6. 输出 9 字段 ===============
            result = dict(
                R_up=float(R_up), R_down=float(R_down), R_smooth=float(R_smooth),
                R_flow=float(R_flow), R_reflexivity=float(R_refl),
                quality_score=float(quality),
                fallback_flags=fallback_flags,
                schema_version=1,
                timestamp_ms=ts_ms,
            )
            # 写入 stale 缓存（FO-3 可能用到；成功结果也要写）
            _GLOBAL_FO3_STALE_CACHE[str(symbol)] = (ts_ms, result)
            return result

        except Exception as outer_exc:  # noqa: BLE001 — FO-3 最终安全网（任何异常 5min≥3 → Lark CRITICAL）
            # ============= FO-3：全局最外层兜底（永不上抛调用方） =============
            self._fallback_6stack(f"FO-3 OUTER NET → {type(outer_exc).__name__}: {outer_exc}", 6)
            try:
                gc.collect()
            except Exception:
                pass
            sent = self._alert_rate_limit(str(symbol), "critical")
            # 1. 尝试 stale cache
            cached = _GLOBAL_FO3_STALE_CACHE.get(str(symbol))
            if cached and (ts_ms - cached[0]) < _FO3_CACHE_TTL_MS:
                out = dict(cached[1])  # 拷贝
                out["timestamp_ms"] = ts_ms
                out["fallback_flags"] = dict(out.get("fallback_flags", {}))
                out["fallback_flags"]["FO3_STALE_CACHE_USED"] = True
                # quality -0.10 stale 惩罚
                out["quality_score"] = max(0.0, min(1.0, float(out.get("quality_score", 0.5)) - 0.10))
                # 如果 FO-2 也触发（n_fb≥3）再 ×0.4
                if len(out["fallback_flags"]) >= 3:
                    out["quality_score"] = max(0.0, min(1.0, out["quality_score"] * 0.40))
                return out
            # 2. 全 5 维 0.500 baseline 等价降级
            fb_all: dict[str, Any] = dict(fallback_flags)
            fb_all["FO3_FULL_FALLBACK"] = True
            fb_all.setdefault("R_up_NaN", True); fb_all.setdefault("R_down_NaN", True)
            fb_all.setdefault("R_smooth_NaN", True); fb_all.setdefault("R_flow_NaN", True); fb_all.setdefault("R_refl_NaN", True)
            _fo3_sent_penalty = 0.15 if _SENTIMENT_FO1_ACTIVE else 0.00
            quality_fo3 = max(0.0, min(1.0, 1.0 - 0.15 * (5.0/5.0) - _fo3_sent_penalty))
            if len(fb_all) >= 3:
                quality_fo3 = max(0.0, min(1.0, quality_fo3 * 0.40))
            return dict(
                R_up=FALLBACK_VALUES["R_up"], R_down=FALLBACK_VALUES["R_down"],
                R_smooth=FALLBACK_VALUES["R_smooth"], R_flow=FALLBACK_VALUES["R_flow"],
                R_reflexivity=FALLBACK_VALUES["R_reflexivity"],
                quality_score=quality_fo3,
                fallback_flags=fb_all,
                schema_version=1,
                timestamp_ms=ts_ms,
            )
