"""
ranking_subsystem_scan.py — 每日多子系统扫描

对榜单候选标的运行 6 个子系统信号计算：
  bcrm2 / bdsm / event / three_screen / v4_wave / evolution(washout)

输出 scheduler_data/ranking_subsystem_signals.json（统一格式，每条含 subsystem/symbol/direction/confidence/...）。
42 层 publisher（three_screen_state_adapter / v4_wave_state_adapter）读取此文件发布到总线；
榜单侧融合器也直接读取此文件。

用法:
  python3 ranking_subsystem_scan.py                  # 从 coin_pool + ranking_asset_pool 自动收集
  python3 ranking_subsystem_scan.py BTC HYPE AMD      # 指定标的
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


# ── 路径注入 ──────────────────────────────────────────────────────
def _repo_root() -> Path:
    here = Path(__file__).resolve().parent
    for parent in (here, *here.parents):
        if (parent / ".git").exists():
            return parent
    return here.parent.parent


REPO = _repo_root()
SCHED = REPO / "1-ARCHITECTURE" / "dreamos" / "cli" / "scheduler_data"
OUT = SCHED / "ranking_subsystem_signals.json"
SCHED.mkdir(parents=True, exist_ok=True)

# 子系统路径注入
for sub in [
    "11-易经推理系统",
    "12-三屏趋势系统",
    "17-v4-wave-strategy",
    "23-四层闭环自进化交易架构",
    "29-事件驱动策略系统",
    "40-周期神经网络系统",
    "42-神经网络交易协调层",
]:
    p = REPO / sub
    if p.is_dir() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

asset_pool_dir = REPO / "1-ARCHITECTURE" / "dreamos" / "cli"
if str(asset_pool_dir) not in sys.path:
    sys.path.insert(0, str(asset_pool_dir))


# ── 候选收集 ───────────────────────────────────────────────────────
def _collect_symbols() -> List[str]:
    symbols: List[str] = []
    seen = set()
    for fname in ("coin_pool.json",):
        p = SCHED / fname
        if p.is_file():
            try:
                data = json.loads(p.read_text())
                for key in ("long_pool", "short_pool"):
                    for entry in data.get(key, []) or []:
                        s = entry.get("symbol", "")
                        if s and s not in seen:
                            seen.add(s)
                            symbols.append(s)
            except Exception:
                pass
    p = SCHED / "ranking_asset_pool.json"
    if p.is_file():
        try:
            data = json.loads(p.read_text())
            for entry in data.get("items", []) or data.get("symbols", []) or []:
                s = entry.get("symbol", "") if isinstance(entry, dict) else str(entry)
                if s and s not in seen:
                    seen.add(s)
                    symbols.append(s)
        except Exception:
            pass
    return symbols


def _to_inst_id(symbol: str) -> str:
    s = symbol.upper().replace("-", "").replace("/", "")
    return f"{s}-USDT-SWAP"


# ── K 线拉取 + resample ────────────────────────────────────────────
def _fetch_daily_and_weekly(symbol: str) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    from ranking_asset_pool import OkxFeed  # noqa: WPS433

    inst_id = _to_inst_id(symbol)
    feed = OkxFeed()
    try:
        raw = feed.candles(inst_id)
    except Exception:
        raw = []
    if not raw or len(raw) < 30:
        return None, None

    # daily
    try:
        df = pd.DataFrame(
            raw,
            columns=["ts", "open", "high", "low", "close", "volume"]
            + [f"x{i}" for i in range(len(raw[0]) - 6)],
        )
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["ts"] = pd.to_datetime(df["ts"].astype(float), unit="ms", utc=True)
        df = df.dropna(subset=["close"]).sort_values("ts").reset_index(drop=True)
        df = df.set_index("ts")
    except Exception:
        return None, None

    # weekly resample
    try:
        df_w = (
            df.resample("W")
            .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
            .dropna(subset=["close"])
        )
    except Exception:
        df_w = None

    return df, df_w


# ── 各子系统扫描器 ────────────────────────────────────────────────
def _scan_bcrm2(df: pd.DataFrame, symbol: str) -> Optional[Dict[str, Any]]:
    try:
        from scripts.memory_l4.bcrm2_adapter import BCRM2Adapter  # noqa: WPS433

        adapter = BCRM2Adapter(symbol=symbol, timeframe="1D")
        result = adapter.infer(df, auto_train=True)
        if not result.get("ok"):
            return None
        ns = result.get("next_state") or {}
        dir_map = {"UP": "long", "DOWN": "short", "FLAT": "neutral"}
        direction = dir_map.get(str(ns.get("direction", "FLAT")), "neutral")
        confidence = float(ns.get("confidence", 0.0) or 0.0)
        if direction == "neutral" or confidence < 0.05:
            return None
        return {
            "subsystem": "bcrm2",
            "source": "11-bcrm",
            "symbol": symbol,
            "direction": direction,
            "confidence": round(confidence, 4),
            "score": round(confidence, 4),
            "horizon": "days",
            "risk_level": result.get("risk_level", "NORMAL"),
        }
    except Exception:
        return None


def _scan_three_screen(
    df_daily: pd.DataFrame, df_weekly: Optional[pd.DataFrame], symbol: str
) -> Optional[Dict[str, Any]]:
    if df_daily is None or df_weekly is None or len(df_daily) < 60:
        return None
    try:
        from engine import compute_trend_signal_from_dataframes  # noqa: WPS433

        result = compute_trend_signal_from_dataframes(
            weekly_df=df_weekly,
            daily_df=df_daily,
            symbol=symbol,
        )
        if not isinstance(result, dict):
            return None
        # three_screen 输出 final_signal dict，含 action/confidence
        fs = result.get("final_signal") or {}
        if isinstance(fs, dict):
            action = str(fs.get("action") or "").upper()
            confidence = float(fs.get("confidence") or 0.0)
        else:
            action = str(result.get("action") or result.get("signal") or "").upper()
            confidence = float(
                result.get("bayesian_confidence")
                or result.get("overall_confidence")
                or result.get("confidence")
                or 0.0
            )
        dir_map = {"BUY": "long", "SELL": "short", "LONG": "long", "SHORT": "short"}
        direction = dir_map.get(action, "neutral")
        if direction == "neutral":
            return None
        # confidence 在 three_screen 里常是百分比 0-100
        conf_norm = (
            round(min(1.0, confidence / 100.0), 4) if confidence > 1 else round(confidence, 4)
        )
        if conf_norm < 0.05:
            return None
        return {
            "subsystem": "three_screen",
            "source": "12-three-screen",
            "symbol": symbol,
            "direction": direction,
            "confidence": conf_norm,
            "score": conf_norm,
            "horizon": "days",
        }
    except Exception:
        return None


def _scan_v4_wave(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        # 先清掉 12-三屏趋势 的 data 包缓存（避免与 17-v4-wave 的 data 冲突）
        sys.modules.pop("data.market_data", None)
        from v4_wave_engine import compute_v4_wave_signal  # noqa: WPS433

        result = compute_v4_wave_signal(spot_inst=f"{symbol}-USDT", is_btc=(symbol == "BTC"))
        if not isinstance(result, dict) or result.get("error"):
            return None
        action = str(result.get("action") or result.get("signal") or "").upper()
        dir_map = {"BUY": "long", "SELL": "short", "LONG": "long", "SHORT": "short"}
        direction = dir_map.get(action, "neutral")
        confidence = float(result.get("confidence") or result.get("overall_confidence") or 0.0)
        if direction == "neutral":
            return None
        conf_norm = (
            round(min(1.0, confidence / 100.0), 4) if confidence > 1 else round(confidence, 4)
        )
        if conf_norm < 0.05:
            return None
        return {
            "subsystem": "v4_wave",
            "source": "17-v4-wave",
            "symbol": symbol,
            "direction": direction,
            "confidence": conf_norm,
            "score": conf_norm,
            "horizon": "days",
        }
    except Exception:
        return None


def _scan_from_42_bus(symbol: str, bus_state_path: Path) -> List[Dict[str, Any]]:
    """从已有的 42 总线状态提取 bdsm / event / washout / cycle 等信号。"""
    if not bus_state_path.is_file():
        return []
    try:
        data = json.loads(bus_state_path.read_text())
    except Exception:
        return []
    signals = []
    for sig in data.get("signals", []) or []:
        if not isinstance(sig, dict):
            continue
        src = sig.get("source", "")
        sym = str(sig.get("symbol") or "")
        # 归一化 symbol: BTC/USDT → BTC, 大写匹配
        sym_norm = sym.upper().replace("-USDT", "").replace("-SWAP", "").replace("/", "")
        if sym_norm != symbol.upper():
            continue
        direction = sig.get("direction", "neutral")
        if direction in ("flat", "neutral", ""):
            continue
        # source → subsystem
        sub_map = {
            "bdsm": "bdsm",
            "11-bdsm": "bdsm",
            "11-bcrm-tactical": "bcrm2",
            "washout": "evolution",
            "29-event": "event",
            "40-cycle": "cycle",
            "40-divergence": "cycle",
        }
        subsystem = sub_map.get(src, src)
        try:
            conf = max(0.0, min(1.0, float(sig.get("confidence", 0.0) or 0.0)))
        except (TypeError, ValueError):
            conf = 0.0
        if conf < 0.05:
            continue
        signals.append(
            {
                "subsystem": subsystem,
                "source": src,
                "symbol": symbol,
                "direction": direction,
                "confidence": round(conf, 4),
                "score": round(conf, 4),
                "horizon": sig.get("horizon", "days"),
            }
        )
    return signals


# ── 主流程 ────────────────────────────────────────────────────────
def run(symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    if symbols is None:
        symbols = _collect_symbols()

    bus_state_path = REPO / "42-神经网络交易协调层" / "runtime" / "bus_state.json"

    all_signals: List[Dict[str, Any]] = []
    seen_keys = set()
    now = datetime.now(timezone.utc)

    print(f"[ranking_subsystem_scan] 目标 {len(symbols)} 标的，开始 {now.isoformat()}")
    t0 = time.time()

    for i, symbol in enumerate(symbols):
        print(f"  [{i+1}/{len(symbols)}] {symbol} ... ", end="", flush=True)
        inst_signals: List[Dict[str, Any]] = []

        # 1. 先从 42 总线拉已有信号（bdsm / event / washout / 40-cycle）
        inst_signals.extend(_scan_from_42_bus(symbol, bus_state_path))

        # 2. BCRM2
        df_d, df_w = _fetch_daily_and_weekly(symbol)
        if df_d is not None:
            sig = _scan_bcrm2(df_d, symbol)
            if sig:
                inst_signals.append(sig)

            # 3. 三屏趋势
            sig = _scan_three_screen(df_d, df_w, symbol)
            if sig:
                inst_signals.append(sig)

        # 4. V4 波浪（自带数据获取）
        sig = _scan_v4_wave(symbol)
        if sig:
            inst_signals.append(sig)

        # 去重：同 (subsystem, symbol) 只保留最高分的
        deduped = {}
        for s in inst_signals:
            key = (s["subsystem"], s["symbol"])
            if key not in deduped or s["confidence"] > deduped[key]["confidence"]:
                deduped[key] = s
        for s in deduped.values():
            # 幂等 key
            k = (s["subsystem"], s["symbol"], s["direction"])
            if k in seen_keys:
                continue
            seen_keys.add(k)
            s["ts"] = now.isoformat()
            s["expires_at"] = (now + timedelta(days=1)).isoformat()
            all_signals.append(s)

        print(f"{len(deduped)} sigs")

    elapsed = time.time() - t0

    # 按 subsystem 统计
    from collections import Counter

    sub_counts = Counter(s["subsystem"] for s in all_signals)
    print(
        f"[ranking_subsystem_scan] 完成，共 {len(all_signals)} 信号，耗时 {elapsed:.1f}s "
        f"by_subsystem={dict(sub_counts)}"
    )

    return {
        "generated_at": now.isoformat(),
        "expires_at": (now + timedelta(days=1)).isoformat(),
        "source": "ranking_subsystem_scan.py",
        "signals": all_signals,
    }


def main(argv: Optional[List[str]] = None) -> int:
    argv = argv or sys.argv[1:]
    payload = run(argv or None)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"→ 写入 {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
