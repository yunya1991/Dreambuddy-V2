#!/usr/bin/env python3
"""
易经推理交易自动化监控与自进化任务
功能：
1. 监控易经推理交易是否正常运行（检查心跳、学习调度、OKX连接）
2. 发现异常时自动恢复执行（启动 polling_trader）
3. 自进化学习：重训 LiangyiEngine + QMM，分析绩效，调整置信度阈值
4. 在远端 PR 下创建评论

用法：
  python -m scripts.memory_l4.yijing_monitor
  python -m scripts.memory_l4.yijing_monitor --check-only    # 仅检查状态
  python -m scripts.memory_l4.yijing_monitor --evolve-only   # 仅执行自进化和PR评论
"""
import os, sys, json, subprocess, time, argparse, warnings, math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

warnings.filterwarnings("ignore")

# ── 路径设置 ────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 加载 .env 配置，确保 os.environ 中包含 POLLING_COINS/INITIAL_EQUITY 等
try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
except Exception:
    pass

from scripts.memory_l4.paths import (
    workspace_root,
    workbuddy_dir,
    memory_l4_dir,
    memory_l4_cases_dir,
    memory_l4_stats_dir,
    memory_l4_reviews_dir,
    memory_l4_distills_dir,
)

BASE_DIR = workspace_root()

# ── 配置 ───────────────────────────────────────────────────────────────────
HEARTBEAT_FILE = workbuddy_dir() / "memory_l4" / "guardian" / "heartbeat.json"
SCHEDULER_STATE_FILE = workbuddy_dir() / "memory_l4" / "learning" / "scheduler_state.json"
PERF_FILE = workbuddy_dir() / "memory_l4" / "stats" / "performance.json"
TRADER_LOG_DIR = BASE_DIR / "data" / "polling_trader"
OKX_SIM_DIR = BASE_DIR / "data" / "okx_sim"
LOG_FILE = BASE_DIR / "logs" / "yijing_monitor.log"
RISK_STATE_FILE = workbuddy_dir() / "memory_l4" / "risk" / "risk_state.json"

MAX_IDLE_MINUTES = 30   # 心跳超过30分钟无更新认为异常
GH_TOKEN = os.environ.get("GH_TOKEN", os.environ.get("GITHUB_TOKEN", ""))
PR_NUMBER = "52"
REPO = "yunya1991/Dreambuddy-V2"

FEISHU_ALERT_ENABLED = True

# ── 飞书告警 ────────────────────────────────────────────────────────────────

def _send_feishu_alert(alert_type: str, level: str, message: str, details: Dict = None):
    if not FEISHU_ALERT_ENABLED:
        return
    try:
        from scripts.memory_l4.yijing_feishu_alert import send_alert
        send_alert(alert_type, level, message, details)
    except Exception as e:
        _log(f"飞书告警发送失败: {e}")

def _send_feishu_heartbeat_timeout(idle_minutes: float):
    try:
        from scripts.memory_l4.yijing_feishu_alert import notify_heartbeat_timeout
        notify_heartbeat_timeout(idle_minutes, MAX_IDLE_MINUTES)
    except Exception as e:
        _log(f"飞书心跳告警发送失败: {e}")

def _send_feishu_trading_halted(reason: str, consecutive_losses: int, daily_pnl: float = 0):
    try:
        from scripts.memory_l4.yijing_feishu_alert import notify_trading_halted
        notify_trading_halted(reason, consecutive_losses, daily_pnl)
    except Exception as e:
        _log(f"飞书交易暂停告警发送失败: {e}")

def _send_feishu_status_summary(health: bool, status: str, detail: Dict):
    try:
        from scripts.memory_l4.yijing_feishu_alert import notify_status_summary
        notify_status_summary(health, status, detail)
    except Exception as e:
        _log(f"飞书状态汇总发送失败: {e}")

# ── 工具函数 ────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)

def _fmt_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")

