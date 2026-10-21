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
# 18 中心已迁移 PostgreSQL，复用 39 模块统一 PG 辅助模块（FAIL-OPEN）
_DC_PG_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "39-金融语义蒸馏系统", "scripts",
)
if _DC_PG_DIR not in sys.path:
    sys.path.insert(0, _DC_PG_DIR)
import dc_pg

# SPEC v1.5: 实体别名表（SSoT，39-金融语义蒸馏系统接管维护）
_ALIASES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "entity_aliases.json")
try:
    with open(_ALIASES_PATH, "r", encoding="utf-8") as _f:
        ENTITY_ALIASES = json.load(_f)
except Exception:
    ENTITY_ALIASES = {}  # FAIL-OPEN: 别名表缺失时仅字母代号解析


def _resolve_symbol(message, candidates=None):
    """SPEC v1.5 统一币种解析: 中文别名(最长匹配优先) → 字母代号 → None."""
    if not message:
        return None
    # 1) 中文/英文别名匹配（最长优先，避免『以太坊』被『以太』截断）
    _alias_pairs = []
    for sym, aliases in ENTITY_ALIASES.items():
        if candidates is not None and sym not in candidates:
            continue
        for a in aliases:
            if a and a in message:
                _alias_pairs.append((len(a), sym))
    if _alias_pairs:
        _alias_pairs.sort(reverse=True)
        return _alias_pairs[0][1]
    # 2) 字母代号匹配（限定候选集合内）
    m = re.search(r"([A-Z]{2,10})", message.upper())
    if m:
        sym = m.group(1)
        if candidates is None or sym in candidates:
            return sym
    return None

# 数据源关键词 → source 映射（消息中出现关键词即命中）
SOURCE_KEYWORDS = [
    ("defillama", ["defi tvl", "tvl", "defillama"]),
    ("fear_greed", ["恐惧贪婪", "fear greed", "fear_greed"]),
    ("fear_greed_enhanced", ["恐惧贪婪指数增强", "增强恐惧贪婪"]),
    ("fred", ["fred", "美联储经济数据", "cpi", "ppi", "通胀", "联邦基金利率", "货币供应", "工业产出", "美元指数", "美债", "美股", "标普", "纳指", "纳斯达克"]),
    ("econ_calendar", ["非农", "nfp", "经济日历"]),
    ("coinglass", ["coinglass", "衍生品数据"]),
    ("deribit", ["deribit", "期权数据"]),
    ("long_short_ratio", ["多空比", "long short"]),
    ("stablecoin_transparency", ["稳定币", "stablecoin"]),
    ("blockchain_info", ["链上数据", "链上活跃"]),
    ("yfinance", ["金融行情", "yfinance", "黄金", "原油"]),
    ("ccxt", ["交易所行情", "行情", "价格", "什么价", "ccxt"]),
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


# fred 源关键词 → FRED 序列精确映射（修复：CPI 等查询误返源下最新一条无关序列，如 IR14260）
FRED_SERIES_KEYWORDS = [
    ("CPIAUCSL", ["cpi", "消费者价格", "通胀指数", "物价指数"]),
    ("PPIACO", ["ppi", "生产者价格"]),
    ("FEDFUNDS", ["联邦基金利率", "fed funds"]),
    ("M2NS", ["m2", "货币供应"]),
    ("WALCL", ["资产负债表", "walcl"]),
    ("INDPRO", ["工业产出", "工业生产"]),
    ("VIXCLS", ["vix", "恐慌指数"]),
    ("DGS10", ["美债", "10年", "十年期"]),
    ("DTWEXBGS", ["美元指数"]),
    ("SP500", ["标普", "美股", "美国股市"]),
    ("NASDAQCOM", ["纳指", "纳斯达克"]),
    ("DCOILWTICO", ["原油", "wti", "油价"]),
]


# 各数据源关键词 → 序列精确映射与默认序列（修复：多序列源误返最新一条无关记录）
SERIES_KEYWORDS = {
    "fred": FRED_SERIES_KEYWORDS,
    "econ_calendar": [
        ("nfp", ["非农", "nfp"]),
        ("cpi", ["cpi", "消费者价格"]),
        ("ppi", ["ppi", "生产者价格"]),
    ],
    "ccxt": [
        ("BTC/USDT", ["btc", "比特币"]),
    ],
    "yfinance": [
        ("^GSPC", ["标普", "美股", "美国股市"]),
        ("^IXIC", ["纳指", "纳斯达克"]),
        ("GC=F", ["黄金"]),
        ("CL=F", ["原油", "油价"]),
        ("BTC-USD", ["btc"]),
    ],
    "stablecoin_transparency": [
        ("tether_current", ["usdt", "tether"]),
        ("usdc_current", ["usdc"]),
        ("stablecoins_top_10", ["稳定币", "stablecoin", "整体", "前十"]),
    ],
    "defillama": [
        ("chains_summary", ["公链", "chains"]),
        ("all_protocols", ["tvl", "defi", "协议", "锁仓"]),
    ],
}
SERIES_DEFAULTS = {
    "ccxt": "BTC/USDT",
    "yfinance": "^GSPC",
    "stablecoin_transparency": "stablecoins_top_10",
    "defillama": "all_protocols",
}


def _resolve_series(src: str, message: str):
    m = message.lower()
    for series, kws in SERIES_KEYWORDS.get(src, []):
        if any(kw in m for kw in kws):
            return series
    return SERIES_DEFAULTS.get(src)


def _fetch_cpi_yoy():
    """从 19-DAL mm_metrics 读取 CPI 同比百分比（actual/forecast/previous，最新发布口径）"""
    import sqlite3 as _sq
    try:
        dal_db = os.path.normpath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "..",
            "19-数据访问层", "data", "dreambuddy_core.db"))
        if not os.path.exists(dal_db):
            return None
        conn = _sq.connect(f"file:{dal_db}?mode=ro", uri=True)
        out = {}
        for name in ("actual", "forecast", "previous"):
            row = conn.execute(
                "SELECT metric_value FROM mm_metrics "
                "WHERE sub_category='cpi' AND metric_name=? "
                "ORDER BY timestamp DESC LIMIT 1", (name,),
            ).fetchone()
            if row and row[0] is not None:
                out[name] = row[0]
        conn.close()
        return out if "actual" in out else None
    except Exception:
        return None


