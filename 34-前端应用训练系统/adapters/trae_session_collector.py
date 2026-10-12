"""Trae 对话历史采集器。

从本地 Trae session memory（~/.trae-cn/memory/projects/.../session_memory_*.jsonl）
提取多样化的 intent_type（restart/analyze/bugfix/commit/deploy 等），
降低 S 层 RAG检索集中度。

设计:
  - 遍历所有日期目录（YYYYMMDD）下的 session_memory_*.jsonl 文件
  - 解析每行 JSON，提取 intent/actions/outcome/learned 字段
  - 通过关键词分类器将自然语言 intent 映射为标准 intent_type
  - 增量采集: compact_summary_meta.created_at_ms > since
  - FAIL-OPEN: 目录不存在或解析失败时返回空列表

字段映射:
  - intent (自然语言) → classify() → intent_type (标准标签)
  - actions → actions
  - outcome → outcome_text
  - learned → learned
  - message_id → metadata["message_id"]
  - message_summary_time → metadata["message_summary_time"]
  - compact_summary_meta.created_at_ms → metadata["created_at_ms"] (增量采集依据)
  - source = "trae_session"
  - layer_tags = ["S"] (S 层意图识别训练)
  - quality = "B" (Trae 对话历史是实践验证的)
"""
import json
import os
import re
import sys
from typing import List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase

# Trae session memory 默认根目录
_DEFAULT_TRAE_MEMORY_ROOT = os.path.expanduser(
    "~/.trae-cn/memory/projects/"
    "-Users-zhangjiangtao-WorkBuddy-dreambuddy-v2--p2-5f8e8db8067187fd2690"
)

# intent_type 分类规则（关键词优先级从高到低）
# 优先级说明: deploy/commit/restart 等操作类优先匹配，避免被 analyze 覆盖
_INTENT_RULES = [
    ("restart",  [r"重启", r"reload", r"启动服务", r"restart", r"launchd", r"launch"]),
    ("deploy",   [r"部署", r"deploy", r"发布", r"上线", r"publish"]),
    ("commit",   [r"提交", r"commit", r"push", r"git\s"]),
    ("bugfix",   [r"修复", r"解决.*问题", r"fix", r"repair", r"debug", r"排查.*原因", r"红旗"]),
    ("test",     [r"测试", r"验证", r"test", r"verify", r"regression", r"验收"]),
    ("analyze",  [r"检查", r"排查", r"分析", r"评估", r"inspect", r"analyze", r"investigate", r"诊断", r"巡检"]),
    ("research", [r"调研", r"研究", r"research", r"搜索", r"文献", r"review", r"对标"]),
    ("feature",  [r"新增", r"开发", r"实现", r"添加", r"创建", r"create", r"add\s", r"implement", r"build"]),
    ("refactor", [r"重构", r"优化", r"refactor", r"optimize", r"清理", r"simplify", r"治理"]),
]


def classify_intent(intent: str) -> str:
    """将自然语言 intent 映射为标准 intent_type 标签。

    Args:
        intent: Trae session memory 中的自然语言任务描述

    Returns:
        标准化 intent_type（restart/analyze/bugfix/commit/deploy/
        research/feature/test/refactor/general）
    """
    if not intent:
        return "general"
    for label, patterns in _INTENT_RULES:
        for p in patterns:
            if re.search(p, intent, re.IGNORECASE):
                return label
    return "general"


class TraeSessionCollector(TrainingDataProvider):
    """Trae 对话历史采集器。

    从 ~/.trae-cn/memory/projects/.../session_memory_*.jsonl 提取训练案例，
    通过关键词分类器将自然语言 intent 映射为标准 intent_type，
    为 S 层意图识别训练提供多样化的训练数据。
    """

    def __init__(self, memory_root: str = ""):
        self._memory_root = memory_root or _DEFAULT_TRAE_MEMORY_ROOT

    def get_source_name(self) -> str:
        return "trae_session"

    def get_quality_threshold(self) -> str:
        return "B"

    def fetch_cases(
        self, limit: int = 100, since: Optional[str] = None
    ) -> List[TrainingCase]:
        """从 Trae session memory jsonl 批量获取训练案例。

        Args:
            limit: 最大返回数量
            since: 增量采集时间戳（ms 字符串），None 或 "0" 表示全量

        Returns:
            训练案例列表（FAIL-OPEN：目录不存在或解析失败时返回空列表）
        """
        if not os.path.isdir(self._memory_root):
            return []

        since_ms = 0
        if since:
            try:
                since_ms = int(since)
            except (ValueError, TypeError):
                since_ms = 0

        cases: List[TrainingCase] = []
        try:
            for date_dir in sorted(os.listdir(self._memory_root), reverse=True):
                date_path = os.path.join(self._memory_root, date_dir)
                if not os.path.isdir(date_path):
                    continue
                for fname in os.listdir(date_path):
                    if not (fname.startswith("session_memory_") and fname.endswith(".jsonl")):
                        continue
                    fpath = os.path.join(date_path, fname)
                    cases.extend(self._parse_jsonl(fpath, since_ms))
                    if len(cases) >= limit:
                        break
                if len(cases) >= limit:
                    break
        except Exception:
            pass

        return cases[:limit]

    @staticmethod
    def _parse_jsonl(fpath: str, since_ms: int) -> List[TrainingCase]:
        """解析单个 session_memory jsonl 文件。

        Args:
            fpath: jsonl 文件路径
            since_ms: 增量采集阈值（ms 时间戳），0 表示全量

        Returns:
            训练案例列表
        """
        cases: List[TrainingCase] = []
        try:
            with open(fpath, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # 增量过滤: compact_summary_meta.created_at_ms
                    meta = obj.get("compact_summary_meta") or {}
                    created_at_ms = meta.get("created_at_ms", 0)
                    if since_ms and created_at_ms and created_at_ms <= since_ms:
                        continue

                    intent_text = obj.get("intent", "")
                    if not intent_text:
                        continue

                    intent_type = classify_intent(intent_text)
                    actions = obj.get("actions", [])
                    outcome = obj.get("outcome", "")
                    learned = obj.get("learned", [])

                    cases.append(TrainingCase(
                        intent=intent_type,
                        actions=actions,
                        outcome_text=outcome,
                        learned=learned if learned else [],
                        layer_tags=["S"],
                        quality="B",
                        confidence=0.5,
                        source="trae_session",
                        metadata={
                            "message_id": obj.get("message_id", ""),
                            "message_summary_time": obj.get("message_summary_time", ""),
                            "original_intent": intent_text,
                            "created_at_ms": created_at_ms,
                            "session_file": os.path.basename(fpath),
                        },
                    ))
        except Exception:
            pass
        return cases
