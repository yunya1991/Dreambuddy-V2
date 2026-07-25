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
import argparse
import json
import os
import subprocess
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / "core"))
sys.path.insert(0, str(BASE_DIR / "lib"))

try:
    from config_loader import load_config

    load_config("v15")
except Exception:
    pass

# ── 配置 ───────────────────────────────────────────────────────────────────
AGENT_A_LOG_DIR = BASE_DIR / "logs" / "v15"
AGENT_B_LOG_DIR = BASE_DIR / "logs" / "v15"
MAX_IDLE_MINUTES = 240  # 超过4小时认为未正常运行
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
        return False, "从未运行过"

    if idle_minutes > MAX_IDLE_MINUTES:
        return False, f"已空闲 {idle_minutes:.0f} 分钟（阈值 {MAX_IDLE_MINUTES} 分钟）"

    return True, f"最近运行 {_fmt_ts(latest_ts)}，空闲 {idle_minutes:.0f} 分钟"


# ── 执行 Agent ──────────────────────────────────────────────────────────────


def run_agent_a():
    """执行 V15 马丁策略交易器"""
    print("=" * 60)
    print("[AutoMonitor] 启动 V15 马丁策略执行")
    print("=" * 60)
    script = BASE_DIR / "core" / "v15_trader.py"
    if not script.exists():
        print(f"[AutoMonitor] 错误: 脚本不存在 {script}")
        return False

    try:
        result = subprocess.run(
            ["python3", str(script)], cwd=str(BASE_DIR), capture_output=True, text=True, timeout=180
        )
        key_lines = [
            l
            for l in result.stdout.split("\n")
            if any(
                kw in l
                for kw in ["信号触发", "开仓", "加仓", "止盈", "止损", "胜率", "权益", "错误"]
            )
            and "Warning" not in l
        ]
        for line in key_lines[-10:]:
            print(f"  {line.strip()}")
        if result.returncode != 0:
            print(f"[AutoMonitor] V15 退出码 {result.returncode}: {result.stderr[:200]}")
            return False
        print("[AutoMonitor] V15 执行完成")
        return True
    except subprocess.TimeoutExpired:
        print("[AutoMonitor] V15 执行超时")
        return False
    except Exception as e:
        print(f"[AutoMonitor] V15 执行异常: {e}")
        return False


def run_agent_b():
    """执行 V15 马丁策略交易器（备用入口）"""
    print("=" * 60)
    print("[AutoMonitor] 启动 V15 马丁策略执行（备用入口）")
    print("=" * 60)
    script = BASE_DIR / "run.py"
    if not script.exists():
        print(f"[AutoMonitor] 错误: 脚本不存在 {script}")
        return False

    try:
        result = subprocess.run(
            ["python3", str(script), "trade"],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=180,
        )
        key_lines = [
            l
            for l in result.stdout.split("\n")
            if any(
                kw in l
                for kw in ["信号触发", "开仓", "加仓", "止盈", "止损", "胜率", "权益", "错误"]
            )
            and "Warning" not in l
        ]
        for line in key_lines[-10:]:
            print(f"  {line.strip()}")
        if result.returncode != 0:
            print(f"[AutoMonitor] V15 (run.py) 退出码 {result.returncode}: {result.stderr[:200]}")
            return False
        print("[AutoMonitor] V15 (run.py) 执行完成")
        return True
    except subprocess.TimeoutExpired:
        print("[AutoMonitor] V15 (run.py) 执行超时")
        return False
    except Exception as e:
        print(f"[AutoMonitor] V15 (run.py) 执行异常: {e}")
        return False


# ── 复盘蒸馏学习 ────────────────────────────────────────────────────────────


def load_logs(log_dir: Path, limit: int = 10) -> list:
    """加载最近 N 条日志"""
    logs = []
    if not log_dir.exists():
        return logs
    for f in sorted(log_dir.glob("*.log"))[-limit:]:
        try:
            with open(f) as fp:
                for line in fp.readlines()[-50:]:
                    if "信号触发" in line or "开仓" in line or "止盈" in line or "止损" in line:
                        logs.append({"line": line.strip()})
        except Exception:
            pass
    return logs


def distill_v15():
    """V15 马丁策略复盘蒸馏学习"""
    print("\n" + "=" * 60)
    print("[AutoMonitor] V15 马丁策略复盘蒸馏学习")
    print("=" * 60)

    state_path = BASE_DIR / "data" / "v15_state.json"
    state = {}
    if state_path.exists():
        try:
            with open(state_path) as f:
                state = json.load(f)
        except Exception:
            pass

    total_trades = state.get("total_trades", 0)
    total_wins = state.get("total_wins", 0)
    consecutive_losses = state.get("consecutive_losses", 0)
    positions = state.get("positions", {})

    win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0

    print(f"[AutoMonitor] 总交易: {total_trades}, 盈利: {total_wins}, 胜率: {win_rate:.1f}%")
    print(f"[AutoMonitor] 连续亏损: {consecutive_losses} 次")
    print(f"[AutoMonitor] 当前持仓: {len(positions)} 个")

    if positions:
        for coin, pos in positions.items():
            entry_price = pos.get("entry_price", 0)
            sl_price = pos.get("stop_loss_price", 0)
            tp_pct = pos.get("take_profit_pct", 0) * 100
            print(f"  {coin}: 入场={entry_price}, 止损={sl_price}, 止盈={tp_pct:.1f}%")

    if consecutive_losses >= 3:
        print(f"[AutoMonitor] ⚠️ 连续{consecutive_losses}次亏损，建议提高置信度门槛")

    if total_trades > 0 and win_rate < 40:
        print(f"[AutoMonitor] ⚠️ 胜率{win_rate:.1f}%低于40%，建议优化策略参数")


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
                capture_output=True,
                text=True,
                timeout=60,
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
        cycle = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
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
        headers = {"Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github.v3+json"}
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
    distill_v15()

    # ── 4. PR 评论 ──
    post_pr_comment()

    print("\n" + "=" * 60)
    print(f"[AutoMonitor] 完成 | {_fmt_ts(_now())}")
    print("=" * 60)


if __name__ == "__main__":
    main()
