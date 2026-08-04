#!/usr/bin/env python3
"""Agent A 记忆系统 — 跨 session 持久化记忆
包含：Lessons 管理、交易记录、大师切换、连胜连败追踪
"""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional

# L4 TradeEvent 注册（跨系统统一交易记录）
try:
    _L4_ROOT = Path(__file__).resolve().parents[3] / "11-易经推理系统"
    if str(_L4_ROOT) not in sys.path:
        sys.path.insert(0, str(_L4_ROOT))
    from scripts.memory_l4.trade_event import TradeEvent
    from scripts.memory_l4.case_registry import UnifiedCaseRegistry
    _L4_ENABLED = True
except Exception as _e:
    _L4_ENABLED = False

MEMORY_PATH = Path(__file__).parent.parent / "data" / "agent_a_memory.json"

MASTER_LIST = [
    "Jesse Livermore",
    "Paul Tudor Jones",
    "Richard Dennis",
    "Stanley Druckenmiller",
    "Jim Simons",
]

MAX_LESSONS = 20
MAX_RECENT_TRADES = 50
MAX_PENDING_STRATEGIES = 5

# 连败保护最大持续时间（小时），超时后自动重置 loss_streak
LOSS_PROTECTION_MAX_HOURS = 48
# 触发连败保护冷却的连败笔数阈值（连败达到此值才强制 HOLD 观望）
LOSS_PROTECTION_TRIGGER = 15


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_memory() -> Dict:
    """加载记忆，不存在则初始化"""
    if MEMORY_PATH.exists():
        try:
            with open(MEMORY_PATH) as f:
                data = json.load(f)
                if "hold_streak" not in data:
                    data["hold_streak"] = 0
                if "loss_protection_start_ts" not in data:
                    data["loss_protection_start_ts"] = None
                if "evolution" not in data:
                    data["evolution"] = {
                        "adopted_params": {},
                        "a8_last_inspection": None,
                        "dream_last_analysis": None,
                        "github_last_search": None,
                        "evolution_count": 0,
                        "successful_evolutions": 0,
                        "failed_evolutions": 0,
                    }
                return data
        except Exception:
            pass
    return {
        "current_master": "Jesse Livermore",
        "total_trades": 0,
        "win_streak": 0,
        "loss_streak": 0,
        "loss_protection_start_ts": None,  # 连败保护启动时间（ISO格式），用于48小时超时重置
        "hold_streak": 0,
        "max_drawdown_pct": 0.0,
        "peak_equity": 60.0,
        "total_pnl_usdt": 0.0,
        "lessons": [],
        "recent_trades": [],
        "pending_strategies": [],
        "master_switch_history": [],
        "active_positions": {},
        "evolution": {
            "adopted_params": {},
            "a8_last_inspection": None,
            "dream_last_analysis": None,
            "github_last_search": None,
            "evolution_count": 0,
            "successful_evolutions": 0,
            "failed_evolutions": 0,
        },
    }


def save_memory(memory: Dict):
    """保存记忆到磁盘"""
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MEMORY_PATH, "w") as f:
        json.dump(memory, f, indent=2, ensure_ascii=False)


# ── Lessons 管理 ─────────────────────────────────────────────────────────

def add_lesson(
    memory: Dict,
    content: str,
    universality: int = 3,
    importance: int = 3,
) -> Dict:
    """
    添加一条新教训，优胜劣汰
    - 评分 = 普适性 × 重要性
    - 超过 MAX_LESSONS 时删除评分最低的
    - 评分 < 10 的自动淘汰
    """
    if not content or len(content.strip()) == 0:
        return memory

    score = universality * importance
    if score < 10:
        return memory

    lesson = {
        "id": len(memory.get("lessons", [])) + 1,
        "content": content.strip(),
        "universality": universality,
        "importance": importance,
        "score": score,
        "created_at": _now_iso(),
    }

    lessons = memory.get("lessons", [])
    lessons.append(lesson)

    # 按评分排序
    lessons.sort(key=lambda x: x["score"], reverse=True)

    # 淘汰低分的
    lessons = [l for l in lessons if l["score"] >= 10]

    # 保留最多 MAX_LESSONS 条
    if len(lessons) > MAX_LESSONS:
        lessons = lessons[:MAX_LESSONS]

    memory["lessons"] = lessons
    return memory


def get_top_lessons(memory: Dict, n: int = 10) -> List[Dict]:
    """获取评分最高的 n 条教训"""
    lessons = memory.get("lessons", [])
    return sorted(lessons, key=lambda x: x["score"], reverse=True)[:n]


# ── 连败保护超时管理 ─────────────────────────────────────────────────────

