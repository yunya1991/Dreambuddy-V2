"""单币基本面排名器 — CoinFundamentalRanker。

基于 Artemis Fundamentals 架构（Revenue Stability / MC/Fees Mean Reversion /
TVL Growth Momentum / Revenue Quality），覆盖三类资产：
  - crypto_usdt（加密货币）：DeFiLlama TVL/Fees + CoinGecko market_cap
  - us_stock（美股）：yfinance PE/margins/ROE/revenueGrowth
  - precious_metal（贵金属）：yfinance ETF + FRED T10YIE

Shadow 模式：只计算 + 记录 + 审计，不参与任何交易决策。
开关：enable_coin_fundamental_ranker（默认 False）

Phase B1：数据类 + 映射表 + 分类函数。
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)


# ===========================================================================
# 开关 + 路径
# ===========================================================================

# 总开关（默认 False，Shadow 模式：只计算 + 记录 + 审计，不参与交易决策）
ENABLE_COIN_FUNDAMENTAL_RANKER = False

# Shadow 审计日志默认路径：11-易经推理系统/scripts/runtime/coin_fundamental_shadow.jsonl
# force_vector → memory_l4 → scripts，然后 + runtime
_RUNTIME_DIR = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "runtime"))
SHADOW_JSONL_PATH = os.path.join(_RUNTIME_DIR, "coin_fundamental_shadow.jsonl")

# data_center.db 默认路径：dreambuddy-v2/18-数据获取中心/data_center.db
# force_vector → memory_l4 → scripts → 11-易经推理系统 → dreambuddy-v2（4级）
_REPO = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "..", ".."))
DEFAULT_DB_PATH = os.path.join(_REPO, "18-数据获取中心", "data_center.db")


# ===========================================================================
# 映射表
# ===========================================================================

# BDSM 权威币种池（10 币） — BTC 为 L1 龙头于 L1 代理信号就绪后纳入；
# SKY 暂移除，待原生 collector 补齐后再评估纳入。
# 2026-09-06 新增 ZEC（L1 隐私币）、ARB（L2 龙头）
# 所有需要引用 BDSM 池的模块（polling_trader、data_server、p0_backtest_verify 等）
# 都应该从这里 import BDSM_COINS，避免散落硬编码
BDSM_COINS: frozenset = frozenset(
    {"UNI", "PUMP", "HYPE", "AAVE", "SOL", "CRCL", "ETH", "BTC", "ZEC", "ARB"}
)

# 加密货币映射：币种符号 → (CoinGecko coin_id, DeFiLlama protocol_slug)
# defillama_slug 为 None 表示该币是 L1 链而非 DeFi protocol（无费用数据）
CRYPTO_MAP: Dict[str, Dict[str, Optional[str]]] = {
    "BTC": {"coingecko_id": "bitcoin", "defillama_slug": None},
    "ETH": {"coingecko_id": "ethereum", "defillama_slug": None},
    "SOL": {"coingecko_id": "solana", "defillama_slug": None},
    "UNI": {"coingecko_id": "uniswap", "defillama_slug": "uniswap"},
    "LINK": {"coingecko_id": "chainlink", "defillama_slug": "chainlink"},
    "AAVE": {"coingecko_id": "aave", "defillama_slug": "aave"},
    # --- Phase G 关注范围扩展（可持续回购项目）---
    # SKY: 协议盈余回购，稳定来源（BDSM RQ=高）
    "SKY": {"coingecko_id": "sky-ecosystem", "defillama_slug": "sky"},
    # PUMP: Pump.fun 交易费回购，规模大（BDSM SI=高）
    "PUMP": {"coingecko_id": "pump-fun", "defillama_slug": "pump-fun"},
    # --- Phase E 闭环三案例锚定（E6 扩展）---
    # HYPE: Hyperliquid，盈收强+估值稳，P3 估值修复案例锚定
    "HYPE": {"coingecko_id": "hyperliquid", "defillama_slug": "hyperliquid"},
    # CRCL: 主网预期驱动案例锚定，coingecko_id 视实际可用性调整
    # 注：DeFiLlama slug 为 None（非 DeFi protocol 类，无费用数据）
    "CRCL": {"coingecko_id": "acrocalctoken", "defillama_slug": None},
    # ZEC: L1 隐私币龙头，DeFiLlama 无 protocol 数据（NVT 估值）
    "ZEC": {"coingecko_id": "zcash", "defillama_slug": None},
    # ARB: L2 Arbitrum 治理代币，DeFiLlama 有 protocol 费用数据
    "ARB": {"coingecko_id": "arbitrum", "defillama_slug": "arbitrum"},
}

# 美股映射：股票代码 → yfinance symbol（1:1，预留未来 ticker 别名）
STOCK_MAP: Dict[str, str] = {
    "NVDA": "NVDA",
    "AAPL": "AAPL",
    "MSFT": "MSFT",
}

# 贵金属映射：金属代码 → (yfinance ETF, FRED series)
METAL_MAP: Dict[str, Dict[str, str]] = {
    "XAUUSD": {"yfinance_etf": "GLD", "fred_series": "T10YIE"},
    "XAGUSD": {"yfinance_etf": "SLV", "fred_series": "T10YIE"},
}


# ===========================================================================
# 数据类
# ===========================================================================

@dataclass
class CoinFundamentalSignal:
    """单币基本面信号 — Shadow 模式输出。

    fundamental_score: 等权合成四子信号后的综合分数 [-1.0, +1.0]
    rank: S(≥2子信号>0.5) / A(≥1子信号>0.5) / B(中性) / C(score<-0.3)
    sub_signals: 四个基本面子信号名称→值
    data_quality: sufficient(全4信号) / partial(缺失≤2) / insufficient(缺失>2)
    confidence: 数据覆盖率和信号一致性的综合置信度 [0.0, 1.0]
    error: FAIL-OPEN 时的错误信息（正常为 None）

    Phase E 闭环字段（E4 扩展）：
    current_phase: P1_EXPECTATION / P2_REVENUE_EXPANSION / P3_VALUATION_RECOVERY
    phase_confidence: [0,1] 阶段识别三因子一致性
    phase_switch_triggers: 触发评估的事件/阈值清单
    phase_strategy_hint: 来自 3.8 阶段策略映射表的提示
    """
    coin: str                              # 币种标识 (BTC/UNI/NVDA/XAUUSD等)
    asset_class: str                       # crypto_usdt / us_stock / precious_metal
    fundamental_score: float              # 综合基本面分数 [-1.0, +1.0]
    rank: str                              # S/A/B/C 等级
    sub_signals: Dict[str, float]          # 四个子信号名称→值
    data_quality: str                      # sufficient / partial / insufficient
    confidence: float                      # 置信度 [0.0, 1.0]
    timestamp: str                         # ISO8601 计算时间
    error: Optional[str] = None            # 异常时的错误信息（FAIL-OPEN）
    # --- Phase E 闭环字段（E4 新增，默认中性 P2）---
    current_phase: str = "P2_REVENUE_EXPANSION"
    phase_confidence: float = 0.0
    phase_switch_triggers: List[str] = field(default_factory=list)
    phase_strategy_hint: Dict[str, Any] = field(default_factory=dict)


# ===========================================================================
# 分类 + 映射函数
# ===========================================================================

def classify_asset_class(coin: str) -> Optional[str]:
    """分类资产类别。

    Returns:
        "crypto_usdt" / "us_stock" / "precious_metal" / None
    """
    if coin in CRYPTO_MAP:
        return "crypto_usdt"
    if coin in STOCK_MAP:
        return "us_stock"
    if coin in METAL_MAP:
        return "precious_metal"
    return None


def get_protocol_mapping(coin: str) -> Optional[str]:
    """获取 DeFiLlama protocol slug（仅 DeFi protocol 类加密货币有值）。

    BTC/ETH 等 L1 链返回 None（它们是链而非 protocol）。
    """
    info = CRYPTO_MAP.get(coin)
    if info is None:
        return None
    return info.get("defillama_slug")


def get_coingecko_id(coin: str) -> Optional[str]:
    """获取 CoinGecko coin_id（仅加密货币有值）。"""
    info = CRYPTO_MAP.get(coin)
    if info is None:
        return None
    return info.get("coingecko_id")


def get_yfinance_symbol(coin: str) -> Optional[str]:
    """获取 yfinance symbol（美股和贵金属有值，加密货币返回 None）。"""
    if coin in STOCK_MAP:
        return STOCK_MAP[coin]
    if coin in METAL_MAP:
        return METAL_MAP[coin]["yfinance_etf"]
    return None


def get_metal_fred_series(coin: str) -> Optional[str]:
    """获取贵金属对应的 FRED series ID（仅贵金属有值）。"""
    info = METAL_MAP.get(coin)
    if info is None:
        return None
    return info.get("fred_series")


# ===========================================================================
# B5: 主模块合成 — compute_signal + compute_for_coins + write_shadow
# ===========================================================================
# 子模块 compute_all 延迟导入避免循环依赖（子模块 import ranker 的映射函数）
# 模块级变量供测试 mock patch 路径 force_vector.coin_fundamental_ranker.{name}

crypto_compute_all = None
stock_compute_all = None
metal_compute_all = None


def _get_crypto_compute_all():
    global crypto_compute_all
    if crypto_compute_all is None:
        from force_vector.coin_fundamental_crypto import compute_all
        crypto_compute_all = compute_all
    return crypto_compute_all


def _get_stock_compute_all():
    global stock_compute_all
    if stock_compute_all is None:
        from force_vector.coin_fundamental_stock import compute_all
        stock_compute_all = compute_all
    return stock_compute_all


def _get_metal_compute_all():
    global metal_compute_all
    if metal_compute_all is None:
        from force_vector.coin_fundamental_metal import compute_all
        metal_compute_all = compute_all
    return metal_compute_all


# 原四信号（Artemis Fundamentals 架构）
_ORIGINAL_SIGNALS = frozenset({
    "revenue_stability", "mc_fees_mean_reversion",
    "tvl_growth_momentum", "revenue_quality",
})
# 阶段识别信号（E5/E6/E7 BDSM 三维度）
_PHASE_SIGNALS = frozenset({
    "supply_shrinkage_intensity", "value_capture_delta", "revenue_sustainability",
})


def _synthesize_score(sub_signals: Dict[str, float]) -> float:
    """分层加权合成子信号 → fundamental_score.

    七信号分层加权（对齐 project_memory 约束）：
      - 原四信号等权占 50%
      - E5/E6/E7 各占约 16.67%（50%/3）

    向后兼容：
      - 仅原四信号（stock/metal）→ 等权合成
      - 仅阶段信号（边缘情况）→ 等权合成

    Returns:
        [-1.0, +1.0]
    """
    if not sub_signals:
        return 0.0
    orig_values = [v for k, v in sub_signals.items() if k in _ORIGINAL_SIGNALS]
    phase_values = [v for k, v in sub_signals.items() if k in _PHASE_SIGNALS]
    orig_score = sum(orig_values) / len(orig_values) if orig_values else 0.0
    phase_score = sum(phase_values) / len(phase_values) if phase_values else 0.0
    if orig_values and phase_values:
        # 七信号：原四50% + 阶段三50%
        raw = orig_score * 0.5 + phase_score * 0.5
    elif orig_values:
        raw = orig_score  # 仅原四（stock/metal）
    elif phase_values:
        raw = phase_score  # 仅阶段（边缘）
    else:
        raw = 0.0
    return max(-1.0, min(1.0, raw))


def _determine_rank(score: float, sub_signals: Dict[str, float]) -> str:
    """等级映射：S / A / B / C。

    - S：score > 0.6 且 ≥2 个子信号 > 0.5（趋势持仓候选）
    - A：score > 0.3（优先关注）
    - B：-0.3 ~ 0.3（正常）
    - C：score < -0.3（谨慎）
    """
    strong_count = sum(1 for v in sub_signals.values() if v > 0.5)
    if score > 0.6 and strong_count >= 2:
        return "S"
    if score > 0.3:
        return "A"
    if score < -0.3:
        return "C"
    return "B"


def _determine_data_quality(sub_signals: Dict[str, float]) -> str:
    """数据质量：sufficient / partial / insufficient。

    - sufficient：全 4 信号非 0
    - partial：1-2 信号为 0
    - insufficient：>2 信号为 0（含全 0）
    """
    if not sub_signals:
        return "insufficient"
    zero_count = sum(1 for v in sub_signals.values() if v == 0.0)
    total = len(sub_signals)
    if zero_count == 0:
        return "sufficient"
    if zero_count <= total // 2:
        return "partial"
    return "insufficient"


def _compute_confidence(sub_signals: Dict[str, float]) -> float:
    """置信度 = 非零信号数 / 总信号数。"""
    if not sub_signals:
        return 0.0
    non_zero = sum(1 for v in sub_signals.values() if v != 0.0)
    return max(0.0, min(1.0, non_zero / len(sub_signals)))


def compute_signal(coin: str, db_path: str = None) -> CoinFundamentalSignal:
    """主入口：计算指定币种的基本面信号。

    1. classify_asset_class → 分派到 crypto/stock/metal compute_all
    2. 等权合成 fundamental_score
    3. 等级映射 S/A/B/C
    4. data_quality + confidence

    FAIL-OPEN：任何异常 → fundamental_score=0.0, rank="B",
              data_quality="insufficient", error=异常信息。
    """
    # 默认 db_path
    if db_path is None:
        db_path = DEFAULT_DB_PATH

    now = datetime.now(timezone.utc).astimezone().isoformat()
    neutral = CoinFundamentalSignal(
        coin=coin, asset_class="",
        fundamental_score=0.0, rank="B",
        sub_signals={}, data_quality="insufficient",
        confidence=0.0, timestamp=now,
        error="neutral default",
    )

    try:
        asset_class = classify_asset_class(coin)
        if asset_class is None:
            neutral.error = f"unknown coin: {coin}"
            neutral.asset_class = "unknown"
            return neutral

        neutral.asset_class = asset_class

        # 分派到子模块
        if asset_class == "crypto_usdt":
            fn = _get_crypto_compute_all()
            sub_signals = fn(coin, db_path)
        elif asset_class == "us_stock":
            fn = _get_stock_compute_all()
            sub_signals = fn(coin, db_path)
        elif asset_class == "precious_metal":
            fn = _get_metal_compute_all()
            sub_signals = fn(coin, db_path)
        else:
            neutral.error = f"unsupported asset_class: {asset_class}"
            return neutral

        # 合成
        score = _synthesize_score(sub_signals)
        rank = _determine_rank(score, sub_signals)
        quality = _determine_data_quality(sub_signals)
        confidence = _compute_confidence(sub_signals)

        # Phase E 闭环：调用 classify_phase + get_strategy_hint 填充阶段字段
        # 延迟导入避免循环依赖（phase_classifier/phase_strategy_map 不 import ranker）
        phase_classification = None
        try:
            from force_vector.coin_fundamental_phase_classifier import classify_phase
            from force_vector.coin_fundamental_valuation_query import query_valuation_percentile
            from force_vector.coin_fundamental_event_timeline import query_event_timeline
            # F1: valuation_percentile 真实查询（CoinGecko market_chart 历史分位）
            # FAIL-OPEN：查询异常或数据不足返回 50.0（中性）
            valuation_percentile = query_valuation_percentile(coin, db_path)
            # F2: event_timeline 真实查询（odaily newsflash 代币里程碑事件）
            # FAIL-OPEN：查询异常或无事件返回空 list，phase_classifier 走默认规则
            event_timeline = query_event_timeline(coin, db_path)
            phase_classification = classify_phase(
                coin=coin,
                sub_signals=sub_signals,
                valuation_percentile=valuation_percentile,
                event_timeline=event_timeline,
            )
        except Exception as phase_exc:  # FAIL-OPEN：阶段识别异常不阻塞主信号
            phase_classification = None

        phase_strategy_hint: Dict[str, Any] = {}
        if phase_classification is not None:
            try:
                from force_vector.coin_fundamental_phase_strategy_map import get_strategy_hint
                phase_strategy_hint = get_strategy_hint(
                    phase_classification.current_phase, rank,
                )
            except Exception:  # FAIL-OPEN：策略映射异常返回中性空 dict
                phase_strategy_hint = {}

        return CoinFundamentalSignal(
            coin=coin, asset_class=asset_class,
            fundamental_score=round(score, 4), rank=rank,
            sub_signals=sub_signals, data_quality=quality,
            confidence=round(confidence, 4), timestamp=now,
            error=None,
            current_phase=(
                phase_classification.current_phase
                if phase_classification is not None
                else "P2_REVENUE_EXPANSION"
            ),
            phase_confidence=(
                round(phase_classification.phase_confidence, 4)
                if phase_classification is not None
                else 0.0
            ),
            phase_switch_triggers=(
                list(phase_classification.switch_triggers)
                if phase_classification is not None
                else []
            ),
            phase_strategy_hint=phase_strategy_hint,
        )
    except Exception as exc:
        # FAIL-OPEN：6 层堆栈日志 + 中性默认
        tb_lines = traceback.format_exc().splitlines()
        neutral.error = f"{type(exc).__name__}: {exc}"
        neutral.sub_signals = neutral.sub_signals or {}
        return neutral


def compute_for_coins(coin_list: List[str], db_path: str = None) -> List[CoinFundamentalSignal]:
    """批量计算多币种的基本面信号。"""
    return [compute_signal(coin, db_path) for coin in coin_list]


def write_shadow(signal: CoinFundamentalSignal, jsonl_path: str = SHADOW_JSONL_PATH) -> None:
    """追加写入 Shadow JSONL 审计日志。

    格式对齐 SPEC §5.1：包含 price_at_signal / price_7d_after 等留空字段，
    由定时任务在 7d/14d/30d 后回填，用于计算 IC 和命中率。
    """
    # 确保目录存在
    dir_path = os.path.dirname(jsonl_path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)

    record = {
        "coin": signal.coin,
        "asset_class": signal.asset_class,
        "timestamp": signal.timestamp,
        "fundamental_score": signal.fundamental_score,
        "rank": signal.rank,
        "sub_signals": signal.sub_signals,
        "data_quality": signal.data_quality,
        "confidence": signal.confidence,
        "error": signal.error,
        # 价格追踪字段（信号生成时留空，由定时任务回填）
        "price_at_signal": None,
        "price_7d_after": None,
        "price_14d_after": None,
        "price_30d_after": None,
        "return_7d": None,
        "return_14d": None,
        "return_30d": None,
    }

    with open(jsonl_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
