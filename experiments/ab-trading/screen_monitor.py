#!/usr/bin/env python3
"""
三屏马丁交易自动化监控与自进化任务
功能：
1. 监控三屏马丁系统是否正常运行（检查执行器和编排器最近运行时间）
2. 发现异常时自动触发 screen_orchestrator.py 恢复执行
3. 自进化学习：分析 trade_history，动态调整策略参数（addon_pct, tp_pct, vol_mult）
4. 在远端 PR 下创建评论

用法：
  python3 screen_monitor.py
  python3 screen_monitor.py --check-only    # 仅检查状态
  python3 screen_monitor.py --evolve-only   # 仅执行自进化和PR评论
"""
import os, sys, json, subprocess, time, argparse, warnings, math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

# ── 配置 ───────────────────────────────────────────────────────────────────
STATE_FILE = BASE_DIR / "data" / "screen_trade_state.json"
ORCH_STATE_FILE = BASE_DIR / "data" / "screen_orchestrator_state.json"
EVOLUTION_FILE = BASE_DIR / "data" / "screen_evolution_state.json"
LOG_FILE = BASE_DIR / "logs" / "screen_monitor.log"

MAX_IDLE_MINUTES = 240   # 超过4小时认为未正常运行

def _load_env():
    env_file = BASE_DIR / "config" / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())

_load_env()
GH_TOKEN = os.environ.get("GH_TOKEN", os.environ.get("GITHUB_TOKEN", ""))
PR_NUMBER = "52"
REPO = "yunya1991/Dreambuddy-V2"

# 自进化参数边界
MIN_ADDON_PCT = 5.0
MAX_ADDON_PCT = 12.0
MIN_TP_PCT = 2.5
MAX_TP_PCT = 6.0
MIN_VOL_MULT = 0.5
MAX_VOL_MULT = 2.0

# ── 工具函数 ────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)

def _fmt_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")

