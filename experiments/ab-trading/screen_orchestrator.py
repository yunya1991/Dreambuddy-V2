#!/usr/bin/env python3
"""
三屏马丁自主调度编排器 (Screen Orchestrator)
参考 orchestrator.py 的模式，负责三屏交易的自主调度与事件驱动

触发逻辑：
1. 常规心跳：每4小时一次
2. 市场异常波动：BTC 1h 涨跌幅 > 3%
3. 研报更新：A6情报有新内容时触发
4. 重要事件：经济数据/政策事件窗口
5. 自主申请：执行器检测到关键价位时主动申请
"""
import os, json, time, subprocess, warnings
from datetime import datetime, timezone, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / "config" / ".env")
except Exception:
    pass

BASE_DIR = Path(__file__).parent
STATE_FILE = BASE_DIR / "data" / "screen_orchestrator_state.json"
SCHED_FILE = BASE_DIR / "data" / "screen_self_schedule.json"
LOG_FILE = BASE_DIR / "logs" / "screen_orchestrator.log"

NORMAL_INTERVAL_H = 1      # 放宽验证阶段：1H心跳
VOLATILITY_PCT = 2.0       # 降低波动阈值，更易触发
EVENT_WINDOW_H = 0.5       # 缩短事件窗口
INTEL_CHECK_INTERVAL_H = 1 # 研报检查间隔缩短

HOME_BIN = "/opt/homebrew/bin"
os.environ["PATH"] = HOME_BIN + ":" + os.environ.get("PATH", "")


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
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
    return {
        "last_run_ts": 0,
        "run_count": 0,
        "last_trigger_reason": "",
        "last_volatility_check": 0,
        "last_intel_check": 0,
        "last_intel_date": "",
        "event_cache": [],
        "last_event_check_ts": 0,
    }


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ── 自主调度申请 ──────────────────────────────────────────────────────────

def load_schedule_requests() -> list:
    if not SCHED_FILE.exists():
        return []
    try:
        with open(SCHED_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def clear_expired_requests() -> list:
    reqs = load_schedule_requests()
    now = time.time()
    valid = [r for r in reqs if r.get("expires_ts", 0) > now]
    SCHED_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SCHED_FILE, "w") as f:
        json.dump(valid, f, indent=2, ensure_ascii=False)
    return valid


def request_early_run(reason: str, run_at_ts: float, priority: str = "normal"):
    reqs = load_schedule_requests()
    reqs.append({
        "reason": reason,
        "run_at_ts": run_at_ts,
        "expires_ts": run_at_ts + 3600,
        "priority": priority,
        "created_ts": time.time(),
    })
    SCHED_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SCHED_FILE, "w") as f:
        json.dump(reqs, f, indent=2, ensure_ascii=False)
    log(f"📅 调度申请已写入: {reason} @ {datetime.fromtimestamp(run_at_ts).strftime('%H:%M')}")


# ── 市场波动检测（零 Token） ──────────────────────────────────────────────

def check_market_volatility() -> dict:
    """检测 BTC 1h 波动（OKX 行情）"""
    try:
        import subprocess
        r = subprocess.run(
            ["okx", "market", "ticker", "BTC-USDT-SWAP", "--json"],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "NO_UPDATE_CHECK": "1", "PATH": os.environ["PATH"]}
        )
        stdout = "\n".join(l for l in r.stdout.split("\n") if "Update available" not in l and "Run: npm" not in l).strip()
        if r.returncode != 0:
            return {"change_pct": 0, "direction": "N/A"}
        if not stdout.startswith("["):
            return {"change_pct": 0, "direction": "N/A"}
        data = json.loads(stdout)
        if not data or not isinstance(data, list) or not data[0]:
            return {"change_pct": 0, "direction": "N/A"}
        t = data[0]
        last = float(t.get("last", 0))
        open24h = float(t.get("open24h", 0))
        if open24h == 0:
            return {"change_pct": 0, "direction": "N/A"}
        change_pct = abs((last - open24h) / open24h * 100)
        direction = "UP" if last > open24h else "DOWN"
        return {"change_pct": round(change_pct, 2), "direction": direction, "last": last, "open24h": open24h}
    except Exception as e:
        return {"change_pct": 0, "direction": "ERROR", "error": str(e)}


# ── 研报更新检测 ──────────────────────────────────────────────────────────

def check_new_intel() -> bool:
    """检测 A6 情报是否有新内容"""
    try:
        from report_loader import load_a6_intel
        intel = load_a6_intel()
        state = load_state()
        if intel and not intel.get("error"):
            intel_date = intel.get("date", "")
            if intel_date and intel_date != state.get("last_intel_date", ""):
                state["last_intel_date"] = intel_date
                save_state(state)
                return True
        return False
    except Exception:
        return False


# ── 重要事件检测 ──────────────────────────────────────────────────────────

