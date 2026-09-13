"""入场侧 BCRM2.0 反向信号分层治理

对称于离场侧 exit_engine._check_bcrm_reverse_signal（规则 2b），
形成开仓-离场学习闭环。

分层策略（设计文档 entry_bcrm_soft_weight_design.md §2）：
  | BCRM2.0 反向 conf | 处理       | 仓位系数 | outcome 标签     |
  |------------------|-----------|---------|-----------------|
  | ≥0.95 + BDSM 一致 | 硬否决     | 0       | 不学习           |
  | ≥0.95（无 BDSM）  | 软权重     | ×0.3    | REDUCE_WEIGHT   |
  | 0.85-0.95         | 软权重     | ×0.5    | REDUCE_WEIGHT   |
  | 0.80-0.85         | 软权重     | ×0.7    | REDUCE_WEIGHT   |
  | <0.80             | 不干预     | ×1.0    | 正常 outcome    |

FAIL-OPEN: 缓存缺失/过期/异常 → weight_factor=1.0, veto=False
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# BCRM2.0 反向信号新鲜度阈值（秒），与离场侧 BCRM_REVERSE_STALE_SEC 对齐
_BCRM_REVERSE_STALE_SEC = 1800  # 30 分钟


@dataclass
class EntryWeightDecision:
    """入场侧权重因子决策结果

    Attributes:
        weight_factor: 仓位乘数（0.0=不开仓, 0.3/0.5/0.7=软权重, 1.0=正常）
        veto: 硬否决标志（True=不开仓，灾难性保护，不进入学习闭环）
        bcrm_reverse_conf: 开仓时 BCRM 反向置信度（写入 TradeRecord 供平仓学习用）
    """
    weight_factor: float = 1.0
    veto: bool = False
    bcrm_reverse_conf: float = 0.0


def compute_bcrm_entry_weight_factor(
    bcrm_dir: str,
    bcrm_conf: float,
    bcrm_ts: float,
    evo_dir: str,
    bdsm_constraint: str = "",
    now: float | None = None,
    pattern_factor: float | None = None,
) -> EntryWeightDecision:
    """计算入场侧 BCRM2.0 反向信号的分层仓位权重因子

    Args:
        bcrm_dir: BCRM2.0 预测方向（"UP" / "DOWN" / "" = 缓存缺失）
        bcrm_conf: BCRM2.0 置信度
        bcrm_ts: BCRM2.0 推理时间戳
        evo_dir: evolution 开仓方向（"LONG" / "SHORT"）
        bdsm_constraint: BDSM 方向约束（"LONG_ONLY" / "SHORT_ONLY" / ""）
        now: 当前时间戳（测试注入），默认 time.time()
        pattern_factor: Phase 4.1 PatternDetector 形态因子（负值=看跌，
            正值=看涨, 0.0/None=无形态信号）。头肩顶看跌+evo_dir=LONG 时额外降权。

    Returns:
        EntryWeightDecision: weight_factor / veto / bcrm_reverse_conf

    FAIL-OPEN: 缓存缺失(bcrm_dir="")、过期(>30min)、异常 → weight_factor=1.0
    """
    try:
        _now = now if now is not None else time.time()

        bcrm_dir = str(bcrm_dir or "").upper()
        evo_dir = str(evo_dir or "").upper()
        bdsm_constraint = str(bdsm_constraint or "").upper()
        bcrm_conf = float(bcrm_conf or 0.0)
        bcrm_ts = float(bcrm_ts or 0.0)

        # Phase 4.1: pattern_factor 降权系数（头肩顶看跌+evo_dir=LONG 时生效）
        _pf = 0.0
        try:
            if pattern_factor is not None:
                _pf = float(pattern_factor)
        except (TypeError, ValueError):
            _pf = 0.0

        def _apply_pf(d: EntryWeightDecision) -> EntryWeightDecision:
            """对非 veto 决策应用 pattern_factor 降权。"""
            if _pf < 0 and evo_dir == "LONG" and not d.veto:
                _penalty = abs(_pf) * 0.3
                d.weight_factor = max(0.3, d.weight_factor * (1.0 - _penalty))
            return d

        # ── FAIL-OPEN: 缓存缺失 → 放行
        if not bcrm_dir:
            return _apply_pf(EntryWeightDecision(weight_factor=1.0, veto=False, bcrm_reverse_conf=0.0))

        # ── FAIL-OPEN: 信号过期 → 放行
        if (_now - bcrm_ts) >= _BCRM_REVERSE_STALE_SEC:
            return _apply_pf(EntryWeightDecision(weight_factor=1.0, veto=False, bcrm_reverse_conf=0.0))

        # ── 方向冲突检测
        is_conflict = (
            (bcrm_dir == "UP" and evo_dir == "SHORT")
            or (bcrm_dir == "DOWN" and evo_dir == "LONG")
        )
        if not is_conflict:
            # 同向 → 不干预
            return _apply_pf(EntryWeightDecision(weight_factor=1.0, veto=False, bcrm_reverse_conf=0.0))

        # ── 分层治理（反向冲突时）
        # BDSM 方向一致判断：
        #   BCRM DOWN + BDSM SHORT_ONLY → 一致（都看空）
        #   BCRM UP + BDSM LONG_ONLY → 一致（都看多）
        bdsm_consistent = (
            (bcrm_dir == "DOWN" and "SHORT" in bdsm_constraint)
            or (bcrm_dir == "UP" and "LONG" in bdsm_constraint)
        )

        # ── ≥0.95 + BDSM 一致 → 硬否决
        if bcrm_conf >= 0.95 and bdsm_consistent:
            logger.warning(
                "[EntryGovernor] BCRM reverse conf=%.2f + BDSM consistent → hard veto",
                bcrm_conf,
            )
            return EntryWeightDecision(
                weight_factor=0.0, veto=True, bcrm_reverse_conf=0.0,
            )

        # ── ≥0.95（无 BDSM 一致）→ ×0.3
        if bcrm_conf >= 0.95:
            return _apply_pf(EntryWeightDecision(
                weight_factor=0.3, veto=False, bcrm_reverse_conf=bcrm_conf,
            ))

        # ── 0.85-0.95 → ×0.5
        if bcrm_conf >= 0.85:
            return _apply_pf(EntryWeightDecision(
                weight_factor=0.5, veto=False, bcrm_reverse_conf=bcrm_conf,
            ))

        # ── 0.80-0.85 → ×0.7
        if bcrm_conf >= 0.80:
            return _apply_pf(EntryWeightDecision(
                weight_factor=0.7, veto=False, bcrm_reverse_conf=bcrm_conf,
            ))

        # ── <0.80 → 不干预
        return _apply_pf(EntryWeightDecision(
            weight_factor=1.0, veto=False, bcrm_reverse_conf=0.0,
        ))

    except Exception as e:
        logger.warning("[FO] compute_bcrm_entry_weight_factor crash: %s", e)
        return EntryWeightDecision(weight_factor=1.0, veto=False, bcrm_reverse_conf=0.0)


# ============================================================================
# 超时换仓信号扫描（全池多空相对强弱）
# ============================================================================

# 超时换仓信号阈值
_ROTATION_CONF_DELTA = 0.15   # 信号需比当前持仓 confidence 高 0.15
_ROTATION_CONF_FLOOR = 0.65   # 绝对门槛：信号 confidence ≥ 0.65 才考虑

# BCRM 方向 → evolution 方向映射
_BCRM_DIR_MAP = {"UP": "long", "DOWN": "short"}


def find_strongest_rotation_signal(
    evo_signals: dict,
    bcrm_signals: dict,
    exclude_coin: str,
    cur_confidence: float,
    cur_direction: str,
) -> dict | None:
    """扫描全池（evolution + BCRM2.0）所有币种、所有方向的最强换仓信号

    背景：超时评估原本只看同方向更强信号（多头只看更强多头），
    改为全池多空相对强弱——市场空头格局明显时，应平浮盈多头换空。

    Args:
        evo_signals: evolution 信号池 {coin: {top_path_confidence, top_path_direction}}
        bcrm_signals: BCRM2.0 信号池 {coin: {direction, confidence}}
        exclude_coin: 当前持仓币种（排除自身）
        cur_confidence: 当前持仓的 confidence
        cur_direction: 当前持仓方向（"long" / "short"）

    Returns:
        最强信号 dict {coin, direction, confidence, source, is_opposite} 或 None
        条件：confidence > cur_confidence + 0.15 且 confidence >= 0.65

    FAIL-OPEN: 任何异常 → 返回 None（不触发换仓，维持原持仓）
    """
    try:
        exclude = str(exclude_coin or "").upper()
        cur_dir = str(cur_direction or "").lower()
        cur_conf = float(cur_confidence or 0.0)
        threshold = max(cur_conf + _ROTATION_CONF_DELTA, _ROTATION_CONF_FLOOR)

        strongest: dict | None = None

        def _consider(coin: str, direction: str, confidence: float, source: str):
            nonlocal strongest
            if not direction or direction not in ("long", "short"):
                return
            if confidence < threshold:
                return
            if strongest is None or confidence > strongest["confidence"]:
                strongest = {
                    "coin": coin,
                    "direction": direction,
                    "confidence": confidence,
                    "source": source,
                    "is_opposite": direction != cur_dir,
                }

        # 扫描 evolution 信号池
        for coin, kd in (evo_signals or {}).items():
            if str(coin or "").upper() == exclude:
                continue
            if not isinstance(kd, dict):
                continue
            _consider(
                coin=str(coin),
                direction=str(kd.get("top_path_direction", "") or "").lower(),
                confidence=float(kd.get("top_path_confidence", 0.0) or 0.0),
                source="evolution",
            )

        # 扫描 BCRM2.0 信号池
        for coin, info in (bcrm_signals or {}).items():
            if str(coin or "").upper() == exclude:
                continue
            if not isinstance(info, dict):
                continue
            bcrm_dir = str(info.get("direction", "") or "").upper()
            evo_dir = _BCRM_DIR_MAP.get(bcrm_dir, "")
            _consider(
                coin=str(coin),
                direction=evo_dir,
                confidence=float(info.get("confidence", 0.0) or 0.0),
                source="bcrm",
            )

        return strongest

    except Exception as e:
        logger.warning("[FO] find_strongest_rotation_signal crash: %s", e)
        return None
