#!/usr/bin/env python3
"""P3 meme 平台监控（L4 维度一 meme 层）：Pump 平台指标观测。

meme 热点更替快，固定代币清单会滞后，改为平台级指标观测：
  - 新池数量与毕业率（pumpswap 池占比，毕业=从 bonding curve 迁移到 AMM）
  - 新池 FDV 分布中位数
  - 买卖人数比、24h 价格变化分布
数据源：GeckoTerminal 公开 API（已验证可用，无需鉴权）。
产出：meme_platform.json
"""

import http.client
import json
import math
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from statistics import median

# R-42-04/P1-03：DREAMBUDDY_ROOT 环境变量统一模块根路径；未设置时按 __file__ 推导（仓库内模块同级布局）
_DREAMBUDDY_ROOT = os.environ.get("DREAMBUDDY_ROOT") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

API = "https://api.geckoterminal.com/api/v2/networks/solana/new_pools"
OUT = os.path.join(_DREAMBUDDY_ROOT, "40-周期神经网络系统", "meme_platform.json")
PAGES = 5  # 5 页 × 20 池 = 100 个最新池


def fetch_page(page, max_retries=3, base_delay=1.0):
    url = f"{API}?include=dex&page={page}"
    last_exc = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except (
            urllib.error.URLError,
            http.client.IncompleteRead,
            TimeoutError,
            json.JSONDecodeError,
        ) as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                print(
                    f"  [retry] page {page} attempt {attempt+1}/{max_retries} failed: {exc}; sleep {delay}s"
                )
                time.sleep(delay)
    raise last_exc


def fetch_binance_web3_bsc(conn=None, hours=24):
    """读 18 域 web3_market 聚合条（BSC 小币横截面），fail-open。

    来源：18-数据获取中心 采集器 binance_web3_agg 的 sub_category=web3_market。
    该条已由 18 侧做过横截面聚合（中位数/比率），这里只做读取与字段挑选，
    不再二次聚合，避免口径分叉。
    """
    try:
        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import db_access

        _conn = conn or db_access.connect()
        ph = "%s" if db_access.backend() == "postgres" else "?"
        cur = _conn.cursor()
        cur.execute(
            "SELECT timestamp, metrics FROM records "
            f"WHERE source={ph} AND sub_category={ph} "
            "ORDER BY timestamp DESC LIMIT 1",
            ("binance_web3_agg", "web3_market"),
        )
        row = cur.fetchone()
        if not row:
            return {"degraded": True, "reason": "no-web3-market-record"}
        ts_text, metrics = row
        if isinstance(metrics, str):
            metrics = json.loads(metrics)
        if not isinstance(metrics, dict):
            return {"degraded": True, "reason": "metrics-not-object"}
        try:
            rec_dt = datetime.fromisoformat(str(ts_text).replace("Z", "+00:00"))
            if rec_dt.tzinfo is None:
                rec_dt = rec_dt.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - rec_dt).total_seconds() / 3600.0
        except Exception:
            age_hours = None
        keys = (
            "web3_structure_count",
            "web3_new_wallet_pct_med",
            "web3_top10_conc_med",
            "web3_high_risk_ratio",
            "web3_hype_med",
            "web3_sentiment_mean",
            "web3_meme_score_med",
            "web3_smart_money_net_inflow_usd",
            "web3_narrative_net_inflow_med",
            "web3_buy_sell_vol_ratio",
            "web3_liquidity_med",
        )
        out = {
            "degraded": False,
            "generated_at": str(ts_text),
            "age_hours": (round(age_hours, 2) if age_hours is not None else None),
        }
        for k in keys:
            out[k] = metrics.get(k)
        if age_hours is not None and age_hours > hours:
            out["stale"] = True
        return out
    except Exception as exc:  # noqa: BLE001 fail-open：40 主链路不因 web3 缺失中断
        return {"degraded": True, "reason": f"web3-read-failed: {exc}"}


