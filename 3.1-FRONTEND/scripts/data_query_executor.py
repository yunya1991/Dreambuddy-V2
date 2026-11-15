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
import time

# 接入 34 系统 L0（core/l0_foundation.py，与本脚本同处项目根下两级）
_TRAINING_SYS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "34-前端应用训练系统",
)
if _TRAINING_SYS_DIR not in sys.path:
    sys.path.insert(0, _TRAINING_SYS_DIR)
from core.l0_foundation import get_l0  # noqa: E402

# 18 中心已迁移 PostgreSQL，复用 39 模块统一 PG 辅助模块（FAIL-OPEN）
_DC_PG_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "39-金融语义蒸馏系统",
    "scripts",
)
if _DC_PG_DIR not in sys.path:
    sys.path.insert(0, _DC_PG_DIR)
import dc_pg  # noqa: E402

# S1 指标字典（54 模块 l1agg 为唯一事实源，与前端 timeseries 共用）
_L1AGG_ROOT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "54-L1架构能力聚合层",
)
if _L1AGG_ROOT not in sys.path:
    sys.path.insert(0, _L1AGG_ROOT)
# S1-c 价格回显（asof 验证 + 默认基准）：加密→BTC；美股→标普/纳指/道指；
# 美联储/宏观→黄金/美股指数；大宗商品→石油；避险→黄金；其他→BTC。
from l1agg.align import AlignError as _AlignError  # noqa: E402
from l1agg.align import load_leader as _load_leader  # noqa: E402

# 四类追问钩子 + 三项可执行能力（龙头对照 / 相关性 Top / 延续性强度）
from l1agg.hooks import build_hooks, format_hooks  # noqa: E402
from l1agg.price_echo import (  # noqa: E402
    PriceEchoError as _PriceEchoError,
)
from l1agg.price_echo import (  # noqa: E402
    echo_anchor_price,
    find_past_day_reference,
    format_echo,
    price_echo,
)
from l1agg.price_echo import (  # noqa: E402
    resolve_anchor as _resolve_anchor,
)
from l1agg.relations import (  # noqa: E402
    RelationError as _RelationError,
)
from l1agg.relations import (  # noqa: E402
    leader_gap as _leader_gap,
)
from l1agg.relations import (  # noqa: E402
    persistence_strength as _persistence_strength,
)
from l1agg.relations import (  # noqa: E402
    top_correlated as _top_correlated,
)
from l1agg.series_catalog import (  # noqa: E402
    format_series_output,
    resolve_days,
    resolve_event_kind,
    resolve_metric,
    resolve_whale_metric,
)

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
            # 收紧：单字别名不参与子串匹配（避免『金』误命中『资金费率』，与 39 系统 mcp_server.py 对齐）
            if a and len(a) >= 2 and a in message:
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


def _symbols_in_message(message):
    """按出现顺序返回消息中的资产符号（别名最长优先，单字别名不参与）。"""
    if not message:
        return []
    hits = []
    for sym, aliases in ENTITY_ALIASES.items():
        best = None
        for a in aliases:
            if not a or len(a) < 2:
                continue
            pos = message.lower().find(a.lower())
            if pos >= 0 and (best is None or pos < best[0]):
                best = (pos, -len(a))
        if best is not None:
            hits.append((best[0], best[1], sym))
    hits.sort()
    out = []
    for _pos, _neg_len, sym in hits:
        if sym not in out:
            out.append(sym)
    return out


def _attach_hooks(result, symbol, *, at_day=None, subject=None):
    """给答案追加四类追问钩子（结构化 + 文本可选项）。FAIL-OPEN。"""
    try:
        hooks = build_hooks(symbol, at_day=at_day, subject=subject)
    except Exception:
        return result
    data = result.get("data")
    if isinstance(data, dict):
        data["hooks"] = hooks
    result["hooks"] = hooks
    result["answer"] = (result.get("answer") or "") + format_hooks(hooks)
    return result


# 数据源关键词 → source 映射（消息中出现关键词即命中）
SOURCE_KEYWORDS = [
    ("defillama", ["defi tvl", "tvl", "defillama"]),
    ("fear_greed", ["恐惧贪婪", "fear greed", "fear_greed"]),
    ("fear_greed_enhanced", ["恐惧贪婪指数增强", "增强恐惧贪婪"]),
    (
        "fred",
        [
            "fred",
            "美联储经济数据",
            "cpi",
            "ppi",
            "通胀",
            "联邦基金利率",
            "货币供应",
            "工业产出",
            "美元指数",
            "美债",
            "美股",
            "标普",
            "纳指",
            "纳斯达克",
        ],
    ),
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
    (
        "CPI",
        ["超预期上行", "超预期", "高于预期"],
        "通胀超预期 → 加息预期升温 → 利好美元、压制风险资产，加密市场承压",
    ),
    ("CPI", ["低于预期", "不及预期"], "通胀降温 → 降息预期升温 → 风险资产受益，加密市场偏多"),
    ("恐惧贪婪指数", ["极度贪婪", "转向贪婪"], "市场情绪过热 → 追高风险加大，警惕回调（逆向信号）"),
    (
        "恐惧贪婪指数",
        ["极度恐惧", "转向恐惧"],
        "市场恐慌 → 历史上常为阶段性底部区域（逆向机会信号）",
    ),
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
        ("chains_summary", ["公链", "chains", "tvl", "defi", "锁仓"]),
        ("all_protocols", ["协议", "protocol"]),
    ],
}
SERIES_DEFAULTS = {
    "ccxt": "BTC/USDT",
    "yfinance": "^GSPC",
    "stablecoin_transparency": "stablecoins_top_10",
    # DeFi 总锁仓取 chains_summary（全链汇总）；all_protocols 是协议求和、跨链重复计数
    "defillama": "chains_summary",
}


def _resolve_series(src: str, message: str):
    m = message.lower()
    for series, kws in SERIES_KEYWORDS.get(src, []):
        if any(kw in m for kw in kws):
            return series
    return SERIES_DEFAULTS.get(src)


_DAL_DB_PATH = os.path.normpath(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "19-数据访问层",
        "data",
        "dreambuddy_core.db",
    )
)


def _cst_date_parts(ts: int):
    """mm_metrics 时间戳按 CST（UTC+8）取年月日；FRED 月度期以 CST 月初落库。"""
    import time as _t

    g = _t.gmtime(int(ts) + 8 * 3600)
    return g.tm_year, g.tm_mon, g.tm_mday


def _fetch_cpi_yoy(db_path: str = ""):
    """美国 CPI 同比（%）。

    优先：mm_metrics 中 sub_category='cpi' 的 actual/forecast/previous（财经日历发布口径）。
    回退：由 CPIAUCSL 月度指数计算——最新观测月 vs 去年同月（缺同月则取最近可用更早月），
          只看 CST 月初的观测行，排除增量采集产生的"当前时间"重复快照。
    FAIL-OPEN：数据不足/异常 → None（调用方保留指数原值展示）。
    """
    import sqlite3 as _sq

    try:
        path = db_path or _DAL_DB_PATH
        if not os.path.exists(path):
            return None
        conn = _sq.connect(f"file:{path}?mode=ro", uri=True)
        out = {}
        for name in ("actual", "forecast", "previous"):
            row = conn.execute(
                "SELECT metric_value FROM mm_metrics "
                "WHERE sub_category='cpi' AND metric_name=? "
                "ORDER BY timestamp DESC LIMIT 1",
                (name,),
            ).fetchone()
            if row and row[0] is not None:
                out[name] = row[0]
        if "actual" in out:
            conn.close()
            return out

        rows = conn.execute(
            "SELECT timestamp, metric_value FROM mm_metrics "
            "WHERE sub_category='CPIAUCSL' AND metric_name='value' "
            "AND metric_value IS NOT NULL ORDER BY timestamp ASC"
        ).fetchall()
        conn.close()
        monthly = {}
        for ts, val in rows:
            y, m, d = _cst_date_parts(int(ts))
            if d == 1:  # 仅月度观测点
                monthly[(y, m)] = float(val)
        if len(monthly) < 13:
            return None
        latest_month = max(monthly)
        base_key = (latest_month[0] - 1, latest_month[1])
        if base_key not in monthly:
            prior = [k for k in monthly if k < base_key]
            if not prior:
                return None
            base_key = max(prior)
        base = monthly[base_key]
        if base <= 0:
            return None
        latest = monthly[latest_month]
        return {
            "actual": round((latest / base - 1) * 100, 2),
            "period": "%04d-%02d" % latest_month,
            "base_period": "%04d-%02d" % base_key,
            "index": round(latest, 3),
        }
    except Exception:
        return None


