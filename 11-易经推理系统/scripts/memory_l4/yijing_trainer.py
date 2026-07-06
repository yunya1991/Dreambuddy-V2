#!/usr/bin/env python3
"""
易经交易推理训练器
基于 OKX 历史行情，对 BCRM 易经推理模型进行回测训练和多场景验证

训练循环：
OKX历史K线 → 构造market_snapshot → BCRM推理 → 模拟交易 → 结果统计 → 两仪学习
"""
import json
import time
import warnings
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore")

from scripts.memory_l4.bcrm.engine import default_engine, BCRMEngine
from scripts.memory_l4.bcrm.output_contract import BCRMOutput
from scripts.memory_l4.bcrm.liangyi_engine import LiangyiEngine
from scripts.memory_l4.bcrm.bagua_engine import BaguaEngine, default_bagua_engine
from scripts.memory_l4.okx_simulated import OKXSimulatedClient

TRAIN_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "training"
TRAIN_DATA_DIR.mkdir(parents=True, exist_ok=True)

from scripts.memory_l4.paths import memory_l4_cases_dir, memory_l4_dir

LIANGYI_STATE_FILE = memory_l4_dir() / "liangyi_state.json"


def _save_cases_to_l4(cases: List[Dict], source: str = "backtest") -> int:
    """
    将回测产生的案例持久化到 L4 案例库（.workbuddy/memory_l4/cases/）。

    Args:
        cases: 案例列表
        source: 来源标识

    Returns:
        成功保存的案例数
    """
    import uuid
    import time

    cases_dir = memory_l4_cases_dir()
    cases_dir.mkdir(parents=True, exist_ok=True)

    saved = 0
    for i, case in enumerate(cases):
        case_id = case.get("case_id") or f"bcrm_backtest_{source}_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        case["case_id"] = case_id
        case["source"] = source
        case["version"] = "v0.2"
        if "ts" not in case:
            case["ts"] = case.get("market_snapshot", {}).get("ts") or ""

        filepath = cases_dir / f"{case_id}.json"
        try:
            with filepath.open("w", encoding="utf-8") as f:
                json.dump(case, f, indent=2, ensure_ascii=False, default=str)
            saved += 1
        except Exception:
            continue

    return saved


@dataclass
class TradeRecord:
    """交易记录"""
    ts: str = ""
    price: float = 0
    direction: str = ""      # UP/DOWN/FLAT
    action: str = ""         # open_long/open_short/hold/close_long/close_short/reduce
    confidence: float = 0.0
    hexagram: str = ""
    stop_loss: float = 0
    take_profit: float = 0
    entry_price: float = 0
    exit_price: float = 0
    pnl: float = 0
    pnl_pct: float = 0
    exit_reason: str = ""    # signal/stop_loss/take_profit/reverse


@dataclass
class ScenarioResult:
    """场景测试结果"""
    name: str = ""
    bar: str = ""
    start_price: float = 0
    end_price: float = 0
    buy_hold_return: float = 0
    total_trades: int = 0
    win_trades: int = 0
    loss_trades: int = 0
    total_pnl: float = 0
    win_rate: float = 0
    max_drawdown: float = 0
    avg_win: float = 0
    avg_loss: float = 0
    profit_factor: float = 0
    trades: List[Dict] = field(default_factory=list)


def _kline_to_snapshot(kline_data: List[Dict], idx: int = 0) -> Dict:
    """
    将 K 线数据转换为 BCRM 需要的 market_snapshot

    Args:
        kline_data: K线数组（按时间倒序，0=最新）
        idx: 当前索引（从最新算起）
    """
    if not kline_data or idx >= len(kline_data):
        return {}

    current = kline_data[idx]
    price = current["c"]

    # 收集多周期数据
    lookback_short = min(5, len(kline_data) - idx)
    lookback_med = min(20, len(kline_data) - idx)
    lookback_long = min(60, len(kline_data) - idx)

    closes_short = [kline_data[i]["c"] for i in range(idx, idx + lookback_short)]
    closes_med = [kline_data[i]["c"] for i in range(idx, idx + lookback_med)]
    closes_long = [kline_data[i]["c"] for i in range(idx, idx + lookback_long)]
    highs = [kline_data[i]["h"] for i in range(idx, idx + lookback_med)]
    lows = [kline_data[i]["l"] for i in range(idx, idx + lookback_med)]
    volumes = [kline_data[i]["v"] for i in range(idx, idx + lookback_short)]

    high = max(highs)
    low = min(lows)

    # 计算均线方向
    ma_short = sum(closes_short) / len(closes_short) if closes_short else price
    ma_med = sum(closes_med) / len(closes_med) if closes_med else price
    ma_long = sum(closes_long) / len(closes_long) if closes_long else price

    # 涨跌幅（短期/中期）
    prev_close = kline_data[idx + 1]["c"] if idx + 1 < len(kline_data) else price
    change_pct = (price - prev_close) / prev_close if prev_close else 0

    # 中期涨跌幅
    med_change = (price - closes_med[-1]) / closes_med[-1] if closes_med[-1] else 0

    # 波动率（ATR 简化版）
    atr_vals = []
    for i in range(idx, idx + min(14, len(kline_data) - idx)):
        k = kline_data[i]
        tr = max(k["h"] - k["l"], abs(k["h"] - (kline_data[i+1]["c"] if i+1 < len(kline_data) else k["c"])),
                 abs(k["l"] - (kline_data[i+1]["c"] if i+1 < len(kline_data) else k["c"])))
        if k["c"]:
            atr_vals.append(tr / k["c"])
    volatility = sum(atr_vals) / len(atr_vals) if atr_vals else 0.02
    volatility = max(0.005, min(volatility, 0.20))

    # 价格位置（相对近期高低点）
    if high > low:
        price_position = (price - low) / (high - low)
    else:
        price_position = 0.5

    # 成交量变化
    avg_vol = sum(volumes) / len(volumes) if volumes else 1
    cur_vol = current["v"]
    volume_ratio = cur_vol / avg_vol if avg_vol else 1.0
    volume_ratio = max(0.3, min(volume_ratio, 5.0))

    # ── 四维评分（基于价格行为构造） ──

    # 1. 供需评分：均线排列 + 价格相对位置
    ma_bullish = (price > ma_short > ma_med > ma_long)
    ma_bearish = (price < ma_short < ma_med < ma_long)
    if ma_bullish:
        sd_score = 0.8 + min(change_pct * 5, 0.15)
    elif ma_bearish:
        sd_score = 0.2 + min(change_pct * 5, -0.15)
    else:
        # 部分排列
        if price > ma_med:
            sd_score = 0.55 + change_pct * 3
        else:
            sd_score = 0.45 + change_pct * 3
    sd_score = max(0.15, min(sd_score, 0.85))

    # 2. 技术评分：动量 + 突破
    momentum = med_change * 8  # 中期动量放大
    # 突破加分
    breakout = 0
    if price > high * 0.98 and change_pct > 0:
        breakout = 0.15
    elif price < low * 1.02 and change_pct < 0:
        breakout = -0.15
    tech_score = 0.5 + momentum + breakout
    tech_score = max(0.15, min(tech_score, 0.85))

    # 3. 资金评分：量价配合
    if change_pct > 0 and volume_ratio > 1.2:
        cf_score = 0.7 + min(volume_ratio * 0.05, 0.15)
    elif change_pct < 0 and volume_ratio > 1.2:
        cf_score = 0.3 - min(volume_ratio * 0.05, 0.15)
    elif change_pct > 0 and volume_ratio < 0.8:
        cf_score = 0.55  # 缩量上涨，怀疑
    elif change_pct < 0 and volume_ratio < 0.8:
        cf_score = 0.45  # 缩量下跌，怀疑
    else:
        cf_score = 0.5 + change_pct * 2
    cf_score = max(0.15, min(cf_score, 0.85))

    # 4. 情绪评分：波动率 + 极值位置
    if price_position > 0.8 and volatility > 0.03:
        sent_score = 0.7  # 高位高波动 = 贪婪
    elif price_position < 0.2 and volatility > 0.03:
        sent_score = 0.3  # 低位高波动 = 恐慌
    else:
        sent_score = 0.4 + price_position * 0.4
    sent_score = max(0.15, min(sent_score, 0.85))

    # 趋势强度：均线偏离度 + 波动率
    ma_dev = abs(price - ma_med) / ma_med if ma_med else 0
    trend_strength = min(ma_dev * 10 + volatility * 3, 0.9)
    trend_strength = max(0.1, trend_strength)

    return {
        "snapshot_ts": current.get("ts_str", datetime.now(timezone.utc).isoformat()),
        "price": price,
        "symbol": "BTC-USDT-SWAP",
        "market_scale": 0.7,
        "supply_demand_score": sd_score,
        "technical_score": tech_score,
        "capital_flow_score": cf_score,
        "sentiment_score": sent_score,
        "trend_strength": trend_strength,
        "volatility": volatility,
        "volume_ratio": volume_ratio,
        "price_position": price_position,
        "change_pct": change_pct,
        "med_change_pct": med_change,
        "high": high,
        "low": low,
        "ma_short": ma_short,
        "ma_med": ma_med,
        "ma_long": ma_long,
    }


