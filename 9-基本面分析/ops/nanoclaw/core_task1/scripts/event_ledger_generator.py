#!/usr/bin/env python3
"""
事件账本生成器（JSONL 格式）- V9.5 版本

输出契约升级为事件账本 JSONL，支持：
- event_type: 事件类型分类
- window: 时间窗口
- surprise_bucket: 意外程度分级
- risk_action_proposal: 风险行动建议

符合 9.1/9.2/9.3 迭代规范
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from enum import Enum

# 导入分析模块
sys.path.insert(0, str(Path(__file__).parent))
from traditional_finance_analyzer import TraditionalFinanceAnalyzer
from event_mapping_policy import map_event_type, is_high_grade_event


class EventType(Enum):
    """事件类型 - 9.1 规范"""
    ONCHAIN_DATA = "onchain_data"           # 链上数据
    KOL_VIEW = "kols_view"                  # 大 V 观点
    PROJECT_UPDATE = "project_update"       # 项目动态
    MONETARY_POLICY = "monetary_policy"     # 货币政策
    US_DATA = "us_data"                     # 美国数据
    GEOPOLITICS = "geopolitics"             # 地缘政治
    CRYPTO_REGULATION = "crypto_regulation" # 加密监管
    PROTOCOL_TECH = "protocol_tech"         # 协议技术
    SECURITY_INCIDENT = "security_incident" # 黑客安全
    MEME_CULTURE = "meme_culture"           # 文化与 meme
    MARKET_ANALYSIS = "market_analysis"     # 市场分析


class Window(Enum):
    """时间窗口 - 9.2 规范"""
    T0 = "T0"       # 当日 (0-24h)
    T1 = "T1"       # 数日 (1-7d)
    T2 = "T2"       # 数周 (1-4w)
    T3 = "T3"       # 数月 (1-6m)


class SurpriseBucket(Enum):
    """意外程度分级 - 9.3 规范"""
    EXPECTED = "expected"           # 符合预期
    MILD_SURPRISE = "mild"          # 轻微意外
    MODERATE_SURPRISE = "moderate"  # 中等意外
    MAJOR_SURPRISE = "major"        # 重大意外
    SHOCK = "shock"                 # 冲击性事件


class RiskActionProposal(Enum):
    """风险行动建议 - 9.3 规范"""
    HOLD = "hold"                   # 持有/观望
    REDUCE = "reduce"               # 减仓
    INCREASE = "increase"           # 加仓
    HEDGE = "hedge"                 # 对冲
    STOP_LOSS = "stop_loss"         # 止损
    TAKE_PROFIT = "take_profit"     # 止盈


@dataclass
class EventLedgerEntry:
    """事件账本条目 - V9.5 完整契约"""
    # 基础信息
    event_id: str                           # 事件唯一标识
    timestamp: str                          # ISO8601 时间戳
    source: str                             # 数据来源

    # 9.1 规范：事件类型
    event_type: str                         # EventType 枚举值

    # 9.2 规范：时间窗口
    window: str                             # Window 枚举值
    window_range: str                       # 文档口径：[-48h,+48h] 等
    published_at: str                       # 发布时间
    expiry_at: Optional[str]                # 失效时间

    # 9.3 规范：意外程度
    surprise_bucket: str                    # SurpriseBucket 枚举值
    expectation_bucket: Optional[str]       # 文档口径：偏鹰/符合/偏鸽 或 利多/中性/利空
    expected_value: Optional[float]         # 市场预期值
    actual_value: Optional[float]           # 实际值
    surprise_score: float                   # 意外分数 (-1 到 1)

    # 9.3 规范：风险行动
    risk_action_proposal: str               # RiskActionProposal 枚举值
    confidence_level: float                 # 置信度 (0-1)
    position_impact: float                  # 仓位影响 (-1 到 1)

    # 内容
    title: str                              # 标题
    summary: str                            # 摘要
    content: str                            # 完整内容
    source_url: str                         # 来源 URL

    # 分析字段
    sentiment_score: float                  # 情感分数 (-1 到 1)
    credibility: str                        # 可信度 high/medium/low
    cross_market_map: str                   # 跨市场映射
    risk_flags: List[str]                   # 风险旗标
    community_base_score: float             # 社区强度基线 [0,1]
    decay_half_life_hours: int              # 衰减半衰期（小时）
    decay_factor: float                     # 时效衰减因子 [0,1]
    community_effective_score: float        # 社区有效强度 [0,1]
    narrative_status: str                   # active|cooling|archive

    # 元数据
    version: str                            # 契约版本
    market_trend_state: str = ""
    market_trend_ma20: float = 0.0
    market_trend_volatility_20d: float = 0.0
    market_trend_price_vs_ma: float = 0.0
    window_policy_asset_bucket: str = ""
    window_policy_market_state: str = ""

    def __post_init__(self):
        if self.risk_flags is None:
            self.risk_flags = []


class EventLedgerGenerator:
    """事件账本生成器 - V9.5"""

    def __init__(self, ledger_version: str = "9.5"):
        self.analyzer = TraditionalFinanceAnalyzer()
        self.event_counter = 0
        self.ledger_version = str(ledger_version or "9.5").strip() or "9.5"
        self._sentiment_pos_tokens = {
            "上涨", "拉升", "突破", "创新高", "获批", "增持", "买入", "净流入", "流入", "利好", "adoption",
            "approved", "inflow", "bullish", "surge", "partnership", "upgrade", "launch", "record high",
        }
        self._sentiment_neg_tokens = {
            "下跌", "暴跌", "回撤", "清算", "爆仓", "被盗", "黑客", "攻击", "漏洞", "监管调查", "处罚", "禁令", "流出",
            "净流出", "利空", "bearish", "hack", "exploit", "outflow", "sell-off", "lawsuit", "ban", "liquidation",
        }
        self._top_kol = {
            "vitalikbuterin": {"tier": "T0", "weight": 1.5},
            "a16zcrypto": {"tier": "T0", "weight": 1.4},
            "cz_binance": {"tier": "T0", "weight": 1.5},
            "czbinance": {"tier": "T0", "weight": 1.5},
        }
        self._onchain_flow_tokens = {
            "onchain",
            "链上",
            "资金",
            "flow",
            "etf",
            "whale",
            "交易所",
            "inflow",
            "outflow",
            "stablecoin",
            "持仓",
            "glassnode",
            "woonomic",
            "cryptoquant",
        }

    def generate_event_id(self) -> str:
        """生成事件 ID"""
        self.event_counter += 1
        now = datetime.now()
        prefix = "EVT"
        if self.ledger_version in {"9.7", "9.7_direct", "v97_direct"}:
            prefix = "EVT-V97"
        if self.ledger_version in {"9.8", "9.8_onchain", "v98_onchain"}:
            prefix = "EVT-V98"
        return f"{prefix}-{now.strftime('%Y%m%d%H%M%S')}-{self.event_counter:04d}"

    def _kol_profile(self, news_item: Dict) -> tuple[str | None, float]:
        if not isinstance(news_item, dict):
            return None, 1.0
        raw = [
            str(news_item.get("influencer") or ""),
            str(news_item.get("source") or ""),
            str(news_item.get("source_url") or ""),
            str(news_item.get("title") or ""),
        ]
        blob = " ".join([s for s in raw if s]).lower()
        for k, v in self._top_kol.items():
            if k in blob:
                return str(v.get("tier") or "T0"), float(v.get("weight") or 1.0)
        return None, 1.0

    def _estimate_sentiment_score(self, news_item: Dict) -> float:
        raw = news_item.get("sentiment_score")
        try:
            if raw is not None and str(raw).strip() != "":
                return max(-1.0, min(1.0, float(raw)))
        except Exception:
            pass
        text = " ".join([
            str(news_item.get("title") or ""),
            str(news_item.get("summary") or news_item.get("key_fact") or ""),
            str(news_item.get("content") or ""),
            str(news_item.get("risk_action_proposal") or ""),
            str(news_item.get("event_type") or news_item.get("category") or ""),
        ]).lower()
        if not text.strip():
            return 0.0
        pos = 0
        neg = 0
        for token in self._sentiment_pos_tokens:
            if token in text:
                pos += 1
        for token in self._sentiment_neg_tokens:
            if token in text:
                neg += 1
        if pos == 0 and neg == 0:
            return 0.0
        score = (pos - neg) / float(pos + neg)
        return max(-1.0, min(1.0, score))

    def _is_kol_event(self, item: Dict) -> bool:
        et = str(item.get("event_type") or item.get("category") or "").strip().lower()
        return et in {EventType.KOL_VIEW.value, "kol_view"}

    def _is_onchain_kol(self, item: Dict) -> bool:
        blob = " ".join(
            [
                str(item.get("title") or ""),
                str(item.get("summary") or ""),
                str(item.get("content") or ""),
                str(item.get("cross_market_map") or ""),
                str(item.get("source") or ""),
                str(item.get("influencer") or ""),
            ]
        ).lower()
        return any(tok in blob for tok in self._onchain_flow_tokens)

    def classify_event_type(self, category: str, topic: str = None, text: str = "") -> str:
        mapped = map_event_type(topic=topic, category=category, title=text, body="")
        allowed = {e.value for e in EventType}
        if mapped in allowed:
            return mapped
        return EventType.MARKET_ANALYSIS.value

    def classify_window(self, impact_horizon: str) -> str:
        """分类时间窗口 - 9.2 规范"""
        mapping = {
            "T0": Window.T0.value,
            "T1": Window.T1.value,
            "T2": Window.T2.value,
            "T3": Window.T3.value,
        }
        return mapping.get(impact_horizon, Window.T1.value)

    def classify_window_range(self, impact_horizon: str) -> str:
        mapping = {
            "T0": "[0,+4h]",
            "T1": "[-6h,+6h]",
            "T2": "[-24h,+24h]",
            "T3": "[-48h,+48h]",
        }
        return mapping.get(impact_horizon, "[-24h,+24h]")

    def classify_window_from_range(self, window_range: str) -> str:
        mapping = {
            "[0,+4h]": Window.T0.value,
            "[-6h,+6h]": Window.T1.value,
            "[-24h,+24h]": Window.T2.value,
            "[-48h,+48h]": Window.T3.value,
        }
        return mapping.get(str(window_range or "").strip(), Window.T1.value)

    def classify_expectation_bucket(
        self,
        event_type: str,
        sentiment_score: float,
        expected_value: Optional[float] = None,
        actual_value: Optional[float] = None,
        surprise: Optional[float] = None,
    ) -> Optional[str]:
        if surprise is None and expected_value is not None and actual_value is not None:
            try:
                surprise = float(actual_value) - float(expected_value)
            except Exception:
                surprise = None
        if surprise is None:
            return "unknown"
        if event_type in {EventType.MONETARY_POLICY.value, EventType.US_DATA.value}:
            if surprise > 0:
                return "偏鹰"
            if surprise < 0:
                return "偏鸽"
            return "符合"
        if event_type in {EventType.GEOPOLITICS.value, EventType.CRYPTO_REGULATION.value, EventType.MARKET_ANALYSIS.value}:
            if surprise > 0:
                return "利多"
            if surprise < 0:
                return "利空"
            return "中性"
        return "unknown"

    def calculate_surprise_bucket(self, sentiment_score: float, risk_flags: List[str]) -> tuple:
        """
        计算意外程度分级 - 9.3 规范

        返回：(surprise_bucket, surprise_score)
        """
        abs_score = abs(sentiment_score)
        flag_penalty = len(risk_flags) * 0.1

        # 计算意外分数
        surprise_score = abs_score * (1 + flag_penalty)
        surprise_score = max(-1, min(1, surprise_score))

        # 分级
        if abs_score >= 0.8:
            bucket = SurpriseBucket.MAJOR_SURPRISE.value
        elif abs_score >= 0.6:
            bucket = SurpriseBucket.MODERATE_SURPRISE.value
        elif abs_score >= 0.4:
            bucket = SurpriseBucket.MILD_SURPRISE.value
        elif abs_score >= 0.2:
            bucket = SurpriseBucket.EXPECTED.value
        else:
            bucket = SurpriseBucket.EXPECTED.value

        return bucket, surprise_score

    def propose_risk_action(self, sentiment_score: float, confidence: str,
                            surprise_bucket: str, event_type: str, window_range: str) -> str:
        """
        提出风险行动建议 - 9.3 规范
        """
        # 基础置信度
        conf_map = {"high": 0.9, "medium": 0.6, "low": 0.3}
        conf = conf_map.get(confidence, 0.5)

        high_grade = is_high_grade_event(event_type=event_type, event_window_range=window_range)
        if high_grade:
            if sentiment_score < -0.6:
                return RiskActionProposal.STOP_LOSS.value
            if sentiment_score < -0.2:
                return RiskActionProposal.REDUCE.value
            if surprise_bucket == SurpriseBucket.MAJOR_SURPRISE.value:
                return RiskActionProposal.HEDGE.value
            return RiskActionProposal.HOLD.value

        if sentiment_score < -0.5 and conf > 0.7:
            if sentiment_score < -0.8:
                return RiskActionProposal.STOP_LOSS.value
            return RiskActionProposal.REDUCE.value

        # 正面 + 高可信度 → 加仓
        if sentiment_score > 0.5 and conf > 0.7:
            return RiskActionProposal.INCREASE.value

        # 重大意外 → 对冲
        if surprise_bucket == SurpriseBucket.MAJOR_SURPRISE.value:
            return RiskActionProposal.HEDGE.value

        # 默认持有
        return RiskActionProposal.HOLD.value

    def create_ledger_entry(self, news_item: Dict) -> EventLedgerEntry:
        """创建事件账本条目"""
        category = news_item.get("category", "")
        topic = news_item.get("topic", "")
        text = f"{news_item.get('title', '')} {news_item.get('summary', news_item.get('key_fact', ''))}"

        # 9.1: 事件类型
        event_type = self.classify_event_type(category, topic, text)

        # 9.2: 时间窗口（优先使用上游动态窗口回灌结果）
        dynamic_window_range = str(news_item.get("event_window_range") or "").strip()
        if dynamic_window_range:
            window_range = dynamic_window_range
            window = self.classify_window_from_range(window_range)
        else:
            window = self.classify_window(news_item.get("impact_horizon", "T1"))
            window_range = self.classify_window_range(news_item.get("impact_horizon", "T1"))

        # 9.3: 意外程度
        sentiment = self._estimate_sentiment_score(news_item)
        risk_flags = news_item.get("risk_flags", [])
        surprise_bucket, surprise_score = self.calculate_surprise_bucket(sentiment, risk_flags)

        # 9.3: 风险行动
        confidence = news_item.get("source_confidence", "medium")
        risk_action = self.propose_risk_action(sentiment, confidence, surprise_bucket, event_type, window_range)
        if not bool(news_item.get("dynamic_window_gate_open", True)):
            risk_action = RiskActionProposal.HOLD.value

        # 计算置信度
        conf_map = {"high": 0.9, "medium": 0.6, "low": 0.3}
        confidence_level = conf_map.get(confidence, 0.5)
        kol_tier, kol_weight = self._kol_profile(news_item)
        if self.ledger_version in {"9.7", "9.7_direct", "v97_direct"}:
            if event_type == EventType.KOL_VIEW.value:
                if kol_tier:
                    confidence_level = max(confidence_level, 0.85)
                    confidence_level = min(0.95, confidence_level * kol_weight)
                else:
                    risk_action = RiskActionProposal.HOLD.value
                    confidence_level = max(0.3, confidence_level * 0.6)
        expectation_bucket = news_item.get("expectation_bucket")
        if not expectation_bucket:
            expectation_bucket = self.classify_expectation_bucket(
                event_type,
                sentiment,
                news_item.get("expected_value"),
                news_item.get("actual_value"),
                news_item.get("surprise"),
            )
        if expectation_bucket == "unknown":
            confidence_level = max(0.3, confidence_level * 0.7)

        # 计算仓位影响
        position_impact = sentiment * confidence_level
        attention_type = str(news_item.get("attention_type") or "event")
        if attention_type == "market_microstructure":
            default_half_life = 6
        elif attention_type in {"event", "policy", "security"}:
            default_half_life = 24
        else:
            default_half_life = 72
        try:
            community_base_score = float(news_item.get("community_base_score", 0.0) or 0.0)
        except Exception:
            community_base_score = 0.0
        community_base_score = max(0.0, min(1.0, community_base_score))
        if self.ledger_version in {"9.7", "9.7_direct", "v97_direct"} and event_type == EventType.KOL_VIEW.value:
            if kol_tier:
                community_base_score = max(community_base_score, 0.18)
            else:
                community_base_score = min(community_base_score, 0.12)
        try:
            decay_half_life_hours = int(news_item.get("decay_half_life_hours", default_half_life) or default_half_life)
        except Exception:
            decay_half_life_hours = default_half_life
        decay_half_life_hours = max(1, decay_half_life_hours)
        try:
            decay_factor = float(news_item.get("decay_factor", 1.0) or 1.0)
        except Exception:
            decay_factor = 1.0
        decay_factor = max(0.0, min(1.0, decay_factor))
        try:
            community_effective_score = float(news_item.get("community_effective_score", 0.0) or 0.0)
        except Exception:
            community_effective_score = 0.0
        if community_effective_score <= 0.0:
            community_effective_score = community_base_score * decay_factor * confidence_level
        community_effective_score = max(0.0, min(1.0, community_effective_score))
        narrative_status = str(news_item.get("narrative_status") or "").strip()
        if narrative_status not in {"active", "cooling", "archive"}:
            if community_effective_score >= 0.5:
                narrative_status = "active"
            elif community_effective_score >= 0.2:
                narrative_status = "cooling"
            else:
                narrative_status = "archive"

        # 设置失效时间
        published_at = news_item.get("published_at", datetime.now().isoformat())
        pub_dt = datetime.fromisoformat(published_at)

        if window == "T0":
            expiry_dt = pub_dt + timedelta(days=1)
        elif window == "T1":
            expiry_dt = pub_dt + timedelta(days=7)
        elif window == "T2":
            expiry_dt = pub_dt + timedelta(weeks=4)
        else:
            expiry_dt = pub_dt + timedelta(weeks=12)

        entry = EventLedgerEntry(
            event_id=self.generate_event_id(),
            timestamp=datetime.now().isoformat(),
            source=news_item.get("source", "Odaily" if category else "华尔街见闻"),
            event_type=event_type,
            window=window,
            window_range=window_range,
            published_at=published_at,
            expiry_at=expiry_dt.isoformat(),
            surprise_bucket=surprise_bucket,
            expectation_bucket=expectation_bucket,
            expected_value=news_item.get("expected_value"),
            actual_value=news_item.get("actual_value"),
            surprise_score=surprise_score,
            risk_action_proposal=risk_action,
            confidence_level=confidence_level,
            position_impact=position_impact,
            title=news_item.get("title", ""),
            summary=news_item.get("summary", news_item.get("key_fact", "")),
            content=news_item.get("summary", ""),
            source_url=news_item.get("source_url", ""),
            sentiment_score=sentiment,
            credibility=confidence,
            cross_market_map=news_item.get("cross_market_map", ""),
            risk_flags=risk_flags,
            community_base_score=community_base_score,
            decay_half_life_hours=decay_half_life_hours,
            decay_factor=decay_factor,
            community_effective_score=community_effective_score,
            narrative_status=narrative_status,
            version=self.ledger_version,
            market_trend_state=str(news_item.get("market_trend_state") or ""),
            market_trend_ma20=float(news_item.get("market_trend_ma20") or 0.0),
            market_trend_volatility_20d=float(news_item.get("market_trend_volatility_20d") or 0.0),
            market_trend_price_vs_ma=float(news_item.get("market_trend_price_vs_ma") or 0.0),
            window_policy_asset_bucket=str(news_item.get("window_policy_asset_bucket") or ""),
            window_policy_market_state=str(news_item.get("window_policy_market_state") or ""),
        )

        return entry

    def generate_ledger(self, news_list: List[Dict]) -> List[EventLedgerEntry]:
        """生成完整事件账本"""
        self.event_counter = 0
        entries = []
        if self.ledger_version in {"9.7", "9.7_direct", "v97_direct", "9.8", "9.8_onchain", "v98_onchain"}:
            selected: list[dict] = []
            per_day_kol: dict[str, dict] = {}
            for item in news_list:
                if not isinstance(item, dict):
                    continue
                if not self._is_kol_event(item):
                    selected.append(item)
                    continue
                if self.ledger_version in {"9.8", "9.8_onchain", "v98_onchain"} and not self._is_onchain_kol(item):
                    continue
                pub = str(item.get("published_at") or item.get("fetched_at") or "").strip()
                day_key = pub[:10] if len(pub) >= 10 else ""
                tier, weight = self._kol_profile(item)
                if not day_key:
                    if tier:
                        selected.append(item)
                    continue
                if not tier:
                    continue
                try:
                    sentiment = float(self._estimate_sentiment_score(item) or 0.0)
                except Exception:
                    sentiment = 0.0
                try:
                    conf = {"high": 0.9, "medium": 0.6, "low": 0.3}.get(str(item.get("source_confidence") or "medium"), 0.6)
                except Exception:
                    conf = 0.6
                score = abs(sentiment) * conf * weight
                prev = per_day_kol.get(day_key)
                if not prev:
                    per_day_kol[day_key] = {"item": item, "score": score}
                elif score > float(prev.get("score") or 0.0):
                    per_day_kol[day_key] = {"item": item, "score": score}
            for row in per_day_kol.values():
                it = row.get("item")
                if isinstance(it, dict):
                    selected.append(it)
            selected.sort(key=lambda x: str((x or {}).get("published_at") or (x or {}).get("fetched_at") or ""))
            news_list = selected

        for news in news_list:
            entry = self.create_ledger_entry(news)
            entries.append(entry)

        return entries

    def to_jsonl(self, entries: List[EventLedgerEntry]) -> str:
        """转换为 JSONL 格式"""
        lines = []
        for entry in entries:
            data = asdict(entry)
            lines.append(json.dumps(data, ensure_ascii=False))
        return "\n".join(lines)

    def save_jsonl(self, entries: List[EventLedgerEntry], output_path: Path):
        """保存 JSONL 文件"""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(self.to_jsonl(entries))

        print(f"[✓] 事件账本已保存：{output_path}")


def generate_mock_news_for_ledger(hours: int = 24) -> List[Dict]:
    """生成模拟新闻数据用于测试"""
    now = datetime.now()

    news = [
        {
            "title": "比特币 ETF 单日净流入超 5 亿美元，创 3 个月新高",
            "category": "onchain_data",
            "source": "Odaily",
            "source_url": "https://www.odaily.news/newsflash/123456",
            "published_at": (now - timedelta(hours=2)).isoformat(),
            "summary": "贝莱德 IBIT 单日流入 3.2 亿美元，总资产管理规模突破 500 亿",
            "source_confidence": "high",
            "impact_horizon": "T0",
            "sentiment_score": 0.8,
            "cross_market_map": "ETF 流入→BTC 需求↑→价格上涨",
            "risk_flags": []
        },
        {
            "title": "美联储 12 月会议纪要：官员们对通胀进展感到担忧",
            "topic": "fed",
            "source": "华尔街见闻",
            "source_url": "https://wallstreetcn.com/articles/3766940",
            "published_at": (now - timedelta(hours=1)).isoformat(),
            "key_fact": "多数官员认为 12 月降息合适，但对 2026 年利率路径存在分歧",
            "source_confidence": "high",
            "impact_horizon": "T0",
            "sentiment_score": -0.7,
            "cross_market_map": "鹰派纪要→美债收益率↑→风险资产承压",
            "risk_flags": []
        },
        {
            "title": "某分析师称山寨季将在 2 周内到来",
            "category": "kols_view",
            "source": "Odaily",
            "source_url": "https://twitter.com/analyst/status/123456",
            "published_at": (now - timedelta(hours=6)).isoformat(),
            "summary": "基于历史周期和当前市值占比，认为山寨季即将启动",
            "source_confidence": "low",
            "impact_horizon": "T2",
            "sentiment_score": 0.3,
            "cross_market_map": "山寨季预期→资金从 BTC 流出→小市值币种波动加大",
            "risk_flags": ["单源爆料", "无数据支撑"]
        },
        {
            "title": "中东局势升级：伊朗威胁封锁霍尔木兹海峡",
            "topic": "geopolitics",
            "source": "华尔街见闻",
            "source_url": "https://wallstreetcn.com/articles/3766942",
            "published_at": (now - timedelta(hours=8)).isoformat(),
            "key_fact": "该地区承担全球 20% 石油运输",
            "source_confidence": "medium",
            "impact_horizon": "T1",
            "sentiment_score": -0.5,
            "cross_market_map": "地缘风险→原油↑→通胀预期↑→VIX↑",
            "risk_flags": ["标题与正文不一致"]
        },
        {
            "title": "以太坊链上稳定币结算量首次超越比特币",
            "category": "onchain_data",
            "source": "Odaily",
            "source_url": "https://www.odaily.news/newsflash/123457",
            "published_at": (now - timedelta(hours=4)).isoformat(),
            "summary": "USDT + USDC 在以太坊的日结算量达 120 亿美元，BTC 链上为 85 亿",
            "source_confidence": "high",
            "impact_horizon": "T1",
            "sentiment_score": 0.5,
            "cross_market_map": "以太坊生态活跃→ETH/BTC 走强",
            "risk_flags": []
        }
    ]

    return news[:max(1, int(len(news) * hours / 24))]


def main():
    """主函数 - 生成事件账本 JSONL"""
    import argparse

    parser = argparse.ArgumentParser(description='生成事件账本 JSONL (V9.3)')
    parser.add_argument('--hours', '-H', type=int, default=24, help='时间窗口 (小时)')
    parser.add_argument('--output', '-o', type=str, default=None, help='输出文件名')
    parser.add_argument('--demo', action='store_true', help='使用演示数据')
    args = parser.parse_args()

    print("=" * 60)
    print("  事件账本生成器 (V9.3 - JSONL 格式)")
    print("=" * 60)
    print(f"\n时间窗口：最近 {args.hours} 小时")

    # 创建生成器
    generator = EventLedgerGenerator()

    # 生成/获取新闻数据
    if args.demo:
        news_list = generate_mock_news_for_ledger(args.hours)
    else:
        # 从现有简报系统获取
        news_list = generate_mock_news_for_ledger(args.hours)

    print(f"输入新闻数：{len(news_list)}")

    # 生成事件账本
    entries = generator.generate_ledger(news_list)

    # 确定输出路径
    output_dir = Path(__file__).parent.parent / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.output:
        output_path = output_dir / args.output
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        output_path = output_dir / f"event_ledger_{ts}.jsonl"

    # 保存 JSONL
    generator.save_jsonl(entries, output_path)

    # 打印摘要
    print(f"\n【事件账本摘要】")

    # 按事件类型统计
    by_type = {}
    for e in entries:
        t = e.event_type
        by_type[t] = by_type.get(t, 0) + 1

    print("\n按事件类型:")
    for t, c in sorted(by_type.items()):
        print(f"  {t}: {c} 条")

    # 按时间窗口统计
    by_window = {}
    for e in entries:
        w = e.window
        by_window[w] = by_window.get(w, 0) + 1

    print("\n按时间窗口:")
    for w, c in sorted(by_window.items()):
        print(f"  {w}: {c} 条")

    # 按意外程度统计
    by_surprise = {}
    for e in entries:
        s = e.surprise_bucket
        by_surprise[s] = by_surprise.get(s, 0) + 1

    print("\n按意外程度:")
    for s, c in sorted(by_surprise.items()):
        print(f"  {s}: {c} 条")

    # 按风险行动统计
    by_action = {}
    for e in entries:
        a = e.risk_action_proposal
        by_action[a] = by_action.get(a, 0) + 1

    print("\n按风险行动:")
    for a, c in sorted(by_action.items()):
        print(f"  {a}: {c} 条")

    # 打印示例条目
    if entries:
        print(f"\n【示例条目】")
        sample = asdict(entries[0])
        print(json.dumps(sample, indent=2, ensure_ascii=False)[:1000] + "...")

    return entries


if __name__ == "__main__":
    main()
