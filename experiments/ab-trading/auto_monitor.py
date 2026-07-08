#!/usr/bin/env python3
"""
交易系统自动化监控与复盘任务
功能：
1. 监控 Agent A 和 Agent B 是否正常运行（检查最近日志时间）
2. 发现未正常运行时自动触发执行
   - Agent A：按记忆工作流执行（agent_a_runner.py）
   - Agent B：按完整流程执行（agent_b_runner.py）
3. 复盘蒸馏学习：分析交易日志，提取教训，更新记忆
4. 在远端 PR 下创建评论

用法：
  python3 auto_monitor.py
  python3 auto_monitor.py --distill-only    # 仅执行复盘和PR评论
  python3 auto_monitor.py --check-only      # 仅检查状态不触发执行
"""
import os, sys, json, subprocess, time, argparse, warnings
from datetime import datetime, timezone, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

# ── 配置 ───────────────────────────────────────────────────────────────────
AGENT_A_LOG_DIR = BASE_DIR / "logs" / "agent_a"
AGENT_B_LOG_DIR = BASE_DIR / "logs" / "agent_b"
MAX_IDLE_MINUTES = 240   # 超过4小时认为未正常运行
GH_TOKEN = os.environ.get("GH_TOKEN", os.environ.get("GITHUB_TOKEN", ""))
PR_NUMBER = "52"
REPO = "yunya1991/Dreambuddy-V2"

# ── 工具函数 ────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)

def _fmt_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")

def get_latest_log_ts(log_dir: Path) -> datetime:
    """获取最近日志文件的时间戳"""
    if not log_dir.exists():
        return datetime.min.replace(tzinfo=timezone.utc)
    logs = sorted(log_dir.glob("*.json"), reverse=True)
    if not logs:
        return datetime.min.replace(tzinfo=timezone.utc)
    # 从文件名解析时间
    fname = logs[0].stem
    try:
        # 格式如 20260707_040933 或 20260706-1906
        if "_" in fname:
            dt = datetime.strptime(fname, "%Y%m%d_%H%M%S")
        elif "-" in fname:
            dt = datetime.strptime(fname, "%Y%m%d-%H%M")
        else:
            # 尝试从文件修改时间获取
            mtime = logs[0].stat().st_mtime
            dt = datetime.fromtimestamp(mtime)
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        mtime = logs[0].stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc)

def is_agent_running(agent_name: str, log_dir: Path) -> tuple[bool, str]:
    """检查 Agent 是否正常运行，返回 (是否正常, 状态说明)"""
    latest_ts = get_latest_log_ts(log_dir)
    now = _now()
    idle_minutes = (now - latest_ts).total_seconds() / 60

    if latest_ts == datetime.min.replace(tzinfo=timezone.utc):
        return False, f"从未运行过"

    if idle_minutes > MAX_IDLE_MINUTES:
        return False, f"已空闲 {idle_minutes:.0f} 分钟（阈值 {MAX_IDLE_MINUTES} 分钟）"

    return True, f"最近运行 {_fmt_ts(latest_ts)}，空闲 {idle_minutes:.0f} 分钟"

# ── 执行 Agent ──────────────────────────────────────────────────────────────

def run_agent_a():
    """按记忆工作流执行 Agent A"""
    print("=" * 60)
    print("[AutoMonitor] 启动 Agent A 执行（记忆工作流）")
    print("=" * 60)
    script = BASE_DIR / "agents" / "agent_a_runner.py"
    if not script.exists():
        print(f"[AutoMonitor] 错误: 脚本不存在 {script}")
        return False

    try:
        result = subprocess.run(
            ["python3", str(script)],
            cwd=str(BASE_DIR),
            capture_output=True, text=True, timeout=180
        )
        key_lines = [l for l in result.stdout.split("\n")
                     if any(kw in l for kw in ["决策", "执行", "拦截", "通过", "权益", "USDC", "错误", "记忆", "大师"])
                     and "Warning" not in l]
        for line in key_lines[-10:]:
            print(f"  {line.strip()}")
        if result.returncode != 0:
            print(f"[AutoMonitor] Agent A 退出码 {result.returncode}: {result.stderr[:200]}")
            return False
        print("[AutoMonitor] Agent A 执行完成")
        return True
    except subprocess.TimeoutExpired:
        print("[AutoMonitor] Agent A 执行超时")
        return False
    except Exception as e:
        print(f"[AutoMonitor] Agent A 执行异常: {e}")
        return False

