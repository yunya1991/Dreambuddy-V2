#!/usr/bin/env python3
"""
监控适配器模块
为每个系统提供监控适配接口
"""
import json
import os
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Optional

from monitor_core import MonitorResult, MonitorStatus, load_json


class YijingAdapter:
    """易经推理系统监控适配器"""

    # 措施3：BCRM2.0 降级/失败关键字（用于扫描 polling_trader 日志）
    BCRM2_FAILURE_KEYWORDS = (
        "BCRM2.0 训练失败",
        "BCRM2.0 运行异常",
        "BCRM2.0 推理失败",
        "BCRM2.0 启动健康检查失败",
        "降级到 BCRM 1.0",
        "降级回退到 BCRM 1.0",
    )

    def __init__(self, system_name: str, config: Dict):
        self.system_name = system_name
        self.config = config
        self.base_dir = Path(config["base_dir"])
        self.max_idle_minutes = config.get("max_idle_minutes", 30)

    def check_health(self) -> MonitorResult:
        heartbeat_file = self.base_dir / ".workbuddy" / "memory_l4" / "guardian" / "heartbeat.json"
        risk_file = self.base_dir / ".workbuddy" / "memory_l4" / "risk" / "risk_state.json"
        stat_file = self.base_dir / ".workbuddy" / "memory_l4" / "stats" / "performance.json"

        heartbeat = load_json(heartbeat_file, {})
        risk = load_json(risk_file, {})
        perf = load_json(stat_file, {})

        now = datetime.now(timezone.utc).timestamp()
        last_heartbeat = heartbeat.get("ts", heartbeat.get("timestamp", 0))
        idle_minutes = (now - last_heartbeat) / 60 if last_heartbeat else float("inf")

        # 措施3：BCRM2.0 健康自检（日志扫描 + 模型缓存检查）
        bcrm2_status = self._check_bcrm2_health()

        detail = {
            "pid": heartbeat.get("pid"),
            "status": heartbeat.get("status"),
            "idle_minutes": round(idle_minutes, 1),
            "case_count": heartbeat.get("case_count", 0),
            "trading_halted": risk.get("trading_halted", False),
            "consecutive_losses": risk.get("consecutive_losses", 0),
            "total_trades": perf.get("total_trades", 0),
            "win_rate": perf.get("win_rate", 0),
            "bcrm2_status": bcrm2_status["status"],
            "bcrm2_detail": bcrm2_status["detail"],
        }

        # 优先级1：交易暂停（最严重）
        if risk.get("trading_halted", False):
            return MonitorResult(
                self.system_name,
                MonitorStatus.CRITICAL,
                f"交易暂停: {risk.get('halt_reason', '未知')}",
                detail,
            )

        # 优先级2：心跳超时
        if idle_minutes > self.max_idle_minutes:
            return MonitorResult(
                self.system_name,
                MonitorStatus.CRITICAL,
                f"心跳超时！已空闲 {idle_minutes:.0f} 分钟",
                detail,
            )

        # 优先级3：进程状态异常
        if heartbeat.get("status") in ("error", "stopped"):
            return MonitorResult(
                self.system_name,
                MonitorStatus.CRITICAL,
                f"进程状态异常: {heartbeat.get('status')}",
                detail,
            )

        # 优先级4：BCRM2.0 健康检查（措施3）
        if bcrm2_status["status"] == "critical":
            return MonitorResult(
                self.system_name,
                MonitorStatus.CRITICAL,
                f"BCRM2.0 异常: {bcrm2_status['detail']}",
                detail,
            )
        if bcrm2_status["status"] == "warning":
            return MonitorResult(
                self.system_name,
                MonitorStatus.WARNING,
                f"BCRM2.0 警告: {bcrm2_status['detail']}",
                detail,
            )

        return MonitorResult(
            self.system_name,
            MonitorStatus.HEALTHY,
            f"心跳正常，空闲 {idle_minutes:.0f} 分钟，案例 {heartbeat.get('case_count', 0)} 个 | BCRM2.0: {bcrm2_status['detail']}",
            detail,
        )

    def _check_bcrm2_health(self) -> Dict:
        """措施3：BCRM2.0 健康自检

        通过两个维度评估 BCRM2.0 健康状态：
        1. 扫描 polling_trader 当天日志，查找降级/失败关键字
        2. 检查 bcrm2_models 模型缓存目录的新鲜度

        Returns:
            {"status": "healthy"|"warning"|"critical", "detail": str}
        """
        today_str = datetime.now().strftime("%Y%m%d")
        log_file = self.base_dir / "data" / "polling_trader" / f"trader_{today_str}.jsonl"
        models_dir = self.base_dir / "data" / "bcrm2_models"

        # 维度1：扫描当天日志中的 BCRM2.0 失败/降级记录
        failure_count = 0
        latest_failure = ""
        if log_file.exists():
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    # 只读最后 500 行避免大日志内存问题
                    lines = f.readlines()[-500:]
                for line in lines:
                    try:
                        entry = json.loads(line.strip())
                        msg = entry.get("msg", "")
                        if any(kw in msg for kw in self.BCRM2_FAILURE_KEYWORDS):
                            failure_count += 1
                            latest_failure = msg
                    except Exception:
                        continue
            except Exception:
                pass

        # 维度2：检查模型缓存目录
        model_files = []
        if models_dir.exists():
            try:
                model_files = list(models_dir.glob("*"))
            except Exception:
                pass

        # 综合判定
        if failure_count > 0:
            # 当天有降级/失败记录 — critical
            snippet = latest_failure[:80] if latest_failure else "未知"
            return {
                "status": "critical",
                "detail": f"当天检测到 {failure_count} 次 BCRM2.0 降级/失败 | 最近: {snippet}",
            }

        if not model_files:
            # 没有失败记录但模型缓存目录为空/不存在 — warning
            # 可能是首次启动未训练，或模型缓存被清理
            return {
                "status": "warning",
                "detail": "BCRM2.0 模型缓存目录为空 (可能未训练或首次启动)",
            }

        # 检查模型文件新鲜度（最新修改时间）
        try:
            latest_mtime = max(f.stat().st_mtime for f in model_files if f.is_file())
            age_hours = (datetime.now().timestamp() - latest_mtime) / 3600
            if age_hours > 48:
                return {
                    "status": "warning",
                    "detail": f"BCRM2.0 模型缓存已 {age_hours:.0f} 小时未更新 (共 {len(model_files)} 个文件)",
                }
            return {
                "status": "healthy",
                "detail": f"模型缓存正常 ({len(model_files)} 个文件，{age_hours:.1f}h 前更新)",
            }
        except Exception:
            return {
                "status": "healthy",
                "detail": f"模型缓存存在 ({len(model_files)} 个文件)",
            }

    def get_performance(self) -> Dict:
        perf_file = self.base_dir / ".workbuddy" / "memory_l4" / "stats" / "performance.json"
        perf = load_json(perf_file, {})
        return {
            "total_trades": perf.get("total_trades", 0),
            "win_rate": perf.get("win_rate", 0),
            "total_pnl": perf.get("total_pnl", 0),
            "sharpe": perf.get("sharpe_ratio", 0),
            "max_drawdown": perf.get("max_drawdown", 0),
        }

    def get_trading_stats(self) -> Dict:
        risk_file = self.base_dir / ".workbuddy" / "memory_l4" / "risk" / "risk_state.json"
        risk = load_json(risk_file, {})
        return {
            "trading_halted": risk.get("trading_halted", False),
            "consecutive_losses": risk.get("consecutive_losses", 0),
            "daily_pnl": risk.get("daily_pnl", 0),
            "positions": risk.get("active_positions", 0),
        }

    def get_risk_status(self) -> Dict:
        risk_file = self.base_dir / ".workbuddy" / "memory_l4" / "risk" / "risk_state.json"
        risk = load_json(risk_file, {})
        return {
            "halted": risk.get("trading_halted", False),
            "consecutive_losses": risk.get("consecutive_losses", 0),
            "max_consecutive_losses": 5,
            "status": "正常" if not risk.get("trading_halted") else "暂停",
        }

    def get_core_metrics(self) -> Dict:
        heartbeat_file = self.base_dir / ".workbuddy" / "memory_l4" / "guardian" / "heartbeat.json"
        heartbeat = load_json(heartbeat_file, {})
        return {
            "pid": heartbeat.get("pid"),
            "status": heartbeat.get("status", "unknown"),
            "model_version": "BCRM 2.0",
            "confidence_threshold": 0.60,
            "margin_mode": "isolated",
            "monitored_coins": 29,
            "interval_seconds": 3600,
        }


