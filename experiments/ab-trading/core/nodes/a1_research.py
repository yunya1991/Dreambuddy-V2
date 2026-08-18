"""
A1 深度调研节点（v2.1 — 对接 A系列研报本地目录）
调用优先级：
  1. 本地 A系列研报目录（最新文件）← 新增
  2. A1 Feed API（http://49.233.123.96:3456/feed）
  3. 内置 fallback 规则

同时读取 A6 情报报告，融入决策输入。

SKILL.md 调用路径: experiments/ab-trading/core/nodes/a1_research
A系列研报路径: experiments/ab-trading/A系列研报/A1研报/  (A1报告 JSON)
                 experiments/ab-trading/A系列研报/A6研报/  (A6报告 MD)
"""

from typing import Dict, Any, Optional, List
import json, time, requests, os, glob
from pathlib import Path
from datetime import datetime, timedelta


# ── A系列研报目录（绝对路径）──────────────────────────────────────────────
_A1_REPORT_DIR = Path(__file__).resolve().parent.parent.parent / "A系列研报" / "A1研报"
_A6_REPORT_DIR = Path(__file__).resolve().parent.parent.parent / "A系列研报" / "A6研报"
_WEEKLY_REPORT_DIR = Path(__file__).resolve().parent.parent.parent / "A系列研报" / "周报"
_A1_REPORT_DIR.mkdir(parents=True, exist_ok=True)
_A6_REPORT_DIR.mkdir(parents=True, exist_ok=True)
_WEEKLY_REPORT_DIR.mkdir(parents=True, exist_ok=True)

# 报告最大年龄（小时）—— 超过此年龄的研报视为过期，降级到 API
_MAX_REPORT_AGE_HOURS = 12
_MAX_WEEKLY_AGE_HOURS = 336  # 14 天（周报每周生成，保留两周）