def check_upcoming_events() -> list:
    """检查未来24h重要事件（零Token，本地已知事件 + 研报提示）"""
    events = []

    try:
        from report_loader import load_a6_intel
        intel = load_a6_intel()
        if intel and not intel.get("error"):
            p0 = intel.get("p0_alerts", 0)
            p1 = intel.get("p1_alerts", 0)
            if p0 > 0:
                events.append({"name": f"P0级告警({p0}条)", "delta_h": 0, "source": "A6"})
            if p1 >= 3:
                events.append({"name": f"密集P1告警({p1}条)", "delta_h": 0, "source": "A6"})
            rec = intel.get("recommendation", "")
            if "警惕" in rec or "风险" in rec or "谨慎" in rec:
                events.append({"name": "A6风险提示", "delta_h": 0, "source": "A6"})
    except Exception:
        pass

    return events


# ── 触发决策 ──────────────────────────────────────────────────────────────

def should_trigger(state: dict) -> tuple:
    """
    综合判断是否需要触发本轮执行
    返回 (是否触发, 原因)
    """
    now_ts = time.time()
    elapsed_h = (now_ts - state.get("last_run_ts", 0)) / 3600

    # 1. 自主调度申请（最高优先级）
    reqs = clear_expired_requests()
    pending = [r for r in reqs if r.get("run_at_ts", 0) <= now_ts]
    if pending:
        best = sorted(pending, key=lambda x: x.get("priority") == "urgent", reverse=True)[0]
        return True, f"🤖 自主申请: {best['reason']}"

    # 2. 市场极端波动（零Token）
    vol = check_market_volatility()
    if vol.get("change_pct", 0) >= VOLATILITY_PCT:
        return True, f"⚡ 波动触发: BTC 1h {vol['direction']} {vol['change_pct']}%"

    # 3. 重要事件/风险告警
    events = check_upcoming_events()
    urgent_events = [e for e in events if e.get("source") == "A6" and "P0" in e.get("name", "")]
    if urgent_events and elapsed_h >= 0.5:
        return True, f"🚨 风险事件: {urgent_events[0]['name']}"

    # 4. 研报更新触发（A6有新内容）
    if elapsed_h >= 1.5:
        new_intel = check_new_intel()
        if new_intel:
            return True, "📰 A6情报更新"

    # 5. 常规4H心跳（兜底）
    if elapsed_h >= NORMAL_INTERVAL_H:
        return True, f"⏰ 常规心跳: 已过 {elapsed_h:.1f}H"

    return False, f"⏸ 等待中 (距上次 {elapsed_h:.1f}H / {NORMAL_INTERVAL_H}H)"


# ── 执行三屏交易 ──────────────────────────────────────────────────────────

def run_screen_trade(reason: str):
    """执行三屏马丁巡检"""
    log(f"🚀 触发三屏马丁执行 — {reason}")
    script_path = BASE_DIR / "screen_executor.py"
    try:
        result = subprocess.run(
            ["python3", str(script_path), "run", reason],
            cwd=str(BASE_DIR),
            capture_output=True, text=True, timeout=180,
            env={**os.environ, "PYTHONPATH": str(BASE_DIR)}
        )
        key_lines = [l for l in result.stdout.split("\n")
                     if any(kw in l for kw in ["决策", "开仓", "加仓", "止盈", "ACTION", "INFO", "ERROR", "SUCCESS"])
                     and "Warning" not in l and "Update" not in l]
        for line in key_lines[:10]:
            log(f"  {line.strip()}")
        if result.returncode != 0:
            log(f"  ❌ 退出码 {result.returncode}: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        log(f"  ⚠️ 超时: screen_executor.py")
    except Exception as e:
        log(f"  ❌ 执行失败: {e}")


# ── 主函数 ────────────────────────────────────────────────────────────────

def main():
    state = load_state()

    # 模式检测（每轮都检测，必要时切换）
    try:
        from mode_manager import check_and_switch_mode
        mode_result = check_and_switch_mode()
        if mode_result.get("switched"):
            log(f"🔄 模式切换: {mode_result['old_mode']} → {mode_result['new_mode']} ({mode_result['reason']})")
    except Exception as e:
        log(f"模式检测异常: {e}")

    trigger, reason = should_trigger(state)

    if trigger:
        run_screen_trade(reason)
        state["last_run_ts"] = time.time()
        state["run_count"] = state.get("run_count", 0) + 1
        state["last_trigger_reason"] = reason
        state["last_volatility_check"] = time.time()
        save_state(state)
    else:
        log(reason)


def get_orchestrator_state() -> dict:
    state = load_state()
    now_ts = time.time()
    elapsed_h = (now_ts - state.get("last_run_ts", 0)) / 3600
    vol = check_market_volatility()

    # 模式状态
    mode_state = {}
    try:
        from mode_manager import get_current_state
        mode_state = get_current_state()
    except Exception:
        pass

    return {
        **state,
        "elapsed_h": round(elapsed_h, 1),
        "next_run_h": round(max(0, NORMAL_INTERVAL_H - elapsed_h), 1),
        "volatility": vol,
        "normal_interval_h": NORMAL_INTERVAL_H,
        "volatility_threshold": VOLATILITY_PCT,
        "mode": mode_state,
    }


if __name__ == "__main__":
    main()
