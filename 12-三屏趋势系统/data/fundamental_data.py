"""三屏趋势系统 — 基本面数据获取

从 A系列研报 读取基本面趋势判断，实现基本面与技术面撮合。

数据源对应关系：
  - 周报 (Markdown) → 周线基本面方向 + 置信度
  - A1日报 (JSON)   → 日线基本面方向 + 置信度

研报目录: experiments/ab-trading/A系列研报/
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ── 路径配置 ──────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_REPORT_BASE = _PROJECT_ROOT / "experiments" / "ab-trading" / "A系列研报"
WEEKLY_REPORT_DIR = _REPORT_BASE / "周报"
DAILY_REPORT_DIR = _REPORT_BASE / "A1研报"


# ── Regime → 方向映射 ────────────────────────────────────────────────────

_REGIME_DIRECTION_MAP = {
    # Bull regimes
    "BULL": "BULL",
    "BULL_MARKET": "BULL",
    "BULL_CONTINUATION": "BULL",
    "NEUTRAL_TRANSITION": "NEUTRAL",
    # Bear regimes
    "BEAR": "BEAR",
    "BEAR_MARKET": "BEAR",
    "BEAR_CONTINUATION": "BEAR",
    "BEAR_TRANSITION": "BEAR",
    "BEAR_RECOVERY": "NEUTRAL",  # 熊市恢复中，方向中性偏多
    # Neutral
    "NEUTRAL": "NEUTRAL",
    "RANGE_BOUND": "NEUTRAL",
}


def _regime_to_direction(regime: str) -> str:
    """将 regime 名称映射为 BULL/BEAR/NEUTRAL"""
    if not regime:
        return "NEUTRAL"
    regime_upper = regime.upper().replace("-", "_").replace(" ", "_")
    return _REGIME_DIRECTION_MAP.get(regime_upper, "NEUTRAL")


def _score_to_confidence(score: float, max_score: float = 100) -> float:
    """将评分转换为 0-100 置信度

    评分 50 = 中性（置信度 0）
    评分 100 = 极度看多（置信度 100）
    评分 0 = 极度看空（置信度 100，方向为 BEAR）
    """
    deviation = abs(score - 50) * 2  # 0-100 范围
    return min(100, max(0, deviation))


def _score_to_direction(score: float, threshold: float = 55) -> str:
    """将评分映射为方向

    score >= 55 → BULL
    score <= 45 → BEAR
    其余 → NEUTRAL
    """
    if score >= threshold:
        return "BULL"
    elif score <= (100 - threshold):
        return "BEAR"
    return "NEUTRAL"


# ── A1 日报解析 ──────────────────────────────────────────────────────────

def _parse_a1_daily(filepath: Path) -> Optional[Dict]:
    """解析单个 A1 日报 JSON 文件

    支持三种 JSON 格式：
    1. market_regime.regime + market_regime.confidence + market_regime.composite_score
    2. regime.name + regime.confidence + si_index.value
    3. regime + confidence + si_index

    返回:
        {"date", "direction", "confidence", "regime", "score", "source_file"}
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    date_str = ""
    direction = "NEUTRAL"
    confidence = 0.0
    regime_name = "UNKNOWN"
    score = 50.0

    # 提取日期
    date_str = (
        data.get("date", "")
        or data.get("timestamp", "")
        or data.get("meta", {}).get("timestamp", "")
        or ""
    )[:10]

    # 格式1: market_regime 嵌套
    mr = data.get("market_regime")
    if isinstance(mr, dict):
        regime_name = mr.get("regime", "UNKNOWN")
        conf_raw = mr.get("confidence", 0)
        confidence = conf_raw * 100 if conf_raw <= 1.0 else conf_raw
        score = mr.get("composite_score", 50)
        direction = _regime_to_direction(regime_name)
        # 如果 composite_score 可用，用它修正方向
        score_dir = _score_to_direction(score)
        if score_dir != "NEUTRAL":
            direction = score_dir
        return {
            "date": date_str,
            "direction": direction,
            "confidence": round(confidence, 1),
            "regime": regime_name,
            "score": score,
            "source_file": filepath.name,
        }

    # 格式2: regime 对象嵌套
    reg = data.get("regime")
    if isinstance(reg, dict):
        regime_name = reg.get("name", "UNKNOWN")
        conf_raw = reg.get("confidence", 0)
        confidence = conf_raw * 100 if conf_raw <= 1.0 else conf_raw
        direction = _regime_to_direction(regime_name)
    else:
        # 格式3: regime 字符串
        regime_name = data.get("regime", "UNKNOWN")
        if isinstance(regime_name, str):
            direction = _regime_to_direction(regime_name)

    # confidence
    if confidence == 0:
        conf_raw = data.get("confidence", 0)
        confidence = conf_raw * 100 if conf_raw <= 1.0 else conf_raw

    # si_index 作为补充评分
    si = data.get("si_index")
    if isinstance(si, dict):
        score = si.get("value", 50)
    elif isinstance(si, (int, float)):
        score = si

    # three_screen.daily 作为方向参考
    ts = data.get("three_screen")
    if isinstance(ts, dict):
        daily_score = ts.get("daily", 0)
        if daily_score > 0:
            direction = "BULL"
        elif daily_score < 0:
            direction = "BEAR"

    # 如果 confidence 仍然为0，用 score 推断
    if confidence == 0 and score != 50:
        confidence = _score_to_confidence(score)

    return {
        "date": date_str,
        "direction": direction,
        "confidence": round(max(0, min(100, confidence)), 1),
        "regime": regime_name if isinstance(regime_name, str) else "UNKNOWN",
        "score": score,
        "source_file": filepath.name,
    }


