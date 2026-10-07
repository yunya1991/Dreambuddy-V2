"""TDD-SVC-002: 多维度相对估值（Multi-dim Valuation）。

> 版本: v1.0 (TDD-SVC-002 GREEN)
> SPEC: docs/superpowers/specs/2026-10-07-sector-valuation-comparison-spec.md §4.4

设计决策（SPEC §4.4）：
  多维估值合成 MC/Fees + MC/TVL + PEG，比单一 MC/Fees 更能识别真实低估。
  权重：MC/Fees 0.5（主维度，复用 E8 逻辑）/ MC/TVL 0.3（DeFi 专用）/ PEG 0.2（增长调整）

合成公式（SPEC §3.2 指标 2）：
  multi_dim_score = 1.0 - (weighted_pct / 50.0)
    映射到 [-1, +1]，与 E8 一致
  score > 0.3：多维低估
  score < -0.3：多维高估

铁律（SPEC §0.2）：
  R1 赛道内对比（横向百分位在同赛道内计算）
  R3 多维交叉验证：低估判断需至少 2 个维度同时 < 40 百分位才确认
  R4 FAIL-OPEN：数据不足不触发信号

权重归一化（SPEC §7.2 FAIL-OPEN）：
  缺数据维度权重置 0，剩余维度权重归一化到 1.0

调用复用：
  - SECTOR_MAP / _SECTOR_COIN_META / _fetch_coin_info / _fetch_protocol_fees / _fetch_protocol_tvl
    （coin_fundamental_crypto，不修改 E8）
  - _calc_growth_rate（coin_fundamental_crypto，计算 fees 增长率用于 PEG）
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from force_vector.coin_fundamental_crypto import (  # noqa: E402
    SECTOR_MAP,
    _SECTOR_COIN_META,
    _fetch_coin_info,
    _fetch_protocol_fees,
    _fetch_protocol_tvl,
    _fetch_sector_valuation_ratios,
    _calc_growth_rate,
    DEFAULT_DB_PATH,
)
from force_vector.coin_fundamental_ranker import get_protocol_mapping  # noqa: E402


# ---------------------------------------------------------------------------
# 常量（SPEC §4.4）
# ---------------------------------------------------------------------------

# 默认维度权重：MC/Fees 0.5 / MC/TVL 0.3 / PEG 0.2
_DEFAULT_WEIGHTS: Dict[str, float] = {
    "mc_fees": 0.5,
    "mc_tvl": 0.3,
    "peg": 0.2,
}

# 低估确认阈值：维度百分位 < 40 视为该维度低估
_LOW_DIM_THRESHOLD = 40.0
# 确认低估所需的最小维度数（R3 多维交叉验证）
_MIN_LOW_DIMS_FOR_CONFIRM = 2

# 多维低估/高估分数阈值
_UNDervalued_SCORE_THRESHOLD = 0.3
_OVERVALUED_SCORE_THRESHOLD = -0.3


# ---------------------------------------------------------------------------
# 纯函数：从各维度百分位合成分数
# ---------------------------------------------------------------------------

def compute_multi_dim_score_from_percentiles(
    pcts: Dict[str, float],
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """从各维度横向百分位合成多维估值分数。

    Args:
        pcts: 各维度横向百分位，如 {"mc_fees": 20.0, "mc_tvl": 25.0, "peg": 30.0}
            缺数据的维度不传入或传 None。
        weights: 各维度权重，None 用默认 {"mc_fees": 0.5, "mc_tvl": 0.3, "peg": 0.2}

    Returns:
        Dict 包含：
          - mc_fees_pct / mc_tvl_pct / peg_pct: 各维度百分位（缺数据为 0.0）
          - multi_dim_score: 合成分数 [-1, +1]，>0 低估
          - confirmed_low: 是否确认多维低估（≥2 维度 < 40）
          - dimensions_available: 可用维度数

    合成公式：
      1. 过滤有效维度（百分位在 [0, 100]）
      2. 权重归一化：缺数据维度权重置 0，剩余权重归一化到 1.0
      3. weighted_pct = sum(归一化权重_i * pct_i)
      4. multi_dim_score = 1.0 - weighted_pct/50，clamp 到 [-1, +1]
      5. confirmed_low: 统计 pct < 40 的维度数，≥2 → True
    """
    if weights is None:
        weights = dict(_DEFAULT_WEIGHTS)

    # 收集有效维度（百分位在 [0, 100]）
    valid_dims: Dict[str, float] = {}
    for dim, pct in pcts.items():
        if pct is None:
            continue
        try:
            v = float(pct)
        except (TypeError, ValueError):
            continue
        if 0.0 <= v <= 100.0:
            valid_dims[dim] = v

    # 构造返回的百分位字段（缺数据维度为 0.0）
    result: Dict[str, float] = {
        "mc_fees_pct": valid_dims.get("mc_fees", 0.0),
        "mc_tvl_pct": valid_dims.get("mc_tvl", 0.0),
        "peg_pct": valid_dims.get("peg", 0.0),
        "multi_dim_score": 0.0,
        "confirmed_low": False,
        "dimensions_available": len(valid_dims),
    }

    if not valid_dims:
        return result  # FAIL-OPEN：无数据 → score = 0.0

    # 权重归一化：缺数据维度权重置 0，剩余归一化到 1.0
    total_weight = sum(weights.get(dim, 0.0) for dim in valid_dims)
    if total_weight <= 0:
        return result  # FAIL-OPEN：权重全 0

    # 计算 weighted_pct
    weighted_pct = 0.0
    for dim, pct in valid_dims.items():
        w = weights.get(dim, 0.0) / total_weight  # 归一化
        weighted_pct += w * pct

    # 合成分数：multi_dim_score = 1.0 - weighted_pct/50
    score = 1.0 - (weighted_pct / 50.0)
    score = max(-1.0, min(1.0, score))

    # R3 多维交叉验证：≥2 维度 < 40 才确认低估
    low_dim_count = sum(1 for pct in valid_dims.values() if pct < _LOW_DIM_THRESHOLD)
    confirmed_low = (
        low_dim_count >= _MIN_LOW_DIMS_FOR_CONFIRM
        and score > _UNDervalued_SCORE_THRESHOLD
    )

    result["multi_dim_score"] = score
    result["confirmed_low"] = confirmed_low
    return result


# ---------------------------------------------------------------------------
# 数据获取：各维度横向百分位
# ---------------------------------------------------------------------------

def _compute_percentile_in_sector(
    target_coin: str, ratios: Dict[str, float]
) -> Optional[float]:
    """计算 target coin 的比率在赛道内的横向百分位 [0, 100]。

    复用 E8 的百分位计算逻辑：pct = (比 target 便宜的占比) * 100

    Args:
        target_coin: 目标币大写
        ratios: {coin_upper: ratio} 赛道内各币的比率

    Returns:
        百分位 [0, 100]，None 表示无数据
    """
    if not ratios or len(ratios) < 3:
        return None

    target_upper = (target_coin or "").upper()
    target_ratio = ratios.get(target_upper)
    if target_ratio is None:
        return None

    # 横向百分位：比 target 便宜（ratio 更小）的占比
    sorted_ratios = sorted(ratios.values())
    cheaper_count = sum(1 for r in sorted_ratios if r < target_ratio)
    pct = (cheaper_count / len(sorted_ratios)) * 100.0
    return max(0.0, min(100.0, pct))


def _fetch_sector_mc_tvl_ratios(sector: str, db_path: str) -> Dict[str, float]:
    """获取赛道内各币的 MC/TVL 比率（仅 DeFi，L1 返回空）。

    MC/TVL = market_cap_usd / tvl
    返回 {coin_upper: mc_tvl_ratio}，仅包含成功获取数据的币。
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
            if not coin_id or not slug:
                continue  # L1 无 TVL，跳过

            coin_info = _fetch_coin_info(db_path, coin_id) if coin_id else {}
            mcap = float(coin_info.get("market_cap_usd", 0) or 0)
            if mcap <= 0:
                continue

            tvl_data = _fetch_protocol_tvl(db_path, slug) if slug else {}
            tvl = float(tvl_data.get("tvl", 0) or 0)
            if tvl <= 0:
                continue

            ratios[member] = mcap / tvl
        except Exception:
            continue  # FAIL-OPEN：单个币失败不影响其他

    return ratios