def _build_contradiction_list(snapshot: Dict) -> List[Dict]:
    """根据市场快照构造矛盾列表（多维度矛盾）"""
    contradictions = []
    price_pos = snapshot.get("price_position", 0.5)
    trend_str = snapshot.get("trend_strength", 0.5)
    vol = snapshot.get("volatility", 0.03)
    change = snapshot.get("change_pct", 0)
    med_change = snapshot.get("med_change_pct", 0)
    vol_ratio = snapshot.get("volume_ratio", 1.0)
    sd = snapshot.get("supply_demand_score", 0.5)
    tech = snapshot.get("technical_score", 0.5)
    cf = snapshot.get("capital_flow_score", 0.5)
    sent = snapshot.get("sentiment_score", 0.5)

    # 主矛盾：趋势方向
    if change > 0.01:
        thesis = "多头动能释放，趋势向上"
        antithesis = "短期超买，回调压力增大"
        tension = 0.4 + trend_str * 0.4
    elif change < -0.01:
        thesis = "空头动能释放，趋势向下"
        antithesis = "短期超卖，反弹预期增强"
        tension = 0.4 + trend_str * 0.4
    else:
        thesis = "多空平衡，震荡整理"
        antithesis = "方向选择临近，变盘在即"
        tension = 0.3 + vol * 5

    tension = max(0.2, min(tension, 0.85))
    consistency = 0.5 + abs(sd - 0.5) + abs(tech - 0.5)
    consistency = max(0.3, min(consistency, 0.9))
    contradictions.append({
        "thesis": thesis,
        "antithesis": antithesis,
        "subject": "BTC趋势方向",
        "tension": tension,
        "consistency": consistency,
    })

    # 次矛盾：量价关系
    if change > 0 and vol_ratio > 1.2:
        thesis = "放量上涨，资金持续流入"
        antithesis = "量能过大，警惕阶段性顶部"
        contradictions.append({
            "thesis": thesis, "antithesis": antithesis,
            "subject": "量价配合", "tension": 0.5 + vol_ratio * 0.1,
            "consistency": 0.6,
        })
    elif change < 0 and vol_ratio > 1.2:
        thesis = "放量下跌，恐慌情绪蔓延"
        antithesis = "恐慌出尽后或迎反弹"
        contradictions.append({
            "thesis": thesis, "antithesis": antithesis,
            "subject": "量价配合", "tension": 0.5 + vol_ratio * 0.1,
            "consistency": 0.6,
        })
    elif change > 0 and vol_ratio < 0.8:
        thesis = "缩量上涨，抛压较轻"
        antithesis = "缺乏量能支撑，上涨难持续"
        contradictions.append({
            "thesis": thesis, "antithesis": antithesis,
            "subject": "量价配合", "tension": 0.4,
            "consistency": 0.4,
        })
    elif change < 0 and vol_ratio < 0.8:
        thesis = "缩量下跌，杀跌动能不足"
        antithesis = "买盘低迷，继续阴跌"
        contradictions.append({
            "thesis": thesis, "antithesis": antithesis,
            "subject": "量价配合", "tension": 0.4,
            "consistency": 0.4,
        })

    # 第三矛盾：中期 vs 短期
    if med_change > 0.05 and change < -0.005:
        thesis = "中期上升趋势完好"
        antithesis = "短期调整，考验支撑"
        contradictions.append({
            "thesis": thesis, "antithesis": antithesis,
            "subject": "多周期共振", "tension": 0.5,
            "consistency": 0.5,
        })
    elif med_change < -0.05 and change > 0.005:
        thesis = "中期下降趋势完好"
        antithesis = "短期反弹，测试压力"
        contradictions.append({
            "thesis": thesis, "antithesis": antithesis,
            "subject": "多周期共振", "tension": 0.5,
            "consistency": 0.5,
        })

    # 第四矛盾：情绪极值
    if price_pos > 0.85 and vol > 0.04:
        thesis = "市场极度亢奋，FOMO情绪"
        antithesis = "物极必反，警惕顶部"
        contradictions.append({
            "thesis": thesis, "antithesis": antithesis,
            "subject": "市场情绪", "tension": 0.7,
            "consistency": 0.7,
        })
    elif price_pos < 0.15 and vol > 0.04:
        thesis = "市场极度恐慌，抛售情绪"
        antithesis = "否极泰来，底部临近"
        contradictions.append({
            "thesis": thesis, "antithesis": antithesis,
            "subject": "市场情绪", "tension": 0.7,
            "consistency": 0.7,
        })

    return contradictions