def exec_metric_series(message: str):
    """S1: 指标历史序列直答（真实 mm_metrics，无合成数据）。"""
    spec = resolve_metric(message)
    if not spec:
        return {
            "success": True,
            "answer": "未能识别要查询的指标序列，可指明：CPI、恐惧贪婪指数、BTC 价格、MVRV、资金费率、DeFi TVL 等",
            "data": None,
        }
    days = resolve_days(message, spec["days"])
    ctx = get_l0().fetch_context(
        "datacenter.series",
        {
            "sub_category": spec["sub_category"],
            "metric_name": spec["metric_name"],
            "days": days,
            "agg": "daily",
        },
    )
    if ctx.get("degraded"):
        return {
            "success": True,
            "degraded": True,
            "answer": f"序列查询失败: {ctx['meta'].get('error') or ctx['meta'].get('reason', '')}",
            "data": None,
        }
    data = ctx.get("data") or {}
    meta = ctx.get("meta") or {}
    points = data.get("points") or []
    quality = meta.get("quality") or ""
    out = format_series_output(
        series=spec,
        points=points,
        days=days,
        quality=quality,
        source=ctx.get("source") or "",
    )
    payload = {
        "sub_category": spec["sub_category"],
        "metric_name": spec["metric_name"],
        "label": spec["label"],
        "unit": spec.get("unit") or "",
        "days": days,
        "agg": data.get("agg"),
        "sample_n": len(points),
        "quality": quality,
        "index": out,
        "points": points,
    }
    if points:
        sign = spec.get("sign", 1.0) or 1.0
        scale = spec.get("scale", 1.0) or 1.0  # 与 unit 同量纲（如 bln→亿美元 scale=0.1）
        values = [float(p["value"]) * sign / scale for p in points]
        payload["stats"] = {
            "first": values[0],
            "last": values[-1],
            "min": min(values),
            "max": max(values),
            "change": round(values[-1] - values[0], 6),
        }
    answer = out["text"]
    # 同期锚定价回显：验证「当时价格 → 当前价格 → 变化」的对齐链路（默认基准见 price_echo）
    if points:
        last_ts = int(points[-1].get("ts") or 0)
        is_self = spec.get("metric_name") == "close_usd" and spec.get("sub_category") in (
            "BTC",
            "ETH",
            "SOL",
            "XAU",
        )
        if last_ts and not is_self:
            try:
                day = time.strftime("%Y-%m-%d", time.gmtime(last_ts))
                echo = echo_anchor_price(
                    _DAL_DB_PATH,
                    day,
                    sub_category=spec["sub_category"],
                    metric_name=spec["metric_name"],
                    days=1825,
                )
                payload["price_echo"] = echo
                at, now = echo["at"], echo["now"]
                pct = echo["change"]["pct"]
                pct_text = "N/A" if pct is None else f"{pct:+.2f}"
                answer += (
                    f"；同期{echo['symbol']}（{echo['anchor']['label']}基准）"
                    f"{at['asof_day']} 收 {at['price']:,.2f}，最新 {now['price']:,.2f}"
                    f"（{'实时' if now['kind'] == 'live' else '库内最后一点'}），变化 {pct_text}%"
                )
            except Exception:
                pass  # FAIL-OPEN：回显失败不影响主答案
    if points and spec["sub_category"] == "CPIAUCSL":
        cpi = _fetch_cpi_yoy()
        if cpi and cpi.get("actual") is not None:
            payload["yoy"] = cpi
            answer += f"；同比 {cpi['actual']:+.2f}%（{cpi.get('period', '')} 观测）"
    anchor = _resolve_anchor(spec["sub_category"], spec["metric_name"])
    at_day = None
    if points:
        try:
            at_day = time.strftime("%Y-%m-%d", time.gmtime(int(points[-1].get("ts") or 0)))
        except (TypeError, ValueError):
            at_day = None
    return _attach_hooks(
        {"success": True, "answer": answer, "data": payload},
        anchor.primary,
        at_day=at_day,
    )


def _series_last(sub: str, metric: str, days: int):
    """取单维序列最新点 (value, ts)；不可用/空 → None。"""
    ctx = get_l0().fetch_context(
        "datacenter.series",
        {"sub_category": sub, "metric_name": metric, "days": days, "agg": "daily"},
    )
    if ctx.get("degraded"):
        return None
    points = (ctx.get("data") or {}).get("points") or []
    if not points:
        return None
    last = points[-1]
    return float(last["value"]), int(last.get("ts", 0))


def _cst_hm(ts: int) -> str:
    import time as _t

    g = _t.gmtime(int(ts) + 8 * 3600)
    return "%04d-%02d-%02d %02d:%02d" % (g.tm_year, g.tm_mon, g.tm_mday, g.tm_hour, g.tm_min)


def exec_whale_flow(message: str):
    """巨鲸动向：exchanges_whales 单维序列直答（净流入/转入/转出/笔数）。"""
    spec = resolve_whale_metric(message)
    days = resolve_days(message, spec["days"])
    ctx = get_l0().fetch_context(
        "datacenter.series",
        {
            "sub_category": spec["sub_category"],
            "metric_name": spec["metric_name"],
            "days": days,
            "agg": "daily",
        },
    )
    if ctx.get("degraded"):
        return {
            "success": True,
            "degraded": True,
            "answer": f"巨鲸数据暂不可用: {ctx['meta'].get('error') or ctx['meta'].get('reason', '')}",
            "data": None,
        }
    data = ctx.get("data") or {}
    meta = ctx.get("meta") or {}
    points = data.get("points") or []
    unit = spec["unit"]
    quality = meta.get("quality") or ""
    out = format_series_output(
        series=spec,
        points=points,
        days=days,
        quality=quality,
        source=ctx.get("source") or "",
    )
    head = out["text"]
    values = [float(p["value"]) * (spec.get("sign") or 1.0) for p in points]
    # 24h 转入/转出与大额转账笔数（同一 sub_category 的伴随单维，补充方向判断）
    extra = []
    for metric, label, sc in (
        ("whale_24h_to_ex_usd", "24h 转入交易所", 1e8),
        ("whale_24h_from_ex_usd", "24h 转出交易所", 1e8),
        ("whales_transfer_count", "大额转账笔数", 1.0),
    ):
        if metric == spec["metric_name"]:
            continue
        got = _series_last("exchanges_whales", metric, max(days, 2))
        if got is None:
            continue
        val, ts = got
        if metric == "whales_transfer_count":
            extra.append(f"{label} {val:.0f} 笔（{_cst_hm(ts)}）")
        else:
            extra.append(f"{label} {val / sc:.2f} 亿美元（{_cst_hm(ts)}）")
    answer = head + ("；" + "，".join(extra) if extra else "")
    payload = {
        "sub_category": spec["sub_category"],
        "metric_name": spec["metric_name"],
        "label": spec["label"],
        "unit": unit,
        "days": days,
        "sample_n": len(points),
        "quality": quality,
        "index": out,
        "points": points,
    }
    if values:
        payload["stats"] = {
            "last": values[-1],
            "min": min(values),
            "max": max(values),
            "change": round(values[-1] - values[0], 6),
        }
    return {"success": True, "answer": answer, "data": payload}


def exec_calendar_event(message: str):
    """经济日历：mm_events 单维事件检索（议息/非农/CPI/PPI 的下一次或近期日程）。"""
    kind = resolve_event_kind(message)
    kinds = [kind["kind"]] if kind else []
    label = kind["label"] if kind else "经济数据事件"
    ctx = get_l0().fetch_context(
        "datacenter.events", {"kinds": kinds, "limit": 3, "future_days": 400}
    )
    if ctx.get("degraded"):
        return {
            "success": True,
            "degraded": True,
            "answer": f"经济日历暂不可用: {ctx['meta'].get('error') or ctx['meta'].get('reason', '')}",
            "data": None,
        }
    events = ctx.get("data") or []
    if not events:
        return {
            "success": True,
            "answer": f"经济日历中暂无后续{label}日程（数据源未更新）",
            "data": {"kind": kind["kind"] if kind else "", "events": []},
        }
    first = events[0]
    tail = "；再往后：" + "，".join(e["event_time_cst"] for e in events[1:]) if events[1:] else ""
    answer = (
        f"下一次{label}：{first['event_time_cst']}（北京时间），"
        f"{first['title'] or first['event_type']}（来源 {first['source']}，质量 {first['quality']}）"
        + tail
    )
    return {
        "success": True,
        "answer": answer,
        "data": {
            "kind": kind["kind"] if kind else "",
            "label": label,
            "events": events,
        },
    }


