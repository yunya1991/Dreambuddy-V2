# -*- coding: utf-8 -*-
"""39-金融语义蒸馏系统 · P3 第二批量变：时空周期维度（SPEC v1.4 §9.8，零 token）

从 OKX 日线 K 线计算三个时空周期量变观测（描述性，不做方向判断）：
  1. 盘整区间检测（横有多长）：N 日内振幅 < 阈值 → 盘整状态，记录盘整天数
     突破检测（竖有多高）：盘整后突破区间边界 → 记录盘整时长与突破方向/幅度
  2. 斐波那契关键位触及：以近期高低点计算回撤位（0.236/0.382/0.5/0.618/0.786），
     价格触及关键位 → 记录触及事件
  3. 四年周期位置：以 BTC 减半日为锚点，计算当前处于周期第几年（叙事纪律：仅位置描述）

产出: spacetime_events.jsonl（追加流）+ 状态文件（断点续算）
用法: python3 gen_spacetime_events.py
"""
import json
import sys
import os
import urllib.request
from datetime import datetime, timezone

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SYS_DIR = os.path.dirname(_THIS_DIR)
_REPO = os.path.dirname(_SYS_DIR)

OUT_PATH = os.path.join(_SYS_DIR, "spacetime_events.jsonl")
STATE_PATH = os.path.join(_SYS_DIR, ".spacetime_state.json")

sys.path.insert(0, _THIS_DIR)
import dc_pg  # PostgreSQL 辅助模块（18 中心迁移后替代 SQLite）


def _fetch_fundamental_context(symbol):
    """读取基本面交叉上下文（BDSM 估值百分位 + 资金费率），FAIL-OPEN。"""
    ctx = {"valuation_percentile": None, "funding_rate": None}
    # 资金费率（PostgreSQL，FAIL-OPEN）
    # 注意：sub_category=funding_rate 的最新记录多为 coinglass 来源（Silver 清洗后
    # metrics 仅含 item_count，无实际费率值），故优先取 binance_funding_rate 来源
    # （metrics 含 funding_rate_pct / funding_rate_annualized_pct），取不到再回退。
    try:
        row = dc_pg.fetch_latest_by_source("binance_funding_rate", "funding_rate") \
            or dc_pg.fetch_latest("funding_rate")
        if row:
            m = row.get("metrics") or {}
            if isinstance(m, str):
                try:
                    m = json.loads(m)
                except Exception:
                    m = {}
            for k in ("funding_rate_pct", "funding_rate"):
                if isinstance(m.get(k), (int, float)):
                    ctx["funding_rate"] = float(m[k])
                    break
    except Exception:
        pass
    # BDSM 估值百分位（经 34 系统 L0 快照，FAIL-OPEN）
    try:
        sys.path.insert(0, os.path.join(_REPO, "34-前端应用训练系统"))
        from core.l0_foundation import get_l0
        snap = get_l0().fetch_context("yijing.bdsm")
        if not snap.get("degraded"):
            coins = (snap.get("data") or {}).get("coins") or {}
            info = coins.get(symbol) or {}
            if isinstance(info.get("valuation_percentile"), (int, float)):
                ctx["valuation_percentile"] = float(info["valuation_percentile"])
    except Exception:
        pass
    return ctx


def _cross_validate_note(nature, ctx):
    """基本面交叉验证观察（描述性，不做方向判断）。"""
    if not nature:
        return None
    vp, fr = ctx.get("valuation_percentile"), ctx.get("funding_rate")
    parts = []
    if vp is not None:
        zone = "低估值区" if vp < 30 else ("高估值区" if vp > 70 else "中估值区")
        parts.append(f"估值百分位 {vp:.0f}%（{zone}）")
    if fr is not None:
        bias = "空头偏向" if fr < 0 else "多头偏向"
        parts.append(f"资金费率 {fr:+.4f}（{bias}）")
    if not parts:
        return None
    if "洗盘式" in nature and vp is not None and vp < 30:
        lead = "交叉验证观察：价值区缩量整理"
    elif "洗盘式" in nature and vp is not None and vp > 70:
        lead = "交叉验证观察：高估区缩量整理，方向选择敏感"
    else:
        lead = "交叉验证观察"
    return f"{lead}（{'，'.join(parts)}）"

OKX_CANDLES_URL = "https://www.okx.com/api/v5/market/candles?instId={inst}&bar=1D&limit={limit}"
SYMBOLS = ["BTC-USDT", "ETH-USDT"]