def check_loss_protection_timeout(memory: Dict) -> Dict:
    """
    检查连败保护是否超过48小时，超时则自动重置 loss_streak。

    设计逻辑：
    - 连败≥LOSS_PROTECTION_TRIGGER 时，loss_protection_start_ts 记录保护启动时间
    - 超过 LOSS_PROTECTION_MAX_HOURS 后自动重置 loss_streak=0
    - 防止系统陷入无限连败保护死循环

    返回更新后的 memory。
    """
    loss_streak = memory.get("loss_streak", 0)
    start_ts = memory.get("loss_protection_start_ts")

    # 连败≥阈值 但没有记录启动时间 → 补记
    if loss_streak >= LOSS_PROTECTION_TRIGGER and not start_ts:
        memory["loss_protection_start_ts"] = _now_iso()
        return memory

    # 连败<阈值 → 清除启动时间
    if loss_streak < LOSS_PROTECTION_TRIGGER:
        memory["loss_protection_start_ts"] = None
        return memory

    # 连败≥阈值 且有启动时间 → 检查是否超时
    if start_ts:
        try:
            start_time = datetime.fromisoformat(start_ts)
            now = datetime.now(timezone.utc)
            elapsed_hours = (now - start_time).total_seconds() / 3600

            if elapsed_hours >= LOSS_PROTECTION_MAX_HOURS:
                print(f"[风控] 连败保护已持续{elapsed_hours:.1f}小时（≥{LOSS_PROTECTION_MAX_HOURS}h），自动重置 loss_streak")
                memory["loss_streak"] = 0
                memory["loss_protection_start_ts"] = None
                memory["win_streak"] = 0
                # 添加一条教训记录超时重置事件
                add_lesson(
                    memory,
                    f"连败保护超时重置：持续{elapsed_hours:.1f}小时后自动解除，需重新评估市场环境",
                    universality=3,
                    importance=3,
                )
        except (ValueError, TypeError):
            # 时间戳格式异常，重新记录
            memory["loss_protection_start_ts"] = _now_iso()

    return memory


def get_loss_protection_countdown(memory: Dict) -> Optional[Dict]:
    """
    获取连败保护倒计时信息。

    返回:
        None — 未处于连败保护状态
        Dict — {
            "start_ts": 保护启动时间,
            "elapsed_hours": 已经过小时数,
            "remaining_hours": 剩余小时数,
            "max_hours": 最大保护小时数,
            "loss_streak": 当前连败次数,
        }
    """
    loss_streak = memory.get("loss_streak", 0)
    start_ts = memory.get("loss_protection_start_ts")

    if loss_streak < LOSS_PROTECTION_TRIGGER or not start_ts:
        return None

    try:
        start_time = datetime.fromisoformat(start_ts)
        now = datetime.now(timezone.utc)
        elapsed_hours = (now - start_time).total_seconds() / 3600
        remaining_hours = max(0, LOSS_PROTECTION_MAX_HOURS - elapsed_hours)

        return {
            "start_ts": start_ts,
            "elapsed_hours": round(elapsed_hours, 1),
            "remaining_hours": round(remaining_hours, 1),
            "max_hours": LOSS_PROTECTION_MAX_HOURS,
            "loss_streak": loss_streak,
        }
    except (ValueError, TypeError):
        return None


# ── 交易记录 ─────────────────────────────────────────────────────────────

def record_trade(
    memory: Dict,
    coin: str,
    action: str,
    entry_price: float,
    exit_price: Optional[float],
    pnl_pct: float,
    confidence: float,
    master: str,
    lesson: str = "",
) -> Dict:
    """记录一笔交易（开仓时 exit_price 和 pnl_pct 可以为 0）"""
    trade = {
        "timestamp": _now_iso(),
        "coin": coin,
        "action": action,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "pnl_pct": pnl_pct,
        "confidence": confidence,
        "master": master,
        "lesson": lesson,
    }

    trades = memory.get("recent_trades", [])
    trades.append(trade)
    if len(trades) > MAX_RECENT_TRADES:
        trades = trades[-MAX_RECENT_TRADES:]
    memory["recent_trades"] = trades

    # 更新统计
    if pnl_pct != 0:
        memory["total_trades"] = memory.get("total_trades", 0) + 1
        if pnl_pct > 0:
            memory["win_streak"] = memory.get("win_streak", 0) + 1
            memory["loss_streak"] = 0
        else:
            memory["loss_streak"] = memory.get("loss_streak", 0) + 1
            memory["win_streak"] = 0

    return memory


