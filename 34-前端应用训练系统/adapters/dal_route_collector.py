"""19-DAL 统一数据层 ma_migration_audit 采集器 — DSH 层原生序列数据源 (P3)。

直接查询 19-DAL 的 ma_migration_audit 审计表,提取 DualWrite/shadow_read/migration_script
调用链作为 node_sequence,专供 DSH 层训练。

设计（SPEC-DSH §1.6,不需要补日志）:
  - ma_migration_audit 表天然记录三类调用链:
    · dual_write    — legacy.execute → new.execute_secondary → audit
    · shadow_read   — legacy.read → new.read → compare → audit
    · migration_script — batch.run → insert_or_ignore → audit
  - 按 category 映射到预定义 node_sequence 模板
  - result(MATCH/DIFF/APPLIED/SKIPPED/FAILED) → outcome_text
  - confidence: MATCH/APPLIED=0.8, DIFF/FAILED=0.3, SKIPPED=0.5
  - 增量采集: 基于 run_at 时间戳
  - FAIL-OPEN: DB 不存在/查询失败返回空列表
"""
import json
import os
import sys
from datetime import datetime
from typing import List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)
_19_DIR = os.path.join(_PROJECT_ROOT, "19-数据访问层")

for _p in [_THIS_DIR, _34_DIR, _19_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase


def _get_db_path() -> str:
    return os.environ.get(
        "DAL_DB_PATH",
        os.path.join(os.environ.get("DATA_DIR", "./data"), "dreambuddy_core.db"),
    )


# category → node_sequence 模板（对应 di.py / import_runner.py 的实际调用链）
_CATEGORY_TEMPLATES = {
    "dual_write": [
        "dual_write.intercept",
        "classify_method",
        "legacy.execute",
        "new.execute_secondary",
        "audit.write",
    ],
    "shadow_read": [
        "dual_write.intercept",
        "classify_method",
        "legacy.read",
        "new.read",
        "shadow_read.compare",
        "audit.write",
    ],
    "migration_script": [
        "import_batch.run",
        "batch.dispatch",
        "insert_or_ignore",
        "audit.write",
    ],
}


def _confidence_from_result(result: str) -> float:
    """根据审计结果派生置信度。"""
    if result in ("MATCH", "APPLIED"):
        return 0.8
    if result in ("DIFF", "FAILED"):
        return 0.3
    if result == "SKIPPED":
        return 0.5
    return 0.4


class DalRouteCollector(TrainingDataProvider):
    """19-DAL ma_migration_audit 采集器。

    查询 ma_migration_audit 审计表,按 category 映射到 node_sequence 模板,
    作为 DSH 层训练数据。
    """

    def __init__(self):
        pass

    def get_source_name(self) -> str:
        return "dal_route"

    def get_quality_threshold(self) -> str:
        return "A"

    def fetch_cases(
        self, limit: int = 100, since: Optional[str] = None
    ) -> List[TrainingCase]:
        """查询 ma_migration_audit 表采集 DAL 调用链序列。

        Args:
            limit: 最大返回数量
            since: 增量采集时间戳(ISO8601),只返回 run_at > since 的记录

        Returns:
            训练案例列表（FAIL-OPEN）
        """
        cases: List[TrainingCase] = []
        # 触发 19-DAL .env 加载（设置 DATA_DIR/DB_BACKEND 等环境变量）
        try:
            import dreambuddy_dal.di  # noqa: F401
        except Exception:
            pass
        db_path = _get_db_path()
        if not os.path.isfile(db_path):
            return cases

        try:
            from dreambuddy_dal.connection import get_sqlite_connection
        except Exception:
            return cases

        # 增量过滤
        since_filter = ""
        params: list = []
        if since:
            try:
                since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
                since_filter = "WHERE run_at > ?"
                params = [since_dt.isoformat()]
            except (ValueError, TypeError):
                pass

        query = (
            f"SELECT category, event_name, entity_key, result, severity, "
            f"details, latency_ms, run_at FROM ma_migration_audit "
            f"{since_filter} ORDER BY run_at DESC LIMIT ?"
        )
        params.append(limit)

        try:
            with get_sqlite_connection(db_path, assert_critical_pragmas=False) as conn:
                rows = conn.execute(query, params).fetchall()
        except Exception:
            return cases

        for row in rows:
            (category, event_name, entity_key, result, severity,
             details_json, latency_ms, run_at) = row

            template = _CATEGORY_TEMPLATES.get(category)
            if not template:
                continue  # 未知 category 跳过

            # migration_script: 用 event_name(batch_id) 替换第 2 节点
            node_seq = list(template)
            if category == "migration_script" and event_name:
                node_seq[1] = f"batch.{event_name}"

            outcome = (result or "UNKNOWN").upper()
            confidence = _confidence_from_result(outcome)

            # 解析 details
            try:
                details = json.loads(details_json) if details_json else {}
            except (json.JSONDecodeError, TypeError):
                details = {}

            cases.append(TrainingCase(
                intent=f"dal_{category}",
                actions=node_seq,
                outcome_text=outcome,
                learned=[f"category={category}", f"result={outcome}",
                         f"severity={severity}"],
                layer_tags=["DSH"],
                quality="A",
                confidence=confidence,
                source="dal_route",
                metadata={
                    "category": category,
                    "event_name": event_name,
                    "entity_key": entity_key,
                    "severity": severity,
                    "latency_ms": latency_ms,
                    "run_at": run_at,
                    "details": details,
                },
            ))

        return cases
