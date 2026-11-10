"""文章因素抽象抽取器 — SPEC-D1-MULTIDIM-STATE §2.5（P0.5 前置门禁）。

三层流水线（规则版，非 LLM）：
  F1 因素识别：6 大类 60 细类本体，最长别名优先，输出证据 span
  F2 单因素方向：证据句 ±1 句窗口内判多空，hedged/strong 区分强度
  F3 多因素合成：按 9 域模块权重加权 → composite direction/score

设计边界（用户方法论）：只输出 (factor, direction, strength, span)，
不做语义摘要、不做情感长文分析、不做 LLM 推理。

FAIL-OPEN：任何异常返回空结构，不抛。
"""

from __future__ import annotations

import logging

from data_center.processing.dimension_context import ALL_DIMENSIONS, DIMENSION_MAP

logger = logging.getLogger("data_center.processing.factor_extractor")

# ── F1 因素本体：6 大类 × 10 细类（别名用于术语匹配）───────────

FACTOR_ONTOLOGY: dict[str, dict[str, list[str]]] = {
    "technical": {
        "trend": ["趋势", "均线", "MA", "EMA", "多头排列", "空头排列", "上升通道", "下降通道"],
        "momentum": ["RSI", "MACD", "KDJ", "动量", "超买", "超卖", "技术性背离"],
        "level": ["支撑位", "阻力位", "关键支撑", "关键阻力", "前高", "前低", "关键位", "颈线"],
        "volume": ["成交量", "放量", "缩量", "量价背离", "成交额", "换手率"],
        "pattern": ["形态", "头肩", "三角形", "旗形", "双底", "双顶", "楔形"],
        "ma_cross": ["金叉", "死叉", "均线交叉"],
        "volatility": ["波动率", "ATR", "布林带", "带宽"],
        "fib": ["斐波那契", "回撤位"],
        "candlestick": ["K线", "阳线", "阴线", "十字星", "长上影"],
        "trendline": ["趋势线", "上升趋势线", "下降趋势线"],
    },
    "flow": {
        "funding": ["资金费率", "资金费", "费率", "funding rate"],
        "oi": ["未平仓合约", "持仓量", "持仓", "OI"],
        "long_short": ["多空比", "多头持仓", "空头持仓", "多空持仓比"],
        "etf_flow": ["ETF净流入", "ETF净流出", "ETF资金", "ETF流入"],
        "stablecoin": ["稳定币增发", "USDT增发", "USDC增发", "稳定币流入"],
        "exchange_netflow": ["交易所净流入", "交易所净流出", "交易所余额", "交易所储备"],
        "whale": ["巨鲸", "鲸鱼", "大额转账", "大户持仓"],
        "liquidation": ["爆仓", "清算", "强平", "多头爆仓", "空头爆仓"],
        "taker": ["主动买入", "主动卖出", "taker"],
        "etf_premium": ["溢价", "折价", "GBTC"],
    },
    "onchain": {
        "active_addr": ["活跃地址", "地址数", "新增地址"],
        "hashrate": ["哈希率", "算力", "矿工", "挖矿难度"],
        "mvrv": ["MVRV", "市值实现值比"],
        "sopr": ["SOPR", "已花费产出利润率"],
        "nupl": ["NUPL", "净未实现盈亏"],
        "holder": ["持币地址", "长期持有者", "筹码分布", "巨鲸地址"],
        "tvl": ["TVL", "锁仓量", "总锁仓"],
        "gas": ["Gas费", "网络拥堵", "链上手续费"],
        "exchange_supply": ["交易所存量", "交易所持有量"],
        "realized_cap": ["已实现市值", "实现价格"],
    },
    "macro": {
        "rate": ["美联储", "加息", "降息", "利率", "联邦基金"],
        "inflation": ["CPI", "PCE", "通胀", "物价指数"],
        "employment": ["非农", "失业率", "就业数据"],
        "liquidity": ["流动性", "缩表", "扩表", "QE", "QT", "逆回购"],
        "dollar": ["美元指数", "DXY", "美元走强", "美元走弱"],
        "treasury": ["美债", "国债收益率", "期限利差", "十年期"],
        "equity": ["美股", "纳斯达克", "标普", "风险资产"],
        "gdp": ["GDP", "经济增速", "经济衰退"],
        "central_bank": ["央行", "欧洲央行", "日本央行", "中国人民银行"],
        "credit": ["高收益债", "信用利差", "主权违约"],
    },
    "event": {
        "regulation": ["监管", "SEC", "政策", "合规", "立法"],
        "etf_approval": ["ETF获批", "ETF通过", "ETF申请", "ETF审批"],
        "hack": ["黑客", "被盗", "漏洞", "安全事件", "攻击事件"],
        "unlock": ["解锁", "代币释放", "线性释放", "悬崖解锁"],
        "listing": ["上线", "上所", "首发上线", "下架", "摘牌"],
        "partnership": ["战略合作", "达成合作", "深度合作"],
        "funding_round": ["A轮融资", "B轮融资", "种子轮", "领投", "投资轮"],
        "legal": ["诉讼", "罚款", "和解", "起诉"],
        "upgrade": ["升级", "硬分叉", "主网上线", "网络升级"],
        "airdrop": ["空投", "空投快照"],
    },
    "sentiment": {
        "fear_greed": ["恐慌", "贪婪", "恐惧贪婪指数", "情绪指数"],
        "social_heat": ["社交热度", "讨论量", "搜索量", "关注度"],
        "narrative": ["叙事", "板块轮动", "热点", "主题投资"],
        "retail": ["散户", "新手入场", "韭菜", "FOMO"],
        "institutional": ["机构投资者", "机构资金", "机构入场", "对冲基金", "上市公司", "主权基金"],
        "analyst": ["分析师", "研报", "目标价", "分析师预测"],
        "community": ["社区", "社群", "KOL", "大V"],
        "halving": ["减半", "产量减半"],
        "cycle": ["市场周期", "牛熊周期", "四年周期", "周期顶部", "周期底部"],
        "altseason": ["山寨季", "山寨币季节", "轮动行情"],
    },
}

