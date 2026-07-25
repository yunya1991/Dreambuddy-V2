"""
AB Trading Bridge — 打通 AB 交易系统与易经推理大模型。

P0: A/B 决策写入 shared_memory_bus
P1: A/B 历史案例接入两仪引擎对比学习
P2: BCRM 对 A/B 历史时点做模拟推理
P3: 元学习路由表，动态选择最优决策源

数据流:
  AB Trading (WorkBuddy) ──→ shared_memory_bus ──→ BCRM 易经大模型
                                                    ↓
                                              liangyi_engine.learn_from_cases()
                                                    ↓
                                              对比学习 & 元路由
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.memory_l4.shared_memory_bus import (
    publish_shared_memory_event,
    read_shared_memory_events,
    _default_bus_path,
)
from scripts.memory_l4.paths import artifacts_memory_l4_dir


# ============================================================
# 配置
# ============================================================

# AB 交易系统日志目录（可被环境变量覆盖）
AB_LOG_DIR = Path(os.environ.get(
    "AB_LOG_DIR",
    "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/logs",
))

# 状态文件：记录已发布的日志，避免重复
_STATE_FILE = artifacts_memory_l4_dir() / "shared_bus" / "ab_bridge_state.json"

# ACL 配置：允许 agent_a / agent_b 发布，允许 bcrm_engine 读取
ACL_CONFIG = {
    "agent_a": {"publish": True, "read": True},
    "agent_b": {"publish": True, "read": True},
    "bcrm_engine": {"read": True, "publish": True},
    "bcrm_sim_trader": {"read": True, "publish": True},
    "screen_engine": {"read": True, "publish": True},
    "tavily_macro": {"read": True, "publish": True},
    "a_research": {"read": True, "publish": True},
}


# ============================================================
# P0: A/B 决策写入 shared_memory_bus
# ============================================================

def _load_state() -> Dict[str, Any]:
    """加载已发布状态。"""
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"published_files": []}


def _save_state(state: Dict[str, Any]) -> None:
    """保存已发布状态。"""
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                           encoding="utf-8")


def _convert_log_to_event(log_data: Dict[str, Any],
                          agent_id: str) -> Dict[str, Any]:
    """
    将 A/B 日志转换为 shared_memory_bus 事件 payload。

    保留完整决策信息，附加标准化字段供 BCRM 消费。
    """
    ts = log_data.get("ts_utc", datetime.now().isoformat())
    action = log_data.get("action", "HOLD")
    confidence = log_data.get("confidence", 0.0)

    payload = {
        # 核心决策
        "agent_id": agent_id,
        "cycle_id": log_data.get("cycle_id", ""),
        "action": action,
        "confidence": confidence,
        "coin": log_data.get("coin", ""),
        "leverage": log_data.get("leverage", 1),
        "entry_price": log_data.get("entry_price", 0.0),
        "stop_loss": log_data.get("stop_loss_price"),
        "take_profit": log_data.get("take_profit_price"),

        # 市场状态
        "market_regime": log_data.get("market_regime", "UNKNOWN"),
        "key_contradictions": log_data.get("key_contradictions", []),
        "reasoning_steps": log_data.get("reasoning_steps", []),
        "decision_rationale": log_data.get("decision_rationale", ""),

        # 系统状态
        "system_features_used": log_data.get("system_features_used", []),
        "intent_type": log_data.get("intent_type"),
        "plan_budget_mode": log_data.get("plan_budget_mode"),

        # 交易结果（可能为 null，尚未平仓）
        "pnl_pct": log_data.get("pnl_pct"),
        "was_correct": log_data.get("was_correct"),
        "exit_reason": log_data.get("exit_reason"),

        # 持仓快照
        "active_positions": log_data.get("active_positions", {}),
        "account_equity": log_data.get("account_equity"),

        # 原始日志路径（供追溯）
        "source_agent": agent_id,
    }

    return payload


def publish_new_decisions(ab_log_dir: Path = None,
                          dry_run: bool = False) -> Dict[str, Any]:
    """
    扫描 A/B 日志目录，将新日志发布到 shared_memory_bus。

    Args:
        ab_log_dir: AB 日志根目录（下含 agent_a/ 和 agent_b/）
        dry_run: 仅打印不实际发布

    Returns:
        统计信息 {published, skipped, errors, total_a, total_b}
    """
    ab_log_dir = ab_log_dir or AB_LOG_DIR
    state = _load_state()
    published_set = set(state["published_files"])

    stats = {"published": 0, "skipped": 0, "errors": 0,
             "total_a": 0, "total_b": 0}

    for agent_subdir, agent_id in [("agent_a", "agent_a"),
                                   ("agent_b", "agent_b")]:
        log_dir = ab_log_dir / agent_subdir
        if not log_dir.exists():
            continue

        for log_file in sorted(log_dir.glob("*.json")):
            rel_path = f"{agent_subdir}/{log_file.name}"
            if rel_path in published_set:
                stats["skipped"] += 1
                continue

            try:
                log_data = json.loads(log_file.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"  [ERROR] 读取 {rel_path}: {e}")
                stats["errors"] += 1
                continue

            payload = _convert_log_to_event(log_data, agent_id)
            ts = payload.get("cycle_id") or payload.get("ts_utc") or \
                datetime.now().isoformat()

            if dry_run:
                print(f"  [DRY] {agent_id} {log_file.name}: "
                      f"{payload['action']} conf={payload['confidence']}")
            else:
                result = publish_shared_memory_event(
                    snapshot_ts=ts,
                    agent_id=agent_id,
                    event_type="trading_decision",
                    payload=payload,
                    acl_config=ACL_CONFIG,
                )
                if not result.get("ok"):
                    print(f"  [DENIED] {rel_path}: {result.get('reason')}")
                    stats["errors"] += 1
                    continue

            published_set.add(rel_path)
            stats["published"] += 1
            if agent_id == "agent_a":
                stats["total_a"] += 1
            else:
                stats["total_b"] += 1

    if not dry_run:
        state["published_files"] = sorted(published_set)
        _save_state(state)

    return stats


def read_ab_decisions(agent_id: str = "",
                      limit: int = 100) -> List[Dict[str, Any]]:
    """
    从 shared_memory_bus 读取 A/B 交易决策事件。

    Args:
        agent_id: 过滤特定 agent（"agent_a" / "agent_b"），空字符串=全部
        limit: 最多读取条数

    Returns:
        事件列表
    """
    # 读取需要 ACL 授权，用 bcrm_engine 身份读取
    read_agent = agent_id if agent_id else "bcrm_engine"
    events = read_shared_memory_events(
        limit=limit,
        agent_id=read_agent,
        acl_config=ACL_CONFIG,
    )
    # 如果指定了 agent_id 做过滤
    if agent_id and agent_id != "bcrm_engine":
        events = [e for e in events if e.get("agent_id") == agent_id]
    return events


def get_bus_stats() -> Dict[str, Any]:
    """获取 shared_memory_bus 的统计信息。"""
    events = read_shared_memory_events(
        limit=10000, agent_id="bcrm_engine", acl_config=ACL_CONFIG)
    a_events = [e for e in events if e.get("agent_id") == "agent_a"]
    b_events = [e for e in events if e.get("agent_id") == "agent_b"]

    a_actions = {}
    b_actions = {}
    for e in a_events:
        action = (e.get("payload") or {}).get("action", "UNKNOWN")
        a_actions[action] = a_actions.get(action, 0) + 1
    for e in b_events:
        action = (e.get("payload") or {}).get("action", "UNKNOWN")
        b_actions[action] = b_actions.get(action, 0) + 1

    return {
        "total_events": len(events),
        "agent_a_events": len(a_events),
        "agent_b_events": len(b_events),
        "a_action_distribution": a_actions,
        "b_action_distribution": b_actions,
        "bus_path": str(_default_bus_path()),
    }


# ============================================================
# P1: A/B 案例接入两仪引擎对比学习
# ============================================================

def _infer_macro_phase_from_regime(regime: str,
                                    confidence: float) -> Tuple[str, str]:
    """
    从 AB 日志的 market_regime 估算宏观美林时钟阶段。

    映射关系:
      BULL/TRENDING_UP → 复苏（春）或过热（夏）
      BEAR/TRENDING_DOWN → 衰退（冬）或滞胀（秋）
      SIDEWAYS/RANGE/UNCERTAIN → 中性，用置信度辅助判断

    Returns:
        (macro_phase, macro_season)
    """
    r = (regime or "").upper()
    # 从 BCRM _constants 导入常量
    from scripts.memory_l4.bcrm._constants import (
        MACRO_RECOVERY, MACRO_OVERHEAT, MACRO_STAGFLATION, MACRO_RECESSION,
        MACRO_SEASON,
    )

    if r in ("BULL", "TRENDING_UP", "UPTREND"):
        phase = MACRO_OVERHEAT if confidence > 0.7 else MACRO_RECOVERY
    elif r in ("BEAR", "TRENDING_DOWN", "DOWNTREND"):
        phase = MACRO_STAGFLATION if confidence > 0.6 else MACRO_RECESSION
    else:
        # SIDEWAYS/RANGE/UNCERTAIN → 用置信度
        phase = MACRO_RECOVERY if confidence > 0.5 else MACRO_RECESSION

    season = MACRO_SEASON.get(phase, "春")
    return phase, season


def _infer_micro_phase_from_log(log_payload: Dict[str, Any]) -> Tuple[str, str]:
    """
    从 AB 日志推断微观生命周期阶段。

    用持仓信息 + action 推断:
      持仓+LONG → 生长（夏）
      持仓+SHORT → 衰落（冬）
      HOLD+无持仓 → 萌芽（春）
      HOLD+有持仓 → 成熟（秋）
    """
    from scripts.memory_l4.bcrm._constants import (
        MICRO_SPROUT, MICRO_GROWTH, MICRO_MATURE, MICRO_DECLINE,
        MICRO_SEASON,
    )

    action = (log_payload.get("action") or "HOLD").upper()
    positions = log_payload.get("active_positions") or {}
    has_position = len(positions) > 0

    if action in ("LONG", "BUY") and has_position:
        phase = MICRO_GROWTH
    elif action in ("SHORT", "SELL"):
        phase = MICRO_DECLINE
    elif has_position:
        phase = MICRO_MATURE
    else:
        phase = MICRO_SPROUT

    season = MICRO_SEASON.get(phase, "春")
    return phase, season


def convert_event_to_learning_case(event: Dict[str, Any]) -> Optional[Dict]:
    """
    将 shared_memory_bus 事件转换为两仪引擎学习案例格式。

    liangyi_engine.learn_from_cases() 需要:
      - liangyi_state: {macro_phase, micro_phase, macro_season, micro_season, ...}
      - scale_params: {weight_time, weight_space, weight_surface, weight_core, ...}
      - actual_outcome: {is_correct: bool}

    Returns:
        学习案例 dict，或 None（数据不完整时跳过）
    """
    payload = event.get("payload") or {}
    action = payload.get("action", "HOLD")
    confidence = payload.get("confidence", 0.5)
    regime = payload.get("market_regime", "UNKNOWN")
    was_correct = payload.get("was_correct")
    pnl_pct = payload.get("pnl_pct")

    # 交易尚未平仓（was_correct=None 且 pnl=None），跳过
    if was_correct is None and pnl_pct is None:
        return None

    macro_phase, macro_season = _infer_macro_phase_from_regime(regime, confidence)
    micro_phase, micro_season = _infer_micro_phase_from_log(payload)

    is_resonance = macro_season == micro_season
    from scripts.memory_l4.bcrm._constants import SEASON_OPPOSITE
    is_conflict = SEASON_OPPOSITE.get(macro_season) == micro_season

    # 判断 is_correct
    if was_correct is not None:
        is_correct = bool(was_correct)
    elif pnl_pct is not None:
        is_correct = pnl_pct > 0
    else:
        # HOLD 且无 PnL：视为中性正确（不亏不赚）
        is_correct = action == "HOLD"

    # 估算 scale_params（用默认值，后续 P2 会用真实推理结果覆盖）
    from scripts.memory_l4.bcrm.scale_engine import ScaleParams
    default_params = ScaleParams()

    return {
        "case_id": f"{event.get('agent_id')}_{payload.get('cycle_id', '')}",
        "agent_id": event.get("agent_id"),
        "liangyi_state": {
            "macro_phase": macro_phase,
            "micro_phase": micro_phase,
            "macro_season": macro_season,
            "micro_season": micro_season,
            "is_resonance": is_resonance,
            "is_conflict": is_conflict,
        },
        "scale_params": {
            "weight_time": default_params.weight_time,
            "weight_space": default_params.weight_space,
            "weight_surface": default_params.weight_surface,
            "weight_core": default_params.weight_core,
            "market_mass_base": default_params.market_mass_base,
            "velocity_decay": default_params.velocity_decay,
        },
        "actual_outcome": {
            "is_correct": is_correct,
            "pnl_pct": pnl_pct,
            "action": action,
        },
        "market_regime": regime,
        "confidence": confidence,
        "coin": payload.get("coin", ""),
        "ts_utc": payload.get("cycle_id") or event.get("ts", ""),
    }


def run_comparative_learning(events: List[Dict[str, Any]] = None,
                              engine=None) -> Dict[str, Any]:
    """
    从 A/B 事件中提取学习案例，送入两仪引擎学习。

    Args:
        events: 事件列表（None 则从 bus 读取）
        engine: 两仪引擎实例（None 则新建）

    Returns:
        学习统计 {total_cases, valid_cases, by_agent, learned_stats}
    """
    from scripts.memory_l4.bcrm.liangyi_engine import LiangyiEngine

    if events is None:
        events = read_shared_memory_events(limit=10000, agent_id="bcrm_engine",
                                           acl_config=ACL_CONFIG)
    if engine is None:
        engine = LiangyiEngine()

    cases = []
    skipped = 0
    by_agent = {"agent_a": 0, "agent_b": 0}

    for event in events:
        case = convert_event_to_learning_case(event)
        if case is None:
            skipped += 1
            continue
        cases.append(case)
        aid = case.get("agent_id", "")
        if aid in by_agent:
            by_agent[aid] += 1

    if len(cases) == 0:
        return {
            "total_events": len(events),
            "valid_cases": 0,
            "skipped": skipped,
            "by_agent": by_agent,
            "learned": False,
            "reason": "no valid cases (all pending close)",
        }

    engine.learn_from_cases(cases)
    learned_stats = engine.get_learned_stats()
    season_stats = engine.get_learned_season_stats()

    return {
        "total_events": len(events),
        "valid_cases": len(cases),
        "skipped": skipped,
        "by_agent": by_agent,
        "learned": True,
        "learned_combos": len(learned_stats),
        "learned_seasons": len(season_stats),
        "combo_details": {
            f"{k[0]}|{k[1]}": {
                "total": v["total"],
                "correct": v["correct"],
                "win_rate": round(v["win_rate"], 4),
            }
            for k, v in learned_stats.items()
        },
        "season_details": {
            f"{k[0]}|{k[1]}": {
                "total": v["total"],
                "correct": v["correct"],
                "win_rate": round(v["win_rate"], 4),
            }
            for k, v in season_stats.items()
        },
    }


# ============================================================
# P2: BCRM 对 A/B 历史时点做模拟推理
# ============================================================

def _construct_market_snapshot_from_log(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    从 A/B 日志 payload 构造 BCRM 可用的市场快照。

    A/B 日志没有完整的四维评分，从推理步骤和持仓信息中提取估算值。
    """
    regime = (payload.get("market_regime") or "RANGE").upper()
    confidence = payload.get("confidence", 0.5)
    action = (payload.get("action") or "HOLD").upper()
    reasoning = " ".join(payload.get("reasoning_steps") or [])
    rationale = payload.get("decision_rationale") or ""

    # 从推理步骤中提取技术指标估算值
    # 尝试解析 RSI
    import re
    rsi_match = re.search(r"RSI[=\s]*(\d+\.?\d*)", reasoning + " " + rationale)
    rsi = float(rsi_match.group(1)) / 100.0 if rsi_match else 0.5

    # 尝试解析资金费率
    fr_match = re.search(r"资金费率[=\s]*(-?\d+\.?\d*)", reasoning + " " + rationale)
    funding_rate = float(fr_match.group(1)) / 100.0 if fr_match else 0.0

    # 从 regime 估算四维评分
    if regime in ("BULL", "TRENDING_UP"):
        sd, tech, cf, sent = 0.65, 0.65, 0.6, 0.6
        trend_strength = 0.6
    elif regime in ("BEAR", "TRENDING_DOWN"):
        sd, tech, cf, sent = 0.35, 0.35, 0.4, 0.3
        trend_strength = 0.6
    else:
        sd, tech, cf, sent = 0.5, 0.5, 0.5, 0.5
        trend_strength = 0.4

    # 用 RSI 微调技术面
    tech = (tech + rsi) / 2

    # 用 action 调整供需面
    if action in ("LONG", "BUY"):
        sd = max(0.5, sd)
    elif action in ("SHORT", "SELL"):
        sd = min(0.5, sd)

    return {
        "supply_demand_score": round(sd, 4),
        "technical_score": round(tech, 4),
        "capital_flow_score": round(cf, 4),
        "sentiment_score": round(sent, 4),
        "trend_strength": round(trend_strength, 4),
        "volatility": 0.5,
        "volume_ratio": 1.0,
        "price_position": 0.5,
        "snapshot_ts": payload.get("cycle_id") or payload.get("ts_utc", ""),
        "gdp_growth": 0.03,
        "cpi": 0.025,
        "interest_rate": 0.025,
        # 附加 AB 上下文
        "ab_regime": regime,
        "ab_confidence": confidence,
        "ab_action": action,
        "ab_coin": payload.get("coin", ""),
    }


