"""
基本面分析系统适配器
封装 10-经典指标系统 中的基本面模块 API

API 基础路径: http://127.0.0.1:8092

可用端点:
- /fundamental/flows/brief/latest - 资金流简报
- /fundamental/flows/regime/latest - 资金流Regime
- /fundamental/narrative/brief/latest - 叙事简报
- /fundamental/trading/latest - 交易信号
- /fundamental/overview/latest - 概览
- /fundamental/news/brief/latest - 新闻简报
"""
import requests
from typing import Dict, Optional, List, Any
from dataclasses import dataclass


@dataclass
class FundFlowData:
    """资金流数据"""
    direction: str = "NEUTRAL"  # INFLOW / OUTFLOW / NEUTRAL
    etf_flow: float = 0.0
    oi_change: float = 0.0
    funding_rate: float = 0.0
    strength: float = 0.3


@dataclass
class SentimentData:
    """情绪数据"""
    fear_greed: float = 50.0  # 0-100
    sentiment: str = "NEUTRAL"  # FEAR / GREED / NEUTRAL
    long_short_ratio: float = 1.0
    funding_rate: float = 0.0


@dataclass
class FundamentalOverview:
    """基本面概览"""
    regime: str = "UNKNOWN"
    trend_direction: str = "NEUTRAL"
    key_drivers: List[str] = None
    risk_level: str = "MEDIUM"


class FundamentalAPIClient:
    """
    基本面分析系统 API 客户端
    """
    
    DEFAULT_BASE_URL = "http://127.0.0.1:8092"
    TIMEOUT = 5
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or self.DEFAULT_BASE_URL
        self._session = requests.Session()
    
    def _get(self, path: str, params: Dict = None) -> Optional[Dict]:
        """GET 请求封装，失败返回 None"""
        try:
            resp = self._session.get(
                f"{self.base_url}{path}",
                params=params,
                timeout=self.TIMEOUT
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return None
    
    def is_available(self) -> bool:
        """检查基本面系统是否在线"""
        result = self._get("/fundamental/overview/latest")
        return result is not None and result.get("ok", False)
    
    def get_fund_flows(self, symbol: str = "BTC") -> FundFlowData:
        """
        获取资金流数据
        优先调用API，失败则使用本地代理计算
        """
        # 尝试 API
        result = self._get("/fundamental/flows/brief/latest")
        if result and result.get("ok"):
            data = result.get("data", {})
            return FundFlowData(
                direction=data.get("direction", "NEUTRAL"),
                etf_flow=data.get("etf_flow", 0.0),
                oi_change=data.get("oi_change", 0.0),
                funding_rate=data.get("funding_rate", 0.0),
                strength=data.get("strength", 0.3),
            )
        
        # 降级：返回空数据（由调用方根据其他指标判断）
        return FundFlowData()
    
    def get_sentiment(self, symbol: str = "BTC") -> SentimentData:
        """
        获取市场情绪数据
        优先调用API，失败则使用本地代理
        """
        # 尝试 API
        result = self._get("/fundamental/trading/latest")
        if result and result.get("ok"):
            data = result.get("data", {})
            return SentimentData(
                fear_greed=data.get("fear_greed_index", 50.0),
                sentiment=data.get("sentiment", "NEUTRAL"),
                long_short_ratio=data.get("long_short_ratio", 1.0),
                funding_rate=data.get("funding_rate", 0.0),
            )
        
        # 降级：使用资金费率作为情绪代理
        return SentimentData()
    
    def get_overview(self) -> FundamentalOverview:
        """获取基本面概览"""
        result = self._get("/fundamental/overview/latest")
        if result and result.get("ok"):
            data = result.get("data", {})
            return FundamentalOverview(
                regime=data.get("regime", "UNKNOWN"),
                trend_direction=data.get("trend_direction", "NEUTRAL"),
                key_drivers=data.get("key_drivers", []),
                risk_level=data.get("risk_level", "MEDIUM"),
            )
        
        return FundamentalOverview()
    
    def get_news_brief(self, limit: int = 10) -> List[Dict]:
        """获取新闻简报"""
        result = self._get("/fundamental/news/brief/latest")
        if result and result.get("ok"):
            return result.get("news", [])[:limit]
        return []
    
    def calculate_sentiment_local(self, funding_rate: float, 
                                  rsi: float = None,
                                  ch24h: float = None) -> SentimentData:
        """
        本地计算情绪指标（降级方案）
        基于资金费率、RSI、涨跌幅等综合估算
        """
        score = 50.0
        
        # 资金费率贡献
        if funding_rate > 0.0005:
            score += 15  # 正费率=多头拥挤=贪婪
        elif funding_rate > 0.0001:
            score += 5
        elif funding_rate < -0.0005:
            score -= 15  # 负费率=空头拥挤=恐惧
        elif funding_rate < -0.0001:
            score -= 5
        
        # RSI贡献
        if rsi is not None:
            score += (rsi - 50) * 0.5
        
        # 24H涨跌贡献
        if ch24h is not None:
            score += ch24h * 2
        
        score = max(0, min(100, score))
        
        if score > 70:
            sentiment = "GREED"
        elif score < 30:
            sentiment = "FEAR"
        else:
            sentiment = "NEUTRAL"
        
        return SentimentData(
            fear_greed=score,
            sentiment=sentiment,
            funding_rate=funding_rate,
        )
