#!/usr/bin/env python3
"""
AB-Trading 记忆与SKILL驱动调度器 — Orchestrator
每4小时执行一次，调用 Agent A/B 的记忆模块与 SKILL 工作流进行交易决策

自主性逻辑：
1. 常规心跳：距上次运行 > 4H 自动触发
2. 事件驱动：重要经济事件前后 1H 内主动触发
3. Agent 自主申请：agents 写入 self_schedule.json 申请提前运行
4. 紧急信号：市场波动超阈值时触发（BTC 1H变动 > 3%）

记忆与SKILL集成：
- 执行前加载双方记忆（Agent A/B），生成记忆摘要供调度决策参考
- 加载 SKILL Registry 状态，检查 SKILL 可用性
- 执行后更新双方记忆（记录调度决策、触发原因）
"""
import os, sys, json, time, subprocess, requests, warnings
from datetime import datetime, timezone, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")
BASE_DIR  = Path(__file__).parent
ENV_FILE  = BASE_DIR / "config" / ".env"
SCHED_FILE = BASE_DIR / "data" / "self_schedule.json"
STATE_FILE = BASE_DIR / "data" / "orchestrator_state.json"
LOG_FILE   = BASE_DIR / "logs" / "orchestrator.log"

NORMAL_INTERVAL_H = 4          # 常规间隔：4H
EVENT_WINDOW_H    = 0.5        # 重要事件前后触发窗口（30分钟）
VOLATILITY_PCT    = 2.0        # BTC 1H 波动触发阈值

TAVILY_KEY = None
try:
    from dotenv import load_dotenv
    load_dotenv(ENV_FILE)
    TAVILY_KEY = os.environ.get("TAVILY_API_KEY")
except Exception:
    pass


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# ── 状态管理 ──────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_run_ts": 0, "run_count": 0, "last_trigger_reason": ""}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ── Agent 自主调度请求 ────────────────────────────────────────────────────

def load_schedule_requests() -> list:
    """读取 agents 写入的自主调度申请"""
    if not SCHED_FILE.exists():
        return []
    try:
        with open(SCHED_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def clear_expired_requests():
    """清理过期的调度申请"""
    reqs = load_schedule_requests()
    now = time.time()
    valid = [r for r in reqs if r.get("expires_ts", 0) > now]
    SCHED_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SCHED_FILE, "w") as f:
        json.dump(valid, f, indent=2)
    return valid


def request_early_run(reason: str, run_at_ts: float, priority: str = "normal"):
    """供 agents 调用：申请在指定时间提前触发"""
    reqs = load_schedule_requests()
    reqs.append({
        "reason":     reason,
        "run_at_ts":  run_at_ts,
        "expires_ts": run_at_ts + 3600,  # 1H 后过期
        "priority":   priority,
        "created_ts": time.time(),
    })
    SCHED_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SCHED_FILE, "w") as f:
        json.dump(reqs, f, indent=2)
    log(f"📅 调度申请已写入: {reason} @ {datetime.fromtimestamp(run_at_ts).strftime('%H:%M')}")


# ── 重要经济事件检测 ─────────────────────────────────────────────────────

KNOWN_EVENTS = [
    # 格式：(月, 日, 时, 分, 事件名)  UTC 时间
    # 每月更新一次（由 agents 通过 Tavily 自动更新）
]

def check_upcoming_events_local() -> list:
    """本地已知事件检测（零Token）"""
    now = datetime.now(timezone.utc)
    upcoming = []
    for (month, day, hour, minute, name) in KNOWN_EVENTS:
        event_dt = now.replace(month=month, day=day, hour=hour, minute=minute, second=0)
        delta = (event_dt - now).total_seconds() / 3600
        if -EVENT_WINDOW_H <= delta <= EVENT_WINDOW_H:
            upcoming.append({"name": name, "delta_h": round(delta, 2)})
    return upcoming


def fetch_upcoming_events_tavily() -> list:
    """用 Tavily 查询未来24H重要经济事件（有Token成本，每日最多1次）"""
    if not TAVILY_KEY:
        return []
    state = load_state()
    last_event_check = state.get("last_event_check_ts", 0)
    if time.time() - last_event_check < 20 * 3600:  # 20H 内不重复查
        return state.get("cached_events", [])
    try:
        s = requests.Session(); s.trust_env = False
        r = s.post("https://api.tavily.com/search", json={
            "api_key": TAVILY_KEY,
            "query":   "US economic events today CPI NFP FOMC Fed meeting crypto market impact",
            "search_depth": "basic",
            "max_results": 5,
        }, timeout=10)
        results = r.json().get("results", [])
        events = []
        keywords = ["CPI", "NFP", "FOMC", "Fed", "GDP", "PCE", "inflation", "employment", "rate decision"]
        for res in results:
            title = res.get("title", "")
            if any(k.lower() in title.lower() for k in keywords):
                events.append({"name": title[:60], "source": "tavily", "delta_h": 0})
        # 缓存结果
        state["last_event_check_ts"] = time.time()
        state["cached_events"] = events
        save_state(state)
        log(f"📰 Tavily 事件检测: 发现 {len(events)} 个重要事件")
        return events
    except Exception as e:
        log(f"⚠️ Tavily 事件查询失败: {e}")
        return []


