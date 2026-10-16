# -*- coding: utf-8 -*-
"""数据查询执行脚本 (SPEC v0.7 执行闭环 / L0 收敛 P1.3)。

由前端 /api/data/query 路由调用（execFile 模式，同 market_data_query.py）。
输入: JSON {intent, message}
输出: JSON {success, intent, answer, data}

- 十意图的数据访问统一经 L0 `L0Foundation.fetch_context(scope)`（见 34 系统 core/l0_foundation.py）；
- data_query: 从消息解析数据源关键词 → L0 直查 18-数据获取中心 data_center.db 最新记录
- data_insight: 匹配变化模式知识库 → 返回金融市场含义解读（纯知识，无数据访问）
- 本层只保留: 问法解析、业务判空、答案格式化；数据源路径/读取/降级全部在 L0
- FAIL-OPEN: 任何异常返回 degraded，不抛出
"""
import json
import os
import re
import sys

# 接入 34 系统 L0（core/l0_foundation.py，与本脚本同处项目根下两级）
_TRAINING_SYS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "34-前端应用训练系统",
)
if _TRAINING_SYS_DIR not in sys.path:
    sys.path.insert(0, _TRAINING_SYS_DIR)
from core.l0_foundation import get_l0

# 数据源关键词 → source 映射（消息中出现关键词即命中）
SOURCE_KEYWORDS = [
    ("defillama", ["defi tvl", "tvl", "defillama"]),
    ("fear_greed", ["恐惧贪婪", "fear greed", "fear_greed"]),
    ("fear_greed_enhanced", ["恐惧贪婪指数增强", "增强恐惧贪婪"]),
    ("fred", ["fred", "美联储经济数据", "cpi", "非农"]),
    ("coinglass", ["coinglass", "衍生品数据"]),
    ("deribit", ["deribit", "期权数据"]),
    ("long_short_ratio", ["多空比", "long short"]),
    ("stablecoin_transparency", ["稳定币", "stablecoin"]),
    ("blockchain_info", ["链上数据", "链上活跃"]),
    ("ccxt", ["交易所行情", "行情", "价格", "什么价", "ccxt"]),
    ("yfinance", ["金融行情", "yfinance", "美股", "标普"]),
    ("gdelt", ["gdelt", "全球新闻事件"]),
    ("theblockbeats_dataview", ["律动", "blockbeats"]),
    ("odaily_newsflash", ["odaily", "快讯"]),
    ("panewslab", ["panews"]),
]

# 变化模式知识库（与 34 系统 data_insight_collector 对齐）
INSIGHT_KNOWLEDGE = [
    ("CPI", ["超预期上行", "超预期", "高于预期"], "通胀超预期 → 加息预期升温 → 利好美元、压制风险资产，加密市场承压"),
    ("CPI", ["低于预期", "不及预期"], "通胀降温 → 降息预期升温 → 风险资产受益，加密市场偏多"),
    ("恐惧贪婪指数", ["极度贪婪", "转向贪婪"], "市场情绪过热 → 追高风险加大，警惕回调（逆向信号）"),
    ("恐惧贪婪指数", ["极度恐惧", "转向恐惧"], "市场恐慌 → 历史上常为阶段性底部区域（逆向机会信号）"),
    ("稳定币", ["增长", "上升", "流入"], "场内资金流入 → 链上购买力增强，中期偏多信号"),
    ("稳定币", ["下降", "减少", "撤离"], "资金撤离 → 链上流动性收缩，中期偏空信号"),
    ("多空比", ["多头拥挤", "多头过度"], "多头拥挤 → 轧空动能不足，警惕多头踩踏下行"),
    ("多空比", ["空头拥挤", "空头过度"], "空头拥挤 → 轧空反弹风险上升"),
    ("DeFi TVL", ["上升", "增长"], "链上活跃度提升 → 链上经济扩张，生态代币偏多"),
    ("DeFi TVL", ["下降", "减少"], "资金撤离链上协议 → 生态收缩，偏空信号"),
    ("非农", ["强劲", "超预期"], "就业强劲 → 经济过热担忧 → 加息预期升温，风险资产承压"),
    ("非农", ["不及预期", "走弱"], "就业走弱 → 衰退担忧与降息预期并存，市场波动加大"),
    ("资金费率", ["高正费率", "正费率"], "多头付费拥挤 → 杠杆过热，警惕多头清算连锁"),
    ("资金费率", ["负费率"], "空头付费拥挤 → 空头杠杆过热，轧空反弹概率上升"),
    ("美联储", ["鸽派"], "鸽派 → 流动性宽松预期 → 风险资产受益"),
    ("美联储", ["鹰派"], "鹰派 → 流动性收紧预期 → 风险资产承压"),
    ("期权", ["看跌激增", "看跌"], "对冲需求上升 → 机构防御姿态，警惕下行"),
]