# ── meme 层温度标定锚点 ─────────────────────────────────────────────
# 说明：BSC 小币横截面刚接入，历史样本 < 30，暂用固定锚点做单调映射；
# 样本足够后应改为「相对自身历史的分位/z-score」，届时这些常量仅作兜底。
_HYPE_LOG_LO = 5.0  # log10(social_hype)=5（约 10 万）→ 温度 0
_HYPE_LOG_SPAN = 1.5  # 再涨 1.5 个数量级（约 316 万）→ 温度 1
_RISK_FULL_RATIO = 0.15  # 高危代币占比 15% → 风险偏好满量程
_CONC_LO_PCT = 60.0  # 前10集中度 ≤60% 视为分散（结构风险 0）
_CONC_SPAN_PCT = 40.0  # 60%→100% 线性映射到 0→1
_MEME_SCORE_LO = 2.0  # meme 算法评分 2.0 → 热度 0
_MEME_SCORE_SPAN = 2.5  # 2.0→4.5 → 热度 1
_GRAD_LO_PCT = 5.0  # Solana 毕业率 5% → 热度 0
_GRAD_SPAN_PCT = 20.0  # 5%→25% → 热度 1
# 分位标定门槛：19 DAL 中同一指标有效样本 ≥ 该值后，温度改用它自身历史分位
_PCT_MIN_SAMPLES = 30
_WEB3_HISTORY_METRICS = (
    "web3_hype_med",
    "web3_sentiment_mean",
    "web3_high_risk_ratio",
)


def _clamp01(x):
    return max(0.0, min(1.0, float(x)))


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _pct_rank(history_values, current):
    """当前值在自身历史中的分位（0-1）；有效样本不足 → None 走固定锚点。"""
    vals = [v for v in history_values if v is not None]
    if len(vals) < _PCT_MIN_SAMPLES:
        return None
    return sum(1 for v in vals if v <= current) / len(vals)


def load_web3_history(max_snapshots=168):
    """读 19 DAL 最近 N 个 web3_market 横截面（按 timestamp 分组）。

    仅用于温度分位标定；后端不可用/无数据 → []（fail-open，回退固定锚点）。
    """
    try:
        from db_access import _placeholder, connect
    except Exception:
        return []
    sql = _placeholder(
        "SELECT timestamp, metric_name, metric_value FROM mm_metrics "
        "WHERE sub_category = 'web3_market' ORDER BY timestamp DESC"
    )
    try:
        conn = connect()
        try:
            cur = conn.cursor()
            cur.execute(sql)
            rows = cur.fetchall()
        finally:
            conn.close()
    except Exception:
        return []

    grouped = {}
    for ts, name, value in rows:
        if name not in _WEB3_HISTORY_METRICS:
            continue
        if ts not in grouped:
            if len(grouped) >= max_snapshots:
                break  # rows 已按 timestamp 降序，够数即停
            grouped[ts] = {}
        v = _num(value)
        if v is not None:
            grouped[ts][name] = v
    return list(grouped.values())