def _log(msg: str):
    ts = _fmt_ts(_now())
    line = f"[{ts}] {msg}"
    # 避免重复写：如果 stdout/stderr 被重定向到同一个日志文件（例如 shell >> log 2>&1），
    # 就跳过 print，只通过显式写文件输出。只有交互式（TTY）运行时同时输出到终端。
    try:
        if sys.stdout.isatty():
            print(line, flush=True)
    except Exception:
        pass
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

def check_yijing_health() -> tuple[bool, str, dict]:
    """
    检查易经推理交易健康状态
    返回: (是否正常, 状态说明, 详细数据)
    """
    heartbeat = load_json(HEARTBEAT_FILE, {"ts": 0, "status": "never_run"})
    scheduler = load_json(SCHEDULER_STATE_FILE, {"last_retrain_time": 0})
    perf = load_json(PERF_FILE, {"total_pnl": 0, "win_rate": 0})

    now_ts = _now().timestamp()
    heartbeat_idle = (now_ts - heartbeat.get("ts", 0)) / 60

    # 统计案例数
    cases_dir = memory_l4_cases_dir()
    case_count = len(list(cases_dir.glob("*.json"))) if cases_dir.exists() else 0

    # 统计交易日志
    trader_logs = list(TRADER_LOG_DIR.glob("*.jsonl")) if TRADER_LOG_DIR.exists() else []
    trader_log_count = len(trader_logs)

    detail = {
        "heartbeat": heartbeat,
        "scheduler": scheduler,
        "perf": perf,
        "heartbeat_idle_min": round(heartbeat_idle, 1),
        "case_count": case_count,
        "trader_log_count": trader_log_count,
        "last_retrain": scheduler.get("last_retrain_time_str", "never"),
        "retrain_count": scheduler.get("retrain_count", 0),
        "total_pnl": perf.get("total_pnl", 0),
        "win_rate": perf.get("win_rate", 0),
    }

    # 检查心跳是否活跃
    if heartbeat_idle > MAX_IDLE_MINUTES:
        _send_feishu_heartbeat_timeout(heartbeat_idle)
        return False, f"心跳已空闲 {heartbeat_idle:.0f} 分钟（阈值 {MAX_IDLE_MINUTES} 分钟）", detail

    # 检查是否有运行记录
    if heartbeat.get("status") in ("error", "stopped"):
        _send_feishu_alert(
            "heartbeat",
            "critical",
            f"进程状态异常: {heartbeat.get('status')} | last_error: {heartbeat.get('last_error', 'N/A')}",
            {"pid": heartbeat.get("pid"), "status": heartbeat.get("status")}
        )
        return False, f"进程状态异常: {heartbeat.get('status')} | last_error: {heartbeat.get('last_error', 'N/A')}", detail

    # 检查风控状态
    risk_state = load_json(RISK_STATE_FILE, {})
    if risk_state.get("trading_halted", False):
        _send_feishu_trading_halted(
            risk_state.get("halt_reason", ""),
            risk_state.get("consecutive_losses", 0),
            risk_state.get("daily_pnl", 0),
        )
        detail["trading_halted"] = True
        detail["halt_reason"] = risk_state.get("halt_reason")

    return True, f"心跳正常，空闲 {heartbeat_idle:.0f} 分钟，案例 {case_count} 个，重训 {scheduler.get('retrain_count', 0)} 次", detail

# ── 恢复执行 ────────────────────────────────────────────────────────────────