def _contradictions_to_bcrm_format(contradictions: List[Dict], snapshot: Dict) -> List[Dict]:
    """
    将辩证矛盾格式（thesis/antithesis/tension）转换为 BCRM 引擎兼容格式
    （id/dominant_side/direction/intensity/confidence/type）。

    每个矛盾根据 snapshot 中的四维评分和价格变化推断主导方和方向。
    """
    bcrm_contradictions = []
    change = snapshot.get("change_pct", 0)
    sd = snapshot.get("supply_demand_score", 0.5)
    tech = snapshot.get("technical_score", 0.5)
    cf = snapshot.get("capital_flow_score", 0.5)
    sent = snapshot.get("sentiment_score", 0.5)

    type_map = {
        "BTC趋势方向": "trend_countertrend",
        "量价配合": "volume_price",
        "多周期共振": "trend_countertrend",
        "市场情绪": "sentiment_fear_greed",
    }

    for i, c in enumerate(contradictions):
        subject = c.get("subject", f"contradiction_{i}")
        tension = c.get("tension", 0.5)
        consistency = c.get("consistency", 0.5)

        # 计算综合多空偏向（-1 ~ 1）
        bias = 0
        if "趋势方向" in subject or "多周期" in subject:
            bias = change * 50  # 涨跌幅放大
            bias += (tech - 0.5) * 2
            bias += (cf - 0.5) * 2
        elif "量价" in subject:
            bias = (sd - 0.5) * 2
            bias += (cf - 0.5) * 1.5
        elif "情绪" in subject:
            bias = (sent - 0.5) * 3

        bias = max(-1.0, min(1.0, bias))

        if bias > 0.1:
            dominant = "BULL"
            direction = "UP"
        elif bias < -0.1:
            dominant = "BEAR"
            direction = "DOWN"
        else:
            dominant = "EQUAL"
            direction = "NEUTRAL"

        intensity = tension  # 0~1
        confidence = consistency  # 0~1

        bcrm_contradictions.append({
            "id": f"c{i}_{subject}",
            "type": type_map.get(subject, "supply_demand"),
            "dominant_side": dominant,
            "direction": direction,
            "intensity": round(intensity, 4),
            "confidence": round(confidence, 4),
            "tension": tension,
            "thesis": c.get("thesis", ""),
            "antithesis": c.get("antithesis", ""),
            "subject": subject,
        })

    return bcrm_contradictions


def _load_kline_from_okx(inst_id: str = "BTC-USDT-SWAP",
                         bar: str = "4H",
                         limit: int = 200) -> List[Dict]:
    """从 OKX 获取 K 线数据"""
    client = OKXSimulatedClient()
    result = client.get_kline(inst_id=inst_id, bar=bar, limit=limit)
    if not result.get("ok"):
        return []
    candles = result.get("candles", [])
    # 转换为统一格式
    formatted = []
    for c in candles:
        ts = c.get("ts", 0)
        formatted.append({
            "ts": ts,
            "ts_str": datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat() if ts else "",
            "o": c.get("o", 0),
            "h": c.get("h", 0),
            "l": c.get("l", 0),
            "c": c.get("c", 0),
            "v": c.get("vol", 0),
        })
    return formatted


def _get_hexagram_risk_level(hexagram_name_cn: str) -> float:
    """
    根据卦象评估风险等级（返回风险系数，0~1，越高越危险）
    基于卦象含义的简化评估
    """
    good_gua = [
        "乾为天", "坤为地", "水雷屯", "山水蒙", "水天需", "地水师",
        "水地比", "风天小畜", "天泽履", "地天泰", "天地否", "天火同人",
        "火天大有", "地山谦", "雷地豫", "泽雷随", "山风蛊", "地泽临",
        "风地观", "火雷噬嗑", "山火贲", "山地剥", "地雷复", "天雷无妄",
        "山天大畜", "山雷颐", "泽风大过", "坎为水", "离为火", "泽山咸",
        "雷风恒", "天山遁", "雷天大壮", "火地晋", "地火明夷", "风火家人",
        "火泽睽", "水山蹇", "雷水解", "山泽损", "风雷益", "泽天夬",
        "天风姤", "泽地萃", "地风升", "泽水困", "水风井", "泽火革",
        "火风鼎", "震为雷", "艮为山", "风山渐", "雷泽归妹", "雷火丰",
        "火山旅", "巽为风", "兑为泽", "风水涣", "水泽节", "风泽中孚",
        "雷山小过", "水火既济", "火水未济",
    ]
    bad_gua = [
        "坎为水", "山地剥", "天地否", "泽风大过", "火水未济", "山雷颐",
        "水山蹇", "泽水困", "雷山小过", "地火明夷", "火地晋", "天风姤",
    ]
    if hexagram_name_cn in bad_gua:
        return 0.8
    elif hexagram_name_cn in good_gua:
        return 0.3
    else:
        return 0.5


def _build_research_contradictions(snapshot: Dict) -> List[Dict]:
    """
    构造 A 系列研报矛盾输入（模拟研报数据）
    从宏观面、资金面、消息面生成多维度矛盾
    """
    contradictions = []
    price = snapshot.get("price", 0)
    med_change = snapshot.get("med_change_pct", 0)
    volatility = snapshot.get("volatility", 0.02)
    trend_str = snapshot.get("trend_strength", 0.5)

    # 宏观矛盾：货币政策 vs 经济预期
    if med_change > 0.03:
        thesis = "宏观流动性宽松，持续推高风险资产"
        antithesis = "经济复苏不及预期，上涨缺乏基本面支撑"
        tension = 0.5 + trend_str * 0.2
    elif med_change < -0.03:
        thesis = "宏观紧缩预期升温，风险资产承压"
        antithesis = "政策底已现，估值修复行情临近"
        tension = 0.5 + trend_str * 0.2
    else:
        thesis = "宏观政策中性偏暖，市场底部抬升"
        antithesis = "经济数据疲弱，上行动能不足"
        tension = 0.4
    contradictions.append({
        "thesis": thesis, "antithesis": antithesis,
        "subject": "宏观政策面", "tension": tension, "consistency": 0.55,
    })

    # 资金面矛盾：机构资金 vs 散户情绪
    if volatility > 0.04:
        thesis = "机构资金逢低布局，长线资金入场"
        antithesis = "散户恐慌抛售，短期流动性风险"
        contradictions.append({
            "thesis": thesis, "antithesis": antithesis,
            "subject": "资金面博弈", "tension": 0.6, "consistency": 0.5,
        })
    elif med_change > 0.05:
        thesis = "资金持续流入，趋势加速"
        antithesis = "获利盘积累，回调风险增加"
        contradictions.append({
            "thesis": thesis, "antithesis": antithesis,
            "subject": "资金面博弈", "tension": 0.55, "consistency": 0.6,
        })

    # 链上数据矛盾：链上活跃 vs 价格反应
    if trend_str > 0.5:
        thesis = "链上活跃度上升，基本面支撑强劲"
        antithesis = "链上数据滞后，价格或已提前反映"
        contradictions.append({
            "thesis": thesis, "antithesis": antithesis,
            "subject": "链上基本面", "tension": 0.45, "consistency": 0.45,
        })

    return contradictions