class V15Adapter:
    """V15经典马丁策略监控适配器"""

    def __init__(self, system_name: str, config: Dict):
        self.system_name = system_name
        self.config = config
        self.base_dir = Path(config["base_dir"])
        self.max_idle_minutes = config.get("max_idle_minutes", 240)

    def check_health(self) -> MonitorResult:
        state_file = self.base_dir / "data" / "v15_state.json"

        state = load_json(state_file, {})

        now = datetime.now(timezone.utc).timestamp()

        last_poll_str = state.get("last_poll", "")
        last_action = 0
        try:
            if last_poll_str:
                last_action = datetime.fromisoformat(last_poll_str).timestamp()
        except Exception:
            pass

        idle_minutes = (now - last_action) / 60 if last_action > 0 else float("inf")

        detail = {
            "total_trades": state.get("total_trades", 0),
            "total_wins": state.get("total_wins", 0),
            "win_rate": round(state.get("total_wins", 0) / max(state.get("total_trades", 1), 1) * 100, 1),
            "consecutive_losses": state.get("consecutive_losses", 0),
            "positions": len(state.get("positions", {})),
            "idle_minutes": round(idle_minutes, 1),
            "run_count": state.get("run_count", 0),
        }

        if idle_minutes > self.max_idle_minutes:
            return MonitorResult(
                self.system_name,
                MonitorStatus.CRITICAL,
                f"已空闲 {idle_minutes:.0f} 分钟（阈值 {self.max_idle_minutes} 分钟）",
                detail,
            )

        if state.get("consecutive_losses", 0) >= 5:
            return MonitorResult(
                self.system_name,
                MonitorStatus.WARNING,
                f"连续亏损 {state['consecutive_losses']} 次",
                detail,
            )

        return MonitorResult(
            self.system_name,
            MonitorStatus.HEALTHY,
            f"运行正常，空闲 {idle_minutes:.0f} 分钟，交易 {state.get('total_trades', 0)} 笔",
            detail,
        )

    def get_performance(self) -> Dict:
        state_file = self.base_dir / "data" / "v15_state.json"
        state = load_json(state_file, {})
        total_trades = state.get("total_trades", 0)
        total_wins = state.get("total_wins", 0)
        return {
            "total_trades": total_trades,
            "win_rate": round(total_wins / max(total_trades, 1) * 100, 1),
            "consecutive_losses": state.get("consecutive_losses", 0),
            "positions": len(state.get("positions", {})),
        }

    def get_trading_stats(self) -> Dict:
        state_file = self.base_dir / "data" / "v15_state.json"
        state = load_json(state_file, {})
        return {
            "positions": len(state.get("positions", {})),
            "total_trades": state.get("total_trades", 0),
            "direction": "long-short",
        }

    def get_risk_status(self) -> Dict:
        state_file = self.base_dir / "data" / "v15_state.json"
        state = load_json(state_file, {})
        return {
            "consecutive_losses": state.get("consecutive_losses", 0),
            "max_consecutive_losses": 5,
            "status": "正常" if state.get("consecutive_losses", 0) < 5 else "警告",
        }

    def get_core_metrics(self) -> Dict:
        return {
            "model_version": "V15 Classic Martin",
            "direction_gate": "MA128+BTC趋势",
            "coin_count": 30,
            "margin_mode": "isolated",
            "confidence_threshold": 0.5,
        }