def record_closed_trade(
    memory: Dict,
    closed_info: Dict,
    confidence: float = 0.0,
    master: str = "",
) -> Dict:
    """
    记录一笔已平仓的交易（从离场模块返回的 closed_info）
    会更新 recent_trades 以及连胜连败统计
    """
    trade = {
        "timestamp": closed_info.get("exit_ts", _now_iso()),
        "coin": closed_info.get("coin", ""),
        "action": closed_info.get("action", ""),
        "entry_price": closed_info.get("entry_price", 0),
        "exit_price": closed_info.get("exit_price", 0),
        "pnl_pct": closed_info.get("pnl_pct", 0),
        "confidence": confidence,
        "master": master,
        "lesson": f"离场原因:{closed_info.get('exit_reason', 'N/A')}",
        "exit_reason": closed_info.get("exit_reason", ""),
    }

    trades = memory.get("recent_trades", [])
    trades.append(trade)
    if len(trades) > MAX_RECENT_TRADES:
        trades = trades[-MAX_RECENT_TRADES:]
    memory["recent_trades"] = trades

    # 更新统计（只有有实际盈亏才更新）
    pnl = closed_info.get("pnl_pct", 0)
    if pnl != 0:
        memory["total_trades"] = memory.get("total_trades", 0) + 1
        memory["total_pnl_usdt"] = memory.get("total_pnl_usdt", 0) + pnl * closed_info.get("position_size_usdt", 0)
        if pnl > 0:
            memory["win_streak"] = memory.get("win_streak", 0) + 1
            memory["loss_streak"] = 0
            memory["loss_protection_start_ts"] = None  # 连胜 → 清除保护计时
        else:
            memory["loss_streak"] = memory.get("loss_streak", 0) + 1
            memory["win_streak"] = 0
            # 连败≥阈值 → 记录保护启动时间
            if memory["loss_streak"] >= LOSS_PROTECTION_TRIGGER and not memory.get("loss_protection_start_ts"):
                memory["loss_protection_start_ts"] = _now_iso()

    # 注册到 L4
    if _L4_ENABLED and pnl != 0:
        try:
            coin = closed_info.get("coin", "")
            action = closed_info.get("action", "")
            trade_id = f"agent_a_{int(datetime.now(timezone.utc).timestamp())}_{coin}"
            event = TradeEvent(
                event_id=TradeEvent.generate_event_id(),
                system_source="agent_a",
                trade_id=trade_id,
                ts_entry=closed_info.get("entry_ts", _now_iso()),
                ts_exit=closed_info.get("exit_ts", _now_iso()),
                symbol=f"{coin}-USDT-SWAP",
                direction=action.lower(),
                entry_price=closed_info.get("entry_price", 0),
                exit_price=closed_info.get("exit_price", 0),
                position_size=closed_info.get("position_size_usdt", 0),
                pnl=pnl * closed_info.get("position_size_usdt", 0),
                pnl_pct=pnl * 100,
                exit_reason=closed_info.get("exit_reason", ""),
                decision_context={
                    "master": master,
                    "confidence": confidence,
                    "lesson": f"离场原因:{closed_info.get('exit_reason', 'N/A')}",
                },
            )
            registry = UnifiedCaseRegistry()
            case_id, success = registry.register_trade_event(event)
            if success:
                print(f"[Agent A] L4 案例已注册: {case_id}")
        except Exception as e:
            print(f"[Agent A] L4 注册异常: {e}")

    return memory


def update_equity_stats(memory: Dict, current_equity: float) -> Dict:
    """更新权益统计和最大回撤"""
    peak = max(memory.get("peak_equity", current_equity), current_equity)
    memory["peak_equity"] = peak

    if peak > 0:
        drawdown = (peak - current_equity) / peak * 100
        memory["max_drawdown_pct"] = max(memory.get("max_drawdown_pct", 0), drawdown)

    return memory


def update_hold_streak(memory: Dict, action: str) -> Dict:
    """
    更新连续HOLD计数
    - action == "HOLD" 时递增
    - action == "LONG/SHORT" 时重置为0
    """
    if action == "HOLD":
        memory["hold_streak"] = memory.get("hold_streak", 0) + 1
    else:
        memory["hold_streak"] = 0
    return memory


# ── 大师风格切换 ─────────────────────────────────────────────────────────

