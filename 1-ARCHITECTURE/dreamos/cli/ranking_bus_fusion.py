"""
ranking_bus_fusion.py — 42 总线 + 子系统信号融合器

读取：
  1. 42 SignalBus 持久化状态（bus_state.json）
  2. ranking_subsystem_scan.py 产出（ranking_subsystem_signals.json）
  3. ranking_decision_card.py 产出（ranking_decision_cards.json，补 SL/TP）
  4. A 组动量分（ranking_asset_pool.json 或 coin_pool.json）

输出：综合榜 + 子系统分榜，带 subsystem 标签 + 方向共识分 + 风险分级。

线上 FAIL-OPEN：任一源缺失/过期时降级，不报错。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _repo_root() -> Path:
    here = Path(__file__).resolve().parent
    for parent in (here, *here.parents):
        if (parent / ".git").exists():
            return parent
    return here.parent.parent


REPO = _repo_root()
SCHED = REPO / "1-ARCHITECTURE" / "dreamos" / "cli" / "scheduler_data"


# ── Source → Subsystem 映射 ─────────────────────────────────────────
SOURCE_TO_SUBSYSTEM = {
    "11-bcrm": "bcrm2",
    "11-bcrm-tactical": "bcrm2",
    "bcrm2": "bcrm2",
    "bdsm": "bdsm",
    "11-bdsm": "bdsm",
    "29-event": "event",
    "event": "event",
    "washout": "evolution",
    "23-washout": "evolution",
    "40-cycle": "cycle",
    "40-divergence": "cycle",
    "40-resonance": "cycle",
    "strategic_extension": "strategic",
    "23-contradiction": "evolution",
    "12-three-screen": "three_screen",
    "17-v4-wave": "v4_wave",
}


def _norm_symbol(sym: str) -> str:
    return (
        str(sym).upper().replace("-USDT", "").replace("-SWAP", "").replace("/", "").replace("-", "")
    )


def _is_usable_symbol(sym: str) -> bool:
    """过滤 MACRO / precious_metal / us_stock 等板块信号。"""
    sym = sym.upper()
    skip = {"MACRO", "CRYPTO_USDT", "PRECIOUS_METAL", "US_STOCK", "CYCLE"}
    if sym in skip:
        return False
    # 只接受字母+数字（真实标的代码）
    return sym.isalnum() and len(sym) <= 12


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except (TypeError, ValueError):
        return None


def _load_json(path: Path, max_age_hours: float = 48.0) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    gen = _parse_iso(data.get("generated_at") or data.get("ts"))
    if (
        gen is not None
        and (datetime.now(timezone.utc) - gen).total_seconds() > max_age_hours * 3600
    ):
        return None
    return data


# ── 读取各信号源 ───────────────────────────────────────────────────
def _load_bus_state() -> List[Dict[str, Any]]:
    path = REPO / "42-神经网络交易协调层" / "runtime" / "bus_state.json"
    data = _load_json(path, max_age_hours=48)
    if not data:
        return []
    out = []
    for sig in data.get("signals", []) or []:
        if not isinstance(sig, dict):
            continue
        src = sig.get("source", "")
        sym = _norm_symbol(sig.get("symbol") or "")
        if not _is_usable_symbol(sym):
            continue
        direction = sig.get("direction", "neutral")
        if direction in ("flat", "neutral"):
            continue
        try:
            conf = max(0.0, min(1.0, float(sig.get("confidence", 0.0) or 0.0)))
        except (TypeError, ValueError):
            conf = 0.0
        if conf < 0.05:
            continue
        out.append(
            {
                "subsystem": SOURCE_TO_SUBSYSTEM.get(src, src),
                "source": src,
                "symbol": sym,
                "direction": direction,
                "confidence": round(conf, 4),
                "score": round(conf, 4),
                "horizon": sig.get("horizon", "days"),
            }
        )
    return out


def _load_subsystem_scan() -> List[Dict[str, Any]]:
    path = SCHED / "ranking_subsystem_signals.json"
    data = _load_json(path, max_age_hours=48)
    if not data:
        return []
    out = []
    seen = set()
    for sig in data.get("signals", []) or []:
        if not isinstance(sig, dict):
            continue
        sym = _norm_symbol(sig.get("symbol") or "")
        if not _is_usable_symbol(sym):
            continue
        direction = sig.get("direction", "neutral")
        if direction in ("flat", "neutral"):
            continue
        conf = max(0.0, min(1.0, float(sig.get("confidence", 0.0) or 0.0)))
        if conf < 0.05:
            continue
        key = (sig.get("subsystem"), sym, direction)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "subsystem": sig.get("subsystem", "unknown"),
                "source": sig.get("source", sig.get("subsystem", "unknown")),
                "symbol": sym,
                "direction": direction,
                "confidence": round(conf, 4),
                "score": round(conf, 4),
                "horizon": sig.get("horizon", "days"),
            }
        )
    return out


def _merge_signals(a: List[Dict], b: List[Dict]) -> List[Dict]:
    seen = set()
    out: List[Dict] = []
    for sig in a + b:
        key = (sig["subsystem"], sig["symbol"], sig["direction"])
        if key in seen:
            continue
        seen.add(key)
        out.append(sig)
    return out


# ── 融合算法 ─────────────────────────────────────────────────────
def _fuse(signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按 symbol 聚合：方向共识 + 置信度均值 + 参与子系统列表。"""
    by_symbol: Dict[str, List[Dict]] = {}
    for s in signals:
        by_symbol.setdefault(s["symbol"], []).append(s)

    fused: List[Dict[str, Any]] = []
    for sym, inst_signals in by_symbol.items():
        # 统计多空
        longs = [s for s in inst_signals if s["direction"] == "long"]
        shorts = [s for s in inst_signals if s["direction"] == "short"]
        n = len(inst_signals)
        if n == 0:
            continue
        if len(longs) >= len(shorts):
            direction = "long"
            group = longs
        else:
            direction = "short"
            group = shorts
        if len(group) == 0:
            continue
        # 共识：方向一致子系统 / 总子系统
        consensus = len(group) / n
        # 置信度均值（方向一致的那些）
        conf_mean = sum(s["confidence"] for s in group) / len(group)
        # 子系统标签列表
        subsystems = sorted({s["subsystem"] for s in inst_signals})
        # 各子系统分榜需要的 Top1~2 按 subsystem 存
        sub_scores = {}
        for s in inst_signals:
            sub = s["subsystem"]
            if sub not in sub_scores or s["confidence"] > sub_scores[sub]["confidence"]:
                sub_scores[sub] = {
                    "direction": s["direction"],
                    "confidence": s["confidence"],
                    "source": s.get("source"),
                }
        fused.append(
            {
                "symbol": sym,
                "direction": direction,
                "consensus": round(consensus, 4),
                "confidence": round(conf_mean, 4),
                "n_signals": n,
                "subsystems": subsystems,
                "sub_scores": sub_scores,
                # 综合分：0.5×共识 + 0.5×置信度（简化版，RR 等 P2 回测后加）
                "fusion_score": round(0.5 * consensus + 0.5 * conf_mean, 4),
            }
        )
    fused.sort(key=lambda x: x["fusion_score"], reverse=True)
    return fused