def run_agent_b():
    """按完整流程执行 Agent B"""
    print("=" * 60)
    print("[AutoMonitor] 启动 Agent B 执行（完整流程）")
    print("=" * 60)
    script = BASE_DIR / "agents" / "agent_b_runner.py"
    if not script.exists():
        print(f"[AutoMonitor] 错误: 脚本不存在 {script}")
        return False

    try:
        result = subprocess.run(
            ["python3", str(script)],
            cwd=str(BASE_DIR),
            capture_output=True, text=True, timeout=300
        )
        key_lines = [l for l in result.stdout.split("\n")
                     if any(kw in l for kw in ["决策", "执行", "拦截", "通过", "权益", "USDC", "错误", "记忆", "闭环", "教训"])
                     and "Warning" not in l]
        for line in key_lines[-10:]:
            print(f"  {line.strip()}")
        if result.returncode != 0:
            print(f"[AutoMonitor] Agent B 退出码 {result.returncode}: {result.stderr[:200]}")
            return False
        print("[AutoMonitor] Agent B 执行完成")
        return True
    except subprocess.TimeoutExpired:
        print("[AutoMonitor] Agent B 执行超时")
        return False
    except Exception as e:
        print(f"[AutoMonitor] Agent B 执行异常: {e}")
        return False

# ── 复盘蒸馏学习 ────────────────────────────────────────────────────────────

def load_logs(log_dir: Path, limit: int = 10) -> list:
    """加载最近 N 条日志"""
    logs = []
    if not log_dir.exists():
        return logs
    for f in sorted(log_dir.glob("*.json"))[-limit:]:
        try:
            with open(f) as fp:
                logs.append(json.load(fp))
        except Exception:
            pass
    return logs

def distill_agent_a():
    """Agent A 复盘蒸馏学习"""
    print("\n" + "=" * 60)
    print("[AutoMonitor] Agent A 复盘蒸馏学习")
    print("=" * 60)

    from core.agent_a_memory import (
        load_memory, save_memory, add_lesson,
        update_equity_stats, maybe_switch_master,
    )

    mem = load_memory()
    logs = load_logs(AGENT_A_LOG_DIR, limit=20)

    if not logs:
        print("[AutoMonitor] Agent A 无日志，跳过复盘")
        return

    # 统计最近交易
    closed_trades = [l for l in logs if l.get("action") != "HOLD" and l.get("pnl_pct") is not None]
    wins = [t for t in closed_trades if t.get("pnl_pct", 0) > 0]
    losses = [t for t in closed_trades if t.get("pnl_pct", 0) <= 0]

    print(f"[AutoMonitor] 最近 {len(logs)} 轮，非HOLD {len(closed_trades)} 笔，盈利 {len(wins)} 笔，亏损 {len(losses)} 笔")

    # 提取教训
    new_lessons = []
    if losses:
        avg_loss = sum(t.get("pnl_pct", 0) for t in losses) / len(losses)
        lesson = f"最近{len(losses)}笔亏损，平均亏损{avg_loss:.2f}%，需提高置信度门槛或优化止损"
        new_lessons.append((lesson, 3, 4))

    if wins:
        avg_win = sum(t.get("pnl_pct", 0) for t in wins) / len(wins)
        lesson = f"最近{len(wins)}笔盈利，平均盈利{avg_win:.2f}%，可总结成功模式"
        new_lessons.append((lesson, 3, 3))

    # 检查连续亏损
    recent_actions = [l.get("action") for l in logs[-10:]]
    hold_streak = 0
    for a in reversed(recent_actions):
        if a == "HOLD":
            hold_streak += 1
        else:
            break
    if hold_streak >= 5:
        lesson = f"连续{hold_streak}轮HOLD，可能存在过度保守，建议重新评估市场环境"
        new_lessons.append((lesson, 4, 4))

    # 保存教训
    for content, u, i in new_lessons:
        mem = add_lesson(mem, content, universality=u, importance=i)
        print(f"[AutoMonitor] 新增教训: {content}")

    # 更新权益统计
    latest = logs[-1] if logs else {}
    equity = latest.get("execution", {}).get("equity", 0)
    if equity > 0:
        mem = update_equity_stats(mem, equity)

    # 检查大师切换
    regime = latest.get("market_regime", "RANGE")
    mem = maybe_switch_master(mem, regime)

    save_memory(mem)
    print(f"[AutoMonitor] Agent A 记忆已保存，当前大师: {mem.get('current_master')}")