class ScreenAdapter:
    """三屏趋势系统监控适配器"""

    def __init__(self, system_name: str, config: Dict):
        self.system_name = system_name
        self.config = config
        self.base_dir = Path(config["base_dir"])
        self.max_idle_minutes = config.get("max_idle_minutes", 240)

    def check_health(self) -> MonitorResult:
        state_file = self.base_dir / "data" / "screen_trade_state.json"

        state = load_json(state_file, {})

        now = datetime.now(timezone.utc).timestamp()
        last_check = state.get("last_check_ts", 0)
        last_action = state.get("last_action_ts", 0)

        idle_minutes = (now - last_check) / 60 if last_check > 0 else float("inf")

        detail = {
            "active": state.get("active", False),
            "direction": state.get("direction", "NONE"),
            "symbol": state.get("active_symbol", "?"),
            "run_count": state.get("run_count", 0),
            "orch_run_count": state.get("orch_run_count", 0),
            "idle_minutes": round(idle_minutes, 1),
            "trade_history_count": len(state.get("trade_history", [])),
        }

        if idle_minutes > self.max_idle_minutes:
            return MonitorResult(
                self.system_name,
                MonitorStatus.CRITICAL,
                f"已空闲 {idle_minutes:.0f} 分钟（阈值 {self.max_idle_minutes} 分钟）",
                detail,
            )

        return MonitorResult(
            self.system_name,
            MonitorStatus.HEALTHY,
            f"运行正常，空闲 {idle_minutes:.0f} 分钟，活跃交易 {state.get('active', False)}",
            detail,
        )

    def get_performance(self) -> Dict:
        state_file = self.base_dir / "data" / "screen_trade_state.json"
        evolution_file = self.base_dir / "data" / "screen_evolution_state.json"

        state = load_json(state_file, {})
        evolution = load_json(evolution_file, {})

        trades = state.get("trade_history", [])
        closed = [t for t in trades if t.get("action") in ("CLOSE", "TP_HIT", "SL_HIT")]

        return {
            "trade_history_count": len(trades),
            "evolution_count": evolution.get("evolution_count", 0),
            "closed_trades": len(closed),
        }

    def get_trading_stats(self) -> Dict:
        state_file = self.base_dir / "data" / "screen_trade_state.json"
        state = load_json(state_file, {})
        return {
            "active": state.get("active", False),
            "direction": state.get("direction", "NONE"),
            "symbol": state.get("active_symbol", "?"),
            "total_size": state.get("total_size", 0),
        }

    def get_risk_status(self) -> Dict:
        state_file = self.base_dir / "data" / "screen_trade_state.json"
        state = load_json(state_file, {})
        return {
            "addon_pct": state.get("addon_pct", 8.0),
            "tp_pct": state.get("tp_pct", 4.0),
            "vol_mult": state.get("vol_mult", 1.0),
            "status": "正常",
        }

    def get_core_metrics(self) -> Dict:
        return {
            "model_version": "Screen Trend System",
            "strategy": "Three-Screen",
            "ml_model": "LightGBM",
            "screen_count": 3,
            "interval_seconds": 300,
        }


