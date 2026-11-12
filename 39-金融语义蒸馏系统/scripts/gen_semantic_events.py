# -*- coding: utf-8 -*-
"""39-金融语义蒸馏系统 · P1 语义事件流生成（SPEC §7.2，零 token）

将交易日志中的术语出现记录升级为语义事件：
  语义事件 = {术语, 时间戳, 标的, 取值, 市场上下文, 后续结果}

产出: semantic_events.jsonl（持续追加流，供 P3 复杂语义衍生与 34 训练消费）

运行模式:
  --backfill  回填模式：扫描历史 trader.log，生成历史事件（一次性）
  --live      增量模式：只处理上次运行后的新增日志行（配合定时任务持续追加）

事件源模式（SPEC-EMERGENCE-FINANCIAL-ENV §3.4 / P0-A，2026-11-11）:
  --source events  读取 canonical EventRecord（18/data_center/events/events.jsonl），
                   调用 9 域 SentimentEngine 打分后追加 sentiment/event/trace_id 三个块；
                   sentiment=null 是合法状态（模型不可用），禁止填 0 冒充已打分。
                   旧行不重写，按 trace_id 幂等跳过。

用法:
  python3 gen_semantic_events.py --backfill
  python3 gen_semantic_events.py --live
  python3 gen_semantic_events.py --source events
"""

import argparse
import difflib
import importlib.util
import json
import math
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SYS_DIR = os.path.dirname(_THIS_DIR)
_REPO = os.path.dirname(_SYS_DIR)

TRADER_LOG = "/home/luke/logs/yijing/trader.log"
OUT_PATH = os.path.join(_SYS_DIR, "semantic_events.jsonl")
# 热点新闻影响力榜产物（SPEC-20261113 §5.1）；env HOT_NEWS_PATH 可覆盖
HOT_NEWS_PATH = os.path.join(_SYS_DIR, "hot_news.json")
STATE_PATH = os.path.join(_SYS_DIR, ".semantic_events_state.json")
EVENTS_PATH = os.path.join(_REPO, "18-数据获取中心", "data_center", "events", "events.jsonl")
# P1-A：中文财经正文外置存储（事件 body_ref → bodies.jsonl#<id>）
BODIES_PATH = os.path.join(_REPO, "18-数据获取中心", "data_center", "events", "bodies.jsonl")
SENTIMENT_ENGINE_PATH = os.path.join(_REPO, "9-基本面分析", "engines", "sentiment_engine.py")

# 事件类型 → 半衰期（小时），与 SPEC §3.3 表格一致；未列出的走 24h
HALF_LIFE_H = {
    "earnings": 24,
    "guidance": 24,
    "fomc": 24,
    "rate_decision": 24,
    "cpi": 24,
    "nfp": 24,
    "macro_other": 24,
    "mna": 48,
    "buyback": 48,
    "dividend": 48,
    "regulatory": 48,
    "product": 48,
    "legal": 48,
}

# ─────────────────────────────────────────────────────────────────────────────
# 热点新闻影响力榜（SPEC-20261113 §3–§5）
# 权重集中定义，改权重不需要动公式；全链路零 token。
# ─────────────────────────────────────────────────────────────────────────────
TYPE_WEIGHT = {
    "rate_decision": 1.00,
    "fomc": 0.95,
    "cpi": 0.95,
    "nfp": 0.95,
    "earnings": 0.85,
    "guidance": 0.85,
    "regulatory": 0.80,
    "legal": 0.75,
    "mna": 0.75,
    "buyback": 0.60,
    "dividend": 0.60,
    "product": 0.50,
    "macro_other": 0.40,
}
SOURCE_WEIGHT = {
    "sec_edgar": 1.00,
    "fed_calendar": 1.00,
    "macro_calendar": 0.90,
    "jin10": 0.80,
    "wallstreetcn": 0.80,
    "cls": 0.75,
    "sina_finance": 0.70,
}
DEFAULT_TYPE_WEIGHT = 0.40
DEFAULT_SOURCE_WEIGHT = 0.60
SENTIMENT_THRESHOLD = 0.15
IMPORTANCE_WEIGHTS = {
    "type": 0.30,
    "sentiment": 0.25,
    "recency": 0.20,
    "source": 0.15,
    "corroboration": 0.10,
}
DEDUP_JACCARD = 0.78
DEDUP_RATIO = 0.90
# 短中文标题单字改写（正处于/正处在，13 字）4-gram Jaccard 实测≈0.43，故 ratio 门限取 0.40；
# 仍由 ratio≥0.90 + 同 type + symbols 交集双重守卫，避免跨主题误合并
DEDUP_RATIO_MIN_JACCARD = 0.40
HOT_NEWS_WINDOW_H = 24
HOT_NEWS_CLUSTER_WINDOW_H = 48
HOT_NEWS_TOP_N = 50

