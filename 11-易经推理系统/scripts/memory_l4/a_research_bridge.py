#!/usr/bin/env python3
"""
A 系列研报数据接入 - 将 A1/A6/周报研报发布到 shared_memory_bus
作为易经大模型推理的深度数据源

A1: 每日研报（regime 研判）
A6: 每4小时情报监控
周报: 每周总结
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORTS_DIR = Path(
    "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/A系列研报"
)

A1_DIR = REPORTS_DIR / "A1研报"
A6_DIR = REPORTS_DIR / "A6研报"
WEEKLY_DIR = REPORTS_DIR / "周报"


def _read_json_safe(path: Path) -> Optional[Dict]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_md_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _extract_date_from_filename(name: str) -> str:
    m = re.search(r'(\d{8})', name)
    if m:
        d = m.group(1)
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return ""


def list_a1_reports(limit: int = 10) -> List[Dict]:
    """列出 A1 研报列表"""
    if not A1_DIR.exists():
        return []
    files = sorted(A1_DIR.glob("a1_regime_*.json"), reverse=True)
    return [
        {
            "file": f.name,
            "date": _extract_date_from_filename(f.name),
            "size": f.stat().st_size,
            "path": str(f),
        }
        for f in files[:limit]
    ]


def list_a6_reports(limit: int = 10) -> List[Dict]:
    """列出 A6 研报列表"""
    if not A6_DIR.exists():
        return []
    files = sorted(A6_DIR.glob("a6_intelligence_brief_*.md"), reverse=True)
    return [
        {
            "file": f.name,
            "date": _extract_date_from_filename(f.name),
            "size": f.stat().st_size,
            "path": str(f),
        }
        for f in files[:limit]
    ]


def list_weekly_reports(limit: int = 10) -> List[Dict]:
    """列出周报列表"""
    if not WEEKLY_DIR.exists():
        return []
    files = sorted(WEEKLY_DIR.glob("*.md"), reverse=True)
    return [
        {
            "file": f.name,
            "date": _extract_date_from_filename(f.name),
            "size": f.stat().st_size,
            "path": str(f),
        }
        for f in files[:limit]
    ]


def parse_a1_report(file_path: Path) -> Dict:
    """解析 A1 研报 JSON"""
    data = _read_json_safe(file_path)
    if not data:
        return {"ok": False, "error": "failed to read a1 report"}

    regime = data.get("market_regime", {})
    si = data.get("si_index", {})
    primary = data.get("primary_contradiction", {})

    return {
        "ok": True,
        "type": "a1",
        "file": file_path.name,
        "date": _extract_date_from_filename(file_path.name),
        "regime": regime.get("regime", ""),
        "regime_confidence": regime.get("confidence", 0),
        "technical_regime": regime.get("technical_regime", ""),
        "fundamental_regime": regime.get("fundamental_regime", ""),
        "composite_score": regime.get("composite_score", 0),
        "triple_screen": regime.get("triple_screen", {}),
        "si_score": si.get("score", 0),
        "si_range": si.get("range", ""),
        "si_confidence": si.get("confidence", 0),
        "position_mapping": si.get("position_mapping", ""),
        "primary_contradiction": {
            "id": primary.get("id", ""),
            "description": primary.get("description", ""),
            "dominant_side": primary.get("dominant_side", ""),
            "direction": primary.get("direction_implication", ""),
            "confidence": primary.get("confidence", 0),
        },
        "total_contradictions": data.get("total_contradictions", 0),
        "contradiction_intensity": data.get("contradiction_intensity", ""),
        "signal_sufficiency": data.get("signal_sufficiency", {}),
        "action_pressure": data.get("action_pressure", {}),
        "key_levels": data.get("key_levels", {}),
        "macro_assets": data.get("macro_assets", {}),
        "etf_flow": data.get("etf_flow", {}),
        "whale_data": data.get("whale_data", {}),
        "fgi": data.get("fgi", {}),
        "next_key_events": data.get("next_key_events", []),
        "raw_data": data,
    }


def parse_a6_report(file_path: Path) -> Dict:
    """解析 A6 情报简报（Markdown）"""
    content = _read_md_safe(file_path)
    if not content:
        return {"ok": False, "error": "failed to read a6 report"}

    lines = content.split("\n")

    price = ""
    regime = ""
    direction = ""
    fgi = ""
    total_score = 0

    for line in lines:
        if "BTC价格" in line and "$" in line:
            m = re.search(r'\$([\d,]+)', line)
            if m:
                price = m.group(1).replace(",", "")
        if "Regime:" in line:
            m = re.search(r'Regime:\s*(\S+)', line)
            if m:
                regime = m.group(1)
        if "方向判定" in line:
            if "BULL" in line:
                direction = "BULLISH"
            elif "BEAR" in line:
                direction = "BEARISH"
            else:
                direction = "NEUTRAL"
        if "SI_Index" in line and "=" in line:
            m = re.search(r'SI_Index\s*=\s*([+-]?\d+)', line)
            if m:
                total_score = int(m.group(1))
        if "FGI" in line and "Extreme Fear" in line:
            fgi = "Extreme Fear"
        elif "FGI" in line and "Fear" in line:
            fgi = "Fear"
        elif "FGI" in line and "Neutral" in line:
            fgi = "Neutral"

    return {
        "ok": True,
        "type": "a6",
        "file": file_path.name,
        "date": _extract_date_from_filename(file_path.name),
        "regime": regime,
        "direction": direction,
        "btc_price": float(price) if price else 0,
        "fgi_status": fgi,
        "si_index": total_score,
        "content_length": len(content),
        "summary": content[:500],
    }


def get_latest_reports() -> Dict:
    """获取最新的各类型研报"""
    a1_list = list_a1_reports(limit=1)
    a6_list = list_a6_reports(limit=1)
    weekly_list = list_weekly_reports(limit=1)

    result = {
        "ok": True,
        "a1": None,
        "a6": None,
        "weekly": None,
    }

    if a1_list:
        a1 = parse_a1_report(Path(a1_list[0]["path"]))
        if a1.get("ok"):
            result["a1"] = {k: v for k, v in a1.items() if k != "raw_data"}

    if a6_list:
        result["a6"] = parse_a6_report(Path(a6_list[0]["path"]))

    if weekly_list:
        result["weekly"] = {
            "file": weekly_list[0]["file"],
            "date": weekly_list[0]["date"],
        }

    return result


def publish_a1_report(file_path: str = None) -> Dict:
    """发布 A1 研报到 shared_memory_bus"""
    from scripts.memory_l4.shared_memory_bus import publish_shared_memory_event
    from scripts.memory_l4.ab_bridge import ACL_CONFIG

    if file_path:
        a1 = parse_a1_report(Path(file_path))
    else:
        a1_list = list_a1_reports(limit=1)
        if not a1_list:
            return {"ok": False, "error": "no a1 reports found"}
        a1 = parse_a1_report(Path(a1_list[0]["path"]))

    if not a1.get("ok"):
        return {"ok": False, "error": a1.get("error")}

    payload = {
        "report_type": "a1",
        "report_file": a1["file"],
        "report_date": a1["date"],
        "regime": a1["regime"],
        "regime_confidence": a1["regime_confidence"],
        "si_score": a1["si_score"],
        "si_range": a1["si_range"],
        "primary_contradiction": a1["primary_contradiction"],
        "total_contradictions": a1["total_contradictions"],
        "contradiction_intensity": a1["contradiction_intensity"],
        "signal_sufficiency": a1["signal_sufficiency"],
        "action_pressure": a1["action_pressure"],
        "key_levels": a1["key_levels"],
        "macro_assets": a1["macro_assets"],
        "triple_screen": a1["triple_screen"],
    }

    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    result = publish_shared_memory_event(
        snapshot_ts=ts,
        agent_id="a_research",
        event_type="a1_report_update",
        payload=payload,
        acl_config=ACL_CONFIG,
    )

    return {
        "ok": result.get("ok", False),
        "published": result.get("ok", False),
        "regime": a1["regime"],
        "si_score": a1["si_score"],
        "bus_path": result.get("bus_path", ""),
    }


def publish_a6_report(file_path: str = None) -> Dict:
    """发布 A6 研报到 shared_memory_bus"""
    from scripts.memory_l4.shared_memory_bus import publish_shared_memory_event
    from scripts.memory_l4.ab_bridge import ACL_CONFIG

    if file_path:
        a6 = parse_a6_report(Path(file_path))
    else:
        a6_list = list_a6_reports(limit=1)
        if not a6_list:
            return {"ok": False, "error": "no a6 reports found"}
        a6 = parse_a6_report(Path(a6_list[0]["path"]))

    if not a6.get("ok"):
        return {"ok": False, "error": a6.get("error")}

    payload = {
        "report_type": "a6",
        "report_file": a6["file"],
        "report_date": a6["date"],
        "regime": a6["regime"],
        "direction": a6["direction"],
        "btc_price": a6["btc_price"],
        "fgi_status": a6["fgi_status"],
        "si_index": a6["si_index"],
        "summary": a6.get("summary", ""),
    }

    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    result = publish_shared_memory_event(
        snapshot_ts=ts,
        agent_id="a_research",
        event_type="a6_report_update",
        payload=payload,
        acl_config=ACL_CONFIG,
    )

    return {
        "ok": result.get("ok", False),
        "published": result.get("ok", False),
        "regime": a6["regime"],
        "direction": a6["direction"],
        "si_index": a6["si_index"],
        "bus_path": result.get("bus_path", ""),
    }


def publish_all_latest() -> Dict:
    """发布所有最新研报"""
    results = {}
    try:
        r = publish_a1_report()
        results["a1"] = r
    except Exception as e:
        results["a1"] = {"ok": False, "error": str(e)}

    try:
        r = publish_a6_report()
        results["a6"] = r
    except Exception as e:
        results["a6"] = {"ok": False, "error": str(e)}

    return results


def get_research_summary() -> Dict:
    """获取研报数据摘要（供前端）"""
    reports = get_latest_reports()
    return {
        "a1_count": len(list_a1_reports(limit=100)),
        "a6_count": len(list_a6_reports(limit=100)),
        "weekly_count": len(list_weekly_reports(limit=100)),
        "latest": reports,
        "reports_dir": str(REPORTS_DIR),
    }


def cli():
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.memory_l4.a_research_bridge <command>")
        print("Commands:")
        print("  list       - 列出研报")
        print("  latest     - 查看最新研报摘要")
        print("  publish    - 发布最新研报到总线")
        print("  publish-a1 - 仅发布 A1")
        print("  publish-a6 - 仅发布 A6")
        print("  summary    - 研报数据摘要")
        return

    cmd = sys.argv[1]

    if cmd == "list":
        print("A1 研报:")
        for r in list_a1_reports(5):
            print(f"  {r['file']} ({r['size']} bytes)")
        print("\nA6 研报:")
        for r in list_a6_reports(5):
            print(f"  {r['file']} ({r['size']} bytes)")
        print("\n周报:")
        for r in list_weekly_reports(5):
            print(f"  {r['file']} ({r['size']} bytes)")
        return

    if cmd == "latest":
        result = get_latest_reports()
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str)[:3000])
        return

    if cmd == "publish":
        result = publish_all_latest()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if cmd == "publish-a1":
        result = publish_a1_report()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if cmd == "publish-a6":
        result = publish_a6_report()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if cmd == "summary":
        result = get_research_summary()
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str)[:2000])
        return

    print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    cli()