# ── F3 合成权重（来自 9 域 signal_engine 模块权重口径）───────────

CATEGORY_WEIGHTS: dict[str, float] = {
    "flow": 1.5,
    "onchain": 1.3,
    "macro": 1.2,
    "technical": 1.1,
    "event": 1.0,
    "sentiment": 1.0,
}

# ── F2 方向词 ────────────────────────────────────────────────

_BULL_WORDS = [
    "上涨",
    "走强",
    "利好",
    "反弹",
    "突破",
    "拉升",
    "新高",
    "看涨",
    "牛市",
    "上行",
    "看多",
    "增持",
    "流入",
    "宽松",
    "放水",
    "降息",
    "获批",
    "通过",
    "超预期",
    "提振",
    "乐观",
    "买入",
    "加仓",
    "筑底",
    "低估",
]

_BEAR_WORDS = [
    "下跌",
    "走弱",
    "利空",
    "回调",
    "抛压",
    "暴跌",
    "崩盘",
    "新低",
    "看跌",
    "熊市",
    "下行",
    "减持",
    "流出",
    "收紧",
    "缩表",
    "加息",
    "否决",
    "推迟",
    "低于预期",
    "打压",
    "悲观",
    "卖出",
    "减仓",
    "见顶",
    "超买",
    "高估",
]

_HEDGED_WORDS = ["可能", "或将", "或许", "预计", "有望", "存在", "若"]

_STRONG_WORDS = ["大幅", "显著", "明确", "必然", "确定", "强劲", "剧烈"]

_SENT_DELIMS = "。！？\n；;"


def _split_sentences(text: str) -> list[tuple[int, int]]:
    """返回句子 (start, end) 边界列表。"""
    out: list[tuple[int, int]] = []
    start = 0
    for i, ch in enumerate(text):
        if ch in _SENT_DELIMS:
            if i + 1 > start:
                out.append((start, i + 1))
            start = i + 1
    if len(text) > start:
        out.append((start, len(text)))
    return out


def _build_alias_index() -> list[tuple[str, str, str, str]]:
    """(alias, factor_id, category, subtype)，按 alias 长度降序（最长优先）。"""
    idx: list[tuple[str, str, str, str]] = []
    for cat, subs in FACTOR_ONTOLOGY.items():
        for sub, aliases in subs.items():
            fid = f"{cat}.{sub}"
            for a in aliases:
                idx.append((a, fid, cat, sub))
    idx.sort(key=lambda x: len(x[0]), reverse=True)
    return idx