# 主题簇：顺序即优先级，命中多个取最靠前（§4.1）
TOPIC_RULES = [
    (
        "rates_policy",
        "利率与央行",
        [
            "美联储",
            "FOMC",
            "降息",
            "加息",
            "利率",
            "鲍威尔",
            "点阵图",
            "逆回购",
            "欧央行",
            "日本央行",
            "LPR",
        ],
    ),
    ("inflation", "通胀", ["CPI", "PCE", "通胀", "物价", "核心通胀"]),
    ("labor", "就业", ["非农", "就业", "失业率", "ADP", "就业报告"]),
    (
        "growth",
        "增长景气",
        ["GDP", "PMI", "社融", "M2", "社零", "进出口", "工业增加值", "零售销售"],
    ),
    (
        "crypto_reg",
        "加密监管",
        ["加密", "比特币", "以太坊", "稳定币", "ETF", "SEC", "币安", "Coinbase"],
    ),
    (
        "geopolitics",
        "地缘政治",
        ["战争", "袭击", "制裁", "胡塞", "俄乌", "中东", "关税", "贸易战", "停火"],
    ),
    ("earnings", "财报业绩", ["财报", "业绩", "营收", "净利润", "EPS", "指引", "预警"]),
    (
        "capital_action",
        "资本运作",
        ["收购", "并购", "回购", "分红", "减持", "增持", "IPO", "私有化", "评级"],
    ),
    (
        "tech_ai",
        "科技与 AI",
        ["AI", "芯片", "算力", "英伟达", "OpenAI", "大模型", "半导体", "量子"],
    ),
    ("commodities", "商品", ["黄金", "原油", "天然气", "铜", "OPEC", "白银", "油价", "金价"]),
]
TOPIC_LABELS = {t: label for t, label, _ in TOPIC_RULES}
TOPIC_LABELS["other"] = "其他"


def topic_of(text):
    """标题 → 单标签主题簇；未命中返回 other。"""
    low = str(text or "").lower()
    for topic, _label, keywords in TOPIC_RULES:
        for kw in keywords:
            if kw.lower() in low:
                return topic
    return "other"


def sentiment_label(score):
    if not isinstance(score, (int, float)):
        return "未知"
    if score > SENTIMENT_THRESHOLD:
        return "利好"
    if score < -SENTIMENT_THRESHOLD:
        return "利空"
    return "中性"


def corroboration_from_source_count(n):
    """多源印证：单源 0.5 / 双源 0.815 / 三源 1.0。"""
    if n <= 1:
        return 0.5
    return round(min(1.0, 0.5 + 0.5 * math.log2(n) / math.log2(3)), 3)


