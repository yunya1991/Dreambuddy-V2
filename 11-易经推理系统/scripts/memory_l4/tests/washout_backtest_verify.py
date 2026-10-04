#!/usr/bin/env python3
"""W5 洗盘判定系统 — 事后归因回测验证脚本.

对历史止损出场交易做后视归因：
  1. 触发门激活率（WashoutTriggerGate.should_activate）
  2. 后视反弹判定（止损后价格是否回到入场价 → 判断是否洗盘扫损）
  3. W5 价值估算（避免被扫损的损失 vs 继续逆向的额外损失）

FAIL-OPEN：任何单条交易拉数据失败，跳过该交易继续下一条，不中断。
方向感知：long 止损看"价格是否回升过入场价"；short 止损看"价格是否回落破入场价"。
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd
import requests

# ---- sys.path 设置：bcrm2 包位于 scripts/memory_l4/bcrm2 ----
SCRIPT_DIR = Path(__file__).resolve().parent
L4_DIR = SCRIPT_DIR.parent  # .../scripts/memory_l4
sys.path.insert(0, str(L4_DIR))

from bcrm2.washout_trigger_gate import WashoutTriggerGate  # noqa: E402

TRADE_INDEX = (
    "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/.workbuddy/trade_index/"
    "all_trades_index.jsonl"
)
RESULT_CSV = str(SCRIPT_DIR / "washout_backtest_result.csv")
SUMMARY_JSON = str(SCRIPT_DIR / "washout_backtest_summary.json")

OKX_URL = "https://www.okx.com/api/v5/market/history-candles"


# ---------------------------------------------------------------------------
# OKX K 线拉取（支持 after=拉之前 / before=拉之后）
# ---------------------------------------------------------------------------
def _build_session() -> requests.Session:
    s = requests.Session()
    s.trust_env = True
    proxies: dict = {}
    https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    all_proxy = os.environ.get("ALL_PROXY") or os.environ.get("all_proxy")
    if https_proxy:
        proxies["https"] = https_proxy
    if http_proxy:
        proxies["http"] = http_proxy
    if all_proxy and not proxies:
        proxies["http"] = all_proxy
        proxies["https"] = all_proxy
    if not proxies:
        # 本地 Clash 默认端口探测（与 data_fetcher 保持一致）
        for port in (7890, 7891, 14122, 38324):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                    proxies = {
                        "http": f"http://127.0.0.1:{port}",
                        "https": f"http://127.0.0.1:{port}",
                    }
                    break
            except Exception:
                continue
    if proxies:
        s.proxies = dict(proxies)
    return s


_SESSION: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = _build_session()
    return _SESSION


def _parse_candles(rows: list) -> pd.DataFrame:
    df = pd.DataFrame(
        rows,
        columns=[
            "ts", "open", "high", "low", "close",
            "volume", "vol_ccy", "vol_ccy_quote", "confirm",
        ],
    )
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    df["timestamp"] = pd.to_datetime(df["ts"].astype(int), unit="ms", utc=True)
    df = df.set_index("timestamp").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df[["open", "high", "low", "close", "volume"]]


_BAR_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
           "1H": 3_600_000, "4H": 14_400_000, "1D": 86_400_000, "1W": 604_800_000}


def fetch_candles(
    coin: str,
    bar: str,
    anchor_ts_ms: int,
    direction: str,
    n_bars: int,
) -> Tuple[pd.DataFrame, Optional[str]]:
    """拉取 K 线。

    OKX history-candles 语义（已实测确认）：
      - after=X  → 返回 ts < X 的数据（更旧），newest-first。
      - before=X → 返回 ts > X 的【最新一批】（而非紧接其后），不可用于正向翻页。
    因此两种方向都用 after= 游标实现：
      - 'before'：after=anchor，取 <= anchor 的最新 n 根（= 紧接锚点之前）。
      - 'after' ：after=(anchor + n*bar_ms)，取 >= anchor 的最旧 n 根（= 紧接锚点之后）。

    Args:
        coin: 币种符号，如 BTC（内部拼 -USDT / -USDT-SWAP）。
        bar: K 线周期，如 '1D' / '1H'。
        anchor_ts_ms: 锚点时间戳（毫秒）。
        direction: 'before' = 拉锚点【之前】的数据；'after' = 拉锚点【之后】的数据。
        n_bars: 目标根数。
    Returns:
        (DataFrame[open,high,low,close,volume], 实际命中的 instId 或 None)
    """
    s = _get_session()
    base = (
        coin.upper().replace("-USDT", "").replace("USDT", "").replace("-SWAP", "")
    )
    candidates = [f"{base}-USDT", f"{base}-USDT-SWAP"]
    bar_ms = _BAR_MS.get(bar, 3_600_000)
    anchor_ts = pd.Timestamp(anchor_ts_ms, unit="ms", tz="UTC")

    if direction == "after":
        # 游标前移到锚点+n 根之外，用 after= 拉取窗口
        query_cursor = str(anchor_ts_ms + (n_bars + 5) * bar_ms)
        window_end = anchor_ts + pd.Timedelta(milliseconds=(n_bars + 1) * bar_ms)
    else:  # before
        query_cursor = str(anchor_ts_ms)
        window_end = anchor_ts

    all_rows: list = []
    chosen_inst: Optional[str] = None
    pages = max(1, n_bars // 100 + 3)
    for _ in range(pages):
        got = False
        for inst_id in candidates:
            params: dict = {"instId": inst_id, "bar": bar, "limit": "100",
                            "after": query_cursor}
            try:
                r = s.get(OKX_URL, params=params, timeout=10)
                j = r.json()
            except Exception:
                continue
            if j.get("code") == "0" and j.get("data"):
                rows = j["data"]
                all_rows.extend(rows)
                # OKX 返回 newest→oldest，最后一条是最旧 → 下一页游标
                query_cursor = rows[-1][0]
                chosen_inst = inst_id
                got = True
                break
        if not got:
            break
        if len(all_rows) >= n_bars + 100:  # 多拉一点便于过滤
            break
        time.sleep(0.15)

    if not all_rows:
        return pd.DataFrame(), None
    df = _parse_candles(all_rows)
    if direction == "after":
        df = df[(df.index >= anchor_ts) & (df.index <= window_end)]
        df = df.head(n_bars)  # 升序后最旧 n 根 = 紧接锚点之后
    else:
        df = df[df.index <= anchor_ts]
        df = df.tail(n_bars)  # 升序后最新 n 根 = 紧接锚点之前
    return df, chosen_inst


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def load_stoploss_trades() -> list:
    trades = []
    with open(TRADE_INDEX, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                trades.append(json.loads(line))
            except Exception:
                continue
    sl = []
    for t in trades:
        reason = t.get("exit_reason", "") or ""
        ep = float(t.get("entry_price", 0) or 0)
        et_in = t.get("entry_time", "") or ""
        et_out = t.get("exit_time", "") or ""
        if "STOP_LOSS" in reason and ep > 0 and et_in and et_out:
            sl.append(t)
    return sl


def _is_direction_aware_rebound(
    direction: str,
    entry_price: float,
    max_high: Optional[float],
    min_low: Optional[float],
    strong_mult: float,
) -> bool:
    """方向感知反弹判定。

    long 止损：洗盘 = 价格回升过入场价 → max_high >= entry_price * mult(>=1)
    short 止损：洗盘 = 价格回落破入场价 → min_low <= entry_price * mult(<=1)
      strong_mult: 普通=1.0；强反弹 long=1.02 / short=0.98
    """
    if max_high is None or min_low is None:
        return False
    d = (direction or "").lower()
    if d.startswith("short"):
        return min_low <= entry_price * strong_mult
    # long / default
    return max_high >= entry_price * strong_mult


def process_one_trade(t: dict, gate: WashoutTriggerGate) -> dict:
    coin = t.get("coin", "")
    direction = t.get("direction", "")
    entry_price = float(t.get("entry_price", 0) or 0)
    exit_price = float(t.get("exit_price", 0) or 0)
    pnl_pct = float(t.get("pnl_pct", 0) or 0)
    entry_time = pd.Timestamp(t["entry_time"])
    exit_time = pd.Timestamp(t["exit_time"])
    entry_ts_ms = int(entry_time.timestamp() * 1000)
    exit_ts_ms = int(exit_time.timestamp() * 1000)

    rec = {
        "trade_id": t.get("trade_id", ""),
        "coin": coin,
        "direction": direction,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "pnl_pct": pnl_pct,
        "trigger_activated": False,
        "rebound_24h": False,
        "rebound_48h_strong": False,
        "max_high_24h": None,
        "max_high_48h": None,
        "min_low_24h": None,
        "min_low_48h": None,
        "adverse_move_pct": 0.0,  # 若 W5 误判 hold，止损后继续逆向的额外损失(pct)
        "daily_bars": 0,
        "hourly_bars": 0,
        "note": "",
    }

    # --- 1) 1D 触发门判定（拉 entry_time 之前 260 根）---
    try:
        daily_df, _inst = fetch_candles(coin, "1D", entry_ts_ms, "before", 260)
        rec["daily_bars"] = len(daily_df)
        if len(daily_df) >= 31:
            rec["trigger_activated"] = bool(gate.should_activate(daily_df))
        else:
            rec["note"] = "daily_bars<31"
    except Exception as e:
        rec["note"] = f"daily_err:{type(e).__name__}:{e}"

    # --- 2) 1H 后视反弹（拉 exit_time 之后 50 根 ≈ 48h+缓冲）---
    try:
        hour_df, _inst2 = fetch_candles(coin, "1H", exit_ts_ms, "after", 50)
        rec["hourly_bars"] = len(hour_df)
        if len(hour_df) > 0:
            h24 = hour_df.head(24)
            h48 = hour_df.head(48)
            max_high_24 = float(h24["high"].max()) if len(h24) > 0 else None
            max_high_48 = float(h48["high"].max()) if len(h48) > 0 else None
            min_low_24 = float(h24["low"].min()) if len(h24) > 0 else None
            min_low_48 = float(h48["low"].min()) if len(h48) > 0 else None
            rec["max_high_24h"] = max_high_24
            rec["max_high_48h"] = max_high_48
            rec["min_low_24h"] = min_low_24
            rec["min_low_48h"] = min_low_48
            # 方向感知
            rec["rebound_24h"] = _is_direction_aware_rebound(
                direction, entry_price, max_high_24, min_low_24, 1.0
            )
            strong_mult = 1.02 if (direction or "").lower().startswith("long") else 0.98
            rec["rebound_48h_strong"] = _is_direction_aware_rebound(
                direction, entry_price, max_high_48, min_low_48, strong_mult
            )
            # 误判额外损失：若 hold 不止损，止损后价格继续逆向的幅度
            d = (direction or "").lower()
            if d.startswith("short"):
                # short 持仓，价格上行才亏；额外亏损 = max(0, max_high_48 - exit_price)/entry
                if max_high_48 is not None and max_high_48 > exit_price:
                    rec["adverse_move_pct"] = (max_high_48 - exit_price) / entry_price
            else:
                # long 持仓，价格下行才亏；额外亏损 = max(0, exit_price - min_low_48)/entry
                if min_low_48 is not None and min_low_48 < exit_price:
                    rec["adverse_move_pct"] = (exit_price - min_low_48) / entry_price
        else:
            if not rec["note"]:
                rec["note"] = "hourly_empty"
    except Exception as e:
        if rec["note"]:
            rec["note"] += f"|hourly_err:{type(e).__name__}:{e}"
        else:
            rec["note"] = f"hourly_err:{type(e).__name__}:{e}"

    return rec


def main() -> int:
    sl_trades = load_stoploss_trades()
    total = len(sl_trades)
    print(f"=== W5 事后归因回测 ===")
    print(f"止损出场样本: {total} 条\n")

    gate = WashoutTriggerGate()
    results: list = []
    for i, t in enumerate(sl_trades, 1):
        print(f"[{i}/{total}] {t.get('coin','?')} {t.get('direction','')} "
              f"entry={t.get('entry_price')} ...", flush=True)
        try:
            rec = process_one_trade(t, gate)
        except Exception as e:
            # 顶层 FAIL-OPEN
            rec = {
                "trade_id": t.get("trade_id", ""),
                "coin": t.get("coin", ""),
                "direction": t.get("direction", ""),
                "entry_price": t.get("entry_price", 0),
                "exit_price": t.get("exit_price", 0),
                "pnl_pct": t.get("pnl_pct", 0),
                "trigger_activated": False,
                "rebound_24h": False,
                "rebound_48h_strong": False,
                "max_high_24h": None,
                "max_high_48h": None,
                "min_low_24h": None,
                "min_low_48h": None,
                "adverse_move_pct": 0.0,
                "daily_bars": 0,
                "hourly_bars": 0,
                "note": f"top_fail:{type(e).__name__}:{e}",
            }
        results.append(rec)
        time.sleep(0.5)  # 限频

    # 保存明细 CSV
    df = pd.DataFrame(results)
    df.to_csv(RESULT_CSV, index=False)

    # 统计
    valid = [r for r in results if r["daily_bars"] > 0 or r["hourly_bars"] > 0]
    n_valid_trigger = sum(1 for r in results if r["daily_bars"] > 0)
    n_trigger = sum(1 for r in results if r["trigger_activated"])
    n_rebound24 = sum(1 for r in results if r["rebound_24h"])
    n_strong48 = sum(1 for r in results if r["rebound_48h_strong"])

    # 价值估算（pct 累加；pnl_pct 为负数代表亏损，取绝对值）
    potential_value = sum(
        abs(r["pnl_pct"]) for r in results if r["rebound_24h"]
    )
    misjudge_risk = sum(
        r["adverse_move_pct"] for r in results if not r["rebound_48h_strong"]
    )
    net_value = potential_value - misjudge_risk

    summary = {
        "total_stoploss_trades": total,
        "valid_samples": len(valid),
        "trigger_gate_activated": n_trigger,
        "trigger_gate_valid_base": n_valid_trigger,
        "trigger_activation_rate": (
            round(n_trigger / n_valid_trigger, 4) if n_valid_trigger else 0.0
        ),
        "rebound_24h_count": n_rebound24,
        "rebound_24h_rate": round(n_rebound24 / total, 4) if total else 0.0,
        "rebound_48h_strong_count": n_strong48,
        "rebound_48h_strong_rate": round(n_strong48 / total, 4) if total else 0.0,
        "w5_potential_value_pct": round(potential_value, 4),
        "w5_misjudge_risk_pct": round(misjudge_risk, 4),
        "w5_net_value_pct": round(net_value, 4),
        "direction_note": (
            "long 止损看 max_high>=entry；short 止损看 min_low<=entry（方向感知）"
        ),
        "data_issues": [r for r in results if r.get("note")],
    }
    with open(SUMMARY_JSON, "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # 报告
    print("\n=== W5 事后归因回测报告 ===")
    print(f"样本数: {total} 条止损出场交易")
    print(f"有效数据样本: {len(valid)} 条（拉到 K 线的）")
    print(f"触发门激活率: {n_trigger}/{n_valid_trigger} "
          f"({round(n_trigger/n_valid_trigger*100,1) if n_valid_trigger else 0}%) "
          f"[基于 {n_valid_trigger} 条有 1D 数据]")
    print(f"止损后 24h 反弹率: {n_rebound24}/{total} "
          f"({round(n_rebound24/total*100,1) if total else 0}%)  ← 说明是洗盘扫损")
    print(f"止损后 48h 强反弹率: {n_strong48}/{total} "
          f"({round(n_strong48/total*100,1) if total else 0}%)")
    print(f"W5 潜在价值（避免被扫损的损失）: +{potential_value*100:.2f}%")
    print(f"W5 误判风险（继续逆向的额外损失）: +{misjudge_risk*100:.2f}%")
    print(f"净价值: {'+' if net_value>=0 else ''}{net_value*100:.2f}%")
    print(f"\n明细已保存: {RESULT_CSV}")
    print(f"汇总已保存: {SUMMARY_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