def exec_data_query(message: str):
    src = resolve_source(message)
    if not src:
        return {
            "success": True,
            "answer": "未能识别要查询的数据源，请指明具体数据（如 DeFi TVL、恐惧贪婪指数、CPI 等）",
            "data": None,
        }
    fetch_params = {"source": src}
    series = _resolve_series(src, message)
    if series:
        fetch_params["sub_category"] = series
    ctx = get_l0().fetch_context("datacenter.record", fetch_params)
    if ctx.get("degraded"):
        if ctx["meta"].get("reason") == "source_missing":
            return {
                "success": True,
                "degraded": True,
                "answer": "数据获取中心数据库暂不可用",
                "data": None,
            }
        return {
            "success": True,
            "degraded": True,
            "answer": f"查询失败: {ctx['meta'].get('error', '')}",
            "data": None,
        }
    row = ctx["data"]
    if not row:
        return {"success": True, "answer": f"数据源 {src} 暂无记录", "data": None}
    metrics = row["metrics"]
    answer = f"{src}/{row['sub_category']} 最新数据（{row['timestamp']}）：{json.dumps(metrics, ensure_ascii=False)[:300] if metrics else '无指标'}"
    if fetch_params.get("sub_category") == "CPIAUCSL":
        yoy = _fetch_cpi_yoy()
        if yoy:
            idx_val = metrics.get("value") if isinstance(metrics, dict) else None
            if yoy.get("forecast") is not None or yoy.get("previous") is not None:
                answer = (
                    f"美国CPI同比 {yoy.get('actual')}%"
                    f"（预期 {yoy.get('forecast')}%，前值 {yoy.get('previous')}%）"
                    f"；CPI指数水平 CPIAUCSL={idx_val}（1982-84=100，{row['timestamp']}）"
                )
            else:
                answer = (
                    f"美国CPI同比 {yoy.get('actual')}%"
                    f"（{yoy.get('period')} 观测，基期 {yoy.get('base_period')}）"
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
                    return {
                        "success": True,
                        "answer": f"{metric}{p}的市场含义：{meaning}",
                        "data": {"metric": metric, "pattern": p, "meaning": meaning},
                    }
    return {
        "success": True,
        "answer": "暂无该变化模式的解读知识，可尝试询问 CPI、恐惧贪婪指数、稳定币、多空比、资金费率等指标的变化含义",
        "data": None,
    }


_DIM_DESC = {
    "C1": "资金面",
    "C2": "情绪面",
    "C3": "技术面",
    "C4": "宏观",
    "C6": "时序",
    "C7": "隐性",
    "C8": "衍生维度",
}
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
        parts.append(
            f"{_DIM_DESC.get(d, d)}({_DIR_DESC.get(direction, direction)}, 强度{strength:.2f})"
        )
    # 矛盾/一致判断
    dirs = set(v[0] for v in dims.values())  # noqa: C401
    state = "各维度方向存在分歧（矛盾状态）" if len(dirs) > 1 else "各维度方向一致"
    return {
        "success": True,
        "answer": f"当前矛盾状态：{state}。各维度：{'；'.join(parts)}",
        "data": {
            "dims": {d: {"direction": dims[d][0], "strength": dims[d][1]} for d in dims},
            "state": state,
        },
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
        return {
            "success": True,
            "need_clarification": True,
            "answer": "请问您想查询哪个币种？（如：以太坊、BTC、黄金）",
            "data": None,
        }
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
        return {
            "success": True,
            "need_clarification": True,
            "answer": "请问您想查询哪个币种？（如：以太坊、BTC、黄金）",
            "data": None,
        }
    if symbol not in results:
        symbol = next(iter(results))
    info = results[symbol] or {}
    direction = info.get("direction", "NEUTRAL")
    confidence = info.get("confidence", 0.0)
    hexagram = info.get("hexagram", "")
    return {
        "success": True,
        "answer": f"{symbol} 技术面推理：方向{_YJ_DIR_DESC.get(direction, direction)}，置信度{confidence:.2f}，卦象{hexagram or '无'}",
        "data": {
            "symbol": symbol,
            "direction": direction,
            "confidence": confidence,
            "hexagram": hexagram,
        },
    }


def _fmt_pct(value):
    return f"{value * 100:+.2f}%"


def exec_technical_indicator(message):
    """技术指标直答（54 D-B00–B07，确定性、零 token、无 LLM）。

    数据链路：L0 `market.candles`（日线优先；日线 OHLC 不全时回退小时线）→
    54 `l1agg.technical.analyze`。样本不足/无 OHLC 时如实回 gate 与缺失腿，
    不伪造高低点（SPEC §5.4 双端同步）。
    """
    try:
        from l1agg.candles import CandleError
        from l1agg.candles import load as load_candles
        from l1agg.technical import MIN_BARS, analyze
    except Exception as e:  # noqa: BLE001  FAIL-OPEN：54 模块不可用时降级
        return {
            "success": True,
            "degraded": True,
            "answer": f"技术指标能力不可用: {e}",
            "data": None,
        }

    symbol = _resolve_symbol(message) or "BTC"
    candidates = []
    failures = []
    for bar, days in (("1d", 365), ("1h", 60)):
        try:
            candles = load_candles(symbol, bar=bar, days=days)
        except CandleError as e:
            failures.append(f"{bar}:{e}")
            continue
        candidates.append((candles, analyze(candles)))
    if not candidates:
        return {
            "success": True,
            "degraded": True,
            "answer": f"{symbol} K线数据不可用（{'；'.join(failures) or '无数据源'}）",
            "data": None,
        }

    with_ohlc = [(c, o) for c, o in candidates if c.has_ohlc and o.get("gate") == "ok"]
    candles, out = with_ohlc[0] if with_ohlc else candidates[0]
    bar_label = {"1d": "日线", "1h": "小时线"}.get(candles.bar, candles.bar)
    span = out.get("span") or "无"
    n = out.get("sample_n") or 0

    if out.get("gate") == "empty":
        return {
            "success": True,
            "degraded": True,
            "answer": f"{symbol} 暂无可用的{bar_label} K线数据",
            "data": out,
        }
    if out.get("gate") != "ok":
        reason = "；".join(out.get("degraded") or [])
        answer = f"{symbol} {bar_label}样本不足（{n} 根，需≥{MIN_BARS} 根）"
        if not out.get("has_ohlc"):
            answer += "，库内暂无可用的高低点(OHLC)，支撑/压力位无法计算"
        return {
            "success": True,
            "degraded": True,
            "answer": f"{answer}。原因：{reason}" if reason else answer,
            "data": out,
        }

    caps = out["capabilities"]
    parts = []
    b01 = caps.get("D-B01") or {}
    if b01.get("gate") == "ok":
        rel = b01.get("price_vs_ma20")
        parts.append(
            f"现价 {b01['price']:.2f}（MA20 {b01['ma20']:.2f}"
            + (f"，偏离 {_fmt_pct(rel)}" if rel is not None else "")
            + "）"
        )
    b02 = caps.get("D-B02") or {}
    if b02.get("gate") == "ok":
        parts.append(f"RSI14 {b02['rsi14']:.1f}（{b02['zone']}）")
    b03 = caps.get("D-B03") or {}
    if b03.get("gate") == "ok":
        cross = {"golden": "金叉", "death": "死叉"}.get(b03.get("cross"), "无交叉")
        parts.append(f"MACD {cross}（DIF {b03['dif']:.2f} / DEA {b03['dea']:.2f}）")
    b04 = caps.get("D-B04") or {}
    if b04.get("gate") == "ok":
        parts.append(f"ATR14 {b04['atr14']:.2f}（{b04['atr_pct'] * 100:.2f}%）")
    b05 = caps.get("D-B05") or {}
    if b05.get("gate") == "ok":
        parts.append(
            f"布林上/中/下 {b05['upper']:.2f}/{b05['mid']:.2f}/{b05['lower']:.2f}"
            f"（%B {b05['boll_pos']:.2f}）"
        )
    b06 = caps.get("D-B06") or {}
    if b06.get("gate") == "ok":
        parts.append(f"量比 {b06['vol_ratio']:.2f}")
    b07 = caps.get("D-B07") or {}
    if b07.get("gate") == "ok":
        parts.append(
            f"支撑 {b07['support']:.2f}（触碰 {b07['support_touches']} 次，"
            f"距离 {_fmt_pct(b07['support_dist'])}）"
        )
        parts.append(
            f"压力 {b07['resistance']:.2f}（触碰 {b07['resistance_touches']} 次，"
            f"距离 {_fmt_pct(b07['resistance_dist'])}）"
        )

    head = f"{symbol} 技术面（{bar_label}，{n} 根，{span}"
    if out.get("is_stale"):
        head += f"，滞后 {out.get('stale_days')} 天"
    head += "）"
    answer = f"{head}：" + "；".join(parts) if parts else f"{head}：指标暂不可用"
    if not out.get("has_ohlc"):
        answer += "。注意：库内暂无可用的高低点(OHLC)，ATR/支撑压力位未计算"
    ohlc_note = (candles.meta or {}).get("ohlc_note")
    if ohlc_note:
        answer += f"。注意：{ohlc_note}"
    return {
        "success": True,
        "degraded": bool(out.get("degraded")),
        "answer": answer,
        "data": out,
    }


# ── 统计关系问答（54 D-E02/E03/E05/E07/E08/E10）──────────────
# 子能力选择：按序匹配，命中即止；无命中默认回撤（价格样本最稳）
_STAT_DRAWDOWN_CUE = re.compile(r"回撤|drawdown|跌了多少", re.IGNORECASE)
_STAT_SEASONAL_CUE = re.compile(r"季节性|月份效应|几月|星期几|周几|月内|月初|月末|日历效应")
_STAT_PERCENTILE_CUE = re.compile(r"分位|百分位|percentile|同分位|前瞻收益|前瞻分布", re.IGNORECASE)
_STAT_STATE_CUE = re.compile(r"状态转移|转移矩阵|状态切换|停留|状态持续性")
_STAT_IC_CUE = re.compile(
    r"(?:^|[^A-Za-z])IC(?:[^A-Za-z]|$)|信息系数|因子有效|单调性", re.IGNORECASE
)
_STAT_CORR_CUE = re.compile(r"相关|同向|领先|滞后")
_STAT_CROSS_CUE = re.compile(r"同向率|同向比例|跨资产同向|相关稳定|相关突变|突变点|周期对齐")
_STAT_ALIGN_CUE = re.compile(r"对齐切片|时空对齐|对齐窗口|陈旧|stale|ffill", re.IGNORECASE)
_STAT_CROWDING_CUE = re.compile(r"拥挤|拥挤度|crowding|杠杆过热|多空比过热", re.IGNORECASE)
_STAT_SIGNIFICANCE_CUE = re.compile(
    r"显著性|是否显著|显著吗|HAC|Newey|Newey-West|Deflated|DSR", re.IGNORECASE
)
# D-A/D-B/D-G 专用口径先于宽词：避免 ATH→普通回撤、历史分位→前瞻分位、
# 滚动相关→通用相关、波动率目标→普通年化波动率。
_STAT_VOL_TARGET_CUE = re.compile(r"波动率目标|目标波动|vol[ _-]?target", re.IGNORECASE)
_STAT_ATH_CUE = re.compile(r"\bATH\b|历史新高|距.{0,6}高点|离.{0,6}高点", re.IGNORECASE)
_STAT_SLOPE_CUE = re.compile(r"趋势斜率|斜率|slope", re.IGNORECASE)
_STAT_MOMENTUM_CUE = re.compile(
    r"12\s*[-_]\s*1|momentum(?!\s*factor)|动量(?!因子|延续)", re.IGNORECASE
)
_STAT_REAL_RATE_CUE = re.compile(r"实际利率|real[ _-]?rate", re.IGNORECASE)
_STAT_ROLLING_CORR_CUE = re.compile(r"滚动相关|rolling[ _-]?corr", re.IGNORECASE)
_STAT_LEAD_LAG_CUE = re.compile(r"领先滞后|lead[ _-]?lag|谁领先|谁滞后", re.IGNORECASE)
_STAT_EXTREME_CUE = re.compile(r"极端事件|极端频率|超阈值|阈值频率|极端.{0,6}频率")
_STAT_ETF_FLOW_CUE = re.compile(
    r"ETF.{0,12}(?:滚动和|滚动净流入)|净流入滚动和|(?:7|30)\s*日(?:ETF)?净流入",
    re.IGNORECASE,
)
_STAT_STABLECOIN_CUE = re.compile(
    r"稳定币.{0,10}(?:规模增速|规模增长|增速)|stablecoin.{0,20}growth", re.IGNORECASE
)
_STAT_YOY_CUE = re.compile(r"同比|year[ -]?over[ -]?year|\byoy\b", re.IGNORECASE)
_STAT_MOM_CUE = re.compile(r"环比|month[ -]?over[ -]?month|\bmom\b", re.IGNORECASE)
_STAT_CAGR_CUE = re.compile(r"CAGR|年化复合|复合增长率", re.IGNORECASE)
_STAT_HIST_PERCENTILE_CUE = re.compile(r"历史分位|历史百分位|分位排名|当前分位")
_STAT_CHANGE_RATE_CUE = re.compile(r"变化率|区间变化|变化幅度")
_STAT_HISTORY_SERIES_CUE = re.compile(r"历史序列|序列降采样|日频序列|周频序列|月频序列")
_STAT_ANNUAL_VOL_CUE = re.compile(r"年化波动|波动率|volatility", re.IGNORECASE)
_STAT_SERIES_DRAWDOWN_CUE = re.compile(r"单序列回撤|回撤画像")

_STAT_METRIC_CAPS = frozenset(
    {"D-A01", "D-A02", "D-A03", "D-A04", "D-A08", "D-A09", "D-A13", "D-A15", "D-A16"}
)
_STAT_PRICE_DATE_CAPS = frozenset({"D-A07", "D-B08", "D-B09", "D-G08", "D-G09"})

# 拥挤度合成（F26 固定权重 0.4/0.3/0.3）所需三指标：sub_category / metric_name / 展示名
_CROWDING_SERIES = (
    ("okx_derivatives", "funding_rate_pct", "资金费率"),
    ("open_interest", "open_interest_value", "未平仓"),
    ("long_short_ratio", "long_short_ratio", "多空比"),
)


def _load_crowding_panel(days: int = 180):
    """拥挤度三指标日频序列；返回 (panel, 缺失项中文名)。全部可用才允许合成。"""
    panel, missing = {}, []
    for sub, metric, label in _CROWDING_SERIES:
        ctx = get_l0().fetch_context(
            "datacenter.series",
            {"sub_category": sub, "metric_name": metric, "days": days, "agg": "daily"},
        )
        points = (ctx.get("data") or {}).get("points") or []
        values = [float(p["value"]) for p in points if p.get("value") is not None]
        if values:
            panel[label] = values
        else:
            missing.append(label)
    return panel, missing


def _stat_dates(ts_values):
    """epoch 秒 → UTC ISO 日期（能力层 C 组方法要求日频日期轴）。"""
    from datetime import datetime, timezone

    return [datetime.fromtimestamp(int(t), timezone.utc).date().isoformat() for t in ts_values]


def _load_stat_series(sub_category, metric_name, *, days, agg="daily", sign=1.0, scale=1.0):
    """统计能力取数：值与日期成对过滤，沿用指标目录的符号/量纲换算。"""
    ctx = get_l0().fetch_context(
        "datacenter.series",
        {
            "sub_category": sub_category,
            "metric_name": metric_name,
            "days": days,
            "agg": agg,
        },
    )
    if ctx.get("degraded"):
        return None
    points = (ctx.get("data") or {}).get("points") or []
    values, dates = [], []
    for point in points:
        if point.get("value") is None or point.get("ts") is None:
            continue
        values.append(float(point["value"]) * sign / scale)
        dates.append(_stat_dates([point["ts"]])[0])
    return (values, dates) if values else None


def _stat_returns(values):
    return [values[i] / values[i - 1] - 1.0 for i in range(1, len(values)) if values[i - 1]]


def _stat_returns_with_dates(values, dates):
    """收益与日期同步过滤：`dates[i]` 对应 `values[i-1] → values[i]` 的收益。"""
    out_v, out_d = [], []
    for i in range(1, len(values)):
        prev = values[i - 1]
        if not prev:
            continue
        out_v.append(values[i] / prev - 1.0)
        out_d.append(dates[i])
    return out_v, out_d


def _stat_result(envelope):
    """能力层信封 → L1 执行器口径（answer 原样透出，数值不改写）。"""
    out = {
        "success": True,
        "answer": envelope.get("answer", ""),
        "data": envelope.get("data"),
        "quality": envelope.get("quality"),
        "capability": envelope.get("capability"),
    }
    if not envelope.get("ok"):
        out["degraded"] = True
    return out


def exec_stat_query(message):
    """统计关系直答（54 能力层，确定性、零 token、无 LLM）。

    数据链路：日线 730 天经 54 `l1agg.candles`（L0 market.candles）→
    `l1agg.capabilities.run_capability`。样本不足/无法计算由能力层自行降级，
    本层不修改 `quality`、不改写 `answer` 数值；FAIL-OPEN 不向上抛异常。
    """
    try:
        from l1agg.candles import CandleError
        from l1agg.candles import load as load_candles
        from l1agg.capabilities import run_capability
        from l1agg.capabilities.manifest import assert_public
    except Exception as e:  # noqa: BLE001  FAIL-OPEN：54 模块不可用时降级
        return {
            "success": True,
            "degraded": True,
            "answer": f"统计关系能力不可用: {e}",
            "data": None,
        }

    message = message or ""
    resolved_symbol = _resolve_symbol(message)
    symbol = resolved_symbol or "BTC"

    if _STAT_VOL_TARGET_CUE.search(message):
        capability_id = "D-G09"
    elif _STAT_ATH_CUE.search(message):
        capability_id = "D-B09"
    elif _STAT_SLOPE_CUE.search(message):
        capability_id = "D-B08"
    elif _STAT_MOMENTUM_CUE.search(message):
        capability_id = "D-G08"
    elif _STAT_REAL_RATE_CUE.search(message):
        capability_id = "D-A10"
    elif _STAT_ROLLING_CORR_CUE.search(message):
        capability_id = "D-A11"
    elif _STAT_LEAD_LAG_CUE.search(message):
        capability_id = "D-A12"
    elif _STAT_EXTREME_CUE.search(message):
        capability_id = "D-A13"
    elif _STAT_ETF_FLOW_CUE.search(message):
        capability_id = "D-A15"
    elif _STAT_STABLECOIN_CUE.search(message):
        capability_id = "D-A16"
    elif _STAT_YOY_CUE.search(message):
        capability_id = "D-A08"
    elif _STAT_MOM_CUE.search(message):
        capability_id = "D-A09"
    elif _STAT_CAGR_CUE.search(message):
        capability_id = "D-A03"
    elif _STAT_HIST_PERCENTILE_CUE.search(message):
        capability_id = "D-A04"
    elif _STAT_CHANGE_RATE_CUE.search(message):
        capability_id = "D-A02"
    elif _STAT_HISTORY_SERIES_CUE.search(message):
        capability_id = "D-A01"
    elif _STAT_ANNUAL_VOL_CUE.search(message):
        capability_id = "D-A06"
    elif _STAT_SERIES_DRAWDOWN_CUE.search(message):
        capability_id = "D-A07"
    elif _STAT_DRAWDOWN_CUE.search(message):
        capability_id = "D-E10"
    elif _STAT_CROWDING_CUE.search(message):
        capability_id = "D-A14"
    elif _STAT_SEASONAL_CUE.search(message):
        capability_id = "D-E03"
    elif _STAT_PERCENTILE_CUE.search(message):
        capability_id = "D-E02"
    elif _STAT_STATE_CUE.search(message):
        capability_id = "D-E07"
    elif _STAT_IC_CUE.search(message):
        capability_id = "D-E08"
    elif _STAT_ALIGN_CUE.search(message):
        capability_id = "D-E12"
    elif _STAT_CROSS_CUE.search(message):
        capability_id = "D-E11"
    elif _STAT_CORR_CUE.search(message):
        capability_id = "D-E05"
    elif _STAT_SIGNIFICANCE_CUE.search(message):
        capability_id = "D-G22"
    else:
        capability_id = "D-E10"

    # S0 执行外露硬闸（SPEC-54 §4.8 / ADR-V14）：internal 能力直接抛 PermissionError，
    # 不降级、不返回数据——外露属于安全事故。
    assert_public(capability_id)

    if capability_id == "D-A10":
        # DGS10 与 CPI 的月内发布日期不同，按 UTC 月份对齐；period=12 才是月度同比。
        days = resolve_days(message, 1825)
        try:
            nominal = _load_stat_series("DGS10", "value", days=days, agg="monthly")
            cpi = _load_stat_series("CPIAUCSL", "value", days=days, agg="monthly")
            if nominal is None or cpi is None:
                return {
                    "success": True,
                    "degraded": True,
                    "answer": "实际利率需要 DGS10 与 CPIAUCSL 两条月度序列，当前数据不可用，不做推算。",
                    "data": None,
                    "capability": "D-A10",
                }
            nominal_by_month = {date[:7]: value for value, date in zip(*nominal, strict=False)}
            cpi_by_month = {date[:7]: value for value, date in zip(*cpi, strict=False)}
            months = sorted(set(nominal_by_month) & set(cpi_by_month))
            if not months:
                return {
                    "success": True,
                    "degraded": True,
                    "answer": "DGS10 与 CPIAUCSL 没有共同月份，暂无法计算实际利率，不做推算。",
                    "data": None,
                    "capability": "D-A10",
                }
            envelope = run_capability(
                "D-A10",
                nominal=[nominal_by_month[month] for month in months],
                cpi=[cpi_by_month[month] for month in months],
                dates=[f"{month}-01" for month in months],
                period=12,
            )
        except Exception as e:  # noqa: BLE001  FAIL-OPEN
            return {
                "success": True,
                "degraded": True,
                "answer": f"实际利率计算异常: {e}",
                "data": None,
                "capability": "D-A10",
            }
        return _stat_result(envelope)

    if capability_id in _STAT_METRIC_CAPS:
        spec = resolve_metric(message)
        if not spec:
            return {
                "success": True,
                "degraded": True,
                "answer": f"{capability_id} 需要明确的指标序列（如 CPI、MVRV、资金费率、ETF 净流入、稳定币规模），不做推算。",
                "data": None,
                "capability": capability_id,
            }
        agg = "monthly" if capability_id in ("D-A08", "D-A09") else "daily"
        default_days = 1825 if agg == "monthly" else spec["days"]
        days = resolve_days(message, default_days)
        try:
            loaded = _load_stat_series(
                spec["sub_category"],
                spec["metric_name"],
                days=days,
                agg=agg,
                sign=spec.get("sign", 1.0) or 1.0,
                scale=spec.get("scale", 1.0) or 1.0,
            )
            if loaded is None:
                return {
                    "success": True,
                    "degraded": True,
                    "answer": f"{spec['label']}序列不可用，暂无法计算 {capability_id}，不做推算。",
                    "data": None,
                    "capability": capability_id,
                }
            values, dates = loaded
            kwargs = {
                "values": values,
                "dates": dates,
                "name": spec["label"],
                "symbol": resolved_symbol or "",
            }
            if capability_id in ("D-A01", "D-A02", "D-A04", "D-A08", "D-A09", "D-A15"):
                kwargs["unit"] = spec.get("unit") or ""
            if capability_id == "D-A01":
                if re.search(r"月频|月度", message):
                    kwargs["freq"] = "monthly"
                elif re.search(r"周频|每周", message):
                    kwargs["freq"] = "weekly"
            elif capability_id == "D-A13":
                if re.search(r"下跌|低于|下方|跌破", message):
                    kwargs["side"] = "below"
                elif re.search(r"绝对|涨跌", message):
                    kwargs["side"] = "abs"
            envelope = run_capability(capability_id, **kwargs)
        except Exception as e:  # noqa: BLE001  FAIL-OPEN
            return {
                "success": True,
                "degraded": True,
                "answer": f"{capability_id} 指标统计异常: {e}",
                "data": None,
                "capability": capability_id,
            }
        return _stat_result(envelope)

    if capability_id == "D-E08":
        # 无因子数据源：如实降级，不拿价格序列伪造因子
        return {
            "success": True,
            "degraded": True,
            "answer": "条件 IC 需要明确的因子序列与前瞻收益口径，当前 L1 未接入因子数据源："
            "请指明因子（如动量/波动率/资金费率）后再计算，不做推算。",
            "data": None,
            "capability": "D-E08",
        }

    if capability_id == "D-A14":
        # 拥挤度合成按冻结口径 F26 固定权重 0.4/0.3/0.3，三指标缺一不合成（不拿单指标冒充）
        panel, missing = _load_crowding_panel()
        if missing:
            return {
                "success": True,
                "degraded": True,
                "answer": f"拥挤度合成需要资金费率/未平仓/多空比三条对齐序列（F26 固定权重 0.4/0.3/0.3），"
                f"当前缺少：{'、'.join(missing)}，暂不输出拥挤度档位，不做推算。",
                "data": None,
                "capability": "D-A14",
            }
        try:
            envelope = run_capability("D-A14", series=panel, symbol=symbol)
        except Exception as e:  # noqa: BLE001  FAIL-OPEN
            return {
                "success": True,
                "degraded": True,
                "answer": f"拥挤度合成计算异常: {e}",
                "data": None,
                "capability": "D-A14",
            }
        return _stat_result(envelope)

    if capability_id == "D-E12":
        # 时空对齐切片：每资产独立日期轴（R18 内部做 UTC 日收盘 + 跨源去重 + ffill）
        participants = [symbol] + [s for s in _symbols_in_message(message) if s != symbol]
        series = {}
        last_error = None
        for sym in participants:
            candles = None
            for policy in ("snapshot", "auto"):
                try:
                    candles = load_candles(sym, bar="1d", days=730, source_policy=policy)
                except CandleError as e:
                    last_error = e
                    candles = None
                if candles is not None and candles.sample_n:
                    break
            if candles is None or not candles.sample_n:
                return {
                    "success": True,
                    "degraded": True,
                    "answer": f"{sym} K线数据不可用，暂无法做时空对齐切片（{last_error}）",
                    "data": None,
                    "capability": "D-E12",
                }
            series[sym] = list(zip(_stat_dates(candles.ts), list(candles.close), strict=False))
        try:
            envelope = run_capability("D-E12", series=series)
        except Exception as e:  # noqa: BLE001  FAIL-OPEN
            return {
                "success": True,
                "degraded": True,
                "answer": f"时空对齐切片计算异常: {e}",
                "data": None,
                "capability": "D-E12",
            }
        return _stat_result(envelope)

    if capability_id in ("D-E05", "D-E11", "D-A11", "D-A12"):
        peers = [s for s in _symbols_in_message(message) if s != symbol]
        if not peers:
            label = {
                "D-E11": "跨资产同向",
                "D-A11": "滚动相关",
                "D-A12": "领先滞后相关",
            }.get(capability_id, "相关性")
            return {
                "success": True,
                "degraded": True,
                "answer": f"{label}统计需要第二个标的"
                f"（当前识别为 {symbol}），请指明对比对象（如 BTC 与 ETH），不做推算。",
                "data": None,
                "capability": capability_id,
            }
        peer = peers[0]
        # 跨资产日收益必须同一「收盘锚点」：优先两侧都走日频快照（close_anchor=snapshot_last），
        # 避免一侧真实日线（UTC 日末收盘）与一侧快照（日内时点）混算导致同期相关被低估；
        # 某标的无快照时整体退回 auto，并在回答里标注锚点混用。
        x_candles = y_candles = None
        last_error = None
        for policy in ("snapshot", "auto"):
            try:
                cx = load_candles(symbol, bar="1d", days=730, source_policy=policy)
                cy = load_candles(peer, bar="1d", days=730, source_policy=policy)
            except CandleError as e:
                last_error = e
                continue
            if cx.sample_n and cy.sample_n:
                x_candles, y_candles = cx, cy
                break
            last_error = last_error or "empty series"
        if x_candles is None:
            return {
                "success": True,
                "degraded": True,
                "answer": f"{symbol}/{peer} K线数据不可用，暂无法计算相关性（{last_error}）",
                "data": None,
                "capability": capability_id,
            }
        # 按共同交易日（UTC 日期轴，日线 ts 已归一到 UTC 日首）对齐后取日收益
        x_map = dict(zip(_stat_dates(x_candles.ts), x_candles.close, strict=False))
        y_map = dict(zip(_stat_dates(y_candles.ts), y_candles.close, strict=False))
        common = sorted(set(x_map) & set(y_map))
        if len(common) < 2:
            return {
                "success": True,
                "degraded": True,
                "answer": f"{symbol} 与 {peer} 无对齐的日线数据，暂无法计算相关性，不做推算。",
                "data": None,
                "capability": capability_id,
            }
        try:
            if capability_id == "D-E05" and len(peers) >= 2:
                # ≥3 资产：共同交易日面板 → 日收益 → M05/M06/M07 相关矩阵
                panel = {symbol: x_map, peer: y_map}
                for extra in peers[1:]:
                    extra_candles = None
                    for policy in ("snapshot", "auto"):
                        try:
                            extra_candles = load_candles(
                                extra, bar="1d", days=730, source_policy=policy
                            )
                        except CandleError:
                            extra_candles = None
                        if extra_candles is not None and extra_candles.sample_n:
                            break
                    if extra_candles is None or not extra_candles.sample_n:
                        return {
                            "success": True,
                            "degraded": True,
                            "answer": f"{extra} K线数据不可用，多资产相关矩阵无法完整计算，不做推算。",
                            "data": None,
                            "capability": "D-E05",
                        }
                    panel[extra] = dict(
                        zip(_stat_dates(extra_candles.ts), extra_candles.close, strict=False)
                    )
                common = sorted(set.intersection(*(set(m) for m in panel.values())))
                if len(common) < 3:
                    return {
                        "success": True,
                        "degraded": True,
                        "answer": f"{len(panel)} 个资产共同交易日仅 {len(common)} 天，"
                        "不足 3 天，不做推算。",
                        "data": None,
                        "capability": "D-E05",
                    }
                envelope = run_capability(
                    "D-E05",
                    series={
                        name: _stat_returns([m[t] for t in common]) for name, m in panel.items()
                    },
                    dates=common[1:],
                    x_name=symbol,
                    y_name=peer,
                )
                return _stat_result(envelope)

            x_returns, x_dates = _stat_returns_with_dates([x_map[t] for t in common], common)
            y_returns, _ = _stat_returns_with_dates([y_map[t] for t in common], common)
            if capability_id in ("D-E11", "D-A12"):
                envelope = run_capability(
                    capability_id,
                    x=x_returns,
                    y=y_returns,
                    dates=x_dates,
                    x_name=symbol,
                    y_name=peer,
                )
            elif capability_id == "D-A11":
                envelope = run_capability(
                    "D-A11",
                    x=x_returns,
                    y=y_returns,
                    dates=x_dates,
                    name=f"{symbol}/{peer}",
                )
            else:
                envelope = run_capability(
                    "D-E05",
                    x=x_returns,
                    y=y_returns,
                    dates=x_dates,
                    x_name=symbol,
                    y_name=peer,
                )
        except Exception as e:  # noqa: BLE001  FAIL-OPEN
            return {
                "success": True,
                "degraded": True,
                "answer": f"相关性计算异常: {e}",
                "data": None,
                "capability": capability_id,
            }
        result = _stat_result(envelope)
        if x_candles.close_anchor != y_candles.close_anchor:
            result["answer"] += "（两侧收盘锚点不同，相关值可能偏低）"
        return result

    try:
        days = 1825 if capability_id == "D-B09" else 730
        candles = load_candles(symbol, bar="1d", days=days)
    except CandleError as e:
        return {
            "success": True,
            "degraded": True,
            "answer": f"{symbol} K线数据不可用，暂无法计算该统计（{e}）",
            "data": None,
            "capability": capability_id,
        }

    if capability_id == "D-G22":
        # 显著性推断：日收益序列 → Q06 HAC t + Q07 Deflated Sharpe（n<250 由能力层 FAIL-OPEN）
        try:
            envelope = run_capability(
                "D-G22", series=_stat_returns(list(candles.close)), name=symbol
            )
        except Exception as e:  # noqa: BLE001  FAIL-OPEN
            return {
                "success": True,
                "degraded": True,
                "answer": f"显著性推断计算异常: {e}",
                "data": None,
                "capability": "D-G22",
            }
        return _stat_result(envelope)

    if capability_id == "D-A06":
        kwargs = {
            "values": list(candles.close),
            "dates": _stat_dates(candles.ts),
            "name": f"{symbol} 价格",
            "symbol": symbol,
        }
    else:
        kwargs = {"prices": list(candles.close), "symbol": symbol}
    if capability_id == "D-E03":
        kwargs["dates"] = _stat_dates(candles.ts)
        kwargs["is_returns"] = False
    elif capability_id == "D-E02":
        # percentile_forward(prices, dates, ...)：PIT 口径需要 UTC 日期轴
        kwargs["dates"] = _stat_dates(candles.ts)
    elif capability_id == "D-E07":
        kwargs["is_returns"] = False
    elif capability_id == "D-E10" or capability_id in _STAT_PRICE_DATE_CAPS:
        # 回撤/趋势/动量/波动率目标共用 UTC 日期轴，供质量块与图形输出。
        kwargs["dates"] = _stat_dates(candles.ts)
    try:
        envelope = run_capability(capability_id, **kwargs)
    except Exception as e:  # noqa: BLE001  FAIL-OPEN
        return {
            "success": True,
            "degraded": True,
            "answer": f"{capability_id} 统计计算异常: {e}",
            "data": None,
            "capability": capability_id,
        }
    return _stat_result(envelope)


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
        return {
            "success": True,
            "need_clarification": True,
            "answer": "请问您想查询哪个币种？（如：以太坊、BTC、黄金）",
            "data": None,
        }
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
        "data": {
            "symbol": symbol,
            "score": score,
            "rank": rank,
            "phase": phase,
            "valuation_percentile": pct,
        },
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


def settle_to_cognitive(intent, message, result, trace_id=""):
    """沉淀分流入口 (SPEC v1.0 §3.5): 成功→案例库；有价值的探索发现→认知系统。

    P1.3 起实现上收至 L0（core.l0_foundation.L0Foundation.settle），行为不变，FAIL-OPEN。
    trace_id（执行链 SPEC §6.2）随 context 透传，案例库按 trace 关联，不用 task_id 冒充。
    """
    context = {"intent": intent, "message": message}
    if trace_id:
        context["trace_id"] = trace_id
    get_l0().settle(result, context)


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
    "monetary_policy": "货币政策",
    "crypto_regulation": "加密监管",
    "us_policy": "美国政策",
    "us_data": "美国经济数据",
    "geopolitics": "地缘政治",
    "market": "行情动态",
    "project": "项目动态",
}


def _match_event_type(message):
    """从用户消息匹配事件类型（多关键词命中取首个）。"""
    for etype, kws in _EVENT_TYPE_KEYWORDS.items():
        for kw in kws:
            if kw in (message or ""):
                return etype
    return None


# ── L1 新闻检索（SPEC-41-L1-新闻意图检索 §7）：news_digest.json / hot_news.json ──
# 数据源分工（§5.4 窗口三级）：
#   24h  → hot_news.json（榜单，带 5 维 importance 与 clusters）
#   168h / 720h → news_digest.json（全量 + 30 天，39 域日更产出）
_NEWS_SYS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "39-金融语义蒸馏系统")
)
_NEWS_DIGEST_PATH = os.environ.get("NEWS_DIGEST_PATH") or os.path.join(
    _NEWS_SYS_DIR, "news_digest.json"
)
_HOT_NEWS_PATH = os.environ.get("HOT_NEWS_PATH") or os.path.join(_NEWS_SYS_DIR, "hot_news.json")