def _parse_ts(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def importance_parts(
    published_at=None, etype="macro_other", sentiment=None, origin=None, source_count=1, now=None
):
    """评分分解（各 0–1）；sentiment 缺失时 S=0，但禁止用 0 冒充已打分。"""
    now = now or datetime.now(timezone.utc)
    t = TYPE_WEIGHT.get(etype, DEFAULT_TYPE_WEIGHT)
    if isinstance(sentiment, dict) and isinstance(sentiment.get("score"), (int, float)):
        score = float(sentiment["score"])
        conf = sentiment.get("confidence")
        conf = float(conf) if isinstance(conf, (int, float)) else 1.0
        s = min(1.0, abs(score) * conf)
        half_life = sentiment.get("half_life_h") or HALF_LIFE_H.get(etype, 24)
    else:
        s = 0.0
        half_life = HALF_LIFE_H.get(etype, 24)
    dt = _parse_ts(published_at)
    if dt is None:
        r = 0.0
    else:
        age_h = max(0.0, (now - dt).total_seconds() / 3600.0)
        hl = half_life if isinstance(half_life, (int, float)) and half_life > 0 else 24
        r = 0.5 ** (age_h / hl)
    return {
        "type": round(t, 3),
        "sentiment": round(s, 3),
        "recency": round(r, 3),
        "source": round(SOURCE_WEIGHT.get(str(origin or ""), DEFAULT_SOURCE_WEIGHT), 3),
        "corroboration": corroboration_from_source_count(source_count),
    }


def importance(
    published_at=None, etype="macro_other", sentiment=None, origin=None, source_count=1, now=None
):
    """importance = 100 × Σ(权重 × 分项)。"""
    parts = importance_parts(published_at, etype, sentiment, origin, source_count, now)
    total = sum(IMPORTANCE_WEIGHTS[k] * parts[k] for k in IMPORTANCE_WEIGHTS)
    return round(100.0 * total, 1), parts


# ── 去重：boilerplate 归一化 + 4-gram Jaccard / difflib ratio ──
_SOURCE_PREFIX_RE = re.compile(
    r"^(财联社.{0,6}电[，、,]?|金十数据整理[：:]|市场消息[：:]|快讯[：:]|据[^，。：:]{2,14}[：:])"
)
_BRACKET_RE = re.compile(r"【[^】]*】")
_CODE_SUFFIX_RE = re.compile(r"\([A-Za-z0-9.]{2,12}\)")
_NON_WORD_RE = re.compile(r"[\W_]+", re.UNICODE)


def normalize_title(text):
    """NFKC → 去【】→ 去源前缀 → 去证券代码后缀 → 小写 → 去空白标点（保留数字）。"""
    s = unicodedata.normalize("NFKC", str(text or ""))
    s = _BRACKET_RE.sub("", s)
    s = _SOURCE_PREFIX_RE.sub("", s.strip())
    s = _CODE_SUFFIX_RE.sub("", s)
    return _NON_WORD_RE.sub("", s.lower())


def _ngrams(s, n=4):
    if not s:
        return set()
    if len(s) <= n:
        return {s}
    return {s[i : i + n] for i in range(len(s) - n + 1)}


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _similar(grams_a, text_a, grams_b, text_b):
    j = _jaccard(grams_a, grams_b)
    if j >= DEDUP_JACCARD:
        return True
    if j < DEDUP_RATIO_MIN_JACCARD:
        return False
    return difflib.SequenceMatcher(None, text_a, text_b).ratio() >= DEDUP_RATIO


_CUT_MARKS = "。，；："


def title_short(text, limit=40):
    """≤40 字；优先在句读处截断，硬截断不切数字/英文单词。"""
    s = str(text or "").strip()
    if len(s) <= limit:
        return s
    head = s[:limit]
    cut = max(head.rfind(m) for m in _CUT_MARKS)
    if cut >= 10:
        return s[:cut]
    i = limit - 1
    while (
        i > 0
        and s[i].isascii()
        and s[i].isalnum()
        and s[i - 1].isascii()
        and (s[i - 1].isalnum() or s[i - 1] in ".-")
    ):
        i -= 1
    return s[: max(i, 1)] + "…"


def _sentiment_block(sentiment):
    if not isinstance(sentiment, dict):
        return None
    score = sentiment.get("score")
    if not isinstance(score, (int, float)):
        return None
    return {
        "score": round(float(score), 4),
        "confidence": sentiment.get("confidence"),
        "label": sentiment_label(float(score)),
    }


def _row_title(row):
    return str(row.get("raw") or row.get("term") or "").strip()


def _row_event_type(row):
    return (row.get("event") or {}).get("type") or "macro_other"


def _collect_rows(rows, now, hours):
    """只取 events 源、有 event 块、且在窗口内的行（排除 trader.log 历史行）。"""
    cutoff = now - timedelta(hours=hours)
    out = []
    for row in rows:
        if row.get("source") != "events.jsonl":
            continue
        if not isinstance(row.get("event"), dict):
            continue
        dt = _parse_ts(row.get("timestamp"))
        if dt is None or dt < cutoff:
            continue
        out.append((row, dt))
    return out


def build_hot_news(
    rows,
    now=None,
    window_h=HOT_NEWS_WINDOW_H,
    cluster_window_h=HOT_NEWS_CLUSTER_WINDOW_H,
    top_n=HOT_NEWS_TOP_N,
):
    """语义事件行 → 热点新闻影响力榜产物（dict）。纯函数，便于测试。"""
    now = now or datetime.now(timezone.utc)
    entries = []
    for row, dt in _collect_rows(rows, now, cluster_window_h):
        title = _row_title(row) or _row_event_type(row)
        norm = normalize_title(title)
        entries.append(
            {
                "row": row,
                "ts": dt,
                "type": _row_event_type(row),
                "title": title,
                "norm": norm,
                "grams": _ngrams(norm),
                "symbols": {str(row.get("symbol") or "MACRO")},
            }
        )
    entries.sort(key=lambda e: e["ts"])

    # 贪心聚类：同 type + symbols 有交集 + 文本相似
    clusters = []
    for entry in entries:
        target = None
        for cluster in clusters:
            if cluster["type"] != entry["type"]:
                continue
            if not (cluster["symbols"] & entry["symbols"]):
                continue
            if _similar(cluster["grams"], cluster["norm"], entry["grams"], entry["norm"]):
                target = cluster
                break
        if target is None:
            clusters.append(
                {
                    "type": entry["type"],
                    "symbols": set(entry["symbols"]),
                    "norm": entry["norm"],
                    "grams": entry["grams"],
                    "members": [entry],
                }
            )
        else:
            target["members"].append(entry)
            target["symbols"] |= entry["symbols"]

    window_cutoff = now - timedelta(hours=window_h)
    items = []
    total = scored = unscored = cluster_24h = 0
    type_dist, topic_dist = {}, {}
    topic_scores = {}
    models = {}

    for cluster in clusters:
        origins = {str(m["row"].get("origin") or "unknown") for m in cluster["members"]}
        source_count = len(origins)
        in_window = []
        for member in cluster["members"]:
            row = member["row"]
            sentiment = row.get("sentiment")
            member["importance"], member["parts"] = importance(
                published_at=row.get("timestamp"),
                etype=member["type"],
                sentiment=sentiment,
                origin=row.get("origin"),
                source_count=source_count,
                now=now,
            )
            if member["ts"] >= window_cutoff:
                in_window.append(member)
                total += 1
                type_dist[member["type"]] = type_dist.get(member["type"], 0) + 1
                topic = row.get("topic") or topic_of(member["title"])
                topic_dist[topic] = topic_dist.get(topic, 0) + 1
                if _sentiment_block(sentiment) is not None:
                    scored += 1
                    topic_scores.setdefault(topic, []).append(member["importance"])
                    if isinstance(sentiment, dict) and sentiment.get("model"):
                        models[sentiment["model"]] = models.get(sentiment["model"], 0) + 1
                else:
                    unscored += 1
        if not in_window:
            continue
        cluster_24h += 1
        # 簇代表：24h 内已打分成员中 importance 最高者（未打分不进榜）
        ranked = [m for m in in_window if _sentiment_block(m["row"].get("sentiment")) is not None]
        if not ranked:
            continue
        rep = max(ranked, key=lambda m: (m["importance"], m["ts"].timestamp()))
        row = rep["row"]
        topic = row.get("topic") or topic_of(rep["title"])
        items.append(
            {
                "event_id": row.get("trace_id"),
                "title": rep["title"],
                "title_short": title_short(rep["title"]),
                "topic": topic,
                "event_type": rep["type"],
                "symbols": sorted(rep["symbols"]),
                "sentiment": _sentiment_block(row.get("sentiment")),
                "importance": rep["importance"],
                "parts": rep["parts"],
                "published_at": row.get("timestamp"),
                "origin": row.get("origin"),
                "source_url": row.get("source_url"),
                "source_count": source_count,
                "dup_count": len(cluster["members"]) - 1,
                "recomputed": not all(
                    row.get(key) is not None for key in ("topic", "importance", "origin")
                ),
                "_ts": rep["ts"].timestamp(),
            }
        )

    items.sort(key=lambda x: (-x["importance"], -x["_ts"]))
    top = []
    for rank, item in enumerate(items[:top_n], start=1):
        item.pop("_ts", None)
        item["rank"] = rank
        top.append(item)

    clusters_out = [
        {
            "topic": topic,
            "label": TOPIC_LABELS.get(topic, topic),
            "count": count,
            "avg_importance": (
                round(sum(topic_scores[topic]) / len(topic_scores[topic]), 1)
                if topic_scores.get(topic)
                else 0.0
            ),
        }
        for topic, count in sorted(topic_dist.items(), key=lambda kv: -kv[1])
    ]
    avg_importance = round(sum(i["importance"] for i in items) / len(items), 1) if items else 0.0
    model_name = max(models, key=models.get) if models else "unavailable"

    return {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_h": window_h,
        "model": {"name": model_name, "normalized": True},
        "stats": {
            "total": total,
            "scored": scored,
            "unscored": unscored,
            "clusters": cluster_24h,
            "dedup_saved": total - cluster_24h,
            "high_impact": sum(1 for i in items if i["importance"] >= 70),
            "avg_importance": avg_importance,
            "type_dist": dict(sorted(type_dist.items(), key=lambda kv: -kv[1])),
            "topic_dist": dict(sorted(topic_dist.items(), key=lambda kv: -kv[1])),
        },
        "top": top,
        "clusters": clusters_out,
        "degraded": unscored > 0,
    }


def _atomic_write_json(path, payload):
    tmp = f"{path}.tmp"
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def write_hot_news(semantic_path=None, out_path=None, now=None):
    """每轮无条件重写 hot_news.json（recency 才会衰减、generated_at 才会滚动）。"""
    semantic_path = semantic_path or OUT_PATH
    out_path = out_path or os.environ.get("HOT_NEWS_PATH") or HOT_NEWS_PATH
    rows = []
    if os.path.isfile(semantic_path):
        with open(semantic_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    payload = build_hot_news(rows, now=now)
    _atomic_write_json(out_path, payload)
    return payload


_sentiment_engine = None

# 术语事件模式（术语 → 正则，含分组提取取值）
# 结构约定: 时间戳后固定 [INFO]，再取 [标的]，避免非贪婪误匹配 [INFO]
EVENT_PATTERNS = {
    "BCRM连续性": re.compile(r"\[([\d:\- ]+)\] \[INFO\] \[(\w+)\].*?BCRM连续=(\w+)\(([\d.]+)\)"),
    "三层弹性放行": re.compile(
        r"\[([\d:\- ]+)\] \[INFO\] \[(\w+)\].*?方案C 三层弹性放行 \| P1=(\w+) Elder=(\w+) BCRM连续=(\w+) Score_B=([\d.]+)"
    ),
    "弹性门控试错仓": re.compile(
        r"\[([\d:\- ]+)\] \[INFO\] \[(\w+)\].*?ElasticGate3L 将给 ?([\d.]+) ?试错仓"
    ),
    "BDSM仓位兜底": re.compile(
        r"\[([\d:\- ]+)\] \[INFO\] \[(\w+)\].*?BDSM 最低仓位兜底 \| ([\d.]+)U→([\d.]+)U"
    ),
    "P1趋势过滤": re.compile(
        r"\[([\d:\- ]+)\] \[INFO\] \[(\w+)\].*?P1长多趋势过滤 \| 共振(成功|失败)"
    ),
    "反向信号软权重": re.compile(
        r"\[([\d:\- ]+)\] \[INFO\] \[[\w\-]+\] (\w+).*?反向信号软权重.*?仓位 ×([\d.]+)"
    ),
    "开仓事件": re.compile(
        r"\[([\d:\- ]+)\] \[INFO\] \[(\w+)\] 开仓成功 \| ordId=([\w]+) \| 入场价≈([\d.]+)"
    ),
    "置信度信号": re.compile(r"\[([\d:\- ]+)\] \[INFO\] \[(\w+)\].*?置信度=([\d.]+) 方向=(\w+)"),
}


def _load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"processed_lines": 0}


def _save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f)


