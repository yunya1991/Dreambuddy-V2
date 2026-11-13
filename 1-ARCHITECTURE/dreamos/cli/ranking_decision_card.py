"""
ranking_decision_card.py — P0 决策卡维度预计算

对榜单候选标的（加密 + OKX 合成品种）计算：
  入场区间（ATR ±0.5）、止损止盈（BCRM2 风险参数 + ATR）、
  风险分级（BCRM2 triangle_verification）、历史类比（CBR）。

每日 cron 运行一次，输出 scheduler_data/ranking_decision_cards.json；
trading_ranking.py 在构建决策卡时读取并合并，文件缺失/过期时 FAIL-OPEN
降级为现有硬编码空值。

用法:
  python3 ranking_decision_card.py                  # 从 coin_pool + ranking_asset_pool 自动收集
  python3 ranking_decision_card.py BTC HYPE AMD      # 指定标的
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


# ── 路径与依赖 ──────────────────────────────────────────────────────
def _repo_root() -> Path:
    here = Path(__file__).resolve().parent
    for parent in (here, *here.parents):
        if (parent / ".git").exists():
            return parent
    return here.parent.parent


REPO = _repo_root()
SCHED = REPO / "1-ARCHITECTURE" / "dreamos" / "cli" / "scheduler_data"
OUT = SCHED / "ranking_decision_cards.json"
SCHED.mkdir(parents=True, exist_ok=True)

# 子系统路径注入
for sub in ["11-易经推理系统"]:
    p = REPO / sub
    if p.is_dir() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

# 复用 ranking_asset_pool 的 OkxFeed
asset_pool_dir = REPO / "1-ARCHITECTURE" / "dreamos" / "cli"
if str(asset_pool_dir) not in sys.path:
    sys.path.insert(0, str(asset_pool_dir))


# ── OKX symbol → inst_id ─────────────────────────────────────────────
def _to_inst_id(symbol: str) -> str:
    s = symbol.upper().replace("-", "").replace("/", "")
    # 合成品种（大宗/指数）也走 USDT 永续
    return f"{s}-USDT-SWAP"


# ── ATR ──────────────────────────────────────────────────────────────
def _atr(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    if df is None or len(df) < period + 1 or not {"high", "low", "close"}.issubset(df.columns):
        return None
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    prev_c = np.roll(closes, 1)
    tr = np.maximum(highs - lows, np.maximum(np.abs(highs - prev_c), np.abs(lows - prev_c)))
    return float(np.mean(tr[-period:]))


# ── 从多个池收集候选 ────────────────────────────────────────────────
def _collect_symbols() -> List[str]:
    symbols: List[str] = []
    seen = set()

    # 1. coin_pool.json
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

    # 2. ranking_asset_pool.json
    p = SCHED / "ranking_asset_pool.json"
    if p.is_file():
        try:
            data = json.loads(p.read_text())
            for entry in data.get("items", []) or data.get("symbols", []) or []:
                if isinstance(entry, dict):
                    s = entry.get("symbol", "")
                else:
                    s = str(entry)
                if s and s not in seen:
                    seen.add(s)
                    symbols.append(s)
        except Exception:
            pass

    return symbols


# ── BCRM2 推理（FAIL-OPEN） ──────────────────────────────────────────
def _infer_bcrm2(df: pd.DataFrame, symbol: str) -> Dict[str, Any]:
    """返回 {direction, confidence, risk_level, risk_score, position_factor,
    sl_tighten_factor, tp_adjustment, derived_sl, derived_tp, warn}
    或空 dict 表示推理失败。"""
    out: Dict[str, Any] = {}
    try:
        from scripts.memory_l4.bcrm2_adapter import BCRM2Adapter  # noqa: WPS433

        adapter = BCRM2Adapter(symbol=symbol, timeframe="1D")
        result = adapter.infer(df, auto_train=True)
        if not result.get("ok"):
            return out

        ns = result.get("next_state") or {}
        direction_raw = ns.get("direction", "FLAT")
        # BCRM2 用 UP/DOWN/FLAT，映射为 long/short/neutral
        dir_map = {"UP": "long", "DOWN": "short", "FLAT": "neutral"}
        out["direction"] = dir_map.get(direction_raw, "neutral")
        out["confidence"] = float(ns.get("confidence", 0.0) or 0.0)

        # 风险参数
        out["risk_level"] = result.get("risk_level", "NORMAL")
        out["risk_score"] = float(result.get("risk_score", 0.0) or 0.0)
        out["position_factor"] = float(result.get("position_factor", 1.0) or 1.0)
        out["sl_tighten_factor"] = float(result.get("sl_tighten_factor", 1.0) or 1.0)
        out["tp_adjustment"] = float(result.get("tp_adjustment", 1.0) or 1.0)

        # 告警
        warns = result.get("a0_warnings") or []
        tv = result.get("triangle_verification") or {}
        if isinstance(tv, dict) and tv.get("risk_warnings"):
            warns.extend(
                tv["risk_warnings"]
                if isinstance(tv["risk_warnings"], list)
                else [tv["risk_warnings"]]
            )
        out["warnings"] = warns[:3]

    except Exception as exc:
        out["warnings"] = [f"bcrm2_infer_failed: {exc}"]

    return out


# ── CBR 历史类比（FAIL-OPEN） ────────────────────────────────────────
def _cbr_analogy(symbol: str, bcrm2: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not bcrm2 or bcrm2.get("direction") == "neutral":
        return out
    try:
        from scripts.memory_l4.cbr_adapter import BCRMSignal, CBRSignalEnhancer  # noqa: WPS433

        signal = BCRMSignal(
            inst_id=f"{symbol}-USDT-SWAP",
            direction=bcrm2["direction"],
            confidence=bcrm2.get("confidence", 0.5),
            volatility=0.0,
        )
        enhancer = CBRSignalEnhancer()
        enhancer.load()
        enhanced = enhancer.enhance(signal)

        if enhanced.cbr_similarity_top1 > 0.3:
            parts = []
            if enhanced.cbr_historical_win_rate:
                parts.append(f"历史胜率 {enhanced.cbr_historical_win_rate:.0%}")
            if enhanced.cbr_avg_pnl:
                parts.append(f"平均盈亏 {enhanced.cbr_avg_pnl:+.2f}%")
            parts.append(f"相似度 {enhanced.cbr_similarity_top1:.1%}")
            if enhanced.cbr_risk_notes:
                parts.append(f"风险：{'; '.join(enhanced.cbr_risk_notes[:2])}")
            out["historicalAnalogy"] = " | ".join(parts)

    except Exception as exc:
        # CBR 缺失或 shard 不存在时静默降级，不报错
        out["_cbr_err"] = str(exc)
    return out


# ── 资产类别 → risk level 映射 ───────────────────────────────────────
def _bcrm2_risk_to_display(risk_level: str) -> str:
    """BCRM2 risk_level (NORMAL/ELEVATED/HIGH/EXTREME) → expert/intermediate/beginner。"""
    mapping = {
        "NORMAL": "beginner",
        "ELEVATED": "intermediate",
        "HIGH": "expert",
        "EXTREME": "expert",
    }
    return mapping.get(risk_level.upper() if risk_level else "", "intermediate")


# ── 主流程 ──────────────────────────────────────────────────────────
def build_decision_cards(symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    from ranking_asset_pool import OkxFeed  # noqa: WPS433

    if symbols is None:
        symbols = _collect_symbols()

    feed = OkxFeed()
    results: Dict[str, Any] = {}
    built_at = datetime.now(timezone.utc).isoformat()
    t0 = time.time()

    print(f"[ranking_decision_card] 目标 {len(symbols)} 个标的，开始时间 {built_at}")

    for i, symbol in enumerate(symbols):
        inst_id = _to_inst_id(symbol)
        print(f"  [{i+1}/{len(symbols)}] {symbol} ({inst_id}) ... ", end="", flush=True)

        card: Dict[str, Any] = {
            "entry": {"price": None, "range": [None, None], "batches": []},
            "stopLoss": None,
            "takeProfit": [],
            "riskLevel": "intermediate",
            "historicalAnalogy": "",
            "inferred": False,
        }

        # 1. 拉 K 线
        try:
            raw = feed.candles(inst_id)
        except Exception:
            raw = []

        if not raw or len(raw) < 30:
            print("no_candles")
            card["warnings"] = ["kline_not_available"]
            results[symbol] = card
            continue

        # OKX candles: [ts, o, h, l, c, vol, ...]
        try:
            df = pd.DataFrame(
                raw,
                columns=["ts", "open", "high", "low", "close", "volume"]
                + [f"x{i}" for i in range(len(raw[0]) - 6)],
            )
            for col in ("open", "high", "low", "close", "volume"):
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna(subset=["close"])
            df = df.sort_values("ts").reset_index(drop=True)
        except Exception as exc:
            print(f"df_err:{exc}")
            card["warnings"] = [f"parse_kline_failed: {exc}"]
            results[symbol] = card
            continue

        price = float(df["close"].iloc[-1])

        # 2. ATR
        atr = _atr(df, 14)

        # 3. BCRM2 推理
        bcrm2 = _infer_bcrm2(df, symbol)

        # 4. CBR 历史类比
        cbr = _cbr_analogy(symbol, bcrm2)

        # 5. 组装决策卡
        direction = bcrm2.get("direction", "neutral")
        risk_level_raw = bcrm2.get("risk_level", "NORMAL")
        card["riskLevel"] = _bcrm2_risk_to_display(risk_level_raw)
        card["positionFactor"] = bcrm2.get("position_factor", 1.0)

        # 入场区间（±0.5 ATR）
        if atr and atr > 0 and price > 0:
            half_atr = atr * 0.5
            card["entry"] = {
                "price": round(price, 4),
                "range": [round(price - half_atr, 4), round(price + half_atr, 4)],
                "batches": [],
            }
            # 止损止盈
            sl_atr = bcrm2.get("sl_tighten_factor", 1.0) * 2.0  # 默认 2 ATR
            tp_atr = bcrm2.get("tp_adjustment", 1.0) * 3.0  # 默认 3 ATR
            if direction == "long":
                card["stopLoss"] = round(price - atr * sl_atr, 4)
                card["takeProfit"] = [
                    {"price": round(price + atr * tp_atr * 0.6, 4), "pct": 0.5},
                    {"price": round(price + atr * tp_atr, 4), "pct": 0.5},
                ]
            elif direction == "short":
                card["stopLoss"] = round(price + atr * sl_atr, 4)
                card["takeProfit"] = [
                    {"price": round(price - atr * tp_atr * 0.6, 4), "pct": 0.5},
                    {"price": round(price - atr * tp_atr, 4), "pct": 0.5},
                ]

        # 风险标签与方向
        if bcrm2:
            card["inferred"] = True
            card["direction"] = direction
            card["confidence"] = round(bcrm2.get("confidence", 0.0), 3)
            card["warnings"] = bcrm2.get("warnings", [])[:2]

        # 历史类比
        if cbr.get("historicalAnalogy"):
            card["historicalAnalogy"] = cbr["historicalAnalogy"]

        print(f"ok price={price} risk={card['riskLevel']} inferred={card['inferred']}")
        results[symbol] = card

    elapsed = time.time() - t0
    inferred_count = sum(1 for c in results.values() if c.get("inferred"))
    print(
        f"[ranking_decision_card] 完成 {len(results)} 标的，其中 inferred={inferred_count}，耗时 {elapsed:.1f}s"
    )

    return {
        "generated_at": built_at,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "source": "ranking_decision_card.py",
        "items": results,
    }


def main(argv: Optional[List[str]] = None) -> int:
    argv = argv or sys.argv[1:]
    payload = build_decision_cards(argv or None)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"→ 写入 {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