# 窗口触发词（§5.4）：历史词优先判定，避免「上周…最近」被 24h 抢走
_NEWS_WINDOW_HISTORY = (
    "上周",
    "上月",
    "更早",
    "之前",
    "历史",
    "这个月",
    "本月",
    "30天",
    "30 天",
    "近一个月",
    "近30日",
)
_NEWS_WINDOW_NOW = ("最新", "今天", "今日", "刚刚", "24小时", "24 小时", "现在", "当天")

_NEWS_TOPIC_RULES = None


def _news_topic_rules():
    """读取 39 的 canonical topic 词表（与打标同源 → 映射零误差）；失败返回空。

    词表 = 打标关键词 + 主题中文标签（如「地缘政治」本身不是打标词，但是主题名）。
    """
    global _NEWS_TOPIC_RULES
    if _NEWS_TOPIC_RULES is None:
        try:
            from gen_semantic_events import TOPIC_LABELS, TOPIC_RULES

            _NEWS_TOPIC_RULES = tuple(
                (t, tuple(str(k) for k in kws) + ((TOPIC_LABELS.get(t) or ""),))
                for t, _label, kws in TOPIC_RULES
            )
        except Exception:  # noqa: BLE001
            _NEWS_TOPIC_RULES = ()
    return _NEWS_TOPIC_RULES


