"""D1: CoinFundamental Shadow 价格回填脚本。

用法：
    python scripts/coin_fundamental_price_backfill.py \
        --jsonl runtime/coin_fundamental_shadow.jsonl \
        [--dry-run] [--max-recs 100] [--verbose]

输入：  coin_fundamental_shadow.jsonl（每行一个 CoinFundamentalSignal + 价格 null 字段）
输出：  coin_fundamental_shadow.backfilled.jsonl（原文件保留为审计基线）
字段：  price_at_signal / price_7d_after / price_14d_after / price_30d_after
        return_7d / return_14d / return_30d

FAIL-OPEN：单条 API 异常 → 保持 null 不阻塞整体。
幂等性：  已回填字段（非 null）在 rerun 时不再覆盖。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional


_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_L4_DIR = os.path.normpath(os.path.join(_THIS_DIR, ".."))
if _L4_DIR not in sys.path:
    sys.path.insert(0, _L4_DIR)

from force_vector.coin_fundamental_ranker import (
    CRYPTO_MAP,
    STOCK_MAP,
    METAL_MAP,
    classify_asset_class,
    SHADOW_JSONL_PATH,
)


# ===========================================================================
# Helpers：符号映射 + 年龄门槛 + 收益率
# ===========================================================================

def _map_coin_to_yf_symbol(coin: str) -> Optional[str]:
    """三类资产 → yfinance 历史价格 symbol。

    分派按 classify_asset_class（按资产类不强制 MAP 包含）：
    - crypto_usdt     → {COIN}-USD   e.g. BTC→BTC-USD, C0→C0-USD（测试兼容）
    - us_stock        → TICKER       e.g. NVDA→NVDA
    - precious_metal  → METAL_MAP.yfinance_etf  XAUUSD→GLD, XAGUSD→SLV
    - 未知 → None（跳过不报错）
    """
    if not coin:
        return None
    cls = classify_asset_class(coin)
    if cls == "crypto_usdt":
        return f"{coin}-USD"
    if cls == "us_stock":
        return coin
    if cls == "precious_metal":
        if coin in METAL_MAP:
            info = METAL_MAP.get(coin) or {}
            tk = info.get("yfinance_etf")
            return tk or None
        # 其他贵金属符号按 COIN-USD 兼容映射兜底（后续扩展）
        return f"{coin}-USD"
    return None


def _parse_ts(ts: str) -> Optional[datetime]:
    """解析 ISO8601 时间戳；失败返回 None。"""
    if not ts or not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _should_backfill_window(timestamp_iso: str, window_days: int,
                            now: Optional[datetime] = None) -> bool:
    """当前时间与信号的间隔 ≥ window_days → 允许回填该窗口。"""
    dt = _parse_ts(timestamp_iso)
    if dt is None:
        return False
    if now is None:
        now = datetime.now(dt.tzinfo or timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=dt.tzinfo or timezone.utc)
    delta = now - dt
    return delta.days >= window_days


def _return_pct(price_at: float, price_after: float) -> Optional[float]:
    """(p_after / p_at - 1) * 100；p_at 为 0 或 None → None（FAIL-OPEN）。"""
    try:
        p0 = float(price_at)
        p1 = float(price_after)
    except (TypeError, ValueError):
        return None
    if p0 == 0:
        return None
    return (p1 / p0 - 1.0) * 100.0


# ===========================================================================
# yfinance 历史价格读取（封装为可 mock 的独立函数）
# ===========================================================================

def _fetch_price_at_date(symbol: str, target_date: date) -> Optional[float]:
    """取 yfinance 目标日期附近的收盘价格。

    拉取 [target_date - 5d, target_date + 5d]，取最接近（≤target_date）的可用日期。
    失败（网络/缺包/无数据）→ 返回 None（调用方 FAIL-OPEN）。
    """
    try:
        import yfinance as yf  # 延迟导入 — 测试时通过 mock 跳过
    except ImportError:
        return None

    try:
        start = target_date - timedelta(days=6)
        end = target_date + timedelta(days=2)  # yf history end is exclusive, give 1 padding day
        df = yf.Ticker(symbol).history(start=start.isoformat(), end=end.isoformat(),
                                       auto_adjust=False)
        if df is None or df.empty:
            return None
        # 取 ≤ target_date 的最后一行
        ts_list = [d.date() for d in df.index.tolist()]
        eligible = [i for i, d in enumerate(ts_list) if d <= target_date]
        if not eligible:
            return None
        i = max(eligible)
        close = df.iloc[i].get("Close")
        if close is None:
            return None
        return float(close)
    except Exception:
        return None


# ===========================================================================
# 核心流程：读 jsonl → 回填 → 写 sidecar backfilled jsonl
# ===========================================================================

def _backfilled_path(src_path: str) -> str:
    """x.jsonl → x.backfilled.jsonl（无论目录中是否有点）。"""
    base, ext = os.path.splitext(src_path)
    return f"{base}.backfilled{ext or '.jsonl'}"


def process_jsonl(jsonl_path: str,
                  out_path: Optional[str] = None,
                  dry_run: bool = False,
                  max_recs: Optional[int] = None,
                  verbose: bool = False) -> Optional[str]:
    """处理 shadow JSONL，返回 backfilled 写出路径（dry_run 时返回 None）。

    Args:
        jsonl_path: 源 shadow JSONL 路径
        out_path:   输出路径（默认源路径 + .backfilled 后缀）
        dry_run:    True 时只模拟不写文件
        max_recs:   限制处理条数（用于调试 / 增量抽样）
        verbose:    打印逐行摘要
    """
    if not os.path.isfile(jsonl_path):
        raise FileNotFoundError(jsonl_path)

    if out_path is None:
        out_path = _backfilled_path(jsonl_path)

    # 先全量读入内存（shadow 规模不大，按 6h/coin × 10 币计，每天 ~40 条，1 年仅 1.5w 条）
    records: List[Dict] = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                # 损坏行：保留原样以便审计
                records.append({"_raw_line": line, "_line_no": line_no})

    if max_recs is not None:
        records = records[:max_recs]

    windows = [7, 14, 30]

    for rec in records:
        if "_raw_line" in rec:
            continue
        coin = rec.get("coin", "")
        symbol = _map_coin_to_yf_symbol(coin)
        ts_iso = rec.get("timestamp", "")

        # 1) price_at_signal：无论新旧只要为 null 就填
        if rec.get("price_at_signal") is None and symbol is not None:
            signal_dt = _parse_ts(ts_iso)
            if signal_dt:
                try:
                    rec["price_at_signal"] = _fetch_price_at_date(
                        symbol, signal_dt.date()
                    )
                except Exception:
                    rec["price_at_signal"] = None

        p_at = rec.get("price_at_signal")

        # 2) window prices + return_Nd
        for w in windows:
            p_key = f"price_{w}d_after"
            r_key = f"return_{w}d"
            if rec.get(p_key) is None and symbol is not None and _should_backfill_window(ts_iso, w):
                signal_dt = _parse_ts(ts_iso)
                if signal_dt:
                    target_d = signal_dt.date() + timedelta(days=w)
                    try:
                        rec[p_key] = _fetch_price_at_date(symbol, target_d)
                    except Exception:
                        rec[p_key] = None
            # 对应 return_Nd：只要价格有就填
            p_after = rec.get(p_key)
            if rec.get(r_key) is None and p_after is not None and p_at is not None:
                rec[r_key] = _return_pct(p_at, p_after)

    if dry_run:
        if verbose:
            _print_summary(records)
        return None

    # 原子写：temp → rename
    dirp = os.path.dirname(os.path.abspath(out_path)) or "."
    os.makedirs(dirp, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=dirp, prefix=".bf_", suffix=".jsonl.tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as tf:
            for rec in records:
                if "_raw_line" in rec:
                    tf.write(rec["_raw_line"] + "\n")
                else:
                    tf.write(json.dumps(rec, ensure_ascii=False) + "\n")
        os.replace(tmp_path, out_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    if verbose:
        try:
            _print_summary(records)
        except Exception:
            pass
    return out_path


def _print_summary(records: List[Dict]) -> None:
    n = len(records)
    p_at = sum(1 for r in records if r.get("price_at_signal") is not None and "_raw_line" not in r)
    p7 = sum(1 for r in records if r.get("price_7d_after") is not None)
    r30 = sum(1 for r in records if r.get("return_30d") is not None)
    print(f"[coin_fundamental_backfill] records={n}  price_at_filled={p_at}/{n}  "
          f"price_7d_filled={p7}/{n}  return_30d_filled={r30}/{n}")


# ===========================================================================
# CLI
# ===========================================================================

def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="D1: 回填 CoinFundamental Shadow 历史价格与收益率")
    p.add_argument("--jsonl-path", default=SHADOW_JSONL_PATH,
                   help=f"Shadow JSONL 源路径 (default: {SHADOW_JSONL_PATH})")
    p.add_argument("--out-path", default=None,
                   help="输出 backfilled 路径（默认源路径 .backfilled.jsonl）")
    p.add_argument("--dry-run", action="store_true", help="只模拟不写文件")
    p.add_argument("--max-recs", type=int, default=None, help="限制处理条数")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    try:
        out = process_jsonl(
            jsonl_path=args.jsonl_path,
            out_path=args.out_path,
            dry_run=args.dry_run,
            max_recs=args.max_recs,
            verbose=args.verbose,
        )
    except FileNotFoundError as e:
        print(f"[ERR] jsonl not found: {e}", file=sys.stderr)
        return 2
    if out:
        print(f"[OK] wrote: {out}")
    else:
        print("[OK] dry_run completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