def maybe_switch_master(memory: Dict, market_regime: str = "RANGE") -> Dict:
    """
    根据交易表现和市场环境，评估是否切换大师风格
    切换规则：
      - 连亏3笔且震荡市 → 切换（震荡市趋势策略易反复止损）
      - 累计回撤≥15% → 强制切换
      - 连败≥5笔 → 必须切换
      - 连续15轮HOLD → 强制切换（打破过度保守死循环）

    注意：market_regime 现由 detect_market_regime() 基于市场统计输出，
    规则兜底/保守循环打破路径不再硬编码 TREND_UP/DOWN，故 RANGE 分支
    可真正生效（此前 regime 永为趋势，该分支永不触发）。
    """
    current = memory.get("current_master", "Jesse Livermore")
    loss_streak = memory.get("loss_streak", 0)
    hold_streak = memory.get("hold_streak", 0)
    max_dd = memory.get("max_drawdown_pct", 0)
    switch_reason = ""

    # 强制切换条件
    if max_dd >= 15:
        switch_reason = f"最大回撤{max_dd:.1f}%≥15%，强制切换"
    elif loss_streak >= 3 and "RANGE" in market_regime.upper():
        switch_reason = f"连败{loss_streak}次且震荡市，切换风格"
    elif loss_streak >= 5:
        switch_reason = f"连败{loss_streak}次，必须切换"
    elif hold_streak >= 15:
        switch_reason = f"连续{hold_streak}轮HOLD，过度保守，强制切换风格"

    if not switch_reason:
        return memory

    # 选择新大师（轮换）
    try:
        idx = MASTER_LIST.index(current)
        new_master = MASTER_LIST[(idx + 1) % len(MASTER_LIST)]
    except ValueError:
        new_master = "Paul Tudor Jones"

    # 记录切换历史
    history = memory.get("master_switch_history", [])
    history.append({
        "timestamp": _now_iso(),
        "old_master": current,
        "new_master": new_master,
        "reason": switch_reason,
        "loss_streak": loss_streak,
        "max_drawdown_pct": max_dd,
    })
    memory["master_switch_history"] = history[-10:]
    memory["current_master"] = new_master

    # 添加切换教训
    add_lesson(
        memory,
        f"{current}风格在当前市场不适用，已切换为{new_master}",
        universality=2,
        importance=4,
    )

    return memory


# ── 待验证策略（向外学习）─────────────────────────────────────────────────

def add_pending_strategy(memory: Dict, strategy: str, source: str = "external") -> Dict:
    """添加一个待验证策略到待验证池"""
    pending = memory.get("pending_strategies", [])
    if len(pending) >= MAX_PENDING_STRATEGIES:
        pending = pending[1:]  # 去掉最旧的

    pending.append({
        "strategy": strategy,
        "source": source,
        "added_at": _now_iso(),
        "verify_count": 0,
        "correct_count": 0,
    })
    memory["pending_strategies"] = pending
    return memory


def verify_strategy(memory: Dict, strategy_idx: int, correct: bool) -> Dict:
    """验证一次待验证策略，正确2/3则升级为Lesson"""
    pending = memory.get("pending_strategies", [])
    if strategy_idx >= len(pending):
        return memory

    item = pending[strategy_idx]
    item["verify_count"] += 1
    if correct:
        item["correct_count"] += 1

    # 验证通过（≥3次验证且正确率≥2/3）
    if item["verify_count"] >= 3 and item["correct_count"] / item["verify_count"] >= 0.66:
        add_lesson(
            memory,
            item["strategy"],
            universality=3,
            importance=4,
        )
        pending.pop(strategy_idx)

    memory["pending_strategies"] = pending
    return memory


# ── 进化系统记忆 ──────────────────────────────────────────────────────────

def get_evolution_params(memory: Dict) -> Dict:
    """获取已采纳的进化参数"""
    return memory.get("evolution", {}).get("adopted_params", {})


def update_evolution_params(memory: Dict, params: Dict) -> Dict:
    """更新进化参数"""
    if "evolution" not in memory:
        memory["evolution"] = {}
    if "adopted_params" not in memory["evolution"]:
        memory["evolution"]["adopted_params"] = {}
    memory["evolution"]["adopted_params"].update(params)
    return memory


def record_evolution_result(memory: Dict, success: bool) -> Dict:
    """记录一次进化结果"""
    evo = memory.get("evolution", {})
    evo["evolution_count"] = evo.get("evolution_count", 0) + 1
    if success:
        evo["successful_evolutions"] = evo.get("successful_evolutions", 0) + 1
    else:
        evo["failed_evolutions"] = evo.get("failed_evolutions", 0) + 1
    memory["evolution"] = evo
    return memory


def set_evolution_timestamp(memory: Dict, key: str) -> Dict:
    """设置进化检查时间戳"""
    if "evolution" not in memory:
        memory["evolution"] = {}
    memory["evolution"][key] = _now_iso()
    return memory


# ── 快速测试 ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Agent A 记忆系统测试 ===")
    mem = load_memory()
    print(f"当前大师: {mem['current_master']}")
    print(f"总交易数: {mem['total_trades']}")
    print(f"连胜/连败: {mem['win_streak']}/{mem['loss_streak']}")
    print(f"Lessons 数量: {len(mem['lessons'])}")
    print(f"近期交易数: {len(mem['recent_trades'])}")

    # 测试添加 lesson
    mem = add_lesson(mem, "RSI超买时不追多", universality=4, importance=5)
    print(f"\n添加 lesson 后: {len(mem['lessons'])} 条")
    print(f"Top 1: {mem['lessons'][0]['content']} (score={mem['lessons'][0]['score']})")

    save_memory(mem)
    print(f"\n已保存到: {MEMORY_PATH}")
