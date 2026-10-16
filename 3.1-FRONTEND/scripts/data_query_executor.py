# -*- coding: utf-8 -*-
"""数据查询执行脚本 (SPEC v0.7 执行闭环)。

由前端 /api/data/query 路由调用（execFile 模式，同 market_data_query.py）。
输入: JSON {intent, message}
输出: JSON {success, intent, answer, data}

- data_query: 从消息解析数据源关键词 → 直查 18-数据获取中心 data_center.db 最新记录
- data_insight: 匹配变化模式知识库 → 返回金融市场含义解读
- FAIL-OPEN: 任何异常返回 degraded，不抛出
"""
import glob
import json
import os
import re
import sqlite3
import sys

DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "18-数据获取中心", "data_center.db",
)

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
    if not os.path.exists(DB_PATH):
        return {"success": True, "degraded": True, "answer": "数据获取中心数据库暂不可用", "data": None}
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT source, category, sub_category, timestamp, metrics, events "
            "FROM records WHERE source = ? ORDER BY id DESC LIMIT 1", (src,)
        ).fetchone()
        conn.close()
    except Exception as e:
        return {"success": True, "degraded": True, "answer": f"查询失败: {e}", "data": None}
    if not row:
        return {"success": True, "answer": f"数据源 {src} 暂无记录", "data": None}
    metrics = None
    try:
        metrics = json.loads(row["metrics"]) if row["metrics"] else None
    except Exception:
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


EVOLUTION_LOG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "23-四层闭环自进化交易架构", "dreambuddy_evolution", "logs", "evolution_pipeline.log",
)
EVOLUTION_SNAPSHOT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "23-四层闭环自进化交易架构", "dreambuddy_evolution", "gene_data", "evolution_snapshots.json",
)

_DIM_DESC = {"C1": "资金面", "C2": "情绪面", "C3": "技术面", "C4": "宏观", "C6": "时序", "C7": "隐性", "C8": "衍生维度"}
_DIR_DESC = {"long": "看多", "short": "看空", "neutral": "中性"}


def exec_contradiction_insight(message):
    """链路 A: 解析矛盾日志，返回各维度矛盾方向/强度解读。"""
    if not os.path.exists(EVOLUTION_LOG):
        return {"success": True, "degraded": True, "answer": "自进化系统矛盾日志暂不可用", "data": None}
    try:
        with open(EVOLUTION_LOG, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[-3000:]
    except Exception as e:
        return {"success": True, "degraded": True, "answer": f"日志读取失败: {e}", "data": None}
    pat = re.compile(r"\[Contradiction\] dim=(C\d) dir=(\w+) strength=([0-9.]+)")
    dims = {}
    for line in lines:
        m = pat.search(line)
        if m:
            dims[m.group(1)] = (m.group(2), float(m.group(3)))
    if not dims:
        return {"success": True, "answer": "当前日志中暂无矛盾维度记录", "data": None}
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
    """链路 B: 解析快照，返回币种多维预测交汇与最小阻力路径。"""
    if not os.path.exists(EVOLUTION_SNAPSHOT):
        return {"success": True, "degraded": True, "answer": "自进化系统快照暂不可用", "data": None}
    try:
        with open(EVOLUTION_SNAPSHOT, encoding="utf-8") as f:
            snap = json.load(f)
    except Exception as e:
        return {"success": True, "degraded": True, "answer": f"快照读取失败: {e}", "data": None}
    if not isinstance(snap, dict) or not snap:
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


BCRM2_SUMMARY = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "11-易经推理系统", "data", "bcrm2", "bcrm2_hourly_summary.json",
)
BDSM_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "11-易经推理系统", ".workbuddy", "bdsm",
)
TRADER_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "11-易经推理系统", "data", "polling_trader",
)

_YJ_DIR_DESC = {"UP": "看涨", "DOWN": "看跌", "NEUTRAL": "中性"}
_YJ_ASSET_DESC = {"crypto_usdt": "加密货币", "us_stock": "美股", "precious_metal": "贵金属"}


def _extract_symbol(message, candidates):
    """从消息中解析币种（在候选集合内匹配）。"""
    m = re.search(r"([A-Z]{2,10})", message.upper())
    if m and m.group(1) in candidates:
        return m.group(1)
    return None


