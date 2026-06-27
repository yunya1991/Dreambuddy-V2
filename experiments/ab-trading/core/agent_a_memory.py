#!/usr/bin/env python3
"""
Agent A 记忆系统 — 跨 session 持久化记忆
包含：Lessons 管理、交易记录、大师切换、连胜连败追踪
"""
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional

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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_memory() -> Dict:
    """加载记忆，不存在则初始化"""
    if MEMORY_PATH.exists():
        try:
            with open(MEMORY_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "current_master": "Jesse Livermore",
        "total_trades": 0,
        "win_streak": 0,
        "loss_streak": 0,
        "max_drawdown_pct": 0.0,
        "peak_equity": 60.0,
        "total_pnl_usdt": 0.0,
        "lessons": [],
        "recent_trades": [],
        "pending_strategies": [],
        "master_switch_history": [],
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


def update_equity_stats(memory: Dict, current_equity: float) -> Dict:
    """更新权益统计和最大回撤"""
    peak = max(memory.get("peak_equity", current_equity), current_equity)
    memory["peak_equity"] = peak

    if peak > 0:
        drawdown = (peak - current_equity) / peak * 100
        memory["max_drawdown_pct"] = max(memory.get("max_drawdown_pct", 0), drawdown)

    return memory


# ── 大师风格切换 ─────────────────────────────────────────────────────────

def maybe_switch_master(memory: Dict, market_regime: str = "RANGE") -> Dict:
    """
    根据交易表现和市场环境，评估是否切换大师风格
    切换规则：
      - 连亏3笔 → 大概率切换
      - 累计回撤≥15% → 强制切换
      - 错过10%以上单边行情 → 切换到趋势追踪型
    """
    current = memory.get("current_master", "Jesse Livermore")
    loss_streak = memory.get("loss_streak", 0)
    max_dd = memory.get("max_drawdown_pct", 0)
    switch_reason = ""

    # 强制切换条件
    if max_dd >= 15:
        switch_reason = f"最大回撤{max_dd:.1f}%≥15%，强制切换"
    elif loss_streak >= 3 and "RANGE" in market_regime.upper():
        switch_reason = f"连败{loss_streak}次且震荡市，切换风格"
    elif loss_streak >= 5:
        switch_reason = f"连败{loss_streak}次，必须切换"

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