def run_polling_trader():
    """启动易经推理轮询交易器"""
    _log("=" * 60)
    _log("启动易经推理轮询交易器")
    _log("=" * 60)

    script = BASE_DIR / "scripts" / "memory_l4" / "polling_trader.py"
    if not script.exists():
        _log(f"错误: 脚本不存在 {script}")
        return False

    try:
        # 使用 nohup 后台启动（参数与 .env 保持一致：INITIAL_EQUITY 200USDT，15币种，interval=300s）
        import os
        coins = os.environ.get("POLLING_COINS", "UNI,PUMP,MU,SKHYNIX,HYPE,ETH,BTC,SOL,XAU,XAG,GOOGL,NVDA,AMZN,OKB,BNB")
        interval = os.environ.get("POLLING_INTERVAL", "300")
        confidence = os.environ.get("CONFIDENCE_THRESHOLD", "0.70")
        max_positions = os.environ.get("MAX_POSITIONS", "3")
        position_pct = os.environ.get("DEFAULT_POSITION_PCT", "0.10")
        initial_equity = os.environ.get("INITIAL_EQUITY", "200")

        # 日志重定向到 BASE_DIR/logs
        log_dir = BASE_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_log = log_dir / "trading_stdout.log"
        stderr_log = log_dir / "trading_stderr.log"

        # 用 Popen 后台启动（nohup + 重定向），避免 subprocess.run timeout=30 触发"启动超时"误报
        cmd = [
            "nohup", sys.executable, "-m", "scripts.memory_l4.polling_trader",
            "--interval", interval, "--coins", coins,
            "--confidence", confidence, "--max-positions", max_positions,
            "--position-pct", position_pct,
            "--initial-equity", initial_equity,
        ]
        with open(stdout_log, "a") as out_f, open(stderr_log, "a") as err_f:
            proc = subprocess.Popen(
                cmd,
                cwd=str(BASE_DIR),
                stdout=out_f, stderr=err_f,
                start_new_session=True,
            )
        _log(f"Popen 启动成功 PID={proc.pid}")
        # 短等待确认进程未立即退出
        time.sleep(3)
        polled = proc.poll()
        if polled is None:
            _log(f"polling_trader 已在后台启动（PID={proc.pid}，存活）")
            return True
        else:
            _log(f"启动后立即退出 (exit={polled})，请检查 {stderr_log}")
            return False
    except Exception as e:
        _log(f"启动异常: {e}")
        return False

# ── 自进化学习 ──────────────────────────────────────────────────────────────

def trigger_retrain():
    """触发两仪引擎和QMM重训"""
    _log("=" * 60)
    _log("触发易经推理模型重训")
    _log("=" * 60)

    try:
        from scripts.memory_l4.learning_scheduler import LearningScheduler
        from scripts.memory_l4.bcrm.engine import BCRMEngine

        bcrm = BCRMEngine.from_config()  # PROP-20260810
        scheduler = LearningScheduler(bcrm)

        # 强制触发重训
        scheduler.trigger_retrain(force=True)
        _log("重训完成")

        # 保存状态
        state = load_json(SCHEDULER_STATE_FILE, {})
        state["last_retrain_time"] = _now().timestamp()
        state["last_retrain_time_str"] = _fmt_ts(_now())
        state["retrain_count"] = state.get("retrain_count", 0) + 1
        save_json(SCHEDULER_STATE_FILE, state)

        return True
    except Exception as e:
        _log(f"重训异常: {e}")
        return False