def execute(mkt: Dict, memory: Dict, data: Dict) -> Dict[str, Any]:
    """
    执行 A1 深度调研（含 A0 矛盾检测 + A6 情报注入）

    Args:
        mkt: 市场数据
        memory: 记忆数据
        data: 节点间共享数据

    Returns:
        {
            "direction": "LONG" | "SHORT" | "HOLD",
            "confidence": 0.0-1.0,
            "rationale": ["分析理由"],
            "data": {
                "a0": {...},
                "a1_report": {...},   # 来自 A1研报目录 或 API
                "a6_report": {...},   # 来自 A6研报目录
            }
        }
    """
    coin = mkt.get("coin", "BTC")
    price = mkt.get("price", 0)
    ch24 = mkt.get("change_24h", 0)

    reasoning = []
    a0_data = {}
    a1_report: Dict = {}
    a6_report: Dict = {}
    weekly_report: Dict = {}

    # ── Step0: 读取 A系列研报 + 周报（本地目录优先）─────────────────────
    a1_report = _load_latest_a1_report(coin, reasoning)
    a6_report = _load_latest_a6_report(coin, reasoning)
    weekly_report = _load_latest_weekly_report(reasoning)

    # ── Step1: A0 矛盾检测（内置）──────────────────────────────────────
    a0_result = _detect_contradictions(mkt, memory, data)
    a0_data = a0_result["a0"]
    reasoning.append(f"[A0内置] 矛盾检测: dominant={a0_data.get('dominant_force','NEUTRAL')}")

    # ── Step2: 融合 周报 + A0 + A1 + A6 ─────────────────────────────
    a1_dir = a1_report.get("direction", "HOLD")
    a1_conf = a1_report.get("confidence", 0.45)
    a1_source = a1_report.get("_source", "unknown")

    a6_dir = a6_report.get("direction", "HOLD")
    a6_conf = a6_report.get("confidence", 0.45)
    a6_risk = a6_report.get("risk_warning", "")

    w_dir = weekly_report.get("direction", "HOLD")
    w_conf = weekly_report.get("confidence", 0.5)
    w_strategy = weekly_report.get("strategy", "")
    w_position_cap = weekly_report.get("position_cap", "")
    w_trend = weekly_report.get("weekly_trend", "")
    w_source = weekly_report.get("_source", "unknown")

    a0_dir = "LONG" if a0_data.get("dominant_force") == "BULL" else \
             "SHORT" if a0_data.get("dominant_force") == "BEAR" else "HOLD"
    a0_conf = a0_data.get("confidence", 0.45)

    # A6 风险警告注入 rationale
    if a6_risk:
        reasoning.append(f"[A6情报] ⚠️ 风险警告: {a6_risk[:80]}")

    # 周报方向注入 rationale
    if w_source not in ("none", "expired", "error"):
        reasoning.append(f"[周报] 方向={w_dir} 趋势={w_trend} 策略={w_strategy} 仓位上限={w_position_cap}")

    # 四源融合（优先级: 周报(战略层) > A1 > A6 > A0，同向加成，冲突降权）
    # 周报作为战略层约束，如果周报方向明确（非HOLD），作为基础方向
    merged_dir = "HOLD"
    merged_conf = 0.45

    if w_dir != "HOLD" and w_source not in ("none", "expired", "error"):
        merged_dir = w_dir
        merged_conf = w_conf
        reasoning.append(f"[融合] 基础方向来自 周报({w_dir}), 置信度={w_conf:.2f} [{w_source}]")
    elif a1_dir != "HOLD":
        merged_dir = a1_dir
        merged_conf = a1_conf
        reasoning.append(f"[融合] 基础方向来自 A1({a1_dir}), 置信度={a1_conf:.2f} [{a1_source}]")
    elif a6_dir != "HOLD":
        merged_dir = a6_dir
        merged_conf = a6_conf
        reasoning.append(f"[融合] A1=HOLD, 使用 A6 结论: {a6_dir}")
    else:
        merged_dir = a0_dir
        merged_conf = a0_conf
        reasoning.append(f"[融合] A1/A6=HOLD，使用 A0 结论: {a0_dir}")

    # A1 与基础方向同向加成 / 冲突降权
    if a1_dir != "HOLD" and merged_dir != a1_dir and w_dir != "HOLD":
        merged_conf = max(merged_conf - 0.05, 0.20)
        reasoning.append(f"[融合] ⚠️ A1({a1_dir}) 与周报({merged_dir}) 冲突，置信度 -0.05 降权")
    elif a1_dir != "HOLD" and a1_dir == merged_dir:
        merged_conf = min(merged_conf + 0.03, 0.92)
        reasoning.append(f"[融合] A1({a1_dir}) 与基础方向同向，置信度 +0.03 加成")

    # A6 与基础方向同向加成 / 冲突降权
    if a6_dir != "HOLD" and a6_dir == merged_dir:
        merged_conf = min(merged_conf + 0.03, 0.92)
        reasoning.append(f"[融合] A6({a6_dir}) 与基础方向同向，置信度 +0.03 加成")
    elif a6_dir != "HOLD" and a6_dir != merged_dir:
        merged_conf = max(merged_conf - 0.05, 0.20)
        reasoning.append(f"[融合] ⚠️ A6({a6_dir}) 与基础方向({merged_dir}) 冲突，置信度 -0.05 降权")

    # A0 矛盾冲突时降权
    if a0_dir != "HOLD" and a0_dir != merged_dir:
        merged_conf = max(merged_conf - 0.04, 0.20)
        reasoning.append(f"[融合] ⚠️ A0({a0_dir}) 与融合结论冲突，置信度 -0.04 降权")

    merged_conf = max(min(merged_conf, 0.92), 0.20)

    return {
        "node": "A1_调研(含周报+A0+A6情报)",
        "direction": merged_dir,
        "confidence": round(merged_conf, 3),
        "rationale": reasoning,
        "data": {
            "a0": a0_data,
            "weekly_report": weekly_report,
            "a1_report": a1_report,
            "a6_report": a6_report,
        }
    }


# ── A1 研报读取 ────────────────────────────────────────────────────────────

def _load_latest_a1_report(coin: str, reasoning: List[str]) -> Dict:
    """
    读取 A系列研报/A1研报/ 中最新的报告文件。
    支持 JSON 格式（a1_regime_YYYYMMDD.json）。
    如果本地文件过期或不存在，降级到 Feed API。
    """
    # 1) 尝试读取本地最新 JSON 报告
    local_report = _read_latest_json_report(_A1_REPORT_DIR, coin, reasoning)
    if local_report:
        return local_report

    # 2) 降级：调用 Feed API
    reasoning.append("[A1研报] 本地研报目录无有效文件，调用 Feed API")
    try:
        resp = requests.get(
            "http://49.233.123.96:3456/feed",
            params={"coin": coin, "limit": 3},
            timeout=5
        )
        if resp.status_code == 200:
            feed = resp.json()
            result = feed if isinstance(feed, dict) else {"summary": str(feed)[:200]}
            result["_source"] = "feed_api"
            reasoning.append(f"[A1 Feed] API 获取到 {len(result)} 条数据")
            return result
        else:
            reasoning.append(f"[A1 Feed] API 返回 {resp.status_code}，使用备用逻辑")
    except Exception as e:
        reasoning.append(f"[A1 Feed] 请求失败: {str(e)[:50]}，使用备用逻辑")

    # 3) 最终降级：内置规则
    reasoning.append("[A1研报] 使用内置 fallback 逻辑")
    return {**_fallback_research_simple(coin), "_source": "fallback"}


