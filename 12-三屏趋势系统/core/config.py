"""三屏趋势系统 — 配置常量"""

from typing import List, Dict

CANDIDATE_COINS: List[Dict] = [
    # 主流币
    {"symbol": "BTC", "spot": "BTC-USDT", "swap": "BTC-USDT-SWAP", "is_btc": True},
    {"symbol": "ETH", "spot": "ETH-USDT", "swap": "ETH-USDT-SWAP", "is_btc": False},
    {"symbol": "SOL", "spot": "SOL-USDT", "swap": "SOL-USDT-SWAP", "is_btc": False},
    {"symbol": "BNB", "spot": "BNB-USDT", "swap": "BNB-USDT-SWAP", "is_btc": False},
    {"symbol": "XRP", "spot": "XRP-USDT", "swap": "XRP-USDT-SWAP", "is_btc": False},
    # 高市值山寨
    {"symbol": "DOGE", "spot": "DOGE-USDT", "swap": "DOGE-USDT-SWAP", "is_btc": False},
    {"symbol": "ADA", "spot": "ADA-USDT", "swap": "ADA-USDT-SWAP", "is_btc": False},
    {"symbol": "AVAX", "spot": "AVAX-USDT", "swap": "AVAX-USDT-SWAP", "is_btc": False},
    {"symbol": "LINK", "spot": "LINK-USDT", "swap": "LINK-USDT-SWAP", "is_btc": False},
    {"symbol": "DOT", "spot": "DOT-USDT", "swap": "DOT-USDT-SWAP", "is_btc": False},
    {"symbol": "TRX", "spot": "TRX-USDT", "swap": "TRX-USDT-SWAP", "is_btc": False},
    {"symbol": "MATIC", "spot": "MATIC-USDT", "swap": "MATIC-USDT-SWAP", "is_btc": False},
    # DeFi 赛道
    {"symbol": "UNI", "spot": "UNI-USDT", "swap": "UNI-USDT-SWAP", "is_btc": False},
    {"symbol": "AAVE", "spot": "AAVE-USDT", "swap": "AAVE-USDT-SWAP", "is_btc": False},
    {"symbol": "LDO", "spot": "LDO-USDT", "swap": "LDO-USDT-SWAP", "is_btc": False},
    # L2 / 新兴公链
    {"symbol": "ARB", "spot": "ARB-USDT", "swap": "ARB-USDT-SWAP", "is_btc": False},
    {"symbol": "OP", "spot": "OP-USDT", "swap": "OP-USDT-SWAP", "is_btc": False},
    {"symbol": "APT", "spot": "APT-USDT", "swap": "APT-USDT-SWAP", "is_btc": False},
    {"symbol": "SUI", "spot": "SUI-USDT", "swap": "SUI-USDT-SWAP", "is_btc": False},
    {"symbol": "SEI", "spot": "SEI-USDT", "swap": "SEI-USDT-SWAP", "is_btc": False},
    # Meme / 热门
    {"symbol": "PEPE", "spot": "PEPE-USDT", "swap": "PEPE-USDT-SWAP", "is_btc": False},
    {"symbol": "WIF", "spot": "WIF-USDT", "swap": "WIF-USDT-SWAP", "is_btc": False},
    # 平台币 / 其他
    {"symbol": "OKB", "spot": "OKB-USDT", "swap": "OKB-USDT-SWAP", "is_btc": False},
    {"symbol": "HYPE", "spot": "HYPE-USDT", "swap": "HYPE-USDT-SWAP", "is_btc": False},
]

SCREEN1_INDICATORS: List[str] = [
    "RSI_50", "SuperTrend", "StochRSI_Cross", "OBV_Trend", "Keltner_Channel"
]

SCREEN2_INDICATORS: List[str] = [
    "GoldenCross_50_200", "MACD_Cross", "Vortex", "TEMA", "EMA_Align_20_50_200",
    "Elder_ray",  # 趋势力度衰竭/逆转预警（Bull/Bear Power）
]

WEEKLY_WEIGHT: float = 0.6
DAILY_WEIGHT: float = 0.4

REVERSAL_THRESHOLD: float = 60.0
REVERSAL_SPEED_LOW: float = 30.0
REVERSAL_ACCEL_HIGH: float = 20.0

TECHNICAL_WEIGHT: float = 0.6
FUNDAMENTAL_WEIGHT: float = 0.4
MAX_CONFLICT_DEDUCTION: float = 0.3

OPEN_CONFIDENCE_THRESHOLD: float = 60.0
TRIAL_CONFIDENCE_THRESHOLD: float = 45.0

POSITION_TIERS: List[tuple] = [
    (85, 0.60),
    (75, 0.45),
    (65, 0.30),
    (55, 0.15),
    (45, 0.05),
    (0, 0.02),   # 低于45%也有最小仓位（2%），低置信度低仓位
]

CONFIDENCE_JUMP_THRESHOLD: float = 15.0
COUNTER_TREND_ADDON_BUDGET: float = 0.40
TOTAL_POSITION_BUDGET_CAP: float = 0.80

DEFAULT_INST_SPOT: str = "BTC-USDT"
DEFAULT_INST_SWAP: str = "BTC-USDT-SWAP"