def _emit(events, term, ts, symbol, values, raw):
    events.append(
        {
            "term": term,
            "timestamp": ts.strip(),
            "symbol": symbol,
            "values": values,
            "raw": raw[:200],
            "source": "trader.log",
        }
    )


def scan(start_line=0, max_lines=500000):
    """从指定行号扫描日志，生成语义事件列表。"""
    events = []
    processed = 0
    try:
        with open(TRADER_LOG, "r", encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f):
                if i < start_line:
                    continue
                if i - start_line >= max_lines:
                    break
                processed += 1
                for term, pat in EVENT_PATTERNS.items():
                    m = pat.search(line)
                    if m:
                        g = m.groups()
                        # 通用结构: (时间, 标的, *取值)
                        ts, symbol = g[0], g[1]
                        values = list(g[2:])
                        _emit(events, term, ts, symbol, values, line.strip())
                        # 同一行可含多个术语事件（如 P1过滤+弹性门控），各自独立记录
    except FileNotFoundError:
        pass
    return events, processed


def _load_scorer():
    """懒加载 9 域情绪引擎（模型生命周期留在 9，39 只调用稳定函数，不 import torch）。"""
    global _sentiment_engine
    if _sentiment_engine is None:
        spec = importlib.util.spec_from_file_location(
            "dreambuddy_sentiment_engine", SENTIMENT_ENGINE_PATH
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _sentiment_engine = module.SentimentEngine()
    return _sentiment_engine


# 中文模型标记：必须整词/带分隔符匹配，不能用裸 "zh" 子串
# （否则本地路径 /Users/zhangjiangtao/... 会把英文模型误判成中文模型）
_ZH_MODEL_RE = re.compile(r"(chinese|finbert[-_]?zh|(^|[/_\-])zh($|[/_\-]))")


def _normalize_model(raw):
    """§7.7：落库 model 归一化为四值，避免同一模型多种写法。"""
    if not raw:
        return "unavailable"
    low = str(raw).lower()
    if "rule" in low:
        return "rule_fallback"
    if _ZH_MODEL_RE.search(low):
        return "finbert-tone-chinese"
    if "finbert" in low:
        return "ProsusAI/finbert"
    return "unavailable"


def _score_text(text, half_life_h=24):
    """调用 9 域 FinBERT 打分服务；异常 → None（sentiment=null 合法，禁止填 0 冒充）。"""
    try:
        res = _load_scorer().analyze_text(text, with_meta=True)
    except Exception:
        return None
    if not isinstance(res, dict):
        return None
    return {
        "score": round(float(res.get("score", 0.0)), 4),
        "confidence": res.get("confidence"),
        "model": _normalize_model(res.get("model")),
        "half_life_h": half_life_h,
    }


def _load_bodies(path=None):
    """读取正文快照（body_id → content_text）；缺失返回空 dict（FAIL-OPEN）。"""
    path = path or os.environ.get("EMERGENCE_BODIES_PATH") or BODIES_PATH
    out = {}
    if not os.path.isfile(path):
        return out
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if row.get("id"):
                    out[str(row["id"])] = str(row.get("content_text") or "")
    except OSError:
        return {}
    return out


def _resolve_body(ev, bodies):
    """事件正文：兼容内联 body（旧行）与 body_ref（P1-A 正文外置）。"""
    inline = str(ev.get("body") or "").strip()
    if inline:
        return inline
    ref = ev.get("body_ref")
    if not ref or not bodies:
        return ""
    return str(bodies.get(str(ref).split("#")[-1].strip()) or "").strip()


def _event_to_line(ev, scorer=_score_text, bodies=None):
    """canonical EventRecord → 39 语义事件行（新增 sentiment/event/trace_id + 榜单字段）。"""
    etype = ev.get("type") or "macro_other"
    title = str(ev.get("title") or "").strip()
    body = _resolve_body(ev, bodies or {})
    text = f"{title}。{body}".strip("。 ") if title else ""
    sentiment = scorer(text, HALF_LIFE_H.get(etype, 24)) if text else None
    symbols = [str(s) for s in (ev.get("symbols") or []) if s]
    ts = ev.get("available_at") or ev.get("event_time") or ""
    origin = ev.get("source")
    imp, parts = importance(
        published_at=ts, etype=etype, sentiment=sentiment, origin=origin, source_count=1
    )
    return {
        "term": title[:80] or etype,
        "timestamp": ts,
        "symbol": symbols[0] if symbols else "MACRO",
        "values": [f"{sentiment['score']:.4f}"] if sentiment else [],
        "raw": title[:200],
        "source": "events.jsonl",
        "sentiment": sentiment,
        "event": {
            "type": etype,
            "surprise": ev.get("surprise"),
            "surprise_unit": ev.get("surprise_unit"),
        },
        "trace_id": ev.get("event_id"),
        # 榜单字段（SPEC §4.4）：origin 修复 P-H5 来源丢失；sentiment_missing 禁止 0 冒充
        "origin": origin,
        "source_url": ev.get("source_url"),
        "topic": topic_of(title),
        "importance": imp,
        "importance_parts": parts,
        "cluster_id": ev.get("event_id"),
        "sentiment_missing": sentiment is None,
    }


def emit_from_events(events_path=None, out_path=None, scorer=None, bodies_path=None):
    """把 canonical EventRecord 转成 39 语义事件行；按 trace_id 幂等，旧行不重写。"""
    events_path = events_path or os.environ.get("EMERGENCE_EVENTS_PATH") or EVENTS_PATH
    out_path = out_path or OUT_PATH
    scorer = scorer or _score_text
    bodies = _load_bodies(bodies_path)
    if not os.path.isfile(events_path):
        print(f"[WARN] 事件文件不存在，跳过：{events_path}")
        return [], 0

    seen = set()
    if os.path.isfile(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if row.get("source") == "events.jsonl" and row.get("trace_id"):
                    seen.add(row["trace_id"])

    emitted, skipped = [], 0
    with open(events_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("event_id") in seen:
                skipped += 1
                continue
            emitted.append(_event_to_line(ev, scorer, bodies))
            seen.add(ev.get("event_id"))

    if emitted:
        with open(out_path, "a", encoding="utf-8") as f:
            for e in emitted:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return emitted, skipped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", action="store_true", help="回填模式：全量扫描历史日志")
    parser.add_argument("--live", action="store_true", help="增量模式：只处理新增行")
    parser.add_argument(
        "--source", choices=["trader", "events"], default="trader", help="事件源（P0-A）"
    )
    parser.add_argument("--events-path", default=None, help="canonical events.jsonl 路径")
    args = parser.parse_args()

    if args.source == "events":
        emitted, skipped = emit_from_events(args.events_path)
        print(f"[OK] 事件源：新增 {len(emitted)} 条，跳过已处理 {skipped} 条 → {OUT_PATH}")
        # 每轮无条件重写榜单（SPEC §7 第 8 项）：recency 衰减 / generated_at 滚动
        payload = write_hot_news()
        stats = payload["stats"]
        print(
            f"[OK] 热点榜：Top {len(payload['top'])} 条 / {stats['total']} 事件 / "
            f"去重节省 {stats['dedup_saved']} / 高影响 {stats['high_impact']} → {HOT_NEWS_PATH}"
        )
        return

    if args.backfill:
        start = 0
    elif args.live:
        start = _load_state().get("processed_lines", 0)
        # ── 轮转检测（2026-10-29）：日志轮转后行数小于已处理行数 → 自动重置从头扫描 ──
        # 防止轮转导致状态错位、增量模式静默停更（10-25 轮转事故复盘）
        try:
            with open(TRADER_LOG, "r", encoding="utf-8", errors="ignore") as f:
                total_lines = sum(1 for _ in f)
            if start > total_lines:
                print(
                    f"[WARN] 检测到日志轮转：已处理 {start} 行 > 当前 {total_lines} 行，重置状态从头扫描"
                )
                start = 0
        except FileNotFoundError:
            pass
    else:
        parser.error("需指定 --backfill 或 --live")

    events, processed = scan(start)
    if events:
        with open(OUT_PATH, "a", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    _save_state({"processed_lines": start + processed})

    print(
        f"[OK] 模式={'backfill' if args.backfill else 'live'} "
        f"扫描 {processed} 行, 产出 {len(events)} 条语义事件 → {OUT_PATH}"
    )
    if events:
        by_term = {}
        for e in events:
            by_term[e["term"]] = by_term.get(e["term"], 0) + 1
        for t, n in sorted(by_term.items(), key=lambda kv: -kv[1]):
            print(f"     {t}: {n} 条")


if __name__ == "__main__":
    main()