def run_bcrm_on_event(event: Dict[str, Any],
                      engine=None) -> Optional[Dict[str, Any]]:
    """
    对 A/B 事件做 BCRM 模拟推理。

    Args:
        event: shared_memory_bus 事件
        engine: BCRM 引擎实例（None 则新建）

    Returns:
        三方对比结果 {ab_decision, bcrm_decision, agreement, ...}
    """
    from scripts.memory_l4.bcrm.engine import BCRMEngine

    if engine is None:
        engine = BCRMEngine()

    payload = event.get("payload") or {}
    market_snapshot = _construct_market_snapshot_from_log(payload)

    # 从 OKX 加载最近 K 线，注入到快照（驱动八卦力学引擎）
    try:
        from scripts.memory_l4.okx_simulated import OKXSimulatedClient
        coin = (market_snapshot.get("ab_coin") or "BTC").upper()
        if not coin.endswith("-USDT-SWAP"):
            inst_id = f"{coin}-USDT-SWAP"
        else:
            inst_id = coin
        okx = OKXSimulatedClient()
        kline_resp = okx.get_kline(inst_id, bar="1H", limit=60)
        kline_1h = kline_resp.get("candles", []) if isinstance(kline_resp, dict) else kline_resp
        if kline_1h and len(kline_1h) > 0:
            closes = [float(k.get("c", 0)) for k in kline_1h if k.get("c")]
            volumes = [float(k.get("vol", k.get("v", 0))) for k in kline_1h if k.get("vol", k.get("v"))]
            market_snapshot["closes_window"] = closes
            market_snapshot["volumes_window"] = volumes
            market_snapshot["price"] = closes[-1] if closes else 0
            # 重新计算 trend_strength
            if len(closes) >= 20:
                med_chg = (closes[-1] - closes[-20]) / closes[-20] if closes[-20] else 0
                market_snapshot["med_change_pct"] = med_chg
                market_snapshot["trend_strength"] = min(1.0, abs(med_chg) * 20)
            # 价格位置
            if closes:
                hi = max(closes)
                lo = min(closes)
                if hi > lo:
                    market_snapshot["price_position"] = (closes[-1] - lo) / (hi - lo)
    except Exception:
        pass

    # 构造矛盾列表（从 AB 日志的 key_contradictions 提取）
    contradictions = []
    for c in payload.get("key_contradictions") or []:
        contradictions.append({
            "id": c[:50] if isinstance(c, str) else "",
            "type": "ab_observed",
            "tension": 0.5,
            "dominant_side": "EQUAL",
            "description": c,
        })
    if not contradictions:
        # 默认矛盾
        contradictions = [{
            "id": "default",
            "type": "supply_demand",
            "tension": 0.5,
            "dominant_side": "EQUAL",
        }]

    # 运行 BCRM 推理
    bcrm_output = engine.infer(
        market_snapshot=market_snapshot,
        contradiction_list=contradictions,
        memory_cases=None,
    )

    # 提取 BCRM 决策
    bcrm_direction = bcrm_output.next_state.direction if bcrm_output.next_state else "UNKNOWN"
    bcrm_confidence = bcrm_output.next_state.confidence if bcrm_output.next_state else 0.0
    bcrm_hexagram = bcrm_output.hexagram.hexagram_name_cn if bcrm_output.hexagram else ""
    bcrm_changed_hexagram = bcrm_output.hexagram.changed_hexagram_cn if bcrm_output.hexagram else ""
    bcrm_direction_hint = bcrm_output.hexagram.direction_hint if bcrm_output.hexagram else "FLAT"
    bcrm_hexagram_confidence = bcrm_output.hexagram.confidence if bcrm_output.hexagram else 0.0
    is_fail_closed = (bcrm_output.next_state.derivation == "fail-closed"
                      if bcrm_output.next_state else True)

    # --- 八卦力学引擎：第一性原理力场计算（驱动底层）---
    bagua_result = None
    try:
        from scripts.memory_l4.bcrm.bagua_engine import BaguaEngine
        bagua_engine = BaguaEngine()
        closes = market_snapshot.get("closes_window") or []
        volumes = market_snapshot.get("volumes_window") or []
        bagua_result = bagua_engine.infer(
            snapshot=market_snapshot,
            closes=closes,
            volumes=volumes,
        )
    except Exception:
        pass

    # 融合 BCRM 与八卦力学方向
    final_direction = bcrm_direction
    final_confidence = bcrm_confidence
    final_hexagram = bcrm_hexagram
    if bagua_result is not None:
        bagua_dir = bagua_result.primary_direction
        bagua_conf = bagua_result.primary_confidence
        bagua_dir_num = 1 if bagua_dir == "long" else (-1 if bagua_dir == "short" else 0)
        bcrm_dir_num = 1 if bcrm_direction == "UP" else (-1 if bcrm_direction == "DOWN" else 0)

        if bcrm_dir_num != 0 and bagua_dir_num != 0:
            if bcrm_dir_num == bagua_dir_num:
                final_confidence = min(0.95, bcrm_confidence * 0.5 + bagua_conf * 0.5 + 0.1)
            else:
                if bagua_conf > bcrm_confidence + 0.2:
                    final_direction = "UP" if bagua_dir == "long" else "DOWN"
                    final_confidence = bagua_conf * 0.7
                else:
                    final_confidence = bcrm_confidence * 0.4
        elif bcrm_dir_num == 0 and bagua_dir_num != 0:
            final_direction = "UP" if bagua_dir == "long" else "DOWN"
            final_confidence = bagua_conf * 0.6
        elif bagua_dir_num == 0 and bcrm_dir_num != 0:
            final_confidence = bcrm_confidence * 0.7

        # 六十四卦名优先使用八卦力学结果
        if bagua_result.hexagram_name_cn:
            final_hexagram = bagua_result.hexagram_name_cn

    # AB 决策
    ab_action = payload.get("action", "HOLD").upper()
    ab_confidence = payload.get("confidence", 0.0)

    # 方向映射：AB action → BCRM direction
    direction_map = {"LONG": "UP", "SHORT": "DOWN", "HOLD": "FLAT",
                     "BUY": "UP", "SELL": "DOWN", "BLOCK": "FLAT"}
    ab_direction = direction_map.get(ab_action, "FLAT")

    # 一致性判断
    if bcrm_direction == ab_direction:
        agreement = "AGREE"
    elif bcrm_direction == "FLAT" or ab_direction == "FLAT":
        agreement = "PARTIAL"
    else:
        agreement = "DISAGREE"

    # 构造 bagua_engine 字段（供前端展示）
    bagua_payload = None
    if bagua_result is not None:
        bagua_payload = bagua_result.to_dict() if hasattr(bagua_result, "to_dict") else None

    return {
        "agent_id": event.get("agent_id"),
        "cycle_id": payload.get("cycle_id", ""),
        "coin": payload.get("coin", ""),
        "ab_decision": {
            "action": ab_action,
            "direction": ab_direction,
            "confidence": ab_confidence,
        },
        "bcrm_decision": {
            "direction": bcrm_direction,
            "confidence": round(bcrm_confidence, 4),
            "hexagram": bcrm_hexagram,
            "changed_hexagram": bcrm_changed_hexagram,
            "direction_hint": bcrm_direction_hint,
            "hexagram_confidence": round(bcrm_hexagram_confidence, 4),
            "fail_closed": is_fail_closed,
            "reason_codes": bcrm_output.reason_codes,
            "derivation": bcrm_output.next_state.derivation if bcrm_output.next_state else "",
            # === 八卦力学引擎输出（供前端展示）===
            "bagua_hexagram": bagua_result.hexagram_name_cn if bagua_result else "",
            "bagua_current_gua": bagua_result.current_gua_cn if bagua_result else "",
            "bagua_liangyi": (bagua_result.liangyi_state + f"({bagua_result.liangyi_strength:.2f})"
                              if bagua_result else ""),
            "bagua_primary_dir": bagua_result.primary_direction if bagua_result else "",
            "bagua_primary_conf": round(bagua_result.primary_confidence, 4) if bagua_result else 0,
            "bagua_sixiang": bagua_result.sixiang.to_dict() if bagua_result else {},
            "bagua_potential": bagua_result.potential_field.to_dict() if bagua_result else {},
        },
        # 八卦力学引擎输出（第一性原理）
        "bagua_engine": bagua_payload,
        # 融合后的最终决策
        "final_decision": {
            "direction": final_direction,
            "confidence": round(final_confidence, 4),
            "hexagram": final_hexagram,
        },
        "agreement": agreement,
        "liangyi_state": bcrm_output.liangyi_state,
        "scale_params": bcrm_output.scale_params,
        "market_snapshot": {
            "regime": market_snapshot["ab_regime"],
            "scores": {
                "sd": market_snapshot["supply_demand_score"],
                "tech": market_snapshot["technical_score"],
                "cf": market_snapshot["capital_flow_score"],
                "sent": market_snapshot["sentiment_score"],
            },
        },
    }