_CN_NUM = {
    "一": 1,
    "两": 2,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _news_window(message):
    """窗口三级 → (window_h, source)。"""
    msg = message or ""
    if any(w in msg for w in _NEWS_WINDOW_HISTORY):
        return 720, "news_digest"
    if any(w in msg for w in _NEWS_WINDOW_NOW):
        return 24, "hot_news"
    return 168, "news_digest"


def _news_topic(message):
    msg = (message or "").lower()
    for topic, kws in _news_topic_rules():
        if any(kw and kw.lower() in msg for kw in kws):
            return topic
    return None


def _news_sentiment(message):
    msg = message or ""
    if any(w in msg for w in ("利好", "看多", "正面", "大涨")):
        return "利好"
    if any(w in msg for w in ("利空", "看空", "负面", "大跌")):
        return "利空"
    if "中性" in msg:
        return "中性"
    return None


def _news_importance_min(message):
    msg = message or ""
    return 70 if any(w in msg for w in ("重要", "关键", "高影响", "重大", "要紧")) else 0


def _news_keywords(message):
    """实体别名展开（与 39 query_entity 同源）+ 原词。无实体返回空（不做标题过滤）。"""
    sym = _resolve_symbol(message)
    if not sym:
        return []
    kws = [sym] + [a for a in ENTITY_ALIASES.get(sym, []) if a and len(a) >= 2]
    return kws


def _news_limit(message):
    m = re.search(r"([0-9]+|[一二两三四五六七八九十])\s*(?:条|个|则|篇)", message or "")
    if not m:
        return 5
    token = m.group(1)
    n = int(token) if token.isdigit() else _CN_NUM.get(token, 5)
    return max(1, min(n, 10))


def _news_load(source):
    path = _HOT_NEWS_PATH if source == "hot_news" else _NEWS_DIGEST_PATH
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def _news_normalize(payload, source):
    raw = payload.get("top") if source == "hot_news" else payload.get("items")
    out = []
    for it in raw or []:
        if not isinstance(it, dict):
            continue
        senti = it.get("sentiment") if isinstance(it.get("sentiment"), dict) else {}
        out.append(
            {
                "ts": it.get("published_at") if source == "hot_news" else it.get("ts"),
                "title": str(it.get("title") or it.get("title_short") or ""),
                "topic": it.get("topic") or "other",
                "sentiment": senti.get("label"),
                "importance": it.get("importance"),
                "origin": it.get("origin"),
                "source_url": it.get("source_url"),
            }
        )
    return out


def _news_unclassified_ratio(payload):
    dist = payload.get("topic_dist") or (payload.get("stats") or {}).get("topic_dist") or {}
    total = sum(v for v in dist.values() if isinstance(v, int)) or 0
    if not total:
        return 0.0
    return round(dist.get("other", 0) / total, 4)


def _news_coverage_note(payload, source):
    if source == "hot_news":
        return "榜单口径：近 24h top50，无历史纵深"
    cov = payload.get("coverage") or {}
    zeros = [d for d, n in sorted(cov.items()) if not n]
    if not zeros:
        return ""
    head = "、".join(zeros[:3])
    extra = f" 等 {len(zeros)} 天" if len(zeros) > 3 else ""
    return f"{head}{extra}无数据（采集异常）"


def _news_window_label(window_h):
    if window_h == 24:
        return "24 小时"
    return f"{window_h // 24} 天"


def exec_news_search(message):
    """L1 新闻检索（SPEC-41-L1 §7）：按标题关键词 + 39 标签检索新闻条目。

    硬约束：0 命中禁止编造（输出覆盖数与未分类占比）、topic=other 不过滤、
    产物缺失 FAIL-OPEN、全程零 token。
    """
    window_h, source = _news_window(message)
    topic = _news_topic(message)
    sentiment = _news_sentiment(message)
    importance_min = _news_importance_min(message)
    keywords = _news_keywords(message)
    limit = _news_limit(message)
    span = _news_window_label(window_h)

    payload, err = _news_load(source)
    if payload is None:
        return {
            "success": True,
            "intent": "event_listing",
            "handled": True,
            "degraded": True,
            "answer": "新闻检索库暂不可用（产物尚未生成），可稍后重试",
            "data": {
                "window_h": window_h,
                "source": source,
                "matched": 0,
                "scanned": 0,
                "coverage_note": f"产物缺失：{err}",
                "unclassified_ratio": None,
                "items": [],
            },
        }

    items = _news_normalize(payload, source)
    scanned = len(items)
    ratio = _news_unclassified_ratio(payload)
    note = _news_coverage_note(payload, source)

    # 标签过滤：topic 仅当 != other 时生效（§7.3 硬约束 2）
    topic_filter = topic if topic and topic != "other" else "none"
    hits = []
    for it in items:
        title_low = (it["title"] or "").lower()
        if keywords and not any(k.lower() in title_low for k in keywords):
            continue
        if topic_filter != "none" and it["topic"] != topic_filter:
            continue
        if sentiment and it["sentiment"] != sentiment:
            continue
        if importance_min and (it["importance"] or 0) < importance_min:
            continue
        hits.append(it)

    # 排序：importance DESC, ts DESC（先按 ts 倒序，再稳定按 importance 倒序）
    hits.sort(key=lambda x: x["ts"] or "", reverse=True)
    hits.sort(key=lambda x: x["importance"] or 0, reverse=True)
    top = hits[:limit]

    if not hits:
        who = "/".join(keywords) if keywords else "该条件"
        answer = (
            f"近 {span}未检索到与『{who}』相关的新闻"
            f"（当期共 {scanned} 条，其中未分类 {int(ratio * 100)}%）"
        )
        if note:
            answer += f"；注意：{note}"
    else:
        lines = []
        for i, it in enumerate(top, 1):
            ts = (it["ts"] or "")[:16].replace("T", " ")
            senti = it["sentiment"] or "未知"
            imp = it["importance"]
            imp_txt = f"{imp:.1f}" if isinstance(imp, (int, float)) else "-"
            lines.append(f"{i}. [{ts}] {it['title']}（{it['topic']}/{senti}/影响 {imp_txt}）")
        answer = (
            f"近 {span}检索到 {len(hits)} 条相关新闻"
            f"（当期共 {scanned} 条，未分类 {int(ratio * 100)}%，展示前 {len(top)} 条）：\n"
            + "\n".join(lines)
        )
        if note:
            answer += f"\n注意：{note}"

    return {
        "success": True,
        "intent": "event_listing",
        "handled": True,
        "degraded": False,
        "answer": answer,
        "data": {
            "window_h": window_h,
            "source": source,
            "matched": len(hits),
            "scanned": scanned,
            "coverage_note": note,
            "unclassified_ratio": ratio,
            "topic_filter": topic_filter,
            "sentiment_filter": sentiment,
            "importance_min": importance_min,
            "keywords": keywords,
            "items": top,
        },
    }


def exec_event_listing(message):
    """【legacy】旧版事件罗列（newsflash od_event_type 口径）：保留可调用，不参与主链路。"""
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
        items.append(
            {
                "time": (ts or "")[:16],
                "type": row_type,
                "summary": desc[:100],
                "tickers": tickers[:3],
                "sentiment": sentiment,
            }
        )
        if len(items) >= 10:
            break
    if not items:
        return {"success": True, "legacy": True, "answer": "近期未找到相关事件快讯", "data": []}
    type_desc = _EVENT_TYPE_DESC_L1.get(etype, "全部") if etype else "全部"
    lines = []
    for i, it in enumerate(items, 1):
        tick = f" | 关联: {','.join(it['tickers'])}" if it["tickers"] else ""
        lines.append(f"{i}. [{it['time']}] {it['summary']}{tick}（情绪:{it['sentiment']}）")
    answer = f"近期{type_desc}事件（按时间倒序，共 {len(items)} 条）：\n" + "\n".join(lines)
    # 层间钩子 (SPEC v1.3 §9.7): 基于罗列内容动态生成 L2 引导
    hint = None
    if etype:
        hint = f"想了解{type_desc}事件的整体演变与量变趋势吗？可问：{type_desc}事件怎么演变"
    else:
        hint = "想深入了解某类事件线的演变吗？可问：加密监管事件怎么演变"
    return {
        "success": True,
        "legacy": True,
        "answer": answer,
        "next_layer_hint": hint,
        "data": {"event_type": etype, "items": items},
    }


# ── L2 事件线查询 (39 SPEC v1.2 §9.7): 消费 event_lines.json ──
_EVENT_LINES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..",
    "39-金融语义蒸馏系统",
    "event_lines.json",
)