def build_meme_layer_metrics(web3_block, graduation_rate_pct, history=None):
    """合成 L4_meme 层的三个消费指标（纯函数，无 IO）。

    - meme_temperature：投机温度 0-1（社交热度 40% + 情绪极性 35% + 风险偏好 25%）
      输入映射优先用**自身历史分位**（samples ≥ 30），不足则回退固定锚点单调映射，
      避免 socialHype 量纲漂移把温度带偏。
    - structure_risk：筹码结构风险 0-1（前 10 集中度）；只做信号折扣，不产生方向
    - meme_heat_composite：双链热度 0-1（BSC meme 算法评分 + Solana 毕业率）

    web3 聚合条缺失/degraded → 返回 degraded，绝不编造数值（FAIL-OPEN）。
    """
    w = web3_block or {}
    if not w or w.get("degraded"):
        return {
            "degraded": True,
            "reason": w.get("reason") or "web3-block-missing",
            "meme_temperature": None,
            "meme_direction": None,
            "structure_risk": None,
            "meme_heat_composite": None,
        }

    hist = history or []
    parts = {}
    part_modes = {}

    def _temperature_part(metric_key, fixed_value):
        """优先历史分位，不足 30 样本回退固定映射。"""
        cur = _num(w.get(metric_key))
        if cur is None or fixed_value is None:
            return None
        pct = _pct_rank([_num(h.get(metric_key)) for h in hist], cur)
        if pct is not None:
            part_modes[metric_key] = "percentile"
            return pct
        part_modes[metric_key] = "fixed"
        return fixed_value

    hype = _num(w.get("web3_hype_med"))
    fixed_hype = (
        _clamp01((math.log10(hype) - _HYPE_LOG_LO) / _HYPE_LOG_SPAN)
        if hype is not None and hype > 0
        else None
    )
    v = _temperature_part("web3_hype_med", fixed_hype)
    if v is not None:
        parts["hype"] = v

    sent = _num(w.get("web3_sentiment_mean"))
    v = _temperature_part(
        "web3_sentiment_mean", _clamp01((sent + 1.0) / 2.0) if sent is not None else None
    )
    if v is not None:
        parts["sentiment"] = v

    risk = _num(w.get("web3_high_risk_ratio"))
    v = _temperature_part(
        "web3_high_risk_ratio", _clamp01(risk / _RISK_FULL_RATIO) if risk is not None else None
    )
    if v is not None:
        parts["risk_appetite"] = v

    temperature = round(sum(parts.values()) / len(parts), 4) if parts else None
    direction = None
    if temperature is not None:
        if temperature >= 0.65:
            direction = "hot"
        elif temperature <= 0.35:
            direction = "cold"
        else:
            direction = "neutral"

    conc = _num(w.get("web3_top10_conc_med"))
    structure_risk = (
        round(_clamp01((conc - _CONC_LO_PCT) / _CONC_SPAN_PCT), 4) if conc is not None else None
    )

    heat = {}
    score = _num(w.get("web3_meme_score_med"))
    if score is not None:
        heat["bsc_meme_score"] = _clamp01((score - _MEME_SCORE_LO) / _MEME_SCORE_SPAN)
    grad = _num(graduation_rate_pct)
    if grad is not None:
        heat["sol_graduation"] = _clamp01((grad - _GRAD_LO_PCT) / _GRAD_SPAN_PCT)
    composite = round(sum(heat.values()) / len(heat), 4) if heat else None

    return {
        "degraded": False,
        "meme_temperature": temperature,
        "meme_direction": direction,
        "structure_risk": structure_risk,
        "meme_heat_composite": composite,
        "inputs": {
            **{k: round(v, 4) for k, v in parts.items()},
            **{k: round(v, 4) for k, v in heat.items()},
        },
        "calibration": {
            "mode": (
                "percentile" if any(v == "percentile" for v in part_modes.values()) else "fixed"
            ),
            "parts_mode": part_modes,
            "history_n": len(hist),
            "percentile_min_samples": _PCT_MIN_SAMPLES,
            "hype_log_lo": _HYPE_LOG_LO,
            "hype_log_span": _HYPE_LOG_SPAN,
            "risk_full_ratio": _RISK_FULL_RATIO,
            "conc_lo_pct": _CONC_LO_PCT,
            "conc_span_pct": _CONC_SPAN_PCT,
            "meme_score_lo": _MEME_SCORE_LO,
            "meme_score_span": _MEME_SCORE_SPAN,
            "graduation_lo_pct": _GRAD_LO_PCT,
            "graduation_span_pct": _GRAD_SPAN_PCT,
        },
    }


