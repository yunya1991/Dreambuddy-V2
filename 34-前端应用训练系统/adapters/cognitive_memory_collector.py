"""认知系统记忆采集器。

直接查询 cognitive_memory.db SQLite 数据库，
实现 TrainingDataProvider 协议，为主动训练采集器提供认知记忆数据。

设计:
  - 直接 sqlite3 查询（无 IPC 开销，不依赖 MCP server 运行）
  - 质量门控: B级以上(S/A/B)直接采集，C/D级跳过
  - 增量采集: created_at > since 的记忆
  - FAIL-OPEN: DB 不可用时返回空列表

字段映射:
  - content → outcome_text (完整内容) + intent (首行截取) + learned ([content])
  - quality_level → quality
  - confidence → confidence
  - tags → metadata["tags"] (JSON解析为list)
  - id → metadata["id"]
  - source = "cognitive" (采集器名称，非原始source)
  - layer_tags = ["C"] (认知记忆属反思层)
"""
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from typing import List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase

# 默认 DB 路径
_DEFAULT_DB_PATH = os.path.join(
    _PROJECT_ROOT, "4-MEMORY", "data", "cognitive_memory.db"
)

# 质量等级优先级（数字越大越好）
_QUALITY_ORDER = {"S": 4, "A": 3, "B": 2, "C": 1, "D": 0}


class CognitiveMemoryCollector(TrainingDataProvider):
    """认知系统记忆采集器。

    从 cognitive_memory.db 查询 B级以上记忆，转换为 TrainingCase。
    C级记忆需 verify 升级后才入库（本采集器跳过C级及以下）。
    """

    def __init__(self, db_path: str = "", quality_threshold: str = "B"):
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._quality_threshold = quality_threshold

    def get_source_name(self) -> str:
        return "cognitive"

    def get_quality_threshold(self) -> str:
        return self._quality_threshold

    def fetch_cases(
        self, limit: int = 100, since: Optional[str] = None
    ) -> List[TrainingCase]:
        """从 cognitive_memory.db 批量获取 B级以上记忆。

        Args:
            limit: 最大返回数量
            since: 增量采集时间戳(ms 字符串)，None 或 "0" 表示全量

        Returns:
            训练案例列表（FAIL-OPEN：DB 不可用时返回空列表）
        """
        if not os.path.exists(self._db_path):
            return []

        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row

            # 查询 B级以上（S/A/B），按 created_at 增量过滤
            sql = (
                "SELECT id, content, quality_level, confidence, tags, "
                "memory_type, source, created_at, verify_count, level "
                "FROM memories "
                "WHERE quality_level IN ('S', 'A', 'B')"
            )
            params = []

            if since:
                # since 是 ms 时间戳字符串，created_at 是 ISO 格式文本
                # 转换 since 为 ISO 格式用于字符串比较
                since_ts = int(since)
                since_iso = datetime.fromtimestamp(
                    since_ts / 1000, tz=timezone.utc
                ).isoformat()
                sql += " AND created_at > ?"
                params.append(since_iso)

            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()
            conn.close()

            return [self._convert_memory(r) for r in rows]
        except Exception:
            return []

    @staticmethod
    def _convert_memory(row: sqlite3.Row) -> TrainingCase:
        """将认知记忆记录转换为 TrainingCase。"""
        content = row["content"] or ""
        tags_raw = row["tags"] or "[]"
        try:
            tags = json.loads(tags_raw) if isinstance(tags_raw, str) else tags_raw
        except (json.JSONDecodeError, TypeError):
            tags = []

        # 从 content 提取 intent（首行或前100字符）
        first_line = content.split("\n")[0][:100] if content else "cognitive_memory"

        return TrainingCase(
            intent=first_line,
            actions=[],
            outcome_text=content,
            learned=[content] if content else [],
            layer_tags=["S", "C"],  # 认知记忆→S层(意图识别)+C层(反思)
            quality=row["quality_level"] or "C",
            confidence=row["confidence"] or 0.0,
            source="cognitive",
            metadata={
                "id": row["id"] or "",
                "tags": tags,
                "memory_type": row["memory_type"] or "",
                "original_source": row["source"] or "",
                "created_at": row["created_at"] or "",
                "verify_count": row["verify_count"] or 0,
                "level": row["level"] or "observation",
            },
        )