def _calc_triple_screen_score(closes: List[float]) -> Dict:
    """
    计算三屏马丁评分（Screen1: 7维评分）
    从 screen_martin_bridge 核心逻辑提取，作为额外信号源
    """
    if not closes or len(closes) < 30:
        return {"ok": False, "error": "not enough data"}

    price = closes[-1]

    def sma(vals, period):
        if len(vals) < period:
            return None
        return sum(vals[-period:]) / period

    def rsi(closes_, period=14):
        if len(closes_) < period + 1:
            return 50
        gains, losses = [], []
        for i in range(1, len(closes_)):
            d = closes_[i] - closes_[i - 1]
            gains.append(max(d, 0))
            losses.append(max(-d, 0))
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    ma5 = sma(closes, 5) or price
    ma20 = sma(closes, 20) or price
    ma60 = sma(closes, 60) or price if len(closes) >= 60 else price

    tech_score = 0
    if price > ma5:
        tech_score += 20
    if price > ma20:
        tech_score += 20
    if ma5 > ma20:
        tech_score += 20
    if price > ma60:
        tech_score += 20
    rsi_val = rsi(closes, 14)
    tech_score += int(20 * (rsi_val / 100))

    # 波动率（链上评分的简化）
    vol_20 = 0
    if len(closes) >= 20:
        rets = [(closes[i] - closes[i-1]) / closes[i-1]
                for i in range(1, len(closes[-20:]))]
        vol_20 = (sum(r**2 for r in rets) / len(rets)) ** 0.5 * 100 * (365 ** 0.5)
    onchain_score = max(0, 100 - int(vol_20 * 2))

    # 周期评分（简化：用价格位置模拟）
    mom_30d = (price / closes[-31] - 1) * 100 if len(closes) > 30 else 0
    cycle_score = max(0, min(100, int(50 + mom_30d * 2)))

    # 综合评分
    dimensions = [
        ("technical", tech_score, 40),
        ("onchain", onchain_score, 15),
        ("cycle", cycle_score, 10),
        ("macro", max(0, min(100, int(50 + mom_30d * 1.5))), 10),
        ("sentiment", int(50 + (rsi_val - 50) * 0.5), 5),
    ]
    total_weight = sum(d[2] for d in dimensions)
    weighted_score = sum(d[1] * d[2] for d in dimensions) / total_weight

    direction = "BULLISH" if weighted_score > 55 else (
        "BEARISH" if weighted_score < 45 else "NEUTRAL")

    return {
        "ok": True,
        "total_score": round(weighted_score, 1),
        "direction": direction,
        "tech_score": tech_score,
        "onchain_score": onchain_score,
        "cycle_score": cycle_score,
        "rsi": round(rsi_val, 1),
        "ma5": round(ma5, 2),
        "ma20": round(ma20, 2),
        "ma60": round(ma60, 2),
    }


def _detect_ranging_market(snapshot: Dict, closes: List[float] = None) -> Dict:
    """
    震荡市识别
    返回: {is_ranging, range_high, range_low, range_width, adx, squeeze_count}
    """
    price = snapshot.get("price", 0)
    volatility = snapshot.get("volatility", 0.02)
    med_change = abs(snapshot.get("med_change_pct", 0))
    trend_str = snapshot.get("trend_strength", 0.5)

    # 特征1：波动率低
    low_vol = volatility < 0.025
    # 特征2：中期涨跌幅小
    small_range = med_change < 0.03
    # 特征3：趋势强度弱
    weak_trend = trend_str < 0.35

    # 布林带收窄检测（如果有收盘价数据）
    squeeze = False
    range_high = price * 1.02
    range_low = price * 0.98
    if closes and len(closes) >= 20:
        ma20 = sum(closes[-20:]) / 20
        std20 = (sum((c - ma20) ** 2 for c in closes[-20:]) / 20) ** 0.5
        boll_width = (std20 * 2) / ma20 if ma20 else 0
        squeeze = boll_width < 0.03  # 布林带宽度 < 3%
        range_high = ma20 + std20 * 2
        range_low = ma20 - std20 * 2

    # 综合判断：满足 2 个以上特征即为震荡市
    score = sum([low_vol, small_range, weak_trend, squeeze])
    is_ranging = score >= 2

    range_width = (range_high - range_low) / price if price else 0.04

    return {
        "is_ranging": is_ranging,
        "range_high": range_high,
        "range_low": range_low,
        "range_width": range_width,
        "confidence": score / 4,
        "low_volatility": low_vol,
        "small_range": small_range,
        "weak_trend": weak_trend,
        "boll_squeeze": squeeze,
    }


def _grid_trade_decision(price: float, grid_state: Dict, ranging_info: Dict) -> Dict:
    """
    震荡市网格交易决策
    在震荡区间内高抛低吸
    """
    if not grid_state.get("active"):
        # 初始化网格
        grid_state["active"] = True
        grid_state["range_high"] = ranging_info["range_high"]
        grid_state["range_low"] = ranging_info["range_low"]
        grid_state["levels"] = 5
        grid_state["filled_levels"] = []
        grid_state["base_position"] = 0

    range_high = grid_state["range_high"]
    range_low = grid_state["range_low"]
    range_width = range_high - range_low
    level_size = range_width / grid_state["levels"] if range_width else 0

    # 判断当前价格所在网格位置（0=底部，levels=顶部）
    current_level = int((price - range_low) / level_size) if level_size else 2
    current_level = max(0, min(grid_state["levels"], current_level))

    action = "HOLD"
    target_pct = 0

    # 网格策略：越跌越买，越涨越卖
    if current_level <= 1 and len(grid_state["filled_levels"]) < grid_state["levels"]:
        action = "LONG_GRID"
        target_pct = 0.05 * (grid_state["levels"] - current_level)
    elif current_level >= grid_state["levels"] - 1 and grid_state["filled_levels"]:
        action = "SHORT_GRID"
        target_pct = 0.05 * len(grid_state["filled_levels"])

    return {
        "action": action,
        "current_level": current_level,
        "range_high": range_high,
        "range_low": range_low,
        "target_position_pct": target_pct,
    }




def _simulate_trade_pnl(entries: List[Dict], current_price: float,
                        stop_loss: float, take_profit: float,
                        direction: str) -> Tuple[bool, bool, float]:
    """
    简化盈亏计算：判断是否触发止损止盈

    Returns:
        (sl_hit, tp_hit, pnl_pct)
    """
    if not entries:
        return False, False, 0

    avg_entry = sum(e["price"] for e in entries) / len(entries)
    qty = sum(e["qty"] for e in entries)

    if direction == "long":
        pnl_pct = (current_price - avg_entry) / avg_entry
        sl_hit = current_price <= stop_loss if stop_loss else False
        tp_hit = current_price >= take_profit if take_profit else False
    else:
        pnl_pct = (avg_entry - current_price) / avg_entry
        sl_hit = current_price >= stop_loss if stop_loss else False
        tp_hit = current_price <= take_profit if take_profit else False

    return sl_hit, tp_hit, pnl_pct