class AgentAAdapter:
    """Agent A 监控适配器"""

    def __init__(self, system_name: str, config: Dict):
        self.system_name = system_name
        self.config = config
        self.base_dir = Path(config["base_dir"])
        self.max_idle_minutes = config.get("max_idle_minutes", 240)

    def check_health(self) -> MonitorResult:
        log_dir = self.base_dir / "logs" / "agent_a"
        mem_file = self.base_dir / "data" / "agent_a_memory.json"

        latest_ts = self._get_latest_log_time(log_dir)
        mem = load_json(mem_file, {})

        now = datetime.now(timezone.utc)
        idle_minutes = (now - latest_ts).total_seconds() / 60 if latest_ts else float("inf")

        detail = {
            "idle_minutes": round(idle_minutes, 1),
            "current_master": mem.get("current_master", "?"),
            "total_lessons": len(mem.get("lessons", [])),
            "last_regime": mem.get("last_regime", "?"),
        }

        if idle_minutes > self.max_idle_minutes:
            return MonitorResult(
                self.system_name,
                MonitorStatus.CRITICAL,
                f"已空闲 {idle_minutes:.0f} 分钟（阈值 {self.max_idle_minutes} 分钟）",
                detail,
            )

        return MonitorResult(
            self.system_name,
            MonitorStatus.HEALTHY,
            f"运行正常，空闲 {idle_minutes:.0f} 分钟，大师: {mem.get('current_master', '?')}",
            detail,
        )

    def _get_latest_log_time(self, log_dir: Path) -> datetime:
        if not log_dir.exists():
            return datetime.min.replace(tzinfo=timezone.utc)
        logs = sorted(log_dir.glob("*.json"), reverse=True)
        if not logs:
            return datetime.min.replace(tzinfo=timezone.utc)
        fname = logs[0].stem
        try:
            if "_" in fname:
                dt = datetime.strptime(fname, "%Y%m%d_%H%M%S")
            elif "-" in fname:
                dt = datetime.strptime(fname, "%Y%m%d-%H%M")
            else:
                mtime = logs[0].stat().st_mtime
                dt = datetime.fromtimestamp(mtime)
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            mtime = logs[0].stat().st_mtime
            return datetime.fromtimestamp(mtime, tz=timezone.utc)

    def get_performance(self) -> Dict:
        return {}

    def get_trading_stats(self) -> Dict:
        return {}

    def get_risk_status(self) -> Dict:
        return {"status": "正常"}

    def get_core_metrics(self) -> Dict:
        mem_file = self.base_dir / "data" / "agent_a_memory.json"
        mem = load_json(mem_file, {})
        return {
            "model_version": "Agent A",
            "current_master": mem.get("current_master", "?"),
            "strategy": "Memory-based Trading",
        }


