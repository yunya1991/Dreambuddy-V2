#!/usr/bin/env python3
"""
易经推理系统 — inspect 诊断命令
借鉴 grok-build 的 grok inspect：把系统内部状态一次性摊开，快速定位问题。

用法:
  python -m scripts.memory_l4.inspect              # 完整诊断（表格输出）
  python -m scripts.memory_l4.inspect --brief      # 摘要模式
  python -m scripts.memory_l4.inspect --json       # JSON 输出
  python -m scripts.memory_l4.inspect --watch 60   # 持续监控
  python -m scripts.memory_l4.inspect --panels system,positions,knowledge  # 指定面板
"""
import argparse
import json
import time
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import sys

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.memory_l4.paths import (
    workspace_root,
    workbuddy_dir,
    memory_l4_dir,
    memory_l4_cases_dir,
    memory_l4_stats_dir,
    memory_l4_reviews_dir,
    memory_l4_distills_dir,
)


@dataclass
class PanelResult:
    panel_id: str
    name: str
    status: str
    summary: str
    details: Dict[str, Any] = field(default_factory=dict)
    checked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class InspectReport:
    def __init__(self, panels: List[PanelResult]):
        self.panels = panels
        self.overall_status = self._compute_overall_status()

    def _compute_overall_status(self) -> str:
        statuses = [p.status for p in self.panels]
        if "error" in statuses:
            return "error"
        if "warn" in statuses:
            return "warn"
        return "ok"

    def to_dict(self) -> Dict:
        return {
            "overall_status": self.overall_status,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "panels": [
                {
                    "panel_id": p.panel_id,
                    "name": p.name,
                    "status": p.status,
                    "summary": p.summary,
                    "details": p.details,
                    "checked_at": p.checked_at,
                }
                for p in self.panels
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_brief(self) -> str:
        lines = [f"整体状态: {self._status_emoji(self.overall_status)} {self.overall_status.upper()}"]
        for p in self.panels:
            emoji = self._status_emoji(p.status)
            lines.append(f"  {emoji} {p.name}: {p.summary}")
        return "\n".join(lines)

    def to_table(self) -> str:
        lines = []
        lines.append("=" * 80)
        lines.append(f"{'易经推理系统诊断报告':^80}")
        lines.append("=" * 80)
        lines.append(f"整体状态: {self._status_emoji(self.overall_status)} {self.overall_status.upper()}")
        lines.append(f"检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("-" * 80)

        for p in self.panels:
            emoji = self._status_emoji(p.status)
            lines.append(f"\n{emoji} [{p.panel_id}] {p.name}")
            lines.append(f"  状态: {p.status.upper()}")
            lines.append(f"  摘要: {p.summary}")
            if p.details:
                lines.append("  详情:")
                for k, v in p.details.items():
                    lines.append(f"    - {k}: {v}")

        lines.append("\n" + "=" * 80)
        return "\n".join(lines)

    @staticmethod
    def _status_emoji(status: str) -> str:
        if status == "error":
            return "❌"
        if status == "warn":
            return "⚠️"
        return "✅"


class BasePanel:
    PANEL_ID = ""
    PANEL_NAME = ""

    def check(self) -> PanelResult:
        raise NotImplementedError


class SystemPanel(BasePanel):
    PANEL_ID = "system"
    PANEL_NAME = "🏛️ 系统状态"

    def check(self) -> PanelResult:
        details = {}
        status = "ok"
        summary = ""

        heartbeat_file = workbuddy_dir() / "memory_l4" / "guardian" / "heartbeat.json"
        if heartbeat_file.exists():
            try:
                with open(heartbeat_file, "r", encoding="utf-8") as f:
                    hb = json.load(f)
                last_ts = hb.get("timestamp", "")
                if last_ts:
                    try:
                        dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                        now = datetime.now(timezone.utc)
                        diff_min = (now - dt).total_seconds() / 60
                        details["last_heartbeat"] = last_ts
                        details["idle_minutes"] = f"{diff_min:.1f}"
                        if diff_min > 30:
                            status = "error"
                            summary = f"心跳超时 ({diff_min:.0f}分钟未更新)"
                        else:
                            summary = f"心跳正常 ({diff_min:.0f}分钟前)"
                    except Exception:
                        status = "warn"
                        summary = "心跳时间格式异常"
            except Exception as e:
                status = "warn"
                summary = f"心跳文件解析失败: {e}"
        else:
            status = "warn"
            summary = "心跳文件不存在"

        pid_file = workbuddy_dir() / "memory_l4" / "guardian" / "pid.txt"
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                details["pid"] = pid
                try:
                    subprocess.run(
                        ["kill", "-0", str(pid)],
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    details["process_alive"] = True
                except subprocess.CalledProcessError:
                    details["process_alive"] = False
                    if status == "ok":
                        status = "warn"
                        summary = f"进程 {pid} 不存在"
            except Exception:
                pass

        cycle_file = workbuddy_dir() / "memory_l4" / "learning" / "scheduler_state.json"
        if cycle_file.exists():
            try:
                with open(cycle_file, "r", encoding="utf-8") as f:
                    cs = json.load(f)
                details["cycle_count"] = cs.get("retrain_count", 0)
            except Exception:
                pass

        if not summary:
            summary = "系统运行正常"

        return PanelResult(
            panel_id=self.PANEL_ID,
            name=self.PANEL_NAME,
            status=status,
            summary=summary,
            details=details,
        )


class PositionsPanel(BasePanel):
    PANEL_ID = "positions"
    PANEL_NAME = "💼 持仓状态"

    def check(self) -> PanelResult:
        details = {}
        status = "ok"
        summary = ""

        local_positions = []
        try:
            from scripts.memory_l4.trading_utils import PositionTracker

            tracker = PositionTracker()
            local_positions = tracker.all_open_positions()
            details["local_position_count"] = len(local_positions)
            if local_positions:
                details["local_positions"] = [
                    {
                        "coin": p.coin,
                        "inst_id": p.inst_id,
                        "direction": p.direction,
                        "entry_price": p.entry_price,
                        "strategy_source": p.strategy_source,
                    }
                    for p in local_positions
                ]
        except Exception as e:
            status = "warn"
            summary = f"本地持仓读取失败: {e}"
            return PanelResult(
                panel_id=self.PANEL_ID,
                name=self.PANEL_NAME,
                status=status,
                summary=summary,
                details=details,
            )

        okx_positions = []
        try:
            from scripts.memory_l4.okx_simulated import OKXSimulatedClient

            client = OKXSimulatedClient()
            coins = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE"]
            for coin in coins:
                inst_id = f"{coin}-USDT-SWAP"
                result = client.get_positions(inst_id)
                if result.get("ok"):
                    for pos in result.get("positions", []):
                        if float(pos["pos"]) > 0:
                            okx_positions.append(
                                {
                                    "inst_id": inst_id,
                                    "direction": pos["pos_side"],
                                    "size": float(pos["pos"]),
                                    "avg_px": float(pos.get("avg_px", 0)),
                                }
                            )
            details["okx_position_count"] = len(okx_positions)
        except Exception as e:
            status = "warn"
            summary = f"OKX持仓读取失败: {e}"

        local_inst_ids = {p.inst_id for p in local_positions}
        okx_inst_ids = {p["inst_id"] for p in okx_positions}

        missing_in_okx = local_inst_ids - okx_inst_ids
        missing_in_local = okx_inst_ids - local_inst_ids

        if missing_in_okx or missing_in_local:
            status = "error"
            summary = "持仓不一致"
            details["missing_in_okx"] = list(missing_in_okx)
            details["missing_in_local"] = list(missing_in_local)
        else:
            summary = f"持仓一致 ({len(local_positions)} 个)"

        return PanelResult(
            panel_id=self.PANEL_ID,
            name=self.PANEL_NAME,
            status=status,
            summary=summary,
            details=details,
        )


class KnowledgePanel(BasePanel):
    PANEL_ID = "knowledge"
    PANEL_NAME = "📦 知识状态"

    def check(self) -> PanelResult:
        details = {}
        status = "ok"
        summary = ""

        cases_dir = memory_l4_cases_dir()
        l4_case_count = len(list(cases_dir.glob("*.json"))) if cases_dir.exists() else 0
        details["l4_case_count"] = l4_case_count

        index_path = workbuddy_dir() / "memory_l4" / "index" / "latest.json"
        cbr_case_count = 0
        index_age_hours = -1
        if index_path.exists():
            try:
                with open(index_path, "r", encoding="utf-8") as f:
                    index = json.load(f)
                cbr_case_count = len(index.get("case_features", {}))
                details["cbr_case_count"] = cbr_case_count

                snapshot_ts = index.get("snapshot_ts", "")
                if snapshot_ts:
                    try:
                        dt = datetime.fromisoformat(snapshot_ts.replace("Z", "+00:00"))
                        now = datetime.now(timezone.utc)
                        index_age_hours = (now - dt).total_seconds() / 3600
                        details["index_age_hours"] = f"{index_age_hours:.1f}"
                    except Exception:
                        pass
            except Exception as e:
                details["index_error"] = str(e)

        details["cbr_case_count"] = cbr_case_count

        kg_triple_count = 0
        try:
            from scripts.memory_l4.kg_store import KGStore

            kg = KGStore()
            stats = kg.get_stats()
            kg_triple_count = stats.get("triple_count", 0)
            details["kg_triple_count"] = kg_triple_count
            details["entity_count"] = stats.get("entity_count", 0)
        except Exception as e:
            details["kg_error"] = str(e)

        if cbr_case_count < 10:
            status = "warn"
            summary = f"CBR案例不足 ({cbr_case_count}个)"
        elif index_age_hours > 24:
            status = "warn"
            summary = f"索引过期 ({index_age_hours:.0f}小时)"
        else:
            summary = f"L4={l4_case_count} CBR={cbr_case_count} KG={kg_triple_count}"

        return PanelResult(
            panel_id=self.PANEL_ID,
            name=self.PANEL_NAME,
            status=status,
            summary=summary,
            details=details,
        )


class ModelsPanel(BasePanel):
    PANEL_ID = "models"
    PANEL_NAME = "🧠 模型状态"

    def _get_bcrm2_models_dir(self) -> Path:
        from pathlib import Path
        import scripts.memory_l4.bcrm2_adapter as _ba
        return Path(_ba.__file__).resolve().parents[1] / "data" / "bcrm2_models"

    def _scan_model_dirs(self, models_dir: Path) -> dict:
        symbols = set()
        timeframes = set()
        total_models = 0
        l1_count = 0
        l2_count = 0
        latest_model = None
        latest_mtime = 0

        if not models_dir.exists():
            return {
                "symbols": [],
                "timeframes": [],
                "total_models": 0,
                "l1_count": 0,
                "l2_count": 0,
                "latest_model": None,
                "latest_train_time": None,
            }

        for item in models_dir.iterdir():
            if item.is_dir() and "_" in item.name:
                parts = item.name.split("_")
                if len(parts) >= 2:
                    symbols.add(parts[0])
                    timeframes.add(parts[1])
                total_models += 1
                l1_path = item / "l1_model.txt"
                l2_path = item / "l2_model.txt"
                if l1_path.exists():
                    l1_count += 1
                    mt = l1_path.stat().st_mtime
                    if mt > latest_mtime:
                        latest_mtime = mt
                        latest_model = item.name
                if l2_path.exists():
                    l2_count += 1

        return {
            "symbols": sorted(symbols),
            "timeframes": sorted(timeframes),
            "total_models": total_models,
            "l1_count": l1_count,
            "l2_count": l2_count,
            "latest_model": latest_model,
            "latest_train_time": datetime.fromtimestamp(latest_mtime).strftime(
                "%Y-%m-%d %H:%M:%S"
            ) if latest_mtime > 0 else None,
        }

    def check(self) -> PanelResult:
        details = {}
        status = "ok"
        summary = ""

        models_dir = self._get_bcrm2_models_dir()
        details["models_dir"] = str(models_dir)
        details["models_dir_exists"] = models_dir.exists()

        scan = self._scan_model_dirs(models_dir)
        details.update(scan)

        if not models_dir.exists() or scan["total_models"] == 0:
            status = "error"
            summary = "模型目录不存在或无模型"
            return PanelResult(
                panel_id=self.PANEL_ID,
                name=self.PANEL_NAME,
                status=status,
                summary=summary,
                details=details,
            )

        if scan["l1_count"] == 0:
            status = "error"
            summary = "无 L1 模型文件"
            return PanelResult(
                panel_id=self.PANEL_ID,
                name=self.PANEL_NAME,
                status=status,
                summary=summary,
                details=details,
            )

        try:
            from scripts.memory_l4.bcrm2.incremental_learner import IncrementalLearner

            il = IncrementalLearner()
            train_data = il._load_training_data()
            if train_data:
                details["training_sample_count"] = len(train_data)
                if len(train_data) < 50:
                    status = "warn"
                    summary = f"训练样本不足 ({len(train_data)}个)"
        except Exception as e:
            details["sample_count_error"] = str(e)

        if not summary:
            summary = (
                f"{scan['l1_count']}个L1模型, {scan['l2_count']}个L2模型, "
                f"{len(scan['symbols'])}币种, {len(scan['timeframes'])}周期"
            )

        return PanelResult(
            panel_id=self.PANEL_ID,
            name=self.PANEL_NAME,
            status=status,
            summary=summary,
            details=details,
        )


class SkillsPanel(BasePanel):
    PANEL_ID = "skills"
    PANEL_NAME = "⚙️ 技能状态"

    def check(self) -> PanelResult:
        details = {}
        status = "ok"
        summary = ""

        skills_dir = workspace_root() / "skills"
        if skills_dir.exists():
            skill_md_files = list(skills_dir.rglob("SKILL.md"))
            details["skill_md_count"] = len(skill_md_files)

            valid_count = 0
            invalid_count = 0
            invalid_skills = []
            for smd in skill_md_files:
                try:
                    content = smd.read_text(encoding="utf-8")
                    if "---\n" in content and "name:" in content:
                        valid_count += 1
                    else:
                        invalid_count += 1
                        invalid_skills.append(str(smd.relative_to(workspace_root())))
                except Exception:
                    invalid_count += 1
                    invalid_skills.append(str(smd.relative_to(workspace_root())))

            details["valid_count"] = valid_count
            details["invalid_count"] = invalid_count
            if invalid_count > 0:
                status = "warn"
                summary = f"{invalid_count} 个 SKILL.md 格式异常"
                if len(invalid_skills) <= 5:
                    details["invalid_skills"] = invalid_skills
            else:
                summary = f"{valid_count} 个技能就绪"
        else:
            status = "warn"
            summary = "skills 目录不存在"

        return PanelResult(
            panel_id=self.PANEL_ID,
            name=self.PANEL_NAME,
            status=status,
            summary=summary,
            details=details,
        )


class RiskPanel(BasePanel):
    PANEL_ID = "risk"
    PANEL_NAME = "💰 风控状态"

    def check(self) -> PanelResult:
        details = {}
        status = "ok"
        summary = ""

        try:
            from scripts.memory_l4.trading_utils import PerformanceTracker

            tracker = PerformanceTracker()
            today_stats = tracker.get_today_stats()
            details["today_pnl"] = today_stats.get("total_pnl", 0)
            details["today_trades"] = today_stats.get("total_trades", 0)
            details["consecutive_losses"] = today_stats.get("current_consecutive_losses", 0)
            details["win_rate"] = today_stats.get("win_rate", 0)

            pnl = today_stats.get("total_pnl", 0)
            if pnl < -50:
                status = "warn"
                summary = f"今日亏损较大 ({pnl:.2f} USDT)"

            consecutive_losses = today_stats.get("current_consecutive_losses", 0)
            if consecutive_losses >= 5:
                status = "error"
                summary = f"连续亏损 {consecutive_losses} 次，已触发熔断"
        except Exception as e:
            status = "warn"
            summary = f"风控状态读取失败: {e}"

        if not summary:
            summary = "风控状态正常"

        return PanelResult(
            panel_id=self.PANEL_ID,
            name=self.PANEL_NAME,
            status=status,
            summary=summary,
            details=details,
        )


class ConnectionsPanel(BasePanel):
    PANEL_ID = "connections"
    PANEL_NAME = "🔗 连接状态"

    def check(self) -> PanelResult:
        details = {}
        status = "ok"
        summary = ""

        okx_ok = False
        try:
            from scripts.memory_l4.okx_simulated import OKXSimulatedClient

            client = OKXSimulatedClient()
            result = client.get_balance()
            if result.get("ok"):
                okx_ok = True
        except Exception as e:
            details["okx_error"] = str(e)

        details["okx_connected"] = okx_ok

        sqlite_ok = False
        try:
            from scripts.memory_l4.kg_store import KGStore

            kg = KGStore()
            kg.get_stats()
            sqlite_ok = True
        except Exception as e:
            details["sqlite_error"] = str(e)

        details["sqlite_connected"] = sqlite_ok

        feishu_ok = True
        try:
            import os

            webhook_url = os.environ.get("FEISHU_WEBHOOK_URL", "")
            if not webhook_url:
                feishu_ok = False
                details["feishu_error"] = "FEISHU_WEBHOOK_URL 未配置"
        except Exception as e:
            feishu_ok = False
            details["feishu_error"] = str(e)

        details["feishu_configured"] = feishu_ok

        if not okx_ok:
            status = "warn"
            summary = "OKX 连接失败"
        elif not sqlite_ok:
            status = "error"
            summary = "SQLite 连接失败"
        elif not feishu_ok:
            status = "info"
            summary = "飞书未配置"
        else:
            summary = "所有连接正常"

        return PanelResult(
            panel_id=self.PANEL_ID,
            name=self.PANEL_NAME,
            status=status,
            summary=summary,
            details=details,
        )


class AlertsPanel(BasePanel):
    PANEL_ID = "alerts"
    PANEL_NAME = "⚠️ 最近告警"

    def check(self) -> PanelResult:
        details = {}
        status = "ok"
        summary = ""

        log_dir = workspace_root() / "data" / "polling_trader"
        today = datetime.now().strftime("%Y%m%d")
        log_file = log_dir / f"trader_{today}.jsonl"

        alerts = []
        if log_file.exists():
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()[-50:]

                for line in reversed(lines):
                    line = line.strip()
                    if line:
                        try:
                            entry = json.loads(line)
                            level = entry.get("level", "").upper()
                            if level in ("WARN", "ERROR"):
                                alerts.append(
                                    {
                                        "ts": entry.get("ts", ""),
                                        "level": level,
                                        "msg": entry.get("msg", "")[:100],
                                    }
                                )
                            if len(alerts) >= 10:
                                break
                        except Exception:
                            pass

                alerts = alerts[::-1]
            except Exception as e:
                details["read_error"] = str(e)

        details["recent_alerts"] = alerts
        details["alert_count"] = len(alerts)

        if len(alerts) > 0:
            error_count = sum(1 for a in alerts if a["level"] == "ERROR")
            warn_count = len(alerts) - error_count
            if error_count > 0:
                status = "warn"
                summary = f"最近有 {error_count} 个 ERROR, {warn_count} 个 WARN"
            else:
                status = "warn"
                summary = f"最近有 {warn_count} 个 WARN"
        else:
            summary = "最近无告警"

        return PanelResult(
            panel_id=self.PANEL_ID,
            name=self.PANEL_NAME,
            status=status,
            summary=summary,
            details=details,
        )


PANEL_REGISTRY = {
    "system": SystemPanel,
    "positions": PositionsPanel,
    "knowledge": KnowledgePanel,
    "models": ModelsPanel,
    "skills": SkillsPanel,
    "risk": RiskPanel,
    "connections": ConnectionsPanel,
    "alerts": AlertsPanel,
}


class SystemInspector:
    def __init__(self):
        self.panels = {name: cls() for name, cls in PANEL_REGISTRY.items()}

    def inspect(self, panel_ids: Optional[List[str]] = None) -> InspectReport:
        if panel_ids:
            selected = [pid for pid in panel_ids if pid in self.panels]
        else:
            selected = list(self.panels.keys())

        results = []
        for pid in selected:
            panel = self.panels[pid]
            try:
                result = panel.check()
            except Exception as e:
                result = PanelResult(
                    panel_id=pid,
                    name=panel.PANEL_NAME,
                    status="error",
                    summary=f"检查异常: {e}",
                    details={"exception": str(e)},
                )
            results.append(result)

        return InspectReport(results)


def main():
    parser = argparse.ArgumentParser(description="易经推理系统诊断工具")
    parser.add_argument(
        "--brief", action="store_true", help="摘要模式输出"
    )
    parser.add_argument(
        "--json", action="store_true", help="JSON 格式输出"
    )
    parser.add_argument(
        "--watch", type=int, default=0, help="持续监控模式，指定刷新间隔(秒)"
    )
    parser.add_argument(
        "--panels", type=str, default="", help="指定检查面板，逗号分隔"
    )

    args = parser.parse_args()

    panel_ids = None
    if args.panels:
        panel_ids = [p.strip() for p in args.panels.split(",")]

    inspector = SystemInspector()

    if args.watch > 0:
        try:
            while True:
                report = inspector.inspect(panel_ids)
                print("\033[H\033[J", end="")
                print(report.to_table())
                print(f"\n下次刷新: {args.watch}秒后 (按 Ctrl+C 退出)")
                time.sleep(args.watch)
        except KeyboardInterrupt:
            print("\n退出监控")
        return

    report = inspector.inspect(panel_ids)

    if args.json:
        print(report.to_json())
    elif args.brief:
        print(report.to_brief())
    else:
        print(report.to_table())

    if report.overall_status == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
