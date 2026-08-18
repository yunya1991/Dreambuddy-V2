#!/usr/bin/env python3
"""
做梦产物集成模块 — 16-调控系统 Phase 2+

读取和解析做梦部产物，集成到 A1 调研报告中。

支持的产物类型：
  - dream_journal_YYYYMMDD.md — 每日梦境日志
  - dream_brainstorm_daily_*.md — 每日头脑风暴
  - dream_brainstorm_weekly_*.md — 周度头脑风暴
  - dream_insight_*.md — 洞察报告

核心功能：
  - 自动搜索最新做梦产物
  - 解析关键字段（被压制信号、噩梦场景、反直觉信号等）
  - 与 A1 调研结果交叉验证
  - 生成 dream_insights 结构化输出
"""

import re
import os
import glob
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

BASE_DIR = Path(__file__).parent.parent.parent

SEARCH_PATHS = [
    BASE_DIR / "11-易经推理系统" / "skills" / "3-SUPPORT" / "boss-secretary" / "reports",
    BASE_DIR / "6-TRADING" / "skills" / "dream-oneirology",
    BASE_DIR / "artifacts" / "oneirology",
    Path(os.path.expanduser("~/.workbuddy/artifacts/oneirology")),
    Path(os.path.expanduser("~/.workbuddy/skills/boss-secretary/reports")),
    BASE_DIR / "16-调控系统" / "artifacts" / "dream-insights",
    BASE_DIR,
]


@dataclass
class DreamProduct:
    """做梦产物"""
    path: Path
    product_type: str
    title: str
    date: str
    content: str
    frontmatter: Dict[str, Any]


def _parse_frontmatter(content: str) -> Dict[str, Any]:
    """解析 YAML frontmatter"""
    if not content.startswith("---"):
        return {}
    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return {}
    fm_text = match.group(1)
    result = {}
    for line in fm_text.split("\n"):
        line = line.strip()
        if ":" in line:
            k, v = line.split(":", 1)
            v = v.strip().strip('"').strip("'")
            result[k.strip()] = v
    return result


def _extract_sections(content: str) -> Dict[str, str]:
    """提取 Markdown 章节"""
    sections = {}
    current_section = "_preamble"
    current_lines = []

    for line in content.split("\n"):
        if line.startswith("## "):
            if current_section and current_lines:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_section and current_lines:
        sections[current_section] = "\n".join(current_lines).strip()

    return sections


def _extract_bullet_list(section_text: str) -> List[str]:
    """从章节文本中提取无序列表项"""
    items = []
    for line in section_text.split("\n"):
        line = line.strip()
        if line.startswith("- ") or line.startswith("* "):
            item = line[2:].strip()
            item = re.sub(r"^\*\*.*?\*\*:\s*", "", item)
            item = re.sub(r"^`.*?`\s*", "", item)
            if item:
                items.append(item)
    return items


def _find_latest_products(max_age_days: int = 7) -> List[DreamProduct]:
    """搜索最新的做梦产物"""
    products = []
    patterns = [
        "dream_journal_*.md",
        "dream_brainstorm_daily_*.md",
        "dream_brainstorm_weekly_*.md",
        "dream_insight_*.md",
    ]

    seen_paths = set()
    for search_dir in SEARCH_PATHS:
        if not search_dir.exists():
            continue
        for pattern in patterns:
            full_pattern = str(search_dir / "**" / pattern)
            for filepath in glob.glob(full_pattern, recursive=True):
                fp = Path(filepath).resolve()
                if str(fp) in seen_paths:
                    continue
                seen_paths.add(str(fp))

                try:
                    mtime = fp.stat().st_mtime
                    age_days = (datetime.now().timestamp() - mtime) / 86400
                    if age_days > max_age_days:
                        continue

                    with open(fp, "r", encoding="utf-8") as f:
                        content = f.read()

                    fm = _parse_frontmatter(content)
                    fname = fp.name

                    if "dream_journal" in fname:
                        ptype = "dream_journal"
                    elif "brainstorm_daily" in fname:
                        ptype = "brainstorm_daily"
                    elif "brainstorm_weekly" in fname:
                        ptype = "brainstorm_weekly"
                    elif "dream_insight" in fname:
                        ptype = "dream_insight"
                    else:
                        ptype = "other"

                    title = fm.get("title", fp.stem)
                    date_str = fm.get("date", "")
                    if not date_str:
                        date_match = re.search(r"(\d{8})", fname)
                        if date_match:
                            d = date_match.group(1)
                            date_str = f"{d[:4]}-{d[4:6]}-{d[6:]}"
                        else:
                            date_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")

                    products.append(DreamProduct(
                        path=fp,
                        product_type=ptype,
                        title=title,
                        date=date_str,
                        content=content,
                        frontmatter=fm,
                    ))
                except Exception:
                    pass

    products.sort(key=lambda p: p.date, reverse=True)
    return products