def exec_technical_analysis(message):
    """技术指标推理: 查 BCRM2 汇总返回方向/置信度/卦象。"""
    if not os.path.exists(BCRM2_SUMMARY):
        return {"success": True, "degraded": True, "answer": "BCRM2 汇总数据暂不可用", "data": None}
    try:
        with open(BCRM2_SUMMARY, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        return {"success": True, "degraded": True, "answer": f"汇总读取失败: {e}", "data": None}
    results = (d or {}).get("results") or {}
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
    """单币种估值: 查 BDSM 快照返回评分/等级/阶段/估值百分位。"""
    if not os.path.isdir(BDSM_DIR):
        return {"success": True, "degraded": True, "answer": "BDSM 快照目录暂不可用", "data": None}
    files = sorted(glob.glob(os.path.join(BDSM_DIR, "bdsm_snapshot_*.json")))
    if not files:
        return {"success": True, "answer": "暂无 BDSM 快照", "data": None}
    try:
        with open(files[-1], encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        return {"success": True, "degraded": True, "answer": f"快照读取失败: {e}", "data": None}
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
    """跨资产趋势: 查战略层影子日志返回三资产类别状态。"""
    if not os.path.isdir(TRADER_DIR):
        return {"success": True, "degraded": True, "answer": "交易日志目录暂不可用", "data": None}
    files = sorted(glob.glob(os.path.join(TRADER_DIR, "trader_*.jsonl")))
    if not files:
        return {"success": True, "answer": "暂无交易日志", "data": None}
    try:
        with open(files[-1], encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[-2000:]
    except Exception as e:
        return {"success": True, "degraded": True, "answer": f"日志读取失败: {e}", "data": None}
    asset_state = {}
    veto_pat = re.compile(r"dimension_veto \| (.+?)$")
    for line in lines:
        if "[战略层影子]" not in line or "dimension_veto" not in line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        m = veto_pat.search(rec.get("msg", ""))
        if not m:
            continue
        for part in m.group(1).split("|"):
            kv = part.strip().split("=", 1)
            if len(kv) == 2 and kv[0] in _YJ_ASSET_DESC:
                asset_state[kv[0]] = kv[1].strip()
    if not asset_state:
        return {"success": True, "answer": "日志中暂无战略层跨资产状态", "data": None}
    parts = [f"{_YJ_ASSET_DESC.get(a, a)}:{v}" for a, v in sorted(asset_state.items())]
    return {
        "success": True,
        "answer": f"跨资产当前状态：{'；'.join(parts)}",
        "data": {"assets": asset_state},
    }


EVENT_STATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "11-易经推理系统", "data", "event_driven_state.json",
)

_SCORE_DESC = {
    "surprise": "意外度",
    "priced_in": "定价度",
    "real_rate": "实际利率",
    "resilience": "韧性",
    "cross_asset": "跨资产",
    "news": "新闻",
}


def exec_event_analysis(message):
    """金融事件分析: 查实时事件驱动状态返回六维评分解读。"""
    if not os.path.exists(EVENT_STATE_PATH):
        return {"success": True, "degraded": True, "answer": "事件驱动状态数据暂不可用", "data": None}
    try:
        with open(EVENT_STATE_PATH, encoding="utf-8") as f:
            state = json.load(f)
    except Exception as e:
        return {"success": True, "degraded": True, "answer": f"状态读取失败: {e}", "data": None}
    sig = (state or {}).get("signal") or {}
    if not sig:
        return {"success": True, "answer": "暂无事件驱动信号数据", "data": None}
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


COG_ENTRY_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "4-MEMORY", "9-工具与接口",
)


CASE_STORE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "34-前端应用训练系统", "l1_case_store.jsonl",
)