def run_backtest(scenario_name: str, kline_data: List[Dict],
                 engine: BCRMEngine = None,
                 start_idx: int = 20, end_idx: int = None,
                 initial_capital: float = 10000,
                 position_pct: float = 0.1,
                 slippage: float = 0.0005) -> ScenarioResult:
    """
    运行回测

    Args:
        scenario_name: 场景名称
        kline_data: K线数据（倒序，0=最新）
        engine: BCRM引擎实例
        start_idx: 起始K线索引（跳过前N根用于计算指标）
        end_idx: 结束K线索引
        initial_capital: 初始资金
        position_pct: 单笔仓位占资金比例
        slippage: 滑点

    Returns:
        ScenarioResult
    """
    if engine is None:
        engine = default_engine()

    if end_idx is None:
        end_idx = len(kline_data) - 1

    result = ScenarioResult(name=scenario_name)
    result.bar = "4H"
    result.start_price = kline_data[end_idx]["c"] if end_idx < len(kline_data) else 0
    result.end_price = kline_data[start_idx]["c"] if start_idx < len(kline_data) else 0
    result.buy_hold_return = (result.end_price - result.start_price) / result.start_price if result.start_price else 0

    capital = initial_capital
    peak_capital = capital
    max_drawdown = 0
    total_pnl = 0
    win_trades = 0
    loss_trades = 0
    total_win = 0
    total_loss = 0
    all_trades = []

    # 当前持仓状态
    position = {
        "direction": "",   # long / short / ""
        "entries": [],     # [{price, qty}]
        "stop_loss": 0,
        "take_profit": 0,
        "entry_price": 0,
        "hexagram": "",
    }

    # 两仪引擎（用于在线学习）—— 使用传入 engine 的实例，确保学习结果持久化
    liangyi_engine = engine.liangyi_engine if engine else LiangyiEngine()
    learning_cases = []  # 积累的学习案例

    # 八卦力学引擎（第一性原理计算）
    bagua_engine = BaguaEngine()

    # 震荡市网格交易状态
    grid_state = {"active": False}
    use_grid_strategy = False  # 是否启用网格模式

    # 从旧到新遍历（end_idx 是最旧的，start_idx 是最新的）
    for i in range(end_idx, start_idx - 1, -1):
        if i >= len(kline_data):
            continue

        snapshot = _kline_to_snapshot(kline_data, idx=i)

        # --- 增强1: 三屏马丁评分注入快照 ---
        closes_window = [kline_data[j]["c"] for j in range(
            i, min(i + 60, len(kline_data)))]
        screen_score = _calc_triple_screen_score(closes_window)
        if screen_score.get("ok"):
            snapshot["triple_screen_score"] = screen_score["total_score"]
            snapshot["triple_screen_direction"] = screen_score["direction"]
            snapshot["screen_tech_score"] = screen_score["tech_score"]
            snapshot["screen_onchain_score"] = screen_score["onchain_score"]
            snapshot["screen_rsi"] = screen_score["rsi"]

        # --- 增强2: 构建矛盾列表（技术 + 研报） ---
        contradictions = _build_contradiction_list(snapshot)
        research_contras = _build_research_contradictions(snapshot)
        contradictions.extend(research_contras)

        # --- 增强3: 震荡市识别 ---
        ranging_info = _detect_ranging_market(snapshot, closes_window)
        snapshot["is_ranging"] = ranging_info["is_ranging"]
        snapshot["ranging_confidence"] = ranging_info["confidence"]

        qmm_output = {"uncertainty": 0.3}

        try:
            bcrm_result = engine.infer(
                market_snapshot=snapshot,
                contradiction_list=contradictions,
                qmm_output=qmm_output,
            )
        except Exception:
            continue

        direction = bcrm_result.next_state.direction
        confidence = bcrm_result.next_state.confidence
        hex_cn = bcrm_result.hexagram.hexagram_name_cn or bcrm_result.hexagram.hexagram_name
        fail_closed = bcrm_result.is_fail_closed()

        # --- 增强: 八卦力学引擎（第一性原理校验）---
        try:
            # 获取K线窗口（旧→新）
            closes_window = [kline_data[j]["c"] for j in range(
                i, min(i + 60, len(kline_data)))]
            volumes_window = [kline_data[j].get("vol", kline_data[j].get("v", 0))
                              for j in range(i, min(i + 60, len(kline_data)))]

            bagua_result = bagua_engine.infer(
                snapshot=snapshot,
                closes=closes_window,
                volumes=volumes_window,
            )

            # 八卦力学方向
            bagua_dir = bagua_result.primary_direction
            bagua_conf = bagua_result.primary_confidence

            # 方向映射
            bcrm_dir_num = 1 if direction == "UP" else (-1 if direction == "DOWN" else 0)
            bagua_dir_num = 1 if bagua_dir == "long" else (-1 if bagua_dir == "short" else 0)

            # 融合：
            # 1. 方向一致则提高置信度，不一致则降低
            # 2. 八卦力学作为第一性原理，权重更高（0.6 vs 0.4）
            if bcrm_dir_num != 0 and bagua_dir_num != 0:
                if bcrm_dir_num == bagua_dir_num:
                    # 共振：大幅提升置信度
                    confidence = min(0.95, confidence * 0.5 + bagua_conf * 0.5 + 0.1)
                else:
                    # 背离：大幅降低置信度
                    confidence = confidence * 0.4
                    # 如果八卦力学置信度远高于 BCRM，跟随八卦方向
                    if bagua_conf > confidence + 0.2:
                        direction = "UP" if bagua_dir == "long" else "DOWN"
                        confidence = bagua_conf * 0.7
            elif bcrm_dir_num == 0 and bagua_dir_num != 0:
                # BCRM 无方向但八卦有方向，跟随八卦
                direction = "UP" if bagua_dir == "long" else "DOWN"
                confidence = bagua_conf * 0.6
            elif bagua_dir_num == 0 and bcrm_dir_num != 0:
                # 八卦中立，BCRM 有方向，降低置信度
                confidence = confidence * 0.7

            # 如果八卦引擎算出了六十四卦名，优先使用
            if bagua_result.hexagram_name_cn:
                hex_cn = bagua_result.hexagram_name_cn

        except Exception as e:
            # 八卦引擎失败不影响主流程
            pass

        # 获取 B1 主路径风控参数
        sl_px = 0
        tp_px = 0
        reduce_ratio = 0
        if bcrm_result.strategy_branches:
            b1 = next((b for b in bcrm_result.strategy_branches
                       if b.branch_id == "B1"), None)
            if b1:
                sl_px = b1.stop_loss_px
                tp_px = b1.take_profit_px
                reduce_ratio = b1.reduce_ratio

        price = snapshot["price"]
        ts = snapshot["snapshot_ts"]

        # ── 检查止盈止损 ──
        if position["direction"]:
            sl_hit, tp_hit, pnl_pct = _simulate_trade_pnl(
                position["entries"], price,
                position["stop_loss"], position["take_profit"],
                position["direction"])

            if sl_hit:
                # 止损
                qty = sum(e["qty"] for e in position["entries"])
                entry_px = sum(e["price"] * e["qty"] for e in position["entries"]) / qty
                pnl = (price - entry_px) * qty if position["direction"] == "long" else (entry_px - price) * qty
                pnl_with_slip = pnl - price * qty * slippage
                capital += pnl_with_slip

                all_trades.append({
                    "ts": ts, "price": price, "action": "stop_loss",
                    "direction": position["direction"], "hexagram": position["hexagram"],
                    "entry_price": entry_px, "exit_price": price,
                    "pnl": pnl_with_slip, "pnl_pct": pnl_pct,
                    "exit_reason": "stop_loss",
                })
                loss_trades += 1
                total_loss += abs(pnl_with_slip)
                position = {"direction": "", "entries": [], "stop_loss": 0,
                            "take_profit": 0, "entry_price": 0, "hexagram": ""}

            elif tp_hit:
                # 止盈
                qty = sum(e["qty"] for e in position["entries"])
                entry_px = sum(e["price"] * e["qty"] for e in position["entries"]) / qty
                pnl = (price - entry_px) * qty if position["direction"] == "long" else (entry_px - price) * qty
                pnl_with_slip = pnl - price * qty * slippage
                capital += pnl_with_slip

                all_trades.append({
                    "ts": ts, "price": price, "action": "take_profit",
                    "direction": position["direction"], "hexagram": position["hexagram"],
                    "entry_price": entry_px, "exit_price": price,
                    "pnl": pnl_with_slip, "pnl_pct": pnl_pct,
                    "exit_reason": "take_profit",
                })
                win_trades += 1
                total_win += pnl_with_slip
                position = {"direction": "", "entries": [], "stop_loss": 0,
                            "take_profit": 0, "entry_price": 0, "hexagram": ""}

        # ── 根据 BCRM 信号交易 ──
        if fail_closed or confidence < 0.25:
            continue

        # --- 增强4: 三屏马丁信号一致性校验 ---
        screen_dir = snapshot.get("triple_screen_direction", "NEUTRAL")
        bcrm_dir_num = 1 if direction == "UP" else (-1 if direction == "DOWN" else 0)
        screen_dir_num = 1 if screen_dir == "BULLISH" else (-1 if screen_dir == "BEARISH" else 0)
        # 方向一致则增强置信度，不一致则削弱
        if bcrm_dir_num != 0 and screen_dir_num != 0:
            if bcrm_dir_num == screen_dir_num:
                confidence = min(0.95, confidence * 1.15)
            else:
                confidence = confidence * 0.75

        # --- 增强5: 震荡市处理 ---
        is_ranging = ranging_info.get("is_ranging", False)
        if is_ranging and ranging_info.get("confidence", 0) > 0.5:
            # 震荡市模式：
            # 1. 提高开仓置信度门槛
            if confidence < 0.45:
                continue
            # 2. 降低单笔仓位
            grid_pos_pct = position_pct * 0.6
            # 3. 缩小止损止盈（贴近震荡区间边界）
            range_width = ranging_info.get("range_width", 0.04)
            if sl_px and tp_px:
                # 震荡市中止损止盈更紧凑
                pass
        else:
            grid_pos_pct = position_pct

        # 趋势过滤：震荡市中提高置信度要求
        med_change = snapshot.get("med_change_pct", 0)
        if abs(med_change) < 0.02 and confidence < 0.4:
            continue

        if direction == "UP" and not position["direction"]:
            # 开多
            qty = (capital * grid_pos_pct) / price
            entry_px = price * (1 + slippage)
            position = {
                "direction": "long",
                "entries": [{"price": entry_px, "qty": qty}],
                "stop_loss": sl_px,
                "take_profit": tp_px,
                "entry_price": entry_px,
                "hexagram": hex_cn,
            }
            all_trades.append({
                "ts": ts, "price": entry_px, "action": "open_long",
                "direction": "long", "hexagram": hex_cn,
                "entry_price": entry_px, "exit_price": 0,
                "pnl": 0, "pnl_pct": 0, "exit_reason": "",
                "confidence": confidence, "stop_loss": sl_px, "take_profit": tp_px,
                "liangyi_state": bcrm_result.liangyi_state,
                "scale_params": bcrm_result.scale_params,
            })

        elif direction == "DOWN" and not position["direction"]:
            # 开空
            qty = (capital * grid_pos_pct) / price
            entry_px = price * (1 - slippage)
            position = {
                "direction": "short",
                "entries": [{"price": entry_px, "qty": qty}],
                "stop_loss": sl_px,
                "take_profit": tp_px,
                "entry_price": entry_px,
                "hexagram": hex_cn,
            }
            all_trades.append({
                "ts": ts, "price": entry_px, "action": "open_short",
                "direction": "short", "hexagram": hex_cn,
                "entry_price": entry_px, "exit_price": 0,
                "pnl": 0, "pnl_pct": 0, "exit_reason": "",
                "confidence": confidence, "stop_loss": sl_px, "take_profit": tp_px,
                "liangyi_state": bcrm_result.liangyi_state,
                "scale_params": bcrm_result.scale_params,
            })

        elif direction == "FLAT" and position["direction"]:
            # 信号反转 → 平仓
            qty = sum(e["qty"] for e in position["entries"])
            entry_px = sum(e["price"] * e["qty"] for e in position["entries"]) / qty
            pnl = (price - entry_px) * qty if position["direction"] == "long" else (entry_px - price) * qty
            pnl_with_slip = pnl - price * qty * slippage
            capital += pnl_with_slip

            exit_reason = "signal_flat"
            pnl_pct = pnl_with_slip / (entry_px * qty) if entry_px * qty else 0

            all_trades.append({
                "ts": ts, "price": price,
                "action": f"close_{position['direction']}",
                "direction": position["direction"],
                "hexagram": position["hexagram"],
                "entry_price": entry_px, "exit_price": price,
                "pnl": pnl_with_slip, "pnl_pct": pnl_pct,
                "exit_reason": exit_reason,
            })
            if pnl_with_slip >= 0:
                win_trades += 1
                total_win += pnl_with_slip
            else:
                loss_trades += 1
                total_loss += abs(pnl_with_slip)
            position = {"direction": "", "entries": [], "stop_loss": 0,
                        "take_profit": 0, "entry_price": 0, "hexagram": ""}

        elif direction == "UP" and position["direction"] == "short":
            # 反转：平空开多
            # 平空
            qty = sum(e["qty"] for e in position["entries"])
            entry_px = sum(e["price"] * e["qty"] for e in position["entries"]) / qty
            pnl = (entry_px - price) * qty
            pnl_with_slip = pnl - price * qty * slippage
            capital += pnl_with_slip
            if pnl_with_slip >= 0:
                win_trades += 1
                total_win += pnl_with_slip
            else:
                loss_trades += 1
                total_loss += abs(pnl_with_slip)
            all_trades.append({
                "ts": ts, "price": price, "action": "close_short_reverse",
                "direction": "short", "hexagram": position["hexagram"],
                "entry_price": entry_px, "exit_price": price,
                "pnl": pnl_with_slip,
                "pnl_pct": pnl_with_slip / (entry_px * qty) if entry_px * qty else 0,
                "exit_reason": "reverse",
            })
            # 开多
            qty_new = (capital * grid_pos_pct) / price
            entry_px_new = price * (1 + slippage)
            position = {
                "direction": "long",
                "entries": [{"price": entry_px_new, "qty": qty_new}],
                "stop_loss": sl_px,
                "take_profit": tp_px,
                "entry_price": entry_px_new,
                "hexagram": hex_cn,
            }
            all_trades.append({
                "ts": ts, "price": entry_px_new, "action": "open_long",
                "direction": "long", "hexagram": hex_cn,
                "entry_price": entry_px_new, "exit_price": 0,
                "pnl": 0, "pnl_pct": 0, "exit_reason": "",
                "confidence": confidence, "stop_loss": sl_px, "take_profit": tp_px,
                "liangyi_state": bcrm_result.liangyi_state,
                "scale_params": bcrm_result.scale_params,
            })

        elif direction == "DOWN" and position["direction"] == "long":
            # 反转：平多开空
            qty = sum(e["qty"] for e in position["entries"])
            entry_px = sum(e["price"] * e["qty"] for e in position["entries"]) / qty
            pnl = (price - entry_px) * qty
            pnl_with_slip = pnl - price * qty * slippage
            capital += pnl_with_slip
            if pnl_with_slip >= 0:
                win_trades += 1
                total_win += pnl_with_slip
            else:
                loss_trades += 1
                total_loss += abs(pnl_with_slip)
            all_trades.append({
                "ts": ts, "price": price, "action": "close_long_reverse",
                "direction": "long", "hexagram": position["hexagram"],
                "entry_price": entry_px, "exit_price": price,
                "pnl": pnl_with_slip,
                "pnl_pct": pnl_with_slip / (entry_px * qty) if entry_px * qty else 0,
                "exit_reason": "reverse",
            })
            # 开空
            qty_new = (capital * grid_pos_pct) / price
            entry_px_new = price * (1 - slippage)
            position = {
                "direction": "short",
                "entries": [{"price": entry_px_new, "qty": qty_new}],
                "stop_loss": sl_px,
                "take_profit": tp_px,
                "entry_price": entry_px_new,
                "hexagram": hex_cn,
            }
            all_trades.append({
                "ts": ts, "price": entry_px_new, "action": "open_short",
                "direction": "short", "hexagram": hex_cn,
                "entry_price": entry_px_new, "exit_price": 0,
                "pnl": 0, "pnl_pct": 0, "exit_reason": "",
                "confidence": confidence, "stop_loss": sl_px, "take_profit": tp_px,
                "liangyi_state": bcrm_result.liangyi_state,
                "scale_params": bcrm_result.scale_params,
            })

        # 跟踪最大回撤
        if capital > peak_capital:
            peak_capital = capital
        dd = (peak_capital - capital) / peak_capital if peak_capital else 0
        if dd > max_drawdown:
            max_drawdown = dd

    # 如果还有未平仓，用最后价格平仓
    if position["direction"]:
        last_price = kline_data[start_idx]["c"] if start_idx < len(kline_data) else 0
        qty = sum(e["qty"] for e in position["entries"])
        entry_px = sum(e["price"] * e["qty"] for e in position["entries"]) / qty
        pnl = (last_price - entry_px) * qty if position["direction"] == "long" else (entry_px - last_price) * qty
        pnl_with_slip = pnl - last_price * qty * slippage
        capital += pnl_with_slip
        total_pnl = capital - initial_capital
        if pnl_with_slip >= 0:
            win_trades += 1
            total_win += pnl_with_slip
        else:
            loss_trades += 1
            total_loss += abs(pnl_with_slip)
        all_trades.append({
            "ts": kline_data[start_idx].get("ts_str", ""),
            "price": last_price,
            "action": f"close_{position['direction']}",
            "direction": position["direction"],
            "hexagram": position["hexagram"],
            "entry_price": entry_px, "exit_price": last_price,
            "pnl": pnl_with_slip,
            "pnl_pct": pnl_with_slip / (entry_px * qty) if entry_px * qty else 0,
            "exit_reason": "end_of_test",
        })

    total_pnl = capital - initial_capital
    total_trades = win_trades + loss_trades
    win_rate = win_trades / total_trades if total_trades else 0
    profit_factor = total_win / total_loss if total_loss else 0
    avg_win = total_win / win_trades if win_trades else 0
    avg_loss = -total_loss / loss_trades if loss_trades else 0

    result.total_trades = total_trades
    result.win_trades = win_trades
    result.loss_trades = loss_trades
    result.total_pnl = total_pnl
    result.win_rate = win_rate
    result.max_drawdown = max_drawdown
    result.avg_win = avg_win
    result.avg_loss = avg_loss
    result.profit_factor = profit_factor
    result.trades = all_trades

    # --- 两仪引擎在线学习 ---
    # 从交易记录中构建学习案例
    learned_cases = []
    try:
        learned_cases = _train_liangyi_from_trades(liangyi_engine, all_trades, kline_data, start_idx, end_idx)
    except Exception:
        pass

    result.learned_cases = learned_cases
    return result