def exec_event_line_query(message):
    """L2 事件线查询: 同主题事件聚合 + 时间标签 + 变化描述（观察性）。"""
    try:
        with open(_EVENT_LINES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {
            "success": True,
            "degraded": True,
            "answer": "事件线数据暂不可用（尚未生成）",
            "data": None,
        }
    lines = data.get("lines", [])
    if not lines:
        return {"success": True, "answer": "暂无事件线数据", "data": []}
    # 匹配主题（消息含主题关键词或主题名）
    matched = None
    for l in lines:  # noqa: E741
        if l["topic"] in (message or ""):
            matched = l
            break
    if matched is None:
        for l in lines:  # noqa: E741
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
        l = matched  # noqa: E741
        items = "\n".join(f"  · [{it['time']}] {it['summary']}" for it in l["recent_items"])
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
            hint = (
                f"【{l['topic']}】量变正在加速积累，是否深入观察窗口分布与情绪变化？"
                f"（L3 多因子综合即将上线）"
            )
        elif "温和积累" in qsig or "消退" in qsig:
            hint = f"想看【{l['topic']}】的量变窗口分布详情吗？可追问：{l['topic']}量变分布"
        else:
            hint = f"想结合市场指标看【{l['topic']}】的综合状态吗？（L3 上线后可用）"
        return {"success": True, "answer": answer, "next_layer_hint": hint, "data": l}
    # 未匹配主题：罗列全部事件线概览
    overview = "\n".join(
        f"  · {l['topic']}: {l['event_count']} 事件, 跨度 {l['span_hours']}h, "
        f"频次{l['freq_trend']}, {l['sentiment_trend']}"
        for l in lines  # noqa: E741
    )
    return {
        "success": True,
        "answer": f"当前事件线概览（可追问具体主题如『加密监管事件怎么演变』）：\n{overview}",
        "data": {
            "lines": [{"topic": l["topic"], "count": l["event_count"]} for l in lines]  # noqa: E741
        },  # noqa: E741
    }


def exec_doc_search(message: str):
    """L1 文档检索（41 SPEC §7.10-1 / §13.1-A3）：零 token，桥接 41 BM25 倒排索引。"""
    import re as _re
    import subprocess as _sp

    # 从问法中提取查询词：去掉检索动词与文档类名词
    q = _re.sub(r"(帮我|请|查一下|查|搜一下|搜|找一下|找|检索|搜索|一下)", "", message)
    q = _re.sub(r"(的)?(文档|资料|SPEC|规范|手册|指南|知识库|wiki|在哪|位置|路径|全文检索)", "", q)
    q = q.strip() or message
    try:
        proc = _sp.run(
            ["/home/ubuntu/fis-p0/.venv/bin/python", "/home/ubuntu/fis-p0/scripts/search_cli.py"],
            input=json.dumps({"query": q, "limit": 8}),
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, "FIS_PG_PASSWORD": os.environ.get("FIS_PG_PASSWORD")},
        )
        res = json.loads(proc.stdout or "{}")
        hits = res.get("hits", []) if res.get("success") else []
        if not hits:
            return {
                "success": True,
                "answer": f"未找到与『{q}』相关的文档",
                "data": {"query": q, "hits": []},
            }
        lines = [
            f"{i + 1}. {h['source']['path']}（相关度 {h['score']:.2f}）"
            for i, h in enumerate(hits[:8])
        ]
        return {
            "success": True,
            "answer": "找到 %d 篇相关文档：" % len(hits) + chr(10).join(lines),
            "data": {
                "query": q,
                "hits": [
                    {"path": h["source"]["path"], "score": h["score"], "type": h["type"]}
                    for h in hits[:8]
                ],
            },
        }
    except Exception as e:
        return {"success": True, "degraded": True, "answer": f"文档检索暂不可用: {e}", "data": None}


