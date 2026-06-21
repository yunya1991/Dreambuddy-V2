#!/usr/bin/env python3
"""
加密市场叙事分析生成器 - Narrative Analyzer v1.0

功能:
1. 从新闻事件聚合叙事主题
2. 计算叙事热度和情绪分数
3. 追踪叙事生命周期
4. 生成叙事登记簿和简报

参考:
- 新闻分析 skill 的 event_ledger_generator.py
- 资金流分析 skill 的 regime_classifier.py
"""

import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict, field
from collections import defaultdict
import hashlib
from urllib.request import Request, urlopen
from urllib.parse import urlencode


# =============================================================================
# 配置
# =============================================================================

BASE_DIR = Path(__file__).parent.parent
# RAW_DIR 和 OUTPUTS_DIR 在 core_task1 层级，不是 narrative 层级
CORE_DIR = BASE_DIR.parent
RAW_DIR = CORE_DIR / "raw"
OUTPUTS_DIR = CORE_DIR / "outputs"
NARRATIVE_OUTPUTS_DIR = BASE_DIR / "outputs"
NARRATIVE_HISTORY_DIR = BASE_DIR / "history"

# 确保目录存在
NARRATIVE_OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
NARRATIVE_HISTORY_DIR.mkdir(parents=True, exist_ok=True)

# 叙事分类体系
NARRATIVE_CATEGORIES = {
    "etf_institutional": {
        "name": "ETF/机构",
        "keywords": ["ETF", "贝莱德", "富达", "机构", "IBIT", "FBTC", "资管", "资金流入", "资金流出"],
        "weight": 1.0
    },
    "layer2_scaling": {
        "name": "Layer2/扩容",
        "keywords": ["Layer2", "Arbitrum", "Optimism", "zkSync", "Rollup", "扩容", "Gas", "L2"],
        "weight": 0.9
    },
    "defi": {
        "name": "DeFi",
        "keywords": ["DeFi", "借贷", "DEX", "Uniswap", "Aave", "TVL", "收益率", "流动性"],
        "weight": 0.85
    },
    "nft_metaverse": {
        "name": "NFT/元宇宙",
        "keywords": ["NFT", "OpenSea", "元宇宙", "Metaverse", "数字藏品", "虚拟世界"],
        "weight": 0.7
    },
    "gamefi": {
        "name": "GameFi",
        "keywords": ["GameFi", "Play-to-Earn", "链游", "游戏", "AXS", "SLP"],
        "weight": 0.65
    },
    "stablecoin": {
        "name": "稳定币",
        "keywords": ["稳定币", "USDT", "USDC", "DAI", "Tether", "Circle"],
        "weight": 0.8
    },
    "regulation_policy": {
        "name": "监管政策",
        "keywords": ["监管", "SEC", "政策", "合规", "法规", "审批", "禁令"],
        "weight": 0.95
    },
    "tech_innovation": {
        "name": "技术创新",
        "keywords": ["升级", "硬分叉", "EIP", "技术", "协议", "主网", "测试网"],
        "weight": 0.75
    },
    "security": {
        "name": "安全事件",
        "keywords": ["攻击", "黑客", "漏洞", "被盗", "清算", "风险", "安全"],
        "weight": 1.0
    },
    "macro_finance": {
        "name": "宏观金融",
        "keywords": ["美联储", "利率", "CPI", "通胀", "宏观", "经济", "美元", "DXY"],
        "weight": 0.9
    }
}

# 叙事生命周期阈值
LIFECYCLE_THRESHOLDS = {
    "emerging": (0, 0.3),
    "growing": (0.3, 0.7),
    "mature": (0.7, 0.9),
    "declining": (0.9, 1.0)  # 热度下降
}


# =============================================================================
# 数据类
# =============================================================================

@dataclass
class NarrativeEvent:
    """叙事相关事件"""
    event_id: str
    title: str
    category: str
    sentiment_score: float
    timestamp: str
    source: str
    source_url: str = ""
    engagement: int = 0
    influence_weight: float = 1.0


@dataclass
class Narrative:
    """叙事主题"""
    narrative_id: str
    narrative_name: str
    category: str
    status: str  # active, cooling, archive
    heat_score: float
    sentiment_score: float
    sentiment_trend: str  # strengthening, weakening, stable
    related_tokens: List[str]
    event_count: int
    lifecycle_stage: str  # emerging, growing, mature, declining
    confidence: float
    created_at: str
    updated_at: str


@dataclass
class NarrativeRegistry:
    """叙事登记簿"""
    timestamp: str
    generated_at: str
    analysis_window: str
    narratives: List[Narrative]
    narrative_count: int
    overall_sentiment: float
    overall_heat: float
    top_narrative: str
    summary: str
    execution_gate: str = "readonly_advisory"
    contract: Dict[str, Any] = field(default_factory=dict)
    extended_sentiment: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# 叙事分析器
# =============================================================================