def resolve_source(message: str):
    m = message.lower()
    for src, keywords in SOURCE_KEYWORDS:
        for kw in keywords:
            if kw in m:
                return src
    return None


def exec_data_query(message: str):
    src = resolve_source(message)
    if not src:
        return {"success": True, "answer": "未能识别要查询的数据源，请指明具体数据（如 DeFi TVL、恐惧贪婪指数、CPI 等）", "data": None}
    ctx = get_l0().fetch_context("datacenter.record", {"source": src})
    if ctx.get("degraded"):
        if ctx["meta"].get("reason") == "source_missing":
            return {"success": True, "degraded": True, "answer": "数据获取中心数据库暂不可用", "data": None}
        return {"success": True, "degraded": True, "answer": f"查询失败: {ctx['meta'].get('error', '')}", "data": None}
    row = ctx["data"]
    if not row:
        return {"success": True, "answer": f"数据源 {src} 暂无记录", "data": None}
    metrics = row["metrics"]
    return {
        "success": True,
        "answer": f"{src} 最新数据（{row['timestamp']}）：{json.dumps(metrics, ensure_ascii=False)[:300] if metrics else '无指标'}",
        "data": {
            "source": row["source"],
            "category": row["category"],
            "sub_category": row["sub_category"],
            "timestamp": row["timestamp"],
            "metrics": metrics,
        },
    }


def exec_data_insight(message: str):
    for metric, patterns, meaning in INSIGHT_KNOWLEDGE:
        if metric in message:
            for p in patterns:
                if p in message:
                    return {"success": True, "answer": f"{metric}{p}的市场含义：{meaning}", "data": {"metric": metric, "pattern": p, "meaning": meaning}}
    return {"success": True, "answer": "暂无该变化模式的解读知识，可尝试询问 CPI、恐惧贪婪指数、稳定币、多空比、资金费率等指标的变化含义", "data": None}


_DIM_DESC = {"C1": "资金面", "C2": "情绪面", "C3": "技术面", "C4": "宏观", "C6": "时序", "C7": "隐性", "C8": "衍生维度"}
_DIR_DESC = {"long": "看多", "short": "看空", "neutral": "中性"}


def exec_contradiction_insight(message):
    """链路 A: 经 L0 解析矛盾日志，返回各维度矛盾方向/强度解读。"""
    ctx = get_l0().fetch_context("evolution.contradiction")
    if ctx.get("degraded"):
        if ctx["meta"].get("reason") == "source_missing":
            answer = "自进化系统矛盾日志暂不可用"
        else:
            answer = f"日志读取失败: {ctx['meta'].get('error', '')}"
        return {"success": True, "degraded": True, "answer": answer, "data": None}
    payload = ctx["data"]
    if not payload:
        return {"success": True, "answer": "当前日志中暂无矛盾维度记录", "data": None}
    dims = {d: (v["direction"], v["strength"]) for d, v in payload["dims"].items()}
    parts = []
    for d in sorted(dims.keys()):
        direction, strength = dims[d]
        parts.append(f"{_DIM_DESC.get(d, d)}({_DIR_DESC.get(direction, direction)}, 强度{strength:.2f})")
    # 矛盾/一致判断
    dirs = set(v[0] for v in dims.values())
    state = "各维度方向存在分歧（矛盾状态）" if len(dirs) > 1 else "各维度方向一致"
    return {
        "success": True,
        "answer": f"当前矛盾状态：{state}。各维度：{'；'.join(parts)}",
        "data": {"dims": {d: {"direction": dims[d][0], "strength": dims[d][1]} for d in dims}, "state": state},
    }


