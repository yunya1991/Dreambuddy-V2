#!/usr/bin/env python3
"""
统一监控核心模块
定义监控接口和核心逻辑，各系统通过适配器接入

监控指标:
- 进程状态 (running/stopped/error)
- 心跳时间 (最后活跃时间)
- 交易状态 (持仓数/连续亏损/交易暂停)
- 性能指标 (胜率/盈亏比/夏普比率)
- 模型状态 (版本/加载状态/推理异常)
"""
import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


BASE_DIR = Path(__file__).parent
LOG_DIR = BASE_DIR / "logs"
CONFIG_DIR = BASE_DIR / "config"
LOG_DIR.mkdir(parents=True, exist_ok=True)


class MonitorStatus:
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class MonitorResult:
    def __init__(self, system: str, status: str, message: str, detail: Dict = None):
        self.system = system
        self.status = status
        self.message = message
        self.detail = detail or {}
        self.timestamp = datetime.now(timezone.utc)

    def to_dict(self) -> Dict:
        return {
            "system": self.system,
            "status": self.status,
            "message": self.message,
            "detail": self.detail,
            "timestamp": self.timestamp.isoformat(),
        }

    def is_healthy(self) -> bool:
        return self.status == MonitorStatus.HEALTHY


class MonitorAdapter:
    """监控适配器基类，各系统实现此接口"""

    def __init__(self, system_name: str, config: Dict):
        self.system_name = system_name
        self.config = config
        self.base_dir = Path(config.get("base_dir", "."))
        self.max_idle_minutes = config.get("max_idle_minutes", 30)

    def check_health(self) -> MonitorResult:
        """检查系统健康状态"""
        raise NotImplementedError

    def get_performance(self) -> Dict:
        """获取性能指标"""
        return {}

    def get_trading_stats(self) -> Dict:
        """获取交易统计"""
        return {}

    def get_risk_status(self) -> Dict:
        """获取风险状态"""
        return {}

    def get_core_metrics(self) -> Dict:
        """获取核心运行态指标"""
        return {}


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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fmt_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def _log(msg: str, system: str = "monitor"):
    ts = _fmt_ts(_now())
    line = f"[{ts}] [{system}] {msg}"
    print(line, flush=True)
    log_file = LOG_DIR / f"monitor.log"
    with open(log_file, "a") as f:
        f.write(line + "\n")


