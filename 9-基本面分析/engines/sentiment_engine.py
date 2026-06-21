"""
情绪分析引擎
基于关键词正则匹配进行情绪分析
"""

import re
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone


# 正面关键词
POSITIVE_KEYWORDS = [
    "bullish", "rally", "surge", "approval", "inflow", "positive", "adoption",
    "上涨", "利好", "突破", "机构", "流入", "买入", "看涨", "做多",
    "approval", "ETF", "批准", "通过", "吸筹", "增持", "创新高"
]

# 负面关键词
NEGATIVE_KEYWORDS = [
    "bearish", "crash", "selloff", "ban", "hack", "fraud", "liquidation", "outflow",
    "reject", "negative", "下跌", "利空", "暴跌", "监管", "清算", "卖出",
    "看跌", "做空", "爆仓", "减持", "创新低", "被禁", "风险", "抛售"
]

# 分类关键词映射
CATEGORY_KEYWORDS = {
    "监管政策": ["SEC", "CFTC", "FED", "美联储", "监管", "政策", "法案", "条例", "批准", "禁令", "ETF批准", "ETF通过"],
    "项目动态": ["发布", "更新", "升级", "合并", "分叉", "空投", "上线", "下架", "合作", " partnership"],
    "市场数据": ["流入", "流出", "交易量", "持仓", "爆仓", "杠杆", "资金费率", "多空比", "MVRV", "SOPR"],
    "社区热话": ["病毒式传播", "热点", "FOMO", "社区", "推特", "讨论", "关注", "热度", "meme"]
}


class SentimentEngine:
    """情绪分析引擎"""
    
    def __init__(self):
        self.positive_pattern = self._build_pattern(POSITIVE_KEYWORDS)
        self.negative_pattern = self._build_pattern(NEGATIVE_KEYWORDS)
        self.category_patterns = {cat: self._build_pattern(kws) 
                                   for cat, kws in CATEGORY_KEYWORDS.items()}
    
    def _build_pattern(self, keywords: List[str]) -> re.Pattern:
        """构建正则表达式模式"""
        escaped = [re.escape(kw) for kw in keywords]
        pattern = "|".join(escaped)
        return re.compile(pattern, re.IGNORECASE)
    
    def analyze_text(self, text: str) -> Dict[str, Any]:
        """
        分析单条文本的情绪
        
        Args:
            text: 待分析的文本
        
        Returns:
            包含 score, sentiment, categories 的字典
        """
        if not text:
            return {"score": 0, "sentiment": "neutral", "categories": [], "matches": []}
        
        positive_matches = self.positive_pattern.findall(text)
        negative_matches = self.negative_pattern.findall(text)
        
        pos_count = len(positive_matches)
        neg_count = len(negative_matches)
        total = pos_count + neg_count
        
        if total == 0:
            score = 0
            sentiment_label = "neutral"
        else:
            score = (pos_count - neg_count) / total
            if score > 0.2:
                sentiment_label = "positive"
            elif score < -0.2:
                sentiment_label = "negative"
            else:
                sentiment_label = "neutral"
        
        # 检测分类
        categories = []
        for cat, pattern in self.category_patterns.items():
            if pattern.search(text):
                categories.append(cat)
        
        return {
            "score": round(score, 4),
            "sentiment": sentiment_label,
            "categories": categories,
            "matches": {
                "positive": pos_count,
                "negative": neg_count
            }
        }
    
    def analyze_batch(self, texts: List[str]) -> Dict[str, Any]:
        """
        批量分析文本
        
        Args:
            texts: 文本列表
        
        Returns:
            汇总的情绪分析结果
        """
        if not texts:
            return {
                "score": 0,
                "sentiment": "neutral",
                "count": 0,
                "positive_count": 0,
                "negative_count": 0,
                "category_distribution": {}
            }
        
        results = [self.analyze_text(t) for t in texts]
        
        total_score = sum(r["score"] for r in results)
        avg_score = total_score / len(results)
        
        pos_count = sum(1 for r in results if r["sentiment"] == "positive")
        neg_count = sum(1 for r in results if r["sentiment"] == "negative")
        
        # 分类统计
        cat_dist = {}
        for r in results:
            for cat in r["categories"]:
                cat_dist[cat] = cat_dist.get(cat, 0) + 1
        
        if avg_score > 0.2:
            sentiment = "positive"
        elif avg_score < -0.2:
            sentiment = "negative"
        else:
            sentiment = "neutral"
        
        # 转换为0-100的情绪指数
        sentiment_index = int((avg_score + 1) * 50)
        
        return {
            "score": round(avg_score, 4),
            "sentiment": sentiment,
            "sentiment_index": sentiment_index,
            "count": len(texts),
            "positive_count": pos_count,
            "negative_count": neg_count,
            "category_distribution": cat_dist
        }
    
    def get_fear_greed_estimate(self, sentiment_index: int) -> str:
        """
        根据情绪指数估算恐惧/贪婪值
        
        Args:
            sentiment_index: 情绪指数 (0-100)
        
        Returns:
            恐惧/贪婪等级描述
        """
        if sentiment_index >= 75:
            return "extreme_greed"
        elif sentiment_index >= 60:
            return "greed"
        elif sentiment_index >= 40:
            return "neutral"
        elif sentiment_index >= 25:
            return "fear"
        else:
            return "extreme_fear"


def create_sentiment_engine() -> SentimentEngine:
    """创建情绪分析引擎实例"""
    return SentimentEngine()