def _fetch_sector_peg_ratios(sector: str, db_path: str) -> Dict[str, float]:
    """获取赛道内各币的 PEG 比率 = (MC/Fees) / Fees_Growth。

    PEG = (MC/Fees) / fees_growth_rate
    高增长（fees_growth 大）→ PEG 小 → 低估
    低增长 / 负增长 → PEG 大 / 负 → 高估 / 无意义

    返回 {coin_upper: peg_ratio}，仅包含成功获取数据的币。
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
            if not coin_id or not slug:
                continue  # L1 无 fees，跳过

            coin_info = _fetch_coin_info(db_path, coin_id) if coin_id else {}
            mcap = float(coin_info.get("market_cap_usd", 0) or 0)
            if mcap <= 0:
                continue

            fees_data = _fetch_protocol_fees(db_path, slug) if slug else {}
            fees_30d = float(fees_data.get("fees_30d", 0) or 0)
            if fees_30d <= 0:
                continue

            mc_fees = mcap / fees_30d
            # 费用增长率（30d 首尾对比）
            fees_ts = fees_data.get("timeseries", [])
            growth = _calc_growth_rate(fees_ts) if fees_ts else None
            if growth is None or growth <= 0:
                continue  # 负增长或无数据 → PEG 无意义

            ratios[member] = mc_fees / growth
        except Exception:
            continue  # FAIL-OPEN：单个币失败不影响其他

    return ratios


def _fetch_dimension_percentiles(coin: str, db_path: str) -> Dict[str, float]:
    """获取 target coin 在赛道内的各维度横向百分位。

    Args:
        coin: 目标币符号（如 "UNI"）
        db_path: data_center.db 路径

    Returns:
        {"mc_fees": pct, "mc_tvl": pct, "peg": pct}
        缺数据的维度不返回。
    """
    result: Dict[str, float] = {}

    # 找 target coin 所属赛道
    coin_upper = (coin or "").upper()
    sector: Optional[str] = None
    for s, members in SECTOR_MAP.items():
        if coin_upper in members:
            sector = s
            break
    if sector is None:
        return result  # 不在任何赛道 → FAIL-OPEN

    # 维度 1: MC/Fees（L1 用 NVT）— 复用 E8 的 _fetch_sector_valuation_ratios
    try:
        mc_fees_ratios = _fetch_sector_valuation_ratios(sector, db_path)
        mc_fees_pct = _compute_percentile_in_sector(coin_upper, mc_fees_ratios)
        if mc_fees_pct is not None:
            result["mc_fees"] = mc_fees_pct
    except Exception:
        pass  # FAIL-OPEN

    # 维度 2: MC/TVL（仅 DeFi）
    try:
        mc_tvl_ratios = _fetch_sector_mc_tvl_ratios(sector, db_path)
        mc_tvl_pct = _compute_percentile_in_sector(coin_upper, mc_tvl_ratios)
        if mc_tvl_pct is not None:
            result["mc_tvl"] = mc_tvl_pct
    except Exception:
        pass  # FAIL-OPEN

    # 维度 3: PEG (MC/Fees / Fees_Growth)
    try:
        peg_ratios = _fetch_sector_peg_ratios(sector, db_path)
        peg_pct = _compute_percentile_in_sector(coin_upper, peg_ratios)
        if peg_pct is not None:
            result["peg"] = peg_pct
    except Exception:
        pass  # FAIL-OPEN

    return result


# ---------------------------------------------------------------------------
# 主函数：compute_multi_dim_valuation
# ---------------------------------------------------------------------------

def compute_multi_dim_valuation(
    coin: str, db_path: Optional[str] = None
) -> Dict[str, float]:
    """计算 target coin 的多维度相对估值（SPEC §4.4）。

    流程：
      1. _fetch_dimension_percentiles 获取各维度横向百分位
      2. compute_multi_dim_score_from_percentiles 合成分数
      3. FAIL-OPEN：任何异常 → 返回中性结果

    Args:
        coin: 目标币符号（如 "UNI"）
        db_path: data_center.db 路径；None 用 DEFAULT_DB_PATH

    Returns:
        Dict 包含：
          - mc_fees_pct / mc_tvl_pct / peg_pct: 各维度百分位
          - multi_dim_score: 合成分数 [-1, +1]，>0 低估
          - confirmed_low: 是否确认多维低估（≥2 维度 < 40）
          - dimensions_available: 可用维度数
    """
    if not db_path:
        db_path = DEFAULT_DB_PATH

    try:
        pcts = _fetch_dimension_percentiles(coin, db_path)
        return compute_multi_dim_score_from_percentiles(pcts)
    except Exception:
        # FAIL-OPEN：任何异常 → 中性结果
        return {
            "mc_fees_pct": 0.0,
            "mc_tvl_pct": 0.0,
            "peg_pct": 0.0,
            "multi_dim_score": 0.0,
            "confirmed_low": False,
            "dimensions_available": 0,
        }