def analyze_performance() -> dict:
    """分析交易绩效（P1修正：优先从 PerformanceTracker 的 daily_stats.json 读取，统一数据源）"""
    _log("=" * 60)
    _log("分析易经推理交易绩效")
    _log("=" * 60)

    perf = load_json(PERF_FILE, {
        "total_trades": 0,
        "win_count": 0,
        "loss_count": 0,
        "win_rate": 0,
        "total_pnl": 0,
        "avg_pnl": 0,
        "max_win": 0,
        "max_loss": 0,
        "consecutive_losses": 0,
    })

    # P1修正：优先从 PerformanceTracker 的 daily_stats.json 读取（与 polling_trader 同源）
    daily_stats_file = workbuddy_dir() / "memory_l4" / "stats" / "daily_stats.json"
    all_trades_file = workbuddy_dir() / "memory_l4" / "stats" / "all_trades.jsonl"

    pnl_list = []
    consecutive_losses = 0

    # 优先从 all_trades.jsonl 读取逐笔交易（PerformanceTracker 写入）
    if all_trades_file.exists():
        try:
            for line in all_trades_file.read_text(encoding="utf-8").strip().split("\n"):
                if not line.strip():
                    continue
                trade = json.loads(line)
                pnl = trade.get("pnl", 0)
                if pnl is not None:
                    pnl_list.append(pnl)
        except Exception as e:
            _log(f"读取 all_trades.jsonl 失败: {e}，回退到 cases 目录")

    # 如果 all_trades.jsonl 不可用，回退到 cases 目录（兼容旧数据）
    if not pnl_list:
        cases_dir = memory_l4_cases_dir()
        if cases_dir.exists():
            cases = [load_json(f) for f in cases_dir.glob("*.json")]
            pnl_list = [c.get("pnl", 0) for c in cases if c.get("pnl") is not None]

    if pnl_list:
        perf["total_trades"] = len(pnl_list)
        perf["win_count"] = sum(1 for p in pnl_list if p > 0)
        perf["loss_count"] = sum(1 for p in pnl_list if p <= 0)
        perf["win_rate"] = perf["win_count"] / perf["total_trades"] if perf["total_trades"] > 0 else 0
        perf["total_pnl"] = sum(pnl_list)
        perf["avg_pnl"] = perf["total_pnl"] / perf["total_trades"]
        perf["max_win"] = max(pnl_list) if pnl_list else 0
        perf["max_loss"] = min(pnl_list) if pnl_list else 0

        # 从 daily_stats.json 读取最近一天的连亏次数
        if daily_stats_file.exists():
            try:
                daily_stats = load_json(daily_stats_file, {})
                # 取最近一天
                if daily_stats:
                    latest_date = sorted(daily_stats.keys())[-1]
                    latest = daily_stats[latest_date]
                    consecutive_losses = latest.get("current_consecutive_losses", 0)
            except Exception:
                pass

    perf["consecutive_losses"] = consecutive_losses

    _log(f"绩效统计: 总交易 {perf['total_trades']} 笔 | 胜率 {perf['win_rate']:.1%} | 总盈亏 {perf['total_pnl']:.2f} USDT")

    # 保存更新后的绩效
    perf["last_update"] = _fmt_ts(_now())
    perf["data_source"] = "all_trades.jsonl" if all_trades_file.exists() else "cases"
    save_json(PERF_FILE, perf)

    return perf