def run_bcrm_batch(events: List[Dict[str, Any]] = None,
                   limit: int = 50) -> Dict[str, Any]:
    """
    批量对 A/B 事件做 BCRM 模拟推理。

    Returns:
        批量统计 {total, success, fail_closed, agreement_stats, by_agent}
    """
    if events is None:
        events = read_shared_memory_events(limit=limit, agent_id="bcrm_engine",
                                           acl_config=ACL_CONFIG)

    from scripts.memory_l4.bcrm.engine import BCRMEngine
    engine = BCRMEngine()

    results = []
    agree_count = 0
    partial_count = 0
    disagree_count = 0
    fail_closed_count = 0

    for event in events:
        try:
            result = run_bcrm_on_event(event, engine=engine)
            if result:
                results.append(result)
                a = result["agreement"]
                if a == "AGREE":
                    agree_count += 1
                elif a == "PARTIAL":
                    partial_count += 1
                else:
                    disagree_count += 1
                if result["bcrm_decision"]["fail_closed"]:
                    fail_closed_count += 1
        except Exception as e:
            print(f"  [ERROR] BCRM inference failed: {e}")

    total = len(results)
    return {
        "total": total,
        "success": total - fail_closed_count,
        "fail_closed": fail_closed_count,
        "agreement_stats": {
            "agree": agree_count,
            "partial": partial_count,
            "disagree": disagree_count,
            "agree_rate": round(agree_count / total, 4) if total > 0 else 0,
        },
        "results": results[-20:],  # 返回最近20条
    }


