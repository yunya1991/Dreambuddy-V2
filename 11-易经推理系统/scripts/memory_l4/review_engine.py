"""复盘引擎模块 — 对错双向分析。

连接 L1 TradeCase 与 L4 Distill 的桥梁。
消费 TradeCase + Episode + A7/A8 报告，产出 ReviewRecord。

v0.2 新增模块 — Phase 2 (P1)
"""

import json
from datetime import datetime
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.memory_l4.paths import (
    memory_l4_cases_dir,
    memory_l4_reviews_dir,
    memory_l4_dir,
    workspace_root,
)
from scripts.memory_l4.tradingagents_reflector import (
    create_reflector,
    MultiDimensionalAnalyzer,
    L4MemoryLog,
)


# ── 64卦三分类（模块级常量，供仓位/卦象过滤统一使用） ─────────
# 保持与 _hexagram_expected_outcome 内部完全一致，单一事实源
BULLISH_HEXAGRAMS = frozenset([
    "乾", "需", "比", "小畜", "履", "泰", "同人", "大有",
    "谦", "豫", "随", "临", "复", "大畜", "颐",
    "咸", "恒", "大壮", "晋", "家人", "解", "益", "夬",
    "萃", "升", "鼎", "丰", "渐", "节", "中孚",
])

BEARISH_HEXAGRAMS = frozenset([
    "蒙", "讼", "师", "否", "观", "噬嗑", "剥", "无妄",
    "大过", "坎", "蛊", "遁", "明夷", "睽", "蹇", "损",
    "姤", "困", "井", "归妹", "旅", "涣", "小过",
])

NEUTRAL_HEXAGRAMS = frozenset([
    "坤", "屯", "贲", "离", "革", "震", "艮", "巽", "兑",
    "既济", "未济",
])


def now_iso_local() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _list_json(dir_path: Path) -> List[Path]:
    if not dir_path.exists():
        return []
    return sorted([p for p in dir_path.glob("*.json") if p.is_file()])