def evolve_thresholds(perf: dict) -> dict:
    """
    根据绩效自进化调整阈值
    规则：
    - 胜率 < 40%：降低单笔仓位（保持信号频率，降低风险）
    - 胜率 > 60%：提高单笔仓位（信号质量高，加大投入）
    - 连续亏损 >= 5：降低仓位至最小，触发复盘
    - 总盈利 > 500U：适当提高仓位
    - 总亏损 < -100U：降低仓位
    - 置信度门槛保持稳定，不随亏损提高（保持交易频率）
    """
    thresholds = {
        "confidence_threshold": 0.70,
        "daily_loss_limit": -30.0,
        "max_consecutive_losses": 999,
        "loss_limit_pct": 0.20,
        "default_position_pct": 0.10,
    }

    # 从现有配置加载
    config_file = OKX_SIM_DIR / "config.json"
    if config_file.exists():
        config = load_json(config_file, {})
        thresholds["confidence_threshold"] = config.get("confidence_threshold", 0.70)
        thresholds["daily_loss_limit"] = config.get("daily_loss_limit", -30.0)
        thresholds["max_consecutive_losses"] = config.get("max_consecutive_losses", 999)
        thresholds["loss_limit_pct"] = config.get("loss_limit_pct", 0.20)
        thresholds["default_position_pct"] = config.get("default_position_pct", 0.10)

    adjustments = []

    win_rate = perf.get("win_rate", 0)
    total_pnl = perf.get("total_pnl", 0)
    consecutive_losses = perf.get("consecutive_losses", 0)

    # 置信度门槛保持稳定（不随亏损提高）
    # 根据胜率调整单笔仓位而非置信度门槛
    if win_rate < 0.40:
        thresholds["default_position_pct"] = max(thresholds["default_position_pct"] - 0.02, 0.02)
        adjustments.append(f"胜率偏低({win_rate:.1%}): 降低仓位至{thresholds['default_position_pct']:.1%}")
    elif win_rate > 0.60:
        thresholds["default_position_pct"] = min(thresholds["default_position_pct"] + 0.02, 0.20)
        adjustments.append(f"胜率偏高({win_rate:.1%}): 提高仓位至{thresholds['default_position_pct']:.1%}")

    # 根据总盈亏调整仓位
    if total_pnl > 500:
        thresholds["default_position_pct"] = min(thresholds["default_position_pct"] + 0.01, 0.20)
        adjustments.append("总盈利良好: 提高仓位")
    elif total_pnl < -100:
        thresholds["default_position_pct"] = max(thresholds["default_position_pct"] - 0.02, 0.02)
        adjustments.append(f"总亏损较大({total_pnl:.0f}U): 降低仓位")

    # 根据连续亏损调整
    if consecutive_losses >= 5:
        thresholds["default_position_pct"] = max(thresholds["default_position_pct"] - 0.03, 0.02)
        adjustments.append(f"连续亏损{consecutive_losses}次: 大幅降低仓位")

    # 根据总交易数调整置信度门槛（仅在交易足够多时微调）
    total_trades = perf.get("total_trades", 0)
    if total_trades >= 20:
        if win_rate < 0.30:
            thresholds["confidence_threshold"] = min(thresholds["confidence_threshold"] + 0.03, 0.80)
            adjustments.append("交易足够多但胜率低: 小幅提高置信度门槛")
        elif win_rate > 0.70:
            thresholds["confidence_threshold"] = max(thresholds["confidence_threshold"] - 0.02, 0.55)
            adjustments.append("交易足够多且胜率高: 小幅降低置信度门槛")

    _log(f"阈值调整: confidence {thresholds['confidence_threshold']:.2f}, "
         f"position_pct {thresholds['default_position_pct']:.1%}, "
         f"daily_loss {thresholds['daily_loss_limit']:.0f}")
    if adjustments:
        _log(f"调整原因: {'; '.join(adjustments)}")

    # 保存更新后的配置
    config = load_json(config_file, {})
    config["confidence_threshold"] = thresholds["confidence_threshold"]
    config["daily_loss_limit"] = thresholds["daily_loss_limit"]
    config["max_consecutive_losses"] = thresholds["max_consecutive_losses"]
    config["loss_limit_pct"] = thresholds["loss_limit_pct"]
    config["default_position_pct"] = thresholds["default_position_pct"]
    config["last_evolve"] = _fmt_ts(_now())
    save_json(config_file, config)

    return {
        "thresholds": thresholds,
        "adjustments": adjustments,
    }

def _run_self_evolution_cycle(perf: dict) -> dict:
    """
    接入 SelfEvolutionEngine 三层闭环（A8理论实践验证 / 做梦部 / 联网反思）。
    停滞检测通过才执行完整周期，否则返回未触发报告。
    与 evolve_thresholds 互补：前者做轻量规则调整，本函数做深度自进化。
    """
    try:
        from scripts.memory_l4.self_evolution_engine import SelfEvolutionEngine
        engine = SelfEvolutionEngine()
        stats = {
            "win_rate": perf.get("win_rate", 1.0),
            "total_trades": perf.get("total_trades", 0),
            # 以下字段暂无数据源，使用默认值（不会误触发对应条件）
            "hold_streak": 0,
            "accuracy_trend": [],
            "hold_rate": 0.0,
            "top_hexagrams": {},
        }
        should, reason = engine.should_trigger(stats)
        if not should:
            _log(f"[自进化] {reason}，跳过三层闭环")
            return {"triggered": False, "reason": reason}
        _log(f"[自进化] 触发三层闭环: {reason}")
        report = engine.run_full_cycle(stats, [])
        _log(f"[自进化] 完成 | 采纳 {len(report.get('adopted', []))} 个提案")
        return {"triggered": True, "reason": reason, "report": report}
    except Exception as e:
        _log(f"[自进化] 三层闭环异常: {e}")
        return {"triggered": False, "error": str(e)}

