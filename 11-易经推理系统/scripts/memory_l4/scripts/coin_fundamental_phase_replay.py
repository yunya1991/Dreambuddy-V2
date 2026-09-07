"""阶段闭环回放脚本 — PhaseReplay。

回放三案例完整阶段流转，验证系统在每个切换点是否及时识别：
  - CRCL：P1（主网预期）→ P2（落地后盈收跟踪）
  - UNI：P2（Robinhood 接入盈收扩张）→ P3（估值到高位）
  - HYPE：P3（大跌后修复力）

合成数据策略（spec E5）：
  E5 回放先用合成快照序列（事件时间线 + E5/E6 序列 + 估值分位序列），
  真实历史数据接入留待 Phase F 数据源扩展。

输出：回放报告，含每个切换点的 from/to/triggers/confidence/strategy_hint_delta。

FAIL-OPEN：空时间线或异常 → 返回空结果，不抛异常。
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# 将 force_vector 加入 sys.path
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_L4_DIR = os.path.dirname(_THIS_DIR)
if _L4_DIR not in sys.path:
    sys.path.insert(0, _L4_DIR)

from force_vector.coin_fundamental_phase_classifier import (
    P1_EXPECTATION,
    P2_REVENUE_EXPANSION,
    P3_VALUATION_RECOVERY,
    classify_phase,
)
from force_vector.coin_fundamental_phase_strategy_map import get_strategy_hint


# ===========================================================================
# 数据结构
# ===========================================================================

@dataclass
class PhaseSnapshot:
    """合成快照输入。

    ts: 时间戳（ISO8601 或简单日期）
    e5: supply_shrinkage_intensity
    e6: value_capture_delta
    valuation_percentile: [0, 100]
    events: 事件时间线（type/status 字典列表）
    """
    ts: str
    e5: float
    e6: float
    valuation_percentile: float
    events: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class PhaseReplayStep:
    """回放单步输出：快照 + 识别结果。"""
    ts: str
    e5: float
    e6: float
    valuation_percentile: float
    phase: str
    confidence: float
    triggers: List[str] = field(default_factory=list)
    strategy_hint: Dict[str, Any] = field(default_factory=dict)
    evidence: Dict[str, float] = field(default_factory=dict)


@dataclass
class SwitchRecord:
    """阶段切换记录。"""
    ts: str
    from_phase: str
    to_phase: str
    triggers: List[str] = field(default_factory=list)
    confidence: float = 0.0
    strategy_hint_delta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReplayResult:
    """单个案例回放结果。"""
    case_name: str
    snapshots: List[PhaseReplayStep] = field(default_factory=list)
    switches: List[SwitchRecord] = field(default_factory=list)
    total_snapshots: int = 0
    total_switches: int = 0
    final_phase: Optional[str] = None


# ===========================================================================
# 三案例合成时间线
# ===========================================================================

# CRCL 案例：P1（主网预期）→ P2（落地后盈收跟踪）
# 用户原话："CRCL 代表预期利好，迎来的强势，以及潜在投资机会；
#           一旦预期落地，短期风险较高，则会进入到类似 UNI 的增长模式"
# T2 设计：保持 e6 高/val 低（规则匹配仍 P1），由事件 landed 触发 P1→P2 切换
CRCL_REPLAY_TIMELINE: List[PhaseSnapshot] = [
    PhaseSnapshot(ts="2026-06-01", e5=0.20, e6=0.80, valuation_percentile=20.0,
                  events=[{"type": "mainnet_launch", "status": "pending"}]),
    PhaseSnapshot(ts="2026-07-01", e5=0.25, e6=0.75, valuation_percentile=25.0,
                  events=[{"type": "mainnet_launch", "status": "pending"}]),
    PhaseSnapshot(ts="2026-08-01", e5=0.30, e6=0.70, valuation_percentile=25.0,
                  events=[{"type": "mainnet_launch", "status": "landed"}]),
    PhaseSnapshot(ts="2026-09-01", e5=0.50, e6=0.50, valuation_percentile=45.0,
                  events=[]),
]

# UNI 案例：P2（Robinhood 接入盈收扩张）→ P3（估值到高位）
# 用户原话："UNI 代表当下盈收增强带来的，价格大幅增长；
#           等估值到达一定阶段，就会出现类似 HYPE 这类"
UNI_REPLAY_TIMELINE: List[PhaseSnapshot] = [
    PhaseSnapshot(ts="2026-05-01", e5=0.70, e6=0.50, valuation_percentile=50.0,
                  events=[]),
    PhaseSnapshot(ts="2026-06-01", e5=0.60, e6=0.40, valuation_percentile=70.0,
                  events=[]),
    PhaseSnapshot(ts="2026-07-01", e5=0.50, e6=0.40, valuation_percentile=85.0,
                  events=[]),
    PhaseSnapshot(ts="2026-08-01", e5=0.50, e6=0.30, valuation_percentile=88.0,
                  events=[]),
]

# HYPE 案例：P3（盈收强+估值稳，大跌后强势修复）
# 用户原话："HYPE 这类，盈收基本面强，估值稳定，大跌以后能强势修复"
HYPE_REPLAY_TIMELINE: List[PhaseSnapshot] = [
    PhaseSnapshot(ts="2026-06-01", e5=0.60, e6=0.40, valuation_percentile=85.0,
                  events=[]),
    PhaseSnapshot(ts="2026-07-01", e5=0.50, e6=0.30, valuation_percentile=82.0,
                  events=[]),
    PhaseSnapshot(ts="2026-08-01", e5=0.50, e6=0.30, valuation_percentile=81.0,
                  events=[]),
    PhaseSnapshot(ts="2026-09-01", e5=0.40, e6=0.20, valuation_percentile=83.0,
                  events=[]),
]


# ===========================================================================
# 回放函数
# ===========================================================================

def _snapshot_to_step(coin: str, snap: PhaseSnapshot, rank: str = "S") -> PhaseReplayStep:
    """单快照识别 → 回放步。

    rank 默认 "S"（用于查询策略映射表）。
    """
    sub_signals = {
        "supply_shrinkage_intensity": snap.e5,
        "value_capture_delta": snap.e6,
    }
    classification = classify_phase(
        coin=coin,
        sub_signals=sub_signals,
        valuation_percentile=snap.valuation_percentile,
        event_timeline=snap.events if snap.events else None,
    )
    strategy_hint = get_strategy_hint(classification.current_phase, rank)
    return PhaseReplayStep(
        ts=snap.ts,
        e5=snap.e5,
        e6=snap.e6,
        valuation_percentile=snap.valuation_percentile,
        phase=classification.current_phase,
        confidence=round(classification.phase_confidence, 4),
        triggers=list(classification.switch_triggers),
        strategy_hint=strategy_hint,
        evidence=dict(classification.evidence),
    )


def replay_case(case_name: str, timeline: Optional[List[PhaseSnapshot]]) -> ReplayResult:
    """回放单个案例，识别阶段切换点。

    FAIL-OPEN：空时间线或 None → 返回空 ReplayResult（不抛异常）。
    """
    result = ReplayResult(case_name=case_name)

    if not timeline:
        return result

    prev_step: Optional[PhaseReplayStep] = None
    for snap in timeline:
        try:
            step = _snapshot_to_step(case_name, snap)
        except Exception:
            # FAIL-OPEN：单快照识别异常跳过，不影响后续
            continue

        result.snapshots.append(step)

        # 切换检测
        if prev_step is not None and step.phase != prev_step.phase:
            prev_hint = prev_step.strategy_hint
            curr_hint = step.strategy_hint
            switch = SwitchRecord(
                ts=step.ts,
                from_phase=prev_step.phase,
                to_phase=step.phase,
                triggers=list(step.triggers),
                confidence=step.confidence,
                strategy_hint_delta={
                    "from_case_anchor": prev_hint.get("case_anchor", ""),
                    "to_case_anchor": curr_hint.get("case_anchor", ""),
                    "from_priority_weight": prev_hint.get("priority_weight", 0),
                    "to_priority_weight": curr_hint.get("priority_weight", 0),
                    "from_holding_period": prev_hint.get("holding_period_hint", ""),
                    "to_holding_period": curr_hint.get("holding_period_hint", ""),
                },
            )
            result.switches.append(switch)

        prev_step = step

    result.total_snapshots = len(result.snapshots)
    result.total_switches = len(result.switches)
    if result.snapshots:
        result.final_phase = result.snapshots[-1].phase
    return result


def replay_all_cases(db_path: Optional[str] = None) -> List[ReplayResult]:
    """批量回放 CRCL / UNI / HYPE 三个案例。

    F3 集成：优先使用真实历史数据（DeFiLlama fees + CoinGecko MCAP），
    数据不足时回退合成时间线（FAIL-OPEN）。

    db_path: data_center.db 路径，None 则使用默认路径。
    """
    # 延迟导入避免循环依赖
    try:
        _L4_DIR = os.path.dirname(_THIS_DIR)
        _FV_DIR = os.path.join(_L4_DIR, "force_vector")
        if _FV_DIR not in sys.path:
            sys.path.insert(0, _FV_DIR)
        from force_vector.coin_fundamental_historical_data_loader import build_real_snapshots
    except Exception:
        build_real_snapshots = None  # type: ignore

    # 案例名 → 合成时间线（回退用）
    _SYNTHETIC_MAP = {
        "CRCL": CRCL_REPLAY_TIMELINE,
        "UNI": UNI_REPLAY_TIMELINE,
        "HYPE": HYPE_REPLAY_TIMELINE,
    }

    results: List[ReplayResult] = []
    for case_name, synthetic_timeline in _SYNTHETIC_MAP.items():
        # F3: 优先尝试真实历史数据
        real_timeline: Optional[List[PhaseSnapshot]] = None
        if build_real_snapshots is not None:
            try:
                real_timeline = build_real_snapshots(case_name, db_path)
            except Exception:
                real_timeline = None

        # 真实数据不足 → 回退合成数据（FAIL-OPEN）
        timeline = real_timeline if real_timeline else synthetic_timeline
        results.append(replay_case(case_name, timeline))
    return results


# ===========================================================================
# 报告生成（可选：输出 JSON 文件）
# ===========================================================================

def _result_to_dict(result: ReplayResult) -> Dict[str, Any]:
    """将 ReplayResult 转为可 JSON 序列化的 dict。"""
    return {
        "case_name": result.case_name,
        "total_snapshots": result.total_snapshots,
        "total_switches": result.total_switches,
        "final_phase": result.final_phase,
        "snapshots": [
            {
                "ts": s.ts, "phase": s.phase, "confidence": s.confidence,
                "e5": s.e5, "e6": s.e6, "valuation_percentile": s.valuation_percentile,
                "triggers": s.triggers, "strategy_hint": s.strategy_hint,
            }
            for s in result.snapshots
        ],
        "switches": [
            {
                "ts": sw.ts, "from": sw.from_phase, "to": sw.to_phase,
                "triggers": sw.triggers, "confidence": sw.confidence,
                "strategy_hint_delta": sw.strategy_hint_delta,
            }
            for sw in result.switches
        ],
    }


def write_replay_report(results: List[ReplayResult], json_path: str) -> None:
    """将回放报告写入 JSON 文件。"""
    import json
    dir_path = os.path.dirname(json_path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    report = {
        "version": "1.0",
        "cases": [_result_to_dict(r) for r in results],
    }
    tmp_path = json_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, json_path)


# ===========================================================================
# CLI 入口（可选）
# ===========================================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="阶段闭环回放脚本")
    parser.add_argument(
        "--output", "-o",
        default=os.path.join(_L4_DIR, "runtime", "coin_fundamental_phase_replay.json"),
        help="输出 JSON 报告路径",
    )
    args = parser.parse_args()

    results = replay_all_cases()
    for r in results:
        print(f"\n=== {r.case_name} ===")
        print(f"  快照数: {r.total_snapshots}, 切换数: {r.total_switches}, "
              f"最终阶段: {r.final_phase}")
        for sw in r.switches:
            print(f"  切换 @ {sw.ts}: {sw.from_phase} → {sw.to_phase} "
                  f"(triggers={sw.triggers}, conf={sw.confidence})")

    write_replay_report(results, args.output)
    print(f"\n报告已写入: {args.output}")
