"""三屏趋势系统 — 配置常量"""

from typing import Dict, List

CANDIDATE_COINS: List[Dict] = [
    # 核心大币种（回测验证正收益）
    {"symbol": "BTC", "spot": "BTC-USDT", "swap": "BTC-USDT-SWAP", "is_btc": True},
    {"symbol": "ETH", "spot": "ETH-USDT", "swap": "ETH-USDT-SWAP", "is_btc": False},
    {"symbol": "SOL", "spot": "SOL-USDT", "swap": "SOL-USDT-SWAP", "is_btc": False},
    {"symbol": "BNB", "spot": "BNB-USDT", "swap": "BNB-USDT-SWAP", "is_btc": False},
    # 高流动性扩展币种
    {"symbol": "HYPE", "spot": "HYPE-USDT", "swap": "HYPE-USDT-SWAP", "is_btc": False},
    {"symbol": "UNI", "spot": "UNI-USDT", "swap": "UNI-USDT-SWAP", "is_btc": False},
    {"symbol": "ARB", "spot": "ARB-USDT", "swap": "ARB-USDT-SWAP", "is_btc": False},
    {"symbol": "ZEC", "spot": "ZEC-USDT", "swap": "ZEC-USDT-SWAP", "is_btc": False},
    {"symbol": "DOGE", "spot": "DOGE-USDT", "swap": "DOGE-USDT-SWAP", "is_btc": False},
]

SCREEN1_INDICATORS: List[str] = [
    "RSI_50",
    "SuperTrend",
    "StochRSI_Cross",
    "OBV_Trend",
    "Keltner_Channel",
]

SCREEN2_INDICATORS: List[str] = [
    "GoldenCross_50_200",
    "MACD_Cross",
    "Vortex",
    "TEMA",
    "EMA_Align_20_50_200",
    "Elder_ray",  # 趋势力度衰竭/逆转预警（Bull/Bear Power）
]

# Phase 2: 反方指标 — 平衡确认偏误
# 与趋势指标形成对冲：趋势BULL时反方可能发出BEAR（超买/背离/高波动）
COUNTER_INDICATORS: List[str] = [
    "Bollinger_Bands",  # 布林带均值回归：超买/超卖
    "RSI_Divergence",  # 量价背离：顶背离/底背离
    "ATR_Volatility",  # 波动率突变：极端行情预警
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
    (0, 0.02),  # 低于45%也有最小仓位（2%），低置信度低仓位
]

CONFIDENCE_JUMP_THRESHOLD: float = 15.0
COUNTER_TREND_ADDON_BUDGET: float = 0.40
TOTAL_POSITION_BUDGET_CAP: float = 0.80

# Phase 2: 极端行情应对机制
EXTREME_VOLATILITY_THRESHOLD: float = 2.0  # ATR > 2倍均值 → 极端行情
EXTREME_VOLATILITY_POSITION_CAP: float = 0.30  # 极端行情下最大仓位30%
DAILY_LOSS_CIRCUIT_BREAKER: float = 0.08  # 单日亏损>8% → 熔断
MAX_DRAWDOWN_CIRCUIT_BREAKER: float = 0.20  # 最大回撤>20% → 强制降仓

# Phase 2: 动态权重过拟合防护
WEIGHT_LOOKBACK_WINDOW: int = 180  # 权重计算回看窗口（天）
WEIGHT_SMOOTHING_ALPHA: float = 0.95  # 权重指数平滑系数
WEIGHT_MIN: float = 0.05  # 单指标最低权重5%
WEIGHT_MAX: float = 0.30  # 单指标最高权重30%

DEFAULT_INST_SPOT: str = "BTC-USDT"
DEFAULT_INST_SWAP: str = "BTC-USDT-SWAP"

# Phase 3: 逐仓模式 + 价值风险评估 + 加仓系统
MARGIN_MODE: str = "isolated"
MAX_LEVERAGE: float = 5.0
MAX_POSITION_PCT: float = 0.50
MAX_ADDON_POSITION_PCT: float = 0.70

BTC_DIVERGENCE_ADDON_PCT: float = 0.08
BASE_TAKE_PROFIT_PCT: float = 0.04
BASE_STOP_LOSS_PCT: float = 0.10

RISK_REWARD_THRESHOLD: float = 1.5
TREND_STRENGTH_ADDON_THRESHOLD: float = 65.0
MAX_ADDON_COUNT: int = 2

# Phase 3.1: BTC风向标 — 全系统做多/做空闸门
BTC_WIND_VANE_DAILY_MA: int = 128  # 日线MA128
BTC_WIND_VANE_WEEKLY_MA: int = 200  # 周线MA200
BTC_WIND_VANE_BREAK_DAYS: int = 3  # 连续跌破MA128的天数阈值
BTC_WIND_VANE_ENABLED: bool = True  # 风向标总开关

# ── 第一屏基本面分析开关（可回退到纯技术分析基线）──
# True: 集成 6-TRADING 7维基本面分析（减半周期/矿工经济/链上估值/宏观金融/跨市场）
# False: 纯技术分析（基线策略，对应 git tag baseline-tech-only）
# 基本面数据不可用时自动回退到纯技术分析
FUNDAMENTAL_SCREEN1_ENABLED: bool = True
FUNDAMENTAL_TECH_WEIGHT: float = 0.6  # 技术权重
FUNDAMENTAL_FUND_WEIGHT: float = 0.4  # 基本面权重

# ── Phase 3.5: 最小阻力方向引擎（第一性原理）──
# 市场总是沿着阻力最小方向运动
# 时间三维（长/中/小周期）× 五维阻力算法 → 最小阻力三维模型（D/V/A）→ 最小阻力方向
LEAST_RESISTANCE_ENABLED: bool = True  # 最小阻力引擎总开关（纯算法驱动，静态指标已移除）
LEAST_RESISTANCE_PRICE_LOOKBACK: int = 60  # 价格阻力回看周期
LEAST_RESISTANCE_WEIGHTS: Dict[str, float] = {
    "price": 0.30,  # 价格阻力权重（压力位/支撑位）
    "volume": 0.20,  # 量能阻力权重（OBV/放量缩量）
    "momentum": 0.20,  # 动量阻力权重（RSI/MACD/背离）
    "trend": 0.20,  # 趋势阻力权重（均线斜率/Elder-ray）
    "fundamental": 0.10,  # 基本面阻力权重
}