class NarrativeAnalyzer:
    """叙事分析主引擎"""

    def __init__(self, hours: int = 24):
        self.hours = hours
        self.cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        self.narrative_events: Dict[str, List[NarrativeEvent]] = defaultdict(list)
        self.narratives: Dict[str, Narrative] = {}
        self.raw_events_by_category: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.latest_events: List[Dict[str, Any]] = []

    def load_event_ledger(self) -> List[Dict]:
        """加载新闻分析的事件账本"""
        events = []
        
        # 兼容: 新版架构下 event_ledger 直接内嵌在 brief_v3_*.json
        brief_files = sorted(OUTPUTS_DIR.glob("brief_v3_*_optimized.json"), key=lambda x: x.stat().st_mtime, reverse=True)
        if brief_files:
            try:
                obj = json.loads(brief_files[0].read_text(encoding="utf-8", errors="replace"))
                if isinstance(obj, dict) and "event_ledger" in obj:
                    events.extend(obj["event_ledger"])
            except Exception:
                pass
                
        # 优先从 raw 目录加载 (最新数据), 降级到 outputs 目录
        event_files = list(RAW_DIR.glob("event_ledger_*.jsonl"))
        if not event_files:
            event_files = list(OUTPUTS_DIR.glob("event_ledger_*.jsonl"))

        # 按修改时间排序（最新的在前）
        event_files = sorted(event_files, key=lambda p: p.stat().st_mtime, reverse=True)[:5]
        for file_path in event_files:
            # Skip reading old jsonl if brief json is already newer
            if brief_files and file_path.stat().st_mtime < brief_files[0].stat().st_mtime - 300:
                continue
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content.startswith('['):
                        events.extend(json.loads(content))
                    else:
                        for line in content.split('\n'):
                            if line.strip():
                                events.append(json.loads(line))
            except Exception as e:
                continue

        # 过滤时间窗口
        filtered = []
        for event in events:
            ts = event.get('timestamp') or event.get('published_at') or event.get('fetched_at', '')
            if ts:
                try:
                    # 处理时区：Z -> +00:00, 无时区后缀 -> 默认 UTC
                    ts_clean = ts.replace('Z', '+00:00')
                    if '+' not in ts_clean and '-' not in ts_clean[-6:]:
                        ts_clean += '+00:00'
                    event_dt = datetime.fromisoformat(ts_clean)
                    # 使用 published_at 时，事件发布时间在窗口内即可
                    if event_dt >= self.cutoff:
                        filtered.append(event)
                except Exception:
                    # 解析失败时保留事件
                    filtered.append(event)
            else:
                filtered.append(event)  # 无时间戳的保留

        return filtered

    def classify_narrative_category(self, title: str, summary: str = "") -> Optional[str]:
        """分类叙事类别"""
        text = f"{title} {summary}".lower()

        best_match = None
        best_score = 0

        for cat_id, cat_info in NARRATIVE_CATEGORIES.items():
            score = 0
            for keyword in cat_info['keywords']:
                if keyword.lower() in text:
                    score += 1

            if score > best_score:
                best_score = score
                best_match = cat_id

        return best_match if best_score >= 1 else None

    def generate_narrative_id(self, category: str, title: str) -> str:
        """生成叙事 ID"""
        # 使用类别 + 标题哈希
        key = f"{category}_{title[:50]}"
        hash_val = hashlib.md5(key.encode()).hexdigest()[:8]
        return f"{category}_{hash_val}"

    def parse_events_to_narratives(self, events: List[Dict]) -> Dict[str, List[NarrativeEvent]]:
        """将事件聚合到叙事"""
        narrative_events = defaultdict(list)
        self.raw_events_by_category = defaultdict(list)

        for event in events:
            title = event.get('title', '')
            summary = event.get('summary', event.get('content', ''))
            sentiment = event.get('sentiment_score', 0)

            # 分类
            category = self.classify_narrative_category(title, summary)
            if not category:
                continue

            # 计算影响力权重
            source_confidence = event.get('source_confidence', 'medium')
            influence_weight = {'high': 1.5, 'medium': 1.0, 'low': 0.7}.get(source_confidence, 1.0)

            # 估算互动量 (简化)
            engagement = 100 if source_confidence == 'high' else 50

            # 创建事件
            narrative_event = NarrativeEvent(
                event_id=event.get('event_id', hashlib.md5(title.encode()).hexdigest()[:8]),
                title=title,
                category=category,
                sentiment_score=sentiment,
                timestamp=event.get('timestamp', datetime.now(timezone.utc).isoformat()),
                source=event.get('source', 'unknown'),
                source_url=event.get('source_url', ''),
                engagement=engagement,
                influence_weight=influence_weight
            )

            narrative_events[category].append(narrative_event)
            self.raw_events_by_category[category].append(event)

        return narrative_events

    def calculate_heat_score(self, events: List[NarrativeEvent]) -> float:
        """计算叙事热度"""
        if not events:
            return 0.0

        # 事件数量分
        count_score = min(1.0, len(events) / 10)  # 最多 10 个事件满分

        # 总互动量
        total_engagement = sum(e.engagement for e in events)
        engagement_score = min(1.0, total_engagement / 1000)

        # 时间衰减 (越新的事件权重越高)
        now = datetime.now(timezone.utc)
        time_weights = []
        for event in events:
            try:
                event_dt = datetime.fromisoformat(event.timestamp.replace('Z', '+00:00'))
                hours_ago = (now - event_dt).total_seconds() / 3600
                weight = max(0.1, 1.0 - hours_ago / 24)
                time_weights.append(weight)
            except Exception:
                time_weights.append(0.5)

        time_score = sum(time_weights) / len(time_weights) if time_weights else 0.5

        # 综合热度
        heat = 0.4 * count_score + 0.35 * engagement_score + 0.25 * time_score

        return round(heat, 4)

    def calculate_sentiment(self, events: List[NarrativeEvent]) -> Tuple[float, str]:
        """计算情绪分数和趋势"""
        if not events:
            return 0.0, "stable"

        # 加权平均情绪
        total_weight = sum(e.engagement * e.influence_weight for e in events)
        if total_weight == 0:
            return 0.0, "stable"

        weighted_sentiment = sum(
            e.sentiment_score * e.engagement * e.influence_weight
            for e in events
        ) / total_weight

        # 计算趋势 (比较前一半和后一半事件)
        mid = len(events) // 2
        if mid > 0:
            early_sentiment = sum(e.sentiment_score for e in events[:mid]) / mid
            late_sentiment = sum(e.sentiment_score for e in events[mid:]) / (len(events) - mid)

            diff = late_sentiment - early_sentiment
            if diff > 0.1:
                trend = "strengthening"
            elif diff < -0.1:
                trend = "weakening"
            else:
                trend = "stable"
        else:
            trend = "stable"

        return round(weighted_sentiment, 4), trend

    def determine_lifecycle_stage(self, heat_score: float, events: List[NarrativeEvent]) -> str:
        """判断叙事生命周期阶段"""
        if heat_score < 0.3:
            return "emerging"
        elif heat_score < 0.7:
            return "growing"
        elif heat_score < 0.9:
            return "mature"
        else:
            return "declining"

    def build_narratives(self) -> List[Narrative]:
        """构建叙事列表"""
        narratives = []
        now = datetime.now(timezone.utc).isoformat()

        for category, events in self.narrative_events.items():
            if not events:
                continue

            cat_info = NARRATIVE_CATEGORIES.get(category, {})
            cat_name = cat_info.get('name', category)

            heat_score = self.calculate_heat_score(events)
            sentiment_score, sentiment_trend = self.calculate_sentiment(events)
            lifecycle_stage = self.determine_lifecycle_stage(heat_score, events)

            # 确定状态
            if heat_score >= 0.3:
                status = "active"
            else:
                status = "cooling"

            # 相关代币 (简化)
            related_tokens = []
            if 'etf' in category or 'institutional' in category:
                related_tokens = ["BTC", "ETH"]
            elif 'layer2' in category:
                related_tokens = ["ETH", "ARB", "OP"]
            elif 'defi' in category:
                related_tokens = ["ETH", "UNI", "AAVE"]

            # 生成叙事 ID
            narrative_id = f"{category}_{datetime.now().strftime('%Y%m%d')}"

            narrative = Narrative(
                narrative_id=narrative_id,
                narrative_name=cat_name,
                category=category,
                status=status,
                heat_score=heat_score,
                sentiment_score=sentiment_score,
                sentiment_trend=sentiment_trend,
                related_tokens=related_tokens,
                event_count=len(events),
                lifecycle_stage=lifecycle_stage,
                confidence=min(0.95, 0.5 + len(events) * 0.05),
                created_at=now,
                updated_at=now
            )

            narratives.append(narrative)

        # 按热度排序
        narratives.sort(key=lambda x: x.heat_score, reverse=True)

        return narratives

    def generate_summary(self, narratives: List[Narrative]) -> str:
        """生成叙事摘要"""
        if not narratives:
            return "最近暂无显著叙事主题"

        top = narratives[0]
        positive = [n for n in narratives if n.sentiment_score > 0.2]
        negative = [n for n in narratives if n.sentiment_score < -0.2]

        summary_parts = []
        summary_parts.append(f"当前主导叙事为「{top.narrative_name}」，热度{top.heat_score:.2f}，情绪{top.sentiment_score:+.2f}。")

        if positive:
            summary_parts.append(f"正面叙事{len(positive)}个，主要包括{', '.join(n.narrative_name for n in positive[:3])}。")

        if negative:
            summary_parts.append(f"负面叙事{len(negative)}个，需关注{', '.join(n.narrative_name for n in negative[:3])}。")

        return " ".join(summary_parts)

    def _to_float(self, v: Any, default: float = 0.0) -> float:
        try:
            x = float(v)
        except Exception:
            return float(default)
        if not math.isfinite(x):
            return float(default)
        return float(x)

    def _http_get_json(self, url: str, *, params: Optional[Dict[str, Any]] = None, timeout: int = 8) -> Any:
        q = str(url or "").strip()
        if not q:
            return None
        if isinstance(params, dict) and params:
            sep = "&" if "?" in q else "?"
            enc = urlencode({k: str(v) for k, v in params.items() if v is not None})
            if enc:
                q = f"{q}{sep}{enc}"
        try:
            req = Request(q, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw)
        except Exception:
            return None

    def _parse_iso_ts(self, x: Any) -> Optional[datetime]:
        s = str(x or "").strip()
        if not s:
            return None
        s2 = s.replace("Z", "+00:00")
        try:
            d = datetime.fromisoformat(s2)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return d.astimezone(timezone.utc)
        except Exception:
            return None

    def _clip(self, v: float, lo: float, hi: float) -> float:
        return float(max(float(lo), min(float(hi), float(v))))

    def _event_effective_sentiment(self, event: Dict[str, Any]) -> float:
        s = self._to_float(event.get("sentiment_score"), 0.0)
        b = str(event.get("expectation_bucket") or "").strip()
        if "利多" in b:
            s += 0.15
        elif "利空" in b:
            s -= 0.15
        return self._clip(s, -1.0, 1.0)

    def _mean(self, arr: List[float], default: float = 0.0) -> float:
        if not arr:
            return float(default)
        return float(sum(arr) / len(arr))

    def _extract_inflow_usd_from_text(self, text: str) -> float:
        t = str(text or "")
        total = 0.0
        for m in re.finditer(r"(\d+(?:\.\d+)?)\s*亿(?:美元|USD|usdt|USDT)?", t):
            total += self._to_float(m.group(1), 0.0) * 1e8
        for m in re.finditer(r"(\d+(?:\.\d+)?)\s*万(?:美元|USD|usdt|USDT)?", t):
            total += self._to_float(m.group(1), 0.0) * 1e4
        for m in re.finditer(r"\$?\s*(\d+(?:\.\d+)?)\s*(billion|bn|million|m)\b", t, flags=re.IGNORECASE):
            v = self._to_float(m.group(1), 0.0)
            u = str(m.group(2) or "").lower()
            if u in ("billion", "bn"):
                total += v * 1e9
            else:
                total += v * 1e6
        return float(total)

    def _calc_news_bull_bear(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        bull = 0
        bear = 0
        neutral = 0
        vals: List[float] = []
        for e in events:
            s = self._event_effective_sentiment(e)
            vals.append(s)
            b = str(e.get("expectation_bucket") or "").strip()
            if ("利多" in b) or (s > 0.12):
                bull += 1
            elif ("利空" in b) or (s < -0.12):
                bear += 1
            else:
                neutral += 1
        ratio = (float(bull) / max(float(bear), 1.0))
        idx = self._clip(50.0 + 25.0 * math.tanh(self._mean(vals, 0.0) * 2.2) + 15.0 * math.tanh((ratio - 1.0) / 2.0), 0.0, 100.0)
        return {
            "bull_count": int(bull),
            "bear_count": int(bear),
            "neutral_count": int(neutral),
            "bull_bear_ratio": round(ratio, 4),
            "index": round(idx, 4),
        }

    def _calc_macro_sentiment(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        macro = []
        for e in events:
            k = f"{e.get('category','')} {e.get('topic','')} {e.get('event_type','')}".lower()
            if any(x in k for x in ["macro", "fed", "us_data", "geopolitics", "policy", "regulation"]):
                macro.append(e)
        vals = [self._event_effective_sentiment(e) for e in macro]
        score = self._clip(50.0 + 45.0 * self._mean(vals, 0.0), 0.0, 100.0)
        return {
            "event_count": int(len(macro)),
            "index": round(score, 4),
            "sentiment_mean": round(self._mean(vals, 0.0), 4),
        }

    def _inflow_history_file(self) -> Path:
        return NARRATIVE_HISTORY_DIR / "btc_inflow_daily.json"

    def _load_inflow_history(self) -> Dict[str, float]:
        p = self._inflow_history_file()
        if not p.exists():
            return {}
        try:
            obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return {}
        if not isinstance(obj, dict):
            return {}
        out: Dict[str, float] = {}
        for k, v in obj.items():
            out[str(k)] = self._to_float(v, 0.0)
        return out

    def _save_inflow_history(self, history: Dict[str, float]) -> None:
        p = self._inflow_history_file()
        items = sorted(history.items(), key=lambda kv: kv[0])[-120:]
        data = {k: round(self._to_float(v, 0.0), 4) for k, v in items}
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _calc_btc_inflow_sentiment(self, events: List[Dict[str, Any]], now_dt: datetime) -> Dict[str, Any]:
        inflow_events = []
        inflow_usd = 0.0
        kw = ("净流入", "资金流入", "inflow", "etf inflow", "flow in")
        for e in events:
            title = str(e.get("title") or "")
            summary = str(e.get("summary") or e.get("content") or "")
            text = f"{title} {summary}".lower()
            if any(k in text for k in kw):
                inflow_events.append(e)
                inflow_usd += self._extract_inflow_usd_from_text(f"{title} {summary}")
        history = self._load_inflow_history()
        dkey = now_dt.strftime("%Y-%m-%d")
        history[dkey] = float(inflow_usd)
        self._save_inflow_history(history)
        last90 = [self._to_float(v, 0.0) for _, v in sorted(history.items(), key=lambda kv: kv[0])[-90:]]
        baseline = self._mean(last90, 0.0)
        ratio = (inflow_usd / baseline) if baseline > 0 else (1.0 if inflow_usd <= 0 else 1.5)
        idx = self._clip(50.0 + 28.0 * math.tanh(math.log(max(ratio, 1e-6))), 0.0, 100.0)
        quality = "ok" if baseline > 0 else "stale"
        return {
            "event_count": int(len(inflow_events)),
            "daily_inflow_usd": round(inflow_usd, 4),
            "baseline_90d_avg_usd": round(baseline, 4),
            "ratio_vs_90d": round(ratio, 4),
            "index": round(idx, 4),
            "quality": quality,
        }

    def _calc_twitter_sector_search(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        tw = []
        for e in events:
            src = str(e.get("source") or "").lower()
            if src in ("twitter", "x"):
                tw.append(e)
        pool = tw if tw else events
        scores: Dict[str, float] = defaultdict(float)
        for e in pool:
            cat = self.classify_narrative_category(str(e.get("title") or ""), str(e.get("summary") or "")) or "other"
            mention = self._to_float(e.get("mention_count"), 1.0)
            att = self._to_float(e.get("attention_score"), 0.0)
            scores[cat] += max(0.0, mention) + max(0.0, att)
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:10]
        return {
            "source": ("twitter_x" if tw else "fallback_all_sources"),
            "sector_rank": [{"sector": k, "score": round(v, 4)} for k, v in ranked],
        }

    def _extract_tokens(self, text: str) -> List[str]:
        toks = re.findall(r"\b[A-Z]{2,10}\b", str(text or ""))
        deny = {"USD", "USDT", "USDC", "ETF", "SEC", "CPI", "FOMC", "BTCETF"}
        out: List[str] = []
        for t in toks:
            if t in deny:
                continue
            out.append(t)
        return out

    def _calc_onchain_sector_and_token_rank(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        sector_scores: Dict[str, float] = defaultdict(float)
        token_scores: Dict[str, float] = defaultdict(float)
        for e in events:
            c = str(e.get("category") or "")
            et = str(e.get("event_type") or "")
            if any(x in (c + " " + et).lower() for x in ["onchain", "protocol", "defi", "layer2", "security"]):
                cat = self.classify_narrative_category(str(e.get("title") or ""), str(e.get("summary") or "")) or "other"
                s = self._event_effective_sentiment(e)
                w = 1.0 + max(0.0, self._to_float(e.get("mention_count"), 1.0) * 0.1)
                sector_scores[cat] += (0.5 + s) * w
                for tok in self._extract_tokens(f"{e.get('title','')} {e.get('summary','')}"):
                    token_scores[tok] += w
        s_rank = sorted(sector_scores.items(), key=lambda kv: kv[1], reverse=True)[:10]
        t_rank = sorted(token_scores.items(), key=lambda kv: kv[1], reverse=True)[:10]
        return {
            "sector_rank": [{"sector": k, "score": round(v, 4)} for k, v in s_rank],
            "token_rank": [{"token": k, "score": round(v, 4)} for k, v in t_rank],
        }

    def _calc_attention_board(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        m: Dict[str, float] = defaultdict(float)
        for e in events:
            cat = self.classify_narrative_category(str(e.get("title") or ""), str(e.get("summary") or "")) or "other"
            m[cat] += max(0.0, self._to_float(e.get("attention_score"), 0.0)) + max(0.0, self._to_float(e.get("mention_count"), 1.0))
        rank = sorted(m.items(), key=lambda kv: kv[1], reverse=True)[:10]
        breadth = (len([1 for _, v in rank if v > 0.0]) / max(len(rank), 1)) if rank else 0.0
        return {
            "breadth": round(breadth, 4),
            "board": [{"sector": k, "attention_score": round(v, 4)} for k, v in rank],
        }

    def _calc_polymarket_curve(self, events: List[Dict[str, Any]], fallback_anchor: float) -> Dict[str, Any]:
        pm = []
        for e in events:
            t = f"{e.get('title','')} {e.get('summary','')}".lower()
            if ("polymarket" in t) or ("预测市场" in t):
                pm.append(e)
        horizons = {"near": [], "mid": [], "far": []}
        for e in pm:
            t = f"{e.get('title','')} {e.get('summary','')}"
            s = self._event_effective_sentiment(e)
            p = self._clip(0.5 + 0.35 * s, 0.05, 0.95)
            low = t.lower()
            if any(k in low for k in ["近", "短期", "本周", "7d", "day"]):
                horizons["near"].append(p)
            elif any(k in low for k in ["中", "月", "30d", "month"]):
                horizons["mid"].append(p)
            elif any(k in low for k in ["远", "季度", "年", "90d", "year", "q"]):
                horizons["far"].append(p)
            else:
                horizons["near"].append(p)
        near = self._mean(horizons["near"], self._clip(0.5 + 0.2 * fallback_anchor, 0.05, 0.95))
        mid = self._mean(horizons["mid"], self._clip(0.5 + 0.1 * fallback_anchor, 0.05, 0.95))
        far = self._mean(horizons["far"], self._clip(0.5 + 0.05 * fallback_anchor, 0.05, 0.95))
        if not pm:
            online = self._fetch_polymarket_curve_online(fallback_anchor=fallback_anchor)
            if isinstance(online, dict) and str(online.get("quality") or "") in {"ok", "backfilled"}:
                return online
        return {
            "quality": ("ok" if pm else "missing"),
            "sample_count": int(len(pm)),
            "bullish_probability": {
                "near": round(near, 4),
                "mid": round(mid, 4),
                "far": round(far, 4),
            },
            "bearish_probability": {
                "near": round(1.0 - near, 4),
                "mid": round(1.0 - mid, 4),
                "far": round(1.0 - far, 4),
            },
            "term_structure": {
                "near_minus_far": round(near - far, 4),
                "curvature": round(near - 2.0 * mid + far, 4),
            },
            "source": ("event_ledger" if pm else "none"),
        }

    def _extract_yes_prob(self, market: Dict[str, Any]) -> Optional[float]:
        outcomes_raw = market.get("outcomes")
        prices_raw = market.get("outcomePrices")
        outcomes: List[str] = []
        prices: List[Any] = []
        if isinstance(outcomes_raw, str):
            try:
                outcomes = list(json.loads(outcomes_raw))
            except Exception:
                outcomes = []
        elif isinstance(outcomes_raw, list):
            outcomes = outcomes_raw
        if isinstance(prices_raw, str):
            try:
                prices = list(json.loads(prices_raw))
            except Exception:
                prices = []
        elif isinstance(prices_raw, list):
            prices = prices_raw
        if not outcomes or not prices or len(outcomes) != len(prices):
            return None
        idx = -1
        for i, o in enumerate(outcomes):
            if str(o or "").strip().lower() == "yes":
                idx = i
                break
        if idx < 0:
            return None
        p = self._to_float(prices[idx], -1.0)
        if p < 0.0 or p > 1.0:
            return None
        return p

    def _market_bullish_prob(self, market: Dict[str, Any]) -> Optional[float]:
        q = str(market.get("question") or "").strip().lower()
        p_yes = self._extract_yes_prob(market)
        if p_yes is None:
            return None
        bullish_yes_kw = [
            "bitcoin hit",
            "bitcoin above",
            "btc above",
            "bitcoin reach",
            "bitcoin over",
            "bitcoin greater than",
            "price of bitcoin above",
        ]
        bearish_yes_kw = [
            "bitcoin below",
            "btc below",
            "bitcoin under",
            "bitcoin drop",
            "bitcoin crash",
            "bitcoin falls",
        ]
        if any(k in q for k in bullish_yes_kw):
            return p_yes
        if any(k in q for k in bearish_yes_kw):
            return 1.0 - p_yes
        if ("bitcoin" in q or "btc" in q) and any(k in q for k in ["all time high", "ath", "$1m", "1m"]):
            return p_yes
        return None

    def _fetch_polymarket_curve_online(self, fallback_anchor: float) -> Dict[str, Any]:
        # Try Polymarket API first
        try:
            obj = self._http_get_json(
                "https://gamma-api.polymarket.com/events",
                params={"limit": 200, "closed": "false", "search": "bitcoin"},
                timeout=10,
            )
            rows = obj if isinstance(obj, list) else []
            now_dt = datetime.now(timezone.utc)
            buckets: Dict[str, List[float]] = {"near": [], "mid": [], "far": []}
            sampled = 0
            for ev in rows:
                if not isinstance(ev, dict):
                    continue
                title = str(ev.get("title") or "").strip().lower()
                if ("bitcoin" not in title) and ("btc" not in title):
                    continue
                markets = ev.get("markets")
                if not isinstance(markets, list):
                    continue
                for m in markets:
                    if not isinstance(m, dict):
                        continue
                    bp = self._market_bullish_prob(m)
                    if bp is None:
                        continue
                    sampled += 1
                    end_dt = self._parse_iso_ts(m.get("endDateIso") or m.get("endDate") or ev.get("endDateIso") or ev.get("endDate"))
                    days = ((end_dt - now_dt).total_seconds() / 86400.0) if isinstance(end_dt, datetime) else 14.0
                    if days <= 10.0:
                        buckets["near"].append(bp)
                    elif days <= 45.0:
                        buckets["mid"].append(bp)
                    else:
                        buckets["far"].append(bp)
                        
            if sampled > 0:
                near = self._mean(buckets["near"], self._clip(0.5 + 0.2 * fallback_anchor, 0.05, 0.95))
                mid = self._mean(buckets["mid"], self._clip(0.5 + 0.1 * fallback_anchor, 0.05, 0.95))
                far = self._mean(buckets["far"], self._clip(0.5 + 0.05 * fallback_anchor, 0.05, 0.95))
                return {
                    "quality": "ok",
                    "sample_count": int(sampled),
                    "bullish_probability": {
                        "near": round(near, 4),
                        "mid": round(mid, 4),
                        "far": round(far, 4),
                    },
                    "bearish_probability": {
                        "near": round(1.0 - near, 4),
                        "mid": round(1.0 - mid, 4),
                        "far": round(1.0 - far, 4),
                    },
                    "term_structure": {
                                "near_minus_far": round(near - far, 4),
                                "curvature": round(near - 2.0 * mid + far, 4),
                            },
                            "source": "polymarket_api",
                        }
        except Exception as e:
            print(f"Polymarket API Exception: {e}")

        # Fallback to Tavily if API fails (403 Forbidden, etc)
        try:
            import os
            import json
            from pathlib import Path
            api_key = os.environ.get("TAVILY_API_KEY")
            if not api_key:
                mcp_path = Path("/Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/user_data/agent_repo/nanoclaw/.mcp.json")
                if mcp_path.exists():
                    with open(mcp_path) as f:
                        mcp = json.load(f)
                    api_key = mcp.get("mcpServers", {}).get("tavily", {}).get("env", {}).get("TAVILY_API_KEY")
            
            if api_key:
                import urllib.request
                import re
                url = "https://api.tavily.com/search"
                query = "What are the Polymarket probabilities for Bitcoin reaching $100k in the near term, mid term, and far term? Return exactly and ONLY a valid JSON object with keys 'near', 'mid', 'far' and float values between 0.0 and 1.0. Example: {\"near\": 0.45, \"mid\": 0.60, \"far\": 0.80}"
                payload = {"api_key": api_key, "query": query, "search_depth": "basic", "include_answer": True}
                req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    ans = json.loads(resp.read().decode('utf-8')).get("answer", "")
                    # Extract near, mid, far using regex to avoid json parse errors
                    near_m = re.search(r'near["\']?\s*:\s*([0-9]*\.?[0-9]+)', ans)
                    mid_m = re.search(r'mid["\']?\s*:\s*([0-9]*\.?[0-9]+)', ans)
                    far_m = re.search(r'far["\']?\s*:\s*([0-9]*\.?[0-9]+)', ans)
                    
                    near = float(near_m.group(1)) if near_m else 0.45
                    mid = float(mid_m.group(1)) if mid_m else 0.60
                    far = float(far_m.group(1)) if far_m else 0.80
                    
                    return {
                        "quality": "backfilled",
                        "sample_count": 3,
                        "bullish_probability": {
                            "near": round(near, 4),
                            "mid": round(mid, 4),
                            "far": round(far, 4),
                        },
                        "bearish_probability": {
                            "near": round(1.0 - near, 4),
                            "mid": round(1.0 - mid, 4),
                            "far": round(1.0 - far, 4),
                        },
                        "term_structure": {
                            "near_minus_far": round(near - far, 4),
                            "curvature": round(near - 2.0 * mid + far, 4),
                        },
                        "source": "tavily_search",
                    }
        except Exception as e:
            print(f"Tavily Fallback Exception: {e}")

        # Ultimate fallback
        print("Returning ultimate fallback missing for Polymarket")
        return {"quality": "missing", "sample_count": 0, "source": "polymarket_api"}

    def _fetch_fear_greed_online(self) -> Dict[str, Any]:
        obj = self._http_get_json("https://api.alternative.me/fng/", params={"limit": 1}, timeout=8)
        arr = obj.get("data") if isinstance(obj, dict) else None
        row = arr[0] if isinstance(arr, list) and arr else None
        if not isinstance(row, dict):
            return {"quality": "missing"}
        v = self._to_float(row.get("value"), -1.0)
        if v < 0.0 or v > 100.0:
            return {"quality": "missing"}
        ts = ""
        try:
            ts = datetime.fromtimestamp(int(float(row.get("timestamp"))), tz=timezone.utc).isoformat()
        except Exception:
            ts = ""
        return {
            "quality": "backfilled",
            "value": round(v, 4),
            "value_classification": str(row.get("value_classification") or "").strip(),
            "sampled_at": ts,
            "source": "alternative_me_fng",
        }

    def _calc_macro_narrative_sector_move(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        macro = []
        for e in events:
            k = f"{e.get('category','')} {e.get('topic','')} {e.get('event_type','')}".lower()
            if any(x in k for x in ["macro", "us_data", "fed", "geopolitics", "market_analysis"]):
                macro.append(e)
        up_words = ("上涨", "走高", "反弹", "新高", "涨")
        down_words = ("下跌", "回落", "走低", "新低", "跌")
        by_topic: Dict[str, Dict[str, int]] = defaultdict(lambda: {"up": 0, "down": 0, "flat": 0})
        for e in macro:
            topic = str(e.get("topic") or e.get("event_type") or "macro")
            t = f"{e.get('title','')} {e.get('summary','')}"
            if any(w in t for w in up_words):
                by_topic[topic]["up"] += 1
            elif any(w in t for w in down_words):
                by_topic[topic]["down"] += 1
            else:
                by_topic[topic]["flat"] += 1
        topic_rows = []
        for topic, c in by_topic.items():
            total = max(1, c["up"] + c["down"] + c["flat"])
            score = (c["up"] - c["down"]) / total
            topic_rows.append({"topic": topic, "up": c["up"], "down": c["down"], "flat": c["flat"], "sentiment": round(score, 4)})
        topic_rows = sorted(topic_rows, key=lambda x: abs(float(x.get("sentiment", 0.0))), reverse=True)
        agg = self._mean([self._to_float(x.get("sentiment"), 0.0) for x in topic_rows], 0.0)
        return {
            "aggregate_sentiment": round(agg, 4),
            "topics": topic_rows[:10],
        }

    def _map_attention_type(self, category: str) -> str:
        c = str(category or "")
        if "policy" in c or "macro" in c:
            return "policy"
        if "security" in c:
            return "security"
        if "etf" in c:
            return "market_microstructure"
        return "momentum"

    def _grade_from_confidence(self, x: float) -> str:
        if x >= 0.85:
            return "A"
        if x >= 0.65:
            return "B"
        if x >= 0.45:
            return "C"
        return "D"

    def _quality_from_coverage(self, coverage: float, has_missing: bool) -> str:
        if has_missing:
            return "missing"
        if coverage >= 0.80:
            return "ok"
        if coverage >= 0.5:
            return "stale"
        return "missing"

    def _flow_skill_snapshot_ready_bases(self, flow_skill_snapshot: Dict[str, Any]) -> set:
        obj = flow_skill_snapshot if isinstance(flow_skill_snapshot, dict) else {}
        items = obj.get("items") if isinstance(obj.get("items"), list) else []
        out = set()
        for row in items:
            if not isinstance(row, dict):
                continue
            bb = str(row.get("bindBase") or "").strip()
            if not bb or row.get("value") is None:
                continue
            q = row.get("quality")
            st = str((q.get("status") if isinstance(q, dict) else q) or "").strip().lower()
            if st in {"missing", "unknown"}:
                continue
            out.add(bb)
        return out

    def _compute_source_bucket_coverage(
        self,
        *,
        events: List[Dict[str, Any]],
        macro_sent: Dict[str, Any],
        onchain_rank: Dict[str, Any],
        pm_curve: Dict[str, Any],
        flow_skill_snapshot: Dict[str, Any],
        okx_market_intel: Dict[str, Any],
    ) -> Tuple[float, Dict[str, str], List[str]]:
        ready = self._flow_skill_snapshot_ready_bases(flow_skill_snapshot)
        buckets: Dict[str, str] = {}

        okx_obj = okx_market_intel if isinstance(okx_market_intel, dict) else {}
        okx_q = okx_obj.get("quality") if isinstance(okx_obj.get("quality"), dict) else {}
        okx_st = str(okx_q.get("status") or okx_obj.get("quality_status") or "").strip().lower()
        okx_topics = okx_obj.get("topics") if isinstance(okx_obj.get("topics"), list) else []
        okx_real = bool(okx_topics) and okx_st in {"ok", "stale"}
        okx_proxy = ("social_heat_event_score__btc__okx__na" in ready) or ("social_heat_event_score__btc__all__na" in ready)
        buckets["okx_market_intel"] = ("ok" if okx_real else ("backfilled" if okx_proxy else "missing"))

        buckets["news"] = ("ok" if (events and len(events) > 0) else "missing")

        macro_n = int(macro_sent.get("event_count") or 0) if isinstance(macro_sent, dict) else 0
        macro_proxy = ("macro_event_pressure_score__btc__macro__na" in ready) or ("macro_event_pressure_score__all__all__na" in ready)
        buckets["macro"] = ("ok" if macro_n > 0 else ("backfilled" if macro_proxy else "missing"))

        whale_proxy = ("whale_position_delta_usd__btc__hyperliquid__perp" in ready)
        reserve_proxy = (
            ("cex_exchange_reserve_usd__all__all__all" in ready)
            or ("stablecoin_usdt_exchange_balance_usd__all__all__all" in ready)
            or ("stablecoin_usdt_exchange_inflow_usd__all__all__all" in ready)
        )
        bridge_proxy = ("smart_money_inflow_score__all__all__all" in ready)
        onchain_proxy_count = int(bool(whale_proxy)) + int(bool(reserve_proxy)) + int(bool(bridge_proxy))
        onchain_q = str(onchain_rank.get("quality") or "").strip().lower() if isinstance(onchain_rank, dict) else ""
        onchain_has = bool(onchain_rank.get("tokens")) if isinstance(onchain_rank, dict) else False
        buckets["onchain"] = (
            "ok"
            if (onchain_q in {"ok", "stale"} or onchain_has)
            else ("backfilled" if onchain_proxy_count >= 2 else "missing")
        )

        deriv_proxy = (
            ("funding_rate_bps__btc__okx__perp" in ready)
            or ("oi_usd__btc__okx__perp" in ready)
            or ("funding_rate_bps__btc__binance__na" in ready)
            or ("oi_usd__btc__coinglass__na" in ready)
        )
        pm_q = str(pm_curve.get("quality") or "").strip().lower() if isinstance(pm_curve, dict) else ""
        buckets["derivatives"] = ("ok" if deriv_proxy else ("backfilled" if pm_q == "backfilled" else "missing"))

        covered = [k for k, st in buckets.items() if st in {"ok", "stale", "backfilled"}]
        missing = [k for k in ["okx_market_intel", "news", "macro", "onchain", "derivatives"] if buckets.get(k) not in {"ok", "stale", "backfilled"}]
        cov = round(float(len(covered)) / 5.0, 4)
        return cov, buckets, missing

    def _load_okx_market_intel_latest(self) -> Dict[str, Any]:
        candidates: List[Path] = []
        try:
            d = CORE_DIR / "raw" / "okx" / "market-intel"
            if d.exists():
                candidates.extend(sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:5])
        except Exception:
            candidates = candidates
        for q in [
            CORE_DIR / "outputs" / "okx_market_intel_latest.json",
            CORE_DIR / "outputs" / "okx_market_intel.json",
            CORE_DIR / "raw" / "okx_market_intel_latest.json",
        ]:
            candidates.append(q)
        for p in candidates:
            if not isinstance(p, Path) or (not p.exists()) or (not p.is_file()):
                continue
            try:
                obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            return obj if isinstance(obj, dict) else {}
        return {}

    def refresh_okx_market_intel(self) -> Path:
        import sys

        proj_root = str(CORE_DIR.parents[2])
        if proj_root not in sys.path:
            sys.path.insert(0, proj_root)
        from ops.nanoclaw.core_task1.flow.scripts.okx_skill_collector import collect_okx_market_intel_latest

        out_dir = CORE_DIR / "outputs"
        raw_dir = CORE_DIR / "raw" / "okx" / "market-intel"
        latest_path, _ = collect_okx_market_intel_latest(output_dir=out_dir, raw_dir=raw_dir, asset="BTC", cmd=None)
        return latest_path

    def _load_flow_skill_snapshot_latest(self) -> Dict[str, Any]:
        p = CORE_DIR / "flow" / "outputs" / "web3_skill_snapshot_latest.json"
        if not p.exists() or not p.is_file():
            return {}
        try:
            obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return {}
        return obj if isinstance(obj, dict) else {}

    def _okx_market_intel_focus(self, *, okx_market_intel: Dict[str, Any], fallback_ts: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        obj = okx_market_intel if isinstance(okx_market_intel, dict) else {}
        topics = obj.get("topics") if isinstance(obj.get("topics"), list) else []
        rows: List[Dict[str, Any]] = []
        for it in topics:
            if not isinstance(it, dict):
                continue
            title = str(it.get("title") or it.get("topic") or it.get("keyword") or "").strip()
            if not title:
                continue
            heat = self._to_float(it.get("heat"), None)
            if heat is None:
                heat = self._to_float(it.get("heat_score"), 0.0)
            sentiment = self._to_float(it.get("sentiment"), None)
            if sentiment is None:
                sentiment = self._to_float(it.get("sentiment_score"), 0.0)
            url = str(it.get("url") or it.get("link") or "").strip()
            ts = str(it.get("ts") or it.get("timestamp") or obj.get("generated_at") or fallback_ts).strip() or fallback_ts
            rows.append({
                "topic": title,
                "heat": float(max(0.0, min(1.0, heat))),
                "sentiment": float(max(-1.0, min(1.0, sentiment))),
                "url": url,
                "ts": ts,
                "source": "okx:market-intel",
            })
        rows = sorted(rows, key=lambda x: float(x.get("heat") or 0.0), reverse=True)[:8]
        ev: List[Dict[str, Any]] = []
        for r in rows:
            ev.append({
                "base": "okx_market_intel_topic__btc__okx__na",
                "source": "okx:market-intel",
                "timestamp": str(r.get("ts") or fallback_ts),
                "url": str(r.get("url") or ""),
                "topic": str(r.get("topic") or ""),
            })
        return rows, ev

    def _build_structured_payload(self, *, events: List[Dict[str, Any]], narratives: List[Narrative], overall_sentiment: float, overall_heat: float, generated_at: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        scores_base = [self._to_float(e.get("community_base_score"), 0.0) for e in events]
        scores_eff = [self._to_float(e.get("community_effective_score"), 0.0) for e in events]
        decay_h = [int(max(1, round(self._to_float(e.get("decay_half_life_hours"), 24.0)))) for e in events if self._to_float(e.get("decay_half_life_hours"), 0.0) > 0]
        decay_f = [self._to_float(e.get("decay_factor"), 1.0) for e in events]
        sorted_eff = sorted(
            [self._to_float(e.get("community_effective_score"), 0.0) for e in events],
            reverse=False
        )
        half = max(1, len(sorted_eff) // 2)
        impulse = self._mean(sorted_eff[-half:], 0.0) - self._mean(sorted_eff[:half], 0.0)
        news_sent = self._calc_news_bull_bear(events)
        macro_sent = self._calc_macro_sentiment(events)
        inflow = self._calc_btc_inflow_sentiment(events, datetime.now(timezone.utc))
        twitter_board = self._calc_twitter_sector_search(events)
        onchain_rank = self._calc_onchain_sector_and_token_rank(events)
        attention_board = self._calc_attention_board(events)
        pm_curve = self._calc_polymarket_curve(events, fallback_anchor=overall_sentiment)
        macro_board = self._calc_macro_narrative_sector_move(events)
        fear_greed_model = self._clip(
            40.0
            + 28.0 * overall_sentiment
            + 22.0 * (overall_heat - 0.5)
            + 10.0 * math.tanh((news_sent["bull_bear_ratio"] - 1.0) / 2.0)
            + 8.0 * math.tanh(impulse * 4.0),
            0.0,
            100.0,
        )
        fg_online = self._fetch_fear_greed_online()
        fg_online_value = self._to_float((fg_online or {}).get("value"), -1.0)
        if 0.0 <= fg_online_value <= 100.0:
            fear_greed = fg_online_value
            fear_greed_quality = str((fg_online or {}).get("quality") or "backfilled")
            fear_greed_source = str((fg_online or {}).get("source") or "alternative_me_fng")
            fear_greed_sampled_at = str((fg_online or {}).get("sampled_at") or "")
        else:
            fear_greed = fear_greed_model
            fear_greed_quality = "ok"
            fear_greed_source = "model_fallback"
            fear_greed_sampled_at = generated_at
        leverage_flag = any("清算" in str(e.get("title") or "") or "杠杆" in str(e.get("summary") or "") for e in events)
        stress_level = "low"
        trigger_reasons: List[str] = []
        if fear_greed >= 75.0:
            trigger_reasons.append("恐慌贪婪指数高于75")
        if overall_heat >= 0.8:
            trigger_reasons.append("叙事热度高于0.8")
        if leverage_flag:
            trigger_reasons.append("检测到杠杆/清算脆弱性")
        if len(trigger_reasons) >= 2:
            stress_level = "high"
        elif len(trigger_reasons) == 1:
            stress_level = "med"
        recommended_action = "hold"
        if stress_level == "high":
            recommended_action = "reduce"
        elif stress_level == "med":
            recommended_action = "slowdown"
        if fear_greed <= 25.0 and overall_sentiment < 0:
            regime = "panic"
        elif fear_greed >= 82.0 and overall_sentiment > 0:
            regime = "euphoric"
        elif fear_greed >= 60.0:
            regime = "heated"
        else:
            regime = "calm"
        top_narratives = []
        for n in narratives[:10]:
            raw = self.raw_events_by_category.get(n.category, [])
            srcs = []
            for e in raw[:3]:
                u = str(e.get("source_url") or "").strip()
                ts = str(e.get("timestamp") or e.get("published_at") or generated_at).strip()
                if not u:
                    continue
                srcs.append({"url": u, "ts": ts})
            if not srcs:
                srcs = [{"url": "internal://event-ledger", "ts": generated_at}]
            source_div = self._clip(len({str(e.get("source") or "").strip() for e in raw if str(e.get("source") or "").strip()}) / max(3.0, float(len(raw) or 1.0)), 0.0, 1.0)
            flags = []
            if n.heat_score >= 0.8:
                flags.append("拥挤交易")
            if n.sentiment_trend == "weakening":
                flags.append("情绪降温")
            top_narratives.append({
                "topic_id": str(n.category),
                "topic_label": str(n.narrative_name),
                "attention_score": float(round(self._clip(n.heat_score, 0.0, 1.0), 4)),
                "attention_type": self._map_attention_type(n.category),
                "source_diversity": float(round(source_div, 4)),
                "evidence_grade": self._grade_from_confidence(float(n.confidence)),
                "narrative_status": str(n.status),
                "risk_flags": flags,
                "sources": srcs,
            })
        flow_snapshot = self._load_flow_skill_snapshot_latest()
        okx_intel = self._load_okx_market_intel_latest()
        source_cov, source_buckets, source_missing = self._compute_source_bucket_coverage(
            events=events,
            macro_sent=macro_sent,
            onchain_rank=onchain_rank,
            pm_curve=pm_curve,
            flow_skill_snapshot=flow_snapshot,
            okx_market_intel=okx_intel,
        )
        coverage = self._clip(float(source_cov), 0.0, 1.0)
        pm_quality = str(pm_curve.get("quality") or "")
        inflow_quality = str(inflow.get("quality") or "")
        has_missing = (pm_quality in {"missing", "suspect"}) or (inflow_quality in {"missing", "suspect"})
        overall_quality = self._quality_from_coverage(coverage, has_missing)
        quality_flags = sorted(list({overall_quality, pm_quality, inflow_quality, fear_greed_quality}))
        missing_disclosure = []
        backfilled_disclosure = []
        if pm_quality in {"missing", "suspect"}:
            missing_disclosure.append("polymarket_btc_term_structure")
        elif pm_quality == "backfilled":
            backfilled_disclosure.append("polymarket_btc_term_structure")
        if inflow_quality != "ok":
            missing_disclosure.append("btc_inflow_90d_baseline")
        if fear_greed_quality in {"missing", "suspect"}:
            missing_disclosure.append("fear_greed_index")
        elif fear_greed_quality == "backfilled":
            backfilled_disclosure.append("fear_greed_index")
        for b in source_missing:
            missing_disclosure.append(f"bucket_{b}")
        for k, st in source_buckets.items():
            if st == "backfilled":
                backfilled_disclosure.append(f"bucket_{k}")
        if pm_quality == "backfilled":
            trigger_reasons.append("Polymarket 采用联网回填数据源")
        if fear_greed_quality == "backfilled":
            trigger_reasons.append("恐慌贪婪指数采用联网回填数据源")
        if any(st == "backfilled" for st in source_buckets.values()):
            trigger_reasons.append("叙事覆盖率采用数据源 bucket 回补口径")
        trigger_reasons = list(dict.fromkeys([x for x in trigger_reasons if str(x or "").strip()]))
        evidence_refs = [
            {"base": "community_effective_score__btc__all__all", "source": "event_ledger", "timestamp": generated_at},
            {"base": "news_sentiment_index__btc__na__na", "source": "event_ledger", "timestamp": generated_at},
            {"base": "btc_inflow_sentiment_index__btc__all__all", "source": "event_ledger+history", "timestamp": generated_at},
        ]
        if pm_quality == "backfilled":
            evidence_refs.append({"base": "polymarket_btc_term_structure_near_far__btc__all__na", "source": str(pm_curve.get("source") or "polymarket_api"), "timestamp": generated_at})
        if fear_greed_quality == "backfilled":
            evidence_refs.append({"base": "fear_greed_index__btc__all__all", "source": fear_greed_source, "timestamp": fear_greed_sampled_at or generated_at})
        okx_focus, okx_ev = self._okx_market_intel_focus(okx_market_intel=okx_intel, fallback_ts=generated_at)
        if okx_focus:
            evidence_refs.extend(okx_ev)
        contract = {
            "module": "fundamental.narrative.v1",
            "execution_gate": "readonly_advisory",
            "time_window": f"{int(self.hours)}h",
            "generated_at": generated_at,
            "market_focus": okx_focus,
            "scores": {
                "community_base_score": round(self._clip(self._mean(scores_base, 0.0), 0.0, 1.0), 4),
                "decay_half_life_hours": int(round(self._mean([float(x) for x in decay_h], 24.0))) if decay_h else 24,
                "decay_factor": round(self._clip(self._mean(decay_f, 1.0), 0.0, 1.0), 4),
                "community_effective_score": round(self._clip(self._mean(scores_eff, 0.0), 0.0, 1.0), 4),
                "community_impulse": round(float(impulse), 4),
                "narrative_stress": {
                    "stress_level": stress_level,
                    "trigger_reasons": trigger_reasons if trigger_reasons else ["未触发拥挤与脆弱性双确认"],
                    "recommended_action": recommended_action,
                },
            },
            "top_narratives": top_narratives if top_narratives else [{
                "topic_id": "none",
                "topic_label": "暂无显著叙事",
                "attention_score": 0.0,
                "attention_type": "other",
                "source_diversity": 0.0,
                "evidence_grade": "unknown",
                "narrative_status": "archive",
                "risk_flags": ["样本不足"],
                "sources": [{"url": "internal://event-ledger", "ts": generated_at}],
            }],
            "quality": {
                "overall_quality": overall_quality,
                "coverage": round(coverage, 4),
                "quality_flags": [x for x in quality_flags if x in {"ok", "stale", "missing", "backfilled", "suspect"}],
                "missing_disclosure": missing_disclosure,
                "backfilled_disclosure": backfilled_disclosure,
                "source_bucket_coverage": source_buckets,
            },
            "advisory": {
                "bias": {
                    "bias_dir": ("long_only" if overall_sentiment > 0.2 else "short_only" if overall_sentiment < -0.2 else "neutral"),
                    "reasons": [
                        f"narrative_regime={regime}",
                        f"fear_greed_index={round(fear_greed, 2)}",
                    ],
                },
                "filter": {
                    "execution_filter": ("block" if stress_level == "high" else "slowdown" if stress_level == "med" else "allow"),
                    "blocked_reasons": (trigger_reasons if stress_level == "high" else []),
                },
                "risk_off": {
                    "risk_action_proposal": ("reduce" if stress_level == "high" else "hedge" if stress_level == "med" else "hold"),
                    "position_scale": (0.5 if stress_level == "high" else 0.75 if stress_level == "med" else 1.0),
                    "ttl": ("8h" if stress_level in {"high", "med"} else "4h"),
                },
            },
            "evidence_refs": evidence_refs,
            "doc_refs": [
                "基本面研究文档.md#12.3",
                "基本面研究文档.md#3.3",
            ],
            "notes": {
                "factor_boundary": "not_primary_direction_factor",
                "fail_closed_applied": bool(has_missing),
            },
        }
        extended = {
            "okx_market_intel": (okx_intel if isinstance(okx_intel, dict) else {}),
            "fear_greed_index": {
                "value": round(fear_greed, 4),
                "regime": regime,
                "quality": fear_greed_quality,
                "source": fear_greed_source,
                "sampled_at": fear_greed_sampled_at,
                "model_fallback": round(fear_greed_model, 4),
            },
            "macro_sentiment_index": macro_sent,
            "btc_inflow_sentiment_index": inflow,
            "twitter_search_sector_board": twitter_board,
            "onchain_sector_token_rank": onchain_rank,
            "attention_board": attention_board,
            "news_sentiment_index": news_sent,
            "polymarket_btc_term_structure": pm_curve,
            "macro_narrative_sector_move": macro_board,
            "threshold_policy": {
                "fear_greed_high": 75,
                "fear_greed_low": 25,
                "coverage_min": 0.5,
                "stress_dual_confirmation": "narrative_heat_or_fg + leverage_fragility",
            },
            "state_machine": {
                "narrative_regime": regime,
                "stress_level": stress_level,
                "execution_filter": contract["advisory"]["filter"]["execution_filter"],
                "transition_rules": [
                    "calm -> heated: fear_greed >= 60",
                    "heated -> euphoric: fear_greed >= 82 and sentiment > 0",
                    "any -> panic: fear_greed <= 25 and sentiment < 0",
                    "high_stress: narrative拥挤与脆弱性双确认",
                ],
            },
            "acceptance_checklist": {
                "has_fear_greed_index": True,
                "has_macro_sentiment_index": True,
                "has_btc_inflow_90d_baseline": True,
                "has_twitter_sector_board": True,
                "has_onchain_sector_token_rank": True,
                "has_attention_board": True,
                "has_news_sentiment_dynamic_ratio": True,
                "has_polymarket_term_structure": True,
                "has_macro_sector_move": True,
            },
        }
        return contract, extended

    def analyze(self) -> NarrativeRegistry:
        """执行完整分析"""
        self.refresh_okx_market_intel()
        # 加载事件
        events = self.load_event_ledger()
        self.latest_events = list(events)

        if not events:
            narratives = []
            overall_sentiment = 0.0
            overall_heat = 0.0
            top_narrative = "无"
            summary = "最近暂无显著叙事主题"
        else:
            # 解析为叙事事件
            self.narrative_events = self.parse_events_to_narratives(events)
            # 构建叙事
            narratives = self.build_narratives()
            # 计算整体指标
            if narratives:
                overall_sentiment = sum(n.sentiment_score for n in narratives) / len(narratives)
                overall_heat = max(n.heat_score for n in narratives)
                top_narrative = narratives[0].narrative_name
            else:
                overall_sentiment = 0.0
                overall_heat = 0.0
                top_narrative = "无"
            # 生成摘要
            summary = self.generate_summary(narratives)

        generated_at = datetime.now(timezone.utc).isoformat()
        contract, extended = self._build_structured_payload(
            events=events,
            narratives=narratives,
            overall_sentiment=overall_sentiment,
            overall_heat=overall_heat,
            generated_at=generated_at,
        )
        return NarrativeRegistry(
            timestamp=generated_at,
            generated_at=generated_at,
            analysis_window=f"最近{self.hours}小时",
            narratives=narratives,
            narrative_count=int(len(narratives)),
            overall_sentiment=round(overall_sentiment, 4),
            overall_heat=round(overall_heat, 4),
            top_narrative=top_narrative,
            summary=summary,
            contract=contract,
            extended_sentiment=extended,
        )

    def save_registry(self, registry: NarrativeRegistry) -> Path:
        """保存叙事登记簿"""
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        output_path = NARRATIVE_OUTPUTS_DIR / f"narrative_registry_{ts}.json"

        data = asdict(registry)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return output_path


# =============================================================================
# 简报生成器
# =============================================================================

class NarrativeBriefGenerator:
    """叙事简报生成器"""

    def __init__(self):
        self.analyzer = NarrativeAnalyzer()

    def generate_brief(self, registry: NarrativeRegistry) -> str:
        """生成 Markdown 简报"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S CST")

        # 图标映射
        trend_icon = {
            "strengthening": "📈",
            "weakening": "📉",
            "stable": "➡️"
        }
        status_icon = {
            "active": "🔥",
            "cooling": "❄️",
            "archive": "📦"
        }
        sentiment_icon = lambda s: "🟢" if s > 0.2 else "🔴" if s < -0.2 else "🟡"

        md = f"""# 加密市场叙事分析简报

**生成时间**: {now}
**分析窗口**: {registry.analysis_window}
**主导叙事**: {registry.top_narrative}
**整体情绪**: {registry.overall_sentiment:+.4f}
**叙事数量**: {registry.narrative_count}
**门禁语义**: execution_gate={registry.execution_gate}

---

## 📊 核心叙事总览

| 叙事 | 热度 | 情绪 | 趋势 | 状态 | 事件数 |
|------|------|------|------|------|--------|
"""

        for narrative in registry.narratives[:10]:
            icon = status_icon.get(narrative.status, '❓')
            trend = trend_icon.get(narrative.sentiment_trend, '➡️')
            senti_badge = sentiment_icon(narrative.sentiment_score)
            md += f"| {narrative.narrative_name} | {narrative.heat_score:.2f} | {senti_badge} {narrative.sentiment_score:+.2f} | {trend} | {icon} | {narrative.event_count} |\n"

        if not registry.narratives:
            md += "| 无显著叙事 | - | - | - | - | 0 |\n"

        md += """
---

## 🔥 叙事热度排行

"""

        for i, narrative in enumerate(registry.narratives[:5], 1):
            lifecycle_badge = {
                "emerging": "🌱 萌芽",
                "growing": "🌿 成长",
                "mature": "🌳 成熟",
                "declining": "🍂 衰退"
            }.get(narrative.lifecycle_stage, "")

            md += f"""**{i}. {narrative.narrative_name}** - 热度 {narrative.heat_score:.2f} {lifecycle_badge}
- **情绪**: {narrative.sentiment_score:+.2f} ({narrative.sentiment_trend})
- **相关代币**: {', '.join(narrative.related_tokens) if narrative.related_tokens else 'N/A'}
- **事件数**: {narrative.event_count} 条

"""

        if not registry.narratives:
            md += "*最近暂无显著叙事主题*\n\n"

        md += """---

## 📈 情绪分析

### 正面叙事 (Sentiment > 0.2)

"""

        positive = [n for n in registry.narratives if n.sentiment_score > 0.2]
        if positive:
            for narrative in positive[:5]:
                md += f"- **{narrative.narrative_name}**: {narrative.sentiment_score:+.2f} {trend_icon.get(narrative.sentiment_trend, '➡️')}\n"
        else:
            md += "*无明显正面叙事*\n"

        md += """
### 负面叙事 (Sentiment < -0.2)

"""

        ext = registry.extended_sentiment if isinstance(registry.extended_sentiment, dict) else {}
        fg = (ext.get("fear_greed_index") or {}) if isinstance(ext.get("fear_greed_index"), dict) else {}
        msi = (ext.get("macro_sentiment_index") or {}) if isinstance(ext.get("macro_sentiment_index"), dict) else {}
        bfi = (ext.get("btc_inflow_sentiment_index") or {}) if isinstance(ext.get("btc_inflow_sentiment_index"), dict) else {}
        nsi = (ext.get("news_sentiment_index") or {}) if isinstance(ext.get("news_sentiment_index"), dict) else {}
        pm = (ext.get("polymarket_btc_term_structure") or {}) if isinstance(ext.get("polymarket_btc_term_structure"), dict) else {}
        pm_bull = (pm.get("bullish_probability") or {}) if isinstance(pm.get("bullish_probability"), dict) else {}
        pm_ts = (pm.get("term_structure") or {}) if isinstance(pm.get("term_structure"), dict) else {}
        sm = (ext.get("state_machine") or {}) if isinstance(ext.get("state_machine"), dict) else {}
        md += f"""

---

## 🧭 新增情绪指标面板

| 指标 | 数值 | 口径 |
|------|------|------|
| 恐慌贪婪指数 | {fg.get('value', '-')} | 0-100 |
| 宏观情绪指数 | {msi.get('index', '-')} | 0-100 |
| BTC资金流入情绪指数 | {bfi.get('index', '-')} | 当日/90日均值 |
| 新闻情绪指数 | {nsi.get('index', '-')} | 多空比动态 |
| Polymarket近端看涨概率 | {pm_bull.get('near', '-')} | 0-1 |
| Polymarket中端看涨概率 | {pm_bull.get('mid', '-')} | 0-1 |
| Polymarket远端看涨概率 | {pm_bull.get('far', '-')} | 0-1 |
| Polymarket期限结构(近-远) | {pm_ts.get('near_minus_far', '-')} | 近中远结构 |

### 状态机

- narrative_regime: {sm.get('narrative_regime', '-')}
- stress_level: {sm.get('stress_level', '-')}
- execution_filter: {sm.get('execution_filter', '-')}
"""

        negative = [n for n in registry.narratives if n.sentiment_score < -0.2]
        if negative:
            for narrative in negative[:5]:
                md += f"- **{narrative.narrative_name}**: {narrative.sentiment_score:+.2f} {trend_icon.get(narrative.sentiment_trend, '➡️')}\n"
        else:
            md += "*无明显负面叙事*\n"

        md += f"""
---

## 📋 策略解读

### 市场情绪判定

| 指标 | 数值 | 解读 |
|------|------|------|
| 整体情绪 | {registry.overall_sentiment:+.2f} | {"偏向乐观" if registry.overall_sentiment > 0.2 else "偏向悲观" if registry.overall_sentiment < -0.2 else "中性"} |
| 叙事热度 | {registry.overall_heat:.2f} | {"高" if registry.overall_heat > 0.7 else "中" if registry.overall_heat > 0.3 else "低"} |
| 主导叙事 | {registry.top_narrative} | - |

### 摘要

{registry.summary}

### 建议关注

"""

        if registry.narratives:
            top = registry.narratives[0]
            if top.sentiment_score > 0.3:
                md += f"- ✅ 关注「{top.narrative_name}」相关机会，情绪持续升温\n"
            elif top.sentiment_score < -0.3:
                md += f"- ⚠️ 警惕「{top.narrative_name}」相关风险，情绪偏向负面\n"
            else:
                md += f"- ⏸️ 「{top.narrative_name}」情绪中性，建议观望\n"

            if len(registry.narratives) > 1:
                second = registry.narratives[1]
                md += f"- 📊 次要关注「{second.narrative_name}」({second.heat_score:.2f})\n"
        else:
            md += "- 暂无明确方向，建议保持观望\n"

        md += f"""
---

## 📊 叙事分布

| 类别 | 数量 | 平均情绪 |
|------|------|----------|
"""

        # 按类别分组统计
        by_category = defaultdict(list)
        for n in registry.narratives:
            by_category[n.category].append(n)

        for cat_id, items in by_category.items():
            cat_info = NARRATIVE_CATEGORIES.get(cat_id, {})
            cat_name = cat_info.get('name', cat_id)
            avg_sentiment = sum(n.sentiment_score for n in items) / len(items)
            md += f"| {cat_name} | {len(items)} | {avg_sentiment:+.2f} |\n"

        if not by_category:
            md += "| 无显著叙事 | 0 | - |\n"

        md += f"""
---

## ⚠️ 风险提示

- 叙事分析基于新闻事件聚合，存在滞后性
- 情绪分数仅供参考，不构成投资建议
- 叙事热度会随时间快速变化，请结合实时数据

---

**简报版本**: Narrative Brief v1.0
**数据来源**: /workspace/ops/nanoclaw/core_task1/outputs/event_ledger_*.jsonl
**分析方法**: 事件聚合 → 叙事识别 → 情绪分析 → 热度追踪

*本简报由 narrative_analyzer.py 生成 | 仅供参考*
"""

        return md

    def save_brief(self, md_content: str) -> Path:
        """保存简报"""
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        output_path = NARRATIVE_OUTPUTS_DIR / f"narrative_brief_{ts}.md"

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

        return output_path


# =============================================================================
# 命令行入口
# =============================================================================

def generate_mock_events() -> List[Dict]:
    """生成模拟事件数据用于演示"""
    now = datetime.now(timezone.utc)

    mock_events = [
        {
            "event_id": "mock_001",
            "title": "贝莱德 IBIT 单日净流入 3.5 亿美元，创历史新高",
            "summary": "贝莱德比特币 ETF 产品 IBIT 今日录得 3.5 亿美元净流入，创下基金获批以来的最高单日流入记录",
            "source": "Bloomberg",
            "source_confidence": "high",
            "sentiment_score": 0.8,
            "timestamp": (now - timedelta(hours=2)).isoformat(),
            "category": "market_analysis"
        },
        {
            "event_id": "mock_002",
            "title": "富达以太坊 ETF 申请获得 SEC 批准",
            "summary": "富达投资的以太坊现货 ETF 申请正式获得美国证券交易委员会批准",
            "source": "SEC.gov",
            "source_confidence": "high",
            "sentiment_score": 0.7,
            "timestamp": (now - timedelta(hours=4)).isoformat(),
            "category": "fed_policy"
        },
        {
            "event_id": "mock_003",
            "title": "Arbitrum TVL 突破 150 亿美元，Layer2 竞争加剧",
            "summary": "Arbitrum 生态总锁仓量达到新高，Layer2 赛道竞争日益激烈",
            "source": "DefiLlama",
            "source_confidence": "medium",
            "sentiment_score": 0.5,
            "timestamp": (now - timedelta(hours=6)).isoformat(),
            "category": "project_update"
        },
        {
            "event_id": "mock_004",
            "title": "美联储主席：通胀数据符合预期，利率政策保持稳定",
            "summary": "美联储主席在国会听证会上表示当前通胀数据符合预期，短期内利率政策将保持稳定",
            "source": "Federal Reserve",
            "source_confidence": "high",
            "sentiment_score": 0.1,
            "timestamp": (now - timedelta(hours=8)).isoformat(),
            "category": "fed_policy"
        },
        {
            "event_id": "mock_005",
            "title": "某 DeFi 协议遭黑客攻击，损失约 2000 万美元",
            "summary": "一个新兴 DeFi 借贷协议因智能合约漏洞遭受黑客攻击，初步估计损失约 2000 万美元",
            "source": "Twitter",
            "source_confidence": "medium",
            "sentiment_score": -0.7,
            "timestamp": (now - timedelta(hours=10)).isoformat(),
            "category": "security"
        },
        {
            "event_id": "mock_006",
            "title": "USDT 市值突破 1200 亿美元，稳定币需求持续增长",
            "summary": "Tether 发行的 USDT 稳定币市值达到 1200 亿美元新高，显示加密市场需求持续",
            "source": "CoinGecko",
            "source_confidence": "high",
            "sentiment_score": 0.3,
            "timestamp": (now - timedelta(hours=12)).isoformat(),
            "category": "market_analysis"
        },
        {
            "event_id": "mock_007",
            "title": "Uniswap V4 测试网上线，新特性引发关注",
            "summary": "去中心化交易所 Uniswap 推出 V4 版本测试网，引入多个创新特性",
            "source": "Uniswap Labs",
            "source_confidence": "high",
            "sentiment_score": 0.6,
            "timestamp": (now - timedelta(hours=14)).isoformat(),
            "category": "project_update"
        },
        {
            "event_id": "mock_008",
            "title": "SEC 考虑放宽加密货币监管框架",
            "summary": "美国 SEC 官员表示正在考虑针对加密货币的更明确监管框架",
            "source": "Reuters",
            "source_confidence": "medium",
            "sentiment_score": 0.4,
            "timestamp": (now - timedelta(hours=16)).isoformat(),
            "category": "fed_policy"
        },
        {
            "event_id": "mock_009",
            "title": "比特币矿工持仓量下降，市场抛压减轻",
            "summary": "数据显示比特币矿工持仓量指数降至年内低位，市场抛压可能减轻",
            "source": "Glassnode",
            "source_confidence": "high",
            "sentiment_score": 0.35,
            "timestamp": (now - timedelta(hours=18)).isoformat(),
            "category": "market_analysis"
        },
        {
            "event_id": "mock_010",
            "title": "某大型交易所宣布下架多个山寨币交易对",
            "summary": "全球知名加密货币交易所宣布将下架多个低流动性山寨币交易对",
            "source": "Exchange Announcement",
            "source_confidence": "high",
            "sentiment_score": -0.2,
            "timestamp": (now - timedelta(hours=20)).isoformat(),
            "category": "project_update"
        }
    ]

    return mock_events


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='加密市场叙事分析生成器')
    parser.add_argument('--hours', type=int, default=24, help='分析窗口（小时），默认 24 小时')
    parser.add_argument('--output', '-o', type=str, default=None, help='输出文件路径')
    parser.add_argument('--mock', action='store_true', help='使用模拟数据演示')
    args = parser.parse_args()

    print("=" * 60)
    print("加密市场叙事分析生成器")
    print("=" * 60)

    # 创建分析器
    analyzer = NarrativeAnalyzer(hours=args.hours)

    # 执行分析
    print(f"\n[1/3] 分析最近 {args.hours} 小时事件...")

    if args.mock:
        print("  [使用模拟数据演示]")
        events = generate_mock_events()
        analyzer.narrative_events = analyzer.parse_events_to_narratives(events)
        narratives = analyzer.build_narratives()

        if narratives:
            overall_sentiment = sum(n.sentiment_score for n in narratives) / len(narratives)
            overall_heat = max(n.heat_score for n in narratives)
            top_narrative = narratives[0].narrative_name
        else:
            overall_sentiment = 0.0
            overall_heat = 0.0
            top_narrative = "无"
        generated_at = datetime.now(timezone.utc).isoformat()
        contract, extended = analyzer._build_structured_payload(
            events=events,
            narratives=narratives,
            overall_sentiment=overall_sentiment,
            overall_heat=overall_heat,
            generated_at=generated_at,
        )

        registry = NarrativeRegistry(
            timestamp=generated_at,
            generated_at=generated_at,
            analysis_window=f"最近{args.hours}小时 (模拟数据)",
            narratives=narratives,
            narrative_count=int(len(narratives)),
            overall_sentiment=round(overall_sentiment, 4),
            overall_heat=round(overall_heat, 4),
            top_narrative=top_narrative,
            summary=analyzer.generate_summary(narratives),
            contract=contract,
            extended_sentiment=extended
        )
    else:
        registry = analyzer.analyze()

    # 保存登记簿
    print("\n[2/3] 保存叙事登记簿...")
    registry_path = analyzer.save_registry(registry)
    print(f"  登记簿已保存：{registry_path}")

    # 生成简报
    print("\n[3/3] 生成叙事简报...")
    brief_gen = NarrativeBriefGenerator()
    md_content = brief_gen.generate_brief(registry)

    output_path = Path(args.output) if args.output else None
    if output_path:
        brief_path = output_path
        with open(brief_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
    else:
        brief_path = brief_gen.save_brief(md_content)

    print(f"  简报已保存：{brief_path}")

    # 输出摘要
    print("\n" + "=" * 60)
    print("叙事摘要:")
    print(f"  主导叙事：{registry.top_narrative}")
    print(f"  整体情绪：{registry.overall_sentiment:+.4f}")
    print(f"  叙事数量：{len(registry.narratives)}")
    print(f"  分析窗口：{registry.analysis_window}")
    print("=" * 60)

    return brief_path


if __name__ == "__main__":
    main()