def _read_latest_json_report(report_dir: Path, coin: str, reasoning: List[str]) -> Optional[Dict]:
    """读取指定目录下最新的 JSON 研报（按文件名时间戳排序）"""
    if not report_dir.exists():
        reasoning.append(f"[A1研报] 目录不存在: {report_dir}")
        return None

    # 查找所有 JSON 文件（支持 a1_regime_YYYYMMDD.json 或类似命名）
    json_files = sorted(report_dir.glob("*.json"), key=os.path.getmtime, reverse=True)
    if not json_files:
        reasoning.append(f"[A1研报] 目录无 JSON 文件: {report_dir}")
        return None

    latest_file = json_files[0]
    file_mtime = datetime.fromtimestamp(os.path.getmtime(latest_file))
    age_hours = (datetime.now() - file_mtime).total_seconds() / 3600

    if age_hours > _MAX_REPORT_AGE_HOURS:
        reasoning.append(f"[A1研报] 最新文件年龄 {age_hours:.1f}h > {_MAX_REPORT_AGE_HOURS}h，视为过期")
        return None

    try:
        with open(latest_file, "r", encoding="utf-8") as f:
            report = json.load(f)
        reasoning.append(f"[A1研报] 读取本地文件: {latest_file.name} (年龄 {age_hours:.1f}h)")
        # 标准化输出格式
        return _normalize_a1_json_report(report, str(latest_file.name))
    except Exception as e:
        reasoning.append(f"[A1研报] 读取失败: {str(e)[:60]}")
        return None


def _normalize_a1_json_report(raw: Dict, filename: str) -> Dict:
    """将 A1 JSON 报告标准化为 {direction, confidence, summary, _source} 格式"""
    # 尝试从 regime_classification 提取
    regime = raw.get("regime_classification", {})
    if regime:
        regime_type = regime.get("regime", "UNKNOWN")
        confidence = regime.get("confidence", 0.45)
        # regime -> direction 映射
        direction = "HOLD"
        if "BULL" in regime_type or "RECOVERY" in regime_type:
            direction = "LONG"
        elif "BEAR" in regime_type or "CRASH" in regime_type:
            direction = "SHORT"

        summary = regime.get("key_observation", raw.get("summary", ""))[:200]
        return {
            "direction": direction,
            "confidence": confidence,
            "summary": summary,
            "regime": regime_type,
            "filename": filename,
            "_source": "local_a1_report",
        }

    # 裸格式（已有 direction/confidence）
    return {
        "direction": raw.get("direction", "HOLD"),
        "confidence": raw.get("confidence", 0.45),
        "summary": raw.get("summary", ""),
        "filename": filename,
        "_source": "local_a1_report",
    }


# ── A6 研报读取 ────────────────────────────────────────────────────────────

def _load_latest_a6_report(coin: str, reasoning: List[str]) -> Dict:
    """
    读取 A系列研报/A6研报/ 中最新的 Markdown 报告。
    解析关键信息：方向、置信度、风险警告。
    """
    if not _A6_REPORT_DIR.exists():
        reasoning.append(f"[A6研报] 目录不存在: {_A6_REPORT_DIR}")
        return {"_source": "none"}

    # 查找所有 MD 文件（按修改时间排序）
    md_files = sorted(_A6_REPORT_DIR.glob("*.md"), key=os.path.getmtime, reverse=True)
    if not md_files:
        reasoning.append("[A6研报] 目录无 MD 文件")
        return {"_source": "none"}

    latest_file = md_files[0]
    file_mtime = datetime.fromtimestamp(os.path.getmtime(latest_file))
    age_hours = (datetime.now() - file_mtime).total_seconds() / 3600

    if age_hours > _MAX_REPORT_AGE_HOURS:
        reasoning.append(f"[A6研报] 最新文件年龄 {age_hours:.1f}h > {_MAX_REPORT_AGE_HOURS}h，视为过期")
        return {"_source": "expired", "age_hours": age_hours}

    try:
        with open(latest_file, "r", encoding="utf-8") as f:
            content = f.read()
        reasoning.append(f"[A6研报] 读取本地文件: {latest_file.name} (年龄 {age_hours:.1f}h)")
        return _parse_a6_markdown_report(content, str(latest_file.name))
    except Exception as e:
        reasoning.append(f"[A6研报] 读取失败: {str(e)[:60]}")
        return {"_source": "error"}