def _train_liangyi_from_trades(liangyi_engine: LiangyiEngine,
                                trades: List[Dict],
                                kline_data: List[Dict],
                                start_idx: int, end_idx: int) -> List[Dict]:
    """
    从交易记录训练两仪引擎
    构建案例格式: {liangyi_state, scale_params, actual_outcome: {is_correct}}

    Returns:
        构建的案例列表（可用于持久化）
    """
    cases = []
    # 按时间正序遍历（end_idx 是旧的，start_idx 是新的）
    open_trades = {}  # hexagram -> open trade info

    for t in trades:
        if t["action"].startswith("open_"):
            open_trades[t["hexagram"]] = t
        elif t.get("exit_reason") and t["hexagram"] in open_trades:
            open_t = open_trades.pop(t["hexagram"], None)
            if not open_t:
                continue
            is_correct = t["pnl"] >= 0

            # 优先使用 BCRM 真实输出的 liangyi_state 和 scale_params
            real_liangyi = open_t.get("liangyi_state")
            real_scale = open_t.get("scale_params")

            if real_liangyi and real_scale:
                # 使用真实 BCRM 输出
                case = {
                    "liangyi_state": real_liangyi,
                    "scale_params": real_scale,
                    "actual_outcome": {
                        "is_correct": is_correct,
                        "pnl_pct": t.get("pnl_pct", 0),
                        "exit_reason": t.get("exit_reason", ""),
                    },
                    "decision_outcome": {
                        "is_correct": is_correct,
                    },
                    "entry_price": open_t.get("entry_price"),
                    "exit_price": t.get("price"),
                    "direction": open_t.get("direction"),
                    "hexagram": t["hexagram"],
                }
            else:
                # 简化构造（兼容旧数据）
                confidence = open_t.get("confidence", 0.5)
                entry_price = open_t["entry_price"]
                price_pos = 0.5
                trend_str = 0.5
                for i in range(end_idx, start_idx - 1, -1):
                    if i < len(kline_data) and abs(kline_data[i]["c"] - entry_price) / entry_price < 0.001:
                        closes_med = [kline_data[j]["c"] for j in range(
                            i, min(i + 20, len(kline_data)))]
                        if closes_med:
                            high_m = max(closes_med)
                            low_m = min(closes_med)
                            if high_m > low_m:
                                price_pos = (entry_price - low_m) / (high_m - low_m)
                        break

                macro_phase = "recovery"
                if price_pos > 0.7:
                    macro_phase = "overheat"
                elif price_pos < 0.3:
                    macro_phase = "recession"

                micro_phase = "growth"
                if trend_str < 0.3:
                    micro_phase = "decline"
                elif price_pos > 0.7:
                    micro_phase = "mature"
                elif price_pos < 0.3:
                    micro_phase = "sprout"

                case = {
                    "liangyi_state": {
                        "macro_phase": macro_phase,
                        "micro_phase": micro_phase,
                        "macro_season": {"recovery": "春", "overheat": "夏",
                                          "stagflation": "秋", "recession": "冬"}.get(macro_phase, "春"),
                        "micro_season": {"sprout": "春", "growth": "夏",
                                          "mature": "秋", "decline": "冬"}.get(micro_phase, "春"),
                    },
                    "scale_params": {
                        "weight_time": 0.25,
                        "weight_space": 0.2,
                        "weight_surface": 0.25,
                        "weight_core": 0.3,
                        "market_mass_base": 1.0,
                        "velocity_decay": 0.85,
                        "confidence_threshold": max(0.25, 0.7 - confidence),
                        "reversal_threshold": 0.2,
                    },
                    "actual_outcome": {
                        "is_correct": is_correct,
                    },
                    "decision_outcome": {
                        "is_correct": is_correct,
                    },
                }
            cases.append(case)

    if cases and len(cases) >= 3:
        liangyi_engine.learn_from_cases(cases)

    return cases


