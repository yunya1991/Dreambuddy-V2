"""同赛道估值对比 §4.6 — 顶层编排器。

整合 sector_waterline + sector_undervalued_scanner + multi_dim_valuation + follow_up_catalyst，
输出 G1（低估潜力币）、G2（赛道水位）、G3（过热做空信号）三类信号。

输出契约：
  - G1 waterlines: List[SectorWaterline]  赛道水位
  - G2 undervalued_scan: SectorUndervaluedScan  低估候选
  - G3 overheat_signals: List[SectorOverheatSignal]  过热做空信号

铁律遵循：
  - R2 中位数优先：waterline 来自 sector_waterline 的中位数
  - R3 多维交叉验证：scanner 已含 ≥2 维 < 40 确认
  - R4 FAIL-OPEN：异常返回中性结果，不阻塞 BDSM 快照生成
  - R5 跟涨需龙头动量确认：catalyst 已含 leader_momentum
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

# 复用已有模块（from import 形式，便于测试 mock）
from force_vector.coin_fundamental_crypto import SECTOR_MAP, DEFAULT_DB_PATH
from force_vector.sector_waterline import compute_sector_waterline, SectorWaterline
from force_vector.sector_undervalued_scanner import scan_sector_undervalued, SectorUndervaluedScan
from force_vector.multi_dim_valuation import compute_multi_dim_valuation

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 阈值
# ---------------------------------------------------------------------------

# G3 过热信号三重确认阈值（SPEC §5.3）
_OVERHEAT_WATERLINE_THRESHOLD = 85.0      # 条件1：水位 >= 85
_OVERHEAT_LEADER_MOMENTUM_THRESHOLD = -0.1  # 条件2：龙头动量 < -0.1
_OVERHEAT_OVERVALUED_RATIO_THRESHOLD = 0.6  # 条件3：高估币占比 >= 0.6

# 高估币判定：undervalued_score < -0.3
_OVERVALUED_SCORE_THRESHOLD = -0.3

# confidence 计算：waterline 85-100 映射到 0-1
_CONFIDENCE_SCALE = 15.0


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class SectorOverheatSignal:
    """赛道过热做空信号（SPEC §5.3）。

    三重确认触发（AND）：
      1. waterline >= 85（赛道严重过热）
      2. leader_momentum < -0.1（龙头开始转弱）
      3. overvalued_ratio >= 0.6（赛道内 ≥ 60% 币多维高估）

    Attributes:
        sector: 赛道名
        waterline: 赛道水位（median_percentile）
        leader_momentum: 龙头 7d 动量归一化 [-1, +1]
        overvalued_ratio: 赛道内 undervalued_score < -0.3 的币占比 [0, 1]
        confidence: 信号置信度 [0, 1]
    """
    sector: str
    waterline: float
    leader_momentum: float
    overvalued_ratio: float
    confidence: float


@dataclass
class SectorValuationResult:
    """编排器输出（SPEC §4.6）。

    Attributes:
        timestamp: ISO 格式时间戳
        waterlines: 所有赛道水位（G2）
        undervalued_scan: 低估扫描结果（G1）
        overheat_signals: 过热做空信号（G3）
    """
    timestamp: str
    waterlines: List[SectorWaterline] = field(default_factory=list)
    undervalued_scan: Optional[SectorUndervaluedScan] = None
    overheat_signals: List[SectorOverheatSignal] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------

def compute_overvalued_ratio(scores: List[float]) -> float:
    """计算赛道内 undervalued_score < -0.3 的币占比。

    Args:
        scores: 赛道内所有币的 multi_dim_score 列表

    Returns:
        高估币占比 [0, 1]；空列表返回 0.0
    """
    if not scores:
        return 0.0
    overvalued_count = sum(1 for s in scores if s < _OVERVALUED_SCORE_THRESHOLD)
    return overvalued_count / len(scores)


def should_trigger_overheat(
    waterline: float,
    leader_momentum: float,
    overvalued_ratio: float,
) -> bool:
    """判断是否触发过热做空信号（SPEC §5.3 三重 AND）。

    Args:
        waterline: 赛道水位
        leader_momentum: 龙头 7d 动量
        overvalued_ratio: 高估币占比

    Returns:
        True 触发；False 不触发
    """
    if waterline < _OVERHEAT_WATERLINE_THRESHOLD:
        return False
    if leader_momentum >= _OVERHEAT_LEADER_MOMENTUM_THRESHOLD:
        return False
    if overvalued_ratio < _OVERHEAT_OVERVALUED_RATIO_THRESHOLD:
        return False
    return True


def _compute_confidence(waterline: float) -> float:
    """计算过热信号置信度：waterline 85-100 映射到 0-1。

    Args:
        waterline: 赛道水位

    Returns:
        置信度 [0, 1]
    """
    if waterline <= _OVERHEAT_WATERLINE_THRESHOLD:
        return 0.0
    confidence = (waterline - _OVERHEAT_WATERLINE_THRESHOLD) / _CONFIDENCE_SCALE
    return max(0.0, min(1.0, confidence))


# ---------------------------------------------------------------------------
# 编排器
# ---------------------------------------------------------------------------

class SectorValuationOrchestrator:
    """同赛道估值对比编排器（SPEC §4.6）。

    整合 waterline + scanner + multi_dim + catalyst，
    输出 G1（低估潜力币）、G2（赛道水位）、G3（过热做空信号）。
    """

    def run(self, db_path: Optional[str] = None) -> SectorValuationResult:
        """执行编排，返回三类信号。

        Args:
            db_path: data_center.db 路径；None 用 DEFAULT_DB_PATH

        Returns:
            SectorValuationResult；异常时返回中性结果（FAIL-OPEN）
        """
        if not db_path:
            db_path = DEFAULT_DB_PATH

        timestamp = datetime.now(timezone.utc).isoformat()

        try:
            # G2: 赛道水位
            waterlines: List[SectorWaterline] = []
            for sector in SECTOR_MAP.keys():
                try:
                    wl = compute_sector_waterline(sector, db_path)
                    if wl is not None:
                        waterlines.append(wl)
                except Exception as e:
                    logger.warning("waterline fail-open for %s: %s", sector, e)

            # G1: 低估扫描
            try:
                undervalued_scan = scan_sector_undervalued(db_path)
            except Exception as e:
                logger.warning("scanner fail-open: %s", e)
                undervalued_scan = SectorUndervaluedScan(
                    timestamp=timestamp, sectors={}, top_opportunities=[]
                )

            # G3: 过热做空信号（遍历每个赛道）
            overheat_signals: List[SectorOverheatSignal] = []
            for wl in waterlines:
                try:
                    sector = wl.sector
                    sector_coins = SECTOR_MAP.get(sector, [])

                    # 收集赛道内所有币的 multi_dim_score
                    scores: List[float] = []
                    for coin in sector_coins:
                        try:
                            md = compute_multi_dim_valuation(coin, db_path)
                            scores.append(float(md.get("multi_dim_score", 0.0)))
                        except Exception:
                            scores.append(0.0)

                    overvalued_ratio = compute_overvalued_ratio(scores)

                    if should_trigger_overheat(
                        waterline=wl.median_percentile,
                        leader_momentum=wl.leader_momentum_7d,
                        overvalued_ratio=overvalued_ratio,
                    ):
                        confidence = _compute_confidence(wl.median_percentile)
                        overheat_signals.append(SectorOverheatSignal(
                            sector=sector,
                            waterline=wl.median_percentile,
                            leader_momentum=wl.leader_momentum_7d,
                            overvalued_ratio=overvalued_ratio,
                            confidence=confidence,
                        ))
                except Exception as e:
                    logger.warning("overheat detection fail-open for %s: %s", sector, e)

            return SectorValuationResult(
                timestamp=timestamp,
                waterlines=waterlines,
                undervalued_scan=undervalued_scan,
                overheat_signals=overheat_signals,
            )

        except Exception as e:
            logger.warning("orchestrator FAIL-OPEN: %s", e)
            return SectorValuationResult(
                timestamp=timestamp,
                waterlines=[],
                undervalued_scan=None,
                overheat_signals=[],
            )