def exec_leader_compare(message):
    """钩子 2：同赛道龙头对照（同期涨跌幅差 + 日变动相关）。"""
    syms = _symbols_in_message(message)
    symbol = syms[0] if syms else _resolve_symbol(message)
    if not symbol:
        return {
            "success": True,
            "need_clarification": True,
            "answer": "请问要对比哪个资产与同赛道龙头？（如：以太坊和比特币）",
            "data": None,
        }
    peer = syms[1] if len(syms) > 1 else None
    try:
        out = _leader_gap(_DAL_DB_PATH, symbol, peer=peer)
    except (_RelationError, _AlignError, _PriceEchoError) as exc:
        return {
            "success": True,
            "degraded": True,
            "answer": f"{symbol} 与龙头对照不可用：{exc}",
            "data": None,
        }
    return _attach_hooks(
        {"success": True, "answer": out["text"], "data": out},
        symbol,
    )


def exec_top_correlation(message):
    """钩子 3：与目标资产相关性最高的指标（Pearson + BH-FDR）。"""
    syms = _symbols_in_message(message)
    symbol = syms[0] if syms else _resolve_symbol(message)
    if not symbol:
        return {
            "success": True,
            "need_clarification": True,
            "answer": "请问要查哪个资产的相关性指标？（如：以太坊）",
            "data": None,
        }
    try:
        out = _top_correlated(_DAL_DB_PATH, symbol, top_k=5)
    except (_RelationError, _AlignError, _PriceEchoError) as exc:
        return {
            "success": True,
            "degraded": True,
            "answer": f"{symbol} 相关性扫描不可用：{exc}",
            "data": None,
        }
    return _attach_hooks(
        {"success": True, "answer": out["text"], "data": out},
        symbol,
    )