# ============================================================
# P3: 元学习路由表
# ============================================================

class MetaLearningRouter:
    """
    元学习路由器 — 跟踪 A/B/BCRM 三方表现，推荐最优决策源。

    按 (market_regime, liangyi_state) 维度统计各方胜率，
    动态推荐当前场景下最可信的决策源。
    """

    def __init__(self):
        # 路由表: {(regime, macro_phase, micro_phase): {source: {wins, total}}}
        self._routing_table: Dict[Tuple[str, str, str], Dict[str, Dict]] = {}

    def update(self, regime: str, macro_phase: str, micro_phase: str,
               source: str, is_correct: bool) -> None:
        """更新路由表中某个源的胜率记录。"""
        key = (regime, macro_phase, micro_phase)
        if key not in self._routing_table:
            self._routing_table[key] = {}
        if source not in self._routing_table[key]:
            self._routing_table[key][source] = {"wins": 0, "total": 0}
        self._routing_table[key][source]["total"] += 1
        if is_correct:
            self._routing_table[key][source]["wins"] += 1

    def recommend(self, regime: str, macro_phase: str,
                  micro_phase: str) -> Dict[str, Any]:
        """
        推荐当前场景下最优决策源。

        Returns:
            {recommended_source, confidence, stats}
        """
        key = (regime, macro_phase, micro_phase)
        sources = self._routing_table.get(key, {})

        if not sources:
            return {
                "recommended_source": "bcrm_engine",
                "confidence": 0.0,
                "reason": "no_data_default",
                "stats": {},
            }

        # 计算各方胜率，选最高的
        best_source = None
        best_win_rate = -1
        stats = {}
        for source, s in sources.items():
            wr = s["wins"] / s["total"] if s["total"] > 0 else 0
            stats[source] = {"win_rate": round(wr, 4),
                             "total": s["total"], "wins": s["wins"]}
            if wr > best_win_rate and s["total"] >= 3:  # 最少3样本
                best_win_rate = wr
                best_source = source

        if best_source is None:
            return {
                "recommended_source": "bcrm_engine",
                "confidence": 0.0,
                "reason": "insufficient_samples",
                "stats": stats,
            }

        return {
            "recommended_source": best_source,
            "confidence": round(best_win_rate, 4),
            "reason": "best_win_rate",
            "stats": stats,
        }

    def get_routing_table(self) -> Dict[str, Any]:
        """获取完整路由表。"""
        out = {}
        for (regime, macro, micro), sources in self._routing_table.items():
            key = f"{regime}|{macro}|{micro}"
            out[key] = {}
            for source, s in sources.items():
                wr = s["wins"] / s["total"] if s["total"] > 0 else 0
                out[key][source] = {"win_rate": round(wr, 4),
                                    "total": s["total"], "wins": s["wins"]}
        return out

    def save(self, path: Path = None) -> None:
        """保存路由表到文件。"""
        path = path or (artifacts_memory_l4_dir() / "shared_bus" /
                        "meta_routing_table.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.get_routing_table(),
                                   ensure_ascii=False, indent=2),
                        encoding="utf-8")

    def build_from_events(self, events: List[Dict],
                          bcrm_results: List[Dict] = None) -> None:
        """
        从 A/B 事件和 BCRM 推理结果构建路由表。

        Args:
            events: shared_memory_bus 事件列表
            bcrm_results: P2 的 BCRM 推理结果列表
        """
        # 构建 bcrm_results 的索引
        bcrm_by_cycle = {}
        if bcrm_results:
            for r in bcrm_results:
                cycle = r.get("cycle_id", "")
                if cycle:
                    bcrm_by_cycle[f"{r.get('agent_id')}_{cycle}"] = r

        for event in events:
            payload = event.get("payload") or {}
            was_correct = payload.get("was_correct")
            pnl_pct = payload.get("pnl_pct")

            # 尚未平仓，跳过
            if was_correct is None and pnl_pct is None:
                continue

            agent_id = event.get("agent_id", "")
            regime = (payload.get("market_regime") or "UNKNOWN").upper()
            confidence = payload.get("confidence", 0.5)

            # 推断两仪状态
            macro_phase, _ = _infer_macro_phase_from_regime(regime, confidence)
            micro_phase, _ = _infer_micro_phase_from_log(payload)

            is_correct = bool(was_correct) if was_correct is not None else (
                (pnl_pct or 0) > 0)

            # 更新 A/B 路由
            self.update(regime, macro_phase, micro_phase, agent_id, is_correct)

            # 更新 BCRM 路由（如果有对应推理结果）
            cycle_id = payload.get("cycle_id", "")
            bcrm_key = f"{agent_id}_{cycle_id}"
            bcrm_r = bcrm_by_cycle.get(bcrm_key)
            if bcrm_r:
                bcrm_correct = self._evaluate_bcrm_correctness(
                    bcrm_r, payload)
                self.update(regime, macro_phase, micro_phase,
                            "bcrm_engine", bcrm_correct)

    @staticmethod
    def _evaluate_bcrm_correctness(bcrm_result: Dict,
                                    ab_payload: Dict) -> bool:
        """
        评估 BCRM 推理是否正确。

        用 AB 交易的实际结果作为 ground truth:
        - 如果 BCRM 方向与 AB 一致 → 用 AB 的 was_correct
        - 如果 BCRM 方向与 AB 不一致 → 用 AB 的反向结果
        """
        bcrm_dir = bcrm_result.get("bcrm_decision", {}).get("direction", "")
        ab_action = ab_payload.get("action", "HOLD").upper()

        direction_map = {"LONG": "UP", "SHORT": "DOWN", "HOLD": "FLAT"}
        ab_dir = direction_map.get(ab_action, "FLAT")

        was_correct = ab_payload.get("was_correct")
        pnl_pct = ab_payload.get("pnl_pct")

        if was_correct is None and pnl_pct is None:
            return False

        ab_correct = bool(was_correct) if was_correct is not None else (
            (pnl_pct or 0) > 0)

        # 如果 BCRM 与 AB 方向一致，AB 对则 BCRM 对
        if bcrm_dir == ab_dir:
            return ab_correct
        # 如果方向相反，AB 对则 BCRM 错
        elif bcrm_dir in ("UP", "DOWN") and ab_dir in ("UP", "DOWN"):
            return not ab_correct
        # BCRM 是 FLAT，如果 AB 亏损则 BCRM "对"（避损）
        elif bcrm_dir == "FLAT" and not ab_correct:
            return True
        else:
            return False