class UnifiedMonitor:
    """统一监控管理器"""

    def __init__(self, config_path: Optional[str] = None):
        self.adapters: Dict[str, MonitorAdapter] = {}
        self.config = self._load_config(config_path)
        self._init_adapters()

    def _load_config(self, config_path: Optional[str]) -> Dict:
        if config_path:
            return load_json(Path(config_path))
        default_config = CONFIG_DIR / "monitor_config.json"
        if default_config.exists():
            return load_json(default_config)
        return self._default_config()

    def _default_config(self) -> Dict:
        root = Path(__file__).parent.parent
        return {
            "systems": {
                "yijing": {
                    "enabled": True,
                    "base_dir": str(root / "11-易经推理系统"),
                    "max_idle_minutes": 30,
                    "adapter": "YijingAdapter",
                },
                "v15": {
                    "enabled": True,
                    "base_dir": str(root / "14-V15经典马丁策略"),
                    "max_idle_minutes": 240,
                    "adapter": "V15Adapter",
                },
                "screen": {
                    "enabled": True,
                    "base_dir": str(root / "12-三屏趋势系统"),
                    "max_idle_minutes": 240,
                    "adapter": "ScreenAdapter",
                },
                "agent_a": {
                    "enabled": True,
                    "base_dir": str(root / "experiments" / "ab-trading"),
                    "max_idle_minutes": 240,
                    "adapter": "AgentAAdapter",
                },
                "agent_b": {
                    "enabled": True,
                    "base_dir": str(root / "experiments" / "ab-trading"),
                    "max_idle_minutes": 240,
                    "adapter": "AgentBAdapter",
                },
            },
            "alert": {
                "enabled": True,
                "feishu_enabled": True,
                "alert_on_warning": True,
                "alert_on_critical": True,
                "summary_interval_minutes": 180,
            },
            "scheduler": {
                "enabled": True,
                "interval_minutes": 60,
            },
        }

    def _init_adapters(self):
        from adapters import (
            YijingAdapter, V15Adapter, ScreenAdapter,
            AgentAAdapter, AgentBAdapter,
        )

        adapter_map = {
            "YijingAdapter": YijingAdapter,
            "V15Adapter": V15Adapter,
            "ScreenAdapter": ScreenAdapter,
            "AgentAAdapter": AgentAAdapter,
            "AgentBAdapter": AgentBAdapter,
        }

        for system_name, system_config in self.config.get("systems", {}).items():
            if not system_config.get("enabled", True):
                continue
            adapter_class = adapter_map.get(system_config.get("adapter"))
            if adapter_class:
                try:
                    self.adapters[system_name] = adapter_class(system_name, system_config)
                    _log(f"已加载适配器: {system_name}")
                except Exception as e:
                    _log(f"加载适配器失败 {system_name}: {e}", "error")

    def monitor_all(self) -> Dict[str, MonitorResult]:
        """监控所有已配置系统"""
        results = {}
        for name, adapter in self.adapters.items():
            try:
                result = adapter.check_health()
                results[name] = result
                _log(f"{name}: {result.status} - {result.message}")
            except Exception as e:
                _log(f"{name} 监控异常: {e}", "error")
                results[name] = MonitorResult(
                    name, MonitorStatus.UNKNOWN, f"监控异常: {e}"
                )
        return results

    def get_all_metrics(self) -> Dict[str, Dict]:
        """获取所有系统的核心指标"""
        metrics = {}
        for name, adapter in self.adapters.items():
            try:
                metrics[name] = {
                    "health": adapter.check_health().to_dict(),
                    "performance": adapter.get_performance(),
                    "trading": adapter.get_trading_stats(),
                    "risk": adapter.get_risk_status(),
                    "core": adapter.get_core_metrics(),
                }
            except Exception as e:
                metrics[name] = {"error": str(e)}
        return metrics

    def send_alerts(self, results: Dict[str, MonitorResult]):
        """根据监控结果发送告警"""
        from feishu_alert import (
            notify_heartbeat_timeout,
            notify_trading_halted,
            notify_status_summary,
            notify_system_error,
        )

        alert_config = self.config.get("alert", {})
        if not alert_config.get("enabled", True):
            return

        for name, result in results.items():
            if result.status == MonitorStatus.CRITICAL:
                if "心跳" in result.message or "空闲" in result.message:
                    idle_minutes = result.detail.get("idle_minutes", 0)
                    notify_heartbeat_timeout(name, idle_minutes, self.adapters[name].max_idle_minutes)
                elif "暂停" in result.message:
                    notify_trading_halted(
                        name,
                        result.message,
                        result.detail.get("consecutive_losses", 0),
                        result.detail.get("daily_pnl", 0),
                    )
                else:
                    notify_system_error(name, result.message)

            elif result.status == MonitorStatus.WARNING and alert_config.get("alert_on_warning"):
                notify_status_summary(name, False, result.message, result.detail)

        healthy_count = sum(1 for r in results.values() if r.is_healthy())
        overall_health = healthy_count == len(results)
        overall_status = f"{healthy_count}/{len(results)} 系统正常" if overall_health else f"{len(results)-healthy_count}/{len(results)} 系统异常"
        notify_status_summary("全局", overall_health, overall_status, {
            "系统数": len(results),
            "正常": healthy_count,
            "异常": len(results) - healthy_count,
        })


def main():
    monitor = UnifiedMonitor()
    results = monitor.monitor_all()
    monitor.send_alerts(results)

    print("\n" + "=" * 80)
    print("统一监控报告")
    print("=" * 80)
    for name, result in results.items():
        status_icon = "✅" if result.is_healthy() else "🔴" if result.status == "critical" else "⚠️"
        print(f"\n{status_icon} {name}: {result.status}")
        print(f"   消息: {result.message}")
        if result.detail:
            for k, v in result.detail.items():
                if not isinstance(v, dict):
                    print(f"   {k}: {v}")


if __name__ == "__main__":
    main()
