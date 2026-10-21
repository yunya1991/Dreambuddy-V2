# -*- coding: utf-8 -*-
"""快讯语义采集器 — S 层 news_event 意图训练数据源 (39 SPEC v1.1 §9.2 P-快讯)。

从 18-数据获取中心的星球日报快讯（newsflash 记录）生成训练样本：
  1. 事件类型识别样本：快讯正文 → od_event_type 分类（天然标签，零标注成本）
  2. 实体关联样本：快讯正文 → tickers_hit 代币关联
  3. 情绪标签维度（§12.3 初期规则标注）：正文关键词 → 正/负/中性三分类

FAIL-OPEN: 数据库缺失/解析失败返回空列表，不阻塞训练。
"""
import json
import os
import re
import sys
from typing import List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase

# 18 中心已迁移 PostgreSQL，复用 39 模块统一 PG 辅助模块（FAIL-OPEN）
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "39-金融语义蒸馏系统", "scripts"))
import dc_pg

# 情绪关键词词典（§12.3 初期规则标注口径）
_POSITIVE_WORDS = ["上涨", "突破", "新高", "利好", "增持", "批准", "通过", "合作", "融资", "上涨", "暴涨", "利好"]
_NEGATIVE_WORDS = ["下跌", "暴跌", "新低", "利空", "减持", "制裁", "禁止", "警告", "诉讼", "黑客", "被盗", "清算", "崩盘", "风险"]

_EVENT_TYPE_DESC = {
    "monetary_policy": "货币政策", "crypto_regulation": "加密监管",
    "us_policy": "美国政策", "us_data": "美国经济数据",
    "geopolitics": "地缘政治", "market": "行情动态", "project": "项目动态",
}


def _sentiment_of(text: str) -> str:
    """规则+关键词词典情绪三分类（正/负/中性）。"""
    pos = sum(1 for w in _POSITIVE_WORDS if w in text)
    neg = sum(1 for w in _NEGATIVE_WORDS if w in text)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


class NewsflashSemanticCollector(TrainingDataProvider):
    """从 18 中心快讯数据生成 news_event 意图训练样本。"""

    def get_source_name(self) -> str:
        return "newsflash_semantic"

    def get_quality_threshold(self) -> str:
        return "B"

    def fetch_cases(self, limit: int = 100, since: Optional[str] = None) -> List[TrainingCase]:
        # PostgreSQL 查询（dc_pg 统一接口，FAIL-OPEN：异常返回空）
        rows = dc_pg.fetch_records("newsflash_%", limit=max(limit * 2, 200), order_desc=True)

        cases: List[TrainingCase] = []
        seen_hash = set()
        for row in rows:
            if len(cases) >= limit:
                break
            ts = row.get("timestamp", "") or ""
            m = row.get("metrics") or {}
            if isinstance(m, str):
                try:
                    m = json.loads(m)
                except Exception:
                    continue
            if not isinstance(m, dict):
                continue
            desc = re.sub(r"<[^>]+>", "", m.get("description", "")).strip()
            event_type = m.get("od_event_type", "")
            tickers = m.get("tickers_hit", "")
            title_hash = m.get("od_title_hash", "")
            if not desc or not event_type or title_hash in seen_hash:
                continue
            seen_hash.add(title_hash)
            # 解析 tickers（PG jsonb 可能已是 list）
            if isinstance(tickers, list):
                tickers_list = tickers
            else:
                try:
                    tickers_list = json.loads(tickers) if tickers else []
                except Exception:
                    tickers_list = []
            sentiment = _sentiment_of(desc)
            type_desc = _EVENT_TYPE_DESC.get(event_type, event_type)
            excerpt = desc[:120]
            cases.append(TrainingCase(
                intent="news_event",
                actions=[f"event_type:{event_type}", f"sentiment:{sentiment}"] +
                        [f"ticker:{t}" for t in tickers_list[:3]],
                outcome_text=f"这条快讯属于什么事件类型：{excerpt}",
                learned=[f"快讯事件 | {type_desc} | 情绪:{sentiment} | 关联代币:{','.join(tickers_list[:3]) or '无'}"],
                layer_tags=["S"],
                quality="B",
                confidence=0.7,
                source="newsflash_semantic",
                metadata={
                    "event_type": event_type,
                    "sentiment": sentiment,
                    "tickers": tickers_list[:5],
                    "published_at": ts,
                    "engine_hint": "18-数据获取中心/odaily_newsflash",
                },
            ))
        return cases[:limit]