class AgentBAdapter:
    """Agent B 监控适配器"""

    def __init__(self, system_name: str, config: Dict):
        self.system_name = system_name
        self.config = config
        self.base_dir = Path(config["base_dir"])
        self.max_idle_minutes = config.get("max_idle_minutes", 240)

    def check_health(self) -> MonitorResult:
        log_dir = self.base_dir / "logs" / "agent_b"
        mem_file = self.base_dir / "data" / "agent_b_memory.json"

        latest_ts = self._get_latest_log_time(log_dir)
        mem = load_json(mem_file, {})

        now = datetime.now(timezone.utc)
        idle_minutes = (now - latest_ts).total_seconds() / 60 if latest_ts else float("inf")

        detail = {
            "idle_minutes": round(idle_minutes, 1),
            "total_lessons": len(mem.get("lessons", [])),
            "last_regime": mem.get("last_regime", "?"),
        }

        if idle_minutes > self.max_idle_minutes:
            return MonitorResult(
                self.system_name,
                MonitorStatus.CRITICAL,
                f"已空闲 {idle_minutes:.0f} 分钟（阈值 {self.max_idle_minutes} 分钟）",
                detail,
            )

        return MonitorResult(
            self.system_name,
            MonitorStatus.HEALTHY,
            f"运行正常，空闲 {idle_minutes:.0f} 分钟，教训 {len(mem.get('lessons', []))} 条",
            detail,
        )

    def _get_latest_log_time(self, log_dir: Path) -> datetime:
        if not log_dir.exists():
            return datetime.min.replace(tzinfo=timezone.utc)
        logs = sorted(log_dir.glob("*.json"), reverse=True)
        if not logs:
            return datetime.min.replace(tzinfo=timezone.utc)
        fname = logs[0].stem
        try:
            if "_" in fname:
                dt = datetime.strptime(fname, "%Y%m%d_%H%M%S")
            elif "-" in fname:
                dt = datetime.strptime(fname, "%Y%m%d-%H%M")
            else:
                mtime = logs[0].stat().st_mtime
                dt = datetime.fromtimestamp(mtime)
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            mtime = logs[0].stat().st_mtime
            return datetime.fromtimestamp(mtime, tz=timezone.utc)

    def get_performance(self) -> Dict:
        return {}

    def get_trading_stats(self) -> Dict:
        return {}

    def get_risk_status(self) -> Dict:
        return {"status": "正常"}

    def get_core_metrics(self) -> Dict:
        return {
            "model_version": "Agent B",
            "strategy": "Full Cycle Trading",
        }