def distill_agent_b():
    """Agent B 复盘蒸馏学习"""
    print("\n" + "=" * 60)
    print("[AutoMonitor] Agent B 复盘蒸馏学习")
    print("=" * 60)

    logs = load_logs(AGENT_B_LOG_DIR, limit=20)
    if not logs:
        print("[AutoMonitor] Agent B 无日志，跳过复盘")
        return

    # 加载记忆
    mem_path = BASE_DIR / "data" / "agent_b_memory.json"
    memory = {}
    if mem_path.exists():
        with open(mem_path) as f:
            memory = json.load(f)

    # 统计
    closed_trades = [l for l in logs if l.get("action") != "HOLD" and l.get("pnl_pct") is not None]
    wins = [t for t in closed_trades if t.get("pnl_pct", 0) > 0]
    losses = [t for t in closed_trades if t.get("pnl_pct", 0) <= 0]

    print(f"[AutoMonitor] 最近 {len(logs)} 轮，非HOLD {len(closed_trades)} 笔，盈利 {len(wins)} 笔，亏损 {len(losses)} 笔")

    # 提取教训
    lessons = memory.get("lessons", [])
    if losses:
        avg_loss = sum(t.get("pnl_pct", 0) for t in losses) / len(losses)
        lesson = f"最近{len(losses)}笔亏损，平均亏损{avg_loss:.2f}%，regime={memory.get('last_regime','?')}，提升置信度门槛至0.75"
        if lesson not in lessons:
            lessons.append(lesson)
            print(f"[AutoMonitor] 新增教训: {lesson}")

    if wins:
        avg_win = sum(t.get("pnl_pct", 0) for t in wins) / len(wins)
        lesson = f"最近{len(wins)}笔盈利，平均盈利{avg_win:.2f}%，可总结趋势跟踪成功模式"
        if lesson not in lessons:
            lessons.append(lesson)
            print(f"[AutoMonitor] 新增教训: {lesson}")

    # 保留最近20条
    memory["lessons"] = lessons[-20:]

    # 保存
    mem_path.parent.mkdir(parents=True, exist_ok=True)
    with open(mem_path, "w") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)
    print(f"[AutoMonitor] Agent B 记忆已保存，共 {len(memory['lessons'])} 条教训")

# ── PR 评论 ─────────────────────────────────────────────────────────────────