_ALIAS_INDEX = _build_alias_index()


def _find_matches(text: str) -> list[tuple[int, int, str, str, str, str]]:
    """最长别名优先 + 位置占用去重，返回 (start, end, alias, factor_id, cat, sub)。"""
    occupied = [False] * len(text)
    out: list[tuple[int, int, str, str, str, str]] = []
    for alias, fid, cat, sub in _ALIAS_INDEX:
        start = 0
        while True:
            i = text.find(alias, start)
            if i < 0:
                break
            end = i + len(alias)
            if not any(occupied[i:end]):
                for j in range(i, end):
                    occupied[j] = True
                out.append((i, end, alias, fid, cat, sub))
            start = end
    return out


def _judge_direction(window: str) -> tuple[str, str]:
    """窗口内判方向与强度 → (direction, strength)。"""
    bull = sum(window.count(w) for w in _BULL_WORDS)
    bear = sum(window.count(w) for w in _BEAR_WORDS)
    if bull > bear:
        direction = "bullish"
    elif bear > bull:
        direction = "bearish"
    else:
        direction = "neutral"

    if any(w in window for w in _HEDGED_WORDS):
        strength = "hedged"
    elif any(w in window for w in _STRONG_WORDS):
        strength = "strong"
    else:
        strength = "moderate"
    return direction, strength


def extract_factors(text: object) -> list[dict]:
    """F1+F2：返回 [{factor_id, category, subtype, count, direction, strength, evidence}]。

    FAIL-OPEN：非字符串/异常返回 []。
    """
    try:
        if not isinstance(text, str) or not text.strip():
            return []
        sents = _split_sentences(text)
        if not sents:
            return []

        matches = _find_matches(text)
        if not matches:
            return []

        # 句子索引：记录每个命中落在第几句
        def _sent_idx(pos: int) -> int:
            for k, (s, e) in enumerate(sents):
                if s <= pos < e:
                    return k
            return 0

        grouped: dict[str, dict] = {}
        for start, end, alias, fid, cat, sub in matches:
            g = grouped.setdefault(
                fid,
                {
                    "factor_id": fid,
                    "category": cat,
                    "subtype": sub,
                    "count": 0,
                    "evidence": [],
                    "_sent_ids": set(),
                },
            )
            g["count"] += 1
            g["evidence"].append(
                {
                    "alias": alias,
                    "span": [start, end],
                    "text": text[sents[_sent_idx(start)][0] : sents[_sent_idx(start)][1]],
                }
            )
            g["_sent_ids"].add(_sent_idx(start))

        out: list[dict] = []
        for fid, g in grouped.items():
            # 上下文窗口：证据句 ±1 句
            win_ids: set[int] = set()
            for si in g["_sent_ids"]:
                for d in (-1, 0, 1):
                    if 0 <= si + d < len(sents):
                        win_ids.add(si + d)
            window = "".join(text[s:e] for s, e in (sents[k] for k in sorted(win_ids)))
            direction, strength = _judge_direction(window)
            out.append(
                {
                    "factor_id": fid,
                    "category": g["category"],
                    "subtype": g["subtype"],
                    "count": g["count"],
                    "direction": direction,
                    "strength": strength,
                    "evidence": g["evidence"],
                }
            )
        out.sort(key=lambda h: (-h["count"], h["factor_id"]))
        return out
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] extract_factors 异常 %s: %s", type(e).__name__, str(e)[:200])
        return []


def extract_article_factors(text: object, doc_id: str = "") -> dict:
    """F1+F2+F3：整篇文章的因素清单 + 合成方向。FAIL-OPEN。"""
    try:
        factors = extract_factors(text)
        num = 0.0
        den = 0.0
        for f in factors:
            w = CATEGORY_WEIGHTS.get(f["category"], 1.0)
            sign = (
                1.0 if f["direction"] == "bullish" else -1.0 if f["direction"] == "bearish" else 0.0
            )
            num += sign * w
            den += w
        score = (num / den) if den else 0.0
        if score > 0.15:
            direction = "bullish"
        elif score < -0.15:
            direction = "bearish"
        else:
            direction = "neutral"
        return {
            "doc_id": doc_id,
            "factors": factors,
            "n_factors": len(factors),
            "categories": sorted({f["category"] for f in factors}),
            "composite": {"direction": direction, "score": round(score, 4)},
        }
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning(
            "[FAIL-OPEN] extract_article_factors 异常 %s: %s", type(e).__name__, str(e)[:200]
        )
        return {
            "doc_id": doc_id,
            "factors": [],
            "n_factors": 0,
            "categories": [],
            "composite": {"direction": "neutral", "score": 0.0},
        }


