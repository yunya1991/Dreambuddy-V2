"""
经典指标系统适配器
封装 10-经典指标系统/ml_trade_service.py 的 REST API

API 基础路径: http://127.0.0.1:8092
"""
import requests
from typing import Dict, Optional, List, Any
from dataclasses import dataclass


@dataclass
class TechnicalIndicators:
    """技术指标数据结构"""
    rsi: float = 50.0
    macd: Dict[str, float] = None
    ema: Dict[str, float] = None
    atr: float = 0.0
    bollinger: Dict[str, float] = None
    volume_ratio: float = 1.0
    trend_direction: str = "NEUTRAL"
    trend_strength: float = 0.0


class ClassicIndicatorsClient:
    """
    经典指标系统 API 客户端
    
    可用端点:
    - /api/v1/ml3/indicator - 系统状态
    - /strategy/registry - 策略注册表
    - /strategy/backtest - 回测
    - /signals/v1 - 信号生成
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
        """检查经典指标系统是否在线"""
        result = self._get("/api/v1/ml3/indicator")
        return result is not None and result.get("ok", False)
    
    def get_strategy_registry(self) -> List[Dict]:
        """获取策略注册表"""
        result = self._get("/strategy/registry")
        if result and result.get("ok"):
            return result.get("strategies", [])
        return []
    
    def calculate_indicators_local(self, closes: List[float], 
                                   highs: List[float] = None,
                                   lows: List[float] = None,
                                   volumes: List[float] = None) -> TechnicalIndicators:
        """
        本地计算技术指标（降级方案）
        当经典指标系统不可用时，使用本地实现
        """
        if not closes or len(closes) < 2:
            return TechnicalIndicators()
        
        # RSI
        rsi = self._calc_rsi(closes)
        
        # EMA
        ema20 = self._calc_ema(closes, 20)
        ema50 = self._calc_ema(closes, 50)
        ema200 = self._calc_ema(closes, 200) if len(closes) >= 200 else closes[-1]
        
        # ATR
        atr = self._calc_atr(highs, lows, closes) if highs and lows else 0
        
        # 量比
        vol_ratio = 1.0
        if volumes and len(volumes) >= 20:
            avg_vol = sum(volumes[-20:]) / 20
            if avg_vol > 0:
                vol_ratio = volumes[-1] / avg_vol
        
        # 趋势判断
        if closes[-1] > ema20 > ema50:
            trend = "UP"
            strength = min(abs(ema20 - ema50) / ema50 * 100, 1.0)
        elif closes[-1] < ema20 < ema50:
            trend = "DOWN"
            strength = min(abs(ema20 - ema50) / ema50 * 100, 1.0)
        else:
            trend = "NEUTRAL"
            strength = 0.3
        
        return TechnicalIndicators(
            rsi=rsi,
            ema={"ema20": ema20, "ema50": ema50, "ema200": ema200},
            atr=atr,
            volume_ratio=vol_ratio,
            trend_direction=trend,
            trend_strength=strength,
        )
    
    def _calc_rsi(self, prices: List[float], period: int = 14) -> float:
        """计算 RSI"""
        if len(prices) < period + 1:
            return 50.0
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [max(d, 0) for d in deltas[-period:]]
        losses = [max(-d, 0) for d in deltas[-period:]]
        avg_g = sum(gains) / period
        avg_l = sum(losses) / period
        if avg_l == 0:
            return 100.0
        rs = avg_g / avg_l
        return 100 - 100 / (1 + rs)
    
    def _calc_ema(self, prices: List[float], period: int) -> float:
        """计算 EMA"""
        if len(prices) < period:
            return prices[-1] if prices else 0
        k = 2 / (period + 1)
        e = prices[-period]
        for p in prices[-period+1:]:
            e = p * k + e * (1 - k)
        return e
    
    def _calc_atr(self, highs: List[float], lows: List[float], 
                  closes: List[float], period: int = 14) -> float:
        """计算 ATR"""
        if len(closes) < 2 or not highs or not lows:
            return 0
        trs = []
        for i in range(1, min(period + 1, len(closes))):
            h = highs[i] if i < len(highs) else closes[i]
            l = lows[i] if i < len(lows) else closes[i]
            c_prev = closes[i-1]
            trs.append(max(h - l, abs(h - c_prev), abs(l - c_prev)))
        return sum(trs) / len(trs) if trs else 0