# 盘整检测参数（预注册，叙事纪律：调整需回测校准）
CONSOL_WINDOW = 30        # 检测窗口：近 30 日
CONSOL_RANGE_PCT = 0.15   # 盘整判定：窗口内高低振幅 < 15%
# 斐波那契回撤位
FIB_LEVELS = [0.236, 0.382, 0.5, 0.618, 0.786]
FIB_TOLERANCE = 0.008     # 触及容差：价格距关键位 < 0.8%
# 四年周期锚点：BTC 减半日（历史：2020-05-11, 2024-04-20；下次预估 2028）
HALVING_ANCHORS = ["2020-05-11", "2024-04-20"]


def _load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_run": ""}


def _save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f)


def fetch_candles(inst, limit=100):
    """拉取 OKX 日线 K 线，返回按时间升序的 [{ts, o, h, l, c}]。"""
    url = OKX_CANDLES_URL.format(inst=inst, limit=limit)
    req = urllib.request.Request(url, headers={"User-Agent": "spacetime/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    rows = data.get("data", [])
    candles = []
    for r in rows:
        # OKX 返回: [ts, o, h, l, c, vol, ...]（时间降序）
        candles.append({
            "ts": int(r[0]) / 1000,
            "o": float(r[1]), "h": float(r[2]),
            "l": float(r[3]), "c": float(r[4]),
            "v": float(r[5]),
        })
    candles.reverse()  # 升序
    return candles


def _atr(candles, n):
    """简单 ATR（真实波幅均值，参考洗盘判定 F3 口径）。"""
    if len(candles) < n + 1:
        return None
    trs = []
    for i in range(-n, 0):
        c, p = candles[i], candles[i - 1]
        tr = max(c["h"] - c["l"], abs(c["h"] - p["c"]), abs(c["l"] - p["c"]))
        trs.append(tr)
    return sum(trs) / len(trs)


def detect_consolidation(candles):
    """盘整检测（横有多长）与突破观测（竖有多高）。
    参考系统洗盘判定口径（washout F1/F3）：
      - F3 ATR 压缩比 atr_5/atr_20 < 1 → 振幅收窄（盘整确认）
      - F1 量比 vol/ma20 < 0.8 → 缩量整理（洗盘式盘整特征）
      - 量价区分：缩量+收窄=洗盘式盘整；放量+宽幅=关注方向选择
    """
    events = []
    if len(candles) < CONSOL_WINDOW:
        return events
    win = candles[-CONSOL_WINDOW:]
    hi = max(c["h"] for c in win)
    lo = min(c["l"] for c in win)
    last = candles[-1]
    if lo <= 0:
        return events
    range_pct = (hi - lo) / lo
    # 洗盘口径参考指标（F3 ATR 压缩比 / F1 量比）
    atr5, atr20 = _atr(candles, 5), _atr(candles, 20)
    atr_ratio = round(atr5 / atr20, 3) if atr5 and atr20 and atr20 > 0 else None
    vols = [c["v"] for c in candles[-21:-1]]
    vol_ma20 = sum(vols) / len(vols) if vols else None
    vol_ratio = round(last["v"] / vol_ma20, 2) if vol_ma20 and vol_ma20 > 0 else None
    if range_pct < CONSOL_RANGE_PCT:
        # 盘整状态：结合洗盘口径判定盘整性质（描述性）
        nature = None
        if atr_ratio is not None and vol_ratio is not None:
            if atr_ratio < 1.0 and vol_ratio < 0.8:
                nature = "洗盘式盘整（振幅收窄+缩量整理，参考 washout F1/F3 口径）"
            elif atr_ratio >= 1.0 and vol_ratio >= 1.5:
                nature = "放量宽幅盘整（波动放大+放量，关注方向选择）"
            else:
                nature = "普通盘整"
        events.append({
            "layer": "spacetime", "dim": "time",
            "type": "consolidation",
            "symbol": None,
            "detail": {
                "days": CONSOL_WINDOW, "range_pct": round(range_pct, 4),
                "high": hi, "low": lo,
                "atr_compress_ratio": atr_ratio,
                "volume_ratio_20d": vol_ratio,
                "nature": nature,
            },
            "note": f"近{CONSOL_WINDOW}日振幅 {range_pct:.1%} < {CONSOL_RANGE_PCT:.0%}，盘整状态（横有多长：{CONSOL_WINDOW}日）"
                     + (f"；{nature}（ATR比 {atr_ratio}，量比 {vol_ratio}）" if nature else ""),
        })
    else:
        # 非盘整：检测是否刚从盘整突破（前窗口盘整 + 当前价出区间）
        prev_win = candles[-(CONSOL_WINDOW + 1):-1]
        if prev_win:
            p_hi = max(c["h"] for c in prev_win)
            p_lo = min(c["l"] for c in prev_win)
            p_range = (p_hi - p_lo) / p_lo if p_lo > 0 else 1.0
            if p_range < CONSOL_RANGE_PCT:
                c = last["c"]
                if c > p_hi or c < p_lo:
                    direction = "up" if c > p_hi else "down"
                    events.append({
                        "layer": "spacetime", "dim": "time",
                        "type": "breakout",
                        "symbol": None,
                        "detail": {
                            "consolidation_days": CONSOL_WINDOW,
                            "direction": direction,
                            "break_pct": round(abs(c - (p_hi if direction == "up" else p_lo)) / (p_hi - p_lo) * 100, 2) if p_hi > p_lo else 0,
                        },
                        "note": f"盘整{CONSOL_WINDOW}日后向上突破" if direction == "up" else f"盘整{CONSOL_WINDOW}日后向下突破",
                    })
    return events


def detect_fibonacci(candles):
    """斐波那契回撤位触及检测（空间维度）。"""
    events = []
    if len(candles) < 30:
        return events
    win = candles[-90:] if len(candles) >= 90 else candles
    hi = max(c["h"] for c in win)
    lo = min(c["l"] for c in win)
    last = candles[-1]["c"]
    if hi <= lo:
        return events
    # 回撤位：从高点向低点回撤
    for level in FIB_LEVELS:
        fib_price = hi - (hi - lo) * level
        if abs(last - fib_price) / fib_price < FIB_TOLERANCE:
            events.append({
                "layer": "spacetime", "dim": "space",
                "type": "fib_touch",
                "symbol": None,
                "detail": {
                    "level": level, "fib_price": round(fib_price, 2),
                    "last": last, "swing_high": hi, "swing_low": lo,
                },
                "note": f"价格触及斐波那契 {level} 回撤位（{fib_price:.0f}）",
            })
            break  # 每次只记最接近的一个位
    return events


def detect_cycle_position():
    """四年周期位置（减半锚点，仅位置描述）。"""
    events = []
    now = datetime.now(timezone.utc)
    anchors = [datetime.strptime(a, "%Y-%m-%d").replace(tzinfo=timezone.utc)
               for a in HALVING_ANCHORS]
    current_anchor = None
    for a in anchors:
        if now >= a:
            current_anchor = a
    if current_anchor is None:
        return events
    days_since = (now - current_anchor).days
    years_since = days_since / 365.25
    events.append({
        "layer": "spacetime", "dim": "cycle",
        "type": "cycle_position",
        "symbol": "BTC",
        "detail": {
            "halving_anchor": current_anchor.strftime("%Y-%m-%d"),
            "days_since": days_since,
            "years_since": round(years_since, 2),
            "cycle_year": min(4, int(years_since) + 1),
        },
        "note": f"减半后第 {round(years_since, 1)} 年（四年周期第 {min(4, int(years_since) + 1)} 年）",
    })
    return events


def main():
    state = _load_state()
    today = datetime.now().strftime("%Y-%m-%d")
    all_events = []
    for inst in SYMBOLS:
        try:
            candles = fetch_candles(inst)
        except Exception as e:
            print(f"[WARN] {inst} K 线获取失败（FAIL-OPEN 跳过）: {e}")
            continue
        sym = inst.split("-")[0]
        # 基本面交叉上下文（SPEC v1.6 §9.8.4）
        fund_ctx = _fetch_fundamental_context(sym)
        for ev in detect_consolidation(candles) + detect_fibonacci(candles):
            ev["symbol"] = sym
            ev["date"] = today
            # 盘整事件附加基本面交叉验证观察
            if ev["type"] == "consolidation":
                cross = _cross_validate_note(ev["detail"].get("nature"), fund_ctx)
                if cross:
                    ev["detail"]["fundamental_cross"] = fund_ctx
                    ev["note"] = f"{ev['note']}；{cross}"
            all_events.append(ev)
        print(f"[OK] {inst}: {len(candles)} 根日线已分析")
    for ev in detect_cycle_position():
        ev["date"] = today
        all_events.append(ev)
    # 追加写入（同日去重：状态记录已写日期）
    if state.get("last_run") != today:
        with open(OUT_PATH, "a", encoding="utf-8") as f:
            for ev in all_events:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        _save_state({"last_run": today})
        print(f"[OK] 时空周期量变事件 {len(all_events)} 条已追加 → {OUT_PATH}")
    else:
        print(f"[SKIP] 今日已运行（{today}），避免重复记录")
    for ev in all_events:
        print(f"     [{ev['dim']}] {ev['type']}: {ev['note']}")


if __name__ == "__main__":
    main()