def _get_latest_a1_daily() -> Optional[Dict]:
    """获取最新的 A1 日报数据"""
    if not DAILY_REPORT_DIR.exists():
        return None

    files = sorted(DAILY_REPORT_DIR.glob("a1_regime_*.json"), reverse=True)
    for f in files:
        result = _parse_a1_daily(f)
        if result:
            return result
    return None


def _get_recent_a1_dailies(days: int = 7) -> List[Dict]:
    """获取最近 N 天的 A1 日报列表"""
    if not DAILY_REPORT_DIR.exists():
        return []

    files = sorted(DAILY_REPORT_DIR.glob("a1_regime_*.json"), reverse=True)
    results = []
    for f in files[:days]:
        parsed = _parse_a1_daily(f)
        if parsed:
            results.append(parsed)
    return results


# ── 周报解析 ──────────────────────────────────────────────────────────────

def _parse_weekly_report(filepath: Path) -> Optional[Dict]:
    """解析周报 Markdown 文件

    从 frontmatter 和正文中提取：
    - date
    - 方向（从"方向"行或决策摘要表提取）
    - 评分（从"评分"行提取）
    - regime

    返回:
        {"date", "direction", "confidence", "regime", "score", "source_file"}
    """
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception:
        return None

    date_str = ""
    direction = "NEUTRAL"
    confidence = 0.0
    regime = "UNKNOWN"
    score = 50.0

    # 提取 frontmatter 中的 date
    fm_match = re.search(r"^date:\s*[\"']?(.+?)[\"']?\s*$", content, re.MULTILINE)
    if fm_match:
        date_str = fm_match.group(1).strip()[:10]

    # 提取方向关键词
    # 匹配 "方向" 行中的方向描述
    dir_patterns = [
        (r'方向["\s|]*\*?\*?\s*(?:WAIT\s*→\s*)?(弱多头|多头|LONG|BULL|看多|多方)', "BULL"),
        (r'方向["\s|]*\*?\*?\s*(?:WAIT\s*→\s*)?(弱空头|空头|SHORT|BEAR|看空|空方)', "BEAR"),
        (r'方向["\s|]*\*?\*?\s*(?:WAIT|观望|中性|NEUTRAL)', "NEUTRAL"),
        (r'\*\*方向\*\*\s*\|?\s*\*?\*?(?:WAIT\s*→\s*)?(弱多头|多头|LONG)', "BULL"),
        (r'\*\*方向\*\*\s*\|?\s*\*?\*?(?:WAIT\s*→\s*)?(弱空头|空头|SHORT)', "BEAR"),
    ]
    for pattern, dir_label in dir_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            direction = dir_label
            break

    # 提取评分 — 匹配多种格式：
    #   | **评分** | **55/100** |    (markdown table)
    #   **周线评分**: 60/100         (inline)
    #   评分: 55/100                 (simple)
    score_match = re.search(r'评分\*{0,2}\s*[\|:]\s*\*{0,2}\s*(\d+(?:\.\d+)?)\s*/\s*100', content)
    if score_match:
        score = float(score_match.group(1))
    else:
        score_match2 = re.search(r'周线评分\*{0,2}\s*[:：]\s*\*{0,2}\s*(\d+(?:\.\d+)?)\s*/\s*100', content)
        if score_match2:
            score = float(score_match2.group(1))

    # 提取 regime
    regime_match = re.search(r'Regime["\s|:]*\*?\*?\s*(BEAR_\w+|BULL_\w+|NEUTRAL\w*|RANGE_\w+)', content, re.IGNORECASE)
    if regime_match:
        regime = regime_match.group(1).upper()
        regime_dir = _regime_to_direction(regime)
        if regime_dir != "NEUTRAL":
            direction = regime_dir

    # 评分转置信度
    confidence = _score_to_confidence(score)

    # 方向优先级：regime > 评分 > 文本关键词
    # regime 已在上面处理，此处仅在 regime 未给出明确方向时用评分补充
    if regime == "UNKNOWN":
        score_dir = _score_to_direction(score)
        if score_dir != "NEUTRAL":
            direction = score_dir

    return {
        "date": date_str,
        "direction": direction,
        "confidence": round(confidence, 1),
        "regime": regime,
        "score": score,
        "source_file": filepath.name,
    }


