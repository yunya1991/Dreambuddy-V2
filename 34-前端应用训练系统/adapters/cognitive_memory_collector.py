"""认知系统记忆采集器。

批量读取 cognitive_memory.db 的认知记忆（M4⑪ 起经 Memory port bulk-read），
实现 TrainingDataProvider 协议，为主动训练采集器提供认知记忆数据。

设计:
  - Memory port bulk-read（export_entries，无 IPC 开销，不依赖 MCP server 运行）
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
  - layer_tags = ["S", "C"] (认知记忆属反思层)

TDD 阶段路由 (v0.5):
  - RED (失败测试/未实现) → layer_tags=["C"] + metadata.outcome="failure"
    （失败信号驱动 C 层产出纠正类决策 REDO/RETRY，缓解 C 决策单一）
  - GREEN (测试通过/已实现) → layer_tags=["LLM","DSH"] + metadata.outcome="success"
    （成功信号进 LLM success_count + DSH 执行路径）
  - 未命中 → 保持默认 ["S","C"]，outcome 由 quality 派生
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)

from interfaces.training_data_provider import (  # noqa: E402
    TrainingCase,
    TrainingDataProvider,
)

# 默认 DB 路径
_DEFAULT_DB_PATH = os.path.join(_PROJECT_ROOT, "4-MEMORY", "data", "cognitive_memory.db")

# 质量等级优先级（数字越大越好）
_QUALITY_ORDER = {"S": 4, "A": 3, "B": 2, "C": 1, "D": 0}

# TDD 阶段标记（大小写不敏感，用于 RED→C / GREEN→LLM+DSH 路由）
# 说明: 不用裸 "GREEN"（误命中 72 条非 TDD 记录），只取 TDD 定向标记
_TDD_RED_MARKERS = (
    "TDD RED",
    "RED 测试",
    "RED测试",
    "RED 阶段",
    "红灯",
    "未实现",
    "ModuleNotFoundError",
    "测试失败",
    "断言失败",
    "failing test",
)
_TDD_GREEN_MARKERS = (
    "RED→GREEN",
    "RED->GREEN",
    "→GREEN",
    "TDD GREEN",
    "GREEN 阶段",
    "绿灯",
    "测试全过",
    "全部通过",
    "已实现并通过",
    "通过测试",
)


def classify_tdd_phase(content: str) -> Optional[str]:
    """从记忆正文识别 TDD 阶段。

    优先 RED（失败信号对 C 层学习价值更高），其次 GREEN，均不命中返回 None。

    Args:
        content: 记忆正文

    Returns:
        "red" | "green" | None
    """
    if not content:
        return None
    text = content.upper()
    for m in _TDD_RED_MARKERS:
        if m.upper() in text:
            return "red"
    for m in _TDD_GREEN_MARKERS:
        if m.upper() in text:
            return "green"
    return None


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

    def fetch_cases(self, limit: int = 100, since: Optional[str] = None) -> List[TrainingCase]:
        """经 Memory port bulk-read 批量获取 B级以上记忆。

        Args:
            limit: 最大返回数量
            since: 增量采集时间戳(ms 字符串)，None 或 "0" 表示全量

        Returns:
            训练案例列表（FAIL-OPEN：DB 不可用时返回空列表）
        """
        if not os.path.exists(self._db_path):
            return []

        port = None
        try:
            port = self._memory_port()
            since_iso = None
            if since:
                # since 是 ms 时间戳字符串，created_at 是 ISO 格式文本
                since_ts = int(since)
                since_iso = datetime.fromtimestamp(since_ts / 1000, tz=timezone.utc).isoformat()

            res = port.export_entries(
                min_quality=self._quality_threshold, limit=limit, since=since_iso
            )
            rows = res.get("entries", [])
            return [self._convert_memory(r) for r in rows]
        except Exception:
            return []
        finally:
            if port is not None:
                port.close()

    def _memory_port(self) -> Any:
        """构造 Memory port 只读 adapter（函数级 sys.path 注入，禁止模块级）。"""
        if _PROJECT_ROOT not in sys.path:
            sys.path.insert(0, _PROJECT_ROOT)
        from dreambuddy_l0.adapters.cognitive import from_vector_memory

        return from_vector_memory(storage_path=self._db_path)

    @staticmethod
    def _convert_memory(row: Dict[str, Any]) -> TrainingCase:
        """将认知记忆条目（Memory port bulk-read 统一信封）转换为 TrainingCase。"""
        content = row["content"] or ""
        tags_raw = row["tags"] if row["tags"] is not None else []
        try:
            tags = json.loads(tags_raw) if isinstance(tags_raw, str) else tags_raw
        except (json.JSONDecodeError, TypeError):
            tags = []

        # P1: 从 content 结构化前缀 [xxx] 或 tags 提取 intent_type
        intent = CognitiveMemoryCollector._extract_intent(content, tags)

        # TDD 阶段路由: RED→C(failure) / GREEN→LLM+DSH(success) / 未命中→S+C
        tdd_phase = classify_tdd_phase(content)
        if tdd_phase == "red":
            layer_tags = ["C"]
            derived_outcome = "failure"
        elif tdd_phase == "green":
            layer_tags = ["LLM", "DSH"]
            derived_outcome = "success"
        else:
            layer_tags = ["S", "C"]
            derived_outcome = None

        metadata = {
            "id": row["id"] or "",
            "tags": tags,
            "memory_type": row["memory_type"] or "",
            "original_source": row["source"] or "",
            "created_at": row["created_at"] or "",
            "verify_count": row["verify_count"] or 0,
            "level": row["level"] or "observation",
        }
        if tdd_phase:
            metadata["tdd_phase"] = tdd_phase
        if derived_outcome:
            metadata["outcome"] = derived_outcome

        return TrainingCase(
            intent=intent,
            actions=[],
            outcome_text=content,
            learned=[content] if content else [],
            layer_tags=layer_tags,
            quality=row["quality_level"] or "C",
            confidence=row["confidence"] or 0.0,
            source="cognitive",
            metadata=metadata,
        )

    @staticmethod
    def _extract_intent(content: str, tags: list) -> str:
        """从 content 结构化前缀 [xxx] 或 tags 提取简短 intent_type。

        策略:
          1. 解析 content 首行的 [xxx] 标签，取第一个标签
          2. 如无标签，用 tags[0] 作为 intent
          3. 如都无，用 "cognitive_observation"
          4. 长度截断 50 字符（P3 数据质量门控）
        """
        import re

        # 尝试从 content 首行提取 [xxx] 标签
        first_line = content.split("\n")[0] if content else ""
        match = re.match(r"\[([^\]]+)\]", first_line)
        if match:
            intent = match.group(1).strip()
        elif tags and len(tags) > 0:
            # 用第一个 tag 作为 intent
            intent = str(tags[0]).strip()
        else:
            intent = "cognitive_observation"

        # P3: 长度门控 — intent_type 不超过 50 字符
        if len(intent) > 50:
            intent = intent[:50]

        return intent
