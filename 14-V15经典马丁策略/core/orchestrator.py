#!/usr/bin/env python3
"""
自主调度编排器 — Orchestrator
每15分钟被 cron 调用，决定是否触发 Agent A / B

自主性逻辑：
1. 常规心跳：距上次运行 > 1H 自动触发
2. 事件驱动：重要经济事件前后 1H 内主动触发
3. Agent 自主申请：agents 写入 self_schedule.json 申请提前运行
4. 紧急信号：市场波动超阈值时触发（BTC 1H变动 > 3%）
"""
import os, json, time, subprocess, requests, warnings
from datetime import datetime, timezone, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")
BASE_DIR  = Path(__file__).parent.parent
ENV_FILE  = BASE_DIR / "config" / ".env.v15"
SCHED_FILE = BASE_DIR / "data" / "self_schedule.json"
STATE_FILE = BASE_DIR / "data" / "orchestrator_state.json"
LOG_FILE   = BASE_DIR / "logs" / "orchestrator.log"

NORMAL_INTERVAL_H = 1          # 常规间隔（放宽验证阶段：1H）
EVENT_WINDOW_H    = 0.5        # 重要事件前后触发窗口（放宽为30分钟）
VOLATILITY_PCT    = 2.0        # BTC 1H 波动触发阈值（降低到2%更易触发）

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


# ── 执行 agents ───────────────────────────────────────────────────────────

def run_agents(reason: str):
    log(f"🚀 触发执行 — {reason}")
    script_path = BASE_DIR / "core" / "v15_trader.py"
    if not script_path.exists():
        log(f"⚠️ 脚本不存在: {script_path}")
        return
    try:
        result = subprocess.run(
            ["python3", str(script_path)],
            cwd=str(BASE_DIR),
            capture_output=True, text=True, timeout=120
        )
        key_lines = [l for l in result.stdout.split("\n")
                     if any(kw in l for kw in ["信号触发", "开仓", "加仓", "止盈", "止损", "胜率", "权益", "错误"])
                     and "Warning" not in l]
        for line in key_lines[:4]:
            log(f"  {line.strip()}")
        if result.returncode != 0:
            log(f"  ❌ 退出码 {result.returncode}: {result.stderr[:100]}")
    except subprocess.TimeoutExpired:
        log(f"  ⚠️ 超时: v15_trader.py")
    except Exception as e:
        log(f"  ❌ 执行失败: {e}")


# ── 主函数 ───────────────────────────────────────────────────────────────

def main():
    state = load_state()
    trigger, reason = should_trigger(state)

    if trigger:
        run_agents(reason)
        state["last_run_ts"]       = time.time()
        state["run_count"]         = state.get("run_count", 0) + 1
        state["last_trigger_reason"] = reason
        save_state(state)

        # 每日一次：用 Tavily 查未来事件，并让 agents 知晓
        fetch_upcoming_events_tavily()
    else:
        log(reason)


if __name__ == "__main__":
    main()