def exec_persistence_strength(message):
    """钩子 4：历史周期下的趋势延续性强度（Hurst / VR / AR1 / 连涨连跌）。"""
    syms = _symbols_in_message(message)
    symbol = syms[0] if syms else _resolve_symbol(message)
    if not symbol:
        return {
            "success": True,
            "need_clarification": True,
            "answer": "请问要评估哪个资产的趋势延续性？（如：比特币、以太坊）",
            "data": None,
        }
    try:
        out = _persistence_strength(_DAL_DB_PATH, symbol)
    except (_RelationError, _AlignError, _PriceEchoError) as exc:
        return {
            "success": True,
            "degraded": True,
            "answer": f"{symbol} 延续性强度不可用：{exc}",
            "data": None,
        }
    return _attach_hooks(
        {"success": True, "answer": out["text"], "data": out},
        symbol,
    )


def exec_price_query(message):
    """价格查询: 经 L0 直连 OKX API 获取实时价格，失败降级回查 18 中心。"""
    # SPEC v1.5: 别名表统一解析，无币种时澄清追问（不再静默默认 BTC）
    symbol = _resolve_symbol(message)
    if symbol is None:
        return {
            "success": True,
            "need_clarification": True,
            "answer": "请问您想查询哪个币种的价格？（如：以太坊、BTC、黄金）",
            "data": None,
        }
    inst_id = f"{symbol}-USDT"
    ctx = get_l0().fetch_context("market.ticker", {"symbol": symbol})
    t = None if ctx.get("degraded") else ctx["data"]

    # 历史时点 → 价格回显（asof）：当时价 + 现价 + 变化，验证对齐层
    at_day = find_past_day_reference(message)
    if at_day:
        live_price = live_ts = None
        try:
            if t and t.get("last"):
                live_price = float(t["last"])
                live_ts = int(t.get("ts", 0)) // 1000 or None
        except (TypeError, ValueError):
            live_price = None
        try:
            series = _load_leader(_DAL_DB_PATH, symbol, days=1825)
            echo = price_echo(
                series,
                at_day,
                symbol=symbol,
                now_price=live_price,
                now_ts=live_ts,
                source=("okx_ticker+dal_mm_metrics" if live_price else "dal_mm_metrics"),
            )
            return _attach_hooks(
                {"success": True, "answer": format_echo(echo), "data": echo},
                symbol,
                at_day=at_day,
            )
        except (_PriceEchoError, _AlignError) as exc:
            return {
                "success": True,
                "degraded": True,
                "answer": f"{symbol} 在 {at_day} 的价格回显不可用：{exc}",
                "data": None,
            }

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
        return _attach_hooks(
            {
                "success": True,
                "answer": (
                    f"{symbol} 实时价格（OKX {inst_id}）：{last} USDT，"
                    f"24h涨跌 {sign}{chg:.2f}%，24h最高 {high}，最低 {low}"
                ),
                "data": {
                    "symbol": symbol,
                    "inst_id": inst_id,
                    "last": last,
                    "open24h": open24h,
                    "high24h": high,
                    "low24h": low,
                    "change_pct": round(chg, 2),
                    "source": "okx",
                },
            },
            symbol,
        )
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
        elif intent == "technical_indicator":
            result = exec_technical_indicator(message)
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
        elif intent == "leader_compare":
            result = exec_leader_compare(message)
        elif intent == "top_correlation":
            result = exec_top_correlation(message)
        elif intent == "persistence_strength":
            result = exec_persistence_strength(message)
        elif intent == "metric_series":
            result = exec_metric_series(message)
        elif intent == "stat_query":
            result = exec_stat_query(message)
        elif intent == "whale_flow":
            result = exec_whale_flow(message)
        elif intent == "calendar_event":
            result = exec_calendar_event(message)
        elif intent == "event_listing":
            result = exec_event_listing(message)
        elif intent == "event_line_query":
            result = exec_event_line_query(message)
        elif intent == "doc_search":
            result = exec_doc_search(message)
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