def run_evolution():
    """执行自进化学习流程"""
    _log("\n" + "=" * 60)
    _log("易经推理自进化学习")
    _log("=" * 60)

    # 1. 分析绩效
    perf = analyze_performance()

    # 2. 触发重训
    trigger_retrain()

    # 3. 进化阈值
    evolved = evolve_thresholds(perf)

    # 3.5 三层自进化闭环（A8 / 做梦部 / 联网反思）— 停滞检测通过才触发
    self_evo_report = _run_self_evolution_cycle(perf)

    # 4. 保存进化记录
    evolution_file = workbuddy_dir() / "memory_l4" / "evolution" / "yijing_evolution.json"
    evolution = load_json(evolution_file, {
        "evolution_count": 0,
        "history": [],
        "lessons": [],
    })

    # A-3修复：阈值无变化时不 increment evolution_count、不写 history
    adjustments = evolved.get("adjustments", [])
    new_thresholds = evolved.get("thresholds", {})

    # 取上一条 history 的 thresholds 做对比
    prev_history = evolution.get("history", [])
    prev_thresholds = prev_history[-1]["thresholds"] if prev_history else {}

    # 判断是否有实质变化（阈值不同 或 adjustments 非空且不重复）
    thresholds_changed = (new_thresholds != prev_thresholds)
    # 检查 adjustments 是否与上一条完全相同
    prev_adjustments = prev_history[-1].get("adjustments", []) if prev_history else []
    adjustments_same = (adjustments == prev_adjustments and not thresholds_changed)

    if thresholds_changed or (adjustments and not adjustments_same):
        evolution["evolution_count"] = evolution.get("evolution_count", 0) + 1
        evolution["history"].append({
            "ts": _fmt_ts(_now()),
            "win_rate": perf.get("win_rate", 0),
            "total_pnl": perf.get("total_pnl", 0),
            "thresholds": new_thresholds,
            "adjustments": adjustments,
        })
        evolution["history"] = evolution["history"][-20:]
        _log(f"进化状态已保存 | 累计进化 {evolution['evolution_count']} 次")
    else:
        _log(f"阈值无变化，跳过进化记录（当前累计 {evolution.get('evolution_count', 0)} 次）")

    # 提取教训
    lessons = evolution.get("lessons", [])
    if perf.get("win_rate", 1) < 0.35:
        lesson = f"胜率仅{perf['win_rate']:.1%}，BCRM+八卦双引擎信号质量不足，建议加强两仪识别"
        if lesson not in lessons:
            lessons.append(lesson)
            _log(f"新增教训: {lesson}")
    if perf.get("total_pnl", 0) < -300:
        lesson = f"总亏损{perf['total_pnl']:.0f}U，风控阈值过于宽松，需收紧置信度门槛和仓位比例"
        if lesson not in lessons:
            lessons.append(lesson)
            _log(f"新增教训: {lesson}")

    evolution["lessons"] = lessons[-20:]
    evolution["last_evolve_ts"] = _now().timestamp()
    if self_evo_report.get("triggered"):
        _se_report = self_evo_report.get("report", {})
        evolution["last_self_evolution"] = {
            "ts": _fmt_ts(_now()),
            "reason": self_evo_report.get("reason", ""),
            "adopted_count": len(_se_report.get("adopted", [])),
            "proposals_count": len(_se_report.get("proposals", [])),
        }
    save_json(evolution_file, evolution)

    _log(f"进化状态已保存 | 累计进化 {evolution['evolution_count']} 次")

    return evolution, perf, evolved

# ── PR 评论 ─────────────────────────────────────────────────────────────────

