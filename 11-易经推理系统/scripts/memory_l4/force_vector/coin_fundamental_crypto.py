"""加密货币基本面四信号模块 — CoinFundamentalCrypto。

基于 Artemis Fundamentals 架构，四个近正交信号：
  1. Revenue Stability：费用 Sharpe → 稳定→正
  2. MC/Fees Mean Reversion：市值/费用 比率 → 高估值→负
  3. TVL Growth Momentum：TVL 7d 变化率 → 增长→正
  4. Revenue Quality：费用/TVL 效率 → 高效→正

数据来源：data_center.db SQLite records 表
  - DeFiLlama protocol_fees（source=defillama, category=protocol, sub_category=fees_{slug}）
  - CoinGecko coin_info（source=coingecko, category=coin, sub_category={coin_id}）
  - DeFiLlama protocols（source=defillama, category=protocol, sub_category=all_protocols）

FAIL-OPEN：任何异常 → 对应信号返回 0.0，不阻塞整体。
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
from statistics import mean, stdev
from typing import Dict, Optional

# 从 coin_fundamental_ranker 获取映射
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from force_vector.coin_fundamental_ranker import (
    get_coingecko_id,
    get_protocol_mapping,
)

# BTC/ETH/SOL 等 L1 链的「NVT 历史中位数」先验锚点（CoinMetrics 2017-2025 公开数据中枢）
# 当 DB 未灌 l1_* 记录时，二级回退使用；单位 = 网络市值 ÷ 链上日交易价值。
# FAIL-OPEN：如果未来数据齐全时覆盖，会被 _fetch_L1_chain_metrics DB 读数覆盖（优先级更高）。
_L1_NVT_MEDIAN_PRIOR: Dict[str, float] = {
    "BTC": 25.0,
    "ETH": 22.0,
    "SOL": 30.0,
    "CRCL": 40.0,
}
# 供给收缩前验：BTC 每 4 年减半（S2F ratio 当前约 55 左右）。此表用于 L1_miner_proxy_fallback
# 当 coin_data 无 mcap 时构造矿工费近似（不影响 coin_info 已提供时的主路径）
# 哈希率近似：按最新公开量级 TH/s
_L1_HASH_RATE_PRIOR_THs: Dict[str, float] = {
    "BTC": 900_000_000.0,   # ≈ 900 EH/s = 900M TH/s（2026 年中量级）
    "ETH": 20_000_000_000.0,  # validators×effort 代理
    "SOL": 5_000_000.0,      # compute-units proxy
    "CRCL": 1_000_000.0,
}
# L1 revenue_quality 每 TH/s 矿工费效率的「中性点」：tanh((eff - neutral)/scale)
# 单位 = USD / (day × TH/s)。BTC 历史公开的矿工费/哈希率约 0.008 $/TH/day（2024-2025 均价）。
# 这里留中性值，使得正常水平 → 0；高效超 0 → +；低迷 <0 → −
_L1_EFFICIENCY_NEUTRAL: Dict[str, float] = {
    "BTC": 0.010,       # 0.01 USD / (TH/day)
    "ETH": 0.0004,      # ETH validators 等效值 低 2 数量级
    "SOL": 0.15,        # SOL compute-units 高 1 数量级
    "CRCL": 0.05,
}
# L1 RQ 效率系数的尺度参数（1σ 偏离）
_L1_EFFICIENCY_SCALE: Dict[str, float] = {
    "BTC": 0.005,
    "ETH": 0.0002,
    "SOL": 0.075,
    "CRCL": 0.025,
}
# OKX K 线 / CoinGecko market_chart 拉取代理（同 bdsm_snapshot_writer）
_L1_HTTP_PROXY = os.environ.get("SNAPSHOT_PROXY") or os.environ.get("HTTP_PROXY") or None

# ===========================================================================
# E8 板块横向估值（Cross-Sector Valuation）
# ===========================================================================
# 板块成员表：BDSM 池内币 + 主流竞对，用于横向对比 MC/Fees 估值。
# CRCL 暂不归入（主网未上线，无费用数据）。
SECTOR_MAP: Dict[str, list] = {
    "DEX": ["UNI", "CRV", "1INCH", "CAKE", "SUSHI"],
    "Lending": ["AAVE", "COMP", "MKR"],
    "L1": ["BTC", "ETH", "SOL", "BNB", "ADA", "ZEC"],
    "L2": ["OP", "ARB", "MATIC", "STX"],
    "Meme": ["PUMP", "DOGE", "SHIB", "PEPE"],
    "Perp_DEX": ["HYPE", "GMX", "GNS", "DYDX"],
}

# 板块成员 → (coingecko_id, defillama_slug) 映射
# 竞对币（非 BDSM 池）的 CRYPTO_MAP 补全在这里，避免污染主映射表
_SECTOR_COIN_META: Dict[str, Dict[str, Optional[str]]] = {
    # DEX
    "UNI": {"coingecko_id": "uniswap", "defillama_slug": "uniswap"},
    "CRV": {"coingecko_id": "curve-dao-token", "defillama_slug": "curve"},
    "1INCH": {"coingecko_id": "1inch", "defillama_slug": "1inch"},
    "CAKE": {"coingecko_id": "pancakeswap-token", "defillama_slug": "pancakeswap"},
    "SUSHI": {"coingecko_id": "sushi", "defillama_slug": "sushi"},
    # Lending
    "AAVE": {"coingecko_id": "aave", "defillama_slug": "aave"},
    "COMP": {"coingecko_id": "compound-governance-token", "defillama_slug": "compound"},
    "MKR": {"coingecko_id": "maker", "defillama_slug": "makerdao"},
    # L1（无 defillama_slug，用 NVT 替代 MC/Fees）
    "BTC": {"coingecko_id": "bitcoin", "defillama_slug": None},
    "ETH": {"coingecko_id": "ethereum", "defillama_slug": None},
    "SOL": {"coingecko_id": "solana", "defillama_slug": None},
    "BNB": {"coingecko_id": "binancecoin", "defillama_slug": None},
    "ADA": {"coingecko_id": "cardano", "defillama_slug": None},
    "ZEC": {"coingecko_id": "zcash", "defillama_slug": None},
    # L2
    "OP": {"coingecko_id": "optimism", "defillama_slug": "optimism"},
    "ARB": {"coingecko_id": "arbitrum", "defillama_slug": "arbitrum"},
    "MATIC": {"coingecko_id": "matic-network", "defillama_slug": "polygon"},
    "STX": {"coingecko_id": "blockstack", "defillama_slug": "stacks"},
    # Meme
    "PUMP": {"coingecko_id": "pump-fun", "defillama_slug": "pump-fun"},
    "DOGE": {"coingecko_id": "dogecoin", "defillama_slug": None},
    "SHIB": {"coingecko_id": "shiba-inu", "defillama_slug": None},
    "PEPE": {"coingecko_id": "pepe", "defillama_slug": None},
    # Perp DEX
    "HYPE": {"coingecko_id": "hyperliquid", "defillama_slug": "hyperliquid"},
    "GMX": {"coingecko_id": "gmx", "defillama_slug": "gmx"},
    "GNS": {"coingecko_id": "gains-network", "defillama_slug": "gains-network"},
    "DYDX": {"coingecko_id": "dydx", "defillama_slug": "dydx"},
}


def _get_sector_of_coin(coin: str) -> Optional[str]:
    """查询 coin 所属板块名称。不在任何板块 → None。"""
    coin_upper = (coin or "").upper()
    for sector, members in SECTOR_MAP.items():
        if coin_upper in members:
            return sector
    return None


def _fetch_sector_valuation_ratios(sector: str, db_path: str) -> Dict[str, float]:
    """获取板块内所有币的 MC/Fees 比率（L1 用 NVT 替代）。

    返回 {coin: ratio}，仅包含成功获取数据的币。
    """
    ratios: Dict[str, float] = {}
    members = SECTOR_MAP.get(sector, [])
    if len(members) < 3:
        return ratios

    for member in members:
        try:
            meta = _SECTOR_COIN_META.get(member)
            if meta is None:
                continue
            coin_id = meta.get("coingecko_id")
            slug = meta.get("defillama_slug")

            # 获取市值
            coin_info = _fetch_coin_info(db_path, coin_id) if coin_id else {}
            mcap = float(coin_info.get("market_cap_usd", 0) or 0)
            if mcap <= 0:
                continue

            # 获取费用（L1 用 NVT 替代，DeFi 用 protocol fees）
            if slug:
                fees_data = _fetch_protocol_fees(db_path, slug)
                fees_30d = float(fees_data.get("fees_30d", 0) or 0)
            else:
                # L1：尝试从 _fetch_L1_chain_metrics 获取 nvt_ratio
                l1_data = _fetch_L1_chain_metrics(member, db_path)
                nvt = float(l1_data.get("nvt_ratio", 0) or 0)
                if nvt > 0:
                    ratios[member] = nvt
                continue

            if fees_30d <= 0:
                continue
            ratios[member] = mcap / fees_30d
        except Exception:
            continue  # FAIL-OPEN：单个币失败不影响其他

    return ratios


def compute_e8_cross_sector_valuation(coin: str, db_path: str) -> float:
    """E8 板块横向估值：1 - (该币 MC/Fees 在板块中的百分位)。

    取值 [-1, +1]：
      - E8 > 0：该币在板块中相对便宜（横向低估）
      - E8 < 0：该币在板块中相对贵（横向高估）
      - E8 = 0：板块中位或数据不足

    映射公式：E8 = 1 - pct/50，pct ∈ [0, 100]
      - pct=0   → E8=+1（板块最便宜）
      - pct=50  → E8=0（板块中位）
      - pct=100 → E8=-1（板块最贵）

    FAIL-OPEN：板块成员 <3 / 不在板块 / 该币无估值数据 → 0.0
    """
    sector = _get_sector_of_coin(coin)
    if sector is None:
        return 0.0

    members = SECTOR_MAP.get(sector, [])
    if len(members) < 3:
        return 0.0

    ratios = _fetch_sector_valuation_ratios(sector, db_path)
    # 有效数据点 < 3 → 无法计算百分位，FAIL-OPEN
    if len(ratios) < 3:
        return 0.0

    coin_upper = (coin or "").upper()
    target_ratio = ratios.get(coin_upper)
    if target_ratio is None:
        return 0.0  # 该币无数据

    # 计算百分位：比 target 便宜（ratio 更小）的占比
    sorted_ratios = sorted(ratios.values())
    cheaper_count = sum(1 for r in sorted_ratios if r < target_ratio)
    pct = (cheaper_count / len(sorted_ratios)) * 100.0

    # 映射到 [-1, +1]
    e8 = 1.0 - (pct / 50.0)
    return max(-1.0, min(1.0, e8))

# data_center.db 默认路径：dreambuddy-v2/18-数据获取中心/data_center.db
# force_vector → memory_l4 → scripts → 11-易经推理系统 → dreambuddy-v2（4级）
_REPO = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "..", ".."))
_DATA_CENTER_ROOT = os.path.join(_REPO, "18-数据获取中心")
DEFAULT_DB_PATH = os.path.join(_DATA_CENTER_ROOT, "data_center.db")


# ===========================================================================
# BDSM 原生数据源映射（Phase G — 项目官网爬虫）
# ===========================================================================
# coin → (bdsm_source, source_type, source_age_days)
# source_type: protocol_surplus(稳定) > trading_fee(高波动) > asset_yield(中等)
_BDSM_SOURCE_MAP: Dict[str, Dict[str, object]] = {
    "UNI": {
        "source": "bdsm_uniswap",
        "source_type": "trading_fee",
        "source_age_days": 180,  # Uniswap V3 上线超 180 天
    },
    "PUMP": {
        "source": "bdsm_pump",
        "source_type": "trading_fee",
        "source_age_days": 365,  # pump.fun 上线超 1 年
    },
    "HYPE": {
        "source": "bdsm_hype",
        "source_type": "trading_fee",
        "source_age_days": 365,  # Hyperliquid 上线超 1 年
    },
    "AAVE": {
        "source": "bdsm_aave",
        "source_type": "asset_yield",  # 借贷利差收入
        "source_age_days": 720,  # Aave V3 上线超 2 年
    },
    "CRCL": {
        "source": "bdsm_circle",
        "source_type": "asset_yield",  # 储备利息收入（稳定币）
        "source_age_days": 365,  # USDC 长期稳定运行
    },
    "SOL": {
        "source": "bdsm_solana",
        "source_type": "trading_fee",  # 链上交易费
        "source_age_days": 365,  # Solana 主网长期运行
    },
}


# ===========================================================================
# 数据读取（SQLite）
# ===========================================================================

def _safe_json(text) -> any:
    if isinstance(text, dict):
        return text
    if not isinstance(text, str):
        return {}
    try:
        v = json.loads(text)
        return v if isinstance(v, (dict, list)) else {}
    except Exception:
        return {}


def _fetch_protocol_fees(db_path: str, protocol: str) -> dict:
    """从 SQLite 读取 DeFiLlama protocol fees 数据。"""
    if not protocol or not os.path.exists(db_path):
        return {}
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT metrics, timeseries FROM records "
            "WHERE source='defillama' AND category='protocol' "
            f"AND sub_category='fees_{protocol}' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if row is None:
            return {}
        metrics = _safe_json(row["metrics"])
        ts = _safe_json(row["timeseries"])
        return {"fees_30d": metrics.get("fees_30d", 0.0), "timeseries": ts if isinstance(ts, list) else []}
    except Exception:
        return {}


def _fetch_coin_info(db_path: str, coin_id: str) -> dict:
    """从 SQLite 读取 CoinGecko coin info 数据。"""
    if not coin_id or not os.path.exists(db_path):
        return {}
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT metrics FROM records "
            "WHERE source='coingecko' AND category='coin' "
            f"AND sub_category='{coin_id}' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if row is None:
            return {}
        return _safe_json(row["metrics"])
    except Exception:
        return {}


def _fetch_protocol_tvl(db_path: str, protocol: str) -> dict:
    """从 SQLite 读取 DeFiLlama protocols 中指定 protocol 的 TVL。

    查询最新和 7 天前的 all_protocols 记录，提取该 protocol 的 TVL。
    """
    if not protocol or not os.path.exists(db_path):
        return {}
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        # 最新一条 all_protocols 记录
        row = conn.execute(
            "SELECT timeseries FROM records "
            "WHERE source='defillama' AND category='protocol' "
            "AND sub_category='all_protocols' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if row is None:
            return {}
        ts = _safe_json(row["timeseries"])
        if not isinstance(ts, list):
            return {}
        # 在 timeseries 中查找指定 protocol
        for p in ts:
            if isinstance(p, dict) and (p.get("slug") == protocol or p.get("name", "").lower() == protocol):
                return {"tvl": float(p.get("tvl") or 0.0), "tvl_7d_ago": None}
        return {}
    except Exception:
        return {}


def _fetch_bdsm_data(db_path: str, source: str) -> dict:
    """从 SQLite 读取 BDSM 原生采集器数据（metrics + raw）。

    查询最新一条 source=bdsm_xxx, category=bdsm 的记录。
    返回 {"metrics": {...}, "raw": {...}}，失败返回空 dict。
    """
    if not source or not os.path.exists(db_path):
        return {}
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT metrics, raw FROM records "
            "WHERE source=? AND category='bdsm' "
            "ORDER BY id DESC LIMIT 1",
            (source,),
        ).fetchone()
        conn.close()
        if row is None:
            return {}
        return {"metrics": _safe_json(row["metrics"]), "raw": _safe_json(row["raw"])}
    except Exception:
        return {}


def _build_fees_by_chain(coin: str, metrics: dict, raw: dict) -> Dict[str, float]:
    """从 BDSM 原生数据构造分链费用字典（E7 输入）。

    - PUMP/HYPE：单链协议 → {chain: annualized_revenue}
    - UNI：协议费用不分链（CoinGecko 只有总量）→ {"ethereum": revenue}
    - AAVE：从 raw.chain_breakdown 构造分链 market_size 代理
    """
    if coin == "PUMP":
        rev = float(metrics.get("annualized_revenue_usd", 0) or 0)
        return {"solana": rev} if rev > 0 else {}
    if coin == "HYPE":
        rev = float(metrics.get("annualized_revenue_usd", 0) or 0)
        return {"hyperliquid": rev} if rev > 0 else {}
    if coin == "UNI":
        rev = float(metrics.get("annualized_protocol_revenue_usd", 0) or 0)
        return {"ethereum": rev} if rev > 0 else {}
    if coin == "AAVE":
        chain_breakdown = raw.get("chain_breakdown", [])
        if isinstance(chain_breakdown, list):
            result = {}
            for cb in chain_breakdown:
                if isinstance(cb, dict):
                    chain = cb.get("chain", "").lower()
                    size = float(cb.get("market_size_usd", 0) or 0)
                    if chain and size > 0:
                        result[chain] = size
            return result
    if coin == "SOL":
        rev = float(metrics.get("annualized_revenue_usd", 0) or 0)
        return {"solana": rev} if rev > 0 else {}
    if coin == "CRCL":
        # Circle USDC 储备组成作为"分链"集中度代理（E7 输入）
        rev = float(metrics.get("annualized_revenue_usd", 0) or 0)
        if rev > 0:
            total_reserves = float(metrics.get("usdc_total_reserves_bln", 0) or 0)
            if total_reserves > 0:
                # 按储备组成分配收入代理
                return {
                    "sii_deposits": rev * float(metrics.get("usdc_sii_deposits_bln", 0)) / total_reserves,
                    "overnight_repo": rev * float(metrics.get("usdc_overnight_repo_bln", 0)) / total_reserves,
                    "treasuries_3m": rev * float(metrics.get("usdc_treasuries_3m_bln", 0)) / total_reserves,
                    "other_bank_deposits": rev * float(metrics.get("usdc_other_bank_deposits_bln", 0)) / total_reserves,
                }
    return {}


def _compute_bdsm_signals(
    coin: str, metrics: dict, raw: dict, info: dict
) -> tuple[float, float, float]:
    """从 BDSM 原生数据计算 E5/E6/E7 三信号。

    Returns:
        (e5, e6, e7)，每个为 [-1.0, +1.0]
    """
    e5 = 0.0
    e6 = 0.0
    e7 = 0.0

    # ── E5: supply shrinkage intensity ──────────────────────────
    circ = float(metrics.get("circulating_supply", 0) or 0)
    max_sup = float(metrics.get("max_supply", 0) or 0)
    has_revenue = 1.0 if float(metrics.get("annualized_revenue_usd", 0) or
                               metrics.get("annualized_protocol_revenue_usd", 0) or 0) > 0 else 0.0
    if circ > 0 and max_sup > 0:
        e5 = compute_supply_shrinkage_intensity(circ, max_sup, 1.0)
    elif "total_supply_offset_pct" in metrics:
        # PUMP: total_supply_offset_pct = 销毁百分比（如 16.354）
        lock = max(0.0, min(1.0, float(metrics["total_supply_offset_pct"]) / 100))
        e5 = max(-1.0, min(1.0, math.tanh(lock * 2.0 + has_revenue * 0.3)))
    elif "burned_pct" in metrics:
        lock = max(0.0, min(1.0, float(metrics["burned_pct"]) / 100))
        e5 = max(-1.0, min(1.0, math.tanh(lock * 2.0 + has_revenue * 0.3)))

    # ── E6: value capture delta (年化收入/市值 归一化) ───────────
    rev = float(metrics.get("annualized_revenue_usd", 0) or
                metrics.get("annualized_protocol_revenue_usd", 0) or 0)
    mcap = float(metrics.get("market_cap_usd", 0) or
                 metrics.get("pump_fdv_usd", 0) or 0)
    if rev > 0 and mcap > 0:
        yield_ratio = rev / mcap
        # 5% 年化收益率 → tanh(0) = 0（中性），> 5% → 正，< 5% → 负
        e6 = max(-1.0, min(1.0, math.tanh((yield_ratio - 0.05) / 0.05)))

    # ── E7: revenue sustainability (分链集中度 + 类型 + 持续性) ──
    fees_by_chain = _build_fees_by_chain(coin, metrics, raw)
    if fees_by_chain:
        e7 = compute_revenue_sustainability(
            fees_by_chain,
            source_type=str(info.get("source_type", "mixed")),
            source_age_days=int(info.get("source_age_days", 365)),
        )

    return e5, e6, e7


# ===========================================================================
# 纯计算函数
# ===========================================================================

def compute_revenue_stability(fees_timeseries: list) -> float:
    """费用 Sharpe ratio → 稳定→正信号。

    Args:
        fees_timeseries: [{"date": "...", "fees_usd": float}, ...]
    Returns:
        [-1.0, +1.0]，Sharpe 越高→越正
    """
    if not fees_timeseries or len(fees_timeseries) < 3:
        return 0.0
    values = []
    for item in fees_timeseries:
        try:
            v = float(item.get("fees_usd", 0))
            if v > 0:
                values.append(v)
        except (TypeError, ValueError):
            continue
    if len(values) < 3:
        return 0.0
    avg = mean(values)
    sd = stdev(values)
    if avg == 0:
        return 0.0
    if sd == 0:
        return 1.0  # 完全稳定（所有值相同）→ 最大正信号
    sharpe = avg / sd
    # Sharpe < 1.5 → 负信号（不稳定），Sharpe > 1.5 → 正信号（稳定）
    return max(-1.0, min(1.0, math.tanh((sharpe - 1.5) / 1.5)))


def compute_mc_fees_mean_reversion(market_cap: float, fees_30d: float) -> float:
    """MC/Fees 比率 → 高估值→负信号。

    ratio = market_cap / fees_30d（类似 P/E）
    log scale 中位数约 log10(30)≈1.5，偏离越大→信号越强（高→负）。

    Returns:
        [-1.0, +1.0]，高估值→负
    """
    if fees_30d <= 0 or market_cap <= 0:
        return 0.0
    ratio = market_cap / fees_30d
    if ratio <= 0:
        return 0.0
    log_ratio = math.log10(ratio)
    # 中位数 1.5（ratio≈31），偏离 0.5 为一个标准差
    deviation = (log_ratio - 1.5) / 0.5
    # 高 ratio → deviation > 0 → signal < 0（负信号）
    return max(-1.0, min(1.0, -math.tanh(deviation)))


def compute_tvl_growth_momentum(tvl_current: float, tvl_7d_ago: float) -> float:
    """TVL 7d 变化率 → 增长→正信号。

    Returns:
        [-1.0, +1.0]，增长→正
    """
    if tvl_7d_ago is None or tvl_7d_ago <= 0 or tvl_current <= 0:
        return 0.0
    growth = (tvl_current - tvl_7d_ago) / tvl_7d_ago
    # 5% 增长 → tanh(1.0) ≈ 0.76
    return max(-1.0, min(1.0, math.tanh(growth / 0.05)))


def compute_revenue_quality(fees_30d_avg: float, tvl: float) -> float:
    """费用/TVL 效率 → 高效→正信号。

    Returns:
        [-1.0, +1.0]，高效率→正
    """
    if tvl <= 0 or fees_30d_avg <= 0:
        return 0.0
    efficiency = fees_30d_avg / tvl
    # 中性点 0.001（0.1% 日效率），低于→负信号，高于→正信号
    return max(-1.0, min(1.0, math.tanh((efficiency - 0.001) / 0.002)))


def compute_supply_shrinkage_intensity(
    circulating_supply: float, max_supply: float, fees_30d: float
) -> float:
    """供给收缩强度 → 通缩→正信号（E5，阶段识别器输入特征）。

    UNI 费用开关销毁案例：费用用于销毁代币 → circulating/max < 1 → 通缩 → 利好。
    锁定比例为主信号，有费用收入（可能用于销毁）为辅助增强。

    Args:
        circulating_supply: 流通供给量
        max_supply: 最大供给量
        fees_30d: 30天费用收入（有费用→可能有销毁机制）
    Returns:
        [-1.0, +1.0]，收缩→正
    """
    if circulating_supply <= 0:
        return 0.0
    base = max_supply if max_supply > 0 else circulating_supply
    if base <= 0:
        return 0.0
    lock_ratio = 1.0 - (circulating_supply / base)
    lock_ratio = max(0.0, min(1.0, lock_ratio))
    # 有费用收入 → 销毁机制可能存在，小幅增强
    has_fees = 1.0 if fees_30d > 0 else 0.0
    return max(-1.0, min(1.0, math.tanh(lock_ratio * 2.0 + has_fees * 0.3)))


def compute_value_capture_delta(
    fees_growth_rate: float, tvl_growth_rate: float
) -> float:
    """价值捕获质变 delta → 费用增长超TVL→正信号（E6，阶段识别器输入特征）。

    UNI Robinhood 接入案例：费用收入大幅增长，超 TVL 增长 → 价值捕获能力提升。
    delta = fees_growth - tvl_growth，正值=盈收扩张强于规模扩张。

    Args:
        fees_growth_rate: 费用增长率（如 30d 首尾对比）
        tvl_growth_rate: TVL 增长率（如 7d 变化率）
    Returns:
        [-1.0, +1.0]，盈收扩张→正
    """
    if fees_growth_rate is None or tvl_growth_rate is None:
        return 0.0
    try:
        delta = float(fees_growth_rate) - float(tvl_growth_rate)
    except (TypeError, ValueError):
        return 0.0
    # 5% 差距 → tanh(1.0) ≈ 0.76
    return max(-1.0, min(1.0, math.tanh(delta / 0.05)))


def compute_revenue_sustainability(
    fees_by_chain: Dict[str, float],
    source_type: str = "mixed",
    source_age_days: int = 365,
) -> float:
    """收入可持续性 → 稳定分散来源→正信号（E7，BDSM RQ 维度）。

    三维度评估（从 UNI 大涨分析框架抽象）：
      1. 集中度：单一来源占比>30%开始惩罚，>80%→0（集中度风险）
         文章案例：UNI 60%来自 RH Chain → 集中度风险
      2. 来源类型：协议盈余(稳定) > 交易手续费(高波动) > 资产收益(中等)
         文章案例：HYPE 交易费 / SKY 协议盈余 / UNI 交易费
      3. 持续性：来源<60天→低持续性（新链风险）
         文章案例：RH Chain 上线<2月 → 低持续性

    Args:
        fees_by_chain: 分链费用 {"robinhood_chain": 925000, "ethereum": 400000}
        source_type: trading_fee / protocol_surplus / asset_yield / mixed
        source_age_days: 主要来源上线天数
    Returns:
        [-1.0, +1.0]，稳定分散来源→正
    """
    if not fees_by_chain:
        return 0.0
    total = sum(v for v in fees_by_chain.values() if v and v > 0)
    if total <= 0:
        return 0.0

    # 1. 集中度评分：max_share <=0.3→1.0, >=0.8→0.0, 线性插值
    max_share = max(v for v in fees_by_chain.values() if v and v > 0) / total
    if max_share <= 0.3:
        concentration_score = 1.0
    elif max_share >= 0.8:
        concentration_score = 0.0
    else:
        concentration_score = 1.0 - (max_share - 0.3) / 0.5

    # 2. 来源类型评分
    _TYPE_SCORES = {
        "protocol_surplus": 1.0,  # 最稳定（SKY）
        "trading_fee": 0.6,      # 高波动但规模大（HYPE/UNI）
        "asset_yield": 0.5,      # 中等
        "mixed": 0.5,
    }
    type_score = _TYPE_SCORES.get(source_type, 0.5)

    # 3. 持续性评分
    if source_age_days >= 180:
        sustainability_score = 1.0
    elif source_age_days >= 60:
        sustainability_score = 0.7
    else:
        sustainability_score = 0.3  # 新来源→低持续性

    # BDS RQ = 集中度40% + 类型30% + 持续性30%
    bds_rq = concentration_score * 0.4 + type_score * 0.3 + sustainability_score * 0.3
    # tanh 归一化，中性点 0.5
    return max(-1.0, min(1.0, math.tanh((bds_rq - 0.5) / 0.25)))


def _calc_growth_rate(timeseries: list) -> Optional[float]:
    """从 timeseries 首尾计算增长率（用于 E6 的 fees_growth_rate）。"""
    if not timeseries or len(timeseries) < 2:
        return None
    try:
        first = float(timeseries[0].get("fees_usd", 0))
        last = float(timeseries[-1].get("fees_usd", 0))
        if first <= 0:
            return None
        return (last - first) / first
    except (TypeError, ValueError, IndexError):
        return None


# ===========================================================================
# L1 链代理指标（BTC/ETH/SOL 等非 DeFi 协议 L1 层）
# E1-E4 替代：矿工费时序 / NVT估值 / 活跃地址增速 / 矿工费哈希率效率
# ===========================================================================

def _fetch_L1_chain_metrics(coin: str, db_path: str) -> dict:
    """从 SQLite data_center.db 读取 L1 链上指标。

    表 source=`chain_onchain` / category=`l1` / sub_category=`l1_{coingecko_id}`
    取最新一条 record 的 timeseries JSON（flat dict）。

    Schema（timeseries dict 中 key 集合，FAIL-OPEN 缺任一安全 0）：
      - miner_fees_timeseries: list[{date, fees_usd}]  ≥7 点（30 天矿工费）
      - miner_fees_30d:       float（30 日矿工费总额 USD）
      - nvt_ratio:            float（当前 NVT = 市值 / 链上 日交易价值）
      - nvt_historical_median:float（NVT 历史中位数，用于 E2 估值回归）
      - active_addresses_now: float（当前日活地址数）
      - active_addresses_7d_ago: float（7 日前日活地址数）
      - hashrate_THs:         float（当前哈希率 TH/s）

    FAIL-OPEN：任何异常 / 无记录 → 自动进入【二级回退 _L1_miner_proxy_fallback】，
    保证 BTC/ETH/SOL 在 DB 未灌入 L1 记录时也能拿到可工作的最小 4 信号集。
    """
    # 一级：SQLite DB 正式记录（权威）
    if coin and db_path and os.path.exists(db_path):
        coin_id = get_coingecko_id(coin)
        if coin_id:
            try:
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT timeseries FROM records "
                    "WHERE source='chain_onchain' AND category='l1' "
                    "AND sub_category=? "
                    "ORDER BY id DESC LIMIT 1",
                    (f"l1_{coin_id}",),
                ).fetchone()
                conn.close()
                if row is not None:
                    ts = _safe_json(row["timeseries"])
                    if isinstance(ts, dict) and ts:
                        return ts
            except Exception:
                pass  # 静默 fall-through → 二级回退

    # 二级：HTTP/K线先验回退（保证「DB 未灌也能产出 L1 最小信号集」）
    try:
        return _L1_miner_proxy_fallback(coin, db_path)
    except Exception:
        return {}


def _L1_miner_proxy_fallback(coin: str, db_path: str) -> dict:
    """L1 代理二级回退：DB 无 l1_* 记录时，从现有可用数据源拼最小可用信号集。

    数据优先级（FAIL-OPEN 按序降级）：
      1. defillama category='chain' chains_summary → 每个 L1 已有的 fees/tvl 全局数据（未来）
      2. OKX 1D K线 USD 成交量 30 日序列 → 矿工费时序代理（波动率同构）
      3. OKX 1D volume_now vs 7d_ago → 活跃地址增速同构代理（成交量=地址×币数）
      4. _L1_NVT_MEDIAN_PRIOR 固定中枢（BTC=25.0），实时 NVT ≈ price×supply / (price×volume_24h ×α)
         → 近似 NVT = 流通市值 / (24h USD 成交量 × 0.30) — 0.30 为「交易所成交量 vs 真实链上
         交易价值」换算系数（BTC 历史公开数据拟合量级）。
      5. _L1_HASH_RATE_PRIOR_THs 量级先验
      6. 缺任何单项 → 返回项不填 → compute_all 独立 FAIL-OPEN 0，不连锁

    Returns: 与 _fetch_L1_chain_metrics 同构 dict；不应抛异常。
    """
    # 0. OKX 1D K 线拉取（最多 35 天，拿足 30d 首尾对比 + 7d 地址代理）
    ts_30: list = []
    now_vol = 0.0
    vol_7d_ago = 0.0
    price_now = 0.0
    price_7d_ago = 0.0
    try:
        import requests  # noqa: WPS433
        cache_key = (coin or "").upper()
        inst_id = f"{cache_key}-USDT-SWAP"
        url = "https://www.okx.com/api/v5/market/history-candles"
        params = {"instId": inst_id, "bar": "1D", "limit": "120"}
        proxies = (
            {"http": _L1_HTTP_PROXY, "https": _L1_HTTP_PROXY}
            if _L1_HTTP_PROXY else None
        )
        data = requests.get(url, params=params, proxies=proxies, timeout=10).json()
        raw = list(reversed(data.get("data", []) or []))
        if len(raw) >= 30:
            # 最近 30 天 daily volume (用 OKX k[7] = volCcyQuote，单位 = USD 计价成交额)
            # 注意：k[5]=vol(基础币数量 BTC/ETH…), k[6]=volCcy(也是基础币，同k5)，k[7]=volCcyQuote(USD)
            ts_30 = []
            total_30 = 0.0
            for k in raw[-30:]:
                try:
                    close_p = float(k[4] or 0.0)
                    vol_USD = float(k[7] or 0.0) if len(k) > 7 else 0.0
                    if vol_USD <= 0 and len(k) > 5:  # 旧 API 回退：vol×close
                        vol_USD = float(k[5] or 0.0) * close_p
                    ts = int(k[0])
                    from datetime import datetime, timezone as _tz  # noqa: WPS433
                    d = datetime.fromtimestamp(ts / 1000, tz=_tz.utc).strftime("%Y-%m-%d")
                    # 矿工费近似：daily USD volume × fee_rate_prior ≈ 日交易量 × 0.2%~0.5% 作为矿工费总额代理
                    # BTC 历史矿工费 / 链上日交易量比率 ≈ 0.003；交易所×链上×chain_frac 的有效系数 ≈ 0.0008
                    # 取 0.001 保证稳定 Sharpe 同构，不会饱和到 1.0
                    daily_fees_proxy_usd = vol_USD * 0.001
                    ts_30.append({"date": d, "fees_usd": daily_fees_proxy_usd})
                    total_30 += daily_fees_proxy_usd
                except (TypeError, ValueError, IndexError):
                    continue
            miner_30d_total = total_30
            # 价格代理（取最近 / 7d 前）
            try:
                price_now = float(raw[-1][4] or 0.0)
                price_7d_ago = float(raw[-8][4] or 0.0)
                # USD 成交量 7 日对比（做活跃地址数增速代理，相关性高）
                _v_now = float(raw[-1][7] or 0.0) if len(raw[-1]) > 7 else 0.0
                _v_7d = float(raw[-8][7] or 0.0) if len(raw[-8]) > 7 else 0.0
                if _v_now <= 0 and len(raw[-1]) > 5:
                    _v_now = float(raw[-1][5] or 0.0) * price_now
                    _v_7d = float(raw[-8][5] or 0.0) * price_7d_ago
                now_vol = _v_now
                vol_7d_ago = _v_7d
            except (IndexError, TypeError, ValueError):
                price_now = 0.0
                price_7d_ago = 0.0
                now_vol = 0.0
                vol_7d_ago = 0.0
        else:
            ts_30 = []
            miner_30d_total = 0.0
            price_now = 0.0
            price_7d_ago = 0.0
    except Exception:
        ts_30 = []
        miner_30d_total = 0.0

    # 1. 取流通市值 & 供给（走既有 _fetch_coin_info / 若空则 K线价格 × coingecko 流通供给量级先验）
    coin_id = get_coingecko_id(coin) or ""
    circulating_supply_proxy: Dict[str, float] = {
        "BTC": 19_700_000.0,
        "ETH": 120_000_000.0,
        "SOL": 580_000_000.0,
        "CRCL": 8_500_000_000.0,
    }
    market_cap_usd = 0.0
    try:
        coin_info = _fetch_coin_info(db_path, coin_id) if (coin_id and os.path.exists(db_path)) else {}
        market_cap_usd = float(coin_info.get("market_cap_usd", 0) or 0)
    except Exception:
        coin_info = {}
    if market_cap_usd <= 0 and price_now > 0:
        market_cap_usd = price_now * circulating_supply_proxy.get(coin.upper(), 1.0)

    # 2. 实时 NVT 近似 = market_cap / (24h chain value)。
    #    关键经验：直接用 chain_frac_prior × 交易所 USD 成交额做链上代理，会低估
    #    链上交易价值（BTC 当前链上日均 ≈ 15~20B USD vs 交易所 USD 成交额 5B）导致 NVT
    #    被算出 1000+ 而饱和到 -1。改用「NVT 等价换算系数」K(coin)：
    #        chain_value ≈ K × USD_Quote_Volume(24h)
    #    取 K≈12/2.4/2.7 使 BTC/ETH/SOL 的 NVT 在当前市价下落在中值 25/22/30 附近，
    #    让 NVT 偏差信号能「围绕 0 有合理 1σ 分布」而非饱和到 ±1。
    #    更长期：DB 有权威 chain_onchain.l1_bitcoin 记录后会覆盖本先验。
    chain_nvt_eq_coeff: Dict[str, float] = {
        "BTC": 12.0,
        "ETH": 2.35,
        "SOL": 2.70,
        "CRCL": 0.30,
    }
    coeff = chain_nvt_eq_coeff.get(coin.upper(), 1.0)
    nvt_now = 0.0
    if market_cap_usd > 0 and now_vol > 0 and coeff > 0:
        nvt_now = market_cap_usd / (now_vol * coeff)
    nvt_median = _L1_NVT_MEDIAN_PRIOR.get(coin.upper(), 30.0)

    # 3. 活跃地址数 proxy：用 K线数据的 USD 成交量**长周期动量**代理地址活跃度。
    #    经验：周同比受周末/单周FOMO脉冲噪声大；30日×30日动量更稳定。
    #    为适配 DeFi `tvl_growth = 5%/0.05 → tanh(1)=0.76` 尺度（BTC 30日成交量动量 ±40% 正常），
    #    用 ±15%/日增长等效尺度：L1 单独的 compute_L1_tvl_growth 函数 — 在 compute_all 侧专用。
    addr_now = 0.0
    addr_7d_ago = 0.0
    try:
        vol_all_full = [float(x[7] or 0.0) if (isinstance(x, list) and len(x) > 7) else 0.0
                        for x in raw]
        # Fallback: 如果 volCcyQuote 都 0，用 vol×close 近似
        _pr_now = float(raw[-1][4] or 0.0) if len(raw) >= 1 and isinstance(raw[-1], list) else 0.0
        if all(v == 0 for v in vol_all_full[-5:]) and _pr_now > 0 and isinstance(raw[-1], list) and len(raw[-1]) > 5:
            vol_all_full = [(float(k[5] or 0.0) * float(k[4] or 0.0)) if isinstance(k, list) else 0.0
                            for k in raw]
        # 优先 90 日：前 30d 日均 vs 60-90d 前的 30d 日均
        if len(vol_all_full) >= 90 and all(v > 0 for v in vol_all_full[-90:]):
            recent = sum(vol_all_full[-30:]) / 30.0
            ancient = sum(vol_all_full[-90:-60]) / 30.0
            if recent > 0 and ancient > 0:
                addr_now = recent
                addr_7d_ago = ancient
        elif len(vol_all_full) >= 60 and all(v > 0 for v in vol_all_full[-60:]):
            recent = sum(vol_all_full[-20:]) / 20.0
            ancient = sum(vol_all_full[-60:-40]) / 20.0
            if recent > 0 and ancient > 0:
                addr_now = recent
                addr_7d_ago = ancient
        elif len(vol_all_full) >= 30 and all(v > 0 for v in vol_all_full[-30:]):
            recent = sum(vol_all_full[-10:]) / 10.0
            ancient = sum(vol_all_full[-30:-20]) / 10.0
            if recent > 0 and ancient > 0:
                addr_now = recent
                addr_7d_ago = ancient
        elif now_vol > 0 and vol_7d_ago > 0:
            addr_now = now_vol
            addr_7d_ago = vol_7d_ago
    except (IndexError, ValueError, TypeError, ZeroDivisionError):
        addr_now = 0.0
        addr_7d_ago = 0.0

    # 4. hashrate_THs 量级先验
    hashrate_prior = _L1_HASH_RATE_PRIOR_THs.get(coin.upper(), 0.0)

    # 5. FAIL-OPEN：只有「非 0 且有效」才填，让上层 compute_all 对缺信号独立兜底
    result: Dict[str, object] = {}
    if ts_30 and len(ts_30) >= 7:
        # 7d 滑窗平滑矿工费代理时序：避免单周 FOMC 周内脉冲使 30d 首尾比冲爆 E6
        def _smooth(series: list) -> list:
            vals = [float(x.get("fees_usd", 0) or 0) for x in series]
            smoothed: list = []
            for i, _ in enumerate(vals):
                lo = max(0, i - 3)
                hi = min(len(vals), i + 4)
                smoothed.append(sum(vals[lo:hi]) / max(1, hi - lo))
            return [
                {"date": series[i].get("date"), "fees_usd": smoothed[i]}
                for i in range(len(series))
            ]

        smooth_ts = _smooth(ts_30)
        result["miner_fees_timeseries"] = smooth_ts
        result["miner_fees_30d"] = float(sum(x["fees_usd"] for x in smooth_ts))
    if nvt_now > 0 and nvt_median > 0:
        result["nvt_ratio"] = float(nvt_now)
        result["nvt_historical_median"] = float(nvt_median)
    if addr_now > 0 and addr_7d_ago > 0:
        result["active_addresses_now"] = float(addr_now)
        result["active_addresses_7d_ago"] = float(addr_7d_ago)
    if hashrate_prior > 0:
        result["hashrate_THs"] = float(hashrate_prior)
    return result


def compute_L1_nvt_mean_reversion(nvt_current: float, nvt_median: float) -> float:
    """L1 NVT 比率估值回归（E2）：NVT 低于历史中值 → 网络价值低估 → 正信号。

    NVT ≈ 网络市值 / 日交易量价值链上（类似 P/E）。
    低 → 估值有支撑 → 正；高 → 泡沫 → 负。

    Args:
        nvt_current: 当前 NVT
        nvt_median:  NVT 历史中位数（>0）

    Returns: [-1, +1]。小于中值 → 正；大于中值 → 负；缺数据/非法 → 0
    """
    if not nvt_current or not nvt_median or nvt_median <= 0 or nvt_current <= 0:
        return 0.0
    # ratio < 1 → 低估 → deviation < 0 → -tanh(负) = 正（符合原 mc_fees_mean_reversion 方向）
    ratio = nvt_current / nvt_median
    deviation = (math.log10(ratio) - 0) / 0.15   # 0.15 log10 ≈ 1.41× 为 1σ 偏离
    return max(-1.0, min(1.0, -math.tanh(deviation)))


def compute_L1_revenue_quality(coin: str,
                               miner_fees_30d_avg: float,
                               hashrate_THs: float) -> float:
    """L1 专属收入质量（E4）：每 TH/s 安全投入能产出多少日均矿工费。"""
    if hashrate_THs <= 0 or miner_fees_30d_avg <= 0:
        return 0.0
    try:
        efficiency = miner_fees_30d_avg / hashrate_THs   # USD / (TH·day)
    except ZeroDivisionError:
        return 0.0
    key = (coin or "").upper()
    neutral = _L1_EFFICIENCY_NEUTRAL.get(key, 0.005)
    scale = _L1_EFFICIENCY_SCALE.get(key, 0.0025)
    if scale <= 0:
        return 0.0
    return max(-1.0, min(1.0, math.tanh((efficiency - neutral) / scale)))


def compute_L1_tvl_growth_momentum(addr_current: float, addr_past: float) -> float:
    """L1 活跃地址（proxy=长周期成交量动量）增速信号。

    与 DeFi TVL 5% 中性不同，L1 成交量 30d×30d 的 ±25% 才属于「强趋势」1σ。
    对应 tanh(±1) ≈ ±0.76；±75% 接近 ±1。
    """
    if addr_past is None or addr_past <= 0 or addr_current <= 0:
        return 0.0
    growth = (addr_current - addr_past) / addr_past   # 30d × 30d 区间内总增长 ≈ 年化/4
    # 25% 区间增速 → 强信号。
    return max(-1.0, min(1.0, math.tanh(growth / 0.25)))


def _L1_calc_dual_slope_growth(timeseries: list) -> Optional[float]:
    """L1 专用稳健增长率：timeseries 前 1/3 段平均 vs 后 1/3 段平均，抗首尾脉冲。

    相比直接「首-尾」能抵抗 2026-08-05 这种 FOMC/地缘事件周的单周尖峰。
    """
    if not isinstance(timeseries, list) or len(timeseries) < 9:
        return None
    vals = [float(x.get("fees_usd", 0) or 0) for x in timeseries if isinstance(x, dict)]
    n = len(vals)
    if n < 9:
        return None
    seg = n // 3
    head_avg = sum(vals[:seg]) / seg
    tail_avg = sum(vals[-seg:]) / seg
    if head_avg <= 0 or tail_avg <= 0:
        return None
    return (tail_avg - head_avg) / head_avg


# ===========================================================================
# 组合函数
# ===========================================================================

def compute_all(coin: str, db_path: str = DEFAULT_DB_PATH) -> Dict[str, float]:
    """计算指定加密货币的七个基本面信号（含 E5/E6/E7 阶段识别器输入）。

    Phase G：E5/E6/E7 优先从 BDSM 原生数据源（项目官网爬虫）计算，
    原四信号仍用 DeFiLlama/CoinGecko 数据。FAIL-OPEN：任何异常 → 对应信号 0.0。
    """
    result = {
        "revenue_stability": 0.0,
        "mc_fees_mean_reversion": 0.0,
        "tvl_growth_momentum": 0.0,
        "revenue_quality": 0.0,
        "supply_shrinkage_intensity": 0.0,   # E5
        "value_capture_delta": 0.0,          # E6
        "revenue_sustainability": 0.0,        # E7 (BDSM RQ)
    }
    try:
        coin_id = get_coingecko_id(coin)
        protocol = get_protocol_mapping(coin)

        # 读取数据（原四信号：DeFiLlama + CoinGecko）
        fees_data = _fetch_protocol_fees(db_path, protocol) if protocol else {}
        coin_data = _fetch_coin_info(db_path, coin_id) if coin_id else {}
        tvl_data = _fetch_protocol_tvl(db_path, protocol) if protocol else {}

        # ---- L1 代理分支 (protocol=None 但 coin 在 CRYPTO_MAP = L1 链) ----
        # BTC/ETH/SOL 等 L1 没有 DeFi protocol_slug，原 fees/tvl 数据 = {}。
        # 这里：如果有 L1 链上指标，把 L1 代理映射到与原四信号同构的输入：
        #   E1 fees_ts                   ← L1.miner_fees_timeseries（同构，直接替换）
        #   E2 mc_fees_mean_reversion     ← L1.NVT 估值分位（专用 compute_L1_nvt_*）
        #   E3 tvl_current/tvl_7d_ago     ← L1.active_addresses（按变量名复用）
        #   E4 fees_30d_avg/tvl           ← L1.miner_fees_30d/30 ÷ hashrate_THs（效率）
        l1_data = {}
        if not protocol and coin_id:          # 是 L1 链，尝试 L1 链上指标
            l1_data = _fetch_L1_chain_metrics(coin, db_path)
            if l1_data:
                # 同构替换 fees/tvl：后续原计算流程不必分支
                miner_ts = l1_data.get("miner_fees_timeseries", [])
                miner_30d = float(l1_data.get("miner_fees_30d", 0) or 0)
                if miner_ts or miner_30d:
                    fees_data = {
                        "timeseries": miner_ts if isinstance(miner_ts, list) else [],
                        "fees_30d": miner_30d,
                    }
                # 活跃地址数 作为 TVL 代理（仅当 TVL 目前为 {} 才覆盖）
                addr_now = float(l1_data.get("active_addresses_now", 0) or 0)
                addr_7d = l1_data.get("active_addresses_7d_ago")
                if addr_now and addr_7d is not None:
                    tvl_data = {
                        "tvl": addr_now,
                        "tvl_7d_ago": (
                            float(addr_7d) if isinstance(addr_7d, (int, float, str)) and
                            float(addr_7d) > 0 else None
                        ),
                    }

        # 🆕 Phase G: 读取 BDSM 原生数据（项目官网爬虫）
        bdsm_info = _BDSM_SOURCE_MAP.get(coin)
        bdsm_data = {}
        if bdsm_info:
            bdsm_data = _fetch_bdsm_data(db_path, str(bdsm_info["source"]))

        # 1. Revenue Stability
        fees_ts = fees_data.get("timeseries", [])
        result["revenue_stability"] = compute_revenue_stability(fees_ts)

        # 2. MC/Fees Mean Reversion  →  L1 走 NVT 估值专用函数（优先）
        market_cap = float(coin_data.get("market_cap_usd", 0))
        fees_30d = float(fees_data.get("fees_30d", 0))
        if l1_data:
            nvt = float(l1_data.get("nvt_ratio", 0) or 0)
            nvt_med = float(l1_data.get("nvt_historical_median", 0) or 0)
            if nvt > 0 and nvt_med > 0:
                result["mc_fees_mean_reversion"] = compute_L1_nvt_mean_reversion(nvt, nvt_med)
            else:
                result["mc_fees_mean_reversion"] = compute_mc_fees_mean_reversion(
                    market_cap, fees_30d
                )
        else:
            result["mc_fees_mean_reversion"] = compute_mc_fees_mean_reversion(
                market_cap, fees_30d
            )

        # 3. TVL Growth Momentum
        #   DeFi 币：TVL 7d 增速同构 compute_tvl_growth_momentum (1σ=5%)
        #   L1 币：长周期成交量动量（90/60/30d 尺度）→ L1 专用 1σ=25%（避免周内脉冲饱和）
        tvl_current = float(tvl_data.get("tvl", 0))
        tvl_7d_ago = tvl_data.get("tvl_7d_ago")
        if l1_data:
            result["tvl_growth_momentum"] = compute_L1_tvl_growth_momentum(
                tvl_current, tvl_7d_ago
            )
        else:
            result["tvl_growth_momentum"] = compute_tvl_growth_momentum(
                tvl_current, tvl_7d_ago
            )

        # 4. Revenue Quality
        # fees_30d_avg = fees_30d / 30（日均矿工费 / 协议费）
        fees_30d_avg = fees_30d / 30.0 if fees_30d > 0 else 0.0
        if l1_data:
            # L1 专用：分币种 TH/s 矿工费效率（避免 DeFi fees/tvl 中性 0.001 错配）
            hashrate = float(l1_data.get("hashrate_THs", 0) or 0)
            result["revenue_quality"] = compute_L1_revenue_quality(
                coin, fees_30d_avg, hashrate
            )
        else:
            result["revenue_quality"] = compute_revenue_quality(fees_30d_avg, tvl_current)

        # 5-7. E5/E6/E7 — 优先 BDSM 原生数据，回退原计算
        bdsm_computed = False
        if bdsm_data and bdsm_info:
            bdsm_metrics = bdsm_data.get("metrics", {})
            bdsm_raw = bdsm_data.get("raw", {})
            if bdsm_metrics:
                e5, e6, e7 = _compute_bdsm_signals(
                    coin, bdsm_metrics, bdsm_raw, bdsm_info
                )
                result["supply_shrinkage_intensity"] = e5
                result["value_capture_delta"] = e6
                result["revenue_sustainability"] = e7
                bdsm_computed = True

        if not bdsm_computed:
            # 回退：原 DeFiLlama/CoinGecko 计算
            # 5. Supply Shrinkage Intensity (E5)
            circulating_supply = float(coin_data.get("circulating_supply", 0))
            max_supply = float(coin_data.get("max_supply", 0))
            result["supply_shrinkage_intensity"] = compute_supply_shrinkage_intensity(
                circulating_supply, max_supply, fees_30d
            )

            # 6. Value Capture Delta (E6)
            # L1 专用：_L1_calc_dual_slope_growth → 30×90d 的双段稳健增长率（抗首尾脉冲）
            tvl_growth_rate = None
            if tvl_current > 0 and tvl_7d_ago is not None and tvl_7d_ago > 0:
                tvl_growth_rate = (tvl_current - tvl_7d_ago) / tvl_7d_ago
            if l1_data:
                fees_growth_rate = _L1_calc_dual_slope_growth(fees_ts)
                # L1 变化率尺度更大：fees_growth × 90d 双段 正常 ±50%，tvl_growth × 30d×2 正常 ±25%
                # scale 0.60 让 50%~60% δ ≈ tanh(1)=0.76；±180%~≈±1 极端（危机/小牛尾）
                if fees_growth_rate is None or tvl_growth_rate is None:
                    result["value_capture_delta"] = 0.0
                else:
                    try:
                        delta = float(fees_growth_rate) - float(tvl_growth_rate)
                    except (TypeError, ValueError):
                        delta = 0.0
                    result["value_capture_delta"] = max(
                        -1.0, min(1.0, math.tanh(delta / 0.60))
                    )
            else:
                fees_growth_rate = _calc_growth_rate(fees_ts)
                result["value_capture_delta"] = compute_value_capture_delta(
                    fees_growth_rate, tvl_growth_rate
                )

            # 7. Revenue Sustainability (E7) — 无 BDSM 数据时保持 0.0（中性）

        # 8. E8 板块横向估值（Cross-Sector Valuation）
        # 区分「自身高估」vs「板块共振」，与纵向 valuation_percentile 交叉验证
        try:
            result["e8_cross_sector_valuation"] = compute_e8_cross_sector_valuation(
                coin, db_path
            )
        except Exception:
            result["e8_cross_sector_valuation"] = 0.0  # FAIL-OPEN

    except Exception:
        pass  # FAIL-OPEN：全部保持 0.0

    return result
