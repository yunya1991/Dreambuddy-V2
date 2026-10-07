"""同赛道估值对比 §4.3 — 全赛道低估扫描器。

从所有赛道中挖掘「被低估 + 具备跟涨潜力」的币种，输出排序候选清单。

核心逻辑：
  1. 遍历所有 SECTOR_MAP 赛道
  2. 对赛道内每个币调用 compute_multi_dim_valuation 拿低估分
  3. 过滤 undervalued_score > 0.3 的币（R3 多维交叉验证）
  4. 计算 opportunity_score = undervalued_score * 0.6 + catalyst * 0.4（仅当两者都 > 0）
  5. 按 opportunity_score 降序输出 Top N

铁律遵循：
  - R3 多维交叉验证：undervalued_score 来自 multi_dim_valuation，已含 ≥2 维 < 40 确认
  - R4 FAIL-OPEN：异常返回空 scan，不阻塞主链路
  - R5 跟涨需龙头动量确认：catalyst 已含 leader_momentum × sector_breadth
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

# 复用已有模块（from import 形式，便于测试 mock）
from force_vector.coin_fundamental_crypto import SECTOR_MAP, DEFAULT_DB_PATH
from force_vector.multi_dim_valuation import compute_multi_dim_valuation
from force_vector.follow_up_catalyst import compute_follow_up_catalyst

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 阈值与权重
# ---------------------------------------------------------------------------

# 进入低估候选的最低 undervalued_score（SPEC §4.3 步骤 3）
_UNDERVALUED_THRESHOLD = 0.3

# opportunity_score 权重（SPEC §4.3 公式 4）
_UNDERVALUED_WEIGHT = 0.6
_CATALYST_WEIGHT = 0.4

# rank 体系阈值（同 BDSM rank）
_RANK_S_THRESHOLD = 0.7
_RANK_A_THRESHOLD = 0.5
_RANK_B_THRESHOLD = 0.3

# Top N 输出上限
_TOP_N_DEFAULT = 20


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class UndervaluedCoin:
    """赛道低估候选币（SPEC §4.3）。

    Attributes:
        coin: 币符号（如 "UNI"）
        sector: 所属赛道（如 "DEX"）
        undervalued_score: 多维低估分 [-1, +1]，来自 multi_dim_valuation
        multi_dim_details: 各维度横向百分位 {mc_fees_pct, mc_tvl_pct, peg_pct}
        leader_momentum: 赛道龙头 7d 动量归一化 [-1, +1]
        opportunity_score: 综合潜力分 [0, 1]，越大越优
        rank: 排名等级 S/A/B/C
    """
    coin: str
    sector: str
    undervalued_score: float
    multi_dim_details: Dict[str, float]
    leader_momentum: float
    opportunity_score: float
    rank: str


@dataclass
class SectorUndervaluedScan:
    """全赛道低估扫描结果（SPEC §4.3）。

    Attributes:
        timestamp: ISO 格式时间戳
        sectors: 赛道 → 低估币列表
        top_opportunities: 全赛道 Top N 潜力币（按 opportunity_score 降序）
    """
    timestamp: str
    sectors: Dict[str, List[UndervaluedCoin]] = field(default_factory=dict)
    top_opportunities: List[UndervaluedCoin] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------

def compute_opportunity_score(undervalued_score: float, catalyst: float) -> float:
    """计算综合潜力分（SPEC §4.3 公式 4）。

    opportunity_score = undervalued_score * 0.6 + catalyst * 0.4
    仅当 undervalued_score > 0 且 catalyst > 0 时计算，否则返回 0.0

    Args:
        undervalued_score: 多维低估分 [-1, +1]
        catalyst: 跟涨催化因子 [-1, +1]

    Returns:
        综合潜力分 [0, 1]
    """
    if undervalued_score <= 0 or catalyst <= 0:
        return 0.0
    score = undervalued_score * _UNDERVALUED_WEIGHT + catalyst * _CATALYST_WEIGHT
    # 钳制到 [0, 1]
    return max(0.0, min(1.0, score))


def compute_rank(score: float) -> str:
    """根据 opportunity_score 计算 rank 等级（同 BDSM rank）。

    Args:
        score: opportunity_score [0, 1]

    Returns:
        S(>=0.7) / A(>=0.5) / B(>=0.3) / C(其他)
    """
    if score >= _RANK_S_THRESHOLD:
        return "S"
    if score >= _RANK_A_THRESHOLD:
        return "A"
    if score >= _RANK_B_THRESHOLD:
        return "B"
    return "C"


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def scan_sector_undervalued(
    db_path: Optional[str] = None,
    top_n: int = _TOP_N_DEFAULT,
) -> SectorUndervaluedScan:
    """扫描全赛道低估候选（SPEC §4.3）。

    流程：
      1. 遍历 SECTOR_MAP 所有赛道
      2. 对赛道内每个币调用 compute_multi_dim_valuation
      3. 过滤 undervalued_score > 0.3
      4. 调用 compute_follow_up_catalyst 拿赛道级 catalyst
      5. 计算 opportunity_score 并赋 rank
      6. 跨赛道合并、按 opportunity_score 降序、输出 Top N

    Args:
        db_path: data_center.db 路径；None 用 DEFAULT_DB_PATH
        top_n: Top N 输出上限

    Returns:
        SectorUndervaluedScan；异常时返回空 scan（FAIL-OPEN）
    """
    if not db_path:
        db_path = DEFAULT_DB_PATH

    timestamp = datetime.now(timezone.utc).isoformat()

    try:
        sectors: Dict[str, List[UndervaluedCoin]] = {}
        all_candidates: List[UndervaluedCoin] = []

        for sector, coins in SECTOR_MAP.items():
            if not coins:
                continue

            # 赛道级 catalyst（每赛道一次）
            try:
                catalyst_result = compute_follow_up_catalyst(sector, db_path)
                catalyst = float(catalyst_result.get("catalyst", 0.0))
                leader_momentum = float(catalyst_result.get("leader_momentum", 0.0))
            except Exception:
                catalyst = 0.0
                leader_momentum = 0.0

            sector_undervalued: List[UndervaluedCoin] = []

            for coin in coins:
                try:
                    multi_dim = compute_multi_dim_valuation(coin, db_path)
                    undervalued_score = float(multi_dim.get("multi_dim_score", 0.0))
                except Exception:
                    undervalued_score = 0.0
                    multi_dim = {}

                # 硬过滤：undervalued_score > 0.3 才进入候选
                if undervalued_score <= _UNDERVALUED_THRESHOLD:
                    continue

                # 各维度百分位详情
                multi_dim_details = {
                    "mc_fees_pct": float(multi_dim.get("mc_fees_pct", 0.0)),
                    "mc_tvl_pct": float(multi_dim.get("mc_tvl_pct", 0.0)),
                    "peg_pct": float(multi_dim.get("peg_pct", 0.0)),
                }

                opportunity = compute_opportunity_score(undervalued_score, catalyst)
                rank = compute_rank(opportunity)

                candidate = UndervaluedCoin(
                    coin=coin,
                    sector=sector,
                    undervalued_score=undervalued_score,
                    multi_dim_details=multi_dim_details,
                    leader_momentum=leader_momentum,
                    opportunity_score=opportunity,
                    rank=rank,
                )
                sector_undervalued.append(candidate)
                all_candidates.append(candidate)

            if sector_undervalued:
                sectors[sector] = sector_undervalued

        # 跨赛道合并 + 降序 + Top N
        all_candidates.sort(key=lambda c: c.opportunity_score, reverse=True)
        top_opportunities = all_candidates[:top_n]

        return SectorUndervaluedScan(
            timestamp=timestamp,
            sectors=sectors,
            top_opportunities=top_opportunities,
        )

    except Exception as e:
        logger.warning("scan_sector_undervalued FAIL-OPEN: %s", e)
        return SectorUndervaluedScan(
            timestamp=timestamp,
            sectors={},
            top_opportunities=[],
        )