# ============================================================
# P4: 前端监控数据汇总
# ============================================================

def get_yijing_summary() -> Dict[str, Any]:
    """
    返回前端易经推理 Tab 所需的全部数据。

    包含: 总线统计、最近 BCRM 推理、学习进度、路由表。
    """
    # 1. 总线统计
    bus_stats = get_bus_stats()

    # 2. 最近事件
    events = read_shared_memory_events(
        limit=50, agent_id="bcrm_engine", acl_config=ACL_CONFIG)

    # 3. 最近 BCRM 推理（取最近 10 条）
    recent_bcrm = []
    try:
        bcrm_batch = run_bcrm_batch(events=events[-10:])
        recent_bcrm = bcrm_batch.get("results", [])
    except Exception:
        pass

    # 4. 学习进度
    learn_stats = {}
    try:
        learn_stats = run_comparative_learning(events=events)
    except Exception:
        pass

    # 5. 路由表
    routing_path = artifacts_memory_l4_dir() / "shared_bus" / "meta_routing_table.json"
    routing_table = {}
    if routing_path.exists():
        try:
            routing_table = json.loads(routing_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # 6. 最新 BCRM 推理详情（取第一条）
    latest_bcrm = recent_bcrm[0] if recent_bcrm else None

    # 如果有 bagua 引擎结果，融合进显示字段（让前端能看到第一性原理）
    if latest_bcrm and latest_bcrm.get("bagua_engine"):
        be = latest_bcrm["bagua_engine"]
        bd = latest_bcrm.get("bcrm_decision", {})
        # 优先显示八卦力学的六十四卦 + 主方向
        if be.get("hexagram_name_cn"):
            bd["hexagram"] = be["hexagram_name_cn"]
        if be.get("primary_direction"):
            direction_map = {"long": "UP", "short": "DOWN", "neutral": "FLAT"}
            bd["direction_hint"] = direction_map.get(be["primary_direction"], "FLAT")
        if be.get("primary_confidence") is not None:
            bd["hexagram_confidence"] = round(be["primary_confidence"], 4)
        # 把四象数据塞进 liangyi_state 字段（前端会读）
        six = be.get("sixiang", {})
        pf = be.get("potential_field", {})
        latest_bcrm["liangyi_state"] = {
            "macro_phase_cn": f"八卦={be.get('current_gua_cn', '--')} | 势能场=长{be.get('liangyi_strength', 0):.2f}",
            "macro_season": be.get("liangyi_state", ""),
            "micro_phase_cn": f"时={six.get('time_force', 0):+.2f} 空={six.get('space_force', 0):+.2f} 表={six.get('surface_force', 0):+.2f} 里={six.get('core_force', 0):+.2f}",
            "micro_season": f"势 {pf.get('least_resistance_dir', 'neutral')} | gap={pf.get('resistance_gap', 0):.2f}",
            "is_resonance": be.get("liangyi_state") == "yang",
            "is_conflict": be.get("liangyi_state") == "yin",
            "resonance_factor": f"mag={six.get('magnitude', 0):.2f} con={six.get('consistency', 0):.2f}",
            "trend_strength": six.get("magnitude", 0),
        }
        latest_bcrm["bcrm_decision"] = bd

    # 7. 模拟交易数据
    sim_summary = {}
    try:
        sim_summary = get_sim_trade_summary()
    except Exception:
        pass

    # 8. 三屏马丁数据
    screen_data = {}
    try:
        from scripts.memory_l4.screen_martin_bridge import get_screen_engine_summary
        sc = get_screen_engine_summary()
        if sc.get("ok"):
            screen_data = {
                "overall_score": sc.get("overall_score", 0),
                "direction": sc.get("direction", ""),
                "recommendation": sc.get("recommendation", ""),
            }
    except Exception:
        pass

    # 9. A系列研报数据
    research_data = {}
    try:
        from scripts.memory_l4.a_research_bridge import get_research_summary
        rs = get_research_summary()
        research_data = rs
    except Exception:
        pass

    # 10. 事件类型统计
    event_types = {}
    for e in events:
        et = e.get("event_type", "unknown")
        event_types[et] = event_types.get(et, 0) + 1

    # 11. QMM 量化内核信号（从 signals_index.json 读取，未运行则返回空状态）
    qmm_data = _get_qmm_summary()

    # 12. L4 案例库统计 + LiangyiEngine 持久化学习状态
    l4_case_count = 0
    l4_liangyi_learned = {}
    try:
        from scripts.memory_l4.paths import memory_l4_cases_dir, memory_l4_dir
        cases_dir = memory_l4_cases_dir()
        if cases_dir.exists():
            l4_case_count = len(list(cases_dir.glob("*.json")))
        liangyi_path = memory_l4_dir() / "liangyi_state.json"
        if liangyi_path.exists():
            ls_data = json.loads(liangyi_path.read_text(encoding="utf-8"))
            l4_liangyi_learned = {
                "combo_count": len(ls_data.get("learned_stats", {})),
                "season_count": len(ls_data.get("learned_season_stats", {})),
                "combo_details": {
                    k: {"total": v.get("total", 0), "win_rate": round(v.get("win_rate", 0), 4)}
                    for k, v in ls_data.get("learned_stats", {}).items()
                },
            }
    except Exception:
        pass

    # 13. BCRM 2.0 实时推理（用本地K线数据，不依赖OKX API）
    bcrm2_latest = {}
    try:
        from scripts.memory_l4.bcrm2_adapter import BCRM2Adapter
        from pathlib import Path as _Path
        import pandas as _pd

        kline_file = _Path(__file__).resolve().parents[1] / "data" / "klines" / "BTC_1H.csv"
        if kline_file.exists():
            df = _pd.read_csv(kline_file)
            if "timestamp" in df.columns:
                df["timestamp"] = _pd.to_datetime(df["timestamp"])
                df = df.set_index("timestamp")
            adapter = BCRM2Adapter("BTC", "1H")
            result = adapter.infer(df, auto_train=False)
            if result and result.get("ok") is not False:
                ns = result.get("next_state", {})
                hex_info = result.get("hexagram", {}) or {}
                bcrm2_latest = {
                    "available": True,
                    "symbol": "BTC",
                    "timeframe": "1H",
                    "direction": ns.get("direction", "FLAT"),
                    "confidence": ns.get("confidence", 0),
                    "derivation": ns.get("derivation", ""),
                    "fail_closed": result.get("is_fail_closed", lambda: False)() if callable(result.get("is_fail_closed")) else result.get("is_fail_closed", True),
                    "hexagram": {
                        "name_cn": hex_info.get("hexagram_name_cn", ""),
                        "name": hex_info.get("hexagram_name", ""),
                        "upper_gua": hex_info.get("upper_gua", {}).get("name", "") if isinstance(hex_info.get("upper_gua"), dict) else "",
                        "lower_gua": hex_info.get("lower_gua", {}).get("name", "") if isinstance(hex_info.get("lower_gua"), dict) else "",
                        "meaning": hex_info.get("hexagram_meaning", ""),
                        "risk_level": hex_info.get("risk_level", ""),
                        "direction_hint": hex_info.get("direction_hint", ""),
                        "mutual_gua": hex_info.get("mutual_gua", ""),
                        "changed_gua": hex_info.get("changed_gua", ""),
                        "narrative": hex_info.get("narrative", "")[:200] if hex_info.get("narrative") else "",
                    },
                    "position_factor": result.get("position_factor", 1.0),
                    "sl_tighten_factor": result.get("sl_tighten_factor", 1.0),
                    "early_exit_signal": result.get("early_exit_signal", False),
                }
    except Exception as e:
        bcrm2_latest = {"available": False, "error": str(e)[:100]}

    # 14. 增量学习 / 反馈闭环状态
    incremental_learning_state = {}
    try:
        from scripts.memory_l4.bcrm2.incremental_learner import IncrementalLearner
        learner = IncrementalLearner()
        perf = learner.db.get_recent_performance("BTC")
        versions = learner.version_manager.list_versions("BTC") if hasattr(learner, 'version_manager') else []
        should_retrain, retrain_reason = learner.should_retrain("BTC")
        incremental_learning_state = {
            "available": True,
            "total_trades": perf.get("n_trades", 0),
            "win_rate": perf.get("win_rate", 0),
            "total_pnl": perf.get("total_pnl", 0),
            "sharpe": perf.get("sharpe", 0),
            "model_versions": len(versions) if isinstance(versions, list) else 0,
            "should_retrain": should_retrain,
            "retrain_reason": retrain_reason,
            "feedback_loop_healthy": True,
        }
    except Exception as e:
        incremental_learning_state = {"available": False, "error": str(e)[:100]}

    return {
        "bus_stats": bus_stats,
        "event_types": event_types,
        "latest_bcrm": latest_bcrm,
        "recent_bcrm_count": len(recent_bcrm),
        "agreement_stats": {
            "agree": sum(1 for r in recent_bcrm if r.get("agreement") == "AGREE"),
            "partial": sum(1 for r in recent_bcrm if r.get("agreement") == "PARTIAL"),
            "disagree": sum(1 for r in recent_bcrm if r.get("agreement") == "DISAGREE"),
        },
        "learn_stats": {
            "valid_cases": learn_stats.get("valid_cases", 0),
            "learned_combos": learn_stats.get("learned_combos", 0),
            "combo_details": learn_stats.get("combo_details", {}),
            "season_details": learn_stats.get("season_details", {}),
        } if learn_stats.get("learned") else {
            "valid_cases": 0,
            "learned_combos": 0,
            "note": "尚无足够已平仓案例用于学习",
        },
        "routing_table": routing_table,
        "routing_entries": len(routing_table),
        "sim_trade": sim_summary,
        "screen_martin": screen_data,
        "research": research_data,
        "qmm": qmm_data,
        "l4_case_count": l4_case_count,
        "l4_liangyi_learned": l4_liangyi_learned,
        "bcrm2": bcrm2_latest,
        "incremental_learning": incremental_learning_state,
    }


def _get_qmm_summary() -> Dict[str, Any]:
    """
    读取 QMM 量化内核最新信号（从 signals_index.json）。

    QMM 是 Sidecar 量化内核，需先调用 run_qmm_with_gate() 生成信号。
    未运行时返回空状态（available=False），前端展示友好提示。
    """
    try:
        from scripts.memory_l4.qmm.paths import qmm_dir
        signals_path = qmm_dir() / "signals_index.json"
        if not signals_path.exists():
            return {
                "available": False,
                "note": "QMM 未运行，需先调用 run_qmm_with_gate() 生成信号（要求 ≥15 个 case）",
                "gate_status": "OFFLINE",
            }
        data = json.loads(signals_path.read_text(encoding="utf-8"))
        # 读取最新 snapshot 详情（如果存在）
        snapshot_file = data.get("output_file")
        snapshot_detail = {}
        if snapshot_file:
            sp = Path(snapshot_file)
            if not sp.is_absolute():
                sp = qmm_dir() / snapshot_file
            if sp.exists():
                try:
                    snapshot_detail = json.loads(sp.read_text(encoding="utf-8"))
                except Exception:
                    pass
        # Fallback: 如果 output_file 路径不存在（如迁移后路径变化），
        # 从 qmm_dir 中找最新的快照文件
        if not snapshot_detail:
            try:
                import glob
                snap_files = sorted(
                    glob.glob(str(qmm_dir() / "qmm_snapshot_*.json")),
                    reverse=True,
                )
                for sf in snap_files:
                    try:
                        snap_data = json.loads(Path(sf).read_text(encoding="utf-8"))
                        if snap_data.get("version") or snap_data.get("qmm_version"):
                            snapshot_detail = snap_data
                            break
                    except Exception:
                        continue
            except Exception:
                pass
        return {
            "available": True,
            "signals_index": data,
            "snapshot": snapshot_detail,
            "gate_status": data.get("gate_status") or (
                "FAILED" if data.get("gate_results", {}).get("passed") is False else
                ("PASSED" if data.get("gate_results", {}).get("passed") else "UNKNOWN")),
            "gate_results": data.get("gate_results", data.get("gate", {})),
            "snapshot_ts": data.get("generated_at", ""),
            "version_triple": {
                "data_version": data.get("data_version", ""),
                "feature_def_version": data.get("feature_def_version", ""),
                "qmm_version": data.get("qmm_version", ""),
            },
            # 六契约核心信号
            "trend_state": data.get("trend_state", "UNKNOWN"),
            "trend_change_point": data.get("trend_change_point", "STABLE"),
            "mrd_vector": data.get("mrd_vector", {}),
            "uncertainty": data.get("uncertainty", 0.0),
            "reason_codes": data.get("reason_codes", []),
            "evidence_refs": data.get("evidence_refs", []),
            # 三屏对齐（优先从 signals_index 直接读取）
            "triple_screen": data.get("triple_screen") or snapshot_detail.get("triple_screen", {}),
            "velocity": data.get("velocity") or snapshot_detail.get("velocity", {}),
            "acceleration": data.get("acceleration") or snapshot_detail.get("acceleration", {}),
        }
    except Exception as e:
        return {
            "available": False,
            "error": str(e),
            "gate_status": "OFFLINE",
        }


# ============================================================
# P8: 模拟交易闭环 (BCRM → OKX模拟盘 → 写回总线)
# ============================================================

def _map_bcrm_to_action(bcrm_decision: Dict[str, Any],
                        strategy_branches: List[Dict] = None,
                        bcrm_result: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    将 BCRM 推理结果映射为交易操作（含风控参数）。

    新增：fail-closed 时检查八卦力学引擎方向，若 bagua 信号强则 override。

    Returns:
        dict with keys: action, stop_loss_px, take_profit_px, reduce_ratio
    """
    direction = bcrm_decision.get("direction", "FLAT")
    confidence = bcrm_decision.get("confidence", 0.0)
    fail_closed = bcrm_decision.get("fail_closed", True)

    result = {
        "action": "hold",
        "stop_loss_px": 0,
        "take_profit_px": 0,
        "reduce_ratio": 0,
    }

    # 从策略分支中提取风控参数（取 B1 主路径）
    if strategy_branches:
        b1 = next((b for b in strategy_branches if b.get("branch_id") == "B1"), None)
        if b1:
            result["stop_loss_px"] = b1.get("stop_loss_px", 0)
            result["take_profit_px"] = b1.get("take_profit_px", 0)
            result["reduce_ratio"] = b1.get("reduce_ratio", 0)

    # 检查八卦力学引擎 override（fail-closed 或低置信度时）
    bagua_override = False
    if bcrm_result:
        be = bcrm_result.get("bagua_engine")
        if be:
            bagua_dir = be.get("primary_direction")
            bagua_conf = be.get("primary_confidence", 0)
            # bagua 置信度 > 0.45 且方向明确时，允许 override
            if bagua_conf >= 0.45 and bagua_dir in ("long", "short"):
                bagua_override = True
                direction = "UP" if bagua_dir == "long" else "DOWN"
                confidence = max(confidence, bagua_conf * 0.8)

    if not bagua_override:
        if fail_closed:
            return result
        if confidence < 0.3:
            return result

    if direction == "UP":
        result["action"] = "open_long"
    elif direction == "DOWN":
        result["action"] = "open_short"
    else:
        result["action"] = "hold"

    return result


def run_simulated_trade(event: Dict[str, Any] = None,
                        bcrm_result: Dict[str, Any] = None,
                        engine=None) -> Dict[str, Any]:
    """
    执行一次模拟交易闭环：BCRM推理 → OKX模拟下单 → 写回总线

    Args:
        event: shared_memory_bus 事件（None 则用最新事件）
        bcrm_result: 已有的 BCRM 结果（None 则重新推理）
        engine: BCRM 引擎实例

    Returns:
        模拟交易结果
    """
    from scripts.memory_l4.okx_simulated import OKXSimulatedClient
    from scripts.memory_l4.shared_memory_bus import publish_shared_memory_event

    if event is None:
        events = read_shared_memory_events(limit=1, agent_id="bcrm_engine",
                                           acl_config=ACL_CONFIG)
        if not events:
            return {"ok": False, "error": "no events in bus"}
        event = events[0]

    if bcrm_result is None:
        bcrm_result = run_bcrm_on_event(event, engine=engine)

    bcrm_dec = bcrm_result.get("bcrm_decision", {})
    strategy_branches = bcrm_result.get("strategy_branches", [])

    # 多币种：从 event/bcrm_result 中提取 coin 并映射到 OKX inst_id
    coin = bcrm_result.get("coin", "BTC")
    if not coin:
        payload_coin = event.get("payload", {}).get("coin", "")
        coin = payload_coin or "BTC"
    inst_id = f"{coin.upper()}-USDT-SWAP" if not coin.upper().endswith("-USDT-SWAP") else coin.upper()

    action_info = _map_bcrm_to_action(bcrm_dec, strategy_branches, bcrm_result)
    action = action_info["action"]

    client = OKXSimulatedClient()
    sim_result = client.simulate_trade_from_bcrm(
        bcrm_result={
            "hexagram": bcrm_dec.get("hexagram", ""),
            "two_yi_state": bcrm_result.get("liangyi_state", ""),
            "direction": bcrm_dec.get("direction", ""),
            "confidence": bcrm_dec.get("confidence", 0.0),
            "action": action,
            "stop_loss_px": action_info["stop_loss_px"],
            "take_profit_px": action_info["take_profit_px"],
            "reduce_ratio": action_info["reduce_ratio"],
        },
        inst_id=inst_id,
    )

    payload = bcrm_result.get("market_snapshot", {}).copy()
    payload.update({
        "cycle_id": bcrm_result.get("cycle_id", ""),
        "coin": bcrm_result.get("coin", "BTC"),
        "bcrm_decision": bcrm_dec,
        "liangyi_state": bcrm_result.get("liangyi_state", ""),
        "scale_params": bcrm_result.get("scale_params", {}),
        "strategy_branches": strategy_branches,
        "sim_action": action,
        "sim_stop_loss_px": action_info["stop_loss_px"],
        "sim_take_profit_px": action_info["take_profit_px"],
        "sim_reduce_ratio": action_info["reduce_ratio"],
        "sim_trade_result": sim_result,
    })

    publish_result = publish_shared_memory_event(
        snapshot_ts=event.get("ts", ""),
        agent_id="bcrm_sim_trader",
        event_type="sim_trade_executed",
        payload=payload,
        acl_config=ACL_CONFIG,
    )

    return {
        "ok": True,
        "bcrm_result": bcrm_result,
        "action": action,
        "sim_trade": sim_result,
        "published": publish_result.get("ok", False),
        "publish_result": publish_result,
    }


def run_simulated_batch(limit: int = 10) -> Dict[str, Any]:
    """
    批量执行模拟交易闭环。

    Args:
        limit: 最多处理多少条事件

    Returns:
        批量统计
    """
    from scripts.memory_l4.bcrm.engine import BCRMEngine

    events = read_shared_memory_events(limit=limit, agent_id="bcrm_engine",
                                       acl_config=ACL_CONFIG)
    engine = BCRMEngine()

    results = []
    actions_count = {"open_long": 0, "open_short": 0, "hold": 0,
                     "close_long": 0, "close_short": 0}

    for event in events:
        try:
            r = run_simulated_trade(event=event, engine=engine)
            results.append(r)
            action = r.get("action", "hold")
            actions_count[action] = actions_count.get(action, 0) + 1
        except Exception as e:
            results.append({"ok": False, "error": str(e)})

    success = sum(1 for r in results if r.get("ok"))
    executed = sum(1 for r in results
                   if r.get("action") and r["action"] != "hold"
                   and r.get("sim_trade", {}).get("executed"))

    return {
        "total": len(events),
        "success": success,
        "failed": len(events) - success,
        "executed_trades": executed,
        "actions": actions_count,
        "results": results,
    }


def get_sim_trade_summary() -> Dict[str, Any]:
    """获取模拟交易汇总数据（供前端）"""
    from scripts.memory_l4.okx_simulated import OKXSimulatedClient, CONFIG_DIR

    events = read_shared_memory_events(limit=500, agent_id="bcrm_engine",
                                       acl_config=ACL_CONFIG)
    sim_events = [e for e in events
                  if e.get("event_type") == "sim_trade_executed"]

    client = OKXSimulatedClient()
    perf = client.get_performance_summary()

    action_count = {"open_long": 0, "open_short": 0, "hold": 0,
                    "close_long": 0, "close_short": 0}
    hexagram_count = {}
    liangyi_count = {}

    for e in sim_events:
        payload = e.get("payload", {})
        action = payload.get("sim_action", "hold")
        action_count[action] = action_count.get(action, 0) + 1

        hexagram = payload.get("bcrm_decision", {}).get("hexagram", "")
        if hexagram:
            hexagram_count[hexagram] = hexagram_count.get(hexagram, 0) + 1

        liangyi = payload.get("liangyi_state", "")
        if liangyi:
            if isinstance(liangyi, dict):
                ly_key = liangyi.get("macro_phase_cn", "") + "_" + liangyi.get("micro_phase_cn", "")
                liangyi_count[ly_key] = liangyi_count.get(ly_key, 0) + 1
            else:
                liangyi_count[liangyi] = liangyi_count.get(liangyi, 0) + 1

    latest_sim = sim_events[-1] if sim_events else None
    latest_action = latest_sim.get("payload", {}).get("sim_action", "") if latest_sim else ""
    latest_hexagram = (latest_sim.get("payload", {}).get("bcrm_decision", {}).get("hexagram", "")
                       if latest_sim else "")

    return {
        "sim_trade_count": len(sim_events),
        "action_distribution": action_count,
        "top_hexagrams": dict(sorted(hexagram_count.items(),
                                     key=lambda x: -x[1])[:8]),
        "liangyi_distribution": liangyi_count,
        "latest": {
            "action": latest_action,
            "hexagram": latest_hexagram,
            "ts": latest_sim.get("ts", "") if latest_sim else "",
        },
        "okx_performance": perf,
        "config_dir": str(CONFIG_DIR),
    }


# ============================================================
# CLI 入口
# ============================================================

def cli():
    """命令行入口。"""
    import argparse
    parser = argparse.ArgumentParser(description="AB Bridge — AB 交易与易经大模型桥接")
    sub = parser.add_subparsers(dest="command")

    # P0: 发布新决策
    p_publish = sub.add_parser("publish", help="发布新 A/B 决策到 shared_memory_bus")
    p_publish.add_argument("--dry-run", action="store_true", help="仅预览不实际发布")
    p_publish.add_argument("--log-dir", type=str, default=None, help="AB 日志目录")

    # P0: 查看统计
    sub.add_parser("stats", help="查看 shared_memory_bus 统计")

    # P1: 对比学习
    sub.add_parser("learn", help="从 A/B 事件学习到两仪引擎")

    # P2: BCRM 模拟推理
    p_sim = sub.add_parser("simulate", help="BCRM 对 A/B 时点模拟推理")
    p_sim.add_argument("--limit", type=int, default=50, help="最多推理条数")

    # P3: 构建路由表
    sub.add_parser("route", help="构建元学习路由表")

    # 全流程
    sub.add_parser("run-all", help="运行 P0→P1→P2→P3 全流程")

    sub.add_parser("yijing-status", help="获取易经推理监控数据（供前端）")

    # P8: 模拟交易
    p_simtrade = sub.add_parser("sim-trade", help="执行 BCRM 模拟交易闭环")
    p_simtrade.add_argument("--limit", type=int, default=1, help="处理事件数量")
    p_simtrade.add_argument("--batch", action="store_true", help="批量模式")

    sub.add_parser("sim-trade-summary", help="获取模拟交易汇总数据")

    # P4: 三层自进化
    p_evolve = sub.add_parser("self-evolve", help="触发三层自进化（A8+做梦部+联网反思）")
    p_evolve.add_argument("--force", action="store_true", help="强制触发（忽略停滞检测）")

    args = parser.parse_args()

    if args.command == "publish":
        log_dir = Path(args.log_dir) if args.log_dir else None
        print("P0: 发布 A/B 决策到 shared_memory_bus")
        stats = publish_new_decisions(ab_log_dir=log_dir, dry_run=args.dry_run)
        print(f"  发布: {stats['published']}")
        print(f"  跳过(已发布): {stats['skipped']}")
        print(f"  错误: {stats['errors']}")
        print(f"  Agent A 总计: {stats['total_a']}")
        print(f"  Agent B 总计: {stats['total_b']}")

    elif args.command == "stats":
        stats = get_bus_stats()
        print(json.dumps(stats, ensure_ascii=False, indent=2))

    elif args.command == "learn":
        print("P1: 从 A/B 事件对比学习")
        result = run_comparative_learning()
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "simulate":
        print("P2: BCRM 模拟推理")
        result = run_bcrm_batch(limit=args.limit)
        # 不打印全部 results，只打印统计
        summary = {k: v for k, v in result.items() if k != "results"}
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    elif args.command == "route":
        print("P3: 构建元学习路由表")
        events = read_shared_memory_events(limit=10000, agent_id="bcrm_engine",
                                           acl_config=ACL_CONFIG)
        bcrm_results = run_bcrm_batch(events=events)
        router = MetaLearningRouter()
        router.build_from_events(events, bcrm_results["results"])
        router.save()
        print(json.dumps(router.get_routing_table(), ensure_ascii=False, indent=2))

    elif args.command == "run-all":
        print("=" * 60)
        print("AB Bridge 全流程: P0 → P1 → P2 → P3")
        print("=" * 60)

        # P0
        print("\n[P0] 发布 A/B 决策...")
        p0_stats = publish_new_decisions()
        print(f"  发布: {p0_stats['published']}, 跳过: {p0_stats['skipped']}")
        bus_stats = get_bus_stats()
        print(f"  Bus 总事件: {bus_stats['total_events']}")

        # P1
        print("\n[P1] 对比学习...")
        p1_result = run_comparative_learning()
        print(f"  有效案例: {p1_result.get('valid_cases', 0)}")
        print(f"  学习组合: {p1_result.get('learned_combos', 0)}")
        if p1_result.get("combo_details"):
            for combo, stats in p1_result["combo_details"].items():
                print(f"    {combo}: {stats['correct']}/{stats['total']} "
                      f"(WR={stats['win_rate']:.1%})")

        # P2
        print("\n[P2] BCRM 模拟推理...")
        events = read_shared_memory_events(limit=100, agent_id="bcrm_engine",
                                           acl_config=ACL_CONFIG)
        p2_result = run_bcrm_batch(events=events)
        agree = p2_result["agreement_stats"]
        print(f"  推理: {p2_result['total']}, "
              f"Fail-closed: {p2_result['fail_closed']}")
        print(f"  一致: {agree['agree']}, 部分: {agree['partial']}, "
              f"不一致: {agree['disagree']}")
        print(f"  一致率: {agree['agree_rate']:.1%}")

        # P3
        print("\n[P3] 构建路由表...")
        router = MetaLearningRouter()
        router.build_from_events(events, p2_result["results"])
        router.save()
        table = router.get_routing_table()
        print(f"  路由条目: {len(table)}")
        for key, sources in list(table.items())[:5]:
            print(f"    {key}:")
            for src, s in sources.items():
                print(f"      {src}: WR={s['win_rate']:.1%} ({s['wins']}/{s['total']})")

        print("\n" + "=" * 60)
        print("全流程完成")
        print("=" * 60)

    elif args.command == "self-evolve":
        # P4: 三层自进化（A8 + 做梦部 + 联网反思）
        print("=" * 60)
        print("P4: 三层自进化引擎")
        print("=" * 60)
        try:
            from scripts.memory_l4.self_evolution_engine import SelfEvolutionEngine
            # 收集系统表现统计
            bus_stats = get_bus_stats()
            sim_summary_raw = json.loads(
                __import__("subprocess").run(
                    [sys.executable, "-m", "scripts.memory_l4.ab_bridge", "sim-trade-summary"],
                    capture_output=True, text=True, cwd=str(_ROOT)
                ).stdout or "{}"
            )
            dist = sim_summary_raw.get("action_distribution", {})
            total = sum(dist.values()) or 1
            hold_rate = dist.get("hold", 0) / total

            stats = {
                "win_rate":       0.5,   # 真实数据待接入
                "hold_rate":      hold_rate,
                "hold_streak":    hold_rate * 10,
                "top_hexagrams":  sim_summary_raw.get("top_hexagrams", {}),
                "total_trades":   total,
            }

            engine = SelfEvolutionEngine()
            should, reason = engine.should_trigger(stats)
            force = getattr(args, "force", False)

            if should or force:
                print(f"触发原因: {reason}")
                result = engine.run_full_cycle(stats, [], force=force)
                print(json.dumps({
                    "adopted_count": len(result["adopted"]),
                    "proposals":     [p["title"] for p in result["proposals"]],
                    "adopted":       [p["title"] for p in result["adopted"]],
                }, ensure_ascii=False, indent=2))
            else:
                print(f"无需触发: {reason}")
                print(json.dumps({"should_trigger": False, "reason": reason},
                                  ensure_ascii=False))
        except Exception as e:
            import traceback
            print(json.dumps({"error": str(e), "traceback": traceback.format_exc()},
                              ensure_ascii=False))

    elif args.command == "yijing-status":
        result = get_yijing_summary()
        print(json.dumps(result, ensure_ascii=False, default=str, indent=2))

    elif args.command == "sim-trade":
        if args.batch:
            print(f"P8: 批量模拟交易 (limit={args.limit})")
            result = run_simulated_batch(limit=args.limit)
            summary = {k: v for k, v in result.items() if k != "results"}
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            print("P8: 单次模拟交易")
            result = run_simulated_trade()
            print(f"  操作: {result.get('action')}")
            print(f"  卦象: {result.get('bcrm_result', {}).get('bcrm_decision', {}).get('hexagram', '')}")
            print(f"  两仪: {result.get('bcrm_result', {}).get('liangyi_state', '')}")
            sim = result.get("sim_trade", {})
            print(f"  执行: {sim.get('executed', False)}")
            if sim.get("order_result"):
                ord_r = sim["order_result"]
                if ord_r.get("dry_run"):
                    print(f"  Dry-run: 预估价格 {ord_r.get('estimated_price')}")
            print(f"  写回总线: {result.get('published', False)}")

    elif args.command == "sim-trade-summary":
        result = get_sim_trade_summary()
        print(json.dumps(result, ensure_ascii=False, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    cli()