def exec_data_query(message: str):
    src = resolve_source(message)
    if not src:
        return {"success": True, "answer": "未能识别要查询的数据源，请指明具体数据（如 DeFi TVL、恐惧贪婪指数、CPI 等）", "data": None}
    fetch_params = {"source": src}
    series = _resolve_series(src, message)
    if series:
        fetch_params["sub_category"] = series
    ctx = get_l0().fetch_context("datacenter.record", fetch_params)
    if ctx.get("degraded"):
        if ctx["meta"].get("reason") == "source_missing":
            return {"success": True, "degraded": True, "answer": "数据获取中心数据库暂不可用", "data": None}
        return {"success": True, "degraded": True, "answer": f"查询失败: {ctx['meta'].get('error', '')}", "data": None}
    row = ctx["data"]
    if not row:
        return {"success": True, "answer": f"数据源 {src} 暂无记录", "data": None}
    metrics = row["metrics"]
    answer = f"{src}/{row['sub_category']} 最新数据（{row['timestamp']}）：{json.dumps(metrics, ensure_ascii=False)[:300] if metrics else '无指标'}"
    if fetch_params.get("sub_category") == "CPIAUCSL":
        yoy = _fetch_cpi_yoy()
        if yoy:
            idx_val = metrics.get("value") if isinstance(metrics, dict) else None
            answer = (
                f"美国CPI同比 {yoy.get('actual')}%"
                f"（预期 {yoy.get('forecast')}%，前值 {yoy.get('previous')}%）"
                f"；CPI指数水平 CPIAUCSL={idx_val}（1982-84=100，{row['timestamp']}）"
            )
    return {
        "success": True,
        "answer": answer,
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
    # SPEC v1.5: 别名表统一解析（中文别名优先），无币种时澄清追问
    symbol = _resolve_symbol(message, snap)
    if symbol is None:
        return {"success": True, "need_clarification": True,
                "answer": "请问您想查询哪个币种？（如：以太坊、BTC、黄金）", "data": None}
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
    """SPEC v1.5: 统一走别名表解析（在候选集合内匹配）。"""
    return _resolve_symbol(message, candidates)


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
    symbol = _extract_symbol(message, results)
    if symbol is None:
        return {"success": True, "need_clarification": True,
                "answer": "请问您想查询哪个币种？（如：以太坊、BTC、黄金）", "data": None}
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
    symbol = _extract_symbol(message, avail)
    if symbol is None:
        return {"success": True, "need_clarification": True,
                "answer": "请问您想查询哪个币种？（如：以太坊、BTC、黄金）", "data": None}
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


# ── L1 事件罗列服务 (39 SPEC v1.2 §9.7) ─────────────────────
_EVENT_TYPE_KEYWORDS = {
    "monetary_policy": ["货币政策", "降息", "加息", "利率", "美联储", "FOMC", "央行"],
    "crypto_regulation": ["监管", "牌照", "ETF", "SEC", "稳定币监管", "反洗钱"],
    "us_policy": ["美国政策", "白宫", "国会", "财政部", "制裁", "国债"],
    "us_data": ["经济数据", "非农", "CPI", "PPI", "GDP", "失业率", "PMI"],
    "geopolitics": ["地缘", "中东", "俄乌", "冲突", "军事"],
    "market": ["行情", "涨跌", "市场"],
    "project": ["项目", "融资", "上线", "合作"],
}
_EVENT_TYPE_DESC_L1 = {
    "monetary_policy": "货币政策", "crypto_regulation": "加密监管",
    "us_policy": "美国政策", "us_data": "美国经济数据",
    "geopolitics": "地缘政治", "market": "行情动态", "project": "项目动态",
}


def _match_event_type(message):
    """从用户消息匹配事件类型（多关键词命中取首个）。"""
    for etype, kws in _EVENT_TYPE_KEYWORDS.items():
        for kw in kws:
            if kw in (message or ""):
                return etype
    return None


def exec_event_listing(message):
    """L1 事件罗列: 按事件类型过滤快讯记录，时间倒序罗列（标题/时间/关联代币/情绪）。"""
    etype = _match_event_type(message)
    # PostgreSQL 查询（dc_pg 统一接口，FAIL-OPEN：异常返回空）
    rows = dc_pg.fetch_records("newsflash_%", limit=400, order_desc=True)
    # 解析并过滤
    items = []
    seen = set()
    for row in rows:
        ts = row.get("timestamp", "") or ""
        m = row.get("metrics") or {}
        if isinstance(m, str):
            try:
                m = json.loads(m)
            except Exception:
                continue
        if not isinstance(m, dict):
            continue
        row_type = m.get("od_event_type", "")
        if etype and row_type != etype:
            continue
        title_hash = m.get("od_title_hash", "")
        if title_hash in seen:
            continue
        seen.add(title_hash)
        desc = re.sub(r"<[^>]+>", "", m.get("description", "")).strip()
        if not desc:
            continue
        tickers = m.get("tickers_hit") or []
        if isinstance(tickers, str):
            try:
                tickers = json.loads(tickers)
            except Exception:
                tickers = []
        # 情绪（与 34 采集器同口径的简化规则）
        pos = sum(1 for w in ("上涨", "突破", "新高", "利好", "批准", "融资") if w in desc)
        neg = sum(1 for w in ("下跌", "暴跌", "利空", "制裁", "禁止", "黑客", "清算") if w in desc)
        sentiment = "positive" if pos > neg else ("negative" if neg > pos else "neutral")
        items.append({
            "time": (ts or "")[:16],
            "type": row_type,
            "summary": desc[:100],
            "tickers": tickers[:3],
            "sentiment": sentiment,
        })
        if len(items) >= 10:
            break
    if not items:
        return {"success": True, "answer": "近期未找到相关事件快讯", "data": []}
    type_desc = _EVENT_TYPE_DESC_L1.get(etype, "全部") if etype else "全部"
    lines = []
    for i, it in enumerate(items, 1):
        tick = f" | 关联: {','.join(it['tickers'])}" if it["tickers"] else ""
        lines.append(f"{i}. [{it['time']}] {it['summary']}{tick}（情绪:{it['sentiment']}）")
    answer = f"近期{type_desc}事件（按时间倒序，共 {len(items)} 条）：\n" + "\n".join(lines)
    # 层间钩子 (SPEC v1.3 §9.7): 基于罗列内容动态生成 L2 引导
    hint = None
    if etype:
        hint = (f"想了解{type_desc}事件的整体演变与量变趋势吗？"
                f"可问：{type_desc}事件怎么演变")
    else:
        hint = "想深入了解某类事件线的演变吗？可问：加密监管事件怎么演变"
    return {"success": True, "answer": answer, "next_layer_hint": hint,
            "data": {"event_type": etype, "items": items}}


# ── L2 事件线查询 (39 SPEC v1.2 §9.7): 消费 event_lines.json ──
_EVENT_LINES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..", "39-金融语义蒸馏系统", "event_lines.json",
)