def run_multi_scenario_test(engine: BCRMEngine = None) -> List[ScenarioResult]:
    """
    多场景回测验证
    从 OKX 获取不同周期的历史数据，切分为不同场景
    """
    print("正在从 OKX 获取历史 K 线数据...")
    kline_4h = _load_kline_from_okx(bar="4H", limit=300)
    kline_1h = _load_kline_from_okx(bar="1H", limit=500)
    kline_1d = _load_kline_from_okx(bar="1D", limit=100)

    if not kline_4h:
        print("获取 K 线数据失败")
        return []

    print(f"获取到 {len(kline_4h)} 根 4H K线, {len(kline_1h)} 根 1H K线, {len(kline_1d)} 根 日K")

    scenarios = []

    # 场景1：近期趋势（最近 50 根 4H = 约 8 天）
    if len(kline_4h) >= 70:
        print("\n运行场景1: 近期趋势 (4H × 50bar)...")
        r = run_backtest("近期趋势(4H)", kline_4h, engine=engine,
                         start_idx=0, end_idx=50)
        scenarios.append(r)

    # 场景2：中期震荡（50-150 根 4H）
    if len(kline_4h) >= 170:
        print("运行场景2: 中期震荡 (4H × 100bar)...")
        r = run_backtest("中期震荡(4H)", kline_4h, engine=engine,
                         start_idx=50, end_idx=150)
        scenarios.append(r)

    # 场景3：长期走势（150-250 根 4H）
    if len(kline_4h) >= 270:
        print("运行场景3: 长期走势 (4H × 100bar)...")
        r = run_backtest("长期走势(4H)", kline_4h, engine=engine,
                         start_idx=150, end_idx=250)
        scenarios.append(r)

    # 场景4：1H 高频（最近 200 根 1H）
    if kline_1h and len(kline_1h) >= 220:
        print("运行场景4: 高频交易 (1H × 200bar)...")
        r = run_backtest("高频交易(1H)", kline_1h, engine=engine,
                         start_idx=0, end_idx=200, position_pct=0.05)
        scenarios.append(r)

    # 场景5：日线趋势（最近 50 根日K）
    if kline_1d and len(kline_1d) >= 70:
        print("运行场景5: 日线趋势 (1D × 50bar)...")
        r = run_backtest("日线趋势(1D)", kline_1d, engine=engine,
                         start_idx=0, end_idx=50, position_pct=0.2)
        scenarios.append(r)

    # --- L4 持久化：汇总所有场景的 cases ---
    all_cases: List[Dict] = []
    for r in scenarios:
        if hasattr(r, "learned_cases") and r.learned_cases:
            for c in r.learned_cases:
                c["scenario"] = r.name
                all_cases.append(c)

    if all_cases:
        saved = _save_cases_to_l4(all_cases, source="multi_scenario_backtest")
        print(f"\nL4 案例库: 保存了 {saved} 个案例到 {memory_l4_cases_dir()}")
    else:
        print("\nL4 案例库: 无有效案例（不足3笔开平仓对）")

    # 保存 LiangyiEngine 学习状态
    if engine and hasattr(engine, "liangyi_engine"):
        try:
            ok = engine.liangyi_engine.save_state(str(LIANGYI_STATE_FILE))
            if ok:
                print(f"L4 两仪引擎: 状态已保存到 {LIANGYI_STATE_FILE}")
        except Exception:
            pass

    return scenarios