# ── 市场波动检测 ─────────────────────────────────────────────────────────

def check_market_volatility() -> dict:
    """检测 BTC 1H 波动（零Token，直接调 Hyperliquid）"""
    try:
        s = requests.Session(); s.trust_env = False
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - 3600000  # 1H ago
        r = s.post("https://api.hyperliquid.xyz/info", json={
            "type": "candleSnapshot",
            "req": {"coin": "BTC", "interval": "1h", "startTime": start_ms, "endTime": now_ms}
        }, timeout=8)
        candles = r.json()
        if candles and len(candles) >= 1:
            last = candles[-1]
            open_px  = float(last["o"])
            close_px = float(last["c"])
            change_pct = abs((close_px - open_px) / open_px * 100)
            return {"change_pct": round(change_pct, 2), "direction": "UP" if close_px > open_px else "DOWN"}
    except Exception:
        pass
    return {"change_pct": 0, "direction": "NEUTRAL"}


# ── 触发决策 ─────────────────────────────────────────────────────────────

def should_trigger(state: dict) -> tuple[bool, str]:
    """
    综合判断是否需要触发本轮执行
    返回 (是否触发, 原因)
    """
    now_ts = time.time()
    elapsed_h = (now_ts - state.get("last_run_ts", 0)) / 3600

    # 1. Agent 自主申请（最高优先级）
    reqs = clear_expired_requests()
    pending = [r for r in reqs if r.get("run_at_ts", 0) <= now_ts]
    if pending:
        best = sorted(pending, key=lambda x: x.get("priority") == "urgent", reverse=True)[0]
        return True, f"🤖 Agent自主申请: {best['reason']}"

    # 2. 市场极端波动（零Token检测）
    vol = check_market_volatility()
    if vol["change_pct"] >= VOLATILITY_PCT:
        return True, f"⚡ 市场波动触发: BTC 1H {vol['direction']} {vol['change_pct']}%"

    # 3. 本地已知重要事件
    local_events = check_upcoming_events_local()
    if local_events:
        ev = local_events[0]
        return True, f"📅 重要事件窗口: {ev['name']} (T{ev['delta_h']:+.1f}H)"

    # 4. 常规4H心跳（兜底）
    if elapsed_h >= NORMAL_INTERVAL_H:
        return True, f"⏰ 常规心跳: 已过 {elapsed_h:.1f}H"

    return False, f"⏸ 等待中 (距上次 {elapsed_h:.1f}H / {NORMAL_INTERVAL_H}H)"


# ── 记忆与SKILL集成 ─────────────────────────────────────────────────────

def load_agent_memories() -> dict:
    """
    加载 Agent A/B 记忆模块，生成调度决策参考摘要
    返回: {agent_a: {...}, agent_b: {...}, summary: str}
    """
    memories = {"agent_a": {}, "agent_b": {}, "summary": ""}

    # Agent A 记忆
    try:
        sys.path.insert(0, str(BASE_DIR))
        from core.agent_a_memory import load_memory as load_a_memory
        a_mem = load_a_memory()
        memories["agent_a"] = {
            "current_master": a_mem.get("current_master", "N/A"),
            "total_trades": a_mem.get("total_trades", 0),
            "win_streak": a_mem.get("win_streak", 0),
            "loss_streak": a_mem.get("loss_streak", 0),
            "hold_streak": a_mem.get("hold_streak", 0),
            "max_drawdown_pct": round(a_mem.get("max_drawdown_pct", 0), 1),
            "active_positions": list(a_mem.get("active_positions", {}).keys()),
            "lessons_count": len(a_mem.get("lessons", [])),
        }
    except Exception as e:
        log(f"⚠️ Agent A 记忆加载失败: {e}")

    # Agent B 记忆
    b_mem_path = BASE_DIR / "data" / "agent_b_memory.json"
    try:
        if b_mem_path.exists():
            with open(b_mem_path) as f:
                b_mem = json.load(f)
            memories["agent_b"] = {
                "total_cycles": b_mem.get("total_cycles", 0),
                "win_streaks": b_mem.get("win_streaks", 0),
                "loss_streaks": b_mem.get("loss_streaks", 0),
                "last_regime": b_mem.get("last_regime", "N/A"),
                "active_positions": list(b_mem.get("active_positions", {}).keys()),
                "lessons_count": len(b_mem.get("lessons", [])),
            }
    except Exception as e:
        log(f"⚠️ Agent B 记忆加载失败: {e}")

    # 生成摘要
    a = memories["agent_a"]
    b = memories["agent_b"]
    summary_parts = []
    if a:
        summary_parts.append(
            f"A[大师:{a.get('current_master')} 交易:{a.get('total_trades')} "
            f"连胜:{a.get('win_streak')}/连败:{a.get('loss_streak')} "
            f"回撤:{a.get('max_drawdown_pct')}% 持仓:{a.get('active_positions',[])}]"
        )
    if b:
        summary_parts.append(
            f"B[周期:{b.get('total_cycles')} "
            f"连胜:{b.get('win_streaks')}/连败:{b.get('loss_streaks')} "
            f"Regime:{b.get('last_regime')} 持仓:{b.get('active_positions',[])}]"
        )
    memories["summary"] = " | ".join(summary_parts) if summary_parts else "无记忆"
    return memories