def post_pr_comment(detail: dict, evolution: dict, perf: dict, evolved: dict):
    """在远端 PR 下创建易经推理专属评论"""
    _log("\n" + "=" * 60)
    _log("创建易经推理 PR 评论")
    _log("=" * 60)

    if not GH_TOKEN:
        _log("GH_TOKEN 未配置，跳过 PR 评论")
        return False

    cycle = _now().strftime('%Y%m%d_%H%M%S')

    # 构建报告
    heartbeat = detail.get("heartbeat", {})
    scheduler = detail.get("scheduler", {})
    thresholds = evolved.get("thresholds", {})

    body = f"""## 🧙 易经推理交易报告 | cycle: {cycle}

### 🎯 系统状态
| 项目 | 值 |
|------|-----|
| 进程状态 | {heartbeat.get('status', 'unknown')} |
| 心跳空闲 | {detail.get('heartbeat_idle_min', 0)} 分钟 |
| PID | {heartbeat.get('pid', 'N/A')} |
| 累计轮数 | {heartbeat.get('cycle_count', 0)} |

### 📈 交易绩效
| 指标 | 值 |
|------|-----|
| 总交易数 | {perf.get('total_trades', 0)} 笔 |
| 胜率 | {perf.get('win_rate', 0):.1%} |
| 总盈亏 | {perf.get('total_pnl', 0):.2f} USDT |
| 最大盈利 | {perf.get('max_win', 0):.2f} U |
| 最大亏损 | {perf.get('max_loss', 0):.2f} U |

### 🔄 模型状态
| 项目 | 值 |
|------|-----|
| 案例总数 | {detail.get('case_count', 0)} 个 |
| 重训次数 | {scheduler.get('retrain_count', 0)} 次 |
| 上次重训 | {scheduler.get('last_retrain_time_str', 'never')} |

### ⚙️ 风控阈值
| 参数 | 当前值 | 进化后值 |
|------|--------|----------|
| 置信度门槛 | {thresholds.get('confidence_threshold', 0.45):.2f} | {evolved.get('thresholds', {}).get('confidence_threshold', 0.45):.2f} |
| 日亏损限制 | {thresholds.get('daily_loss_limit', -100):.0f} U | {evolved.get('thresholds', {}).get('daily_loss_limit', -100):.0f} U |
| 最大连续亏损 | {thresholds.get('max_consecutive_losses', 5)} 次 | {evolved.get('thresholds', {}).get('max_consecutive_losses', 5)} 次 |

### 🔧 本轮调整
{chr(10).join(f"- {a}" for a in evolved.get('adjustments', [])) if evolved.get('adjustments') else '- 无调整'}

### 🧠 教训总结
{chr(10).join(f"- {l}" for l in evolution.get('lessons', [])[-5:]) if evolution.get('lessons') else '- 暂无'}

### 📝 建议
1. 根据胜率和盈亏比动态调整置信度门槛，平衡开仓频率与成功率
2. 定期重训两仪引擎和QMM模型，保持预测准确性
3. 关注连续亏损次数，及时触发熔断机制

---
- 监控时间: {_fmt_ts(_now())}
- 自进化次数: {evolution.get('evolution_count', 0)}
- 本报告由 yijing_monitor.py 自动生成
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
    parser = argparse.ArgumentParser(description="易经推理交易自动化监控")
    parser.add_argument("--check-only", action="store_true", help="仅检查状态不触发执行")
    parser.add_argument("--evolve-only", action="store_true", help="仅执行自进化和PR评论")
    args = parser.parse_args()

    _log("=" * 60)
    _log(f"易经推理监控启动 | {_fmt_ts(_now())}")
    _log("=" * 60)

    # ── 1. 检查健康状态 ──
    healthy, status, detail = check_yijing_health()
    _log(f"\n[易经推理] 状态: {'✅ 正常' if healthy else '⚠️ 异常'} | {status}")

    if not healthy and not args.evolve_only:
        if not args.check_only:
            _log("[AutoMonitor] 易经推理异常，触发恢复执行...")
            run_polling_trader()
        else:
            _log("[AutoMonitor] --check-only 模式，跳过执行")

    # ── 2. 自进化学习 ──
    evolution, perf, evolved = run_evolution()

    # ── 3. PR 评论 ──
    post_pr_comment(detail, evolution, perf, evolved)

    # ── 4. 飞书状态汇总 ──
    _send_feishu_status_summary(healthy, status, detail)

    _log("\n" + "=" * 60)
    _log(f"易经推理监控完成 | {_fmt_ts(_now())}")
    _log("=" * 60)

if __name__ == "__main__":
    main()