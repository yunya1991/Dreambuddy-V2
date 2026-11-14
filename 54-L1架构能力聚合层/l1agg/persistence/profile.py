# -*- coding: utf-8 -*-
"""延续性画像聚合：A1–A7 + A8 条件分布扩展 → 单一 profile。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import align
from . import metrics as M
from .constants import CAVEAT, KIND, MIN_N, PersistenceError


@dataclass
class PersistenceProfile:
    symbol: str
    span: str = ""
    sample_n: int = 0
    metrics: dict = field(default_factory=dict)
    quality: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "kind": KIND,
            "symbol": self.symbol,
            "span": self.span,
            "sample_n": self.sample_n,
            "metrics": self.metrics,
            "quality": self.quality,
            "caveat": CAVEAT,
            "text": self._text(),
        }

    def _text(self) -> str:
        m = self.metrics
        parts = [f"{self.symbol} 近 {self.sample_n} 个交易日延续性画像（{self.span}）"]

        h = m.get("hurst") or {}
        if h.get("h") is not None:
            if h.get("regime_displayable"):
                label = {"persistent": "持续", "anti_persistent": "反持续", "random_walk": "随机"}[
                    h["regime"]
                ]
                parts.append(f"Hurst={h['h']}（{label}，置信度 {h['confidence']}）")
            else:
                # 评审 §6 反对 2：低置信度不展示 regime 标签，避免误导
                parts.append(f"Hurst={h['h']}（口径敏感，仅参考，不作结论）")

        vr = m.get("variance_ratio") or []
        if vr:
            parts.append("、".join(f"VR({v['q']})={v['vr']}" for v in vr))

        a = m.get("ar1") or {}
        if a.get("phi") is not None:
            hl = a.get("halflife_days")
            parts.append(
                f"AR(1) φ={a['phi']}"
                + (f"，半衰期 {hl} 日" if hl is not None else "，无有效半衰期")
            )

        r = m.get("runs") or {}
        if r.get("n_runs"):
            parts.append(f"最长连涨/连跌={r['max_up']}/{r['max_down']} 日")

        t = m.get("transition") or {}
        if t.get("p_up_up") is not None:
            parts.append(f"P(涨|涨)={t['p_up_up']}，P(跌|跌)={t['p_down_down']}")

        s = m.get("trend") or {}
        if s.get("t") is not None:
            parts.append(f"趋势斜率 t={s['t']}（R²={s['r2']}，t 未做自相关修正）")

        ic = m.get("ic_decay") or {}
        if ic.get("items"):
            seg = "、".join(
                f"h={it['h']} IC={it['ric']}" for it in ic["items"] if it.get("ric") is not None
            )
            if seg:
                parts.append(f"动量 IC：{seg}")

        a8 = m.get("conditional_distribution") or {}
        result = a8.get("result") or {}
        horizons = result.get("by_horizon") or []
        current = horizons[0] if horizons else {}
        if current.get("effective_n"):
            downgrade = (
                "4 桶非重叠样本不足，降为 2 桶；"
                if a8.get("buckets") != a8.get("requested_buckets")
                else ""
            )
            insufficient = "，每桶非重叠样本未达 250" if a8.get("gate") != "ok" else ""
            parts.append(
                f"{downgrade}波动率同状态后 1 日：均值 {current['mean'] * 100:+.2f}%，"
                f"中位 {current['median'] * 100:+.2f}%，80% 历史区间 "
                f"[{current['p10'] * 100:+.2f}%, {current['p90'] * 100:+.2f}%]，"
                f"上涨 {current['win_rate'] * 100:.1f}%（{a8['buckets']} 桶，"
                f"有效 n={current['effective_n']}，非重叠 n={current['nonoverlap_n']}{insufficient}）"
            )
        elif a8:
            parts.append("波动率同状态条件分布样本不足")

        q = self.quality
        if q.get("status") != "good":
            parts.append(f"[降级：{q.get('degraded_reason') or q.get('status')}]")
        parts.append(CAVEAT)
        return "；".join(parts) + "。"


def conditional_distribution(
    prices,
    dates=None,
    *,
    window: int = MIN_N,
    vol_window: int = 20,
    min_bucket_n: int = MIN_N,
) -> dict:
    """A8：I30 波动状态经 R02 PIT 分桶，检查所有桶后执行 4→2 降级。"""
    from ..methods import run as run_method
    from ..methods.technical import rolling_volatility

    out = {
        "gate": "insufficient_samples",
        "state": "volatility",
        "state_method": "I30",
        "method": "R02",
        "h": 1,
        "requested_buckets": 4,
        "buckets": 4,
        "min_bucket_nonoverlap_n": min_bucket_n,
        "vol_window": vol_window,
        "degraded_reason": None,
        "result": None,
    }
    try:
        run_method("I30", {"close": prices}, window=vol_window, lookback=window)
        vols = rolling_volatility(prices, vol_window)
        offset = len(prices) - len(vols)
        aligned_prices = [float(v) for v in prices[offset:]]
        if dates is None:
            timestamps = list(range(len(vols)))
        else:
            if len(dates) != len(prices):
                raise ValueError("dates length must equal prices length")
            timestamps = [
                v.isoformat() if hasattr(v, "isoformat") else str(v) for v in dates[offset:]
            ]
        data = {
            "indicator": vols,
            "price": aligned_prices,
            "timestamps": timestamps,
            "align_method": align.ALIGN_METHOD,
        }

        def evaluate(buckets: int):
            envelope = run_method(
                "R02",
                data,
                buckets=buckets,
                horizons=(1,),
                label="滚动波动率",
                pit=True,
                window=window,
            )
            result = envelope.get("result")
            passed = bool(result) and all(
                row["nonoverlap_n"] >= min_bucket_n for row in result["by_horizon"][0]["by_bucket"]
            )
            return envelope, passed

        four, four_passed = evaluate(4)
        if four.get("gate") != "ok":
            out.update(buckets=2, degraded_reason=four["gate"])
            return out
        if four_passed:
            out.update(gate="ok", result=four["result"])
            return out

        two, two_passed = evaluate(2)
        out.update(
            gate="ok" if two_passed else "insufficient_samples",
            buckets=2,
            degraded_reason="bucket_nonoverlap_lt_250",
            result=two.get("result"),
        )
        return out
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        out.update(buckets=2, degraded_reason=f"{type(exc).__name__}: {exc}")
        return out


def build_profile(
    db_path: str,
    symbol: str = "BTC",
    *,
    days: int = 1200,
    min_n: int = MIN_N,
    vr_qs=(2, 5, 10, 20),
    ic_horizons=(1, 5, 20),
) -> dict:
    """组装单资产延续性画像（A1–A7），所有失败项返回 None 并写 reason。"""
    prices_map = align.load_price(db_path, symbol, days)
    dates = sorted(prices_map)
    prices = [prices_map[d] for d in dates]
    span = f"{dates[0]}~{dates[-1]}" if dates else ""
    rets = align.log_returns(prices)
    n = len(rets)

    metrics: dict = {}
    errors: dict = {}

    def run(name, fn):
        try:
            metrics[name] = fn()
        except (PersistenceError, ZeroDivisionError, ValueError) as exc:
            metrics[name] = None
            errors[name] = f"{type(exc).__name__}: {exc}"

    run("hurst", lambda: M.hurst_rs(rets))
    run("variance_ratio", lambda: [M.variance_ratio(rets, q) for q in vr_qs])
    run("ar1", lambda: M.ar1_halflife(rets))
    run("runs", lambda: M.run_length_stats(rets))
    run("transition", lambda: M.transition_matrix(rets))
    run("trend", lambda: M.trend_slope(prices))
    run("ic_decay", lambda: M.ic_decay(prices, horizons=ic_horizons))
    # A8 有独立的 T0.5 样本门禁，不改变 A1–A7 的 quality.status 语义。
    metrics["conditional_distribution"] = conditional_distribution(prices, dates)

    if n < min_n:
        status, degraded = "partial", "insufficient_samples"
    elif errors:
        # 样本够但方法失败：不能报 good，否则与 degraded_reason 自相矛盾
        status, degraded = "degraded", "partial_methods_failed"
    else:
        status, degraded = "good", None

    profile = PersistenceProfile(
        symbol=symbol.upper(),
        span=span,
        sample_n=n,
        metrics=metrics,
        quality={
            "status": status,
            "sample_n": n,
            "span": span,
            "align_method": align.ALIGN_METHOD,
            "timezone": align.TIMEZONE,
            "min_n": min_n,
            "lookback_days": days,  # 自然日回看窗口（非交易日数），评审 I2
            "degraded_reason": degraded,
            "failed_methods": errors,
            "hurst_confident_n": M.HURST_CONFIDENT_N,
            "hurst_max_chunk": M.HURST_MAX_CHUNK,
            "notes": [
                "trend_t_no_hac: 趋势斜率 t 未做 Newey-West 修正，仅作相对比较",
                "hurst_low_confidence: Hurst 在 n<2000 时口径敏感，不展示 regime 标签",
                "ic_phase: IC 非重叠口径为 h 个相位的均值，极差见 ric_nonoverlap_min/max",
                "a8_independent_gate: A8 使用自身 4→2 桶门禁，不改变 A1–A7 质量状态",
            ],
        },
    )
    return profile.to_dict()
