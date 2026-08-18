#!/usr/bin/env python3
"""
三屏交易研报加载器
- 周报：每周一更新，Screen1 战略参考
- A1日报：每日更新，Screen2 战术参考
- A6情报：每4h更新，Screen3 执行参考
"""
import json, re, os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

BASE_DIR = Path(__file__).parent
REPORT_DIR = BASE_DIR / "A系列研报"
WEEKLY_DIR = REPORT_DIR / "周报"
A1_DIR = REPORT_DIR / "A1研报"
A6_DIR = REPORT_DIR / "A6研报"

CACHE_TTL = {
    "weekly": 3600,
    "a1_daily": 1800,
    "a6_intel": 900,
}

_cache: Dict[str, dict] = {}


def _parse_front_matter(text: str) -> Dict[str, Any]:
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    fm = {}
    for line in parts[1].strip().split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm


def _find_latest(directory: Path, pattern: str) -> Optional[Path]:
    if not directory.exists():
        return None
    files = sorted(directory.glob(pattern))
    return files[-1] if files else None


def _is_fresh(key: str, ttl: int) -> bool:
    if key not in _cache:
        return False
    fetched = _cache[key].get("_fetched_at")
    if isinstance(fetched, str):
        fetched = datetime.fromisoformat(fetched)
    if not isinstance(fetched, datetime):
        return False
    age = (datetime.now(timezone.utc) - fetched).total_seconds()
    return age < ttl


def load_weekly() -> Optional[Dict]:
    """加载最新周报（Screen1战略参考）"""
    if _is_fresh("weekly", CACHE_TTL["weekly"]):
        return _cache["weekly"]

    f = _find_latest(WEEKLY_DIR, "screen1_*.md")
    if not f:
        return None

    try:
        text = f.read_text(encoding="utf-8")
        fm = _parse_front_matter(text)

        direction = None
        score = None
        strategy = None
        summary = ""

        m = re.search(r"\*\*方向\*\*[：:]\s*([^\n]+)", text)
        if m:
            direction = m.group(1).strip()

        m = re.search(r"周线评分[：:]\s*(\d+)\s*/\s*100", text)
        if m:
            score = int(m.group(1))

        m = re.search(r"\*\*策略\*\*[：:]\s*([^\n]+)", text)
        if m:
            strategy = m.group(1).strip()

        m = re.search(r"##\s*执行摘要\s*\n\s*\n(.+?)\n---", text, re.DOTALL)
        if m:
            summary = m.group(1).strip()
            summary = re.sub(r"\*\*[^*]+\*\*", "", summary).strip()
            summary = summary[:300] + "..." if len(summary) > 300 else summary

        data = {
            "title": fm.get("title", f.name),
            "date": fm.get("date", ""),
            "valid_until": fm.get("valid_until", ""),
            "source": fm.get("source", ""),
            "version": fm.get("version", ""),
            "direction": direction,
            "score": score,
            "strategy": strategy,
            "summary": summary,
            "file": str(f),
            "raw_excerpt": text[:500],
        }
        _cache["weekly"] = {**data, "_fetched_at": datetime.now(timezone.utc).isoformat()}
        return data
    except Exception as e:
        return {"error": str(e), "file": str(f)}