def exec_path_insight(message):
    """链路 B: 经 L0 读快照，返回币种多维预测交汇与最小阻力路径。"""
    ctx = get_l0().fetch_context("evolution.snapshot")
    if ctx.get("degraded"):
        if ctx["meta"].get("reason") == "source_missing":
            answer = "自进化系统快照暂不可用"
        else:
            answer = f"快照读取失败: {ctx['meta'].get('error', '')}"
        return {"success": True, "degraded": True, "answer": answer, "data": None}
    snap = ctx["data"]
    if not snap:
        return {"success": True, "answer": "快照中暂无币种数据", "data": None}
    # 从消息解析币种（大写字母数字组合，默认 BTC）
    m = re.search(r"([A-Z]{2,10})", message.upper())
    symbol = m.group(1) if m and m.group(1) in snap else "BTC"
    if symbol not in snap:
        # 取第一个有维度预测的币种
        for k, v in snap.items():
            if isinstance(v, dict) and v.get("dimension_predictions"):
                symbol = k
                break
    info = snap.get(symbol) or {}
    dim_pred = info.get("dimension_predictions") or {}
    action = info.get("action", "neutral")
    if not dim_pred:
        return {"success": True, "answer": f"{symbol} 暂无维度预测数据", "data": None}
    votes = list(dim_pred.values())
    agree = sum(1 for v in votes if v == action)
    summary = "/".join(f"{_DIM_DESC.get(k, k)}:{_DIR_DESC.get(v, v)}" for k, v in dim_pred.items())
    return {
        "success": True,
        "answer": f"{symbol} 多维交汇：{summary} → 最小阻力路径 {_DIR_DESC.get(action, action)}（{agree}/{len(votes)} 维度一致）",
        "data": {
            "symbol": symbol,
            "dimension_predictions": dim_pred,
            "action": action,
            "level0_dstar": info.get("level0_dstar", ""),
            "agree_ratio": f"{agree}/{len(votes)}",
        },
    }


_YJ_DIR_DESC = {"UP": "看涨", "DOWN": "看跌", "NEUTRAL": "中性"}
_YJ_ASSET_DESC = {"crypto_usdt": "加密货币", "us_stock": "美股", "precious_metal": "贵金属"}


def _extract_symbol(message, candidates):
    """从消息中解析币种（在候选集合内匹配）。"""
    m = re.search(r"([A-Z]{2,10})", message.upper())
    if m and m.group(1) in candidates:
        return m.group(1)
    return None


def exec_technical_analysis(message):
    """技术指标推理: 经 L0 查 BCRM2 汇总返回方向/置信度/卦象。"""
    ctx = get_l0().fetch_context("yijing.bcrm2")
    if ctx.get("degraded"):
        if ctx["meta"].get("reason") == "source_missing":
            answer = "BCRM2 汇总数据暂不可用"
        else:
            answer = f"汇总读取失败: {ctx['meta'].get('error', '')}"
        return {"success": True, "degraded": True, "answer": answer, "data": None}
    results = ctx["data"]
    if not results:
        return {"success": True, "answer": "BCRM2 汇总中暂无币种推理结果", "data": None}
    symbol = _extract_symbol(message, results) or "BTC"
    if symbol not in results:
        symbol = next(iter(results))
    info = results[symbol] or {}
    direction = info.get("direction", "NEUTRAL")
    confidence = info.get("confidence", 0.0)
    hexagram = info.get("hexagram", "")
    return {
        "success": True,
        "answer": f"{symbol} 技术面推理：方向{_YJ_DIR_DESC.get(direction, direction)}，置信度{confidence:.2f}，卦象{hexagram or '无'}",
        "data": {"symbol": symbol, "direction": direction, "confidence": confidence, "hexagram": hexagram},
    }