def _parse_a6_markdown_report(content: str, filename: str) -> Dict:
    """
    解析 A6 Markdown 情报报告，提取：
    - direction: 从趋势研判/综合研判提取
    - confidence: 从置信度字段提取（如有）
    - risk_warning: 风险警告（⚠️ 内容）
    - summary: 核心摘要
    """
    result = {
        "filename": filename,
        "_source": "local_a6_report",
        "direction": "HOLD",
        "confidence": 0.45,
        "risk_warning": "",
        "summary": "",
    }

    # 提取风险警告（⚠️ 行）
    import re
    warning_matches = re.findall(r"⚠️\s*([^\n]+)", content)
    if warning_matches:
        result["risk_warning"] = " | ".join(warning_matches[:3])

    # 从三屏综合研判提取方向
    if re.search(r"BEAR|Bear|bear.*\(-2\)|空头|下跌", content[:3000]):
        result["direction"] = "SHORT"
    if re.search(r"BULL|Bull|bull.*\(\+2\)|多头|上涨", content[:3000]):
        result["direction"] = "LONG"
    # 更精确的：看 "综合研判" 或 "核心结论" 部分
    conclusion_section = ""
    for section_header in ["综合研判", "核心结论", "情报结论", "三屏综合"]:
        idx = content.find(section_header)
        if idx >= 0:
            conclusion_section = content[idx:idx+800]
            break
    if conclusion_section:
        if re.search(r"偏多|偏LONG|看多|LONG|bull|BULL", conclusion_section, re.I):
            result["direction"] = "LONG"
        elif re.search(r"偏空|偏SHORT|看空|SHORT|bear|BEAR", conclusion_section, re.I):
            result["direction"] = "SHORT"

    # 提取 summary（取第一段非标题内容）
    lines = [l.strip() for l in content.split("\n") if l.strip() and not l.strip().startswith("#")]
    if lines:
        result["summary"] = lines[0][:200]

    return result


def _load_latest_weekly_report(reasoning: List[str]) -> Dict:
    """
    读取 A系列研报/周报/ 中最新的第一屏周报（screen1_*.md）。
    解析关键信息：周线方向、策略类型、仓位上限、A1-A3分析摘要。
    周报过期阈值为 14 天（每周生成一次）。
    """
    if not _WEEKLY_REPORT_DIR.exists():
        reasoning.append("[周报] 周报目录不存在")
        return {"_source": "none"}

    import re
    files = sorted(_WEEKLY_REPORT_DIR.glob("screen1_*.md"), key=os.path.getmtime, reverse=True)
    if not files:
        reasoning.append("[周报] 无周报文件")
        return {"_source": "none"}

    latest = files[0]
    age_hours = (time.time() - latest.stat().st_mtime) / 3600
    if age_hours > _MAX_WEEKLY_AGE_HOURS:
        reasoning.append(f"[周报] 最新周报已过期 ({age_hours/24:.1f}天前)")
        return {"_source": "expired", "age_hours": age_hours}

    try:
        content = latest.read_text(encoding="utf-8")
        result = _parse_weekly_report(content, latest.name)
        reasoning.append(f"[周报] 读取 {latest.name} ({age_hours:.1f}h前) → 方向={result['direction']} 策略={result['strategy']} 仓位上限={result['position_cap']}")
        return result
    except Exception as e:
        reasoning.append(f"[周报] 读取失败: {e}")
        return {"_source": "error"}