def _extract_insights_from_product(product: DreamProduct) -> Dict[str, List[str]]:
    """从做梦产物中提取核心洞察字段"""
    sections = _extract_sections(product.content)
    insights = {
        "suppressed_signals": [],
        "nightmare_scenarios": [],
        "counter_intuitive_signals": [],
        "improvement_suggestions": [],
        "contradiction_map": [],
        "compulsive_patterns": [],
        "risk_warnings": [],
        "key_insights": [],
    }

    for sec_name, sec_text in sections.items():
        sec_lower = sec_name.lower()

        if any(k in sec_lower for k in ["被压制", "压制信号", "suppressed"]):
            insights["suppressed_signals"].extend(_extract_bullet_list(sec_text))

        if any(k in sec_lower for k in ["噩梦", "噩梦场景", "nightmare", "极端风险"]):
            insights["nightmare_scenarios"].extend(_extract_bullet_list(sec_text))

        if any(k in sec_lower for k in ["反直觉", "counter-intuitive", "反常识"]):
            insights["counter_intuitive_signals"].extend(_extract_bullet_list(sec_text))

        if any(k in sec_lower for k in ["改进建议", "优化点", "improvement", "决策优化"]):
            insights["improvement_suggestions"].extend(_extract_bullet_list(sec_text))

        if any(k in sec_lower for k in ["矛盾", "contradiction", "冲突"]):
            insights["contradiction_map"].extend(_extract_bullet_list(sec_text))

        if any(k in sec_lower for k in ["强迫性重复", "重复模式", "compulsive", "反复犯错"]):
            insights["compulsive_patterns"].extend(_extract_bullet_list(sec_text))

        if any(k in sec_lower for k in ["风险", "警示", "warning", "risk"]):
            insights["risk_warnings"].extend(_extract_bullet_list(sec_text))

        if any(k in sec_lower for k in ["洞察", "核心发现", "insight", "关键发现"]):
            insights["key_insights"].extend(_extract_bullet_list(sec_text))

    all_text = product.content
    patterns = {
        "suppressed_signals": [r"被压制[的之]信号[:：]?\s*(.+?)(?:\n|$)", r"suppressed signal[:：]?\s*(.+?)(?:\n|$)"],
        "nightmare_scenarios": [r"噩梦场景[:：]?\s*(.+?)(?:\n|$)", r"nightmare scenario[:：]?\s*(.+?)(?:\n|$)"],
        "counter_intuitive_signals": [r"反直觉[的之]?信号?[:：]?\s*(.+?)(?:\n|$)"],
    }
    for key, pat_list in patterns.items():
        for pat in pat_list:
            for match in re.finditer(pat, all_text, re.IGNORECASE):
                val = match.group(1).strip()
                if val and val not in insights[key]:
                    insights[key].append(val)

    return insights


def load_dream_insights(max_age_days: int = 7,
                        max_products: int = 3) -> Dict[str, Any]:
    """
    加载并整合做梦产物洞察

    Args:
        max_age_days: 最大天数（默认7天内）
        max_products: 最多加载多少个产物

    Returns:
        结构化 dream_insights 字典，符合 A1 SKILL 输出规范
    """
    products = _find_latest_products(max_age_days)

    if not products:
        return {
            "incorporated": False,
            "available": False,
            "reason": "未找到近期做梦产物",
            "suppressed_signals": [],
            "nightmare_scenarios": [],
            "counter_intuitive": [],
            "improvement_suggestions": [],
            "contradiction_analysis": [],
            "pattern_warnings": [],
            "products_found": 0,
            "latest_product_date": "",
        }

    products = products[:max_products]

    all_insights = {
        "suppressed_signals": [],
        "nightmare_scenarios": [],
        "counter_intuitive_signals": [],
        "improvement_suggestions": [],
        "contradiction_map": [],
        "compulsive_patterns": [],
        "risk_warnings": [],
        "key_insights": [],
    }

    product_infos = []
    for p in products:
        insights = _extract_insights_from_product(p)
        for key in all_insights:
            for item in insights.get(key, []):
                if item and item not in all_insights[key]:
                    all_insights[key].append(item)
        product_infos.append({
            "type": p.product_type,
            "title": p.title,
            "date": p.date,
            "path": str(p.path),
        })

    latest_date = products[0].date if products else ""

    return {
        "incorporated": True,
        "available": True,
        "products_found": len(products),
        "latest_product_date": latest_date,
        "products": product_infos,
        "suppressed_signals": all_insights["suppressed_signals"][:5],
        "nightmare_scenarios": all_insights["nightmare_scenarios"][:3],
        "counter_intuitive": all_insights["counter_intuitive_signals"][:3],
        "improvement_suggestions": all_insights["improvement_suggestions"][:5],
        "contradiction_analysis": all_insights["contradiction_map"][:3],
        "pattern_warnings": all_insights["compulsive_patterns"][:3],
        "risk_warnings_dream": all_insights["risk_warnings"][:3],
        "dream_key_insights": all_insights["key_insights"][:5],
    }


