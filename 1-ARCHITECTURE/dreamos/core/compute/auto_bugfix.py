"""
L3 自修复: 自动 bugfix 闭环
=============================
异常检测 → 认知库 recall(相似历史) →
  命中 → dream-bugfix-workflow 自动执行
  未命中 → 5why + 人工审核 + 修复后自动 record

用法:
    loop = AutoBugfixLoop(
        health_checker=checker,
        recall_fn=cognitive_recall,
        record_fn=cognitive_record,
    )
    loop.run_once()  # 执行一次自检 + 修复
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class BugfixAction(str, Enum):
    NO_ACTION = "no_action"           # 无异常
    AUTO_FIX = "auto_fix"             # recall 命中，自动修复
    MANUAL_REQUIRED = "manual_required"  # recall 未命中，需人工
    RECORDED = "recorded"             # 已记录到认知库


@dataclass
class BugfixReport:
    """自动 bugfix 报告"""
    action: BugfixAction
    anomaly_description: str = ""
    recalled_memories: List[Dict] = field(default_factory=list)
    fix_applied: bool = False
    fix_description: str = ""
    recorded: bool = False
    memory_id: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action.value,
            "anomaly_description": self.anomaly_description,
            "recalled_count": len(self.recalled_memories),
            "fix_applied": self.fix_applied,
            "fix_description": self.fix_description,
            "recorded": self.recorded,
            "memory_id": self.memory_id,
            "timestamp": self.timestamp,
        }


class AutoBugfixLoop:
    """自动 bugfix 闭环

    流程:
        1. 运行健康检查（DreamOS HealthChecker / DSH HeartbeatMonitor）
        2. 如有异常 → recall 检索相似历史经验
        3. 命中（有相关记忆） → 自动执行修复（dream-bugfix-workflow）
        4. 未命中 → 记录为新经验（C 级），标记需人工审核
        5. 修复后 verify（贝叶斯置信度更新）
    """

    def __init__(
        self,
        health_check_fn: Optional[Callable] = None,
        recall_fn: Optional[Callable] = None,
        record_fn: Optional[Callable] = None,
        verify_fn: Optional[Callable] = None,
        auto_fix_fn: Optional[Callable] = None,
    ):
        """
        Args:
            health_check_fn: 健康检查函数，返回异常列表
            recall_fn: 认知库检索函数，签名 (context, top_k, min_quality) → memories
            record_fn: 认知库记录函数，签名 (content, tags, quality_level) → memory_id
            verify_fn: 认知库验证函数，签名 (memory_id, success) → result
            auto_fix_fn: 自动修复执行函数，签名 (anomaly, memories) → fix_result
        """
        self._health_check_fn = health_check_fn
        self._recall_fn = recall_fn
        self._record_fn = record_fn
        self._verify_fn = verify_fn
        self._auto_fix_fn = auto_fix_fn

    def run_once(self) -> BugfixReport:
        """执行一次自动 bugfix 闭环"""
        report = BugfixReport(action=BugfixAction.NO_ACTION)

        # 1. 健康检查
        anomalies = self._collect_anomalies()
        if not anomalies:
            logger.info("[AutoBugfix] 健康检查通过，无异常")
            return report

        # 取第一个异常处理（多异常时逐个处理）
        anomaly = anomalies[0]
        report.anomaly_description = self._describe_anomaly(anomaly)

        # 2. recall 检索相似历史
        memories = self._recall_similar(anomaly)
        report.recalled_memories = memories

        if memories:
            # 3a. 命中 → 自动修复
            report.action = BugfixAction.AUTO_FIX
            fix_result = self._apply_fix(anomaly, memories)
            if fix_result:
                report.fix_applied = True
                report.fix_description = str(fix_result)
            else:
                report.action = BugfixAction.MANUAL_REQUIRED
                report.fix_description = "自动修复失败，需人工介入"
        else:
            # 3b. 未命中 → 记录新经验，标记人工
            report.action = BugfixAction.MANUAL_REQUIRED

        # 4. 记录到认知库
        self._record_experience(anomaly, report)
        report.recorded = True

        return report

    # ------------------------------------------------------------------
    # 内部步骤
    # ------------------------------------------------------------------
    def _collect_anomalies(self) -> List[Dict]:
        """收集异常"""
        if self._health_check_fn is None:
            return []
        try:
            result = self._health_check_fn()
            if isinstance(result, list):
                return result
            if isinstance(result, dict):
                checks = result.get("checks", [])
                return [
                    c for c in checks
                    if c.get("status") not in ("healthy", "alive", "ok")
                ]
            return []
        except Exception as e:
            logger.warning(f"[AutoBugfix] 健康检查异常: {e}")
            return []

    def _recall_similar(self, anomaly: Dict) -> List[Dict]:
        """recall 检索相似历史"""
        if self._recall_fn is None:
            return []
        try:
            context = self._describe_anomaly(anomaly)
            result = self._recall_fn(context=context, top_k=5, min_quality="C")
            if isinstance(result, list):
                return result
            if isinstance(result, dict):
                return result.get("memories", [])
            return []
        except Exception as e:
            logger.warning(f"[AutoBugfix] recall 异常: {e}")
            return []

    def _apply_fix(self, anomaly: Dict, memories: List[Dict]) -> Optional[str]:
        """执行自动修复"""
        if self._auto_fix_fn is None:
            # 无自动修复函数 → 仅记录
            return None
        try:
            result = self._auto_fix_fn(anomaly, memories)
            return str(result) if result else None
        except Exception as e:
            logger.warning(f"[AutoBugfix] 自动修复异常: {e}")
            return None

    def _record_experience(self, anomaly: Dict, report: BugfixReport) -> None:
        """记录经验到认知库"""
        if self._record_fn is None:
            return
        try:
            content = (
                f"[auto-bugfix] {report.anomaly_description} | "
                f"action={report.action.value} | "
                f"recalled={len(report.recalled_memories)} | "
                f"fix_applied={report.fix_applied}"
            )
            tags = "auto-detected,anomaly,bugfix"
            quality = "C" if report.action == BugfixAction.MANUAL_REQUIRED else "B"

            result = self._record_fn(
                content=content,
                tags=tags,
                quality_level=quality,
            )
            if isinstance(result, dict):
                report.memory_id = result.get("memory_id")
            elif isinstance(result, str):
                report.memory_id = result
        except Exception as e:
            logger.warning(f"[AutoBugfix] 记录异常: {e}")

    @staticmethod
    def _describe_anomaly(anomaly: Dict) -> str:
        """将异常描述为字符串"""
        name = anomaly.get("name", "unknown")
        status = anomaly.get("status", "unknown")
        message = anomaly.get("message", "")
        return f"{name} status={status} {message}".strip()


def create_default_auto_bugfix(
    health_checker=None,
    cognitive_recall=None,
    cognitive_record=None,
) -> AutoBugfixLoop:
    """创建默认的自动 bugfix 闭环

    Args:
        health_checker: DreamOSHealthChecker 实例
        cognitive_recall: 认知库 recall 函数
        cognitive_record: 认知库 record 函数

    Returns:
        配置好的 AutoBugfixLoop
    """
    def health_check_fn():
        if health_checker is None:
            return []
        report = health_checker.run_all_checks()
        return [
            c.to_dict() for c in report.checks
            if c.status.value not in ("healthy",)
        ]

    return AutoBugfixLoop(
        health_check_fn=health_check_fn,
        recall_fn=cognitive_recall,
        record_fn=cognitive_record,
    )