def post_pr_comment():
    """在远端 PR 下创建评论"""
    print("\n" + "=" * 60)
    print("[AutoMonitor] 创建 PR 评论")
    print("=" * 60)

    if not GH_TOKEN:
        print("[AutoMonitor] GH_TOKEN 未配置，跳过 PR 评论")
        return False

    # 使用 submit_agent_b_pr.py 生成报告
    script = BASE_DIR / "submit_agent_b_pr.py"
    if script.exists():
        try:
            result = subprocess.run(
                ["python3", str(script)],
                cwd=str(BASE_DIR),
                capture_output=True, text=True, timeout=60
            )
            print(result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)
            if "PR评论成功" in result.stdout:
                print("[AutoMonitor] PR 评论创建成功")
                return True
            else:
                print(f"[AutoMonitor] PR 评论可能失败: {result.stdout[-200:]}")
                return False
        except Exception as e:
            print(f"[AutoMonitor] PR 评论异常: {e}")
            return False
    else:
        # 手动创建简单评论
        cycle = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        logs_a = load_logs(AGENT_A_LOG_DIR, limit=5)
        logs_b = load_logs(AGENT_B_LOG_DIR, limit=5)

        last_a = logs_a[-1] if logs_a else {}
        last_b = logs_b[-1] if logs_b else {}

        body = f"""## 🤖 自动化监控报告 | {cycle}

### Agent A 状态
- 最新决策: {last_a.get('action', 'N/A')} {last_a.get('coin', 'N/A')}
- 置信度: {last_a.get('confidence', 0):.0%}
- 权益: {last_a.get('execution', {}).get('equity', 'N/A')}

### Agent B 状态
- 最新决策: {last_b.get('action', 'N/A')} {last_b.get('coin', 'N/A')}
- 置信度: {last_b.get('confidence', 0):.0%}
- 权益: {last_b.get('account_equity', 'N/A')}

### 系统状态
- 监控时间: {_fmt_ts(_now())}
- 本报告由 auto_monitor.py 自动生成
"""
        url = f"https://api.github.com/repos/{REPO}/issues/{PR_NUMBER}/comments"
        headers = {
            "Authorization": f"token {GH_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        try:
            import requests
            r = requests.post(url, headers=headers, json={"body": body}, timeout=15)
            if r.status_code in (200, 201):
                print("[AutoMonitor] PR 评论创建成功")
                return True
            else:
                print(f"[AutoMonitor] PR 评论失败: {r.status_code} - {r.text[:200]}")
                return False
        except Exception as e:
            print(f"[AutoMonitor] PR 评论异常: {e}")
            return False

# ── 主流程 ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="交易系统自动化监控")
    parser.add_argument("--check-only", action="store_true", help="仅检查状态不触发执行")
    parser.add_argument("--distill-only", action="store_true", help="仅执行复盘和PR评论")
    args = parser.parse_args()

    print("=" * 60)
    print(f"[AutoMonitor] 启动 | {_fmt_ts(_now())}")
    print("=" * 60)

    # ── 1. 检查 Agent A ──
    a_ok, a_status = is_agent_running("Agent A", AGENT_A_LOG_DIR)
    print(f"\n[Agent A] 状态: {'✅ 正常' if a_ok else '⚠️ 异常'} | {a_status}")

    if not a_ok and not args.distill_only:
        if not args.check_only:
            run_agent_a()
        else:
            print("[AutoMonitor] --check-only 模式，跳过执行")

    # ── 2. 检查 Agent B ──
    b_ok, b_status = is_agent_running("Agent B", AGENT_B_LOG_DIR)
    print(f"\n[Agent B] 状态: {'✅ 正常' if b_ok else '⚠️ 异常'} | {b_status}")

    if not b_ok and not args.distill_only:
        if not args.check_only:
            run_agent_b()
        else:
            print("[AutoMonitor] --check-only 模式，跳过执行")

    # ── 3. 复盘蒸馏学习 ──
    distill_agent_a()
    distill_agent_b()

    # ── 4. PR 评论 ──
    post_pr_comment()

    print("\n" + "=" * 60)
    print(f"[AutoMonitor] 完成 | {_fmt_ts(_now())}")
    print("=" * 60)

if __name__ == "__main__":
    main()