def cross_validate_with_research(dream_insights: Dict[str, Any],
                                 a1_report: Dict[str, Any]) -> Dict[str, Any]:
    """
    做梦洞察与 A1 调研结果交叉验证

    Args:
        dream_insights: 做梦产物洞察
        a1_report: A1 调研报告

    Returns:
        交叉验证结果
    """
    if not dream_insights.get("incorporated", False):
        return {
            "performed": False,
            "reason": "无做梦产物可用",
        }

    ms = a1_report.get("market_state", {}) if isinstance(a1_report, dict) else {}
    sig_suf = a1_report.get("signal_sufficiency", {}) if isinstance(a1_report, dict) else {}

    a1_direction = ms.get("trend_direction", "UNCLEAR")
    a1_net = sig_suf.get("net_direction", "MIXED") if isinstance(sig_suf, dict) else "MIXED"

    dream_bullish = 0
    dream_bearish = 0
    dream_neutral = 0

    for sig in dream_insights.get("suppressed_signals", []):
        if any(w in sig for w in ["涨", "多", "bull", "up", "反弹", "上涨"]):
            dream_bullish += 1
        elif any(w in sig for w in ["跌", "空", "bear", "down", "回调", "下跌"]):
            dream_bearish += 1
        else:
            dream_neutral += 1

    for sig in dream_insights.get("counter_intuitive", []):
        if any(w in sig for w in ["涨", "多", "bull", "up"]):
            dream_bullish += 1
        elif any(w in sig for w in ["跌", "空", "bear", "down"]):
            dream_bearish += 1
        else:
            dream_neutral += 1

    dream_net = "UP" if dream_bullish > dream_bearish else ("DOWN" if dream_bearish > dream_bullish else "MIXED")

    a1_is_up = a1_net == "UP" or a1_direction in ("BULL", "NEUTRAL_UP")
    a1_is_down = a1_net == "DOWN" or a1_direction in ("BEAR", "NEUTRAL_DOWN")
    dream_is_up = dream_net == "UP"
    dream_is_down = dream_net == "DOWN"

    contradictions = []
    confirmations = []

    if a1_is_up and dream_is_down:
        contradictions.append({
            "type": "梦境矛盾",
            "description": "A1调研看多 vs 做梦洞察看空",
            "severity": "HIGH",
            "impact": "降低A1调研置信度，警惕反向走势",
        })
    elif a1_is_down and dream_is_up:
        contradictions.append({
            "type": "梦境矛盾",
            "description": "A1调研看空 vs 做梦洞察看多",
            "severity": "HIGH",
            "impact": "降低A1调研置信度，警惕反向走势",
        })
    elif a1_is_up and dream_is_up:
        confirmations.append("A1调研与做梦洞察方向一致（看多），信号可信度提升")
    elif a1_is_down and dream_is_down:
        confirmations.append("A1调研与做梦洞察方向一致（看空），信号可信度提升")
    else:
        confirmations.append("A1调研与做梦洞察无明显矛盾")

    has_nightmare = len(dream_insights.get("nightmare_scenarios", [])) > 0

    return {
        "performed": True,
        "a1_net_direction": a1_net,
        "dream_net_direction": dream_net,
        "dream_bullish_signals": dream_bullish,
        "dream_bearish_signals": dream_bearish,
        "dream_neutral_signals": dream_neutral,
        "contradictions": contradictions,
        "confirmations": confirmations,
        "has_nightmare_scenarios": has_nightmare,
        "impact_assessment": "降低置信度" if contradictions else "提升置信度",
    }


def get_dream_insights_for_a1(max_age_days: int = 7) -> Dict[str, Any]:
    """
    为 A1 适配器准备 dream_insights 字段（符合 SKILL.md 输出规范）

    Args:
        max_age_days: 最大天数

    Returns:
        可直接嵌入 A1 报告的 dream_insights 字典
    """
    insights = load_dream_insights(max_age_days)

    return {
        "incorporated": insights.get("incorporated", False),
        "suppressed_signals": insights.get("suppressed_signals", []),
        "nightmare_scenarios": insights.get("nightmare_scenarios", []),
        "counter_intuitive": insights.get("counter_intuitive", []),
        "products_info": insights.get("products", []),
        "latest_date": insights.get("latest_product_date", ""),
        "note": "" if insights.get("incorporated") else "无近期做梦产物，使用默认分析",
    }


if __name__ == "__main__":
    insights = load_dream_insights(max_age_days=30)
    print(f"找到做梦产物: {insights['products_found']} 个")
    print(f"最新日期: {insights['latest_product_date']}")
    print(f"被压制信号: {len(insights['suppressed_signals'])} 个")
    print(f"噩梦场景: {len(insights['nightmare_scenarios'])} 个")
    print(f"反直觉信号: {len(insights['counter_intuitive'])} 个")
    if insights.get("products"):
        for p in insights["products"]:
            print(f"  - [{p['type']}] {p['date']}: {p['title']}")
