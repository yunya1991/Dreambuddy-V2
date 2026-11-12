"""金融环境四层联合验证（SPEC-EMERGENCE-FINANCIAL-ENV §7.2，P2-B）。

回答四个问题，层层收紧：
  L-A 单层    每层单独有没有信息？            → 各层 Spearman IC / ICIR / t
  L-B 交叉    E×S、E×M、S×P 是否优于单层？    → 交互项 IC + 分组 IC
  L-C 三方    E+S+M 叠加的增量是否 > 任意两路？→ 正交化增量 IC + block bootstrap CI
  L-D 状态    是否只在特定 regime 下有效？     → 按 label / VIX 档 / F&G 极值分桶 IC

纪律（硬约束）：
  1. verdict 只能来自 `registry/factor_gate.py` 的 `assert_gate()` / `write_verdict()`，
     本模块不得手写 verdict 字面量（`tests/test_no_direct_verdict_write.py` 静态扫描）。
  2. 因子未在 `configs/factor_preregistration.json` 预注册 → 不记 trial、不写 verdict，
     由 `assert_gate()` 如实返回 `insufficient_data / not_preregistered`（E-1 防 HARKing）。
  3. 样本量不足 `MIN_N_OBS` 或前视审计有违规 → 只走 `assert_gate()` 只读判定，
     不写 `trials.jsonl` / `factor_verdicts.jsonl`（避免污染试验记账）。
  4. L-D 分桶是**描述性统计**，不是独立假设，不记 trial。
  5. 无价格数据 → 整体 `data_status="insufficient_data"`，不伪造任何结论。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "registry") not in sys.path:  # CLI 直跑时 conftest 不生效
    sys.path.insert(0, str(_ROOT / "registry"))

import financial_env_align as fea  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from factor_gate import (  # noqa: E402
    MIN_N_OBS,
    VERDICTS,
    FactorGateError,
    assert_gate,
    record_trial,
    register_factor,
    write_verdict,
)

REPORT_VERSION = "financial-env-validate-v1"
MIN_CROSS_SECTION = 3  # 截面 IC 至少需要 3 个标的，否则该日不计入
MIN_TS_DATES = 30  # 市场级因子时序 IC 至少需要 30 个交易日
DEFAULT_BOOTSTRAP = 200
DEFAULT_SEED = 7

_BASE = Path(__file__).resolve().parents[1]
DEFAULT_OUT = _BASE / "runtime" / "financial_env_report.json"

LAYER_PAIRS = (("E_score", "S_score"), ("E_score", "M_score"), ("S_score", "P_score"))


DEFAULT_KLINES_DIR = _BASE.parent / "11-易经推理系统" / "scripts" / "data" / "klines"
DEFAULT_SYMBOLS = ("BTC", "ETH", "SOL", "AVAX", "LINK")
DEFAULT_SEMANTIC_EVENTS = _BASE.parent / "39-金融语义蒸馏系统" / "semantic_events.jsonl"
_LEADER_FORM_ROOT = _BASE.parent / "21-特征工程中心" / "feature_hub" / "modules"
_NINE_DOMAIN_ROOT = _BASE.parent / "9-基本面分析"
_TREND_CONTEXT_COLUMNS = ["symbol", "date", "trend_20d"]


# ── S 层适配器（39 语义事件流 → align 契约）──


def load_semantic_sentiment(path: str | Path | None = None) -> pd.DataFrame:
    """读 39 `semantic_events.jsonl` → `symbol/date/score/available_at`。

    只取 `sentiment.score` 非空且 `symbol` 非空的行（trader.log 行无 sentiment，跳过）；
    同一标的同一天多条按 `score` 均值聚合，`available_at` 取最大时间戳（不提前可见）。
    文件缺失或字段不全 → 空表（FAIL-OPEN，S 层缺失即 NaN，不用 0 冒充）。
    """
    p = Path(path) if path else DEFAULT_SEMANTIC_EVENTS
    cols = ["symbol", "date", "score", "available_at"]
    if not p.is_file():
        return pd.DataFrame(columns=cols)
    rows: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        senti = obj.get("sentiment")
        if not isinstance(senti, dict) or senti.get("score") is None:
            continue
        symbol = str(obj.get("symbol") or "").strip()
        ts = pd.to_datetime(obj.get("timestamp"), utc=True, errors="coerce")
        if not symbol or pd.isna(ts):
            continue
        try:
            score = float(senti["score"])
        except (TypeError, ValueError):
            continue
        rows.append({"symbol": symbol, "date": ts.date(), "score": score, "available_at": ts})
    if not rows:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(rows)
    return (
        df.groupby(["symbol", "date"], as_index=False)
        .agg(score=("score", "mean"), available_at=("available_at", "max"))
        .loc[:, cols]
    )


# ── 价格源适配（G10 未关闭：此处只作验证级输入，不是生产唯一价格源）──


def _read_kline_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    need = {"timestamp", "open", "high", "low", "close", "volume"}
    if not need.issubset(df.columns):
        raise ValueError(f"{path.name} 缺列：{sorted(need - set(df.columns))}")
    out = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
    out = out.dropna(subset=["timestamp"]).sort_values("timestamp")
    out["date"] = out["timestamp"].dt.date
    return out


def _to_daily(df: pd.DataFrame) -> pd.DataFrame:
    """1H/4H → 日线（同日最后一根 close、最高 high、最低 low、量能求和）。"""
    g = df.groupby("date", sort=True)
    return pd.DataFrame(
        {
            "open": g["open"].first(),
            "high": g["high"].max(),
            "low": g["low"].min(),
            "close": g["close"].last(),
            "volume": g["volume"].sum(),
        }
    ).reset_index()


def _load_unified(symbols: Sequence[str], days: int) -> tuple[dict[str, pd.DataFrame], dict]:
    """从 18 统一价格源（G10）读日线；不可用则返回空（由调用方回退 CSV）。"""
    root18 = _BASE.parent / "18-数据获取中心"
    if str(root18) not in sys.path:
        sys.path.append(str(root18))
    try:
        from data_center.market import price_source  # noqa: PLC0415
    except ImportError:
        logger.warning("FAIL-OPEN: 18域统一价格源不可用，回退 CSV kline")
        return {}, {}
    bars, metas = {}, {}
    for sym in symbols:
        try:
            df, meta = price_source.load_daily(sym, days=days)
        except Exception as exc:  # noqa: BLE001  FAIL-OPEN：单标的失败回退 CSV
            logger.warning("FAIL-OPEN: price_source.load_daily(%s) 失败：%s", sym, exc)
            continue
        if df is None or df.empty:
            continue
        bars[sym] = df.loc[:, ["date", "open", "high", "low", "close", "volume"]].copy()
        metas[sym] = meta
    return bars, metas


def load_klines(
    klines_dir: str | Path = DEFAULT_KLINES_DIR,
    symbols: Sequence[str] = DEFAULT_SYMBOLS,
    days: int = 2200,
    use_unified: bool = True,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], dict]:
    """→ (prices[symbol,date,close], {symbol: 日线 OHLCV}, provenance)。

    价格优先级（SPEC §2.4 U-1 / G10）：18 统一价格源（OKX 主源 + Binance 显式 fallback，
    UTC 日线）→ 11 域 `*_1D.csv` → `*_1H.csv` 聚合日线。回退时必须如实标注 provenance。
    """
    root = Path(klines_dir)
    unified, unified_meta = _load_unified(symbols, days) if use_unified else ({}, {})
    prices, bars, used = [], {}, {}
    for sym in symbols:
        if sym in unified:
            daily = unified[sym].copy()
            meta = unified_meta[sym]
            bars[sym] = daily.reset_index(drop=True)
            used[sym] = {
                "source": meta.get("source", "okx"),
                "from": str(daily["date"].min()),
                "to": str(daily["date"].max()),
                "n_days": int(daily.shape[0]),
                "tier": "unified",
            }
        else:
            if not root.is_dir():
                continue
            daily_path = root / f"{sym}_1D.csv"
            hourly_path = root / f"{sym}_1H.csv"
            if daily_path.is_file():
                daily, src = _read_kline_csv(daily_path), "1D"
            elif hourly_path.is_file():
                daily, src = _to_daily(_read_kline_csv(hourly_path)), "1H->1D"
            else:
                continue
            bars[sym] = daily.reset_index(drop=True)
            used[sym] = {
                "source": src,
                "from": str(daily["date"].min()),
                "to": str(daily["date"].max()),
                "n_days": int(daily.shape[0]),
                "tier": "kline_csv",
            }
        prices.append(bars[sym].assign(symbol=sym)[["symbol", "date", "close"]])
    if not prices:
        raise SystemExit(f"未在 {root} 找到任何 {symbols} 的 klines 文件")
    px = pd.concat(prices, ignore_index=True)
    tiers = {row["tier"] for row in used.values()}
    provenance = {
        "kind": "unified" if tiers == {"unified"} else "mixed" if len(tiers) > 1 else "kline_csv",
        "root": str(root),
        "symbols": used,
        "note": "统一价格源（G10）为 18 data_center.market.price_source；kline_csv 仅作回退",
    }
    return px, bars, provenance


def form_from_bars(bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """用 21 域 `leader_form.compute` 从日线派生 P 层（复用 P1-C 实现，不另写一套）。"""
    if str(_LEADER_FORM_ROOT) not in sys.path:
        sys.path.append(str(_LEADER_FORM_ROOT))
    try:
        from leader_form import compute  # noqa: PLC0415
    except ImportError as exc:
        logger.warning("FAIL-OPEN: 21域 leader_form 不可用，P层形态跳过：%s", exc)
        return pd.DataFrame()
    frames = []
    for sym, bar in bars.items():
        try:
            feats = compute(bar, symbol=sym)
        except Exception as exc:  # noqa: BLE001  单标的失败不阻断其它
            logger.warning("FAIL-OPEN: leader_form.compute(%s) 失败：%s", sym, exc)
            continue
        feats["symbol"] = sym
        feats["date"] = bar["date"].to_numpy()
        frames.append(feats)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def trend_context_from_history(
    module: str = "sentiment", base_dir: Path | None = None
) -> pd.DataFrame:
    """9 域真实历史 → 市场级逐日 `trend_20d`，不足 20 观测不输出。

    每个滚动窗口都调用 9 域权威统计函数，避免在 48 域复制 Spearman 口径。
    9 域或历史文件不可用时返回空表（FAIL-OPEN）。
    """
    if str(_NINE_DOMAIN_ROOT) not in sys.path:
        sys.path.append(str(_NINE_DOMAIN_ROOT))
    try:
        from engines.dimension_history import (  # noqa: PLC0415
            compute_dimension_history,
            load_series,
        )

        series = load_series(module, base_dir=base_dir)
        rows = []
        for end in range(19, len(series)):
            as_of = str(series[end].get("date") or "")[:10]
            window = series[end - 19 : end + 1]
            history = compute_dimension_history(window, module, as_of=as_of)
            trend = history["stats"]["trend_20d"]
            day = history["coverage"]["last_day"]
            if trend is not None and day is not None:
                rows.append(
                    {
                        "symbol": "",
                        "date": pd.to_datetime(day).date(),
                        "trend_20d": float(trend),
                    }
                )
    except Exception as exc:  # noqa: BLE001 形态上下文缺失不得阻断既有四层验证
        logger.warning("FAIL-OPEN: trend_context_from_history(%s) 失败：%s", module, exc)
        return pd.DataFrame(columns=_TREND_CONTEXT_COLUMNS)
    return pd.DataFrame(rows, columns=_TREND_CONTEXT_COLUMNS)


def add_trend_context(
    form: pd.DataFrame | None,
    module: str = "sentiment",
    base_dir: Path | None = None,
) -> pd.DataFrame | None:
    """把市场级趋势作为形态行叠加；`align` 会按日期广播为 `P_trend_20d`。"""
    context = trend_context_from_history(module, base_dir=base_dir)
    if context.empty or (form is not None and "trend_20d" in form.columns):
        return form
    if form is None or form.empty:
        return context
    return pd.concat([form, context], ignore_index=True, sort=False)


def _long(df: pd.DataFrame) -> pd.DataFrame:
    """(symbol, date) MultiIndex → 带列的长表。"""
    out = df.copy()
    out["symbol"] = out.index.get_level_values("symbol")
    out["date"] = out.index.get_level_values("date")
    return out.reset_index(drop=True)


def _ic_by_date(frame: pd.DataFrame, factor: str, ret: str, min_xs: int = MIN_CROSS_SECTION):
    """逐日截面 Spearman IC；横截面不足 `min_xs` 或因子无变异的日期丢弃。"""
    out: dict[Any, float] = {}
    if factor not in frame.columns or ret not in frame.columns:
        return pd.Series(dtype=float)
    for d, g in frame.dropna(subset=[factor, ret]).groupby("date"):
        if len(g) < min_xs or g[factor].nunique() < 2:
            continue
        ic = g[factor].corr(g[ret], method="spearman")
        if pd.notna(ic):
            out[d] = float(ic)
    return pd.Series(out, dtype=float)


def ic_stats(frame: pd.DataFrame, factor: str, ret: str, min_xs: int = MIN_CROSS_SECTION) -> dict:
    """→ {ic, icir, t_stat, n_dates, n_obs, ic_series}。"""
    ics = _ic_by_date(frame, factor, ret, min_xs)
    n_obs = int(frame[[factor, ret]].dropna().shape[0]) if factor in frame.columns else 0
    n = int(ics.shape[0])
    if n == 0:
        return {
            "ic": None,
            "icir": None,
            "t_stat": 0.0,
            "n_dates": 0,
            "n_obs": n_obs,
            "ic_series": ics,
        }
    mean = float(ics.mean())
    sd = float(ics.std(ddof=1)) if n > 1 else 0.0
    icir = mean / sd if sd > 0 else 0.0
    return {
        "ic": mean,
        "icir": icir,
        "t_stat": icir * float(np.sqrt(n)),
        "n_dates": n,
        "n_obs": n_obs,
        "ic_series": ics,
    }


def ts_stats(frame: pd.DataFrame, factor: str, ret: str) -> dict | None:
    """市场级因子的时序 IC（截面只有一个取值时，截面 IC 无定义）。

    做法：按日取因子与收益的截面均值 → 对日期序列求 Spearman，
    `t = IC·√((n-2)/(1-IC²))`。M 层（VIX 档位）天然市场级，只能这样评估。
    """
    if factor not in frame.columns or ret not in frame.columns:
        return None
    g = frame.dropna(subset=[factor, ret]).groupby("date")[[factor, ret]].mean()
    n = int(g.shape[0])
    if n < MIN_TS_DATES or g[factor].nunique() < 2:
        return None
    ic = g[factor].corr(g[ret], method="spearman")
    if pd.isna(ic):
        return None
    ic = float(ic)
    t_stat = ic * float(np.sqrt((n - 2) / max(1.0 - ic * ic, 1e-12)))
    return {
        "ic": ic,
        "icir": None,
        "t_stat": t_stat,
        "n_dates": n,
        "n_obs": int(frame[[factor, ret]].dropna().shape[0]),
        "ic_series": pd.Series([ic], dtype=float),
        "mode": "time_series",
    }


def _public(stats: dict) -> dict:
    return {k: v for k, v in stats.items() if k != "ic_series"}


def _xs_z(frame: pd.DataFrame, cols: Sequence[str]) -> pd.DataFrame:
    """按日截面标准化（缺失填 0，避免整行被丢弃）。"""
    out = pd.DataFrame(index=frame.index)
    grouped = frame.groupby("date")
    for c in cols:
        mean = grouped[c].transform("mean")
        std = grouped[c].transform("std").replace(0, np.nan)
        out[c] = ((frame[c] - mean) / std).fillna(0.0)
    return out


def layer_scores_from(frame: pd.DataFrame) -> pd.DataFrame:
    """四层 → 标量分数（方向统一为「越大越看多」）。

    E_score = E_direction（无事件为 0）
    S_score = 语义情绪分值
    M_score = -(VIX 档位)/3（VIX 越高越 risk-off）
    P_score = 形态数值列的截面 z 均值
    P_trend_20d = 9 域市场级趋势上下文（独立时序评估，不混入截面 P_score）
    """
    out = pd.DataFrame(index=frame.index)
    if "E_direction" in frame.columns:
        out["E_score"] = pd.to_numeric(frame["E_direction"], errors="coerce").fillna(0.0)
    if "S_score" in frame.columns:
        out["S_score"] = pd.to_numeric(frame["S_score"], errors="coerce")
    if "M_vix_bucket_code" in frame.columns:
        out["M_score"] = -pd.to_numeric(frame["M_vix_bucket_code"], errors="coerce") / 3.0
    p_cols = [
        c
        for c in frame.columns
        if c.startswith("P_")
        and c != "P_trend_20d"
        and pd.api.types.is_numeric_dtype(frame[c])
        and frame[c].notna().any()
    ]
    if p_cols:
        z = _xs_z(frame, p_cols)
        out["P_score"] = z.mean(axis=1).where(frame[p_cols].notna().any(axis=1))
    if "P_trend_20d" in frame.columns:
        out["P_trend_20d"] = pd.to_numeric(frame["P_trend_20d"], errors="coerce")
    return out.dropna(axis=1, how="all")


def _orthogonalize(frame: pd.DataFrame, target: str, controls: Sequence[str]) -> pd.Series:
    """截面回归取残差（日频、按 date 分组）；截面不足时退化为池化 OLS。"""
    y_all = pd.to_numeric(frame[target], errors="coerce")
    controls = [c for c in controls if c in frame.columns]
    if not controls:
        return y_all
    resid = y_all.astype(float).copy()
    for _, g in frame.groupby("date"):
        y = pd.to_numeric(g[target], errors="coerce")
        x = g[controls].apply(pd.to_numeric, errors="coerce")
        mask = y.notna() & x.notna().all(axis=1)
        if int(mask.sum()) < len(controls) + 2:
            continue
        design = np.column_stack([np.ones(int(mask.sum())), x[mask].to_numpy(dtype=float)])
        beta, *_ = np.linalg.lstsq(design, y[mask].to_numpy(dtype=float), rcond=None)
        resid.loc[g.index[mask]] = y[mask].to_numpy(dtype=float) - design @ beta
    if resid.isna().all():
        mask = y_all.notna() & frame[controls].notna().all(axis=1)
        if int(mask.sum()) > len(controls) + 1:
            design = np.column_stack(
                [np.ones(int(mask.sum())), frame.loc[mask, controls].to_numpy(dtype=float)]
            )
            beta, *_ = np.linalg.lstsq(design, y_all[mask].to_numpy(dtype=float), rcond=None)
            resid.loc[mask] = y_all[mask].to_numpy(dtype=float) - design @ beta
    return resid


def _bootstrap_ci(ics: pd.Series, rounds: int, seed: int):
    """对逐日 IC 序列做 block bootstrap（按日重采样）→ (mean, lo, hi)。"""
    vals = ics.dropna().to_numpy(dtype=float)
    if vals.size == 0 or rounds <= 0:
        return {"mean": None, "lo": None, "hi": None, "rounds": 0}
    rng = np.random.default_rng(seed)
    means = [float(rng.choice(vals, size=vals.size, replace=True).mean()) for _ in range(rounds)]
    return {
        "mean": float(np.mean(means)),
        "lo": float(np.percentile(means, 2.5)),
        "hi": float(np.percentile(means, 97.5)),
        "rounds": int(rounds),
    }


# ── 门禁接线 ─────────────────────────────────────────────────


def _gate(
    factor_id: str,
    horizon: int,
    stats: dict,
    *,
    leakage_ok: bool,
    prereg_path: Path | None,
    dsr: float | None,
    pbo: float | None,
) -> dict:
    """样本量/泄漏不满足时只读判定；满足且已预注册才记 trial 并写 verdict。"""
    kwargs = {
        "factor_id": factor_id,
        "horizon": horizon,
        "ic": float(stats.get("ic") or 0.0),
        "t_stat": float(stats.get("t_stat") or 0.0),
        "n_obs": int(stats.get("n_obs") or 0),
        "dsr": dsr,
        "pbo": pbo,
        "leakage_ok": leakage_ok,
    }
    if stats.get("ic") is None or int(stats.get("n_obs") or 0) < MIN_N_OBS or not leakage_ok:
        rec = assert_gate(**kwargs)
        if stats.get("ic") is None:
            rec["gate_note"] = "ic=None（该层无可用变异或截面/时序样本不足）"
        return rec
    try:
        register_factor(factor_id, prereg_path=prereg_path)
    except FactorGateError as exc:
        rec = assert_gate(**kwargs)
        rec["gate_note"] = str(exc)
        return rec
    record_trial(
        factor_id,
        horizon,
        ic=kwargs["ic"],
        t_stat=kwargs["t_stat"],
        n_obs=kwargs["n_obs"],
        params={"module": "financial_env_validate"},
        script=__file__,
    )
    return write_verdict(**kwargs, script=__file__)


# ── 四层验证 ─────────────────────────────────────────────────


def _layer_a(frame: pd.DataFrame, ret: str, min_xs: int) -> dict:
    scores = layer_scores_from(frame)
    factors = {}
    for name in scores.columns:
        work = frame.assign(**{name: scores[name].to_numpy()})
        stats = ic_stats(work, name, ret, min_xs)
        stats["mode"] = "cross_section"
        if stats["ic"] is None:
            ts = ts_stats(work, name, ret)
            if ts is not None:
                stats = ts
        factors[name] = stats
    combo_cols = [c for c in ("E_score", "S_score", "M_score", "P_score") if c in scores.columns]
    if len(combo_cols) >= 2:
        combo = scores[combo_cols].mean(axis=1, skipna=True)
        work = frame.assign(ALL_layers=combo.to_numpy())
        stats = ic_stats(work, "ALL_layers", ret, min_xs)
        stats["mode"] = "cross_section"
        if stats["ic"] is None:
            ts = ts_stats(work, "ALL_layers", ret)
            if ts is not None:
                stats = ts
        factors["ALL_layers"] = stats
    return factors


def _layer_b(frame: pd.DataFrame, scores: pd.DataFrame, ret: str, min_xs: int) -> dict:
    pairs = {}
    for a, b in LAYER_PAIRS:
        if a not in scores.columns or b not in scores.columns:
            continue
        interact = (scores[a] * scores[b]).rename("interaction")
        work = frame.assign(interaction=interact.to_numpy())
        stats = ic_stats(work, "interaction", ret, min_xs)
        grouped = {}
        for cond_name, cond in (
            ("event", work.get("E_has_event", pd.Series(0.0, index=work.index)).astype(float) > 0),
            (
                "no_event",
                work.get("E_has_event", pd.Series(0.0, index=work.index)).astype(float) <= 0,
            ),
        ):
            grouped[cond_name] = _public(ic_stats(work[cond], a, ret, min_xs))
        pairs[f"{a}x{b}"] = {"interaction": _public(stats), "grouped": grouped}
    return pairs


def _layer_c(
    frame: pd.DataFrame, scores: pd.DataFrame, ret: str, min_xs: int, seed: int, rounds: int
) -> dict:
    """逐步加入的增量 IC：先 E，再加 S，再加 M，每步对已加入层正交化。"""
    order = [c for c in ("E_score", "S_score", "M_score", "P_score") if c in scores.columns]
    steps = []
    used: list[str] = []
    for name in order:
        if used:
            resid = _orthogonalize(frame.assign(_step=scores[name].to_numpy()), "_step", used)
        else:
            resid = scores[name]
        work = frame.assign(incremental=resid.to_numpy())
        stats = ic_stats(work, "incremental", ret, min_xs)
        steps.append(
            {
                "added": name,
                "controls": list(used),
                "stats": _public(stats),
                "bootstrap": _bootstrap_ci(stats["ic_series"], rounds, seed),
            }
        )
        used.append(name)
    return {"steps": steps, "bootstrap_rounds": rounds, "seed": seed}


def _layer_d(frame: pd.DataFrame, scores: pd.DataFrame, ret: str, min_xs: int) -> dict:
    """按 regime / VIX 档 / F&G 极值分桶的 IC（描述性，不进门禁）。"""
    buckets: dict[str, dict] = {}
    if "M_label" in frame.columns:
        for label, g in frame.groupby("M_label"):
            work = g.assign(**{c: scores.loc[g.index, c].to_numpy() for c in scores.columns})
            buckets[f"label={label}"] = {
                c: _public(ic_stats(work, c, ret, min_xs)) for c in scores.columns
            }
    if "M_vix_bucket_code" in frame.columns:
        for code, g in frame.groupby("M_vix_bucket_code"):
            work = g.assign(**{c: scores.loc[g.index, c].to_numpy() for c in scores.columns})
            buckets[f"vix_bucket={code:g}"] = {
                c: _public(ic_stats(work, c, ret, min_xs)) for c in scores.columns
            }
    if "M_fng" in frame.columns and pd.to_numeric(frame["M_fng"], errors="coerce").notna().any():
        fng = pd.to_numeric(frame["M_fng"], errors="coerce")
        for name, mask in (
            ("fng<25", fng < 25),
            ("fng>75", fng > 75),
            ("fng_mid", fng.between(25, 75)),
        ):
            work = frame[mask.fillna(False)]
            if work.empty:
                continue
            scores_sub = scores.loc[work.index]
            work = work.assign(**{c: scores_sub[c].to_numpy() for c in scores.columns})
            buckets[name] = {c: _public(ic_stats(work, c, ret, min_xs)) for c in scores.columns}
    return buckets


# ── 主入口 ───────────────────────────────────────────────────


def validate(
    aligned: pd.DataFrame,
    horizon: int = 5,
    *,
    min_cross_section: int = MIN_CROSS_SECTION,
    bootstrap: int = DEFAULT_BOOTSTRAP,
    seed: int = DEFAULT_SEED,
    prereg_path: Path | None = None,
    dsr: float | None = None,
    pbo: float | None = None,
    price_source: dict | None = None,
) -> dict:
    """四层联合验证。`aligned` 必须来自 `financial_env_align.align()`。"""
    violations = list(aligned.attrs.get("lookahead_violations") or [])
    ret = f"forward_ret_{horizon}d"
    frame = _long(aligned) if not aligned.empty else pd.DataFrame()
    has_prices = ret in frame.columns and frame[ret].notna().any() if not frame.empty else False

    report: dict[str, Any] = {
        "version": REPORT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "horizon": horizon,
        "n_obs": int(frame.shape[0]),
        "n_dates": int(frame["date"].nunique()) if not frame.empty else 0,
        "n_symbols": int(frame["symbol"].nunique()) if not frame.empty else 0,
        "lookahead_violations": len(violations),
        "min_n_obs": MIN_N_OBS,
        "price_source": price_source or {"kind": "caller_supplied"},
    }

    if not has_prices:
        report["data_status"] = "insufficient_data"
        report["reason"] = "no_forward_returns"
        report["L_A"] = {"factors": {}}
        report["L_B"] = {"pairs": {}}
        report["L_C"] = {"steps": []}
        report["L_D"] = {"buckets": {}}
        rec = assert_gate(
            "ALL_layers", horizon, 0.0, 0.0, int(frame.shape[0]), leakage_ok=not violations
        )
        report["gate"] = rec
        report["verdict"] = rec["verdict"]
        assert report["verdict"] in VERDICTS
        return report

    report["data_status"] = (
        "ok" if int(frame.shape[0]) >= MIN_N_OBS and not violations else "insufficient_data"
    )
    if violations:
        report["reason"] = "lookahead_violation"
    elif report["data_status"] != "ok":
        report["reason"] = f"n_obs={int(frame.shape[0])}<{MIN_N_OBS}"

    scores = layer_scores_from(frame)
    gate_kwargs = {
        "leakage_ok": not violations,
        "prereg_path": prereg_path,
        "dsr": dsr,
        "pbo": pbo,
    }

    layer_a = _layer_a(frame, ret, min_cross_section)
    factors_out = {}
    for name, stats in layer_a.items():
        rec = _gate(name, horizon, stats, **gate_kwargs)
        payload = _public(stats)
        payload["verdict"] = rec["verdict"]
        payload["reasons"] = rec["reasons"]
        factors_out[name] = payload
    report["L_A"] = {"factors": factors_out}

    pairs = _layer_b(frame, scores, ret, min_cross_section)
    for key, payload in pairs.items():
        rec = _gate(key, horizon, payload["interaction"], **gate_kwargs)
        payload["verdict"] = rec["verdict"]
        payload["reasons"] = rec["reasons"]
    report["L_B"] = {"pairs": pairs}

    report["L_C"] = _layer_c(frame, scores, ret, min_cross_section, seed, bootstrap)
    report["L_D"] = {"buckets": _layer_d(frame, scores, ret, min_cross_section)}

    lead = factors_out.get("ALL_layers") or next(iter(factors_out.values()), None)
    gate_summary = {
        "reasons": lead["reasons"] if lead else ["no_layer"],
        "factor_id": "ALL_layers",
        "n_obs": int(frame.shape[0]),
        "n_dates": report["n_dates"],
    }
    gate_summary["verdict"] = lead["verdict"] if lead else "insufficient_data"
    report["gate"] = gate_summary
    report["verdict"] = gate_summary["verdict"]
    assert report["verdict"] in VERDICTS
    return report


# ── CLI ──────────────────────────────────────────────────────


def _load_table(path: str | None) -> pd.DataFrame | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        raise SystemExit(f"文件不存在：{p}")
    if p.suffix.lower() in (".parquet", ".pq"):
        return pd.read_parquet(p)
    return pd.read_csv(p)


def _load_jsonl(path: str | None) -> list[dict]:
    if not path:
        return []
    p = Path(path)
    if not p.is_file():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _load_regime(dir_path: str | Path) -> list[dict]:
    d = Path(dir_path)
    if not d.is_dir():
        return []
    rows = []
    for p in sorted(d.glob("*.json")):
        try:
            rows.append(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return rows


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="金融环境四层联合验证（P2-B）")
    ap.add_argument("--prices", help="OHLCV csv/parquet，需含 symbol/date/close")
    ap.add_argument(
        "--klines-dir",
        nargs="?",
        const=str(DEFAULT_KLINES_DIR),
        help="CSV 回退目录；价格优先取 18 统一价格源（G10）",
    )
    ap.add_argument("--symbols", help="逗号分隔标的（默认 BTC,ETH,SOL,AVAX,LINK）")
    ap.add_argument("--days", type=int, default=2200, help="统一价格源回看天数")
    ap.add_argument(
        "--no-unified-prices", action="store_true", help="禁用 18 统一价格源，仅用 klines CSV"
    )
    ap.add_argument("--no-form-from-klines", action="store_true", help="不从 klines 派生 P 层")
    ap.add_argument("--events", help="E 层 events.jsonl")
    ap.add_argument("--sentiment", help="S 层 JSONL（symbol/date/score/available_at）")
    ap.add_argument(
        "--semantic-events",
        nargs="?",
        const=str(DEFAULT_SEMANTIC_EVENTS),
        default=str(DEFAULT_SEMANTIC_EVENTS),
        help="未显式给 --sentiment 时，自动从 39 语义事件流派生 S 层（默认 semantic_events.jsonl）",
    )
    ap.add_argument("--form", help="P 层 csv/parquet（symbol/date/数值列）")
    ap.add_argument(
        "--trend-module",
        default="sentiment",
        help="提供 trend_20d 形态上下文的 9 域模块（默认 sentiment）",
    )
    ap.add_argument("--no-trend-context", action="store_true", help="禁用 9 域 trend_20d 上下文")
    ap.add_argument("--regime-dir", default=str(_BASE / "runtime" / "regime"))
    ap.add_argument("--asset-class", default="crypto")
    ap.add_argument("--horizon", type=int, default=5)
    ap.add_argument("--bootstrap", type=int, default=DEFAULT_BOOTSTRAP)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--dsr", type=float, default=None)
    ap.add_argument("--pbo", type=float, default=None)
    ap.add_argument("--prereg", help="预注册文件路径（缺省用 configs/factor_preregistration.json）")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(list(argv) if argv is not None else None)

    prices = _load_table(args.prices)
    form = _load_table(args.form)
    source = {"kind": "caller_supplied_csv" if prices is not None else "none"}
    if prices is None and args.klines_dir:
        raw_symbols = args.symbols or ",".join(DEFAULT_SYMBOLS)
        symbols = tuple(s.strip() for s in raw_symbols.split(",") if s.strip())
        prices, bars, source = load_klines(
            args.klines_dir,
            symbols,
            days=args.days,
            use_unified=not args.no_unified_prices,
        )
        if form is None and not args.no_form_from_klines:
            form = form_from_bars(bars)

    if not args.no_trend_context:
        form = add_trend_context(form, module=args.trend_module)

    sentiment = _load_jsonl(args.sentiment)
    if not sentiment:  # 未显式传 --sentiment → 自动接 39 语义事件流（S 层唯一来源）
        sentiment = load_semantic_sentiment(args.semantic_events)
        source["sentiment"] = "39_semantic_events" if not sentiment.empty else "none"
    else:
        source["sentiment"] = "cli"

    aligned = fea.align(
        _load_jsonl(args.events),
        sentiment,
        _load_regime(args.regime_dir),
        form,
        horizon=args.horizon,
        prices=prices,
        asset_class=args.asset_class,
    )
    report = validate(
        aligned,
        horizon=args.horizon,
        bootstrap=args.bootstrap,
        seed=args.seed,
        dsr=args.dsr,
        pbo=args.pbo,
        prereg_path=Path(args.prereg) if args.prereg else None,
        price_source=source,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {"out": str(out), "data_status": report["data_status"]}
    summary["verdict"] = report["verdict"]
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