def exec_fundamental_valuation(message):
    """单币种估值: 经 L0 查 BDSM 快照返回评分/等级/阶段/估值百分位。"""
    ctx = get_l0().fetch_context("yijing.bdsm")
    if ctx.get("degraded"):
        if ctx["meta"].get("reason") == "source_missing":
            answer = "BDSM 快照目录暂不可用"
        else:
            answer = f"快照读取失败: {ctx['meta'].get('error', '')}"
        return {"success": True, "degraded": True, "answer": answer, "data": None}
    d = ctx["data"]
    if not d:
        return {"success": True, "answer": "暂无 BDSM 快照", "data": None}
    coins = (d or {}).get("coins") or {}
    avail = {k: v for k, v in coins.items() if isinstance(v, dict) and v.get("available")}
    if not avail:
        return {"success": True, "answer": "快照中暂无可用币种估值数据", "data": None}
    symbol = _extract_symbol(message, avail) or "BTC"
    if symbol not in avail:
        symbol = next(iter(avail))
    info = avail[symbol] or {}
    score = info.get("score", 0.0)
    rank = info.get("rank", "")
    phase = info.get("phase", "")
    pct = info.get("valuation_percentile", 0.0)
    return {
        "success": True,
        "answer": f"{symbol} 基本面估值：评分{score:.2f}，等级{rank or '无'}，阶段{phase or '无'}，估值百分位{pct:.0f}",
        "data": {"symbol": symbol, "score": score, "rank": rank, "phase": phase, "valuation_percentile": pct},
    }


def exec_asset_class_trend(message):
    """跨资产趋势: 经 L0 查战略层影子日志返回三资产类别状态。"""
    ctx = get_l0().fetch_context("yijing.strategic")
    if ctx.get("degraded"):
        if ctx["meta"].get("reason") == "source_missing":
            answer = "交易日志目录暂不可用"
        else:
            answer = f"日志读取失败: {ctx['meta'].get('error', '')}"
        return {"success": True, "degraded": True, "answer": answer, "data": None}
    if ctx["data"] is None:
        # meta.log_file 存在表示「有日志但无战略层记录」，否则为「无日志文件」
        answer = "日志中暂无战略层跨资产状态" if ctx["meta"].get("log_file") else "暂无交易日志"
        return {"success": True, "answer": answer, "data": None}
    asset_state = ctx["data"]["assets"]
    parts = [f"{_YJ_ASSET_DESC.get(a, a)}:{v}" for a, v in sorted(asset_state.items())]
    return {
        "success": True,
        "answer": f"跨资产当前状态：{'；'.join(parts)}",
        "data": {"assets": asset_state},
    }


_SCORE_DESC = {
    "surprise": "意外度",
    "priced_in": "定价度",
    "real_rate": "实际利率",
    "resilience": "韧性",
    "cross_asset": "跨资产",
    "news": "新闻",
}


def exec_event_analysis(message):
    """金融事件分析: 经 L0 查实时事件驱动状态返回六维评分解读。"""
    ctx = get_l0().fetch_context("event.state")
    if ctx.get("degraded"):
        if ctx["meta"].get("reason") == "source_missing":
            answer = "事件驱动状态数据暂不可用"
        else:
            answer = f"状态读取失败: {ctx['meta'].get('error', '')}"
        return {"success": True, "degraded": True, "answer": answer, "data": None}
    state = ctx["data"]
    if not state:
        return {"success": True, "answer": "暂无事件驱动信号数据", "data": None}
    sig = (state or {}).get("signal") or {}
    event_type = sig.get("event_type", "none")
    event_phase = sig.get("event_phase", "")
    signal_dir = sig.get("signal", "neutral")
    strength = sig.get("strength", 0.0)
    confidence = sig.get("confidence", 0.0)
    reason = sig.get("reason", "")
    guidance = sig.get("forward_guidance", "")
    scores = sig.get("scores") or {}
    score_parts = [f"{_SCORE_DESC.get(k, k)}{v:.2f}" for k, v in scores.items()]
    answer = (
        f"当前事件分析：类型{event_type}，阶段{event_phase}，"
        f"信号{signal_dir}（强度{strength:.1f}，置信度{confidence:.1f}）。"
        f"六维评分：{'、'.join(score_parts)}。结论：{reason}"
    )
    if guidance and guidance != "neutral":
        answer += f"（前瞻指引：{guidance}）"
    return {
        "success": True,
        "answer": answer,
        "data": {
            "event_type": event_type,
            "event_phase": event_phase,
            "signal": signal_dir,
            "strength": strength,
            "confidence": confidence,
            "scores": scores,
            "reason": reason,
            "forward_guidance": guidance,
            "updated_at": (state or {}).get("updated_at", ""),
        },
    }


def settle_to_cognitive(intent, message, result):
    """沉淀分流入口 (SPEC v1.0 §3.5): 成功→案例库；有价值的探索发现→认知系统。

    P1.3 起实现上收至 L0（core.l0_foundation.L0Foundation.settle），行为不变，FAIL-OPEN。
    """
    get_l0().settle(result, {"intent": intent, "message": message})