def _extract_pnl(episode: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    out = episode.get("outcome") or {}
    pnl_pct = out.get("realized_pnl_pct")
    if pnl_pct is None:
        pnl_pct = out.get("unrealized_pnl_pct")
    pnl_usdt = out.get("realized_pnl_usdt")
    if pnl_usdt is None:
        pnl_usdt = out.get("unrealized_pnl_usdt")

    if pnl_pct is None and "decision_outcome" in episode:
        do = episode.get("decision_outcome", {})
        pnl_pct = do.get("pnl_pct")
        if pnl_pct is None:
            pnl_pct = do.get("pnl")

    return (
        float(pnl_pct) if pnl_pct is not None else None,
        float(pnl_usdt) if pnl_usdt is not None else None,
    )


def _extract_episode_path(case: Dict[str, Any]) -> str:
    refs = ((case.get("execution") or {}).get("episode_refs") or [])
    if not refs:
        return ""
    return str((refs[0] or {}).get("path") or "")


def _read_episode(case: Dict[str, Any]) -> Dict[str, Any]:
    raw = _extract_episode_path(case)
    if not raw:
        return {}
    p = Path(raw)
    if not p.is_absolute():
        p = _ROOT / p
    if not p.exists():
        return {}
    try:
        return _load_json(p)
    except Exception:
        return {}


def _extract_theory_signals(case: Dict[str, Any]) -> Dict[str, List[str]]:
    """从 case 中提取理论信号（卦象、策略规则、系统来源）"""
    signals = {"hexagrams": [], "strategies": [], "rules": [], "regimes": []}

    ec = case.get("evidence_chain", {})
    for ref in ec.get("signal_refs", []):
        if isinstance(ref, dict):
            if ref.get("type") == "hexagram":
                signals["hexagrams"].append(ref.get("ref", ""))
            elif ref.get("type") == "strategy":
                signals["strategies"].append(ref.get("ref", ""))
        elif isinstance(ref, str):
            signals["strategies"].append(ref)

    dc = case.get("decision_context", {})
    if isinstance(dc, dict):
        if "hexagram" in dc:
            signals["hexagrams"].append(str(dc["hexagram"]))
        if "strategy" in dc:
            signals["strategies"].append(str(dc["strategy"]))
        if "signal" in dc:
            signals["rules"].append(str(dc["signal"]))

    es = case.get("environment_snapshot", {})
    if isinstance(es, dict) and "regime" in es:
        signals["regimes"].append(str(es["regime"]))

    return {k: list(set(v)) for k, v in signals.items() if v}


def _verify_theory_practice(case: Dict[str, Any], pnl_pct: float) -> Dict[str, Any]:
    """A8 理论实践验证：验证理论信号与实际结果的一致性

    根据证据链中的理论信号，分析其与实际盈亏结果是否一致。
    """
    signals = _extract_theory_signals(case)
    direction = case.get("direction", "long")
    outcome = "profit" if pnl_pct > 0 else "loss"

    confirmed = []
    contradicted = []
    gaps = []

    for hexagram in signals.get("hexagrams", []):
        expected_outcome = _hexagram_expected_outcome(hexagram, direction)
        if expected_outcome == outcome:
            confirmed.append({
                "type": "hexagram",
                "ref": hexagram,
                "expected": expected_outcome,
                "actual": outcome,
                "confidence": 0.7,
            })
        elif expected_outcome != "unknown":
            contradicted.append({
                "type": "hexagram",
                "ref": hexagram,
                "expected": expected_outcome,
                "actual": outcome,
                "confidence": 0.7,
            })

    for strategy in signals.get("strategies", []):
        expected_outcome = _strategy_expected_outcome(strategy, case)
        if expected_outcome == outcome:
            confirmed.append({
                "type": "strategy",
                "ref": strategy,
                "expected": expected_outcome,
                "actual": outcome,
                "confidence": 0.6,
            })
        elif expected_outcome != "unknown":
            contradicted.append({
                "type": "strategy",
                "ref": strategy,
                "expected": expected_outcome,
                "actual": outcome,
                "confidence": 0.6,
            })

    for regime in signals.get("regimes", []):
        expected_outcome = _regime_expected_outcome(regime, direction)
        if expected_outcome == outcome:
            confirmed.append({
                "type": "regime",
                "ref": regime,
                "expected": expected_outcome,
                "actual": outcome,
                "confidence": 0.5,
            })
        elif expected_outcome != "unknown":
            contradicted.append({
                "type": "regime",
                "ref": regime,
                "expected": expected_outcome,
                "actual": outcome,
                "confidence": 0.5,
            })

    if confirmed and not contradicted:
        consistency = "consistent"
        score = min(1.0, 0.5 + len(confirmed) * 0.15)
    elif contradicted and not confirmed:
        consistency = "contradicted"
        score = max(0.0, 0.5 - len(contradicted) * 0.2)
    else:
        consistency = "partially_consistent"
        score = 0.5

    if not signals:
        gaps.append("缺少理论信号，无法进行理论验证")
    if not confirmed and not contradicted:
        gaps.append("无法从当前信号推断预期结果")
    if len(contradicted) > 0:
        gaps.append(f"{len(contradicted)} 个理论信号与实际结果矛盾")

    return {
        "signals": signals,
        "confirmed_theories": confirmed,
        "contradicted_theories": contradicted,
        "consistency": consistency,
        "consistency_score": round(score, 2),
        "gap_analysis": gaps,
    }


def _hexagram_expected_outcome(hexagram: str, direction: str) -> str:
    """根据卦象推断预期结果

    基于卦义将64卦分为三类（原实现63/64卦全为positive，等价于无判别力）：
    - BULLISH（吉卦）：做多有利 → long=profit, short=loss
    - BEARISH（凶卦）：做空有利 → short=profit, long=loss
    - NEUTRAL（中性）：方向不明 → unknown

    分类集合引用模块级常量 BULLISH_HEXAGRAMS / BEARISH_HEXAGRAMS，保持单一事实源。
    """
    hexagram = hexagram.strip()

    if hexagram in BULLISH_HEXAGRAMS:
        return "profit" if direction == "long" else "loss"
    if hexagram in BEARISH_HEXAGRAMS:
        return "profit" if direction == "short" else "loss"
    return "unknown"


def _strategy_expected_outcome(strategy: str, case: Dict[str, Any]) -> str:
    """根据策略名称推断预期结果"""
    strategy = strategy.lower()
    if any(k in strategy for k in ["martin", "加仓", "金字塔"]):
        return "profit"
    if any(k in strategy for k in ["three_screen", "三屏", "共振"]):
        es = case.get("environment_snapshot", {})
        if isinstance(es, dict) and es.get("regime") == "trend_up":
            return "profit" if case.get("direction") == "long" else "loss"
        if isinstance(es, dict) and es.get("regime") == "trend_down":
            return "profit" if case.get("direction") == "short" else "loss"
    if any(k in strategy for k in ["yijing", "易经", "卦"]):
        dc = case.get("decision_context", {})
        if isinstance(dc, dict):
            confidence = dc.get("confidence", 0)
            if isinstance(confidence, (int, float)) and confidence > 0.7:
                return "profit"
    return "unknown"


def _regime_expected_outcome(regime: str, direction: str) -> str:
    """根据市场状态推断预期结果"""
    regime = regime.lower()
    if regime in ["trend_up"]:
        return "profit" if direction == "long" else "loss"
    if regime in ["trend_down"]:
        return "profit" if direction == "short" else "loss"
    if regime in ["ranging_up"]:
        return "profit" if direction == "long" else "unknown"
    if regime in ["ranging_down"]:
        return "profit" if direction == "short" else "unknown"
    return "unknown"


def analyze_success(
    case: Dict[str, Any],
    episode: Dict[str, Any],
) -> Dict[str, Any]:
    """成功案例分析 → 成功经验。

    Args:
        case: TradeCase 数据
        episode: Episode 数据

    Returns:
        成功分析结果（包含理论实践验证）
    """
    pnl_pct, pnl_usdt = _extract_pnl(episode)

    thinking_chain = case.get("thinking_chain") or []
    key_decisions = []
    for stage in thinking_chain:
        if stage.get("decision"):
            key_decisions.append({
                "stage": stage["stage"],
                "decision": stage["decision"],
                "rationale": stage.get("rationale"),
            })

    regime = (case.get("environment_snapshot") or {}).get("regime", "unknown")

    theory_verification = _verify_theory_practice(case, pnl_pct or 0)

    return {
        "case_id": case["case_id"],
        "direction": "success",
        "pnl_pct": pnl_pct,
        "pnl_usdt": pnl_usdt,
        "regime": regime,
        "key_decisions": key_decisions,
        "thinking_chain_length": len(thinking_chain),
        "theory_verification": theory_verification,
    }


def analyze_failure(
    case: Dict[str, Any],
    episode: Dict[str, Any],
) -> Dict[str, Any]:
    """失败案例分析 → 风险信号。

    复用 failure_analyzer 的分组逻辑但输出到统一分析格式。

    Args:
        case: TradeCase 数据
        episode: Episode 数据

    Returns:
        失败分析结果（包含理论实践验证）
    """
    pnl_pct, pnl_usdt = _extract_pnl(episode)

    out = episode.get("outcome") or {}
    exit_reason = str(out.get("exit_reason") or out.get("stop_reason") or "unknown")

    regime = (case.get("environment_snapshot") or {}).get("regime", "unknown")

    thinking_chain = case.get("thinking_chain") or []
    stages_covered = [s.get("stage") for s in thinking_chain if s.get("stage")]

    theory_verification = _verify_theory_practice(case, pnl_pct or 0)

    failure_patterns = _detect_failure_patterns(case, episode, exit_reason)

    return {
        "case_id": case["case_id"],
        "direction": "failure",
        "pnl_pct": pnl_pct,
        "pnl_usdt": pnl_usdt,
        "regime": regime,
        "exit_reason": exit_reason,
        "stages_covered": stages_covered,
        "theory_verification": theory_verification,
        "failure_patterns": failure_patterns,
    }


def _detect_failure_patterns(case: Dict[str, Any], episode: Dict[str, Any], exit_reason: str) -> List[Dict[str, Any]]:
    """检测失败模式"""
    patterns = []

    if exit_reason in ["stop_loss", "止损"]:
        patterns.append({
            "type": "stop_loss_hit",
            "description": "触发止损",
            "severity": "high",
        })

    if exit_reason in ["liquidation", "强制平仓"]:
        patterns.append({
            "type": "liquidation",
            "description": "强制平仓",
            "severity": "critical",
        })

    es = case.get("environment_snapshot", {})
    if isinstance(es, dict):
        if es.get("regime") == "sideways" and case.get("direction") in ["long", "short"]:
            patterns.append({
                "type": "wrong_regime",
                "description": "在震荡市中开趋势单",
                "severity": "medium",
            })

    ec = case.get("evidence_chain", {})
    if not ec or not ec.get("signal_refs"):
        patterns.append({
            "type": "insufficient_evidence",
            "description": "缺少交易信号证据",
            "severity": "medium",
        })

    tc = case.get("thinking_chain") or []
    if len(tc) < 2:
        patterns.append({
            "type": "incomplete_thinking",
            "description": "思考链不完整",
            "severity": "low",
        })

    return patterns


def _generate_distill_proposals(case: Dict[str, Any], analysis: Dict[str, Any], theory_verification: Dict[str, Any]) -> List[Dict[str, Any]]:
    """生成蒸馏建议（A7 实践理论报告雏形）

    根据理论验证结果，生成可用于蒸馏的命题建议。
    """
    proposals = []

    confirmed = theory_verification.get("confirmed_theories", [])
    contradicted = theory_verification.get("contradicted_theories", [])
    consistency = theory_verification.get("consistency", "partially_consistent")

    system_source = case.get("system_source", "unknown")
    direction = case.get("direction", "long")
    regime = (case.get("environment_snapshot") or {}).get("regime", "unknown")
    pnl_pct = analysis.get("pnl_pct") or 0

    if confirmed:
        for ct in confirmed:
            if ct.get("type") == "strategy":
                proposals.append({
                    "type": "strategy_rule",
                    "statement": f"{system_source} 在 {regime} 市场下的 {ct['ref']} 策略有效",
                    "evidence_count": 1,
                    "confidence": ct.get("confidence", 0.6),
                    "direction": direction,
                    "regime": regime,
                })
            elif ct.get("type") == "hexagram":
                proposals.append({
                    "type": "signal_rule",
                    "statement": f"卦象 {ct['ref']} 在 {direction} 方向下预测准确",
                    "evidence_count": 1,
                    "confidence": ct.get("confidence", 0.7),
                    "direction": direction,
                })

    if contradicted:
        for ct in contradicted:
            proposals.append({
                "type": "refutation",
                "statement": f"{ct['type']} {ct['ref']} 在 {regime} 市场下预测失败",
                "evidence_count": 1,
                "confidence": ct.get("confidence", 0.5),
                "direction": direction,
                "regime": regime,
                "actual_outcome": ct.get("actual"),
            })

    if consistency == "consistent" and abs(pnl_pct) > 2:
        proposals.append({
            "type": "success_pattern",
            "statement": f"{system_source} 在 {regime} 市场下 {direction} 方向交易成功率高",
            "evidence_count": 1,
            "confidence": min(0.9, 0.5 + abs(pnl_pct) / 20),
            "direction": direction,
            "regime": regime,
            "pnl_pct": pnl_pct,
        })

    if consistency == "contradicted" and abs(pnl_pct) > 2:
        proposals.append({
            "type": "failure_pattern",
            "statement": f"{system_source} 在 {regime} 市场下 {direction} 方向交易需要调整",
            "evidence_count": 1,
            "confidence": min(0.9, 0.5 + abs(pnl_pct) / 20),
            "direction": direction,
            "regime": regime,
            "pnl_pct": pnl_pct,
            "gap_analysis": theory_verification.get("gap_analysis", []),
        })

    return proposals


def build_review_record(
    case: Dict[str, Any],
    analysis: Dict[str, Any],
    a7_report: Optional[Dict[str, Any]] = None,
    a8_report: Optional[Dict[str, Any]] = None,
    snapshot_ts: Optional[str] = None,
    reflector=None,
    episode: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构建 ReviewRecord（包含 A7/A8 理论实践验证 + TradingAgents Reflector）。

    Args:
        case: TradeCase 数据
        analysis: analyze_success/analyze_failure 的返回值
        a7_report: A7 实践理论报告 (可选)
        a8_report: A8 理论验证报告 (可选)
        snapshot_ts: 复盘时间戳
        reflector: TradingAgents Reflector 实例 (可选)
        episode: Episode 数据 (用于 Reflector)

    Returns:
        ReviewRecord 字典
    """
    ts = snapshot_ts or now_iso_local()
    case_id = case.get("case_id", "unknown")
    review_id = f"REV_{ts.replace(':', '').replace('-', '').replace('+', '')[:15]}_{case_id}"

    pnl_pct = analysis.get("pnl_pct")
    direction = analysis.get("direction", "mixed")

    theory_verification = analysis.get("theory_verification", {})
    consistency_score = theory_verification.get("consistency_score", 0.5)
    confirmed_theories = theory_verification.get("confirmed_theories", [])
    contradicted_theories = theory_verification.get("contradicted_theories", [])
    gap_analysis = theory_verification.get("gap_analysis", [])
    failure_patterns = analysis.get("failure_patterns", [])

    # ── TradingAgents Reflector 深度反思 ──
    ta_reflection = {}
    multi_dim_analysis = {}
    if reflector and episode is not None:
        try:
            ta_reflection = reflector.reflect(case, episode, analysis)
            multi_dim_analysis = ta_reflection.get("multi_dimensional_analysis", {})
        except Exception as e:
            ta_reflection = {"error": str(e)}

    # ── 多维度分析师视角 ──
    if not multi_dim_analysis and episode is not None:
        analyzer = MultiDimensionalAnalyzer()
        multi_dim_analysis = analyzer.analyze(case, episode)

    mistakes: List[Dict[str, Any]] = []
    successes: List[Dict[str, Any]] = []

    if direction == "failure":
        exit_reason = analysis.get("exit_reason", "待分析")
        theory_gap = "待理论与实践验证"
        if contradicted_theories:
            theory_gap = f"{len(contradicted_theories)} 个理论信号与实际结果矛盾"
        elif gap_analysis:
            theory_gap = "; ".join(gap_analysis)

        mistakes.append({
            "what": f"交易亏损 {pnl_pct}%",
            "why": exit_reason,
            "severity": min(1.0, abs(pnl_pct or 0) / 5.0) if pnl_pct is not None else None,
            "stage_ref": None,
            "theory_gap": theory_gap,
            "patterns": failure_patterns,
        })

        for ct in contradicted_theories:
            mistakes.append({
                "what": f"{ct['type']} {ct['ref']} 预测错误",
                "why": f"预期 {ct['expected']}，实际 {ct['actual']}",
                "severity": ct.get("confidence", 0.5),
                "stage_ref": ct["type"],
                "theory_gap": "理论与实践不一致",
            })

    elif direction == "success":
        why = "待理论与实践验证"
        if confirmed_theories:
            why = f"{len(confirmed_theories)} 个理论信号验证成功"

        successes.append({
            "what": f"交易盈利 {pnl_pct}%",
            "why": why,
            "severity": None,
            "stage_ref": None,
            "theory_gap": None,
            "reproducible": consistency_score > 0.7,
            "confirmed_theories": confirmed_theories,
        })

    record: Dict[str, Any] = {
        "review_id": review_id,
        "version": "v0.3",
        "snapshot_ts": ts,
        "case_id": case_id,
        "direction": direction,
        "mistakes": mistakes,
        "successes": successes,
        "theory_practice_analysis": {
            "consistency_score": consistency_score,
            "consistency": theory_verification.get("consistency", "partially_consistent"),
            "confirmed_theories": confirmed_theories,
            "contradicted_theories": contradicted_theories,
            "gap_analysis": gap_analysis,
            "signals": theory_verification.get("signals", {}),
        },
        "distill_proposals": _generate_distill_proposals(case, analysis, theory_verification),
        "quadrant": case.get("quadrant", {"x": 0.0, "y": 0.0, "evidence": {}}),
        "a7_report_ref": None,
        "a8_report_ref": None,
        # ── TradingAgents 增强字段 ──
        "tradingagents_reflection": ta_reflection,
        "multi_dimensional_analysis": multi_dim_analysis,
    }

    if a7_report:
        record["a7_report_ref"] = "a7_report_pending"
    if a8_report:
        record["a8_report_ref"] = "a8_report_pending"

    return record


def run_review(
    snapshot_ts: Optional[str] = None,
    cases: Optional[List[Dict[str, Any]]] = None,
    episodes_by_case_id: Optional[Dict[str, Dict[str, Any]]] = None,
    output_dir: Optional[Path] = None,
    enable_tradingagents: bool = True,
) -> Dict[str, Any]:
    """批量复盘（集成 TradingAgents Reflector）。

    Args:
        snapshot_ts: 复盘时间戳
        cases: TradeCase 列表，默认加载全部
        episodes_by_case_id: {case_id: episode} 字典，默认自动加载
        output_dir: 输出目录
        enable_tradingagents: 是否启用 TradingAgents Reflector

    Returns:
        复盘结果摘要
    """
    ts = snapshot_ts or now_iso_local()

    if cases is None:
        cases = [_load_json(p) for p in _list_json(memory_l4_cases_dir())]

    if episodes_by_case_id is None:
        episodes_by_case_id = {}
        for c in cases:
            cid = c.get("case_id", "")
            if cid:
                episodes_by_case_id[cid] = _read_episode(c)

    # ── TradingAgents Reflector 初始化 ──
    reflector = None
    memory_log = None
    if enable_tradingagents:
        try:
            reflector = create_reflector()
            memory_log = reflector.memory_log
        except Exception:
            pass

    reviews: List[Dict[str, Any]] = []
    success_count = 0
    failure_count = 0
    mixed_count = 0

    for case in cases:
        cid = case.get("case_id", "")
        episode = episodes_by_case_id.get(cid, {})
        pnl_pct, _ = _extract_pnl(episode)

        if pnl_pct is None:
            do = case.get("decision_outcome", {})
            pnl_pct = do.get("pnl_pct")

        if pnl_pct is None:
            continue

        if pnl_pct > 0:
            analysis = analyze_success(case, episode)
            success_count += 1
        else:
            analysis = analyze_failure(case, episode)
            failure_count += 1

        record = build_review_record(
            case, analysis, snapshot_ts=ts,
            reflector=reflector, episode=episode,
        )
        reviews.append(record)

        # ── Memory Log: Phase A (记录决策) + Phase B (更新结果) ──
        if memory_log:
            try:
                trade_date = case.get("ts", ts)[:10]
                symbol = case.get("symbol", "Unknown")
                direction = case.get("direction", "unknown")
                decision_summary = record.get("multi_dimensional_analysis", {}).get("summary", "")

                memory_log.store_decision(
                    case_id=cid,
                    symbol=symbol,
                    trade_date=trade_date,
                    direction=direction,
                    decision_summary=decision_summary,
                    evidence_chain=case.get("evidence_chain"),
                )

                reflection = record.get("tradingagents_reflection", {}).get("reflection_text", "")
                if reflection:
                    memory_log.update_with_outcome(
                        case_id=cid,
                        symbol=symbol,
                        trade_date=trade_date,
                        pnl_pct=pnl_pct or 0,
                        pnl_usdt=case.get("decision_outcome", {}).get("pnl", 0) or 0,
                        holding_days=1,
                        reflection=reflection,
                    )
            except Exception:
                pass

    # 保存
    out_dir = output_dir or memory_l4_reviews_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    for record in reviews:
        path = out_dir / f"{record['review_id']}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "snapshot_ts": ts,
        "total_reviews": len(reviews),
        "success_count": success_count,
        "failure_count": failure_count,
        "mixed_count": mixed_count,
        "output_dir": str(out_dir),
    }