def main():
    now = datetime.now(timezone.utc).isoformat()

    pools = []
    dex_names = {}  # dex id -> name
    for page in range(1, PAGES + 1):
        try:
            d = fetch_page(page)
        except Exception as e:
            print(f"page {page} fetch error: {e}")
            break
        for inc in d.get("included", []):
            if inc.get("type") == "dex":
                dex_names[inc["id"]] = inc.get("attributes", {}).get("name", inc["id"])
        pools.extend(d.get("data", []))

    print(f"fetched pools={len(pools)}  dexs={sorted(set(dex_names))}")

    # 按 dex 关系归属分类（pool 的 relationships.dex.data.id）
    pump_fun_pools = []  # pump-fun：内盘 bonding curve
    pumpswap_pools = []  # pumpswap：毕业池（AMM）
    other_pools = []
    for p in pools:
        dex_id = (p.get("relationships", {}).get("dex", {}).get("data") or {}).get("id", "")
        if dex_id == "pump-fun":
            pump_fun_pools.append(p)
        elif dex_id == "pumpswap":
            pumpswap_pools.append(p)
        else:
            other_pools.append(p)

    def pool_stats(plist):
        fdvs = [
            float(p["attributes"]["fdv_usd"])
            for p in plist
            if p["attributes"].get("fdv_usd") is not None
        ]
        vol24 = [float(p["attributes"].get("volume_usd", {}).get("h24", 0)) for p in plist]
        buys = sum(
            int(p["attributes"].get("transactions", {}).get("h24", {}).get("buys", 0))
            for p in plist
        )
        sells = sum(
            int(p["attributes"].get("transactions", {}).get("h24", {}).get("sells", 0))
            for p in plist
        )
        chg = [
            float(p["attributes"].get("price_change_percentage", {}).get("h24", 0)) for p in plist
        ]
        return {
            "count": len(plist),
            "fdv_median_usd": round(median(fdvs), 2) if fdvs else None,
            "fdv_max_usd": round(max(fdvs), 2) if fdvs else None,
            "vol24_total_usd": round(sum(vol24), 2),
            "buys_24h": buys,
            "sells_24h": sells,
            "buy_sell_ratio": round(buys / sells, 3) if sells else None,
            "chg24_median_pct": round(median(chg), 2) if chg else None,
        }

    n_pump = len(pump_fun_pools) + len(pumpswap_pools)
    graduation_rate = (len(pumpswap_pools) / n_pump * 100) if n_pump else None

    out = {
        "generated_at": now,
        "data_source": "GeckoTerminal public API /networks/solana/new_pools",
        "sample": {"pages": PAGES, "pools_total": len(pools)},
        "pump_platform": {
            "pump_fun_bonding_pools": pool_stats(pump_fun_pools),
            "pumpswap_graduated_pools": pool_stats(pumpswap_pools),
            "graduation_rate_pct": (
                round(graduation_rate, 2) if graduation_rate is not None else None
            ),
        },
        "other_dex_pools": pool_stats(other_pools),
        # BSC 小币横截面（18 域 binance_web3_agg 聚合条）；缺失时 degraded，不影响 Solana 主块
        "binance_web3_bsc": fetch_binance_web3_bsc(),
        "note": "毕业率=新池样本中 pumpswap 池占比（毕业=从 bonding curve 迁移到 AMM）；毕业率上升=meme 热度健康，下降=热度退潮；binance_web3_bsc 为 BSC 链跨币聚合（聪明钱净流入/新钱包占比/筹码集中/社交热度），供 40 域 meme 层与 P5 特征消费",
    }
    # meme 层温度/结构/双链热度（由 BSC 横截面 + Solana 毕业率合成，供 L4_meme 层消费）
    out["meme_layer"] = build_meme_layer_metrics(
        out.get("binance_web3_bsc"),
        out["pump_platform"].get("graduation_rate_pct"),
        history=load_web3_history(),
    )

    with open(OUT, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    ml = out["meme_layer"]
    print(
        f"pump-fun(内盘): {len(pump_fun_pools)}  pumpswap(毕业): {len(pumpswap_pools)}  "
        f"毕业率: {out['pump_platform']['graduation_rate_pct']}%"
    )
    print(
        f"meme 层: 温度={ml.get('meme_temperature')} 方向={ml.get('meme_direction')} "
        f"结构风险={ml.get('structure_risk')} 双链热度={ml.get('meme_heat_composite')}"
    )
    print(f"saved: {OUT}")


if __name__ == "__main__":
    main()
