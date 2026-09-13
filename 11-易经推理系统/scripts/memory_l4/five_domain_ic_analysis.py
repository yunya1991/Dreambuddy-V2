"""战略层五域因子 IC 检验（Phase 1）

计算各维度/子指标对未来 7 日收益的 RankIC 和 IC_IR。
数据不足时输出描述性统计，样本≥250 后结果具统计意义。

用法：
    python five_domain_ic_analysis.py
输出：
    runtime/five_domain_ic_report.csv
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent.parent
_DB_PATH = _REPO / "18-数据获取中心" / "data_center.db"
_RUNTIME = _HERE / "runtime"
_REPORT_CSV = _RUNTIME / "five_domain_ic_report.csv"

if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from five_domain_sqlite_reader import (  # noqa: E402
    read_three_classes_from_sqlite,
    _compute_merrill,
    _compute_liquidity_score,
)
from five_domain_feature_computer import FiveDomainFeatureComputer  # noqa: E402


# ============================================================
# 子指标原始值映射（coin_data 字段名 → 子指标名）
# ============================================================
SUBINDICATOR_MAP = {
    "dao": {
        "fedfunds_rate": "央行政策方向",
        "stablecoin_mcap_bln": "机构资金净流入",
        "policy_sentiment_score": "政策景气度",
        "stablecoin_change_rate": "变化率",
        "cycle4y_t_rel": "大周期位置",
    },
    "tian": {
        "merrill_phase": "美林时钟",
        "atr_percentile_proxy": "波动率周期",
        "liquidity_score": "流动性周期",
        "yield_10y_2y": "10Y-2Y利差",
    },
    "di": {
        "regime": "regime代理",
        "spring_force_score": "弹簧力场MA",
    },
    "jiang": {},  # system_state 因子，不做 IC
    "fa": {},     # system_state 因子，不做 IC
}

# 资产类 → 收益标的
ASSET_RETURN_MAP = {
    "crypto_usdt": "BTC-USD",
    "us_stock": "SPY",
    "precious_metal": "GLD",
}


def _safe_json(text: Any) -> dict:
    if text is None:
        return {}
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("utf-8", errors="replace")
    if isinstance(text, str):
        try:
            return json.loads(text)
        except Exception:
            return {}
    if isinstance(text, dict):
        return text
    return {}


def _get_daily_snapshots(db_path: Path) -> List[Tuple[str, Dict[str, Dict[str, Any]]]]:
    """按日期获取三类资产的 coin_data 快照。

    对每个日期，从 records 表读取该日及之前的最新记录构造 coin_data。
    返回 [(date_str, {cls: coin_data}), ...] 按日期升序。
    """
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        # 获取所有有记录的日期
        rows = conn.execute(
            "SELECT DISTINCT date(timestamp) as d FROM records "
            "WHERE source IN ('fred','yfinance','panewslab','theblockbeats_dataview',"
            "'fear_greed','gold_supply_demand','stablecoin_transparency','defillama',"
            "'etherscan','ccxt') "
            "ORDER BY d"
        ).fetchall()
        dates = [r["d"] for r in rows]
        conn.close()
    except Exception:
        return []

    snapshots = []
    for d in dates:
        try:
            coin_data = _build_snapshot_for_date(db_path, d)
            if coin_data:
                snapshots.append((d, coin_data))
        except Exception:
            continue
    return snapshots


def _build_snapshot_for_date(db_path: Path, target_date: str) -> Dict[str, Dict[str, Any]]:
    """构造指定日期的三类资产 coin_data 快照。

    从 records 表读取 target_date 及之前的最新记录，复用 read_macro_from_sqlite 的字段映射。
    """
    macro = _read_macro_for_date(db_path, target_date)
    if not macro:
        return {}

    shared_fields = (
        "vix_close", "fedfunds_rate", "m2_yoy_pct", "fed_balance_sheet_trillion",
        "us_cpi_yoy_pct", "us_indpro_yoy_pct", "policy_sentiment_score",
        "liquidity_score", "merrill_phase", "atr_percentile_proxy",
        "stablecoin_change_rate", "stablecoin_mcap_bln", "yield_10y_2y",
        "fear_greed_norm", "blockbeats_sentiment_norm",
        "blockbeats_signal_dao_avg", "blockbeats_signal_tian_avg",
        "blockbeats_signal_di_avg", "blockbeats_signal_jiang_avg",
        "blockbeats_inflow_top10_total_usd", "gold_supply_demand_balance_t",
    )

    def _build(template_cls: str) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        for key in shared_fields:
            d[key] = macro.get(key)
        # odaily_* 字段
        for k, v in macro.items():
            if k.startswith("odaily_"):
                d[k] = v
        if template_cls == "crypto_usdt":
            for k, v in macro.items():
                if k.startswith("pn_"):
                    d[k] = v
            d["cycle4y_t_rel"] = macro.get("cycle4y_t_rel")
        elif template_cls in ("us_stock", "precious_metal"):
            for k, v in macro.items():
                if k.startswith("pn_us_") or k.startswith("pn_cycle_"):
                    d[k] = v
        return d

    return {
        "crypto_usdt": _build("crypto_usdt"),
        "us_stock": _build("us_stock"),
        "precious_metal": _build("precious_metal"),
    }


def _read_macro_for_date(db_path: Path, target_date: str) -> Dict[str, Any]:
    """读取指定日期及之前的最新宏观记录，构造 macro dict。

    复用 five_domain_sqlite_reader.read_macro_from_sqlite 的字段映射逻辑，
    但增加 timestamp <= target_date 过滤。
    """
    result: Dict[str, Any] = {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT source, sub_category, metrics, raw, timestamp, id "
            "FROM records WHERE source IN "
            "('fred','yfinance','ccxt','defillama','etherscan','tavily',"
            "'theblockbeats_dataview','panewslab','stablecoin_transparency',"
            "'odaily_newsflash','fear_greed','gold_supply_demand') "
            "AND date(timestamp) <= ? "
            "ORDER BY id DESC",
            (target_date,),
        ).fetchall()
        conn.close()
    except Exception:
        return result

    # 按 (source, sub_category) 去重保留最新
    latest: Dict[tuple, Any] = {}
    for r in rows:
        key = (r["source"], r["sub_category"])
        if key not in latest:
            latest[key] = r
    if not latest:
        return result

    def _metric(src: str, sub: str) -> dict:
        rec = latest.get((src, sub))
        return _safe_json(rec["metrics"]) if rec else {}

    # FRED（回补数据用 sub_category=CPIAUCSL，带 yoy_pct；兼容 history 路由）
    result["fedfunds_rate"] = _metric("fred", "FEDFUNDS").get("value")
    cpi = _metric("fred", "CPIAUCSL")
    result["us_cpi_yoy_pct"] = cpi.get("yoy_pct") or _metric("fred", "CPIAUCSL_history").get("yoy_pct")
    indpro = _metric("fred", "INDPRO")
    result["us_indpro_yoy_pct"] = indpro.get("yoy_pct") or _metric("fred", "INDPRO_history").get("yoy_pct")
    m2 = _metric("fred", "M2SL")
    result["m2_yoy_pct"] = m2.get("yoy_pct") or _metric("fred", "M2SL_history").get("yoy_pct")
    walcl = _metric("fred", "WALCL")
    walcl_val = walcl.get("value")
    if isinstance(walcl_val, (int, float)):
        result["fed_balance_sheet_trillion"] = round(float(walcl_val) / 1e6, 4)
    t10y2 = _metric("fred", "T10Y2YM")
    t10y2_val = t10y2.get("value")
    if isinstance(t10y2_val, (int, float)):
        result["yield_10y_2y"] = float(t10y2_val)

    # VIX
    vix = _metric("yfinance", "^VIX")
    vix_val = vix.get("value") or vix.get("close")
    if isinstance(vix_val, (int, float)):
        result["vix_close"] = float(vix_val)
        result["atr_percentile_proxy"] = float(np.clip((float(vix_val) - 10.0) / 40.0, 0.0, 1.0))

    # 稳定币：优先用 tether_current/usdc_current，否则从 stablecoin_hist 的 timeseries 按日期取
    usdt_m = _metric("stablecoin_transparency", "tether_current")
    usdc_m = _metric("stablecoin_transparency", "usdc_current")
    usdt_bln = usdt_m.get("usdt_circulating_usd_bln")
    usdc_bln = usdc_m.get("usdc_circulating_usd_bln")
    stablecoin_total = None
    try:
        vals = [float(v) for v in (usdt_bln, usdc_bln) if isinstance(v, (int, float))]
        if vals:
            stablecoin_total = round(sum(vals), 4)
    except Exception:
        pass

    # 若 current 无值，从 stablecoin_hist_{usdt,usdc} 的 timeseries 按 target_date 取
    if stablecoin_total is None:
        try:
            conn2 = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn2.row_factory = sqlite3.Row
            hist_bln = 0.0
            for sym in ("usdt", "usdc"):
                hrow = conn2.execute(
                    "SELECT timeseries FROM records WHERE source='stablecoin_transparency' "
                    "AND sub_category=? ORDER BY id DESC LIMIT 1",
                    (f"stablecoin_hist_{sym}",),
                ).fetchone()
                if hrow:
                    ts = _safe_json(hrow["timeseries"])
                    # 找 target_date 或之前最近的点
                    for pt in ts:
                        if pt.get("date") <= target_date:
                            v = pt.get("circulating_usd_bln")
                            if isinstance(v, (int, float)):
                                hist_bln += float(v)
                                break
            if hist_bln > 0:
                stablecoin_total = round(hist_bln, 4)
            conn2.close()
        except Exception:
            pass

    if stablecoin_total is not None:
        result["stablecoin_mcap_bln"] = stablecoin_total

    # 变化率：从 stablecoin_hist timeseries 计算
    if result.get("stablecoin_change_rate") is None and stablecoin_total is not None:
        try:
            conn2 = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn2.row_factory = sqlite3.Row
            vals_by_date = {}
            for sym in ("usdt", "usdc"):
                hrow = conn2.execute(
                    "SELECT timeseries FROM records WHERE source='stablecoin_transparency' "
                    "AND sub_category=? ORDER BY id DESC LIMIT 1",
                    (f"stablecoin_hist_{sym}",),
                ).fetchone()
                if hrow:
                    ts = _safe_json(hrow["timeseries"])
                    for pt in ts:
                        d = pt.get("date")
                        v = pt.get("circulating_usd_bln")
                        if d and isinstance(v, (int, float)):
                            vals_by_date[d] = vals_by_date.get(d, 0.0) + float(v)
            conn2.close()
            if vals_by_date:
                dates_sorted = sorted(vals_by_date.keys())
                cur = vals_by_date.get(target_date)
                if cur is None:
                    # 找最近的日期
                    for d in reversed(dates_sorted):
                        if d <= target_date:
                            cur = vals_by_date[d]
                            break
                if cur:
                    # 找 7 天前的值
                    from datetime import datetime, timedelta
                    td = datetime.strptime(target_date, "%Y-%m-%d")
                    week_ago = (td - timedelta(days=7)).strftime("%Y-%m-%d")
                    prev = vals_by_date.get(week_ago)
                    if prev is None:
                        for d in reversed(dates_sorted):
                            if d <= week_ago:
                                prev = vals_by_date[d]
                                break
                    if prev and prev > 0:
                        result["stablecoin_change_rate"] = round((cur - prev) / prev * 100, 4)
        except Exception:
            pass

    # 美林时钟
    cpi_yoy = result.get("us_cpi_yoy_pct")
    indpro_yoy = result.get("us_indpro_yoy_pct")
    if isinstance(cpi_yoy, (int, float)) and isinstance(indpro_yoy, (int, float)):
        result["merrill_phase"] = _compute_merrill(cpi_yoy, indpro_yoy)

    # 流动性评分
    if any(result.get(k) is not None for k in ("fedfunds_rate", "m2_yoy_pct", "fed_balance_sheet_trillion")):
        result["liquidity_score"] = _compute_liquidity_score(
            result.get("fedfunds_rate"), result.get("m2_yoy_pct"), result.get("fed_balance_sheet_trillion"))

    # BlockBeats
    bb_pulse = _metric("theblockbeats_dataview", "bottom_pulse_index")
    pulse_val = bb_pulse.get("score")
    if isinstance(pulse_val, (int, float)):
        result["blockbeats_sentiment_norm"] = round(float(pulse_val) / 100.0, 4)
        if result.get("policy_sentiment_score") is None:
            result["policy_sentiment_score"] = result["blockbeats_sentiment_norm"]

    signal_map: Dict[str, list] = {}
    for sub in ("bottom_signal_tian", "bottom_signal_jiang", "bottom_signal_di", "bottom_signal_dao"):
        m = _metric("theblockbeats_dataview", sub)
        dim = m.get("five_dimension")
        sc = m.get("score")
        if isinstance(dim, str) and isinstance(sc, (int, float)):
            signal_map.setdefault(dim, []).append(float(sc))
    for dim, vals in signal_map.items():
        if vals:
            result[f"blockbeats_signal_{dim}_avg"] = round(sum(vals) / len(vals), 4)

    # Top10 净流入
    try:
        conn2 = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn2.row_factory = sqlite3.Row
        top = conn2.execute(
            "SELECT id FROM records WHERE source='theblockbeats_dataview' "
            "AND sub_category='top10_inflow_di' AND date(timestamp) <= ? "
            "ORDER BY id DESC LIMIT 1", (target_date,),
        ).fetchone()
        if top:
            inflow_rows = conn2.execute(
                "SELECT metrics FROM records WHERE source='theblockbeats_dataview' "
                "AND sub_category='top10_inflow_di' AND id >= ? AND id <= ? ORDER BY id DESC",
                (max(0, top["id"] - 50), top["id"]),
            ).fetchall()
            seen = set()
            total_usd = 0.0
            for r in inflow_rows:
                m = _safe_json(r["metrics"])
                sym = m.get("symbol")
                usd = m.get("inflow_usd")
                if not sym or sym in seen:
                    continue
                seen.add(sym)
                if isinstance(usd, (int, float)):
                    total_usd += float(usd)
            result["blockbeats_inflow_top10_total_usd"] = round(total_usd, 2)
        conn2.close()
    except Exception:
        pass

    # fear_greed
    fg_m = _metric("fear_greed", "crypto_fear_greed")
    fg_val = fg_m.get("value")
    if isinstance(fg_val, (int, float)):
        result["fear_greed_norm"] = round(float(fg_val) / 100.0, 4)

    # gold_supply_demand
    for (src, sub), rec in latest.items():
        if src == "gold_supply_demand":
            gsd = _safe_json(rec["metrics"])
            bal = gsd.get("supply_demand_balance")
            if isinstance(bal, (int, float)):
                result["gold_supply_demand_balance_t"] = float(bal)
            break

    # Panewslab 8 板块
    for (src, sub), rec in latest.items():
        if src == "panewslab" and rec["metrics"]:
            m = _safe_json(rec["metrics"])
            prefix = f"pn_{sub}_"
            for k, v in m.items():
                if isinstance(v, (int, float, str)):
                    result[f"{prefix}{k}"] = v

    return result


def _fetch_yf_returns(symbol: str, days: int = 250) -> Dict[str, float]:
    """从 yfinance 获取日线收盘价，返回 {date_str: close}。

    FAIL-OPEN：yfinance 失败时返回空 dict。
    """
    try:
        import yfinance as yf
        end = datetime.now()
        start = end - timedelta(days=days + 60)
        df = yf.download(symbol, start=start.strftime("%Y-%m-%d"),
                         end=end.strftime("%Y-%m-%d"), progress=False, auto_adjust=True)
        if df.empty:
            return {}
        # 处理 MultiIndex columns
        if isinstance(df.columns, object) and hasattr(df.columns, "levels"):
            close_col = [c for c in df.columns if c[0] == "Close"]
            if close_col:
                closes = df[close_col[0]]
            else:
                closes = df["Close"]
        else:
            closes = df["Close"]
        result = {}
        for idx, val in closes.items():
            date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
            result[date_str] = float(val)
        return result
    except Exception:
        return {}


def _compute_rank_ic(factor: np.ndarray, forward_ret: np.ndarray) -> float:
    """计算 Spearman RankIC。"""
    if len(factor) < 3 or len(forward_ret) < 3:
        return 0.0
    mask = ~(np.isnan(factor) | np.isnan(forward_ret))
    f = factor[mask]
    r = forward_ret[mask]
    if len(f) < 3:
        return 0.0
    # rank
    from scipy.stats import spearmanr
    try:
        ic, _ = spearmanr(f, r)
        return float(ic) if not np.isnan(ic) else 0.0
    except Exception:
        return 0.0


def _compute_ic_ir(ic_series: List[float]) -> Tuple[float, float]:
    """计算 IC_IR = mean(IC) / std(IC)。

    返回 (ic_mean, ic_ir)。
    """
    if len(ic_series) < 2:
        return 0.0, 0.0
    arr = np.array(ic_series)
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1))
    if std < 1e-9:
        return mean, 0.0
    return mean, mean / std


def analyze_ic() -> List[Dict[str, Any]]:
    """主分析逻辑，返回 IC 报告行列表。"""
    print(f"[IC] 数据路径: {_DB_PATH}")
    print(f"[IC] 数据库存在: {_DB_PATH.exists()}")

    snapshots = _get_daily_snapshots(_DB_PATH)
    n_days = len(snapshots)
    print(f"[IC] 快照天数: {n_days}")

    if n_days < 10:
        print(f"[IC] ⚠️ 样本量不足（{n_days}<10），结果仅供参考，需≥250 天才具统计意义")

    # 获取三类资产的价格
    prices: Dict[str, Dict[str, float]] = {}
    for cls, symbol in ASSET_RETURN_MAP.items():
        prices[cls] = _fetch_yf_returns(symbol, days=max(n_days + 30, 250))
        print(f"[IC] {cls}({symbol}) 价格点数: {len(prices[cls])}")

    computer = FiveDomainFeatureComputer(enable=True)

    # 收集每个子指标的 (factor_value, forward_return) 对
    factor_returns: Dict[str, List[Tuple[float, float]]] = {}

    for i, (date_str, coin_data_by_cls) in enumerate(snapshots):
        # 计算未来 7 日收益
        for cls in ASSET_RETURN_MAP:
            cd = coin_data_by_cls.get(cls, {})
            if not cd:
                continue
            # 找 7 天后的价格
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d")
                future_date = d + timedelta(days=7)
                future_date_str = future_date.strftime("%Y-%m-%d")
            except Exception:
                continue

            cls_prices = prices.get(cls, {})
            current_price = cls_prices.get(date_str)
            future_price = cls_prices.get(future_date_str)
            if current_price is None or future_price is None or current_price <= 0:
                continue
            fwd_ret = (future_price - current_price) / current_price

            # 提取各子指标原始值
            for dim, field_map in SUBINDICATOR_MAP.items():
                for field, name in field_map.items():
                    val = cd.get(field)
                    if val is None:
                        continue
                    # 处理非数值字段（merrill_phase, regime 是字符串）
                    if isinstance(val, str):
                        # 映射到数值
                        val = _categorical_to_numeric(field, val)
                    if not isinstance(val, (int, float)):
                        continue
                    key = f"{cls}|{dim}|{name}"
                    factor_returns.setdefault(key, []).append((float(val), fwd_ret))

    # 计算每个因子的 IC
    report_rows = []
    WINDOW = 60  # 滚动窗口天数
    for key, pairs in factor_returns.items():
        cls, dim, name = key.split("|", 2)
        if len(pairs) < WINDOW:
            # 样本不足，用全样本单期 IC
            if len(pairs) < 5:
                report_rows.append({
                    "asset_class": cls, "dimension": dim, "subindicator": name,
                    "n_samples": len(pairs), "rank_ic": None, "ic_mean": None,
                    "ic_ir": None, "significant": False,
                    "note": "样本<5，无法计算IC",
                })
            else:
                factors = np.array([p[0] for p in pairs])
                rets = np.array([p[1] for p in pairs])
                ic = _compute_rank_ic(factors, rets)
                report_rows.append({
                    "asset_class": cls, "dimension": dim, "subindicator": name,
                    "n_samples": len(pairs), "rank_ic": round(ic, 4),
                    "ic_mean": round(ic, 4), "ic_ir": 0.0, "significant": False,
                    "note": f"样本<{WINDOW}，IC_IR无法计算",
                })
            continue

        # 滚动窗口计算多期 IC
        factors = np.array([p[0] for p in pairs])
        rets = np.array([p[1] for p in pairs])
        ic_series = []
        for i in range(WINDOW, len(factors) + 1):
            window_f = factors[i - WINDOW:i]
            window_r = rets[i - WINDOW:i]
            ic = _compute_rank_ic(window_f, window_r)
            if ic != 0.0:  # 跳过常数因子窗口
                ic_series.append(ic)
        ic_mean, ic_ir = _compute_ic_ir(ic_series) if ic_series else (0.0, 0.0)
        # 全样本 IC
        full_ic = _compute_rank_ic(factors, rets)
        significant = abs(ic_mean) > 0.03 and abs(ic_ir) > 0.5
        report_rows.append({
            "asset_class": cls, "dimension": dim, "subindicator": name,
            "n_samples": len(pairs), "rank_ic": round(full_ic, 4),
            "ic_mean": round(ic_mean, 4), "ic_ir": round(ic_ir, 4),
            "significant": significant,
            "note": "有效" if significant else "不显著",
        })

    return report_rows


def _categorical_to_numeric(field: str, val: str) -> Optional[float]:
    """将分类字段映射为数值。"""
    merrill_map = {"RECOVERY": 0.25, "EXPANSION": 0.50, "STAGFLATION": 0.75, "DEFLATION": 1.0}
    regime_map = {"trend_up": 0.2, "breakout": 0.4, "ranging": 0.5, "high_volatility": 0.7, "trend_down": 0.9}
    if field == "merrill_phase":
        return merrill_map.get(val, 0.5)
    if field == "regime":
        return regime_map.get(val, 0.5)
    return None


def save_report(rows: List[Dict[str, Any]]) -> Path:
    """保存 IC 报告到 CSV。"""
    _RUNTIME.mkdir(parents=True, exist_ok=True)
    import csv
    with open(_REPORT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [
            "asset_class", "dimension", "subindicator", "n_samples",
            "rank_ic", "ic_mean", "ic_ir", "significant", "note"
        ])
        writer.writeheader()
        writer.writerows(rows)
    return _REPORT_CSV


def print_summary(rows: List[Dict[str, Any]]) -> None:
    """打印 IC 报告摘要。"""
    print("\n" + "=" * 80)
    print("战略层五域因子 IC 检验报告")
    print("=" * 80)
    print(f"{'资产类':<15}{'维度':<6}{'子指标':<14}{'样本':>6}{'RankIC':>8}{'IC_IR':>8}{'显著性':>8}")
    print("-" * 80)
    sig_count = 0
    for r in sorted(rows, key=lambda x: (x["asset_class"], x["dimension"], x["subindicator"])):
        ic_str = f"{r['rank_ic']:.4f}" if r["rank_ic"] is not None else "N/A"
        ir_str = f"{r['ic_ir']:.4f}" if r["ic_ir"] is not None else "N/A"
        sig = "✅" if r["significant"] else "❌"
        if r["significant"]:
            sig_count += 1
        print(f"{r['asset_class']:<15}{r['dimension']:<6}{r['subindicator']:<14}"
              f"{r['n_samples']:>6}{ic_str:>8}{ir_str:>8}{sig:>8}")
    print("-" * 80)
    print(f"显著因子数: {sig_count} / {len(rows)}")
    print(f"显著性阈值: |RankIC|>0.03 且 |IC_IR|>0.5")
    print(f"报告路径: {_REPORT_CSV}")
    print("=" * 80)


if __name__ == "__main__":
    rows = analyze_ic()
    if rows:
        path = save_report(rows)
        print_summary(rows)
        print(f"\n[IC] 报告已保存: {path}")
    else:
        print("[IC] 无数据可分析")