def _log(msg: str):
    ts = _fmt_ts(_now())
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def load_json(path: Path, default: dict = None) -> dict:
    if not path.exists():
        return default or {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default or {}

def save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def ts_to_dt(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)

# ── 监控 ────────────────────────────────────────────────────────────────────

def check_screen_health() -> tuple[bool, str, dict]:
    """
    检查三屏马丁健康状态
    返回: (是否正常, 状态说明, 详细数据)
    """
    state = load_json(STATE_FILE, {"last_check_ts": 0, "last_action_ts": 0, "run_count": 0})
    orch = load_json(ORCH_STATE_FILE, {"last_run_ts": 0, "run_count": 0})

    now_ts = _now().timestamp()
    check_idle = (now_ts - state.get("last_check_ts", 0)) / 60
    action_idle = (now_ts - state.get("last_action_ts", 0)) / 60
    orch_idle = (now_ts - orch.get("last_run_ts", 0)) / 60

    detail = {
        "state": state,
        "orch": orch,
        "check_idle_min": round(check_idle, 1),
        "action_idle_min": round(action_idle, 1),
        "orch_idle_min": round(orch_idle, 1),
        "run_count": state.get("run_count", 0),
        "orch_run_count": orch.get("run_count", 0),
        "active": state.get("active", False),
        "direction": state.get("direction", "NONE"),
        "symbol": state.get("active_symbol", "?"),
    }

    # 检查逻辑：编排器或执行器超过阈值即认为异常
    max_idle = max(check_idle, action_idle, orch_idle)

    if max_idle > MAX_IDLE_MINUTES:
        return False, f"已空闲 {max_idle:.0f} 分钟（阈值 {MAX_IDLE_MINUTES} 分钟）", detail

    return True, f"最近检查 {_fmt_ts(ts_to_dt(state.get('last_check_ts', 0)))}，空闲 {check_idle:.0f} 分钟", detail

# ── 恢复执行 ────────────────────────────────────────────────────────────────

def run_screen_orchestrator():
    """触发三屏马丁编排器执行"""
    _log("=" * 60)
    _log("启动三屏马丁编排器恢复执行")
    _log("=" * 60)

    script = BASE_DIR / "screen_orchestrator.py"
    if not script.exists():
        _log(f"错误: 脚本不存在 {script}")
        return False

    try:
        result = subprocess.run(
            ["python3", str(script)],
            cwd=str(BASE_DIR),
            capture_output=True, text=True, timeout=180
        )
        key_lines = [l for l in result.stdout.split("\n")
                     if any(kw in l for kw in ["触发", "执行", "决策", "持仓", "错误", "完成"])
                     and "Warning" not in l]
        for line in key_lines[-15:]:
            _log(f"  {line.strip()}")
        if result.returncode != 0:
            _log(f"编排器退出码 {result.returncode}: {result.stderr[:200]}")
            return False
        _log("三屏马丁编排器执行完成")
        return True
    except subprocess.TimeoutExpired:
        _log("编排器执行超时")
        return False
    except Exception as e:
        _log(f"编排器执行异常: {e}")
        return False

# ── 自进化学习 ──────────────────────────────────────────────────────────────

def calculate_pnl(entry_price: float, exit_price: float, direction: str, size: float) -> float:
    """计算单笔盈亏（USDT）"""
    if direction == "BEAR":
        return (entry_price - exit_price) * size
    else:
        return (exit_price - entry_price) * size

def analyze_trade_history(trades: List[dict]) -> dict:
    """分析交易历史，提取关键指标"""
    if not trades:
        return {}

    opens = [t for t in trades if t.get("action") in ("OPEN_BEAR", "OPEN_BULL")]
    closes = [t for t in trades if t.get("action") in ("CLOSE", "MANUAL_CLOSE", "TP_HIT", "SL_HIT")]

    # 尝试配对 open/close
    paired = []
    open_idx = 0
    for c in closes:
        # 找到对应的 open
        for i, o in enumerate(opens[open_idx:], open_idx):
            if o.get("symbol", "?") == c.get("symbol", "?"):
                paired.append((o, c))
                open_idx = i + 1
                break

    pnls = []
    win_count = 0
    loss_count = 0
    for o, c in paired:
        direction = o.get("side", o.get("direction", "BULL"))
        pnl = calculate_pnl(
            o.get("price", 0),
            c.get("price", 0),
            direction,
            o.get("size", 0)
        )
        pnls.append(pnl)
        if pnl > 0:
            win_count += 1
        else:
            loss_count += 1

    total = len(pnls)
    win_rate = win_count / total if total > 0 else 0
    avg_pnl = sum(pnls) / total if total > 0 else 0
    total_pnl = sum(pnls)
    max_win = max(pnls) if pnls else 0
    max_loss = min(pnls) if pnls else 0

    return {
        "total_trades": total,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": win_rate,
        "avg_pnl": avg_pnl,
        "total_pnl": total_pnl,
        "max_win": max_win,
        "max_loss": max_loss,
        "profit_factor": abs(sum(p for p in pnls if p > 0) / sum(p for p in pnls if p < 0)) if any(p < 0 for p in pnls) else float('inf'),
    }

def evolve_parameters(state: dict, stats: dict) -> dict:
    """
    根据交易统计自进化调整参数
    规则：
    - 胜率 < 40%：收紧止盈、放宽加仓间隔（减少风险暴露）
    - 胜率 > 60%：放宽止盈、收紧加仓间隔（让利润奔跑）
    - 盈亏比 < 1.0：提高止盈比例
    - 连续亏损：降低仓位倍数
    """
    current = {
        "addon_pct": state.get("addon_pct", 8.0),
        "tp_pct": state.get("tp_pct", 4.0),
        "vol_mult": state.get("vol_mult", 1.0),
    }

    if not stats or stats.get("total_trades", 0) < 3:
        _log("交易样本不足（<3），跳过参数进化")
        return current

    win_rate = stats.get("win_rate", 0)
    profit_factor = stats.get("profit_factor", 0)
    total_pnl = stats.get("total_pnl", 0)

    _log(f"自进化分析: 胜率={win_rate:.1%}, 盈亏比={profit_factor:.2f}, 总盈亏={total_pnl:.2f} USDT")

    new_addon = current["addon_pct"]
    new_tp = current["tp_pct"]
    new_vol = current["vol_mult"]
    adjustments = []

    # 根据胜率调整
    if win_rate < 0.40:
        new_addon = min(new_addon + 0.5, MAX_ADDON_PCT)
        new_tp = max(new_tp - 0.3, MIN_TP_PCT)
        adjustments.append("胜率偏低: 放宽加仓间隔+收紧止盈")
    elif win_rate > 0.60:
        new_addon = max(new_addon - 0.5, MIN_ADDON_PCT)
        new_tp = min(new_tp + 0.3, MAX_TP_PCT)
        adjustments.append("胜率偏高: 收紧加仓间隔+放宽止盈")

    # 根据盈亏比调整
    if profit_factor < 1.0 and profit_factor != float('inf'):
        new_tp = min(new_tp + 0.5, MAX_TP_PCT)
        adjustments.append("盈亏比<1: 提高止盈比例")
    elif profit_factor > 2.0:
        new_tp = max(new_tp - 0.2, MIN_TP_PCT)
        adjustments.append("盈亏比>2: 可适当收紧止盈锁定利润")

    # 根据总盈亏调整 vol_mult
    if total_pnl < -50:
        new_vol = max(new_vol * 0.9, MIN_VOL_MULT)
        adjustments.append("总亏损>50U: 降低波动倍数")
    elif total_pnl > 100:
        new_vol = min(new_vol * 1.05, MAX_VOL_MULT)
        adjustments.append("总盈利>100U: 轻微提高波动倍数")

    _log(f"参数调整: addon_pct {current['addon_pct']:.2f} -> {new_addon:.2f}, "
         f"tp_pct {current['tp_pct']:.2f} -> {new_tp:.2f}, "
         f"vol_mult {current['vol_mult']:.2f} -> {new_vol:.2f}")
    if adjustments:
        _log(f"调整原因: {'; '.join(adjustments)}")

    return {
        "addon_pct": round(new_addon, 2),
        "tp_pct": round(new_tp, 2),
        "vol_mult": round(new_vol, 3),
        "adjustments": adjustments,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "total_pnl": total_pnl,
    }

def run_evolution():
    """执行自进化学习"""
    _log("\n" + "=" * 60)
    _log("三屏马丁自进化学习")
    _log("=" * 60)

    state = load_json(STATE_FILE, {"trade_history": []})
    trades = state.get("trade_history", [])

    _log(f"交易历史: {len(trades)} 条记录")

    # 分析历史
    stats = analyze_trade_history(trades)
    if stats:
        _log(f"配对交易: {stats['total_trades']} 笔 | 胜率 {stats['win_rate']:.1%} | "
             f"总盈亏 {stats['total_pnl']:.2f} USDT")

    # 进化参数
    evolved = evolve_parameters(state, stats)

    # 保存进化状态
    evolution = load_json(EVOLUTION_FILE, {
        "evolution_count": 0,
        "parameter_history": [],
        "lessons": [],
    })

    evolution["evolution_count"] = evolution.get("evolution_count", 0) + 1
    evolution["parameter_history"].append({
        "ts": _fmt_ts(_now()),
        "addon_pct": evolved["addon_pct"],
        "tp_pct": evolved["tp_pct"],
        "vol_mult": evolved["vol_mult"],
        "win_rate": evolved.get("win_rate", 0),
        "profit_factor": evolved.get("profit_factor", 0),
        "total_pnl": evolved.get("total_pnl", 0),
        "adjustments": evolved.get("adjustments", []),
    })
    # 保留最近20条历史
    evolution["parameter_history"] = evolution["parameter_history"][-20:]

    # 提取教训
    lessons = evolution.get("lessons", [])
    if stats.get("win_rate", 1) < 0.40:
        lesson = f"胜率仅{stats['win_rate']:.1%}，建议加强Screen1信号过滤或降低开仓频率"
        if lesson not in lessons:
            lessons.append(lesson)
            _log(f"新增教训: {lesson}")
    if stats.get("profit_factor", 999) < 1.0:
        lesson = f"盈亏比{stats['profit_factor']:.2f}<1，止盈设置过于保守或止损过宽"
        if lesson not in lessons:
            lessons.append(lesson)
            _log(f"新增教训: {lesson}")

    evolution["lessons"] = lessons[-20:]
    evolution["last_evolve_ts"] = _now().timestamp()

    save_json(EVOLUTION_FILE, evolution)
    _log(f"进化状态已保存 | 累计进化 {evolution['evolution_count']} 次")

    # 可选：将进化参数写回 screen_trade_state.json
    # 注意：这会影响实际交易参数，谨慎开启
    # state["addon_pct"] = evolved["addon_pct"]
    # state["tp_pct"] = evolved["tp_pct"]
    # state["vol_mult"] = evolved["vol_mult"]
    # save_json(STATE_FILE, state)
    # _log("进化参数已同步到交易状态")

    return evolution, stats

# ── PR 评论 ─────────────────────────────────────────────────────────────────

def post_pr_comment(detail: dict, evolution: dict, stats: dict):
    """在远端 PR 下创建三屏马丁专属评论"""
    _log("\n" + "=" * 60)
    _log("创建三屏马丁 PR 评论")
    _log("=" * 60)

    if not GH_TOKEN:
        _log("GH_TOKEN 未配置，跳过 PR 评论")
        return False

    cycle = _now().strftime('%Y%m%d_%H%M%S')
    state = detail.get("state", {})

    # 构建报告
    active = state.get("active", False)
    direction = state.get("direction", "NONE")
    symbol = state.get("active_symbol", "?")
    total_size = state.get("total_size", 0)
    avg_entry = state.get("avg_entry", 0)
    tp_price = state.get("tp_price", 0)
    run_count = state.get("run_count", 0)
    trade_history = state.get("trade_history", [])
    mode = state.get("last_mode", "v9")

    # 参数
    addon_pct = state.get("addon_pct", 8.0)
    tp_pct = state.get("tp_pct", 4.0)
    vol_mult = state.get("vol_mult", 1.0)

    # 进化参数
    evo_count = evolution.get("evolution_count", 0)
    param_hist = evolution.get("parameter_history", [])
    latest_params = param_hist[-1] if param_hist else {}

    # 统计
    win_rate = stats.get("win_rate", 0) if stats else 0
    total_pnl = stats.get("total_pnl", 0) if stats else 0

    body = f"""## 📊 三屏马丁交易报告 | cycle: {cycle}

### 🎯 当前持仓
| 项目 | 值 |
|------|-----|
| 状态 | {'🟢 持仓中' if active else '⚪ 空仓'} |
| 方向 | {direction} |
| 标的 | {symbol} |
| 持仓量 | {total_size} |
| 均价 | ${avg_entry:.2f} |
| 止盈价 | ${tp_price:.2f} |

### ⚙️ 策略参数
| 参数 | 当前值 | 进化后值 |
|------|--------|----------|
| 加仓间隔 | {addon_pct:.2f}% | {latest_params.get('addon_pct', addon_pct):.2f}% |
| 止盈比例 | {tp_pct:.2f}% | {latest_params.get('tp_pct', tp_pct):.2f}% |
| 波动倍数 | {vol_mult:.3f} | {latest_params.get('vol_mult', vol_mult):.3f} |
| 决策模式 | {mode} | - |

### 📈 交易统计
| 指标 | 值 |
|------|-----|
| 累计执行轮数 | {run_count} |
| 历史交易记录 | {len(trade_history)} 条 |
| 配对交易数 | {stats.get('total_trades', 0) if stats else 0} 笔 |
| 胜率 | {win_rate:.1%} |
| 总盈亏 | {total_pnl:.2f} USDT |
| 自进化次数 | {evo_count} |

### 🔧 本轮调整
{chr(10).join(f"- {a}" for a in latest_params.get('adjustments', [])) if latest_params.get('adjustments') else '- 无调整'}

### 🧠 教训总结
{chr(10).join(f"- {l}" for l in evolution.get('lessons', [])[-5:]) if evolution.get('lessons') else '- 暂无'}

### 📝 系统状态
- 监控时间: {_fmt_ts(_now())}
- 执行器空闲: {detail.get('check_idle_min', 0)} 分钟
- 编排器空闲: {detail.get('orch_idle_min', 0)} 分钟
- 本报告由 screen_monitor.py 自动生成
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
            _log("PR 评论创建成功")
            return True
        else:
            _log(f"PR 评论失败: {r.status_code} - {r.text[:200]}")
            return False
    except Exception as e:
        _log(f"PR 评论异常: {e}")
        return False

# ── 主流程 ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="三屏马丁自动化监控")
    parser.add_argument("--check-only", action="store_true", help="仅检查状态不触发执行")
    parser.add_argument("--evolve-only", action="store_true", help="仅执行自进化和PR评论")
    args = parser.parse_args()

    _log("=" * 60)
    _log(f"三屏马丁监控启动 | {_fmt_ts(_now())}")
    _log("=" * 60)

    # ── 1. 检查健康状态 ──
    healthy, status, detail = check_screen_health()
    _log(f"\n[三屏马丁] 状态: {'✅ 正常' if healthy else '⚠️ 异常'} | {status}")

    if not healthy and not args.evolve_only:
        if not args.check_only:
            _log("[AutoMonitor] 三屏马丁异常，触发编排器恢复执行...")
            run_screen_orchestrator()
        else:
            _log("[AutoMonitor] --check-only 模式，跳过执行")

    # ── 2. 自进化学习 ──
    evolution, stats = run_evolution()

    # ── 3. PR 评论 ──
    post_pr_comment(detail, evolution, stats)

    _log("\n" + "=" * 60)
    _log(f"三屏马丁监控完成 | {_fmt_ts(_now())}")
    _log("=" * 60)

if __name__ == "__main__":
    main()