def print_report(results: List[ScenarioResult]):
    """打印测试报告"""
    print("\n" + "=" * 80)
    print("  易经交易推理模型 - 多场景回测验证报告")
    print("=" * 80)

    header = f"{'场景':<20} {'交易数':>6} {'胜率':>8} {'盈亏比':>8} {'总盈亏':>10} {'最大回撤':>8} {'买持收益':>10}"
    print(header)
    print("-" * 80)

    total_trades = 0
    total_win = 0
    total_loss = 0
    total_pnl = 0

    for r in results:
        pnl_str = f"+${r.total_pnl:,.0f}" if r.total_pnl >= 0 else f"-${abs(r.total_pnl):,.0f}"
        bh_str = f"+{r.buy_hold_return*100:+.1f}%"
        print(f"{r.name:<20} {r.total_trades:>6} {r.win_rate*100:>7.1f}% {r.profit_factor:>8.2f} {pnl_str:>10} {r.max_drawdown*100:>7.2f}% {bh_str:>10}")
        total_trades += r.total_trades
        total_pnl += r.total_pnl
        if r.avg_win > 0:
            total_win += r.avg_win * r.win_trades
        if r.avg_loss < 0:
            total_loss += abs(r.avg_loss) * r.loss_trades

    print("-" * 80)
    overall_wr = 0
    overall_pf = 0
    if total_trades:
        win_count = sum(r.win_trades for r in results)
        overall_wr = win_count / total_trades
        overall_pf = total_win / total_loss if total_loss else 0
    print(f"{'汇总':<20} {total_trades:>6} {overall_wr*100:>7.1f}% {overall_pf:>8.2f} {('+$' if total_pnl>=0 else '-$') + f'{abs(total_pnl):,.0f}':>10}")

    print("\n" + "=" * 80)

    # 卦象统计
    print("\n  各卦象交易统计 (所有场景)")
    print("-" * 40)
    hex_stats = {}
    for r in results:
        for t in r.trades:
            if t["action"].startswith("open_") and t.get("hexagram"):
                hx = t["hexagram"]
                if hx not in hex_stats:
                    hex_stats[hx] = {"count": 0, "win": 0, "loss": 0, "pnl": 0}
                hex_stats[hx]["count"] += 1
            elif t.get("exit_reason") and t.get("pnl", 0) != 0:
                # 平仓记录，对应上一个开仓的卦象
                pass

    if hex_stats:
        sorted_hex = sorted(hex_stats.items(), key=lambda x: -x[1]["count"])
        for hx, s in sorted_hex[:15]:
            print(f"  {hx:<15} {s['count']:>3} 次")

    print("\n" + "=" * 80)


def main():
    """CLI 入口"""
    import sys

    print("易经交易推理模型训练器")
    print("=" * 50)

    engine = default_engine()

    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # 多场景测试
        results = run_multi_scenario_test(engine=engine)
        if results:
            print_report(results)
            # 保存结果
            out_file = TRAIN_DATA_DIR / f"backtest_result_{int(time.time())}.json"
            save_data = []
            for r in results:
                save_data.append({
                    "name": r.name,
                    "bar": r.bar,
                    "start_price": r.start_price,
                    "end_price": r.end_price,
                    "buy_hold_return": r.buy_hold_return,
                    "total_trades": r.total_trades,
                    "win_trades": r.win_trades,
                    "loss_trades": r.loss_trades,
                    "total_pnl": r.total_pnl,
                    "win_rate": r.win_rate,
                    "max_drawdown": r.max_drawdown,
                    "profit_factor": r.profit_factor,
                    "trade_count": len(r.trades),
                })
            with open(out_file, "w") as f:
                json.dump(save_data, f, indent=2, ensure_ascii=False)
            print(f"\n结果已保存到: {out_file}")
        return

    # 默认：运行一次快速回测
    print("\n获取 OKX 历史行情...")
    kline = _load_kline_from_okx(bar="4H", limit=100)
    if not kline:
        print("获取数据失败")
        return

    print(f"获取到 {len(kline)} 根 4H K线")
    print("运行回测...")
    result = run_backtest("快速测试", kline, engine=engine, start_idx=20, end_idx=99)
    print_report([result])


if __name__ == "__main__":
    main()