def _subsystem_top(
    signals: List[Dict[str, Any]], top_n: int = 2
) -> Dict[str, List[Dict[str, Any]]]:
    """按 subsystem 分组取 Top N。"""
    by_sub: Dict[str, List[Dict]] = {}
    for s in signals:
        by_sub.setdefault(s["subsystem"], []).append(s)
    out = {}
    for sub, lst in by_sub.items():
        # 按 confidence 排，同 symbol 只留最高分方向
        dedup: Dict[str, Dict] = {}
        for s in sorted(lst, key=lambda x: x["confidence"], reverse=True):
            if s["symbol"] not in dedup:
                dedup[s["symbol"]] = s
        out[sub] = list(dedup.values())[:top_n]
    return out


# ── 主入口 ───────────────────────────────────────────────────────
def build_rankings() -> Dict[str, Any]:
    bus_sigs = _load_bus_state()
    scan_sigs = _load_subsystem_scan()
    merged = _merge_signals(bus_sigs, scan_sigs)

    fused = _fuse(merged)
    by_sub = _subsystem_top(merged, top_n=2)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_signals": len(merged),
        "source_breakdown": {
            "bus_state": len(bus_sigs),
            "subsystem_scan": len(scan_sigs),
        },
        "combined": fused,
        "by_subsystem": by_sub,
    }


if __name__ == "__main__":

    result = build_rankings()
    print(json.dumps(result, ensure_ascii=False, indent=2)[:3000])