def _get_latest_weekly() -> Optional[Dict]:
    """获取最新的周报数据"""
    if not WEEKLY_REPORT_DIR.exists():
        return None

    files = sorted(WEEKLY_REPORT_DIR.glob("screen1_*.md"), reverse=True)
    for f in files:
        result = _parse_weekly_report(f)
        if result:
            return result
    return None


# ── 合并基本面数据 ────────────────────────────────────────────────────────

def _merge_fundamental(weekly: Optional[Dict], daily: Optional[Dict]) -> Dict:
    """合并周报和日报的基本面数据

    合并规则：
    - 周报权重 60%（周线级别更重要）
    - 日报权重 40%
    - 方向以一致方向为准；不一致时取周报方向，降低置信度
    - 置信度加权平均

    返回:
        {
            "direction": "BULL"/"BEAR"/"NEUTRAL",
            "confidence": 0-100,
            "weekly": {...},
            "daily": {...},
            "reports": [...],
            "bull_count": int,
            "bear_count": int,
            "total_reports": int,
        }
    """
    reports = []
    bull_count = 0
    bear_count = 0

    weekly_dir = weekly["direction"] if weekly else "NEUTRAL"
    weekly_conf = weekly["confidence"] if weekly else 0
    daily_dir = daily["direction"] if daily else "NEUTRAL"
    daily_conf = daily["confidence"] if daily else 0

    if weekly:
        reports.append({
            "type": "周报",
            "timeframe": "weekly",
            **weekly,
        })
        if weekly_dir == "BULL":
            bull_count += 1
        elif weekly_dir == "BEAR":
            bear_count += 1

    if daily:
        reports.append({
            "type": "A1日报",
            "timeframe": "daily",
            **daily,
        })
        if daily_dir == "BULL":
            bull_count += 1
        elif daily_dir == "BEAR":
            bear_count += 1

    # 方向合并
    if weekly_dir == daily_dir and weekly_dir != "NEUTRAL":
        final_direction = weekly_dir
        final_confidence = weekly_conf * 0.6 + daily_conf * 0.4
    elif weekly_dir != "NEUTRAL" and daily_dir == "NEUTRAL":
        final_direction = weekly_dir
        final_confidence = weekly_conf * 0.7
    elif daily_dir != "NEUTRAL" and weekly_dir == "NEUTRAL":
        final_direction = daily_dir
        final_confidence = daily_conf * 0.5
    elif weekly_dir != "NEUTRAL" and daily_dir != "NEUTRAL" and weekly_dir != daily_dir:
        # 方向矛盾，取周线方向但大幅降低置信度
        final_direction = weekly_dir
        final_confidence = max(weekly_conf, daily_conf) * 0.3
    else:
        final_direction = "NEUTRAL"
        final_confidence = 0

    final_confidence = round(max(0, min(100, final_confidence)), 1)

    return {
        "direction": final_direction,
        "confidence": final_confidence,
        "weekly": weekly,
        "daily": daily,
        "reports": reports,
        "bull_count": bull_count,
        "bear_count": bear_count,
        "total_reports": len(reports),
    }


# ── 公开接口 ──────────────────────────────────────────────────────────────

def fetch_fundamental_data(symbol: str = "BTC") -> Dict:
    """
    获取基本面数据（周报 + A1日报）

    周报 → 周线基本面方向 + 置信度
    A1日报 → 日线基本面方向 + 置信度
    两者合并后输出统一的基本面方向和置信度，用于技术面+基本面撮合。

    参数:
        symbol: 币种符号（预留，当前研报以 BTC 为主）

    返回:
        {
            "direction": "BULL"/"BEAR"/"NEUTRAL",
            "confidence": 0-100,
            "weekly": {"date", "direction", "confidence", "regime", "score", ...},
            "daily": {"date", "direction", "confidence", "regime", "score", ...},
            "reports": [...],
            "bull_count": int,
            "bear_count": int,
            "total_reports": int,
        }
    """
    weekly = _get_latest_weekly()
    daily = _get_latest_a1_daily()

    if not weekly and not daily:
        return {
            "direction": "NEUTRAL",
            "confidence": 0,
            "weekly": None,
            "daily": None,
            "reports": [{"type": "无研报", "direction": "NEUTRAL", "confidence": 0}],
            "bull_count": 0,
            "bear_count": 0,
            "total_reports": 0,
        }

    return _merge_fundamental(weekly, daily)


def fetch_fundamental_by_timeframe(symbol: str = "BTC") -> Dict[str, Optional[Dict]]:
    """
    按时间周期分别获取基本面数据

    返回:
        {
            "weekly": {"direction", "confidence", "regime", "score", ...} or None,
            "daily": {"direction", "confidence", "regime", "score", ...} or None,
        }
    """
    return {
        "weekly": _get_latest_weekly(),
        "daily": _get_latest_a1_daily(),
    }


if __name__ == "__main__":
    result = fetch_fundamental_data("BTC")
    print(json.dumps(result, ensure_ascii=False, indent=2))