def check_skill_registry() -> dict:
    """
    检查 SKILL Registry 状态，确认 A/C/F 链 SKILL 可用性
    返回: {available: [str], unavailable: [str], total: int}
    """
    try:
        sys.path.insert(0, str(BASE_DIR))
        from core.modules.skill_loader import SkillLoader
        loader = SkillLoader(str(BASE_DIR.parent.parent))
        result = {"available": [], "unavailable": [], "total": 0}
        for skill_name in SkillLoader.SKILL_PATHS:
            if loader.is_skill_available(skill_name):
                result["available"].append(skill_name)
            else:
                result["unavailable"].append(skill_name)
        result["total"] = len(SkillLoader.SKILL_PATHS)
        return result
    except Exception as e:
        log(f"⚠️ SKILL Registry 检查失败: {e}")
        return {"available": [], "unavailable": [], "total": 0, "error": str(e)}


def update_orchestrator_memory(reason: str, memories: dict, skill_status: dict):
    """
    更新调度器状态记忆：记录本轮调度决策、触发原因、记忆摘要
    写入 orchestrator_state.json
    """
    state = load_state()
    state["last_trigger_reason"] = reason
    state["last_memory_summary"] = memories.get("summary", "")
    state["last_skill_available"] = skill_status.get("available", [])
    state["last_skill_unavailable"] = skill_status.get("unavailable", [])
    save_state(state)


# ── 执行 agents ───────────────────────────────────────────────────────────

def run_agents(reason: str, memories: dict = None, skill_status: dict = None):
    """
    执行 Agent A/B，传递记忆上下文和 SKILL 状态
    Agent A: LLM 驱动 + 记忆系统 + SKILL 框架
    Agent B: BAC 架构 + 交易记忆闭环 + SKILL 工作流
    """
    log(f"🚀 触发执行 — {reason}")
    if memories:
        log(f"🧠 记忆摘要: {memories.get('summary', 'N/A')}")
    if skill_status:
        avail = skill_status.get("available", [])
        log(f"📋 SKILL状态: {len(avail)}/{skill_status.get('total',0)} 可用 {avail}")

    for agent_script in ["agents/agent_a_runner.py", "agents/agent_b_runner.py"]:
        script_path = BASE_DIR / agent_script
        if not script_path.exists():
            log(f"⚠️ 脚本不存在: {script_path}")
            continue
        agent_label = "A" if "agent_a" in agent_script else "B"
        try:
            result = subprocess.run(
                ["python3", str(script_path)],
                cwd=str(BASE_DIR),
                capture_output=True, text=True, timeout=180
            )
            # 提取关键输出行
            key_lines = [l for l in result.stdout.split("\n")
                         if any(kw in l for kw in ["决策", "执行", "拦截", "通过", "权益", "USDC", "错误",
                                                     "记忆", "SKILL", "模式", "离场", "经典"])
                         and "Warning" not in l]
            for line in key_lines[:6]:
                log(f"  [{agent_label}] {line.strip()}")
            if result.returncode != 0:
                log(f"  ❌ [{agent_label}] 退出码 {result.returncode}: {result.stderr[:100]}")
        except subprocess.TimeoutExpired:
            log(f"  ⚠️ [{agent_label}] 超时: {agent_script}")
        except Exception as e:
            log(f"  ❌ [{agent_label}] 执行失败: {e}")


# ── 主函数 ───────────────────────────────────────────────────────────────

def main():
    state = load_state()
    trigger, reason = should_trigger(state)

    if trigger:
        # 加载双方记忆和 SKILL 状态
        memories = load_agent_memories()
        skill_status = check_skill_registry()

        # 执行 Agent A/B（记忆+SKILL驱动）
        run_agents(reason, memories=memories, skill_status=skill_status)

        # 更新调度器状态
        state["last_run_ts"]       = time.time()
        state["run_count"]         = state.get("run_count", 0) + 1
        state["last_trigger_reason"] = reason
        save_state(state)

        # 更新调度器记忆（记录本轮决策上下文）
        update_orchestrator_memory(reason, memories, skill_status)

        # 每日一次：用 Tavily 查未来事件，并让 agents 知晓
        fetch_upcoming_events_tavily()
    else:
        log(reason)


if __name__ == "__main__":
    main()