def settle_case(intent, message, result):
    """案例沉淀: 成功执行的 query→answer 对写入案例库 (统计学习回路, FAIL-OPEN)。"""
    if not result or not result.get("success") or result.get("degraded"):
        return
    try:
        import datetime as _dt
        case = {
            "ts": _dt.datetime.now().isoformat(timespec="seconds"),
            "intent": intent,
            "message": message,
            "answer": str(result.get("answer", ""))[:300],
            "data": result.get("data"),
        }
        with open(CASE_STORE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")
    except Exception:
        pass  # FAIL-OPEN


def _detect_valuable_finding(intent, message, result):
    """价值判断: 探索发现的有价值经验知识（无价值返回 None）。

    规则: ① 数据源的坑（metrics 空/数值全 0）② 环境发现（降级/不可用）③ 异常模式。
    正常查询返回正常数据 → 无认知价值（案例沉淀已覆盖）。
    """
    if not result:
        return None
    answer = str(result.get("answer", ""))
    data = result.get("data")
    if result.get("degraded") or "executor_failed" in answer or "执行异常" in answer:
        return f"发现: {answer[:150]}"
    if isinstance(data, dict):
        metrics = data.get("metrics")
        if metrics is None or metrics == "" or metrics == {}:
            return f"数据源的坑: {data.get('source', '?')} 的 metrics 为空（category={data.get('category', '?')}）"
        if isinstance(metrics, dict):
            numeric = [v for v in metrics.values() if isinstance(v, (int, float))]
            if numeric and all(v == 0 for v in numeric):
                return f"数据源的坑: {data.get('source', '?')} 数值字段全为 0（sub_category={data.get('sub_category', '?')}），数据质量存疑"
    return None


def settle_cognitive_valuable(intent, message, result):
    """认知沉淀: 有价值的探索发现才 record 回认知系统 (FAIL-OPEN)。"""
    finding = _detect_valuable_finding(intent, message, result)
    if not finding:
        return
    try:
        if COG_ENTRY_PATH not in sys.path:
            sys.path.insert(0, COG_ENTRY_PATH)
        from cognitive_loop_entry import get_cle
        cle = get_cle()
        cle.record(
            content=f"[L1探索发现] intent={intent} | 问法: {message} | {finding}",
            quality_level="B",
            confidence=0.6,
            tags=["l1-router", "settle-finding", intent],
            source="l1_router",
            memory_type="experience",
        )
    except Exception:
        pass  # FAIL-OPEN


def settle_to_cognitive(intent, message, result):
    """沉淀分流入口 (SPEC v1.0 §3.5): 成功→案例库；有价值的探索发现→认知系统。"""
    settle_case(intent, message, result)
    settle_cognitive_valuable(intent, message, result)
RISK_LOG_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "16-调控系统", "logs",
)

_RISK_STATE_DESC = {"IDLE": "待命", "ARMED": "已武装", "TRIGGERED": "已触发", "CLOSED": "已平仓"}


def exec_risk_control(message):
    """调控风控: 查 16-调控系统日志返回持仓风控状态。"""
    if not os.path.isdir(RISK_LOG_DIR):
        return {"success": True, "degraded": True, "answer": "调控系统日志暂不可用", "data": None}
    files = sorted(glob.glob(os.path.join(RISK_LOG_DIR, "trailing_runner_*.log")))
    if not files:
        return {"success": True, "answer": "暂无调控系统日志", "data": None}
    try:
        with open(files[-1], encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[-500:]
    except Exception as e:
        return {"success": True, "degraded": True, "answer": f"日志读取失败: {e}", "data": None}
    pat = re.compile(
        r"评估完成: 总持仓=(\d+) IDLE=(\d+) ARMED=(\d+) TRIGGERED=(\d+) CLOSED=(\d+) 历史触发累计=(\d+)"
    )
    latest = None
    for line in lines:
        m = pat.search(line)
        if m:
            latest = {
                "total": int(m.group(1)), "IDLE": int(m.group(2)), "ARMED": int(m.group(3)),
                "TRIGGERED": int(m.group(4)), "CLOSED": int(m.group(5)),
                "history_triggered": int(m.group(6)),
            }
    if not latest:
        return {"success": True, "answer": "日志中暂无风控评估记录", "data": None}
    parts = [f"{_RISK_STATE_DESC.get(k, k)}{v}" for k, v in latest.items() if k in _RISK_STATE_DESC]
    answer = (
        f"当前风控状态：总持仓{latest['total']}，{'、'.join(parts)}，"
        f"历史触发累计{latest['history_triggered']}次"
    )
    return {"success": True, "answer": answer, "data": {"positions": latest}}


OKX_BASE = "https://www.okx.com"
OKX_BACKUP = "https://aws.okx.com"


def _okx_ticker(inst_id):
    """请求 OKX 公开行情接口（无需鉴权），失败返回 None。"""
    import urllib.request
    for base in (OKX_BASE, OKX_BACKUP):
        try:
            url = f"{base}/api/v5/market/ticker?instId={inst_id}"
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            if body.get("code") == "0" and body.get("data"):
                return body["data"][0]
        except Exception:
            continue
    return None


def exec_price_query(message):
    """价格查询: 直连 OKX API 获取实时价格，失败降级回查 18 中心。"""
    m = re.search(r"([A-Z]{2,10})", message.upper())
    symbol = m.group(1) if m else "BTC"
    inst_id = f"{symbol}-USDT"
    t = _okx_ticker(inst_id)
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