# ── F3 主导因素主张（claim）— SPEC §2.5.1 / D8 ─────────────────
# 主张提取，不是信号合成：抽出"作者认为哪个因素主导、指向哪个方向"。

_HORIZON_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("intraday", ("日内", "今日", "今天", "24小时", "盘中", "短线")),
    ("days", ("本周", "这周", "短期", "近期", "未来几天")),
    ("weeks", ("本月", "中期", "未来几周", "数周")),
    ("months", ("长期", "季度", "半年")),
]

_HORIZON_URGENCY = {"intraday": 0.9, "days": 0.6, "weeks": 0.35, "months": 0.2}

_CONFIDENCE_BY_STRENGTH = {"strong": 0.8, "moderate": 0.6, "hedged": 0.35}


def _detect_horizon(text: str) -> str:
    for horizon, kws in _HORIZON_RULES:
        if any(kw in text for kw in kws):
            return horizon
    return "days"


def extract_dominance_claim(text: object, doc_id: str = "", published_at: str = "") -> dict:
    """F3：主导因素主张（DominanceClaim）。FAIL-OPEN。"""
    empty = {
        "claim_type": "dominance",
        "doc_id": doc_id,
        "published_at": published_at,
        "dominant_factor": None,
        "dominant_dimension": None,
        "direction": "neutral",
        "horizon": "days",
        "confidence_in_text": 0.0,
        "urgency": _HORIZON_URGENCY["days"],
        "impact": 1.0,
        "supporting_factors": [],
        "opposing_factors": [],
        "salience_distribution": dict.fromkeys(ALL_DIMENSIONS, 0.0),
        "evidence_spans": [],
    }
    try:
        factors = extract_factors(text)
        if not factors:
            return empty

        dist = dict.fromkeys(ALL_DIMENSIONS, 0.0)
        for f in factors:
            dim = DIMENSION_MAP.get(f["category"])
            if dim:
                dist[dim] += f["count"] * CATEGORY_WEIGHTS.get(f["category"], 1.0)
        total = sum(dist.values())
        if total > 0:
            dist = {k: round(v / total, 6) for k, v in dist.items()}

        candidates = [f for f in factors if f["direction"] != "neutral"]
        if not candidates:
            return {**empty, "salience_distribution": dist}

        candidates.sort(
            key=lambda f: (
                -(f["count"] * CATEGORY_WEIGHTS.get(f["category"], 1.0)),
                f["factor_id"],
            )
        )
        dom = candidates[0]
        direction = dom["direction"]
        text_s = text if isinstance(text, str) else ""
        horizon = _detect_horizon(text_s)

        supporting = [
            f"{f['factor_id']}:{f['direction']}"
            for f in factors
            if f is not dom and f["direction"] == direction
        ][:5]
        opposing = [
            f"{f['factor_id']}:{f['direction']}"
            for f in factors
            if f["direction"] not in ("neutral", direction)
        ][:5]

        spans = []
        for ev in dom.get("evidence", [])[:3]:
            span = ev.get("span") or [0, 0]
            spans.append({"doc_id": doc_id, "start": span[0], "end": span[1]})

        return {
            "claim_type": "dominance",
            "doc_id": doc_id,
            "published_at": published_at,
            "dominant_factor": dom["factor_id"],
            "dominant_dimension": DIMENSION_MAP.get(dom["category"]),
            "direction": direction,
            "horizon": horizon,
            "confidence_in_text": _CONFIDENCE_BY_STRENGTH.get(dom["strength"], 0.6),
            "urgency": _HORIZON_URGENCY[horizon],
            "impact": CATEGORY_WEIGHTS.get(dom["category"], 1.0),
            "supporting_factors": supporting,
            "opposing_factors": opposing,
            "salience_distribution": dist,
            "evidence_spans": spans,
        }
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning(
            "[FAIL-OPEN] extract_dominance_claim 异常 %s: %s", type(e).__name__, str(e)[:200]
        )
        return empty
