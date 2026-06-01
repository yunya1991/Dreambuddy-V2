#!/usr/bin/env python3
"""
回测策略实现模块 v14.0
======================
忠实实现 TRADING_WORKFLOW_SPEC_v1.md 设计规范

v14.0 — BTC牛市信号增强 + ETH波动率自适应:
  A1. 牛市溢价分: STRONG_BULL + LONG + RSI∈[50,75] → signal_score +8 (仓位 MEDIUM→STRONG)
  A2. RSI过热减仓: STRONG_BULL + LONG + RSI>75 → single_layer_pct×0.5 (防高位追涨)
  B1. ETH vol_mult地板 1.30→1.50: 加仓间隔10.4%→12%, 止盈5.2%→6% (链变稀疏)
  B2. ETH SHORT L2c放宽: avg×1.20→avg×1.25 (多5%呼吸空间, 减少误止链)

v13.0 — 强趋势区顺势马丁 (ABOVE_ALL/BELOW_ALL + 连涨跌 + MEC):
  1. ABOVE_ALL (BTC全线上方=强多头): 连跌≥3日 + MEC≥2 → 开 LONG 马丁
  2. BELOW_ALL (BTC全线下方=强空头): 连涨≥3日 + MEC≥2 → 开 SHORT 马丁
  3. 与IN_ZONE单层不同: 不设ma_zone_opened, 允许马丁加仓, 用L2b/L2c出场
  4. MEC阈值统一: score≥2=满仓(1.0), <2=BLOCKED, 动能+量能双确认即可入场

v12.0 — L2b/L2c 双层链保护 (防马丁链在趋势反转中越陷越深):
  1. L2b: Regime对立止链 — 持仓方向与当前 Regime 明确对立时提前止损整条链
     Level=0: 仅 STRONG 对立才触发 (SHORT+STRONG_BULL / LONG+STRONG_BEAR)
     Level>=1: WEAK 或 STRONG 对立均触发 (保护已堆叠的马丁链)
  2. L2c: 链均价提前保护 — Level>=1 时启用与v9.0相同的均价×1.20/×0.80止损
     不等Level3加满: 第1次加仓后即保护, 防止极端行情在链内继续叠损
  3. 不影响 V9 熊市基线: 熊市SHORT链极少加仓, L2b/L2c基本不触发

v11.0 — MEC动能衰竭确认 + V9基础保留 (BLOCKED→FALLBACK_V9):
  1. calc_btc_mec(): 三维验证BTC动能衰竭 (动能/量能/势能, score 0-3)
  2. BLOCKED状态改为FALLBACK_V9: 无MA信号时V9正常入场, 不再阻止
  3. BLOCKED_LOW_MEC: MA区间但MEC评分不足(<2), 直接回退V9
  4. BELOW_ALL_BLOCKED仅阻止LONG: 强趋势下跌时仍允许STRONG_BEAR SHORT
  5. MA区间反向单: score≥3 满仓(size_mult=1.0), score=2 半仓(0.5), 无加仓
  6. 势能门槛按币种vol_mult动态: 1.5×vol_mult ATR

v10.0 — 日线MA区间经验法则: 涨三不追，跌四不压:
  1. detect_btc_ma_zone(): 检测BTC价格在MA5/13/30/65/128/200中的区间位置
  2. check_ma_zone_entry_signal(): 连续涨3日→允许空头, 连续跌4日→允许多头
  3. BTC作为全局参考: BTC跌破所有均线时禁止所有币种开仓
  4. Screen2可覆盖Screen1方向: 均线区间内日线反转信号优先
  5. Screen2Output新增 ma_zone_gate / ma_direction 字段

v9.0 — Level3加满后启用均价止损 (防整链亏损):
  1. is_martin_complete 时设置 stop_loss_price = avg_entry×0.80 (LONG) / ×1.20 (SHORT)
  2. check_exit_signals L1-SL 仅在 is_martin_complete 且 stop_loss_price>0 时触发
  3. 未加满前无固定SL, 仍靠信号反转/回撤出场

v8.0 — 用户马丁经验规则 (个人实战优化):
  1. 加仓间隔: 每跌 addon_gap_pct%×vol_mult 加一次仓 (复利计算, BTC=8%, SOL/ETH按波动率放大)
  2. 止盈: 均价+tp_pct%×vol_mult 一次全平 (BTC=4%, SOL/ETH按波动率放大), 无分批
  3. 加仓门禁: 需 Screen2 信号评分 ≥ addon_min_score (默认50)
  4. 无固定价格止损 (移除SL触发); 非明确信号不提前出场
  5. 出场条件: ① TP目标触及 ② Screen1方向明确反转 ③ 20%组合回撤强制全平
  6. 移除 risk_event 出场 (ATR扩张不再强制平仓)

v7.0 Opt-1B — 动态历史波动率(HV)驱动 Regime 阈值:
  1. _calc_quarterly_vol_mult(): 13周滚动 std / BTC基准(9%/周) → vol_mult
  2. 静态 _STATIC_REGIME_VOL_MULT 作为数据不足时的 fallback
  3. 回测自动滚动; 实盘建议每季度重新计算一次 vol_mult
  4. 效果: SOL vol_mult≈1.8, STRONG_BEAR 门槛动态扩宽至 ~-35% 4周跌幅

v7.0 Opt-2 — RSI+ATR 加仓抑制 (addon_suppressed, 阈值按代币波动率分档):
  1. Screen2Output 新增 addon_suppressed 字段
  2. ADDON_SUPPRESS_THRESHOLDS: BTC(RSI>70/ATR>1.4×) ETH(72/1.5×) SOL(76/1.8×)
  3. 引擎在 calc_martin_add_on 前检查 screen2.addon_suppressed

v6.0 Option C — 双向马丁 (bidirectional martingale):
  1. STRONG_BEAR regime → 强制做空 (direction=SHORT, 仓位60%)
  2. WEAK_BEAR regime → 继续观望 (direction=WAIT, 拒绝LONG)
  3. SHORT马丁底层全部就绪: 加仓触发high>=target, SL=均价×1.20, TP=均价-ATR×mult

v5.0 熊市门禁 (A+B方案):
  1. detect_market_regime() EMA50缺失时改用 price vs EMA20 (B: 解除50周数据依赖)
  2. Screen1 熊市入场门禁: regime=WEAK_BEAR/STRONG_BEAR → direction=WAIT, 拒绝新LONG (A)
  3. 移除失效的 EMA50×0.95 强制做空覆盖 (EMA50在27周数据内不可靠)

v4.0 市场状态增强 (v2改进):
  1. Screen1 熊市强制覆盖: 周线收盘低于EMA50×0.95 → 强制空头
  2. 新增 detect_market_regime(): 5档市场状态识别, 输出仓位乘数
  3. Screen1Output 新增 regime/regime_multiplier 字段
  4. Screen2 仓位计算引入 regime_multiplier (倍数缩放)
  5. TP倍数收窄: 0.8x/1.5x/2.5x ATR (原 2x/3x/5x)

v3.1 规范对齐修正 (D1/D2):
  D1. 分批止盈比例: 50%→30%→20% (原 30%/30%/40%)
  D2. 止损动态化: 加仓阶段=Level3极限价保护; 马丁完成后=均价×0.80

v3.0 基础修正 (完全对齐规范):
  1. 止损: 固定20% (基于入场价), 不再使用ATR倍数
  2. 加仓: 等额加仓 (不再递减)
  3. 止盈: 仅Level 3加满后启用 (不再Level 2即可)
  4. 离场: 分批止盈 50%/30%/20% (不再一次性全平)
  5. 仓位: 对齐规范 强多头60%/弱多头40%/观望20% 总仓位上限
  6. 止盈: 三层TP (ATR倍数), 渐进锁利

第一屏 (周线): 方向判断 + 策略类型选择 + 仓位上限
第二屏 (日线): 信号强度评估 + 四类订单设置
第三屏 (日线模拟): A9四层离场决策

简化说明:
  - 回测中以日线为主要时间粒度
  - 周线通过 resample 日线生成
  - 小时线信号简化为日线内的低点/高点触发
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import statistics


# ==================== 数据类型 ====================

class Direction(Enum):
    LONG = "long"
    SHORT = "short"
    WAIT = "wait"


class SignalStrength(Enum):
    STRONG = "strong"       # >=70
    MEDIUM = "medium"       # 50-69
    WEAK = "weak"           # 30-49
    NONE = "none"           # <30


class StrategyType(Enum):
    FUTURES_MARTIN = "futures_martin"
    SPOT_MARTIN = "spot_martin"


class ExitReason(Enum):
    TAKE_PROFIT_1 = "take_profit_1"      # v8.0: 单次全仓止盈 (均价+tp_pct%×vol_mult)
    TAKE_PROFIT_2 = "take_profit_2"      # 保留兼容 (v8.0不使用)
    TAKE_PROFIT_3 = "take_profit_3"      # 保留兼容 (v8.0不使用)
    STOP_LOSS = "stop_loss"              # 保留兼容 (v8.0不触发固定SL)
    SIGNAL_REVERSAL = "signal_reversal"
    DRAWDOWN_LIMIT = "drawdown_limit"
    RISK_EVENT = "risk_event"            # 保留兼容 (v8.0不触发)
    END_OF_BACKTEST = "end_of_backtest"
    NONE = "none"


@dataclass
class Screen1Output:
    """第一屏输出: 周线决策"""
    timestamp: int
    direction: Direction
    strategy_type: StrategyType
    weekly_score: float
    ema_trend: str
    macd_signal: str
    market_state: str = "观望"
    position_limit_pct: float = 0.20    # 总仓位上限: 20%/40%/60%
    regime: str = "CONSOLIDATION"       # 市场形态: STRONG_BULL/WEAK_BULL/CONSOLIDATION/WEAK_BEAR/STRONG_BEAR
    regime_multiplier: float = 0.5      # 仓位乘数: 0.5(震荡) / 0.75(弱趋势) / 1.0(强趋势)
    vol_mult: float = 1.0               # v8.0: 动态HV乘数, 用于加仓间隔和止盈计算


@dataclass
class Screen2Output:
    """第二屏输出: 日线预设"""
    timestamp: int
    signal_strength: SignalStrength
    signal_score: float
    entry_price: float
    position_pct: float              # 单层仓位比例 (总仓位的1/4)
    add_on_levels: List[float]       # 3个加仓价位 (复利间隔 addon_gap%×vol_mult)
    tp_target: float                 # v8.0: 单次全仓止盈目标 (均价+tp_pct%×vol_mult)
    atr: float
    volatility: float
    addon_suppressed: bool = False   # v7.0 Opt-2: RSI超买/ATR扩张时抑制本轮加仓
    ma_zone_gate: str = "BREAKOUT_SKIP"      # v10.0: MA区间门禁状态
    ma_direction: Optional["Direction"] = None  # v10.0: MA区间确定的方向 (可覆盖Screen1)
    ma_zone_ref_price: float = 0.0           # v10.0: 参考MA价格 (SHORT=阻力MA, LONG=支撑MA)
    ma_zone_size_mult: float = 1.0           # v11.0: MEC评分决定仓位 (score=3→1.0, score=2→0.5)


@dataclass
class Position:
    """当前持仓状态"""
    direction: Direction = Direction.WAIT
    entry_price: float = 0.0         # 加权平均入场价
    initial_size_usd: float = 0.0    # 初始入场大小 (用于等额加仓)
    size_usd: float = 0.0            # 当前持仓大小
    level: int = 0                   # 马丁层级 0=初始, 1-3=加仓
    add_on_levels: List[float] = field(default_factory=list)
    tp_target: float = 0.0           # v8.0: 单次全仓止盈目标 (随均价滚动更新)
    stop_loss_price: float = 0.0     # v9.0: 均价止损 (仅 Level3加满后启用, 默认0=未激活)
    highest_equity: float = 0.0
    entry_date: str = ""
    signal_strength: SignalStrength = SignalStrength.NONE
    screen1: Optional[Screen1Output] = None
    total_cost: float = 0.0
    is_martin_complete: bool = False  # Level 3加满标志 (用于统计)
    ma_zone_opened: bool = False      # v10.0: 是否为MA区间反向单
    ma_zone_ref_price: float = 0.0   # v10.0: 参考MA价格 (SHORT=阻力MA突破出场, LONG=支撑MA跌破出场)


@dataclass
class Trade:
    """交易记录"""
    trade_id: int
    timestamp: int
    date: str
    action: str           # open / add_on / partial_close / close
    direction: Direction
    price: float
    size_usd: float
    fee: float
    signal_strength: SignalStrength
    screen1_direction: Direction
    exit_reason: ExitReason = ExitReason.NONE
    pnl: float = 0.0
    pnl_pct: float = 0.0
    equity_at_close: float = 0.0


# ==================== 默认策略参数 (可被贝叶斯优化覆盖) ====================

DEFAULT_STRATEGY_PARAMS = {
    # 第一屏参数
    "strong_score_threshold": 65.0,   # 强多头阈值 (规范: >=65)
    "weak_score_threshold": 50.0,     # 弱多头阈值 (规范: >=50)
    "short_score_threshold": 35.0,    # 空头阈值 (规范: <=35)

    # v8.0 加仓参数: 按固定百分比复利计算间隔, 按 vol_mult 放大
    "addon_gap_pct": 8.0,             # BTC加仓间隔基准 (每跌8%加仓; SOL/ETH×vol_mult)
    "addon_min_score": 50.0,          # 加仓最低信号评分门禁 (Screen2 score)

    # v8.0 止盈参数: 单次全仓止盈, 按 vol_mult 放大
    "tp_pct": 4.0,                    # BTC止盈基准 (均价+4%; SOL/ETH×vol_mult)
}


def _apply_opt_params(defaults: dict, overrides: dict = None) -> dict:
    """合并优化参数 (保留默认值, 仅覆盖传入的参数)"""
    if not overrides:
        return defaults
    return {**defaults, **overrides}

# v7.0 Opt-1B: 动态 HV 驱动的 Regime 阈值乘数
# 静态表作为 fallback (数据 <4 周时使用)
# 推导: BTC~65%/ETH~85%/SOL~115% 年化波动率 → 周波动率基准 BTC≈9%/周
# v14.0-B1: ETH波动率地板 1.30→1.50 (加仓间隔10.4%→12%, 止盈5.2%→6%)
_STATIC_REGIME_VOL_MULT: dict = {
    "BTC-USDT-SWAP": 1.00,
    "ETH-USDT-SWAP": 1.50,
    "SOL-USDT-SWAP": 1.75,
}

# v7.0 Opt-2: 按代币波动率分档的加仓抑制阈值
# BTC 最敏感(低门槛), SOL 最宽松(高门槛), 避免误伤高波动品种正常行情
ADDON_SUPPRESS_THRESHOLDS: dict = {
    "BTC-USDT-SWAP": {"rsi_long": 70, "rsi_short": 30, "atr_mult": 1.4},
    "ETH-USDT-SWAP": {"rsi_long": 72, "rsi_short": 28, "atr_mult": 1.5},
    "SOL-USDT-SWAP": {"rsi_long": 76, "rsi_short": 24, "atr_mult": 1.8},
}


def _calc_quarterly_vol_mult(
    weekly_candles: List[Dict],
    idx: int,
    inst_id: str = "BTC-USDT-SWAP",
    reference_wv: float = 9.0,
) -> float:
    """
    动态历史波动率 (HV) → Regime 阈值乘数

    用最近 13 周 (≈一个季度) 的周收益率 std 除以 BTC 基准周波动率 (9%/周)
    返回值在 [0.8, 2.5] 之间, 数据不足时回退到静态表
    """
    if idx < 4:
        return _STATIC_REGIME_VOL_MULT.get(inst_id, 1.0)
    n = min(13, idx)
    returns = []
    for j in range(idx - n + 1, idx + 1):
        prev_close = weekly_candles[j - 1].get("close") or 0
        curr_close = weekly_candles[j].get("close") or 0
        if prev_close > 0:
            returns.append((curr_close - prev_close) / prev_close * 100)
    if len(returns) < 4:
        return _STATIC_REGIME_VOL_MULT.get(inst_id, 1.0)
    hv_weekly = statistics.stdev(returns)
    dynamic_mult = hv_weekly / reference_wv
    # 以静态基准为下限: 动态 HV 只能扩宽阈值, 不能收紧
    # 避免短期低波动期给高波动代币赋予过低的 vol_mult (冷启动问题)
    static_floor = _STATIC_REGIME_VOL_MULT.get(inst_id, 1.0)
    return max(static_floor, min(2.5, round(dynamic_mult, 3)))


# ==================== MA区间经验法则 (v10.0) ====================

MA_PERIODS = [5, 13, 30, 65, 128, 200]


def detect_btc_ma_zone(btc_candles: List[Dict], idx: int) -> str:
    """
    检测 BTC 价格在均线系列中的位置 (v10.0)

    返回:
      "IN_ZONE"          — 价格被夹在均线之间 (至少一条在上，一条在下)
      "ABOVE_ALL"        — 价格高于全部有效MA → 上行突破，跳过经验法则
      "BELOW_ALL"        — 价格低于全部有效MA → 强趋势下跌，禁止所有开仓
      "INSUFFICIENT_DATA"— 有效MA不足3条，无法判断
    """
    if idx < 0 or idx >= len(btc_candles):
        return "INSUFFICIENT_DATA"

    price = btc_candles[idx]["close"]
    ma_values = [btc_candles[idx].get(f"sma{p}") for p in MA_PERIODS]
    valid = [v for v in ma_values if v is not None]

    if len(valid) < 3:
        return "INSUFFICIENT_DATA"

    above = [v for v in valid if v > price]
    below = [v for v in valid if v < price]

    if not above:
        return "ABOVE_ALL"
    if not below:
        return "BELOW_ALL"
    return "IN_ZONE"


def calc_btc_mec(
    btc_candles: List[Dict],
    btc_idx: int,
    signal_dir: str,
    vol_mult: float,
    consecutive_days: int,
) -> Tuple[int, Dict]:
    """
    BTC动能衰竭确认 (MEC, v11.0)

    三维验证: 动能/量能/势能 各1分, 满分3分
      动能: 末日涨幅 < 首日涨幅 (相对衰减)
      量能: 末日成交量 < 首日成交量 (量能背离)
      势能: BTC收盘距最近阻力/支撑MA < 1.5×vol_mult 个ATR (接近关键位)

    signal_dir: "SHORT"(看空,3连涨) / "LONG"(看多,4连跌)
    vol_mult: 目标币种波动率乘数, 仅用于势能门槛
    consecutive_days: 触发条件天数 (SHORT=3, LONG=4)
    返回: (score 0-3, detail_dict)
    """
    if btc_idx < consecutive_days + 1:
        return 0, {"error": "insufficient_data"}

    first_idx = btc_idx - consecutive_days + 1
    last_idx = btc_idx

    first_c = btc_candles[first_idx]
    last_c = btc_candles[last_idx]
    prev_first = btc_candles[first_idx - 1]

    score = 0
    detail: Dict = {}

    # 动能: 末日vs首日收益率绝对值
    gain_first = abs(first_c["close"] - prev_first["close"]) / (prev_first["close"] + 1e-9)
    gain_last = abs(last_c["close"] - btc_candles[last_idx - 1]["close"]) / (btc_candles[last_idx - 1]["close"] + 1e-9)
    momentum_decay = gain_last < gain_first
    detail["gain_first"] = round(gain_first * 100, 3)
    detail["gain_last"] = round(gain_last * 100, 3)
    detail["momentum_decay"] = momentum_decay
    if momentum_decay:
        score += 1

    # 量能: 末日vs首日成交量
    vol_first = first_c.get("volume", 0)
    vol_last = last_c.get("volume", 0)
    vol_ratio = vol_last / (vol_first + 1e-9) if vol_first > 0 else 1.0
    volume_diverge = vol_last < vol_first
    detail["vol_first"] = round(vol_first, 1)
    detail["vol_last"] = round(vol_last, 1)
    detail["vol_ratio"] = round(vol_ratio, 3)
    detail["volume_diverge"] = volume_diverge
    if volume_diverge:
        score += 1

    # 势能: BTC接近关键MA (距离 < 1.5×vol_mult 个ATR)
    atr_val = last_c.get("atr")
    close_val = last_c["close"]
    ma_vals = [last_c.get(f"sma{p}") for p in MA_PERIODS]
    valid_mas = [v for v in ma_vals if v is not None]
    proximity = False
    threshold_atr = 1.5 * vol_mult
    if atr_val and atr_val > 0 and valid_mas:
        if signal_dir == "SHORT":
            mas_above = [v for v in valid_mas if v > close_val]
            if mas_above:
                nearest = min(mas_above)
                dist_atr = (nearest - close_val) / atr_val
                proximity = dist_atr < threshold_atr
                detail["nearest_resist_ma"] = round(nearest, 4)
                detail["dist_atr"] = round(dist_atr, 3)
        else:
            mas_below = [v for v in valid_mas if v < close_val]
            if mas_below:
                nearest = max(mas_below)
                dist_atr = (close_val - nearest) / atr_val
                proximity = dist_atr < threshold_atr
                detail["nearest_support_ma"] = round(nearest, 4)
                detail["dist_atr"] = round(dist_atr, 3)
    detail["proximity"] = proximity
    detail["threshold_atr"] = threshold_atr
    if proximity:
        score += 1

    detail["score"] = score
    return score, detail


def check_ma_zone_entry_signal(
    btc_candles: List[Dict],
    target_candles: List[Dict],
    btc_idx: int,
    target_idx: int,
    vol_mult: float = 1.0,
) -> Tuple[str, Optional[Direction], float, float]:
    """
    "涨三不追，跌四不压" 均线区间经验法则 (v11.0)

    BTC作为全局参考: BTC区间状态决定是否应用此规则
    目标币种(target)的连涨/连跌条件决定方向
    MEC评分决定入场规模 (v11.0新增)

    返回: (gate, direction_override, ref_ma_price, size_mult)
      gate:
        "LONG_ALLOWED"     — IN_ZONE 连跌4日+支撑未破+MEC≥2 → 单层多头; ref_ma=支撑MA
        "SHORT_ALLOWED"    — IN_ZONE 连涨3日+阻力未突破+MEC≥2 → 单层空头; ref_ma=阻力MA
        "ABOVE_ALL_LONG"   — 强多头 连跌≥3日+MEC≥2 → LONG马丁(可加仓); ref_ma=0
        "BELOW_ALL_SHORT"  — 强空头 连涨≥3日+MEC≥2 → SHORT马丁(可加仓); ref_ma=0
        "BLOCKED_LOW_MEC"  — 连涨/连跌条件满足但MEC<2 → 回退V9正常入场
        "BELOW_ALL_BLOCKED"— BTC跌破所有均线且无涨三信号 → 仅阻止LONG (SHORT保留)
        "BREAKOUT_SKIP"    — BTC上行突破或数据不足 → 跳过此规则用常规Screen2
      size_mult: ABOVE/BELOW_ALL=1.0, IN_ZONE MEC=3→1.0/MEC=2→0.5, 其余→0.0
    """
    zone = detect_btc_ma_zone(btc_candles, btc_idx)

    if zone == "INSUFFICIENT_DATA":
        return "BREAKOUT_SKIP", None, 0.0, 0.0

    # v13.0: 强多头区 (BTC全线上方) — 跌三不压 + MEC → LONG 马丁
    if zone == "ABOVE_ALL":
        if target_idx >= 3:
            consecutive_down = 0
            for j in range(target_idx, max(0, target_idx - 5), -1):
                if j > 0 and target_candles[j]["close"] < target_candles[j - 1]["close"]:
                    consecutive_down += 1
                else:
                    break
            if consecutive_down >= 3:
                mec_score, _ = calc_btc_mec(btc_candles, btc_idx, "LONG", vol_mult, consecutive_down)
                if mec_score >= 2:
                    return "ABOVE_ALL_LONG", Direction.LONG, 0.0, 1.0
        return "BREAKOUT_SKIP", None, 0.0, 0.0

    # v13.0: 强空头区 (BTC全线下方) — 涨三不追 + MEC → SHORT 马丁
    if zone == "BELOW_ALL":
        if target_idx >= 3:
            consecutive_up = 0
            for j in range(target_idx, max(0, target_idx - 5), -1):
                if j > 0 and target_candles[j]["close"] > target_candles[j - 1]["close"]:
                    consecutive_up += 1
                else:
                    break
            if consecutive_up >= 3:
                mec_score, _ = calc_btc_mec(btc_candles, btc_idx, "SHORT", vol_mult, consecutive_up)
                if mec_score >= 2:
                    return "BELOW_ALL_SHORT", Direction.SHORT, 0.0, 1.0
        return "BELOW_ALL_BLOCKED", None, 0.0, 0.0

    # zone == "IN_ZONE": 检测目标币种连涨/连跌
    if target_idx < 4:
        return "BREAKOUT_SKIP", None, 0.0, 0.0

    curr_price = target_candles[target_idx]["close"]

    # 连续上涨天数 (从今日向前数)
    consecutive_up = 0
    for j in range(target_idx, max(0, target_idx - 5), -1):
        if j > 0 and target_candles[j]["close"] > target_candles[j - 1]["close"]:
            consecutive_up += 1
        else:
            break

    # 连续下跌天数
    consecutive_down = 0
    for j in range(target_idx, max(0, target_idx - 6), -1):
        if j > 0 and target_candles[j]["close"] < target_candles[j - 1]["close"]:
            consecutive_down += 1
        else:
            break

    # 目标币种可用MA值
    target_mas = [target_candles[target_idx].get(f"sma{p}") for p in MA_PERIODS]
    valid_mas = [v for v in target_mas if v is not None]

    if not valid_mas:
        return "BREAKOUT_SKIP", None, 0.0, 0.0

    mas_above = sorted([v for v in valid_mas if v > curr_price])
    mas_below = sorted([v for v in valid_mas if v < curr_price], reverse=True)

    # 涨三不追: 连涨>=3日 且 收盘仍低于最近上方MA(阻力未破) -> MEC验证后空头
    if consecutive_up >= 3 and mas_above:
        nearest_above = mas_above[0]
        if curr_price < nearest_above:
            mec_score, _ = calc_btc_mec(btc_candles, btc_idx, "SHORT", vol_mult, consecutive_up)
            if mec_score >= 2:
                size_mult = 1.0 if mec_score >= 3 else 0.5
                return "SHORT_ALLOWED", Direction.SHORT, nearest_above, size_mult
            else:
                return "BLOCKED_LOW_MEC", None, 0.0, 0.0

    # 跌四不压: 连跌>=4日 且 收盘仍高于最近下方MA(支撑未破) -> MEC验证后多头
    if consecutive_down >= 4 and mas_below:
        nearest_below = mas_below[0]
        if curr_price > nearest_below:
            mec_score, _ = calc_btc_mec(btc_candles, btc_idx, "LONG", vol_mult, consecutive_down)
            if mec_score >= 2:
                size_mult = 1.0 if mec_score >= 3 else 0.5
                return "LONG_ALLOWED", Direction.LONG, nearest_below, size_mult
            else:
                return "BLOCKED_LOW_MEC", None, 0.0, 0.0

    return "BREAKOUT_SKIP", None, 0.0, 0.0


# ==================== 市场形态识别 ====================

def detect_market_regime(
    weekly_candles: List[Dict],
    weekly_idx: int,
    vol_mult: float = 1.0,
) -> Tuple[str, float]:
    """
    市场状态识别 (5档), 返回 (regime_name, position_multiplier)

    vol_mult: 按代币波动率缩放价格动量阈值 (见 REGIME_VOL_MULT)
      BTC=1.0 (基准), ETH=1.3, SOL=1.75

    Regimes:
      STRONG_BULL  — EMA20>EMA50 >3%, MACD hist>0且增长, RSI 50-75  → 1.0
      WEAK_BULL    — EMA20>EMA50 0-3%, 或混合多头信号               → 0.75
      CONSOLIDATION— |EMA20-EMA50|/EMA50 <0.5%, ATR/close <2%       → 0.5
      WEAK_BEAR    — EMA20<EMA50 0-3%, 或 MACD hist<0               → 0.75
      STRONG_BEAR  — EMA20<EMA50 >3%, 或 close<EMA50×0.95           → 1.0
    """
    if weekly_idx < 1:
        return "CONSOLIDATION", 0.5

    curr = weekly_candles[weekly_idx]
    prev = weekly_candles[weekly_idx - 1]

    ema20     = curr.get("ema20")
    ema50     = curr.get("ema50")
    curr_hist = curr.get("macd_hist")
    prev_hist = prev.get("macd_hist")
    rsi       = curr.get("rsi")
    atr_val   = curr.get("atr") or 0
    close_val = curr.get("close") or 1

    # --- 主路径: EMA20+EMA50 均可用 ---
    if ema20 and ema50:
        ema_diff_pct = (ema20 - ema50) / ema50 * 100  # 正=多, 负=空

        if ema_diff_pct < -3.0:
            return "STRONG_BEAR", 1.0

        macd_growing = (curr_hist is not None and prev_hist is not None
                        and curr_hist > 0 and curr_hist > prev_hist)
        rsi_ok = rsi is not None and 50 <= rsi <= 75
        if ema_diff_pct > 3.0 and macd_growing and rsi_ok:
            return "STRONG_BULL", 1.0

        if abs(ema_diff_pct) < 0.5:
            atr_ratio = atr_val / close_val if close_val > 0 else 0
            if atr_ratio < 0.02:
                return "CONSOLIDATION", 0.5

        if ema_diff_pct < 0 or (curr_hist is not None and curr_hist < 0):
            return "WEAK_BEAR", 0.75

        return "WEAK_BULL", 0.75

    # --- B: 价格动量 fallback (EMA 数据不足时, 如周线窗口<50根) ---
    # 用4周涨跌幅 + 连续下跌判断趋势，无需EMA，最少需要4根周线
    if weekly_idx < 4:
        return "CONSOLIDATION", 0.5

    c4w = weekly_candles[weekly_idx - 4]["close"]
    c2w = weekly_candles[weekly_idx - 2]["close"] if weekly_idx >= 2 else close_val
    c1w = weekly_candles[weekly_idx - 1]["close"]
    chg4w = (close_val - c4w) / c4w * 100 if c4w > 0 else 0.0
    consec_down = close_val < c1w and c1w < c2w

    sb = 20 * vol_mult   # STRONG_BEAR/BULL 门槛 (BTC:-20/+20, SOL:-35/+35)
    wb = 8  * vol_mult   # WEAK_BEAR/BULL   门槛 (BTC:-8/+8,   SOL:-14/+14)
    sb2 = 10 * vol_mult  # STRONG_BEAR 连续下跌辅助门槛

    if chg4w < -sb or (chg4w < -sb2 and consec_down):
        return "STRONG_BEAR", 1.0
    if chg4w < -wb or (chg4w < -(wb * 0.5) and consec_down):
        return "WEAK_BEAR", 0.75
    if chg4w > sb:
        return "STRONG_BULL", 1.0
    if chg4w > wb:
        return "WEAK_BULL", 0.75
    return "CONSOLIDATION", 0.5


# ==================== 第一屏: 周线决策 ====================

def run_screen1(
    weekly_candles: List[Dict],
    current_idx: int,
    price: float,
    inst_id: str = "BTC-USDT-SWAP",
    opt_params: dict = None,
) -> Screen1Output:
    """
    第一屏: 周线决策 (对齐规范 1.1)

    评分维度 (各0-25分, 总分0-100):
    1. EMA趋势 (EMA20 vs EMA50)
    2. MACD金叉/死叉
    3. 价格与EMA关系
    4. 成交量趋势

    方向规则 (规范):
    - score >= 65: 强多头 LONG, 仓位上限60%, 合约马丁
    - score >= 50: 弱多头 LONG, 仓位上限40%
    - score > 35:  观望 LONG, 仓位上限20% (默认多头)
    - score <= 35: 空头 SHORT, 仓位上限60%, 合约马丁
    """
    if current_idx < 1:
        return Screen1Output(
            timestamp=weekly_candles[current_idx]["ts"],
            direction=Direction.LONG,
            strategy_type=StrategyType.SPOT_MARTIN,
            weekly_score=50.0,
            ema_trend="neutral",
            macd_signal="none",
            market_state="观望",
            position_limit_pct=0.20,
            regime="CONSOLIDATION",
            regime_multiplier=0.5,
            vol_mult=1.0,
        )

    params = _apply_opt_params(DEFAULT_STRATEGY_PARAMS, opt_params)
    strong_threshold = params["strong_score_threshold"]   # 65
    weak_threshold = params["weak_score_threshold"]       # 50
    short_threshold = params["short_score_threshold"]     # 35

    curr = weekly_candles[current_idx]
    prev = weekly_candles[current_idx - 1]
    vol_mult = _calc_quarterly_vol_mult(weekly_candles, current_idx, inst_id)
    regime, regime_multiplier = detect_market_regime(weekly_candles, current_idx, vol_mult)
    score = 50.0
    ema_trend = "neutral"
    macd_signal = "none"

    # 维度1: EMA趋势 (0-25分)
    if curr.get("ema20") and curr.get("ema50"):
        ema20, ema50 = curr["ema20"], curr["ema50"]
        if ema20 > ema50:
            trend_strength = min((ema20 / ema50 - 1) * 100, 5) / 5 * 25
            score += trend_strength
            ema_trend = "bullish"
        elif ema20 < ema50:
            trend_strength = min((ema50 / ema20 - 1) * 100, 5) / 5 * 25
            score -= trend_strength
            ema_trend = "bearish"

    # 维度2: MACD金叉/死叉 (0-25分)
    if (curr.get("macd_hist") is not None and prev.get("macd_hist") is not None
            and curr.get("macd") is not None):
        curr_hist = curr["macd_hist"]
        prev_hist = prev["macd_hist"]
        if prev_hist <= 0 and curr_hist > 0:
            score += 20
            macd_signal = "golden_cross"
        elif prev_hist >= 0 and curr_hist < 0:
            score -= 20
            macd_signal = "death_cross"
        elif curr_hist > 0:
            score += min(abs(curr_hist) / (abs(curr["macd"]) + 0.001) * 10, 10)
        elif curr_hist < 0:
            score -= min(abs(curr_hist) / (abs(curr["macd"]) + 0.001) * 10, 10)

    # 维度3: 价格与EMA关系 (0-25分)
    if curr.get("ema20"):
        ema20 = curr["ema20"]
        price_ratio = (price - ema20) / ema20 * 100
        if price_ratio > 0:
            score += min(price_ratio * 5, 12)
        else:
            score -= min(abs(price_ratio) * 5, 12)

    # 维度4: 成交量趋势 (0-25分)
    if curr.get("vol_ratio"):
        vr = curr["vol_ratio"]
        if vr > 1.5:
            score += 8
        elif vr < 0.7:
            score -= 5

    score = max(0, min(100, score))

    # 方向判断 (v5.0: 评分分支 + 熊市门禁, 移除失效的EMA50绝对跌破覆盖)
    if score <= short_threshold:
        direction = Direction.SHORT
        market_state = "空头"
        position_limit = 0.60
    elif score >= strong_threshold:
        direction = Direction.LONG
        market_state = "强多头"
        position_limit = 0.60
    elif score >= weak_threshold:
        direction = Direction.LONG
        market_state = "弱多头"
        position_limit = 0.40
    else:
        direction = Direction.LONG
        market_state = "观望"
        position_limit = 0.20

    # v6.0 Option C: 双向马丁 — 按 regime 决定 LONG/SHORT/WAIT
    # 仅影响新开仓; 已持仓由 check_exit_signals 正常管理
    if direction == Direction.LONG:
        if regime == "STRONG_BEAR":
            # 强熊市: 反转做空 (4w跌幅>20% 或 >10%+连续下跌)
            direction = Direction.SHORT
            market_state = "强制空头(STRONG_BEAR)"
            position_limit = 0.60
        elif regime == "WEAK_BEAR":
            # 弱熊市: 观望, 不冒险
            direction = Direction.WAIT
            market_state = "暂停入场(WEAK_BEAR)"
            position_limit = 0.0

    # 策略类型: 基于波动率
    atr_val = curr.get("atr") or 0
    close_val = curr["close"] or 1
    volatility = atr_val / close_val * 100 if close_val > 0 else 0
    strategy_type = StrategyType.FUTURES_MARTIN if volatility > 3 else StrategyType.SPOT_MARTIN

    return Screen1Output(
        timestamp=curr["ts"],
        direction=direction,
        strategy_type=strategy_type,
        weekly_score=round(score, 2),
        ema_trend=ema_trend,
        macd_signal=macd_signal,
        market_state=market_state,
        position_limit_pct=position_limit,
        regime=regime,
        regime_multiplier=regime_multiplier,
        vol_mult=vol_mult,
    )


# ==================== 第二屏: 日线预设 ====================

def _calc_20d_volatility(daily_candles: List[Dict], idx: int) -> float:
    """计算20日波动率 (百分比)"""
    if idx < 20:
        return 2.0
    returns = []
    for i in range(idx - 19, idx + 1):
        if i > 0 and daily_candles[i - 1]["close"] > 0:
            ret = (daily_candles[i]["close"] - daily_candles[i - 1]["close"]) / daily_candles[i - 1]["close"]
            returns.append(ret)
    if len(returns) < 5:
        return 2.0
    return statistics.stdev(returns) * 100


def _calc_20d_atr(daily_candles: List[Dict], idx: int) -> float:
    """计算20日ATR均值，用于判断ATR是否异常扩张"""
    if idx < 5:
        return daily_candles[idx].get("atr") or 0.0
    vals = [daily_candles[j].get("atr") or 0.0 for j in range(max(0, idx - 19), idx + 1) if daily_candles[j].get("atr")]
    return sum(vals) / len(vals) if vals else 0.0


def _classify_signal(score: float) -> SignalStrength:
    if score >= 70:
        return SignalStrength.STRONG
    elif score >= 50:
        return SignalStrength.MEDIUM
    elif score >= 30:
        return SignalStrength.WEAK
    return SignalStrength.NONE


def run_screen2(
    daily_candles: List[Dict],
    current_idx: int,
    screen1: Screen1Output,
    position: Optional[Position],
    inst_id: str = "BTC-USDT-SWAP",
    opt_params: dict = None,
    btc_daily_candles: List[Dict] = None,
    btc_idx: int = None,
) -> Screen2Output:
    """
    第二屏: 日线预设 (v10.0)

    v10.0 新增 MA区间经验法则:
    - BTC跌破所有MA -> 全面禁止开仓 (ma_zone_gate=BELOW_ALL_BLOCKED)
    - BTC在区间内 -> 涨三不追/跌四不压作为独立入场门, 方向可覆盖Screen1
    - BTC上行突破/数据不足 -> 跳过此规则 (ma_zone_gate=BREAKOUT_SKIP)

    v8.0 规则:
    - 加仓间隔: addon_gap_pct%×vol_mult 复利计算 (BTC=8%, SOL/ETH按波动率放大)
    - 止盈: 单次全仓, 均价+tp_pct%×vol_mult (BTC=4%, SOL/ETH按波动率放大)
    - 无固定止损价 (由 check_exit_signals L2/L4 管理出场)
    - 仓位: 对齐规范的60%/40%/20%总仓位上限
    """
    params = _apply_opt_params(DEFAULT_STRATEGY_PARAMS, opt_params)
    addon_gap_pct = params.get("addon_gap_pct", 8.0)
    tp_pct = params.get("tp_pct", 4.0)
    vol_mult = getattr(screen1, "vol_mult", 1.0)

    curr = daily_candles[current_idx]
    price = curr["close"]
    score = 50.0

    # 维度1: 趋势一致性 (日线与周线方向一致)
    if curr.get("ema20") and curr.get("ema50"):
        if screen1.direction == Direction.LONG and curr["ema20"] > curr["ema50"]:
            score += 15
        elif screen1.direction == Direction.SHORT and curr["ema20"] < curr["ema50"]:
            score += 15
        elif screen1.direction != Direction.WAIT:
            score -= 10

    # 维度2: MACD信号
    if current_idx >= 1:
        prev = daily_candles[current_idx - 1]
        curr_hist = curr.get("macd_hist") or 0
        prev_hist = prev.get("macd_hist") or 0
        if prev_hist <= 0 and curr_hist > 0 and screen1.direction == Direction.LONG:
            score += 20
        elif prev_hist >= 0 and curr_hist < 0 and screen1.direction == Direction.SHORT:
            score += 20
        elif curr_hist > 0 and screen1.direction == Direction.LONG:
            score += 8
        elif curr_hist < 0 and screen1.direction == Direction.SHORT:
            score += 8

    # 维度3: RSI信号
    rsi_val = curr.get("rsi")
    if rsi_val is not None:
        if screen1.direction == Direction.LONG:
            if rsi_val < 30:
                score += 15
            elif rsi_val > 70:
                score -= 10
            elif 40 <= rsi_val <= 60:
                score += 5
        elif screen1.direction == Direction.SHORT:
            if rsi_val > 70:
                score += 15
            elif rsi_val < 30:
                score -= 10
            elif 40 <= rsi_val <= 60:
                score += 5

    # 维度4: 成交量确认
    vr = curr.get("vol_ratio") or 1.0
    if vr > 1.3:
        score += 5
    elif vr < 0.6:
        score -= 5

    # v14.0-A1: 牛市溢价分 (STRONG_BULL + LONG + RSI∈[50,75] → 健康牛市区段加分)
    if (screen1.regime == "STRONG_BULL" and screen1.direction == Direction.LONG
            and rsi_val is not None and 50 <= rsi_val <= 75):
        score += 8

    score = max(0, min(100, score))
    signal_strength = _classify_signal(score)

    # 波动率与ATR
    atr_val = curr.get("atr") or (price * 0.02)
    volatility = _calc_20d_volatility(daily_candles, current_idx)

    # === v11.0: MA区间经验法则 (仅在未持仓时检查入场门禁) ===
    ma_gate = "BREAKOUT_SKIP"
    ma_direction_override: Optional[Direction] = None
    ma_zone_ref_price_val: float = 0.0
    ma_zone_size_mult_val: float = 1.0

    if btc_daily_candles is not None and btc_idx is not None and position is not None and position.direction == Direction.WAIT:
        btc_ref = btc_daily_candles if inst_id != "BTC-USDT-SWAP" else daily_candles
        btc_ref_idx = btc_idx if inst_id != "BTC-USDT-SWAP" else current_idx
        ma_gate, ma_direction_override, ma_zone_ref_price_val, ma_zone_size_mult_val = check_ma_zone_entry_signal(
            btc_ref, daily_candles, btc_ref_idx, current_idx, vol_mult
        )

    # v11.0: BTC跌破所有均线且无涨三信号 -> 仅阻止LONG (STRONG_BEAR SHORT仍允许)
    # v13.0: BELOW_ALL_SHORT/ABOVE_ALL_LONG 不命中此分支, 直接透传到仓位计算
    if ma_gate == "BELOW_ALL_BLOCKED" and screen1.direction != Direction.SHORT:
        return Screen2Output(
            timestamp=curr["ts"],
            signal_strength=SignalStrength.NONE,
            signal_score=round(score, 2),
            entry_price=price,
            position_pct=0.0,
            add_on_levels=[],
            tp_target=0.0,
            atr=atr_val,
            volatility=round(volatility, 4),
            addon_suppressed=True,
            ma_zone_gate=ma_gate,
            ma_direction=None,
        )
    elif ma_gate == "BELOW_ALL_BLOCKED":
        # Screen1 is SHORT (STRONG_BEAR) — allow normal V9 flow
        ma_gate = "BREAKOUT_SKIP"

    # v11.0: BLOCKED_LOW_MEC / 未满足连涨跌条件 → 回退V9正常入场 (不再阻止)

    # === 确定有效方向 (MA信号可覆盖Screen1) ===
    effective_direction = ma_direction_override if ma_direction_override is not None else screen1.direction

    # === 仓位计算 (对齐规范) ===
    total_limit = screen1.position_limit_pct
    strength_mult = {
        SignalStrength.STRONG: 1.0,
        SignalStrength.MEDIUM: 0.7,
        SignalStrength.WEAK: 0.4,
        SignalStrength.NONE: 0.2,
    }.get(signal_strength, 0.2)

    effective_total = total_limit * strength_mult * screen1.regime_multiplier
    single_layer_pct = effective_total / 4.0

    # v14.0-A2: RSI过热减仓 (STRONG_BULL + LONG + RSI>75 → 半仓入场)
    if (screen1.regime == "STRONG_BULL" and screen1.direction == Direction.LONG
            and rsi_val is not None and rsi_val > 75):
        single_layer_pct = single_layer_pct * 0.5

    # v11.0: MA区间反向单按MEC评分缩放仓位
    if ma_direction_override is not None and ma_zone_size_mult_val < 1.0:
        single_layer_pct = single_layer_pct * ma_zone_size_mult_val

    # v8.0: 加仓间隔 = addon_gap_pct%×vol_mult 复利 (使用 effective_direction)
    gap = addon_gap_pct / 100.0 * vol_mult
    add_on_levels = []
    if effective_direction == Direction.LONG:
        add_on_levels = [
            round(price * (1 - gap) ** 1, 2),
            round(price * (1 - gap) ** 2, 2),
            round(price * (1 - gap) ** 3, 2),
        ]
        tp_target = round(price * (1 + tp_pct / 100.0 * vol_mult), 2)
    elif effective_direction == Direction.SHORT:
        add_on_levels = [
            round(price * (1 + gap) ** 1, 2),
            round(price * (1 + gap) ** 2, 2),
            round(price * (1 + gap) ** 3, 2),
        ]
        tp_target = round(price * (1 - tp_pct / 100.0 * vol_mult), 2)
    else:
        tp_target = 0.0

    # v7.0 Opt-2: RSI+ATR 加仓抑制 (阈值按代币波动率分档)
    sup_cfg = ADDON_SUPPRESS_THRESHOLDS.get(
        inst_id, ADDON_SUPPRESS_THRESHOLDS["ETH-USDT-SWAP"]
    )
    rsi_val = curr.get("rsi")
    avg_atr_20d = _calc_20d_atr(daily_candles, current_idx)
    atr_expanding = avg_atr_20d > 0 and atr_val > avg_atr_20d * sup_cfg["atr_mult"]
    addon_suppressed = False
    if atr_expanding:
        if effective_direction == Direction.LONG and rsi_val and rsi_val > sup_cfg["rsi_long"]:
            addon_suppressed = True
        elif effective_direction == Direction.SHORT and rsi_val and rsi_val < sup_cfg["rsi_short"]:
            addon_suppressed = True

    return Screen2Output(
        timestamp=curr["ts"],
        signal_strength=signal_strength,
        signal_score=round(score, 2),
        entry_price=price,
        position_pct=round(single_layer_pct, 4),
        add_on_levels=add_on_levels,
        tp_target=tp_target,
        atr=atr_val,
        volatility=round(volatility, 4),
        addon_suppressed=addon_suppressed,
        ma_zone_gate=ma_gate,
        ma_direction=ma_direction_override,
        ma_zone_ref_price=ma_zone_ref_price_val,
        ma_zone_size_mult=ma_zone_size_mult_val,
    )


# ==================== 第三屏: A9离场决策 ====================

def check_exit_signals(
    position: Position,
    daily_candle: Dict,
    screen1: Screen1Output,
    current_equity: float,
    peak_equity: float,
    trade_count: int,
    inst_id: str = "BTC-USDT-SWAP",  # v14.0-B2: ETH L2c定制
) -> Tuple[bool, ExitReason, int]:
    """
    v12.0 离场决策 (四条件)

    返回: (should_exit, exit_reason, -1)  — 全部为全仓平仓 (-1)

    L1a: TP目标触及 (均价+tp_pct%×vol_mult) → 全平
    L1b: 均价止损 (仅 Level3加满后; avg×0.80/×1.20) → 全平
    L2:  Screen1 方向明确反转 (LONG→SHORT 或 SHORT→LONG)
    L2b: Regime对立止链 (v12.0):
         Level=0: 仅 STRONG 对立触发 (SHORT+STRONG_BULL / LONG+STRONG_BEAR)
         Level>=1: WEAK或STRONG 对立均触发 (SHORT+BULL / LONG+BEAR)
    L2c: 链均价提前保护 (v12.0): Level>=2 且未加满时, avg×1.20(SHORT)/×0.80(LONG)
    L4:  最大回撤约束 (20%强制全平)

    已移除: L1-固定SL(未加满时无SL), L1c(移动止盈), L3(风险事件/ATR扩张)
    """
    if position.direction == Direction.WAIT:
        return False, ExitReason.NONE, -1

    high = daily_candle["high"]
    low = daily_candle["low"]

    # --- L1a: 单次全仓止盈 (tp_target 触发) ---
    if position.tp_target > 0:
        if position.direction == Direction.LONG and high >= position.tp_target:
            return True, ExitReason.TAKE_PROFIT_1, -1
        elif position.direction == Direction.SHORT and low <= position.tp_target:
            return True, ExitReason.TAKE_PROFIT_1, -1

    # --- L1b: 均价止损 (v9.0: 仅 Level3加满后激活, stop_loss_price=avg×0.80/×1.20) ---
    if position.is_martin_complete and position.stop_loss_price > 0:
        if position.direction == Direction.LONG and low <= position.stop_loss_price:
            return True, ExitReason.STOP_LOSS, -1
        elif position.direction == Direction.SHORT and high >= position.stop_loss_price:
            return True, ExitReason.STOP_LOSS, -1

    # --- L2: Screen1 方向明确反转 (MA区间单用参考MA突破替代, 避免当日开仓次日立刻被L2关闭) ---
    if position.ma_zone_opened and position.ma_zone_ref_price > 0:
        # MA区间反向单: 参考MA价格被突破则出场 (SHORT=阻力MA被向上突破, LONG=支撑MA被向下跌破)
        close_price = daily_candle["close"]
        if position.direction == Direction.SHORT and close_price > position.ma_zone_ref_price:
            return True, ExitReason.SIGNAL_REVERSAL, -1
        if position.direction == Direction.LONG and close_price < position.ma_zone_ref_price:
            return True, ExitReason.SIGNAL_REVERSAL, -1
    elif position.screen1 and screen1.direction != Direction.WAIT:
        if position.direction == Direction.LONG and screen1.direction == Direction.SHORT:
            return True, ExitReason.SIGNAL_REVERSAL, -1
        if position.direction == Direction.SHORT and screen1.direction == Direction.LONG:
            return True, ExitReason.SIGNAL_REVERSAL, -1

    # --- L2b: Regime对立止链 (v12.0: 防趋势反转时马丁链越陷越深) ---
    # MA区间单跳过L2b (已有自己的参考MA出场逻辑)
    if not position.ma_zone_opened:
        current_regime = screen1.regime
        if position.level >= 1:
            # 已加仓: WEAK或STRONG对立都触发
            if position.direction == Direction.SHORT and current_regime in ("WEAK_BULL", "STRONG_BULL"):
                return True, ExitReason.SIGNAL_REVERSAL, -1
            if position.direction == Direction.LONG and current_regime in ("WEAK_BEAR", "STRONG_BEAR"):
                return True, ExitReason.SIGNAL_REVERSAL, -1
        else:
            # 初始单: 仅STRONG对立触发 (避免震荡市频繁止损)
            if position.direction == Direction.SHORT and current_regime == "STRONG_BULL":
                return True, ExitReason.SIGNAL_REVERSAL, -1
            if position.direction == Direction.LONG and current_regime == "STRONG_BEAR":
                return True, ExitReason.SIGNAL_REVERSAL, -1

    # --- L2c: 链均价提前保护 (v12.0: level>=1 未加满时也启用均价止损) ---
    # 与v9.0 L1b逻辑相同 (avg×1.20/×0.80), 但不等Level3完成即生效
    # 防止第1次加仓后极端反向行情继续叠损 (如ETH 2025-05, 2025-07事件)
    # v14.0-B2: ETH SHORT L2c放宽至avg×1.25 (ETH波动大, 多5%呼吸空间)
    l2c_mult = 1.25 if (inst_id == "ETH-USDT-SWAP" and position.direction == Direction.SHORT) else 1.20
    if position.level >= 1 and not position.is_martin_complete and not position.ma_zone_opened:
        avg = position.entry_price  # recalc_avg_entry已将entry_price更新为加权均价
        if position.direction == Direction.LONG and low <= avg * 0.80:
            return True, ExitReason.STOP_LOSS, -1
        if position.direction == Direction.SHORT and high >= avg * l2c_mult:
            return True, ExitReason.STOP_LOSS, -1

    # --- L4: 最大回撤约束 (20%强制全平) ---
    if peak_equity > 0:
        drawdown = (peak_equity - current_equity) / peak_equity * 100
        if drawdown >= 20:
            return True, ExitReason.DRAWDOWN_LIMIT, -1

    return False, ExitReason.NONE, -1


# ==================== 仓位管理 ====================

def calc_martin_add_on(
    position: Position,
    candle: Dict,
    available_capital: float,
    equity: float,
    taker_fee: float = 0.0005,
    min_score: float = 50.0,
    signal_score: float = 50.0,
) -> Optional[Tuple[float, float]]:
    """
    检查是否触发马丁加仓 (v8.0: 需信号评分门禁 + 等额加仓)

    返回: (add_price, add_size_usd) 或 None
    """
    if position.direction == Direction.WAIT:
        return None
    if position.level >= 3:  # 最多3次加仓
        return None

    # v8.0: 信号强度门禁 (加仓需 Screen2 评分达标)
    if signal_score < min_score:
        return None

    # 检查当前价格是否触发加仓位
    price = candle["close"]
    low = candle["low"]
    high = candle["high"]

    target_level = position.level
    if target_level >= len(position.add_on_levels):
        return None

    target_price = position.add_on_levels[target_level]

    # 检查是否触及
    triggered = False
    if position.direction == Direction.LONG and low <= target_price:
        triggered = True
    elif position.direction == Direction.SHORT and high >= target_price:
        triggered = True

    if not triggered:
        return None

    # === 等额加仓 (规范) ===
    add_size = position.initial_size_usd

    # 累计仓位上限
    total_after_add = position.size_usd + add_size + add_size * taker_fee
    if total_after_add / equity > 0.60:
        add_size = max(equity * 0.60 - position.size_usd, 0) * (1 - taker_fee)
        if add_size < 10:
            return None

    # 检查可用资金
    if add_size * (1 + taker_fee) > available_capital:
        add_size = available_capital / (1 + taker_fee)
        if add_size < 10:
            return None

    return (target_price, round(add_size, 2))



def recalc_avg_entry(
    position: Position,
    add_price: float,
    add_size: float,
    taker_fee: float = 0.0005,
    vol_mult: float = 1.0,
    tp_pct: float = 4.0,
):
    """重新计算平均入场价和止盈目标 (v8.0: TP随均价滚动更新, 无固定SL)"""
    old_total = position.entry_price * position.size_usd
    new_total = add_price * add_size
    total_size = position.size_usd + add_size

    if total_size > 0:
        position.entry_price = (old_total + new_total) / total_size
    position.size_usd = total_size
    position.total_cost += add_size * taker_fee
    position.level += 1

    # v8.0: TP目标 = 新均价 × (1 + tp_pct%×vol_mult)
    tp_gap = tp_pct / 100.0 * vol_mult
    if position.direction == Direction.LONG:
        position.tp_target = round(position.entry_price * (1 + tp_gap), 2)
    elif position.direction == Direction.SHORT:
        position.tp_target = round(position.entry_price * (1 - tp_gap), 2)

    # 马丁完成统计 (Level 3 = 初始 + 3次加仓)
    if position.level >= 3:
        position.is_martin_complete = True
        # v9.0: Level3加满后激活均价止损 (防整链全亏)
        if position.direction == Direction.LONG:
            position.stop_loss_price = round(position.entry_price * 0.80, 2)
        elif position.direction == Direction.SHORT:
            position.stop_loss_price = round(position.entry_price * 1.20, 2)