def exec_event_line_query(message):
    """L2 事件线查询: 同主题事件聚合 + 时间标签 + 变化描述（观察性）。"""
    try:
        with open(_EVENT_LINES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"success": True, "degraded": True,
                "answer": "事件线数据暂不可用（尚未生成）", "data": None}
    lines = data.get("lines", [])
    if not lines:
        return {"success": True, "answer": "暂无事件线数据", "data": []}
    # 匹配主题（消息含主题关键词或主题名）
    matched = None
    for l in lines:
        if l["topic"] in (message or ""):
            matched = l
            break
    if matched is None:
        for l in lines:
            topic_kw = {
                "美联储利率": ("美联储", "利率", "加息", "降息"),
                "加密监管": ("监管", "SEC", "牌照"),
                "代币解锁": ("解锁", "锁仓"),
                "巨鲸动向": ("巨鲸", "大户"),
                "地缘冲突": ("地缘", "中东", "俄乌"),
                "ETF 动态": ("ETF",),
            }
            if any(k in (message or "") for k in topic_kw.get(l["topic"], ())):
                matched = l
                break
    if matched:
        l = matched
        items = "\n".join(
            f"  · [{it['time']}] {it['summary']}" for it in l["recent_items"])
        answer = (
            f"【{l['topic']}】事件线：共 {l['event_count']} 条事件，"
            f"时间跨度 {l['span_hours']}h（{l['time_start']} ~ {l['time_end']}）\n"
            f"变化观察：频次{l['freq_trend']}，{l['sentiment_trend']}"
            f"（前半段情绪 {l['sentiment_early']} → 后半段 {l['sentiment_late']}）\n"
            f"量变观察：{l.get('quantity_signal', '量变平稳')}"
            f"（末窗口/均值 {l.get('quantity_intensity', 0)} 倍，z={l.get('quantity_z', 0)}，"
            f"窗口分布 {l.get('quantity_distribution', [])}）\n"
            f"关联标的：{','.join(l['top_tickers']) or '无'}\n"
            f"近期事件：\n{items}"
        )
        # 层间钩子 (SPEC v1.3 §9.7): 信号驱动优先，量变信号时升级为精准提示
        hint = None
        qsig = l.get("quantity_signal", "")
        if "加速积累" in qsig:
            hint = (f"【{l['topic']}】量变正在加速积累，是否深入观察窗口分布与情绪变化？"
                    f"（L3 多因子综合即将上线）")
        elif "温和积累" in qsig or "消退" in qsig:
            hint = f"想看【{l['topic']}】的量变窗口分布详情吗？可追问：{l['topic']}量变分布"
        else:
            hint = f"想结合市场指标看【{l['topic']}】的综合状态吗？（L3 上线后可用）"
        return {"success": True, "answer": answer, "next_layer_hint": hint, "data": l}
    # 未匹配主题：罗列全部事件线概览
    overview = "\n".join(
        f"  · {l['topic']}: {l['event_count']} 事件, 跨度 {l['span_hours']}h, "
        f"频次{l['freq_trend']}, {l['sentiment_trend']}" for l in lines)
    return {"success": True,
            "answer": f"当前事件线概览（可追问具体主题如『加密监管事件怎么演变』）：\n{overview}",
            "data": {"lines": [{"topic": l["topic"], "count": l["event_count"]} for l in lines]}}


def exec_price_query(message):
    """价格查询: 经 L0 直连 OKX API 获取实时价格，失败降级回查 18 中心。"""
    # SPEC v1.5: 别名表统一解析，无币种时澄清追问（不再静默默认 BTC）
    symbol = _resolve_symbol(message)
    if symbol is None:
        return {"success": True, "need_clarification": True,
                "answer": "请问您想查询哪个币种的价格？（如：以太坊、BTC、黄金）", "data": None}
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
        elif intent == "event_listing":
            result = exec_event_listing(message)
        elif intent == "event_line_query":
            result = exec_event_line_query(message)
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
