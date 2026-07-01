"""
A1 深度调研节点
调用 A1 Feed 获取深度调研报告，结合 A0 矛盾检测

SKILL.md 调用路径: experiments/ab-trading/core/nodes/a1_research
"""

from typing import Dict, Any
import json, time, requests


def execute(mkt: Dict, memory: Dict, data: Dict) -> Dict[str, Any]:
    """
    执行 A1 深度调研（含 A0 矛盾检测）

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
                "a0": {...},  # A0 矛盾数据
                "a1_report": {...}  # A1 调研报告
            }
        }
    """
    coin  = mkt.get("coin", "BTC")
    price = mkt.get("price", 0)
    ch24  = mkt.get("change_24h", 0)

    reasoning = []
    a0_data = {}
    a1_report = {}

    # ── Step 1: A0 矛盾检测（内置）──────────────────────────────────────
    a0_result = _detect_contradictions(mkt, memory, data)
    a0_data = a0_result["a0"]
    reasoning.append(f"[A0内置] 矛盾检测: dominant={a0_data.get('dominant_force','NEUTRAL')}")

    # ── Step 2: A1 深度调研（调用 Feed API）────────────────────────────
    try:
        resp = requests.get(
            "http://49.233.123.96:3456/feed",
            params={"coin": coin, "limit": 3},
            timeout=5
        )
        if resp.status_code == 200:
            feed = resp.json()
            a1_report = feed if isinstance(feed, dict) else {"summary": str(feed)[:200]}
            reasoning.append(f"[A1 Feed] 获取到 {len(a1_report)} 条调研报告")
        else:
            reasoning.append(f"[A1 Feed] API 返回 {resp.status_code}，使用备用逻辑")
            a1_report = _fallback_research(mkt)
    except Exception as e:
        reasoning.append(f"[A1 Feed] 请求失败: {str(e)[:50]}，使用备用逻辑")
        a1_report = _fallback_research(mkt)

    # ── Step 3: 融合 A0 + A1 ───────────────────────────────────────────
    a1_dir = a1_report.get("direction", "HOLD")
    a1_conf = a1_report.get("confidence", 0.45)

    a0_dir = "LONG" if a0_data.get("dominant_force") == "BULL" else \
             "SHORT" if a0_data.get("dominant_force") == "BEAR" else "HOLD"
    a0_conf = a0_data.get("confidence", 0.45)

    # 融合逻辑
    if a0_dir != "HOLD" and a1_dir != "HOLD":
        if a0_dir == a1_dir:
            merged_dir = a0_dir
            merged_conf = round((a0_conf + a1_conf) / 2 + 0.03, 3)  # 同向加成
            reasoning.append(f"[融合] A0({a0_dir}) + A1({a1_dir}) 同向，置信度加成")
        else:
            merged_dir = a0_dir if a0_conf > a1_conf else a1_dir
            merged_conf = round((a0_conf + a1_conf) / 2 - 0.05, 3)  # 冲突降权
            reasoning.append(f"[融合] ⚠️ A0({a0_dir}) vs A1({a1_dir}) 冲突，降低置信度")
    elif a1_dir != "HOLD":
        merged_dir = a1_dir
        merged_conf = a1_conf
        reasoning.append(f"[融合] 使用 A1 结论: {a1_dir}")
    else:
        merged_dir = a0_dir
        merged_conf = a0_conf
        reasoning.append(f"[融合] A1=HOLD，使用 A0 结论: {a0_dir}")

    merged_conf = max(min(merged_conf, 0.90), 0.25)

    return {
        "node": "A1_调研(含A0)",
        "direction": merged_dir,
        "confidence": round(merged_conf, 3),
        "rationale": reasoning,
        "data": {
            "a0": a0_data,
            "a1_report": a1_report,
        }
    }


def _detect_contradictions(mkt: Dict, memory: Dict, data: Dict) -> Dict:
    """A0 矛盾检测：识别多空信号矛盾"""
    rsi = mkt.get("rsi14", 50)
    ch24 = mkt.get("change_24h", 0)
    fund_rate = mkt.get("funding_rate", 0)

    contradictions = []

    # RSI vs 涨跌矛盾
    if rsi > 60 and ch24 < -1:
        contradictions.append({"type": "RSI_vs_PRICE", "bull": False,
                               "desc": f"RSI={rsi:.1f} 偏高但价格下跌"})
    elif rsi < 40 and ch24 > 1:
        contradictions.append({"type": "RSI_vs_PRICE", "bull": True,
                               "desc": f"RSI={rsi:.1f} 偏低但价格上涨"})

    # 资金费率 vs 涨跌矛盾
    if fund_rate > 0.01 and ch24 < -2:
        contradictions.append({"type": "FUND_vs_PRICE", "bull": True,
                               "desc": f"正资金费率但价格下跌=空头拥挤"})
    elif fund_rate < -0.01 and ch24 > 2:
        contradictions.append({"type": "FUND_vs_PRICE", "bull": False,
                               "desc": f"负资金费率但价格上涨=多头拥挤"})

    # 判断主导力量
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


def _fallback_research(mkt: Dict) -> Dict:
    """A1 备用调研（无 API 时）"""
    coin = mkt.get("coin", "BTC")
    ch24 = mkt.get("change_24h", 0)
    fund_rate = mkt.get("funding_rate", 0)

    direction = "HOLD"
    conf = 0.45

    if fund_rate < -0.01:  # 负费率 = 空头付多头
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