def _parse_weekly_report(content: str, filename: str) -> Dict:
    """
    解析第一屏周报 Markdown，提取：
    - direction: 周线方向（做多/做空/观望 → LONG/SHORT/HOLD）
    - strategy: 策略类型（合约马丁/现货马丁）
    - position_cap: 仓位上限（百分比）
    - weekly_trend: 周线趋势
    - weekly_score: 周线评分
    - summary: 核心摘要
    """
    import re
    result = {
        "filename": filename,
        "_source": "local_weekly_report",
        "direction": "HOLD",
        "confidence": 0.5,
        "strategy": "",
        "position_cap": "",
        "weekly_trend": "",
        "weekly_score": 0,
        "summary": "",
    }

    # 提取方向
    for pattern in [r"\*{0,2}方向\*{0,2}[：:]\s*(做多|做空|观望)", r"方向[：:]\s*(LONG|SHORT|HOLD|WAIT)"]:
        m = re.search(pattern, content, re.I)
        if m:
            d = m.group(1).upper()
            if "做多" in d or "LONG" in d:
                result["direction"] = "LONG"
            elif "做空" in d or "SHORT" in d:
                result["direction"] = "SHORT"
            else:
                result["direction"] = "HOLD"
            break

    # 提取策略类型
    m = re.search(r"\*{0,2}策略\*{0,2}[：:]\s*(合约马丁|现货马丁)", content)
    if m:
        result["strategy"] = m.group(1)

    # 提取仓位上限
    for pattern in [r"仓位上限[：:]\s*(\d+%)", r"基础仓位[：:]\s*(\d+%)"]:
        m = re.search(pattern, content)
        if m:
            result["position_cap"] = m.group(1)
            break

    # 提取周线趋势
    m = re.search(r"周线趋势[：:]\s*(多头|空头|震荡)", content)
    if m:
        result["weekly_trend"] = m.group(1)

    # 提取周线评分
    m = re.search(r"周线评分[：:]\s*(\d+)", content)
    if m:
        result["weekly_score"] = int(m.group(1))
        result["confidence"] = min(result["weekly_score"] / 100.0, 0.95)

    # 提取摘要（执行摘要部分）
    idx = content.find("核心判断")
    if idx >= 0:
        result["summary"] = content[idx:idx+300].replace("\n", " ").strip()[:200]
    else:
        lines = [l.strip() for l in content.split("\n") if l.strip() and not l.strip().startswith("#") and not l.strip().startswith("---")]
        if lines:
            result["summary"] = lines[0][:200]

    return result


# ── 原有函数保留（兼容）───────────────────────────────────────────────────

def _detect_contradictions(mkt: Dict, memory: Dict, data: Dict) -> Dict:
    """A0 矛盾检测：识别多空信号矛盾"""
    rsi = mkt.get("rsi14", 50)
    ch24 = mkt.get("change_24h", 0)
    fund_rate = mkt.get("funding_rate", 0)

    contradictions = []

    if rsi > 60 and ch24 < -1:
        contradictions.append({"type": "RSI_vs_PRICE", "bull": False,
                               "desc": f"RSI={rsi:.1f} 偏高但价格下跌"})
    elif rsi < 40 and ch24 > 1:
        contradictions.append({"type": "RSI_vs_PRICE", "bull": True,
                               "desc": f"RSI={rsi:.1f} 偏低但价格上涨"})

    if fund_rate > 0.01 and ch24 < -2:
        contradictions.append({"type": "FUND_vs_PRICE", "bull": True,
                               "desc": f"正资金费率但价格下跌=空头拥挤"})
    elif fund_rate < -0.01 and ch24 > 2:
        contradictions.append({"type": "FUND_vs_PRICE", "bull": False,
                               "desc": f"负资金费率但价格上涨=多头拥挤"})

    bull_count = sum(1 for c in contradictions if c.get("bull"))
    bear_count = len(contradictions) - bull_count

    if bull_count > bear_count:
        dominant = "BULL"
        conf = 0.50 + bull_count * 0.05
    elif bear_count > bull_count:
        dominant = "BEAR"
        conf = 0.50 + bear_count * 0.05
    else:
        dominant = "NEUTRAL"
        conf = 0.45

    return {
        "a0": {
            "dominant_force": dominant,
            "confidence": round(min(conf, 0.75), 3),
            "contradictions": contradictions,
        }
    }


def _fallback_research_simple(coin: str) -> Dict:
    """简易 fallback（仅返回 direction/confidence，不含 mkt 依赖）"""
    return {
        "direction": "HOLD",
        "confidence": 0.45,
        "summary": f"[fallback] {coin} 无可用研报数据",
    }


def _fallback_research(mkt: Dict) -> Dict:
    """A1 备用调研（无 API 时）"""
    coin = mkt.get("coin", "BTC")
    ch24 = mkt.get("change_24h", 0)
    fund_rate = mkt.get("funding_rate", 0)

    direction = "HOLD"
    conf = 0.45

    if fund_rate < -0.01:
        direction = "LONG"
        conf = 0.55
    elif fund_rate > 0.01:
        direction = "SHORT"
        conf = 0.55

    if abs(ch24) > 3:
        conf = min(conf + 0.05, 0.70)

    return {
        "direction": direction,
        "confidence": conf,
        "summary": f"[备用] {coin} 24h={ch24:+.2f}% 费率={fund_rate*100:+.2f}%",
    }


def a1_execute(mkt: Dict, memory: Dict, data: Dict) -> Dict[str, Any]:
    return execute(mkt, memory, data)