def load_a1_daily() -> Optional[Dict]:
    """加载最新A1日报（Screen2战术参考）"""
    if _is_fresh("a1_daily", CACHE_TTL["a1_daily"]):
        return _cache["a1_daily"]

    f = _find_latest(A1_DIR, "a1_regime_*.json")
    if not f:
        return None

    try:
        with open(f, encoding="utf-8") as fp:
            raw = json.load(fp)

        # 兼容两种格式：
        #   新格式（实际）: 顶层 regime/confidence/si_index(int)/three_screen 等
        #   旧格式（历史）: market_regime 嵌套字典
        if "market_regime" in raw and isinstance(raw["market_regime"], dict):
            # 旧格式
            mr = raw.get("market_regime", {})
            triple_raw = mr.get("triple_screen", {})
            regime = mr.get("regime", "")
            confidence = mr.get("confidence", 0)
            si_raw = raw.get("si_index", {})
            si_score = si_raw.get("score", 0) if isinstance(si_raw, dict) else int(si_raw or 0)
            pc = raw.get("primary_contradiction", {})
            pc_dict = {
                "id": pc.get("id", "") if isinstance(pc, dict) else "",
                "description": pc.get("description", "") if isinstance(pc, dict) else str(pc),
                "dominant_side": pc.get("dominant_side", "") if isinstance(pc, dict) else "",
                "direction_implication": pc.get("direction_implication", "") if isinstance(pc, dict) else "",
            }
            triple = {
                "week": triple_raw.get("S1_week", triple_raw.get("weekly", {})),
                "day": triple_raw.get("S2_day", triple_raw.get("daily", {})),
                "hour": triple_raw.get("S3_hour", triple_raw.get("hourly", {})),
            }
        else:
            # 新格式（2026-07 以后实际格式）
            three = raw.get("three_screen", {})
            triple = {
                "week":  {"score": three.get("weekly", 0)},
                "day":   {"score": three.get("daily", 0)},
                "hour":  {"score": three.get("hourly", 0)},
                "composite": three.get("composite", 0),
            }
            regime = raw.get("regime", "")
            confidence = raw.get("confidence", 0)
            si_score = int(raw.get("si_index", 0) or 0)
            # 提取主要矛盾
            dominant_id = raw.get("dominant_contradiction", "")
            contradictions = raw.get("contradictions", [])
            pc_item = next((c for c in contradictions if c.get("id") == dominant_id), {})
            pc_dict = {
                "id":                  dominant_id,
                "description":         pc_item.get("name", ""),
                "dominant_side":       pc_item.get("bias", ""),
                "direction_implication": pc_item.get("change", ""),
            }

        data = {
            "date":              raw.get("date", ""),
            "regime":            regime,
            "confidence":        confidence,
            "level":             raw.get("level", 0),
            "triple_screen":     triple,
            "si_index": {
                "score":           si_score,
                "components":      raw.get("si_index_components", {}),
            },
            "key_levels":        raw.get("key_levels", {}),
            "primary_contradiction": pc_dict,
            "contradictions":    raw.get("contradictions", []),
            # 价格快照
            "btc_price":         raw.get("btc_price", 0),
            "eth_price":         raw.get("eth_price", 0),
            "sol_price":         raw.get("sol_price", 0),
            "fgi":               raw.get("fgi", 0),
            "funding_rate_btc":  raw.get("funding_rate_btc", 0),
            "etf_1d_usd":        raw.get("etf_1d_usd", 0),
            "file":              str(f),
        }
        _cache["a1_daily"] = {**data, "_fetched_at": datetime.now(timezone.utc).isoformat()}
        return data
    except Exception as e:
        return {"error": str(e), "file": str(f)}


def load_a6_intel() -> Optional[Dict]:
    """加载最新A6情报（Screen3执行参考）"""
    if _is_fresh("a6_intel", CACHE_TTL["a6_intel"]):
        return _cache["a6_intel"]

    f = _find_latest(A6_DIR, "a6_intelligence_brief_*.md")
    if not f:
        return None

    try:
        text = f.read_text(encoding="utf-8")
        fm = _parse_front_matter(text)

        regime = ""
        confidence = 0
        direction = ""
        si_score = 0
        p0_alerts = 0
        p1_alerts = 0
        p2_alerts = 0
        recommendation = ""

        m = re.search(r"\*\*Regime\*\*[：:]\s*([^\(]+)", text)
        if m:
            regime = m.group(1).strip()

        m = re.search(r"置信度\*\*[：:]\s*(\d+)%", text)
        if m:
            confidence = int(m.group(1))

        m = re.search(r"SI_Index\s*=\s*([+-]?\d+)", text)
        if m:
            si_score = int(m.group(1))

        m = re.search(r"###?\s*P0告警.*?\n\s*✅?\s*无P0级告警|P0告警.*?\(🔴\s*(\d+)\s*条\)", text)
        if m and m.group(1):
            p0_alerts = int(m.group(1))

        m = re.search(r"###?\s*P1告警.*?\(⚠️\s*(\d+)\s*条\)", text)
        if m:
            p1_alerts = int(m.group(1))

        m = re.search(r"###?\s*P2告警.*?\(ℹ️\s*(\d+)\s*条\)", text)
        if m:
            p2_alerts = int(m.group(1))

        m = re.search(r"\*\*(维持空仓观望|操作建议)[^\n]*\*\*\s*—\s*([^\n]+)", text)
        if m:
            recommendation = m.group(2).strip()
        else:
            m = re.search(r"操作建议[：:]\s*\*\*([^*]+)\*\*", text)
            if m:
                recommendation = m.group(1).strip()

        m = re.search(r"NEUTRAL偏(BULL|BEAR)", text)
        if m:
            direction = "NEUTRAL_" + m.group(1)

        data = {
            "title": fm.get("title", f.name),
            "date": fm.get("date", ""),
            "round": "",
            "regime": regime,
            "confidence": confidence,
            "direction": direction,
            "si_score": si_score,
            "p0_alerts": p0_alerts,
            "p1_alerts": p1_alerts,
            "p2_alerts": p2_alerts,
            "recommendation": recommendation,
            "file": str(f),
        }

        m = re.search(r"第(\d+)轮", text)
        if m:
            data["round"] = m.group(1)

        _cache["a6_intel"] = {**data, "_fetched_at": datetime.now(timezone.utc).isoformat()}
        return data
    except Exception as e:
        return {"error": str(e), "file": str(f)}


def get_all_reports() -> Dict:
    """一次性获取所有研报摘要"""
    return {
        "weekly": load_weekly(),
        "a1_daily": load_a1_daily(),
        "a6_intel": load_a6_intel(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    reports = get_all_reports()
    print(json.dumps(reports, indent=2, ensure_ascii=False))