_RISK_STATE_DESC = {"IDLE": "待命", "ARMED": "已武装", "TRIGGERED": "已触发", "CLOSED": "已平仓"}


def exec_risk_control(message):
    """调控风控: 经 L0 查 16-调控系统日志返回持仓风控状态。"""
    ctx = get_l0().fetch_context("riskcontrol.trailing")
    if ctx.get("degraded"):
        if ctx["meta"].get("reason") == "source_missing":
            answer = "调控系统日志暂不可用"
        else:
            answer = f"日志读取失败: {ctx['meta'].get('error', '')}"
        return {"success": True, "degraded": True, "answer": answer, "data": None}
    if ctx["data"] is None:
        answer = "日志中暂无风控评估记录" if ctx["meta"].get("log_file") else "暂无调控系统日志"
        return {"success": True, "answer": answer, "data": None}
    latest = ctx["data"]["positions"]
    parts = [f"{_RISK_STATE_DESC.get(k, k)}{v}" for k, v in latest.items() if k in _RISK_STATE_DESC]
    answer = (
        f"当前风控状态：总持仓{latest['total']}，{'、'.join(parts)}，"
        f"历史触发累计{latest['history_triggered']}次"
    )
    return {"success": True, "answer": answer, "data": {"positions": latest}}


def exec_price_query(message):
    """价格查询: 经 L0 直连 OKX API 获取实时价格，失败降级回查 18 中心。"""
    m = re.search(r"([A-Z]{2,10})", message.upper())
    symbol = m.group(1) if m else "BTC"
    inst_id = f"{symbol}-USDT"
    ctx = get_l0().fetch_context("market.ticker", {"symbol": symbol})
    t = None if ctx.get("degraded") else ctx["data"]
    if t:
        last = t.get("last", "")
        open24h = t.get("open24h", "")
        high = t.get("high24h", "")
        low = t.get("low24h", "")
        try:
            chg = (float(last) - float(open24h)) / float(open24h) * 100 if open24h else 0.0
        except Exception:
            chg = 0.0
        sign = "+" if chg >= 0 else ""
        return {
            "success": True,
            "answer": (
                f"{symbol} 实时价格（OKX {inst_id}）：{last} USDT，"
                f"24h涨跌 {sign}{chg:.2f}%，24h最高 {high}，最低 {low}"
            ),
            "data": {
                "symbol": symbol, "inst_id": inst_id, "last": last,
                "open24h": open24h, "high24h": high, "low24h": low,
                "change_pct": round(chg, 2), "source": "okx",
            },
        }
    # 降级: 回查 18 中心数据库
    fallback = exec_data_query(message)
    if fallback.get("data"):
        fallback["answer"] = f"（OKX 实时接口不可用，降级为缓存数据）{fallback.get('answer', '')}"
    return fallback


def main():
    # 优先从命令行参数读取（execFile 不支持 stdin input），其次 stdin
    try:
        if len(sys.argv) > 1:
            req = json.loads(sys.argv[1])
        else:
            req = json.loads(sys.stdin.read() or "{}")
    except Exception:
        req = {}
    intent = req.get("intent", "")
    message = req.get("message", "")
    try:
        if intent == "data_query":
            result = exec_data_query(message)
        elif intent == "data_insight":
            result = exec_data_insight(message)
        elif intent == "contradiction_insight":
            result = exec_contradiction_insight(message)
        elif intent == "path_insight":
            result = exec_path_insight(message)
        elif intent == "technical_analysis":
            result = exec_technical_analysis(message)
        elif intent == "fundamental_valuation":
            result = exec_fundamental_valuation(message)
        elif intent == "asset_class_trend":
            result = exec_asset_class_trend(message)
        elif intent == "event_analysis":
            result = exec_event_analysis(message)
        elif intent == "risk_control":
            result = exec_risk_control(message)
        elif intent == "price_query":
            result = exec_price_query(message)
        else:
            result = {"success": True, "answer": "该意图暂不支持执行闭环", "data": None}
    except Exception as e:
        result = {"success": True, "degraded": True, "answer": f"执行异常: {e}", "data": None}
    result["intent"] = intent
    # settle 沉淀链路: 执行结果回写认知系统 (FAIL-OPEN，不阻塞返回)
    settle_to_cognitive(intent, message, result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
