"""
Dream OS Daily Briefing 生成器 (F7.2)

Muse 启发：用户设置一次任务后，AI 持续交付简报。
每日固定时段推送：盘前综述(8:00) / 盘中异动(13:00) / 盘后总结(21:00)

阶段 A 实现：聚合 scheduler 执行历史 + 系统状态快照生成简报
阶段 C 完善：接入 BCRM2.0 / BDSM / S3/S4 / 持仓 PnL 真实数据源

数据持久化: scheduler_data/briefings/{date}_{type}.json
FAIL-OPEN: 任何数据源失败不阻塞简报生成，对应字段标记为 unavailable
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# F7.5: 产物中台归一存储 (FAIL-OPEN: 导入失败不影响简报生成)
try:
    from dreamos.core.artifact import ArtifactStore, ArtifactType
    _ARTIFACT_STORE = ArtifactStore()
except Exception:
    _ARTIFACT_STORE = None


class BriefingType:
    PRE_MARKET = "pre_market"      # 盘前综述 (8:00)
    MID_MARKET = "mid_market"      # 盘中异动 (13:00)
    POST_MARKET = "post_market"    # 盘后总结 (21:00)

    @classmethod
    def from_hour(cls, hour: int) -> str:
        """根据小时推断简报类型"""
        if 6 <= hour < 12:
            return cls.PRE_MARKET
        elif 12 <= hour < 17:
            return cls.MID_MARKET
        else:
            return cls.POST_MARKET


class DailyBriefing:
    """每日简报生成器

    聚合多源数据生成结构化简报，持久化到 scheduler_data/briefings/
    """

    def __init__(self, data_dir: Optional[Path] = None):
        if data_dir is None:
            data_dir = Path(__file__).resolve().parent / "scheduler_data"
        self.data_dir = Path(data_dir)
        self.briefings_dir = self.data_dir / "briefings"
        self.briefings_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, briefing_type: Optional[str] = None) -> Dict[str, Any]:
        """生成一份简报

        Args:
            briefing_type: 简报类型 (pre_market/mid_market/post_market)，
                          None 则根据当前小时推断

        Returns:
            简报 dict，结构见 _build_briefing
        """
        now = datetime.now()
        if briefing_type is None:
            briefing_type = BriefingType.from_hour(now.hour)

        logger.info(f"生成 {briefing_type} 简报 @ {now.isoformat()}")

        briefing = self._build_briefing(briefing_type, now)
        self._save(briefing)
        return briefing

    def _build_briefing(self, briefing_type: str, now: datetime) -> Dict[str, Any]:
        """构建简报内容（FAIL-OPEN: 各数据源独立 try/except）"""
        return {
            "id": f"briefing_{now.strftime('%Y%m%d_%H%M%S')}",
            "type": briefing_type,
            "title": self._title_for(briefing_type, now),
            "generated_at": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            # ── 系统状态快照 ──
            "system_status": self._collect_system_status(),
            # ── 调度器执行历史（最近 N 条） ──
            "scheduler_history": self._collect_scheduler_history(limit=20),
            # ── 简报正文（阶段 A: 基于系统状态生成摘要文本） ──
            "summary": self._generate_summary(briefing_type, now),
            # ── 真实数据源（阶段 C 逐步接入） ──
            "bcrm2_status": self._collect_bcrm2_status(),
            "bdsm_status": self._collect_bdsm_status(),
            "s3_s4_signals": {"status": "unavailable", "note": "待调研战略层 S3/S4 信号入口"},
            "positions": self._collect_positions(),
        }

    # ── 数据源采集（FAIL-OPEN） ────────────────

    def _collect_system_status(self) -> Dict[str, Any]:
        """采集系统状态快照"""
        try:
            jobs_file = self.data_dir / "scheduler_jobs.json"
            if not jobs_file.exists():
                return {"status": "no_jobs_config"}
            with open(jobs_file) as f:
                jobs = json.load(f)
            enabled = [j for j in jobs if j.get("enabled")]
            return {
                "status": "ok",
                "total_jobs": len(jobs),
                "enabled_jobs": len(enabled),
                "job_types": list({j.get("job_type", "scan") for j in jobs}),
                "jobs": [
                    {"name": j["name"], "cron": j.get("cron_expr"), "enabled": j.get("enabled", True)}
                    for j in jobs
                ],
            }
        except Exception as e:
            logger.warning(f"采集系统状态失败: {e}")
            return {"status": "error", "error": str(e)}

    def _collect_bcrm2_status(self) -> Dict[str, Any]:
        """采集 BCRM2.0 推理绩效（读取 memory_l4/stats/daily_stats.json 最新日）"""
        try:
            stats_dir = (
                Path(__file__).resolve().parent.parent.parent.parent
                / "11-易经推理系统" / ".workbuddy" / "memory_l4" / "stats"
            )
            stats_file = stats_dir / "daily_stats.json"
            if not stats_file.exists():
                return {"status": "unavailable", "note": "daily_stats.json 不存在"}
            with open(stats_file, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or not data:
                return {"status": "unavailable", "note": "daily_stats.json 为空"}
            latest_date = max(data.keys())
            day = data[latest_date]
            return {
                "status": "ok",
                "date": latest_date,
                "total_trades": day.get("total_trades", 0),
                "win_trades": day.get("win_trades", 0),
                "loss_trades": day.get("loss_trades", 0),
                "total_pnl": round(day.get("total_pnl", 0), 4),
                "win_rate": round(day.get("win_rate", 0), 4),
                "profit_factor": round(day.get("profit_factor", 0), 4),
                "max_drawdown": round(day.get("max_drawdown", 0), 6),
                "ending_equity": round(day.get("ending_equity", 0), 2),
                "current_consecutive_losses": day.get("current_consecutive_losses", 0),
            }
        except Exception as e:
            logger.warning(f"采集 BCRM2.0 状态失败: {e}")
            return {"status": "error", "error": str(e)}

    def _collect_positions(self) -> Dict[str, Any]:
        """采集持仓状态（从 BDSM 快照的 scaling_plan 提取有持仓的币种）"""
        try:
            bdsm_dir = (
                Path(__file__).resolve().parent.parent.parent.parent
                / "11-易经推理系统" / ".workbuddy" / "bdsm"
            )
            snapshots = sorted(bdsm_dir.glob("bdsm_snapshot_*.json"), reverse=True)
            if not snapshots:
                return {"status": "unavailable", "note": "无 BDSM 快照"}
            with open(snapshots[0], encoding="utf-8") as f:
                data = json.load(f)
            coins = data.get("coins", {})
            positions = []
            for symbol, info in coins.items():
                if not isinstance(info, dict):
                    continue
                sp = info.get("scaling_plan") or {}
                accumulated = sp.get("accumulated_notional", 0) or 0
                if accumulated > 0:
                    positions.append({
                        "symbol": symbol,
                        "accumulated_notional": round(accumulated, 2),
                        "remaining_budget": round(sp.get("remaining_budget", 0) or 0, 2),
                        "target_notional": round(sp.get("target_notional_usdt", 0) or 0, 2),
                        "avg_entry_price": sp.get("avg_entry_price", 0),
                        "exit_action": info.get("exit_action", "NONE"),
                    })
            positions.sort(key=lambda x: x["accumulated_notional"], reverse=True)
            total_notional = round(sum(p["accumulated_notional"] for p in positions), 2)
            return {
                "status": "ok",
                "snapshot_date": data.get("snapshot_date"),
                "total_positions": len(positions),
                "total_notional": total_notional,
                "positions": positions,
            }
        except Exception as e:
            logger.warning(f"采集持仓状态失败: {e}")
            return {"status": "error", "error": str(e)}

    def _collect_bdsm_status(self) -> Dict[str, Any]:
        """采集 BDSM 出场巡检快照（读取最新 bdsm_snapshot_YYYYMMDD.json）"""
        try:
            bdsm_dir = Path(__file__).resolve().parent.parent.parent.parent / "11-易经推理系统" / ".workbuddy" / "bdsm"
            if not bdsm_dir.exists():
                return {"status": "unavailable", "note": "BDSM 快照目录不存在"}
            snapshots = sorted(bdsm_dir.glob("bdsm_snapshot_*.json"), reverse=True)
            if not snapshots:
                return {"status": "unavailable", "note": "无 BDSM 快照文件"}
            latest = snapshots[0]
            with open(latest, encoding="utf-8") as f:
                data = json.load(f)
            coins = data.get("coins", {})
            # 提取每个币种的关键指标
            coin_summaries = []
            for symbol, info in coins.items():
                if not isinstance(info, dict):
                    continue
                coin_summaries.append({
                    "symbol": symbol,
                    "confidence": info.get("confidence"),
                    "score": info.get("score"),
                    "rank": info.get("rank"),
                    "phase": info.get("phase"),
                    "direction_constraint": info.get("direction_constraint"),
                    "exit_action": info.get("exit_action"),
                    "exit_triggers": info.get("exit_triggers", []),
                })
            # 按 score 降序
            coin_summaries.sort(key=lambda x: x.get("score") or 0, reverse=True)
            return {
                "status": "ok",
                "snapshot_date": data.get("snapshot_date"),
                "generated_at": data.get("generated_at"),
                "total_coins": len(coin_summaries),
                "top5": coin_summaries[:5],
                "exit_signals": [c for c in coin_summaries if c.get("exit_action") != "NONE"],
            }
        except Exception as e:
            logger.warning(f"采集 BDSM 状态失败: {e}")
            return {"status": "error", "error": str(e)}

    def _collect_scheduler_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """采集最近调度执行历史"""
        try:
            history_file = self.data_dir / "scheduler_history.json"
            if not history_file.exists():
                return []
            with open(history_file) as f:
                history = json.load(f)
            return history[-limit:]
        except Exception as e:
            logger.warning(f"采集调度历史失败: {e}")
            return []

    # ── 简报正文生成 ──────────────────────────

    def _title_for(self, briefing_type: str, now: datetime) -> str:
        date_str = now.strftime("%Y-%m-%d")
        titles = {
            BriefingType.PRE_MARKET: f"盘前综述 · {date_str}",
            BriefingType.MID_MARKET: f"盘中异动 · {date_str}",
            BriefingType.POST_MARKET: f"盘后总结 · {date_str}",
        }
        return titles.get(briefing_type, f"每日简报 · {date_str}")

    def _generate_summary(self, briefing_type: str, now: datetime) -> str:
        """生成简报摘要文本（阶段 A: 基于系统状态）"""
        sys_status = self._collect_system_status()
        history = self._collect_scheduler_history(limit=5)

        lines = []
        if briefing_type == BriefingType.PRE_MARKET:
            lines.append("【盘前综述】")
            lines.append(f"生成时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")
            lines.append("")
            lines.append("系统就绪状态:")
            if sys_status.get("status") == "ok":
                lines.append(f"  - 已启用定时任务: {sys_status.get('enabled_jobs', 0)}/{sys_status.get('total_jobs', 0)}")
                lines.append(f"  - 任务类型: {', '.join(sys_status.get('job_types', []))}")
            lines.append("")
            lines.append("最近执行记录:")
            if history:
                for h in history:
                    lines.append(f"  - {h.get('timestamp', '?')} {h.get('symbol', '')} {h.get('action', '')}")
            else:
                lines.append("  (暂无执行记录)")
            lines.append("")
            lines.append("注: BCRM2.0/BDSM/S3-S4 真实信号将在阶段 C 接入。")

        elif briefing_type == BriefingType.MID_MARKET:
            lines.append("【盘中异动】")
            lines.append(f"生成时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")
            lines.append("")
            if history:
                lines.append("近 5 条执行记录:")
                for h in history:
                    lines.append(f"  - {h.get('timestamp', '?')} {h.get('symbol', '')} {h.get('action', '')}")
            else:
                lines.append("(暂无执行记录)")
            lines.append("")
            lines.append("注: BDSM 出场巡检/止损触发 将在阶段 C 接入。")

        else:  # post_market
            lines.append("【盘后总结】")
            lines.append(f"生成时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")
            lines.append("")
            if sys_status.get("status") == "ok":
                lines.append(f"今日定时任务执行: {sys_status.get('enabled_jobs', 0)} 个启用")
            if history:
                lines.append(f"最近执行记录数: {len(history)}")
            lines.append("")
            lines.append("注: 持仓 PnL/自进化每日采纳 将在阶段 C 接入。")

        return "\n".join(lines)

    # ── 持久化 ────────────────────────────────

    def _save(self, briefing: Dict[str, Any]) -> None:
        """持久化简报到 scheduler_data/briefings/{date}_{type}.json
        F7.5: 同步写入产物中台 (artifact_type=briefing)
        """
        date_str = briefing["date"]
        btype = briefing["type"]
        filename = f"{date_str}_{btype}.json"
        filepath = self.briefings_dir / filename
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(briefing, f, indent=2, ensure_ascii=False)
            logger.info(f"简报已持久化: {filepath}")
        except Exception as e:
            logger.error(f"简报持久化失败: {e}")

        # F7.5: 写入产物中台 (FAIL-OPEN)
        if _ARTIFACT_STORE is not None:
            try:
                aid = _ARTIFACT_STORE.save(
                    artifact_type=ArtifactType.BRIEFING,
                    title=briefing.get("title", f"{date_str} {btype}"),
                    data=briefing,
                    tags=["daily_briefing", btype],
                    source="daily_briefing.py",
                    summary=briefing.get("summary", ""),
                    artifact_id=briefing.get("id"),
                )
                logger.info(f"简报已写入产物中台: {aid}")
            except Exception as e:
                logger.warning(f"简报写入产物中台失败 (不影响主流程): {e}")

    # ── 查询接口（供前端 API 调用） ────────────

    def list_briefings(self, limit: int = 50) -> List[Dict[str, Any]]:
        """列出所有简报（按文件名倒序 = 时间倒序）"""
        try:
            files = sorted(self.briefings_dir.glob("*.json"), reverse=True)
            result = []
            for f in files[:limit]:
                try:
                    with open(f, encoding="utf-8") as fh:
                        result.append(json.load(fh))
                except Exception:
                    continue
            return result
        except Exception as e:
            logger.warning(f"列出简报失败: {e}")
            return []

    def get_briefing(self, briefing_id: str) -> Optional[Dict[str, Any]]:
        """按 ID 获取单条简报"""
        try:
            for f in self.briefings_dir.glob("*.json"):
                try:
                    with open(f, encoding="utf-8") as fh:
                        b = json.load(fh)
                        if b.get("id") == briefing_id:
                            return b
                except Exception:
                    continue
            return None
        except Exception as e:
            logger.warning(f"获取简报失败: {e}")
            return None


def run_daily_briefing(briefing_type: Optional[str] = None) -> Dict[str, Any]:
    """scheduler 调用入口：生成一份简报"""
    generator = DailyBriefing()
    return generator.generate(briefing_type=briefing_type)


if __name__ == "__main__":
    # 手动测试: python -m dreamos.cli.daily_briefing
    import argparse
    parser = argparse.ArgumentParser(description="生成每日简报")
    parser.add_argument("--type", choices=["pre_market", "mid_market", "post_market"],
                        default=None, help="简报类型 (默认按当前小时推断)")
    args = parser.parse_args()
    b = run_daily_briefing(args.type)
    filename = f"{b['date']}_{b['type']}.json"
    print(f"已生成简报: {b['id']} ({b['title']})")
    print(f"持久化路径: {Path(__file__).resolve().parent / 'scheduler_data' / 'briefings' / filename}")
